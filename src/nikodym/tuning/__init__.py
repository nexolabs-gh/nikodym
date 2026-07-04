"""Capa ``tuning`` de Nikodym: búsqueda de hiperparámetros con Optuna (SDD-13).

Este ``__init__`` es **liviano**: reexporta la jerarquía de excepciones, las *specs* del espacio de
búsqueda y el config declarativo (:class:`TuningConfig`), y **puebla el hook diferido**
``_TUNING_CONFIG_CLS`` en :class:`~nikodym.core.config.NikodymConfig` para que la sección ``tuning``
se valide como sub-config real, **sin** arrastrar ``optuna``/``pandas``/``numpy`` ni backends ML.
Los DTOs de resultados (:mod:`nikodym.tuning.results`) se reexportan de forma **perezosa** (vía
``__getattr__``) porque anotan ``MLConfig``/``MLChallenger`` y usan ``pandas``: cargarlos traería
``nikodym.ml``, que se difiere hasta que el usuario los pida. Al final se importa ``tuning.step``
para ejecutar ``@register('standard', domain='tuning')`` **sin** arrastrar optuna/pandas/numpy ni
los backends ML (el step los carga perezosamente dentro de ``execute``; patrón idéntico a
``ml.__init__``). Nomenclatura en inglés técnico para APIs; docstrings y errores en español.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.tuning.config import (
    TuningConfig,
    TuningMetric,
    TuningObjectiveConfig,
    TuningPruner,
    TuningSampler,
    TuningSamplerConfig,
    TuningValidationConfig,
    ValidationStrategy,
)
from nikodym.tuning.exceptions import (
    TuningConfigError,
    TuningDataError,
    TuningDeterminismError,
    TuningError,
    TuningOptimizeError,
    TuningSearchSpaceError,
)
from nikodym.tuning.search_space import (
    CategoricalSpec,
    FloatSpec,
    IntSpec,
    ParamSpec,
    SearchSpaceConfig,
    SuggestTrial,
    default_search_space,
    suggest_params,
)

# Registra la clase real del sub-config tuning en el hook de `core` (sin importar optuna/backends).
_schema._TUNING_CONFIG_CLS = TuningConfig

# Reexports perezosos: los DTOs de resultados anotan `MLConfig`/`MLChallenger`/`pandas`; cargarlos
# arrastraría `nikodym.ml`, así que se difieren hasta el primer acceso (import liviano).
_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "SamplerMetadata": ("nikodym.tuning.results", "SamplerMetadata"),
    "TuningCardSection": ("nikodym.tuning.results", "TuningCardSection"),
    "TuningOptimizer": ("nikodym.tuning.optimizer", "TuningOptimizer"),
    "TuningResult": ("nikodym.tuning.results", "TuningResult"),
    "TuningStep": ("nikodym.tuning.step", "TuningStep"),
    "TuningTrialRecord": ("nikodym.tuning.results", "TuningTrialRecord"),
}

__all__ = [
    "CategoricalSpec",
    "FloatSpec",
    "IntSpec",
    "ParamSpec",
    "SamplerMetadata",
    "SearchSpaceConfig",
    "SuggestTrial",
    "TuningCardSection",
    "TuningConfig",
    "TuningConfigError",
    "TuningDataError",
    "TuningDeterminismError",
    "TuningError",
    "TuningMetric",
    "TuningObjectiveConfig",
    "TuningOptimizeError",
    "TuningOptimizer",
    "TuningPruner",
    "TuningResult",
    "TuningSampler",
    "TuningSamplerConfig",
    "TuningSearchSpaceError",
    "TuningStep",
    "TuningTrialRecord",
    "TuningValidationConfig",
    "ValidationStrategy",
    "default_search_space",
    "suggest_params",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="tuning") al importar
# `nikodym.tuning`, sin arrastrar optuna/pandas/numpy ni los backends ML (el step los carga en
# `execute`; mismo patrón que `nikodym.ml.__init__`).
importlib.import_module("nikodym.tuning.step")


def __getattr__(name: str) -> Any:
    """Carga los DTOs de resultados bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.tuning' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
