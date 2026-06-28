"""Capa ``performance`` de Nikodym: desempeño post-modelo (SDD-11).

Al importarse, registra :class:`PerformanceConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.performance`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.performance`` ni dependencias de scoring.
Los DTOs tabulares se reexportan de forma perezosa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.performance.config import (
    EvaluationSource,
    PerformanceConfig,
    PerformancePartition,
    ScoreDirection,
)
from nikodym.performance.exceptions import (
    PerformanceDataError,
    PerformanceError,
    PerformanceMetricError,
)

# Registra la clase real del sub-config performance en el hook de `core`.
_schema._PERFORMANCE_CONFIG_CLS = PerformanceConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "DecilePerformanceRecord": ("nikodym.performance.results", "DecilePerformanceRecord"),
    "DiscriminantMetricRecord": ("nikodym.performance.results", "DiscriminantMetricRecord"),
    "PerformanceCardSection": ("nikodym.performance.results", "PerformanceCardSection"),
    "PerformanceResult": ("nikodym.performance.results", "PerformanceResult"),
}

__all__ = [
    "DecilePerformanceRecord",
    "DiscriminantMetricRecord",
    "EvaluationSource",
    "PerformanceCardSection",
    "PerformanceConfig",
    "PerformanceDataError",
    "PerformanceError",
    "PerformanceMetricError",
    "PerformancePartition",
    "PerformanceResult",
    "ScoreDirection",
]


def __getattr__(name: str) -> Any:
    """Carga DTOs de performance bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.performance' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
