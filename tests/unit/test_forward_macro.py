"""Tests de ``MacroProjectionModel`` (SDD-20 B20.3)."""

from __future__ import annotations

import math
import subprocess
import sys
import warnings
from typing import Any

import numpy as np
import pandas as pd
import pytest
from numpy.testing import assert_allclose
from pandas.testing import assert_frame_equal

import nikodym.forward.macro as macro_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import MissingDependencyError, NotFittedError
from nikodym.forward.config import (
    ForwardConfig,
    ForwardInputConfig,
    MacroModelConfig,
    MacroSourceConfig,
    SatelliteConfig,
    ScenarioConfig,
    ScenarioDefinitionConfig,
    TtcReversionConfig,
)
from nikodym.forward.exceptions import (
    ForwardConfigError,
    ForwardFitError,
    ForwardInputError,
    MacroProjectionError,
)
from nikodym.forward.macro import MacroProjectionModel

_MACRO_COLUMNS = [
    "scenario",
    "scenario_weight",
    "period",
    "time_value",
    "macro_variable",
    "projected_value",
    "model_value",
    "shock_value",
    "method",
    "model_id",
    "is_reasonable_supportable",
    "warning_codes",
]


def _scenario(name: str, weight: float, **overrides: object) -> ScenarioDefinitionConfig:
    data: dict[str, object] = {"name": name, "weight": weight}
    data.update(overrides)
    return ScenarioDefinitionConfig.model_validate(data)


def _scenarios(*, variables: tuple[str, ...] = ("y",)) -> ScenarioConfig:
    return ScenarioConfig(
        scenarios=(
            _scenario("base", 0.60),
            _scenario("adverse", 0.30, shocks={variable: 0.10 for variable in variables}),
            _scenario("severe", 0.10, shocks={variable: 0.20 for variable in variables}),
        )
    )


def _cfg(
    *,
    variables: tuple[str, ...] = ("y",),
    exogenous: tuple[str, ...] = (),
    macro: MacroModelConfig | None = None,
    min_history_periods: int = 12,
    ttc_reversion: TtcReversionConfig | None = None,
) -> ForwardConfig:
    return ForwardConfig(
        input=ForwardInputConfig(
            macro_source=MacroSourceConfig(
                type="dataframe",
                variable_cols=variables,
                exogenous_cols=exogenous,
            ),
            pd_basis_assumption="pit",
        ),
        satellite=SatelliteConfig(
            factor_cols=(variables[0],),
            min_history_periods=min_history_periods,
        ),
        macro=macro or MacroModelConfig(arima_order=(1, 0, 0), ljung_box_lags=(1, 2, 3)),
        scenarios=_scenarios(variables=variables),
        ttc_reversion=ttc_reversion or TtcReversionConfig(reasonable_supportable_periods=2),
    )


def _ar1_golden_frame() -> pd.DataFrame:
    rng = np.random.default_rng(1523)
    values = [2.0]
    for _ in range(1, 19):
        values.append(1.0 + 0.5 * values[-1] + float(rng.normal(0.0, 0.5)))
    values.append(4.0)
    return pd.DataFrame({"period": range(1, len(values) + 1), "y": values})


def _two_variable_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period": range(1, 15),
            "y": [float(i) for i in range(1, 15)],
            "z": [float(30 - i) for i in range(1, 15)],
        }
    )


def test_arima_golden_outputs_tidy_auditoria_y_no_mutacion() -> None:
    frame = _ar1_golden_frame()
    original = frame.copy(deep=True)
    audit = InMemoryAuditSink()

    model = MacroProjectionModel.from_config(_cfg()).fit(frame, audit=audit)
    projection = model.predict(horizon=3)
    base = projection[projection["scenario"] == "base"].reset_index(drop=True)

    assert tuple(model.macro_variables_) == ("y",)
    assert model.frequency_ is None
    assert model.time_index_[0] == 1
    assert model.time_index_[-1] == 20
    assert model.dependency_versions_["statsmodels"] != "no-disponible"
    assert model.diagnostics_.method == "arima"
    assert model.diagnostics_.macro_variables == ("y",)
    assert model.diagnostics_.input_rows == 20
    assert model.diagnostics_.input_gaps == 0
    assert model.diagnostics_.input_missing == 0
    assert len(model.diagnostics_.macro_data_hash or "") == 64
    assert model.diagnostics_.ljung_box_lags == (1, 2, 3)
    assert set(model.diagnostics_.ljung_box_p_values["y"]) == {"1", "2", "3"}
    assert all(
        math.isfinite(value) for value in model.diagnostics_.ljung_box_p_values["y"].values()
    )
    assert model.residual_diagnostics() == model.diagnostics_
    assert [event.payload["regla"] for event in audit.events] == ["forward_macro_model"]
    assert_frame_equal(frame, original)

    assert list(projection.columns) == _MACRO_COLUMNS
    assert len(projection) == 9
    assert_allclose(base["model_value"].to_numpy(), np.array([3.0, 2.5, 2.25]), atol=0.004)
    assert_allclose(base["projected_value"].to_numpy(), base["model_value"].to_numpy(), atol=0.0)
    assert base["time_value"].tolist() == [21.0, 22.0, 23.0]
    assert base["method"].tolist() == ["ARIMA", "ARIMA", "ARIMA"]
    assert base["model_id"].tolist() == ["macro:arima:y", "macro:arima:y", "macro:arima:y"]
    assert base["is_reasonable_supportable"].tolist() == [True, True, False]
    assert base["warning_codes"].tolist() == [(), (), ()]

    adverse = projection[projection["scenario"] == "adverse"].reset_index(drop=True)
    assert_allclose(adverse["projected_value"] - adverse["model_value"], np.full(3, 0.10))


def test_predict_sin_horizon_y_no_fiteado_fallan_controlado() -> None:
    model = MacroProjectionModel.from_config(_cfg())
    with pytest.raises(NotFittedError, match="no está fiteado"):
        model.predict(horizon=1)
    with pytest.raises(NotFittedError, match="no está fiteado"):
        model.residual_diagnostics()

    fitted = model.fit(_ar1_golden_frame())
    with pytest.raises(MacroProjectionError, match="horizon explícito"):
        fitted.predict()
    for horizon in (0, -1, True):
        with pytest.raises(MacroProjectionError, match="entero positivo"):
            fitted.predict(horizon=horizon)


def test_ljung_box_publica_pvalues_y_falla_si_config_lo_exige() -> None:
    values = [0.0]
    for index in range(1, 60):
        values.append(0.90 * values[-1] + (1.0 if index % 7 == 0 else 0.10))
    frame = pd.DataFrame({"period": range(len(values)), "y": values})
    macro = MacroModelConfig(arima_order=(0, 0, 0), ljung_box_lags=(1, 2, 3))

    fitted = MacroProjectionModel.from_config(_cfg(macro=macro)).fit(frame)

    assert fitted.diagnostics_.ljung_box_action == "warn"
    assert fitted.diagnostics_.ljung_box_p_values["y"]["1"] < 0.05

    failing = MacroModelConfig(
        arima_order=(0, 0, 0),
        ljung_box_lags=(1, 2, 3),
        fail_on_ljung_box=True,
    )
    with pytest.raises(ForwardFitError, match="Ljung-Box"):
        MacroProjectionModel.from_config(_cfg(macro=failing)).fit(frame)


def test_input_errors_series_corta_constante_columnas_y_missing() -> None:
    cfg = _cfg()
    with pytest.raises(ForwardInputError, match=r"pandas\.DataFrame"):
        MacroProjectionModel.from_config(cfg).fit({"period": [1], "y": [1.0]})
    with pytest.raises(ForwardInputError, match="Faltan columnas"):
        MacroProjectionModel.from_config(cfg).fit(pd.DataFrame({"period": [1, 2, 3]}))
    with pytest.raises(ForwardInputError, match="duplicados"):
        MacroProjectionModel.from_config(cfg).fit(
            pd.DataFrame({"period": [1, 1, *list(range(2, 12))], "y": range(12)})
        )
    with pytest.raises(ForwardInputError, match="missing"):
        MacroProjectionModel.from_config(cfg).fit(
            pd.DataFrame({"period": range(12), "y": [1.0, np.nan, *range(2, 12)]})
        )
    with pytest.raises(ForwardInputError, match="no finitos"):
        MacroProjectionModel.from_config(cfg).fit(
            pd.DataFrame({"period": range(12), "y": [1.0, math.inf, *range(2, 12)]})
        )
    with pytest.raises(ForwardFitError, match="demasiado corta"):
        MacroProjectionModel.from_config(cfg).fit(pd.DataFrame({"period": [1, 2], "y": [1.0, 2.0]}))
    with pytest.raises(ForwardFitError, match="constante"):
        MacroProjectionModel.from_config(cfg).fit(pd.DataFrame({"period": range(12), "y": 1.0}))


def test_arimax_exige_exogenas_futuras_y_proyecta_con_frame_por_escenario() -> None:
    frame = pd.DataFrame(
        {
            "period": range(1, 21),
            "y": [1.0 + 0.2 * index for index in range(20)],
            "x": [float(index) for index in range(20)],
        }
    )
    macro = MacroModelConfig(kind="arimax", arima_order=(0, 0, 0), ljung_box_lags=(1, 2))
    model = MacroProjectionModel.from_config(
        _cfg(variables=("y",), exogenous=("x",), macro=macro)
    ).fit(frame)
    future = pd.DataFrame(
        {
            "scenario": ["base", "base", "base"],
            "period": [21, 22, 23],
            "x": [20.0, 21.0, 22.0],
        }
    )

    projected = model.predict(horizon=3, scenario_frame=future)

    assert projected[projected["scenario"] == "severe"]["shock_value"].tolist() == [
        0.20,
        0.20,
        0.20,
    ]
    assert projected["method"].unique().tolist() == ["ARIMAX"]
    with pytest.raises(MacroProjectionError, match="exógenas futuras"):
        model.predict(horizon=3)
    with pytest.raises(MacroProjectionError, match="Faltan exógenas"):
        model.predict(horizon=3, scenario_frame=pd.DataFrame({"period": [21, 22, 23]}))
    with pytest.raises(MacroProjectionError, match="suficientes"):
        model.predict(horizon=4, scenario_frame=future)
    with pytest.raises(MacroProjectionError, match="finitas"):
        model.predict(
            horizon=3,
            scenario_frame=pd.DataFrame(
                {
                    "scenario": ["base", "base", "base"],
                    "period": [21, 22, 23],
                    "x": [1.0, np.inf, 3.0],
                }
            ),
        )


def test_auto_arima_opt_in_con_fake_y_dependencia_faltante(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeAutoModel:
        order = (1, 0, 0)
        seasonal_order = (0, 0, 0, 0)

        def resid(self) -> np.ndarray[Any, Any]:
            return np.array([0.2, -0.1, 0.1, -0.2, 0.0, 0.1, -0.1, 0.2, -0.2, 0.1, 0.0, -0.1])

        def predict(self, *, n_periods: int, **kwargs: Any) -> np.ndarray[Any, Any]:
            assert kwargs["X"] is None
            return np.arange(1, n_periods + 1, dtype="float64")

    def fake_auto_arima(series: Any, **kwargs: Any) -> FakeAutoModel:
        calls.append({"series_len": len(series), **kwargs})
        warnings.warn("orden revisado", UserWarning, stacklevel=2)
        return FakeAutoModel()

    original_auto_import = macro_module._import_auto_arima
    monkeypatch.setattr(macro_module, "_import_auto_arima", lambda: fake_auto_arima)
    cfg = _cfg(macro=MacroModelConfig(kind="auto_arima", ljung_box_lags=(1,)))
    model = MacroProjectionModel.from_config(cfg).fit(_ar1_golden_frame())
    projected = model.predict(horizon=2)

    assert calls[0]["random"] is False
    assert calls[0]["random_state"] is None
    assert model.diagnostics_.method == "auto_arima"
    assert any("pmdarima:y:UserWarning" in warning for warning in model.diagnostics_.warnings)
    assert projected[projected["scenario"] == "base"]["model_value"].tolist() == [1.0, 2.0]
    assert projected[projected["scenario"] == "base"]["method"].tolist() == [
        "auto_arima",
        "auto_arima",
    ]

    original_import = macro_module.importlib.import_module

    def fake_import(name: str) -> Any:
        if name == "pmdarima":
            raise ModuleNotFoundError(name)
        return original_import(name)

    monkeypatch.setattr(macro_module, "_import_auto_arima", original_auto_import)
    monkeypatch.setattr(macro_module.importlib, "import_module", fake_import)
    with pytest.raises(MissingDependencyError, match=r"nikodym\[forecasting\]"):
        MacroProjectionModel.from_config(cfg).fit(_ar1_golden_frame())


def test_var_y_vecm_multivariados_con_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeVARResult:
        k_ar = 1
        resid = np.array([[0.1, -0.1], [0.2, -0.2], [0.1, -0.1], [0.0, 0.0]])

        def forecast(self, *, y: np.ndarray[Any, Any], steps: int) -> np.ndarray[Any, Any]:
            assert y.shape == (1, 2)
            return np.array([[10.0 + step, 20.0 + step] for step in range(1, steps + 1)])

    class FakeVAR:
        def __init__(self, values: pd.DataFrame) -> None:
            self.values = values

        def fit(self, *, maxlags: int, ic: Any, trend: str) -> FakeVARResult:
            assert maxlags == 1
            assert ic is None
            assert trend == "c"
            return FakeVARResult()

    monkeypatch.setattr(macro_module, "_import_var", lambda: FakeVAR)
    var_cfg = _cfg(
        variables=("y", "z"),
        macro=MacroModelConfig(kind="var", var_lags=1, ljung_box_lags=(1,)),
    )
    var_model = MacroProjectionModel.from_config(var_cfg).fit(_two_variable_frame())
    var_projection = var_model.predict(horizon=2)

    assert var_model.diagnostics_.orders_lags == {"var_lags": 1}
    base = var_projection[var_projection["scenario"] == "base"].reset_index(drop=True)
    assert base["macro_variable"].tolist() == ["y", "y", "z", "z"]
    assert base["model_value"].tolist() == [11.0, 12.0, 21.0, 22.0]
    assert base["method"].tolist() == ["VAR", "VAR", "VAR", "VAR"]

    class FakeVECMResult:
        resid = np.array([[0.1, -0.1], [0.2, -0.2], [0.1, -0.1], [0.0, 0.0]])

        def predict(self, *, steps: int) -> np.ndarray[Any, Any]:
            return np.array([[30.0 + step, 40.0 + step] for step in range(1, steps + 1)])

    class FakeVECM:
        def __init__(self, values: pd.DataFrame, *, k_ar_diff: int, coint_rank: int) -> None:
            assert values.columns.tolist() == ["y", "z"]
            assert k_ar_diff == 2
            assert coint_rank == 1

        def fit(self) -> FakeVECMResult:
            return FakeVECMResult()

    monkeypatch.setattr(macro_module, "_import_vecm", lambda: FakeVECM)
    vecm_cfg = _cfg(
        variables=("y", "z"),
        macro=MacroModelConfig(kind="vecm", var_lags=2, vecm_rank=1, ljung_box_lags=(1,)),
    )
    vecm_model = MacroProjectionModel.from_config(vecm_cfg).fit(_two_variable_frame())
    vecm_projection = vecm_model.predict(horizon=2)

    assert vecm_model.diagnostics_.orders_lags == {"k_ar_diff": 2, "vecm_rank": 1}
    assert vecm_projection[vecm_projection["scenario"] == "base"]["model_value"].tolist() == [
        31.0,
        32.0,
        41.0,
        42.0,
    ]
    missing_rank = _cfg(variables=("y", "z"), macro=MacroModelConfig(kind="vecm"))
    with pytest.raises(ForwardConfigError, match="FALTA-DATO-FWD"):
        MacroProjectionModel.from_config(missing_rank).fit(_two_variable_frame())


def test_helpers_temporales_y_numericos() -> None:
    assert isinstance(MacroProjectionModel(config=_cfg().model_dump()), MacroProjectionModel)
    assert isinstance(MacroProjectionModel.from_config(_cfg().model_dump()), MacroProjectionModel)

    periods = tuple(pd.period_range("2025Q1", periods=3, freq="Q"))
    assert macro_module._future_time_values(periods, horizon=2, frequency="Q", pd=pd) == (
        pd.Period("2025Q4", freq="Q-DEC"),
        pd.Period("2026Q1", freq="Q-DEC"),
    )
    dates = tuple(pd.date_range("2025-01-01", periods=3, freq="MS"))
    assert macro_module._infer_frequency(dates, pd=pd) == "MS"
    assert macro_module._future_time_values(dates, horizon=2, frequency="MS", pd=pd) == (
        pd.Timestamp("2025-04-01"),
        pd.Timestamp("2025-05-01"),
    )
    with pytest.raises(MacroProjectionError, match="frequency"):
        macro_module._future_time_values(dates, horizon=1, frequency=None, pd=pd)
    with pytest.raises(MacroProjectionError, match="vacío"):
        macro_module._future_time_values((), horizon=1, frequency=None, pd=pd)
    with pytest.raises(MacroProjectionError, match="Tipo temporal"):
        macro_module._future_time_values((object(),), horizon=1, frequency=None, pd=pd)
    assert macro_module._infer_frequency((1, 2), pd=pd) is None
    assert macro_module._infer_frequency(periods, pd=pd) == "Q-DEC"
    assert macro_module._infer_frequency(("a", "b", "c"), pd=pd) is None
    with pytest.raises(ForwardInputError, match="booleano"):
        macro_module._normalize_time_value(True)
    assert macro_module._normalize_time_value(None) is None
    assert macro_module._normalize_time_value(1) == 1
    assert macro_module._normalize_time_value(-0.0) == 0.0
    assert macro_module._normalize_time_value("3") == 3.0
    assert macro_module._normalize_time_value(object()).startswith("<object object")
    with pytest.raises(MacroProjectionError, match="no finito"):
        macro_module._clean_float(math.inf)
    with pytest.raises(ForwardFitError, match="p-value"):
        macro_module._unit_interval_float(1.1)
    assert macro_module._count_time_gaps((1, 2, 4, 5), np=np) == 1
    assert macro_module._count_time_gaps(("a", "b", "c"), np=np) == 0
    assert macro_module._count_time_gaps((1, 1, 1), np=np) == 0
    assert macro_module._numeric_time_step((1,)) == 1.0
    assert macro_module._numeric_time_step((1, 1)) == 1.0
    assert macro_module._time_range(()) is None
    assert macro_module._is_numeric_time(True) is False
    assert macro_module._is_numeric_time(object()) is False
    assert macro_module._dedupe(["a", "a", "b"]) == ("a", "b")


def test_helpers_defensivos_de_modelo_y_forecast(monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = macro_module._PreparedMacroFrame(
        frame=pd.DataFrame({"period": [1, 2], "y": [1.0, 2.0], "z": [2.0, 3.0]}),
        macro_variables=("y",),
        exogenous_variables=(),
        time_index=(1, 2),
        frequency=None,
        input_rows=2,
        input_gaps=0,
        input_missing=0,
        input_time_range=(1, 2),
        macro_data_hash="hash",
    )
    with pytest.raises(ForwardConfigError, match="var"):
        macro_module._validate_model_shape(
            prepared,
            cfg=_cfg(
                variables=("y", "z"),
                macro=MacroModelConfig(kind="var", var_lags=1),
            ),
        )
    with pytest.raises(ForwardConfigError, match="arimax"):
        macro_module._validate_model_shape(
            prepared,
            cfg=_cfg(variables=("y",), exogenous=("x",), macro=MacroModelConfig(kind="arimax")),
        )
    auto_cfg = _cfg(macro=MacroModelConfig(use_pmdarima_auto_order=True))
    multi_prepared = macro_module._PreparedMacroFrame(
        frame=prepared.frame,
        macro_variables=("y", "z"),
        exogenous_variables=(),
        time_index=(1, 2),
        frequency=None,
        input_rows=2,
        input_gaps=0,
        input_missing=0,
        input_time_range=(1, 2),
        macro_data_hash="hash",
    )
    with pytest.raises(ForwardConfigError, match="una variable"):
        macro_module._validate_model_shape(multi_prepared, cfg=auto_cfg)

    no_lag = macro_module._ljung_box_diagnostics(
        {"y": np.array([0.1])},
        cfg=_cfg(macro=MacroModelConfig(ljung_box_lags=(5,))),
    )
    assert no_lag["warnings"] == ("ljung_box_no_valid_lags:y",)

    arimax_macro = MacroModelConfig(kind="arimax", arima_order=(0, 0, 0), ljung_box_lags=(1,))
    arimax_cfg = _cfg(variables=("y",), exogenous=("x",), macro=arimax_macro)
    frame = pd.DataFrame(
        {
            "period": range(1, 13),
            "y": [float(index) for index in range(12)],
            "x": [float(index) for index in range(12)],
        }
    )
    arimax_model = MacroProjectionModel.from_config(arimax_cfg).fit(frame)
    with pytest.raises(MacroProjectionError, match="ARIMAX exige"):
        macro_module._forecast_univariate(arimax_model, horizon=1, future_exog=None, np=np)
    future = pd.DataFrame({"x": [12.0, 13.0]})
    assert macro_module._future_exogenous_values(
        future,
        scenario_name="base",
        horizon=2,
        cfg=arimax_cfg,
        pd=pd,
        np=np,
    ).shape == (2, 1)
    assert (
        macro_module._future_exogenous_values(
            future,
            scenario_name="base",
            horizon=2,
            cfg=_cfg(),
            pd=pd,
            np=np,
        )
        is None
    )

    with pytest.raises(MacroProjectionError, match="multivariado"):
        macro_module._matrix_forecast_state(
            np.ones((2, 1)),
            ("y", "z"),
            (),
            np=np,
        )
    assert macro_module._residual_matrix(
        pd.DataFrame({"y": [0.1], "z": [0.2]}),
        ("y", "z"),
        np=np,
    ).shape == (1, 2)
    with pytest.raises(ForwardFitError, match="residuos"):
        macro_module._residual_matrix(np.ones((2, 1)), ("y", "z"), np=np)
    assert macro_module._finite_array(0.0, field_name="x", np=np).tolist() == [0.0]
    with pytest.raises(ForwardFitError, match="no finitos"):
        macro_module._finite_array([math.nan], field_name="x", np=np)
    with pytest.raises(MacroProjectionError, match="largo inesperado"):
        macro_module._float_tuple([1.0], length=2, np=np)
    with pytest.raises(MacroProjectionError, match="no finitos"):
        macro_module._float_tuple([math.inf], length=1, np=np)

    class FakeStatsmodelsError(Exception):
        pass

    FakeStatsmodelsError.__module__ = "statsmodels.fake"

    def raise_statsmodels_error() -> None:
        raise FakeStatsmodelsError()

    def raise_value_error() -> None:
        raise ValueError("boom")

    with pytest.raises(ForwardFitError, match="Fallo controlado"):
        macro_module._capture_warnings(raise_statsmodels_error, source="x")
    with pytest.raises(ValueError, match="boom"):
        macro_module._capture_warnings(raise_value_error, source="x")

    class FakeModule:
        ARIMA = object()
        VAR = object()
        VECM = object()
        acorr_ljungbox = object()
        auto_arima = object()

    def fake_import(name: str) -> FakeModule:
        assert name in {
            "statsmodels.tsa.arima.model",
            "statsmodels.tsa.vector_ar.var_model",
            "statsmodels.tsa.vector_ar.vecm",
            "statsmodels.stats.diagnostic",
            "pmdarima",
        }
        return FakeModule()

    monkeypatch.setattr(macro_module.importlib, "import_module", fake_import)
    assert macro_module._import_statsmodels_arima() is FakeModule.ARIMA
    assert macro_module._import_var() is FakeModule.VAR
    assert macro_module._import_vecm() is FakeModule.VECM
    assert macro_module._import_ljung_box() is FakeModule.acorr_ljungbox
    assert macro_module._import_auto_arima() is FakeModule.auto_arima


def test_imports_perezosos_y_dependencias_faltantes(monkeypatch: pytest.MonkeyPatch) -> None:
    code = (
        "import sys;"
        "baseline=set(sys.modules);"
        "import nikodym.forward.results;"
        "import nikodym.forward.macro;"
        "blocked=[m for m in ('pandas','scipy','statsmodels','pmdarima') "
        "if m in sys.modules and m not in baseline];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    original_import = macro_module.importlib.import_module

    def fake_import(name: str) -> Any:
        blocked = {
            "pandas",
            "numpy",
            "statsmodels.tsa.arima.model",
            "statsmodels.tsa.vector_ar.var_model",
            "statsmodels.tsa.vector_ar.vecm",
            "statsmodels.stats.diagnostic",
            "pmdarima",
        }
        if name in blocked:
            raise ModuleNotFoundError(name)
        return original_import(name)

    monkeypatch.setattr(macro_module.importlib, "import_module", fake_import)
    with pytest.raises(MissingDependencyError, match="pandas"):
        macro_module._import_pandas()
    with pytest.raises(MissingDependencyError, match="numpy"):
        macro_module._import_numpy()
    with pytest.raises(MissingDependencyError, match=r"nikodym\[forecasting\]"):
        macro_module._import_statsmodels_arima()
    with pytest.raises(MissingDependencyError, match=r"nikodym\[forecasting\]"):
        macro_module._import_var()
    with pytest.raises(MissingDependencyError, match=r"nikodym\[forecasting\]"):
        macro_module._import_vecm()
    with pytest.raises(MissingDependencyError, match=r"nikodym\[forecasting\]"):
        macro_module._import_ljung_box()
    with pytest.raises(MissingDependencyError, match=r"nikodym\[forecasting\]"):
        macro_module._import_auto_arima()
