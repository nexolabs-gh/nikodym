"""Implementación MLflow del ``ModelInventory`` definido por governance (SDD-04 §4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nikodym.core.exceptions import MissingDependencyError
from nikodym.governance.exceptions import RegistryUnavailableError
from nikodym.governance.inventory import InventoryEntry, InventoryRecord
from nikodym.tracking.config import TrackingConfig
from nikodym.tracking.exceptions import ModelNotFoundError, TrackingError
from nikodym.utils.optional import require_extra

__all__ = ["MLflowInventory", "ModelVersionRef", "RegisteredModelInfo"]


class ModelVersionRef(BaseModel):
    """Referencia de bajo nivel a una versión del MLflow Registry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    run_id: str | None
    source_uri: str
    aliases: list[str] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)
    config_hash: str | None
    created_at: datetime


class RegisteredModelInfo(BaseModel):
    """Resumen de un modelo registrado y su última versión."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    n_versions: int
    latest: ModelVersionRef | None


class MLflowInventory:
    """Inventario SR 11-7 respaldado por MLflow Model Registry."""

    def __init__(self, config: TrackingConfig, *, client: Any | None = None) -> None:
        """Guarda config y cliente opcional; MLflow se resuelve perezosamente."""
        self.config = config
        self._client = client

    def register(self, entry: InventoryEntry) -> str:
        """Registra ``entry`` idempotentemente por ``(model_name, config_hash)``."""
        self._ensure_registry_available()
        existing = self._find_by_config_hash(entry.model_name, entry.config_hash)
        if existing is not None:
            return existing.version

        client = self._client_or_raise()
        tags = _entry_tags(entry)
        _create_registered_model_if_needed(client, entry.model_name)
        try:
            version = client.create_model_version(
                name=entry.model_name,
                source=f"runs:/{entry.run_id}/model",
                run_id=entry.run_id,
                tags=tags,
            )
        except Exception as exc:
            raise RegistryUnavailableError(
                f"MLflow Registry no pudo crear versión para '{entry.model_name}': {exc}"
            ) from exc

        version_id = str(version.version)
        for key, value in tags.items():
            client.set_model_version_tag(entry.model_name, version_id, key, value)
        for alias in _aliases_from_tags(entry.tags):
            client.set_registered_model_alias(entry.model_name, alias, version_id)
        return version_id

    def get_active(self, model_name: str) -> InventoryRecord | None:
        """Devuelve la versión apuntada por el alias ``champion``, si existe."""
        ref = self.latest_version(model_name, alias="champion")
        return None if ref is None else _to_inventory_record(ref)

    def list_versions(self, model_name: str) -> list[InventoryRecord]:
        """Lista versiones rehidratadas desde tags del Registry."""
        return [_to_inventory_record(ref) for ref in self._version_refs(model_name)]

    def list_models(self) -> list[RegisteredModelInfo]:
        """Lista modelos registrados con conteo y última versión."""
        client = self._client_or_raise()
        models = _call_search_registered_models(client)
        infos: list[RegisteredModelInfo] = []
        for model in models:
            name = str(model.name)
            refs = self._version_refs(name)
            infos.append(
                RegisteredModelInfo(
                    name=name,
                    n_versions=len(refs),
                    latest=refs[-1] if refs else None,
                )
            )
        return infos

    def get_version(self, name: str, version: str | int) -> ModelVersionRef:
        """Lee una versión exacta; ausente levanta ``ModelNotFoundError``."""
        client = self._client_or_raise()
        try:
            raw = client.get_model_version(name, str(version))
        except Exception as exc:
            raise ModelNotFoundError(
                f"No existe la versión '{version}' del modelo '{name}' en el Registry."
            ) from exc
        return _to_model_version_ref(raw)

    def latest_version(self, name: str, *, alias: str | None = None) -> ModelVersionRef | None:
        """Devuelve versión por alias o la última numérica; ``None`` si no existe."""
        client = self._client_or_raise()
        if alias is not None:
            try:
                return _to_model_version_ref(client.get_model_version_by_alias(name, alias))
            except Exception:
                return None
        refs = self._version_refs(name)
        return refs[-1] if refs else None

    def _version_refs(self, model_name: str) -> list[ModelVersionRef]:
        """Busca versiones de un modelo y las ordena por versión numérica."""
        client = self._client_or_raise()
        try:
            versions = client.search_model_versions(f"name='{model_name}'")
        except Exception:
            return []
        refs = [_to_model_version_ref(raw) for raw in versions]
        return sorted(refs, key=lambda item: int(item.version))

    def _find_by_config_hash(self, model_name: str, config_hash: str) -> ModelVersionRef | None:
        """Busca una versión existente con el mismo tag ``nikodym.config_hash``."""
        for ref in self._version_refs(model_name):
            if ref.tags.get("nikodym.config_hash") == config_hash:
                return ref
        return None

    def _client_or_raise(self) -> Any:
        """Devuelve ``MlflowClient`` perezoso o traduce ausencia del extra."""
        if self._client is not None:
            return self._client
        try:
            (mlflow,) = require_extra("tracking", "mlflow")
        except MissingDependencyError as exc:
            raise TrackingError(
                "MLflowInventory requiere el extra `tracking`: instala `nikodym[tracking]`."
            ) from exc
        if self.config.registry_uri is not None:
            mlflow.set_registry_uri(self.config.registry_uri)
        if self.config.tracking_uri is not None:
            mlflow.set_tracking_uri(self.config.tracking_uri)
        self._client = mlflow.tracking.MlflowClient(registry_uri=self.config.registry_uri)
        return self._client

    def _ensure_registry_available(self) -> None:
        """Falla ruidoso si el Registry configurado es file store local."""
        if not _registry_db_backed(self.config.registry_uri or self.config.tracking_uri):
            raise RegistryUnavailableError(
                "El Model Registry requiere backend de base de datos; configure "
                "registry_uri='sqlite:///.../mlflow.db' o un servidor MLflow."
            )


def _entry_tags(entry: InventoryEntry) -> dict[str, str]:
    """Compone tags canónicos de inventario con prefijo ``nikodym.``."""
    tags = dict(entry.tags)
    required = {
        "nikodym.config_hash": entry.config_hash,
        "nikodym.run_id": entry.run_id,
        "nikodym.proxima_revision": entry.next_review_date.isoformat(),
    }
    optional = {
        "nikodym.data_hash": entry.data_hash,
        "nikodym.git_sha": entry.git_sha,
        "nikodym.model_card_uri": tags.get("nikodym.model_card_uri"),
    }
    tags.update(required)
    tags.update({key: value for key, value in optional.items() if value is not None})
    for key, value in entry.metrics.items():
        tags[f"nikodym.metric.{key}"] = str(value)
    return tags


def _aliases_from_tags(tags: dict[str, str]) -> list[str]:
    """Lee aliases declarados por governance en tags estables."""
    raw = tags.get("nikodym.aliases") or tags.get("nikodym.alias")
    if raw is None:
        return []
    return [alias.strip() for alias in raw.split(",") if alias.strip()]


def _to_model_version_ref(raw: Any) -> ModelVersionRef:
    """Normaliza un objeto ``ModelVersion`` de MLflow o fake de tests."""
    tags = dict(getattr(raw, "tags", {}) or {})
    return ModelVersionRef(
        name=str(raw.name),
        version=str(raw.version),
        run_id=getattr(raw, "run_id", None),
        source_uri=str(getattr(raw, "source", "")),
        aliases=list(getattr(raw, "aliases", []) or []),
        tags=tags,
        config_hash=tags.get("nikodym.config_hash"),
        created_at=_to_datetime(getattr(raw, "creation_timestamp", None)),
    )


def _to_inventory_record(ref: ModelVersionRef) -> InventoryRecord:
    """Convierte una referencia MLflow en el record liviano del Protocol governance."""
    return InventoryRecord(
        model_name=ref.name,
        version=ref.version,
        config_hash=ref.tags.get("nikodym.config_hash", ""),
        data_hash=ref.tags.get("nikodym.data_hash"),
        git_sha=ref.tags.get("nikodym.git_sha"),
        run_id=ref.run_id or ref.tags.get("nikodym.run_id", ""),
        aliases=ref.aliases,
        tags=ref.tags,
        model_card_uri=ref.tags.get("nikodym.model_card_uri"),
        created_at=ref.created_at,
    )


def _to_datetime(value: Any) -> datetime:
    """Convierte timestamps MLflow en milisegundos a ``datetime`` UTC."""
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value) / 1000.0, UTC)
    return datetime.fromtimestamp(0, UTC)


def _create_registered_model_if_needed(client: Any, name: str) -> None:
    """Crea el modelo registrado si el backend lo exige y tolera que ya exista."""
    create = getattr(client, "create_registered_model", None)
    if not callable(create):
        return
    try:
        create(name)
    except Exception:
        return


def _call_search_registered_models(client: Any) -> list[Any]:
    """Compatibiliza clientes MLflow/fakes con nombres de método distintos."""
    search = getattr(client, "search_registered_models", None)
    if callable(search):
        return list(search())
    list_models = getattr(client, "list_registered_models", None)
    if callable(list_models):
        return list(list_models())
    return []


def _registry_db_backed(uri: str | None) -> bool:
    """Heurística defensiva: file store local no soporta Model Registry."""
    if uri is None:
        return False
    return uri.startswith(("sqlite://", "postgresql://", "mysql://", "http://", "https://"))
