"""Constructor lógico de reportes auditables (SDD-26 §4/§6/§7).

``ReportBuilder`` recolecta las cards y artefactos tabulares ya publicados por un ``Study``,
normaliza los nombres heterogéneos al contrato canónico de ``report`` y arma un
:class:`~nikodym.report.results.ReportInputBundle`. No renderiza HTML, no escribe archivos, no
calcula hashes de artefactos y no importa motores gráficos ni SDKs de IA.

El módulo es *pass-through*: no recalcula ni normaliza números de dominios aguas arriba. Sólo toma
snapshots defensivos de estructuras mutables, especialmente ``DataFrame``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NoReturn, TypeAlias, cast

from pydantic import BaseModel

from nikodym.report.config import ReportConfig
from nikodym.report.exceptions import ReportInputError
from nikodym.report.results import (
    ReportInputBundle,
    ReportManifest,
    ReportOutputFormat,
    ReportSection,
)

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.lineage import LineageBundle
    from nikodym.core.study import Study

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any
    LineageBundle: TypeAlias = Any
    Study: TypeAlias = Any

__all__ = ["CANONICAL_SECTION_ORDER", "ReportBuilder"]

CANONICAL_SECTION_ORDER: Final[tuple[str, ...]] = (
    "lineage",
    "eda",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
    "limitations",
    "appendix",
)
_CARD_ARTIFACTS: Final[tuple[tuple[str, str], ...]] = (
    ("eda", "eda_card"),
    ("binning", "binning_card"),
    ("selection", "selection_card"),
    ("model", "model_card"),
    ("scorecard", "card"),
    ("calibration", "card"),
    ("performance", "card"),
    ("stability", "card"),
)
_CARD_KEY_BY_DOMAIN: Final[dict[str, str]] = dict(_CARD_ARTIFACTS)
_TABLE_ARTIFACTS: Final[tuple[tuple[str, str], ...]] = (
    ("eda", "default_rate"),
    ("eda", "stability"),
    ("eda", "univariate"),
    ("eda", "quality"),
    ("binning", "tables"),
    ("binning", "summary"),
    ("binning", "woe_frame"),
    ("selection", "selected_woe_frame"),
    ("selection", "selection_table"),
    ("selection", "correlation_matrix"),
    ("selection", "vif_table"),
    ("selection", "stability_table"),
    ("model", "coefficients"),
    ("model", "stepwise_trace"),
    ("model", "fit_statistics"),
    ("model", "raw_pd_frame"),
    ("scorecard", "scorecard"),
    ("scorecard", "score"),
    ("calibration", "parameters"),
    ("calibration", "calibrated_pd_frame"),
    ("performance", "performance_table"),
    ("performance", "discriminant_metrics"),
    ("stability", "psi_table"),
    ("stability", "stability_metrics"),
)
_FIGURE_ARTIFACTS: Final[tuple[tuple[str, str], ...]] = (("eda", "figures"),)
_SECTION_TITLES: Final[dict[str, str]] = {
    "lineage": "Lineage",
    "eda": "EDA",
    "binning": "Binning WoE",
    "selection": "Selección",
    "model": "Modelo PD",
    "scorecard": "Scorecard",
    "calibration": "Calibración",
    "performance": "Desempeño",
    "stability": "Estabilidad",
    "limitations": "Limitaciones",
    "appendix": "Apéndice",
}
_VALID_OUTPUT_FORMATS: Final[frozenset[str]] = frozenset(
    {"html", "pdf", "docx", "json", "csv", "xlsx"}
)


class ReportBuilder:
    """Ensambla el documento lógico desde cards/results; no renderiza."""

    def __init__(self, config: ReportConfig) -> None:
        """Construye el builder desde una ``ReportConfig`` validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: ReportConfig) -> ReportBuilder:
        """Construye ``ReportBuilder`` desde ``NikodymConfig.report``."""
        return cls(cfg)

    def collect(self, study: Study) -> ReportInputBundle:
        """Recolecta cards, tablas, figuras y lineage en un snapshot defensivo."""
        lineage = _lineage_from_study(study)
        cards = self._collect_cards(study)
        tables = self._collect_tables(study)
        tables.update(_extract_card_dataframes(cards))
        figures = self._collect_figures(study)
        missing_sections = self._missing_required_sections(cards)
        bundle = ReportInputBundle(
            lineage=lineage,
            cards=cards,
            tables=tables,
            figures=figures,
            sections=(),
            missing_sections=missing_sections,
        )
        sections = self.build_sections(bundle)
        return ReportInputBundle(
            lineage=lineage,
            cards=cards,
            tables=tables,
            figures=figures,
            sections=sections,
            missing_sections=missing_sections,
        )

    def build_sections(self, bundle: ReportInputBundle) -> tuple[ReportSection, ...]:
        """Construye secciones en el orden canónico y aplica ``missing_policy``."""
        cards = bundle.cards
        sections: list[ReportSection] = []
        for section_id in CANONICAL_SECTION_ORDER:
            if section_id == "lineage":
                sections.append(_lineage_section(bundle.lineage))
            elif section_id in _CARD_KEY_BY_DOMAIN:
                section = self._domain_section(section_id, cards)
                if section is not None:
                    sections.append(section)
            elif section_id == "limitations":
                sections.append(_limitations_section(bundle))
            else:
                sections.append(_appendix_section(bundle))
        return tuple(sections)

    def build_manifest(self, bundle: ReportInputBundle, *, path: str) -> ReportManifest:
        """Ensambla metadatos pre-render; el renderer completa el ``sha256`` real."""
        output_format = _output_format_from_path(path, self.config)
        return ReportManifest(
            report_id=f"{self.config.basename}-{bundle.lineage.config_hash[:12]}",
            title="Reporte scorecard",
            created_from_lineage_at=bundle.lineage.created_at.isoformat(),
            template_id=self.config.html.template_id,
            template_version=self.config.schema_version,
            output_format=output_format,
            path=path,
            sha256="",
            deterministic=self.config.html.deterministic_ids and not self.config.ai.enabled,
            ai_enabled=self.config.ai.enabled,
            ai_used=False,
            sections=bundle.sections,
        )

    def _collect_cards(self, study: Study) -> dict[str, dict[str, Any]]:
        """Lee las cards canónicas del ``ArtifactStore`` y valida ``metric_sections``."""
        cards: dict[str, dict[str, Any]] = {}
        for domain, key in _CARD_ARTIFACTS:
            if not study.artifacts.has(domain, key):
                continue
            artifact_name = f"{domain}.{key}"
            raw = _card_to_mapping(study.artifacts.get(domain, key), artifact_name)
            _payload_and_metric_sections(raw, artifact=artifact_name)
            cards[domain] = raw
        return cards

    def _collect_tables(self, study: Study) -> dict[str, DataFrameLike]:
        """Extrae ``DataFrame`` de artefactos tabulares conocidos sin alterar upstream."""
        tables: dict[str, DataFrameLike] = {}
        for domain, key in _TABLE_ARTIFACTS:
            if study.artifacts.has(domain, key):
                tables.update(
                    _extract_dataframes(study.artifacts.get(domain, key), f"{domain}.{key}")
                )
        return tables

    def _collect_figures(self, study: Study) -> dict[str, Any]:
        """Recolecta especificaciones declarativas de figuras publicadas por EDA."""
        figures: dict[str, Any] = {}
        for domain, key in _FIGURE_ARTIFACTS:
            if study.artifacts.has(domain, key):
                figures[f"{domain}.{key}"] = _copy_value(study.artifacts.get(domain, key))
        return figures

    def _missing_required_sections(self, cards: Mapping[str, Any]) -> tuple[str, ...]:
        """Lista secciones obligatorias ausentes en el orden canónico de reporte."""
        required = set(self.config.sections.required_sections)
        return tuple(
            section_id
            for section_id in CANONICAL_SECTION_ORDER
            if section_id in required and section_id not in cards
        )

    def _domain_section(
        self,
        section_id: str,
        cards: Mapping[str, Any],
    ) -> ReportSection | None:
        """Construye una sección de dominio o aplica la política de faltantes."""
        if section_id in cards:
            artifact_name = f"{section_id}.{_CARD_KEY_BY_DOMAIN[section_id]}"
            payload, metric_sections = _payload_and_metric_sections(
                _card_to_mapping(cards[section_id], artifact_name),
                artifact=artifact_name,
            )
            return ReportSection(
                id=section_id,
                title=_SECTION_TITLES[section_id],
                status="included",
                source_domain=section_id,
                source_key=_CARD_KEY_BY_DOMAIN[section_id],
                payload=payload,
                metric_sections=metric_sections,
            )

        if section_id not in set(self.config.sections.required_sections):
            return None
        if self.config.sections.missing_policy == "error":
            raise ReportInputError(
                "Falta una card requerida para construir el reporte: "
                f"dominio='{section_id}', clave='{_CARD_KEY_BY_DOMAIN[section_id]}'. "
                "Ejecute el step aguas arriba o use missing_policy='warn'/'skip' para un "
                "reporte parcial explícito."
            )
        if self.config.sections.missing_policy == "skip":
            return None
        return ReportSection(
            id=section_id,
            title=_SECTION_TITLES[section_id],
            status="missing",
            source_domain=section_id,
            source_key=_CARD_KEY_BY_DOMAIN[section_id],
            payload={
                "warning": (
                    "Sección requerida ausente; el reporte parcial no inventa números ni "
                    "rellena métricas."
                )
            },
            metric_sections={},
        )


def _lineage_from_study(study: Study) -> LineageBundle:
    lineage = getattr(getattr(study, "run_context", None), "lineage", None)
    if lineage is None:
        try:
            lineage = study.lineage_bundle()
        except Exception as exc:
            raise ReportInputError(
                "El reporte requiere LineageBundle disponible en el Study; ejecute la corrida "
                "o inyecte run_context.lineage antes de construir el bundle."
            ) from exc
    return cast(LineageBundle, _copy_value(lineage))


def _lineage_section(lineage: LineageBundle) -> ReportSection:
    return ReportSection(
        id="lineage",
        title=_SECTION_TITLES["lineage"],
        status="included",
        source_domain="core",
        source_key="lineage",
        payload=_copy_mapping(cast(Mapping[Any, Any], lineage.model_dump(mode="json"))),
        metric_sections={},
    )


def _limitations_section(bundle: ReportInputBundle) -> ReportSection:
    payload: dict[str, Any] = {
        "determinism_caveats": tuple(bundle.lineage.determinism_caveats),
        "missing_sections": bundle.missing_sections,
    }
    return ReportSection(
        id="limitations",
        title=_SECTION_TITLES["limitations"],
        status="included",
        source_domain="report",
        source_key="limitations",
        payload=payload,
        metric_sections={},
    )


def _appendix_section(bundle: ReportInputBundle) -> ReportSection:
    payload: dict[str, Any] = {
        "missing_sections": bundle.missing_sections,
        "table_keys": tuple(bundle.tables),
        "figure_keys": tuple(bundle.figures),
    }
    return ReportSection(
        id="appendix",
        title=_SECTION_TITLES["appendix"],
        status="included",
        source_domain="report",
        source_key="appendix",
        payload=payload,
        metric_sections={},
    )


def _card_to_mapping(value: Any, artifact: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return _copy_mapping(cast(Mapping[Any, Any], value.model_dump(mode="python")))
    if isinstance(value, Mapping):
        return _copy_mapping(value)
    raise ReportInputError(
        f"La card '{artifact}' debe ser un BaseModel o mapping serializable; "
        f"tipo observado={type(value).__name__}."
    )


def _payload_and_metric_sections(
    raw_card: Mapping[str, Any],
    *,
    artifact: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_metric_sections = raw_card.get("metric_sections", {})
    if raw_metric_sections is None:
        metric_sections: dict[str, Any] = {}
    elif isinstance(raw_metric_sections, Mapping):
        metric_sections = _copy_mapping(raw_metric_sections)
    else:
        raise ReportInputError(
            f"metric_sections de '{artifact}' debe ser un mapping JSON-serializable."
        )
    _validate_metric_sections(metric_sections, artifact=artifact)
    payload = {
        key: _payload_value(value, prefix=f"{artifact}.{key}")
        for key, value in raw_card.items()
        if key != "metric_sections"
    }
    return payload, metric_sections


def _validate_metric_sections(metric_sections: Mapping[str, Any], *, artifact: str) -> None:
    try:
        json.dumps(
            metric_sections,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            default=_raise_not_json_serializable,
        )
    except (TypeError, ValueError) as exc:
        raise ReportInputError(
            f"metric_sections de '{artifact}' no es JSON-serializable; "
            "publique métricas estructuradas sin objetos Python opacos ni floats no finitos."
        ) from exc


def _raise_not_json_serializable(value: object) -> NoReturn:
    raise TypeError(f"{type(value).__name__} no es JSON-serializable")


def _extract_dataframes(value: Any, prefix: str) -> dict[str, DataFrameLike]:
    if _is_dataframe_like(value):
        return {prefix: cast(DataFrameLike, _copy_value(value))}
    if isinstance(value, BaseModel):
        return _extract_dataframes(value.model_dump(mode="python"), prefix)
    if isinstance(value, Mapping):
        frames: dict[str, DataFrameLike] = {}
        for raw_key in sorted(value, key=str):
            frames.update(_extract_dataframes(value[raw_key], f"{prefix}.{raw_key}"))
        return frames
    return {}


def _extract_card_dataframes(cards: Mapping[str, Mapping[str, Any]]) -> dict[str, DataFrameLike]:
    frames: dict[str, DataFrameLike] = {}
    for domain, raw_card in cards.items():
        frames.update(_extract_dataframes(raw_card, f"{domain}.{_CARD_KEY_BY_DOMAIN[domain]}"))
    return frames


def _copy_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): _copy_value(item) for key, item in value.items()}


def _payload_value(value: Any, *, prefix: str) -> Any:
    if _is_dataframe_like(value):
        return {"table_ref": prefix}
    if isinstance(value, BaseModel):
        return _payload_value(value.model_dump(mode="python"), prefix=prefix)
    if isinstance(value, Mapping):
        return {
            str(key): _payload_value(item, prefix=f"{prefix}.{key}") for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _payload_value(item, prefix=f"{prefix}.{index}") for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return tuple(
            _payload_value(item, prefix=f"{prefix}.{index}") for index, item in enumerate(value)
        )
    return _copy_value(value)


def _copy_value(value: Any) -> Any:
    if _is_dataframe_like(value):
        return value.copy(deep=True)
    if isinstance(value, BaseModel):
        return value.model_copy(deep=True)
    if isinstance(value, Mapping):
        return {copy.deepcopy(key): _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_value(item) for item in value)
    return copy.deepcopy(value)


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))


def _output_format_from_path(path: str, config: ReportConfig) -> ReportOutputFormat:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in _VALID_OUTPUT_FORMATS:
        return cast(ReportOutputFormat, suffix)
    fallback = config.formats[0] if config.formats else "html"
    return cast(ReportOutputFormat, fallback)
