"""Fixtures raíz de la suite de tests de Nikodym."""

import pytest

from nikodym.core.seeding import SeedManager


@pytest.fixture(autouse=True)
def _pythonhashseed_fijo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fija ``PYTHONHASHSEED`` para toda la suite.

    ``SeedManager.apply_global`` (que ``Study.__init__`` invoca) advierte si ``PYTHONHASHSEED`` no
    está fijo; con ``filterwarnings=error`` ese aviso rompería cualquier test que construya un
    ``Study``. Fijarlo aquí cubre todo el suite (no solo un módulo); los tests de seeding que
    prueban el aviso lo sobrescriben con ``monkeypatch.delenv`` en su propio cuerpo.
    """
    monkeypatch.setenv("PYTHONHASHSEED", "0")


@pytest.fixture
def seed_manager() -> SeedManager:
    """``SeedManager`` con la semilla por defecto del proyecto (42)."""
    return SeedManager(42)
