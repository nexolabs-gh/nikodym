"""Excepciones propias de la capa ``performance`` (SDD-11 §4)."""

from nikodym.core.exceptions import NikodymError

__all__ = ["PerformanceDataError", "PerformanceError", "PerformanceMetricError"]


class PerformanceError(NikodymError):
    """Error base de la evaluación de desempeño post-modelo."""


class PerformanceDataError(PerformanceError):
    """Error en los datos requeridos para calcular métricas de desempeño."""


class PerformanceMetricError(PerformanceError):
    """Error al calcular o validar métricas de desempeño."""
