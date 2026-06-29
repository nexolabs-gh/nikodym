"""Excepciones propias de la capa ``survival`` (SDD-18 §4/§8)."""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "SurvivalConfigError",
    "SurvivalError",
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
