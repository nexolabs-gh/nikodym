"""Tests del ``MLChallenger`` (SDD-12 §4/§7/§11): wrapper sklearn-like del challenger ML.

Los backends de scikit-learn (SVM/RandomForest, extra base ``[ml]`` siempre disponible) ejercen el
estimador de punta a punta con la librería **real**: golden stump, determinismo byte-a-byte,
validación de target, monotonía no soportada (warn/error) e invariantes de predicción. Los backends
GBDT (``xgboost``/``lightgbm``/``catboost``, no instalados en la suite) se ejercen con **fakes**
inyectados por ``importlib.import_module`` (mismo patrón que ``test_ml_backends``) para cubrir el
recorte de early stopping, el cableado de monotonía, ``best_iteration`` e ``MLPredictError`` sin
librerías pesadas. Un subproceso verifica que ``import nikodym.ml.estimator`` es liviano.
"""

from __future__ import annotations

import math
import subprocess
import sys
import types
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

import nikodym.ml.backends as backends
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import NotFittedError
from nikodym.ml.config import (
    MLConfig,
    MLTrainConfig,
    MonotonicConfig,
    RandomForestParams,
    SvmParams,
    XGBoostParams,
)
from nikodym.ml.estimator import (
    MLChallenger,
    _as_target,
    _extract_best_iteration,
    _stratified_carve,
    _validate_and_normalize_proba,
    _validate_binary_target,
)
from nikodym.ml.exceptions import (
    MLConfigError,
    MLDataError,
    MLFitError,
    MLMonotonicError,
    MLPredictError,
)


# ─────────────────────────── datasets deterministas ───────────────────────────
def _separable_dataset() -> tuple[pd.DataFrame, pd.Series]:
    """Dataset separable por ``f0`` (stump → hojas puras: PD 0.0 y 1.0 a mano)."""
    features = pd.DataFrame({"f0": [0.0] * 8 + [1.0] * 8, "f1": [1.0] * 8 + [0.0] * 8})
    target = pd.Series([0] * 8 + [1] * 8, name="target")
    return features, target


def _balanced_dataset(n_per_class: int = 12) -> tuple[pd.DataFrame, pd.Series]:
    """Panel balanceado con dos features y ambas clases para el recorte de early stopping."""
    rng = np.random.default_rng(2026)
    f0 = np.concatenate([rng.normal(-1.0, size=n_per_class), rng.normal(1.0, size=n_per_class)])
    f1 = np.concatenate([rng.normal(1.0, size=n_per_class), rng.normal(-1.0, size=n_per_class)])
    features = pd.DataFrame({"f0": f0, "f1": f1})
    target = pd.Series([0] * n_per_class + [1] * n_per_class, name="target")
    return features, target


def _rf_config(**overrides: Any) -> MLConfig:
    """``MLConfig`` de Random Forest determinista y sin early stopping (sin monotonía)."""
    base: dict[str, Any] = dict(
        backend="random_forest",
        hyperparameters=RandomForestParams(n_estimators=5, max_depth=2, min_samples_leaf=1),
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    base.update(overrides)
    return MLConfig(**base)


# ═══════════════════════════ backends sklearn reales ═══════════════════════════
def test_random_forest_golden_stump_fit_predict() -> None:
    """Stump separable: la PD del challenger es la proporción de malos por hoja (0.0 / 1.0)."""
    features, target = _separable_dataset()
    challenger = MLChallenger.from_config(_rf_config()).fit(
        features, target, rng=np.random.default_rng(0)
    )

    assert challenger.feature_names_in_ == ("f0", "f1")
    assert challenger.classes_.tolist() == [0, 1]
    assert challenger.monotone_constraints_ == ()
    assert challenger.best_iteration_ is None
    assert challenger.n_threads_ == 1 and challenger.deterministic_ is True
    assert challenger.backend_version_.strip()
    assert set(challenger.feature_importances_) == {"f0", "f1"}

    pd_hat = challenger.predict_pd(features)
    assert pd_hat[:8].tolist() == [0.0] * 8
    assert pd_hat[8:].tolist() == [1.0] * 8
    proba = challenger.predict_proba(features)
    assert proba.shape == (16, 2)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0)


def test_random_forest_reproducibilidad_byte_a_byte() -> None:
    """Misma semilla + single-thread ⇒ ``seed_`` y ``predict_pd`` idénticos entre corridas."""
    features, target = _separable_dataset()
    config = _rf_config()

    def _run() -> tuple[int, np.ndarray[Any, Any]]:
        challenger = MLChallenger.from_config(config).fit(
            features, target, rng=np.random.default_rng(42)
        )
        return challenger.seed_, challenger.predict_pd(features)

    seed_a, pd_a = _run()
    seed_b, pd_b = _run()
    assert seed_a == seed_b
    np.testing.assert_array_equal(pd_a, pd_b)


def test_rng_por_defecto_es_determinista() -> None:
    """Sin ``rng`` explícito el estimador cae a un generador fijo (reproducible)."""
    features, target = _separable_dataset()
    a = MLChallenger.from_config(_rf_config()).fit(features, target)
    b = MLChallenger.from_config(_rf_config()).fit(features, target)
    assert a.seed_ == b.seed_
    np.testing.assert_array_equal(a.predict_pd(features), b.predict_pd(features))


def test_from_config_acepta_mapping_y_get_set_params() -> None:
    """``from_config`` valida un mapping y el estimador expone ``get_params``/``set_params``."""
    challenger = MLChallenger.from_config(
        {
            "backend": "random_forest",
            "hyperparameters": {"n_estimators": 7},
            "monotonic": {"mode": "off"},
        }
    )
    assert challenger.backend == "random_forest"
    assert "backend" in challenger.get_params(deep=False)
    challenger.set_params(n_threads=1, require_both_classes=False)
    assert challenger.require_both_classes is False


def test_monotonia_no_soportada_warn_se_ignora_y_audita() -> None:
    """RF con monotonía ``from_binning`` y ``warn``: se ignora la constraint y se audita (§7)."""
    features, target = _separable_dataset()
    sink = InMemoryAuditSink()
    config = _rf_config(monotonic=MonotonicConfig(mode="from_binning", on_unsupported="warn"))
    challenger = MLChallenger.from_config(config).fit(
        features, target, rng=np.random.default_rng(0), audit=sink
    )

    assert challenger.monotone_constraints_ == ()
    ignored = [e for e in sink.events if e.payload.get("regla") == "ml_monotonic_ignored"]
    assert len(ignored) == 1
    assert ignored[0].payload["accion"] == "ignore"


def test_monotonia_no_soportada_error_levanta_en_fit() -> None:
    """SVM construido directo con monotonía ``error`` levanta ``MLMonotonicError`` al fitear."""
    features, target = _separable_dataset()
    challenger = MLChallenger(
        backend="svm",
        hyperparameters=SvmParams(kernel="linear"),
        monotonic_mode="from_binning",
        monotonic_on_unsupported="error",
        validation_fraction=0.0,
        early_stopping_rounds=None,
    )
    with pytest.raises(MLMonotonicError, match="no soporta monotonic"):
        challenger.fit(features, target, rng=np.random.default_rng(0))


def test_predict_sin_fit_levanta_not_fitted() -> None:
    """Predecir antes de fitear levanta ``NotFittedError`` (contrato sklearn)."""
    features, _ = _separable_dataset()
    with pytest.raises(NotFittedError):
        MLChallenger.from_config(_rf_config()).predict_proba(features)


def test_predict_columna_faltante_levanta() -> None:
    """Predecir sin las features del ajuste levanta ``MLPredictError``."""
    features, target = _separable_dataset()
    challenger = MLChallenger.from_config(_rf_config()).fit(
        features, target, rng=np.random.default_rng(0)
    )
    with pytest.raises(MLPredictError, match="faltantes"):
        challenger.predict_proba(features.drop(columns=["f1"]))


def test_require_both_classes_false_permite_una_clase() -> None:
    """Con ``require_both_classes=False`` una partición de una clase no levanta ``MLDataError``."""
    features = pd.DataFrame({"f0": [0.0, 1.0, 0.5], "f1": [1.0, 0.0, 0.5]})
    target = pd.Series([0, 0, 0], name="target")
    config = _rf_config(
        train=MLTrainConfig(
            validation_fraction=0.0, early_stopping_rounds=None, require_both_classes=False
        )
    )
    challenger = MLChallenger.from_config(config).fit(
        features, target, rng=np.random.default_rng(0)
    )
    assert challenger.classes_.tolist() == [0]


# ═══════════════════════════ validación de config / datos ═══════════════════════════
def test_resolve_config_hiperparametros_incoherentes_levanta() -> None:
    """Hiperparámetros de otro backend levantan ``MLConfigError`` al resolver el config en fit."""
    features, target = _separable_dataset()
    challenger = MLChallenger(
        backend="random_forest",
        hyperparameters=SvmParams(),
        monotonic_mode="off",
        validation_fraction=0.0,
        early_stopping_rounds=None,
    )
    with pytest.raises(MLConfigError, match="RandomForestParams"):
        challenger.fit(features, target, rng=np.random.default_rng(0))


def test_resolve_config_rango_invalido_se_traduce_a_mlconfigerror() -> None:
    """Un valor fuera de rango (``ValidationError`` de Pydantic) se traduce a ``MLConfigError``."""
    features, target = _separable_dataset()
    challenger = MLChallenger(
        backend="random_forest",
        hyperparameters=RandomForestParams(),
        monotonic_mode="off",
        validation_fraction=1.5,  # fuera de [0, 1)
        early_stopping_rounds=None,
    )
    with pytest.raises(MLConfigError, match="inválidos"):
        challenger.fit(features, target, rng=np.random.default_rng(0))


@pytest.mark.parametrize(
    ("frame", "match"),
    [
        ([1, 2, 3], "pandas.DataFrame"),
        (pd.DataFrame({"f0": []}), "vacío"),
    ],
)
def test_fit_entrada_invalida_levanta_mldataerror(frame: Any, match: str) -> None:
    """``fit`` rechaza entradas no tabulares o vacías con ``MLDataError``."""
    target = pd.Series([0, 1], name="target")
    with pytest.raises(MLDataError, match=match):
        MLChallenger.from_config(_rf_config()).fit(frame, target, rng=np.random.default_rng(0))


def test_fit_columnas_duplicadas_levanta() -> None:
    """Columnas duplicadas en X levantan ``MLDataError`` (ambigüedad de features)."""
    features = pd.DataFrame([[0.0, 1.0], [1.0, 0.0]], columns=["f0", "f0"])
    target = pd.Series([0, 1], name="target")
    with pytest.raises(MLDataError, match="duplicadas"):
        MLChallenger.from_config(_rf_config()).fit(features, target, rng=np.random.default_rng(0))


@pytest.mark.parametrize(
    ("target", "match"),
    [
        (pd.Series([0.0, np.nan], name="t"), "nulos"),
        (pd.Series([0, 2], name="t"), "inválidos"),
        (pd.Series([0, 0], name="t"), "ambas clases"),
    ],
)
def test_validate_binary_target_rechaza(target: pd.Series, match: str) -> None:
    """Target con nulos, valores fuera de 0/1 o una sola clase (con ``require_both``) falla."""
    with pytest.raises(MLDataError, match=match):
        _validate_binary_target(target, require_both=True, np=np)


def test_as_target_coacciona_alinea_y_valida_largo() -> None:
    """``_as_target`` coacciona arrays, reindexa por etiqueta y valida el largo contra X."""
    index = pd.Index([10, 11, 12])
    coerced = _as_target(np.array([0, 1, 0]), index, pd, context="fit")
    assert coerced.index.tolist() == [10, 11, 12]

    shuffled = pd.Series([1, 0, 1], index=[12, 11, 10])
    aligned = _as_target(shuffled, index, pd, context="fit")
    assert aligned.loc[10] == 1 and aligned.loc[12] == 1

    with pytest.raises(MLDataError, match="filas de X"):
        _as_target(pd.Series([0, 1], index=[10, 11]), index, pd, context="fit")


# ═══════════════════════════ recorte de early stopping (helper puro) ═══════════════════════════
def test_stratified_carve_disjunto_y_estratificado() -> None:
    """El recorte separa fit/es sin solape, cubre el índice y conserva ambas clases por lado."""
    features, target = _balanced_dataset(n_per_class=10)
    fit_frame, fit_target, eval_set = _stratified_carve(
        features, target, 0.3, np.random.default_rng(7), np=np
    )
    assert eval_set is not None
    eval_frame, eval_target = eval_set
    fit_idx = set(fit_frame.index)
    eval_idx = set(eval_frame.index)
    assert fit_idx.isdisjoint(eval_idx)
    assert fit_idx | eval_idx == set(features.index)
    assert fit_target.nunique() == 2 and eval_target.nunique() == 2


def test_stratified_carve_todo_singleton_queda_vacio() -> None:
    """Con una observación por clase el recorte queda vacío y levanta ``MLDataError``."""
    features = pd.DataFrame({"f0": [0.0, 1.0], "f1": [1.0, 0.0]})
    target = pd.Series([0, 1], name="target")
    with pytest.raises(MLDataError, match="vacío"):
        _stratified_carve(features, target, 0.2, np.random.default_rng(0), np=np)


def test_stratified_carve_lado_de_una_sola_clase_levanta() -> None:
    """Si una clase no aporta al recorte, el early stopping queda de una sola clase y falla."""
    features = pd.DataFrame({"f0": [0.0, 0.0, 0.0, 0.0, 1.0], "f1": [1.0, 1.0, 1.0, 1.0, 0.0]})
    target = pd.Series([0, 0, 0, 0, 1], name="target")
    with pytest.raises(MLDataError, match="una sola clase"):
        _stratified_carve(features, target, 0.2, np.random.default_rng(0), np=np)


# ═══════════════════════════ helpers puros de predicción / introspección ═══════════════════════
@pytest.mark.parametrize(
    ("proba", "match"),
    [
        (np.zeros((3, 3)), "forma"),
        (np.array([[0.5, float("nan")]]), "no finitas"),
        (np.array([[0.4, 1.6]]), "fuera de"),
    ],
)
def test_validate_and_normalize_proba_rechaza(proba: Any, match: str) -> None:
    """La validación de probabilidades rechaza forma, no-finitud y rango sin clipear."""
    with pytest.raises(MLPredictError, match=match):
        _validate_and_normalize_proba(proba, np=np)


def test_validate_and_normalize_proba_normaliza_menos_cero() -> None:
    """``-0.0`` se normaliza a ``+0.0`` en la matriz de probabilidades devuelta."""
    normalized = _validate_and_normalize_proba(np.array([[-0.0, 1.0]]), np=np)
    assert math.copysign(1.0, normalized[0, 0]) == 1.0


class _BestIterUnderscore:
    best_iteration_ = 3


class _BestIterPlain:
    best_iteration = 4


class _BestIterGetter:
    def get_best_iteration(self) -> int:
        return 5


class _BestIterGetterNone:
    def get_best_iteration(self) -> int | None:
        return None


class _BestIterNone:
    pass


@pytest.mark.parametrize(
    ("fitted", "expected"),
    [
        (_BestIterUnderscore(), 3),
        (_BestIterPlain(), 4),
        (_BestIterGetter(), 5),
        (_BestIterGetterNone(), None),
        (_BestIterNone(), None),
    ],
)
def test_extract_best_iteration(fitted: object, expected: int | None) -> None:
    """La introspección de ``best_iteration`` cubre los tres nombres nativos y la ausencia."""
    assert _extract_best_iteration(fitted) == expected


# ═══════════════════════════ backend GBDT vía fakes ═══════════════════════════
class _FakeXGBBooster:
    def __init__(self, names: list[str], scores: dict[str, float]) -> None:
        self.feature_names = names
        self._scores = scores

    def get_score(self, importance_type: str) -> dict[str, float]:
        assert importance_type == "gain"
        return dict(self._scores)


class _FakeXGB:
    """Fake de ``XGBClassifier`` con comportamiento configurable por atributos de clase."""

    _proba_row: tuple[float, float] = (0.4, 0.6)
    _classes: tuple[int, ...] | None = (0, 1)
    _best_iteration_attr: str | None = "best_iteration"
    _best_iteration_value: int | None = 7
    _raise_on_fit: Exception | None = None
    _proba_columns: int = 2

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        if self._classes is not None:
            self.classes_ = np.array(self._classes)
        if self._best_iteration_attr is not None:
            setattr(self, self._best_iteration_attr, self._best_iteration_value)
        self.set_params_calls: dict[str, Any] = {}
        self.fit_positional: tuple[Any, Any] | None = None
        self.fit_kwargs: dict[str, Any] | None = None

    def set_params(self, **kwargs: Any) -> _FakeXGB:
        self.set_params_calls.update(kwargs)
        return self

    def fit(self, features: Any, target: Any, **kwargs: Any) -> _FakeXGB:
        if self._raise_on_fit is not None:
            raise self._raise_on_fit
        self.fit_positional = (features, target)
        self.fit_kwargs = kwargs
        return self

    def predict_proba(self, features: Any) -> np.ndarray[Any, Any]:
        if self._proba_columns != 2:
            return np.zeros((len(features), self._proba_columns))
        return np.tile(np.asarray(self._proba_row, dtype=float), (len(features), 1))

    def get_booster(self) -> _FakeXGBBooster:
        return _FakeXGBBooster(["f0", "f1"], {"f0": 3.0, "f1": 1.0})


class _FakeXGBOutOfRange(_FakeXGB):
    _proba_row = (0.4, 1.6)


class _FakeXGBNaN(_FakeXGB):
    _proba_row = (float("nan"), 0.6)


class _FakeXGBWrongShape(_FakeXGB):
    _proba_columns = 3


class _FakeXGBNegZero(_FakeXGB):
    _proba_row = (-0.0, 1.0)


class _FakeXGBNoClasses(_FakeXGB):
    _classes = None


class _FakeXGBOtherClasses(_FakeXGB):
    _classes = (0, 2)


class _FakeXGBRaises(_FakeXGB):
    _raise_on_fit = ValueError("no convergió")


def _install_fake_xgb(monkeypatch: pytest.MonkeyPatch, classifier: type[_FakeXGB]) -> None:
    """Inyecta un módulo ``xgboost`` falso con el clasificador dado en ``import_module``."""
    module = types.ModuleType("xgboost")
    module.XGBClassifier = classifier  # type: ignore[attr-defined]
    module.__version__ = "2.1.0-fake"  # type: ignore[attr-defined]
    real_import = backends.importlib.import_module

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "xgboost":
            return module
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(backends.importlib, "import_module", fake_import)


def _xgb_config(**overrides: Any) -> MLConfig:
    base: dict[str, Any] = dict(backend="xgboost", hyperparameters=XGBoostParams(n_estimators=10))
    base.update(overrides)
    return MLConfig(**base)


def test_xgboost_from_binning_cablea_constraints_menos_uno(monkeypatch: pytest.MonkeyPatch) -> None:
    """``from_binning`` traduce a constraint ``-1`` por feature en el orden de columnas (§7)."""
    _install_fake_xgb(monkeypatch, _FakeXGB)
    features, target = _separable_dataset()
    config = _xgb_config(
        monotonic=MonotonicConfig(mode="from_binning"),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    challenger = MLChallenger.from_config(config).fit(
        features, target, rng=np.random.default_rng(0)
    )
    assert challenger.monotone_constraints_ == (-1, -1)
    assert cast(Any, challenger.estimator_).init_kwargs["monotone_constraints"] == (-1, -1)
    assert challenger.best_iteration_ == 7
    assert challenger.backend_version_ == "2.1.0-fake"


def test_xgboost_explicit_y_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """``explicit`` usa el mapa del usuario; ``off`` no pasa ``monotone_constraints`` al backend."""
    _install_fake_xgb(monkeypatch, _FakeXGB)
    features, target = _separable_dataset()
    explicit = MLChallenger.from_config(
        _xgb_config(
            monotonic=MonotonicConfig(mode="explicit", explicit={"f0": 1, "f1": -1}),
            train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
        )
    ).fit(features, target, rng=np.random.default_rng(0))
    assert explicit.monotone_constraints_ == (1, -1)

    off = MLChallenger.from_config(
        _xgb_config(
            monotonic=MonotonicConfig(mode="off"),
            train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
        )
    ).fit(features, target, rng=np.random.default_rng(0))
    assert off.monotone_constraints_ == ()
    assert "monotone_constraints" not in cast(Any, off.estimator_).init_kwargs


def test_xgboost_early_stopping_aisla_fit_de_validacion(monkeypatch: pytest.MonkeyPatch) -> None:
    """El recorte seeded pasa un ``eval_set`` disjunto del set de ajuste (aislamiento, §7)."""
    _install_fake_xgb(monkeypatch, _FakeXGB)
    features, target = _balanced_dataset(n_per_class=10)
    config = _xgb_config(
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.3, early_stopping_rounds=5),
    )
    challenger = MLChallenger.from_config(config).fit(
        features, target, rng=np.random.default_rng(3)
    )
    native = cast(Any, challenger.estimator_)

    fit_index = set(native.fit_positional[0].index)
    eval_frame, _ = native.fit_kwargs["eval_set"][0]
    eval_index = set(eval_frame.index)
    assert fit_index.isdisjoint(eval_index)
    assert fit_index | eval_index == set(features.index)
    assert native.set_params_calls == {"early_stopping_rounds": 5}


def test_xgboost_eval_set_explicito_se_respeta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un ``eval_set`` explícito se usa tal cual (sin recorte interno)."""
    _install_fake_xgb(monkeypatch, _FakeXGB)
    x_fit, y_fit = _separable_dataset()
    x_es, y_es = _separable_dataset()
    config = _xgb_config(
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.2, early_stopping_rounds=5),
    )
    challenger = MLChallenger.from_config(config).fit(
        x_fit, y_fit, eval_set=(x_es, y_es), rng=np.random.default_rng(0)
    )
    native = cast(Any, challenger.estimator_)
    assert list(native.fit_positional[0].index) == list(x_fit.index)
    assert list(native.fit_kwargs["eval_set"][0][0].index) == list(x_es.index)


def test_xgboost_sin_early_stopping_no_recorta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin fracción de validación ni rondas no hay ``eval_set`` (GBDT sin early stopping)."""
    _install_fake_xgb(monkeypatch, _FakeXGB)
    features, target = _separable_dataset()
    config = _xgb_config(
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    challenger = MLChallenger.from_config(config).fit(
        features, target, rng=np.random.default_rng(0)
    )
    native = cast(Any, challenger.estimator_)
    assert native.fit_kwargs == {"verbose": False}
    assert list(native.fit_positional[0].index) == list(features.index)


def test_xgboost_fit_falla_se_envuelve_en_mlfiterror(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un error del backend en ``fit`` se envuelve en ``MLFitError`` con backend y semilla."""
    _install_fake_xgb(monkeypatch, _FakeXGBRaises)
    features, target = _separable_dataset()
    config = _xgb_config(
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    with pytest.raises(MLFitError, match="falló al ajustar"):
        MLChallenger.from_config(config).fit(features, target, rng=np.random.default_rng(0))


def test_xgboost_sin_classes_levanta_mlfiterror(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si el estimador nativo no expone ``classes_`` tras fit se levanta ``MLFitError``."""
    _install_fake_xgb(monkeypatch, _FakeXGBNoClasses)
    features, target = _separable_dataset()
    config = _xgb_config(
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    with pytest.raises(MLFitError, match="classes_"):
        MLChallenger.from_config(config).fit(features, target, rng=np.random.default_rng(0))


def test_xgboost_clase_positiva_ausente_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si la clase positiva (1) no está en ``classes_`` la PD levanta ``MLPredictError``."""
    _install_fake_xgb(monkeypatch, _FakeXGBOtherClasses)
    features, target = _separable_dataset()
    config = _xgb_config(
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    challenger = MLChallenger.from_config(config).fit(
        features, target, rng=np.random.default_rng(0)
    )
    with pytest.raises(MLPredictError, match="clase positiva"):
        challenger.predict_pd(features)


@pytest.mark.parametrize(
    ("classifier", "match"),
    [
        (_FakeXGBOutOfRange, "fuera de"),
        (_FakeXGBNaN, "no finitas"),
        (_FakeXGBWrongShape, "forma"),
    ],
)
def test_xgboost_predict_invariantes(
    monkeypatch: pytest.MonkeyPatch, classifier: type[_FakeXGB], match: str
) -> None:
    """Predicciones fuera de rango, no finitas o de forma inválida levantan ``MLPredictError``."""
    _install_fake_xgb(monkeypatch, classifier)
    features, target = _separable_dataset()
    config = _xgb_config(
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    challenger = MLChallenger.from_config(config).fit(
        features, target, rng=np.random.default_rng(0)
    )
    with pytest.raises(MLPredictError, match=match):
        challenger.predict_proba(features)


def test_xgboost_predict_normaliza_menos_cero(monkeypatch: pytest.MonkeyPatch) -> None:
    """El challenger normaliza ``-0.0`` a ``+0.0`` en la PD del backend."""
    _install_fake_xgb(monkeypatch, _FakeXGBNegZero)
    features, target = _separable_dataset()
    config = _xgb_config(
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    challenger = MLChallenger.from_config(config).fit(
        features, target, rng=np.random.default_rng(0)
    )
    proba = challenger.predict_proba(features)
    assert math.copysign(1.0, proba[0, 0]) == 1.0


# ═══════════════════════════ reexport y núcleo liviano ═══════════════════════════
def test_reexport_perezoso_de_ml_challenger() -> None:
    """``MLChallenger`` se expone de forma perezosa desde ``nikodym.ml`` y en ``__all__``."""
    import nikodym.ml as ml

    assert "MLChallenger" in ml.__all__
    assert ml.MLChallenger is MLChallenger


def test_import_estimator_es_liviano_en_proceso_fresco() -> None:
    """``import nikodym.ml.estimator`` no arrastra librerías ML ni tabulares (SDD-12 §9)."""
    code = (
        "import sys;"
        "import nikodym.ml.estimator;"
        "bloqueados=[m for m in "
        "('numpy','pandas','pandera','pyarrow','scipy','sklearn','xgboost','lightgbm','catboost') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
