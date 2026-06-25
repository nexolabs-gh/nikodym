"""Tests de ``AuditConfig`` y su cableado diferido en ``NikodymConfig``."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

import nikodym.audit
from nikodym.audit import AuditConfig, AuditError, JsonlAuditSink
from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.config import schema as _schema_mod


def test_audit_public_api_reexporta_superficie() -> None:
    """El paquete ``audit`` publica la superficie mínima definida por SDD-03."""
    assert nikodym.audit.AuditConfig is AuditConfig
    assert nikodym.audit.AuditError is AuditError
    assert nikodym.audit.JsonlAuditSink is JsonlAuditSink
    assert "read_trail" in nikodym.audit.__all__


def test_audit_config_defaults_y_titles() -> None:
    """Defaults defendibles y metadatos UI quedan declarados en el sub-config."""
    cfg = AuditConfig()

    assert cfg.enabled is True
    assert cfg.trail_filename == "audit_trail.jsonl"
    assert cfg.flush_each is True
    assert cfg.capture_environment is True
    assert cfg.tracked_packages is None
    for nombre, campo in AuditConfig.model_fields.items():
        assert campo.title is not None, f"AuditConfig.{nombre} sin title"
        assert campo.description is not None, f"AuditConfig.{nombre} sin description"


def test_nikodymconfig_audit_instancia_y_dict_coaccionan() -> None:
    """Con ``nikodym.audit`` importado, ``audit`` se valida como ``AuditConfig`` real."""
    audit_cfg = AuditConfig(flush_each=False)
    cfg = NikodymConfig(audit=audit_cfg)
    assert isinstance(cfg.audit, AuditConfig)
    assert cfg.audit is audit_cfg

    desde_dict = NikodymConfig(
        audit={"flush_each": False, "tracked_packages": ["nikodym", "pydantic"]}
    )
    assert isinstance(desde_dict.audit, AuditConfig)
    assert desde_dict.audit.flush_each is False
    assert desde_dict.audit.tracked_packages == ("nikodym", "pydantic")


def test_nikodymconfig_audit_extra_forbid() -> None:
    """Un typo dentro de ``audit`` se rechaza cuando el hook está poblado."""
    with pytest.raises(ValidationError):
        NikodymConfig(audit={"flush_each": False, "typo": 1})


def test_nikodymconfig_audit_core_only_blob_y_rechazo_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook, ``audit`` es blob JSON-canónico; valores no deterministas se rechazan."""
    monkeypatch.setattr(_schema_mod, "_AUDIT_CONFIG_CLS", None)

    cfg = NikodymConfig(audit={"enabled": False})
    assert cfg.audit == {"enabled": False}

    with pytest.raises(ValidationError, match="audit debe ser JSON-canónico"):
        NikodymConfig(audit={"x": {1, 2, 3}})


def test_config_hash_excluye_audit_por_ser_infraestructura() -> None:
    """Cambiar política de auditoría no altera la identidad del experimento."""
    base = config_hash(NikodymConfig())
    con_trail_a = config_hash(NikodymConfig(audit=AuditConfig(trail_filename="a.jsonl")))
    con_trail_b = config_hash(NikodymConfig(audit=AuditConfig(trail_filename="b.jsonl")))

    assert con_trail_a == base
    assert con_trail_b == base


def test_import_core_no_arrastra_audit_ni_stack_tabular() -> None:
    """El gate liviano se preserva en un proceso fresco."""
    code = (
        "import nikodym.core, sys;"
        "mods=('nikodym.audit','nikodym.data','pandera','pyarrow','pandas');"
        "assert not [m for m in mods if m in sys.modules]"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
