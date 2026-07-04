"""Tests del ``TuningStep`` (SDD-13 §7/§9/§11): orquestación de la búsqueda de hiperparámetros.

El paso se ejercita end-to-end con ``RandomForest`` + ``optuna`` **reales** (extra base ``[ml]`` +
``[tuning]``) vía ``Study.run(['tuning'])`` con los artefactos aguas arriba inyectados a mano, más
tests unitarios de las funciones puras (monotonía derivada del binning, lectura de artefactos,
resolución de config, invariante ``best_config``). Cubre: publicación de las siete claves, la deuda
regulatoria de monotonía por variable (no ``-1`` uniforme), el reúso del ``TuningOptimizer`` sin
recodificar, el cableado ``tuning`` **antes** de ``ml``, y el import liviano de ``nikodym.tuning``.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

optuna = pytest.importorskip("optuna")
optuna.logging.set_verbosity(optuna.logging.WARNING)

import nikodym.tuning  # noqa: E402,F401  (registra @register('standard', domain='tuning') + hook)
from nikodym.core import study as study_module  # noqa: E402
from nikodym.core.audit import InMemoryAuditSink  # noqa: E402
from nikodym.core.config import NikodymConfig  # noqa: E402
from nikodym.core.exceptions import ArtifactNotFoundError  # noqa: E402
from nikodym.core.registry import REGISTRY  # noqa: E402
from nikodym.core.study import Study  # noqa: E402
from nikodym.ml.config import (  # noqa: E402
    MLConfig,
    MLTrainConfig,
    MonotonicConfig,
    RandomForestParams,
)
from nikodym.tuning import step as tuning_step  # noqa: E402
from nikodym.tuning.config import (  # noqa: E402
    TuningConfig,
    TuningSamplerConfig,
    TuningValidationConfig,
)
from nikodym.tuning.exceptions import (  # noqa: E402
    TuningConfigError,
    TuningDataError,
    TuningOptimizeError,
)
from nikodym.tuning.optimizer import TuningOptimizer  # noqa: E402
from nikodym.tuning.results import TuningCardSection, TuningResult  # noqa: E402
from nikodym.tuning.search_space import IntSpec, SearchSpaceConfig  # noqa: E402
from nikodym.tuning.step import (  # noqa: E402
    TuningStep,
    _as_dataframe,
    _as_string_tuple,
    _assert_best_config_only_hp,
    _config_without_hyperparameters,
    _derive_from_binning,
    _hyperparameters_dict,
    _ml_config_from_study,
    _read_binning_tables,
    _read_feature_frame,
    _read_frame_metadata,
    _read_woe_column_map,
    _requires_for,
    _tuning_config_from_study,
    _validate_features,
    _woe_monotone_direction,
)


# ═══════════════════════════ builders de fixtures ═══════════════════════════
def _binning_table(woe_values: list[float]) -> pd.DataFrame:
    """Tabla estilo OptBinning: bins de valor + filas Special/Missing/Totals a excluir."""
    bins = [f"bin{i}" for i in range(len(woe_values))] + ["Special", "Missing", "Totals"]
    woe = [*woe_values, 0.31, -0.12, 0.0]
    return pd.DataFrame({"Bin": bins, "WoE": woe, "Count": [10] * len(bins)})


def _artifacts(per_class: int = 30) -> dict[str, Any]:
    """Artefactos aguas arriba: WoE parcialmente separable (gaussianas solapadas) + tablas.

    Las gaussianas solapadas (no separables al 100%) evitan que el ``PerformanceEvaluator`` reviente
    por buckets de decil constantes; las tablas de binning son sintéticas: ``f0`` monótona (⇒ -1)
    y ``f1`` peak (⇒ 0), para ejercer la derivación de monotonía por variable (§7.7).
    """
    partition_col, target_col = "partition", "target"
    rng = np.random.default_rng(7)
    records: list[dict[str, Any]] = []
    for partition in ("desarrollo", "holdout", "oot"):
        f0 = np.concatenate([rng.normal(-1.0, 1.0, per_class), rng.normal(1.0, 1.0, per_class)])
        f1 = np.concatenate([rng.normal(0.5, 1.0, per_class), rng.normal(-0.5, 1.0, per_class)])
        targets = [0] * per_class + [1] * per_class
        for i in range(2 * per_class):
            records.append(
                {
                    partition_col: partition,
                    target_col: targets[i],
                    "f0__woe": float(f0[i]),
                    "f1__woe": float(f1[i]),
                }
            )
    woe_frame = pd.DataFrame(records)
    tables = {
        "f0": _binning_table([1.5, 0.4, -1.2]),  # monótona decreciente ⇒ -1
        "f1": _binning_table([-0.5, 0.6, -0.4]),  # peak (no monótona) ⇒ 0
    }
    return {
        "woe_frame": woe_frame,
        "tables": tables,
        "result": types.SimpleNamespace(woe_column_map={"f0": "f0__woe", "f1": "f1__woe"}),
        "labels": types.SimpleNamespace(target_col=target_col),
        "splits": types.SimpleNamespace(partition_col=partition_col),
    }


def _ml_config(**overrides: Any) -> MLConfig:
    """``MLConfig`` de Random Forest determinista con monotonía por defecto (from_binning)."""
    base: dict[str, Any] = dict(
        backend="random_forest",
        hyperparameters=RandomForestParams(n_estimators=15, max_depth=3, min_samples_leaf=2),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    base.update(overrides)
    return MLConfig(**base)


def _tuning_config(**overrides: Any) -> TuningConfig:
    """``TuningConfig`` barato: pocos trials, espacio reducido sobre hiperparámetros de RF."""
    base: dict[str, Any] = dict(
        optimizer=TuningSamplerConfig(n_trials=4),
        validation=TuningValidationConfig(strategy="cv", n_folds=3),
        search_space=SearchSpaceConfig(
            params={
                "max_depth": IntSpec(low=2, high=4),
                "min_samples_leaf": IntSpec(low=2, high=6),
            }
        ),
    )
    base.update(overrides)
    return TuningConfig(**base)


def _study(
    ml_cfg: MLConfig | None = None,
    tuning_cfg: TuningConfig | None = None,
    arts: dict[str, Any] | None = None,
) -> Study:
    """Construye un ``Study`` con sink en memoria y los artefactos de binning/data inyectados."""
    arts = arts if arts is not None else _artifacts()
    study = Study(NikodymConfig(tuning=tuning_cfg or _tuning_config(), ml=ml_cfg or _ml_config()))
    study.set_audit_sink(InMemoryAuditSink())
    study.artifacts.set("data", "labels", arts["labels"])
    study.artifacts.set("data", "splits", arts["splits"])
    study.artifacts.set("binning", "woe_frame", arts["woe_frame"])
    study.artifacts.set("binning", "result", arts["result"])
    study.artifacts.set("binning", "tables", arts["tables"])
    return study


def _decisions(study: Study, regla: str) -> list[dict[str, Any]]:
    """Devuelve los ``valor`` de las decisiones auditadas con una ``regla`` dada."""
    sink = study._audit
    assert isinstance(sink, InMemoryAuditSink)
    return [
        event.payload["valor"]
        for event in sink.events
        if event.kind == "decision" and event.payload["regla"] == regla
    ]


# ═══════════════════════════ end-to-end vía Study (RandomForest + optuna reales) ═══════════════
def test_e2e_from_binning_publica_siete_artefactos() -> None:
    """El pipeline data→binning→tuning publica las siete claves y θ* dentro del espacio."""
    study = _study()
    study.run(["tuning"])

    for key in tuning_step.TUNING_ARTIFACTS:
        assert study.artifacts.has("tuning", key)
    result = study.artifacts.get("tuning", "result")
    assert isinstance(result, TuningResult)
    assert result.term_structure() is None
    assert len(result.trials) == 4
    best = study.artifacts.get("tuning", "best_hyperparameters")
    assert type(best) is RandomForestParams
    assert 2 <= best.max_depth <= 4
    assert 2 <= best.min_samples_leaf <= 6
    assert study.artifacts.get("tuning", "best_config").hyperparameters == best
    assert study.artifacts.get("tuning", "best_estimator") is not None
    card = study.artifacts.get("tuning", "card")
    assert isinstance(card, TuningCardSection)
    assert set(card.metric_sections) == {"optimization_history", "param_importances", "trials"}


def test_e2e_cruza_con_optimizador_independiente() -> None:
    """Golden no tautológico: el step reproduce un ``TuningOptimizer`` corrido a mano igual seed."""
    arts = _artifacts()
    study = _study(arts=arts)
    study.run(["tuning"])
    result = study.artifacts.get("tuning", "result")

    # Reconstruye X_dev/y_dev y la monotonía derivada exactamente como el step, con el mismo seed.
    seed = study.seed_manager.int_seed_for("tuning")
    woe = arts["woe_frame"]
    mask = (woe["partition"].astype("string").eq("desarrollo") & woe["target"].notna()).to_numpy()
    x_dev = woe.loc[mask, ["f0__woe", "f1__woe"]].copy(deep=True)
    y_dev = woe.loc[mask, "target"].copy(deep=True)
    optimizer = TuningOptimizer.from_config(_tuning_config(), _ml_config())
    independent = optimizer.optimize(
        x_dev, y_dev, seed=seed, monotone_directions={"f0__woe": -1, "f1__woe": 0}
    )

    assert result.best_value == independent.best_value
    assert result.best_hyperparameters.model_dump() == independent.best_hyperparameters.model_dump()


def test_e2e_tuning_corre_antes_de_ml() -> None:
    """``Study.run(['tuning','ml'])`` corre ambos en orden y publica los dos dominios (§2)."""
    arts = _artifacts(per_class=40)
    study = _study(ml_cfg=_ml_config(monotonic=MonotonicConfig(mode="off")), arts=arts)
    study.artifacts.set("model", "raw_pd_frame", _raw_pd_frame(arts))
    study.run(["tuning", "ml"])

    assert study.artifacts.has("tuning", "result")
    assert study.artifacts.has("ml", "result")


def test_e2e_reproducibilidad_byte_a_byte_sin_importancia() -> None:
    """Dos corridas con misma semilla ⇒ ``best``/``trials`` idénticos (importancia excluida, §9)."""

    def snapshot() -> tuple[Any, ...]:
        study = _study()
        study.run(["tuning"])
        result = study.artifacts.get("tuning", "result")
        trials = tuple(
            (t.number, tuple(sorted(t.params.items())), t.value, t.state) for t in result.trials
        )
        return (
            result.best_value,
            tuple(sorted(result.best_hyperparameters.model_dump().items())),
            trials,
        )

    assert snapshot() == snapshot()


def test_e2e_monotonia_derivada_por_variable() -> None:
    """``from_binning`` restringe ``f0__woe`` (monótona) y libera ``f1__woe`` (peak) (§7.7)."""
    study = _study()
    study.run(["tuning"])
    leakage = _decisions(study, "tuning_leakage")
    assert leakage[0]["monotone_constrained"] == ["f0__woe"]
    assert leakage[0]["fit_partition"] == "desarrollo"
    assert leakage[0]["holdout_oot_used"] is False


def test_e2e_monotonia_off_no_restringe() -> None:
    """``monotonic.mode='off'`` no fija constraints (rama ``None`` de la derivación)."""
    study = _study(ml_cfg=_ml_config(monotonic=MonotonicConfig(mode="off")))
    study.run(["tuning"])
    assert _decisions(study, "tuning_leakage")[0]["monotone_constrained"] == []


def test_e2e_monotonia_explicita_reenvia_mapa() -> None:
    """``monotonic.mode='explicit'`` propaga el mapa del usuario a la búsqueda (rama explícita)."""
    study = _study(
        ml_cfg=_ml_config(monotonic=MonotonicConfig(mode="explicit", explicit={"f0__woe": -1}))
    )
    study.run(["tuning"])
    assert _decisions(study, "tuning_leakage")[0]["monotone_constrained"] == ["f0__woe"]


def test_e2e_no_muta_los_artefactos_de_entrada() -> None:
    """Copia defensiva: ``woe_frame`` no se muta tras la corrida (§6)."""
    arts = _artifacts()
    woe_before = arts["woe_frame"].copy(deep=True)
    ml_before = _ml_config()
    study = _study(arts=arts)
    study.run(["tuning"])

    pd.testing.assert_frame_equal(study.artifacts.get("binning", "woe_frame"), woe_before)
    assert study.config.ml == ml_before  # NikodymConfig.ml intacta


def test_e2e_audita_todas_las_reglas_del_paso() -> None:
    """El trail incluye sampler/espacio/objetivo/leakage/mejor/importancia (§9)."""
    study = _study()
    study.run(["tuning"])
    reglas = {
        event.payload["regla"]
        for event in study._audit.events  # type: ignore[attr-defined]
        if event.kind == "decision"
    }
    assert {
        "tuning_sampler",
        "tuning_search_space",
        "tuning_objective",
        "tuning_leakage",
        "tuning_best",
        "tuning_importance",
    } <= reglas
    sampler = _decisions(study, "tuning_sampler")[0]
    assert sampler["sampler"] == "tpe"
    assert sampler["optuna_version"] == str(optuna.__version__)
    space = _decisions(study, "tuning_search_space")[0]
    assert space["params"] == {"max_depth": "int", "min_samples_leaf": "int"}
    best = _decisions(study, "tuning_best")[0]
    assert (
        best["best_hyperparameters"]["max_depth"]
        == study.artifacts.get("tuning", "best_hyperparameters").max_depth
    )


def test_e2e_modo_no_determinista_audita_caveat() -> None:
    """``deterministic=False`` marca no byte-reproducible y lo audita (§9)."""
    study = _study(tuning_cfg=_tuning_config(deterministic=False))
    study.run(["tuning"])
    metadata = study.artifacts.get("tuning", "result").sampler_metadata
    assert metadata.deterministic is False
    determinism = _decisions(study, "tuning_determinism")
    assert determinism and determinism[0]["byte_reproducible"] is False
    card = study.artifacts.get("tuning", "card")
    assert any("no determinista" in limit.lower() for limit in card.limitations)


# ═══════════════════════════ caminos de error ═══════════════════════════
def test_data_raw_esta_diferido() -> None:
    """``ml.feature_source='data_raw'`` levanta ``TuningConfigError`` (FALTA-DATO-ML-1)."""
    study = _study(ml_cfg=MLConfig(backend="xgboost", feature_source="data_raw"))
    with pytest.raises(TuningConfigError, match="data_raw"):
        study.run(["tuning"])


def test_ml_ausente_levanta_config_error() -> None:
    """Sin ``NikodymConfig.ml`` no hay challenger que tunear ⇒ ``TuningConfigError`` (§8)."""
    step = TuningStep.from_config(_tuning_config())
    step._audit = InMemoryAuditSink()
    study = Study(NikodymConfig(tuning=_tuning_config()))
    with pytest.raises(TuningConfigError, match="requiere una sección 'ml'"):
        step.execute(study, np.random.default_rng(0))


def test_artefacto_requerido_ausente_en_execute() -> None:
    """``execute`` re-deriva los ``requires`` reales y exige su presencia (ArtifactNotFound)."""
    arts = _artifacts()
    step = TuningStep.from_config(_tuning_config())
    step._audit = InMemoryAuditSink()
    study = Study(NikodymConfig(tuning=_tuning_config(), ml=_ml_config()))
    study.artifacts.set("data", "labels", arts["labels"])
    study.artifacts.set("data", "splits", arts["splits"])  # falta binning.* → execute lo detecta
    with pytest.raises(ArtifactNotFoundError, match="woe_frame"):
        step.execute(study, np.random.default_rng(0))


def test_validate_pipeline_rechaza_requires_sin_proveedor() -> None:
    """Pre-run: un ``requires`` sin proveedor aguas arriba es config inejecutable (ConfigError)."""
    from nikodym.core.exceptions import ConfigError

    study = Study(NikodymConfig(tuning=_tuning_config(), ml=_ml_config()))
    study.set_audit_sink(InMemoryAuditSink())
    study.artifacts.set("data", "labels", _artifacts()["labels"])
    study.artifacts.set("data", "splits", _artifacts()["splits"])
    with pytest.raises(ConfigError, match="binning"):
        study.run(["tuning"])


def test_desarrollo_vacio_levanta_data_error() -> None:
    """Ninguna fila en la partición de ajuste ⇒ ``TuningDataError`` (§7.6)."""
    study = _study(ml_cfg=_ml_config(train=MLTrainConfig(fit_partition="inexistente")))
    with pytest.raises(TuningDataError, match="partición de ajuste"):
        study.run(["tuning"])


# ═══════════════════════════ requires dinámicos (CT-1) ═══════════════════════════
def test_from_config_declara_requires_por_defecto_de_ml() -> None:
    """``from_config`` declara los ``requires`` con los defaults de ``ml`` (binning_woe)."""
    step = TuningStep.from_config(_tuning_config())
    assert step.name == "tuning"
    assert step.provides == tuple(("tuning", key) for key in tuning_step.TUNING_ARTIFACTS)
    assert step.requires == _requires_for("binning_woe", "from_binning")
    assert ("model", "raw_pd_frame") not in step.requires  # tuning no compara contra el campeón


def test_requires_for_por_feature_source_y_monotonia() -> None:
    """``_requires_for`` compone binning/selección/tablas como ``ml`` menos el campeón (§2/§6)."""
    binning_from = set(_requires_for("binning_woe", "from_binning"))
    assert ("binning", "tables") in binning_from
    assert ("binning", "woe_frame") in binning_from
    assert ("model", "raw_pd_frame") not in binning_from

    binning_off = set(_requires_for("binning_woe", "off"))
    assert ("binning", "tables") not in binning_off

    selection = set(_requires_for("selection_woe", "off"))
    assert ("selection", "selected_woe_frame") in selection
    assert ("selection", "selected_woe_columns") in selection

    data_raw = set(_requires_for("data_raw", "off"))
    assert ("data", "frame") in data_raw


# ═══════════════════════════ lectura de artefactos (funciones puras) ═══════════════════════════
def test_read_feature_frame_selection_woe() -> None:
    """La rama ``selection_woe`` lee ``selected_woe_frame``/``selected_woe_columns`` (copia)."""
    arts = _artifacts()
    store = _FakeStore(
        {
            ("selection", "selected_woe_frame"): arts["woe_frame"],
            ("selection", "selected_woe_columns"): ("f0__woe",),
        }
    )
    study = types.SimpleNamespace(artifacts=store)
    cfg = _ml_config(feature_source="selection_woe", monotonic=MonotonicConfig(mode="off"))
    frame, columns = _read_feature_frame(study, cfg, pd)
    assert columns == ("f0__woe",)
    assert frame is not arts["woe_frame"]  # copia defensiva


def test_read_frame_metadata_valida_contrato() -> None:
    """``labels``/``splits`` deben exponer ``target_col``/``partition_col`` como ``str``."""
    ok = types.SimpleNamespace(
        artifacts=_FakeStore(
            {
                ("data", "labels"): types.SimpleNamespace(target_col="target"),
                ("data", "splits"): types.SimpleNamespace(partition_col="partition"),
            }
        )
    )
    assert _read_frame_metadata(ok) == ("target", "partition")

    bad_labels = types.SimpleNamespace(
        artifacts=_FakeStore(
            {
                ("data", "labels"): types.SimpleNamespace(target_col=None),
                ("data", "splits"): types.SimpleNamespace(partition_col="partition"),
            }
        )
    )
    with pytest.raises(TuningDataError, match="target_col"):
        _read_frame_metadata(bad_labels)

    bad_splits = types.SimpleNamespace(
        artifacts=_FakeStore(
            {
                ("data", "labels"): types.SimpleNamespace(target_col="target"),
                ("data", "splits"): types.SimpleNamespace(partition_col=123),
            }
        )
    )
    with pytest.raises(TuningDataError, match="partition_col"):
        _read_frame_metadata(bad_splits)


def test_read_woe_column_map_y_tables_validan_tipo() -> None:
    """``binning.result``/``binning.tables`` deben traer estructuras no vacías del tipo correcto."""
    bad_map = types.SimpleNamespace(
        artifacts=_FakeStore({("binning", "result"): types.SimpleNamespace(woe_column_map={})})
    )
    with pytest.raises(TuningDataError, match="woe_column_map"):
        _read_woe_column_map(bad_map)

    bad_tables = types.SimpleNamespace(artifacts=_FakeStore({("binning", "tables"): []}))
    with pytest.raises(TuningDataError, match="tablas WoE"):
        _read_binning_tables(bad_tables)


def test_validate_features_rechaza_colisiones_y_faltantes() -> None:
    """Valida columnas presentes y sin colisión con partición/target."""
    frame = pd.DataFrame({"partition": ["a"], "target": [0], "f0__woe": [1.0]})
    _validate_features(frame, ("f0__woe",), "target", "partition")
    with pytest.raises(TuningDataError, match="features WoE"):
        _validate_features(frame, (), "target", "partition")
    with pytest.raises(TuningDataError, match="estructural"):
        _validate_features(frame.drop(columns=["partition"]), ("f0__woe",), "target", "partition")
    with pytest.raises(TuningDataError, match="columnas de features"):
        _validate_features(frame, ("ausente__woe",), "target", "partition")
    with pytest.raises(TuningDataError, match="partición ni el target"):
        _validate_features(frame, ("target",), "target", "partition")


def test_as_dataframe_y_string_tuple_validan_tipo() -> None:
    """Los validadores de artefactos rechazan tipos incorrectos con ``TuningDataError``."""
    assert isinstance(_as_dataframe(pd.DataFrame({"a": [1]}), pd, "x"), pd.DataFrame)
    with pytest.raises(TuningDataError, match="DataFrame"):
        _as_dataframe(object(), pd, "x")
    assert _as_string_tuple(["a", "b"], "cols") == ("a", "b")
    with pytest.raises(TuningDataError, match="tuple"):
        _as_string_tuple([1, 2], "cols")


# ═══════════════════════════ monotonía derivada (funciones puras) ═══════════════════════════
def test_woe_monotone_direction_monotona_y_no_monotona() -> None:
    """WoE monótono ⇒ ``-1``; peak ⇒ ``0``; un solo bin ⇒ ``-1`` (trivial)."""
    assert _woe_monotone_direction(_binning_table([1.5, 0.4, -1.2]), pd=pd, np=np) == -1
    assert _woe_monotone_direction(_binning_table([-1.2, 0.4, 1.5]), pd=pd, np=np) == -1
    assert _woe_monotone_direction(_binning_table([-0.5, 0.6, -0.4]), pd=pd, np=np) == 0
    assert _woe_monotone_direction(_binning_table([0.7]), pd=pd, np=np) == -1


def test_woe_monotone_direction_valida_estructura_de_tabla() -> None:
    """Tabla sin ``Bin``/``WoE`` o no-DataFrame levanta ``TuningDataError``."""
    with pytest.raises(TuningDataError, match="DataFrame"):
        _woe_monotone_direction(object(), pd=pd, np=np)
    with pytest.raises(TuningDataError, match="columnas requeridas"):
        _woe_monotone_direction(pd.DataFrame({"Bin": ["a"]}), pd=pd, np=np)


def test_derive_from_binning_mapea_y_rechaza_no_mapeable() -> None:
    """Deriva ``{-1, 0}`` por columna WoE; una columna sin tabla levanta ``TuningDataError``."""
    tables = {"f0": _binning_table([1.5, 0.4, -1.2]), "f1": _binning_table([-0.5, 0.6, -0.4])}
    woe_column_map = {"f0": "f0__woe", "f1": "f1__woe"}
    directions = _derive_from_binning(("f0__woe", "f1__woe"), woe_column_map, tables, pd=pd, np=np)
    assert directions == {"f0__woe": -1, "f1__woe": 0}
    with pytest.raises(TuningDataError, match="mapear"):
        _derive_from_binning(
            ("x__woe",), {"f0": "f0__woe"}, {"f0": _binning_table([1.0])}, pd=pd, np=np
        )


# ═══════════════════════════ resolución de config e invariante ═══════════════════════════
def test_tuning_config_from_study_resuelve_fuente() -> None:
    """Lee ``config.tuning`` como config, dict o ``None`` (fallback al config del paso)."""
    fallback = _tuning_config()
    none_study = types.SimpleNamespace(config=types.SimpleNamespace(tuning=None))
    assert _tuning_config_from_study(none_study, fallback=fallback) is fallback

    typed = _tuning_config(refit_best=False)
    typed_study = types.SimpleNamespace(config=types.SimpleNamespace(tuning=typed))
    assert _tuning_config_from_study(typed_study, fallback=fallback) is typed

    dict_study = types.SimpleNamespace(config=types.SimpleNamespace(tuning={"n_jobs": 1}))
    resolved = _tuning_config_from_study(dict_study, fallback=fallback)
    assert isinstance(resolved, TuningConfig)


def test_ml_config_from_study_resuelve_fuente() -> None:
    """Lee ``config.ml`` como ``MLConfig`` o dict; ``None`` levanta ``TuningConfigError``."""
    typed = _ml_config()
    typed_study = types.SimpleNamespace(config=types.SimpleNamespace(ml=typed))
    assert _ml_config_from_study(typed_study) is typed

    dict_study = types.SimpleNamespace(
        config=types.SimpleNamespace(ml={"backend": "random_forest", "monotonic": {"mode": "off"}})
    )
    resolved = _ml_config_from_study(dict_study)
    assert isinstance(resolved, MLConfig)
    assert resolved.backend == "random_forest"

    none_study = types.SimpleNamespace(config=types.SimpleNamespace(ml=None))
    with pytest.raises(TuningConfigError, match="requiere una sección 'ml'"):
        _ml_config_from_study(none_study)


def test_assert_best_config_only_hp() -> None:
    """El invariante acepta un cambio de sólo hiperparámetros y rechaza otro cambio (§6)."""
    ml = _ml_config()
    tuned = ml.model_copy(
        update={"hyperparameters": RandomForestParams(n_estimators=99, max_depth=4)}
    )
    _assert_best_config_only_hp(ml, tuned)  # sólo HP: pasa
    assert "hyperparameters" not in _config_without_hyperparameters(ml)

    divergente = ml.model_copy(update={"feature_source": "selection_woe"})
    with pytest.raises(TuningOptimizeError, match="algo más que 'hyperparameters'"):
        _assert_best_config_only_hp(ml, divergente)


def test_hyperparameters_dict_es_escalar() -> None:
    """Los hiperparámetros ganadores se vuelcan a un dict de escalares para la auditoría."""
    params = _hyperparameters_dict(RandomForestParams(n_estimators=25, max_depth=4))
    assert params["n_estimators"] == 25
    assert params["max_depth"] == 4


# ═══════════════════════════ cableado en core.study ═══════════════════════════
def test_core_study_cablea_tuning_antes_de_ml() -> None:
    """``Study`` ubica ``tuning`` tras ``calibration`` y antes de ``ml`` (§2)."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order[order.index("calibration") + 1] == "tuning"
    assert order[order.index("tuning") + 1] == "ml"
    assert study_module._DOMAIN_MODULES["tuning"] == "nikodym.tuning"
    assert study_module._DOMAIN_CONFIG_CLASSES["tuning"] == (
        "nikodym.tuning.config",
        "TuningConfig",
    )
    assert REGISTRY.resolve("tuning", "standard") is TuningStep

    study = Study(NikodymConfig(tuning=TuningConfig(), ml=_ml_config()))
    assert study._default_step_names() == ["tuning", "ml"]
    assert isinstance(study._resolve_step("tuning"), TuningStep)


def test_emit_delega_al_sink() -> None:
    """``TuningStep.emit`` reenvía el evento al ``AuditSink`` inyectado (sink futuro)."""
    from datetime import UTC, datetime

    from nikodym.core.audit import AuditEvent

    sink = InMemoryAuditSink()
    step = TuningStep.from_config(_tuning_config())
    step._audit = sink
    event = AuditEvent(kind="decision", step="tuning", payload={"regla": "x"}, ts=datetime.now(UTC))
    step.emit(event)
    assert sink.events[-1] is event


# ═══════════════════════════ reúso e import liviano (§9/§11) ═══════════════════════════
def test_no_reimplementa_metricas_ni_importa_shap_backends() -> None:
    """El step reúsa el optimizador y no reimplementa métricas ni importa SHAP/backends/optuna."""
    source = Path(tuning_step.__file__).read_text(encoding="utf-8")
    for banned in (
        "roc_auc_score",
        "roc_curve",
        "import shap",
        "import optuna",
        "import xgboost",
        "import lightgbm",
        "import catboost",
        "from sklearn",
        "def _auc",
        "def _ks",
    ):
        assert banned not in source, f"token prohibido en tuning.step: {banned}"
    assert "TuningOptimizer" in source


def test_import_tuning_es_liviano() -> None:
    """``import nikodym.tuning`` no arrastra optuna/pandas/numpy ni los backends ML (§9)."""
    code = (
        "import nikodym.tuning, sys; "
        "heavy = [m for m in "
        "('optuna','sklearn','xgboost','lightgbm','catboost','pandas','numpy','nikodym.ml') "
        "if m in sys.modules]; "
        "assert not heavy, heavy"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# ═══════════════════════════ utilidades de test ═══════════════════════════
def _raw_pd_frame(arts: dict[str, Any]) -> pd.DataFrame:
    """Campeón débil (linear sobre ``f1__woe``) para el paso ``ml`` del test de orden."""
    woe = arts["woe_frame"]
    linear = 0.6 * woe["f1__woe"].to_numpy(dtype="float64") + 0.4 * woe["f0__woe"].to_numpy(
        dtype="float64"
    )
    return pd.DataFrame(
        {
            "partition": woe["partition"].to_numpy(),
            "target": woe["target"].to_numpy(),
            "linear_predictor": linear,
            "pd_raw": 1.0 / (1.0 + np.exp(-linear)),
        }
    )


class _FakeStore:
    """``ArtifactStore`` mínimo para tests unitarios de lectores (sólo ``get``)."""

    def __init__(self, data: dict[tuple[str, str], Any]) -> None:
        self._data = data

    def get(self, domain: str, key: str) -> Any:
        return self._data[(domain, key)]
