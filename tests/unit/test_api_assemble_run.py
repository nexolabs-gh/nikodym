"""Tests de ``nikodym.api.assemble_run`` (CT-4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from nikodym.api import assemble_run
from nikodym.audit import AuditConfig, JsonlAuditSink
from nikodym.core.audit import FanOutSink, NullAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import MissingDependencyError
from nikodym.governance import GovernanceConfig, NullInventory
from nikodym.tracking import MLflowInventory, TrackingConfig, TrackingSink


def test_assemble_run_sin_infra_devuelve_noops() -> None:
    """Sin secciones infra explícitas, ``core`` recibe no-ops conscientes."""
    sink, inventory = assemble_run(NikodymConfig())

    assert isinstance(sink, NullAuditSink)
    assert isinstance(inventory, NullInventory)


def test_assemble_run_compone_audit_y_tracking_en_fanout(tmp_path, monkeypatch) -> None:
    """Audit JSONL y tracking comparten el hook único mediante ``FanOutSink``."""
    monkeypatch.chdir(tmp_path)
    cfg = NikodymConfig(
        audit=AuditConfig(trail_filename="audit.jsonl"),
        tracking=TrackingConfig(tracking_uri="file:///tmp/mlruns"),
    )

    sink, inventory = assemble_run(cfg)

    assert isinstance(sink, FanOutSink)
    assert [type(item) for item in sink.sinks] == [JsonlAuditSink, TrackingSink]
    assert isinstance(inventory, NullInventory)
    sink.emit(
        __import__("nikodym.core.audit", fromlist=["AuditEvent"]).AuditEvent(
            kind="run_end",
            step=None,
            payload={"status": "done"},
            ts=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
    )
    sink.sinks[0].close()


def test_assemble_run_secciones_disabled_caen_a_null() -> None:
    """``enabled=False`` desactiva sinks sin tocar el inventario no-op."""
    sink, inventory = assemble_run(
        NikodymConfig(
            audit=AuditConfig(enabled=False),
            tracking=TrackingConfig(enabled=False),
        )
    )

    assert isinstance(sink, NullAuditSink)
    assert isinstance(inventory, NullInventory)


def test_assemble_run_publish_true_sin_extra_falla_ruidoso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una petición explícita de publicar no cae a ``NullInventory`` si falta MLflow."""

    def missing(extra: str, *modules: str) -> tuple[Any, ...]:
        raise MissingDependencyError("falta mlflow")

    monkeypatch.setattr("nikodym.api.require_extra", missing)
    cfg = NikodymConfig(
        governance=GovernanceConfig(
            purpose="Scorecard",
            publish_to_inventory=True,
        )
    )

    with pytest.raises(MissingDependencyError, match="falta mlflow"):
        assemble_run(cfg)


def test_assemble_run_publish_true_resuelve_mlflow_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con extra disponible, la publicación usa ``MLflowInventory``."""

    def available(extra: str, *modules: str) -> tuple[Any, ...]:
        return (object(),)

    monkeypatch.setattr("nikodym.api.require_extra", available)
    cfg = NikodymConfig(
        governance={
            "purpose": "Scorecard",
            "publish_to_inventory": True,
        },
        tracking={
            "registry_uri": "sqlite:///registry.db",
        },
    )

    sink, inventory = assemble_run(cfg)

    assert isinstance(sink, TrackingSink)
    assert isinstance(inventory, MLflowInventory)
    assert inventory.config.registry_uri == "sqlite:///registry.db"


def test_assemble_run_coacciona_blobs_core_only(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """La API revalida blobs creados antes de importar las capas infra."""

    def available(extra: str, *modules: str) -> tuple[Any, ...]:
        return (object(),)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_schema_mod, "_AUDIT_CONFIG_CLS", None)
    monkeypatch.setattr(_schema_mod, "_GOVERNANCE_CONFIG_CLS", None)
    monkeypatch.setattr(_schema_mod, "_TRACKING_CONFIG_CLS", None)
    monkeypatch.setattr("nikodym.api.require_extra", available)
    cfg = NikodymConfig(
        audit={"trail_filename": "audit.jsonl"},
        governance={"purpose": "Scorecard", "publish_to_inventory": True},
        tracking={"registry_uri": "sqlite:///registry.db"},
    )

    sink, inventory = assemble_run(cfg)

    assert isinstance(sink, FanOutSink)
    assert isinstance(inventory, MLflowInventory)
    sink.emit(
        __import__("nikodym.core.audit", fromlist=["AuditEvent"]).AuditEvent(
            kind="run_end",
            step=None,
            payload={"status": "done"},
            ts=datetime.now(UTC),
        )
    )
    sink.sinks[0].close()
