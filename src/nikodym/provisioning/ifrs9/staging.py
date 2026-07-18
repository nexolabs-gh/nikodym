"""Asignación del staging IFRS 9 (SICR / Stage 1/2/3) por operación (SDD-16 §3/§7).

:class:`StagingEngine` evalúa los siete gatillos de aumento significativo del riesgo de crédito
(SICR) del SDD-16 §3 sobre el ``frame`` económico y las PD actuales (``pd_life``/``pd_pit``), y
asigna a cada operación el **Stage más severo disparado** (``3 > 2 > 1``). Gatillos (§3):

1. **Ratio PD lifetime** actual/origen ``>= sicr_pd_ratio_threshold`` → Stage 2. El ratio
   se pide sólo cuando ``origination_pd_life_col`` está configurada; su ausencia en el frame cuando
   se pide el ratio levanta :class:`IfrsStagingError` (contrato duro: NO se degrada).
2. **Backstop PIT** actual/origen ``>= sicr_pd_pit_backstop_multiple`` → Stage 2. La PD PIT
   en origen se lee de la columna convencional de nombre fijo ``pd_pit_origination`` (no
   parametrizada en ``IfrsStagingConfig`` en B16.6; el panel longitudinal se difiere por CT-3); el
   gatillo se evalúa cuando esa columna está presente.
3. **Downgrade por notches** (``rating_actual - rating_origen >= notch_downgrade_threshold``) →
   Stage 2 (blando). Las columnas de rating son grados numéricos crecientes en riesgo (mayor grado
   ⇒ peor calidad).
4. **Override cualitativo** (``stage_override_col``) → fuerza Stage 2 o 3 según el valor de la
   columna (``1`` = sin override, ``2``/``3`` = Stage forzado).
5. **Presunción 30 dpd** ``days_past_due >= dpd_sicr_backstop`` → Stage 2.
6. **Default 90 dpd / is_default** ``days_past_due >= dpd_default_backstop`` o flag ``is_default`` →
   Stage 3.
7. **Exención de bajo riesgo** (opt-in ``low_credit_risk_exemption`` + ``low_credit_risk_col``):
   puede rescatar a Stage 1 los gatillos 1-4. Las referencias 30/90 dpd de IFRS 9 son presunciones
   rebatibles. Por política conservadora explícita del motor v1, los gatillos DPD y el default
   tienen prioridad sobre la exención; esta precedencia es una política de Nikodym, no
   irrebatibilidad normativa.

La salida es un ``DataFrame`` tidy por operación con ``stage`` (``1``/``2``/``3``),
``sicr_triggers`` (gatillos disparados por fila, en orden canónico auditable) y
``low_credit_risk_exempt`` (la exención estaba activa para la fila), preservando el índice del
``frame``. El motor no muta el
``frame`` (solo lee columnas y arma una salida nueva) y no clipa ni degrada en silencio: las brechas
de dato o los valores fuera de contrato levantan :class:`IfrsStagingError` (gatillos/columnas) o
:class:`~nikodym.provisioning.ifrs9.exceptions.IfrsInputError` (días de mora negativos/no enteros).

``pandas``/``numpy`` se importan de forma perezosa dentro de los métodos: ni ``import nikodym.core``
ni ``import nikodym.provisioning.ifrs9`` deben arrastrar esas dependencias en top-level.

Nomenclatura IFRS 9 (regla dura D-CONV-1): ``pd``/``lgd``/``ead``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Self, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9.exceptions import IfrsInputError, IfrsStagingError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.provisioning.ifrs9.config import IfrsStagingConfig

    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    NDArrayInt: TypeAlias = np.ndarray[Any, np.dtype[np.int64]]
    NDArrayBool: TypeAlias = np.ndarray[Any, np.dtype[np.bool_]]
    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series
else:
    NDArrayFloat: TypeAlias = Any
    NDArrayInt: TypeAlias = Any
    NDArrayBool: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["StagingEngine"]

# Columna convencional de nombre fijo con la PD PIT en origen del backstop PIT (gatillo 2). No está
# parametrizada en IfrsStagingConfig en B16.6 (el panel longitudinal se difiere por CT-3); el motor
# la lee del frame por nombre fijo y evalúa el gatillo sólo cuando está presente.
_ORIGINATION_PD_PIT_COLUMN: str = "pd_pit_origination"

# Nombres canónicos y auditables de los gatillos SICR publicados en ``sicr_triggers`` (§3).
_TRIGGER_PD_RATIO: str = "sicr_pd_ratio"
_TRIGGER_PIT_BACKSTOP: str = "sicr_pd_pit_backstop"
_TRIGGER_NOTCH: str = "notch_downgrade"
_TRIGGER_OVERRIDE: str = "stage_override"
_TRIGGER_DPD_SICR: str = "dpd_sicr_backstop"
_TRIGGER_DPD_DEFAULT: str = "dpd_default_backstop"
_TRIGGER_IS_DEFAULT: str = "is_default"

_NUMPY_MESSAGE: str = "StagingEngine requiere numpy; instale nikodym[scoring]."
_PANDAS_MESSAGE: str = "StagingEngine requiere pandas; instale nikodym[scoring]."


class StagingEngine:
    """Motor de asignación del staging IFRS 9 (SICR / backstops / exención) (SDD-16 §3)."""

    def __init__(self, config: IfrsStagingConfig) -> None:
        """Inicializa el motor con su sub-config ``IfrsStagingConfig`` ya validado."""
        self._config = config

    @classmethod
    def from_config(cls, cfg: IfrsStagingConfig) -> Self:
        """Construye el motor de staging desde ``IfrsStagingConfig`` (molde hermano)."""
        return cls(cfg)

    def assign(self, frame: DataFrame, *, pd_life: Series, pd_pit: Series) -> DataFrame:
        """Asigna el Stage 1/2/3 por operación evaluando los gatillos SICR de SDD-16 §3.

        Parameters
        ----------
        frame
            DataFrame económico con las columnas que exigen los gatillos activos (días de mora,
            PD lifetime/PIT en origen, rating, override, flags de default/bajo riesgo). No se muta.
        pd_life
            Serie con la PD lifetime **actual** por operación, alineada por posición al ``frame``.
        pd_pit
            Serie con la PD PIT **actual** por operación, alineada por posición al ``frame``.

        Returns
        -------
        pandas.DataFrame
            Tabla tidy por operación con ``stage`` (``1``/``2``/``3``), ``sicr_triggers`` (tupla de
            gatillos disparados por fila) y ``low_credit_risk_exempt`` (bool); el índice del
            ``frame`` se preserva.

        Raises
        ------
        IfrsStagingError
            Si falta una columna requerida por un gatillo activo, la PD en origen no es
            estrictamente positiva, el override o un flag no respetan su contrato, o la exención se
            pide sin ``low_credit_risk_col``.
        IfrsInputError
            Si los días de mora son negativos, no finitos o no enteros.
        MissingDependencyError
            Si falta ``numpy`` o ``pandas``.
        """
        numpy = _import_numpy()
        pandas = _import_pandas()
        n = frame.shape[0]
        pd_life_arr = _series_to_array(pd_life, frame, numpy, name="pd_life")
        pd_pit_arr = _series_to_array(pd_pit, frame, numpy, name="pd_pit")
        dpd = _dpd_column(frame, self._config.days_past_due_col, numpy)
        exemptible_entries = [
            (_TRIGGER_PD_RATIO, numpy.where(self._fired_pd_ratio(frame, pd_life_arr, numpy), 2, 1)),
            (
                _TRIGGER_PIT_BACKSTOP,
                numpy.where(self._fired_pit_backstop(frame, pd_pit_arr, numpy), 2, 1),
            ),
            (_TRIGGER_NOTCH, numpy.where(self._fired_notch(frame, numpy), 2, 1)),
            (_TRIGGER_OVERRIDE, self._override_stage(frame, n, numpy)),
        ]
        priority_entries = [
            (_TRIGGER_DPD_SICR, numpy.where(dpd >= self._config.dpd_sicr_backstop, 2, 1)),
            (_TRIGGER_DPD_DEFAULT, numpy.where(dpd >= self._config.dpd_default_backstop, 3, 1)),
            (_TRIGGER_IS_DEFAULT, numpy.where(self._fired_is_default(frame, n, numpy), 3, 1)),
        ]
        exempt = self._exempt_rows(frame, n, numpy)
        return self._assemble(frame, exemptible_entries, priority_entries, exempt, pandas)

    def _fired_pd_ratio(
        self, frame: DataFrame, pd_life_arr: NDArrayFloat, numpy: Any
    ) -> NDArrayBool:
        """Gatillo 1: ``PD_life_actual / PD_life_origen >= sicr_pd_ratio_threshold`` (§3)."""
        col = self._config.origination_pd_life_col
        if col is None:
            return cast("NDArrayBool", numpy.zeros(pd_life_arr.shape[0], dtype=bool))
        origen = _column(frame, col, numpy)
        if not bool(numpy.all(origen > 0.0)):
            raise IfrsStagingError(
                "El gatillo de ratio SICR exige PD lifetime en origen estrictamente positiva."
            )
        return cast("NDArrayBool", pd_life_arr / origen >= self._config.sicr_pd_ratio_threshold)

    def _fired_pit_backstop(
        self, frame: DataFrame, pd_pit_arr: NDArrayFloat, numpy: Any
    ) -> NDArrayBool:
        """Gatillo 2: ``PD_PIT_actual / PD_PIT_origen >= sicr_pd_pit_backstop_multiple`` (§3)."""
        if _ORIGINATION_PD_PIT_COLUMN not in frame.columns:
            return cast("NDArrayBool", numpy.zeros(pd_pit_arr.shape[0], dtype=bool))
        origen = _column(frame, _ORIGINATION_PD_PIT_COLUMN, numpy)
        if not bool(numpy.all(origen > 0.0)):
            raise IfrsStagingError("El backstop PIT exige PD PIT en origen estrictamente positiva.")
        return cast(
            "NDArrayBool", pd_pit_arr / origen >= self._config.sicr_pd_pit_backstop_multiple
        )

    def _fired_notch(self, frame: DataFrame, numpy: Any) -> NDArrayBool:
        """Gatillo 3: ``rating_actual - rating_origen >= notch_downgrade_threshold`` (§3)."""
        threshold = self._config.notch_downgrade_threshold
        if threshold is None:
            return cast("NDArrayBool", numpy.zeros(frame.shape[0], dtype=bool))
        # IfrsStagingConfig garantiza rating_col/origination_rating_col no-None con el threshold.
        rating = _column(frame, cast("str", self._config.rating_col), numpy)
        origen = _column(frame, cast("str", self._config.origination_rating_col), numpy)
        return cast("NDArrayBool", rating - origen >= threshold)

    def _override_stage(self, frame: DataFrame, n: int, numpy: Any) -> NDArrayInt:
        """Gatillo 4: Stage forzado por el override cualitativo (``1`` = sin override) (§3)."""
        col = self._config.stage_override_col
        if col is None:
            return cast("NDArrayInt", numpy.ones(n, dtype=numpy.int64))
        return _stage_override_array(frame, col, numpy)

    def _fired_is_default(self, frame: DataFrame, n: int, numpy: Any) -> NDArrayBool:
        """Gatillo 6: flag de default opcional (SDD-16 §6); se usa si la columna existe."""
        col = self._config.is_default_col
        if col is None or col not in frame.columns:
            return cast("NDArrayBool", numpy.zeros(n, dtype=bool))
        return _bool_column(frame, col, numpy)

    def _exempt_rows(self, frame: DataFrame, n: int, numpy: Any) -> NDArrayBool:
        """Gatillo 7: filas con la exención de bajo riesgo activa (opt-in) (§3)."""
        if not self._config.low_credit_risk_exemption:
            return cast("NDArrayBool", numpy.zeros(n, dtype=bool))
        col = self._config.low_credit_risk_col
        if col is None:
            raise IfrsStagingError(
                "La exención de bajo riesgo (low_credit_risk_exemption) exige low_credit_risk_col."
            )
        return _bool_column(frame, col, numpy)

    def _assemble(
        self,
        frame: DataFrame,
        exemptible_entries: list[tuple[str, Any]],
        priority_entries: list[tuple[str, Any]],
        exempt: NDArrayBool,
        pandas: Any,
    ) -> DataFrame:
        """Combina gatillos; la política v1 da prioridad a DPD/default sobre la exención."""
        stages: list[int] = []
        triggers: list[tuple[str, ...]] = []
        exempt_flags: list[bool] = []
        for i in range(frame.shape[0]):
            fired: list[str] = []
            exemptible = 1
            for name, stage_arr in exemptible_entries:
                value = int(stage_arr[i])
                if value > 1:
                    fired.append(name)
                    exemptible = max(exemptible, value)
            priority = 1
            for name, stage_arr in priority_entries:
                value = int(stage_arr[i])
                if value > 1:
                    fired.append(name)
                    priority = max(priority, value)
            exempt_i = bool(exempt[i])
            # Política conservadora v1: DPD/default prevalecen; IFRS 9 los trata como presunciones
            # rebatibles, no como reglas irrebatibles. La configurabilidad se difiere por SDD.
            stage = priority if exempt_i else max(exemptible, priority)
            stages.append(stage)
            triggers.append(tuple(fired))
            exempt_flags.append(exempt_i)
        return cast(
            "DataFrame",
            pandas.DataFrame(
                {
                    "stage": stages,
                    "sicr_triggers": triggers,
                    "low_credit_risk_exempt": exempt_flags,
                },
                index=frame.index,
            ),
        )


def _column(frame: DataFrame, name: str, numpy: Any) -> NDArrayFloat:
    """Extrae una columna como arreglo float64 finito, o levanta ``IfrsStagingError``."""
    if name not in frame.columns:
        raise IfrsStagingError(
            f"La columna '{name}' requerida por un gatillo de staging no está en el frame."
        )
    return _to_float_array(frame[name].to_numpy(), name, numpy)


def _series_to_array(series: Series, frame: DataFrame, numpy: Any, *, name: str) -> NDArrayFloat:
    """Convierte una serie a float64 finito y valida que alinee su longitud con el ``frame``."""
    array = _to_float_array(series.to_numpy(), name, numpy)
    if array.shape[0] != frame.shape[0]:
        raise IfrsStagingError(
            f"La serie '{name}' debe alinear su longitud con el frame ({frame.shape[0]} filas)."
        )
    return array


def _to_float_array(values: Any, name: str, numpy: Any) -> NDArrayFloat:
    """Castea a float64 y exige valores finitos, mapeando fallos a ``IfrsStagingError``."""
    try:
        array = numpy.asarray(values, dtype=numpy.float64)
    except (ValueError, TypeError) as exc:
        raise IfrsStagingError(f"El campo '{name}' debe ser numérico.") from exc
    if not bool(numpy.all(numpy.isfinite(array))):
        raise IfrsStagingError(f"El campo '{name}' debe contener sólo valores finitos.")
    return cast("NDArrayFloat", array)


def _bool_column(frame: DataFrame, name: str, numpy: Any) -> NDArrayBool:
    """Extrae una columna booleana (bool o ``0``/``1``), o levanta ``IfrsStagingError``."""
    if name not in frame.columns:
        raise IfrsStagingError(
            f"La columna booleana '{name}' requerida por un gatillo de staging no está en el frame."
        )
    values = frame[name].to_numpy()
    if values.dtype == bool:
        return cast("NDArrayBool", values)
    array = _to_float_array(values, name, numpy)
    if not bool(numpy.all((array == 0.0) | (array == 1.0))):
        raise IfrsStagingError(f"La columna booleana '{name}' debe contener sólo 0/1 o booleanos.")
    return cast("NDArrayBool", array != 0.0)


def _dpd_column(frame: DataFrame, name: str, numpy: Any) -> NDArrayInt:
    """Extrae los días de mora como enteros ``>= 0``; los fallos son ``IfrsInputError`` (§8)."""
    if name not in frame.columns:
        raise IfrsStagingError(f"La columna de días de mora '{name}' no está en el frame.")
    try:
        array = numpy.asarray(frame[name].to_numpy(), dtype=numpy.float64)
    except (ValueError, TypeError) as exc:
        raise IfrsInputError(f"La columna '{name}' (días de mora) debe ser numérica.") from exc
    if not bool(numpy.all(numpy.isfinite(array))):
        raise IfrsInputError(f"La columna '{name}' (días de mora) debe ser finita.")
    if not bool(numpy.all(array >= 0.0)):
        raise IfrsInputError(f"La columna '{name}' (días de mora) no puede ser negativa.")
    if not bool(numpy.all(array == numpy.floor(array))):
        raise IfrsInputError(f"La columna '{name}' (días de mora) debe ser entera.")
    return cast("NDArrayInt", array.astype(numpy.int64))


def _stage_override_array(frame: DataFrame, name: str, numpy: Any) -> NDArrayInt:
    """Valida el override cualitativo como entero en ``{1, 2, 3}`` (``1`` = sin override)."""
    if name not in frame.columns:
        raise IfrsStagingError(
            f"La columna de override '{name}' requerida por el staging no está en el frame."
        )
    array = _to_float_array(frame[name].to_numpy(), name, numpy)
    if not bool(numpy.all(array == numpy.floor(array))):
        raise IfrsStagingError(f"El override de stage '{name}' debe ser entero en {{1, 2, 3}}.")
    if not bool(numpy.all((array == 1.0) | (array == 2.0) | (array == 3.0))):
        raise IfrsStagingError(
            f"El override de stage '{name}' debe estar en {{1, 2, 3}} (1 = sin override)."
        )
    return cast("NDArrayInt", array.astype(numpy.int64))


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
