"""Serialización read-only de una corrida a JSON transportable (SDD-23 §4.3, §6).

Esta capa **solo formatea** lo que el motor ya materializó: nunca recalcula un número. Toma el
``ModelCard`` consolidado (vía :class:`~nikodym.governance.ModelCardBuilder`) y las *cards* por
dominio publicadas en ``study.artifacts``, y las proyecta a estructuras JSON puras. Es **lógica
pura**, testeable sin FastAPI, y *domain-agnostic*: no importa módulos de dominio ni reimplementa
rangos, enums, finitud ni fórmulas de riesgo (SDD-23 §11).

Invariantes duras (§6): (1) **nunca** ``NaN``/``Inf`` en el JSON — un guard defensivo levanta
:class:`~nikodym.ui.exceptions.UiSerializationError` ante cualquier no-finito, en vez de emitir
tokens que rompen JSON estricto; (2) **no-mutación** — se leen DTOs frozen y copias, jamás se
escribe bajo namespaces de dominio; (3) la UI **no produce números** — todo dato serializado viene
de un artefacto de origen citable.
"""

from __future__ import annotations

import json
import warnings
from typing import TYPE_CHECKING, Any

import numpy as np
from pydantic import BaseModel

from nikodym.core.exceptions import NikodymError
from nikodym.governance import GovernanceConfig, ModelCardBuilder
from nikodym.ui.exceptions import UiSerializationError

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.study import Study

__all__ = ["dump_dto", "serialize_study", "to_records"]

# Mapa canónico dominio → clave de su *card* en ``study.artifacts``. La clave NO es uniforme:
# binning/selection/model usan ``"<dom>_card"``; scorecard/calibration/performance/stability usan
# ``"card"``. La fuente de verdad es ``report/builder.py:_CARD_ARTIFACTS`` (SDD-23 §6); se replica
# aquí (no se importa ``report``) para conservar la frontera *domain-agnostic* del backend.
# ``tests/unit/test_ui_serializers.py`` coteja este mapa contra el canónico para detectar deriva.
_CARD_KEY_BY_DOMAIN: dict[str, str] = {
    "binning": "binning_card",
    "selection": "selection_card",
    "model": "model_card",
    "scorecard": "card",
    "calibration": "card",
    "performance": "card",
    "stability": "card",
}

# Mensaje estable de fallo. ``run_context`` NO persiste el mensaje del ``NikodymError`` de dominio
# (solo se emite al audit-trail vía el evento ``run_end``), de modo que la serialización no puede
# recuperarlo desde el ``Study``; se reporta el fallo de forma honesta y el detalle vive en el
# reporte, el lineage y el audit-trail (SDD-23 §8; ver nota de desviación en el resumen de B23.3).
_FAILURE_MESSAGE = (
    "La corrida falló durante la ejecución del pipeline. El model card parcial, el lineage y el "
    "audit-trail conservan la evidencia disponible del error de dominio."
)


def serialize_study(study: Study, *, governance: GovernanceConfig | None) -> dict[str, Any]:
    """Compone el JSON read-only de resultados de una corrida (SDD-23 §6).

    Parameters
    ----------
    study : Study
        Corrida finalizada (``run_context.status`` en ``"done"``/``"failed"``) o parcial.
    governance : GovernanceConfig or None
        Config de gobernanza para construir el ``ModelCard`` consolidado; ``None`` ⇒ card ausente.

    Returns
    -------
    dict
        ``{status, run_id, error, model_card, <dominio>...}``. ``error`` es ``None`` salvo en fallo;
        ``model_card`` es ``None`` si no hay gobernanza o la corrida no produjo card; cada
        clave de dominio (binning/selection/model/scorecard/calibration/performance/stability) trae
        su *card* serializada, **fusionada** con los frames ricos graficables de ese dominio (§6), o
        ``None`` si el dominio no corrió (nunca se fabrica).
    """
    status = study.run_context.status
    payload: dict[str, Any] = {
        "status": status,
        "run_id": study.run_context.run_id,
        "error": _FAILURE_MESSAGE if status == "failed" else None,
        "model_card": _serialize_model_card(study, governance),
    }
    for domain, key in _CARD_KEY_BY_DOMAIN.items():
        payload[domain] = (
            dump_dto(study.artifacts.get(domain, key)) if study.artifacts.has(domain, key) else None
        )
    _augment_with_rich_artifacts(study, payload)
    return payload


def _augment_with_rich_artifacts(study: Study, payload: dict[str, Any]) -> None:
    """Fusiona (merge aditivo) los frames ricos graficables en cada objeto de dominio (§6).

    Puramente aditivo: **no** toca las *cards* ya presentes ni el motor; solo lee más claves de
    ``study.artifacts`` y las proyecta bajo el guard de finitud. Las claves ricas se agregan solo
    cuando el dominio corrió (su card es un ``dict``); un artefacto rico concreto ausente entra como
    ``None`` (nunca se fabrica). No hay colisión de nombres con las claves de las cards.
    """
    if isinstance(payload["binning"], dict):
        payload["binning"]["tables_by_variable"] = _binning_tables(study)
    if isinstance(payload["selection"], dict):
        payload["selection"]["decisions"] = _selection_decisions(study)
    if isinstance(payload["model"], dict):
        payload["model"]["coefficients"] = _domain_records(study, "model", "coefficients")
    if isinstance(payload["scorecard"], dict):
        payload["scorecard"]["points"] = _domain_records(study, "scorecard", "scorecard")
        payload["scorecard"]["score_values"] = _score_values(study)
    if isinstance(payload["calibration"], dict):
        payload["calibration"]["isotonic_knots"] = _isotonic_knots(study)
    if isinstance(payload["performance"], dict):
        payload["performance"]["deciles"] = _domain_records(
            study, "performance", "performance_table"
        )
        payload["performance"]["discriminant"] = _domain_records(
            study, "performance", "discriminant_metrics"
        )
    if isinstance(payload["stability"], dict):
        # Dos frames graficables (SDD-11 §6). ``psi_table`` trae los bins de PSI del score, de la
        # PD calibrada y del CSI por característica juntos; la columna ``metric`` los distingue
        # (``score_psi``/``pd_psi``/``csi``) y cada bin lleva su ``band``. ``stability_metrics``
        # resume una fila por métrica/comparación (incluye ``temporal_score``). Los CSI por
        # característica viven DENTRO de ambos frames (filas ``metric == "csi"``), no en clave
        # aparte. ``_domain_records`` aplica el guard de finitud y ``NaN`` → ``None``.
        payload["stability"]["psi_table"] = _domain_records(study, "stability", "psi_table")
        payload["stability"]["stability_metrics"] = _domain_records(
            study, "stability", "stability_metrics"
        )


def _domain_records(study: Study, domain: str, key: str) -> list[dict[str, Any]] | None:
    """Proyecta el ``DataFrame`` ``(domain, key)`` a records; ``None`` si el artefacto falta."""
    if not study.artifacts.has(domain, key):
        return None
    return _frame_records(study.artifacts.get(domain, key))


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Proyecta un ``DataFrame`` a records, coaccionando cada celda a un tipo JSON nativo (§6).

    Las celdas de los frames del motor no son siempre tipos nativos de Python: los campos
    ``float | None`` de los DTOs fila-nivel se materializan como ``NaN`` (p. ej. ``iv`` en la fila
    *intercept* de coeficientes, o ``auc``/``gini``/``ks`` de una partición sin métricas), y la
    columna ``Bin`` de una tabla OptBinning **categórica** trae ``numpy.ndarray`` por bin
    (``array(['independiente'])``), además de escalares ``numpy``. :func:`_to_json_native` los
    normaliza uniformemente: ``NaN`` → ``None`` (ausente, igual que ``model_dump`` de un DTO
    nullable); ``ndarray``/``list``/``tuple`` → lista nativa (recursiva); escalar ``numpy`` → su
    ``.item()``. **No** fabrica números. Un ``Inf`` genuino **no** es ausente: sobrevive a la
    coacción y el guard de finitud lo rechaza (falla ruidoso), como en :func:`to_records`.
    """
    records = [
        {str(column): _to_json_native(value) for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]
    _ensure_json_safe(records, context="tabla de resultados")
    return records


def _to_json_native(value: Any) -> Any:
    """Coacciona una celda a un tipo JSON nativo (``NaN`` float → ``None``; ``Inf`` sobrevive).

    Cubre los tipos ``numpy`` que ``json.dumps`` no serializa: ``ndarray`` → lista (recursiva),
    escalar (``np.integer``/``np.floating``/``np.bool_``/``np.str_``) → su ``.item()``. Preserva la
    semántica de ausencia: ``float('nan')`` (incl. ``np.float64('nan')``, subclase de ``float``) →
    ``None``; ``Inf`` se mantiene finito-inválido para que el guard lo rechace, no lo enmascara.
    """
    if isinstance(value, float):  # incl. np.float64 (subclase): NaN→None, resto→float nativo
        return None if value != value else float(value)
    if isinstance(value, np.ndarray):
        return [_to_json_native(item) for item in value.tolist()]
    if isinstance(value, np.generic):  # escalar numpy no-float (int/bool/str/…) → nativo, recursivo
        return _to_json_native(value.item())
    if isinstance(value, (list, tuple)):
        return [_to_json_native(item) for item in value]
    return value


def _binning_tables(study: Study) -> dict[str, list[dict[str, Any]]] | None:
    """Tablas OptBinning por variable → ``{feature: records}``; ``None`` si el artefacto falta.

    Cada valor es la tabla ``binning_table`` normalizada del motor, proyectada fila a fila con sus
    columnas canónicas de OptBinning (conteos, tasas y métricas por *bin*, con la fila ``Totals``
    incluida tal como viene). El detalle de columnas está en el mapa de serialización de SDD-23 §6.
    """
    if not study.artifacts.has("binning", "tables"):
        return None
    tables: dict[str, pd.DataFrame] = study.artifacts.get("binning", "tables")
    return {str(feature): _frame_records(frame) for feature, frame in tables.items()}


def _selection_decisions(study: Study) -> list[dict[str, Any]] | None:
    """Decisiones de selección por variable (DTOs ``VariableSelectionDecision``) → records.

    ``None`` si el resultado de selección está ausente. Se excluyen a propósito
    ``correlation_matrix``/``vif_table``/``stability`` (fuera de alcance de esta capa).
    """
    if not study.artifacts.has("selection", "result"):
        return None
    return [dump_dto(decision) for decision in study.artifacts.get("selection", "result").decisions]


def _score_values(study: Study) -> list[float] | None:
    """Columna de score fila-nivel como ``list[float]`` (para el histograma); ``None`` si ausente.

    El nombre de la columna es dinámico: se lee de ``ScorecardCardSection.score_column`` (default
    ``"score"``). Se emite el array completo (la demo está pre-cacheada) bajo el guard de finitud.
    """
    if not study.artifacts.has("scorecard", "score"):
        return None
    score_column = study.artifacts.get("scorecard", "card").score_column
    values: list[float] = study.artifacts.get("scorecard", "score")[score_column].tolist()
    _ensure_json_safe(values, context="scorecard.score_values")
    return values


def _isotonic_knots(study: Study) -> list[list[float]] | None:
    """Knots isotónicos → ``[[x, y], ...]``; ``None`` si el método no es isotónico o falta.

    ``CalibrationParameters.isotonic_knots`` es una tupla vacía cuando el método no es isotónico
    (p. ej. ``intercept_offset``): se respeta como ``None``, sin fabricar una curva de fiabilidad.
    """
    if not study.artifacts.has("calibration", "parameters"):
        return None
    knots = study.artifacts.get("calibration", "parameters").isotonic_knots
    if not knots:
        return None
    pairs = [[float(x), float(y)] for x, y in knots]
    _ensure_json_safe(pairs, context="calibration.isotonic_knots")
    return pairs


def to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Proyecta un ``DataFrame`` a ``list[dict]`` (``to_dict("records")``) con guard de finitud.

    Las claves se normalizan a ``str`` (claves JSON) y se valida que el resultado sea JSON estricto:
    cualquier float no-finito levanta :class:`~nikodym.ui.exceptions.UiSerializationError`.
    """
    records = [
        {str(column): value for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]
    _ensure_json_safe(records, context="tabla de resultados")
    return records


def dump_dto(dto: BaseModel) -> dict[str, Any]:
    """Serializa un DTO Pydantic a JSON (``model_dump(mode="json")``) con guard de finitud."""
    dumped = dto.model_dump(mode="json")
    _ensure_json_safe(dumped, context=type(dto).__name__)
    return dumped


def _serialize_model_card(study: Study, governance: object) -> dict[str, Any] | None:
    """Construye y serializa el ``ModelCard`` consolidado, o ``None`` si no hay card (§6/§8)."""
    resolved = _resolve_governance(governance)
    if resolved is None:
        return None
    try:
        with warnings.catch_warnings():
            # El ``ModelCardBuilder`` avisa "trail no disponible" al construir sin trail; la UI ya
            # refleja esa condición en las limitaciones del card, no la re-emite como warning.
            warnings.filterwarnings("ignore", message="trail no disponible", category=UserWarning)
            card = ModelCardBuilder(resolved).build(study)
    except NikodymError:
        # Corrida demasiado parcial para una card válida: ausente, no fabricada (SDD-23 §6/§8).
        return None
    return dump_dto(card)


def _resolve_governance(governance: object) -> GovernanceConfig | None:
    """Normaliza la gobernanza a ``GovernanceConfig`` (coacciona un blob/dict) o ``None``."""
    if governance is None:
        return None
    if isinstance(governance, GovernanceConfig):
        return governance
    return GovernanceConfig.model_validate(governance)


def _ensure_json_safe(value: Any, *, context: str) -> None:
    """Falla ruidoso (guard defensivo) si ``value`` no es JSON estricto: no-finito u opaco."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise UiSerializationError(
            f"el artefacto '{context}' no es serializable a JSON estricto (no-finito u objeto "
            f"opaco detectado): {exc}."
        ) from exc
