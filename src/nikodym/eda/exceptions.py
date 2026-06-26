"""Excepciones propias de la capa ``eda`` (SDD-27 §8)."""

from nikodym.core.exceptions import NikodymError

__all__ = ["EdaError"]


class EdaError(NikodymError):
    """Error en el análisis exploratorio descriptivo de riesgo de crédito."""
