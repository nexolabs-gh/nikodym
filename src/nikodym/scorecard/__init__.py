"""Capa ``scorecard`` de Nikodym: escalamiento log-odds a puntos (SDD-09).

Al importarse, registra :class:`ScorecardConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.scorecard`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.scorecard`` ni dependencias de scoring. La
lógica pesada de escalamiento y el ``ScorecardStep`` se añadirán en B9.2-B9.4 y se cargarán bajo
demanda; B9.1 solo cablea el config.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.scorecard.config import (
    InterceptAllocation,
    PointOverrideConfig,
    RoundingMethod,
    ScorecardConfig,
    ScoreDirection,
)
from nikodym.scorecard.exceptions import (
    ScorecardError,
    ScorecardFitError,
    ScorecardTransformError,
)

# Registra la clase real del sub-config scorecard en el hook de `core`.
_schema._SCORECARD_CONFIG_CLS = ScorecardConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "PointsScaler": ("nikodym.scorecard.scaler", "PointsScaler"),
    "Scorecard": ("nikodym.scorecard.transformer", "Scorecard"),
    "ScorecardBinPoint": ("nikodym.scorecard.results", "ScorecardBinPoint"),
    "ScorecardCardSection": ("nikodym.scorecard.results", "ScorecardCardSection"),
    "ScorecardResult": ("nikodym.scorecard.results", "ScorecardResult"),
}

__all__ = [
    "InterceptAllocation",
    "PointOverrideConfig",
    "PointsScaler",
    "RoundingMethod",
    "ScoreDirection",
    "Scorecard",
    "ScorecardBinPoint",
    "ScorecardCardSection",
    "ScorecardConfig",
    "ScorecardError",
    "ScorecardFitError",
    "ScorecardResult",
    "ScorecardTransformError",
]


def __getattr__(name: str) -> Any:
    """Carga componentes pesados de scorecard bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.scorecard' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
