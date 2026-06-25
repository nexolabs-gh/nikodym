"""Excepciones propias de la capa ``governance`` (SDD-03 §8)."""

from nikodym.core.exceptions import NikodymError

__all__ = ["GovernanceError", "RegistryUnavailableError"]


class GovernanceError(NikodymError):
    """Error al construir evidencia de gobernanza o registrar escenarios."""


class RegistryUnavailableError(GovernanceError):
    """El inventario configurado no soporta un Registry de modelos usable."""
