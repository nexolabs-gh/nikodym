"""Evaluador de estabilidad poblacional, característica y temporal post-modelo (SDD-11 §4/§7).

``StabilityEvaluator`` toma un frame analítico ya alineado por las capas aguas arriba y calcula el
PSI del score (y de la PD calibrada), el CSI por característica final y la estabilidad temporal del
score. La regla anti-leakage de SDD-11 es central: los bins se fijan **una sola vez** en la
partición de Desarrollo (población esperada) y se aplican tal cual a Holdout/OOT y a cada período;
nunca se rebinnea sobre la población actual.

El módulo conserva el import liviano de ``nikodym.stability``: pandas, numpy y pandera se importan
dentro de ``evaluate`` o helpers locales. Los resultados finales se materializan en los DTOs de
``stability.results``, que vuelven a validar columnas canónicas, invariantes y copias defensivas.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeAlias, cast

from pydantic import ValidationError

from nikodym.core.base import BaseNikodymEstimator
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.stability.config import (
    CsiSource,
    ScoreDirection,
    StabilityComparison,
    StabilityConfig,
    TemporalAxis,
    TemporalFrequency,
)
from nikodym.stability.exceptions import StabilityDataError, StabilityMetricError
from nikodym.stability.results import (
    CsiRecord,
    PsiRecord,
    StabilityCardSection,
    StabilityMetricRecord,
    StabilityResult,
    TemporalStabilityRecord,
    _bands_by_comparison,
    _max_psi_by_comparison,
    _worst_csi,
)

if TYPE_CHECKING:
    import pandas as pd

    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series[Any]
else:
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["StabilityEvaluator"]

_SCORING_EXTRA_MESSAGE = (
    "StabilityEvaluator requiere pandas/numpy/pandera; instale nikodym[scoring]."
)
_PSI_TABLE_COLUMNS: tuple[str, ...] = tuple(PsiRecord.model_fields)
_STABILITY_METRIC_COLUMNS: tuple[str, ...] = tuple(StabilityMetricRecord.model_fields)
_DEFAULT_COMPARISONS: tuple[StabilityComparison, ...] = ("dev_vs_holdout", "dev_vs_oot")
_DEVELOPMENT_PARTITION = "desarrollo"
_COMPARISON_PARTITIONS: dict[StabilityComparison, tuple[str, str]] = {
    "dev_vs_holdout": (_DEVELOPMENT_PARTITION, "holdout"),
    "dev_vs_oot": (_DEVELOPMENT_PARTITION, "oot"),
}
_TEMPORAL_CANDIDATE_NAMES: frozenset[str] = frozenset({"period", "periodo", "cohort", "cohorte"})
_BAND_TO_ACTION: dict[str, str] = {
    "stable": "none",
    "review": "vigilar",
    "redevelop": "redesarrollar",
    "not_evaluable": "none",
}
_AUDITABLE_BANDS: frozenset[str] = frozenset({"review", "redevelop"})
_INTERNAL_PERIOD_COLUMN = "__nikodym_period__"
_SCORE_FEATURE = "score"
_PD_FEATURE = "pd_calibrated"


class StabilityEvaluator(AuditableMixin, BaseNikodymEstimator):
    """Calcula PSI del score/PD, CSI por característica y estabilidad temporal post-modelo."""

    config_cls: ClassVar[type[StabilityConfig]] = StabilityConfig

    def __init__(
        self,
        *,
        score_column: str = "score",
        pd_column: str = "pd_calibrated",
        partition_column: str = "partition",
        score_direction: ScoreDirection = "higher_is_lower_risk",
        psi_bins: int = 10,
        csi_bins: int = 10,
        psi_stable_threshold: float = 0.10,
        psi_review_threshold: float = 0.25,
        smoothing: float = 1e-6,
        comparisons: tuple[StabilityComparison, ...] = _DEFAULT_COMPARISONS,
        temporal_axis: TemporalAxis = "period",
        temporal_column: str | None = None,
        temporal_freq: TemporalFrequency = "M",
        include_pd_stability: bool = True,
        csi_source: CsiSource = "score_points",
    ) -> None:
        """Asigna hiperparámetros sin ejecutar cálculos científicos."""
        self.score_column = score_column
        self.pd_column = pd_column
        self.partition_column = partition_column
        self.score_direction = score_direction
        self.psi_bins = psi_bins
        self.csi_bins = csi_bins
        self.psi_stable_threshold = psi_stable_threshold
        self.psi_review_threshold = psi_review_threshold
        self.smoothing = smoothing
        self.comparisons = comparisons
        self.temporal_axis = temporal_axis
        self.temporal_column = temporal_column
        self.temporal_freq = temporal_freq
        self.include_pd_stability = include_pd_stability
        self.csi_source = csi_source

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig | Mapping[str, Any]) -> Self:
        """Construye el evaluador desde ``StabilityConfig`` excluyendo metadatos de schema."""
        if not isinstance(cfg, StabilityConfig):
            cfg = StabilityConfig.model_validate(cfg)
        kwargs = cfg.model_dump(exclude={"type", "schema_version"})
        return cls(**kwargs)

    def evaluate(
        self,
        frame: DataFrame,
        *,
        score_column: str,
        pd_column: str,
        partition_column: str,
        feature_point_columns: Sequence[str],
    ) -> StabilityResult:
        """Evalúa PSI del score/PD, CSI por característica y estabilidad temporal por partición.

        Parameters
        ----------
        frame : pandas.DataFrame
            Frame analítico post-modelo con score, PD calibrada, partición, columnas
            ``<feature>__points`` y, si aplica, la columna de período/cohorte.
        score_column : str
            Columna del score operacional.
        pd_column : str
            Columna de PD calibrada post-modelo, estrictamente en ``(0, 1)``.
        partition_column : str
            Columna que identifica ``desarrollo``, ``holdout`` y ``oot``.
        feature_point_columns : Sequence[str]
            Columnas ``<feature>__points`` cuya distribución de puntos alimenta el CSI.

        Returns
        -------
        StabilityResult
            DTO agregado con ``psi_table``, ``stability_metrics``, records y card.
        """
        pd_module = _import_pandas()
        np_module = _import_numpy()
        pa_module = _import_pandera()
        cfg = _validate_runtime_config(
            self,
            score_column=score_column,
            pd_column=pd_column,
            partition_column=partition_column,
        )

        copied = _as_dataframe(frame, pd_module)
        feature_cols = tuple(feature_point_columns)
        _validate_unique_columns(copied)
        if not copied.index.is_unique:
            raise StabilityDataError("StabilityEvaluator requiere índice único.")
        temporal_name = _resolve_temporal_column(copied, cfg)
        validated = _validate_schema(
            copied,
            cfg=cfg,
            feature_point_columns=feature_cols,
            temporal_name=temporal_name,
            pa=pa_module,
        )
        prepared = _prepare_frame(
            validated,
            cfg=cfg,
            feature_point_columns=feature_cols,
            temporal_name=temporal_name,
            pd=pd_module,
            np=np_module,
        )

        dev_scores = _partition_array(
            prepared,
            cfg=cfg,
            partition=_DEVELOPMENT_PARTITION,
            column=cfg.score_column,
            np=np_module,
        )
        dev_present = dev_scores.size > 0
        score_edges = (
            _quantile_interior_edges(dev_scores, cfg.psi_bins, np_module) if dev_present else None
        )

        psi_records: list[PsiRecord] = []
        csi_records: list[CsiRecord] = []
        metric_records: list[StabilityMetricRecord] = []

        self._evaluate_score_psi(
            prepared,
            cfg=cfg,
            dev_scores=dev_scores,
            score_edges=score_edges,
            dev_present=dev_present,
            np=np_module,
            psi_records=psi_records,
            metric_records=metric_records,
        )
        if cfg.include_pd_stability:
            self._evaluate_pd_psi(
                prepared,
                cfg=cfg,
                dev_present=dev_present,
                np=np_module,
                psi_records=psi_records,
                metric_records=metric_records,
            )
        self._evaluate_csi(
            prepared,
            cfg=cfg,
            feature_point_columns=feature_cols,
            dev_present=dev_present,
            np=np_module,
            csi_records=csi_records,
            metric_records=metric_records,
        )
        temporal_records = self._evaluate_temporal(
            prepared,
            cfg=cfg,
            dev_scores=dev_scores,
            score_edges=score_edges,
            dev_present=dev_present,
            temporal_name=temporal_name,
            np=np_module,
            metric_records=metric_records,
        )

        metric_tuple = tuple(metric_records)
        worst_csi_feature, worst_csi_value = _worst_csi(metric_tuple)
        card = StabilityCardSection(
            score_direction=cfg.score_direction,
            csi_source=cfg.csi_source,
            comparisons=tuple(cfg.comparisons),
            psi_bins=cfg.psi_bins,
            stable_threshold=cfg.psi_stable_threshold,
            review_threshold=cfg.psi_review_threshold,
            max_psi_by_comparison=_max_psi_by_comparison(metric_tuple),
            bands_by_comparison=_bands_by_comparison(metric_tuple),
            worst_csi_feature=worst_csi_feature,
            worst_csi_value=worst_csi_value,
            dependency_versions=_dependency_versions(),
            metric_sections={
                "stability": {
                    "temporal_axis": cfg.temporal_axis,
                    "include_pd_stability": cfg.include_pd_stability,
                    "csi_features": list(feature_cols),
                    "n_periods": len(temporal_records),
                }
            },
        )
        bin_rows: list[PsiRecord | CsiRecord] = [*psi_records, *csi_records]
        psi_table = _records_to_frame(
            bin_rows,
            columns=_PSI_TABLE_COLUMNS,
            pd=pd_module,
            index_name="bin_id",
            index_values=[
                f"{record.metric}|{record.comparison}|{record.feature}|{record.bin_label}"
                for record in bin_rows
            ],
        )
        stability_metrics = _records_to_frame(
            metric_records,
            columns=_STABILITY_METRIC_COLUMNS,
            pd=pd_module,
            index_name="metric_id",
            index_values=[
                f"{record.metric}|{record.comparison}|{record.feature}" for record in metric_records
            ],
        )
        result = StabilityResult(
            psi_table=psi_table,
            stability_metrics=stability_metrics,
            psi_records=tuple(psi_records),
            csi_records=tuple(csi_records),
            metric_records=metric_tuple,
            temporal_records=tuple(temporal_records),
            card=card,
        )

        self.result_ = result
        self.psi_table_ = result.psi_table
        self.stability_metrics_ = result.stability_metrics
        self.psi_records_ = result.psi_records
        self.csi_records_ = result.csi_records
        self.metric_records_ = result.metric_records
        self.temporal_records_ = result.temporal_records
        self.card_ = result.card
        return result

    def _evaluate_score_psi(
        self,
        prepared: DataFrame,
        *,
        cfg: StabilityConfig,
        dev_scores: Any,
        score_edges: Any,
        dev_present: bool,
        np: Any,
        psi_records: list[PsiRecord],
        metric_records: list[StabilityMetricRecord],
    ) -> None:
        """Calcula el PSI del score por comparación con bins fijados en Desarrollo."""
        for comparison in cfg.comparisons:
            _, actual_partition = _COMPARISON_PARTITIONS[comparison]
            actual = _partition_array(
                prepared, cfg=cfg, partition=actual_partition, column=cfg.score_column, np=np
            )
            if not dev_present or actual.size == 0:
                metric_records.append(
                    _metric_not_evaluable("score_psi", comparison, _SCORE_FEATURE, cfg)
                )
                continue
            counts = _bin_counts_continuous(dev_scores, actual, score_edges, np)
            psi = _psi_from_counts(counts, int(dev_scores.size), int(actual.size), cfg.smoothing)
            band = _band(psi.total, cfg.psi_stable_threshold, cfg.psi_review_threshold)
            psi_records.extend(
                _psi_records_from(
                    psi,
                    metric="score_psi",
                    comparison=comparison,
                    feature=_SCORE_FEATURE,
                    band=band,
                )
            )
            metric_records.append(
                _metric_evaluable("score_psi", comparison, _SCORE_FEATURE, psi.total, band, cfg)
            )
            self._log_band(
                regla="psi_score",
                band=band,
                value=psi.total,
                comparison=comparison,
                feature=_SCORE_FEATURE,
                cfg=cfg,
            )

    def _evaluate_pd_psi(
        self,
        prepared: DataFrame,
        *,
        cfg: StabilityConfig,
        dev_present: bool,
        np: Any,
        psi_records: list[PsiRecord],
        metric_records: list[StabilityMetricRecord],
    ) -> None:
        """Calcula el PSI de la PD calibrada por comparación con bins fijados en Desarrollo."""
        dev_pd = _partition_array(
            prepared, cfg=cfg, partition=_DEVELOPMENT_PARTITION, column=cfg.pd_column, np=np
        )
        pd_edges = _quantile_interior_edges(dev_pd, cfg.psi_bins, np) if dev_present else None
        for comparison in cfg.comparisons:
            _, actual_partition = _COMPARISON_PARTITIONS[comparison]
            actual = _partition_array(
                prepared, cfg=cfg, partition=actual_partition, column=cfg.pd_column, np=np
            )
            if not dev_present or actual.size == 0:
                metric_records.append(_metric_not_evaluable("pd_psi", comparison, _PD_FEATURE, cfg))
                continue
            counts = _bin_counts_continuous(dev_pd, actual, pd_edges, np)
            psi = _psi_from_counts(counts, int(dev_pd.size), int(actual.size), cfg.smoothing)
            band = _band(psi.total, cfg.psi_stable_threshold, cfg.psi_review_threshold)
            psi_records.extend(
                _psi_records_from(
                    psi, metric="pd_psi", comparison=comparison, feature=_PD_FEATURE, band=band
                )
            )
            metric_records.append(
                _metric_evaluable("pd_psi", comparison, _PD_FEATURE, psi.total, band, cfg)
            )
            self._log_band(
                regla="psi_pd",
                band=band,
                value=psi.total,
                comparison=comparison,
                feature=_PD_FEATURE,
                cfg=cfg,
            )

    def _evaluate_csi(
        self,
        prepared: DataFrame,
        *,
        cfg: StabilityConfig,
        feature_point_columns: tuple[str, ...],
        dev_present: bool,
        np: Any,
        csi_records: list[CsiRecord],
        metric_records: list[StabilityMetricRecord],
    ) -> None:
        """Calcula el CSI por característica con puntos discretos o bins fijados en Desarrollo."""
        for feature in feature_point_columns:
            dev_points = _partition_array(
                prepared, cfg=cfg, partition=_DEVELOPMENT_PARTITION, column=feature, np=np
            )
            discrete = dev_present and int(np.unique(dev_points).size) <= cfg.csi_bins
            feature_edges = (
                _quantile_interior_edges(dev_points, cfg.csi_bins, np)
                if dev_present and not discrete
                else None
            )
            for comparison in cfg.comparisons:
                _, actual_partition = _COMPARISON_PARTITIONS[comparison]
                actual = _partition_array(
                    prepared, cfg=cfg, partition=actual_partition, column=feature, np=np
                )
                if not dev_present or actual.size == 0:
                    metric_records.append(_metric_not_evaluable("csi", comparison, feature, cfg))
                    continue
                if discrete:
                    counts = _bin_counts_discrete(dev_points, actual, np)
                else:
                    counts = _bin_counts_continuous(dev_points, actual, feature_edges, np)
                psi = _psi_from_counts(
                    counts, int(dev_points.size), int(actual.size), cfg.smoothing
                )
                band = _band(psi.total, cfg.psi_stable_threshold, cfg.psi_review_threshold)
                csi_records.extend(
                    _csi_records_from(psi, comparison=comparison, feature=feature, band=band)
                )
                metric_records.append(
                    _metric_evaluable("csi", comparison, feature, psi.total, band, cfg)
                )
                self._log_band(
                    regla="csi_feature",
                    band=band,
                    value=psi.total,
                    comparison=comparison,
                    feature=feature,
                    cfg=cfg,
                )

    def _evaluate_temporal(
        self,
        prepared: DataFrame,
        *,
        cfg: StabilityConfig,
        dev_scores: Any,
        score_edges: Any,
        dev_present: bool,
        temporal_name: str | None,
        np: Any,
        metric_records: list[StabilityMetricRecord],
    ) -> list[TemporalStabilityRecord]:
        """Agrega el score por período/cohorte y calcula su PSI contra Desarrollo."""
        if cfg.temporal_axis == "none":
            return []
        if not dev_present:
            metric_records.append(
                _metric_not_evaluable("temporal_score", cfg.temporal_axis, _SCORE_FEATURE, cfg)
            )
            return []

        period_series = prepared[_INTERNAL_PERIOD_COLUMN]
        periods = sorted(str(value) for value in period_series.unique().tolist())
        temporal_records: list[TemporalStabilityRecord] = []
        psi_values: list[float] = []
        bands: list[str] = []
        for period in periods:
            mask = period_series.astype(str).eq(period)
            scores = prepared.loc[mask, cfg.score_column].to_numpy(dtype="float64", copy=True)
            pds = prepared.loc[mask, cfg.pd_column].to_numpy(dtype="float64", copy=True)
            counts = _bin_counts_continuous(dev_scores, scores, score_edges, np)
            psi = _psi_from_counts(counts, int(dev_scores.size), int(scores.size), cfg.smoothing)
            band = _band(psi.total, cfg.psi_stable_threshold, cfg.psi_review_threshold)
            quantiles = np.quantile(scores, [0.25, 0.5, 0.75])
            temporal_records.append(
                TemporalStabilityRecord(
                    period=period,
                    n_total=int(scores.size),
                    mean_score=_finite_scalar(np.mean(scores), context="mean_score"),
                    p25_score=_finite_scalar(quantiles[0], context="p25_score"),
                    p50_score=_finite_scalar(quantiles[1], context="p50_score"),
                    p75_score=_finite_scalar(quantiles[2], context="p75_score"),
                    mean_pd=_finite_scalar(np.mean(pds), context="mean_pd"),
                    psi=psi.total,
                    band=cast(Any, band),
                )
            )
            psi_values.append(psi.total)
            bands.append(band)

        worst_index = int(max(range(len(psi_values)), key=psi_values.__getitem__))
        worst_value = psi_values[worst_index]
        worst_band = bands[worst_index]
        metric_records.append(
            _metric_evaluable(
                "temporal_score", cfg.temporal_axis, _SCORE_FEATURE, worst_value, worst_band, cfg
            )
        )
        self._log_band(
            regla="score_temporal",
            band=worst_band,
            value=worst_value,
            comparison=cfg.temporal_axis,
            feature=_SCORE_FEATURE,
            cfg=cfg,
        )
        return temporal_records

    def _log_band(
        self,
        *,
        regla: str,
        band: str,
        value: float,
        comparison: str,
        feature: str,
        cfg: StabilityConfig,
    ) -> None:
        """Audita con ``log_decision`` cada banda que cruza ``review`` o ``redevelop``."""
        if band not in _AUDITABLE_BANDS:
            return
        self.log_decision(
            regla=regla,
            umbral={
                "psi_stable_threshold": cfg.psi_stable_threshold,
                "psi_review_threshold": cfg.psi_review_threshold,
            },
            valor={"comparison": comparison, "feature": feature, "value": value},
            accion=_BAND_TO_ACTION[band],
        )


@dataclass(frozen=True)
class _BinPsi:
    """Aporte de un bin individual al PSI/CSI ya suavizado."""

    bin_label: str
    expected_count: int
    actual_count: int
    expected_pct: float
    actual_pct: float
    component_value: float


@dataclass(frozen=True)
class _PsiResult:
    """Resultado de un PSI/CSI: bins y total agregado."""

    bins: tuple[_BinPsi, ...]
    total: float


def _import_pandas() -> Any:
    """Importa pandas localmente y traduce ausencias a mensaje accionable."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _import_numpy() -> Any:
    """Importa numpy localmente y traduce ausencias a mensaje accionable."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _import_pandera() -> Any:
    """Importa ``pandera.pandas`` bajo demanda, nunca el top-level de pandera."""
    try:
        import pandera.pandas as pa
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return pa


def _validate_runtime_config(
    estimator: StabilityEvaluator,
    *,
    score_column: str,
    pd_column: str,
    partition_column: str,
) -> StabilityConfig:
    """Revalida hiperparámetros planos y columnas efectivas de ``evaluate``."""
    try:
        cfg = StabilityConfig(
            score_column=score_column,
            pd_column=pd_column,
            partition_column=partition_column,
            score_direction=estimator.score_direction,
            psi_bins=estimator.psi_bins,
            csi_bins=estimator.csi_bins,
            psi_stable_threshold=estimator.psi_stable_threshold,
            psi_review_threshold=estimator.psi_review_threshold,
            smoothing=estimator.smoothing,
            comparisons=tuple(estimator.comparisons),
            temporal_axis=estimator.temporal_axis,
            temporal_column=estimator.temporal_column,
            temporal_freq=estimator.temporal_freq,
            include_pd_stability=estimator.include_pd_stability,
            csi_source=estimator.csi_source,
        )
    except (ConfigError, TypeError, ValidationError) as exc:
        raise ConfigError(f"Hiperparámetros inválidos para StabilityEvaluator: {exc}") from exc

    if len(set(cfg.comparisons)) != len(cfg.comparisons):
        raise ConfigError("StabilityEvaluator requiere comparaciones sin duplicados.")
    return cfg


def _as_dataframe(df: object, pd: Any) -> DataFrame:
    """Valida y copia defensivamente una entrada tabular."""
    if not isinstance(df, pd.DataFrame):
        raise StabilityDataError(
            "StabilityEvaluator.evaluate requiere pandas.DataFrame; "
            f"tipo observado={type(df).__name__}."
        )
    return cast(DataFrame, df.copy(deep=True))


def _validate_unique_columns(frame: DataFrame) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise StabilityDataError(
            f"StabilityEvaluator requiere nombres de columnas únicos; duplicadas: {joined}."
        )


def _resolve_temporal_column(frame: DataFrame, cfg: StabilityConfig) -> str | None:
    """Resuelve la columna temporal: explícita, inferida única o error si es ambigua/ausente."""
    if cfg.temporal_axis == "none":
        return None
    if cfg.temporal_column is not None:
        if cfg.temporal_column not in frame.columns:
            raise StabilityDataError(
                f"stability.temporal_column='{cfg.temporal_column}' no está en el frame."
            )
        return cfg.temporal_column

    candidates = [
        str(column) for column in frame.columns if str(column).lower() in _TEMPORAL_CANDIDATE_NAMES
    ]
    if not candidates:
        raise StabilityDataError(
            "temporal_axis distinto de 'none' pero no se halló una columna de período/cohorte; "
            "fije stability.temporal_column."
        )
    if len(candidates) > 1:
        raise StabilityDataError(
            f"Columna temporal ambigua entre {candidates}; fije stability.temporal_column."
        )
    return candidates[0]


def _validate_schema(
    frame: DataFrame,
    *,
    cfg: StabilityConfig,
    feature_point_columns: tuple[str, ...],
    temporal_name: str | None,
    pa: Any,
) -> DataFrame:
    """Valida columnas requeridas y no-nulos mínimos mediante checks propios y pandera."""
    required = [cfg.partition_column, cfg.score_column, cfg.pd_column, *feature_point_columns]
    if temporal_name is not None:
        required.append(temporal_name)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise StabilityDataError(f"stability frame no contiene columnas requeridas: {joined}.")

    columns: dict[str, Any] = {
        column: pa.Column(nullable=False, required=True) for column in required
    }
    schema = pa.DataFrameSchema(columns, strict=False)
    try:
        validated = schema.validate(frame, lazy=True)
    except Exception as exc:
        if _is_pandera_schema_error(pa, exc):
            raise StabilityDataError(
                "El frame de stability no cumple el esquema mínimo de SDD-11 §6."
            ) from exc
        raise
    return cast(DataFrame, validated.copy(deep=True))


def _is_pandera_schema_error(pa: Any, exc: Exception) -> bool:
    """Reconoce errores de pandera sin importar ``pandera`` en el top-level."""
    return isinstance(exc, (pa.errors.SchemaError, pa.errors.SchemaErrors))


def _prepare_frame(
    frame: DataFrame,
    *,
    cfg: StabilityConfig,
    feature_point_columns: tuple[str, ...],
    temporal_name: str | None,
    pd: Any,
    np: Any,
) -> DataFrame:
    """Convierte columnas numéricas, valida finitud/rango y agrega la etiqueta de período."""
    prepared = frame.copy(deep=True)
    score = _numeric_array(prepared[cfg.score_column], column=cfg.score_column, np=np)
    calibrated_pd = _numeric_array(prepared[cfg.pd_column], column=cfg.pd_column, np=np)
    invalid_pd = (calibrated_pd <= 0.0) | (calibrated_pd >= 1.0)
    if bool(invalid_pd.any()):
        observed = calibrated_pd[invalid_pd][0]
        raise StabilityDataError(
            f"{cfg.pd_column} debe estar estrictamente en (0, 1): "
            f"valor observado={float(observed)!r}."
        )

    prepared[cfg.score_column] = _float_series(score, prepared.index, pd)
    prepared[cfg.pd_column] = _float_series(calibrated_pd, prepared.index, pd)
    for column in feature_point_columns:
        points = _numeric_array(prepared[column], column=column, np=np)
        prepared[column] = _float_series(points, prepared.index, pd)
    if temporal_name is not None:
        prepared[_INTERNAL_PERIOD_COLUMN] = _period_labels(
            prepared[temporal_name], cfg.temporal_freq, pd
        )
    return prepared


def _numeric_array(series: Series, *, column: str, np: Any) -> Any:
    """Convierte una serie a ``float64`` finito antes de binnear o agregar."""
    try:
        values = series.to_numpy(dtype="float64", copy=True)
    except (TypeError, ValueError) as exc:
        raise StabilityDataError(
            f"La columna '{column}' debe ser numérica float64-compatible."
        ) from exc
    finite = np.isfinite(values)
    if not bool(finite.all()):
        observed = values[~finite][0]
        raise StabilityDataError(
            f"La columna '{column}' debe contener sólo valores finitos: "
            f"valor observado={float(observed)!r}."
        )
    return values


def _float_series(values: Any, index: Any, pd: Any) -> Series:
    """Crea una serie float64 normalizada (``-0.0 -> 0.0``) para publicar y binnear."""
    return cast(
        Series,
        pd.Series(values, index=index, dtype="float64").map(_normalize_float).astype("float64"),
    )


def _period_labels(series: Series, freq: str, pd: Any) -> Series:
    """Etiqueta de período: bucketiza datetime por frecuencia o usa el valor como cohorte."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return cast(Series, series.dt.to_period(freq).astype(str))
    return cast(Series, series.astype(str))


def _partition_array(
    frame: DataFrame,
    *,
    cfg: StabilityConfig,
    partition: str,
    column: str,
    np: Any,
) -> Any:
    """Extrae el array float64 de una columna para las filas de una partición."""
    del np
    mask = frame[cfg.partition_column].eq(partition)
    return frame.loc[mask, column].to_numpy(dtype="float64", copy=True)


def _quantile_interior_edges(values: Any, n_bins: int, np: Any) -> Any:
    """Fija los cortes interiores de bins por cuantiles de Desarrollo (anti-leakage)."""
    interior_quantiles = np.linspace(0.0, 1.0, n_bins + 1)[1:-1]
    edges = np.quantile(values, interior_quantiles)
    return np.unique(edges)


def _bin_counts_continuous(
    expected_values: Any,
    actual_values: Any,
    interior_edges: Any,
    np: Any,
) -> list[tuple[str, int, int]]:
    """Cuenta esperado/actual por bin continuo usando cortes fijados en Desarrollo."""
    n_bins = int(interior_edges.size) + 1
    expected_idx = np.searchsorted(interior_edges, expected_values, side="right")
    actual_idx = np.searchsorted(interior_edges, actual_values, side="right")
    expected_counts = np.bincount(expected_idx, minlength=n_bins)
    actual_counts = np.bincount(actual_idx, minlength=n_bins)
    return [
        (f"bin_{index:02d}", int(expected_counts[index]), int(actual_counts[index]))
        for index in range(n_bins)
    ]


def _bin_counts_discrete(
    expected_values: Any,
    actual_values: Any,
    np: Any,
) -> list[tuple[str, int, int]]:
    """Cuenta esperado/actual sobre los puntos discretos de Desarrollo, con bin ``__other__``."""
    categories = np.unique(expected_values)
    n_categories = int(categories.size)
    member = np.isin(actual_values, categories)
    has_other = bool((~member).any())
    n_bins = n_categories + (1 if has_other else 0)

    expected_idx = np.searchsorted(categories, expected_values)
    actual_idx = np.where(member, np.searchsorted(categories, actual_values), n_categories)
    expected_counts = np.bincount(expected_idx, minlength=n_bins)
    actual_counts = np.bincount(actual_idx, minlength=n_bins)

    counts = [
        (_discrete_label(categories[index]), int(expected_counts[index]), int(actual_counts[index]))
        for index in range(n_categories)
    ]
    if has_other:
        counts.append(
            ("__other__", int(expected_counts[n_categories]), int(actual_counts[n_categories]))
        )
    return counts


def _discrete_label(value: Any) -> str:
    """Etiqueta canónica y estable de un punto discreto."""
    return f"pts={float(value)!r}"


def _psi_from_counts(
    counts: list[tuple[str, int, int]],
    n_expected: int,
    n_actual: int,
    smoothing: float,
) -> _PsiResult:
    """Aplica la fórmula PSI con suavizado de proporciones cero antes del logaritmo."""
    total = 0.0
    bins: list[_BinPsi] = []
    for label, expected_count, actual_count in counts:
        expected_raw = expected_count / n_expected
        actual_raw = actual_count / n_actual
        expected_pct = expected_raw if expected_raw > 0.0 else smoothing
        actual_pct = actual_raw if actual_raw > 0.0 else smoothing
        component = (actual_pct - expected_pct) * math.log(actual_pct / expected_pct)
        total += component
        bins.append(
            _BinPsi(
                bin_label=label,
                expected_count=expected_count,
                actual_count=actual_count,
                expected_pct=_normalize_float(expected_pct),
                actual_pct=_normalize_float(actual_pct),
                component_value=_normalize_float(component),
            )
        )
    return _PsiResult(bins=tuple(bins), total=_finite_scalar(total, context="psi"))


def _psi_records_from(
    psi: _PsiResult,
    *,
    metric: str,
    comparison: str,
    feature: str,
    band: str,
) -> list[PsiRecord]:
    """Construye filas ``PsiRecord`` para ``psi_table`` desde un PSI calculado."""
    return [
        PsiRecord(
            metric=cast(Any, metric),
            comparison=comparison,
            feature=feature,
            bin_label=bin_psi.bin_label,
            expected_count=bin_psi.expected_count,
            actual_count=bin_psi.actual_count,
            expected_pct=bin_psi.expected_pct,
            actual_pct=bin_psi.actual_pct,
            component_value=bin_psi.component_value,
            total_value=psi.total,
            band=cast(Any, band),
        )
        for bin_psi in psi.bins
    ]


def _csi_records_from(
    psi: _PsiResult,
    *,
    comparison: str,
    feature: str,
    band: str,
) -> list[CsiRecord]:
    """Construye filas ``CsiRecord`` para ``psi_table`` desde un CSI calculado."""
    return [
        CsiRecord(
            metric="csi",
            comparison=comparison,
            feature=feature,
            bin_label=bin_psi.bin_label,
            expected_count=bin_psi.expected_count,
            actual_count=bin_psi.actual_count,
            expected_pct=bin_psi.expected_pct,
            actual_pct=bin_psi.actual_pct,
            component_value=bin_psi.component_value,
            total_value=psi.total,
            band=cast(Any, band),
        )
        for bin_psi in psi.bins
    ]


def _metric_evaluable(
    metric: str,
    comparison: str,
    feature: str,
    value: float,
    band: str,
    cfg: StabilityConfig,
) -> StabilityMetricRecord:
    """Construye una fila evaluable de ``stability_metrics``."""
    return StabilityMetricRecord(
        metric=cast(Any, metric),
        comparison=comparison,
        feature=feature,
        value=value,
        stable_threshold=cfg.psi_stable_threshold,
        review_threshold=cfg.psi_review_threshold,
        band=cast(Any, band),
        action=cast(Any, _BAND_TO_ACTION[band]),
    )


def _metric_not_evaluable(
    metric: str,
    comparison: str,
    feature: str,
    cfg: StabilityConfig,
) -> StabilityMetricRecord:
    """Construye una fila ``not_evaluable`` de ``stability_metrics`` sin value."""
    return StabilityMetricRecord(
        metric=cast(Any, metric),
        comparison=comparison,
        feature=feature,
        value=None,
        stable_threshold=cfg.psi_stable_threshold,
        review_threshold=cfg.psi_review_threshold,
        band="not_evaluable",
        action="none",
    )


def _band(value: float, stable_threshold: float, review_threshold: float) -> str:
    """Asigna la banda PSI/CSI según los umbrales configurados."""
    if value < stable_threshold:
        return "stable"
    if value < review_threshold:
        return "review"
    return "redevelop"


def _records_to_frame(
    records: Sequence[Any],
    *,
    columns: tuple[str, ...],
    pd: Any,
    index_name: str,
    index_values: list[str],
) -> DataFrame:
    """Convierte records Pydantic a DataFrame con columnas e índice canónicos."""
    rows = [record.model_dump() for record in records]
    frame = pd.DataFrame(rows, columns=list(columns))
    frame.index = pd.Index(index_values, name=index_name)
    return _normalize_float_columns(frame)


def _normalize_float_columns(frame: DataFrame) -> DataFrame:
    """Normaliza ``-0.0`` a ``0.0`` sólo en columnas float."""
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        series = copied[column]
        zero_mask = series == 0.0
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _dependency_versions() -> dict[str, str]:
    """Publica versiones de dependencias usadas por el evaluator."""
    import importlib.metadata as importlib_metadata

    versions: dict[str, str] = {}
    for public_name, module_name in (("numpy", "numpy"), ("pandas", "pandas")):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
        versions[public_name] = str(getattr(module, "__version__", "unknown"))
    try:
        versions["pandera"] = importlib_metadata.version("pandera")
    except importlib_metadata.PackageNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return {name: versions[name] for name in sorted(versions)}


def _finite_scalar(value: Any, *, context: str) -> float:
    """Normaliza un escalar y exige finitud antes de publicarlo."""
    observed = float(value)
    if not math.isfinite(observed):
        raise StabilityMetricError(f"El estadístico {context} produjo un valor no finito.")
    return _normalize_float(observed)


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` sin redondear otros valores."""
    observed = float(value)
    if observed == 0.0:
        return 0.0
    return observed
