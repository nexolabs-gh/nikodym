"""Tests de ``UnivariateProfiler`` (SDD-27 §3/§4/§6/§7): perfiles e IV descriptivo."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pandas.testing import assert_frame_equal

import nikodym.eda as eda
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.seeding import SeedManager
from nikodym.eda.config import UnivariateConfig
from nikodym.eda.exceptions import EdaError
from nikodym.eda.univariate import UnivariateProfiler, UnivariateResult


def _frame() -> pd.DataFrame:
    index = pd.Index([f"op-{position:03d}" for position in range(8)], name="loan_id")
    return pd.DataFrame(
        {
            "target": pd.Series([0, 1, 0, 1, pd.NA, 0, 1, 0], index=index, dtype="Int8"),
            "score": pd.Series([10.0, 20.0, 30.0, np.nan, 50.0, 60.0, 70.0, 80.0], index=index),
            "category": pd.Series(
                ["A", "B", "A", "C", "A", None, "rare", "B"],
                index=index,
                dtype="object",
            ),
        },
        index=index,
    )


def _profiler(**kwargs: object) -> UnivariateProfiler:
    return UnivariateProfiler(UnivariateConfig.model_validate(kwargs))


def _assert_univariate_equal(left: UnivariateResult, right: UnivariateResult) -> None:
    assert left.descriptive_iv.keys() == right.descriptive_iv.keys()
    for column, value in left.descriptive_iv.items():
        assert value == pytest.approx(right.descriptive_iv[column])
    assert left.profiles.keys() == right.profiles.keys()
    for column, profile in left.profiles.items():
        assert_frame_equal(profile, right.profiles[column])


def test_from_config_conserva_univariate_config() -> None:
    cfg = UnivariateConfig(n_quantile_bins=4, compute_descriptive_iv=True)

    profiler = UnivariateProfiler.from_config(cfg)

    assert profiler.config is cfg


def test_reexports_perezosos_de_univariate() -> None:
    assert eda.__getattr__("UnivariateProfiler") is UnivariateProfiler
    assert eda.__getattr__("UnivariateResult") is UnivariateResult


def test_columns_vacio_devuelve_resultado_vacio() -> None:
    result = _profiler().profile(_frame(), target_col="target", columns=())

    assert result == UnivariateResult(profiles={}, descriptive_iv={})


def test_golden_iv_descriptivo_dos_por_dos_con_laplace_y_no_muta_frame() -> None:
    index = pd.Index([f"op-{position:03d}" for position in range(10)], name="loan_id")
    df = pd.DataFrame(
        {
            "target": pd.Series([1, 1, 1, 0, 1, 0, 0, 0, 0, 0], index=index, dtype="Int8"),
            "segment": pd.Series(["alto"] * 4 + ["bajo"] * 6, index=index, dtype="object"),
        },
        index=index,
    )
    original = df.copy(deep=True)
    audit = InMemoryAuditSink()

    result = _profiler(compute_descriptive_iv=True).profile(
        df, target_col="target", columns=("segment",), audit=audit
    )

    expected = pd.DataFrame(
        {
            "tramo": ["alto", "bajo"],
            "n": pd.Series([4, 6], dtype="int64"),
            "coverage": [0.4, 0.6],
            "default_rate": [0.75, 1 / 6],
        }
    )
    assert_frame_equal(result.profiles["segment"], expected)
    # A mano: buenos/malos por tramo = alto 1/3, bajo 5/1; alpha=0.5, K=2.
    assert math.isclose(result.descriptive_iv["segment"], 1.0426249816227684)
    assert audit.events == []
    assert_frame_equal(df, original)


def test_coverage_suma_uno_y_n_suma_elegibles_para_numerica_y_categorica() -> None:
    df = _frame()

    result = _profiler(n_quantile_bins=3, rare_level_threshold=0.2).profile(
        df, target_col="target", columns=("score", "category")
    )

    eligible_rows = int(df["target"].isin((0, 1)).fillna(False).sum())
    for profile in result.profiles.values():
        assert list(profile.columns) == ["tramo", "n", "coverage", "default_rate"]
        assert int(profile["n"].sum()) == eligible_rows
        assert profile["coverage"].sum() == pytest.approx(1.0)

    category_profile = result.profiles["category"]
    assert category_profile["tramo"].tolist() == ["A", "B", "_otros_", "missing"]
    assert category_profile["n"].tolist() == [2, 2, 2, 1]


def test_columna_cien_por_ciento_missing_produce_tramo_missing() -> None:
    index = pd.Index(["op-1", "op-2", "op-3"], name="loan_id")
    df = pd.DataFrame(
        {
            "target": pd.Series([0, 1, 0], index=index, dtype="Int8"),
            "all_missing": pd.Series([np.nan, np.nan, np.nan], index=index),
        },
        index=index,
    )

    profile = (
        _profiler()
        .profile(df, target_col="target", columns=("all_missing",))
        .profiles["all_missing"]
    )

    expected = pd.DataFrame(
        {
            "tramo": ["missing"],
            "n": pd.Series([3], dtype="int64"),
            "coverage": [1.0],
            "default_rate": [1 / 3],
        }
    )
    assert_frame_equal(profile, expected)


def test_columna_categorica_completamente_faltante_produce_tramo_missing() -> None:
    """Una categórica 100% faltante produce solo el tramo ``missing``."""
    index = pd.Index(["op-1", "op-2", "op-3", "op-4"], name="loan_id")
    df = pd.DataFrame(
        {
            "target": pd.Series([0, 1, 0, 0], index=index, dtype="Int8"),
            "segmento": pd.Series(
                pd.array([pd.NA, pd.NA, pd.NA, pd.NA], dtype="string"),
                index=index,
            ),
        },
        index=index,
    )
    assert not pd.api.types.is_numeric_dtype(df["segmento"].dtype)

    profile = (
        UnivariateProfiler.from_config(UnivariateConfig())
        .profile(df, target_col="target", columns=("segmento",))
        .profiles["segmento"]
    )

    expected = pd.DataFrame(
        {
            "tramo": ["missing"],
            "n": pd.Series([4], dtype="int64"),
            "coverage": [1.0],
            "default_rate": [0.25],
        }
    )
    assert_frame_equal(profile, expected)


def test_numerica_con_infinitos_preserva_conteos_y_los_trata_como_missing() -> None:
    index = pd.Index([f"op-{position}" for position in range(6)], name="loan_id")
    df = pd.DataFrame(
        {
            "target": pd.Series([0, 1, 0, 1, 0, 1], index=index, dtype="Int8"),
            "ratio": pd.Series([1.0, np.inf, 2.0, -np.inf, 3.0, 4.0], index=index),
        },
        index=index,
    )

    profile = (
        _profiler(n_quantile_bins=3)
        .profile(df, target_col="target", columns=("ratio",))
        .profiles["ratio"]
    )

    missing = profile.loc[profile["tramo"].eq("missing")]
    assert int(profile["n"].sum()) == 6
    assert profile["coverage"].sum() == pytest.approx(1.0)
    assert missing["n"].tolist() == [2]
    assert missing["coverage"].tolist() == [pytest.approx(2 / 6)]
    assert profile["tramo"].iloc[-1] == "missing"


def test_sin_elegibles_reporta_missing_con_n_cero_y_tasa_nan() -> None:
    index = pd.Index(["op-1", "op-2"], name="loan_id")
    df = pd.DataFrame(
        {
            "target": pd.Series([pd.NA, pd.NA], index=index, dtype="Int8"),
            "score": pd.Series([1.0, 2.0], index=index),
            "category": pd.Series(["A", None], index=index, dtype="object"),
        },
        index=index,
    )

    result = _profiler(compute_descriptive_iv=True).profile(
        df, target_col="target", columns=("score", "category")
    )

    for profile in result.profiles.values():
        assert profile.loc[0, "tramo"] == "missing"
        assert profile.loc[0, "n"] == 0
        assert profile.loc[0, "coverage"] == pytest.approx(1.0)
        assert math.isnan(profile.loc[0, "default_rate"])
    assert result.descriptive_iv == {"score": 0.0, "category": 0.0}


def test_numerica_constante_y_qcut_con_bins_vacios_no_fallan() -> None:
    index = pd.Index([f"op-{position}" for position in range(6)], name="loan_id")
    df = pd.DataFrame(
        {
            "target": pd.Series([0, 1, 0, 1, 0, 1], index=index, dtype="Int8"),
            "constant": pd.Series([7.0] * 6, index=index),
            "repeated": pd.Series([1.0, 1.0, 2.0, 2.0, 3.0, 3.0], index=index),
        },
        index=index,
    )

    result = _profiler(n_quantile_bins=4).profile(
        df, target_col="target", columns=("constant", "repeated")
    )

    assert result.profiles["constant"]["tramo"].tolist() == ["[7.0, 7.0]"]
    assert result.profiles["constant"]["n"].tolist() == [6]
    assert int(result.profiles["repeated"]["n"].sum()) == 6
    assert result.profiles["repeated"]["coverage"].sum() == pytest.approx(1.0)


def test_iv_descriptivo_cero_normaliza_menos_cero() -> None:
    index = pd.Index([f"op-{position}" for position in range(4)], name="loan_id")
    df = pd.DataFrame(
        {
            "target": pd.Series([0, 1, 0, 1], index=index, dtype="Int8"),
            "segment": pd.Series(["A", "A", "B", "B"], index=index, dtype="object"),
        },
        index=index,
    )

    result = _profiler(compute_descriptive_iv=True).profile(
        df, target_col="target", columns=("segment",)
    )

    assert result.descriptive_iv["segment"] == 0.0
    assert math.copysign(1.0, result.descriptive_iv["segment"]) == 1.0


def test_invariancia_a_reordenar_filas_no_cambia_tablas_ni_iv() -> None:
    df = _frame()
    reordered = df.loc[list(reversed(df.index))]
    profiler = _profiler(n_quantile_bins=3, rare_level_threshold=0.2, compute_descriptive_iv=True)

    base = profiler.profile(df, target_col="target", columns=("score", "category"))
    permuted = profiler.profile(reordered, target_col="target", columns=("score", "category"))

    _assert_univariate_equal(base, permuted)


def test_determinismo_bit_identico_y_muestra_aguas_arriba_reproducible() -> None:
    df = _frame()
    profiler = _profiler(n_quantile_bins=3, rare_level_threshold=0.2, compute_descriptive_iv=True)

    first = profiler.profile(df, target_col="target", columns=("score", "category"))
    second = profiler.profile(df, target_col="target", columns=("score", "category"))
    _assert_univariate_equal(first, second)

    sample_a = df.sample(n=5, random_state=SeedManager(42).generator_for("eda"))
    sample_b = df.sample(n=5, random_state=SeedManager(42).generator_for("eda"))
    assert_frame_equal(sample_a, sample_b)
    sampled_first = profiler.profile(sample_a, target_col="target", columns=("score", "category"))
    sampled_second = profiler.profile(sample_b, target_col="target", columns=("score", "category"))
    _assert_univariate_equal(sampled_first, sampled_second)


@pytest.mark.parametrize(
    ("frame", "target_col", "columns", "match"),
    [
        (
            pd.DataFrame({"target": pd.Series(dtype="Int8"), "x": pd.Series(dtype="float64")}),
            "target",
            ("x",),
            "no tiene filas",
        ),
        (
            pd.DataFrame(
                {"target": pd.Series([1, 0], index=["op-1", "op-1"], dtype="Int8"), "x": [1, 2]},
                index=pd.Index(["op-1", "op-1"], name="loan_id"),
            ),
            "target",
            ("x",),
            "índice único",
        ),
        (
            pd.DataFrame({"x": [1, 2]}),
            "target",
            ("x",),
            "columna target existente",
        ),
        (
            pd.DataFrame({"target": pd.Series([1, 0], dtype="Int8"), "x": [1, 2]}),
            "target",
            ("z",),
            "columna\\(s\\) existente\\(s\\)",
        ),
    ],
)
def test_errores_de_contrato_son_edaerror_en_espanol(
    frame: pd.DataFrame, target_col: str, columns: tuple[str, ...], match: str
) -> None:
    with pytest.raises(EdaError, match=match):
        _profiler().profile(frame, target_col=target_col, columns=columns)


def test_columnas_duplicadas_levantan_edaerror_claro() -> None:
    index = pd.Index(["op-1", "op-2"], name="loan_id")
    df = pd.DataFrame(
        [[1, 10.0, 20.0], [0, 30.0, 40.0]],
        columns=["target", "x", "x"],
        index=index,
    )
    df["target"] = pd.Series([1, 0], index=index, dtype="Int8")

    with pytest.raises(EdaError, match="nombres de columnas únicos"):
        _profiler().profile(df, target_col="target", columns=("x",))


@st.composite
def _univariate_frames(draw: st.DrawFn) -> pd.DataFrame:
    n_rows = draw(st.integers(min_value=1, max_value=35))
    targets = draw(
        st.lists(
            st.one_of(st.integers(min_value=0, max_value=1), st.none()),
            min_size=n_rows,
            max_size=n_rows,
        )
    )
    scores = draw(
        st.lists(
            st.one_of(
                st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
                st.none(),
            ),
            min_size=n_rows,
            max_size=n_rows,
        )
    )
    categories = draw(
        st.lists(
            st.one_of(st.sampled_from(["A", "B", "C"]), st.none()),
            min_size=n_rows,
            max_size=n_rows,
        )
    )
    index = pd.Index([f"op-{position:03d}" for position in range(n_rows)], name="loan_id")
    target_values = [pd.NA if value is None else value for value in targets]
    return pd.DataFrame(
        {
            "target": pd.Series(target_values, index=index, dtype="Int8"),
            "score": pd.Series(scores, index=index, dtype="float64"),
            "category": pd.Series(categories, index=index, dtype="object"),
        },
        index=index,
    )


@settings(max_examples=40, deadline=None)
@given(frame=_univariate_frames())
def test_hypothesis_tasas_en_rango_e_invariante_a_reordenar(frame: pd.DataFrame) -> None:
    profiler = _profiler(n_quantile_bins=4, rare_level_threshold=0.15, compute_descriptive_iv=True)

    base = profiler.profile(frame, target_col="target", columns=("score", "category"))
    reordered = profiler.profile(
        frame.sample(frac=1.0, random_state=20240626),
        target_col="target",
        columns=("score", "category"),
    )

    for profile in base.profiles.values():
        rates = profile.loc[profile["n"] > 0, "default_rate"]
        assert rates.between(0.0, 1.0).all()
        assert int(profile["n"].sum()) == int(frame["target"].isin((0, 1)).fillna(False).sum())
        assert profile["coverage"].sum() == pytest.approx(1.0)
    _assert_univariate_equal(base, reordered)
