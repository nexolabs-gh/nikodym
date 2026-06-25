"""Tests de fixtures programáticas públicas de ``nikodym.testing``."""

from __future__ import annotations

import numpy as np
import pytest

from nikodym.core.config import NikodymConfig
from nikodym.core.registry import REGISTRY
from nikodym.core.seeding import SeedManager
from nikodym.core.steps import Step
from nikodym.core.study import Study
from nikodym.testing import dummy_step_config, golden_seed_sequence, minimal_study
from nikodym.testing.fixtures import _ensure_dummy_step_registered


def test_minimal_study_es_study_con_config_por_defecto() -> None:
    """``minimal_study`` materializa el DoD F0: ``Study(NikodymConfig())``."""
    study = minimal_study()
    assert isinstance(study, Study)
    assert study.config == NikodymConfig()
    assert study.seed_manager.root_seed == 42


def test_dummy_step_config_registra_step_dummy_idempotente() -> None:
    """El helper registra un Step dummy reutilizable sin duplicar entradas."""
    cfg = dummy_step_config()
    again = dummy_step_config()
    assert cfg.name == "nikodym-dummy-step"
    assert cfg.run.steps == []
    assert again == cfg
    assert REGISTRY.available("testing") == ["dummy"]


def test_dummy_step_resuelto_ejecuta_y_publica_valor_dorado() -> None:
    """El Step dummy consume el ``rng`` inyectado y escribe un artefacto reproducible."""
    dummy_step_config()
    step_cls = REGISTRY.resolve("testing", "dummy")
    step = step_cls.from_config(None)
    assert isinstance(step, Step)
    study = minimal_study()
    value = step.execute(study, SeedManager(42).generator_for("testing"))
    assert value == 1520688771
    assert study.artifacts.get("testing", "dummy_value") == 1520688771


def test_golden_seed_sequence_devuelve_valores_exactos() -> None:
    """La secuencia pública coincide con los golden values de ``SeedManager(42)``."""
    assert golden_seed_sequence("binning", 5) == [
        35866044,
        1925873718,
        1338300275,
        1612367033,
        1074782850,
    ]
    assert golden_seed_sequence("selection", 3) == [1742200289, 883286722, 821234755]
    assert golden_seed_sequence("binning", 0) == []


def test_golden_seed_sequence_rechaza_n_negativo() -> None:
    """Un tamaño negativo falla con mensaje explícito."""
    with pytest.raises(ValueError, match="n debe ser >= 0"):
        golden_seed_sequence("binning", -1)


def test_golden_seed_sequence_equivale_a_seed_manager() -> None:
    """El helper usa el mismo rango entero que los golden canónicos."""
    expected = SeedManager(42).generator_for("testing").integers(0, 2**31, size=4).tolist()
    assert golden_seed_sequence("testing", 4) == [int(value) for value in expected]


def test_dummy_step_overwrite_permite_re_ejecutar() -> None:
    """El Step dummy usa ``overwrite=True`` para ser estable en tests repetidos."""
    dummy_step_config()
    step = REGISTRY.resolve("testing", "dummy").from_config(None)
    study = minimal_study()
    first = step.execute(study, np.random.default_rng(0))
    second = step.execute(study, np.random.default_rng(0))
    assert first == second
    assert study.artifacts.get("testing", "dummy_value") == first


def test_dummy_step_config_falla_si_registro_apunta_a_componente_invalido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La defensa detecta drift si el registro ``testing/dummy`` apunta a algo no-Step."""
    monkeypatch.setitem(REGISTRY._registry, ("testing", "dummy"), object)
    with pytest.raises(AssertionError, match="no satisface"):
        _ensure_dummy_step_registered()
