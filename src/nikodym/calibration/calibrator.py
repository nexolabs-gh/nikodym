"""Calibrador de PD cruda a PD calibrada (SDD-10 §4/§7).

``PDCalibrator`` ajusta una transformación determinista sobre ``linear_predictor``/``pd_raw`` y
publica el frame canónico de ocho columnas definido en SDD-10 §6. El default
``intercept_offset`` sólo desplaza el intercepto en log-odds, por lo que preserva ranking y
discriminación. ``platt_scaling`` e ``isotonic`` quedan como métodos opt-in: en Platt, el
``post_offset`` aplicado para reanclar una tasa externa es monótono y no altera el ranking cuando
``slope > 0``.

El módulo no importa ``pandas``, ``numpy``, ``scipy`` ni ``sklearn`` al cargarse; las dependencias
científicas se resuelven dentro de ``fit``/``transform`` para mantener liviano
``import nikodym.calibration``.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias, cast

from pydantic import ValidationError

from nikodym.calibration.config import (
    AnchorKind,
    AnchorSource,
    CalibrationConfig,
    CalibrationMethod,
)
from nikodym.calibration.exceptions import (
    CalibrationFitError,
    CalibrationOffsetExceededError,
    CalibrationTransformError,
)
from nikodym.calibration.results import (
    CalibrationCardSection,
    CalibrationParameters,
    CalibrationResult,
)
from nikodym.core.base import NikodymTransformer
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, MissingDependencyError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    Series: TypeAlias = pd.Series[Any]
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["PDCalibrator"]

_SCORING_EXTRA_MESSAGE = (
    "PDCalibrator requiere pandas/numpy/scipy/scikit-learn; instale nikodym[scoring]."
)
_FIT_PARTITION: Literal["desarrollo"] = "desarrollo"
_MODELABLE_PARTITIONS = frozenset({_FIT_PARTITION, "holdout", "oot"})
_CONSISTENCY_ATOL = 1e-9
_CONSISTENCY_RTOL = 1e-7
_OUTPUT_COLUMNS: tuple[str, ...] = (
    "partition",
    "target",
    "linear_predictor",
    "pd_raw",
    "linear_predictor_calibrated",
    "pd_calibrated",
    "calibration_method",
    "anchor_kind",
)
_OUTPUT_FLOAT_COLUMNS: tuple[str, ...] = (
    "linear_predictor",
    "pd_raw",
    "linear_predictor_calibrated",
    "pd_calibrated",
)


class PDCalibrator(NikodymTransformer):
    """Calibra PD cruda de una logística a una tasa central."""

    config_cls: ClassVar[type[CalibrationConfig]] = CalibrationConfig

    def __init__(
        self,
        *,
        method: CalibrationMethod = "intercept_offset",
        target_pd: float | None = None,
        anchor_kind: AnchorKind = "through_the_cycle",
        anchor_source: AnchorSource = "development_observed",
        fit_partition: Literal["desarrollo"] = "desarrollo",
        target_tolerance: float = 1e-12,
        max_abs_offset: float | None = None,
        max_iter: int = 100,
        min_fit_rows: int = 30,
        require_both_classes_for_supervised: bool = True,
        pd_raw_column: str = "pd_raw",
        linear_predictor_column: str = "linear_predictor",
        pd_calibrated_column: str = "pd_calibrated",
        linear_predictor_calibrated_column: str = "linear_predictor_calibrated",
        partition_column: str = "partition",
        target_column: str = "target",
    ) -> None:
        """Asigna hiperparámetros sin lógica para preservar ``clone`` de sklearn."""
        self.method = method
        self.target_pd = target_pd
        self.anchor_kind = anchor_kind
        self.anchor_source = anchor_source
        self.fit_partition = fit_partition
        self.target_tolerance = target_tolerance
        self.max_abs_offset = max_abs_offset
        self.max_iter = max_iter
        self.min_fit_rows = min_fit_rows
        self.require_both_classes_for_supervised = require_both_classes_for_supervised
        self.pd_raw_column = pd_raw_column
        self.linear_predictor_column = linear_predictor_column
        self.pd_calibrated_column = pd_calibrated_column
        self.linear_predictor_calibrated_column = linear_predictor_calibrated_column
        self.partition_column = partition_column
        self.target_column = target_column

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> PDCalibrator:
        """Construye ``PDCalibrator`` desde ``CalibrationConfig`` excluyendo ``type``."""
        if not isinstance(cfg, CalibrationConfig):
            cfg = CalibrationConfig.model_validate(cfg)
        kwargs = cfg.model_dump(exclude={"type"})
        return cls(**kwargs)

    def fit(
        self,
        raw_pd_frame: DataFrame,
        *,
        audit: AuditSink | None = None,
    ) -> Self:
        """Ajusta parámetros de calibración usando sólo filas de Desarrollo."""
        pd = _import_pandas()
        np = _import_numpy()
        expit = _import_scipy_expit()
        brentq = _import_scipy_brentq()
        _validate_runtime_config(self)
        if audit is not None:
            self._audit = audit

        frame = _as_dataframe(raw_pd_frame, pd, context="fit")
        contract = _validate_raw_contract(
            self,
            frame,
            pd=pd,
            np=np,
            expit=expit,
            context="fit",
        )
        if contract.excluded_count:
            self.log_decision(
                regla="calibration_fuera_de_modelo",
                umbral=sorted(_MODELABLE_PARTITIONS),
                valor={"filas_filtradas": contract.excluded_count},
                accion="no_calibrar",
            )

        fit_frame = _development_frame(self, contract.modelable_frame)
        if len(fit_frame.index) < self.min_fit_rows:
            raise CalibrationFitError(
                "calibration requiere suficientes filas de Desarrollo: "
                f"n_fit={len(fit_frame.index)}, min_fit_rows={self.min_fit_rows}."
            )

        target_pd = _resolve_target_pd(self, fit_frame, pd=pd, np=np)
        eta_dev = _numeric_array(
            fit_frame[self.linear_predictor_column],
            column=self.linear_predictor_column,
            np=np,
            error_cls=CalibrationFitError,
        )
        raw_pd_dev = _numeric_array(
            fit_frame[self.pd_raw_column],
            column=self.pd_raw_column,
            np=np,
            error_cls=CalibrationFitError,
        )
        raw_mean_pd_dev = _normalize_float(float(raw_pd_dev.mean()))
        observed_default_rate_dev = _observed_default_rate(fit_frame, self.target_column, np=np)

        if self.method == "intercept_offset":
            state = _fit_intercept_offset(
                self,
                eta_dev=eta_dev,
                target_pd=target_pd,
                expit=expit,
                brentq=brentq,
                np=np,
            )
        elif self.method == "platt_scaling":
            state = _fit_platt_scaling(
                self,
                fit_frame=fit_frame,
                eta_dev=eta_dev,
                target_pd=target_pd,
                expit=expit,
                brentq=brentq,
                np=np,
            )
        else:
            state = _fit_isotonic(
                self,
                fit_frame=fit_frame,
                eta_dev=eta_dev,
                raw_pd_dev=raw_pd_dev,
                target_pd=target_pd,
                expit=expit,
                brentq=brentq,
                np=np,
            )

        calibrated = _transform_with_state(
            self,
            contract.modelable_frame,
            state=state,
            pd=pd,
            np=np,
            expit=expit,
        )
        dev_mask = calibrated["partition"].eq(_FIT_PARTITION)
        achieved_mean = _normalize_float(float(calibrated.loc[dev_mask, "pd_calibrated"].mean()))
        if abs(achieved_mean - target_pd) > self.target_tolerance:
            raise CalibrationFitError(
                _solver_error_message(
                    target_pd=target_pd,
                    bracket=state.bracket,
                    iterations=state.iterations,
                    achieved_mean=achieved_mean,
                )
            )

        ranking_preserved = _ranking_preserved(
            contract.modelable_frame[self.pd_raw_column],
            calibrated["pd_calibrated"],
            pd=pd,
            np=np,
        )
        ties_created = (
            state.ties_created
            if self.method == "isotonic"
            else _ties_created(
                contract.modelable_frame[self.pd_raw_column],
                calibrated["pd_calibrated"],
                np=np,
            )
        )
        dependency_versions = _dependency_versions(
            include_scipy=True,
            include_sklearn=self.method in {"platt_scaling", "isotonic"},
        )
        parameters = CalibrationParameters(
            method=self.method,
            target_pd=target_pd,
            anchor_kind=self.anchor_kind,
            anchor_source=self.anchor_source,
            fit_partition=_FIT_PARTITION,
            offset=state.offset,
            slope=state.slope,
            intercept=state.intercept,
            isotonic_knots=state.isotonic_knots,
            post_offset=state.post_offset,
            target_tolerance=float(self.target_tolerance),
            achieved_mean_pd_dev=achieved_mean,
            raw_mean_pd_dev=raw_mean_pd_dev,
            observed_default_rate_dev=observed_default_rate_dev,
            n_fit=len(fit_frame.index),
        )
        card = CalibrationCardSection(
            method=self.method,
            target_pd=target_pd,
            anchor_kind=self.anchor_kind,
            anchor_source=self.anchor_source,
            fit_partition=_FIT_PARTITION,
            n_fit=len(fit_frame.index),
            raw_mean_pd_dev=raw_mean_pd_dev,
            calibrated_mean_pd_dev=achieved_mean,
            observed_default_rate_dev=observed_default_rate_dev,
            offset=state.offset,
            slope=state.slope,
            intercept=state.intercept,
            ranking_preserved=ranking_preserved,
            ties_created=ties_created,
            pd_raw_column="pd_raw",
            pd_calibrated_column="pd_calibrated",
            dependency_versions=dependency_versions,
        )
        result = CalibrationResult(
            calibrated_pd_frame=calibrated,
            parameters=parameters,
            card=card,
        )

        self.method_ = self.method
        self.target_pd_ = target_pd
        self.anchor_kind_ = self.anchor_kind
        self.anchor_source_ = self.anchor_source
        self.fit_partition_ = _FIT_PARTITION
        self.offset_ = state.offset
        self.slope_ = state.slope
        self.intercept_ = state.intercept
        self.post_offset_ = state.post_offset
        self.isotonic_knots_ = state.isotonic_knots
        self._isotonic_model_ = state.isotonic_model
        self.parameters_ = parameters
        self.card_ = card
        self.result_ = result
        self.ranking_preserved_ = ranking_preserved
        self.ties_created_ = ties_created
        self.dependency_versions_ = dependency_versions
        self.raw_mean_pd_dev_ = raw_mean_pd_dev
        self.achieved_mean_pd_dev_ = achieved_mean
        self.n_fit_ = len(fit_frame.index)
        self.observed_default_rate_dev_ = observed_default_rate_dev

        _audit_fit(self)
        return self

    def transform(self, raw_pd_frame: DataFrame) -> DataFrame:
        """Aplica la calibración fiteada y publica las ocho columnas canónicas."""
        self._check_fitted()
        pd = _import_pandas()
        np = _import_numpy()
        expit = _import_scipy_expit()
        if self.method_ == "platt_scaling":
            _import_logistic_regression()
        if self.method_ == "isotonic":
            _import_isotonic_regression()

        frame = _as_dataframe(raw_pd_frame, pd, context="transform")
        contract = _validate_raw_contract(
            self,
            frame,
            pd=pd,
            np=np,
            expit=expit,
            context="transform",
        )
        if contract.excluded_count:
            self.log_decision(
                regla="calibration_fuera_de_modelo",
                umbral=sorted(_MODELABLE_PARTITIONS),
                valor={"filas_filtradas": contract.excluded_count},
                accion="no_calibrar",
            )
        return _transform_with_state(
            self,
            contract.modelable_frame,
            state=_state_from_estimator(self),
            pd=pd,
            np=np,
            expit=expit,
        )

    def fit_transform(
        self,
        raw_pd_frame: DataFrame,
        *,
        audit: AuditSink | None = None,
    ) -> DataFrame:
        """Ajusta el calibrador y devuelve el frame calibrado para la misma entrada."""
        return self.fit(raw_pd_frame, audit=audit).transform(raw_pd_frame)


@dataclass(frozen=True)
class RawContract:
    """Entrada validada y filtrada a filas modelables."""

    modelable_frame: DataFrame
    excluded_count: int


@dataclass(frozen=True)
class FitState:
    """Parámetros fiteados necesarios para aplicar una calibración."""

    method: CalibrationMethod
    target_pd: float
    offset: float | None
    slope: float | None
    intercept: float | None
    post_offset: float | None
    isotonic_model: Any | None
    isotonic_knots: tuple[tuple[float, float], ...]
    ties_created: int
    bracket: tuple[float, float]
    iterations: int


def _import_pandas() -> Any:
    """Importa pandas localmente y traduce ausencias a mensaje accionable."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _import_numpy() -> Any:
    """Importa numpy localmente y traduce ausencias a mensaje accionable."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _import_scipy_expit() -> Any:
    """Importa ``scipy.special.expit`` bajo demanda."""
    try:
        special = importlib.import_module("scipy.special")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return special.expit


def _import_scipy_brentq() -> Any:
    """Importa ``scipy.optimize.brentq`` bajo demanda."""
    try:
        optimize = importlib.import_module("scipy.optimize")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return optimize.brentq


def _import_logistic_regression() -> Any:
    """Importa ``LogisticRegression`` bajo demanda."""
    try:
        linear_model = importlib.import_module("sklearn.linear_model")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return linear_model.LogisticRegression


def _import_isotonic_regression() -> Any:
    """Importa ``IsotonicRegression`` bajo demanda."""
    try:
        isotonic = importlib.import_module("sklearn.isotonic")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return isotonic.IsotonicRegression


def _validate_runtime_config(estimator: PDCalibrator) -> None:
    """Revalida hiperparámetros planos contra ``CalibrationConfig``."""
    try:
        estimator._validate_config()
    except (ConfigError, ValidationError) as exc:
        raise ConfigError(f"Hiperparámetros inválidos para PDCalibrator: {exc}") from exc


def _as_dataframe(
    df: object,
    pd: Any,
    *,
    context: Literal["fit", "transform"],
) -> DataFrame:
    """Valida y copia defensivamente una entrada tabular."""
    if not isinstance(df, pd.DataFrame):
        error_cls = CalibrationFitError if context == "fit" else CalibrationTransformError
        raise error_cls(
            f"PDCalibrator.{context} requiere pandas.DataFrame; tipo observado={type(df).__name__}."
        )
    if len(df.index) == 0:
        error_cls = CalibrationFitError if context == "fit" else CalibrationTransformError
        raise error_cls(f"PDCalibrator.{context} recibió un DataFrame vacío.")
    return cast(DataFrame, df.copy(deep=True))


def _validate_raw_contract(
    estimator: PDCalibrator,
    frame: DataFrame,
    *,
    pd: Any,
    np: Any,
    expit: Any,
    context: Literal["fit", "transform"],
) -> RawContract:
    """Valida columnas, unicidad, finitud y consistencia ``pd_raw ≈ sigmoid(eta)``."""
    del pd
    error_cls = CalibrationFitError if context == "fit" else CalibrationTransformError
    _validate_unique_columns(frame, error_cls=error_cls)
    if not frame.index.is_unique:
        raise error_cls("PDCalibrator requiere índice único en raw_pd_frame.")
    _validate_required_columns(estimator, frame, error_cls=error_cls)
    _validate_output_collisions(estimator, frame, error_cls=error_cls)

    modelable_mask = frame[estimator.partition_column].isin(_MODELABLE_PARTITIONS)
    modelable = frame.loc[modelable_mask].copy(deep=True)
    excluded_count = int((~modelable_mask).sum())
    if len(modelable.index) == 0:
        return RawContract(modelable_frame=modelable, excluded_count=excluded_count)

    eta = _numeric_array(
        modelable[estimator.linear_predictor_column],
        column=estimator.linear_predictor_column,
        np=np,
        error_cls=error_cls,
    )
    pd_raw = _numeric_array(
        modelable[estimator.pd_raw_column],
        column=estimator.pd_raw_column,
        np=np,
        error_cls=error_cls,
    )
    invalid_pd_mask = (pd_raw <= 0.0) | (pd_raw >= 1.0)
    if bool(invalid_pd_mask.any()):
        observed = pd_raw[invalid_pd_mask][0]
        raise error_cls(
            "pd_raw debe estar estrictamente en (0, 1) para filas modelables: "
            f"valor observado={float(observed)!r}."
        )

    expected = expit(eta)
    close = np.isclose(pd_raw, expected, atol=_CONSISTENCY_ATOL, rtol=_CONSISTENCY_RTOL)
    if not bool(close.all()):
        diff = np.abs(pd_raw - expected)
        max_diff = float(diff.max())
        position = int(diff.argmax())
        raise error_cls(
            "pd_raw no es consistente con sigmoid(linear_predictor): "
            f"fila={modelable.index[position]!r}, diferencia_max={max_diff:.12g}, "
            f"atol={_CONSISTENCY_ATOL:.12g}, rtol={_CONSISTENCY_RTOL:.12g}."
        )
    return RawContract(modelable_frame=modelable, excluded_count=excluded_count)


def _validate_unique_columns(frame: DataFrame, *, error_cls: type[Exception]) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise error_cls(f"PDCalibrator requiere nombres de columnas únicos; duplicadas: {joined}.")


def _validate_required_columns(
    estimator: PDCalibrator,
    frame: DataFrame,
    *,
    error_cls: type[Exception],
) -> None:
    """Valida columnas mínimas de entrada según configuración."""
    required = (
        estimator.partition_column,
        estimator.target_column,
        estimator.linear_predictor_column,
        estimator.pd_raw_column,
    )
    missing = [column for column in required if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise error_cls(f"raw_pd_frame no contiene columnas requeridas: {joined}.")


def _validate_output_collisions(
    estimator: PDCalibrator,
    frame: DataFrame,
    *,
    error_cls: type[Exception],
) -> None:
    """Evita sobrescribir columnas de salida si el input ya venía calibrado."""
    configured_outputs = (
        estimator.linear_predictor_calibrated_column,
        estimator.pd_calibrated_column,
        "calibration_method",
        "anchor_kind",
    )
    collisions = [column for column in configured_outputs if column in frame.columns]
    if collisions:
        joined = ", ".join(f"'{column}'" for column in collisions)
        raise error_cls(f"PDCalibrator no sobrescribe columnas existentes; colisiones: {joined}.")


def _numeric_array(
    series: Series,
    *,
    column: str,
    np: Any,
    error_cls: type[Exception],
) -> NDArrayFloat:
    """Convierte una serie a float64 finito sin ordenar ni agregar."""
    try:
        values = series.to_numpy(dtype="float64", copy=True)
    except (TypeError, ValueError) as exc:
        raise error_cls(f"La columna '{column}' debe ser numérica float64-compatible.") from exc
    finite = np.isfinite(values)
    if not bool(finite.all()):
        observed = values[~finite][0]
        raise error_cls(
            f"La columna '{column}' debe contener sólo valores finitos: "
            f"valor observado={float(observed)!r}."
        )
    return cast(NDArrayFloat, values)


def _development_frame(estimator: PDCalibrator, modelable_frame: DataFrame) -> DataFrame:
    """Selecciona la partición Desarrollo en orden estable."""
    fit_frame = modelable_frame.loc[modelable_frame[estimator.partition_column].eq(_FIT_PARTITION)]
    return fit_frame.copy(deep=True)


def _resolve_target_pd(
    estimator: PDCalibrator,
    fit_frame: DataFrame,
    *,
    pd: Any,
    np: Any,
) -> float:
    """Resuelve el ancla final; ``development_observed`` materializa la media del target Dev."""
    del pd
    if estimator.anchor_source != "development_observed":
        # Las fuentes no-Dev exigen target_pd explícito; ``_validate_runtime_config`` (al inicio de
        # ``fit``) ya rechazó ``target_pd=None`` para estas fuentes, así que aquí es un float real.
        return _normalize_float(float(cast(float, estimator.target_pd)))

    target = _binary_target_array(
        fit_frame,
        estimator.target_column,
        np=np,
        error_cls=CalibrationFitError,
        require_both_classes=True,
    )
    observed = _normalize_float(float(target.mean()))
    return observed


def _binary_target_array(
    frame: DataFrame,
    target_column: str,
    *,
    np: Any,
    error_cls: type[Exception],
    require_both_classes: bool,
) -> NDArrayFloat:
    """Devuelve target Dev como 0/1 y valida ambas clases cuando corresponde."""
    target = _numeric_array(frame[target_column], column=target_column, np=np, error_cls=error_cls)
    valid_binary = (target == 0.0) | (target == 1.0)
    if not bool(valid_binary.all()):
        observed = target[~valid_binary][0]
        raise error_cls(
            "El target de Desarrollo debe ser binario 0/1 para calibración supervisada: "
            f"valor observado={float(observed)!r}."
        )
    classes = set(float(value) for value in np.unique(target).tolist())
    if require_both_classes and classes != {0.0, 1.0}:
        raise error_cls(
            "El target de Desarrollo debe contener ambas clases 0 y 1 para calibración "
            f"supervisada; clases observadas={sorted(classes)}."
        )
    return cast(NDArrayFloat, target.astype("int64", copy=False))


def _observed_default_rate(frame: DataFrame, target_column: str, *, np: Any) -> float | None:
    """Calcula tasa observada Dev si el target es binario completo; si no, publica ``None``."""
    try:
        target = _binary_target_array(
            frame,
            target_column,
            np=np,
            error_cls=CalibrationFitError,
            require_both_classes=False,
        )
    except CalibrationFitError:
        return None
    return _normalize_float(float(target.mean()))


def _fit_intercept_offset(
    estimator: PDCalibrator,
    *,
    eta_dev: NDArrayFloat,
    target_pd: float,
    expit: Any,
    brentq: Any,
    np: Any,
) -> FitState:
    """Ajusta el offset de intercepto que iguala la media PD de Desarrollo al ancla."""
    delta, achieved, bracket, iterations = _solve_offset(
        eta_dev,
        target_pd=target_pd,
        tolerance=float(estimator.target_tolerance),
        max_iter=int(estimator.max_iter),
        expit=expit,
        brentq=brentq,
        np=np,
    )
    if abs(achieved - target_pd) > estimator.target_tolerance:
        raise CalibrationFitError(
            _solver_error_message(
                target_pd=target_pd,
                bracket=bracket,
                iterations=iterations,
                achieved_mean=achieved,
            )
        )
    _enforce_max_abs_offset(estimator, offset=delta, method="intercept_offset")
    return FitState(
        method="intercept_offset",
        target_pd=target_pd,
        offset=delta,
        slope=None,
        intercept=None,
        post_offset=None,
        isotonic_model=None,
        isotonic_knots=(),
        ties_created=0,
        bracket=bracket,
        iterations=iterations,
    )


def _fit_platt_scaling(
    estimator: PDCalibrator,
    *,
    fit_frame: DataFrame,
    eta_dev: NDArrayFloat,
    target_pd: float,
    expit: Any,
    brentq: Any,
    np: Any,
) -> FitState:
    """Ajusta Platt supervisado y reancla con un ``post_offset`` monótono."""
    logistic_regression = _import_logistic_regression()
    target = _binary_target_array(
        fit_frame,
        estimator.target_column,
        np=np,
        error_cls=CalibrationFitError,
        require_both_classes=estimator.require_both_classes_for_supervised,
    )
    try:
        model = logistic_regression(
            penalty=None,
            solver="lbfgs",
            max_iter=int(estimator.max_iter),
        )
        model.fit(eta_dev.reshape(-1, 1), target)
    except Exception as exc:
        raise CalibrationFitError(f"No se pudo ajustar platt_scaling: {exc}") from exc

    slope = _finite_scalar(model.coef_[0][0], label="slope")
    intercept = _finite_scalar(model.intercept_[0], label="intercept")
    if slope <= 0.0:
        raise CalibrationFitError(
            f"platt_scaling produjo slope <= 0, lo que invertiría el ranking: slope={slope!r}."
        )

    base_linear = intercept + (slope * eta_dev)
    post_offset, _achieved, bracket, iterations = _solve_offset(
        base_linear,
        target_pd=target_pd,
        tolerance=float(estimator.target_tolerance),
        max_iter=int(estimator.max_iter),
        expit=expit,
        brentq=brentq,
        np=np,
    )
    _enforce_max_abs_offset(estimator, offset=post_offset, method="platt_scaling")
    return FitState(
        method="platt_scaling",
        target_pd=target_pd,
        offset=None,
        slope=slope,
        intercept=intercept,
        post_offset=post_offset,
        isotonic_model=None,
        isotonic_knots=(),
        ties_created=0,
        bracket=bracket,
        iterations=iterations,
    )


def _fit_isotonic(
    estimator: PDCalibrator,
    *,
    fit_frame: DataFrame,
    eta_dev: NDArrayFloat,
    raw_pd_dev: NDArrayFloat,
    target_pd: float,
    expit: Any,
    brentq: Any,
    np: Any,
) -> FitState:
    """Ajusta isotónica no paramétrica y cuenta empates creados en Desarrollo."""
    isotonic_regression = _import_isotonic_regression()
    target = _binary_target_array(
        fit_frame,
        estimator.target_column,
        np=np,
        error_cls=CalibrationFitError,
        require_both_classes=estimator.require_both_classes_for_supervised,
    )
    try:
        model = isotonic_regression(increasing=True, out_of_bounds="clip")
        model.fit(eta_dev, target)
    except Exception as exc:
        raise CalibrationFitError(f"No se pudo ajustar isotonic: {exc}") from exc

    base_pd = _clip_probability_array(model.predict(eta_dev), np=np)
    base_linear = _logit_array(base_pd, np=np)
    post_offset, _achieved, bracket, iterations = _solve_offset(
        base_linear,
        target_pd=target_pd,
        tolerance=float(estimator.target_tolerance),
        max_iter=int(estimator.max_iter),
        expit=expit,
        brentq=brentq,
        np=np,
    )
    _enforce_max_abs_offset(estimator, offset=post_offset, method="isotonic")
    calibrated_dev = _clip_probability_array(expit(base_linear + post_offset), np=np)
    ties_created = _ties_created(raw_pd_dev, calibrated_dev, np=np)
    knots = tuple(
        (_normalize_float(float(x)), _normalize_float(float(y)))
        for x, y in zip(model.X_thresholds_, model.y_thresholds_, strict=True)
    )
    return FitState(
        method="isotonic",
        target_pd=target_pd,
        offset=None,
        slope=None,
        intercept=None,
        post_offset=post_offset,
        isotonic_model=model,
        isotonic_knots=knots,
        ties_created=ties_created,
        bracket=bracket,
        iterations=iterations,
    )


def _solve_offset(
    linear: NDArrayFloat,
    *,
    target_pd: float,
    tolerance: float,
    max_iter: int,
    expit: Any,
    brentq: Any,
    np: Any,
) -> tuple[float, float, tuple[float, float], int]:
    """Resuelve ``mean(sigmoid(linear + delta)) == target_pd`` por brentq robusto."""
    lower, upper = _offset_bracket(linear, target_pd=target_pd, np=np)

    def objective(delta: float) -> float:
        return _mean_sigmoid(linear, delta=delta, expit=expit, np=np) - target_pd

    try:
        root, result = brentq(
            objective,
            lower,
            upper,
            xtol=min(max(tolerance, 1e-15), 1.0),
            maxiter=max_iter,
            full_output=True,
            disp=False,
        )
    except Exception as exc:
        achieved = _mean_sigmoid(linear, delta=0.0, expit=expit, np=np)
        raise CalibrationFitError(
            _solver_error_message(
                target_pd=target_pd,
                bracket=(lower, upper),
                iterations=max_iter,
                achieved_mean=achieved,
            )
        ) from exc

    delta = _normalize_float(float(root))
    achieved = _normalize_float(_mean_sigmoid(linear, delta=delta, expit=expit, np=np))
    iterations = int(getattr(result, "iterations", max_iter))
    if not bool(getattr(result, "converged", False)):
        raise CalibrationFitError(
            _solver_error_message(
                target_pd=target_pd,
                bracket=(lower, upper),
                iterations=iterations,
                achieved_mean=achieved,
            )
        )
    return delta, achieved, (lower, upper), iterations


def _enforce_max_abs_offset(
    estimator: PDCalibrator,
    *,
    offset: float,
    method: CalibrationMethod,
) -> None:
    """Aplica el guard opcional del offset de reanclaje a tasa central."""
    max_abs_offset = estimator.max_abs_offset
    if max_abs_offset is None:
        return
    if abs(float(offset)) > float(max_abs_offset):
        raise CalibrationOffsetExceededError(
            offset=_normalize_float(float(offset)),
            max_abs_offset=float(max_abs_offset),
            method=method,
            partition=_FIT_PARTITION,
        )


def _offset_bracket(
    linear: NDArrayFloat,
    *,
    target_pd: float,
    np: Any,
) -> tuple[float, float]:
    """Construye bracket finito que rodea la raíz para cualquier ancla en ``(0, 1)``."""
    min_eta = float(linear.min())
    max_eta = float(linear.max())
    center = _logit_scalar(target_pd)
    lower = _normalize_float(center - max_eta - 8.0)
    upper = _normalize_float(center - min_eta + 8.0)
    if not (math.isfinite(lower) and math.isfinite(upper) and lower < upper):
        raise CalibrationFitError(
            "No se pudo construir un bracket finito para calibración: "
            f"target_pd={target_pd!r}, min_eta={min_eta!r}, max_eta={max_eta!r}."
        )
    del np
    return lower, upper


def _mean_sigmoid(linear: NDArrayFloat, *, delta: float, expit: Any, np: Any) -> float:
    """Calcula la media de ``sigmoid(linear + delta)`` tras validar finitud."""
    shifted = linear + delta
    finite = np.isfinite(shifted)
    if not bool(finite.all()):
        raise CalibrationFitError("El offset produjo predictores lineales no finitos.")
    return _normalize_float(float(expit(shifted).mean()))


def _transform_with_state(
    estimator: PDCalibrator,
    modelable_frame: DataFrame,
    *,
    state: FitState,
    pd: Any,
    np: Any,
    expit: Any,
) -> DataFrame:
    """Aplica un estado fiteado a filas modelables y devuelve columnas canónicas."""
    eta = _numeric_array(
        modelable_frame[estimator.linear_predictor_column],
        column=estimator.linear_predictor_column,
        np=np,
        error_cls=CalibrationTransformError,
    )
    pd_raw = _numeric_array(
        modelable_frame[estimator.pd_raw_column],
        column=estimator.pd_raw_column,
        np=np,
        error_cls=CalibrationTransformError,
    )
    linear_calibrated = _calibrated_linear(eta, state=state, np=np)
    pd_calibrated = _clip_probability_array(expit(linear_calibrated), np=np)

    result = pd.DataFrame(index=modelable_frame.index.copy())
    result["partition"] = modelable_frame[estimator.partition_column].copy(deep=True)
    result["target"] = modelable_frame[estimator.target_column].copy(deep=True)
    result["linear_predictor"] = pd.Series(eta, index=modelable_frame.index, dtype="float64")
    result["pd_raw"] = pd.Series(pd_raw, index=modelable_frame.index, dtype="float64")
    result["linear_predictor_calibrated"] = pd.Series(
        linear_calibrated,
        index=modelable_frame.index,
        dtype="float64",
    )
    result["pd_calibrated"] = pd.Series(
        pd_calibrated,
        index=modelable_frame.index,
        dtype="float64",
    )
    result["calibration_method"] = state.method
    result["anchor_kind"] = estimator.anchor_kind
    for column in _OUTPUT_FLOAT_COLUMNS:
        result[column] = result[column].astype("float64").map(_normalize_float).astype("float64")
    return cast(DataFrame, result.loc[:, list(_OUTPUT_COLUMNS)].copy(deep=True))


def _calibrated_linear(
    eta: NDArrayFloat,
    *,
    state: FitState,
    np: Any,
) -> NDArrayFloat:
    """Calcula el predictor lineal calibrado según el método fiteado."""
    with np.errstate(over="ignore", invalid="ignore"):
        if state.method == "intercept_offset":
            assert state.offset is not None
            linear = eta + state.offset
        elif state.method == "platt_scaling":
            assert state.slope is not None
            assert state.intercept is not None
            post_offset = 0.0 if state.post_offset is None else state.post_offset
            linear = state.intercept + (state.slope * eta) + post_offset
        else:
            if state.isotonic_model is None:
                raise CalibrationTransformError(
                    "El calibrador isotonic no conserva modelo fiteado."
                )
            post_offset = 0.0 if state.post_offset is None else state.post_offset
            base_pd = _clip_probability_array(state.isotonic_model.predict(eta), np=np)
            linear = _logit_array(base_pd, np=np) + post_offset
    finite = np.isfinite(linear)
    if not bool(finite.all()):
        observed = linear[~finite][0]
        raise CalibrationTransformError(
            "La calibración produjo predictor lineal no finito: "
            f"valor observado={float(observed)!r}."
        )
    return cast(NDArrayFloat, linear.astype("float64", copy=False))


def _state_from_estimator(estimator: PDCalibrator) -> FitState:
    """Reconstruye estado inmutable desde atributos fiteados."""
    return FitState(
        method=estimator.method_,
        target_pd=estimator.target_pd_,
        offset=estimator.offset_,
        slope=estimator.slope_,
        intercept=estimator.intercept_,
        post_offset=estimator.post_offset_,
        isotonic_model=estimator._isotonic_model_,
        isotonic_knots=estimator.isotonic_knots_,
        ties_created=estimator.ties_created_,
        bracket=(0.0, 0.0),
        iterations=0,
    )


#: Dos PD que difieren menos que esto son indistinguibles en la práctica: la diferencia es ruido de
#: coma flotante, no señal de riesgo. Ninguna cartera real distingue deudores a 1e-12 de PD.
_PD_RESOLUTION = 1e-12


def _ranking_preserved(raw: Series, calibrated: Series, *, pd: Any, np: Any) -> bool:
    """Indica si la calibración conservó el ordenamiento por riesgo del modelo.

    Es ``False`` cuando la calibración invierte el orden de dos deudores, o cuando colapsa al mismo
    valor a dos deudores que el modelo crudo SÍ distinguía (lo que hace la isotónica al aplanar
    tramos: destruye poder de discriminación y baja el AUC). Ambas cosas le importan a un validador.

    NO es ``False``, en cambio, cuando el empate lo crea la aritmética: una calibración monótona
    (``intercept_offset`` es un desplazamiento en el logit) no puede invertir el orden, pero sí
    puede mandar dos PD crudas separadas por ~1e-17 al mismo ``float64``. El check anterior
    comparaba los rangos con igualdad exacta, así que ese colapso de precisión lo reportaba como
    ranking roto: un falso positivo que alarma sin motivo y que, al depender de la aritmética de
    la plataforma, enrojecía solo en windows-3.11.

    El colapso de precisión no se silencia: sigue contándose en ``ties_created``.
    """
    raw_values = _as_float_array(pd.Series(raw, index=calibrated.index), np=np)
    calibrated_values = _as_float_array(calibrated, np=np)
    if raw_values.size != calibrated_values.size or raw_values.size < 2:
        return True

    # Orden estable por PD cruda: entre empates preexistentes se conserva el orden original, así que
    # un empate que YA venía del modelo nunca se cuenta en contra de la calibración.
    order = np.argsort(raw_values, kind="stable")
    raw_sorted = raw_values[order]
    calibrated_sorted = calibrated_values[order]

    raw_gaps = np.diff(raw_sorted)
    calibrated_gaps = np.diff(calibrated_sorted)
    scale = max(1.0, float(np.max(np.abs(calibrated_values))))
    tolerance = _PD_RESOLUTION * scale

    # Inversión: dos deudores dados vuelta. Siempre es una violación.
    if bool(np.any(calibrated_gaps < -tolerance)):
        return False

    # Colapso material: el modelo crudo los distinguía y la calibración los dejó iguales.
    collapsed = np.abs(calibrated_gaps) <= tolerance
    distinguishable = raw_gaps > _PD_RESOLUTION
    return not bool(np.any(collapsed & distinguishable))


def _ties_created(raw: Any, calibrated: Any, *, np: Any) -> int:
    """Cuenta empates adicionales creados por la transformación calibrada."""
    raw_values = _as_float_array(raw, np=np)
    calibrated_values = _as_float_array(calibrated, np=np)
    raw_ties = len(raw_values) - int(np.unique(raw_values).size)
    calibrated_ties = len(calibrated_values) - int(np.unique(calibrated_values).size)
    return max(0, calibrated_ties - raw_ties)


def _as_float_array(values: Any, *, np: Any) -> NDArrayFloat:
    """Convierte series/listas/arrays a ``float64`` finito para métricas internas."""
    if hasattr(values, "to_numpy"):
        array = values.to_numpy(dtype="float64", copy=True)
    else:
        array = np.asarray(values, dtype="float64")
    finite = np.isfinite(array)
    if not bool(finite.all()):
        raise CalibrationFitError("No se pueden calcular métricas con valores no finitos.")
    return cast(NDArrayFloat, array)


def _clip_probability_array(probabilities: Any, *, np: Any) -> NDArrayFloat:
    """Recorta probabilidades al intervalo abierto representable en float64."""
    values = np.asarray(probabilities, dtype="float64")
    finite = np.isfinite(values)
    if not bool(finite.all()):
        observed = values[~finite][0]
        raise CalibrationTransformError(
            f"La calibración produjo PD no finita: valor observado={float(observed)!r}."
        )
    lower = np.nextafter(0.0, 1.0)
    upper = np.nextafter(1.0, 0.0)
    return cast(NDArrayFloat, np.clip(values, lower, upper).astype("float64", copy=False))


def _logit_array(probabilities: NDArrayFloat, *, np: Any) -> NDArrayFloat:
    """Convierte probabilidades abiertas a logits finitos."""
    with np.errstate(divide="ignore", invalid="ignore"):
        logits = np.log(probabilities) - np.log1p(-probabilities)
    finite = np.isfinite(logits)
    if not bool(finite.all()):
        raise CalibrationFitError("La transformación logit produjo valores no finitos.")
    return cast(NDArrayFloat, logits.astype("float64", copy=False))


def _logit_scalar(probability: float) -> float:
    """Calcula logit escalar estable para una probabilidad abierta."""
    return math.log(probability) - math.log1p(-probability)


def _finite_scalar(value: object, *, label: str) -> float:
    """Convierte un escalar a float finito normalizado."""
    observed = float(cast(Any, value))
    if not math.isfinite(observed):
        raise CalibrationFitError(f"{label} no es finito: {observed!r}.")
    return _normalize_float(observed)


def _dependency_versions(*, include_scipy: bool, include_sklearn: bool) -> dict[str, str]:
    """Publica versiones de dependencias usadas por el método ejercido."""
    modules: dict[str, str] = {"numpy": "numpy", "pandas": "pandas"}
    if include_scipy:
        modules["scipy"] = "scipy"
    if include_sklearn:
        modules["scikit-learn"] = "sklearn"

    versions: dict[str, str] = {}
    for public_name, module_name in modules.items():
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
        versions[public_name] = str(getattr(module, "__version__", "unknown"))
    return {name: versions[name] for name in sorted(versions)}


def _audit_fit(estimator: PDCalibrator) -> None:
    """Registra decisiones de auditoría del ajuste completado."""
    estimator.log_decision(
        regla="calibration_anchor",
        umbral=estimator.fit_partition_,
        valor={
            "target_pd": estimator.target_pd_,
            "anchor_kind": estimator.anchor_kind_,
            "anchor_source": estimator.anchor_source_,
        },
        accion="fijar_ancla",
    )
    estimator.log_decision(
        regla="calibration_method",
        umbral=estimator.target_tolerance,
        valor={"method": estimator.method_, "n_fit": estimator.n_fit_},
        accion="ajustar_calibracion",
    )
    estimator.log_decision(
        regla="calibration_offset",
        umbral=estimator.target_tolerance,
        valor={
            "offset": estimator.offset_,
            "raw_mean_pd_dev": estimator.raw_mean_pd_dev_,
            "calibrated_mean_pd_dev": estimator.achieved_mean_pd_dev_,
        },
        accion="publicar_pd_calibrada",
    )
    if estimator.method_ == "platt_scaling":
        estimator.log_decision(
            regla="calibration_platt",
            umbral="slope>0",
            valor={
                "slope": estimator.slope_,
                "intercept": estimator.intercept_,
                "post_offset": estimator.post_offset_,
            },
            accion="preservar_ranking",
        )
    if estimator.method_ == "isotonic":
        estimator.log_decision(
            regla="calibration_isotonic",
            umbral="monotona_no_decreciente",
            valor={
                "n_knots": len(estimator.isotonic_knots_),
                "ties_created": estimator.ties_created_,
            },
            accion="registrar_empates",
        )
    estimator.log_decision(
        regla="calibration_ranking",
        umbral="rank(pd_raw)==rank(pd_calibrated)",
        valor={
            "ranking_preserved": estimator.ranking_preserved_,
            "ties_created": estimator.ties_created_,
        },
        accion="registrar_ranking",
    )


def _solver_error_message(
    *,
    target_pd: float,
    bracket: tuple[float, float],
    iterations: int,
    achieved_mean: float,
) -> str:
    """Mensaje estándar de no convergencia con datos suficientes para auditoría."""
    return (
        "No se pudo calibrar la media PD dentro de la tolerancia: "
        f"target_pd={target_pd!r}, bracket={bracket!r}, iteraciones={iterations}, "
        f"media_alcanzada={achieved_mean!r}."
    )


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` sin redondear otros valores."""
    observed = float(value)
    if observed == 0.0:
        return 0.0
    return observed
