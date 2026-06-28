"""Capa ``model`` de Nikodym: regresión logística PD sobre variables WoE (SDD-08).

Al importarse, registra :class:`ModelConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.model`` se valida como sub-config real sin
que ``import nikodym.core`` arrastre ``nikodym.model`` ni dependencias de scoring. La lógica pesada
de estimación (``estimator.py``) se carga bajo demanda; el paquete importa ``model.step`` al final
para ejecutar ``@register("standard", domain="model")`` sin arrastrar dependencias de scoring.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.model.config import (
    IvContributionConfig,
    ModelConfig,
    ModelEngine,
    ModelOptimizer,
    ModelPolicyAction,
    SignPolicyConfig,
    StepwiseConfig,
    StepwiseCriterion,
    StepwiseDirection,
)
from nikodym.model.exceptions import ModelError, ModelFitError, ModelTransformError

# Registra la clase real del sub-config model en el hook de `core`.
_schema._MODEL_CONFIG_CLS = ModelConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "CoefficientRecord": ("nikodym.model.results", "CoefficientRecord"),
    "LogisticPDModel": ("nikodym.model.estimator", "LogisticPDModel"),
    "ModelCardSection": ("nikodym.model.results", "ModelCardSection"),
    "ModelFitStatistics": ("nikodym.model.results", "ModelFitStatistics"),
    "ModelResult": ("nikodym.model.results", "ModelResult"),
    "ModelStep": ("nikodym.model.step", "ModelStep"),
    "StepwiseDecision": ("nikodym.model.results", "StepwiseDecision"),
}

__all__ = [
    "CoefficientRecord",
    "IvContributionConfig",
    "LogisticPDModel",
    "ModelCardSection",
    "ModelConfig",
    "ModelEngine",
    "ModelError",
    "ModelFitError",
    "ModelFitStatistics",
    "ModelOptimizer",
    "ModelPolicyAction",
    "ModelResult",
    "ModelStep",
    "ModelTransformError",
    "SignPolicyConfig",
    "StepwiseConfig",
    "StepwiseCriterion",
    "StepwiseDecision",
    "StepwiseDirection",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="model") al importar
# `nikodym.model`, sin contaminar `import nikodym.core` ni cargar scoring.
importlib.import_module("nikodym.model.step")


def __getattr__(name: str) -> Any:
    """Carga componentes pesados de model bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.model' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
