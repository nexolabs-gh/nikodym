"""Tests de ``MLflowInventory`` con cliente MLflow fake."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from nikodym.audit import EnvironmentSnapshot
from nikodym.core.exceptions import MissingDependencyError
from nikodym.governance import InventoryEntry, ModelCard, ModelInventory, RegistryUnavailableError
from nikodym.tracking import MLflowInventory, ModelNotFoundError, TrackingConfig, TrackingError
from nikodym.tracking import inventory as inventory_mod

_TS = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)


@dataclass
class _Version:
    """Versión fake del MLflow Registry."""

    name: str
    version: str
    run_id: str
    source: str
    tags: dict[str, str]
    aliases: list[str] = field(default_factory=list)
    creation_timestamp: int = 1_771_847_200_000


class _FakeClient:
    """Cliente fake con la mínima API de ``MlflowClient`` usada por el inventario."""

    def __init__(self) -> None:
        self.models: set[str] = set()
        self.versions: list[_Version] = []
        self.calls: list[tuple[str, Any]] = []

    def create_registered_model(self, name: str) -> None:
        """Crea modelo o simula que ya existe."""
        self.calls.append(("create_registered_model", name))
        if name in self.models:
            raise RuntimeError("ya existe")
        self.models.add(name)

    def create_model_version(
        self,
        *,
        name: str,
        source: str,
        run_id: str,
        tags: dict[str, str],
    ) -> _Version:
        """Crea una versión fake."""
        self.calls.append(("create_model_version", (name, source, run_id, dict(tags))))
        version = _Version(
            name=name,
            version=str(len([v for v in self.versions if v.name == name]) + 1),
            run_id=run_id,
            source=source,
            tags=dict(tags),
        )
        self.versions.append(version)
        return version

    def set_model_version_tag(self, name: str, version: str, key: str, value: str) -> None:
        """Actualiza un tag de versión."""
        self.calls.append(("set_model_version_tag", (name, version, key, value)))
        self.get_model_version(name, version).tags[key] = value

    def set_registered_model_alias(self, name: str, alias: str, version: str) -> None:
        """Mueve un alias al version indicado."""
        self.calls.append(("set_registered_model_alias", (name, alias, version)))
        for candidate in self.versions:
            if candidate.name == name and alias in candidate.aliases:
                candidate.aliases.remove(alias)
        self.get_model_version(name, version).aliases.append(alias)

    def search_model_versions(self, filter_string: str) -> list[_Version]:
        """Busca por nombre con el filtro ``name='<model>'``."""
        name = filter_string.split("'", maxsplit=2)[1]
        return [version for version in self.versions if version.name == name]

    def get_model_version(self, name: str, version: str) -> _Version:
        """Devuelve una versión exacta o falla como MLflow."""
        for candidate in self.versions:
            if candidate.name == name and candidate.version == version:
                return candidate
        raise RuntimeError("no existe")

    def get_model_version_by_alias(self, name: str, alias: str) -> _Version:
        """Devuelve la versión apuntada por alias."""
        for candidate in self.versions:
            if candidate.name == name and alias in candidate.aliases:
                return candidate
        raise RuntimeError("sin alias")

    def search_registered_models(self) -> list[Any]:
        """Lista modelos fake."""
        return [SimpleNamespace(name=name) for name in sorted(self.models)]


class _FailingCreateClient(_FakeClient):
    """Cliente fake cuyo Registry falla al crear versiones."""

    def create_model_version(
        self,
        *,
        name: str,
        source: str,
        run_id: str,
        tags: dict[str, str],
    ) -> _Version:
        """Simula backend DB inaccesible."""
        raise RuntimeError("DB caída")


class _NoCreateClient(_FakeClient):
    """Cliente fake sin ``create_registered_model`` para cubrir backend que no lo expone."""

    create_registered_model = None


class _ListOnlyClient:
    """Cliente fake con API legacy ``list_registered_models``."""

    def list_registered_models(self) -> list[Any]:
        """Lista modelos con método alternativo."""
        return [SimpleNamespace(name="legacy-model")]


class _FakeMLflowModule:
    """Módulo MLflow fake para probar import perezoso sin cliente inyectado."""

    def __init__(self, client: _FakeClient) -> None:
        self.client = client
        self.calls: list[tuple[str, str]] = []
        self.tracking = SimpleNamespace(MlflowClient=self._client_factory)

    def set_registry_uri(self, uri: str) -> None:
        """Registra URI de registry."""
        self.calls.append(("set_registry_uri", uri))

    def set_tracking_uri(self, uri: str) -> None:
        """Registra URI de tracking."""
        self.calls.append(("set_tracking_uri", uri))

    def _client_factory(self, *, registry_uri: str | None = None) -> _FakeClient:
        """Devuelve el cliente fake."""
        self.calls.append(("MlflowClient", registry_uri or ""))
        return self.client


def _card() -> ModelCard:
    """Model card mínimo para inventario."""
    env = EnvironmentSnapshot(
        python_version="3.12.9",
        platform="macOS-15-arm64",
        library_versions={},
        uv_lock_hash=None,
        captured_at=_TS,
    )
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
        environment=env,
    )


def _entry(*, config_hash: str = "cfg123", run_id: str = "run-001") -> InventoryEntry:
    """Entrada de inventario con tags canónicos y aliases declarados."""
    return InventoryEntry(
        model_name="riesgo-consumo",
        config_hash=config_hash,
        data_hash="data123",
        git_sha="abc123",
        run_id=run_id,
        metrics={"auc": 0.8},
        model_card=_card(),
        next_review_date=_TS,
        tags={
            "nikodym.config_hash": config_hash,
            "nikodym.model_card_uri": f"runs:/{run_id}/model_card.json",
            "nikodym.estado_validacion": "desarrollo",
            "nikodym.aliases": "champion, production",
        },
    )


def test_mlflow_inventory_implementa_protocol_e_idempotencia() -> None:
    """``register`` no duplica versiones con el mismo ``config_hash``."""
    client = _FakeClient()
    inventory = MLflowInventory(
        TrackingConfig(registry_uri="sqlite:///registry.db"),
        client=client,
    )
    entry = _entry()

    assert isinstance(inventory, ModelInventory)
    assert inventory.register(entry) == "1"
    assert inventory.register(entry) == "1"
    assert inventory.register(_entry(config_hash="cfg456", run_id="run-002")) == "2"
    assert len(client.versions) == 2
    assert ("set_registered_model_alias", ("riesgo-consumo", "champion", "1")) in client.calls
    assert ("set_registered_model_alias", ("riesgo-consumo", "production", "1")) in client.calls

    active = inventory.get_active("riesgo-consumo")
    assert active is not None
    assert active.version == "2"
    assert active.config_hash == "cfg456"
    assert active.model_card_uri == "runs:/run-002/model_card.json"
    assert active.aliases == ["champion", "production"]
    versions = inventory.list_versions("riesgo-consumo")
    assert [version.version for version in versions] == ["1", "2"]
    assert inventory.latest_version("riesgo-consumo", alias="production").version == "2"
    assert inventory.latest_version("riesgo-consumo", alias="challenger") is None
    assert inventory.latest_version("riesgo-consumo").version == "2"
    assert inventory.get_version("riesgo-consumo", 1).config_hash == "cfg123"
    assert inventory.list_models()[0].n_versions == 2


def test_mlflow_inventory_metrics_no_se_escriben_como_tags() -> None:
    """Las metricas quedan en entry.metrics, no en tags ``nikodym.metric.*``."""
    entry = _entry()
    tags = inventory_mod._entry_tags(entry)

    assert entry.metrics == {"auc": 0.8}
    assert "nikodym.config_hash" in tags
    assert not [key for key in tags if key.startswith("nikodym.metric.")]


def test_mlflow_inventory_modelo_version_ausente() -> None:
    """Lecturas inexistentes devuelven ``None`` o levantan la excepción propia."""
    inventory = MLflowInventory(
        TrackingConfig(registry_uri="sqlite:///registry.db"),
        client=_FakeClient(),
    )

    assert inventory.get_active("riesgo-consumo") is None
    assert inventory.list_versions("riesgo-consumo") == []
    assert inventory.latest_version("riesgo-consumo") is None
    with pytest.raises(ModelNotFoundError, match="No existe"):
        inventory.get_version("riesgo-consumo", "99")


def test_mlflow_inventory_file_store_falla_ruidoso() -> None:
    """El método del Protocol nunca publica silenciosamente contra file store."""
    inventory = MLflowInventory(
        TrackingConfig(tracking_uri="file:///tmp/mlruns"),
        client=_FakeClient(),
    )

    with pytest.raises(RegistryUnavailableError, match="backend de base de datos"):
        inventory.register(_entry())


def test_mlflow_inventory_traduce_error_de_registry() -> None:
    """Errores de backend al crear versión se traducen a ``RegistryUnavailableError``."""
    inventory = MLflowInventory(
        TrackingConfig(registry_uri="sqlite:///registry.db"),
        client=_FailingCreateClient(),
    )

    with pytest.raises(RegistryUnavailableError, match="no pudo crear versión"):
        inventory.register(_entry())


def test_mlflow_inventory_extra_ausente_falla_ruidoso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin cliente inyectado, la ausencia de MLflow se traduce a error propio."""

    def missing(extra: str, *modules: str) -> tuple[Any, ...]:
        raise MissingDependencyError("falta mlflow")

    monkeypatch.setattr("nikodym.tracking.inventory.require_extra", missing)
    inventory = MLflowInventory(TrackingConfig(registry_uri="sqlite:///registry.db"))

    with pytest.raises(TrackingError, match="requiere el extra"):
        inventory.list_versions("riesgo-consumo")


def test_mlflow_inventory_import_perezoso_exitoso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin cliente inyectado, MLflow se importa al usar el inventario."""
    client = _FakeClient()
    fake_mlflow = _FakeMLflowModule(client)

    def available(extra: str, *modules: str) -> tuple[Any, ...]:
        return (fake_mlflow,)

    monkeypatch.setattr("nikodym.tracking.inventory.require_extra", available)
    inventory = MLflowInventory(
        TrackingConfig(
            tracking_uri="sqlite:///tracking.db",
            registry_uri="sqlite:///registry.db",
        )
    )

    assert inventory.list_versions("riesgo-consumo") == []
    assert fake_mlflow.calls == [
        ("set_registry_uri", "sqlite:///registry.db"),
        ("set_tracking_uri", "sqlite:///tracking.db"),
        ("MlflowClient", "sqlite:///registry.db"),
    ]

    default_mlflow = _FakeMLflowModule(_FakeClient())
    monkeypatch.setattr(
        "nikodym.tracking.inventory.require_extra",
        lambda extra, *modules: (default_mlflow,),
    )
    assert MLflowInventory(TrackingConfig()).list_versions("riesgo-consumo") == []
    assert default_mlflow.calls == [("MlflowClient", "")]


def test_mlflow_inventory_fallbacks_privados() -> None:
    """Fallas defensivas y formatos alternativos mantienen salida determinista."""
    client = _NoCreateClient()
    inventory = MLflowInventory(
        TrackingConfig(registry_uri="sqlite:///registry.db"),
        client=client,
    )
    entry = _entry()
    entry = entry.model_copy(update={"tags": {"nikodym.config_hash": "cfg123"}})

    assert inventory.register(entry) == "1"
    assert not [call for call in client.calls if call[0] == "set_registered_model_alias"]
    assert inventory_mod._aliases_from_tags({}) == []
    assert inventory_mod._to_datetime(_TS) == _TS
    assert inventory_mod._to_datetime(None) == datetime.fromtimestamp(0, UTC)
    assert inventory_mod._registry_db_backed(None) is False
    assert inventory_mod._call_search_registered_models(_ListOnlyClient())[0].name == "legacy-model"
    assert inventory_mod._call_search_registered_models(object()) == []
    inventory_mod._create_registered_model_if_needed(object(), "sin-api")


def test_mlflow_inventory_search_model_versions_falla() -> None:
    """Un backend que falla al buscar versiones degrada a lista vacía en lectura."""

    class FailingSearchClient(_FakeClient):
        """Cliente que falla al buscar versiones."""

        def search_model_versions(self, filter_string: str) -> list[_Version]:
            """Simula error de lectura."""
            raise RuntimeError("lectura caída")

    inventory = MLflowInventory(
        TrackingConfig(registry_uri="sqlite:///registry.db"),
        client=FailingSearchClient(),
    )

    assert inventory.list_versions("riesgo-consumo") == []
