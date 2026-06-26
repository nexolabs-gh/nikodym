"""Tests de ``DefaultRateAnalyzer`` (SDD-27 §4/§6/§7): tasas y reproducibilidad."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

from nikodym.core.audit import InMemoryAuditSink
from nikodym.eda.config import DefaultRateConfig
from nikodym.eda.default_rate import DefaultRateAnalyzer, DefaultRateResult, _stable_label
from nikodym.eda.exceptions import EdaError


def _frame_from_targets(targets: list[int | None], months: list[str]) -> pd.DataFrame:
    index = pd.Index([f"op-{position:03d}" for position in range(len(targets))], name="loan_id")
    target_values = [pd.NA if value is None else value for value in targets]
    return pd.DataFrame(
        {
            "fecha": pd.Series(pd.to_datetime(months), index=index),
            "target": pd.Series(target_values, index=index, dtype="Int8"),
        },
        index=index,
    )


def _analyzer(**kwargs: object) -> DefaultRateAnalyzer:
    return DefaultRateAnalyzer(DefaultRateConfig(**kwargs))  # type: ignore[arg-type]


def test_from_config_conserva_default_rate_config() -> None:
    cfg = DefaultRateConfig(date_col="fecha", min_obs_per_period=10)

    analyzer = DefaultRateAnalyzer.from_config(cfg)

    assert analyzer.config is cfg


def test_golden_cien_elegibles_diez_malos_y_no_muta_frame() -> None:
    df = _frame_from_targets(
        targets=[1] * 10 + [0] * 90,
        months=["2024-01-15"] * 100,
    )
    original = df.copy(deep=True)
    audit = InMemoryAuditSink()

    result = _analyzer(date_col="fecha", min_obs_per_period=50).compute(
        df, target_col="target", audit=audit
    )

    assert isinstance(result, DefaultRateResult)
    assert result.axis == "period"
    assert list(result.by_period.columns) == [
        "period",
        "n_total",
        "n_eligible",
        "n_bad",
        "default_rate",
        "low_confidence",
    ]
    assert result.by_period.loc[0, "period"] == pd.Period("2024-01", freq="M")
    assert result.by_period.loc[0, "n_total"] == 100
    assert result.by_period.loc[0, "n_eligible"] == 100
    assert result.by_period.loc[0, "n_bad"] == 10
    assert result.by_period.loc[0, "default_rate"] == pytest.approx(0.10)
    assert result.overall_rate == pytest.approx(0.10)
    assert not bool(result.by_period.loc[0, "low_confidence"])
    assert audit.events == []
    assert_frame_equal(df, original)


def test_indice_duplicado_levanta_edaerror_sin_agregar_silenciosamente() -> None:
    df = pd.DataFrame(
        {
            "fecha": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-02-01"]),
            "target": pd.Series([1, 0, 1], index=["op-1", "op-1", "op-2"], dtype="Int8"),
        },
        index=pd.Index(["op-1", "op-1", "op-2"], name="loan_id"),
    )

    with pytest.raises(EdaError, match="índice único"):
        _analyzer(date_col="fecha").compute(df, target_col="target")


def test_indice_duplicado_axis_cohort_levanta_edaerror_antes_de_agrupar() -> None:
    index = pd.Index(["op-1", "op-1", "op-2"], name="loan_id")
    df = pd.DataFrame(
        {
            "cohort": pd.Series(["2024Q1", "2024Q2", "2024Q1"], index=index),
            "target": pd.Series([1, 0, 1], index=index, dtype="Int8"),
        },
        index=index,
    )

    with pytest.raises(EdaError, match="índice único"):
        _analyzer(axis="cohort", cohort_col="cohort").compute(df, target_col="target")


def test_overall_rate_es_ponderado_por_elegibles_no_promedio_simple() -> None:
    df = _frame_from_targets(
        targets=[1] * 10 + [0] * 90 + [1] * 5 + [0] * 5,
        months=["2024-01-15"] * 100 + ["2024-02-15"] * 10,
    )

    result = _analyzer(date_col="fecha", min_obs_per_period=20).compute(df, target_col="target")

    assert result.by_period["default_rate"].tolist() == [pytest.approx(0.10), pytest.approx(0.50)]
    assert result.by_period["low_confidence"].tolist() == [False, True]
    assert result.overall_rate == pytest.approx(15 / 110)
    assert result.overall_rate != pytest.approx((0.10 + 0.50) / 2)


def test_invariantes_de_conteo_incluyen_no_elegibles_en_n_total() -> None:
    df = _frame_from_targets(
        targets=[1, 0, None, 0, None, 1, 1],
        months=[
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-02-01",
            "2024-02-02",
            "2024-02-03",
            "2024-02-04",
        ],
    )

    result = _analyzer(date_col="fecha", min_obs_per_period=1).compute(df, target_col="target")

    assert (result.by_period["n_bad"] >= 0).all()
    assert (result.by_period["n_bad"] <= result.by_period["n_eligible"]).all()
    assert (result.by_period["n_eligible"] <= result.by_period["n_total"]).all()
    assert result.by_period["n_total"].tolist() == [3, 4]
    assert result.by_period["n_eligible"].tolist() == [2, 3]
    assert result.by_period["n_bad"].tolist() == [1, 2]


def test_n_eligible_cero_produce_nan_sin_excepcion() -> None:
    df = _frame_from_targets(
        targets=[None, None, None],
        months=["2024-03-01", "2024-03-02", "2024-03-03"],
    )

    result = _analyzer(date_col="fecha", min_obs_per_period=1).compute(df, target_col="target")

    assert result.by_period.loc[0, "n_total"] == 3
    assert result.by_period.loc[0, "n_eligible"] == 0
    assert result.by_period.loc[0, "n_bad"] == 0
    assert math.isnan(result.by_period.loc[0, "default_rate"])
    assert math.isnan(result.overall_rate)
    assert bool(result.by_period.loc[0, "low_confidence"])


def test_axis_period_infiere_unica_columna_datetime() -> None:
    df = _frame_from_targets([1, 0], ["2024-01-01", "2024-02-01"]).rename(
        columns={"fecha": "observation_date"}
    )

    result = _analyzer(date_col=None).compute(df, target_col="target")

    assert result.by_period["period"].tolist() == [
        pd.Period("2024-01", freq="M"),
        pd.Period("2024-02", freq="M"),
    ]


def test_axis_period_soporta_datetime_con_timezone_sin_warning() -> None:
    index = pd.Index(["op-1", "op-2"], name="loan_id")
    df = pd.DataFrame(
        {
            "fecha": pd.Series(
                pd.to_datetime(["2024-01-01 08:00", "2024-01-02 09:00"], utc=True),
                index=index,
            ),
            "target": pd.Series([1, 0], index=index, dtype="Int8"),
        },
        index=index,
    )

    result = _analyzer(date_col="fecha").compute(df, target_col="target")

    assert result.by_period.loc[0, "period"] == pd.Period("2024-01", freq="M")
    assert result.by_period.loc[0, "default_rate"] == pytest.approx(0.5)


def test_axis_cohort_agrupa_por_columna_configurada() -> None:
    index = pd.Index(["op-1", "op-2", "op-3", "op-4", "op-5"], name="loan_id")
    df = pd.DataFrame(
        {
            "cohort": ["2024Q2", "2024Q1", "2024Q1", "2024Q2", "2024Q2"],
            "target": pd.Series([1, 0, pd.NA, 0, 0], index=index, dtype="Int8"),
        },
        index=index,
    )

    result = _analyzer(axis="cohort", cohort_col="cohort", min_obs_per_period=3).compute(
        df, target_col="target"
    )

    assert result.axis == "cohort"
    assert result.by_period["period"].tolist() == ["2024Q1", "2024Q2"]
    assert result.by_period["n_total"].tolist() == [2, 3]
    assert result.by_period["n_eligible"].tolist() == [1, 3]
    assert result.by_period["n_bad"].tolist() == [0, 1]
    assert result.by_period["low_confidence"].tolist() == [True, False]
    assert result.overall_rate == pytest.approx(1 / 4)


def test_axis_cohort_con_tipos_mixtos_es_invariante_a_reordenar_filas() -> None:
    index = pd.Index(["op-1", "op-2", "op-3", "op-4"], name="loan_id")
    df = pd.DataFrame(
        {
            "cohort": pd.Series([2024, "2024", 2024, "2024"], index=index, dtype="object"),
            "target": pd.Series([1, 0, 0, 0], index=index, dtype="Int8"),
        },
        index=index,
    )
    reordered = df.loc[["op-2", "op-1", "op-4", "op-3"]]
    analyzer = _analyzer(axis="cohort", cohort_col="cohort", min_obs_per_period=1)

    base = analyzer.compute(df, target_col="target")
    permuted = analyzer.compute(reordered, target_col="target")

    assert base.by_period["period"].tolist() == [2024, "2024"]
    assert base.by_period["default_rate"].tolist() == [pytest.approx(0.5), pytest.approx(0.0)]
    assert_frame_equal(base.by_period, permuted.by_period)
    assert base.overall_rate == pytest.approx(permuted.overall_rate)


def test_axis_cohort_no_colapsa_int_y_float_iguales_al_permutar() -> None:
    index = pd.Index(["op-int", "op-float"], name="loan_id")
    df = pd.DataFrame(
        {
            "cohort": pd.Series([2024, 2024.0], index=index, dtype="object"),
            "target": pd.Series([1, 0], index=index, dtype="Int8"),
        },
        index=index,
    )
    reordered = df.loc[["op-float", "op-int"]]
    analyzer = _analyzer(axis="cohort", cohort_col="cohort", min_obs_per_period=1)

    base = analyzer.compute(df, target_col="target")
    permuted = analyzer.compute(reordered, target_col="target")

    assert base.by_period["period"].tolist() == [2024.0, 2024]
    assert base.by_period["default_rate"].tolist() == [pytest.approx(0.0), pytest.approx(1.0)]
    assert_frame_equal(base.by_period, permuted.by_period)
    assert base.overall_rate == pytest.approx(permuted.overall_rate)


def test_axis_cohort_no_colapsa_int_y_bool_iguales_al_permutar() -> None:
    index = pd.Index(["op-int", "op-bool"], name="loan_id")
    df = pd.DataFrame(
        {
            "cohort": pd.Series([1, True], index=index, dtype="object"),
            "target": pd.Series([1, 0], index=index, dtype="Int8"),
        },
        index=index,
    )
    reordered = df.loc[["op-bool", "op-int"]]
    analyzer = _analyzer(axis="cohort", cohort_col="cohort", min_obs_per_period=1)

    base = analyzer.compute(df, target_col="target")
    permuted = analyzer.compute(reordered, target_col="target")

    assert base.by_period["period"].tolist() == [True, 1]
    assert base.by_period["default_rate"].tolist() == [pytest.approx(0.0), pytest.approx(1.0)]
    assert_frame_equal(base.by_period, permuted.by_period)
    assert base.overall_rate == pytest.approx(permuted.overall_rate)


def test_axis_cohort_faltante_tiene_representante_visible_determinista() -> None:
    index = pd.Index(["op-1", "op-2"], name="loan_id")
    df = pd.DataFrame(
        {
            "cohort": pd.Series([None, None], index=index, dtype="object"),
            "target": pd.Series([1, 0], index=index, dtype="Int8"),
        },
        index=index,
    )

    result = _analyzer(axis="cohort", cohort_col="cohort", min_obs_per_period=1).compute(
        df, target_col="target"
    )

    assert result.by_period["period"].isna().tolist() == [True]
    assert result.by_period.loc[0, "default_rate"] == pytest.approx(0.5)


def test_orden_cohort_trata_etiquetas_faltantes_de_forma_estable() -> None:
    assert _stable_label(None) == ""
    assert _stable_label(float("nan")) == ""
    assert _stable_label(2024) != _stable_label("2024")


@pytest.mark.parametrize(
    ("frame", "config", "match"),
    [
        (
            pd.DataFrame({"target": pd.Series([1, 0], dtype="Int8")}),
            DefaultRateConfig(date_col=None),
            "requiere una columna de fecha",
        ),
        (
            pd.DataFrame(
                {
                    "fecha_1": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                    "fecha_2": pd.to_datetime(["2024-02-01", "2024-02-02"]),
                    "target": pd.Series([1, 0], dtype="Int8"),
                }
            ),
            DefaultRateConfig(date_col=None),
            "más de una columna datetime",
        ),
        (
            pd.DataFrame({"fecha": pd.to_datetime(["2024-01-01"]), "target": [1]}),
            DefaultRateConfig(date_col="fecha_inexistente"),
            "columna de fecha inexistente",
        ),
        (
            pd.DataFrame({"fecha": ["2024-01-01"], "target": [1]}),
            DefaultRateConfig(date_col="fecha"),
            "requiere una columna datetime",
        ),
        (
            pd.DataFrame({"fecha": pd.to_datetime(["2024-01-01"])}),
            DefaultRateConfig(date_col="fecha"),
            "columna target existente",
        ),
        (
            pd.DataFrame(
                {"fecha": pd.Series(dtype="datetime64[ns]"), "target": pd.Series(dtype="Int8")}
            ),
            DefaultRateConfig(date_col="fecha"),
            "no tiene filas",
        ),
        (
            pd.DataFrame({"cohort": ["2024Q1"], "target": [1]}),
            DefaultRateConfig(axis="cohort", cohort_col=None),
            "requiere declarar",
        ),
        (
            pd.DataFrame({"cohort": ["2024Q1"], "target": [1]}),
            DefaultRateConfig(axis="cohort", cohort_col="vintage"),
            "columna inexistente",
        ),
    ],
)
def test_errores_de_contrato_son_edaerror_en_espanol(
    frame: pd.DataFrame, config: DefaultRateConfig, match: str
) -> None:
    with pytest.raises(EdaError, match=match):
        DefaultRateAnalyzer(config).compute(frame, target_col="target")


def test_resultado_es_inmutable_a_nivel_de_campos() -> None:
    df = _frame_from_targets([1, 0], ["2024-01-01", "2024-01-02"])
    result = _analyzer(date_col="fecha").compute(df, target_col="target")

    with pytest.raises(ValidationError):
        result.overall_rate = 0.99


@st.composite
def _default_rate_frames(draw: st.DrawFn) -> pd.DataFrame:
    n_rows = draw(st.integers(min_value=1, max_value=40))
    month_offsets = draw(
        st.lists(st.integers(min_value=0, max_value=5), min_size=n_rows, max_size=n_rows)
    )
    targets = draw(
        st.lists(
            st.one_of(st.integers(min_value=0, max_value=1), st.none()),
            min_size=n_rows,
            max_size=n_rows,
        )
    )
    index = pd.Index([f"op-{position:03d}" for position in range(n_rows)], name="loan_id")
    dates = [pd.Timestamp("2024-01-15") + pd.DateOffset(months=offset) for offset in month_offsets]
    target_values = [pd.NA if value is None else value for value in targets]
    return pd.DataFrame(
        {
            "fecha": pd.Series(dates, index=index, dtype="datetime64[ns]"),
            "target": pd.Series(target_values, index=index, dtype="Int8"),
        },
        index=index,
    )


@settings(max_examples=40, deadline=None)
@given(frame=_default_rate_frames())
def test_hypothesis_tasas_en_rango_e_invariante_a_reordenar(frame: pd.DataFrame) -> None:
    analyzer = _analyzer(date_col="fecha", min_obs_per_period=1)

    base = analyzer.compute(frame, target_col="target")
    reordered = analyzer.compute(frame.sample(frac=1.0, random_state=20240626), target_col="target")

    rates = base.by_period.loc[base.by_period["n_eligible"] > 0, "default_rate"]
    assert rates.between(0.0, 1.0).all()
    assert_frame_equal(base.by_period, reordered.by_period)
    if math.isnan(base.overall_rate):
        assert math.isnan(reordered.overall_rate)
    else:
        assert base.overall_rate == pytest.approx(reordered.overall_rate)
