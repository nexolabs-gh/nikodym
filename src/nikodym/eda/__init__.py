"""Capa ``eda`` de Nikodym: diagnóstico exploratorio orientado a riesgo (SDD-27).

Al importarse, registra :class:`EdaConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.eda`` se valida como sub-config real sin que
``import nikodym.core`` arrastre ``nikodym.eda`` ni dependencias tabulares. Esta primera pieza de
EDA solo publica configuración y excepciones; los analizadores se añaden en B5.2+.

**Experimental (SemVer 0.x).**
"""

from nikodym.core.config import schema as _schema
from nikodym.eda.config import (
    DefaultRateConfig,
    EdaConfig,
    QualityConfig,
    SamplingConfig,
    TemporalStabilityConfig,
    UnivariateConfig,
)
from nikodym.eda.exceptions import EdaError

# Registra la clase real del sub-config EDA en el hook de `core`.
_schema._EDA_CONFIG_CLS = EdaConfig

__all__ = [
    "DefaultRateConfig",
    "EdaConfig",
    "EdaError",
    "QualityConfig",
    "SamplingConfig",
    "TemporalStabilityConfig",
    "UnivariateConfig",
]
