"""Helpers internos para compatibilidad con MLflow Registry."""

from __future__ import annotations

__all__ = ["_registry_db_backed"]


def _registry_db_backed(uri: str | None) -> bool:
    """Heurística defensiva: file store local no soporta Model Registry."""
    if uri is None:
        return False
    return uri.startswith(("sqlite://", "postgresql://", "mysql://", "http://", "https://"))
