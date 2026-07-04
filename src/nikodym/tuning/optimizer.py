"""Optimizador de hiperparámetros con Optuna (SDD-13 §4/§7).

:class:`TuningOptimizer` corre un **estudio Optuna** determinista que busca los hiperparámetros del
challenger de ``ml`` (SDD-12): un sampler seedeado (``TPESampler``/``RandomSampler``), un pruner
opcional (``median``/``none``) y una **función objetivo** que, por trial, sugiere un vector ``θ``
del espacio de búsqueda (:func:`~nikodym.tuning.search_space.suggest_params`), instancia un
:class:`~nikodym.ml.estimator.MLChallenger` vía su API sklearn-like
(``from_config``/``set_params``), lo ajusta sobre un **CV estratificado seeded y fijo entre trials**
de ``desarrollo`` (o un holdout interno) y **reúsa**
:class:`~nikodym.performance.PerformanceEvaluator` (SDD-11) para la métrica de discriminación.
**Nunca** recodifica AUC/Gini/KS ni el ``fit`` del backend: los toma prestados de SDD-11/SDD-12
(tests AST anti-reimplementación, §11).

**Anti-leakage (§7).** La búsqueda ocurre **solo** sobre las filas que el step le entrega
(``desarrollo``); ``holdout``/``oot`` jamás entran al objetivo. Las folds son **fijas entre trials**
(misma semilla) para aislar la señal de hiperparámetros de la varianza del split.

**Núcleo liviano y determinismo (§9).** ``optuna``/``pandas``/``numpy`` y el ``MLChallenger``/
``PerformanceEvaluator`` se importan **perezosamente** dentro de :meth:`TuningOptimizer.optimize`;
``import nikodym.tuning.optimizer`` no arrastra ninguno. La semilla entera
(``SeedManager.int_seed_for('tuning')``) siembra el sampler, las folds y el ``fit`` del challenger
(constante entre trials). La importancia de hiperparámetros se siembra
(``FanovaImportanceEvaluator(seed=...)``, nitpick A14(1)) pero se **excluye del assert byte-a-byte**
(best-effort; puede variar entre versiones de optuna — FALTA-DATO-TUN-2). Si falta el extra
``[tuning]`` se levanta :class:`~nikodym.core.exceptions.MissingDependencyError`
(``instale nikodym[tuning]``), no una excepción propia.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from typing import TYPE_CHECKING, Any, ClassVar, Final, TypeAlias, cast

from pydantic import ValidationError

from nikodym.core.base import BaseNikodymEstimator
from nikodym.core.exceptions import MissingDependencyError
from nikodym.tuning.config import TuningConfig
from nikodym.tuning.exceptions import (
    TuningConfigError,
    TuningDataError,
    TuningOptimizeError,
    TuningSearchSpaceError,
)
from nikodym.tuning.results import (
    SamplerMetadata,
    TuningCardSection,
    TuningResult,
    TuningTrialRecord,
)
from nikodym.tuning.search_space import suggest_params

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink
    from nikodym.ml.config import MLConfig
    from nikodym.ml.estimator import MLChallenger
    from nikodym.tuning.results import BackendParams, TrialState

    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series[Any]
    NDArrayInt: TypeAlias = np.ndarray[Any, np.dtype[np.int64]]
    Generator: TypeAlias = np.random.Generator
else:
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any
    NDArrayInt: TypeAlias = Any
    Generator: TypeAlias = Any
    AuditSink: TypeAlias = Any
    MLConfig: TypeAlias = Any
    MLChallenger: TypeAlias = Any
    BackendParams: TypeAlias = Any

__all__ = ["TuningOptimizer"]

_TUNING_EXTRA_MESSAGE = (
    "la optimización de hiperparámetros requiere optuna; instale nikodym[tuning]."
)
# Recorte a (0, 1) del PD del challenger antes del logit (coherente con SDD-12 §7 y §7.10d;
# nitpick A14(2): un único clip a (eps, 1-eps) para score y pd_raw).
_PD_CLIP_EPS: Final = 1e-9
# La métrica sólo necesita la discriminación (AUC/Gini/KS); el evaluador exige n_deciles>=2. Se usa
# el mínimo para evitar buckets constantes-fraccionarios (el DTO de decil valida min<=mean<=max, que
# la media pandas puede violar por 1 ULP en un bucket de un único valor repetido). El tuning ignora
# la tabla de deciles y lee sólo ``discriminant_records``.
_EVAL_N_DECILES: Final = 2
_EVAL_MIN_ROWS: Final = 2
_EVAL_MIN_EVENTS: Final = 1
# Partición sintética (modelable) para la fold de validación que consume el evaluador de SDD-11.
_FOLD_PARTITION: Final = "desarrollo"
_COL_PARTITION: Final = "partition"
_COL_TARGET: Final = "target"
_COL_SCORE: Final = "linear_predictor"
_COL_PD: Final = "pd_raw"


class TuningOptimizer(BaseNikodymEstimator):
    """Busca los hiperparámetros óptimos del challenger ML con Optuna (SDD-13 §4).

    Se construye con :meth:`from_config` desde una :class:`~nikodym.tuning.config.TuningConfig` y
    la :class:`~nikodym.ml.config.MLConfig` de la que **hereda** backend, fuente de features y
    monotonía (no las duplica). :meth:`optimize` corre el estudio y devuelve un
    :class:`~nikodym.tuning.results.TuningResult` con ``θ*``, la ``MLConfig`` tuneada y (opcional)
    el estimador reajustado. Los atributos fiteados llevan sufijo ``_``.
    """

    config_cls: ClassVar[type[TuningConfig]] = TuningConfig

    def __init__(
        self,
        *,
        config: TuningConfig | None = None,
        ml_config: MLConfig | None = None,
    ) -> None:
        """Asigna las configuraciones sin correr la búsqueda (sin lógica en __init__)."""
        self.config = config
        self.ml_config = ml_config

    @classmethod
    def from_config(cls, cfg: TuningConfig, ml_cfg: MLConfig) -> TuningOptimizer:  # type: ignore[override]
        """Construye el optimizador desde la config del tuning y la del challenger (SDD-13 §4).

        ``ml_cfg`` es obligatoria: sin challenger no hay hiperparámetros que tunear. Se coacciona a
        :class:`~nikodym.ml.config.MLConfig` para reusar su validación y resolver defaults.
        """
        from nikodym.ml.config import MLConfig as _MLConfig

        tuning_cfg = cfg if isinstance(cfg, TuningConfig) else TuningConfig.model_validate(cfg)
        resolved_ml = ml_cfg if isinstance(ml_cfg, _MLConfig) else _MLConfig.model_validate(ml_cfg)
        return cls(config=tuning_cfg, ml_config=resolved_ml)

    def optimize(
        self,
        X: DataFrame,  # noqa: N803
        y: Series,
        *,
        seed: int,
        monotone_directions: dict[str, int] | None = None,
        audit: AuditSink | None = None,
    ) -> TuningResult:
        """Corre el estudio Optuna y devuelve los hiperparámetros ganadores (SDD-13 §7).

        Parameters
        ----------
        X : pandas.DataFrame
            Features WoE de ``desarrollo`` (el step ya filtró la partición; nunca holdout/oot).
        y : pandas.Series
            Target binario 0/1 alineado con ``X``.
        seed : int
            Semilla ``SeedManager.int_seed_for('tuning')``; siembra sampler, folds y fit.
        monotone_directions : dict[str, int] | None
            Direcciones de monotonía fijas por variable (WoE); si se entregan, se aplican en modo
            ``explicit`` en todos los trials. ``None`` usa la monotonía de ``ml``.
        audit : AuditSink | None
            Sink opcional que recibe las decisiones del reajuste final (``best_estimator``).
        """
        if self.config is None or self.ml_config is None:
            raise TuningConfigError(
                "TuningOptimizer requiere 'config' y 'ml_config'; use from_config()."
            )
        optuna = _import_optuna()
        np = _import_numpy()
        pd = _import_pandas()
        cfg = self.config
        ml_cfg = self.ml_config
        space = cfg.resolve_search_space(ml_cfg)

        x_dev, y_dev = _prepare_dev(X, y, pd=pd, np=np)
        folds = _build_folds(y_dev, cfg=cfg, seed=seed, np=np)
        metric = cfg.objective.metric
        pruner_active = cfg.optimizer.pruner != "none"

        base_params = cast(Any, ml_cfg.hyperparameters)
        params_cls = type(base_params)

        def objective(trial: Any) -> float:
            theta = suggest_params(trial, space)
            params_model = _merge_params(params_cls, base_params, theta)
            challenger = _build_challenger(ml_cfg, params_model, monotone_directions)
            fold_values: list[float] = []
            for step_idx, (train_pos, val_pos) in enumerate(folds):
                fold_values.append(
                    _fold_metric(
                        challenger,
                        x_dev,
                        y_dev,
                        train_pos,
                        val_pos,
                        metric=metric,
                        seed=seed,
                        np=np,
                        pd=pd,
                    )
                )
                if pruner_active:
                    _report_and_maybe_prune(
                        trial, float(np.mean(fold_values)), step_idx, optuna=optuna
                    )
            mean_value = float(np.mean(fold_values))
            if not math.isfinite(mean_value):
                raise TuningOptimizeError(
                    f"la métrica objetivo '{metric}' produjo un valor no finito en el trial "
                    f"{trial.number}."
                )
            return mean_value

        sampler = _build_sampler(optuna, cfg.optimizer.sampler, seed)
        pruner = _build_pruner(optuna, cfg.optimizer.pruner)
        study = optuna.create_study(
            direction=cfg.objective.direction, sampler=sampler, pruner=pruner
        )
        study.optimize(
            objective,
            n_trials=cfg.optimizer.n_trials,
            timeout=cfg.optimizer.timeout_seconds,
            n_jobs=cfg.n_jobs,
        )

        trials = _trial_records(study, optuna=optuna)
        n_complete = sum(1 for record in trials if record.state == "complete")
        try:
            best_trial = study.best_trial
        except ValueError as exc:
            raise TuningOptimizeError(
                f"todos los trials fallaron o fueron podados (completos={n_complete}); no hay "
                "mejor trial. Revise el espacio de búsqueda o el pruner."
            ) from exc
        # El objetivo sólo devuelve valores finitos (o levanta ``TuningOptimizeError``), de modo que
        # el mejor trial completo nunca acarrea NaN/inf al ``best_value``.
        best_value = float(best_trial.value)
        best_config = _build_best_config(ml_cfg, base_params, dict(best_trial.params))
        best_params_model = cast("BackendParams", best_config.hyperparameters)
        importances = _param_importances(optuna, study, seed)

        best_estimator = None
        if cfg.refit_best:
            best_estimator = _build_challenger(best_config, best_params_model, monotone_directions)
            best_estimator.fit(x_dev, y_dev, rng=np.random.default_rng(seed), audit=audit)

        sampler_metadata = SamplerMetadata(
            sampler=cfg.optimizer.sampler,
            pruner=cfg.optimizer.pruner,
            seed=seed,
            n_trials_requested=cfg.optimizer.n_trials,
            n_trials_complete=n_complete,
            optuna_version=str(optuna.__version__),
            direction=cfg.objective.direction,
            metric=metric,
            deterministic=cfg.deterministic,
        )
        card = _build_card(cfg, ml_cfg, trials, importances, best_value, n_complete)
        result = TuningResult(
            best_hyperparameters=best_params_model,
            best_config=best_config,
            best_estimator=best_estimator,
            best_value=best_value,
            trials=trials,
            param_importances=tuple(importances.items()),
            sampler_metadata=sampler_metadata,
            card=card,
        )

        self.study_ = study
        self.best_params_ = best_params_model
        self.best_value_ = best_value
        self.best_config_ = best_config
        self.best_estimator_ = best_estimator
        self.trials_ = trials
        self.param_importances_ = result.param_importances
        self.sampler_seed_ = seed
        self.n_trials_effective_ = n_complete
        self.deterministic_ = cfg.deterministic
        return result


# ── imports perezosos (núcleo liviano, §9) ──────────────────────────────────────────────────────
def _import_optuna() -> Any:
    """Importa optuna bajo demanda y traduce su ausencia al extra ``[tuning]``."""
    try:
        return importlib.import_module("optuna")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_TUNING_EXTRA_MESSAGE) from exc


def _import_numpy() -> Any:
    """Importa numpy localmente (dep base de ``data``)."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:  # pragma: no cover - numpy es dep base de data
        raise MissingDependencyError(_TUNING_EXTRA_MESSAGE) from exc


def _import_pandas() -> Any:
    """Importa pandas localmente (dep base de ``data``)."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:  # pragma: no cover - pandas es dep base de data
        raise MissingDependencyError(_TUNING_EXTRA_MESSAGE) from exc


# ── estudio Optuna ──────────────────────────────────────────────────────────────────────────────
def _build_sampler(optuna: Any, name: str, seed: int) -> Any:
    """Construye el sampler seedeado (``tpe`` bayesiano o ``random`` baseline, §9)."""
    if name == "tpe":
        return optuna.samplers.TPESampler(seed=seed)
    return optuna.samplers.RandomSampler(seed=seed)


def _build_pruner(optuna: Any, name: str) -> Any:
    """Construye el pruner (``median`` con valores por fold o ``none`` sin poda, §5)."""
    if name == "median":
        return optuna.pruners.MedianPruner()
    return optuna.pruners.NopPruner()


def _report_and_maybe_prune(trial: Any, value: float, step: int, *, optuna: Any) -> None:
    """Reporta el valor parcial por fold y poda el trial si el pruner lo indica (§7.10e)."""
    trial.report(value, step)
    if trial.should_prune():
        raise optuna.TrialPruned


def _trial_records(study: Any, *, optuna: Any) -> tuple[TuningTrialRecord, ...]:
    """Traduce los trials de Optuna a DTOs ``TuningTrialRecord`` en orden de ejecución (§6)."""
    states = optuna.trial.TrialState
    state_names: dict[Any, TrialState] = {
        states.COMPLETE: "complete",
        states.PRUNED: "pruned",
        states.FAIL: "fail",
    }
    records: list[TuningTrialRecord] = []
    for trial in study.trials:
        state = state_names.get(trial.state, "fail")
        value = float(trial.value) if state == "complete" and trial.value is not None else None
        records.append(
            TuningTrialRecord(
                number=trial.number, params=dict(trial.params), value=value, state=state
            )
        )
    return tuple(records)


def _param_importances(optuna: Any, study: Any, seed: int) -> dict[str, float]:
    """Calcula la importancia de hiperparámetros seedeada (best-effort, excluida del golden, §9).

    Nitpick A14(1)/FALTA-DATO-TUN-2: se siembra ``FanovaImportanceEvaluator`` para reproducibilidad
    dentro de una versión de optuna, pero el resultado no se asevera byte-a-byte (puede cambiar
    entre versiones). Un estudio con muy pocos trials no admite importancia: se degrada a un mapa
    vacío en lugar de fallar la optimización.
    """
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
            evaluator = optuna.importance.FanovaImportanceEvaluator(seed=seed)
            raw = optuna.importance.get_param_importances(study, evaluator=evaluator)
    except Exception:
        return {}
    return {str(name): float(value) for name, value in raw.items()}


# ── challenger y métrica por fold (reúso SDD-12/SDD-11) ──────────────────────────────────────────
def _merge_params(params_cls: Any, base_params: Any, theta: dict[str, Any]) -> Any:
    """Sustituye en los hiperparámetros base sólo los ``θ`` sugeridos por el trial (§7.10a/b)."""
    merged = base_params.model_dump()
    merged.update(theta)
    try:
        return params_cls.model_validate(merged)
    except ValidationError as exc:
        raise TuningSearchSpaceError(
            f"el espacio de búsqueda sugirió hiperparámetros fuera de rango del backend: {exc}"
        ) from exc


def _build_challenger(
    ml_cfg: MLConfig, params_model: Any, monotone_directions: dict[str, int] | None
) -> MLChallenger:
    """Instancia el challenger (API sklearn-like SDD-12) con ``θ`` y determinismo fijo (§7.10b)."""
    from nikodym.ml.estimator import MLChallenger

    challenger = MLChallenger.from_config(ml_cfg)
    challenger.set_params(hyperparameters=params_model, deterministic=True, n_threads=1)
    if monotone_directions:
        challenger.set_params(
            monotonic_mode="explicit", monotonic_explicit=dict(monotone_directions)
        )
    return challenger


def _fold_metric(
    challenger: MLChallenger,
    x_dev: DataFrame,
    y_dev: Series,
    train_pos: NDArrayInt,
    val_pos: NDArrayInt,
    *,
    metric: str,
    seed: int,
    np: Any,
    pd: Any,
) -> float:
    """Ajusta el challenger en la fold de train y evalúa la métrica en la de val (§7.10c/d)."""
    challenger.fit(x_dev.iloc[train_pos], y_dev.iloc[train_pos], rng=np.random.default_rng(seed))
    pd_hat = challenger.predict_pd(x_dev.iloc[val_pos])
    return _discrimination_value(pd_hat, y_dev.iloc[val_pos], metric=metric, np=np, pd=pd)


def _discrimination_value(pd_hat: Any, y_val: Series, *, metric: str, np: Any, pd: Any) -> float:
    """Arma el frame analítico y lee la métrica reusando ``PerformanceEvaluator`` (SDD-11, §7.10d).

    No recodifica AUC/Gini/KS: recorta ``pd_hat`` a ``(eps, 1-eps)``, deriva ``score = logit(pd)`` y
    delega en el evaluador de SDD-11, del que lee ``discriminant_records``. Una fold no evaluable
    (una sola clase o filas insuficientes) levanta :class:`TuningDataError`.
    """
    from nikodym.performance.evaluator import PerformanceEvaluator

    pd_interior = np.clip(np.asarray(pd_hat, dtype="float64"), _PD_CLIP_EPS, 1.0 - _PD_CLIP_EPS)
    linear = np.log(pd_interior / (1.0 - pd_interior))
    frame = pd.DataFrame(
        {
            _COL_PARTITION: _FOLD_PARTITION,
            _COL_TARGET: y_val.to_numpy(),
            _COL_SCORE: linear,
            _COL_PD: pd_interior,
        },
        index=y_val.index,
    )
    evaluator = PerformanceEvaluator(
        evaluation_source="pd_calibrated",
        partitions=(_FOLD_PARTITION,),
        n_deciles=_EVAL_N_DECILES,
        min_rows_per_partition=_EVAL_MIN_ROWS,
        min_events_per_partition=_EVAL_MIN_EVENTS,
    )
    result = evaluator.evaluate(
        frame,
        score_column=_COL_SCORE,
        pd_column=_COL_PD,
        target_column=_COL_TARGET,
        partition_column=_COL_PARTITION,
    )
    record = next(r for r in result.discriminant_records if r.partition == _FOLD_PARTITION)
    value = getattr(record, metric)
    if record.status == "not_evaluable" or value is None:
        raise TuningDataError(
            "la fold de validación no es evaluable (una sola clase o filas insuficientes): "
            f"estado='{record.status}'. Baje n_folds o use strategy='holdout'."
        )
    # El evaluador de SDD-11 ya garantiza AUC/Gini/KS finitos (levanta si no lo son); la finitud del
    # promedio de folds se verifica una sola vez en el objetivo.
    return float(value)


# ── construcción de folds seeded (numpy puro; sin sklearn, §7/§11) ───────────────────────────────
def _prepare_dev(X: DataFrame, y: Series, *, pd: Any, np: Any) -> tuple[DataFrame, Series]:  # noqa: N803
    """Copia ``X``/``y``, valida target binario con ambas clases y reindexa a un rango (§6/§7.6)."""
    if not isinstance(X, pd.DataFrame):
        raise TuningDataError(
            f"TuningOptimizer.optimize requiere pandas.DataFrame; tipo={type(X).__name__}."
        )
    if len(X.index) == 0:
        raise TuningDataError("TuningOptimizer.optimize recibió un DataFrame vacío.")
    target = y.copy(deep=True) if isinstance(y, pd.Series) else pd.Series(y, index=X.index)
    if len(target) != len(X.index):
        raise TuningDataError(
            f"y debe tener las filas de X (len(y)={len(target)}, len(X)={len(X.index)})."
        )
    values = np.asarray(target.to_numpy())
    if bool(pd.isna(values).any()):
        raise TuningDataError("el target de la búsqueda contiene valores nulos.")
    classes = {int(value) for value in np.unique(values)}
    if not classes <= {0, 1}:
        raise TuningDataError(
            f"el target de la búsqueda debe ser binario 0/1; observado={sorted(classes)}."
        )
    if classes != {0, 1}:
        raise TuningDataError(
            f"la búsqueda requiere ambas clases 0 y 1 en desarrollo; observadas={sorted(classes)}."
        )
    x_dev = cast(DataFrame, X.reset_index(drop=True).copy(deep=True))
    y_dev = cast(Series, pd.Series(values, index=x_dev.index, name=getattr(target, "name", None)))
    return x_dev, y_dev


def _build_folds(
    y_dev: Series, *, cfg: TuningConfig, seed: int, np: Any
) -> list[tuple[NDArrayInt, NDArrayInt]]:
    """Construye las folds fijas entre trials (CV estratificado seeded u holdout, §7.10c)."""
    target = np.asarray(y_dev.to_numpy())
    if cfg.validation.strategy == "cv":
        return _stratified_kfold(target, cfg.validation.n_folds, seed, np=np)
    return [_stratified_holdout(target, cfg.validation.holdout_fraction, seed, np=np)]


def _stratified_kfold(
    target: NDArrayInt, n_folds: int, seed: int, *, np: Any
) -> list[tuple[NDArrayInt, NDArrayInt]]:
    """Reparte cada clase en ``n_folds`` bloques seeded; exige clases suficientes (§7.10c/§8)."""
    counts = {int(label): int((target == label).sum()) for label in np.unique(target)}
    scarce = min(counts.values())
    if scarce < n_folds:
        raise TuningDataError(
            f"la clase menos poblada tiene {scarce} filas < n_folds={n_folds}; baje n_folds o use "
            "strategy='holdout'."
        )
    rng = np.random.default_rng(seed)
    fold_of = np.empty(len(target), dtype="int64")
    for label in np.unique(target):
        positions = np.flatnonzero(target == label)
        shuffled = rng.permutation(positions)
        for fold_index, chunk in enumerate(np.array_split(shuffled, n_folds)):
            fold_of[chunk] = fold_index
    folds: list[tuple[NDArrayInt, NDArrayInt]] = []
    for fold_index in range(n_folds):
        val_pos = np.flatnonzero(fold_of == fold_index)
        train_pos = np.flatnonzero(fold_of != fold_index)
        folds.append((train_pos, val_pos))
    return folds


def _stratified_holdout(
    target: NDArrayInt, fraction: float, seed: int, *, np: Any
) -> tuple[NDArrayInt, NDArrayInt]:
    """Recorta un holdout interno estratificado seeded con ambas clases en cada lado (§7.10c/§8)."""
    rng = np.random.default_rng(seed)
    val_positions: list[NDArrayInt] = []
    for label in np.unique(target):
        positions = np.flatnonzero(target == label)
        n_val = min(max(round(fraction * len(positions)), 1), len(positions) - 1)
        if n_val <= 0:
            raise TuningDataError(
                f"la clase {int(label)} tiene {len(positions)} filas: insuficientes para un "
                "holdout interno estratificado. Baje holdout_fraction o use strategy='cv'."
            )
        val_positions.append(rng.permutation(positions)[:n_val])
    val_pos = np.sort(np.concatenate(val_positions))
    train_pos = np.setdiff1d(np.arange(len(target)), val_pos)
    return train_pos, val_pos


# ── DTOs de salida ──────────────────────────────────────────────────────────────────────────────
def _build_best_config(ml_cfg: MLConfig, base_params: Any, best_theta: dict[str, Any]) -> MLConfig:
    """Reconstruye la ``MLConfig`` tuneada sustituyendo sólo ``hyperparameters=θ*`` (§6)."""
    from nikodym.ml.config import MLConfig as _MLConfig

    merged = base_params.model_dump()
    merged.update(best_theta)
    payload = ml_cfg.model_dump()
    payload["hyperparameters"] = merged
    return _MLConfig.model_validate(payload)


def _build_card(
    cfg: TuningConfig,
    ml_cfg: MLConfig,
    trials: tuple[TuningTrialRecord, ...],
    importances: dict[str, float],
    best_value: float,
    n_complete: int,
) -> TuningCardSection:
    """Arma la tarjeta CT-2 con la curva de optimización, los trials y la importancia (§9)."""
    summary: dict[str, str | int | float | bool] = {
        "backend": ml_cfg.backend,
        "sampler": cfg.optimizer.sampler,
        "pruner": cfg.optimizer.pruner,
        "metric": cfg.objective.metric,
        "validation_strategy": cfg.validation.strategy,
        "n_trials_requested": cfg.optimizer.n_trials,
        "n_trials_complete": n_complete,
        "best_value": best_value,
        "deterministic": cfg.deterministic,
    }
    metric_sections: dict[str, Any] = {
        "optimization_history": [
            {"number": record.number, "value": record.value, "state": record.state}
            for record in trials
        ],
        "param_importances": [
            {"param": name, "importance": value} for name, value in importances.items()
        ],
        "trials": [
            {
                "number": record.number,
                "params": dict(record.params),
                "value": record.value,
                "state": record.state,
            }
            for record in trials
        ],
    }
    limitations: tuple[str, ...] = (
        "La importancia de hiperparámetros es best-effort y puede variar entre versiones de optuna "
        "(FALTA-DATO-TUN-2): excluida del assert byte-a-byte.",
    )
    if not cfg.deterministic:
        limitations = (
            *limitations,
            "Modo no determinista (n_jobs>1 o timeout): sin garantía de reproducibilidad "
            "byte-a-byte.",
        )
    return TuningCardSection(
        summary=summary,
        metric_sections=metric_sections,
        assumptions=(
            "La búsqueda ocurre sólo sobre 'desarrollo'; holdout/oot no entran al objetivo "
            "(anti-leakage).",
        ),
        limitations=limitations,
    )
