"""Tests de resultados de ``performance``: DTOs puros, copias y lazy exports."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.performance as performance_pkg
import nikodym.performance.results as performance_results
from nikodym.performance.config import (
    EvaluationSource as ConfigEvaluationSource,
)
from nikodym.performance.config import (
    PerformancePartition as ConfigPerformancePartition,
)
from nikodym.performance.config import (
    ScoreDirection as ConfigScoreDirection,
)
from nikodym.performance.results import (
    DecilePerformanceRecord,
    DiscriminantMetricRecord,
    PerformanceCardSection,
    PerformanceResult,
)


def test_discriminant_metric_record_golden_estados_y_normalizacion() -> None:
    record = _discriminant_record(
        source="score",
        status="threshold_flag",
        auc=-0.0,
        gini=-0.0,
        ks=-0.0,
        ks_cutoff_risk_score=-0.0,
        ks_cutoff_score=-0.0,
        tpr_at_ks=-0.0,
        fpr_at_ks=-0.0,
    )

    assert record.model_dump(mode="json") == {
        "partition": "desarrollo",
        "n_total": 100,
        "n_bad": 20,
        "n_good": 80,
        "auc": 0.0,
        "gini": 0.0,
        "ks": 0.0,
        "ks_cutoff_risk_score": 0.0,
        "ks_cutoff_score": 0.0,
        "tpr_at_ks": 0.0,
        "fpr_at_ks": 0.0,
        "source": "score",
        "status": "threshold_flag",
    }
    assert math.copysign(1.0, record.ks_cutoff_score) == 1.0

    not_evaluable = _discriminant_record(
        partition="holdout",
        n_total=18,
        n_bad=0,
        n_good=18,
        auc=math.nan,
        gini=math.inf,
        ks=-math.inf,
        ks_cutoff_risk_score=None,
        ks_cutoff_score=True,
        tpr_at_ks="no numerico",
        fpr_at_ks=None,
        status="not_evaluable",
    )
    assert not_evaluable.model_dump(mode="json") == {
        "partition": "holdout",
        "n_total": 18,
        "n_bad": 0,
        "n_good": 18,
        "auc": None,
        "gini": None,
        "ks": None,
        "ks_cutoff_risk_score": None,
        "ks_cutoff_score": None,
        "tpr_at_ks": None,
        "fpr_at_ks": None,
        "source": "pd_calibrated",
        "status": "not_evaluable",
    }

    with pytest.raises(ValidationError, match="frozen"):
        record.auc = 0.7
    with pytest.raises(ValidationError):
        _discriminant_record(extra="no permitido")
    with pytest.raises(ValidationError, match="n_total"):
        _discriminant_record(n_total=3, n_bad=1, n_good=1)
    with pytest.raises(ValidationError, match="not_evaluable"):
        _discriminant_record(status="not_evaluable")
    with pytest.raises(ValidationError, match="particiones evaluables"):
        _discriminant_record(auc=math.nan)
    with pytest.raises(ValidationError, match="ks_cutoff_score"):
        _discriminant_record(source="score", ks_cutoff_score=None)


def test_decile_performance_record_golden_invariantes_y_float_finito() -> None:
    record = _decile_record(
        bad_rate=-0.0,
        good_rate=-0.0,
        mean_pd=-0.0,
        min_pd=-0.0,
        max_pd=-0.0,
        mean_score=-0.0,
        min_score=-0.0,
        max_score=-0.0,
        cum_bad_capture_rate=-0.0,
        cum_good_capture_rate=-0.0,
        lift=-0.0,
        ks_at_decile=-0.0,
    )

    assert record.model_dump(mode="json") == {
        "partition": "desarrollo",
        "decile": 1,
        "n_total": 10,
        "n_bad": 4,
        "n_good": 6,
        "bad_rate": 0.0,
        "good_rate": 0.0,
        "mean_pd": 0.0,
        "min_pd": 0.0,
        "max_pd": 0.0,
        "mean_score": 0.0,
        "min_score": 0.0,
        "max_score": 0.0,
        "cum_total": 10,
        "cum_bad": 4,
        "cum_good": 6,
        "cum_bad_capture_rate": 0.0,
        "cum_good_capture_rate": 0.0,
        "lift": 0.0,
        "ks_at_decile": 0.0,
    }
    assert isinstance(record.decile, int)
    assert math.copysign(1.0, record.bad_rate) == 1.0

    with pytest.raises(ValidationError, match="frozen"):
        record.lift = 3.0
    with pytest.raises(ValidationError):
        _decile_record(extra="no permitido")
    with pytest.raises(ValidationError, match="n_total"):
        _decile_record(n_total=9)
    with pytest.raises(ValidationError, match="cum_total"):
        _decile_record(cum_total=9)
    with pytest.raises(ValidationError, match="min_pd"):
        _decile_record(min_pd=0.30, mean_pd=0.20, max_pd=0.40)
    with pytest.raises(ValidationError, match="min_score"):
        _decile_record(min_score=450.0, mean_score=430.0, max_score=500.0)
    with pytest.raises(ValidationError, match="números finitos"):
        _decile_record(bad_rate=math.inf)


def test_performance_card_section_golden_copias_metric_sections_y_no_finitos() -> None:
    metric_sections: dict[str, Any] = {
        "diagnostico": {
            "delta": -0.0,
            "serie": [math.inf, math.nan, -0.0],
            "tupla": (-0.0,),
            "nested": {"valor": -0.0},
            "nota": "ok",
        }
    }
    thresholds = {"ks_min": -0.0, "auc_min": 0.60}
    max_metrics = {
        "holdout": {"ks": -0.0, "gini": math.inf, "auc": True},
        "desarrollo": {"ks": 0.40, "gini": 0.50, "auc": 0.75},
    }
    bands = {"holdout": "not_evaluable", "desarrollo": "ok"}
    versions = {"sklearn": "1.7.2", "pandas": "2.3.3", "numpy": "2.4.6"}
    card = _card(
        thresholds=thresholds,
        max_metrics_by_partition=max_metrics,
        bands_by_partition=bands,
        dependency_versions=versions,
        metric_sections=metric_sections,
    )

    assert card.model_dump(mode="json") == {
        "evaluation_source": "pd_calibrated",
        "score_direction": "higher_is_lower_risk",
        "partitions": ["desarrollo", "holdout"],
        "thresholds": {"auc_min": 0.60, "ks_min": 0.0},
        "max_metrics_by_partition": {
            "desarrollo": {"auc": 0.75, "gini": 0.50, "ks": 0.40},
            "holdout": {"auc": None, "gini": None, "ks": 0.0},
        },
        "bands_by_partition": {"desarrollo": "ok", "holdout": "not_evaluable"},
        "n_deciles": 10,
        "dependency_versions": {"numpy": "2.4.6", "pandas": "2.3.3", "sklearn": "1.7.2"},
        "metric_sections": {
            "diagnostico": {
                "delta": 0.0,
                "serie": [None, None, 0.0],
                "tupla": [0.0],
                "nested": {"valor": 0.0},
                "nota": "ok",
            }
        },
    }
    assert math.copysign(1.0, card.thresholds["ks_min"]) == 1.0
    assert math.copysign(1.0, card.metric_sections["diagnostico"]["delta"]) == 1.0

    thresholds["auc_min"] = 99.0
    max_metrics["desarrollo"]["auc"] = 99.0
    bands["desarrollo"] = "mutado"
    versions["pandas"] = "mutado"
    metric_sections["diagnostico"]["delta"] = 99.0
    card.thresholds["auc_min"] = 88.0
    card.max_metrics_by_partition["desarrollo"]["auc"] = 88.0
    card.bands_by_partition["desarrollo"] = "mutado"
    card.dependency_versions["pandas"] = "mutado"
    card.metric_sections["diagnostico"]["delta"] = 88.0

    assert card.thresholds == {"auc_min": 0.60, "ks_min": 0.0}
    assert card.max_metrics_by_partition["desarrollo"]["auc"] == 0.75
    assert card.bands_by_partition == {"desarrollo": "ok", "holdout": "not_evaluable"}
    assert card.dependency_versions == {
        "numpy": "2.4.6",
        "pandas": "2.3.3",
        "sklearn": "1.7.2",
    }
    assert card.metric_sections["diagnostico"]["delta"] == 0.0

    with pytest.raises(ValidationError, match="frozen"):
        card.n_deciles = 20
    with pytest.raises(ValidationError):
        _card(extra="no permitido")


def test_performance_card_section_valida_shape_y_defaults() -> None:
    assert _card(thresholds=None, metric_sections=None).metric_sections == {}
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])
    with pytest.raises(ValidationError, match="partitions"):
        _card(partitions=())
    with pytest.raises(ValidationError, match="duplicados"):
        _card(
            partitions=("desarrollo", "desarrollo"),
            max_metrics_by_partition={"desarrollo": {"auc": 0.7, "gini": 0.4, "ks": 0.2}},
            bands_by_partition={"desarrollo": "ok"},
        )
    with pytest.raises(ValidationError, match="bands_by_partition"):
        _card(bands_by_partition={"desarrollo": "ok"})
    with pytest.raises(ValidationError, match="max_metrics_by_partition"):
        _card(max_metrics_by_partition={"desarrollo": {"auc": 0.75, "gini": 0.50, "ks": 0.40}})
    with pytest.raises(ValidationError, match="auc, gini y ks"):
        _card(
            max_metrics_by_partition={
                "desarrollo": {"auc": 0.75, "gini": 0.50},
                "holdout": {"auc": None, "gini": None, "ks": None},
            }
        )
    with pytest.raises(ValidationError, match="thresholds"):
        _card(thresholds={"auc_min": math.nan})
    with pytest.raises(ValidationError):
        _card(thresholds=["no permitido"])
    with pytest.raises(ValidationError):
        _card(max_metrics_by_partition=["no permitido"])
    with pytest.raises(ValidationError):
        _card(
            max_metrics_by_partition={
                "desarrollo": 0.75,
                "holdout": {"auc": None, "gini": None, "ks": None},
            }
        )


def test_performance_result_envuelve_dataframes_records_y_card_con_copias() -> None:
    performance_table = _performance_table()
    discriminant_metrics = _discriminant_metrics_frame()
    result = _result(performance_table=performance_table, discriminant_metrics=discriminant_metrics)

    performance_table.loc[0, "bad_rate"] = 0.99
    discriminant_metrics.loc[0, "auc"] = 0.99
    observed_table = result.performance_table
    observed_metrics = result.discriminant_metrics

    assert result.performance_table is not result.performance_table
    assert result.discriminant_metrics is not result.discriminant_metrics
    assert_frame_equal(observed_table, _normalized_performance_table())
    assert_frame_equal(observed_metrics, _normalized_discriminant_metrics_frame())
    assert tuple(observed_table.columns) == (
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
    assert tuple(observed_metrics.columns) == (
        "partition",
        "n_total",
        "n_bad",
        "n_good",
        "auc",
        "gini",
        "ks",
        "ks_cutoff_risk_score",
        "ks_cutoff_score",
        "tpr_at_ks",
        "fpr_at_ks",
        "source",
        "status",
    )

    observed_table.loc[0, "bad_rate"] = 0.77
    observed_metrics.loc[0, "auc"] = 0.77
    assert_frame_equal(result.performance_table, _normalized_performance_table())
    assert_frame_equal(result.discriminant_metrics, _normalized_discriminant_metrics_frame())

    round_tripped = PerformanceResult.model_validate(
        {
            "performance_table": result.performance_table,
            "discriminant_metrics": result.discriminant_metrics,
            "performance_records": [record.model_dump() for record in result.performance_records],
            "discriminant_records": [record.model_dump() for record in result.discriminant_records],
            "card": result.card.model_dump(),
        }
    )
    assert_frame_equal(round_tripped.performance_table, result.performance_table)
    assert_frame_equal(round_tripped.discriminant_metrics, result.discriminant_metrics)
    assert round_tripped.performance_records == result.performance_records
    assert round_tripped.discriminant_records == result.discriminant_records
    assert round_tripped.card == result.card

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card()
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_performance_result_valida_dataframes_y_consistencia_card() -> None:
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(performance_table="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(performance_table=_performance_table().drop(columns=["lift"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(discriminant_metrics=_discriminant_metrics_frame().drop(columns=["status"]))
    with pytest.raises(ValidationError, match=r"card\.partitions"):
        _result(
            card=_card(
                partitions=("holdout", "desarrollo"),
                max_metrics_by_partition={
                    "holdout": {"auc": None, "gini": None, "ks": None},
                    "desarrollo": {"auc": 0.75, "gini": 0.50, "ks": 0.40},
                },
            )
        )
    with pytest.raises(ValidationError, match="evaluation_source"):
        _result(card=_card(evaluation_source="score"))
    with pytest.raises(ValidationError, match="max_metrics_by_partition"):
        _result(
            card=_card(
                max_metrics_by_partition={
                    "desarrollo": {"auc": 0.76, "gini": 0.50, "ks": 0.40},
                    "holdout": {"auc": None, "gini": None, "ks": None},
                }
            )
        )
    with pytest.raises(ValidationError, match="particiones no resumidas"):
        _result(performance_records=(_decile_record(partition="oot"),))
    with pytest.raises(ValidationError, match=r"card\.n_deciles"):
        _result(performance_records=(_decile_record(decile=11),))


def test_performance_results_lazy_exports_y_nucleo_liviano_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.core;"
        "import nikodym.performance as performance;"
        "blocked=[m for m in ('pandas','scipy','sklearn','statsmodels','optbinning') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "loaded=[getattr(performance, name) for name in "
        "('DiscriminantMetricRecord','DecilePerformanceRecord',"
        "'PerformanceCardSection','PerformanceResult')];"
        "assert loaded[-1].__name__ == 'PerformanceResult';"
        "blocked=[m for m in ('pandas','scipy','sklearn','statsmodels','optbinning') "
        "if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert performance_pkg.PerformanceResult is PerformanceResult
    with pytest.raises(AttributeError, match="NoExiste"):
        _ = performance_pkg.NoExiste


def test_results_module_expone_aliases_publicos_de_config() -> None:
    assert performance_results.EvaluationSource == ConfigEvaluationSource
    assert performance_results.PerformancePartition == ConfigPerformancePartition
    assert performance_results.ScoreDirection == ConfigScoreDirection
    assert "DiscriminantMetricRecord" in performance_results.__all__
    assert "DecilePerformanceRecord" in performance_results.__all__
    assert "PerformanceCardSection" in performance_results.__all__
    assert "PerformanceResult" in performance_results.__all__


def _discriminant_record(**updates: Any) -> DiscriminantMetricRecord:
    payload: dict[str, Any] = {
        "partition": "desarrollo",
        "n_total": 100,
        "n_bad": 20,
        "n_good": 80,
        "auc": 0.75,
        "gini": 0.50,
        "ks": 0.40,
        "ks_cutoff_risk_score": 0.125,
        "ks_cutoff_score": None,
        "tpr_at_ks": 0.70,
        "fpr_at_ks": 0.30,
        "source": "pd_calibrated",
        "status": "ok",
    }
    payload.update(updates)
    return DiscriminantMetricRecord(**payload)


def _decile_record(**updates: Any) -> DecilePerformanceRecord:
    payload: dict[str, Any] = {
        "partition": "desarrollo",
        "decile": 1,
        "n_total": 10,
        "n_bad": 4,
        "n_good": 6,
        "bad_rate": 0.40,
        "good_rate": 0.60,
        "mean_pd": 0.18,
        "min_pd": 0.12,
        "max_pd": 0.24,
        "mean_score": 410.0,
        "min_score": 390.0,
        "max_score": 430.0,
        "cum_total": 10,
        "cum_bad": 4,
        "cum_good": 6,
        "cum_bad_capture_rate": 0.40,
        "cum_good_capture_rate": 0.075,
        "lift": 2.0,
        "ks_at_decile": 0.325,
    }
    payload.update(updates)
    return DecilePerformanceRecord(**payload)


def _card(**updates: Any) -> PerformanceCardSection:
    payload: dict[str, Any] = {
        "evaluation_source": "pd_calibrated",
        "score_direction": "higher_is_lower_risk",
        "partitions": ("desarrollo", "holdout"),
        "thresholds": {"auc_min": 0.60, "ks_min": 0.20},
        "max_metrics_by_partition": {
            "desarrollo": {"auc": 0.75, "gini": 0.50, "ks": 0.40},
            "holdout": {"auc": None, "gini": None, "ks": None},
        },
        "bands_by_partition": {"desarrollo": "ok", "holdout": "not_evaluable"},
        "n_deciles": 10,
        "dependency_versions": {"pandas": "2.3.3", "numpy": "2.4.6", "sklearn": "1.7.2"},
    }
    payload.update(updates)
    return PerformanceCardSection(**payload)


def _result(
    *,
    performance_table: Any | None = None,
    discriminant_metrics: Any | None = None,
    performance_records: tuple[DecilePerformanceRecord, ...] | None = None,
    discriminant_records: tuple[DiscriminantMetricRecord, ...] | None = None,
    card: PerformanceCardSection | None = None,
    extra: object | None = None,
) -> PerformanceResult:
    payload: dict[str, Any] = {
        "performance_table": _performance_table()
        if performance_table is None
        else performance_table,
        "discriminant_metrics": _discriminant_metrics_frame()
        if discriminant_metrics is None
        else discriminant_metrics,
        "performance_records": _performance_records()
        if performance_records is None
        else performance_records,
        "discriminant_records": _discriminant_records()
        if discriminant_records is None
        else discriminant_records,
        "card": _card() if card is None else card,
    }
    if extra is not None:
        payload["extra"] = extra
    return PerformanceResult(**payload)


def _performance_records() -> tuple[DecilePerformanceRecord, ...]:
    return (
        _decile_record(),
        _decile_record(
            partition="holdout",
            n_total=4,
            n_bad=0,
            n_good=4,
            bad_rate=0.0,
            good_rate=1.0,
            mean_pd=0.04,
            min_pd=0.02,
            max_pd=0.06,
            mean_score=680.0,
            min_score=650.0,
            max_score=710.0,
            cum_total=4,
            cum_bad=0,
            cum_good=4,
            cum_bad_capture_rate=0.0,
            cum_good_capture_rate=1.0,
            lift=0.0,
            ks_at_decile=0.0,
        ),
    )


def _discriminant_records() -> tuple[DiscriminantMetricRecord, ...]:
    return (
        _discriminant_record(),
        _discriminant_record(
            partition="holdout",
            n_total=4,
            n_bad=0,
            n_good=4,
            auc=None,
            gini=None,
            ks=None,
            ks_cutoff_risk_score=None,
            ks_cutoff_score=None,
            tpr_at_ks=None,
            fpr_at_ks=None,
            status="not_evaluable",
        ),
    )


def _performance_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "holdout"],
            "decile": [1, 1],
            "n_total": [10, 4],
            "n_bad": [4, 0],
            "n_good": [6, 4],
            "bad_rate": [-0.0, 0.0],
            "good_rate": [0.60, 1.0],
            "mean_pd": [0.18, 0.04],
            "min_pd": [0.12, 0.02],
            "max_pd": [0.24, 0.06],
            "mean_score": [410.0, 680.0],
            "min_score": [390.0, 650.0],
            "max_score": [430.0, 710.0],
            "cum_total": [10, 4],
            "cum_bad": [4, 0],
            "cum_good": [6, 4],
            "cum_bad_capture_rate": [0.40, -0.0],
            "cum_good_capture_rate": [0.075, 1.0],
            "lift": [2.0, -0.0],
            "ks_at_decile": [0.325, -0.0],
        },
        index=pd.Index(["dev_d1", "ho_d1"], name="bucket_id"),
    )


def _discriminant_metrics_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "holdout"],
            "n_total": [100, 4],
            "n_bad": [20, 0],
            "n_good": [80, 4],
            "auc": [0.75, None],
            "gini": [0.50, None],
            "ks": [0.40, None],
            "ks_cutoff_risk_score": [0.125, None],
            "ks_cutoff_score": [None, None],
            "tpr_at_ks": [0.70, None],
            "fpr_at_ks": [0.30, None],
            "source": ["pd_calibrated", "pd_calibrated"],
            "status": ["ok", "not_evaluable"],
        },
        index=pd.Index(["dev", "ho"], name="partition_id"),
    )


def _normalized_performance_table() -> pd.DataFrame:
    return _normalize_frame(_performance_table())


def _normalized_discriminant_metrics_frame() -> pd.DataFrame:
    return _normalize_frame(_discriminant_metrics_frame())


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    for column in normalized.select_dtypes(include=["float"]).columns:
        normalized[column] = normalized[column].mask(normalized[column] == 0.0, 0.0)
    return normalized
