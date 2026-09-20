"""Tasa de malos por tramo y por muestra: el diagnóstico de monotonía fuera de desarrollo.

Enmienda FLUJO-GUIADO-SCORECARD §3.6-2 (D-FLU-6). Es un artefacto **aparte** —``("binning",
"event_rate_by_partition")``— con clave y golden propios: las tablas de binning y el ``summary``
no cambian de esquema, y un consumidor 1.x puede ignorarlo.

Metodología (constante, sin perilla):

- Los tramos son los fijados en desarrollo: ``bin_frame`` ya trae la etiqueta congelada de cada
  observación elegible. Se cuentan filas y malos por variable, tramo y muestra sobre las filas con
  target no nulo.
- La tendencia de referencia es la efectiva de desarrollo (``monotonic_trend`` resuelto del
  ``summary``). Un tramo ``inverts`` cuando el signo de la diferencia de tasa con el tramo
  anterior contradice esa tendencia; los empates (diferencia cero) no invierten; ``Special`` y
  ``Missing`` quedan fuera de la comparación; un tramo con menos de
  :data:`MIN_FILAS_POR_TRAMO` filas en la muestra no se evalúa (``inverts`` nulo), y tampoco se
  evalúa el tramo que lo sigue, porque no tiene con qué compararse.
- Sólo hay veredicto para tendencias ascendente o descendente (las que el motor resuelve para una
  variable numérica); con cualquier otra forma o sin tendencia —categóricas— ``inverts`` es nulo.

Sólo alerta; no descarta: el descarte sigue siendo decisión del usuario (``exclude``) o de la
selección en desarrollo.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final, cast

if TYPE_CHECKING:
    import pandas as pd
    from pandas import DataFrame

__all__ = [
    "EVENT_RATE_BY_PARTITION_COLUMNS",
    "MIN_FILAS_POR_TRAMO",
    "PARTICIONES_DIAGNOSTICO",
    "event_rate_by_partition",
]

#: Filas mínimas por tramo y muestra para evaluar la inversión. Es una **constante del
#: diagnóstico**, filas por tramo, no malos por partición: no tiene relación con
#: ``data.partition.min_bads_per_partition`` ni con ningún campo del config. Se elige por ser la
#: cifra que un validador ya reconoce como grupo mínimo (el default de Hosmer-Lemeshow).
MIN_FILAS_POR_TRAMO: Final = 30

#: Muestras que el diagnóstico recorre, en orden; una muestra ausente no produce filas.
PARTICIONES_DIAGNOSTICO: Final[tuple[str, ...]] = ("desarrollo", "holdout", "oot")

EVENT_RATE_BY_PARTITION_COLUMNS: Final[tuple[str, ...]] = (
    "feature",
    "bin_id",
    "bin_label",
    "partition",
    "n",
    "n_bad",
    "event_rate",
    "inverts",
)

_TRAMOS_ESPECIALES: Final[frozenset[str]] = frozenset({"Special", "Missing"})
_BIN_SUFFIX: Final = "__bin"


def event_rate_by_partition(
    *,
    bin_frame: pd.DataFrame,
    target: pd.Series,
    partition: pd.Series,
    tables: Mapping[str, pd.DataFrame],
    trends: Mapping[str, str | None],
) -> pd.DataFrame:
    """Una fila por variable, tramo y muestra, con ``inverts`` cuando se pudo evaluar.

    Parameters
    ----------
    bin_frame
        Las etiquetas congeladas ``<variable>__bin`` de cada fila elegible.
    target, partition
        El target 0/1 (nulo en las filas sin desempeño) y la muestra de cada fila, alineados por
        índice con ``bin_frame``.
    tables
        Las tablas de binning por variable (para el orden de los tramos, ``bin_id``).
    trends
        La tendencia efectiva de desarrollo por variable (``summary.monotonic_trend``).
    """
    pandas = importlib.import_module("pandas")  # perezoso: el binning importa liviano
    objetivo = pandas.to_numeric(target.reindex(bin_frame.index), errors="coerce")
    muestra = partition.reindex(bin_frame.index).astype("string")
    filas: list[dict[str, Any]] = []
    for columna in bin_frame.columns:
        if not str(columna).endswith(_BIN_SUFFIX):
            continue
        variable = str(columna)[: -len(_BIN_SUFFIX)]
        orden = _orden_de_tramos(tables.get(variable))
        etiquetas = bin_frame[columna].astype("string")
        tendencia = trends.get(variable)
        for particion in PARTICIONES_DIAGNOSTICO:
            en_muestra = muestra.eq(particion).fillna(False).astype(bool) & objetivo.notna()
            if not bool(en_muestra.any()):
                continue
            conteos = _conteos_por_tramo(etiquetas[en_muestra], objetivo[en_muestra])
            tramos = _tramos_ordenados(conteos, orden)
            inversiones = _inversiones(tramos, conteos, tendencia)
            for etiqueta, bin_id in tramos:
                n, n_bad = conteos[etiqueta]
                filas.append(
                    {
                        "feature": variable,
                        "bin_id": bin_id,
                        "bin_label": etiqueta,
                        "partition": particion,
                        "n": int(n),
                        "n_bad": int(n_bad),
                        "event_rate": (n_bad / n) if n else float("nan"),
                        "inverts": inversiones.get(etiqueta),
                    }
                )
    salida = pandas.DataFrame(filas, columns=list(EVENT_RATE_BY_PARTITION_COLUMNS))
    salida["bin_id"] = salida["bin_id"].astype("Int64")
    salida["inverts"] = salida["inverts"].astype("boolean")
    return cast("DataFrame", salida)


def _orden_de_tramos(tabla: pd.DataFrame | None) -> dict[str, int]:
    """El ``bin_id`` de cada etiqueta, en el orden de la tabla de binning de desarrollo.

    Las etiquetas categóricas del ``bin_frame`` (``['a', 'b']``) y de la tabla (``[a, b]``)
    difieren sólo en las comillas: se comparan sin ellas.
    """
    if tabla is None or "Bin" not in tabla.columns:
        return {}
    orden: dict[str, int] = {}
    for posicion, etiqueta in enumerate(tabla["Bin"].astype(str).tolist()):
        if etiqueta == "" or etiqueta == "Totals":
            continue
        orden.setdefault(_normalizar(etiqueta), posicion)
    return orden


def _normalizar(etiqueta: str) -> str:
    return etiqueta.replace("'", "").replace('"', "").strip()


def _conteos_por_tramo(etiquetas: pd.Series, objetivo: pd.Series) -> dict[str, tuple[int, int]]:
    pandas = importlib.import_module("pandas")
    agrupado = pandas.DataFrame({"tramo": etiquetas.astype(str), "malo": objetivo.astype(float)})
    resumen = agrupado.groupby("tramo", sort=False)["malo"].agg(["count", "sum"])
    return {
        str(tramo): (int(fila["count"]), int(fila["sum"])) for tramo, fila in resumen.iterrows()
    }


def _tramos_ordenados(
    conteos: Mapping[str, tuple[int, int]], orden: Mapping[str, int]
) -> list[tuple[str, int | None]]:
    """Las etiquetas presentes en la muestra con su ``bin_id``, en el orden de desarrollo."""
    con_id = [(etiqueta, orden.get(_normalizar(etiqueta))) for etiqueta in conteos]
    con_id.sort(key=lambda par: (par[1] is None, par[1] if par[1] is not None else 0, par[0]))
    return con_id


def _inversiones(
    tramos: list[tuple[str, int | None]],
    conteos: Mapping[str, tuple[int, int]],
    tendencia: str | None,
) -> dict[str, bool | None]:
    """``inverts`` por etiqueta: sólo con tendencia ascendente o descendente y tramos evaluables."""
    resultado: dict[str, bool | None] = dict.fromkeys((etiqueta for etiqueta, _ in tramos), None)
    if tendencia not in {"ascending", "descending"}:
        return resultado
    evaluables = [
        (etiqueta, bin_id)
        for etiqueta, bin_id in tramos
        if bin_id is not None and _normalizar(etiqueta) not in _TRAMOS_ESPECIALES
    ]
    anterior: tuple[str, float] | None = None
    for etiqueta, _ in evaluables:
        n, n_bad = conteos[etiqueta]
        if n < MIN_FILAS_POR_TRAMO:
            anterior = None  # el siguiente tampoco tiene con qué compararse
            continue
        tasa = n_bad / n
        if anterior is not None:
            delta = tasa - anterior[1]
            if delta == 0:
                resultado[etiqueta] = False
            elif tendencia == "ascending":
                resultado[etiqueta] = delta < 0
            else:
                resultado[etiqueta] = delta > 0
        anterior = (etiqueta, tasa)
    return resultado
