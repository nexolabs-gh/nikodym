"""Capa ``explain`` de Nikodym: explicabilidad unificada scorecard + SHAP (SDD-14).

Este ``__init__`` es **liviano**: reexporta la jerarquía de excepciones y el config declarativo
(:class:`ExplainConfig` con sus sub-schemas y alias de tipos), y **puebla el hook diferido**
``_EXPLAIN_CONFIG_CLS`` en :class:`~nikodym.core.config.NikodymConfig` para que la sección
``explain`` se valide como sub-config real, **sin** que ``import nikodym.core`` ni
``import nikodym.explain`` arrastren ``shap``/``matplotlib``/``numba``/``sklearn``/``pandas``/
``numpy``: el motor y los explainers se importan de forma **perezosa** en bloques posteriores
(B14.2+). Nomenclatura en inglés técnico para APIs; docstrings y errores en español.

En B14.1 aún no existen ``step``/``engine``/``results``; cuando lleguen (B14.2+) este ``__init__``
sumará los reexports perezosos y el ``importlib.import_module('nikodym.explain.step')`` que ejecuta
``@register('standard', domain='explain')``, igual que ``ml.__init__``/``tuning.__init__``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

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

__all__ = [
    "ContributionSpace",
    "ExplainBackendError",
    "ExplainConfig",
    "ExplainConfigError",
    "ExplainDataError",
    "ExplainDeterminismError",
    "ExplainError",
    "ExplainExplainerError",
    "ExplainOutputConfig",
    "ExplainReasonCodeError",
    "ExplainTargets",
    "LocalScope",
    "LocalScopeConfig",
    "MLExplainerChoice",
    "MLExplainerConfig",
    "ReasonCodesConfig",
    "ScorecardBaseline",
    "ScorecardExplainConfig",
    "TreePerturbation",
]
