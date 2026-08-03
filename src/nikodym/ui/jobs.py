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

__all__ = ["JOB_IDS", "artefactos_admitidos", "decisiones_de", "list_jobs"]

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
#   external_artifacts · el mismo insumo, en forma MÁQUINA-LEGIBLE (D-PUE-2); ver más abajo
#   jurisdiction_*   · país cuya normativa impone el cálculo; `None` = neutral (D-JOB-8)
#   status / unavailable_reason
#
# ⚠️ `external_input` y `external_artifacts` son campos distintos y no se pueden fusionar.
# El primero es **copy** —lo lee un analista en la landing— y vive bajo el gate de jerga, que veta
# nombrar claves internas; el segundo es **dato** y no tiene más remedio que nombrarlas. Meter la
# clave en el copy habría puesto los dos gates en contradicción.
#
# Forma de cada entrada de `external_artifacts` (D-PUE-2):
#
#   artifact      · pareja ``(dominio, clave)`` del almacén de resultados del motor. **De aquí sale
#                   la allowlist de la puerta por HTTP**: una clave que ningún trabajo disponible
#                   declare se rechaza sin materializar nada. Por código la puerta sigue siendo
#                   general; por la red es esta lista.
#   label         · qué es, en idioma de negocio. Es copy y entra al gate de jerga.
#   when          · condición del config que hace pertinente esta clave, o `None` si siempre.
#                   ⚠️ Existe porque el método interno pide una clave **u otra** según de dónde
#                   declares que sale la PD: fijar una sola dejaría el trabajo roto en silencio en
#                   cuanto alguien cambiara ese campo.
#   key_question  · cómo se pregunta cuál columna identifica cada fila. La llave **no es config**
#                   —por código el artefacto llega ya indexado—, así que viaja en la petición,
#                   igual que el identificador del dataset (D-PUE-5).
#   columns       · qué hay que mapear del archivo. Cada rol se pregunta **una vez** y su respuesta
#                   puede escribir **varios** campos del config: dos secciones que miran el mismo
#                   archivo nombran la misma columna, y preguntarlo dos veces sería absurdo.
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
        "external_artifacts": (),
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
        # Vacío a propósito, y no es un olvido: `survival` no REQUIERE la PD —ninguno de sus pasos
        # la pide—, así que no hay clave que traer por la puerta. El copy de arriba describe un
        # insumo opcional del método, no un artefacto del motor. Los dos campos miden cosas
        # distintas y por eso pueden no coincidir.
        "external_artifacts": (),
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
        "external_artifacts": (),
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
        "external_artifacts": (),
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
        "external_artifacts": (
            {
                "artifact": ("calibration", "calibrated_pd_frame"),
                "label": "La PD calibrada de tu modelo, por operación",
                "when": {"path": "provisioning_internal.pd_source", "equals": "calibration"},
                "key_question": "¿Qué columna identifica cada operación?",
                "columns": (
                    {
                        "question": "¿Qué columna trae la probabilidad de incumplimiento?",
                        "config_paths": ("provisioning_internal.pd_column",),
                    },
                ),
            },
            {
                "artifact": ("model", "raw_pd_frame"),
                "label": "La PD sin calibrar de tu modelo, por operación",
                "when": {"path": "provisioning_internal.pd_source", "equals": "model"},
                "key_question": "¿Qué columna identifica cada operación?",
                "columns": (
                    {
                        "question": "¿Qué columna trae la probabilidad de incumplimiento?",
                        "config_paths": ("provisioning_internal.pd_column",),
                    },
                ),
            },
        ),
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        # Disponible desde D-PUE-11: el motor siempre supo correrlo —`check_pipeline` lo declaraba
        # ejecutable con la PD inyectada— y lo que faltaba era la puerta por HTTP, que es D-JOB-7.
        "status": _AVAILABLE,
        "unavailable_reason": None,
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
        "external_artifacts": (),
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
        "external_artifacts": (),
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
        # Las dos claves salen de UNA sola tabla del usuario si él quiere (D-PUE-4), y ésa es la
        # forma que la interfaz propone: el motor exige que los dos artefactos compartan índice, y
        # con un solo archivo eso se cumple por construcción en vez de fallar al octavo paso.
        "external_artifacts": (
            {
                "artifact": ("calibration", "calibrated_pd_frame"),
                "label": "La PD de tu modelo, con su muestra y el resultado observado",
                "when": None,
                "key_question": "¿Qué columna identifica cada operación?",
                "columns": (
                    {
                        "question": "¿Qué columna trae la probabilidad de incumplimiento?",
                        # Un solo rol, dos campos: las dos secciones leen el mismo archivo.
                        "config_paths": ("performance.pd_column", "stability.pd_column"),
                    },
                    {
                        "question": "¿Qué columna dice a qué muestra pertenece cada operación?",
                        "config_paths": (
                            "performance.partition_column",
                            "stability.partition_column",
                        ),
                    },
                    {
                        "question": "¿Qué columna dice si la operación terminó incumpliendo?",
                        "config_paths": ("performance.target_column",),
                    },
                ),
            },
            {
                "artifact": ("scorecard", "score"),
                "label": "El puntaje que tu modelo asigna a cada operación",
                "when": None,
                "key_question": "¿Qué columna identifica cada operación?",
                "columns": (
                    {
                        "question": "¿Qué columna trae el puntaje de tu modelo?",
                        "config_paths": ("performance.score_column", "stability.score_column"),
                    },
                ),
            },
        ),
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        # Disponible desde D-PUE-11. ⚠️ Alcance declarado: mide y documenta con `performance` y
        # `stability`. La validación formal —la sección `validation`— necesita además un artefacto
        # que NO es una tabla, y por HTTP sólo entran tablas (D-PUE-1/D-PUE-12): eso es trabajo
        # aparte y aquí no se promete.
        "status": _AVAILABLE,
        "unavailable_reason": None,
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
        # Declara lo que aceptará, aunque hoy no se pueda iniciar: su bloqueo es otro (falta que el
        # método interno pueda delegar en el motor de severidad), no la puerta. La allowlist sólo
        # mira los trabajos disponibles, así que declararlo aquí no abre nada.
        "external_artifacts": (
            {
                "artifact": ("calibration", "calibrated_pd_frame"),
                "label": "La PD calibrada de tu modelo, por operación",
                "when": {"path": "provisioning_internal.pd_source", "equals": "calibration"},
                "key_question": "¿Qué columna identifica cada operación?",
                "columns": (
                    {
                        "question": "¿Qué columna trae la probabilidad de incumplimiento?",
                        "config_paths": ("provisioning_internal.pd_column",),
                    },
                ),
            },
        ),
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
        "external_artifacts": (),
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
#
# Forma de cada entrada de `answer_forms` (D-COL-6):
#
#   id       · identificador estable de la forma. Para un path cuyo schema es una unión discriminada
#              es EL discriminador, y un gate bidireccional exige que el conjunto de ids iguale
#              al de ramas: una quinta estrategia sin su forma pone rojo, y una forma sin rama
#              detrás, también.
#   label    · la forma en idioma de negocio, que es lo único que el usuario lee. Es copy y entra al
#              gate de jerga.
#   help     · cuándo conviene, y a qué obliga. Copy.
#   template · el fragmento de config que la forma produce, literal. Vive aquí y no en el front por
#              el mismo motivo que `presets.py`: elegir forma no puede exigirle a la interfaz que
#              reimplemente el dominio (SDD-23 §11). Un gate lo valida contra el modelo real del
#              path, así que una plantilla que el motor rechazaría no llega a la pantalla.
#   slots    · los huecos que la plantilla deja A PROPÓSITO, como rutas dentro del propio fragmento.
#              🔴 Son la diferencia entre pre-rellenar y auto-contestar (D-COL-8): la forma escribe
#              la ESTRUCTURA —que es lo que el usuario no tiene por qué saber construir— y deja el
#              DATO institucional en blanco. Mientras un slot siga vacío la decisión NO está
#              contestada, y el catálogo lo dice en vez de dejar que la interfaz lo adivine: sin
#              esto, escribir la plantilla marcaría la pregunta como respondida con los huecos
#              vacíos, que es exactamente el falso «ya está» que D-OBL-5 existe para impedir.
#
# ⚠️ Una decisión que se contesta con UN dato —una columna— declara `answer_forms: ()`. No es un
# olvido: no hay nada que elegir, y fabricarle una forma única sería una pantalla de más para
# preguntar lo mismo.
_DECISIONES_POR_SECCION: dict[str, tuple[dict[str, Any], ...]] = {
    "data": (
        {
            "path": "data.target.bad_rule",
            "question": "¿Qué define a un cliente malo en tu cartera?",
            "help": (
                "La condición con la que tu área marca el incumplimiento. Suele ser un corte de "
                "mora —«más de 90 días»—, a veces junto con otra condición. No hay un valor "
                "estándar: depende de tu política, y por eso lo eliges tú."
            ),
            "answer_forms": (
                {
                    "id": "condiciones",
                    "label": "La escribo como condiciones sobre mis columnas",
                    "help": (
                        "Para la política clásica: «más de 90 días de mora», sola o junto con otra "
                        "condición. Eliges la columna, la comparación y el corte."
                    ),
                    "template": {"all_of": [{"col": "", "op": "", "value": None}], "any_of": []},
                    "slots": ("all_of.0.col", "all_of.0.op", "all_of.0.value"),
                },
                {
                    "id": "columna_marcada",
                    "label": "Ya viene marcada en una columna de mi archivo",
                    "help": (
                        "Tu archivo trae la marca de incumplimiento ya calculada por tu área. "
                        "Dices qué columna la lleva y qué valor marca al malo; el motor no supone "
                        "que sea un 1."
                    ),
                    # `op` NO es un supuesto del motor: es lo que esta forma SIGNIFICA —«la columna
                    # vale tal cosa»—, y es justo lo que el usuario compra al elegirla. Lo que sí
                    # sería suponer es el valor, y por eso `value` es un hueco (D-COL-7).
                    "template": {"all_of": [{"col": "", "op": "==", "value": ""}], "any_of": []},
                    "slots": ("all_of.0.col", "all_of.0.value"),
                },
            ),
        },
        {
            "path": "data.partition.strategy",
            "question": "¿Cómo separas la muestra para validar?",
            "help": (
                "Al azar, por fecha, por cohortes, o leyendo una separación que tu archivo ya "
                "trae marcada en una columna. Si tus datos tienen eje de tiempo, separar por "
                "fecha mide mejor lo que pasará en producción, porque valida contra un período que "
                "el modelo no vio."
            ),
            "answer_forms": (
                {
                    "id": "temporal",
                    "label": "Por fecha: lo más reciente queda fuera de tiempo",
                    "help": (
                        "La opción que mejor anticipa producción, porque valida contra un período "
                        "que el modelo no vio. Necesita una columna de fecha y desde cuándo "
                        "empieza el período reservado."
                    ),
                    "template": {
                        "type": "temporal",
                        "date_col": "",
                        "oot_from": "",
                        "holdout_fraction": 0.2,
                    },
                    "slots": ("date_col", "oot_from"),
                },
                {
                    "id": "cohort",
                    "label": "Por cohortes, reservando algunas enteras",
                    "help": (
                        "Cuando tu cartera se agrupa en camadas —trimestres de originación, "
                        "campañas— y quieres reservar camadas completas en vez de cortar por una "
                        "fecha."
                    ),
                    "template": {
                        "type": "cohort",
                        "cohort_col": "",
                        "oot_cohorts": [],
                        "holdout_fraction": 0.2,
                    },
                    "slots": ("cohort_col", "oot_cohorts"),
                },
                {
                    "id": "columna",
                    "label": "Ya viene marcada en una columna de mi archivo",
                    "help": (
                        "Tu archivo ya trae la división que usa tu área. Dices qué columna la "
                        "lleva y qué valores corresponden a cada muestra; nada se adivina por "
                        "parecido de nombre ni por orden."
                    ),
                    "template": {
                        "type": "columna",
                        "partition_col": "",
                        "desarrollo": [],
                        "holdout": [],
                        "oot": [],
                    },
                    # `holdout` y `oot` quedan fuera de los huecos exigidos porque el motor admite
                    # mapear sólo algunas (D-COL-4). `desarrollo` sí entra: sin ella no hay muestra
                    # sobre la que ajustar, así que declararla no es suponer, es lo que el propio
                    # motor exige para poder modelar.
                    "slots": ("partition_col", "desarrollo"),
                },
                {
                    "id": "random",
                    "label": "Al azar, en tres trozos",
                    "help": (
                        "Reparte las filas al azar. ⚠️ El trozo «fuera de tiempo» que produce NO es "
                        "posterior en el tiempo: sale del mismo período que el resto, así que mide "
                        "menos de lo que su nombre promete. Úsala sólo si tus datos no tienen "
                        "ninguna columna de fecha ni de camada."
                    ),
                    # Única forma sin huecos: las tres fracciones son defaults del motor, no
                    # criterio institucional, y elegir esta forma ya es la respuesta completa.
                    "template": {
                        "type": "random",
                        "dev_fraction": 0.7,
                        "holdout_fraction": 0.15,
                        "oot_fraction": 0.15,
                        "stratify_by": None,
                    },
                    "slots": (),
                },
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
            "answer_forms": (),
        },
        {
            "path": "survival.input.event_col",
            "question": "¿Qué columna dice si el evento llegó a ocurrir?",
            "help": (
                "Distingue a quien incumplió de quien seguía sano cuando terminó la observación. "
                "Sin ella las dos situaciones se confunden y las curvas salen sesgadas."
            ),
            "answer_forms": (),
        },
    ),
}


def _exige_claves(entrada: dict[str, Any], esperadas: frozenset[str], que: str) -> None:
    """Falla si el literal trae una clave que este serializador no sabe publicar.

    🔴 Es el mecanismo que los serializadores de abajo decían tener y no tenían. Escribirlos campo
    a campo hace que una clave nueva **no se cuele** al contrato REST con la forma que tuviera, pero
    por sí solo NO avisa: la descarta en silencio. Medido — añadir una clave al literal de
    ``external_artifacts`` dejaba los 31 gates del catálogo en verde y el dato desaparecía por el
    camino. Eso convierte cualquier campo nuevo en una feature muerta y silenciosa, que es el modo
    de fallo que este repo ya pagó con D-JOB-17 (implementado, probado y sin una sola llamada).
    """
    sobran = sorted(set(entrada) - esperadas)
    faltan = sorted(esperadas - set(entrada))
    if sobran or faltan:
        raise ValueError(
            f"{que}: el literal del catálogo no cuadra con lo que se publica"
            + (f"; sobra(n) {sobran} —decide cómo viaja(n) al contrato REST" if sobran else "")
            + (f"; falta(n) {faltan}" if faltan else "")
        )


_CLAVES_DE_FORMA = frozenset({"id", "label", "help", "template", "slots"})
_CLAVES_DE_DECISION = frozenset({"path", "question", "help", "answer_forms"})


def _forma_json(forma: dict[str, Any]) -> dict[str, Any]:
    """Copia JSON-able de una forma de respuesta (D-COL-6), campo a campo."""
    _exige_claves(forma, _CLAVES_DE_FORMA, f"forma de respuesta {forma.get('id')!r}")
    return {
        "id": forma["id"],
        "label": forma["label"],
        "help": forma["help"],
        # La plantilla es dato arbitrario del schema del path: se copia en profundidad tal cual,
        # convirtiendo las tuplas del literal en listas para que viaje por JSON.
        "template": _json_profundo(forma["template"]),
        "slots": list(forma["slots"]),
    }


def _json_profundo(valor: Any) -> Any:
    """Vuelve JSON-able un fragmento de plantilla sin perder su forma (tuplas → listas)."""
    if isinstance(valor, dict):
        return {clave: _json_profundo(hijo) for clave, hijo in valor.items()}
    if isinstance(valor, tuple | list):
        return [_json_profundo(hijo) for hijo in valor]
    return valor


def decisiones_de(secciones: Iterable[str]) -> list[dict[str, Any]]:
    """Decisiones obligatorias de un conjunto de secciones, sin repetir y en orden estable.

    El orden es el de ``_DECISIONES_POR_SECCION``, no el de ``secciones``: dos trabajos con las
    mismas secciones en distinto orden tienen que preguntar lo mismo en el mismo orden, o la
    interfaz dependería de cómo se escribió el catálogo.

    Devuelve copias **profundas**: con `answer_forms` la decisión dejó de ser plana, y un
    ``dict(decision)`` habría entregado al llamador las mismas plantillas del literal del módulo.
    """
    presentes = set(secciones)
    return [
        _decision_json(decision)
        for seccion, decisiones in _DECISIONES_POR_SECCION.items()
        if seccion in presentes
        for decision in decisiones
    ]


def _decision_json(decision: dict[str, Any]) -> dict[str, Any]:
    """Copia JSON-able de una decisión obligatoria, campo a campo."""
    _exige_claves(decision, _CLAVES_DE_DECISION, f"decisión {decision.get('path')!r}")
    return {
        "path": decision["path"],
        "question": decision["question"],
        "help": decision["help"],
        "answer_forms": [_forma_json(f) for f in decision["answer_forms"]],
    }


def _insumo_json(entrada: dict[str, Any]) -> dict[str, Any]:
    """Copia JSON-able de una entrada de ``external_artifacts`` (tuplas → listas, en profundidad).

    Se escribe campo a campo y no con un ``deepcopy`` genérico para que **añadir una clave al
    literal sin decidir cómo viaja** rompa aquí, en vez de colarse al contrato REST con la forma
    que tuviera. El `_exige_claves` es lo que hace verdadera esa frase: sin él la clave nueva se
    descartaba en silencio y el docstring prometía una guarda que no existía.
    """
    _exige_claves(
        entrada,
        frozenset({"artifact", "label", "when", "key_question", "columns"}),
        f"insumo externo {entrada.get('label')!r}",
    )
    condicion = entrada["when"]
    return {
        "artifact": list(entrada["artifact"]),
        "label": entrada["label"],
        "when": None if condicion is None else dict(condicion),
        "key_question": entrada["key_question"],
        "columns": [
            {"question": columna["question"], "config_paths": list(columna["config_paths"])}
            for columna in entrada["columns"]
        ],
    }


def artefactos_admitidos() -> frozenset[tuple[str, str]]:
    """Allowlist de la puerta por HTTP: lo que algún trabajo DISPONIBLE acepta de fuera (D-PUE-2).

    Sólo cuentan los disponibles. Un trabajo que no se puede iniciar no puede prestar su clave para
    que otro la inyecte, y declarar por adelantado lo que un trabajo aceptará el día que se
    desbloquee es información útil que no tiene por qué abrir superficie hoy.

    ⚠️ Esta restricción es **de la red**, no del motor: por código la puerta sigue siendo general
    y admite cualquier clave válida del vocabulario de dominios. Acotarla aquí evita que un cliente
    local siembre claves arbitrarias y desplace cálculos que el usuario cree que se están haciendo.
    """
    return frozenset(
        (str(entrada["artifact"][0]), str(entrada["artifact"][1]))
        for job in _JOBS
        if job["status"] == _AVAILABLE
        for entrada in job["external_artifacts"]
    )


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
            "external_artifacts": [_insumo_json(e) for e in job["external_artifacts"]],
            "required_decisions": decisiones_de(job["sections"]),
        }
        for job in _JOBS
    ]
