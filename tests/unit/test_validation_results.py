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
    }
    assert math.copysign(1.0, brier.statistic) == 1.0

    hl_not_evaluable = _calibration_record(decision="not_evaluable", p_value=None, alpha=None)
    assert hl_not_evaluable.p_value is None

    with pytest.raises(ValidationError, match="frozen"):
        hl.statistic = 1.0
    with pytest.raises(ValidationError):
        _calibration_record(extra="no permitido")
    with pytest.raises(ValidationError, match="finitos"):
        _calibration_record(statistic=math.nan)


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
        "n_tests": 5,
        "n_failed": 0,
        "dependency_versions": {"numpy": "2.4.6", "pandas": "2.3.3", "scipy": "1.14.1"},
        "falta_dato": ["FALTA-DATO-VAL-2"],
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
        "n_tests": 5,
        "n_failed": 0,
        "dependency_versions": {"pandas": "2.3.3", "numpy": "2.4.6", "scipy": "1.14.1"},
        "falta_dato": ("FALTA-DATO-VAL-2",),
        "metric_sections": {},
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
            "statistic": [7.34, 0.062, 0.48],
            "degrees_of_freedom": [8.0, math.nan, math.nan],
            "p_value": [0.50, math.nan, 0.62],
            "alpha": [0.05, math.nan, 0.05],
            "decision": ["pass", "not_evaluable", "pass"],
            "traffic_light": [None, None, "green"],
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
