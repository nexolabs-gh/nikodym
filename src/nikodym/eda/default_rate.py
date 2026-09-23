"""Tasa de default descriptiva para la capa ``eda`` (SDD-27 §4/§6/§7).

``DefaultRateAnalyzer`` agrega una tabla por período o cohorte sin ajustar parámetros ni mutar el
``DataFrame`` de entrada. La población elegible se define estrictamente por ``target`` en
``{0, 1}``; los ``<NA>`` y cualquier valor fuera de contrato quedan fuera del denominador, pero
siguen contando en ``n_total``.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

from typing import Final, Literal, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator

from nikodym.core.audit import AuditSink
from nikodym.eda.config import DefaultRateConfig
from nikodym.eda.exceptions import EdaError

__all__ = [
    "AXIS_LABELS",
    "DEFAULT_RATE_NOT_EVALUABLE_REASON_LABELS",
    "MAX_PUBLISHED_PERIODS",
    "DefaultRateAnalyzer",
    "DefaultRateNotEvaluableReason",
    "DefaultRateResult",
    "EdaAxis",
    "tasa_no_calculable",
    "tasa_no_evaluable",
]

#: Los dos ejes con que se agrupa la tasa de incumplimiento; es la anotación de ``axis`` en el
#: config y en el resultado, para que ninguno de los dos pueda ganar un valor sin el otro.
EdaAxis = Literal["period", "cohort"]

#: Por qué la tasa NO se pudo agrupar (D-SC-17). Mismo molde que
#: :data:`nikodym.eda.stability.NotEvaluableReason`: hay causa **si y sólo si** ``by_period`` está
#: vacía. Hoy tiene una sola causa porque hay un solo caso en que el motor no puede agrupar sin
#: contradecir algo que el usuario declaró (§2 de la enmienda); el tipo es un ``Literal`` para que
#: una causa nueva mueva su rótulo, su espejo en el front y sus gates a la vez.
DefaultRateNotEvaluableReason = Literal["sin_eje_temporal", "no_calculable"]

#: Las palabras públicas de cada causa de la tasa: una sola fuente para el resumen de la etapa, el
#: panel de Resultados y la prosa del informe, con espejo gateado en el front (mismo molde que
#: ``NOT_EVALUABLE_REASON_LABELS`` y ``BAND_LABELS``). ``no_calculable`` (D-SC-19) es la de una
#: falla: el detalle —el mensaje del motor— viaja aparte, en ``EdaCardSection.failed_analyses``.
DEFAULT_RATE_NOT_EVALUABLE_REASON_LABELS: Final[dict[str, str]] = {
    "sin_eje_temporal": "el archivo no trae columna de fecha ni cohorte declarada",
    "no_calculable": "no se pudo calcular",
}

#: Las palabras públicas de cada eje: el panel y el informe dicen «por fecha de observación» o
#: «por cohorte», nunca ``period``/``cohort`` crudos (D-SC-5; mismo molde que ``BAND_LABELS``).
AXIS_LABELS: Final[dict[str, str]] = {
    "period": "por fecha de observación",
    "cohort": "por cohorte",
}

#: Períodos o cohortes de ``by_period`` que las superficies PUBLICAN como máximo —la respuesta de
#: la interfaz y la tabla del informe—, en el orden del motor (cierre 1 de D-SC, decidido por
#: delegación de Cami el 2026-09-12). El eje de cohorte acepta cualquier columna y una casi única
#: produce una fila por operación; el motor calcula y conserva la tabla ENTERA —este tope no la
#: toca— y quien la publica dice cuántas filas hay y que recortó. La capa ``ui`` no importa
#: dominios: replica el valor y un gate ata los dos.
MAX_PUBLISHED_PERIODS: Final = 1000

#: Prefijo de la ruta de este dominio en ``NikodymConfig``, para anclar sus errores (D-EXI-5).
_LOC_SECCION: tuple[str, ...] = ("eda",)

_GROUP_COL: Final = "__nikodym_eda_period"
_ELIGIBLE_COL: Final = "__nikodym_eda_eligible"
_BAD_COL: Final = "__nikodym_eda_bad"
_RESULT_COLUMNS: Final = (
    "period",
    "n_total",
    "n_eligible",
    "n_bad",
    "default_rate",
    "low_confidence",
)


class DefaultRateResult(BaseModel):
    """Resultado inmutable de la tasa de default por período/cohorte.

    ``not_evaluable_reason`` es aditivo (D-SC-17) y sigue el molde que D-SC-2 le dio a
    ``StabilityResult``: la causa por la que la tasa **no se pudo agrupar**, o ``None``. La
    invariante, probada en los dos sentidos, se ancla en la TABLA —hay causa si y sólo si
    ``by_period`` está vacía— y no en ``overall_rate``, porque ahí el ``NaN`` ya significaba desde
    antes «sin operaciones elegibles» y las dos ausencias son independientes.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    by_period: pd.DataFrame
    axis: EdaAxis
    overall_rate: float
    #: Aditivo (D-SC-17): la causa cuando no hay eje con que agrupar, o ``None``.
    not_evaluable_reason: DefaultRateNotEvaluableReason | None = None

    @model_validator(mode="after")
    def _causa_si_y_solo_si_tabla_vacia(self) -> DefaultRateResult:
        """La invariante se **comprueba**, no sólo se documenta (D-SC-17).

        Aguas abajo la causa apaga la figura, la tabla del informe y la validación de columnas de
        la estabilidad. Un resultado con causa **y** filas haría que esas superficies escondieran
        evidencia que sí existe, y uno sin causa y sin filas dejaría al lector sin saber por qué no
        hay tabla. Ninguno de los dos lo puede producir el motor; los dos los puede construir a
        mano quien use esta API estable, así que el DTO los rechaza en su frontera.

        🔴 **Sólo se comprueba la dirección aditiva**: «con causa ⇒ tabla vacía y con sus seis
        columnas». La recíproca —«tabla vacía ⇒ causa»— **no** se exige aquí, y no por descuido:
        antes de esta enmienda ``DefaultRateResult(by_period=<vacía>, …)`` era una construcción
        legal de una API estable 1.x, y prohibirla en una minor sería una ruptura (hallazgo
        adversarial del rango, verificado). Una tabla vacía sin causa se sigue tratando como
        siempre —el informe la recolecta, nadie la omite—, así que tampoco esconde nada. La
        bicondicional sigue siendo la invariante del **motor**, y sus tests la prueban en los dos
        sentidos; lo que el DTO garantiza es que nadie apague superficies sin haber vaciado la
        tabla.
        """
        if self.not_evaluable_reason is None:
            return self
        if len(self.by_period.index) != 0:
            raise ValueError(
                "DefaultRateResult con causa de no evaluabilidad y tabla no vacía: la causa apaga "
                "la figura y la tabla del informe, así que publicarla con filas escondería "
                "evidencia calculada."
            )
        faltan = [c for c in _RESULT_COLUMNS if c not in self.by_period.columns]
        if faltan:
            joined = ", ".join(f"'{c}'" for c in faltan)
            raise ValueError(
                f"DefaultRateResult no evaluable sin la(s) columna(s) {joined}: sus "
                "consumidores leen columnas aunque no haya filas."
            )
        return self


class DefaultRateAnalyzer:
    """Calcula la tasa de default sobre la población elegible del target."""

    def __init__(self, config: DefaultRateConfig) -> None:
        """Construye el analizador con ``EdaConfig.default_rate``."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: DefaultRateConfig) -> DefaultRateAnalyzer:
        """Construye un analizador desde ``DefaultRateConfig``."""
        return cls(cfg)

    def compute(
        self,
        frame: pd.DataFrame,
        *,
        target_col: str,
        audit: AuditSink | None = None,
    ) -> DefaultRateResult:
        """Calcula la tasa de default por período/cohorte sin mutar el input.

        Parameters
        ----------
        frame : pandas.DataFrame
            Dataset etiquetado por ``data`` o equivalente standalone.
        target_col : str
            Columna binaria nullable: ``1`` malo, ``0`` bueno, ``<NA>`` no elegible.
        audit : AuditSink or None
            Reservado para compatibilidad con la orquestación; este analizador puro no emite
            eventos auditables.

        Returns
        -------
        DefaultRateResult
            Tabla agregada ordenada y tasa global ponderada por elegibles.

        Raises
        ------
        EdaError
            Si faltan columnas requeridas, el eje temporal es ambiguo/no datetime o no hay filas
            que describir.
        """
        del audit
        _validar_poblacion(frame, target_col=target_col)

        source = frame.copy(deep=True)
        group_frame = _resolve_group_frame(source, self.config)
        target = source[target_col]
        aggregation_frame = group_frame.copy(deep=True)
        aggregation_frame[_ELIGIBLE_COL] = _eligible_mask(target)
        aggregation_frame[_BAD_COL] = _bad_mask(target)
        by_period = _aggregate_default_rate(
            aggregation_frame,
            axis=self.config.axis,
            min_obs_per_period=self.config.min_obs_per_period,
        )
        return DefaultRateResult(
            by_period=by_period.copy(deep=True),
            axis=self.config.axis,
            overall_rate=_overall_rate(by_period),
        )


def tasa_no_evaluable(
    frame: pd.DataFrame,
    *,
    target_col: str,
    axis: EdaAxis,
    reason: DefaultRateNotEvaluableReason,
) -> DefaultRateResult:
    """La tasa que no se pudo agrupar: tabla vacía, causa declarada y tasa global (D-SC-17).

    Vive aquí, en el módulo dueño del DTO, para que la invariante de ``DefaultRateResult`` tenga
    **una sola** fuente: ``EdaStep`` decide *cuándo* no hay eje (es el único que ve la partición
    declarada, D-SC-3), y este constructor decide *qué forma* tiene ese resultado.

    🔴 **Valida la población igual que ``compute``.** Los tres guards —frame no vacío, índice
    único, columna de target presente— vivían dentro de ``compute``, que esta rama no llama;
    saltárselos aceptaría un índice duplicado, que es lo contrario de reproducible, o mataría la
    corrida con un ``KeyError`` incidental en vez del ``EdaError`` del contrato.

    ``by_period`` sale vacía y no con una fila ``<NA>`` que agregue toda la población: esa fila
    sería un período inventado, y el informe y el panel la pintarían como una serie de un punto.
    ``overall_rate`` sí se calcula —no necesita eje— con la **misma regla de siempre**: ``NaN``
    cuando no hay ninguna operación elegible.
    """
    _validar_poblacion(frame, target_col=target_col)
    target = frame[target_col]
    n_eligible = int(_eligible_mask(target).sum())
    n_bad = int(_bad_mask(target).sum())
    overall = float("nan") if n_eligible == 0 else float(n_bad / n_eligible)
    return DefaultRateResult(
        by_period=_tabla_vacia(),
        axis=axis,
        overall_rate=overall,
        not_evaluable_reason=reason,
    )


def tasa_no_calculable(
    frame: pd.DataFrame | None,
    *,
    target_col: str | None,
    axis: EdaAxis,
) -> DefaultRateResult:
    """La tasa que FALLÓ, sea por lo que sea: tabla vacía y causa ``no_calculable`` (D-SC-19).

    Es la red del paso, y por eso su contrato es el contrario al de :func:`tasa_no_evaluable`:
    **no valida la población y nunca levanta**. Aquélla valida porque se usa cuando la población
    es buena y sólo falta el eje; ésta se usa cuando algo falló —una fecha ambigua, una columna
    declarada que no existe o una población rota— y validar aquí volvería a detener la corrida
    justo en los casos que tiene que rescatar (revisión adversarial de la enmienda, pasada 1).

    ``overall_rate`` se conserva cuando se puede: si el frame existe, trae la columna del target y
    tiene elegibles —el caso de las dos fechas, donde la población es buena—, es la tasa global de
    siempre. Si no, ``NaN``, y las superficies dicen «no disponible», nunca «sin elegibles».
    """
    return DefaultRateResult(
        by_period=_tabla_vacia(),
        axis=axis,
        overall_rate=_tasa_global_si_se_puede(frame, target_col),
        not_evaluable_reason="no_calculable",
    )


def _tasa_global_si_se_puede(frame: pd.DataFrame | None, target_col: str | None) -> float:
    """``n_malos / n_elegibles`` sobre el frame, o ``NaN`` si no hay con qué. Nunca levanta."""
    try:
        if frame is None or target_col is None or target_col not in frame.columns:
            return float("nan")
        target = frame[target_col]
        n_eligible = int(_eligible_mask(target).sum())
        if n_eligible == 0:
            return float("nan")
        return float(int(_bad_mask(target).sum()) / n_eligible)
    except Exception:
        return float("nan")


def _tabla_vacia() -> pd.DataFrame:
    """``by_period`` sin filas y con las seis columnas del contrato, en su orden y con su dtype."""
    return pd.DataFrame(
        {
            "period": pd.Series([], dtype="object"),
            "n_total": pd.Series([], dtype="int64"),
            "n_eligible": pd.Series([], dtype="int64"),
            "n_bad": pd.Series([], dtype="int64"),
            "default_rate": pd.Series([], dtype="float64"),
            "low_confidence": pd.Series([], dtype="bool"),
        }
    )


def _validar_poblacion(frame: pd.DataFrame, *, target_col: str) -> None:
    """Las tres validaciones de entrada, compartidas por las DOS rutas de la tasa (D-SC-17)."""
    _validate_non_empty_frame(frame)
    _validate_unique_index(frame)
    _validate_target_column(frame, target_col)


def _validate_non_empty_frame(frame: pd.DataFrame) -> None:
    """Rechaza particiones vacías: no hay población que describir."""
    if frame.empty:
        raise EdaError("La población entregada a EDA no tiene filas para describir.")


def _validate_unique_index(frame: pd.DataFrame) -> None:
    """Falla temprano si el índice no identifica observaciones de forma única."""
    if frame.index.is_unique:
        return

    duplicates = frame.index[frame.index.duplicated()].unique()
    sample = ", ".join(repr(value) for value in duplicates[:5])
    raise EdaError(
        "DefaultRateAnalyzer requiere un índice único para garantizar reproducibilidad; "
        f"el índice contiene {len(duplicates)} etiqueta(s) duplicada(s): {sample}. "
        "Defina un identificador de observación único antes de calcular default_rate."
    )


def _validate_target_column(frame: pd.DataFrame, target_col: str) -> None:
    """Valida que exista la columna de target antes de agregar."""
    if target_col not in frame.columns:
        raise EdaError(
            f"La tasa de default requiere una columna target existente: target_col='{target_col}'."
        )


def _resolve_group_frame(frame: pd.DataFrame, config: DefaultRateConfig) -> pd.DataFrame:
    """Resuelve la clave interna de agrupación y la etiqueta visible del eje."""
    if config.axis == "period":
        periods = _period_values(frame, config)
        return pd.DataFrame({_GROUP_COL: periods, "period": periods}, index=frame.index)

    cohorts = _cohort_values(frame, config)
    return pd.DataFrame(
        {
            _GROUP_COL: cohorts.map(_stable_label),
            "period": cohorts.map(_cohort_display_value),
        },
        index=frame.index,
    )


def _period_values(frame: pd.DataFrame, config: DefaultRateConfig) -> pd.Series:
    """Discretiza la columna datetime configurada o inferida con ``to_period``."""
    date_col = config.date_col if config.date_col is not None else _infer_date_column(frame)
    if date_col not in frame.columns:
        raise EdaError(
            "La tasa de default por período referencia una columna de fecha inexistente: "
            f"date_col='{date_col}'."
        )

    dates = frame[date_col]
    if not pd.api.types.is_datetime64_any_dtype(dates.dtype):
        raise EdaError(
            "La tasa de default por período requiere una columna datetime; "
            f"date_col='{date_col}', dtype={dates.dtype}."
        )

    normalized_dates = _drop_timezone_without_warning(dates)
    periods = normalized_dates.dt.to_period(config.period_freq)
    periods.name = "period"
    return cast(pd.Series, periods)


def datetime_columns(frame: pd.DataFrame) -> tuple[str, ...]:
    """Las columnas ``datetime`` del frame, en su orden: la única base de la inferencia de fecha."""
    return tuple(
        str(column)
        for column in frame.columns
        if pd.api.types.is_datetime64_any_dtype(frame[column].dtype)
    )


def _infer_date_column(frame: pd.DataFrame) -> str:
    """Infiere la única columna datetime; falla si falta o si hay ambigüedad."""
    date_columns = list(datetime_columns(frame))
    if len(date_columns) == 1:
        return date_columns[0]
    if not date_columns:
        raise EdaError(
            "La tasa de default por período requiere una columna de fecha; declárela en "
            "eda.default_rate.date_col o use axis='cohort'.",
            loc=(*_LOC_SECCION, "default_rate", "date_col"),
        )
    joined = ", ".join(f"'{column}'" for column in date_columns)
    raise EdaError(
        "La tasa de default por período encontró más de una columna datetime plausible; "
        f"declare eda.default_rate.date_col explícitamente. Columnas detectadas: {joined}."
    )


def _drop_timezone_without_warning(dates: pd.Series) -> pd.Series:
    """Elimina zona horaria antes de ``to_period`` para evitar warnings de pandas."""
    timezone = getattr(dates.dt, "tz", None)
    if timezone is None:
        return dates
    return cast(pd.Series, dates.dt.tz_localize(None))


def _cohort_values(frame: pd.DataFrame, config: DefaultRateConfig) -> pd.Series:
    """Devuelve la cohorte configurada como eje de agregación."""
    cohort_col = config.cohort_col
    if cohort_col is None:
        raise EdaError(
            "La tasa de default por cohorte requiere declarar eda.default_rate.cohort_col."
        )
    if cohort_col not in frame.columns:
        raise EdaError(
            "La tasa de default por cohorte referencia una columna inexistente: "
            f"cohort_col='{cohort_col}'."
        )
    cohorts = frame[cohort_col].copy(deep=True)
    cohorts.name = "period"
    return cohorts


def _eligible_mask(target: pd.Series) -> pd.Series:
    """Marca filas con target binario válido ``0`` o ``1``."""
    return target.isin((0, 1)).fillna(False).astype("bool")


def _bad_mask(target: pd.Series) -> pd.Series:
    """Marca filas malas entre los targets válidos."""
    return target.eq(1).fillna(False).astype("bool")


def _aggregate_default_rate(
    frame: pd.DataFrame,
    *,
    axis: EdaAxis,
    min_obs_per_period: int,
) -> pd.DataFrame:
    """Agrega conteos y tasas por eje, con orden determinista."""
    grouped = frame.groupby(_GROUP_COL, dropna=False, observed=True, sort=False)
    result = grouped.agg(
        period=("period", "first"),
        n_total=(_ELIGIBLE_COL, "size"),
        n_eligible=(_ELIGIBLE_COL, "sum"),
        n_bad=(_BAD_COL, "sum"),
    ).reset_index()
    result["n_total"] = result["n_total"].astype("int64")
    result["n_eligible"] = result["n_eligible"].astype("int64")
    result["n_bad"] = result["n_bad"].astype("int64")
    result["default_rate"] = _default_rate_series(result)
    result["low_confidence"] = result["n_eligible"].lt(min_obs_per_period).astype("bool")
    result = _sort_result(result, axis)
    return result.loc[:, list(_RESULT_COLUMNS)].reset_index(drop=True)


def _default_rate_series(result: pd.DataFrame) -> pd.Series:
    """Calcula ``n_bad / n_eligible`` y deja ``NaN`` cuando el denominador es cero."""
    denominators = result["n_eligible"].replace(0, np.nan).astype("float64")
    return (result["n_bad"].astype("float64") / denominators).astype("float64")


def _sort_result(result: pd.DataFrame, axis: EdaAxis) -> pd.DataFrame:
    """Ordena períodos reales por valor temporal y cohortes por etiqueta estable."""
    if axis == "period":
        return result.sort_values("period", kind="mergesort", na_position="last")

    return result.sort_values(_GROUP_COL, kind="mergesort")


def _stable_label(value: object) -> str:
    """Clave tipo-consciente para cohortes; no es serialización inyectiva universal."""
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return ""
    value_type = type(value)
    type_token = f"{value_type.__module__}.{value_type.__qualname__}"
    return f"{type_token}:{value!r}"


def _cohort_display_value(value: object) -> object:
    """Normaliza solo faltantes para que el representante visible no dependa del orden."""
    if _stable_label(value) == "":
        return pd.NA
    return value


def _overall_rate(by_period: pd.DataFrame) -> float:
    """Calcula tasa global ponderada por elegibles."""
    n_eligible = int(by_period["n_eligible"].sum())
    if n_eligible == 0:
        return float("nan")
    return float(by_period["n_bad"].sum() / n_eligible)
