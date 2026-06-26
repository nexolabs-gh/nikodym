"""Calidad descriptiva de datos para la capa ``eda`` (SDD-27 §3/§4/§7).

``DataQualityProfiler`` calcula una tabla por columna con tipo, tasa de missing, cardinalidad y
flags descriptivos. Es diagnóstico EDA: solo reporta; no elimina columnas ni transforma el
``DataFrame`` para el modelo.

DECISIÓN AUTÓNOMA (frontera, revisión de Cami): el SDD fija que ``near_unique`` representa
``cardinalidad ≈ nº filas``, pero ``QualityConfig`` no tiene umbral propio. Hasta revisión, se usa
el umbral existente ``near_constant_threshold`` sobre los valores no nulos:
``cardinality / n_no_nulos >= near_constant_threshold``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.core.audit import AuditSink
from nikodym.eda.config import QualityConfig
from nikodym.eda.default_rate import _validate_non_empty_frame, _validate_unique_index

__all__ = ["DataQualityProfiler", "QualityResult"]

_RESULT_COLUMNS: Final = (
    "col",
    "dtype",
    "missing_rate",
    "cardinality",
    "near_constant",
    "near_unique",
    "high_cardinality",
)


class QualityResult(BaseModel):
    """Resultado inmutable del diagnóstico descriptivo de calidad por columna."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    by_column: pd.DataFrame


class DataQualityProfiler:
    """Calcula missing, cardinalidad y flags descriptivos por columna."""

    def __init__(self, config: QualityConfig) -> None:
        """Construye el profiler con ``EdaConfig.quality``."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: QualityConfig) -> DataQualityProfiler:
        """Construye un profiler desde ``QualityConfig``."""
        return cls(cfg)

    def profile(
        self,
        frame: pd.DataFrame,
        *,
        audit: AuditSink | None = None,
    ) -> QualityResult:
        """Calcula el diagnóstico de calidad sin mutar el ``DataFrame`` de entrada.

        Parameters
        ----------
        frame : pandas.DataFrame
            Dataset validado por ``data`` o equivalente standalone. Se diagnostican todas sus
            columnas.
        audit : AuditSink or None
            Reservado para compatibilidad con la orquestación; este profiler puro no emite eventos
            auditables.

        Returns
        -------
        QualityResult
            Tabla con una fila por columna y flags descriptivos de calidad.

        Raises
        ------
        EdaError
            Si el frame está vacío o el índice no identifica observaciones de forma única.
        """
        del audit
        _validate_non_empty_frame(frame)
        _validate_unique_index(frame)

        source = frame.copy(deep=True)
        n_rows = len(source)
        rows = [
            _profile_column(
                column,
                source.iloc[:, position],
                config=self.config,
                n_rows=n_rows,
            )
            for position, column in enumerate(source.columns)
        ]
        by_column = pd.DataFrame(rows, columns=list(_RESULT_COLUMNS))
        by_column = by_column.astype(
            {
                "col": "object",
                "dtype": "object",
                "missing_rate": "float64",
                "cardinality": "int64",
                "near_constant": "bool",
                "near_unique": "bool",
                "high_cardinality": "bool",
            }
        )
        return QualityResult(by_column=by_column.copy(deep=True))


def _profile_column(
    column: object,
    series: pd.Series,
    *,
    config: QualityConfig,
    n_rows: int,
) -> dict[str, object]:
    """Calcula las métricas de calidad de una columna."""
    clean = _series_with_non_finite_as_missing(series)
    missing_rate = float(clean.isna().sum()) / float(n_rows)
    non_missing = clean.dropna()
    n_non_missing = len(non_missing)
    cardinality = int(non_missing.nunique(dropna=True))
    near_constant = _is_near_constant(non_missing, config.near_constant_threshold)
    # DECISIÓN AUTÓNOMA (frontera, revisión de Cami): sin umbral propio para near_unique.
    near_unique = bool(
        n_non_missing > 0 and cardinality / n_non_missing >= config.near_constant_threshold
    )
    high_cardinality = bool(
        _is_categorical_like(series) and cardinality > config.high_cardinality_threshold
    )
    return {
        "col": str(column),
        "dtype": str(series.dtype),
        "missing_rate": missing_rate,
        "cardinality": cardinality,
        "near_constant": near_constant,
        "near_unique": near_unique,
        "high_cardinality": high_cardinality,
    }


def _series_with_non_finite_as_missing(series: pd.Series) -> pd.Series:
    """Neutraliza ``±inf`` como missing antes de contar NaN y cardinalidad."""
    if pd.api.types.is_numeric_dtype(series.dtype):
        return series.replace([np.inf, -np.inf], np.nan)
    return series.copy(deep=True)


def _is_near_constant(non_missing: pd.Series, threshold: float) -> bool:
    """Marca columnas donde un valor domina los no nulos finitos."""
    if non_missing.empty:
        return False

    counts = non_missing.value_counts(dropna=True, sort=False)
    max_share = float(counts.max()) / float(len(non_missing))
    return bool(max_share >= threshold)


def _is_categorical_like(series: pd.Series) -> bool:
    """Identifica columnas categóricas para el flag de alta cardinalidad."""
    dtype = series.dtype
    checks = (
        pd.api.types.is_object_dtype(dtype),
        isinstance(dtype, pd.CategoricalDtype),
        pd.api.types.is_string_dtype(dtype),
    )
    return any(checks)
