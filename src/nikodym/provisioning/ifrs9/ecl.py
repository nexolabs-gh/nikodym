"""Motor ECL marginal por período con descuento a EIR y multiescenario (SDD-16 §3/§7).

:class:`EclEngine` evalúa la pérdida crediticia esperada IFRS 9 fila a fila desde una malla tidy de
componentes ya alineada por ``(row_id, scenario, period)`` (PD marginal, LGD, EAD y ``time_value``),
la EIR por instrumento y el stage por operación. Implementa la fórmula canónica del SDD-16 §3::

    ECL = Σ_k w_k · Σ_t [ PD_marg_k(t) · LGD_k(t) · EAD_k(t) · DF(t) ]

- **Motor marginal.** Para cada componente ``ecl_marginal = PD_marg · LGD · EAD · DF``, con
  ``DF(t) = (1 + EIR)^(-tau(t))``. La convención de ``tau(t)`` la fija
  ``IfrsEclConfig.discount_convention`` (D-IFRS-9): ``annual_eir_year_fraction`` usa
  ``tau(t) = time_value`` (fracción de año) y ``period_eir`` usa ``tau(t) = period`` (índice de
  período). El factor de descuento se valida en ``(0, 1]`` sin clip silencioso (fuera de rango o no
  finito levanta :class:`IfrsEclError`).
- **Truncado por horizonte según stage.** ``ECL 12m`` suma los períodos ``period <= horizon_12m``;
  ``ECL lifetime`` suma hasta ``max_lifetime`` (o todo el soporte si es ``None``).
  ``H(1)=horizon_12m`` (Stage 1); ``H(2)=H(3)=max_lifetime`` (Stage 2/3).
- **Ponderación de outputs multiescenario.** ``ECL_reportado = Σ_k w_k · ECL_k``; se ponderan los
  **outputs** por escenario, nunca los inputs macro (guard anti escenario medio, ESPEC §5.6). Los
  pesos los aporta ``forward``/config; el motor **no** los inventa ni normaliza: exige ``Σ w_k = 1``
  (con un solo escenario, ``w = 1``) y que cubran exactamente los escenarios presentes, o levanta
  :class:`IfrsEclError`.
- **Stage 3 directo (opcional).** Con ``stage3_direct=True``, la ECL lifetime de las filas Stage 3
  se calcula como ``EAD · LGD · DF(0)`` (``DF(0)=1``) sobre el período más temprano de cada
  escenario, ponderado por ``w_k`` (D-IFRS-14).
- **Invariante de consistencia.** ``ecl_reported`` es ``ecl_12m`` en Stage 1 y ``ecl_lifetime`` en
  Stage 2/3 por construcción (SDD-16 §6). Sin ``NaN``/``inf`` en ninguna salida (validación en la
  entrada; nunca clip silencioso) y ``-0.0`` se normaliza a ``0.0`` (reproducibilidad).

Devuelve dos ``DataFrame`` tidy: la ``ecl_term_structure`` larga por ``row_id`` x ``scenario`` x
``period`` (columnas canónicas SDD-16 §6, evidencia auditable de la suma) y el ``detail`` por
operación con ``ecl_12m``/``ecl_lifetime``/``ecl_reported``. El ensamblado del
``IfrsProvisionResult`` completo (staging/summary/card) es responsabilidad de ``engine.py`` (B16.8);
este bloque es solo el motor ECL. El motor no muta los insumos (solo lee columnas y arma salidas).

``pandas``/``numpy`` se importan de forma perezosa dentro de los métodos: ni ``import nikodym.core``
ni ``import nikodym.provisioning.ifrs9`` deben arrastrar esas dependencias en top-level.

Nomenclatura IFRS 9 (regla dura D-CONV-1): ``pd``/``lgd``/``ead``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
from typing import TYPE_CHECKING, Any, Self, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9.exceptions import IfrsEclError

if TYPE_CHECKING:
    from collections.abc import Mapping

    import numpy as np
    import pandas as pd

    from nikodym.provisioning.ifrs9.config import IfrsEclConfig

    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    NDArrayInt: TypeAlias = np.ndarray[Any, np.dtype[np.int64]]
    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series
else:
    NDArrayFloat: TypeAlias = Any
    NDArrayInt: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["EclEngine"]

# Columnas mínimas de la malla tidy de componentes alineados por (row_id, scenario, period).
_COMPONENT_COLUMNS: tuple[str, ...] = (
    "row_id",
    "scenario",
    "period",
    "time_value",
    "pd_marginal",
    "lgd",
    "ead",
)
# Columnas canónicas de la salida ``ecl_term_structure`` (orden fijo SDD-16 §6, homólogo a results).
_TERM_STRUCTURE_COLUMNS: tuple[str, ...] = (
    "row_id",
    "scenario",
    "period",
    "time_value",
    "pd_marginal",
    "lgd",
    "ead",
    "discount_factor",
    "ecl_marginal",
)
# Columnas del ``detail`` por operación que publica el motor ECL (subconjunto de detail SDD-16 §6).
_DETAIL_COLUMNS: tuple[str, ...] = (
    "row_id",
    "stage",
    "ecl_12m",
    "ecl_lifetime",
    "ecl_reported",
)
# Tolerancia absoluta para exigir que los pesos de escenario sumen 1 (SDD-16 §5/§6).
_WEIGHT_SUM_TOL: float = 1e-9

_NUMPY_MESSAGE: str = "EclEngine requiere numpy; instale nikodym[scoring]."
_PANDAS_MESSAGE: str = "EclEngine requiere pandas; instale nikodym[scoring]."


class EclEngine:
    """Motor ECL marginal IFRS 9 con descuento a EIR y ponderación de escenarios (SDD-16 §3)."""

    def __init__(self, config: IfrsEclConfig) -> None:
        """Inicializa el motor con su sub-config ``IfrsEclConfig`` ya validado."""
        self._config = config

    @classmethod
    def from_config(cls, cfg: IfrsEclConfig) -> Self:
        """Construye el motor ECL desde ``IfrsEclConfig`` (molde hermano ``from_config``)."""
        return cls(cfg)

    def compute(
        self,
        components: DataFrame,
        *,
        eir: Series,
        stages: Series,
        weights: Mapping[str, float],
        horizon_12m: int,
        max_lifetime: int | None = None,
    ) -> tuple[DataFrame, DataFrame]:
        """Calcula la ECL marginal por período y la agrega por operación ponderando escenarios.

        Parameters
        ----------
        components
            DataFrame tidy con una fila por ``(row_id, scenario, period)`` y las columnas
            ``row_id``/``scenario``/``period``/``time_value``/``pd_marginal``/``lgd``/``ead`` ya
            alineadas por los motores aguas arriba (PD PIT/lifetime, LGD, EAD). No se muta.
        eir
            Tasa efectiva por instrumento, ``Series`` indexada por ``row_id`` (``> -1`` por fila).
        stages
            Stage IFRS 9 (``1``/``2``/``3``) por operación, ``Series`` indexada por ``row_id``.
        weights
            Pesos de escenario ``w_k``; deben cubrir exactamente los escenarios presentes, ser
            positivos y sumar 1 (con un solo escenario, ``w = 1``).
        horizon_12m
            Períodos que cubren 12 meses (``H_12m``, entero ``>= 1``) para el truncado de Stage 1.
        max_lifetime
            Tope del horizonte lifetime (``T_max``, entero ``>= 1``); ``None`` usa todo el soporte.

        Returns
        -------
        tuple[pandas.DataFrame, pandas.DataFrame]
            ``(ecl_term_structure, detail)``: la term-structure de ECL larga por ``row_id`` x
            ``scenario`` x ``period`` (evidencia auditable) y el detalle por operación con
            ``ecl_12m``/``ecl_lifetime``/``ecl_reported`` (``ecl_reported`` es ``ecl_12m`` en Stage
            1 y ``ecl_lifetime`` en Stage 2/3).

        Raises
        ------
        IfrsEclError
            Si los horizontes son inválidos, la malla de componentes rompe su contrato (columna
            faltante, insumo no finito/fuera de rango), los pesos no cubren los escenarios o no
            suman 1, falta la EIR/stage de una operación, o el descuento cae fuera de ``(0, 1]``.
        MissingDependencyError
            Si falta ``numpy`` o ``pandas``.
        """
        numpy = _import_numpy()
        pandas = _import_pandas()
        _validate_horizons(horizon_12m, max_lifetime)
        cols = _read_components(components, numpy, max_lifetime)
        scenario_keys = [str(scenario) for scenario in cols["scenario"]]
        weight_by_scenario = _resolve_weights(weights, set(scenario_keys))
        eir_map = _resolve_eir(eir, numpy)
        stage_map = _resolve_stages(stages, numpy)
        row_id_keys = [str(row_id) for row_id in cols["row_id"]]
        missing_eir = sorted({row_id for row_id in row_id_keys if row_id not in eir_map})
        if missing_eir:
            raise IfrsEclError(f"Faltan EIR para las operaciones: {missing_eir}.")
        eir_arr = numpy.array([eir_map[row_id] for row_id in row_id_keys], dtype=numpy.float64)
        weight_arr = numpy.array(
            [weight_by_scenario[scenario] for scenario in scenario_keys], dtype=numpy.float64
        )
        discount = self._discount_factor(eir_arr, cols["period"], cols["time_value"], numpy)
        ecl_marginal = cols["pd_marginal"] * cols["lgd"] * cols["ead"] * discount
        ecl_marginal = numpy.where(ecl_marginal == 0.0, 0.0, ecl_marginal)
        term_structure = self._term_structure(cols, discount, ecl_marginal, pandas, numpy)
        detail = self._detail(cols, weight_arr, ecl_marginal, horizon_12m, stage_map, pandas, numpy)
        return term_structure, detail

    def _discount_factor(
        self,
        eir_arr: NDArrayFloat,
        period_arr: NDArrayInt,
        time_value_arr: NDArrayFloat,
        numpy: Any,
    ) -> NDArrayFloat:
        """Calcula ``DF(t) = (1 + EIR)^(-tau(t))`` según la convención y lo valida en ``(0, 1]``."""
        base = 1.0 + eir_arr  # ``_resolve_eir`` garantiza EIR > -1, luego base > 0.
        if self._config.discount_convention == "period_eir":
            exponent = period_arr.astype(numpy.float64)
        else:
            exponent = time_value_arr
        # Base positiva evita ``nan``; se ignoran overflow/underflow para no romper
        # filterwarnings=error y se validan finitud/rango en vez de clipar en silencio.
        with numpy.errstate(over="ignore", under="ignore", divide="ignore"):
            discount = numpy.power(base, -exponent)
        if not bool(numpy.all(numpy.isfinite(discount))):
            raise IfrsEclError(
                "El factor de descuento no es finito; revise EIR/horizonte (no se clipa)."
            )
        if bool(numpy.any(discount <= 0.0)) or bool(numpy.any(discount > 1.0)):
            raise IfrsEclError(
                "El factor de descuento debe estar en (0, 1]; revise EIR (no se clipa)."
            )
        return cast("NDArrayFloat", discount)

    def _term_structure(
        self,
        cols: dict[str, Any],
        discount: NDArrayFloat,
        ecl_marginal: NDArrayFloat,
        pandas: Any,
        numpy: Any,
    ) -> DataFrame:
        """Arma la ``ecl_term_structure`` larga por ``row_id`` x ``scenario`` x ``period``."""
        data = {
            "row_id": cols["row_id"],
            "scenario": cols["scenario"],
            "period": cols["period"],
            "time_value": numpy.where(cols["time_value"] == 0.0, 0.0, cols["time_value"]),
            "pd_marginal": numpy.where(cols["pd_marginal"] == 0.0, 0.0, cols["pd_marginal"]),
            "lgd": numpy.where(cols["lgd"] == 0.0, 0.0, cols["lgd"]),
            "ead": numpy.where(cols["ead"] == 0.0, 0.0, cols["ead"]),
            "discount_factor": discount,
            "ecl_marginal": ecl_marginal,
        }
        return cast("DataFrame", pandas.DataFrame(data, columns=list(_TERM_STRUCTURE_COLUMNS)))

    def _detail(
        self,
        cols: dict[str, Any],
        weight_arr: NDArrayFloat,
        ecl_marginal: NDArrayFloat,
        horizon_12m: int,
        stage_map: dict[str, int],
        pandas: Any,
        numpy: Any,
    ) -> DataFrame:
        """Agrega la ECL por operación (12m/lifetime/reportado) ponderando outputs por escenario."""
        weighted = ecl_marginal * weight_arr
        within_12m = cols["period"] <= horizon_12m
        aggregation = pandas.DataFrame(
            {
                "row_id": cols["row_id"],
                "_ecl_12m": numpy.where(within_12m, weighted, 0.0),
                "_ecl_lifetime": weighted,
            }
        )
        grouped = (
            aggregation.groupby("row_id", sort=False, dropna=False)
            .agg(ecl_12m=("_ecl_12m", "sum"), ecl_lifetime=("_ecl_lifetime", "sum"))
            .reset_index()
        )
        unique_row_ids = grouped["row_id"].to_numpy()
        ecl_12m = numpy.asarray(grouped["ecl_12m"].to_numpy(), dtype=numpy.float64)
        ecl_lifetime = numpy.asarray(grouped["ecl_lifetime"].to_numpy(), dtype=numpy.float64)
        row_keys = [str(row_id) for row_id in unique_row_ids]
        missing_stage = sorted({row_id for row_id in row_keys if row_id not in stage_map})
        if missing_stage:
            raise IfrsEclError(f"Faltan stages para las operaciones: {missing_stage}.")
        stage_arr = numpy.array([stage_map[row_id] for row_id in row_keys], dtype=numpy.int64)
        if self._config.stage3_direct:
            direct = _direct_lifetime(cols, weight_arr, pandas, numpy)
            direct_arr = numpy.array([direct[row_id] for row_id in row_keys], dtype=numpy.float64)
            ecl_lifetime = numpy.where(stage_arr == 3, direct_arr, ecl_lifetime)
        reported = numpy.where(stage_arr == 1, ecl_12m, ecl_lifetime)
        detail = {
            "row_id": unique_row_ids,
            "stage": stage_arr,
            "ecl_12m": numpy.where(ecl_12m == 0.0, 0.0, ecl_12m),
            "ecl_lifetime": numpy.where(ecl_lifetime == 0.0, 0.0, ecl_lifetime),
            "ecl_reported": numpy.where(reported == 0.0, 0.0, reported),
        }
        return cast("DataFrame", pandas.DataFrame(detail, columns=list(_DETAIL_COLUMNS)))


def _validate_horizons(horizon_12m: int, max_lifetime: int | None) -> None:
    """Valida que ``horizon_12m`` y ``max_lifetime`` sean horizontes enteros ``>= 1``."""
    if horizon_12m < 1:
        raise IfrsEclError(f"horizon_12m debe ser un entero >= 1; valor: {horizon_12m!r}.")
    if max_lifetime is not None and max_lifetime < 1:
        raise IfrsEclError(f"max_lifetime debe ser None o un entero >= 1; valor: {max_lifetime!r}.")


def _read_components(frame: DataFrame, numpy: Any, max_lifetime: int | None) -> dict[str, Any]:
    """Extrae y valida la malla de componentes, truncando por ``max_lifetime`` si se informa."""
    faltantes = [col for col in _COMPONENT_COLUMNS if col not in frame.columns]
    if faltantes:
        raise IfrsEclError(
            f"components debe contener {_COMPONENT_COLUMNS}; columnas faltantes: {faltantes}."
        )
    period = _period_array(frame["period"].to_numpy(), numpy)
    time_value = _to_float_array(frame["time_value"].to_numpy(), "time_value", numpy)
    if bool(numpy.any(time_value < 0.0)):
        raise IfrsEclError("time_value debe ser mayor o igual a 0.")
    pd_marginal = _to_float_array(frame["pd_marginal"].to_numpy(), "pd_marginal", numpy)
    if bool(numpy.any((pd_marginal < 0.0) | (pd_marginal > 1.0))):
        raise IfrsEclError("pd_marginal debe estar en [0, 1].")
    lgd = _to_float_array(frame["lgd"].to_numpy(), "lgd", numpy)
    if bool(numpy.any((lgd < 0.0) | (lgd > 1.0))):
        raise IfrsEclError("lgd debe estar en [0, 1].")
    ead = _to_float_array(frame["ead"].to_numpy(), "ead", numpy)
    if bool(numpy.any(ead < 0.0)):
        raise IfrsEclError("ead debe ser mayor o igual a 0.")
    cols: dict[str, Any] = {
        "row_id": frame["row_id"].to_numpy(),
        "scenario": frame["scenario"].to_numpy(),
        "period": period,
        "time_value": time_value,
        "pd_marginal": pd_marginal,
        "lgd": lgd,
        "ead": ead,
    }
    if period.shape[0] == 0:
        raise IfrsEclError("components no puede estar vacío.")
    if max_lifetime is not None:
        mask = period <= max_lifetime
        if not bool(numpy.any(mask)):
            raise IfrsEclError(
                f"No quedan períodos con period <= max_lifetime={max_lifetime} en components."
            )
        cols = {key: value[mask] for key, value in cols.items()}
    return cols


def _direct_lifetime(
    cols: dict[str, Any], weight_arr: NDArrayFloat, pandas: Any, numpy: Any
) -> dict[str, float]:
    """Calcula la ECL Stage 3 directa ``Σ_k w_k · EAD_k0 · LGD_k0`` (DF(0)=1) por operación."""
    frame = pandas.DataFrame(
        {
            "row_id": cols["row_id"],
            "scenario": cols["scenario"],
            "period": cols["period"],
            "ead": cols["ead"],
            "lgd": cols["lgd"],
            "_weight": weight_arr,
        }
    )
    ordered = frame.sort_values("period", kind="mergesort")
    first = ordered.groupby(["row_id", "scenario"], sort=False, dropna=False).first().reset_index()
    contribution = first["ead"].to_numpy() * first["lgd"].to_numpy() * first["_weight"].to_numpy()
    per_row = pandas.DataFrame({"row_id": first["row_id"].to_numpy(), "_direct": contribution})
    summed = per_row.groupby("row_id", sort=False, dropna=False)["_direct"].sum()
    return {str(row_id): float(value) for row_id, value in summed.items()}


def _resolve_weights(weights: Mapping[str, float], scenarios_present: set[str]) -> dict[str, float]:
    """Valida los pesos (positivos, que cubren los escenarios y suman 1); no los inventa."""
    if not weights:
        raise IfrsEclError("Los pesos de escenario no pueden estar vacíos (no se inventan).")
    resolved: dict[str, float] = {}
    for key, value in weights.items():
        name = str(key)
        if not math.isfinite(value):
            raise IfrsEclError(f"El peso del escenario '{name}' debe ser finito.")
        if value <= 0.0:
            raise IfrsEclError(f"El peso del escenario '{name}' debe ser estrictamente positivo.")
        resolved[name] = float(value)
    if set(resolved) != scenarios_present:
        raise IfrsEclError(
            "Los pesos de escenario deben cubrir exactamente los escenarios presentes "
            f"(pesos={sorted(resolved)}, escenarios={sorted(scenarios_present)})."
        )
    total = math.fsum(resolved.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=_WEIGHT_SUM_TOL):
        raise IfrsEclError(f"Los pesos de escenario deben sumar 1; suma observada={total!r}.")
    return resolved


def _resolve_eir(series: Series, numpy: Any) -> dict[str, float]:
    """Convierte la serie de EIR en un mapa ``row_id -> EIR`` finito y ``> -1``, sin duplicados."""
    values = _to_float_array(series.to_numpy(), "eir", numpy)
    keys = [str(index) for index in series.index]
    result: dict[str, float] = {}
    for key, value in zip(keys, values, strict=True):
        if key in result:
            raise IfrsEclError(f"El índice de 'eir' debe ser único por row_id; repetido: {key!r}.")
        if value <= -1.0:
            raise IfrsEclError(
                f"La EIR de la operación '{key}' debe ser mayor que -1 (descuento positivo)."
            )
        result[key] = float(value)
    return result


def _resolve_stages(series: Series, numpy: Any) -> dict[str, int]:
    """Convierte la serie de stages en un mapa ``row_id -> stage`` en ``{1, 2, 3}`` sin duplicar."""
    values = _to_float_array(series.to_numpy(), "stages", numpy)
    keys = [str(index) for index in series.index]
    result: dict[str, int] = {}
    for key, value in zip(keys, values, strict=True):
        if key in result:
            raise IfrsEclError(
                f"El índice de 'stages' debe ser único por row_id; repetido: {key!r}."
            )
        if value not in (1.0, 2.0, 3.0):
            raise IfrsEclError(f"El stage de '{key}' debe ser 1, 2 o 3; valor: {value!r}.")
        result[key] = int(value)
    return result


def _period_array(values: Any, numpy: Any) -> NDArrayInt:
    """Extrae ``period`` como enteros ``>= 1``, mapeando fallos a ``IfrsEclError``."""
    array = _to_float_array(values, "period", numpy)
    if bool(numpy.any(array < 1.0)) or bool(numpy.any(array != numpy.floor(array))):
        raise IfrsEclError("period debe ser un entero mayor o igual a 1.")
    return cast("NDArrayInt", array.astype(numpy.int64))


def _to_float_array(values: Any, name: str, numpy: Any) -> NDArrayFloat:
    """Castea a float64 y exige valores finitos, mapeando fallos a ``IfrsEclError``."""
    try:
        array = numpy.asarray(values, dtype=numpy.float64)
    except (ValueError, TypeError) as exc:
        raise IfrsEclError(f"El campo '{name}' debe ser numérico.") from exc
    if not bool(numpy.all(numpy.isfinite(array))):
        raise IfrsEclError(f"El campo '{name}' debe contener sólo valores finitos.")
    return cast("NDArrayFloat", array)


def _import_numpy() -> Any:
    """Importa ``numpy`` bajo demanda para preservar el import liviano del núcleo."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_NUMPY_MESSAGE) from exc


def _import_pandas() -> Any:
    """Importa ``pandas`` bajo demanda para preservar el import liviano del núcleo."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_PANDAS_MESSAGE) from exc
