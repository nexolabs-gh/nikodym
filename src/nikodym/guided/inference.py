"""Lo que la puerta guiada infiere del archivo, y cómo lo declara (D-FLU-1, D-SIM-2).

Cada inferencia es una regla fija —no configurable (D-FLU-12)— que se aplica sobre el frame ya
cargado y se emite al trail como ``decision`` con ``autor="puerta_guiada"`` y su motivo, para que
quien quiera cambiarla sepa exactamente qué cambió. Lo institucional (qué es «malo», la frontera
fuera de tiempo) **no** se infiere: aquí sólo se sugiere el valor con el que la puerta se detiene
antes de correr (D-OBL-5).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import pandas as pd

__all__ = [
    "AUTOR_PUERTA",
    "Inferencia",
    "columnas_categoricas",
    "columnas_esquema",
    "columnas_predictoras",
    "dtype_logico",
    "sugerir_oot_cohorts",
    "sugerir_oot_from",
]

#: Autor con que la puerta firma sus inferencias en el trail (D-SIM-6: las decisiones humanas van
#: con ``autor="usuario"``; las de la puerta, con éste).
AUTOR_PUERTA: Final = "puerta_guiada"

#: Meses de cobertura a partir de los cuales la sugerencia de frontera OOT son «los últimos 12
#: meses»; por debajo, el último cuarto de los meses cubiertos (§8-2 de la enmienda, como
#: sugerencia y no como default: la frontera se exige, D-OBL-5).
_MESES_PARA_SUGERIR_UN_ANIO: Final = 24
_FRACCION_OOT_SUGERIDA: Final = 0.25


@dataclass(frozen=True, slots=True)
class Inferencia:
    """Una inferencia de la puerta, lista para emitirse al trail como ``decision``."""

    regla: str
    valor: Any
    motivo: str

    def payload(self) -> dict[str, Any]:
        """Los seis campos que materializa ``DecisionRecord`` más ``autor`` y ``motivo``."""
        return {
            "regla": self.regla,
            "umbral": None,
            "valor": self.valor,
            "accion": "declarar",
            "autor": AUTOR_PUERTA,
            "motivo": self.motivo,
        }


def dtype_logico(serie: pd.Series) -> str:
    """El dtype lógico de ``data.schema`` que describe una columna del frame.

    Regla fija: booleano → ``bool``; entero → ``int``; real → ``float``; fecha → ``datetime``;
    categoría de pandas → ``category``; todo lo demás (texto, objeto) → ``str``.
    """
    dtype = serie.dtype
    if isinstance(dtype, pd.CategoricalDtype):
        return "category"
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    if pd.api.types.is_integer_dtype(dtype):
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    return "str"


def columnas_esquema(frame: pd.DataFrame, *, fechas: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Las ``ColumnSpec`` de ``data.schema.columns`` inferidas de los dtypes del frame.

    ``nullable`` se declara medido: es verdadero sólo si la columna trae vacíos. Las columnas de
    ``fechas`` —el eje temporal que el usuario nombró— se declaran ``datetime`` con coacción, para
    que un archivo que trae la fecha como texto (``2024-01-15``) entre igual: la partición temporal
    y el análisis exploratorio exigen una fecha de verdad.
    """
    fechas_declaradas = set(fechas)
    columnas: list[dict[str, Any]] = []
    for nombre in frame.columns:
        serie = frame[nombre]
        if str(nombre) in fechas_declaradas:
            dtype, coerce = "datetime", True
        else:
            dtype, coerce = dtype_logico(serie), False
        columnas.append(
            {
                "name": str(nombre),
                "dtype": dtype,
                "nullable": bool(serie.isna().any()),
                "required": True,
                "coerce": coerce,
                "ge": None,
                "le": None,
                "isin": None,
                "unique": False,
            }
        )
    return columnas


def columnas_predictoras(
    frame: pd.DataFrame, *, excluidas: Mapping[str, str]
) -> tuple[tuple[str, ...], dict[str, str]]:
    """Las columnas candidatas a predictoras y, por cada excluida, su motivo.

    Se excluyen las que ``excluidas`` nombra (identificador, columnas de la regla del target por
    D-FUGA, fecha o cohorte de la partición) y las de tipo fecha, que el binning tampoco admite.
    """
    incluidas: list[str] = []
    motivos: dict[str, str] = {}
    for nombre in frame.columns:
        columna = str(nombre)
        if columna in excluidas:
            motivos[columna] = excluidas[columna]
            continue
        if pd.api.types.is_datetime64_any_dtype(frame[nombre].dtype):
            motivos[columna] = "columna de fecha: no se tramifica"
            continue
        incluidas.append(columna)
    return tuple(incluidas), motivos


def columnas_categoricas(frame: pd.DataFrame, predictoras: Sequence[str]) -> tuple[str, ...]:
    """Las predictoras de texto, categoría o booleanas: entran al binning como categóricas."""
    return tuple(
        columna
        for columna in predictoras
        if dtype_logico(frame[columna]) in {"str", "category", "bool"}
    )


def sugerir_oot_from(fechas: pd.Series) -> tuple[str, str, int, str]:
    """Rango cubierto por la columna de fecha y la frontera OOT que la puerta usaría.

    Devuelve ``(primera, última, meses_cubiertos, sugerencia)`` con las fechas en ISO. La
    sugerencia son los últimos 12 meses si el archivo cubre al menos 24; si no, el último cuarto
    de los meses cubiertos (al menos uno). Es una sugerencia que se muestra: la frontera la fija
    la institución (D-OBL-5).
    """
    valores = pd.to_datetime(fechas, errors="coerce").dropna()
    if valores.empty:
        raise ValueError("la columna de fecha no trae ninguna fecha legible.")
    primera = valores.min()
    ultima = valores.max()
    meses = (ultima.year - primera.year) * 12 + (ultima.month - primera.month) + 1
    if meses >= _MESES_PARA_SUGERIR_UN_ANIO:
        meses_oot = 12
    else:
        meses_oot = max(1, math.ceil(meses * _FRACCION_OOT_SUGERIDA))
    inicio_oot = (ultima.to_period("M") - (meses_oot - 1)).to_timestamp()
    return (
        primera.date().isoformat(),
        ultima.date().isoformat(),
        int(meses),
        inicio_oot.date().isoformat(),
    )


def sugerir_oot_cohorts(cohortes: pd.Series) -> tuple[list[str], list[str]]:
    """Las cohortes distintas, ordenadas, y las que la puerta reservaría como OOT.

    La sugerencia es el último cuarto de las cohortes (al menos una) en orden lexicográfico, que
    es el orden cronológico de las añadas escritas como ``2024Q1`` o ``2024-01``.
    """
    distintas = sorted({str(valor) for valor in cohortes.dropna().unique()})
    if not distintas:
        raise ValueError("la columna de cohorte no trae ningún valor.")
    n_oot = max(1, math.ceil(len(distintas) * _FRACCION_OOT_SUGERIDA))
    return distintas, distintas[-n_oot:]
