"""Tests del ``MLStep`` (SDD-12 §7/§9/§11): orquestación del challenger ML.

El paso se ejercita end-to-end con ``RandomForest`` **real** (extra base ``[ml]``, siempre
disponible) vía ``Study.run(['ml'])`` con artefactos aguas arriba inyectados a mano, más tests
unitarios de las funciones puras (monotonía derivada del binning, comparación, tarjeta, metadata)
con *fakes*. Cubre la deuda crítica B12.4 nitpick #1 (monotonía por variable, no ``-1`` uniforme),
el reúso de los evaluadores SDD-11 (test AST anti-reimplementación) y el import liviano.
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

import nikodym.ml  # noqa: F401  (registra @register('standard', domain='ml') + hook de config)
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError
from nikodym.core.study import Study
from nikodym.ml import step as ml_step
from nikodym.ml.config import (
    MLComparisonConfig,
    MLConfig,
    MLOutputConfig,
    MLTrainConfig,
    MonotonicConfig,
    RandomForestParams,
)
from nikodym.ml.exceptions import MLComparisonError, MLConfigError, MLDataError
from nikodym.ml.results import MLBackendMetadata, MLCardSection, MLComparisonRecord, MLResult
from nikodym.ml.step import (
    MLStep,
    _apply_tuning_best_config,
    _as_dataframe,
    _as_ml_config,
    _as_string_tuple,
    _better,
    _build_backend_metadata,
    _build_card,
    _calibration_config_from_study,
    _champion_analytic,
    _comparison_payload,
    _derive_from_binning,
    _hyperparameters_dict,
    _is_finite,
    _make_record,
    _ml_config_from_study,
    _monotone_pairs,
    _read_binning_tables,
    _read_champion_frame,
    _read_frame_metadata,
    _read_woe_column_map,
    _requires_for,
    _top_importances,
    _validate_features,
    _woe_monotone_direction,
)


# ═══════════════════════════ builders de fixtures ═══════════════════════════
def _binning_table(woe_values: list[float]) -> pd.DataFrame:
    """Tabla estilo OptBinning: bins de valor + filas Special/Missing/Totals a excluir."""
    bins = [f"bin{i}" for i in range(len(woe_values))] + ["Special", "Missing", "Totals"]
    woe = [*woe_values, 0.31, -0.12, 0.0]
    return pd.DataFrame({"Bin": bins, "WoE": woe, "Count": [10] * len(bins)})


def _artifacts(per: int = 40) -> dict[str, Any]:
    """Artefactos aguas arriba: WoE (f0 fuerte, f1 ruido), campeón débil (linear en f1)."""
    partition_col, target_col = "partition", "target"
    rng = np.random.default_rng(20260704)
    records: list[dict[str, Any]] = []
    for partition in ("desarrollo", "holdout", "oot"):
        for i in range(per):
            bad = i % 2  # 20 buenos (target 0) + 20 malos (target 1) por partición
            f0 = (2.0 if bad == 0 else -2.0) + float(rng.normal(scale=0.4))
            f1 = float(rng.normal(scale=1.0))
            records.append(
                {partition_col: partition, target_col: bad, "f0__woe": f0, "f1__woe": f1}
            )
    woe_frame = pd.DataFrame(records)
    linear = 0.6 * woe_frame["f1__woe"].to_numpy(dtype="float64")  # campeón débil (ruido)
    pd_raw = 1.0 / (1.0 + np.exp(-linear))
    raw_pd_frame = pd.DataFrame(
        {
            partition_col: woe_frame[partition_col].to_numpy(),
            target_col: woe_frame[target_col].to_numpy(),
            "linear_predictor": linear,
            "pd_raw": pd_raw,
        }
    )
    tables = {
        "f0": _binning_table([1.5, 0.4, -1.2]),  # monótona decreciente ⇒ -1
        "f1": _binning_table([-0.5, 0.6, -0.4]),  # peak (no monótona) ⇒ 0
    }
    return {
        "woe_frame": woe_frame,
        "raw_pd_frame": raw_pd_frame,
        "tables": tables,
        "result": types.SimpleNamespace(woe_column_map={"f0": "f0__woe", "f1": "f1__woe"}),
        "labels": types.SimpleNamespace(target_col=target_col),
        "splits": types.SimpleNamespace(partition_col=partition_col),
    }


def _study(ml_cfg: MLConfig, arts: dict[str, Any] | None = None) -> Study:
    """Construye un ``Study`` con sink en memoria y los artefactos de binning/model inyectados."""
    arts = arts if arts is not None else _artifacts()
    study = Study(NikodymConfig(ml=ml_cfg))
    study.set_audit_sink(InMemoryAuditSink())
    study.artifacts.set("data", "labels", arts["labels"])
    study.artifacts.set("data", "splits", arts["splits"])
    study.artifacts.set("binning", "woe_frame", arts["woe_frame"])
    study.artifacts.set("binning", "result", arts["result"])
    study.artifacts.set("binning", "tables", arts["tables"])
    study.artifacts.set("model", "raw_pd_frame", arts["raw_pd_frame"])
    return study


def _rf_config(**overrides: Any) -> MLConfig:
    """``MLConfig`` de Random Forest determinista con monotonía por defecto (from_binning)."""
    base: dict[str, Any] = dict(
        backend="random_forest",
        hyperparameters=RandomForestParams(n_estimators=25, max_depth=4, min_samples_leaf=2),
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    base.update(overrides)
    return MLConfig(**base)


def _decisions(study: Study, regla: str) -> list[dict[str, Any]]:
    """Devuelve los ``valor`` de las decisiones auditadas con una ``regla`` dada."""
    sink = study._audit
    assert isinstance(sink, InMemoryAuditSink)
    return [
        event.payload["valor"]
        for event in sink.events
        if event.kind == "decision" and event.payload["regla"] == regla
    ]


def _fake_challenger(**overrides: Any) -> Any:
    """Fake de ``MLChallenger`` fiteado para tests de tarjeta/metadata sin backend real."""
    base: dict[str, Any] = dict(
        backend_version_="9.9.9",
        seed_=7,
        n_threads_=1,
        deterministic_=True,
        best_iteration_=None,
        feature_names_in_=("f0__woe", "f1__woe"),
        feature_importances_={"f0__woe": 0.7, "f1__woe": 0.3},
        monotone_constraints_=(),
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


# ═══════════════════════════ end-to-end vía Study (RandomForest real) ═══════════════════════════
def test_e2e_binning_woe_from_binning_publica_siete_artefactos() -> None:
    """El pipeline data→binning→model→ml publica los siete artefactos y PD ∈ [0, 1]."""
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="from_binning")))
    study.run(["ml"])

    for key in ml_step.ML_ARTIFACTS:
        assert study.artifacts.has("ml", key)
    pd_frame = study.artifacts.get("ml", "pd_frame")
    assert list(pd_frame.columns) == ["partition", "target", "pd_hat"]
    assert len(pd_frame.index) == 120
    assert bool(((pd_frame["pd_hat"] >= 0.0) & (pd_frame["pd_hat"] <= 1.0)).all())
    assert study.artifacts.get("ml", "calibrated_pd_frame") is None

    result = study.artifacts.get("ml", "result")
    assert isinstance(result, MLResult)
    assert result.term_structure() is None
    card = study.artifacts.get("ml", "card")
    assert set(card.metric_sections) == {"comparison_curves", "feature_importances", "determinism"}
    assert card.metric_sections["determinism"]["byte_reproducible"] is True


def test_e2e_monotonia_derivada_libera_variable_no_monotona() -> None:
    """``from_binning`` marca ``f1__woe`` (peak) como libre y ``f0__woe`` como restringida (§7)."""
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="from_binning")))
    study.run(["ml"])

    valores = _decisions(study, "ml_monotonic")
    assert valores, "debe auditar la decisión ml_monotonic"
    assert valores[0]["free_features"] == ["f1__woe"]
    assert valores[0]["config_mode"] == "from_binning"
    assert valores[0]["effective_mode"] == "explicit"


def test_e2e_comparacion_challenger_supera_al_campeon_debil() -> None:
    """El challenger (RF sobre f0) gana en AUC al campeón débil (linear sobre ruido f1)."""
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="off")))
    study.run(["ml"])

    comparison = study.artifacts.get("ml", "comparison")
    assert comparison, "la comparación no debe estar vacía"
    pares = {(record.partition, record.metric) for record in comparison}
    assert ("desarrollo", "auc") in pares
    assert any(record.metric == "auc" and record.better == "challenger" for record in comparison)
    assert any(
        record.metric == "psi" and record.partition in {"holdout", "oot"} for record in comparison
    )
    assert all(
        record.source == "performance_evaluator" for record in comparison if record.metric != "psi"
    )
    assert all(
        record.source == "stability_evaluator" for record in comparison if record.metric == "psi"
    )


def test_e2e_reuso_performance_evaluator_consistente() -> None:
    """El AUC/Gini/KS del campeón que publica ``ml`` coincide con ``PerformanceEvaluator`` (§11)."""
    from nikodym.performance.evaluator import PerformanceEvaluator

    arts = _artifacts()
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="off")), arts=arts)
    study.run(["ml"])
    comparison = study.artifacts.get("ml", "comparison")

    champion = _champion_analytic(arts["raw_pd_frame"], "partition", "target", pd)
    evaluator = PerformanceEvaluator(evaluation_source="pd_calibrated")
    independent = evaluator.evaluate(
        champion,
        score_column="linear_predictor",
        pd_column="pd_raw",
        target_column="target",
        partition_column="partition",
    )
    by_partition = {record.partition: record for record in independent.discriminant_records}
    checked = 0
    for record in comparison:
        if record.source == "performance_evaluator":
            expected = getattr(by_partition[record.partition], record.metric)
            assert record.champion_value == pytest.approx(expected)
            checked += 1
    assert checked > 0


def test_e2e_determinismo_byte_a_byte() -> None:
    """Dos corridas con misma semilla y datos producen ``pd_frame``/comparación idénticos (§11)."""
    first = _study(_rf_config(monotonic=MonotonicConfig(mode="off")))
    second = _study(_rf_config(monotonic=MonotonicConfig(mode="off")))
    first.run(["ml"])
    second.run(["ml"])

    pd.testing.assert_frame_equal(
        first.artifacts.get("ml", "pd_frame"), second.artifacts.get("ml", "pd_frame")
    )
    assert first.artifacts.get("ml", "comparison") == second.artifacts.get("ml", "comparison")


def test_e2e_no_muta_los_artefactos_de_entrada() -> None:
    """Copia defensiva: ``woe_frame``/``raw_pd_frame`` no se mutan tras la corrida (§6)."""
    arts = _artifacts()
    woe_before = arts["woe_frame"].copy(deep=True)
    raw_before = arts["raw_pd_frame"].copy(deep=True)
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="off")), arts=arts)
    study.run(["ml"])

    pd.testing.assert_frame_equal(study.artifacts.get("binning", "woe_frame"), woe_before)
    pd.testing.assert_frame_equal(study.artifacts.get("model", "raw_pd_frame"), raw_before)


def test_e2e_selection_woe_usa_columnas_seleccionadas() -> None:
    """``feature_source='selection_woe'`` entrena sólo sobre las columnas seleccionadas."""
    arts = _artifacts()
    study = Study(
        NikodymConfig(
            ml=_rf_config(feature_source="selection_woe", monotonic=MonotonicConfig(mode="off"))
        )
    )
    study.set_audit_sink(InMemoryAuditSink())
    study.artifacts.set("data", "labels", arts["labels"])
    study.artifacts.set("data", "splits", arts["splits"])
    study.artifacts.set("selection", "selected_woe_frame", arts["woe_frame"])
    study.artifacts.set("selection", "selected_woe_columns", ("f0__woe",))
    study.artifacts.set("model", "raw_pd_frame", arts["raw_pd_frame"])
    study.run(["ml"])

    estimator = study.artifacts.get("ml", "estimator")
    assert estimator.feature_names_in_ == ("f0__woe",)


def test_e2e_calibracion_opcional_reusa_pdcalibrator() -> None:
    """``calibrate_challenger=True`` publica ``calibrated_pd_frame`` con el esquema de SDD-10."""
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="off"), calibrate_challenger=True))
    study.run(["ml"])

    calibrated = study.artifacts.get("ml", "calibrated_pd_frame")
    assert calibrated is not None
    assert {"pd_calibrated", "linear_predictor_calibrated"} <= set(calibrated.columns)
    valores = _decisions(study, "ml_calibration")
    assert valores[0]["calibrated"] is True


def test_e2e_modo_no_determinista_audita_caveat() -> None:
    """``deterministic=False`` marca el resultado no byte-reproducible y lo audita (§9)."""
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="off"), deterministic=False))
    study.run(["ml"])

    metadata = study.artifacts.get("ml", "backend_metadata")
    assert metadata.deterministic is False
    assert _decisions(study, "ml_determinism"), "debe auditar ml_determinism"
    card = study.artifacts.get("ml", "card")
    assert card.metric_sections["determinism"]["byte_reproducible"] is False
    assert any("multihilo" in limitacion for limitacion in card.limitations)


def test_e2e_audita_todas_las_reglas_del_paso() -> None:
    """El trail incluye backend/semilla/features/monotonía/train/comparación/calibración (§9)."""
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="off")))
    study.run(["ml"])

    reglas = {
        event.payload["regla"]
        for event in study._audit.events  # type: ignore[attr-defined]
        if event.kind == "decision"
    }
    assert {
        "ml_backend",
        "ml_seed",
        "ml_feature_source",
        "ml_monotonic",
        "ml_train",
        "ml_comparison",
        "ml_calibration",
    } <= reglas


# ═══════════════════════════ caminos de error ═══════════════════════════
def test_data_raw_esta_diferido() -> None:
    """``feature_source='data_raw'`` levanta ``MLConfigError`` (FALTA-DATO-ML-1)."""
    step = MLStep.from_config(MLConfig(backend="xgboost", feature_source="data_raw"))
    step._audit = InMemoryAuditSink()
    study = Study(NikodymConfig())
    with pytest.raises(MLConfigError, match="data_raw"):
        step.execute(study, np.random.default_rng(0))


def test_artefacto_requerido_ausente() -> None:
    """La ausencia de ``model.raw_pd_frame`` levanta ``ArtifactNotFoundError`` antes de ejecutar."""
    arts = _artifacts()
    step = MLStep.from_config(_rf_config(monotonic=MonotonicConfig(mode="off")))
    step._audit = InMemoryAuditSink()
    study = Study(NikodymConfig())
    study.artifacts.set("data", "labels", arts["labels"])
    study.artifacts.set("data", "splits", arts["splits"])
    study.artifacts.set("binning", "woe_frame", arts["woe_frame"])
    study.artifacts.set("binning", "result", arts["result"])
    with pytest.raises(ArtifactNotFoundError, match="raw_pd_frame"):
        step.execute(study, np.random.default_rng(0))


def test_indices_desalineados_campeon_challenger() -> None:
    """Un campeón con menos filas modelables que el challenger levanta ``MLComparisonError``."""
    arts = _artifacts()
    arts["raw_pd_frame"] = arts["raw_pd_frame"].iloc[1:].copy(deep=True)
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="off")), arts=arts)
    with pytest.raises(MLComparisonError, match="no coinciden"):
        study.run(["ml"])


def test_prediccion_sin_filas_en_predict_partitions() -> None:
    """``predict_partitions`` sin coincidencias levanta ``MLDataError``."""
    study = _study(
        _rf_config(
            monotonic=MonotonicConfig(mode="off"),
            train=MLTrainConfig(
                predict_partitions=("inexistente",),
                validation_fraction=0.0,
                early_stopping_rounds=None,
            ),
        )
    )
    with pytest.raises(MLDataError, match="predict_partitions"):
        study.run(["ml"])


# ═══════════════════════════ monotonía derivada (deuda crítica B12.4) ═══════════════════════════
def test_woe_monotone_direction_monotona_y_no_monotona() -> None:
    """WoE monótono ⇒ ``-1``; peak ⇒ ``0``; un solo bin ⇒ ``-1`` (trivial)."""
    assert _woe_monotone_direction(_binning_table([1.5, 0.4, -1.2]), pd=pd, np=np) == -1
    assert _woe_monotone_direction(_binning_table([-1.2, 0.4, 1.5]), pd=pd, np=np) == -1
    assert _woe_monotone_direction(_binning_table([-0.5, 0.6, -0.4]), pd=pd, np=np) == 0
    assert _woe_monotone_direction(_binning_table([0.7]), pd=pd, np=np) == -1


def test_woe_monotone_direction_valida_estructura_de_tabla() -> None:
    """Tabla sin ``Bin``/``WoE`` o no-DataFrame levanta ``MLDataError``."""
    with pytest.raises(MLDataError, match="DataFrame"):
        _woe_monotone_direction(object(), pd=pd, np=np)
    with pytest.raises(MLDataError, match="columnas requeridas"):
        _woe_monotone_direction(pd.DataFrame({"Bin": ["a"]}), pd=pd, np=np)


def test_derive_from_binning_mapea_por_woe_column_map() -> None:
    """Deriva ``{-1, 0}`` por columna WoE invirtiendo ``woe_column_map``."""
    tables = {"f0": _binning_table([1.5, 0.4, -1.2]), "f1": _binning_table([-0.5, 0.6, -0.4])}
    woe_column_map = {"f0": "f0__woe", "f1": "f1__woe"}
    directions = _derive_from_binning(("f0__woe", "f1__woe"), woe_column_map, tables, pd=pd, np=np)
    assert directions == {"f0__woe": -1, "f1__woe": 0}


def test_derive_from_binning_columna_no_mapeable() -> None:
    """Una columna WoE sin tabla asociada levanta ``MLDataError``."""
    with pytest.raises(MLDataError, match="mapear"):
        _derive_from_binning(
            ("x__woe",), {"f0": "f0__woe"}, {"f0": _binning_table([1.0])}, pd=pd, np=np
        )


# ═══════════════════════════ comparación (funciones puras) ═══════════════════════════
def test_better_orientacion_por_metrica() -> None:
    """AUC premia el mayor; PSI premia el menor; la tolerancia declara empate (§6)."""
    assert _better("auc", 0.1, 1e-6) == "challenger"
    assert _better("auc", -0.1, 1e-6) == "champion"
    assert _better("psi", -0.1, 1e-6) == "challenger"
    assert _better("psi", 0.1, 1e-6) == "champion"
    assert _better("gini", 0.0, 1e-6) == "tie"


def test_make_record_finito_o_none() -> None:
    """Con valores finitos arma el record; con un valor faltante retorna ``None``."""
    record = _make_record("holdout", "auc", 0.70, 0.82, 1e-6, source="performance_evaluator")
    assert record is not None
    assert record.delta == pytest.approx(0.12)
    assert record.better == "challenger"
    assert _make_record("oot", "auc", None, 0.8, 1e-6, source="performance_evaluator") is None


def test_comparison_payload_proyecta_record() -> None:
    """El payload de auditoría refleja todos los campos del record."""
    record = MLComparisonRecord(
        partition="oot",
        metric="ks",
        champion_value=0.3,
        challenger_value=0.5,
        delta=0.2,
        better="challenger",
        source="performance_evaluator",
    )
    payload = _comparison_payload(record)
    assert payload == {
        "partition": "oot",
        "metric": "ks",
        "champion_value": 0.3,
        "challenger_value": 0.5,
        "delta": 0.2,
        "better": "challenger",
        "source": "performance_evaluator",
    }


def test_is_finite_rechaza_none_bool_y_no_numericos() -> None:
    """``_is_finite`` excluye ``None``/``bool``/``NaN``/``inf``/no numéricos y acepta floats."""
    assert not _is_finite(None)
    assert not _is_finite(True)
    assert not _is_finite(float("nan"))
    assert not _is_finite(float("inf"))
    assert not _is_finite("x")
    assert _is_finite(1.5)


# ═══════════════════════════ DTOs de salida (funciones puras con fakes) ═══════════════════════════
def test_build_card_con_gbdt_no_determinista() -> None:
    """La tarjeta incluye ``best_iteration`` y marca el caveat de no byte-reproducibilidad."""
    challenger = _fake_challenger(best_iteration_=7, deterministic_=False, n_threads_=4)
    card = _build_card(_rf_config(), challenger, (), (("f0__woe", 0.9),))
    assert isinstance(card, MLCardSection)
    assert card.summary["best_iteration"] == 7
    assert card.metric_sections["determinism"]["byte_reproducible"] is False
    assert any("multihilo" in limitacion for limitacion in card.limitations)


def test_build_backend_metadata_desde_fake() -> None:
    """La metadata refleja semilla, versión, ``best_iteration`` y hiperparámetros."""
    challenger = _fake_challenger(best_iteration_=3)
    metadata = _build_backend_metadata(_rf_config(), challenger, (("f0__woe", 0.9),))
    assert isinstance(metadata, MLBackendMetadata)
    assert metadata.best_iteration == 3
    assert metadata.seed == 7
    assert metadata.hyperparameters["n_estimators"] == 25


def test_monotone_pairs_empareja_o_vacio() -> None:
    """Empareja nombres con constraints en orden de columnas; sin constraints devuelve ``()``."""
    challenger = _fake_challenger(monotone_constraints_=(-1, 0), feature_names_in_=("a", "b"))
    assert _monotone_pairs(challenger) == (("a", -1), ("b", 0))
    assert _monotone_pairs(_fake_challenger()) == ()


def test_top_importances_respeta_toggle_y_top_k() -> None:
    """Publica top-k descendente o ``()`` según ``publish_feature_importances``."""
    challenger = _fake_challenger(feature_importances_={"a": 0.2, "b": 0.9, "c": 0.5})
    cfg = _rf_config(output=MLOutputConfig(top_k_importances=2))
    assert _top_importances(challenger, cfg) == (("b", 0.9), ("c", 0.5))
    cfg_off = _rf_config(output=MLOutputConfig(publish_feature_importances=False))
    assert _top_importances(challenger, cfg_off) == ()


def test_hyperparameters_dict_es_escalar() -> None:
    """Los hiperparámetros del backend se vuelcan a un dict de escalares para la metadata."""
    params = _hyperparameters_dict(_rf_config())
    assert params["n_estimators"] == 25
    assert params["min_samples_leaf"] == 2


# ═══════════════════════════ requires dinámicos y lectura de artefactos ═══════════════════════════
def test_requires_dinamicos_por_feature_source_y_monotonia() -> None:
    """``requires`` incluye tablas de binning sólo con ``from_binning`` (CT-1, §2/§6)."""
    binning_from = set(_requires_for(_rf_config(monotonic=MonotonicConfig(mode="from_binning"))))
    assert ("binning", "tables") in binning_from
    assert ("binning", "woe_frame") in binning_from

    binning_off = set(_requires_for(_rf_config(monotonic=MonotonicConfig(mode="off"))))
    assert ("binning", "tables") not in binning_off

    selection = set(
        _requires_for(
            _rf_config(feature_source="selection_woe", monotonic=MonotonicConfig(mode="off"))
        )
    )
    assert ("selection", "selected_woe_frame") in selection
    assert ("selection", "selected_woe_columns") in selection

    data_raw = set(_requires_for(MLConfig(backend="xgboost", feature_source="data_raw")))
    assert ("data", "frame") in data_raw


def test_ml_config_from_study_resuelve_fuente() -> None:
    """Lee ``config.ml`` como ``MLConfig``, dict o ``None`` (fallback al config del paso)."""
    fallback = _rf_config()
    none_study = types.SimpleNamespace(config=types.SimpleNamespace(ml=None))
    assert _ml_config_from_study(none_study, fallback=fallback) is fallback

    typed = _rf_config(monotonic=MonotonicConfig(mode="off"))
    typed_study = types.SimpleNamespace(config=types.SimpleNamespace(ml=typed))
    assert _ml_config_from_study(typed_study, fallback=fallback) is typed

    dict_study = types.SimpleNamespace(
        config=types.SimpleNamespace(ml={"backend": "random_forest"})
    )
    resolved = _ml_config_from_study(dict_study, fallback=fallback)
    assert isinstance(resolved, MLConfig)
    assert resolved.backend == "random_forest"


def test_calibration_config_from_study_resuelve_fuente() -> None:
    """Lee ``config.calibration`` como config, dict o ``None`` (default)."""
    from nikodym.calibration.config import CalibrationConfig

    none_study = types.SimpleNamespace(config=types.SimpleNamespace(calibration=None))
    assert isinstance(_calibration_config_from_study(none_study), CalibrationConfig)

    typed = CalibrationConfig()
    typed_study = types.SimpleNamespace(config=types.SimpleNamespace(calibration=typed))
    assert _calibration_config_from_study(typed_study) is typed

    dict_study = types.SimpleNamespace(
        config=types.SimpleNamespace(calibration={"target_pd": 0.03})
    )
    resolved = _calibration_config_from_study(dict_study)
    assert isinstance(resolved, CalibrationConfig)
    assert resolved.target_pd == pytest.approx(0.03)


def test_read_frame_metadata_valida_contrato() -> None:
    """``labels``/``splits`` deben exponer ``target_col``/``partition_col`` como ``str``."""
    ok = types.SimpleNamespace()
    ok.artifacts = _FakeStore(
        {
            ("data", "labels"): types.SimpleNamespace(target_col="target"),
            ("data", "splits"): types.SimpleNamespace(partition_col="partition"),
        }
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
    with pytest.raises(MLDataError, match="target_col"):
        _read_frame_metadata(bad_labels)

    bad_splits = types.SimpleNamespace(
        artifacts=_FakeStore(
            {
                ("data", "labels"): types.SimpleNamespace(target_col="target"),
                ("data", "splits"): types.SimpleNamespace(partition_col=123),
            }
        )
    )
    with pytest.raises(MLDataError, match="partition_col"):
        _read_frame_metadata(bad_splits)


def test_read_champion_frame_exige_columnas() -> None:
    """``model.raw_pd_frame`` sin ``linear_predictor``/``pd_raw`` levanta ``MLDataError``."""
    frame = pd.DataFrame({"partition": ["desarrollo"], "target": [0]})
    study = types.SimpleNamespace(artifacts=_FakeStore({("model", "raw_pd_frame"): frame}))
    with pytest.raises(MLDataError, match="columnas requeridas"):
        _read_champion_frame(study, "target", "partition", pd)


def test_read_woe_column_map_y_tables_validan_tipo() -> None:
    """``binning.result``/``binning.tables`` deben traer estructuras no vacías del tipo correcto."""
    bad_map = types.SimpleNamespace(
        artifacts=_FakeStore({("binning", "result"): types.SimpleNamespace(woe_column_map={})})
    )
    with pytest.raises(MLDataError, match="woe_column_map"):
        _read_woe_column_map(bad_map)

    bad_tables = types.SimpleNamespace(artifacts=_FakeStore({("binning", "tables"): []}))
    with pytest.raises(MLDataError, match="tablas WoE"):
        _read_binning_tables(bad_tables)


def test_validate_features_rechaza_colisiones_y_faltantes() -> None:
    """Valida columnas presentes y sin colisión con partición/target."""
    frame = pd.DataFrame({"partition": ["a"], "target": [0], "f0__woe": [1.0]})
    _validate_features(frame, ("f0__woe",), "target", "partition")
    with pytest.raises(MLDataError, match="features WoE"):
        _validate_features(frame, (), "target", "partition")
    with pytest.raises(MLDataError, match="estructural"):
        _validate_features(frame.drop(columns=["partition"]), ("f0__woe",), "target", "partition")
    with pytest.raises(MLDataError, match="columnas de features"):
        _validate_features(frame, ("ausente__woe",), "target", "partition")
    with pytest.raises(MLDataError, match="partición ni el target"):
        _validate_features(frame, ("target",), "target", "partition")


def test_as_dataframe_y_string_tuple_validan_tipo() -> None:
    """Los validadores de artefactos rechazan tipos incorrectos con ``MLDataError``."""
    assert isinstance(_as_dataframe(pd.DataFrame({"a": [1]}), pd, "x"), pd.DataFrame)
    with pytest.raises(MLDataError, match="DataFrame"):
        _as_dataframe(object(), pd, "x")
    assert _as_string_tuple(["a", "b"], "cols") == ("a", "b")
    with pytest.raises(MLDataError, match="tuple"):
        _as_string_tuple([1, 2], "cols")


# ═══════════════════════════ reúso e import liviano (SDD-12 §11) ═══════════════════════════
def test_no_reimplementa_metricas_ni_importa_shap_optuna() -> None:
    """El step reúsa los evaluadores/calibrador y no reimplementa métricas ni importa SHAP."""
    source = Path(ml_step.__file__).read_text(encoding="utf-8")
    for banned in (
        "roc_auc_score",
        "roc_curve",
        "import shap",
        "import optuna",
        "def _auc",
        "def _psi",
    ):
        assert banned not in source, f"token prohibido en ml.step: {banned}"
    assert "PerformanceEvaluator" in source
    assert "StabilityEvaluator" in source
    assert "PDCalibrator" in source


def test_e2e_monotonia_explicita() -> None:
    """``monotonic.mode='explicit'`` reenvía el mapa del usuario tal cual al estimador."""
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="explicit", explicit={"f0__woe": -1})))
    study.run(["ml"])
    valores = _decisions(study, "ml_monotonic")
    assert valores[0]["config_mode"] == "explicit"
    assert valores[0]["effective_mode"] == "explicit"
    assert valores[0]["free_features"] == []


def test_comparacion_solo_psi() -> None:
    """Con ``metrics=('psi',)`` sólo se emiten brechas de estabilidad (rama sin discriminación)."""
    study = _study(
        _rf_config(
            monotonic=MonotonicConfig(mode="off"),
            comparison=MLComparisonConfig(metrics=("psi",)),
        )
    )
    study.run(["ml"])
    comparison = study.artifacts.get("ml", "comparison")
    assert comparison
    assert all(record.metric == "psi" for record in comparison)


def test_comparacion_solo_auc_ignora_particion_sin_datos() -> None:
    """Con ``metrics=('auc',)`` y una partición fantasma se omite el record no evaluable (§6)."""
    study = _study(
        _rf_config(
            monotonic=MonotonicConfig(mode="off"),
            comparison=MLComparisonConfig(
                metrics=("auc",),
                partitions=("desarrollo", "holdout", "oot", "fantasma"),
            ),
        )
    )
    study.run(["ml"])
    comparison = study.artifacts.get("ml", "comparison")
    assert all(record.metric == "auc" for record in comparison)
    assert "fantasma" not in {record.partition for record in comparison}


def test_emit_delega_al_sink() -> None:
    """``MLStep.emit`` reenvía el evento al ``AuditSink`` inyectado (contrato de sink futuro)."""
    from datetime import UTC, datetime

    from nikodym.core.audit import AuditEvent

    sink = InMemoryAuditSink()
    step = MLStep.from_config(_rf_config())
    step._audit = sink
    event = AuditEvent(kind="decision", step="ml", payload={"regla": "x"}, ts=datetime.now(UTC))
    step.emit(event)
    assert sink.events[-1] is event


def test_import_ml_es_liviano() -> None:
    """``import nikodym.ml`` no arrastra pandas/numpy ni los backends ML (§9)."""
    code = (
        "import nikodym.ml, sys; "
        "heavy = [m for m in ('pandas','numpy','sklearn','xgboost','lightgbm','catboost') "
        "if m in sys.modules]; "
        "assert not heavy, heavy"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# ═══════════════════════════ consumo opcional de tuning (deuda B-ML-TUN, SDD-13 §6) ═══════════════
def test_e2e_consume_tuning_best_config_usa_theta_estrella() -> None:
    """Con ``('tuning','best_config')`` presente, ``ml`` usa θ* y difiere del baseline."""
    baseline = _study(_rf_config(monotonic=MonotonicConfig(mode="off")))
    baseline.run(["ml"])

    ml_cfg = _rf_config(monotonic=MonotonicConfig(mode="off"))
    study = _study(ml_cfg)
    best_config = ml_cfg.model_copy(
        update={
            "hyperparameters": RandomForestParams(n_estimators=3, max_depth=1, min_samples_leaf=8)
        }
    )
    study.artifacts.set("tuning", "best_config", best_config)
    study.run(["ml"])

    metadata = study.artifacts.get("ml", "backend_metadata")
    assert metadata.hyperparameters["n_estimators"] == 3
    assert metadata.hyperparameters["max_depth"] == 1
    valores = _decisions(study, "ml_backend")
    assert valores[0]["hyperparameters_source"] == "tuning"
    assert valores[0]["hyperparameters"]["n_estimators"] == 3
    assert study.artifacts.get("ml", "card").summary["hyperparameters_source"] == "tuning"
    # θ* degenerado ⇒ predicciones distintas al baseline sin tuning (rev. aditiva real).
    base_pd = baseline.artifacts.get("ml", "pd_frame")["pd_hat"].to_numpy()
    tuned_pd = study.artifacts.get("ml", "pd_frame")["pd_hat"].to_numpy()
    assert not np.allclose(base_pd, tuned_pd)


def test_e2e_sin_tuning_source_config_intacto() -> None:
    """Sin ``('tuning','best_config')``, ``ml`` usa ``cfg.hyperparameters`` y marca ``config``."""
    study = _study(_rf_config(monotonic=MonotonicConfig(mode="off")))
    study.run(["ml"])

    metadata = study.artifacts.get("ml", "backend_metadata")
    assert metadata.hyperparameters["n_estimators"] == 25  # el de la config manual, no tuneado
    assert _decisions(study, "ml_backend")[0]["hyperparameters_source"] == "config"
    assert study.artifacts.get("ml", "card").summary["hyperparameters_source"] == "config"


def test_apply_tuning_best_config_sustituye_solo_hyperparameters() -> None:
    """Presente ⇒ toma **sólo** ``best_config.hyperparameters``; ausente ⇒ ``cfg`` intacto."""
    ml_cfg = _rf_config(monotonic=MonotonicConfig(mode="off"))

    # ausente: cfg intacto y source='config' (misma instancia, sin copia).
    empty = types.SimpleNamespace(artifacts=_FakeStore({}))
    same, source_absent = _apply_tuning_best_config(empty, ml_cfg)
    assert source_absent == "config"
    assert same is ml_cfg

    # presente y divergente en más que hyperparameters: sólo se toman los hyperparameters (θ*).
    divergent = ml_cfg.model_copy(
        update={
            "feature_source": "selection_woe",
            "hyperparameters": RandomForestParams(n_estimators=9),
        }
    )
    present = types.SimpleNamespace(artifacts=_FakeStore({("tuning", "best_config"): divergent}))
    effective, source_present = _apply_tuning_best_config(present, ml_cfg)
    assert source_present == "tuning"
    assert effective.hyperparameters.n_estimators == 9
    assert effective.feature_source == ml_cfg.feature_source == "binning_woe"


def test_as_ml_config_rechaza_tipo_invalido() -> None:
    """``tuning.best_config`` que no sea ``MLConfig`` levanta ``MLDataError`` (defensivo)."""
    ml_cfg = _rf_config()
    assert _as_ml_config(ml_cfg) is ml_cfg
    with pytest.raises(MLDataError, match="MLConfig"):
        _as_ml_config(object())


# ═══════════════════════════ utilidades de test ═══════════════════════════
class _FakeStore:
    """``ArtifactStore`` mínimo para tests unitarios de lectores (sólo ``get``)."""

    def __init__(self, data: dict[tuple[str, str], Any]) -> None:
        self._data = data

    def get(self, domain: str, key: str) -> Any:
        return self._data[(domain, key)]

    def has(self, domain: str, key: str) -> bool:
        return (domain, key) in self._data
