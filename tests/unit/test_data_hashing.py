"""Tests de ``data_hash`` (SDD-02 D-DATA-2): contenido lógico por bloques."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from nikodym.core.exceptions import DataValidationError
from nikodym.data.hashing import data_hash

GOLDEN_DATA_HASH = "9c5118ad5b593e577783c64f5268b5ae7d755e799353099f30e0498e8ea19f68"
GOLDEN_CATEGORY_DATA_HASH = "65191931e5ccb9956156e85d7ffff3ec6989b0e8e702884831a39059a37468cc"


def _canonical_frame() -> pd.DataFrame:
    idx = pd.Index(["op-003", "op-001", "op-002"], name="loan_id")
    return pd.DataFrame(
        {
            "dias_mora": [0, 90, 30],
            "saldo": [1000.25, 250.0, 0.0],
            "vigente": [True, False, True],
            "segmento": ["retail", "pyme", "retail"],
        },
        index=idx,
    ).astype(
        {
            "dias_mora": "int64",
            "saldo": "float64",
            "vigente": "bool",
            "segmento": "object",
        }
    )


def _categorical_frame() -> pd.DataFrame:
    idx = pd.Index(["op-001", "op-002", "op-003", "op-004"], name="loan_id")
    return pd.DataFrame(
        {
            "dias_mora": [0, 15, 90, 30],
            "segmento": pd.Categorical(
                ["retail", "pyme", "retail", "empresa"],
                categories=["empresa", "pyme", "retail"],
                ordered=False,
            ),
        },
        index=idx,
    ).astype({"dias_mora": "int64"})


def test_data_hash_golden_value_pineado_a_pandas_de_uv_lock() -> None:
    # Golden calculado con pandas 2.3.3, versión pineada en uv.lock para este entorno.
    result = data_hash(_canonical_frame())

    assert result == GOLDEN_DATA_HASH
    assert len(result) == 64
    assert int(result, 16) > 0


def test_data_hash_es_determinista_en_llamadas_y_copias_independientes() -> None:
    df = _canonical_frame()

    assert data_hash(df) == data_hash(df)
    assert data_hash(df) == data_hash(df.copy(deep=True))


def test_data_hash_rechaza_indice_duplicado_con_mensaje_especifico() -> None:
    idx = pd.Index(["op-001", "op-001", "op-002"], name="loan_id")
    df = pd.DataFrame({"saldo": [100.0, 200.0, 300.0]}, index=idx, dtype="float64")

    with pytest.raises(DataValidationError) as exc_info:
        data_hash(df)

    message = str(exc_info.value).lower()
    assert "índice" in message
    assert "duplicad" in message
    assert "1 etiqueta" in message


def test_data_hash_category_es_reproducible_y_tiene_golden() -> None:
    df = _categorical_frame()
    distinto_orden_categorias = _categorical_frame()
    distinto_orden_categorias["segmento"] = distinto_orden_categorias[
        "segmento"
    ].cat.reorder_categories(["retail", "pyme", "empresa"], ordered=False)

    result = data_hash(df)

    assert isinstance(df["segmento"].dtype, pd.CategoricalDtype)
    assert result == data_hash(df)
    assert result == data_hash(df.copy(deep=True))
    # Esperado: pandas hashea ``category`` por contenido lógico con ``categorize=True``; cambiar
    # el orden declarado de ``categories`` no debe mover el ancla ni el golden.
    assert result == data_hash(distinto_orden_categorias)
    assert result == GOLDEN_CATEGORY_DATA_HASH


def test_data_hash_es_invariante_al_orden_de_columnas() -> None:
    df = _canonical_frame()
    permutado = df[["segmento", "vigente", "saldo", "dias_mora"]]

    assert data_hash(df) == data_hash(permutado)


def test_data_hash_es_invariante_a_permutacion_de_filas_con_mismo_indice() -> None:
    df = _canonical_frame()
    permutado = df.iloc[[2, 0, 1]]

    assert data_hash(df) == data_hash(permutado)


def test_data_hash_es_invariante_al_tamano_de_bloque() -> None:
    df = _canonical_frame()

    assert data_hash(df) == data_hash(df, block_size=1)
    assert data_hash(df) == data_hash(df, block_size=2)


def test_data_hash_cambia_si_cambia_valor_indice_o_dtype() -> None:
    df = _canonical_frame()

    otro_valor = df.copy(deep=True)
    otro_valor.loc["op-001", "saldo"] = 251.0

    otro_indice = df.rename(index={"op-001": "op-999"})

    otro_dtype = df.copy(deep=True)
    otro_dtype["dias_mora"] = otro_dtype["dias_mora"].astype("float64")

    original_hash = data_hash(df)
    assert data_hash(otro_valor) != original_hash
    assert data_hash(otro_indice) != original_hash
    assert data_hash(otro_dtype) != original_hash


def test_data_hash_normaliza_menos_cero_float_a_cero() -> None:
    idx = pd.Index(["a", "b"], name="id")
    con_menos_cero = pd.DataFrame({"saldo": [-0.0, 10.0]}, index=idx, dtype="float64")
    con_cero = pd.DataFrame({"saldo": [0.0, 10.0]}, index=idx, dtype="float64")

    assert data_hash(con_menos_cero) == data_hash(con_cero)


def test_data_hash_no_muta_el_dataframe_de_entrada() -> None:
    df = _canonical_frame()
    original = df.copy(deep=True)

    data_hash(df, block_size=1)

    assert_frame_equal(df, original)


def test_data_hash_dataframe_vacio_es_determinista() -> None:
    df = pd.DataFrame(
        {
            "dias_mora": pd.Series(dtype="int64"),
            "saldo": pd.Series(dtype="float64"),
        },
        index=pd.Index([], name="loan_id"),
    )

    assert data_hash(df) == data_hash(df.copy(deep=True))
    assert len(data_hash(df)) == 64


def test_data_hash_rechaza_block_size_invalido() -> None:
    with pytest.raises(ValueError, match="block_size debe ser mayor o igual a 1"):
        data_hash(_canonical_frame(), block_size=0)


def test_data_hash_con_nan_es_determinista_y_distinto_de_sin_nan() -> None:
    idx = pd.Index(["a", "b"], name="id")
    con_nan = pd.DataFrame({"saldo": [1.0, float("nan")]}, index=idx, dtype="float64")
    sin_nan = pd.DataFrame({"saldo": [1.0, 0.0]}, index=idx, dtype="float64")

    assert data_hash(con_nan) == data_hash(con_nan.copy(deep=True))
    assert data_hash(con_nan) != data_hash(sin_nan)
