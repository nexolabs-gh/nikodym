"""Wrappers Cox PH y AFT para lifetime PD con lifelines (SDD-18 §3/§7).

``CoxPHSurvivalModel`` ajusta un Cox proportional hazards y publica el diagnóstico
Schoenfeld cuando la configuración lo habilita. ``AFTSurvivalModel`` ajusta una familia AFT
paramétrica explícita. Ambos modelos derivan hazards de intervalo desde las curvas ``S(t)`` para
mantener la identidad ``PD_marginal(t) = S(t-1) * h(t)`` usada aguas abajo por IFRS 9.

El módulo preserva el import liviano de ``nikodym.survival``: ``pandas``, ``numpy`` y
``lifelines`` se cargan sólo dentro de ``fit``/predicción y helpers de ejecución. Se evita
deliberadamente ``scikit-survival`` por licencia GPL-3.0.

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
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    NDArrayInt: TypeAlias = np.ndarray[Any, np.dtype[np.int64]]
    Series: TypeAlias = pd.Series[Any]
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any
    NDArrayInt: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["AFTSurvivalModel", "CoxPHSurvivalModel"]

_COX_METHOD: Literal["cox_ph"] = "cox_ph"
_AFT_METHOD: Literal["aft"] = "aft"
_SURVIVAL_EXTRA_MESSAGE = "instale nikodym[survival]"
_NO_TIME_GRID_WARNING = "FALTA-DATO-SUR-1"
_NO_PH_THRESHOLD_WARNING = "D-SUR-7"
_PARTITION_COL = "partition"
_PARTITION_DESARROLLO = "desarrollo"
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
class _LifelinesComponents:
    cox_ph_fitter: Any
    weibull_aft_fitter: Any
    lognormal_aft_fitter: Any
    loglogistic_aft_fitter: Any
    proportional_hazard_test: Any


@dataclass(frozen=True)
class _PredictionPoint:
    row_id: str
    segment: str | None
    partition: str | None
    period: int
    time_value: float
    survival: float
    hazard: float
    linear_predictor: float | None


class CoxPHSurvivalModel(AuditableMixin):
    """Ajusta Cox proportional hazards y publica diagnóstico Schoenfeld."""

    config_cls: ClassVar[type[SurvivalConfig]] = SurvivalConfig
    config_: SurvivalConfig
    duration_col_: str
    event_col_: str
    covariate_cols_: tuple[str, ...]
    fitter_: Any
    max_observed_time_: float
    observed_times_: tuple[float, ...]
    n_rows_: int
    n_fit_rows_: int
    n_events_: int
    n_censored_: int
    warning_codes_: tuple[str, ...]
    schoenfeld_test_: dict[str, Any] | None
    prediction_features_: DataFrame
    fit_statistics_: dict[str, Any]
    dependency_versions_: dict[str, str]
    diagnostics_: SurvivalDiagnostics
    card_: SurvivalCard

    def __init__(self, *, config: SurvivalConfig | Mapping[str, Any] | None = None) -> None:
        """Asigna la configuración survival sin importar lifelines."""
        if config is None or isinstance(config, SurvivalConfig):
            self.config = config
        else:
            self.config = SurvivalConfig.model_validate(config)

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig | Mapping[str, Any]) -> CoxPHSurvivalModel:
        """Construye el estimador desde ``SurvivalConfig`` y exige ``method='cox_ph'``."""
        if not isinstance(cfg, SurvivalConfig):
            cfg = SurvivalConfig.model_validate(cfg)
        if cfg.method != _COX_METHOD:
            raise SurvivalConfigError("CoxPHSurvivalModel.from_config exige method='cox_ph'.")
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
        """Ajusta Cox PH con lifelines sobre Desarrollo si existe ``partition``."""
        _fit_lifelines_model(
            self,
            frame,
            duration_col=duration_col,
            event_col=event_col,
            covariate_cols=covariate_cols,
            pd_frame=pd_frame,
            audit=audit,
            method=_COX_METHOD,
        )
        return self

    def predict_survival(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Predice curvas ``S(t)`` individuales con el Cox fiteado."""
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
        """Predice hazards de intervalo derivados de ``S(t)`` para Cox PH."""
        pd = _import_pandas()
        points, _fallback_warning = _predict_points(self, frame, times, pd=pd)
        rows, index = _hazard_rows(points, link=_COX_METHOD)
        return _records_to_frame(rows, columns=_HAZARD_COLUMNS, index=index, pd=pd)

    def term_structure(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Publica lifetime PD tidy individual: hazard, supervivencia y PD acumulada."""
        pd = _import_pandas()
        points, fallback_warning = _predict_points(self, frame, times, pd=pd)
        rows, index = _term_structure_rows(
            self,
            points,
            fallback_warning,
            method=_COX_METHOD,
        )
        return _records_to_frame(rows, columns=_TERM_STRUCTURE_COLUMNS, index=index, pd=pd)

    def proportional_hazard_diagnostics(self) -> dict[str, Any]:
        """Retorna una copia del test Schoenfeld publicado por el ajuste Cox."""
        _check_fitted(self, class_name="CoxPHSurvivalModel")
        return dict(self.schoenfeld_test_ or {})


class AFTSurvivalModel(AuditableMixin):
    """Ajusta modelos AFT paramétricos de lifelines con familia explícita."""

    config_cls: ClassVar[type[SurvivalConfig]] = SurvivalConfig
    config_: SurvivalConfig
    duration_col_: str
    event_col_: str
    covariate_cols_: tuple[str, ...]
    fitter_: Any
    max_observed_time_: float
    observed_times_: tuple[float, ...]
    n_rows_: int
    n_fit_rows_: int
    n_events_: int
    n_censored_: int
    warning_codes_: tuple[str, ...]
    schoenfeld_test_: dict[str, Any] | None
    prediction_features_: DataFrame
    fit_statistics_: dict[str, Any]
    dependency_versions_: dict[str, str]
    diagnostics_: SurvivalDiagnostics
    card_: SurvivalCard

    def __init__(self, *, config: SurvivalConfig | Mapping[str, Any] | None = None) -> None:
        """Asigna la configuración survival sin importar lifelines."""
        if config is None or isinstance(config, SurvivalConfig):
            self.config = config
        else:
            self.config = SurvivalConfig.model_validate(config)

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig | Mapping[str, Any]) -> AFTSurvivalModel:
        """Construye el estimador desde ``SurvivalConfig`` y exige ``method='aft'``."""
        if not isinstance(cfg, SurvivalConfig):
            cfg = SurvivalConfig.model_validate(cfg)
        if cfg.method != _AFT_METHOD:
            raise SurvivalConfigError("AFTSurvivalModel.from_config exige method='aft'.")
        if cfg.cox_aft.aft_family is None:
            raise SurvivalConfigError("AFTSurvivalModel exige cox_aft.aft_family.")
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
        """Ajusta la familia AFT configurada con lifelines."""
        _fit_lifelines_model(
            self,
            frame,
            duration_col=duration_col,
            event_col=event_col,
            covariate_cols=covariate_cols,
            pd_frame=pd_frame,
            audit=audit,
            method=_AFT_METHOD,
        )
        return self

    def predict_survival(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Predice curvas ``S(t)`` individuales con el AFT fiteado."""
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
        """Predice hazards de intervalo derivados de ``S(t)`` para AFT."""
        pd = _import_pandas()
        points, _fallback_warning = _predict_points(self, frame, times, pd=pd)
        rows, index = _hazard_rows(points, link=self.config_.cox_aft.aft_family)
        return _records_to_frame(rows, columns=_HAZARD_COLUMNS, index=index, pd=pd)

    def term_structure(
        self,
        frame: DataFrame,
        *,
        times: Sequence[int | float],
    ) -> DataFrame:
        """Publica lifetime PD tidy individual: hazard, supervivencia y PD acumulada."""
        pd = _import_pandas()
        points, fallback_warning = _predict_points(self, frame, times, pd=pd)
        rows, index = _term_structure_rows(
            self,
            points,
            fallback_warning,
            method=_AFT_METHOD,
        )
        return _records_to_frame(rows, columns=_TERM_STRUCTURE_COLUMNS, index=index, pd=pd)


def _fit_lifelines_model(
    model: CoxPHSurvivalModel | AFTSurvivalModel,
    frame: DataFrame,
    *,
    duration_col: str,
    event_col: str,
    covariate_cols: tuple[str, ...],
    pd_frame: DataFrame | None,
    audit: AuditSink | None,
    method: Literal["cox_ph", "aft"],
) -> None:
    cfg = _effective_config(
        model.config,
        method=method,
        duration_col=duration_col,
        event_col=event_col,
    )
    pd = _import_pandas()
    np = _import_numpy()
    components = _import_lifelines_components()
    if audit is not None:
        model._audit = audit

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
    durations = _duration_array(prepared[duration_col], column=duration_col, np=np)
    events = _event_array(prepared[event_col], column=event_col, np=np)
    fit_mask = _fit_mask(prepared, np=np)
    fit_frame = prepared.loc[fit_mask].copy(deep=True)
    fit_events = cast("NDArrayInt", events[fit_mask])
    if fit_frame.empty:
        raise SurvivalFitError("No hay filas de Desarrollo para ajustar survival lifelines.")
    if int(fit_events.sum()) == 0:
        raise SurvivalFitError("Cox/AFT exige al menos un evento observado.")
    if method == _COX_METHOD and not covariates:
        raise SurvivalConfigError("CoxPHSurvivalModel requiere al menos una covariable numérica.")

    fitter = _new_fitter(components, cfg, method=method)
    lifelines_frame = _lifelines_fit_frame(
        fit_frame,
        duration_col=duration_col,
        event_col=event_col,
        covariate_cols=covariates,
    )
    try:
        with _lifelines_warnings_as_errors():
            fitter.fit(lifelines_frame, duration_col=duration_col, event_col=event_col)
    except Warning as exc:
        raise SurvivalFitError("lifelines emitió un warning durante el ajuste Cox/AFT.") from exc
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise SurvivalFitError(f"lifelines rechazó el ajuste Cox/AFT: {exc}") from exc

    schoenfeld_test = None
    warning_codes: tuple[str, ...] = ()
    if method == _COX_METHOD and cfg.cox_aft.ph_test_enabled:
        schoenfeld_test = _schoenfeld_test(
            fitter,
            lifelines_frame,
            cfg=cfg,
            components=components,
        )
        if cfg.cox_aft.ph_p_value_threshold is None:
            warnings.warn(
                "D-SUR-7: ph_p_value_threshold no está configurado; "
                "el test Schoenfeld queda como diagnóstico no bloqueante.",
                UserWarning,
                stacklevel=2,
            )
            warning_codes = (_NO_PH_THRESHOLD_WARNING,)

    _store_fit_state(
        model,
        cfg=cfg,
        fitter=fitter,
        duration_col=duration_col,
        event_col=event_col,
        covariates=covariates,
        prepared=prepared,
        durations=durations,
        events=events,
        fit_frame=fit_frame,
        warning_codes=warning_codes,
        schoenfeld_test=schoenfeld_test,
        method=method,
    )
    _log_fit_decisions(model, method=method)


def _effective_config(
    config: SurvivalConfig | None,
    *,
    method: Literal["cox_ph", "aft"],
    duration_col: str,
    event_col: str,
) -> SurvivalConfig:
    if config is not None:
        if config.method != method:
            raise SurvivalConfigError(f"El modelo lifelines exige method='{method}'.")
        if method == _AFT_METHOD and config.cox_aft.aft_family is None:
            raise SurvivalConfigError("method='aft' exige cox_aft.aft_family.")
        return config
    if method == _AFT_METHOD:
        raise SurvivalConfigError("AFTSurvivalModel exige cox_aft.aft_family.")
    return SurvivalConfig(
        method=method,
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
    copied = _as_dataframe(frame, pd, class_name="Cox/AFT")
    _validate_unique_index(copied)
    _validate_required_columns(
        copied,
        duration_col=duration_col,
        event_col=event_col,
        covariate_cols=(),
        segment_col=cfg.input.segment_col,
        id_col=cfg.input.id_col,
    )
    prepared = _merge_prediction_columns(
        copied,
        pd_frame=pd_frame,
        covariate_cols=covariate_cols,
        pd=pd,
    )
    _validate_required_columns(
        prepared,
        duration_col=duration_col,
        event_col=event_col,
        covariate_cols=covariate_cols,
        segment_col=cfg.input.segment_col,
        id_col=cfg.input.id_col,
    )
    _validate_numeric_columns(prepared, columns=covariate_cols, np=np)
    _validate_optional_text_column(prepared, cfg.input.segment_col)
    _validate_optional_text_column(prepared, cfg.input.id_col)
    partition_col = _PARTITION_COL if _PARTITION_COL in prepared.columns else None
    _validate_optional_text_column(prepared, partition_col)
    return prepared


def _merge_prediction_columns(
    frame: DataFrame,
    *,
    pd_frame: DataFrame | None,
    covariate_cols: tuple[str, ...],
    pd: Any,
) -> DataFrame:
    source_columns = [column for column in covariate_cols if column not in frame.columns]
    if _PARTITION_COL not in frame.columns and pd_frame is not None:
        source_columns.append(_PARTITION_COL)
    source_columns = list(dict.fromkeys(source_columns))
    if not source_columns:
        return frame
    if pd_frame is None:
        return frame
    source = _as_dataframe(pd_frame, pd, class_name="pd_frame")
    _validate_unique_index(source)
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


def _combined_covariates(
    configured: tuple[str, ...],
    explicit: tuple[str, ...],
) -> tuple[str, ...]:
    observed: dict[str, None] = {}
    for column in (*configured, *explicit):
        observed.setdefault(column, None)
    return tuple(observed)


def _fit_mask(frame: DataFrame, *, np: Any) -> NDArrayInt:
    if _PARTITION_COL not in frame.columns:
        return cast("NDArrayInt", np.ones(len(frame.index), dtype=bool))
    values = frame[_PARTITION_COL].astype("string")
    mask = (values == _PARTITION_DESARROLLO).to_numpy(dtype=bool, na_value=False)
    if bool(mask.any()):
        return cast("NDArrayInt", mask)
    return cast("NDArrayInt", np.ones(len(frame.index), dtype=bool))


def _lifelines_fit_frame(
    frame: DataFrame,
    *,
    duration_col: str,
    event_col: str,
    covariate_cols: tuple[str, ...],
) -> DataFrame:
    columns = (duration_col, event_col, *covariate_cols)
    return cast("DataFrame", frame.loc[:, columns].copy(deep=True))


def _new_fitter(
    components: _LifelinesComponents,
    cfg: SurvivalConfig,
    *,
    method: Literal["cox_ph", "aft"],
) -> Any:
    if method == _COX_METHOD:
        return components.cox_ph_fitter()
    family = cfg.cox_aft.aft_family
    if family == "weibull":
        return components.weibull_aft_fitter()
    if family == "lognormal":
        return components.lognormal_aft_fitter()
    if family == "loglogistic":
        return components.loglogistic_aft_fitter()
    raise SurvivalConfigError("method='aft' exige cox_aft.aft_family.")


def _schoenfeld_test(
    fitter: Any,
    fit_frame: DataFrame,
    *,
    cfg: SurvivalConfig,
    components: _LifelinesComponents,
) -> dict[str, Any]:
    try:
        with _lifelines_warnings_as_errors():
            result = components.proportional_hazard_test(
                fitter,
                fit_frame,
                time_transform="rank",
            )
    except Warning as exc:
        raise SurvivalFitError("lifelines emitió un warning en el test Schoenfeld.") from exc
    summary = result.summary
    by_covariate: dict[str, dict[str, float]] = {}
    for covariate, row in summary.iterrows():
        by_covariate[str(covariate)] = {
            "test_statistic": _clean_float(float(row["test_statistic"])),
            "p": _clean_float(float(row["p"])),
            "minus_log2_p": _clean_float(float(row["-log2(p)"])),
        }
    threshold = cfg.cox_aft.ph_p_value_threshold
    violations = tuple(
        covariate
        for covariate, values in by_covariate.items()
        if threshold is not None and values["p"] < threshold
    )
    min_p = min((values["p"] for values in by_covariate.values()), default=None)
    return {
        "time_transform": "rank",
        "ph_p_value_threshold": threshold,
        "min_p": min_p,
        "violations": violations,
        "by_covariate": by_covariate,
    }


@contextmanager
def _lifelines_warnings_as_errors() -> Iterator[None]:
    """Convierte warnings de lifelines en errores propios bajo control local."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        yield


def _store_fit_state(
    model: CoxPHSurvivalModel | AFTSurvivalModel,
    *,
    cfg: SurvivalConfig,
    fitter: Any,
    duration_col: str,
    event_col: str,
    covariates: tuple[str, ...],
    prepared: DataFrame,
    durations: NDArrayFloat,
    events: NDArrayInt,
    fit_frame: DataFrame,
    warning_codes: tuple[str, ...],
    schoenfeld_test: dict[str, Any] | None,
    method: Literal["cox_ph", "aft"],
) -> None:
    model.config_ = cfg
    model.duration_col_ = duration_col
    model.event_col_ = event_col
    model.covariate_cols_ = covariates
    model.fitter_ = fitter
    model.max_observed_time_ = _clean_float(float(max(durations)))
    model.observed_times_ = tuple(sorted({_clean_float(float(value)) for value in durations}))
    model.n_rows_ = len(prepared.index)
    model.n_fit_rows_ = len(fit_frame.index)
    model.n_events_ = int(events.sum())
    model.n_censored_ = int(model.n_rows_ - model.n_events_)
    model.warning_codes_ = warning_codes
    model.schoenfeld_test_ = schoenfeld_test
    model.prediction_features_ = _prediction_features(
        prepared,
        cfg=cfg,
        covariate_cols=covariates,
    )
    model.fit_statistics_ = _fit_statistics(fitter, method=method)
    model.dependency_versions_ = _dependency_versions()
    model.diagnostics_ = SurvivalDiagnostics(
        method=method,
        n_rows=model.n_rows_,
        n_events=model.n_events_,
        n_censored=model.n_censored_,
        max_observed_time=model.max_observed_time_,
        schoenfeld_test=schoenfeld_test,
        aft_family=cfg.cox_aft.aft_family if method == _AFT_METHOD else None,
        fit_statistics=model.fit_statistics_,
        warnings=warning_codes,
    )
    model.card_ = SurvivalCard(
        method=method,
        pd_source=cfg.input.pd_source,
        duration_col=duration_col,
        event_col=event_col,
        time_unit=cfg.time_grid.time_unit,
        n_rows=model.n_rows_,
        n_events=model.n_events_,
        n_periods=len(model.observed_times_),
        output_columns=_TERM_STRUCTURE_COLUMNS,
        diagnostics=model.diagnostics_,
        dependency_versions=model.dependency_versions_,
        falta_dato=(),
        metric_sections={
            "schoenfeld": schoenfeld_test or {},
            "term_structure_summary": {"observed_times": model.observed_times_},
        },
    )


def _prediction_features(
    frame: DataFrame,
    *,
    cfg: SurvivalConfig,
    covariate_cols: tuple[str, ...],
) -> DataFrame:
    columns = [*covariate_cols]
    if cfg.input.segment_col is not None:
        columns.append(cfg.input.segment_col)
    if _PARTITION_COL in frame.columns:
        columns.append(_PARTITION_COL)
    unique_columns = tuple(dict.fromkeys(columns))
    return cast("DataFrame", frame.loc[:, unique_columns].copy(deep=True))


def _log_fit_decisions(
    model: CoxPHSurvivalModel | AFTSurvivalModel,
    *,
    method: Literal["cox_ph", "aft"],
) -> None:
    model.log_decision(
        regla="survival_method",
        umbral={"method": method, "aft_family": model.config_.cox_aft.aft_family},
        valor={
            "pd_source": model.config_.input.pd_source,
            "duration_col": model.duration_col_,
            "event_col": model.event_col_,
            "covariate_cols": model.covariate_cols_,
        },
        accion=f"fit_{method}",
    )
    model.log_decision(
        regla="survival_input_quality",
        umbral={"partition_col": _PARTITION_COL},
        valor={
            "n_rows": model.n_rows_,
            "n_fit_rows": model.n_fit_rows_,
            "n_events": model.n_events_,
            "n_censored": model.n_censored_,
        },
        accion="validar_input_survival",
    )
    if method == _COX_METHOD:
        model.log_decision(
            regla="survival_schoenfeld",
            umbral={"ph_p_value_threshold": model.config_.cox_aft.ph_p_value_threshold},
            valor=model.schoenfeld_test_,
            accion="publicar_diagnostico_ph",
        )
    else:
        model.log_decision(
            regla="survival_aft",
            umbral={"aft_family": model.config_.cox_aft.aft_family},
            valor=model.fit_statistics_,
            accion="publicar_diagnostico_aft",
        )


def _predict_points(
    model: CoxPHSurvivalModel | AFTSurvivalModel,
    frame: DataFrame,
    times: Sequence[int | float],
    *,
    pd: Any,
) -> tuple[tuple[_PredictionPoint, ...], str | None]:
    _check_fitted(model, class_name=type(model).__name__)
    prepared = _prepare_prediction_frame(frame, model=model, pd=pd)
    resolved_times, fallback_warning = _resolve_times(model, times)
    survival_frame = _predict_survival_frame(model, prepared, resolved_times)
    linear_predictors = _linear_predictors(model, prepared)

    points: list[_PredictionPoint] = []
    for row_position, (row_index, row) in enumerate(prepared.iterrows()):
        previous_survival = 1.0
        for period, time_value in enumerate(resolved_times, start=1):
            survival_value = cast("Any", survival_frame.iloc[period - 1, row_position])
            survival = _unit_float(float(survival_value), field_name="survival")
            hazard = _interval_hazard(previous_survival=previous_survival, survival=survival)
            points.append(
                _PredictionPoint(
                    row_id=str(row_index),
                    segment=_row_text(row, model.config_.input.segment_col),
                    partition=_row_text(
                        row,
                        _PARTITION_COL if _PARTITION_COL in row.index else None,
                    ),
                    period=period,
                    time_value=time_value,
                    survival=survival,
                    hazard=hazard,
                    linear_predictor=linear_predictors[row_position],
                )
            )
            previous_survival = survival
    return tuple(points), fallback_warning


def _prepare_prediction_frame(
    frame: DataFrame,
    *,
    model: CoxPHSurvivalModel | AFTSurvivalModel,
    pd: Any,
) -> DataFrame:
    np = _import_numpy()
    copied = _as_dataframe(frame, pd, class_name=type(model).__name__)
    _validate_unique_index(copied)
    prepared = _fill_prediction_features(copied, model=model)
    _validate_required_columns(
        prepared,
        duration_col=None,
        event_col=None,
        covariate_cols=model.covariate_cols_,
        segment_col=model.config_.input.segment_col,
        id_col=None,
    )
    _validate_numeric_columns(prepared, columns=model.covariate_cols_, np=np)
    _validate_optional_text_column(prepared, model.config_.input.segment_col)
    return prepared


def _fill_prediction_features(
    frame: DataFrame,
    *,
    model: CoxPHSurvivalModel | AFTSurvivalModel,
) -> DataFrame:
    columns = [
        column
        for column in model.covariate_cols_
        if column in model.prediction_features_.columns and column not in frame.columns
    ]
    if _PARTITION_COL in model.prediction_features_.columns and _PARTITION_COL not in frame.columns:
        columns.append(_PARTITION_COL)
    if not columns:
        return frame
    missing_index = [
        str(index) for index in frame.index if index not in model.prediction_features_.index
    ]
    if missing_index:
        raise SurvivalInputError(
            f"No hay features almacenadas para filas de predicción: {missing_index}."
        )
    prepared = frame.copy(deep=True)
    stored = model.prediction_features_.loc[frame.index, columns]
    for column in columns:
        prepared[column] = stored[column]
    return prepared


def _predict_survival_frame(
    model: CoxPHSurvivalModel | AFTSurvivalModel,
    frame: DataFrame,
    times: tuple[float, ...],
) -> DataFrame:
    features = cast("DataFrame", frame.loc[:, model.covariate_cols_].copy(deep=True))
    try:
        with _lifelines_warnings_as_errors():
            survival = model.fitter_.predict_survival_function(features, times=list(times))
    except Warning as exc:
        raise SurvivalTransformError("lifelines emitió un warning durante la predicción.") from exc
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise SurvivalTransformError(f"lifelines rechazó la predicción survival: {exc}") from exc
    if survival.shape != (len(times), len(frame.index)):
        raise SurvivalTransformError("lifelines publicó una matriz survival con forma inesperada.")
    return _normalize_frame(cast("DataFrame", survival))


def _linear_predictors(
    model: CoxPHSurvivalModel | AFTSurvivalModel,
    frame: DataFrame,
) -> tuple[float | None, ...]:
    if not isinstance(model, CoxPHSurvivalModel):
        return (None,) * len(frame.index)
    features = cast("DataFrame", frame.loc[:, model.covariate_cols_].copy(deep=True))
    try:
        values = model.fitter_.predict_log_partial_hazard(features)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise SurvivalTransformError(f"lifelines rechazó el predictor lineal Cox: {exc}") from exc
    return tuple(_clean_float(float(value)) for value in values.to_numpy(dtype="float64"))


def _resolve_times(
    model: CoxPHSurvivalModel | AFTSurvivalModel,
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
            values = model.observed_times_
            fallback_warning = _NO_TIME_GRID_WARNING
    resolved = _validate_times(values)
    outside_cox_support = (
        isinstance(model, CoxPHSurvivalModel)
        and max(resolved) > model.max_observed_time_ + _FLOAT_ATOL
    )
    if outside_cox_support:
        raise SurvivalTransformError(
            "Cox PH no extrapola fuera del soporte observado: "
            f"time_value={max(resolved)}, max_observed_time={model.max_observed_time_}."
        )
    return resolved, fallback_warning


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


def _survival_rows(
    points: tuple[_PredictionPoint, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows = [
        {
            "row_id": point.row_id,
            "segment": point.segment,
            "period": point.period,
            "time_value": point.time_value,
            "survival": point.survival,
        }
        for point in points
    ]
    return rows, [_curve_index(point.row_id, point.period) for point in points]


def _hazard_rows(
    points: tuple[_PredictionPoint, ...],
    *,
    link: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows = [
        {
            "row_id": point.row_id,
            "segment": point.segment,
            "period": point.period,
            "time_value": point.time_value,
            "hazard": point.hazard,
            "link": link,
            "linear_predictor_hazard": point.linear_predictor,
        }
        for point in points
    ]
    return rows, [_curve_index(point.row_id, point.period) for point in points]


def _term_structure_rows(
    model: CoxPHSurvivalModel | AFTSurvivalModel,
    points: tuple[_PredictionPoint, ...],
    fallback_warning: str | None,
    *,
    method: Literal["cox_ph", "aft"],
) -> tuple[list[dict[str, Any]], list[str]]:
    warning_codes = tuple(
        dict.fromkeys(
            (
                *model.warning_codes_,
                *((fallback_warning,) if fallback_warning is not None else ()),
            )
        )
    )
    rows: list[dict[str, Any]] = []
    for point in points:
        rows.append(
            {
                "row_id": point.row_id,
                "segment": point.segment,
                "partition": point.partition,
                "period": point.period,
                "time_value": point.time_value,
                "hazard": point.hazard,
                "survival": point.survival,
                "pd_marginal": _non_negative_float(
                    point.survival * point.hazard / max(1.0 - point.hazard, _FLOAT_ATOL),
                    field_name="pd_marginal",
                ),
                "pd_cumulative": _unit_float(1.0 - point.survival, field_name="pd_cumulative"),
                "method": method,
                "pd_source": model.config_.input.pd_source,
                "scenario": _SCENARIO,
                "warning_codes": warning_codes,
            }
        )
    return rows, [_curve_index(point.row_id, point.period) for point in points]


def _interval_hazard(*, previous_survival: float, survival: float) -> float:
    if survival > previous_survival + _FLOAT_ATOL:
        raise SurvivalTransformError("La supervivencia predicha no puede aumentar en la grilla.")
    if previous_survival <= _FLOAT_ATOL:
        return 0.0
    hazard = 1.0 - survival / previous_survival
    return _unit_float(hazard, field_name="hazard")


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
        raise SurvivalInputError(f"Faltan columnas requeridas para Cox/AFT: {missing}.")


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


def _validate_numeric_columns(frame: DataFrame, *, columns: tuple[str, ...], np: Any) -> None:
    for column in columns:
        _numeric_values(frame[column], column=column, np=np)


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
            f"Valores missing/no finitos en columna='{column}'; survival no imputa: {invalid}."
        )
    return cast("NDArrayFloat", values)


def _validate_optional_text_column(frame: DataFrame, column: str | None) -> None:
    if column is not None and bool(frame[column].isna().any()):
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


def _row_text(row: Series, column: str | None) -> str | None:
    if column is None:
        return None
    return str(row[column])


def _as_dataframe(value: object, pd: Any, *, class_name: str) -> DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise SurvivalInputError(f"{class_name} requiere un pandas.DataFrame.")
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


def _fit_statistics(fitter: Any, *, method: Literal["cox_ph", "aft"]) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "n_obs": getattr(fitter, "_n_examples", None),
        "log_likelihood": getattr(fitter, "log_likelihood_", None),
        "concordance_index": getattr(fitter, "concordance_index_", None),
        "n_parameters": _n_parameters(fitter),
    }
    if method == _COX_METHOD:
        stats["partial_aic"] = getattr(fitter, "AIC_partial_", None)
    else:
        stats["aic"] = getattr(fitter, "AIC_", None)
    return stats


def _n_parameters(fitter: Any) -> int | None:
    params = getattr(fitter, "params_", None)
    if params is not None and hasattr(params, "shape"):
        return int(params.shape[0])
    return None


def _dependency_versions() -> dict[str, str]:
    return {
        "pandas": version("pandas"),
        "numpy": version("numpy"),
        "lifelines": version("lifelines"),
    }


def _check_fitted(model: CoxPHSurvivalModel | AFTSurvivalModel, *, class_name: str) -> None:
    if not hasattr(model, "fitter_"):
        raise NotFittedError(f"{class_name} no está fiteado; llame fit(...) antes de predecir.")


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


def _import_lifelines_components() -> _LifelinesComponents:
    """Importa lifelines localmente y traduce su ausencia al extra survival."""
    try:
        lifelines = importlib.import_module("lifelines")
        statistics = importlib.import_module("lifelines.statistics")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SURVIVAL_EXTRA_MESSAGE) from exc
    return _LifelinesComponents(
        cox_ph_fitter=lifelines.CoxPHFitter,
        weibull_aft_fitter=lifelines.WeibullAFTFitter,
        lognormal_aft_fitter=lifelines.LogNormalAFTFitter,
        loglogistic_aft_fitter=lifelines.LogLogisticAFTFitter,
        proportional_hazard_test=statistics.proportional_hazard_test,
    )


def _import_pandas() -> Any:
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("Cox/AFT requiere pandas.") from exc


def _import_numpy() -> Any:
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("Cox/AFT requiere numpy.") from exc
