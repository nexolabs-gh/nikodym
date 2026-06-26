"""Tests de ``TemporalStabilityAnalyzer`` (SDD-27 §3/§4/§7/§9)."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from pydantic import ValidationError

import nikodym.eda as eda
from nikodym.core.audit import InMemoryAuditSink
from nikodym.eda.config import TemporalStabilityConfig
from nikodym.eda.default_rate import DefaultRateResult
from nikodym.eda.exceptions import EdaError
from nikodym.eda.stability import StabilityResult, TemporalStabilityAnalyzer


def _default_rate_result(
    rates: list[float],
    *,
    low_confidence: list[bool] | None = None,
) -> DefaultRateResult:
    low_confidence_values = low_confidence if low_confidence is not None else [False] * len(rates)
    periods = pd.period_range("2024-01", periods=len(rates), freq="M")
    n_eligible = [100] * len(rates)
    n_bad = [round(rate * 100) if math.isfinite(rate) else 0 for rate in rates]
    by_period = pd.DataFrame(
        {
            "period": periods,
            "n_total": n_eligible,
            "n_eligible": n_eligible,
            "n_bad": n_bad,
            "default_rate": rates,
            "low_confidence": low_confidence_values,
        }
    )
    return DefaultRateResult(
        by_period=by_period,
        axis="period",
        overall_rate=sum(n_bad) / sum(n_eligible),
    )


def _analyzer(**kwargs: object) -> TemporalStabilityAnalyzer:
    return TemporalStabilityAnalyzer(TemporalStabilityConfig.model_validate(kwargs))


def test_from_config_y_superficie_no_estimador() -> None:
    cfg = TemporalStabilityConfig(metric="max_relative_drift", threshold=0.40)

    analyzer = TemporalStabilityAnalyzer.from_config(cfg)

    assert analyzer.config is cfg
    assert not hasattr(analyzer, "fit")
    assert not hasattr(analyzer, "predict")


def test_assess_rechaza_axis_cohort_con_edaerror_en_espanol() -> None:
    result = DefaultRateResult(
        by_period=pd.DataFrame(
            {
                "period": ["2024Q10", "2024Q2"],
                "n_total": [100, 100],
                "n_eligible": [100, 100],
                "n_bad": [10, 20],
                "default_rate": [0.10, 0.20],
                "low_confidence": [False, False],
            }
        ),
        axis="cohort",
        overall_rate=0.15,
    )

    with pytest.raises(EdaError, match="solo aplica al eje temporal"):
        _analyzer().assess(result)


def test_reexports_perezosos_de_stability_y_default_rate() -> None:
    assert eda.__getattr__("TemporalStabilityAnalyzer") is TemporalStabilityAnalyzer
    assert eda.__getattr__("StabilityResult") is StabilityResult
    assert eda.__getattr__("DefaultRateResult") is DefaultRateResult
    with pytest.raises(AttributeError, match="NoExiste"):
        eda.__getattr__("NoExiste")


def test_golden_dispara_umbral_y_emite_un_evento_decision() -> None:
    result = _default_rate_result([0.10, 0.20, 0.30])
    audit = InMemoryAuditSink()

    stability = _analyzer(metric="max_relative_drift", threshold=0.40).assess(result, audit=audit)

    assert stability.flagged
    assert stability.metric_used == "max_relative_drift"
    assert stability.threshold == pytest.approx(0.40)
    assert stability.cv == pytest.approx(0.408248290463863)
    assert stability.max_relative_drift == pytest.approx(0.50)
    assert stability.trend_slope == pytest.approx(0.10)
    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.kind == "decision"
    assert event.step is None
    assert event.payload["regla"] == "estabilidad_temporal"
    assert event.payload["umbral"] == pytest.approx(0.40)
    assert event.payload["valor"] == pytest.approx(0.50)
    assert event.payload["accion"] == "senalar_redesarrollo"


def test_serie_estable_no_emite_auditoria() -> None:
    result = _default_rate_result([0.10, 0.11, 0.09])
    audit = InMemoryAuditSink()

    stability = _analyzer(metric="cv", threshold=0.25).assess(result, audit=audit)

    assert not stability.flagged
    assert stability.cv == pytest.approx(0.08164965809277264)
    assert audit.events == []


def test_menos_de_dos_periodos_evaluables_registra_no_evaluable() -> None:
    result = _default_rate_result([0.10, 0.90], low_confidence=[False, True])
    audit = InMemoryAuditSink()

    stability = _analyzer(metric="cv", threshold=0.0).assess(result, audit=audit)

    assert not stability.flagged
    assert math.isnan(stability.cv)
    assert math.isnan(stability.max_relative_drift)
    assert math.isnan(stability.trend_slope)
    assert len(audit.events) == 1
    assert audit.events[0].kind == "decision"
    assert audit.events[0].payload == {
        "regla": "estabilidad_temporal",
        "umbral": 0.0,
        "valor": "<2 períodos",
        "accion": "no_evaluable",
    }


def test_no_evaluable_sin_audit_no_levanta() -> None:
    result = _default_rate_result([0.10])

    stability = _analyzer(metric="cv", threshold=0.0).assess(result)

    assert not stability.flagged
    assert math.isnan(stability.cv)


def test_periodo_low_confidence_no_entra_al_calculo() -> None:
    result = _default_rate_result([0.10, 0.90, 0.20], low_confidence=[False, True, False])

    stability = _analyzer(metric="cv", threshold=0.90).assess(result)

    assert not stability.flagged
    assert stability.cv == pytest.approx(1 / 3)
    assert stability.max_relative_drift == pytest.approx(1 / 3)
    assert stability.trend_slope == pytest.approx(0.10)


def test_by_period_barajado_ordena_por_periodo_antes_de_tendencia() -> None:
    ordered = _default_rate_result([0.10, 0.20, 0.30])
    shuffled = DefaultRateResult(
        by_period=ordered.by_period.iloc[[2, 1, 0]].reset_index(drop=True),
        axis=ordered.axis,
        overall_rate=ordered.overall_rate,
    )
    analyzer = _analyzer(metric="trend_slope", threshold=0.05)

    ordered_stability = analyzer.assess(ordered)
    shuffled_stability = analyzer.assess(shuffled)

    assert ordered_stability.cv == pytest.approx(shuffled_stability.cv)
    assert ordered_stability.max_relative_drift == pytest.approx(
        shuffled_stability.max_relative_drift
    )
    assert ordered_stability.trend_slope == pytest.approx(shuffled_stability.trend_slope)
    assert shuffled_stability.trend_slope == pytest.approx(0.10)


def test_periodo_nat_no_entra_a_la_serie_temporal() -> None:
    clean = _default_rate_result([0.10, 0.20, 0.30])
    nat_row = pd.DataFrame(
        {
            "period": [pd.NaT],
            "n_total": [100],
            "n_eligible": [100],
            "n_bad": [90],
            "default_rate": [0.90],
            "low_confidence": [False],
        }
    )
    with_nat = DefaultRateResult(
        by_period=pd.concat(
            [clean.by_period.iloc[[0]], nat_row, clean.by_period.iloc[1:]],
            ignore_index=True,
        ),
        axis=clean.axis,
        overall_rate=clean.overall_rate,
    )
    analyzer = _analyzer(metric="cv", threshold=0.25)

    clean_stability = analyzer.assess(clean)
    with_nat_stability = analyzer.assess(with_nat)

    assert with_nat_stability.cv == pytest.approx(clean_stability.cv)
    assert with_nat_stability.max_relative_drift == pytest.approx(
        clean_stability.max_relative_drift
    )
    assert with_nat_stability.trend_slope == pytest.approx(clean_stability.trend_slope)


def test_tasa_infinita_se_excluye_como_no_finita() -> None:
    result = _default_rate_result([0.10, math.inf, 0.20])

    stability = _analyzer(metric="cv", threshold=0.90).assess(result)

    assert not stability.flagged
    assert stability.cv == pytest.approx(1 / 3)
    assert stability.max_relative_drift == pytest.approx(1 / 3)
    assert stability.trend_slope == pytest.approx(0.10)


def test_media_cero_deja_metricas_relativas_nan_sin_warning_ni_flag() -> None:
    result = _default_rate_result([0.0, 0.0])
    audit = InMemoryAuditSink()

    stability = _analyzer(metric="cv", threshold=0.0).assess(result, audit=audit)

    assert not stability.flagged
    assert math.isnan(stability.cv)
    assert math.isnan(stability.max_relative_drift)
    assert stability.trend_slope == pytest.approx(0.0)
    assert audit.events == []


def test_trend_slope_es_metrica_configurable() -> None:
    result = _default_rate_result([0.10, 0.15, 0.20])
    audit = InMemoryAuditSink()

    stability = _analyzer(metric="trend_slope", threshold=0.04).assess(result, audit=audit)

    assert stability.flagged
    assert stability.metric_used == "trend_slope"
    assert stability.trend_slope == pytest.approx(0.05)
    assert len(audit.events) == 1
    assert audit.events[0].payload["valor"] == pytest.approx(0.05)


def test_resultado_es_reproducible_para_mismo_input() -> None:
    result = _default_rate_result([0.12, 0.18, 0.15, 0.21])
    analyzer = _analyzer(metric="cv", threshold=0.25)

    first = analyzer.assess(result)
    second = analyzer.assess(result)

    assert first == second


def test_resultado_es_inmutable_a_nivel_de_campos() -> None:
    result = _default_rate_result([0.10, 0.20])
    stability = _analyzer().assess(result)

    with pytest.raises(ValidationError):
        stability.flagged = True


def test_by_period_malformado_levanta_edaerror_en_espanol() -> None:
    bad_result = DefaultRateResult(
        by_period=pd.DataFrame({"period": ["2024-01", "2024-02"], "default_rate": [0.10, 0.20]}),
        axis="period",
        overall_rate=0.15,
    )

    with pytest.raises(EdaError, match="low_confidence"):
        _analyzer().assess(bad_result)
