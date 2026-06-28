"""Excepciones propias de la capa ``stability`` (SDD-11 §4)."""

from nikodym.core.exceptions import NikodymError

__all__ = ["StabilityDataError", "StabilityError", "StabilityMetricError"]


class StabilityError(NikodymError):
    """Error base de la evaluación de estabilidad post-modelo."""


class StabilityDataError(StabilityError):
    """Error en los datos requeridos para calcular métricas de estabilidad."""


class StabilityMetricError(StabilityError):
    """Error al calcular o validar métricas de estabilidad."""
