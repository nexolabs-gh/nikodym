"""Capa ``stress`` de Nikodym: stress testing, sensibilidad y reverse stress (SDD-21).

Al importarse, registra :class:`StressConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.stress`` se valida como sub-config real sin
que ``import nikodym.core`` importe ``nikodym.stress`` ni motores económicos futuros. En B21.2 los
DTOs de resultados se exportan bajo demanda para no arrastrar ``pandas`` ni engines.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.stress.config import (
    ReverseStressConfig,
    SensitivitySweepConfig,
    StressConfig,
    StressDirection,
    StressInputConfig,
    StressMetric,
    StressOperation,
    StressOutputConfig,
    StressScenarioConfig,
    StressShockConfig,
    StressTargetConfig,
    StressValidationConfig,
)
from nikodym.stress.exceptions import (
    NonMonotonicStressError,
    ReverseStressError,
    StressConfigError,
    StressDependencyError,
    StressEngineError,
    StressError,
    StressFaltaDatoError,
    StressInputError,
    StressOutputError,
    StressScenarioError,
)

# Registra la clase real del sub-config stress en el hook de `core`.
_schema._STRESS_CONFIG_CLS = StressConfig

# Exports perezosos: DTOs de resultados, engine y el paso orquestable. El módulo destino se importa
# sólo al acceder al nombre, para no arrastrar `pandas`/engines al importar `nikodym.stress`.
_RESULT_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "EclEngineLike": ("nikodym.stress.engine", "EclEngineLike"),
    "ProvisionEngineLike": ("nikodym.stress.engine", "ProvisionEngineLike"),
    "ReverseStressResult": ("nikodym.stress.results", "ReverseStressResult"),
    "StressCard": ("nikodym.stress.results", "StressCard"),
    "StressDiagnostics": ("nikodym.stress.results", "StressDiagnostics"),
    "StressResult": ("nikodym.stress.results", "StressResult"),
    "StressScenarioResult": ("nikodym.stress.results", "StressScenarioResult"),
    "StressSensitivityResult": ("nikodym.stress.results", "StressSensitivityResult"),
    "StressStep": ("nikodym.stress.step", "StressStep"),
    "StressTestEngine": ("nikodym.stress.engine", "StressTestEngine"),
}

__all__ = [
    "EclEngineLike",
    "NonMonotonicStressError",
    "ProvisionEngineLike",
    "ReverseStressConfig",
    "ReverseStressError",
    "ReverseStressResult",
    "SensitivitySweepConfig",
    "StressCard",
    "StressConfig",
    "StressConfigError",
    "StressDependencyError",
    "StressDiagnostics",
    "StressDirection",
    "StressEngineError",
    "StressError",
    "StressFaltaDatoError",
    "StressInputConfig",
    "StressInputError",
    "StressMetric",
    "StressOperation",
    "StressOutputConfig",
    "StressOutputError",
    "StressResult",
    "StressScenarioConfig",
    "StressScenarioError",
    "StressScenarioResult",
    "StressSensitivityResult",
    "StressShockConfig",
    "StressStep",
    "StressTargetConfig",
    "StressTestEngine",
    "StressValidationConfig",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="stress") al importar
# `nikodym.stress`, sin contaminar `import nikodym.core` ni cargar pandas/engines/results.
importlib.import_module("nikodym.stress.step")


def __getattr__(name: str) -> Any:
    """Carga DTOs de resultados, engine y el paso orquestable bajo demanda."""
    if name not in _RESULT_EXPORTS:
        raise AttributeError(f"module 'nikodym.stress' has no attribute {name!r}")

    module_name, attribute_name = _RESULT_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
