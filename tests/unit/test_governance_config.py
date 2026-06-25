"""Tests de ``GovernanceConfig`` y su cableado diferido en ``NikodymConfig``."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

import nikodym.governance
from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.config import schema as _schema_mod
from nikodym.governance import (
    GovernanceConfig,
    GovernanceError,
    ModelCardBuilder,
    RegistryUnavailableError,
)


def test_governance_public_api_reexporta_superficie() -> None:
    """El paquete ``governance`` publica la superficie mínima definida por SDD-03."""
    assert nikodym.governance.GovernanceConfig is GovernanceConfig
    assert nikodym.governance.GovernanceError is GovernanceError
    assert nikodym.governance.RegistryUnavailableError is RegistryUnavailableError
    assert nikodym.governance.ModelCardBuilder is ModelCardBuilder
    assert "ModelInventory" in nikodym.governance.__all__


def test_governance_config_purpose_obligatorio_y_defaults() -> None:
    """``purpose`` es la fricción obligatoria SR 11-7; el resto trae defaults defendibles."""
    with pytest.raises(ValidationError):
        GovernanceConfig()

    cfg = GovernanceConfig(purpose="Scorecard comportamiento consumo")

    assert cfg.model_name == "nikodym-model"
    assert cfg.estado_validacion == "desarrollo"
    assert cfg.review_period_months == 12
    assert cfg.publish_to_inventory is False
    assert cfg.scenario_log_filename == "scenario_log.jsonl"
    assert cfg.require_overlay_justification is True
    for nombre, campo in GovernanceConfig.model_fields.items():
        assert campo.title is not None, f"GovernanceConfig.{nombre} sin title"
        assert campo.description is not None, f"GovernanceConfig.{nombre} sin description"


def test_governance_vocabulario_cerrado_levanta() -> None:
    """Los tags descriptivos de inventario usan vocabulario cerrado."""
    with pytest.raises(ValidationError):
        GovernanceConfig(purpose="x", cartera="consumer")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        GovernanceConfig(purpose="x", motor="ifrs")  # type: ignore[arg-type]


def test_nikodymconfig_governance_instancia_y_dict_coaccionan() -> None:
    """Con ``nikodym.governance`` importado, la sección se valida como config real."""
    gov_cfg = GovernanceConfig(purpose="Gobernanza de scorecard", publish_to_inventory=True)
    cfg = NikodymConfig(governance=gov_cfg)
    assert isinstance(cfg.governance, GovernanceConfig)
    assert cfg.governance is gov_cfg

    desde_dict = NikodymConfig(
        governance={
            "purpose": "Scorecard comportamiento",
            "assumptions": ["muestra cerrada"],
            "limitations": ["uso interno"],
            "motor": "scoring",
            "fase": "F1",
            "author": "riesgo@example.com",
        }
    )
    assert isinstance(desde_dict.governance, GovernanceConfig)
    assert desde_dict.governance.assumptions == ("muestra cerrada",)
    assert desde_dict.governance.limitations == ("uso interno",)
    assert desde_dict.governance.motor == "scoring"


def test_nikodymconfig_governance_extra_forbid() -> None:
    """Un typo dentro de ``governance`` se rechaza cuando el hook está poblado."""
    with pytest.raises(ValidationError):
        NikodymConfig(governance={"purpose": "x", "typo": 1})


def test_nikodymconfig_governance_core_only_blob_y_rechazo_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook, ``governance`` es blob JSON-canónico; valores no deterministas se rechazan."""
    monkeypatch.setattr(_schema_mod, "_GOVERNANCE_CONFIG_CLS", None)

    cfg = NikodymConfig(governance={"purpose": "documentar"})
    assert cfg.governance == {"purpose": "documentar"}

    with pytest.raises(ValidationError, match="governance debe ser JSON-canónico"):
        NikodymConfig(governance={"x": {1, 2, 3}})


def test_config_hash_excluye_governance_por_ser_infraestructura() -> None:
    """Cambiar gobernanza/documentación no altera la identidad del experimento."""
    base = config_hash(NikodymConfig())
    con_a = config_hash(NikodymConfig(governance=GovernanceConfig(purpose="A")))
    con_b = config_hash(
        NikodymConfig(
            governance=GovernanceConfig(
                purpose="B",
                publish_to_inventory=True,
                model_name="otro-modelo",
            )
        )
    )

    assert con_a == base
    assert con_b == base


def test_registry_unavailable_desciende_de_governance_error() -> None:
    """La excepción de Registry pertenece al contrato de governance."""
    assert issubclass(RegistryUnavailableError, GovernanceError)


def test_import_core_no_arrastra_governance_ni_stack_tabular() -> None:
    """El gate liviano se preserva en un proceso fresco."""
    code = (
        "import nikodym.core, sys;"
        "mods=('nikodym.governance','nikodym.audit','nikodym.data','pandera','pyarrow','pandas');"
        "assert not [m for m in mods if m in sys.modules]"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
