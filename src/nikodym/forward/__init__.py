"""Capa ``forward`` de Nikodym: forward-looking macro y PIT/TTC (SDD-20).

Al importarse, registra :class:`ForwardConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.forward`` se valida como sub-config real sin
que ``import nikodym.core`` arrastre ``nikodym.forward`` ni dependencias estadísticas opcionales.
Este paquete no importa statsmodels, pmdarima, pandas ni scipy en top-level; los motores concretos
llegarán en B20.3-B20.6 y cargarán sus dependencias dentro de ``fit``/``execute``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from nikodym.core.config import schema as _schema
from nikodym.forward.config import (
    ForwardConfig,
    ForwardInputConfig,
    ForwardValidationConfig,
    MacroModelConfig,
    MacroModelKind,
    MacroSourceConfig,
    MacroSourceType,
    PdBasisAssumption,
    SatelliteConfig,
    SatelliteMode,
    ScenarioConfig,
    ScenarioDefinitionConfig,
    TargetComponent,
    TermStructureSource,
    TtcAnchor,
    TtcReversionConfig,
    TtcReversionMethod,
)
from nikodym.forward.exceptions import (
    ForwardConfigError,
    ForwardError,
    ForwardFitError,
    ForwardInputError,
    ForwardPredictionError,
    ForwardScenarioError,
    MacroProjectionError,
    PitConsistencyError,
    SatelliteModelError,
)

# Registra la clase real del sub-config forward en el hook de `core`.
_schema._FORWARD_CONFIG_CLS = ForwardConfig

__all__ = [
    "ForwardConfig",
    "ForwardConfigError",
    "ForwardError",
    "ForwardFitError",
    "ForwardInputConfig",
    "ForwardInputError",
    "ForwardPredictionError",
    "ForwardScenarioError",
    "ForwardValidationConfig",
    "MacroModelConfig",
    "MacroModelKind",
    "MacroProjectionError",
    "MacroSourceConfig",
    "MacroSourceType",
    "PdBasisAssumption",
    "PitConsistencyError",
    "SatelliteConfig",
    "SatelliteMode",
    "SatelliteModelError",
    "ScenarioConfig",
    "ScenarioDefinitionConfig",
    "TargetComponent",
    "TermStructureSource",
    "TtcAnchor",
    "TtcReversionConfig",
    "TtcReversionMethod",
]
