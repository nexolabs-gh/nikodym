"""Golden del config_hash (SDD-01 §5, §11): congela la identidad del config por defecto.

Un cambio en este valor señala una ruptura de la canonicalización (orden de claves, serialización,
secciones excluidas) que invalidaría la idempotencia del inventario de modelos entre releases.
Recalcular y actualizar el golden SOLO de forma deliberada y documentada.
"""

import os
import subprocess
import sys

import pytest

from nikodym.core.config import NikodymConfig, ReproConfig, config_hash

# Identidad SHA-256 de NikodymConfig() por defecto (sin INFRA_SECTIONS). Congelado a mano.
GOLDEN_DEFAULT_CONFIG_HASH = "02b667fc7421ceb14fa7c72f9897d8e16a66fb7e8cba116d1336677b32582175"


def _hash_en_subproceso(hashseed: str) -> str:
    """Calcula config_hash(NikodymConfig()) en un proceso fresco con PYTHONHASHSEED dado."""
    codigo = (
        "from nikodym.core.config import NikodymConfig, config_hash;"
        "print(config_hash(NikodymConfig()))"
    )
    salida = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": hashseed},
    )
    return salida.stdout.strip()


def test_config_hash_default_congelado() -> None:
    """El hash del config por defecto coincide con el golden (estabilidad cross-release)."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_config_hash_estable_bajo_reordenamiento() -> None:
    """Configs equivalentes con kwargs en distinto orden producen el mismo hash."""
    uno = NikodymConfig(name="a", repro=ReproConfig(seed=7))
    dos = NikodymConfig(repro=ReproConfig(seed=7), name="a")
    assert config_hash(uno) == config_hash(dos)


@pytest.mark.parametrize("hashseed", ["0", "1", "random"])
def test_config_hash_determinista_cross_proceso(hashseed: str) -> None:
    """El hash del config por defecto es estable entre procesos con distinto PYTHONHASHSEED."""
    assert _hash_en_subproceso(hashseed) == GOLDEN_DEFAULT_CONFIG_HASH
