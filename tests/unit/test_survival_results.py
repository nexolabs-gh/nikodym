"""Tests de resultados de ``survival``: DTOs puros, copias y CT-2."""

from __future__ import annotations

import inspect
import math
import subprocess
import sys
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, ClassVar, Self

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.survival.results as survival_results
from nikodym.survival.config import (
    AftFamily as ConfigAftFamily,
)
from nikodym.survival.config import (
    DiscreteHazardLink as ConfigDiscreteHazardLink,
)
from nikodym.survival.config import (
    PdSource as ConfigPdSource,
)
from nikodym.survival.config import (
    SurvivalConfig,
)
from nikodym.survival.config import (
    SurvivalMethod as ConfigSurvivalMethod,
)
from nikodym.survival.exceptions import SurvivalTransformError
from nikodym.survival.results import (
    SurvivalCard,
    SurvivalDiagnostics,
    SurvivalResult,
    SurvivalTermRecord,
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
_DEFAULT = object()


class DummySurvivalModel:
    """Modelo mínimo compatible con ``BaseSurvivalModel`` para envolver resultados."""

    config_cls: ClassVar[type[SurvivalConfig]] = SurvivalConfig

    def fit(
        self,
        frame: pd.DataFrame,
        *,
        duration_col: str,
        event_col: str,
        covariate_cols: tuple[str, ...] = (),
        pd_frame: pd.DataFrame | None = None,
        audit: object | None = None,
    ) -> Self:
        """Ajuste no operativo usado solo para cumplir el protocolo."""
        del frame, duration_col, event_col, covariate_cols, pd_frame, audit
        return self

    def predict_survival(
        self,
        frame: pd.DataFrame,
        *,
        times: Sequence[int | float],
    ) -> pd.DataFrame:
        """Predicción dummy de supervivencia."""
        del frame, times
        return pd.DataFrame()

    def predict_hazard(
        self,
        frame: pd.DataFrame,
        *,
        times: Sequence[int | float],
    ) -> pd.DataFrame:
        """Predicción dummy de hazard."""
        del frame, times
        return pd.DataFrame()

    def term_structure(
        self,
        frame: pd.DataFrame,
        *,
        times: Sequence[int | float],
    ) -> pd.DataFrame:
        """Term-structure dummy."""
        del frame, times
        return pd.DataFrame()


class FakeDataFrame:
    """Frame-like deliberadamente no pandas para probar la defensa de ``term_structure``."""

    columns = pd.Index(_TERM_COLUMNS)

    def copy(self, *, deep: bool) -> FakeDataFrame:
        """Devuelve una copia lógica falsa."""
        assert deep is True
        return self

    def select_dtypes(self, *, include: list[str]) -> pd.DataFrame:
        """Emula la API mínima usada por el DTO."""
        assert include == ["float"]
        return pd.DataFrame()

    def itertuples(self, *, index: bool) -> Any:
        """Entrega una fila válida para pasar la validación duck-typed."""
        assert index is False
        return iter(
            [
                (
                    "loan-001",
                    "retail",
                    "desarrollo",
                    1,
                    1.0,
                    None,
                    1.0,
                    0.0,
                    0.0,
                    "kaplan_meier",
                    "none",
                    None,
                    (),
                )
            ]
        )


def test_survival_term_record_golden_invariantes_y_mapping_warnings() -> None:
    record = _term_record(time_value=-0.0, hazard=-0.0, pd_marginal=-0.0, pd_cumulative=-0.0)

    assert tuple(SurvivalTermRecord.model_fields) == (
        "row_id",
        "period",
        "time_value",
        "survival",
        "hazard",
        "pd_marginal",
        "pd_cumulative",
        "method",
        "pd_source",
        "segment",
        "scenario",
        "warnings",
    )
    assert record.model_dump(mode="json") == {
        "row_id": "loan-001",
        "period": 1,
        "time_value": 0.0,
        "survival": 1.0,
        "hazard": 0.0,
        "pd_marginal": 0.0,
        "pd_cumulative": 0.0,
        "method": "kaplan_meier",
        "pd_source": "none",
        "segment": "retail",
        "scenario": None,
        "warnings": ["FALTA-DATO-SUR-1"],
    }
    assert math.copysign(1.0, record.pd_marginal) == 1.0
    assert "warnings" not in _term_structure_frame().columns
    assert "warning_codes" in _term_structure_frame().columns

    with pytest.raises(ValidationError, match="frozen"):
        record.period = 2
    with pytest.raises(ValidationError):
        _term_record(extra="no permitido")
    with pytest.raises(ValidationError, match="pd_cumulative"):
        _term_record(survival=0.95, pd_cumulative=0.20)
    with pytest.raises(ValidationError, match="mayor o igual a 0"):
        _term_record(pd_marginal=-0.01, survival=0.99, pd_cumulative=0.01)
    with pytest.raises(ValidationError, match=r"\[0, 1\]"):
        _term_record(hazard=1.20)
    with pytest.raises(ValidationError, match="números finitos"):
        _term_record(hazard=math.inf)
    with pytest.raises(ValidationError, match="time_value"):
        _term_record(time_value=-0.01)


def test_survival_diagnostics_golden_copias_y_normalizacion() -> None:
    schoenfeld = {
        "zeta": {"p_value": -0.0, "stat": math.inf},
        "alfa": ("ok", -0.0),
    }
    fit_statistics: dict[str, Any] = {
        "ll": -0.0,
        "aic": math.inf,
        "n_iter": 7,
        "status": "converged",
        "flag": True,
        "scale": Decimal("-0"),
        "decimal_nan": Decimal("NaN"),
        "np_zero": np.float32(-0.0),
        "np_inf": np.float32(math.inf),
        "raw": object(),
        "none": None,
    }
    diagnostics = _diagnostics(
        max_observed_time=-0.0,
        schoenfeld_test=schoenfeld,
        fit_statistics=fit_statistics,
    )

    dumped = diagnostics.model_dump(mode="json")
    assert dumped["max_observed_time"] == 0.0
    assert dumped["schoenfeld_test"] == {
        "zeta": {"p_value": 0.0, "stat": None},
        "alfa": ["ok", 0.0],
    }
    assert dumped["fit_statistics"] == {
        "ll": 0.0,
        "aic": None,
        "n_iter": 7,
        "status": "converged",
        "flag": "True",
        "scale": 0.0,
        "decimal_nan": None,
        "np_zero": 0.0,
        "np_inf": None,
        "raw": str(fit_statistics["raw"]),
        "none": None,
    }
    assert _diagnostics(fit_statistics=None).fit_statistics == {}

    schoenfeld["zeta"]["p_value"] = 99.0
    fit_statistics["ll"] = 99.0
    diagnostics.schoenfeld_test["zeta"]["p_value"] = 88.0
    diagnostics.fit_statistics["ll"] = 88.0

    assert diagnostics.schoenfeld_test["zeta"]["p_value"] == 0.0
    assert diagnostics.fit_statistics["ll"] == 0.0

    with pytest.raises(ValidationError, match="frozen"):
        diagnostics.n_rows = 99
    with pytest.raises(ValidationError):
        _diagnostics(extra="no permitido")
    with pytest.raises(ValidationError, match="max_observed_time"):
        _diagnostics(max_observed_time=-0.01)
    with pytest.raises(ValidationError, match="n_events \\+ n_censored"):
        _diagnostics(n_rows=2, n_events=2, n_censored=1)
    with pytest.raises(ValidationError):
        _diagnostics(schoenfeld_test=["no permitido"])
    with pytest.raises(ValidationError):
        _diagnostics(fit_statistics=["no permitido"])


def test_survival_card_golden_ct2_orden_copias_y_defaults() -> None:
    metric_sections: dict[str, Any] = {
        "person_period": {"rows": 20, "delta": -0.0},
        "term_structure_summary": {"last_pd_cumulative": 0.10},
        "custom": {"nested": {"b": 2, "a": 1}, "serie": [math.nan, -0.0]},
        "schoenfeld": {"global_p_value": 0.42},
        "km_greenwood": {"variance": math.inf},
    }
    dependency_versions = {"pandas": "2.3.3", "lifelines": "0.30.0"}
    card = _card(metric_sections=metric_sections, dependency_versions=dependency_versions)

    assert tuple(SurvivalCard.model_fields) == (
        "method",
        "pd_source",
        "duration_col",
        "event_col",
        "time_unit",
        "n_rows",
        "n_events",
        "n_periods",
        "output_columns",
        "diagnostics",
        "dependency_versions",
        "falta_dato",
        "metric_sections",
    )
    dumped_sections = card.model_dump(mode="json")["metric_sections"]
    assert list(dumped_sections) == [
        "person_period",
        "term_structure_summary",
        "custom",
        "schoenfeld",
        "km_greenwood",
    ]
    assert list(dumped_sections["custom"]["nested"]) == ["b", "a"]
    assert dumped_sections["person_period"]["delta"] == 0.0
    assert dumped_sections["custom"]["serie"] == [None, 0.0]
    assert dumped_sections["km_greenwood"]["variance"] is None
    assert _card().metric_sections == {
        "term_structure_summary": {},
        "schoenfeld": {},
        "km_greenwood": {},
        "person_period": {},
    }
    assert _card(metric_sections=None).metric_sections == {
        "term_structure_summary": {},
        "schoenfeld": {},
        "km_greenwood": {},
        "person_period": {},
    }
    assert list(_card(metric_sections={"custom": {"ok": True}}).metric_sections) == [
        "custom",
        "term_structure_summary",
        "schoenfeld",
        "km_greenwood",
        "person_period",
    ]
    assert list(card.dependency_versions) == ["pandas", "lifelines"]

    metric_sections["person_period"]["rows"] = 99
    dependency_versions["pandas"] = "mutado"
    card.metric_sections["person_period"]["rows"] = 88
    card.dependency_versions["pandas"] = "mutado"

    assert card.metric_sections["person_period"]["rows"] == 20
    assert card.dependency_versions["pandas"] == "2.3.3"

    with pytest.raises(ValidationError, match="frozen"):
        card.n_periods = 99
    with pytest.raises(ValidationError):
        _card(extra="no permitido")
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])
    with pytest.raises(ValidationError):
        _card(dependency_versions=["no permitido"])
    with pytest.raises(ValidationError, match="no pueden estar vacías"):
        _card(duration_col=" ")
    with pytest.raises(ValidationError, match="n_events"):
        _card(n_rows=1, n_events=2)
    with pytest.raises(ValidationError, match=r"diagnostics\.method"):
        _card(method="aft", diagnostics=_diagnostics(method="cox_ph", aft_family="weibull"))
    with pytest.raises(ValidationError, match="conteos"):
        _card(n_rows=10, diagnostics=_diagnostics(n_rows=11))


def test_survival_result_envuelve_dataframes_term_structure_y_copias() -> None:
    term_structure = _term_structure_frame()
    curves = _survival_curve_frame()
    hazards = _hazard_frame()
    result = _result(
        term_structure_frame=term_structure,
        survival_curve_frame=curves,
        hazard_frame=hazards,
    )

    term_structure.loc["loan-001|1", "pd_marginal"] = 99.0
    curves.loc["loan-001|1", "survival"] = 99.0
    hazards.loc["loan-001|1", "hazard"] = 99.0

    observed_term = result.term_structure()
    assert observed_term is not None
    assert result.term_structure_frame is not result.term_structure_frame
    assert result.survival_curve_frame is not result.survival_curve_frame
    assert result.hazard_frame is not result.hazard_frame
    assert_frame_equal(observed_term, _normalized_term_structure_frame())
    assert_frame_equal(result.term_structure_frame, _normalized_term_structure_frame())
    assert_frame_equal(result.survival_curve_frame, _normalized_survival_curve_frame())
    assert_frame_equal(result.hazard_frame, _normalized_hazard_frame())
    assert tuple(observed_term.columns) == _TERM_COLUMNS
    assert math.copysign(1.0, observed_term.loc["loan-001|1", "pd_marginal"]) == 1.0
    assert observed_term.loc["loan-001|2", "pd_cumulative"] == pytest.approx(0.10)
    assert observed_term.loc["loan-001|2", "pd_marginal"] >= 0.0
    assert (
        observed_term.loc["loan-001|2", "survival"]
        <= observed_term.loc[
            "loan-001|1",
            "survival",
        ]
    )

    observed_term.loc["loan-001|2", "pd_cumulative"] = 77.0
    assert_frame_equal(result.term_structure(), _normalized_term_structure_frame())
    assert result.diagnostics == _diagnostics()
    assert result.card == _card()
    assert isinstance(result.estimator, DummySurvivalModel)

    annotation = inspect.signature(SurvivalResult.term_structure).return_annotation
    assert annotation == "pandas.DataFrame | None"

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card(n_periods=3)
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_survival_result_valida_dataframes_y_consistencia() -> None:
    diagnostic_result = _result(term_structure_frame=None, card=_card(output_columns=()))
    assert diagnostic_result.term_structure() is None

    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(term_structure_frame="no es DataFrame")
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(survival_curve_frame="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(term_structure_frame=_term_structure_frame().drop(columns=["warning_codes"]))
    with pytest.raises(ValidationError, match="pd_cumulative"):
        _result(term_structure_frame=_term_structure_frame(pd_cumulative=[0.0, 0.30]))
    with pytest.raises(ValidationError, match="pd_marginal"):
        _result(term_structure_frame=_term_structure_frame(pd_marginal=[0.0, -0.01]))
    with pytest.raises(ValidationError, match="survival no puede aumentar"):
        _result(
            term_structure_frame=_term_structure_frame(
                survival=[0.90, 0.95],
                pd_cumulative=[0.10, 0.05],
            )
        )
    with pytest.raises(ValidationError, match="period debe crecer"):
        _result(term_structure_frame=_term_structure_frame(period=[1, 1]))
    with pytest.raises(ValidationError, match="period debe ser entero"):
        _result(term_structure_frame=_term_structure_frame(period=[1.0, 2.0]))
    with pytest.raises(ValidationError, match="period debe ser mayor"):
        _result(term_structure_frame=_term_structure_frame(period=[0, 1]))
    with pytest.raises(ValidationError, match="hazard debe ser None"):
        _result(term_structure_frame=_term_structure_frame(hazard=[None, "malo"]))
    with pytest.raises(ValidationError, match="time_value"):
        _result(term_structure_frame=_term_structure_frame(time_value=[1.0, -2.0]))
    with pytest.raises(ValidationError, match=r"card\.diagnostics"):
        _result(card=_card(diagnostics=_diagnostics(warnings=("otra",))))
    with pytest.raises(ValidationError, match="output_columns"):
        _result(card=_card(output_columns=("row_id",)))

    fake = FakeDataFrame()
    fake_result = _result(term_structure_frame=fake)
    with pytest.raises(SurvivalTransformError, match=r"pandas\.DataFrame"):
        fake_result.term_structure()


def test_survival_results_import_liviano_y_exports_publicos() -> None:
    code = (
        "import sys;"
        "import nikodym.survival.results;"
        "blocked=[m for m in ('pandas','lifelines','statsmodels','sksurv') if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert survival_results.SurvivalMethod == ConfigSurvivalMethod
    assert survival_results.DiscreteHazardLink == ConfigDiscreteHazardLink
    assert survival_results.PdSource == ConfigPdSource
    assert survival_results.AftFamily == ConfigAftFamily
    assert "SurvivalTermRecord" in survival_results.__all__
    assert "SurvivalDiagnostics" in survival_results.__all__
    assert "SurvivalCard" in survival_results.__all__
    assert "SurvivalResult" in survival_results.__all__


def _term_record(**updates: Any) -> SurvivalTermRecord:
    payload: dict[str, Any] = {
        "row_id": "loan-001",
        "period": 1,
        "time_value": 1.0,
        "survival": 1.0,
        "hazard": None,
        "pd_marginal": 0.0,
        "pd_cumulative": 0.0,
        "method": "kaplan_meier",
        "pd_source": "none",
        "segment": "retail",
        "scenario": None,
        "warnings": ("FALTA-DATO-SUR-1",),
    }
    payload.update(updates)
    return SurvivalTermRecord(**payload)


def _diagnostics(**updates: Any) -> SurvivalDiagnostics:
    payload: dict[str, Any] = {
        "method": "discrete_hazard",
        "n_rows": 2,
        "n_events": 1,
        "n_censored": 1,
        "max_observed_time": 2.0,
        "link": "logit",
        "schoenfeld_test": None,
        "aft_family": None,
        "fit_statistics": {"log_likelihood": -12.5, "n_params": 3, "status": "ok"},
        "warnings": (),
    }
    payload.update(updates)
    return SurvivalDiagnostics(**payload)


def _card(**updates: Any) -> SurvivalCard:
    payload: dict[str, Any] = {
        "method": "discrete_hazard",
        "pd_source": "model_raw",
        "duration_col": "months_to_default",
        "event_col": "default_flag",
        "time_unit": "month",
        "n_rows": 2,
        "n_events": 1,
        "n_periods": 2,
        "output_columns": _TERM_COLUMNS,
        "diagnostics": _diagnostics(),
        "dependency_versions": {"pandas": "2.3.3", "statsmodels": "0.14.6"},
        "falta_dato": (),
    }
    payload.update(updates)
    return SurvivalCard(**payload)


def _result(
    *,
    estimator: Any | None = None,
    term_structure_frame: Any = _DEFAULT,
    survival_curve_frame: Any = _DEFAULT,
    hazard_frame: Any = _DEFAULT,
    diagnostics: SurvivalDiagnostics | None = None,
    card: SurvivalCard | None = None,
    extra: object | None = None,
) -> SurvivalResult:
    payload: dict[str, Any] = {
        "estimator": DummySurvivalModel() if estimator is None else estimator,
        "term_structure_frame": _term_structure_frame()
        if term_structure_frame is _DEFAULT
        else term_structure_frame,
        "survival_curve_frame": _survival_curve_frame()
        if survival_curve_frame is _DEFAULT
        else survival_curve_frame,
        "hazard_frame": _hazard_frame() if hazard_frame is _DEFAULT else hazard_frame,
        "diagnostics": _diagnostics() if diagnostics is None else diagnostics,
        "card": _card() if card is None else card,
    }
    if extra is not None:
        payload["extra"] = extra
    return SurvivalResult(**payload)


def _term_structure_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "row_id": ["loan-001", "loan-001"],
        "segment": ["retail", "retail"],
        "partition": ["desarrollo", "desarrollo"],
        "period": [1, 2],
        "time_value": [1.0, 2.0],
        "hazard": [-0.0, 0.10],
        "survival": [1.0, 0.90],
        "pd_marginal": [-0.0, 0.10],
        "pd_cumulative": [-0.0, 0.10],
        "method": ["discrete_hazard", "discrete_hazard"],
        "pd_source": ["model_raw", "model_raw"],
        "scenario": [math.nan, math.nan],
        "warning_codes": [(), ("FALTA-DATO-SUR-1",)],
    }
    payload.update(updates)
    return pd.DataFrame(payload, index=pd.Index(["loan-001|1", "loan-001|2"], name="curve_id"))


def _survival_curve_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "row_id": ["loan-001"],
            "segment": ["retail"],
            "period": [1],
            "time_value": [1.0],
            "survival": [-0.0],
            "greenwood_variance": [0.0125],
        },
        index=pd.Index(["loan-001|1"], name="curve_id"),
    )


def _hazard_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "row_id": ["loan-001"],
            "segment": ["retail"],
            "period": [1],
            "time_value": [1.0],
            "hazard": [-0.0],
            "link": ["logit"],
            "linear_predictor_hazard": [0.0],
        },
        index=pd.Index(["loan-001|1"], name="curve_id"),
    )


def _normalized_term_structure_frame() -> pd.DataFrame:
    return _normalize_frame(_term_structure_frame())


def _normalized_survival_curve_frame() -> pd.DataFrame:
    return _normalize_frame(_survival_curve_frame())


def _normalized_hazard_frame() -> pd.DataFrame:
    return _normalize_frame(_hazard_frame())


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    for column in normalized.select_dtypes(include=["float"]).columns:
        normalized[column] = normalized[column].mask(normalized[column] == 0.0, 0.0)
    return normalized
