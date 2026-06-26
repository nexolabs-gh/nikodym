"""Tests de ``DataQualityProfiler`` (SDD-27 §3/§4/§7): calidad descriptiva."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pandas.testing import assert_frame_equal

import nikodym.eda as eda
from nikodym.core.audit import InMemoryAuditSink
from nikodym.eda.config import QualityConfig
from nikodym.eda.exceptions import EdaError
from nikodym.eda.quality import DataQualityProfiler, QualityResult


def _profiler(**kwargs: object) -> DataQualityProfiler:
    return DataQualityProfiler(QualityConfig.model_validate(kwargs))


def _quality_frame() -> pd.DataFrame:
    index = pd.Index([f"op-{position:03d}" for position in range(10)], name="loan_id")
    return pd.DataFrame(
        {
            "near_constant": pd.Series(["A"] * 9 + ["B"], index=index, dtype="object"),
            "high_card": pd.Series(
                ["A", "B", "C", "D", "E", "A", "B", "C", "D", None],
                index=index,
                dtype="object",
            ),
            "id_num": pd.Series(range(1001, 1011), index=index, dtype="int64"),
            "normal_num": pd.Series(
                [1.0, 2.0, 3.0, 4.0, 5.0, 1.0, 2.0, 3.0, 4.0, 5.0],
                index=index,
                dtype="float64",
            ),
        },
        index=index,
    )


def test_from_config_y_superficie_no_estimador() -> None:
    cfg = QualityConfig(near_constant_threshold=0.80, high_cardinality_threshold=3)

    profiler = DataQualityProfiler.from_config(cfg)

    assert profiler.config is cfg
    assert not hasattr(profiler, "fit")
    assert not hasattr(profiler, "predict")


def test_reexports_perezosos_de_quality() -> None:
    assert eda.__getattr__("DataQualityProfiler") is DataQualityProfiler
    assert eda.__getattr__("QualityResult") is QualityResult


def test_golden_flags_por_columna_y_no_muta_frame() -> None:
    df = _quality_frame()
    original = df.copy(deep=True)
    audit = InMemoryAuditSink()

    result = _profiler(near_constant_threshold=0.80, high_cardinality_threshold=3).profile(
        df, audit=audit
    )

    expected = pd.DataFrame(
        {
            "col": ["near_constant", "high_card", "id_num", "normal_num"],
            "dtype": ["object", "object", "int64", "float64"],
            "missing_rate": [0.0, 0.1, 0.0, 0.0],
            "cardinality": pd.Series([2, 5, 10, 5], dtype="int64"),
            "near_constant": pd.Series([True, False, False, False], dtype="bool"),
            "near_unique": pd.Series([False, False, True, False], dtype="bool"),
            "high_cardinality": pd.Series([False, True, False, False], dtype="bool"),
        }
    )
    assert isinstance(result, QualityResult)
    assert list(result.by_column.columns) == [
        "col",
        "dtype",
        "missing_rate",
        "cardinality",
        "near_constant",
        "near_unique",
        "high_cardinality",
    ]
    assert_frame_equal(result.by_column, expected)
    assert audit.events == []
    assert_frame_equal(df, original)


def test_columna_cien_por_ciento_missing_no_divide_por_cero() -> None:
    index = pd.Index(["op-1", "op-2", "op-3"], name="loan_id")
    df = pd.DataFrame(
        {"all_missing": pd.Series([np.nan, np.nan, np.nan], index=index, dtype="float64")},
        index=index,
    )

    result = _profiler().profile(df)

    row = result.by_column.loc[0]
    assert row["col"] == "all_missing"
    assert row["missing_rate"] == pytest.approx(1.0)
    assert row["cardinality"] == 0
    assert not bool(row["near_constant"])
    assert not bool(row["near_unique"])
    assert not bool(row["high_cardinality"])


def test_invariancia_a_reordenar_filas() -> None:
    df = _quality_frame()
    reordered = df.loc[list(reversed(df.index))]
    profiler = _profiler(near_constant_threshold=0.80, high_cardinality_threshold=3)

    base = profiler.profile(df)
    permuted = profiler.profile(reordered)

    assert_frame_equal(base.by_column, permuted.by_column)


def test_numerica_con_infinitos_los_cuenta_como_missing_no_cardinalidad() -> None:
    index = pd.Index([f"op-{position}" for position in range(5)], name="loan_id")
    df = pd.DataFrame(
        {"ratio": pd.Series([1.0, np.inf, 2.0, -np.inf, 2.0], index=index)},
        index=index,
    )

    result = _profiler().profile(df)

    row = result.by_column.loc[0]
    assert row["dtype"] == "float64"
    assert row["missing_rate"] == pytest.approx(2 / 5)
    assert row["cardinality"] == 2
    assert not bool(row["near_constant"])
    assert not bool(row["near_unique"])
    assert not bool(row["high_cardinality"])


def test_category_dtype_activa_high_cardinality_solo_para_categoricas() -> None:
    index = pd.Index([f"op-{position}" for position in range(6)], name="loan_id")
    df = pd.DataFrame(
        {
            "segment": pd.Series(
                pd.Categorical(["A", "B", "C", "D", "A", None]),
                index=index,
            ),
            "numeric_id": pd.Series([1, 2, 3, 4, 5, 6], index=index, dtype="int64"),
        },
        index=index,
    )

    result = _profiler(near_constant_threshold=0.90, high_cardinality_threshold=3).profile(df)

    assert result.by_column["high_cardinality"].tolist() == [True, False]
    assert result.by_column["near_unique"].tolist() == [False, True]


@pytest.mark.parametrize(
    ("frame", "match"),
    [
        (
            pd.DataFrame({"x": pd.Series(dtype="float64")}),
            "no tiene filas",
        ),
        (
            pd.DataFrame(
                {"x": pd.Series([1.0, 2.0], index=["op-1", "op-1"])},
                index=pd.Index(["op-1", "op-1"], name="loan_id"),
            ),
            "índice único",
        ),
    ],
)
def test_errores_de_contrato_son_edaerror_en_espanol(frame: pd.DataFrame, match: str) -> None:
    with pytest.raises(EdaError, match=match):
        _profiler().profile(frame)


@st.composite
def _quality_frames(draw: st.DrawFn) -> pd.DataFrame:
    n_rows = draw(st.integers(min_value=1, max_value=30))
    numeric_values = draw(
        st.lists(
            st.one_of(
                st.floats(
                    min_value=-100.0,
                    max_value=100.0,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                st.none(),
            ),
            min_size=n_rows,
            max_size=n_rows,
        )
    )
    categories = draw(
        st.lists(
            st.one_of(st.sampled_from(["A", "B", "C", "D"]), st.none()),
            min_size=n_rows,
            max_size=n_rows,
        )
    )
    index = pd.Index([f"op-{position:03d}" for position in range(n_rows)], name="loan_id")
    numeric = [np.nan if value is None else value for value in numeric_values]
    return pd.DataFrame(
        {
            "numeric": pd.Series(numeric, index=index, dtype="float64"),
            "category": pd.Series(categories, index=index, dtype="object"),
        },
        index=index,
    )


@settings(max_examples=40, deadline=None)
@given(frame=_quality_frames())
def test_hypothesis_missing_rate_en_rango_y_cardinalidad_no_negativa(
    frame: pd.DataFrame,
) -> None:
    result = _profiler(near_constant_threshold=0.75, high_cardinality_threshold=3).profile(frame)

    assert result.by_column["missing_rate"].between(0.0, 1.0).all()
    assert result.by_column["cardinality"].ge(0).all()
    assert result.by_column["col"].tolist() == ["numeric", "category"]
