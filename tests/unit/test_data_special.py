"""Tests de ``SpecialValuePolicy`` (SDD-02 §4/§7): centinelas, máscara y auditoría."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import DataValidationError
from nikodym.data.config import MissingConfig, SpecialValueSpec
from nikodym.data.special import MaskedFrame, SpecialValuePolicy


def _spec(
    columns: tuple[str, ...] | str = "*",
    sentinels: tuple[float | str, ...] = (-99999.0,),
    label: str = "special",
) -> SpecialValueSpec:
    return SpecialValueSpec(columns=columns, sentinels=sentinels, label=label)


def test_from_config_conserva_missing_config() -> None:
    """``from_config`` construye desde ``DataConfig.missing`` / ``MissingConfig``."""
    cfg = MissingConfig(special_values=(_spec(columns=("saldo",)),))

    policy = SpecialValuePolicy.from_config(cfg)

    assert policy.config is cfg


def test_un_sentinel_normaliza_a_nan_con_mask_y_catalogo_golden() -> None:
    """Un centinela declarado se reemplaza por ``NaN`` sin confundir missing genuino."""
    df = pd.DataFrame(
        {"saldo": [100.0, -99999.0, math.nan, 50.0], "segmento": ["A", "B", "C", "D"]},
        index=pd.Index(["op-1", "op-2", "op-3", "op-4"], name="loan_id"),
    )
    original = df.copy(deep=True)
    policy = SpecialValuePolicy(
        MissingConfig(special_values=(_spec(columns=("saldo",), sentinels=(-99999.0,)),))
    )

    masked = policy.apply(df)

    assert isinstance(masked, MaskedFrame)
    assert masked.special_catalog == {"saldo": [-99999.0]}
    assert masked.frame["saldo"].isna().tolist() == [False, True, True, False]
    assert masked.frame.loc["op-1", "saldo"] == 100.0
    assert masked.frame.loc["op-4", "saldo"] == 50.0
    assert masked.special_mask.to_dict(orient="list") == {
        "saldo": [False, True, False, False],
        "segmento": [False, False, False, False],
    }
    assert_frame_equal(df, original)


def test_multiples_specs_y_sentinels_con_catalogo_determinista_sin_duplicados() -> None:
    """El catálogo sigue el orden de declaración y elimina duplicados por columna."""
    df = pd.DataFrame(
        {
            "dias_mora": [0, 9999, -1, 30],
            "segmento": ["SIN_DATO", "NO_APLICA", "SIN_DATO", "retail"],
        },
        index=pd.Index(["a", "b", "c", "d"], name="loan_id"),
    )
    policy = SpecialValuePolicy(
        MissingConfig(
            special_values=(
                _spec(columns=("dias_mora",), sentinels=(9999.0, -1.0), label="sin_historia"),
                _spec(
                    columns=("segmento",),
                    sentinels=("SIN_DATO", "NO_APLICA", "SIN_DATO"),
                    label="sin_segmento",
                ),
            )
        )
    )

    masked = policy.apply(df)

    assert masked.special_catalog == {
        "dias_mora": [9999.0, -1.0],
        "segmento": ["SIN_DATO", "NO_APLICA"],
    }
    assert masked.special_mask.to_dict(orient="list") == {
        "dias_mora": [False, True, True, False],
        "segmento": [True, True, True, False],
    }
    assert masked.frame.isna().sum().to_dict() == {"dias_mora": 2, "segmento": 3}


def test_columns_asterisco_y_lista_respetan_orden_de_columnas_y_specs() -> None:
    """``columns='*'`` recorre todas las columnas y las listas explícitas acotan el alcance."""
    df = pd.DataFrame(
        {
            "a": [-1, 1],
            "b": ["x", "-1"],
            "c": [-1.0, 2.0],
        },
        index=pd.Index(["r1", "r2"], name="id"),
    )
    policy = SpecialValuePolicy(
        MissingConfig(
            special_values=(
                _spec(columns="*", sentinels=(-1.0,), label="no_aplica"),
                _spec(columns=("b",), sentinels=("x",), label="sin_texto"),
            )
        )
    )

    masked = policy.apply(df)

    assert list(masked.special_catalog) == ["a", "c", "b"]
    assert masked.special_catalog == {"a": [-1.0], "c": [-1.0], "b": ["x"]}
    assert masked.special_mask.to_dict(orient="list") == {
        "a": [True, False],
        "b": [True, False],
        "c": [True, False],
    }


def test_dataframe_vacio_preserva_forma_indice_columnas_y_catalogo_vacio() -> None:
    """Un ``DataFrame`` vacío mantiene forma exacta y no inventa catálogo."""
    df = pd.DataFrame(
        {
            "saldo": pd.Series(dtype="float64"),
            "segmento": pd.Series(dtype="object"),
        },
        index=pd.Index([], name="loan_id"),
    )
    policy = SpecialValuePolicy(
        MissingConfig(special_values=(_spec(columns="*", sentinels=(-1.0, "SIN_DATO")),))
    )

    masked = policy.apply(df)

    assert_frame_equal(masked.frame, df)
    assert list(masked.special_mask.index) == []
    assert list(masked.special_mask.columns) == ["saldo", "segmento"]
    assert masked.special_mask.dtypes.astype(str).to_dict() == {
        "saldo": "bool",
        "segmento": "bool",
    }
    assert masked.special_catalog == {}


def test_columna_declarada_inexistente_levanta_datavalidationerror() -> None:
    """Una columna explícita inexistente falla con error propio y mensaje en español."""
    policy = SpecialValuePolicy(
        MissingConfig(special_values=(_spec(columns=("saldo", "mora"), sentinels=(-1.0,)),))
    )

    with pytest.raises(DataValidationError, match=r"columna\(s\) inexistente\(s\).*'mora'"):
        policy.apply(pd.DataFrame({"saldo": [100.0]}))


def test_auditoria_reporta_sentinel_y_missing_rate_superado() -> None:
    """La auditoría emite decisiones por centinela detectado y por missing alto."""
    df = pd.DataFrame({"saldo": [999.0, math.nan, 10.0], "mora": [0, 0, 0]})
    policy = SpecialValuePolicy(
        MissingConfig(
            special_values=(_spec(columns=("saldo",), sentinels=(999.0,)),),
            max_missing_rate=0.5,
        )
    )
    audit = InMemoryAuditSink()

    policy.apply(df, audit=audit)

    assert [event.kind for event in audit.events] == ["decision", "decision"]
    assert audit.events[0].payload == {
        "regla": "special_value",
        "umbral": 999.0,
        "valor": 1,
        "accion": "normalizar_a_nan",
    }
    assert audit.events[1].payload == {
        "regla": "max_missing_rate",
        "umbral": 0.5,
        "valor": {"columna": "saldo", "missing_rate": 2 / 3},
        "accion": "reportar_columna",
    }


def test_dtypes_mixtos_comparan_sin_warning_y_detectan_int_float_object_string_category() -> None:
    """Las comparaciones incompatibles se saltan y las compatibles detectan centinelas."""
    df = pd.DataFrame(
        {
            "int_col": pd.Series([9999, 1, 2], dtype="int64"),
            "float_col": pd.Series([1.5, 9999.0, 2.5], dtype="float64"),
            "object_col": pd.Series([9999.0, "MISSING", None], dtype="object"),
            "string_col": pd.Series(["MISSING", "ok", pd.NA], dtype="string"),
            "category_col": pd.Series(["ok", "MISSING", "ok"], dtype="category"),
            "bool_col": pd.Series([True, False, True], dtype="bool"),
            "date_col": pd.to_datetime(["2024-01-01", "2024-02-01", None]),
        }
    )
    policy = SpecialValuePolicy(
        MissingConfig(
            special_values=(
                _spec(
                    columns="*",
                    sentinels=(9999.0, "MISSING", "AUSENTE", math.nan),
                    label="mixto",
                ),
            )
        )
    )

    masked = policy.apply(df)

    assert masked.special_catalog == {
        "int_col": [9999.0],
        "float_col": [9999.0],
        "object_col": [9999.0, "MISSING"],
        "string_col": ["MISSING"],
        "category_col": ["MISSING"],
    }
    assert masked.special_mask.to_dict(orient="list") == {
        "int_col": [True, False, False],
        "float_col": [False, True, False],
        "object_col": [True, True, False],
        "string_col": [True, False, False],
        "category_col": [False, True, False],
        "bool_col": [False, False, False],
        "date_col": [False, False, False],
    }
    assert masked.frame["bool_col"].tolist() == [True, False, True]
    assert_series_equal(masked.frame["date_col"], df["date_col"])


def test_sentinel_ausente_no_agrega_columna_al_catalogo() -> None:
    """Un centinela declarado pero no observado no produce entrada de catálogo."""
    df = pd.DataFrame({"saldo": [100.0, 200.0], "mora": [0, 30]})
    policy = SpecialValuePolicy(
        MissingConfig(special_values=(_spec(columns=("saldo",), sentinels=(-99999.0,)),))
    )

    masked = policy.apply(df)

    assert masked.special_catalog == {}
    assert not masked.special_mask.to_numpy().any()
    assert_frame_equal(masked.frame, df)
