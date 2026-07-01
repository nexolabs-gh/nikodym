"""Tests de resultados de ``stress``: DTOs puros, copias y CT-2."""

from __future__ import annotations

import inspect
import math
import subprocess
import sys
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.stress as stress_pkg
import nikodym.stress.results as stress_results
from nikodym.stress.exceptions import StressOutputError
from nikodym.stress.results import (
    ReverseStressResult,
    StressCard,
    StressDiagnostics,
    StressResult,
    StressScenarioResult,
    StressSensitivityResult,
)

_SCENARIO_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "base_forward_scenario",
    "severity",
    "macro_variable",
    "operation",
    "shock_value",
    "applied_shock",
    "period",
    "source",
    "warning_codes",
)
_TERM_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "severity",
    "base_forward_scenario",
    "row_id",
    "segment",
    "partition",
    "source_model",
    "method",
    "pd_source",
    "period",
    "time_value",
    "macro_variable_set",
    "hazard_base",
    "hazard_stress",
    "survival_stress",
    "pd_marginal_base",
    "pd_marginal_stress",
    "pd_cumulative_base",
    "pd_cumulative_stress",
    "lgd_base",
    "lgd_stress",
    "pd_basis",
    "basis_state",
    "satellite_adjustment_base",
    "satellite_adjustment_stress",
    "warning_codes",
)
_IMPACT_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "severity",
    "metric",
    "value_base",
    "value_stress",
    "absolute_delta",
    "relative_delta",
    "group_key",
    "period",
    "engine_source",
    "warning_codes",
)
_REVERSE_PATH_COLUMNS: tuple[str, ...] = (
    "target_name",
    "iteration",
    "lo",
    "hi",
    "mid",
    "metric_value",
    "threshold",
    "decision",
)
_DEFAULT = object()


class FakeTermStructureFrame:
    """Frame-like no pandas para probar la defensa de ``term_structure``."""

    columns = pd.Index(_TERM_COLUMNS)

    def copy(self, *, deep: bool) -> FakeTermStructureFrame:
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
                    "severe_downturn",
                    "severe",
                    1.0,
                    "severe",
                    "id-1",
                    "retail",
                    "desarrollo",
                    "survival",
                    "survival",
                    "survival",
                    1,
                    1.0,
                    "unemployment",
                    0.10,
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
                    0.0,
                    0.0,
                    (),
                )
            ]
        )


class FakeImpactFrame:
    """Frame-like no pandas para probar la defensa de ``tidy``."""

    columns = pd.Index(_IMPACT_COLUMNS)

    def copy(self, *, deep: bool) -> FakeImpactFrame:
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
                    "severe_downturn",
                    "severe",
                    1.0,
                    "ecl",
                    10.0,
                    15.0,
                    5.0,
                    0.5,
                    "segment=retail",
                    1,
                    "ecl_engine",
                    (),
                )
            ]
        )


class FakeScenarioFrame:
    """Frame-like no pandas para probar la defensa de ``scenarios``."""

    columns = pd.Index(_SCENARIO_COLUMNS)

    def copy(self, *, deep: bool) -> FakeScenarioFrame:
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
                    "severe_downturn",
                    "severe",
                    "severe",
                    1.0,
                    "unemployment",
                    "additive",
                    0.0,
                    0.0,
                    1,
                    "user",
                    (),
                )
            ]
        )


def test_stress_scenario_result_golden_copias_y_normalizacion() -> None:
    """``StressScenarioResult`` envuelve frames SDD-21 §6 sin mutabilidad externa."""
    scenario_frame = _scenario_frame()
    macro = _macro_projection_frame()
    term = _term_structure_frame()
    impact = _impact_frame()
    result = _scenario_result(
        scenario_frame=scenario_frame,
        stressed_macro_frame=macro,
        stressed_term_structure_frame=term,
        impact_frame=impact,
        severity=Decimal("1.0"),
    )

    scenario_frame.loc[0, "applied_shock"] = 99.0
    macro.loc[0, "projected_value"] = 99.0
    term.loc["id-1|1", "pd_marginal_stress"] = 99.0
    impact.loc[0, "value_stress"] = 99.0

    assert tuple(StressScenarioResult.model_fields) == (
        "scenario_name",
        "scenario_kind",
        "severity",
        "scenario_frame",
        "stressed_macro_frame",
        "stressed_term_structure_frame",
        "impact_frame",
        "warning_codes",
    )
    assert result.scenario_name == "severe_downturn"
    assert result.severity == pytest.approx(1.0)
    assert result.scenario_frame is not result.scenario_frame
    assert result.stressed_macro_frame is not result.stressed_macro_frame
    assert result.stressed_term_structure_frame is not result.stressed_term_structure_frame
    assert result.impact_frame is not result.impact_frame
    assert_frame_equal(result.scenario_frame, _normalized_scenario_frame())
    assert_frame_equal(result.stressed_macro_frame, _normalized_macro_projection_frame())
    assert_frame_equal(result.stressed_term_structure_frame, _normalized_term_structure_frame())
    assert_frame_equal(result.impact_frame, _normalized_impact_frame())
    assert result.scenario_frame.loc[0, "shock_value"] == 0.0
    assert result.stressed_macro_frame.loc[0, "shock_value"] == 0.0
    assert result.stressed_term_structure_frame.loc["id-1|1", "macro_variable_set"] == (
        "unemployment",
        "inflation",
    )
    assert math.copysign(1.0, result.impact_frame.loc[1, "absolute_delta"]) == 1.0

    observed_impact = result.impact_frame
    observed_impact.loc[0, "value_stress"] = 88.0
    assert_frame_equal(result.impact_frame, _normalized_impact_frame())

    with pytest.raises(ValidationError, match="frozen"):
        result.severity = 2.0
    with pytest.raises(ValidationError):
        _scenario_result(extra="no permitido")
    with pytest.raises(ValidationError, match="mean"):
        _scenario_result(scenario_name="mean")
    with pytest.raises(ValidationError, match="mean"):
        _scenario_result(scenario_name="Mean")
    with pytest.raises(ValidationError, match="mayores o iguales"):
        _scenario_result(severity=-0.01)
    with pytest.raises(ValidationError, match="warning_codes"):
        _scenario_result(warning_codes=(" ",))


def test_diagnostics_y_card_golden_payloads_copias_y_defaults() -> None:
    """Diagnósticos y card normalizan payloads CT-2 y protegen dicts mutables."""
    dependency_versions = {"pandas": "2.3.3", "engine": 1, Decimal("-0"): -0.0, "flag": True}
    diagnostics = StressDiagnostics(
        scenario_count=1,
        sensitivity_count=1,
        reverse_count=1,
        falta_dato_codes=("FALTA-DATO-STR-1",),
        warning_codes=("WARN-STR-1",),
        dependency_versions=dependency_versions,
    )
    metric_sections: dict[str, Any] = {
        "scenario_impacts": {"delta": -0.0},
        "custom": {
            "flag": True,
            "label": "ok",
            "serie": [Decimal("-0"), Decimal("1.25")],
            "tupla": (-0.0,),
        },
    }
    card = StressCard(
        summary={
            "scenario_count": 1,
            "zero": Decimal("-0"),
            Decimal("-0"): -0.0,
            "ok": True,
            "label": "stress",
        },
        metric_sections=metric_sections,
        assumptions=("sin Monte Carlo v1",),
        limitations=("engine ECL externo",),
    )

    assert tuple(StressDiagnostics.model_fields) == (
        "scenario_count",
        "sensitivity_count",
        "reverse_count",
        "falta_dato_codes",
        "warning_codes",
        "dependency_versions",
    )
    assert diagnostics.model_dump(mode="json") == {
        "scenario_count": 1,
        "sensitivity_count": 1,
        "reverse_count": 1,
        "falta_dato_codes": ["FALTA-DATO-STR-1"],
        "warning_codes": ["WARN-STR-1"],
        "dependency_versions": {"pandas": "2.3.3", "engine": "1", "0.0": "0.0", "flag": "True"},
    }
    assert tuple(StressCard.model_fields) == (
        "summary",
        "metric_sections",
        "assumptions",
        "limitations",
    )
    assert card.model_dump(mode="json") == {
        "summary": {
            "scenario_count": 1,
            "zero": 0.0,
            "0.0": 0.0,
            "ok": True,
            "label": "stress",
        },
        "metric_sections": {
            "scenario_impacts": {"delta": 0.0},
            "custom": {
                "flag": True,
                "label": "ok",
                "serie": [0.0, 1.25],
                "tupla": [0.0],
            },
            "sensitivity_curves": {},
            "reverse_stress": {},
            "term_structure_summary": {},
            "falta_dato": {},
        },
        "assumptions": ["sin Monte Carlo v1"],
        "limitations": ["engine ECL externo"],
    }
    assert card.summary == {
        "scenario_count": 1,
        "zero": 0.0,
        "0.0": 0.0,
        "ok": True,
        "label": "stress",
    }
    assert card.metric_sections["custom"] == {
        "flag": True,
        "label": "ok",
        "serie": [0.0, 1.25],
        "tupla": (0.0,),
    }
    card_sets = StressCard(
        summary={"ok": True},
        metric_sections={
            "custom": {
                "set": {Decimal("-0"), 2.0},
                "frozenset": frozenset({Decimal("-0"), 3.0}),
                "numpy_zero": np.float64("-0.0"),
            }
        },
    )
    assert card_sets.metric_sections["custom"]["set"] == {0.0, 2.0}
    assert card_sets.metric_sections["custom"]["frozenset"] == frozenset({0.0, 3.0})
    assert card_sets.metric_sections["custom"]["numpy_zero"] == 0.0
    assert StressCard(summary={"ok": np.bool_(True)}).summary["ok"] is True
    assert (
        StressCard(
            summary={"ok": True}, metric_sections={"custom": {"flag": np.array(True)}}
        ).metric_sections["custom"]["flag"]
        is True
    )
    assert StressCard(summary={"ok": True}).metric_sections == {
        "scenario_impacts": {},
        "sensitivity_curves": {},
        "reverse_stress": {},
        "term_structure_summary": {},
        "falta_dato": {},
    }
    assert (
        StressCard(summary={"ok": True}, metric_sections=None).metric_sections
        == StressCard(summary={"ok": True}).metric_sections
    )

    dependency_versions["pandas"] = "mutado"
    metric_sections["scenario_impacts"]["delta"] = 99.0
    diagnostics.dependency_versions["pandas"] = "mutado"
    card.metric_sections["scenario_impacts"]["delta"] = 88.0
    card.summary["zero"] = 77.0
    assert diagnostics.dependency_versions["pandas"] == "2.3.3"
    assert card.metric_sections["scenario_impacts"]["delta"] == 0.0
    assert card.summary["zero"] == 0.0

    with pytest.raises(ValidationError, match="frozen"):
        diagnostics.scenario_count = 2
    with pytest.raises(ValidationError):
        StressDiagnostics(
            scenario_count=0,
            sensitivity_count=0,
            reverse_count=0,
            dependency_versions=["no permitido"],
        )
    with pytest.raises(ValidationError, match="summary"):
        StressCard(summary={"bad": math.inf})
    with pytest.raises(ValidationError, match="summary"):
        StressCard(summary={"bad": Decimal("NaN")})
    with pytest.raises(ValueError, match="float"):
        stress_results._normalize_required_float(np.bool_(True))
    with pytest.raises(ValueError, match="entero"):
        stress_results._integer_value(np.bool_(True), field_name="period")
    with pytest.raises(ValidationError, match="summary"):
        StressCard(summary={"bad": object()})
    with pytest.raises(ValidationError, match="summary"):
        StressCard(summary={math.nan: 1.0})
    with pytest.raises(ValidationError, match="summary"):
        StressCard(summary={math.inf: 1.0})
    with pytest.raises(ValidationError, match="summary"):
        StressCard(summary={None: 1.0})
    with pytest.raises(ValidationError):
        StressCard(summary=["no permitido"])
    with pytest.raises(ValidationError):
        StressCard(summary={"ok": True}, metric_sections=["no permitido"])
    with pytest.raises(ValidationError, match="metric_sections"):
        StressCard(summary={"ok": True}, metric_sections={"bad": math.inf})
    with pytest.raises(ValidationError, match="metric_sections"):
        StressCard(summary={"ok": True}, metric_sections={"bad": Decimal("NaN")})
    with pytest.raises(ValidationError, match="metric_sections"):
        StressCard(summary={"ok": True}, metric_sections={"bad": np.array([math.nan])})
    with pytest.raises(ValidationError, match="arreglos NumPy"):
        StressCard(summary={"ok": True}, metric_sections={"bad": np.array([1.0])})
    with pytest.raises(ValidationError, match="metric_sections"):
        StressCard(summary={"ok": True}, metric_sections={math.nan: {"value": 1.0}})
    with pytest.raises(ValidationError, match="metric_sections"):
        StressCard(summary={"ok": True}, metric_sections={"bad": {"value": pd.NA}})
    with pytest.raises(ValidationError, match="dependency_versions"):
        StressDiagnostics(
            scenario_count=0,
            sensitivity_count=0,
            reverse_count=0,
            dependency_versions={math.nan: "1.0"},
        )
    with pytest.raises(ValidationError, match="dependency_versions"):
        StressDiagnostics(
            scenario_count=0,
            sensitivity_count=0,
            reverse_count=0,
            dependency_versions={"engine": math.inf},
        )
    with pytest.raises(ValidationError, match="dependency_versions"):
        StressDiagnostics(
            scenario_count=0,
            sensitivity_count=0,
            reverse_count=0,
            dependency_versions={"engine": None},
        )
    with pytest.raises(ValidationError, match="card_texts"):
        StressCard(summary={"ok": True}, assumptions=(" ",))


def test_bool_like_numpy_defensivo_results() -> None:
    """El guard bool-like cubre escalares NumPy y objetos defensivos."""

    class FakeBoolShapeNone:
        """Objeto tipo NumPy con dtype bool y shape ausente."""

        __module__ = "numpy"
        dtype = type("Dtype", (), {"kind": "b"})()
        shape = None

    class FakeBoolBadShape:
        """Objeto tipo NumPy con dtype bool y shape no iterable."""

        __module__ = "numpy"
        dtype = type("Dtype", (), {"kind": "b"})()
        shape = object()

    assert stress_results._is_bool_like(np.array(True)) is True
    assert stress_results._contains_nonfinite(np.array([math.nan]), allow_none=False) is True
    assert (
        stress_results._contains_nonfinite(
            np.array([{"x": math.inf}], dtype=object), allow_none=False
        )
        is True
    )
    assert (
        stress_results._contains_nonfinite(
            np.array(["NaT"], dtype="datetime64[ns]"), allow_none=False
        )
        is True
    )
    assert stress_results._contains_nonfinite(np.array(["ok"]), allow_none=False) is False

    class NonHashableKey:
        """Objeto no hashable para celdas escalares opcionales."""

        __hash__ = None

    with pytest.raises(ValueError, match="escalar"):
        stress_results._validate_optional_scalar_cell(NonHashableKey(), field_name="row_id")
    assert stress_results._is_bool_like(FakeBoolShapeNone()) is False
    assert stress_results._is_bool_like(FakeBoolBadShape()) is False


def test_numpy_array_contains_nonfinite_fallback_sin_numpy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El helper lazy degrada si NumPy no puede importarse."""

    def fail_import(name: str) -> object:
        if name == "numpy":
            raise ModuleNotFoundError(name)
        return __import__(name)

    monkeypatch.setattr(stress_results.importlib, "import_module", fail_import)
    assert stress_results._numpy_array_contains_nonfinite(np.array([1.0]), allow_none=False) is None


def test_sensitivity_y_reverse_result_golden_copias_y_validaciones() -> None:
    """Sensibilidad y reverse stress publican DTOs frozen con frames defensivos."""
    sensitivity_frame = _impact_frame(scenario_kind=["sensitivity", "sensitivity", "sensitivity"])
    baseline = _baseline_metric_frame()
    sensitivity = StressSensitivityResult(
        sweep_name="unemployment_grid",
        factor="unemployment",
        severity_grid=(Decimal("-0"), 1.0, 2.0),
        sensitivity_frame=sensitivity_frame,
        baseline_metric_frame=baseline,
        monotonicity_flag="increasing",
    )
    reverse_path = _reverse_path_frame()
    reverse = ReverseStressResult(
        target_name="capital_floor",
        metric="ecl",
        threshold=25.0,
        direction="at_least",
        severity=1.25,
        metric_value=25.0,
        iterations=1,
        bracket=(Decimal("-0"), 5.0),
        converged=True,
        reverse_path_frame=reverse_path,
    )
    reverse_no_convergido = ReverseStressResult(
        target_name="capital_floor",
        metric="ecl",
        threshold=25.0,
        direction="at_least",
        severity=1.25,
        metric_value=24.0,
        iterations=1,
        bracket=(Decimal("-0"), 5.0),
        converged=False,
        reverse_path_frame=_reverse_path_frame(
            metric_value=[27.5, 24.0],
            decision=["move_hi", "move_lo"],
        ),
    )

    sensitivity_frame.loc[0, "value_stress"] = 99.0
    baseline.loc[0, "value"] = 99.0
    reverse_path.loc[0, "metric_value"] = 99.0

    assert tuple(StressSensitivityResult.model_fields) == (
        "sweep_name",
        "factor",
        "severity_grid",
        "sensitivity_frame",
        "baseline_metric_frame",
        "monotonicity_flag",
    )
    assert sensitivity.severity_grid == (0.0, 1.0, 2.0)
    assert_frame_equal(
        sensitivity.sensitivity_frame,
        _normalize_frame(
            _impact_frame(scenario_kind=["sensitivity", "sensitivity", "sensitivity"])
        ),
    )
    assert_frame_equal(sensitivity.baseline_metric_frame, _normalized_baseline_metric_frame())
    assert sensitivity.baseline_metric_frame.loc[0, "payload"] == {
        "zero": 0.0,
        "nonzero_decimal": Decimal("1.25"),
        "items": [0.0, True],
    }
    baseline_float = StressSensitivityResult(
        sweep_name="unemployment_grid",
        factor="unemployment",
        severity_grid=(0.0, 1.0, 2.0),
        sensitivity_frame=_impact_frame(
            scenario_kind=["sensitivity", "sensitivity", "sensitivity"]
        ),
        baseline_metric_frame=_baseline_metric_frame(value=[-0.0]),
        monotonicity_flag="increasing",
    )
    observed_baseline_value = baseline_float.baseline_metric_frame.loc[0, "value"]
    assert observed_baseline_value == 0.0
    assert math.copysign(1.0, observed_baseline_value) > 0.0
    assert tuple(ReverseStressResult.model_fields) == (
        "target_name",
        "metric",
        "threshold",
        "direction",
        "severity",
        "metric_value",
        "iterations",
        "bracket",
        "converged",
        "reverse_path_frame",
    )
    assert reverse.bracket == (0.0, 5.0)
    assert reverse.iterations == 1
    assert reverse_no_convergido.converged is False
    assert reverse_no_convergido.metric_value == pytest.approx(24.0)
    assert_frame_equal(reverse.reverse_path_frame, _normalized_reverse_path_frame())

    sensitivity_missing_float = _impact_frame(
        scenario_kind=["sensitivity", "sensitivity", "sensitivity"]
    )
    sensitivity_missing_float["relative_delta"] = pd.Series(
        [0.20, None, 0.50],
        index=sensitivity_missing_float.index,
    )
    sensitivity_con_missing = StressSensitivityResult(
        sweep_name="unemployment_grid",
        factor="unemployment",
        severity_grid=(0.0, 1.0, 2.0),
        sensitivity_frame=sensitivity_missing_float,
        baseline_metric_frame=_baseline_metric_frame(),
        monotonicity_flag="increasing",
    )
    assert sensitivity_con_missing.sensitivity_frame["relative_delta"].tolist() == [
        0.20,
        None,
        0.50,
    ]

    with pytest.raises(ValidationError, match="severity_grid"):
        StressSensitivityResult(
            sweep_name="grid",
            factor="unemployment",
            severity_grid=(),
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(),
            monotonicity_flag="flat",
        )
    with pytest.raises(ValidationError, match="severity_grid"):
        StressSensitivityResult(
            sweep_name="grid",
            factor="unemployment",
            severity_grid=None,
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(),
            monotonicity_flag="flat",
        )
    with pytest.raises(ValidationError, match="severity_grid"):
        StressSensitivityResult(
            sweep_name="grid",
            factor="unemployment",
            severity_grid=(0.0, 0.0),
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(),
            monotonicity_flag="flat",
        )
    with pytest.raises(ValidationError, match="sweep_name"):
        StressSensitivityResult(
            sweep_name=" ",
            factor="unemployment",
            severity_grid=(0.0, 1.0),
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(),
            monotonicity_flag="flat",
        )
    with pytest.raises(ValidationError, match="metric"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="otra",
            threshold=25.0,
            direction="at_least",
            severity=1.0,
            metric_value=25.0,
            iterations=0,
            bracket=(0.0, 5.0),
            converged=False,
            reverse_path_frame=_reverse_path_frame(),
        )
    with pytest.raises(ValidationError, match="bracket"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.0,
            metric_value=25.0,
            iterations=0,
            bracket=None,
            converged=False,
            reverse_path_frame=_reverse_path_frame(),
        )
    with pytest.raises(ValidationError, match="bracket"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.0,
            metric_value=25.0,
            iterations=0,
            bracket=(0.0,),
            converged=False,
            reverse_path_frame=_reverse_path_frame(),
        )
    with pytest.raises(ValidationError, match="iterations"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.0,
            metric_value=25.0,
            iterations=-1,
            bracket=(0.0, 5.0),
            converged=False,
            reverse_path_frame=_reverse_path_frame(),
        )
    for threshold in (True, Decimal("NaN"), math.inf):
        with pytest.raises(ValidationError, match="números finitos"):
            ReverseStressResult(
                target_name="capital_floor",
                metric="ecl",
                threshold=threshold,
                direction="at_least",
                severity=1.0,
                metric_value=25.0,
                iterations=0,
                bracket=(0.0, 5.0),
                converged=False,
                reverse_path_frame=_reverse_path_frame(),
            )
    with pytest.raises(ValidationError, match="bracket"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=6.0,
            metric_value=25.0,
            iterations=0,
            bracket=(0.0, 5.0),
            converged=False,
            reverse_path_frame=_reverse_path_frame(),
        )


def test_stress_result_ct2_tidy_term_structure_none_y_exports() -> None:
    """``StressResult`` cumple CT-2 y expone DTOs vía ``nikodym.stress``."""
    scenario_frame = _scenario_frame()
    term = _term_structure_frame()
    impact = _impact_frame()
    result = _result(
        stress_scenario_frame=scenario_frame,
        stress_term_structure_frame=term,
        stress_impact_frame=impact,
    )

    scenario_frame.loc[0, "applied_shock"] = 99.0
    term.loc["id-1|1", "pd_marginal_stress"] = 99.0
    impact.loc[0, "value_stress"] = 99.0

    observed_scenarios = result.scenarios()
    observed_term = result.term_structure()
    observed_impact = result.tidy()
    assert observed_term is not None
    assert result.stress_scenario_frame is not result.stress_scenario_frame
    assert result.stress_term_structure_frame is not result.stress_term_structure_frame
    assert result.stress_impact_frame is not result.stress_impact_frame
    assert_frame_equal(result.stress_scenario_frame, _normalized_scenario_frame())
    assert_frame_equal(result.stress_term_structure_frame, _normalized_term_structure_frame())
    assert_frame_equal(result.stress_impact_frame, _normalized_impact_frame())
    assert_frame_equal(observed_scenarios, _normalized_scenario_frame())
    assert_frame_equal(observed_term, _normalized_term_structure_frame())
    assert_frame_equal(observed_impact, _normalized_impact_frame())
    assert tuple(observed_scenarios.columns) == _SCENARIO_COLUMNS
    assert tuple(observed_term.columns) == _TERM_COLUMNS
    assert tuple(observed_impact.columns) == _IMPACT_COLUMNS

    observed_scenarios.loc[0, "applied_shock"] = 77.0
    observed_term.loc["id-1|2", "pd_cumulative_stress"] = 77.0
    observed_impact.loc[0, "value_stress"] = 77.0
    assert_frame_equal(result.scenarios(), _normalized_scenario_frame())
    assert_frame_equal(result.term_structure(), _normalized_term_structure_frame())
    assert_frame_equal(result.tidy(), _normalized_impact_frame())

    assert inspect.signature(StressResult.term_structure).return_annotation == (
        "pandas.DataFrame | None"
    )
    assert inspect.signature(StressResult.scenarios).return_annotation == "pandas.DataFrame"
    assert inspect.signature(StressResult.tidy).return_annotation == "pandas.DataFrame"
    optional_adjustment = _result(
        stress_term_structure_frame=_term_structure_frame(
            satellite_adjustment_base=[None, 0.10, -0.20]
        )
    )
    assert optional_adjustment.term_structure() is not None
    optional_numeric_missing = _term_structure_frame()
    optional_numeric_missing["lgd_base"] = pd.Series(
        [None, 0.40, None],
        index=optional_numeric_missing.index,
    )
    optional_numeric_missing["lgd_stress"] = pd.Series(
        [None, 0.45, None],
        index=optional_numeric_missing.index,
    )
    optional_missing_result = _result(stress_term_structure_frame=optional_numeric_missing)
    observed_optional_term = optional_missing_result.term_structure()
    assert observed_optional_term is not None
    assert observed_optional_term["lgd_base"].tolist() == [None, 0.40, None]
    assert observed_optional_term["lgd_stress"].tolist() == [None, 0.45, None]

    optional_impact_missing = _impact_frame()
    optional_impact_missing["relative_delta"] = pd.Series(
        [0.20, None, 0.50],
        index=optional_impact_missing.index,
    )
    optional_impact_missing["period"] = pd.Series(
        [1, None, 1],
        index=optional_impact_missing.index,
    )
    optional_impact_result = _result(stress_impact_frame=optional_impact_missing)
    observed_optional_impact = optional_impact_result.tidy()
    assert observed_optional_impact["relative_delta"].tolist() == [0.20, None, 0.50]
    assert observed_optional_impact["period"].tolist() == [1.0, None, 1.0]
    optional_impact_pd_na = _impact_frame()
    optional_impact_pd_na["relative_delta"] = pd.Series(
        [0.20, pd.NA, 0.50],
        dtype=object,
        index=optional_impact_pd_na.index,
    )
    optional_pd_na_result = _result(stress_impact_frame=optional_impact_pd_na)
    assert optional_pd_na_result.tidy()["relative_delta"].tolist() == [0.20, None, 0.50]

    optional_curve_keys = _result(
        stress_term_structure_frame=_term_structure_frame(
            segment=[None, None, None],
            partition=[None, None, None],
        )
    )
    assert optional_curve_keys.term_structure() is not None

    diagnostic = _result(
        scenario_results=(
            _scenario_result(stressed_macro_frame=None, stressed_term_structure_frame=None),
        ),
        publish_stressed_term_structure=False,
        stress_term_structure_frame=None,
        diagnostics=_diagnostics(scenario_count=1),
    )
    assert diagnostic.term_structure() is None
    assert_frame_equal(diagnostic.tidy(), _normalized_impact_frame())

    with pytest.raises(ValidationError, match="publish_stressed_term_structure=True"):
        _result(stress_term_structure_frame=None)
    with pytest.raises(ValidationError, match="publish_stressed_term_structure=False"):
        _result(publish_stressed_term_structure=False)
    with pytest.raises(ValidationError, match="scenario_results"):
        _result(
            scenario_results=(
                _scenario_result(stressed_macro_frame=None, stressed_term_structure_frame=None),
            ),
            stress_term_structure_frame=_term_structure_frame(),
            diagnostics=_diagnostics(scenario_count=1),
        )
    with pytest.raises(ValidationError, match="scenario_results"):
        _result(
            publish_stressed_term_structure=False,
            stress_term_structure_frame=None,
            diagnostics=_diagnostics(scenario_count=1),
        )

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card()
    with pytest.raises(ValidationError):
        _result(extra="no permitido")
    with pytest.raises(ValidationError, match="scenario_count"):
        _result(diagnostics=_diagnostics(scenario_count=0))
    sensitivity_result = StressSensitivityResult(
        sweep_name="grid",
        factor="unemployment",
        severity_grid=(0.0, 1.0),
        sensitivity_frame=_impact_frame(
            scenario_kind=["sensitivity", "sensitivity", "sensitivity"]
        ),
        baseline_metric_frame=_baseline_metric_frame(),
        monotonicity_flag="increasing",
    )
    with pytest.raises(ValidationError, match="sensitivity_count"):
        _result(
            sensitivity_results=(sensitivity_result,),
            diagnostics=_diagnostics(scenario_count=1, sensitivity_count=0),
        )
    reverse_result = ReverseStressResult(
        target_name="capital_floor",
        metric="ecl",
        threshold=25.0,
        direction="at_least",
        severity=1.25,
        metric_value=25.0,
        iterations=1,
        bracket=(0.0, 5.0),
        converged=True,
        reverse_path_frame=_reverse_path_frame(),
    )
    with pytest.raises(ValidationError, match="reverse_count"):
        _result(
            reverse_results=(reverse_result,),
            diagnostics=_diagnostics(scenario_count=1, reverse_count=0),
        )

    fake_term = _result(stress_term_structure_frame=FakeTermStructureFrame())
    with pytest.raises(StressOutputError, match=r"pandas\.DataFrame"):
        fake_term.term_structure()
    fake_scenario = _result(stress_scenario_frame=FakeScenarioFrame())
    with pytest.raises(StressOutputError, match=r"pandas\.DataFrame"):
        fake_scenario.scenarios()
    fake_impact = _result(stress_impact_frame=FakeImpactFrame())
    with pytest.raises(StressOutputError, match=r"pandas\.DataFrame"):
        fake_impact.tidy()

    assert stress_pkg.StressResult is StressResult
    assert "StressResult" in stress_results.__all__


@pytest.mark.parametrize(
    ("frame_kind", "updates", "message"),
    [
        (
            "stress_scenario",
            {"macro_variable": [None, "unemployment", "gdp"]},
            "macro_variable",
        ),
        (
            "stress_scenario",
            {"operation": ["multiply", "additive", "additive"]},
            "operation",
        ),
        (
            "stress_scenario",
            {"period": [0, 2, 3]},
            "period debe ser mayor",
        ),
        (
            "stress_scenario",
            {"source": ["sin_fuente", "user", "user"]},
            "source",
        ),
        ("scenario", {"scenario": ["Average", "severe_downturn", "severe_downturn"]}, "mean"),
        ("scenario", {"scenario": [None, "severe_downturn", "severe_downturn"]}, "scenario"),
        ("scenario", {"macro_variable": [None, "unemployment", "gdp"]}, "macro_variable"),
        ("scenario", {"period": [0, 2, 3]}, "period debe ser mayor"),
        ("scenario", {"warning_codes": ["WARN", (), ()]}, "warning_codes"),
        ("scenario", {"warning_codes": [(1,), (), ()]}, "contener textos"),
        ("scenario", {"projected_value": [math.nan, 2.5, 1.0]}, "NaN"),
        ("scenario", {"is_reasonable_supportable": [1, True, True]}, "booleano"),
        ("term", {"scenario_kind": ["otro", "severe", "severe"]}, "scenario_kind"),
        ("term", {"period": [0, 2, 3]}, "period debe ser mayor"),
        ("term", {"period": [1, 1, 3]}, "period debe ser contiguo"),
        ("term", {"period": [2, 3, 4]}, "period debe ser contiguo"),
        ("term", {"period": [1, 3, 4]}, "period debe ser contiguo"),
        ("term", {"time_value": [-1.0, 2.0, 3.0]}, "time_value"),
        ("term", {"source_model": [None, "survival", "survival"]}, "source_model"),
        ("term", {"source_model": [np.datetime64("NaT"), "survival", "survival"]}, "NaN"),
        ("term", {"row_id": [(None,), "id-1", "id-1"]}, "row_id"),
        ("term", {"row_id": [np.array([1]), "id-1", "id-1"]}, "row_id"),
        ("term", {"segment": [{"bad": None}, "retail", "retail"]}, "segment"),
        ("term", {"partition": [frozenset({None}), None, None]}, "partition"),
        ("term", {"macro_variable_set": [None, ("unemployment",), ("gdp",)]}, "macro_variable_set"),
        ("term", {"macro_variable_set": [(), ("unemployment",), ("gdp",)]}, "macro_variable_set"),
        (
            "term",
            {"macro_variable_set": [("unemployment", None), ("unemployment",), ("gdp",)]},
            "macro_variable_set",
        ),
        ("term", {"macro_variable_set": [(1,), ("unemployment",), ("gdp",)]}, "macro_variable_set"),
        (
            "term",
            {"macro_variable_set": [("",), ("unemployment",), ("gdp",)]},
            "macro_variable_set",
        ),
        (
            "term",
            {"macro_variable_set": [("unemployment", {None: "x"}), ("unemployment",), ("gdp",)]},
            "macro_variable_set",
        ),
        (
            "term",
            {"macro_variable_set": [("unemployment", {"x": None}), ("unemployment",), ("gdp",)]},
            "macro_variable_set",
        ),
        (
            "term",
            {"macro_variable_set": [("unemployment", pd.NA), ("unemployment",), ("gdp",)]},
            "NaN",
        ),
        (
            "term",
            {
                "macro_variable_set": [
                    ("unemployment", {pd.NA: "x"}),
                    ("unemployment",),
                    ("gdp",),
                ]
            },
            "NaN",
        ),
        (
            "term",
            {
                "macro_variable_set": [
                    ("unemployment", {math.inf: "x"}),
                    ("unemployment",),
                    ("gdp",),
                ]
            },
            "NaN",
        ),
        (
            "term",
            {"macro_variable_set": [("unemployment", {"x": pd.NA}), ("unemployment",), ("gdp",)]},
            "NaN",
        ),
        ("term", {"pd_basis": [None, "pit", "pit"]}, "pd_basis"),
        ("term", {"pd_basis": [" ", "pit", "pit"]}, "pd_basis"),
        ("term", {"pd_basis": ["through-cycle", "pit", "pit"]}, "pd_basis debe ser pit"),
        ("term", {"hazard_stress": [1.20, 0.20, 0.125]}, r"\[0, 1\]"),
        ("term", {"basis_state": ["otro", "blended", "ttc"]}, "basis_state"),
        (
            "term",
            {"pd_marginal_stress": [0.10, 0.10, 0.09]},
            "survival_stress",
        ),
        ("term", {"survival_stress": [0.85, 0.72, 0.63]}, "1 - survival_stress"),
        (
            "term",
            {
                "survival_stress": [0.90, 0.80, 0.70],
                "pd_cumulative_stress": [0.10, 0.20, 0.30],
            },
            r"survival_stress\(t-1\)",
        ),
        (
            "term",
            {
                "survival_stress": [0.90, 0.95, 0.70],
                "hazard_stress": [0.10, 0.05, 0.2631578947368421],
                "pd_marginal_stress": [0.10, 0.045, 0.25],
                "pd_cumulative_stress": [0.10, 0.05, 0.30],
            },
            "no puede decrecer",
        ),
        ("term", {"satellite_adjustment_stress": [0.0, "malo", 0.0]}, "satellite"),
        ("impact", {"metric": ["auc", "ecl", "loss"]}, "metric"),
        ("impact", {"group_key": [None, "segment=retail", "segment=retail"]}, "group_key"),
        (
            "impact",
            {
                "metric": ["pd_marginal", "loss", "ecl"],
                "value_stress": [1.20, 0.0, 15.0],
                "absolute_delta": [1.10, 0.0, 5.0],
                "relative_delta": [11.0, None, 0.50],
            },
            r"\[0, 1\]",
        ),
        (
            "impact",
            {
                "metric": ["ecl", "loss", "ratio"],
                "value_base": [10.0, 0.0, 1.0],
                "value_stress": [-1.0, 0.0, 1.0],
                "absolute_delta": [-11.0, 0.0, 0.0],
                "relative_delta": [-1.10, None, 0.0],
            },
            "mayores o iguales",
        ),
        ("impact", {"absolute_delta": [4.0, 0.0, 5.0]}, "absolute_delta"),
        ("impact", {"relative_delta": [0.20, 0.1, 0.5]}, "relative_delta"),
        ("impact", {"period": [0, None, 1]}, "period debe ser mayor"),
        ("impact", {"period": [True, None, 1]}, "period debe ser entero"),
        ("impact", {"period": [1.5, None, 1]}, "period debe ser entero"),
        ("impact", {"period": ["uno", None, 1]}, "period debe ser entero"),
        (
            "impact",
            {"engine_source": ["manual", "forward_only", "ecl_engine"]},
            "engine_source",
        ),
        ("reverse", {"target_name": [None, "capital_floor"]}, "target_name"),
        ("reverse", {"iteration": [-1, 1]}, "iteration"),
        ("reverse", {"mid": [6.0, 1.25]}, "mid"),
        ("reverse", {"decision": ["move_lo", "stop"]}, "decision"),
    ],
)
def test_stress_results_valida_frames_sdd21(
    frame_kind: str,
    updates: dict[str, Any],
    message: str,
) -> None:
    """Los frames publicados rechazan columnas/valores fuera del contrato SDD-21 §6."""
    frame = _frame_for_kind(frame_kind, updates)
    if frame_kind == "stress_scenario":
        with pytest.raises(ValidationError, match=message):
            _result(stress_scenario_frame=frame)
    elif frame_kind == "scenario":
        with pytest.raises(ValidationError, match=message):
            _scenario_result(stressed_macro_frame=frame)
    elif frame_kind == "term":
        with pytest.raises(ValidationError, match=message):
            _result(stress_term_structure_frame=frame)
    elif frame_kind == "impact":
        with pytest.raises(ValidationError, match=message):
            _result(stress_impact_frame=frame)
    else:
        with pytest.raises(ValidationError, match=message):
            ReverseStressResult(
                target_name="capital_floor",
                metric="ecl",
                threshold=25.0,
                direction="at_least",
                severity=1.25,
                metric_value=25.0,
                iterations=1,
                bracket=(0.0, 5.0),
                converged=True,
                reverse_path_frame=frame,
            )


@pytest.mark.parametrize("periods", ([2, 3, 4], [1, 3, 4]))
def test_stress_scenario_result_exige_term_structure_contigua(periods: list[int]) -> None:
    """El DTO por escenario también rechaza horizontes lifetime faltantes."""
    with pytest.raises(ValidationError, match="period debe ser contiguo"):
        _scenario_result(stressed_term_structure_frame=_term_structure_frame(period=periods))


@pytest.mark.parametrize(
    ("frame_kind", "payload_field", "updates", "message"),
    [
        (
            "stress_scenario",
            "scenario_frame",
            {"stress_scenario": ["otro_downturn", "severe_downturn", "severe_downturn"]},
            "scenario_frame.stress_scenario",
        ),
        (
            "stress_scenario",
            "scenario_frame",
            {"scenario_kind": ["custom", "severe", "severe"]},
            "scenario_frame.scenario_kind",
        ),
        (
            "stress_scenario",
            "scenario_frame",
            {"severity": [2.0, 1.0, 1.0]},
            "scenario_frame.severity",
        ),
        (
            "scenario",
            "stressed_macro_frame",
            {"scenario": ["otro_downturn", "severe_downturn", "severe_downturn"]},
            "stressed_macro_frame.scenario",
        ),
        (
            "term",
            "stressed_term_structure_frame",
            {"stress_scenario": ["otro_downturn", "otro_downturn", "otro_downturn"]},
            "stressed_term_structure_frame.stress_scenario",
        ),
        (
            "term",
            "stressed_term_structure_frame",
            {"scenario_kind": ["custom", "severe", "severe"]},
            "stressed_term_structure_frame.scenario_kind",
        ),
        (
            "term",
            "stressed_term_structure_frame",
            {"severity": [2.0, 2.0, 2.0]},
            "stressed_term_structure_frame.severity",
        ),
        (
            "impact",
            "impact_frame",
            {"stress_scenario": ["otro_downturn", "severe_downturn", "severe_downturn"]},
            "impact_frame.stress_scenario",
        ),
        (
            "impact",
            "impact_frame",
            {"scenario_kind": ["custom", "severe", "severe"]},
            "impact_frame.scenario_kind",
        ),
        (
            "impact",
            "impact_frame",
            {"severity": [2.0, 1.0, 1.0]},
            "impact_frame.severity",
        ),
    ],
)
def test_stress_scenario_result_exige_frames_del_mismo_contexto(
    frame_kind: str,
    payload_field: str,
    updates: dict[str, Any],
    message: str,
) -> None:
    """El DTO por escenario no puede envolver filas de otro escenario/severidad."""
    payload = {payload_field: _frame_for_kind(frame_kind, updates)}
    with pytest.raises(ValidationError, match=message):
        _scenario_result(**payload)


def test_stress_results_validaciones_estructurales() -> None:
    """Errores estructurales cubren columnas exactas, tipos frame y no finitos."""
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _scenario_result(scenario_frame="no es DataFrame")
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _scenario_result(stressed_macro_frame="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(stress_scenario_frame=_scenario_frame().drop(columns=["warning_codes"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _scenario_result(
            stressed_macro_frame=_macro_projection_frame().drop(columns=["warning_codes"])
        )
    bad_projected = _macro_projection_frame()
    bad_projected.loc[1, "projected_value"] = 2.75
    with pytest.raises(ValidationError, match=r"model_value \+ shock_value"):
        _scenario_result(stressed_macro_frame=bad_projected)
    bad_shock = _macro_projection_frame()
    bad_shock.loc[1, "shock_value"] = Decimal("0.25")
    with pytest.raises(ValidationError, match=r"model_value \+ shock_value"):
        _scenario_result(stressed_macro_frame=bad_shock)
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(stress_term_structure_frame=_term_structure_frame().drop(columns=["warning_codes"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(stress_impact_frame=_impact_frame().drop(columns=["warning_codes"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=23,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame().drop(columns=["decision"]),
        )
    with pytest.raises(ValidationError, match="baseline_metric_frame"):
        StressSensitivityResult(
            sweep_name="grid",
            factor="unemployment",
            severity_grid=(0.0, 1.0),
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(payload=[{"bad": [math.inf]}]),
            monotonicity_flag="increasing",
        )
    with pytest.raises(ValidationError, match="baseline_metric_frame"):
        StressSensitivityResult(
            sweep_name="grid",
            factor="unemployment",
            severity_grid=(0.0, 1.0),
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(payload=[{"bad": Decimal("NaN")}]),
            monotonicity_flag="increasing",
        )
    with pytest.raises(ValidationError, match="baseline_metric_frame"):
        StressSensitivityResult(
            sweep_name="grid",
            factor="unemployment",
            severity_grid=(0.0, 1.0),
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(payload=[{"bad": None}]),
            monotonicity_flag="increasing",
        )
    with pytest.raises(ValidationError, match="baseline_metric_frame"):
        StressSensitivityResult(
            sweep_name="grid",
            factor="unemployment",
            severity_grid=(0.0, 1.0),
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(payload=[{"bad": pd.NA}]),
            monotonicity_flag="increasing",
        )
    with pytest.raises(ValidationError, match="baseline_metric_frame"):
        StressSensitivityResult(
            sweep_name="grid",
            factor="unemployment",
            severity_grid=(0.0, 1.0),
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(payload=[{"bad": {math.inf}}]),
            monotonicity_flag="increasing",
        )
    with pytest.raises(ValidationError, match="baseline_metric_frame"):
        StressSensitivityResult(
            sweep_name="grid",
            factor="unemployment",
            severity_grid=(0.0, 1.0),
            sensitivity_frame=_impact_frame(),
            baseline_metric_frame=_baseline_metric_frame(payload=[{"bad": frozenset({pd.NA})}]),
            monotonicity_flag="increasing",
        )
    with pytest.raises(ValidationError, match="relative_delta"):
        _result(stress_impact_frame=_impact_frame(relative_delta=[0.5, 0.1, 0.5]))
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.0,
            metric_value=25.0,
            iterations=0,
            bracket=(0.0, 5.0),
            converged=False,
            reverse_path_frame=None,
        )
    with pytest.raises(ValidationError, match="no puede estar vacío"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.0,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=False,
            reverse_path_frame=_reverse_path_frame().iloc[0:0],
        )
    with pytest.raises(ValidationError, match="threshold"):
        ReverseStressResult(
            target_name="pd_floor",
            metric="pd_marginal",
            threshold=1.2,
            direction="at_least",
            severity=1.0,
            metric_value=1.2,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(
                target_name=["pd_floor", "pd_floor"],
                metric_value=[1.1, 1.2],
                threshold=[1.2, 1.2],
                mid=[0.5, 1.0],
            ),
        )
    with pytest.raises(ValidationError, match=r"\[0, 1\]"):
        ReverseStressResult(
            target_name="pd_floor",
            metric="pd_marginal",
            threshold=0.5,
            direction="at_least",
            severity=1.0,
            metric_value=0.5,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(
                target_name=["pd_floor", "pd_floor"],
                metric_value=[0.6, 1.2],
                threshold=[0.5, 0.5],
            ),
        )
    with pytest.raises(ValidationError, match="threshold"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=-1.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(threshold=[-1.0, -1.0]),
        )
    with pytest.raises(ValidationError, match="fila por iteración"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=2,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(),
        )
    with pytest.raises(ValidationError, match="secuencia"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(iteration=[0, 2]),
        )
    with pytest.raises(ValidationError, match="target_name"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(target_name=["otro", "capital_floor"]),
        )
    with pytest.raises(ValidationError, match="threshold"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(threshold=[25.0, 26.0]),
        )
    with pytest.raises(ValidationError, match="terminar en converged"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(decision=["move_hi", "move_hi"]),
        )
    with pytest.raises(ValidationError, match="no puede terminar en converged"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=False,
            reverse_path_frame=_reverse_path_frame(),
        )
    with pytest.raises(ValidationError, match="severity"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.0,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(),
        )
    with pytest.raises(ValidationError, match="mayores o iguales"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=-0.01,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(),
        )
    with pytest.raises(ValidationError, match="metric_value"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=24.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(),
        )
    with pytest.raises(ValidationError, match="bracket declarado"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(lo=[1.0, 0.0], hi=[4.0, 2.5]),
        )
    with pytest.raises(ValidationError, match="bracket siguiente"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(lo=[0.0, 0.25], hi=[5.0, 2.5]),
        )
    with pytest.raises(ValidationError, match="direction/threshold"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(
                metric_value=[20.0, 25.0],
                decision=["move_hi", "converged"],
            ),
        )
    with pytest.raises(ValidationError, match="direction/threshold"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_most",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(
                metric_value=[20.0, 25.0],
                decision=["move_lo", "converged"],
            ),
        )
    with pytest.raises(ValidationError, match="solo puede marcar converged"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(decision=["converged", "converged"]),
        )
    with pytest.raises(ValidationError, match=r"lo \+ \(hi - lo\) / 2"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=25.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(mid=[2.0, 1.25]),
        )
    with pytest.raises(ValidationError, match="direction=at_least"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.25,
            metric_value=24.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(metric_value=[27.5, 24.0]),
        )
    with pytest.raises(ValidationError, match="direction=at_most"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_most",
            severity=3.75,
            metric_value=26.0,
            iterations=1,
            bracket=(0.0, 5.0),
            converged=True,
            reverse_path_frame=_reverse_path_frame(
                lo=[0.0, 2.5],
                hi=[5.0, 5.0],
                mid=[2.5, 3.75],
                metric_value=[27.5, 26.0],
                decision=["move_lo", "converged"],
            ),
        )
    duplicated_index_term = _term_structure_frame()
    duplicated_index_term.index = pd.Index(["dup", "dup", "dup"], name="curve_id")
    macro_variable_set_position = duplicated_index_term.columns.get_loc("macro_variable_set")
    duplicated_index_term.iat[0, macro_variable_set_position] = ("unemployment", "inflation")
    duplicated_index_result = _result(stress_term_structure_frame=duplicated_index_term)
    observed_term = duplicated_index_result.term_structure()
    assert observed_term is not None
    observed_macro_set = observed_term.iat[0, macro_variable_set_position]
    assert observed_macro_set == ("unemployment", "inflation")
    with pytest.raises(ValidationError, match="bracket"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.0,
            metric_value=25.0,
            iterations=0,
            bracket=(5.0, 0.0),
            converged=False,
            reverse_path_frame=_reverse_path_frame(),
        )
    with pytest.raises(ValidationError, match="iterations"):
        ReverseStressResult(
            target_name="capital_floor",
            metric="ecl",
            threshold=25.0,
            direction="at_least",
            severity=1.0,
            metric_value=25.0,
            iterations=True,
            bracket=(0.0, 5.0),
            converged=False,
            reverse_path_frame=_reverse_path_frame(),
        )


def test_stress_results_import_liviano_y_exports_publicos() -> None:
    """Los DTOs de resultados no se importan hasta pedirlos."""
    code = (
        "import sys;"
        "import nikodym.stress;"
        "assert 'nikodym.stress.results' not in sys.modules;"
        "blocked=[m for m in ('pandas','numpy','scipy','statsmodels','nikodym.provisioning') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'StressResult' in nikodym.stress.__all__;"
        "_=nikodym.stress.StressResult;"
        "assert 'nikodym.stress.results' in sys.modules;"
        "blocked=[m for m in ('pandas','numpy','scipy','statsmodels','nikodym.provisioning') "
        "if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert stress_pkg.StressCard is StressCard
    assert stress_results.StressDiagnostics is StressDiagnostics
    assert "StressScenarioResult" in stress_results.__all__
    assert "StressSensitivityResult" in stress_results.__all__
    assert "ReverseStressResult" in stress_results.__all__


def _frame_for_kind(frame_kind: str, updates: dict[str, Any]) -> pd.DataFrame:
    factories = {
        "impact": _impact_frame,
        "reverse": _reverse_path_frame,
        "scenario": _macro_projection_frame,
        "stress_scenario": _scenario_frame,
        "term": _term_structure_frame,
    }
    return factories[frame_kind](**updates)


def _scenario_result(
    *,
    scenario_name: str = "severe_downturn",
    scenario_kind: str = "severe",
    severity: Any = 1.0,
    scenario_frame: Any = _DEFAULT,
    stressed_macro_frame: Any = _DEFAULT,
    stressed_term_structure_frame: Any = _DEFAULT,
    impact_frame: Any = _DEFAULT,
    warning_codes: tuple[str, ...] = (),
    extra: object | None = None,
) -> StressScenarioResult:
    payload: dict[str, Any] = {
        "scenario_name": scenario_name,
        "scenario_kind": scenario_kind,
        "severity": severity,
        "scenario_frame": _scenario_frame() if scenario_frame is _DEFAULT else scenario_frame,
        "stressed_macro_frame": _macro_projection_frame()
        if stressed_macro_frame is _DEFAULT
        else stressed_macro_frame,
        "stressed_term_structure_frame": _term_structure_frame()
        if stressed_term_structure_frame is _DEFAULT
        else stressed_term_structure_frame,
        "impact_frame": _impact_frame() if impact_frame is _DEFAULT else impact_frame,
        "warning_codes": warning_codes,
    }
    if extra is not None:
        payload["extra"] = extra
    return StressScenarioResult(**payload)


def _diagnostics(**updates: Any) -> StressDiagnostics:
    payload: dict[str, Any] = {
        "scenario_count": 1,
        "sensitivity_count": 0,
        "reverse_count": 0,
        "falta_dato_codes": (),
        "warning_codes": (),
        "dependency_versions": {"pandas": "2.3.3"},
    }
    payload.update(updates)
    return StressDiagnostics(**payload)


def _card(**updates: Any) -> StressCard:
    payload: dict[str, Any] = {
        "summary": {"scenario_count": 1, "max_delta": 5.0},
        "metric_sections": {
            "scenario_impacts": {"max_absolute_delta": 5.0},
            "term_structure_summary": {"rows": 3},
        },
        "assumptions": (),
        "limitations": (),
    }
    payload.update(updates)
    return StressCard(**payload)


def _result(
    *,
    scenario_results: tuple[StressScenarioResult, ...] | None = None,
    sensitivity_results: tuple[StressSensitivityResult, ...] = (),
    reverse_results: tuple[ReverseStressResult, ...] = (),
    publish_stressed_term_structure: bool = True,
    stress_scenario_frame: Any = _DEFAULT,
    stress_term_structure_frame: Any = _DEFAULT,
    stress_impact_frame: Any = _DEFAULT,
    diagnostics: StressDiagnostics | None = None,
    card: StressCard | None = None,
    extra: object | None = None,
) -> StressResult:
    payload: dict[str, Any] = {
        "scenario_results": (_scenario_result(),) if scenario_results is None else scenario_results,
        "sensitivity_results": sensitivity_results,
        "reverse_results": reverse_results,
        "publish_stressed_term_structure": publish_stressed_term_structure,
        "stress_scenario_frame": _scenario_frame()
        if stress_scenario_frame is _DEFAULT
        else stress_scenario_frame,
        "stress_term_structure_frame": _term_structure_frame()
        if stress_term_structure_frame is _DEFAULT
        else stress_term_structure_frame,
        "stress_impact_frame": _impact_frame()
        if stress_impact_frame is _DEFAULT
        else stress_impact_frame,
        "diagnostics": _diagnostics() if diagnostics is None else diagnostics,
        "card": _card() if card is None else card,
    }
    if extra is not None:
        payload["extra"] = extra
    return StressResult(**payload)


def _scenario_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "stress_scenario": ["severe_downturn", "severe_downturn", "severe_downturn"],
        "scenario_kind": ["severe", "severe", "severe"],
        "base_forward_scenario": ["severe", "severe", "severe"],
        "severity": [1.0, 1.0, 1.0],
        "macro_variable": ["unemployment", "unemployment", "gdp"],
        "operation": ["additive", "additive", "additive"],
        "shock_value": pd.Series([Decimal("-0"), 0.50, -0.0], dtype=object),
        "applied_shock": [0.0, 0.50, 0.0],
        "period": [1, 2, 3],
        "source": ["user", "user", "user"],
        "warning_codes": [(), ("WARN-STR-1",), ()],
    }
    payload.update(updates)
    return pd.DataFrame(payload)


def _macro_projection_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "scenario": ["severe_downturn", "severe_downturn", "severe_downturn"],
        "scenario_weight": [1.0, 1.0, 1.0],
        "period": [1, 2, 3],
        "time_value": [1.0, 2.0, 3.0],
        "macro_variable": ["unemployment", "unemployment", "gdp"],
        "projected_value": [1.0, 2.5, 1.0],
        "model_value": [1.0, 2.0, 1.0],
        "shock_value": pd.Series([Decimal("-0"), 0.50, -0.0], dtype=object),
        "method": ["arima", "arima", "arima"],
        "model_id": ["macro-1", "macro-1", "macro-1"],
        "is_reasonable_supportable": [True, True, True],
        "warning_codes": [(), ("WARN-STR-1",), None],
    }
    payload.update(updates)
    return pd.DataFrame(payload)


def _term_structure_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "stress_scenario": ["severe_downturn", "severe_downturn", "severe_downturn"],
        "scenario_kind": ["severe", "severe", "severe"],
        "severity": [1.0, 1.0, 1.0],
        "base_forward_scenario": ["severe", "severe", "severe"],
        "row_id": ["id-1", "id-1", "id-1"],
        "segment": ["retail", "retail", "retail"],
        "partition": ["desarrollo", "desarrollo", "desarrollo"],
        "source_model": ["survival", "survival", "survival"],
        "method": ["survival", "survival", "survival"],
        "pd_source": ["survival", "survival", "survival"],
        "period": [1, 2, 3],
        "time_value": [1.0, 2.0, 3.0],
        "macro_variable_set": [("unemployment", "inflation"), ("unemployment",), ("gdp",)],
        "hazard_base": [0.10, 0.20, 0.125],
        "hazard_stress": [0.10, 0.20, 0.125],
        "survival_stress": [0.90, 0.72, 0.63],
        "pd_marginal_base": [0.10, 0.18, 0.09],
        "pd_marginal_stress": [0.10, 0.18, 0.09],
        "pd_cumulative_base": [0.10, 0.28, 0.37],
        "pd_cumulative_stress": [0.10, 0.28, 0.37],
        "lgd_base": [None, None, None],
        "lgd_stress": [None, None, None],
        "pd_basis": ["pit", "pit", "pit"],
        "basis_state": ["pit", "blended", "ttc"],
        "satellite_adjustment_base": [-0.0, 0.10, -0.20],
        "satellite_adjustment_stress": [-0.0, 0.15, -0.25],
        "warning_codes": [(), (), ("WARN-STR-1",)],
    }
    payload.update(updates)
    for column in (
        "hazard_base",
        "lgd_base",
        "lgd_stress",
        "pd_cumulative_base",
        "pd_marginal_base",
        "satellite_adjustment_base",
        "satellite_adjustment_stress",
    ):
        payload[column] = pd.array(payload[column], dtype=object)
    return pd.DataFrame(
        payload,
        index=pd.Index(["id-1|1", "id-1|2", "id-1|3"], name="curve_id"),
    )


def _impact_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "stress_scenario": ["severe_downturn", "severe_downturn", "severe_downturn"],
        "scenario_kind": ["severe", "severe", "severe"],
        "severity": [1.0, 1.0, 1.0],
        "metric": ["pd_marginal", "loss", "ecl"],
        "value_base": [0.10, 0.0, 10.0],
        "value_stress": [0.12, 0.0, 15.0],
        "absolute_delta": [0.02, -0.0, 5.0],
        "relative_delta": [0.20, None, 0.50],
        "group_key": ["segment=retail", "segment=retail", "segment=retail"],
        "period": [1, None, 1],
        "engine_source": ["forward_only", "forward_only", "ecl_engine"],
        "warning_codes": [(), (), ("WARN-STR-1",)],
    }
    payload.update(updates)
    payload["relative_delta"] = pd.Series(payload["relative_delta"], dtype=object)
    payload["period"] = pd.Series(payload["period"], dtype=object)
    return pd.DataFrame(payload)


def _reverse_path_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "target_name": ["capital_floor", "capital_floor"],
        "iteration": [0, 1],
        "lo": [0.0, 0.0],
        "hi": [5.0, 2.5],
        "mid": [2.5, 1.25],
        "metric_value": [27.5, 25.0],
        "threshold": [25.0, 25.0],
        "decision": ["move_hi", "converged"],
    }
    payload.update(updates)
    return pd.DataFrame(payload)


def _baseline_metric_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "metric": ["ecl"],
        "value": pd.Series([Decimal("-0")], dtype=object),
        "payload": [
            {"zero": Decimal("-0"), "nonzero_decimal": Decimal("1.25"), "items": [-0.0, True]}
        ],
    }
    payload.update(updates)
    return pd.DataFrame(payload)


def _normalized_macro_projection_frame() -> pd.DataFrame:
    return _normalize_frame(_macro_projection_frame())


def _normalized_scenario_frame() -> pd.DataFrame:
    return _normalize_frame(_scenario_frame())


def _normalized_term_structure_frame() -> pd.DataFrame:
    return _normalize_frame(_term_structure_frame())


def _normalized_impact_frame() -> pd.DataFrame:
    return _normalize_frame(_impact_frame())


def _normalized_reverse_path_frame() -> pd.DataFrame:
    return _normalize_frame(_reverse_path_frame())


def _normalized_baseline_metric_frame() -> pd.DataFrame:
    return _normalize_frame(_baseline_metric_frame())


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    for column in normalized.select_dtypes(include=["float"]).columns:
        normalized[column] = normalized[column].mask(normalized[column] == 0.0, 0.0)
    for column in normalized.select_dtypes(include=["object"]).columns:
        normalized[column] = normalized[column].astype("object")
        for index in normalized.index:
            normalized.at[index, column] = _normalize_object_cell(normalized.at[index, column])
    return normalized


def _normalize_object_cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value.is_finite() and float(value) == 0.0:
            return 0.0
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value == 0.0:
        return 0.0
    if isinstance(value, dict):
        return {str(key): _normalize_object_cell(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_object_cell(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_object_cell(item) for item in value)
    return value
