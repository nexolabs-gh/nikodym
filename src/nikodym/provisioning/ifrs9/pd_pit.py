"""Transformación PD point-in-time y derivación de horizontes 12m/lifetime (SDD-16 §3/§7).

Dos funciones puras que alimentan el motor ECL sin estado propio:

- :func:`vasicek_pit` transforma una PD through-the-cycle (TTC) a base point-in-time (PIT) con el
  modelo monofactorial de Vasicek ``PD_pit = Phi((PhiInv(PD_ttc) - sqrt(rho)*Z) / sqrt(1 - rho))``.
  La orientación es fija (ESPEC §5.5): ``Z<0`` (recesión) sube la PD y ``Z>0`` (expansión) la baja;
  el signo ``-sqrt(rho)*Z`` implementa esa convención. La PD TTC es el esperado ``E_Z[PD_pit]``, no
  la evaluación en ``Z=0`` (efecto Jensen): ``PD_pit(Z=0) != PD_ttc`` para ``rho>0``.
- :func:`marginal_to_horizon` deriva ``PD_12m`` (suma de PD marginales hasta ``horizon_periods``) y
  ``PD_life`` (suma de todas las PD marginales, ``= PD_cum(T_max)``) por entidad/curva.

``scipy.stats.norm`` (``Phi``/``PhiInv``) se importa de forma perezosa dentro de la función porque
es una dependencia pesada del extra ``scoring``: ni ``import nikodym.core`` ni
``import nikodym.provisioning.ifrs9`` deben arrastrar ``scipy``/``pandas``/``numpy`` en top-level.
Las validaciones de rango levantan :class:`~nikodym.provisioning.ifrs9.exceptions.IfrsPdError` con
mensaje en español; la salida nunca se clipa en silencio y ``-0.0`` se normaliza a ``0.0``.

Nomenclatura IFRS 9 (regla dura D-CONV-1): ``pd``/``lgd``/``ead``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9.exceptions import IfrsPdError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    DataFrame: TypeAlias = pd.DataFrame
else:
    NDArrayFloat: TypeAlias = Any
    DataFrame: TypeAlias = Any

__all__ = ["marginal_to_horizon", "vasicek_pit"]

# Epsilon de clip para PD_TTC antes de PhiInv: evita +/-inf en 0/1 sin distorsionar PDs reales
# (queda cómodamente lejos de los bordes representables de la doble precisión cerca de 0 y 1).
_PD_CLIP_EPS: float = 1e-12
# Tolerancia absoluta para exigir que la PD lifetime acumulada no supere 1 (PD es probabilidad).
_PD_SUM_TOL: float = 1e-9
# Columnas mínimas del contrato tidy de term-structure que consume ``marginal_to_horizon``.
_REQUIRED_TS_COLUMNS: tuple[str, ...] = ("row_id", "period", "pd_marginal")
_SCIPY_EXTRA_MESSAGE = "vasicek_pit requiere scipy para Phi/PhiInv; instale nikodym[scoring]."


def vasicek_pit(pd_ttc: NDArrayFloat, *, rho: float, z: NDArrayFloat) -> NDArrayFloat:
    """Transforma la PD TTC a PD point-in-time con el modelo monofactorial de Vasicek.

    Calcula ``PD_pit = Phi((PhiInv(PD_ttc) - sqrt(rho)*Z) / sqrt(1 - rho))`` con orientación fija
    (ESPEC §5.5): ``Z<0`` (recesión) sube la PD y ``Z>0`` (expansión) la baja. ``pd_ttc`` se clipa a
    ``[eps, 1-eps]`` antes de ``PhiInv`` para evitar ``+/-inf`` en 0/1. La salida se valida en
    ``[0, 1]`` sin clip silencioso (fuera de rango levanta :class:`IfrsPdError`) y ``-0.0`` se
    normaliza a ``0.0``. ``pd_ttc`` y ``z`` se difunden (broadcasting) según numpy.

    Parameters
    ----------
    pd_ttc
        PD through-the-cycle por período (o fila x período), en ``[0, 1]``.
    rho
        Correlación de activos monofactorial, en el intervalo abierto ``(0, 1)``.
    z
        Factor sistémico ``Z ~ N(0, 1)`` por escenario/período.

    Returns
    -------
    numpy.ndarray
        PD point-in-time con la misma forma difundida de ``pd_ttc`` y ``z``, en ``[0, 1]``.

    Raises
    ------
    IfrsPdError
        Si ``rho`` cae fuera de ``(0, 1)``, ``pd_ttc`` fuera de ``[0, 1]``, ``z`` o la PD resultante
        no son finitos, o la PD PIT resultante cae fuera de ``[0, 1]``.
    """
    if not math.isfinite(rho) or not 0.0 < rho < 1.0:
        raise IfrsPdError(f"rho debe estar en el intervalo abierto (0, 1); valor: {rho!r}.")

    numpy = _import_numpy()
    pd_ttc_arr = numpy.asarray(pd_ttc, dtype=numpy.float64)
    z_arr = numpy.asarray(z, dtype=numpy.float64)

    if not bool(numpy.all(numpy.isfinite(pd_ttc_arr))):
        raise IfrsPdError("pd_ttc debe contener sólo valores finitos.")
    if bool(numpy.any(pd_ttc_arr < 0.0)) or bool(numpy.any(pd_ttc_arr > 1.0)):
        raise IfrsPdError("pd_ttc debe estar en [0, 1].")
    if not bool(numpy.all(numpy.isfinite(z_arr))):
        raise IfrsPdError("El factor sistémico Z debe contener sólo valores finitos.")

    norm = _import_scipy_norm()
    clipped = numpy.clip(pd_ttc_arr, _PD_CLIP_EPS, 1.0 - _PD_CLIP_EPS)
    quantile = numpy.asarray(norm.ppf(clipped), dtype=numpy.float64)
    argument = (quantile - math.sqrt(rho) * z_arr) / math.sqrt(1.0 - rho)
    pd_pit = numpy.asarray(norm.cdf(argument), dtype=numpy.float64)

    if not bool(numpy.all(numpy.isfinite(pd_pit))):
        raise IfrsPdError("La PD PIT resultante no es finita.")
    if bool(numpy.any(pd_pit < 0.0)) or bool(numpy.any(pd_pit > 1.0)):
        raise IfrsPdError("La PD PIT resultante cayó fuera de [0, 1]; no se clipa en silencio.")

    normalized = numpy.where(pd_pit == 0.0, 0.0, pd_pit)
    return cast("NDArrayFloat", normalized)


def marginal_to_horizon(term_structure: DataFrame, *, horizon_periods: int) -> DataFrame:
    """Deriva la PD 12m y la PD lifetime por entidad desde una term-structure tidy de PD marginal.

    Agrupa la term-structure larga por ``row_id`` (y ``scenario`` si la columna existe) y calcula
    ``PD_12m = sum(PD_marginal | period <= horizon_periods)`` y ``PD_life = sum(PD_marginal)``
    (``= PD_cum(T_max)``). No muta la entrada (usa copia defensiva). Valida el contrato mínimo
    ``(row_id, period, pd_marginal)``, ``pd_marginal`` finita en ``[0, 1]``, ``period`` entero
    ``>= 1`` y que la PD lifetime acumulada no supere 1; ``-0.0`` se normaliza a ``0.0``.

    Parameters
    ----------
    term_structure
        DataFrame tidy en formato largo con, al menos, ``row_id``, ``period`` y ``pd_marginal``;
        ``scenario`` es opcional y, si está presente, entra a la clave de agregación.
    horizon_periods
        Períodos que cubren el horizonte 12m (mensual=12, trimestral=4, anual=1); debe ser ``>= 1``.

    Returns
    -------
    pandas.DataFrame
        Una fila por entidad con las columnas de agregación (``row_id`` y, si aplica, ``scenario``)
        más ``pd_12m`` y ``pd_life``.

    Raises
    ------
    IfrsPdError
        Si ``horizon_periods < 1``, faltan columnas requeridas, ``pd_marginal`` no es finita o cae
        fuera de ``[0, 1]``, ``period`` no es un entero ``>= 1``, o la PD lifetime supera 1.
    """
    if horizon_periods < 1:
        raise IfrsPdError(
            f"horizon_periods debe ser mayor o igual a 1; valor: {horizon_periods!r}."
        )

    faltantes = [col for col in _REQUIRED_TS_COLUMNS if col not in term_structure.columns]
    if faltantes:
        raise IfrsPdError(
            f"term_structure debe contener {_REQUIRED_TS_COLUMNS}; columnas faltantes: {faltantes}."
        )

    numpy = _import_numpy()

    group_cols = ["row_id"]
    if "scenario" in term_structure.columns:
        group_cols.append("scenario")
    working = term_structure.loc[:, [*group_cols, "period", "pd_marginal"]].copy(deep=True)

    period = numpy.asarray(working["period"].to_numpy(), dtype=numpy.float64)
    if not bool(numpy.all(numpy.isfinite(period))):
        raise IfrsPdError("period debe contener sólo enteros finitos.")
    if bool(numpy.any(period < 1.0)) or bool(numpy.any(period != numpy.floor(period))):
        raise IfrsPdError("period debe ser un entero mayor o igual a 1.")

    marginal = numpy.asarray(working["pd_marginal"].to_numpy(), dtype=numpy.float64)
    if not bool(numpy.all(numpy.isfinite(marginal))):
        raise IfrsPdError("pd_marginal debe contener sólo valores finitos.")
    if bool(numpy.any(marginal < 0.0)) or bool(numpy.any(marginal > 1.0)):
        raise IfrsPdError("pd_marginal debe estar en [0, 1].")

    within_12m = working["period"] <= horizon_periods
    working["_pd_marginal_12m"] = working["pd_marginal"].where(within_12m, 0.0)
    aggregated = working.groupby(group_cols, dropna=False, sort=False).agg(
        pd_12m=("_pd_marginal_12m", "sum"),
        pd_life=("pd_marginal", "sum"),
    )
    result = aggregated.reset_index()

    pd_life_values = numpy.asarray(result["pd_life"].to_numpy(), dtype=numpy.float64)
    if bool(numpy.any(pd_life_values > 1.0 + _PD_SUM_TOL)):
        raise IfrsPdError(
            "La PD lifetime acumulada superó 1; term-structure inconsistente (PD es probabilidad)."
        )

    for columna in ("pd_12m", "pd_life"):
        valores = numpy.asarray(result[columna].to_numpy(), dtype=numpy.float64)
        result[columna] = numpy.where(valores == 0.0, 0.0, valores)

    return result


def _import_numpy() -> Any:
    """Importa ``numpy`` bajo demanda para preservar el import liviano del núcleo."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("vasicek_pit requiere numpy.") from exc


def _import_scipy_norm() -> Any:
    """Importa ``scipy.stats.norm`` bajo demanda (dependencia pesada del extra ``scoring``)."""
    try:
        stats = importlib.import_module("scipy.stats")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCIPY_EXTRA_MESSAGE) from exc
    return stats.norm
