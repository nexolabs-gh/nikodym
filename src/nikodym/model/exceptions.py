"""Excepciones propias de la capa ``model`` (SDD-08 §8)."""

from nikodym.core.exceptions import NikodymError

__all__ = ["ModelError", "ModelFitError", "ModelTransformError"]


class ModelError(NikodymError):
    """Error base del modelo logístico PD para scorecard."""


class ModelFitError(ModelError):
    """Error al ajustar el modelo logístico sobre la partición de Desarrollo."""


class ModelTransformError(ModelError):
    """Error al transformar datos WoE a PD cruda con el modelo fiteado."""
