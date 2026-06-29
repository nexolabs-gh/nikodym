"""Motor de provisiones CMF (Chile): ``PE = PI·PDI·Exposición`` (B-1).

Al importarse, registra :class:`CmfProvisioningConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.provisioning_cmf`` se valida como
sub-config real sin que ``import nikodym.core`` arrastre ``nikodym.provisioning`` ni dependencias
tabulares pesadas. Nomenclatura CMF (regla dura D-CONV-1): ``pi``/``pdi``/``pe``, nunca
``pd``/``lgd``/``ead``.

**Experimental (SemVer 0.x).**
"""

from nikodym.core.config import schema as _schema
from nikodym.provisioning.cmf.config import (
    CmfExposureConfig,
    CmfFinancialGuaranteePolicy,
    CmfGuaranteeConfig,
    CmfMatrixConfig,
    CmfPdMappingConfig,
    CmfPdMappingMethod,
    CmfPdSourceDomain,
    CmfProvisioningConfig,
    CmfRoundingPolicy,
)
from nikodym.provisioning.cmf.exceptions import (
    CmfCalculationError,
    CmfConfigError,
    CmfInputError,
    CmfMappingError,
    CmfMatrixError,
    CmfMissingRegulatoryDataError,
    CmfProvisioningError,
)

# Registra la clase real del sub-config provisioning_cmf en el hook de `core`.
_schema._PROVISIONING_CMF_CONFIG_CLS = CmfProvisioningConfig

__all__ = [
    "CmfCalculationError",
    "CmfConfigError",
    "CmfExposureConfig",
    "CmfFinancialGuaranteePolicy",
    "CmfGuaranteeConfig",
    "CmfInputError",
    "CmfMappingError",
    "CmfMatrixConfig",
    "CmfMatrixError",
    "CmfMissingRegulatoryDataError",
    "CmfPdMappingConfig",
    "CmfPdMappingMethod",
    "CmfPdSourceDomain",
    "CmfProvisioningConfig",
    "CmfProvisioningError",
    "CmfRoundingPolicy",
]
