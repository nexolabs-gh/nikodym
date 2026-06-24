"""Fixtures raíz de la suite de tests de Nikodym."""

import pytest

from nikodym.core.seeding import SeedManager


@pytest.fixture
def seed_manager() -> SeedManager:
    """``SeedManager`` con la semilla por defecto del proyecto (42)."""
    return SeedManager(42)
