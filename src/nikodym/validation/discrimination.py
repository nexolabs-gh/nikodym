"""Consumo y reúso de la discriminación (AUC/Gini/KS) de la validación avanzada (SDD-22 §3.1/§7).

La capa ``validation`` **no** recalcula AUC/Gini/KS: SDD-11 es la fuente canónica. Este módulo
resuelve la familia ``discrimination`` de dos maneras, sin reimplementar jamás la fórmula:

* **Consumo** -- cuando el modelo trae el artefacto ``("performance","discriminant_metrics")``, cada
  fila se proyecta a un :class:`~nikodym.validation.results.DiscriminationRecord` con
  ``source="performance_artifact"``; los números (AUC/Gini/KS) se copian *verbatim* del artefacto.
* **Fallback (reúso)** -- cuando el modelo no tiene paquete ``performance`` (p. ej. un modelo
  ``ml`` de SDD-12), se **reúsa** ``PerformanceEvaluator.evaluate(...)`` de SDD-11 sobre
  ``(pd_calibrated, target, partition)`` con ``source="recomputed"``. El evaluador es la ÚNICA vía
  de cálculo: nunca se llama ``roc_auc_score``/``roc_curve`` ni se reimplementa KS/Gini aquí.

El import de ``PerformanceEvaluator`` es **perezoso** (dentro de la rama de fallback) para no
acoplar el import de ``nikodym.validation`` al grafo de ``performance``/scikit-learn y preservar el
núcleo liviano (SDD-22 §10). ``pandas`` es dependencia base y se importa al tope. Las entradas se
copian de forma defensiva (``copy(deep=True)``): nunca se mutan los artefactos/frames aguas arriba.

Una partición con una sola clase en el target (o bajo el mínimo técnico) queda ``not_evaluable`` con
``auc=None`` (§8): en el consumo se lee el estado del artefacto y en el fallback lo decide el
``PerformanceEvaluator``. Los floats los normaliza (``-0.0`` -> ``0.0``) el propio
``DiscriminationRecord``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, TypeAlias

import pandas as pd

from nikodym.validation.config import DiscriminationPartition, DiscriminationValidationConfig
from nikodym.validation.exceptions import ValidationDataError
from nikodym.validation.results import DiscriminationRecord

if TYPE_CHECKING:
    from nikodym.performance.results import DiscriminantMetricRecord

DiscriminationSourceValue: TypeAlias = Literal["performance_artifact", "recomputed"]
DiscriminationStatusValue: TypeAlias = Literal["ok", "not_evaluable"]

__all__ = [
    "discrimination_from_artifact",
    "discrimination_recomputed",
    "evaluate_discrimination",
]

# Particiones por defecto de la familia de discriminación (SDD-22 §5).
_DEFAULT_PARTITIONS: tuple[DiscriminationPartition, ...] = ("desarrollo", "holdout", "oot")
# Columnas de ``discriminant_metrics`` (SDD-11 §6) que proyecta el DiscriminationRecord.
_ARTIFACT_INPUT_COLUMNS: tuple[str, ...] = (
    "partition",
    "n_total",
    "n_bad",
    "auc",
    "gini",
    "ks",
    "status",
)
# Estado de performance -> estado de discriminación de validación (un ``threshold_flag`` sigue
# siendo evaluable: sólo marca un umbral institucional, no vuelve ``not_evaluable`` la partición).
_STATUS_MAP: dict[str, DiscriminationStatusValue] = {
    "ok": "ok",
    "threshold_flag": "ok",
    "not_evaluable": "not_evaluable",
}
# Columna de score sintética del fallback: ``PerformanceEvaluator`` exige la columna aunque, con
# ``evaluation_source="pd_calibrated"``, el ranking sea la PD calibrada (el score no altera AUC/KS).
_SYNTHETIC_SCORE_COLUMN: str = "__nikodym_validation_score__"


def discrimination_from_artifact(
    discriminant_metrics: pd.DataFrame,
    *,
    partitions: Sequence[str] | None = None,
) -> list[DiscriminationRecord]:
    """Proyecta ``discriminant_metrics`` de SDD-11 a DiscriminationRecords (consumo; SDD-22 §7).

    Copia el artefacto de forma defensiva y, en su orden de aparición, proyecta cada partición a un
    :class:`~nikodym.validation.results.DiscriminationRecord` con ``source="performance_artifact"``;
    los números (AUC/Gini/KS) se copian *verbatim*, sin recálculo. Con ``partitions`` se filtra al
    subconjunto pedido (conservando el orden del artefacto); ``None`` reporta todas las presentes.
    ``threshold_flag`` se colapsa a ``ok`` y ``not_evaluable`` se conserva con ``auc=None``.
    """
    frame = _validate_artifact_frame(discriminant_metrics)
    requested = set(partitions) if partitions is not None else None
    columns = {name: frame[name].tolist() for name in _ARTIFACT_INPUT_COLUMNS}
    records: list[DiscriminationRecord] = []
    for (
        partition_value,
        n_total_value,
        n_bad_value,
        auc_value,
        gini_value,
        ks_value,
        status_value,
    ) in zip(
        columns["partition"],
        columns["n_total"],
        columns["n_bad"],
        columns["auc"],
        columns["gini"],
        columns["ks"],
        columns["status"],
        strict=True,
    ):
        partition = str(partition_value)
        if requested is not None and partition not in requested:
            continue
        records.append(
            DiscriminationRecord(
                partition=partition,
                n_total=int(n_total_value),
                n_bad=int(n_bad_value),
                auc=auc_value,
                gini=gini_value,
                ks=ks_value,
                source="performance_artifact",
                status=_map_status(str(status_value)),
            )
        )
    return records


def discrimination_recomputed(
    frame: pd.DataFrame,
    *,
    pd_column: str = "pd_calibrated",
    target_column: str = "target",
    partition_column: str = "partition",
    partitions: Sequence[DiscriminationPartition] = _DEFAULT_PARTITIONS,
    min_rows_per_partition: int = 30,
    min_events_per_partition: int = 1,
) -> list[DiscriminationRecord]:
    """Reúsa ``PerformanceEvaluator`` de SDD-11 y proyecta su salida (fallback; SDD-22 §7/§10).

    Para un modelo sin paquete ``performance`` se **reúsa** ``PerformanceEvaluator.evaluate(...)``
    sobre ``(pd_calibrated, target, partition)`` con ``evaluation_source="pd_calibrated"``: el
    evaluador de SDD-11 es la única vía de cálculo de AUC/Gini/KS (jamás se reimplementan aquí). El
    import de ``PerformanceEvaluator`` es perezoso, sólo en este fallback, para no romper el núcleo
    liviano. Cada ``DiscriminantMetricRecord`` se proyecta con ``source="recomputed"``; los estados
    ``not_evaluable`` (una sola clase, bajo mínimo, partición vacía) llegan con ``auc=None``.
    """
    work = _validate_source_frame(
        frame,
        columns=(pd_column, target_column, partition_column),
        caller="discrimination_recomputed",
    )
    # Import perezoso SOLO en el fallback: no acoplar el import de validation a performance/sklearn.
    from nikodym.performance.evaluator import PerformanceEvaluator

    if _SYNTHETIC_SCORE_COLUMN in work.columns:
        raise ValidationDataError(
            f"El frame no puede contener la columna reservada '{_SYNTHETIC_SCORE_COLUMN}'."
        )
    work[_SYNTHETIC_SCORE_COLUMN] = work[pd_column]
    evaluator = PerformanceEvaluator(
        score_column=_SYNTHETIC_SCORE_COLUMN,
        pd_column=pd_column,
        target_column=target_column,
        partition_column=partition_column,
        evaluation_source="pd_calibrated",
        partitions=tuple(partitions),
        min_rows_per_partition=min_rows_per_partition,
        min_events_per_partition=min_events_per_partition,
    )
    result = evaluator.evaluate(
        work,
        score_column=_SYNTHETIC_SCORE_COLUMN,
        pd_column=pd_column,
        target_column=target_column,
        partition_column=partition_column,
    )
    return [_record_from_metric(record) for record in result.discriminant_records]


def evaluate_discrimination(
    cfg: DiscriminationValidationConfig,
    *,
    performance_metrics: pd.DataFrame | None = None,
    calibrated_frame: pd.DataFrame | None = None,
    pd_column: str = "pd_calibrated",
    target_column: str = "target",
    partition_column: str = "partition",
) -> list[DiscriminationRecord]:
    """Resuelve la familia ``discrimination`` según ``cfg`` y los artefactos presentes (SDD-22 §7).

    Con ``cfg.consume_performance`` y el artefacto ``discriminant_metrics`` presente, **consume**
    (``discrimination_from_artifact``). En caso contrario cae al **fallback** por reúso
    (``discrimination_recomputed``) sobre el frame de PD calibrada; si tampoco hay frame, es un
    error de datos ruidoso (nada que consumir ni reúsar).
    """
    if cfg.consume_performance and performance_metrics is not None:
        return discrimination_from_artifact(performance_metrics, partitions=cfg.partitions)
    if calibrated_frame is None:
        raise ValidationDataError(
            "La discriminación por fallback (reúso de PerformanceEvaluator) exige el frame de PD "
            "calibrada: no hay artefacto discriminant_metrics consumible ni calibrated_frame."
        )
    return discrimination_recomputed(
        calibrated_frame,
        pd_column=pd_column,
        target_column=target_column,
        partition_column=partition_column,
        partitions=cfg.partitions,
    )


def _record_from_metric(record: DiscriminantMetricRecord) -> DiscriminationRecord:
    """Proyecta un ``DiscriminantMetricRecord`` de SDD-11 a un DiscriminationRecord recomputado."""
    status: DiscriminationStatusValue = (
        "not_evaluable" if record.status == "not_evaluable" else "ok"
    )
    return DiscriminationRecord(
        partition=record.partition,
        n_total=record.n_total,
        n_bad=record.n_bad,
        auc=record.auc,
        gini=record.gini,
        ks=record.ks,
        source="recomputed",
        status=status,
    )


def _map_status(raw: str) -> DiscriminationStatusValue:
    """Traduce el estado de ``discriminant_metrics`` al estado de discriminación de validación."""
    try:
        return _STATUS_MAP[raw]
    except KeyError as exc:
        raise ValidationDataError(
            f"Estado de discriminación desconocido en el artefacto: {raw!r}."
        ) from exc


def _validate_artifact_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Copia y valida el artefacto ``discriminant_metrics``: DataFrame con las columnas de §6."""
    if not isinstance(frame, pd.DataFrame):
        raise ValidationDataError(
            "discrimination_from_artifact requiere un pandas.DataFrame; "
            f"tipo observado={type(frame).__name__}."
        )
    copied = frame.copy(deep=True)
    missing = [name for name in _ARTIFACT_INPUT_COLUMNS if name not in copied.columns]
    if missing:
        raise ValidationDataError(
            f"El artefacto discriminant_metrics no contiene columnas requeridas: {missing}."
        )
    return copied


def _validate_source_frame(
    frame: pd.DataFrame, *, columns: tuple[str, ...], caller: str
) -> pd.DataFrame:
    """Copia y valida el frame de PD calibrada: DataFrame con las columnas declaradas."""
    if not isinstance(frame, pd.DataFrame):
        raise ValidationDataError(
            f"{caller} requiere un pandas.DataFrame; tipo observado={type(frame).__name__}."
        )
    copied = frame.copy(deep=True)
    missing = [name for name in columns if name not in copied.columns]
    if missing:
        raise ValidationDataError(
            f"El frame de discriminación no contiene columnas requeridas: {missing}."
        )
    return copied
