"""Tests de ``TemporalStabilityAnalyzer`` (SDD-27 §3/§4/§7/§9)."""

from __future__ import annotations

import math
from typing import Literal, get_args

import pandas as pd
import pytest
from pydantic import ValidationError

import nikodym.eda as eda
from nikodym.core.audit import InMemoryAuditSink
from nikodym.eda.config import TemporalStabilityConfig
from nikodym.eda.default_rate import DefaultRateResult
from nikodym.eda.exceptions import EdaError
from nikodym.eda.stability import (
    NOT_EVALUABLE_REASON_LABELS,
    NotEvaluableReason,
    StabilityResult,
    TemporalStabilityAnalyzer,
)


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


def _cohort_result() -> DefaultRateResult:
    """Tasa por cohorte con dos cohortes válidas: hay tasas, pero no cronología."""
    return DefaultRateResult(
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


def test_axis_cohort_es_no_evaluable_declarado_y_no_un_error() -> None:
    """D-SC-2: el eje de cohorte deja la señal temporal sin evaluar, con su causa, sin reventar.

    🔴 Nació ROJO sobre el árbol anterior: ``_validate_temporal_axis`` levantaba ``EdaError`` y
    con él moría la corrida entera de ``eda`` —perfiles, calidad y tasa por cohorte incluidos—
    por una señal que SDD-27 §8 ya declaraba «no evaluable». Es el mismo tratamiento que «menos
    de dos períodos»: métricas ``NaN``, ``flagged=False`` y una decisión ``no_evaluable`` en el
    trail que nombra la causa.
    """
    audit = InMemoryAuditSink()

    stability = _analyzer(metric="cv", threshold=0.25).assess(_cohort_result(), audit=audit)

    assert not stability.flagged
    assert math.isnan(stability.cv)
    assert math.isnan(stability.max_relative_drift)
    assert math.isnan(stability.trend_slope)
    assert stability.metric_used == "cv"
    assert stability.not_evaluable_reason == "eje_cohorte"
    assert len(audit.events) == 1
    assert audit.events[0].kind == "decision"
    assert audit.events[0].payload == {
        "regla": "estabilidad_temporal",
        "umbral": 0.25,
        "valor": "eje de cohorte sin cronología",
        "accion": "no_evaluable",
    }


@pytest.mark.parametrize(
    ("rates", "low_confidence", "metric", "reason"),
    [
        # Un solo período: no hay serie que comparar.
        ([0.10], None, "cv", "pocos_periodos_evaluables"),
        # Dos períodos, pero uno de baja confianza: queda uno solo evaluable.
        ([0.10, 0.90], [False, True], "cv", "pocos_periodos_evaluables"),
        # Dos períodos suficientes y ningún incumplimiento: las métricas relativas no existen…
        ([0.0, 0.0], None, "cv", "tasa_media_cero"),
        ([0.0, 0.0], None, "max_relative_drift", "tasa_media_cero"),
        # …pero la pendiente sí: es cero, evaluable y sin causa (§0-13).
        ([0.0, 0.0], None, "trend_slope", None),
        # Serie normal: indicador finito, sin causa.
        ([0.10, 0.11, 0.09], None, "cv", None),
    ],
)
def test_la_causa_existe_si_y_solo_si_el_indicador_no_es_finito(
    rates: list[float],
    low_confidence: list[bool] | None,
    metric: Literal["cv", "max_relative_drift", "trend_slope"],
    reason: str | None,
) -> None:
    """D-SC-2, en los dos sentidos: causa ⇔ el indicador configurado no es finito.

    Devolver ``not_evaluable_reason=None`` con el indicador en ``NaN`` —o una causa con el
    indicador finito— es el control negativo preespecificado del §6 de la enmienda: cualquiera
    de los dos pone rojo esta tabla.
    """
    result = _default_rate_result(rates, low_confidence=low_confidence)

    stability = _analyzer(metric=metric, threshold=10.0).assess(result)

    indicador = float(getattr(stability, metric))
    assert stability.not_evaluable_reason == reason
    assert (stability.not_evaluable_reason is None) == math.isfinite(indicador)
    assert not stability.flagged


def test_la_causa_es_una_de_las_tres_declaradas() -> None:
    """El enum del motor y el mapa de palabras públicas cubren exactamente las mismas causas."""
    assert set(NOT_EVALUABLE_REASON_LABELS) == set(get_args(NotEvaluableReason))
    assert all(palabra != clave for clave, palabra in NOT_EVALUABLE_REASON_LABELS.items())


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
    assert stability.not_evaluable_reason == "pocos_periodos_evaluables"
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


def test_media_cero_deja_metricas_relativas_nan_sin_warning_y_declara_la_causa() -> None:
    """Con el indicador relativo y tasa media cero no hay señal: se declara, no se calla.

    Hasta D-SC-2 este caso salía en silencio —``NaN`` y ningún evento—, indistinguible en el
    trail de una serie evaluable. Ahora lleva la tercera causa (§0-13) y su decisión.
    """
    result = _default_rate_result([0.0, 0.0])
    audit = InMemoryAuditSink()

    stability = _analyzer(metric="cv", threshold=0.0).assess(result, audit=audit)

    assert not stability.flagged
    assert math.isnan(stability.cv)
    assert math.isnan(stability.max_relative_drift)
    assert stability.trend_slope == pytest.approx(0.0)
    assert stability.not_evaluable_reason == "tasa_media_cero"
    assert len(audit.events) == 1
    assert audit.events[0].payload == {
        "regla": "estabilidad_temporal",
        "umbral": 0.0,
        "valor": "tasa media cero",
        "accion": "no_evaluable",
    }


def test_media_cero_con_la_pendiente_es_evaluable_y_no_emite_decision() -> None:
    """La otra cara de §0-13: con ``trend_slope`` el indicador vale cero y es evaluable."""
    result = _default_rate_result([0.0, 0.0])
    audit = InMemoryAuditSink()

    stability = _analyzer(metric="trend_slope", threshold=0.0).assess(result, audit=audit)

    assert not stability.flagged
    assert stability.trend_slope == pytest.approx(0.0)
    assert stability.not_evaluable_reason is None
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
