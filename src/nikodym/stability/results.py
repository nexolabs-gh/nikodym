"""DTOs puros de resultados de estabilidad post-modelo (SDD-11 §4/§6).

Este módulo publica contenedores Pydantic para salidas ya calculadas por la futura capa
``stability``. No calcula PSI, CSI ni estabilidad temporal; solo fija contratos de I/O,
normalización numérica y copias defensivas. Tampoco importa ``pandas``, ``numpy``, ``scipy`` ni
``sklearn`` en runtime para preservar el import liviano de ``nikodym.stability``.

El contrato canónico de ``psi_table`` y ``stability_metrics`` es el de SDD-11 §6, con columnas
exactas y orden estable. Los floats publicados normalizan ``-0.0`` como ``0.0`` y los valores no
finitos de métricas opcionales se degradan a ``None`` antes de cualquier comparación. La banda
(``stable``/``review``/``redevelop``/``not_evaluable``) determina de forma única la acción
auditada (``none``/``vigilar``/``redesarrollar``).

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.stability.config import CsiSource, ScoreDirection, StabilityComparison

if TYPE_CHECKING:
    import pandas as pd

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any

PsiMetricName: TypeAlias = Literal["score_psi", "pd_psi"]
CsiMetricName: TypeAlias = Literal["csi"]
StabilityMetricName: TypeAlias = Literal["score_psi", "pd_psi", "csi", "temporal_score"]
StabilityBand: TypeAlias = Literal["stable", "review", "redevelop", "not_evaluable"]
StabilityAction: TypeAlias = Literal["none", "vigilar", "redesarrollar"]

_PSI_TABLE_COLUMNS: tuple[str, ...] = (
    "metric",
    "comparison",
    "feature",
    "bin_label",
    "expected_count",
    "actual_count",
    "expected_pct",
    "actual_pct",
    "component_value",
    "total_value",
    "band",
)
_STABILITY_METRIC_COLUMNS: tuple[str, ...] = (
    "metric",
    "comparison",
    "feature",
    "value",
    "stable_threshold",
    "review_threshold",
    "band",
    "action",
)

# Mapa determinista banda -> acción auditada (SDD-11 §6/§8). Una banda fija su única acción.
_BAND_TO_ACTION: dict[str, str] = {
    "stable": "none",
    "review": "vigilar",
    "redevelop": "redesarrollar",
    "not_evaluable": "none",
}

__all__ = [
    "CsiRecord",
    "CsiSource",
    "PsiRecord",
    "ScoreDirection",
    "StabilityCardSection",
    "StabilityComparison",
    "StabilityMetricRecord",
    "StabilityResult",
    "TemporalStabilityRecord",
]


class StabilityMetricRecord(BaseModel):
    """Fila publicada de ``stability_metrics`` para una métrica/comparación resumida."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: StabilityMetricName
    comparison: str
    feature: str
    value: float | None
    stable_threshold: float
    review_threshold: float
    band: StabilityBand
    action: StabilityAction

    @field_validator("value", mode="before")
    @classmethod
    def _normaliza_value(cls, value: Any) -> float | None:
        """Descarta no-finitos y publica ``-0.0`` como ``0.0`` en el indicador opcional."""
        return _normalize_optional_float(value)

    @field_validator("stable_threshold", "review_threshold", mode="before")
    @classmethod
    def _normaliza_umbral(cls, value: Any) -> float:
        """Exige umbrales float finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida umbrales, mapa banda->acción y la regla métrica<=>evaluable."""
        if self.stable_threshold > self.review_threshold:
            raise ValueError("stable_threshold no puede superar review_threshold.")

        expected_action = _BAND_TO_ACTION[self.band]
        if self.action != expected_action:
            raise ValueError(f"La acción de la banda {self.band!r} debe ser {expected_action!r}.")

        if self.band == "not_evaluable":
            if self.value is not None:
                raise ValueError("Una métrica not_evaluable no debe publicar value.")
            return self
        if self.value is None:
            raise ValueError("Las métricas evaluables deben publicar un value finito.")
        return self


class PsiRecord(BaseModel):
    """Fila publicada de ``psi_table`` para un bin de PSI de score o PD calibrada."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: PsiMetricName
    comparison: str
    feature: str
    bin_label: str
    expected_count: int = Field(ge=0)
    actual_count: int = Field(ge=0)
    expected_pct: float
    actual_pct: float
    component_value: float
    total_value: float
    band: StabilityBand

    @field_validator(
        "expected_pct",
        "actual_pct",
        "component_value",
        "total_value",
        mode="before",
    )
    @classmethod
    def _normaliza_float_requerido(cls, value: Any) -> float:
        """Exige floats finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida que las proporciones suavizadas queden en ``[0, 1]``."""
        _check_proportions(self.expected_pct, self.actual_pct)
        return self


class CsiRecord(BaseModel):
    """Fila publicada de ``psi_table`` para un bin de CSI de una característica final."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: CsiMetricName
    comparison: str
    feature: str
    bin_label: str
    expected_count: int = Field(ge=0)
    actual_count: int = Field(ge=0)
    expected_pct: float
    actual_pct: float
    component_value: float
    total_value: float
    band: StabilityBand

    @field_validator(
        "expected_pct",
        "actual_pct",
        "component_value",
        "total_value",
        mode="before",
    )
    @classmethod
    def _normaliza_float_requerido(cls, value: Any) -> float:
        """Exige floats finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida que las proporciones suavizadas queden en ``[0, 1]``."""
        _check_proportions(self.expected_pct, self.actual_pct)
        return self


class TemporalStabilityRecord(BaseModel):
    """Resumen de estabilidad temporal del score/PD para un período o cohorte."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    period: str
    n_total: int = Field(ge=0)
    mean_score: float | None
    p25_score: float | None
    p50_score: float | None
    p75_score: float | None
    mean_pd: float | None
    psi: float | None
    band: StabilityBand

    @field_validator(
        "mean_score",
        "p25_score",
        "p50_score",
        "p75_score",
        "mean_pd",
        "psi",
        mode="before",
    )
    @classmethod
    def _normaliza_float_opcional(cls, value: Any) -> float | None:
        """Descarta no-finitos y publica ``-0.0`` como ``0.0`` en agregados opcionales."""
        return _normalize_optional_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida la regla métrica<=>evaluable y el orden de cuantiles."""
        mean_score = self.mean_score
        p25 = self.p25_score
        p50 = self.p50_score
        p75 = self.p75_score
        psi = self.psi
        optional_values = (mean_score, p25, p50, p75, self.mean_pd, psi)
        if self.band == "not_evaluable":
            if any(value is not None for value in optional_values):
                raise ValueError("Un período not_evaluable no debe publicar métricas.")
            return self
        if mean_score is None or p25 is None or p50 is None or p75 is None or psi is None:
            raise ValueError("Los períodos evaluables deben publicar score, cuantiles y PSI.")
        if not p25 <= p50 <= p75:
            raise ValueError("Debe cumplirse p25_score <= p50_score <= p75_score.")
        return self


class StabilityCardSection(BaseModel):
    """Resumen determinista de estabilidad para model card, governance y reportes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "bands_by_comparison",
            "dependency_versions",
            "max_psi_by_comparison",
            "metric_sections",
        }
    )

    score_direction: ScoreDirection
    csi_source: CsiSource
    comparisons: tuple[str, ...]
    psi_bins: int = Field(ge=2)
    stable_threshold: float
    review_threshold: float
    max_psi_by_comparison: dict[str, float | None]
    bands_by_comparison: dict[str, str]
    worst_csi_feature: str | None = None
    worst_csi_value: float | None = None
    dependency_versions: dict[str, str]
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("stable_threshold", "review_threshold", mode="before")
    @classmethod
    def _normaliza_umbral(cls, value: Any) -> float:
        """Exige umbrales float finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @field_validator("worst_csi_value", mode="before")
    @classmethod
    def _normaliza_worst_csi(cls, value: Any) -> float | None:
        """Descarta no-finitos y publica ``-0.0`` como ``0.0`` en el peor CSI."""
        return _normalize_optional_float(value)

    @field_validator("max_psi_by_comparison", mode="before")
    @classmethod
    def _copia_max_psi(cls, value: Any) -> Any:
        """Copia los PSI máximos por comparación y neutraliza no-finitos."""
        return _normalize_optional_float_map(value)

    @field_validator("bands_by_comparison", "dependency_versions")
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
        """Valida que la tarjeta pueda reconstruir comparaciones, bandas y máximos."""
        if not self.comparisons:
            raise ValueError("comparisons debe contener al menos una comparación.")
        if len(set(self.comparisons)) != len(self.comparisons):
            raise ValueError("comparisons no debe contener duplicados.")

        comparison_set = set(self.comparisons)
        if set(self.bands_by_comparison) != comparison_set:
            raise ValueError(
                "bands_by_comparison debe tener las mismas comparaciones que comparisons."
            )
        if set(self.max_psi_by_comparison) != comparison_set:
            raise ValueError(
                "max_psi_by_comparison debe tener las mismas comparaciones que comparisons."
            )
        if self.stable_threshold > self.review_threshold:
            raise ValueError("stable_threshold no puede superar review_threshold.")
        if (self.worst_csi_feature is None) != (self.worst_csi_value is None):
            raise ValueError("worst_csi_feature y worst_csi_value deben definirse juntos.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            if name in {"max_psi_by_comparison", "metric_sections"}:
                return copy.deepcopy(value)
            return dict(value)
        return value


class StabilityResult(BaseModel):
    """Contenedor agregado de artefactos publicados por la capa ``stability``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset({"psi_table", "stability_metrics"})

    psi_table: DataFrameLike
    stability_metrics: DataFrameLike
    psi_records: tuple[PsiRecord, ...]
    csi_records: tuple[CsiRecord, ...]
    metric_records: tuple[StabilityMetricRecord, ...]
    temporal_records: tuple[TemporalStabilityRecord, ...]
    card: StabilityCardSection

    @field_validator("psi_table", mode="before")
    @classmethod
    def _copia_psi_table(cls, value: Any) -> Any:
        """Copia el frame de bins PSI/CSI y valida sus columnas canónicas."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_PSI_TABLE_COLUMNS,
            field_name="psi_table",
        )

    @field_validator("stability_metrics", mode="before")
    @classmethod
    def _copia_stability_metrics(cls, value: Any) -> Any:
        """Copia el frame de métricas resumidas y valida sus columnas canónicas."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_STABILITY_METRIC_COLUMNS,
            field_name="stability_metrics",
        )

    @model_validator(mode="after")
    def _check_consistencia_con_card(self) -> Self:
        """Valida que records y tarjeta describan el mismo resultado agregado."""
        psi_comparisons = tuple(
            record.comparison for record in self.metric_records if record.metric == "score_psi"
        )
        if psi_comparisons != self.card.comparisons:
            raise ValueError(
                "card.comparisons debe coincidir con las comparaciones score_psi de metric_records."
            )

        if _max_psi_by_comparison(self.metric_records) != self.card.max_psi_by_comparison:
            raise ValueError("max_psi_by_comparison debe coincidir con metric_records.")
        if _bands_by_comparison(self.metric_records) != self.card.bands_by_comparison:
            raise ValueError("bands_by_comparison debe coincidir con metric_records.")

        worst_feature, worst_value = _worst_csi(self.metric_records)
        if worst_feature != self.card.worst_csi_feature or worst_value != self.card.worst_csi_value:
            raise ValueError("worst_csi debe coincidir con los registros CSI de metric_records.")

        known_comparisons = set(self.card.comparisons)
        unknown_psi = {
            record.comparison
            for record in self.psi_records
            if record.comparison not in known_comparisons
        }
        if unknown_psi:
            raise ValueError("psi_records contiene comparaciones no resumidas en card.")
        unknown_csi = {
            record.comparison
            for record in self.csi_records
            if record.comparison not in known_comparisons
        }
        if unknown_csi:
            raise ValueError("csi_records contiene comparaciones no resumidas en card.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el DTO."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value


def _check_proportions(expected_pct: float, actual_pct: float) -> None:
    if not 0.0 <= expected_pct <= 1.0:
        raise ValueError("expected_pct debe estar en [0, 1].")
    if not 0.0 <= actual_pct <= 1.0:
        raise ValueError("actual_pct debe estar en [0, 1].")


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


def _max_psi_by_comparison(
    records: tuple[StabilityMetricRecord, ...],
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for record in records:
        if record.metric not in ("score_psi", "pd_psi"):
            continue
        comparison = record.comparison
        if comparison not in result:
            result[comparison] = record.value
        elif record.value is not None:
            current = result[comparison]
            result[comparison] = record.value if current is None else max(current, record.value)
    return result


def _bands_by_comparison(
    records: tuple[StabilityMetricRecord, ...],
) -> dict[str, str]:
    return {record.comparison: record.band for record in records if record.metric == "score_psi"}


def _worst_csi(
    records: tuple[StabilityMetricRecord, ...],
) -> tuple[str | None, float | None]:
    worst_feature: str | None = None
    worst_value: float | None = None
    for record in records:
        if record.metric != "csi" or record.value is None:
            continue
        if worst_value is None or record.value > worst_value:
            worst_value = record.value
            worst_feature = record.feature
    return worst_feature, worst_value


def _normalize_optional_float_map(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    return {str(key): _finite_number(value[key]) for key in sorted(value, key=str)}


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
