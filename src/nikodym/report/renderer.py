"""Renderizadores determinísticos de reportes HTML y Quarto opcional (SDD-26 §4/§7).

``HtmlReportRenderer`` transforma un :class:`~nikodym.report.results.ReportInputBundle` en HTML
standalone usando Jinja2 con import perezoso. La salida básica es reproducible byte a byte:
no usa reloj, UUIDs, rutas locales absolutas ni orden dependiente de ``hash()``.

``QuartoReportRenderer`` mantiene Quarto como ruta derivada y no crítica: detecta el binario solo
cuando está habilitado, invoca el comando de forma mockeable y conserva el HTML básico como
artefacto primario.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import warnings
from collections.abc import Callable, Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Any, Final, Literal, TypeAlias, cast

from pydantic import BaseModel

from nikodym.report._manifest import REPORT_TEMPLATE_VERSION, REPORT_TITLE, html_report_id
from nikodym.report.builder import CANONICAL_SECTION_ORDER
from nikodym.report.config import (
    AiNarrationConfig,
    HtmlRenderConfig,
    QuartoRenderConfig,
    ReportConfig,
    SectionPolicyConfig,
)
from nikodym.report.exceptions import (
    ReportDependencyError,
    ReportExportError,
    ReportRenderError,
)
from nikodym.report.results import (
    AiNarrationBlock,
    ReportInputBundle,
    ReportManifest,
    ReportSection,
)

__all__ = ["HtmlReportRenderer", "QuartoReportRenderer"]

_LOGGER: Final = logging.getLogger(__name__)

JSONValue: TypeAlias = dict[str, Any] | list[Any] | str | int | float | bool | None
TableCell: TypeAlias = str

# Los bytes internos de un ``<svg>`` de matplotlib dependen de freetype y no son idénticos entre
# sistemas operativos; el digest del manifest/golden los reemplaza por un placeholder para ser
# reproducible cross-OS (el HTML en disco conserva los SVG). Non-greedy + DOTALL: cada gráfico se
# recorta por separado (matplotlib no anida ``<svg>``).
_SVG_STRIP_PATTERN: Final = re.compile(r"<svg\b[^>]*>.*?</svg>", re.DOTALL)
_STRIPPED_SVG: Final = '<svg data-chart="stripped"></svg>'

_HTML_TEMPLATE_ID: Final = "scorecard_basic_v1"
_QUARTO_SOURCE_NAME: Final = "scorecard_report.qmd"
_TEMPLATE_PACKAGE: Final = "nikodym.report.templates"
_TEMPLATE_NAME: Final = "scorecard_report.html.j2"
_CSS_FILES: Final[dict[str, str]] = {
    "nikodym": "scorecard_report.css",
    "plain": "scorecard_report_plain.css",
}


class HtmlReportRenderer:
    """Render HTML standalone determinístico con Jinja2."""

    def __init__(
        self,
        config: ReportConfig | HtmlRenderConfig | None = None,
        *,
        basename: str | None = None,
        sections: SectionPolicyConfig | None = None,
        ai: AiNarrationConfig | None = None,
    ) -> None:
        """Construye el renderer desde ``ReportConfig`` o ``HtmlRenderConfig``."""
        self.config = _coerce_report_config(
            config,
            basename=basename,
            sections=sections,
            ai=ai,
        )
        self._last_bundle: ReportInputBundle | None = None
        self._last_ai_blocks: tuple[AiNarrationBlock, ...] = ()

    @classmethod
    def from_config(cls, cfg: ReportConfig) -> HtmlReportRenderer:
        """Construye ``HtmlReportRenderer`` desde ``NikodymConfig.report``."""
        return cls(cfg)

    def render(
        self,
        bundle: ReportInputBundle,
        *,
        ai_blocks: tuple[AiNarrationBlock, ...] = (),
    ) -> str:
        """Renderiza HTML standalone byte-determinístico desde el bundle lógico."""
        try:
            from jinja2 import Environment, PackageLoader, StrictUndefined
        except ModuleNotFoundError as exc:
            raise ReportDependencyError(
                "No se pudo renderizar report.html: falta Jinja2. "
                "Instale nikodym con dependencias base actualizadas y vuelva a ejecutar."
            ) from exc

        self._last_bundle = bundle
        self._last_ai_blocks = ai_blocks
        environment = Environment(
            loader=PackageLoader("nikodym.report", "templates"),
            autoescape=True,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        try:
            rendered = _load_template(environment).render(
                title=REPORT_TITLE,
                template_id=self.config.html.template_id,
                template_version=REPORT_TEMPLATE_VERSION,
                created_from_lineage_at=bundle.lineage.created_at.isoformat(),
                lineage=_lineage_view(bundle),
                css=_css_for_theme(self.config.html.theme),
                sections=_section_views(bundle, ai_blocks, self.config),
            )
        except ReportRenderError:
            raise
        except Exception as exc:
            raise ReportRenderError(
                "No se pudo renderizar report.html: dominio='report', plantilla="
                f"'{self.config.html.template_id}', acción='revise el bundle y la plantilla'."
            ) from exc
        return _normalize_newlines(rendered)

    def build_manifest(self, html: str) -> ReportManifest:
        """Construye el manifiesto HTML canónico sin escribir archivos."""
        bundle = self._last_bundle
        if bundle is None:
            raise ReportExportError(
                "No se puede construir el manifest report.html porque no hay bundle "
                "renderizado; acción='llame HtmlReportRenderer.render antes de build_manifest'."
            )

        digest = _digest_html(html)
        ai_used = any(block.generated for block in self._last_ai_blocks)
        return ReportManifest(
            report_id=html_report_id(bundle, self.config),
            title=REPORT_TITLE,
            created_from_lineage_at=bundle.lineage.created_at.isoformat(),
            template_id=self.config.html.template_id,
            template_version=REPORT_TEMPLATE_VERSION,
            output_format="html",
            path="",
            sha256=digest,
            deterministic=self.config.html.deterministic_ids and not ai_used,
            ai_enabled=self.config.ai.enabled or bool(self._last_ai_blocks),
            ai_used=ai_used,
            sections=_ordered_sections(bundle.sections),
        )

    def write(self, html: str, *, output_dir: str) -> ReportManifest:
        """Escribe el HTML en disco y devuelve un manifiesto reproducible."""
        bundle = self._last_bundle
        if bundle is None:
            raise ReportExportError(
                "No se puede exportar report.html porque no hay bundle renderizado; "
                "acción='llame HtmlReportRenderer.render antes de write'."
            )

        directory = _prepare_output_dir(output_dir)
        filename = f"{self.config.basename}.html"
        output_path = directory / filename
        normalized_html = _normalize_newlines(html)
        payload = normalized_html.encode("utf-8")
        temp_path = directory / f".{filename}.tmp"

        try:
            temp_path.write_bytes(payload)
            temp_path.replace(output_path)
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            raise ReportExportError(
                "No se pudo escribir el reporte HTML: dominio='report', "
                f"clave='{filename}', output_dir='{output_dir}', "
                "acción='verifique permisos y espacio disponible'."
            ) from exc

        manifest = self.build_manifest(normalized_html)
        return manifest.model_copy(update={"path": _manifest_path(directory, filename)})


class QuartoReportRenderer:
    """Render opcional vía binario externo ``quarto`` para artefactos derivados."""

    def __init__(self, config: ReportConfig | QuartoRenderConfig | None = None) -> None:
        """Construye el renderer Quarto desde ``ReportConfig`` o ``QuartoRenderConfig``."""
        if isinstance(config, QuartoRenderConfig):
            self.config = ReportConfig(quarto=config)
        elif config is None:
            self.config = ReportConfig()
        else:
            self.config = config

    @classmethod
    def from_config(cls, cfg: ReportConfig) -> QuartoReportRenderer:
        """Construye ``QuartoReportRenderer`` desde ``NikodymConfig.report``."""
        return cls(cfg)

    def render(self, bundle: ReportInputBundle, *, output_dir: str) -> ReportManifest:
        """Renderiza HTML básico y, si procede, invoca Quarto de forma opcional."""
        html_renderer = HtmlReportRenderer.from_config(self.config)
        html = html_renderer.render(bundle)

        if not self.config.quarto.enabled:
            return html_renderer.write(html, output_dir=output_dir)

        quarto_path = shutil.which("quarto")
        if quarto_path is None:
            if self.config.quarto.fail_if_unavailable:
                raise ReportDependencyError(
                    "Quarto no está disponible para report: instale Quarto desde "
                    "https://quarto.org y asegure que el binario 'quarto' esté en PATH."
                )
            warnings.warn(
                "Quarto no está disponible; se usó HTML básico determinístico.",
                RuntimeWarning,
                stacklevel=2,
            )
            return html_renderer.write(html, output_dir=output_dir)

        manifest = html_renderer.write(html, output_dir=output_dir)
        self._invoke_quarto(quarto_path, output_dir=output_dir, html_path=manifest.path)
        return manifest

    def _invoke_quarto(self, quarto_path: str, *, output_dir: str, html_path: str) -> None:
        """Invoca Quarto sobre una fuente mínima derivada del HTML primario."""
        directory = _prepare_output_dir(output_dir)
        source = directory / _QUARTO_SOURCE_NAME
        source.write_text(
            "\n".join(
                (
                    "---",
                    "title: Reporte scorecard",
                    "format: html",
                    "---",
                    "",
                    f"Reporte HTML primario: {html_path}",
                    "",
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        formats = self.config.quarto.formats or ("pdf",)
        for output_format in formats:
            command = [
                quarto_path,
                "render",
                source.name,
                "--to",
                output_format,
                "--output",
                f"{self.config.basename}.{output_format}",
            ]
            try:
                subprocess.run(
                    command,
                    cwd=directory,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise ReportRenderError(
                    "Quarto falló al renderizar report: dominio='report', "
                    f"formato='{output_format}', acción='revise la instalación de Quarto'."
                ) from exc


def _coerce_report_config(
    config: ReportConfig | HtmlRenderConfig | None,
    *,
    basename: str | None,
    sections: SectionPolicyConfig | None,
    ai: AiNarrationConfig | None,
) -> ReportConfig:
    if isinstance(config, HtmlRenderConfig):
        return ReportConfig(
            basename=basename or "scorecard_report",
            html=config,
            sections=sections or SectionPolicyConfig(),
            ai=ai or AiNarrationConfig(),
        )
    if config is None:
        if basename is None and sections is None and ai is None:
            return ReportConfig()
        return ReportConfig(
            basename=basename or "scorecard_report",
            sections=sections or SectionPolicyConfig(),
            ai=ai or AiNarrationConfig(),
        )
    return config


def _section_views(
    bundle: ReportInputBundle,
    ai_blocks: tuple[AiNarrationBlock, ...],
    config: ReportConfig,
) -> list[dict[str, Any]]:
    sections_by_id = {section.id: section for section in bundle.sections}
    narratives = {block.section_id: block for block in ai_blocks}
    views: list[dict[str, Any]] = []
    for section_id in CANONICAL_SECTION_ORDER:
        section = sections_by_id.get(section_id)
        if section is None:
            continue
        views.append(
            {
                "id": section.id,
                "html_id": _element_id("section", section.id),
                "title": section.title,
                "status": section.status,
                "source": _section_source(section),
                "payload_items": _mapping_items(section.payload),
                "metric_items": _mapping_items(section.metric_sections),
                "tables": _tables_for_section(bundle, section.id, config.sections.max_table_rows),
                "charts": _charts_for_section(bundle, section.id, config),
                "figures": _figures_for_section(bundle, section.id),
                "narration": _narration_view(narratives.get(section.id), config.ai.label_ai_text),
            }
        )
    return views


def _ordered_sections(sections: tuple[ReportSection, ...]) -> tuple[ReportSection, ...]:
    order = {section_id: index for index, section_id in enumerate(CANONICAL_SECTION_ORDER)}
    return tuple(sorted(sections, key=lambda section: (order.get(section.id, 999), section.id)))


def _lineage_view(bundle: ReportInputBundle) -> dict[str, str]:
    lineage = bundle.lineage
    return {
        "git_sha": _display_scalar(lineage.git_sha, key_path=("git_sha",)),
        "data_hash": _display_scalar(lineage.data_hash, key_path=("data_hash",)),
        "config_hash": _display_scalar(lineage.config_hash, key_path=("config_hash",)),
        "root_seed": _display_scalar(lineage.root_seed, key_path=("root_seed",)),
    }


def _section_source(section: ReportSection) -> str:
    domain = section.source_domain or "sin_dominio"
    key = section.source_key or "sin_clave"
    return f"{domain}.{key}"


def _mapping_items(value: Mapping[str, Any]) -> list[dict[str, str | bool]]:
    items: list[dict[str, str | bool]] = []
    for raw_key in sorted(value, key=str):
        key = str(raw_key)
        rendered = _display_value(value[raw_key], key_path=(key,))
        items.append({"key": key, "value": rendered, "multiline": "\n" in rendered})
    return items


def _narration_view(block: AiNarrationBlock | None, label_ai_text: bool) -> dict[str, str] | None:
    if block is None:
        return None
    label = "Narrativa generada por IA" if label_ai_text and block.generated else ""
    warning = block.warning or ""
    return {"text": block.text, "label": label, "warning": warning}


def _tables_for_section(
    bundle: ReportInputBundle,
    section_id: str,
    max_rows: int,
) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    prefix = f"{section_id}."
    for key in sorted(bundle.tables, key=str):
        if key == section_id or key.startswith(prefix):
            tables.append(_table_view(key, bundle.tables[key], max_rows=max_rows))
    return tables


def _table_view(key: str, table: Any, *, max_rows: int) -> dict[str, Any]:
    if not _is_dataframe_like(table):
        raise ReportRenderError(
            f"Tabla no renderizable en report: clave='{key}', acción='publique un DataFrame'."
        )
    columns = tuple(table.columns)
    records = cast(list[Mapping[Any, Any]], table.to_dict(orient="records"))
    rows = [
        tuple(
            _display_scalar(record.get(column), key_path=(key, str(column))) for column in columns
        )
        for record in records
    ]
    visible_rows = rows[:max_rows]
    return {
        "key": key,
        "html_id": _element_id("table", key),
        "columns": [str(column) for column in columns],
        "rows": visible_rows,
        "total_rows": len(rows),
        "shown_rows": len(visible_rows),
        "truncated": len(rows) > len(visible_rows),
    }


def _figures_for_section(bundle: ReportInputBundle, section_id: str) -> list[dict[str, str]]:
    figures: list[dict[str, str]] = []
    prefix = f"{section_id}."
    for key in sorted(bundle.figures, key=str):
        if key == section_id or key.startswith(prefix):
            figures.append(
                {
                    "key": key,
                    "html_id": _element_id("figure", key),
                    "payload": _display_value(bundle.figures[key], key_path=(key,)),
                }
            )
    return figures


_CHART_TITLES: Final[dict[str, str]] = {
    "gains": "Curva de ganancia acumulada por partición",
    "discrimination": "Discriminación (AUC/Gini/KS) por partición",
    "coefficients": "Coeficientes del modelo (β, IC 95 %)",
    "stability": "Estabilidad PSI/CSI por comparación",
    "reliability": "Curva de calibración (confiabilidad) por partición",
}


def _chart_gains(charts: Any, bundle: ReportInputBundle) -> str:
    """Curva de ganancia desde ``performance.performance_table``."""
    return cast(
        str,
        charts.render_gains_chart(
            bundle.tables["performance.performance_table"], title=_CHART_TITLES["gains"]
        ),
    )


def _chart_discrimination(charts: Any, bundle: ReportInputBundle) -> str:
    """Barras de discriminación desde ``performance.discriminant_metrics``."""
    return cast(
        str,
        charts.render_discrimination_bars(
            bundle.tables["performance.discriminant_metrics"],
            title=_CHART_TITLES["discrimination"],
        ),
    )


def _chart_coefficients(charts: Any, bundle: ReportInputBundle) -> str:
    """Forest de coeficientes desde ``model.coefficients``."""
    return cast(
        str,
        charts.render_coefficients_forest(
            bundle.tables["model.coefficients"], title=_CHART_TITLES["coefficients"]
        ),
    )


def _chart_stability(charts: Any, bundle: ReportInputBundle) -> str:
    """Barras horizontales PSI/CSI desde ``stability.stability_metrics``."""
    return cast(
        str,
        charts.render_stability_chart(
            bundle.tables["stability.stability_metrics"], title=_CHART_TITLES["stability"]
        ),
    )


def _chart_reliability(charts: Any, bundle: ReportInputBundle) -> str:
    """Curva de confiabilidad derivada en render-time desde ``calibration.calibrated_pd_frame``.

    ``reliability_curve`` (capa ``ui``) proyecta el frame calibrado a la lista ``by_partition`` que
    consume ``render_reliability_chart``; el import es perezoso para no arrastrar la capa ``ui`` al
    import del paquete ``report``.
    """
    from nikodym.ui.reliability import reliability_curve

    curve = reliability_curve(bundle.tables["calibration.calibrated_pd_frame"])
    return cast(
        str,
        charts.render_reliability_chart(curve["by_partition"], title=_CHART_TITLES["reliability"]),
    )


# Mapeo sección → gráficos (nombre estable + builder). El nombre alimenta el ``id`` HTML del slot.
_CHART_BUILDERS: Final[
    dict[str, tuple[tuple[str, Callable[[Any, ReportInputBundle], str]], ...]]
] = {
    "performance": (("gains", _chart_gains), ("discrimination", _chart_discrimination)),
    "model": (("coefficients", _chart_coefficients),),
    "stability": (("stability", _chart_stability),),
    "calibration": (("reliability", _chart_reliability),),
}


def _charts_for_section(
    bundle: ReportInputBundle,
    section_id: str,
    config: ReportConfig,
) -> list[dict[str, str]]:
    """Genera los SVG deterministas de la sección desde ``bundle.tables`` (import perezoso).

    Cada gráfico se produce aislado y con degradación con gracia: si falta ``matplotlib``, faltan
    columnas o la tabla no está publicada, se omite ese gráfico (el slot editorial queda vacío) y el
    reporte se renderiza igual. El import de :mod:`nikodym.report.charts` es perezoso para preservar
    el import liviano del paquete ``report`` (nunca top-level).
    """
    if not config.html.render_charts:
        return []
    builders = _CHART_BUILDERS.get(section_id)
    if builders is None:
        return []
    from nikodym.report import charts  # perezoso: matplotlib no entra al import del paquete.

    results: list[dict[str, str]] = []
    for name, build in builders:
        try:
            svg = build(charts, bundle)
        except Exception as exc:  # degradación con gracia: un gráfico nunca tumba el reporte.
            _LOGGER.warning(
                "report: gráfico '%s.%s' omitido por degradación con gracia: %s",
                section_id,
                name,
                exc,
            )
            continue
        results.append({"html_id": _element_id("chart", f"{section_id}-{name}"), "svg": svg})
    return results


def _display_value(value: Any, *, key_path: tuple[str, ...]) -> str:
    if isinstance(value, Mapping):
        rendered = {
            str(key): _display_json_value(value[key], key_path=(*key_path, str(key)))
            for key in sorted(value, key=str)
        }
        return json.dumps(rendered, sort_keys=True, ensure_ascii=False, indent=2)
    if isinstance(value, tuple | list):
        return json.dumps(
            [_display_json_value(item, key_path=key_path) for item in value],
            ensure_ascii=False,
            indent=2,
        )
    if isinstance(value, set | frozenset):
        ordered = sorted(value, key=lambda item: _stable_json(_canonical_value(item)))
        return json.dumps(
            [_display_json_value(item, key_path=key_path) for item in ordered],
            ensure_ascii=False,
            indent=2,
        )
    if isinstance(value, BaseModel):
        return _display_value(value.model_dump(mode="python"), key_path=key_path)
    if _is_dataframe_like(value):
        return "[tabla referenciada]"
    return _display_scalar(value, key_path=key_path)


def _display_json_value(value: Any, *, key_path: tuple[str, ...]) -> JSONValue:
    if isinstance(value, Mapping):
        return {
            str(key): _display_json_value(value[key], key_path=(*key_path, str(key)))
            for key in sorted(value, key=str)
        }
    if isinstance(value, tuple | list):
        return [_display_json_value(item, key_path=key_path) for item in value]
    if isinstance(value, set | frozenset):
        ordered = sorted(value, key=lambda item: _stable_json(_canonical_value(item)))
        return [_display_json_value(item, key_path=key_path) for item in ordered]
    if isinstance(value, BaseModel):
        return _display_json_value(value.model_dump(mode="python"), key_path=key_path)
    if _is_dataframe_like(value):
        return "[tabla referenciada]"
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return _format_float(value, key_path=key_path)
    if isinstance(value, str):
        return value
    return {"unsupported_type": type(value).__name__}


def _display_scalar(value: Any, *, key_path: tuple[str, ...]) -> str:
    if value is None:
        return "No disponible"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return _format_float(value, key_path=key_path)
    if isinstance(value, BaseModel):
        return _display_value(value.model_dump(mode="python"), key_path=key_path)
    if isinstance(value, Mapping | Sequence) and not isinstance(value, str | bytes | bytearray):
        return _display_value(value, key_path=key_path)
    return str(value)


def _format_float(value: float, *, key_path: tuple[str, ...]) -> str:
    if value == 0.0:
        value = 0.0
    if not math.isfinite(value):
        if math.isnan(value):
            return "nan"
        return "inf" if value > 0 else "-inf"
    key = ".".join(key_path).lower()
    if _is_percent_key(key):
        return f"{value:.4f}"
    if _is_six_decimal_key(key):
        return f"{value:.6f}"
    return f"{value:.6f}"


def _is_percent_key(key: str) -> bool:
    return any(token in key for token in ("pct", "percent", "porcentaje", "tasa", "rate"))


def _is_six_decimal_key(key: str) -> bool:
    return any(token in key for token in ("pd", "psi", "csi", "auc", "ks", "gini"))


def _canonical_value(value: Any) -> JSONValue:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_canonical_value(item) for item in sorted(value, key=str)]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if value == 0.0:
            return 0.0
        if math.isfinite(value):
            return value
        if math.isnan(value):
            return {"non_finite_float": "nan"}
        return {"non_finite_float": "inf" if value > 0 else "-inf"}
    if isinstance(value, str):
        return value
    return {"unsupported_type": type(value).__name__}


def _stable_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _element_id(kind: str, raw_id: str) -> str:
    """Deriva IDs HTML siempre determinísticos desde el tipo y la clave lógica."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw_id.strip().lower()).strip("-")
    return f"{kind}-{slug or 'sin-id'}"


def _load_template(environment: Any) -> Any:
    """Carga la plantilla editorial del paquete; aislada para poder simular fallos en tests."""
    return environment.get_template(_TEMPLATE_NAME)


def _css_for_theme(theme: Literal["nikodym", "plain"]) -> str:
    """Lee el CSS del tema desde los archivos empaquetados bajo ``report/templates``."""
    filename = _CSS_FILES.get(theme, _CSS_FILES["nikodym"])
    return resources.files(_TEMPLATE_PACKAGE).joinpath(filename).read_text("utf-8").strip()


def _normalize_newlines(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        return f"{normalized}\n"
    return normalized


def _digest_html(html: str) -> str:
    """SHA-256 del HTML con cada ``<svg>…</svg>`` reemplazado por un placeholder estable.

    El manifest y los goldens usan este digest en vez del ``sha256`` de los bytes crudos: los SVG de
    los gráficos dependen de freetype y no son byte-idénticos entre sistemas operativos, así que se
    excluyen para que el digest sea reproducible cross-OS. Cubre datos y estructura del reporte; el
    determinismo byte a byte de cada SVG se verifica aparte en ``test_report_charts``. El HTML en
    disco conserva los SVG intactos.
    """
    stripped = _SVG_STRIP_PATTERN.sub(_STRIPPED_SVG, _normalize_newlines(html))
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()


def _prepare_output_dir(output_dir: str) -> Path:
    directory = Path(output_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReportExportError(
            "No se pudo crear el directorio de salida del reporte: dominio='report', "
            f"output_dir='{output_dir}', acción='verifique permisos de la ruta padre'."
        ) from exc
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        raise ReportExportError(
            "El directorio de salida del reporte no es escribible: dominio='report', "
            f"output_dir='{output_dir}', acción='ajuste permisos o use otra ruta'."
        )
    return directory


def _manifest_path(directory: Path, filename: str) -> str:
    if directory.is_absolute():
        return filename
    return (directory / filename).as_posix()


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))
