"""Capa ``tuning`` de Nikodym: búsqueda de hiperparámetros con Optuna (SDD-13).

Este ``__init__`` es **liviano**: reexporta la jerarquía de excepciones y las *specs* del espacio de
búsqueda, sin arrastrar ``optuna``/``pandas``/``numpy`` ni los backends ML (import perezoso en
bloques posteriores B13.3+). El cableado del ``TuningStep`` y el poblado del hook
``_TUNING_CONFIG_CLS`` en :class:`~nikodym.core.config.NikodymConfig` se difieren a B13.4.
Nomenclatura en inglés técnico para APIs; docstrings y errores en español.

**Experimental (SemVer 0.x).**
"""

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

__all__ = [
    "CategoricalSpec",
    "FloatSpec",
    "IntSpec",
    "ParamSpec",
    "SearchSpaceConfig",
    "SuggestTrial",
    "TuningConfigError",
    "TuningDataError",
    "TuningDeterminismError",
    "TuningError",
    "TuningOptimizeError",
    "TuningSearchSpaceError",
    "default_search_space",
    "suggest_params",
]
