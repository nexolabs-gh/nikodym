"""Adaptadores de backend del challenger ML (SDD-12 §4/§9).

Cada *backend* envuelve una librería nativa (scikit-learn ``SVC``/``RandomForestClassifier``,
``xgboost``, ``lightgbm`` o ``catboost``) tras una interfaz común, el :class:`Backend` Protocol, que
el ``MLChallenger`` (B12.4) orquesta sin conocer la librería concreta. La abstracción es
**target-agnóstica** por diseño (reusable a futuro para LGD/EAD), pero v1 solo cablea clasificación
binaria / PD.

**Núcleo liviano (SDD-12 §9).** ``import nikodym.ml.backends`` **no** importa
sklearn/xgboost/lightgbm/catboost/pandas/numpy: cada método importa su librería de forma
**perezosa** (dentro del método, vía :func:`_import_backend`). Si el *extra* del backend no está
instalado, se levanta :class:`~nikodym.core.exceptions.MissingDependencyError` nombrando el extra
exacto (``ml`` para SVM/RandomForest de sklearn; ``xgboost``/``lightgbm``/``catboost`` para los
GBDT). :func:`resolve_backend` mapea el nombre al adaptador **sin** importar ninguna librería
pesada hasta que se invoca un método.

**Monotonía (SDD-12 §4/§7).** ``supports_monotone`` distingue los backends con soporte nativo de
``monotone_constraints`` (XGBoost/LightGBM/CatBoost) de los que no lo tienen (SVM/RandomForest):
estos últimos **ignoran** las constraints sin romper (el ``MLMonotonicError`` lo decide el
challenger según ``on_unsupported``, no este módulo). Recibir ``monotone_constraints=None`` nunca
falla.

**Reproducibilidad (SDD-12 §9).** Al construir el estimador nativo se siembra por librería con el
``seed`` recibido (``random_state``/``random_seed`` según la lib) y se fijan las banderas de
single-thread deterministas: XGBoost ``n_jobs``/``verbosity=0``; LightGBM
``deterministic=True`` + ``force_row_wise=True`` + ``n_jobs`` (alias de ``num_threads``) +
``verbose=-1``; CatBoost ``thread_count`` + ``verbose=False`` + ``allow_writing_files=False``;
sklearn ``n_jobs``.
Las importancias publicadas son **nativas** (gain/split del backend), nunca SHAP (eso es SDD-14).

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, cast, runtime_checkable

from nikodym.core.exceptions import MissingDependencyError
from nikodym.ml.exceptions import MLBackendError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.ml.config import (
        CatBoostParams,
        LightGBMParams,
        MLBackendName,
        RandomForestParams,
        SvmParams,
        XGBoostParams,
    )

    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series[Any]
    EvalSet: TypeAlias = tuple[DataFrame, Series] | None
    BackendParams: TypeAlias = (
        SvmParams | RandomForestParams | XGBoostParams | LightGBMParams | CatBoostParams
    )
else:
    NDArrayFloat: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any
    EvalSet: TypeAlias = Any
    BackendParams: TypeAlias = Any

__all__ = [
    "Backend",
    "CatBoostBackend",
    "LightGBMBackend",
    "SklearnRandomForestBackend",
    "SklearnSVMBackend",
    "XGBoostBackend",
    "resolve_backend",
]


@runtime_checkable
class Backend(Protocol):
    """Contrato común de un backend de estimador nativo del challenger (SDD-12 §4).

    Un backend construye un estimador nativo sin fitear (:meth:`build`), lo ajusta
    (:meth:`fit`, con early stopping opcional para los GBDT), predice probabilidades
    (:meth:`predict_proba`), expone sus importancias nativas (:meth:`feature_importances`) y su
    versión (:meth:`backend_version`). ``supports_monotone`` indica si acepta
    ``monotone_constraints`` de forma nativa.
    """

    name: str
    supports_monotone: bool

    def build(
        self,
        params: BackendParams,
        *,
        seed: int,
        n_threads: int,
        monotone_constraints: tuple[int, ...] | None,
    ) -> object:
        """Construye el estimador nativo sin fitear, sembrado y en single-thread determinista."""
        ...

    def fit(
        self,
        estimator: object,
        X_fit: DataFrame,  # noqa: N803
        y_fit: Series,
        *,
        eval_set: EvalSet = None,
        early_stopping_rounds: int | None = None,
    ) -> object:
        """Ajusta el estimador; ``eval_set``/``early_stopping_rounds`` solo aplican a los GBDT."""
        ...

    def predict_proba(self, estimator: object, X: DataFrame) -> NDArrayFloat:  # noqa: N803
        """Devuelve la matriz de probabilidades ``(n, 2)`` del estimador fiteado."""
        ...

    def feature_importances(self, estimator: object) -> dict[str, float]:
        """Devuelve las importancias **nativas** (gain/split) por feature, nunca SHAP."""
        ...

    def backend_version(self) -> str:
        """Devuelve la versión de la librería del backend (para golden values pineados)."""
        ...


def _import_backend(module_name: str, extra: str) -> Any:
    """Importa perezosamente la librería de un backend; si falta, nombra el extra exacto.

    Parameters
    ----------
    module_name : str
        Nombre del módulo importable (p. ej. ``"xgboost"`` o ``"sklearn.svm"``).
    extra : str
        Extra de ``[project.optional-dependencies]`` que instala la librería.

    Raises
    ------
    MissingDependencyError
        Si el módulo no está instalado; el mensaje nombra ``nikodym[<extra>]``.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise MissingDependencyError(f"instale nikodym[{extra}]") from exc


class _NativeBackend:
    """Base con la predicción y la versión comunes a todos los backends nativos."""

    _version_module: str
    _extra: str

    def predict_proba(self, estimator: object, X: DataFrame) -> NDArrayFloat:  # noqa: N803
        """Delega en el ``predict_proba`` nativo del estimador fiteado (matriz ``(n, 2)``)."""
        return cast("NDArrayFloat", cast(Any, estimator).predict_proba(X))

    def backend_version(self) -> str:
        """Lee ``__version__`` de la librería del backend (import perezoso)."""
        module = _import_backend(self._version_module, self._extra)
        return str(module.__version__)


class _SklearnBackend(_NativeBackend):
    """Base de los backends de scikit-learn (SVM/RandomForest): sin monotonía ni early stopping."""

    supports_monotone: bool = False
    _version_module = "sklearn"
    _extra = "ml"

    def fit(
        self,
        estimator: object,
        X_fit: DataFrame,  # noqa: N803
        y_fit: Series,
        *,
        eval_set: EvalSet = None,
        early_stopping_rounds: int | None = None,
    ) -> object:
        """Ajusta el estimador sklearn; ignora ``eval_set``/``early_stopping_rounds`` (no GBDT)."""
        del eval_set, early_stopping_rounds
        fitted = cast(Any, estimator)
        fitted.fit(X_fit, y_fit)
        return fitted


class SklearnSVMBackend(_SklearnBackend):
    """Backend SVM de scikit-learn (``SVC`` con probabilidades por Platt); sin monotonía."""

    name = "svm"

    def build(
        self,
        params: BackendParams,
        *,
        seed: int,
        n_threads: int,
        monotone_constraints: tuple[int, ...] | None,
    ) -> object:
        """Construye un ``SVC(probability=True)`` sembrado; ignora hilos y monotonía (§4)."""
        del n_threads, monotone_constraints
        svm_module = _import_backend("sklearn.svm", self._extra)
        return svm_module.SVC(probability=True, random_state=seed, **params.model_dump())

    def feature_importances(self, estimator: object) -> dict[str, float]:
        """Devuelve ``|coef_|`` por feature (kernel lineal); vacío si el kernel no lo expone.

        Los kernels no lineales (``rbf``) no tienen ``coef_`` ni importancia nativa: se devuelve
        ``{}`` en vez de fallar, para no romper un backend válido por un artefacto secundario (la
        explicabilidad post-hoc es SDD-14). El paso lo audita.
        """
        fitted = cast(Any, estimator)
        if not hasattr(fitted, "coef_"):
            return {}
        names = fitted.feature_names_in_
        weights = fitted.coef_[0]
        return {str(name): abs(float(weight)) for name, weight in zip(names, weights, strict=True)}


class SklearnRandomForestBackend(_SklearnBackend):
    """Backend Random Forest de scikit-learn; determinista con ``random_state``, sin monotonía."""

    name = "random_forest"

    def build(
        self,
        params: BackendParams,
        *,
        seed: int,
        n_threads: int,
        monotone_constraints: tuple[int, ...] | None,
    ) -> object:
        """Construye un ``RandomForestClassifier`` sembrado; ignora monotonía (no soportada, §4)."""
        del monotone_constraints
        ensemble = _import_backend("sklearn.ensemble", self._extra)
        return ensemble.RandomForestClassifier(
            random_state=seed, n_jobs=n_threads, **params.model_dump()
        )

    def feature_importances(self, estimator: object) -> dict[str, float]:
        """Devuelve la importancia de Gini nativa (``feature_importances_``) por feature."""
        fitted = cast(Any, estimator)
        names = fitted.feature_names_in_
        importances = fitted.feature_importances_
        return {str(name): float(value) for name, value in zip(names, importances, strict=True)}


class XGBoostBackend(_NativeBackend):
    """Backend XGBoost (GBDT); soporta ``monotone_constraints`` y early stopping."""

    name = "xgboost"
    supports_monotone = True
    _version_module = "xgboost"
    _extra = "xgboost"

    def build(
        self,
        params: BackendParams,
        *,
        seed: int,
        n_threads: int,
        monotone_constraints: tuple[int, ...] | None,
    ) -> object:
        """Construye un ``XGBClassifier`` sembrado, single-thread y silencioso (``verbosity=0``)."""
        xgb = _import_backend("xgboost", self._extra)
        kwargs: dict[str, Any] = dict(params.model_dump())
        kwargs.update(random_state=seed, n_jobs=n_threads, verbosity=0)
        if monotone_constraints is not None:
            kwargs["monotone_constraints"] = tuple(monotone_constraints)
        return xgb.XGBClassifier(**kwargs)

    def fit(
        self,
        estimator: object,
        X_fit: DataFrame,  # noqa: N803
        y_fit: Series,
        *,
        eval_set: EvalSet = None,
        early_stopping_rounds: int | None = None,
    ) -> object:
        """Ajusta el GBDT; en XGBoost 2.x el early stopping se fija por ``set_params`` (§9)."""
        fitted = cast(Any, estimator)
        if eval_set is not None:
            if early_stopping_rounds is not None:
                fitted.set_params(early_stopping_rounds=early_stopping_rounds)
            fitted.fit(X_fit, y_fit, eval_set=[eval_set], verbose=False)
        else:
            fitted.fit(X_fit, y_fit, verbose=False)
        return fitted

    def feature_importances(self, estimator: object) -> dict[str, float]:
        """Devuelve la importancia nativa por ``gain``; ``0.0`` en las features no usadas."""
        booster = cast(Any, estimator).get_booster()
        scores = booster.get_score(importance_type="gain")
        return {str(name): float(scores.get(name, 0.0)) for name in booster.feature_names}


class LightGBMBackend(_NativeBackend):
    """Backend LightGBM (GBDT leaf-wise); soporta monotonía y early stopping por callback."""

    name = "lightgbm"
    supports_monotone = True
    _version_module = "lightgbm"
    _extra = "lightgbm"

    def build(
        self,
        params: BackendParams,
        *,
        seed: int,
        n_threads: int,
        monotone_constraints: tuple[int, ...] | None,
    ) -> object:
        """Construye un ``LGBMClassifier`` determinista single-thread (``n_jobs`` = hilos)."""
        lgb = _import_backend("lightgbm", self._extra)
        kwargs: dict[str, Any] = dict(params.model_dump())
        kwargs.update(
            random_state=seed,
            n_jobs=n_threads,
            deterministic=True,
            force_row_wise=True,
            verbose=-1,
        )
        if monotone_constraints is not None:
            kwargs["monotone_constraints"] = list(monotone_constraints)
        return lgb.LGBMClassifier(**kwargs)

    def fit(
        self,
        estimator: object,
        X_fit: DataFrame,  # noqa: N803
        y_fit: Series,
        *,
        eval_set: EvalSet = None,
        early_stopping_rounds: int | None = None,
    ) -> object:
        """Ajusta el GBDT; en LightGBM 4.x el early stopping va por ``callbacks`` (§9)."""
        fitted = cast(Any, estimator)
        fit_kwargs: dict[str, Any] = {}
        if eval_set is not None:
            fit_kwargs["eval_set"] = [eval_set]
            if early_stopping_rounds is not None:
                lgb = _import_backend("lightgbm", self._extra)
                fit_kwargs["callbacks"] = [lgb.early_stopping(early_stopping_rounds, verbose=False)]
        fitted.fit(X_fit, y_fit, **fit_kwargs)
        return fitted

    def feature_importances(self, estimator: object) -> dict[str, float]:
        """Devuelve la importancia nativa por ``gain`` del booster, alineada por feature."""
        booster = cast(Any, estimator).booster_
        gains = booster.feature_importance(importance_type="gain")
        names = booster.feature_name()
        return {str(name): float(gain) for name, gain in zip(names, gains, strict=True)}


class CatBoostBackend(_NativeBackend):
    """Backend CatBoost (GBDT de árboles simétricos); soporta monotonía y early stopping."""

    name = "catboost"
    supports_monotone = True
    _version_module = "catboost"
    _extra = "catboost"

    def build(
        self,
        params: BackendParams,
        *,
        seed: int,
        n_threads: int,
        monotone_constraints: tuple[int, ...] | None,
    ) -> object:
        """Construye un ``CatBoostClassifier`` sembrado, single-thread y sin escribir archivos."""
        cb = _import_backend("catboost", self._extra)
        kwargs: dict[str, Any] = dict(params.model_dump())
        kwargs.update(
            random_seed=seed,
            thread_count=n_threads,
            verbose=False,
            allow_writing_files=False,
        )
        if monotone_constraints is not None:
            kwargs["monotone_constraints"] = list(monotone_constraints)
        return cb.CatBoostClassifier(**kwargs)

    def fit(
        self,
        estimator: object,
        X_fit: DataFrame,  # noqa: N803
        y_fit: Series,
        *,
        eval_set: EvalSet = None,
        early_stopping_rounds: int | None = None,
    ) -> object:
        """Ajusta el GBDT; CatBoost recibe ``eval_set``/early stopping en ``fit`` (§9)."""
        fitted = cast(Any, estimator)
        fit_kwargs: dict[str, Any] = {"verbose": False}
        if eval_set is not None:
            fit_kwargs["eval_set"] = eval_set
            if early_stopping_rounds is not None:
                fit_kwargs["early_stopping_rounds"] = early_stopping_rounds
        fitted.fit(X_fit, y_fit, **fit_kwargs)
        return fitted

    def feature_importances(self, estimator: object) -> dict[str, float]:
        """Devuelve la importancia nativa de CatBoost alineada con ``feature_names_``."""
        fitted = cast(Any, estimator)
        importances = fitted.get_feature_importance()
        names = fitted.feature_names_
        return {str(name): float(value) for name, value in zip(names, importances, strict=True)}


_BACKENDS: dict[str, type[Backend]] = {
    "svm": SklearnSVMBackend,
    "random_forest": SklearnRandomForestBackend,
    "xgboost": XGBoostBackend,
    "lightgbm": LightGBMBackend,
    "catboost": CatBoostBackend,
}


def resolve_backend(name: MLBackendName) -> Backend:
    """Mapea el nombre de backend a su adaptador **sin** importar la librería nativa (SDD-12 §4).

    Parameters
    ----------
    name : MLBackendName
        Nombre del backend (``svm``/``random_forest``/``xgboost``/``lightgbm``/``catboost``).

    Returns
    -------
    Backend
        Instancia del adaptador; la librería pesada solo se importa al invocar un método.

    Raises
    ------
    MLBackendError
        Si el nombre no corresponde a ningún backend conocido.
    """
    try:
        backend_cls = _BACKENDS[name]
    except KeyError as exc:
        raise MLBackendError(f"backend ML desconocido: {name!r}.") from exc
    return backend_cls()
