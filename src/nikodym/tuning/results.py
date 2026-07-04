"""DTOs puros del resultado de la búsqueda de hiperparámetros (SDD-13 §4/§6).

Este módulo publica los contenedores Pydantic *frozen* que la capa ``tuning`` expone a
``ml``/``report``/``governance``: el historial de trials, la metadata del sampler, la tarjeta CT-2 y
el resultado agregado con los hiperparámetros ganadores. **No** corre el estudio Optuna, **no**
importa ``optuna`` y **no** importa ``pandas``/``numpy``/``sklearn`` ni los backends ML en runtime:
``pandas`` vive solo bajo ``TYPE_CHECKING`` y se importa perezosamente dentro de
:meth:`TuningResult.trials_frame`. El ``__init__`` de ``nikodym.tuning`` lo reexporta de forma
**perezosa**, de modo que ``import nikodym.tuning`` no arrastre este módulo (ni ``nikodym.ml``).

Forward-ref del campo ``best_estimator``: el §4 lo anota como ``MLChallenger | None`` (subclase que
crea B12.4). Como el proyecto prohíbe ``model_rebuild()`` (Pydantic 2.x), el campo se tipa con su
clase base concreta ya disponible, :class:`~nikodym.core.base.NikodymClassifier`, y
``arbitrary_types_allowed=True``; en runtime el objeto validado es un ``MLChallenger`` (subclase de
``NikodymClassifier``, luego pasa el ``isinstance`` de Pydantic sin acoplar este módulo a B12.4).

Cumplimiento CT-2: la puerta de extensión es ``TuningCardSection.metric_sections`` (aditiva, copiada
a la lectura: curva de optimización + trials + importancias); :meth:`TuningResult.term_structure`
retorna **siempre** ``None`` (``tuning`` no es multi-período, a diferencia de IFRS 9/forward). Orden
estable (§6/§9): ``param_importances`` desc por valor con desempate lexicográfico; ``trials`` en el
orden de ejecución (número ascendente). Los floats normalizan ``-0.0`` como ``0.0`` y **jamás**
publican ``NaN``/``inf`` (fallan explícito o, en ``metric_sections``, degradan a ``None``).

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nikodym.core.base import NikodymClassifier
from nikodym.ml.config import (
    CatBoostParams,
    LightGBMParams,
    MLConfig,
    RandomForestParams,
    SvmParams,
    XGBoostParams,
)

if TYPE_CHECKING:
    import pandas as pd

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any

TrialState: TypeAlias = Literal["complete", "pruned", "fail"]
# Unión de hiperparámetros tipados por backend (== ``MLConfig.hyperparameters`` sin ``None``).
BackendParams: TypeAlias = (
    SvmParams | RandomForestParams | XGBoostParams | LightGBMParams | CatBoostParams
)

__all__ = [
    "SamplerMetadata",
    "TuningCardSection",
    "TuningResult",
    "TuningTrialRecord",
]


class TuningTrialRecord(BaseModel):
    """Registro de un trial del estudio: número, hiperparámetros, valor y estado (SDD-13 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int = Field(ge=0)
    params: dict[str, str | int | float | bool]
    value: float | None
    state: TrialState

    @field_validator("params", mode="before")
    @classmethod
    def _normaliza_params(cls, value: Any) -> Any:
        """Normaliza los floats de los hiperparámetros preservando el orden de sugerencia."""
        if not isinstance(value, Mapping):
            return value
        return {str(key): _normalize_scalar_value(item) for key, item in value.items()}

    @field_validator("value", mode="before")
    @classmethod
    def _normaliza_value(cls, value: Any) -> Any:
        """Exige valor finito (``-0.0``→``0.0``) o ``None`` para trials podados/fallidos."""
        if value is None:
            return None
        return _normalize_required_float(value)


class SamplerMetadata(BaseModel):
    """Metadata reproducible del sampler y del estudio Optuna (SDD-13 §4/§9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sampler: str
    pruner: str
    seed: int = Field(ge=0)
    n_trials_requested: int = Field(ge=1)
    n_trials_complete: int = Field(ge=0)
    optuna_version: str
    direction: Literal["maximize", "minimize"]
    metric: Literal["auc", "gini", "ks"]
    deterministic: bool

    @field_validator("sampler", "pruner", "optuna_version")
    @classmethod
    def _valida_texto(cls, value: str) -> str:
        """Valida que el sampler, el pruner y la versión de optuna no estén vacíos."""
        if not value.strip():
            raise ValueError("sampler, pruner y optuna_version no pueden estar vacíos.")
        return value


class TuningCardSection(BaseModel):
    """Tarjeta CT-2 del tuning para model card, governance y report (SDD-13 §4/§9)."""

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


class TuningResult(BaseModel):
    """Contenedor agregado de los artefactos publicados por la capa ``tuning`` (SDD-13 §4/§6)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    best_hyperparameters: BackendParams
    best_config: MLConfig
    best_estimator: NikodymClassifier | None
    best_value: float
    trials: tuple[TuningTrialRecord, ...]
    param_importances: tuple[tuple[str, float], ...]
    sampler_metadata: SamplerMetadata
    card: TuningCardSection

    @field_validator("best_value", mode="before")
    @classmethod
    def _normaliza_best_value(cls, value: Any) -> float:
        """Exige que el mejor valor objetivo sea finito (``-0.0``→``0.0``)."""
        return _normalize_required_float(value)

    @field_validator("param_importances", mode="before")
    @classmethod
    def _ordena_importances(cls, value: Any) -> Any:
        """Normaliza y ordena las importancias desc por valor, desempate por nombre (§6)."""
        items = _coerce_pairs(value)
        if items is None:
            return value
        seen: set[str] = set()
        pairs: list[tuple[str, float]] = []
        for name, raw in items:
            key = str(name)
            if key in seen:
                raise ValueError(f"param_importances no puede repetir el hiperparámetro '{key}'.")
            seen.add(key)
            pairs.append((key, _normalize_non_negative_float(raw)))
        pairs.sort(key=lambda pair: (-pair[1], pair[0]))
        return tuple(pairs)

    def term_structure(self) -> pd.DataFrame | None:
        """Retorna ``None``: el tuning no publica estructura temporal (CT-2, SDD-13 §9).

        A diferencia de IFRS 9/forward, ``tuning`` produce hiperparámetros escalares y una curva de
        optimización, no una curva multi-período; alimenta a ``report``/``governance`` por
        ``card`` + ``metric_sections``.
        """
        return None

    def trials_frame(self) -> pd.DataFrame:
        """Materializa el tidy de :class:`TuningTrialRecord` (SDD-13 §6).

        Columnas ``number``, ``param_<hiperparámetro>`` (unión estable en orden de aparición),
        ``value`` y ``state``, en el orden de ejecución de los trials. Importa ``pandas`` de forma
        perezosa para no romper el import liviano de ``nikodym.tuning``.
        """
        import pandas as pd

        trials = self.trials
        param_names: list[str] = []
        seen: set[str] = set()
        for trial in trials:
            for name in trial.params:
                if name not in seen:
                    seen.add(name)
                    param_names.append(name)
        data: dict[str, list[Any]] = {"number": [trial.number for trial in trials]}
        for name in param_names:
            data[f"param_{name}"] = [trial.params.get(name) for trial in trials]
        data["value"] = [trial.value for trial in trials]
        data["state"] = [trial.state for trial in trials]
        columns = ["number", *(f"param_{name}" for name in param_names), "value", "state"]
        return pd.DataFrame(data, columns=columns)


def _coerce_pairs(value: Any) -> list[tuple[Any, Any]] | None:
    if isinstance(value, Mapping):
        return list(value.items())
    if not isinstance(value, (list, tuple)):
        return None
    pairs: list[tuple[Any, Any]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("cada entrada debe ser un par (hiperparámetro, valor).")
        pairs.append((item[0], item[1]))
    return pairs


def _normalize_scalar_value(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, float):
        return value
    if not math.isfinite(value):
        raise ValueError("los valores float de resumen/hiperparámetros deben ser finitos.")
    return _normalize_float(value)


def _normalize_required_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("los valores objetivo deben ser números reales.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("los valores objetivo deben ser finitos (ni NaN ni inf).")
    return _normalize_float(candidate)


def _normalize_non_negative_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("las importancias deben ser números reales.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("las importancias no pueden ser NaN ni inf.")
    if candidate < 0.0:
        raise ValueError("las importancias de hiperparámetros no pueden ser negativas.")
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
