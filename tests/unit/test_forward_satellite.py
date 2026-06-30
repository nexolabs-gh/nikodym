"""Tests de ``SatelliteModel`` (SDD-20 B20.4)."""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import numpy as np
import pandas as pd
import pytest
from numpy.testing import assert_allclose
from pandas.testing import assert_frame_equal

import nikodym.forward.satellite as satellite_module
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
    ForwardInputError,
    ForwardPredictionError,
    PitConsistencyError,
    SatelliteModelError,
)
from nikodym.forward.satellite import SatelliteModel

_TERM_COLUMNS = [
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
    "pd_basis",
]
_FORWARD_COLUMNS = [
    "row_id",
    "segment",
    "partition",
    "source_model",
    "period",
    "time_value",
    "scenario",
    "scenario_weight",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "pd_marginal_base",
    "pd_cumulative_base",
    "lgd",
    "lgd_base",
    "pd_basis",
    "basis_state",
    "ttc_reversion_weight",
    "satellite_adjustment",
    "macro_model_id",
    "satellite_model_id",
    "method",
    "pd_source",
    "warning_codes",
]


class ScenarioStub:
    """Stub mínimo hasta B20.5."""

    scenario_weights_: ClassVar[dict[str, float]] = {
        "base": 0.60,
        "adverse": 0.30,
        "severe": 0.10,
    }

    def __init__(self) -> None:
        self.validated = False

    def validate_macro_projection(self, frame: pd.DataFrame) -> None:
        self.validated = True
        assert "macro_variable" in frame.columns


def _scenario(name: str, weight: float, shock: float = 0.0) -> ScenarioDefinitionConfig:
    shocks = {} if name == "base" else {"x": shock}
    return ScenarioDefinitionConfig(name=name, weight=weight, shocks=shocks)


def _cfg(
    *,
    mode: str = "fit",
    target_components: tuple[str, ...] = ("pd",),
    coefficient_table_path: str | None = None,
    min_history_periods: int = 5,
    require_pit_consistency: bool = True,
    pd_basis_assumption: str | None = "pit",
    segment_col: str | None = None,
) -> ForwardConfig:
    return ForwardConfig(
        input=ForwardInputConfig(
            macro_source=MacroSourceConfig(type="dataframe", variable_cols=("x",)),
            pd_basis_assumption=pd_basis_assumption,
            require_pit_consistency=require_pit_consistency,
        ),
        satellite=SatelliteConfig(
            mode=mode,  # type: ignore[arg-type]
            factor_cols=("x",),
            segment_col=segment_col,
            target_components=target_components,  # type: ignore[arg-type]
            coefficient_table_path=coefficient_table_path,
            min_history_periods=min_history_periods,
        ),
        macro=MacroModelConfig(horizon_periods=2, ljung_box_lags=(1,)),
        scenarios=ScenarioConfig(
            scenarios=(
                _scenario("base", 0.60),
                _scenario("adverse", 0.30, 1.0),
                _scenario("severe", 0.10, 2.0),
            )
        ),
        ttc_reversion=TtcReversionConfig(reasonable_supportable_periods=2),
    )


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _logit(value: float) -> float:
    return math.log(value / (1.0 - value))


def _term_structure(
    hazards: list[float],
    *,
    include_hazard: bool = True,
    lgd: list[float | None] | None = None,
    pd_basis: str | None = "pit",
) -> pd.DataFrame:
    survival_prev = 1.0
    rows: list[dict[str, Any]] = []
    for period, hazard in enumerate(hazards, start=1):
        pd_marginal = survival_prev * hazard
        survival = survival_prev * (1.0 - hazard)
        pd_cumulative = 1.0 - survival
        rows.append(
            {
                "row_id": "id-1",
                "segment": "retail",
                "partition": "desarrollo",
                "period": period,
                "time_value": float(period),
                "hazard": hazard,
                "survival": survival,
                "pd_marginal": pd_marginal,
                "pd_cumulative": pd_cumulative,
                "method": "survival",
                "pd_source": "survival",
                "scenario": None,
                "warning_codes": (),
                "pd_basis": pd_basis,
            }
        )
        survival_prev = survival
    frame = pd.DataFrame(rows, columns=_TERM_COLUMNS)
    if not include_hazard:
        frame = frame.drop(columns=["hazard"])
    if lgd is not None:
        frame["lgd"] = lgd
    return frame


def _macro_history(values: list[float] | None = None) -> pd.DataFrame:
    x_values = [-2.0, -1.0, 0.0, 1.0, 2.0] if values is None else values
    return pd.DataFrame({"period": range(1, len(x_values) + 1), "x": x_values})


def _macro_projection(
    *,
    periods: tuple[int, ...] = (1, 2),
    adverse_delta: dict[int, float] | None = None,
    severe_delta: dict[int, float] | None = None,
) -> pd.DataFrame:
    adverse = adverse_delta or {period: 1.0 for period in periods}
    severe = severe_delta or {period: 2.0 for period in periods}
    weights = {"base": 0.60, "adverse": 0.30, "severe": 0.10}
    rows: list[dict[str, Any]] = []
    for scenario in ("base", "adverse", "severe"):
        for period in periods:
            projected = 0.0
            if scenario == "adverse":
                projected = adverse[period]
            elif scenario == "severe":
                projected = severe[period]
            rows.append(
                {
                    "scenario": scenario,
                    "scenario_weight": weights[scenario],
                    "period": period,
                    "time_value": float(period),
                    "macro_variable": "x",
                    "projected_value": projected,
                    "model_value": 0.0,
                    "shock_value": projected,
                    "method": "ARIMA",
                    "model_id": "macro:arima:x",
                    "is_reasonable_supportable": True,
                    "warning_codes": (),
                }
            )
    return pd.DataFrame(rows)


def _fixed_table(path: Path, coefficient: float = 0.5) -> Path:
    pd.DataFrame(
        {
            "target_component": ["pd"],
            "factor_col": ["x"],
            "coefficient": [coefficient],
            "sign": ["positive" if coefficient > 0.0 else "zero"],
        }
    ).to_csv(path, index=False)
    return path


def _fitted_model() -> SatelliteModel:
    base_logit = _logit(0.02)
    hazards = [_sigmoid(base_logit + 0.5 * value) for value in [-2.0, -1.0, 0.0, 1.0, 2.0]]
    return SatelliteModel.from_config(_cfg()).fit(_term_structure(hazards), _macro_history())


def test_golden_satellite_logit_statsmodels_real_auditoria_y_no_mutacion() -> None:
    base_logit = _logit(0.02)
    hazards = [_sigmoid(base_logit + 0.5 * value) for value in [-2.0, -1.0, 0.0, 1.0, 2.0]]
    historical_term = _term_structure(hazards)
    macro_history = _macro_history()
    term_snapshot = historical_term.copy(deep=True)
    macro_snapshot = macro_history.copy(deep=True)
    audit = InMemoryAuditSink()

    model = SatelliteModel.from_config(_cfg()).fit(historical_term, macro_history, audit=audit)
    scenarios = ScenarioStub()
    projected = model.predict(
        _term_structure([0.02]),
        _macro_projection(periods=(1,), adverse_delta={1: 1.0}, severe_delta={1: 2.0}),
        scenarios=scenarios,
    )

    beta = model.coefficients_["pd"]["__all__"]["factors"]["x"]
    assert beta == pytest.approx(0.5, abs=1e-10)
    assert model.coefficients_["pd"]["__all__"]["alpha"] == 0.0
    assert model.reference_macro_ == {"x": 0.0}
    assert model.fit_statistics_["engine"] == "statsmodels.OLS"
    assert model.diagnostics_.coefficients["pd"]["__all__"]["factors"]["x"] == pytest.approx(0.5)
    assert [event.payload["regla"] for event in audit.events] == ["forward_satellite_model"]
    assert scenarios.validated is True
    assert_frame_equal(historical_term, term_snapshot)
    assert_frame_equal(macro_history, macro_snapshot)

    adverse = projected[projected["scenario"] == "adverse"].reset_index(drop=True)
    assert list(projected.columns) == _FORWARD_COLUMNS
    assert _logit(0.02) == pytest.approx(-3.8918202981)
    assert _logit(0.02) + beta == pytest.approx(-3.3918202981, abs=1e-10)
    assert adverse.loc[0, "hazard"] == pytest.approx(0.0325520809, abs=1e-10)
    assert adverse.loc[0, "pd_marginal"] == pytest.approx(0.0325520809, abs=1e-10)
    assert adverse.loc[0, "satellite_adjustment"] == pytest.approx(0.5, abs=1e-10)
    assert adverse.loc[0, "pd_basis"] == "pit"
    assert adverse.loc[0, "basis_state"] == "pit"
    assert adverse.loc[0, "ttc_reversion_weight"] == 1.0


def test_golden_recomposicion_lifetime() -> None:
    model = _fitted_model()

    projected = model.predict(
        _term_structure([0.10, 0.20]),
        _macro_projection(periods=(1, 2), adverse_delta={1: 0.0, 2: 0.0}),
        scenarios=ScenarioStub(),
    )

    base = projected[projected["scenario"] == "base"].sort_values("period").reset_index(drop=True)
    assert_allclose(base["hazard"].to_numpy(), np.array([0.10, 0.20]), atol=1e-12)
    assert_allclose(base["survival"].to_numpy(), np.array([0.90, 0.72]), atol=1e-12)
    assert_allclose(base["pd_marginal"].to_numpy(), np.array([0.10, 0.18]), atol=1e-12)
    assert base.loc[1, "pd_cumulative"] == pytest.approx(0.28, abs=1e-12)


def test_monotonicidad_separa_method_pd_source_y_scenario() -> None:
    model = _fitted_model()
    survival_curve = _term_structure([0.10, 0.20])
    survival_curve["source_model"] = "motor-comun"
    survival_curve["method"] = "survival"
    survival_curve["pd_source"] = "survival"
    markov_curve = _term_structure([0.05, 0.07])
    markov_curve["source_model"] = "motor-comun"
    markov_curve["method"] = "markov"
    markov_curve["pd_source"] = "markov"
    term = pd.concat([survival_curve, markov_curve], ignore_index=True)

    projected = model.predict(
        term,
        _macro_projection(periods=(1, 2), adverse_delta={1: 0.0, 2: 0.0}),
        scenarios=ScenarioStub(),
    )

    base_curves = projected[projected["scenario"] == "base"].groupby(
        ["source_model", "method", "pd_source"],
        sort=False,
    )["period"]
    assert base_curves.agg(tuple).to_dict() == {
        ("motor-comun", "markov", "markov"): (1, 2),
        ("motor-comun", "survival", "survival"): (1, 2),
    }

    broken = projected.copy(deep=True)
    broken_curve = (
        (broken["scenario"] == "base")
        & (broken["source_model"] == "motor-comun")
        & (broken["method"] == "survival")
        & (broken["pd_source"] == "survival")
    )
    broken.loc[broken_curve & (broken["period"] == 2), "pd_cumulative"] = 0.0
    with pytest.raises(ForwardPredictionError, match="Monotonicidad"):
        satellite_module._validate_forward_monotonicity(broken, cfg=model.config_)


def test_lgd_ausente_permitido_y_diagnosticado() -> None:
    cfg = _cfg(target_components=("pd", "lgd"))

    model = SatelliteModel.from_config(cfg).fit(_term_structure([0.02] * 5), _macro_history())
    projected = model.predict(
        _term_structure([0.02]),
        _macro_projection(periods=(1,)),
        scenarios=ScenarioStub(),
    )

    assert model.diagnostics_.warnings == ("lgd_base_ausente",)
    assert "lgd" not in model.coefficients_
    assert projected["lgd"].isna().all()
    assert projected["lgd_base"].isna().all()
    assert all("lgd_base_ausente" in codes for codes in projected["warning_codes"])


def test_coeficientes_fijos_csv_y_errores_de_signo(tmp_path: Path) -> None:
    path = _fixed_table(tmp_path / "coefficients.csv")
    cfg = _cfg(mode="fixed_coefficients", coefficient_table_path=str(path), min_history_periods=3)
    model = SatelliteModel.from_config(cfg).fit(
        _term_structure([0.02] * 3),
        _macro_history([0.0, 0.0, 0.0]),
    )

    projected = model.predict(
        _term_structure([0.02]),
        _macro_projection(periods=(1,)),
        scenarios=ScenarioStub(),
    )

    adverse = projected[projected["scenario"] == "adverse"].reset_index(drop=True)
    assert model.diagnostics_.mode == "fixed_coefficients"
    assert model.fit_statistics_["engine"] == "fixed_coefficients"
    assert adverse.loc[0, "hazard"] == pytest.approx(0.0325520809, abs=1e-10)

    bad_path = tmp_path / "bad.csv"
    pd.DataFrame({"target_component": ["pd"], "factor_col": ["x"], "coefficient": [0.5]}).to_csv(
        bad_path, index=False
    )
    bad_cfg = _cfg(
        mode="fixed_coefficients",
        coefficient_table_path=str(bad_path),
        min_history_periods=3,
    )
    with pytest.raises(SatelliteModelError, match="signo documentado"):
        SatelliteModel.from_config(bad_cfg).fit(
            _term_structure([0.02] * 3),
            _macro_history([0.0, 0.0, 0.0]),
        )

    sign_path = tmp_path / "sign.csv"
    pd.DataFrame(
        {
            "target_component": ["pd"],
            "factor_col": ["x"],
            "coefficient": [-0.5],
            "sign": ["positive"],
        }
    ).to_csv(sign_path, index=False)
    sign_cfg = _cfg(
        mode="fixed_coefficients",
        coefficient_table_path=str(sign_path),
        min_history_periods=3,
    )
    with pytest.raises(SatelliteModelError, match="positive"):
        SatelliteModel.from_config(sign_cfg).fit(
            _term_structure([0.02] * 3),
            _macro_history([0.0, 0.0, 0.0]),
        )


def test_hazard_ausente_se_deriva_y_casos_no_derivables(tmp_path: Path) -> None:
    cfg = _cfg(
        mode="fixed_coefficients",
        coefficient_table_path=str(_fixed_table(tmp_path / "coefficients.csv", coefficient=0.0)),
        min_history_periods=3,
    )
    model = SatelliteModel.from_config(cfg).fit(
        _term_structure([0.10, 0.20], include_hazard=False),
        _macro_history([0.0, 0.0, 0.0]),
    )

    projected = model.predict(
        _term_structure([0.10, 0.20], include_hazard=False),
        _macro_projection(periods=(1, 2)),
        scenarios=ScenarioStub(),
    )

    base = projected[projected["scenario"] == "base"].sort_values("period")
    assert base["hazard"].tolist() == pytest.approx([0.10, 0.20])
    assert all("hazard_derivado_desde_pd_marginal" in codes for codes in base["warning_codes"])

    impossible = _term_structure([0.50, 0.20], include_hazard=False)
    impossible.loc[0, "survival"] = 0.0
    with pytest.raises(ForwardInputError, match="no derivable"):
        model.predict(impossible, _macro_projection(periods=(1, 2)), scenarios=ScenarioStub())


def test_casos_borde_sdd8_y_no_fiteado(tmp_path: Path) -> None:
    model = _fitted_model()
    with pytest.raises(NotFittedError, match="no está fiteado"):
        SatelliteModel.from_config(_cfg()).predict(
            _term_structure([0.02]),
            _macro_projection(periods=(1,)),
            scenarios=ScenarioStub(),
        )

    missing_factor = _macro_projection(periods=(1,)).assign(macro_variable="z")
    with pytest.raises(SatelliteModelError, match="Factor satellite no proyectado"):
        model.predict(_term_structure([0.02]), missing_factor, scenarios=ScenarioStub())

    bad_hazard = _term_structure([0.02])
    bad_hazard.loc[0, "hazard"] = 1.0
    with pytest.raises(ForwardInputError, match=r"\(0, 1\)"):
        model.predict(bad_hazard, _macro_projection(periods=(1,)), scenarios=ScenarioStub())

    bad_lgd = _term_structure([0.02] * 5, lgd=[0.2, 0.3, 1.2, 0.4, 0.5])
    with pytest.raises(ForwardInputError, match=r"\[0, 1\]"):
        SatelliteModel.from_config(_cfg(target_components=("pd", "lgd"))).fit(
            bad_lgd,
            _macro_history(),
        )

    overflow_path = _fixed_table(tmp_path / "overflow.csv", coefficient=1000.0)
    overflow_cfg = _cfg(
        mode="fixed_coefficients",
        coefficient_table_path=str(overflow_path),
        min_history_periods=3,
    )
    overflow_model = SatelliteModel.from_config(overflow_cfg).fit(
        _term_structure([0.02] * 3),
        _macro_history([0.0, 0.0, 0.0]),
    )
    with pytest.raises(ForwardPredictionError, match="overflow logit"):
        overflow_model.predict(
            _term_structure([0.02]),
            _macro_projection(periods=(1,)),
            scenarios=ScenarioStub(),
        )

    unresolved_cfg = _cfg(require_pit_consistency=True, pd_basis_assumption="pit")
    unknown_basis = _term_structure([0.02] * 5, pd_basis="point")
    with pytest.raises(PitConsistencyError, match="pd_basis desconocida"):
        SatelliteModel.from_config(unresolved_cfg).fit(unknown_basis, _macro_history())


def test_validadores_privados_e_imports_perezosos(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(SatelliteModel.from_config(_cfg().model_dump()), SatelliteModel)  # type: ignore[arg-type]

    broken = pd.DataFrame(
        {
            "row_id": ["id-1", "id-1"],
            "segment": ["retail", "retail"],
            "partition": ["desarrollo", "desarrollo"],
            "source_model": ["survival", "survival"],
            "period": [1, 2],
            "scenario": ["base", "base"],
            "pd_cumulative": [0.20, 0.10],
        }
    )
    with pytest.raises(ForwardPredictionError, match="Monotonicidad"):
        satellite_module._validate_forward_monotonicity(broken, cfg=_cfg())
    duplicate_period = broken.copy(deep=True)
    duplicate_period["pd_cumulative"] = [0.10, 0.20]
    duplicate_period["period"] = [1, 1]
    with pytest.raises(ForwardPredictionError, match="period"):
        satellite_module._validate_forward_monotonicity(duplicate_period, cfg=_cfg())
    with pytest.raises(ForwardInputError, match="entero"):
        satellite_module._positive_int(1.5, field_name="period")
    with pytest.raises(ForwardPredictionError, match="Overflow"):
        satellite_module._sigmoid(math.inf)
    with pytest.raises(ForwardInputError, match="no finitos"):
        satellite_module._probability_array(
            [math.inf],
            field_name="hazard",
            open_interval=True,
            np=np,
        )

    code = (
        "import sys;"
        "baseline=set(sys.modules);"
        "import nikodym.forward.satellite;"
        "blocked=[m for m in ('pandas','scipy','statsmodels','pmdarima') "
        "if m in sys.modules and m not in baseline];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    original_import = satellite_module.importlib.import_module

    def fake_import(name: str) -> Any:
        if name in {"pandas", "numpy", "statsmodels.api"}:
            raise ModuleNotFoundError(name)
        return original_import(name)

    monkeypatch.setattr(satellite_module.importlib, "import_module", fake_import)
    with pytest.raises(MissingDependencyError, match="pandas"):
        satellite_module._import_pandas()
    with pytest.raises(MissingDependencyError, match="numpy"):
        satellite_module._import_numpy()
    with pytest.raises(MissingDependencyError, match=r"nikodym\[forecasting\]"):
        satellite_module._import_statsmodels_api()


def test_lgd_presente_segmento_y_source_model_explicito() -> None:
    x_values = [-2.0, -1.0, 0.0, 1.0, 2.0]
    pd_hazards = [_sigmoid(_logit(0.02) + 0.5 * value) for value in x_values]
    lgd_values = [_sigmoid(_logit(0.40) + 0.2 * value) for value in x_values]
    cfg = _cfg(target_components=("pd", "lgd"), segment_col="segment")

    model = SatelliteModel.from_config(cfg).fit(
        _term_structure(pd_hazards, lgd=lgd_values),
        _macro_history(),
    )
    term = _term_structure([0.02], lgd=[0.40])
    term["source_model"] = "survival_explicit"
    projected = model.predict(term, _macro_projection(periods=(1,)), scenarios=ScenarioStub())

    adverse = projected[projected["scenario"] == "adverse"].reset_index(drop=True)
    assert model.diagnostics_.segments == ("retail",)
    assert model.coefficients_["lgd"]["retail"]["factors"]["x"] == pytest.approx(0.2, abs=1e-10)
    assert adverse.loc[0, "lgd"] == pytest.approx(_sigmoid(_logit(0.40) + 0.2), abs=1e-10)
    assert adverse.loc[0, "source_model"] == "survival_explicit"


def test_validaciones_de_inputs_macro_y_term_structure() -> None:
    cfg = _cfg(min_history_periods=3)
    with pytest.raises(ForwardInputError, match=r"pandas\.DataFrame"):
        SatelliteModel.from_config(cfg).fit({"period": [1], "x": [1.0]}, _macro_history())
    with pytest.raises(ForwardInputError, match="macro históricas"):
        SatelliteModel.from_config(cfg).fit(
            _term_structure([0.02] * 3),
            pd.DataFrame({"period": [1, 2, 3]}),
        )
    with pytest.raises(ForwardInputError, match="duplicados"):
        SatelliteModel.from_config(cfg).fit(
            _term_structure([0.02] * 3),
            pd.DataFrame({"period": [1, 1, 2], "x": [0.0, 1.0, 2.0]}),
        )
    with pytest.raises(SatelliteModelError, match="historia insuficiente"):
        SatelliteModel.from_config(_cfg(min_history_periods=5)).fit(
            _term_structure([0.02] * 3),
            _macro_history([0.0, 1.0, 2.0]),
        )
    with pytest.raises(ForwardInputError, match="no finitos"):
        SatelliteModel.from_config(cfg).fit(
            _term_structure([0.02] * 3),
            pd.DataFrame({"period": [1, 2, 3], "x": [0.0, math.inf, 2.0]}),
        )
    with pytest.raises(SatelliteModelError, match="constante"):
        SatelliteModel.from_config(cfg).fit(
            _term_structure([0.02] * 3),
            _macro_history([1.0, 1.0, 1.0]),
        )
    with pytest.raises(ForwardInputError, match="term_structure"):
        SatelliteModel.from_config(cfg).fit(
            _term_structure([0.02] * 3).drop(columns=["method"]),
            _macro_history([0.0, 1.0, 2.0]),
        )
    with pytest.raises(ForwardInputError, match="segment_col"):
        SatelliteModel.from_config(_cfg(segment_col="pool", min_history_periods=3)).fit(
            _term_structure([0.02] * 3).drop(columns=["segment"]),
            _macro_history([0.0, 1.0, 2.0]),
        )
    with pytest.raises(ForwardInputError, match="no cubre"):
        SatelliteModel.from_config(cfg).fit(
            _term_structure([0.02, 0.03, 0.04]),
            pd.DataFrame({"period": [1, 2, 9], "x": [0.0, 1.0, 2.0]}),
        )


def test_pd_basis_lgd_base_y_hazard_derivado_ramas() -> None:
    pd_mod = pd
    np_mod = np
    cfg_warn = _cfg(require_pit_consistency=False, pd_basis_assumption=None)
    term = _term_structure([0.02]).drop(
        columns=["pd_basis", "row_id", "segment", "partition", "scenario"]
    )
    prepared = satellite_module._prepare_term_structure(term, cfg=cfg_warn, pd=pd_mod, np=np_mod)
    assert prepared.frame["pd_basis"].tolist() == ["pit"]
    assert "pd_basis_no_resuelta" in prepared.warnings
    assert {"row_id", "segment", "partition", "scenario", "source_model"} <= set(
        prepared.frame.columns
    )

    unknown = _term_structure([0.02], pd_basis="point")
    prepared_unknown = satellite_module._prepare_term_structure(
        unknown,
        cfg=cfg_warn,
        pd=pd_mod,
        np=np_mod,
    )
    assert prepared_unknown.frame["pd_basis"].tolist() == ["pit"]

    blank_basis = _term_structure([0.02], pd_basis="")
    prepared_blank = satellite_module._prepare_term_structure(
        blank_basis,
        cfg=_cfg(),
        pd=pd_mod,
        np=np_mod,
    )
    assert prepared_blank.frame["pd_basis"].tolist() == ["pit"]

    invalid_cfg = cfg_warn.model_copy(
        update={
            "input": cfg_warn.input.model_copy(update={"require_pit_consistency": True}),
        }
    )
    with pytest.raises(PitConsistencyError, match="pd_basis no resuelta"):
        satellite_module._prepare_term_structure(
            _term_structure([0.02]).drop(columns=["pd_basis"]),
            cfg=invalid_cfg,
            pd=pd_mod,
            np=np_mod,
        )

    empty_lgd = _term_structure([0.02], lgd=[None])
    empty_prepared = satellite_module._prepare_term_structure(
        empty_lgd,
        cfg=_cfg(),
        pd=pd_mod,
        np=np_mod,
    )
    assert empty_prepared.has_lgd_base is False
    lgd_base = _term_structure([0.02])
    lgd_base["lgd_base"] = [0.35]
    lgd_prepared = satellite_module._prepare_term_structure(
        lgd_base,
        cfg=_cfg(),
        pd=pd_mod,
        np=np_mod,
    )
    assert lgd_prepared.has_lgd_base is True

    duplicate_period = _term_structure([0.10, 0.20], include_hazard=False)
    duplicate_period.loc[1, "period"] = 1
    with pytest.raises(ForwardInputError, match="crecer estrictamente"):
        satellite_module._prepare_term_structure(duplicate_period, cfg=_cfg(), pd=pd_mod, np=np_mod)


def test_coeficientes_fijos_parquet_interceptos_y_validaciones(tmp_path: Path) -> None:
    parquet_path = tmp_path / "coefficients.parquet"
    pd.DataFrame(
        {
            "target_component": ["pd", "pd", "lgd"],
            "factor_col": ["alpha", "x", "x"],
            "coefficient": [0.0, 0.5, 0.2],
            "sign": ["zero", "positive", "positive"],
            "segment": ["retail", "retail", "retail"],
        }
    ).to_parquet(parquet_path)
    cfg = _cfg(
        mode="fixed_coefficients",
        coefficient_table_path=str(parquet_path),
        target_components=("pd", "lgd"),
        segment_col="segment",
        min_history_periods=3,
    )
    model = SatelliteModel.from_config(cfg).fit(
        _term_structure([0.02] * 3, lgd=[0.40, 0.40, 0.40]),
        _macro_history([0.0, 0.0, 0.0]),
    )
    assert model.coefficients_["pd"]["retail"]["alpha"] == 0.0

    with pytest.raises(SatelliteModelError, match="coefficient_table_path"):
        SatelliteModel.from_config(
            _cfg(mode="fixed_coefficients", coefficient_table_path=None, min_history_periods=3)
        ).fit(_term_structure([0.02] * 3), _macro_history([0.0, 0.0, 0.0]))

    unknown_factor = tmp_path / "unknown.csv"
    pd.DataFrame(
        {
            "target_component": ["pd"],
            "factor_col": ["z"],
            "coefficient": [0.5],
            "sign": ["positive"],
        }
    ).to_csv(unknown_factor, index=False)
    with pytest.raises(SatelliteModelError, match="factor desconocido"):
        SatelliteModel.from_config(
            _cfg(
                mode="fixed_coefficients",
                coefficient_table_path=str(unknown_factor),
                min_history_periods=3,
            )
        ).fit(_term_structure([0.02] * 3), _macro_history([0.0, 0.0, 0.0]))

    missing_factor = tmp_path / "missing_factor.csv"
    pd.DataFrame(
        {
            "target_component": ["lgd"],
            "factor_col": ["x"],
            "coefficient": [0.2],
            "sign": ["positive"],
        }
    ).to_csv(missing_factor, index=False)
    with pytest.raises(SatelliteModelError, match="target 'pd'"):
        SatelliteModel.from_config(
            _cfg(
                mode="fixed_coefficients",
                coefficient_table_path=str(missing_factor),
                min_history_periods=3,
            )
        ).fit(_term_structure([0.02] * 3), _macro_history([0.0, 0.0, 0.0]))

    pd_only = tmp_path / "pd_only.csv"
    pd.DataFrame(
        {
            "target_component": ["pd"],
            "factor_col": ["x"],
            "coefficient": [0.5],
            "sign": ["positive"],
        }
    ).to_csv(pd_only, index=False)
    pd_only_cfg = _cfg(
        mode="fixed_coefficients",
        coefficient_table_path=str(pd_only),
        target_components=("pd", "lgd"),
        min_history_periods=3,
    )
    pd_only_model = SatelliteModel.from_config(pd_only_cfg).fit(
        _term_structure([0.02] * 3),
        _macro_history([0.0, 0.0, 0.0]),
    )
    assert "lgd" not in pd_only_model.coefficients_

    incomplete = tmp_path / "incomplete.csv"
    pd.DataFrame(
        {
            "target_component": ["pd"],
            "factor_col": ["alpha"],
            "coefficient": [0.0],
            "sign": ["zero"],
        }
    ).to_csv(incomplete, index=False)
    with pytest.raises(SatelliteModelError, match="Faltan coeficientes"):
        SatelliteModel.from_config(
            _cfg(
                mode="fixed_coefficients",
                coefficient_table_path=str(incomplete),
                min_history_periods=3,
            )
        ).fit(_term_structure([0.02] * 3), _macro_history([0.0, 0.0, 0.0]))

    for sign, coefficient in (("negative", 0.5), ("zero", 0.1), ("documentado", 0.1)):
        with pytest.raises(SatelliteModelError):
            satellite_module._validate_documented_sign(coefficient, sign=sign)


def test_macro_projection_ramas_y_errores() -> None:
    cfg = _cfg()
    plain_scenarios = object()
    no_weight_frame = _macro_projection(periods=(1,)).drop(
        columns=["scenario_weight", "warning_codes", "model_id"]
    )
    prepared = satellite_module._prepare_macro_projection(
        no_weight_frame,
        scenarios=plain_scenarios,
        cfg=cfg,
        pd=pd,
        np=np,
    )
    assert prepared.scenario_weights == {"base": 0.60, "adverse": 0.30, "severe": 0.10}
    assert prepared.macro_model_ids[("base", 1)] == "macro:unknown"
    assert prepared.warning_codes == {}

    weights_object = SimpleNamespace(weights_={"base": 1.0})
    assert satellite_module._scenario_weights(
        no_weight_frame,
        scenarios=weights_object,
        cfg=cfg,
    ) == {"base": 1.0}
    frame_weights = _macro_projection(periods=(1,))
    assert (
        satellite_module._scenario_weights(frame_weights, scenarios=object(), cfg=cfg)["adverse"]
        == 0.30
    )
    partial_weights = frame_weights.copy(deep=True)
    partial_weights["scenario_weight"] = np.nan
    assert satellite_module._scenario_weights(partial_weights, scenarios=object(), cfg=cfg) == {
        "base": 0.60,
        "adverse": 0.30,
        "severe": 0.10,
    }

    with pytest.raises(SatelliteModelError, match="columnas requeridas"):
        satellite_module._prepare_macro_projection(
            _macro_projection(periods=(1,)).drop(columns=["projected_value"]),
            scenarios=plain_scenarios,
            cfg=cfg,
            pd=pd,
            np=np,
        )
    with pytest.raises(ForwardInputError, match="no finitos"):
        satellite_module._prepare_macro_projection(
            _macro_projection(periods=(1,)).assign(projected_value=math.inf),
            scenarios=plain_scenarios,
            cfg=cfg,
            pd=pd,
            np=np,
        )
    no_reference = _macro_projection(periods=(1,))
    no_reference = no_reference[no_reference["scenario"] != "base"]
    with pytest.raises(SatelliteModelError, match="referencia"):
        satellite_module._prepare_macro_projection(
            no_reference,
            scenarios=plain_scenarios,
            cfg=cfg,
            pd=pd,
            np=np,
        )
    duplicated_source = _macro_projection(periods=(1,))
    duplicated = pd.concat(
        [
            duplicated_source,
            duplicated_source[duplicated_source["scenario"] == "adverse"].iloc[[0]],
        ],
        ignore_index=True,
    )
    with pytest.raises(SatelliteModelError, match="duplicados"):
        satellite_module._prepare_macro_projection(
            duplicated,
            scenarios=plain_scenarios,
            cfg=cfg,
            pd=pd,
            np=np,
        )

    extra = pd.concat(
        [
            _macro_projection(periods=(1,)),
            pd.DataFrame(
                {
                    "scenario": ["base"],
                    "scenario_weight": [0.60],
                    "period": [1],
                    "time_value": [1.0],
                    "macro_variable": ["z"],
                    "projected_value": [99.0],
                    "model_value": [99.0],
                    "shock_value": [0.0],
                    "method": ["ARIMA"],
                    "model_id": ["macro:arima:z"],
                    "is_reasonable_supportable": [True],
                    "warning_codes": [()],
                }
            ),
        ],
        ignore_index=True,
    )
    assert ("base", 1, "z") not in satellite_module._macro_deltas(extra, cfg=cfg)


def test_ramas_defensivas_privadas(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg()
    pd_mod = pd
    np_mod = np
    one_row = _term_structure([0.02])
    with pytest.raises(SatelliteModelError, match="observaciones insuficientes"):
        satellite_module._fit_coefficients(
            one_row.assign(x=0.0),
            reference_macro={"x": 0.0},
            has_lgd_base=False,
            cfg=cfg,
            pd=pd_mod,
            np=np_mod,
        )

    class WarnOLS:
        def __init__(self, response: Any, design: pd.DataFrame) -> None:
            self.response = response
            self.design = design

        def fit(self) -> object:
            import warnings

            warnings.warn("colinealidad", UserWarning, stacklevel=2)
            return object()

    monkeypatch.setattr(
        satellite_module,
        "_import_statsmodels_api",
        lambda: SimpleNamespace(OLS=WarnOLS),
    )
    with pytest.raises(SatelliteModelError, match="warning"):
        satellite_module._fit_ols(pd.Series([0.0, 1.0]), pd.DataFrame({"x": [0.0, 1.0]}), np=np)

    class ValueOLS:
        def __init__(self, response: Any, design: pd.DataFrame) -> None:
            self.response = response
            self.design = design

        def fit(self) -> object:
            raise ValueError("boom")

    monkeypatch.setattr(
        satellite_module,
        "_import_statsmodels_api",
        lambda: SimpleNamespace(OLS=ValueOLS),
    )
    with pytest.raises(SatelliteModelError, match="rechazó"):
        satellite_module._fit_ols(pd.Series([0.0, 1.0]), pd.DataFrame({"x": [0.0, 1.0]}), np=np)

    class LinAlgOLS:
        def __init__(self, response: Any, design: pd.DataFrame) -> None:
            self.response = response
            self.design = design

        def fit(self) -> object:
            raise np.linalg.LinAlgError("singular")

    monkeypatch.setattr(
        satellite_module,
        "_import_statsmodels_api",
        lambda: SimpleNamespace(OLS=LinAlgOLS),
    )
    with pytest.raises(SatelliteModelError, match="resolver"):
        satellite_module._fit_ols(pd.Series([0.0, 1.0]), pd.DataFrame({"x": [0.0, 1.0]}), np=np)

    assert satellite_module._optional_stat_float("no-num") is None
    assert satellite_module._optional_stat_float(math.inf) is None
    assert satellite_module._optional_stat_float(-0.0) == 0.0
    assert satellite_module._segments_from_coefficients(
        {"pd": {"retail": {"alpha": 0.0, "factors": {"x": 0.5}}}}
    ) == ("retail",)
    assert satellite_module._segments_from_coefficients({"pd": 1}) == ()
    with pytest.raises(SatelliteModelError, match="Factor satellite no proyectado"):
        satellite_module._satellite_adjustment(
            SimpleNamespace(),
            scenario="base",
            period=1,
            prepared_macro=SimpleNamespace(deltas={}),
            coefficients={"pd": {"__all__": {"alpha": 0.0, "factors": {"x": 0.5}}}},
            cfg=cfg,
            component="pd",
        )
    with pytest.raises(SatelliteModelError, match="sin coeficientes"):
        satellite_module._coefficient_payload({}, component="pd", segment="retail")
    with pytest.raises(SatelliteModelError, match="segmento"):
        satellite_module._coefficient_payload(
            {"pd": {"otro": {"alpha": 0.0, "factors": {"x": 0.5}}}},
            component="pd",
            segment="retail",
        )
    assert (
        satellite_module._project_lgd(
            SimpleNamespace(lgd_base=0.4),
            scenario="base",
            period=1,
            prepared_macro=SimpleNamespace(deltas={}),
            coefficients={},
            cfg=cfg,
        )
        is None
    )
    assert (
        satellite_module._source_model(
            SimpleNamespace(source_model=None, pd_source="otro", method="manual")
        )
        == "manual"
    )
    assert (
        satellite_module._source_model(
            SimpleNamespace(source_model="", pd_source="otro", method="manual")
        )
        == "manual"
    )
    assert (
        satellite_module._segment_value(
            SimpleNamespace(pool="pyme"),
            cfg=_cfg(segment_col="pool"),
        )
        == "pyme"
    )
    assert satellite_module._none_if_missing(math.nan) is None
    assert satellite_module._warning_tuple(None) == ()
    assert satellite_module._warning_tuple("") == ()
    assert satellite_module._warning_tuple(7) == ("7",)
    with pytest.raises(ForwardInputError, match="no negativo"):
        satellite_module._non_negative_float(-0.1)
    with pytest.raises(ForwardInputError, match="booleano"):
        satellite_module._positive_int(True, field_name="period")
    with pytest.raises(ForwardInputError, match="mayor o igual"):
        satellite_module._positive_int(0, field_name="period")
    with pytest.raises(ForwardInputError, match="no finito"):
        satellite_module._clean_float(math.inf)

    def missing_version(_package: str) -> str:
        raise satellite_module.PackageNotFoundError

    monkeypatch.setattr(satellite_module, "version", missing_version)
    assert satellite_module._package_version("nope") == "no-disponible"
