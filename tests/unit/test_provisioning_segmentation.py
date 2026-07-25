"""Esquemas de segmentación y regímenes regulatorios (``_ENMIENDA-SEGMENTACION.md``)."""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap

import pytest
from pydantic import ValidationError

from nikodym.provisioning import segmentation
from nikodym.provisioning.cmf import engine as cmf_engine
from nikodym.provisioning.segmentation import (
    REGIME_REGISTRY,
    SchemeOwner,
    SegmentationScheme,
    known_regimes,
    regime_scheme,
    regime_spec,
)


def _portfolios_despachados(funcion: object) -> frozenset[str]:
    """Valores de cartera que el if-chain de ``_resolve_provision`` compara explícitamente.

    Se lee del **código real** con ``ast`` en vez de mantener una lista paralela: una lista paralela
    sería una cuarta declaración del mismo dominio, que es justo el defecto que esto vigila.
    """
    arbol = ast.parse(textwrap.dedent(inspect.getsource(funcion)))  # type: ignore[arg-type]
    encontrados: set[str] = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Compare) or not isinstance(nodo.left, ast.Name):
            continue
        if nodo.left.id != "portfolio":
            continue
        for operador, comparado in zip(nodo.ops, nodo.comparators, strict=True):
            es_igualdad_textual = (
                isinstance(operador, ast.Eq)
                and isinstance(comparado, ast.Constant)
                and isinstance(comparado.value, str)
            )
            if es_igualdad_textual:
                encontrados.add(comparado.value)  # type: ignore[attr-defined]
    return frozenset(encontrados)


def test_esquema_normativo_y_despachador_declaran_el_mismo_dominio() -> None:
    """El vocabulario del esquema es EXACTAMENTE el que el motor sabe despachar (D-SEG-4).

    Sin este gate el dominio vuelve a estar declarado en dos lugares desacoplados: si el esquema
    gana un valor que el if-chain no resuelve, el gate de entrada lo deja pasar y el fallo aparece a
    mitad del cómputo —lo que CRP-5 prohíbe—; si pierde uno, queda una rama muerta que nadie ve.
    """
    esquema = regime_scheme("CL-CMF-B1")
    assert _portfolios_despachados(cmf_engine._resolve_provision) == frozenset(esquema.values)


def test_el_gate_de_dominio_caza_una_divergencia_inyectada() -> None:
    """El gate anterior sólo sirve si falla cuando el dominio diverge de verdad.

    Se inyecta un despachador con una cartera que el esquema no declara: si el gate no lo caza, no
    está vigilando nada.
    """

    def _despachador_con_cartera_extra(portfolio: str) -> str:
        if portfolio == "consumer":
            return "consumo"
        if portfolio == "commercial_individual_peru":  # no está en el esquema chileno
            return "otra"
        return "resto"

    esquema = regime_scheme("CL-CMF-B1")
    despachados = _portfolios_despachados(_despachador_con_cartera_extra)
    assert despachados != frozenset(esquema.values)
    assert "commercial_individual_peru" in despachados


def test_vocabulario_normativo_chileno_es_golden() -> None:
    """El vocabulario y su orden son contrato publicado: se fijan literal (criterio 2).

    El test de orden de ``summary`` en ``test_cmf_engine.py`` sólo protege el orden relativo de las
    carteras presentes en su golden, así que permutar dos que no aparecen ahí se le escaparía. Este
    golden cierra ese hueco: caza **cualquier** permutación del vocabulario.
    """
    assert regime_scheme("CL-CMF-B1").values == (
        "commercial_individual",
        "commercial_group_leasing",
        "commercial_group_student",
        "commercial_group_generic_factoring",
        "consumer",
        "housing",
    )


def test_todo_regimen_registrado_tiene_motor_implementado() -> None:
    """La regla de honestidad se hace cumplir con el registro, no con el sistema de tipos (D-SEG-1).

    Ampliar un ``Literal["CL"]`` a ``Literal["CL","PE"]`` compila igual de bien sin motor detrás;
    esto no.
    """
    assert known_regimes(), "El registro de regímenes no puede quedar vacío."
    for regime_id, spec in REGIME_REGISTRY.items():
        assert spec.regime_id == regime_id
        modulo = importlib.import_module(f"nikodym.provisioning.{spec.engine}")
        assert modulo is not None
        assert spec.scheme.regime == regime_id


def test_regimen_desconocido_nombra_los_disponibles() -> None:
    """Un régimen sin motor no existe, y el error lo dice sin insinuar que vendrá."""
    with pytest.raises(KeyError, match="CL-CMF-B1"):
        regime_spec("PE-SBS")


def test_esquema_derivado_no_puede_enumerar_ni_cerrarse() -> None:
    """El vocabulario de ``grouping='score_band'`` no existe hasta calcularlo (D-SEG-2)."""
    with pytest.raises(ValidationError, match="no puede enumerar valores"):
        SegmentationScheme(
            scheme_id="bandas",
            owner=SchemeOwner.RUNTIME,
            version="1",
            column="group_id",
            values=("b1", "b2"),
            closed=False,
        )
    with pytest.raises(ValidationError, match="no puede declararse cerrado"):
        SegmentationScheme(
            scheme_id="bandas", owner=SchemeOwner.RUNTIME, version="1", column="group_id"
        )


def test_esquema_normativo_exige_regimen_y_vocabulario() -> None:
    """Un esquema que dice venir de una norma tiene que decir de cuál y enumerar sus segmentos."""
    with pytest.raises(ValidationError, match="no declara cuál"):
        SegmentationScheme(
            scheme_id="x",
            owner=SchemeOwner.REGIME,
            version="1",
            column="c",
            values=("a",),
        )
    with pytest.raises(ValidationError, match="no declara su vocabulario"):
        SegmentationScheme(
            scheme_id="x", owner=SchemeOwner.REGIME, version="1", column="c", regime="CL-CMF-B1"
        )


def test_esquema_institucional_abierto_admite_cualquier_valor() -> None:
    """La institución puede declarar su taxonomía cerrada o abierta; se respeta lo que declare."""
    abierto = SegmentationScheme(
        scheme_id="grupos-banco",
        owner=SchemeOwner.INSTITUTION,
        version="1",
        column="group_id",
        closed=False,
    )
    cerrado = SegmentationScheme(
        scheme_id="grupos-banco",
        owner=SchemeOwner.INSTITUTION,
        version="1",
        column="group_id",
        values=("retail", "mayorista"),
    )
    assert abierto.admits("lo-que-sea")
    assert cerrado.admits("retail")
    assert not cerrado.admits("retail ")


def test_la_llave_de_resolucion_lleva_el_esquema() -> None:
    """Dos esquemas pueden compartir el valor ``consumer``; la llave pelada colisionaría."""
    chileno = regime_scheme("CL-CMF-B1")
    banco = SegmentationScheme(
        scheme_id="grupos-banco",
        owner=SchemeOwner.INSTITUTION,
        version="1",
        column="group_id",
        values=("consumer",),
    )
    assert chileno.key("consumer") != banco.key("consumer")


def test_vocabulario_sin_duplicados() -> None:
    """Un vocabulario con repetidos rompería el orden de presentación y el conteo de segmentos."""
    with pytest.raises(ValidationError, match="repite valores"):
        SegmentationScheme(
            scheme_id="x",
            owner=SchemeOwner.INSTITUTION,
            version="1",
            column="c",
            values=("a", "a"),
        )


def test_modulo_no_arrastra_pandas() -> None:
    """``import nikodym.provisioning`` debe seguir siendo liviano (SDD-17)."""
    fuente = inspect.getsource(segmentation)
    assert "import pandas" not in fuente
