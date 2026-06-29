"""Capa ``survival`` de Nikodym: survival analysis y lifetime PD (SDD-18).

Al importarse, registra :class:`SurvivalConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.survival`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.survival`` ni dependencias estadísticas
opcionales. Este paquete no importa lifelines, statsmodels ni pandas en top-level; los motores
concretos llegarán en B18.3-B18.5 y cargarán sus dependencias dentro de ``fit``/``execute``.

**Experimental (SemVer 0.x).**
"""

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

# Registra la clase real del sub-config survival en el hook de `core`.
_schema._SURVIVAL_CONFIG_CLS = SurvivalConfig

__all__ = [
    "AftFamily",
    "BaseSurvivalModel",
    "CoxAftConfig",
    "DiscreteHazardConfig",
    "DiscreteHazardLink",
    "KaplanMeierConfig",
    "PdSource",
    "SurvivalConfig",
    "SurvivalConfigError",
    "SurvivalError",
    "SurvivalFitError",
    "SurvivalInputConfig",
    "SurvivalInputError",
    "SurvivalLicenseError",
    "SurvivalMethod",
    "SurvivalTimeGridConfig",
    "SurvivalTransformError",
]
