"""Tests de resultados de ``model``: DTOs puros, model card y lazy exports."""

from __future__ import annotations

import math
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

from nikodym.model import results as model_results
from nikodym.model.results import (
    CoefficientRecord,
    ModelCardSection,
    ModelFitStatistics,
    ModelResult,
    StepwiseDecision,
)


def test_stepwise_decision_construible_frozen_extra_forbid_y_normaliza_float() -> None:
    decision = StepwiseDecision(
        iteration=1,
        feature="saldo",
        woe_column="saldo__woe",
        action="enter",
        criterion="wald_pvalue",
        p_value=-0.0,
        lr_stat=-0.0,
        beta=-0.0,
        threshold=-0.0,
        detail="entra por p-value bajo umbral",
    )

    assert decision.p_value == 0.0
    assert decision.lr_stat == 0.0
    assert decision.beta == 0.0
    assert decision.threshold == 0.0
    assert math.copysign(1.0, decision.p_value) == 1.0
    with pytest.raises(ValidationError, match="frozen"):
        decision.action = "remove"
    with pytest.raises(ValidationError):
        StepwiseDecision(
            iteration=1,
            feature="saldo",
            woe_column="saldo__woe",
            action="entrar",
            criterion="wald_pvalue",
            p_value=0.01,
            lr_stat=None,
            beta=-0.3,
            threshold=0.05,
            detail="literal inválido",
        )
    with pytest.raises(ValidationError):
        StepwiseDecision(
            iteration=1,
            feature="saldo",
            woe_column="saldo__woe",
            action="enter",
            criterion="wald_pvalue",
            p_value=0.01,
            lr_stat=None,
            beta=-0.3,
            threshold=0.05,
            detail="campo extra",
            detalle="no permitido",
        )


def test_coefficient_record_normaliza_floats_y_rechaza_extra() -> None:
    coefficient = CoefficientRecord(
        feature="intercept",
        woe_column="const",
        beta=-0.0,
        standard_error=-0.0,
        wald_z=-0.0,
        p_value=-0.0,
        conf_low=-0.0,
        conf_high=-0.0,
        expected_sign="none",
        sign_ok=None,
        iv=-0.0,
        iv_contribution=-0.0,
    )

    dump = coefficient.model_dump(mode="json")
    assert dump == {
        "feature": "intercept",
        "woe_column": "const",
        "beta": 0.0,
        "standard_error": 0.0,
        "wald_z": 0.0,
        "p_value": 0.0,
        "conf_low": 0.0,
        "conf_high": 0.0,
        "expected_sign": "none",
        "sign_ok": None,
        "iv": 0.0,
        "iv_contribution": 0.0,
    }
    assert math.copysign(1.0, coefficient.beta) == 1.0
    with pytest.raises(ValidationError, match="frozen"):
        coefficient.beta = 1.0
    with pytest.raises(ValidationError):
        CoefficientRecord(**(dump | {"expected_sign": "positive"}))
    with pytest.raises(ValidationError):
        CoefficientRecord(**(dump | {"origen": "statsmodels"}))


def test_model_fit_statistics_golden_y_normaliza_menos_cero() -> None:
    statistics = _fit_statistics(
        log_likelihood=-0.0,
        null_log_likelihood=-25.0,
        pseudo_r2_mcfadden=-0.0,
        aic=15.2,
        bic=18.7,
        llr=-0.0,
        llr_p_value=-0.0,
    )

    assert statistics.model_dump(mode="json") == {
        "n_obs_dev": 100,
        "n_events_dev": 30,
        "n_nonevents_dev": 70,
        "log_likelihood": 0.0,
        "null_log_likelihood": -25.0,
        "pseudo_r2_mcfadden": 0.0,
        "aic": 15.2,
        "bic": 18.7,
        "llr": 0.0,
        "llr_p_value": 0.0,
        "converged": True,
        "optimizer": "newton",
        "n_iterations": 7,
    }
    assert math.copysign(1.0, statistics.log_likelihood) == 1.0
    assert math.copysign(1.0, statistics.llr) == 1.0
    with pytest.raises(ValidationError):
        ModelFitStatistics(
            n_obs_dev=100,
            n_events_dev=30,
            n_nonevents_dev=70,
            log_likelihood=-12.3,
            null_log_likelihood=-25.0,
            pseudo_r2_mcfadden=0.51,
            aic=15.2,
            bic=18.7,
            llr=25.4,
            llr_p_value=0.002,
            converged=True,
            optimizer="newton",
            n_iterations=7,
            extra="no permitido",
        )


def test_model_result_construible_con_copias_defensivas_y_validacion() -> None:
    coefficients = _coefficients_frame()
    raw_pd = _raw_pd_frame()
    result = _model_result(coefficients=coefficients, raw_pd_frame=raw_pd)

    coefficients.loc[0, "beta"] = 999.0
    raw_pd.loc["c1", "pd_raw"] = 999.0
    observed_coefficients = result.coefficients
    observed_raw_pd = result.raw_pd_frame

    assert_frame_equal(observed_coefficients, _coefficients_frame())
    assert_frame_equal(observed_raw_pd, _raw_pd_frame())
    observed_coefficients.loc[0, "beta"] = 777.0
    observed_raw_pd.loc["c1", "pd_raw"] = 777.0
    assert_frame_equal(result.coefficients, _coefficients_frame())
    assert_frame_equal(result.raw_pd_frame, _raw_pd_frame())
    assert result.final_features == ("saldo", "ingreso", "mora")
    assert result.final_woe_columns == ("saldo__woe", "ingreso__woe", "mora__woe")
    with pytest.raises(ValidationError, match="final_features y final_woe_columns"):
        _model_result(final_woe_columns=("saldo__woe",))
    with pytest.raises(ValidationError):
        _model_result(extra="no permitido")


def test_model_card_section_from_result_golden_bit_identica() -> None:
    result = _model_result()
    card = ModelCardSection.from_result(
        result,
        engine="logit",
        thresholds=_thresholds(),
        dependency_versions={
            "statsmodels": "0.14.6",
            "pandas": "2.3.3",
            "numpy": "2.4.6",
        },
        metric_sections={
            "diagnostico": {
                "llr": -0.0,
                "serie": [-0.0, math.nan],
                "tupla": (-0.0,),
                "nota": "ok",
            }
        },
    )

    expected_dump = {
        "engine": "logit",
        "n_candidates": 4,
        "n_final_features": 3,
        "final_features": ["saldo", "ingreso", "mora"],
        "thresholds": {
            "entry_p_value": 0.05,
            "exit_p_value": 0.05,
            "iv_contribution.threshold": 0.45,
            "sign_policy.action": "flag",
            "umbral_no_finito": None,
        },
        "sign_flags": ["ingreso"],
        "iv_contribution_flags": ["mora"],
        "fit_statistics": _fit_statistics().model_dump(mode="json"),
        "dependency_versions": {
            "numpy": "2.4.6",
            "pandas": "2.3.3",
            "statsmodels": "0.14.6",
        },
        "metric_sections": {
            "diagnostico": {
                "llr": 0.0,
                "serie": [0.0, None],
                "tupla": [0.0],
                "nota": "ok",
            }
        },
    }
    expected = ModelCardSection(
        **(
            expected_dump
            | {
                "metric_sections": {
                    "diagnostico": {
                        "llr": 0.0,
                        "serie": [0.0, None],
                        "tupla": (0.0,),
                        "nota": "ok",
                    }
                }
            }
        )
    )

    assert card == expected
    assert card.model_dump(mode="json") == expected_dump
    assert math.copysign(1.0, card.metric_sections["diagnostico"]["llr"]) == 1.0


def test_model_card_section_no_muta_resultado_ni_parametros_y_entrega_copias() -> None:
    result = _model_result()
    original_coefficients = result.coefficients
    original_raw_pd = result.raw_pd_frame
    thresholds = _thresholds()
    dependency_versions = {"statsmodels": "0.14.6", "pandas": "2.3.3"}
    metric_sections: dict[str, Any] = {"diagnostico": {"ks": 0.31}}

    card = ModelCardSection.from_result(
        result,
        engine="glm_binomial",
        thresholds=thresholds,
        dependency_versions=dependency_versions,
        metric_sections=metric_sections,
    )
    thresholds["entry_p_value"] = 0.99
    dependency_versions["statsmodels"] = "roto"
    metric_sections["diagnostico"]["ks"] = 9.9
    card.thresholds["entry_p_value"] = 0.77
    card.dependency_versions["statsmodels"] = "mutado"
    card.metric_sections["diagnostico"]["ks"] = 8.8

    assert card.thresholds["entry_p_value"] == 0.05
    assert card.dependency_versions["statsmodels"] == "0.14.6"
    assert card.metric_sections == {"diagnostico": {"ks": 0.31}}
    assert_frame_equal(result.coefficients, original_coefficients)
    assert_frame_equal(result.raw_pd_frame, original_raw_pd)


def test_model_card_section_filtra_no_finitos_de_forma_determinista() -> None:
    coefficients = pd.DataFrame(
        {
            "feature": ["mora", "saldo", "ingreso", "intercept"],
            "woe_column": ["mora__woe", "saldo__woe", "ingreso__woe", "const"],
            "beta": [-0.3, -0.2, -0.1, -1.0],
            "standard_error": [math.inf, math.nan, 0.12, 0.08],
            "wald_z": [math.nan, -1.2, -0.8, -12.0],
            "p_value": [math.nan, 0.04, math.inf, 0.0],
            "conf_low": [-0.5, -0.4, math.nan, -1.2],
            "conf_high": [-0.1, 0.0, math.inf, -0.8],
            "expected_sign": ["negative", "negative", "negative", "none"],
            "sign_ok": [True, True, True, None],
            "iv": [0.25, 0.25, 0.25, None],
            "iv_contribution": [math.nan, math.inf, 0.55, None],
        }
    )
    trace = (
        _decision("saldo", criterion="iv_contribution", action="flag", threshold=math.nan),
        _decision("ingreso", criterion="sign", action="flag", beta=math.inf),
    )
    result = _model_result(coefficients=coefficients, stepwise_trace=trace)
    reordered = _model_result(
        coefficients=coefficients.iloc[::-1].reset_index(drop=True),
        stepwise_trace=tuple(reversed(trace)),
    )

    card = ModelCardSection.from_result(
        result,
        engine="logit",
        thresholds={"iv_contribution.threshold": 0.50},
        dependency_versions={},
    )
    reordered_card = ModelCardSection.from_result(
        reordered,
        engine="logit",
        thresholds={"iv_contribution.threshold": 0.50},
        dependency_versions={},
    )

    assert card.sign_flags == ("ingreso",)
    assert card.iv_contribution_flags == ("saldo", "ingreso")
    assert reordered_card.sign_flags == card.sign_flags
    assert reordered_card.iv_contribution_flags == card.iv_contribution_flags

    all_nonfinite = ModelCardSection.from_result(
        _model_result(
            coefficients=coefficients.assign(iv_contribution=[math.nan, math.inf, math.nan, None]),
            stepwise_trace=(),
        ),
        engine="logit",
        thresholds={"iv_contribution.threshold": math.nan},
        dependency_versions={},
    )
    assert all_nonfinite.thresholds["iv_contribution.threshold"] is None
    assert all_nonfinite.iv_contribution_flags == ()


def test_model_card_section_fallback_sin_candidate_features_y_columnas_faltantes() -> None:
    result = _model_result(
        estimator=SimpleNamespace(),
        coefficients=pd.DataFrame({"feature": ["saldo"], "beta": [-0.2]}),
        stepwise_trace=(_decision("mora", criterion="iv_contribution", action="exclude"),),
    )

    card = ModelCardSection.from_result(
        result,
        engine="logit",
        thresholds={"threshold": "sin uso"},
        dependency_versions={},
    )

    assert card.n_candidates == 3
    assert card.sign_flags == ()
    assert card.iv_contribution_flags == ()


def test_model_card_section_candidate_features_lista_y_metric_sections_none() -> None:
    result = _model_result(estimator=SimpleNamespace(feature_names_in_=["saldo", "ingreso"]))

    card = ModelCardSection.from_result(
        result,
        engine="logit",
        thresholds={},
        dependency_versions={},
        metric_sections=None,
    )

    assert card.n_candidates == 2
    assert card.metric_sections == {}
    direct_card = ModelCardSection(
        engine="logit",
        n_candidates=0,
        n_final_features=0,
        final_features=(),
        thresholds={},
        sign_flags=(),
        iv_contribution_flags=(),
        fit_statistics=_fit_statistics(),
        dependency_versions={},
        metric_sections=None,
    )
    assert direct_card.metric_sections == {}


def test_model_card_section_fallback_con_candidate_features_invalidas() -> None:
    result = _model_result(estimator=SimpleNamespace(feature_names_in_=("saldo", 123)))

    card = ModelCardSection.from_result(
        result,
        engine="logit",
        thresholds={},
        dependency_versions={},
    )

    assert card.n_candidates == 3


def test_model_card_section_metric_sections_tipo_invalido_y_dataframe_invalido() -> None:
    with pytest.raises(ValidationError):
        ModelCardSection(
            engine="logit",
            n_candidates=0,
            n_final_features=0,
            final_features=(),
            thresholds={},
            sign_flags=(),
            iv_contribution_flags=(),
            fit_statistics=_fit_statistics(),
            dependency_versions={},
            metric_sections=["no permitido"],
        )
    with pytest.raises(ValidationError):
        _model_result(coefficients=cast(Any, "no es DataFrame"))


def test_dataframe_floats_normalizan_menos_cero_al_entrar() -> None:
    coefficients = _coefficients_frame()
    coefficients.loc[0, "beta"] = -0.0
    raw_pd = _raw_pd_frame()
    raw_pd.loc["c1", "linear_predictor"] = -0.0
    raw_pd.loc["c2", "pd_raw"] = -0.0

    result = _model_result(coefficients=coefficients, raw_pd_frame=raw_pd)

    assert result.coefficients.loc[0, "beta"] == 0.0
    assert math.copysign(1.0, result.coefficients.loc[0, "beta"]) == 1.0
    assert result.raw_pd_frame.loc["c1", "linear_predictor"] == 0.0
    assert result.raw_pd_frame.loc["c2", "pd_raw"] == 0.0
    assert math.copysign(1.0, result.raw_pd_frame.loc["c2", "pd_raw"]) == 1.0


def test_model_results_lazy_exports_y_nucleo_liviano_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.model as model;"
        "blocked=[m for m in ('statsmodels','sklearn','scipy') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'pandas' not in sys.modules, 'pandas cargado antes del lazy export';"
        "loaded=[getattr(model, name) for name in "
        "('StepwiseDecision','CoefficientRecord','ModelFitStatistics',"
        "'ModelCardSection','ModelResult')];"
        "assert loaded[-1].__name__ == 'ModelResult';"
        "assert 'pandas' in sys.modules;"
        "blocked=[m for m in ('statsmodels','sklearn','scipy') if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_results_module_expone_aliases_publicos() -> None:
    assert "StepwiseAction" in model_results.__all__
    assert "StepwiseCriterion" in model_results.__all__


def _decision(
    feature: str,
    *,
    criterion: str = "wald_pvalue",
    action: str = "enter",
    p_value: float | None = 0.04,
    lr_stat: float | None = None,
    beta: float | None = -0.2,
    threshold: float | None = 0.05,
) -> StepwiseDecision:
    return StepwiseDecision(
        iteration=1,
        feature=feature,
        woe_column=f"{feature}__woe",
        action=action,
        criterion=criterion,
        p_value=p_value,
        lr_stat=lr_stat,
        beta=beta,
        threshold=threshold,
        detail=f"{criterion}:{action}",
    )


def _fit_statistics(
    *,
    log_likelihood: float = -12.3,
    null_log_likelihood: float = -25.0,
    pseudo_r2_mcfadden: float = 0.508,
    aic: float = 32.6,
    bic: float = 44.1,
    llr: float | None = 25.4,
    llr_p_value: float | None = 0.002,
) -> ModelFitStatistics:
    return ModelFitStatistics(
        n_obs_dev=100,
        n_events_dev=30,
        n_nonevents_dev=70,
        log_likelihood=log_likelihood,
        null_log_likelihood=null_log_likelihood,
        pseudo_r2_mcfadden=pseudo_r2_mcfadden,
        aic=aic,
        bic=bic,
        llr=llr,
        llr_p_value=llr_p_value,
        converged=True,
        optimizer="newton",
        n_iterations=7,
    )


def _model_result(
    *,
    estimator: Any | None = None,
    final_woe_columns: tuple[str, ...] = ("saldo__woe", "ingreso__woe", "mora__woe"),
    coefficients: pd.DataFrame | None = None,
    stepwise_trace: tuple[StepwiseDecision, ...] = (),
    raw_pd_frame: pd.DataFrame | None = None,
    extra: object | None = None,
) -> ModelResult:
    payload: dict[str, Any] = {
        "estimator": estimator
        if estimator is not None
        else SimpleNamespace(feature_names_in_=("saldo", "ingreso", "mora", "antiguedad")),
        "final_features": ("saldo", "ingreso", "mora"),
        "final_woe_columns": final_woe_columns,
        "coefficients": _coefficients_frame() if coefficients is None else coefficients,
        "stepwise_trace": stepwise_trace,
        "fit_statistics": _fit_statistics(),
        "raw_pd_frame": _raw_pd_frame() if raw_pd_frame is None else raw_pd_frame,
        "model_card": _card_placeholder(),
    }
    if extra is not None:
        payload["extra"] = extra
    return ModelResult(**payload)


def _card_placeholder() -> ModelCardSection:
    return ModelCardSection(
        engine="logit",
        n_candidates=4,
        n_final_features=3,
        final_features=("saldo", "ingreso", "mora"),
        thresholds={},
        sign_flags=(),
        iv_contribution_flags=(),
        fit_statistics=_fit_statistics(),
        dependency_versions={},
    )


def _coefficients_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "feature": ["intercept", "saldo", "ingreso", "mora"],
            "woe_column": ["const", "saldo__woe", "ingreso__woe", "mora__woe"],
            "beta": [-1.25, -0.42, 0.18, -0.31],
            "standard_error": [0.08, 0.11, 0.09, 0.13],
            "wald_z": [-15.625, -3.8181818182, 2.0, -2.3846153846],
            "p_value": [0.0, 0.0001, 0.0455, 0.0171],
            "conf_low": [-1.4068, -0.6356, 0.0036, -0.5648],
            "conf_high": [-1.0932, -0.2044, 0.3564, -0.0552],
            "expected_sign": ["none", "negative", "negative", "negative"],
            "sign_ok": [None, True, False, True],
            "iv": [None, 0.31, 0.22, 0.47],
            "iv_contribution": [None, 0.31, 0.22, 0.47],
        }
    )


def _raw_pd_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "desarrollo", "holdout"],
            "target": pd.Series([0, 1, 0], dtype="int64"),
            "linear_predictor": [-1.55, -0.25, 0.75],
            "pd_raw": [0.17508627, 0.4378235, 0.6791787],
            "score_input_complete": [True, True, True],
        },
        index=pd.Index(["c1", "c2", "c3"], name="cliente_id"),
    )


def _thresholds() -> dict[str, float | str | None]:
    return {
        "exit_p_value": 0.05,
        "entry_p_value": 0.05,
        "sign_policy.action": "flag",
        "iv_contribution.threshold": 0.45,
        "umbral_no_finito": math.nan,
    }
