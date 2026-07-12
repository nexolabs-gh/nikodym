"""Perfiles univariados descriptivos para la capa ``eda`` (SDD-27 §3/§4/§7).

``UnivariateProfiler`` calcula tablas feature-target con conteo, cobertura y tasa de default por
tramo sin ajustar parámetros ni mutar el ``DataFrame`` de entrada. Los tramos numéricos usan
cuantiles descriptivos y los categóricos agrupan niveles raros; ambos son diagnóstico EDA y no
transforman el dato para el modelo.

El IV opcional es **pre-binning, NO es el IV final de SDD-06** (D-EDA-3).

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import math
from typing import Final, SupportsFloat, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.core.audit import AuditSink
from nikodym.eda.config import UnivariateConfig
from nikodym.eda.default_rate import (
    _bad_mask,
    _default_rate_series,
    _eligible_mask,
    _stable_label,
    _validate_non_empty_frame,
    _validate_target_column,
    _validate_unique_index,
)
from nikodym.eda.exceptions import EdaError

__all__ = ["UnivariateProfiler", "UnivariateResult"]

_RESULT_COLUMNS: Final = ("tramo", "n", "coverage", "default_rate")
_N_BAD_COL: Final = "__nikodym_eda_n_bad"
_MISSING_KEY: Final = "__nikodym_eda_missing"
_RARE_KEY: Final = "__nikodym_eda_rare"
_MISSING_LABEL: Final = "missing"
_RARE_LABEL: Final = "_otros_"
_LAPLACE_ALPHA: Final = 0.5


class UnivariateResult(BaseModel):
    """Resultado inmutable de perfiles univariados feature-target."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    profiles: dict[str, pd.DataFrame]
    descriptive_iv: dict[str, float]


class UnivariateProfiler:
    """Calcula perfiles descriptivos de features candidatas frente al target."""

    def __init__(self, config: UnivariateConfig) -> None:
        """Construye el profiler con ``EdaConfig.univariate``."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: UnivariateConfig) -> UnivariateProfiler:
        """Construye un profiler desde ``UnivariateConfig``."""
        return cls(cfg)

    def profile(
        self,
        frame: pd.DataFrame,
        *,
        target_col: str,
        columns: tuple[str, ...],
        audit: AuditSink | None = None,
    ) -> UnivariateResult:
        """Calcula perfiles univariados sobre filas con target elegible.

        Parameters
        ----------
        frame : pandas.DataFrame
            Dataset etiquetado por ``data`` o equivalente standalone.
        target_col : str
            Columna binaria nullable: ``1`` malo, ``0`` bueno, ``<NA>`` no elegible.
        columns : tuple[str, ...]
            Columnas candidatas a perfilar. Una tupla vacía produce resultado vacío.
        audit : AuditSink or None
            Reservado para compatibilidad con la orquestación; este profiler puro no emite eventos
            auditables y no aplica muestreo.

        Returns
        -------
        UnivariateResult
            Diccionario columna-tabla y, si se pidió, IV descriptivo pre-binning.

        Raises
        ------
        EdaError
            Si faltan columnas requeridas, el frame está vacío o el índice no es único.
        """
        del audit
        _validate_non_empty_frame(frame)
        _validate_unique_index(frame)
        _validate_target_column(frame, target_col)
        _validate_profile_columns(frame, columns)

        if not columns:
            return UnivariateResult(profiles={}, descriptive_iv={})

        source = frame.copy(deep=True)
        eligible = _eligible_mask(source[target_col])
        bad = _bad_mask(source[target_col]).loc[eligible]
        profiles: dict[str, pd.DataFrame] = {}
        descriptive_iv: dict[str, float] = {}

        for column in columns:
            column_data = source.loc[:, column]
            if isinstance(column_data, pd.DataFrame):
                raise EdaError(
                    "El perfil univariado requiere nombres de columnas únicos; "
                    f"la columna '{column}' aparece más de una vez."
                )
            series = column_data.loc[eligible].copy(deep=True)
            full_profile = _profile_feature(series, bad, self.config)
            profiles[column] = full_profile.loc[:, list(_RESULT_COLUMNS)].copy(deep=True)
            if self.config.compute_descriptive_iv:
                descriptive_iv[column] = _descriptive_iv(full_profile)

        return UnivariateResult(profiles=profiles, descriptive_iv=descriptive_iv)


def _validate_profile_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    """Valida que las columnas solicitadas existan antes de perfilar."""
    missing = [column for column in columns if column not in frame.columns]
    if not missing:
        return

    joined = ", ".join(f"'{column}'" for column in missing)
    raise EdaError(f"El perfil univariado requiere columna(s) existente(s): {joined}.")


def _profile_feature(
    series: pd.Series,
    bad: pd.Series,
    config: UnivariateConfig,
) -> pd.DataFrame:
    """Despacha el perfil según dtype pandas de la columna."""
    if pd.api.types.is_numeric_dtype(series.dtype):
        return _numeric_profile(series, bad, config)
    return _categorical_profile(series, bad, config)


def _numeric_profile(
    series: pd.Series,
    bad: pd.Series,
    config: UnivariateConfig,
) -> pd.DataFrame:
    """Construye tramos por cuantiles y deja ``missing`` al final."""
    total_n = len(series)
    if total_n == 0:
        return _aggregate_profile(
            pd.Series(index=series.index, dtype="object"),
            bad,
            order=[_MISSING_KEY],
            display_values={_MISSING_KEY: _MISSING_LABEL},
        )

    series = series.replace([np.inf, -np.inf], np.nan)
    missing = series.isna()
    keys = pd.Series(index=series.index, dtype="object")
    order: list[str] = []
    display_values: dict[str, object] = {}
    non_missing = series.loc[~missing]

    if not non_missing.empty:
        raw_codes, raw_edges = pd.qcut(
            non_missing,
            config.n_quantile_bins,
            duplicates="drop",
            labels=False,
            retbins=True,
        )
        codes = pd.Series(raw_codes, index=non_missing.index)
        edges = np.asarray(raw_edges, dtype="float64")
        observed_codes = sorted(int(code) for code in codes.dropna().unique())
        for code in observed_codes:
            label = _interval_label(edges, code)
            code_mask = codes.eq(code).fillna(False).astype("bool")
            keys.loc[code_mask[code_mask].index] = label
            order.append(label)
            display_values[label] = label

        if not order:
            label = _constant_numeric_label(non_missing)
            keys.loc[non_missing.index] = label
            order.append(label)
            display_values[label] = label

    if bool(missing.any()):
        keys.loc[missing] = _MISSING_KEY
        order.append(_MISSING_KEY)
        display_values[_MISSING_KEY] = _MISSING_LABEL

    return _aggregate_profile(keys, bad, order=order, display_values=display_values)


def _interval_label(edges: np.ndarray, code: int) -> str:
    """Construye la etiqueta ``str(interval)`` sin usar el formateo interno de ``qcut``."""
    left = _normalize_float(float(edges[code]))
    right = _normalize_float(float(edges[code + 1]))
    return str(pd.Interval(left=left, right=right, closed="right"))


def _constant_numeric_label(non_missing: pd.Series) -> str:
    """Etiqueta determinista para una numérica constante que ``qcut`` colapsó a cero bins."""
    value = float(cast(SupportsFloat, non_missing.iloc[0]))
    value = _normalize_float(value)
    return str(pd.Interval(left=value, right=value, closed="both"))


def _categorical_profile(
    series: pd.Series,
    bad: pd.Series,
    config: UnivariateConfig,
) -> pd.DataFrame:
    """Construye tramos por nivel, con raros en ``_otros_`` y ``missing`` al final."""
    total_n = len(series)
    if total_n == 0:
        return _aggregate_profile(
            pd.Series(index=series.index, dtype="object"),
            bad,
            order=[_MISSING_KEY],
            display_values={_MISSING_KEY: _MISSING_LABEL},
        )

    missing = series.isna()
    keys = pd.Series(index=series.index, dtype="object")
    order: list[str] = []
    display_values: dict[str, object] = {}
    non_missing = series.loc[~missing]

    if not non_missing.empty:
        stable_keys = non_missing.map(_stable_label)
        counts = stable_keys.value_counts(sort=False)
        sorted_keys = sorted(str(key) for key in counts.index)
        rare_keys = {
            key
            for key in sorted_keys
            if float(counts.loc[key]) / float(total_n) < config.rare_level_threshold
        }
        normal_keys = [key for key in sorted_keys if key not in rare_keys]

        for key in normal_keys:
            key_mask = stable_keys.eq(key).fillna(False).astype("bool")
            keys.loc[key_mask[key_mask].index] = key
            order.append(key)
            display_values[key] = _representative_value(non_missing, stable_keys, key)

        if rare_keys:
            rare_mask = stable_keys.isin(rare_keys).fillna(False).astype("bool")
            keys.loc[rare_mask[rare_mask].index] = _RARE_KEY
            order.append(_RARE_KEY)
            display_values[_RARE_KEY] = _RARE_LABEL

    if bool(missing.any()):
        keys.loc[missing] = _MISSING_KEY
        order.append(_MISSING_KEY)
        display_values[_MISSING_KEY] = _MISSING_LABEL

    return _aggregate_profile(keys, bad, order=order, display_values=display_values)


def _representative_value(series: pd.Series, stable_keys: pd.Series, key: str) -> object:
    """Recupera el valor visible del nivel sin comparar objetos heterogéneos."""
    key_mask = stable_keys.eq(key).fillna(False).astype("bool")
    return series.loc[key_mask].iloc[0]


def _aggregate_profile(
    keys: pd.Series,
    bad: pd.Series,
    *,
    order: list[str],
    display_values: dict[str, object],
) -> pd.DataFrame:
    """Agrega conteos, cobertura y tasa de default respetando el orden recibido."""
    total_n = len(keys)
    rows: list[dict[str, object]] = []
    for key in order:
        mask = keys.eq(key).fillna(False).astype("bool")
        n = int(mask.sum())
        n_bad = int(bad.loc[mask].sum())
        coverage = 1.0 if total_n == 0 else _normalize_float(float(n) / float(total_n))
        rows.append(
            {
                "tramo": display_values[key],
                "n": n,
                _N_BAD_COL: n_bad,
                "coverage": coverage,
            }
        )

    result = pd.DataFrame(rows, columns=["tramo", "n", _N_BAD_COL, "coverage"])
    result["n"] = result["n"].astype("int64")
    result[_N_BAD_COL] = result[_N_BAD_COL].astype("int64")
    rate_input = pd.DataFrame(
        {"n_eligible": result["n"], "n_bad": result[_N_BAD_COL]},
        index=result.index,
    )
    result["default_rate"] = _default_rate_series(rate_input).map(_normalize_float)
    result["coverage"] = result["coverage"].astype("float64").map(_normalize_float)
    return result


def _descriptive_iv(profile: pd.DataFrame) -> float:
    """Calcula IV descriptivo pre-binning con suavizado de Laplace.

    Este valor es un diagnóstico de EDA **pre-binning, NO es el IV final de SDD-06**.
    """
    k = len(profile)
    n = profile["n"].astype("float64")
    n_bad = profile[_N_BAD_COL].astype("float64")
    n_good = n - n_bad
    total_good = float(n_good.sum())
    total_bad = float(n_bad.sum())
    alpha_k = _LAPLACE_ALPHA * float(k)
    dist_good = (n_good + _LAPLACE_ALPHA) / (total_good + alpha_k)
    dist_bad = (n_bad + _LAPLACE_ALPHA) / (total_bad + alpha_k)
    iv = float(((dist_good - dist_bad) * np.log(dist_good / dist_bad)).sum())
    return _normalize_float(iv)


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` sin tocar ``NaN``."""
    if math.isnan(value):
        return value
    if value == 0.0:
        return 0.0
    return value
