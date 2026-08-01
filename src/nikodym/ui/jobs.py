"""Catálogo de TRABAJOS de la interfaz (D-JOB-1/3, `_SDD-UI-POR-TRABAJOS.md`).

Un **trabajo** es lo que un área de riesgo viene a hacer —«un scorecard de comportamiento», «la
provisión IFRS 9»—, dicho con el nombre que usan los equipos y los entregables dentro de un banco
(D-JOB-14). Elegir uno fija **qué secciones del formulario existen esa sesión**: un área que sólo
hace LGD no tiene por qué ver binning, y quien viene a un scorecard no tiene por qué ver IFRS 9.

**Por qué vive aquí y no en TypeScript**, que habría sido más barato (D-JOB-15): D-JOB-3 exige una
sola fuente que consuman **landing, sidebar y preflight**, y el preflight es Python
(:func:`nikodym.check_dataset`, ``POST /api/preflight``). Un catálogo en el front lo deja fuera por
construcción. Además, declarar qué secciones e insumos define un trabajo es dominio, y SDD-23 §1
prohíbe alojar dominio en el front. La puerta de artefactos por HTTP (D-JOB-7) tendrá la misma
necesidad.

⚠️ **Este módulo es *domain-agnostic*, como el resto de :mod:`nikodym.ui`** (lo veta el test AST
``test_ui_no_importa_modulos_de_dominio``): las secciones se nombran con **claves literales**, igual
que los presets, sin importar un solo módulo de dominio para componerlas. El gate del catálogo es
quien ata esos literales a la realidad, en las dos direcciones.

**Qué NO es este catálogo.** No decide qué pasos corre el motor —eso lo sigue resolviendo el DAG a
partir de las secciones no nulas del config— ni entra al ``config_hash`` (D-JOB-9). Es navegación:
dos usuarios que llegan al mismo config por trabajos distintos producen la misma identidad.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

__all__ = ["JOB_IDS", "decisiones_de", "list_jobs"]

# Estados de un trabajo. `available` se puede iniciar; `unavailable` aparece con su motivo y NO se
# puede iniciar (D-JOB-6): un trabajo que no corre hoy se DECLARA, no se promete ni se esconde.
# Ocultarlo dejaría al usuario creyendo que la librería no lo tiene, que es la mentira contraria.
_AVAILABLE = "available"
_UNAVAILABLE = "unavailable"

# El catálogo, en el orden en que se ofrece. Cada entrada declara:
#
#   id            · clave estable (no se muestra)
#   label         · nombre de negocio (D-JOB-14)
#   description   · qué entrega, en una línea, sin jerga interna
#   sections      · claves de sección del FORMULARIO que este trabajo muestra, en orden de pipeline
#   missing_sections · secciones que el trabajo necesitaría y que el formulario NO ofrece hoy
#   external_input   · insumo que hay que traer de fuera, en lenguaje de negocio (`None` si ninguno)
#   jurisdiction_*   · país cuya normativa impone el cálculo; `None` = neutral (D-JOB-8)
#   status / unavailable_reason
#
# ⚠️ `sections` y `missing_sections` son listas distintas a propósito. Meter `stress` en `sections`
# habría hecho fallar el gate «toda sección declarada existe en el formulario»; omitirlo a secas
# habría hecho que el catálogo callara por qué ese trabajo no está disponible. Separarlas deja el
# gate TOTAL —sin escapatoria para los trabajos no disponibles— y al catálogo diciendo la verdad.
_JOBS: tuple[dict[str, Any], ...] = (
    {
        "id": "scorecard_pd",
        "label": "Scorecard de comportamiento (PD)",
        "description": (
            "Del panel de comportamiento a una tarjeta de puntaje con su PD calibrada, "
            "sus métricas de discriminación y su informe de validación."
        ),
        "sections": (
            "data",
            "binning",
            "selection",
            "model",
            "scorecard",
            "calibration",
            "performance",
            "stability",
            "report",
        ),
        "missing_sections": (),
        "external_input": None,
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        "status": _AVAILABLE,
        "unavailable_reason": None,
    },
    {
        "id": "pd_lifetime",
        "label": "PD lifetime (curvas de supervivencia)",
        "description": (
            "Cuándo ocurre el incumplimiento, no sólo con qué probabilidad: curvas de "
            "supervivencia sobre datos censurados y su estructura temporal de PD."
        ),
        "sections": ("data", "survival", "report"),
        "missing_sections": (),
        "external_input": "La PD del modelo, si quieres anclar las curvas a ella.",
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        "status": _AVAILABLE,
        "unavailable_reason": None,
    },
    {
        "id": "provisiones_cmf",
        "label": "Provisiones CMF",
        "description": (
            "Provisión por el método estándar del Capítulo B-1: matrices normativas por "
            "cartera, mapeo de PD, exposición y garantías."
        ),
        "sections": ("data", "provisioning_cmf", "report"),
        "missing_sections": (),
        "external_input": None,
        "jurisdiction_code": "CL",
        "jurisdiction_label": "Chile",
        "status": _AVAILABLE,
        "unavailable_reason": None,
    },
    {
        "id": "provisiones_ifrs9",
        "label": "Provisiones IFRS 9 / ECL",
        "description": (
            "Pérdida esperada de tres etapas: PD lifetime, LGD, EAD, staging por SICR y "
            "descuento a la tasa efectiva."
        ),
        # Compuesto: la ECL lifetime consume la term-structure que produce survival, así que ese
        # paso es parte del trabajo y no un dominio ajeno que se cuela en el sidebar.
        "sections": ("data", "survival", "provisioning_ifrs9", "report"),
        "missing_sections": (),
        "external_input": None,
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        "status": _AVAILABLE,
        "unavailable_reason": None,
    },
    {
        "id": "provision_interna",
        "label": "Provisión interna / LGD",
        "description": (
            "Provisión por el método interno del banco: grupos homogéneos, y la PD, la LGD "
            "y la exposición propias de la institución."
        ),
        "sections": ("data", "provisioning_internal", "report"),
        "missing_sections": (),
        "external_input": "La PD calibrada de tu modelo.",
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        "status": _UNAVAILABLE,
        # El motor SÍ sabe correrlo —`check_pipeline` lo declara ejecutable con la PD inyectada por
        # la puerta de artefactos del paquete B—, pero esa puerta existe sólo por código: el paquete
        # la dejó fuera de HTTP/UI a propósito. Es D-JOB-7, y hasta entonces el trabajo no se puede
        # iniciar desde aquí.
        "unavailable_reason": (
            "Necesita que traigas la PD ya calibrada de tu modelo, y por ahora eso sólo se "
            "puede hacer desde Python."
        ),
    },
    {
        "id": "pd_y_lgd",
        "label": "PD + LGD en una corrida",
        "description": (
            "El scorecard completo y la provisión interna en una sola corrida y un solo "
            "informe, para el área que hace las dos cosas."
        ),
        "sections": (
            "data",
            "binning",
            "selection",
            "model",
            "scorecard",
            "calibration",
            "performance",
            "stability",
            "provisioning_internal",
            "report",
        ),
        "missing_sections": (),
        "external_input": None,
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        "status": _AVAILABLE,
        "unavailable_reason": None,
    },
    {
        "id": "comparar_provisiones",
        "label": "Comparar provisiones (CMF vs. interna)",
        "description": (
            "La regla del máximo del Capítulo B-1: la provisión estándar de la CMF y la del "
            "método interno del banco, comparadas por institución."
        ),
        "sections": (
            "data",
            "provisioning_cmf",
            "provisioning_internal",
            "provisioning",
            "report",
        ),
        "missing_sections": (),
        "external_input": None,
        "jurisdiction_code": "CL",
        "jurisdiction_label": "Chile",
        "status": _AVAILABLE,
        "unavailable_reason": None,
    },
    {
        "id": "validar_modelo",
        "label": "Validar un modelo existente",
        "description": (
            "Tu scorecard y tu PD, medidos y documentados por nuestro informe: "
            "discriminación, calibración y estabilidad, sin volver a modelar."
        ),
        "sections": ("data", "performance", "stability", "report"),
        "missing_sections": (),
        "external_input": "Tu scorecard y la PD que produce.",
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        "status": _UNAVAILABLE,
        "unavailable_reason": (
            "La ruta todavía no existe: falta poder traer un scorecard y una PD de fuera. "
            "Es el siguiente trabajo en construirse."
        ),
    },
    {
        "id": "lgd_modelada",
        # El §4 del SDD lo llamaba «LGD modelada (… + regresión)», nombrando la transformación de
        # las variables. El nombre cambió al programarlo por dos motivos que se refuerzan:
        # `test_ui_no_reimplementa_formulas_de_dominio` veta ese término en toda la capa `ui` —el
        # gate es un grep sobre el fuente completo, comentarios incluidos, y no distingue una
        # fórmula reimplementada de un rótulo—, y D-JOB-14 pide nombres de negocio. La técnica se
        # explica en la descripción, que es donde corresponde.
        "label": "LGD modelada por regresión",
        "description": (
            "Modelar la severidad con las mismas variables discretizadas del scorecard, en "
            "vez de traerla dada o promediarla por grupo."
        ),
        "sections": ("data", "binning", "provisioning_internal", "report"),
        "missing_sections": (),
        "external_input": "La PD calibrada de tu modelo.",
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        "status": _UNAVAILABLE,
        # Medido (D-JOB-11): el motor de LGD ya existe y ya admite como covariables las columnas
        # transformadas que publica el binning; lo que falta es que el método interno pueda delegar
        # en él. Es un paquete acotado, no una capacidad nueva — y por eso el motivo no dice «no lo
        # tenemos».
        "unavailable_reason": (
            "El motor de LGD ya modela por regresión, pero el método interno todavía no puede "
            "delegar en él: sólo admite la LGD dada o el promedio por grupo."
        ),
    },
    {
        "id": "stress_testing",
        "label": "Stress testing",
        "description": (
            "Escenarios adversos y shocks macro propagados sobre la cartera, con reverse "
            "stress para encontrar la severidad que cruza tu umbral."
        ),
        "sections": ("data", "report"),
        # `stress` NO está en el formulario, y es exactamente el motivo por el que este trabajo no
        # se puede iniciar. Declararlo aquí —y no en `sections`— deja el gate total sin que el
        # catálogo tenga que callarse la razón.
        "missing_sections": ("stress",),
        "external_input": None,
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        "status": _UNAVAILABLE,
        # D-JOB-13: es Python-only, nunca se midió de punta a punta, y el catálogo de datos externos
        # ya documentó que no lee archivos. Medirlo es un trabajo propio.
        "unavailable_reason": (
            "El motor de escenarios corre desde Python, pero todavía no tiene pantalla ni se "
            "ha probado de punta a punta desde la interfaz."
        ),
    },
)

#: Ids del catálogo, en su orden de presentación.
JOB_IDS: tuple[str, ...] = tuple(job["id"] for job in _JOBS)


# Las DECISIONES OBLIGATORIAS que impone cada sección (D-OBL-6): lo que el motor no puede rellenar
# por nadie porque es criterio de la institución, no un default.
#
# ⚠️ Se declaran POR SECCIÓN y no por trabajo a propósito. Ocho de los diez trabajos incluyen `data`,
# así que repetirlas trabajo a trabajo sería copiar el mismo par ocho veces y dejar que se
# desincronicen: la primera vez que alguien afinara el copy, siete quedarían atrás en silencio.
#
# El `path` es la coordenada interna —la misma que indexa el config, el schema y el catálogo de
# defaults— y NUNCA se enseña: lo que el usuario lee es `question` (D-OBL-9). Los paths están atados
# a `model_fields` por el gate bidireccional de `test_jobs_decisiones.py`, de modo que un campo
# obligatorio nuevo en el motor no puede quedarse sin su pregunta.
_DECISIONES_POR_SECCION: dict[str, tuple[dict[str, str], ...]] = {
    "data": (
        {
            "path": "data.target.bad_rule",
            "question": "¿Qué define a un cliente malo en tu cartera?",
            "help": (
                "La condición con la que tu área marca el incumplimiento. Suele ser un corte de "
                "mora —«más de 90 días»—, a veces junto con otra condición. No hay un valor "
                "estándar: depende de tu política, y por eso lo eliges tú."
            ),
        },
        {
            "path": "data.partition.strategy",
            "question": "¿Cómo separas la muestra para validar?",
            "help": (
                "Al azar, por fecha o por cohortes. Si tus datos tienen eje de tiempo, separar por "
                "fecha mide mejor lo que pasará en producción, porque valida contra un período que "
                "el modelo no vio."
            ),
        },
    ),
    "survival": (
        {
            "path": "survival.input.duration_col",
            "question": "¿Qué columna mide el tiempo hasta el evento?",
            "help": (
                "Cuánto duró cada operación bajo observación: meses desde el desembolso hasta el "
                "incumplimiento, o hasta que dejaste de observarla."
            ),
        },
        {
            "path": "survival.input.event_col",
            "question": "¿Qué columna dice si el evento llegó a ocurrir?",
            "help": (
                "Distingue a quien incumplió de quien seguía sano cuando terminó la observación. "
                "Sin ella las dos situaciones se confunden y las curvas salen sesgadas."
            ),
        },
    ),
}


def decisiones_de(secciones: Iterable[str]) -> list[dict[str, str]]:
    """Decisiones obligatorias de un conjunto de secciones, sin repetir y en orden estable.

    El orden es el de ``_DECISIONES_POR_SECCION``, no el de ``secciones``: dos trabajos con las
    mismas secciones en distinto orden tienen que preguntar lo mismo en el mismo orden, o la
    interfaz dependería de cómo se escribió el catálogo.
    """
    presentes = set(secciones)
    return [
        dict(decision)
        for seccion, decisiones in _DECISIONES_POR_SECCION.items()
        if seccion in presentes
        for decision in decisiones
    ]


def list_jobs() -> list[dict[str, Any]]:
    """Cataloga los trabajos disponibles para la landing y el sidebar.

    Devuelve copias JSON-ables: las tuplas del literal viajan como listas y el llamador no puede
    mutar el catálogo del proceso.
    """
    return [
        {
            **job,
            "sections": list(job["sections"]),
            "missing_sections": list(job["missing_sections"]),
            "required_decisions": decisiones_de(job["sections"]),
        }
        for job in _JOBS
    ]
