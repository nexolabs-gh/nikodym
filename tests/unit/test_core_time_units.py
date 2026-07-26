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


# Alias → canónico, ESCRITO A MANO y no derivado de `YEAR_FRACTIONS`. Es la diferencia entre un
# test y una tautología: comparar cada alias contra el valor que se lee del mismo dict no puede
# fallar nunca, ni siquiera si alguien pone `"monthly": 1.0`. Un revisor adversarial lo demostró
# mutando seis entradas —entre ellas `monthly` de 1/12 a 1.0, que multiplicaría la ECL por 12— y
# viendo pasar la suite ENTERA. Esta tabla es la que hace verdadero al gate de cobertura
# regulatoria: sin ella, el 100 % de `time_units.py` sólo prueba que el módulo se importa.
_ALIAS_CANONICO: dict[str, str] = {
    "years": "year",
    "annual": "year",
    "yearly": "year",
    "ano": "year",
    "anos": "year",
    "anio": "year",
    "anios": "year",
    "anual": "year",
    "semesters": "semester",
    "semestre": "semester",
    "semestres": "semester",
    "semestral": "semester",
    "quarters": "quarter",
    "quarterly": "quarter",
    "trimestre": "quarter",
    "trimestres": "quarter",
    "trimestral": "quarter",
    "months": "month",
    "monthly": "month",
    "mes": "month",
    "meses": "month",
    "mensual": "month",
    "weeks": "week",
    "weekly": "week",
    "semana": "week",
    "semanas": "week",
    "semanal": "week",
    "days": "day",
    "daily": "day",
    "dia": "day",
    "dias": "day",
    "diario": "day",
}

# Los seis canónicos y su fracción, también a mano. `_ALIAS_CANONICO` ancla los sinónimos entre sí;
# esto ancla el valor absoluto, de modo que mover `"year"` tampoco pase inadvertido.
_CANONICO_FRACCION: dict[str, float] = {
    "year": 1.0,
    "semester": 0.5,
    "quarter": 0.25,
    "month": 1.0 / 12.0,
    "week": 1.0 / 52.0,
    "day": 1.0 / 365.0,
}


@pytest.mark.parametrize(("alias", "canonico"), sorted(_ALIAS_CANONICO.items()))
def test_cada_alias_vale_lo_mismo_que_su_canonico(alias: str, canonico: str) -> None:
    """Un alias con el valor cambiado rompe la provisión por un factor de 12 o de 365, en silencio.

    Es la razón por la que el módulo entró al gate de cobertura regulatoria, y el gate por sí solo
    **no** puede cazarlo: las 78 entradas del dict son un único statement.
    """
    assert year_fraction(alias) == _CANONICO_FRACCION[canonico], alias


@pytest.mark.parametrize(("canonico", "fraccion"), sorted(_CANONICO_FRACCION.items()))
def test_el_valor_absoluto_de_cada_canonico_esta_anclado(canonico: str, fraccion: float) -> None:
    """Sin esto, mover los seis canónicos a la vez pasaría el test de alias sin despeinarse."""
    assert year_fraction(canonico) == fraccion


def test_la_tabla_no_tiene_alias_sin_anclar() -> None:
    """Un alias nuevo sin fila en `_ALIAS_CANONICO` sería un valor sin test. Falla ruidoso.

    Es la guarda anti-vacuidad de los dos tests de arriba: sin ella, alguien podría añadir
    `"quincenal": 1.0` y ningún test lo miraría.
    """
    anclados = set(_ALIAS_CANONICO) | set(_CANONICO_FRACCION)
    sin_anclar = set(YEAR_FRACTIONS) - anclados

    assert not sin_anclar, f"alias sin valor fijado por un test: {sorted(sin_anclar)}"


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
