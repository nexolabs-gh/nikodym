"""Tests de resultados de ``binning``: bandas IV, contenedores y model card."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.binning
from nikodym.binning.exceptions import BinningError
from nikodym.binning.results import (
    BinningCardSection,
    BinningResult,
    BinningVariableSummary,
    iv_band,
)


@pytest.mark.parametrize(
    ("iv", "expected"),
    [
        (0.0, "none"),
        (0.0199, "none"),
        (0.02, "weak"),
        (0.0999, "weak"),
        (0.10, "medium"),
        (0.2999, "medium"),
        (0.30, "strong"),
        (0.4999, "strong"),
        (0.50, "suspicious"),
        (1.0, "suspicious"),
    ],
)
def test_iv_band_fronteras_exacto(iv: float, expected: str) -> None:
    assert iv_band(iv) == expected


@pytest.mark.parametrize("iv", [math.nan, math.inf, -0.01])
def test_iv_band_rechaza_valores_no_defendibles(iv: float) -> None:
    with pytest.raises(BinningError, match=rf"valor observado={iv!r}"):
        iv_band(iv)


def test_binning_variable_summary_construible_y_frozen() -> None:
    summary = BinningVariableSummary(
        name="saldo",
        dtype="numerical",
        status="OPTIMAL",
        selected=True,
        n_bins=4,
        iv=0.31,
        iv_band="strong",
        monotonic_trend="ascending",
    )

    assert summary.skipped_reason is None
    with pytest.raises(ValidationError, match="frozen"):
        summary.status = "FEASIBLE"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "name": "segmento",
            "dtype": "ordinal",
            "status": "OPTIMAL",
            "selected": True,
            "n_bins": 3,
            "iv": 0.12,
            "iv_band": "medium",
            "monotonic_trend": None,
        },
        {
            "name": "segmento",
            "dtype": "categorical",
            "status": "OPTIMAL",
            "selected": True,
            "n_bins": 3,
            "iv": 0.12,
            "iv_band": "alto",
            "monotonic_trend": None,
        },
    ],
)
def test_binning_variable_summary_rechaza_literals_invalidos(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        BinningVariableSummary(**payload)


def test_binning_result_construible_con_dataframes() -> None:
    result = _binning_result()

    assert_frame_equal(result.woe_frame, _woe_frame())
    assert set(result.tables) == {"saldo", "segmento"}
    assert_frame_equal(result.summary, _summary_frame())
    assert result.woe_column_map == {"saldo": "saldo__woe", "segmento": "segmento__woe"}
    assert result.skipped_variables == {"edad": "all_missing"}


def test_binning_card_section_from_result_golden_y_orden_determinista() -> None:
    result = _binning_result()
    card = BinningCardSection.from_result(
        result,
        special_handling="separate",
        missing_handling="empirical",
        optbinning_version="0.20.0",
    )

    expected = BinningCardSection(
        n_variables_requested=3,
        n_variables_binned=2,
        n_variables_skipped=1,
        iv_by_variable={"saldo": 0.31, "segmento": 0.12},
        monotonicity_by_variable={"saldo": "ascending", "segmento": None},
        special_handling="separate",
        missing_handling="empirical",
        optbinning_version="0.20.0",
    )
    assert card == expected
    assert list(card.iv_by_variable) == ["saldo", "segmento"]
    assert list(card.monotonicity_by_variable) == ["saldo", "segmento"]


def test_binning_card_section_from_result_no_muta_resultado() -> None:
    result = _binning_result()
    original_woe = result.woe_frame.copy(deep=True)
    original_summary = result.summary.copy(deep=True)
    original_tables = {name: table.copy(deep=True) for name, table in result.tables.items()}
    original_variable_summaries = result.variable_summaries
    original_column_map = dict(result.woe_column_map)
    original_skipped = dict(result.skipped_variables)

    BinningCardSection.from_result(
        result,
        special_handling="separate",
        missing_handling="empirical",
        optbinning_version="0.20.0",
    )

    assert_frame_equal(result.woe_frame, original_woe)
    assert_frame_equal(result.summary, original_summary)
    for name, table in original_tables.items():
        assert_frame_equal(result.tables[name], table)
    assert result.variable_summaries == original_variable_summaries
    assert result.woe_column_map == original_column_map
    assert result.skipped_variables == original_skipped


def test_binning_lazy_exports_publicos_cargan_results_bajo_demanda() -> None:
    assert nikodym.binning.BinningResult is BinningResult
    assert nikodym.binning.BinningVariableSummary is BinningVariableSummary
    assert nikodym.binning.BinningCardSection is BinningCardSection
    assert nikodym.binning.iv_band is iv_band


def _variable_summaries() -> tuple[BinningVariableSummary, ...]:
    return (
        BinningVariableSummary(
            name="saldo",
            dtype="numerical",
            status="OPTIMAL",
            selected=True,
            n_bins=4,
            iv=0.31,
            iv_band="strong",
            monotonic_trend="ascending",
        ),
        BinningVariableSummary(
            name="segmento",
            dtype="categorical",
            status="OPTIMAL",
            selected=True,
            n_bins=3,
            iv=0.12,
            iv_band="medium",
            monotonic_trend=None,
        ),
    )


def _woe_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "target": pd.Series([0, 1], dtype="int64"),
            "partition": ["desarrollo", "holdout"],
            "saldo__woe": [0.7, -0.4],
            "segmento__woe": [0.1, -0.2],
        },
        index=pd.Index(["c1", "c2"], name="cliente_id"),
    )


def _summary_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": ["saldo", "segmento"],
            "dtype": ["numerical", "categorical"],
            "status": ["OPTIMAL", "OPTIMAL"],
            "selected": pd.Series([True, True], dtype="bool"),
            "n_bins": pd.Series([4, 3], dtype="int64"),
            "iv": [0.31, 0.12],
        }
    )


def _tables() -> dict[str, pd.DataFrame]:
    return {
        "saldo": pd.DataFrame(
            {
                "Bin": ["(-inf, 0]", "(0, inf)"],
                "Count": pd.Series([10, 8], dtype="int64"),
                "WoE": [0.7, -0.4],
                "IV": [0.2, 0.11],
            }
        ),
        "segmento": pd.DataFrame(
            {
                "Bin": ["A", "B"],
                "Count": pd.Series([9, 9], dtype="int64"),
                "WoE": [0.1, -0.2],
                "IV": [0.05, 0.07],
            }
        ),
    }


def _binning_result() -> BinningResult:
    return BinningResult(
        woe_frame=_woe_frame(),
        tables=_tables(),
        summary=_summary_frame(),
        variable_summaries=_variable_summaries(),
        woe_column_map={"saldo": "saldo__woe", "segmento": "segmento__woe"},
        skipped_variables={"edad": "all_missing"},
    )
