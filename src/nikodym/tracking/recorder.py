"""Recorder MLflow para runs, métricas y artefactos de Nikodym (SDD-04 §4/§7)."""

from __future__ import annotations

import json
import math
import tempfile
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from nikodym.core.config import INFRA_SECTIONS, NikodymConfig, config_hash
from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.lineage import LineageBundle
from nikodym.tracking.config import TrackingConfig
from nikodym.tracking.exceptions import TrackingError
from nikodym.tracking.inventory import ModelVersionRef
from nikodym.utils.optional import require_extra

if TYPE_CHECKING:
    from nikodym.core.study import Study

__all__ = ["RunHandle", "TrackingRecorder"]


class RunHandle(BaseModel):
    """Referencia serializable a un run MLflow abierto o persistido."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    experiment_id: str
    artifact_uri: str
    tracking_uri: str


def _json_compacto(value: Any) -> str:
    """Serializa valores complejos como JSON compacto determinista para params/artefactos."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _stringify(value: Any) -> str:
    """Convierte un valor a texto estable para MLflow params/tags."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)) or value is None:
        return "" if value is None else str(value)
    return _json_compacto(value)


def _flatten_config(cfg: NikodymConfig) -> dict[str, str]:
    """Aplana el config computacional a params ``cfg.*`` excluyendo secciones INFRA."""
    payload = cfg.model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))
    flattened: dict[str, str] = {}

    def visit(prefix: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                visit(f"{prefix}.{key}", item)
            return
        flattened[prefix] = _stringify(value)

    for key, value in payload.items():
        visit(f"cfg.{key}", value)
    return flattened


def _metric_items(results: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    """Separa métricas finitas de payload no numérico para ``results.json``."""
    source = results.get("metrics", results)
    non_numeric: dict[str, Any] = {}
    metrics: dict[str, float] = {}

    if not isinstance(source, Mapping):
        return metrics, {"metrics": source}

    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                visit(f"{prefix}.{key}" if prefix else str(key), item)
            return
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            non_numeric[prefix] = value
            return
        metrics[prefix] = float(value)

    for key, value in source.items():
        visit(str(key), value)
    for key, value in results.items():
        if key != "metrics":
            non_numeric[key] = value
    return metrics, non_numeric


class TrackingRecorder:
    """Frontera MLflow: traduce un ``Study`` ejecutado a un run auditable."""

    def __init__(
        self,
        config: TrackingConfig,
        *,
        mlflow_module: Any | None = None,
        warning_sink: Callable[[str], None] | None = None,
    ) -> None:
        """Guarda config e inyección opcional; no abre conexiones ni runs en ``__init__``."""
        self.config = config
        self._mlflow_module = mlflow_module
        self._warning_sink = warning_sink
        self._handle: RunHandle | None = None
        self._bound_study: Study | None = None
        self._default_model_name: str | None = None
        self._no_op = not config.enabled

    def start_run(self, study: Study, *, run_name: str | None = None) -> RunHandle:
        """Abre un run MLflow y devuelve un handle con sus identificadores."""
        self._bound_study = study
        self._default_model_name = study.config.name
        handle = self._start_run(run_name=run_name or study.config.name)
        if not self._no_op:
            self.log_config(study.config)
            if study.run_context.lineage is not None:
                self.log_lineage(study.run_context.lineage)
        return handle

    def __enter__(self) -> RunHandle:
        """Abre un run para el ``Study`` ligado previamente por ``start_run`` o el sink."""
        if self._bound_study is None:
            raise TrackingError("No hay Study ligado al TrackingRecorder para abrir el run.")
        return self.start_run(self._bound_study)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Cierra el run de forma idempotente, marcando fallo si hubo excepción."""
        status = "FAILED" if exc_type is not None else "FINISHED"
        self.end_run(status=status)

    def ensure_run(self, *, run_name: str | None = None) -> RunHandle:
        """Abre un run si aún no existe; lo usa ``TrackingSink`` con eventos de ``core``."""
        if self._handle is not None:
            return self._handle
        return self._start_run(run_name=run_name)

    def end_run(self, *, status: str = "FINISHED") -> None:
        """Cierra el run activo si existe; doble cierre es no-op."""
        if self._handle is None or self._no_op:
            return None

        def operation(mlflow: Any) -> None:
            mlflow.end_run(status=status)

        self._safe(operation, action="cerrar run MLflow")
        self._handle = None
        return None

    def log_config(self, config: NikodymConfig) -> None:
        """Loguea params computacionales y tags de identidad del config."""

        def operation(mlflow: Any) -> None:
            params = _flatten_config(config)
            mlflow.log_params(params)
            mlflow.set_tags(
                {
                    "nikodym.config_hash": config_hash(config),
                    "nikodym.schema_version": config.schema_version,
                }
            )

        self._safe(operation, action="loguear config en MLflow")

    def log_metrics(self, results: dict[str, Any], *, step: int | None = None) -> None:
        """Loguea métricas finitas como metrics y el resto como ``results.json``."""
        metrics, non_numeric = _metric_items(results)

        def operation(mlflow: Any) -> None:
            for key, value in metrics.items():
                if step is None:
                    mlflow.log_metric(key, value)
                else:
                    mlflow.log_metric(key, value, step=step)
            if non_numeric:
                mlflow.log_dict(json.loads(_json_compacto(non_numeric)), "results.json")

        self._safe(operation, action="loguear métricas en MLflow")

    def log_lineage(self, bundle: LineageBundle) -> None:
        """Loguea lineage como tags de búsqueda y artefacto JSON."""
        tags = {
            "nikodym.config_hash": bundle.config_hash,
            "nikodym.schema_version": bundle.schema_version,
            "nikodym.git_dirty": _stringify(bundle.git_dirty),
            "nikodym.root_seed": str(bundle.root_seed),
        }
        optional = {
            "nikodym.git_sha": bundle.git_sha,
            "nikodym.data_hash": bundle.data_hash,
            "nikodym.uv_lock_hash": bundle.uv_lock_hash,
        }
        tags.update({key: value for key, value in optional.items() if value is not None})

        def operation(mlflow: Any) -> None:
            mlflow.set_tags(tags)
            mlflow.log_dict(bundle.model_dump(mode="json"), "study/lineage.json")

        self._safe(operation, action="loguear lineage en MLflow")

    def log_study_dir(self, path: str | Path) -> None:
        """Adjunta el directorio serializado del ``Study`` bajo ``study/``."""
        if not self.config.log_study_artifacts:
            return None

        def operation(mlflow: Any) -> None:
            mlflow.log_artifacts(str(Path(path)), artifact_path="study")

        self._safe(operation, action="loguear directorio del Study en MLflow")
        return None

    def log_artifact_file(self, path: str | Path, *, artifact_path: str | None = None) -> None:
        """Adjunta un fichero de artefacto al run activo."""

        def operation(mlflow: Any) -> None:
            mlflow.log_artifact(str(Path(path)), artifact_path=artifact_path)

        self._safe(operation, action="loguear artefacto en MLflow")

    def register_model(
        self,
        model_uri: str,
        *,
        name: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> ModelVersionRef | None:
        """Registra un modelo vía el atajo MLflow de bajo nivel.

        Con un Registry no respaldado por DB devuelve ``None`` + warning; el contrato regulatorio
        ruidoso vive en ``MLflowInventory.register``.
        """
        if not _registry_db_backed(self.config.registry_uri or self.config.tracking_uri):
            self._warn(
                "Registry MLflow no disponible: configure registry_uri sqlite/http para registrar."
            )
            return None

        result: ModelVersionRef | None = None

        def operation(mlflow: Any) -> None:
            nonlocal result
            model_name = (
                name
                or self.config.registered_model_name
                or self._default_model_name
                or "nikodym-model"
            )
            version = mlflow.register_model(model_uri, model_name)
            client = mlflow.tracking.MlflowClient(registry_uri=self.config.registry_uri)
            for key, value in (tags or {}).items():
                client.set_model_version_tag(model_name, str(version.version), key, value)
            result = ModelVersionRef(
                name=model_name,
                version=str(version.version),
                run_id=getattr(version, "run_id", None),
                source_uri=str(getattr(version, "source", model_uri)),
                aliases=list(getattr(version, "aliases", []) or []),
                tags=dict(tags or {}),
                config_hash=(tags or {}).get("nikodym.config_hash"),
                created_at=_version_timestamp(getattr(version, "creation_timestamp", None)),
            )

        self._safe(operation, action="registrar modelo en MLflow")
        return result

    def snapshot_study(self, study: Study) -> None:
        """Guarda temporalmente el ``Study`` y adjunta su directorio si la config lo permite."""
        if not self.config.log_study_artifacts:
            return None
        with tempfile.TemporaryDirectory(prefix="nikodym-study-") as tmp:
            path = study.save(Path(tmp) / "study")
            self.log_study_dir(path)
        return None

    def _start_run(self, *, run_name: str | None = None) -> RunHandle:
        """Implementación interna tolerante a errores de apertura de run."""
        if self._handle is not None:
            return self._handle
        if self._no_op:
            self._handle = RunHandle(
                run_id="",
                experiment_id="",
                artifact_uri="",
                tracking_uri=self.config.tracking_uri or "./mlruns",
            )
            return self._handle

        handle: RunHandle | None = None

        def operation(mlflow: Any) -> None:
            nonlocal handle
            if self.config.tracking_uri is not None:
                mlflow.set_tracking_uri(self.config.tracking_uri)
            if self.config.registry_uri is not None:
                mlflow.set_registry_uri(self.config.registry_uri)
            if self.config.experiment_name is not None:
                mlflow.set_experiment(self.config.experiment_name)
            run = mlflow.start_run(run_name=run_name)
            info = run.info
            handle = RunHandle(
                run_id=str(info.run_id),
                experiment_id=str(info.experiment_id),
                artifact_uri=str(info.artifact_uri),
                tracking_uri=str(mlflow.get_tracking_uri()),
            )
            if self.config.autolog:
                self._warn("autolog=True fue ignorado: Nikodym exige logging explícito.")

        self._safe(operation, action="abrir run MLflow")
        self._handle = handle or RunHandle(
            run_id="",
            experiment_id="",
            artifact_uri="",
            tracking_uri=self.config.tracking_uri or "./mlruns",
        )
        self._no_op = handle is None
        return self._handle

    def _mlflow(self) -> Any:
        """Importa MLflow perezosamente o devuelve la inyección de tests."""
        if self._mlflow_module is not None:
            return self._mlflow_module
        (mlflow,) = require_extra("tracking", "mlflow")
        self._mlflow_module = mlflow
        return mlflow

    def _safe(self, func: Callable[[Any], None], *, action: str) -> None:
        """Ejecuta una operación MLflow con degradación según ``fail_on_tracking_error``."""
        if self._no_op:
            return None
        try:
            func(self._mlflow())
        except MissingDependencyError as exc:
            self._handle_tracking_error(
                f"{action} requiere el extra tracking: instala `nikodym[tracking]`.", exc
            )
        except Exception as exc:
            self._handle_tracking_error(f"No se pudo {action}: {exc}", exc)
        return None

    def _handle_tracking_error(self, message: str, exc: Exception) -> None:
        """Aplica la política de error del recorder."""
        if self.config.fail_on_tracking_error:
            raise TrackingError(message) from exc
        self._warn(message)
        self._no_op = True

    def _warn(self, message: str) -> None:
        """Advierte por warning o delega al sink inyectado de tests."""
        if self._warning_sink is not None:
            self._warning_sink(message)
            return
        warnings.warn(message, UserWarning, stacklevel=3)


def _registry_db_backed(uri: str | None) -> bool:
    """Heurística defensiva: file store local no soporta Model Registry."""
    if uri is None:
        return False
    return uri.startswith(("sqlite://", "postgresql://", "mysql://", "http://", "https://"))


def _version_timestamp(value: Any) -> Any:
    """Normaliza timestamp de MLflow delegando a Pydantic si ya es ``datetime``."""
    from datetime import UTC, datetime

    if isinstance(value, datetime):
        return value
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value) / 1000.0, UTC)
    return datetime.fromtimestamp(0, UTC)
