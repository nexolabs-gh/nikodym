"""Tests de los adaptadores de backend del challenger ML (SDD-12 §4/§9/§11).

Los backends de scikit-learn (SVM/RandomForest) se ejercen con la librería **real** (extra base
``[ml]``, siempre disponible en la suite): golden stump hand-verificable, determinismo,
importancias nativas y la puerta de dependencia faltante. Los backends GBDT
(``xgboost``/``lightgbm``/``catboost``) se ejercen con **fakes** inyectados por
``importlib.import_module`` para cubrir el 100% del cableado sin instalar las librerías pesadas, y
—cuando el extra está instalado— con un smoke real marcado con ``requires_<lib>`` (se salta si la
librería no está presente). Un subproceso verifica el import liviano (``import
nikodym.ml.backends`` no arrastra sklearn/xgboost/lightgbm/catboost/pandas/numpy).
"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
import types
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

import nikodym.ml.backends as backends
from nikodym.core.exceptions import MissingDependencyError
from nikodym.ml.backends import (
    Backend,
    CatBoostBackend,
    LightGBMBackend,
    SklearnRandomForestBackend,
    SklearnSVMBackend,
    XGBoostBackend,
    resolve_backend,
)
from nikodym.ml.config import (
    CatBoostParams,
    LightGBMParams,
    RandomForestParams,
    SvmParams,
    XGBoostParams,
)
from nikodym.ml.exceptions import MLBackendError

_HAS_XGBOOST = importlib.util.find_spec("xgboost") is not None
_HAS_LIGHTGBM = importlib.util.find_spec("lightgbm") is not None
_HAS_CATBOOST = importlib.util.find_spec("catboost") is not None


# ─────────────────────────── datasets deterministas ───────────────────────────


def _separable_dataset() -> tuple[pd.DataFrame, pd.Series]:
    """Dataset perfectamente separable por una feature (stump → hojas puras)."""
    features = pd.DataFrame({"woe": [0.0] * 8 + [1.0] * 8})
    target = pd.Series([0] * 8 + [1] * 8, name="target")
    return features, target


def _svm_dataset() -> tuple[pd.DataFrame, pd.Series]:
    """Dataset casi separable (con solape) para SVM: Platt CV bien planteado, sin warnings."""
    x1 = np.concatenate([np.linspace(-2.0, 0.3, 20), np.linspace(-0.3, 2.0, 20)])
    x2 = np.concatenate([np.linspace(-1.0, 1.0, 20), np.linspace(1.0, -1.0, 20)])
    features = pd.DataFrame({"ingreso__woe": x1, "mora__woe": x2})
    target = pd.Series([0] * 20 + [1] * 20, name="target")
    return features, target


# ─────────────────────────── contrato Protocol / factory ───────────────────────────


@pytest.mark.parametrize(
    ("backend", "name", "supports_monotone"),
    [
        (SklearnSVMBackend(), "svm", False),
        (SklearnRandomForestBackend(), "random_forest", False),
        (XGBoostBackend(), "xgboost", True),
        (LightGBMBackend(), "lightgbm", True),
        (CatBoostBackend(), "catboost", True),
    ],
)
def test_backend_es_runtime_checkable(backend: Backend, name: str, supports_monotone: bool) -> None:
    """Cada adaptador satisface el Protocol ``Backend`` y declara nombre/monotonía correctos."""
    assert isinstance(backend, Backend)
    assert backend.name == name
    assert backend.supports_monotone is supports_monotone


def test_objeto_arbitrario_no_es_backend() -> None:
    """Un objeto sin la interfaz no pasa el ``isinstance`` estructural."""
    assert not isinstance(object(), Backend)


@pytest.mark.parametrize(
    ("name", "backend_cls"),
    [
        ("svm", SklearnSVMBackend),
        ("random_forest", SklearnRandomForestBackend),
        ("xgboost", XGBoostBackend),
        ("lightgbm", LightGBMBackend),
        ("catboost", CatBoostBackend),
    ],
)
def test_resolve_backend_mapea_nombre(name: str, backend_cls: type[Backend]) -> None:
    """``resolve_backend`` mapea cada nombre a su adaptador sin importar librerías pesadas."""
    resolved = resolve_backend(cast(Any, name))
    assert isinstance(resolved, backend_cls)


def test_resolve_backend_desconocido_levanta() -> None:
    """Un nombre fuera del mapa levanta ``MLBackendError``."""
    with pytest.raises(MLBackendError, match="desconocido"):
        resolve_backend(cast(Any, "perceptron"))


def test_resolve_backend_no_importa_librerias_pesadas() -> None:
    """Resolver un backend GBDT no importa su librería (import perezoso hasta usar un método)."""
    code = (
        "import sys;"
        "from nikodym.ml.backends import resolve_backend;"
        "backend = resolve_backend('xgboost');"
        "assert backend.name == 'xgboost';"
        "assert 'xgboost' not in sys.modules;"
        "assert 'sklearn' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# ─────────────────────────── backends sklearn (reales) ───────────────────────────


def test_random_forest_golden_stump() -> None:
    """Stump separable: la PD de hoja pura es la proporción de malos (0.0 y 1.0), a mano."""
    features, target = _separable_dataset()
    backend = SklearnRandomForestBackend()
    estimator = backend.build(
        RandomForestParams(n_estimators=1, max_depth=1, min_samples_leaf=1),
        seed=0,
        n_threads=1,
        monotone_constraints=None,
    )
    fitted = backend.fit(estimator, features, target)
    pd_hat = backend.predict_proba(fitted, features)[:, 1]

    assert pd_hat[:8].tolist() == [0.0] * 8
    assert pd_hat[8:].tolist() == [1.0] * 8
    assert backend.feature_importances(fitted) == {"woe": 1.0}


def test_random_forest_es_determinista() -> None:
    """Dos corridas con misma semilla y single-thread producen ``predict_proba`` idéntico."""
    features, target = _separable_dataset()
    backend = SklearnRandomForestBackend()
    params = RandomForestParams(n_estimators=5, max_depth=2, min_samples_leaf=1)

    def _run() -> np.ndarray[Any, Any]:
        estimator = backend.build(params, seed=42, n_threads=1, monotone_constraints=None)
        fitted = backend.fit(estimator, features, target)
        return backend.predict_proba(fitted, features)

    np.testing.assert_array_equal(_run(), _run())


def test_random_forest_version_no_vacia() -> None:
    """``backend_version`` devuelve la versión de scikit-learn instalada."""
    version = SklearnRandomForestBackend().backend_version()
    assert isinstance(version, str)
    assert version.strip()


def test_svm_predict_proba_es_probabilidad() -> None:
    """El SVM produce una matriz ``(n, 2)`` de probabilidades que suman 1 por fila."""
    features, target = _svm_dataset()
    backend = SklearnSVMBackend()
    estimator = backend.build(
        SvmParams(kernel="linear"), seed=0, n_threads=1, monotone_constraints=None
    )
    fitted = backend.fit(estimator, features, target)
    proba = backend.predict_proba(fitted, features)

    assert proba.shape == (len(features), 2)
    assert np.all(proba >= 0.0) and np.all(proba <= 1.0)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0)


def test_svm_es_determinista() -> None:
    """El SVM sembrado es determinista entre corridas."""
    features, target = _svm_dataset()
    backend = SklearnSVMBackend()

    def _run() -> np.ndarray[Any, Any]:
        estimator = backend.build(
            SvmParams(kernel="linear"), seed=7, n_threads=1, monotone_constraints=None
        )
        fitted = backend.fit(estimator, features, target)
        return backend.predict_proba(fitted, features)

    np.testing.assert_array_equal(_run(), _run())


def test_svm_lineal_importancias_por_coef() -> None:
    """Con kernel lineal las importancias nativas son ``|coef_|`` por feature."""
    features, target = _svm_dataset()
    backend = SklearnSVMBackend()
    estimator = backend.build(
        SvmParams(kernel="linear"), seed=0, n_threads=1, monotone_constraints=None
    )
    fitted = backend.fit(estimator, features, target)
    importances = backend.feature_importances(fitted)

    assert set(importances) == {"ingreso__woe", "mora__woe"}
    assert all(value >= 0.0 for value in importances.values())


def test_svm_rbf_sin_coef_importancias_vacias() -> None:
    """Con kernel no lineal no hay ``coef_``: ``feature_importances`` devuelve ``{}`` sin romper."""
    features, target = _svm_dataset()
    backend = SklearnSVMBackend()
    estimator = backend.build(
        SvmParams(kernel="rbf"), seed=0, n_threads=1, monotone_constraints=None
    )
    fitted = backend.fit(estimator, features, target)
    assert backend.feature_importances(fitted) == {}


@pytest.mark.parametrize(
    ("backend", "params"),
    [
        (SklearnSVMBackend(), SvmParams()),
        (SklearnRandomForestBackend(), RandomForestParams(n_estimators=2, max_depth=1)),
    ],
)
def test_sklearn_ignora_monotone_constraints(backend: Backend, params: Any) -> None:
    """SVM/RandomForest ignoran ``monotone_constraints`` sin romper (no soportan monotonía, §4)."""
    features, target = _svm_dataset()
    estimator = backend.build(params, seed=0, n_threads=1, monotone_constraints=(-1, 1))
    fitted = backend.fit(estimator, features, target)
    assert backend.predict_proba(fitted, features).shape == (len(features), 2)


@pytest.mark.parametrize(
    ("backend", "module_name"),
    [
        (SklearnSVMBackend(), "sklearn.svm"),
        (SklearnRandomForestBackend(), "sklearn.ensemble"),
    ],
)
def test_sklearn_extra_faltante_levanta(
    monkeypatch: pytest.MonkeyPatch, backend: Backend, module_name: str
) -> None:
    """Sin el extra ``[ml]`` (sklearn ausente), ``build`` levanta ``MissingDependencyError``."""
    _use_missing(monkeypatch, module_name)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[ml\]"):
        backend.build(SvmParams(), seed=0, n_threads=1, monotone_constraints=None)


# ─────────────────────────── fakes de librerías GBDT ───────────────────────────


def _use_fake(
    monkeypatch: pytest.MonkeyPatch, module_name: str, fake_module: types.ModuleType
) -> None:
    """Inyecta un módulo falso como resultado de ``import_module`` para ``module_name``."""
    real_import = importlib.import_module

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == module_name:
            return fake_module
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(backends.importlib, "import_module", fake_import)


def _use_missing(monkeypatch: pytest.MonkeyPatch, module_name: str) -> None:
    """Simula la ausencia de una librería: ``import_module`` levanta ``ModuleNotFoundError``."""
    real_import = importlib.import_module

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == module_name:
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(backends.importlib, "import_module", fake_import)


class _FakeXGBBooster:
    def __init__(self, feature_names: list[str], gain_scores: dict[str, float]) -> None:
        self.feature_names = feature_names
        self._gain_scores = gain_scores

    def get_score(self, importance_type: str) -> dict[str, float]:
        assert importance_type == "gain"
        return dict(self._gain_scores)


class _FakeXGBClassifier:
    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.set_params_calls: dict[str, Any] = {}
        self.fit_kwargs: dict[str, Any] | None = None

    def set_params(self, **kwargs: Any) -> _FakeXGBClassifier:
        self.set_params_calls.update(kwargs)
        return self

    def fit(self, features: Any, target: Any, **kwargs: Any) -> _FakeXGBClassifier:
        del features, target
        self.fit_kwargs = kwargs
        return self

    def predict_proba(self, features: Any) -> np.ndarray[Any, Any]:
        return np.tile((0.4, 0.6), (len(features), 1))

    def get_booster(self) -> _FakeXGBBooster:
        return _FakeXGBBooster(["f0", "f1"], {"f0": 3.0})


class _FakeLGBMBooster:
    def __init__(self, names: list[str], gains: list[float]) -> None:
        self._names = names
        self._gains = gains

    def feature_importance(self, importance_type: str) -> list[float]:
        assert importance_type == "gain"
        return list(self._gains)

    def feature_name(self) -> list[str]:
        return list(self._names)


class _FakeLGBMClassifier:
    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.fit_kwargs: dict[str, Any] | None = None
        self.booster_ = _FakeLGBMBooster(["f0", "f1"], [1.0, 2.0])

    def fit(self, features: Any, target: Any, **kwargs: Any) -> _FakeLGBMClassifier:
        del features, target
        self.fit_kwargs = kwargs
        return self

    def predict_proba(self, features: Any) -> np.ndarray[Any, Any]:
        return np.tile((0.3, 0.7), (len(features), 1))


class _FakeCatBoostClassifier:
    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.fit_kwargs: dict[str, Any] | None = None
        self.feature_names_ = ["f0", "f1"]

    def fit(self, features: Any, target: Any, **kwargs: Any) -> _FakeCatBoostClassifier:
        del features, target
        self.fit_kwargs = kwargs
        return self

    def predict_proba(self, features: Any) -> np.ndarray[Any, Any]:
        return np.tile((0.2, 0.8), (len(features), 1))

    def get_feature_importance(self) -> list[float]:
        return [10.0, 20.0]


def _fake_early_stopping(stopping_rounds: int, verbose: bool = True) -> tuple[str, int, bool]:
    return ("early_stopping", stopping_rounds, verbose)


def _fake_xgb_module() -> types.ModuleType:
    module = types.ModuleType("xgboost")
    module.XGBClassifier = _FakeXGBClassifier  # type: ignore[attr-defined]
    module.__version__ = "2.1.0-fake"  # type: ignore[attr-defined]
    return module


def _fake_lgb_module() -> types.ModuleType:
    module = types.ModuleType("lightgbm")
    module.LGBMClassifier = _FakeLGBMClassifier  # type: ignore[attr-defined]
    module.early_stopping = _fake_early_stopping  # type: ignore[attr-defined]
    module.__version__ = "4.3.0-fake"  # type: ignore[attr-defined]
    return module


def _fake_catboost_module() -> types.ModuleType:
    module = types.ModuleType("catboost")
    module.CatBoostClassifier = _FakeCatBoostClassifier  # type: ignore[attr-defined]
    module.__version__ = "1.2.5-fake"  # type: ignore[attr-defined]
    return module


_TINY = pd.DataFrame({"f0": [0.0, 1.0, 0.0], "f1": [1.0, 0.0, 1.0]})
_TINY_TARGET = pd.Series([0, 1, 0], name="target")


# ─────────────────────────── XGBoost (fake) ───────────────────────────


def test_xgboost_build_cablea_semilla_hilos_y_monotonia(monkeypatch: pytest.MonkeyPatch) -> None:
    """``build`` siembra, fija single-thread/silencio y pasa ``monotone_constraints`` como tupla."""
    _use_fake(monkeypatch, "xgboost", _fake_xgb_module())
    estimator = XGBoostBackend().build(
        XGBoostParams(max_depth=4), seed=11, n_threads=1, monotone_constraints=(-1, 1)
    )
    kwargs = cast(Any, estimator).init_kwargs
    assert kwargs["random_state"] == 11
    assert kwargs["n_jobs"] == 1
    assert kwargs["verbosity"] == 0
    assert kwargs["max_depth"] == 4
    assert kwargs["monotone_constraints"] == (-1, 1)


def test_xgboost_build_sin_monotonia_omite_constraint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``monotone_constraints=None`` no se pasa la clave al estimador nativo."""
    _use_fake(monkeypatch, "xgboost", _fake_xgb_module())
    estimator = XGBoostBackend().build(
        XGBoostParams(), seed=0, n_threads=1, monotone_constraints=None
    )
    assert "monotone_constraints" not in cast(Any, estimator).init_kwargs


def test_xgboost_fit_early_stopping_por_set_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """En XGBoost 2.x el early stopping se fija por ``set_params`` con ``eval_set`` en fit."""
    _use_fake(monkeypatch, "xgboost", _fake_xgb_module())
    backend = XGBoostBackend()
    estimator = backend.build(XGBoostParams(), seed=0, n_threads=1, monotone_constraints=None)
    fitted = cast(
        Any,
        backend.fit(
            estimator, _TINY, _TINY_TARGET, eval_set=(_TINY, _TINY_TARGET), early_stopping_rounds=10
        ),
    )
    assert fitted.set_params_calls == {"early_stopping_rounds": 10}
    assert fitted.fit_kwargs == {"eval_set": [(_TINY, _TINY_TARGET)], "verbose": False}


def test_xgboost_fit_eval_set_sin_early_stopping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``eval_set`` pero ``early_stopping_rounds=None`` no se llama ``set_params``."""
    _use_fake(monkeypatch, "xgboost", _fake_xgb_module())
    backend = XGBoostBackend()
    estimator = backend.build(XGBoostParams(), seed=0, n_threads=1, monotone_constraints=None)
    fitted = cast(
        Any,
        backend.fit(estimator, _TINY, _TINY_TARGET, eval_set=(_TINY, _TINY_TARGET)),
    )
    assert fitted.set_params_calls == {}
    assert fitted.fit_kwargs == {"eval_set": [(_TINY, _TINY_TARGET)], "verbose": False}


def test_xgboost_fit_sin_eval_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin ``eval_set`` se ajusta sin early stopping."""
    _use_fake(monkeypatch, "xgboost", _fake_xgb_module())
    backend = XGBoostBackend()
    estimator = backend.build(XGBoostParams(), seed=0, n_threads=1, monotone_constraints=None)
    fitted = cast(Any, backend.fit(estimator, _TINY, _TINY_TARGET))
    assert fitted.set_params_calls == {}
    assert fitted.fit_kwargs == {"verbose": False}


def test_xgboost_predict_proba_y_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """``predict_proba`` delega en el nativo y ``backend_version`` lee ``__version__``."""
    _use_fake(monkeypatch, "xgboost", _fake_xgb_module())
    backend = XGBoostBackend()
    estimator = backend.build(XGBoostParams(), seed=0, n_threads=1, monotone_constraints=None)
    proba = backend.predict_proba(estimator, _TINY)
    assert proba.shape == (len(_TINY), 2)
    assert backend.backend_version() == "2.1.0-fake"


def test_xgboost_importancias_gain_rellena_no_usadas(monkeypatch: pytest.MonkeyPatch) -> None:
    """La importancia por ``gain`` rellena con ``0.0`` las features sin split."""
    _use_fake(monkeypatch, "xgboost", _fake_xgb_module())
    backend = XGBoostBackend()
    estimator = backend.build(XGBoostParams(), seed=0, n_threads=1, monotone_constraints=None)
    assert backend.feature_importances(estimator) == {"f0": 3.0, "f1": 0.0}


def test_xgboost_extra_faltante_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seleccionar ``xgboost`` sin el extra levanta ``MissingDependencyError`` (extra exacto)."""
    _use_missing(monkeypatch, "xgboost")
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[xgboost\]"):
        XGBoostBackend().build(XGBoostParams(), seed=0, n_threads=1, monotone_constraints=None)


# ─────────────────────────── LightGBM (fake) ───────────────────────────


def test_lightgbm_build_cablea_determinismo_y_monotonia(monkeypatch: pytest.MonkeyPatch) -> None:
    """``build`` fija determinismo single-thread y pasa ``monotone_constraints`` como lista."""
    _use_fake(monkeypatch, "lightgbm", _fake_lgb_module())
    estimator = LightGBMBackend().build(
        LightGBMParams(num_leaves=15), seed=9, n_threads=1, monotone_constraints=(-1, 0)
    )
    kwargs = cast(Any, estimator).init_kwargs
    assert kwargs["random_state"] == 9
    assert kwargs["n_jobs"] == 1
    assert kwargs["deterministic"] is True
    assert kwargs["force_row_wise"] is True
    assert kwargs["verbose"] == -1
    assert kwargs["num_leaves"] == 15
    assert kwargs["monotone_constraints"] == [-1, 0]


def test_lightgbm_build_sin_monotonia_omite_constraint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``monotone_constraints=None`` no se pasa la clave al estimador nativo."""
    _use_fake(monkeypatch, "lightgbm", _fake_lgb_module())
    estimator = LightGBMBackend().build(
        LightGBMParams(), seed=0, n_threads=1, monotone_constraints=None
    )
    assert "monotone_constraints" not in cast(Any, estimator).init_kwargs


def test_lightgbm_fit_early_stopping_por_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """En LightGBM 4.x el early stopping va por ``callbacks`` con ``eval_set`` en fit."""
    _use_fake(monkeypatch, "lightgbm", _fake_lgb_module())
    backend = LightGBMBackend()
    estimator = backend.build(LightGBMParams(), seed=0, n_threads=1, monotone_constraints=None)
    fitted = cast(
        Any,
        backend.fit(
            estimator, _TINY, _TINY_TARGET, eval_set=(_TINY, _TINY_TARGET), early_stopping_rounds=5
        ),
    )
    assert fitted.fit_kwargs["eval_set"] == [(_TINY, _TINY_TARGET)]
    assert fitted.fit_kwargs["callbacks"] == [("early_stopping", 5, False)]


def test_lightgbm_fit_eval_set_sin_early_stopping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``eval_set`` pero sin ``early_stopping_rounds`` no se agregan callbacks."""
    _use_fake(monkeypatch, "lightgbm", _fake_lgb_module())
    backend = LightGBMBackend()
    estimator = backend.build(LightGBMParams(), seed=0, n_threads=1, monotone_constraints=None)
    fitted = cast(
        Any,
        backend.fit(estimator, _TINY, _TINY_TARGET, eval_set=(_TINY, _TINY_TARGET)),
    )
    assert fitted.fit_kwargs == {"eval_set": [(_TINY, _TINY_TARGET)]}


def test_lightgbm_fit_sin_eval_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin ``eval_set`` se ajusta sin argumentos extra."""
    _use_fake(monkeypatch, "lightgbm", _fake_lgb_module())
    backend = LightGBMBackend()
    estimator = backend.build(LightGBMParams(), seed=0, n_threads=1, monotone_constraints=None)
    fitted = cast(Any, backend.fit(estimator, _TINY, _TINY_TARGET))
    assert fitted.fit_kwargs == {}


def test_lightgbm_predict_proba_version_e_importancias(monkeypatch: pytest.MonkeyPatch) -> None:
    """``predict_proba``/``backend_version`` e importancia ``gain`` completa del booster."""
    _use_fake(monkeypatch, "lightgbm", _fake_lgb_module())
    backend = LightGBMBackend()
    estimator = backend.build(LightGBMParams(), seed=0, n_threads=1, monotone_constraints=None)
    assert backend.predict_proba(estimator, _TINY).shape == (len(_TINY), 2)
    assert backend.backend_version() == "4.3.0-fake"
    assert backend.feature_importances(estimator) == {"f0": 1.0, "f1": 2.0}


def test_lightgbm_extra_faltante_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seleccionar ``lightgbm`` sin el extra levanta ``MissingDependencyError``."""
    _use_missing(monkeypatch, "lightgbm")
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[lightgbm\]"):
        LightGBMBackend().build(LightGBMParams(), seed=0, n_threads=1, monotone_constraints=None)


# ─────────────────────────── CatBoost (fake) ───────────────────────────


def test_catboost_build_cablea_semilla_hilos_y_monotonia(monkeypatch: pytest.MonkeyPatch) -> None:
    """``build`` siembra (``random_seed``), fija ``thread_count`` y no escribe archivos."""
    _use_fake(monkeypatch, "catboost", _fake_catboost_module())
    estimator = CatBoostBackend().build(
        CatBoostParams(depth=5), seed=3, n_threads=1, monotone_constraints=(1, -1)
    )
    kwargs = cast(Any, estimator).init_kwargs
    assert kwargs["random_seed"] == 3
    assert kwargs["thread_count"] == 1
    assert kwargs["verbose"] is False
    assert kwargs["allow_writing_files"] is False
    assert kwargs["depth"] == 5
    assert kwargs["monotone_constraints"] == [1, -1]


def test_catboost_build_sin_monotonia_omite_constraint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``monotone_constraints=None`` no se pasa la clave al estimador nativo."""
    _use_fake(monkeypatch, "catboost", _fake_catboost_module())
    estimator = CatBoostBackend().build(
        CatBoostParams(), seed=0, n_threads=1, monotone_constraints=None
    )
    assert "monotone_constraints" not in cast(Any, estimator).init_kwargs


def test_catboost_fit_early_stopping_en_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    """CatBoost recibe ``eval_set`` (tupla) y ``early_stopping_rounds`` en ``fit``."""
    _use_fake(monkeypatch, "catboost", _fake_catboost_module())
    backend = CatBoostBackend()
    estimator = backend.build(CatBoostParams(), seed=0, n_threads=1, monotone_constraints=None)
    fitted = cast(
        Any,
        backend.fit(
            estimator, _TINY, _TINY_TARGET, eval_set=(_TINY, _TINY_TARGET), early_stopping_rounds=8
        ),
    )
    assert fitted.fit_kwargs == {
        "verbose": False,
        "eval_set": (_TINY, _TINY_TARGET),
        "early_stopping_rounds": 8,
    }


def test_catboost_fit_eval_set_sin_early_stopping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``eval_set`` pero sin ``early_stopping_rounds`` solo se pasa ``eval_set``."""
    _use_fake(monkeypatch, "catboost", _fake_catboost_module())
    backend = CatBoostBackend()
    estimator = backend.build(CatBoostParams(), seed=0, n_threads=1, monotone_constraints=None)
    fitted = cast(
        Any,
        backend.fit(estimator, _TINY, _TINY_TARGET, eval_set=(_TINY, _TINY_TARGET)),
    )
    assert fitted.fit_kwargs == {"verbose": False, "eval_set": (_TINY, _TINY_TARGET)}


def test_catboost_fit_sin_eval_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin ``eval_set`` solo se pasa ``verbose=False``."""
    _use_fake(monkeypatch, "catboost", _fake_catboost_module())
    backend = CatBoostBackend()
    estimator = backend.build(CatBoostParams(), seed=0, n_threads=1, monotone_constraints=None)
    fitted = cast(Any, backend.fit(estimator, _TINY, _TINY_TARGET))
    assert fitted.fit_kwargs == {"verbose": False}


def test_catboost_predict_proba_version_e_importancias(monkeypatch: pytest.MonkeyPatch) -> None:
    """``predict_proba``/``backend_version`` e importancia nativa alineada con las features."""
    _use_fake(monkeypatch, "catboost", _fake_catboost_module())
    backend = CatBoostBackend()
    estimator = backend.build(CatBoostParams(), seed=0, n_threads=1, monotone_constraints=None)
    assert backend.predict_proba(estimator, _TINY).shape == (len(_TINY), 2)
    assert backend.backend_version() == "1.2.5-fake"
    assert backend.feature_importances(estimator) == {"f0": 10.0, "f1": 20.0}


def test_catboost_extra_faltante_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seleccionar ``catboost`` sin el extra levanta ``MissingDependencyError``."""
    _use_missing(monkeypatch, "catboost")
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[catboost\]"):
        CatBoostBackend().build(CatBoostParams(), seed=0, n_threads=1, monotone_constraints=None)


# ─────────────────────────── smoke real GBDT (skip si falta la lib) ───────────────────────────


def _gbdt_dataset() -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Panel sintético monótono para el smoke real: fit + early stopping."""
    rng = np.random.default_rng(20260703)
    n = 240
    f0 = rng.normal(size=n)
    f1 = rng.normal(size=n)
    f2 = rng.normal(size=n)
    logit = 1.5 * f0 - 1.2 * f1 + 0.3 * f2
    target = (rng.uniform(size=n) < 1.0 / (1.0 + np.exp(-logit))).astype(int)
    features = pd.DataFrame({"f0": f0, "f1": f1, "f2": f2})
    labels = pd.Series(target, name="target")
    return features.iloc[:180], labels.iloc[:180], features.iloc[180:], labels.iloc[180:]


@pytest.mark.parametrize(
    ("backend", "params"),
    [
        pytest.param(
            XGBoostBackend(),
            XGBoostParams(n_estimators=30, max_depth=2),
            marks=[
                pytest.mark.requires_xgboost,
                pytest.mark.skipif(not _HAS_XGBOOST, reason="extra [xgboost] no instalado"),
            ],
            id="xgboost",
        ),
        pytest.param(
            LightGBMBackend(),
            LightGBMParams(n_estimators=30, num_leaves=7, min_child_samples=5),
            marks=[
                pytest.mark.requires_lightgbm,
                pytest.mark.skipif(not _HAS_LIGHTGBM, reason="extra [lightgbm] no instalado"),
            ],
            id="lightgbm",
        ),
        pytest.param(
            CatBoostBackend(),
            CatBoostParams(iterations=30, depth=2),
            marks=[
                pytest.mark.requires_catboost,
                pytest.mark.skipif(not _HAS_CATBOOST, reason="extra [catboost] no instalado"),
            ],
            id="catboost",
        ),
    ],
)
def test_gbdt_real_smoke_y_determinismo(backend: Backend, params: Any) -> None:
    """Smoke real end-to-end del GBDT: build → fit (early stopping) → predict → importancias."""
    x_fit, y_fit, x_es, y_es = _gbdt_dataset()
    constraints = (1, -1, 0)

    def _run() -> np.ndarray[Any, Any]:
        estimator = backend.build(params, seed=123, n_threads=1, monotone_constraints=constraints)
        fitted = backend.fit(
            estimator, x_fit, y_fit, eval_set=(x_es, y_es), early_stopping_rounds=10
        )
        return backend.predict_proba(fitted, x_es)

    proba = _run()
    assert proba.shape == (len(x_es), 2)
    assert np.all(proba >= 0.0) and np.all(proba <= 1.0)

    estimator = backend.build(params, seed=123, n_threads=1, monotone_constraints=constraints)
    fitted = backend.fit(estimator, x_fit, y_fit, eval_set=(x_es, y_es), early_stopping_rounds=10)
    importances = backend.feature_importances(fitted)
    assert set(importances) == {"f0", "f1", "f2"}
    assert backend.backend_version().strip()
    np.testing.assert_array_equal(proba, _run())


# ─────────────────────────── import liviano ───────────────────────────


def test_import_backends_es_liviano_en_proceso_fresco() -> None:
    """``import nikodym.ml.backends`` no arrastra librerías ML ni tabulares (SDD-12 §9)."""
    code = (
        "import sys;"
        "import nikodym.ml.backends;"
        "bloqueados=[m for m in "
        "('numpy','pandas','pandera','pyarrow','scipy','sklearn','xgboost','lightgbm','catboost') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
