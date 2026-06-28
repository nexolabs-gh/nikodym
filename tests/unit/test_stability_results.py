"""Tests de resultados de ``stability``: DTOs puros, copias y lazy exports."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.stability as stability_pkg
import nikodym.stability.results as stability_results
from nikodym.stability.config import (
    CsiSource as ConfigCsiSource,
)
from nikodym.stability.config import (
    ScoreDirection as ConfigScoreDirection,
)
from nikodym.stability.config import (
    StabilityComparison as ConfigStabilityComparison,
)
from nikodym.stability.results import (
    CsiRecord,
    PsiRecord,
    StabilityCardSection,
    StabilityMetricRecord,
    StabilityResult,
    TemporalStabilityRecord,
    _max_psi_by_comparison,
    _worst_csi,
)


def test_stability_metric_record_golden_estados_y_normalizacion() -> None:
    record = _metric_record(
        value=-0.0,
        stable_threshold=-0.0,
        review_threshold=0.25,
        band="stable",
        action="none",
    )

    assert record.model_dump(mode="json") == {
        "metric": "score_psi",
        "comparison": "dev_vs_holdout",
        "feature": "score",
        "value": 0.0,
        "stable_threshold": 0.0,
        "review_threshold": 0.25,
        "band": "stable",
        "action": "none",
    }
    assert math.copysign(1.0, record.value) == 1.0

    not_evaluable = _metric_record(
        metric="pd_psi",
        comparison="dev_vs_oot",
        feature="pd_calibrated",
        value=math.nan,
        band="not_evaluable",
        action="none",
    )
    assert not_evaluable.model_dump(mode="json") == {
        "metric": "pd_psi",
        "comparison": "dev_vs_oot",
        "feature": "pd_calibrated",
        "value": None,
        "stable_threshold": 0.10,
        "review_threshold": 0.25,
        "band": "not_evaluable",
        "action": "none",
    }

    with pytest.raises(ValidationError, match="frozen"):
        record.value = 0.7
    with pytest.raises(ValidationError):
        _metric_record(extra="no permitido")
    with pytest.raises(ValidationError, match="review_threshold"):
        _metric_record(stable_threshold=0.30, review_threshold=0.25)
    with pytest.raises(ValidationError, match="números finitos"):
        _metric_record(stable_threshold=math.inf)
    with pytest.raises(ValidationError, match="acción de la banda"):
        _metric_record(band="review", action="none")
    with pytest.raises(ValidationError, match="not_evaluable no debe publicar"):
        _metric_record(band="not_evaluable", action="none", value=0.30)
    with pytest.raises(ValidationError, match="evaluables deben publicar"):
        _metric_record(value=math.nan)


def test_psi_record_golden_invariantes_y_float_finito() -> None:
    record = _psi_record(
        expected_pct=-0.0,
        actual_pct=0.0,
        component_value=-0.0,
        total_value=-0.0,
    )

    assert record.model_dump(mode="json") == {
        "metric": "score_psi",
        "comparison": "dev_vs_holdout",
        "feature": "score",
        "bin_label": "(-inf, 380]",
        "expected_count": 120,
        "actual_count": 95,
        "expected_pct": 0.0,
        "actual_pct": 0.0,
        "component_value": 0.0,
        "total_value": 0.0,
        "band": "stable",
    }
    assert isinstance(record.expected_count, int)
    assert math.copysign(1.0, record.component_value) == 1.0

    with pytest.raises(ValidationError, match="frozen"):
        record.total_value = 3.0
    with pytest.raises(ValidationError):
        _psi_record(extra="no permitido")
    with pytest.raises(ValidationError):
        _psi_record(metric="csi")
    with pytest.raises(ValidationError):
        _psi_record(expected_count=-1)
    with pytest.raises(ValidationError, match="números finitos"):
        _psi_record(component_value=math.inf)
    with pytest.raises(ValidationError, match="expected_pct"):
        _psi_record(expected_pct=1.5)
    with pytest.raises(ValidationError, match="actual_pct"):
        _psi_record(actual_pct=1.5)


def test_csi_record_golden_invariantes_y_metric_literal() -> None:
    record = _csi_record(
        expected_pct=-0.0,
        actual_pct=0.0,
        component_value=-0.0,
        total_value=-0.0,
    )

    assert record.model_dump(mode="json") == {
        "metric": "csi",
        "comparison": "dev_vs_oot",
        "feature": "ingreso_mensual",
        "bin_label": "bin_3",
        "expected_count": 40,
        "actual_count": 52,
        "expected_pct": 0.0,
        "actual_pct": 0.0,
        "component_value": 0.0,
        "total_value": 0.0,
        "band": "review",
    }
    assert math.copysign(1.0, record.total_value) == 1.0

    with pytest.raises(ValidationError, match="frozen"):
        record.band = "stable"
    with pytest.raises(ValidationError):
        _csi_record(extra="no permitido")
    with pytest.raises(ValidationError):
        _csi_record(metric="score_psi")
    with pytest.raises(ValidationError):
        _csi_record(actual_count=-1)
    with pytest.raises(ValidationError, match="números finitos"):
        _csi_record(total_value=math.nan)
    with pytest.raises(ValidationError, match="actual_pct"):
        _csi_record(actual_pct=1.2)


def test_temporal_stability_record_golden_estados_y_orden() -> None:
    record = _temporal_record(
        mean_score=-0.0,
        p25_score=-0.0,
        p50_score=-0.0,
        p75_score=-0.0,
        mean_pd=-0.0,
        psi=-0.0,
    )

    assert record.model_dump(mode="json") == {
        "period": "2024-01",
        "n_total": 1500,
        "mean_score": 0.0,
        "p25_score": 0.0,
        "p50_score": 0.0,
        "p75_score": 0.0,
        "mean_pd": 0.0,
        "psi": 0.0,
        "band": "stable",
    }
    assert math.copysign(1.0, record.psi) == 1.0

    sin_pd = _temporal_record(mean_pd=None)
    assert sin_pd.mean_pd is None

    not_evaluable = _temporal_record(
        period="2024-12",
        n_total=5,
        mean_score=math.nan,
        p25_score=math.inf,
        p50_score=None,
        p75_score=None,
        mean_pd=None,
        psi=None,
        band="not_evaluable",
    )
    assert not_evaluable.model_dump(mode="json") == {
        "period": "2024-12",
        "n_total": 5,
        "mean_score": None,
        "p25_score": None,
        "p50_score": None,
        "p75_score": None,
        "mean_pd": None,
        "psi": None,
        "band": "not_evaluable",
    }

    with pytest.raises(ValidationError, match="frozen"):
        record.psi = 0.5
    with pytest.raises(ValidationError):
        _temporal_record(extra="no permitido")
    with pytest.raises(ValidationError):
        _temporal_record(n_total=-1)
    with pytest.raises(ValidationError, match="not_evaluable no debe publicar"):
        _temporal_record(band="not_evaluable")
    with pytest.raises(ValidationError, match="evaluables deben publicar"):
        _temporal_record(psi=math.nan)
    with pytest.raises(ValidationError, match="p25_score"):
        _temporal_record(p25_score=560.0, p50_score=510.0, p75_score=555.0)


def test_stability_card_section_golden_copias_metric_sections_y_no_finitos() -> None:
    metric_sections: dict[str, Any] = {
        "diagnostico": {
            "delta": -0.0,
            "serie": [math.inf, math.nan, -0.0],
            "tupla": (-0.0,),
            "nested": {"valor": -0.0},
            "nota": "ok",
        }
    }
    max_psi = {"dev_vs_oot": math.inf, "dev_vs_holdout": -0.0}
    bands = {"dev_vs_oot": "review", "dev_vs_holdout": "stable"}
    versions = {"sklearn": "1.7.2", "pandas": "2.3.3", "numpy": "2.4.6"}
    card = _card(
        max_psi_by_comparison=max_psi,
        bands_by_comparison=bands,
        dependency_versions=versions,
        metric_sections=metric_sections,
        worst_csi_value=-0.0,
    )

    assert card.model_dump(mode="json") == {
        "score_direction": "higher_is_lower_risk",
        "csi_source": "score_points",
        "comparisons": ["dev_vs_holdout", "dev_vs_oot"],
        "psi_bins": 10,
        "stable_threshold": 0.10,
        "review_threshold": 0.25,
        "max_psi_by_comparison": {"dev_vs_holdout": 0.0, "dev_vs_oot": None},
        "bands_by_comparison": {"dev_vs_holdout": "stable", "dev_vs_oot": "review"},
        "worst_csi_feature": "ingreso_mensual",
        "worst_csi_value": 0.0,
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
    assert math.copysign(1.0, card.max_psi_by_comparison["dev_vs_holdout"]) == 1.0
    assert math.copysign(1.0, card.metric_sections["diagnostico"]["delta"]) == 1.0

    max_psi["dev_vs_holdout"] = 99.0
    bands["dev_vs_holdout"] = "mutado"
    versions["pandas"] = "mutado"
    metric_sections["diagnostico"]["delta"] = 99.0
    card.max_psi_by_comparison["dev_vs_holdout"] = 88.0
    card.bands_by_comparison["dev_vs_holdout"] = "mutado"
    card.dependency_versions["pandas"] = "mutado"
    card.metric_sections["diagnostico"]["delta"] = 88.0

    assert card.max_psi_by_comparison == {"dev_vs_holdout": 0.0, "dev_vs_oot": None}
    assert card.bands_by_comparison == {"dev_vs_holdout": "stable", "dev_vs_oot": "review"}
    assert card.dependency_versions == {
        "numpy": "2.4.6",
        "pandas": "2.3.3",
        "sklearn": "1.7.2",
    }
    assert card.metric_sections["diagnostico"]["delta"] == 0.0

    with pytest.raises(ValidationError, match="frozen"):
        card.psi_bins = 20
    with pytest.raises(ValidationError):
        _card(extra="no permitido")


def test_stability_card_section_valida_shape_y_defaults() -> None:
    assert _card(metric_sections=None).metric_sections == {}
    assert _card(worst_csi_feature=None, worst_csi_value=None).worst_csi_feature is None
    assert _card(
        max_psi_by_comparison={"dev_vs_holdout": True, "dev_vs_oot": 0.19}
    ).max_psi_by_comparison == {
        "dev_vs_holdout": None,
        "dev_vs_oot": 0.19,
    }

    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])
    with pytest.raises(ValidationError, match="comparisons"):
        _card(comparisons=())
    with pytest.raises(ValidationError, match="duplicados"):
        _card(
            comparisons=("dev_vs_holdout", "dev_vs_holdout"),
            max_psi_by_comparison={"dev_vs_holdout": 0.08},
            bands_by_comparison={"dev_vs_holdout": "stable"},
        )
    with pytest.raises(ValidationError, match="bands_by_comparison"):
        _card(bands_by_comparison={"dev_vs_holdout": "stable"})
    with pytest.raises(ValidationError, match="max_psi_by_comparison"):
        _card(max_psi_by_comparison={"dev_vs_holdout": 0.08})
    with pytest.raises(ValidationError, match="review_threshold"):
        _card(stable_threshold=0.30)
    with pytest.raises(ValidationError, match="números finitos"):
        _card(stable_threshold=math.nan)
    with pytest.raises(ValidationError, match="worst_csi"):
        _card(worst_csi_value=None)
    with pytest.raises(ValidationError):
        _card(max_psi_by_comparison=["no permitido"])


def test_stability_result_envuelve_dataframes_records_y_card_con_copias() -> None:
    psi_table = _psi_table()
    stability_metrics = _stability_metrics_frame()
    result = _result(psi_table=psi_table, stability_metrics=stability_metrics)

    psi_table.loc["psi_0", "expected_pct"] = 0.99
    stability_metrics.loc["m0", "value"] = 0.99
    observed_psi = result.psi_table
    observed_metrics = result.stability_metrics

    assert result.psi_table is not result.psi_table
    assert result.stability_metrics is not result.stability_metrics
    assert_frame_equal(observed_psi, _normalized_psi_table())
    assert_frame_equal(observed_metrics, _normalized_stability_metrics_frame())
    assert tuple(observed_psi.columns) == (
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
    assert tuple(observed_metrics.columns) == (
        "metric",
        "comparison",
        "feature",
        "value",
        "stable_threshold",
        "review_threshold",
        "band",
        "action",
    )

    observed_psi.loc["psi_0", "expected_pct"] = 0.77
    observed_metrics.loc["m0", "value"] = 0.77
    assert_frame_equal(result.psi_table, _normalized_psi_table())
    assert_frame_equal(result.stability_metrics, _normalized_stability_metrics_frame())

    round_tripped = StabilityResult.model_validate(
        {
            "psi_table": result.psi_table,
            "stability_metrics": result.stability_metrics,
            "psi_records": [record.model_dump() for record in result.psi_records],
            "csi_records": [record.model_dump() for record in result.csi_records],
            "metric_records": [record.model_dump() for record in result.metric_records],
            "temporal_records": [record.model_dump() for record in result.temporal_records],
            "card": result.card.model_dump(),
        }
    )
    assert_frame_equal(round_tripped.psi_table, result.psi_table)
    assert_frame_equal(round_tripped.stability_metrics, result.stability_metrics)
    assert round_tripped.psi_records == result.psi_records
    assert round_tripped.csi_records == result.csi_records
    assert round_tripped.metric_records == result.metric_records
    assert round_tripped.temporal_records == result.temporal_records
    assert round_tripped.card == result.card

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card()
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_stability_result_valida_dataframes_y_consistencia_card() -> None:
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(psi_table="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(psi_table=_psi_table().drop(columns=["band"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(stability_metrics=_stability_metrics_frame().drop(columns=["action"]))
    with pytest.raises(ValidationError, match=r"card\.comparisons"):
        _result(
            card=_card(
                comparisons=("dev_vs_oot", "dev_vs_holdout"),
                max_psi_by_comparison={"dev_vs_oot": 0.190, "dev_vs_holdout": 0.083},
                bands_by_comparison={"dev_vs_oot": "review", "dev_vs_holdout": "stable"},
            )
        )
    with pytest.raises(ValidationError, match="max_psi_by_comparison"):
        _result(card=_card(max_psi_by_comparison={"dev_vs_holdout": 0.084, "dev_vs_oot": 0.190}))
    with pytest.raises(ValidationError, match="bands_by_comparison"):
        _result(
            card=_card(bands_by_comparison={"dev_vs_holdout": "review", "dev_vs_oot": "review"})
        )
    with pytest.raises(ValidationError, match="worst_csi"):
        _result(card=_card(worst_csi_value=0.200))
    with pytest.raises(ValidationError, match="comparaciones no resumidas"):
        _result(psi_records=(_psi_record(comparison="dev_vs_unknown"),))
    with pytest.raises(ValidationError, match="comparaciones no resumidas"):
        _result(csi_records=(_csi_record(comparison="dev_vs_unknown"),))


def test_helpers_resumen_cubren_maximos_y_peor_csi() -> None:
    records = (
        _metric_record(
            metric="score_psi", comparison="a", value=0.05, band="stable", action="none"
        ),
        _metric_record(
            metric="pd_psi", comparison="a", value=0.12, band="review", action="vigilar"
        ),
        _metric_record(
            metric="score_psi", comparison="b", value=None, band="not_evaluable", action="none"
        ),
        _metric_record(
            metric="pd_psi", comparison="b", value=0.30, band="redevelop", action="redesarrollar"
        ),
        _metric_record(
            metric="score_psi", comparison="c", value=0.07, band="stable", action="none"
        ),
        _metric_record(
            metric="pd_psi", comparison="c", value=None, band="not_evaluable", action="none"
        ),
        _metric_record(
            metric="csi",
            comparison="a",
            feature="edad",
            value=0.20,
            band="review",
            action="vigilar",
        ),
        _metric_record(
            metric="csi",
            comparison="b",
            feature="ingreso",
            value=0.35,
            band="redevelop",
            action="redesarrollar",
        ),
        _metric_record(
            metric="csi", comparison="a", feature="deuda", value=0.10, band="stable", action="none"
        ),
        _metric_record(
            metric="csi",
            comparison="c",
            feature="antig",
            value=None,
            band="not_evaluable",
            action="none",
        ),
        _metric_record(
            metric="temporal_score",
            comparison="2024-01",
            feature="score",
            value=0.04,
            band="stable",
            action="none",
        ),
    )

    assert _max_psi_by_comparison(records) == {"a": 0.12, "b": 0.30, "c": 0.07}
    assert _worst_csi(records) == ("ingreso", 0.35)
    assert _worst_csi(()) == (None, None)


def test_stability_results_lazy_exports_y_nucleo_liviano_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.core;"
        "import nikodym.stability as stability;"
        "blocked=[m for m in ('pandas','scipy','sklearn','statsmodels','optbinning') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "loaded=[getattr(stability, name) for name in "
        "('StabilityMetricRecord','PsiRecord','CsiRecord','TemporalStabilityRecord',"
        "'StabilityCardSection','StabilityResult')];"
        "assert loaded[-1].__name__ == 'StabilityResult';"
        "blocked=[m for m in ('pandas','scipy','sklearn','statsmodels','optbinning') "
        "if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert stability_pkg.StabilityResult is StabilityResult
    with pytest.raises(AttributeError, match="NoExiste"):
        _ = stability_pkg.NoExiste


def test_results_module_expone_aliases_publicos_de_config() -> None:
    assert stability_results.ScoreDirection == ConfigScoreDirection
    assert stability_results.CsiSource == ConfigCsiSource
    assert stability_results.StabilityComparison == ConfigStabilityComparison
    assert "StabilityMetricRecord" in stability_results.__all__
    assert "PsiRecord" in stability_results.__all__
    assert "CsiRecord" in stability_results.__all__
    assert "TemporalStabilityRecord" in stability_results.__all__
    assert "StabilityCardSection" in stability_results.__all__
    assert "StabilityResult" in stability_results.__all__


def _metric_record(**updates: Any) -> StabilityMetricRecord:
    payload: dict[str, Any] = {
        "metric": "score_psi",
        "comparison": "dev_vs_holdout",
        "feature": "score",
        "value": 0.083,
        "stable_threshold": 0.10,
        "review_threshold": 0.25,
        "band": "stable",
        "action": "none",
    }
    payload.update(updates)
    return StabilityMetricRecord(**payload)


def _psi_record(**updates: Any) -> PsiRecord:
    payload: dict[str, Any] = {
        "metric": "score_psi",
        "comparison": "dev_vs_holdout",
        "feature": "score",
        "bin_label": "(-inf, 380]",
        "expected_count": 120,
        "actual_count": 95,
        "expected_pct": 0.24,
        "actual_pct": 0.19,
        "component_value": 0.011,
        "total_value": 0.083,
        "band": "stable",
    }
    payload.update(updates)
    return PsiRecord(**payload)


def _csi_record(**updates: Any) -> CsiRecord:
    payload: dict[str, Any] = {
        "metric": "csi",
        "comparison": "dev_vs_oot",
        "feature": "ingreso_mensual",
        "bin_label": "bin_3",
        "expected_count": 40,
        "actual_count": 52,
        "expected_pct": 0.20,
        "actual_pct": 0.26,
        "component_value": 0.016,
        "total_value": 0.142,
        "band": "review",
    }
    payload.update(updates)
    return CsiRecord(**payload)


def _temporal_record(**updates: Any) -> TemporalStabilityRecord:
    payload: dict[str, Any] = {
        "period": "2024-01",
        "n_total": 1500,
        "mean_score": 512.0,
        "p25_score": 470.0,
        "p50_score": 510.0,
        "p75_score": 555.0,
        "mean_pd": 0.071,
        "psi": 0.045,
        "band": "stable",
    }
    payload.update(updates)
    return TemporalStabilityRecord(**payload)


def _card(**updates: Any) -> StabilityCardSection:
    payload: dict[str, Any] = {
        "score_direction": "higher_is_lower_risk",
        "csi_source": "score_points",
        "comparisons": ("dev_vs_holdout", "dev_vs_oot"),
        "psi_bins": 10,
        "stable_threshold": 0.10,
        "review_threshold": 0.25,
        "max_psi_by_comparison": {"dev_vs_holdout": 0.083, "dev_vs_oot": 0.190},
        "bands_by_comparison": {"dev_vs_holdout": "stable", "dev_vs_oot": "review"},
        "worst_csi_feature": "ingreso_mensual",
        "worst_csi_value": 0.142,
        "dependency_versions": {"pandas": "2.3.3", "numpy": "2.4.6", "sklearn": "1.7.2"},
    }
    payload.update(updates)
    return StabilityCardSection(**payload)


def _result(
    *,
    psi_table: Any | None = None,
    stability_metrics: Any | None = None,
    psi_records: tuple[PsiRecord, ...] | None = None,
    csi_records: tuple[CsiRecord, ...] | None = None,
    metric_records: tuple[StabilityMetricRecord, ...] | None = None,
    temporal_records: tuple[TemporalStabilityRecord, ...] | None = None,
    card: StabilityCardSection | None = None,
    extra: object | None = None,
) -> StabilityResult:
    payload: dict[str, Any] = {
        "psi_table": _psi_table() if psi_table is None else psi_table,
        "stability_metrics": _stability_metrics_frame()
        if stability_metrics is None
        else stability_metrics,
        "psi_records": _psi_records() if psi_records is None else psi_records,
        "csi_records": _csi_records() if csi_records is None else csi_records,
        "metric_records": _metric_records() if metric_records is None else metric_records,
        "temporal_records": _temporal_records() if temporal_records is None else temporal_records,
        "card": _card() if card is None else card,
    }
    if extra is not None:
        payload["extra"] = extra
    return StabilityResult(**payload)


def _metric_records() -> tuple[StabilityMetricRecord, ...]:
    return (
        _metric_record(),
        _metric_record(comparison="dev_vs_oot", value=0.190, band="review", action="vigilar"),
        _metric_record(
            metric="csi",
            comparison="dev_vs_oot",
            feature="ingreso_mensual",
            value=0.142,
            band="review",
            action="vigilar",
        ),
    )


def _psi_records() -> tuple[PsiRecord, ...]:
    return (
        _psi_record(),
        _psi_record(comparison="dev_vs_oot", bin_label="(380, inf)", band="review"),
    )


def _csi_records() -> tuple[CsiRecord, ...]:
    return (_csi_record(),)


def _temporal_records() -> tuple[TemporalStabilityRecord, ...]:
    return (
        _temporal_record(),
        _temporal_record(period="2024-02", psi=0.061, band="stable"),
    )


def _psi_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "metric": ["score_psi", "csi"],
            "comparison": ["dev_vs_holdout", "dev_vs_oot"],
            "feature": ["score", "ingreso_mensual"],
            "bin_label": ["(-inf, 380]", "bin_3"],
            "expected_count": [120, 40],
            "actual_count": [95, 52],
            "expected_pct": [0.60, 0.20],
            "actual_pct": [0.48, 0.26],
            "component_value": [-0.0, 0.016],
            "total_value": [0.083, 0.142],
            "band": ["stable", "review"],
        },
        index=pd.Index(["psi_0", "csi_0"], name="row_id"),
    )


def _stability_metrics_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "metric": ["score_psi", "csi"],
            "comparison": ["dev_vs_holdout", "dev_vs_oot"],
            "feature": ["score", "ingreso_mensual"],
            "value": [0.083, 0.142],
            "stable_threshold": [0.10, 0.10],
            "review_threshold": [0.25, 0.25],
            "band": ["stable", "review"],
            "action": ["none", "vigilar"],
        },
        index=pd.Index(["m0", "m1"], name="metric_id"),
    )


def _normalized_psi_table() -> pd.DataFrame:
    return _normalize_frame(_psi_table())


def _normalized_stability_metrics_frame() -> pd.DataFrame:
    return _normalize_frame(_stability_metrics_frame())


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    for column in normalized.select_dtypes(include=["float"]).columns:
        normalized[column] = normalized[column].mask(normalized[column] == 0.0, 0.0)
    return normalized
