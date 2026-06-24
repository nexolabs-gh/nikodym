"""Tests del import perezoso de extras (SDD-25 §4, §11)."""

import pytest

from nikodym.core.exceptions import MissingDependencyError
from nikodym.utils import optional


def test_require_extra_returns_imported_modules() -> None:
    """``require_extra`` devuelve los módulos importados, en orden."""
    json_mod, math_mod = optional.require_extra("base", "json", "math")
    assert json_mod.__name__ == "json"
    assert math_mod.__name__ == "math"


def test_require_extra_missing_raises_with_install_hint() -> None:
    """Un módulo ausente levanta MissingDependencyError con la línea de instalación del extra."""
    with pytest.raises(MissingDependencyError, match=r"nikodym\[xgboost\]"):
        optional.require_extra("xgboost", "modulo_que_no_existe_xyz")


def test_has_extra_true_when_present() -> None:
    """``has_extra`` es True si todos los módulos están importables."""
    assert optional.has_extra("base", "json") is True


def test_has_extra_false_when_absent() -> None:
    """``has_extra`` es False (no levanta) si falta un módulo."""
    assert optional.has_extra("xgboost", "modulo_que_no_existe_xyz") is False


def test_extra_map_keys_are_known_extras() -> None:
    """El mapa de extras cubre los extras de usuario esperados (sin 'all')."""
    assert "all" not in optional.EXTRA_TO_DISTRIBUTIONS
    assert "scoring" in optional.EXTRA_TO_DISTRIBUTIONS
    assert optional.EXTRA_TO_DISTRIBUTIONS["scoring"] == ("optbinning", "statsmodels", "sklearn")
