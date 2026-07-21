"""Estimador logístico PD con inferencia statsmodels y stepwise (SDD-08 §4/§7).

``LogisticPDModel`` consume columnas WoE ya seleccionadas por ``selection`` y ajusta una
regresión logística binaria ``target=1`` malo/default. El módulo es pesado por diseño, pero se
carga sólo bajo demanda desde ``nikodym.model.__getattr__``; ``statsmodels``, ``scipy``,
``pandas`` y ``numpy`` se importan dentro de métodos/helpers para preservar el import liviano del
paquete.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
import warnings
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias, cast

from pydantic import ValidationError

from nikodym.core.base import NikodymClassifier
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.model.config import (
    IvContributionConfig,
    ModelConfig,
    ModelEngine,
    ModelOptimizer,
    ModelPolicyAction,
    SignPolicyConfig,
    StepwiseConfig,
    StepwiseCriterion,
    StepwiseDirection,
)
from nikodym.model.exceptions import ModelFitError, ModelTransformError
from nikodym.model.results import ModelFitStatistics, StepwiseDecision

_SCORING_EXTRA_MESSAGE = (
    "LogisticPDModel requiere statsmodels/scipy/scikit-learn; instale nikodym[scoring]."
)

try:
    from sklearn.base import BaseEstimator, ClassifierMixin  # type: ignore[import-untyped]
except ModuleNotFoundError as exc:
    raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc

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

__all__ = ["LogisticPDModel"]

_PARTITION_DESARROLLO = "desarrollo"
_INTERCEPT = "const"
_COEFFICIENT_COLUMNS: tuple[str, ...] = (
    "feature",
    "woe_column",
    "beta",
    "standard_error",
    "wald_z",
    "p_value",
    "conf_low",
    "conf_high",
    "expected_sign",
    "sign_ok",
    "iv",
    "iv_contribution",
)
_IV_CONTRIBUTION_COLUMNS: tuple[str, ...] = ("feature", "woe_column", "iv", "iv_contribution")


class LogisticPDModel(ClassifierMixin, BaseEstimator, NikodymClassifier):  # type: ignore[misc]
    """Modelo logístico PD sobre columnas WoE seleccionadas."""

    config_cls: ClassVar[type[ModelConfig]] = ModelConfig

    def __init__(
        self,
        *,
        engine: ModelEngine = "logit",
        fit_intercept: bool = True,
        stepwise_direction: StepwiseDirection = "bidirectional",
        stepwise_criterion: StepwiseCriterion = "wald_pvalue",
        entry_p_value: float = 0.05,
        exit_p_value: float = 0.05,
        max_iter: int = 100,
        min_features: int = 1,
        optimizer: ModelOptimizer = "newton",
        fit_maxiter: int = 100,
        tol: float = 1e-8,
        expected_beta_sign: Literal["negative"] = "negative",
        sign_policy: ModelPolicyAction = "exclude",
        fail_on_forced_inverted: bool = True,
        iv_contribution_threshold: float = 0.90,
        iv_contribution_policy: ModelPolicyAction = "exclude",
        force_include: tuple[str, ...] = (),
        force_exclude: tuple[str, ...] = (),
        alpha: float = 0.05,
        fail_if_no_features: bool = True,
    ) -> None:
        """Asigna hiperparámetros sin transformar para preservar ``clone`` de sklearn."""
        self.engine = engine
        self.fit_intercept = fit_intercept
        self.stepwise_direction = stepwise_direction
        self.stepwise_criterion = stepwise_criterion
        self.entry_p_value = entry_p_value
        self.exit_p_value = exit_p_value
        self.max_iter = max_iter
        self.min_features = min_features
        self.optimizer = optimizer
        self.fit_maxiter = fit_maxiter
        self.tol = tol
        self.expected_beta_sign = expected_beta_sign
        self.sign_policy = sign_policy
        self.fail_on_forced_inverted = fail_on_forced_inverted
        self.iv_contribution_threshold = iv_contribution_threshold
        self.iv_contribution_policy = iv_contribution_policy
        self.force_include = force_include
        self.force_exclude = force_exclude
        self.alpha = alpha
        self.fail_if_no_features = fail_if_no_features

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> LogisticPDModel:
        """Construye ``LogisticPDModel`` desde ``ModelConfig`` y sus sub-configs."""
        if not isinstance(cfg, ModelConfig):
            cfg = ModelConfig.model_validate(cfg)
        direction = cfg.stepwise.direction if cfg.stepwise.enabled else "none"
        return cls(
            engine=cfg.engine,
            fit_intercept=cfg.fit_intercept,
            stepwise_direction=direction,
            stepwise_criterion=cfg.stepwise.criterion,
            entry_p_value=cfg.stepwise.entry_p_value,
            exit_p_value=cfg.stepwise.exit_p_value,
            max_iter=cfg.stepwise.max_iter,
            min_features=cfg.stepwise.min_features,
            optimizer=cfg.optimizer,
            fit_maxiter=cfg.fit_maxiter,
            tol=cfg.tol,
            expected_beta_sign=cfg.sign_policy.expected_beta_sign,
            sign_policy=cfg.sign_policy.action,
            fail_on_forced_inverted=cfg.sign_policy.fail_on_forced_inverted,
            iv_contribution_threshold=cfg.iv_contribution.threshold,
            iv_contribution_policy=cfg.iv_contribution.action,
            force_include=cfg.force_include,
            force_exclude=cfg.force_exclude,
            alpha=cfg.alpha,
            fail_if_no_features=cfg.fail_if_no_features,
        )

    def fit(
        self,
        X: DataFrame,  # noqa: N803
        y: Series,
        *,
        feature_names: tuple[str, ...],
        woe_columns: tuple[str, ...],
        iv_by_feature: Mapping[str, float],
        audit: AuditSink | None = None,
        sample_weight: Series | None = None,
    ) -> Self:
        """Ajusta la logística PD y el stepwise usando sólo filas de Desarrollo."""
        pd = _import_pandas()
        np = _import_numpy()
        _validate_runtime_config(self)
        if audit is not None:
            self._audit = audit

        frame = _as_dataframe(X, pd, context="fit")
        target = _as_target_series(y, frame.index, pd)
        weights = _as_weight_series(sample_weight, frame.index, pd)
        _validate_unique_columns(frame, error_cls=ModelFitError)
        candidates = _candidate_specs(
            frame=frame,
            feature_names=feature_names,
            woe_columns=woe_columns,
            iv_by_feature=iv_by_feature,
            np=np,
        )
        _validate_force_overrides(self, candidates)
        dev_frame, dev_target, dev_weights = _development_sample(
            frame=frame,
            target=target,
            sample_weight=weights,
            pd=pd,
        )
        _validate_binary_target(dev_target)
        _validate_finite_woe(dev_frame, candidates, np=np)

        final_features, trace = _run_stepwise(
            estimator=self,
            frame=dev_frame,
            target=dev_target,
            sample_weight=dev_weights,
            candidates=candidates,
            pd=pd,
            np=np,
        )
        _validate_final_feature_count(self, final_features, candidate_count=len(candidates))
        final_fit = _fit_statsmodels(
            estimator=self,
            frame=dev_frame,
            target=dev_target,
            sample_weight=dev_weights,
            features=final_features,
            candidates=candidates,
            pd=pd,
            np=np,
        )

        self.result_ = final_fit.result
        self.engine_ = self.engine
        self.feature_names_in_ = tuple(feature_names)
        self.woe_columns_in_ = tuple(woe_columns)
        self.final_features_ = final_features
        self.final_woe_columns_ = tuple(
            candidates[feature].woe_column for feature in final_features
        )
        self.params_ = final_fit.params.copy(deep=True)
        self.bse_ = final_fit.bse.copy(deep=True)
        self.pvalues_ = final_fit.pvalues.copy(deep=True)
        self.wald_z_ = final_fit.wald_z.copy(deep=True)
        self.conf_int_ = final_fit.conf_int.copy(deep=True)
        self.coef_ = _coef_array(final_fit.params, self.final_woe_columns_, np)
        self.intercept_ = _intercept_array(final_fit.params, np)
        self.classes_ = np.asarray([0, 1], dtype="int64")
        self.n_features_in_ = len(self.final_woe_columns_)
        self.fit_statistics_ = _fit_statistics(
            estimator=self,
            fit=final_fit,
            target=dev_target,
            n_features=len(final_features),
        )
        self.iv_contribution_ = _iv_contribution_frame(
            final_features=final_features,
            candidates=candidates,
            pd=pd,
        )
        self.coefficient_table_ = _coefficient_table(
            fit=final_fit,
            final_features=final_features,
            candidates=candidates,
            iv_contribution=self.iv_contribution_,
            pd=pd,
        )
        self.stepwise_trace_ = trace
        self.dependency_versions_ = _dependency_versions()
        return self

    def decision_function(self, X: DataFrame) -> Series:  # noqa: N803
        """Devuelve el predictor lineal preservando índice y orden de entrada."""
        self._check_fitted()
        pd = _import_pandas()
        np = _import_numpy()
        frame = _as_dataframe(X, pd, context="predict")
        _validate_prediction_columns(frame, self.final_woe_columns_)
        values = frame.loc[:, list(self.final_woe_columns_)].to_numpy(dtype="float64", copy=True)
        if not bool(np.isfinite(values).all()):
            raise ModelTransformError("LogisticPDModel no puede puntuar columnas WoE no finitas.")
        # El guard de finitud de abajo ES el mecanismo intencionado para detectar un predictor
        # no finito (p. ej. coeficientes ±inf). numpy emite ``RuntimeWarning: invalid value
        # encountered in matmul`` de forma dependiente de plataforma/BLAS (x86 sí, arm64 no); con
        # ``filterwarnings=error`` eso rompería el test en Linux/Windows antes de llegar al guard.
        with np.errstate(invalid="ignore", over="ignore", divide="ignore"):
            linear = values @ self.coef_.reshape(-1)
            linear = linear + float(self.intercept_[0])
        if not bool(np.isfinite(linear).all()):
            raise ModelTransformError("El predictor lineal produjo valores no finitos.")
        return cast(Series, pd.Series(linear, index=frame.index, name="linear_predictor"))

    def predict_pd(self, X: DataFrame) -> Series:  # noqa: N803
        """Devuelve PD cruda ``P(target=1)`` preservando el índice original."""
        pd = _import_pandas()
        np = _import_numpy()
        expit = _import_scipy_expit()
        linear = self.decision_function(X)
        probabilities = expit(linear.to_numpy(dtype="float64", copy=True))
        if not bool(np.isfinite(probabilities).all()):
            raise ModelTransformError("La PD cruda contiene valores no finitos.")
        return cast(Series, pd.Series(probabilities, index=linear.index, name="pd_raw"))

    def predict_proba(self, X: DataFrame) -> NDArrayFloat:  # noqa: N803
        """Devuelve probabilidades ``[P(good), P(bad)]`` con el orden de entrada."""
        np = _import_numpy()
        pd_bad = self.predict_pd(X).to_numpy(dtype="float64", copy=True)
        probabilities = np.column_stack((1.0 - pd_bad, pd_bad))
        if not bool(np.isfinite(probabilities).all()):
            raise ModelTransformError("predict_proba produjo probabilidades no finitas.")
        return cast(NDArrayFloat, probabilities)

    def predict(self, X: DataFrame) -> NDArrayInt:  # noqa: N803
        """Clasifica con umbral fijo 0.5; la calibración formal vive en SDD-10."""
        np = _import_numpy()
        return cast(NDArrayInt, np.asarray(self.predict_pd(X).ge(0.5), dtype="int64"))


@dataclass(frozen=True)
class CandidateSpec:
    """Metadata trazable de una feature candidata."""

    feature: str
    woe_column: str
    iv: float


@dataclass(frozen=True)
class FitOutput:
    """Resultado normalizado de un ajuste statsmodels."""

    result: Any
    params: Series
    bse: Series
    pvalues: Series
    wald_z: Series
    conf_int: DataFrame
    llf: float
    llnull: float
    pseudo_r2: float
    aic: float
    bic: float
    llr: float | None
    llr_p_value: float | None
    n_iterations: int | None
    converged: bool


@dataclass(frozen=True)
class ForwardEvaluation:
    """Evaluación de entrada de una candidata fuera del modelo."""

    feature: str
    p_value: float
    wald_p_value: float | None
    lr_p_value: float | None
    lr_stat: float | None
    beta: float


@dataclass(frozen=True)
class BackwardEvaluation:
    """Evaluación de salida de una variable dentro del modelo."""

    feature: str
    p_value: float
    wald_p_value: float | None
    lr_p_value: float | None
    lr_stat: float | None
    beta: float


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


def _import_statsmodels_components() -> tuple[
    Any,
    Any,
    Any,
    type[Warning],
    type[Warning],
    type[Exception],
]:
    """Importa las piezas de statsmodels usadas por el estimador."""
    try:
        discrete = importlib.import_module("statsmodels.discrete.discrete_model")
        glm_module = importlib.import_module("statsmodels.genmod.generalized_linear_model")
        families = importlib.import_module("statsmodels.genmod.families")
        exceptions = importlib.import_module("statsmodels.tools.sm_exceptions")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return (
        discrete.Logit,
        glm_module.GLM,
        families.Binomial,
        exceptions.PerfectSeparationWarning,
        exceptions.ConvergenceWarning,
        exceptions.PerfectSeparationError,
    )


def _import_scipy_chi2_sf() -> Any:
    """Importa ``scipy.stats.chi2.sf`` para LR-test."""
    try:
        stats = importlib.import_module("scipy.stats")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return stats.chi2.sf


def _import_scipy_expit() -> Any:
    """Importa ``scipy.special.expit`` para PD cruda estable."""
    try:
        special = importlib.import_module("scipy.special")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return special.expit


def _validate_runtime_config(estimator: LogisticPDModel) -> None:
    """Revalida hiperparámetros planos contra ``ModelConfig``."""
    try:
        _config_from_estimator(estimator)
    except (ConfigError, ValidationError) as exc:
        raise ConfigError(f"Hiperparámetros inválidos para LogisticPDModel: {exc}") from exc


def _config_from_estimator(estimator: LogisticPDModel) -> ModelConfig:
    """Reconstruye el config anidado desde los hiperparámetros del estimador."""
    return ModelConfig(
        engine=estimator.engine,
        fit_intercept=estimator.fit_intercept,
        optimizer=estimator.optimizer,
        fit_maxiter=estimator.fit_maxiter,
        tol=estimator.tol,
        alpha=estimator.alpha,
        stepwise=StepwiseConfig(
            enabled=estimator.stepwise_direction != "none",
            direction=estimator.stepwise_direction,
            criterion=estimator.stepwise_criterion,
            entry_p_value=estimator.entry_p_value,
            exit_p_value=estimator.exit_p_value,
            max_iter=estimator.max_iter,
            min_features=estimator.min_features,
        ),
        sign_policy=SignPolicyConfig(
            expected_beta_sign=estimator.expected_beta_sign,
            action=estimator.sign_policy,
            fail_on_forced_inverted=estimator.fail_on_forced_inverted,
        ),
        iv_contribution=IvContributionConfig(
            threshold=estimator.iv_contribution_threshold,
            action=estimator.iv_contribution_policy,
        ),
        force_include=estimator.force_include,
        force_exclude=estimator.force_exclude,
        fail_if_no_features=estimator.fail_if_no_features,
    )


def _as_dataframe(df: object, pd: Any, *, context: Literal["fit", "predict"]) -> DataFrame:
    """Valida y copia defensivamente una entrada tabular."""
    if not isinstance(df, pd.DataFrame):
        error_cls = ModelFitError if context == "fit" else ModelTransformError
        raise error_cls(
            f"LogisticPDModel.{context} requiere pandas.DataFrame; "
            f"tipo observado={type(df).__name__}."
        )
    if len(df.index) == 0:
        error_cls = ModelFitError if context == "fit" else ModelTransformError
        raise error_cls(f"LogisticPDModel.{context} recibió un DataFrame vacío.")
    return cast(DataFrame, df.copy(deep=True))


def _as_target_series(y: object, index: Index, pd: Any) -> Series:
    """Coacciona ``y`` a ``Series`` alineada con ``X`` sin mutar el objeto recibido."""
    target = y.copy(deep=True) if isinstance(y, pd.Series) else pd.Series(y, index=index)
    if len(target) != len(index):
        raise ModelFitError(
            "El target debe tener la misma cantidad de filas que X: "
            f"len(y)={len(target)}, len(X)={len(index)}."
        )
    if not target.index.equals(index):
        target = target.reindex(index)
    return cast(Series, target.copy(deep=True))


def _as_weight_series(sample_weight: object, index: Index, pd: Any) -> Series | None:
    """Coacciona pesos opcionales y valida largo/alineación."""
    if sample_weight is None:
        return None
    weights = (
        sample_weight.copy(deep=True)
        if isinstance(sample_weight, pd.Series)
        else pd.Series(sample_weight, index=index)
    )
    if len(weights) != len(index):
        raise ModelFitError(
            "sample_weight debe tener la misma cantidad de filas que X: "
            f"len(sample_weight)={len(weights)}, len(X)={len(index)}."
        )
    if not weights.index.equals(index):
        weights = weights.reindex(index)
    return cast(Series, weights.copy(deep=True))


def _validate_unique_columns(frame: DataFrame, *, error_cls: type[Exception]) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise error_cls(
            f"LogisticPDModel requiere nombres de columnas únicos; duplicadas: {joined}."
        )


def _candidate_specs(
    *,
    frame: DataFrame,
    feature_names: tuple[str, ...],
    woe_columns: tuple[str, ...],
    iv_by_feature: Mapping[str, float],
    np: Any,
) -> dict[str, CandidateSpec]:
    """Valida metadata de candidatas y devuelve un mapping ordenable por feature."""
    if len(feature_names) != len(woe_columns):
        raise ModelFitError(
            "feature_names y woe_columns deben tener el mismo largo: "
            f"len(feature_names)={len(feature_names)}, len(woe_columns)={len(woe_columns)}."
        )
    if len(set(feature_names)) != len(feature_names):
        raise ModelFitError(f"feature_names contiene duplicados: {feature_names!r}.")
    if len(set(woe_columns)) != len(woe_columns):
        raise ModelFitError(f"woe_columns contiene duplicados: {woe_columns!r}.")

    missing_columns = [column for column in woe_columns if column not in frame.columns]
    if missing_columns:
        joined = ", ".join(f"'{column}'" for column in missing_columns)
        raise ModelFitError(f"Faltan columnas WoE candidatas para fit: {joined}.")

    candidates: dict[str, CandidateSpec] = {}
    for feature, woe_column in zip(feature_names, woe_columns, strict=True):
        if feature not in iv_by_feature:
            raise ModelFitError(
                "iv_by_feature no contiene el IV consumido desde binning.summary para "
                f"feature='{feature}'."
            )
        raw_iv = iv_by_feature[feature]
        try:
            iv = float(raw_iv)
        except (TypeError, ValueError) as exc:
            raise ModelFitError(f"IV inválido para feature='{feature}': valor={raw_iv!r}.") from exc
        if not bool(np.isfinite(iv)) or iv < 0.0:
            raise ModelFitError(
                f"IV debe ser finito y no negativo: feature='{feature}', iv={iv!r}."
            )
        candidates[feature] = CandidateSpec(
            feature=feature,
            woe_column=woe_column,
            iv=_normalize_float(iv),
        )
    return {feature: candidates[feature] for feature in sorted(candidates)}


def _validate_force_overrides(
    estimator: LogisticPDModel,
    candidates: Mapping[str, CandidateSpec],
) -> None:
    """Valida que overrides de negocio apunten a features candidatas reales."""
    candidate_names = set(candidates)
    include = set(estimator.force_include)
    exclude = set(estimator.force_exclude)
    conflict = sorted(include & exclude)
    if conflict:
        raise ConfigError(f"force_include y force_exclude se contradicen: {conflict}.")
    missing = sorted((include | exclude) - candidate_names)
    if missing:
        available = ", ".join(f"'{feature}'" for feature in sorted(candidate_names))
        raise ModelFitError(
            "Los overrides de model deben referirse a features seleccionadas; "
            f"faltantes={missing}, disponibles=[{available}]."
        )


def _development_sample(
    *,
    frame: DataFrame,
    target: Series,
    sample_weight: Series | None,
    pd: Any,
) -> tuple[DataFrame, Series, Series | None]:
    """Filtra ``partition='desarrollo'`` cuando la columna existe."""
    if "partition" not in frame.columns:
        dev_mask = target.notna()
    else:
        dev_mask = frame["partition"].astype(str).eq(_PARTITION_DESARROLLO) & target.notna()
    dev_frame = frame.loc[dev_mask].copy(deep=True)
    dev_target = target.loc[dev_mask].copy(deep=True)
    dev_weight = None if sample_weight is None else sample_weight.loc[dev_mask].copy(deep=True)
    if len(dev_frame.index) == 0:
        raise ModelFitError("La partición Desarrollo no contiene filas con target no nulo.")
    del pd
    return dev_frame, dev_target, dev_weight


def _validate_binary_target(target: Series) -> None:
    """Valida target binario 0/1 con ambas clases antes de ajustar la logística."""
    invalid_mask = ~target.isin((0, 1))
    if bool(invalid_mask.any()):
        observed = sorted(str(value) for value in target.loc[invalid_mask].unique())
        raise ModelFitError(
            "El target de model debe contener sólo 0/1 en Desarrollo; "
            f"valores inválidos={observed}."
        )
    classes = set(int(value) for value in target.unique())
    if classes != {0, 1}:
        raise ModelFitError(
            "Target degenerado para model: Desarrollo requiere ambas clases 0 y 1; "
            f"clases observadas={sorted(classes)}."
        )


def _validate_finite_woe(
    frame: DataFrame,
    candidates: Mapping[str, CandidateSpec],
    *,
    np: Any,
) -> None:
    """Falla antes de statsmodels si alguna columna WoE candidata no es finita."""
    for spec in candidates.values():
        values = frame[spec.woe_column].to_numpy(dtype="float64", copy=True)
        if not bool(np.isfinite(values).all()):
            raise ModelFitError(
                "LogisticPDModel.fit recibió WoE no finita en Desarrollo: "
                f"feature='{spec.feature}', columna='{spec.woe_column}'."
            )


def _run_stepwise(
    *,
    estimator: LogisticPDModel,
    frame: DataFrame,
    target: Series,
    sample_weight: Series | None,
    candidates: Mapping[str, CandidateSpec],
    pd: Any,
    np: Any,
) -> tuple[tuple[str, ...], tuple[StepwiseDecision, ...]]:
    """Ejecuta stepwise y guardas de signo/IV hasta converger."""
    current = _initial_feature_pool(estimator, candidates)
    trace: list[StepwiseDecision] = []
    direction = estimator.stepwise_direction

    for iteration in range(1, estimator.max_iter + 1):
        sign_moved = _apply_sign_guard(
            estimator=estimator,
            current=current,
            trace=trace,
            iteration=iteration,
            frame=frame,
            target=target,
            sample_weight=sample_weight,
            candidates=candidates,
            pd=pd,
            np=np,
        )
        if sign_moved:
            current = sign_moved
            continue

        iv_moved = _apply_iv_guard(
            estimator=estimator,
            current=current,
            trace=trace,
            iteration=iteration,
            candidates=candidates,
            pd=pd,
        )
        if iv_moved:
            current = iv_moved
            continue

        moved = False
        if direction in {"forward", "bidirectional"}:
            forward_evaluation = _best_forward_candidate(
                estimator=estimator,
                current=current,
                frame=frame,
                target=target,
                sample_weight=sample_weight,
                candidates=candidates,
                pd=pd,
                np=np,
            )
            if forward_evaluation is not None and _passes_entry(estimator, forward_evaluation):
                current = tuple(sorted((*current, forward_evaluation.feature)))
                _record_stepwise_decision(
                    estimator,
                    trace,
                    iteration=iteration,
                    spec=candidates[forward_evaluation.feature],
                    action="enter",
                    criterion=estimator.stepwise_criterion,
                    p_value=forward_evaluation.p_value,
                    lr_stat=forward_evaluation.lr_stat,
                    beta=forward_evaluation.beta,
                    threshold=estimator.entry_p_value,
                    detail=_criterion_detail(
                        forward_evaluation.wald_p_value,
                        forward_evaluation.lr_p_value,
                    ),
                )
                moved = True
        if moved:
            continue

        if direction in {"backward", "bidirectional"}:
            backward_evaluation = _worst_backward_candidate(
                estimator=estimator,
                current=current,
                frame=frame,
                target=target,
                sample_weight=sample_weight,
                candidates=candidates,
                pd=pd,
                np=np,
            )
            if backward_evaluation is not None and _fails_exit(estimator, backward_evaluation):
                current = tuple(
                    feature for feature in current if feature != backward_evaluation.feature
                )
                _record_stepwise_decision(
                    estimator,
                    trace,
                    iteration=iteration,
                    spec=candidates[backward_evaluation.feature],
                    action="remove",
                    criterion=estimator.stepwise_criterion,
                    p_value=backward_evaluation.p_value,
                    lr_stat=backward_evaluation.lr_stat,
                    beta=backward_evaluation.beta,
                    threshold=estimator.exit_p_value,
                    detail=_criterion_detail(
                        backward_evaluation.wald_p_value,
                        backward_evaluation.lr_p_value,
                    ),
                )
                moved = True

        if not moved:
            return tuple(sorted(current)), tuple(trace)

    raise ModelFitError(
        "El stepwise no convergió antes de max_iter: "
        f"max_iter={estimator.max_iter}, features_actuales={tuple(sorted(current))}."
    )


def _initial_feature_pool(
    estimator: LogisticPDModel,
    candidates: Mapping[str, CandidateSpec],
) -> tuple[str, ...]:
    """Resuelve el pool inicial según la dirección configurada."""
    available = tuple(sorted(candidates))
    force_exclude = set(estimator.force_exclude)
    if estimator.stepwise_direction in {"backward", "none"}:
        return tuple(feature for feature in available if feature not in force_exclude)
    return tuple(sorted(set(estimator.force_include)))


def _best_forward_candidate(
    *,
    estimator: LogisticPDModel,
    current: tuple[str, ...],
    frame: DataFrame,
    target: Series,
    sample_weight: Series | None,
    candidates: Mapping[str, CandidateSpec],
    pd: Any,
    np: Any,
) -> ForwardEvaluation | None:
    """Escoge la mejor candidata de entrada con desempate lexicográfico."""
    outside = [feature for feature in sorted(candidates) if feature not in current]
    outside = [feature for feature in outside if feature not in estimator.force_exclude]
    if not outside:
        return None

    red_fit = None
    if estimator.stepwise_criterion in {"lr_test", "both"}:
        red_fit = _fit_statsmodels(
            estimator=estimator,
            frame=frame,
            target=target,
            sample_weight=sample_weight,
            features=current,
            candidates=candidates,
            pd=pd,
            np=np,
        )

    evaluations: list[ForwardEvaluation] = []
    for feature in outside:
        full_features = tuple(sorted((*current, feature)))
        full_fit = _fit_statsmodels(
            estimator=estimator,
            frame=frame,
            target=target,
            sample_weight=sample_weight,
            features=full_features,
            candidates=candidates,
            pd=pd,
            np=np,
        )
        woe_column = candidates[feature].woe_column
        wald_p = _finite_float(full_fit.pvalues.loc[woe_column], label=f"p-value {feature}")
        lr_p = None
        lr_stat = None
        if red_fit is not None:
            lr_stat, lr_p = _lr_test(full_fit, red_fit, df=1)
        p_value = _selection_p_value(estimator.stepwise_criterion, wald_p, lr_p)
        beta = _finite_float(full_fit.params.loc[woe_column], label=f"beta {feature}")
        evaluations.append(
            ForwardEvaluation(
                feature=feature,
                p_value=p_value,
                wald_p_value=wald_p,
                lr_p_value=lr_p,
                lr_stat=lr_stat,
                beta=beta,
            )
        )
    return min(evaluations, key=lambda item: (item.p_value, item.feature))


def _worst_backward_candidate(
    *,
    estimator: LogisticPDModel,
    current: tuple[str, ...],
    frame: DataFrame,
    target: Series,
    sample_weight: Series | None,
    candidates: Mapping[str, CandidateSpec],
    pd: Any,
    np: Any,
) -> BackwardEvaluation | None:
    """Escoge la peor variable de permanencia con desempate lexicográfico."""
    removable = [feature for feature in sorted(current) if feature not in estimator.force_include]
    if not removable:
        return None

    full_fit = _fit_statsmodels(
        estimator=estimator,
        frame=frame,
        target=target,
        sample_weight=sample_weight,
        features=current,
        candidates=candidates,
        pd=pd,
        np=np,
    )
    evaluations: list[BackwardEvaluation] = []
    for feature in removable:
        woe_column = candidates[feature].woe_column
        wald_p = _finite_float(full_fit.pvalues.loc[woe_column], label=f"p-value {feature}")
        lr_p = None
        lr_stat = None
        if estimator.stepwise_criterion in {"lr_test", "both"}:
            reduced = tuple(item for item in current if item != feature)
            red_fit = _fit_statsmodels(
                estimator=estimator,
                frame=frame,
                target=target,
                sample_weight=sample_weight,
                features=reduced,
                candidates=candidates,
                pd=pd,
                np=np,
            )
            lr_stat, lr_p = _lr_test(full_fit, red_fit, df=1)
        p_value = _selection_p_value(estimator.stepwise_criterion, wald_p, lr_p)
        beta = _finite_float(full_fit.params.loc[woe_column], label=f"beta {feature}")
        evaluations.append(
            BackwardEvaluation(
                feature=feature,
                p_value=p_value,
                wald_p_value=wald_p,
                lr_p_value=lr_p,
                lr_stat=lr_stat,
                beta=beta,
            )
        )
    return min(evaluations, key=lambda item: (-item.p_value, item.feature))


def _passes_entry(estimator: LogisticPDModel, evaluation: ForwardEvaluation) -> bool:
    """Evalúa el umbral de entrada según el criterio configurado."""
    if estimator.stepwise_criterion == "both":
        return (
            evaluation.wald_p_value is not None
            and evaluation.lr_p_value is not None
            and evaluation.wald_p_value <= estimator.entry_p_value
            and evaluation.lr_p_value <= estimator.entry_p_value
        )
    return evaluation.p_value <= estimator.entry_p_value


def _fails_exit(estimator: LogisticPDModel, evaluation: BackwardEvaluation) -> bool:
    """Evalúa el umbral de salida según el criterio configurado."""
    if estimator.stepwise_criterion == "both":
        return (
            evaluation.wald_p_value is not None
            and evaluation.lr_p_value is not None
            and (
                evaluation.wald_p_value > estimator.exit_p_value
                or evaluation.lr_p_value > estimator.exit_p_value
            )
        )
    return evaluation.p_value > estimator.exit_p_value


def _selection_p_value(
    criterion: StepwiseCriterion,
    wald_p_value: float,
    lr_p_value: float | None,
) -> float:
    """Normaliza un p-value comparable para ranking determinista."""
    if criterion == "wald_pvalue":
        return wald_p_value
    if lr_p_value is None:
        raise ModelFitError("LR-test no produjo p-value finito para el stepwise.")
    if criterion == "lr_test":
        return lr_p_value
    return max(wald_p_value, lr_p_value)


def _apply_sign_guard(
    *,
    estimator: LogisticPDModel,
    current: tuple[str, ...],
    trace: list[StepwiseDecision],
    iteration: int,
    frame: DataFrame,
    target: Series,
    sample_weight: Series | None,
    candidates: Mapping[str, CandidateSpec],
    pd: Any,
    np: Any,
) -> tuple[str, ...] | None:
    """Aplica la política de signo esperado ``beta < 0``."""
    if not current:
        return None
    fit = _fit_statsmodels(
        estimator=estimator,
        frame=frame,
        target=target,
        sample_weight=sample_weight,
        features=current,
        candidates=candidates,
        pd=pd,
        np=np,
    )
    for feature in sorted(current):
        spec = candidates[feature]
        beta = _normalize_float(_finite_float(fit.params.loc[spec.woe_column], label="beta"))
        if beta < 0.0:
            continue
        if feature in estimator.force_include and estimator.fail_on_forced_inverted:
            _record_stepwise_decision(
                estimator,
                trace,
                iteration=iteration,
                spec=spec,
                action="fail",
                criterion="sign",
                p_value=None,
                lr_stat=None,
                beta=beta,
                threshold=0.0,
                detail="force_include con beta no negativa",
            )
            raise ModelFitError(
                "force_include no puede conservar una variable con signo contrario al riesgo: "
                f"feature='{feature}', beta={beta:.12g}, esperado beta<0."
            )
        if estimator.sign_policy == "fail":
            _record_stepwise_decision(
                estimator,
                trace,
                iteration=iteration,
                spec=spec,
                action="fail",
                criterion="sign",
                p_value=None,
                lr_stat=None,
                beta=beta,
                threshold=0.0,
                detail="sign_policy=fail",
            )
            raise ModelFitError(
                f"Signo invertido en feature='{feature}': beta={beta:.12g}, esperado beta<0."
            )
        if estimator.sign_policy == "flag":
            _record_stepwise_decision(
                estimator,
                trace,
                iteration=iteration,
                spec=spec,
                action="flag",
                criterion="sign",
                p_value=None,
                lr_stat=None,
                beta=beta,
                threshold=0.0,
                detail="sign_policy=flag conserva beta no negativa",
            )
            continue
        if feature in estimator.force_include:
            raise ModelFitError(
                "sign_policy=exclude no puede excluir una variable force_include sin autorización "
                f"explícita: feature='{feature}', beta={beta:.12g}."
            )
        _record_stepwise_decision(
            estimator,
            trace,
            iteration=iteration,
            spec=spec,
            action="exclude",
            criterion="sign",
            p_value=None,
            lr_stat=None,
            beta=beta,
            threshold=0.0,
            detail="beta no negativa excluida",
        )
        return tuple(item for item in current if item != feature)
    return None


def _apply_iv_guard(
    *,
    estimator: LogisticPDModel,
    current: tuple[str, ...],
    trace: list[StepwiseDecision],
    iteration: int,
    candidates: Mapping[str, CandidateSpec],
    pd: Any,
) -> tuple[str, ...] | None:
    """Aplica el guard de concentración de IV consumido desde ``binning.summary``."""
    del pd
    if not current:
        return None
    total_iv = sum(candidates[feature].iv for feature in current)
    if total_iv == 0.0:
        if estimator.iv_contribution_policy == "flag":
            for feature in sorted(current):
                _record_stepwise_decision(
                    estimator,
                    trace,
                    iteration=iteration,
                    spec=candidates[feature],
                    action="flag",
                    criterion="iv_contribution",
                    p_value=None,
                    lr_stat=None,
                    beta=None,
                    threshold=estimator.iv_contribution_threshold,
                    detail="sum(iv)==0; guard no evaluable",
                )
            return None
        raise ModelFitError(
            "No se puede evaluar IV-contribution porque sum(iv)==0 para el modelo vigente."
        )

    exceeded = [
        (feature, _normalize_float(candidates[feature].iv / total_iv))
        for feature in sorted(current)
        if candidates[feature].iv / total_iv > estimator.iv_contribution_threshold
    ]
    if not exceeded:
        return None
    if estimator.iv_contribution_policy == "fail":
        feature, contribution = max(exceeded, key=lambda item: (item[1], item[0]))
        _record_stepwise_decision(
            estimator,
            trace,
            iteration=iteration,
            spec=candidates[feature],
            action="fail",
            criterion="iv_contribution",
            p_value=None,
            lr_stat=None,
            beta=None,
            threshold=estimator.iv_contribution_threshold,
            detail=f"iv_contribution={contribution:.6g}",
        )
        raise ModelFitError(
            "IV-contribution supera el umbral configurado: "
            f"feature='{feature}', valor={contribution:.12g}, "
            f"umbral={estimator.iv_contribution_threshold:.12g}."
        )
    if estimator.iv_contribution_policy == "flag":
        for feature, contribution in exceeded:
            _record_stepwise_decision(
                estimator,
                trace,
                iteration=iteration,
                spec=candidates[feature],
                action="flag",
                criterion="iv_contribution",
                p_value=None,
                lr_stat=None,
                beta=None,
                threshold=estimator.iv_contribution_threshold,
                detail=f"iv_contribution={contribution:.6g}",
            )
        return None

    removable = [
        (feature, value) for feature, value in exceeded if feature not in estimator.force_include
    ]
    if not removable:
        raise ModelFitError(
            "IV-contribution excedido sólo en variables force_include; no se puede excluir sin "
            "romper el override de negocio."
        )
    feature, contribution = min(removable, key=lambda item: (-item[1], item[0]))
    _record_stepwise_decision(
        estimator,
        trace,
        iteration=iteration,
        spec=candidates[feature],
        action="exclude",
        criterion="iv_contribution",
        p_value=None,
        lr_stat=None,
        beta=None,
        threshold=estimator.iv_contribution_threshold,
        detail=f"iv_contribution={contribution:.6g}",
    )
    return tuple(item for item in current if item != feature)


def _fit_statsmodels(
    *,
    estimator: LogisticPDModel,
    frame: DataFrame,
    target: Series,
    sample_weight: Series | None,
    features: tuple[str, ...],
    candidates: Mapping[str, CandidateSpec],
    pd: Any,
    np: Any,
) -> FitOutput:
    """Ajusta ``Logit``/``GLM Binomial`` y normaliza la inferencia publicada."""
    if estimator.engine == "logit" and sample_weight is not None:
        raise ModelFitError(
            "sample_weight no está soportado con engine='logit'; use engine='glm_binomial'."
        )
    y = target.astype("int64")
    exog = _design_matrix(
        frame=frame,
        features=features,
        candidates=candidates,
        fit_intercept=estimator.fit_intercept,
        pd=pd,
    )
    logit_cls, glm_cls, binomial_cls, perfect_warning, convergence_warning, perfect_error = (
        _import_statsmodels_components()
    )
    try:
        with _statsmodels_warnings_as_errors(perfect_warning, convergence_warning):
            if estimator.engine == "logit":
                model = logit_cls(y, exog, check_rank=True)
                result = model.fit(
                    method=estimator.optimizer,
                    maxiter=estimator.fit_maxiter,
                    tol=estimator.tol,
                    disp=False,
                )
            else:
                fit_kwargs: dict[str, object] = {
                    "maxiter": estimator.fit_maxiter,
                    "tol": estimator.tol,
                    "disp": False,
                }
                if sample_weight is not None:
                    model = glm_cls(
                        y,
                        exog,
                        family=binomial_cls(),
                        freq_weights=sample_weight.astype("float64"),
                    )
                else:
                    model = glm_cls(y, exog, family=binomial_cls())
                result = model.fit(**fit_kwargs)
    except (perfect_warning, convergence_warning, perfect_error) as exc:
        raise ModelFitError(
            "statsmodels reportó separación perfecta/cuasi-perfecta o no convergencia; "
            "revise bins, variables dominantes o colinealidad."
        ) from exc
    except np.linalg.LinAlgError as exc:
        raise ModelFitError(
            "statsmodels no pudo invertir la matriz del modelo; revise colinealidad/rank."
        ) from exc
    except ValueError as exc:
        raise ModelFitError(f"statsmodels rechazó la matriz de diseño: {exc}") from exc

    converged = _converged(result)
    if not converged:
        raise ModelFitError(
            "statsmodels no convergió dentro de fit_maxiter: "
            f"fit_maxiter={estimator.fit_maxiter}, engine='{estimator.engine}'."
        )
    return _normalize_fit_output(
        result=result,
        exog_columns=tuple(str(column) for column in exog.columns),
        alpha=estimator.alpha,
        engine=estimator.engine,
        pd=pd,
        np=np,
    )


def _design_matrix(
    *,
    frame: DataFrame,
    features: tuple[str, ...],
    candidates: Mapping[str, CandidateSpec],
    fit_intercept: bool,
    pd: Any,
) -> DataFrame:
    """Construye matriz exógena con constante explícita opcional."""
    columns = [candidates[feature].woe_column for feature in features]
    exog = frame.loc[:, columns].copy(deep=True) if columns else pd.DataFrame(index=frame.index)
    if fit_intercept:
        exog.insert(0, _INTERCEPT, 1.0)
    if exog.shape[1] == 0:
        raise ModelFitError("El modelo sin intercepto requiere al menos una variable WoE.")
    for column in exog.columns:
        exog[column] = exog[column].astype("float64")
    return cast(DataFrame, exog)


@contextmanager
def _statsmodels_warnings_as_errors(
    perfect_warning: type[Warning],
    convergence_warning: type[Warning],
) -> Iterator[None]:
    """Convierte sólo warnings esperados de statsmodels en excepciones locales."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "error",
            category=perfect_warning,
            module=r"statsmodels\..*",
        )
        warnings.filterwarnings(
            "error",
            category=convergence_warning,
            module=r"statsmodels\..*",
        )
        yield


def _converged(result: Any) -> bool:
    """Lee la bandera de convergencia de wrappers Logit/GLM."""
    mle_retvals = getattr(result, "mle_retvals", None)
    if isinstance(mle_retvals, dict) and "converged" in mle_retvals:
        return bool(mle_retvals["converged"])
    if hasattr(result, "converged"):
        return bool(result.converged)
    return True


def _normalize_fit_output(
    *,
    result: Any,
    exog_columns: tuple[str, ...],
    alpha: float,
    engine: ModelEngine,
    pd: Any,
    np: Any,
) -> FitOutput:
    """Extrae métricas statsmodels y falla ante cualquier valor no finito publicable."""
    params = _series_from_result(result.params, exog_columns, "params", pd)
    bse = _series_from_result(result.bse, exog_columns, "bse", pd)
    pvalues = _series_from_result(result.pvalues, exog_columns, "pvalues", pd)
    wald_z = _series_from_result(result.tvalues, exog_columns, "wald_z", pd)
    conf_int = _conf_int_frame(result.conf_int(alpha=alpha), exog_columns, pd)

    _validate_finite_series(params, "coeficientes", np)
    _validate_finite_series(bse, "errores estándar", np)
    _validate_finite_series(pvalues, "p-values", np)
    _validate_finite_series(wald_z, "Wald z", np)
    _validate_finite_frame(conf_int, "intervalos de confianza", np)

    llf = _finite_float(result.llf, label="llf")
    llnull = _finite_float(result.llnull, label="llnull")
    if engine == "logit":
        pseudo_r2 = _finite_float(result.prsquared, label="prsquared")
    else:
        pseudo_r2 = _mcfadden_from_ll(llf, llnull)
    nobs = _finite_float(result.nobs, label="nobs")
    k_params = len(params)
    aic = _normalize_float((-2.0 * llf) + (2.0 * k_params))
    bic = _normalize_float((-2.0 * llf) + (math.log(nobs) * k_params))
    df_model = max(k_params - 1, 0)
    if df_model == 0:
        llr = 0.0
        llr_p_value = None
    else:
        llr, llr_p_value = _lr_values(llf_full=llf, llf_red=llnull, df=df_model)

    return FitOutput(
        result=result,
        params=params.map(_normalize_float),
        bse=bse.map(_normalize_float),
        pvalues=pvalues.map(_normalize_float),
        wald_z=wald_z.map(_normalize_float),
        conf_int=conf_int.map(_normalize_float),
        llf=llf,
        llnull=llnull,
        pseudo_r2=pseudo_r2,
        aic=aic,
        bic=bic,
        llr=llr,
        llr_p_value=llr_p_value,
        n_iterations=_n_iterations(result),
        converged=True,
    )


def _series_from_result(value: Any, index: tuple[str, ...], label: str, pd: Any) -> Series:
    """Convierte Series/ndarray statsmodels a Series indexada por columnas exógenas."""
    if isinstance(value, pd.Series):
        series = value.copy(deep=True)
        series.index = [str(item) for item in series.index]
        return cast(Series, series.loc[list(index)].astype("float64"))
    return cast(Series, pd.Series(value, index=index, name=label, dtype="float64"))


def _conf_int_frame(value: Any, index: tuple[str, ...], pd: Any) -> DataFrame:
    """Normaliza intervalos de confianza a columnas ``lower``/``upper``."""
    if isinstance(value, pd.DataFrame):
        frame = value.copy(deep=True)
        frame.index = [str(item) for item in frame.index]
        frame = frame.loc[list(index)]
        frame.columns = ["lower", "upper"]
        return cast(DataFrame, frame.astype("float64"))
    return cast(DataFrame, pd.DataFrame(value, index=index, columns=["lower", "upper"]))


def _validate_finite_series(series: Series, label: str, np: Any) -> None:
    """Falla si una serie publicable contiene NaN/inf."""
    values = series.to_numpy(dtype="float64", copy=True)
    if not bool(np.isfinite(values).all()):
        raise ModelFitError(f"statsmodels publicó {label} no finitos.")


def _validate_finite_frame(frame: DataFrame, label: str, np: Any) -> None:
    """Falla si un DataFrame publicable contiene NaN/inf."""
    values = frame.to_numpy(dtype="float64", copy=True)
    if not bool(np.isfinite(values).all()):
        raise ModelFitError(f"statsmodels publicó {label} no finitos.")


def _n_iterations(result: Any) -> int | None:
    """Extrae contador de iteraciones cuando statsmodels lo publica."""
    mle_retvals = getattr(result, "mle_retvals", None)
    if isinstance(mle_retvals, dict):
        for key in ("iterations", "nit"):
            value = mle_retvals.get(key)
            if isinstance(value, int):
                return value
    fit_history = getattr(result, "fit_history", None)
    if isinstance(fit_history, dict) and isinstance(fit_history.get("iteration"), int):
        return cast(int, fit_history["iteration"])
    return None


def _mcfadden_from_ll(llf: float, llnull: float) -> float:
    """Calcula McFadden explícitamente desde ``llf``/``llnull``."""
    if llnull == 0.0:
        raise ModelFitError("No se puede calcular McFadden R2 porque llnull==0.")
    return _normalize_float(1.0 - (llf / llnull))


def _lr_test(full_fit: FitOutput, red_fit: FitOutput, *, df: int) -> tuple[float, float]:
    """Calcula LR-test para modelos anidados usando ``scipy.stats.chi2.sf``."""
    return _lr_values(llf_full=full_fit.llf, llf_red=red_fit.llf, df=df)


def _lr_values(*, llf_full: float, llf_red: float, df: int) -> tuple[float, float]:
    """Calcula estadístico LR y p-value finitos."""
    if df <= 0:
        raise ModelFitError(f"LR-test requiere df positivo; df={df}.")
    chi2_sf = _import_scipy_chi2_sf()
    lr_stat = _normalize_float(2.0 * (llf_full - llf_red))
    if lr_stat < -1e-10:
        raise ModelFitError(f"LR-test inválido: llf_full={llf_full:.12g} < llf_red={llf_red:.12g}.")
    lr_stat = max(lr_stat, 0.0)
    p_value = _normalize_float(float(chi2_sf(lr_stat, df)))
    if not math.isfinite(p_value):
        raise ModelFitError("LR-test produjo p-value no finito.")
    return lr_stat, p_value


def _fit_statistics(
    *,
    estimator: LogisticPDModel,
    fit: FitOutput,
    target: Series,
    n_features: int,
) -> ModelFitStatistics:
    """Construye DTO de estadísticas in-sample de Desarrollo."""
    n_events = int(target.sum())
    n_obs = len(target)
    return ModelFitStatistics(
        n_obs_dev=n_obs,
        n_events_dev=n_events,
        n_nonevents_dev=n_obs - n_events,
        log_likelihood=fit.llf,
        null_log_likelihood=fit.llnull,
        pseudo_r2_mcfadden=fit.pseudo_r2,
        aic=fit.aic,
        bic=fit.bic,
        llr=fit.llr if n_features > 0 else 0.0,
        llr_p_value=fit.llr_p_value if n_features > 0 else None,
        converged=fit.converged,
        optimizer=estimator.optimizer if estimator.engine == "logit" else "irls",
        n_iterations=fit.n_iterations,
    )


def _coef_array(params: Series, final_woe_columns: tuple[str, ...], np: Any) -> NDArrayFloat:
    """Devuelve coeficientes en shape sklearn ``(1, n_features)``."""
    values = [float(params.loc[column]) for column in final_woe_columns]
    return cast(NDArrayFloat, np.asarray([values], dtype="float64"))


def _intercept_array(params: Series, np: Any) -> NDArrayFloat:
    """Devuelve intercepto en shape sklearn ``(1,)``."""
    value = float(params.loc[_INTERCEPT]) if _INTERCEPT in params.index else 0.0
    return cast(NDArrayFloat, np.asarray([_normalize_float(value)], dtype="float64"))


def _iv_contribution_frame(
    *,
    final_features: tuple[str, ...],
    candidates: Mapping[str, CandidateSpec],
    pd: Any,
) -> DataFrame:
    """Publica IV consumido y contribución por feature final."""
    total_iv = sum(candidates[feature].iv for feature in final_features)
    rows: list[dict[str, object]] = []
    for feature in final_features:
        spec = candidates[feature]
        contribution = None if total_iv == 0.0 else _normalize_float(spec.iv / total_iv)
        rows.append(
            {
                "feature": feature,
                "woe_column": spec.woe_column,
                "iv": spec.iv,
                "iv_contribution": contribution,
            }
        )
    return cast(DataFrame, pd.DataFrame(rows, columns=_IV_CONTRIBUTION_COLUMNS))


def _coefficient_table(
    *,
    fit: FitOutput,
    final_features: tuple[str, ...],
    candidates: Mapping[str, CandidateSpec],
    iv_contribution: DataFrame,
    pd: Any,
) -> DataFrame:
    """Construye tabla auditable de coeficientes en orden estable."""
    contribution_by_feature = {
        str(row["feature"]): row["iv_contribution"]
        for row in cast("list[dict[str, object]]", iv_contribution.to_dict(orient="records"))
    }
    rows: list[dict[str, object]] = []
    if _INTERCEPT in fit.params.index:
        rows.append(_coefficient_row(fit=fit, feature="intercept", woe_column=_INTERCEPT))
    for feature in final_features:
        spec = candidates[feature]
        rows.append(
            _coefficient_row(
                fit=fit,
                feature=feature,
                woe_column=spec.woe_column,
                iv=spec.iv,
                iv_contribution=contribution_by_feature.get(feature),
            )
        )
    return cast(DataFrame, pd.DataFrame(rows, columns=_COEFFICIENT_COLUMNS))


def _coefficient_row(
    *,
    fit: FitOutput,
    feature: str,
    woe_column: str,
    iv: float | None = None,
    iv_contribution: object = None,
) -> dict[str, object]:
    """Serializa una fila de coeficientes con signo esperado."""
    beta = _normalize_float(float(fit.params.loc[woe_column]))
    expected_sign = "none" if feature == "intercept" else "negative"
    return {
        "feature": feature,
        "woe_column": woe_column,
        "beta": beta,
        "standard_error": _normalize_float(float(fit.bse.loc[woe_column])),
        "wald_z": _normalize_float(float(fit.wald_z.loc[woe_column])),
        "p_value": _normalize_float(float(fit.pvalues.loc[woe_column])),
        "conf_low": _normalize_float(float(cast(Any, fit.conf_int.loc[woe_column, "lower"]))),
        "conf_high": _normalize_float(float(cast(Any, fit.conf_int.loc[woe_column, "upper"]))),
        "expected_sign": expected_sign,
        "sign_ok": None if feature == "intercept" else beta < 0.0,
        "iv": iv,
        "iv_contribution": iv_contribution,
    }


def _validate_final_feature_count(
    estimator: LogisticPDModel,
    final_features: tuple[str, ...],
    *,
    candidate_count: int,
) -> None:
    """Aplica el mínimo de features finales sin bloquear el caso intercept-only explícito."""
    if candidate_count == 0:
        return
    if len(final_features) < estimator.min_features and estimator.fail_if_no_features:
        raise ModelFitError(
            "No quedó el mínimo de variables finales tras stepwise/signos/IV: "
            f"n_final={len(final_features)}, min_features={estimator.min_features}."
        )


def _validate_prediction_columns(frame: DataFrame, required: tuple[str, ...]) -> None:
    """Valida columnas WoE finales antes de puntuar."""
    missing = [column for column in required if column not in frame.columns]
    if missing:
        requeridas = ", ".join(f"'{column}'" for column in required)
        faltantes = ", ".join(f"'{column}'" for column in missing)
        raise ModelTransformError(
            "LogisticPDModel requiere las columnas WoE finales para predecir; "
            f"requeridas=[{requeridas}], faltantes=[{faltantes}]."
        )


def _record_stepwise_decision(
    estimator: LogisticPDModel,
    trace: list[StepwiseDecision],
    *,
    iteration: int,
    spec: CandidateSpec,
    action: Literal["enter", "remove", "keep", "flag", "exclude", "fail"],
    criterion: Literal["wald_pvalue", "lr_test", "both", "sign", "iv_contribution"],
    p_value: float | None,
    lr_stat: float | None,
    beta: float | None,
    threshold: float | None,
    detail: str,
) -> None:
    """Agrega traza y emite auditoría de decisión."""
    decision = StepwiseDecision(
        iteration=iteration,
        feature=spec.feature,
        woe_column=spec.woe_column,
        action=action,
        criterion=criterion,
        p_value=_optional_normalized(p_value),
        lr_stat=_optional_normalized(lr_stat),
        beta=_optional_normalized(beta),
        threshold=_optional_normalized(threshold),
        detail=detail,
    )
    trace.append(decision)
    estimator.log_decision(
        regla=f"model_{criterion}",
        umbral=threshold,
        valor={"feature": spec.feature, "p_value": p_value, "lr_stat": lr_stat, "beta": beta},
        accion=action,
    )


def _criterion_detail(wald_p_value: float | None, lr_p_value: float | None) -> str:
    """Texto compacto de diagnóstico para una decisión Wald/LR."""
    parts: list[str] = []
    if wald_p_value is not None:
        parts.append(f"wald_p={wald_p_value:.6g}")
    if lr_p_value is not None:
        parts.append(f"lr_p={lr_p_value:.6g}")
    return ", ".join(parts)


def _dependency_versions() -> dict[str, str]:
    """Publica versiones de dependencias que afectan inferencia/reproducibilidad."""
    modules = {
        "statsmodels": "statsmodels",
        "scikit-learn": "sklearn",
        "scipy": "scipy",
        "pandas": "pandas",
        "numpy": "numpy",
    }
    versions: dict[str, str] = {}
    for public_name, module_name in modules.items():
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
        versions[public_name] = str(getattr(module, "__version__", "unknown"))
    return {name: versions[name] for name in sorted(versions)}


def _finite_float(value: object, *, label: str) -> float:
    """Convierte un escalar a float finito normalizado."""
    try:
        candidate = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ModelFitError(f"{label} no es numérico: {value!r}.") from exc
    if not math.isfinite(candidate):
        raise ModelFitError(f"{label} no es finito: {candidate!r}.")
    return _normalize_float(candidate)


def _optional_normalized(value: float | None) -> float | None:
    """Normaliza ``-0.0`` en métricas opcionales."""
    if value is None:
        return None
    return _normalize_float(value)


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` sin redondear otros valores."""
    if value == 0.0:
        return 0.0
    return value
