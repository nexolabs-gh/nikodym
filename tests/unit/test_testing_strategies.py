"""Tests de estrategias Hypothesis públicas de ``nikodym.testing``."""

from __future__ import annotations

import subprocess
import sys
from types import ModuleType
from typing import Literal

import pytest
from hypothesis import given, settings

from nikodym.core.config import NikodymConfig
from nikodym.core.config import schema as core_schema
from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.testing.strategies import (
    _config_cls_for_domain,
    _literal_tags,
    discriminated_union_tags,
    nikodym_config_strategy,
)


def test_import_nikodym_testing_no_importa_hypothesis_en_proceso_fresco() -> None:
    """La API pública no arrastra Hypothesis hasta usar estrategias."""
    code = "import nikodym.testing, sys;assert 'hypothesis' not in sys.modules, sorted(sys.modules)"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_nikodym_config_strategy_exige_hypothesis_perezoso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si falta Hypothesis, el error explica que es dependencia de entorno de test."""
    import nikodym.testing.strategies as strategies

    real_import = strategies.importlib.import_module

    def fake_import(name: str) -> ModuleType:
        if name == "hypothesis.strategies":
            raise ImportError(name)
        module = real_import(name)
        assert isinstance(module, ModuleType)
        return module

    monkeypatch.setattr(strategies.importlib, "import_module", fake_import)
    with pytest.raises(MissingDependencyError, match="pip install hypothesis"):
        strategies.nikodym_config_strategy()


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy())
def test_nikodym_config_strategy_genera_configs_core_validos(cfg: NikodymConfig) -> None:
    """La estrategia base genera configs raíz válidos y cerrados."""
    assert isinstance(cfg, NikodymConfig)
    assert cfg.data is None
    assert cfg.run.steps is None


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["data"], require_data=True))
def test_nikodym_config_strategy_genera_configs_data_validos(cfg: NikodymConfig) -> None:
    """Con ``require_data=True`` la sección ``data`` se valida por su hook real."""
    from nikodym.data.config import DataConfig

    assert isinstance(cfg.data, DataConfig)
    assert cfg.data.type == "standard"


def test_nikodym_config_strategy_rechaza_secciones_desconocidas() -> None:
    """Una sección fuera del F0 soportado falla ruidoso."""
    with pytest.raises(ValueError, match="Secciones no soportadas"):
        nikodym_config_strategy(sections=["scoring"])


def test_discriminated_union_tags_cruza_data_con_registry() -> None:
    """El tag de sección ``data`` coincide con el ``REGISTRY`` global."""
    tags = discriminated_union_tags()
    assert tags == {"data": ["standard"]}
    assert set(tags["data"]) == set(REGISTRY.available("data"))


def test_literal_tags_devuelve_vacio_para_anotacion_no_literal() -> None:
    """Las anotaciones no ``Literal`` no se interpretan como discriminadores."""
    assert _literal_tags(int) == []
    assert _literal_tags(Literal["a", "b", 1]) == ["a", "b"]


def test_config_cls_for_domain_falla_si_hook_no_esta_cargado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El cruce anti-drift falla ruidoso si la sección no pobló el hook diferido."""
    monkeypatch.setattr(core_schema, "_DATA_CONFIG_CLS", None)
    with pytest.raises(AssertionError, match="No hay config_cls"):
        _config_cls_for_domain("data")
