"""Jerarquía de excepciones de Nikodym (SDD-01 §4, SDD-05 §4.3).

Regla única: toda excepción de la librería desciende de :class:`NikodymError`, de modo que
``except NikodymError`` captura cualquier fallo propio sin tener que enumerar cada clase.
``core.exceptions`` aloja la **raíz** y las excepciones del **núcleo**; los módulos de dominio
definen sus propias subclases (de :class:`NikodymError` o de la excepción de core que
corresponda) en su propio módulo. Los mensajes van en **español** e incluyen, cuando aplica,
la regla, el umbral gatillante y el valor observado (auditabilidad, §4 principio 2).
"""

__all__ = [
    "ArtifactExistsError",
    "ArtifactNotFoundError",
    "ConfigError",
    "ConfigVersionError",
    "DataValidationError",
    "DuplicateRegistrationError",
    "MigrationNotFoundError",
    "MissingDependencyError",
    "NikodymError",
    "NotFittedError",
    "RegistryError",
    "RegulatoryError",
    "ReproducibilityError",
    "UnknownComponentError",
    "UntrustedStudyError",
]


class NikodymError(Exception):
    """Raíz de toda excepción de la librería Nikodym."""


class ConfigError(NikodymError):
    """Config inválido: campo desconocido, tipo/rango erróneo o mutación de un config frozen."""


class ConfigVersionError(ConfigError):
    """El ``schema_version`` del config es mayor que el del paquete (config "del futuro")."""


class MigrationNotFoundError(ConfigError):
    """Falta un migrador registrado para saltar de una ``schema_version`` a otra."""


class DataValidationError(NikodymError):
    """Los datos no cumplen el contrato de esquema/calidad esperado."""


class NotFittedError(NikodymError):
    """Se invocó ``predict``/``transform``/``compute`` antes de ``fit``.

    Desciende solo de :class:`NikodymError` (D-CORE-5): un ``except`` sobre la
    ``NotFittedError`` de scikit-learn no la atrapa. Un estimador de dominio que necesite
    capturar ambas puede definir localmente una subclase multiherencia.
    """


class RegistryError(NikodymError):
    """Error genérico del registro de componentes (``Registry``)."""


class UnknownComponentError(RegistryError):
    """Se solicitó un componente ``(domain, name)`` no registrado."""


class DuplicateRegistrationError(RegistryError):
    """Se registró dos veces la misma pareja ``(domain, name)`` (detectado en import time)."""


class ArtifactNotFoundError(NikodymError):
    """Se solicitó un artefacto ``(domain, key)`` ausente del ``ArtifactStore``."""


class ArtifactExistsError(NikodymError):
    """Se intentó escribir un artefacto ``(domain, key)`` ya presente sin ``overwrite=True``."""


class ReproducibilityError(NikodymError):
    """El ``config_hash`` no coincide al recargar un ``Study`` (señal de manipulación)."""


class UntrustedStudyError(NikodymError):
    """Se cargó con ``trust=False`` un ``Study`` de origen no verificado (vector pickle)."""


class RegulatoryError(NikodymError):
    """Violación de una regla regulatoria dura (p. ej. la regla B-1; SDD-15/17/28)."""


class MissingDependencyError(NikodymError):
    """Se usó un backend opcional sin instalar su *extra* (import perezoso; SDD-25)."""
