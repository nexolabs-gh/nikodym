"""Evaluador de discriminación y tabla de gains post-modelo (SDD-11 §4/§7).

``PerformanceEvaluator`` toma un frame analítico ya alineado por las capas aguas arriba y calcula
AUC, Gini, KS y deciles/gains por partición. La orientación publicada es siempre positiva hacia
default: por defecto usa la PD calibrada; si se evalúa el score y ``score_direction`` indica que un
score mayor es menor riesgo, invierte el signo antes de llamar a scikit-learn.

El módulo conserva el import liviano de ``nikodym.performance``: pandas, numpy, pandera y sklearn se
importan dentro de ``evaluate`` o helpers locales. Los resultados finales se materializan en los
DTOs de ``performance.results``, que vuelven a validar columnas canónicas, invariantes y copias
defensivas.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeAlias, cast

from pydantic import ValidationError

from nikodym.core.base import BaseNikodymEstimator
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.performance.config import (
    EvaluationSource,
    PerformanceConfig,
    PerformancePartition,
    ScoreDirection,
)
from nikodym.performance.exceptions import PerformanceDataError, PerformanceMetricError
from nikodym.performance.results import (
    DecilePerformanceRecord,
    DiscriminantMetricRecord,
    PerformanceCardSection,
    PerformanceResult,
)

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    DataFrame: TypeAlias = pd.DataFrame
    NDArrayBool: TypeAlias = np.ndarray[Any, np.dtype[np.bool_]]
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    NDArrayInt: TypeAlias = np.ndarray[Any, np.dtype[np.int64]]
    Series: TypeAlias = pd.Series[Any]
else:
    DataFrame: TypeAlias = Any
    NDArrayBool: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any
    NDArrayInt: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["PerformanceEvaluator"]

_SCORING_EXTRA_MESSAGE = (
    "PerformanceEvaluator requiere pandas/numpy/pandera/scikit-learn; instale nikodym[scoring]."
)
_PERFORMANCE_TABLE_COLUMNS: tuple[str, ...] = tuple(DecilePerformanceRecord.model_fields)
_DISCRIMINANT_METRIC_COLUMNS: tuple[str, ...] = tuple(DiscriminantMetricRecord.model_fields)
_MODELABLE_PARTITIONS: tuple[PerformancePartition, ...] = ("desarrollo", "holdout", "oot")
_METRIC_THRESHOLD_KEYS: dict[str, str] = {
    "auc": "auc_min",
    "gini": "gini_min",
    "ks": "ks_min",
}
_INTERNAL_RISK_COLUMN = "__nikodym_risk_score__"
_INTERNAL_INDEX_KEY_COLUMN = "__nikodym_index_key__"


class PerformanceEvaluator(AuditableMixin, BaseNikodymEstimator):
    """Calcula métricas discriminantes y deciles/gains para score o PD calibrada."""

    config_cls: ClassVar[type[PerformanceConfig]] = PerformanceConfig

    def __init__(
        self,
        *,
        score_column: str = "score",
        pd_column: str = "pd_calibrated",
        target_column: str = "target",
        partition_column: str = "partition",
        score_direction: ScoreDirection = "higher_is_lower_risk",
        evaluation_source: EvaluationSource = "pd_calibrated",
        partitions: tuple[PerformancePartition, ...] = _MODELABLE_PARTITIONS,
        n_deciles: int = 10,
        min_rows_per_partition: int = 30,
        min_events_per_partition: int = 1,
        optional_thresholds: dict[str, float] | None = None,
    ) -> None:
        """Asigna hiperparámetros sin ejecutar cálculos científicos."""
        self.score_column = score_column
        self.pd_column = pd_column
        self.target_column = target_column
        self.partition_column = partition_column
        self.score_direction = score_direction
        self.evaluation_source = evaluation_source
        self.partitions = partitions
        self.n_deciles = n_deciles
        self.min_rows_per_partition = min_rows_per_partition
        self.min_events_per_partition = min_events_per_partition
        self.optional_thresholds = {} if optional_thresholds is None else optional_thresholds

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig | Mapping[str, Any]) -> Self:
        """Construye el evaluador desde ``PerformanceConfig`` excluyendo metadatos de schema."""
        if not isinstance(cfg, PerformanceConfig):
            cfg = PerformanceConfig.model_validate(cfg)
        kwargs = cfg.model_dump(exclude={"type", "schema_version"})
        return cls(**kwargs)

    def evaluate(
        self,
        frame: DataFrame,
        *,
        score_column: str,
        pd_column: str,
        target_column: str,
        partition_column: str,
    ) -> PerformanceResult:
        """Evalúa AUC/Gini/KS y tabla de deciles por partición.

        Parameters
        ----------
        frame : pandas.DataFrame
            Frame analítico post-modelo con score, PD calibrada, target y partición.
        score_column : str
            Columna del score operacional.
        pd_column : str
            Columna de PD calibrada post-modelo.
        target_column : str
            Columna target binaria, con ``1`` como default.
        partition_column : str
            Columna que identifica ``desarrollo``, ``holdout`` y ``oot``.

        Returns
        -------
        PerformanceResult
            DTO agregado con ``performance_table``, ``discriminant_metrics``, records y card.
        """
        pd_module = _import_pandas()
        np_module = _import_numpy()
        pa_module = _import_pandera()
        sklearn_metrics = _import_sklearn_metrics()
        cfg = _validate_runtime_config(
            self,
            score_column=score_column,
            pd_column=pd_column,
            target_column=target_column,
            partition_column=partition_column,
        )

        copied = _as_dataframe(frame, pd_module)
        validated = _validate_input_schema(
            copied,
            cfg=cfg,
            pd=pd_module,
            pa=pa_module,
        )
        modelable = _modelable_frame(validated, cfg=cfg, pd=pd_module)
        prepared = _prepare_modelable_frame(
            modelable,
            cfg=cfg,
            pd=pd_module,
            np=np_module,
        )

        performance_records: list[DecilePerformanceRecord] = []
        discriminant_records: list[DiscriminantMetricRecord] = []
        not_evaluable_reasons: dict[str, str] = {}
        threshold_flags: dict[str, list[str]] = {}
        effective_deciles: dict[str, int] = {}

        for partition in cfg.partitions:
            partition_frame = _partition_frame(prepared, cfg=cfg, partition=partition)
            performance_for_partition, n_effective = _decile_records_for_partition(
                partition_frame,
                cfg=cfg,
                pd=pd_module,
                np=np_module,
            )
            performance_records.extend(performance_for_partition)
            effective_deciles[partition] = n_effective

            evaluability = _evaluability(partition_frame, cfg=cfg, np=np_module)
            if evaluability.reason is not None:
                not_evaluable_reasons[partition] = evaluability.reason
                self.log_decision(
                    regla="performance_not_evaluable",
                    umbral={
                        "min_rows_per_partition": cfg.min_rows_per_partition,
                        "min_events_per_partition": cfg.min_events_per_partition,
                    },
                    valor={
                        "partition": partition,
                        "n_total": evaluability.n_total,
                        "n_bad": evaluability.n_bad,
                        "n_good": evaluability.n_good,
                        "motivo": evaluability.reason,
                    },
                    accion="no_evaluar",
                )
                discriminant_records.append(
                    _not_evaluable_record(
                        partition=partition,
                        counts=evaluability,
                        source=cfg.evaluation_source,
                    )
                )
                continue

            computed = _compute_discriminant_metrics(
                partition_frame,
                cfg=cfg,
                sklearn_metrics=sklearn_metrics,
                np=np_module,
            )
            flags = _threshold_flags_for(computed, cfg.optional_thresholds)
            if flags:
                threshold_flags[partition] = flags
                for metric_name in flags:
                    threshold_key = _METRIC_THRESHOLD_KEYS[metric_name]
                    self.log_decision(
                        regla=f"performance_{threshold_key}",
                        umbral=cfg.optional_thresholds[threshold_key],
                        valor={
                            "partition": partition,
                            metric_name: getattr(computed, metric_name),
                        },
                        accion="threshold_flag",
                    )

            discriminant_records.append(
                _discriminant_record_from_metrics(
                    partition=partition,
                    counts=evaluability,
                    computed=computed,
                    source=cfg.evaluation_source,
                    status="threshold_flag" if flags else "ok",
                )
            )

        performance_table = _records_to_frame(
            performance_records,
            columns=_PERFORMANCE_TABLE_COLUMNS,
            pd=pd_module,
            index_name="bucket_id",
            index_values=[f"{record.partition}_d{record.decile}" for record in performance_records],
        )
        discriminant_metrics = _records_to_frame(
            discriminant_records,
            columns=_DISCRIMINANT_METRIC_COLUMNS,
            pd=pd_module,
            index_name="partition_id",
            index_values=[record.partition for record in discriminant_records],
        )
        card = PerformanceCardSection(
            evaluation_source=cfg.evaluation_source,
            score_direction=cfg.score_direction,
            partitions=tuple(record.partition for record in discriminant_records),
            thresholds=cfg.optional_thresholds,
            max_metrics_by_partition=_metrics_by_partition(discriminant_records),
            bands_by_partition={record.partition: record.status for record in discriminant_records},
            n_deciles=cfg.n_deciles,
            dependency_versions=_dependency_versions(),
            metric_sections={
                "discrimination": {
                    "effective_deciles_by_partition": effective_deciles,
                    "not_evaluable_reasons_by_partition": not_evaluable_reasons,
                    "threshold_flags_by_partition": threshold_flags,
                }
            },
        )
        result = PerformanceResult(
            performance_table=performance_table,
            discriminant_metrics=discriminant_metrics,
            performance_records=tuple(performance_records),
            discriminant_records=tuple(discriminant_records),
            card=card,
        )

        self.result_ = result
        self.performance_table_ = result.performance_table
        self.discriminant_metrics_ = result.discriminant_metrics
        self.performance_records_ = result.performance_records
        self.discriminant_records_ = result.discriminant_records
        self.card_ = result.card
        return result


@dataclass(frozen=True)
class SklearnMetrics:
    """Funciones de scikit-learn usadas por el evaluador."""

    roc_auc_score: Any
    roc_curve: Any


@dataclass(frozen=True)
class Evaluability:
    """Conteos y motivo de evaluación para una partición."""

    n_total: int
    n_bad: int
    n_good: int
    reason: str | None


@dataclass(frozen=True)
class DiscriminantComputation:
    """Métricas discriminantes ya calculadas para una partición evaluable."""

    auc: float
    gini: float
    ks: float
    ks_cutoff_risk_score: float
    ks_cutoff_score: float | None
    tpr_at_ks: float
    fpr_at_ks: float


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


def _import_sklearn_metrics() -> SklearnMetrics:
    """Importa métricas de scikit-learn bajo demanda."""
    try:
        metrics = importlib.import_module("sklearn.metrics")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return SklearnMetrics(
        roc_auc_score=metrics.roc_auc_score,
        roc_curve=metrics.roc_curve,
    )


def _validate_runtime_config(
    estimator: PerformanceEvaluator,
    *,
    score_column: str,
    pd_column: str,
    target_column: str,
    partition_column: str,
) -> PerformanceConfig:
    """Revalida hiperparámetros planos y columnas efectivas de ``evaluate``."""
    try:
        cfg = PerformanceConfig(
            score_column=score_column,
            pd_column=pd_column,
            target_column=target_column,
            partition_column=partition_column,
            score_direction=estimator.score_direction,
            evaluation_source=estimator.evaluation_source,
            partitions=tuple(estimator.partitions),
            n_deciles=estimator.n_deciles,
            min_rows_per_partition=estimator.min_rows_per_partition,
            min_events_per_partition=estimator.min_events_per_partition,
            optional_thresholds=dict(estimator.optional_thresholds),
        )
    except (ConfigError, TypeError, ValidationError) as exc:
        raise ConfigError(f"Hiperparámetros inválidos para PerformanceEvaluator: {exc}") from exc

    if len(set(cfg.partitions)) != len(cfg.partitions):
        raise ConfigError("PerformanceEvaluator requiere particiones sin duplicados.")
    return cfg


def _as_dataframe(df: object, pd: Any) -> DataFrame:
    """Valida y copia defensivamente una entrada tabular."""
    if not isinstance(df, pd.DataFrame):
        raise PerformanceDataError(
            "PerformanceEvaluator.evaluate requiere pandas.DataFrame; "
            f"tipo observado={type(df).__name__}."
        )
    return cast(DataFrame, df.copy(deep=True))


def _validate_input_schema(
    frame: DataFrame,
    *,
    cfg: PerformanceConfig,
    pd: Any,
    pa: Any,
) -> DataFrame:
    """Valida columnas, índice y no-nulos mínimos mediante checks propios y pandera."""
    del pd
    _validate_unique_columns(frame)
    if not frame.index.is_unique:
        raise PerformanceDataError("PerformanceEvaluator requiere índice único.")
    _validate_required_columns(frame, cfg=cfg)

    schema = pa.DataFrameSchema(
        {
            cfg.partition_column: pa.Column(nullable=False, required=True),
            cfg.target_column: pa.Column(nullable=False, required=True),
            cfg.score_column: pa.Column(nullable=False, required=True),
            cfg.pd_column: pa.Column(nullable=False, required=True),
        },
        strict=False,
    )
    try:
        validated = schema.validate(frame, lazy=True)
    except Exception as exc:
        if _is_pandera_schema_error(pa, exc):
            raise PerformanceDataError(
                "El frame de performance no cumple el esquema mínimo de SDD-11 §6."
            ) from exc
        raise
    return cast(DataFrame, validated.copy(deep=True))


def _is_pandera_schema_error(pa: Any, exc: Exception) -> bool:
    """Reconoce errores de pandera sin importar ``pandera`` en el top-level."""
    return isinstance(exc, (pa.errors.SchemaError, pa.errors.SchemaErrors))


def _validate_unique_columns(frame: DataFrame) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise PerformanceDataError(
            f"PerformanceEvaluator requiere nombres de columnas únicos; duplicadas: {joined}."
        )


def _validate_required_columns(frame: DataFrame, *, cfg: PerformanceConfig) -> None:
    """Valida presencia de columnas mínimas según configuración efectiva."""
    required = (
        cfg.partition_column,
        cfg.target_column,
        cfg.score_column,
        cfg.pd_column,
    )
    missing = [column for column in required if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise PerformanceDataError(f"performance frame no contiene columnas requeridas: {joined}.")


def _modelable_frame(frame: DataFrame, *, cfg: PerformanceConfig, pd: Any) -> DataFrame:
    """Filtra particiones configuradas y conserva una copia modelable."""
    del pd
    mask = frame[cfg.partition_column].isin(cfg.partitions)
    return frame.loc[mask].copy(deep=True)


def _prepare_modelable_frame(
    frame: DataFrame,
    *,
    cfg: PerformanceConfig,
    pd: Any,
    np: Any,
) -> DataFrame:
    """Convierte columnas numéricas, valida finitud y agrega ``risk_score`` interno."""
    prepared = frame.copy(deep=True)
    if len(prepared.index) == 0:
        prepared[_INTERNAL_RISK_COLUMN] = pd.Series(dtype="float64")
        prepared[_INTERNAL_INDEX_KEY_COLUMN] = pd.Series(dtype="object")
        return prepared

    target = _binary_target_array(prepared[cfg.target_column], column=cfg.target_column, np=np)
    score = _numeric_array(
        prepared[cfg.score_column],
        column=cfg.score_column,
        np=np,
        error_cls=PerformanceDataError,
    )
    calibrated_pd = _numeric_array(
        prepared[cfg.pd_column],
        column=cfg.pd_column,
        np=np,
        error_cls=PerformanceDataError,
    )
    invalid_pd = (calibrated_pd <= 0.0) | (calibrated_pd >= 1.0)
    if bool(invalid_pd.any()):
        observed = calibrated_pd[invalid_pd][0]
        raise PerformanceDataError(
            f"{cfg.pd_column} debe estar estrictamente en (0, 1): "
            f"valor observado={float(observed)!r}."
        )

    risk_score = _risk_score_array(score=score, calibrated_pd=calibrated_pd, cfg=cfg, np=np)
    prepared[cfg.target_column] = pd.Series(target, index=prepared.index, dtype="int64")
    prepared[cfg.score_column] = _float_series(score, index=prepared.index, pd=pd)
    prepared[cfg.pd_column] = _float_series(calibrated_pd, index=prepared.index, pd=pd)
    prepared[_INTERNAL_RISK_COLUMN] = _float_series(risk_score, index=prepared.index, pd=pd)
    prepared[_INTERNAL_INDEX_KEY_COLUMN] = [
        _index_sort_key(value) for value in prepared.index.tolist()
    ]
    return prepared


def _numeric_array(
    series: Series,
    *,
    column: str,
    np: Any,
    error_cls: type[Exception],
) -> NDArrayFloat:
    """Convierte una serie a ``float64`` finito antes de ordenar o comparar."""
    try:
        values = series.to_numpy(dtype="float64", copy=True)
    except (TypeError, ValueError) as exc:
        raise error_cls(f"La columna '{column}' debe ser numérica float64-compatible.") from exc
    finite = np.isfinite(values)
    if not bool(finite.all()):
        observed = values[~finite][0]
        raise error_cls(
            f"La columna '{column}' debe contener sólo valores finitos: "
            f"valor observado={float(observed)!r}."
        )
    return cast(NDArrayFloat, values)


def _binary_target_array(series: Series, *, column: str, np: Any) -> NDArrayInt:
    """Convierte target supervisado a 0/1 y rechaza valores ambiguos."""
    target = _numeric_array(series, column=column, np=np, error_cls=PerformanceDataError)
    valid_binary = (target == 0.0) | (target == 1.0)
    if not bool(valid_binary.all()):
        observed = target[~valid_binary][0]
        raise PerformanceDataError(
            f"El target '{column}' debe ser binario 0/1: valor observado={float(observed)!r}."
        )
    return cast(NDArrayInt, target.astype("int64", copy=False))


def _risk_score_array(
    *,
    score: NDArrayFloat,
    calibrated_pd: NDArrayFloat,
    cfg: PerformanceConfig,
    np: Any,
) -> NDArrayFloat:
    """Construye el ranking interno con orientación positiva hacia default."""
    if cfg.evaluation_source == "pd_calibrated":
        values = calibrated_pd
    elif cfg.score_direction == "higher_is_lower_risk":
        values = -score
    else:
        values = score
    return cast(NDArrayFloat, np.asarray(values, dtype="float64"))


def _float_series(values: NDArrayFloat, *, index: Any, pd: Any) -> Series:
    """Crea una serie float64 normalizada para publicar y ordenar."""
    return cast(
        Series,
        pd.Series(values, index=index, dtype="float64").map(_normalize_float).astype("float64"),
    )


def _index_sort_key(value: object) -> str:
    """Construye clave determinista de desempate a partir del índice original."""
    return f"{type(value).__name__}:{value!r}"


def _partition_frame(
    frame: DataFrame,
    *,
    cfg: PerformanceConfig,
    partition: str,
) -> DataFrame:
    """Extrae una partición con copia profunda y orden original intacto."""
    mask = frame[cfg.partition_column].eq(partition)
    return frame.loc[mask].copy(deep=True)


def _evaluability(frame: DataFrame, *, cfg: PerformanceConfig, np: Any) -> Evaluability:
    """Determina si una partición puede calcular métricas supervisadas."""
    n_total = len(frame.index)
    if n_total == 0:
        return Evaluability(n_total=0, n_bad=0, n_good=0, reason="partition_empty")

    target = frame[cfg.target_column].to_numpy(dtype="int64", copy=True)
    n_bad = int(target.sum())
    n_good = int(n_total - n_bad)
    classes = set(int(value) for value in np.unique(target).tolist())
    if classes != {0, 1}:
        return Evaluability(
            n_total=n_total,
            n_bad=n_bad,
            n_good=n_good,
            reason="single_class",
        )
    if n_total < cfg.min_rows_per_partition:
        return Evaluability(
            n_total=n_total,
            n_bad=n_bad,
            n_good=n_good,
            reason="below_min_rows",
        )
    if n_bad < cfg.min_events_per_partition:
        return Evaluability(
            n_total=n_total,
            n_bad=n_bad,
            n_good=n_good,
            reason="below_min_events",
        )
    return Evaluability(n_total=n_total, n_bad=n_bad, n_good=n_good, reason=None)


def _decile_records_for_partition(
    frame: DataFrame,
    *,
    cfg: PerformanceConfig,
    pd: Any,
    np: Any,
) -> tuple[list[DecilePerformanceRecord], int]:
    """Construye deciles/gains con ranking estable y tamaños uniformes."""
    n_total = len(frame.index)
    if n_total == 0:
        return [], 0

    sorted_frame = frame.sort_values(
        by=[_INTERNAL_RISK_COLUMN, _INTERNAL_INDEX_KEY_COLUMN],
        ascending=[False, True],
        kind="mergesort",
    ).copy(deep=True)
    effective_deciles = min(int(cfg.n_deciles), n_total)
    assignments = np.empty(n_total, dtype="int64")
    for decile, positions in enumerate(
        np.array_split(np.arange(n_total), effective_deciles),
        start=1,
    ):
        assignments[positions] = decile
    sorted_frame["decile"] = pd.Series(assignments, index=sorted_frame.index, dtype="int64")

    total_bad = int(sorted_frame[cfg.target_column].sum())
    total_good = int(n_total - total_bad)
    partition_bad_rate = _safe_divide(total_bad, n_total)

    records: list[DecilePerformanceRecord] = []
    cum_total = 0
    cum_bad = 0
    cum_good = 0
    for decile in range(1, effective_deciles + 1):
        bucket = sorted_frame.loc[sorted_frame["decile"].eq(decile)].copy(deep=True)
        bucket_total = len(bucket.index)
        bucket_bad = int(bucket[cfg.target_column].sum())
        bucket_good = int(bucket_total - bucket_bad)
        cum_total += bucket_total
        cum_bad += bucket_bad
        cum_good += bucket_good

        bad_rate = _safe_divide(bucket_bad, bucket_total)
        good_rate = _safe_divide(bucket_good, bucket_total)
        cum_bad_capture_rate = _safe_divide(cum_bad, total_bad)
        cum_good_capture_rate = _safe_divide(cum_good, total_good)
        lift = _safe_divide(bad_rate, partition_bad_rate)
        ks_at_decile = (
            abs(cum_bad_capture_rate - cum_good_capture_rate)
            if total_bad > 0 and total_good > 0
            else 0.0
        )

        records.append(
            DecilePerformanceRecord(
                partition=str(bucket[cfg.partition_column].iloc[0]),
                decile=decile,
                n_total=bucket_total,
                n_bad=bucket_bad,
                n_good=bucket_good,
                bad_rate=bad_rate,
                good_rate=good_rate,
                mean_pd=_series_stat(bucket[cfg.pd_column], "mean"),
                min_pd=_series_stat(bucket[cfg.pd_column], "min"),
                max_pd=_series_stat(bucket[cfg.pd_column], "max"),
                mean_score=_series_stat(bucket[cfg.score_column], "mean"),
                min_score=_series_stat(bucket[cfg.score_column], "min"),
                max_score=_series_stat(bucket[cfg.score_column], "max"),
                cum_total=cum_total,
                cum_bad=cum_bad,
                cum_good=cum_good,
                cum_bad_capture_rate=cum_bad_capture_rate,
                cum_good_capture_rate=cum_good_capture_rate,
                lift=lift,
                ks_at_decile=ks_at_decile,
            )
        )
    return records, effective_deciles


def _series_stat(series: Series, stat: str) -> float:
    """Calcula un estadístico escalar finito de una serie numérica validada."""
    if stat == "mean":
        value = float(series.mean())
    elif stat == "min":
        value = float(series.min())
    else:
        value = float(series.max())
    if not math.isfinite(value):
        raise PerformanceMetricError(f"El estadístico {stat} produjo un valor no finito.")
    return _normalize_float(value)


def _compute_discriminant_metrics(
    frame: DataFrame,
    *,
    cfg: PerformanceConfig,
    sklearn_metrics: SklearnMetrics,
    np: Any,
) -> DiscriminantComputation:
    """Calcula AUC/Gini/KS con scikit-learn y cortes finitos."""
    target = frame[cfg.target_column].to_numpy(dtype="int64", copy=True)
    risk_score = frame[_INTERNAL_RISK_COLUMN].to_numpy(dtype="float64", copy=True)
    try:
        auc = _normalize_float(float(sklearn_metrics.roc_auc_score(target, risk_score)))
        fpr, tpr, thresholds = sklearn_metrics.roc_curve(target, risk_score)
    except Exception as exc:
        raise PerformanceMetricError(f"No se pudieron calcular métricas ROC/AUC: {exc}") from exc

    finite_thresholds = np.isfinite(thresholds)
    if not bool(finite_thresholds.any()):
        raise PerformanceMetricError("roc_curve no produjo cortes finitos para KS.")

    fpr_finite = fpr[finite_thresholds]
    tpr_finite = tpr[finite_thresholds]
    thresholds_finite = thresholds[finite_thresholds]
    ks_values = np.abs(tpr_finite - fpr_finite)
    position = int(np.argmax(ks_values))
    ks = _normalize_float(float(ks_values[position]))
    risk_cutoff = _normalize_float(float(thresholds_finite[position]))
    score_cutoff = _score_cutoff_from_risk(risk_cutoff, cfg=cfg)
    return DiscriminantComputation(
        auc=auc,
        gini=_normalize_float((2.0 * auc) - 1.0),
        ks=ks,
        ks_cutoff_risk_score=risk_cutoff,
        ks_cutoff_score=score_cutoff,
        tpr_at_ks=_normalize_float(float(tpr_finite[position])),
        fpr_at_ks=_normalize_float(float(fpr_finite[position])),
    )


def _score_cutoff_from_risk(risk_cutoff: float, *, cfg: PerformanceConfig) -> float | None:
    """Traduce el corte de ``risk_score`` a score operacional cuando aplica."""
    if cfg.evaluation_source != "score":
        return None
    if cfg.score_direction == "higher_is_lower_risk":
        return _normalize_float(-risk_cutoff)
    return _normalize_float(risk_cutoff)


def _threshold_flags_for(
    computed: DiscriminantComputation,
    thresholds: Mapping[str, float],
) -> list[str]:
    """Detecta cruces de umbrales mínimos institucionales."""
    flags: list[str] = []
    for metric_name, threshold_key in _METRIC_THRESHOLD_KEYS.items():
        threshold = thresholds.get(threshold_key)
        if threshold is None:
            continue
        value = getattr(computed, metric_name)
        if value < threshold:
            flags.append(metric_name)
    return flags


def _not_evaluable_record(
    *,
    partition: str,
    counts: Evaluability,
    source: EvaluationSource,
) -> DiscriminantMetricRecord:
    """Construye fila de métricas ``not_evaluable`` sin floats opcionales."""
    return DiscriminantMetricRecord(
        partition=partition,
        n_total=counts.n_total,
        n_bad=counts.n_bad,
        n_good=counts.n_good,
        auc=None,
        gini=None,
        ks=None,
        ks_cutoff_risk_score=None,
        ks_cutoff_score=None,
        tpr_at_ks=None,
        fpr_at_ks=None,
        source=source,
        status="not_evaluable",
    )


def _discriminant_record_from_metrics(
    *,
    partition: str,
    counts: Evaluability,
    computed: DiscriminantComputation,
    source: EvaluationSource,
    status: str,
) -> DiscriminantMetricRecord:
    """Construye fila evaluable de ``discriminant_metrics``."""
    return DiscriminantMetricRecord(
        partition=partition,
        n_total=counts.n_total,
        n_bad=counts.n_bad,
        n_good=counts.n_good,
        auc=computed.auc,
        gini=computed.gini,
        ks=computed.ks,
        ks_cutoff_risk_score=computed.ks_cutoff_risk_score,
        ks_cutoff_score=computed.ks_cutoff_score,
        tpr_at_ks=computed.tpr_at_ks,
        fpr_at_ks=computed.fpr_at_ks,
        source=source,
        status=cast(Any, status),
    )


def _records_to_frame(
    records: list[DecilePerformanceRecord] | list[DiscriminantMetricRecord],
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


def _metrics_by_partition(
    records: list[DiscriminantMetricRecord],
) -> dict[str, dict[str, float | None]]:
    """Resume AUC/Gini/KS por partición para la card."""
    return {
        record.partition: {"auc": record.auc, "gini": record.gini, "ks": record.ks}
        for record in records
    }


def _dependency_versions() -> dict[str, str]:
    """Publica versiones de dependencias usadas por el evaluator."""
    modules: dict[str, str] = {
        "numpy": "numpy",
        "pandas": "pandas",
        "scikit-learn": "sklearn",
    }
    versions: dict[str, str] = {}
    for public_name, module_name in modules.items():
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
        versions[public_name] = str(getattr(module, "__version__", "unknown"))
    return {name: versions[name] for name in sorted(versions)}


def _safe_divide(numerator: float, denominator: float) -> float:
    """Divide sin warnings ni infinito; devuelve ``0.0`` si el denominador es cero."""
    if denominator == 0:
        return 0.0
    return _normalize_float(float(numerator) / float(denominator))


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` sin redondear otros valores."""
    observed = float(value)
    if observed == 0.0:
        return 0.0
    return observed
