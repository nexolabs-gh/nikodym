"""Tests de ``EdaCardSection``: resumen auditable del EDA para report/model card."""

from __future__ import annotations

from typing import Literal

import pandas as pd
import pytest

from nikodym.eda.card import EdaCardSection
from nikodym.eda.config import EdaConfig
from nikodym.eda.default_rate import DefaultRateResult
from nikodym.eda.figures import FigureSpec
from nikodym.eda.quality import QualityResult
from nikodym.eda.stability import StabilityResult
from nikodym.eda.step import EdaResult, EdaStep
from nikodym.eda.univariate import UnivariateResult


def _eda_result(
    metric_used: Literal["cv", "max_relative_drift", "trend_slope"] = "cv",
) -> EdaResult:
    """Construye un ``EdaResult`` fijo, sin ejecutar analizadores."""
    default_rate = DefaultRateResult(
        by_period=pd.DataFrame(
            {
                "period": pd.period_range("2024-01", periods=3, freq="M"),
                "n_total": pd.Series([10, 12, 8], dtype="int64"),
                "n_eligible": pd.Series([8, 10, 6], dtype="int64"),
                "n_bad": pd.Series([1, 2, 0], dtype="int64"),
                "default_rate": [0.125, 0.2, 0.0],
                "low_confidence": pd.Series([False, False, True], dtype="bool"),
            }
        ),
        axis="period",
        overall_rate=0.125,
    )
    stability = StabilityResult(
        cv=0.25,
        max_relative_drift=0.4,
        trend_slope=-0.02,
        metric_used=metric_used,
        threshold=0.2,
        flagged=True,
    )
    univariate = UnivariateResult(
        profiles={
            "score": pd.DataFrame(
                {
                    "tramo": ["bajo", "alto"],
                    "n": pd.Series([12, 12], dtype="int64"),
                    "coverage": [0.5, 0.5],
                    "default_rate": [0.1, 0.2],
                }
            ),
            "segment": pd.DataFrame(
                {
                    "tramo": ["A", "B"],
                    "n": pd.Series([18, 6], dtype="int64"),
                    "coverage": [0.75, 0.25],
                    "default_rate": [0.05, 0.3],
                }
            ),
        },
        descriptive_iv={"score": 0.7, "segment": 0.4},
    )
    quality = QualityResult(
        by_column=pd.DataFrame(
            {
                "col": ["score", "segment", "id_cliente", "saldo"],
                "dtype": ["float64", "object", "object", "float64"],
                "missing_rate": [0.0, 0.1, 0.0, 0.5],
                "cardinality": pd.Series([4, 3, 4, 2], dtype="int64"),
                "near_constant": pd.Series([True, False, True, False], dtype="bool"),
                "near_unique": pd.Series([False, True, True, False], dtype="bool"),
                "high_cardinality": pd.Series([False, False, True, True], dtype="bool"),
            }
        )
    )
    figures = (
        FigureSpec(
            kind="line",
            title="Tasa de default por período",
            data=default_rate.by_period.loc[:, ["period", "default_rate"]],
            x="period",
            y="default_rate",
        ),
        FigureSpec(
            kind="bar",
            title="Tasa de default por tramo: score",
            data=univariate.profiles["score"].loc[:, ["tramo", "default_rate"]],
            x="tramo",
            y="default_rate",
        ),
    )
    return EdaResult(
        default_rate=default_rate,
        stability=stability,
        univariate=univariate,
        quality=quality,
        figures=figures,
    )


@pytest.mark.parametrize(
    ("metric_used", "expected_stability_value"),
    [
        ("cv", 0.25),
        ("max_relative_drift", 0.4),
    ],
)
def test_build_eda_card_resume_campos_golden(
    metric_used: Literal["cv", "max_relative_drift"],
    expected_stability_value: float,
) -> None:
    """El card lee los campos ya calculados y produce golden values manuales."""
    result = _eda_result(metric_used=metric_used)
    card = EdaStep.from_config(EdaConfig())._build_eda_card(result=result)

    assert isinstance(card, EdaCardSection)
    assert card.overall_default_rate == 0.125
    assert card.n_periods == 3
    assert card.stability_flagged is True
    assert card.stability_metric_used == metric_used
    assert card.stability_threshold == 0.2
    assert card.stability_value == expected_stability_value
    assert card.n_columns_profiled == 2
    assert card.quality_flag_counts == {
        "near_constant": 2,
        "near_unique": 2,
        "high_cardinality": 2,
    }
    assert card.n_figures == 2


def test_build_eda_card_sobre_mismo_resultado_es_determinista() -> None:
    """El resumen del mismo ``EdaResult`` es idéntico y no introduce estado."""
    result = _eda_result(metric_used="max_relative_drift")
    step = EdaStep.from_config(EdaConfig())

    first = step._build_eda_card(result=result)
    second = step._build_eda_card(result=result)

    assert first == second
    assert first.model_dump() == {
        "overall_default_rate": 0.125,
        "n_periods": 3,
        "stability_flagged": True,
        "stability_metric_used": "max_relative_drift",
        "stability_threshold": 0.2,
        "stability_value": 0.4,
        "n_columns_profiled": 2,
        "quality_flag_counts": {
            "near_constant": 2,
            "near_unique": 2,
            "high_cardinality": 2,
        },
        "n_figures": 2,
    }
