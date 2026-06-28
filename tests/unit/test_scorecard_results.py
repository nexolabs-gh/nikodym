"""Tests de resultados de ``scorecard``: DTOs puros, copias y lazy exports."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any, cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.scorecard.results as scorecard_results
from nikodym.scorecard.config import (
    RoundingMethod as ConfigRoundingMethod,
)
from nikodym.scorecard.config import (
    ScoreDirection as ConfigScoreDirection,
)
from nikodym.scorecard.results import (
    ScorecardBinPoint,
    ScorecardCardSection,
    ScorecardResult,
)


def test_scorecard_bin_point_frozen_extra_forbid_y_normaliza_float() -> None:
    point = ScorecardBinPoint(
        feature="saldo",
        woe_column="saldo__woe",
        bin_label="[0, 100)",
        bin_index=0,
        woe=-0.0,
        beta=-0.0,
        intercept_share=-0.0,
        raw_points=-0.0,
        points=-0.0,
        rounding_delta=-0.0,
        source="binning_table",
    )

    assert point.model_dump(mode="json") == {
        "feature": "saldo",
        "woe_column": "saldo__woe",
        "bin_label": "[0, 100)",
        "bin_index": 0,
        "woe": 0.0,
        "beta": 0.0,
        "intercept_share": 0.0,
        "raw_points": 0.0,
        "points": 0.0,
        "rounding_delta": 0.0,
        "source": "binning_table",
    }
    assert math.copysign(1.0, point.woe) == 1.0
    assert isinstance(point.points, float)
    assert math.copysign(1.0, point.points) == 1.0
    integer_point = ScorecardBinPoint(**(point.model_dump() | {"points": 12}))
    assert integer_point.points == 12
    with pytest.raises(ValidationError, match="frozen"):
        point.points = 99.0
    with pytest.raises(ValidationError):
        ScorecardBinPoint(**(point.model_dump() | {"source": "formula_unseen"}))
    with pytest.raises(ValidationError):
        ScorecardBinPoint(**(point.model_dump() | {"origen": "interno"}))


def test_scorecard_card_section_golden_copias_y_metric_sections() -> None:
    metric_sections: dict[str, Any] = {
        "diagnostico": {
            "delta": -0.0,
            "serie": [math.nan, -0.0],
            "tupla": (-0.0,),
            "nota": "ok",
        }
    }
    card = _card(
        pdo=-0.0,
        target_score=-0.0,
        min_score=math.inf,
        max_score=math.nan,
        dependency_versions={"pandas": "2.3.3", "numpy": "2.4.6"},
        metric_sections=metric_sections,
    )

    expected_dump = {
        "pdo": 0.0,
        "target_score": 0.0,
        "target_odds": 30.0,
        "factor": 34.62468061392734,
        "offset": 522.2472200776769,
        "score_direction": "higher_is_lower_risk",
        "rounding_method": "nearest_integer",
        "n_variables": 2,
        "score_column": "score",
        "points_columns": ["saldo__points", "mora__points"],
        "min_score": None,
        "max_score": None,
        "overrides_count": 1,
        "dependency_versions": {"numpy": "2.4.6", "pandas": "2.3.3"},
        "metric_sections": {
            "diagnostico": {
                "delta": 0.0,
                "serie": [None, 0.0],
                "tupla": [0.0],
                "nota": "ok",
            }
        },
    }
    assert card.model_dump(mode="json") == expected_dump
    assert math.copysign(1.0, card.metric_sections["diagnostico"]["delta"]) == 1.0

    metric_sections["diagnostico"]["delta"] = 99.0
    card.metric_sections["diagnostico"]["delta"] = 88.0
    card.dependency_versions["pandas"] = "mutado"
    assert card.metric_sections == {
        "diagnostico": {"delta": 0.0, "serie": [None, 0.0], "tupla": (0.0,), "nota": "ok"}
    }
    assert card.dependency_versions == {"numpy": "2.4.6", "pandas": "2.3.3"}
    with pytest.raises(ValidationError, match="frozen"):
        card.offset = 1.0
    with pytest.raises(ValidationError):
        _card(extra="no permitido")


def test_card_metric_sections_none_e_invalido() -> None:
    assert _card(metric_sections=None).metric_sections == {}
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])


def test_card_filtra_limites_no_finitos_antes_de_comparar() -> None:
    sin_limites = _card(min_score=None, max_score=None)
    min_infinito = _card(min_score=math.inf, max_score=500.0)
    max_nan = _card(min_score=250.0, max_score=math.nan)
    bool_descartado = _card(min_score=True, max_score=700.0)

    assert sin_limites.min_score is None
    assert sin_limites.max_score is None
    assert min_infinito.min_score is None
    assert min_infinito.max_score == 500.0
    assert max_nan.min_score == 250.0
    assert max_nan.max_score is None
    assert bool_descartado.min_score is None
    with pytest.raises(ValidationError, match="min_score debe ser menor"):
        _card(min_score=800.0, max_score=700.0)
    with pytest.raises(ValidationError, match="n_variables"):
        _card(n_variables=3)


def test_scorecard_result_construible_con_copias_defensivas_y_normalizacion() -> None:
    scorecard = _scorecard_frame()
    score = _score_frame()
    result = _result(scorecard=scorecard, score=score)

    scorecard.loc[0, "points"] = 999.0
    score.loc["c1", "score"] = 999.0
    observed_scorecard = result.scorecard
    observed_score = result.score

    assert_frame_equal(observed_scorecard, _normalized_scorecard_frame())
    assert_frame_equal(observed_score, _normalized_score_frame())
    assert math.copysign(1.0, observed_scorecard.loc[0, "raw_points"]) == 1.0
    assert math.copysign(1.0, observed_score.loc["c1", "saldo__points"]) == 1.0

    observed_scorecard.loc[0, "points"] = 777.0
    observed_score.loc["c1", "score"] = 777.0
    assert_frame_equal(result.scorecard, _normalized_scorecard_frame())
    assert_frame_equal(result.score, _normalized_score_frame())


def test_scorecard_result_valida_consistencia_y_dataframe() -> None:
    with pytest.raises(ValidationError, match="factor"):
        _result(card=_card(factor=99.0))
    with pytest.raises(ValidationError, match="offset"):
        _result(card=_card(offset=99.0))
    with pytest.raises(ValidationError, match="score_direction"):
        _result(card=_card(score_direction="higher_is_higher_risk"))
    with pytest.raises(ValidationError, match="points_columns"):
        _result(card=_card(n_variables=1, points_columns=("saldo__points",)))
    with pytest.raises(ValidationError, match="score_column"):
        _result(card=_card(score_column="score_total"))
    with pytest.raises(ValidationError, match="score_column"):
        _result(score=_score_frame().drop(columns=["score"]))
    with pytest.raises(ValidationError, match="columnas de puntos"):
        _result(score=_score_frame().drop(columns=["mora__points"]))
    with pytest.raises(ValidationError):
        _result(extra="no permitido")
    with pytest.raises(ValidationError):
        _result(scorecard=cast(Any, "no es DataFrame"))


def test_scorecard_results_lazy_exports_y_nucleo_liviano_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.scorecard as scorecard;"
        "blocked=[m for m in ('pandas','statsmodels','sklearn','scipy','optbinning') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "loaded=[getattr(scorecard, name) for name in "
        "('ScorecardBinPoint','ScorecardCardSection','ScorecardResult')];"
        "assert loaded[-1].__name__ == 'ScorecardResult';"
        "assert 'pandas' in sys.modules;"
        "blocked=[m for m in ('statsmodels','sklearn','scipy','optbinning') if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_results_module_expone_aliases_publicos_de_config() -> None:
    assert scorecard_results.ScoreDirection == ConfigScoreDirection
    assert scorecard_results.RoundingMethod == ConfigRoundingMethod
    assert "ScorecardBinPoint" in scorecard_results.__all__
    assert "ScorecardCardSection" in scorecard_results.__all__
    assert "ScorecardResult" in scorecard_results.__all__


def _card(**updates: Any) -> ScorecardCardSection:
    payload: dict[str, Any] = {
        "pdo": 24.0,
        "target_score": 640.0,
        "target_odds": 30.0,
        "factor": 34.62468061392734,
        "offset": 522.2472200776769,
        "score_direction": "higher_is_lower_risk",
        "rounding_method": "nearest_integer",
        "n_variables": 2,
        "score_column": "score",
        "points_columns": ("saldo__points", "mora__points"),
        "min_score": 300.0,
        "max_score": 900.0,
        "overrides_count": 1,
        "dependency_versions": {"pandas": "2.3.3"},
    }
    payload.update(updates)
    return ScorecardCardSection(**payload)


def _result(
    *,
    scorecard: pd.DataFrame | None = None,
    score: pd.DataFrame | None = None,
    card: ScorecardCardSection | None = None,
    extra: object | None = None,
) -> ScorecardResult:
    payload: dict[str, Any] = {
        "scorecard": _scorecard_frame() if scorecard is None else scorecard,
        "score": _score_frame() if score is None else score,
        "factor": 34.62468061392734,
        "offset": 522.2472200776769,
        "score_direction": "higher_is_lower_risk",
        "points_columns": ("saldo__points", "mora__points"),
        "score_column": "score",
        "card": _card() if card is None else card,
    }
    if extra is not None:
        payload["extra"] = extra
    return ScorecardResult(**payload)


def _scorecard_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "feature": ["saldo", "saldo", "mora"],
            "woe_column": ["saldo__woe", "saldo__woe", "mora__woe"],
            "bin_label": ["[0, 100)", "[100, inf)", "mora_alta"],
            "bin_index": [0, 1, 0],
            "woe": [-0.0, 0.75, -0.25],
            "beta": [-0.42, -0.42, -0.31],
            "intercept_share": [12.0, 12.0, 12.0],
            "raw_points": [-0.0, 18.4, 9.6],
            "points": [-0.0, 18.0, 10.0],
            "rounding_delta": [-0.0, -0.4, 0.4],
            "source": ["binning_table", "override", "binning_table"],
        }
    )


def _score_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "saldo__points": [-0.0, 18.0],
            "mora__points": [10.0, -0.0],
            "score": [10.0, 18.0],
            "partition": ["desarrollo", "holdout"],
        },
        index=pd.Index(["c1", "c2"], name="cliente_id"),
    )


def _normalized_scorecard_frame() -> pd.DataFrame:
    return _normalize_frame(_scorecard_frame())


def _normalized_score_frame() -> pd.DataFrame:
    return _normalize_frame(_score_frame())


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    for column in normalized.select_dtypes(include=["float"]).columns:
        normalized[column] = normalized[column].mask(normalized[column] == 0.0, 0.0)
    return normalized
