"""Excepciones propias de la capa ``audit`` (SDD-03 §8)."""

from nikodym.core.exceptions import NikodymError

__all__ = ["AuditError"]


class AuditError(NikodymError):
    """Error de persistencia, lectura o hashing del audit-trail."""
