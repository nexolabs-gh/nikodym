"""Tests de config_hash (SDD-01 §5): determinismo, exclusión de INFRA_SECTIONS, sensibilidad."""

from nikodym.core.config import INFRA_SECTIONS, NikodymConfig, ReproConfig, config_hash


def test_es_hex_sha256() -> None:
    """El hash es un string hexadecimal SHA-256 de 64 caracteres."""
    digest = config_hash(NikodymConfig())
    assert isinstance(digest, str)
    assert len(digest) == 64
    int(digest, 16)  # no levanta -> es hex válido


def test_determinista() -> None:
    """Dos configs idénticos producen el mismo hash (DoD F0 b)."""
    assert config_hash(NikodymConfig()) == config_hash(NikodymConfig())


def test_excluye_infra_sections() -> None:
    """Cambiar 'name' (en INFRA_SECTIONS) NO cambia el hash (DoD F0 b)."""
    assert config_hash(NikodymConfig(name="alfa")) == config_hash(NikodymConfig(name="beta"))


def test_cambia_con_campo_computacional() -> None:
    """Cambiar repro.seed (sección computacional) SÍ cambia el hash."""
    uno = config_hash(NikodymConfig(repro=ReproConfig(seed=1)))
    dos = config_hash(NikodymConfig(repro=ReproConfig(seed=2)))
    assert uno != dos


def test_infra_sections_contenido_exacto() -> None:
    """INFRA_SECTIONS contiene exactamente las cinco secciones de infraestructura."""
    assert set(INFRA_SECTIONS) == {"name", "governance", "audit", "tracking", "report"}
