"""Tests del ``TuningOptimizer`` (SDD-13 §4/§7/§11): estudio Optuna sobre el challenger ML.

El optimizador se ejerce con las librerías **reales** (optuna + scikit-learn RandomForest, el extra
base ``[ml]``): objetivo determinista con dataset diminuto y folds fijas, reproducibilidad
byte-a-byte de ``trials``/``best`` (la importancia queda **fuera** del assert byte-a-byte, nitpick
A14(1)/FALTA-DATO-TUN-2), anti-leakage de las folds, reúso sin recodificar de
``PerformanceEvaluator``/``MLChallenger`` (test AST), extra ``[tuning]`` faltante, valor no finito y
particiones degeneradas. Un subproceso verifica que ``import nikodym.tuning.optimizer`` es liviano.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

optuna = pytest.importorskip("optuna")
optuna.logging.set_verbosity(optuna.logging.WARNING)

from nikodym.core.audit import InMemoryAuditSink  # noqa: E402
from nikodym.core.exceptions import MissingDependencyError  # noqa: E402
from nikodym.ml.config import (  # noqa: E402
    MLConfig,
    MLTrainConfig,
    MonotonicConfig,
    RandomForestParams,
)
from nikodym.tuning import optimizer as opt_mod  # noqa: E402
from nikodym.tuning.config import (  # noqa: E402
    TuningConfig,
    TuningSamplerConfig,
    TuningValidationConfig,
)
from nikodym.tuning.exceptions import (  # noqa: E402
    TuningConfigError,
    TuningDataError,
    TuningOptimizeError,
    TuningSearchSpaceError,
)
from nikodym.tuning.optimizer import TuningOptimizer  # noqa: E402
from nikodym.tuning.results import TuningResult  # noqa: E402
from nikodym.tuning.search_space import IntSpec, SearchSpaceConfig  # noqa: E402

# Golden pineado a scikit-learn 1.7.x + optuna 4.9.x (D-TUN-golden): un cambio de versión que mueva
# estos valores es un evento auditado, no un fallo silencioso (SDD-13 §9).
_SEED = 20240704
_GOLDEN_BEST_VALUE = 0.9892525057360223
_GOLDEN_MAX_DEPTH = 2
_GOLDEN_MIN_SAMPLES_LEAF = 2


# ─────────────────────────── datasets y configs deterministas ───────────────────────────
def _dataset(n_per_class: int = 40, seed: int = 7) -> tuple[pd.DataFrame, pd.Series]:
    """Panel binario con dos features gaussianas parcialmente separables (barato para CI)."""
    rng = np.random.default_rng(seed)
    f0 = np.concatenate([rng.normal(-1.0, 1.0, n_per_class), rng.normal(1.0, 1.0, n_per_class)])
    f1 = np.concatenate([rng.normal(0.5, 1.0, n_per_class), rng.normal(-0.5, 1.0, n_per_class)])
    features = pd.DataFrame({"f0": f0, "f1": f1})
    target = pd.Series([0] * n_per_class + [1] * n_per_class, name="target")
    order = rng.permutation(len(features))
    return features.iloc[order].reset_index(drop=True), target.iloc[order].reset_index(drop=True)


def _ml_config(**overrides: Any) -> MLConfig:
    """``MLConfig`` de Random Forest determinista, sin early stopping ni monotonía."""
    base: dict[str, Any] = dict(
        backend="random_forest",
        hyperparameters=RandomForestParams(n_estimators=20, max_depth=3, min_samples_leaf=5),
        monotonic=MonotonicConfig(mode="off"),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    base.update(overrides)
    return MLConfig(**base)


def _tuning_config(**overrides: Any) -> TuningConfig:
    """``TuningConfig`` barato: pocos trials, espacio reducido sobre hiperparámetros de RF."""
    base: dict[str, Any] = dict(
        optimizer=TuningSamplerConfig(n_trials=6),
        validation=TuningValidationConfig(strategy="cv", n_folds=3),
        search_space=SearchSpaceConfig(
            params={
                "max_depth": IntSpec(low=2, high=5),
                "min_samples_leaf": IntSpec(low=2, high=10),
            }
        ),
    )
    base.update(overrides)
    return TuningConfig(**base)


def _optimize(
    tuning: TuningConfig | None = None, ml: MLConfig | None = None, **kw: Any
) -> TuningResult:
    """Corre el optimizador con las configs por defecto salvo override."""
    optimizer = TuningOptimizer.from_config(tuning or _tuning_config(), ml or _ml_config())
    features, target = _dataset()
    return optimizer.optimize(features, target, seed=_SEED, **kw)


# ═══════════════════════════ objetivo determinista y golden (§11) ═══════════════════════════
def test_objetivo_golden_random_forest() -> None:
    """Golden: el mejor trial y su valor objetivo son estables con RF + dataset diminuto."""
    result = _optimize()

    assert isinstance(result, TuningResult)
    assert result.best_value == _GOLDEN_BEST_VALUE
    assert result.best_hyperparameters.max_depth == _GOLDEN_MAX_DEPTH
    assert result.best_hyperparameters.min_samples_leaf == _GOLDEN_MIN_SAMPLES_LEAF
    assert len(result.trials) == 6
    assert result.sampler_metadata.n_trials_complete == 6
    assert result.sampler_metadata.sampler == "tpe"
    assert result.sampler_metadata.metric == "auc"
    assert result.sampler_metadata.deterministic is True
    assert result.sampler_metadata.optuna_version == str(optuna.__version__)
    # La importancia existe y está ordenada desc, pero NO se pinea a un golden byte-a-byte.
    assert len(result.param_importances) == 2
    values = [value for _, value in result.param_importances]
    assert values == sorted(values, reverse=True)


def test_reproducibilidad_byte_a_byte_sin_importancia() -> None:
    """Dos corridas con misma semilla ⇒ ``trials``/``best`` idénticos (importancia excluida, §9)."""

    def snapshot() -> tuple[Any, ...]:
        result = _optimize()
        trials = tuple(
            (t.number, tuple(sorted(t.params.items())), t.value, t.state) for t in result.trials
        )
        return (
            result.best_value,
            tuple(sorted(result.best_hyperparameters.model_dump().items())),
            trials,
        )

    assert snapshot() == snapshot()


def test_best_config_difiere_solo_en_hiperparametros() -> None:
    """``best_config`` == ``ml`` con ``hyperparameters=θ*`` y el resto invariante (§6)."""
    ml = _ml_config()
    result = _optimize(ml=ml)

    original = ml.model_dump()
    tuned = result.best_config.model_dump()
    original.pop("hyperparameters")
    tuned.pop("hyperparameters")
    assert original == tuned
    assert result.best_config.hyperparameters == result.best_hyperparameters
    assert type(result.best_hyperparameters) is RandomForestParams


def test_refit_publica_estimador_ajustado_y_toggle_off() -> None:
    """``refit_best=True`` publica un challenger ajustado; ``False`` no publica estimador."""
    con_refit = _optimize()
    assert con_refit.best_estimator is not None
    pd_hat = con_refit.best_estimator.predict_pd(_dataset()[0])
    assert pd_hat.shape == (80,)
    assert bool(np.isfinite(pd_hat).all())

    sin_refit = _optimize(tuning=_tuning_config(refit_best=False))
    assert sin_refit.best_estimator is None


def test_card_y_atributos_fiteados() -> None:
    """La tarjeta CT-2 lleva curva/trials/importancia; ``term_structure`` es None (§9)."""
    optimizer = TuningOptimizer.from_config(_tuning_config(), _ml_config())
    features, target = _dataset()
    result = optimizer.optimize(features, target, seed=_SEED)

    assert result.term_structure() is None
    frame = result.trials_frame()
    assert list(frame.columns) == [
        "number",
        "param_max_depth",
        "param_min_samples_leaf",
        "value",
        "state",
    ]
    sections = result.card.metric_sections
    assert set(sections) == {"optimization_history", "param_importances", "trials"}
    assert len(sections["optimization_history"]) == 6
    assert result.card.summary["backend"] == "random_forest"
    assert any("anti-leakage" in a for a in result.card.assumptions)
    # atributos fiteados (§4)
    assert optimizer.best_value_ == result.best_value
    assert optimizer.n_trials_effective_ == 6
    assert optimizer.sampler_seed_ == _SEED
    assert optimizer.deterministic_ is True
    assert optimizer.study_ is not None


def test_card_marca_no_determinismo() -> None:
    """Con ``deterministic=False`` la tarjeta añade el caveat de no reproducibilidad (§9)."""
    result = _optimize(tuning=_tuning_config(deterministic=False))
    assert result.sampler_metadata.deterministic is False
    assert len(result.card.limitations) == 2
    assert any("no determinista" in limit.lower() for limit in result.card.limitations)


# ═══════════════════════════ sampler / pruner / holdout ═══════════════════════════
def test_sampler_random_es_reproducible() -> None:
    """El sampler ``random`` seedeado también es byte-reproducible."""
    tuning = _tuning_config(optimizer=TuningSamplerConfig(sampler="random", n_trials=5))
    a = _optimize(tuning=tuning)
    b = _optimize(tuning=tuning)
    assert a.best_value == b.best_value
    assert a.sampler_metadata.sampler == "random"


def test_pruner_median_con_cv_completa() -> None:
    """``pruner='median'`` con ``strategy='cv'`` reporta valores por fold y completa el estudio."""
    tuning = _tuning_config(optimizer=TuningSamplerConfig(pruner="median", n_trials=6))
    result = _optimize(tuning=tuning)
    assert result.sampler_metadata.pruner == "median"
    assert result.sampler_metadata.n_trials_complete >= 1


def test_holdout_interno_reproducible() -> None:
    """``strategy='holdout'`` usa un split interno seeded y produce un resultado reproducible."""
    tuning = _tuning_config(
        validation=TuningValidationConfig(strategy="holdout", holdout_fraction=0.3)
    )
    a = _optimize(tuning=tuning)
    b = _optimize(tuning=tuning)
    assert a.best_value == b.best_value
    assert a.sampler_metadata.n_trials_complete == 6


def test_todos_los_trials_podados_levanta_optimize_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si el pruner poda todos los trials no hay mejor trial ⇒ ``TuningOptimizeError`` (§8)."""

    class _AlwaysPrune(optuna.pruners.BasePruner):
        def prune(self, study: Any, trial: Any) -> bool:
            return True

    monkeypatch.setattr(opt_mod, "_build_pruner", lambda _optuna, _name: _AlwaysPrune())
    tuning = _tuning_config(optimizer=TuningSamplerConfig(pruner="median", n_trials=4))
    with pytest.raises(TuningOptimizeError, match="podados"):
        _optimize(tuning=tuning)


# ═══════════════════════════ monotonía fija + audit ═══════════════════════════
def test_monotonia_explicita_y_audit_en_refit() -> None:
    """Las direcciones de monotonía se fijan en modo explícito y el refit audita al sink (§7)."""
    sink = InMemoryAuditSink()
    optimizer = TuningOptimizer.from_config(_tuning_config(), _ml_config())
    features, target = _dataset()
    result = optimizer.optimize(
        features, target, seed=_SEED, monotone_directions={"f0": -1, "f1": -1}, audit=sink
    )
    assert result.best_estimator is not None
    # RandomForest no soporta monotonía: el refit lo audita como ignorado (on_unsupported='warn').
    assert any(event.payload.get("regla") == "ml_monotonic_ignored" for event in sink.events)


# ═══════════════════════════ errores de config/datos (§8) ═══════════════════════════
def test_optimize_sin_config_levanta_config_error() -> None:
    """Un optimizador sin config/ml_config no puede correr ⇒ ``TuningConfigError``."""
    optimizer = TuningOptimizer()
    features, target = _dataset()
    with pytest.raises(TuningConfigError, match="from_config"):
        optimizer.optimize(features, target, seed=_SEED)


def test_from_config_coacciona_dicts() -> None:
    """``from_config`` acepta dicts y los coacciona a los sub-schemas tipados."""
    optimizer = TuningOptimizer.from_config(
        {"optimizer": {"n_trials": 4}},
        {"backend": "random_forest", "monotonic": {"mode": "off"}},
    )
    assert isinstance(optimizer.config, TuningConfig)
    assert isinstance(optimizer.ml_config, MLConfig)
    assert optimizer.ml_config.backend == "random_forest"


def test_espacio_fuera_de_rango_del_backend_levanta_search_space_error() -> None:
    """Un espacio que sugiere hiperparámetros fuera de los rangos del backend ⇒ error (§8)."""
    tuning = _tuning_config(
        search_space=SearchSpaceConfig(params={"n_estimators": IntSpec(low=6000, high=7000)})
    )
    with pytest.raises(TuningSearchSpaceError, match="fuera de rango"):
        _optimize(tuning=tuning)


def test_valor_no_finito_levanta_optimize_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una métrica no finita en las folds propaga ``TuningOptimizeError`` (§8)."""
    monkeypatch.setattr(opt_mod, "_discrimination_value", lambda *a, **k: float("nan"))
    with pytest.raises(TuningOptimizeError, match="no finito"):
        _optimize()


def test_target_una_sola_clase_levanta_data_error() -> None:
    """Un ``desarrollo`` con una sola clase no admite búsqueda ⇒ ``TuningDataError`` (§8)."""
    features = pd.DataFrame({"f0": [0.0, 1.0, 2.0, 3.0], "f1": [1.0, 0.0, 1.0, 0.0]})
    target = pd.Series([1, 1, 1, 1], name="target")
    optimizer = TuningOptimizer.from_config(_tuning_config(), _ml_config())
    with pytest.raises(TuningDataError, match="ambas clases"):
        optimizer.optimize(features, target, seed=_SEED)


def test_folds_mas_que_clase_minoritaria_levanta_data_error() -> None:
    """``n_folds`` mayor que la clase menos poblada ⇒ ``TuningDataError`` (§8)."""
    tuning = _tuning_config(validation=TuningValidationConfig(strategy="cv", n_folds=10))
    features, target = _dataset(n_per_class=4)
    optimizer = TuningOptimizer.from_config(tuning, _ml_config())
    with pytest.raises(TuningDataError, match="n_folds"):
        optimizer.optimize(features, target, seed=_SEED)


# ═══════════════════════════ helpers puros (§7) ═══════════════════════════
def test_prepare_dev_valida_entradas() -> None:
    """``_prepare_dev`` rechaza entradas malformadas y reindexa a un rango único."""
    with pytest.raises(TuningDataError, match="DataFrame"):
        opt_mod._prepare_dev([1, 2], pd.Series([0, 1]), pd=pd, np=np)
    with pytest.raises(TuningDataError, match="vacío"):
        opt_mod._prepare_dev(pd.DataFrame({"f0": []}), pd.Series([], dtype="int64"), pd=pd, np=np)
    with pytest.raises(TuningDataError, match="filas de X"):
        opt_mod._prepare_dev(pd.DataFrame({"f0": [1.0, 2.0]}), pd.Series([0]), pd=pd, np=np)
    with pytest.raises(TuningDataError, match="nulos"):
        opt_mod._prepare_dev(
            pd.DataFrame({"f0": [1.0, 2.0]}), pd.Series([0.0, np.nan]), pd=pd, np=np
        )
    with pytest.raises(TuningDataError, match="binario"):
        opt_mod._prepare_dev(pd.DataFrame({"f0": [1.0, 2.0]}), pd.Series([0, 2]), pd=pd, np=np)
    # coacción de y no-Series + reindex a RangeIndex
    frame = pd.DataFrame({"f0": [1.0, 2.0]}, index=[10, 20])
    x_dev, y_dev = opt_mod._prepare_dev(frame, [0, 1], pd=pd, np=np)
    assert list(x_dev.index) == [0, 1]
    assert list(y_dev.to_numpy()) == [0, 1]


def test_stratified_holdout_clase_unitaria_levanta_data_error() -> None:
    """Un holdout con una clase de una sola fila es imposible ⇒ ``TuningDataError``."""
    target = np.array([0, 1, 1, 1], dtype="int64")
    with pytest.raises(TuningDataError, match="holdout"):
        opt_mod._stratified_holdout(target, 0.2, _SEED, np=np)


def test_discrimination_value_fold_no_evaluable() -> None:
    """Una fold de validación de una sola clase no es evaluable ⇒ ``TuningDataError`` (§7.10d)."""
    pd_hat = np.array([0.2, 0.4, 0.6, 0.8])
    y_val = pd.Series([1, 1, 1, 1], index=[0, 1, 2, 3])
    with pytest.raises(TuningDataError, match="no es evaluable"):
        opt_mod._discrimination_value(pd_hat, y_val, metric="auc", np=np, pd=pd)


def test_report_and_maybe_prune_ambas_ramas() -> None:
    """``_report_and_maybe_prune`` reporta el valor y poda sólo si el pruner lo indica (§7.10e)."""

    class _Trial:
        def __init__(self, prune: bool) -> None:
            self._prune = prune
            self.reported: list[tuple[float, int]] = []

        def report(self, value: float, step: int) -> None:
            self.reported.append((value, step))

        def should_prune(self) -> bool:
            return self._prune

    seguir = _Trial(prune=False)
    opt_mod._report_and_maybe_prune(seguir, 0.9, 0, optuna=optuna)
    assert seguir.reported == [(0.9, 0)]

    podar = _Trial(prune=True)
    with pytest.raises(optuna.TrialPruned):
        opt_mod._report_and_maybe_prune(podar, 0.1, 1, optuna=optuna)


def test_importancia_vacia_con_un_solo_trial() -> None:
    """Un estudio de un único trial no admite importancia ⇒ mapa vacío, sin fallar (§9)."""
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=1))
    study.optimize(lambda trial: trial.suggest_float("x", 0.0, 1.0), n_trials=1)
    assert opt_mod._param_importances(optuna, study, _SEED) == {}


# ═══════════════════════════ reúso e import liviano (§9/§11) ═══════════════════════════
def test_no_reimplementa_metricas_ni_importa_backends() -> None:
    """El optimizador reúsa los evaluadores/estimadores y no recodifica métricas ni el fit (§11)."""
    source = Path(opt_mod.__file__).read_text(encoding="utf-8")
    for banned in (
        "roc_auc_score",
        "roc_curve",
        "def _auc",
        "def _gini",
        "def _ks",
        "import sklearn",
        "from sklearn",
        "import xgboost",
        "import lightgbm",
        "import catboost",
        "import shap",
        "import optuna",
    ):
        assert banned not in source, f"token prohibido en tuning.optimizer: {banned}"
    assert "PerformanceEvaluator" in source
    assert "MLChallenger" in source
    assert "suggest_params" in source


def test_extra_tuning_faltante_levanta_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin el extra ``[tuning]`` (optuna) ⇒ ``MissingDependencyError`` con el extra nombrado."""
    real_import = importlib.import_module

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "optuna":
            raise ModuleNotFoundError("No module named 'optuna'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(opt_mod.importlib, "import_module", fake_import)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[tuning\]"):
        _optimize()


def test_import_optimizer_es_liviano_en_proceso_fresco() -> None:
    """``import nikodym.tuning.optimizer`` no arrastra optuna/ML/tabulares (§9)."""
    code = (
        "import nikodym.tuning.optimizer, sys;"
        "heavy = [m for m in ('optuna','sklearn','xgboost','lightgbm','catboost','numpy','pandas')"
        " if m in sys.modules];"
        "assert not heavy, heavy"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
