"""Validación declarativa de esquemas tabulares para la capa ``data`` (SDD-02 §4/§7).

``SchemaValidator`` traduce :class:`~nikodym.data.config.SchemaConfig` a un esquema pandera y
valida ``pandas.DataFrame`` con ``lazy=True`` para acumular todos los incumplimientos en un único
``DataValidationError`` de Nikodym.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Any, Final

import pandas as pd
import pandera.pandas as pa

from nikodym.core.audit import AuditSink
from nikodym.core.exceptions import DataValidationError
from nikodym.data.config import ColumnSpec, SchemaConfig

__all__ = ["SchemaValidator"]

_PANDERA_DTYPES: Final[dict[str, str]] = {
    "int": "int64",
    "float": "float64",
    "str": "str",
    "bool": "bool",
    "category": "category",
    "datetime": "datetime64[ns]",
}


class SchemaValidator:
    """Valida columnas, tipos y reglas simples mediante pandera.

    ``index_col`` se interpreta como el nombre del índice pandas ya existente: el validador no
    ejecuta ``set_index`` ni consume una columna ordinaria con ese nombre. Si el identificador vive
    como columna, debe declararse como ``ColumnSpec`` o en ``unique_keys``; si vive en el índice,
    ``index_col`` exige que el índice tenga ese nombre y sea único.
    """

    def __init__(self, config: SchemaConfig | None = None) -> None:
        """Construye el validador con las reglas declarativas de ``SchemaConfig``."""
        self.config = config or SchemaConfig()

    @classmethod
    def from_config(cls, cfg: SchemaConfig) -> SchemaValidator:
        """Construye un validador desde ``DataConfig.schema_`` / ``SchemaConfig``."""
        return cls(cfg)

    def build_schema(self) -> pa.DataFrameSchema:
        """Traduce ``SchemaConfig`` al contrato imperativo de pandera.

        Returns
        -------
        pandera.pandas.DataFrameSchema
            Esquema listo para validar un ``DataFrame`` con backend pandas. El mapeo de tipos
            lógico→pandera es explícito: ``int``→``int64``, ``float``→``float64``, ``str``→``str``,
            ``bool``→``bool``, ``category``→``category`` y ``datetime``→``datetime64[ns]``.
        """
        columns: dict[str, Any] = {}
        for spec in self.config.columns:
            columns[spec.name] = pa.Column(
                _dtype_for(spec),
                checks=_checks_for(spec),
                nullable=spec.nullable,
                coerce=spec.coerce,
                required=spec.required,
                unique=spec.unique,
            )

        return pa.DataFrameSchema(
            columns,
            strict=self.config.strict,
            ordered=self.config.ordered,
            unique=list(self.config.unique_keys) if self.config.unique_keys is not None else None,
            index=self._build_index(),
        )

    def validate(self, df: pd.DataFrame, *, audit: AuditSink | None = None) -> pd.DataFrame:
        """Valida ``df`` y devuelve el ``DataFrame`` resultante de pandera.

        Parameters
        ----------
        df : pandas.DataFrame
            Dataset a validar. No se muta in-place; si ``coerce=True`` pandera devuelve una copia
            con los tipos coaccionados.
        audit : AuditSink or None
            Reservado para la orquestación de ``DataStep``; la validación de esquema no emite
            decisiones todavía.

        Returns
        -------
        pandas.DataFrame
            ``DataFrame`` validado, posiblemente coaccionado según ``ColumnSpec.coerce``.

        Raises
        ------
        DataValidationError
            Si pandera detecta incumplimientos. El mensaje agrega todos los fallos de
            ``failure_cases`` en español, con columna, check, valor ofensor e índice.
        """
        del audit
        try:
            return self.build_schema().validate(df, lazy=True)
        except pa.errors.SchemaErrors as exc:
            raise DataValidationError(_format_schema_errors(exc)) from exc

    def _build_index(self) -> Any | None:
        """Construye el índice pandera si ``index_col`` está declarado."""
        if self.config.index_col is None:
            return None
        return pa.Index(name=self.config.index_col, unique=True)


def _dtype_for(spec: ColumnSpec) -> str:
    """Devuelve el dtype pandera asociado al dtype lógico de una columna."""
    return _PANDERA_DTYPES[spec.dtype]


def _checks_for(spec: ColumnSpec) -> list[Any]:
    """Construye los checks pandera derivados de cotas e inclusión declaradas."""
    checks: list[Any] = []
    if spec.ge is not None and spec.le is not None:
        checks.append(pa.Check.in_range(spec.ge, spec.le))
    elif spec.ge is not None:
        checks.append(pa.Check.ge(spec.ge))
    elif spec.le is not None:
        checks.append(pa.Check.le(spec.le))

    if spec.isin is not None:
        checks.append(pa.Check.isin(list(spec.isin)))
    return checks


def _format_schema_errors(exc: pa.errors.SchemaErrors) -> str:
    """Convierte ``failure_cases`` de pandera en un reporte accionable en español."""
    failure_cases = exc.failure_cases
    count = len(failure_cases.index)
    header = (
        "El DataFrame no cumple el esquema declarado. "
        f"Se detectaron {count} fallo(s) con validación lazy=True:"
    )
    rows = [_format_failure_row(row) for row in failure_cases.to_dict(orient="records")]
    return "\n".join([header, *rows])


def _format_failure_row(row: dict[Any, Any]) -> str:
    """Formatea una fila de ``failure_cases`` con columna/check/valor/índice."""
    column = _column_label(row)
    check = _format_value(row.get("check"))
    failure_case = _format_value(row.get("failure_case"))
    index = _format_value(row.get("index"))
    return f"- columna: {column}; check: {check}; valor ofensor: {failure_case}; índice: {index}"


def _column_label(row: dict[Any, Any]) -> str:
    """Obtiene una columna legible incluso para fallos de esquema a nivel DataFrame."""
    column = row.get("column")
    if not _is_missing(column):
        return _format_value(column)

    failure_case = row.get("failure_case")
    if not _is_missing(failure_case):
        return _format_value(failure_case)

    schema_context = row.get("schema_context")
    if not _is_missing(schema_context):
        return _format_value(schema_context)
    return "<dataframe>"


def _format_value(value: Any) -> str:
    """Normaliza valores de pandera/pandas a texto estable para el reporte."""
    if _is_missing(value):
        return "<sin valor>"
    return str(value)


def _is_missing(value: Any) -> bool:
    """Detecta escalares nulos sin romper con listas/arrays devueltos por pandera."""
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(result, bool):
        return result
    return False
