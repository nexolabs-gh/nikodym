"""Tests de ``TrackingRecorder`` y ``TrackingSink`` con MLflow fake."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nikodym.core.audit import AuditEvent
from nikodym.core.config import NikodymConfig
from nikodym.core.config import schema as _schema_mod
from nikodym.core.config.schema import RunConfig
from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.lineage import LineageBundle
from nikodym.core.study import Study
from nikodym.tracking import TrackingConfig, TrackingError, TrackingRecorder, TrackingSink

_TS = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)


class _FakeMLflow:
    """MLflow fake suficiente para verificar las llamadas públicas del recorder."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.tracking_uri = "./mlruns"
        self.started = 0
        self.tracking = SimpleNamespace(MlflowClient=self._client_factory)

    def set_tracking_uri(self, uri: str) -> None:
        """Registra el tracking URI."""
        self.tracking_uri = uri
        self.calls.append(("set_tracking_uri", uri))

    def set_registry_uri(self, uri: str) -> None:
        """Registra el registry URI."""
        self.calls.append(("set_registry_uri", uri))

    def set_experiment(self, name: str) -> None:
        """Registra el experimento."""
        self.calls.append(("set_experiment", name))

    def start_run(self, *, run_name: str | None = None) -> Any:
        """Abre un run fake con ids deterministas."""
        self.started += 1
        self.calls.append(("start_run", run_name))
        info = SimpleNamespace(
            run_id=f"run-{self.started}",
            experiment_id="exp-001",
            artifact_uri=f"file:///tmp/run-{self.started}",
        )
        return SimpleNamespace(info=info)

    def get_tracking_uri(self) -> str:
        """Devuelve el URI activo."""
        return self.tracking_uri

    def log_params(self, params: dict[str, str]) -> None:
        """Registra params."""
        self.calls.append(("log_params", params))

    def set_tags(self, tags: dict[str, str]) -> None:
        """Registra tags."""
        self.calls.append(("set_tags", tags))

    def log_metric(self, key: str, value: float, *, step: int | None = None) -> None:
        """Registra una métrica."""
        self.calls.append(("log_metric", (key, value, step)))

    def log_dict(self, payload: dict[str, Any], artifact_file: str) -> None:
        """Registra un dict como artefacto."""
        self.calls.append(("log_dict", (artifact_file, payload)))

    def log_artifacts(self, path: str, *, artifact_path: str | None = None) -> None:
        """Registra un directorio."""
        self.calls.append(("log_artifacts", (path, artifact_path)))

    def log_artifact(self, path: str, *, artifact_path: str | None = None) -> None:
        """Registra un archivo."""
        self.calls.append(("log_artifact", (Path(path).name, artifact_path)))

    def end_run(self, *, status: str) -> None:
        """Cierra el run."""
        self.calls.append(("end_run", status))

    def autolog(self) -> None:
        """No debe llamarse por la regla dura D-TRK-3."""
        self.calls.append(("autolog", None))

    def register_model(self, model_uri: str, model_name: str) -> Any:
        """Registra un modelo fake por el atajo de bajo nivel."""
        self.calls.append(("register_model", (model_uri, model_name)))
        return SimpleNamespace(
            name=model_name,
            version="3",
            run_id="run-registered",
            source=model_uri,
            aliases=["champion"],
            creation_timestamp=1_771_847_200_000,
        )

    def _client_factory(self, *, registry_uri: str | None = None) -> Any:
        """Devuelve un cliente fake para tags de versión."""
        self.calls.append(("MlflowClient", registry_uri))

        class Client:
            """Cliente fake embebido para tags de modelo."""

            def __init__(self, calls: list[tuple[str, Any]]) -> None:
                self.calls = calls

            def set_model_version_tag(
                self,
                model_name: str,
                version: str,
                key: str,
                value: str,
            ) -> None:
                """Registra tag de versión."""
                self.calls.append(("set_model_version_tag", (model_name, version, key, value)))

        return Client(self.calls)


class _BrokenMLflow(_FakeMLflow):
    """MLflow fake que falla al abrir run."""

    def start_run(self, *, run_name: str | None = None) -> Any:
        """Simula servidor MLflow caído."""
        raise RuntimeError("servidor caído")


def _lineage() -> LineageBundle:
    """Lineage determinista para tests de tracking."""
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123",
        config_hash="cfg123",
        root_seed=42,
        uv_lock_hash="uvhash",
        library_versions={"nikodym": "0.1.0"},
        determinism_caveats=[],
        created_at=_TS,
        schema_version="1.0.0",
    )


def _study() -> Study:
    """Study finalizado en memoria con lineage y métricas."""
    study = Study(NikodymConfig(name="riesgo", tracking=TrackingConfig()))
    study.run_context.status = "done"
    study.run_context.run_id = "study-run"
    study.run_context.lineage = _lineage()
    study.results["metrics"] = {"auc": 0.81, "ks": 0.42, "nan": float("nan")}
    study.results["table"] = {"x": [1, 2]}
    return study


def test_recorder_start_run_loguea_config_lineage_y_metrics(tmp_path: Path) -> None:
    """El recorder abre run, filtra métricas y adjunta artefactos sin autolog."""
    fake = _FakeMLflow()
    recorder = TrackingRecorder(
        TrackingConfig(
            tracking_uri="file:///tmp/mlruns",
            registry_uri="sqlite:///tmp/registry.db",
            experiment_name="riesgo-exp",
            autolog=True,
        ),
        mlflow_module=fake,
    )
    study = _study()

    with pytest.warns(UserWarning, match="autolog=True fue ignorado"):
        handle = recorder.start_run(study, run_name="manual")
    recorder.log_metrics(study.results, step=7)
    artifact = tmp_path / "model_card.json"
    artifact.write_text("{}", encoding="utf-8")
    recorder.log_artifact_file(artifact, artifact_path="cards")
    recorder.log_study_dir(tmp_path)
    recorder.end_run()

    assert handle.run_id == "run-1"
    assert ("set_tracking_uri", "file:///tmp/mlruns") in fake.calls
    assert ("set_registry_uri", "sqlite:///tmp/registry.db") in fake.calls
    assert ("set_experiment", "riesgo-exp") in fake.calls
    assert ("start_run", "manual") in fake.calls
    assert not [call for call in fake.calls if call[0] == "autolog"]
    params = next(value for name, value in fake.calls if name == "log_params")
    assert params == {
        "cfg.repro.seed": "42",
        "cfg.repro.strict_determinism": "false",
        "cfg.run.fail_fast": "true",
        "cfg.schema_version": "1.0.0",
    }
    tag_payloads = [value for name, value in fake.calls if name == "set_tags"]
    assert tag_payloads[0]["nikodym.config_hash"]
    assert tag_payloads[1]["nikodym.git_sha"] == "abc123"
    assert ("log_metric", ("auc", 0.81, 7)) in fake.calls
    assert ("log_metric", ("ks", 0.42, 7)) in fake.calls
    results_payload = next(
        value for name, value in fake.calls if name == "log_dict" and value[0] == "results.json"
    )[1]
    assert set(results_payload) == {"nan", "table"}
    assert results_payload["table"] == {"x": [1, 2]}
    assert ("log_artifact", ("model_card.json", "cards")) in fake.calls
    assert ("log_artifacts", (str(tmp_path), "study")) in fake.calls
    assert ("end_run", "FINISHED") in fake.calls


def test_recorder_cubre_context_manager_y_ramas_de_metricas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ramas defensivas del recorder se mantienen deterministas."""
    fake = _FakeMLflow()
    recorder = TrackingRecorder(TrackingConfig(), mlflow_module=fake)

    with pytest.raises(TrackingError, match="No hay Study ligado"):
        recorder.__enter__()

    study = _study()
    recorder._bound_study = study
    handle = recorder.__enter__()
    assert handle.run_id == "run-1"
    assert recorder.ensure_run(run_name="reusado") == handle
    recorder.log_metrics({"metrics": {"nested": {"auc": 0.7}, "flag": True, "txt": "x"}})
    recorder.log_metrics({"metrics": ["no-mapping"]})
    recorder.__exit__(RuntimeError, RuntimeError("boom"), None)
    assert ("log_metric", ("nested.auc", 0.7, None)) in fake.calls
    assert ("end_run", "FAILED") in fake.calls

    sin_lineage = Study(NikodymConfig())
    TrackingRecorder(TrackingConfig(), mlflow_module=fake).start_run(sin_lineage)

    broken_start = TrackingRecorder(
        TrackingConfig(),
        mlflow_module=_BrokenMLflow(),
        warning_sink=lambda message: None,
    )
    broken_start.start_run(_study())

    from nikodym.tracking import recorder as recorder_mod

    assert recorder_mod._stringify(None) == ""
    assert recorder_mod._stringify({"b": 2, "a": 1}) == '{"a":1,"b":2}'

    def available(extra: str, *modules: str) -> tuple[Any, ...]:
        return (fake,)

    monkeypatch.setattr("nikodym.tracking.recorder.require_extra", available)
    imported = TrackingRecorder(TrackingConfig())
    imported.ensure_run(run_name="importado")
    assert imported._mlflow_module is fake


def test_recorder_register_model_y_flags_de_artifactos() -> None:
    """El atajo de registro y los flags de artefactos siguen contratos SDD-04."""
    warnings: list[str] = []
    file_store = TrackingRecorder(
        TrackingConfig(),
        warning_sink=warnings.append,
    )
    assert file_store.register_model("runs:/run/model") is None
    assert warnings == [
        "Registry MLflow no disponible: configure registry_uri sqlite/http para registrar."
    ]

    fake = _FakeMLflow()
    recorder = TrackingRecorder(
        TrackingConfig(
            registry_uri="sqlite:///registry.db",
            registered_model_name="scorecard",
            log_study_artifacts=False,
        ),
        mlflow_module=fake,
    )
    ref = recorder.register_model(
        "runs:/run/model",
        tags={"nikodym.config_hash": "cfg123"},
    )
    recorder.log_study_dir(".")
    recorder.snapshot_study(_study())

    assert ref is not None
    assert ref.name == "scorecard"
    assert ref.version == "3"
    assert ref.config_hash == "cfg123"
    assert ("register_model", ("runs:/run/model", "scorecard")) in fake.calls
    assert (
        "set_model_version_tag",
        ("scorecard", "3", "nikodym.config_hash", "cfg123"),
    ) in fake.calls
    assert not [call for call in fake.calls if call[0] == "log_artifacts"]


def test_recorder_register_model_default_name_desde_study() -> None:
    """Si el recorder vio un Study, el nombre por defecto viene de ``config.name``."""
    fake = _FakeMLflow()
    recorder = TrackingRecorder(
        TrackingConfig(registry_uri="sqlite:///registry.db"),
        mlflow_module=fake,
    )
    recorder.start_run(_study())

    ref = recorder.register_model("runs:/run/model")

    assert ref is not None
    assert ref.name == "riesgo"
    assert ("register_model", ("runs:/run/model", "riesgo")) in fake.calls


def test_recorder_flatten_config_serializa_listas_y_dicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El aplanado convierte listas/dicts computacionales a JSON compacto."""
    monkeypatch.setattr(_schema_mod, "_DATA_CONFIG_CLS", None)
    fake = _FakeMLflow()
    recorder = TrackingRecorder(TrackingConfig(), mlflow_module=fake)
    cfg = NikodymConfig(
        run=RunConfig(steps=["data"]),
        data={"load": {"source": "clientes.parquet", "cols": ["a", "b"]}},
    )

    recorder.log_config(cfg)

    params = next(value for name, value in fake.calls if name == "log_params")
    assert params["cfg.run.steps"] == '["data"]'
    assert params["cfg.data.load.cols"] == '["a","b"]'


def test_recorder_start_run_reusado_y_timestamp_helpers() -> None:
    """Ramas restantes del start interno y normalización de timestamp quedan cubiertas."""
    fake = _FakeMLflow()
    recorder = TrackingRecorder(TrackingConfig(), mlflow_module=fake)
    study = _study()

    first = recorder.start_run(study)
    second = recorder.start_run(study)

    from nikodym.tracking import recorder as recorder_mod

    assert second == first
    assert fake.started == 1
    assert recorder_mod._version_timestamp(_TS) == _TS
    assert recorder_mod._version_timestamp(None) == datetime.fromtimestamp(0, UTC)


def test_recorder_enabled_false_es_noop_sin_mlflow() -> None:
    """``enabled=False`` devuelve handle vacío y no toca MLflow."""
    recorder = TrackingRecorder(TrackingConfig(enabled=False))

    handle = recorder.ensure_run(run_name="no-op")
    recorder.log_config(NikodymConfig())
    recorder.log_metrics({"metrics": {"auc": 0.8}})
    recorder.end_run()

    assert handle.run_id == ""
    assert handle.tracking_uri == "./mlruns"


def test_recorder_degrada_error_a_warning_o_trackingerror() -> None:
    """Por defecto MLflow no tumba cálculo; con fail_on_tracking_error sí falla ruidoso."""
    warnings: list[str] = []
    recorder = TrackingRecorder(
        TrackingConfig(),
        mlflow_module=_BrokenMLflow(),
        warning_sink=warnings.append,
    )

    handle = recorder.ensure_run(run_name="degrada")
    assert handle.run_id == ""
    assert warnings == ["No se pudo abrir run MLflow: servidor caído"]

    estricto = TrackingRecorder(
        TrackingConfig(fail_on_tracking_error=True),
        mlflow_module=_BrokenMLflow(),
    )
    with pytest.raises(TrackingError, match="abrir run MLflow"):
        estricto.ensure_run(run_name="estricto")


def test_recorder_mlflow_ausente_degrada_o_falla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La ausencia del extra tracking se maneja dentro del import perezoso."""

    def missing(extra: str, *modules: str) -> tuple[Any, ...]:
        raise MissingDependencyError("falta mlflow")

    monkeypatch.setattr("nikodym.tracking.recorder.require_extra", missing)
    warnings: list[str] = []

    recorder = TrackingRecorder(TrackingConfig(), warning_sink=warnings.append)
    recorder.ensure_run(run_name="sin-extra")
    assert warnings == ["abrir run MLflow requiere el extra tracking: instala `nikodym[tracking]`."]

    estricto = TrackingRecorder(TrackingConfig(fail_on_tracking_error=True))
    with pytest.raises(TrackingError, match="requiere el extra tracking"):
        estricto.ensure_run(run_name="sin-extra")


def test_tracking_sink_refleja_eventos_y_cierra_run(tmp_path: Path) -> None:
    """El sink implementa ``AuditSink`` y acumula decisiones como artefacto JSONL."""
    fake = _FakeMLflow()
    study = _study()
    recorder = TrackingRecorder(TrackingConfig(), mlflow_module=fake)
    sink = TrackingSink(recorder, study=study)
    artifact = tmp_path / "artefacto.txt"
    artifact.write_text("x", encoding="utf-8")

    sink.emit(AuditEvent(kind="run_start", step=None, payload={"name": "scorecard"}, ts=_TS))
    sink.emit(
        AuditEvent(
            kind="decision",
            step="binning",
            payload={"regla": "iv_min", "umbral": 0.02, "valor": 0.01, "accion": "descartar"},
            ts=_TS,
        )
    )
    sink.emit(AuditEvent(kind="artifact", step="data", payload={"path": str(artifact)}, ts=_TS))
    sink.emit(AuditEvent(kind="run_end", step=None, payload={"status": "done"}, ts=_TS))

    assert ("start_run", "scorecard") in fake.calls
    assert ("log_metric", ("nikodym.run_started", 1.0, None)) in fake.calls
    assert ("log_metric", ("nikodym.n_decisions", 1.0, None)) in fake.calls
    assert ("log_artifact", ("artefacto.txt", "artifacts")) in fake.calls
    assert ("log_artifact", ("decisions.jsonl", "audit")) in fake.calls
    assert ("end_run", "FINISHED") in fake.calls


def test_tracking_sink_run_end_failed_sin_study() -> None:
    """Sin Study ligado, el sink igual cierra el run y evita ramas de snapshot."""
    fake = _FakeMLflow()
    sink = TrackingSink(TrackingRecorder(TrackingConfig(), mlflow_module=fake))

    sink.emit(AuditEvent(kind="run_start", step=None, payload={}, ts=_TS))
    sink.emit(AuditEvent(kind="artifact", step="data", payload={"path": 123}, ts=_TS))
    sink.emit(AuditEvent(kind="run_end", step=None, payload={"status": "failed"}, ts=_TS))

    assert ("end_run", "FAILED") in fake.calls


def test_tracking_sink_run_end_sin_lineage_y_evento_desconocido() -> None:
    """Ramas sin lineage y evento no estándar son no-op seguros."""
    fake = _FakeMLflow()
    study = Study(NikodymConfig())
    study.run_context.status = "done"
    study.results["metrics"] = {"auc": 0.5}
    sink = TrackingSink(TrackingRecorder(TrackingConfig(), mlflow_module=fake), study=study)

    sink.emit(AuditEvent(kind="run_start", step=None, payload={}, ts=_TS))
    sink.emit(AuditEvent(kind="run_end", step=None, payload={"status": "done"}, ts=_TS))
    sink.emit(SimpleNamespace(kind="otro", payload={}, model_dump=lambda mode: {}))  # type: ignore[arg-type]

    assert ("log_metric", ("auc", 0.5, None)) in fake.calls
