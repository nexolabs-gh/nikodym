"""Tests de ``UiConfig`` (SDD-23 §4.3, §5b, D-UI-3).

Verifica la forma exacta del modelo de ajustes de la app y la regla dura D-UI-3: ``UiConfig`` no
es una sección de ``NikodymConfig`` y no entra al ``config_hash``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nikodym.core.config import INFRA_SECTIONS, NikodymConfig, ReproConfig, config_hash
from nikodym.ui.settings import UiConfig


def test_uiconfig_defaults_y_cotas() -> None:
    """Los defaults y cotas coinciden con §4.3."""
    cfg = UiConfig()
    assert cfg.deploy_mode == "local"
    assert cfg.theme == "auto"
    assert cfg.upload_max_mb == 200
    assert cfg.workdir == ".nikodym_ui"
    assert cfg.exposed_sections == ()
    assert cfg.allow_live_execution is True


def test_uiconfig_valida_literales_y_rango() -> None:
    """Valores fuera de los ``Literal``/cotas fallan (validación de Pydantic, no reimplementada)."""
    with pytest.raises(ValidationError):
        UiConfig(deploy_mode="produccion")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        UiConfig(theme="neon")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        UiConfig(upload_max_mb=0)
    with pytest.raises(ValidationError):
        UiConfig(upload_max_mb=4096)


def test_uiconfig_frozen_y_extra_forbid() -> None:
    """Hereda de ``NikodymBaseConfig``: inmutable y cerrado a campos desconocidos."""
    cfg = UiConfig()
    with pytest.raises(ValidationError):
        cfg.theme = "dark"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        UiConfig(campo_inexistente=1)  # type: ignore[call-arg]


def test_ui_no_es_seccion_de_nikodymconfig() -> None:
    """D-UI-3: no hay campo ``ui`` en ``NikodymConfig`` ni en las secciones de infraestructura."""
    assert "ui" not in NikodymConfig.model_fields
    assert "ui" not in INFRA_SECTIONS


def test_uiconfig_fuera_del_config_hash() -> None:
    """D-UI-3: cambiar tema/modo/workdir NO altera el ``config_hash`` de ningún experimento."""
    experimento = NikodymConfig(repro=ReproConfig(seed=7))
    hash_referencia = config_hash(experimento)
    for ajustes in (
        UiConfig(theme="dark"),
        UiConfig(deploy_mode="demo"),
        UiConfig(workdir="/otro/dir"),
        UiConfig(allow_live_execution=False),
    ):
        assert isinstance(ajustes, UiConfig)  # los ajustes existen pero son ortogonales
        assert config_hash(experimento) == hash_referencia
