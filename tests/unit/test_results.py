"""Tests de ``core.results`` (SDD-01 §4, CT-2): Protocols ``ProvisionResultLike``/``ECLResultLike``.

Verifican la verificación estructural de ``@runtime_checkable`` (presencia de nombres), la
herencia del contrato de lectura (ECL ⊇ Provisión) y la **prueba de fuego CT-2**: la puerta
``term_structure()`` aguanta un payload estructurado (DataFrame tidy por stage x escenario).
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from nikodym.core.results import ECLResultLike, ProvisionResultLike


class _ProvisionStub:
    """Implementación mínima que satisface ``ProvisionResultLike`` (motor CMF agregado)."""

    def __init__(self, *, term: pd.DataFrame | None = None) -> None:
        self.componentes = pd.DataFrame({"pi": [0.1], "pdi": [0.5], "exposicion": [100.0]})
        self.total = 5.0
        self.por_cartera: Mapping[str, float] = {"comercial": 3.0, "consumo": 2.0}
        self.motor = "cmf_standard"
        self._term = term

    def to_frame(self) -> pd.DataFrame:
        return self.componentes

    def term_structure(self) -> pd.DataFrame | None:
        return self._term


class _ECLStub(_ProvisionStub):
    """Implementación que añade lo específico de IFRS 9 para satisfacer ``ECLResultLike``."""

    def __init__(self, *, term: pd.DataFrame | None = None) -> None:
        super().__init__(term=term)
        self.motor = "ifrs9_ecl"
        self.por_instrumento = pd.DataFrame(
            {"PD": [0.1], "LGD": [0.4], "EAD": [100.0], "stage": [1]}
        )
        self.por_escenario: Mapping[str, float] = {"base": 4.0, "adverso": 6.0, "severo": 9.0}


# --- ProvisionResultLike ----------------------------------------------------------------------


def test_provision_stub_satisface_el_protocol() -> None:
    """Un stub con todos los miembros es instancia de ProvisionResultLike (presencia de nombres)."""
    assert isinstance(_ProvisionStub(), ProvisionResultLike)


def test_objeto_incompleto_no_satisface_provision() -> None:
    """Falta ``motor`` → no satisface ProvisionResultLike (runtime_checkable verifica presencia)."""

    class _Incompleto:
        def __init__(self) -> None:
            self.componentes = pd.DataFrame()
            self.total = 1.0
            self.por_cartera: Mapping[str, float] = {}
            # falta 'motor', to_frame, term_structure

    assert not isinstance(_Incompleto(), ProvisionResultLike)


def test_to_frame_devuelve_dataframe() -> None:
    """``to_frame`` materializa una vista tabular (DataFrame)."""
    assert isinstance(_ProvisionStub().to_frame(), pd.DataFrame)


def test_term_structure_none_para_motor_agregado() -> None:
    """CMF agregado/scoring: ``term_structure()`` devuelve None."""
    assert _ProvisionStub().term_structure() is None


# --- ECLResultLike ----------------------------------------------------------------------------


def test_ecl_stub_satisface_ambos_protocols() -> None:
    """Un stub ECL satisface ECLResultLike Y ProvisionResultLike (herencia del contrato)."""
    stub = _ECLStub()
    assert isinstance(stub, ECLResultLike)
    assert isinstance(stub, ProvisionResultLike)


def test_provision_no_satisface_ecl() -> None:
    """Un stub que cumple Provisión pero sin ``por_instrumento``/``por_escenario`` no es ECL."""
    stub = _ProvisionStub()
    assert isinstance(stub, ProvisionResultLike)
    assert not isinstance(stub, ECLResultLike)


# --- Prueba de fuego CT-2 (criterio de aceptación F0) ------------------------------------------


def test_ct2_term_structure_aguanta_payload_estructurado() -> None:
    """CT-2: ``term_structure()`` admite un DataFrame tidy [escenario, t, componente, valor].

    Convierte el riesgo de F4 (ECL lifetime) en un test que falla hoy si la firma no sirve.
    """
    curva = pd.DataFrame(
        {
            "escenario": ["base", "base", "adverso", "adverso"],
            "t": [1, 2, 1, 2],
            "componente": ["ecl", "ecl", "ecl", "ecl"],
            "valor": [0.10, 0.18, 0.22, 0.35],
        }
    )
    stub = _ECLStub(term=curva)
    assert isinstance(stub, ECLResultLike)
    ts = stub.term_structure()
    assert ts is not None
    assert list(ts.columns) == ["escenario", "t", "componente", "valor"]
    assert len(ts) == 4
