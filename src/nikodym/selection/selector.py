"""Selector sklearn-like de variables WoE para scorecards (SDD-07 §4).

``FeatureSelector`` consume artefactos ya publicados por ``binning``: columnas WoE, resumen IV y
``woe_column_map``. Ajusta todos los filtros que deciden inclusión usando solo la partición
Desarrollo; Holdout/OOT alimentan únicamente diagnósticos PSI/CSI. La auditoría persistente y el
ensamblado con ``Study`` quedan para ``SelectionStep`` (B7.4).

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
import warnings
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias, cast

from pydantic import ValidationError

from nikodym.core.base import NikodymTransformer
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    SelectionPriority,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.selection.exceptions import SelectionFitError, SelectionTransformError

_SCORING_EXTRA_MESSAGE = (
    "FeatureSelector requiere scikit-learn/statsmodels; instale nikodym[scoring]."
)

try:
    from sklearn.base import BaseEstimator, TransformerMixin  # type: ignore[import-untyped]
except ModuleNotFoundError as exc:
    raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.audit import AuditSink
    from nikodym.selection.results import VariableSelectionDecision

    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any
    VariableSelectionDecision: TypeAlias = Any

__all__ = ["FeatureSelector"]

_STRUCTURAL_COLUMNS: tuple[str, ...] = ("target", "label_status", "partition", "ttd")
_PARTITION_DESARROLLO = "desarrollo"
_KNOWN_VIF_DIVIDE_BY_ZERO_WARNING = "divide by zero encountered in scalar divide"
_VIF_WARNING_MODULE = r"statsmodels\.stats\.outliers_influence"
_NUMERIC_PRIORITIES: tuple[SelectionPriority, ...] = ("iv", "auc", "ks", "gini")
_ALL_PRIORITIES: tuple[SelectionPriority, ...] = ("iv", "auc", "ks", "gini", "name")
_SELECTION_TABLE_COLUMNS: tuple[str, ...] = (
    "feature",
    "woe_column",
    "included",
    "reason",
    "iv",
    "iv_band",
    "auc",
    "gini",
    "ks",
    "max_abs_corr",
    "max_corr_with",
    "vif",
    "max_csi",
    "forced",
    "detail",
)
_STABILITY_TABLE_COLUMNS: tuple[str, ...] = (
    "feature",
    "woe_column",
    "sample",
    "csi",
    "csi_band",
    "smoothing",
)
_VIF_TABLE_COLUMNS: tuple[str, ...] = (
    "iteration",
    "feature",
    "woe_column",
    "vif",
    "removed",
    "reason",
)


class FeatureSelector(TransformerMixin, BaseEstimator, NikodymTransformer):  # type: ignore[misc]
    """Selector sklearn-like de columnas WoE para scorecard."""

    config_cls: ClassVar[type[SelectionConfig]] = SelectionConfig

    def __init__(
        self,
        *,
        feature_columns: tuple[str, ...] | Literal["*"] = "*",
        exclude_columns: tuple[str, ...] = (),
        force_include: tuple[str, ...] = (),
        force_exclude: tuple[str, ...] = (),
        min_iv: float = 0.02,
        max_iv: float | None = 0.50,
        max_iv_action: Literal["flag", "exclude"] = "flag",
        compute_univariate_metrics: bool = True,
        min_auc: float | None = None,
        min_ks: float | None = None,
        min_gini: float | None = None,
        priority_order: tuple[SelectionPriority, ...] = ("iv", "auc", "ks", "name"),
        correlation_enabled: bool = True,
        correlation_method: Literal["pearson", "spearman", "kendall"] = "pearson",
        correlation_threshold: float = 0.75,
        clustering_method: Literal["none", "connected_components"] = "none",
        vif_enabled: bool = True,
        vif_threshold: float = 5.0,
        vif_add_intercept: bool = True,
        vif_max_iterations: int | None = None,
        stability_enabled: bool = True,
        stability_action: Literal["report_only", "exclude"] = "report_only",
        stability_stable_threshold: float = 0.10,
        stability_review_threshold: float = 0.25,
        stability_smoothing: float = 1e-6,
        keep_structural_columns: bool = True,
        fail_if_no_features: bool = True,
    ) -> None:
        """Asigna hiperparámetros sin transformar para preservar ``clone`` de sklearn."""
        self.feature_columns = feature_columns
        self.exclude_columns = exclude_columns
        self.force_include = force_include
        self.force_exclude = force_exclude
        self.min_iv = min_iv
        self.max_iv = max_iv
        self.max_iv_action = max_iv_action
        self.compute_univariate_metrics = compute_univariate_metrics
        self.min_auc = min_auc
        self.min_ks = min_ks
        self.min_gini = min_gini
        self.priority_order = priority_order
        self.correlation_enabled = correlation_enabled
        self.correlation_method = correlation_method
        self.correlation_threshold = correlation_threshold
        self.clustering_method = clustering_method
        self.vif_enabled = vif_enabled
        self.vif_threshold = vif_threshold
        self.vif_add_intercept = vif_add_intercept
        self.vif_max_iterations = vif_max_iterations
        self.stability_enabled = stability_enabled
        self.stability_action = stability_action
        self.stability_stable_threshold = stability_stable_threshold
        self.stability_review_threshold = stability_review_threshold
        self.stability_smoothing = stability_smoothing
        self.keep_structural_columns = keep_structural_columns
        self.fail_if_no_features = fail_if_no_features

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> FeatureSelector:
        """Construye ``FeatureSelector`` desde ``SelectionConfig`` y sus sub-configs."""
        if not isinstance(cfg, SelectionConfig):
            cfg = SelectionConfig.model_validate(cfg)
        return cls(
            feature_columns=cfg.feature_columns,
            exclude_columns=cfg.exclude_columns,
            force_include=cfg.force_include,
            force_exclude=cfg.force_exclude,
            min_iv=cfg.min_iv,
            max_iv=cfg.max_iv,
            max_iv_action=cfg.max_iv_action,
            compute_univariate_metrics=cfg.compute_univariate_metrics,
            min_auc=cfg.min_auc,
            min_ks=cfg.min_ks,
            min_gini=cfg.min_gini,
            priority_order=cfg.priority_order,
            correlation_enabled=cfg.correlation.enabled,
            correlation_method=cfg.correlation.method,
            correlation_threshold=cfg.correlation.threshold,
            clustering_method=cfg.correlation.clustering_method,
            vif_enabled=cfg.vif.enabled,
            vif_threshold=cfg.vif.threshold,
            vif_add_intercept=cfg.vif.add_intercept,
            vif_max_iterations=cfg.vif.max_iterations,
            stability_enabled=cfg.stability.enabled,
            stability_action=cfg.stability.action,
            stability_stable_threshold=cfg.stability.stable_threshold,
            stability_review_threshold=cfg.stability.review_threshold,
            stability_smoothing=cfg.stability.smoothing,
            keep_structural_columns=cfg.keep_structural_columns,
            fail_if_no_features=cfg.fail_if_no_features,
        )

    def fit(
        self,
        woe_frame: DataFrame,
        *,
        target_col: str,
        partition_col: str,
        binning_summary: DataFrame,
        woe_column_map: Mapping[str, str],
        audit: AuditSink | None = None,
    ) -> Self:
        """Ajusta filtros de selección sobre Desarrollo sin mutar artefactos de entrada."""
        pd = _import_pandas()
        np = _import_numpy()
        _validate_runtime_config(self)
        frame = _as_dataframe(woe_frame, pd, context="fit")
        summary = _as_dataframe(binning_summary, pd, context="fit")
        _validate_unique_columns(frame, error_cls=SelectionFitError)
        _validate_required_columns(frame, target_col=target_col, partition_col=partition_col)

        candidates = _resolve_candidates(
            frame=frame,
            summary=summary,
            woe_column_map=woe_column_map,
            feature_columns=self.feature_columns,
            exclude_columns=self.exclude_columns,
            force_include=self.force_include,
            force_exclude=self.force_exclude,
            pd=pd,
        )
        dev = _development_frame(frame, target_col=target_col, partition_col=partition_col)
        target = _development_target(dev[target_col])
        states = _initial_candidate_states(candidates, summary, pd)
        _validate_forced_finite(states, dev, self.force_include, self.force_exclude, np=np)

        compute_metrics = (
            self.compute_univariate_metrics
            or self.min_auc is not None
            or self.min_ks is not None
            or self.min_gini is not None
        )
        _apply_univariate_metrics(states, dev, target, compute_metrics=compute_metrics)
        _apply_initial_filters(states, self, dev, np=np)

        ranked_features = _rank_features(
            tuple(feature for feature, state in states.items() if state.included),
            states,
            self.priority_order,
        )
        correlation_matrix = _correlation_matrix(
            dev,
            states,
            ranked_features,
            method=self.correlation_method,
            pd=pd,
        )
        if self.correlation_enabled and len(ranked_features) > 1:
            if self.clustering_method == "connected_components":
                _apply_correlation_components(
                    states,
                    ranked_features,
                    correlation_matrix,
                    threshold=self.correlation_threshold,
                )
            else:
                _apply_correlation_pruning(
                    states,
                    ranked_features,
                    correlation_matrix,
                    threshold=self.correlation_threshold,
                )

        ranked_after_correlation = _rank_features(
            tuple(feature for feature, state in states.items() if state.included),
            states,
            self.priority_order,
        )
        vif_table = _apply_vif_filter(
            states=states,
            dev=dev,
            ranked_features=ranked_after_correlation,
            enabled=self.vif_enabled,
            threshold=self.vif_threshold,
            add_intercept=self.vif_add_intercept,
            max_iterations=self.vif_max_iterations,
            pd=pd,
            np=np,
        )
        stability_table = _stability_table(
            frame=frame,
            dev=dev,
            states=states,
            partition_col=partition_col,
            enabled=self.stability_enabled,
            action=self.stability_action,
            stable_threshold=self.stability_stable_threshold,
            review_threshold=self.stability_review_threshold,
            smoothing=self.stability_smoothing,
            pd=pd,
        )
        _apply_stability_action(
            states,
            stability_table,
            action=self.stability_action,
            review_threshold=self.stability_review_threshold,
        )

        selected_features = _rank_features(
            tuple(feature for feature, state in states.items() if state.included),
            states,
            self.priority_order,
        )
        if not selected_features and self.fail_if_no_features:
            raise SelectionFitError(
                "No quedó ninguna variable seleccionada tras aplicar filtros de selection."
            )

        self.candidate_features_ = tuple(sorted(states))
        self.candidate_woe_columns_ = tuple(
            states[feature].woe_column for feature in self.candidate_features_
        )
        self.selected_features_ = selected_features
        self.selected_woe_columns_ = tuple(
            states[feature].woe_column for feature in selected_features
        )
        self.excluded_features_ = {
            feature: state.reason for feature, state in states.items() if not state.included
        }
        self.correlation_matrix_ = _normalize_numeric_dataframe(correlation_matrix, pd)
        self.vif_table_ = _normalize_numeric_dataframe(vif_table, pd)
        self.stability_table_ = _normalize_numeric_dataframe(stability_table, pd)
        self.structural_columns_ = _structural_columns(frame, target_col, partition_col)
        self.selection_table_ = _selection_table(states, pd)
        self.decisions_ = _decision_log(states)
        self.decision_log_ = self.decisions_
        self.selected_woe_frame_ = self.transform(frame)
        self.result_ = _selection_result(self, self.selected_woe_frame_)

        if audit is not None:
            self._audit = audit
            _emit_audit_log(self, states)
        return self

    def transform(self, woe_frame: DataFrame) -> DataFrame:
        """Filtra el frame WoE a columnas estructurales y variables seleccionadas."""
        self._check_fitted()
        pd = _import_pandas()
        np = _import_numpy()
        frame = _as_dataframe(woe_frame, pd, context="transform")
        missing = [column for column in self.selected_woe_columns_ if column not in frame.columns]
        if missing:
            joined = ", ".join(f"'{column}'" for column in missing)
            raise SelectionTransformError(
                f"FeatureSelector.transform requiere columnas WoE fiteadas; faltan: {joined}."
            )
        for column in self.selected_woe_columns_:
            values = frame[column].to_numpy(dtype="float64", copy=True)
            if not bool(np.isfinite(values).all()):
                raise SelectionTransformError(
                    "FeatureSelector.transform no puede publicar WoE no finita: "
                    f"columna='{column}'."
                )

        columns: list[str] = []
        if self.keep_structural_columns:
            columns.extend(column for column in self.structural_columns_ if column in frame.columns)
        columns.extend(self.selected_woe_columns_)
        return frame.loc[:, columns].copy(deep=True)

    def fit_transform(self, woe_frame: DataFrame, **kwargs: Any) -> DataFrame:
        """Ajusta la selección y devuelve el frame WoE filtrado para el mismo input."""
        return self.fit(woe_frame, **kwargs).transform(woe_frame)


@dataclass
class CandidateState:
    """Estado interno de una feature candidata durante el ajuste."""

    feature: str
    woe_column: str
    iv: float
    included: bool = True
    reason: str = "included"
    auc: float | None = None
    gini: float | None = None
    ks: float | None = None
    max_abs_corr: float | None = None
    max_corr_with: str | None = None
    vif: float | None = None
    max_csi: float | None = None
    forced: Literal["include", "exclude"] | None = None
    detail: str | None = None


def _import_pandas() -> Any:
    """Importa pandas localmente para preservar el import liviano de ``nikodym.selection``."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "FeatureSelector requiere pandas; instale las dependencias base de nikodym."
        ) from exc


def _import_numpy() -> Any:
    """Importa numpy localmente para cálculos de finitud y matrices."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "FeatureSelector requiere numpy; instale las dependencias base de nikodym."
        ) from exc


def _import_sklearn_metrics() -> tuple[Any, Any]:
    """Importa métricas de sklearn y traduce la ausencia del extra scoring."""
    try:
        metrics = importlib.import_module("sklearn.metrics")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return metrics.roc_auc_score, metrics.roc_curve


def _import_variance_inflation_factor() -> Any:
    """Importa VIF de statsmodels y traduce la ausencia del extra scoring."""
    try:
        module = importlib.import_module("statsmodels.stats.outliers_influence")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return module.variance_inflation_factor


def _validate_runtime_config(estimator: FeatureSelector) -> None:
    """Revalida los hiperparámetros planos contra ``SelectionConfig``."""
    try:
        _config_from_estimator(estimator)
    except (ConfigError, ValidationError) as exc:
        raise ConfigError(f"Hiperparámetros inválidos para FeatureSelector: {exc}") from exc


def _config_from_estimator(estimator: FeatureSelector) -> SelectionConfig:
    """Reconstruye el config anidado desde los parámetros planos del selector."""
    return SelectionConfig(
        feature_columns=estimator.feature_columns,
        exclude_columns=estimator.exclude_columns,
        force_include=estimator.force_include,
        force_exclude=estimator.force_exclude,
        min_iv=estimator.min_iv,
        max_iv=estimator.max_iv,
        max_iv_action=estimator.max_iv_action,
        compute_univariate_metrics=estimator.compute_univariate_metrics,
        min_auc=estimator.min_auc,
        min_ks=estimator.min_ks,
        min_gini=estimator.min_gini,
        priority_order=estimator.priority_order,
        correlation=CorrelationSelectionConfig(
            enabled=estimator.correlation_enabled,
            method=estimator.correlation_method,
            threshold=estimator.correlation_threshold,
            clustering_method=estimator.clustering_method,
        ),
        vif=VifSelectionConfig(
            enabled=estimator.vif_enabled,
            threshold=estimator.vif_threshold,
            add_intercept=estimator.vif_add_intercept,
            max_iterations=estimator.vif_max_iterations,
        ),
        stability=StabilitySelectionConfig(
            enabled=estimator.stability_enabled,
            action=estimator.stability_action,
            stable_threshold=estimator.stability_stable_threshold,
            review_threshold=estimator.stability_review_threshold,
            smoothing=estimator.stability_smoothing,
        ),
        keep_structural_columns=estimator.keep_structural_columns,
        fail_if_no_features=estimator.fail_if_no_features,
    )


def _as_dataframe(df: object, pd: Any, *, context: str) -> DataFrame:
    """Valida y copia defensivamente una entrada tabular."""
    if not isinstance(df, pd.DataFrame):
        error_cls = SelectionFitError if context == "fit" else SelectionTransformError
        raise error_cls(
            "FeatureSelector requiere pandas.DataFrame; "
            f"contexto='{context}', tipo observado={type(df).__name__}."
        )
    return cast(DataFrame, df.copy(deep=True))


def _validate_unique_columns(frame: DataFrame, *, error_cls: type[Exception]) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise error_cls(
            f"FeatureSelector requiere nombres de columnas únicos; duplicadas: {joined}."
        )


def _validate_required_columns(frame: DataFrame, *, target_col: str, partition_col: str) -> None:
    """Valida target y partición antes de construir Desarrollo."""
    missing = [column for column in (target_col, partition_col) if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise SelectionFitError(f"Faltan columnas requeridas para selection: {joined}.")


def _resolve_candidates(
    *,
    frame: DataFrame,
    summary: DataFrame,
    woe_column_map: Mapping[str, str],
    feature_columns: tuple[str, ...] | Literal["*"],
    exclude_columns: tuple[str, ...],
    force_include: tuple[str, ...],
    force_exclude: tuple[str, ...],
    pd: Any,
) -> dict[str, str]:
    """Resuelve features raw candidatas y su columna WoE asociada."""
    del pd
    mapping = {str(feature): str(column) for feature, column in woe_column_map.items()}
    reverse_mapping = {column: feature for feature, column in mapping.items()}
    summary_rows = _summary_rows(summary)
    publishable = {
        feature for feature, row in summary_rows.items() if bool(row.get("selected", True))
    }
    available = {
        feature
        for feature, woe_column in mapping.items()
        if feature in publishable and woe_column in frame.columns
    }
    _validate_available_woe(mapping, publishable, frame)

    if feature_columns == "*":
        selected = set(available)
    else:
        selected = set(
            _resolve_identifier_sequence(
                feature_columns,
                available,
                mapping,
                reverse_mapping,
                label="feature_columns",
            )
        )

    excluded = set(
        _resolve_identifier_sequence(
            exclude_columns,
            available,
            mapping,
            reverse_mapping,
            label="exclude_columns",
        )
    )
    forced_include = set(
        _resolve_identifier_sequence(
            force_include,
            available,
            mapping,
            reverse_mapping,
            label="force_include",
        )
    )
    forced_exclude = set(
        _resolve_identifier_sequence(
            force_exclude,
            available,
            mapping,
            reverse_mapping,
            label="force_exclude",
        )
    )

    candidate_features = (selected - excluded) | forced_include | forced_exclude
    if not candidate_features:
        raise SelectionFitError(
            "No hay variables candidatas para selection tras resolver overrides."
        )
    return {feature: mapping[feature] for feature in sorted(candidate_features)}


def _summary_rows(summary: DataFrame) -> dict[str, dict[str, object]]:
    """Indexa ``binning_summary`` por nombre de feature."""
    if "name" not in summary.columns:
        raise SelectionFitError("binning_summary debe contener una columna 'name'.")
    duplicated = summary["name"].astype(str).duplicated(keep=False)
    if bool(duplicated.any()):
        repeated = sorted(summary.loc[duplicated, "name"].astype(str).unique())
        raise SelectionFitError(f"binning_summary contiene features duplicadas: {repeated}.")
    rows: dict[str, dict[str, object]] = {}
    for row in cast("list[dict[str, object]]", summary.to_dict(orient="records")):
        feature = str(row["name"])
        rows[feature] = row
    return rows


def _validate_available_woe(
    mapping: Mapping[str, str],
    publishable: set[str],
    frame: DataFrame,
) -> None:
    """Valida que las columnas WoE disponibles existan en el frame."""
    missing_columns = sorted(
        feature
        for feature, woe_column in mapping.items()
        if feature in publishable and woe_column not in frame
    )
    if missing_columns:
        joined = ", ".join(f"'{feature}'" for feature in missing_columns)
        raise SelectionFitError(f"woe_column_map apunta a columna(s) inexistente(s): {joined}.")


def _resolve_identifier_sequence(
    identifiers: tuple[str, ...],
    available: set[str],
    mapping: Mapping[str, str],
    reverse_mapping: Mapping[str, str],
    *,
    label: str,
) -> tuple[str, ...]:
    """Resuelve identificadores raw o WoE y falla ante nombres no publicables por binning."""
    resolved: list[str] = []
    missing: list[str] = []
    for identifier in identifiers:
        if identifier in available:
            resolved.append(identifier)
        elif identifier in reverse_mapping and reverse_mapping[identifier] in available:
            resolved.append(reverse_mapping[identifier])
        else:
            missing.append(identifier)
    if missing:
        joined = ", ".join(f"'{name}'" for name in sorted(missing))
        available_names = ", ".join(f"'{name}'" for name in sorted(mapping))
        raise SelectionFitError(
            f"{label} declara variable(s) inexistente(s) o no binneada(s): {joined}; "
            f"disponibles en woe_column_map: {available_names}."
        )
    return tuple(dict.fromkeys(resolved))


def _development_frame(frame: DataFrame, *, target_col: str, partition_col: str) -> DataFrame:
    """Devuelve la muestra Desarrollo con target no nulo, sin tocar Holdout/OOT."""
    dev_mask = (
        frame[partition_col].astype(str).eq(_PARTITION_DESARROLLO) & frame[target_col].notna()
    )
    dev = frame.loc[dev_mask].copy(deep=True)
    if dev.empty:
        raise SelectionFitError("La partición Desarrollo no contiene filas con target no nulo.")
    return dev


def _development_target(target: Series) -> Series:
    """Valida target binario 0/1 con ambas clases en Desarrollo."""
    invalid = ~target.isin((0, 1))
    if bool(invalid.any()):
        observed = sorted(str(value) for value in target.loc[invalid].unique())
        raise SelectionFitError(
            "El target de selection debe contener solo 0/1 en Desarrollo; "
            f"valores inválidos={observed}."
        )
    classes = set(int(value) for value in target.unique())
    if classes != {0, 1}:
        raise SelectionFitError(
            "Target degenerado para selection: Desarrollo requiere ambas clases 0 y 1; "
            f"clases observadas={sorted(classes)}."
        )
    return cast(Series, target.astype("int64").copy(deep=True))


def _initial_candidate_states(
    candidates: Mapping[str, str],
    summary: DataFrame,
    pd: Any,
) -> dict[str, CandidateState]:
    """Crea el estado inicial con IV consumido desde ``binning_summary``."""
    del pd
    rows = _summary_rows(summary)
    states: dict[str, CandidateState] = {}
    for feature, woe_column in candidates.items():
        raw_iv = rows[feature].get("iv")
        try:
            iv = float(cast(Any, raw_iv))
        except (TypeError, ValueError) as exc:
            raise SelectionFitError(
                f"binning_summary.iv inválido para feature='{feature}': {raw_iv!r}."
            ) from exc
        if not math.isfinite(iv) or iv < 0.0:
            raise SelectionFitError(
                f"binning_summary.iv debe ser finito y no negativo: feature='{feature}', iv={iv!r}."
            )
        states[feature] = CandidateState(
            feature=feature,
            woe_column=woe_column,
            iv=_normalize_float(iv),
        )
    return states


def _validate_forced_finite(
    states: Mapping[str, CandidateState],
    dev: DataFrame,
    force_include: tuple[str, ...],
    force_exclude: tuple[str, ...],
    *,
    np: Any,
) -> None:
    """Falla si un override apunta a WoE no finita en Desarrollo."""
    forced = set(force_include) | set(force_exclude)
    reverse = {state.woe_column: feature for feature, state in states.items()}
    raw_forced = {reverse.get(name, name) for name in forced}
    nonfinite = []
    for feature in sorted(raw_forced):
        state = states.get(feature)
        if state is None:
            continue
        values = dev[state.woe_column].to_numpy(dtype="float64", copy=True)
        if not bool(np.isfinite(values).all()):
            nonfinite.append(feature)
    if nonfinite:
        joined = ", ".join(f"'{feature}'" for feature in nonfinite)
        raise SelectionFitError(f"Overrides apuntan a columnas WoE no finitas: {joined}.")


def _apply_univariate_metrics(
    states: Mapping[str, CandidateState],
    dev: DataFrame,
    target: Series,
    *,
    compute_metrics: bool,
) -> None:
    """Calcula AUC/Gini/KS una vez por candidata sobre ``risk_score = -WoE``."""
    if not compute_metrics:
        return
    roc_auc_score, roc_curve = _import_sklearn_metrics()
    y_true = target.to_numpy(dtype="int64", copy=True)
    for state in states.values():
        risk_score = -dev[state.woe_column].to_numpy(dtype="float64", copy=True)
        if not all(math.isfinite(float(value)) for value in risk_score.tolist()):
            continue
        auc = float(roc_auc_score(y_true, risk_score))
        fpr, tpr, _ = roc_curve(y_true, risk_score, pos_label=1)
        ks = max(abs(float(tp) - float(fp)) for tp, fp in zip(tpr, fpr, strict=True))
        state.auc = _normalize_float(auc)
        state.gini = _normalize_float((2.0 * auc) - 1.0)
        state.ks = _normalize_float(ks)


def _apply_initial_filters(
    states: Mapping[str, CandidateState],
    estimator: FeatureSelector,
    dev: DataFrame,
    *,
    np: Any,
) -> None:
    """Aplica exclusiones técnicas, negocio e IV/AUC/KS/Gini antes del ranking."""
    for feature in sorted(states):
        state = states[feature]
        if feature in estimator.force_exclude:
            _exclude(state, "business_exclude", forced="exclude")
            continue
        if feature in estimator.force_include:
            state.forced = "include"
            state.reason = "business_include"

        values = dev[state.woe_column].to_numpy(dtype="float64", copy=True)
        if not bool(np.isfinite(values).all()) or len(set(values.tolist())) <= 1:
            if state.forced == "include":
                raise SelectionFitError(
                    "force_include no puede conservar una variable constante o no finita: "
                    f"feature='{feature}'."
                )
            _exclude(state, "constant_or_nonfinite")
            continue
        if state.forced == "include":
            continue
        if state.iv < estimator.min_iv:
            _exclude(
                state,
                "low_iv",
                detail=f"iv={state.iv:.12g} < min_iv={estimator.min_iv:.12g}",
            )
            continue
        if estimator.max_iv is not None and state.iv >= estimator.max_iv:
            if estimator.max_iv_action == "exclude":
                _exclude(
                    state,
                    "high_iv",
                    detail=f"iv={state.iv:.12g} >= max_iv={estimator.max_iv:.12g}",
                )
                continue
            state.reason = "high_iv"
            state.detail = f"iv={state.iv:.12g} >= max_iv={estimator.max_iv:.12g}"
        if estimator.min_auc is not None and _metric_below(state.auc, estimator.min_auc):
            _exclude(state, "low_auc")
            continue
        if estimator.min_ks is not None and _metric_below(state.ks, estimator.min_ks):
            _exclude(state, "low_ks")
            continue
        if estimator.min_gini is not None and _metric_below(state.gini, estimator.min_gini):
            _exclude(state, "low_gini")


def _metric_below(value: float | None, threshold: float) -> bool:
    """Indica si una métrica ausente o finita cae bajo el umbral."""
    return value is None or value < threshold


def _exclude(
    state: CandidateState,
    reason: str,
    *,
    forced: Literal["include", "exclude"] | None = None,
    detail: str | None = None,
) -> None:
    """Marca una candidata como excluida con motivo normalizado."""
    state.included = False
    state.reason = reason
    state.forced = forced if forced is not None else state.forced
    state.detail = detail


def _rank_features(
    features: tuple[str, ...],
    states: Mapping[str, CandidateState],
    priority_order: tuple[SelectionPriority, ...],
) -> tuple[str, ...]:
    """Ordena features de forma total y determinista según ``priority_order``."""
    priorities = _canonical_priorities(priority_order)

    def sort_key(feature: str) -> tuple[object, ...]:
        state = states[feature]
        parts: list[object] = []
        for priority in priorities:
            if priority == "name":
                parts.append(feature)
            else:
                parts.append(-_priority_metric(state, priority))
        return tuple(parts)

    return tuple(sorted(features, key=sort_key))


def _canonical_priorities(
    priority_order: tuple[SelectionPriority, ...],
) -> tuple[SelectionPriority, ...]:
    """Elimina duplicados y completa métricas ausentes para mantener un orden total."""
    ordered: list[SelectionPriority] = []
    for token in priority_order:
        if token in _ALL_PRIORITIES and token not in ordered:
            ordered.append(token)
    for token in _NUMERIC_PRIORITIES:
        if token not in ordered:
            ordered.append(token)
    if "name" not in ordered:
        ordered.append("name")
    return tuple(ordered)


def _priority_metric(state: CandidateState, priority: SelectionPriority) -> float:
    """Devuelve métrica finita para ranking; los valores ausentes pierden."""
    value = getattr(state, priority)
    if isinstance(value, int | float) and math.isfinite(float(value)):
        return float(value)
    return -math.inf


def _correlation_matrix(
    dev: DataFrame,
    states: Mapping[str, CandidateState],
    ranked_features: tuple[str, ...],
    *,
    method: Literal["pearson", "spearman", "kendall"],
    pd: Any,
) -> DataFrame:
    """Calcula matriz de correlación Dev entre sobrevivientes hard."""
    if not ranked_features:
        return cast(DataFrame, pd.DataFrame())
    columns = [states[feature].woe_column for feature in ranked_features]
    return dev.loc[:, columns].copy(deep=True).corr(method=method)


def _apply_correlation_pruning(
    states: Mapping[str, CandidateState],
    ranked_features: tuple[str, ...],
    correlation_matrix: DataFrame,
    *,
    threshold: float,
) -> None:
    """Aplica poda greedy por correlación preservando variables forzadas."""
    retained: list[str] = []
    for feature in ranked_features:
        state = states[feature]
        if not state.included:
            continue
        conflicts = _correlation_conflicts(feature, retained, states, correlation_matrix, threshold)
        if not conflicts:
            retained.append(feature)
            continue
        forced_conflicts = [other for other, _ in conflicts if states[other].forced == "include"]
        if state.forced == "include":
            if not forced_conflicts:
                _remove_non_forced_conflicts(states, retained, conflicts, state)
            retained.append(feature)
            continue
        corr_with, corr_value = _strongest_conflict(conflicts)
        state.max_abs_corr = corr_value
        state.max_corr_with = corr_with
        _exclude(
            state,
            "high_correlation",
            detail=f"|rho|={corr_value:.12g} > threshold={threshold:.12g}",
        )


def _apply_correlation_components(
    states: Mapping[str, CandidateState],
    ranked_features: tuple[str, ...],
    correlation_matrix: DataFrame,
    *,
    threshold: float,
) -> None:
    """Agrupa componentes por correlación alta y conserva el mejor rankeado de cada una."""
    rank = {feature: index for index, feature in enumerate(ranked_features)}
    parent = {feature: feature for feature in ranked_features}

    def find(feature: str) -> str:
        while parent[feature] != feature:
            parent[feature] = parent[parent[feature]]
            feature = parent[feature]
        return feature

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for index, left in enumerate(ranked_features):
        for right in ranked_features[index + 1 :]:
            corr = _abs_corr(left, right, states, correlation_matrix)
            if corr is not None and corr > threshold:
                union(left, right)

    components: dict[str, list[str]] = {}
    for feature in ranked_features:
        components.setdefault(find(feature), []).append(feature)
    for members in components.values():
        winner = min(members, key=lambda feature: rank[feature])
        for feature in members:
            if feature == winner:
                continue
            corr = _abs_corr(feature, winner, states, correlation_matrix)
            state = states[feature]
            state.max_abs_corr = corr
            state.max_corr_with = winner
            _exclude(state, "cluster_representative_lost")


def _correlation_conflicts(
    feature: str,
    retained: list[str],
    states: Mapping[str, CandidateState],
    correlation_matrix: DataFrame,
    threshold: float,
) -> list[tuple[str, float]]:
    """Lista retenidas que superan el umbral contra la candidata actual."""
    conflicts: list[tuple[str, float]] = []
    for other in retained:
        corr = _abs_corr(feature, other, states, correlation_matrix)
        if corr is not None and corr > threshold:
            conflicts.append((other, corr))
    return conflicts


def _remove_non_forced_conflicts(
    states: Mapping[str, CandidateState],
    retained: list[str],
    conflicts: list[tuple[str, float]],
    current: CandidateState,
) -> None:
    """Elimina retenidas no forzadas cuando entra una variable forzada."""
    for other, corr_value in conflicts:
        other_state = states[other]
        retained.remove(other)
        other_state.max_abs_corr = corr_value
        other_state.max_corr_with = current.feature
        _exclude(other_state, "high_correlation", detail="desplazada por force_include")


def _strongest_conflict(conflicts: list[tuple[str, float]]) -> tuple[str, float]:
    """Escoge el conflicto más fuerte con desempate lexicográfico."""
    return max(conflicts, key=lambda item: (item[1], item[0]))


def _abs_corr(
    left: str,
    right: str,
    states: Mapping[str, CandidateState],
    correlation_matrix: DataFrame,
) -> float | None:
    """Lee una correlación absoluta finita entre dos features."""
    left_column = states[left].woe_column
    right_column = states[right].woe_column
    if (
        left_column not in correlation_matrix.index
        or right_column not in correlation_matrix.columns
    ):
        return None
    value = float(cast(Any, correlation_matrix.loc[left_column, right_column]))
    if not math.isfinite(value):
        return None
    return _normalize_float(abs(value))


def _apply_vif_filter(
    *,
    states: Mapping[str, CandidateState],
    dev: DataFrame,
    ranked_features: tuple[str, ...],
    enabled: bool,
    threshold: float,
    add_intercept: bool,
    max_iterations: int | None,
    pd: Any,
    np: Any,
) -> DataFrame:
    """Aplica VIF iterativo con captura local del warning de colinealidad perfecta."""
    if not enabled or not ranked_features:
        return cast(DataFrame, pd.DataFrame(columns=_VIF_TABLE_COLUMNS))
    remaining = list(ranked_features)
    if len(remaining) == 1:
        state = states[remaining[0]]
        state.vif = 1.0
        return cast(
            DataFrame,
            pd.DataFrame(
                [
                    {
                        "iteration": 0,
                        "feature": state.feature,
                        "woe_column": state.woe_column,
                        "vif": 1.0,
                        "removed": False,
                        "reason": None,
                    }
                ],
                columns=_VIF_TABLE_COLUMNS,
            ),
        )

    n_dev = len(dev)
    if n_dev <= len(remaining) + 1:
        raise SelectionFitError(
            "Muestra Desarrollo insuficiente para VIF: "
            f"n_dev={n_dev}, p={len(remaining)}, regla n_dev > p + 1."
        )

    rows: list[dict[str, object]] = []
    iteration = 0
    while True:
        vif_values = _compute_vif_values(
            dev,
            remaining,
            states,
            add_intercept=add_intercept,
            np=np,
        )
        row_indexes: dict[str, int] = {}
        for feature in remaining:
            state = states[feature]
            state.vif = vif_values[feature]
            row_indexes[feature] = len(rows)
            rows.append(
                {
                    "iteration": iteration,
                    "feature": feature,
                    "woe_column": state.woe_column,
                    "vif": _normalize_float(vif_values[feature]),
                    "removed": False,
                    "reason": None,
                }
            )
        if not _has_vif_over_threshold(vif_values, threshold):
            break
        removable = [feature for feature in remaining if states[feature].forced != "include"]
        if not removable:
            raise SelectionFitError(
                "VIF excede el umbral sólo entre variables force_include; "
                f"umbral={threshold}, valores={vif_values!r}."
            )
        to_remove = max(
            removable,
            key=lambda feature: _vif_removal_key(feature, vif_values, ranked_features),
        )
        states[to_remove].included = False
        states[to_remove].reason = "high_vif"
        states[to_remove].detail = f"vif={vif_values[to_remove]!r} > threshold={threshold:.12g}"
        remaining.remove(to_remove)
        removed_row = rows[row_indexes[to_remove]]
        removed_row["removed"] = True
        removed_row["reason"] = "high_vif"
        if len(remaining) <= 1:
            states[remaining[0]].vif = 1.0
            break
        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            break
    return cast(DataFrame, pd.DataFrame(rows, columns=_VIF_TABLE_COLUMNS))


def _compute_vif_values(
    dev: DataFrame,
    features: list[str],
    states: Mapping[str, CandidateState],
    *,
    add_intercept: bool,
    np: Any,
) -> dict[str, float]:
    """Calcula VIF por feature usando statsmodels y constante explícita opcional."""
    variance_inflation_factor = _import_variance_inflation_factor()
    columns = [states[feature].woe_column for feature in features]
    exog = dev.loc[:, columns].to_numpy(dtype="float64", copy=True)
    offset = 0
    if add_intercept:
        intercept = np.ones((exog.shape[0], 1), dtype="float64")
        exog = np.concatenate([intercept, exog], axis=1)
        offset = 1
    values: dict[str, float] = {}
    with _suppress_known_vif_warning():
        for index, feature in enumerate(features):
            value = float(variance_inflation_factor(exog, index + offset))
            values[feature] = _normalize_float(value)
    return values


def _has_vif_over_threshold(vif_values: Mapping[str, float], threshold: float) -> bool:
    """Detecta VIF sobre umbral tratando NaN/inf como exceso."""
    return any(not math.isfinite(value) or value > threshold for value in vif_values.values())


def _vif_removal_key(
    feature: str,
    vif_values: Mapping[str, float],
    ranked_features: tuple[str, ...],
) -> tuple[int, float, int, str]:
    """Ordena determinísticamente candidatos a eliminación por VIF."""
    value = vif_values[feature]
    nonfinite = not math.isfinite(value)
    comparable = math.inf if nonfinite else value
    rank_position = ranked_features.index(feature)
    return (int(nonfinite), comparable, rank_position, feature)


def _stability_table(
    *,
    frame: DataFrame,
    dev: DataFrame,
    states: Mapping[str, CandidateState],
    partition_col: str,
    enabled: bool,
    action: Literal["report_only", "exclude"],
    stable_threshold: float,
    review_threshold: float,
    smoothing: float,
    pd: Any,
) -> DataFrame:
    """Calcula PSI/CSI por variable y muestra usando Desarrollo como expected."""
    del action
    if not enabled:
        return cast(DataFrame, pd.DataFrame(columns=_STABILITY_TABLE_COLUMNS))
    samples = tuple(
        sample
        for sample in sorted(frame[partition_col].dropna().astype(str).unique())
        if sample != _PARTITION_DESARROLLO
    )
    rows: list[dict[str, object]] = []
    for feature in sorted(states):
        state = states[feature]
        expected = dev[state.woe_column]
        for sample in samples:
            actual = frame.loc[frame[partition_col].astype(str).eq(sample), state.woe_column]
            csi = _psi(expected, actual, smoothing=smoothing)
            band = _csi_band(
                csi,
                stable_threshold=stable_threshold,
                review_threshold=review_threshold,
            )
            rows.append(
                {
                    "feature": feature,
                    "woe_column": state.woe_column,
                    "sample": sample,
                    "csi": csi,
                    "csi_band": band,
                    "smoothing": smoothing,
                }
            )
        feature_csi = [float(cast(float, row["csi"])) for row in rows if row["feature"] == feature]
        state.max_csi = _normalize_float(max(feature_csi)) if feature_csi else None
    return cast(DataFrame, pd.DataFrame(rows, columns=_STABILITY_TABLE_COLUMNS))


def _psi(expected: Series, actual: Series, *, smoothing: float) -> float:
    """Calcula PSI/CSI con suavizado aditivo sobre categorías observadas."""
    categories = sorted(set(expected.tolist()) | set(actual.tolist()))
    if not categories:
        return 0.0
    expected_counts = expected.value_counts(dropna=False)
    actual_counts = actual.value_counts(dropna=False)
    expected_denominator = float(len(expected)) + (smoothing * len(categories))
    actual_denominator = float(len(actual)) + (smoothing * len(categories))
    total = 0.0
    for category in categories:
        expected_rate = (
            float(expected_counts.get(category, 0.0)) + smoothing
        ) / expected_denominator
        actual_rate = (float(actual_counts.get(category, 0.0)) + smoothing) / actual_denominator
        total += (actual_rate - expected_rate) * math.log(actual_rate / expected_rate)
    return _normalize_float(total)


def _csi_band(value: float, *, stable_threshold: float, review_threshold: float) -> str:
    """Clasifica CSI/PSI en bandas regulatorias de estabilidad."""
    if value < stable_threshold:
        return "stable"
    if value < review_threshold:
        return "review"
    return "redevelop"


def _apply_stability_action(
    states: Mapping[str, CandidateState],
    stability_table: DataFrame,
    *,
    action: Literal["report_only", "exclude"],
    review_threshold: float,
) -> None:
    """Aplica exclusión por estabilidad sólo si el usuario la activó explícitamente."""
    if action != "exclude" or stability_table.empty:
        return
    unstable = stability_table.loc[stability_table["csi"].ge(review_threshold), "feature"]
    for feature in sorted(set(unstable.astype(str).tolist())):
        state = states[feature]
        if state.included and state.forced != "include":
            _exclude(state, "high_stability")


def _selection_table(states: Mapping[str, CandidateState], pd: Any) -> DataFrame:
    """Construye tabla final de decisiones con una fila por candidata."""
    rows = [_state_row(states[feature]) for feature in sorted(states)]
    return cast(DataFrame, pd.DataFrame(rows, columns=_SELECTION_TABLE_COLUMNS))


def _state_row(state: CandidateState) -> dict[str, object]:
    """Serializa una candidata para tablas y decisiones Pydantic."""
    from nikodym.binning.results import iv_band

    return {
        "feature": state.feature,
        "woe_column": state.woe_column,
        "included": state.included,
        "reason": state.reason,
        "iv": _normalize_float(state.iv),
        "iv_band": iv_band(state.iv),
        "auc": _optional_float(state.auc),
        "gini": _optional_float(state.gini),
        "ks": _optional_float(state.ks),
        "max_abs_corr": _optional_float(state.max_abs_corr),
        "max_corr_with": state.max_corr_with,
        "vif": _optional_float(state.vif),
        "max_csi": _optional_float(state.max_csi),
        "forced": state.forced,
        "detail": state.detail,
    }


def _optional_float(value: float | None) -> float | None:
    """Normaliza ``-0.0`` sin convertir ausencias a cero."""
    if value is None:
        return None
    return _normalize_float(float(value))


def _decision_log(states: Mapping[str, CandidateState]) -> tuple[VariableSelectionDecision, ...]:
    """Construye decisiones Pydantic reutilizando la banda IV de binning."""
    from nikodym.selection.results import VariableSelectionDecision

    return tuple(
        VariableSelectionDecision.model_validate(_state_row(states[feature]))
        for feature in sorted(states)
    )


def _selection_result(selector: FeatureSelector, selected_woe_frame: DataFrame) -> Any:
    """Agrupa salidas principales en ``SelectionResult``."""
    from nikodym.selection.results import SelectionResult

    return SelectionResult(
        candidate_features=selector.candidate_features_,
        candidate_woe_columns=selector.candidate_woe_columns_,
        selected_features=selector.selected_features_,
        selected_woe_columns=selector.selected_woe_columns_,
        selected_woe_frame=selected_woe_frame,
        selection_table=selector.selection_table_,
        correlation_matrix=selector.correlation_matrix_,
        vif_table=selector.vif_table_,
        stability_table=selector.stability_table_,
        decisions=selector.decisions_,
    )


def _structural_columns(frame: DataFrame, target_col: str, partition_col: str) -> tuple[str, ...]:
    """Resuelve columnas estructurales que se conservan en ``transform``."""
    requested = (*_STRUCTURAL_COLUMNS, target_col, partition_col)
    return tuple(dict.fromkeys(column for column in requested if column in frame.columns))


def _emit_audit_log(selector: FeatureSelector, states: Mapping[str, CandidateState]) -> None:
    """Registrar decisiones mínimas del fit puro cuando se inyecta un ``AuditSink``."""
    for feature in sorted(states):
        state = states[feature]
        if state.reason == "included":
            continue
        selector.log_decision(
            regla=state.reason,
            umbral=_audit_threshold(selector, state.reason),
            valor=_audit_value(state),
            accion="incluir" if state.included else "excluir",
        )


def _audit_threshold(selector: FeatureSelector, reason: str) -> object:
    """Mapea motivo a umbral auditable."""
    thresholds: dict[str, object] = {
        "low_iv": selector.min_iv,
        "high_iv": selector.max_iv,
        "low_auc": selector.min_auc,
        "low_ks": selector.min_ks,
        "low_gini": selector.min_gini,
        "high_correlation": selector.correlation_threshold,
        "high_vif": selector.vif_threshold,
        "high_stability": selector.stability_review_threshold,
        "business_include": "force_include",
        "business_exclude": "force_exclude",
    }
    return thresholds.get(reason)


def _audit_value(state: CandidateState) -> object:
    """Escoge el valor observado más útil para auditoría."""
    if state.reason in {"low_iv", "high_iv", "business_include", "business_exclude"}:
        return state.iv
    if state.reason == "low_auc":
        return state.auc
    if state.reason == "low_ks":
        return state.ks
    if state.reason == "low_gini":
        return state.gini
    if state.reason == "high_correlation":
        return state.max_abs_corr
    if state.reason == "high_vif":
        return state.vif
    if state.reason == "high_stability":
        return state.max_csi
    return state.detail


def _normalize_numeric_dataframe(df: DataFrame, pd: Any) -> DataFrame:
    """Normaliza ``-0.0`` en columnas flotantes de salida."""
    result = df.copy(deep=True)
    for column in result.columns:
        if pd.api.types.is_float_dtype(result[column]):
            result[column] = result[column].map(lambda value: _normalize_float(float(value)))
    return result


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` y conserva otros valores especiales para decisiones técnicas."""
    if math.isnan(value):
        return value
    if value == 0.0:
        return 0.0
    return value


@contextmanager
def _suppress_known_vif_warning() -> Iterator[None]:
    """Captura sólo el warning conocido de VIF infinito por colinealidad perfecta."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_KNOWN_VIF_DIVIDE_BY_ZERO_WARNING,
            category=RuntimeWarning,
            module=_VIF_WARNING_MODULE,
        )
        yield
