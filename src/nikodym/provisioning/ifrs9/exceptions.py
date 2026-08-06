"""Excepciones propias de la capa ``provisioning.ifrs9`` (SDD-16 §4/§8).

Toda excepción desciende de :class:`~nikodym.core.exceptions.NikodymError` (raíz propia de la
librería). La jerarquía separa los errores de configuración (:class:`IfrsConfigError`), de datos de
entrada (:class:`IfrsInputError` y su especialización :class:`IfrsTermStructureError` para el
contrato tidy de term-structure) y de cada etapa económica del motor ECL (PD/LGD/EAD, staging,
motor ECL). Los mensajes van en español e incluyen cartera, fila, escenario/período, regla y valor
observado cuando aplique.
"""

from nikodym.core.exceptions import ConfigError, NikodymError
from nikodym.provisioning.exceptions import LgdError

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


class IfrsConfigError(IfrsProvisioningError, ConfigError):
    """Error en la configuración declarativa de provisiones IFRS 9."""


class IfrsInputError(IfrsProvisioningError):
    """Error en los datos de entrada requeridos para calcular la ECL."""


class IfrsTermStructureError(IfrsInputError):
    """Error por un contrato tidy de term-structure lifetime incumplido."""


class IfrsPdError(IfrsProvisioningError):
    """Error al transformar la PD a base PIT/lifetime (Vasicek, horizontes 12m/lifetime)."""


#: Alias de :class:`~nikodym.provisioning.exceptions.LgdError` (D-LGD-2).
#:
#: El motor de LGD se elevó al nivel compartido de ``provisioning`` porque lo consumen los dos
#: motores de provisiones, así que su excepción también subió y ``IfrsLgdError`` pasa a ser el
#: mismo objeto. Se conserva el nombre para no romper los imports existentes.
#:
#: ⚠️ Cambio de contrato, y va con su nota en el CHANGELOG: **deja de descender de
#: ``IfrsProvisioningError``**. Medido antes de decidirlo: ningún ``except`` de ``src/`` captura esa
#: base, y la única invariante aseverada sobre ella —``issubclass(..., NikodymError)``,
#: ``test_ifrs9_config.py:627``— se sigue cumpliendo. El motor IFRS 9 es experimental, fuera de la
#: garantía SemVer 1.x.
IfrsLgdError = LgdError


class IfrsEadError(IfrsProvisioningError):
    """Error al calcular la EAD/CCF o el perfil de exposición por período."""


class IfrsStagingError(IfrsProvisioningError):
    """Error al asignar el staging IFRS 9 (SICR, backstops 30/90 dpd, exención)."""


class IfrsEclError(IfrsProvisioningError):
    """Error en el motor ECL marginal (descuento a EIR, ponderación de escenarios)."""


class IfrsFaltaDatoError(IfrsProvisioningError):
    """Error por un aviso declarado **gobernable** con ``fail_on_falta_dato=True`` (D-CRP6-3).

    No lo levantan los avisos estructurales —los que el motor emite en toda corrida por una
    capacidad diferida propia—, que se registran en la card y nunca detienen: ver
    :func:`nikodym.core.markers.governable_warnings`.
    """
