"""Resultados puros de la selección pre-modelo de variables WoE (SDD-07 §4).

``SelectionResult`` y ``SelectionCardSection`` son contenedores de salida: reciben tablas y
decisiones ya calculadas por el futuro ``SelectionStep``/``FeatureSelector`` y no ejercen
``sklearn``, ``statsmodels`` ni ``scipy`` en runtime. Este módulo puede importar ``pandas`` porque
pertenece al dominio ``selection``; el paquete ``nikodym.selection`` lo reexporta de forma perezosa
para preservar el import liviano.

Decisiones para revisión de Cami:
- La banda de IV se reutiliza desde ``nikodym.binning.results.iv_band`` para mantener una sola
  fuente de verdad.
- ``SelectionCardSection.from_result`` deriva solo agregados deterministas del resultado recibido.
- ``dependency_versions`` entra como parámetro explícito; aquí no se importan dependencias de
  scoring para resolver versiones.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Literal, Self, TypeAlias, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator

from nikodym.binning.results import IvBand, iv_band

SelectionDecisionReason: TypeAlias = Literal[
    "included",
    "business_exclude",
    "business_include",
    "low_iv",
    "high_iv",
    "low_auc",
    "low_ks",
    "low_gini",
    "high_correlation",
    "high_vif",
    "cluster_representative_lost",
    "constant_or_nonfinite",
    "missing_binning_artifact",
    "forced_conflict",
    "high_stability",
]
ThresholdValue: TypeAlias = float | str | None

_DECISION_REASON_ORDER: tuple[SelectionDecisionReason, ...] = (
    "included",
    "business_exclude",
    "business_include",
    "low_iv",
    "high_iv",
    "low_auc",
    "low_ks",
    "low_gini",
    "high_correlation",
    "high_vif",
    "cluster_representative_lost",
    "constant_or_nonfinite",
    "missing_binning_artifact",
    "forced_conflict",
    "high_stability",
)

__all__ = [
    "SelectionCardSection",
    "SelectionDecisionReason",
    "SelectionResult",
    "VariableSelectionDecision",
]


class VariableSelectionDecision(BaseModel):
    """Decisión auditable para una variable candidata de ``selection``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str
    woe_column: str
    included: bool
    reason: SelectionDecisionReason
    iv: float
    iv_band: IvBand
    auc: float | None
    gini: float | None
    ks: float | None
    max_abs_corr: float | None
    max_corr_with: str | None
    vif: float | None
    max_csi: float | None
    forced: Literal["include", "exclude"] | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def _check_iv_band_matches_iv(self) -> Self:
        """Valida que la banda IV venga de la fuente única de ``binning``."""
        if self.iv_band != iv_band(self.iv):
            raise ValueError("iv_band no coincide con iv_band(iv) de binning.")
        return self


class SelectionResult(BaseModel):
    """Contenedor agregado de las salidas principales de ``selection``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    candidate_features: tuple[str, ...]
    candidate_woe_columns: tuple[str, ...]
    selected_features: tuple[str, ...]
    selected_woe_columns: tuple[str, ...]
    selected_woe_frame: pd.DataFrame
    selection_table: pd.DataFrame
    correlation_matrix: pd.DataFrame
    vif_table: pd.DataFrame
    stability_table: pd.DataFrame
    decisions: tuple[VariableSelectionDecision, ...]


class SelectionCardSection(BaseModel):
    """Resumen compacto de ``selection`` para model card y reporte."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    n_candidates: int
    n_selected: int
    n_excluded: int
    thresholds: dict[str, ThresholdValue]
    excluded_by_reason: dict[str, int]
    selected_features: tuple[str, ...]
    high_iv_flags: tuple[str, ...]
    stability_flags: tuple[str, ...]
    max_abs_correlation_after_selection: float | None
    max_vif_after_selection: float | None
    dependency_versions: dict[str, str]

    @classmethod
    def from_result(
        cls,
        result: SelectionResult,
        *,
        thresholds: Mapping[str, ThresholdValue],
        dependency_versions: Mapping[str, str],
    ) -> SelectionCardSection:
        """Deriva una sección de model card sin recalcular ni mutar el resultado."""
        decision_by_feature = {decision.feature: decision for decision in result.decisions}
        selected_feature_set = set(result.selected_features)
        selected_features = tuple(
            feature for feature in result.candidate_features if feature in selected_feature_set
        )

        excluded_counts: Counter[str] = Counter(
            decision.reason for decision in result.decisions if not decision.included
        )
        max_iv_threshold = _float_threshold(thresholds, "max_iv")
        stability_threshold = _float_threshold(thresholds, "stability.stable_threshold")

        return cls(
            n_candidates=len(result.candidate_features),
            n_selected=len(selected_features),
            n_excluded=len(result.candidate_features) - len(selected_features),
            thresholds=dict(sorted(thresholds.items())),
            excluded_by_reason={
                reason: excluded_counts[reason]
                for reason in _DECISION_REASON_ORDER
                if excluded_counts[reason]
            },
            selected_features=selected_features,
            high_iv_flags=_high_iv_flags(
                result.candidate_features,
                decision_by_feature,
                max_iv_threshold,
            ),
            stability_flags=_stability_flags(
                result.candidate_features,
                decision_by_feature,
                stability_threshold,
            ),
            max_abs_correlation_after_selection=_max_abs_correlation_after_selection(result),
            max_vif_after_selection=_max_vif_after_selection(result),
            dependency_versions=dict(sorted(dependency_versions.items())),
        )


def _float_threshold(thresholds: Mapping[str, ThresholdValue], key: str) -> float | None:
    value = thresholds.get(key)
    if isinstance(value, float):
        return value
    return None


def _high_iv_flags(
    features: tuple[str, ...],
    decisions: Mapping[str, VariableSelectionDecision],
    threshold: float | None,
) -> tuple[str, ...]:
    if threshold is None:
        return tuple(
            feature
            for feature in features
            if decisions[feature].reason == "high_iv" or decisions[feature].iv_band == "suspicious"
        )

    return tuple(feature for feature in features if decisions[feature].iv >= threshold)


def _stability_flags(
    features: tuple[str, ...],
    decisions: Mapping[str, VariableSelectionDecision],
    threshold: float | None,
) -> tuple[str, ...]:
    if threshold is None:
        return tuple(
            feature for feature in features if decisions[feature].reason == "high_stability"
        )

    return tuple(
        feature
        for feature in features
        if _exceeds_stability_threshold(decisions[feature], threshold)
    )


def _max_abs_correlation_after_selection(result: SelectionResult) -> float | None:
    matrix = result.correlation_matrix
    selected_columns = tuple(
        column
        for column in result.selected_woe_columns
        if column in matrix.index and column in matrix.columns
    )
    if len(selected_columns) < 2:
        return None

    correlations = [
        correlation
        for index, left in enumerate(selected_columns)
        for right in selected_columns[index + 1 :]
        if math.isfinite(correlation := abs(float(cast(float, matrix.loc[left, right]))))
    ]
    if not correlations:
        return None

    return _normalize_float(max(correlations))


def _exceeds_stability_threshold(decision: VariableSelectionDecision, threshold: float) -> bool:
    max_csi = decision.max_csi
    return max_csi is not None and max_csi >= threshold


def _max_vif_after_selection(result: SelectionResult) -> float | None:
    vif_values = [
        vif
        for decision in result.decisions
        if decision.included
        and decision.vif is not None
        and math.isfinite(vif := float(decision.vif))
    ]
    if not vif_values:
        return None

    return _normalize_float(max(vif_values))


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value
