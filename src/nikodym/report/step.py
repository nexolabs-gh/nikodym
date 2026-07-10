"""Paso orquestable de la capa ``report`` (SDD-26 §4/§7/§9; CT-1).

``ReportStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``report``:
exige las ocho cards canónicas de F1, toma un snapshot defensivo del ``Study`` mediante
:class:`~nikodym.report.builder.ReportBuilder`, genera narrativa básica o IA opcional, renderiza el
HTML determinístico y publica el bundle, el manifiesto y el resultado agregado bajo
``domain='report'``.

El módulo evita importar Jinja2, Quarto, SDKs IA o librerías gráficas en import time. El renderer y
los narradores se cargan dentro de ``execute`` para que ``import nikodym.core`` siga liviano y para
que ``nikodym.report`` pueda registrar el step sin activar dependencias opcionales.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TypeAlias

from nikodym.core.audit import AuditEvent
from nikodym.core.exceptions import ArtifactNotFoundError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.report.builder import ReportBuilder
from nikodym.report.config import ReportConfig
from nikodym.report.exceptions import ReportExportError
from nikodym.report.results import AiNarrationBlock, ReportInputBundle, ReportManifest, ReportResult

if TYPE_CHECKING:
    import numpy as np

    from nikodym.core.study import Study
else:
    Study: TypeAlias = Any

__all__ = ["REPORT_ARTIFACTS", "REPORT_REQUIRED_CARDS", "ReportStep"]

REPORT_REQUIRED_CARDS: Final[tuple[ArtifactKey, ...]] = (
    ("eda", "eda_card"),
    ("binning", "binning_card"),
    ("selection", "selection_card"),
    ("model", "model_card"),
    ("scorecard", "card"),
    ("calibration", "card"),
    ("performance", "card"),
    ("stability", "card"),
)
REPORT_ARTIFACTS: Final[tuple[str, ...]] = (
    "input_bundle",
    "manifest",
    "result",
)


@register("standard", domain="report")
class ReportStep(AuditableMixin):
    """Orquesta el reporte canónico F1 y publica ``domain='report'``."""

    name: str = "report"
    requires: tuple[ArtifactKey, ...] = REPORT_REQUIRED_CARDS
    provides: tuple[ArtifactKey, ...] = tuple(("report", key) for key in REPORT_ARTIFACTS)

    def __init__(self, config: ReportConfig) -> None:
        """Construye el paso desde la sección ``ReportConfig`` ya validada.

        ``requires`` se **deriva** del config: se filtra :data:`REPORT_REQUIRED_CARDS` a las cards
        cuyo dominio esté en ``config.sections.required_sections``. Así un pipeline que no corre
        todas las secciones canónicas F1 (p. ej. el preset sin ``eda``) declara sólo las cards que
        realmente exige, y el motor (``_validate_pipeline``/``_check_prerequisites``, CT-1) no
        rechaza el config por un prerequisito inalcanzable. Con el default de ocho secciones el
        comportamiento no cambia: se siguen requiriendo las ocho cards. ``REPORT_REQUIRED_CARDS`` es
        el mapeo canónico dominio→card y no se altera; sólo se filtra.
        """
        self.config = config
        required_domains = set(config.sections.required_sections)
        self.requires = tuple(
            (domain, key) for domain, key in REPORT_REQUIRED_CARDS if domain in required_domains
        )

    @classmethod
    def from_config(cls, cfg: ReportConfig) -> ReportStep:
        """Construye ``ReportStep`` desde ``NikodymConfig.report``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` si un motor futuro lo requiere."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> ReportResult:
        """Ejecuta report determinístico sin consumir ``rng`` y publica tres artefactos."""
        del rng
        cfg = _report_config_from_study(study, fallback=self.config)
        _validate_required_cards(study, self.requires, step_name=self.name)
        _preflight_output_dir(cfg)

        builder = ReportBuilder.from_config(cfg)
        bundle = builder.collect(study)
        sections = builder.build_sections(bundle)
        bundle = bundle.model_copy(update={"sections": sections}, deep=True)

        ai_blocks = _narration_blocks(bundle, cfg)
        renderer = _html_renderer(cfg)
        html = renderer.render(bundle, ai_blocks=ai_blocks)
        manifest = _manifest_for_html(renderer, html, config=cfg)
        result = ReportResult(
            manifest=manifest,
            input_bundle=bundle,
            html_path=_resolve_html_path(cfg, manifest),
            ai_blocks=ai_blocks,
        )
        self._log_report_decisions(bundle=bundle, manifest=manifest, result=result, config=cfg)
        self._publish_artifacts(study, result)
        return result

    def _publish_artifacts(self, study: Study, result: ReportResult) -> None:
        """Publica los tres artefactos estables del dominio ``report``."""
        study.artifacts.set("report", "input_bundle", result.input_bundle.model_copy(deep=True))
        study.artifacts.set("report", "manifest", result.manifest.model_copy(deep=True))
        study.artifacts.set("report", "result", result.model_copy(deep=True))

    def _log_report_decisions(
        self,
        *,
        bundle: ReportInputBundle,
        manifest: ReportManifest,
        result: ReportResult,
        config: ReportConfig,
    ) -> None:
        """Registra decisiones auditables de ensamblado, IA, truncamiento y export."""
        self.log_decision(
            regla="report_sections",
            umbral=tuple(config.sections.required_sections),
            valor={
                "sections": tuple(section.id for section in bundle.sections),
                "missing_sections": bundle.missing_sections,
            },
            accion="renderizar_reporte",
        )
        for table_key, total_rows in _truncated_tables(bundle, config):
            self.log_decision(
                regla="report_table_truncation",
                umbral=config.sections.max_table_rows,
                valor={"table_key": table_key, "total_rows": total_rows},
                accion="truncar_visualizacion",
            )
        _log_ai_decision(self, result.ai_blocks, config)
        if manifest.path:
            self.log_decision(
                regla="report_export_html",
                umbral=config.output_dir,
                valor={"path": manifest.path, "sha256": manifest.sha256},
                accion="publicar_html_local",
            )


def _report_config_from_study(study: Study, *, fallback: ReportConfig) -> ReportConfig:
    """Lee ``NikodymConfig.report`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "report", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, ReportConfig):
        return raw_config
    return ReportConfig.model_validate(raw_config)


def _validate_required_cards(
    study: Study,
    required: tuple[ArtifactKey, ...],
    *,
    step_name: str,
) -> None:
    """Valida CT-1 para llamadas directas a ``execute`` y preserva ``ArtifactNotFoundError``."""
    for domain, key in required:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso '{step_name}' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


def _resolve_html_path(config: ReportConfig, manifest: ReportManifest) -> str | None:
    """Ruta ABSOLUTA/real del HTML escrito, para que consumidores puedan abrirlo (SDD-23 §4.3).

    ``manifest.path`` es el basename determinístico (portable, entra al golden del manifiesto);
    ``ReportResult.html_path`` es la ruta real en disco = ``output_dir/basename``, lo que un
    consumidor como :func:`nikodym.ui.runs._report_html` necesita para leer y persistir el reporte.
    Sin ``output_dir`` no se escribe archivo → ``None`` (reporte sólo-en-memoria).
    """
    output_dir = config.output_dir.strip()
    if not output_dir or not manifest.path:
        return None
    return str(Path(output_dir) / manifest.path)


def _preflight_output_dir(config: ReportConfig) -> None:
    """Falla temprano si el export local configurado no es escribible."""
    output_dir = config.output_dir.strip()
    if not output_dir:
        return
    directory = Path(output_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReportExportError(
            "No se pudo crear el directorio de salida del reporte: dominio='report', "
            f"output_dir='{config.output_dir}', acción='verifique permisos de la ruta padre'."
        ) from exc
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        raise ReportExportError(
            "El directorio de salida del reporte no es escribible: dominio='report', "
            f"output_dir='{config.output_dir}', acción='ajuste permisos o use otra ruta'."
        )


def _narration_blocks(
    bundle: ReportInputBundle,
    config: ReportConfig,
) -> tuple[AiNarrationBlock, ...]:
    """Genera narrativa básica y, si corresponde, la ruta IA con fallback elegante."""
    from nikodym.report.ai import AINarrator, RuleBasedNarrator

    basic = RuleBasedNarrator().narrate(bundle)
    if not config.ai.enabled:
        return basic
    return AINarrator(config.ai).enrich(bundle)


def _html_renderer(config: ReportConfig) -> Any:
    """Construye el renderer HTML cargando Jinja2 sólo cuando ``render`` lo necesite."""
    from nikodym.report.renderer import HtmlReportRenderer

    return HtmlReportRenderer.from_config(config)


def _manifest_for_html(
    renderer: Any,
    html: str,
    *,
    config: ReportConfig,
) -> ReportManifest:
    """Escribe HTML si hay ``output_dir``; si no, usa el manifest canónico del renderer."""
    output_dir = config.output_dir.strip()
    if output_dir:
        manifest = renderer.write(html, output_dir=output_dir)
        return ReportManifest.model_validate(manifest)

    manifest = renderer.build_manifest(html)
    return ReportManifest.model_validate(manifest)


def _truncated_tables(
    bundle: ReportInputBundle,
    config: ReportConfig,
) -> tuple[tuple[str, int], ...]:
    """Detecta tablas cuyo render HTML aplica truncamiento visual explícito."""
    truncated: list[tuple[str, int]] = []
    max_rows = config.sections.max_table_rows
    for key, table in bundle.tables.items():
        row_count = len(getattr(table, "index", ()))
        if row_count > max_rows:
            truncated.append((key, row_count))
    return tuple(truncated)


def _log_ai_decision(
    step: ReportStep,
    ai_blocks: tuple[AiNarrationBlock, ...],
    config: ReportConfig,
) -> None:
    """Audita si la IA quedó deshabilitada, se usó o degradó a narrativa básica."""
    if not config.ai.enabled:
        step.log_decision(
            regla="report_ai_disabled",
            umbral=False,
            valor={"provider": config.ai.provider},
            accion="usar_narrativa_basica",
        )
        return

    generated = sum(1 for block in ai_blocks if block.generated)
    warnings = tuple(block.warning for block in ai_blocks if block.warning)
    if generated:
        step.log_decision(
            regla="report_ai_usage",
            umbral=True,
            valor={
                "provider": config.ai.provider,
                "generated_blocks": generated,
                "input_payload_hashes": tuple(block.input_payload_hash for block in ai_blocks),
            },
            accion="usar_narrativa_ia",
        )
        return
    step.log_decision(
        regla="report_ai_fallback",
        umbral=True,
        valor={"provider": config.ai.provider, "warnings": warnings},
        accion="usar_narrativa_basica",
    )
