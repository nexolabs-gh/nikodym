"""Endpoints REST de solo-lectura/validación de B23.2 (SDD-23 §4.2).

Expone los **3** endpoints del esqueleto: ``GET /api/schema`` (schema del config + defaults +
orden de secciones), ``POST /api/validate`` (validación **por reconstrucción**: reconstruye
``NikodymConfig`` y devuelve el ``ValidationError`` estructurado, **siempre 200**) y
``GET /api/datasets`` (catálogo sintético). La lógica de cada endpoint vive en funciones **puras**
(sin FastAPI), testeables al 100% sin servidor; :func:`build_router` solo las cablea a un
``APIRouter`` con import **perezoso** de FastAPI. El backend es *domain-agnostic*: no importa
módulos de dominio ni reimplementa rangos/enums/finitud ni fórmulas de riesgo — la verdad de
validación es Pydantic (SDD-23 §3.3).

``/run``, ``/results`` y ``/report`` (y ``serializers.py``) son de B23.3 y **no** están aquí.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from nikodym.core.config import NikodymConfig, config_hash
from nikodym.ui.datasets import list_datasets

if TYPE_CHECKING:
    from fastapi import APIRouter

__all__ = ["build_router", "datasets_payload", "schema_payload", "validate_config"]


def schema_payload() -> dict[str, Any]:
    """Compone la respuesta de ``GET /api/schema``.

    Returns
    -------
    dict
        ``{json_schema, defaults, section_order}``: el JSON-Schema de ``NikodymConfig``, los
        defaults resueltos del config vacío y el orden de declaración de las secciones para el form.
    """
    # ``model_validate({})`` construye el config por defecto (todas las secciones opcionales) sin
    # enumerar argumentos: equivale a ``NikodymConfig()`` en runtime y satisface a mypy (la vista
    # TYPE_CHECKING del schema marca varias secciones como requeridas).
    return {
        "json_schema": NikodymConfig.model_json_schema(),
        "defaults": NikodymConfig.model_validate({}).model_dump(mode="json", by_alias=True),
        "section_order": list(NikodymConfig.model_fields),
    }


def validate_config(config: Any) -> dict[str, Any]:
    """Valida un config por **reconstrucción** de ``NikodymConfig`` (SDD-23 §3.3).

    Parameters
    ----------
    config : Any
        Dict del config editado (o cualquier valor a validar).

    Returns
    -------
    dict
        ``{valid, config_hash, errors}``. En éxito, ``valid=True`` y el ``config_hash`` del modelo;
        ante un ``ValidationError``, ``valid=False``, ``config_hash=None`` y la lista estructurada
        de ``{loc, msg, type}``. Nunca reimplementa rangos/enums: la verdad es Pydantic.
    """
    try:
        model = NikodymConfig.model_validate(config)
    except ValidationError as exc:
        return {"valid": False, "config_hash": None, "errors": _format_errors(exc)}
    return {"valid": True, "config_hash": config_hash(model), "errors": []}


def datasets_payload() -> list[dict[str, Any]]:
    """Compone la respuesta de ``GET /api/datasets`` (catálogo sintético estable)."""
    return list_datasets()


def _format_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Proyecta ``exc.errors()`` a ``{loc, msg, type}`` JSON-serializable (sin ``ctx``/``input``).

    ``loc`` (tupla) se convierte a lista y se omiten ``ctx``/``input``/``url``: pueden traer objetos
    no serializables y el contrato REST solo expone ``loc``/``msg``/``type`` (SDD-23 §4.2).
    """
    return [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]


def build_router() -> APIRouter:
    """Construye el ``APIRouter`` con los 3 endpoints (import perezoso de FastAPI)."""
    from fastapi import APIRouter

    router = APIRouter(prefix="/api")

    @router.get("/schema")
    async def schema() -> dict[str, Any]:
        """Devuelve el JSON-Schema del config, sus defaults y el orden de secciones."""
        return schema_payload()

    @router.post("/validate")
    async def validate(payload: dict[str, Any]) -> dict[str, Any]:
        """Valida el config recibido en ``{config}`` por reconstrucción (siempre 200)."""
        return validate_config(payload.get("config"))

    @router.get("/datasets")
    async def datasets() -> list[dict[str, Any]]:
        """Lista los datasets sintéticos disponibles."""
        return datasets_payload()

    return router
