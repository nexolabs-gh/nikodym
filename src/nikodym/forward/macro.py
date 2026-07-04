"""Proyección macroeconómica forward-looking (SDD-20 §3/§4/§6).

``MacroProjectionModel`` ajusta modelos macro ARIMA/SARIMA/ARIMAX univariados y VAR/VECM
multivariados con ``statsmodels`` como ruta primaria. ``pmdarima.auto_arima`` queda detrás de
configuración explícita. El módulo preserva el import liviano de ``nikodym.forward``: ``pandas``,
``numpy``, ``scipy``, ``statsmodels`` y ``pmdarima`` se cargan solo en ``fit``/``predict`` o en
helpers invocados por esos métodos.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import hashlib
import importlib
import math
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeAlias, cast

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import MissingDependencyError, NotFittedError
from nikodym.core.mixins import AuditableMixin
from nikodym.forward.config import ForwardConfig, MacroModelKind
from nikodym.forward.exceptions import (
    ForwardConfigError,
    ForwardFitError,
    ForwardInputError,
    MacroProjectionError,
)
from nikodym.forward.results import MacroDiagnostics

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any

__all__ = ["MacroProjectionModel"]

_FORECASTING_EXTRA_MESSAGE = "instale nikodym[forecasting]"
_LJUNG_BOX_ALPHA = 0.05
_BASE_SCENARIO = "base"
_SCENARIO_COLUMN = "scenario"
_MACRO_PROJECTION_COLUMNS: tuple[str, ...] = (
    "scenario",
    "scenario_weight",
    "period",
    "time_value",
    "macro_variable",
    "projected_value",
    "model_value",
    "shock_value",
    "method",
    "model_id",
    "is_reasonable_supportable",
    "warning_codes",
)
_UNIVARIATE_KINDS: frozenset[str] = frozenset({"arima", "sarima", "arimax", "auto_arima"})
_MULTIVARIATE_KINDS: frozenset[str] = frozenset({"var", "vecm"})


@dataclass(frozen=True)
class _PreparedMacroFrame:
    frame: DataFrame
    macro_variables: tuple[str, ...]
    exogenous_variables: tuple[str, ...]
    time_index: tuple[Any, ...]
    frequency: str | None
    input_rows: int
    input_gaps: int
    input_missing: int
    input_time_range: tuple[str | int | float | None, str | int | float | None] | None
    macro_data_hash: str


@dataclass(frozen=True)
class _CapturedResult:
    value: Any
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _FitState:
    models: dict[str, Any]
    residuals: dict[str, NDArrayFloat]
    orders_lags: dict[str, Any]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _ForecastState:
    values: dict[str, tuple[float, ...]]
    warnings: tuple[str, ...]


class MacroProjectionModel(AuditableMixin):
    """Ajusta y proyecta variables macroeconómicas para forward-looking."""

    config_cls: ClassVar[type[ForwardConfig]] = ForwardConfig

    def __init__(self, *, config: ForwardConfig | Mapping[str, Any]) -> None:
        """Asigna configuración forward sin importar dependencias estadísticas pesadas."""
        if isinstance(config, ForwardConfig):
            self.config = config
        else:
            self.config = ForwardConfig.model_validate(config)

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig | Mapping[str, Any]) -> MacroProjectionModel:
        """Construye el modelo desde ``ForwardConfig`` o un mapping equivalente."""
        if not isinstance(cfg, ForwardConfig):
            cfg = ForwardConfig.model_validate(cfg)
        return cls(config=cfg)

    def fit(self, macro_frame: DataFrame, *, audit: AuditSink | None = None) -> Self:
        """Ajusta el modelo macro configurado y publica diagnósticos residuales."""
        pd = _import_pandas()
        np = _import_numpy()
        if audit is not None:
            self._audit = audit

        cfg = self.config
        prepared = _prepare_macro_frame(macro_frame, cfg=cfg, pd=pd, np=np)
        _validate_model_shape(prepared, cfg=cfg)
        if cfg.macro.kind in _UNIVARIATE_KINDS:
            fit_state = _fit_univariate(prepared, cfg=cfg, np=np)
        elif cfg.macro.kind == "var":
            fit_state = _fit_var(prepared, cfg=cfg, np=np)
        else:
            fit_state = _fit_vecm(prepared, cfg=cfg, np=np)

        dependency_versions = _dependency_versions(
            cfg.macro.kind,
            cfg.macro.use_pmdarima_auto_order,
        )
        diagnostics = _build_diagnostics(
            prepared=prepared,
            fit_state=fit_state,
            cfg=cfg,
            dependency_versions=dependency_versions,
        )
        if _ljung_box_failed(diagnostics) and cfg.macro.fail_on_ljung_box:
            raise ForwardFitError(
                "Diagnóstico Ljung-Box bajo el umbral configurado "
                f"({_LJUNG_BOX_ALPHA}); revise autocorrelación residual."
            )

        self.config_ = cfg
        self.macro_variables_ = prepared.macro_variables
        self.time_index_ = prepared.time_index
        self.frequency_ = prepared.frequency
        self.models_ = dict(fit_state.models)
        self.residuals_ = {
            variable: _copy_array(residual, np=np)
            for variable, residual in fit_state.residuals.items()
        }
        self.diagnostics_ = diagnostics
        self.dependency_versions_ = dict(dependency_versions)
        self._fit_warnings_ = tuple(fit_state.warnings)
        self._last_observations_ = _last_observations(prepared, np=np)
        self._history_matrix_ = prepared.frame[list(prepared.macro_variables)].to_numpy(
            dtype="float64",
        )
        self._log_fit_decisions(prepared=prepared)
        return self

    def predict(
        self,
        *,
        horizon: int | None = None,
        scenario_frame: DataFrame | None = None,
    ) -> DataFrame:
        """Proyecta variables macro y devuelve ``macro_projection`` tidy."""
        pd = _import_pandas()
        np = _import_numpy()
        _check_fitted(self)
        periods = _validate_horizon(horizon)
        _check_scenario_frame_consumible(scenario_frame, kind=self.config_.macro.kind)
        future_times = _future_time_values(
            self.time_index_,
            horizon=periods,
            frequency=self.frequency_,
            pd=pd,
        )
        rows: list[dict[str, Any]] = []
        scenario_weights = _scenario_weights(self.config_)
        warning_codes = tuple(self._fit_warnings_)
        for scenario in self.config_.scenarios.scenarios:
            future_exog = _future_exogenous_values(
                scenario_frame,
                scenario_name=scenario.name,
                horizon=periods,
                cfg=self.config_,
                pd=pd,
                np=np,
            )
            forecast = _forecast_model(self, horizon=periods, future_exog=future_exog, np=np)
            scenario_warnings = _dedupe((*warning_codes, *forecast.warnings))
            for variable in self.macro_variables_:
                shocks = scenario.shocks
                shock_value = _clean_float(float(shocks.get(variable, 0.0)))
                for period, model_value in enumerate(forecast.values[variable], start=1):
                    projected = _clean_float(model_value + shock_value)
                    rows.append(
                        {
                            "scenario": scenario.name,
                            "scenario_weight": scenario_weights[scenario.name],
                            "period": period,
                            "time_value": future_times[period - 1],
                            "macro_variable": variable,
                            "projected_value": projected,
                            "model_value": model_value,
                            "shock_value": shock_value,
                            "method": _method_label(self.config_.macro.kind),
                            "model_id": _model_id(self.config_.macro.kind, variable),
                            "is_reasonable_supportable": (
                                period <= self.config_.ttc_reversion.reasonable_supportable_periods
                            ),
                            "warning_codes": scenario_warnings,
                        }
                    )
        return _records_to_frame(rows, pd=pd)

    def residual_diagnostics(self) -> MacroDiagnostics:
        """Devuelve los diagnósticos residuales generados durante ``fit``."""
        _check_fitted(self)
        return self.diagnostics_

    def _log_fit_decisions(self, *, prepared: _PreparedMacroFrame) -> None:
        self.log_decision(
            regla="forward_macro_model",
            umbral={
                "kind": self.config_.macro.kind,
                "ljung_box_lags": self.config_.macro.ljung_box_lags,
                "fail_on_ljung_box": self.config_.macro.fail_on_ljung_box,
            },
            valor={
                "macro_variables": self.macro_variables_,
                "input_rows": prepared.input_rows,
                "warnings": self.diagnostics_.warnings,
            },
            accion="fit_macro_projection",
        )


def _prepare_macro_frame(
    frame: DataFrame,
    *,
    cfg: ForwardConfig,
    pd: Any,
    np: Any,
) -> _PreparedMacroFrame:
    copied = _as_dataframe(frame, pd)
    macro_source = cfg.input.macro_source
    required = [macro_source.time_col, *macro_source.variable_cols, *macro_source.exogenous_cols]
    missing_columns = [column for column in required if column not in copied.columns]
    if missing_columns:
        raise ForwardInputError(f"Faltan columnas macro requeridas: {missing_columns}.")
    if bool(copied.duplicated(subset=[macro_source.time_col], keep=False).any()):
        raise ForwardInputError("El histórico macro contiene períodos duplicados.")
    copied = copied.sort_values(macro_source.time_col, kind="mergesort").reset_index(drop=True)
    model_columns = [*macro_source.variable_cols, *macro_source.exogenous_cols]
    missing_cells = int(copied[[macro_source.time_col, *model_columns]].isna().sum().sum())
    if missing_cells > 0:
        raise ForwardInputError(f"El histórico macro contiene {missing_cells} valores missing.")
    for column in model_columns:
        values = copied[column].to_numpy(dtype="float64")
        if not bool(np.all(np.isfinite(values))):
            raise ForwardInputError(f"La columna macro {column!r} contiene valores no finitos.")
        copied[column] = values
    min_history = cfg.satellite.min_history_periods
    if len(copied.index) < min_history:
        raise ForwardFitError(
            "Serie macro demasiado corta para ajustar: "
            f"observaciones={len(copied.index)}, min_history_periods={min_history}."
        )
    for variable in macro_source.variable_cols:
        if int(copied[variable].nunique(dropna=False)) < 2:
            raise ForwardFitError(f"Serie macro constante no modelable: variable={variable!r}.")

    time_index = tuple(copied[macro_source.time_col].tolist())
    frequency = macro_source.frequency or _infer_frequency(time_index, pd=pd)
    return _PreparedMacroFrame(
        frame=copied,
        macro_variables=macro_source.variable_cols,
        exogenous_variables=macro_source.exogenous_cols,
        time_index=time_index,
        frequency=frequency,
        input_rows=len(copied.index),
        input_gaps=_count_time_gaps(time_index, np=np),
        input_missing=missing_cells,
        input_time_range=_time_range(time_index),
        macro_data_hash=_macro_data_hash(copied[[macro_source.time_col, *model_columns]], pd=pd),
    )


def _validate_model_shape(prepared: _PreparedMacroFrame, *, cfg: ForwardConfig) -> None:
    kind = cfg.macro.kind
    if kind in _MULTIVARIATE_KINDS and len(prepared.macro_variables) < 2:
        raise ForwardConfigError("kind='var'/'vecm' exige al menos dos variable_cols.")
    if kind == "arimax" and not prepared.exogenous_variables:
        raise ForwardConfigError("kind='arimax' exige macro_source.exogenous_cols no vacío.")
    if cfg.macro.use_pmdarima_auto_order and len(prepared.macro_variables) != 1:
        raise ForwardConfigError("use_pmdarima_auto_order=True solo aplica a una variable macro.")


def _fit_univariate(prepared: _PreparedMacroFrame, *, cfg: ForwardConfig, np: Any) -> _FitState:
    models: dict[str, Any] = {}
    residuals: dict[str, NDArrayFloat] = {}
    orders_lags: dict[str, Any] = {}
    warnings_seen: list[str] = []
    for variable in prepared.macro_variables:
        series = prepared.frame[variable].to_numpy(dtype="float64")
        if cfg.macro.kind == "auto_arima" or cfg.macro.use_pmdarima_auto_order:
            fit = _fit_auto_arima(series, prepared=prepared, cfg=cfg, variable=variable, np=np)
        else:
            fit = _fit_statsmodels_arima(series, prepared=prepared, cfg=cfg, variable=variable)
        models[variable] = fit.value["model"]
        residuals[variable] = _finite_array(fit.value["residuals"], field_name="residuals", np=np)
        orders_lags[variable] = fit.value["orders_lags"]
        warnings_seen.extend(fit.warnings)
    return _FitState(
        models=models,
        residuals=residuals,
        orders_lags=orders_lags,
        warnings=_dedupe(warnings_seen),
    )


def _fit_statsmodels_arima(
    series: NDArrayFloat,
    *,
    prepared: _PreparedMacroFrame,
    cfg: ForwardConfig,
    variable: str,
) -> _CapturedResult:
    arima_cls = _import_statsmodels_arima()
    exog = _historical_exog(prepared, cfg=cfg)
    order = cfg.macro.arima_order
    seasonal_order = cfg.macro.seasonal_order if cfg.macro.kind == "sarima" else None
    statsmodels_seasonal_order = seasonal_order or (0, 0, 0, 0)
    trend = "c" if order[1] == 0 and (seasonal_order is None or seasonal_order[1] == 0) else "n"

    def fit_model() -> Any:
        model = arima_cls(
            series,
            exog=exog,
            order=order,
            seasonal_order=statsmodels_seasonal_order,
            trend=trend,
        )
        return model.fit()

    captured = _capture_warnings(fit_model, source=f"statsmodels:{variable}")
    result = captured.value
    return _CapturedResult(
        value={
            "model": result,
            "residuals": result.resid,
            "orders_lags": {
                "order": order,
                "seasonal_order": seasonal_order,
                "trend": trend,
            },
        },
        warnings=captured.warnings,
    )


def _fit_auto_arima(
    series: NDArrayFloat,
    *,
    prepared: _PreparedMacroFrame,
    cfg: ForwardConfig,
    variable: str,
    np: Any,
) -> _CapturedResult:
    auto_arima = _import_auto_arima()
    exog = _historical_exog(prepared, cfg=cfg)
    random = cfg.macro.auto_arima_random
    random_state = cfg.macro.random_state

    def fit_model() -> Any:
        return auto_arima(
            series,
            X=exog,
            seasonal=cfg.macro.kind == "sarima",
            random=random,
            random_state=random_state,
            suppress_warnings=False,
            error_action="raise",
        )

    captured = _capture_warnings(fit_model, source=f"pmdarima:{variable}")
    model = captured.value
    residual_values = model.resid()
    order = tuple(int(item) for item in model.order)
    seasonal_order = tuple(int(item) for item in getattr(model, "seasonal_order", (0, 0, 0, 0)))
    return _CapturedResult(
        value={
            "model": model,
            "residuals": _finite_array(residual_values, field_name="residuals", np=np),
            "orders_lags": {"order": order, "seasonal_order": seasonal_order},
        },
        warnings=captured.warnings,
    )


def _fit_var(prepared: _PreparedMacroFrame, *, cfg: ForwardConfig, np: Any) -> _FitState:
    var_cls = _import_var()
    lags = cfg.macro.var_lags or 1
    values = prepared.frame[list(prepared.macro_variables)]

    def fit_model() -> Any:
        return var_cls(values).fit(maxlags=lags, ic=None, trend="c")

    captured = _capture_warnings(fit_model, source="statsmodels:VAR")
    residual_values = _residual_matrix(captured.value.resid, prepared.macro_variables, np=np)
    residuals = {
        variable: _finite_array(residual_values[:, index], field_name="residuals", np=np)
        for index, variable in enumerate(prepared.macro_variables)
    }
    return _FitState(
        models={"__multivariate__": captured.value},
        residuals=residuals,
        orders_lags={"var_lags": lags},
        warnings=captured.warnings,
    )


def _fit_vecm(prepared: _PreparedMacroFrame, *, cfg: ForwardConfig, np: Any) -> _FitState:
    if cfg.macro.vecm_rank is None:
        raise ForwardConfigError(
            "FALTA-DATO-FWD: kind='vecm' exige vecm_rank explícito en esta versión."
        )
    vecm_cls = _import_vecm()
    k_ar_diff = cfg.macro.var_lags or 1
    values = prepared.frame[list(prepared.macro_variables)]

    def fit_model() -> Any:
        return vecm_cls(values, k_ar_diff=k_ar_diff, coint_rank=cfg.macro.vecm_rank).fit()

    captured = _capture_warnings(fit_model, source="statsmodels:VECM")
    residual_values = _residual_matrix(captured.value.resid, prepared.macro_variables, np=np)
    residuals = {
        variable: _finite_array(residual_values[:, index], field_name="residuals", np=np)
        for index, variable in enumerate(prepared.macro_variables)
    }
    return _FitState(
        models={"__multivariate__": captured.value},
        residuals=residuals,
        orders_lags={"k_ar_diff": k_ar_diff, "vecm_rank": cfg.macro.vecm_rank},
        warnings=captured.warnings,
    )


def _build_diagnostics(
    *,
    prepared: _PreparedMacroFrame,
    fit_state: _FitState,
    cfg: ForwardConfig,
    dependency_versions: Mapping[str, str],
) -> MacroDiagnostics:
    ljung_box = _ljung_box_diagnostics(fit_state.residuals, cfg=cfg)
    warnings_seen = _dedupe((*fit_state.warnings, *ljung_box["warnings"]))
    failed = any(
        p_value < _LJUNG_BOX_ALPHA
        for values in ljung_box["p_values"].values()
        for p_value in values.values()
    )
    action = "fail" if cfg.macro.fail_on_ljung_box and failed else "warn" if failed else "pass"
    return MacroDiagnostics(
        method=cfg.macro.kind,
        macro_variables=prepared.macro_variables,
        frequency=prepared.frequency,
        orders_lags=fit_state.orders_lags,
        horizon=cfg.macro.horizon_periods,
        dependency_versions=dict(dependency_versions),
        input_rows=prepared.input_rows,
        input_gaps=prepared.input_gaps,
        input_missing=prepared.input_missing,
        input_time_range=prepared.input_time_range,
        macro_data_hash=prepared.macro_data_hash,
        ljung_box_lags=ljung_box["lags"],
        ljung_box_statistics=ljung_box["statistics"],
        ljung_box_p_values=ljung_box["p_values"],
        ljung_box_action=action,
        warnings=warnings_seen,
    )


def _ljung_box_diagnostics(
    residuals: Mapping[str, NDArrayFloat],
    *,
    cfg: ForwardConfig,
) -> dict[str, Any]:
    np = _import_numpy()
    acorr_ljungbox = _import_ljung_box()
    configured_lags = tuple(sorted(dict.fromkeys(cfg.macro.ljung_box_lags)))
    statistics: dict[str, dict[int, float]] = {}
    p_values: dict[str, dict[int, float]] = {}
    warnings_seen: list[str] = []
    lags_used: set[int] = set()
    for variable, residual in residuals.items():
        clean = np.asarray(residual, dtype="float64")
        clean = clean[np.isfinite(clean)]
        valid_lags = tuple(lag for lag in configured_lags if lag < len(clean))
        if not valid_lags:
            warnings_seen.append(f"ljung_box_no_valid_lags:{variable}")
            statistics[variable] = {}
            p_values[variable] = {}
            continue

        def run_test(clean_values: NDArrayFloat = clean, lags: tuple[int, ...] = valid_lags) -> Any:
            return acorr_ljungbox(clean_values, lags=list(lags), return_df=True)

        captured = _capture_warnings(run_test, source=f"ljung_box:{variable}")
        table = captured.value
        warnings_seen.extend(captured.warnings)
        lags_used.update(valid_lags)
        statistics[variable] = {
            int(lag): _clean_float(float(table.loc[lag, "lb_stat"])) for lag in valid_lags
        }
        p_values[variable] = {
            int(lag): _unit_interval_float(float(table.loc[lag, "lb_pvalue"])) for lag in valid_lags
        }
    return {
        "lags": tuple(sorted(lags_used)),
        "statistics": statistics,
        "p_values": p_values,
        "warnings": _dedupe(warnings_seen),
    }


def _ljung_box_failed(diagnostics: MacroDiagnostics) -> bool:
    return any(
        p_value is not None and p_value < _LJUNG_BOX_ALPHA
        for values in diagnostics.ljung_box_p_values.values()
        for p_value in values.values()
    )


def _forecast_model(
    estimator: MacroProjectionModel,
    *,
    horizon: int,
    future_exog: NDArrayFloat | None,
    np: Any,
) -> _ForecastState:
    cfg = estimator.config_
    if cfg.macro.kind in _UNIVARIATE_KINDS:
        return _forecast_univariate(estimator, horizon=horizon, future_exog=future_exog, np=np)
    if cfg.macro.kind == "var":
        return _forecast_var(estimator, horizon=horizon, np=np)
    return _forecast_vecm(estimator, horizon=horizon, np=np)


def _forecast_univariate(
    estimator: MacroProjectionModel,
    *,
    horizon: int,
    future_exog: NDArrayFloat | None,
    np: Any,
) -> _ForecastState:
    values: dict[str, tuple[float, ...]] = {}
    warnings_seen: list[str] = []
    if estimator.config_.macro.kind == "arimax" and future_exog is None:
        raise MacroProjectionError("ARIMAX exige exógenas futuras suficientes para proyectar.")
    for variable in estimator.macro_variables_:
        model = estimator.models_[variable]

        def run_forecast(current_model: Any = model) -> Any:
            if estimator.config_.macro.kind == "auto_arima" or (
                estimator.config_.macro.use_pmdarima_auto_order
            ):
                return current_model.predict(n_periods=horizon, X=future_exog)
            return current_model.forecast(steps=horizon, exog=future_exog)

        captured = _capture_warnings(run_forecast, source=f"forecast:{variable}")
        warnings_seen.extend(captured.warnings)
        values[variable] = _float_tuple(captured.value, length=horizon, np=np)
    return _ForecastState(values=values, warnings=_dedupe(warnings_seen))


def _forecast_var(estimator: MacroProjectionModel, *, horizon: int, np: Any) -> _ForecastState:
    model = estimator.models_["__multivariate__"]
    lags = int(getattr(model, "k_ar", 1))
    y = np.asarray(estimator._history_matrix_, dtype="float64")[-lags:, :]

    def run_forecast() -> Any:
        return model.forecast(y=y, steps=horizon)

    captured = _capture_warnings(run_forecast, source="forecast:VAR")
    matrix = np.asarray(captured.value, dtype="float64")
    return _matrix_forecast_state(matrix, estimator.macro_variables_, captured.warnings, np=np)


def _forecast_vecm(estimator: MacroProjectionModel, *, horizon: int, np: Any) -> _ForecastState:
    model = estimator.models_["__multivariate__"]

    def run_forecast() -> Any:
        return model.predict(steps=horizon)

    captured = _capture_warnings(run_forecast, source="forecast:VECM")
    matrix = np.asarray(captured.value, dtype="float64")
    return _matrix_forecast_state(matrix, estimator.macro_variables_, captured.warnings, np=np)


def _matrix_forecast_state(
    matrix: NDArrayFloat,
    variables: tuple[str, ...],
    warnings_seen: tuple[str, ...],
    *,
    np: Any,
) -> _ForecastState:
    if matrix.ndim != 2 or matrix.shape[1] != len(variables):
        raise MacroProjectionError(
            "El forecast multivariado no coincide con las variables macro configuradas."
        )
    values = {
        variable: _float_tuple(matrix[:, index], length=matrix.shape[0], np=np)
        for index, variable in enumerate(variables)
    }
    return _ForecastState(values=values, warnings=warnings_seen)


def _check_scenario_frame_consumible(scenario_frame: DataFrame | None, *, kind: str) -> None:
    """Aborta si se proveen trayectorias por escenario que el kind no puede consumir.

    Solo ``arimax`` aplica trayectorias exógenas futuras por escenario. Para los demás
    kinds (``arima``/``sarima``/``auto_arima``/``var``/``vecm``) el ``scenario_frame`` se
    descartaría en silencio y ``projected_value(adverse)`` quedaría idéntico a ``base``,
    falseando el ECL ponderado. Si el usuario provee trayectorias que no se pueden usar, se
    levanta un error explícito en vez de degradar en silencio (nunca etiquetar sin calcular).
    """
    if scenario_frame is None or kind == "arimax":
        return
    raise MacroProjectionError(
        f"scenario_frame aporta trayectorias macro por escenario, pero kind={kind!r} no las "
        "consume; solo 'arimax' aplica exógenas futuras por escenario. Exprese los escenarios "
        "mediante shocks o use kind='arimax'."
    )


def _future_exogenous_values(
    scenario_frame: DataFrame | None,
    *,
    scenario_name: str,
    horizon: int,
    cfg: ForwardConfig,
    pd: Any,
    np: Any,
) -> NDArrayFloat | None:
    if cfg.macro.kind != "arimax":
        return None
    exogenous_cols = cfg.input.macro_source.exogenous_cols
    if scenario_frame is None:
        raise MacroProjectionError("ARIMAX exige scenario_frame con exógenas futuras.")
    frame = _as_dataframe(scenario_frame, pd)
    missing = [column for column in exogenous_cols if column not in frame.columns]
    if missing:
        raise MacroProjectionError(f"Faltan exógenas futuras para ARIMAX: {missing}.")
    if _SCENARIO_COLUMN in frame.columns:
        scenario_mask = frame[_SCENARIO_COLUMN].astype("string") == scenario_name
        selected = frame.loc[scenario_mask].copy(deep=True)
        if selected.empty and scenario_name != _BASE_SCENARIO:
            base_mask = frame[_SCENARIO_COLUMN].astype("string") == _BASE_SCENARIO
            selected = frame.loc[base_mask].copy(deep=True)
    else:
        selected = frame.copy(deep=True)
    if cfg.input.macro_source.time_col in selected.columns:
        selected = selected.sort_values(cfg.input.macro_source.time_col, kind="mergesort")
    if len(selected.index) < horizon:
        raise MacroProjectionError(
            "ARIMAX exige exógenas futuras suficientes: "
            f"scenario={scenario_name!r}, filas={len(selected.index)}, horizon={horizon}."
        )
    values = selected.loc[:, list(exogenous_cols)].head(horizon).to_numpy(dtype="float64")
    if not bool(np.all(np.isfinite(values))):
        raise MacroProjectionError("Las exógenas futuras ARIMAX deben ser finitas.")
    return cast("NDArrayFloat", values)


def _historical_exog(prepared: _PreparedMacroFrame, *, cfg: ForwardConfig) -> NDArrayFloat | None:
    if cfg.macro.kind != "arimax":
        return None
    return cast(
        "NDArrayFloat",
        prepared.frame[list(prepared.exogenous_variables)].to_numpy(dtype="float64"),
    )


def _last_observations(prepared: _PreparedMacroFrame, *, np: Any) -> dict[str, float]:
    values = prepared.frame[list(prepared.macro_variables)].tail(1).to_numpy(dtype="float64")
    flat = np.asarray(values, dtype="float64").reshape(len(prepared.macro_variables))
    return {
        variable: _clean_float(float(flat[index]))
        for index, variable in enumerate(prepared.macro_variables)
    }


def _as_dataframe(frame: DataFrame, pd: Any) -> DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise ForwardInputError("MacroProjectionModel requiere un pandas.DataFrame.")
    return cast("DataFrame", frame.copy(deep=True))


def _records_to_frame(rows: list[dict[str, Any]], *, pd: Any) -> DataFrame:
    frame = pd.DataFrame.from_records(rows, columns=_MACRO_PROJECTION_COLUMNS)
    for column in ("scenario_weight", "projected_value", "model_value", "shock_value"):
        zero_mask = frame[column] == 0.0
        if bool(zero_mask.any()):
            frame[column] = frame[column].mask(zero_mask, 0.0)
    return cast("DataFrame", frame)


def _validate_horizon(horizon: int | None) -> int:
    if horizon is None:
        raise MacroProjectionError("predict requiere horizon explícito.")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise MacroProjectionError(f"horizon debe ser un entero positivo; recibido {horizon!r}.")
    return horizon


def _check_fitted(estimator: MacroProjectionModel) -> None:
    if not hasattr(estimator, "models_"):
        raise NotFittedError(
            "MacroProjectionModel no está fiteado; llame fit(...) antes de proyectar."
        )


def _future_time_values(
    time_index: Sequence[Any],
    *,
    horizon: int,
    frequency: str | None,
    pd: Any,
) -> tuple[Any, ...]:
    if not time_index:
        raise MacroProjectionError("El índice temporal macro está vacío.")
    last = time_index[-1]
    if isinstance(last, pd.Period):
        return tuple(last + step for step in range(1, horizon + 1))
    if isinstance(last, pd.Timestamp):
        if frequency is None:
            raise MacroProjectionError("Series temporales con fecha requieren frequency inferible.")
        start = last + pd.tseries.frequencies.to_offset(frequency)
        return tuple(pd.date_range(start=start, periods=horizon, freq=frequency).tolist())
    if _is_numeric_time(last):
        step = _numeric_time_step(time_index)
        return tuple(_clean_float(float(last) + step * period) for period in range(1, horizon + 1))
    raise MacroProjectionError(f"Tipo temporal macro no soportado para forecast: {type(last)!r}.")


def _infer_frequency(time_index: Sequence[Any], *, pd: Any) -> str | None:
    if len(time_index) < 3:
        return None
    if all(isinstance(value, pd.Timestamp) for value in time_index):
        inferred = pd.infer_freq(list(time_index))
        return None if inferred is None else str(inferred)
    if all(isinstance(value, pd.Period) for value in time_index):
        freq = time_index[-1].freqstr
        return None if freq is None else str(freq)
    return None


def _count_time_gaps(time_index: Sequence[Any], *, np: Any) -> int:
    if len(time_index) < 3 or not all(_is_numeric_time(value) for value in time_index):
        return 0
    values = np.asarray([float(value) for value in time_index], dtype="float64")
    diffs = np.diff(values)
    positive = diffs[diffs > 0.0]
    if len(positive) == 0:
        return 0
    step = float(np.min(positive))
    gaps = [max(round(float(diff / step)) - 1, 0) for diff in diffs]
    return int(sum(gaps))


def _numeric_time_step(time_index: Sequence[Any]) -> float:
    if len(time_index) < 2:
        return 1.0
    previous = float(time_index[-2])
    current = float(time_index[-1])
    step = current - previous
    if not math.isfinite(step) or step <= 0.0:
        return 1.0
    return _clean_float(step)


def _time_range(
    time_index: Sequence[Any],
) -> tuple[str | int | float | None, str | int | float | None] | None:
    if not time_index:
        return None
    return (_normalize_time_value(time_index[0]), _normalize_time_value(time_index[-1]))


def _normalize_time_value(value: Any) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ForwardInputError(f"El tiempo macro no puede ser booleano: {value!r}.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _clean_float(value)
    if _is_numeric_time(value):
        return _clean_float(float(value))
    return str(value)


def _is_numeric_time(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        candidate = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(candidate)


def _macro_data_hash(frame: DataFrame, *, pd: Any) -> str:
    digest = hashlib.sha256()
    digest.update(b"nikodym.forward.macro_hash.v1")
    logical = frame.copy(deep=True)
    for column in logical.select_dtypes(include=["float"]).columns:
        series = logical[column]
        zero_mask = series == 0.0
        if bool(zero_mask.any()):
            logical[column] = series.mask(zero_mask, 0.0)
    hashed = pd.util.hash_pandas_object(logical, index=True).to_numpy(dtype="uint64")
    digest.update(hashed.astype("<u8", copy=False).tobytes())
    return digest.hexdigest()


def _capture_warnings(func: Callable[[], Any], *, source: str) -> _CapturedResult:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            value = func()
        except Exception as exc:
            if exc.__class__.__module__.startswith(("statsmodels", "pmdarima")):
                raise ForwardFitError(f"Fallo controlado en motor macro {source}: {exc}") from exc
            raise
    return _CapturedResult(value=value, warnings=_warning_codes(caught, source=source))


def _warning_codes(caught: Sequence[warnings.WarningMessage], *, source: str) -> tuple[str, ...]:
    codes: list[str] = []
    for item in caught:
        category = item.category.__name__
        message = str(item.message).strip().replace(" ", "_")
        codes.append(f"{source}:{category}:{message[:80]}")
    return _dedupe(codes)


def _residual_matrix(value: Any, variables: tuple[str, ...], *, np: Any) -> NDArrayFloat:
    if hasattr(value, "loc"):
        matrix = value.loc[:, list(variables)].to_numpy(dtype="float64")
    else:
        matrix = np.asarray(value, dtype="float64")
    if matrix.ndim != 2 or matrix.shape[1] != len(variables):
        raise ForwardFitError("Los residuos multivariados no coinciden con variable_cols.")
    return cast("NDArrayFloat", matrix)


def _finite_array(value: Any, *, field_name: str, np: Any) -> NDArrayFloat:
    array = np.asarray(value, dtype="float64")
    if array.ndim == 0:
        array = array.reshape(1)
    if not bool(np.all(np.isfinite(array))):
        raise ForwardFitError(f"{field_name} contiene valores no finitos.")
    array[array == 0.0] = 0.0
    return cast("NDArrayFloat", array)


def _copy_array(value: NDArrayFloat, *, np: Any) -> NDArrayFloat:
    copied = np.asarray(value, dtype="float64").copy()
    copied[copied == 0.0] = 0.0
    return cast("NDArrayFloat", copied)


def _float_tuple(value: Any, *, length: int, np: Any) -> tuple[float, ...]:
    array = np.asarray(value, dtype="float64").reshape(-1)
    if len(array) != length:
        raise MacroProjectionError(
            f"Forecast macro devolvió largo inesperado: esperado={length}, observado={len(array)}."
        )
    if not bool(np.all(np.isfinite(array))):
        raise MacroProjectionError("Forecast macro contiene valores no finitos.")
    return tuple(_clean_float(float(item)) for item in array)


def _scenario_weights(cfg: ForwardConfig) -> dict[str, float]:
    return {
        scenario.name: _clean_float(float(scenario.weight)) for scenario in cfg.scenarios.scenarios
    }


def _dependency_versions(kind: MacroModelKind, use_pmdarima_auto_order: bool) -> dict[str, str]:
    dependencies = ["numpy", "pandas", "statsmodels"]
    if kind == "auto_arima" or use_pmdarima_auto_order:
        dependencies.append("pmdarima")
    return {name: _package_version(name) for name in dependencies}


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "no-disponible"


def _method_label(kind: MacroModelKind) -> str:
    return "auto_arima" if kind == "auto_arima" else kind.upper()


def _model_id(kind: MacroModelKind, variable: str) -> str:
    return f"macro:{kind}:{variable}"


def _clean_float(value: float) -> float:
    if not math.isfinite(value):
        raise MacroProjectionError(f"Valor macro no finito: {value!r}.")
    if value == 0.0:
        return 0.0
    return value


def _unit_interval_float(value: float) -> float:
    cleaned = _clean_float(value)
    if cleaned < 0.0 or cleaned > 1.0:
        raise ForwardFitError(f"p-value Ljung-Box fuera de [0, 1]: {cleaned}.")
    return cleaned


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _import_pandas() -> Any:
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("MacroProjectionModel requiere pandas.") from exc


def _import_numpy() -> Any:
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("MacroProjectionModel requiere numpy.") from exc


def _import_statsmodels_arima() -> Any:
    try:
        module = importlib.import_module("statsmodels.tsa.arima.model")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            f"MacroProjectionModel requiere statsmodels; {_FORECASTING_EXTRA_MESSAGE}."
        ) from exc
    return module.ARIMA


def _import_var() -> Any:
    try:
        module = importlib.import_module("statsmodels.tsa.vector_ar.var_model")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            f"MacroProjectionModel requiere statsmodels; {_FORECASTING_EXTRA_MESSAGE}."
        ) from exc
    return module.VAR


def _import_vecm() -> Any:
    try:
        module = importlib.import_module("statsmodels.tsa.vector_ar.vecm")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            f"MacroProjectionModel requiere statsmodels; {_FORECASTING_EXTRA_MESSAGE}."
        ) from exc
    return module.VECM


def _import_ljung_box() -> Any:
    try:
        module = importlib.import_module("statsmodels.stats.diagnostic")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            f"MacroProjectionModel requiere statsmodels; {_FORECASTING_EXTRA_MESSAGE}."
        ) from exc
    return module.acorr_ljungbox


def _import_auto_arima() -> Any:
    try:
        module = importlib.import_module("pmdarima")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_FORECASTING_EXTRA_MESSAGE) from exc
    return module.auto_arima
