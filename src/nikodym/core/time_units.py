"""Unidades temporales de una term-structure: cuántos años vale un período declarado.

Una curva de PD publica ``time_value`` —el instante de cada punto— y la unidad en que ese número
está expresado. `ifrs9` descuenta con ``DF(t) = (1 + EIR)^(-tau)`` donde ``tau`` va **en años**, así
que sin unidad no hay descuento correcto: la misma cartera declarada en meses en vez de años
subestimaba la ECL en torno a un 40-50 %, medido, y en silencio (D-HOR-0).

Este módulo es la única tabla de conversión del paquete. Se consume por nombre, nunca copiando sus
literales a un ``if`` por motor: una segunda tabla que se desincronice de esta produce dos motores
que descuentan distinto sobre la misma curva.

**Un literal desconocido no es un error.** :func:`year_fraction` devuelve ``None`` y quien la llama
decide qué hacer —en `ifrs9`, presumir años y declararlo con una marca gobernable—. La razón es que
``"period"``, el default de fábrica de ``survival`` y ``markov``, no es ninguna unidad: levantar una
excepción rompería a **todo** usuario que nunca tocó el campo, y D-HOR-0 se eligió sobre la
alternativa de años-por-convención precisamente porque no rompe a nadie.

La normalización es deliberadamente laxa —``casefold`` y sin diacríticos, en español y en inglés,
singular y plural— porque ``time_unit`` es un campo de texto libre que escribe la institución
(``survival/config.py``, ``markov/config.py``). Ser estricto aquí produce falsos negativos que, con
``fail_on_falta_dato=True``, abortan corridas legítimas por una tilde.
"""

from __future__ import annotations

import unicodedata
from typing import Final

__all__ = ["YEAR_FRACTIONS", "known_time_units", "year_fraction"]

# Fracción de año de cada unidad reconocida, por su forma ya normalizada.
#
# ``week`` y ``day`` son una **convención declarada**, no una identidad: 1/52 y 1/365 ignoran años
# bisiestos y el day-count real (ACT/360, 30/360, …). Se incluyen igual porque la alternativa es
# peor: sin ellas, una curva diaria caería en la presunción de años y descontaría ``(1+EIR)^-365``,
# aniquilando la ECL. Un day-count aproximado y explícito es preferible a un absurdo silencioso.
#
# ``quincena``/``bimestre`` quedan **fuera a propósito**: su fracción de año es ambigua (26 vs 24
# períodos) y el motor no inventa convenciones. Caen en la rama de unidad no declarada.
#
# ``period`` —el default de ``survival`` y ``markov``— tampoco está aquí, y su ausencia es la
# decisión, no un olvido: nombra un índice, no una duración, y no hay nada que convertir.
YEAR_FRACTIONS: Final[dict[str, float]] = {
    # año
    "year": 1.0,
    "years": 1.0,
    "annual": 1.0,
    "yearly": 1.0,
    "ano": 1.0,
    "anos": 1.0,
    "anio": 1.0,
    "anios": 1.0,
    "anual": 1.0,
    # semestre
    "semester": 0.5,
    "semesters": 0.5,
    "semestre": 0.5,
    "semestres": 0.5,
    "semestral": 0.5,
    # trimestre
    "quarter": 0.25,
    "quarters": 0.25,
    "quarterly": 0.25,
    "trimestre": 0.25,
    "trimestres": 0.25,
    "trimestral": 0.25,
    # mes
    "month": 1.0 / 12.0,
    "months": 1.0 / 12.0,
    "monthly": 1.0 / 12.0,
    "mes": 1.0 / 12.0,
    "meses": 1.0 / 12.0,
    "mensual": 1.0 / 12.0,
    # semana
    "week": 1.0 / 52.0,
    "weeks": 1.0 / 52.0,
    "weekly": 1.0 / 52.0,
    "semana": 1.0 / 52.0,
    "semanas": 1.0 / 52.0,
    "semanal": 1.0 / 52.0,
    # día
    "day": 1.0 / 365.0,
    "days": 1.0 / 365.0,
    "daily": 1.0 / 365.0,
    "dia": 1.0 / 365.0,
    "dias": 1.0 / 365.0,
    "diario": 1.0 / 365.0,
}
"""Fracción de año por unidad normalizada. Se consume vía :func:`year_fraction`, no directamente."""


def _normalize(unit: str) -> str:
    """Normaliza un literal de unidad: sin espacios, sin mayúsculas y sin diacríticos.

    ``NFKD`` descompone la letra acentuada en base + combinante y el filtro descarta la combinante,
    de modo que ``"Año"``, ``"ANO"`` y ``"año"`` colapsan al mismo literal.
    """
    descompuesto = unicodedata.normalize("NFKD", unit.strip())
    return "".join(char for char in descompuesto if not unicodedata.combining(char)).casefold()


def year_fraction(unit: str | None) -> float | None:
    """Devuelve cuántos años vale un período de ``unit``, o ``None`` si no es convertible.

    Parameters
    ----------
    unit : str or None
        Unidad temporal tal como la declara el productor de la term-structure. ``None``, cadena
        vacía y cualquier literal fuera de :data:`YEAR_FRACTIONS` —incluido ``"period"``— devuelven
        ``None``: son «no declarada», no un error.

    Returns
    -------
    float or None
        Factor por el que multiplicar ``time_value`` para obtener años. ``1/12`` para meses, de modo
        que ``3 meses * 1/12 = 0,25 años``.

    Examples
    --------
    >>> year_fraction("month") == 1 / 12
    True
    >>> year_fraction("AÑOS")
    1.0
    >>> year_fraction("period") is None
    True
    """
    if unit is None:
        return None
    return YEAR_FRACTIONS.get(_normalize(unit))


def known_time_units() -> tuple[str, ...]:
    """Devuelve las unidades convertibles reconocidas, ordenadas de mayor a menor duración.

    Pensada para construir mensajes de ayuda sin duplicar la tabla. El orden es estable para que un
    texto generado no cambie entre corridas.
    """
    return tuple(sorted(YEAR_FRACTIONS, key=lambda unit: (-YEAR_FRACTIONS[unit], unit)))
