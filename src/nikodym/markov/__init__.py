"""Capa ``markov`` de Nikodym: migración de estados y PD lifetime (SDD-19).

Al importarse, registra :class:`MarkovConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.markov`` se valida como sub-config real sin
que ``import nikodym.core`` arrastre ``nikodym.markov`` ni dependencias numéricas opcionales. Este
paquete no importa scipy, numpy ni pandas en top-level; los motores concretos llegarán en B19.2+
y cargarán sus dependencias dentro de ``fit``/``execute``.

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
    "MarkovStep": ("nikodym.markov.step", "MarkovStep"),
    "TransitionMatrixEstimator": (
        "nikodym.markov.transition",
        "TransitionMatrixEstimator",
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
]


def __getattr__(name: str) -> Any:
    """Carga estimadores Markov bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.markov' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
