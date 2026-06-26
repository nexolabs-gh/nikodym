"""Capa ``eda`` de Nikodym: diagnóstico exploratorio orientado a riesgo (SDD-27).

Al importarse, registra :class:`EdaConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.eda`` se valida como sub-config real sin que
``import nikodym.core`` arrastre ``nikodym.eda`` ni dependencias tabulares. Los analizadores se
exponen de forma perezosa para que ``import nikodym.eda`` tampoco importe pandas hasta que el
usuario pida un analizador concreto.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final

from nikodym.core.config import schema as _schema
from nikodym.eda.config import (
    DefaultRateConfig,
    EdaConfig,
    QualityConfig,
    SamplingConfig,
    TemporalStabilityConfig,
    UnivariateConfig,
)
from nikodym.eda.exceptions import EdaError

if TYPE_CHECKING:
    from nikodym.eda.default_rate import DefaultRateAnalyzer, DefaultRateResult
    from nikodym.eda.quality import DataQualityProfiler, QualityResult
    from nikodym.eda.stability import StabilityResult, TemporalStabilityAnalyzer
    from nikodym.eda.univariate import UnivariateProfiler, UnivariateResult

# Registra la clase real del sub-config EDA en el hook de `core`.
_schema._EDA_CONFIG_CLS = EdaConfig

_LAZY_EXPORTS: Final = {
    "DefaultRateAnalyzer": ("nikodym.eda.default_rate", "DefaultRateAnalyzer"),
    "DefaultRateResult": ("nikodym.eda.default_rate", "DefaultRateResult"),
    "DataQualityProfiler": ("nikodym.eda.quality", "DataQualityProfiler"),
    "QualityResult": ("nikodym.eda.quality", "QualityResult"),
    "StabilityResult": ("nikodym.eda.stability", "StabilityResult"),
    "TemporalStabilityAnalyzer": ("nikodym.eda.stability", "TemporalStabilityAnalyzer"),
    "UnivariateProfiler": ("nikodym.eda.univariate", "UnivariateProfiler"),
    "UnivariateResult": ("nikodym.eda.univariate", "UnivariateResult"),
}

__all__ = [
    "DataQualityProfiler",
    "DefaultRateAnalyzer",
    "DefaultRateConfig",
    "DefaultRateResult",
    "EdaConfig",
    "EdaError",
    "QualityConfig",
    "QualityResult",
    "SamplingConfig",
    "StabilityResult",
    "TemporalStabilityAnalyzer",
    "TemporalStabilityConfig",
    "UnivariateConfig",
    "UnivariateProfiler",
    "UnivariateResult",
]


def __getattr__(name: str) -> Any:
    """Carga analizadores EDA bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.eda' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
