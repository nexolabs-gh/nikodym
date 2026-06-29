"""Tests de Cox PH y AFT survival: goldens lifelines, bordes y contrato liviano."""

from __future__ import annotations

import importlib
import subprocess
import sys
import warnings
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from lifelines.datasets import load_rossi
from pandas.testing import assert_frame_equal

import nikodym.survival.cox_aft as ca_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import MissingDependencyError, NotFittedError
from nikodym.survival import AFTSurvivalModel as ExportedAFTSurvivalModel
from nikodym.survival import CoxPHSurvivalModel as ExportedCoxPHSurvivalModel
from nikodym.survival.base import BaseSurvivalModel
from nikodym.survival.config import (
    CoxAftConfig,
    SurvivalConfig,
    SurvivalInputConfig,
    SurvivalTimeGridConfig,
)
from nikodym.survival.cox_aft import AFTSurvivalModel, CoxPHSurvivalModel
from nikodym.survival.exceptions import (
    SurvivalConfigError,
    SurvivalFitError,
    SurvivalInputError,
    SurvivalTransformError,
)

_TERM_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "partition",
    "period",
    "time_value",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "method",
    "pd_source",
    "scenario",
    "warning_codes",
)
_HAZARD_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "period",
    "time_value",
    "hazard",
    "link",
    "linear_predictor_hazard",
)
_SURVIVAL_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "period",
    "time_value",
    "survival",
)


def test_cox_rossi_goldens_schoenfeld_warning_no_bloqueante_y_no_muta() -> None:
    """Cox real sobre Rossi publica goldens de lifelines y D-SUR-7 no bloquea."""
    frame = _rossi_frame()
    original = frame.copy(deep=True)
    audit = InMemoryAuditSink()

    with pytest.warns(UserWarning, match="D-SUR-7"):
        model = CoxPHSurvivalModel.from_config(_cfg("cox_ph")).fit(
            frame,
            duration_col="week",
            event_col="arrest",
            audit=audit,
        )
    survival = model.predict_survival(frame.iloc[:2], times=[10, 20, 30])
    hazards = model.predict_hazard(frame.iloc[:1], times=[10, 20, 30])
    term = model.term_structure(frame.iloc[:1], times=[10, 20, 30])
    diagnostics = model.proportional_hazard_diagnostics()

    expected_term = pd.DataFrame(
        {
            "row_id": ["R000", "R000", "R000"],
            "segment": [None, None, None],
            "partition": [None, None, None],
            "period": [1, 2, 3],
            "time_value": [10.0, 20.0, 30.0],
            "hazard": [0.030321364964003505, 0.05374108996471649, 0.046345008592101],
            "survival": [0.9696786350359965, 0.9175670482736635, 0.8750423955375919],
            "pd_marginal": [0.030321364964003505, 0.052111586762332976, 0.04252465273607169],
            "pd_cumulative": [0.030321364964003505, 0.08243295172633647, 0.12495760446240811],
            "method": ["cox_ph", "cox_ph", "cox_ph"],
            "pd_source": ["none", "none", "none"],
            "scenario": [None, None, None],
            "warning_codes": [("D-SUR-7",), ("D-SUR-7",), ("D-SUR-7",)],
        },
        index=pd.Index(["R000|1", "R000|2", "R000|3"], name="curve_id"),
    )

    assert isinstance(model, BaseSurvivalModel)
    assert tuple(term.columns) == _TERM_COLUMNS
    assert tuple(hazards.columns) == _HAZARD_COLUMNS
    assert tuple(survival.columns) == _SURVIVAL_COLUMNS
    assert_frame_equal(term, expected_term, check_dtype=False, atol=1e-12, rtol=1e-12)
    assert survival["survival"].tolist() == pytest.approx(
        [
            0.9696786350359965,
            0.9175670482736635,
            0.8750423955375919,
            0.912621138563536,
            0.77455224199654,
            0.6727471930575906,
        ],
        abs=1e-12,
    )
    assert hazards["linear_predictor_hazard"].tolist() == pytest.approx(
        [0.013808071910158662] * 3,
        abs=1e-12,
    )
    assert model.fit_statistics_["log_likelihood"] == pytest.approx(-660.8570253844155)
    assert model.fit_statistics_["partial_aic"] == pytest.approx(1327.714050768831)
    assert diagnostics["min_p"] == pytest.approx(0.010072964141879323)
    assert diagnostics["by_covariate"]["age"]["test_statistic"] == pytest.approx(6.6219472804162764)
    assert diagnostics["by_covariate"]["fin"]["p"] == pytest.approx(0.9821669038506964)
    assert diagnostics["by_covariate"]["prio"]["minus_log2_p"] == pytest.approx(1.3968186795520026)
    assert model.card_.metric_sections["schoenfeld"] == diagnostics
    assert [event.payload["regla"] for event in audit.events] == [
        "survival_method",
        "survival_input_quality",
        "survival_schoenfeld",
    ]
    assert_frame_equal(frame, original)
    assert "sksurv" not in sys.modules


def test_cox_con_umbral_ph_no_emite_warning_y_marca_violacion() -> None:
    """Con umbral configurado, Schoenfeld queda estructurado sin warning global."""
    frame = _rossi_frame()
    model = CoxPHSurvivalModel.from_config(_cfg("cox_ph", ph_p_value_threshold=0.05)).fit(
        frame,
        duration_col="week",
        event_col="arrest",
    )
    term = model.term_structure(frame.iloc[:1], times=[])

    assert model.proportional_hazard_diagnostics()["violations"] == ("age",)
    assert term["warning_codes"].tolist() == [("FALTA-DATO-SUR-1",)] * len(term.index)


def test_aft_rossi_goldens_tres_familias_y_frames() -> None:
    """AFT real exige familia explícita y reproduce goldens lifelines de Rossi."""
    frame = _rossi_frame()
    expected = {
        "weibull": {
            "aic": 1374.0825559545508,
            "survival": [0.972320271780808, 0.9285822473362704, 0.8774508191852732],
            "hazard": [0.027679728219191957, 0.04498314569172901, 0.05506397338272695],
            "pd_marginal": [0.027679728219191957, 0.043738024444537636, 0.051131428150997166],
            "pd_cumulative": [0.027679728219191957, 0.07141775266372963, 0.12254918081472677],
        },
        "lognormal": {
            "aic": 1384.8820697886802,
            "survival": [0.9690256766839346, 0.9104606169203698, 0.8502771518261052],
            "hazard": [0.030974323316065422, 0.060437056697999925, 0.0661022168073947],
            "pd_marginal": [0.030974323316065422, 0.05856505976356469, 0.060183465094264615],
            "pd_cumulative": [0.030974323316065422, 0.08953938307963016, 0.1497228481738948],
        },
        "loglogistic": {
            "aic": 1375.863626907072,
            "survival": [0.9737641570276476, 0.927781636220013, 0.873524945051999],
            "hazard": [0.026235842972352375, 0.04722141442132488, 0.05848002272287667],
            "pd_marginal": [0.026235842972352375, 0.045982520807634625, 0.05425669116801406],
            "pd_cumulative": [0.026235842972352375, 0.07221836377998703, 0.12647505494800104],
        },
    }

    for family, golden in expected.items():
        audit = InMemoryAuditSink()
        model = AFTSurvivalModel.from_config(_cfg("aft", aft_family=family)).fit(
            frame,
            duration_col="week",
            event_col="arrest",
            audit=audit,
        )
        survival = model.predict_survival(frame.iloc[:1], times=[10, 20, 30])
        hazard = model.predict_hazard(frame.iloc[:1], times=[10, 20, 30])
        term = model.term_structure(frame.iloc[:1], times=[10, 20, 30])

        assert model.diagnostics_.aft_family == family
        assert model.fit_statistics_["aic"] == pytest.approx(golden["aic"])
        assert survival["survival"].tolist() == pytest.approx(golden["survival"], abs=1e-12)
        assert hazard["hazard"].tolist() == pytest.approx(golden["hazard"], abs=1e-12)
        assert hazard["link"].tolist() == [family, family, family]
        assert hazard["linear_predictor_hazard"].tolist() == [None, None, None]
        assert term["pd_marginal"].tolist() == pytest.approx(golden["pd_marginal"], abs=1e-12)
        assert term["pd_cumulative"].tolist() == pytest.approx(
            golden["pd_cumulative"],
            abs=1e-12,
        )
        assert term["method"].tolist() == ["aft", "aft", "aft"]
        assert term["warning_codes"].tolist() == [(), (), ()]
        assert [event.payload["regla"] for event in audit.events] == [
            "survival_method",
            "survival_input_quality",
            "survival_aft",
        ]


def test_config_mapping_no_fiteado_y_aft_sin_familia() -> None:
    """Constructores por mapping y errores de método/no-fit quedan ruidosos."""
    frame = _rossi_frame()
    mapped_from_config = CoxPHSurvivalModel.from_config(
        _cfg("cox_ph", ph_p_value_threshold=0.05).model_dump()
    ).fit(frame, duration_col="week", event_col="arrest")
    mapped = CoxPHSurvivalModel(config=_cfg("cox_ph", ph_p_value_threshold=0.05).model_dump()).fit(
        frame,
        duration_col="week",
        event_col="arrest",
    )
    aft_from_config = AFTSurvivalModel.from_config(
        _cfg("aft", aft_family="weibull").model_dump()
    ).fit(frame, duration_col="week", event_col="arrest")
    aft_mapped = AFTSurvivalModel(config=_cfg("aft", aft_family="weibull").model_dump()).fit(
        frame,
        duration_col="week",
        event_col="arrest",
    )
    broken_aft = _cfg("aft", aft_family="weibull").model_copy(
        update={"cox_aft": CoxAftConfig(aft_family=None)}
    )

    assert mapped_from_config.config_.method == "cox_ph"
    assert mapped.config_.method == "cox_ph"
    assert aft_from_config.config_.cox_aft.aft_family == "weibull"
    assert aft_mapped.config_.cox_aft.aft_family == "weibull"
    with pytest.raises(SurvivalConfigError, match="method='cox_ph'"):
        CoxPHSurvivalModel.from_config(_cfg("kaplan_meier"))
    with pytest.raises(SurvivalConfigError, match="method='aft'"):
        AFTSurvivalModel.from_config(_cfg("cox_ph"))
    with pytest.raises(SurvivalConfigError, match="AFTSurvivalModel exige"):
        AFTSurvivalModel.from_config(broken_aft)
    with pytest.raises(SurvivalConfigError, match="method='cox_ph'"):
        CoxPHSurvivalModel(config=_cfg("aft", aft_family="weibull")).fit(
            frame,
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalConfigError, match="method='aft' exige"):
        AFTSurvivalModel(config=broken_aft).fit(frame, duration_col="week", event_col="arrest")
    with pytest.raises(SurvivalConfigError, match="aft_family"):
        AFTSurvivalModel().fit(frame, duration_col="week", event_col="arrest")
    with pytest.raises(NotFittedError, match="CoxPHSurvivalModel"):
        CoxPHSurvivalModel.from_config(_cfg("cox_ph")).predict_survival(frame, times=[1])
    with pytest.raises(NotFittedError, match="CoxPHSurvivalModel"):
        CoxPHSurvivalModel.from_config(_cfg("cox_ph")).proportional_hazard_diagnostics()
    with pytest.raises(NotFittedError, match="AFTSurvivalModel"):
        AFTSurvivalModel.from_config(_cfg("aft", aft_family="weibull")).predict_hazard(
            frame,
            times=[1],
        )


def test_input_pd_frame_partition_segment_y_no_mutacion() -> None:
    """Covariables desde pd_frame, partición Desarrollo y segmentos mantienen contrato."""
    frame = _rossi_frame().assign(segment="retail", loan_code=lambda data: data.index)
    pd_frame = pd.DataFrame(
        {
            "pd_raw": np.linspace(0.01, 0.40, len(frame)),
            "partition": ["desarrollo"] * 300 + ["holdout"] * (len(frame) - 300),
        },
        index=frame.index,
    )
    frame_original = frame.copy(deep=True)
    pd_original = pd_frame.copy(deep=True)
    cfg = _cfg(
        "cox_ph",
        covariate_cols=("fin", "age", "pd_raw"),
        segment_col="segment",
        id_col="loan_code",
        ph_p_value_threshold=0.05,
    )

    model = CoxPHSurvivalModel.from_config(cfg).fit(
        frame,
        duration_col="week",
        event_col="arrest",
        pd_frame=pd_frame,
    )
    term = model.term_structure(frame.iloc[:1], times=[10])
    fallback = CoxPHSurvivalModel.from_config(
        _cfg(
            "cox_ph",
            covariate_cols=("fin", "age", "pd_raw"),
            ph_p_value_threshold=0.05,
        )
    ).fit(
        frame.assign(partition="holdout"),
        duration_col="week",
        event_col="arrest",
        pd_frame=pd_frame.drop(columns=["partition"]),
    )

    assert model.n_fit_rows_ == 300
    assert term["segment"].tolist() == ["retail"]
    assert term["partition"].tolist() == ["desarrollo"]
    assert fallback.n_fit_rows_ == len(frame)
    assert_frame_equal(frame, frame_original)
    assert_frame_equal(pd_frame, pd_original)


def test_grillas_de_configuracion_para_aft() -> None:
    """AFT usa ``evaluation_times`` o ``horizon_periods`` cuando ``times`` viene vacío."""
    frame = _rossi_frame()
    evaluation_cfg = _cfg(
        "aft",
        aft_family="weibull",
        time_grid=SurvivalTimeGridConfig(evaluation_times=(10.0, 20.0)),
    )
    horizon_cfg = _cfg(
        "aft",
        aft_family="weibull",
        time_grid=SurvivalTimeGridConfig(horizon_periods=2),
    )

    evaluation = AFTSurvivalModel.from_config(evaluation_cfg).fit(
        frame,
        duration_col="week",
        event_col="arrest",
    )
    horizon = AFTSurvivalModel.from_config(horizon_cfg).fit(
        frame,
        duration_col="week",
        event_col="arrest",
    )

    assert evaluation.term_structure(frame.iloc[:1], times=[])["time_value"].tolist() == [
        10.0,
        20.0,
    ]
    assert horizon.term_structure(frame.iloc[:1], times=[])["time_value"].tolist() == [1.0, 2.0]


def test_errores_de_input_columnas_tipos_eventos_y_grilla() -> None:
    """Bordes de validación replican el contrato survival de SDD-18 §8."""
    frame = _rossi_frame()
    cfg = _cfg("cox_ph", ph_p_value_threshold=0.05)
    model = CoxPHSurvivalModel.from_config(cfg).fit(frame, duration_col="week", event_col="arrest")

    with pytest.raises(SurvivalInputError, match="Faltan columnas"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.drop(columns=["arrest"]),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="índice"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.rename(index={frame.index[1]: frame.index[0]}),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match=r"pandas\.DataFrame"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            "no-frame",  # type: ignore[arg-type]
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="booleana"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.assign(week=True),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="numérica"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.assign(week="1"),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="no positivos"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.assign(week=0.0),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="0/1"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.assign(arrest=True),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="no binario"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.assign(arrest=2),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="booleana"):
        CoxPHSurvivalModel.from_config(_cfg("cox_ph", covariate_cols=("fin",))).fit(
            frame.assign(fin=True),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="numérica"):
        CoxPHSurvivalModel.from_config(_cfg("cox_ph", covariate_cols=("fin",))).fit(
            frame.assign(fin="x"),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="no finitos"):
        CoxPHSurvivalModel.from_config(_cfg("cox_ph", covariate_cols=("fin",))).fit(
            frame.assign(fin=np.nan),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="segment"):
        CoxPHSurvivalModel.from_config(_cfg("cox_ph", segment_col="segment")).fit(
            frame.assign(segment=None),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="loan_code"):
        CoxPHSurvivalModel.from_config(_cfg("cox_ph", id_col="loan_code")).fit(
            frame,
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="partition"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.assign(partition=None),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalFitError, match="No hay filas"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.iloc[:0],
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalFitError, match="al menos un evento"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame.assign(arrest=0),
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalConfigError, match="covariable"):
        CoxPHSurvivalModel().fit(frame, duration_col="week", event_col="arrest")
    with pytest.raises(SurvivalTransformError, match="booleano"):
        model.term_structure(frame.iloc[:1], times=[True])
    with pytest.raises(SurvivalTransformError, match="positivos"):
        model.term_structure(frame.iloc[:1], times=[0])
    with pytest.raises(SurvivalTransformError, match="duplicados"):
        model.term_structure(frame.iloc[:1], times=[10, 10])
    with pytest.raises(SurvivalTransformError, match="fuera del soporte"):
        model.term_structure(frame.iloc[:1], times=[60])
    broken_features = CoxPHSurvivalModel.from_config(cfg).fit(
        frame,
        duration_col="week",
        event_col="arrest",
    )
    broken_features.prediction_features_ = broken_features.prediction_features_.drop(
        columns=["fin"]
    )
    with pytest.raises(SurvivalInputError, match="Faltan columnas"):
        broken_features.term_structure(frame.iloc[:1].drop(columns=["fin"]), times=[10])
    with pytest.raises(SurvivalInputError, match=r"pandas\.DataFrame"):
        model.predict_survival("no-frame", times=[10])  # type: ignore[arg-type]


def test_pd_frame_errores_y_features_almacenadas() -> None:
    """pd_frame ausente/incompleto falla y partición almacenada exige índice conocido."""
    frame = _rossi_frame()
    pd_frame = pd.DataFrame(
        {"pd_raw": np.linspace(0.01, 0.40, len(frame)), "partition": "desarrollo"},
        index=frame.index,
    )
    cfg = _cfg("cox_ph", covariate_cols=("fin", "age", "pd_raw"), ph_p_value_threshold=0.05)
    model = CoxPHSurvivalModel.from_config(cfg).fit(
        frame,
        duration_col="week",
        event_col="arrest",
        pd_frame=pd_frame,
    )

    with pytest.raises(SurvivalInputError, match="Faltan columnas"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame,
            duration_col="week",
            event_col="arrest",
            pd_frame=pd_frame.drop(columns=["pd_raw"]),
        )
    with pytest.raises(SurvivalInputError, match="no cubre"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame,
            duration_col="week",
            event_col="arrest",
            pd_frame=pd_frame.iloc[:-1],
        )
    with pytest.raises(SurvivalInputError, match="índice"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame,
            duration_col="week",
            event_col="arrest",
            pd_frame=pd_frame.rename(index={pd_frame.index[1]: pd_frame.index[0]}),
        )
    with pytest.raises(SurvivalInputError, match="Faltan columnas"):
        CoxPHSurvivalModel.from_config(cfg).fit(
            frame,
            duration_col="week",
            event_col="arrest",
        )
    with pytest.raises(SurvivalInputError, match="features almacenadas"):
        model.term_structure(frame.iloc[:1].rename(index={frame.index[0]: "nuevo"}), times=[10])


def test_helpers_defensivos_y_prediccion_con_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ramas defensivas de lifelines y transformaciones quedan cubiertas con fakes."""
    frame = _rossi_frame()
    model = AFTSurvivalModel.from_config(_cfg("aft", aft_family="weibull")).fit(
        frame,
        duration_col="week",
        event_col="arrest",
    )

    class WarningPredictor:
        """Fitter falso que advierte en predicción."""

        def predict_survival_function(self, *_args: Any, **_kwargs: Any) -> object:
            warnings.warn("predicción inestable", UserWarning, stacklevel=2)
            return pd.DataFrame()

    class ErrorPredictor:
        """Fitter falso que rechaza predicción."""

        def predict_survival_function(self, *_args: Any, **_kwargs: Any) -> object:
            raise ValueError("inválido")

    class WrongShapePredictor:
        """Fitter falso que retorna forma incompatible."""

        def predict_survival_function(self, *_args: Any, **_kwargs: Any) -> object:
            return pd.DataFrame([[0.9, 0.8]])

    class BadLinearPredictor:
        """Fitter falso que rechaza predictor lineal Cox."""

        def predict_log_partial_hazard(self, *_args: Any, **_kwargs: Any) -> object:
            raise ValueError("eta inválido")

    for fitter, match in (
        (WarningPredictor(), "warning"),
        (ErrorPredictor(), "rechazó"),
        (WrongShapePredictor(), "forma inesperada"),
    ):
        model.fitter_ = fitter
        with pytest.raises(SurvivalTransformError, match=match):
            ca_module._predict_survival_frame(model, frame.iloc[:1], (10.0,))

    cox = CoxPHSurvivalModel.from_config(_cfg("cox_ph", ph_p_value_threshold=0.05)).fit(
        frame,
        duration_col="week",
        event_col="arrest",
    )
    cox.fitter_ = BadLinearPredictor()
    with pytest.raises(SurvivalTransformError, match="predictor lineal"):
        ca_module._linear_predictors(cox, frame.iloc[:1])

    assert ca_module._interval_hazard(previous_survival=0.0, survival=0.0) == 0.0
    with pytest.raises(SurvivalTransformError, match="no puede aumentar"):
        ca_module._interval_hazard(previous_survival=0.8, survival=0.9)
    with pytest.raises(SurvivalTransformError, match=r"\[0, 1\]"):
        ca_module._unit_float(1.2, field_name="hazard")
    with pytest.raises(SurvivalTransformError, match="no negativo"):
        ca_module._non_negative_float(-0.1, field_name="pd_marginal")
    assert ca_module._clean_float(-0.0) == 0.0
    assert ca_module._n_parameters(SimpleNamespace(params_=None)) is None
    with pytest.raises(SurvivalConfigError, match="aft_family"):
        ca_module._new_fitter(
            ca_module._import_lifelines_components(),
            _cfg("cox_ph", ph_p_value_threshold=0.05),
            method="aft",
        )
    monkeypatch.setattr(ca_module, "_import_numpy", lambda: np)
    assert ca_module._prepare_prediction_frame(frame.iloc[:1], model=model, pd=pd).shape[0] == 1


def test_lifelines_fit_y_schoenfeld_warnings_traducidos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warnings/errores de lifelines se traducen a excepciones propias."""
    frame = pd.DataFrame(
        {"duration": [1.0, 2.0, 3.0], "event": [1, 0, 1], "x": [0.1, 0.2, 0.3]},
        index=["a", "b", "c"],
    )

    class FitWarningModel:
        """Fitter falso que advierte durante fit."""

        def fit(self, *_args: Any, **_kwargs: Any) -> None:
            warnings.warn("no converge", UserWarning, stacklevel=2)

    class FitValueErrorModel:
        """Fitter falso que rechaza fit."""

        def fit(self, *_args: Any, **_kwargs: Any) -> None:
            raise ValueError("diseño inválido")

    class FitOkModel:
        """Fitter falso mínimo para llegar a Schoenfeld."""

        _n_examples = 3
        log_likelihood_ = -1.0
        concordance_index_ = 0.5
        AIC_partial_ = 2.0
        params_ = pd.Series([1.0], index=["x"])

        def fit(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    def warning_ph_test(*_args: Any, **_kwargs: Any) -> object:
        warnings.warn("ph warning", UserWarning, stacklevel=2)
        return SimpleNamespace(summary=pd.DataFrame())

    for fitter_cls, match in ((FitWarningModel, "warning"), (FitValueErrorModel, "rechazó")):
        monkeypatch.setattr(
            ca_module,
            "_import_lifelines_components",
            lambda fitter_cls=fitter_cls: SimpleNamespace(
                cox_ph_fitter=fitter_cls,
                weibull_aft_fitter=fitter_cls,
                lognormal_aft_fitter=fitter_cls,
                loglogistic_aft_fitter=fitter_cls,
                proportional_hazard_test=lambda *_args, **_kwargs: SimpleNamespace(
                    summary=pd.DataFrame()
                ),
            ),
        )
        with pytest.raises(SurvivalFitError, match=match):
            CoxPHSurvivalModel.from_config(_small_cfg()).fit(
                frame,
                duration_col="duration",
                event_col="event",
            )

    monkeypatch.setattr(
        ca_module,
        "_import_lifelines_components",
        lambda: SimpleNamespace(
            cox_ph_fitter=FitOkModel,
            weibull_aft_fitter=FitOkModel,
            lognormal_aft_fitter=FitOkModel,
            loglogistic_aft_fitter=FitOkModel,
            proportional_hazard_test=warning_ph_test,
        ),
    )
    with pytest.raises(SurvivalFitError, match="Schoenfeld"):
        CoxPHSurvivalModel.from_config(_small_cfg()).fit(
            frame,
            duration_col="duration",
            event_col="event",
        )


def test_missing_dependency_import_guards_y_exports_livianos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """lifelines ausente cita ``[survival]`` y el paquete no carga motores pesados."""
    real_import = importlib.import_module

    def blocked_import(name: str) -> Any:
        if name.startswith("lifelines"):
            raise ModuleNotFoundError("No module named 'lifelines'", name="lifelines")
        return real_import(name)

    monkeypatch.setattr("nikodym.survival.cox_aft.importlib.import_module", blocked_import)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[survival\]"):
        ca_module._import_lifelines_components()
    monkeypatch.setattr(
        "nikodym.survival.cox_aft.importlib.import_module",
        lambda name: (
            (_ for _ in ()).throw(ModuleNotFoundError("No module named 'pandas'", name="pandas"))
            if name == "pandas"
            else real_import(name)
        ),
    )
    with pytest.raises(MissingDependencyError, match="pandas"):
        ca_module._import_pandas()
    monkeypatch.setattr(
        "nikodym.survival.cox_aft.importlib.import_module",
        lambda name: (
            (_ for _ in ()).throw(ModuleNotFoundError("No module named 'numpy'", name="numpy"))
            if name == "numpy"
            else real_import(name)
        ),
    )
    with pytest.raises(MissingDependencyError, match="numpy"):
        ca_module._import_numpy()

    code = (
        "import nikodym.survival, nikodym.survival.cox_aft, sys;"
        "blocked=[m for m in ('lifelines','sksurv') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'CoxPHSurvivalModel' in nikodym.survival.__all__;"
        "assert 'AFTSurvivalModel' in nikodym.survival.__all__;"
        "assert 'CoxPHSurvivalModel' in nikodym.survival.cox_aft.__all__;"
        "assert 'AFTSurvivalModel' in nikodym.survival.cox_aft.__all__"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    assert ExportedCoxPHSurvivalModel is CoxPHSurvivalModel
    assert ExportedAFTSurvivalModel is AFTSurvivalModel


def _cfg(
    method: str,
    *,
    aft_family: str | None = None,
    ph_p_value_threshold: float | None = None,
    covariate_cols: tuple[str, ...] = ("fin", "age", "prio"),
    segment_col: str | None = None,
    id_col: str | None = None,
    time_grid: SurvivalTimeGridConfig | None = None,
) -> SurvivalConfig:
    return SurvivalConfig(
        method=method,  # type: ignore[arg-type]
        input=SurvivalInputConfig(
            duration_col="week",
            event_col="arrest",
            id_col=id_col,
            segment_col=segment_col,
            covariate_cols=covariate_cols,
            pd_source="none",
        ),
        cox_aft=CoxAftConfig(
            ph_p_value_threshold=ph_p_value_threshold,
            aft_family=aft_family,  # type: ignore[arg-type]
        ),
        time_grid=SurvivalTimeGridConfig() if time_grid is None else time_grid,
        fail_on_falta_dato=False,
    )


def _small_cfg() -> SurvivalConfig:
    return SurvivalConfig(
        method="cox_ph",
        input=SurvivalInputConfig(
            duration_col="duration",
            event_col="event",
            covariate_cols=("x",),
            pd_source="none",
        ),
        cox_aft=CoxAftConfig(ph_p_value_threshold=0.05),
        fail_on_falta_dato=False,
    )


def _rossi_frame() -> pd.DataFrame:
    frame = load_rossi()[["week", "arrest", "fin", "age", "prio"]].copy(deep=True)
    frame.index = pd.Index([f"R{position:03d}" for position in range(len(frame))], name="row_id")
    return frame
