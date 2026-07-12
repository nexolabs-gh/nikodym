"""DTOs puros de resultados del scorecard log-odds a puntos (SDD-09 §4).

Este módulo publica solo contenedores Pydantic y helpers deterministas para salidas ya
calculadas por la futura capa ``scorecard``. No escala, no transforma y no importa
``statsmodels``, ``sklearn`` ni ``scipy``; el paquete ``nikodym.scorecard`` reexporta estos
símbolos de forma perezosa para preservar el import liviano.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real
from typing import Any, ClassVar, Literal, TypeAlias

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.scorecard.config import RoundingMethod, ScoreDirection

ScorecardPointSource: TypeAlias = Literal["binning_table", "override"]

__all__ = [
    "RoundingMethod",
    "ScoreDirection",
    "ScorecardBinPoint",
    "ScorecardCardSection",
    "ScorecardResult",
]


class ScorecardBinPoint(BaseModel):
    """Punto publicado para una pareja ``feature``/``bin_label`` del scorecard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str
    woe_column: str
    bin_label: str
    bin_index: int | None
    woe: float
    beta: float
    intercept_share: float
    raw_points: float
    points: float | int
    rounding_delta: float
    source: ScorecardPointSource

    @field_validator("woe", "beta", "intercept_share", "raw_points", "rounding_delta", mode="after")
    @classmethod
    def _normaliza_float_requerido(cls, value: float) -> float:
        """Publica ``-0.0`` como ``0.0`` en componentes escalares."""
        return _normalize_float(value)

    @field_validator("points", mode="after")
    @classmethod
    def _normaliza_points(cls, value: float | int) -> float | int:
        """Normaliza ``-0.0`` en puntos publicados sin convertir enteros."""
        if isinstance(value, float):
            return _normalize_float(value)
        return value


class ScorecardCardSection(BaseModel):
    """Resumen determinista de escala y columnas para model card y reporte."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"dependency_versions", "metric_sections"}
    )

    pdo: float
    target_score: float
    target_odds: float
    factor: float
    offset: float
    score_direction: ScoreDirection
    rounding_method: RoundingMethod
    n_variables: int
    score_column: str
    points_columns: tuple[str, ...]
    min_score: float | None
    max_score: float | None
    overrides_count: int
    dependency_versions: dict[str, str]
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("pdo", "target_score", "target_odds", "factor", "offset", mode="after")
    @classmethod
    def _normaliza_float_requerido(cls, value: float) -> float:
        """Publica ``-0.0`` como ``0.0`` en parámetros escalares de la tarjeta."""
        return _normalize_float(value)

    @field_validator("min_score", "max_score", mode="before")
    @classmethod
    def _normaliza_score_opcional(cls, value: Any) -> float | None:
        """Descarta límites no finitos antes de cualquier comparación posterior."""
        if value is None:
            return None
        return _finite_number(value)

    @field_validator("dependency_versions", mode="after")
    @classmethod
    def _ordena_dependency_versions(cls, versions: dict[str, str]) -> dict[str, str]:
        """Ordena versiones por nombre de dependencia para serialización determinista."""
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

    @model_validator(mode="after")
    def _check_invariantes(self) -> ScorecardCardSection:
        """Valida consistencia interna sin ordenar ni reducir números no finitos."""
        if self.n_variables != len(self.points_columns):
            raise ValueError("n_variables debe coincidir con el largo de points_columns.")
        if (
            self.min_score is not None
            and self.max_score is not None
            and self.min_score >= self.max_score
        ):
            raise ValueError("min_score debe ser menor que max_score.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de estructuras mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            if name == "metric_sections":
                return copy.deepcopy(value)
            return dict(value)
        return value


class ScorecardResult(BaseModel):
    """Contenedor agregado de artefactos publicados por la capa ``scorecard``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset({"scorecard", "score"})

    scorecard: pd.DataFrame
    score: pd.DataFrame
    factor: float
    offset: float
    score_direction: ScoreDirection
    points_columns: tuple[str, ...]
    score_column: str
    card: ScorecardCardSection

    @field_validator("scorecard", "score", mode="before")
    @classmethod
    def _copia_dataframe(cls, value: Any) -> Any:
        """Copia profundamente tablas de entrada y normaliza ``-0.0`` en columnas float."""
        if isinstance(value, pd.DataFrame):
            return _copy_dataframe(value)
        return value

    @field_validator("factor", "offset", mode="after")
    @classmethod
    def _normaliza_float_requerido(cls, value: float) -> float:
        """Publica ``-0.0`` como ``0.0`` en escalares del resultado."""
        return _normalize_float(value)

    @model_validator(mode="after")
    def _check_consistencia_con_card_y_score(self) -> ScorecardResult:
        """Valida que el contenedor y la tarjeta describan la misma salida."""
        if self.factor != self.card.factor:
            raise ValueError("factor debe coincidir con card.factor.")
        if self.offset != self.card.offset:
            raise ValueError("offset debe coincidir con card.offset.")
        if self.score_direction != self.card.score_direction:
            raise ValueError("score_direction debe coincidir con card.score_direction.")
        if self.points_columns != self.card.points_columns:
            raise ValueError("points_columns debe coincidir con card.points_columns.")
        if self.score_column != self.card.score_column:
            raise ValueError("score_column debe coincidir con card.score_column.")
        if self.score_column not in self.score.columns:
            raise ValueError("score debe contener la columna score_column.")
        missing_points = tuple(
            column for column in self.points_columns if column not in self.score.columns
        )
        if missing_points:
            raise ValueError(f"score no contiene columnas de puntos: {missing_points!r}.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el DTO."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and isinstance(
            value,
            pd.DataFrame,
        ):
            return _copy_dataframe(value)
        return value


def _copy_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        series = copied[column]
        zero_mask = series == 0.0
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    candidate = float(value)
    if not math.isfinite(candidate):
        return None
    return _normalize_float(candidate)


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


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value
