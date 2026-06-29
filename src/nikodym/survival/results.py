"""DTOs puros de resultados de survival y lifetime PD (SDD-18 §4/§6).

Este módulo fija los contenedores Pydantic publicados por ``survival``: filas tidy de
term-structure, diagnósticos, tarjeta CT-2 y resultado agregado. No ajusta modelos, no calcula
Kaplan-Meier/Cox/AFT y no importa ``pandas``, ``lifelines`` ni ``statsmodels`` en runtime al cargar
el módulo.

La tabla ``term_structure`` usa la columna canónica ``warning_codes`` (SDD-18 §6), mientras el DTO
fila usa el campo público ``warnings`` (SDD-18 §4). Ese mapeo es intencional: ``warnings`` es el
nombre ergonómico del registro Pydantic y ``warning_codes`` es el nombre estable de la tabla tidy
que consumen IFRS 9, forward-looking y reportes.

``metric_sections`` conserva la puerta CT-2 como payload aditivo y preserva el orden de inserción.
Las colecciones mutables y DataFrames se copian defensivamente al validar y al acceder desde los
DTOs; los floats publicados normalizan ``-0.0`` como ``0.0``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from decimal import Decimal
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.survival.base import BaseSurvivalModel
from nikodym.survival.config import AftFamily, DiscreteHazardLink, PdSource, SurvivalMethod
from nikodym.survival.exceptions import SurvivalTransformError

if TYPE_CHECKING:
    import pandas

    DataFrameLike: TypeAlias = pandas.DataFrame
else:
    DataFrameLike: TypeAlias = Any

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
    "term_structure_summary",
    "schoenfeld",
    "km_greenwood",
    "person_period",
)
_FLOAT_ATOL = 1e-12
_FLOAT_RTOL = 1e-12

__all__ = [
    "AftFamily",
    "DiscreteHazardLink",
    "PdSource",
    "SurvivalCard",
    "SurvivalDiagnostics",
    "SurvivalMethod",
    "SurvivalResult",
    "SurvivalTermRecord",
]


class SurvivalTermRecord(BaseModel):
    """Fila Pydantic de ``term_structure``; su ``warnings`` mapea a ``warning_codes``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_id: str
    period: int = Field(ge=1)
    time_value: float
    survival: float
    hazard: float | None
    pd_marginal: float
    pd_cumulative: float
    method: SurvivalMethod
    pd_source: PdSource
    segment: str | None = None
    scenario: str | None = None
    warnings: tuple[str, ...] = ()

    @field_validator("time_value", "survival", "pd_marginal", "pd_cumulative", mode="before")
    @classmethod
    def _normaliza_float_requerido(cls, value: Any) -> float:
        """Exige floats finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @field_validator("hazard", mode="before")
    @classmethod
    def _normaliza_hazard(cls, value: Any) -> float | None:
        """Exige hazard finito cuando se publica y normaliza ``-0.0``."""
        return _normalize_optional_required_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> SurvivalTermRecord:
        """Valida rangos y consistencia ``pd_cumulative = 1 - survival``."""
        _check_unit_interval(self.survival, field_name="survival")
        if self.hazard is not None:
            _check_unit_interval(self.hazard, field_name="hazard")
        _check_unit_interval(self.pd_cumulative, field_name="pd_cumulative")
        if self.pd_marginal < 0.0:
            raise ValueError("pd_marginal debe ser mayor o igual a 0.")
        if self.time_value < 0.0:
            raise ValueError("time_value debe ser mayor o igual a 0.")
        _check_pd_cumulative_consistency(self.survival, self.pd_cumulative)
        return self


class SurvivalDiagnostics(BaseModel):
    """Diagnósticos publicados por el ajuste survival sin depender de motores externos."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"fit_statistics", "schoenfeld_test"}
    )

    method: SurvivalMethod
    n_rows: int = Field(ge=0)
    n_events: int = Field(ge=0)
    n_censored: int = Field(ge=0)
    max_observed_time: float
    link: DiscreteHazardLink | None = None
    schoenfeld_test: dict[str, Any] | None = None
    aft_family: AftFamily | None = None
    fit_statistics: dict[str, float | int | str | None] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @field_validator("max_observed_time", mode="before")
    @classmethod
    def _normaliza_tiempo_maximo(cls, value: Any) -> float:
        """Exige tiempo observado finito y no negativo."""
        normalized = _normalize_required_float(value)
        if normalized < 0.0:
            raise ValueError("max_observed_time debe ser mayor o igual a 0.")
        return normalized

    @field_validator("schoenfeld_test", mode="before")
    @classmethod
    def _copia_schoenfeld(cls, value: Any) -> Any:
        """Copia el diagnóstico Schoenfeld sin ordenar sus llaves."""
        if value is None:
            return None
        if isinstance(value, Mapping):
            return _normalize_metric_payload(value)
        return value

    @field_validator("fit_statistics", mode="before")
    @classmethod
    def _copia_fit_statistics(cls, value: Any) -> Any:
        """Copia estadísticas de ajuste y normaliza floats no finitos."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {str(key): _normalize_stat_value(item) for key, item in value.items()}
        return value

    @model_validator(mode="after")
    def _check_conteos(self) -> SurvivalDiagnostics:
        """Valida que eventos y censuras no excedan el universo diagnosticado."""
        if self.n_events + self.n_censored > self.n_rows:
            raise ValueError("n_events + n_censored no puede superar n_rows.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class SurvivalCard(BaseModel):
    """Resumen determinista CT-2 para governance, inventario y reportes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"dependency_versions", "metric_sections"}
    )

    method: SurvivalMethod
    pd_source: PdSource
    duration_col: str
    event_col: str
    time_unit: str
    n_rows: int = Field(ge=0)
    n_events: int = Field(ge=0)
    n_periods: int = Field(ge=0)
    output_columns: tuple[str, ...]
    diagnostics: SurvivalDiagnostics
    dependency_versions: dict[str, str]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=lambda: _default_metric_sections())

    @field_validator("duration_col", "event_col", "time_unit")
    @classmethod
    def _valida_texto_no_vacio(cls, value: str) -> str:
        """Valida campos descriptivos no vacíos."""
        if not value.strip():
            raise ValueError("Las columnas y la unidad temporal no pueden estar vacías.")
        return value

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
        """Copia y completa las secciones CT-2 sin ordenar llaves."""
        if value is None:
            normalized: dict[str, Any] = {}
        elif isinstance(value, Mapping):
            normalized = _normalize_metric_payload(value)
        else:
            return value
        return _with_required_metric_sections(normalized)

    @model_validator(mode="after")
    def _check_card(self) -> SurvivalCard:
        """Valida conteos mínimos y consistencia con diagnostics."""
        if self.n_events > self.n_rows:
            raise ValueError("n_events no puede superar n_rows.")
        if self.diagnostics.method != self.method:
            raise ValueError("diagnostics.method debe coincidir con card.method.")
        if self.diagnostics.n_rows != self.n_rows or self.diagnostics.n_events != self.n_events:
            raise ValueError("diagnostics debe coincidir con los conteos de la card.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class SurvivalResult(BaseModel):
    """Contenedor agregado de artefactos publicados por la capa ``survival``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"hazard_frame", "survival_curve_frame", "term_structure_frame"}
    )

    estimator: BaseSurvivalModel
    term_structure_frame: DataFrameLike | None
    survival_curve_frame: DataFrameLike
    hazard_frame: DataFrameLike
    diagnostics: SurvivalDiagnostics
    card: SurvivalCard

    @field_validator("term_structure_frame", mode="before")
    @classmethod
    def _copia_term_structure(cls, value: Any) -> Any:
        """Copia y valida la tabla tidy lifetime PD cuando existe."""
        if value is None:
            return None
        return _copy_and_validate_term_structure(value)

    @field_validator("survival_curve_frame", "hazard_frame", mode="before")
    @classmethod
    def _copia_dataframe_auxiliar(cls, value: Any) -> Any:
        """Copia DataFrames auxiliares sin imponer columnas futuras."""
        return _copy_required_dataframe(value, field_name="survival_curve_frame/hazard_frame")

    @model_validator(mode="after")
    def _check_consistencia(self) -> SurvivalResult:
        """Valida que card y diagnostics describan el mismo resultado agregado."""
        if self.diagnostics != self.card.diagnostics:
            raise ValueError("card.diagnostics debe coincidir con diagnostics.")
        if (
            self.card.output_columns != _TERM_STRUCTURE_COLUMNS
            and self.term_structure_frame is not None
        ):
            raise ValueError("card.output_columns debe listar las columnas canónicas SDD-18 §6.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value

    def term_structure(self) -> pandas.DataFrame | None:
        """Retorna la tabla tidy lifetime PD o ``None`` si solo hubo diagnóstico.

        Cumple CT-2: SDD-16 puede consumir esta salida cuando existe y agregar LGD/EAD/staging/
        descuento. ``pandas`` se importa perezosamente aquí para mantener liviano
        ``import nikodym.survival.results``.
        """
        frame = self.term_structure_frame
        if frame is None:
            return None

        import pandas as pd

        if not isinstance(frame, pd.DataFrame):
            raise SurvivalTransformError("term_structure_frame debe ser un pandas.DataFrame.")
        return cast("pandas.DataFrame", _copy_dataframe(frame))


def _copy_and_validate_term_structure(value: Any) -> Any:
    copied = _copy_required_dataframe(value, field_name="term_structure_frame")
    observed_columns = tuple(str(column) for column in copied.columns)
    if observed_columns != _TERM_STRUCTURE_COLUMNS:
        raise ValueError(
            "term_structure_frame debe tener exactamente las columnas canónicas de SDD-18 §6."
        )
    _validate_term_structure_values(copied)
    return copied


def _copy_required_dataframe(value: Any, *, field_name: str) -> Any:
    if not _is_dataframe_like(value):
        raise ValueError(f"{field_name} debe ser un pandas.DataFrame.")
    return _copy_dataframe(value)


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


def _validate_term_structure_values(frame: Any) -> None:
    previous_by_curve: dict[tuple[Any, ...], tuple[int, float]] = {}
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
        if previous is not None:
            previous_period, previous_survival = previous
            if period <= previous_period:
                raise ValueError("period debe crecer estrictamente dentro de cada curva.")
            if survival > previous_survival + _FLOAT_ATOL:
                raise ValueError("survival no puede aumentar dentro de una curva.")
        previous_by_curve[curve_key] = (period, survival)


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


def _required_frame_float(value: Any, *, field_name: str) -> float:
    normalized = _normalize_required_float(value)
    return normalized


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


def _normalize_required_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Los valores float deben ser números finitos.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("Los valores float deben ser números finitos.")
    return _normalize_float(candidate)


def _normalize_optional_required_float(value: Any) -> float | None:
    if value is None:
        return None
    return _normalize_required_float(value)


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value


def _normalize_stat_value(value: Any) -> float | int | str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return value
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
