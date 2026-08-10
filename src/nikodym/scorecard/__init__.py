"""Capa ``scorecard`` de Nikodym: escalamiento log-odds a puntos (SDD-09).

Al importarse, registra :class:`ScorecardConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.scorecard`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.scorecard`` ni dependencias de scoring. El
paquete importa ``scorecard.step`` al final para ejecutar ``@register("standard",
domain="scorecard")`` sin arrastrar pandas/sklearn; los transformadores y DTOs tabulares se
reexportan de forma perezosa.

**Estable (SemVer 1.x).**
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
    ScorecardBundleError,
    ScorecardError,
    ScorecardFitError,
    ScorecardTransformError,
)

# Registra la clase real del sub-config scorecard en el hook de `core`.
_schema._SCORECARD_CONFIG_CLS = ScorecardConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "BatchApplicationResult": ("nikodym.scorecard.bundle", "BatchApplicationResult"),
    "FittedScorecardBundle": ("nikodym.scorecard.bundle", "FittedScorecardBundle"),
    "PointsScaler": ("nikodym.scorecard.scaler", "PointsScaler"),
    "ScorecardApplicationResult": (
        "nikodym.scorecard.bundle",
        "ScorecardApplicationResult",
    ),
    "Scorecard": ("nikodym.scorecard.transformer", "Scorecard"),
    "ScorecardBinPoint": ("nikodym.scorecard.results", "ScorecardBinPoint"),
    "ScorecardCardSection": ("nikodym.scorecard.results", "ScorecardCardSection"),
    "ScorecardResult": ("nikodym.scorecard.results", "ScorecardResult"),
    "ScorecardStep": ("nikodym.scorecard.step", "ScorecardStep"),
    "apply": ("nikodym.scorecard.bundle", "apply"),
    "fit_scorecard_bundle": ("nikodym.scorecard.bundle", "fit_scorecard_bundle"),
}

__all__ = [
    "BatchApplicationResult",
    "FittedScorecardBundle",
    "InterceptAllocation",
    "PointOverrideConfig",
    "PointsScaler",
    "RoundingMethod",
    "ScoreDirection",
    "Scorecard",
    "ScorecardApplicationResult",
    "ScorecardBinPoint",
    "ScorecardBundleError",
    "ScorecardCardSection",
    "ScorecardConfig",
    "ScorecardError",
    "ScorecardFitError",
    "ScorecardResult",
    "ScorecardStep",
    "ScorecardTransformError",
    "apply",
    "fit_scorecard_bundle",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="scorecard") al
# importar `nikodym.scorecard`, sin contaminar `import nikodym.core` ni cargar pandas/sklearn.
importlib.import_module("nikodym.scorecard.step")


def __getattr__(name: str) -> Any:
    """Carga componentes pesados de scorecard bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.scorecard' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
