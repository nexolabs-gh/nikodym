"""Tests de resultados de ``validation``: DTOs puros, copias defensivas y lazy exports (SDD-22)."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.validation as validation_pkg
import nikodym.validation.results as validation_results
from nikodym.validation.config import (
    BacktestParameter as ConfigBacktestParameter,
)
from nikodym.validation.config import (
    PdTest as ConfigPdTest,
)
from nikodym.validation.config import (
    ValidationFamily as ConfigValidationFamily,
)
from nikodym.validation.results import (
    BacktestRecord,
    CalibrationTestRecord,
    DiscriminationRecord,
    GradeBinomialRecord,
    ValidationCardSection,
    ValidationResult,
)


def test_discrimination_record_golden_estados_y_normalizacion() -> None:
    record = _discrimination_record(auc=-0.0, gini=-0.0, ks=-0.0)

    assert record.model_dump(mode="json") == {
        "partition": "desarrollo",
        "n_total": 1000,
        "n_bad": 80,
        "auc": 0.0,
        "gini": 0.0,
        "ks": 0.0,
        "source": "performance_artifact",
        "status": "ok",
    }
    assert math.copysign(1.0, record.auc) == 1.0

    not_evaluable = _discrimination_record(
        partition="oot",
        auc=math.nan,
        gini=None,
        ks=math.inf,
        source="recomputed",
        status="not_evaluable",
    )
    assert not_evaluable.model_dump(mode="json") == {
        "partition": "oot",
        "n_total": 1000,
        "n_bad": 80,
        "auc": None,
        "gini": None,
        "ks": None,
        "source": "recomputed",
        "status": "not_evaluable",
    }

    with pytest.raises(ValidationError, match="frozen"):
        record.auc = 0.9
    with pytest.raises(ValidationError):
        _discrimination_record(extra="no permitido")
    with pytest.raises(ValidationError, match="partition no puede"):
        _discrimination_record(partition="   ")
    with pytest.raises(ValidationError, match="n_bad no puede exceder"):
        _discrimination_record(n_total=10, n_bad=11)
    with pytest.raises(ValidationError, match="not_evaluable no debe publicar"):
        _discrimination_record(status="not_evaluable", auc=0.8, gini=0.6, ks=0.5)
    with pytest.raises(ValidationError, match="evaluable"):
        _discrimination_record(status="ok", auc=0.8, gini=None, ks=0.5)


def test_calibration_test_record_hl_y_brier_golden() -> None:
    hl = _calibration_record()
    assert hl.model_dump(mode="json") == {
        "partition": "desarrollo",
        "test": "hosmer_lemeshow",
        "n_groups": 10,
        "degrees_of_freedom": 8,
        "statistic": 7.34,
        "p_value": 0.5,
        "alpha": 0.05,
        "decision": "pass",
        "not_evaluable_reason": None,
    }

    brier = _calibration_record(
        test="brier",
        n_groups=None,
        degrees_of_freedom=None,
        statistic=-0.0,
        p_value=None,
        alpha=None,
        decision="not_evaluable",
    )
    assert brier.model_dump(mode="json") == {
        "partition": "desarrollo",
        "test": "brier",
        "n_groups": None,
        "degrees_of_freedom": None,
        "statistic": 0.0,
        "p_value": None,
        "alpha": None,
        "decision": "not_evaluable",
        "not_evaluable_reason": None,
    }
    assert brier.statistic is not None
    assert math.copysign(1.0, brier.statistic) == 1.0

    hl_not_evaluable = _hl_not_evaluable_record()
    assert hl_not_evaluable.p_value is None
    assert hl_not_evaluable.statistic is None
    assert hl_not_evaluable.not_evaluable_reason == "group_below_min"

    with pytest.raises(ValidationError, match="frozen"):
        hl.statistic = 1.0
    with pytest.raises(ValidationError):
        _calibration_record(extra="no permitido")
    with pytest.raises(ValidationError, match="finitos"):
        _calibration_record(statistic=math.nan)


def _hl_not_evaluable_record(**updates: Any) -> CalibrationTestRecord:
    """Un Hosmer-Lemeshow sin veredicto tal como lo publica el motor desde D-VAL-17."""
    payload: dict[str, Any] = {
        "decision": "not_evaluable",
        "statistic": None,
        "p_value": None,
        "alpha": None,
        "not_evaluable_reason": "group_below_min",
    }
    payload.update(updates)
    return _calibration_record(**payload)


@pytest.mark.parametrize(
    "reason",
    ["partition_below_min", "group_below_min", "degenerate_group", "non_finite_statistic"],
)
def test_calibration_test_record_hl_not_evaluable_publica_una_de_las_cuatro_causas(
    reason: str,
) -> None:
    """D-VAL-17: las cuatro causas cerradas, y ninguna otra."""
    record = _hl_not_evaluable_record(not_evaluable_reason=reason)
    assert record.not_evaluable_reason == reason
    assert record.statistic is None
    with pytest.raises(ValidationError):
        _hl_not_evaluable_record(not_evaluable_reason="otra_causa")


def test_calibration_test_record_hl_not_evaluable_no_publica_estadistico_y_exige_causa() -> None:
    """Antes un HL no evaluable publicaba ``statistic=0.0`` —el valor de un ajuste perfecto— y
    ninguna superficie decía por qué (hallazgo 3 de Codex sobre la enmienda, sostenido)."""
    with pytest.raises(ValidationError, match="not_evaluable no publica statistic"):
        _hl_not_evaluable_record(statistic=0.0)
    with pytest.raises(ValidationError, match="exige not_evaluable_reason"):
        _hl_not_evaluable_record(not_evaluable_reason=None)
    # Y al revés: un HL con veredicto lleva su estadístico y ninguna causa.
    with pytest.raises(ValidationError, match="evaluable exige"):
        _calibration_record(statistic=None)
    with pytest.raises(ValidationError, match="no lleva not_evaluable_reason"):
        _calibration_record(not_evaluable_reason="group_below_min")
    # El Brier es un puntaje: conserva su estadístico y no tiene causa que declarar.
    with pytest.raises(ValidationError, match=r"Brier score .*statistic"):
        _calibration_record(
            test="brier",
            n_groups=None,
            degrees_of_freedom=None,
            statistic=None,
            p_value=None,
            alpha=None,
            decision="not_evaluable",
        )
    with pytest.raises(ValidationError, match=r"Brier score .*not_evaluable_reason"):
        _calibration_record(
            test="brier",
            n_groups=None,
            degrees_of_freedom=None,
            statistic=0.1,
            p_value=None,
            alpha=None,
            decision="not_evaluable",
            not_evaluable_reason="degenerate_group",
        )


def test_calibration_test_record_invariantes_rechazan_incoherencias() -> None:
    with pytest.raises(ValidationError, match="partition no puede"):
        _calibration_record(partition="  ")
    with pytest.raises(ValidationError, match=r"p_value debe estar"):
        _calibration_record(p_value=1.5)
    with pytest.raises(ValidationError, match=r"alpha debe estar"):
        _calibration_record(alpha=0.0)
    with pytest.raises(ValidationError, match="Brier score no publica"):
        _calibration_record(
            test="brier", statistic=0.1, p_value=None, alpha=None, decision="not_evaluable"
        )
    with pytest.raises(ValidationError, match="no es pass/fail"):
        _calibration_record(
            test="brier",
            n_groups=None,
            degrees_of_freedom=None,
            statistic=0.1,
            p_value=None,
            alpha=None,
            decision="pass",
        )
    with pytest.raises(ValidationError, match=r"Brier score debe estar"):
        _calibration_record(
            test="brier",
            n_groups=None,
            degrees_of_freedom=None,
            statistic=1.5,
            p_value=None,
            alpha=None,
            decision="not_evaluable",
        )
    with pytest.raises(ValidationError, match="exige n_groups"):
        _calibration_record(n_groups=None)
    with pytest.raises(ValidationError, match="G-2"):
        _calibration_record(n_groups=10, degrees_of_freedom=7)
    with pytest.raises(ValidationError, match="no puede ser negativo"):
        _calibration_record(statistic=-1.0)
    with pytest.raises(ValidationError, match="not_evaluable no publica p_value"):
        _calibration_record(decision="not_evaluable", p_value=0.5)
    with pytest.raises(ValidationError, match="evaluable exige"):
        _calibration_record(decision="pass", p_value=None)


def test_grade_binomial_record_golden_y_rangos() -> None:
    record = _grade_record(observed_defaults=0, observed_dr=-0.0, z_stat=-0.0)
    assert record.model_dump(mode="json") == {
        "grade": "A",
        "n": 500,
        "expected_pd": 0.02,
        "observed_defaults": 0,
        "observed_dr": 0.0,
        "test": "jeffreys",
        "p_value": 0.62,
        "z_stat": 0.0,
        "alpha": 0.05,
        "traffic_light": "green",
        "green_alpha": 0.05,
        "red_alpha": 0.01,
    }
    assert math.copysign(1.0, record.observed_dr) == 1.0
    assert math.copysign(1.0, record.z_stat) == 1.0

    sin_z = _grade_record(z_stat=None)
    assert sin_z.z_stat is None
    assert _grade_record(z_stat=True).z_stat is None
    assert _grade_record(z_stat="no numérico").z_stat is None
    assert _grade_record(z_stat=math.inf).z_stat is None

    with pytest.raises(ValidationError, match="frozen"):
        record.p_value = 0.1
    with pytest.raises(ValidationError):
        _grade_record(extra="no permitido")
    with pytest.raises(ValidationError, match="grade no puede"):
        _grade_record(grade=" ")
    with pytest.raises(ValidationError, match="observed_defaults no puede exceder"):
        _grade_record(n=5, observed_defaults=6)
    with pytest.raises(ValidationError, match="expected_pd debe estar"):
        _grade_record(expected_pd=1.2)
    with pytest.raises(ValidationError, match="observed_dr debe estar"):
        _grade_record(observed_dr=1.2)
    with pytest.raises(ValidationError, match=r"p_value debe estar"):
        _grade_record(p_value=1.2)
    with pytest.raises(ValidationError, match=r"alpha debe estar"):
        _grade_record(alpha=1.0)
    with pytest.raises(ValidationError, match="finitos"):
        _grade_record(p_value=math.nan)


def test_grade_binomial_record_persiste_los_cortes_con_que_se_decidio_el_color() -> None:
    """D-VAL-15: la fila explica su propio color. ``alpha`` es la significancia del contraste y no
    un corte; los cortes viajan aparte, abiertos en (0, 1) y con el rojo más estricto que el verde.
    Sin ellos, con cortes personalizados el color no se podía reconstruir desde el resultado."""
    record = _grade_record(alpha=0.05, green_alpha=0.10, red_alpha=0.02)
    assert (record.alpha, record.green_alpha, record.red_alpha) == (0.05, 0.10, 0.02)

    with pytest.raises(ValidationError, match="green_alpha debe estar"):
        _grade_record(green_alpha=1.0)
    with pytest.raises(ValidationError, match="red_alpha debe estar"):
        _grade_record(red_alpha=0.0)
    with pytest.raises(ValidationError, match="red_alpha < green_alpha"):
        _grade_record(green_alpha=0.01, red_alpha=0.05)
    with pytest.raises(ValidationError, match="red_alpha < green_alpha"):
        _grade_record(green_alpha=0.05, red_alpha=0.05)
    with pytest.raises(ValidationError, match="finitos"):
        _grade_record(green_alpha=math.nan)


@pytest.mark.parametrize(
    ("p_value", "light"),
    [(0.62, "green"), (0.05, "green"), (0.049, "amber"), (0.01, "amber"), (0.0099, "red")],
)
def test_grade_binomial_record_acepta_el_color_que_sus_cortes_deciden(
    p_value: float, light: str
) -> None:
    """La fila explica su propio color: verde con ``p >= verde``, ámbar con ``rojo <= p < verde``,
    rojo por debajo; los bordes son inclusivos por abajo, como en el kernel."""
    record = _grade_record(p_value=p_value, traffic_light=light)
    assert record.traffic_light == light


@pytest.mark.parametrize(
    ("p_value", "light"),
    [(0.001, "green"), (0.62, "red"), (0.03, "green"), (0.62, "amber"), (0.005, "amber")],
)
def test_grade_binomial_record_rechaza_un_color_que_sus_cortes_no_explican(
    p_value: float, light: str
) -> None:
    """Pasada 3 de Codex sobre la capa A: el DTO aceptaba ``p_value=0.001`` con cortes 0,05/0,01 y
    color verde. Los consumidores confían en el color y publican los cortes aparte, así que una
    construcción pública o una actualización parcial podía producir evidencia contradictoria."""
    with pytest.raises(ValidationError, match="traffic_light no corresponde"):
        _grade_record(p_value=p_value, traffic_light=light)


def test_la_regla_del_dto_es_la_del_kernel() -> None:
    """El DTO no puede importar ``calibration_tests`` (importaría al revés), así que replica la
    regla; este gate los ata sobre una malla de p-valores y cortes, bordes incluidos."""
    from nikodym.validation.calibration_tests import traffic_light

    for green, red in [(0.05, 0.01), (0.10, 0.02), (0.5, 0.499), (0.05004, 0.01004)]:
        for p_value in [0.0, red / 2, red, (red + green) / 2, green, (green + 1) / 2, 1.0]:
            esperado = traffic_light(p_value, green_alpha=green, red_alpha=red)
            record = _grade_record(
                p_value=p_value, green_alpha=green, red_alpha=red, traffic_light=esperado
            )
            assert record.traffic_light == esperado


def test_backtest_record_golden_y_test_por_parametro() -> None:
    record = _backtest_record(statistic=-0.0, realised_mean=-0.0)
    assert record.model_dump(mode="json") == {
        "parameter": "pd",
        "segment": "cartera_total",
        "n": 1400,
        "predicted_mean": 0.071,
        "realised_mean": 0.0,
        "test": "jeffreys",
        "statistic": 0.0,
        "p_value": 0.66,
        "alpha": 0.05,
        "one_sided": True,
        "decision": "pass",
    }
    assert math.copysign(1.0, record.statistic) == 1.0

    lgd = _backtest_record(parameter="lgd", segment="hipotecario", test="t_test")
    assert lgd.test == "t_test"
    ead = _backtest_record(parameter="ead", segment="comercial", test="t_test")
    assert ead.parameter == "ead"
    binomial_pd = _backtest_record(test="binomial")
    assert binomial_pd.test == "binomial"

    with pytest.raises(ValidationError, match="frozen"):
        record.p_value = 0.1
    with pytest.raises(ValidationError):
        _backtest_record(extra="no permitido")
    with pytest.raises(ValidationError, match="segment no puede"):
        _backtest_record(segment="")
    with pytest.raises(ValidationError, match=r"p_value debe estar"):
        _backtest_record(p_value=-0.1)
    with pytest.raises(ValidationError, match=r"alpha debe estar"):
        _backtest_record(alpha=1.0)
    with pytest.raises(ValidationError, match="PD usa binomial/jeffreys"):
        _backtest_record(parameter="pd", test="t_test")
    with pytest.raises(ValidationError, match="LGD/EAD usa el t-test"):
        _backtest_record(parameter="lgd", test="binomial")
    with pytest.raises(ValidationError, match="finitos"):
        _backtest_record(statistic=math.inf)


def test_validation_card_section_golden_copias_y_no_finitos() -> None:
    metric_sections: dict[str, Any] = {
        "resumen": {
            "delta": -0.0,
            "serie": [math.inf, math.nan, -0.0],
            "tupla": (-0.0,),
            "nested": {"valor": -0.0},
            "nota": "ok",
        }
    }
    versions = {"scipy": "1.14.1", "pandas": "2.3.3", "numpy": "2.4.6"}
    card = _card(dependency_versions=versions, metric_sections=metric_sections)

    assert card.model_dump(mode="json") == {
        "model_ref": "scorecard@2c8c7cc",
        "families_run": ["discrimination", "calibration", "stability", "backtesting"],
        "overall_status": "pass",
        "n_tests": 3,
        "n_failed": 0,
        "dependency_versions": {"numpy": "2.4.6", "pandas": "2.3.3", "scipy": "1.14.1"},
        "falta_dato": ["DATO-INSTITUCIONAL-VAL-4: families incluye 'backtesting'"],
        "metric_sections": {
            "resumen": {
                "delta": 0.0,
                "serie": [None, None, 0.0],
                "tupla": [0.0],
                "nested": {"valor": 0.0},
                "nota": "ok",
            }
        },
    }
    assert card.model_ref == "scorecard@2c8c7cc"
    assert math.copysign(1.0, card.metric_sections["resumen"]["delta"]) == 1.0

    versions["pandas"] = "mutado"
    metric_sections["resumen"]["delta"] = 99.0
    card.dependency_versions["pandas"] = "mutado"
    card.metric_sections["resumen"]["delta"] = 88.0

    assert card.dependency_versions == {"numpy": "2.4.6", "pandas": "2.3.3", "scipy": "1.14.1"}
    assert card.metric_sections["resumen"]["delta"] == 0.0

    with pytest.raises(ValidationError, match="frozen"):
        card.n_tests = 10
    with pytest.raises(ValidationError):
        _card(extra="no permitido")


def test_validation_card_section_valida_shape_y_defaults() -> None:
    assert _card(metric_sections=None).metric_sections == {}
    assert _card(falta_dato=()).falta_dato == ()

    with pytest.raises(ValidationError, match="model_ref no puede"):
        _card(model_ref="  ")
    with pytest.raises(ValidationError, match="families_run no puede estar"):
        _card(families_run=())
    with pytest.raises(ValidationError, match="duplicadas"):
        _card(families_run=("calibration", "calibration"))
    with pytest.raises(ValidationError, match="solo admite familias"):
        _card(families_run=("calibration", "inexistente"))
    with pytest.raises(ValidationError, match="n_failed no puede exceder"):
        _card(n_tests=2, n_failed=3)
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])


def test_validation_result_envuelve_frames_records_y_card_con_copias() -> None:
    discrimination = _discrimination_frame()
    calibration = _calibration_frame()
    result = _result(discrimination=discrimination, calibration=calibration)

    discrimination.loc[0, "auc"] = 0.99
    calibration.loc[0, "statistic"] = 99.0
    observed_disc = result.discrimination
    observed_calib = result.calibration

    assert result.discrimination is not result.discrimination
    assert_frame_equal(observed_disc, _discrimination_frame())
    assert_frame_equal(observed_calib, _calibration_frame())
    assert tuple(observed_disc.columns) == (
        "partition",
        "n_total",
        "n_bad",
        "auc",
        "gini",
        "ks",
        "source",
        "status",
    )
    assert tuple(result.stability.columns) == (
        "metric",
        "comparison",
        "feature",
        "value",
        "stable_threshold",
        "review_threshold",
        "band",
        "action",
        "source",
        "status",
        "decision",
    )
    assert tuple(result.backtesting.columns) == (
        "parameter",
        "segment",
        "n",
        "predicted_mean",
        "realised_mean",
        "test",
        "statistic",
        "p_value",
        "alpha",
        "one_sided",
        "decision",
    )

    observed_disc.loc[0, "auc"] = 0.11
    assert_frame_equal(result.discrimination, _discrimination_frame())

    round_tripped = ValidationResult.model_validate(
        {
            "discrimination": result.discrimination,
            "calibration": result.calibration,
            "stability": result.stability,
            "backtesting": result.backtesting,
            "discrimination_records": [r.model_dump() for r in result.discrimination_records],
            "calibration_records": [r.model_dump() for r in result.calibration_records],
            "grade_records": [r.model_dump() for r in result.grade_records],
            "backtest_records": [r.model_dump() for r in result.backtest_records],
            "card": result.card.model_dump(),
        }
    )
    assert_frame_equal(round_tripped.discrimination, result.discrimination)
    assert round_tripped.discrimination_records == result.discrimination_records
    assert round_tripped.calibration_records == result.calibration_records
    assert round_tripped.grade_records == result.grade_records
    assert round_tripped.backtest_records == result.backtest_records
    assert round_tripped.card == result.card

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card()
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_validation_result_normaliza_menos_cero_en_dtypes_float() -> None:
    frame = pd.DataFrame(
        {
            "partition": ["desarrollo", "oot"],
            "n_total": [1000, 400],
            "n_bad": [80, 40],
            "auc": pd.array([-0.0, math.nan], dtype="float64"),
            "gini": pd.array([-0.0, None], dtype="Float64"),
            "ks": pd.Series([-0.0, 0.44], dtype="float32"),
            "source": ["performance_artifact", "performance_artifact"],
            "status": ["ok", "ok"],
        }
    )
    result = _result(discrimination=frame)
    observed = result.discrimination

    expected = pd.DataFrame(
        {
            "partition": ["desarrollo", "oot"],
            "n_total": [1000, 400],
            "n_bad": [80, 40],
            "auc": pd.array([0.0, math.nan], dtype="float64"),
            "gini": pd.array([0.0, None], dtype="Float64"),
            "ks": pd.Series([0.0, 0.44], dtype="float32"),
            "source": ["performance_artifact", "performance_artifact"],
            "status": ["ok", "ok"],
        }
    )
    assert_frame_equal(observed, expected)
    assert math.copysign(1.0, observed.loc[0, "auc"]) == 1.0
    assert observed.loc[1, "gini"] is pd.NA
    assert math.isnan(observed.loc[1, "auc"])


def test_validation_result_valida_frames_y_consistencia_card() -> None:
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(discrimination="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(discrimination=_discrimination_frame().drop(columns=["status"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(calibration=_calibration_frame().drop(columns=["traffic_light"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(stability=_stability_frame().drop(columns=["decision"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(backtesting=_backtesting_frame().drop(columns=["one_sided"]))

    with pytest.raises(ValidationError, match="una fila por discrimination_record"):
        _result(discrimination_records=(_discrimination_record(),))
    with pytest.raises(ValidationError, match="una fila por test de calibración"):
        _result(grade_records=())
    with pytest.raises(ValidationError, match="una fila por backtest_record"):
        _result(backtest_records=())

    with pytest.raises(ValidationError, match="discrimination_records exige"):
        _result(card=_card(families_run=("calibration", "stability", "backtesting")))
    with pytest.raises(ValidationError, match="tests de calibración exigen"):
        _result(card=_card(families_run=("discrimination", "stability", "backtesting")))
    with pytest.raises(ValidationError, match="backtest_records exige"):
        _result(card=_card(families_run=("discrimination", "calibration", "stability")))
    with pytest.raises(ValidationError, match="stability exige"):
        _result(card=_card(families_run=("discrimination", "calibration", "backtesting")))


def _card_con_semaforo(**cortes: float) -> ValidationCardSection:
    """Card con la sección CT-2 de validación tal como la publica el evaluador."""
    cuts = {"green_alpha": 0.05, "red_alpha": 0.01, **cortes}
    return _card(
        metric_sections={
            "validation": {
                "traffic_light": {"green": 1, "amber": 0, "red": 0},
                "not_evaluable_grades": [],
                "traffic_light_cuts": cuts,
            }
        }
    )


def test_validation_result_reconcilia_las_filas_de_grado_con_los_records_y_la_card() -> None:
    """Pasada 4 de Codex sobre la capa A: la tabla (lo que pinta el informe), los records (lo que
    lee el trail) y la card (lo que leen la prosa y el panel) son tres copias del mismo semáforo,
    y el validador agregado sólo contaba filas. Coherentes, el resultado se construye; alterada
    UNA copia sin mover cardinalidades, falla nombrando la copia."""
    assert _result(card=_card_con_semaforo()).grade_records[0].green_alpha == 0.05

    tabla = _calibration_frame()
    tabla.loc[2, "green_alpha"] = 0.10
    with pytest.raises(ValidationError, match=r"fila de grado 'A'.*green_alpha"):
        _result(calibration=tabla)

    tabla = _calibration_frame()
    tabla.loc[2, "p_value"] = 0.61
    with pytest.raises(ValidationError, match=r"fila de grado 'A'.*p_value"):
        _result(calibration=tabla)

    tabla = _calibration_frame()
    tabla.loc[2, "traffic_light"] = "amber"
    with pytest.raises(ValidationError, match=r"fila de grado 'A'.*traffic_light"):
        _result(calibration=tabla)

    with pytest.raises(ValidationError, match="traffic_light_cuts de la card"):
        _result(card=_card_con_semaforo(green_alpha=0.10))

    card = _card(
        metric_sections={
            "validation": {
                "traffic_light": {"green": 0, "amber": 1, "red": 0},
                "traffic_light_cuts": {"green_alpha": 0.05, "red_alpha": 0.01},
            }
        }
    )
    with pytest.raises(ValidationError, match="recuento de colores de la card"):
        _result(card=card)

    # Pasada 5 de Codex: con grade_records, una card que perdió la sección CT-2 o una de sus dos
    # claves no se acepta —el informe y el panel leerían la card y callarían los cortes—.
    with pytest.raises(ValidationError, match="exige metric_sections"):
        _result(card=_card(metric_sections={}))
    with pytest.raises(ValidationError, match="traffic_light_cuts"):
        _result(card=_card(metric_sections={"validation": {"traffic_light": {"green": 1}}}))
    with pytest.raises(ValidationError, match="recuento de colores"):
        _result(
            card=_card(
                metric_sections={
                    "validation": {"traffic_light_cuts": {"green_alpha": 0.05, "red_alpha": 0.01}}
                }
            )
        )
    # Sin grade_records no hay semáforo que reconciliar: una card mínima sigue valiendo (con el
    # conteo que sus records derivan: el HL y el backtest).
    assert (
        _result(
            calibration=_calibration_frame().iloc[:2],
            calibration_records=_calibration_records(),
            grade_records=(),
            card=_card(n_tests=2, metric_sections={}),
        ).card.metric_sections
        == {}
    )
    # Y los records tienen que compartir cortes entre sí, haya o no card que reconciliar.
    tabla = _calibration_frame()
    tabla.loc[2, "green_alpha"] = 0.10
    with pytest.raises(ValidationError, match="compartir los mismos cortes"):
        _result(
            calibration=pd.concat([tabla, _calibration_frame().iloc[[2]]], ignore_index=True),
            calibration_records=_calibration_records(),
            grade_records=(_grade_record(green_alpha=0.10), _grade_record()),
            card=_card(metric_sections={}),
        )


def _hl_no_evaluable() -> tuple[pd.DataFrame, tuple[CalibrationTestRecord, ...]]:
    """Tabla y records con el HL de ``desarrollo`` sin veredicto por un grupo bajo el mínimo."""
    tabla = _calibration_frame()
    tabla["statistic"] = tabla["statistic"].astype(object)
    tabla.loc[0, "statistic"] = None
    tabla.loc[0, "p_value"] = None
    tabla.loc[0, "alpha"] = None
    tabla.loc[0, "decision"] = "not_evaluable"
    tabla.loc[0, "not_evaluable_reason"] = "group_below_min"
    records = (_hl_not_evaluable_record(), *_calibration_records()[1:])
    return tabla, records


def _card_hl_no_evaluable(**updates: Any) -> ValidationCardSection:
    """La card coherente con :func:`_hl_no_evaluable`: el HL sale de ``n_tests`` y la sección CT-2
    enumera la partición con su causa."""
    section: dict[str, Any] = {
        "traffic_light": {"green": 1, "amber": 0, "red": 0},
        "not_evaluable_grades": [],
        "traffic_light_cuts": {"green_alpha": 0.05, "red_alpha": 0.01},
        "min_rows_per_group": 200,
        "not_evaluable_partitions": [
            {
                "partition": "desarrollo",
                "n": 1000,
                "n_groups": 10,
                "min_group_size": 100,
                "min_rows": 200,
                "reason": "group_below_min",
            }
        ],
    }
    payload: dict[str, Any] = {"n_tests": 2, "metric_sections": {"validation": section}}
    payload.update(updates)
    return _card(**payload)


def test_validation_result_reconcilia_las_filas_de_hosmer_lemeshow_con_los_records_y_la_card() -> (
    None
):
    """D-VAL-17 extiende la reconciliación de la pasada 4 a las filas sin semáforo: la tabla (lo
    que pinta el informe), los records (lo que lee el trail) y la card (lo que leen la prosa y el
    panel) dicen lo mismo del estadístico, el veredicto y la causa de cada Hosmer-Lemeshow."""
    tabla, records = _hl_no_evaluable()
    coherente = _result(
        calibration=tabla, calibration_records=records, card=_card_hl_no_evaluable()
    )
    assert coherente.calibration_records[0].not_evaluable_reason == "group_below_min"

    # La tabla dice otra cosa que el record: estadístico, veredicto o causa.
    alterada = tabla.copy()
    alterada.loc[0, "statistic"] = 0.0
    with pytest.raises(ValidationError, match=r"fila 'hosmer_lemeshow'.*'desarrollo'.*statistic"):
        _result(calibration=alterada, calibration_records=records, card=_card_hl_no_evaluable())
    alterada = tabla.copy()
    alterada.loc[0, "decision"] = "pass"
    with pytest.raises(ValidationError, match=r"fila 'hosmer_lemeshow'.*decision"):
        _result(calibration=alterada, calibration_records=records, card=_card_hl_no_evaluable())
    alterada = tabla.copy()
    alterada.loc[0, "not_evaluable_reason"] = "degenerate_group"
    with pytest.raises(ValidationError, match=r"fila 'hosmer_lemeshow'.*not_evaluable_reason"):
        _result(calibration=alterada, calibration_records=records, card=_card_hl_no_evaluable())

    # La card perdió la partición sin veredicto, o la lista con otra causa.
    with pytest.raises(ValidationError, match="not_evaluable_partitions"):
        _result(
            calibration=tabla,
            calibration_records=records,
            card=_card_hl_no_evaluable(
                metric_sections={
                    "validation": {
                        "traffic_light": {"green": 1, "amber": 0, "red": 0},
                        "traffic_light_cuts": {"green_alpha": 0.05, "red_alpha": 0.01},
                        "not_evaluable_partitions": [],
                    }
                }
            ),
        )
    section = dict(_card_hl_no_evaluable().metric_sections["validation"])
    section["not_evaluable_partitions"] = [
        {**section["not_evaluable_partitions"][0], "reason": "partition_below_min"}
    ]
    with pytest.raises(ValidationError, match="not_evaluable_partitions"):
        _result(
            calibration=tabla,
            calibration_records=records,
            card=_card_hl_no_evaluable(metric_sections={"validation": section}),
        )
    # Sin HL sin veredicto, una card con la lista vacía —o sin la clave— vale.
    assert _result().calibration_records[0].decision == "pass"


def test_validation_result_reconcilia_todos_los_campos_comunes_de_cada_fila() -> None:
    """Pasada 1 de Codex sobre la capa B: la comparación tabla ↔ record omitía ``alpha`` y
    ``degrees_of_freedom`` en HL y ``n``/``observed_defaults``/``expected_pd``/``observed_dr``/
    ``alpha``/``test``/``statistic`` en las filas de grado, así que un resultado rehidratado podía
    cambiar el alfa, los grados de libertad o el tamaño de muestra y seguir validando."""
    for columna, valor in (("alpha", 0.1), ("degrees_of_freedom", 7.0)):
        tabla = _calibration_frame()
        tabla.loc[0, columna] = valor
        with pytest.raises(
            ValidationError, match=rf"fila 'hosmer_lemeshow'.*'desarrollo'.*{columna}"
        ):
            _result(calibration=tabla)
    for columna, valor in (
        ("n", 501),
        ("observed_defaults", 9),
        ("expected_pd", 0.03),
        ("observed_dr", 0.02),
        ("alpha", 0.1),
        ("test", "binomial"),
        ("statistic", 0.0),
    ):
        tabla = _calibration_frame()
        tabla.loc[2, columna] = valor
        with pytest.raises(ValidationError, match=rf"fila de grado 'A'.*{columna}"):
            _result(calibration=tabla)


def test_validation_result_rechaza_particiones_sin_veredicto_malformadas_o_adulteradas() -> None:
    """Pasada 1 de Codex sobre la capa B: la card se reducía a ``(partition, reason)`` y descartaba
    en silencio las entradas que no fueran mappings. Cada entrada es ahora un DTO cerrado
    (``NotEvaluablePartition``) con sus invariantes, y sus números se reconcilian con la tabla y
    los records: ``n`` con la fila, ``n_groups`` con el record, ``min_group_size`` con
    ``n // n_groups`` y ``min_rows`` homogéneo."""
    from nikodym.validation.results import NOT_EVALUABLE_PARTITION_FIELDS, NotEvaluablePartition

    assert tuple(NotEvaluablePartition.model_fields) == NOT_EVALUABLE_PARTITION_FIELDS
    tabla, records = _hl_no_evaluable()
    base = _card_hl_no_evaluable().metric_sections["validation"]

    def con(entradas: list[Any]) -> ValidationCardSection:
        return _card_hl_no_evaluable(
            metric_sections={"validation": {**base, "not_evaluable_partitions": entradas}}
        )

    entrada = dict(base["not_evaluable_partitions"][0])
    # Coherente: se construye.
    _result(calibration=tabla, calibration_records=records, card=con([entrada]))
    # Una entrada que no es un mapping ya no se descarta en silencio: junto a la entrada válida, la
    # basura tiene que acusarse como inválida (filtrarla dejaría la lista coherente y pasaría).
    with pytest.raises(ValidationError, match="entrada inválida"):
        _result(calibration=tabla, calibration_records=records, card=con([entrada, "basura"]))
    # Una entrada extra que no corresponde a ningún record.
    with pytest.raises(ValidationError, match="not_evaluable_partitions"):
        _result(calibration=tabla, calibration_records=records, card=con([entrada, entrada]))
    # Cada número adulterado por separado.
    for clave, valor, patron in (
        ("n", 999, "n"),
        ("n_groups", 5, "n_groups"),
        ("min_group_size", 99, "min_group_size"),
        ("min_rows", 0, "min_rows"),
    ):
        with pytest.raises(ValidationError, match=patron):
            _result(
                calibration=tabla,
                calibration_records=records,
                card=con([{**entrada, clave: valor}]),
            )
    # Un campo de más o uno de menos.
    with pytest.raises(ValidationError):
        _result(calibration=tabla, calibration_records=records, card=con([{**entrada, "x": 1}]))
    sin_min = {k: v for k, v in entrada.items() if k != "min_rows"}
    with pytest.raises(ValidationError):
        _result(calibration=tabla, calibration_records=records, card=con([sin_min]))
    # Los invariantes del DTO, solos: la partición entera bajo el mínimo no forma grupos y el
    # grupo más chico es el que ``np.array_split`` deja.
    NotEvaluablePartition(
        partition="p",
        n=20,
        n_groups=10,
        min_group_size=None,
        min_rows=30,
        reason="partition_below_min",
    )
    with pytest.raises(ValidationError, match="min_group_size"):
        NotEvaluablePartition(
            partition="p",
            n=20,
            n_groups=10,
            min_group_size=2,
            min_rows=30,
            reason="partition_below_min",
        )
    with pytest.raises(ValidationError, match="bajo el mínimo"):
        NotEvaluablePartition(
            partition="p",
            n=40,
            n_groups=10,
            min_group_size=None,
            min_rows=30,
            reason="partition_below_min",
        )
    with pytest.raises(ValidationError, match="min_group_size"):
        NotEvaluablePartition(
            partition="p",
            n=100,
            n_groups=10,
            min_group_size=9,
            min_rows=30,
            reason="group_below_min",
        )
    with pytest.raises(ValidationError, match="min_rows"):
        NotEvaluablePartition(
            partition="p",
            n=400,
            n_groups=10,
            min_group_size=40,
            min_rows=30,
            reason="group_below_min",
        )


@pytest.mark.parametrize(
    ("n", "min_group_size", "min_rows", "reason"),
    [
        # Grupo vacío: sólo puede ser degenerado (el kernel lo mira antes que el mínimo).
        (5, 0, 3, "group_below_min"),
        (5, 0, 3, "non_finite_statistic"),
        # Grupo no vacío bajo el mínimo: sólo puede ser group_below_min (la puerta va antes del
        # estadístico).
        (25, 2, 3, "non_finite_statistic"),
        (25, 2, 3, "degenerate_group"),
        # Grupo sobre el mínimo: no puede ser group_below_min.
        (100, 10, 3, "group_below_min"),
    ],
)
def test_not_evaluable_partition_reproduce_la_precedencia_de_causas_del_kernel(
    n: int, min_group_size: int, min_rows: int, reason: str
) -> None:
    """Pasada 3 de Codex sobre la capa B: el DTO sólo cotejaba el mínimo con ``group_below_min`` y
    aceptaba, por ejemplo, 25 filas en 10 grupos con mínimo 3 y causa ``non_finite_statistic``,
    que el kernel nunca produce (devuelve ``group_below_min`` antes de calcular nada). La
    precedencia exacta del kernel —vacío → degenerado; bajo el mínimo → ``group_below_min``;
    después denominador y finitud— queda codificada."""
    from nikodym.validation.results import NotEvaluablePartition

    with pytest.raises(ValidationError, match="kernel"):
        NotEvaluablePartition(
            partition="p",
            n=n,
            n_groups=10,
            min_group_size=min_group_size,
            min_rows=min_rows,
            reason=reason,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("n", "min_group_size", "reason"),
    [
        (5, 0, "degenerate_group"),
        (25, 2, "group_below_min"),
        (100, 10, "degenerate_group"),
        (100, 10, "non_finite_statistic"),
    ],
)
def test_not_evaluable_partition_acepta_lo_que_el_kernel_produce(
    n: int, min_group_size: int, reason: str
) -> None:
    from nikodym.validation.results import NotEvaluablePartition

    entrada = NotEvaluablePartition(
        partition="p",
        n=n,
        n_groups=10,
        min_group_size=min_group_size,
        min_rows=3,
        reason=reason,  # type: ignore[arg-type]
    )
    assert entrada.reason == reason


def test_validation_result_ancla_min_rows_al_umbral_efectivo_de_la_card() -> None:
    """Pasada 4 de Codex sobre la capa B: `min_rows` de cada partición sin veredicto sólo se
    exigía homogéneo, así que una card rehidratada podía decir «bajo el mínimo de 101» cuando el
    umbral ejecutado fue 200 (con una sola entrada la homogeneidad es vacua). La card publica el
    umbral efectivo una vez —``metric_sections.validation.min_rows_per_group``, el mismo patrón
    que ``traffic_light_cuts``— y cada copia (particiones y grados sin veredicto) se coteja contra
    él. El límite que queda es el mismo declarado en la capa A: adulterar TODAS las copias a la
    vez no se detecta sin el config."""
    tabla, records = _hl_no_evaluable()
    base = _card_hl_no_evaluable().metric_sections["validation"]

    def con(**cambios: Any) -> ValidationCardSection:
        return _card_hl_no_evaluable(metric_sections={"validation": {**base, **cambios}})

    entrada = dict(base["not_evaluable_partitions"][0])
    _result(calibration=tabla, calibration_records=records, card=con())
    # 200 → 101: sigue cumpliendo los invariantes del DTO, pero no es el umbral de la corrida.
    with pytest.raises(ValidationError, match=r"min_rows.*101.*200"):
        _result(
            calibration=tabla,
            calibration_records=records,
            card=con(not_evaluable_partitions=[{**entrada, "min_rows": 101}]),
        )
    # Sin la clave canónica no hay contra qué cotejar: con particiones sin veredicto se exige.
    sin_clave = {k: v for k, v in base.items() if k != "min_rows_per_group"}
    with pytest.raises(ValidationError, match="min_rows_per_group"):
        _result(
            calibration=tabla,
            calibration_records=records,
            card=_card_hl_no_evaluable(metric_sections={"validation": sin_clave}),
        )
    # Un umbral canónico que no es un entero positivo tampoco vale.
    with pytest.raises(ValidationError, match="min_rows_per_group"):
        _result(calibration=tabla, calibration_records=records, card=con(min_rows_per_group=0))
    # Los grados bajo mínimo también llevan `min_rows` (desde B22.6) y se cotejan con la misma
    # clave.
    grado = {
        "grade": "Z",
        "n": 12,
        "observed_defaults": 3,
        "expected_pd": 0.2,
        "observed_dr": 0.25,
        "min_rows": 30,
        "status": "not_evaluable",
    }
    with pytest.raises(ValidationError, match=r"not_evaluable_grades.*min_rows"):
        _result(
            calibration=tabla, calibration_records=records, card=con(not_evaluable_grades=[grado])
        )
    _result(
        calibration=tabla,
        calibration_records=records,
        card=con(not_evaluable_grades=[{**grado, "min_rows": 200}]),
    )


def test_validation_result_exige_que_la_card_cuente_solo_decisiones_evaluables() -> None:
    """D-VAL-17: ``n_tests``/``n_failed`` y ``overall_status`` son derivables de los records y del
    frame de estabilidad, y la card no puede decir otra cosa (una card rehidratada con ``n_tests``
    inflado publicaría «0 de 5 pruebas fallidas» sobre tres pruebas)."""
    with pytest.raises(ValidationError, match=r"n_tests.*3"):
        _result(card=_card(n_tests=5))
    with pytest.raises(ValidationError, match=r"n_failed"):
        _result(card=_card(n_tests=3, n_failed=1))
    with pytest.raises(ValidationError, match=r"overall_status.*'pass'"):
        _result(card=_card(overall_status="warn"))
    # Un HL sin veredicto no cuenta: con él fuera, la card dice 2 y no 3.
    tabla, records = _hl_no_evaluable()
    with pytest.raises(ValidationError, match=r"n_tests.*2"):
        _result(
            calibration=tabla, calibration_records=records, card=_card_hl_no_evaluable(n_tests=3)
        )
    # Y la sección CT-2, cuando repite el resumen, tiene que repetirlo igual.
    section = {
        **_card().metric_sections["validation"],
        "overall_status": "fail",
        "n_tests": 3,
        "n_failed": 0,
    }
    with pytest.raises(ValidationError, match=r"metric_sections.*overall_status"):
        _result(card=_card(metric_sections={"validation": section}))


def test_validation_result_sin_evidencia_evaluable_es_not_evaluable() -> None:
    """§8-9: una validación sin ninguna prueba evaluable no dice «Pasa»: su estado es la cuarta
    palabra, y la card tiene que llevarla."""
    tabla, records = _hl_no_evaluable()
    solo_hl = tabla.iloc[:2]
    solo_hl_records = records
    stability_sin_decision = _stability_frame()
    stability_sin_decision.loc[0, "band"] = "not_evaluable"
    stability_sin_decision.loc[0, "decision"] = "not_evaluable"
    stability_sin_decision.loc[0, "status"] = "not_evaluable"
    kwargs: dict[str, Any] = {
        "calibration": solo_hl,
        "calibration_records": solo_hl_records,
        "grade_records": (),
        "stability": stability_sin_decision,
        "backtesting": _backtesting_frame().iloc[:0],
        "backtest_records": (),
    }
    card = _card_hl_no_evaluable(
        overall_status="not_evaluable",
        n_tests=0,
        n_failed=0,
        metric_sections={
            "validation": {
                "not_evaluable_partitions": _card_hl_no_evaluable().metric_sections["validation"][
                    "not_evaluable_partitions"
                ],
                "min_rows_per_group": 200,
            }
        },
    )
    result = _result(card=card, **kwargs)
    assert result.card.overall_status == "not_evaluable"
    with pytest.raises(ValidationError, match=r"overall_status.*'not_evaluable'"):
        _result(card=card.model_copy(update={"overall_status": "pass"}), **kwargs)


def test_validation_results_lazy_exports_y_nucleo_liviano_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.core;"
        "import nikodym.validation as validation;"
        "blocked=[m for m in ('pandas','pandera','scipy','sklearn','statsmodels') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "loaded=[getattr(validation, name) for name in "
        "('DiscriminationRecord','CalibrationTestRecord','GradeBinomialRecord',"
        "'BacktestRecord','ValidationCardSection','ValidationResult')];"
        "assert loaded[-1].__name__ == 'ValidationResult';"
        "blocked=[m for m in ('pandas','pandera','scipy','sklearn','statsmodels') "
        "if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert validation_pkg.ValidationResult is ValidationResult
    with pytest.raises(AttributeError, match="NoExiste"):
        _ = validation_pkg.NoExiste


def test_results_module_expone_aliases_y_resuelve_discrepancia_brier() -> None:
    assert validation_results.BacktestParameter == ConfigBacktestParameter
    assert validation_results.PdTest == ConfigPdTest
    assert validation_results.ValidationFamily == ConfigValidationFamily
    assert not hasattr(validation_results, "BrierRecord")
    for name in (
        "DiscriminationRecord",
        "CalibrationTestRecord",
        "GradeBinomialRecord",
        "BacktestRecord",
        "ValidationCardSection",
        "ValidationResult",
    ):
        assert name in validation_results.__all__


def _discrimination_record(**updates: Any) -> DiscriminationRecord:
    payload: dict[str, Any] = {
        "partition": "desarrollo",
        "n_total": 1000,
        "n_bad": 80,
        "auc": 0.82,
        "gini": 0.64,
        "ks": 0.50,
        "source": "performance_artifact",
        "status": "ok",
    }
    payload.update(updates)
    return DiscriminationRecord(**payload)


def _calibration_record(**updates: Any) -> CalibrationTestRecord:
    payload: dict[str, Any] = {
        "partition": "desarrollo",
        "test": "hosmer_lemeshow",
        "n_groups": 10,
        "degrees_of_freedom": 8,
        "statistic": 7.34,
        "p_value": 0.50,
        "alpha": 0.05,
        "decision": "pass",
    }
    payload.update(updates)
    return CalibrationTestRecord(**payload)


def _grade_record(**updates: Any) -> GradeBinomialRecord:
    payload: dict[str, Any] = {
        "grade": "A",
        "n": 500,
        "expected_pd": 0.02,
        "observed_defaults": 8,
        "observed_dr": 0.016,
        "test": "jeffreys",
        "p_value": 0.62,
        "z_stat": -0.48,
        "alpha": 0.05,
        "traffic_light": "green",
        "green_alpha": 0.05,
        "red_alpha": 0.01,
    }
    payload.update(updates)
    return GradeBinomialRecord(**payload)


def _backtest_record(**updates: Any) -> BacktestRecord:
    payload: dict[str, Any] = {
        "parameter": "pd",
        "segment": "cartera_total",
        "n": 1400,
        "predicted_mean": 0.071,
        "realised_mean": 0.068,
        "test": "jeffreys",
        "statistic": -0.42,
        "p_value": 0.66,
        "alpha": 0.05,
        "one_sided": True,
        "decision": "pass",
    }
    payload.update(updates)
    return BacktestRecord(**payload)


def _card(**updates: Any) -> ValidationCardSection:
    payload: dict[str, Any] = {
        "model_ref": "scorecard@2c8c7cc",
        "families_run": ("discrimination", "calibration", "stability", "backtesting"),
        "overall_status": "pass",
        # Lo derivado de los records de ``_result()``: un HL con veredicto, un grado y un backtest.
        "n_tests": 3,
        "n_failed": 0,
        "dependency_versions": {"pandas": "2.3.3", "numpy": "2.4.6", "scipy": "1.14.1"},
        "falta_dato": ("DATO-INSTITUCIONAL-VAL-4: families incluye 'backtesting'",),
        # La sección CT-2 como la publica el evaluador: con grade_records, el resultado la exige.
        "metric_sections": {
            "validation": {
                "traffic_light": {"green": 1, "amber": 0, "red": 0},
                "not_evaluable_grades": [],
                "traffic_light_cuts": {"green_alpha": 0.05, "red_alpha": 0.01},
            }
        },
    }
    payload.update(updates)
    return ValidationCardSection(**payload)


def _result(
    *,
    discrimination: Any | None = None,
    calibration: Any | None = None,
    stability: Any | None = None,
    backtesting: Any | None = None,
    discrimination_records: tuple[DiscriminationRecord, ...] | None = None,
    calibration_records: tuple[CalibrationTestRecord, ...] | None = None,
    grade_records: tuple[GradeBinomialRecord, ...] | None = None,
    backtest_records: tuple[BacktestRecord, ...] | None = None,
    card: ValidationCardSection | None = None,
    extra: object | None = None,
) -> ValidationResult:
    payload: dict[str, Any] = {
        "discrimination": _discrimination_frame() if discrimination is None else discrimination,
        "calibration": _calibration_frame() if calibration is None else calibration,
        "stability": _stability_frame() if stability is None else stability,
        "backtesting": _backtesting_frame() if backtesting is None else backtesting,
        "discrimination_records": _discrimination_records()
        if discrimination_records is None
        else discrimination_records,
        "calibration_records": _calibration_records()
        if calibration_records is None
        else calibration_records,
        "grade_records": _grade_records() if grade_records is None else grade_records,
        "backtest_records": _backtest_records() if backtest_records is None else backtest_records,
        "card": _card() if card is None else card,
    }
    if extra is not None:
        payload["extra"] = extra
    return ValidationResult(**payload)


def _discrimination_records() -> tuple[DiscriminationRecord, ...]:
    return (
        _discrimination_record(),
        _discrimination_record(
            partition="oot", n_total=400, n_bad=40, auc=0.78, gini=0.56, ks=0.44
        ),
    )


def _calibration_records() -> tuple[CalibrationTestRecord, ...]:
    return (
        _calibration_record(),
        _calibration_record(
            test="brier",
            n_groups=None,
            degrees_of_freedom=None,
            statistic=0.062,
            p_value=None,
            alpha=None,
            decision="not_evaluable",
        ),
    )


def _grade_records() -> tuple[GradeBinomialRecord, ...]:
    return (_grade_record(),)


def _backtest_records() -> tuple[BacktestRecord, ...]:
    return (_backtest_record(),)


def _discrimination_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "oot"],
            "n_total": [1000, 400],
            "n_bad": [80, 40],
            "auc": [0.82, 0.78],
            "gini": [0.64, 0.56],
            "ks": [0.50, 0.44],
            "source": ["performance_artifact", "performance_artifact"],
            "status": ["ok", "ok"],
        }
    )


def _calibration_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "desarrollo", "desarrollo"],
            "test": ["hosmer_lemeshow", "brier", "jeffreys"],
            "grade": ["ALL", "ALL", "A"],
            "n": [1000, 1000, 500],
            "observed_defaults": [80, 80, 8],
            "expected_pd": [0.08, 0.08, 0.02],
            "observed_dr": [0.08, 0.08, 0.016],
            # El de la fila de grado es el ``z`` del record (-0.48): la reconciliación lo coteja.
            "statistic": [7.34, 0.062, -0.48],
            "degrees_of_freedom": [8.0, math.nan, math.nan],
            "p_value": [0.50, math.nan, 0.62],
            "alpha": [0.05, math.nan, 0.05],
            "decision": ["pass", "not_evaluable", "pass"],
            "traffic_light": [None, None, "green"],
            "green_alpha": [None, None, 0.05],
            "red_alpha": [None, None, 0.01],
            "not_evaluable_reason": [None, None, None],
        }
    )


def _stability_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "metric": ["score_psi"],
            "comparison": ["dev_vs_oot"],
            "feature": ["score"],
            "value": [0.083],
            "stable_threshold": [0.10],
            "review_threshold": [0.25],
            "band": ["stable"],
            "action": ["none"],
            "source": ["stability_artifact"],
            "status": ["ok"],
            "decision": ["pass"],
        }
    )


def _backtesting_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "parameter": ["pd"],
            "segment": ["cartera_total"],
            "n": [1400],
            "predicted_mean": [0.071],
            "realised_mean": [0.068],
            "test": ["jeffreys"],
            "statistic": [-0.42],
            "p_value": [0.66],
            "alpha": [0.05],
            "one_sided": [True],
            "decision": ["pass"],
        }
    )
