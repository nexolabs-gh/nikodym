"""Capa ``forward`` de Nikodym: forward-looking macro y PIT/TTC (SDD-20).

Al importarse, registra :class:`ForwardConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.forward`` se valida como sub-config real sin
que ``import nikodym.core`` arrastre ``nikodym.forward`` ni dependencias estadísticas opcionales.
Este paquete no importa statsmodels, pmdarima, pandas ni scipy en top-level; los motores concretos
llegarán en B20.3-B20.6 y cargarán sus dependencias dentro de ``fit``/``execute``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

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

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "FORWARD_ECL_CONTRACT_VERSION": ("nikodym.forward.results", "FORWARD_ECL_CONTRACT_VERSION"),
    "ForwardCard": ("nikodym.forward.results", "ForwardCard"),
    "ForwardDiagnostics": ("nikodym.forward.results", "ForwardDiagnostics"),
    "ForwardEclInput": ("nikodym.forward.results", "ForwardEclInput"),
    "ForwardResult": ("nikodym.forward.results", "ForwardResult"),
    "ForwardStep": ("nikodym.forward.step", "ForwardStep"),
    "MacroDiagnostics": ("nikodym.forward.results", "MacroDiagnostics"),
    "MacroProjectionResult": ("nikodym.forward.results", "MacroProjectionResult"),
    "SatelliteDiagnostics": ("nikodym.forward.results", "SatelliteDiagnostics"),
    "SatelliteResult": ("nikodym.forward.results", "SatelliteResult"),
    "ScenarioWeighting": ("nikodym.forward.scenarios", "ScenarioWeighting"),
    "ScenarioDiagnostics": ("nikodym.forward.results", "ScenarioDiagnostics"),
}

__all__ = [
    "FORWARD_ECL_CONTRACT_VERSION",
    "ForwardCard",
    "ForwardConfig",
    "ForwardConfigError",
    "ForwardDiagnostics",
    "ForwardEclInput",
    "ForwardError",
    "ForwardFitError",
    "ForwardInputConfig",
    "ForwardInputError",
    "ForwardPredictionError",
    "ForwardResult",
    "ForwardScenarioError",
    "ForwardStep",
    "ForwardValidationConfig",
    "MacroDiagnostics",
    "MacroModelConfig",
    "MacroModelKind",
    "MacroProjectionError",
    "MacroProjectionResult",
    "MacroSourceConfig",
    "MacroSourceType",
    "PdBasisAssumption",
    "PitConsistencyError",
    "SatelliteConfig",
    "SatelliteDiagnostics",
    "SatelliteMode",
    "SatelliteModelError",
    "SatelliteResult",
    "ScenarioConfig",
    "ScenarioDefinitionConfig",
    "ScenarioDiagnostics",
    "ScenarioWeighting",
    "TargetComponent",
    "TermStructureSource",
    "TtcAnchor",
    "TtcReversionConfig",
    "TtcReversionMethod",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="forward") al
# importar `nikodym.forward`, sin contaminar `import nikodym.core` ni cargar dependencias pesadas.
importlib.import_module("nikodym.forward.step")


def __getattr__(name: str) -> Any:
    """Carga DTOs forward bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.forward' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
