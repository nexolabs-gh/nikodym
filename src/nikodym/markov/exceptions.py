"""Excepciones propias de la capa ``markov`` (SDD-19 §4/§8)."""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "InvalidGeneratorError",
    "MarkovConfigError",
    "MarkovEmbeddingError",
    "MarkovError",
    "MarkovFitError",
    "MarkovInputError",
    "MarkovTransformError",
    "NonStochasticMatrixError",
]


class MarkovError(NikodymError):
    """Error base de modelos Markov para migración de estados y lifetime PD."""


class MarkovConfigError(MarkovError):
    """Error en la configuración declarativa de Markov."""


class MarkovInputError(MarkovError):
    """Error en los datos de entrada requeridos para ajustar o proyectar Markov."""


class MarkovFitError(MarkovError):
    """Error durante el ajuste de matrices de transición o generadores Markov."""


class MarkovTransformError(MarkovError):
    """Error al transformar matrices, generadores o term-structures Markov."""


class NonStochasticMatrixError(MarkovTransformError):
    """Error por matriz de transición no estocástica."""


class InvalidGeneratorError(MarkovTransformError):
    """Error por generador continuo inválido."""


class MarkovEmbeddingError(MarkovTransformError):
    """Error al diagnosticar o regularizar el embedding de una matriz Markov."""
