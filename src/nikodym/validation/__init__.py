"""Capa ``validation`` de Nikodym: validación avanzada (calibración, backtesting, semáforo, SDD-22).

Al importarse, registra :class:`ValidationConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.validation`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.validation`` ni dependencias
tabulares/estadísticas (pandas/pandera/scipy/sklearn). B22.1 aporta **solo config y excepciones**;
los DTOs, evaluadores y el step llegan en los bloques siguientes (B22.2+) y se reexportan de forma
perezosa. Nomenclatura en inglés técnico para APIs; docstrings y errores en español.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.validation.config import (
    BacktestingValidationConfig,
    BacktestParameter,
    CalibrationValidationConfig,
    DiscriminationPartition,
    DiscriminationValidationConfig,
    HlGrouping,
    PdTest,
    StabilityValidationConfig,
    ValidationConfig,
    ValidationFamily,
)

# Registra la clase real del sub-config validation en el hook de `core`.
_schema._VALIDATION_CONFIG_CLS = ValidationConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "BacktestError": ("nikodym.validation.exceptions", "BacktestError"),
    "CalibrationTestError": ("nikodym.validation.exceptions", "CalibrationTestError"),
    "ValidationConfigError": ("nikodym.validation.exceptions", "ValidationConfigError"),
    "ValidationDataError": ("nikodym.validation.exceptions", "ValidationDataError"),
    "ValidationError": ("nikodym.validation.exceptions", "ValidationError"),
}

__all__ = [
    "BacktestError",
    "BacktestParameter",
    "BacktestingValidationConfig",
    "CalibrationTestError",
    "CalibrationValidationConfig",
    "DiscriminationPartition",
    "DiscriminationValidationConfig",
    "HlGrouping",
    "PdTest",
    "StabilityValidationConfig",
    "ValidationConfig",
    "ValidationConfigError",
    "ValidationDataError",
    "ValidationError",
    "ValidationFamily",
]


def __getattr__(name: str) -> Any:
    """Carga componentes de validation bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.validation' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
