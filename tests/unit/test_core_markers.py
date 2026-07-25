"""Tests del contrato de marcas: FALTA-DATO vs DATO-INSTITUCIONAL (enmienda de taxonomía).

El modo de fallo que cubren estos tests no es ruidoso: un filtro que sólo conozca una de las dos
marcas **descarta la otra en silencio**, sin excepción ni warning, y el aviso desaparece de la card
sin que nada se ponga rojo. Por eso se fija aquí, y no sólo en cada capa.
"""

import pytest

from nikodym.core.markers import (
    DECLARED_MARKERS,
    INSTITUTIONAL_MARKER,
    MISSING_DATA_MARKER,
    declared_prefixes,
    is_declared_warning,
    strip_declared_codes,
)


def test_las_dos_marcas_son_distintas_y_ninguna_prefija_a_la_otra() -> None:
    """Si una marca fuese prefijo de la otra, filtrar por prefijo mezclaría las clases."""
    assert MISSING_DATA_MARKER != INSTITUTIONAL_MARKER
    assert not MISSING_DATA_MARKER.startswith(INSTITUTIONAL_MARKER)
    assert not INSTITUTIONAL_MARKER.startswith(MISSING_DATA_MARKER)
    assert DECLARED_MARKERS == (MISSING_DATA_MARKER, INSTITUTIONAL_MARKER)


@pytest.mark.parametrize(
    "code",
    [
        "FALTA-DATO",
        "FALTA-DATO-IFRS-4",
        "FALTA-DATO-VAL-1",
        "DATO-INSTITUCIONAL",
        "DATO-INSTITUCIONAL-FWD-1",
        "DATO-INSTITUCIONAL-PROV-3",
    ],
)
def test_reconoce_ambas_marcas(code: str) -> None:
    """Las dos clases de aviso declarado llegan a la card; ninguna se pierde por el filtro."""
    assert is_declared_warning(code)


@pytest.mark.parametrize(
    "code",
    ["comparacion_incompleta", "cobertura_imputada_cero", "piso_incompleto", "", "DATO", "FALTA"],
)
def test_ignora_los_warnings_que_no_son_avisos_declarados(code: str) -> None:
    """Los códigos de warning por celda no son avisos declarados y no deben colarse en la card."""
    assert not is_declared_warning(code)


def test_familia_acota_a_su_capa_en_ambas_marcas() -> None:
    """El filtro por familia de ``stress`` recoge sus dos clases y descarta las de otras capas."""
    assert is_declared_warning("FALTA-DATO-STR-5", family="STR")
    assert is_declared_warning("DATO-INSTITUCIONAL-STR-2", family="STR")
    assert not is_declared_warning("FALTA-DATO-IFRS-4", family="STR")
    assert not is_declared_warning("DATO-INSTITUCIONAL-FWD-1", family="STR")


def test_declared_prefixes_sin_familia_son_las_marcas_desnudas() -> None:
    """Sin familia, los prefijos cubren tanto el código con familia como la marca sola."""
    assert declared_prefixes() == (MISSING_DATA_MARKER, INSTITUTIONAL_MARKER)
    assert declared_prefixes("IFRS") == ("FALTA-DATO-IFRS", "DATO-INSTITUCIONAL-IFRS")


# --- Saneo del mensaje para el copy público (enmienda RUN-ERROR, D-ERR-4) ----------------------


#: Mensajes REALES de `raise` del motor, con el código en las tres posiciones en que aparece: al
#: frente, entre paréntesis a mitad de frase y al final. Un saneador probado sólo contra el caso
#: fácil (código al frente) deja pasar los otros dos.
_MENSAJES_REALES = [
    (
        "DATO-INSTITUCIONAL-FWD-1: adverse/severe deben declarar macro_path_path o shocks; "
        "no se inventan.",
        "adverse/severe deben declarar macro_path_path o shocks; no se inventan.",
    ),
    (
        "feature_source='data_raw' está diferido (FALTA-DATO-ML-1): use 'binning_woe'.",
        "feature_source='data_raw' está diferido: use 'binning_woe'.",
    ),
    (
        "El backend exige imputación declarada (no tolera NaN): FALTA-DATO-ML-1.",
        "El backend exige imputación declarada (no tolera NaN).",
    ),
    (
        "FALTA-DATO-FWD-8: kind='vecm' exige vecm_rank explícito.",
        "kind='vecm' exige vecm_rank explícito.",
    ),
]


@pytest.mark.parametrize(("crudo", "esperado"), _MENSAJES_REALES, ids=lambda v: v[:28])
def test_el_saneo_quita_el_codigo_y_deja_la_frase_legible(crudo: str, esperado: str) -> None:
    """El panel de resultados es copy público: la limitación se explica, el código se va."""
    assert strip_declared_codes(crudo) == esperado


@pytest.mark.parametrize(("crudo", "esperado"), _MENSAJES_REALES, ids=lambda v: v[:28])
def test_el_saneo_no_deja_ningun_codigo_en_pie(crudo: str, esperado: str) -> None:
    """La garantía dura, independiente de la puntuación: ninguna marca sobrevive al saneo."""
    del esperado
    assert not any(marca in strip_declared_codes(crudo) for marca in DECLARED_MARKERS)


def test_el_saneo_respeta_un_mensaje_que_no_trae_codigo() -> None:
    """El caso mayoritario: un mensaje sin marca vuelve intacto, sin recortes creativos."""
    mensaje = "El DataFrame no cumple el esquema declarado. columna: mora_max_12m; check: dtype"
    assert strip_declared_codes(mensaje) == mensaje


def test_el_saneo_alcanza_varios_codigos_en_el_mismo_mensaje() -> None:
    """Un mensaje puede citar dos avisos; quitar sólo el primero deja el segundo a la vista."""
    saneado = strip_declared_codes(
        "Faltan dos: FALTA-DATO-IFRS-4 y DATO-INSTITUCIONAL-STR-2 en la misma corrida."
    )
    assert saneado == "Faltan dos: y en la misma corrida."
    assert not any(marca in saneado for marca in DECLARED_MARKERS)
