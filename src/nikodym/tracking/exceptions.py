"""Excepciones propias de la capa ``tracking`` (SDD-04 §8)."""

from nikodym.core.exceptions import NikodymError
from nikodym.governance.exceptions import RegistryUnavailableError

__all__ = ["ModelNotFoundError", "RegistryUnavailableError", "TrackingError"]


class TrackingError(NikodymError):
    """Error de comunicación o persistencia en la frontera MLflow."""


class ModelNotFoundError(TrackingError):
    """El modelo o versión solicitada no existe en el Registry."""
