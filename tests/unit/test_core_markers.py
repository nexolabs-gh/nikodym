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
