"""Contrato de inventario de modelos definido por governance (SDD-03 §4.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from nikodym.governance.model_card import ModelCard

__all__ = [
    "InventoryEntry",
    "InventoryRecord",
    "ModelInventory",
    "NullInventory",
    "publish_inventory",
]


class InventoryEntry(BaseModel):
    """Entrada completa que una implementación de inventario debe registrar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str
    config_hash: str
    data_hash: str | None
    git_sha: str | None
    run_id: str
    metrics: dict[str, float] = Field(default_factory=dict)
    model_card: ModelCard
    next_review_date: datetime
    tags: dict[str, str] = Field(default_factory=dict)


class InventoryRecord(BaseModel):
    """Registro liviano leído desde el inventario y rehidratable desde tags."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str
    version: str
    config_hash: str
    data_hash: str | None
    git_sha: str | None
    run_id: str
    aliases: list[str] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)
    model_card_uri: str | None
    created_at: datetime


@runtime_checkable
class ModelInventory(Protocol):
    """Protocol SR 11-7 que SDD-04 implementa sobre MLflow Registry.

    ``register`` debe ser idempotente por la ancla ``(model_name, nikodym.config_hash)``. Si el
    backend no soporta Registry, la implementación levanta ``RegistryUnavailableError``.
    """

    def register(self, entry: InventoryEntry) -> str:
        """Registra una entrada y devuelve el identificador de versión."""
        ...

    def get_active(self, model_name: str) -> InventoryRecord | None:
        """Devuelve la versión activa del modelo, si existe."""
        ...

    def list_versions(self, model_name: str) -> list[InventoryRecord]:
        """Lista las versiones conocidas del modelo."""
        ...


class NullInventory:
    """Inventario no-operativo para ``publish_to_inventory=False``."""

    def register(self, entry: InventoryEntry) -> str:
        """No registra nada y devuelve cadena vacía por no-op consciente."""
        return ""

    def get_active(self, model_name: str) -> InventoryRecord | None:
        """Sin backend, no hay versión activa."""
        return None

    def list_versions(self, model_name: str) -> list[InventoryRecord]:
        """Sin backend, no hay versiones."""
        return []


def publish_inventory(entry: InventoryEntry, *, inventory: ModelInventory | None = None) -> str:
    """Publica una entrada usando el inventario inyectado o ``NullInventory``.

    La resolución ``publish_to_inventory=True`` + extra ``tracking`` vive fuera de este módulo
    (B3.1c, ``assemble_run``). Aquí solo se aplica el no-op explícito cuando el llamador entrega
    ``inventory=None``.
    """
    resolved = inventory if inventory is not None else NullInventory()
    return resolved.register(entry)
