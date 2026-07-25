"""Marcas de aviso declarado: qué le falta a Nikodym y qué le corresponde a la institución.

Un aviso declarado es la constancia, en el resultado, de que algo no se calculó con un dato real.
Hay dos causas distintas y no conviene confundirlas (enmienda de taxonomía, D-MARCA-1):

``FALTA-DATO``
    **Brecha del motor**: algo que Nikodym todavía no trae, difirió, o no verificó contra la fuente
    oficial. Es una carencia propia y se enuncia como tal.

``DATO-INSTITUCIONAL``
    **Input que aporta la institución**: un parámetro, una definición o un dato de entrada que sólo
    puede fijar quien usa la librería. No confiesa una carencia: deja constancia de que el motor se
    negó a inventar un supuesto que no le corresponde.

La regla para clasificar un código nuevo cabe en una línea: ``FALTA-DATO`` es *lo debe Nikodym*;
``DATO-INSTITUCIONAL`` es *lo debe la institución*.

Las dos marcas se consumen desde aquí, nunca como literal en cada capa: los pasos arman
``card.falta_dato`` filtrando los ``warning_codes`` por prefijo, y un filtro que sólo conozca una de
las marcas descarta la otra **en silencio**, sin fallar (D-MARCA-3).
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "DECLARED_MARKERS",
    "INSTITUTIONAL_MARKER",
    "MISSING_DATA_MARKER",
    "declared_prefixes",
    "is_declared_warning",
    "strip_declared_codes",
]

MISSING_DATA_MARKER: Final = "FALTA-DATO"
"""Marca de brecha del motor: Nikodym no lo trae, lo difirió o no lo verificó."""

INSTITUTIONAL_MARKER: Final = "DATO-INSTITUCIONAL"
"""Marca de input institucional: el parámetro, la definición o el dato los pone la institución."""

DECLARED_MARKERS: Final[tuple[str, str]] = (MISSING_DATA_MARKER, INSTITUTIONAL_MARKER)
"""Las dos marcas de aviso declarado, en orden estable."""


def declared_prefixes(family: str | None = None) -> tuple[str, ...]:
    """Devuelve los prefijos de aviso declarado, opcionalmente acotados a una familia.

    Parameters
    ----------
    family : str or None
        Familia del código (``"STR"``, ``"IFRS"``, …). Con ``None`` devuelve las marcas desnudas,
        que cubren tanto el código con familia (``FALTA-DATO-IFRS-4``) como la marca sola.

    Returns
    -------
    tuple of str
        Prefijos en el orden de :data:`DECLARED_MARKERS`.
    """
    if family is None:
        return DECLARED_MARKERS
    return tuple(f"{marker}-{family}" for marker in DECLARED_MARKERS)


def is_declared_warning(code: str, *, family: str | None = None) -> bool:
    """Indica si ``code`` es un aviso declarado, de cualquiera de las dos marcas.

    Parameters
    ----------
    code : str
        Código de warning tal como lo emite el motor.
    family : str or None
        Si se indica, exige además que el código pertenezca a esa familia.
    """
    return code.startswith(declared_prefixes(family))


#: Un código de aviso declarado tal como aparece **dentro de una frase**: la marca desnuda o con su
#: familia y número (``FALTA-DATO``, ``DATO-INSTITUCIONAL-FWD-1``). Se ancla al comienzo de la marca
#: para no morder un guion que venga antes.
_DECLARED_CODE = re.compile(
    r"(?:{})(?:-[A-Z0-9]+)*".format("|".join(re.escape(marker) for marker in DECLARED_MARKERS))
)

#: Restos que deja el recorte: un paréntesis que se quedó vacío, puntuación colgando al principio o
#: al final de la frase, y espacios dobles donde estaba el código.
_LIMPIEZAS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"\(\s*[:;,.]?\s*\)"), ""),
    (re.compile(r"\s+([.,;:!?])"), r"\1"),
    (re.compile(r"([:;,])\s*([.!?])"), r"\2"),
    (re.compile(r"[ \t]{2,}"), " "),
    (re.compile(r"^[\s:;,.\-—]+"), ""),
    (re.compile(r"[\s:;,\-—]+$"), ""),
)


def strip_declared_codes(text: str) -> str:
    """Quita los códigos de aviso declarado de un texto, dejando la frase legible.

    Existe para una frontera concreta: el mensaje de un ``NikodymError`` es prosa escrita para un
    humano, pero **once** ``raise`` del motor le anteponen o intercalan el código de la marca
    (``DATO-INSTITUCIONAL-FWD-1: adverse/severe deben declarar…``). Ese mensaje viaja tal cual a
    ``run_context.error.message`` —superficie de código, donde el código es el dato— y **saneado**
    al panel de resultados de la UI, que es copy público y donde la regla es explicar la limitación
    en el idioma del lector, sin nombrar el código (enmienda RUN-ERROR, D-ERR-4).

    No es un filtro de seguridad ni un sanitizador de HTML: sólo recorta los códigos del contrato de
    marcas y normaliza la puntuación que queda huérfana.

    Parameters
    ----------
    text : str
        Texto que puede contener uno o más códigos de aviso declarado.

    Returns
    -------
    str
        El mismo texto sin los códigos. Un texto que no traía ninguno vuelve intacto salvo por el
        recorte de espacios en los extremos.

    Examples
    --------
    >>> strip_declared_codes("DATO-INSTITUCIONAL-FWD-1: declare macro_path_path o shocks.")
    'declare macro_path_path o shocks.'
    >>> strip_declared_codes("feature_source='data_raw' está diferido (FALTA-DATO-ML-1): use otro.")
    "feature_source='data_raw' está diferido: use otro."
    """
    limpio = _DECLARED_CODE.sub("", text)
    for patron, reemplazo in _LIMPIEZAS:
        limpio = patron.sub(reemplazo, limpio)
    return limpio
