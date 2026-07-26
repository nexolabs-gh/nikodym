"""Excepciones propias de la capa ``survival`` (SDD-18 §4/§8)."""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "SurvivalConfigError",
    "SurvivalError",
    "SurvivalFaltaDatoError",
    "SurvivalFitError",
    "SurvivalInputError",
    "SurvivalLicenseError",
    "SurvivalTransformError",
]


class SurvivalError(NikodymError):
    """Error base de los modelos de survival y lifetime PD."""


class SurvivalConfigError(SurvivalError):
    """Error en la configuración declarativa de survival."""


class SurvivalInputError(SurvivalError):
    """Error en los datos de entrada requeridos para ajustar o predecir survival."""


class SurvivalFitError(SurvivalError):
    """Error durante el ajuste estadístico de un modelo de survival."""


class SurvivalTransformError(SurvivalError):
    """Error al transformar hazards, supervivencia o PD lifetime."""


class SurvivalLicenseError(SurvivalError):
    """Error por uso de una dependencia o ruta no permitida por licencia."""


class SurvivalFaltaDatoError(SurvivalError):
    """Error por un aviso declarado **gobernable** con ``fail_on_falta_dato=True`` (D-CRP6-4).

    Espejo de :class:`nikodym.provisioning.ifrs9.exceptions.IfrsFaltaDatoError`: el flag pregunta
    lo mismo en las siete capas, así que la forma de negarse también es la misma.

    A diferencia de IFRS 9, ``survival`` **no declara marcas estructurales**: se midió que sus tres
    avisos (``DATO-INSTITUCIONAL-SUR-1/2/3``) desaparecen con una entrada válida, así que todos son
    gobernables. Ver :func:`nikodym.core.markers.governable_warnings`.
    """
