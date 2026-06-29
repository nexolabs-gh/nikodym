"""Tests de discrete-time hazard survival: goldens, bordes y contrato liviano."""

from __future__ import annotations

import importlib
import math
import subprocess
import sys
import warnings
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

import nikodym.survival.discrete_hazard as dh_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import MissingDependencyError, NotFittedError
from nikodym.survival import DiscreteTimeHazardModel as ExportedDiscreteTimeHazardModel
from nikodym.survival.base import BaseSurvivalModel
from nikodym.survival.config import (
    DiscreteHazardConfig,
    SurvivalConfig,
    SurvivalInputConfig,
    SurvivalTimeGridConfig,
)
from nikodym.survival.discrete_hazard import DiscreteTimeHazardModel
from nikodym.survival.exceptions import (
    SurvivalConfigError,
    SurvivalFitError,
    SurvivalInputError,
    SurvivalTransformError,
)
from nikodym.survival.results import SurvivalDiagnostics

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


def test_hazard_chain_golden_manual() -> None:
    """Hazards fijos reproducen la cadena IFRS 9 de SDD-18 §3."""
    survival, pd_marginal, pd_cumulative = dh_module._hazard_chain((0.10, 0.20))

    assert survival == pytest.approx((0.90, 0.72), abs=1e-12)
    assert pd_marginal == pytest.approx((0.10, 0.18), abs=1e-12)
    assert pd_cumulative == pytest.approx((0.10, 0.28), abs=1e-12)


def test_glm_logit_saturado_recupera_hazard_empirico_y_term_structure() -> None:
    """El GLM real con dummies por período recupera ``d_t/n_t`` en el caso saturado."""
    frame = _golden_hazard_frame()
    original = frame.copy(deep=True)
    audit = InMemoryAuditSink()

    model = DiscreteTimeHazardModel.from_config(_cfg()).fit(
        frame,
        duration_col="duration",
        event_col="event",
        audit=audit,
    )
    hazard = model.predict_hazard(frame.iloc[:2], times=[1, 2])
    survival = model.predict_survival(frame.iloc[:1], times=[1, 2])
    term = model.term_structure(frame.iloc[:1], times=[1, 2])

    assert isinstance(model, BaseSurvivalModel)
    assert model.params_.loc["period_1"] == pytest.approx(math.log(0.10 / 0.90), abs=1e-6)
    assert model.params_.loc["period_2"] == pytest.approx(math.log(0.20 / 0.80), abs=1e-6)
    assert hazard["hazard"].tolist() == pytest.approx([0.10, 0.20, 0.10, 0.20], abs=1e-6)
    assert survival["survival"].tolist() == pytest.approx([0.90, 0.72], abs=1e-6)
    assert term["hazard"].tolist() == pytest.approx([0.10, 0.20], abs=1e-6)
    assert term["survival"].tolist() == pytest.approx([0.90, 0.72], abs=1e-6)
    assert term["pd_marginal"].tolist() == pytest.approx([0.10, 0.18], abs=1e-6)
    assert term["pd_cumulative"].tolist() == pytest.approx([0.10, 0.28], abs=1e-6)
    assert tuple(term.columns) == _TERM_COLUMNS
    assert tuple(hazard.columns) == _HAZARD_COLUMNS
    assert tuple(survival.columns) == _SURVIVAL_COLUMNS
    assert_frame_equal(frame, original)
    assert [event.payload["regla"] for event in audit.events] == [
        "survival_method",
        "survival_input_quality",
        "survival_pd_source",
        "survival_person_period",
    ]
    assert model.diagnostics_.link == "logit"
    assert model.card_.metric_sections["person_period"]["events_by_period"] == {"1": 10, "2": 18}


def test_constructor_mapping_config_default_y_partition_desde_pd_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cubre construcción por mapping, default sin config y partición almacenada desde PD."""
    frame = _golden_hazard_frame()
    payload = _cfg().model_dump()
    mapped = DiscreteTimeHazardModel(config=payload).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )
    mapped_from_config = DiscreteTimeHazardModel.from_config(payload).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )
    default = DiscreteTimeHazardModel().fit(frame, duration_col="duration", event_col="event")
    pd_frame = _pd_frame(frame.index, with_partition=True)
    with_pd_partition = DiscreteTimeHazardModel.from_config(
        _cfg(pd_source="model_raw", pd_role="covariate")
    ).fit(
        frame,
        duration_col="duration",
        event_col="event",
        pd_frame=pd_frame,
    )
    prediction_with_stored = with_pd_partition.term_structure(frame.iloc[:1], times=[1])
    explicit = frame.iloc[:1].assign(
        pd_raw=pd_frame.iloc[:1]["pd_raw"],
        partition=pd_frame.iloc[:1]["partition"],
    )
    prediction_with_explicit = with_pd_partition.term_structure(explicit, times=[1])

    def empty_fit_mask(_frame: pd.DataFrame, *, pd: Any, np: Any) -> Any:
        del pd
        return np.zeros(len(_frame.index), dtype=bool)

    monkeypatch.setattr(dh_module, "_fit_mask", empty_fit_mask)
    with pytest.raises(SurvivalFitError, match="No hay filas"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame,
            duration_col="duration",
            event_col="event",
        )

    assert mapped.config_.method == "discrete_hazard"
    assert mapped_from_config.config_.method == "discrete_hazard"
    assert default.config_.input.pd_source == "none"
    assert prediction_with_stored["partition"].tolist() == ["desarrollo"]
    assert prediction_with_explicit["partition"].tolist() == ["desarrollo"]


def test_person_period_evento_y_censura_sin_filas_posteriores() -> None:
    """La expansión corta en evento/censura y marca target sólo en el período de default."""
    pd_mod = dh_module._import_pandas()
    np_mod = dh_module._import_numpy()
    frame = pd.DataFrame(
        {"duration": [3, 2], "event": [1, 0], "x": [0.5, 0.7]},
        index=pd.Index(["evento", "censura"], name="loan_id"),
    )
    durations = dh_module._duration_period_array(frame["duration"], column="duration", np=np_mod)
    events = dh_module._event_array(frame["event"], column="event", np=np_mod)

    person_period = dh_module._expand_person_period_from_arrays(
        frame,
        durations=durations,
        events=events,
        cfg=_cfg(covariate_cols=("x",)),
        covariate_cols=("x",),
        pd=pd_mod,
    )

    assert person_period["row_id"].tolist() == [
        "evento",
        "evento",
        "evento",
        "censura",
        "censura",
    ]
    assert person_period["period"].tolist() == [1, 2, 3, 1, 2]
    assert person_period["__event_it"].tolist() == [0, 0, 1, 0, 0]
    assert "censura|3" not in person_period.index


def test_invariantes_term_structure_y_fallback_de_grilla() -> None:
    """La salida tidy respeta monotonía, acumulación y warning por grilla implícita."""
    frame = _golden_hazard_frame()
    model = DiscreteTimeHazardModel.from_config(_cfg()).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )
    term = model.term_structure(frame.iloc[:3], times=[])

    for _row_id, group in term.groupby("row_id", sort=False):
        assert group["survival"].is_monotonic_decreasing
        assert (group["pd_marginal"] >= 0.0).all()
        assert group["pd_cumulative"].tolist() == pytest.approx(
            (1.0 - group["survival"]).tolist(),
            abs=1e-12,
        )
        assert group["pd_marginal"].sum() == pytest.approx(group["pd_cumulative"].iloc[-1])
    assert term["warning_codes"].tolist() == [("FALTA-DATO-SUR-1",)] * 6


def test_cloglog_saturado_y_roles_pd_covariate_offset_segment() -> None:
    """Cubre link cloglog y las tres formas declaradas de incorporar PD F1."""
    frame = _golden_hazard_frame()
    cloglog = DiscreteTimeHazardModel.from_config(_cfg(link="cloglog")).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )
    covariate = DiscreteTimeHazardModel.from_config(
        _cfg(pd_role="covariate", pd_source="model_raw")
    ).fit(
        frame,
        duration_col="duration",
        event_col="event",
        pd_frame=_pd_frame(frame.index),
    )
    offset = DiscreteTimeHazardModel.from_config(_cfg(pd_role="offset", pd_source="model_raw")).fit(
        frame,
        duration_col="duration",
        event_col="event",
        pd_frame=_pd_frame(frame.index),
    )
    segment = DiscreteTimeHazardModel.from_config(
        _cfg(pd_role="segment", pd_source="model_raw")
    ).fit(
        frame,
        duration_col="duration",
        event_col="event",
        pd_frame=_pd_frame(frame.index, categorical_pd=True),
    )

    assert cloglog.term_structure(frame.iloc[:1], times=[1, 2])["hazard"].tolist() == pytest.approx(
        [0.10, 0.20],
        abs=1e-6,
    )
    assert "pd_raw" in covariate.design_columns_
    assert "pd_raw" not in offset.design_columns_
    assert "pd_segment[bajo]" in segment.design_columns_
    assert offset.term_structure(frame.iloc[:1], times=[1, 2])["hazard"].between(0.0, 1.0).all()


def test_no_leakage_con_partition_y_no_mutacion_de_frames() -> None:
    """Cambiar target fuera de Desarrollo no mueve coeficientes ni muta entradas."""
    frame = _partitioned_frame()
    pd_frame = _pd_frame(frame.index, with_partition=True)
    frame_original = frame.copy(deep=True)
    pd_original = pd_frame.copy(deep=True)
    mutated = frame.copy(deep=True)
    mutated.loc[mutated["partition"] != "desarrollo", "event"] = (
        1
        - mutated.loc[
            mutated["partition"] != "desarrollo",
            "event",
        ]
    )

    baseline = DiscreteTimeHazardModel.from_config(_cfg()).fit(
        frame,
        duration_col="duration",
        event_col="event",
        pd_frame=pd_frame,
    )
    shifted = DiscreteTimeHazardModel.from_config(_cfg()).fit(
        mutated,
        duration_col="duration",
        event_col="event",
        pd_frame=pd_frame,
    )

    assert_series_equal(baseline.params_, shifted.params_)
    assert_frame_equal(frame, frame_original)
    assert_frame_equal(pd_frame, pd_original)


def test_segment_col_id_col_partition_fallback_y_validaciones_texto() -> None:
    """Segmento/id declarados se validan y una partición sin Desarrollo usa todo el frame."""
    frame = _golden_hazard_frame().assign(segment="retail", loan_code=lambda data: data.index)
    model = DiscreteTimeHazardModel.from_config(
        _cfg(segment_col="segment", id_col="loan_code")
    ).fit(
        frame.assign(partition="holdout"),
        duration_col="duration",
        event_col="event",
    )
    term = model.term_structure(frame.iloc[:1], times=[1])

    assert term["segment"].tolist() == ["retail"]
    assert model.n_fit_rows_ == len(frame)
    with pytest.raises(SurvivalInputError, match="loan_code"):
        DiscreteTimeHazardModel.from_config(_cfg(id_col="loan_code")).fit(
            frame.drop(columns=["loan_code"]),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="segment"):
        DiscreteTimeHazardModel.from_config(_cfg(segment_col="segment")).fit(
            frame.assign(segment=None),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="partition"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame.assign(partition=None),
            duration_col="duration",
            event_col="event",
        )


def test_errores_fit_input_config_y_statsmodels() -> None:
    """Bordes ruidosos de config, columnas, duración/evento, covariables y solver."""
    frame = _golden_hazard_frame()
    with pytest.raises(SurvivalConfigError, match="method='discrete_hazard'"):
        DiscreteTimeHazardModel.from_config(_cfg(method="kaplan_meier"))
    with pytest.raises(SurvivalConfigError, match="method='discrete_hazard'"):
        DiscreteTimeHazardModel(config=_cfg(method="kaplan_meier")).fit(
            frame,
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(NotFittedError, match="no está fiteado"):
        DiscreteTimeHazardModel.from_config(_cfg()).predict_hazard(frame, times=[1])
    with pytest.raises(SurvivalInputError, match="Faltan columnas"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame.drop(columns=["event"]),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="índice"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame.rename(index={frame.index[1]: frame.index[0]}),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match=r"pandas\.DataFrame"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            "no-frame",  # type: ignore[arg-type]
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="booleana"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame.assign(duration=[True] * len(frame)),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="numérica"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame.assign(duration=["1"] * len(frame)),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="entera positiva"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame.assign(duration=[1.5] * len(frame)),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="0/1"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame.assign(event=[True] * len(frame)),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="no binario"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame.assign(event=[2] * len(frame)),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="cov"):
        DiscreteTimeHazardModel.from_config(_cfg(covariate_cols=("cov",))).fit(
            frame.assign(cov=[math.inf] * len(frame)),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="booleana"):
        DiscreteTimeHazardModel.from_config(_cfg(covariate_cols=("cov",))).fit(
            frame.assign(cov=[True] * len(frame)),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="numérica"):
        DiscreteTimeHazardModel.from_config(_cfg(covariate_cols=("cov",))).fit(
            frame.assign(cov=["x"] * len(frame)),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalFitError, match="al menos un evento"):
        DiscreteTimeHazardModel.from_config(_cfg()).fit(
            frame.assign(event=0),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalFitError, match="Eventos insuficientes"):
        DiscreteTimeHazardModel.from_config(_cfg(min_events_per_period=19)).fit(
            frame,
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalFitError, match="separación"):
        DiscreteTimeHazardModel.from_config(
            _cfg(include_period_dummies=False, covariate_cols=("x",))
        ).fit(
            pd.DataFrame(
                {"duration": [1, 1, 1, 1], "event": [0, 0, 1, 1], "x": [0, 0, 1, 1]},
                index=["a", "b", "c", "d"],
            ),
            duration_col="duration",
            event_col="event",
        )


def test_errores_pd_frame_prediccion_y_grilla() -> None:
    """Falla ante PD ambiguo, segmentos nuevos, hazards inválidos y extrapolación."""
    frame = _golden_hazard_frame()
    pd_frame = _pd_frame(frame.index)
    model = DiscreteTimeHazardModel.from_config(
        _cfg(pd_source="model_raw", pd_role="covariate")
    ).fit(
        frame,
        duration_col="duration",
        event_col="event",
        pd_frame=pd_frame,
    )

    with pytest.raises(SurvivalInputError, match="exige pd_frame"):
        DiscreteTimeHazardModel.from_config(_cfg(pd_source="model_raw", pd_role="covariate")).fit(
            frame,
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="Faltan columnas requeridas en pd_frame"):
        DiscreteTimeHazardModel.from_config(_cfg(pd_source="model_raw", pd_role="covariate")).fit(
            frame,
            duration_col="duration",
            event_col="event",
            pd_frame=pd_frame.drop(columns=["pd_raw"]),
        )
    with pytest.raises(SurvivalInputError, match="no cubre"):
        DiscreteTimeHazardModel.from_config(_cfg(pd_source="model_raw", pd_role="covariate")).fit(
            frame,
            duration_col="duration",
            event_col="event",
            pd_frame=pd_frame.iloc[:-1],
        )
    with pytest.raises(SurvivalInputError, match="índice"):
        DiscreteTimeHazardModel.from_config(_cfg(pd_source="model_raw", pd_role="covariate")).fit(
            frame,
            duration_col="duration",
            event_col="event",
            pd_frame=pd_frame.rename(index={pd_frame.index[1]: pd_frame.index[0]}),
        )
    with pytest.raises(SurvivalInputError, match="features PD almacenadas"):
        model.term_structure(
            pd.DataFrame({"duration": [1], "event": [0]}, index=["nuevo"]),
            times=[1],
        )
    with pytest.raises(SurvivalTransformError, match="booleano"):
        model.term_structure(frame.iloc[:1], times=[True])
    with pytest.raises(SurvivalTransformError, match="enteros positivos"):
        model.term_structure(frame.iloc[:1], times=[1.5])
    with pytest.raises(SurvivalTransformError, match="duplicados"):
        model.term_structure(frame.iloc[:1], times=[1, 1])
    with pytest.raises(SurvivalTransformError, match="fuera del soporte"):
        model.term_structure(frame.iloc[:1], times=[3])
    with pytest.raises(SurvivalTransformError, match=r"\[0, 1\]"):
        dh_module._hazard_chain((1.2,))
    with pytest.raises(SurvivalTransformError, match="no negativo"):
        dh_module._non_negative_float(-0.1, field_name="pd_marginal")


def test_segmento_pd_no_observado_y_extrapolacion_constante_declarada() -> None:
    """Segmentos PD nuevos fallan; extrapolación declarada funciona sin dummies de período."""
    frame = _golden_hazard_frame()
    pd_frame = _pd_frame(frame.index, categorical_pd=True)
    segment_model = DiscreteTimeHazardModel.from_config(
        _cfg(pd_role="segment", pd_source="model_raw")
    ).fit(
        frame,
        duration_col="duration",
        event_col="event",
        pd_frame=pd_frame,
    )
    segment_model.prediction_features_.loc[frame.index[0], "pd_raw"] = "nuevo"

    extrapolating = DiscreteTimeHazardModel.from_config(
        _cfg(
            include_period_dummies=False,
            time_grid=SurvivalTimeGridConfig(horizon_periods=3),
        )
    ).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )
    term = extrapolating.term_structure(frame.iloc[:1], times=[])

    with pytest.raises(SurvivalTransformError, match="Segmentos PD no observados"):
        segment_model.term_structure(frame.iloc[:1], times=[1])
    assert term["period"].tolist() == [1, 2, 3]
    assert term["hazard"].between(0.0, 1.0).all()


def test_helpers_defensivos_de_diseno_y_grilla() -> None:
    """Helpers privados cubren ramas de diseño vacío, duplicado y grilla explícita."""
    pd_mod = dh_module._import_pandas()
    frame = _golden_hazard_frame()
    model = DiscreteTimeHazardModel.from_config(
        _cfg(time_grid=SurvivalTimeGridConfig(evaluation_times=(1.0, 2.0)))
    ).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )
    duplicated = pd.DataFrame([[1.0, 2.0]])
    duplicated.columns = pd.Index(["x", "x"])

    term = model.term_structure(frame.iloc[:1], times=[])
    empty_rows, empty_index = dh_module._survival_rows(())

    with pytest.raises(SurvivalInputError, match="duplicadas"):
        dh_module._validate_design_matrix(duplicated)
    with pytest.raises(SurvivalFitError, match="columna de diseño"):
        dh_module._validate_design_matrix(pd.DataFrame(index=[0]))
    with pytest.raises(SurvivalInputError, match="Falta columna PD"):
        dh_module._validate_pd_role_columns(
            pd.DataFrame({"duration": [1]}),
            cfg=_cfg(pd_source="model_raw", pd_role="covariate"),
            np=np,
        )
    with pytest.raises(SurvivalInputError, match="partition"):
        dh_module._fit_mask(pd.DataFrame({"partition": [None]}), pd=pd_mod, np=np)

    assert term["period"].tolist() == [1, 2]
    assert term["warning_codes"].tolist() == [(), ()]
    assert (empty_rows, empty_index) == ([], [])
    assert dh_module._series_from_result([1.0], ("x",), pd_mod).to_dict() == {"x": 1.0}
    assert dh_module._inverse_logit(1.0) == pytest.approx(0.7310585786300049)
    dh_module._check_min_events({1: 2}, _cfg(min_events_per_period=1))
    assert (
        dh_module._n_iterations(
            SimpleNamespace(fit_history={"iteration": True}, mle_retvals={"iterations": 5})
        )
        == 5
    )
    assert dh_module._n_iterations(SimpleNamespace(mle_retvals=[])) is None


def test_missing_dependency_import_guards_y_np_integer_en_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """statsmodels ausente cita ``[scoring]`` y los imports públicos siguen livianos."""
    real_import = importlib.import_module

    def blocked_import(name: str) -> Any:
        if name.startswith("statsmodels"):
            raise ModuleNotFoundError("No module named 'statsmodels'", name="statsmodels")
        return real_import(name)

    monkeypatch.setattr("nikodym.survival.discrete_hazard.importlib.import_module", blocked_import)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        dh_module._import_statsmodels_components()
    monkeypatch.setattr(
        "nikodym.survival.discrete_hazard.importlib.import_module",
        lambda name: (
            (_ for _ in ()).throw(ModuleNotFoundError("No module named 'pandas'", name="pandas"))
            if name == "pandas"
            else real_import(name)
        ),
    )
    with pytest.raises(MissingDependencyError, match="pandas"):
        dh_module._import_pandas()
    monkeypatch.setattr(
        "nikodym.survival.discrete_hazard.importlib.import_module",
        lambda name: (
            (_ for _ in ()).throw(ModuleNotFoundError("No module named 'numpy'", name="numpy"))
            if name == "numpy"
            else real_import(name)
        ),
    )
    with pytest.raises(MissingDependencyError, match="numpy"):
        dh_module._import_numpy()

    diagnostics = SurvivalDiagnostics(
        method="discrete_hazard",
        n_rows=1,
        n_events=1,
        n_censored=0,
        max_observed_time=1,
        link="logit",
        fit_statistics={"n_obs": cast("Any", np.int64(7))},
    )
    assert diagnostics.fit_statistics["n_obs"] == 7
    assert isinstance(diagnostics.fit_statistics["n_obs"], int)
    assert not isinstance(diagnostics.fit_statistics["n_obs"], float)

    code = (
        "import nikodym.core, sys;"
        "assert 'nikodym.survival' not in sys.modules;"
        "import nikodym.survival;"
        "blocked=[m for m in ('statsmodels','lifelines','sksurv') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'DiscreteTimeHazardModel' in nikodym.survival.__all__"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert ExportedDiscreteTimeHazardModel is DiscreteTimeHazardModel
    assert "DiscreteTimeHazardModel" in dh_module.__all__


def test_helpers_de_solver_y_numericos_con_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ramas defensivas del wrapper GLM quedan traducidas a errores propios."""
    frame = pd.DataFrame({"x": [1.0, 1.0], "__event_it": [0, 1]})
    exog = pd.DataFrame({"const": [1.0, 1.0]})
    cfg = _cfg(include_period_dummies=False)

    class FakeWarning(Warning):
        """Warning falso para probar traducción local."""

    class FakePerfectError(Exception):
        """Error falso de separación perfecta."""

    class WarningModel:
        """Modelo falso que emite warning durante fit."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def fit(self, **_kwargs: Any) -> object:
            warnings.warn("no converge", FakeWarning, stacklevel=2)
            return SimpleNamespace(converged=True)

    class LinAlgModel:
        """Modelo falso que levanta error lineal."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def fit(self, **_kwargs: Any) -> object:
            raise np.linalg.LinAlgError("singular")

    class ValueErrorModel:
        """Modelo falso que rechaza diseño."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def fit(self, **_kwargs: Any) -> object:
            raise ValueError("inválido")

    class NonConvergedModel:
        """Modelo falso que retorna ``converged=False``."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def fit(self, **_kwargs: Any) -> object:
            return SimpleNamespace(converged=False)

    for model_cls, match in (
        (WarningModel, "separación"),
        (LinAlgModel, "invertir"),
        (ValueErrorModel, "rechazó"),
        (NonConvergedModel, "no convergió"),
    ):
        monkeypatch.setattr(
            dh_module,
            "_import_statsmodels_components",
            lambda model_cls=model_cls: SimpleNamespace(
                glm=model_cls,
                binomial=lambda link: object(),
                logit=lambda: object(),
                cloglog=lambda: object(),
                perfect_warning=FakeWarning,
                convergence_warning=FakeWarning,
                perfect_error=FakePerfectError,
            ),
        )
        with pytest.raises(SurvivalFitError, match=match):
            dh_module._fit_glm(
                target=frame["__event_it"],
                exog=exog,
                offset=None,
                cfg=cfg,
                np=np,
            )

    assert dh_module._converged(SimpleNamespace(mle_retvals={"converged": False})) is False
    assert dh_module._converged(SimpleNamespace()) is True
    assert dh_module._n_iterations(SimpleNamespace(fit_history={"iteration": 3})) == 3
    assert dh_module._n_iterations(SimpleNamespace(mle_retvals={"nit": 4})) == 4
    assert dh_module._n_iterations(SimpleNamespace(mle_retvals={"iterations": "x"})) is None
    assert dh_module._inverse_logit(-1000.0) == 0.0
    assert dh_module._inverse_cloglog(1000.0) == 1.0
    assert dh_module._inverse_cloglog(-1000.0) == 0.0
    assert dh_module._clean_float(-0.0) == 0.0


def _cfg(
    *,
    method: str = "discrete_hazard",
    link: str = "logit",
    pd_source: str = "none",
    pd_role: str = "none",
    include_period_dummies: bool = True,
    covariate_cols: tuple[str, ...] = (),
    min_events_per_period: int | None = None,
    time_grid: SurvivalTimeGridConfig | None = None,
    segment_col: str | None = None,
    id_col: str | None = None,
) -> SurvivalConfig:
    return SurvivalConfig(
        method=method,  # type: ignore[arg-type]
        input=SurvivalInputConfig(
            duration_col="duration",
            event_col="event",
            id_col=id_col,
            segment_col=segment_col,
            pd_source=pd_source,  # type: ignore[arg-type]
            covariate_cols=covariate_cols,
        ),
        time_grid=SurvivalTimeGridConfig() if time_grid is None else time_grid,
        discrete_hazard=DiscreteHazardConfig(
            link=link,  # type: ignore[arg-type]
            include_period_dummies=include_period_dummies,
            pd_role=pd_role,  # type: ignore[arg-type]
            min_events_per_period=min_events_per_period,
        ),
        fail_on_falta_dato=False,
    )


def _golden_hazard_frame() -> pd.DataFrame:
    rows: list[dict[str, int]] = []
    index: list[str] = []
    for position in range(100):
        index.append(f"L{position:03d}")
        if position < 10:
            rows.append({"duration": 1, "event": 1})
        elif position < 28:
            rows.append({"duration": 2, "event": 1})
        else:
            rows.append({"duration": 2, "event": 0})
    return pd.DataFrame(rows, index=pd.Index(index, name="loan_id"))


def _partitioned_frame() -> pd.DataFrame:
    dev = _golden_hazard_frame()
    dev["partition"] = "desarrollo"
    holdout = _golden_hazard_frame().iloc[:10].copy(deep=True)
    holdout.index = pd.Index([f"H{idx}" for idx in range(len(holdout))], name="loan_id")
    holdout["partition"] = "holdout"
    oot = _golden_hazard_frame().iloc[10:20].copy(deep=True)
    oot.index = pd.Index([f"O{idx}" for idx in range(len(oot))], name="loan_id")
    oot["partition"] = "oot"
    return pd.concat([dev, holdout, oot])


def _pd_frame(
    index: pd.Index,
    *,
    categorical_pd: bool = False,
    with_partition: bool = False,
) -> pd.DataFrame:
    if categorical_pd:
        pd_raw: list[float | str] = [
            "bajo" if position % 2 == 0 else "alto" for position in range(len(index))
        ]
    else:
        pd_raw = [0.01 + 0.001 * (position % 5) for position in range(len(index))]
    frame = pd.DataFrame(
        {
            "pd_raw": pd_raw,
            "linear_predictor": [-4.0 + 0.01 * (position % 7) for position in range(len(index))],
        },
        index=index.copy(),
    )
    if with_partition:
        frame["partition"] = [
            "desarrollo" if str(label).startswith("L") else "holdout" for label in index
        ]
    return frame
