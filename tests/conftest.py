"""Fixtures raíz de la suite de tests de Nikodym."""

import os

import pytest
from hypothesis import settings

from nikodym.core.seeding import SeedManager

settings.register_profile("dev", max_examples=50, deadline=None)
settings.register_profile(
    "ci",
    derandomize=True,
    max_examples=200,
    deadline=None,
    print_blob=True,
)
settings.register_profile(
    "nikodym_deterministic",
    derandomize=True,
    max_examples=25,
    deadline=None,
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


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
