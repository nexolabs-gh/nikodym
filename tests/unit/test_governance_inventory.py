"""Tests del contrato de inventario de ``nikodym.governance``."""

from __future__ import annotations

from datetime import UTC, datetime

from nikodym.audit import EnvironmentSnapshot
from nikodym.governance import (
    GovernanceConfig,
    InventoryEntry,
    InventoryRecord,
    ModelCard,
    ModelInventory,
    NullInventory,
    publish_inventory,
)

_TS = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)
_ENV = EnvironmentSnapshot(
    python_version="3.12.9",
    platform="macOS-15-arm64",
    library_versions={},
    uv_lock_hash=None,
    captured_at=_TS,
)


class _FakeInventory:
    """Inventario fake para probar el Protocol sin depender de tracking/MLflow."""

    def __init__(self) -> None:
        self.entries: list[InventoryEntry] = []

    def register(self, entry: InventoryEntry) -> str:
        """Registra idempotentemente por ``(model_name, config_hash)``."""
        for index, existing in enumerate(self.entries, start=1):
            if (existing.model_name, existing.config_hash) == (entry.model_name, entry.config_hash):
                return str(index)
        self.entries.append(entry)
        return str(len(self.entries))

    def get_active(self, model_name: str) -> InventoryRecord | None:
        """Devuelve una versión activa fake si hay entradas para el modelo."""
        for entry in self.entries:
            if entry.model_name == model_name:
                return InventoryRecord(
                    model_name=entry.model_name,
                    version="1",
                    config_hash=entry.config_hash,
                    data_hash=entry.data_hash,
                    git_sha=entry.git_sha,
                    run_id=entry.run_id,
                    aliases=["champion"],
                    tags=entry.tags,
                    model_card_uri=entry.tags.get("nikodym.model_card_uri"),
                    created_at=_TS,
                )
        return None

    def list_versions(self, model_name: str) -> list[InventoryRecord]:
        """Lista registros fake del modelo solicitado."""
        active = self.get_active(model_name)
        return [] if active is None else [active]


def _card() -> ModelCard:
    """ModelCard mínimo para construir entradas de inventario."""
    return ModelCard(
        run_id="run-001",
        config_hash="cfg123",
        data_hash="data123",
        git_sha="abc123",
        git_dirty=False,
        root_seed=42,
        schema_version="1.0.0",
        created_at=_TS,
        purpose="Scorecard",
        assumptions=[],
        limitations=[],
        data_description=None,
        metrics={"auc": 0.8},
        metric_sections={},
        decisions=[],
        determinism_caveats=[],
        review_date=_TS,
        next_review_date=_TS,
        environment=_ENV,
    )


def _entry() -> InventoryEntry:
    """Entrada de inventario con tags canónicos de identidad/descripción."""
    return InventoryEntry(
        model_name="riesgo-consumo",
        config_hash="cfg123",
        data_hash="data123",
        git_sha="abc123",
        run_id="run-001",
        metrics={"auc": 0.8},
        model_card=_card(),
        next_review_date=_TS,
        tags={
            "nikodym.config_hash": "cfg123",
            "nikodym.data_hash": "data123",
            "nikodym.git_sha": "abc123",
            "nikodym.root_seed": "42",
            "nikodym.run_id": "run-001",
            "nikodym.schema_version": "1.0.0",
            "nikodym.model_card_uri": "runs:/run-001/model_card.json",
            "nikodym.estado_validacion": "desarrollo",
        },
    )


def test_model_inventory_runtime_checkable_y_fake_idempotente() -> None:
    """El Protocol acepta ``isinstance`` y register es idempotente por contrato."""
    fake = _FakeInventory()
    entry = _entry()

    assert isinstance(fake, ModelInventory)
    assert publish_inventory(entry, inventory=fake) == "1"
    assert publish_inventory(entry, inventory=fake) == "1"
    assert len(fake.entries) == 1

    active = fake.get_active("riesgo-consumo")
    assert active is not None
    assert active.aliases == ["champion"]
    assert active.model_card_uri == "runs:/run-001/model_card.json"
    assert fake.list_versions("riesgo-consumo") == [active]
    assert fake.get_active("otro") is None


def test_null_inventory_es_no_op_consciente() -> None:
    """``inventory=None`` usa NullInventory y no publica nada."""
    entry = _entry()
    null = NullInventory()

    assert isinstance(null, ModelInventory)
    assert publish_inventory(entry) == ""
    assert null.register(entry) == ""
    assert null.get_active("riesgo-consumo") is None
    assert null.list_versions("riesgo-consumo") == []


def test_inventory_entry_record_serializan_tags_y_card() -> None:
    """Los tipos de inventario son Pydantic cerrados y serializables."""
    entry = _entry()
    dumped = entry.model_dump(mode="json")

    assert dumped["model_name"] == "riesgo-consumo"
    assert dumped["model_card"]["config_hash"] == "cfg123"
    assert dumped["tags"]["nikodym.config_hash"] == "cfg123"
    assert GovernanceConfig(purpose="x").estado_validacion == "desarrollo"
