"""Tests de ``core.steps`` (SDD-01 §4/§7; CT-1): ``ArtifactKey``, ``Step`` y ``StepAdapter``.

Incluyen la **prueba de fuego CT-1** (criterio de aceptación F0): un ``Step`` nativo con *fan-in*
(``requires`` de dos artefactos de dos dominios distintos), que ejercita el contrato
``requires``/``provides`` antes de que forward dependa de él.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from nikodym.core.base import NikodymClassifier
from nikodym.core.steps import ArtifactKey, Step, StepAdapter


class _StepNativo:
    """Step nativo de juguete que implementa el Protocol directamente."""

    def __init__(
        self,
        name: str,
        requires: tuple[ArtifactKey, ...],
        provides: tuple[ArtifactKey, ...],
    ) -> None:
        self.name = name
        self.requires = requires
        self.provides = provides

    def execute(self, study: Any, rng: np.random.Generator) -> str:
        return f"{self.name}:{rng.integers(0, 10)}"


# --- Step Protocol (runtime_checkable) --------------------------------------------------------


def test_step_nativo_satisface_protocol() -> None:
    """Un objeto con name/requires/provides/execute es instancia de ``Step``."""
    step = _StepNativo("binning", (), (("binning", "woe"),))
    assert isinstance(step, Step)


def test_objeto_incompleto_no_es_step() -> None:
    """Falta ``execute`` → no satisface ``Step`` (runtime_checkable verifica presencia)."""

    class _SinExecute:
        name = "x"
        requires: tuple[ArtifactKey, ...] = ()
        provides: tuple[ArtifactKey, ...] = ()

    assert not isinstance(_SinExecute(), Step)


def test_ct1_fan_in_dos_dominios() -> None:
    """CT-1 (criterio de aceptación F0): un Step con *fan-in* de dos dominios distintos."""
    requires: tuple[ArtifactKey, ...] = (("binning", "woe"), ("calibration", "pd_calibrada"))
    step = _StepNativo("provisioning", requires, (("provisioning", "pe"),))
    assert isinstance(step, Step)
    assert step.requires == requires
    # dos dominios distintos en el fan-in
    assert len({dominio for dominio, _ in step.requires}) == 2


def test_requires_provides_son_tuplas() -> None:
    """``requires``/``provides`` son tuplas inmutables, no listas."""
    step = _StepNativo("x", (("a", "b"),), (("c", "d"),))
    assert isinstance(step.requires, tuple)
    assert isinstance(step.provides, tuple)


def test_step_nativo_execute_usa_rng() -> None:
    """El ``execute`` de un Step nativo consume el ``rng`` inyectado (reproducible)."""
    step = _StepNativo("binning", (), ())
    rng = np.random.default_rng(42)
    assert step.execute(None, rng).startswith("binning:")


# --- StepAdapter ------------------------------------------------------------------------------


def test_step_adapter_name_es_domain() -> None:
    """``StepAdapter.name == domain`` (invariante de naming, única fuente del dominio)."""
    adapter = StepAdapter("model", NikodymClassifier())
    assert adapter.name == "model"


def test_step_adapter_es_un_step() -> None:
    """Un ``StepAdapter`` satisface el Protocol ``Step`` (tiene los 4 miembros)."""
    adapter = StepAdapter("model", NikodymClassifier())
    assert isinstance(adapter, Step)


def test_step_adapter_propaga_claves_io() -> None:
    """Las claves de I/O pasadas al constructor quedan en ``requires``/``provides``."""
    requires: tuple[ArtifactKey, ...] = (("data", "panel"),)
    provides: tuple[ArtifactKey, ...] = (("model", "fit"),)
    adapter = StepAdapter("model", NikodymClassifier(), requires=requires, provides=provides)
    assert adapter.requires == requires
    assert adapter.provides == provides


def test_step_adapter_execute_difiere_ruidoso() -> None:
    """En F0, ``StepAdapter.execute`` difiere con ``NotImplementedError`` (no no-op silencioso)."""
    adapter = StepAdapter("model", NikodymClassifier())
    with pytest.raises(NotImplementedError, match="primer estimador de dominio"):
        adapter.execute(None, np.random.default_rng(0))
