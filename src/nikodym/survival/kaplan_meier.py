"""Estimador Kaplan-Meier no paramétrico para lifetime PD (SDD-18 §3/§7).

``KaplanMeierSurvivalModel`` calcula manualmente la curva agregada ``S(t)`` y la varianza de
Greenwood con ``numpy``; no usa lifelines en la ruta core. El estimador publica una curva
poblacional o una curva por segmento configurado, con ``row_id=None`` porque Kaplan-Meier no
produce predicción individual en este bloque.

El módulo mantiene liviano ``import nikodym.survival``: pandas y numpy se importan solo dentro de
``fit``/``predict_*``/``term_structure`` y sus helpers.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias, cast

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import NotFittedError
from nikodym.core.mixins import AuditableMixin
from nikodym.survival.config import SurvivalConfig, SurvivalInputConfig
from nikodym.survival.exceptions import (
    SurvivalConfigError,
    SurvivalInputError,
    SurvivalTransformError,
)

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    NDArrayInt: TypeAlias = np.ndarray[Any, np.dtype[np.int64]]
    Series: TypeAlias = pd.Series[Any]
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any
    NDArrayInt: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["KaplanMeierSurvivalModel"]

_METHOD: Literal["kaplan_meier"] = "kaplan_meier"
_ROW_ID = None
_PARTITION = None
_SCENARIO = None
_NO_CONFIDENCE_WARNING = "FALTA-DATO-SUR-3"
_NO_EVENTS_WARNING = "FALTA-DATO-SUR-2"
_NO_TIME_GRID_WARNING = "FALTA-DATO-SUR-1"
_TERM_STRUCTURE_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "partition",
    "period",
    "time_value",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "method",
    "pd_source",
    "scenario",
    "warning_codes",
)
_SURVIVAL_CURVE_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "period",
    "time_value",
    "survival",
    "survival_lower",
    "survival_upper",
    "greenwood_variance",
)
_HAZARD_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "period",
    "time_value",
    "hazard",
    "link",
    "linear_predictor_hazard",
)
_FLOAT_ATOL = 1e-12


@dataclass(frozen=True)
class _CurveEstimate:
    segment: str | None
    n_rows: int
    n_events: int
    n_censored: int
    max_observed_time: float
    event_times: tuple[float, ...]
    survival: tuple[float, ...]
    greenwood_variance: tuple[float, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _GridPoint:
    period: int
    time_value: float
    survival: float
    greenwood_variance: float
    survival_lower: float | None
    survival_upper: float | None
    hazard: float
    pd_marginal: float
    pd_cumulative: float


class KaplanMeierSurvivalModel(AuditableMixin):
    """Calcula Kaplan-Meier agregado y publica curvas, hazards y term-structure."""

    config_cls: ClassVar[type[SurvivalConfig]] = SurvivalConfig

    def __init__(self, *, config: SurvivalConfig | Mapping[str, Any] | None = None) -> None:
        """Asigna la configuración survival sin ejecutar cálculos estadísticos."""
        if config is None or isinstance(config, SurvivalConfig):
            self.config = config
        else:
            self.config = SurvivalConfig.model_validate(config)

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig | Mapping[str, Any]) -> KaplanMeierSurvivalModel:
        """Construye el estimador desde ``SurvivalConfig`` y exige ``method='kaplan_meier'``."""
        if not isinstance(cfg, SurvivalConfig):
            cfg = SurvivalConfig.model_validate(cfg)
        if cfg.method != _METHOD:
            raise SurvivalConfigError(
                "KaplanMeierSurvivalModel.from_config exige method='kaplan_meier'."
            )
        return cls(config=cfg)

    def fit(
        self,
        frame: DataFrame,
        *,
        duration_col: str,
        event_col: str,
        covariate_cols: tuple[str, ...] = (),
        pd_frame: DataFrame | None = None,
        audit: AuditSink | None = None,
    ) -> Self:
        """Ajusta curvas Kaplan-Meier poblacionales o por segmento configurado."""
        pd = _import_pandas()
        np = _import_numpy()
        del pd_frame
        if audit is not None:
            self._audit = audit

        cfg = _effective_config(self.config, duration_col=duration_col, event_col=event_col)
        copied = _as_dataframe(frame, pd)
        _validate_unique_index(copied)
        _validate_required_columns(
            copied,
            duration_col=duration_col,
            event_col=event_col,
            covariate_cols=covariate_cols,
            segment_col=cfg.input.segment_col,
        )
        durations = _duration_array(copied[duration_col], column=duration_col, np=np)
        events = _event_array(copied[event_col], column=event_col, np=np)
        segments = _segment_values(copied, segment_col=cfg.input.segment_col, pd=pd)

        curves = _fit_curves(
            durations=durations,
            events=events,
            segments=segments,
            np=np,
        )
        warnings = _global_warnings(cfg)
        self.config_ = cfg
        self.duration_col_ = duration_col
        self.event_col_ = event_col
        self.segment_col_ = cfg.input.segment_col
        self.curves_ = curves
        self.warning_codes_ = warnings
        self.n_rows_ = len(copied.index)
        self.n_events_ = int(events.sum())
        self.n_censored_ = int(self.n_rows_ - self.n_events_)
        self.max_observed_time_ = _clean_float(float(np.max(durations)))
        self.log_decision(
            regla="survival_input_quality",
            umbral={"duration_col": duration_col, "event_col": event_col},
            valor={
                "n_rows": self.n_rows_,
                "n_events": self.n_events_,
                "n_censored": self.n_censored_,
                "max_observed_time": self.max_observed_time_,
            },
            accion="fit_kaplan_meier",
        )
        self.log_decision(
            regla="survival_km_greenwood",
            umbral={
                "confidence_level": cfg.kaplan_meier.confidence_level,
                "confidence_transform": cfg.kaplan_meier.confidence_transform,
            },
            valor={"curvas": len(curves), "warnings": warnings},
            accion="publicar_varianza_o_ic",
        )
        return self

    def predict_survival(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Predice curvas ``S(t)`` y varianza/IC Greenwood en la grilla solicitada."""
        pd = _import_pandas()
        selected = self._selected_curves(frame, pd=pd)
        rows, index = _survival_rows(self, selected, times)
        return _records_to_frame(rows, columns=_SURVIVAL_CURVE_COLUMNS, index=index, pd=pd)

    def predict_hazard(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Predice hazards discretos derivados de Kaplan-Meier por período de la grilla."""
        pd = _import_pandas()
        selected = self._selected_curves(frame, pd=pd)
        rows, index = _hazard_rows(self, selected, times)
        return _records_to_frame(rows, columns=_HAZARD_COLUMNS, index=index, pd=pd)

    def term_structure(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Publica lifetime PD tidy: hazard, supervivencia, PD marginal y acumulada."""
        pd = _import_pandas()
        selected = self._selected_curves(frame, pd=pd)
        rows, index = _term_structure_rows(self, selected, times)
        return _records_to_frame(rows, columns=_TERM_STRUCTURE_COLUMNS, index=index, pd=pd)

    def _selected_curves(self, frame: DataFrame, *, pd: Any) -> tuple[_CurveEstimate, ...]:
        if not hasattr(self, "curves_"):
            raise NotFittedError(
                "KaplanMeierSurvivalModel no está fiteado; llame fit(...) antes de predecir."
            )
        copied = _as_dataframe(frame, pd)
        curves = self.curves_
        segment_col = self.segment_col_
        if segment_col is None:
            return curves
        if segment_col not in copied.columns:
            raise SurvivalInputError(
                f"KaplanMeierSurvivalModel requiere segment_col='{segment_col}' en predicción."
            )

        known = {curve.segment: curve for curve in curves}
        selected: list[_CurveEstimate] = []
        for segment in _unique_segments(copied[segment_col]):
            if segment not in known:
                raise SurvivalTransformError(
                    "Segmento no observado durante fit: "
                    f"columna='{segment_col}', valor={segment!r}."
                )
            selected.append(known[segment])
        return tuple(selected)


def _effective_config(
    config: SurvivalConfig | None,
    *,
    duration_col: str,
    event_col: str,
) -> SurvivalConfig:
    if config is not None:
        if config.method != _METHOD:
            raise SurvivalConfigError("KaplanMeierSurvivalModel exige method='kaplan_meier'.")
        return config
    return SurvivalConfig(
        method=_METHOD,
        input=SurvivalInputConfig(
            duration_col=duration_col,
            event_col=event_col,
            pd_source="none",
        ),
        fail_on_falta_dato=False,
    )


def _fit_curves(
    *,
    durations: NDArrayFloat,
    events: NDArrayInt,
    segments: tuple[str | None, ...],
    np: Any,
) -> tuple[_CurveEstimate, ...]:
    curves: list[_CurveEstimate] = []
    for segment in _ordered_unique(segments):
        mask = np.array([item == segment for item in segments], dtype=bool)
        curves.append(
            _fit_single_curve(
                durations=durations[mask],
                events=events[mask],
                segment=segment,
                np=np,
            )
        )
    return tuple(curves)


def _fit_single_curve(
    *,
    durations: NDArrayFloat,
    events: NDArrayInt,
    segment: str | None,
    np: Any,
) -> _CurveEstimate:
    event_mask = events == 1
    event_times_array = np.unique(durations[event_mask])
    n_rows = int(durations.size)
    n_events = int(events.sum())
    n_censored = n_rows - n_events
    max_observed_time = _clean_float(float(np.max(durations)))
    warnings = (_NO_EVENTS_WARNING,) if n_events == 0 else ()

    if n_events == 0:
        return _CurveEstimate(
            segment=segment,
            n_rows=n_rows,
            n_events=0,
            n_censored=n_censored,
            max_observed_time=max_observed_time,
            event_times=(),
            survival=(),
            greenwood_variance=(),
            warnings=warnings,
        )

    survival_values: list[float] = []
    variance_values: list[float] = []
    survival = 1.0
    greenwood_sum = 0.0
    for event_time in event_times_array:
        at_risk = int(np.sum(durations >= event_time))
        event_count = int(np.sum((durations == event_time) & event_mask))
        hazard = event_count / at_risk
        survival *= 1.0 - hazard
        if at_risk > event_count:
            greenwood_sum += event_count / (at_risk * (at_risk - event_count))
            variance = survival * survival * greenwood_sum
        else:
            variance = 0.0
        _unit_float(hazard, field_name="hazard")
        survival_values.append(_unit_float(survival, field_name="survival"))
        variance_values.append(_non_negative_float(variance, field_name="greenwood_variance"))

    return _CurveEstimate(
        segment=segment,
        n_rows=n_rows,
        n_events=n_events,
        n_censored=n_censored,
        max_observed_time=max_observed_time,
        event_times=tuple(_clean_float(float(value)) for value in event_times_array),
        survival=tuple(survival_values),
        greenwood_variance=tuple(variance_values),
        warnings=warnings,
    )


def _survival_rows(
    model: KaplanMeierSurvivalModel,
    curves: tuple[_CurveEstimate, ...],
    times: Sequence[int | float],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    index: list[str] = []
    for curve in curves:
        points, _fallback_warning = _grid_points(model, curve, times)
        for point in points:
            rows.append(
                {
                    "row_id": _ROW_ID,
                    "segment": curve.segment,
                    "period": point.period,
                    "time_value": point.time_value,
                    "survival": point.survival,
                    "survival_lower": point.survival_lower,
                    "survival_upper": point.survival_upper,
                    "greenwood_variance": point.greenwood_variance,
                }
            )
            index.append(_curve_index(curve.segment, point.period))
    return rows, index


def _hazard_rows(
    model: KaplanMeierSurvivalModel,
    curves: tuple[_CurveEstimate, ...],
    times: Sequence[int | float],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    index: list[str] = []
    for curve in curves:
        points, _fallback_warning = _grid_points(model, curve, times)
        for point in points:
            rows.append(
                {
                    "row_id": _ROW_ID,
                    "segment": curve.segment,
                    "period": point.period,
                    "time_value": point.time_value,
                    "hazard": point.hazard,
                    "link": None,
                    "linear_predictor_hazard": None,
                }
            )
            index.append(_curve_index(curve.segment, point.period))
    return rows, index


def _term_structure_rows(
    model: KaplanMeierSurvivalModel,
    curves: tuple[_CurveEstimate, ...],
    times: Sequence[int | float],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    index: list[str] = []
    cfg = model.config_
    for curve in curves:
        points, fallback_warning = _grid_points(model, curve, times)
        global_warnings = model.warning_codes_
        warning_codes = tuple(
            dict.fromkeys(
                (
                    *global_warnings,
                    *((fallback_warning,) if fallback_warning is not None else ()),
                    *curve.warnings,
                )
            )
        )
        for point in points:
            rows.append(
                {
                    "row_id": _ROW_ID,
                    "segment": curve.segment,
                    "partition": _PARTITION,
                    "period": point.period,
                    "time_value": point.time_value,
                    "hazard": point.hazard,
                    "survival": point.survival,
                    "pd_marginal": point.pd_marginal,
                    "pd_cumulative": point.pd_cumulative,
                    "method": _METHOD,
                    "pd_source": cfg.input.pd_source,
                    "scenario": _SCENARIO,
                    "warning_codes": warning_codes,
                }
            )
            index.append(_curve_index(curve.segment, point.period))
    return rows, index


def _grid_points(
    model: KaplanMeierSurvivalModel,
    curve: _CurveEstimate,
    times: Sequence[int | float],
) -> tuple[tuple[_GridPoint, ...], str | None]:
    cfg = model.config_
    resolved_times, fallback_warning = _resolve_times(model, times)
    confidence_level = cfg.kaplan_meier.confidence_level
    confidence_transform = cfg.kaplan_meier.confidence_transform
    z_value = (
        NormalDist().inv_cdf((1.0 + confidence_level) / 2.0)
        if confidence_level is not None and confidence_transform is not None
        else None
    )
    points: list[_GridPoint] = []
    previous_survival = 1.0
    for period, time_value in enumerate(resolved_times, start=1):
        if time_value > curve.max_observed_time + _FLOAT_ATOL:
            raise SurvivalTransformError(
                "Kaplan-Meier no extrapola fuera del soporte observado: "
                f"time_value={time_value}, max_observed_time={curve.max_observed_time}."
            )
        survival, variance = _curve_at(curve, time_value)
        lower, upper = _confidence_bounds(
            survival=survival,
            variance=variance,
            z_value=z_value,
            transform=confidence_transform,
        )
        pd_marginal = _clean_float(max(0.0, previous_survival - survival))
        pd_cumulative = _clean_float(1.0 - survival)
        hazard = _clean_float(pd_marginal / previous_survival) if previous_survival > 0.0 else 0.0
        points.append(
            _GridPoint(
                period=period,
                time_value=time_value,
                survival=survival,
                greenwood_variance=variance,
                survival_lower=lower,
                survival_upper=upper,
                hazard=_unit_float(hazard, field_name="hazard"),
                pd_marginal=_non_negative_float(pd_marginal, field_name="pd_marginal"),
                pd_cumulative=_unit_float(pd_cumulative, field_name="pd_cumulative"),
            )
        )
        previous_survival = survival
    return tuple(points), fallback_warning


def _curve_at(curve: _CurveEstimate, time_value: float) -> tuple[float, float]:
    if not curve.event_times:
        return 1.0, 0.0
    index = -1
    for candidate, event_time in enumerate(curve.event_times):
        if event_time <= time_value + _FLOAT_ATOL:
            index = candidate
        else:
            break
    if index < 0:
        return 1.0, 0.0
    return curve.survival[index], curve.greenwood_variance[index]


def _confidence_bounds(
    *,
    survival: float,
    variance: float,
    z_value: float | None,
    transform: str | None,
) -> tuple[float | None, float | None]:
    if z_value is None or transform is None:
        return None, None
    if variance == 0.0 or survival in {0.0, 1.0}:
        return survival, survival
    standard_error = math.sqrt(variance)
    if transform == "plain":
        return _ordered_unit_bounds(
            survival - z_value * standard_error,
            survival + z_value * standard_error,
        )
    log_survival = math.log(survival)
    transformed = math.log(-log_survival)
    transformed_se = standard_error / abs(survival * log_survival)
    lower = math.exp(-math.exp(transformed + z_value * transformed_se))
    upper = math.exp(-math.exp(transformed - z_value * transformed_se))
    return _ordered_unit_bounds(lower, upper)


def _ordered_unit_bounds(lower: float, upper: float) -> tuple[float, float]:
    low = _clip_unit(lower)
    high = _clip_unit(upper)
    return low, high


def _resolve_times(
    model: KaplanMeierSurvivalModel,
    times: Sequence[int | float],
) -> tuple[tuple[float, ...], str | None]:
    cfg = model.config_
    values = tuple(times)
    fallback_warning: str | None = None
    if not values:
        if cfg.time_grid.evaluation_times:
            values = cfg.time_grid.evaluation_times
        elif cfg.time_grid.horizon_periods is not None:
            values = tuple(range(1, cfg.time_grid.horizon_periods + 1))
        else:
            event_times = sorted({time for curve in model.curves_ for time in curve.event_times})
            observed_times = (
                event_times
                if event_times
                else sorted({curve.max_observed_time for curve in model.curves_})
            )
            values = tuple(observed_times)
            fallback_warning = _NO_TIME_GRID_WARNING
    return _validate_times(values), fallback_warning


def _validate_times(values: Sequence[int | float]) -> tuple[float, ...]:
    normalized: list[float] = []
    for position, value in enumerate(values):
        if isinstance(value, bool):
            raise SurvivalTransformError(
                f"times contiene un valor booleano en posición {position}: {value!r}."
            )
        candidate = float(value)
        if not math.isfinite(candidate) or candidate <= 0.0:
            raise SurvivalTransformError(
                f"times debe contener tiempos positivos y finitos; posición={position}, "
                f"valor={value!r}."
            )
        normalized.append(_clean_float(candidate))
    ordered = tuple(sorted(normalized))
    if len(set(ordered)) != len(ordered):
        raise SurvivalTransformError(f"times contiene tiempos duplicados: {values!r}.")
    return ordered


def _global_warnings(cfg: SurvivalConfig) -> tuple[str, ...]:
    if cfg.kaplan_meier.confidence_level is None or cfg.kaplan_meier.confidence_transform is None:
        return (_NO_CONFIDENCE_WARNING,)
    return ()


def _validate_required_columns(
    frame: DataFrame,
    *,
    duration_col: str,
    event_col: str,
    covariate_cols: tuple[str, ...],
    segment_col: str | None,
) -> None:
    required = [duration_col, event_col, *covariate_cols]
    if segment_col is not None:
        required.append(segment_col)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise SurvivalInputError(f"Faltan columnas requeridas para survival: {missing}.")


def _validate_unique_index(frame: DataFrame) -> None:
    if not frame.index.is_unique:
        duplicated = [str(value) for value in frame.index[frame.index.duplicated()].unique()]
        raise SurvivalInputError(f"El índice de survival debe ser único; duplicados={duplicated}.")


def _duration_array(series: Series, *, column: str, np: Any) -> NDArrayFloat:
    if _is_bool_dtype(series):
        raise SurvivalInputError(f"La duración no puede ser booleana: columna='{column}'.")
    if not _is_numeric_dtype(series):
        raise SurvivalInputError(f"La duración debe ser numérica: columna='{column}'.")
    values = series.to_numpy(dtype="float64", na_value=np.nan)
    invalid_mask = ~np.isfinite(values) | (values <= 0.0)
    if bool(invalid_mask.any()):
        invalid = _invalid_values(series, invalid_mask)
        raise SurvivalInputError(
            f"Duración inválida en columna='{column}'; valores no positivos/no finitos={invalid}."
        )
    return cast("NDArrayFloat", values)


def _event_array(series: Series, *, column: str, np: Any) -> NDArrayInt:
    if _is_bool_dtype(series) or not _is_numeric_dtype(series):
        raise SurvivalInputError(f"Evento debe ser numérico binario 0/1: columna='{column}'.")
    values = series.to_numpy(dtype="float64", na_value=np.nan)
    invalid_mask = ~np.isfinite(values) | ~np.isin(values, [0.0, 1.0])
    if bool(invalid_mask.any()):
        invalid = _invalid_values(series, invalid_mask)
        raise SurvivalInputError(
            f"Evento no binario en columna='{column}'; valores observados inválidos={invalid}."
        )
    return cast("NDArrayInt", values.astype("int64"))


def _segment_values(
    frame: DataFrame,
    *,
    segment_col: str | None,
    pd: Any,
) -> tuple[str | None, ...]:
    if segment_col is None:
        return (None,) * len(frame.index)
    if bool(frame[segment_col].isna().any()):
        raise SurvivalInputError(f"segment_col='{segment_col}' no puede contener valores missing.")
    return tuple(str(value) for value in frame[segment_col].astype("string"))


def _unique_segments(series: Series) -> tuple[str | None, ...]:
    if bool(series.isna().any()):
        raise SurvivalInputError("La columna de segmento de predicción no puede contener missing.")
    return _ordered_unique(tuple(str(value) for value in series.astype("string")))


def _ordered_unique(values: Sequence[str | None]) -> tuple[str | None, ...]:
    observed: dict[str | None, None] = {}
    for value in values:
        observed.setdefault(value, None)
    return tuple(observed)


def _records_to_frame(
    rows: list[dict[str, Any]],
    *,
    columns: tuple[str, ...],
    index: list[str],
    pd: Any,
) -> DataFrame:
    frame = pd.DataFrame(rows, columns=columns)
    frame.index = pd.Index(index, name="curve_id")
    return _normalize_frame(frame)


def _normalize_frame(frame: DataFrame) -> DataFrame:
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        copied[column] = copied[column].mask(copied[column] == 0.0, 0.0)
    return copied


def _as_dataframe(value: object, pd: Any) -> DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise SurvivalInputError("KaplanMeierSurvivalModel requiere un pandas.DataFrame.")
    return cast("DataFrame", value.copy(deep=True))


def _invalid_values(series: Series, mask: Any) -> dict[str, Any]:
    invalid = series.loc[mask]
    return {str(index): value for index, value in invalid.to_dict().items()}


def _is_numeric_dtype(series: Series) -> bool:
    pd = _import_pandas()
    return bool(pd.api.types.is_numeric_dtype(series.dtype))


def _is_bool_dtype(series: Series) -> bool:
    pd = _import_pandas()
    return bool(pd.api.types.is_bool_dtype(series.dtype))


def _curve_index(segment: str | None, period: int) -> str:
    segment_key = "__all__" if segment is None else segment
    return f"{segment_key}|{period}"


def _unit_float(value: float, *, field_name: str) -> float:
    cleaned = _clean_float(value)
    if not math.isfinite(cleaned) or not -_FLOAT_ATOL <= cleaned <= 1.0 + _FLOAT_ATOL:
        raise SurvivalTransformError(f"{field_name} debe quedar en [0, 1]: valor={value!r}.")
    return _clip_unit(cleaned)


def _non_negative_float(value: float, *, field_name: str) -> float:
    cleaned = _clean_float(value)
    if not math.isfinite(cleaned) or cleaned < -_FLOAT_ATOL:
        raise SurvivalTransformError(
            f"{field_name} debe ser finito y no negativo: valor={value!r}."
        )
    return max(0.0, cleaned)


def _clip_unit(value: float) -> float:
    return _clean_float(min(1.0, max(0.0, value)))


def _clean_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value


def _import_pandas() -> Any:
    import pandas as pd

    return pd


def _import_numpy() -> Any:
    import numpy as np

    return np
