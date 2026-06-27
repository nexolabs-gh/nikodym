"""Capa ``binning`` de Nikodym: binning supervisado óptimo, WoE e IV (SDD-06).

Al importarse, registra :class:`BinningConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.binning`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.binning`` ni dependencias de scoring.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.binning.config import BinningConfig, MonotonicTrend, VariableBinningConfig
from nikodym.binning.exceptions import BinningError, BinningFitError, BinningTransformError
from nikodym.core.config import schema as _schema

# Registra la clase real del sub-config binning en el hook de `core`.
_schema._BINNING_CONFIG_CLS = BinningConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "BinningCardSection": ("nikodym.binning.results", "BinningCardSection"),
    "BinningResult": ("nikodym.binning.results", "BinningResult"),
    "BinningVariableSummary": ("nikodym.binning.results", "BinningVariableSummary"),
    "WoEBinner": ("nikodym.binning.transformer", "WoEBinner"),
    "iv_band": ("nikodym.binning.results", "iv_band"),
}

__all__ = [
    "BinningCardSection",
    "BinningConfig",
    "BinningError",
    "BinningFitError",
    "BinningResult",
    "BinningTransformError",
    "BinningVariableSummary",
    "MonotonicTrend",
    "VariableBinningConfig",
    "WoEBinner",
    "iv_band",
]


def __getattr__(name: str) -> Any:
    """Carga componentes pesados de binning bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.binning' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
