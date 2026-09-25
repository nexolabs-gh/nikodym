"""Rótulos legibles de un tramo de binning (enmienda COPY-PRUEBA-REAL-SBA, D-CPY-3).

Una sola fuente para cómo se **lee** un tramo en el resumen, ``sc.bins()``, el informe y la
pantalla: las categorías unidas con «, », los tramos auxiliares en palabras y los rangos con
comparadores en es-CL, escritos desde los **bordes efectivos** que publica ``binning``
(``("binning", "bin_edges")``) y no desde la etiqueta de OptBinning, que está redondeada a dos
decimales. La etiqueta del motor sigue siendo la clave de todo lo que casa por tramo.

Vive en ``core`` y no en ``binning`` porque la capa ``ui`` no importa dominios (D-HASH-5); no
importa ``pandas``: opera sobre los ``DataFrame`` que recibe.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

__all__ = [
    "AUX_BIN_LABELS",
    "BIN_EDGES_COLUMNS",
    "es_fila_de_totales",
    "filas_que_casan",
    "formatear_borde",
    "rotulo_de_rango",
    "rotulo_de_tramo",
    "rotulos_por_fila",
]

#: Los tramos auxiliares de OptBinning, dichos para quien lee (enmienda COPY-PRUEBA-REAL-SBA).
AUX_BIN_LABELS: dict[str, str] = {
    "Missing": "Faltantes",
    "Special": "Valores especiales",
}
#: Las columnas de ``("binning", "bin_edges")``: un tramo regular por fila, con sus bordes
#: efectivos a precisión completa (no la etiqueta de OptBinning, redondeada a dos decimales).
BIN_EDGES_COLUMNS: tuple[str, ...] = ("variable", "bin_index", "lower", "upper")


def formatear_borde(valor: float) -> str:
    """Un borde de tramo en es-CL, **exacto**: todos sus decimales significativos y ni uno más.

    Es la representación decimal más corta que vuelve al mismo ``float`` (``repr``), escrita con
    punto de miles y coma decimal. Los cortes de OptBinning son puntos medios entre valores en
    float32 y pueden verse largos (``242.795,8828125``), pero son el borde con que el motor compara:
    redondearlo —la etiqueta de OptBinning usa dos decimales— puede afirmar que una operación junto
    al borde cae en el otro tramo (``242.795,881`` está por debajo de ``242.795,8828125``; por
    encima de ``242.795,88``). Revisión adversarial del código, pasada 2. Un corte declarado a mano
    (``50450``, ``7,5``) sale tal como se escribió.
    """
    if math.isinf(valor):
        return "-∞" if valor < 0 else "∞"
    if valor == 0:
        return "0"
    texto = format(Decimal(repr(float(valor))), "f")
    signo = "-" if texto.startswith("-") else ""
    entero, _, decimales = texto.lstrip("-").partition(".")
    decimales = decimales.rstrip("0")
    miles = f"{int(entero):,}".replace(",", ".")
    return f"{signo}{miles},{decimales}" if decimales else f"{signo}{miles}"


def rotulo_de_rango(lower: float, upper: float) -> str:
    """El rango de un tramo con comparadores: «< 50.450», «≥ 50.450 y < 102.230,5», «≥ 102.230,5».

    Cerrado a la izquierda y abierto a la derecha, como OptBinning.
    """
    if math.isinf(lower) and math.isinf(upper):
        return "todos los valores"
    if math.isinf(lower):
        return f"< {formatear_borde(upper)}"
    if math.isinf(upper):
        return f"≥ {formatear_borde(lower)}"
    return f"≥ {formatear_borde(lower)} y < {formatear_borde(upper)}"


def rotulo_de_tramo(valor: Any) -> str:
    """Las categorías unidas con «, », un tramo auxiliar en palabras, o el texto tal cual.

    Es la regla que la pantalla aplica con ``normalizeBinLabel``. Un rango numérico sin sus bordes
    efectivos se deja como lo escribió el motor: redondeado no se puede reescribir sin arriesgar un
    borde falso.
    """
    if isinstance(valor, list | tuple) or (
        hasattr(valor, "tolist") and not isinstance(valor, str | bytes)
    ):
        elementos = valor.tolist() if hasattr(valor, "tolist") else list(valor)
        if isinstance(elementos, list):
            return ", ".join(str(elemento) for elemento in elementos)
    texto = str(valor)
    return AUX_BIN_LABELS.get(texto, texto)


def es_fila_de_totales(indice: Any, valor: Any) -> bool:
    """La fila de totales de una tabla de binning (índice ``Totals`` o etiqueta vacía o «Total»)."""
    return str(indice) == "Totals" or str(valor) in {"", "Totals", "Total"}


def rotulos_por_fila(tabla: Any, bordes: Any | None, variable: str) -> list[str]:
    """El rótulo legible de cada tramo, **en el orden de la tabla** y sin la fila de totales.

    Por posición y no por la etiqueta del motor: dos cortes que se redondean igual a dos decimales
    dan la misma etiqueta a dos tramos distintos (revisión adversarial del código, pasada 1). Los
    rangos numéricos se escriben desde ``bordes`` (``("binning", "bin_edges")``); si faltan o no
    calzan con los tramos regulares, se deja la etiqueta del motor.
    """
    filas = [
        fila.get("Bin")
        for indice, fila in tabla.iterrows()
        if not es_fila_de_totales(indice, fila.get("Bin"))
    ]
    n_regulares = sum(
        1 for valor in filas if not (isinstance(valor, str) and valor in AUX_BIN_LABELS)
    )
    rangos: list[tuple[float, float]] | None = None
    if bordes is not None and not bordes.empty and set(BIN_EDGES_COLUMNS) <= set(bordes.columns):
        propios = bordes.loc[bordes["variable"].astype(str).eq(variable)].sort_values("bin_index")
        if len(propios.index) == n_regulares and n_regulares > 0:
            rangos = [
                (float(inferior), float(superior))
                for inferior, superior in zip(propios["lower"], propios["upper"], strict=True)
            ]
    salida: list[str] = []
    posicion = 0
    for valor in filas:
        if isinstance(valor, str) and valor in AUX_BIN_LABELS:
            salida.append(AUX_BIN_LABELS[valor])
            continue
        if rangos is not None and isinstance(valor, str):
            salida.append(rotulo_de_rango(*rangos[posicion]))
        else:
            salida.append(rotulo_de_tramo(valor))
        posicion += 1
    return salida


def filas_que_casan(etiqueta: str, crudas: list[str], legibles: list[str]) -> list[int]:
    """Las filas con que casa la etiqueta de un ajuste manual de puntos (D-CPY-3).

    La etiqueta del motor tiene prioridad **global**: si coincide con la de alguna fila, casa con
    esas filas y con nada más, exactamente como antes. Sólo si no coincide con ninguna, puede casar
    con un rótulo legible, y sólo si ese rótulo es de **una** fila: un rótulo que nombra dos tramos
    —o que es a la vez la etiqueta del motor de otro, como una categoría llamada «Missing»— no
    casa (revisión adversarial del código, pasada 1).
    """
    exactas = [posicion for posicion, cruda in enumerate(crudas) if cruda == etiqueta]
    if exactas:
        return exactas
    por_rotulo = [posicion for posicion, legible in enumerate(legibles) if legible == etiqueta]
    return por_rotulo if len(por_rotulo) == 1 else []
