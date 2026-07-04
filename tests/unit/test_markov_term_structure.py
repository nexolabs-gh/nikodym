"""Tests de B19.4: proyección, embedding y term-structure Markov."""

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

import nikodym.markov.term_structure as term_module
from nikodym.core.exceptions import MissingDependencyError
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
    MarkovEmbeddingError,
    MarkovInputError,
    MarkovTransformError,
    NonStochasticMatrixError,
)
from nikodym.markov.term_structure import (
    aalen_johansen,
    chapman_kolmogorov,
    diagnose_embedding,
    markov_term_structure,
    validate_generator,
    validate_transition_matrix,
)

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


def _cfg(
    *,
    states: tuple[str, ...] = ("A", "B", "default"),
    projection_mode: str = "homogeneous",
    embedding_policy: str = "diagnose",
    validation: MarkovValidationConfig | None = None,
) -> MarkovConfig:
    input_cfg = MarkovInputConfig(id_col="id", time_col="time", state_col="state")
    if projection_mode == "aalen_johansen":
        input_cfg = MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            transition_time_col="event_time",
        )
    return MarkovConfig(
        input=input_cfg,
        states=MarkovStateConfig(states=states),
        dynamics=MarkovDynamicsConfig(
            projection_mode=projection_mode, embedding_policy=embedding_policy
        ),
        validation=validation or MarkovValidationConfig(),
    )


def _cohort_matrix() -> np.ndarray[Any, Any]:
    return np.array(
        [
            [0.50, 0.25, 0.25],
            [0.00, 0.50, 0.50],
            [0.00, 0.00, 1.00],
        ],
        dtype="float64",
    )


def test_validate_transition_matrix_publica_tolerancia_no_mutacion_y_errores() -> None:
    matrix = np.array([[0.5 + 1e-12, 0.5], [0.0, 1.0]], dtype="float64")
    original = matrix.copy()

    validate_transition_matrix(
        matrix,
        states=("A", "default"),
        absorbing_states=("default",),
        tol=1e-10,
    )

    assert_allclose(matrix, original)
    with pytest.raises(NonStochasticMatrixError, match=r"fuera de \[0, 1\]"):
        validate_transition_matrix(
            np.array([[1.0 + 1e-8, 0.0], [0.0, 1.0]]),
            states=("A", "default"),
            absorbing_states=("default",),
            tol=1e-10,
        )
    with pytest.raises(NonStochasticMatrixError, match="no suma 1"):
        validate_transition_matrix(
            np.array([[0.5, 0.4], [0.0, 1.0]]),
            states=("A", "default"),
            absorbing_states=("default",),
            tol=1e-10,
        )
    with pytest.raises(NonStochasticMatrixError, match="absorbente"):
        validate_transition_matrix(
            np.array([[1.0, 0.0], [0.1, 0.9]]),
            states=("A", "default"),
            absorbing_states=("default",),
            tol=1e-10,
        )


@pytest.mark.parametrize(
    ("generator", "message"),
    [
        (np.array([[-0.2, -0.1], [0.0, 0.0]]), "negativa"),
        (np.array([[0.1, 0.0], [0.0, 0.0]]), "no positiva"),
        (np.array([[-0.1, 0.2], [0.0, 0.0]]), "no suma 0"),
        (np.array([[-0.2, 0.2], [0.1, -0.1]]), "fila cero"),
    ],
)
def test_validate_generator_publica_golden_y_errores(
    generator: np.ndarray[Any, Any],
    message: str,
) -> None:
    valid = np.array([[-0.2, 0.2], [0.0, 0.0]], dtype="float64")
    original = valid.copy()
    validate_generator(valid, states=("A", "default"), absorbing_states=("default",), tol=1e-10)
    assert_allclose(valid, original)

    with pytest.raises(InvalidGeneratorError, match=message):
        validate_generator(
            generator,
            states=("A", "default"),
            absorbing_states=("default",),
            tol=1e-10,
        )


def test_chapman_kolmogorov_goldens_homogeneo_y_no_homogeneo_ordenado() -> None:
    matrix = _cohort_matrix()
    projected = chapman_kolmogorov([matrix], homogeneous=True, horizons=[2, 1])

    assert list(projected) == [1, 2]
    assert projected[1][0, 2] == pytest.approx(0.25)
    assert projected[2][0, 2] == pytest.approx(0.50)
    assert projected[1][1, 2] == pytest.approx(0.50)
    assert projected[2][1, 2] == pytest.approx(0.75)
    assert_allclose(matrix, _cohort_matrix())

    first = np.array([[0.8, 0.2, 0.0], [0.0, 0.7, 0.3], [0.0, 0.0, 1.0]])
    second = np.array([[0.6, 0.0, 0.4], [0.1, 0.6, 0.3], [0.0, 0.0, 1.0]])
    non_homogeneous = chapman_kolmogorov(
        [first, second],
        homogeneous=False,
        horizons=[1, 2],
    )
    assert_allclose(non_homogeneous[2], first @ second)
    assert not np.allclose(non_homogeneous[2], second @ first)
    only_second = chapman_kolmogorov([first, second], homogeneous=False, horizons=[2])
    assert list(only_second) == [2]
    with pytest.raises(MarkovTransformError, match="Faltan matrices"):
        chapman_kolmogorov([first, second], homogeneous=False, horizons=[3])


@pytest.mark.parametrize("horizons", [[], [True], [-1], [1.5], [1, 1]])
def test_chapman_kolmogorov_defensas_de_horizonte(horizons: list[Any]) -> None:
    with pytest.raises(MarkovTransformError):
        chapman_kolmogorov([np.eye(2)], homogeneous=True, horizons=horizons)

    with pytest.raises(MarkovTransformError, match="matrices"):
        chapman_kolmogorov([], homogeneous=True, horizons=[1])
    with pytest.raises(NonStochasticMatrixError, match="bidimensional"):
        chapman_kolmogorov([np.array([1.0, 0.0])], homogeneous=True, horizons=[1])


def test_markov_term_structure_goldens_columnas_y_hazard() -> None:
    transitions = chapman_kolmogorov([_cohort_matrix()], homogeneous=True, horizons=[1, 2])

    term = markov_term_structure(transitions, config=_cfg())

    assert term.columns.tolist() == _TERM_COLUMNS
    assert term.loc["state:A|1", "pd_cumulative"] == pytest.approx(0.25)
    assert term.loc["state:A|2", "pd_cumulative"] == pytest.approx(0.50)
    assert term.loc["state:A|2", "pd_marginal"] == pytest.approx(0.25)
    assert term.loc["state:B|1", "pd_cumulative"] == pytest.approx(0.50)
    assert term.loc["state:B|2", "pd_cumulative"] == pytest.approx(0.75)
    assert term.loc["state:B|2", "hazard"] == pytest.approx(0.50)
    assert term.loc["state:A|1", "survival"] == pytest.approx(0.75)
    assert term["method"].unique().tolist() == ["cohort"]
    assert term["pd_source"].unique().tolist() == ["markov"]
    assert term["scenario"].isna().all()
    assert term["warning_codes"].tolist() == [(), (), (), ()]


def test_markov_term_structure_marginal_negativa_y_hazard_no_definido() -> None:
    cfg = _cfg(states=("A", "default"), validation=MarkovValidationConfig(stochastic_tol=1e-10))
    almost_flat = markov_term_structure(
        {
            1: np.array([[0.5, 0.5], [0.0, 1.0]]),
            2: np.array([[0.500000000005, 0.499999999995], [0.0, 1.0]]),
        },
        config=cfg,
    )
    assert almost_flat.loc["state:A|2", "pd_marginal"] == 0.0

    with pytest.raises(MarkovTransformError, match="PD marginal negativa"):
        markov_term_structure(
            {
                1: np.array([[0.5, 0.5], [0.0, 1.0]]),
                2: np.array([[0.6, 0.4], [0.0, 1.0]]),
            },
            config=cfg,
        )

    fully_defaulted = markov_term_structure(
        {
            1: np.array([[0.0, 1.0], [0.0, 1.0]]),
            2: np.array([[0.0, 1.0], [0.0, 1.0]]),
        },
        config=cfg,
    )
    assert fully_defaulted.loc["state:A|2", "hazard"] == 0.0
    assert fully_defaulted.loc["state:A|2", "warning_codes"] == ("hazard_undefined_zero_survival",)

    non_integer_time = markov_term_structure(
        {0.5: np.array([[0.8, 0.2], [0.0, 1.0]])},
        config=cfg,
    )
    assert non_integer_time.loc["state:A|1", "time_value"] == pytest.approx(0.5)
    zero_time = markov_term_structure(
        {0.0: np.array([[0.8, 0.2], [0.0, 1.0]])},
        config=cfg,
    )
    assert zero_time.loc["state:A|1", "period"] == 1
    with pytest.raises(MarkovTransformError, match="transitions"):
        markov_term_structure({}, config=cfg)


def test_markov_term_structure_horizontes_no_consecutivos_abortan() -> None:
    """A2: horizontes discretos no consecutivos abortan; consecutivos dan marginal per-período.

    Con (2, 4, 6) el marginal PD_cum(t)-PD_cum(t_previo) abarca varios períodos pero se rotula como
    uno solo (mal distribuido -> ECL descontada mal). La validación telescópica no lo ve. Se exige
    resolución período a período desde 1 o se aborta. Aalen-Johansen queda exento (event-times).
    """
    cfg = _cfg(states=("A", "default"))  # projection_mode='homogeneous' (discreto)
    p = np.array([[0.9, 0.1], [0.0, 1.0]], dtype="float64")

    consecutive = markov_term_structure(
        chapman_kolmogorov([p], homogeneous=True, horizons=[1, 2, 3]),
        config=cfg,
    )
    # Marginal correcto por período: PD_cum(t) - PD_cum(t-1).
    assert consecutive.loc["state:A|1", "pd_marginal"] == pytest.approx(0.10)
    assert consecutive.loc["state:A|2", "pd_marginal"] == pytest.approx(0.09)
    assert consecutive.loc["state:A|3", "pd_marginal"] == pytest.approx(0.081)

    # Horizontes no consecutivos -> raise explícito (no marginal silenciosamente mal distribuido).
    with pytest.raises(MarkovTransformError, match="consecutivos"):
        markov_term_structure(
            chapman_kolmogorov([p], homogeneous=True, horizons=[2, 4, 6]),
            config=cfg,
        )
    # Un solo horizonte > 1 también deja fuera períodos previos -> raise.
    with pytest.raises(MarkovTransformError, match="consecutivos"):
        markov_term_structure({3: np.array([[0.7, 0.3], [0.0, 1.0]])}, config=cfg)

    # Aalen-Johansen exento: event-times no consecutivos NO abortan (incrementos son saltos reales).
    aj_cfg = _cfg(states=("A", "default"), projection_mode="aalen_johansen")
    term_aj = markov_term_structure(
        {
            3.0: np.array([[0.5, 0.5], [0.0, 1.0]]),
            7.0: np.array([[0.0, 1.0], [0.0, 1.0]]),
        },
        config=aj_cfg,
    )
    assert sorted(term_aj["period"].tolist()) == [3, 7]


def test_diagnose_embedding_valido_invalido_forbid_y_regularize() -> None:
    valid_cfg = _cfg(states=("A", "default"))
    matrix = np.array([[0.8, 0.2], [0.0, 1.0]], dtype="float64")

    diagnostics = diagnose_embedding(matrix, delta_t=1.0, config=valid_cfg)

    expected_a = -math.log(0.8)
    assert diagnostics.embedding_status == "valid_principal_log"
    assert diagnostics.embedding_flags == ()
    assert diagnostics.adjusted is False
    assert diagnostics.imaginary_norm == pytest.approx(0.0)
    assert_allclose(diagnostics.generator_candidate, np.array([[-expected_a, expected_a], [0, 0]]))

    singular = np.array([[0.0, 1.0], [0.0, 1.0]], dtype="float64")
    invalid = diagnose_embedding(singular, delta_t=1.0, config=valid_cfg)
    assert invalid.embedding_status == "invalid_principal_log"
    assert invalid.embedding_flags

    forbid_cfg = _cfg(states=("A", "default"), embedding_policy="forbid")
    with pytest.raises(MarkovEmbeddingError, match="Embedding Markov inválido"):
        diagnose_embedding(singular, delta_t=1.0, config=forbid_cfg)

    non_embeddable = np.array(
        [[0.1, 0.9, 0.0], [0.9, 0.1, 0.0], [0.0, 0.0, 1.0]],
        dtype="float64",
    )
    regularize_cfg = _cfg(
        states=("A", "B", "default"),
        embedding_policy="regularize",
        validation=MarkovValidationConfig(stochastic_tol=1e-8, generator_tol=1e-8),
    )
    regularized = diagnose_embedding(non_embeddable, delta_t=1.0, config=regularize_cfg)
    assert regularized.embedding_status == "regularized_principal_log"
    assert regularized.adjusted is True
    assert regularized.distance_fro is not None
    validate_generator(
        regularized.generator_candidate,
        states=("A", "B", "default"),
        absorbing_states=("default",),
        tol=1e-8,
    )


def test_diagnose_embedding_captura_warning_de_logm(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = term_module.importlib.import_module

    class FakeScipyLinalg:
        @staticmethod
        def logm(_matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            warnings.warn(RuntimeWarning("logm inestable"), stacklevel=2)
            return np.eye(2)

        @staticmethod
        def expm(matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            return matrix

    def fake_import(name: str) -> Any:
        if name == "scipy.linalg":
            return FakeScipyLinalg
        return original_import(name)

    monkeypatch.setattr(term_module.importlib, "import_module", fake_import)

    diagnostics = diagnose_embedding(
        np.array([[0.8, 0.2], [0.0, 1.0]]),
        delta_t=1.0,
        config=_cfg(states=("A", "default")),
    )

    assert diagnostics.embedding_status == "invalid_principal_log"
    assert diagnostics.embedding_flags == ("logm_warning",)


def test_diagnose_embedding_errores_controlados_y_regularize_fallido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = term_module.importlib.import_module

    class RaisesLogm:
        @staticmethod
        def logm(_matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            raise ValueError("logm roto")

        @staticmethod
        def expm(matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            return matrix

    class NonFiniteLogm:
        @staticmethod
        def logm(_matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            return np.array([[math.inf, 0.0], [0.0, 0.0]])

        @staticmethod
        def expm(matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            return matrix

    class WarnsExpm:
        @staticmethod
        def logm(_matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            return np.array([[0.0, -0.1], [0.0, 0.0]])

        @staticmethod
        def expm(_matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            warnings.warn(RuntimeWarning("expm inestable"), stacklevel=2)
            return np.eye(2)

    class RaisesExpm(WarnsExpm):
        @staticmethod
        def expm(_matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            raise ValueError("expm roto")

    def patch_scipy(fake: object) -> None:
        def fake_import(name: str) -> Any:
            if name == "scipy.linalg":
                return fake
            return original_import(name)

        monkeypatch.setattr(term_module.importlib, "import_module", fake_import)

    matrix = np.array([[0.8, 0.2], [0.0, 1.0]])
    patch_scipy(RaisesLogm)
    failed = diagnose_embedding(matrix, delta_t=1.0, config=_cfg(states=("A", "default")))
    assert failed.embedding_flags == ("logm_failed",)

    patch_scipy(NonFiniteLogm)
    non_finite = diagnose_embedding(matrix, delta_t=1.0, config=_cfg(states=("A", "default")))
    assert non_finite.embedding_flags == ("logm_non_finite",)

    patch_scipy(WarnsExpm)
    with pytest.raises(MarkovEmbeddingError, match="warning"):
        diagnose_embedding(
            matrix,
            delta_t=1.0,
            config=_cfg(states=("A", "default"), embedding_policy="regularize"),
        )

    patch_scipy(RaisesExpm)
    with pytest.raises(MarkovEmbeddingError, match="expm"):
        diagnose_embedding(
            matrix,
            delta_t=1.0,
            config=_cfg(states=("A", "default"), embedding_policy="regularize"),
        )

    with pytest.raises(MarkovEmbeddingError, match="delta_t"):
        diagnose_embedding(matrix, delta_t=0.0, config=_cfg(states=("A", "default")))


def test_aalen_johansen_simple_product_integral_golden() -> None:
    cfg = _cfg(states=("A", "default"), projection_mode="aalen_johansen")
    frame = pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 3, 3],
            "time": [0.0, 1.0, 0.0, 2.0, 0.0, 2.0],
            "state": ["A", "default", "A", "default", "A", "A"],
            "event_time": [math.nan, 1.0, math.nan, 2.0, math.nan, math.nan],
        }
    )

    projected = aalen_johansen(frame, config=cfg)

    assert list(projected) == [1.0, 2.0]
    assert_allclose(projected[1.0], np.array([[2.0 / 3.0, 1.0 / 3.0], [0.0, 1.0]]))
    assert_allclose(projected[2.0], np.array([[1.0 / 3.0, 2.0 / 3.0], [0.0, 1.0]]))
    term = markov_term_structure(projected, config=cfg)
    assert term.loc["state:A|1", "pd_cumulative"] == pytest.approx(1.0 / 3.0)
    assert term.loc["state:A|2", "pd_cumulative"] == pytest.approx(2.0 / 3.0)
    assert term.loc["state:A|2", "method"] == "aalen_johansen"


def test_aalen_johansen_risk_set_cierra_en_event_time_no_snapshot() -> None:
    """C3: una entidad sale del conjunto en riesgo en su event_time real, no en el snapshot.

    Ejemplo cerrado (auditoría): 2 cuentas A->default con event_times 3 y 7, snapshots {0, 10}. En
    t=7 la cuenta que transitó en t=3 ya NO está en riesgo -> hazard=1/1 -> pd_cum=1.0. Antes del
    fix el intervalo de riesgo se cerraba en el snapshot 10, ambas seguían contadas -> hazard=1/2 ->
    pd_cum=0.75 (Y_i sobreestimado -> hazard subestimado -> sub-provisión IFRS9).
    """
    cfg = _cfg(states=("A", "default"), projection_mode="aalen_johansen")
    frame = pd.DataFrame(
        {
            "id": [1, 1, 2, 2],
            "time": [0.0, 10.0, 0.0, 10.0],
            "state": ["A", "default", "A", "default"],
            "event_time": [math.nan, 3.0, math.nan, 7.0],
        }
    )

    projected = aalen_johansen(frame, config=cfg)

    assert list(projected) == [3.0, 7.0]
    # En t=3 solo transitó una cuenta (ambas en riesgo): hazard=1/2 -> pd_cum=0.5.
    assert projected[3.0][0, 1] == pytest.approx(0.5)
    # En t=7 la cuenta que ya hizo default en t=3 salió del risk set: hazard=1/1 -> pd_cum=1.0.
    assert projected[7.0][0, 1] == pytest.approx(1.0)

    term = markov_term_structure(projected, config=cfg)
    assert term.loc["state:A|7", "pd_cumulative"] == pytest.approx(1.0)


def test_aalen_johansen_solo_en_projection_mode_y_valida_input() -> None:
    with pytest.raises(MarkovTransformError, match="projection_mode"):
        aalen_johansen(pd.DataFrame(), config=_cfg(states=("A", "default")))

    cfg = _cfg(states=("A", "default"), projection_mode="aalen_johansen")
    with pytest.raises(MarkovInputError, match="pandas"):
        aalen_johansen({"id": [1]}, config=cfg)
    with pytest.raises(MarkovInputError, match="Faltan columnas"):
        aalen_johansen(pd.DataFrame({"id": [1]}), config=cfg)


def test_aalen_johansen_defensas_de_eventos_y_pesos() -> None:
    cfg = _cfg(states=("A", "default"), projection_mode="aalen_johansen")
    no_events = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [0.0, 1.0],
            "state": ["A", "A"],
            "event_time": [math.nan, math.nan],
        }
    )
    with pytest.raises(MarkovTransformError, match="snapshots"):
        aalen_johansen(no_events, config=cfg)

    unknown = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [0.0, 1.0],
            "state": ["A", "Z"],
            "event_time": [math.nan, 1.0],
        }
    )
    with pytest.raises(MarkovInputError, match="fuera de catálogo"):
        aalen_johansen(unknown, config=cfg)

    non_increasing = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [1.0, 1.0],
            "state": ["A", "default"],
            "event_time": [math.nan, 1.0],
        }
    )
    with pytest.raises(MarkovInputError, match="crecer estrictamente"):
        aalen_johansen(non_increasing, config=cfg)

    leaves_absorbing = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [0.0, 1.0],
            "state": ["default", "A"],
            "event_time": [math.nan, 1.0],
        }
    )
    with pytest.raises(MarkovInputError, match="absorbente"):
        aalen_johansen(leaves_absorbing, config=cfg)

    missing_event = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [0.0, 1.0],
            "state": ["A", "default"],
            "event_time": [math.nan, math.nan],
        }
    )
    with pytest.raises(MarkovInputError, match="tiempo de evento"):
        aalen_johansen(missing_event, config=cfg)

    outside_event = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [0.0, 1.0],
            "state": ["A", "default"],
            "event_time": [math.nan, 2.0],
        }
    )
    with pytest.raises(MarkovInputError, match="intervalo"):
        aalen_johansen(outside_event, config=cfg)

    event_without_b = pd.DataFrame(
        {
            "id": [1, 1, 2, 2],
            "time": [0.0, 1.0, 0.0, 1.0],
            "state": ["A", "default", "B", "B"],
            "event_time": [math.nan, 1.0, math.nan, math.nan],
        }
    )
    projected = aalen_johansen(
        event_without_b,
        config=_cfg(states=("A", "B", "default"), projection_mode="aalen_johansen"),
    )
    assert projected[1.0][1, 1] == pytest.approx(1.0)

    zero_weight_cfg = MarkovConfig(
        input=MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            transition_time_col="event_time",
            weight_col="weight",
        ),
        states=MarkovStateConfig(states=("A", "default")),
        estimation=MarkovEstimationConfig(use_weights=True),
        dynamics=MarkovDynamicsConfig(projection_mode="aalen_johansen"),
    )
    zero_weight = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [0.0, 1.0],
            "state": ["A", "default"],
            "event_time": [math.nan, 1.0],
            "weight": [0.0, 0.0],
        }
    )
    with pytest.raises(MarkovTransformError, match="Riesgo nulo"):
        aalen_johansen(zero_weight, config=zero_weight_cfg)

    negative_weight = zero_weight.copy(deep=True)
    negative_weight.loc[0, "weight"] = -1.0
    with pytest.raises(MarkovInputError, match="pesos no negativos"):
        aalen_johansen(negative_weight, config=zero_weight_cfg)

    no_weight_col_cfg = MarkovConfig.model_construct(
        schema_version="1.0.0",
        type="standard",
        input=MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            transition_time_col="event_time",
        ),
        states=MarkovStateConfig(states=("A", "default")),
        estimation=MarkovEstimationConfig(use_weights=True),
        dynamics=MarkovDynamicsConfig(projection_mode="aalen_johansen"),
        validation=MarkovValidationConfig(),
        fail_on_falta_dato=True,
    )
    fallback_weight = pd.DataFrame(
        {
            "id": [1, 1],
            "time": [0.0, 1.0],
            "state": ["A", "default"],
            "event_time": [math.nan, 1.0],
        }
    )
    assert aalen_johansen(fallback_weight, config=no_weight_col_cfg)[1.0][0, 1] == pytest.approx(
        1.0
    )

    no_event_col_cfg = MarkovConfig.model_construct(
        schema_version="1.0.0",
        type="standard",
        input=MarkovInputConfig(id_col="id", time_col="time", state_col="state"),
        states=MarkovStateConfig(states=("A", "default")),
        estimation=MarkovEstimationConfig(),
        dynamics=MarkovDynamicsConfig(projection_mode="aalen_johansen"),
        validation=MarkovValidationConfig(),
        fail_on_falta_dato=True,
    )
    with pytest.raises(MarkovInputError, match="transition_time_col"):
        aalen_johansen(pd.DataFrame(), config=no_event_col_cfg)


def test_term_structure_import_liviano_sin_dependencias_nuevas() -> None:
    code = (
        "import sys;"
        "import nikodym.markov.config;"
        "baseline=set(sys.modules);"
        "import nikodym.markov.term_structure;"
        "blocked=[m for m in ('pandas','scipy','nikodym.markov.transition') "
        "if m in sys.modules and m not in baseline];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_helpers_defensivos_privados_y_dependencias_faltantes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg(states=("A", "default"))
    assert term_module._embedding_flags(
        np.array([[0.0, 0.0], [math.inf, 0.0]]),
        imaginary_norm=0.0,
        config=cfg,
        np=np,
    ) == ("generator_non_finite",)
    flags = term_module._embedding_flags(
        np.array([[0.1, -0.2], [0.1, 0.0]]),
        imaginary_norm=1.0,
        config=cfg,
        np=np,
    )
    assert set(flags) == {
        "absorbing_row_nonzero",
        "complex_principal_log",
        "generator_diagonal_positive",
        "generator_offdiag_negative",
        "generator_rows_not_conservative",
    }

    with pytest.raises(MarkovTransformError, match="booleano"):
        term_module._time_value(True)
    with pytest.raises(MarkovTransformError, match="numérico"):
        term_module._time_value("x")
    with pytest.raises(MarkovTransformError, match="finito"):
        term_module._time_value(math.inf)
    with pytest.raises(MarkovTransformError, match=r"\[0, 1\]"):
        term_module._unit_probability(1.1, tol=1e-10, field_name="pd")
    with pytest.raises(MarkovTransformError, match="no negativo"):
        term_module._non_negative_float(-1.0)
    with pytest.raises(MarkovTransformError, match="no finito"):
        term_module._clean_float(math.inf)

    with pytest.raises(NonStochasticMatrixError, match="states"):
        validate_transition_matrix(np.eye(1), states=(), absorbing_states=(), tol=1e-10)
    with pytest.raises(NonStochasticMatrixError, match="duplicados"):
        validate_transition_matrix(np.eye(2), states=("A", "A"), absorbing_states=(), tol=1e-10)
    with pytest.raises(NonStochasticMatrixError, match="subconjunto"):
        validate_transition_matrix(np.eye(1), states=("A",), absorbing_states=("B",), tol=1e-10)
    with pytest.raises(NonStochasticMatrixError, match="tolerancia"):
        validate_transition_matrix(np.eye(1), states=("A",), absorbing_states=(), tol=math.inf)
    with pytest.raises(MarkovTransformError, match="numérica"):
        validate_transition_matrix(np.array([["x"]]), states=("A",), absorbing_states=(), tol=1e-10)

    original_import = term_module.importlib.import_module

    def missing_import(name: str) -> Any:
        if name in {"numpy", "pandas", "scipy.linalg"}:
            raise ModuleNotFoundError(name)
        return original_import(name)

    monkeypatch.setattr(term_module.importlib, "import_module", missing_import)
    with pytest.raises(MissingDependencyError, match="numpy"):
        term_module._import_numpy()
    with pytest.raises(MissingDependencyError, match="pandas"):
        term_module._import_pandas()
    with pytest.raises(MissingDependencyError, match=r"nikodym\[markov\]"):
        term_module._import_scipy_linalg()
