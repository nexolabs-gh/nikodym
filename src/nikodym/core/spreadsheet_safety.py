"""Neutraliza en una tabla los prefijos que una hoja de cálculo interpreta como fórmula.

Excel, LibreOffice y Google Sheets tratan una celda de TEXTO que empieza por ``=``, ``+``, ``-``,
``@``, tabulador o retorno de carro como una fórmula al abrir un CSV o un libro —*CSV/formula
injection*—: un valor ``=HYPERLINK("http://…";"ver")`` en una columna del archivo del usuario se
convierte en un enlace vivo, o en una llamada externa, en el escritorio de quien reciba el export.
Los archivos que Nikodym entrega para abrir en una planilla llevan datos que vienen del archivo
del usuario —el identificador de la operación, los niveles de una categórica, la cohorte que
etiqueta la tasa, y también los NOMBRES de sus columnas, que salen como encabezado— y ninguno los
produce el motor: por eso se neutralizan al EXPORTAR, no al calcular, y la mitigación es la que
recomienda OWASP: anteponer una comilla simple, que fuerza la celda a texto y deja el valor legible
tal cual. Sólo se tocan las celdas de texto que empiezan por uno de esos prefijos —o por la propia
comilla, para que la protección sea inyectiva—; los números, los lógicos, las fechas y el resto
del texto viajan intactos. Hallazgo de la revisión adversarial de la serie de mantenimiento
posterior a la 1.14.0 (pasadas 2, 3 y 4).
"""

from __future__ import annotations

import csv
import functools
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    import pandas as pd

__all__ = ["CSV_QUOTING", "FORMULA_PREFIXES", "neutralize_formula_prefixes"]

#: Cómo se citan los campos de todo CSV que Nikodym entrega para abrir en una planilla: TODO el
#: texto entre comillas y los números sin ellas (``csv.QUOTE_NONNUMERIC``). Así ningún lector
#: tiene que adivinar dónde termina un texto que trae comas, comillas o saltos, y los números se
#: siguen leyendo como números. No basta por sí solo contra un separador regional —un Excel con
#: ``;`` como separador de lista parte la línea por ``;`` ignorando el citado de comas—: de eso se
#: ocupa la guarda tras cada ``;`` y tabulador (:data:`_CELL_START`; pasada 10 de la revisión
#: adversarial).
CSV_QUOTING: Final = csv.QUOTE_NONNUMERIC

#: Primer carácter con el que una hoja de cálculo decide que la celda es una fórmula: los cuatro
#: operadores, sus variantes de ancho completo (U+FF1D, U+FF0B, U+FF0D y U+FF20, que las planillas
#: normalizan al abrir) y los tres controles con los que un texto "salta" a otra celda
#: (tabulador, CR y LF); pasada 5 de la revisión adversarial.
FORMULA_PREFIXES: Final[tuple[str, ...]] = (
    "=",
    "+",
    "-",
    "@",
    "\uff1d",  # FULLWIDTH EQUALS SIGN
    "\uff0b",  # FULLWIDTH PLUS SIGN
    "\uff0d",  # FULLWIDTH HYPHEN-MINUS
    "\uff20",  # FULLWIDTH COMMERCIAL AT
    "\t",
    "\r",
    "\n",
)

_GUARD: Final = "'"
#: Lo que recibe la comilla de guarda: un prefijo activo, o la propia comilla. Escapar también la
#: comilla es lo que hace INYECTIVA la protección: `=x` sale como `'=x` y un valor original `'=x`
#: como `''=x`, así que dos operaciones, cohortes, categorías o encabezados distintos nunca salen
#: byte-idénticos —una conciliación o un join sobre el export no los fundiría en silencio— (pasada
#: 4 de la revisión adversarial). Las imágenes de los tres grupos —empieza por comilla, empieza
#: por prefijo activo, el resto— no se cruzan.
_ESCAPED_PREFIXES: Final[tuple[str, ...]] = (*FORMULA_PREFIXES, _GUARD)
#: Dónde una planilla puede EMPEZAR una celda dentro de un texto: al principio, tras un ``;``, un
#: tabulador o un salto de línea (CRLF, CR o LF, sin partir el CRLF). Un Excel cuyo separador de
#: lista es ``;`` (es-CL, es-ES) abre un CSV de comas partiendo cada línea por ``;`` e ignorando el
#: citado de comas, así que ``texto;=SUM(A1)`` —aunque viaje entre comillas— se convertía en dos
#: celdas, la segunda una fórmula viva; y un texto multilínea abría una FILA nueva tras el salto
#: (pasadas 10 y 11 de la revisión adversarial). La guarda se antepone en cada uno de esos puntos;
#: la coma no hace falta: es el separador del archivo y el citado la protege.
_ACTIVE: Final = "(?=[" + "".join(re.escape(c) for c in _ESCAPED_PREFIXES) + "])"
_CELL_START_WITH_BREAKS: Final = re.compile("(^|\r\n|\r(?!\n)|[;\t\n])" + _ACTIVE)
#: En un libro XLSX cada celda es una celda: ``;``, el tabulador y los saltos no abren otra, y la
#: guarda tras ellos sólo alteraba datos legítimos (pasada 13). Ahí se protege sólo el inicio.
_CELL_START_ONLY: Final = re.compile("(^)" + _ACTIVE)


def _neutralize_value(value: Any, *, cell_breaks: bool = True) -> Any:
    patron = _CELL_START_WITH_BREAKS if cell_breaks else _CELL_START_ONLY
    if isinstance(value, str) and patron.search(value):
        return patron.sub(lambda m: m.group(1) + _GUARD, value)
    return value


def neutralize_formula_prefixes(frame: pd.DataFrame, *, cell_breaks: bool = True) -> pd.DataFrame:
    """Copia de ``frame`` con cada celda de texto que empieza por un prefijo activo protegida.

    Cubre todo lo que se convierte en una celda al exportar: los valores de las columnas de texto
    (``object``, ``string``, ``category`` y cualquier dtype que no sea numérico ni temporal), los
    valores del índice, los nombres de las columnas y el nombre del índice. Anteponer una comilla
    simple es lo único que cambia; una categórica protegida sale como ``object`` en la copia.
    Devuelve el mismo objeto cuando no hay nada que proteger —así un export sin celdas activas
    sigue siendo byte a byte el de siempre— y nunca muta el frame recibido.

    ``cell_breaks`` es la política por formato: en un CSV (``True``) la guarda va también tras
    cada ``;``, tabulador y salto de línea, porque una planilla con otro separador regional los
    convierte en celda o fila nueva; en un libro XLSX (``False``) una celda es una celda, y sólo se
    protege su inicio para no alterar datos legítimos.
    """
    guard = functools.partial(_neutralize_value, cell_breaks=cell_breaks)
    result = frame
    # Por POSICIÓN, no por etiqueta: con una etiqueta repetida `frame[etiqueta]` devuelve un
    # DataFrame sin `dtype` y las dos columnas quedaban sin sanear (pasada 8 de la revisión
    # adversarial). Nadie exige etiquetas únicas en las tablas que se exportan.
    for position in range(frame.shape[1]):
        serie = frame.iloc[:, position]
        if not _is_text_like(serie):
            continue
        valores = serie.astype(object) if _is_categorical(serie) else serie
        protegida = valores.map(guard)
        if not protegida.equals(valores):
            if result is frame:
                result = frame.copy(deep=True)
            result.isetitem(position, protegida.to_numpy())
    # Las etiquetas de filas y de columnas también son celdas: valores y nombres, nivel a nivel
    # si son un `MultiIndex` (los writers de pandas separan cada nivel en su celda; pasada 9).
    indice = _neutralize_labels(frame.index, guard)
    if indice is not None:
        if result is frame:
            result = frame.copy(deep=True)
        result.index = indice
    columnas = _neutralize_labels(frame.columns, guard)
    if columnas is not None:
        if result is frame:
            result = frame.copy(deep=True)
        result.columns = columnas
    return result


def _neutralize_labels(labels: pd.Index, guard: Callable[[Any], Any]) -> pd.Index | None:
    """El índice con sus valores y nombres protegidos, o ``None`` si nada cambia.

    Un ``MultiIndex`` se reconstruye tupla a tupla y nombre a nombre, conservando su estructura;
    un índice plano se toca sólo si es de texto (o mixto), y su nombre siempre se mira.
    """
    import pandas as pd  # local: el módulo no arrastra pandas al importarse

    nombres = [guard(nombre) for nombre in labels.names]
    nombres_cambian = nombres != list(labels.names)
    if isinstance(labels, pd.MultiIndex):
        tuplas = [tuple(guard(value) for value in tupla) for tupla in labels]
        if tuplas != list(labels):
            return pd.MultiIndex.from_tuples(tuplas, names=nombres)
        return labels.set_names(nombres) if nombres_cambian else None
    valores = [guard(value) for value in labels] if _is_text_like(labels) else list(labels)
    if valores != list(labels):
        protegido: pd.Index = pd.Index(valores, name=nombres[0])
        return protegido
    return labels.rename(nombres[0]) if nombres_cambian else None


def _is_categorical(values: Any) -> bool:
    import pandas as pd  # local: el módulo no arrastra pandas al importarse

    return isinstance(getattr(values, "dtype", None), pd.CategoricalDtype)


def _is_text_like(values: Any) -> bool:
    """Todo lo que NO sea numérico, lógico ni temporal: ahí puede vivir un texto.

    La clasificación va por exclusión a propósito: enumerar los dtypes de texto (``object``,
    ``string``, ``category``) dejaba fuera los que la propia pila admite y nadie listó —una
    columna Arrow de texto, ``pd.ArrowDtype(pa.string())``, pasaba con su fórmula intacta
    (pasada 12 de la revisión adversarial)—. Recorrer de más no cuesta nada, porque el
    neutralizador sólo toca ``str``; lo que sí es numérico, lógico o de fecha se salta para que
    conserve su tipo. ``object`` cubre también una columna MIXTA —cohortes enteras y textuales
    juntas—, en la que ``is_string_dtype`` diría que no y dejaría pasar los textos que sí trae.
    """
    import pandas as pd  # local: el módulo no arrastra pandas al importarse

    dtype = getattr(values, "dtype", None)
    if dtype is None:
        return False
    tipos = pd.api.types
    return not (
        tipos.is_numeric_dtype(dtype)
        or tipos.is_bool_dtype(dtype)
        or tipos.is_datetime64_any_dtype(dtype)
        or tipos.is_timedelta64_dtype(dtype)
    )
