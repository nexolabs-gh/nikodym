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

from pydantic import BaseModel

from nikodym.core.exceptions import NikodymError
from nikodym.governance import GovernanceConfig, ModelCardBuilder
from nikodym.ui.exceptions import UiSerializationError

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.study import Study

__all__ = ["dump_dto", "serialize_study", "to_records"]

# Mapa canónico dominio → clave de su *card* en ``study.artifacts``. La clave NO es uniforme:
# binning/selection/model usan ``"<dom>_card"``; scorecard/calibration/performance usan ``"card"``.
# La fuente de verdad es ``report/builder.py:_CARD_ARTIFACTS`` (SDD-23 §6); se replica aquí (no se
# importa ``report``) para conservar la frontera *domain-agnostic* del backend.
# ``tests/unit/test_ui_serializers.py`` coteja este mapa contra el canónico para detectar deriva.
_CARD_KEY_BY_DOMAIN: dict[str, str] = {
    "binning": "binning_card",
    "selection": "selection_card",
    "model": "model_card",
    "scorecard": "card",
    "calibration": "card",
    "performance": "card",
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
        clave de dominio (binning/selection/model/scorecard/calibration/performance) trae su *card*
        serializada o ``None`` si el artefacto está ausente (nunca se fabrica).
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
    return payload


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
