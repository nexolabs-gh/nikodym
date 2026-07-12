"""DTOs puros de resultados del challenger ML (SDD-12 §4/§6).

Este módulo publica los contenedores Pydantic *frozen* que la capa ``ml`` (challenger SVM / Random
Forest / XGBoost / LightGBM / CatBoost) expone a ``validation``/``report``/``governance``: la
comparación cabeza-a-cabeza campeón-vs-challenger, la metadata del backend, la tarjeta CT-2 y el
resultado agregado. **No** entrena, **no** predice, **no** reúsa ``PerformanceEvaluator`` ni
``PDCalibrator`` (eso es el ``MLStep``, B12.3) y **no** importa ``pandas``, ``numpy``, ``sklearn``,
``xgboost``, ``lightgbm`` ni ``catboost`` en runtime: ``pandas`` vive solo bajo ``TYPE_CHECKING`` y
se importa perezosamente dentro de :meth:`MLResult.comparison_frame`, preservando el import liviano
de ``nikodym.ml``.

Forward-ref del campo ``estimator``: el §4 lo anota como ``MLChallenger`` (subclase que crea B12.4).
Como esa clase todavía no existe y el proyecto prohíbe ``model_rebuild()`` (Pydantic 2.13), el campo
se tipa con su clase base concreta ya disponible, :class:`~nikodym.core.base.NikodymClassifier`, y
``arbitrary_types_allowed=True``; en runtime el objeto validado es un ``MLChallenger`` (subclase de
``NikodymClassifier``, luego pasa el ``isinstance`` de Pydantic sin acoplar este módulo a B12.4).

Cumplimiento CT-2: la puerta de extensión es ``MLCardSection.metric_sections`` (tidy, aditiva,
copiada a la lectura); :meth:`MLResult.term_structure` retorna **siempre** ``None`` (``ml`` no es
multi-período, a diferencia de IFRS 9/forward). :meth:`MLResult.comparison_frame` materializa la
proyección tidy de :class:`MLComparisonRecord`.

Orden estable (determinismo, §6/§7): ``feature_importances`` se ordenan descendente por valor con
desempate lexicográfico por nombre; ``monotone_constraints`` preservan el orden de columnas de
``X``; ``comparison_frame()`` preserva el orden de los registros (que el step produce en el orden
de config de particiones y métricas). Los floats normalizan ``-0.0`` como ``0.0`` y **jamás**
publican ``NaN``/``inf`` (fallan explícito o, en ``metric_sections``, degradan a ``None``).

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.core.base import NikodymClassifier
from nikodym.ml.config import ComparisonMetric

if TYPE_CHECKING:
    import pandas as pd

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any

# Orientación del ganador y evaluador de procedencia de cada brecha (SDD-12 §4).
Better: TypeAlias = Literal["champion", "challenger", "tie"]
ComparisonSource: TypeAlias = Literal["performance_evaluator", "stability_evaluator"]

# Columnas canónicas del tidy de comparación (SDD-12 §6, proyección de ``MLComparisonRecord``).
_COMPARISON_COLUMNS: tuple[str, ...] = (
    "partition",
    "metric",
    "champion_value",
    "challenger_value",
    "delta",
    "better",
    "source",
)
# La estabilidad (PSI) sale de ``StabilityEvaluator``; el resto de discriminación, de
# ``PerformanceEvaluator`` (SDD-12 §7, paso 12). El record verifica esta coherencia metric↔source.
_STABILITY_METRICS: frozenset[str] = frozenset({"psi"})

__all__ = [
    "Better",
    "ComparisonMetric",
    "ComparisonSource",
    "MLBackendMetadata",
    "MLCardSection",
    "MLComparisonRecord",
    "MLResult",
]


class MLComparisonRecord(BaseModel):
    """Brecha challenger-vs-campeón para una partición y métrica (SDD-12 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    metric: ComparisonMetric
    champion_value: float
    challenger_value: float
    delta: float
    better: Better
    source: ComparisonSource

    @field_validator("partition")
    @classmethod
    def _valida_partition(cls, value: str) -> str:
        """Valida que la partición comparada no esté vacía."""
        if not value.strip():
            raise ValueError("partition no puede estar vacío.")
        return value

    @field_validator("champion_value", "challenger_value", "delta", mode="before")
    @classmethod
    def _normaliza_valores(cls, value: Any) -> float:
        """Exige valores float finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @model_validator(mode="after")
    def _check_coherencia(self) -> Self:
        """Valida la coherencia entre la métrica y su evaluador de procedencia (§7)."""
        if self.metric in _STABILITY_METRICS:
            if self.source != "stability_evaluator":
                raise ValueError(
                    f"la métrica de estabilidad '{self.metric}' proviene del stability_evaluator."
                )
        elif self.source != "performance_evaluator":
            raise ValueError(
                f"la métrica de discriminación '{self.metric}' proviene del performance_evaluator."
            )
        return self


class MLBackendMetadata(BaseModel):
    """Metadata reproducible del backend fiteado: versión, semilla e importancias (SDD-12 §4/§9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"hyperparameters"})

    backend: str
    backend_version: str
    hyperparameters: dict[str, str | int | float | bool | None]
    seed: int = Field(ge=0)
    n_threads: int = Field(ge=1)
    deterministic: bool
    best_iteration: int | None
    feature_importances: tuple[tuple[str, float], ...]
    monotone_constraints: tuple[tuple[str, int], ...]

    @field_validator("backend", "backend_version")
    @classmethod
    def _valida_texto(cls, value: str) -> str:
        """Valida que el nombre y la versión del backend no estén vacíos."""
        if not value.strip():
            raise ValueError("backend y backend_version no pueden estar vacíos.")
        return value

    @field_validator("hyperparameters", mode="before")
    @classmethod
    def _normaliza_hyperparameters(cls, value: Any) -> Any:
        """Ordena las claves y normaliza los floats de los hiperparámetros (determinismo)."""
        if not isinstance(value, Mapping):
            return value
        normalized = {str(key): _normalize_scalar_value(item) for key, item in value.items()}
        return {key: normalized[key] for key in sorted(normalized)}

    @field_validator("feature_importances", mode="before")
    @classmethod
    def _ordena_importances(cls, value: Any) -> Any:
        """Normaliza y ordena las importancias descendente por valor, desempate por nombre (§7)."""
        items = _coerce_pairs(value)
        if items is None:
            return value
        seen: set[str] = set()
        pairs: list[tuple[str, float]] = []
        for name, raw in items:
            key = str(name)
            if key in seen:
                raise ValueError(f"feature_importances no puede repetir la feature '{key}'.")
            seen.add(key)
            pairs.append((key, _normalize_non_negative_float(raw)))
        pairs.sort(key=lambda pair: (-pair[1], pair[0]))
        return tuple(pairs)

    @field_validator("monotone_constraints", mode="before")
    @classmethod
    def _valida_monotone(cls, value: Any) -> Any:
        """Valida direcciones de monotonía (``-1``/``0``/``1``) preservando el orden de columnas."""
        items = _coerce_pairs(value)
        if items is None:
            return value
        seen: set[str] = set()
        pairs: list[tuple[str, int]] = []
        for name, direction in items:
            key = str(name)
            if not key.strip():
                raise ValueError("monotone_constraints no admite features vacías.")
            if key in seen:
                raise ValueError(f"monotone_constraints no puede repetir la feature '{key}'.")
            if direction not in (-1, 0, 1):
                raise ValueError("la dirección de monotonía debe ser -1, 0 o 1.")
            seen.add(key)
            pairs.append((key, int(direction)))
        return tuple(pairs)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida ``best_iteration`` y que el determinismo byte-a-byte exija single-thread (§9)."""
        if self.best_iteration is not None and self.best_iteration < 0:
            raise ValueError("best_iteration no puede ser negativo.")
        if self.deterministic and self.n_threads != 1:
            raise ValueError(
                "un resultado byte-a-byte determinista exige n_threads=1 (GBDT multihilo no lo es)."
            )
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega una copia de los hiperparámetros mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return dict(value)
        return value


class MLCardSection(BaseModel):
    """Tarjeta CT-2 del challenger para model card, governance y report (SDD-12 §4/§9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"summary", "metric_sections"})

    summary: dict[str, str | int | float | bool]
    metric_sections: dict[str, Any] = Field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @field_validator("summary", mode="before")
    @classmethod
    def _normaliza_summary(cls, value: Any) -> Any:
        """Normaliza los floats del resumen preservando el orden de inserción."""
        if not isinstance(value, Mapping):
            return value
        return {str(key): _normalize_scalar_value(item) for key, item in value.items()}

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia profundamente la puerta CT-2 de métricas aditivas y normaliza sus floats."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(dict(value))
        return value

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias profundas de las estructuras mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class MLResult(BaseModel):
    """Contenedor agregado de los artefactos publicados por la capa ``ml`` (SDD-12 §4/§6)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset({"pd_frame", "calibrated_pd_frame"})

    estimator: NikodymClassifier
    pd_frame: DataFrameLike
    calibrated_pd_frame: DataFrameLike | None
    comparison: tuple[MLComparisonRecord, ...]
    backend_metadata: MLBackendMetadata
    card: MLCardSection

    @field_validator("pd_frame", mode="before")
    @classmethod
    def _copia_pd_frame(cls, value: Any) -> Any:
        """Copia defensivamente la PD del challenger y normaliza ``-0.0`` en sus columnas float."""
        if not _is_dataframe_like(value):
            raise ValueError("pd_frame debe ser un pandas.DataFrame.")
        return _copy_dataframe(value)

    @field_validator("calibrated_pd_frame", mode="before")
    @classmethod
    def _copia_calibrated_pd_frame(cls, value: Any) -> Any:
        """Copia la PD calibrada (formato SDD-10) o retorna ``None`` si no se calibró (§6)."""
        if value is None:
            return None
        if not _is_dataframe_like(value):
            raise ValueError("calibrated_pd_frame debe ser un pandas.DataFrame o None.")
        return _copy_dataframe(value)

    @model_validator(mode="after")
    def _check_comparison(self) -> Self:
        """Valida que la comparación no repita una brecha ``(partition, metric)`` (§6)."""
        keys = [(record.partition, record.metric) for record in self.comparison]
        if len(set(keys)) != len(keys):
            raise ValueError("comparison no puede repetir (partition, metric): una brecha por par.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de los DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value

    def term_structure(self) -> pd.DataFrame | None:
        """Retorna ``None``: el challenger ML no publica estructura temporal (CT-2, SDD-12 §9).

        A diferencia de IFRS 9/forward, ``ml`` produce una PD escalar por observación, no una curva
        multi-período; alimenta a ``report``/``governance`` por ``card`` + ``metric_sections``.
        """
        return None

    def comparison_frame(self) -> pd.DataFrame:
        """Materializa el tidy de :class:`MLComparisonRecord` (SDD-12 §6).

        Preserva el orden de los registros (el ``MLStep`` los produce en el orden de config de
        particiones y métricas). Importa ``pandas`` de forma perezosa para no romper el import
        liviano de ``nikodym.ml``.
        """
        import pandas as pd

        records = self.comparison
        return pd.DataFrame(
            {
                "partition": [record.partition for record in records],
                "metric": [record.metric for record in records],
                "champion_value": [record.champion_value for record in records],
                "challenger_value": [record.challenger_value for record in records],
                "delta": [record.delta for record in records],
                "better": [record.better for record in records],
                "source": [record.source for record in records],
            },
            columns=list(_COMPARISON_COLUMNS),
        )


def _coerce_pairs(value: Any) -> list[tuple[Any, Any]] | None:
    if isinstance(value, Mapping):
        return list(value.items())
    if not isinstance(value, (list, tuple)):
        return None
    pairs: list[tuple[Any, Any]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("cada entrada debe ser un par (feature, valor).")
        pairs.append((item[0], item[1]))
    return pairs


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))


def _copy_dataframe(frame: Any) -> Any:
    copied = frame.copy(deep=True)
    for column in copied.columns:
        series = copied[column]
        if getattr(series.dtype, "kind", "") != "f":
            continue
        zero_mask = (series == 0.0).fillna(False)
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _normalize_scalar_value(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, float):
        return value
    if not math.isfinite(value):
        raise ValueError("los valores float de resumen/hiperparámetros deben ser finitos.")
    return _normalize_float(value)


def _normalize_required_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("las métricas float deben ser números reales.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("las métricas float deben ser finitas (ni NaN ni inf).")
    return _normalize_float(candidate)


def _normalize_non_negative_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("las importancias deben ser números reales.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("las importancias no pueden ser NaN ni inf.")
    if candidate < 0.0:
        raise ValueError("las importancias nativas no pueden ser negativas.")
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
