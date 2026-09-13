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
tal cual. Sólo se tocan las celdas de texto que empiezan por uno de esos prefijos; los números,
los lógicos, las fechas y el resto del texto viajan intactos. Hallazgo de la revisión adversarial
de la serie de mantenimiento posterior a la 1.14.0 (pasadas 2 y 3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    import pandas as pd

__all__ = ["FORMULA_PREFIXES", "neutralize_formula_prefixes"]

#: Primer carácter con el que una hoja de cálculo decide que la celda es una fórmula.
FORMULA_PREFIXES: Final[tuple[str, ...]] = ("=", "+", "-", "@", "\t", "\r")

_GUARD: Final = "'"


def _neutralize_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return _GUARD + value
    return value


def neutralize_formula_prefixes(frame: pd.DataFrame) -> pd.DataFrame:
    """Copia de ``frame`` con cada celda de texto que empieza por un prefijo activo protegida.

    Cubre todo lo que se convierte en una celda al exportar: los valores de las columnas de texto
    (``object``, ``string`` y ``category``, cuyos niveles son texto del usuario), los valores del
    índice, los nombres de las columnas y el nombre del índice. Anteponer una comilla simple es lo
    único que cambia; una categórica protegida sale como ``object`` en la copia. Devuelve el mismo
    objeto cuando no hay nada que proteger —así un export sin celdas activas sigue siendo byte a
    byte el de siempre— y nunca muta el frame recibido.
    """
    import pandas as pd  # local: el módulo no arrastra pandas al importarse

    result = frame
    for column in frame.columns:
        serie = frame[column]
        if not _is_text_like(serie):
            continue
        valores = serie.astype(object) if _is_categorical(serie) else serie
        protegida = valores.map(_neutralize_value)
        if not protegida.equals(valores):
            if result is frame:
                result = frame.copy(deep=True)
            result[column] = protegida
    if _is_text_like(frame.index):
        indice = pd.Index(
            [_neutralize_value(value) for value in frame.index], name=frame.index.name
        )
        if list(indice) != list(frame.index):
            if result is frame:
                result = frame.copy(deep=True)
            result.index = indice
    nombre = _neutralize_value(frame.index.name)
    if nombre != frame.index.name:
        if result is frame:
            result = frame.copy(deep=True)
        result.index = result.index.rename(nombre)
    columnas = [_neutralize_value(label) for label in frame.columns]
    if columnas != list(frame.columns):
        if result is frame:
            result = frame.copy(deep=True)
        result.columns = pd.Index(columnas, name=frame.columns.name)
    return result


def _is_categorical(values: Any) -> bool:
    import pandas as pd  # local: el módulo no arrastra pandas al importarse

    return isinstance(getattr(values, "dtype", None), pd.CategoricalDtype)


def _is_text_like(values: Any) -> bool:
    """``object``, ``string`` o ``category``: donde vive un texto que una planilla lea como fórmula.

    ``object`` cubre también una columna MIXTA —cohortes enteras y textuales juntas—, en la que
    ``is_string_dtype`` diría que no y dejaría pasar los textos que sí trae.
    """
    import pandas as pd  # local: el módulo no arrastra pandas al importarse

    dtype = getattr(values, "dtype", None)
    if dtype is None:
        return False
    return bool(pd.api.types.is_object_dtype(dtype)) or isinstance(
        dtype, pd.StringDtype | pd.CategoricalDtype
    )
