"""DTOs puros de resultados Markov y PD lifetime (SDD-19 §4/§6).

Este módulo fija los contenedores Pydantic publicados por ``markov``: diagnósticos de
embedding, diagnósticos agregados, tarjeta CT-2 y resultado con matrices/term-structure. No
estima matrices, no calcula generadores y no importa ``pandas``, ``numpy`` ni ``scipy`` en runtime
al cargar el módulo.

``MarkovResult.term_structure()`` replica el contrato CT-2 de ``SurvivalResult.term_structure()``:
devuelve un ``DataFrame`` tidy cuando existe una proyección publicable y ``None`` solo para modos
diagnósticos sin horizonte o sin matriz válida. Las colecciones mutables y frames se copian
defensivamente; los floats publicados normalizan ``-0.0`` como ``0.0``.

``EmbeddingDiagnostics`` cubre un gap del SDD-19: §4 declara ``diagnose_embedding(...) ->
EmbeddingDiagnostics`` pero no define el DTO. Sus campos mínimos salen de §3/§7: estado, flags,
distancia Frobenius, candidato de generador real, norma imaginaria y marca de ajuste.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from decimal import Decimal
from numbers import Integral, Real
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.markov.config import EmbeddingPolicy, MarkovMethod, ProjectionMode
from nikodym.markov.exceptions import MarkovTransformError

if TYPE_CHECKING:
    import numpy
    import pandas

    ArrayLike: TypeAlias = numpy.ndarray[Any, Any]
    DataFrameLike: TypeAlias = pandas.DataFrame
    TransitionMatrixEstimator: TypeAlias = Any
else:
    ArrayLike: TypeAlias = Any
    DataFrameLike: TypeAlias = Any
    TransitionMatrixEstimator: TypeAlias = Any

_TRANSITION_MATRIX_COLUMNS: tuple[str, ...] = (
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
_METRIC_SECTION_KEYS: tuple[str, ...] = (
    "transition_matrix_summary",
    "generator_summary",
    "embedding_diagnostics",
    "term_structure_summary",
)
_FLOAT_ATOL = 1e-12
_FLOAT_RTOL = 1e-12

__all__ = [
    "EmbeddingDiagnostics",
    "EmbeddingPolicy",
    "MarkovCard",
    "MarkovDiagnostics",
    "MarkovMethod",
    "MarkovResult",
    "ProjectionMode",
]


class EmbeddingDiagnostics(BaseModel):
    """Diagnóstico mínimo del embedding de una matriz de transición.

    Este DTO cierra el gap del SDD-19 §4: ``diagnose_embedding`` retorna esta estructura, aunque
    el documento no la definía explícitamente. Sus campos vienen de §3/§7: estado y flags del
    embedding, candidato de generador real, norma imaginaria, distancia Frobenius y si hubo ajuste
    o regularización.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"generator_candidate"})

    embedding_status: str
    embedding_flags: tuple[str, ...] = ()
    generator_candidate: ArrayLike | None = None
    imaginary_norm: float | None = None
    distance_fro: float | None = None
    adjusted: bool = False

    @field_validator("embedding_status")
    @classmethod
    def _valida_status(cls, value: str) -> str:
        """Valida que el estado de embedding sea texto no vacío."""
        if not value.strip():
            raise ValueError("embedding_status no puede estar vacío.")
        return value

    @field_validator("generator_candidate", mode="before")
    @classmethod
    def _copia_generator_candidate(cls, value: Any) -> Any:
        """Copia el candidato de generador sin importar ``numpy`` en runtime."""
        if value is None:
            return None
        return _copy_array_like(value)

    @field_validator("imaginary_norm", "distance_fro", mode="before")
    @classmethod
    def _normaliza_float_opcional_no_negativo(cls, value: Any) -> float | None:
        """Exige distancias/normas finitas y no negativas cuando se publican."""
        return _normalize_optional_non_negative_float(value)

    def __getattribute__(self, name: str) -> Any:
        """Entrega copia defensiva del candidato de generador."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS") and value is not None:
            return _copy_array_like(value)
        return value


class MarkovDiagnostics(BaseModel):
    """Diagnósticos publicados por el ajuste Markov sin depender de motores externos."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"fit_statistics"})

    method: MarkovMethod
    projection_mode: ProjectionMode
    states: tuple[str, ...]
    default_state: str
    absorbing_states: tuple[str, ...]
    n_entities: int = Field(ge=0)
    n_observations: int = Field(ge=0)
    n_transitions: int = Field(ge=0)
    n_periods: int = Field(ge=0)
    stochastic_tol: float
    generator_tol: float
    embedding_status: str | None = None
    embedding_flags: tuple[str, ...] = ()
    embedding_adjusted: bool = False
    embedding_distance_fro: float | None = None
    fit_statistics: dict[str, float | int | str | None] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @field_validator("stochastic_tol", "generator_tol", mode="before")
    @classmethod
    def _normaliza_tolerancia(cls, value: Any) -> float:
        """Exige tolerancias finitas y no negativas."""
        return _normalize_non_negative_float(value)

    @field_validator("embedding_distance_fro", mode="before")
    @classmethod
    def _normaliza_distancia_embedding(cls, value: Any) -> float | None:
        """Normaliza la distancia Frobenius opcional del embedding."""
        return _normalize_optional_non_negative_float(value)

    @field_validator("embedding_status", mode="before")
    @classmethod
    def _normaliza_status_opcional(cls, value: Any) -> Any:
        """Rechaza estados de embedding vacíos cuando existen."""
        if value is None:
            return None
        if isinstance(value, str) and value.strip():
            return value
        return value

    @field_validator("fit_statistics", mode="before")
    @classmethod
    def _copia_fit_statistics(cls, value: Any) -> Any:
        """Copia estadísticas de ajuste y neutraliza floats no finitos."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {str(key): _normalize_stat_value(item) for key, item in value.items()}
        return value

    @model_validator(mode="after")
    def _check_estados_y_embedding(self) -> MarkovDiagnostics:
        """Valida estados canónicos y coherencia mínima del embedding."""
        _validate_states(
            states=self.states,
            default_state=self.default_state,
            absorbing_states=self.absorbing_states,
        )
        if self.embedding_status is not None and not self.embedding_status.strip():
            raise ValueError("embedding_status no puede estar vacío.")
        if self.n_transitions > max(self.n_observations - 1, 0) and self.n_observations > 0:
            raise ValueError("n_transitions no puede superar n_observations - 1.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class MarkovCard(BaseModel):
    """Resumen determinista CT-2 para governance, inventario y reportes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"dependency_versions", "metric_sections"}
    )

    method: MarkovMethod
    projection_mode: ProjectionMode
    time_unit: str
    horizon_periods: tuple[int, ...]
    states: tuple[str, ...]
    default_state: str
    absorbing_states: tuple[str, ...]
    output_columns: tuple[str, ...]
    diagnostics: MarkovDiagnostics
    dependency_versions: dict[str, str]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=lambda: _default_metric_sections())

    @field_validator("time_unit")
    @classmethod
    def _valida_time_unit(cls, value: str) -> str:
        """Valida unidad temporal declarativa no vacía."""
        if not value.strip():
            raise ValueError("time_unit no puede estar vacío.")
        return value

    @field_validator("horizon_periods", mode="before")
    @classmethod
    def _valida_horizontes(cls, value: Any) -> Any:
        """Valida horizontes positivos y estrictamente crecientes cuando existen."""
        if value is None:
            return value
        periods = tuple(value)
        previous: int | None = None
        for period in periods:
            current = _integer_value(period, field_name="horizon_periods")
            if current < 1:
                raise ValueError("horizon_periods debe contener enteros positivos.")
            if previous is not None and current <= previous:
                raise ValueError("horizon_periods debe crecer estrictamente.")
            previous = current
        return periods

    @field_validator("dependency_versions", mode="before")
    @classmethod
    def _copia_dependency_versions(cls, value: Any) -> Any:
        """Copia versiones de dependencias preservando orden de inserción."""
        if isinstance(value, Mapping):
            return {str(key): str(item) for key, item in value.items()}
        return value

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia y completa secciones CT-2 de Markov sin ordenar llaves."""
        if value is None:
            normalized: dict[str, Any] = {}
        elif isinstance(value, Mapping):
            normalized = _normalize_metric_payload(value)
        else:
            return value
        return _with_required_metric_sections(normalized)

    @model_validator(mode="after")
    def _check_card(self) -> MarkovCard:
        """Valida consistencia de tarjeta, diagnósticos y estados."""
        _validate_states(
            states=self.states,
            default_state=self.default_state,
            absorbing_states=self.absorbing_states,
        )
        if self.diagnostics.method != self.method:
            raise ValueError("diagnostics.method debe coincidir con card.method.")
        if self.diagnostics.projection_mode != self.projection_mode:
            raise ValueError("diagnostics.projection_mode debe coincidir con card.projection_mode.")
        if self.diagnostics.states != self.states:
            raise ValueError("diagnostics.states debe coincidir con card.states.")
        if self.diagnostics.default_state != self.default_state:
            raise ValueError("diagnostics.default_state debe coincidir con card.default_state.")
        if self.diagnostics.absorbing_states != self.absorbing_states:
            raise ValueError(
                "diagnostics.absorbing_states debe coincidir con card.absorbing_states."
            )
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class MarkovResult(BaseModel):
    """Contenedor agregado de artefactos publicados por la capa ``markov``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"generator_frame", "term_structure_frame", "transition_matrix_frame"}
    )

    estimator: TransitionMatrixEstimator
    transition_matrix_frame: DataFrameLike
    generator_frame: DataFrameLike | None
    term_structure_frame: DataFrameLike | None
    diagnostics: MarkovDiagnostics
    card: MarkovCard

    @field_validator("transition_matrix_frame", mode="before")
    @classmethod
    def _copia_transition_matrix(cls, value: Any) -> Any:
        """Copia y valida la matriz de transición tidy de SDD-19 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_TRANSITION_MATRIX_COLUMNS,
            field_name="transition_matrix_frame",
        )

    @field_validator("generator_frame", mode="before")
    @classmethod
    def _copia_generator(cls, value: Any) -> Any:
        """Copia y valida el generador continuo cuando existe."""
        if value is None:
            return None
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_GENERATOR_COLUMNS,
            field_name="generator_frame",
        )

    @field_validator("term_structure_frame", mode="before")
    @classmethod
    def _copia_term_structure(cls, value: Any) -> Any:
        """Copia y valida la tabla tidy lifetime PD cuando existe."""
        if value is None:
            return None
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_TERM_STRUCTURE_COLUMNS,
            field_name="term_structure_frame",
        )
        _validate_term_structure_values(copied)
        return copied

    @model_validator(mode="after")
    def _check_consistencia(self) -> MarkovResult:
        """Valida que card, diagnostics y tablas describan la misma salida."""
        if self.diagnostics != self.card.diagnostics:
            raise ValueError("card.diagnostics debe coincidir con diagnostics.")
        if (
            self.card.output_columns != _TERM_STRUCTURE_COLUMNS
            and self.term_structure_frame is not None
        ):
            raise ValueError("card.output_columns debe listar las columnas canónicas SDD-19 §6.")
        _validate_transition_matrix(
            self.transition_matrix_frame,
            states=self.diagnostics.states,
            absorbing_states=self.diagnostics.absorbing_states,
            stochastic_tol=self.diagnostics.stochastic_tol,
        )
        if self.generator_frame is not None:
            _validate_generator(
                self.generator_frame,
                absorbing_states=self.diagnostics.absorbing_states,
                generator_tol=self.diagnostics.generator_tol,
            )
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value

    def term_structure(self) -> pandas.DataFrame | None:
        """Retorna la tabla tidy lifetime PD o ``None`` si solo hubo diagnóstico.

        Cumple CT-2: SDD-16/20 pueden consumir esta salida igual que una term-structure de
        ``survival`` cuando existe. ``pandas`` se importa perezosamente aquí para mantener liviano
        ``import nikodym.markov.results``.
        """
        frame = self.term_structure_frame
        if frame is None:
            return None

        import pandas as pd

        if not isinstance(frame, pd.DataFrame):
            raise MarkovTransformError("term_structure_frame debe ser un pandas.DataFrame.")
        return cast("pandas.DataFrame", _copy_dataframe(frame))


def _copy_and_validate_dataframe(
    value: Any,
    *,
    expected_columns: tuple[str, ...],
    field_name: str,
) -> Any:
    if not _is_dataframe_like(value):
        raise ValueError(f"{field_name} debe ser un pandas.DataFrame.")

    copied = _copy_dataframe(value)
    observed_columns = tuple(str(column) for column in copied.columns)
    if observed_columns != expected_columns:
        raise ValueError(
            f"{field_name} debe tener exactamente las columnas canónicas de SDD-19 §6."
        )
    return copied


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))


def _copy_dataframe(frame: Any) -> Any:
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        series = copied[column]
        zero_mask = series == 0.0
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _copy_array_like(value: Any) -> Any:
    if hasattr(value, "copy"):
        return value.copy()
    return copy.deepcopy(value)


def _validate_transition_matrix(
    frame: Any,
    *,
    states: tuple[str, ...],
    absorbing_states: tuple[str, ...],
    stochastic_tol: float,
) -> None:
    row_sums: dict[tuple[Any, ...], float] = {}
    state_set = set(states)
    for row in frame.itertuples(index=False):
        values = dict(zip(_TRANSITION_MATRIX_COLUMNS, row, strict=True))
        from_state = str(values["from_state"])
        to_state = str(values["to_state"])
        if from_state not in state_set or to_state not in state_set:
            raise ValueError(
                "transition_matrix_frame contiene estados fuera de diagnostics.states."
            )

        probability = _required_frame_float(values["probability"], field_name="probability")
        _check_unit_interval(probability, field_name="probability")
        _optional_non_negative_frame_float(values["count"], field_name="count")
        _optional_non_negative_frame_float(values["origin_count"], field_name="origin_count")

        if from_state in absorbing_states:
            expected = 1.0 if to_state == from_state else 0.0
            if not math.isclose(probability, expected, rel_tol=0.0, abs_tol=stochastic_tol):
                raise ValueError("Todo estado absorbente debe tener fila identidad en P.")

        key = (_missing_to_none(values["period"]), from_state, _missing_to_none(values["segment"]))
        row_sums[key] = row_sums.get(key, 0.0) + probability

    for row_sum in row_sums.values():
        if not math.isclose(row_sum, 1.0, rel_tol=0.0, abs_tol=stochastic_tol):
            raise ValueError("Las filas de transition_matrix_frame deben sumar 1.")


def _validate_generator(
    frame: Any,
    *,
    absorbing_states: tuple[str, ...],
    generator_tol: float,
) -> None:
    row_sums: dict[str, float] = {}
    for row in frame.itertuples(index=False):
        values = dict(zip(_GENERATOR_COLUMNS, row, strict=True))
        from_state = str(values["from_state"])
        to_state = str(values["to_state"])
        intensity = _required_frame_float(values["intensity"], field_name="intensity")
        _optional_non_negative_frame_float(values["time_at_risk"], field_name="time_at_risk")
        _optional_non_negative_frame_float(
            values["transition_count"],
            field_name="transition_count",
        )

        if from_state == to_state:
            if intensity > generator_tol:
                raise ValueError("La diagonal del generador debe ser menor o igual a 0.")
        elif intensity < -generator_tol:
            raise ValueError("Las intensidades off-diagonal del generador deben ser no negativas.")

        if from_state in absorbing_states and not math.isclose(
            intensity,
            0.0,
            rel_tol=0.0,
            abs_tol=generator_tol,
        ):
            raise ValueError("Todo estado absorbente debe tener fila cero en Q.")

        row_sums[from_state] = row_sums.get(from_state, 0.0) + intensity

    for row_sum in row_sums.values():
        if not math.isclose(row_sum, 0.0, rel_tol=0.0, abs_tol=generator_tol):
            raise ValueError("Las filas de generator_frame deben sumar 0.")


def _validate_term_structure_values(frame: Any) -> None:
    previous_by_curve: dict[tuple[Any, ...], tuple[int, float, float, float]] = {}
    for row in frame.itertuples(index=False):
        values = dict(zip(_TERM_STRUCTURE_COLUMNS, row, strict=True))
        period = _integer_value(values["period"], field_name="period")
        time_value = _required_frame_float(values["time_value"], field_name="time_value")
        hazard = _optional_frame_float(values["hazard"], field_name="hazard")
        survival = _required_frame_float(values["survival"], field_name="survival")
        pd_marginal = _required_frame_float(values["pd_marginal"], field_name="pd_marginal")
        pd_cumulative = _required_frame_float(
            values["pd_cumulative"],
            field_name="pd_cumulative",
        )

        if period < 1:
            raise ValueError("period debe ser mayor o igual a 1.")
        if time_value < 0.0:
            raise ValueError("time_value debe ser mayor o igual a 0.")
        _check_unit_interval(survival, field_name="survival")
        if hazard is not None:
            _check_unit_interval(hazard, field_name="hazard")
        _check_unit_interval(pd_cumulative, field_name="pd_cumulative")
        if pd_marginal < 0.0:
            raise ValueError("pd_marginal debe ser mayor o igual a 0.")
        _check_pd_cumulative_consistency(survival, pd_cumulative)

        curve_key = _curve_key(values)
        previous = previous_by_curve.get(curve_key)
        previous_sum = 0.0
        if previous is not None:
            previous_period, previous_survival, _, previous_sum = previous
            if period <= previous_period:
                raise ValueError("period debe crecer estrictamente dentro de cada curva.")
            if survival > previous_survival + _FLOAT_ATOL:
                raise ValueError("survival no puede aumentar dentro de una curva.")

        cumulative_marginal = previous_sum + pd_marginal
        if not math.isclose(
            cumulative_marginal,
            pd_cumulative,
            rel_tol=_FLOAT_RTOL,
            abs_tol=_FLOAT_ATOL,
        ):
            raise ValueError("La suma acumulada de pd_marginal debe igualar pd_cumulative.")
        previous_by_curve[curve_key] = (
            period,
            survival,
            pd_cumulative,
            cumulative_marginal,
        )


def _curve_key(values: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _missing_to_none(values["row_id"]),
        _missing_to_none(values["segment"]),
        _missing_to_none(values["partition"]),
        _missing_to_none(values["method"]),
        _missing_to_none(values["pd_source"]),
        _missing_to_none(values["scenario"]),
    )


def _missing_to_none(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _integer_value(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} debe ser entero.")
    return value


def _optional_non_negative_frame_float(value: Any, *, field_name: str) -> float | None:
    if _is_missing_float(value):
        return None
    normalized = _required_frame_float(value, field_name=field_name)
    if normalized < 0.0:
        raise ValueError(f"{field_name} debe ser mayor o igual a 0.")
    return normalized


def _required_frame_float(value: Any, *, field_name: str) -> float:
    try:
        return _normalize_required_float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} debe ser un número finito.") from exc


def _optional_frame_float(value: Any, *, field_name: str) -> float | None:
    if _is_missing_float(value):
        return None
    try:
        return _normalize_required_float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} debe ser None o un número finito.") from exc


def _is_missing_float(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _check_pd_cumulative_consistency(survival: float, pd_cumulative: float) -> None:
    expected = 1.0 - survival
    if not math.isclose(pd_cumulative, expected, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL):
        raise ValueError("pd_cumulative debe ser igual a 1 - survival dentro de tolerancia.")


def _check_unit_interval(value: float, *, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} debe estar en [0, 1].")


def _normalize_non_negative_float(value: Any) -> float:
    normalized = _normalize_required_float(value)
    if normalized < 0.0:
        raise ValueError("Los valores float deben ser mayores o iguales a 0.")
    return normalized


def _normalize_optional_non_negative_float(value: Any) -> float | None:
    if value is None:
        return None
    return _normalize_non_negative_float(value)


def _normalize_required_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Los valores float deben ser números finitos.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("Los valores float deben ser números finitos.")
    return _normalize_float(candidate)


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value


def _normalize_stat_value(value: Any) -> float | int | str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return _normalize_float(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return _normalize_float(float(value))
    if isinstance(value, Real):
        candidate = float(value)
        if not math.isfinite(candidate):
            return None
        return _normalize_float(candidate)
    return str(value)


def _default_metric_sections() -> dict[str, Any]:
    return {key: {} for key in _METRIC_SECTION_KEYS}


def _with_required_metric_sections(value: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    for key in _METRIC_SECTION_KEYS:
        if key not in normalized:
            normalized[key] = {}
    return normalized


def _normalize_metric_payload(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return _normalize_float(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_metric_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_metric_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_metric_payload(item) for item in value)
    return copy.deepcopy(value)


def _validate_states(
    *,
    states: tuple[str, ...],
    default_state: str,
    absorbing_states: tuple[str, ...],
) -> None:
    if not states:
        raise ValueError("states debe contener al menos un estado.")
    if not default_state.strip():
        raise ValueError("default_state no puede estar vacío.")
    if any(not state.strip() for state in states):
        raise ValueError("states no puede contener estados vacíos.")
    if any(not state.strip() for state in absorbing_states):
        raise ValueError("absorbing_states no puede contener estados vacíos.")
    if len(set(states)) != len(states):
        raise ValueError("states no puede contener duplicados.")
    if default_state not in states:
        raise ValueError("states debe contener default_state.")
    absorbing = set(absorbing_states)
    unknown_absorbing = sorted(absorbing - set(states))
    if unknown_absorbing:
        raise ValueError(f"absorbing_states debe ser subconjunto de states: {unknown_absorbing}.")
    if default_state not in absorbing:
        raise ValueError("absorbing_states debe contener default_state.")
