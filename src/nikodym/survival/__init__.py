"""Capa ``survival`` de Nikodym: survival analysis y lifetime PD (SDD-18).

Al importarse, registra :class:`SurvivalConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.survival`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.survival`` ni dependencias estadísticas
opcionales. Este paquete no importa lifelines, statsmodels ni pandas en top-level; los motores
concretos llegarán en B18.3-B18.5 y cargarán sus dependencias dentro de ``fit``/``execute``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final

from nikodym.core.config import schema as _schema
from nikodym.survival.base import BaseSurvivalModel
from nikodym.survival.config import (
    AftFamily,
    CoxAftConfig,
    DiscreteHazardConfig,
    DiscreteHazardLink,
    KaplanMeierConfig,
    PdSource,
    SurvivalConfig,
    SurvivalInputConfig,
    SurvivalMethod,
    SurvivalTimeGridConfig,
)
from nikodym.survival.exceptions import (
    SurvivalConfigError,
    SurvivalError,
    SurvivalFitError,
    SurvivalInputError,
    SurvivalLicenseError,
    SurvivalTransformError,
)

if TYPE_CHECKING:
    from nikodym.survival.cox_aft import AFTSurvivalModel, CoxPHSurvivalModel
    from nikodym.survival.discrete_hazard import DiscreteTimeHazardModel
    from nikodym.survival.kaplan_meier import KaplanMeierSurvivalModel
    from nikodym.survival.step import SurvivalStep

# Registra la clase real del sub-config survival en el hook de `core`.
_schema._SURVIVAL_CONFIG_CLS = SurvivalConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "AFTSurvivalModel": (
        "nikodym.survival.cox_aft",
        "AFTSurvivalModel",
    ),
    "CoxPHSurvivalModel": (
        "nikodym.survival.cox_aft",
        "CoxPHSurvivalModel",
    ),
    "DiscreteTimeHazardModel": (
        "nikodym.survival.discrete_hazard",
        "DiscreteTimeHazardModel",
    ),
    "KaplanMeierSurvivalModel": (
        "nikodym.survival.kaplan_meier",
        "KaplanMeierSurvivalModel",
    ),
    "SurvivalStep": ("nikodym.survival.step", "SurvivalStep"),
}

__all__ = [
    "AFTSurvivalModel",
    "AftFamily",
    "BaseSurvivalModel",
    "CoxAftConfig",
    "CoxPHSurvivalModel",
    "DiscreteHazardConfig",
    "DiscreteHazardLink",
    "DiscreteTimeHazardModel",
    "KaplanMeierConfig",
    "KaplanMeierSurvivalModel",
    "PdSource",
    "SurvivalConfig",
    "SurvivalConfigError",
    "SurvivalError",
    "SurvivalFitError",
    "SurvivalInputConfig",
    "SurvivalInputError",
    "SurvivalLicenseError",
    "SurvivalMethod",
    "SurvivalStep",
    "SurvivalTimeGridConfig",
    "SurvivalTransformError",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="survival") al importar
# `nikodym.survival`, sin contaminar `import nikodym.core` ni cargar pandas/lifelines/statsmodels.
importlib.import_module("nikodym.survival.step")


def __getattr__(name: str) -> Any:
    """Carga estimadores survival bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.survival' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
