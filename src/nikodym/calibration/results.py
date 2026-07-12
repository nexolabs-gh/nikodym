"""DTOs puros de resultados de calibración de PD cruda (SDD-10 §4/§6).

Este módulo publica solo contenedores Pydantic y helpers deterministas para salidas ya
calculadas por la futura capa ``calibration``. No ajusta parámetros, no construye el
``calibrated_pd_frame`` y no importa ``pandas``, ``scipy`` ni ``sklearn`` en runtime; el paquete
``nikodym.calibration`` reexporta estos símbolos de forma perezosa para preservar el import
liviano.

El contrato canónico de ``calibrated_pd_frame`` es el de SDD-10 §6: ocho columnas en orden
``partition``, ``target``, ``linear_predictor``, ``pd_raw``, ``linear_predictor_calibrated``,
``pd_calibrated``, ``calibration_method`` y ``anchor_kind``. La tabla abreviada de SDD-10 §4 es
incompleta; B10.3/B10.4 deberán emitir estas ocho columnas, con ``calibration_method`` y
``anchor_kind`` constantes por corrida.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.calibration.config import AnchorKind, AnchorSource, CalibrationMethod

if TYPE_CHECKING:
    import pandas as pd

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any

_CALIBRATED_PD_COLUMNS: tuple[str, ...] = (
    "partition",
    "target",
    "linear_predictor",
    "pd_raw",
    "linear_predictor_calibrated",
    "pd_calibrated",
    "calibration_method",
    "anchor_kind",
)

__all__ = [
    "AnchorKind",
    "AnchorSource",
    "CalibrationCardSection",
    "CalibrationMethod",
    "CalibrationParameters",
    "CalibrationResult",
]


class CalibrationParameters(BaseModel):
    """Parámetros y métricas de ajuste publicados por ``PDCalibrator``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"isotonic_knots"})

    method: CalibrationMethod
    target_pd: float
    anchor_kind: AnchorKind
    anchor_source: AnchorSource
    fit_partition: Literal["desarrollo"]
    offset: float | None
    slope: float | None
    intercept: float | None
    isotonic_knots: tuple[tuple[float, float], ...] = ()
    post_offset: float | None
    target_tolerance: float
    achieved_mean_pd_dev: float
    raw_mean_pd_dev: float
    observed_default_rate_dev: float | None
    n_fit: int

    @field_validator("target_pd", "target_tolerance", "achieved_mean_pd_dev", "raw_mean_pd_dev")
    @classmethod
    def _normaliza_float_requerido(cls, value: float) -> float:
        """Publica ``-0.0`` como ``0.0`` en parámetros escalares requeridos."""
        return _normalize_float(value)

    @field_validator(
        "offset",
        "slope",
        "intercept",
        "post_offset",
        "observed_default_rate_dev",
    )
    @classmethod
    def _normaliza_float_opcional(cls, value: float | None) -> float | None:
        """Publica ``-0.0`` como ``0.0`` en parámetros escalares opcionales."""
        return _normalize_optional_float(value)

    @field_validator("isotonic_knots")
    @classmethod
    def _normaliza_isotonic_knots(
        cls,
        knots: tuple[tuple[float, float], ...],
    ) -> tuple[tuple[float, float], ...]:
        """Copia y normaliza los knots isotónicos sin mutar la entrada."""
        return tuple((_normalize_float(x), _normalize_float(y)) for x, y in knots)

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de estructuras normalizadas aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return tuple(tuple(pair) for pair in value)
        return value


class CalibrationCardSection(BaseModel):
    """Resumen determinista de calibración para model card y reporte."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"dependency_versions", "metric_sections"}
    )

    method: CalibrationMethod
    target_pd: float
    anchor_kind: AnchorKind
    anchor_source: AnchorSource
    fit_partition: Literal["desarrollo"]
    n_fit: int
    raw_mean_pd_dev: float
    calibrated_mean_pd_dev: float
    observed_default_rate_dev: float | None
    offset: float | None
    slope: float | None
    intercept: float | None
    ranking_preserved: bool
    ties_created: int
    pd_raw_column: str
    pd_calibrated_column: str
    dependency_versions: dict[str, str]
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_pd", "raw_mean_pd_dev", "calibrated_mean_pd_dev")
    @classmethod
    def _normaliza_float_requerido(cls, value: float) -> float:
        """Publica ``-0.0`` como ``0.0`` en métricas escalares de la tarjeta."""
        return _normalize_float(value)

    @field_validator("observed_default_rate_dev", "offset", "slope", "intercept")
    @classmethod
    def _normaliza_float_opcional(cls, value: float | None) -> float | None:
        """Publica ``-0.0`` como ``0.0`` en métricas opcionales de la tarjeta."""
        return _normalize_optional_float(value)

    @field_validator("dependency_versions")
    @classmethod
    def _ordena_dependency_versions(cls, versions: dict[str, str]) -> dict[str, str]:
        """Ordena versiones por dependencia para serialización determinista."""
        return {name: versions[name] for name in sorted(versions)}

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia profundamente la puerta CT-2 de métricas aditivas."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(dict(value))
        return value

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de estructuras mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            if name == "metric_sections":
                return copy.deepcopy(value)
            return dict(value)
        return value


class CalibrationResult(BaseModel):
    """Contenedor agregado de artefactos publicados por la capa ``calibration``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset({"calibrated_pd_frame"})

    calibrated_pd_frame: DataFrameLike
    parameters: CalibrationParameters
    card: CalibrationCardSection

    @field_validator("calibrated_pd_frame", mode="before")
    @classmethod
    def _copia_dataframe(cls, value: Any) -> Any:
        """Copia profundamente el frame calibrado y normaliza ``-0.0`` en columnas float."""
        if not _is_dataframe_like(value):
            raise ValueError("calibrated_pd_frame debe ser un pandas.DataFrame.")

        copied = _copy_dataframe(value)
        observed_columns = tuple(str(column) for column in copied.columns)
        if observed_columns != _CALIBRATED_PD_COLUMNS:
            raise ValueError(
                "calibrated_pd_frame debe tener exactamente las columnas canónicas de SDD-10 §6."
            )
        return copied

    @model_validator(mode="after")
    def _check_consistencia_con_card(self) -> Self:
        """Valida que la tarjeta resuma los mismos parámetros que el resultado."""
        pairs: tuple[tuple[str, object, object], ...] = (
            ("method", self.parameters.method, self.card.method),
            ("target_pd", self.parameters.target_pd, self.card.target_pd),
            ("anchor_kind", self.parameters.anchor_kind, self.card.anchor_kind),
            ("anchor_source", self.parameters.anchor_source, self.card.anchor_source),
            ("fit_partition", self.parameters.fit_partition, self.card.fit_partition),
            ("n_fit", self.parameters.n_fit, self.card.n_fit),
            ("raw_mean_pd_dev", self.parameters.raw_mean_pd_dev, self.card.raw_mean_pd_dev),
            (
                "calibrated_mean_pd_dev",
                self.parameters.achieved_mean_pd_dev,
                self.card.calibrated_mean_pd_dev,
            ),
            (
                "observed_default_rate_dev",
                self.parameters.observed_default_rate_dev,
                self.card.observed_default_rate_dev,
            ),
            ("offset", self.parameters.offset, self.card.offset),
            ("slope", self.parameters.slope, self.card.slope),
            ("intercept", self.parameters.intercept, self.card.intercept),
        )
        for field_name, parameter_value, card_value in pairs:
            if parameter_value != card_value:
                raise ValueError(f"{field_name} debe coincidir entre parameters y card.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el DTO."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value


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


def _normalize_optional_float(value: float | None) -> float | None:
    if value is None:
        return None
    return _normalize_float(value)


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value
