"""Excepciones propias de la capa de orquestación ``provisioning`` (SDD-17 §4/§8).

Toda excepción desciende de :class:`~nikodym.core.exceptions.NikodymError` (raíz propia de la
librería). La jerarquía separa los errores de configuración (:class:`ProvisioningConfigError`), de
resultados de entrada malformados (:class:`ProvisioningInputError` y su especialización
:class:`ProvisioningAlignmentError` para claves/niveles no reconciliables) y de las brechas de
cobertura bajo política estricta (:class:`ProvisioningCoverageError`). Los mensajes van en español e
incluyen el nivel de comparación, la celda, el motor y el valor observado cuando aplique.
"""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "ProvisioningAlignmentError",
    "ProvisioningConfigError",
    "ProvisioningCoverageError",
    "ProvisioningError",
    "ProvisioningInputError",
]


class ProvisioningError(NikodymError):
    """Error base de la orquestación de provisiones (piso prudencial CMF vs IFRS 9)."""


class ProvisioningConfigError(ProvisioningError):
    """Error en la configuración declarativa de la orquestación de provisiones."""


class ProvisioningInputError(ProvisioningError):
    """Error en los resultados de entrada (CMF/IFRS 9) que consume la orquestación."""


class ProvisioningAlignmentError(ProvisioningInputError):
    """Error al alinear claves/niveles no reconciliables entre los motores de provisión."""


class ProvisioningCoverageError(ProvisioningError):
    """Error por una brecha de cobertura de celda bajo la política estricta."""
