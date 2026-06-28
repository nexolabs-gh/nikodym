"""Excepciones propias de la capa ``scorecard`` (SDD-09 §8)."""

from nikodym.core.exceptions import NikodymError

__all__ = ["ScorecardError", "ScorecardFitError", "ScorecardTransformError"]


class ScorecardError(NikodymError):
    """Error base del escalamiento log-odds a puntos de scorecard."""


class ScorecardFitError(ScorecardError):
    """Error al derivar la tabla de puntos desde modelo y binning."""


class ScorecardTransformError(ScorecardError):
    """Error al transformar variables WoE a puntos y score total."""
