"""Capa ``markov`` de Nikodym: migración de estados y PD lifetime (SDD-19).

Al importarse, registra :class:`MarkovConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.markov`` se valida como sub-config real sin
que ``import nikodym.core`` arrastre ``nikodym.markov`` ni dependencias numéricas opcionales. Este
paquete no importa scipy ni pandas en top-level; los motores concretos cargan sus dependencias
dentro de ``fit``/``execute``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.markov.config import (
    EmbeddingPolicy,
    MarkovConfig,
    MarkovDynamicsConfig,
    MarkovEstimationConfig,
    MarkovInputConfig,
    MarkovMethod,
    MarkovStateConfig,
    MarkovValidationConfig,
    ProjectionMode,
)
from nikodym.markov.exceptions import (
    InvalidGeneratorError,
    MarkovConfigError,
    MarkovEmbeddingError,
    MarkovError,
    MarkovFitError,
    MarkovInputError,
    MarkovTransformError,
    NonStochasticMatrixError,
)

# Registra la clase real del sub-config markov en el hook de `core`.
_schema._MARKOV_CONFIG_CLS = MarkovConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "aalen_johansen": ("nikodym.markov.term_structure", "aalen_johansen"),
    "chapman_kolmogorov": ("nikodym.markov.term_structure", "chapman_kolmogorov"),
    "diagnose_embedding": ("nikodym.markov.term_structure", "diagnose_embedding"),
    "markov_term_structure": ("nikodym.markov.term_structure", "markov_term_structure"),
    "MarkovStep": ("nikodym.markov.step", "MarkovStep"),
    "TransitionMatrixEstimator": (
        "nikodym.markov.transition",
        "TransitionMatrixEstimator",
    ),
    "validate_generator": ("nikodym.markov.term_structure", "validate_generator"),
    "validate_transition_matrix": (
        "nikodym.markov.term_structure",
        "validate_transition_matrix",
    ),
}

__all__ = [
    "EmbeddingPolicy",
    "InvalidGeneratorError",
    "MarkovConfig",
    "MarkovConfigError",
    "MarkovDynamicsConfig",
    "MarkovEmbeddingError",
    "MarkovError",
    "MarkovEstimationConfig",
    "MarkovFitError",
    "MarkovInputConfig",
    "MarkovInputError",
    "MarkovMethod",
    "MarkovStateConfig",
    "MarkovStep",
    "MarkovTransformError",
    "MarkovValidationConfig",
    "NonStochasticMatrixError",
    "ProjectionMode",
    "TransitionMatrixEstimator",
    "aalen_johansen",
    "chapman_kolmogorov",
    "diagnose_embedding",
    "markov_term_structure",
    "validate_generator",
    "validate_transition_matrix",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="markov") al importar
# `nikodym.markov`, sin contaminar `import nikodym.core` ni cargar pandas/scipy.
importlib.import_module("nikodym.markov.step")


def __getattr__(name: str) -> Any:
    """Carga estimadores Markov bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.markov' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
