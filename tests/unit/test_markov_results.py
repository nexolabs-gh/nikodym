"""Tests de resultados de ``markov``: DTOs puros, copias y CT-2."""

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

import nikodym.markov.results as markov_results
from nikodym.markov.config import (
    EmbeddingPolicy as ConfigEmbeddingPolicy,
)
from nikodym.markov.config import (
    MarkovMethod as ConfigMarkovMethod,
)
from nikodym.markov.config import (
    ProjectionMode as ConfigProjectionMode,
)
from nikodym.markov.exceptions import MarkovTransformError
from nikodym.markov.results import (
    EmbeddingDiagnostics,
    MarkovCard,
    MarkovDiagnostics,
    MarkovResult,
)

_TRANSITION_COLUMNS: tuple[str, ...] = (
    "period",
    "from_state",
    "to_state",
    "probability",
    "count",
    "origin_count",
    "method",
    "segment",
)
_GENERATOR_COLUMNS: tuple[str, ...] = (
    "from_state",
    "to_state",
    "intensity",
    "time_at_risk",
    "transition_count",
    "source",
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


class DummyTransitionMatrixEstimator:
    """Estimador mínimo para envolver ``MarkovResult`` antes de B19.3."""


class NoCopyCandidate:
    """Objeto sin método ``copy`` para cubrir la copia profunda fallback."""

    def __init__(self, value: float) -> None:
        self.value = value


class FakeDataFrame:
    """Frame-like no pandas para probar la defensa de ``term_structure``."""

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
                    "state:A",
                    "retail",
                    "desarrollo",
                    1,
                    1.0,
                    None,
                    0.90,
                    0.10,
                    0.10,
                    "cohort",
                    "markov",
                    None,
                    (),
                )
            ]
        )


def test_embedding_diagnostics_gap_golden_copias_y_normalizacion() -> None:
    generator = np.array([[-0.2, 0.2], [-0.0, -0.0]], dtype=float)
    diagnostics = EmbeddingDiagnostics(
        embedding_status="valid",
        embedding_flags=("principal_log_real",),
        generator_candidate=generator,
        imaginary_norm=-0.0,
        distance_fro=-0.0,
        adjusted=True,
    )

    assert tuple(EmbeddingDiagnostics.model_fields) == (
        "embedding_status",
        "embedding_flags",
        "generator_candidate",
        "imaginary_norm",
        "distance_fro",
        "adjusted",
    )
    assert diagnostics.embedding_status == "valid"
    assert diagnostics.embedding_flags == ("principal_log_real",)
    assert diagnostics.imaginary_norm == 0.0
    assert diagnostics.distance_fro == 0.0
    assert math.copysign(1.0, diagnostics.distance_fro) == 1.0

    generator[0, 0] = 99.0
    observed = diagnostics.generator_candidate
    assert observed is not None
    assert observed[0, 0] == pytest.approx(-0.2)
    observed[0, 0] = 88.0
    assert diagnostics.generator_candidate[0, 0] == pytest.approx(-0.2)

    assert (
        EmbeddingDiagnostics(
            embedding_status="diagnostic", generator_candidate=None
        ).generator_candidate
        is None
    )
    fallback = NoCopyCandidate(0.25)
    fallback_diagnostics = EmbeddingDiagnostics(
        embedding_status="regularized",
        generator_candidate=fallback,
        imaginary_norm=None,
    )
    fallback.value = 99.0
    fallback_observed = fallback_diagnostics.generator_candidate
    assert isinstance(fallback_observed, NoCopyCandidate)
    assert fallback_observed.value == pytest.approx(0.25)

    with pytest.raises(ValidationError, match="frozen"):
        diagnostics.adjusted = False
    with pytest.raises(ValidationError):
        EmbeddingDiagnostics(embedding_status="valid", extra="no permitido")
    with pytest.raises(ValidationError, match="embedding_status"):
        EmbeddingDiagnostics(embedding_status=" ")
    with pytest.raises(ValidationError, match="mayores o iguales"):
        EmbeddingDiagnostics(embedding_status="valid", imaginary_norm=-0.01)
    with pytest.raises(ValidationError, match="números finitos"):
        EmbeddingDiagnostics(embedding_status="valid", distance_fro=math.inf)


def test_markov_diagnostics_golden_copias_normalizacion_y_estados() -> None:
    fit_statistics: dict[str, Any] = {
        "log_likelihood": -0.0,
        "aic": math.inf,
        "n_iter": 7,
        "status": "ok",
        "flag": True,
        "scale": Decimal("-0"),
        "decimal_nan": Decimal("NaN"),
        "np_zero": np.float32(-0.0),
        "np_inf": np.float32(math.inf),
        "raw": object(),
        "none": None,
    }
    diagnostics = _diagnostics(
        stochastic_tol=-0.0,
        generator_tol=-0.0,
        embedding_distance_fro=-0.0,
        fit_statistics=fit_statistics,
    )

    assert tuple(MarkovDiagnostics.model_fields) == (
        "method",
        "projection_mode",
        "states",
        "default_state",
        "absorbing_states",
        "n_entities",
        "n_observations",
        "n_transitions",
        "n_periods",
        "stochastic_tol",
        "generator_tol",
        "embedding_status",
        "embedding_flags",
        "embedding_adjusted",
        "embedding_distance_fro",
        "fit_statistics",
        "warnings",
    )
    assert diagnostics.model_dump(mode="json") == {
        "method": "cohort",
        "projection_mode": "homogeneous",
        "states": ["A", "default"],
        "default_state": "default",
        "absorbing_states": ["default"],
        "n_entities": 2,
        "n_observations": 4,
        "n_transitions": 3,
        "n_periods": 3,
        "stochastic_tol": 0.0,
        "generator_tol": 0.0,
        "embedding_status": "valid",
        "embedding_flags": ["principal_log_real"],
        "embedding_adjusted": False,
        "embedding_distance_fro": 0.0,
        "fit_statistics": {
            "log_likelihood": 0.0,
            "aic": None,
            "n_iter": 7,
            "status": "ok",
            "flag": "True",
            "scale": 0.0,
            "decimal_nan": None,
            "np_zero": 0.0,
            "np_inf": None,
            "raw": str(fit_statistics["raw"]),
            "none": None,
        },
        "warnings": [],
    }

    fit_statistics["log_likelihood"] = 99.0
    diagnostics.fit_statistics["log_likelihood"] = 88.0
    assert diagnostics.fit_statistics["log_likelihood"] == 0.0
    assert _diagnostics(fit_statistics=None).fit_statistics == {}
    assert _diagnostics(embedding_status=None).embedding_status is None

    with pytest.raises(ValidationError, match="frozen"):
        diagnostics.n_periods = 99
    with pytest.raises(ValidationError):
        _diagnostics(extra="no permitido")
    with pytest.raises(ValidationError, match="states no puede contener duplicados"):
        _diagnostics(states=("A", "A", "default"))
    with pytest.raises(ValidationError, match="al menos un estado"):
        _diagnostics(states=())
    with pytest.raises(ValidationError, match="default_state"):
        _diagnostics(default_state=" ")
    with pytest.raises(ValidationError, match="states no puede contener estados vacíos"):
        _diagnostics(states=("A", " ", "default"))
    with pytest.raises(ValidationError, match="absorbing_states no puede contener estados vacíos"):
        _diagnostics(absorbing_states=("default", " "))
    with pytest.raises(ValidationError, match="states debe contener default_state"):
        _diagnostics(default_state="mora")
    with pytest.raises(ValidationError, match="subconjunto"):
        _diagnostics(absorbing_states=("default", "mora"))
    with pytest.raises(ValidationError, match="debe contener default_state"):
        _diagnostics(absorbing_states=())
    with pytest.raises(ValidationError, match="n_transitions"):
        _diagnostics(n_observations=2, n_transitions=2)
    with pytest.raises(ValidationError, match="mayores o iguales"):
        _diagnostics(stochastic_tol=-0.01)
    with pytest.raises(ValidationError, match="números finitos"):
        _diagnostics(generator_tol=math.inf)
    with pytest.raises(ValidationError, match="embedding_status"):
        _diagnostics(embedding_status=" ")
    with pytest.raises(ValidationError):
        _diagnostics(fit_statistics=["no permitido"])


def test_markov_card_golden_ct2_orden_copias_y_defaults() -> None:
    metric_sections: dict[str, Any] = {
        "embedding_diagnostics": {"distance_fro": -0.0},
        "custom": {"serie": [math.nan, -0.0], "tupla": (-0.0,)},
        "transition_matrix_summary": {"rows": 4},
    }
    dependency_versions = {"pandas": "2.3.3", "numpy": "2.4.6", "scipy": "1.18.0"}
    card = _card(metric_sections=metric_sections, dependency_versions=dependency_versions)

    assert tuple(MarkovCard.model_fields) == (
        "method",
        "projection_mode",
        "time_unit",
        "horizon_periods",
        "states",
        "default_state",
        "absorbing_states",
        "output_columns",
        "diagnostics",
        "dependency_versions",
        "falta_dato",
        "metric_sections",
    )
    dumped_sections = card.model_dump(mode="json")["metric_sections"]
    assert list(dumped_sections) == [
        "embedding_diagnostics",
        "custom",
        "transition_matrix_summary",
        "generator_summary",
        "term_structure_summary",
    ]
    assert dumped_sections["embedding_diagnostics"]["distance_fro"] == 0.0
    assert dumped_sections["custom"]["serie"] == [None, 0.0]
    assert dumped_sections["custom"]["tupla"] == [0.0]
    assert _card().metric_sections == {
        "transition_matrix_summary": {},
        "generator_summary": {},
        "embedding_diagnostics": {},
        "term_structure_summary": {},
    }
    assert _card(metric_sections=None).metric_sections == {
        "transition_matrix_summary": {},
        "generator_summary": {},
        "embedding_diagnostics": {},
        "term_structure_summary": {},
    }
    assert list(card.dependency_versions) == ["pandas", "numpy", "scipy"]

    metric_sections["embedding_diagnostics"]["distance_fro"] = 99.0
    dependency_versions["pandas"] = "mutado"
    card.metric_sections["embedding_diagnostics"]["distance_fro"] = 88.0
    card.dependency_versions["pandas"] = "mutado"
    assert card.metric_sections["embedding_diagnostics"]["distance_fro"] == 0.0
    assert card.dependency_versions["pandas"] == "2.3.3"

    with pytest.raises(ValidationError, match="frozen"):
        card.time_unit = "year"
    with pytest.raises(ValidationError):
        _card(extra="no permitido")
    with pytest.raises(ValidationError, match="time_unit"):
        _card(time_unit=" ")
    with pytest.raises(ValidationError, match="horizon_periods"):
        _card(horizon_periods=(1, 1))
    with pytest.raises(ValidationError, match="horizon_periods"):
        _card(horizon_periods=(0,))
    with pytest.raises(ValidationError, match="horizon_periods"):
        _card(horizon_periods=None)
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])
    with pytest.raises(ValidationError):
        _card(dependency_versions=["no permitido"])
    with pytest.raises(ValidationError, match=r"diagnostics\.method"):
        _card(method="duration", diagnostics=_diagnostics(method="cohort"))
    with pytest.raises(ValidationError, match=r"diagnostics\.projection_mode"):
        _card(projection_mode="aalen_johansen")
    with pytest.raises(ValidationError, match=r"diagnostics\.states"):
        _card(states=("A", "B", "default"))
    with pytest.raises(ValidationError, match=r"diagnostics\.default_state"):
        _card(default_state="A", absorbing_states=("A",))
    with pytest.raises(ValidationError, match=r"diagnostics\.absorbing_states"):
        _card(absorbing_states=("A", "default"))


def test_markov_result_envuelve_frames_term_structure_y_copias() -> None:
    transition = _transition_matrix_frame()
    generator = _generator_frame()
    term_structure = _term_structure_frame()
    result = _result(
        transition_matrix_frame=transition,
        generator_frame=generator,
        term_structure_frame=term_structure,
    )

    transition.loc[0, "probability"] = 99.0
    generator.loc[0, "intensity"] = 99.0
    term_structure.loc["state:A|1", "pd_marginal"] = 99.0

    observed_term = result.term_structure()
    assert observed_term is not None
    assert result.transition_matrix_frame is not result.transition_matrix_frame
    assert result.generator_frame is not result.generator_frame
    assert result.term_structure_frame is not result.term_structure_frame
    assert_frame_equal(result.transition_matrix_frame, _normalized_transition_matrix_frame())
    assert_frame_equal(result.generator_frame, _normalized_generator_frame())
    assert_frame_equal(result.term_structure_frame, _normalized_term_structure_frame())
    assert_frame_equal(observed_term, _normalized_term_structure_frame())
    assert tuple(observed_term.columns) == _TERM_COLUMNS
    assert isinstance(result.estimator, DummyTransitionMatrixEstimator)
    assert result.diagnostics == _diagnostics()
    assert result.card == _card()

    by_curve = observed_term.groupby(["row_id", "segment", "partition"], dropna=False)
    for _, curve in by_curve:
        assert np.allclose(curve["pd_cumulative"], 1.0 - curve["survival"])
        assert bool((curve["pd_marginal"] >= 0.0).all())
        assert bool(curve["pd_cumulative"].is_monotonic_increasing)
        assert curve["pd_marginal"].sum() == pytest.approx(curve["pd_cumulative"].iloc[-1])
    assert math.copysign(1.0, observed_term.loc["state:A|1", "pd_marginal"]) == 1.0

    observed_term.loc["state:A|2", "pd_cumulative"] = 77.0
    assert_frame_equal(result.term_structure(), _normalized_term_structure_frame())

    annotation = inspect.signature(MarkovResult.term_structure).return_annotation
    assert annotation == "pandas.DataFrame | None"

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card(horizon_periods=(1,))
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_markov_result_none_diagnostico_y_validaciones() -> None:
    diagnostic_result = _result(term_structure_frame=None, card=_card(output_columns=()))
    assert diagnostic_result.term_structure() is None
    generator_diagnostic = _result(generator_frame=None)
    assert generator_diagnostic.generator_frame is None

    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(transition_matrix_frame="no es DataFrame")
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(generator_frame="no es DataFrame")
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(term_structure_frame="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(transition_matrix_frame=_transition_matrix_frame().drop(columns=["segment"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(generator_frame=_generator_frame().drop(columns=["source"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(term_structure_frame=_term_structure_frame().drop(columns=["warning_codes"]))
    with pytest.raises(ValidationError, match=r"card\.diagnostics"):
        _result(card=_card(diagnostics=_diagnostics(warnings=("otra",))))
    with pytest.raises(ValidationError, match="output_columns"):
        _result(card=_card(output_columns=("row_id",)))

    fake = FakeDataFrame()
    fake_result = _result(term_structure_frame=fake)
    with pytest.raises(MarkovTransformError, match=r"pandas\.DataFrame"):
        fake_result.term_structure()


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"pd_cumulative": [0.10, 0.30, 0.30], "survival": [0.90, 0.70, 0.70]}, "suma"),
        ({"pd_marginal": [0.10, -0.01, 0.21]}, "pd_marginal"),
        (
            {
                "survival": [0.80, 0.90, 0.70],
                "pd_marginal": [0.20, 0.0, 0.10],
                "pd_cumulative": [0.20, 0.10, 0.30],
            },
            "survival no puede aumentar",
        ),
        ({"period": [1, 1, 3]}, "period debe crecer"),
        ({"period": [1.0, 2.0, 3.0]}, "period debe ser entero"),
        ({"period": [0, 1, 2]}, "period debe ser mayor"),
        ({"hazard": [None, "malo", 0.125]}, "hazard debe ser None"),
        ({"time_value": [1.0, -2.0, 3.0]}, "time_value"),
        ({"pd_cumulative": [0.10, 0.20, 1.10], "survival": [0.90, 0.80, -0.10]}, r"\[0, 1\]"),
        ({"survival": [0.85, 0.80, 0.70]}, "pd_cumulative"),
    ],
)
def test_markov_result_valida_invariantes_term_structure(
    updates: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _result(term_structure_frame=_term_structure_frame(**updates))


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"to_state": ["A", "mora", "A", "default"]}, "estados"),
        ({"probability": [0.70, 0.20, 0.0, 1.0]}, "sumar 1"),
        ({"probability": [0.80, 0.20, 0.10, 0.90]}, "fila identidad"),
        ({"probability": [1.20, -0.20, 0.0, 1.0]}, r"\[0, 1\]"),
        ({"count": [8.0, -1.0, 0.0, 2.0]}, "count"),
        ({"origin_count": [10.0, math.inf, 1.0, 1.0]}, "origin_count"),
    ],
)
def test_markov_result_valida_transition_matrix(updates: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _result(transition_matrix_frame=_transition_matrix_frame(**updates))


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"intensity": [0.01, 0.19, 0.0, 0.0]}, "diagonal"),
        ({"intensity": [-0.20, -0.01, 0.0, 0.0]}, "off-diagonal"),
        ({"intensity": [-0.20, 0.30, 0.0, 0.0]}, "sumar 0"),
        ({"intensity": [-0.20, 0.20, 0.01, -0.01]}, "fila cero"),
        ({"time_at_risk": [10.0, -1.0, 0.0, 0.0]}, "time_at_risk"),
        ({"transition_count": [2.0, math.inf, 0.0, 0.0]}, "transition_count"),
    ],
)
def test_markov_result_valida_generator(updates: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _result(generator_frame=_generator_frame(**updates))


def test_markov_result_acepta_conteos_opcionales_faltantes() -> None:
    transition = _transition_matrix_frame()
    transition["count"] = pd.Series([8.0, None, None, 2.0], dtype=object)
    generator = _generator_frame()
    generator["time_at_risk"] = pd.Series([10.0, None, None, 0.0], dtype=object)

    result = _result(transition_matrix_frame=transition, generator_frame=generator)

    assert result.transition_matrix_frame["count"].tolist()[1:3] == [None, None]
    assert result.generator_frame["time_at_risk"].tolist()[1:3] == [None, None]


def test_markov_results_import_liviano_y_exports_publicos() -> None:
    code = (
        "import sys;"
        "import nikodym.markov.config;"
        "baseline=set(sys.modules);"
        "import nikodym.markov.results;"
        "blocked=[m for m in ('pandas','scipy') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'numpy' in baseline;"
        "assert 'nikodym.markov.step' not in sys.modules;"
        "assert 'nikodym.markov.transition' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert markov_results.MarkovMethod == ConfigMarkovMethod
    assert markov_results.ProjectionMode == ConfigProjectionMode
    assert markov_results.EmbeddingPolicy == ConfigEmbeddingPolicy
    assert "EmbeddingDiagnostics" in markov_results.__all__
    assert "MarkovDiagnostics" in markov_results.__all__
    assert "MarkovCard" in markov_results.__all__
    assert "MarkovResult" in markov_results.__all__


def _diagnostics(**updates: Any) -> MarkovDiagnostics:
    payload: dict[str, Any] = {
        "method": "cohort",
        "projection_mode": "homogeneous",
        "states": ("A", "default"),
        "default_state": "default",
        "absorbing_states": ("default",),
        "n_entities": 2,
        "n_observations": 4,
        "n_transitions": 3,
        "n_periods": 3,
        "stochastic_tol": 1e-12,
        "generator_tol": 1e-12,
        "embedding_status": "valid",
        "embedding_flags": ("principal_log_real",),
        "embedding_adjusted": False,
        "embedding_distance_fro": 0.0,
        "fit_statistics": {"log_likelihood": -12.5, "n_params": 3, "status": "ok"},
        "warnings": (),
    }
    payload.update(updates)
    return MarkovDiagnostics(**payload)


def _card(**updates: Any) -> MarkovCard:
    payload: dict[str, Any] = {
        "method": "cohort",
        "projection_mode": "homogeneous",
        "time_unit": "month",
        "horizon_periods": (1, 2, 3),
        "states": ("A", "default"),
        "default_state": "default",
        "absorbing_states": ("default",),
        "output_columns": _TERM_COLUMNS,
        "diagnostics": _diagnostics(),
        "dependency_versions": {"pandas": "2.3.3", "numpy": "2.4.6"},
        "falta_dato": (),
    }
    payload.update(updates)
    return MarkovCard(**payload)


def _result(
    *,
    estimator: Any | None = None,
    transition_matrix_frame: Any = _DEFAULT,
    generator_frame: Any = _DEFAULT,
    term_structure_frame: Any = _DEFAULT,
    diagnostics: MarkovDiagnostics | None = None,
    card: MarkovCard | None = None,
    extra: object | None = None,
) -> MarkovResult:
    payload: dict[str, Any] = {
        "estimator": DummyTransitionMatrixEstimator() if estimator is None else estimator,
        "transition_matrix_frame": _transition_matrix_frame()
        if transition_matrix_frame is _DEFAULT
        else transition_matrix_frame,
        "generator_frame": _generator_frame() if generator_frame is _DEFAULT else generator_frame,
        "term_structure_frame": _term_structure_frame()
        if term_structure_frame is _DEFAULT
        else term_structure_frame,
        "diagnostics": _diagnostics() if diagnostics is None else diagnostics,
        "card": _card() if card is None else card,
    }
    if extra is not None:
        payload["extra"] = extra
    return MarkovResult(**payload)


def _transition_matrix_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "period": [None, None, None, None],
        "from_state": ["A", "A", "default", "default"],
        "to_state": ["A", "default", "A", "default"],
        "probability": [0.80, 0.20, -0.0, 1.0],
        "count": [8.0, 2.0, -0.0, 2.0],
        "origin_count": [10.0, 10.0, 2.0, 2.0],
        "method": ["cohort", "cohort", "cohort", "cohort"],
        "segment": ["retail", "retail", "retail", "retail"],
    }
    payload.update(updates)
    return pd.DataFrame(payload)


def _generator_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "from_state": ["A", "A", "default", "default"],
        "to_state": ["A", "default", "A", "default"],
        "intensity": [-0.20, 0.20, -0.0, -0.0],
        "time_at_risk": [10.0, 10.0, -0.0, -0.0],
        "transition_count": [2.0, 2.0, -0.0, -0.0],
        "source": ["duration", "duration", "duration", "duration"],
    }
    payload.update(updates)
    return pd.DataFrame(payload)


def _term_structure_frame(**updates: Any) -> pd.DataFrame:
    payload: dict[str, Any] = {
        "row_id": ["state:A", "state:A", "state:A"],
        "segment": ["retail", "retail", "retail"],
        "partition": ["desarrollo", "desarrollo", "desarrollo"],
        "period": [1, 2, 3],
        "time_value": [1.0, 2.0, 3.0],
        "hazard": [0.10, 0.11111111111111112, 0.125],
        "survival": [0.90, 0.80, 0.70],
        "pd_marginal": [0.10, 0.10, 0.10],
        "pd_cumulative": [0.10, 0.20, 0.30],
        "method": ["cohort", "cohort", "cohort"],
        "pd_source": ["markov", "markov", "markov"],
        "scenario": [math.nan, math.nan, math.nan],
        "warning_codes": [(), (), ("FALTA-DATO-MKV-1",)],
    }
    payload.update(updates)
    return pd.DataFrame(
        payload,
        index=pd.Index(["state:A|1", "state:A|2", "state:A|3"], name="curve_id"),
    )


def _normalized_transition_matrix_frame() -> pd.DataFrame:
    return _normalize_frame(_transition_matrix_frame())


def _normalized_generator_frame() -> pd.DataFrame:
    return _normalize_frame(_generator_frame())


def _normalized_term_structure_frame() -> pd.DataFrame:
    return _normalize_frame(_term_structure_frame())


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    for column in normalized.select_dtypes(include=["float"]).columns:
        normalized[column] = normalized[column].mask(normalized[column] == 0.0, 0.0)
    return normalized
