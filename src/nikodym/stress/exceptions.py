"""Excepciones propias de la capa ``stress`` (SDD-21 §4/§8)."""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "NonMonotonicStressError",
    "ReverseStressError",
    "StressConfigError",
    "StressDependencyError",
    "StressEngineError",
    "StressError",
    "StressFaltaDatoError",
    "StressInputError",
    "StressOutputError",
    "StressScenarioError",
]


class StressError(NikodymError):
    """Error base de stress testing, sensibilidad y reverse stress."""


class StressConfigError(StressError):
    """Error en la configuración declarativa de stress testing."""


class StressInputError(StressError):
    """Error en los insumos forward o metadata requeridos por stress testing."""


class StressScenarioError(StressError):
    """Error en escenarios, shocks o severidades declaradas para stress testing."""


class StressEngineError(StressError):
    """Error durante la aplicación del motor determinista de stress testing."""


class StressOutputError(StressError):
    """Error en las salidas tabulares o métricas publicadas por stress testing."""


class StressDependencyError(StressError):
    """Error por dependencia económica o artefacto requerido ausente."""


class StressFaltaDatoError(StressError):
    """Error por brecha FALTA-DATO-STR que no puede inventarse silenciosamente."""


class ReverseStressError(StressEngineError):
    """Error específico al resolver reverse stress por bisección monotónica."""


class NonMonotonicStressError(ReverseStressError):
    """Error cuando la métrica objetivo de reverse stress no es monotónica."""
