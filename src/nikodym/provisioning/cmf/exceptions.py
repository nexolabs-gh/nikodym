"""Excepciones propias de la capa ``provisioning.cmf`` (SDD-15 §4/§8)."""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "CmfCalculationError",
    "CmfConfigError",
    "CmfInputError",
    "CmfMappingError",
    "CmfMatrixError",
    "CmfMissingRegulatoryDataError",
    "CmfProvisioningError",
]


class CmfProvisioningError(NikodymError):
    """Error base del motor de provisiones regulatorias CMF B-1/B-3."""


class CmfConfigError(CmfProvisioningError):
    """Error en la configuración declarativa de provisiones CMF."""


class CmfInputError(CmfProvisioningError):
    """Error en los datos de entrada requeridos para calcular provisiones CMF."""


class CmfMappingError(CmfProvisioningError):
    """Error al mapear carteras, categorías, PD, contingentes o garantías a reglas CMF."""


class CmfMatrixError(CmfProvisioningError):
    """Error al cargar o validar matrices regulatorias CMF versionadas."""


class CmfMissingRegulatoryDataError(CmfMatrixError):
    """Error por un parámetro normativo marcado como ``FALTA-DATO`` o no verificado."""


class CmfCalculationError(CmfProvisioningError):
    """Error al calcular exposición, PI, PDI, PE o provisión CMF."""
