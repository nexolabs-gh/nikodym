"""Capa ``explain`` de Nikodym: explicabilidad unificada scorecard + SHAP (SDD-14).

Este ``__init__`` es **liviano**: reexporta la jerarquía de excepciones y el config declarativo
(:class:`ExplainConfig` con sus sub-schemas y alias de tipos), **puebla el hook diferido**
``_EXPLAIN_CONFIG_CLS`` en :class:`~nikodym.core.config.NikodymConfig` para que la sección
``explain`` se valide como sub-config real, y al final hace
``importlib.import_module('nikodym.explain.step')`` para ejecutar
``@register('standard', domain='explain')``. Todo ello **sin** que ``import nikodym.core`` ni
``import nikodym.explain`` arrastren ``shap``/``matplotlib``/``numba``/``llvmlite``/``sklearn``/
``pandas``/``numpy``: el motor y los explainers importan lo pesado de forma **perezosa** dentro de
sus métodos, y los DTOs/resultados se reexportan perezosos (molde idéntico a ``ml.__init__``).
Nomenclatura en inglés técnico para APIs; docstrings y errores en español.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.explain.config import (
    ContributionSpace,
    ExplainConfig,
    ExplainOutputConfig,
    ExplainTargets,
    LocalScope,
    LocalScopeConfig,
    MLExplainerChoice,
    MLExplainerConfig,
    ReasonCodesConfig,
    ScorecardBaseline,
    ScorecardExplainConfig,
    TreePerturbation,
)
from nikodym.explain.exceptions import (
    ExplainBackendError,
    ExplainConfigError,
    ExplainDataError,
    ExplainDeterminismError,
    ExplainError,
    ExplainExplainerError,
    ExplainReasonCodeError,
)

# Registra la clase real del sub-config explain en el hook de `core` (sin importar shap/tabulares).
_schema._EXPLAIN_CONFIG_CLS = ExplainConfig

# Reexports perezosos de los DTOs, el motor y el step (evitan arrastrar shap/pandas/numpy al
# importar el paquete): sólo se resuelven la primera vez que se acceden por atributo.
_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "UnifiedExplainer": ("nikodym.explain.engine", "UnifiedExplainer"),
    "resolve_explainer": ("nikodym.explain.explainers", "resolve_explainer"),
    "build_reason_codes": ("nikodym.explain.reason_codes", "build_reason_codes"),
    "DriverComparisonRecord": ("nikodym.explain.results", "DriverComparisonRecord"),
    "ExplainCardSection": ("nikodym.explain.results", "ExplainCardSection"),
    "ExplainResult": ("nikodym.explain.results", "ExplainResult"),
    "ExplainerMetadata": ("nikodym.explain.results", "ExplainerMetadata"),
    "LocalExplanationRecord": ("nikodym.explain.results", "LocalExplanationRecord"),
    "ReasonCode": ("nikodym.explain.results", "ReasonCode"),
    "ShapGlobalRecord": ("nikodym.explain.results", "ShapGlobalRecord"),
    "ExplainStep": ("nikodym.explain.step", "ExplainStep"),
}

__all__ = [
    "ContributionSpace",
    "DriverComparisonRecord",
    "ExplainBackendError",
    "ExplainCardSection",
    "ExplainConfig",
    "ExplainConfigError",
    "ExplainDataError",
    "ExplainDeterminismError",
    "ExplainError",
    "ExplainExplainerError",
    "ExplainOutputConfig",
    "ExplainReasonCodeError",
    "ExplainResult",
    "ExplainStep",
    "ExplainTargets",
    "ExplainerMetadata",
    "LocalExplanationRecord",
    "LocalScope",
    "LocalScopeConfig",
    "MLExplainerChoice",
    "MLExplainerConfig",
    "ReasonCode",
    "ReasonCodesConfig",
    "ScorecardBaseline",
    "ScorecardExplainConfig",
    "ShapGlobalRecord",
    "TreePerturbation",
    "UnifiedExplainer",
    "build_reason_codes",
    "resolve_explainer",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="explain") al importar
# `nikodym.explain`, sin arrastrar shap/matplotlib/pandas/numpy (el step los carga en `execute`).
importlib.import_module("nikodym.explain.step")


def __getattr__(name: str) -> Any:
    """Carga perezosa de DTOs/motor/step de ``explain`` para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.explain' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
