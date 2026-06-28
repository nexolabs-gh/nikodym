"""Capa ``calibration`` de Nikodym: calibración de PD cruda (SDD-10).

Al importarse, registra :class:`CalibrationConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.calibration`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.calibration`` ni dependencias de scoring. La
lógica pesada de calibración se cargará bajo demanda cuando se implemente B10.2/B10.4.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.calibration.config import (
    AnchorKind,
    AnchorSource,
    CalibrationConfig,
    CalibrationMethod,
)
from nikodym.calibration.exceptions import (
    CalibrationError,
    CalibrationFitError,
    CalibrationTransformError,
)
from nikodym.core.config import schema as _schema

# Registra la clase real del sub-config calibration en el hook de `core`.
_schema._CALIBRATION_CONFIG_CLS = CalibrationConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "CalibrationCardSection": ("nikodym.calibration.results", "CalibrationCardSection"),
    "CalibrationParameters": ("nikodym.calibration.results", "CalibrationParameters"),
    "CalibrationResult": ("nikodym.calibration.results", "CalibrationResult"),
    "CalibrationStep": ("nikodym.calibration.step", "CalibrationStep"),
    "PDCalibrator": ("nikodym.calibration.calibrator", "PDCalibrator"),
}

__all__ = [
    "AnchorKind",
    "AnchorSource",
    "CalibrationCardSection",
    "CalibrationConfig",
    "CalibrationError",
    "CalibrationFitError",
    "CalibrationMethod",
    "CalibrationParameters",
    "CalibrationResult",
    "CalibrationStep",
    "CalibrationTransformError",
    "PDCalibrator",
]


def __getattr__(name: str) -> Any:
    """Carga componentes pesados de calibration bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.calibration' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
