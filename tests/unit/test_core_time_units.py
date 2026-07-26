"""Tests de ``core.time_units``: la tabla de conversión de unidad temporal a años (D-HOR-0).

Lo que se prueba no es la tabla en sí sino sus dos contratos: que **la misma duración expresada en
unidades distintas colapse al mismo número de años** —el invariante del que depende que `ifrs9`
descuente bien— y que **un literal no reconocido devuelva ``None`` en vez de levantar**, porque
``"period"`` es el default de fábrica de ``survival``/``markov`` y una excepción rompería a todo
usuario que nunca tocó el campo.
"""

from __future__ import annotations

import pytest

from nikodym.core.time_units import YEAR_FRACTIONS, known_time_units, year_fraction


@pytest.mark.parametrize(
    ("unit", "esperado"),
    [
        ("year", 1.0),
        ("semester", 0.5),
        ("quarter", 0.25),
        ("month", 1.0 / 12.0),
        ("week", 1.0 / 52.0),
        ("day", 1.0 / 365.0),
    ],
)
def test_fraccion_de_ano_por_unidad(unit: str, esperado: float) -> None:
    assert year_fraction(unit) == esperado


@pytest.mark.parametrize(
    ("declarado", "canonico"),
    [
        ("YEAR", "year"),
        ("  year  ", "year"),
        ("Años", "year"),
        ("años", "year"),
        ("ANOS", "year"),
        ("anual", "year"),
        ("Meses", "month"),
        ("mensual", "month"),
        ("Trimestral", "quarter"),
        ("días", "day"),
    ],
)
def test_la_normalizacion_tolera_mayusculas_espacios_y_tildes(
    declarado: str, canonico: str
) -> None:
    """``time_unit`` es texto libre que escribe la institución: no se rechaza por una tilde.

    Con ``fail_on_falta_dato=True``, un falso negativo aquí aborta una corrida legítima.
    """
    assert year_fraction(declarado) == year_fraction(canonico)


@pytest.mark.parametrize("unit", [None, "", "   ", "period", "periodo", "período", "step", "t"])
def test_lo_no_convertible_devuelve_none_y_no_levanta(unit: str | None) -> None:
    """``"period"`` nombra un índice, no una duración. Su ausencia de la tabla es la decisión."""
    assert year_fraction(unit) is None


@pytest.mark.parametrize("unit", ["quincena", "bimestre", "fortnight"])
def test_las_unidades_ambiguas_quedan_fuera_a_proposito(unit: str) -> None:
    """26 quincenas o 24 según a quién se le pregunte: el motor no inventa la convención."""
    assert year_fraction(unit) is None


def test_la_misma_duracion_en_distinta_unidad_colapsa_a_los_mismos_anos() -> None:
    """El invariante que hace correcto el descuento: 12 meses, 4 trimestres y 1 año son lo mismo.

    Es la propiedad que `ifrs9` explota para convertir ``time_value`` antes de elevarlo como
    exponente de ``(1+EIR)^-tau``.
    """
    un_ano = 1.0 * _fraccion("year")
    assert 12.0 * _fraccion("month") == pytest.approx(un_ano, rel=1e-12)
    assert 4.0 * _fraccion("quarter") == pytest.approx(un_ano, rel=1e-12)
    assert 2.0 * _fraccion("semester") == pytest.approx(un_ano, rel=1e-12)
    assert 52.0 * _fraccion("week") == pytest.approx(un_ano, rel=1e-12)
    assert 365.0 * _fraccion("day") == pytest.approx(un_ano, rel=1e-12)


def test_tres_meses_son_un_cuarto_de_ano() -> None:
    """El caso concreto de la medición de la enmienda: una curva trimestral declarada en meses."""
    assert 3.0 * _fraccion("month") == pytest.approx(0.25, rel=1e-12)


def test_todo_alias_de_la_tabla_es_convertible() -> None:
    """Ningún alias puede colarse con un valor no positivo o no finito."""
    for unit, fraccion in YEAR_FRACTIONS.items():
        assert year_fraction(unit) == fraccion, unit
        assert fraccion > 0.0, unit


def test_known_time_units_es_estable_y_va_de_mayor_a_menor() -> None:
    """El orden se fija para que un texto de ayuda generado no cambie entre corridas."""
    unidades = known_time_units()

    assert unidades == known_time_units()
    assert set(unidades) == set(YEAR_FRACTIONS)
    fracciones = [YEAR_FRACTIONS[unit] for unit in unidades]
    assert fracciones == sorted(fracciones, reverse=True)


def _fraccion(unit: str) -> float:
    """Desenvuelve el ``float | None`` de :func:`year_fraction` para una unidad conocida."""
    fraccion = year_fraction(unit)
    assert fraccion is not None, unit
    return fraccion
