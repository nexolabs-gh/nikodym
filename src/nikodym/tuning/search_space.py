"""Espacio de búsqueda tipado de hiperparámetros para el tuning con Optuna (SDD-13 §4/§5).

El espacio de búsqueda es una **estructura Pydantic tipada y discriminada por ``kind``**, nunca un
``dict[str, Any]`` ni una expresión ejecutable de usuario: cada hiperparámetro declara su
distribución (:class:`IntSpec`, :class:`FloatSpec` o :class:`CategoricalSpec`) y sus rangos. La
traducción a las llamadas ``trial.suggest_*`` de Optuna (:func:`suggest_params`) se hace por
**duck-typing** sobre un objeto tipo *trial* (:class:`SuggestTrial`): **sin ``eval``** y **sin
importar optuna** (el estudio real vive en ``optimizer.py``, B13.3, con import perezoso).

Núcleo liviano (principio 9): ``import nikodym.tuning.search_space`` **no** arrastra optuna,
sklearn, pandas, numpy ni los backends ML; solo depende del config base
(:class:`NikodymBaseConfig`) y de las excepciones. La referencia al backend (``MLBackendName``,
SDD-12 §5) es un ``TYPE_CHECKING`` puro; el cross-check de que cada clave del espacio sea un campo
válido del params-model del backend lo hace el config (B13.4), no este módulo.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.tuning.exceptions import TuningSearchSpaceError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nikodym.ml.config import MLBackendName

__all__ = [
    "CategoricalSpec",
    "FloatSpec",
    "IntSpec",
    "ParamSpec",
    "SearchSpaceConfig",
    "SuggestTrial",
    "default_search_space",
    "suggest_params",
]


class IntSpec(NikodymBaseConfig):
    """Distribución entera ``low..high`` (opcionalmente logarítmica) para un hiperparámetro."""

    kind: Literal["int"] = "int"
    low: int
    high: int
    log: bool = False
    step: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _valida_rango(self) -> Self:
        """Valida el rango entero (``low<high``, ``log`` positivo y coherente con ``step``)."""
        if self.low >= self.high:
            raise TuningSearchSpaceError(
                f"IntSpec exige low < high, pero low={self.low} y high={self.high}."
            )
        if self.log and self.low <= 0:
            raise TuningSearchSpaceError(
                f"IntSpec con log=True exige low > 0 (dominio logarítmico), pero low={self.low}."
            )
        if self.log and self.step != 1:
            raise TuningSearchSpaceError(
                "IntSpec con log=True exige step=1 (Optuna prohíbe step≠1 en escala logarítmica), "
                f"pero step={self.step}."
            )
        return self


class FloatSpec(NikodymBaseConfig):
    """Distribución real ``low..high`` (opcionalmente logarítmica) para un hiperparámetro."""

    kind: Literal["float"] = "float"
    low: float
    high: float
    log: bool = False

    @model_validator(mode="after")
    def _valida_rango(self) -> Self:
        """Valida el rango real: ``low < high`` y, si ``log``, ``low > 0`` (dominio logarítmico)."""
        if self.low >= self.high:
            raise TuningSearchSpaceError(
                f"FloatSpec exige low < high, pero low={self.low} y high={self.high}."
            )
        if self.log and self.low <= 0.0:
            raise TuningSearchSpaceError(
                f"FloatSpec con log=True exige low > 0 (dominio logarítmico), pero low={self.low}."
            )
        return self


class CategoricalSpec(NikodymBaseConfig):
    """Elección categórica entre ``choices`` (lista no vacía y homogénea de tipos simples)."""

    kind: Literal["categorical"] = "categorical"
    choices: tuple[str | int | float | bool, ...]

    @model_validator(mode="after")
    def _valida_choices(self) -> Self:
        """Valida que ``choices`` sea no vacío y homogéneo en el tipo simple de sus elementos."""
        if not self.choices:
            raise TuningSearchSpaceError("CategoricalSpec exige choices no vacío.")
        tipos = {type(choice) for choice in self.choices}
        if len(tipos) != 1:
            nombres = sorted(tipo.__name__ for tipo in tipos)
            raise TuningSearchSpaceError(
                f"CategoricalSpec exige choices homogéneo, pero mezcla los tipos {nombres}."
            )
        return self


# Unión discriminada por ``kind`` (factory nativo de Pydantic v2; sin `Field(strict=...)` sobre la
# unión, SDD-05 §3). ``ParamSpec`` nombra la distribución de un único hiperparámetro.
ParamSpec = Annotated[IntSpec | FloatSpec | CategoricalSpec, Field(discriminator="kind")]


class SearchSpaceConfig(NikodymBaseConfig):
    """Mapa hiperparámetro → distribución de búsqueda (SDD-13 §4/§5).

    ``params`` vacío ⇒ el config resuelve el espacio por defecto del backend de ``ml`` vía
    :func:`default_search_space` (B13.4). Las claves deben ser campos del params-model del backend;
    ese cross-check lo hace el config, no este schema.
    """

    params: dict[str, ParamSpec] = Field(default_factory=dict)


class SuggestTrial(Protocol):
    """Objeto tipo *trial* de Optuna: expone los métodos ``suggest_*`` (sin importar optuna)."""

    def suggest_int(
        self, name: str, low: int, high: int, *, step: int = ..., log: bool = ...
    ) -> int:
        """Sugiere un entero en ``[low, high]`` (opcional ``step``/``log``)."""
        ...

    def suggest_float(self, name: str, low: float, high: float, *, log: bool = ...) -> float:
        """Sugiere un real en ``[low, high]`` (opcional ``log``)."""
        ...

    def suggest_categorical(self, name: str, choices: Sequence[Any]) -> Any:
        """Sugiere un valor entre ``choices``."""
        ...


def default_search_space(backend: MLBackendName) -> SearchSpaceConfig:
    """Devuelve el espacio de búsqueda por defecto del ``backend`` (D-TUN-space, SDD-13 §5).

    Los rangos son conservadores, alrededor de los defaults D-ML-9 del challenger (SDD-12 §5). En
    los backends GBDT (``xgboost``/``lightgbm``/``catboost``) se **excluye** el número de árboles
    (``n_estimators``/``iterations``) del espacio por defecto: es redundante con el early-stopping,
    que ya recorta las rondas efectivas (nitpick A14(3)). ``random_forest`` **sí** lo tunea, porque
    no tiene early-stopping. Un ``backend`` desconocido levanta :class:`TuningSearchSpaceError`.
    """
    params: dict[str, ParamSpec]
    if backend == "svm":
        params = {
            "C": FloatSpec(low=1e-2, high=1e2, log=True),
            "kernel": CategoricalSpec(choices=("rbf", "linear")),
            "gamma": CategoricalSpec(choices=("scale", "auto")),
        }
    elif backend == "random_forest":
        params = {
            "n_estimators": IntSpec(low=100, high=1000),
            "max_depth": IntSpec(low=2, high=16),
            "min_samples_leaf": IntSpec(low=10, high=200, log=True),
            "max_features": CategoricalSpec(choices=("sqrt", "log2")),
        }
    elif backend == "xgboost":
        params = {
            "max_depth": IntSpec(low=2, high=8),
            "learning_rate": FloatSpec(low=1e-2, high=0.3, log=True),
            "subsample": FloatSpec(low=0.6, high=1.0),
            "colsample_bytree": FloatSpec(low=0.6, high=1.0),
            "reg_lambda": FloatSpec(low=1e-3, high=1e1, log=True),
            "min_child_weight": FloatSpec(low=0.0, high=10.0),
        }
    elif backend == "lightgbm":
        params = {
            "num_leaves": IntSpec(low=15, high=255, log=True),
            "learning_rate": FloatSpec(low=1e-2, high=0.3, log=True),
            "subsample": FloatSpec(low=0.6, high=1.0),
            "colsample_bytree": FloatSpec(low=0.6, high=1.0),
            "reg_lambda": FloatSpec(low=1e-3, high=1e1, log=True),
            "min_child_samples": IntSpec(low=10, high=200, log=True),
        }
    elif backend == "catboost":
        params = {
            "depth": IntSpec(low=2, high=10),
            "learning_rate": FloatSpec(low=1e-2, high=0.3, log=True),
            "l2_leaf_reg": FloatSpec(low=1.0, high=1e1, log=True),
        }
    else:
        raise TuningSearchSpaceError(
            f"no hay espacio de búsqueda por defecto para el backend '{backend}'; "
            "backends soportados: catboost, lightgbm, random_forest, svm, xgboost."
        )
    return SearchSpaceConfig(params=params)


def suggest_params(trial: SuggestTrial, space: SearchSpaceConfig) -> dict[str, Any]:
    """Traduce cada spec del espacio a su llamada ``trial.suggest_*`` (SDD-13 §7.10a).

    Recorre ``space.params`` en orden de inserción y, por cada ``(nombre, spec)``, llama al método
    ``suggest_int``/``suggest_float``/``suggest_categorical`` del ``trial`` según su ``kind``. No
    usa ``eval`` ni importa optuna: ``trial`` es cualquier objeto que exponga esos métodos
    (:class:`SuggestTrial`). Devuelve el ``dict`` de hiperparámetros sugeridos.
    """
    params: dict[str, Any] = {}
    for name, spec in space.params.items():
        if spec.kind == "int":
            params[name] = trial.suggest_int(
                name, spec.low, spec.high, step=spec.step, log=spec.log
            )
        elif spec.kind == "float":
            params[name] = trial.suggest_float(name, spec.low, spec.high, log=spec.log)
        else:
            params[name] = trial.suggest_categorical(name, list(spec.choices))
    return params
