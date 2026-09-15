"""Consumo y reúso de la estabilidad (PSI) de la validación avanzada (SDD-22 §3.3/§7).

La capa ``validation`` **no** recalcula el PSI: SDD-11 es la fuente canónica. Este módulo resuelve
la familia ``stability`` de dos maneras, sin reimplementar jamás la fórmula del PSI:

* **Consumo** -- con ``consume_stability=True`` el paso lee el artefacto
  ``("stability","stability_metrics")`` y cada fila se proyecta al frame tidy ``stability`` de §6
  con ``source="stability_artifact"``; el valor del PSI se copia *verbatim* y sólo se mapea a un
  verdicto de estabilidad por bandas.
* **Recálculo (reúso)** -- con ``consume_stability=False`` el paso **reúsa**
  :func:`nikodym.stability.step.compute_stability` —el mismo ensamblador y el mismo
  ``StabilityEvaluator`` que corre el paso de estabilidad, por la misma llamada (D-VAL-16)— y
  proyecta su ``stability_metrics`` aquí con ``source="recomputed"``. El evaluador de SDD-11 es la
  ÚNICA vía de cálculo del PSI: este módulo sólo clasifica un valor ya computado, venga de donde
  venga. Hasta la capa C de VALIDACION-COTEJADA existía un segundo camino,
  ``stability_recomputed(frame, **kwargs)``, que construía el evaluador con kwargs sueltos y sin
  las columnas del CSI; se retiró para que no haya dos formas de recalcular.

**Mapeo de bandas (SDD-22 §3.3).** El valor del PSI ``v`` se mapea a un verdicto con los umbrales
configurados (defaults 0.10/0.25, idénticos a SDD-11/ESPEC §5.2): ``v < stable`` estable/``pass``,
``stable <= v < review`` vigilar/``warn``, ``v >= review`` redesarrollar/``fail``. La convención de
bordes replica ``_band`` de SDD-11 (``stable`` inclusivo hacia ``review``, ``review`` inclusivo
hacia ``redevelop``) para que validación coincida con SDD-11 cuando los umbrales coinciden. Un valor
no finito/ausente es ``not_evaluable``. El PSI (``v``) nunca se recomputa: sólo se clasifica; por
eso los umbrales configurables tienen efecto sin violar el contrato de "no reimplementar PSI".

Este módulo no importa ``nikodym.stability``: el recálculo lo lanza el paso, que importa
``compute_stability`` de forma perezosa dentro de ``execute`` para no acoplar el import de
``nikodym.validation`` al grafo de ``stability``/scikit-learn y preservar el núcleo liviano (SDD-22
§10). ``pandas`` es dependencia base y se importa al tope. Las entradas se copian de forma
defensiva (``copy(deep=True)``): nunca se mutan los artefactos/frames aguas arriba. Los floats
publicados normalizan ``-0.0`` a ``0.0``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import math
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
    source: StabilitySourceValue = "stability_artifact",
    stable_threshold: float = 0.10,
    review_threshold: float = 0.25,
) -> pd.DataFrame:
    """Proyecta un ``stability_metrics`` de SDD-11 al frame tidy ``stability`` (SDD-22 §7).

    Copia el artefacto de forma defensiva, conserva el valor del PSI *verbatim* y le añade el
    verdicto de estabilidad por bandas (``band``/``action``/``decision``), la procedencia
    ``source`` y el ``status``. El PSI nunca se recomputa aquí: ``source`` dice de dónde salió el
    frame —el artefacto del paso de estabilidad, o el recálculo con el mismo motor que hace
    ``compute_stability`` (D-VAL-16)—, y la proyección es idéntica en los dos casos.
    """
    return _map_stability_metrics(
        stability_metrics,
        source=source,
        stable_threshold=stable_threshold,
        review_threshold=review_threshold,
    )


def evaluate_stability(
    cfg: StabilityValidationConfig,
    stability_metrics: pd.DataFrame,
    *,
    source: StabilitySourceValue,
) -> pd.DataFrame:
    """Proyecta la familia ``stability`` con los umbrales PSI de ``cfg`` (SDD-22 §7).

    ``source`` la decide el paso: ``"stability_artifact"`` cuando consumió el artefacto
    (``cfg.consume_stability``), ``"recomputed"`` cuando recalculó con ``compute_stability``. Este
    despachador no acepta la combinación contraria a la config —consumir con el toggle apagado, o
    declarar recálculo con el toggle encendido—, porque el frame diría una procedencia que la
    config no autorizó (D-VAL-16: sin tercer estado implícito).
    """
    esperada: StabilitySourceValue = "stability_artifact" if cfg.consume_stability else "recomputed"
    if source != esperada:
        raise ValidationDataError(
            f"La estabilidad llega con source={source!r} y consume_stability="
            f"{cfg.consume_stability!r} exige {esperada!r}: el paso consumió o recalculó al revés "
            "de lo configurado."
        )
    return stability_from_artifact(
        stability_metrics,
        source=source,
        stable_threshold=cfg.psi_stable_threshold,
        review_threshold=cfg.psi_review_threshold,
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
