"""Tests de ``ScenarioWeighting`` (SDD-20 B20.5)."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.forward as forward_pkg
import nikodym.forward.scenarios as scenarios_module
from nikodym.core.exceptions import MissingDependencyError
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
    ForwardPredictionError,
    ForwardScenarioError,
)
from nikodym.forward.scenarios import ScenarioWeighting

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
_ANCHOR_COLUMNS = [
    "row_id",
    "segment",
    "partition",
    "source_model",
    "period",
    "time_value",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "method",
    "pd_source",
    "pd_basis",
]


def _scenario(name: str, weight: float, shock: float = 0.0) -> ScenarioDefinitionConfig:
    shocks = {} if name == "base" else {"x": shock}
    return ScenarioDefinitionConfig(name=name, weight=weight, shocks=shocks)


def _cfg(
    *,
    scenarios: ScenarioConfig | None = None,
    ttc_reversion: TtcReversionConfig | None = None,
    fail_on_falta_dato: bool = True,
) -> ForwardConfig:
    return ForwardConfig(
        input=ForwardInputConfig(
            macro_source=MacroSourceConfig(type="dataframe", variable_cols=("x",)),
            pd_basis_assumption="pit",
        ),
        satellite=SatelliteConfig(factor_cols=("x",), min_history_periods=3),
        macro=MacroModelConfig(horizon_periods=5, ljung_box_lags=(1,)),
        scenarios=scenarios
        or ScenarioConfig(
            scenarios=(
                _scenario("base", 0.60),
                _scenario("adverse", 0.30, 1.0),
                _scenario("severe", 0.10, 2.0),
            )
        ),
        ttc_reversion=ttc_reversion
        or TtcReversionConfig(reasonable_supportable_periods=2, reversion_periods=2),
        fail_on_falta_dato=fail_on_falta_dato,
    )


def _constructed_scenario(name: str, weight: float) -> ScenarioDefinitionConfig:
    return ScenarioDefinitionConfig.model_construct(
        name=name,
        weight=weight,
        macro_path_path=None,
        shocks={},
        description=None,
    )


def _cfg_construido(
    scenarios: tuple[ScenarioDefinitionConfig, ...],
    *,
    require_at_least_three: bool = True,
) -> ForwardConfig:
    cfg = _cfg()
    scenario_cfg = ScenarioConfig.model_construct(
        scenarios=scenarios,
        forbid_mean_scenario=True,
        require_at_least_three=require_at_least_three,
    )
    return cfg.model_copy(update={"scenarios": scenario_cfg})


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _logit(value: float) -> float:
    return math.log(value / (1.0 - value))


def _forward_term_structure(hazards: list[float]) -> pd.DataFrame:
    weights = {"base": 0.60, "adverse": 0.30, "severe": 0.10}
    rows: list[dict[str, Any]] = []
    for scenario in ("base", "adverse", "severe"):
        survival_previous = 1.0
        for period, hazard in enumerate(hazards, start=1):
            pd_marginal = survival_previous * hazard
            survival = survival_previous * (1.0 - hazard)
            pd_cumulative = 1.0 - survival
            rows.append(
                {
                    "row_id": "id-1",
                    "segment": "retail",
                    "partition": "desarrollo",
                    "source_model": "survival",
                    "period": period,
                    "time_value": float(period),
                    "scenario": scenario,
                    "scenario_weight": weights[scenario],
                    "hazard": hazard,
                    "survival": survival,
                    "pd_marginal": pd_marginal,
                    "pd_cumulative": pd_cumulative,
                    "pd_marginal_base": pd_marginal,
                    "pd_cumulative_base": pd_cumulative,
                    "lgd": 0.40,
                    "lgd_base": 0.40,
                    "pd_basis": "pit",
                    "basis_state": "pit",
                    "ttc_reversion_weight": 1.0,
                    "satellite_adjustment": 0.0,
                    "macro_model_id": "macro:arima:x",
                    "satellite_model_id": "satellite:wilson:v1",
                    "method": "survival",
                    "pd_source": "survival",
                    "warning_codes": (),
                }
            )
            survival_previous = survival
    return pd.DataFrame(rows, columns=_FORWARD_COLUMNS)


def _ttc_anchor(hazards: list[float], *, pd_basis: str | None = "ttc") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    survival_previous = 1.0
    for period, hazard in enumerate(hazards, start=1):
        pd_marginal = survival_previous * hazard
        survival = survival_previous * (1.0 - hazard)
        pd_cumulative = 1.0 - survival
        rows.append(
            {
                "row_id": "id-1",
                "segment": "retail",
                "partition": "desarrollo",
                "source_model": "survival",
                "period": period,
                "time_value": float(period),
                "hazard": hazard,
                "survival": survival,
                "pd_marginal": pd_marginal,
                "pd_cumulative": pd_cumulative,
                "method": "survival",
                "pd_source": "survival",
                "pd_basis": pd_basis,
            }
        )
        survival_previous = survival
    frame = pd.DataFrame(rows, columns=_ANCHOR_COLUMNS)
    if pd_basis is None:
        frame = frame.drop(columns=["pd_basis"])
    return frame


def _macro_projection() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario": ["base", "adverse", "severe"],
            "scenario_weight": [0.60, 0.30, 0.10],
            "period": [1, 1, 1],
            "macro_variable": ["x", "x", "x"],
            "projected_value": [0.0, 1.0, 2.0],
            "model_value": [0.0, 0.0, 0.0],
            "shock_value": [-0.0, 1.0, 2.0],
        }
    )


def test_scenario_weights_tidy_y_validacion_macro_no_mutan_inputs() -> None:
    cfg = _cfg(scenarios=ScenarioConfig(), fail_on_falta_dato=False)
    weighting = ScenarioWeighting.from_config(cfg)
    assert isinstance(ScenarioWeighting.from_config(_cfg().model_dump()), ScenarioWeighting)
    projection = _macro_projection()
    original = projection.copy(deep=True)

    weights = weighting.scenario_weight_frame()
    weighting.validate_macro_projection(projection)
    weighting.validate_macro_projection(projection.drop(columns=["scenario_weight"]))
    weighting.validate_macro_projection(projection[["scenario"]])

    assert list(weights.columns) == [
        "scenario",
        "weight",
        "is_default",
        "source",
        "description",
    ]
    assert weights["source"].tolist() == ["default_a_confirmar"] * 3
    assert weights["is_default"].tolist() == [True, True, True]
    assert_frame_equal(projection, original)

    missing = projection[projection["scenario"] != "severe"]
    with pytest.raises(ForwardScenarioError, match="Faltan escenarios"):
        weighting.validate_macro_projection(missing)

    bad_weight = projection.copy(deep=True)
    bad_weight.loc[bad_weight["scenario"] == "adverse", "scenario_weight"] = 0.40
    with pytest.raises(ForwardScenarioError, match="no coincide"):
        weighting.validate_macro_projection(bad_weight)

    inconsistent_weight = pd.concat([projection, projection.iloc[[0]]], ignore_index=True)
    inconsistent_weight.loc[len(inconsistent_weight.index) - 1, "scenario_weight"] = 0.70
    with pytest.raises(ForwardScenarioError, match="inconsistente"):
        weighting.validate_macro_projection(inconsistent_weight)

    weighted_mean = projection.assign(weighted_mean_input=True)
    with pytest.raises(ForwardScenarioError, match="weighted_mean_input"):
        weighting.validate_macro_projection(weighted_mean)

    mean = projection.copy(deep=True)
    mean.loc[0, "scenario"] = "mean"
    with pytest.raises(ForwardScenarioError, match="Escenario medio"):
        weighting.validate_macro_projection(mean)

    null_scenario = projection.copy(deep=True)
    null_scenario.loc[0, "scenario"] = None
    with pytest.raises(ForwardScenarioError, match="nulos"):
        weighting.validate_macro_projection(null_scenario)

    empty_scenario = projection.copy(deep=True)
    empty_scenario.loc[0, "scenario"] = " "
    with pytest.raises(ForwardScenarioError, match="vacíos"):
        weighting.validate_macro_projection(empty_scenario)

    config_weights = ScenarioWeighting.from_config(_cfg()).scenario_weight_frame()
    assert config_weights["source"].tolist() == ["config"] * 3
    assert config_weights["is_default"].tolist() == [False, False, False]

    non_default_weights = ScenarioWeighting.from_config(
        _cfg(
            scenarios=ScenarioConfig(
                scenarios=(
                    _scenario("base", 0.50),
                    _scenario("adverse", 0.30, 1.0),
                    _scenario("severe", 0.20, 2.0),
                )
            )
        )
    ).scenario_weight_frame()
    assert non_default_weights["source"].tolist() == ["config"] * 3

    none_weight = projection.copy(deep=True)
    none_weight["scenario_weight"] = None
    weighting.validate_macro_projection(none_weight)


def test_weight_outputs_golden_no_promedia_inputs_macro() -> None:
    weighting = ScenarioWeighting.from_config(_cfg())
    base_logit = _logit(0.02)
    output_by_scenario = pd.DataFrame(
        {
            "portfolio": ["all", "all", "all"],
            "scenario": ["base", "adverse", "severe"],
            "hazard": [
                _sigmoid(base_logit + 0.5 * 1.0),
                _sigmoid(base_logit + 0.5 * 1.5),
                _sigmoid(base_logit + 0.5 * 2.4),
            ],
        }
    )

    weighted = weighting.weight_outputs(
        output_by_scenario,
        value_cols=("hazard",),
        group_cols=("portfolio",),
    )

    mean_input_hazard = _sigmoid(base_logit + 0.5 * 1.29)
    assert weighted["hazard"].tolist() == pytest.approx([0.0383014617], abs=1e-10)
    assert mean_input_hazard == pytest.approx(0.0374413137, abs=1e-10)
    assert weighted.loc[0, "hazard"] != pytest.approx(mean_input_hazard, abs=1e-10)
    assert "scenario" not in weighted.columns


def test_weight_outputs_defensas_de_runtime() -> None:
    weighting = ScenarioWeighting.from_config(_cfg())
    valid = pd.DataFrame(
        {
            "segment": ["retail", "retail", "retail"],
            "scenario": ["base", "adverse", "severe"],
            "ecl": [1.0, 2.0, 3.0],
        }
    )

    assert weighting.weight_outputs(valid, value_cols=("ecl",), group_cols=()).loc[0, "ecl"] == (
        pytest.approx(1.5)
    )
    with pytest.raises(ForwardScenarioError, match="scenario"):
        weighting.weight_outputs(
            valid.drop(columns=["scenario"]),
            value_cols=("ecl",),
            group_cols=(),
        )
    with pytest.raises(ForwardScenarioError, match="group_cols"):
        weighting.weight_outputs(valid, value_cols=("ecl",), group_cols=("scenario",))
    with pytest.raises(ForwardScenarioError, match="value_cols"):
        weighting.weight_outputs(valid, value_cols=(), group_cols=("segment",))

    missing = valid[valid["scenario"] != "severe"]
    with pytest.raises(ForwardScenarioError, match="Faltan escenarios"):
        weighting.weight_outputs(missing, value_cols=("ecl",), group_cols=("segment",))
    with pytest.raises(ForwardScenarioError, match="Faltan escenarios"):
        weighting.weight_outputs(missing, value_cols=("ecl",), group_cols=())

    group_missing = pd.DataFrame(
        {
            "segment": ["retail", "retail", "corp", "corp", "corp"],
            "scenario": ["base", "adverse", "base", "adverse", "severe"],
            "ecl": [1.0, 2.0, 1.0, 2.0, 3.0],
        }
    )
    with pytest.raises(ForwardScenarioError, match="grupo"):
        weighting.weight_outputs(group_missing, value_cols=("ecl",), group_cols=("segment",))

    unknown = valid.copy(deep=True)
    unknown.loc[0, "scenario"] = "optimistic"
    with pytest.raises(ForwardScenarioError, match="no configurados"):
        weighting.weight_outputs(unknown, value_cols=("ecl",), group_cols=("segment",))

    bad_value = valid.copy(deep=True)
    bad_value.loc[0, "ecl"] = math.inf
    with pytest.raises(ForwardScenarioError, match="no finito"):
        weighting.weight_outputs(bad_value, value_cols=("ecl",), group_cols=("segment",))

    with pytest.raises(ForwardScenarioError, match="solapan"):
        weighting.weight_outputs(valid, value_cols=("segment",), group_cols=("segment",))


@pytest.mark.parametrize(
    "cfg",
    [
        _cfg_construido(
            (
                _constructed_scenario("base", 0.60),
                _constructed_scenario("base", 0.30),
                _constructed_scenario("severe", 0.10),
            )
        ),
        _cfg_construido(
            (
                _constructed_scenario("base", 0.60),
                _constructed_scenario("adverse", -0.10),
                _constructed_scenario("severe", 0.50),
            )
        ),
        _cfg_construido(
            (
                _constructed_scenario("base", 0.50),
                _constructed_scenario("adverse", 0.30),
                _constructed_scenario("severe", 0.10),
            )
        ),
        _cfg_construido(
            (
                _constructed_scenario("base", 0.70),
                _constructed_scenario("adverse", 0.30),
            )
        ),
        _cfg_construido(
            (
                _constructed_scenario("", 0.60),
                _constructed_scenario("adverse", 0.30),
                _constructed_scenario("severe", 0.10),
            )
        ),
        _cfg_construido(
            (
                _constructed_scenario("base", 0.60),
                _constructed_scenario("mean", 0.30),
                _constructed_scenario("severe", 0.10),
            )
        ),
    ],
)
def test_pesos_invalidos_duplicados_negativos_y_menos_de_tres_fallan(
    cfg: ForwardConfig,
) -> None:
    with pytest.raises(ForwardScenarioError):
        ScenarioWeighting.from_config(cfg)


def test_apply_ttc_reversion_golden_logit_y_estados() -> None:
    weighting = ScenarioWeighting.from_config(_cfg())
    forward = _forward_term_structure([0.02, 0.03, 0.04, 0.05, 0.06])
    anchor = _ttc_anchor([0.01, 0.01, 0.01, 0.01, 0.01])
    original = forward.copy(deep=True)

    reverted = weighting.apply_ttc_reversion(forward, ttc_anchor=anchor)

    base = reverted[reverted["scenario"] == "base"].sort_values("period").reset_index(drop=True)
    assert_frame_equal(forward, original)
    assert base["ttc_reversion_weight"].tolist() == pytest.approx([1.0, 1.0, 0.5, 0.0, 0.0])
    assert base["basis_state"].tolist() == ["pit", "pit", "blended", "ttc", "ttc"]
    assert base["pd_basis"].tolist() == ["pit", "pit", "pit", "ttc", "ttc"]
    assert base.loc[2, "hazard"] == pytest.approx(
        _sigmoid(0.5 * _logit(0.04) + 0.5 * _logit(0.01)),
        abs=1e-12,
    )
    assert base.loc[3, "hazard"] == pytest.approx(0.01, abs=1e-12)
    assert base.loc[4, "survival"] == pytest.approx(1.0 - base.loc[4, "pd_cumulative"])
    assert base["pd_cumulative"].is_monotonic_increasing


def test_apply_ttc_reversion_advierte_ancla_pit_y_valida_invariantes() -> None:
    weighting = ScenarioWeighting.from_config(_cfg())
    forward = _forward_term_structure([0.02, 0.03, 0.04, 0.05, 0.06])

    with pytest.warns(RuntimeWarning, match="FALTA-DATO-FWD-4"):
        weighting.apply_ttc_reversion(forward, ttc_anchor=_ttc_anchor([0.01] * 5, pd_basis="pit"))
    with pytest.warns(RuntimeWarning, match="FALTA-DATO-FWD-4"):
        weighting.apply_ttc_reversion(forward, ttc_anchor=_ttc_anchor([0.01] * 5, pd_basis=None))

    disabled = ScenarioWeighting.from_config(
        _cfg(ttc_reversion=TtcReversionConfig(enabled=False, method="none"))
    )
    broken = _forward_term_structure([0.10, 0.20])
    mask = (broken["scenario"] == "base") & (broken["period"] == 2)
    broken.loc[mask, "pd_cumulative"] = 0.05
    broken.loc[mask, "survival"] = 0.95
    with pytest.raises(ForwardPredictionError, match="Monotonicidad"):
        disabled.apply_ttc_reversion(broken, ttc_anchor=_ttc_anchor([0.01, 0.01]))

    minimal = pd.DataFrame(
        {
            "scenario": ["base", "adverse", "severe"],
            "period": [1, 1, 1],
            "hazard": [0.10, 0.20, 0.30],
        }
    )
    sorted_minimal = disabled.apply_ttc_reversion(minimal, ttc_anchor=_ttc_anchor([0.01]))
    assert sorted_minimal["scenario"].tolist() == ["base", "adverse", "severe"]

    broken_identity = _forward_term_structure([0.10, 0.20])
    broken_identity.loc[0, "survival"] = 0.99
    with pytest.raises(ForwardPredictionError, match="survival"):
        disabled.apply_ttc_reversion(broken_identity, ttc_anchor=_ttc_anchor([0.01, 0.01]))

    historical_anchor = ScenarioWeighting.from_config(
        _cfg(
            ttc_reversion=TtcReversionConfig(
                reasonable_supportable_periods=2,
                reversion_periods=2,
                ttc_anchor="historical_mean",
            )
        )
    )
    historical_anchor.apply_ttc_reversion(
        forward, ttc_anchor=_ttc_anchor([0.01] * 5, pd_basis="pit")
    )


def test_apply_ttc_reversion_errores_de_ancla_y_probabilidad() -> None:
    weighting = ScenarioWeighting.from_config(_cfg())
    forward = _forward_term_structure([0.02, 0.03, 0.04, 0.05, 0.06])
    anchor = _ttc_anchor([0.01] * 5)

    duplicate_anchor = pd.concat([anchor, anchor.iloc[[0]]], ignore_index=True)
    with pytest.raises(ForwardPredictionError, match="duplicadas"):
        weighting.apply_ttc_reversion(forward, ttc_anchor=duplicate_anchor)

    missing_anchor = anchor[anchor["period"] != 5].reset_index(drop=True)
    with pytest.raises(ForwardPredictionError, match="no cubre"):
        weighting.apply_ttc_reversion(forward, ttc_anchor=missing_anchor)

    zero_anchor = anchor.copy(deep=True)
    zero_anchor.loc[zero_anchor["period"] == 3, "hazard"] = 0.0
    with pytest.raises(ForwardPredictionError, match=r"\(0, 1\)"):
        weighting.apply_ttc_reversion(forward, ttc_anchor=zero_anchor)

    duplicate_period = forward.copy(deep=True)
    duplicate_period.loc[
        (duplicate_period["scenario"] == "base") & (duplicate_period["period"] == 2),
        "period",
    ] = 1
    with pytest.raises(ForwardPredictionError, match="period"):
        weighting.apply_ttc_reversion(duplicate_period, ttc_anchor=anchor)

    out_of_range = forward.copy(deep=True)
    out_of_range.loc[0, "hazard"] = 1.20
    with pytest.raises(ForwardPredictionError, match=r"\[0, 1\]"):
        weighting.apply_ttc_reversion(out_of_range, ttc_anchor=anchor)


def test_hazard_derivado_y_helpers_defensivos_privados() -> None:
    pd_mod = pd
    cfg = _cfg()
    weighting = ScenarioWeighting.from_config(cfg)
    forward = _forward_term_structure([0.02, 0.03, 0.04]).drop(columns=["hazard"])
    anchor = _ttc_anchor([0.01, 0.01, 0.01]).drop(columns=["hazard"])

    reverted = weighting.apply_ttc_reversion(forward, ttc_anchor=anchor)

    assert "hazard" in reverted.columns
    assert reverted[reverted["scenario"] == "base"]["hazard"].tolist()[0] == pytest.approx(0.02)

    impossible = pd.DataFrame(
        {
            "scenario": ["base", "base"],
            "period": [1, 2],
            "pd_marginal": [1.0, 0.1],
        }
    )
    with pytest.raises(ForwardPredictionError, match="no derivable"):
        scenarios_module._ensure_hazard_column(
            impossible, pd=pd_mod, error_cls=ForwardPredictionError
        )

    no_scenario_hazard = pd.DataFrame(
        {
            "row_id": ["id-1", "id-1"],
            "period": [1, 2],
            "pd_marginal": [0.20, 0.08],
        }
    )
    scenarios_module._ensure_hazard_column(
        no_scenario_hazard,
        pd=pd_mod,
        error_cls=ForwardPredictionError,
    )
    assert no_scenario_hazard["hazard"].tolist() == pytest.approx([0.20, 0.10])

    duplicate_hazard_period = pd.DataFrame(
        {
            "scenario": ["base", "base"],
            "period": [1, 1],
            "pd_marginal": [0.10, 0.10],
        }
    )
    with pytest.raises(ForwardPredictionError, match="crecer estrictamente"):
        scenarios_module._ensure_hazard_column(
            duplicate_hazard_period,
            pd=pd_mod,
            error_cls=ForwardPredictionError,
        )

    duplicate_monotonic_period = pd.DataFrame(
        {
            "scenario": ["base", "base"],
            "period": [1, 1],
            "pd_cumulative": [0.10, 0.20],
        }
    )
    with pytest.raises(ForwardPredictionError, match="period"):
        scenarios_module._validate_monotonicity(duplicate_monotonic_period, cfg=cfg)

    bad_periods = [True, 1.5, 0]
    for bad_period in bad_periods:
        with pytest.raises(ForwardPredictionError):
            scenarios_module._positive_int(bad_period, field_name="period")

    assert (
        scenarios_module._probability(
            -0.0,
            field_name="pd",
            tol=1e-10,
            error_cls=ForwardPredictionError,
        )
        == 0.0
    )
    assert (
        scenarios_module._probability(
            1.0 - 1e-12,
            field_name="pd",
            tol=1e-10,
            error_cls=ForwardPredictionError,
        )
        == 1.0
    )
    assert scenarios_module._sigmoid(1.0) == pytest.approx(0.7310585786, abs=1e-10)
    with pytest.raises(ForwardPredictionError, match="Overflow"):
        scenarios_module._sigmoid(math.inf)
    with pytest.raises(ForwardPredictionError, match="fuera de rango"):
        scenarios_module._sigmoid(1000.0)

    unsorted = pd.DataFrame({"period": [2, 1], "row_id": ["id-2", None]})
    sorted_without_scenario = scenarios_module._sort_term_structure(unsorted, cfg=cfg)
    assert sorted_without_scenario["period"].tolist() == [1, 2]

    no_scenario = pd.DataFrame({"period": [1], "hazard": [0.0]})
    scenarios_module._validate_term_structure_invariants(no_scenario, cfg=cfg)

    key_row = next(pd.DataFrame({"row_id": [None], "period": [-0.0]}).itertuples(index=False))
    assert scenarios_module._row_key(key_row, ("row_id", "period")) == (None, 0.0)

    with pytest.raises(ForwardScenarioError, match=r"pandas\.DataFrame"):
        weighting.validate_macro_projection({"scenario": ["base"]})


def test_hazard_derivado_con_indice_no_range_no_publica_nan() -> None:
    weighting = ScenarioWeighting.from_config(_cfg())
    forward = _forward_term_structure([0.02, 0.03, 0.04]).drop(columns=["hazard"])
    anchor = _ttc_anchor([0.01, 0.01, 0.01]).drop(columns=["hazard"])
    forward.index = [10 * (index + 1) for index in range(len(forward.index))]
    anchor.index = [100, 200, 300]

    reverted = weighting.apply_ttc_reversion(forward, ttc_anchor=anchor)

    assert not reverted.isna().any().any()
    base = reverted[reverted["scenario"] == "base"].sort_values("period").reset_index(drop=True)
    expected_blended = _sigmoid(0.5 * _logit(0.04) + 0.5 * _logit(0.01))
    assert base["hazard"].tolist() == pytest.approx([0.02, 0.03, expected_blended], abs=1e-12)
    assert base["ttc_reversion_weight"].tolist() == pytest.approx([1.0, 1.0, 0.5])


def test_validate_probability_columns_rechaza_nan_explicito() -> None:
    cfg = _cfg()
    frame = _forward_term_structure([0.02])
    frame.loc[frame.index[0], "lgd"] = math.nan

    with pytest.raises(ForwardPredictionError, match="no finito"):
        scenarios_module._validate_probability_columns(frame, cfg=cfg)

    nullable = _forward_term_structure([0.02])
    nullable["lgd"] = nullable["lgd"].astype("object")
    nullable.loc[nullable.index[0], "lgd"] = pd.NA
    with pytest.raises(ForwardPredictionError, match="nulo"):
        scenarios_module._validate_probability_columns(nullable, cfg=cfg)


def test_imports_perezosos_exports_y_dependencia_faltante(monkeypatch: pytest.MonkeyPatch) -> None:
    code = (
        "import sys;"
        "import nikodym.forward;"
        "assert 'nikodym.forward.scenarios' not in sys.modules;"
        "baseline=set(sys.modules);"
        "assert 'ScenarioWeighting' in nikodym.forward.__all__;"
        "_=nikodym.forward.ScenarioWeighting;"
        "assert 'nikodym.forward.scenarios' in sys.modules;"
        "blocked=[m for m in ('pandas','numpy','scipy','statsmodels','pmdarima') "
        "if m in sys.modules and m not in baseline];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    assert forward_pkg.ScenarioWeighting is ScenarioWeighting

    original_import = scenarios_module.importlib.import_module

    def fake_import(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError(name)
        return original_import(name)

    monkeypatch.setattr(scenarios_module.importlib, "import_module", fake_import)
    with pytest.raises(MissingDependencyError, match="pandas"):
        scenarios_module._import_pandas()
