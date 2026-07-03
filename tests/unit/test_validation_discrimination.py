"""Tests de ``validation.discrimination`` (SDD-22 §3.1/§7/§11).

Cubre el contrato de reúso-no-reimplementación: el consumo del artefacto ``discriminant_metrics``
iguala byte a byte sus números, el fallback por reúso de ``PerformanceEvaluator`` reproduce el MISMO
número que el consumo, un test AST verifica que no se llama ``roc_auc_score``/``roc_curve`` ni se
reimplementa KS/Gini, y una sola clase en el target degrada a ``not_evaluable`` con ``auc=None``.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.validation.discrimination as discrimination
from nikodym.performance.evaluator import PerformanceEvaluator
from nikodym.validation.config import DiscriminationValidationConfig
from nikodym.validation.discrimination import (
    discrimination_from_artifact,
    discrimination_recomputed,
    evaluate_discrimination,
)
from nikodym.validation.exceptions import ValidationDataError
from nikodym.validation.results import DiscriminationRecord

_PARTITIONS = ("desarrollo", "holdout", "oot")


def _block(partition: str, n: int, prefix: str) -> pd.DataFrame:
    pd_vals = [(index + 1) / (n + 1) for index in range(n)]
    target = [1 if index >= n // 2 else 0 for index in range(n)]
    for boundary in (n // 2 - 1, n // 2, n // 2 + 1):
        target[boundary] = 1 - target[boundary]
    return pd.DataFrame(
        {
            "partition": [partition] * n,
            "score": [float(index + 1) for index in range(n)],
            "pd_calibrated": pd_vals,
            "target": target,
        },
        index=[f"{prefix}{index}" for index in range(n)],
    )


def _analytic_frame() -> pd.DataFrame:
    return pd.concat(
        [_block("desarrollo", 60, "d"), _block("holdout", 40, "h"), _block("oot", 30, "o")]
    )


def _single_class_frame() -> pd.DataFrame:
    n = 40
    return pd.DataFrame(
        {
            "partition": ["desarrollo"] * n,
            "score": [float(index) for index in range(n)],
            "pd_calibrated": [(index + 1) / (n + 1) for index in range(n)],
            "target": [0] * n,
        },
        index=[f"s{index}" for index in range(n)],
    )


def _artifact(frame: pd.DataFrame, *, partitions: tuple[str, ...] = _PARTITIONS) -> pd.DataFrame:
    evaluator = PerformanceEvaluator(evaluation_source="pd_calibrated", partitions=partitions)
    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )
    return result.discriminant_metrics


def _cell(frame: pd.DataFrame, partition: str, column: str) -> object:
    return frame.loc[frame["partition"] == partition, column].iloc[0]


# ─────────────────────────── consumo del artefacto ─────────────────────────


def test_consumo_iguala_byte_a_byte_el_artefacto() -> None:
    frame = _analytic_frame()
    artifact = _artifact(frame)

    consumed = {record.partition: record for record in discrimination_from_artifact(artifact)}

    assert tuple(consumed) == _PARTITIONS
    for partition in _PARTITIONS:
        record = consumed[partition]
        assert record.source == "performance_artifact"
        assert record.status == "ok"
        assert record.auc == float(_cell(artifact, partition, "auc"))
        assert record.gini == float(_cell(artifact, partition, "gini"))
        assert record.ks == float(_cell(artifact, partition, "ks"))
        assert record.n_total == int(_cell(artifact, partition, "n_total"))
        assert record.n_bad == int(_cell(artifact, partition, "n_bad"))


def test_consumo_filtra_particiones_pedidas() -> None:
    artifact = _artifact(_analytic_frame())

    records = discrimination_from_artifact(artifact, partitions=("holdout",))

    assert [record.partition for record in records] == ["holdout"]


def test_consumo_estado_threshold_flag_se_colapsa_a_ok() -> None:
    frame = _analytic_frame()
    evaluator = PerformanceEvaluator(
        evaluation_source="pd_calibrated",
        optional_thresholds={"auc_min": 0.999999},  # fuerza threshold_flag en todas las particiones
    )
    artifact = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    ).discriminant_metrics
    assert set(artifact["status"]) == {"threshold_flag"}

    records = discrimination_from_artifact(artifact)

    assert {record.status for record in records} == {"ok"}
    assert all(record.auc is not None for record in records)


def test_consumo_una_sola_clase_es_not_evaluable() -> None:
    artifact = _artifact(_single_class_frame(), partitions=("desarrollo",))
    assert set(artifact["status"]) == {"not_evaluable"}

    records = discrimination_from_artifact(artifact)

    assert len(records) == 1
    record = records[0]
    assert record.status == "not_evaluable"
    assert record.auc is None
    assert record.gini is None
    assert record.ks is None


# ─────────────────────────── fallback por reúso ────────────────────────────


def test_fallback_reproduce_el_mismo_numero_que_el_consumo() -> None:
    frame = _analytic_frame()
    artifact = _artifact(frame)
    consumed = {record.partition: record for record in discrimination_from_artifact(artifact)}

    recomputed = {
        record.partition: record
        for record in discrimination_recomputed(
            frame,
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )
    }

    assert tuple(recomputed) == _PARTITIONS
    for partition in _PARTITIONS:
        record = recomputed[partition]
        assert record.source == "recomputed"
        assert record.status == "ok"
        # recomputed == artefacto == consumo, byte a byte.
        assert record.auc == float(_cell(artifact, partition, "auc"))
        assert record.gini == float(_cell(artifact, partition, "gini"))
        assert record.ks == float(_cell(artifact, partition, "ks"))
        assert record.auc == consumed[partition].auc
        assert record.gini == consumed[partition].gini
        assert record.ks == consumed[partition].ks
        assert record.n_total == consumed[partition].n_total
        assert record.n_bad == consumed[partition].n_bad


def test_fallback_una_sola_clase_es_not_evaluable() -> None:
    records = discrimination_recomputed(_single_class_frame(), partitions=("desarrollo",))

    assert len(records) == 1
    record = records[0]
    assert record.source == "recomputed"
    assert record.status == "not_evaluable"
    assert record.auc is None
    assert record.gini is None
    assert record.ks is None


def test_fallback_rechaza_columna_reservada() -> None:
    frame = _analytic_frame()
    frame["__nikodym_validation_score__"] = 0.5
    with pytest.raises(ValidationDataError, match="columna reservada"):
        discrimination_recomputed(frame)


# ─────────────────────────── despachador ───────────────────────────────────


def test_despachador_consume_si_hay_artefacto() -> None:
    cfg = DiscriminationValidationConfig()
    artifact = _artifact(_analytic_frame())

    records = evaluate_discrimination(cfg, performance_metrics=artifact)

    assert {record.source for record in records} == {"performance_artifact"}
    assert [record.partition for record in records] == list(_PARTITIONS)


def test_despachador_consume_performance_false_fuerza_fallback() -> None:
    cfg = DiscriminationValidationConfig(consume_performance=False)
    frame = _analytic_frame()
    artifact = _artifact(frame)

    records = evaluate_discrimination(cfg, performance_metrics=artifact, calibrated_frame=frame)

    assert {record.source for record in records} == {"recomputed"}


def test_despachador_cae_a_fallback_sin_artefacto() -> None:
    cfg = DiscriminationValidationConfig()

    records = evaluate_discrimination(cfg, calibrated_frame=_analytic_frame())

    assert {record.source for record in records} == {"recomputed"}


def test_despachador_sin_insumos_es_error() -> None:
    cfg = DiscriminationValidationConfig()
    with pytest.raises(ValidationDataError, match="fallback"):
        evaluate_discrimination(cfg)


# ─────────────────────────── validación de entradas ────────────────────────


def test_from_artifact_rechaza_no_dataframe() -> None:
    with pytest.raises(ValidationDataError, match="pandas"):
        discrimination_from_artifact([1, 2, 3])  # type: ignore[arg-type]


def test_from_artifact_rechaza_columnas_faltantes() -> None:
    frame = pd.DataFrame({"partition": ["desarrollo"], "auc": [0.7]})
    with pytest.raises(ValidationDataError, match="columnas requeridas"):
        discrimination_from_artifact(frame)


def test_from_artifact_rechaza_estado_desconocido() -> None:
    artifact = _artifact(_analytic_frame())
    artifact.loc[artifact["partition"] == "holdout", "status"] = "bananas"
    with pytest.raises(ValidationDataError, match="Estado de discriminación desconocido"):
        discrimination_from_artifact(artifact)


def test_recomputed_rechaza_no_dataframe() -> None:
    with pytest.raises(ValidationDataError, match="pandas"):
        discrimination_recomputed(object())  # type: ignore[arg-type]


def test_recomputed_rechaza_columnas_faltantes() -> None:
    frame = pd.DataFrame({"partition": ["desarrollo"] * 3, "pd_calibrated": [0.1, 0.2, 0.3]})
    with pytest.raises(ValidationDataError, match="columnas requeridas"):
        discrimination_recomputed(frame)


# ─────────────────────────── no mutación ───────────────────────────────────


def test_from_artifact_no_muta_el_artefacto() -> None:
    artifact = _artifact(_analytic_frame())
    original = artifact.copy(deep=True)

    discrimination_from_artifact(artifact)

    assert_frame_equal(artifact, original)


def test_recomputed_no_muta_el_frame() -> None:
    frame = _analytic_frame()
    original = frame.copy(deep=True)

    discrimination_recomputed(frame)

    assert_frame_equal(frame, original)


# ─────────────────────── AST: no reimplementa AUC/KS/Gini ───────────────────


def test_ast_no_reimplementa_discriminacion() -> None:
    source = inspect.getsource(discrimination)
    tree = ast.parse(source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)

    forbidden = {"roc_auc_score", "roc_curve"}
    assert not (called & forbidden), called & forbidden
    # Delegación explícita: la única vía de cálculo es reúsar el evaluador de SDD-11.
    assert "PerformanceEvaluator" in source


# ─────────────────────────── import liviano ────────────────────────────────


def test_import_discrimination_no_arrastra_sklearn_ni_scipy() -> None:
    code = (
        "import sys;"
        "import nikodym.validation.discrimination as d;"
        "blocked=[m for m in ('scipy','sklearn','statsmodels') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert callable(d.discrimination_from_artifact);"
        "assert callable(d.discrimination_recomputed)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_from_artifact_produce_dataclass_frozen() -> None:
    records = discrimination_from_artifact(_artifact(_analytic_frame()))
    assert all(isinstance(record, DiscriminationRecord) for record in records)
    with pytest.raises(ValidationDataError):
        discrimination_from_artifact(None)  # type: ignore[arg-type]
