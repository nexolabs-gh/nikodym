"""Tasa de default descriptiva para la capa ``eda`` (SDD-27 §4/§6/§7).

``DefaultRateAnalyzer`` agrega una tabla por período o cohorte sin ajustar parámetros ni mutar el
``DataFrame`` de entrada. La población elegible se define estrictamente por ``target`` en
``{0, 1}``; los ``<NA>`` y cualquier valor fuera de contrato quedan fuera del denominador, pero
siguen contando en ``n_total``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Final, Literal, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.core.audit import AuditSink
from nikodym.eda.config import DefaultRateConfig
from nikodym.eda.exceptions import EdaError

__all__ = ["DefaultRateAnalyzer", "DefaultRateResult"]

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
    """Resultado inmutable de la tasa de default por período/cohorte."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    by_period: pd.DataFrame
    axis: Literal["period", "cohort"]
    overall_rate: float


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
        _validate_non_empty_frame(frame)
        _validate_unique_index(frame)
        _validate_target_column(frame, target_col)

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


def _infer_date_column(frame: pd.DataFrame) -> str:
    """Infiere la única columna datetime; falla si falta o si hay ambigüedad."""
    date_columns = [
        str(column)
        for column in frame.columns
        if pd.api.types.is_datetime64_any_dtype(frame[column].dtype)
    ]
    if len(date_columns) == 1:
        return date_columns[0]
    if not date_columns:
        raise EdaError(
            "La tasa de default por período requiere una columna de fecha; declárela en "
            "eda.default_rate.date_col o use axis='cohort'."
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
    axis: Literal["period", "cohort"],
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


def _sort_result(result: pd.DataFrame, axis: Literal["period", "cohort"]) -> pd.DataFrame:
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
