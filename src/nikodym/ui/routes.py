"""Endpoints REST del backend (SDD-23 §4.2): solo-lectura/validación (B23.2) + ejecución (B23.3).

Expone los **6** endpoints del contrato: ``GET /api/schema`` (schema del config + defaults + orden
de secciones), ``POST /api/validate`` (validación **por reconstrucción**, siempre 200),
``GET /api/datasets`` (catálogo sintético), ``POST /api/run`` (ejecución síncrona), y
``GET /api/results/{run_id}`` / ``GET /api/report/{run_id}`` (lectura de una corrida persistida). La
lógica de cada endpoint vive en funciones **puras** (sin FastAPI), testeables sin servidor;
:func:`build_router` solo las cablea a un ``APIRouter`` con import **perezoso** de FastAPI. El
backend es *domain-agnostic*: no importa módulos de dominio ni reimplementa rangos/enums/finitud ni
fórmulas de riesgo — la verdad de validación es Pydantic y todo cómputo pasa por ``nikodym.run``
(SDD-23 §3.3, §4.2, §11).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

import nikodym
from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.config.schema import build_full_json_schema
from nikodym.core.exceptions import MissingDependencyError
from nikodym.ui import datasets, runs
from nikodym.ui.exceptions import UiDatasetError, UiRunNotFoundError

if TYPE_CHECKING:
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse

__all__ = [
    "build_router",
    "datasets_payload",
    "run_pipeline",
    "schema_payload",
    "validate_config",
]


def schema_payload() -> dict[str, Any]:
    """Compone la respuesta de ``GET /api/schema``.

    Returns
    -------
    dict
        ``{json_schema, defaults, section_order}``: el JSON-Schema **completo** de ``NikodymConfig``
        (secciones de dominio instaladas con sus ``properties``, vía
        :func:`~nikodym.core.config.schema.build_full_json_schema`), los defaults resueltos del
        config vacío y el orden de declaración de las secciones para el form.
    """
    # El schema completo lo compone el CORE (``build_full_json_schema``): materializa los dominios
    # instalados y empotra sus sub-schemas, degradando por extra ausente. ``nikodym.ui`` sigue
    # domain-agnostic (no importa binning/model/…: la materialización vive en el core, SDD-23 §11).
    # ``model_validate({})`` construye el config por defecto (todas las secciones opcionales) sin
    # enumerar argumentos: equivale a ``NikodymConfig()`` en runtime y satisface a mypy (la vista
    # TYPE_CHECKING del schema marca varias secciones como requeridas).
    return {
        "json_schema": build_full_json_schema(),
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
    return datasets.list_datasets()


def run_pipeline(config: Any, dataset_id: Any, *, workdir: Path) -> dict[str, Any]:
    """Ejecuta una corrida síncrona y la persiste; devuelve ``{run_id, status}`` (SDD-23 §7).

    Flujo: (a) valida ``config`` por reconstrucción —un ``ValidationError`` se propaga para que el
    endpoint responda **422**—; (b) resuelve ``dataset_id`` materializando su parquet determinista
    —un ``UiDatasetError`` se propaga para un **404**— y cablea su ruta a ``data.load.source``
    (edición de config declarativo, no lógica de dominio); (c) corre ``nikodym.run`` **síncrono**
    (que NO relanza en fallo, D-UI-2); (d) persiste la corrida por ``run_id``. Una corrida fallida
    devuelve ``status="failed"`` (nunca un 500 opaco).
    """
    NikodymConfig.model_validate(config)  # (a) precondición: config válido (ValidationError → 422)
    source = datasets.materialize(dataset_id, workdir=workdir)  # (b) UiDatasetError → 404
    resolved = NikodymConfig.model_validate(_wire_dataset_source(config, source))
    study = nikodym.run(resolved)  # (c) síncrono; el fallo vive en run_context.status (D-UI-2)
    run_id = runs.save(study, workdir=workdir, governance=resolved.governance)  # (d)
    return {"run_id": run_id, "status": study.run_context.status}


def _wire_dataset_source(config: dict[str, Any], source: Path) -> dict[str, Any]:
    """Cablea ``data.load.source`` al parquet del dataset sobre una copia del config (no muta)."""
    edited = copy.deepcopy(config)
    data = edited.get("data")
    if isinstance(data, dict):
        load = data.setdefault("load", {})
        if isinstance(load, dict):
            load["source"] = str(source)
    return edited


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
    """Construye el ``APIRouter`` con los 6 endpoints (import perezoso de FastAPI)."""
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import HTMLResponse

    # Las anotaciones de los handlers son *strings* (``from __future__ import annotations``) y
    # FastAPI las resuelve con los globals del módulo; se exponen aquí los tipos de FastAPI recién
    # importados (perezosos) para que ``Request``/``HTMLResponse`` resuelvan en la introspección de
    # firmas sin importar FastAPI en el top-level (núcleo liviano, SDD-23 §10).
    globals().update(Request=Request, HTMLResponse=HTMLResponse)

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
    async def datasets_endpoint() -> list[dict[str, Any]]:
        """Lista los datasets sintéticos disponibles."""
        return datasets_payload()

    @router.post("/run")
    async def run_endpoint(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """Ejecuta ``{config, dataset_id}``: 422 si es inválido, 404 si el dataset no existe."""
        workdir = Path(request.app.state.settings.workdir)
        try:
            return run_pipeline(payload.get("config"), payload.get("dataset_id"), workdir=workdir)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=_format_errors(exc)) from exc
        except UiDatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MissingDependencyError as exc:
            # Extra de dominio ausente (p. ej. tracking/mlflow): se propaga el mensaje del motor
            # ("instale nikodym[<extra>]") sin enmascararlo como 500 opaco (SDD-23 §4.2/§8).
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/results/{run_id}")
    async def results_endpoint(run_id: str, request: Request) -> dict[str, Any]:
        """Sirve el JSON de resultados de una corrida; ``run_id`` desconocido → 404."""
        workdir = Path(request.app.state.settings.workdir)
        try:
            return runs.load_results(run_id, workdir=workdir)
        except UiRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/report/{run_id}")
    async def report_endpoint(run_id: str, request: Request) -> HTMLResponse:
        """Sirve el HTML determinístico del reporte de una corrida; sin reporte → 404."""
        workdir = Path(request.app.state.settings.workdir)
        try:
            html = runs.load_report(run_id, workdir=workdir)
        except UiRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if html is None:
            raise HTTPException(
                status_code=404, detail=f"la corrida '{run_id}' no tiene reporte HTML."
            )
        return HTMLResponse(content=html)

    return router
