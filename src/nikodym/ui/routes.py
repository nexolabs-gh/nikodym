"""Endpoints REST del backend (SDD-23 §4.2): solo-lectura/validación (B23.2) + ejecución (B23.3).

Expone los endpoints del contrato: ``GET /api/schema`` (schema del config + defaults + orden
de secciones), ``POST /api/validate`` (validación **por reconstrucción**, siempre 200),
``GET /api/datasets`` (catálogo sintético), ``POST /api/upload`` (subir un dataset propio
``.csv``/``.xlsx``/``.parquet``, materializado a parquet como ``uploaded_<hash>``),
``GET /api/config/preset`` (preset estándar F1 listo para correr, SDD-23 §3.2/§5),
``GET /api/jobs`` (catálogo de trabajos: qué se puede hacer y qué secciones muestra cada uno,
D-JOB-1/15),
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
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

import nikodym
from nikodym.core.config import NikodymConfig, config_hash, dump_config, loads_config
from nikodym.core.config.effective_defaults import build_effective_defaults
from nikodym.core.config.schema import build_full_json_schema, cargar_configs_de_dominio
from nikodym.core.dataset_check import columnas_producidas_por_seccion
from nikodym.core.exceptions import ConfigError, MissingDependencyError, NikodymError
from nikodym.ui import datasets, jobs, presets, runs
from nikodym.ui.exceptions import UiArtifactError, UiDatasetError, UiRunNotFoundError
from nikodym.ui.serializers import public_engine_message

if TYPE_CHECKING:
    from fastapi import APIRouter, Request, Response
    from fastapi.responses import HTMLResponse

# Media type OOXML de Word: sin él, el navegador baja el .docx como binario opaco y Word protesta.
_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

__all__ = [
    "build_router",
    "config_from_yaml",
    "config_to_yaml",
    "datasets_payload",
    "jobs_payload",
    "preset_payload",
    "presets_index_payload",
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
        ``{json_schema, defaults, section_order, effective_defaults}``: el JSON-Schema **completo**
        de ``NikodymConfig`` (secciones de dominio instaladas con sus ``properties``, vía
        :func:`~nikodym.core.config.schema.build_full_json_schema`), los defaults resueltos del
        config vacío, el orden de declaración de las secciones para el form y el catálogo de
        **defaults efectivos** por campo.
    """
    # El schema completo lo compone el CORE (``build_full_json_schema``): materializa los dominios
    # instalados y empotra sus sub-schemas, degradando por extra ausente. ``nikodym.ui`` sigue
    # domain-agnostic (no importa binning/model/…: la materialización vive en el core, SDD-23 §11).
    # ``model_validate({})`` construye el config por defecto (todas las secciones opcionales) sin
    # enumerar argumentos: equivale a ``NikodymConfig()`` en runtime y satisface a mypy (la vista
    # TYPE_CHECKING del schema marca varias secciones como requeridas).
    #
    # ``effective_defaults`` es ADITIVO (D-FX-5/D-FX-10): los tres campos previos conservan su
    # significado exacto —``defaults`` sigue siendo el config vacío con sus secciones en ``null``—
    # y un cliente viejo lo ignora. Responde la pregunta que ``json_schema`` **no puede** responder:
    # qué valor usaría el motor en un campo que el config no trae. Sin él, el formulario pintaba
    # apagado un interruptor que corre activado.
    return {
        "json_schema": build_full_json_schema(),
        "defaults": NikodymConfig.model_validate({}).model_dump(mode="json", by_alias=True),
        "section_order": list(NikodymConfig.model_fields),
        "effective_defaults": build_effective_defaults(),
    }


def validate_config(config: Any, external_artifacts: Any = None) -> dict[str, Any]:
    """Valida un config por **reconstrucción** de ``NikodymConfig`` (SDD-23 §3.3).

    Responde además si el config es **ejecutable**, que es una pregunta distinta de si es válido
    (enmienda VALIDACION-PIPELINE): un config puede reconstruir perfectamente el modelo Pydantic y
    aun así no poder correr, porque un paso pide un artefacto que ningún paso aguas arriba produce.
    Saberlo mientras se edita es lo que evita que el usuario lo descubra al apretar Ejecutar.

    🔴 **Y por eso ``external_artifacts`` tiene que llegar hasta aquí** (D-PUE-7): con las secciones
    productoras apagadas —que es la forma del config de los trabajos que traen su PD de fuera— el
    veredicto salía ``executable=false`` sobre un config que **sí corre**. Es la familia de D-PRE-9
    y D-INV-1: una superficie que responde «no se puede» sobre lo que no miró.

    ⚠️ Se consumen sólo las **claves**; el archivo y su llave se ignoran. Comprobar no necesita el
    valor (D-ART-2), así que este endpoint no toca el disco y conserva su categoría de seguridad.

    Parameters
    ----------
    config : Any
        Dict del config editado (o cualquier valor a validar).
    external_artifacts : Any
        Lo que la petición declara traer de fuera; de cada entrada se lee sólo ``artifact``.

    Returns
    -------
    dict
        ``{valid, config_hash, errors, pipeline}``. En éxito, ``valid=True`` y el ``config_hash``
        del modelo; ante un ``ValidationError``, ``valid=False``, ``config_hash=None`` y la lista
        estructurada de ``{loc, msg, type}``. Nunca reimplementa rangos/enums: la verdad es
        Pydantic.

        ``pipeline`` es ``{executable, steps, message}`` y vale ``None`` cuando el config no
        reconstruye: sin modelo no hay pipeline que resolver, y fabricar un veredicto sería
        inventarlo. **``valid`` NO cambia de significado** (D-PIPE-1): sigue siendo «reconstruye el
        modelo», que es la precondición de ``/api/run`` y del round-trip YAML. La ejecutabilidad
        viaja en su propio campo, aditivo (CT-3), porque un fallo de pipeline no tiene ``loc`` de
        campo y en ``errors`` —que el front indexa por ``loc``— quedaría invisible.
    """
    # D-HASH-5: sin esto, `valid` depende de qué importó el proceso. Por la UI no se alcanza —el
    # front no valida hasta tener el schema, y `/api/schema` importa los dominios—, pero un cliente
    # HTTP directo que pegue aquí primero recibía `valid=true` sobre un config con rangos violados.
    # No cambia el SIGNIFICADO de `valid` (D-PIPE-1 sigue en pie): lo hace significar lo mismo
    # siempre. Cuesta ~0,3 s una única vez por proceso, y sólo si nadie pidió el schema antes.
    cargar_configs_de_dominio()
    try:
        claves_externas = _claves_externas(external_artifacts)
    except UiArtifactError as exc:
        # Contrato «siempre 200»: una petición malformada es config inválido, no un 500 ni un 422.
        return {
            "valid": False,
            "config_hash": None,
            "errors": _error_de_dominio(exc),
            "pipeline": None,
            "produced_columns_by_section": {},
        }
    try:
        model = NikodymConfig.model_validate(config)
    except ValidationError as exc:
        return {
            "valid": False,
            "config_hash": None,
            "errors": _format_errors(exc),
            "pipeline": None,
            "produced_columns_by_section": {},
        }
    except ConfigError as exc:
        # Un invariante de dominio que se rompe **también** es «este config no reconstruye», y por
        # tanto `valid=False` — no un 500. `ConfigError` no hereda de `ValueError`, así que Pydantic
        # no lo envuelve en `ValidationError` y escapaba entero: bastaba activar un campo opcional
        # sin escribirle valor (`stability.temporal_column=""`) para que este endpoint —cuyo
        # contrato es responder SIEMPRE 200— devolviera 500 y el front lo leyera como «backend no
        # disponible», que es falso. Seis `config.py` levantan `ConfigError` al validar, así que el
        # arreglo va aquí y no sección por sección. Mismo criterio que `/api/config/from-yaml`.
        return {
            "valid": False,
            "config_hash": None,
            "errors": _error_de_dominio(exc),
            "pipeline": None,
            "produced_columns_by_section": {},
        }
    return {
        "valid": True,
        "config_hash": config_hash(model),
        "errors": [],
        "pipeline": _pipeline_payload(model, claves_externas),
        # D-PRO-2/3: qué columnas puede nombrar cada sección sin traerlas del archivo, ya resueltas
        # por sección. Va aquí y no en `/api/schema` porque DEPENDE del config:
        # `columnas_que_produce` devuelve el `target_col` del config, no una constante (hay test
        # que lo exige), y el schema es estático. Este endpoint ya recibe el config.
        # Se publica el mapa COMPLETO, incluidas las secciones que no aportan nada: es lo que la
        # función del núcleo promete, y filtrar aquí obligaría al front a distinguir «esta sección
        # no viene» de «no aporta nada» — que son la misma cosa y no deberían parecer dos.
        "produced_columns_by_section": {
            seccion: list(columnas)
            for seccion, columnas in columnas_producidas_por_seccion(model).items()
        },
    }


def _columnas_del_parquet(source: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Nombres del parquet separados en ``(columnas, índices)``, sin cargar los datos.

    El esquema Arrow no distingue una cosa de la otra: ``read_schema().names`` lista el índice como
    un campo más. Tomarlo tal cual hacía que el dataset del catálogo —cuyo ``loan_id`` vive en el
    índice— se reportara incompatible con su propio preset, que es el falso positivo más caro
    posible. Los metadatos ``pandas`` del parquet sí lo declaran, en ``index_columns``.

    Se detectó **probando el endpoint en vivo**: el test unitario no podía verlo porque le pasaba
    los nombres a mano, ya separados.

    Los índices se **devuelven** en vez de sólo descartarse: sin ellos, ``check_dataset`` no puede
    distinguir un ``index_col`` correcto de uno que no existe en ninguna parte —ninguno de los dos
    está entre las columnas— y el segundo se iba en silencio con ``compatible=True``.
    """
    # `pyarrow` no trae stubs; leer sólo el esquema evita cargar el dataset entero, que es la
    # diferencia entre comprobar y correr (D-PRE-1).
    import pyarrow.parquet as pq

    esquema = pq.read_schema(source)  # type: ignore[no-untyped-call]
    metadatos = esquema.metadata or {}
    indices: set[str] = set()
    if b"pandas" in metadatos:
        pandas_meta = json.loads(metadatos[b"pandas"])
        indices = {
            nombre for nombre in pandas_meta.get("index_columns", []) if isinstance(nombre, str)
        }
    columnas = tuple(nombre for nombre in esquema.names if nombre not in indices)
    return columnas, tuple(nombre for nombre in esquema.names if nombre in indices)


def _valor_en(config: Any, path: str) -> Any:
    """Baja por un path con puntos sobre el config crudo; ``None`` si la clave no existe."""
    nodo: Any = config
    for parte in path.split("."):
        if not isinstance(nodo, dict) or parte not in nodo:
            return None
        nodo = nodo[parte]
    return nodo


def _columnas_de_la_cartera(dataset_id: Any, *, workdir: Path) -> set[str]:
    """Nombres de columna de la cartera, leídos del **esquema** del parquet (D-PRE-1: sin datos).

    Devuelve el conjunto vacío si el dataset aún no está: ahí no hay nada que comparar, y el
    preflight no duplica el diagnóstico que la puerta ya da al ejecutar.
    """
    if not isinstance(dataset_id, str) or not dataset_id:
        return set()
    try:
        source = datasets.materialize(dataset_id, workdir=workdir)
    except UiDatasetError:
        return set()
    columnas, indices = _columnas_del_parquet(source)
    return set(columnas) | set(indices)


def _preflight_insumos(
    config: Any,
    external_artifacts: Any,
    dataset_id: Any,
    *,
    workdir: Path,
) -> list[dict[str, Any]]:
    """Comprueba el insumo externo **sin leer los datos** y devuelve sus avisos (D-PUE-8).

    Lo que se puede saber con el esquema del parquet y el perfil de la ingesta:

    - que las columnas mapeadas **existan** en el archivo que el usuario trajo;
    - que la llave sea **única** — el perfil ya mide los valores distintos por columna (D-PERF-1),
      así que ``n_unicos == n_filas`` responde la pregunta sin abrir el archivo;
    - que el **conteo de filas** cuadre, en el modo posicional.

    ⚠️ **Lo que NO se puede comprobar aquí, y se declara en vez de callarse:** que las etiquetas de
    la llave *cubran* el índice de la cartera. Eso exige comparar valores, o sea leer los datos, y
    D-PRE-1 se lo prohíbe al preflight. Lo verifica el motor al correr, con mensajes que ya existen
    y nombran las etiquetas que faltan. Mismo patrón que D-PRE-4 con el alcance F1: una lista corta
    sin explicación se lee como cobertura total.

    Sigue D-PRE-5: **avisa, no bloquea**. El único caso duro es el conteo de filas del modo
    posicional, y ése lo rechaza :func:`_materializar_externos` al ejecutar, no aquí.
    """
    entradas = _entradas_externas(external_artifacts)
    if not entradas:
        return []

    # ⚠️ Se ACUMULAN las entradas de todos los trabajos que declaran la misma clave, en vez de
    # quedarse con una. La PD calibrada la piden tres trabajos y cada uno la mapea a un campo
    # distinto —`provisioning_internal.pd_column` en uno, `performance.pd_column` en otro—, así que
    # un dict de una entrada por clave se quedaba con la última y no avisaba de nada.
    #
    # Acumularlas no produce falsos positivos, y por una razón que vale la pena dejar escrita: el
    # campo de un trabajo que no es el actual vive en una sección APAGADA, y ahí `_valor_en`
    # devuelve `None`. El config activo filtra solo, sin que esta capa tenga que saber por qué
    # trabajo entró el usuario.
    columnas_por_clave: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for job in jobs.list_jobs():
        for declarada in job["external_artifacts"]:
            clave = (declarada["artifact"][0], declarada["artifact"][1])
            columnas_por_clave.setdefault(clave, []).append(declarada)

    avisos: list[dict[str, Any]] = []
    for entrada in entradas:
        declaradas = columnas_por_clave.get(entrada["artifact"], [])
        origen = entrada.get("dataset_id")
        if not declaradas or not isinstance(origen, str) or not origen:
            continue  # lo rechaza la puerta al ejecutar; el preflight no duplica ese diagnóstico
        try:
            source = datasets.materialize(origen, workdir=workdir)
        except UiDatasetError:
            continue  # el archivo aún no está: no es un desajuste de columnas
        columnas, indices = _columnas_del_parquet(source)
        presentes = set(columnas) | set(indices)

        key_column = entrada.get("key_column")
        if isinstance(key_column, str) and key_column:
            # D-PUE-6-bis (§8.4): que la llave exista TAMBIÉN en la cartera es comparar dos listas
            # de nombres de columna, así que se sabe con el esquema y sin leer un dato (D-PRE-1).
            # Lo que no se puede saber aquí es si las etiquetas cubren —eso exige valores—; lo
            # comprueba la puerta al ejecutar, antes de correr y en idioma de negocio.
            if key_column not in _columnas_de_la_cartera(dataset_id, workdir=workdir):
                avisos.append(
                    {
                        "path": None,
                        "declared": key_column,
                        "kind": "external_key_mismatch",
                        "message": (
                            f"Tu cartera no tiene la columna «{key_column}» que elegiste para "
                            "emparejar las filas. Elige una que esté en los dos archivos, o quita "
                            "el identificador para emparejar por orden de filas."
                        ),
                    }
                )
            if key_column not in presentes:
                avisos.append(
                    {
                        "path": None,
                        "declared": key_column,
                        "kind": "external_missing_key",
                        "message": (
                            f"El archivo que trajiste no tiene la columna «{key_column}» que "
                            "elegiste como identificador."
                        ),
                    }
                )
            else:
                perfil = datasets.load_profile(origen, workdir=workdir)
                columna = next(
                    (c for c in (perfil.columnas if perfil else ()) if c.nombre == key_column),
                    None,
                )
                if perfil is not None and columna is not None and columna.n_unicos < perfil.n_filas:
                    avisos.append(
                        {
                            "path": None,
                            "declared": key_column,
                            "kind": "external_duplicated_key",
                            "message": (
                                f"La columna «{key_column}» se repite en el archivo: no puede "
                                "identificar cada operación."
                            ),
                        }
                    )
        elif key_column is None:
            filas_externas = datasets.row_count(origen, workdir=workdir)
            filas_cartera = datasets.row_count(dataset_id, workdir=workdir)
            if filas_externas != filas_cartera:
                avisos.append(
                    {
                        "path": None,
                        "declared": None,
                        "kind": "external_row_count",
                        "message": (
                            f"El archivo que trajiste tiene {filas_externas} filas y tu cartera "
                            f"tiene {filas_cartera}. Sin una columna que identifique cada "
                            "operación, las filas se emparejan por su orden."
                        ),
                    }
                )

        vistos: set[str] = set()
        for declarada in declaradas:
            for columna_declarada in declarada["columns"]:
                for path in columna_declarada["config_paths"]:
                    esperada = _valor_en(config, path)
                    if not isinstance(esperada, str) or not esperada or esperada in presentes:
                        continue
                    if path in vistos:
                        continue  # dos trabajos pueden mapear el mismo campo: se avisa una vez
                    vistos.add(path)
                    avisos.append(
                        {
                            # El path SÍ va, y es el mismo que indexa el formulario: es lo que
                            # permite que un click salte al campo exacto, como ya hacen los
                            # desajustes del dataset (D-PRE-2). Lo que nunca se enseña es la clave.
                            "path": path,
                            "declared": esperada,
                            "kind": "external_missing_column",
                            "message": (
                                f"El archivo que trajiste no tiene la columna «{esperada}»; "
                                f"tiene {sorted(presentes)[:8]}."
                            ),
                        }
                    )
    return avisos


def preflight_dataset(
    config: Any,
    dataset_id: Any,
    *,
    workdir: Path,
    external_artifacts: Any = None,
) -> dict[str, Any]:
    """Compara ``config`` con las columnas de un dataset **antes** de correr (D-PRE-7).

    Espejo REST de :func:`nikodym.check_dataset`, que es la misma respuesta por código y por
    interfaz. Existe porque ``/api/validate`` responde «¿es válido y ejecutable?» sin mirar el
    dataset: un config impecable puede nombrar columnas que el archivo del usuario no tiene, y hoy
    eso se descubre **de a una**, pagando una corrida por cada desajuste.

    Parameters
    ----------
    config : Any
        Dict del config editado. Un ``ValidationError`` se propaga para que el endpoint dé 422.
    dataset_id : Any
        Identificador del dataset ya conocido por la UI (del catálogo o subido).
    workdir : Path
        Directorio de trabajo donde viven los datasets materializados.
    external_artifacts : Any
        Lo que la petición declara traer de fuera; se comprueba con el esquema y el perfil, sin
        leer los datos (D-PUE-8).

    Returns
    -------
    dict
        ``{compatible, mismatches, uninspected, external_mismatches}``. Los nombres de columna se
        leen del parquet ya materializado **sin cargar los datos**: el esquema basta.

        ⚠️ ``external_mismatches`` va en su **propia** lista y no dentro de ``mismatches``, aunque
        comparta forma. Los de ``mismatches`` los produce :func:`nikodym.check_dataset`, cuyo
        vocabulario de ``kind`` es un ``Literal`` cerrado del núcleo; un artefacto traído por HTTP
        es un concepto de la capa de interfaz, y meterlo ahí obligaría a que el motor conociera una
        puerta que sólo existe en la red. ``compatible`` sigue significando exactamente lo mismo
        que antes —config contra dataset— por la misma razón.
    """
    cargar_configs_de_dominio()  # misma razón que en `validate_config`: D-HASH-5
    model = NikodymConfig.model_validate(config)
    source = datasets.materialize(dataset_id, workdir=workdir)  # UiDatasetError → 404

    columnas, indices = _columnas_del_parquet(source)
    # Lo medido al materializar (D-PERF-1), sea un archivo subido o uno del catálogo: la llamada de
    # arriba acaba de dejarlo escrito, y lo repone también si el parquet ya estaba cacheado. `None`
    # sigue siendo posible —un perfil ilegible, o un workdir donde no se pudo escribir—, y ahí el
    # veredicto es idéntico al de siempre, que es lo que D-PERF-2 exige.
    perfil = datasets.load_profile(dataset_id, workdir=workdir)
    veredicto = nikodym.check_dataset(model, columnas, index_columns=indices, column_profile=perfil)
    return {
        "compatible": veredicto.compatible,
        "mismatches": [
            {"path": m.path, "declared": m.declared, "kind": m.kind, "message": m.message}
            for m in veredicto.mismatches
        ],
        "uninspected": list(veredicto.uninspected),
        # D-ANC-11: qué sección no se pudo mirar Y por qué. Se transporta tal cual, igual que el
        # resto del veredicto: el motivo lo redacta el validador del dominio, que es quien sabe.
        "uninspection_reasons": [
            {"section": seccion, "message": motivo}
            for seccion, motivo in veredicto.uninspection_reasons
        ],
        "external_mismatches": _preflight_insumos(
            config, external_artifacts, dataset_id, workdir=workdir
        ),
    }


def _pipeline_payload(
    model: NikodymConfig,
    claves_externas: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """Proyecta el veredicto de ``nikodym.check_pipeline`` al contrato REST (D-PIPE-2/D-PIPE-5).

    El backend **transporta** el diagnóstico del motor; no lo traduce ni mapea artefacto→sección.
    Eso sería lógica de dominio en la capa UI, que SDD-23 §3.3 prohíbe: el motor es el que sabe
    qué le falta al pipeline. El encabezado del aviso —el copy propio— lo pone el front.

    El mensaje se publica saneado de códigos de marca (:func:`public_engine_message`): esto es copy
    público, y ahí la limitación se explica en el idioma del lector. El mensaje íntegro sigue
    disponible por código en ``nikodym.check_pipeline(config).message``.

    ``inert_artifacts`` se proyecta porque si no **no tiene por dónde salir a la red** (D-PUE-7): la
    §6.1 de la enmienda de la puerta decidió que el aviso de clave inerte llegue a las dos
    superficies —el trail y el veredicto—, precisamente porque el trail no existe con `audit: null`,
    que es lo que traen los presets. Se calculaba y se tiraba.
    """
    check = nikodym.check_pipeline(model, artifacts=claves_externas or None)
    message = (
        None
        if check.message is None
        else public_engine_message(
            check.message,
            error_type=check.error_type,
            is_domain_error=check.is_domain_error,
        )
    )
    return {
        "executable": check.executable,
        "steps": list(check.steps),
        "message": message,
        "inert_artifacts": [list(clave) for clave in check.inert_artifacts],
    }


def config_to_yaml(config: Any) -> dict[str, Any]:
    """Exporta un config editado a YAML canónico (round-trip, SDD-23 §3.4; reúso de SDD-05).

    Reconstruye ``NikodymConfig`` y delega el volcado en ``dump_config`` (YAML en orden de
    declaración, ``allow_unicode``): la serialización la posee SDD-05, no se reimplementa (§3.3).

    Se vuelca con ``exclude_unset=True`` para que el round-trip sea **determinista frente al estado
    de imports del proceso**: sin ello, la sección ``report`` (``report: Any`` en el schema) se
    coacciona a ``ReportConfig`` sólo si ``nikodym.report`` ya fue importado, y esa coacción
    materializa ``report.document`` (default_factory) que el config editado del cliente no traía —
    reintroduciendo un bloque espurio en el YAML según qué se hubiera importado antes (p. ej. al
    capturar los fixtures de la demo tras generar un informe). Omitir los campos no provistos vuelve
    el volcado idéntico en ambos casos (verificado byte a byte) sin tocar el ``config_hash`` (que ya
    excluye ``report`` como sección de infraestructura) ni el lineage de corrida de ``study``.

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
    return {"yaml": dump_config(model, exclude_unset=True)}


def config_from_yaml(text: Any) -> dict[str, Any]:
    """Carga un config desde YAML (con migración) y devuelve el modelo + su hash (SDD-23 §3.4).

    Delega en ``loads_config`` (SDD-05 §5.4-5.5): parsea el YAML, **migra** si el ``schema_version``
    es anterior y valida, envolviendo cualquier fallo (YAML malformado, migración o validación) en
    ``ConfigError`` — que se propaga sin enmascarar (SDD-23 §8). No se reimplementa nada (§3.3).

    Parameters
    ----------
    text : Any
        Contenido YAML del config; se exige un ``str`` (``loads_config`` requiere texto).

    El config se devuelve con ``exclude_unset=True`` (D-FX-8): la **proyección validada** de lo que
    el archivo traía, no su expansión completa. Un YAML parcial vuelve al formulario con la misma
    presencia de claves con que se escribió, y los campos que no trae se pintan como valor
    predeterminado —virtual— en vez de materializarse en el documento del usuario. Expandirlos aquí
    convertía un config de veinte líneas en uno de trescientas sin que nadie hubiera editado nada, y
    dejaba escrito como explícito un valor que el usuario nunca eligió.

    El ``config_hash`` se calcula sobre el modelo **completo**, no sobre la proyección: la identidad
    es la del config que se ejecutaría, y ausente frente a default explícito tienen el mismo digest
    (D-FX-9). Es el mismo criterio con que ``config_to_yaml`` volcaba ya con ``exclude_unset``.

    Returns
    -------
    dict
        ``{config, config_hash}``: el config reconstruido (``model_dump`` JSON con alias, sólo los
        campos provistos) y su ``config_hash`` (identidad estable, SDD-05 §5.5).

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
        "config": model.model_dump(mode="json", by_alias=True, exclude_unset=True),
        "config_hash": config_hash(model),
    }


def datasets_payload() -> list[dict[str, Any]]:
    """Compone la respuesta de ``GET /api/datasets`` (catálogo sintético estable).

    Cada columna trae además sus valores ofrecibles (D-COL-7), que el catálogo conoce sin
    depender de ningún ``workdir``.
    """
    return datasets.list_datasets()


def upload_dataset(
    content: bytes, filename: Any, *, workdir: Path, max_bytes: int | None = None
) -> dict[str, Any]:
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
    return datasets.ingest_upload(content, filename, workdir=workdir, max_bytes=max_bytes)


def preset_payload(preset_id: str | None = None) -> dict[str, Any]:
    """Compone la respuesta de un preset (config completo + ``config_hash`` + dataset, SDD-23/28).

    Sirve un preset —un config completo, curado y *domain-agnostic* (ver
    :mod:`nikodym.ui.presets`), alineado a un dataset sintético— más su ``config_hash`` de
    identidad y el ``dataset_id`` recomendado para correrlo. Con ``preset_id=None`` devuelve el
    estándar F1 (retrocompatibilidad de ``GET /api/config/preset``). El ``config`` se entrega tal
    cual y su validez la establece ``NikodymConfig.model_validate`` (la verdad de validación es
    Pydantic; no se reimplementa el schema, §3.3); el ``config_hash`` ancla la identidad de la
    corrida (SDD-05 §5.5).

    Raises
    ------
    KeyError
        Si ``preset_id`` no corresponde a ningún preset registrado.

    Returns
    -------
    dict
        ``{id, config, config_hash, dataset_id, name, description}``.
    """
    preset = presets.standard_preset() if preset_id is None else presets.get_preset(preset_id)
    model = NikodymConfig.model_validate(preset["config"])
    return {
        "id": preset["id"],
        "config": preset["config"],
        "config_hash": config_hash(model),
        "dataset_id": preset["dataset_id"],
        "name": preset["name"],
        "description": preset["description"],
    }


def jobs_payload() -> dict[str, Any]:
    """Compone la respuesta de ``GET /api/jobs``: el catálogo de trabajos (D-JOB-1/3/15).

    Aditivo: ningún endpoint existente cambia de forma y el ``config_hash`` no se mueve (D-JOB-9).
    Lo consumen la landing (qué se puede hacer), el sidebar (qué secciones existen esta sesión) y,
    más adelante, la puerta de artefactos por HTTP (D-JOB-7) — de ahí que la fuente viva en el
    backend y no en el front.
    """
    return {"jobs": jobs.list_jobs()}


def presets_index_payload() -> dict[str, Any]:
    """Compone la respuesta de ``GET /api/config/presets``: catálogo de presets SIN ``config``.

    El front lo usa para poblar el selector de presets; cada entrada trae lo justo para listar
    (``id``, ``name``, ``description``, ``dataset_id``) y el detalle se pide luego por
    ``GET /api/config/preset/{id}``.
    """
    return {"presets": presets.list_presets()}


def _entradas_externas(external_artifacts: Any) -> list[dict[str, Any]]:
    """Normaliza y valida el CUERPO de ``external_artifacts``: forma **y** allowlist (D-PUE-2).

    Contrato único para los tres endpoints que lo aceptan: ``/api/run`` lo consume entero,
    ``/api/validate`` y ``/api/preflight`` sólo miran ``artifact``. Una sola forma que aprender, y
    cada endpoint decide cuánto mira — es la misma semántica que D-ART-2 fijó para
    ``check_pipeline``, que acepta claves sueltas porque comprobar no necesita el valor.

    🔴 **La allowlist se aplica AQUÍ y no en la materialización**, que es donde estuvo hasta el
    2026-08-02, y la diferencia no es de estilo: con la comprobación sólo en ``/api/run``,
    ``/api/validate`` respondía ``executable=true`` sobre claves que ``/api/run`` rechazaba con 422.
    Eso rompe la paridad validate↔run que la §4.4 de la propia enmienda exige, que es la que hace
    que el botón Ejecutar signifique algo. Comprobar la clave no toca el disco ni materializa nada,
    así que ningún endpoint cambia de categoría de seguridad por hacerlo antes.
    """
    if external_artifacts is None:
        return []
    if not isinstance(external_artifacts, list):
        raise UiArtifactError(
            "el insumo externo debe venir como una lista; "
            f"llegó {type(external_artifacts).__name__}."
        )
    admitidos = jobs.artefactos_admitidos()
    entradas: list[dict[str, Any]] = []
    for cruda in external_artifacts:
        if not isinstance(cruda, dict):
            raise UiArtifactError(
                f"cada insumo externo debe ser un objeto; llegó {type(cruda).__name__}."
            )
        clave = cruda.get("artifact")
        if (
            not isinstance(clave, list | tuple)
            or len(clave) != 2
            or not all(isinstance(parte, str) for parte in clave)
        ):
            raise UiArtifactError(
                f"cada insumo externo declara a qué resultado corresponde; llegó {clave!r}."
            )
        normalizada = (str(clave[0]), str(clave[1]))
        if normalizada not in admitidos:
            raise UiArtifactError(
                "este trabajo no admite traer ese resultado de fuera. Elige un trabajo que lo "
                "pida, o quítalo de la petición."
            )
        entradas.append({**cruda, "artifact": normalizada})
    return entradas


def _claves_externas(external_artifacts: Any) -> tuple[tuple[str, str], ...]:
    """Sólo las claves declaradas, para las superficies que comprueban sin ejecutar (D-PUE-7).

    ``dataset_id`` y la llave se **ignoran** aquí a propósito: comprobar si un pipeline es
    ejecutable no necesita el valor del artefacto, sólo saber que va a estar. Así estas superficies
    no tocan el disco y conservan su categoría de seguridad.
    """
    return tuple(entrada["artifact"] for entrada in _entradas_externas(external_artifacts))


def _emparejar_con_la_cartera(frame: Any, cartera: Any, key_column: str) -> Any:
    """Reordena ``frame`` para que cada fila caiga sobre la operación que le toca (D-PUE-6-bis).

    🔴 **Ésta es la pieza que hace que el modo «con llave» signifique algo.** Indexar sólo el
    archivo del usuario no alinea por etiqueta: cruza. La cartera conserva su ``RangeIndex`` —una
    cartera ``.csv`` o ``.xlsx`` siempre—, así que con llaves numéricas los dos índices coinciden
    **por accidente** y la probabilidad de cada operación se aplica a otra sin que nada falle; con
    llaves de texto no hay intersección y la corrida muere con jerga del motor. Medido las dos
    veces, y **la corrección de declarar ``data.schema.index_col`` tampoco servía**: ese campo
    comprueba el nombre de un índice ya existente y nunca ejecuta ``set_index``
    (`data/schema.py:36-39`), de modo que exigirlo rompía la corrida en su primer paso justo para
    los dos formatos más usados.

    Lo que sí funciona es emparejar aquí: se leen las etiquetas de los dos lados, se verifica que
    las del archivo **cubran** las de la cartera y se devuelve el artefacto reordenado **con el
    índice de la cartera**. El motor alinea entonces sobre el mismo objeto lógico, sea
    ``RangeIndex`` o cualquier otro, y no hace falta pedirle nada al config — así ningún
    ``config_hash`` ni ``data_hash`` se mueve, y el config que se ejecuta sigue siendo el que el
    usuario ve.
    """
    if key_column not in cartera.columns:
        disponibles = [str(c) for c in cartera.columns]
        raise UiArtifactError(
            f"elegiste «{key_column}» para emparejar las filas, pero tu cartera no tiene esa "
            f"columna; las suyas son {disponibles}. Elige una columna que esté en los dos "
            "archivos, o quita el identificador para emparejar por orden de filas."
        )
    etiquetas = cartera[key_column]
    faltan = etiquetas[~etiquetas.isin(frame.index)]
    if not faltan.empty:
        muestra = [str(v) for v in faltan.unique()[:5]]
        raise UiArtifactError(
            f"el archivo que trajiste no tiene {len(faltan)} de las operaciones de tu cartera "
            f"(por ejemplo {muestra}). Tiene que traer una fila por cada operación que vas a medir."
        )
    # `.set_axis` y no `.reindex(cartera.index)`: la etiqueta de la cartera puede repetirse o no ser
    # posicional, y lo que hay que conservar es su ORDEN, no su valor.
    return frame.reindex(etiquetas.to_numpy()).set_axis(cartera.index)


def _materializar_externos(
    external_artifacts: Any,
    dataset_id: Any,
    *,
    workdir: Path,
    config: Any = None,
) -> dict[tuple[str, str], Any]:
    """Convierte lo declarado en la petición en artefactos para el motor (D-PUE-3/4/6-bis).

    Tres cosas, en este orden:

    1. **Allowlist** (D-PUE-2): la aplica :func:`_entradas_externas`, antes de tocar el disco y para
       los tres endpoints por igual. Por código la puerta es general; por la red, no.
    2. **Emparejamiento** (D-PUE-6-bis): con llave declarada, el backend alinea el archivo contra la
       cartera él mismo — ver :func:`_emparejar_con_la_cartera`, que es donde vive el porqué.
    3. **Conteo de filas**, sólo en el modo posicional: es el único desalineamiento que se puede
       detectar sin abrir los archivos, y por eso es error duro y no aviso. ⚠️ Lo que **no** se
       puede detectar ahí es un archivo con el mismo número de filas en otro orden: eso produce una
       corrida sin errores con la probabilidad de cada cliente asignada a otro. De ahí que el modo
       posicional lleve su caveat hasta el informe.

    ⚠️ **En el modo posicional el índice se normaliza**, y no es cosmético: un parquet subido con
    índice propio lo conservaba, así que el motor alineaba por *esas* etiquetas mientras la pantalla
    prometía «la fila 1 con la fila 1». Con el conteo cuadrando e índices ``[1, 0]``, cruzaba sin
    error. Alinear por orden significa por orden, y para eso el índice tiene que ser posicional.

    El ``config`` no se usa para decidir la alineación —eso fue un intento anterior que la medición
    descartó (§8.2 de la enmienda)—: se conserva en la firma porque el preflight lo necesita para
    avisar antes, y tenerlo aquí mantiene una sola forma de llamar a la puerta.

    Un mismo archivo puede alimentar **varias** claves (D-PUE-4), y es la forma que la interfaz
    propone: el motor exige que la PD y el puntaje compartan índice, y con una sola tabla eso se
    cumple por construcción en vez de fallar a mitad de la corrida.
    """
    entradas = _entradas_externas(external_artifacts)
    if not entradas:
        return {}

    materializados: dict[tuple[str, str], Any] = {}
    cartera: Any = None
    for entrada in entradas:
        clave = entrada["artifact"]
        origen = entrada.get("dataset_id")
        if not isinstance(origen, str) or not origen:
            raise UiArtifactError(
                "falta el archivo del que sale el insumo externo: súbelo antes de ejecutar."
            )
        key_column = entrada.get("key_column")
        if key_column is not None and not isinstance(key_column, str):
            raise UiArtifactError(
                f"el identificador de fila debe ser el nombre de una columna; llegó {key_column!r}."
            )
        frame = datasets.load_frame(origen, workdir=workdir, key_column=key_column)
        if cartera is None:  # una sola lectura, aunque el trabajo pida varios insumos
            cartera = datasets.load_frame(dataset_id, workdir=workdir)
        if key_column is None:
            if len(frame) != len(cartera):
                raise UiArtifactError(
                    f"el archivo que trajiste tiene {len(frame)} filas y tu cartera tiene "
                    f"{len(cartera)}. Sin una columna que identifique cada operación, las filas se "
                    "emparejan por su orden, y para eso tienen que ser las mismas."
                )
            frame = frame.reset_index(drop=True)
        else:
            frame = _emparejar_con_la_cartera(frame, cartera, key_column)
        materializados[clave] = frame
    return materializados


def run_pipeline(
    config: Any,
    dataset_id: Any,
    *,
    workdir: Path,
    external_artifacts: Any = None,
) -> dict[str, Any]:
    """Ejecuta una corrida síncrona y la persiste; devuelve ``{run_id, status}`` (SDD-23 §7).

    Flujo: (a) valida ``config`` por reconstrucción —un ``ValidationError`` se propaga para que el
    endpoint responda **422**—; (b) resuelve ``dataset_id`` materializando su parquet determinista
    —un ``UiDatasetError`` se propaga para un **404**— y cablea su ruta a ``data.load.source``
    (más ``report.output_dir`` a un dir bajo el ``workdir``; edición de config declarativo, no
    lógica de dominio); (b-bis) materializa el insumo externo declarado (D-PUE-3); (c) corre
    ``nikodym.run`` **síncrono** (que NO relanza en fallo, D-UI-2); (d) persiste la corrida por
    ``run_id``. Una corrida fallida devuelve ``status="failed"`` (nunca un 500 opaco).

    ⚠️ Los artefactos van por el parámetro ``artifacts=`` de ``nikodym.run``, que es la puerta
    pública del motor: aquí no se toca el ``ArtifactStore`` a mano. Así la colisión con un paso
    activo, la clave inerte y el lineage siguen siendo responsabilidad del núcleo (D-ART-3/4/5/7) y
    no se reimplementan en la capa de interfaz.
    """
    NikodymConfig.model_validate(config)  # (a) precondición: config válido (ValidationError → 422)
    source = datasets.materialize(dataset_id, workdir=workdir)  # (b) UiDatasetError → 404
    wired = _wire_report_output_dir(_wire_dataset_source(config, source), workdir=workdir)
    resolved = NikodymConfig.model_validate(wired)
    externos = _materializar_externos(  # (b-bis)
        external_artifacts, dataset_id, workdir=workdir, config=config
    )
    study = nikodym.run(resolved, artifacts=externos or None)  # (c) síncrono; D-UI-2
    run_id = runs.save(study, workdir=workdir, governance=resolved.governance)  # (d)
    return {"run_id": run_id, "status": study.run_context.status}


def _wire_dataset_source(config: dict[str, Any], source: Path) -> dict[str, Any]:
    """Cablea ``data.load.source`` al parquet del dataset sobre una copia del config (no muta)."""
    edited = copy.deepcopy(config)
    data = edited.get("data")
    if isinstance(data, dict):
        load = data.setdefault("load", {})
        if isinstance(load, dict):
            # POSIX sólo para rutas sin ancla: una ruta raíz/drive/UNC conserva semántica nativa.
            load["source"] = str(source) if source.anchor else source.as_posix()
    return edited


def _wire_report_output_dir(config: dict[str, Any], *, workdir: Path) -> dict[str, Any]:
    """Cablea ``report.output_dir`` a un dir absoluto bajo ``workdir`` sobre una copia (no muta).

    Análogo a :func:`_wire_dataset_source`: fija la salida del HTML a ``workdir/reports`` para que
    el reporte NO se escriba relativo al CWD del server (evita basura en el CWD y colisiones entre
    corridas). ``report`` es infraestructura (:data:`~nikodym.core.config.hashing.INFRA_SECTIONS`)
    → no altera el ``config_hash``. Guarda idempotente: si el config no trae ``report`` o no es un
    dict (preset sin reporte o ``report=None``), no hace nada.
    """
    edited = copy.deepcopy(config)
    report = edited.get("report")
    if isinstance(report, dict):
        report["output_dir"] = str((workdir / "reports").resolve())
    return edited


#: Mensajes en español por ``type`` de error de Pydantic. El ``type`` es contrato estable de
#: Pydantic v2 (a diferencia del ``msg``, que es prosa y cambia entre versiones), así que es la
#: llave correcta para traducir. Lo que no esté aquí cae al ``msg`` original: un mensaje en inglés
#: es peor que uno en español, pero mucho mejor que uno inventado que diga otra cosa.
_MENSAJES: dict[str, str] = {
    "missing": "Este campo es obligatorio.",
    "extra_forbidden": "Este campo no existe en la configuración.",
    "string_type": "Tiene que ser texto.",
    "string_too_short": "El texto es demasiado corto.",
    "string_too_long": "El texto es demasiado largo.",
    "int_type": "Tiene que ser un número entero.",
    "int_parsing": "Tiene que ser un número entero.",
    "int_from_float": "Tiene que ser un número entero, sin decimales.",
    "float_type": "Tiene que ser un número.",
    "float_parsing": "Tiene que ser un número.",
    "decimal_parsing": "Tiene que ser un número.",
    "bool_type": "Tiene que estar activado o desactivado.",
    "bool_parsing": "Tiene que estar activado o desactivado.",
    "list_type": "Tiene que ser una lista.",
    "tuple_type": "Tiene que ser una lista.",
    "set_type": "Tiene que ser una lista sin repetidos.",
    "dict_type": "Tiene que ser un objeto con pares clave-valor.",
    "model_type": "Tiene que ser un objeto con sus campos.",
    "model_attributes_type": "Tiene que ser un objeto con sus campos.",
    "too_short": "Faltan elementos en la lista.",
    "too_long": "Sobran elementos en la lista.",
    "date_type": "Tiene que ser una fecha.",
    "date_from_datetime_parsing": "Tiene que ser una fecha válida.",
    "datetime_parsing": "Tiene que ser una fecha válida.",
    "enum": "Elige uno de los valores del selector.",
    "literal_error": "Elige uno de los valores del selector.",
    "url_parsing": "Tiene que ser una dirección web válida.",
    "json_invalid": "El texto no es JSON válido.",
}

#: Prefijo que Pydantic antepone al mensaje de un validador propio (`ValueError` en un
#: `field_validator`). El mensaje de detrás ya está en español —lo escribe este repo—, pero el
#: prefijo no, y se lee en pantalla.
_PREFIJOS_PYDANTIC = ("Value error, ", "Assertion failed, ")


def _mensaje_en_espanol(error: dict[str, Any]) -> str:
    """Traduce un error de Pydantic al idioma de la interfaz, conservando su detalle numérico.

    La UI está en español y estos mensajes se pintan junto al campo: dejar «Field required» o
    «Input should be a valid integer» en una pantalla en español es copy público sin traducir. La
    traducción es por ``type`` y **nunca inventa**: si el tipo no está mapeado se devuelve el
    mensaje original de Pydantic.

    Los errores de rango llevan su cota en ``ctx`` (``ge``, ``gt``, ``le``, ``lt``): se compone el
    mensaje con el número, porque «tiene que ser mayor o igual que 0» sin el 0 no sirve de nada.
    """
    tipo = str(error.get("type", ""))
    ctx = error.get("ctx") or {}
    cotas = {
        "greater_than": ("gt", "mayor que"),
        "greater_than_equal": ("ge", "mayor o igual que"),
        "less_than": ("lt", "menor que"),
        "less_than_equal": ("le", "menor o igual que"),
        "multiple_of": ("multiple_of", "múltiplo de"),
    }
    if tipo in cotas:
        clave, texto = cotas[tipo]
        limite = ctx.get(clave)
        if limite is not None:
            return f"Tiene que ser {texto} {limite}."
    if tipo in _MENSAJES:
        return _MENSAJES[tipo]
    msg = str(error.get("msg", ""))
    for prefijo in _PREFIJOS_PYDANTIC:
        if msg.startswith(prefijo):
            return msg[len(prefijo) :]
    return msg


def _format_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Proyecta ``exc.errors()`` a ``{loc, msg, type}`` JSON-serializable (sin ``ctx``/``input``).

    ``loc`` (tupla) se convierte a lista y se omiten ``ctx``/``input``/``url``: pueden traer objetos
    no serializables y el contrato REST solo expone ``loc``/``msg``/``type`` (SDD-23 §4.2). El
    ``msg`` viaja **traducido** (:func:`_mensaje_en_espanol`); el ``type``, que es la llave estable
    y la que consume cualquier cliente programático, se conserva intacto.
    """
    return [
        {
            "loc": list(error["loc"]),
            "msg": _mensaje_en_espanol(dict(error)),
            "type": error["type"],
        }
        for error in exc.errors()
    ]


def _error_de_dominio(exc: NikodymError) -> list[dict[str, Any]]:
    """Proyecta un error del motor a la MISMA forma que un error de Pydantic.

    Va con ``loc`` vacío porque un invariante de dominio no pertenece a un campo: nace de la
    relación entre varios (``_check_invariantes``). El front indexa por ``loc`` para pintar el
    error junto a su campo, así que éste no se anclará a ninguno — pero sí entra en el contador de
    «config inválido», que es lo que el usuario necesita para saber que no puede correr. Fabricar
    un ``loc`` a partir del texto del mensaje sería adivinar.

    Acepta cualquier ``NikodymError`` y no sólo ``ConfigError`` porque un insumo externo mal
    declarado tiene exactamente la misma naturaleza: no pertenece a ningún campo del config, y en
    ``/api/validate`` —cuyo contrato es responder siempre 200— tiene que salir como config inválido
    y no como un 500.
    """
    return [{"loc": [], "msg": str(exc), "type": "config_error"}]


def build_router() -> APIRouter:
    """Construye el ``APIRouter`` con los endpoints del contrato (import perezoso de FastAPI)."""
    from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
    from fastapi.responses import HTMLResponse

    # Las anotaciones de los handlers son *strings* (``from __future__ import annotations``) y
    # FastAPI las resuelve con los globals del módulo; se exponen aquí los tipos de FastAPI recién
    # importados (perezosos) para que ``Request``/``HTMLResponse``/``Response``/``UploadFile``
    # resuelvan en la introspección de firmas sin importar FastAPI en el top-level (SDD-23 §10).
    globals().update(
        Request=Request, Response=Response, HTMLResponse=HTMLResponse, UploadFile=UploadFile
    )

    router = APIRouter(prefix="/api")

    @router.get("/schema")
    async def schema() -> dict[str, Any]:
        """Devuelve el JSON-Schema del config, sus defaults y el orden de secciones."""
        return schema_payload()

    @router.post("/validate")
    async def validate(payload: dict[str, Any]) -> dict[str, Any]:
        """Valida ``{config, external_artifacts?}`` por reconstrucción (siempre 200)."""
        return validate_config(payload.get("config"), payload.get("external_artifacts"))

    @router.post("/preflight")
    async def preflight_endpoint(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """Compara ``{config, dataset_id, external_artifacts?}`` con el dataset, sin correr nada."""
        workdir = Path(request.app.state.settings.workdir)
        try:
            return preflight_dataset(
                payload.get("config"),
                payload.get("dataset_id"),
                workdir=workdir,
                external_artifacts=payload.get("external_artifacts"),
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=_format_errors(exc)) from exc
        except ConfigError as exc:
            # Un invariante de dominio roto es entrada del usuario, no un fallo del servidor: 422
            # con el mensaje del motor, nunca un 500 opaco (SDD-23 §8, igual que `from-yaml`).
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except UiArtifactError as exc:
            # Mismo criterio que `/api/run`, y hace falta aquí porque desde D-PUE-2 este endpoint
            # también normaliza el insumo externo: un cuerpo malformado o una clave fuera de la
            # allowlist escapaban enteras y el servidor respondía 500 sobre entrada del usuario.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except UiDatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/datasets")
    async def datasets_endpoint() -> list[dict[str, Any]]:
        """Lista los datasets sintéticos con sus valores ofrecibles (D-COL-7)."""
        return datasets_payload()

    @router.post("/upload")
    async def upload_endpoint(file: UploadFile, request: Request) -> dict[str, Any]:
        """Sube un dataset propio (``.csv``/``.xlsx``/``.parquet``) → ``{dataset_id, ...}``.

        Materializa el archivo a parquet ``uploaded_<hash>`` bajo el ``workdir`` y devuelve su
        ``dataset_id`` + preview de columnas. Un archivo inválido/ilegible/muy grande → 422 (es
        entrada del usuario, nunca un 500 opaco).

        ⚠️ **El tamaño se comprueba ANTES de traer el cuerpo a memoria.** Hasta el 2026-08-02 el
        `await file.read()` iba primero y el tope se evaluaba tres saltos después, con el archivo
        entero ya en RAM: el límite existía y no limitaba nada. Starlette pone las partes grandes
        en un `SpooledTemporaryFile` y publica su tamaño, así que preguntarlo no materializa nada.
        Si el servidor no lo publicara, `upload_dataset` conserva la comprobación de siempre.

        ⚠️ **Y lo que este tope NO cubre, dicho aquí en vez de dejarlo suponer:** FastAPI termina de
        **recibir y parsear** el cuerpo multipart antes de llamar a este handler, así que el archivo
        rechazado ya viajó por la red y ya se escribió al temporal en disco. Lo que se evita es la
        copia final a memoria, no la transferencia — y la «lectura por chunks» que SDD-23 §11
        prometía tampoco la habría evitado, porque el parseo es previo en las dos formas. Cerrarlo
        de verdad exige un middleware que cuente bytes sobre el stream ASGI, que es superficie nueva
        en la capa de seguridad y se decide aparte. El modelo de amenaza lo hace tolerable: la ruta
        exige `Host`, `Origin` y token, o sea alguien que ya está dentro de la sesión local. Se
        declara con su razón por la misma regla que D-PRE-4 y D-PUE-8: una guarda que no dice su
        alcance se lee como cobertura total.
        """
        settings = request.app.state.settings
        workdir = Path(settings.workdir)
        max_bytes = settings.upload_max_mb * 1024 * 1024
        tamano = getattr(file, "size", None)
        if isinstance(tamano, int) and tamano > max_bytes:
            raise HTTPException(status_code=422, detail=datasets.mensaje_de_tope(tamano, max_bytes))
        content = await file.read()
        try:
            return upload_dataset(content, file.filename, workdir=workdir, max_bytes=max_bytes)
        except UiDatasetError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/jobs")
    async def jobs_endpoint() -> dict[str, Any]:
        """Cataloga los trabajos: qué se puede hacer y qué secciones muestra cada uno."""
        return jobs_payload()

    @router.get("/config/presets")
    async def config_presets_index_endpoint() -> dict[str, Any]:
        """Cataloga los presets disponibles (sin ``config``) para el selector del front."""
        return presets_index_payload()

    @router.get("/config/preset")
    async def config_preset_endpoint() -> dict[str, Any]:
        """Sirve el preset estándar F1: un config completo listo para correr sin editar nada."""
        return preset_payload()

    @router.get("/config/preset/{preset_id}")
    async def config_preset_by_id_endpoint(preset_id: str) -> dict[str, Any]:
        """Sirve un preset por id; ``preset_id`` desconocido → 404 (no un 500 opaco)."""
        try:
            return preset_payload(preset_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"preset desconocido: {preset_id!r}"
            ) from exc

    @router.post("/run")
    async def run_endpoint(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """Ejecuta ``{config, dataset_id, external_artifacts?}``: 422 inválido, 404 sin dataset."""
        workdir = Path(request.app.state.settings.workdir)
        try:
            return run_pipeline(
                payload.get("config"),
                payload.get("dataset_id"),
                workdir=workdir,
                external_artifacts=payload.get("external_artifacts"),
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=_format_errors(exc)) from exc
        except ConfigError as exc:
            # Mismo criterio que `/api/validate` y `from-yaml`: el config es entrada del usuario.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except UiArtifactError as exc:
            # 422 y no 404: el insumo externo es entrada del usuario. Una clave que este trabajo no
            # admite, una llave que su archivo no trae o un conteo que no cuadra con la cartera son
            # cosas que él puede corregir; responder «no existe» le diría otra cosa.
            #
            # ⚠️ El orden respecto de `UiDatasetError` es indiferente y decirlo importa: las dos son
            # **hermanas** bajo `UiError`, no una subclase de la otra (verificado con el MRO), así
            # que ninguna captura a la otra. Quien las discrimina es el `raise` de origen, y por eso
            # `load_frame` levanta la de artefacto cuando el problema es la llave declarada.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
        except ConfigError as exc:
            # Mismo criterio que `/api/validate` y `from-yaml`: el config es entrada del usuario.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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

    @router.get("/report/{run_id}/pdf")
    async def report_pdf_endpoint(run_id: str, request: Request) -> Response:
        """Sirve el PDF del reporte de una corrida como descarga; sin PDF → 404."""
        workdir = Path(request.app.state.settings.workdir)
        try:
            pdf = runs.load_report_pdf(run_id, workdir=workdir)
        except UiRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if pdf is None:
            raise HTTPException(
                status_code=404, detail=f"la corrida '{run_id}' no tiene reporte PDF."
            )
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="reporte-modelo.pdf"'},
        )

    @router.get("/report/{run_id}/md")
    async def report_md_endpoint(run_id: str, request: Request) -> Response:
        """Sirve la base editable como ZIP (``.qmd`` + figuras); sin ``.qmd`` → 404.

        Es la **base editable**: el analista la baja, escribe su contexto y sus conclusiones encima
        y compila su propio documento.

        Va como ZIP y no como ``.qmd`` suelto a propósito: el documento referencia sus figuras por
        ruta relativa, así que entregar solo el texto daría un informe con las imágenes rotas. El
        ZIP se descomprime y ``quarto render`` compila tal cual.
        """
        workdir = Path(request.app.state.settings.workdir)
        try:
            bundle = runs.load_report_md_bundle(run_id, workdir=workdir)
        except UiRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if bundle is None:
            raise HTTPException(
                status_code=404, detail=f"la corrida '{run_id}' no tiene reporte .qmd."
            )
        return Response(
            content=bundle,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="reporte-modelo-quarto.zip"'},
        )

    @router.get("/report/{run_id}/docx")
    async def report_docx_endpoint(run_id: str, request: Request) -> Response:
        """Sirve el ``.docx`` (Word) del reporte como descarga; sin ``.docx`` → 404."""
        workdir = Path(request.app.state.settings.workdir)
        try:
            document = runs.load_report_docx(run_id, workdir=workdir)
        except UiRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if document is None:
            raise HTTPException(
                status_code=404, detail=f"la corrida '{run_id}' no tiene reporte .docx."
            )
        return Response(
            content=document,
            media_type=_DOCX_MEDIA_TYPE,
            headers={"Content-Disposition": 'attachment; filename="reporte-modelo.docx"'},
        )

    return router
