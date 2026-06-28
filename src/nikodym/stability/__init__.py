"""Capa ``stability`` de Nikodym: estabilidad post-modelo (SDD-11).

Al importarse, registra :class:`StabilityConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.stability`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.stability`` ni dependencias tabulares/scoring.
Las excepciones se reexportan de forma perezosa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.stability.config import (
    CsiSource,
    ScoreDirection,
    StabilityComparison,
    StabilityConfig,
    TemporalAxis,
    TemporalFrequency,
)

# Registra la clase real del sub-config stability en el hook de `core`.
_schema._STABILITY_CONFIG_CLS = StabilityConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "StabilityDataError": ("nikodym.stability.exceptions", "StabilityDataError"),
    "StabilityError": ("nikodym.stability.exceptions", "StabilityError"),
    "StabilityMetricError": ("nikodym.stability.exceptions", "StabilityMetricError"),
}

__all__ = [
    "CsiSource",
    "ScoreDirection",
    "StabilityComparison",
    "StabilityConfig",
    "StabilityDataError",
    "StabilityError",
    "StabilityMetricError",
    "TemporalAxis",
    "TemporalFrequency",
]


def __getattr__(name: str) -> Any:
    """Carga componentes de stability bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.stability' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
