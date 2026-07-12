"""DTOs puros de resultados de desempeño post-modelo (SDD-11 §4/§6).

Este módulo publica contenedores Pydantic para salidas ya calculadas por la futura capa
``performance``. No calcula AUC, Gini, KS ni tablas de gains; solo fija contratos de I/O,
normalización numérica y copias defensivas. Tampoco importa ``pandas``, ``numpy``, ``scipy`` ni
``sklearn`` en runtime para preservar el import liviano de ``nikodym.performance``.

El contrato canónico de ``performance_table`` y ``discriminant_metrics`` es el de SDD-11 §6, con
columnas exactas y orden estable. Los floats publicados normalizan ``-0.0`` como ``0.0`` y los
valores no finitos de métricas opcionales se degradan a ``None`` antes de cualquier comparación.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.performance.config import EvaluationSource, PerformancePartition, ScoreDirection

if TYPE_CHECKING:
    import pandas as pd

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any

DiscriminantStatus: TypeAlias = Literal["ok", "not_evaluable", "threshold_flag"]

_PERFORMANCE_TABLE_COLUMNS: tuple[str, ...] = (
    "partition",
    "decile",
    "n_total",
    "n_bad",
    "n_good",
    "bad_rate",
    "good_rate",
    "mean_pd",
    "min_pd",
    "max_pd",
    "mean_score",
    "min_score",
    "max_score",
    "cum_total",
    "cum_bad",
    "cum_good",
    "cum_bad_capture_rate",
    "cum_good_capture_rate",
    "lift",
    "ks_at_decile",
)
_DISCRIMINANT_METRIC_COLUMNS: tuple[str, ...] = (
    "partition",
    "n_total",
    "n_bad",
    "n_good",
    "auc",
    "gini",
    "ks",
    "ks_cutoff_risk_score",
    "ks_cutoff_score",
    "tpr_at_ks",
    "fpr_at_ks",
    "source",
    "status",
)
_DISCRIMINANT_METRIC_NAMES: tuple[str, ...] = ("auc", "gini", "ks")

__all__ = [
    "DecilePerformanceRecord",
    "DiscriminantMetricRecord",
    "EvaluationSource",
    "PerformanceCardSection",
    "PerformancePartition",
    "PerformanceResult",
    "ScoreDirection",
]


class DiscriminantMetricRecord(BaseModel):
    """Fila publicada de ``discriminant_metrics`` para una partición evaluada."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    n_total: int = Field(ge=0)
    n_bad: int = Field(ge=0)
    n_good: int = Field(ge=0)
    auc: float | None
    gini: float | None
    ks: float | None
    ks_cutoff_risk_score: float | None
    ks_cutoff_score: float | None
    tpr_at_ks: float | None
    fpr_at_ks: float | None
    source: EvaluationSource
    status: DiscriminantStatus

    @field_validator(
        "auc",
        "gini",
        "ks",
        "ks_cutoff_risk_score",
        "ks_cutoff_score",
        "tpr_at_ks",
        "fpr_at_ks",
        mode="before",
    )
    @classmethod
    def _normaliza_float_opcional(cls, value: Any) -> float | None:
        """Descarta no-finitos y publica ``-0.0`` como ``0.0`` en métricas opcionales."""
        return _normalize_optional_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida población y presencia de métricas según estado de la partición."""
        if self.n_total != self.n_bad + self.n_good:
            raise ValueError("n_total debe coincidir con n_bad + n_good.")

        required_when_evaluable = (
            self.auc,
            self.gini,
            self.ks,
            self.ks_cutoff_risk_score,
            self.tpr_at_ks,
            self.fpr_at_ks,
        )
        if self.status == "not_evaluable":
            optional_values = (*required_when_evaluable, self.ks_cutoff_score)
            if any(value is not None for value in optional_values):
                raise ValueError("Una partición not_evaluable no debe publicar métricas.")
            return self

        if any(value is None for value in required_when_evaluable):
            raise ValueError("Las particiones evaluables deben publicar AUC, Gini, KS y corte.")
        if self.source == "score" and self.ks_cutoff_score is None:
            raise ValueError("ks_cutoff_score es obligatorio cuando source='score'.")
        return self


class DecilePerformanceRecord(BaseModel):
    """Fila publicada de ``performance_table`` para un decil de riesgo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    decile: int = Field(ge=1)
    n_total: int = Field(ge=0)
    n_bad: int = Field(ge=0)
    n_good: int = Field(ge=0)
    bad_rate: float
    good_rate: float
    mean_pd: float
    min_pd: float
    max_pd: float
    mean_score: float
    min_score: float
    max_score: float
    cum_total: int = Field(ge=0)
    cum_bad: int = Field(ge=0)
    cum_good: int = Field(ge=0)
    cum_bad_capture_rate: float
    cum_good_capture_rate: float
    lift: float
    ks_at_decile: float

    @field_validator(
        "bad_rate",
        "good_rate",
        "mean_pd",
        "min_pd",
        "max_pd",
        "mean_score",
        "min_score",
        "max_score",
        "cum_bad_capture_rate",
        "cum_good_capture_rate",
        "lift",
        "ks_at_decile",
        mode="before",
    )
    @classmethod
    def _normaliza_float_requerido(cls, value: Any) -> float:
        """Exige floats finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida conteos y rangos internos sin comparar valores no finitos."""
        if self.n_total != self.n_bad + self.n_good:
            raise ValueError("n_total debe coincidir con n_bad + n_good.")
        if self.cum_total != self.cum_bad + self.cum_good:
            raise ValueError("cum_total debe coincidir con cum_bad + cum_good.")
        if not self.min_pd <= self.mean_pd <= self.max_pd:
            raise ValueError("min_pd <= mean_pd <= max_pd debe cumplirse.")
        if not self.min_score <= self.mean_score <= self.max_score:
            raise ValueError("min_score <= mean_score <= max_score debe cumplirse.")
        return self


class PerformanceCardSection(BaseModel):
    """Resumen determinista de desempeño para model card, governance y reportes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "bands_by_partition",
            "dependency_versions",
            "max_metrics_by_partition",
            "metric_sections",
            "thresholds",
        }
    )

    evaluation_source: EvaluationSource
    score_direction: ScoreDirection
    partitions: tuple[str, ...]
    thresholds: dict[str, float] = Field(default_factory=dict)
    max_metrics_by_partition: dict[str, dict[str, float | None]]
    bands_by_partition: dict[str, str]
    n_deciles: int = Field(ge=1)
    dependency_versions: dict[str, str]
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("thresholds", mode="before")
    @classmethod
    def _copia_thresholds(cls, value: Any) -> Any:
        """Copia y ordena umbrales institucionales finitos."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            normalized: dict[str, float] = {}
            for key, threshold in sorted(value.items()):
                finite = _finite_number(threshold)
                if finite is None:
                    raise ValueError("thresholds debe contener valores numéricos finitos.")
                normalized[str(key)] = finite
            return normalized
        return value

    @field_validator("max_metrics_by_partition", mode="before")
    @classmethod
    def _copia_max_metrics(cls, value: Any) -> Any:
        """Copia métricas máximas y neutraliza no-finitos antes de serializar."""
        return _normalize_metric_map(value)

    @field_validator("bands_by_partition", "dependency_versions")
    @classmethod
    def _ordena_dict_str(cls, values: dict[str, str]) -> dict[str, str]:
        """Ordena mapas de texto para serialización determinista."""
        return {name: values[name] for name in sorted(values)}

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
    def _check_invariantes(self) -> Self:
        """Valida que la tarjeta pueda reconstruir particiones, bandas y máximos."""
        if not self.partitions:
            raise ValueError("partitions debe contener al menos una partición.")
        if len(set(self.partitions)) != len(self.partitions):
            raise ValueError("partitions no debe contener duplicados.")

        partition_set = set(self.partitions)
        if set(self.bands_by_partition) != partition_set:
            raise ValueError("bands_by_partition debe tener las mismas particiones que partitions.")
        if set(self.max_metrics_by_partition) != partition_set:
            raise ValueError(
                "max_metrics_by_partition debe tener las mismas particiones que partitions."
            )
        for partition, metrics in self.max_metrics_by_partition.items():
            if set(metrics) != set(_DISCRIMINANT_METRIC_NAMES):
                raise ValueError(
                    f"max_metrics_by_partition debe publicar auc, gini y ks para {partition!r}."
                )
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            if name in {"max_metrics_by_partition", "metric_sections"}:
                return copy.deepcopy(value)
            return dict(value)
        return value


class PerformanceResult(BaseModel):
    """Contenedor agregado de artefactos publicados por la capa ``performance``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"discriminant_metrics", "performance_table"}
    )

    performance_table: DataFrameLike
    discriminant_metrics: DataFrameLike
    performance_records: tuple[DecilePerformanceRecord, ...]
    discriminant_records: tuple[DiscriminantMetricRecord, ...]
    card: PerformanceCardSection

    @field_validator("performance_table", mode="before")
    @classmethod
    def _copia_performance_table(cls, value: Any) -> Any:
        """Copia el frame de gains y valida sus columnas canónicas."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_PERFORMANCE_TABLE_COLUMNS,
            field_name="performance_table",
        )

    @field_validator("discriminant_metrics", mode="before")
    @classmethod
    def _copia_discriminant_metrics(cls, value: Any) -> Any:
        """Copia el frame de métricas discriminantes y valida sus columnas canónicas."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_DISCRIMINANT_METRIC_COLUMNS,
            field_name="discriminant_metrics",
        )

    @model_validator(mode="after")
    def _check_consistencia_con_card(self) -> Self:
        """Valida que records y tarjeta describan el mismo resultado agregado."""
        record_partitions = tuple(
            metric_record.partition for metric_record in self.discriminant_records
        )
        if record_partitions != self.card.partitions:
            raise ValueError("card.partitions debe coincidir con discriminant_records.")

        for metric_record in self.discriminant_records:
            if metric_record.source != self.card.evaluation_source:
                raise ValueError("evaluation_source debe coincidir con source de cada record.")

        expected_metrics = _metrics_by_partition(self.discriminant_records)
        if expected_metrics != self.card.max_metrics_by_partition:
            raise ValueError("max_metrics_by_partition debe coincidir con discriminant_records.")

        known_partitions = set(self.card.partitions)
        unknown_partitions = {
            performance_record.partition
            for performance_record in self.performance_records
            if performance_record.partition not in known_partitions
        }
        if unknown_partitions:
            raise ValueError("performance_records contiene particiones no resumidas en card.")

        for performance_record in self.performance_records:
            if performance_record.decile > self.card.n_deciles:
                raise ValueError("Los deciles publicados no pueden exceder card.n_deciles.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el DTO."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value


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
            f"{field_name} debe tener exactamente las columnas canónicas de SDD-11 §6."
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


def _metrics_by_partition(
    records: tuple[DiscriminantMetricRecord, ...],
) -> dict[str, dict[str, float | None]]:
    return {
        record.partition: {"auc": record.auc, "gini": record.gini, "ks": record.ks}
        for record in records
    }


def _normalize_metric_map(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value

    normalized: dict[str, dict[str, float | None]] = {}
    for partition in sorted(value, key=str):
        metrics = value[partition]
        if not isinstance(metrics, Mapping):
            return value
        normalized[str(partition)] = {
            str(metric_name): _finite_number(metrics[metric_name])
            for metric_name in sorted(metrics, key=str)
        }
    return normalized


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


def _normalize_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return _finite_number(value)


def _normalize_required_float(value: Any) -> float:
    finite = _finite_number(value)
    if finite is None:
        raise ValueError("Las métricas float deben ser números finitos.")
    return finite


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value
