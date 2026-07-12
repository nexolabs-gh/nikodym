"""Modelo discrete-time hazard para lifetime PD individual (SDD-18 §3/§7).

``DiscreteTimeHazardModel`` expande observaciones a formato person-period y ajusta un GLM
Binomial con link ``logit`` o ``cloglog`` usando ``statsmodels``. La salida es individual: cada
fila de predicción conserva su índice como ``row_id`` y publica hazards, supervivencia,
``PD_marginal`` y ``PD_acumulada`` en tablas tidy.

El módulo preserva el import liviano de ``nikodym.survival``: ``pandas``, ``numpy`` y
``statsmodels`` se importan sólo dentro de métodos/helpers de ejecución.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
import warnings
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias, cast

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import MissingDependencyError, NotFittedError
from nikodym.core.mixins import AuditableMixin
from nikodym.survival.config import SurvivalConfig, SurvivalInputConfig
from nikodym.survival.exceptions import (
    SurvivalConfigError,
    SurvivalFitError,
    SurvivalInputError,
    SurvivalTransformError,
)
from nikodym.survival.results import SurvivalCard, SurvivalDiagnostics

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
    Index: TypeAlias = pd.Index
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    NDArrayInt: TypeAlias = np.ndarray[Any, np.dtype[np.int64]]
    Series: TypeAlias = pd.Series[Any]
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Index: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any
    NDArrayInt: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["DiscreteTimeHazardModel"]

_METHOD: Literal["discrete_hazard"] = "discrete_hazard"
_SCORING_EXTRA_MESSAGE = "DiscreteTimeHazardModel requiere statsmodels; instale nikodym[scoring]."
_NO_TIME_GRID_WARNING = "FALTA-DATO-SUR-1"
_PARTITION_COL = "partition"
_PARTITION_DESARROLLO = "desarrollo"
_TARGET_COL = "__event_it"
_PERIOD_COL = "period"
_TIME_VALUE_COL = "time_value"
_INTERCEPT = "const"
_SCENARIO = None
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
class _StatsmodelsComponents:
    glm: Any
    binomial: Any
    logit: Any
    cloglog: Any
    perfect_warning: type[Warning]
    convergence_warning: type[Warning]
    perfect_error: type[Exception]


@dataclass(frozen=True)
class _PredictionPoint:
    row_id: str
    segment: str | None
    partition: str | None
    period: int
    time_value: float
    hazard: float
    linear_predictor: float


class DiscreteTimeHazardModel(AuditableMixin):
    """Ajusta un discrete-time hazard individual con GLM Binomial."""

    config_cls: ClassVar[type[SurvivalConfig]] = SurvivalConfig

    def __init__(self, *, config: SurvivalConfig | Mapping[str, Any] | None = None) -> None:
        """Asigna la configuración survival sin importar motores estadísticos."""
        if config is None or isinstance(config, SurvivalConfig):
            self.config = config
        else:
            self.config = SurvivalConfig.model_validate(config)

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig | Mapping[str, Any]) -> DiscreteTimeHazardModel:
        """Construye el estimador desde ``SurvivalConfig`` y exige ``method='discrete_hazard'``."""
        if not isinstance(cfg, SurvivalConfig):
            cfg = SurvivalConfig.model_validate(cfg)
        if cfg.method != _METHOD:
            raise SurvivalConfigError(
                "DiscreteTimeHazardModel.from_config exige method='discrete_hazard'."
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
        """Ajusta el GLM person-period sobre Desarrollo si existe ``partition``."""
        pd = _import_pandas()
        np = _import_numpy()
        if audit is not None:
            self._audit = audit

        cfg = _effective_config(self.config, duration_col=duration_col, event_col=event_col)
        covariates = _combined_covariates(cfg.input.covariate_cols, covariate_cols)
        prepared = _prepare_fit_frame(
            frame,
            pd_frame=pd_frame,
            cfg=cfg,
            duration_col=duration_col,
            event_col=event_col,
            covariate_cols=covariates,
            pd=pd,
            np=np,
        )
        durations = _duration_period_array(prepared[duration_col], column=duration_col, np=np)
        events = _event_array(prepared[event_col], column=event_col, np=np)
        fit_mask = _fit_mask(prepared, pd=pd, np=np)
        fit_frame = prepared.loc[fit_mask].copy(deep=True)
        fit_durations = cast("NDArrayInt", durations[fit_mask])
        fit_events = cast("NDArrayInt", events[fit_mask])
        if fit_frame.empty:
            raise SurvivalFitError("No hay filas de Desarrollo para ajustar discrete hazard.")
        if int(fit_events.sum()) == 0:
            raise SurvivalFitError("Discrete hazard exige al menos un evento observado.")

        person_period = _expand_person_period_from_arrays(
            fit_frame,
            durations=fit_durations,
            events=fit_events,
            cfg=cfg,
            covariate_cols=covariates,
            pd=pd,
        )
        events_by_period = _events_by_period(person_period)
        _check_min_events(events_by_period, cfg)
        exog, offset, period_values, pd_segment_categories = _design_matrix_for_fit(
            person_period,
            cfg=cfg,
            covariate_cols=covariates,
            pd=pd,
        )
        result = _fit_glm(
            target=person_period[_TARGET_COL],
            exog=exog,
            offset=offset,
            cfg=cfg,
            np=np,
        )

        self.config_ = cfg
        self.duration_col_ = duration_col
        self.event_col_ = event_col
        self.covariate_cols_ = covariates
        self.design_columns_ = tuple(str(column) for column in exog.columns)
        self.period_values_ = period_values
        self.pd_segment_categories_ = pd_segment_categories
        self.result_ = result
        self.params_ = _series_from_result(result.params, self.design_columns_, pd)
        self.max_observed_period_ = int(durations.max())
        self.n_rows_ = len(prepared.index)
        self.n_fit_rows_ = len(fit_frame.index)
        self.n_events_ = int(events.sum())
        self.n_fit_events_ = int(fit_events.sum())
        self.n_censored_ = int(self.n_rows_ - self.n_events_)
        self.person_period_rows_ = len(person_period.index)
        self.events_by_period_ = events_by_period
        self.warning_codes_ = ()
        self.prediction_features_ = _prediction_features(
            prepared,
            cfg=cfg,
            covariate_cols=covariates,
        )
        self.fit_statistics_ = _fit_statistics(result)
        self.dependency_versions_ = _dependency_versions()
        self.diagnostics_ = SurvivalDiagnostics(
            method=_METHOD,
            n_rows=self.n_rows_,
            n_events=self.n_events_,
            n_censored=self.n_censored_,
            max_observed_time=float(self.max_observed_period_),
            link=cfg.discrete_hazard.link,
            fit_statistics=self.fit_statistics_,
        )
        self.card_ = SurvivalCard(
            method=_METHOD,
            pd_source=cfg.input.pd_source,
            duration_col=duration_col,
            event_col=event_col,
            time_unit=cfg.time_grid.time_unit,
            n_rows=self.n_rows_,
            n_events=self.n_events_,
            n_periods=len(self.period_values_),
            output_columns=_TERM_STRUCTURE_COLUMNS,
            diagnostics=self.diagnostics_,
            dependency_versions=self.dependency_versions_,
            falta_dato=(),
            metric_sections={
                "person_period": {
                    "n_rows": self.person_period_rows_,
                    "events_by_period": dict(self.events_by_period_),
                }
            },
        )
        self._log_fit_decisions(cfg, prepared)
        return self

    def predict_survival(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Predice curvas ``S(t)`` individuales en la grilla solicitada."""
        pd = _import_pandas()
        points, _fallback_warning = _predict_points(self, frame, times, pd=pd)
        rows, index = _survival_rows(points)
        return _records_to_frame(rows, columns=_SURVIVAL_CURVE_COLUMNS, index=index, pd=pd)

    def predict_hazard(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Predice hazards ``h_i(t)`` individuales en la grilla solicitada."""
        pd = _import_pandas()
        points, _fallback_warning = _predict_points(self, frame, times, pd=pd)
        rows = [
            {
                "row_id": point.row_id,
                "segment": point.segment,
                "period": point.period,
                "time_value": point.time_value,
                "hazard": point.hazard,
                "link": self.config_.discrete_hazard.link,
                "linear_predictor_hazard": point.linear_predictor,
            }
            for point in points
        ]
        index = [_curve_index(point.row_id, point.period) for point in points]
        return _records_to_frame(rows, columns=_HAZARD_COLUMNS, index=index, pd=pd)

    def term_structure(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Publica lifetime PD tidy individual: hazard, supervivencia y PD marginal/acumulada."""
        pd = _import_pandas()
        points, fallback_warning = _predict_points(self, frame, times, pd=pd)
        rows, index = _term_structure_rows(self, points, fallback_warning)
        return _records_to_frame(rows, columns=_TERM_STRUCTURE_COLUMNS, index=index, pd=pd)

    def _log_fit_decisions(self, cfg: SurvivalConfig, prepared: DataFrame) -> None:
        pd_column = _pd_source_column(cfg)
        coverage = None if pd_column is None else float(prepared[pd_column].notna().mean())
        self.log_decision(
            regla="survival_method",
            umbral={"method": _METHOD, "link": cfg.discrete_hazard.link},
            valor={
                "pd_source": cfg.input.pd_source,
                "pd_role": cfg.discrete_hazard.pd_role,
                "duration_col": self.duration_col_,
                "event_col": self.event_col_,
                "covariate_cols": self.covariate_cols_,
            },
            accion="fit_discrete_hazard",
        )
        self.log_decision(
            regla="survival_input_quality",
            umbral={
                "partition_col": _PARTITION_COL if _PARTITION_COL in prepared.columns else None
            },
            valor={
                "n_rows": self.n_rows_,
                "n_fit_rows": self.n_fit_rows_,
                "n_events": self.n_events_,
                "n_censored": self.n_censored_,
            },
            accion="validar_input_survival",
        )
        self.log_decision(
            regla="survival_pd_source",
            umbral={"pd_source": cfg.input.pd_source, "pd_role": cfg.discrete_hazard.pd_role},
            valor={"column": pd_column, "coverage": coverage},
            accion="usar_fuente_pd",
        )
        self.log_decision(
            regla="survival_person_period",
            umbral={"include_period_dummies": cfg.discrete_hazard.include_period_dummies},
            valor={
                "n_rows": self.person_period_rows_,
                "periods": self.period_values_,
                "events_by_period": dict(self.events_by_period_),
            },
            accion="expandir_person_period",
        )


def _effective_config(
    config: SurvivalConfig | None,
    *,
    duration_col: str,
    event_col: str,
) -> SurvivalConfig:
    if config is not None:
        if config.method != _METHOD:
            raise SurvivalConfigError("DiscreteTimeHazardModel exige method='discrete_hazard'.")
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


def _prepare_fit_frame(
    frame: DataFrame,
    *,
    pd_frame: DataFrame | None,
    cfg: SurvivalConfig,
    duration_col: str,
    event_col: str,
    covariate_cols: tuple[str, ...],
    pd: Any,
    np: Any,
) -> DataFrame:
    copied = _as_dataframe(frame, pd)
    _validate_unique_index(copied)
    _validate_required_columns(
        copied,
        duration_col=duration_col,
        event_col=event_col,
        covariate_cols=covariate_cols,
        segment_col=cfg.input.segment_col,
        id_col=cfg.input.id_col,
    )
    prepared = _merge_pd_source(copied, pd_frame=pd_frame, cfg=cfg, pd=pd)
    _validate_numeric_columns(prepared, columns=covariate_cols, np=np)
    _validate_pd_role_columns(prepared, cfg=cfg, np=np)
    _validate_optional_text_column(prepared, cfg.input.segment_col)
    partition_col = _PARTITION_COL if _PARTITION_COL in prepared.columns else None
    _validate_optional_text_column(prepared, partition_col)
    return prepared


def _merge_pd_source(
    frame: DataFrame,
    *,
    pd_frame: DataFrame | None,
    cfg: SurvivalConfig,
    pd: Any,
) -> DataFrame:
    columns = _pd_source_columns(cfg)
    needs_partition = _PARTITION_COL not in frame.columns
    if cfg.input.pd_source == "none" or (not columns and not needs_partition):
        return frame
    if pd_frame is None:
        raise SurvivalInputError(
            f"pd_source='{cfg.input.pd_source}' exige pd_frame para discrete hazard."
        )
    source = _as_dataframe(pd_frame, pd)
    _validate_unique_index(source)
    source_columns = [*columns]
    if needs_partition and _PARTITION_COL in source.columns:
        source_columns.append(_PARTITION_COL)
    missing_columns = [column for column in source_columns if column not in source.columns]
    if missing_columns:
        raise SurvivalInputError(f"Faltan columnas requeridas en pd_frame: {missing_columns}.")
    missing_index = [str(index) for index in frame.index if index not in source.index]
    if missing_index:
        raise SurvivalInputError(f"pd_frame no cubre filas de survival: {missing_index}.")
    prepared = frame.copy(deep=True)
    aligned = source.loc[frame.index, source_columns]
    for column in source_columns:
        prepared[column] = aligned[column]
    return prepared


def _pd_source_columns(cfg: SurvivalConfig) -> tuple[str, ...]:
    if cfg.input.pd_source == "none" or cfg.discrete_hazard.pd_role == "none":
        return ()
    column = _pd_source_column(cfg)
    return () if column is None else (column,)


def _pd_source_column(cfg: SurvivalConfig) -> str | None:
    if cfg.input.pd_source == "none" or cfg.discrete_hazard.pd_role == "none":
        return None
    if cfg.discrete_hazard.pd_role == "offset":
        return cfg.input.linear_predictor_column
    return cfg.input.pd_column


def _combined_covariates(
    configured: tuple[str, ...],
    explicit: tuple[str, ...],
) -> tuple[str, ...]:
    observed: dict[str, None] = {}
    for column in (*configured, *explicit):
        observed.setdefault(column, None)
    return tuple(observed)


def _fit_mask(frame: DataFrame, *, pd: Any, np: Any) -> NDArrayInt:
    if _PARTITION_COL not in frame.columns:
        return cast("NDArrayInt", np.ones(len(frame.index), dtype=bool))
    if bool(frame[_PARTITION_COL].isna().any()):
        raise SurvivalInputError("La columna partition no puede contener missing.")
    values = frame[_PARTITION_COL].astype("string")
    mask = (values == _PARTITION_DESARROLLO).to_numpy(dtype=bool, na_value=False)
    if bool(mask.any()):
        return cast("NDArrayInt", mask)
    return cast("NDArrayInt", np.ones(len(frame.index), dtype=bool))


def _expand_person_period_from_arrays(
    frame: DataFrame,
    *,
    durations: NDArrayInt,
    events: NDArrayInt,
    cfg: SurvivalConfig,
    covariate_cols: tuple[str, ...],
    pd: Any,
) -> DataFrame:
    rows: list[dict[str, Any]] = []
    index: list[str] = []
    pd_column = _pd_source_column(cfg)
    for row_position, (row_index, row) in enumerate(frame.iterrows()):
        duration = int(durations[row_position])
        event = int(events[row_position])
        row_id = str(row_index)
        for period in range(1, duration + 1):
            record: dict[str, Any] = {
                "row_id": row_id,
                _PERIOD_COL: period,
                _TIME_VALUE_COL: float(period),
                _TARGET_COL: int(event == 1 and period == duration),
            }
            _copy_optional_columns(record, row, cfg=cfg, covariate_cols=covariate_cols)
            if pd_column is not None:
                record[pd_column] = row[pd_column]
            rows.append(record)
            index.append(_curve_index(row_id, period))
    person_period = pd.DataFrame(rows)
    person_period.index = pd.Index(index, name="person_period_id")
    return _normalize_frame(person_period)


def _prediction_person_period(
    frame: DataFrame,
    *,
    model: DiscreteTimeHazardModel,
    periods: tuple[int, ...],
    pd: Any,
) -> DataFrame:
    rows: list[dict[str, Any]] = []
    index: list[str] = []
    pd_column = _pd_source_column(model.config_)
    prepared = _prepare_prediction_frame(frame, model=model, pd=pd)
    for row_index, row in prepared.iterrows():
        row_id = str(row_index)
        for period in periods:
            record: dict[str, Any] = {
                "row_id": row_id,
                _PERIOD_COL: period,
                _TIME_VALUE_COL: float(period),
            }
            _copy_optional_columns(
                record,
                row,
                cfg=model.config_,
                covariate_cols=model.covariate_cols_,
            )
            if pd_column is not None:
                record[pd_column] = row[pd_column]
            rows.append(record)
            index.append(_curve_index(row_id, period))
    person_period = pd.DataFrame(rows)
    person_period.index = pd.Index(index, name="person_period_id")
    return _normalize_frame(person_period)


def _prepare_prediction_frame(
    frame: DataFrame,
    *,
    model: DiscreteTimeHazardModel,
    pd: Any,
) -> DataFrame:
    _check_fitted(model)
    np = _import_numpy()
    copied = _as_dataframe(frame, pd)
    _validate_unique_index(copied)
    _validate_required_columns(
        copied,
        duration_col=None,
        event_col=None,
        covariate_cols=model.covariate_cols_,
        segment_col=model.config_.input.segment_col,
        id_col=model.config_.input.id_col,
    )
    prepared = _fill_prediction_features(copied, model=model)
    _validate_numeric_columns(prepared, columns=model.covariate_cols_, np=np)
    _validate_pd_role_columns(prepared, cfg=model.config_, np=np)
    _validate_optional_text_column(prepared, model.config_.input.segment_col)
    return prepared


def _fill_prediction_features(frame: DataFrame, *, model: DiscreteTimeHazardModel) -> DataFrame:
    columns = [*_pd_source_columns(model.config_)]
    if _PARTITION_COL in model.prediction_features_.columns and _PARTITION_COL not in frame.columns:
        columns.append(_PARTITION_COL)
    if not columns:
        return frame
    missing = [column for column in columns if column not in frame.columns]
    if not missing:
        return frame
    missing_index = [
        str(index) for index in frame.index if index not in model.prediction_features_.index
    ]
    if missing_index:
        raise SurvivalInputError(
            f"No hay features PD almacenadas para filas de predicción: {missing_index}."
        )
    prepared = frame.copy(deep=True)
    stored = model.prediction_features_.loc[frame.index, missing]
    for column in missing:
        prepared[column] = stored[column]
    return prepared


def _copy_optional_columns(
    record: dict[str, Any],
    row: Series,
    *,
    cfg: SurvivalConfig,
    covariate_cols: tuple[str, ...],
) -> None:
    if cfg.input.segment_col is not None:
        record["segment"] = str(row[cfg.input.segment_col])
    else:
        record["segment"] = None
    if _PARTITION_COL in row.index:
        record[_PARTITION_COL] = str(row[_PARTITION_COL])
    else:
        record[_PARTITION_COL] = None
    for column in covariate_cols:
        record[column] = row[column]


def _prediction_features(
    frame: DataFrame,
    *,
    cfg: SurvivalConfig,
    covariate_cols: tuple[str, ...],
) -> DataFrame:
    columns = [*_pd_source_columns(cfg), *covariate_cols]
    if cfg.input.segment_col is not None:
        columns.append(cfg.input.segment_col)
    if _PARTITION_COL in frame.columns:
        columns.append(_PARTITION_COL)
    unique_columns = tuple(dict.fromkeys(columns))
    return cast("DataFrame", frame.loc[:, unique_columns].copy(deep=True))


def _design_matrix_for_fit(
    person_period: DataFrame,
    *,
    cfg: SurvivalConfig,
    covariate_cols: tuple[str, ...],
    pd: Any,
) -> tuple[DataFrame, Series | None, tuple[int, ...], tuple[str, ...]]:
    period_values = tuple(int(value) for value in sorted(person_period[_PERIOD_COL].unique()))
    pd_segment_categories = _pd_segment_categories(person_period, cfg=cfg)
    exog, offset = _design_matrix(
        person_period,
        cfg=cfg,
        covariate_cols=covariate_cols,
        period_values=period_values,
        pd_segment_categories=pd_segment_categories,
        pd=pd,
    )
    return exog, offset, period_values, pd_segment_categories


def _design_matrix_for_prediction(
    person_period: DataFrame,
    *,
    model: DiscreteTimeHazardModel,
    pd: Any,
) -> tuple[DataFrame, Series | None]:
    return _design_matrix(
        person_period,
        cfg=model.config_,
        covariate_cols=model.covariate_cols_,
        period_values=model.period_values_,
        pd_segment_categories=model.pd_segment_categories_,
        pd=pd,
    )


def _design_matrix(
    person_period: DataFrame,
    *,
    cfg: SurvivalConfig,
    covariate_cols: tuple[str, ...],
    period_values: tuple[int, ...],
    pd_segment_categories: tuple[str, ...],
    pd: Any,
) -> tuple[DataFrame, Series | None]:
    exog = pd.DataFrame(index=person_period.index)
    if cfg.discrete_hazard.include_period_dummies:
        for period in period_values:
            exog[_period_column(period)] = (person_period[_PERIOD_COL] == period).astype("float64")
    else:
        exog[_INTERCEPT] = 1.0

    role = cfg.discrete_hazard.pd_role
    pd_column = _pd_source_column(cfg)
    offset = None
    if pd_column is not None and role == "offset":
        offset = person_period[pd_column].astype("float64")
    elif pd_column is not None and role == "covariate":
        exog[pd_column] = person_period[pd_column].astype("float64")
    elif pd_column is not None and role == "segment":
        _add_pd_segment_dummies(
            exog,
            person_period[pd_column],
            categories=pd_segment_categories,
        )

    for column in covariate_cols:
        exog[column] = person_period[column].astype("float64")
    _validate_design_matrix(exog)
    return cast("DataFrame", exog), cast("Series | None", offset)


def _add_pd_segment_dummies(
    exog: DataFrame,
    series: Series,
    *,
    categories: tuple[str, ...],
) -> None:
    values = tuple(str(value) for value in series.astype("string"))
    unknown = sorted({value for value in values if value not in categories})
    if unknown:
        raise SurvivalTransformError(f"Segmentos PD no observados durante fit: {unknown}.")
    for category in categories[1:]:
        exog[f"pd_segment[{category}]"] = [float(value == category) for value in values]


def _pd_segment_categories(person_period: DataFrame, *, cfg: SurvivalConfig) -> tuple[str, ...]:
    pd_column = _pd_source_column(cfg)
    if pd_column is None or cfg.discrete_hazard.pd_role != "segment":
        return ()
    return tuple(sorted({str(value) for value in person_period[pd_column].astype("string")}))


def _validate_design_matrix(exog: DataFrame) -> None:
    columns = tuple(str(column) for column in exog.columns)
    if len(set(columns)) != len(columns):
        raise SurvivalInputError(f"Columnas de diseño duplicadas en discrete hazard: {columns}.")
    if exog.shape[1] == 0:
        raise SurvivalFitError("Discrete hazard requiere al menos una columna de diseño.")


def _fit_glm(
    *,
    target: Series,
    exog: DataFrame,
    offset: Series | None,
    cfg: SurvivalConfig,
    np: Any,
) -> Any:
    components = _import_statsmodels_components()
    link = components.logit() if cfg.discrete_hazard.link == "logit" else components.cloglog()
    try:
        with _statsmodels_warnings_as_errors():
            model = components.glm(
                target.astype("int64"),
                exog,
                family=components.binomial(link=link),
                offset=offset,
            )
            result = model.fit(maxiter=100, disp=False)
    except (
        components.perfect_warning,
        components.convergence_warning,
        components.perfect_error,
        Warning,
    ) as exc:
        raise SurvivalFitError(
            "statsmodels reportó separación perfecta/cuasi-perfecta o no convergencia "
            "en discrete hazard; revise períodos, covariables o eventos."
        ) from exc
    except np.linalg.LinAlgError as exc:
        raise SurvivalFitError(
            "statsmodels no pudo invertir la matriz del discrete hazard; revise colinealidad."
        ) from exc
    except ValueError as exc:
        raise SurvivalFitError(f"statsmodels rechazó el ajuste discrete hazard: {exc}") from exc
    if not _converged(result):
        raise SurvivalFitError("statsmodels no convergió al ajustar discrete hazard.")
    return result


@contextmanager
def _statsmodels_warnings_as_errors() -> Iterator[None]:
    """Convierte localmente warnings de statsmodels en errores propios."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        yield


def _predict_points(
    model: DiscreteTimeHazardModel,
    frame: DataFrame,
    times: Sequence[int | float],
    *,
    pd: Any,
) -> tuple[tuple[_PredictionPoint, ...], str | None]:
    _check_fitted(model)
    periods, fallback_warning = _resolve_times(model, times)
    person_period = _prediction_person_period(frame, model=model, periods=periods, pd=pd)
    exog, offset = _design_matrix_for_prediction(person_period, model=model, pd=pd)
    linear_predictor = _linear_predictor(exog, model.params_, offset=offset)
    hazards = _inverse_link(linear_predictor, link=model.config_.discrete_hazard.link)
    points = tuple(
        _PredictionPoint(
            row_id=str(row.row_id),
            segment=None if row.segment is None else str(row.segment),
            partition=None if row.partition is None else str(row.partition),
            period=int(cast("Any", row.period)),
            time_value=_clean_float(float(cast("Any", row.time_value))),
            hazard=_unit_float(float(hazard), field_name="hazard"),
            linear_predictor=_clean_float(float(eta)),
        )
        for row, hazard, eta in zip(
            person_period.itertuples(index=False),
            hazards,
            linear_predictor,
            strict=True,
        )
    )
    return points, fallback_warning


def _linear_predictor(
    exog: DataFrame,
    params: Series,
    *,
    offset: Series | None,
) -> tuple[float, ...]:
    values = exog.dot(params).astype("float64")
    if offset is not None:
        values = values + offset.astype("float64")
    return tuple(_clean_float(float(value)) for value in values.to_numpy(dtype="float64"))


def _inverse_link(values: Sequence[float], *, link: str) -> tuple[float, ...]:
    if link == "logit":
        return tuple(_inverse_logit(value) for value in values)
    return tuple(_inverse_cloglog(value) for value in values)


def _inverse_logit(value: float) -> float:
    if value >= 0.0:
        denominator = 1.0 + math.exp(-value)
        return _clean_float(1.0 / denominator)
    exp_value = math.exp(value)
    return _clean_float(exp_value / (1.0 + exp_value))


def _inverse_cloglog(value: float) -> float:
    if value > 36.0:
        return 1.0
    if value < -745.0:
        return 0.0
    return _clean_float(-math.expm1(-math.exp(value)))


def _survival_rows(
    points: tuple[_PredictionPoint, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    index: list[str] = []
    for group in _points_by_row(points):
        survival, _pd_marginal, _pd_cumulative = _hazard_chain(
            tuple(point.hazard for point in group)
        )
        for point, survival_value in zip(group, survival, strict=True):
            rows.append(
                {
                    "row_id": point.row_id,
                    "segment": point.segment,
                    "period": point.period,
                    "time_value": point.time_value,
                    "survival": survival_value,
                }
            )
            index.append(_curve_index(point.row_id, point.period))
    return rows, index


def _term_structure_rows(
    model: DiscreteTimeHazardModel,
    points: tuple[_PredictionPoint, ...],
    fallback_warning: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    index: list[str] = []
    warning_codes = tuple(
        dict.fromkeys(
            (
                *model.warning_codes_,
                *((fallback_warning,) if fallback_warning is not None else ()),
            )
        )
    )
    for group in _points_by_row(points):
        survival, pd_marginal, pd_cumulative = _hazard_chain(tuple(point.hazard for point in group))
        for point, survival_value, marginal_value, cumulative_value in zip(
            group,
            survival,
            pd_marginal,
            pd_cumulative,
            strict=True,
        ):
            rows.append(
                {
                    "row_id": point.row_id,
                    "segment": point.segment,
                    "partition": point.partition,
                    "period": point.period,
                    "time_value": point.time_value,
                    "hazard": point.hazard,
                    "survival": survival_value,
                    "pd_marginal": marginal_value,
                    "pd_cumulative": cumulative_value,
                    "method": _METHOD,
                    "pd_source": model.config_.input.pd_source,
                    "scenario": _SCENARIO,
                    "warning_codes": warning_codes,
                }
            )
            index.append(_curve_index(point.row_id, point.period))
    return rows, index


def _points_by_row(
    points: tuple[_PredictionPoint, ...],
) -> tuple[tuple[_PredictionPoint, ...], ...]:
    groups: list[tuple[_PredictionPoint, ...]] = []
    current: list[_PredictionPoint] = []
    current_key: str | None = None
    for point in points:
        if current_key is None or point.row_id == current_key:
            current.append(point)
            current_key = point.row_id
        else:
            groups.append(tuple(current))
            current = [point]
            current_key = point.row_id
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _hazard_chain(
    hazards: Sequence[float],
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """Convierte hazards en ``S(t)``, ``PD_marginal(t)`` y ``PD_acumulada(t)``."""
    survival_values: list[float] = []
    marginal_values: list[float] = []
    cumulative_values: list[float] = []
    previous_survival = 1.0
    for hazard in hazards:
        clean_hazard = _unit_float(float(hazard), field_name="hazard")
        marginal = _non_negative_float(previous_survival * clean_hazard, field_name="pd_marginal")
        survival = _unit_float(previous_survival * (1.0 - clean_hazard), field_name="survival")
        cumulative = _unit_float(1.0 - survival, field_name="pd_cumulative")
        survival_values.append(survival)
        marginal_values.append(marginal)
        cumulative_values.append(cumulative)
        previous_survival = survival
    return tuple(survival_values), tuple(marginal_values), tuple(cumulative_values)


def _resolve_times(
    model: DiscreteTimeHazardModel,
    times: Sequence[int | float],
) -> tuple[tuple[int, ...], str | None]:
    cfg = model.config_
    values = tuple(times)
    fallback_warning: str | None = None
    if not values:
        if cfg.time_grid.evaluation_times:
            values = cfg.time_grid.evaluation_times
        elif cfg.time_grid.horizon_periods is not None:
            values = tuple(range(1, cfg.time_grid.horizon_periods + 1))
        else:
            values = model.period_values_
            fallback_warning = _NO_TIME_GRID_WARNING
    periods = _validate_times(values)
    max_period = max(periods)
    extrapolation_blocked = (
        not _extrapolation_declared(cfg, max_period) or cfg.discrete_hazard.include_period_dummies
    )
    if max_period > model.max_observed_period_ and extrapolation_blocked:
        raise SurvivalTransformError(
            "Discrete hazard no extrapola fuera del soporte observado sin una config "
            "compatible: "
            f"period={max_period}, max_observed_period={model.max_observed_period_}."
        )
    return periods, fallback_warning


def _extrapolation_declared(cfg: SurvivalConfig, max_period: int) -> bool:
    if cfg.time_grid.horizon_periods is not None and max_period <= cfg.time_grid.horizon_periods:
        return True
    return bool(cfg.time_grid.evaluation_times) and max_period <= max(
        cfg.time_grid.evaluation_times
    )


def _validate_times(values: Sequence[int | float]) -> tuple[int, ...]:
    normalized: list[int] = []
    for position, value in enumerate(values):
        if isinstance(value, bool):
            raise SurvivalTransformError(
                f"times contiene un valor booleano en posición {position}: {value!r}."
            )
        candidate = float(value)
        if not math.isfinite(candidate) or candidate <= 0.0 or not candidate.is_integer():
            raise SurvivalTransformError(
                "times debe contener períodos enteros positivos y finitos; "
                f"posición={position}, valor={value!r}."
            )
        normalized.append(int(candidate))
    ordered = tuple(sorted(normalized))
    if len(set(ordered)) != len(ordered):
        raise SurvivalTransformError(f"times contiene períodos duplicados: {values!r}.")
    return ordered


def _check_min_events(events_by_period: Mapping[int, int], cfg: SurvivalConfig) -> None:
    minimum = cfg.discrete_hazard.min_events_per_period
    if minimum is None:
        return
    invalid = {period: count for period, count in events_by_period.items() if count < minimum}
    if invalid:
        raise SurvivalFitError(
            "Eventos insuficientes por período para discrete hazard: "
            f"mínimo={minimum}, observados={invalid}."
        )


def _events_by_period(person_period: DataFrame) -> dict[int, int]:
    grouped = person_period.groupby(_PERIOD_COL, sort=True)[_TARGET_COL].sum()
    return {int(cast("Any", period)): int(cast("Any", count)) for period, count in grouped.items()}


def _validate_required_columns(
    frame: DataFrame,
    *,
    duration_col: str | None,
    event_col: str | None,
    covariate_cols: tuple[str, ...],
    segment_col: str | None,
    id_col: str | None,
) -> None:
    required = [*covariate_cols]
    if duration_col is not None:
        required.append(duration_col)
    if event_col is not None:
        required.append(event_col)
    if segment_col is not None:
        required.append(segment_col)
    if id_col is not None:
        required.append(id_col)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise SurvivalInputError(f"Faltan columnas requeridas para discrete hazard: {missing}.")


def _validate_unique_index(frame: DataFrame) -> None:
    if not frame.index.is_unique:
        duplicated = [str(value) for value in frame.index[frame.index.duplicated()].unique()]
        raise SurvivalInputError(f"El índice de survival debe ser único; duplicados={duplicated}.")


def _duration_period_array(series: Series, *, column: str, np: Any) -> NDArrayInt:
    if _is_bool_dtype(series):
        raise SurvivalInputError(f"La duración no puede ser booleana: columna='{column}'.")
    if not _is_numeric_dtype(series):
        raise SurvivalInputError(f"La duración debe ser numérica: columna='{column}'.")
    values = series.to_numpy(dtype="float64", na_value=np.nan)
    invalid_mask = ~np.isfinite(values) | (values <= 0.0) | (np.floor(values) != values)
    if bool(invalid_mask.any()):
        invalid = _invalid_values(series, invalid_mask)
        raise SurvivalInputError(
            "Duración inválida para discrete hazard; debe ser entera positiva y finita: "
            f"columna='{column}', valores={invalid}."
        )
    return cast("NDArrayInt", values.astype("int64"))


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


def _validate_numeric_columns(frame: DataFrame, *, columns: tuple[str, ...], np: Any) -> None:
    for column in columns:
        _numeric_values(frame[column], column=column, np=np)


def _validate_pd_role_columns(frame: DataFrame, *, cfg: SurvivalConfig, np: Any) -> None:
    pd_column = _pd_source_column(cfg)
    if pd_column is None:
        return
    if pd_column not in frame.columns:
        raise SurvivalInputError(f"Falta columna PD requerida para discrete hazard: {pd_column!r}.")
    if cfg.discrete_hazard.pd_role == "segment":
        _validate_optional_text_column(frame, pd_column)
    else:
        _numeric_values(frame[pd_column], column=pd_column, np=np)


def _numeric_values(series: Series, *, column: str, np: Any) -> NDArrayFloat:
    if _is_bool_dtype(series):
        raise SurvivalInputError(f"La covariable no puede ser booleana: columna='{column}'.")
    if not _is_numeric_dtype(series):
        raise SurvivalInputError(f"La covariable debe ser numérica: columna='{column}'.")
    values = series.to_numpy(dtype="float64", na_value=np.nan)
    invalid_mask = ~np.isfinite(values)
    if bool(invalid_mask.any()):
        invalid = _invalid_values(series, invalid_mask)
        raise SurvivalInputError(
            f"Valores missing/no finitos en columna='{column}'; supervivencia no imputa: {invalid}."
        )
    return cast("NDArrayFloat", values)


def _validate_optional_text_column(frame: DataFrame, column: str | None) -> None:
    if column is None:
        return
    if bool(frame[column].isna().any()):
        raise SurvivalInputError(f"La columna '{column}' no puede contener valores missing.")


def _invalid_values(series: Series, mask: Any) -> dict[str, Any]:
    invalid = series.loc[mask]
    return {str(index): value for index, value in invalid.to_dict().items()}


def _is_numeric_dtype(series: Series) -> bool:
    pd = _import_pandas()
    return bool(pd.api.types.is_numeric_dtype(series.dtype))


def _is_bool_dtype(series: Series) -> bool:
    pd = _import_pandas()
    return bool(pd.api.types.is_bool_dtype(series.dtype))


def _as_dataframe(value: object, pd: Any) -> DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise SurvivalInputError("DiscreteTimeHazardModel requiere un pandas.DataFrame.")
    return cast("DataFrame", value.copy(deep=True))


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


def _series_from_result(value: Any, columns: tuple[str, ...], pd: Any) -> Series:
    if hasattr(value, "index") and not callable(value.index):
        series = pd.Series(value, index=value.index, dtype="float64")
    else:
        series = pd.Series(value, index=columns, dtype="float64")
    return cast("Series", series.reindex(columns).astype("float64"))


def _fit_statistics(result: Any) -> dict[str, Any]:
    return {
        "n_obs": getattr(result, "nobs", None),
        "df_model": getattr(result, "df_model", None),
        "df_resid": getattr(result, "df_resid", None),
        "llf": getattr(result, "llf", None),
        "aic": getattr(result, "aic", None),
        "deviance": getattr(result, "deviance", None),
        "converged": _converged(result),
        "n_iterations": _n_iterations(result),
    }


def _converged(result: Any) -> bool:
    mle_retvals = getattr(result, "mle_retvals", None)
    if isinstance(mle_retvals, dict) and "converged" in mle_retvals:
        return bool(mle_retvals["converged"])
    if hasattr(result, "converged"):
        return bool(result.converged)
    return True


def _n_iterations(result: Any) -> int | None:
    fit_history = getattr(result, "fit_history", None)
    if isinstance(fit_history, dict):
        value = fit_history.get("iteration")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    mle_retvals = getattr(result, "mle_retvals", None)
    if isinstance(mle_retvals, dict):
        for key in ("iterations", "nit"):
            value = mle_retvals.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _dependency_versions() -> dict[str, str]:
    return {
        "pandas": version("pandas"),
        "numpy": version("numpy"),
        "statsmodels": version("statsmodels"),
    }


def _check_fitted(model: DiscreteTimeHazardModel) -> None:
    if not hasattr(model, "result_"):
        raise NotFittedError(
            "DiscreteTimeHazardModel no está fiteado; llame fit(...) antes de predecir."
        )


def _period_column(period: int) -> str:
    return f"period_{period}"


def _curve_index(row_id: str, period: int) -> str:
    return f"{row_id}|{period}"


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


def _import_statsmodels_components() -> _StatsmodelsComponents:
    """Importa statsmodels localmente y traduce su ausencia al extra correcto."""
    try:
        glm_module = importlib.import_module("statsmodels.genmod.generalized_linear_model")
        families = importlib.import_module("statsmodels.genmod.families")
        exceptions = importlib.import_module("statsmodels.tools.sm_exceptions")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return _StatsmodelsComponents(
        glm=glm_module.GLM,
        binomial=families.Binomial,
        logit=families.links.Logit,
        cloglog=families.links.CLogLog,
        perfect_warning=exceptions.PerfectSeparationWarning,
        convergence_warning=exceptions.ConvergenceWarning,
        perfect_error=exceptions.PerfectSeparationError,
    )


def _import_pandas() -> Any:
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("DiscreteTimeHazardModel requiere pandas.") from exc


def _import_numpy() -> Any:
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("DiscreteTimeHazardModel requiere numpy.") from exc
