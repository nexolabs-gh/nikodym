"""Tests de resultados de ``ml``: DTOs puros del challenger, orden estable e import liviano."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.ml.results as ml_results
from nikodym.core.base import NikodymClassifier
from nikodym.ml.results import (
    MLBackendMetadata,
    MLCardSection,
    MLComparisonRecord,
    MLResult,
)


class _FakeChallenger(NikodymClassifier):
    """Emula el ``MLChallenger`` (subclase de ``NikodymClassifier``) que crea B12.4."""


# ── MLComparisonRecord ──────────────────────────────────────────────────────────────────────────
def test_comparison_record_golden_normaliza_menos_cero_frozen_y_extra() -> None:
    record = _comparison_record(champion_value=-0.0, challenger_value=-0.0, delta=-0.0)

    assert tuple(MLComparisonRecord.model_fields) == (
        "partition",
        "metric",
        "champion_value",
        "challenger_value",
        "delta",
        "better",
        "source",
    )
    assert record.model_dump(mode="json") == {
        "partition": "holdout",
        "metric": "auc",
        "champion_value": 0.0,
        "challenger_value": 0.0,
        "delta": 0.0,
        "better": "challenger",
        "source": "performance_evaluator",
    }
    assert math.copysign(1.0, record.champion_value) == 1.0

    with pytest.raises(ValidationError, match="frozen"):
        record.delta = 1.0
    with pytest.raises(ValidationError):
        _comparison_record(better="best")
    with pytest.raises(ValidationError):
        _comparison_record(origen="x")


def test_comparison_record_valida_partition_y_finitud() -> None:
    with pytest.raises(ValidationError, match="partition no puede estar"):
        _comparison_record(partition="  ")
    with pytest.raises(ValidationError, match="finitas"):
        _comparison_record(delta=float("nan"))
    with pytest.raises(ValidationError, match="números reales"):
        _comparison_record(champion_value=True)


def test_comparison_record_coherencia_metric_source() -> None:
    stability = _comparison_record(metric="psi", source="stability_evaluator")
    assert stability.source == "stability_evaluator"

    with pytest.raises(ValidationError, match="stability_evaluator"):
        _comparison_record(metric="psi", source="performance_evaluator")
    with pytest.raises(ValidationError, match="performance_evaluator"):
        _comparison_record(metric="auc", source="stability_evaluator")


# ── MLBackendMetadata ───────────────────────────────────────────────────────────────────────────
def test_backend_metadata_golden_orden_importances_y_copia() -> None:
    metadata = _backend_metadata(
        hyperparameters={"n_estimators": 500, "learning_rate": -0.0, "booster": "gbtree"},
        feature_importances=[("edad", 0.4), ("saldo", 0.4), ("mora", 0.9)],
        monotone_constraints=[("saldo", -1), ("edad", 0)],
    )

    assert tuple(MLBackendMetadata.model_fields) == (
        "backend",
        "backend_version",
        "hyperparameters",
        "seed",
        "n_threads",
        "deterministic",
        "best_iteration",
        "feature_importances",
        "monotone_constraints",
    )
    assert metadata.model_dump(mode="json") == {
        "backend": "xgboost",
        "backend_version": "2.0.3",
        "hyperparameters": {"booster": "gbtree", "learning_rate": 0.0, "n_estimators": 500},
        "seed": 7,
        "n_threads": 1,
        "deterministic": True,
        "best_iteration": 42,
        # Orden estable: descendente por valor, desempate lexicográfico (edad < saldo).
        "feature_importances": [["mora", 0.9], ["edad", 0.4], ["saldo", 0.4]],
        # monotone_constraints preserva el orden de columnas de X (no se ordena).
        "monotone_constraints": [["saldo", -1], ["edad", 0]],
    }
    # Los tipos escalares de los hiperparámetros sobreviven (int/float/str, sin coerción a bool).
    assert isinstance(metadata.hyperparameters["n_estimators"], int)
    assert metadata.hyperparameters["n_estimators"] is not True

    copia = metadata.hyperparameters
    copia["n_estimators"] = 1
    assert metadata.hyperparameters["n_estimators"] == 500


def test_backend_metadata_hyperparameters_tipos_y_no_finito() -> None:
    metadata = _backend_metadata(
        hyperparameters={"s": "rbf", "i": 3, "f": -0.0, "b": True, "n": None}
    )
    assert metadata.model_dump(mode="json")["hyperparameters"] == {
        "b": True,
        "f": 0.0,
        "i": 3,
        "n": None,
        "s": "rbf",
    }

    with pytest.raises(ValidationError, match="deben ser finitos"):
        _backend_metadata(hyperparameters={"lr": float("inf")})
    with pytest.raises(ValidationError):
        _backend_metadata(hyperparameters=[("a", 1)])


def test_backend_metadata_importances_validaciones() -> None:
    metadata = _backend_metadata(feature_importances={"saldo": 0.6, "edad": 0.4})
    assert metadata.feature_importances == (("saldo", 0.6), ("edad", 0.4))
    assert _backend_metadata(feature_importances=[("saldo", -0.0)]).feature_importances == (
        ("saldo", 0.0),
    )

    with pytest.raises(ValidationError, match="repetir la feature"):
        _backend_metadata(feature_importances=[("saldo", 0.1), ("saldo", 0.2)])
    with pytest.raises(ValidationError, match="no pueden ser negativas"):
        _backend_metadata(feature_importances=[("saldo", -0.1)])
    with pytest.raises(ValidationError, match="NaN ni inf"):
        _backend_metadata(feature_importances=[("saldo", float("nan"))])
    with pytest.raises(ValidationError, match="números reales"):
        _backend_metadata(feature_importances=[("saldo", True)])
    with pytest.raises(ValidationError, match="par"):
        _backend_metadata(feature_importances=[("saldo", 0.1, 0.2)])
    with pytest.raises(ValidationError):
        _backend_metadata(feature_importances=123)


def test_backend_metadata_monotone_validaciones() -> None:
    with pytest.raises(ValidationError, match="features vacías"):
        _backend_metadata(monotone_constraints=[("  ", -1)])
    with pytest.raises(ValidationError, match="repetir la feature"):
        _backend_metadata(monotone_constraints=[("saldo", -1), ("saldo", 1)])
    with pytest.raises(ValidationError, match="-1, 0 o 1"):
        _backend_metadata(monotone_constraints=[("saldo", 2)])
    with pytest.raises(ValidationError, match="par"):
        _backend_metadata(monotone_constraints=[["saldo"]])
    with pytest.raises(ValidationError):
        _backend_metadata(monotone_constraints=123)


def test_backend_metadata_invariantes_texto_seed_hilos_y_determinismo() -> None:
    assert _backend_metadata(best_iteration=None).best_iteration is None
    performance = _backend_metadata(deterministic=False, n_threads=4)
    assert performance.n_threads == 4

    with pytest.raises(ValidationError, match="no pueden estar"):
        _backend_metadata(backend="   ")
    with pytest.raises(ValidationError, match="best_iteration no puede"):
        _backend_metadata(best_iteration=-1)
    with pytest.raises(ValidationError, match="exige n_threads=1"):
        _backend_metadata(deterministic=True, n_threads=2)
    with pytest.raises(ValidationError):
        _backend_metadata(seed=-1)
    with pytest.raises(ValidationError):
        _backend_metadata(n_threads=0)
    with pytest.raises(ValidationError):
        _backend_metadata(extra_field="x")
    with pytest.raises(ValidationError, match="frozen"):
        _backend_metadata().seed = 9


# ── MLCardSection ───────────────────────────────────────────────────────────────────────────────
def test_card_section_golden_ct2_copias_frozen_y_extra() -> None:
    metric_sections: dict[str, Any] = {
        "comparison_curves": {
            "holdout": {"auc": 0.74321, "neg_zero": -0.0, "bad": float("nan")},
            "flags": ["ok", ("t", 1)],
            "label": "curva",
            "count": 3,
        }
    }
    summary: dict[str, Any] = {"backend": "xgboost", "auc_holdout": -0.0, "reproducible": True}
    card = MLCardSection(
        summary=summary,
        metric_sections=metric_sections,
        assumptions=("WoE consistente",),
        limitations=("no reemplaza campeón",),
    )

    assert tuple(MLCardSection.model_fields) == (
        "summary",
        "metric_sections",
        "assumptions",
        "limitations",
    )
    assert card.summary == {"backend": "xgboost", "auc_holdout": 0.0, "reproducible": True}
    assert card.metric_sections == {
        "comparison_curves": {
            "holdout": {"auc": 0.74321, "neg_zero": 0.0, "bad": None},
            "flags": ["ok", ("t", 1)],
            "label": "curva",
            "count": 3,
        }
    }

    # Copia a la lectura + desacople del input: nada muta el DTO frozen.
    summary["backend"] = "mutado"
    metric_sections["comparison_curves"]["holdout"]["auc"] = 99.0
    card.summary["backend"] = "mutado"
    card.metric_sections["comparison_curves"]["holdout"]["auc"] = 99.0
    assert card.summary["backend"] == "xgboost"
    assert card.metric_sections["comparison_curves"]["holdout"]["auc"] == 0.74321

    with pytest.raises(ValidationError, match="frozen"):
        card.assumptions = ()
    with pytest.raises(ValidationError):
        MLCardSection(summary={}, metric_sections={}, extra="x")


def test_card_section_defaults_none_y_no_mapping() -> None:
    card = MLCardSection(summary={"backend": "svm"})
    assert card.metric_sections == {}
    assert card.assumptions == ()
    assert card.limitations == ()
    assert MLCardSection(summary={"backend": "svm"}, metric_sections=None).metric_sections == {}

    with pytest.raises(ValidationError, match="finitos"):
        MLCardSection(summary={"x": float("nan")})
    with pytest.raises(ValidationError):
        MLCardSection(summary=[1, 2])
    with pytest.raises(ValidationError):
        MLCardSection(summary={}, metric_sections=[1, 2])


# ── MLResult ────────────────────────────────────────────────────────────────────────────────────
def test_result_golden_copias_defensivas_frozen_y_extra() -> None:
    frame = _pd_frame()
    result = _result(pd_frame=frame)

    assert tuple(MLResult.model_fields) == (
        "estimator",
        "pd_frame",
        "calibrated_pd_frame",
        "comparison",
        "backend_metadata",
        "card",
    )
    assert isinstance(result.estimator, _FakeChallenger)
    assert result.calibrated_pd_frame is None
    assert result.term_structure() is None

    # -0.0 normalizado en columna float; copia defensiva a la lectura y frente al input.
    assert math.copysign(1.0, result.pd_frame.at[1, "pd_hat"]) == 1.0
    frame.at[0, "pd_hat"] = 99.0
    returned = result.pd_frame
    returned.at[0, "pd_hat"] = 88.0
    assert result.pd_frame.at[0, "pd_hat"] == 0.8

    with pytest.raises(ValidationError, match="frozen"):
        result.pd_frame = _pd_frame()
    with pytest.raises(ValidationError):
        _result(extra="x")
    with pytest.raises(ValidationError):
        _result(estimator=123)
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(pd_frame=123)


def test_result_calibrated_pd_frame_copiado_o_none() -> None:
    calibrated = pd.DataFrame({"partition": ["holdout"], "pd_calibrated": [0.0]})
    result = _result(calibrated_pd_frame=calibrated)

    assert math.copysign(1.0, result.calibrated_pd_frame.at[0, "pd_calibrated"]) == 1.0
    calibrated.at[0, "pd_calibrated"] = 99.0
    returned = result.calibrated_pd_frame
    returned.at[0, "pd_calibrated"] = 88.0
    assert result.calibrated_pd_frame.at[0, "pd_calibrated"] == 0.0

    with pytest.raises(ValidationError, match="DataFrame o None"):
        _result(calibrated_pd_frame=123)


def test_result_copy_dataframe_columna_float_sin_ceros() -> None:
    frame = pd.DataFrame({"partition": ["holdout"], "pd_hat": [0.7]})
    result = _result(pd_frame=frame)
    assert result.pd_frame.at[0, "pd_hat"] == 0.7


def test_result_comparison_unicidad() -> None:
    duplicado = (_comparison_record(), _comparison_record())
    with pytest.raises(ValidationError, match="repetir"):
        _result(comparison=duplicado)


def test_result_comparison_frame_tidy_y_orden() -> None:
    comparison = (
        _comparison_record(metric="auc", champion_value=0.70, challenger_value=0.74, delta=0.04),
        _comparison_record(
            metric="psi",
            source="stability_evaluator",
            champion_value=0.03,
            challenger_value=0.05,
            delta=0.02,
            better="champion",
        ),
    )
    frame = _result(comparison=comparison).comparison_frame()

    expected = pd.DataFrame(
        {
            "partition": ["holdout", "holdout"],
            "metric": ["auc", "psi"],
            "champion_value": [0.70, 0.03],
            "challenger_value": [0.74, 0.05],
            "delta": [0.04, 0.02],
            "better": ["challenger", "champion"],
            "source": ["performance_evaluator", "stability_evaluator"],
        }
    )
    assert_frame_equal(frame, expected)


def test_result_comparison_frame_vacio() -> None:
    frame = _result(comparison=()).comparison_frame()
    assert list(frame.columns) == [
        "partition",
        "metric",
        "champion_value",
        "challenger_value",
        "delta",
        "better",
        "source",
    ]
    assert len(frame) == 0


def test_ml_results_import_liviano_y_all_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.ml;"
        "assert 'pandas' not in sys.modules, 'pandas';"
        "import nikodym.ml.results as r;"
        "blocked=[m for m in ('pandas','numpy','sklearn','xgboost','lightgbm','catboost') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert r.__all__ == ['Better','ComparisonMetric','ComparisonSource','MLBackendMetadata',"
        "'MLCardSection','MLComparisonRecord','MLResult'], r.__all__"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_ml_results_expone_all() -> None:
    for name in ("MLBackendMetadata", "MLCardSection", "MLComparisonRecord", "MLResult"):
        assert name in ml_results.__all__
        assert hasattr(ml_results, name)


# ── Builders ──────────────────────────────────────────────────────────────────────────────────--
def _comparison_record(**updates: Any) -> MLComparisonRecord:
    payload: dict[str, Any] = {
        "partition": "holdout",
        "metric": "auc",
        "champion_value": 0.70,
        "challenger_value": 0.74,
        "delta": 0.04,
        "better": "challenger",
        "source": "performance_evaluator",
    }
    payload.update(updates)
    return MLComparisonRecord(**payload)


def _backend_metadata(**updates: Any) -> MLBackendMetadata:
    payload: dict[str, Any] = {
        "backend": "xgboost",
        "backend_version": "2.0.3",
        "hyperparameters": {"n_estimators": 500, "learning_rate": 0.05},
        "seed": 7,
        "n_threads": 1,
        "deterministic": True,
        "best_iteration": 42,
        "feature_importances": (("saldo", 0.6), ("edad", 0.4)),
        "monotone_constraints": (("saldo", -1), ("edad", -1)),
    }
    payload.update(updates)
    return MLBackendMetadata(**payload)


def _card(**updates: Any) -> MLCardSection:
    payload: dict[str, Any] = {
        "summary": {"backend": "xgboost", "auc_holdout": 0.74},
        "metric_sections": {"comparison_curves": {"holdout": {"auc": 0.74}}},
        "assumptions": ("WoE consistente",),
        "limitations": ("no reemplaza campeón",),
    }
    payload.update(updates)
    return MLCardSection(**payload)


def _pd_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["holdout", "holdout"],
            "target": [1, 0],
            "pd_hat": [0.8, -0.0],
        }
    )


def _result(**updates: Any) -> MLResult:
    payload: dict[str, Any] = {
        "estimator": _FakeChallenger(),
        "pd_frame": _pd_frame(),
        "calibrated_pd_frame": None,
        "comparison": (_comparison_record(),),
        "backend_metadata": _backend_metadata(),
        "card": _card(),
    }
    payload.update(updates)
    return MLResult(**payload)
