"""Normalización de valores especiales para la capa ``data`` (SDD-02 §4/§7).

``SpecialValuePolicy`` aplica el catálogo declarativo de
:class:`~nikodym.data.config.MissingConfig`: detecta centinelas por igualdad vectorizada,
los reemplaza por ``NaN`` en una copia defensiva y conserva una máscara/catálogo para que
``binning`` pueda asignarles un bin propio.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeAlias, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.core.audit import AuditEvent, AuditSink
from nikodym.core.exceptions import DataValidationError
from nikodym.data.config import MissingConfig, SpecialValueSpec

__all__ = ["MaskedFrame", "SpecialValuePolicy"]

Sentinel: TypeAlias = float | str


class MaskedFrame(BaseModel):
    """Resultado de normalizar centinelas sin perder su trazabilidad celda a celda."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    frame: pd.DataFrame
    special_mask: pd.DataFrame
    special_catalog: dict[str, list[Sentinel]]


class SpecialValuePolicy:
    """Normaliza centinelas a ``NaN`` y reporta decisiones de missing/special values."""

    def __init__(self, config: MissingConfig) -> None:
        """Construye la política con las reglas declarativas de ``MissingConfig``."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: MissingConfig) -> SpecialValuePolicy:
        """Construye una política desde ``DataConfig.missing`` / ``MissingConfig``."""
        return cls(cfg)

    def apply(self, df: pd.DataFrame, *, audit: AuditSink | None = None) -> MaskedFrame:
        """Normaliza los centinelas declarados en una copia defensiva de ``df``.

        Parameters
        ----------
        df : pandas.DataFrame
            Dataset ya validado por ``SchemaValidator``. No se muta in-place.
        audit : AuditSink or None
            Sumidero opcional para emitir eventos ``decision`` por centinelas detectados y por
            columnas que superan ``max_missing_rate`` tras la normalización.

        Returns
        -------
        MaskedFrame
            Copia normalizada, máscara booleana de celdas especiales y catálogo por columna.

        Raises
        ------
        DataValidationError
            Si una columna declarada en ``SpecialValueSpec.columns`` no existe en ``df``.
        """
        frame = df.copy(deep=True)
        special_mask = pd.DataFrame(False, index=df.index, columns=df.columns, dtype=bool)
        special_catalog: dict[str, list[Sentinel]] = {}
        reported: set[tuple[str, Sentinel]] = set()

        for spec in self.config.special_values:
            for column in _resolve_columns(spec, df):
                for sentinel in spec.sentinels:
                    mask = _sentinel_mask(df[column], sentinel)
                    count = int(mask.sum())
                    if count == 0:
                        continue

                    special_mask[column] = special_mask[column] | mask
                    frame.loc[mask, column] = float("nan")
                    key = (column, sentinel)
                    if key not in reported:
                        _append_catalog(special_catalog, column, sentinel)
                        _log_decision(
                            audit,
                            regla="special_value",
                            umbral=sentinel,
                            valor=count,
                            accion="normalizar_a_nan",
                        )
                        reported.add(key)

        _report_missing_rates(frame, self.config.max_missing_rate, audit)
        return MaskedFrame(
            frame=frame,
            special_mask=special_mask,
            special_catalog=special_catalog,
        )


def _resolve_columns(spec: SpecialValueSpec, df: pd.DataFrame) -> tuple[str, ...]:
    """Resuelve ``columns='*'`` y valida columnas explícitas contra el ``DataFrame``."""
    if spec.columns == "*":
        return cast("tuple[str, ...]", tuple(df.columns))

    missing = [column for column in spec.columns if column not in df.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise DataValidationError(
            "La política de special values declara columna(s) inexistente(s) "
            f"en el DataFrame validado: {joined}."
        )
    return spec.columns


def _sentinel_mask(series: pd.Series, sentinel: Sentinel) -> pd.Series:
    """Construye una máscara booleana para un centinela sin warnings por dtype incompatible."""
    if _is_missing_scalar(sentinel) or not _is_comparable(series, sentinel):
        return _false_mask(series)

    comparison = series.eq(sentinel)
    return comparison.fillna(False).astype("bool")


def _is_comparable(series: pd.Series, sentinel: Sentinel) -> bool:
    """Decide si vale la pena comparar ``series`` contra ``sentinel`` según su dtype."""
    dtype = series.dtype
    if isinstance(sentinel, str):
        return (
            pd.api.types.is_object_dtype(dtype)
            or pd.api.types.is_string_dtype(dtype)
            or _is_categorical_dtype(dtype)
        )

    if pd.api.types.is_bool_dtype(dtype):
        return False
    return (
        pd.api.types.is_numeric_dtype(dtype)
        or pd.api.types.is_object_dtype(dtype)
        or _is_categorical_dtype(dtype)
    )


def _is_categorical_dtype(dtype: object) -> bool:
    """Detecta dtype categórico sin usar helpers de pandas deprecados."""
    return isinstance(dtype, pd.CategoricalDtype)


def _false_mask(series: pd.Series) -> pd.Series:
    """Devuelve una máscara ``False`` con el mismo índice que ``series``."""
    return pd.Series(False, index=series.index, dtype=bool)


def _is_missing_scalar(value: Sentinel) -> bool:
    """Detecta ``NaN``/``NA`` escalar; un centinela nulo nunca se considera special."""
    return bool(pd.isna(value))


def _append_catalog(
    special_catalog: dict[str, list[Sentinel]], column: str, sentinel: Sentinel
) -> None:
    """Agrega un centinela al catálogo de la columna conservando orden y unicidad."""
    special_catalog.setdefault(column, []).append(sentinel)


def _report_missing_rates(
    frame: pd.DataFrame, max_missing_rate: float, audit: AuditSink | None
) -> None:
    """Emitir decisiones para columnas sobre el umbral de missing tras normalizar."""
    if audit is None:
        return

    missing_rates = frame.isna().mean()
    for column, missing_rate in missing_rates.items():
        rate = float(missing_rate)
        if rate > max_missing_rate:
            _log_decision(
                audit,
                regla="max_missing_rate",
                umbral=max_missing_rate,
                valor={"columna": str(column), "missing_rate": rate},
                accion="reportar_columna",
            )


def _log_decision(
    audit: AuditSink | None, *, regla: str, umbral: object, valor: object, accion: str
) -> None:
    """Emitir un evento ``decision`` con la forma del ``AuditableMixin`` de ``core``."""
    if audit is None:
        return

    audit.emit(
        AuditEvent(
            kind="decision",
            step=None,
            payload={"regla": regla, "umbral": umbral, "valor": valor, "accion": accion},
            ts=datetime.now(UTC),
        )
    )
