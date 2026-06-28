"""Tests de ``StabilityEvaluator``: goldens PSI/CSI/temporal, anti-leakage, auditoría e imports."""

from __future__ import annotations

import builtins
import importlib.metadata
import math
import subprocess
import sys
import textwrap
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sklearn.base import clone

import nikodym.stability.evaluator as evaluator_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.stability.config import StabilityConfig
from nikodym.stability.evaluator import StabilityEvaluator
from nikodym.stability.exceptions import StabilityDataError, StabilityMetricError

_PSI_TABLE_COLUMNS = (
    "metric",
    "comparison",
    "feature",
    "bin_label",
    "expected_count",
    "actual_count",
    "expected_pct",
    "actual_pct",
    "component_value",
    "total_value",
    "band",
)
_STABILITY_METRIC_COLUMNS = (
    "metric",
    "comparison",
    "feature",
    "value",
    "stable_threshold",
    "review_threshold",
    "band",
    "action",
)


def _by_key(records: Any) -> dict[tuple[str, str, str], Any]:
    return {(record.metric, record.comparison, record.feature): record for record in records}


def test_integracion_psi_pd_csi_goldens_card_y_no_muta() -> None:
    audit = InMemoryAuditSink()
    frame = _full_frame()
    original = frame.copy(deep=True)
    evaluator = StabilityEvaluator(
        psi_bins=2,
        temporal_axis="none",
        include_pd_stability=True,
    )
    evaluator._audit = audit

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=("f1__points", "f2__points"),
    )

    metrics = _by_key(result.metric_records)
    assert metrics[("score_psi", "dev_vs_holdout", "score")].value == pytest.approx(0.41588831)
    assert metrics[("score_psi", "dev_vs_holdout", "score")].band == "redevelop"
    assert metrics[("score_psi", "dev_vs_holdout", "score")].action == "redesarrollar"
    assert metrics[("score_psi", "dev_vs_oot", "score")].value == pytest.approx(0.0)
    assert metrics[("score_psi", "dev_vs_oot", "score")].band == "stable"
    assert metrics[("pd_psi", "dev_vs_holdout", "pd_calibrated")].value == pytest.approx(0.04054651)
    assert metrics[("pd_psi", "dev_vs_holdout", "pd_calibrated")].band == "stable"
    assert metrics[("csi", "dev_vs_holdout", "f1__points")].value == pytest.approx(0.05753641)
    assert metrics[("csi", "dev_vs_holdout", "f1__points")].band == "stable"
    assert metrics[("csi", "dev_vs_holdout", "f2__points")].value == pytest.approx(0.87888983)
    assert metrics[("csi", "dev_vs_holdout", "f2__points")].band == "redevelop"
    assert metrics[("csi", "dev_vs_oot", "f1__points")].value == pytest.approx(0.0)

    card = result.card
    assert card.comparisons == ("dev_vs_holdout", "dev_vs_oot")
    assert card.bands_by_comparison == {"dev_vs_holdout": "redevelop", "dev_vs_oot": "stable"}
    assert card.max_psi_by_comparison["dev_vs_holdout"] == pytest.approx(0.41588831)
    assert card.max_psi_by_comparison["dev_vs_oot"] == pytest.approx(0.0)
    assert card.worst_csi_feature == "f2__points"
    assert card.worst_csi_value == pytest.approx(0.87888983)
    assert {"numpy", "pandas", "pandera"} <= set(card.dependency_versions)
    assert card.metric_sections["stability"]["csi_features"] == ["f1__points", "f2__points"]

    assert tuple(result.psi_table.columns) == _PSI_TABLE_COLUMNS
    assert tuple(result.stability_metrics.columns) == _STABILITY_METRIC_COLUMNS
    table = result.psi_table
    score_dvh = table[(table["metric"] == "score_psi") & (table["comparison"] == "dev_vs_holdout")]
    assert score_dvh["expected_count"].tolist() == [5, 5]
    assert score_dvh["actual_count"].tolist() == [8, 2]
    assert score_dvh["expected_pct"].tolist() == pytest.approx([0.5, 0.5])
    assert score_dvh["actual_pct"].tolist() == pytest.approx([0.8, 0.2])
    assert score_dvh["total_value"].tolist() == pytest.approx([0.41588831, 0.41588831])

    assert [event.payload["regla"] for event in audit.events] == ["psi_score", "csi_feature"]
    assert [event.payload["accion"] for event in audit.events] == [
        "redesarrollar",
        "redesarrollar",
    ]
    assert_frame_equal(frame, original)
    assert_frame_equal(result.psi_table, evaluator.psi_table_)


@pytest.mark.parametrize(
    ("holdout_scores", "value", "band", "action", "n_events"),
    [
        ([1, 1, 1, 1, 1, 1, 6, 6, 6, 6], 0.04054651, "stable", "none", 0),
        ([1, 1, 1, 1, 1, 1, 1, 6, 6, 6], 0.16945957, "review", "vigilar", 1),
        ([1, 1, 1, 1, 1, 1, 1, 1, 6, 10], 0.41588831, "redevelop", "redesarrollar", 1),
    ],
)
def test_score_psi_bandas_y_audit_parametrizado(
    holdout_scores: list[float],
    value: float,
    band: str,
    action: str,
    n_events: int,
) -> None:
    audit = InMemoryAuditSink()
    evaluator = _holdout_only_evaluator()
    evaluator._audit = audit

    result = evaluator.evaluate(
        _two_partition_frame(holdout_scores),
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )

    metric = _by_key(result.metric_records)[("score_psi", "dev_vs_holdout", "score")]
    assert metric.value == pytest.approx(value)
    assert metric.band == band
    assert metric.action == action
    assert len(audit.events) == n_events
    if n_events:
        assert audit.events[0].payload["regla"] == "psi_score"
        assert audit.events[0].payload["accion"] == action


def test_smoothing_publica_proporcion_cero_suavizada() -> None:
    evaluator = _holdout_only_evaluator()

    result = evaluator.evaluate(
        _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 1, 1]),
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )

    metric = _by_key(result.metric_records)[("score_psi", "dev_vs_holdout", "score")]
    assert metric.value == pytest.approx(6.90774216)
    assert metric.band == "redevelop"
    table = result.psi_table
    second_bin = table[table["bin_label"] == "bin_01"].iloc[0]
    assert second_bin["actual_count"] == 0
    assert second_bin["expected_count"] == 5
    assert second_bin["actual_pct"] == pytest.approx(1e-6)
    assert second_bin["expected_pct"] == pytest.approx(0.5)


def test_anti_leakage_recalibrar_no_mueve_psi_del_score() -> None:
    redevelop_scores = [1, 1, 1, 1, 1, 1, 1, 1, 6, 10]
    base = _two_partition_frame(redevelop_scores, holdout_pd=[0.05] * 10)
    recalibrated = _two_partition_frame(
        redevelop_scores, holdout_pd=[0.05, 0.05, 0.05, 0.05, 0.05, 0.09, 0.09, 0.09, 0.09, 0.09]
    )
    evaluator = StabilityEvaluator(
        psi_bins=2,
        comparisons=("dev_vs_holdout",),
        include_pd_stability=True,
        temporal_axis="none",
    )

    base_result = evaluator.evaluate(
        base,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )
    recal_result = evaluator.evaluate(
        recalibrated,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )

    base_metrics = _by_key(base_result.metric_records)
    recal_metrics = _by_key(recal_result.metric_records)
    score_key = ("score_psi", "dev_vs_holdout", "score")
    pd_key = ("pd_psi", "dev_vs_holdout", "pd_calibrated")
    assert base_metrics[score_key].value == pytest.approx(0.41588831)
    assert base_metrics[score_key].value > 0.25
    assert base_metrics[score_key].value == recal_metrics[score_key].value
    assert base_metrics[pd_key].value != recal_metrics[pd_key].value


def test_csi_continuo_usa_csi_bins_si_no_hay_puntos_discretos() -> None:
    frame = _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10])
    frame["x__points"] = pd.concat(
        [
            pd.Series([float(i) for i in range(1, 11)], index=frame.index[:10]),
            pd.Series([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 6.0, 10.0], index=frame.index[10:]),
        ]
    )
    evaluator = StabilityEvaluator(
        psi_bins=2,
        csi_bins=2,
        comparisons=("dev_vs_holdout",),
        include_pd_stability=False,
        temporal_axis="none",
    )

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=("x__points",),
    )

    metric = _by_key(result.metric_records)[("csi", "dev_vs_holdout", "x__points")]
    assert metric.value == pytest.approx(0.41588831)
    table = result.psi_table
    csi_rows = table[table["metric"] == "csi"]
    assert csi_rows["bin_label"].tolist() == ["bin_00", "bin_01"]
    assert csi_rows["expected_count"].tolist() == [5, 5]
    assert csi_rows["actual_count"].tolist() == [8, 2]


def test_csi_discreto_agrega_bin_other_para_puntos_fuera_de_dev() -> None:
    # Dev fija categorías {0, 10}; holdout introduce un punto OOV (20) -> bin __other__.
    frame = pd.DataFrame(
        {
            "partition": ["desarrollo", "desarrollo", "holdout", "holdout"],
            "score": [1.0, 2.0, 1.0, 2.0],
            "pd_calibrated": [0.1, 0.2, 0.1, 0.2],
            "x__points": [0.0, 10.0, 10.0, 20.0],
        },
        index=["d0", "d1", "h0", "h1"],
    )
    evaluator = StabilityEvaluator(
        psi_bins=2,
        comparisons=("dev_vs_holdout",),
        include_pd_stability=False,
        temporal_axis="none",
    )

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=("x__points",),
    )

    table = result.psi_table
    other = table[table["bin_label"] == "__other__"].iloc[0]
    assert other["expected_count"] == 0
    assert other["actual_count"] == 1
    assert table[table["bin_label"] == "pts=0.0"].iloc[0]["expected_count"] == 1


def test_estabilidad_temporal_goldens_y_resumen() -> None:
    audit = InMemoryAuditSink()
    evaluator = StabilityEvaluator(
        psi_bins=2,
        temporal_axis="period",
        temporal_column="period",
        include_pd_stability=False,
    )
    evaluator._audit = audit

    result = evaluator.evaluate(
        _temporal_frame(),
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )

    records = result.temporal_records
    assert [record.period for record in records] == ["P1", "P2"]
    first, second = records
    assert first.n_total == 5
    assert first.mean_score == pytest.approx(3.0)
    assert (first.p25_score, first.p50_score, first.p75_score) == pytest.approx((2.0, 3.0, 4.0))
    assert first.mean_pd == pytest.approx(0.1)
    assert first.psi == pytest.approx(0.41588831)
    assert first.band == "redevelop"
    assert second.n_total == 3
    assert second.mean_score == pytest.approx(7.0)
    assert (second.p25_score, second.p50_score, second.p75_score) == pytest.approx((6.5, 7.0, 7.5))
    assert second.mean_pd == pytest.approx(0.2)
    assert second.psi == pytest.approx(6.90774216)

    summary = _by_key(result.metric_records)[("temporal_score", "period", "score")]
    assert summary.value == pytest.approx(6.90774216)
    assert summary.band == "redevelop"
    assert "score_temporal" in [event.payload["regla"] for event in audit.events]


def test_temporal_infiere_columna_unica() -> None:
    evaluator = StabilityEvaluator(
        psi_bins=2,
        temporal_axis="period",
        temporal_column=None,
        include_pd_stability=False,
    )

    result = evaluator.evaluate(
        _temporal_frame(),
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )

    assert [record.period for record in result.temporal_records] == ["P1", "P2"]


def test_temporal_datetime_bucketiza_por_frecuencia() -> None:
    frame = pd.DataFrame(
        {
            "partition": ["desarrollo"] * 8,
            "score": [float(i) for i in range(1, 9)],
            "pd_calibrated": [0.1] * 8,
            "period": pd.to_datetime(["2024-01-05"] * 4 + ["2024-02-10"] * 4, format="%Y-%m-%d"),
        },
        index=[f"t{i}" for i in range(8)],
    )
    evaluator = StabilityEvaluator(
        psi_bins=2,
        temporal_axis="period",
        temporal_column="period",
        temporal_freq="M",
        include_pd_stability=False,
    )

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )

    assert [record.period for record in result.temporal_records] == ["2024-01", "2024-02"]
    assert [record.n_total for record in result.temporal_records] == [4, 4]


def test_temporal_axis_none_omite_el_bloque() -> None:
    evaluator = StabilityEvaluator(psi_bins=2, temporal_axis="none", include_pd_stability=False)

    result = evaluator.evaluate(
        _temporal_frame(),
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )

    assert result.temporal_records == ()
    assert all(record.metric != "temporal_score" for record in result.metric_records)


def test_temporal_columna_ambigua_y_ausente_fallan() -> None:
    ambiguous = _temporal_frame()
    ambiguous["cohort"] = ambiguous["period"]
    evaluator = StabilityEvaluator(temporal_axis="period", temporal_column=None)
    with pytest.raises(StabilityDataError, match="ambigua"):
        evaluator.evaluate(
            ambiguous,
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    sin_temporal = _temporal_frame().drop(columns=["period"])
    with pytest.raises(StabilityDataError, match="no se halló"):
        evaluator.evaluate(
            sin_temporal,
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    explicit = StabilityEvaluator(temporal_axis="period", temporal_column="vintage")
    with pytest.raises(StabilityDataError, match="no está en el frame"):
        explicit.evaluate(
            _temporal_frame(),
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )


def test_oot_ausente_marca_not_evaluable_sin_bloquear_holdout() -> None:
    evaluator = StabilityEvaluator(psi_bins=2, temporal_axis="none", include_pd_stability=True)

    result = evaluator.evaluate(
        _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10]),
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )

    metrics = _by_key(result.metric_records)
    assert metrics[("score_psi", "dev_vs_holdout", "score")].band == "redevelop"
    assert metrics[("score_psi", "dev_vs_oot", "score")].band == "not_evaluable"
    assert metrics[("score_psi", "dev_vs_oot", "score")].value is None
    assert result.card.bands_by_comparison["dev_vs_oot"] == "not_evaluable"
    assert result.card.max_psi_by_comparison["dev_vs_oot"] is None


def test_desarrollo_ausente_todo_not_evaluable() -> None:
    frame = pd.DataFrame(
        {
            "partition": ["holdout", "holdout", "oot", "oot"],
            "score": [1.0, 2.0, 3.0, 4.0],
            "pd_calibrated": [0.1, 0.2, 0.3, 0.4],
            "f1__points": [0.0, 10.0, 0.0, 10.0],
            "period": ["P1", "P1", "P2", "P2"],
        },
        index=["h0", "h1", "o0", "o1"],
    )
    evaluator = StabilityEvaluator(
        psi_bins=2,
        temporal_axis="period",
        temporal_column="period",
        include_pd_stability=True,
    )

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=("f1__points",),
    )

    assert all(record.band == "not_evaluable" for record in result.metric_records)
    assert all(record.value is None for record in result.metric_records)
    assert result.psi_table.empty
    assert result.temporal_records == ()
    assert result.card.worst_csi_feature is None
    assert all(value is None for value in result.card.max_psi_by_comparison.values())


def test_from_config_clone_y_validacion_runtime() -> None:
    cfg = StabilityConfig(
        score_column="score_total",
        pd_column="pd_final",
        partition_column="particion",
        psi_bins=5,
        comparisons=("dev_vs_holdout",),
        temporal_axis="none",
        include_pd_stability=False,
    )

    evaluator = StabilityEvaluator.from_config(cfg)
    cloned = clone(evaluator)

    assert cloned.get_params()["psi_bins"] == 5
    assert cloned.get_params()["temporal_axis"] == "none"
    assert cloned.set_params(psi_bins=7).get_params()["psi_bins"] == 7
    assert StabilityEvaluator.from_config(cfg.model_dump()).pd_column == "pd_final"

    cloned.set_params(psi_stable_threshold=0.30, psi_review_threshold=0.25)
    with pytest.raises(ConfigError, match="StabilityEvaluator"):
        cloned.evaluate(
            _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10]),
            score_column="score_total",
            pd_column="pd_final",
            partition_column="particion",
            feature_point_columns=(),
        )

    duplicated = StabilityEvaluator(comparisons=("dev_vs_holdout", "dev_vs_holdout"))
    with pytest.raises(ConfigError, match="duplicados"):
        duplicated.evaluate(
            _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10]),
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )


def test_validaciones_de_contrato_con_mensajes_propios() -> None:
    evaluator = _holdout_only_evaluator()

    with pytest.raises(StabilityDataError, match=r"pandas\.DataFrame"):
        evaluator.evaluate(  # type: ignore[arg-type]
            "no es frame",
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    base = _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10])
    with pytest.raises(StabilityDataError, match="columnas requeridas"):
        evaluator.evaluate(
            base.drop(columns=["score"]),
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    duplicated = pd.concat([base, base["score"]], axis=1)
    with pytest.raises(StabilityDataError, match="duplicadas"):
        evaluator.evaluate(
            duplicated,
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    duplicate_index = _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10])
    duplicate_index.index = ["x"] * len(duplicate_index.index)
    with pytest.raises(StabilityDataError, match="índice único"):
        evaluator.evaluate(
            duplicate_index,
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    null_partition = _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10])
    null_partition.loc["d0", "partition"] = None
    with pytest.raises(StabilityDataError, match="esquema mínimo"):
        evaluator.evaluate(
            null_partition,
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    non_finite = _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10])
    non_finite.loc["d0", "score"] = math.inf
    with pytest.raises(StabilityDataError, match="finitos"):
        evaluator.evaluate(
            non_finite,
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    invalid_pd = _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10])
    invalid_pd.loc["d0", "pd_calibrated"] = 1.0
    with pytest.raises(StabilityDataError, match=r"\(0, 1\)"):
        evaluator.evaluate(
            invalid_pd,
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    non_numeric = _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10]).astype({"score": "object"})
    non_numeric.loc["d0", "score"] = "alto"
    with pytest.raises(StabilityDataError, match="float64-compatible"):
        evaluator.evaluate(
            non_numeric,
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=(),
        )

    bad_points = _two_partition_frame([1, 1, 1, 1, 1, 1, 1, 1, 6, 10])
    bad_points["x__points"] = 1.0
    bad_points.loc["d0", "x__points"] = math.inf
    with pytest.raises(StabilityDataError, match="finitos"):
        evaluator.evaluate(
            bad_points,
            score_column="score",
            pd_column="pd_calibrated",
            partition_column="partition",
            feature_point_columns=("x__points",),
        )


def test_reproducibilidad_shuffle_determinista() -> None:
    frame = _full_frame()
    evaluator = StabilityEvaluator(psi_bins=2, temporal_axis="none", include_pd_stability=True)

    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=("f1__points", "f2__points"),
    )
    shuffled = frame.sample(frac=1.0, random_state=11)
    shuffled_result = evaluator.evaluate(
        shuffled,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=("f1__points", "f2__points"),
    )

    assert_frame_equal(result.psi_table, shuffled_result.psi_table)
    assert_frame_equal(result.stability_metrics, shuffled_result.stability_metrics)


def test_helpers_defensivos(monkeypatch: pytest.MonkeyPatch) -> None:
    assert evaluator_module._band(0.05, 0.10, 0.25) == "stable"
    assert evaluator_module._band(0.15, 0.10, 0.25) == "review"
    assert evaluator_module._band(0.30, 0.10, 0.25) == "redevelop"
    assert evaluator_module._discrete_label(0.0) == "pts=0.0"
    assert evaluator_module._normalize_float(-0.0) == 0.0

    with pytest.raises(StabilityMetricError, match="estadístico"):
        evaluator_module._finite_scalar(math.inf, context="mean_score")

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

    cfg = StabilityConfig(temporal_axis="none")
    with pytest.raises(RuntimeError, match="boom schema"):
        evaluator_module._validate_schema(
            _two_partition_frame([1.0]),
            cfg=cfg,
            feature_point_columns=(),
            temporal_name=None,
            pa=FakePa,
        )

    real_import = evaluator_module.importlib.import_module

    def block_numpy(name: str) -> Any:
        if name == "numpy":
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return real_import(name)

    monkeypatch.setattr(evaluator_module.importlib, "import_module", block_numpy)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        evaluator_module._dependency_versions()
    monkeypatch.setattr(evaluator_module.importlib, "import_module", real_import)

    def raise_missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", raise_missing)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        evaluator_module._dependency_versions()


def test_import_stability_evaluator_liviano_subprocess() -> None:
    code = textwrap.dedent(
        """
        import sys
        from nikodym.stability.evaluator import StabilityEvaluator

        assert StabilityEvaluator.__name__ == "StabilityEvaluator"
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
        if name in {"pandas", "numpy"}:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name)

    monkeypatch.setattr(evaluator_module.importlib, "import_module", block)
    for helper in (evaluator_module._import_pandas, evaluator_module._import_numpy):
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


def _holdout_only_evaluator() -> StabilityEvaluator:
    return StabilityEvaluator(
        psi_bins=2,
        comparisons=("dev_vs_holdout",),
        include_pd_stability=False,
        temporal_axis="none",
    )


def _two_partition_frame(
    holdout_scores: list[float],
    *,
    holdout_pd: list[float] | None = None,
) -> pd.DataFrame:
    holdout_n = len(holdout_scores)
    holdout_probs = holdout_pd if holdout_pd is not None else [0.05] * holdout_n
    dev = pd.DataFrame(
        {
            "partition": ["desarrollo"] * 10,
            "score": [float(value) for value in range(1, 11)],
            "pd_calibrated": [round(0.01 * value, 2) for value in range(1, 11)],
        },
        index=[f"d{index}" for index in range(10)],
    )
    holdout = pd.DataFrame(
        {
            "partition": ["holdout"] * holdout_n,
            "score": [float(value) for value in holdout_scores],
            "pd_calibrated": [float(value) for value in holdout_probs],
        },
        index=[f"h{index}" for index in range(holdout_n)],
    )
    return pd.concat([dev, holdout])


def _full_frame() -> pd.DataFrame:
    partitions = {
        "desarrollo": {
            "score": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "pd_calibrated": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10],
            "f1__points": [0, 0, 0, 0, 10, 10, 10, 20, 20, 20],
            "f2__points": [0, 0, 0, 0, 0, 10, 10, 10, 10, 10],
        },
        "holdout": {
            "score": [1, 1, 1, 1, 1, 1, 1, 1, 6, 10],
            "pd_calibrated": [0.01, 0.02, 0.03, 0.04, 0.05, 0.05, 0.06, 0.07, 0.08, 0.09],
            "f1__points": [0, 0, 0, 10, 10, 10, 20, 20, 20, 20],
            "f2__points": [0, 0, 0, 0, 0, 0, 0, 0, 0, 10],
        },
        "oot": {
            "score": [1, 1, 1, 1, 1, 6, 6, 6, 6, 6],
            "pd_calibrated": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10],
            "f1__points": [0, 0, 0, 0, 10, 10, 10, 20, 20, 20],
            "f2__points": [0, 0, 0, 0, 0, 10, 10, 10, 10, 10],
        },
    }
    blocks = []
    for partition, columns in partitions.items():
        block = pd.DataFrame(columns)
        block.insert(0, "partition", partition)
        blocks.append(block)
    frame = pd.concat(blocks, ignore_index=True)
    frame.index = [f"r{index:02d}" for index in range(len(frame.index))]
    return frame


def _temporal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["desarrollo"] * 8,
            "score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            "pd_calibrated": [0.1, 0.1, 0.1, 0.1, 0.1, 0.2, 0.2, 0.2],
            "period": ["P1", "P1", "P1", "P1", "P1", "P2", "P2", "P2"],
        },
        index=[f"t{index}" for index in range(8)],
    )
