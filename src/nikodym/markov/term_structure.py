"""Proyección Markov y term-structure PD como funciones libres (SDD-19 §4).

Este módulo concentra las validaciones públicas de matrices estocásticas y generadores, la
proyección Chapman-Kolmogorov, el estimador Aalen-Johansen básico, el diagnóstico de embedding y
la construcción tidy de PD lifetime. Mantiene liviano ``import nikodym.markov``: ``numpy``,
``pandas`` y ``scipy`` se importan solo dentro de funciones.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.markov.config import MarkovConfig
from nikodym.markov.exceptions import (
    InvalidGeneratorError,
    MarkovEmbeddingError,
    MarkovInputError,
    MarkovTransformError,
    NonStochasticMatrixError,
)
from nikodym.markov.results import EmbeddingDiagnostics

if TYPE_CHECKING:
    import numpy
    import pandas

    DataFrame: TypeAlias = pandas.DataFrame
    NDArrayFloat: TypeAlias = numpy.ndarray[Any, numpy.dtype[numpy.float64]]
else:
    DataFrame: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any

__all__ = [
    "aalen_johansen",
    "chapman_kolmogorov",
    "diagnose_embedding",
    "markov_term_structure",
    "validate_generator",
    "validate_transition_matrix",
]

_DEFAULT_STOCHASTIC_TOL = 1e-10
_MARKOV_EXTRA_MESSAGE = "Las funciones Markov requieren scipy.linalg; instale nikodym[markov]."
_PD_SOURCE = "markov"
_SEGMENT = None
_SCENARIO = None
_TERM_STRUCTURE_COLUMNS: tuple[str, ...] = (
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
_WARNING_HAZARD_UNDEFINED = "hazard_undefined_zero_survival"


@dataclass(frozen=True)
class _RiskInterval:
    from_state: str
    start_time: float
    end_time: float
    weight: float


@dataclass(frozen=True)
class _AjEvent:
    event_time: float
    from_state: str
    to_state: str
    weight: float


def validate_transition_matrix(
    matrix: numpy.ndarray[Any, numpy.dtype[numpy.float64]],
    *,
    states: tuple[str, ...],
    absorbing_states: tuple[str, ...],
    tol: float,
) -> None:
    """Valida una matriz de transición estocástica sin mutar la entrada."""
    np, candidate = _array_copy(matrix)
    _validate_tol(tol, error_cls=NonStochasticMatrixError, name="tol")
    _validate_state_contract(
        states=states,
        absorbing_states=absorbing_states,
        error_cls=NonStochasticMatrixError,
    )
    expected_shape = (len(states), len(states))
    if candidate.shape != expected_shape:
        raise NonStochasticMatrixError(
            f"La matriz P debe ser cuadrada de dimensión {len(states)}; shape={candidate.shape}."
        )

    absorbing = set(absorbing_states)
    for row_index, state in enumerate(states):
        row = candidate[row_index, :]
        if not bool(np.all(np.isfinite(row))):
            raise NonStochasticMatrixError(f"La fila de P contiene valores no finitos: {state!r}.")
        low = float(np.min(row))
        high = float(np.max(row))
        if low < -tol or high > 1.0 + tol:
            raise NonStochasticMatrixError(
                "La matriz P contiene probabilidades fuera de [0, 1]: "
                f"state={state!r}, min={low}, max={high}, tol={tol}."
            )
        if state in absorbing:
            expected = np.zeros(len(states), dtype="float64")
            expected[row_index] = 1.0
            if not bool(np.allclose(row, expected, rtol=0.0, atol=tol)):
                raise NonStochasticMatrixError(
                    f"El estado absorbente {state!r} debe tener fila identidad en P."
                )
            continue
        row_sum = float(np.sum(row))
        if not math.isclose(row_sum, 1.0, rel_tol=0.0, abs_tol=tol):
            raise NonStochasticMatrixError(
                f"La fila de P no suma 1: state={state!r}, row_sum={row_sum}, tol={tol}."
            )


def validate_generator(
    generator: numpy.ndarray[Any, numpy.dtype[numpy.float64]],
    *,
    states: tuple[str, ...],
    absorbing_states: tuple[str, ...],
    tol: float,
) -> None:
    """Valida un generador conservativo Markov sin mutar la entrada."""
    np, candidate = _array_copy(generator)
    _validate_tol(tol, error_cls=InvalidGeneratorError, name="tol")
    _validate_state_contract(
        states=states,
        absorbing_states=absorbing_states,
        error_cls=InvalidGeneratorError,
    )
    expected_shape = (len(states), len(states))
    if candidate.shape != expected_shape:
        raise InvalidGeneratorError(
            f"El generador Q debe ser cuadrado de dimensión {len(states)}; shape={candidate.shape}."
        )

    absorbing = set(absorbing_states)
    for row_index, state in enumerate(states):
        row = candidate[row_index, :]
        if not bool(np.all(np.isfinite(row))):
            raise InvalidGeneratorError(f"La fila de Q contiene valores no finitos: {state!r}.")
        if state in absorbing:
            if not bool(np.allclose(row, 0.0, rtol=0.0, atol=tol)):
                raise InvalidGeneratorError(
                    f"El estado absorbente {state!r} debe tener fila cero en Q."
                )
            continue

        diagonal = float(row[row_index])
        off_diagonal = _off_diagonal(row, row_index, np=np)
        min_offdiag = float(np.min(off_diagonal)) if off_diagonal.size else 0.0
        if min_offdiag < -tol:
            raise InvalidGeneratorError(
                "El generador Q contiene intensidad off-diagonal negativa: "
                f"state={state!r}, min_offdiag={min_offdiag}, tol={tol}."
            )
        if diagonal > tol:
            raise InvalidGeneratorError(
                f"La diagonal de Q debe ser no positiva: state={state!r}, diag={diagonal}."
            )
        row_sum = float(np.sum(row))
        if not math.isclose(row_sum, 0.0, rel_tol=0.0, abs_tol=tol):
            raise InvalidGeneratorError(
                f"La fila de Q no suma 0: state={state!r}, row_sum={row_sum}, tol={tol}."
            )


def chapman_kolmogorov(
    matrices: Sequence[numpy.ndarray[Any, numpy.dtype[numpy.float64]]],
    *,
    homogeneous: bool,
    horizons: Sequence[int],
) -> dict[int, numpy.ndarray[Any, numpy.dtype[numpy.float64]]]:
    """Proyecta matrices acumuladas ``P(0,t)`` por Chapman-Kolmogorov."""
    np = _import_numpy()
    values = _validate_integer_horizons(horizons)
    base_matrices = tuple(np.array(matrix, dtype="float64", copy=True) for matrix in matrices)
    if not base_matrices:
        raise MarkovTransformError("matrices debe contener al menos una matriz de transición.")

    states, absorbing_states = _infer_states_and_absorbing(base_matrices[0], np=np)
    for matrix in base_matrices:
        validate_transition_matrix(
            matrix,
            states=states,
            absorbing_states=absorbing_states,
            tol=_DEFAULT_STOCHASTIC_TOL,
        )

    if homogeneous:
        base = base_matrices[0]
        projected: dict[int, NDArrayFloat] = {}
        for horizon in values:
            matrix_power = cast("NDArrayFloat", np.linalg.matrix_power(base, horizon))
            validate_transition_matrix(
                matrix_power,
                states=states,
                absorbing_states=absorbing_states,
                tol=_DEFAULT_STOCHASTIC_TOL,
            )
            projected[horizon] = _normalize_array(matrix_power, np=np)
        return projected

    max_horizon = max(values)
    if max_horizon > len(base_matrices):
        raise MarkovTransformError(
            "Faltan matrices de un período para cubrir el horizonte no homogéneo: "
            f"horizon={max_horizon}, matrices={len(base_matrices)}."
        )

    cumulative = np.eye(len(states), dtype="float64")
    requested = set(values)
    projected = {}
    for period, matrix in enumerate(base_matrices[:max_horizon], start=1):
        cumulative = cast("NDArrayFloat", cumulative @ matrix)
        if period in requested:
            validate_transition_matrix(
                cumulative,
                states=states,
                absorbing_states=absorbing_states,
                tol=_DEFAULT_STOCHASTIC_TOL,
            )
            projected[period] = _normalize_array(cumulative, np=np)
    return projected


def aalen_johansen(
    frame: pandas.DataFrame,
    *,
    config: MarkovConfig,
) -> dict[float, numpy.ndarray[Any, numpy.dtype[numpy.float64]]]:
    """Calcula matrices acumuladas Aalen-Johansen desde un panel con tiempos de evento."""
    if config.dynamics.projection_mode != "aalen_johansen":
        raise MarkovTransformError(
            "aalen_johansen solo se activa con projection_mode='aalen_johansen'."
        )

    pd = _import_pandas()
    np = _import_numpy()
    if not isinstance(frame, pd.DataFrame):
        raise MarkovInputError("aalen_johansen requiere un pandas.DataFrame.")

    copied = cast("DataFrame", frame.copy(deep=True))
    event_col = config.input.transition_time_col
    if event_col is None:
        raise MarkovInputError("aalen_johansen exige input.transition_time_col.")
    required = (config.input.id_col, config.input.time_col, config.input.state_col, event_col)
    missing = [column for column in required if column not in copied.columns]
    if missing:
        raise MarkovInputError(f"Faltan columnas requeridas para Aalen-Johansen: {missing}.")

    intervals, events = _aj_intervals_and_events(copied, config=config, pd=pd)
    if not events:
        raise MarkovTransformError(
            "Aalen-Johansen exige tiempos de evento; use matrices discretas para snapshots."
        )

    states = config.states.states
    state_index = {state: index for index, state in enumerate(states)}
    absorbing = set(config.states.absorbing_states)
    cumulative = np.eye(len(states), dtype="float64")
    projected: dict[float, NDArrayFloat] = {}
    for event_time in tuple(sorted({event.event_time for event in events})):
        increment = np.zeros((len(states), len(states)), dtype="float64")
        for from_state in states:
            if from_state in absorbing:
                continue
            risk = _risk_at(intervals, state=from_state, event_time=event_time)
            outgoing = [
                event
                for event in events
                if event.event_time == event_time and event.from_state == from_state
            ]
            if not outgoing:
                continue
            if risk <= 0.0:
                raise MarkovTransformError(
                    "Riesgo nulo en Aalen-Johansen con eventos observados: "
                    f"state={from_state!r}, event_time={event_time}."
                )
            row = state_index[from_state]
            for event in outgoing:
                increment[row, state_index[event.to_state]] += event.weight / risk
            increment[row, row] = -float(np.sum(increment[row, :]))

        step = np.eye(len(states), dtype="float64") + increment
        validate_transition_matrix(
            step,
            states=states,
            absorbing_states=config.states.absorbing_states,
            tol=config.validation.stochastic_tol,
        )
        cumulative = cast("NDArrayFloat", cumulative @ step)
        validate_transition_matrix(
            cumulative,
            states=states,
            absorbing_states=config.states.absorbing_states,
            tol=config.validation.stochastic_tol,
        )
        projected[event_time] = _normalize_array(cumulative, np=np)
    return projected


def diagnose_embedding(
    matrix: numpy.ndarray[Any, numpy.dtype[numpy.float64]],
    *,
    delta_t: float,
    config: MarkovConfig,
) -> EmbeddingDiagnostics:
    """Diagnostica si ``P`` admite un generador principal válido."""
    np, candidate = _array_copy(matrix)
    _validate_delta_t(delta_t)
    validate_transition_matrix(
        candidate,
        states=config.states.states,
        absorbing_states=config.states.absorbing_states,
        tol=config.validation.stochastic_tol,
    )
    scipy_linalg = _import_scipy_linalg()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            log_matrix = scipy_linalg.logm(candidate)
    except Warning as exc:
        return _embedding_failure(
            flags=("logm_warning",),
            imaginary_norm=None,
            q_candidate=None,
            original=candidate,
            delta_t=delta_t,
            config=config,
            np=np,
            scipy_linalg=scipy_linalg,
            cause=exc,
        )
    except (ArithmeticError, ValueError, OverflowError) as exc:
        return _embedding_failure(
            flags=("logm_failed",),
            imaginary_norm=None,
            q_candidate=None,
            original=candidate,
            delta_t=delta_t,
            config=config,
            np=np,
            scipy_linalg=scipy_linalg,
            cause=exc,
        )

    log_array = np.array(log_matrix, dtype="complex128", copy=True)
    if not bool(np.all(np.isfinite(log_array))):
        return _embedding_failure(
            flags=("logm_non_finite",),
            imaginary_norm=None,
            q_candidate=None,
            original=candidate,
            delta_t=delta_t,
            config=config,
            np=np,
            scipy_linalg=scipy_linalg,
            cause=None,
        )

    imaginary_norm = _non_negative_float(float(np.linalg.norm(np.imag(log_array))))
    q_candidate = np.array(np.real(log_array) / delta_t, dtype="float64", copy=True)
    flags = _embedding_flags(q_candidate, imaginary_norm=imaginary_norm, config=config, np=np)
    if not flags:
        validate_generator(
            q_candidate,
            states=config.states.states,
            absorbing_states=config.states.absorbing_states,
            tol=config.validation.generator_tol,
        )
        return EmbeddingDiagnostics(
            embedding_status="valid_principal_log",
            embedding_flags=(),
            generator_candidate=_normalize_array(q_candidate, np=np),
            imaginary_norm=imaginary_norm,
            distance_fro=None,
            adjusted=False,
        )

    return _embedding_failure(
        flags=flags,
        imaginary_norm=imaginary_norm,
        q_candidate=q_candidate,
        original=candidate,
        delta_t=delta_t,
        config=config,
        np=np,
        scipy_linalg=scipy_linalg,
        cause=None,
    )


def markov_term_structure(
    transitions: Mapping[int | float, numpy.ndarray[Any, numpy.dtype[numpy.float64]]],
    *,
    config: MarkovConfig,
) -> pandas.DataFrame:
    """Convierte matrices acumuladas ``P(0,t)`` en term-structure PD tidy."""
    pd = _import_pandas()
    np = _import_numpy()
    if not transitions:
        raise MarkovTransformError("transitions debe contener al menos un horizonte.")

    states = config.states.states
    default_index = states.index(config.states.default_state)
    absorbing = set(config.states.absorbing_states)
    previous_pd = {state: 1.0 if state == config.states.default_state else 0.0 for state in states}
    rows: list[dict[str, Any]] = []
    index: list[str] = []
    method = (
        "aalen_johansen"
        if config.dynamics.projection_mode == "aalen_johansen"
        else config.estimation.method
    )

    ordered = tuple(
        sorted(
            ((_time_value(horizon), horizon, matrix) for horizon, matrix in transitions.items()),
            key=lambda item: item[0],
        )
    )
    for ordinal, (time_value, _raw_horizon, matrix) in enumerate(ordered, start=1):
        candidate = np.array(matrix, dtype="float64", copy=True)
        validate_transition_matrix(
            candidate,
            states=states,
            absorbing_states=config.states.absorbing_states,
            tol=config.validation.stochastic_tol,
        )
        period = _period_number(time_value, ordinal=ordinal)
        for from_index, state in enumerate(states):
            if state in absorbing:
                continue
            pd_cumulative = _unit_probability(
                float(candidate[from_index, default_index]),
                tol=config.validation.stochastic_tol,
                field_name="pd_cumulative",
            )
            old_pd = previous_pd[state]
            pd_marginal = _pd_marginal(
                pd_cumulative,
                old_pd,
                tol=config.validation.stochastic_tol,
            )
            previous_survival = _unit_probability(
                1.0 - old_pd,
                tol=config.validation.stochastic_tol,
                field_name="survival_previa",
            )
            warning_codes: tuple[str, ...] = ()
            if previous_survival <= config.validation.stochastic_tol:
                hazard = 0.0
                warning_codes = (_WARNING_HAZARD_UNDEFINED,)
            else:
                hazard = _unit_probability(
                    pd_marginal / previous_survival,
                    tol=config.validation.stochastic_tol,
                    field_name="hazard",
                )
            survival = _unit_probability(
                1.0 - pd_cumulative,
                tol=config.validation.stochastic_tol,
                field_name="survival",
            )
            rows.append(
                {
                    "row_id": f"state:{state}",
                    "segment": _SEGMENT,
                    "partition": None,
                    "period": period,
                    "time_value": time_value,
                    "hazard": hazard,
                    "survival": survival,
                    "pd_marginal": pd_marginal,
                    "pd_cumulative": pd_cumulative,
                    "method": method,
                    "pd_source": _PD_SOURCE,
                    "scenario": _SCENARIO,
                    "warning_codes": warning_codes,
                }
            )
            index.append(f"state:{state}|{period}")
            previous_pd[state] = pd_cumulative

    frame = pd.DataFrame.from_records(rows, columns=_TERM_STRUCTURE_COLUMNS)
    frame.index = pd.Index(index)
    return _normalize_frame(frame)


def _array_copy(value: Any) -> tuple[Any, NDArrayFloat]:
    np = _import_numpy()
    try:
        candidate = np.array(value, dtype="float64", copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarkovTransformError("La matriz Markov debe ser numérica.") from exc
    return np, cast("NDArrayFloat", candidate)


def _validate_state_contract(
    *,
    states: tuple[str, ...],
    absorbing_states: tuple[str, ...],
    error_cls: type[Exception],
) -> None:
    if not states:
        raise error_cls("states debe contener al menos un estado.")
    if len(set(states)) != len(states):
        raise error_cls("states no puede contener duplicados.")
    unknown_absorbing = sorted(set(absorbing_states) - set(states))
    if unknown_absorbing:
        raise error_cls(f"absorbing_states debe ser subconjunto de states: {unknown_absorbing}.")


def _validate_tol(tol: float, *, error_cls: type[Exception], name: str) -> None:
    if not math.isfinite(tol) or tol < 0.0:
        raise error_cls(f"{name} debe ser una tolerancia finita y no negativa.")


def _off_diagonal(row: NDArrayFloat, row_index: int, *, np: Any) -> NDArrayFloat:
    if len(row) == 1:
        return cast("NDArrayFloat", np.array([], dtype="float64"))
    return cast("NDArrayFloat", np.delete(row, row_index))


def _validate_integer_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    if not horizons:
        raise MarkovTransformError("horizons debe contener al menos un horizonte.")
    values: list[int] = []
    for position, value in enumerate(horizons):
        if isinstance(value, bool):
            raise MarkovTransformError(
                f"horizons contiene un booleano en posición {position}: {value!r}."
            )
        numeric = float(value)
        if not math.isfinite(numeric) or numeric <= 0.0:
            raise MarkovTransformError(
                "horizons debe contener enteros positivos y finitos: "
                f"posición={position}, valor={value!r}."
            )
        rounded = round(numeric)
        if not math.isclose(numeric, rounded, rel_tol=0.0, abs_tol=1e-12):
            raise MarkovTransformError(f"horizons debe contener enteros: valor={value!r}.")
        values.append(int(rounded))
    ordered = tuple(sorted(values))
    if len(set(ordered)) != len(ordered):
        raise MarkovTransformError(f"horizons contiene valores duplicados: {horizons!r}.")
    return ordered


def _infer_states_and_absorbing(
    matrix: NDArrayFloat,
    *,
    np: Any,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if matrix.ndim != 2:
        raise NonStochasticMatrixError(f"La matriz P debe ser bidimensional; ndim={matrix.ndim}.")
    states = tuple(f"state_{index}" for index in range(int(matrix.shape[0])))
    absorbing: list[str] = []
    for row_index, state in enumerate(states):
        expected = np.zeros(len(states), dtype="float64")
        expected[row_index] = 1.0
        if matrix.shape == (len(states), len(states)) and bool(
            np.allclose(matrix[row_index, :], expected, rtol=0.0, atol=_DEFAULT_STOCHASTIC_TOL)
        ):
            absorbing.append(state)
    return states, tuple(absorbing)


def _aj_intervals_and_events(
    frame: DataFrame,
    *,
    config: MarkovConfig,
    pd: Any,
) -> tuple[tuple[_RiskInterval, ...], tuple[_AjEvent, ...]]:
    sorted_frame = frame.sort_values(
        [config.input.id_col, config.input.time_col],
        kind="mergesort",
    )
    intervals: list[_RiskInterval] = []
    events: list[_AjEvent] = []
    states = set(config.states.states)
    absorbing = set(config.states.absorbing_states)
    columns = tuple(str(column) for column in sorted_frame.columns)
    for _entity, group in sorted_frame.groupby(config.input.id_col, sort=False, dropna=False):
        records = list(group.itertuples(index=False))
        for current, following in pairwise(records):
            current_row = dict(zip(columns, current, strict=True))
            next_row = dict(zip(columns, following, strict=True))
            from_state = str(current_row[config.input.state_col])
            to_state = str(next_row[config.input.state_col])
            if from_state not in states or to_state not in states:
                raise MarkovInputError(
                    f"Estados fuera de catálogo Markov: from={from_state!r}, to={to_state!r}."
                )
            start = _time_value(current_row[config.input.time_col])
            end = _time_value(next_row[config.input.time_col])
            if end <= start:
                raise MarkovInputError("Los tiempos deben crecer estrictamente por id.")
            if from_state in absorbing and to_state != from_state:
                raise MarkovInputError(
                    "Transición observada desde estado absorbente hacia otro estado: "
                    f"from_state={from_state!r}, to_state={to_state!r}."
                )
            weight = _row_weight(current_row, config=config)
            intervals.append(
                _RiskInterval(
                    from_state=from_state,
                    start_time=start,
                    end_time=end,
                    weight=weight,
                )
            )
            if from_state == to_state:
                continue
            event_col = config.input.transition_time_col
            if event_col is None or bool(pd.isna(next_row[event_col])):
                raise MarkovInputError("Toda transición Aalen-Johansen exige tiempo de evento.")
            event_time = _time_value(next_row[event_col])
            if event_time <= start or event_time > end:
                raise MarkovInputError(
                    "transition_time_col debe quedar dentro del intervalo de transición."
                )
            events.append(
                _AjEvent(
                    event_time=event_time,
                    from_state=from_state,
                    to_state=to_state,
                    weight=weight,
                )
            )
    return tuple(intervals), tuple(events)


def _row_weight(row: Mapping[str, Any], *, config: MarkovConfig) -> float:
    if not config.estimation.use_weights:
        return 1.0
    weight_col = config.input.weight_col
    if weight_col is None:
        return 1.0
    weight = _time_value(row[weight_col])
    if weight < 0.0:
        raise MarkovInputError("weight_col debe contener pesos no negativos.")
    return weight


def _risk_at(intervals: tuple[_RiskInterval, ...], *, state: str, event_time: float) -> float:
    return _clean_float(
        sum(
            interval.weight
            for interval in intervals
            if interval.from_state == state
            and interval.start_time < event_time
            and event_time <= interval.end_time
        )
    )


def _embedding_flags(
    q_candidate: NDArrayFloat,
    *,
    imaginary_norm: float,
    config: MarkovConfig,
    np: Any,
) -> tuple[str, ...]:
    flags: list[str] = []
    if imaginary_norm > config.validation.imaginary_tol:
        flags.append("complex_principal_log")
    if not bool(np.all(np.isfinite(q_candidate))):
        flags.append("generator_non_finite")
        return tuple(flags)

    states = config.states.states
    absorbing = set(config.states.absorbing_states)
    tol = config.validation.generator_tol
    for row_index, state in enumerate(states):
        row = q_candidate[row_index, :]
        if state in absorbing:
            if not bool(np.allclose(row, 0.0, rtol=0.0, atol=tol)):
                flags.append("absorbing_row_nonzero")
            continue
        diagonal = float(row[row_index])
        off_diagonal = _off_diagonal(row, row_index, np=np)
        min_offdiag = float(np.min(off_diagonal)) if off_diagonal.size else 0.0
        if min_offdiag < -tol:
            flags.append("generator_offdiag_negative")
        if diagonal > tol:
            flags.append("generator_diagonal_positive")
        row_sum = float(np.sum(row))
        if not math.isclose(row_sum, 0.0, rel_tol=0.0, abs_tol=tol):
            flags.append("generator_rows_not_conservative")
    return tuple(dict.fromkeys(flags))


def _embedding_failure(
    *,
    flags: tuple[str, ...],
    imaginary_norm: float | None,
    q_candidate: NDArrayFloat | None,
    original: NDArrayFloat,
    delta_t: float,
    config: MarkovConfig,
    np: Any,
    scipy_linalg: Any,
    cause: BaseException | None,
) -> EmbeddingDiagnostics:
    policy = config.dynamics.embedding_policy
    normalized_flags = tuple(dict.fromkeys(flags))
    if policy == "diagnose":
        return EmbeddingDiagnostics(
            embedding_status="invalid_principal_log",
            embedding_flags=normalized_flags,
            generator_candidate=(
                None if q_candidate is None else _normalize_array(q_candidate, np=np)
            ),
            imaginary_norm=imaginary_norm,
            distance_fro=None,
            adjusted=False,
        )
    if policy == "forbid" or q_candidate is None:
        message = f"Embedding Markov inválido: flags={normalized_flags}."
        raise MarkovEmbeddingError(message) from cause

    regularized = _regularize_generator(q_candidate, config=config, np=np)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            p_regularized = scipy_linalg.expm(regularized * delta_t)
    except Warning as exc:
        raise MarkovEmbeddingError("La regularización de embedding emitió un warning.") from exc
    except (ArithmeticError, ValueError, OverflowError) as exc:
        raise MarkovEmbeddingError("La regularización de embedding no pudo calcular expm.") from exc

    p_regularized = np.array(p_regularized, dtype="float64", copy=True)
    validate_transition_matrix(
        p_regularized,
        states=config.states.states,
        absorbing_states=config.states.absorbing_states,
        tol=config.validation.stochastic_tol,
    )
    distance = _non_negative_float(float(np.linalg.norm(p_regularized - original, ord="fro")))
    return EmbeddingDiagnostics(
        embedding_status="regularized_principal_log",
        embedding_flags=tuple(dict.fromkeys((*normalized_flags, "regularized"))),
        generator_candidate=_normalize_array(regularized, np=np),
        imaginary_norm=imaginary_norm,
        distance_fro=distance,
        adjusted=True,
    )


def _regularize_generator(
    q_candidate: NDArrayFloat,
    *,
    config: MarkovConfig,
    np: Any,
) -> NDArrayFloat:
    regularized = np.array(q_candidate, dtype="float64", copy=True)
    states = config.states.states
    absorbing = set(config.states.absorbing_states)
    for row_index, state in enumerate(states):
        if state in absorbing:
            regularized[row_index, :] = 0.0
            continue
        for column_index in range(len(states)):
            if column_index == row_index:
                continue
            if regularized[row_index, column_index] < 0.0:
                regularized[row_index, column_index] = 0.0
        row_total = float(np.sum(regularized[row_index, :]))
        regularized[row_index, row_index] = -float(row_total - regularized[row_index, row_index])
    validate_generator(
        regularized,
        states=states,
        absorbing_states=config.states.absorbing_states,
        tol=config.validation.generator_tol,
    )
    return _normalize_array(regularized, np=np)


def _validate_delta_t(delta_t: float) -> None:
    if isinstance(delta_t, bool) or not math.isfinite(float(delta_t)) or float(delta_t) <= 0.0:
        raise MarkovEmbeddingError(f"delta_t debe ser positivo y finito: {delta_t!r}.")


def _period_number(time_value: float, *, ordinal: int) -> int:
    rounded = round(time_value)
    if math.isclose(time_value, rounded, rel_tol=0.0, abs_tol=1e-12):
        period = int(rounded)
        if period >= 1:
            return period
    return ordinal


def _time_value(value: Any) -> float:
    if isinstance(value, bool):
        raise MarkovTransformError(f"El tiempo Markov no puede ser booleano: {value!r}.")
    try:
        candidate = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarkovTransformError(f"El tiempo Markov debe ser numérico: {value!r}.") from exc
    if not math.isfinite(candidate):
        raise MarkovTransformError(f"El tiempo Markov debe ser finito: {value!r}.")
    return _clean_float(candidate)


def _pd_marginal(pd_cumulative: float, previous: float, *, tol: float) -> float:
    marginal = pd_cumulative - previous
    if marginal < 0.0:
        if abs(marginal) <= tol:
            return 0.0
        raise MarkovTransformError(
            "PD marginal negativa fuera de tolerancia: "
            f"pd_cumulative={pd_cumulative}, previous={previous}."
        )
    return _non_negative_float(marginal)


def _unit_probability(value: float, *, tol: float, field_name: str) -> float:
    cleaned = _clean_float(value)
    if cleaned < -tol or cleaned > 1.0 + tol:
        raise MarkovTransformError(f"{field_name} debe estar en [0, 1]; valor={cleaned}.")
    return min(1.0, max(0.0, cleaned))


def _non_negative_float(value: float) -> float:
    cleaned = _clean_float(value)
    if cleaned < 0.0:
        raise MarkovTransformError(f"Valor Markov debe ser no negativo: {cleaned}.")
    return cleaned


def _clean_float(value: float) -> float:
    if not math.isfinite(value):
        raise MarkovTransformError(f"Valor numérico no finito en Markov: {value!r}.")
    if value == 0.0:
        return 0.0
    return value


def _normalize_array(matrix: NDArrayFloat, *, np: Any) -> NDArrayFloat:
    normalized = np.array(matrix, dtype="float64", copy=True)
    normalized[normalized == 0.0] = 0.0
    return cast("NDArrayFloat", normalized)


def _normalize_frame(frame: DataFrame) -> DataFrame:
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        series = copied[column]
        zero_mask = series == 0.0
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _import_numpy() -> Any:
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("Las funciones Markov requieren numpy.") from exc


def _import_pandas() -> Any:
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("Las funciones Markov requieren pandas.") from exc


def _import_scipy_linalg() -> Any:
    try:
        return importlib.import_module("scipy.linalg")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_MARKOV_EXTRA_MESSAGE) from exc
