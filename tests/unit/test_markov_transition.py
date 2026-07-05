"""Tests del motor B19.3 de matrices de transición Markov."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd
import pytest
from numpy.testing import assert_allclose
from pandas.testing import assert_frame_equal

import nikodym.markov.transition as transition_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import MissingDependencyError, NotFittedError
from nikodym.markov.config import (
    MarkovConfig,
    MarkovDynamicsConfig,
    MarkovEstimationConfig,
    MarkovInputConfig,
    MarkovStateConfig,
    MarkovValidationConfig,
)
from nikodym.markov.exceptions import (
    InvalidGeneratorError,
    MarkovFitError,
    MarkovInputError,
    MarkovTransformError,
    NonStochasticMatrixError,
)
from nikodym.markov.transition import TransitionMatrixEstimator

_TRANSITION_COLUMNS = [
    "period",
    "from_state",
    "to_state",
    "probability",
    "count",
    "origin_count",
    "method",
    "segment",
]
_GENERATOR_COLUMNS = [
    "from_state",
    "to_state",
    "intensity",
    "time_at_risk",
    "transition_count",
    "source",
]
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
]


def _states(
    *,
    allow_unknown_states: bool = False,
    states: tuple[str, ...] = ("A", "B", "default"),
) -> MarkovStateConfig:
    return MarkovStateConfig(
        states=states,
        default_state="default",
        absorbing_states=("default",),
        allow_unknown_states=allow_unknown_states,
    )


def _cfg(**overrides: object) -> MarkovConfig:
    kwargs: dict[str, object] = {"states": _states()}
    kwargs.update(overrides)
    return MarkovConfig(**kwargs)


def _duration_cfg() -> MarkovConfig:
    return MarkovConfig(
        input=MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            exposure_time_col="exposure",
        ),
        states=_states(states=("A", "default")),
        estimation=MarkovEstimationConfig(method="duration"),
    )


def _cohort_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6],
            "time": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            "state": [
                "A",
                "A",
                "A",
                "A",
                "A",
                "B",
                "A",
                "default",
                "B",
                "B",
                "B",
                "default",
            ],
        }
    )


def _duration_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            "time": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            "state": ["A", "default", "A", "A", "A", "A", "A", "A", "A", "A"],
            "exposure": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        }
    )


def _duration_frame_exposure_8() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            "time": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            "state": ["A", "default", "A", "A", "A", "A", "A", "A", "A", "A"],
            "exposure": [2.0, 0.0, 2.0, 0.0, 1.0, 0.0, 1.0, 0.0, 2.0, 0.0],
        }
    )


def _probability(
    frame: pd.DataFrame,
    *,
    from_state: str,
    to_state: str,
) -> float:
    row = frame[(frame["from_state"] == from_state) & (frame["to_state"] == to_state)]
    assert len(row) == 1
    return float(row.iloc[0]["probability"])


def test_cohort_mle_golden_outputs_tidy_auditoria_y_no_mutacion() -> None:
    frame = _cohort_frame()
    original = frame.copy(deep=True)
    audit = InMemoryAuditSink()

    estimator = TransitionMatrixEstimator.from_config(_cfg()).fit(frame, audit=audit)

    expected = np.array([[0.50, 0.25, 0.25], [0.0, 0.50, 0.50], [0.0, 0.0, 1.0]])
    assert_allclose(estimator.transition_matrix_, expected)
    assert estimator.period_transition_matrices_ == {}
    assert estimator.generator_ is None
    assert estimator.states_ == ("A", "B", "default")
    assert estimator.default_state_ == "default"
    assert estimator.state_counts_ == {"A": 4.0, "B": 2.0, "default": 0.0}
    assert_allclose(
        estimator.transition_counts_,
        np.array([[2.0, 1.0, 1.0], [0.0, 1.0, 1.0], [0.0, 0.0, 0.0]]),
    )
    assert tuple(estimator.transition_matrix_frame_.columns) == tuple(_TRANSITION_COLUMNS)
    assert _probability(estimator.transition_matrix_frame_, from_state="A", to_state="default") == (
        pytest.approx(0.25)
    )
    assert estimator.diagnostics_.method == "cohort"
    assert estimator.diagnostics_.projection_mode == "homogeneous"
    assert estimator.diagnostics_.n_entities == 6
    assert estimator.diagnostics_.n_observations == 12
    assert estimator.diagnostics_.n_transitions == 6
    assert estimator.diagnostics_.warnings == ()
    assert [event.payload["regla"] for event in audit.events] == [
        "markov_method",
        "markov_input_quality",
    ]
    assert_frame_equal(frame, original)

    projected = estimator.predict_transition(horizons=[2, 1])
    assert list(projected) == [1.0, 2.0]
    assert tuple(projected[1.0].columns) == tuple(_TRANSITION_COLUMNS)
    assert _probability(projected[2.0], from_state="A", to_state="default") == pytest.approx(0.50)
    assert _probability(projected[2.0], from_state="B", to_state="default") == pytest.approx(0.75)

    term = estimator.term_structure(horizons=[1, 2])
    assert tuple(term.columns) == tuple(_TERM_COLUMNS)
    assert term.loc["state:A|1", "pd_cumulative"] == pytest.approx(0.25)
    assert term.loc["state:A|2", "pd_cumulative"] == pytest.approx(0.50)
    assert term.loc["state:A|2", "pd_marginal"] == pytest.approx(0.25)
    assert term.loc["state:B|1", "pd_cumulative"] == pytest.approx(0.50)
    assert term.loc["state:B|2", "pd_cumulative"] == pytest.approx(0.75)
    assert term.loc["state:B|2", "hazard"] == pytest.approx(0.50)


def test_duration_golden_generator_expm_y_outputs_tidy() -> None:
    estimator = TransitionMatrixEstimator.from_config(_duration_cfg()).fit(_duration_frame())

    assert_allclose(estimator.generator_, np.array([[-0.2, 0.2], [0.0, 0.0]]), atol=1e-12)
    assert_allclose(
        estimator.transition_matrix_,
        np.array([[math.exp(-0.2), 1.0 - math.exp(-0.2)], [0.0, 1.0]]),
        atol=1e-12,
    )
    assert estimator.state_counts_ == {"A": 5.0, "default": 0.0}
    assert estimator.time_at_risk_ == {"A": 5.0, "default": 0.0}
    assert tuple(estimator.generator_frame_.columns) == tuple(_GENERATOR_COLUMNS)
    assert estimator.generator_frame_.loc[1, "intensity"] == pytest.approx(0.2)
    assert estimator.generator_frame_.loc[1, "transition_count"] == pytest.approx(1.0)
    assert estimator.generator_frame_.loc[1, "source"] == "duration"

    projected = estimator.predict_transition(horizons=[1, 2])
    assert _probability(projected[1.0], from_state="A", to_state="default") == pytest.approx(
        0.1812692469,
        abs=1e-10,
    )
    assert _probability(projected[2.0], from_state="A", to_state="default") == pytest.approx(
        0.329679954,
        abs=1e-9,
    )
    term = estimator.term_structure(horizons=[1, 2])
    assert term.loc["state:A|1", "pd_cumulative"] == pytest.approx(0.1812692469, abs=1e-10)
    assert term.loc["state:A|2", "pd_cumulative"] == pytest.approx(0.329679954, abs=1e-9)


def test_duration_transition_matrix_origin_count_publica_conteo_no_tiempo_en_riesgo() -> None:
    estimator = TransitionMatrixEstimator.from_config(_duration_cfg()).fit(
        _duration_frame_exposure_8()
    )

    assert estimator.state_counts_ == {"A": 8.0, "default": 0.0}
    assert estimator.time_at_risk_ == {"A": 8.0, "default": 0.0}
    assert estimator.generator_frame_.loc[1, "time_at_risk"] == pytest.approx(8.0)
    assert estimator.generator_frame_.loc[1, "transition_count"] == pytest.approx(1.0)
    origin_counts = estimator.transition_matrix_frame_.loc[
        estimator.transition_matrix_frame_["from_state"] == "A",
        "origin_count",
    ]
    assert origin_counts.tolist() == [5.0, 5.0]


def test_from_config_mapping_weights_particion_unknown_y_absorbente_permanente() -> None:
    cfg = _cfg(
        input=MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            weight_col="weight",
            partition_col="partition",
        ),
        states=_states(allow_unknown_states=True, states=("A", "default")),
        estimation=MarkovEstimationConfig(use_weights=True),
    )
    frame = pd.DataFrame(
        {
            "id": [1, 1, 1, 1, 2, 2],
            "time": [1, 2, 3, 4, 1, 2],
            "state": ["A", "Z", "default", "default", "A", "A"],
            "weight": [2.0, 1.0, 1.0, 1.0, 3.0, 3.0],
            "partition": ["desarrollo", "desarrollo", "desarrollo", "desarrollo", "oot", "oot"],
        }
    )
    estimator = TransitionMatrixEstimator.from_config(cfg.model_dump()).fit(frame)

    assert estimator.state_counts_ == {"A": 2.0, "default": 0.0}
    assert estimator.diagnostics_.warnings == ("unknown_states_dropped:Z",)
    assert_allclose(estimator.transition_matrix_, np.array([[0.0, 1.0], [0.0, 1.0]]))


def test_constructor_default_mapping_segmento_y_particion_sin_desarrollo() -> None:
    default_estimator = TransitionMatrixEstimator()
    assert default_estimator.config.states.states == ("performing", "default")

    mapping_estimator = TransitionMatrixEstimator(config=_cfg().model_dump())
    assert mapping_estimator.config.states.states == ("A", "B", "default")

    segmented_cfg = _cfg(
        input=MarkovInputConfig(id_col="id", time_col="time", state_col="state", segment_col="seg"),
        states=_states(states=("A", "default")),
    )
    with pytest.raises(MarkovInputError, match="Faltan columnas"):
        TransitionMatrixEstimator.from_config(segmented_cfg).fit(_cohort_frame())

    frame = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [1, 2],
            "state": ["A", "default"],
            "seg": ["retail", "retail"],
            "partition": ["oot", "oot"],
        }
    )
    estimator = TransitionMatrixEstimator.from_config(segmented_cfg).fit(frame)
    assert estimator.diagnostics_.n_observations == 2
    assert estimator.transition_matrix_[0, 1] == pytest.approx(1.0)


def test_validacion_estocastica_local_falla_y_normaliza_residuo() -> None:
    too_high = np.array([[1.0 + 1e-8, 0.0], [0.0, 1.0]])
    with pytest.raises(NonStochasticMatrixError, match="fuera de \\[0, 1\\]"):
        transition_module._validate_stochastic_matrix(
            too_high,
            states=("A", "default"),
            absorbing_states=("default",),
            tol=1e-10,
            normalize_within_tolerance=True,
            np=np,
        )

    normalized, warnings = transition_module._validate_stochastic_matrix(
        np.array([[0.5 + 1e-12, 0.5], [0.0, 1.0]]),
        states=("A", "default"),
        absorbing_states=("default",),
        tol=1e-10,
        normalize_within_tolerance=True,
        np=np,
    )
    assert_allclose(normalized[0], np.array([0.5 + 5e-13, 0.5 - 5e-13]), atol=1e-14)
    assert warnings == ("normalized_stochastic_row:A",)


@pytest.mark.parametrize(
    ("matrix", "message"),
    [
        (np.ones((2, 3)), "cuadrada"),
        (np.array([[math.nan, 1.0], [0.0, 1.0]]), "no finitos"),
        (np.array([[0.5, 0.4], [0.0, 1.0]]), "no suma 1"),
        (np.array([[1.0, 0.0], [0.1, 0.9]]), "absorbente"),
    ],
)
def test_validacion_estocastica_local_errores(matrix: np.ndarray[Any, Any], message: str) -> None:
    with pytest.raises(NonStochasticMatrixError, match=message):
        transition_module._validate_stochastic_matrix(
            matrix,
            states=("A", "default"),
            absorbing_states=("default",),
            tol=1e-10,
            normalize_within_tolerance=True,
            np=np,
        )


@pytest.mark.parametrize(
    ("generator", "states", "absorbing", "message"),
    [
        (np.ones((2, 3)), ("A", "default"), ("default",), "cuadrado"),
        (np.array([[math.nan, 0.0], [0.0, 0.0]]), ("A", "default"), ("default",), "no finitos"),
        (np.array([[-0.2, -0.1], [0.0, 0.0]]), ("A", "default"), ("default",), "negativa"),
        (np.array([[0.1, 0.0], [0.0, 0.0]]), ("A", "default"), ("default",), "no positiva"),
        (np.array([[-0.1, 0.2], [0.0, 0.0]]), ("A", "default"), ("default",), "no suma 0"),
        (np.array([[-0.2, 0.2], [0.1, -0.1]]), ("A", "default"), ("default",), "fila cero"),
    ],
)
def test_validacion_generator_local_errores(
    generator: np.ndarray[Any, Any],
    states: tuple[str, ...],
    absorbing: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(InvalidGeneratorError, match=message):
        transition_module._validate_generator(
            generator,
            states=states,
            absorbing_states=absorbing,
            tol=1e-10,
            np=np,
        )


def test_validacion_generator_local_acepta_un_estado_y_normaliza_cero() -> None:
    observed = transition_module._validate_generator(
        np.array([[-0.0]]),
        states=("solo",),
        absorbing_states=(),
        tol=1e-10,
        np=np,
    )

    assert observed[0, 0] == 0.0
    assert math.copysign(1.0, observed[0, 0]) == 1.0


def test_errores_de_input_absorbentes_y_minimos() -> None:
    with pytest.raises(MarkovInputError, match=r"pandas\.DataFrame"):
        TransitionMatrixEstimator.from_config(_cfg()).fit({"id": [1]})
    with pytest.raises(MarkovInputError, match="Faltan columnas"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(pd.DataFrame({"id": [1]}))
    with pytest.raises(MarkovInputError, match="duplicados"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(
            pd.DataFrame({"id": [1, 1], "time": [1, 1], "state": ["A", "B"]})
        )
    with pytest.raises(MarkovInputError, match="fuera de catálogo"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(
            pd.DataFrame({"id": [1, 1], "time": [1, 2], "state": ["A", "Z"]})
        )
    with pytest.raises(MarkovInputError, match="Todos los estados"):
        TransitionMatrixEstimator.from_config(_cfg(states=_states(allow_unknown_states=True))).fit(
            pd.DataFrame({"id": [1, 1], "time": [1, 2], "state": ["Z", "Y"]})
        )
    with pytest.raises(MarkovInputError, match="filas modelables"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(
            pd.DataFrame({"id": [], "time": [], "state": []})
        )
    with pytest.raises(MarkovFitError, match="No hay transiciones"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(
            pd.DataFrame({"id": [1], "time": [1], "state": ["A"]})
        )
    with pytest.raises(MarkovInputError, match="absorbente"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(
            pd.DataFrame({"id": [1, 1, 1], "time": [1, 2, 3], "state": ["A", "default", "A"]})
        )
    with pytest.raises(MarkovFitError, match="origen suficiente"):
        TransitionMatrixEstimator.from_config(
            _cfg(estimation=MarkovEstimationConfig(min_origin_count=3))
        ).fit(pd.DataFrame({"id": [1, 1], "time": [1, 2], "state": ["A", "default"]}))


def test_errores_de_pesos_particion_tiempo_y_exposure() -> None:
    weighted = MarkovConfig.model_construct(
        schema_version="1.0.0",
        type="standard",
        input=MarkovInputConfig(id_col="id", time_col="time", state_col="state"),
        states=_states(),
        estimation=MarkovEstimationConfig(use_weights=True),
        dynamics=MarkovDynamicsConfig(),
        validation=MarkovValidationConfig(),
        fail_on_falta_dato=True,
    )
    with pytest.raises(MarkovInputError, match="weight_col"):
        TransitionMatrixEstimator.from_config(weighted).fit(_cohort_frame())

    bad_weight = _cfg(
        input=MarkovInputConfig(id_col="id", time_col="time", state_col="state", weight_col="w"),
        estimation=MarkovEstimationConfig(use_weights=True),
    )
    with pytest.raises(MarkovInputError, match="pesos finitos"):
        TransitionMatrixEstimator.from_config(bad_weight).fit(
            pd.DataFrame(
                {"id": [1, 1], "time": [1, 2], "state": ["A", "default"], "w": [-1.0, 1.0]}
            )
        )

    with pytest.raises(MarkovInputError, match="partition"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(
            pd.DataFrame(
                {
                    "id": [1, 1],
                    "time": [1, 2],
                    "state": ["A", "default"],
                    "partition": ["desarrollo", None],
                }
            )
        )
    with pytest.raises(MarkovInputError, match="booleano"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(
            pd.DataFrame({"id": [1, 1], "time": [False, True], "state": ["A", "default"]})
        )
    with pytest.raises(MarkovInputError, match="crecer estrictamente"):
        transition_module._delta_time(2.0, 1.0)
    with pytest.raises(MarkovInputError, match="finito"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(
            pd.DataFrame({"id": [1, 1], "time": [1, math.inf], "state": ["A", "default"]})
        )
    with pytest.raises(MarkovInputError, match="número"):
        TransitionMatrixEstimator.from_config(_cfg()).fit(
            pd.DataFrame({"id": [1, 1], "time": ["a", "b"], "state": ["A", "default"]})
        )
    with pytest.raises(MarkovInputError, match="exposure_time_col"):
        TransitionMatrixEstimator.from_config(_duration_cfg()).fit(
            pd.DataFrame(
                {
                    "id": [1, 1],
                    "time": [1, 2],
                    "state": ["A", "default"],
                    "exposure": [-1.0, 0.0],
                }
            )
        )


def test_helpers_defensivos_numericos_y_weight_col_none() -> None:
    weighted = MarkovConfig.model_construct(
        schema_version="1.0.0",
        type="standard",
        input=MarkovInputConfig(id_col="id", time_col="time", state_col="state"),
        states=_states(),
        estimation=MarkovEstimationConfig(use_weights=True),
        dynamics=MarkovDynamicsConfig(),
        validation=MarkovValidationConfig(),
        fail_on_falta_dato=True,
    )
    assert transition_module._transition_weight({}, cfg=weighted) == 1.0
    with pytest.raises(MarkovTransformError, match=r"\[0, 1\]"):
        transition_module._unit_float(1.1, field_name="probability")
    with pytest.raises(MarkovTransformError, match="no negativo"):
        transition_module._non_negative_float(-1.0, field_name="count")
    with pytest.raises(MarkovTransformError, match="no finito"):
        transition_module._clean_float(math.inf)


def test_duration_errores_de_generador_por_exposure_cero() -> None:
    with pytest.raises(InvalidGeneratorError, match="tiempo en riesgo cero"):
        TransitionMatrixEstimator.from_config(_duration_cfg()).fit(
            pd.DataFrame(
                {
                    "id": [1, 1],
                    "time": [1, 2],
                    "state": ["A", "default"],
                    "exposure": [0.0, 0.0],
                }
            )
        )
    with pytest.raises(MarkovFitError, match="tiempo en riesgo positivo"):
        TransitionMatrixEstimator.from_config(_duration_cfg()).fit(
            pd.DataFrame(
                {
                    "id": [1, 1],
                    "time": [1, 2],
                    "state": ["A", "A"],
                    "exposure": [0.0, 0.0],
                }
            )
        )


def test_duration_aplica_min_origin_count_consistente_con_cohort() -> None:
    # Reproduce el bug: `min_origin_count` se aplicaba en cohort pero se ignoraba en
    # silencio en duration. Estado A con un único origen (origin_count=1) y
    # time_at_risk>0, así los guards de riesgo NO lo atrapan: solo min_origin_count debe.
    frame = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [0, 1],
            "state": ["A", "default"],
            "exposure": [1.0, 0.0],
        }
    )
    duration_cfg = MarkovConfig(
        input=MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            exposure_time_col="exposure",
        ),
        states=_states(states=("A", "default")),
        estimation=MarkovEstimationConfig(method="duration", min_origin_count=2),
    )
    with pytest.raises(MarkovFitError, match="origen suficiente") as duration_exc:
        TransitionMatrixEstimator.from_config(duration_cfg).fit(frame)
    assert "'A'" in str(duration_exc.value)
    assert "min_origin_count=2" in str(duration_exc.value)

    # Mismo dataset por cohort ya levantaba idéntico: la inconsistencia queda cerrada.
    cohort_cfg = _cfg(
        states=_states(states=("A", "default")),
        estimation=MarkovEstimationConfig(min_origin_count=2),
    )
    with pytest.raises(MarkovFitError, match="origen suficiente") as cohort_exc:
        TransitionMatrixEstimator.from_config(cohort_cfg).fit(frame)
    assert str(cohort_exc.value) == str(duration_exc.value)


def test_duration_min_origin_count_uno_datos_validos_sigue_ajustando() -> None:
    # Regresión: con el default `min_origin_count=1` el ajuste de datos válidos no cambia.
    cfg = MarkovConfig(
        input=MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            exposure_time_col="exposure",
        ),
        states=_states(states=("A", "default")),
        estimation=MarkovEstimationConfig(method="duration", min_origin_count=1),
    )
    estimator = TransitionMatrixEstimator.from_config(cfg).fit(_duration_frame())
    assert_allclose(estimator.generator_, np.array([[-0.2, 0.2], [0.0, 0.0]]), atol=1e-12)
    assert estimator.state_counts_ == {"A": 5.0, "default": 0.0}
    assert estimator.time_at_risk_ == {"A": 5.0, "default": 0.0}


def test_transform_errors_not_fitted_horizons_y_term_structure() -> None:
    estimator = TransitionMatrixEstimator.from_config(_cfg())
    with pytest.raises(NotFittedError, match="no está fiteado"):
        estimator.predict_transition(horizons=[1])

    fitted = estimator.fit(_cohort_frame())
    for horizons in ([], [True], [-1], [math.inf], [1, 1.0]):
        with pytest.raises(MarkovTransformError):
            fitted.predict_transition(horizons=horizons)

    interval_cfg = _cfg(estimation=MarkovEstimationConfig(interval=2.0))
    interval_fit = TransitionMatrixEstimator.from_config(interval_cfg).fit(_cohort_frame())
    with pytest.raises(MarkovTransformError, match="múltiplos"):
        interval_fit.predict_transition(horizons=[1])

    duration = TransitionMatrixEstimator.from_config(_duration_cfg()).fit(_duration_frame())
    with pytest.raises(MarkovTransformError, match="horizontes enteros"):
        duration.term_structure(horizons=[1.5])

    tol_cfg = _cfg(validation=MarkovValidationConfig(stochastic_tol=1e-10))
    assert transition_module._pd_marginal(0.50, 0.50000000001, tol_cfg) == 0.0
    with pytest.raises(MarkovTransformError, match="PD marginal negativa"):
        transition_module._pd_marginal(0.50, 0.51, tol_cfg)


def test_projection_mode_no_homogeneo_falla_explicito() -> None:
    cfg = _cfg(dynamics=MarkovDynamicsConfig(projection_mode="period_matrices"))
    with pytest.raises(MarkovFitError, match="homogeneous"):
        TransitionMatrixEstimator.from_config(cfg).fit(_cohort_frame())


def test_imports_perezosos_y_dependencias_faltantes(monkeypatch: pytest.MonkeyPatch) -> None:
    code = (
        "import sys;"
        "import nikodym.markov.config;"
        "baseline=set(sys.modules);"
        "import nikodym.markov.transition;"
        "blocked=[m for m in ('pandas','scipy') if m in sys.modules and m not in baseline];"
        "assert not blocked, blocked;"
        "assert 'nikodym.markov.term_structure' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    def fake_import(name: str) -> Any:
        if name in {"pandas", "numpy", "scipy.linalg"}:
            raise ModuleNotFoundError(name)
        return importlib_original(name)

    importlib_original = transition_module.importlib.import_module
    monkeypatch.setattr(transition_module.importlib, "import_module", fake_import)
    with pytest.raises(MissingDependencyError, match="pandas"):
        transition_module._import_pandas()
    with pytest.raises(MissingDependencyError, match="numpy"):
        transition_module._import_numpy()
    with pytest.raises(MissingDependencyError, match=r"nikodym\[markov\]"):
        transition_module._import_expm()
