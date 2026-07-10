"""Endpoints REST del backend (SDD-23 §4.2): solo-lectura/validación (B23.2) + ejecución (B23.3).

Expone los endpoints del contrato: ``GET /api/schema`` (schema del config + defaults + orden
de secciones), ``POST /api/validate`` (validación **por reconstrucción**, siempre 200),
``GET /api/datasets`` (catálogo sintético), ``POST /api/upload`` (subir un dataset propio
``.csv``/``.xlsx``/``.parquet``, materializado a parquet como ``uploaded_<hash>``),
``GET /api/config/preset`` (preset estándar F1 listo para correr, SDD-23 §3.2/§5),
``POST /api/run`` (ejecución síncrona), ``GET /api/results/{run_id}`` / ``GET /api/report/{run_id}``
(lectura de una corrida persistida) y el round-trip YAML ``POST /api/config/to-yaml`` /
``POST /api/config/from-yaml`` (reúso de SDD-05, §3.4). La lógica de cada endpoint vive en funciones
**puras** (sin FastAPI), testeables sin
servidor; :func:`build_router` solo las cablea a un ``APIRouter`` con import **perezoso** de
FastAPI. El backend es *domain-agnostic*: no importa módulos de dominio ni reimplementa
rangos/enums/finitud ni fórmulas de riesgo — la verdad de validación es Pydantic y todo cómputo
pasa por ``nikodym.run`` (SDD-23 §3.3, §4.2, §11).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

import nikodym
from nikodym.core.config import NikodymConfig, config_hash, dump_config, loads_config
from nikodym.core.config.schema import build_full_json_schema
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.ui import datasets, presets, runs
from nikodym.ui.exceptions import UiDatasetError, UiRunNotFoundError

if TYPE_CHECKING:
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse

__all__ = [
    "build_router",
    "config_from_yaml",
    "config_to_yaml",
    "datasets_payload",
    "preset_payload",
    "run_pipeline",
    "schema_payload",
    "upload_dataset",
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


def config_to_yaml(config: Any) -> dict[str, Any]:
    """Exporta un config editado a YAML canónico (round-trip, SDD-23 §3.4; reúso de SDD-05).

    Reconstruye ``NikodymConfig`` y delega el volcado en ``dump_config`` (YAML en orden de
    declaración, ``allow_unicode``): la serialización la posee SDD-05, no se reimplementa (§3.3).

    Parameters
    ----------
    config : Any
        Dict del config editado (o cualquier valor a reconstruir).

    Returns
    -------
    dict
        ``{yaml}`` con el YAML canónico del config.

    Raises
    ------
    pydantic.ValidationError
        Si ``config`` no reconstruye un modelo válido; se **propaga** para que el endpoint responda
        **422** (config válido es precondición de exportar), igual que :func:`run_pipeline`.
    """
    model = NikodymConfig.model_validate(config)
    return {"yaml": dump_config(model)}


def config_from_yaml(text: Any) -> dict[str, Any]:
    """Carga un config desde YAML (con migración) y devuelve el modelo + su hash (SDD-23 §3.4).

    Delega en ``loads_config`` (SDD-05 §5.4-5.5): parsea el YAML, **migra** si el ``schema_version``
    es anterior y valida, envolviendo cualquier fallo (YAML malformado, migración o validación) en
    ``ConfigError`` — que se propaga sin enmascarar (SDD-23 §8). No se reimplementa nada (§3.3).

    Parameters
    ----------
    text : Any
        Contenido YAML del config; se exige un ``str`` (``loads_config`` requiere texto).

    Returns
    -------
    dict
        ``{config, config_hash}``: el config reconstruido (``model_dump`` JSON con alias) y su
        ``config_hash`` (identidad estable, SDD-05 §5.5).

    Raises
    ------
    ConfigError
        Si ``text`` no es un ``str``, o si el YAML no carga/migra/valida (mensaje del motor,
        propagado tal cual desde ``loads_config``).
    """
    if not isinstance(text, str):
        raise ConfigError(f"el YAML del config debe ser un string, no {type(text).__name__}.")
    model = loads_config(text)
    return {
        "config": model.model_dump(mode="json", by_alias=True),
        "config_hash": config_hash(model),
    }


def datasets_payload() -> list[dict[str, Any]]:
    """Compone la respuesta de ``GET /api/datasets`` (catálogo sintético estable)."""
    return datasets.list_datasets()


def upload_dataset(content: bytes, filename: Any, *, workdir: Path) -> dict[str, Any]:
    """Ingesta un dataset propio subido y devuelve ``{dataset_id, name, n_rows, columns}``.

    Valida que ``filename`` sea un ``str`` (precondición del lector por sufijo) y delega la ingesta
    en :func:`nikodym.ui.datasets.ingest_upload`, que valida tamaño/formato, lee con pandas y
    materializa a parquet ``uploaded_<hash>`` (identidad determinista por contenido). No importa
    ``nikodym.data``: la lectura es pandas directo (SDD-23 §11).

    Parameters
    ----------
    content : bytes
        Bytes crudos del archivo subido.
    filename : Any
        Nombre original del archivo; debe ser un ``str`` (si no, ``UiDatasetError`` → 422).
    workdir : Path
        Directorio de trabajo local donde se materializa el parquet del upload.

    Returns
    -------
    dict
        ``{dataset_id, name, n_rows, columns}`` (ver :func:`~nikodym.ui.datasets.ingest_upload`).

    Raises
    ------
    UiDatasetError
        Si ``filename`` no es un ``str`` o si la ingesta falla (vacío, formato/tamaño, ilegible).
    """
    if not isinstance(filename, str):
        raise UiDatasetError(
            f"el nombre del archivo subido debe ser un string, no {type(filename).__name__}."
        )
    return datasets.ingest_upload(content, filename, workdir=workdir)


def preset_payload() -> dict[str, Any]:
    """Compone la respuesta de ``GET /api/config/preset`` (preset estándar F1, SDD-23 §3.2/§5).

    Sirve el preset estándar —un config F1 completo, curado y *domain-agnostic* (ver
    :mod:`nikodym.ui.presets`), alineado a un dataset sintético— más su ``config_hash`` de
    identidad y el ``dataset_id`` recomendado para correrlo. El ``config`` se entrega tal cual y su
    validez la establece ``NikodymConfig.model_validate`` (la verdad de validación es Pydantic; no
    se reimplementa el schema, §3.3); el ``config_hash`` ancla la identidad de la corrida
    (SDD-05 §5.5).

    Returns
    -------
    dict
        ``{config, config_hash, dataset_id, name, description}``.
    """
    preset = presets.standard_preset()
    model = NikodymConfig.model_validate(preset["config"])
    return {
        "config": preset["config"],
        "config_hash": config_hash(model),
        "dataset_id": preset["dataset_id"],
        "name": preset["name"],
        "description": preset["description"],
    }


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
    """Construye el ``APIRouter`` con los endpoints del contrato (import perezoso de FastAPI)."""
    from fastapi import APIRouter, HTTPException, Request, UploadFile
    from fastapi.responses import HTMLResponse

    # Las anotaciones de los handlers son *strings* (``from __future__ import annotations``) y
    # FastAPI las resuelve con los globals del módulo; se exponen aquí los tipos de FastAPI recién
    # importados (perezosos) para que ``Request``/``HTMLResponse``/``UploadFile`` resuelvan en la
    # introspección de firmas sin importar FastAPI en el top-level (núcleo liviano, SDD-23 §10).
    globals().update(Request=Request, HTMLResponse=HTMLResponse, UploadFile=UploadFile)

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

    @router.post("/upload")
    async def upload_endpoint(file: UploadFile, request: Request) -> dict[str, Any]:
        """Sube un dataset propio (``.csv``/``.xlsx``/``.parquet``) → ``{dataset_id, ...}``.

        Materializa el archivo a parquet ``uploaded_<hash>`` bajo el ``workdir`` y devuelve su
        ``dataset_id`` + preview de columnas. Un archivo inválido/ilegible/muy grande → 422 (es
        entrada del usuario, nunca un 500 opaco).
        """
        workdir = Path(request.app.state.settings.workdir)
        content = await file.read()
        try:
            return upload_dataset(content, file.filename, workdir=workdir)
        except UiDatasetError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/config/preset")
    async def config_preset_endpoint() -> dict[str, Any]:
        """Sirve el preset estándar F1: un config completo listo para correr sin editar nada."""
        return preset_payload()

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

    @router.post("/config/to-yaml")
    async def config_to_yaml_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        """Exporta ``{config}`` a YAML canónico; config inválido → 422 (round-trip, SDD-23 §3.4)."""
        try:
            return config_to_yaml(payload.get("config"))
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=_format_errors(exc)) from exc

    @router.post("/config/from-yaml")
    async def config_from_yaml_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        """Carga ``{yaml}`` (con migración) → ``{config, config_hash}``; error → 422 (SDD-23 §3.4).

        Un ``ConfigError`` (YAML malformado, schema no-mapeado, migración fallida o entrada no-str)
        se traduce a **422** con el mensaje del motor, sin enmascararlo como 500 (SDD-23 §8).
        """
        try:
            return config_from_yaml(payload.get("yaml"))
        except ConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
