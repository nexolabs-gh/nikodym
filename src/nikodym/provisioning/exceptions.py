"""Excepciones del nivel compartido de ``provisioning``: orquestación y motor de LGD.

Cubre la orquestación configurable de dos fuentes (SDD-17 §4/§8) y el motor de LGD (D-LGD-2).

Toda excepción desciende de :class:`~nikodym.core.exceptions.NikodymError` (raíz propia de la
librería). La jerarquía separa los errores de configuración (:class:`ProvisioningConfigError`), de
resultados de entrada malformados (:class:`ProvisioningInputError` y su especialización
:class:`ProvisioningAlignmentError` para claves/niveles no reconciliables) y de las brechas de
cobertura bajo política estricta (:class:`ProvisioningCoverageError`). Los mensajes van en español e
incluyen el nivel de comparación, la celda, el motor y el valor observado cuando aplique.

:class:`LgdError` es **hermana** de :class:`ProvisioningError`, no hija: un fallo al estimar la
severidad no es un fallo de orquestación de dos fuentes, y colgarlo de ahí haría que un
``except ProvisioningError`` atrapara algo que nunca pasó por el orquestador.
"""

from nikodym.core.exceptions import ConfigError, NikodymError

__all__ = [
    "LgdError",
    "ProvisioningAlignmentError",
    "ProvisioningConfigError",
    "ProvisioningCoverageError",
    "ProvisioningError",
    "ProvisioningInputError",
]


class LgdError(NikodymError):
    """Error al estimar la LGD por cualquiera de los enfoques soportados (D-LGD-2).

    Vive en el nivel compartido porque el motor de LGD lo usan los dos motores de provisiones —el
    contable IFRS 9 y el interno, que es jurisdiccionalmente neutro—. ``IfrsLgdError`` es hoy un
    **alias** de esta clase, conservado para no romper los imports que ya existían.
    """


class ProvisioningError(NikodymError):
    """Error base de la orquestación configurable de dos fuentes de provisión."""


class ProvisioningConfigError(ProvisioningError, ConfigError):
    """Error en la configuración declarativa de la orquestación de provisiones."""


class ProvisioningInputError(ProvisioningError):
    """Error en los resultados de fuente que consume la orquestación."""


class ProvisioningAlignmentError(ProvisioningInputError):
    """Error al alinear claves/niveles no reconciliables entre los motores de provisión."""


class ProvisioningCoverageError(ProvisioningError):
    """Error por una brecha de cobertura de celda bajo la política estricta."""
