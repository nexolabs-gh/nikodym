"""Excepciones propias de la capa ``forward`` (SDD-20 §4/§8)."""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "ForwardConfigError",
    "ForwardError",
    "ForwardFitError",
    "ForwardInputError",
    "ForwardPredictionError",
    "ForwardScenarioError",
    "MacroProjectionError",
    "PitConsistencyError",
    "SatelliteModelError",
]


class ForwardError(NikodymError):
    """Error base de modelos forward-looking, escenarios macro y ajuste PIT/TTC."""


class ForwardConfigError(ForwardError):
    """Error en la configuración declarativa de forward-looking."""


class ForwardInputError(ForwardError):
    """Error en los insumos macro o term-structures requeridos por forward-looking."""


class ForwardFitError(ForwardError):
    """Error durante el ajuste de modelos macro o satellite forward-looking."""


class ForwardPredictionError(ForwardError):
    """Error al proyectar variables macro, PD/LGD o term-structures forward-looking."""


class ForwardScenarioError(ForwardError):
    """Error en definiciones, pesos o uso indebido de escenarios forward-looking."""


class PitConsistencyError(ForwardError):
    """Error de consistencia entre PD PIT/TTC y supuestos forward-looking."""


class MacroProjectionError(ForwardPredictionError):
    """Error específico al proyectar escenarios macroeconómicos."""


class SatelliteModelError(ForwardPredictionError):
    """Error específico del modelo satellite de PD/LGD forward-looking."""
