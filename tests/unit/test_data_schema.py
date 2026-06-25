"""Tests de ``SchemaValidator`` (SDD-02 §4/§7): pandera, errores lazy y coerción."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from nikodym.core.exceptions import DataValidationError
from nikodym.data import schema as schema_module
from nikodym.data.config import ColumnSpec, SchemaConfig
from nikodym.data.schema import SchemaValidator


def _cfg(*columns: ColumnSpec, **kwargs: object) -> SchemaConfig:
    return SchemaConfig(columns=columns, **kwargs)


def test_from_config_y_config_default() -> None:
    cfg = SchemaConfig()

    validator = SchemaValidator.from_config(cfg)

    assert validator.config is cfg
    assert SchemaValidator().config == SchemaConfig()


def test_build_schema_produce_contrato_pandera_esperado() -> None:
    cfg = _cfg(
        ColumnSpec(name="loan_id", dtype="str", nullable=False, coerce=True, unique=True),
        ColumnSpec(name="edad", dtype="int", ge=18),
        ColumnSpec(name="saldo", dtype="float", le=1_000),
        ColumnSpec(name="estado", dtype="category", isin=("vigente", "castigado")),
        ColumnSpec(name="fecha", dtype="datetime"),
        ColumnSpec(name="activo", dtype="bool"),
        ColumnSpec(name="score", dtype="float", ge=0, le=1),
        strict=True,
        ordered=True,
        unique_keys=("loan_id", "fecha"),
        index_col="loan_id",
    )

    schema = SchemaValidator(cfg).build_schema()

    assert schema.strict is True
    assert schema.ordered is True
    assert schema.unique == ["loan_id", "fecha"]
    assert schema.index.name == "loan_id"
    assert schema.index.unique is True
    assert {name: str(column.dtype) for name, column in schema.columns.items()} == {
        "loan_id": "str",
        "edad": "int64",
        "saldo": "float64",
        "estado": "category",
        "fecha": "datetime64[ns]",
        "activo": "bool",
        "score": "float64",
    }

    loan_id = schema.columns["loan_id"]
    assert loan_id.nullable is False
    assert loan_id.coerce is True
    assert loan_id.required is True
    assert loan_id.unique is True
    assert [check.name for check in schema.columns["edad"].checks] == ["greater_than_or_equal_to"]
    assert [check.name for check in schema.columns["saldo"].checks] == ["less_than_or_equal_to"]
    assert [check.name for check in schema.columns["estado"].checks] == ["isin"]
    assert [check.name for check in schema.columns["score"].checks] == ["in_range"]


def test_todos_los_dtypes_logicos_validan_con_pandera_real() -> None:
    df = pd.DataFrame(
        {
            "entero": pd.Series([1, 2], dtype="int64"),
            "monto": pd.Series([10.5, 20.0], dtype="float64"),
            "texto": ["A", "B"],
            "flag": [True, False],
            "segmento": pd.Series(["retail", "pyme"], dtype="category"),
            "fecha": pd.to_datetime(["2024-01-01", "2024-02-01"]),
        }
    )
    validator = SchemaValidator(
        _cfg(
            ColumnSpec(name="entero", dtype="int"),
            ColumnSpec(name="monto", dtype="float"),
            ColumnSpec(name="texto", dtype="str"),
            ColumnSpec(name="flag", dtype="bool"),
            ColumnSpec(name="segmento", dtype="category"),
            ColumnSpec(name="fecha", dtype="datetime"),
        )
    )

    validated = validator.validate(df)

    assert_frame_equal(validated, df)


def test_canonico_lazy_agrega_columna_faltante_tipo_y_rango() -> None:
    validator = SchemaValidator(
        _cfg(
            ColumnSpec(name="columna_faltante", dtype="int"),
            ColumnSpec(name="edad", dtype="int"),
            ColumnSpec(name="saldo", dtype="float", ge=0, le=100),
        )
    )
    df = pd.DataFrame({"edad": ["no-num"], "saldo": [999.0]})

    with pytest.raises(DataValidationError) as exc_info:
        validator.validate(df)

    message = str(exc_info.value)
    assert "Se detectaron 3 fallo(s)" in message
    assert message.count("- columna:") == 3
    assert "columna_faltante" in message
    assert "column_in_dataframe" in message
    assert "edad" in message
    assert "dtype('int64')" in message
    assert "no-num" in message
    assert "saldo" in message
    assert "in_range" in message
    assert "999.0" in message


def test_nullable_false_rechaza_nulos_y_nullable_true_los_admite() -> None:
    df = pd.DataFrame({"segmento": ["retail", None]})
    nullable_false = SchemaValidator(_cfg(ColumnSpec(name="segmento", dtype="str", nullable=False)))
    nullable_true = SchemaValidator(_cfg(ColumnSpec(name="segmento", dtype="str", nullable=True)))

    with pytest.raises(DataValidationError) as exc_info:
        nullable_false.validate(df)

    assert "segmento" in str(exc_info.value)
    assert "not_nullable" in str(exc_info.value)
    assert_frame_equal(nullable_true.validate(df), df)


def test_unique_de_columna_y_unique_keys_rechazan_duplicados() -> None:
    duplicated_column = pd.DataFrame({"loan_id": ["A", "A"]})
    duplicated_rows = pd.DataFrame(
        {"cliente_id": ["C1", "C1"], "mes": ["2024-01", "2024-01"], "saldo": [10.0, 20.0]}
    )

    with pytest.raises(DataValidationError) as column_exc:
        SchemaValidator(_cfg(ColumnSpec(name="loan_id", dtype="str", unique=True))).validate(
            duplicated_column
        )

    with pytest.raises(DataValidationError) as keys_exc:
        SchemaValidator(
            _cfg(
                ColumnSpec(name="cliente_id", dtype="str"),
                ColumnSpec(name="mes", dtype="str"),
                ColumnSpec(name="saldo", dtype="float"),
                unique_keys=("cliente_id", "mes"),
            )
        ).validate(duplicated_rows)

    assert "field_uniqueness" in str(column_exc.value)
    assert "multiple_fields_uniqueness" in str(keys_exc.value)
    assert "cliente_id" in str(keys_exc.value)
    assert "mes" in str(keys_exc.value)


@pytest.mark.parametrize(
    ("spec", "valid_value", "invalid_value", "check_name"),
    [
        (
            ColumnSpec(name="estado", dtype="str", isin=("vigente", "mora")),
            "vigente",
            "otro",
            "isin",
        ),
        (ColumnSpec(name="edad", dtype="int", ge=18), 18, 17, "greater_than_or_equal_to"),
        (ColumnSpec(name="saldo", dtype="float", le=100), 100.0, 101.0, "less_than_or_equal_to"),
        (ColumnSpec(name="score", dtype="float", ge=0, le=1), 0.5, -0.1, "in_range"),
    ],
)
def test_checks_isin_ge_le_e_in_range_aceptan_y_rechazan(
    spec: ColumnSpec, valid_value: object, invalid_value: object, check_name: str
) -> None:
    validator = SchemaValidator(_cfg(spec))

    valid = pd.DataFrame({spec.name: [valid_value]})
    invalid = pd.DataFrame({spec.name: [invalid_value]})

    assert_frame_equal(validator.validate(valid), valid)
    with pytest.raises(DataValidationError) as exc_info:
        validator.validate(invalid)

    assert spec.name in str(exc_info.value)
    assert check_name in str(exc_info.value)
    assert str(invalid_value) in str(exc_info.value)


def test_strict_true_filter_y_false_manejan_columnas_extra() -> None:
    df = pd.DataFrame({"saldo": [100.0], "extra": ["no-declarada"]})
    spec = ColumnSpec(name="saldo", dtype="float")

    with pytest.raises(DataValidationError) as strict_exc:
        SchemaValidator(_cfg(spec, strict=True)).validate(df)

    filtered = SchemaValidator(_cfg(spec, strict="filter")).validate(df)
    allowed = SchemaValidator(_cfg(spec, strict=False)).validate(df)

    assert "column_in_schema" in str(strict_exc.value)
    assert "extra" in str(strict_exc.value)
    assert filtered.to_dict(orient="list") == {"saldo": [100.0]}
    assert_frame_equal(allowed, df)


def test_ordered_valida_el_orden_de_columnas() -> None:
    validator = SchemaValidator(
        _cfg(ColumnSpec(name="a", dtype="int"), ColumnSpec(name="b", dtype="int"), ordered=True)
    )

    with pytest.raises(DataValidationError) as exc_info:
        validator.validate(pd.DataFrame({"b": [1], "a": [2]}))

    message = str(exc_info.value)
    assert "column_ordered" in message
    assert "a" in message
    assert "b" in message


def test_required_false_permite_columna_ausente_y_coerce_no_muta_df_original() -> None:
    original = pd.DataFrame({"saldo": ["10", "20"]})
    validator = SchemaValidator(
        _cfg(
            ColumnSpec(name="saldo", dtype="int", coerce=True),
            ColumnSpec(name="comentario", dtype="str", required=False),
            strict=True,
        )
    )

    validated = validator.validate(original)

    assert validated.to_dict(orient="list") == {"saldo": [10, 20]}
    assert str(validated["saldo"].dtype) == "int64"
    assert original.to_dict(orient="list") == {"saldo": ["10", "20"]}
    assert str(original["saldo"].dtype) == "object"


def test_index_col_valida_indice_pandas_existente_y_no_una_columna_ordinaria() -> None:
    validator = SchemaValidator(_cfg(ColumnSpec(name="saldo", dtype="float"), index_col="loan_id"))
    con_indice = pd.DataFrame({"saldo": [10.0, 20.0]}, index=pd.Index(["A", "B"], name="loan_id"))
    con_columna = pd.DataFrame({"loan_id": ["A", "B"], "saldo": [10.0, 20.0]})
    indice_duplicado = pd.DataFrame(
        {"saldo": [10.0, 20.0]}, index=pd.Index(["A", "A"], name="loan_id")
    )

    assert_frame_equal(validator.validate(con_indice), con_indice)
    with pytest.raises(DataValidationError) as column_exc:
        validator.validate(con_columna)
    with pytest.raises(DataValidationError) as duplicated_exc:
        validator.validate(indice_duplicado)

    assert "field_name('loan_id')" in str(column_exc.value)
    assert "field_uniqueness" in str(duplicated_exc.value)
    assert "loan_id" in str(duplicated_exc.value)


def test_datavalidationerror_tiene_reporte_en_espanol_con_columna_check_y_valor() -> None:
    validator = SchemaValidator(_cfg(ColumnSpec(name="score", dtype="float", ge=0, le=1)))

    with pytest.raises(DataValidationError) as exc_info:
        validator.validate(pd.DataFrame({"score": [2.5]}))

    message = str(exc_info.value)
    assert "El DataFrame no cumple el esquema declarado" in message
    assert "columna: score" in message
    assert "check: in_range" in message
    assert "valor ofensor: 2.5" in message
    assert "índice: 0" in message


def test_helpers_de_reporte_cubren_fallbacks_defensivos() -> None:
    class BadArray:
        """Objeto mínimo para forzar el camino defensivo de ``pd.isna``."""

        def __array__(self, dtype: object = None) -> object:
            raise TypeError("isna no disponible")

    assert (
        schema_module._format_failure_row({"schema_context": "DataFrameSchema"})
        == "- columna: DataFrameSchema; check: <sin valor>; valor ofensor: <sin valor>; "
        "índice: <sin valor>"
    )
    assert (
        schema_module._format_failure_row({})
        == "- columna: <dataframe>; check: <sin valor>; valor ofensor: <sin valor>; "
        "índice: <sin valor>"
    )
    assert schema_module._format_value([1]) == "[1]"
    assert schema_module._is_missing(BadArray()) is False
