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
from typing import Any, Final

__all__ = [
    "AUX_BIN_LABELS",
    "BIN_EDGES_COLUMNS",
    "formatear_borde",
    "rotulo_de_rango",
    "rotulo_de_tramo",
    "rotulos_de_tramos",
]

#: Los tramos auxiliares de OptBinning, dichos para quien lee (enmienda COPY-PRUEBA-REAL-SBA).
AUX_BIN_LABELS: dict[str, str] = {
    "Missing": "Faltantes",
    "Special": "Valores especiales",
}
#: Las columnas de ``("binning", "bin_edges")``: un tramo regular por fila, con sus bordes
#: efectivos a precisión completa (no la etiqueta de OptBinning, redondeada a dos decimales).
BIN_EDGES_COLUMNS: tuple[str, ...] = ("variable", "bin_index", "lower", "upper")


#: El máximo de decimales con que se escribe un borde; basta para cualquier corte en float32.
_MAX_DECIMALES: Final = 12


def formatear_borde(valor: float) -> str:
    """Un borde de tramo en es-CL, con los decimales que el motor distingue y ni uno más.

    Los cortes de OptBinning son puntos medios entre valores en float32 —``242795.8828125``,
    ``0.37409999966…``— y su etiqueta los redondea a dos decimales, lo que puede afirmar un borde
    falso (``7.12`` para un corte en ``7.12345``). Se escribe con la **menor cantidad de decimales
    que queda dentro de medio ulp de float32** del corte efectivo: a esa precisión trabaja el
    motor, y ningún dato en float32 cae entre el borde escrito y el real. ``242.795,88``,
    ``0,3741``, ``7,12345``; un corte declarado a mano (``50450``, ``7,5``) sale tal como se
    escribió. Punto de miles, coma decimal y sin ceros de relleno.
    """
    if math.isinf(valor):
        return "-∞" if valor < 0 else "∞"
    if valor == 0:
        return "0"
    tolerancia = 2.0 ** (math.floor(math.log2(abs(valor))) - 24)
    decimales = 0
    while decimales < _MAX_DECIMALES and abs(round(valor, decimales) - valor) >= tolerancia:
        decimales += 1
    texto = f"{round(valor, decimales):,.{decimales}f}"
    if texto.startswith("-") and float(texto.replace(",", "")) == 0:
        texto = texto[1:]
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


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


def rotulos_de_tramos(tabla: Any, bordes: Any | None, variable: str) -> dict[str, str]:
    """El rótulo legible de cada tramo de una variable, por su etiqueta del motor (``str(Bin)``).

    La etiqueta del motor sigue siendo la clave de todo lo que casa por tramo —la tabla de puntos,
    el bundle, los cortes fijados—; esto sólo dice cómo se lee. Los rangos numéricos se escriben
    desde ``bordes`` (``("binning", "bin_edges")``); si faltan o no calzan con la tabla, se deja la
    etiqueta del motor.
    """
    filas = [
        fila
        for indice, fila in tabla.iterrows()
        if str(indice) != "Totals" and str(fila.get("Bin")) != ""
    ]
    regulares = [
        fila
        for fila in filas
        if not (isinstance(fila.get("Bin"), str) and fila.get("Bin") in AUX_BIN_LABELS)
    ]
    rangos: list[tuple[float, float]] | None = None
    if bordes is not None and not bordes.empty and set(BIN_EDGES_COLUMNS) <= set(bordes.columns):
        propios = bordes.loc[bordes["variable"].astype(str).eq(variable)].sort_values("bin_index")
        if len(propios.index) == len(regulares) and len(regulares) > 0:
            rangos = [
                (float(inferior), float(superior))
                for inferior, superior in zip(propios["lower"], propios["upper"], strict=True)
            ]
    salida: dict[str, str] = {}
    posicion = 0
    for fila in filas:
        valor = fila.get("Bin")
        crudo = str(valor)
        if isinstance(valor, str) and valor in AUX_BIN_LABELS:
            salida[crudo] = AUX_BIN_LABELS[valor]
            continue
        if rangos is not None and isinstance(valor, str):
            salida[crudo] = rotulo_de_rango(*rangos[posicion])
        else:
            salida[crudo] = rotulo_de_tramo(valor)
        posicion += 1
    return salida
