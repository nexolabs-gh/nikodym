"""Tests de ``assert_bitwise_reproducible``."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from nikodym.testing import assert_bitwise_reproducible


def test_assert_bitwise_reproducible_acepta_resultado_estable() -> None:
    """Dos resultados idénticos pasan por comparación byte a byte."""
    assert_bitwise_reproducible(lambda: {"score": [1, 2, 3], "signed_zero": -0.0})


def test_assert_bitwise_reproducible_detecta_no_reproducible() -> None:
    """Una corrida que cambia entre llamadas falla ruidosamente."""
    counter = itertools.count()

    with pytest.raises(AssertionError, match="no es bit a bit reproducible"):
        assert_bitwise_reproducible(lambda: {"value": next(counter)})


def test_assert_bitwise_reproducible_acepta_normalizacion() -> None:
    """``normalize`` permite remover campos no deterministas legítimos."""
    counter = itertools.count()

    def run() -> dict[str, int]:
        return {"value": 7, "timestamp": next(counter)}

    def normalize(payload: dict[str, int]) -> dict[str, int]:
        return {"value": payload["value"]}

    assert_bitwise_reproducible(run, normalize=normalize)


def test_assert_bitwise_reproducible_falla_si_no_serializa() -> None:
    """Un resultado no serializable falla con diagnóstico claro."""

    def run() -> Any:
        return lambda x: x

    with pytest.raises(AssertionError, match="No se pudo serializar"):
        assert_bitwise_reproducible(run)
