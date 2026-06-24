"""Tests canónicos (golden values) de la siembra determinista (SDD-01 §11, DoD F0).

Los valores dorados se congelaron al implementar :class:`SeedManager` y son estables entre
procesos porque la derivación usa ``hashlib`` + ``SeedSequence`` (no el ``hash()`` builtin ni
``spawn()``). Si un cambio los altera, es una ruptura de reproducibilidad (ancla regulatoria).
"""

import os
import random

import pytest

from nikodym.core.seeding import SeedManager

# — Golden values congelados (SeedManager(42)) —
GOLDEN_BINNING_INTS = [35866044, 1925873718, 1338300275, 1612367033, 1074782850]
GOLDEN_SELECTION_INTS = [1742200289, 883286722, 821234755, 490811694, 908148815]
GOLDEN_INT_SEED_BINNING = 2483230548
GOLDEN_INT_SEED_SELECTION = 1891338934
GOLDEN_STABLE_HASH_BINNING = (
    61193139580640898126684771690257220434569610765035338660848820390849757547066
)


def test_generator_for_is_golden() -> None:
    """``generator_for`` produce la secuencia dorada conocida para cada nombre."""
    sm = SeedManager(42)
    assert sm.generator_for("binning").integers(0, 2**31, size=5).tolist() == GOLDEN_BINNING_INTS
    assert (
        sm.generator_for("selection").integers(0, 2**31, size=5).tolist() == GOLDEN_SELECTION_INTS
    )


def test_streams_are_independent_between_names() -> None:
    """Streams de nombres distintos son independientes (no comparten estado)."""
    sm = SeedManager(42)
    assert GOLDEN_BINNING_INTS != GOLDEN_SELECTION_INTS
    binning = sm.generator_for("binning").integers(0, 2**31, size=5).tolist()
    selection = sm.generator_for("selection").integers(0, 2**31, size=5).tolist()
    assert binning != selection


def test_order_independence() -> None:
    """Derivar 'selection' antes que 'binning' NO altera el stream de 'binning'."""
    sm = SeedManager(42)
    _ = sm.generator_for("selection").integers(0, 2**31, size=5).tolist()
    binning_after = sm.generator_for("binning").integers(0, 2**31, size=5).tolist()
    assert binning_after == GOLDEN_BINNING_INTS


def test_int_seed_for_is_golden_and_stable() -> None:
    """``int_seed_for`` devuelve un ``uint32`` dorado, estable entre procesos (hashlib)."""
    sm = SeedManager(42)
    assert sm.int_seed_for("binning") == GOLDEN_INT_SEED_BINNING
    assert sm.int_seed_for("selection") == GOLDEN_INT_SEED_SELECTION
    assert 0 <= sm.int_seed_for("binning") < 2**32


def test_stable_hash_is_golden() -> None:
    """``_stable_hash`` (hashlib) es determinista y reproducible cross-proceso."""
    assert SeedManager._stable_hash("binning") == GOLDEN_STABLE_HASH_BINNING


def test_seed_propagates_to_derived_streams() -> None:
    """Cambiar ``root_seed`` cambia los streams derivados (la semilla SÍ propaga)."""
    a = SeedManager(42).generator_for("binning").integers(0, 2**31, size=5).tolist()
    b = SeedManager(7).generator_for("binning").integers(0, 2**31, size=5).tolist()
    assert a != b


def test_apply_global_warns_without_pythonhashseed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin ``PYTHONHASHSEED`` fijo, ``apply_global`` advierte (límite honesto)."""
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    with pytest.warns(UserWarning, match="PYTHONHASHSEED"):
        SeedManager(42).apply_global()


def test_apply_global_silent_and_deterministic_with_pythonhashseed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con ``PYTHONHASHSEED`` fijo no advierte y siembra ``random`` de forma determinista."""
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    assert os.environ["PYTHONHASHSEED"] == "0"
    SeedManager(42).apply_global()
    first = random.random()
    SeedManager(42).apply_global()
    second = random.random()
    assert first == second
