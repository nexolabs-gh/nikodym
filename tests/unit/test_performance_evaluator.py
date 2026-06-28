"""Tests de ``PerformanceEvaluator``: goldens, orientación, auditoría e imports perezosos."""

from __future__ import annotations

import builtins
import math
import subprocess
import sys
import textwrap
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sklearn.base import clone

import nikodym.performance.evaluator as evaluator_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.performance.config import PerformanceConfig
from nikodym.performance.evaluator import PerformanceEvaluator
from nikodym.performance.exceptions import PerformanceDataError, PerformanceMetricError


def test_auc_gini_ks_golden_y_deciles_no_muta() -> None:
    frame = _metric_frame()
    original = frame.copy(deep=True)
    evaluator = PerformanceEvaluator(
        partitions=("desarrollo",),
        n_deciles=2,
        min_rows_per_partition=1,
    )

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )

    metric = result.discriminant_records[0]
    assert metric.auc == pytest.approx(0.75)
    assert metric.gini == pytest.approx(0.50)
    assert metric.ks == pytest.approx(0.50)
    assert metric.ks_cutoff_risk_score == pytest.approx(0.90)
    assert metric.ks_cutoff_score is None
    assert metric.tpr_at_ks == pytest.approx(0.50)
    assert metric.fpr_at_ks == pytest.approx(0.0)
    assert metric.status == "ok"
    assert metric.source == "pd_calibrated"

    table = result.performance_table
    assert tuple(table.columns) == (
        "partition",
        "decile",
        "n_total",
        "n_bad",
        "n_good",
        "bad_rate",
        "good_rate",
        "mean_pd",
        "min_pd",
        "max_pd",
        "mean_score",
        "min_score",
        "max_score",
        "cum_total",
        "cum_bad",
        "cum_good",
        "cum_bad_capture_rate",
        "cum_good_capture_rate",
        "lift",
        "ks_at_decile",
    )
    assert table["decile"].tolist() == [1, 2]
    assert table["n_bad"].tolist() == [1, 1]
    assert table["n_good"].tolist() == [1, 1]
    assert table["bad_rate"].tolist() == pytest.approx([0.5, 0.5])
    assert table["mean_pd"].tolist() == pytest.approx([0.85, 0.40])
    assert table["min_pd"].tolist() == pytest.approx([0.80, 0.10])
    assert table["max_pd"].tolist() == pytest.approx([0.90, 0.70])
    assert table["mean_score"].tolist() == pytest.approx([150.0, 350.0])
    assert table["cum_bad_capture_rate"].tolist() == pytest.approx([0.5, 1.0])
    assert table["cum_good_capture_rate"].tolist() == pytest.approx([0.5, 1.0])
    assert table["lift"].tolist() == pytest.approx([1.0, 1.0])
    assert table["ks_at_decile"].tolist() == pytest.approx([0.0, 0.0])

    assert_frame_equal(frame, original)
    assert_frame_equal(result.performance_table, evaluator.performance_table_)
    assert result.card.metric_sections["discrimination"] == {
        "effective_deciles_by_partition": {"desarrollo": 2},
        "not_evaluable_reasons_by_partition": {},
        "threshold_flags_by_partition": {},
    }
    assert {"numpy", "pandas", "scikit-learn"} <= set(result.card.dependency_versions)


def test_tabla_deciles_20_filas_golden_y_shuffle_determinista() -> None:
    frame = _twenty_row_frame()
    evaluator = PerformanceEvaluator(
        partitions=("desarrollo",),
        n_deciles=10,
        min_rows_per_partition=1,
    )

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )
    shuffled = frame.sample(frac=1.0, random_state=17)
    shuffled_result = evaluator.evaluate(
        shuffled,
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )

    assert_frame_equal(result.performance_table, shuffled_result.performance_table)
    assert_frame_equal(result.discriminant_metrics, shuffled_result.discriminant_metrics)
    assert result.discriminant_records[0].auc == pytest.approx(1.0)
    assert result.discriminant_records[0].gini == pytest.approx(1.0)
    assert result.discriminant_records[0].ks == pytest.approx(1.0)
    assert result.discriminant_records[0].ks_cutoff_risk_score == pytest.approx(0.86)

    table = result.performance_table
    assert len(table.index) == 10
    assert table["n_total"].tolist() == [2] * 10
    assert table["n_bad"].tolist() == [2, 2, 2, 2, 2, 0, 0, 0, 0, 0]
    assert table["n_good"].tolist() == [0, 0, 0, 0, 0, 2, 2, 2, 2, 2]

    first = table.iloc[0]
    assert first["bad_rate"] == pytest.approx(1.0)
    assert first["good_rate"] == pytest.approx(0.0)
    assert first["mean_pd"] == pytest.approx(0.945)
    assert first["min_pd"] == pytest.approx(0.94)
    assert first["max_pd"] == pytest.approx(0.95)
    assert first["mean_score"] == pytest.approx(300.5)
    assert first["cum_bad_capture_rate"] == pytest.approx(0.2)
    assert first["cum_good_capture_rate"] == pytest.approx(0.0)
    assert first["lift"] == pytest.approx(2.0)
    assert first["ks_at_decile"] == pytest.approx(0.2)

    fifth = table.iloc[4]
    assert fifth["cum_bad"] == 10
    assert fifth["cum_good"] == 0
    assert fifth["ks_at_decile"] == pytest.approx(1.0)

    sixth = table.iloc[5]
    assert sixth["bad_rate"] == pytest.approx(0.0)
    assert sixth["good_rate"] == pytest.approx(1.0)
    assert sixth["cum_bad_capture_rate"] == pytest.approx(1.0)
    assert sixth["cum_good_capture_rate"] == pytest.approx(0.2)
    assert sixth["lift"] == pytest.approx(0.0)
    assert sixth["ks_at_decile"] == pytest.approx(0.8)

    last = table.iloc[9]
    assert last["cum_total"] == 20
    assert last["cum_bad"] == 10
    assert last["cum_good"] == 10
    assert last["ks_at_decile"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("score_direction", "scores", "expected_risk_cutoff", "expected_score_cutoff"),
    [
        ("higher_is_lower_risk", [100.0, 200.0, 300.0, 400.0], -100.0, 100.0),
        ("higher_is_higher_risk", [0.9, 0.8, 0.7, 0.1], 0.9, 0.9),
    ],
)
def test_orientacion_score_no_invierte_auc(
    score_direction: str,
    scores: list[float],
    expected_risk_cutoff: float,
    expected_score_cutoff: float,
) -> None:
    frame = _metric_frame(score=scores)
    evaluator = PerformanceEvaluator(
        evaluation_source="score",
        score_direction=score_direction,  # type: ignore[arg-type]
        partitions=("desarrollo",),
        n_deciles=2,
        min_rows_per_partition=1,
    )

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )

    metric = result.discriminant_records[0]
    assert metric.auc == pytest.approx(0.75)
    assert metric.gini == pytest.approx(0.50)
    assert metric.ks == pytest.approx(0.50)
    assert metric.ks_cutoff_risk_score == pytest.approx(expected_risk_cutoff)
    assert metric.ks_cutoff_score == pytest.approx(expected_score_cutoff)
    assert metric.source == "score"


def test_particiones_no_evaluables_publican_none_y_auditan() -> None:
    audit = InMemoryAuditSink()
    frame = _single_class_holdout_frame()
    evaluator = PerformanceEvaluator(
        partitions=("desarrollo", "holdout", "oot"),
        n_deciles=2,
        min_rows_per_partition=1,
    )
    evaluator._audit = audit

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )

    statuses = {record.partition: record.status for record in result.discriminant_records}
    assert statuses == {
        "desarrollo": "not_evaluable",
        "holdout": "not_evaluable",
        "oot": "not_evaluable",
    }
    assert all(record.auc is None for record in result.discriminant_records)
    assert all(record.ks_cutoff_risk_score is None for record in result.discriminant_records)
    assert result.card.metric_sections["discrimination"]["not_evaluable_reasons_by_partition"] == {
        "desarrollo": "partition_empty",
        "holdout": "single_class",
        "oot": "partition_empty",
    }
    assert [event.payload["regla"] for event in audit.events] == [
        "performance_not_evaluable",
        "performance_not_evaluable",
        "performance_not_evaluable",
    ]

    table = result.performance_table
    assert table["partition"].tolist() == ["holdout", "holdout"]
    assert table["n_bad"].tolist() == [0, 0]
    assert table["n_good"].tolist() == [2, 2]
    assert table["lift"].tolist() == pytest.approx([0.0, 0.0])
    assert table["ks_at_decile"].tolist() == pytest.approx([0.0, 0.0])


def test_thresholds_opcionales_marcan_estado_y_log_decision() -> None:
    audit = InMemoryAuditSink()
    evaluator = PerformanceEvaluator(
        partitions=("desarrollo",),
        n_deciles=2,
        min_rows_per_partition=1,
        optional_thresholds={"auc_min": 0.80, "gini_min": 0.60, "ks_min": 0.40},
    )
    evaluator._audit = audit

    result = evaluator.evaluate(
        _metric_frame(),
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )

    assert result.discriminant_records[0].status == "threshold_flag"
    assert result.card.bands_by_partition == {"desarrollo": "threshold_flag"}
    assert result.card.metric_sections["discrimination"]["threshold_flags_by_partition"] == {
        "desarrollo": ["auc", "gini"]
    }
    assert [event.payload["regla"] for event in audit.events] == [
        "performance_auc_min",
        "performance_gini_min",
    ]
    assert [event.payload["accion"] for event in audit.events] == [
        "threshold_flag",
        "threshold_flag",
    ]


def test_from_config_clone_y_validacion_runtime() -> None:
    cfg = PerformanceConfig(
        score_column="score_total",
        pd_column="pd_final",
        target_column="malo_12m",
        partition_column="particion",
        evaluation_source="score",
        score_direction="higher_is_higher_risk",
        partitions=("desarrollo",),
        n_deciles=4,
        min_rows_per_partition=1,
        optional_thresholds={"auc_min": 0.60},
    )

    evaluator = PerformanceEvaluator.from_config(cfg)
    cloned = clone(evaluator)

    assert cloned.get_params()["n_deciles"] == 4
    assert cloned.get_params()["evaluation_source"] == "score"
    assert cloned.set_params(n_deciles=5).get_params()["n_deciles"] == 5
    assert PerformanceEvaluator.from_config(cfg.model_dump()).pd_column == "pd_final"

    cloned.set_params(n_deciles=1)
    with pytest.raises(ConfigError, match="PerformanceEvaluator"):
        cloned.evaluate(
            _metric_frame(),
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )

    duplicated = PerformanceEvaluator(partitions=("desarrollo", "desarrollo"))
    with pytest.raises(ConfigError, match="duplicados"):
        duplicated.evaluate(
            _metric_frame(),
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )


def test_validaciones_de_contrato_con_mensajes_propios() -> None:
    evaluator = PerformanceEvaluator(partitions=("desarrollo",), min_rows_per_partition=1)

    with pytest.raises(PerformanceDataError, match=r"pandas\.DataFrame"):
        evaluator.evaluate(  # type: ignore[arg-type]
            "no es frame",
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )

    with pytest.raises(PerformanceDataError, match="columnas requeridas"):
        evaluator.evaluate(
            _metric_frame().drop(columns=["score"]),
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )

    duplicated = pd.concat([_metric_frame(), _metric_frame()["score"]], axis=1)
    with pytest.raises(PerformanceDataError, match="duplicadas"):
        evaluator.evaluate(
            duplicated,
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )

    duplicate_index = _metric_frame()
    duplicate_index.index = ["c0", "c0", "c2", "c3"]
    with pytest.raises(PerformanceDataError, match="índice único"):
        evaluator.evaluate(
            duplicate_index,
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )

    null_partition = _metric_frame()
    null_partition.loc["c0", "partition"] = None
    with pytest.raises(PerformanceDataError, match="esquema mínimo"):
        evaluator.evaluate(
            null_partition,
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )

    invalid_target = _metric_frame().astype({"target": "float64"})
    invalid_target.loc["c0", "target"] = 0.5
    with pytest.raises(PerformanceDataError, match="binario"):
        evaluator.evaluate(
            invalid_target,
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )

    non_numeric = _metric_frame().astype({"score": "object"})
    non_numeric.loc["c0", "score"] = "alto"
    with pytest.raises(PerformanceDataError, match="float64-compatible"):
        evaluator.evaluate(
            non_numeric,
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )

    non_finite = _metric_frame()
    non_finite.loc["c0", "score"] = math.inf
    with pytest.raises(PerformanceDataError, match="finitos"):
        evaluator.evaluate(
            non_finite,
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )

    invalid_pd = _metric_frame()
    invalid_pd.loc["c0", "pd_calibrated"] = 1.0
    with pytest.raises(PerformanceDataError, match=r"\(0, 1\)"):
        evaluator.evaluate(
            invalid_pd,
            score_column="score",
            pd_column="pd_calibrated",
            target_column="target",
            partition_column="partition",
        )


def test_particion_bajo_minimos_y_modelable_vacio() -> None:
    frame = _metric_frame()
    frame["partition"] = "fuera_modelo"
    evaluator = PerformanceEvaluator(partitions=("desarrollo",), min_rows_per_partition=1)

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )

    assert result.discriminant_records[0].status == "not_evaluable"
    assert result.discriminant_records[0].n_total == 0
    assert result.performance_table.empty
    assert result.card.metric_sections["discrimination"]["effective_deciles_by_partition"] == {
        "desarrollo": 0
    }

    low_rows = PerformanceEvaluator(partitions=("desarrollo",), min_rows_per_partition=10)
    low_rows_result = low_rows.evaluate(
        _metric_frame(),
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )
    assert low_rows_result.discriminant_records[0].status == "not_evaluable"
    assert (
        low_rows_result.card.metric_sections["discrimination"][
            "not_evaluable_reasons_by_partition"
        ]["desarrollo"]
        == "below_min_rows"
    )

    low_events = PerformanceEvaluator(
        partitions=("desarrollo",),
        min_rows_per_partition=1,
        min_events_per_partition=3,
    )
    low_events_result = low_events.evaluate(
        _metric_frame(),
        score_column="score",
        pd_column="pd_calibrated",
        target_column="target",
        partition_column="partition",
    )
    assert low_events_result.discriminant_records[0].status == "not_evaluable"
    assert (
        low_events_result.card.metric_sections["discrimination"][
            "not_evaluable_reasons_by_partition"
        ]["desarrollo"]
        == "below_min_events"
    )


def test_helpers_defensivos_metricos(monkeypatch: pytest.MonkeyPatch) -> None:
    np_module = evaluator_module._import_numpy()
    pd_module = evaluator_module._import_pandas()
    cfg = PerformanceConfig(min_rows_per_partition=1, partitions=("desarrollo",))
    prepared = evaluator_module._prepare_modelable_frame(
        _metric_frame(),
        cfg=cfg,
        pd=pd_module,
        np=np_module,
    )

    class BrokenMetrics:
        @staticmethod
        def roc_auc_score(*args: Any, **kwargs: Any) -> float:
            del args, kwargs
            raise ValueError("boom auc")

        @staticmethod
        def roc_curve(*args: Any, **kwargs: Any) -> tuple[Any, Any, Any]:
            del args, kwargs
            return np_module.asarray([0.0]), np_module.asarray([0.0]), np_module.asarray([math.inf])

    with pytest.raises(PerformanceMetricError, match="ROC/AUC"):
        evaluator_module._compute_discriminant_metrics(
            prepared,
            cfg=cfg,
            sklearn_metrics=evaluator_module.SklearnMetrics(
                roc_auc_score=BrokenMetrics.roc_auc_score,
                roc_curve=BrokenMetrics.roc_curve,
            ),
            np=np_module,
        )

    with pytest.raises(PerformanceMetricError, match="cortes finitos"):
        evaluator_module._compute_discriminant_metrics(
            prepared,
            cfg=cfg,
            sklearn_metrics=evaluator_module.SklearnMetrics(
                roc_auc_score=lambda *_args, **_kwargs: 0.5,
                roc_curve=BrokenMetrics.roc_curve,
            ),
            np=np_module,
        )

    with pytest.raises(PerformanceMetricError, match="estadístico"):
        evaluator_module._series_stat(pd.Series([math.inf]), "mean")

    class FakeSchema:
        def validate(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            raise RuntimeError("boom schema")

    class FakeErrors:
        SchemaError = ValueError
        SchemaErrors = TypeError

    class FakePa:
        errors = FakeErrors

        @staticmethod
        def Column(*args: Any, **kwargs: Any) -> object:  # noqa: N802
            del args, kwargs
            return object()

        @staticmethod
        def DataFrameSchema(*args: Any, **kwargs: Any) -> FakeSchema:  # noqa: N802
            del args, kwargs
            return FakeSchema()

    with pytest.raises(RuntimeError, match="boom schema"):
        evaluator_module._validate_input_schema(
            _metric_frame(),
            cfg=cfg,
            pd=pd_module,
            pa=FakePa,
        )

    assert evaluator_module._score_cutoff_from_risk(
        3.0,
        cfg=PerformanceConfig(evaluation_source="score", score_direction="higher_is_higher_risk"),
    ) == pytest.approx(3.0)
    assert evaluator_module._safe_divide(1.0, 0.0) == 0.0
    assert evaluator_module._safe_divide(1.0, 4.0) == pytest.approx(0.25)
    assert evaluator_module._normalize_float(-0.0) == 0.0

    real_import = evaluator_module.importlib.import_module

    def block_sklearn(name: str) -> Any:
        if name == "sklearn":
            raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")
        return real_import(name)

    monkeypatch.setattr(evaluator_module.importlib, "import_module", block_sklearn)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        evaluator_module._dependency_versions()


def test_import_performance_evaluator_liviano_subprocess() -> None:
    code = textwrap.dedent(
        """
        import sys
        from nikodym.performance.evaluator import PerformanceEvaluator

        assert PerformanceEvaluator.__name__ == "PerformanceEvaluator"
        blocked = [m for m in ("pandas", "pandera", "sklearn", "scipy") if m in sys.modules]
        assert blocked == [], blocked
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_imports_perezosos_traducen_dependencias(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = evaluator_module.importlib.import_module

    def block(name: str) -> Any:
        if name in {"pandas", "numpy", "sklearn.metrics"}:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name)

    monkeypatch.setattr(evaluator_module.importlib, "import_module", block)
    for helper in (
        evaluator_module._import_pandas,
        evaluator_module._import_numpy,
        evaluator_module._import_sklearn_metrics,
    ):
        with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
            helper()

    monkeypatch.setattr(evaluator_module.importlib, "import_module", real_import)
    real_dunder_import = builtins.__import__

    def block_pandera(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pandera.pandas":
            raise ModuleNotFoundError("No module named 'pandera.pandas'", name=name)
        return real_dunder_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_pandera)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        evaluator_module._import_pandera()


def _metric_frame(*, score: list[float] | None = None) -> pd.DataFrame:
    scores = score if score is not None else [100.0, 200.0, 300.0, 400.0]
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "desarrollo", "desarrollo", "desarrollo"],
            "target": [1, 0, 1, 0],
            "score": scores,
            "pd_calibrated": [0.90, 0.80, 0.70, 0.10],
        },
        index=["c0", "c1", "c2", "c3"],
    )


def _twenty_row_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["desarrollo"] * 20,
            "target": ([1] * 10) + ([0] * 10),
            "score": [300.0 + i for i in range(20)],
            "pd_calibrated": [0.95 - (0.01 * i) for i in range(20)],
        },
        index=[f"r{i:02d}" for i in range(20)],
    )


def _single_class_holdout_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["holdout"] * 4,
            "target": [0, 0, 0, 0],
            "score": [700.0, 710.0, 720.0, 730.0],
            "pd_calibrated": [0.05, 0.04, 0.03, 0.02],
        },
        index=["h0", "h1", "h2", "h3"],
    )
