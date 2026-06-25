"""Tests de ``TrackingConfig`` y su cableado diferido en ``NikodymConfig``."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

import nikodym.tracking
from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.config import schema as _schema_mod
from nikodym.governance import RegistryUnavailableError
from nikodym.tracking import (
    MLflowInventory,
    ModelNotFoundError,
    RunHandle,
    TrackingConfig,
    TrackingError,
    TrackingRecorder,
    TrackingSink,
)


def test_tracking_public_api_reexporta_superficie() -> None:
    """El paquete ``tracking`` publica la superficie mínima definida por SDD-04."""
    assert nikodym.tracking.TrackingConfig is TrackingConfig
    assert nikodym.tracking.TrackingRecorder is TrackingRecorder
    assert nikodym.tracking.TrackingSink is TrackingSink
    assert nikodym.tracking.MLflowInventory is MLflowInventory
    assert nikodym.tracking.RunHandle is RunHandle
    assert issubclass(TrackingError, Exception)
    assert issubclass(ModelNotFoundError, TrackingError)
    assert nikodym.tracking.RegistryUnavailableError is RegistryUnavailableError


def test_tracking_config_defaults_y_titles() -> None:
    """Defaults defendibles y metadatos UI quedan declarados en el sub-config."""
    cfg = TrackingConfig()

    assert cfg.enabled is True
    assert cfg.tracking_uri is None
    assert cfg.registry_uri is None
    assert cfg.experiment_name is None
    assert cfg.registered_model_name is None
    assert cfg.register_on_success is False
    assert cfg.autolog is False
    assert cfg.log_study_artifacts is True
    assert cfg.log_models is True
    assert cfg.fail_on_tracking_error is False
    for nombre, campo in TrackingConfig.model_fields.items():
        assert campo.title is not None, f"TrackingConfig.{nombre} sin title"
        assert campo.description is not None, f"TrackingConfig.{nombre} sin description"


def test_nikodymconfig_tracking_instancia_y_dict_coaccionan() -> None:
    """Con ``nikodym.tracking`` importado, ``tracking`` se valida como config real."""
    tracking_cfg = TrackingConfig(tracking_uri="file:///tmp/mlruns", autolog=True)
    cfg = NikodymConfig(tracking=tracking_cfg)
    assert isinstance(cfg.tracking, TrackingConfig)
    assert cfg.tracking is tracking_cfg

    desde_dict = NikodymConfig(
        tracking={
            "enabled": True,
            "tracking_uri": "sqlite:///runs.db",
            "registry_uri": "sqlite:///registry.db",
            "experiment_name": "riesgo",
            "registered_model_name": "scorecard",
            "fail_on_tracking_error": True,
        }
    )
    assert isinstance(desde_dict.tracking, TrackingConfig)
    assert desde_dict.tracking.registry_uri == "sqlite:///registry.db"
    assert desde_dict.tracking.fail_on_tracking_error is True


def test_nikodymconfig_tracking_extra_forbid() -> None:
    """Un typo dentro de ``tracking`` se rechaza cuando el hook está poblado."""
    with pytest.raises(ValidationError):
        NikodymConfig(tracking={"enabled": True, "typo": 1})


def test_nikodymconfig_tracking_core_only_blob_y_rechazo_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook, ``tracking`` es blob JSON-canónico; valores no deterministas se rechazan."""
    monkeypatch.setattr(_schema_mod, "_TRACKING_CONFIG_CLS", None)

    cfg = NikodymConfig(tracking={"enabled": False})
    assert cfg.tracking == {"enabled": False}

    with pytest.raises(ValidationError, match="tracking debe ser JSON-canónico"):
        NikodymConfig(tracking={"x": {1, 2, 3}})


def test_config_hash_excluye_tracking_por_ser_infraestructura() -> None:
    """Cambiar destino de tracking no altera la identidad del experimento."""
    base = config_hash(NikodymConfig())
    con_a = config_hash(NikodymConfig(tracking=TrackingConfig(tracking_uri="file:///a")))
    con_b = config_hash(
        NikodymConfig(
            tracking=TrackingConfig(
                tracking_uri="sqlite:///b.db",
                registry_uri="sqlite:///registry.db",
                registered_model_name="otro",
            )
        )
    )

    assert con_a == base
    assert con_b == base


def test_import_core_no_arrastra_tracking_ni_mlflow() -> None:
    """El gate liviano se preserva en un proceso fresco."""
    code = (
        "import nikodym.core, sys;"
        "mods=('nikodym.tracking','mlflow','nikodym.data','pandera','pyarrow','pandas');"
        "assert not [m for m in mods if m in sys.modules]"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
