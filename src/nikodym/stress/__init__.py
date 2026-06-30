"""Capa ``stress`` de Nikodym: stress testing, sensibilidad y reverse stress (SDD-21).

Al importarse, registra :class:`StressConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.stress`` se valida como sub-config real sin
que ``import nikodym.core`` importe ``nikodym.stress`` ni motores económicos futuros. En B21.1 el
paquete expone solo config y excepciones; los DTOs, engine y step se agregan en los bloques
siguientes.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

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

__all__ = [
    "NonMonotonicStressError",
    "ReverseStressConfig",
    "ReverseStressError",
    "SensitivitySweepConfig",
    "StressConfig",
    "StressConfigError",
    "StressDependencyError",
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
    "StressScenarioConfig",
    "StressScenarioError",
    "StressShockConfig",
    "StressTargetConfig",
    "StressValidationConfig",
]
