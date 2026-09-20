"""IV por variable y por muestra: el diagnóstico que un validador pregunta primero.

Enmienda FLUJO-GUIADO-SCORECARD §3.6-1 (D-FLU-6). Es un artefacto **aparte** —``("selection",
"iv_by_partition")``— con clave y golden propios: ``selection_table`` conserva su esquema y el
descarte sigue siendo por ``min_iv`` en desarrollo.

Metodología (constante, sin perilla): los tramos son los fijados en desarrollo (``bin_frame``
trae la etiqueta congelada de cada fila elegible); sobre las filas de cada muestra con target no
nulo se calcula el IV con la fórmula de SDD-06/SDD-07 —``IV = Σ_b (%buenos_b - %malos_b) ·
ln(%buenos_b / %malos_b)``— con las distribuciones **de esa muestra**, así que el IV de
desarrollo coincide con el que publica el binning. ``Special`` y ``Missing`` cuentan como tramos
si existen; un tramo sin malos o sin buenos en la muestra no aporta (el logaritmo no está
definido), que es la convención de OptBinning para los tramos vacíos. Casos borde: muestra ausente
→ sin fila; muestra con una sola clase → ``iv`` nulo con causa ``single_class``. No hay umbral de
filas propio: ``data.partition.min_bads_per_partition`` ya garantiza los malos mínimos de cada
muestra con target, y ese es el único criterio de tamaño.
"""

from __future__ import annotations

import importlib
import math
from typing import TYPE_CHECKING, Any, Final, cast

if TYPE_CHECKING:
    import pandas as pd
    from pandas import DataFrame

__all__ = ["IV_BY_PARTITION_COLUMNS", "PARTICIONES_DIAGNOSTICO", "iv_by_partition"]

PARTICIONES_DIAGNOSTICO: Final[tuple[str, ...]] = ("desarrollo", "holdout", "oot")
IV_BY_PARTITION_COLUMNS: Final[tuple[str, ...]] = (
    "feature",
    "partition",
    "n",
    "n_bad",
    "iv",
    "not_evaluable_reason",
)
_BIN_SUFFIX: Final = "__bin"
_SINGLE_CLASS: Final = "single_class"


def iv_by_partition(
    *, bin_frame: pd.DataFrame, target: pd.Series, partition: pd.Series
) -> pd.DataFrame:
    """Una fila por variable tramificada y muestra presente, con el IV de esa muestra."""
    pandas = importlib.import_module("pandas")  # perezoso: la selección importa liviano
    objetivo = pandas.to_numeric(target.reindex(bin_frame.index), errors="coerce")
    muestra = partition.reindex(bin_frame.index).astype("string")
    filas: list[dict[str, Any]] = []
    for columna in bin_frame.columns:
        if not str(columna).endswith(_BIN_SUFFIX):
            continue
        variable = str(columna)[: -len(_BIN_SUFFIX)]
        etiquetas = bin_frame[columna].astype(str)
        for particion in PARTICIONES_DIAGNOSTICO:
            en_muestra = muestra.eq(particion).fillna(False).astype(bool) & objetivo.notna()
            if not bool(en_muestra.any()):
                continue
            y = objetivo[en_muestra]
            n = len(y)
            n_bad = int(y.sum())
            if n_bad == 0 or n_bad == n:
                filas.append(_fila(variable, particion, n, n_bad, None, _SINGLE_CLASS))
                continue
            filas.append(_fila(variable, particion, n, n_bad, _iv(etiquetas[en_muestra], y), None))
    salida = pandas.DataFrame(filas, columns=list(IV_BY_PARTITION_COLUMNS))
    salida["iv"] = salida["iv"].astype("Float64")
    return cast("DataFrame", salida)


def _iv(etiquetas: pd.Series, y: pd.Series) -> float:
    """La fórmula de SDD-06 sobre los tramos presentes en la muestra."""
    pandas = importlib.import_module("pandas")
    agrupado = pandas.DataFrame({"tramo": etiquetas, "malo": y.astype(float)})
    conteos = agrupado.groupby("tramo", sort=False)["malo"].agg(["count", "sum"])
    total_bad = float(conteos["sum"].sum())
    total_good = float(conteos["count"].sum() - total_bad)
    iv = 0.0
    for _, fila in conteos.iterrows():
        bad = float(fila["sum"])
        good = float(fila["count"]) - bad
        if bad <= 0.0 or good <= 0.0:
            continue
        p_bad = bad / total_bad
        p_good = good / total_good
        iv += (p_good - p_bad) * math.log(p_good / p_bad)
    return iv


def _fila(
    variable: str, particion: str, n: int, n_bad: int, iv: float | None, causa: str | None
) -> dict[str, Any]:
    return {
        "feature": variable,
        "partition": particion,
        "n": n,
        "n_bad": n_bad,
        "iv": iv,
        "not_evaluable_reason": causa,
    }
