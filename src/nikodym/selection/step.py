"""Paso orquestable de la capa ``selection`` (SDD-07 §4/§6/§7; CT-1).

``SelectionStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``selection``: lee artefactos publicados por ``data`` y ``binning``, ajusta
``FeatureSelector`` sólo sobre Desarrollo, transforma el ``woe_frame`` completo a variables
seleccionadas y publica los artefactos auditables bajo el dominio ``selection``.

El módulo evita importar ``pandas``, ``sklearn``, ``statsmodels``, ``scipy`` y
``nikodym.selection.selector`` en import time. ``nikodym.selection`` lo importa para ejecutar
``@register("standard", domain="selection")`` sin contaminar el núcleo liviano; las dependencias
tabulares y de scoring se cargan dentro de ``execute``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from importlib import metadata
from typing import TYPE_CHECKING, Any, Final, Protocol, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.selection.config import SelectionConfig
from nikodym.selection.exceptions import SelectionFitError, SelectionForcedVifConflictError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.study import Study
    from nikodym.data.partition import PartitionResult
    from nikodym.data.target import LabeledFrame
    from nikodym.selection.results import (
        SelectionCardSection,
        SelectionResult,
        VariableSelectionDecision,
    )
    from nikodym.selection.selector import FeatureSelector

    DataFrame: TypeAlias = pd.DataFrame
else:
    DataFrame: TypeAlias = Any
    FeatureSelector: TypeAlias = Any
    LabeledFrame: TypeAlias = Any
    PartitionResult: TypeAlias = Any
    SelectionCardSection: TypeAlias = Any
    SelectionResult: TypeAlias = Any
    VariableSelectionDecision: TypeAlias = Any

__all__ = ["SELECTION_ARTIFACTS", "SelectionStep"]

SELECTION_ARTIFACTS: Final[tuple[str, ...]] = (
    "selected_features",
    "selected_woe_columns",
    "selected_woe_frame",
    "selection_table",
    "correlation_matrix",
    "vif_table",
    "stability_table",
    "result",
    "selection_card",
)
_SCORING_EXTRA_MESSAGE: Final = (
    "SelectionStep requiere FeatureSelector y el extra de scoring; instale nikodym[scoring]."
)
_DEPENDENCY_DISTRIBUTIONS: Final[tuple[str, ...]] = (
    "scikit-learn",
    "statsmodels",
    "scipy",
    "pandas",
    "numpy",
)
_STABILITY_FLAG_BANDS: Final[frozenset[str]] = frozenset({"review", "redevelop"})


class _BinningResultLike(Protocol):
    """Contrato estructural mínimo consumido desde ``BinningResult``."""

    woe_column_map: dict[str, str]


@register("standard", domain="selection")
class SelectionStep(AuditableMixin):
    """Orquesta selección pre-modelo y publica artefactos ``domain='selection'``."""

    name: str = "selection"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "labels"),
        ("data", "splits"),
        ("binning", "process"),
        ("binning", "summary"),
        ("binning", "tables"),
        ("binning", "woe_frame"),
        ("binning", "result"),
    )
    provides: tuple[ArtifactKey, ...] = tuple(("selection", key) for key in SELECTION_ARTIFACTS)

    def __init__(self, config: SelectionConfig) -> None:
        """Construye el paso desde la sección ``SelectionConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: SelectionConfig) -> SelectionStep:
        """Construye ``SelectionStep`` desde ``NikodymConfig.selection``."""
        return cls(cfg)

    def execute(self, study: Study, rng: np.random.Generator) -> SelectionResult:
        """Ejecuta fit en Desarrollo y transform determinista sin consumir ``rng``.

        ``rng`` se recibe por el protocolo homogéneo de ``Step``; selection v1 no introduce muestreo
        ni azar propio. La reproducibilidad depende de datos, config y versiones instaladas.
        """
        del rng
        pd = _import_pandas()

        labels = _as_labeled_frame(study.artifacts.get("data", "labels"))
        splits = _as_partition_result(study.artifacts.get("data", "splits"))
        process = _as_binning_process(study.artifacts.get("binning", "process"))
        summary = _as_dataframe(study.artifacts.get("binning", "summary"), pd, "summary").copy(
            deep=True
        )
        tables = _as_tables(study.artifacts.get("binning", "tables"), pd)
        woe_frame = _as_dataframe(
            study.artifacts.get("binning", "woe_frame"), pd, "woe_frame"
        ).copy(deep=True)
        binning_result = _as_binning_result(study.artifacts.get("binning", "result"))
        del process, tables

        target_col = labels.target_col
        partition_col = splits.partition_col
        ttd_col = splits.ttd_col
        _validate_required_columns(woe_frame, (target_col, partition_col))
        _validate_optional_ttd_column(woe_frame, ttd_col)

        cfg = _selection_config_from_study(study, fallback=self.config)
        selector = _build_selector(cfg)
        try:
            selector.fit(
                woe_frame,
                target_col=target_col,
                partition_col=partition_col,
                binning_summary=summary,
                woe_column_map=dict(binning_result.woe_column_map),
            )
        except SelectionForcedVifConflictError as exc:
            self._log_forced_conflict_if_present(exc, cfg)
            raise

        selected_woe_frame = selector.transform(woe_frame)
        result = _build_result(selector, selected_woe_frame)
        selection_card = _build_selection_card(result, cfg)
        self._log_selection_decisions(result=result, config=cfg)
        self._publish_artifacts(study, result, selection_card)
        return result

    def _log_forced_conflict_if_present(
        self,
        exc: SelectionForcedVifConflictError,
        config: SelectionConfig,
    ) -> None:
        """Registra conflicto de forzadas detectado durante VIF antes de re-levantar el error."""
        message = str(exc)
        self.log_decision(
            regla="forced_conflict",
            umbral=config.vif.threshold,
            valor={"detalle": message},
            accion="fallar_corrida",
        )

    def _log_selection_decisions(
        self,
        *,
        result: SelectionResult,
        config: SelectionConfig,
    ) -> None:
        """Registra exclusiones y flags auditables derivados de ``SelectionResult``."""
        vif_iterations = _removed_vif_iterations(result.vif_table)
        for decision in result.decisions:
            if decision.reason == "included":
                continue
            self.log_decision(
                regla=decision.reason,
                umbral=_decision_threshold(config, decision.reason),
                valor=_decision_value(decision, config, vif_iterations),
                accion=_decision_action(decision),
            )
        self._log_stability_flags(result=result, config=config)

    def _log_stability_flags(
        self,
        *,
        result: SelectionResult,
        config: SelectionConfig,
    ) -> None:
        """Registra PSI/CSI en bandas de revisión o redesarrollo sin cambiar la selección."""
        if not config.stability.enabled or result.stability_table.empty:
            return
        for row in result.stability_table.to_dict(orient="records"):
            band = str(row.get("csi_band", ""))
            if band not in _STABILITY_FLAG_BANDS:
                continue
            self.log_decision(
                regla="stability_csi",
                umbral={
                    "stable_threshold": config.stability.stable_threshold,
                    "review_threshold": config.stability.review_threshold,
                },
                valor={
                    "feature": str(row["feature"]),
                    "woe_column": str(row["woe_column"]),
                    "sample": str(row["sample"]),
                    "csi": _optional_float(row.get("csi")),
                    "csi_band": band,
                    "smoothing": _optional_float(row.get("smoothing")),
                },
                accion=(
                    "diagnosticar_sin_eliminar"
                    if config.stability.action == "report_only"
                    else "evaluar_exclusion"
                ),
            )

    def _publish_artifacts(
        self,
        study: Study,
        result: SelectionResult,
        selection_card: SelectionCardSection,
    ) -> None:
        """Publica los nueve artefactos estables del dominio ``selection``."""
        study.artifacts.set("selection", "selected_features", result.selected_features)
        study.artifacts.set("selection", "selected_woe_columns", result.selected_woe_columns)
        study.artifacts.set(
            "selection", "selected_woe_frame", result.selected_woe_frame.copy(deep=True)
        )
        study.artifacts.set("selection", "selection_table", result.selection_table.copy(deep=True))
        study.artifacts.set(
            "selection", "correlation_matrix", result.correlation_matrix.copy(deep=True)
        )
        study.artifacts.set("selection", "vif_table", result.vif_table.copy(deep=True))
        study.artifacts.set("selection", "stability_table", result.stability_table.copy(deep=True))
        study.artifacts.set("selection", "result", result)
        study.artifacts.set("selection", "selection_card", selection_card)


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "SelectionStep requiere pandas; instale las dependencias base de nikodym."
        ) from exc


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular de ``binning`` antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise SelectionFitError(
        f"El artefacto ('binning', '{artifact}') debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_labeled_frame(value: object) -> LabeledFrame:
    """Valida el artefacto ``data.labels`` con import local de ``data``."""
    from nikodym.data.target import LabeledFrame

    if isinstance(value, LabeledFrame):
        return value
    raise SelectionFitError(
        "El artefacto ('data', 'labels') debe ser un LabeledFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_partition_result(value: object) -> PartitionResult:
    """Valida el artefacto ``data.splits`` con import local de ``data``."""
    from nikodym.data.partition import PartitionResult

    if isinstance(value, PartitionResult):
        return value
    raise SelectionFitError(
        "El artefacto ('data', 'splits') debe ser un PartitionResult; "
        f"tipo observado={type(value).__name__}."
    )


def _as_binning_process(value: object) -> object:
    """Valida estructuralmente el proceso de binning fiteado."""
    if hasattr(value, "transform") and hasattr(value, "woe_column_map_"):
        return value
    raise SelectionFitError(
        "El artefacto ('binning', 'process') debe ser un WoEBinner fiteado; "
        f"tipo observado={type(value).__name__}."
    )


def _as_tables(value: object, pd: Any) -> dict[str, DataFrame]:
    """Valida las tablas por variable publicadas por ``binning``."""
    if not isinstance(value, Mapping):
        raise SelectionFitError(
            "El artefacto ('binning', 'tables') debe ser un mapping de DataFrames; "
            f"tipo observado={type(value).__name__}."
        )
    tables: dict[str, DataFrame] = {}
    for name, table in value.items():
        if not isinstance(table, pd.DataFrame):
            raise SelectionFitError(
                "El artefacto ('binning', 'tables') contiene una tabla no tabular: "
                f"variable={name!r}, tipo observado={type(table).__name__}."
            )
        tables[str(name)] = cast(DataFrame, table.copy(deep=True))
    return tables


def _as_binning_result(value: object) -> _BinningResultLike:
    """Valida estructuralmente el ``BinningResult`` consumido por selection."""
    mapping = getattr(value, "woe_column_map", None)
    if isinstance(mapping, dict) and all(
        isinstance(feature, str) and isinstance(column, str) for feature, column in mapping.items()
    ):
        return cast(_BinningResultLike, value)
    raise SelectionFitError(
        "El artefacto ('binning', 'result') debe exponer woe_column_map: dict[str, str]; "
        f"tipo observado={type(value).__name__}."
    )


def _validate_required_columns(frame: DataFrame, columns: tuple[str, ...]) -> None:
    """Falla con una lista completa si faltan columnas estructurales en ``binning.woe_frame``."""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise SelectionFitError(f"binning.woe_frame no contiene columnas requeridas: {joined}.")


def _validate_optional_ttd_column(frame: DataFrame, ttd_col: str | None) -> None:
    """Valida ``ttd`` sólo cuando el contrato de partición lo declara y el frame lo conserva."""
    if ttd_col is not None and ttd_col not in frame.columns:
        raise SelectionFitError(
            f"binning.woe_frame no contiene la columna ttd declarada por data.splits: '{ttd_col}'."
        )


def _selection_config_from_study(study: Study, *, fallback: SelectionConfig) -> SelectionConfig:
    """Lee ``NikodymConfig.selection`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "selection", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, SelectionConfig):
        return raw_config
    return SelectionConfig.model_validate(raw_config)


def _build_selector(config: SelectionConfig) -> FeatureSelector:
    """Importa ``FeatureSelector`` bajo demanda y traduce la ausencia del extra scoring."""
    try:
        module = importlib.import_module("nikodym.selection.selector")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    selector_cls = module.FeatureSelector
    return cast(FeatureSelector, selector_cls.from_config(config))


def _build_result(selector: FeatureSelector, selected_woe_frame: DataFrame) -> SelectionResult:
    """Construye ``SelectionResult`` con copias defensivas de todas las tablas."""
    from nikodym.selection.results import SelectionResult

    return SelectionResult(
        candidate_features=tuple(selector.candidate_features_),
        candidate_woe_columns=tuple(selector.candidate_woe_columns_),
        selected_features=tuple(selector.selected_features_),
        selected_woe_columns=tuple(selector.selected_woe_columns_),
        selected_woe_frame=selected_woe_frame.copy(deep=True),
        selection_table=selector.selection_table_.copy(deep=True),
        correlation_matrix=selector.correlation_matrix_.copy(deep=True),
        vif_table=selector.vif_table_.copy(deep=True),
        stability_table=selector.stability_table_.copy(deep=True),
        decisions=tuple(selector.decisions_),
    )


def _build_selection_card(
    result: SelectionResult,
    config: SelectionConfig,
) -> SelectionCardSection:
    """Construye la sección de model card resolviendo versiones fuera de ``results.py``."""
    from nikodym.selection.results import SelectionCardSection

    return SelectionCardSection.from_result(
        result,
        thresholds=_thresholds_from_config(config),
        dependency_versions=_dependency_versions(),
    )


def _thresholds_from_config(config: SelectionConfig) -> dict[str, float | str | None]:
    """Serializa umbrales activos de selection para card/report."""
    return {
        "min_iv": config.min_iv,
        "max_iv": config.max_iv,
        "max_iv_action": config.max_iv_action,
        "min_auc": config.min_auc,
        "min_ks": config.min_ks,
        "min_gini": config.min_gini,
        "correlation.method": config.correlation.method,
        "correlation.threshold": (
            config.correlation.threshold if config.correlation.enabled else None
        ),
        "correlation.clustering_method": config.correlation.clustering_method,
        "vif.threshold": config.vif.threshold if config.vif.enabled else None,
        "stability.action": config.stability.action,
        "stability.stable_threshold": (
            config.stability.stable_threshold if config.stability.enabled else None
        ),
        "stability.review_threshold": (
            config.stability.review_threshold if config.stability.enabled else None
        ),
    }


def _dependency_versions() -> dict[str, str]:
    """Obtiene versiones instaladas sin importar módulos pesados."""
    versions: dict[str, str] = {}
    for distribution in _DEPENDENCY_DISTRIBUTIONS:
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = "no_instalado"
    return versions


def _removed_vif_iterations(vif_table: DataFrame) -> dict[str, int]:
    """Indexa la iteración VIF en que una feature fue eliminada."""
    if vif_table.empty or "removed" not in vif_table.columns:
        return {}
    removed = vif_table.loc[vif_table["removed"].astype("bool")]
    return {str(row["feature"]): int(row["iteration"]) for row in removed.to_dict(orient="records")}


def _decision_threshold(config: SelectionConfig, reason: str) -> object:
    """Mapea motivo normalizado a umbral auditable."""
    thresholds: dict[str, object] = {
        "business_include": "force_include",
        "business_exclude": "force_exclude",
        "low_iv": config.min_iv,
        "high_iv": config.max_iv,
        "low_auc": config.min_auc,
        "low_ks": config.min_ks,
        "low_gini": config.min_gini,
        "high_correlation": config.correlation.threshold,
        "cluster_representative_lost": config.correlation.threshold,
        "high_vif": config.vif.threshold,
        "constant_or_nonfinite": "finito_y_no_constante",
        "missing_binning_artifact": "woe_column_map",
        "forced_conflict": "force_include/force_exclude",
        "high_stability": config.stability.review_threshold,
    }
    return thresholds.get(reason)


def _decision_value(
    decision: VariableSelectionDecision,
    config: SelectionConfig,
    vif_iterations: Mapping[str, int],
) -> object:
    """Escoge payload observado para auditoría según la regla gatillante."""
    base: dict[str, object] = {
        "feature": decision.feature,
        "woe_column": decision.woe_column,
    }
    if decision.reason in {"business_include", "business_exclude", "low_iv", "high_iv"}:
        return {**base, "iv": decision.iv, "iv_band": decision.iv_band}
    if decision.reason == "low_auc":
        return {**base, "auc": decision.auc}
    if decision.reason == "low_ks":
        return {**base, "ks": decision.ks}
    if decision.reason == "low_gini":
        return {**base, "gini": decision.gini}
    if decision.reason in {"high_correlation", "cluster_representative_lost"}:
        return {
            **base,
            "feature_retenida": decision.max_corr_with,
            "rho": decision.max_abs_corr,
            "method": config.correlation.method,
        }
    if decision.reason == "high_vif":
        return {**base, "vif": decision.vif, "iteration": vif_iterations.get(decision.feature)}
    if decision.reason == "high_stability":
        return {**base, "max_csi": decision.max_csi}
    if decision.detail is not None:
        return {**base, "detalle": decision.detail}
    return base


def _decision_action(decision: VariableSelectionDecision) -> str:
    """Normaliza la acción auditada desde la decisión final."""
    if decision.reason in {"business_include", "high_iv"} and decision.included:
        return "conservar_con_flag"
    if decision.included:
        return "incluir"
    return "excluir"


def _optional_float(value: object) -> float | None:
    """Convierte valores numéricos opcionales a ``float`` sin inventar ceros."""
    if value is None:
        return None
    try:
        numeric = float(cast(Any, value))
    except (TypeError, ValueError):
        return None
    if numeric == 0.0:
        return 0.0
    return numeric
