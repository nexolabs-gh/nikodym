"""Capa ``performance`` de Nikodym: desempeño post-modelo (SDD-11).

Al importarse, registra :class:`PerformanceConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.performance`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.performance`` ni dependencias de scoring.

**Experimental (SemVer 0.x).**
"""

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

__all__ = [
    "EvaluationSource",
    "PerformanceConfig",
    "PerformanceDataError",
    "PerformanceError",
    "PerformanceMetricError",
    "PerformancePartition",
    "ScoreDirection",
]
