"""Consumo y reúso de la estabilidad (PSI) de la validación avanzada (SDD-22 §3.3/§7).

La capa ``validation`` **no** recalcula el PSI: SDD-11 es la fuente canónica. Este módulo resuelve
la familia ``stability`` de dos maneras, sin reimplementar jamás la fórmula del PSI:

* **Consumo** -- cuando el modelo trae el artefacto ``("stability","stability_metrics")``, cada
  fila se proyecta al frame tidy ``stability`` de §6 con ``source="stability_artifact"``; el valor
  del PSI se copia *verbatim* y sólo se mapea a un verdicto de estabilidad por bandas.
* **Fallback (reúso)** -- cuando el modelo no tiene paquete ``stability``, se **reúsa**
  ``StabilityEvaluator.evaluate(...)`` de SDD-11 y se proyecta su ``stability_metrics``, con
  ``source="recomputed"``. El evaluador es la ÚNICA vía de cálculo del PSI: aquí sólo se clasifica
  un valor ya computado.

**Mapeo de bandas (SDD-22 §3.3).** El valor del PSI ``v`` se mapea a un verdicto con los umbrales
configurados (defaults 0.10/0.25, idénticos a SDD-11/ESPEC §5.2): ``v < stable`` estable/``pass``,
``stable <= v < review`` vigilar/``warn``, ``v >= review`` redesarrollar/``fail``. La convención de
bordes replica ``_band`` de SDD-11 (``stable`` inclusivo hacia ``review``, ``review`` inclusivo
hacia ``redevelop``) para que validación coincida con SDD-11 cuando los umbrales coinciden. Un valor
no finito/ausente es ``not_evaluable``. El PSI (``v``) nunca se recomputa: sólo se clasifica; por
eso los umbrales configurables tienen efecto sin violar el contrato de "no reimplementar PSI".

El import de ``StabilityEvaluator`` es **perezoso** (dentro de la rama de fallback) para no acoplar
el import de ``nikodym.validation`` al grafo de ``stability``/scikit-learn y preservar el núcleo
liviano (SDD-22 §10). ``pandas`` es dependencia base y se importa al tope. Las entradas se copian de
forma defensiva (``copy(deep=True)``): nunca se mutan los artefactos/frames aguas arriba. Los floats
publicados normalizan ``-0.0`` a ``0.0``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Literal, TypeAlias

import pandas as pd

from nikodym.validation.config import StabilityValidationConfig
from nikodym.validation.exceptions import ValidationDataError

StabilityBandValue: TypeAlias = Literal["stable", "review", "redevelop", "not_evaluable"]
StabilityActionValue: TypeAlias = Literal["none", "vigilar", "redesarrollar"]
StabilityDecisionValue: TypeAlias = Literal["pass", "warn", "fail", "not_evaluable"]
StabilitySourceValue: TypeAlias = Literal["stability_artifact", "recomputed"]
StabilityStatusValue: TypeAlias = Literal["ok", "not_evaluable"]

__all__ = [
    "evaluate_stability",
    "stability_from_artifact",
    "stability_recomputed",
]

# Columnas de ``stability_metrics`` (SDD-11 §6) que consume la validación.
_ARTIFACT_INPUT_COLUMNS: tuple[str, ...] = ("metric", "comparison", "feature", "value")
# Columnas del frame tidy ``stability`` que publica la validación (SDD-22 §6).
_STABILITY_OUTPUT_COLUMNS: tuple[str, ...] = (
    "metric",
    "comparison",
    "feature",
    "value",
    "stable_threshold",
    "review_threshold",
    "band",
    "action",
    "source",
    "status",
    "decision",
)
# Mapa banda -> acción auditada (idéntico a SDD-11 §6/§8: una banda fija su única acción).
_ACTION_BY_BAND: dict[StabilityBandValue, StabilityActionValue] = {
    "stable": "none",
    "review": "vigilar",
    "redevelop": "redesarrollar",
    "not_evaluable": "none",
}
# Mapa banda -> verdicto de estabilidad de validación (alimenta overall_status pass/warn/fail).
_DECISION_BY_BAND: dict[StabilityBandValue, StabilityDecisionValue] = {
    "stable": "pass",
    "review": "warn",
    "redevelop": "fail",
    "not_evaluable": "not_evaluable",
}


def stability_from_artifact(
    stability_metrics: pd.DataFrame,
    *,
    stable_threshold: float = 0.10,
    review_threshold: float = 0.25,
) -> pd.DataFrame:
    """Proyecta ``stability_metrics`` de SDD-11 al frame tidy ``stability`` (consumo; SDD-22 §7).

    Copia el artefacto de forma defensiva, conserva el valor del PSI *verbatim* y le añade el
    verdicto de estabilidad por bandas (``band``/``action``/``decision``), la procedencia
    ``source="stability_artifact"`` y el ``status``. El PSI nunca se recomputa.
    """
    return _map_stability_metrics(
        stability_metrics,
        source="stability_artifact",
        stable_threshold=stable_threshold,
        review_threshold=review_threshold,
    )


def stability_recomputed(
    frame: pd.DataFrame,
    *,
    score_column: str = "score",
    pd_column: str = "pd_calibrated",
    partition_column: str = "partition",
    feature_point_columns: Sequence[str] = (),
    stable_threshold: float = 0.10,
    review_threshold: float = 0.25,
    evaluator_kwargs: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Reúsa ``StabilityEvaluator`` de SDD-11 y proyecta su salida (fallback; SDD-22 §7/§10).

    Para un modelo sin paquete ``stability`` se **reúsa** ``StabilityEvaluator.evaluate(...)``: el
    evaluador de SDD-11 es la única vía de cálculo del PSI (jamás se reimplementa aquí). El import
    de ``StabilityEvaluator`` es perezoso, sólo en este fallback, para no romper el núcleo liviano.
    Su ``stability_metrics`` se proyecta con ``source="recomputed"`` idéntico al camino de consumo.
    ``evaluator_kwargs`` reenvía knobs adicionales del evaluador (p. ej. ``comparisons``,
    ``psi_bins``, ``temporal_axis``); no debe repetir los argumentos ya explícitos.
    """
    stable, review = _validate_thresholds(stable_threshold, review_threshold)
    # Import perezoso SOLO en el fallback: no acoplar el import de validation a stability/sklearn.
    from nikodym.stability.evaluator import StabilityEvaluator

    kwargs = dict(evaluator_kwargs or {})
    evaluator = StabilityEvaluator(
        score_column=score_column,
        pd_column=pd_column,
        partition_column=partition_column,
        psi_stable_threshold=stable,
        psi_review_threshold=review,
        **kwargs,
    )
    result = evaluator.evaluate(
        frame,
        score_column=score_column,
        pd_column=pd_column,
        partition_column=partition_column,
        feature_point_columns=tuple(feature_point_columns),
    )
    return _map_stability_metrics(
        result.stability_metrics,
        source="recomputed",
        stable_threshold=stable,
        review_threshold=review,
    )


def evaluate_stability(
    cfg: StabilityValidationConfig,
    *,
    stability_metrics: pd.DataFrame | None = None,
    frame: pd.DataFrame | None = None,
    score_column: str = "score",
    pd_column: str = "pd_calibrated",
    partition_column: str = "partition",
    feature_point_columns: Sequence[str] = (),
    evaluator_kwargs: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Resuelve la familia ``stability`` según ``cfg`` y los artefactos presentes (SDD-22 §7).

    Con ``cfg.consume_stability`` y el artefacto ``stability_metrics`` presente, **consume**
    (``stability_from_artifact``). En caso contrario cae al **fallback** por reúso
    (``stability_recomputed``) sobre el frame analítico; si tampoco hay frame, es un error de datos
    ruidoso (nada que consumir ni reúsar). Usa siempre los umbrales PSI de ``cfg``.
    """
    if cfg.consume_stability and stability_metrics is not None:
        return stability_from_artifact(
            stability_metrics,
            stable_threshold=cfg.psi_stable_threshold,
            review_threshold=cfg.psi_review_threshold,
        )
    if frame is None:
        raise ValidationDataError(
            "La estabilidad por fallback (reúso de StabilityEvaluator) exige el frame analítico: "
            "no hay artefacto stability_metrics consumible ni frame."
        )
    return stability_recomputed(
        frame,
        score_column=score_column,
        pd_column=pd_column,
        partition_column=partition_column,
        feature_point_columns=feature_point_columns,
        stable_threshold=cfg.psi_stable_threshold,
        review_threshold=cfg.psi_review_threshold,
        evaluator_kwargs=evaluator_kwargs,
    )


def _map_stability_metrics(
    stability_metrics: pd.DataFrame,
    *,
    source: StabilitySourceValue,
    stable_threshold: float,
    review_threshold: float,
) -> pd.DataFrame:
    """Proyecta ``stability_metrics`` al frame tidy ``stability`` mapeando bandas (SDD-22 §6/§7)."""
    stable, review = _validate_thresholds(stable_threshold, review_threshold)
    frame = _validate_metrics_frame(stability_metrics)
    columns = {name: frame[name].tolist() for name in _ARTIFACT_INPUT_COLUMNS}
    data: dict[str, list[Any]] = {name: [] for name in _STABILITY_OUTPUT_COLUMNS}
    for metric_value, comparison_value, feature_value, raw_value in zip(
        columns["metric"],
        columns["comparison"],
        columns["feature"],
        columns["value"],
        strict=True,
    ):
        value = _optional_value(raw_value)
        band = _band_for_value(value, stable_threshold=stable, review_threshold=review)
        status: StabilityStatusValue = "not_evaluable" if band == "not_evaluable" else "ok"
        data["metric"].append(str(metric_value))
        data["comparison"].append(str(comparison_value))
        data["feature"].append(str(feature_value))
        data["value"].append(math.nan if value is None else value)
        data["stable_threshold"].append(stable)
        data["review_threshold"].append(review)
        data["band"].append(band)
        data["action"].append(_ACTION_BY_BAND[band])
        data["source"].append(source)
        data["status"].append(status)
        data["decision"].append(_DECISION_BY_BAND[band])
    result = pd.DataFrame(data, columns=list(_STABILITY_OUTPUT_COLUMNS))
    return _normalize_float_columns(result)


def _band_for_value(
    value: float | None, *, stable_threshold: float, review_threshold: float
) -> StabilityBandValue:
    """Clasifica un PSI ya computado en una banda (convención de bordes de SDD-11 ``_band``)."""
    if value is None:
        return "not_evaluable"
    if value < stable_threshold:
        return "stable"
    if value < review_threshold:
        return "review"
    return "redevelop"


def _optional_value(value: Any) -> float | None:
    """Convierte un valor de PSI a float finito normalizado o ``None`` si es ausente/no finito."""
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return _normalize_float(number)


def _validate_thresholds(stable_threshold: float, review_threshold: float) -> tuple[float, float]:
    """Valida y normaliza los umbrales PSI: finitos, no negativos y ``stable < review``."""
    stable = float(stable_threshold)
    review = float(review_threshold)
    if not math.isfinite(stable) or not math.isfinite(review):
        raise ValidationDataError("Los umbrales PSI deben ser números finitos.")
    if stable < 0.0 or review < 0.0:
        raise ValidationDataError("Los umbrales PSI no pueden ser negativos.")
    if not stable < review:
        raise ValidationDataError(
            "psi_stable_threshold debe ser estrictamente menor que psi_review_threshold; "
            f"stable={stable!r}, review={review!r}."
        )
    return _normalize_float(stable), _normalize_float(review)


def _validate_metrics_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Copia y valida ``stability_metrics``: DataFrame con las columnas mínimas de §6."""
    if not isinstance(frame, pd.DataFrame):
        raise ValidationDataError(
            "El consumo de estabilidad requiere un pandas.DataFrame; "
            f"tipo observado={type(frame).__name__}."
        )
    copied = frame.copy(deep=True)
    missing = [name for name in _ARTIFACT_INPUT_COLUMNS if name not in copied.columns]
    if missing:
        raise ValidationDataError(
            f"El artefacto stability_metrics no contiene columnas requeridas: {missing}."
        )
    return copied


def _normalize_float_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Normaliza ``-0.0`` a ``0.0`` sólo en columnas float, preservando ``NaN``."""
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        series = copied[column]
        zero_mask = series == 0.0
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` sin alterar los demás valores."""
    number = float(value)
    if number == 0.0:
        return 0.0
    return number
