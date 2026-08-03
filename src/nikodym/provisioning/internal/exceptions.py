"""Excepciones propias de la capa ``provisioning.internal`` (SDD-28 §4/§8)."""

from nikodym.core.exceptions import ConfigError, NikodymError

__all__ = [
    "InternalCalculationError",
    "InternalConfigError",
    "InternalInputError",
    "InternalProvisioningError",
]


class InternalProvisioningError(NikodymError):
    """Error base del motor de provisiones por método interno (CMF B-1 §3)."""


class InternalConfigError(InternalProvisioningError, ConfigError):
    """Error en la configuración declarativa del método interno."""


class InternalInputError(InternalProvisioningError):
    """Error en los datos de entrada exigidos para calcular la provisión interna."""


class InternalCalculationError(InternalProvisioningError):
    """Error al calcular o cuadrar exposición, PD, LGD o provisión del grupo homogéneo."""
