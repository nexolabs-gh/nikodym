"""Tests de resultados de ``forward``: DTOs puros, copias y CT-2."""

from __future__ import annotations

import inspect
import math
import subprocess
import sys
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.forward as forward_pkg
import nikodym.forward.results as forward_results
from nikodym.forward.config import (
    MacroModelKind as ConfigMacroModelKind,
)
from nikodym.forward.config import (
    SatelliteMode as ConfigSatelliteMode,
)
from nikodym.forward.config import (
    TargetComponent as ConfigTargetComponent,
)
from nikodym.forward.exceptions import ForwardPredictionError
from nikodym.forward.results import (
    ForwardCard,
    ForwardDiagnostics,
    ForwardEclInput,
    ForwardResult,
    MacroDiagnostics,
    MacroProjectionResult,
    SatelliteDiagnostics,
    SatelliteResult,
    ScenarioDiagnostics,
)

_MACRO_COLUMNS: tuple[str, ...] = (
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
)
_TERM_COLUMNS: tuple[str, ...] = (
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
)
_WEIGHT_COLUMNS: tuple[str, ...] = (
    "scenario",
    "weight",
    "is_default",
    "source",
    "description",
)
_ECL_CHAIN = (
    "macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting"
)
_DEFAULT = object()


class FakeDataFrame:
    """Frame-like no pandas para probar la defensa de ``term_structure``."""

    columns = pd.Index(_TERM_COLUMNS)

    def copy(self, *, deep: bool) -> FakeDataFrame:
        """Devuelve una copia lógica falsa."""
        assert deep is True
        return self

    def select_dtypes(self, *, include: list[str]) -> pd.DataFrame:
        """Emula la API mínima usada por el DTO."""
        assert include in (["float"], ["object"])
        return pd.DataFrame()

    def itertuples(self, *, index: bool) -> Any:
        """Entrega una fila válida para pasar la validación duck-typed."""
        assert index is False
        return iter(
            [
                (
                    "id-1",
                    "retail",
                    "desarrollo",
                    "survival",
                    1,
                    1.0,
                    "base",
                    0.60,
                    0.10,
                    0.90,
                    0.10,
                    0.10,
                    0.10,
                    0.10,
                    None,
                    None,
                    "pit",
                    "pit",
                    1.0,
                    0.0,
                    "macro-1",
                    "sat-1",
                    "survival",
                    "survival",
                    (),
                )
            ]
        )


def test_macro_diagnostics_golden_copias_y_normalizacion() -> None:
    """``MacroDiagnostics`` publica el contrato macro y protege mutabilidad."""
    orders_lags: dict[str, Any] = {"arima_order": (1, 0, 0), "zero": -0.0, "nan": math.inf}
    ljung_box_p_values = {"unemployment": [math.nan, -0.0, Decimal("-0")]}
    diagnostics = MacroDiagnostics(
        method="arima",
        macro_variables=("unemployment", "gdp"),
        frequency="M",
        orders_lags=orders_lags,
        horizon=12,
        dependency_versions={"statsmodels": "0.14.5"},
        input_rows=48,
        input_gaps=0,
        input_missing=1,
        input_time_range=(-0.0, 12),
        macro_data_hash="hash-macro",
        ljung_box_lags=(6, 12),
        ljung_box_statistics={"unemployment": {"lag6": Decimal("-0")}},
        ljung_box_p_values=ljung_box_p_values,
        ljung_box_action="warn",
        warnings=("lb-low-pvalue",),
    )

    assert tuple(MacroDiagnostics.model_fields) == (
        "method",
        "macro_variables",
        "frequency",
        "orders_lags",
        "horizon",
        "dependency_versions",
        "input_rows",
        "input_gaps",
        "input_missing",
        "input_time_range",
        "macro_data_hash",
        "ljung_box_lags",
        "ljung_box_statistics",
        "ljung_box_p_values",
        "ljung_box_action",
        "warnings",
    )
    assert diagnostics.model_dump(mode="json") == {
        "method": "arima",
        "macro_variables": ["unemployment", "gdp"],
        "frequency": "M",
        "orders_lags": {"arima_order": [1, 0, 0], "zero": 0.0, "nan": None},
        "horizon": 12,
        "dependency_versions": {"statsmodels": "0.14.5"},
        "input_rows": 48,
        "input_gaps": 0,
        "input_missing": 1,
        "input_time_range": [0.0, 12],
        "macro_data_hash": "hash-macro",
        "ljung_box_lags": [6, 12],
        "ljung_box_statistics": {"unemployment": {"lag6": 0.0}},
        "ljung_box_p_values": {"unemployment": [None, 0.0, 0.0]},
        "ljung_box_action": "warn",
        "warnings": ["lb-low-pvalue"],
    }

    orders_lags["zero"] = 99.0
    diagnostics.orders_lags["zero"] = 88.0
    diagnostics.dependency_versions["statsmodels"] = "mutado"
    assert diagnostics.orders_lags["zero"] == 0.0
    assert diagnostics.dependency_versions["statsmodels"] == "0.14.5"

    with pytest.raises(ValidationError, match="frozen"):
        diagnostics.horizon = 24
    with pytest.raises(ValidationError):
        MacroDiagnostics(
            method="arima",
            macro_variables=("gdp",),
            horizon=1,
            input_rows=1,
            input_gaps=0,
            input_missing=0,
            ljung_box_action="ok",
            extra="no permitido",
        )
    with pytest.raises(ValidationError, match="macro_variables"):
        _macro_diagnostics(macro_variables=())
    with pytest.raises(ValidationError, match="ljung_box_lags"):
        _macro_diagnostics(ljung_box_lags=(0,))
    with pytest.raises(ValidationError, match="input_time_range"):
        _macro_diagnostics(input_time_range=(1, 2, 3))
    with pytest.raises(ValidationError, match="booleanos"):
        _macro_diagnostics(input_time_range=(True, 2))
    with pytest.raises(ValidationError, match="input_time_range"):
        _macro_diagnostics(input_time_range=(object(), 2))
    with pytest.raises(ValidationError, match="ljung_box_action"):
        _macro_diagnostics(ljung_box_action=" ")
    with pytest.raises(ValidationError, match="textos opcionales"):
        _macro_diagnostics(frequency=" ")
    with pytest.raises(ValidationError):
        _macro_diagnostics(macro_data_hash=123)


def test_forward_results_payloads_opcionales_y_fallbacks() -> None:
    """Los payloads opcionales cubren defaults, errores y normalizadores auxiliares."""
    macro = _macro_diagnostics(
        frequency=None,
        orders_lags=None,
        ljung_box_statistics=None,
        ljung_box_p_values=None,
        input_time_range=None,
    )
    assert macro.orders_lags == {}
    assert macro.input_time_range is None

    satellite = _satellite_diagnostics(coefficients=None, fit_statistics=None)
    assert satellite.coefficients == {}
    assert satellite.fit_statistics == {}

    scenario = _scenario_diagnostics(scenario_sources=None)
    assert scenario.scenario_sources == {}

    metric_card = _card(metric_sections={"ljung_box": {"decimal_nan": Decimal("NaN")}})
    assert metric_card.metric_sections["ljung_box"]["decimal_nan"] is None

    decimal_weights = _scenario_weight_frame(
        weight=pd.Series([Decimal("0.60"), Decimal("0.30"), Decimal("0.10")], dtype=object)
    )
    assert _result(scenario_weight_frame=decimal_weights).scenario_weight_frame[
        "weight"
    ].tolist() == [
        Decimal("0.60"),
        Decimal("0.30"),
        Decimal("0.10"),
    ]

    term_with_missing_optional = _term_structure_frame(
        row_id=[math.nan, math.nan, math.nan],
        satellite_adjustment=[None, 0.10, -0.20],
    )
    assert (
        _result(forward_term_structure_frame=term_with_missing_optional).term_structure()
        is not None
    )

    with pytest.raises(ValidationError):
        _macro_diagnostics(orders_lags=["no permitido"])
    with pytest.raises(ValidationError):
        _satellite_diagnostics(coefficients=["no permitido"])
    with pytest.raises(ValidationError):
        _satellite_diagnostics(fit_statistics=["no permitido"])
    with pytest.raises(ValidationError):
        _scenario_diagnostics(scenario_weights=["no permitido"])
    with pytest.raises(ValidationError):
        _scenario_diagnostics(scenario_sources=["no permitido"])
    with pytest.raises(ValidationError):
        _ecl_input(pit_consistency=["no permitido"])
    with pytest.raises(ValidationError, match="números finitos"):
        _result(scenario_weight_frame=_scenario_weight_frame(weight=[True, 0.30, 0.70]))
    with pytest.raises(ValidationError, match="números finitos"):
        _result(scenario_weight_frame=_scenario_weight_frame(weight=[math.inf, 0.0, 0.0]))
    with pytest.raises(ValidationError, match="números finitos"):
        _result(
            scenario_weight_frame=_scenario_weight_frame(
                weight=[Decimal("NaN"), Decimal("0.30"), Decimal("0.70")]
            )
        )


def test_diagnostics_agregados_golden_copias_y_validaciones() -> None:
    """Los diagnósticos agregan macro, satellite, escenarios y PIT/TTC."""
    satellite = _satellite_diagnostics(
        coefficients={"pd": {"unemployment": Decimal("-0")}, "inf": math.inf},
        fit_statistics={
            "aic": math.inf,
            "iterations": 7,
            "flag": True,
            "scale": Decimal("-0"),
            "decimal_nan": Decimal("NaN"),
            "none": None,
            "status": "ok",
            "raw": object(),
        },
    )
    scenario_weights = {"base": 0.60, "adverse": 0.30, "severe": 0.10}
    scenario = _scenario_diagnostics(scenario_weights=scenario_weights)
    diagnostics = _diagnostics(satellite=satellite, scenario=scenario)

    assert tuple(SatelliteDiagnostics.model_fields) == (
        "mode",
        "target_components",
        "factor_columns",
        "segments",
        "coefficients",
        "fit_statistics",
        "warnings",
    )
    assert satellite.model_dump(mode="json") == {
        "mode": "fit",
        "target_components": ["pd", "lgd"],
        "factor_columns": ["unemployment", "gdp"],
        "segments": ["retail"],
        "coefficients": {"pd": {"unemployment": 0.0}, "inf": None},
        "fit_statistics": {
            "aic": None,
            "iterations": 7,
            "flag": "True",
            "scale": 0.0,
            "decimal_nan": None,
            "none": None,
            "status": "ok",
            "raw": str(satellite.fit_statistics["raw"]),
        },
        "warnings": [],
    }
    assert tuple(ScenarioDiagnostics.model_fields) == (
        "scenarios",
        "scenario_weights",
        "scenario_sources",
        "default_scenarios_to_confirm",
        "weight_sum",
        "no_mean_scenario_guard_executed",
        "no_mean_scenario_guard_result",
        "warnings",
    )
    assert scenario.model_dump(mode="json") == {
        "scenarios": ["base", "adverse", "severe"],
        "scenario_weights": scenario_weights,
        "scenario_sources": {
            "base": "config",
            "adverse": "config",
            "severe": "default_a_confirmar",
        },
        "default_scenarios_to_confirm": ["severe"],
        "weight_sum": 1.0,
        "no_mean_scenario_guard_executed": True,
        "no_mean_scenario_guard_result": "passed",
        "warnings": [],
    }
    assert tuple(ForwardDiagnostics.model_fields) == (
        "macro",
        "satellite",
        "scenario",
        "pd_basis",
        "basis_states",
        "pit_warnings",
        "pit_decisions",
        "ttc_reversion_method",
        "ttc_anchor",
        "reasonable_supportable_periods",
        "reversion_periods",
        "blended_periods",
        "no_mean_scenario_guard_executed",
        "no_mean_scenario_guard_result",
        "falta_dato",
        "warnings",
    )
    assert diagnostics.pd_basis == "pit"
    assert diagnostics.basis_states == ("pit", "blended", "ttc")
    assert diagnostics.blended_periods == (13, 14)

    scenario_weights["base"] = 99.0
    scenario.scenario_weights["base"] = 88.0
    satellite.coefficients["pd"]["unemployment"] = 77.0
    assert scenario.scenario_weights["base"] == 0.60
    assert satellite.coefficients["pd"]["unemployment"] == 0.0

    with pytest.raises(ValidationError, match="target_components"):
        _satellite_diagnostics(target_components=())
    with pytest.raises(ValidationError, match="factor_columns"):
        _satellite_diagnostics(factor_columns=())
    with pytest.raises(ValidationError, match="segments"):
        _satellite_diagnostics(segments=(" ",))
    with pytest.raises(ValidationError, match="scenarios no puede contener duplicados"):
        _scenario_diagnostics(scenarios=("base", "base"))
    with pytest.raises(ValidationError, match="mean"):
        _scenario_diagnostics(
            scenarios=("base", "mean"),
            scenario_weights={"base": 0.5, "mean": 0.5},
        )
    with pytest.raises(ValidationError, match="scenario_weights"):
        _scenario_diagnostics(scenario_weights={"base": 1.0})
    with pytest.raises(ValidationError, match="weight_sum"):
        _scenario_diagnostics(weight_sum=0.90)
    with pytest.raises(ValidationError, match="mayores o iguales"):
        _scenario_diagnostics(scenario_weights={"base": 0.6, "adverse": -0.1, "severe": 0.5})
    with pytest.raises(ValidationError, match="basis_states"):
        _diagnostics(basis_states=())
    with pytest.raises(ValidationError, match="blended_periods"):
        _diagnostics(blended_periods=(0,))
    with pytest.raises(ValidationError, match="no_mean_scenario_guard_result"):
        _diagnostics(no_mean_scenario_guard_result=" ")


def test_forward_card_ct2_resultados_huerfanos_y_copias() -> None:
    """``ForwardCard`` completa secciones CT-2 y los DTOs huérfanos no inventan campos."""
    metric_sections: dict[str, Any] = {
        "ljung_box": {"stat": -0.0},
        "custom": {"serie": [math.nan, -0.0], "tupla": (-0.0,)},
        "scenario_weights": {"base": 0.60},
    }
    dependency_versions = {"pandas": "2.3.3", "statsmodels": "0.14.5"}
    card = _card(metric_sections=metric_sections, dependency_versions=dependency_versions)

    assert tuple(ForwardCard.model_fields) == (
        "output_columns",
        "diagnostics",
        "dependency_versions",
        "falta_dato",
        "metric_sections",
    )
    dumped_sections = card.model_dump(mode="json")["metric_sections"]
    assert list(dumped_sections) == [
        "ljung_box",
        "custom",
        "scenario_weights",
        "macro_projection_summary",
        "satellite_coefficients",
        "pit_ttc_consistency",
        "term_structure_summary",
    ]
    assert dumped_sections["ljung_box"]["stat"] == 0.0
    assert dumped_sections["custom"]["serie"] == [None, 0.0]
    assert dumped_sections["custom"]["tupla"] == [0.0]
    assert _card().metric_sections == {
        "macro_projection_summary": {},
        "ljung_box": {},
        "scenario_weights": {},
        "satellite_coefficients": {},
        "pit_ttc_consistency": {},
        "term_structure_summary": {},
    }
    assert _card(metric_sections=None).metric_sections == _card().metric_sections

    metric_sections["ljung_box"]["stat"] = 99.0
    dependency_versions["pandas"] = "mutado"
    card.metric_sections["ljung_box"]["stat"] = 88.0
    card.dependency_versions["pandas"] = "mutado"
    assert card.metric_sections["ljung_box"]["stat"] == 0.0
    assert card.dependency_versions["pandas"] == "2.3.3"

    assert MacroProjectionResult().model_dump(mode="json") == {}
    assert SatelliteResult().model_dump(mode="json") == {}
    with pytest.raises(ValidationError):
        MacroProjectionResult(extra="no permitido")
    with pytest.raises(ValidationError):
        SatelliteResult(extra="no permitido")
    with pytest.raises(ValidationError, match="frozen"):
        card.falta_dato = ("FALTA-DATO-FWD-1",)
    with pytest.raises(ValidationError, match="output_columns"):
        _card(output_columns=("row_id", " "))
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])
    with pytest.raises(ValidationError):
        _card(dependency_versions=["no permitido"])


def test_forward_result_envuelve_frames_ecl_term_structure_y_copias() -> None:
    """``ForwardResult`` y ``ForwardEclInput`` copian frames y cumplen CT-2."""
    macro = _macro_projection_frame()
    term = _term_structure_frame()
    weights = _scenario_weight_frame()
    ecl_input = _ecl_input(term_structure_frame=term, scenario_weight_frame=weights)
    result = _result(
        macro_projection_frame=macro,
        forward_term_structure_frame=term,
        scenario_weight_frame=weights,
        ecl_input=ecl_input,
    )

    macro.loc[0, "scenario_weight"] = 99.0
    term.loc["id-1|1", "pd_marginal"] = 99.0
    weights.loc[0, "weight"] = 99.0

    observed_term = result.term_structure()
    assert observed_term is not None
    assert result.macro_projection_frame is not result.macro_projection_frame
    assert result.forward_term_structure_frame is not result.forward_term_structure_frame
    assert result.scenario_weight_frame is not result.scenario_weight_frame
    assert result.ecl_input.term_structure_frame is not result.ecl_input.term_structure_frame
    assert result.ecl_input.scenario_weight_frame is not result.ecl_input.scenario_weight_frame
    assert_frame_equal(result.macro_projection_frame, _normalized_macro_projection_frame())
    assert_frame_equal(result.forward_term_structure_frame, _normalized_term_structure_frame())
    assert_frame_equal(result.scenario_weight_frame, _normalized_scenario_weight_frame())
    assert_frame_equal(observed_term, _normalized_term_structure_frame())
    assert result.ecl_input.chain == _ECL_CHAIN
    assert result.ecl_input.contract_version == "SDD-20:1.0.0"
    assert result.ecl_input.pit_consistency == {"pd_basis": "pit", "zero": 0.0}
    assert tuple(observed_term.columns) == _TERM_COLUMNS
    assert math.copysign(1.0, observed_term.loc["id-1|1", "satellite_adjustment"]) == 1.0
    assert result.macro_projection_frame.loc[0, "shock_value"] == 0.0

    observed_term.loc["id-1|2", "pd_cumulative"] = 77.0
    assert_frame_equal(result.term_structure(), _normalized_term_structure_frame())

    annotation = inspect.signature(ForwardResult.term_structure).return_annotation
    assert annotation == "pandas.DataFrame | None"

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card(output_columns=())
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_forward_ecl_input_permite_lgd_faltante() -> None:
    """El contrato hacia ECL acepta LGD ausente para que SDD-16 pueda aportarla."""
    term = _term_structure_frame().drop(columns=["lgd", "lgd_base"])

    ecl_input = _ecl_input(term_structure_frame=term)

    assert tuple(ecl_input.term_structure_frame.columns) == tuple(term.columns)
    partial_term = _term_structure_frame().drop(columns=["lgd"])
    partial_ecl_input = _ecl_input(term_structure_frame=partial_term)
    assert tuple(partial_ecl_input.term_structure_frame.columns) == tuple(partial_term.columns)
    forward_results._validate_forward_term_structure_values(partial_term)
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(forward_term_structure_frame=term)


def test_forward_result_none_diagnostico_y_validaciones() -> None:
    """Modo diagnóstico retorna ``None`` y rechaza contratos estructurales rotos."""
    diagnostic = _result(
        forward_term_structure_frame=None,
        card=_card(output_columns=()),
        ecl_input=_ecl_input(term_structure_frame=None),
    )
    assert diagnostic.term_structure() is None
    assert diagnostic.forward_term_structure_frame is None
    assert diagnostic.ecl_input.term_structure_frame is None

    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(macro_projection_frame="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(macro_projection_frame=_macro_projection_frame().drop(columns=["warning_codes"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(
            forward_term_structure_frame=_term_structure_frame().drop(columns=["warning_codes"])
        )
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(scenario_weight_frame=_scenario_weight_frame().drop(columns=["description"]))
    with pytest.raises(ValidationError, match=r"card\.diagnostics"):
        _result(card=_card(diagnostics=_diagnostics(warnings=("otra",))))
    with pytest.raises(ValidationError, match="output_columns"):
        _result(card=_card(output_columns=("row_id",)))
    with pytest.raises(ValidationError, match="ecl_input"):
        _result(ecl_input=_ecl_input(term_structure_frame=None))
    with pytest.raises(ValidationError, match="contract_version"):
        _ecl_input(contract_version=" ")
    with pytest.raises(ValidationError):
        _ecl_input(chain="otra cadena")
    with pytest.raises(ValidationError):
        _ecl_input(extra="no permitido")

    fake_result = _result(forward_term_structure_frame=FakeDataFrame())
    with pytest.raises(ForwardPredictionError, match=r"pandas\.DataFrame"):
        fake_result.term_structure()


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"scenario": ["mean", "adverse", "severe"]}, "mean"),
        ({"period": [0, 1, 1]}, "period debe ser mayor"),
        ({"time_value": [-1.0, 1.0, 1.0]}, "time_value"),
        ({"macro_variable": [" ", "unemployment", "unemployment"]}, "macro_variable"),
        ({"method": [" ", "arima", "arima"]}, "method"),
        ({"model_id": [" ", "macro-1", "macro-1"]}, "model_id"),
    ],
)
def test_forward_result_valida_macro_projection(
    updates: dict[str, Any],
    message: str,
) -> None:
    """La proyección macro cumple columnas e invariantes mínimos de salida."""
    with pytest.raises(ValidationError, match=message):
        _result(macro_projection_frame=_macro_projection_frame(**updates))


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"scenario": ["average", "adverse", "severe"]}, "mean"),
        ({"weight": [0.50, 0.30, 0.10]}, "sumar 1"),
        ({"weight": [0.60, -0.30, 0.70]}, "mayores o iguales"),
        ({"source": ["manual", "config", "config"]}, "source"),
    ],
)
def test_forward_result_valida_scenario_weights(
    updates: dict[str, Any],
    message: str,
) -> None:
    """Los pesos de escenario no aceptan medias, negativos ni fuentes no canónicas."""
    with pytest.raises(ValidationError, match=message):
        _result(scenario_weight_frame=_scenario_weight_frame(**updates))


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"scenario": ["mean", "base", "base"]}, "mean"),
        ({"period": [0, 2, 3]}, "period debe ser mayor"),
        ({"period": [1.0, 2.0, 3.0]}, "period debe ser entero"),
        ({"time_value": [1.0, -2.0, 3.0]}, "time_value"),
        ({"pd_basis": ["ttc", "pit", "pit"]}, "pd_basis"),
        ({"basis_state": ["otro", "blended", "ttc"]}, "basis_state"),
        ({"hazard": [1.20, 0.20, 0.125]}, r"\[0, 1\]"),
        ({"pd_marginal": [-0.10, 0.18, 0.09]}, "pd_marginal"),
        ({"pd_cumulative": [0.20, 0.28, 0.37]}, "1 - survival"),
        ({"period": [1, 1, 3]}, "period debe crecer"),
        (
            {
                "survival": [0.90, 0.95, 0.70],
                "hazard": [0.10, 0.05, 0.2631578947368421],
                "pd_marginal": [0.10, 0.045, 0.25],
                "pd_cumulative": [0.10, 0.05, 0.30],
            },
            "pd_cumulative no puede decrecer",
        ),
        ({"hazard": [0.10, 0.20, 0.125], "pd_marginal": [0.10, 0.10, 0.09]}, "survival"),
        ({"satellite_adjustment": [0.0, "malo", 0.0]}, "satellite_adjustment"),
        ({"lgd": [None, "malo", None]}, "lgd"),
    ],
)
def test_forward_result_valida_term_structure(
    updates: dict[str, Any],
    message: str,
) -> None:
    """La term-structure forward protege invariantes CT-2 básicos."""
    with pytest.raises(ValidationError, match=message):
        _result(forward_term_structure_frame=_term_structure_frame(**updates))


def test_forward_results_import_liviano_y_exports_publicos() -> None:
    """``results`` y los exports lazy no cargan pandas/numpy ni forecasting pesado."""
    code = (
        "import sys;"
        "import nikodym.forward;"
        "assert 'nikodym.forward.results' not in sys.modules;"
        "baseline=set(sys.modules);"
        "blocked=[m for m in ('statsmodels','pmdarima','pandas','scipy') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'ForwardResult' in nikodym.forward.__all__;"
        "_=nikodym.forward.ForwardResult;"
        "assert 'nikodym.forward.results' in sys.modules;"
        "blocked=[m for m in ('statsmodels','pmdarima','pandas','scipy') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert not any(m.startswith('numpy') and m not in baseline for m in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert forward_results.MacroModelKind == ConfigMacroModelKind
    assert forward_results.SatelliteMode == ConfigSatelliteMode
    assert forward_results.TargetComponent == ConfigTargetComponent
    assert forward_pkg.ForwardResult is ForwardResult
    assert "ForwardDiagnostics" in forward_results.__all__
    assert "ForwardResult" in forward_results.__all__


def _macro_diagnostics(**updates: Any) -> MacroDiagnostics:
    payload: dict[str, Any] = {
        "method": "arima",
        "macro_variables": ("unemployment", "gdp"),
        "frequency": "M",
        "orders_lags": {"arima_order": (1, 0, 0)},
        "horizon": 12,
        "dependency_versions": {"statsmodels": "0.14.5"},
        "input_rows": 48,
        "input_gaps": 0,
        "input_missing": 1,
        "input_time_range": ("2024-01", "2025-12"),
        "macro_data_hash": "hash-macro",
        "ljung_box_lags": (6, 12),
        "ljung_box_statistics": {"unemployment": {"lag6": 1.5}},
        "ljung_box_p_values": {"unemployment": {"lag6": 0.25}},
        "ljung_box_action": "warn",
        "warnings": (),
    }
    payload.update(updates)
    return MacroDiagnostics(**payload)


def _satellite_diagnostics(**updates: Any) -> SatelliteDiagnostics:
    payload: dict[str, Any] = {
        "mode": "fit",
        "target_components": ("pd", "lgd"),
        "factor_columns": ("unemployment", "gdp"),
        "segments": ("retail",),
        "coefficients": {"pd": {"unemployment": 0.5}},
        "fit_statistics": {"aic": 12.5, "n_obs": 48},
        "warnings": (),
    }
    payload.update(updates)
    return SatelliteDiagnostics(**payload)


def _scenario_diagnostics(**updates: Any) -> ScenarioDiagnostics:
    payload: dict[str, Any] = {
        "scenarios": ("base", "adverse", "severe"),
        "scenario_weights": {"base": 0.60, "adverse": 0.30, "severe": 0.10},
        "scenario_sources": {
            "base": "config",
            "adverse": "config",
            "severe": "default_a_confirmar",
        },
        "default_scenarios_to_confirm": ("severe",),
        "weight_sum": 1.0,
        "no_mean_scenario_guard_executed": True,
        "no_mean_scenario_guard_result": "passed",
        "warnings": (),
    }
    payload.update(updates)
    return ScenarioDiagnostics(**payload)


def _diagnostics(**updates: Any) -> ForwardDiagnostics:
    payload: dict[str, Any] = {
        "macro": _macro_diagnostics(),
        "satellite": _satellite_diagnostics(),
        "scenario": _scenario_diagnostics(),
        "pd_basis": "pit",
        "basis_states": ("pit", "blended", "ttc"),
        "pit_warnings": (),
        "pit_decisions": ("pd_basis explícito",),
        "ttc_reversion_method": "linear_logit",
        "ttc_anchor": "input_term_structure",
        "reasonable_supportable_periods": 12,
        "reversion_periods": 24,
        "blended_periods": (13, 14),
        "no_mean_scenario_guard_executed": True,
        "no_mean_scenario_guard_result": "passed",
        "falta_dato": (),
        "warnings": (),
    }
    payload.update(updates)
    return ForwardDiagnostics(**payload)


def _card(**updates: Any) -> ForwardCard:
    payload: dict[str, Any] = {
        "output_columns": _TERM_COLUMNS,
        "diagnostics": _diagnostics(),
        "dependency_versions": {"pandas": "2.3.3", "statsmodels": "0.14.5"},
        "falta_dato": (),
    }
    payload.update(updates)
    return ForwardCard(**payload)


def _ecl_input(
    *,
    term_structure_frame: Any = _DEFAULT,
    scenario_weight_frame: Any = _DEFAULT,
    pit_consistency: Any = _DEFAULT,
    chain: object = _DEFAULT,
    contract_version: str = "SDD-20:1.0.0",
    extra: object | None = None,
) -> ForwardEclInput:
    payload: dict[str, Any] = {
        "term_structure_frame": _term_structure_frame()
        if term_structure_frame is _DEFAULT
        else term_structure_frame,
        "scenario_weight_frame": _scenario_weight_frame()
        if scenario_weight_frame is _DEFAULT
        else scenario_weight_frame,
        "pit_consistency": {"pd_basis": "pit", "zero": -0.0}
        if pit_consistency is _DEFAULT
        else pit_consistency,
        "contract_version": contract_version,
    }
    if chain is not _DEFAULT:
        payload["chain"] = chain
    if extra is not None:
        payload["extra"] = extra
    return ForwardEclInput(**payload)


def _result(
    *,
    macro_projection_frame: Any = _DEFAULT,
    forward_term_structure_frame: Any = _DEFAULT,
    scenario_weight_frame: Any = _DEFAULT,
    diagnostics: ForwardDiagnostics | None = None,
    card: ForwardCard | None = None,
    ecl_input: ForwardEclInput | None = None,
    extra: object | None = None,
) -> ForwardResult:
    term = (
        _term_structure_frame()
        if forward_term_structure_frame is _DEFAULT
        else forward_term_structure_frame
    )
    weights = (
        _scenario_weight_frame() if scenario_weight_frame is _DEFAULT else scenario_weight_frame
    )
    payload: dict[str, Any] = {
        "macro_projection_frame": _macro_projection_frame()
        if macro_projection_frame is _DEFAULT
        else macro_projection_frame,
        "forward_term_structure_frame": term,
        "scenario_weight_frame": weights,
        "diagnostics": _diagnostics() if diagnostics is None else diagnostics,
        "card": _card() if card is None else card,
        "ecl_input": _ecl_input(term_structure_frame=term, scenario_weight_frame=weights)
        if ecl_input is None
        else ecl_input,
    }
    if extra is not None:
        payload["extra"] = extra
    return ForwardResult(**payload)


def _macro_projection_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "scenario": ["base", "adverse", "severe"],
        "scenario_weight": [0.60, 0.30, 0.10],
        "period": [1, 1, 1],
        "time_value": [1.0, 1.0, 1.0],
        "macro_variable": ["unemployment", "unemployment", "unemployment"],
        "projected_value": [1.0, 1.5, 2.4],
        "model_value": [1.0, 1.2, 1.3],
        "shock_value": pd.Series([Decimal("-0"), 1.25, -0.0], dtype=object),
        "method": ["arima", "arima", "arima"],
        "model_id": ["macro-1", "macro-1", "macro-1"],
        "is_reasonable_supportable": [True, True, True],
        "warning_codes": [(), (), ("FALTA-DATO-FWD-1",)],
    }
    payload.update(updates)
    return pd.DataFrame(payload)


def _scenario_weight_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "scenario": ["base", "adverse", "severe"],
        "weight": [0.60, 0.30, 0.10],
        "is_default": [False, False, True],
        "source": ["config", "config", "default_a_confirmar"],
        "description": pd.Series([True, "adverse", None], dtype=object),
    }
    payload.update(updates)
    return pd.DataFrame(payload)


def _term_structure_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "row_id": ["id-1", "id-1", "id-1"],
        "segment": ["retail", "retail", "retail"],
        "partition": ["desarrollo", "desarrollo", "desarrollo"],
        "source_model": ["survival", "survival", "survival"],
        "period": [1, 2, 3],
        "time_value": [1.0, 2.0, 3.0],
        "scenario": ["base", "base", "base"],
        "scenario_weight": [0.60, 0.60, 0.60],
        "hazard": [0.10, 0.20, 0.125],
        "survival": [0.90, 0.72, 0.63],
        "pd_marginal": [0.10, 0.18, 0.09],
        "pd_cumulative": [0.10, 0.28, 0.37],
        "pd_marginal_base": [0.10, 0.18, 0.09],
        "pd_cumulative_base": [0.10, 0.28, 0.37],
        "lgd": [None, None, None],
        "lgd_base": [None, None, None],
        "pd_basis": ["pit", "pit", "pit"],
        "basis_state": ["pit", "blended", "ttc"],
        "ttc_reversion_weight": [1.0, 0.5, -0.0],
        "satellite_adjustment": [-0.0, 0.10, -0.20],
        "macro_model_id": ["macro-1", "macro-1", "macro-1"],
        "satellite_model_id": ["sat-1", "sat-1", "sat-1"],
        "method": ["survival", "survival", "survival"],
        "pd_source": ["survival", "survival", "survival"],
        "warning_codes": [(), (), ("FALTA-DATO-FWD-1",)],
    }
    payload.update(updates)
    return pd.DataFrame(
        payload,
        index=pd.Index(["id-1|1", "id-1|2", "id-1|3"], name="curve_id"),
    )


def _normalized_macro_projection_frame() -> pd.DataFrame:
    return _normalize_frame(_macro_projection_frame())


def _normalized_scenario_weight_frame() -> pd.DataFrame:
    return _normalize_frame(_scenario_weight_frame())


def _normalized_term_structure_frame() -> pd.DataFrame:
    return _normalize_frame(_term_structure_frame())


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    for column in normalized.select_dtypes(include=["float"]).columns:
        normalized[column] = normalized[column].mask(normalized[column] == 0.0, 0.0)
    for column in normalized.select_dtypes(include=["object"]).columns:
        normalized[column] = normalized[column].map(_normalize_object_cell)
    return normalized


def _normalize_object_cell(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        if value.is_finite() and float(value) == 0.0:
            return 0.0
        return value
    if isinstance(value, float) and math.isfinite(value) and value == 0.0:
        return 0.0
    return value
