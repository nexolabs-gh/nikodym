"""Tests de la superficie pública del config: __all__ consistente y reexport desde nikodym.core."""

from nikodym import core
from nikodym.core import config


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
