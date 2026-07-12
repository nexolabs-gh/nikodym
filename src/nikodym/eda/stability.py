"""Estabilidad temporal descriptiva de la tasa de default (SDD-27 §3/§4/§7/§9).

``TemporalStabilityAnalyzer`` consume el ``DefaultRateResult`` producido por
``DefaultRateAnalyzer`` y calcula indicadores descriptivos sobre las tasas por período,
excluyendo los períodos marcados como ``low_confidence``. No ajusta parámetros, no predice y no
calcula métricas propias de validación de score como PSI, KS, AUC o Gini.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

from math import isfinite
from typing import Final, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.core.audit import AuditSink
from nikodym.core.mixins import AuditableMixin
from nikodym.eda.config import TemporalStabilityConfig
from nikodym.eda.default_rate import DefaultRateResult
from nikodym.eda.exceptions import EdaError

__all__ = ["StabilityResult", "TemporalStabilityAnalyzer"]

StabilityMetric = Literal["cv", "max_relative_drift", "trend_slope"]

_REQUIRED_COLUMNS: Final = ("period", "default_rate", "low_confidence")
_NOT_EVALUABLE_VALUE: Final = "<2 períodos"


class StabilityResult(BaseModel):
    """Resultado inmutable del diagnóstico descriptivo de estabilidad temporal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cv: float
    max_relative_drift: float
    trend_slope: float
    metric_used: StabilityMetric
    threshold: float
    flagged: bool


class TemporalStabilityAnalyzer(AuditableMixin):
    """Evalúa la estabilidad temporal descriptiva de la tasa de default cruda."""

    def __init__(self, config: TemporalStabilityConfig) -> None:
        """Construye el analizador con ``EdaConfig.stability``."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: TemporalStabilityConfig) -> TemporalStabilityAnalyzer:
        """Construye un analizador desde ``TemporalStabilityConfig``."""
        return cls(cfg)

    def assess(
        self,
        default_rate: DefaultRateResult,
        *,
        audit: AuditSink | None = None,
    ) -> StabilityResult:
        """Calcula CV, drift relativo extremo y pendiente OLS de la tasa de default.

        Parameters
        ----------
        default_rate : DefaultRateResult
            Resultado de ``DefaultRateAnalyzer.compute`` con ``axis='period'`` y la tabla
            ``by_period`` ordenable temporalmente.
        audit : AuditSink or None
            Sumidero opcional para registrar la decisión auditable de redesarrollo o no
            evaluabilidad.

        Returns
        -------
        StabilityResult
            Indicadores descriptivos, métrica configurada, umbral y bandera de señal.

        Raises
        ------
        EdaError
            Si el resultado no usa eje temporal o si ``by_period`` no contiene las columnas
            mínimas del contrato de B5.2.
        """
        _validate_temporal_axis(default_rate)
        rates = _evaluable_rates(default_rate.by_period.copy(deep=True))
        if len(rates) < 2:
            self._log_stability_decision(
                audit,
                umbral=self.config.threshold,
                valor=_NOT_EVALUABLE_VALUE,
                accion="no_evaluable",
            )
            return StabilityResult(
                cv=float("nan"),
                max_relative_drift=float("nan"),
                trend_slope=float("nan"),
                metric_used=self.config.metric,
                threshold=self.config.threshold,
                flagged=False,
            )

        cv = _coefficient_of_variation(rates)
        max_relative_drift = _max_relative_drift(rates)
        trend_slope = _trend_slope(rates)
        metric_value = _metric_value(
            metric=self.config.metric,
            cv=cv,
            max_relative_drift=max_relative_drift,
            trend_slope=trend_slope,
        )
        flagged = bool(isfinite(metric_value) and metric_value > self.config.threshold)
        if flagged:
            self._log_stability_decision(
                audit,
                umbral=self.config.threshold,
                valor=metric_value,
                accion="senalar_redesarrollo",
            )

        return StabilityResult(
            cv=cv,
            max_relative_drift=max_relative_drift,
            trend_slope=trend_slope,
            metric_used=self.config.metric,
            threshold=self.config.threshold,
            flagged=flagged,
        )

    def _log_stability_decision(
        self, audit: AuditSink | None, *, umbral: object, valor: object, accion: str
    ) -> None:
        """Registra la decisión usando el contrato de ``AuditableMixin``."""
        previous_audit = self._audit
        self._audit = previous_audit if audit is None else audit
        try:
            self.log_decision(
                regla="estabilidad_temporal",
                umbral=umbral,
                valor=valor,
                accion=accion,
            )
        finally:
            self._audit = previous_audit


def _evaluable_rates(by_period: pd.DataFrame) -> np.ndarray:
    """Extrae tasas evaluables ordenadas por período, excluyendo baja confianza y no finitas."""
    _validate_by_period_columns(by_period)
    ordered = by_period.dropna(subset=["period"]).sort_values("period", kind="mergesort")
    low_confidence = ordered["low_confidence"].fillna(True).astype("bool")
    rates = pd.to_numeric(ordered["default_rate"], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    evaluable = rates.loc[~low_confidence].dropna()
    return evaluable.to_numpy(dtype="float64", copy=True)


def _validate_temporal_axis(default_rate: DefaultRateResult) -> None:
    """Rechaza estabilidad temporal sobre cohortes sin cronología inferible."""
    if default_rate.axis == "period":
        return

    raise EdaError(
        'La estabilidad temporal descriptiva solo aplica al eje temporal (axis="period"); '
        f'se recibió axis="{default_rate.axis}". '
        "Las cohortes no tienen orden cronológico inferible."
    )


def _validate_by_period_columns(by_period: pd.DataFrame) -> None:
    """Valida que el resultado de tasa de default tenga el contrato mínimo requerido."""
    missing = [column for column in _REQUIRED_COLUMNS if column not in by_period.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise EdaError(
            f"La estabilidad temporal requiere DefaultRateResult.by_period con columna(s) {joined}."
        )


def _coefficient_of_variation(rates: np.ndarray) -> float:
    """Calcula ``sigma / media`` con desviación poblacional y sin warnings por media cero."""
    mean = float(np.mean(rates))
    if mean == 0.0:
        return float("nan")
    return float(np.std(rates, ddof=0) / mean)


def _max_relative_drift(rates: np.ndarray) -> float:
    """Calcula ``max_t |rate_t - media| / media`` según SDD-27 §3."""
    mean = float(np.mean(rates))
    if mean == 0.0:
        return float("nan")
    return float(np.max(np.abs(rates - mean)) / mean)


def _trend_slope(rates: np.ndarray) -> float:
    """Calcula la pendiente OLS simple ``rate ~ índice`` con numpy puro."""
    x = np.arange(len(rates), dtype="float64")
    x_centered = x - float(np.mean(x))
    y_centered = rates - float(np.mean(rates))
    denominator = float(np.sum(x_centered * x_centered))
    return float(np.sum(x_centered * y_centered) / denominator)


def _metric_value(
    *,
    metric: StabilityMetric,
    cv: float,
    max_relative_drift: float,
    trend_slope: float,
) -> float:
    """Devuelve el indicador configurado para compararlo contra el umbral."""
    indicators: dict[StabilityMetric, float] = {
        "cv": cv,
        "max_relative_drift": max_relative_drift,
        "trend_slope": trend_slope,
    }
    return indicators[metric]
