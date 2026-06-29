"""Estimador de matrices de transición Markov (SDD-19 §3/§7).

``TransitionMatrixEstimator`` estima matrices de transición por cohort MLE o generadores
continuos por duration. La salida es determinista, usa copias defensivas del panel de entrada y
mantiene liviano ``import nikodym.markov``: ``pandas``, ``numpy`` y ``scipy`` se importan solo en
``fit``/``predict_transition``/``term_structure`` y sus helpers de ejecución.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeAlias, cast

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import MissingDependencyError, NotFittedError
from nikodym.core.mixins import AuditableMixin
from nikodym.markov.config import MarkovConfig
from nikodym.markov.exceptions import (
    InvalidGeneratorError,
    MarkovFitError,
    MarkovInputError,
    MarkovTransformError,
)
from nikodym.markov.results import MarkovDiagnostics

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any

__all__ = ["TransitionMatrixEstimator"]

_MARKOV_EXTRA_MESSAGE = "TransitionMatrixEstimator requiere scipy.linalg; instale nikodym[markov]."
_PARTITION_DESARROLLO = "desarrollo"
_PD_SOURCE = "markov"
_SCENARIO = None
_SEGMENT = None
_COUNT_ATOL = 1e-12
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


@dataclass(frozen=True)
class _PreparedPanel:
    frame: DataFrame
    n_entities: int
    n_observations: int
    n_periods: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _TransitionObservation:
    from_state: str
    to_state: str
    from_time: float
    to_time: float
    delta_time: float
    weight: float
    exposure_time: float


@dataclass(frozen=True)
class _FitOutput:
    transition_matrix: NDArrayFloat
    period_transition_matrices: dict[float, NDArrayFloat]
    generator: NDArrayFloat | None
    state_counts: dict[str, float]
    transition_origin_counts: dict[str, float]
    transition_counts: NDArrayFloat
    time_at_risk: dict[str, float]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _ProjectedMatrix:
    horizon: float
    matrix: NDArrayFloat
    warnings: tuple[str, ...]


class TransitionMatrixEstimator(AuditableMixin):
    """Estima matrices de transición discretas y generadores continuos Markov."""

    config_cls: ClassVar[type[MarkovConfig]] = MarkovConfig

    def __init__(self, *, config: MarkovConfig | Mapping[str, Any] | None = None) -> None:
        """Asigna configuración Markov sin importar dependencias numéricas pesadas."""
        if config is None:
            self.config = MarkovConfig()
        elif isinstance(config, MarkovConfig):
            self.config = config
        else:
            self.config = MarkovConfig.model_validate(config)

    @classmethod
    def from_config(
        cls,
        cfg: NikodymBaseConfig | Mapping[str, Any],
    ) -> TransitionMatrixEstimator:
        """Construye el estimador desde ``MarkovConfig`` o un mapping equivalente."""
        if not isinstance(cfg, MarkovConfig):
            cfg = MarkovConfig.model_validate(cfg)
        return cls(config=cfg)

    def fit(self, frame: DataFrame, *, audit: AuditSink | None = None) -> Self:
        """Ajusta la matriz ``P`` o el generador ``Q`` desde un panel de migraciones."""
        pd = _import_pandas()
        np = _import_numpy()
        if audit is not None:
            self._audit = audit

        cfg = self.config
        if cfg.dynamics.projection_mode != "homogeneous":
            raise MarkovFitError(
                "TransitionMatrixEstimator B19.3 soporta projection_mode='homogeneous'; "
                f"recibido {cfg.dynamics.projection_mode!r}."
            )

        prepared = _prepare_panel(frame, cfg=cfg, pd=pd, np=np)
        transitions = _derive_transitions(prepared.frame, cfg=cfg)
        if cfg.estimation.method == "cohort":
            fit_output = _fit_cohort(transitions, cfg=cfg, np=np)
        else:
            expm = _import_expm()
            fit_output = _fit_duration(transitions, cfg=cfg, np=np, expm=expm)

        warnings = _dedupe((*prepared.warnings, *fit_output.warnings))
        self.config_ = cfg
        self.states_ = cfg.states.states
        self.default_state_ = cfg.states.default_state
        self.transition_matrix_ = fit_output.transition_matrix.copy()
        self.period_transition_matrices_ = {
            key: value.copy() for key, value in fit_output.period_transition_matrices.items()
        }
        self.generator_ = None if fit_output.generator is None else fit_output.generator.copy()
        self.state_counts_ = dict(fit_output.state_counts)
        self.transition_counts_ = fit_output.transition_counts.copy()
        self.time_at_risk_ = dict(fit_output.time_at_risk)
        self.transition_matrix_frame_ = _transition_matrix_frame(
            matrix=fit_output.transition_matrix,
            states=cfg.states.states,
            transition_counts=fit_output.transition_counts,
            origin_counts=fit_output.transition_origin_counts,
            period=None,
            method=cfg.estimation.method,
            pd=pd,
        )
        self.generator_frame_ = (
            None
            if fit_output.generator is None
            else _generator_frame(
                generator=fit_output.generator,
                transition_counts=fit_output.transition_counts,
                time_at_risk=fit_output.time_at_risk,
                source="duration",
                cfg=cfg,
                pd=pd,
            )
        )
        self.diagnostics_ = MarkovDiagnostics(
            method=cfg.estimation.method,
            projection_mode=cfg.dynamics.projection_mode,
            states=cfg.states.states,
            default_state=cfg.states.default_state,
            absorbing_states=cfg.states.absorbing_states,
            n_entities=prepared.n_entities,
            n_observations=prepared.n_observations,
            n_transitions=len(transitions),
            n_periods=prepared.n_periods,
            stochastic_tol=cfg.validation.stochastic_tol,
            generator_tol=cfg.validation.generator_tol,
            fit_statistics={
                "interval": cfg.estimation.interval,
                "min_origin_count": cfg.estimation.min_origin_count,
                "n_states": len(cfg.states.states),
            },
            warnings=warnings,
        )
        self._log_fit_decisions(prepared=prepared, transitions=transitions)
        return self

    def predict_transition(self, *, horizons: Sequence[int | float]) -> dict[float, DataFrame]:
        """Proyecta matrices acumuladas ``P(0,t)`` y las publica en formato tidy."""
        pd = _import_pandas()
        np = _import_numpy()
        projected = _project_matrices(self, horizons, np=np)
        return {
            point.horizon: _transition_matrix_frame(
                matrix=point.matrix,
                states=self.states_,
                transition_counts=None,
                origin_counts=None,
                period=point.horizon,
                method=self.config_.estimation.method,
                pd=pd,
            )
            for point in projected
        }

    def term_structure(self, *, horizons: Sequence[int | float]) -> DataFrame:
        """Publica PD lifetime tidy por estado inicial no absorbente."""
        pd = _import_pandas()
        np = _import_numpy()
        projected = _project_matrices(self, horizons, np=np)
        rows: list[dict[str, Any]] = []
        index: list[str] = []
        default_index = self.states_.index(self.default_state_)
        absorbing = set(self.config_.states.absorbing_states)
        previous_pd = {state: 0.0 for state in self.states_ if state not in absorbing}
        for point in projected:
            warning_codes = _dedupe(point.warnings)
            for from_index, state in enumerate(self.states_):
                if state in absorbing:
                    continue
                pd_cumulative = _unit_float(
                    float(point.matrix[from_index, default_index]),
                    field_name="pd_cumulative",
                )
                old_pd = previous_pd[state]
                pd_marginal = _pd_marginal(pd_cumulative, old_pd, self.config_)
                previous_survival = _clean_float(1.0 - old_pd)
                hazard = (
                    _unit_float(pd_marginal / previous_survival, field_name="hazard")
                    if previous_survival > 0.0
                    else 0.0
                )
                survival = _unit_float(1.0 - pd_cumulative, field_name="survival")
                rows.append(
                    {
                        "row_id": f"state:{state}",
                        "segment": _SEGMENT,
                        "partition": None,
                        "period": _period_number(point.horizon),
                        "time_value": point.horizon,
                        "hazard": hazard,
                        "survival": survival,
                        "pd_marginal": pd_marginal,
                        "pd_cumulative": pd_cumulative,
                        "method": self.config_.estimation.method,
                        "pd_source": _PD_SOURCE,
                        "scenario": _SCENARIO,
                        "warning_codes": warning_codes,
                    }
                )
                index.append(f"state:{state}|{_period_number(point.horizon)}")
                previous_pd[state] = pd_cumulative
        return _records_to_frame(rows, columns=_TERM_STRUCTURE_COLUMNS, index=index, pd=pd)

    def _log_fit_decisions(
        self,
        *,
        prepared: _PreparedPanel,
        transitions: tuple[_TransitionObservation, ...],
    ) -> None:
        self.log_decision(
            regla="markov_method",
            umbral={
                "method": self.config_.estimation.method,
                "projection_mode": self.config_.dynamics.projection_mode,
                "time_unit": self.config_.dynamics.time_unit,
            },
            valor={
                "states": self.states_,
                "default_state": self.default_state_,
                "absorbing_states": self.config_.states.absorbing_states,
            },
            accion="fit_transition_matrix",
        )
        self.log_decision(
            regla="markov_input_quality",
            umbral={"min_origin_count": self.config_.estimation.min_origin_count},
            valor={
                "n_entities": prepared.n_entities,
                "n_observations": prepared.n_observations,
                "n_transitions": len(transitions),
                "warnings": self.diagnostics_.warnings,
            },
            accion="validar_panel_migraciones",
        )


def _prepare_panel(frame: DataFrame, *, cfg: MarkovConfig, pd: Any, np: Any) -> _PreparedPanel:
    copied = _as_dataframe(frame, pd)
    _validate_columns(copied, cfg)
    _validate_unique_entity_time(copied, cfg)
    prepared, warnings = _filter_known_states(copied, cfg=cfg)
    prepared = _filter_partition(prepared, cfg=cfg)
    if prepared.empty:
        raise MarkovInputError("El panel Markov no contiene filas modelables.")
    _validate_weights(prepared, cfg=cfg, np=np)
    _validate_exposure(prepared, cfg=cfg, np=np)
    n_entities = int(prepared[cfg.input.id_col].nunique(dropna=False))
    n_observations = len(prepared.index)
    n_periods = int(prepared[cfg.input.time_col].nunique(dropna=False))
    return _PreparedPanel(
        frame=prepared,
        n_entities=n_entities,
        n_observations=n_observations,
        n_periods=n_periods,
        warnings=warnings,
    )


def _derive_transitions(
    frame: DataFrame,
    *,
    cfg: MarkovConfig,
) -> tuple[_TransitionObservation, ...]:
    sorted_frame = frame.sort_values(
        [cfg.input.id_col, cfg.input.time_col],
        kind="mergesort",
    )
    transitions: list[_TransitionObservation] = []
    absorbing = set(cfg.states.absorbing_states)
    for _entity, group in sorted_frame.groupby(cfg.input.id_col, sort=False, dropna=False):
        rows = list(group.itertuples(index=False))
        columns = tuple(str(column) for column in group.columns)
        for current, following in pairwise(rows):
            current_row = dict(zip(columns, current, strict=True))
            next_row = dict(zip(columns, following, strict=True))
            from_state = str(current_row[cfg.input.state_col])
            to_state = str(next_row[cfg.input.state_col])
            if from_state in absorbing:
                if to_state != from_state:
                    raise MarkovInputError(
                        "Transición observada desde estado absorbente hacia otro estado: "
                        f"from_state={from_state!r}, to_state={to_state!r}."
                    )
                continue
            delta_time = _delta_time(current_row[cfg.input.time_col], next_row[cfg.input.time_col])
            weight = _transition_weight(current_row, cfg=cfg)
            exposure_time = _transition_exposure(current_row, cfg=cfg, delta_time=delta_time)
            transitions.append(
                _TransitionObservation(
                    from_state=from_state,
                    to_state=to_state,
                    from_time=_time_as_float(current_row[cfg.input.time_col]),
                    to_time=_time_as_float(next_row[cfg.input.time_col]),
                    delta_time=delta_time,
                    weight=weight,
                    exposure_time=exposure_time,
                )
            )
    if not transitions:
        raise MarkovFitError("No hay transiciones Markov válidas para ajustar.")
    return tuple(transitions)


def _fit_cohort(
    transitions: tuple[_TransitionObservation, ...],
    *,
    cfg: MarkovConfig,
    np: Any,
) -> _FitOutput:
    counts = _zero_matrix(cfg, np=np)
    state_counts = {state: 0.0 for state in cfg.states.states}
    state_index = _state_index(cfg)
    for transition in transitions:
        origin = state_index[transition.from_state]
        destination = state_index[transition.to_state]
        counts[origin, destination] += transition.weight
        state_counts[transition.from_state] += transition.weight
    _check_min_origin_counts(state_counts, cfg=cfg)
    matrix = _zero_matrix(cfg, np=np)
    absorbing = set(cfg.states.absorbing_states)
    for state in cfg.states.states:
        row = state_index[state]
        if state in absorbing:
            matrix[row, row] = 1.0
            continue
        origin_count = state_counts[state]
        matrix[row, :] = counts[row, :] / origin_count
    matrix, warnings = _validate_stochastic_matrix(
        matrix,
        states=cfg.states.states,
        absorbing_states=cfg.states.absorbing_states,
        tol=cfg.validation.stochastic_tol,
        normalize_within_tolerance=cfg.validation.normalize_within_tolerance,
        np=np,
    )
    return _FitOutput(
        transition_matrix=matrix,
        period_transition_matrices={},
        generator=None,
        state_counts={state: _clean_float(value) for state, value in state_counts.items()},
        transition_origin_counts={
            state: _clean_float(value) for state, value in state_counts.items()
        },
        transition_counts=_normalize_array(counts, np=np),
        time_at_risk={state: 0.0 for state in cfg.states.states},
        warnings=warnings,
    )


def _fit_duration(
    transitions: tuple[_TransitionObservation, ...],
    *,
    cfg: MarkovConfig,
    np: Any,
    expm: Any,
) -> _FitOutput:
    counts = _zero_matrix(cfg, np=np)
    time_at_risk = {state: 0.0 for state in cfg.states.states}
    origin_counts = {state: 0.0 for state in cfg.states.states}
    state_index = _state_index(cfg)
    for transition in transitions:
        origin_counts[transition.from_state] += transition.weight
        time_at_risk[transition.from_state] += transition.exposure_time * transition.weight
        if transition.from_state != transition.to_state:
            counts[state_index[transition.from_state], state_index[transition.to_state]] += (
                transition.weight
            )
    generator = _zero_matrix(cfg, np=np)
    absorbing = set(cfg.states.absorbing_states)
    for state in cfg.states.states:
        row = state_index[state]
        if state in absorbing:
            continue
        risk = time_at_risk[state]
        transitions_out = float(np.sum(counts[row, :]))
        if risk <= _COUNT_ATOL and transitions_out > _COUNT_ATOL:
            raise InvalidGeneratorError(
                "No se puede estimar intensidad con tiempo en riesgo cero: "
                f"state={state!r}, transition_count={transitions_out}."
            )
        if risk <= _COUNT_ATOL:
            raise MarkovFitError(
                "method='duration' exige tiempo en riesgo positivo para cada estado "
                f"no absorbente: state={state!r}."
            )
        for to_state in cfg.states.states:
            column = state_index[to_state]
            if column != row:
                generator[row, column] = counts[row, column] / risk
        generator[row, row] = -float(np.sum(generator[row, :]))
    generator = _validate_generator(
        generator,
        states=cfg.states.states,
        absorbing_states=cfg.states.absorbing_states,
        tol=cfg.validation.generator_tol,
        np=np,
    )
    transition_matrix = cast("NDArrayFloat", expm(generator * cfg.estimation.interval))
    transition_matrix, warnings = _validate_stochastic_matrix(
        transition_matrix,
        states=cfg.states.states,
        absorbing_states=cfg.states.absorbing_states,
        tol=cfg.validation.stochastic_tol,
        normalize_within_tolerance=cfg.validation.normalize_within_tolerance,
        np=np,
    )
    return _FitOutput(
        transition_matrix=transition_matrix,
        period_transition_matrices={},
        generator=_normalize_array(generator, np=np),
        state_counts={state: _clean_float(value) for state, value in time_at_risk.items()},
        transition_origin_counts={
            state: _clean_float(value) for state, value in origin_counts.items()
        },
        transition_counts=_normalize_array(counts, np=np),
        time_at_risk={state: _clean_float(value) for state, value in time_at_risk.items()},
        warnings=warnings,
    )


def _project_matrices(
    estimator: TransitionMatrixEstimator,
    horizons: Sequence[int | float],
    *,
    np: Any,
) -> tuple[_ProjectedMatrix, ...]:
    _check_fitted(estimator)
    values = _validate_horizons(horizons)
    projected: list[_ProjectedMatrix] = []
    if estimator.generator_ is not None:
        expm = _import_expm()
        for horizon in values:
            matrix = cast("NDArrayFloat", expm(estimator.generator_ * horizon))
            matrix, warnings = _validate_stochastic_matrix(
                matrix,
                states=estimator.states_,
                absorbing_states=estimator.config_.states.absorbing_states,
                tol=estimator.config_.validation.stochastic_tol,
                normalize_within_tolerance=estimator.config_.validation.normalize_within_tolerance,
                np=np,
            )
            projected.append(_ProjectedMatrix(horizon=horizon, matrix=matrix, warnings=warnings))
        return tuple(projected)

    interval = estimator.config_.estimation.interval
    for horizon in values:
        steps = _cohort_steps(horizon, interval=interval)
        matrix = cast("NDArrayFloat", np.linalg.matrix_power(estimator.transition_matrix_, steps))
        matrix, warnings = _validate_stochastic_matrix(
            matrix,
            states=estimator.states_,
            absorbing_states=estimator.config_.states.absorbing_states,
            tol=estimator.config_.validation.stochastic_tol,
            normalize_within_tolerance=estimator.config_.validation.normalize_within_tolerance,
            np=np,
        )
        projected.append(_ProjectedMatrix(horizon=horizon, matrix=matrix, warnings=warnings))
    return tuple(projected)


def _validate_stochastic_matrix(
    matrix: NDArrayFloat,
    *,
    states: tuple[str, ...],
    absorbing_states: tuple[str, ...],
    tol: float,
    normalize_within_tolerance: bool,
    np: Any,
) -> tuple[NDArrayFloat, tuple[str, ...]]:
    from nikodym.markov.term_structure import validate_transition_matrix

    validate_transition_matrix(
        matrix,
        states=states,
        absorbing_states=absorbing_states,
        tol=tol,
    )
    candidate = np.array(matrix, dtype="float64", copy=True)
    warnings: list[str] = []
    absorbing = set(absorbing_states)
    for row_index, state in enumerate(states):
        row = candidate[row_index, :]
        row[(row < 0.0) & (row >= -tol)] = 0.0
        row[(row > 1.0) & (row <= 1.0 + tol)] = 1.0
        if state in absorbing:
            expected = np.zeros(len(states), dtype="float64")
            expected[row_index] = 1.0
            candidate[row_index, :] = expected
            continue
        row_sum = float(np.sum(row))
        if row_sum != 1.0 and normalize_within_tolerance:
            candidate[row_index, :] = row / row_sum
            warnings.append(f"normalized_stochastic_row:{state}")
    return _normalize_array(candidate, np=np), tuple(warnings)


def _validate_generator(
    generator: NDArrayFloat,
    *,
    states: tuple[str, ...],
    absorbing_states: tuple[str, ...],
    tol: float,
    np: Any,
) -> NDArrayFloat:
    from nikodym.markov.term_structure import validate_generator

    validate_generator(
        generator,
        states=states,
        absorbing_states=absorbing_states,
        tol=tol,
    )
    candidate = np.array(generator, dtype="float64", copy=True)
    absorbing = set(absorbing_states)
    for row_index, state in enumerate(states):
        row = candidate[row_index, :]
        if state in absorbing:
            candidate[row_index, :] = 0.0
            continue
        diagonal = float(row[row_index])
        off_diagonal = np.delete(row, row_index)
        off_diagonal[(off_diagonal < 0.0) & (off_diagonal >= -tol)] = 0.0
        candidate[row_index, row_index] = -float(np.sum(candidate[row_index, :]) - diagonal)
    return _normalize_array(candidate, np=np)


def _transition_matrix_frame(
    *,
    matrix: NDArrayFloat,
    states: tuple[str, ...],
    transition_counts: NDArrayFloat | None,
    origin_counts: Mapping[str, float] | None,
    period: float | None,
    method: str,
    pd: Any,
) -> DataFrame:
    rows: list[dict[str, Any]] = []
    for from_index, from_state in enumerate(states):
        for to_index, to_state in enumerate(states):
            rows.append(
                {
                    "period": period,
                    "from_state": from_state,
                    "to_state": to_state,
                    "probability": _unit_float(
                        float(matrix[from_index, to_index]),
                        field_name="probability",
                    ),
                    "count": (
                        None
                        if transition_counts is None
                        else _non_negative_float(
                            float(transition_counts[from_index, to_index]),
                            field_name="count",
                        )
                    ),
                    "origin_count": (
                        None
                        if origin_counts is None
                        else _non_negative_float(
                            float(origin_counts[from_state]),
                            field_name="origin_count",
                        )
                    ),
                    "method": method,
                    "segment": _SEGMENT,
                }
            )
    return _records_to_frame(rows, columns=_TRANSITION_COLUMNS, index=None, pd=pd)


def _generator_frame(
    *,
    generator: NDArrayFloat,
    transition_counts: NDArrayFloat,
    time_at_risk: Mapping[str, float],
    source: str,
    cfg: MarkovConfig,
    pd: Any,
) -> DataFrame:
    rows: list[dict[str, Any]] = []
    states = cfg.states.states
    for from_index, from_state in enumerate(states):
        for to_index, to_state in enumerate(states):
            rows.append(
                {
                    "from_state": from_state,
                    "to_state": to_state,
                    "intensity": _clean_float(float(generator[from_index, to_index])),
                    "time_at_risk": _non_negative_float(
                        float(time_at_risk[from_state]),
                        field_name="time_at_risk",
                    ),
                    "transition_count": _non_negative_float(
                        float(transition_counts[from_index, to_index]),
                        field_name="transition_count",
                    ),
                    "source": source,
                }
            )
    return _records_to_frame(rows, columns=_GENERATOR_COLUMNS, index=None, pd=pd)


def _records_to_frame(
    rows: list[dict[str, Any]],
    *,
    columns: tuple[str, ...],
    index: list[str] | None,
    pd: Any,
) -> DataFrame:
    frame = pd.DataFrame.from_records(rows, columns=columns)
    if index is not None:
        frame.index = pd.Index(index)
    return _normalize_frame(frame)


def _zero_matrix(cfg: MarkovConfig, *, np: Any) -> NDArrayFloat:
    matrix = np.zeros((len(cfg.states.states), len(cfg.states.states)), dtype="float64")
    return cast("NDArrayFloat", matrix)


def _normalize_array(matrix: NDArrayFloat, *, np: Any) -> NDArrayFloat:
    normalized = np.array(matrix, dtype="float64", copy=True)
    normalized[normalized == 0.0] = 0.0
    return cast("NDArrayFloat", normalized)


def _validate_columns(frame: DataFrame, cfg: MarkovConfig) -> None:
    required = [cfg.input.id_col, cfg.input.time_col, cfg.input.state_col]
    if cfg.input.segment_col is not None:
        required.append(cfg.input.segment_col)
    if cfg.estimation.use_weights and cfg.input.weight_col is not None:
        required.append(cfg.input.weight_col)
    if cfg.estimation.method == "duration" and cfg.input.exposure_time_col is not None:
        required.append(cfg.input.exposure_time_col)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise MarkovInputError(f"Faltan columnas requeridas para Markov: {missing}.")


def _validate_unique_entity_time(frame: DataFrame, cfg: MarkovConfig) -> None:
    duplicated = frame.duplicated(subset=[cfg.input.id_col, cfg.input.time_col], keep=False)
    if bool(duplicated.any()):
        raise MarkovInputError("El panel Markov contiene tiempos duplicados por id.")


def _filter_known_states(
    frame: DataFrame,
    *,
    cfg: MarkovConfig,
) -> tuple[DataFrame, tuple[str, ...]]:
    states = set(cfg.states.states)
    observed = frame[cfg.input.state_col].astype("string")
    unknown_mask = ~observed.isin(states)
    if not bool(unknown_mask.any()):
        return frame.copy(deep=True), ()
    unknown = tuple(sorted({str(value) for value in observed[unknown_mask]}))
    if not cfg.states.allow_unknown_states:
        raise MarkovInputError(f"Estados fuera de catálogo Markov: {unknown}.")
    filtered = frame.loc[~unknown_mask].copy(deep=True)
    if filtered.empty:
        raise MarkovInputError("Todos los estados observados quedaron fuera del catálogo Markov.")
    return filtered, (f"unknown_states_dropped:{','.join(unknown)}",)


def _filter_partition(frame: DataFrame, *, cfg: MarkovConfig) -> DataFrame:
    partition_col = cfg.input.partition_col
    if partition_col is None or partition_col not in frame.columns:
        return frame.copy(deep=True)
    values = frame[partition_col].astype("string")
    if bool(values.isna().any()):
        raise MarkovInputError(f"La columna {partition_col!r} no puede contener missing.")
    mask = values == _PARTITION_DESARROLLO
    if bool(mask.any()):
        return frame.loc[mask].copy(deep=True)
    return frame.copy(deep=True)


def _validate_weights(frame: DataFrame, *, cfg: MarkovConfig, np: Any) -> None:
    if not cfg.estimation.use_weights:
        return
    weight_col = cfg.input.weight_col
    if weight_col is None or weight_col not in frame.columns:
        raise MarkovInputError("use_weights=True exige weight_col presente en el frame.")
    weights = frame[weight_col].to_numpy(dtype="float64")
    if not bool(np.all(np.isfinite(weights))) or bool(np.any(weights < 0.0)):
        raise MarkovInputError("weight_col debe contener pesos finitos y no negativos.")


def _validate_exposure(frame: DataFrame, *, cfg: MarkovConfig, np: Any) -> None:
    exposure_col = cfg.input.exposure_time_col
    if cfg.estimation.method != "duration" or exposure_col is None:
        return
    values = frame[exposure_col].to_numpy(dtype="float64")
    if not bool(np.all(np.isfinite(values))) or bool(np.any(values < 0.0)):
        raise MarkovInputError("exposure_time_col debe contener tiempos finitos y no negativos.")


def _transition_weight(row: Mapping[str, Any], *, cfg: MarkovConfig) -> float:
    if not cfg.estimation.use_weights:
        return 1.0
    weight_col = cfg.input.weight_col
    if weight_col is None:
        return 1.0
    return _non_negative_float(float(row[weight_col]), field_name="weight")


def _transition_exposure(
    row: Mapping[str, Any],
    *,
    cfg: MarkovConfig,
    delta_time: float,
) -> float:
    exposure_col = cfg.input.exposure_time_col
    if cfg.estimation.method == "duration" and exposure_col is not None:
        return _non_negative_float(float(row[exposure_col]), field_name="exposure_time")
    return delta_time


def _delta_time(current: Any, following: Any) -> float:
    current_value = _time_as_float(current)
    following_value = _time_as_float(following)
    delta = _clean_float(following_value - current_value)
    if delta <= 0.0:
        raise MarkovInputError(
            f"Los tiempos deben crecer estrictamente por id; delta_time={delta}."
        )
    return delta


def _time_as_float(value: Any) -> float:
    if isinstance(value, bool):
        raise MarkovInputError(f"El tiempo Markov no puede ser booleano: {value!r}.")
    try:
        candidate = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarkovInputError(f"El tiempo Markov no es ordenable como número: {value!r}.") from exc
    if not math.isfinite(candidate):
        raise MarkovInputError(f"El tiempo Markov debe ser finito: {value!r}.")
    return _clean_float(candidate)


def _check_min_origin_counts(state_counts: Mapping[str, float], *, cfg: MarkovConfig) -> None:
    absorbing = set(cfg.states.absorbing_states)
    low = [
        state
        for state in cfg.states.states
        if state not in absorbing and state_counts[state] < cfg.estimation.min_origin_count
    ]
    if low:
        raise MarkovFitError(
            "Estados no absorbentes sin origen suficiente para cohort MLE: "
            f"states={low}, min_origin_count={cfg.estimation.min_origin_count}."
        )


def _state_index(cfg: MarkovConfig) -> dict[str, int]:
    return {state: index for index, state in enumerate(cfg.states.states)}


def _validate_horizons(horizons: Sequence[int | float]) -> tuple[float, ...]:
    if not horizons:
        raise MarkovTransformError("horizons debe contener al menos un horizonte.")
    normalized: list[float] = []
    for position, value in enumerate(horizons):
        if isinstance(value, bool):
            raise MarkovTransformError(
                f"horizons contiene un booleano en posición {position}: {value!r}."
            )
        candidate = float(value)
        if not math.isfinite(candidate) or candidate <= 0.0:
            raise MarkovTransformError(
                "horizons debe contener valores positivos y finitos: "
                f"posición={position}, valor={value!r}."
            )
        normalized.append(_clean_float(candidate))
    ordered = tuple(sorted(normalized))
    if len(set(ordered)) != len(ordered):
        raise MarkovTransformError(f"horizons contiene valores duplicados: {horizons!r}.")
    return ordered


def _cohort_steps(horizon: float, *, interval: float) -> int:
    ratio = horizon / interval
    rounded = round(ratio)
    if not math.isclose(ratio, rounded, rel_tol=0.0, abs_tol=1e-12):
        raise MarkovTransformError(
            "La proyección cohort homogénea exige horizontes múltiplos del intervalo: "
            f"horizon={horizon}, interval={interval}."
        )
    return int(rounded)


def _period_number(horizon: float) -> int:
    rounded = round(horizon)
    if math.isclose(horizon, rounded, rel_tol=0.0, abs_tol=1e-12):
        return int(rounded)
    raise MarkovTransformError(f"term_structure exige horizontes enteros; horizon={horizon}.")


def _pd_marginal(pd_cumulative: float, previous: float, cfg: MarkovConfig) -> float:
    marginal = pd_cumulative - previous
    if marginal < 0.0:
        if abs(marginal) <= cfg.validation.stochastic_tol:
            return 0.0
        raise MarkovTransformError(
            "PD marginal negativa fuera de tolerancia: "
            f"pd_cumulative={pd_cumulative}, previous={previous}."
        )
    return _non_negative_float(marginal, field_name="pd_marginal")


def _as_dataframe(frame: DataFrame, pd: Any) -> DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise MarkovInputError("TransitionMatrixEstimator.fit requiere un pandas.DataFrame.")
    return cast("DataFrame", frame.copy(deep=True))


def _normalize_frame(frame: DataFrame) -> DataFrame:
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        series = copied[column]
        zero_mask = series == 0.0
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _unit_float(value: float, *, field_name: str) -> float:
    cleaned = _clean_float(value)
    if cleaned < -_COUNT_ATOL or cleaned > 1.0 + _COUNT_ATOL:
        raise MarkovTransformError(f"{field_name} debe estar en [0, 1]; valor={cleaned}.")
    return min(1.0, max(0.0, cleaned))


def _non_negative_float(value: float, *, field_name: str) -> float:
    cleaned = _clean_float(value)
    if cleaned < -_COUNT_ATOL:
        raise MarkovTransformError(f"{field_name} debe ser no negativo; valor={cleaned}.")
    return max(0.0, cleaned)


def _clean_float(value: float) -> float:
    if not math.isfinite(value):
        raise MarkovTransformError(f"Valor numérico no finito en Markov: {value!r}.")
    if value == 0.0:
        return 0.0
    return value


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _check_fitted(estimator: TransitionMatrixEstimator) -> None:
    if not hasattr(estimator, "transition_matrix_"):
        raise NotFittedError(
            "TransitionMatrixEstimator no está fiteado; llame fit(...) antes de proyectar."
        )


def _import_pandas() -> Any:
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("TransitionMatrixEstimator requiere pandas.") from exc


def _import_numpy() -> Any:
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("TransitionMatrixEstimator requiere numpy.") from exc


def _import_expm() -> Any:
    try:
        scipy_linalg = importlib.import_module("scipy.linalg")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_MARKOV_EXTRA_MESSAGE) from exc
    return scipy_linalg.expm
