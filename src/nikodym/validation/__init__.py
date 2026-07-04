"""Capa ``validation`` de Nikodym: validación avanzada (calibración, backtesting, semáforo, SDD-22).

Al importarse, registra :class:`ValidationConfig` en el hook diferido de
:mod:`nikodym.core.config.schema` e importa :mod:`nikodym.validation.step` para ejecutar
``@register("standard", domain="validation")`` del :class:`ValidationStep`. Así
``NikodymConfig.validation`` se valida como sub-config real y el step queda en el ``REGISTRY`` sin
que ``import nikodym.core`` ni ``import nikodym.validation`` arrastren dependencias
tabulares/estadísticas (pandas/pandera/scipy/sklearn): el step importa el evaluador y pandas de
forma **perezosa** dentro de ``execute``. Los DTOs, el evaluador y el step se reexportan perezosos.
Nomenclatura en inglés técnico para APIs; docstrings y errores en español.

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
    "BacktestRecord": ("nikodym.validation.results", "BacktestRecord"),
    "CalibrationTestRecord": ("nikodym.validation.results", "CalibrationTestRecord"),
    "DiscriminationRecord": ("nikodym.validation.results", "DiscriminationRecord"),
    "GradeBinomialRecord": ("nikodym.validation.results", "GradeBinomialRecord"),
    "ValidationCardSection": ("nikodym.validation.results", "ValidationCardSection"),
    "ValidationResult": ("nikodym.validation.results", "ValidationResult"),
    "ValidationEvaluator": ("nikodym.validation.evaluator", "ValidationEvaluator"),
    "ValidationStep": ("nikodym.validation.step", "ValidationStep"),
    "VALIDATION_ARTIFACTS": ("nikodym.validation.step", "VALIDATION_ARTIFACTS"),
}

__all__ = [
    "VALIDATION_ARTIFACTS",
    "BacktestError",
    "BacktestParameter",
    "BacktestRecord",
    "BacktestingValidationConfig",
    "CalibrationTestError",
    "CalibrationTestRecord",
    "CalibrationValidationConfig",
    "DiscriminationPartition",
    "DiscriminationRecord",
    "DiscriminationValidationConfig",
    "GradeBinomialRecord",
    "HlGrouping",
    "PdTest",
    "StabilityValidationConfig",
    "ValidationCardSection",
    "ValidationConfig",
    "ValidationConfigError",
    "ValidationDataError",
    "ValidationError",
    "ValidationEvaluator",
    "ValidationFamily",
    "ValidationResult",
    "ValidationStep",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="validation") al
# importar `nikodym.validation`, sin contaminar `import nikodym.core` ni cargar pandas/scipy/sklearn
# (el step importa el evaluador y pandas dentro de execute).
importlib.import_module("nikodym.validation.step")


def __getattr__(name: str) -> Any:
    """Carga componentes de validation bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.validation' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
