"""Tests de la superficie pública del config: __all__ consistente y reexport desde nikodym.core."""

import pytest

from nikodym import core
from nikodym.core import config
from nikodym.core.seeding import SeedManager
from nikodym.core.study import Study


def test_all_names_existen() -> None:
    """Cada nombre de nikodym.core.config.__all__ existe y es importable."""
    for nombre in config.__all__:
        assert hasattr(config, nombre), f"{nombre} declarado en __all__ pero ausente"


def test_reexport_desde_core_es_el_mismo_objeto() -> None:
    """nikodym.core reexporta la superficie del config (mismos objetos)."""
    assert core.NikodymConfig is config.NikodymConfig
    assert core.config_hash is config.config_hash
    assert core.load_config is config.load_config
    assert core.INFRA_SECTIONS is config.INFRA_SECTIONS


def test_core_exports_stateful_lazy_en_proceso(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SeedManager`` y ``Study`` se reexportan bajo demanda desde ``nikodym.core``."""
    seed_manager_attr = "SeedManager"
    study_attr = "Study"
    unknown_attr = "NoExiste"

    monkeypatch.delattr(core, seed_manager_attr, raising=False)
    monkeypatch.delattr(core, study_attr, raising=False)

    assert getattr(core, seed_manager_attr) is SeedManager
    assert getattr(core, study_attr) is Study
    assert core.SeedManager is SeedManager
    assert core.Study is Study

    with pytest.raises(AttributeError, match=unknown_attr):
        getattr(core, unknown_attr)
