"""Tests del import perezoso de extras (SDD-25 §4, §11)."""

import tomllib
from pathlib import Path

import pytest

from nikodym.core.exceptions import MissingDependencyError
from nikodym.utils import optional

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


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


def test_extra_map_keys_son_extras_reales_del_pyproject() -> None:
    """Toda clave del mapa es un extra de usuario declarado en el pyproject (sin claves fantasma).

    Nota: la relación es ⊆, no biyección exacta: ``ai``/``report`` viven en el pyproject pero no
    gatean vía ``require_extra`` (sus imports son perezosos en otras capas), por lo que no tienen
    fila en el mapa. Esa asimetría es pre-existente a B23.2 y ortogonal a la migración de ``ui``.
    """
    with _PYPROJECT.open("rb") as handle:
        pyproject = tomllib.load(handle)
    extras = set(pyproject["project"]["optional-dependencies"]) - {"all"}
    assert set(optional.EXTRA_TO_DISTRIBUTIONS) <= extras
    assert "ui" in extras and "ui" in optional.EXTRA_TO_DISTRIBUTIONS


def test_extra_ui_mapea_a_fastapi_y_uvicorn() -> None:
    """El extra ``ui`` (SDD-23, B23.2) resuelve los módulos ``fastapi`` y ``uvicorn``."""
    assert optional.EXTRA_TO_DISTRIBUTIONS["ui"] == ("fastapi", "uvicorn")
