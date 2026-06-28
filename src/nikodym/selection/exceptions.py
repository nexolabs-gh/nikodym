"""Excepciones propias de la capa ``selection`` (SDD-07 §8)."""

from nikodym.core.exceptions import NikodymError

__all__ = ["SelectionError", "SelectionFitError", "SelectionTransformError"]


class SelectionError(NikodymError):
    """Error base de la selección pre-modelo de variables WoE para scorecard."""


class SelectionFitError(SelectionError):
    """Error al ajustar filtros de selección sobre la partición de Desarrollo."""


class SelectionTransformError(SelectionError):
    """Error al transformar el frame WoE al subconjunto de variables seleccionadas."""
