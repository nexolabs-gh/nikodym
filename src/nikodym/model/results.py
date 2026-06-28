"""DTOs puros de resultados del modelo logístico PD (SDD-08 §4).

Este módulo contiene solo contenedores Pydantic y helpers deterministas para publicar salidas ya
calculadas por el futuro ``LogisticPDModel``/``ModelStep``. No entrena modelos ni importa
``statsmodels``, ``sklearn`` ni ``scipy``; el paquete ``nikodym.model`` reexporta estos símbolos de
forma perezosa para preservar el import liviano.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real
from typing import Any, ClassVar, Literal, Self, TypeAlias, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LogisticPDModel: TypeAlias = Any
StepwiseAction: TypeAlias = Literal["enter", "remove", "keep", "flag", "exclude", "fail"]
StepwiseCriterion: TypeAlias = Literal[
    "wald_pvalue",
    "lr_test",
    "both",
    "sign",
    "iv_contribution",
]
ModelEngine: TypeAlias = Literal["logit", "glm_binomial"]
ThresholdValue: TypeAlias = float | str | None

_IV_THRESHOLD_KEYS: tuple[str, ...] = (
    "iv_contribution.threshold",
    "iv_contribution_threshold",
    "iv_contribution",
)

__all__ = [
    "CoefficientRecord",
    "ModelCardSection",
    "ModelFitStatistics",
    "ModelResult",
    "StepwiseAction",
    "StepwiseCriterion",
    "StepwiseDecision",
]


class StepwiseDecision(BaseModel):
    """Decisión auditable del stepwise o de guardas de signo/IV."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    iteration: int
    feature: str
    woe_column: str
    action: StepwiseAction
    criterion: StepwiseCriterion
    p_value: float | None
    lr_stat: float | None
    beta: float | None
    threshold: float | None
    detail: str

    @field_validator("p_value", "lr_stat", "beta", "threshold", mode="after")
    @classmethod
    def _normaliza_float_opcional(cls, value: float | None) -> float | None:
        """Publica ``-0.0`` como ``0.0`` en métricas opcionales."""
        return _normalize_optional_float(value)


class CoefficientRecord(BaseModel):
    """Fila auditable de coeficientes del modelo ajustado."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str | Literal["intercept"]
    woe_column: str | Literal["const"]
    beta: float
    standard_error: float | None
    wald_z: float | None
    p_value: float | None
    conf_low: float | None
    conf_high: float | None
    expected_sign: Literal["negative", "none"]
    sign_ok: bool | None
    iv: float | None
    iv_contribution: float | None

    @field_validator("beta", mode="after")
    @classmethod
    def _normaliza_float_requerido(cls, value: float) -> float:
        """Publica ``-0.0`` como ``0.0`` en el coeficiente requerido."""
        return _normalize_float(value)

    @field_validator(
        "standard_error",
        "wald_z",
        "p_value",
        "conf_low",
        "conf_high",
        "iv",
        "iv_contribution",
        mode="after",
    )
    @classmethod
    def _normaliza_float_opcional(cls, value: float | None) -> float | None:
        """Publica ``-0.0`` como ``0.0`` en métricas opcionales."""
        return _normalize_optional_float(value)


class ModelFitStatistics(BaseModel):
    """Estadísticas in-sample del ajuste logístico en Desarrollo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    n_obs_dev: int
    n_events_dev: int
    n_nonevents_dev: int
    log_likelihood: float
    null_log_likelihood: float
    pseudo_r2_mcfadden: float
    aic: float
    bic: float
    llr: float | None
    llr_p_value: float | None
    converged: bool
    optimizer: str
    n_iterations: int | None

    @field_validator(
        "log_likelihood",
        "null_log_likelihood",
        "pseudo_r2_mcfadden",
        "aic",
        "bic",
        mode="after",
    )
    @classmethod
    def _normaliza_float_requerido(cls, value: float) -> float:
        """Publica ``-0.0`` como ``0.0`` en estadísticas requeridas."""
        return _normalize_float(value)

    @field_validator("llr", "llr_p_value", mode="after")
    @classmethod
    def _normaliza_float_opcional(cls, value: float | None) -> float | None:
        """Publica ``-0.0`` como ``0.0`` en estadísticas opcionales."""
        return _normalize_optional_float(value)


class ModelCardSection(BaseModel):
    """Resumen determinista del ajuste para model card y reporte."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"thresholds", "dependency_versions", "metric_sections"}
    )

    engine: ModelEngine
    n_candidates: int
    n_final_features: int
    final_features: tuple[str, ...]
    thresholds: dict[str, ThresholdValue]
    sign_flags: tuple[str, ...]
    iv_contribution_flags: tuple[str, ...]
    fit_statistics: ModelFitStatistics
    dependency_versions: dict[str, str]
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("thresholds", mode="after")
    @classmethod
    def _normaliza_thresholds(
        cls,
        thresholds: dict[str, ThresholdValue],
    ) -> dict[str, ThresholdValue]:
        """Ordena y normaliza umbrales float de forma estable."""
        return _normalize_thresholds(thresholds)

    @field_validator("dependency_versions", mode="after")
    @classmethod
    def _ordena_dependency_versions(cls, versions: dict[str, str]) -> dict[str, str]:
        """Ordena versiones por nombre de dependencia para serialización determinista."""
        return {name: versions[name] for name in sorted(versions)}

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia profundamente la puerta CT-2 de métricas aditivas."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(dict(value))
        return value

    @classmethod
    def from_result(
        cls,
        result: ModelResult,
        *,
        engine: ModelEngine,
        thresholds: Mapping[str, ThresholdValue],
        dependency_versions: Mapping[str, str],
        metric_sections: Mapping[str, Any] | None = None,
    ) -> ModelCardSection:
        """Deriva una sección de model card sin recalcular ni mutar el resultado."""
        final_features = tuple(result.final_features)
        candidate_features = _candidate_features(result.estimator, final_features)
        normalized_thresholds = _normalize_thresholds(thresholds)
        return cls(
            engine=engine,
            n_candidates=len(candidate_features),
            n_final_features=len(final_features),
            final_features=final_features,
            thresholds=normalized_thresholds,
            sign_flags=_sign_flags(
                final_features=final_features,
                coefficients=result.coefficients,
                stepwise_trace=result.stepwise_trace,
            ),
            iv_contribution_flags=_iv_contribution_flags(
                final_features=final_features,
                coefficients=result.coefficients,
                stepwise_trace=result.stepwise_trace,
                threshold=_first_finite_threshold(normalized_thresholds, _IV_THRESHOLD_KEYS),
            ),
            fit_statistics=result.fit_statistics,
            dependency_versions=dict(dependency_versions),
            metric_sections={} if metric_sections is None else dict(metric_sections),
        )

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de estructuras mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            if name == "metric_sections":
                return copy.deepcopy(value)
            return dict(value)
        return value


class ModelResult(BaseModel):
    """Contenedor agregado de artefactos publicados por la capa ``model``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset({"coefficients", "raw_pd_frame"})

    estimator: LogisticPDModel
    final_features: tuple[str, ...]
    final_woe_columns: tuple[str, ...]
    coefficients: pd.DataFrame
    stepwise_trace: tuple[StepwiseDecision, ...]
    fit_statistics: ModelFitStatistics
    raw_pd_frame: pd.DataFrame
    model_card: ModelCardSection

    @field_validator("coefficients", "raw_pd_frame", mode="before")
    @classmethod
    def _copia_dataframe(cls, value: Any) -> Any:
        """Copia profundamente tablas de entrada y normaliza ``-0.0`` en columnas float."""
        if isinstance(value, pd.DataFrame):
            return _copy_dataframe(value)
        return value

    @model_validator(mode="after")
    def _check_final_features_y_woe_columns(self) -> Self:
        """Valida consistencia mínima entre features finales y columnas WoE."""
        if len(self.final_features) != len(self.final_woe_columns):
            raise ValueError("final_features y final_woe_columns deben tener el mismo largo.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el DTO."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and isinstance(
            value,
            pd.DataFrame,
        ):
            return _copy_dataframe(value)
        return value


def _candidate_features(
    estimator: LogisticPDModel,
    fallback_final_features: tuple[str, ...],
) -> tuple[str, ...]:
    raw_candidates = getattr(estimator, "feature_names_in_", fallback_final_features)
    if isinstance(raw_candidates, tuple) and all(isinstance(item, str) for item in raw_candidates):
        return raw_candidates
    if isinstance(raw_candidates, list) and all(isinstance(item, str) for item in raw_candidates):
        return tuple(raw_candidates)
    return fallback_final_features


def _sign_flags(
    *,
    final_features: tuple[str, ...],
    coefficients: pd.DataFrame,
    stepwise_trace: tuple[StepwiseDecision, ...],
) -> tuple[str, ...]:
    flags: set[str] = {
        feature
        for feature, sign_ok in _coefficient_column_pairs(coefficients, "sign_ok")
        if feature != "intercept" and sign_ok is False
    }
    flags.update(
        decision.feature
        for decision in stepwise_trace
        if decision.criterion == "sign" and decision.action == "flag"
    )
    return _ordered_existing_features(final_features, flags)


def _iv_contribution_flags(
    *,
    final_features: tuple[str, ...],
    coefficients: pd.DataFrame,
    stepwise_trace: tuple[StepwiseDecision, ...],
    threshold: float | None,
) -> tuple[str, ...]:
    flags: set[str] = {
        decision.feature
        for decision in stepwise_trace
        if decision.criterion == "iv_contribution" and decision.action == "flag"
    }
    if threshold is not None:
        flags.update(
            feature
            for feature, raw_value in _coefficient_column_pairs(coefficients, "iv_contribution")
            if feature != "intercept"
            and (value := _finite_number(raw_value)) is not None
            and value > threshold
        )
    return _ordered_existing_features(final_features, flags)


def _coefficient_column_pairs(
    coefficients: pd.DataFrame, value_column: str
) -> tuple[tuple[str, Any], ...]:
    if "feature" not in coefficients.columns or value_column not in coefficients.columns:
        return ()

    rows = cast(
        list[dict[str, Any]], coefficients.loc[:, ["feature", value_column]].to_dict("records")
    )
    return tuple(
        (feature, row[value_column]) for row in rows if isinstance(feature := row["feature"], str)
    )


def _ordered_existing_features(
    final_features: tuple[str, ...],
    flagged_features: set[str],
) -> tuple[str, ...]:
    return tuple(feature for feature in final_features if feature in flagged_features)


def _first_finite_threshold(
    thresholds: Mapping[str, ThresholdValue],
    keys: tuple[str, ...],
) -> float | None:
    for key in keys:
        value = thresholds.get(key)
        if (finite := _finite_number(value)) is not None:
            return finite
    return None


def _normalize_thresholds(thresholds: Mapping[str, ThresholdValue]) -> dict[str, ThresholdValue]:
    return {
        key: _normalize_threshold_value(value)
        for key, value in sorted(thresholds.items(), key=lambda item: item[0])
    }


def _normalize_threshold_value(value: ThresholdValue) -> ThresholdValue:
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return _normalize_float(value)
    return value


def _normalize_metric_payload(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return _normalize_float(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_metric_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_metric_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_metric_payload(item) for item in value)
    return copy.deepcopy(value)


def _copy_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        series = copied[column]
        zero_mask = series == 0.0
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    candidate = float(value)
    if not math.isfinite(candidate):
        return None
    return _normalize_float(candidate)


def _normalize_optional_float(value: float | None) -> float | None:
    if value is None:
        return None
    return _normalize_float(value)


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value
