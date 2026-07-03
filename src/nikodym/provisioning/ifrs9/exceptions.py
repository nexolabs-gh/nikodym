"""Excepciones propias de la capa ``provisioning.ifrs9`` (SDD-16 §4/§8).

Toda excepción desciende de :class:`~nikodym.core.exceptions.NikodymError` (raíz propia de la
librería). La jerarquía separa los errores de configuración (:class:`IfrsConfigError`), de datos de
entrada (:class:`IfrsInputError` y su especialización :class:`IfrsTermStructureError` para el
contrato tidy de term-structure) y de cada etapa económica del motor ECL (PD/LGD/EAD, staging,
motor ECL). Los mensajes van en español e incluyen cartera, fila, escenario/período, regla y valor
observado cuando aplique.
"""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "IfrsConfigError",
    "IfrsEadError",
    "IfrsEclError",
    "IfrsInputError",
    "IfrsLgdError",
    "IfrsPdError",
    "IfrsProvisioningError",
    "IfrsStagingError",
    "IfrsTermStructureError",
]


class IfrsProvisioningError(NikodymError):
    """Error base del motor de provisiones contables IFRS 9 / ECL."""


class IfrsConfigError(IfrsProvisioningError):
    """Error en la configuración declarativa de provisiones IFRS 9."""


class IfrsInputError(IfrsProvisioningError):
    """Error en los datos de entrada requeridos para calcular la ECL."""


class IfrsTermStructureError(IfrsInputError):
    """Error por un contrato tidy de term-structure lifetime incumplido."""


class IfrsPdError(IfrsProvisioningError):
    """Error al transformar la PD a base PIT/lifetime (Vasicek, horizontes 12m/lifetime)."""


class IfrsLgdError(IfrsProvisioningError):
    """Error al estimar la LGD por cualquiera de los enfoques soportados."""


class IfrsEadError(IfrsProvisioningError):
    """Error al calcular la EAD/CCF o el perfil de exposición por período."""


class IfrsStagingError(IfrsProvisioningError):
    """Error al asignar el staging IFRS 9 (SICR, backstops 30/90 dpd, exención)."""


class IfrsEclError(IfrsProvisioningError):
    """Error en el motor ECL marginal (descuento a EIR, ponderación de escenarios)."""
