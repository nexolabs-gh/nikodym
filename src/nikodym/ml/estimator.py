"""Wrapper de estimador del challenger ML (SDD-12 §4/§7).

:class:`MLChallenger` es el estimador **sklearn-like** que orquesta un backend intercambiable por
config (SVM / Random Forest / XGBoost / LightGBM / CatBoost) para retar al scorecard logístico
campeón sobre el mismo pipeline de datos. Hereda de
:class:`~nikodym.core.base.NikodymClassifier` (familia clasificador) y expone el contrato
``from_config`` / ``fit`` / ``predict_proba`` / ``predict_pd`` más ``get_params`` / ``set_params``
heredados (semántica sklearn, para el tuning de SDD-13). Los atributos fiteados llevan sufijo ``_``.

**Núcleo liviano (SDD-12 §9).** ``import nikodym.ml.estimator`` **no** importa
sklearn/xgboost/lightgbm/catboost/pandas/numpy: los backends se resuelven vía
:func:`resolve_backend` (import perezoso por adaptador) y ``numpy``/``pandas`` se importan dentro
de ``fit``/``predict``. Las anotaciones de DataFrame/estimador viven bajo ``TYPE_CHECKING``.

**Determinismo (SDD-12 §9).** ``fit`` recibe el ``rng`` del run (el step lo deriva de
``study.seed_manager.generator_for("ml")``); de ese ``rng`` se deriva la semilla entera del backend
(``seed_``, byte-reproducible) y el **recorte estratificado** de early stopping. Sólo los backends
GBDT usan early stopping (SVM/RF no): el recorte sale de la partición de ajuste recibida, nunca de
``holdout``/``oot`` (esas particiones el estimador no las ve: el step le pasa sólo ``desarrollo``).

**Monotonía (SDD-12 §7).** ``from_binning`` ⇒ constraint ``-1`` por variable en el espacio WoE
(WoE↑⇒PD↓, convención SDD-06 §3); ``explicit`` ⇒ mapa del usuario; ``off`` ⇒ sin constraints. Sólo
los backends con ``supports_monotone=True`` (XGB/LGBM/CatBoost) las aplican; SVM/RF las ignoran con
auditoría (``on_unsupported='warn'``) o fallan (``'error'`` ⇒ :class:`MLMonotonicError`).

**Invariantes de salida (SDD-12 §6).** ``pd_hat ∈ [0, 1]``, finita, con ``-0.0`` normalizado a
``0.0``; si el backend produce algo fuera de rango o no finito se levanta :class:`MLPredictError`
(prohibido el clipeo silencioso).

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, Self, TypeAlias, cast

from pydantic import ValidationError

from nikodym.core.base import NikodymClassifier
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import MissingDependencyError
from nikodym.ml.backends import resolve_backend
from nikodym.ml.config import (
    MLBackendName,
    MLConfig,
    MLTrainConfig,
    MonotonicConfig,
    MonotonicMode,
)
from nikodym.ml.exceptions import (
    MLConfigError,
    MLDataError,
    MLFitError,
    MLPredictError,
)

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink
    from nikodym.ml.config import (
        CatBoostParams,
        LightGBMParams,
        RandomForestParams,
        SvmParams,
        XGBoostParams,
    )

    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series[Any]
    Generator: TypeAlias = np.random.Generator
    EvalSet: TypeAlias = tuple[DataFrame, Series] | None
    BackendParams: TypeAlias = (
        SvmParams | RandomForestParams | XGBoostParams | LightGBMParams | CatBoostParams
    )
else:
    NDArrayFloat: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any
    Generator: TypeAlias = Any
    EvalSet: TypeAlias = Any
    BackendParams: TypeAlias = Any
    AuditSink: TypeAlias = Any

__all__ = ["MLChallenger"]

_ML_EXTRA_MESSAGE = "MLChallenger requiere numpy/pandas; instale nikodym[ml]."
# Backends GBDT: únicos con early stopping (nitpick A13 §7; SVM/RF no recortan validación interna).
_EARLY_STOPPING_BACKENDS: Final[frozenset[str]] = frozenset({"xgboost", "lightgbm", "catboost"})
# Constraint por variable en espacio WoE para ``from_binning`` (WoE↑⇒PD↓; SDD-06 §3, SDD-12 §7).
_WOE_MONOTONE_DIRECTION: Final[int] = -1
_POSITIVE_CLASS: Final[int] = 1


class MLChallenger(NikodymClassifier):
    """Challenger ML sklearn-like sobre backends intercambiables por config (SDD-12 §4)."""

    config_cls: ClassVar[type[MLConfig]] = MLConfig

    def __init__(
        self,
        *,
        backend: MLBackendName = "xgboost",
        hyperparameters: BackendParams | None = None,
        monotonic_mode: MonotonicMode = "from_binning",
        monotonic_explicit: dict[str, int] | None = None,
        monotonic_on_unsupported: Literal["warn", "error"] = "warn",
        validation_fraction: float = 0.2,
        early_stopping_rounds: int | None = 50,
        require_both_classes: bool = True,
        deterministic: bool = True,
        n_threads: int = 1,
    ) -> None:
        """Asigna los hiperparámetros planos sin transformarlos (semántica sklearn/``clone``)."""
        self.backend = backend
        self.hyperparameters = hyperparameters
        self.monotonic_mode = monotonic_mode
        self.monotonic_explicit = monotonic_explicit
        self.monotonic_on_unsupported = monotonic_on_unsupported
        self.validation_fraction = validation_fraction
        self.early_stopping_rounds = early_stopping_rounds
        self.require_both_classes = require_both_classes
        self.deterministic = deterministic
        self.n_threads = n_threads

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> MLChallenger:
        """Construye el challenger desde :class:`MLConfig` aplanando sus sub-configs (SDD-12 §4)."""
        if not isinstance(cfg, MLConfig):
            cfg = MLConfig.model_validate(cfg)
        return cls(
            backend=cfg.backend,
            hyperparameters=cfg.hyperparameters,
            monotonic_mode=cfg.monotonic.mode,
            monotonic_explicit=dict(cfg.monotonic.explicit),
            monotonic_on_unsupported=cfg.monotonic.on_unsupported,
            validation_fraction=cfg.train.validation_fraction,
            early_stopping_rounds=cfg.train.early_stopping_rounds,
            require_both_classes=cfg.train.require_both_classes,
            deterministic=cfg.deterministic,
            n_threads=cfg.n_threads,
        )

    def fit(
        self,
        X: DataFrame,  # noqa: N803
        y: Series,
        *,
        eval_set: EvalSet = None,
        rng: Generator | None = None,
        audit: AuditSink | None = None,
    ) -> Self:
        """Ajusta el challenger sobre ``X``/``y`` (partición de ajuste) de forma determinista.

        ``eval_set`` fija el set de early stopping (GBDT); si es ``None`` y el backend lo soporta,
        se recorta de ``X``/``y`` un set estratificado seeded (``validation_fraction``). ``rng``
        deriva la semilla del backend y el recorte; ``audit`` recibe las decisiones.
        """
        np = _import_numpy()
        pd = _import_pandas()
        if audit is not None:
            self._audit = audit
        cfg = self._resolve_config()
        # _resolve_config resuelve siempre los defaults del backend (nunca None); cf. MLConfig §5.
        params = cast(BackendParams, cfg.hyperparameters)

        frame = _as_dataframe(X, pd, context="fit")
        target = _as_target(y, frame.index, pd, context="fit")
        feature_names = _feature_names(frame)
        _validate_binary_target(target, require_both=self.require_both_classes, np=np)

        backend = resolve_backend(self.backend)
        constraints = self._derive_monotone_constraints(
            feature_names, supports_monotone=backend.supports_monotone
        )

        generator = np.random.default_rng(0) if rng is None else rng
        seed = int(generator.integers(0, 2**32 - 1))
        fit_frame, fit_target, resolved_eval = self._resolve_eval_set(
            frame, target, eval_set, generator, np=np, pd=pd
        )

        native = backend.build(
            params, seed=seed, n_threads=self.n_threads, monotone_constraints=constraints
        )
        try:
            fitted = backend.fit(
                native,
                fit_frame.loc[:, list(feature_names)],
                fit_target,
                eval_set=_eval_features(resolved_eval, feature_names),
                early_stopping_rounds=self.early_stopping_rounds,
            )
        except (ValueError, RuntimeError, ArithmeticError) as exc:
            raise MLFitError(
                f"el backend '{self.backend}' falló al ajustar (semilla={seed}): {exc}"
            ) from exc

        self.backend_ = backend
        self.estimator_ = fitted
        self.feature_names_in_ = feature_names
        self.monotone_constraints_ = () if constraints is None else constraints
        self.seed_ = seed
        self.n_threads_ = self.n_threads
        self.deterministic_ = self.deterministic
        self.classes_ = _resolve_classes(fitted, np=np)
        self.best_iteration_ = _extract_best_iteration(fitted)
        self.feature_importances_ = dict(backend.feature_importances(fitted))
        self.backend_version_ = backend.backend_version()
        return self

    def predict_proba(self, X: DataFrame) -> NDArrayFloat:  # noqa: N803
        """Devuelve la matriz ``(n, 2)`` de probabilidades validada y con ``-0.0`` normalizado."""
        self._check_fitted()
        np = _import_numpy()
        pd = _import_pandas()
        frame = _as_dataframe(X, pd, context="predict")
        _validate_prediction_columns(frame, self.feature_names_in_)
        proba = self.backend_.predict_proba(
            self.estimator_, frame.loc[:, list(self.feature_names_in_)]
        )
        return _validate_and_normalize_proba(proba, np=np)

    def predict_pd(self, X: DataFrame) -> NDArrayFloat:  # noqa: N803
        """Devuelve la PD del challenger (probabilidad de la clase ``1``) en ``[0, 1]``."""
        np = _import_numpy()
        proba = self.predict_proba(X)
        index = self._positive_class_index(np=np)
        return cast(NDArrayFloat, np.array(proba[:, index], dtype="float64", copy=True))

    # ── helpers de instancia ──────────────────────────────────────────────────────────────────
    def _resolve_config(self) -> MLConfig:
        """Reconstruye :class:`MLConfig` para reusar su validación cruzada y resolver defaults.

        Los hiperparámetros planos del estimador se re-ensamblan en el schema declarativo, que
        valida coherencia backend↔hiperparámetros, determinismo↔hilos y monotonía sin reimplementar.
        """
        try:
            return MLConfig(
                backend=self.backend,
                hyperparameters=self.hyperparameters,
                monotonic=MonotonicConfig(
                    mode=self.monotonic_mode,
                    explicit=cast(
                        "dict[str, Literal[-1, 0, 1]]", dict(self.monotonic_explicit or {})
                    ),
                    on_unsupported=self.monotonic_on_unsupported,
                ),
                train=MLTrainConfig(
                    validation_fraction=self.validation_fraction,
                    early_stopping_rounds=self.early_stopping_rounds,
                    require_both_classes=self.require_both_classes,
                ),
                deterministic=self.deterministic,
                n_threads=self.n_threads,
            )
        except ValidationError as exc:
            raise MLConfigError(
                f"hiperparámetros del challenger inválidos para backend='{self.backend}': {exc}"
            ) from exc

    def _derive_monotone_constraints(
        self, feature_names: tuple[str, ...], *, supports_monotone: bool
    ) -> tuple[int, ...] | None:
        """Traduce el modo de monotonía a la tupla de direcciones en el orden de columnas (§7)."""
        if self.monotonic_mode == "off":
            return None
        if not supports_monotone:
            # El caso on_unsupported='error' lo rechaza la validación de MLConfig en
            # _resolve_config (fuente única, se ejecuta antes en fit); aquí sólo resta el modo
            # 'warn': la constraint se ignora y se audita (SDD-12 §7).
            self.log_decision(
                regla="ml_monotonic_ignored",
                umbral=None,
                valor={"backend": self.backend, "mode": self.monotonic_mode},
                accion="ignore",
            )
            return None
        if self.monotonic_mode == "explicit":
            explicit = self.monotonic_explicit or {}
            return tuple(int(explicit.get(name, 0)) for name in feature_names)
        return tuple(_WOE_MONOTONE_DIRECTION for _ in feature_names)

    def _resolve_eval_set(
        self,
        frame: DataFrame,
        target: Series,
        eval_set: EvalSet,
        generator: Generator,
        *,
        np: Any,
        pd: Any,
    ) -> tuple[DataFrame, Series, EvalSet]:
        """Resuelve el par de ajuste y el set de early stopping (explícito o recortado, §7)."""
        if eval_set is not None:
            es_frame = _as_dataframe(eval_set[0], pd, context="fit")
            es_target = _as_target(eval_set[1], es_frame.index, pd, context="fit")
            return frame, target, (es_frame, es_target)
        if self.backend not in _EARLY_STOPPING_BACKENDS:
            return frame, target, None
        if self.validation_fraction <= 0.0 or self.early_stopping_rounds is None:
            return frame, target, None
        return _stratified_carve(frame, target, self.validation_fraction, generator, np=np)

    def _positive_class_index(self, *, np: Any) -> int:
        """Índice de la clase positiva (``1``) en ``classes_``; falla si el challenger no la vio."""
        matches = np.flatnonzero(np.asarray(self.classes_) == _POSITIVE_CLASS)
        if matches.size == 0:
            raise MLPredictError(
                f"la clase positiva ({_POSITIVE_CLASS}) no está en classes_={list(self.classes_)}."
            )
        return int(matches[0])


# ── imports perezosos (núcleo liviano) ────────────────────────────────────────────────────────
def _import_numpy() -> Any:
    """Importa numpy localmente y traduce su ausencia a un mensaje accionable."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:  # pragma: no cover - numpy es dep base de data
        raise MissingDependencyError(_ML_EXTRA_MESSAGE) from exc


def _import_pandas() -> Any:
    """Importa pandas localmente y traduce su ausencia a un mensaje accionable."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:  # pragma: no cover - pandas es dep base de data
        raise MissingDependencyError(_ML_EXTRA_MESSAGE) from exc


# ── helpers puros de datos ────────────────────────────────────────────────────────────────────
def _as_dataframe(df: object, pd: Any, *, context: Literal["fit", "predict"]) -> DataFrame:
    """Valida y copia defensivamente una entrada tabular no vacía con columnas únicas."""
    if not isinstance(df, pd.DataFrame):
        raise MLDataError(
            f"MLChallenger.{context} requiere pandas.DataFrame; tipo observado={type(df).__name__}."
        )
    if len(df.index) == 0:
        raise MLDataError(f"MLChallenger.{context} recibió un DataFrame vacío.")
    duplicated = df.columns[df.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise MLDataError(f"MLChallenger requiere columnas únicas; duplicadas: {joined}.")
    return cast(DataFrame, df.copy(deep=True))


def _as_target(y: object, index: Any, pd: Any, *, context: Literal["fit", "predict"]) -> Series:
    """Coacciona ``y`` a ``Series`` alineada con ``X`` sin mutar el objeto recibido."""
    target = y.copy(deep=True) if isinstance(y, pd.Series) else pd.Series(y, index=index)
    if len(target) != len(index):
        raise MLDataError(
            f"MLChallenger.{context}: y debe tener las filas de X "
            f"(len(y)={len(target)}, len(X)={len(index)})."
        )
    if not target.index.equals(index):
        target = target.reindex(index)
    return cast(Series, target.copy(deep=True))


def _feature_names(frame: DataFrame) -> tuple[str, ...]:
    """Devuelve los nombres de columna de features como tupla de strings estable."""
    return tuple(str(column) for column in frame.columns)


def _validate_binary_target(target: Series, *, require_both: bool, np: Any) -> None:
    """Valida target binario 0/1 sin NaN y, si ``require_both``, ambas clases presentes."""
    values = target.to_numpy()
    if bool(target.isna().any()):
        raise MLDataError("MLChallenger.fit recibió target con valores nulos en la partición.")
    if not bool(np.isin(values, (0, 1)).all()):
        observed = sorted({str(value) for value in np.unique(values)})
        raise MLDataError(f"el target del challenger debe ser 0/1; valores inválidos={observed}.")
    classes = {int(value) for value in np.unique(values)}
    if require_both and classes != {0, 1}:
        raise MLDataError(
            f"la partición de ajuste requiere ambas clases 0 y 1; observadas={sorted(classes)}."
        )


def _stratified_carve(
    frame: DataFrame,
    target: Series,
    fraction: float,
    generator: Generator,
    *,
    np: Any,
) -> tuple[DataFrame, Series, EvalSet]:
    """Recorta un set de early stopping estratificado por clase, seeded y sin solape (§7).

    Preserva el orden original dentro de cada subconjunto (posiciones ordenadas) y exige que ambos
    subconjuntos conserven las dos clases; si el recorte deja un lado vacío o de una sola clase se
    levanta :class:`MLDataError`.
    """
    values = target.to_numpy()
    eval_positions: list[Any] = []
    for label in np.unique(values):
        label_positions = np.flatnonzero(values == label)
        n_eval = round(fraction * len(label_positions))
        n_eval = min(max(n_eval, 1), len(label_positions) - 1) if len(label_positions) > 1 else 0
        if n_eval == 0:
            continue
        shuffled = generator.permutation(label_positions)
        eval_positions.append(shuffled[:n_eval])
    if not eval_positions:
        raise MLDataError(
            "el recorte de early stopping quedó vacío; baje validation_fraction o desactívelo."
        )
    eval_index = np.sort(np.concatenate(eval_positions))
    fit_index = np.setdiff1d(np.arange(len(values)), eval_index)
    fit_frame = cast(DataFrame, frame.iloc[fit_index])
    eval_frame = cast(DataFrame, frame.iloc[eval_index])
    fit_target = cast(Series, target.iloc[fit_index])
    eval_target = cast(Series, target.iloc[eval_index])
    for name, subset in (("ajuste", fit_target), ("early stopping", eval_target)):
        if len(subset) == 0 or subset.nunique() < 2:
            raise MLDataError(
                f"el recorte de early stopping dejó el set de {name} vacío o de una sola clase; "
                "baje validation_fraction o desactive el early stopping."
            )
    return fit_frame, fit_target, (eval_frame, eval_target)


def _eval_features(eval_set: EvalSet, feature_names: tuple[str, ...]) -> EvalSet:
    """Proyecta el ``eval_set`` a las columnas de features en el orden de entrenamiento."""
    if eval_set is None:
        return None
    es_frame, es_target = eval_set
    return es_frame.loc[:, list(feature_names)], es_target


def _resolve_classes(fitted: object, *, np: Any) -> NDArrayFloat:
    """Lee ``classes_`` del estimador nativo tras el ajuste."""
    classes = getattr(fitted, "classes_", None)
    if classes is None:
        raise MLFitError("el estimador nativo no expuso classes_ tras el ajuste.")
    return cast(NDArrayFloat, np.asarray(classes))


def _extract_best_iteration(fitted: object) -> int | None:
    """Extrae ``best_iteration`` del GBDT cuando existe (nombres nativos por librería), o ``None``.

    Los backends no exponen ``best_iteration`` en el Protocol común, así que se introspecciona el
    estimador nativo por los nombres canónicos: ``best_iteration_`` (LightGBM), ``best_iteration``
    (XGBoost) y ``get_best_iteration()`` (CatBoost). SVM/RF no tienen early stopping ⇒ ``None``.
    """
    for attribute in ("best_iteration_", "best_iteration"):
        value = getattr(fitted, attribute, None)
        if value is not None:
            return int(value)
    getter = getattr(fitted, "get_best_iteration", None)
    if callable(getter):
        value = getter()
        if value is not None:
            return int(value)
    return None


def _validate_prediction_columns(frame: DataFrame, required: tuple[str, ...]) -> None:
    """Valida que estén todas las columnas de features usadas en el ajuste."""
    missing = [column for column in required if column not in frame.columns]
    if missing:
        faltantes = ", ".join(f"'{column}'" for column in missing)
        raise MLPredictError(
            f"MLChallenger.predict requiere las features del ajuste; faltantes: {faltantes}."
        )


def _validate_and_normalize_proba(proba: object, *, np: Any) -> NDArrayFloat:
    """Valida forma ``(n, 2)``, finitud y rango ``[0, 1]``; normaliza ``-0.0`` (sin clipear, §6)."""
    matrix = np.asarray(proba, dtype="float64")
    if matrix.ndim != 2 or matrix.shape[1] != 2:
        raise MLPredictError(
            f"predict_proba del backend debe devolver forma (n, 2); forma observada={matrix.shape}."
        )
    if not bool(np.isfinite(matrix).all()):
        raise MLPredictError("el backend produjo probabilidades no finitas (NaN/inf).")
    if bool((matrix < 0.0).any()) or bool((matrix > 1.0).any()):
        raise MLPredictError(
            "el backend produjo probabilidades fuera de [0, 1]; prohibido el clipeo silencioso."
        )
    normalized = matrix.copy()
    normalized[normalized == 0.0] = 0.0
    return cast(NDArrayFloat, normalized)
