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

__all__ = ["JOB_IDS", "abanico_de", "artefactos_admitidos", "decisiones_de", "list_jobs"]

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
#   overrides     · valores que este trabajo siembra POR ENCIMA del default del motor (D-EJE-2)
#   jurisdiction_*   · país cuya normativa impone el cálculo; `None` = neutral (D-JOB-8)
#   status / unavailable_reason
#
# 🔴 `overrides` existe porque un default del motor puede ser correcto para la librería y dejar
# INEJECUTABLE a un trabajo concreto. Medido: tres de los diez nacían así —dos porque el default de
# la fuente de PD de `survival` exige un artefacto que produce una sección que esos trabajos no
# ofrecen—. Es la misma clase que D-OBL-11 cerró para los capítulos del informe, y hasta ahora el
# único ajuste post-siembra estaba **cableado a mano a un solo path** en el front.
#
# ⚠️ Vive en el CATÁLOGO y no en el front, aunque la siembra sea del front, por la misma razón que
# D-JOB-3 puso aquí el catálogo entero: **el gate que comprueba ejecutabilidad es Python**. Con los
# overrides aquí, ese gate los aplica desde la misma fuente que la pantalla consume, en vez de
# reimplementar una lista paralela que podría divergir en silencio.
#
# ⚠️ Y NO absorbe el recorte de capítulos del informe (D-EJE-3): aquél es una **intersección
# calculada** con las secciones del trabajo, no un valor fijo, y meterlo aquí obligaría a convertir
# este campo en un lenguaje. Son dos piezas contiguas y distintas.
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
        "overrides": (),
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
        # Vacío a propósito, y no es un olvido: con la fuente de PD que este trabajo siembra
        # —ver `overrides`— `survival` no requiere ninguna clave, así que no hay nada que traer por
        # la puerta. El copy de arriba describe un insumo **opcional del método**, no un artefacto
        # del motor. Los dos campos miden cosas distintas y por eso pueden no coincidir.
        "external_artifacts": (),
        # 🔴 Sin esto el trabajo NACE INEJECUTABLE, y así estuvo hasta el 2026-08-04. El default del
        # motor para la fuente de PD de `survival` es la del modelo sin calibrar, que exige un
        # artefacto que produce la sección `model` — y este trabajo no la ofrece ni admite subir esa
        # tabla. Medido: `check_pipeline` daba `executable=False`, y el comentario que decía que
        # «survival no REQUIERE la PD» era cierto **sólo** para el valor que ahora se siembra.
        # El preset F4 ya lo escribía a mano por la misma razón (`ui/presets.py`).
        "overrides": (("survival.input.pd_source", "none"),),
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
        "external_input": "La PD calibrada de tu modelo, por operación.",
        # 🔴 Sin esta puerta el trabajo NACE INEJECUTABLE: el método interno exige la PD calibrada
        # y este trabajo no activa la sección que la produce. Su hermano «Provisión interna / LGD»
        # la declaraba desde el principio con el mismo `when` — el mismo problema, resuelto en el
        # trabajo de al lado y no en éste.
        "external_artifacts": (
            {
                "artifact": ("calibration", "calibrated_pd_frame"),
                "label": "La PD calibrada de tu modelo, por operación",
                "when": {
                    "path": "provisioning_internal.pd_source",
                    "equals": "calibration",
                },
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
        "overrides": (),
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
        # Misma causa que en «PD lifetime», y el censo de defectos no la había visto: el default de
        # la fuente de PD de `survival` exige la sección `model`, que este trabajo tampoco ofrece.
        # Aquí la curva alimenta la ECL lifetime, así que se ajusta con lo que trae el archivo.
        "overrides": (("survival.input.pd_source", "none"),),
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
        "overrides": (),
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
        "overrides": (),
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
        "external_input": "La PD calibrada de tu modelo, por operación.",
        # 🔴 Sin esta puerta el trabajo NACE INEJECUTABLE: el método interno exige la PD calibrada
        # y este trabajo no activa la sección que la produce. Su hermano «Provisión interna / LGD»
        # la declaraba desde el principio con el mismo `when` — el mismo problema, resuelto en el
        # trabajo de al lado y no en éste.
        "external_artifacts": (
            {
                "artifact": ("calibration", "calibrated_pd_frame"),
                "label": "La PD calibrada de tu modelo, por operación",
                "when": {
                    "path": "provisioning_internal.pd_source",
                    "equals": "calibration",
                },
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
        "overrides": (),
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
        "overrides": (),
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
        # El rótulo decía «por regresión» y dejó de ser cierto al entrar el proceso de recuperación,
        # que explícitamente NO ajusta ningún modelo. Es el nombre que se lee en la portada y en el
        # sidebar, o sea la superficie más visible del trabajo.
        "label": "Severidad modelada o calculada",
        # 🔴 La descripción anterior prometía modelar «con las mismas variables discretizadas del
        # scorecard» y el trabajo declaraba `binning` entre sus secciones. Las dos cosas se
        # retiraron juntas al implementar D-LGD-7, y no por alcance sino por MÉTODO: esa
        # codificación es supervisada contra el target de INCUMPLIMIENTO, y usarla como variable
        # explicativa de la SEVERIDAD —otro objetivo, condicional a haber incumplido— importa esa
        # supervisión dentro del modelo de LGD. Dejar la frase habría sido prometer una capacidad
        # que se descartó a propósito; dejar `binning` habría sido prometerla por la puerta de
        # atrás, porque la sección sólo está ahí para producir esas variables.
        "description": (
            "Modelar la severidad con las variables de tu archivo, o calcularla descontando lo "
            "que ya recuperaste, en vez de traerla dada o promediarla por grupo."
        ),
        "sections": ("data", "provisioning_internal", "report"),
        "missing_sections": (),
        "external_input": "La PD de tu modelo, calibrada o sin calibrar.",
        # 🔴 Las DOS puertas, como sus hermanos `provision_interna` y `comparar_provisiones`. Con el
        # trabajo no disponible bastaba una: `artefactos_admitidos()` sólo mira los trabajos
        # DISPONIBLES, y un comentario lo declaraba inocuo. Al pasar a disponible esa condición dejó
        # de cumplirse, y su abanico ofrece `pd_source='model'` — o sea que quien eligiera «la
        # probabilidad sin calibrar» se quedaba sin dónde subirla.
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
        # Sin override, y es deliberado (D-LGD-12). El esqueleto arranca en la forma OBSERVADA
        # porque es la única que se construye sin un dato que sólo el usuario tiene: modelar exige
        # decir qué variables suyas explican la severidad, y calcular por recuperos exige la columna
        # de lo recuperado. Forzar aquí una rama modelada dejaría el esqueleto inconstruible.
        # ⚠️ Por eso mismo el gate de aceptación de este trabajo NO es que aparezca disponible —eso
        # sólo mide que el pipeline resuelva, con `method="provided"`—: es una corrida end-to-end a
        # `done` con la rama modelada puesta, que vive en
        # `test_internal_provisioning_lgd_modelada.py`.
        "overrides": (),
        "jurisdiction_code": None,
        "jurisdiction_label": None,
        "status": _AVAILABLE,
        "unavailable_reason": None,
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
        "overrides": (),
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
#   slots    · los huecos que la plantilla deja A PROPÓSITO, dentro del propio fragmento. Tres
#              formas, y las dos condicionales existen porque la lista plana declaraba incompletas
#              respuestas que el motor acepta:
#                "ruta"                                    · hueco simple, siempre exigido
#                {"path": …, "salvo_si": {"path", "vale"}} · exigido salvo que otro campo del
#                                                            fragmento tome uno de esos valores
#                {"alguno_de": (…)}                        · basta con que UNO de ellos se llene
#              ⚠️ La condición viaja como DATO y la evalúa el front sin saber qué significa: es el
#              mismo mecanismo que el `when` de `external_artifacts`, y por la misma razón —que la
#              interfaz no puede reimplementar la regla del dominio (SDD-23 §11)—.
#              🔴 Son la diferencia entre pre-rellenar y auto-contestar (D-COL-8): la forma escribe
#              la ESTRUCTURA —que es lo que el usuario no tiene por qué saber construir— y deja el
#              DATO institucional en blanco. Mientras un slot siga vacío la decisión NO está
#              contestada, y el catálogo lo dice en vez de dejar que la interfaz lo adivine: sin
#              esto, escribir la plantilla marcaría la pregunta como respondida con los huecos
#              vacíos, que es exactamente el falso «ya está» que D-OBL-5 existe para impedir.
#   precargas· los huecos que pueden llegar PROPUESTOS desde una columna que el trabajo ya preguntó
#              (D-COL-8). Cada entrada declara:
#                slot   · el hueco de ESTA plantilla que se propone, mismo vocabulario que `slots`
#                desde  · dónde el trabajo ya preguntó por esa misma columna. El VALOR no está aquí
#                         —lo escribió el usuario— y sale del config en tiempo de render
#                insumo · el artefacto externo del que salió esa respuesta. La propuesta sólo
#                         procede si ese archivo declara el MISMO `dataset_id` que la cartera:
#                         el motor lee esta columna de la cartera, así que pegar ahí una columna de
#                         otro archivo sería un error de categoría SILENCIOSO
#                nota   · la procedencia, en idioma de negocio. Copy: entra al gate de jerga
#              🔴 Va aquí y NO en los `config_paths` del insumo externo, y la diferencia no es
#              cosmética: un `config_path` ESCRIBE SOLO, y una precarga PROPONE y espera el gesto.
#              El gate de §4 de la enmienda prohíbe lo primero sobre un path de decisión, y hace
#              bien — es la misma frontera que D-OBL-5. Como el config no se toca hasta que el
#              usuario elige la forma, el estado de la decisión no se mueve por tener una propuesta
#              disponible, y un clic escribe exactamente lo que él habría escrito a mano: mismo
#              `config_hash` por los dos caminos (D-OBL-10 / D-JOB-9 intactos).
#              ⚠️ Es autolimitante a propósito: un trabajo que no declara ese insumo no tiene de
#              dónde proponer, así que la misma forma —que se declara por SECCIÓN y la heredan los
#              nueve trabajos— no ofrece nada donde no corresponde, sin necesidad de condicionarla
#              por trabajo.
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
                    "slots": (
                        "all_of.0.col",
                        "all_of.0.op",
                        # 🔴 `isna`/`notna` preguntan por la AUSENCIA de dato: no llevan valor con
                        # qué comparar, y exigirlo dejaba una regla perfectamente válida marcada
                        # como incompleta para siempre. Lo destapó la revisión adversarial.
                        {
                            "path": "all_of.0.value",
                            "salvo_si": {"path": "all_of.0.op", "vale": ("isna", "notna")},
                        },
                    ),
                    # Esta forma construye la política —«más de 90 días de mora»—, así que su
                    # columna es la de MORA, no la que ya trae el resultado observado. Proponer
                    # aquí la del incumplimiento empujaría a contestar una cosa con la otra.
                    "precargas": (),
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
                    "slots": (
                        "all_of.0.col",
                        {
                            "path": "all_of.0.value",
                            "salvo_si": {"path": "all_of.0.op", "vale": ("isna", "notna")},
                        },
                    ),
                    # 🔴 El caso de D-COL-8, medido: «Validar un modelo existente» ya le preguntó al
                    # usuario qué columna dice si la operación terminó incumpliendo, y acto seguido
                    # esta decisión le vuelve a preguntar lo mismo. Se propone la columna; el VALOR
                    # que marca al malo sigue siendo hueco, porque eso es criterio institucional y
                    # nadie lo puede suponer (D-COL-7).
                    "precargas": (
                        {
                            "slot": "all_of.0.col",
                            "desde": "performance.target_column",
                            "insumo": ("calibration", "calibrated_pd_frame"),
                            "nota": (
                                "es la columna que ya dijiste que marca si la operación terminó "
                                "incumpliendo"
                            ),
                        },
                    ),
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
                    # La columna que el trabajo ya preguntó dice a qué MUESTRA pertenece cada
                    # operación, no en qué fecha ocurrió: no hay nada que proponer aquí.
                    "precargas": (),
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
                    # Idem: una camada de originación no es la muestra a la que se asignó cada
                    # operación, aunque en algunas carteras coincidan.
                    "precargas": (),
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
                    "slots": (
                        "partition_col",
                        # 🔴 D-COL-4 al pie de la letra: las particiones exigidas son EXACTAMENTE
                        # las que el usuario mapeó, así que no se puede reclamar `desarrollo` — una
                        # institución que sólo separa validación tiene una respuesta completa. Lo
                        # que el motor sí exige es que haya AL MENOS UNA, y eso es lo que se pide.
                        # La versión anterior exigía `desarrollo` y marcaba incompleta una decisión
                        # que el motor acepta: era el motor reclamando una muestra que nadie separa.
                        {"alguno_de": ("desarrollo", "holdout", "oot")},
                    ),
                    # 🔴 La otra mitad del caso de D-COL-8: la misma columna que el trabajo ya
                    # preguntó —«¿cuál dice a qué muestra pertenece cada operación?»— es exactamente
                    # lo que esta forma necesita. El MAPEO de valores a las tres muestras no se
                    # propone: qué vale «DEV» en esta institución no lo sabe el motor (D-COL-3).
                    "precargas": (
                        {
                            "slot": "partition_col",
                            "desde": "performance.partition_column",
                            "insumo": ("calibration", "calibrated_pd_frame"),
                            "nota": (
                                "es la columna que ya dijiste que marca a qué muestra pertenece "
                                "cada operación"
                            ),
                        },
                    ),
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
                    # Sortear las filas no usa ninguna columna del usuario.
                    "precargas": (),
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


#: Estados en que una opción del abanico puede llegar al usuario (D-ABA-4).
#:
#: Son CUATRO declarados aquí, más un quinto que **no se declara: se computa**. «No puedes usar esto
#: porque tu archivo no trae la pérdida observada» depende del archivo, no de la opción, y
#: afirmarlo desde el catálogo sería hablar de datos que el catálogo no ha visto — el error de
#: categoría que D-PRE-1 existe para impedir. Ése lo emite el preflight.
#:
#: ⚠️ Hasta el 2026-08-08 eran TRES, y el cuarto de esta lista se creía cubierto por el que se
#: computa. **Medido, no lo estaba**: para que el preflight opine el config tiene que construir, y
#: las tres ramas modeladas de LGD **no construyen** (D-EXI-1). El preflight ni se llama —va
#: encadenado detrás de la validación, y con el config inválido queda en `idle`—, así que el
#: estado que debía contestar esto estaba apagado justo para las opciones que lo necesitaban.
_DISPONIBLE = "disponible"

#: El motor NO la tiene. Se muestra igual, en gris y con su motivo: ocultarla dejaría al usuario
#: creyendo que la librería no la contempla, que es la mentira contraria (D-JOB-5).
#:
#: ⚠️ Obliga a las DOS superficies en el mismo commit (D-ABA-5): el catálogo lo dice antes y el
#: validador del motor lo impide después. Rotularla sólo aquí deja el defecto vivo para quien llega
#: por YAML o por código —el 100 % de quien usa esto como librería—; cerrarla sólo en el validador
#: convierte una elección legítima en un error críptico, que era el estado de antes.
_NO_IMPLEMENTADA = "no_implementada"

#: El motor la acepta y **no cambia el resultado**. Es elegible, con su advertencia.
#:
#: ⚠️ Se declara con su medición citada, nunca por sospecha (D-ABA-6): decirle al usuario «esto no
#: va a cambiar tu resultado» es una afirmación fuerte sobre el motor, y sin la disciplina de la
#: cita el estado se convierte en un vertedero de dudas. La cita vive en ``prueba``.
_SIN_EFECTO = "sin_efecto"

#: El motor la tiene, pero **elegirla sola no basta**: exige que declares otro campo del config, y
#: hasta que lo declares el config no se construye (D-EXI-2).
#:
#: 🔴 No es «no implementada» y vetarlo importa: rotular así las tres ramas modeladas de LGD
#: cerraría la deuda **con todos los gates verdes publicando una falsedad** —que la librería no
#: tiene LGD modelada— el día después de implementarla, y el gate de D-ABA-5 exige justamente lo
#: contrario. Y tampoco es ``disponible``: D-ABA-3 prohíbe ofrecer como elegible algo que el
#: motor rechaza.
#:
#: ⚠️ **Exige la clave ``exige``** con la ruta del campo que hay que declarar, y ahí está la
#: diferencia con lo que ya existía: la exigencia SÍ estaba escrita antes, pero como **prosa dentro
#: de ``help``**, donde no la puede leer ninguna máquina ni pintar el front distinto. Con la ruta
#: declarada, el mismo dato sirve para el rótulo, para el salto al control y para el gate.
_EXIGE_OTRO_CAMPO = "exige_otro_campo"

_ESTADOS_DE_OPCION = frozenset({_DISPONIBLE, _NO_IMPLEMENTADA, _SIN_EFECTO, _EXIGE_OTRO_CAMPO})


#: El abanico metodológico, por SECCIÓN y no por trabajo (D-ABA-1/2/3).
#:
#: 🔴 **Se declara a mano, con gate bidireccional contra los literales del motor**, y no se deriva
#: del schema. Tres razones, en orden de peso: (1) lo que el abanico ES no está en el schema — del
#: schema sale ``"beta_regression"``, no «la estimo con un modelo sobre mis variables» ni «necesita
#: que tu archivo traiga la pérdida observada», que es el 100 % de lo que D-JOB-4/5 piden; (2) del
#: schema saldrían las opciones que el motor **rechaza**, y ofrecerlas es prometer una elección
#: falsa; (3) el precedente ya está escrito y probado en las formas de respuesta de D-COL-6. El
#: riesgo de declarar a mano —desincronizarse en silencio— lo cierra el gate, en las dos
#: direcciones y sobre las dos caras: opciones que sobran y puntos de elección que faltan.
#:
#: Por sección y no por trabajo, por la misma razón medida que ``_DECISIONES_POR_SECCION``: ocho de
#: los diez trabajos incluyen `data`, así que declarar por trabajo copiaría el mismo texto ocho
#: veces y la primera vez que alguien afinara el copy, siete quedarían atrás en silencio.
_ABANICO_POR_SECCION: dict[str, tuple[dict[str, Any], ...]] = {
    "data": (
        {
            "path": "data.load.backend",
            "question": "¿Con qué motor quieres leer tu archivo?",
            "help": (
                "Cambia la velocidad de lectura, nunca el resultado: el contenido que llega al "
                "cálculo es el mismo y las cifras del informe no se mueven."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "pandas",
                    "label": "El lector estándar",
                    "help": "Viene incluido y sirve para cualquier tamaño de archivo habitual.",
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "polars",
                    "label": "El lector rápido, para archivos grandes",
                    "help": (
                        "Acelera la lectura de archivos muy grandes. Se instala aparte: si no "
                        "está en tu entorno, la corrida se detiene al abrir el archivo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "data.load.file_format",
            "question": "¿En qué formato viene tu archivo?",
            "help": (
                "Puedes dejar que se reconozca por la extensión, o decirlo tú si el archivo no la "
                "trae o la trae equivocada."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "auto",
                    "label": "Reconocerlo por la extensión",
                    "help": "Mira cómo termina el nombre del archivo y elige el lector que toca.",
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "csv",
                    "label": "Texto separado por comas",
                    "help": "El formato más portable; no transporta el índice de las filas.",
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "parquet",
                    "label": "Parquet",
                    "help": (
                        "Formato columnar comprimido: conserva los tipos y el índice, y es el más "
                        "rápido de leer."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "excel",
                    "label": "Planilla de Excel",
                    "help": (
                        "Lee la primera hoja del libro. Se instala aparte: si no está en tu "
                        "entorno, la corrida se detiene al abrir el archivo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "stability": (
        {
            "path": "stability.comparisons",
            "question": "¿Contra qué muestras quieres comparar la de Desarrollo?",
            "help": (
                "La estabilidad se mide comparando cada muestra contra Desarrollo, que hace de "
                "población esperada. Puedes pedir una comparación o las dos."
            ),
            "multiple": True,
            "options": (
                {
                    "value": "dev_vs_holdout",
                    "label": "Contra la muestra de validación",
                    "help": (
                        "Responde si el modelo se comporta igual sobre clientes del mismo período "
                        "que no usó para ajustarse."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "dev_vs_oot",
                    "label": "Contra la muestra fuera de tiempo",
                    "help": (
                        "Responde si el modelo aguanta en un período posterior, que es la pregunta "
                        "que interesa a quien lo va a poner en producción."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "stability.csi_source",
            "question": "¿Sobre qué se mide el desplazamiento de las características?",
            "help": (
                "El indicador compara cómo se reparten los clientes entre tramos en una muestra y "
                "en otra. Lo que cambia aquí es qué tramos se usan para ese reparto."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "score_points",
                    "label": "Los puntos que aporta cada característica",
                    "help": (
                        "Usa el puntaje que cada variable suma en la tarjeta, que es lo que el "
                        "modelo realmente aplica a cada cliente."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "woe_bins",
                    "label": "Los tramos con que se discretizó cada variable",
                    "help": (
                        "Compararía el reparto sobre los tramos originales en vez de sobre los "
                        "puntos de la tarjeta."
                    ),
                    "estado": _NO_IMPLEMENTADA,
                    "motivo": (
                        "El motor todavía no la calcula: el nombre está reservado para cuando se "
                        "implemente, y elegirla hoy detiene la corrida antes de empezar."
                    ),
                    "prueba": None,
                },
            ),
        },
        {
            "path": "stability.score_direction",
            "question": "En tu escala, ¿un puntaje más alto significa mejor o peor cliente?",
            "help": (
                "Describe el puntaje que se está midiendo, y queda escrito en la ficha del "
                "informe. Los indicadores de estabilidad no cambian con la respuesta —comparan "
                "cómo se reparte la población, y eso no depende de hacia dónde crece el puntaje—, "
                "pero tiene que decir lo mismo que la escala con que se construyó la tarjeta: si "
                "se contradicen, la corrida se detiene antes de publicar dos respuestas distintas."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "higher_is_lower_risk",
                    "label": "Más alto es mejor cliente",
                    "help": (
                        "La convención más habitual: a mayor puntaje, menor probabilidad de "
                        "incumplir."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "higher_is_higher_risk",
                    "label": "Más alto es peor cliente",
                    "help": "Para escalas donde el puntaje mide riesgo y no calidad crediticia.",
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "stability.temporal_axis",
            "question": "¿Cómo quieres seguir el comportamiento del modelo en el tiempo?",
            "help": (
                "Decide si el informe muestra la evolución período a período, por camada de "
                "clientes, o si no muestra evolución temporal."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "none",
                    "label": "No seguirlo en el tiempo",
                    "help": (
                        "La opción correcta si tu archivo no trae ninguna columna de fecha o de "
                        "período: el resto del análisis se calcula igual."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "period",
                    "label": "Por período de observación",
                    "help": (
                        "Agrupa por la fecha en que se observó cada operación. Necesita que tu "
                        "archivo traiga una columna de fecha o de período."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "cohort",
                    "label": "Por camada de originación",
                    "help": (
                        "Agrupa por el momento en que se originó cada operación, que es lo que "
                        "interesa cuando se compara la calidad de lo que se fue colocando."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "stability.temporal_freq",
            "question": "¿Cada cuánto quieres agrupar el seguimiento en el tiempo?",
            "help": (
                "Sólo se aplica si eliges seguir el comportamiento en el tiempo, y sólo si la "
                "columna que lo marca es una fecha: sobre un período ya escrito como texto, el "
                "motor respeta la agrupación que traiga tu archivo."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "M",
                    "label": "Mensual",
                    "help": "El detalle más fino; útil con volúmenes altos por mes.",
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "Q",
                    "label": "Trimestral",
                    "help": "Suaviza el ruido de meses con pocas operaciones.",
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "Y",
                    "label": "Anual",
                    "help": "Para carteras de rotación lenta o historias largas.",
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "binning": (
        {
            "path": "binning.max_pvalue_policy",
            "question": "¿Entre qué tramos exiges que la diferencia de riesgo sea significativa?",
            "help": (
                "Sólo interviene si además fijaste un p-valor máximo entre tramos: si lo dejaste "
                "sin fijar, el motor no aplica esa prueba y esta elección no cambia tu resultado."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "consecutive",
                    "label": "Sólo entre tramos vecinos",
                    "help": (
                        "Exige que cada tramo se distinga del que tiene al lado. Es la lectura "
                        "habitual: basta con que la escalera de riesgo no tenga peldaños repetidos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "all",
                    "label": "Entre todos los pares de tramos",
                    "help": (
                        "Exige que cualquier par de tramos, vecinos o no, se distinga entre sí. Es "
                        "más estricto y suele terminar en menos tramos y mejor separados."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "binning.mip_solver",
            "question": "¿Con qué motor de optimización quieres resolver el corte de los tramos?",
            "help": (
                "Cambia la implementación que busca los cortes, no el criterio con que se eligen: "
                "los dos resuelven el mismo problema y llegan al mismo conjunto de tramos."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "bop",
                    "label": "El motor de optimización binaria",
                    "help": (
                        "Es el que viene puesto y el que se usa en los ejemplos; funciona para "
                        "cualquier cartera de tamaño habitual."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "cbc",
                    "label": "El motor de optimización mixta",
                    "help": (
                        "Alternativa equivalente, ya incluida en tu entorno. Cámbiala sólo por un "
                        "motivo técnico puntual: entrega los mismos tramos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "binning.monotonic_trend",
            "question": "¿Qué forma debe tener la relación entre cada variable y el riesgo?",
            "help": (
                "Es la regla que ordena los tramos y evita que la tarjeta contradiga el criterio "
                "experto. Sobre una variable de texto no se aplica: ahí el motor siempre ordena "
                "los tramos de menor a mayor riesgo, elijas la forma que elijas."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "auto",
                    "label": "Que el motor la deduzca, explorando todas las formas",
                    "help": (
                        "Prueba las formas disponibles variable por variable y se queda con la que "
                        "más poder predictivo conserva. Es la más lenta de las automáticas."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "auto_heuristic",
                    "label": "Que el motor la deduzca, por la vía rápida",
                    "help": (
                        "Igual que la anterior, pero ubica el punto de quiebre con una regla "
                        "aproximada. Notoriamente más rápida cuando exploras muchos cortes."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "auto_asc_desc",
                    "label": "Que el motor elija entre creciente y decreciente",
                    "help": (
                        "Deja que el motor decida el sentido, pero le prohíbe formas con quiebre. "
                        "Es la opción por defecto y la más defendible ante un validador."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "ascending",
                    "label": "Creciente: a mayor valor, mayor riesgo",
                    "help": (
                        "Fuerza el sentido. Úsala cuando conoces de antemano el comportamiento "
                        "esperado, por ejemplo en días de mora o en nivel de endeudamiento."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "descending",
                    "label": "Decreciente: a mayor valor, menor riesgo",
                    "help": (
                        "El sentido inverso, para variables donde más es mejor: antigüedad del "
                        "cliente, renta o puntaje de un buró externo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "concave",
                    "label": "Cambia cada vez menos",
                    "help": (
                        "El riesgo se mueve en un sentido con efecto que se va agotando, sin "
                        "quiebres bruscos. Sirve cuando el efecto se satura en el tramo alto."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "convex",
                    "label": "Cambia cada vez más",
                    "help": (
                        "El riesgo se mueve en un sentido con efecto que se acelera. Sirve cuando "
                        "el deterioro se dispara recién en los valores extremos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "peak",
                    "label": "Sube y después baja",
                    "help": (
                        "Admite un máximo de riesgo en la mitad del rango. El punto de quiebre se "
                        "busca de forma exacta, lo que cuesta más tiempo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "peak_heuristic",
                    "label": "Sube y después baja, con el quiebre aproximado",
                    "help": (
                        "La misma forma, ubicando el máximo con una regla aproximada. La "
                        "alternativa razonable si la búsqueda exacta se demora demasiado."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "valley",
                    "label": "Baja y después sube",
                    "help": (
                        "Admite un mínimo de riesgo en la mitad del rango, la forma típica de la "
                        "edad o del monto. El punto de quiebre se busca de forma exacta."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "valley_heuristic",
                    "label": "Baja y después sube, con el quiebre aproximado",
                    "help": (
                        "La misma forma, ubicando el mínimo con una regla aproximada, para cuando "
                        "la búsqueda exacta se hace cara."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "binning.solver",
            "question": "¿Con qué técnica quieres que se busquen los cortes de los tramos?",
            "help": (
                "Es la familia de optimización que arma los tramos. Hoy sólo una de las dos está "
                "operativa, y es la que viene puesta."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "cp",
                    "label": "Programación por restricciones",
                    "help": (
                        "Resolvería el mismo problema con otra familia de técnicas, pensada para "
                        "restricciones combinatorias."
                    ),
                    "estado": _NO_IMPLEMENTADA,
                    "motivo": (
                        "Hoy no se puede usar: sobre variables continuas se queda pegada sin "
                        "término y sin respetar el límite de tiempo, que es la peor forma de "
                        "fallar. Por eso elegirla detiene la corrida al llegar al agrupamiento en "
                        "tramos, después de haber cargado tus datos."
                    ),
                    "prueba": None,
                },
                {
                    "value": "mip",
                    "label": "Programación entera mixta",
                    "help": (
                        "La técnica en uso: encuentra el corte óptimo y respeta el límite de "
                        "tiempo que le fijes por variable."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "binning.special_handling",
            "question": "¿Qué hacemos con los valores especiales que declaraste en tus datos?",
            "help": (
                "Son los códigos centinela del tipo «sin información» o «no aplica». Si no "
                "declaraste ninguno al describir tus datos, esta elección no cambia tu resultado."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "separate",
                    "label": "Darles un tramo propio",
                    "help": (
                        "Los deja aparte, con su propio nivel de riesgo medido. Es lo indicado "
                        "cuando «sin información» dice algo del cliente, que suele ser el caso."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "as_missing",
                    "label": "Juntarlos con los faltantes",
                    "help": (
                        "Los fusiona con los datos ausentes en un solo tramo. Elígelo si el "
                        "centinela significa exactamente lo mismo que un dato que no llegó."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "binning.variable_overrides.dtype",
            "question": "Para una variable en particular, ¿cómo debe leerse su contenido?",
            "help": (
                "Sirve para corregir a mano el tipo de una variable puntual cuando la lectura "
                "automática se equivoca; el resto de las variables no se ve afectado."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "numerical",
                    "label": "Como una cantidad, en rangos",
                    "help": (
                        "Corta la variable en rangos ordenados. Necesita que la columna sea "
                        "numérica de verdad: sobre texto, la corrida se detiene al agrupar."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "categorical",
                    "label": "Como una categoría, nivel por nivel",
                    "help": (
                        "Agrupa por valores distintos en vez de por rangos. Es lo correcto para un "
                        "código guardado como número: región, sucursal o tipo de producto."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "auto",
                    "label": "Como venga en el archivo",
                    "help": (
                        "Deja que el tipo del dato mande: los textos se agrupan por categoría y "
                        "los números se cortan en rangos. Es lo que ocurre si no intervienes."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "binning.variable_overrides.monotonic_trend",
            "question": (
                "Para una variable en particular, ¿qué forma tiene su relación con el riesgo?"
            ),
            "help": (
                "Anula la regla general sólo para esa variable, cuando sabes que se comporta "
                "distinto al resto. Déjala en blanco para que siga la regla general."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "auto",
                    "label": "Que el motor la deduzca, explorando todas las formas",
                    "help": (
                        "Prueba las formas disponibles y se queda con la que más poder predictivo "
                        "conserva en esta variable. Es la más lenta de las automáticas."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "auto_heuristic",
                    "label": "Que el motor la deduzca, por la vía rápida",
                    "help": (
                        "Igual que la anterior, pero ubica el punto de quiebre con una regla "
                        "aproximada. Notoriamente más rápida cuando exploras muchos cortes."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "auto_asc_desc",
                    "label": "Que el motor elija entre creciente y decreciente",
                    "help": (
                        "Deja que el motor decida el sentido para esta variable, pero le prohíbe "
                        "formas con quiebre."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "ascending",
                    "label": "Creciente: a mayor valor, mayor riesgo",
                    "help": (
                        "Fuerza el sentido sólo en esta variable, por ejemplo en días de mora o "
                        "en nivel de endeudamiento."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "descending",
                    "label": "Decreciente: a mayor valor, menor riesgo",
                    "help": (
                        "El sentido inverso, para variables donde más es mejor: antigüedad del "
                        "cliente, renta o puntaje de un buró externo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "concave",
                    "label": "Cambia cada vez menos",
                    "help": (
                        "El riesgo se mueve en un sentido con efecto que se va agotando, sin "
                        "quiebres bruscos, sólo en esta variable."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "convex",
                    "label": "Cambia cada vez más",
                    "help": (
                        "El riesgo se mueve en un sentido con efecto que se acelera, sólo en esta "
                        "variable; el deterioro se dispara en los valores extremos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "peak",
                    "label": "Sube y después baja",
                    "help": (
                        "Admite un máximo de riesgo en la mitad del rango de esta variable. El "
                        "punto de quiebre se busca de forma exacta."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "peak_heuristic",
                    "label": "Sube y después baja, con el quiebre aproximado",
                    "help": (
                        "La misma forma, ubicando el máximo con una regla aproximada, para cuando "
                        "la búsqueda exacta se hace cara."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "valley",
                    "label": "Baja y después sube",
                    "help": (
                        "Admite un mínimo de riesgo en la mitad del rango, la forma típica de la "
                        "edad o del monto. El punto de quiebre se busca de forma exacta."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "valley_heuristic",
                    "label": "Baja y después sube, con el quiebre aproximado",
                    "help": (
                        "La misma forma, ubicando el mínimo con una regla aproximada, para cuando "
                        "la búsqueda exacta se hace cara."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "survival": (
        {
            "path": "survival.method",
            "question": "¿Con qué método quieres estimar cuándo ocurre el incumplimiento?",
            "help": (
                "Los cuatro entregan lo mismo —curvas de supervivencia y su estructura temporal "
                "de PD—, pero se diferencian en qué le exigen a tu archivo y a tu entorno."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "discrete_hazard",
                    "label": "Riesgo período a período",
                    "help": (
                        "Estima con una regresión la probabilidad de incumplir en cada período y "
                        "admite tus variables explicativas y la probabilidad del scorecard. Se "
                        "apoya en una librería estadística que se instala aparte: si no está en "
                        "tu entorno, la corrida se detiene antes de ajustar."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "kaplan_meier",
                    "label": "Curva observada, sin modelo",
                    "help": (
                        "Lee la curva directamente de lo observado, sin variables explicativas y "
                        "sin suponer ninguna forma. Es el único que no necesita instalar nada "
                        "aparte. A cambio te exige declarar el nivel de confianza y su forma: sin "
                        "ellos avisa que falta un dato tuyo y, con el corte activado, se detiene."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "cox_ph",
                    "label": "Riesgos proporcionales de Cox",
                    "help": (
                        "Relaciona el momento del incumplimiento con tus variables suponiendo que "
                        "el efecto de cada una no cambia en el tiempo. Necesita al menos una "
                        "variable numérica —sin ninguna se detiene antes de ajustar— y una "
                        "librería de supervivencia que se instala aparte."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "aft",
                    "label": "Tiempo de vida acelerado",
                    "help": (
                        "Modela directamente cuánto tarda en llegar el incumplimiento, con una "
                        "familia de curvas que eliges más abajo. Corre incluso sin variables "
                        "explicativas y usa la misma librería de supervivencia que se instala "
                        "aparte."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "survival.input.pd_source",
            "question": (
                "¿Quieres enganchar estas curvas a la probabilidad que ya estima tu scorecard?"
            ),
            "help": (
                "Decide si el modelo se alimenta del scorecard o se ajusta solo. Cambia además "
                "sobre qué población se ajusta: con enganche, sólo sobre la muestra de "
                "Desarrollo; sin él, sobre el libro completo."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "model_raw",
                    "label": "Sí, con la probabilidad sin calibrar",
                    "help": (
                        "Toma la probabilidad cruda del modelo. Exige que el paso que la estima "
                        "corra en la misma sesión: sin él la corrida no arranca. Trae también la "
                        "marca de qué operaciones son de Desarrollo, y el ajuste se limita a ésas."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "calibration",
                    "label": "Sí, con la probabilidad ya calibrada",
                    "help": (
                        "Toma la probabilidad ajustada a tu tasa central. Exige además que corra "
                        "el paso que la calibra: si esa sección está apagada, se te avisa antes "
                        "de ejecutar."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "none",
                    "label": "No, ajustar sólo con lo que trae tu archivo",
                    "help": (
                        "Las curvas se estiman con tus propias variables, sin insumo del "
                        "scorecard, y sobre el libro completo. Es la única que no obliga a "
                        "modelar antes, y por eso la que necesita quien viene sólo a estimar "
                        "curvas de supervivencia."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "survival.discrete_hazard.link",
            "question": (
                "¿Qué forma quieres que tenga la relación entre el riesgo del período y tus "
                "variables?"
            ),
            "help": (
                "Sólo se aplica al riesgo período a período. Cambia la forma de la curva y el "
                "valor de los coeficientes, nunca los datos que hay que traer."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "logit",
                    "label": "Simétrica",
                    "help": (
                        "La forma habitual en riesgo de crédito, la misma de una regresión "
                        "logística: los coeficientes se leen como razones de probabilidades."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "cloglog",
                    "label": "Asimétrica",
                    "help": (
                        "Trata distinto el riesgo alto del bajo y es la versión período a período "
                        "de un modelo de riesgos proporcionales: suele preferirse cuando los "
                        "períodos son largos y dentro de uno puede pasar mucho."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "survival.discrete_hazard.pd_role",
            "question": (
                "¿Qué papel quieres que juegue la probabilidad del scorecard dentro del modelo?"
            ),
            "help": (
                "Sólo se aplica al riesgo período a período, y sólo si lo enganchaste al "
                "scorecard: sin ese enganche las cuatro respuestas dan exactamente el mismo "
                "resultado."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "covariate",
                    "label": "Como una variable más",
                    "help": (
                        "El modelo estima cuánto pesa la probabilidad del scorecard, junto al "
                        "resto de tus variables."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "offset",
                    "label": "Como punto de partida, sin reestimarla",
                    "help": (
                        "Se acepta el nivel de riesgo del scorecard tal cual y el modelo sólo "
                        "corrige el efecto del tiempo. Necesita que la tabla del scorecard traiga "
                        "su puntaje en escala continua, no sólo la probabilidad."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "segment",
                    "label": "Como un grupo de riesgo",
                    "help": (
                        "Estima un nivel propio para cada grupo, sin suponer ninguna forma entre "
                        "ellos. Necesita que la columna traiga un grupo ya formado: apuntada a la "
                        "probabilidad continua del scorecard el ajuste no converge y la corrida "
                        "se detiene."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "none",
                    "label": "Que no entre al modelo",
                    "help": (
                        "El riesgo período a período se ajusta con tus variables y el efecto del "
                        "tiempo, ignorando lo que diga el scorecard."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "survival.cox_aft.aft_family",
            "question": "¿Qué forma quieres suponer para el tiempo hasta el incumplimiento?",
            "help": (
                "Sólo se aplica al tiempo de vida acelerado, y ahí es obligatoria: sin ella la "
                "corrida ni siquiera arranca. Las tres cambian la cola de la curva, que es lo que "
                "decide la PD a largo plazo."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "weibull",
                    "label": "Riesgo que sube o baja de forma sostenida",
                    "help": (
                        "El riesgo cambia en una sola dirección a medida que la operación "
                        "envejece. Es el punto de partida habitual y el más fácil de explicar."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "lognormal",
                    "label": "Riesgo que sube y después baja",
                    "help": (
                        "Admite un máximo de riesgo intermedio y caída posterior, que es el "
                        "patrón típico de una cartera que madura."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "loglogistic",
                    "label": "Riesgo que sube y baja, con caída más lenta",
                    "help": (
                        "Igual que la anterior, pero el riesgo tarda más en apagarse: da más peso "
                        "a los incumplimientos tardíos y sube la PD acumulada del final."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "survival.kaplan_meier.confidence_transform",
            "question": "¿Cómo quieres construir la banda de confianza de la curva observada?",
            "help": (
                "Sólo se aplica a la curva observada, y sólo si además declaras el nivel de "
                "confianza: elegir la forma sola no publica ninguna banda y, con el corte "
                "activado, detiene la corrida."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "plain",
                    "label": "Directa sobre la curva",
                    "help": (
                        "Suma y resta el margen sobre la propia probabilidad de sobrevivir. Es la "
                        "más simple de explicar, pero cerca de los extremos la banda se aplasta "
                        "contra ellos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "loglog",
                    "label": "Sobre una escala transformada",
                    "help": (
                        "Construye la banda en otra escala y la devuelve, así que nunca se sale "
                        "del rango válido. Es la recomendación habitual cuando la supervivencia "
                        "es muy alta o muy baja."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "provisioning_internal": (
        {
            "path": "provisioning_internal.method",
            "question": "¿Cómo quieres calcular la pérdida esperada de cada grupo?",
            "help": (
                "Las dos rutas son metodológicamente válidas y este motor admite ambas. La "
                "diferencia es si descompones la pérdida en sus dos factores o si la traes ya "
                "estimada. Si una norma local te obliga a una de las dos, ésa es la que eliges."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "pd_lgd",
                    "label": "Descomponerla en probabilidad y severidad",
                    "help": (
                        "Multiplica el monto colocado del grupo por su probabilidad de incumplir "
                        "y por su severidad. Necesita que tu archivo traiga la severidad "
                        "observada de cada operación, y no admite que además declares una tasa de "
                        "pérdida."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "direct_loss_rate",
                    "label": "Traer la tasa de pérdida ya estimada",
                    "help": (
                        "Usa la pérdida esperada por unidad de exposición que tú ya "
                        "calculaste, sin descomponerla; la severidad deja de leerse. Necesita esa "
                        "columna en tu "
                        "archivo, y ojo: la probabilidad de incumplir se sigue exigiendo y se "
                        "publica en el detalle, aunque no entre en el monto."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_internal.pd_source",
            "question": "¿De dónde sale la probabilidad de incumplir de cada operación?",
            "help": (
                "El monto de la provisión se apoya en esta probabilidad, así que su procedencia "
                "queda declarada en el informe y en el rastro de auditoría."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "calibration",
                    "label": "De la probabilidad ya calibrada",
                    "help": (
                        "La probabilidad ajustada a tu tasa central, que es la que sostiene un "
                        "análisis histórico fundamentado. Exige que corra el paso que la calibra "
                        "o que subas esa tabla; si falta, se te avisa antes de ejecutar."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "model",
                    "label": "De la probabilidad sin calibrar",
                    "help": (
                        "La probabilidad cruda del modelo, sin ajustar a ninguna tasa central. "
                        "Exige que corra el paso que la estima o que subas esa tabla, y que le "
                        "digas qué columna la trae: el nombre esperado por omisión es el de la "
                        "tabla calibrada, así que sin cambiarlo la corrida se detiene."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_internal.grouping",
            "question": "¿Cómo quieres formar los grupos homogéneos de deudores?",
            "help": (
                "Este método provisiona por grupo, no por operación: la provisión es una cifra "
                "del grupo, que después se reparte entre sus operaciones a prorrata de la "
                "exposición."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "score_band",
                    "label": "Por bandas de riesgo, formadas en la corrida",
                    "help": (
                        "Ordena las operaciones por su probabilidad y las corta en bandas de "
                        "igual tamaño dentro de cada cartera. No necesita ninguna columna extra "
                        "de tu archivo. Si hay muchas probabilidades repetidas quedan menos "
                        "bandas de las pedidas, y el resultado lo avisa."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "segment",
                    "label": "Por el segmento de negocio que traiga tu archivo",
                    "help": (
                        "Los grupos los define una columna tuya —banca personas, pyme, consumo—. "
                        "Necesita esa columna en el archivo, y sin ella la corrida no arranca."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "provided",
                    "label": "Por un grupo ya formado que traiga tu archivo",
                    "help": (
                        "El cálculo es idéntico al anterior y también necesita una columna tuya. "
                        "Lo que cambia es la procedencia que queda declarada en el informe y en "
                        "el rastro de auditoría: un grupo que tú ya formaste, no un segmento de "
                        "negocio. Es lo que lee un validador."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_internal.lgd.method",
            "question": "¿De dónde sale la severidad de cada operación?",
            # 🔴 D-EXI-6: este punto **no aplica siempre**, y hasta el 2026-08-08 su `help` decía
            # que con la tasa de pérdida directa «esta elección no cambia el resultado» — falso:
            # elegir aquí una rama modelada rechazaba el config ENTERO, aunque el motor no abra una
            # sola columna de `lgd` (D-SUB-2 lo declara inerte). Se cierra en la SUPERFICIE y no en
            # el validador: relajar la rama obligaría a que `InternalLgdWorkout()` dejara de fallar
            # —dos clases públicas— y contradiría D-LGD, que decidió que la rama ES el método.
            "when": {"path": "provisioning_internal.method", "equals": "pd_lgd"},
            "help": (
                "Las dos primeras "
                "leen la severidad que trae tu archivo y sólo se diferencian en cómo la resumen "
                "por grupo. Las dos regresiones la MODELAN, pero siguen necesitando la observada "
                "como objetivo del ajuste —o la fracción recuperada, si la nombras—. Sólo el "
                "proceso de recuperación prescinde de ella: la calcula desde tus flujos."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "provided",
                    "label": "Ponderada por monto, conservando la de cada operación",
                    "help": (
                        "La severidad del grupo es el promedio ponderado por el monto colocado, y "
                        "en el detalle cada operación conserva la suya. Es lo que corresponde "
                        "cuando la severidad la estimaste operación por operación."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "group_historical",
                    "label": "Promedio simple del grupo, aplicado a todas sus operaciones",
                    "help": (
                        "Promedio sin ponderar de la severidad observada del grupo, que después "
                        "se aplica igual a cada una de sus operaciones. Es lo que corresponde "
                        "cuando la severidad viene de una experiencia histórica: esa experiencia "
                        "no se pondera por los montos de hoy."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                # ⚠️ Los tres rótulos siguen el vocabulario que la sección hermana de IFRS 9 ya
                # había fijado para EL MISMO motor y LAS MISMAS tres ramas: describen el
                # comportamiento y **evitan el nombre de la distribución**, que a quien decide no
                # le dice nada. Un primer intento rotulaba «regresión beta» frente a «una regresión
                # sobre tus variables», o sea una opción específica contra otra genérica: en el
                # desplegable no había con qué elegir, que es justo lo que D-LGD-15 quiere resolver.
                {
                    "value": "fractional_response",
                    "label": "Modelarla admitiendo recuperos totales y pérdidas totales",
                    "help": (
                        "Ajusta un modelo de la severidad sobre las variables que elijas de tu "
                        "archivo y usa el valor ajustado de cada operación. Admite operaciones que "
                        "se recuperaron por completo y otras que se perdieron por completo, que es "
                        "lo normal en una cartera real. El ajuste se hace sobre la MISMA cartera "
                        "que se provisiona, así que mide el desempeño dentro de la muestra: el "
                        "informe lo dice."
                    ),
                    "estado": _EXIGE_OTRO_CAMPO,
                    "motivo": (
                        "Elegirla sola no basta: hay que decirle con qué variables de tu archivo "
                        "modelar la severidad, y hasta entonces la configuración no se puede "
                        "ejecutar."
                    ),
                    "prueba": "provisioning/internal/config.py:293",
                    "exige": ("provisioning_internal.lgd.covariate_cols",),
                },
                {
                    "value": "beta_regression",
                    "label": "Modelarla acotada estrictamente entre cero y uno",
                    "help": (
                        "Como la anterior, pero exige que la severidad observada esté "
                        "ESTRICTAMENTE entre 0 y 1: basta una operación recuperada por completo o "
                        "perdida por completo para que la corrida se detenga, y esas dos son "
                        "frecuentes en una cartera real. También puede detenerse si el ajuste no "
                        "converge. Si no sabes cuál de las dos elegir, la anterior es la que "
                        "corresponde a este dato."
                    ),
                    "estado": _EXIGE_OTRO_CAMPO,
                    "motivo": (
                        "Elegirla sola no basta: hay que decirle con qué variables de tu archivo "
                        "modelar la severidad, y hasta entonces la configuración no se puede "
                        "ejecutar."
                    ),
                    "prueba": "provisioning/internal/config.py:293",
                    "exige": ("provisioning_internal.lgd.covariate_cols",),
                },
                {
                    "value": "workout",
                    "label": "Calcularla desde el proceso de recuperación real",
                    "help": (
                        "No ajusta ningún modelo: toma lo recuperado de cada operación, le resta "
                        "los costos de recuperarlo, lo trae a valor presente con tu tasa, lo "
                        "divide por la exposición y se queda con LO QUE NO SE RECUPERÓ. Exige "
                        "cinco columnas de tu archivo —lo recuperado, los costos, la exposición, "
                        "los años que tardó y la tasa a la que descuentas— y los tres montos van "
                        "en la misma moneda, no en fracciones."
                    ),
                    "estado": _EXIGE_OTRO_CAMPO,
                    "motivo": (
                        "Elegirla sola no basta: hay que decirle qué columna de tu archivo trae "
                        "lo recuperado, y hasta entonces la configuración no se puede ejecutar."
                    ),
                    "prueba": "provisioning/internal/config.py:443",
                    "exige": ("provisioning_internal.lgd.recovery_col",),
                },
            ),
        },
        {
            "path": "provisioning_internal.rounding",
            "question": "¿Con qué precisión quieres publicar el monto de la provisión?",
            "help": (
                "Se aplica al monto de cada grupo y a su reparto entre operaciones, que siempre "
                "cuadra exacto con el total. Ojo: aquí se parte redondeando al centavo, y los "
                "otros motores de provisión parten sin redondear, así que compararlos exige "
                "igualar esta elección."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "none",
                    "label": "Sin redondear",
                    "help": (
                        "Publica el valor económico exacto, con todos sus decimales. Es lo que "
                        "traen de fábrica los demás motores de provisión, y por tanto lo que hay "
                        "que elegir aquí para compararlos sin ajustes."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "currency_2dp",
                    "label": "Al centavo",
                    "help": (
                        "Redondea a dos decimales, que es la precisión contable habitual de una "
                        "moneda con fracción."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "integer_currency",
                    "label": "A la unidad de moneda",
                    "help": (
                        "Redondea a moneda entera, que es lo que corresponde en monedas sin "
                        "fracción decimal."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "provisioning_ifrs9": (
        {
            "path": "provisioning_ifrs9.pd.term_structure_source",
            "question": "¿De qué análisis salen las curvas de pérdida a lo largo de la vida?",
            "help": (
                "La pérdida esperada se calcula sobre una curva que dice cuánto riesgo hay en cada "
                "período futuro. Aquí eliges qué análisis la produce, y de esa elección dependen "
                "las demás: cada uno publica cosas distintas junto a la curva."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "survival",
                    "label": "Del análisis de supervivencia",
                    "help": (
                        "El camino estándar y el único que esta interfaz arma sola: las curvas "
                        "salen del análisis de duración hasta el incumplimiento. Entrega la curva "
                        "y su unidad de tiempo, pero no la marca a condiciones actuales ni pesos "
                        "de escenario."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "markov",
                    "label": "De las matrices de transición entre estados",
                    "help": (
                        "Deriva la curva del tránsito de la cartera entre estados de mora. "
                        "Necesita que la corrida incluya ese análisis, que hoy sólo se activa "
                        "escribiendo la configuración a mano; ningún trabajo de esta interfaz lo "
                        "incorpora todavía."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "forward",
                    "label": "Del análisis prospectivo con escenarios macro",
                    "help": (
                        "El único que entrega la curva ya ajustada a condiciones actuales y con "
                        "el peso de cada escenario, que es lo que piden las otras dos elecciones "
                        "de arriba en sus valores de fábrica. Necesita que la corrida incluya el "
                        "análisis prospectivo, que hoy sólo se activa escribiendo la "
                        "configuración a mano."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_ifrs9.pd.base_pd_source",
            "question": "¿De dónde sale la probabilidad de incumplir a doce meses?",
            "help": (
                "Esta cifra no cambia los flujos de la pérdida —ésos salen siempre de la curva—, "
                "pero sí decide en qué etapa queda cada operación, y la etapa manda si se "
                "provisionan doce meses o toda la vida del crédito."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "term_structure",
                    "label": "De la misma curva de la vida del crédito",
                    "help": (
                        "Se lee de la propia curva acumulando sus primeros períodos. No exige "
                        "nada aparte de lo que ya necesitas para calcular la pérdida."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "calibration",
                    "label": "De la probabilidad calibrada de tu modelo",
                    "help": (
                        "Ancla la cifra a la que produce tu modelo ya calibrado. Necesita que la "
                        "corrida incluya la calibración y que su tabla cubra todas las "
                        "operaciones que estás provisionando: si falta una, la corrida se "
                        "detiene nombrándola."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_ifrs9.pd.pit_mode",
            "question": "¿Cómo llevas el riesgo de la curva a las condiciones económicas de hoy?",
            "help": (
                "La norma pide medir con la información actual, y una curva histórica describe el "
                "promedio del ciclo. Lo que elijas aquí tiene que calzar con el análisis que "
                "produce tus curvas: el valor de fábrica NO calza con el de fábrica de arriba."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "consume_pit",
                    "label": "Ya vienen a condiciones actuales",
                    "help": (
                        "Usa la curva tal cual, exigiendo que venga marcada como ya ajustada al "
                        "momento. Sólo el análisis prospectivo pone esa marca: con curvas de "
                        "supervivencia o de matrices de transición la corrida se detiene al "
                        "empezar a calcular."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "apply_vasicek",
                    "label": "Ajustarlas con el factor del ciclo económico",
                    "help": (
                        "Transforma la curva promedio con la correlación de la cartera y un "
                        "factor del ciclo por período. Exige que declares esa correlación y, "
                        "además, que la curva traiga el factor: ninguno de los tres análisis de "
                        "arriba lo publica hoy, así que sólo sirve con una curva que aportes tú "
                        "por código."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "ttc_only",
                    "label": "Dejarlas como están, sin ajuste de ciclo",
                    "help": (
                        "Usa el promedio del ciclo sin tocarlo. Es el único que funciona con las "
                        "curvas que esta interfaz sabe producir, y es lo que usa el ejemplo de "
                        "muestra; a cambio, el resultado no incorpora la coyuntura."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_ifrs9.lgd.method",
            "question": "¿Cómo obtienes cuánto se pierde cuando una operación incumple?",
            "help": (
                "La severidad de la pérdida se reparte en dos modas —se recupera casi todo o casi "
                "nada—, así que el motor nunca la promedia con una regresión lineal simple. Cada "
                "camino te pide datos distintos en tu archivo."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "provided",
                    "label": "La traigo yo en el archivo",
                    "help": (
                        "Toma la severidad tal como la entrega tu institución. Necesita que tu "
                        "archivo traiga esa columna; si además nombras una columna de "
                        "recuperación, el motor usa ésa y calcula la severidad como el "
                        "complemento de lo recuperado."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "beta_regression",
                    "label": "La modelo con una regresión acotada entre cero y uno",
                    "help": (
                        "Ajusta un modelo pensado para proporciones. Exige que elijas al menos "
                        "una variable explicativa de tu archivo y que la severidad observada "
                        "quede estrictamente entre cero y uno: un cero o un uno exactos la "
                        "detienen."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "fractional_response",
                    "label": "La modelo admitiendo pérdidas totales y nulas",
                    "help": (
                        "El hermano del anterior que sí acepta severidades de cero y de uno, que "
                        "es lo habitual en una cartera real. Exige igualmente al menos una "
                        "variable explicativa de tu archivo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "workout",
                    "label": "La calculo desde el proceso de recuperación real",
                    "help": (
                        "Trae a valor presente lo recuperado menos los costos y lo compara con la "
                        "exposición. Es el más exigente: necesita la columna de recuperación y, "
                        "con nombres fijos que no puedes cambiar, la exposición, el costo de "
                        "recuperación y los años que tomó recuperar."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_ifrs9.lgd.workout_discount",
            "question": "¿A qué tasa traes a valor presente lo que recuperaste?",
            "help": (
                "Sólo se aplica si calculas la severidad desde el proceso de recuperación real; "
                "con cualquier otro camino el motor ni lo mira. Decide con qué tasa se descuenta "
                "el dinero que entra después del incumplimiento."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "eir",
                    "label": "A la tasa efectiva del propio crédito",
                    "help": (
                        "Es la convención contable: cada operación se descuenta con su tasa "
                        "efectiva, la misma columna de tu archivo que usa el descuento de la "
                        "pérdida esperada."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "contractual",
                    "label": "A una tasa contractual aparte",
                    "help": (
                        "Descuenta con otra tasa que declares por operación. Necesita una columna "
                        "más en tu archivo, con nombre fijo que no puedes cambiar; si no está, la "
                        "corrida se detiene."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_ifrs9.ead.method",
            "question": "¿Cómo determinas cuánto estará expuesto el crédito al incumplir?",
            "help": (
                "Es el monto sobre el que se aplica la pérdida. Puedes entregarlo ya calculado o "
                "dejar que el motor lo estime sumando al saldo dispuesto una parte de la línea "
                "todavía sin usar."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "provided",
                    "label": "La traigo yo en el archivo",
                    "help": (
                        "Toma la exposición tal como la entrega tu institución. Necesita esa sola "
                        "columna, y es lo que usa el ejemplo de muestra."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "ccf",
                    "label": "La estimo desde el saldo y la línea disponible",
                    "help": (
                        "Suma al saldo dispuesto la fracción de la línea sin usar que se espera "
                        "girada antes de incumplir. Necesita las columnas de saldo y de límite, y "
                        "además esa fracción: o una columna por operación o un valor único. Sin "
                        "ninguno de los dos la corrida se detiene al calcular."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_ifrs9.ecl.discount_convention",
            "question": "¿Cómo aplicas la tasa efectiva al descontar la pérdida futura?",
            "help": (
                "La pérdida de cada período se trae a hoy con la tasa efectiva del crédito. Lo "
                "que cambia aquí es el exponente de ese descuento, y sobre una curva mensual las "
                "dos convenciones dan cifras muy distintas."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "annual_eir_year_fraction",
                    "label": "Tasa anual, descontada por fracción de año",
                    "help": (
                        "Interpreta la tasa como anual y descuenta según los años transcurridos. "
                        "Es la convención contable habitual y exige que la curva declare su "
                        "periodicidad; si no la declara, el motor supone años y lo deja anotado "
                        "en el informe."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "period_eir",
                    "label": "Tasa ya expresada por período",
                    "help": (
                        "Interpreta la tasa como la del período de la curva y descuenta contando "
                        "períodos. Correcto sólo si la tasa de tu archivo viene en esa misma "
                        "periodicidad; con una tasa anual sobre una curva mensual subestima la "
                        "provisión."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_ifrs9.ecl.rounding",
            "question": "¿Con cuántos decimales quieres publicar la pérdida esperada?",
            "help": (
                "Es una decisión de presentación contable, no de cálculo. En esta capa el motor "
                "todavía no la aplica: la cifra sale con toda su precisión elijas lo que elijas."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "none",
                    "label": "Sin redondear, el valor económico exacto",
                    "help": (
                        "Publica la cifra con toda su precisión, que es lo que hoy ocurre en "
                        "cualquier caso. Viene así de fábrica."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "currency_2dp",
                    "label": "A dos decimales de la moneda",
                    "help": (
                        "Redondearía la pérdida al centavo antes de publicarla, para cuadrar con "
                        "el asiento contable."
                    ),
                    "estado": _SIN_EFECTO,
                    "motivo": (
                        "El cálculo de pérdida esperada todavía no aplica el redondeo: elegirlo "
                        "no cambia ni una cifra del informe. Se ofrece porque el redondeo sí "
                        "funciona en las provisiones normativas y en el método interno, y "
                        "esconderlo aquí haría creer que el motor no lo contempla."
                    ),
                    "prueba": "provisioning/ifrs9/ecl.py:222",
                },
                {
                    "value": "integer_currency",
                    "label": "A la unidad de moneda entera",
                    "help": (
                        "Redondearía la pérdida a la unidad de moneda entera antes de publicarla, "
                        "para carteras que reportan sin decimales."
                    ),
                    "estado": _SIN_EFECTO,
                    "motivo": (
                        "El cálculo de pérdida esperada todavía no aplica el redondeo: elegirlo "
                        "no cambia ni una cifra del informe. Se ofrece porque el redondeo sí "
                        "funciona en las provisiones normativas y en el método interno, y "
                        "esconderlo aquí haría creer que el motor no lo contempla."
                    ),
                    "prueba": "provisioning/ifrs9/ecl.py:222",
                },
            ),
        },
        {
            "path": "provisioning_ifrs9.scenarios.source",
            "question": "¿De dónde salen los escenarios macro y cuánto pesa cada uno?",
            "help": (
                "La norma pide ponderar varios escenarios en vez de calcular sobre un promedio. "
                "Aquí decides quién aporta esos pesos, y el valor de fábrica exige un análisis "
                "que esta interfaz todavía no arma."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "forward",
                    "label": "Del análisis prospectivo, con sus propios pesos",
                    "help": (
                        "Toma los escenarios y sus pesos de la propia curva. Sólo el análisis "
                        "prospectivo los publica: con curvas de supervivencia o de matrices de "
                        "transición la corrida se detiene apenas empieza a calcular."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "config",
                    "label": "Los peso yo, escenario por escenario",
                    "help": (
                        "Escribes tú el peso de cada escenario. Tienen que sumar uno, ser todos "
                        "positivos y cubrir exactamente los escenarios que traiga la curva, ni "
                        "uno más ni uno menos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "single",
                    "label": "Un solo escenario, sin ponderar",
                    "help": (
                        "Trata la curva como un escenario único con peso completo. Es lo que "
                        "corresponde con curvas de supervivencia o de matrices de transición, y "
                        "es lo que usa el ejemplo de muestra; a cambio, la cifra no incorpora "
                        "escenarios alternativos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "provisioning_cmf": (
        {
            "path": "provisioning_cmf.pd_mapping.method",
            "question": (
                "¿De dónde sale la categoría de riesgo con que entras a la matriz normativa?"
            ),
            "help": (
                "La provisión estándar se lee de una tabla normativa cuya entrada, en cartera "
                "comercial individual, es la categoría del deudor. Aquí decides si esa categoría "
                "la traes clasificada o la deriva el motor desde tu probabilidad de incumplir."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "provided_cmf_category",
                    "label": "La traigo ya clasificada en el archivo",
                    "help": (
                        "Usa la categoría que tu institución ya asignó. Necesita esa columna en "
                        "tu archivo y evita que la clasificación normativa dependa de un modelo "
                        "interno."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "pd_breaks",
                    "label": "La deriva el motor desde cortes de probabilidad",
                    "help": (
                        "Asigna la categoría según en qué tramo cae la probabilidad de cada "
                        "deudor; tienes que declarar los cortes y una categoría más que cortes. "
                        "Necesita que la corrida produzca esa probabilidad, y hoy ningún trabajo "
                        "de esta interfaz encadena un modelo con las provisiones normativas."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_cmf.pd_mapping.pd_source_domain",
            "question": "¿Qué probabilidad de incumplir usas para derivar la categoría?",
            "help": (
                "Sólo se aplica si dejas que el motor derive la categoría desde cortes de "
                "probabilidad; si la traes clasificada, esta elección queda anotada y no se lee. "
                "Decide si entra la cifra cruda del modelo o la ya calibrada."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "model",
                    "label": "La probabilidad cruda que sale del modelo",
                    "help": (
                        "Toma la cifra tal como la produce el modelo, antes de anclarla a una "
                        "tasa de referencia. Necesita que la corrida incluya el ajuste del "
                        "modelo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "calibration",
                    "label": "La probabilidad ya calibrada",
                    "help": (
                        "Toma la cifra después de anclarla a la tasa de incumplimiento que "
                        "declaraste. Necesita que la corrida incluya la calibración y que "
                        "apuntes al resultado de esa etapa: los valores de fábrica siguen "
                        "apuntando al del modelo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_cmf.guarantees.financial_guarantee_policy",
            "question": (
                "¿Qué hace el motor con una garantía financiera cuyo aforo no está verificado?"
            ),
            "help": (
                "Hay garantías financieras cuyos porcentajes de descuento no están en la "
                "normativa que el motor tiene recopilada y verificada. Aquí decides si eso "
                "detiene la corrida o si se sigue, y con qué costo."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "fail",
                    "label": "Detener la corrida y avisar",
                    "help": (
                        "Se detiene nombrando la cartera y la fila, en vez de inventar un aforo. "
                        "Viene así de fábrica y es lo prudente para un cálculo que se reporta al "
                        "regulador. Sólo se dispara si tu archivo declara la garantía financiera."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "ignore_if_missing",
                    "label": "Seguir sin reconocer esa garantía",
                    "help": (
                        "Continúa el cálculo ignorando la garantía, o sea sin darte ningún alivio "
                        "por ella. La provisión queda por lo alto, nunca por lo bajo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "use_recoverable_amount",
                    "label": "Seguir sólo si declaras el monto recuperable",
                    "help": (
                        "Exige que nombres una columna con el monto recuperable y que la fila lo "
                        "traiga; si falta el valor, la corrida se detiene igual. Ojo con el "
                        "alcance: el motor lo exige y lo valida, pero todavía no lo descuenta de "
                        "la provisión, así que la cifra sale igual que ignorando la garantía."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning_cmf.exposure.rounding",
            "question": "¿Con cuántos decimales quieres publicar la provisión?",
            "help": (
                "Es una decisión de presentación contable, no de cálculo: el redondeo se aplica "
                "al final, sobre la provisión publicable, y nunca sobre los porcentajes "
                "normativos intermedios."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "none",
                    "label": "Sin redondear, el valor exacto",
                    "help": (
                        "Publica la provisión con toda su precisión. Viene así de fábrica y es lo "
                        "que conviene si después vas a comparar contra el método interno."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "currency_2dp",
                    "label": "A dos decimales de la moneda",
                    "help": (
                        "Redondea al centavo, hacia arriba en el empate, antes de publicar la "
                        "cifra. Es lo que cuadra con un asiento contable que lleva decimales."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "integer_currency",
                    "label": "A la unidad de moneda entera",
                    "help": (
                        "Redondea a la unidad de moneda entera, hacia arriba en el empate. Para "
                        "carteras que "
                        "reportan sin decimales; sobre muchas filas la suma se aparta un poco del "
                        "valor exacto."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "calibration": (
        {
            "path": "calibration.method",
            "question": "¿Cómo quieres llevar la probabilidad del modelo al nivel de tu cartera?",
            "help": (
                "El modelo ordena bien a los clientes, pero su nivel promedio no tiene por qué "
                "coincidir con la tasa de incumplimiento que tu institución reconoce. Esto decide "
                "con qué transformación se corrige ese nivel."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "intercept_offset",
                    "label": "Sólo corregir el nivel",
                    "help": (
                        "Desplaza todas las probabilidades por igual hasta que su promedio calce "
                        "con la tasa de anclaje. No toca el orden de los clientes: quien era más "
                        "riesgoso lo sigue siendo, y la capacidad de discriminación no se mueve."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "platt_scaling",
                    "label": "Reestimar la curva con los incumplimientos observados",
                    "help": (
                        "Vuelve a estimar pendiente e intercepto usando el resultado observado en "
                        "la muestra de Desarrollo, y recién después ancla el nivel. Corrige "
                        "también la forma de la curva y no sólo su altura; conserva el orden "
                        "mientras la pendiente salga positiva, y si sale negativa se detiene."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "isotonic",
                    "label": "Ajustar la curva libremente, sin forma predefinida",
                    "help": (
                        "El más flexible y el que mejor calza tramo a tramo, pero aplana escalones "
                        "enteros: crea empates entre clientes que el modelo sí distinguía, y "
                        "cuando eso pasa el informe declara que el ordenamiento por riesgo no se "
                        "conservó. Elígelo si el nivel importa más que la discriminación."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "calibration.anchor_kind",
            "question": "¿Ese nivel representa el promedio del ciclo o el momento actual?",
            "help": (
                "Es una etiqueta de gobierno que no mueve ni una cifra: viaja con el resultado y "
                "queda escrita en el informe, para que quien lo lea sepa qué representa el nivel "
                "al que se ancló. Tiene que ser coherente con el origen que elijas para la tasa, o "
                "la corrida no arranca."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "through_the_cycle",
                    "label": "Un promedio de largo plazo, a través del ciclo",
                    "help": (
                        "La lectura habitual para provisiones y capital: el nivel representa un "
                        "promedio de varios años, y no la coyuntura de la que vienen tus datos. Es "
                        "compatible con los cuatro orígenes de la tasa."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "point_in_time",
                    "label": "El nivel del momento actual",
                    "help": (
                        "Declara que el nivel refleja la coyuntura del período observado. Sólo "
                        "puede acompañar a una tasa que fijes tú a mano —la del negocio o la de tu "
                        "histórico—: combinarla con la que se lee de la muestra, o con una "
                        "referencia normativa, detiene la corrida porque sería una etiqueta falsa."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "calibration.anchor_source",
            "question": "¿De dónde sale la tasa de incumplimiento a la que se ancla?",
            "help": (
                "Es el dato institucional del que cuelga todo el nivel de la probabilidad que se "
                "publica, y el informe declara su origen. Tres de las cuatro respuestas exigen que "
                "escribas el número; la cuarta lo calcula sola."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "business_input",
                    "label": "La fija el negocio",
                    "help": (
                        "Ancla al número que tú escribes, respaldado por una decisión de negocio. "
                        "Informarlo es obligatorio: sin ese número la corrida no arranca, porque "
                        "el motor se niega a inventar un ancla."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "historical_default_rate",
                    "label": "Sale de tu histórico de incumplimientos",
                    "help": (
                        "Ancla al número que tú escribes, calculado fuera del motor sobre tu serie "
                        "histórica de largo plazo. También es obligatorio informarlo: el motor no "
                        "lee tu histórico por su cuenta."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "development_observed",
                    "label": "Se lee de la muestra de Desarrollo",
                    "help": (
                        "Calcula la tasa sola, como el promedio observado en la muestra con que se "
                        "ajustó el modelo, y es la respuesta de fábrica. Por eso la tasa objetivo "
                        "se deja vacía: si además escribes un número a mano, la configuración se "
                        "rechaza en vez de descartarlo, porque la corrida anclaría a otro valor."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "external_regulatory",
                    "label": "La fija una referencia normativa externa",
                    "help": (
                        "Ancla al número que tú escribes, tomado de una tasa regulatoria. "
                        "Informarlo es obligatorio, y no se puede combinar con la etiqueta que "
                        "declara el nivel del momento actual."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "model": (
        {
            "path": "model.engine",
            "question": "¿Con qué rutina estadística quieres resolver la regresión?",
            "help": (
                "Las dos resuelven exactamente la misma regresión logística y llegan al mismo "
                "resultado. Lo único que las separa es que una admite ponderar cada operación con "
                "un peso propio, y este proceso no entrega esos pesos."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "logit",
                    "label": "La regresión logística clásica",
                    "help": (
                        "La ruta de fábrica: máxima verosimilitud directa, resuelta con el método "
                        "numérico que elijas a continuación. Es la que queda declarada en la ficha "
                        "del modelo del informe."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "glm_binomial",
                    "label": "El modelo lineal generalizado, familia binomial",
                    "help": (
                        "Resuelve la misma regresión por mínimos cuadrados reponderados en vez de "
                        "por máxima verosimilitud directa, y publica su propia rutina interna en "
                        "la ficha del modelo."
                    ),
                    "estado": _SIN_EFECTO,
                    "motivo": (
                        "Llega al mismo resultado: medido sobre la misma muestra, los coeficientes "
                        "y las probabilidades coinciden hasta el decimotercer decimal. Su única "
                        "ventaja real —ponderar cada operación— no se puede aprovechar desde aquí, "
                        "porque el proceso nunca entrega esos pesos. Y elegirla anula el método "
                        "numérico que escojas a continuación."
                    ),
                    "prueba": "model/step.py:158",
                },
            ),
        },
        {
            "path": "model.optimizer",
            "question": "¿Qué método numérico quieres que use el ajuste para converger?",
            "help": (
                "No cambia el modelo, sólo el camino para llegar a él: los tres terminan en el "
                "mismo ajuste, y esto se toca únicamente cuando la corrida no converge. Se aplica "
                "sólo a la regresión logística clásica; la otra rutina usa siempre la suya y "
                "descarta lo que elijas aquí."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "newton",
                    "label": "Newton-Raphson",
                    "help": (
                        "El estándar y el más rápido cuando el problema está bien planteado: "
                        "resuelve en pocas rondas y es el único que respeta la tolerancia de "
                        "convergencia que hayas fijado. Es la opción de fábrica."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "bfgs",
                    "label": "BFGS",
                    "help": (
                        "Alternativa robusta para cuando el estándar no converge, por ejemplo con "
                        "variables muy correlacionadas entre sí. Ojo: la tolerancia de "
                        "convergencia que fijes no se le aplica —usa la suya— y la librería "
                        "estadística de fondo emite un aviso en cada corrida."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "lbfgs",
                    "label": "L-BFGS",
                    "help": (
                        "La variante de memoria acotada de la anterior, pensada para modelos con "
                        "muchas variables. Comparte su límite: tampoco respeta la tolerancia de "
                        "convergencia que fijes, y arrastra el mismo aviso de la librería "
                        "estadística."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "model.stepwise.direction",
            "question": "¿Cómo quieres que se arme la lista final de variables?",
            "help": (
                "Decide si el proceso construye el modelo incorporando variables de a una, "
                "retirándolas de a una, haciendo las dos cosas en cada ronda, o si no selecciona "
                "nada y se queda con todas las que le llegaron."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "none",
                    "label": "No seleccionar: usar todas las que llegaron",
                    "help": (
                        "Ajusta con todas las variables que sobrevivieron a los pasos anteriores, "
                        "salvo las que hayas vetado a mano. Los controles de signo y de "
                        "concentración siguen actuando: lo que se apaga es la selección "
                        "estadística paso a paso."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "forward",
                    "label": "Incorporar de a una, empezando de cero",
                    "help": (
                        "Parte sin variables —salvo las que hayas forzado a entrar— e incorpora en "
                        "cada ronda la más significativa, hasta que ninguna de las que quedan "
                        "afuera alcanza el umbral de entrada."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "backward",
                    "label": "Partir con todas y retirar de a una",
                    "help": (
                        "Parte con todas las candidatas y retira en cada ronda la menos "
                        "significativa, hasta que todas las que siguen dentro superan el umbral de "
                        "permanencia."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "bidirectional",
                    "label": "Incorporar y retirar en cada ronda",
                    "help": (
                        "Revisa entradas y salidas en cada iteración, así que una variable que "
                        "entró temprano puede salir cuando entran otras que explican lo mismo. Es "
                        "lo habitual en la industria y la opción de fábrica."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "model.stepwise.criterion",
            "question": "¿Con qué prueba estadística se decide si una variable entra o sale?",
            "help": (
                "Sólo se aplica si dejaste que el proceso seleccione las variables: si le pediste "
                "usar todas las que le llegaron, lo que elijas aquí no cambia una sola cifra del "
                "resultado. Cuando sí selecciona, esto gobierna cada entrada y cada salida."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "wald_pvalue",
                    "label": "La significancia individual del coeficiente",
                    "help": (
                        "Mira la significancia del coeficiente de cada variable dentro del modelo "
                        "vigente. Es lo más rápido, porque no obliga a reajustar el modelo sin "
                        "ella, y es la opción de fábrica."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "lr_test",
                    "label": "La comparación entre el modelo con y sin la variable",
                    "help": (
                        "Ajusta el modelo con y sin la variable y compara cuánto mejora el ajuste "
                        "global. Cuesta bastante más —duplica los ajustes de cada ronda— y es más "
                        "fiel cuando la variable se solapa con las que ya están dentro."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "both",
                    "label": "Exigir que pase las dos pruebas",
                    "help": (
                        "La más estricta: una variable entra sólo si supera los dos contrastes, y "
                        "sale si falla cualquiera de ellos. Deja modelos más chicos y más fáciles "
                        "de defender ante un validador."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "model.sign_policy.action",
            "question": "¿Qué hacer si una variable queda apuntando al revés de lo esperado?",
            "help": (
                "Un coeficiente con el signo contrario dice que, según el ajuste, más riesgo en "
                "esa variable significa menos incumplimiento. Casi siempre es solape entre "
                "variables y no un hallazgo, y publicarlo así es indefendible ante un validador."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "exclude",
                    "label": "Sacarla del modelo",
                    "help": (
                        "La retira y vuelve a ajustar sin ella, dejando el motivo escrito en la "
                        "traza de decisiones del informe. Es la opción de fábrica y la que deja un "
                        "modelo económicamente coherente."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "flag",
                    "label": "Dejarla, pero marcarla",
                    "help": (
                        "La conserva en el modelo y la deja señalada en la tabla de coeficientes, "
                        "para que quien valide la vea y decida. Sirve cuando quieres medir el "
                        "efecto antes de descartar nada."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "fail",
                    "label": "Detener la corrida",
                    "help": (
                        "Aborta el ajuste nombrando la variable y su coeficiente, en vez de "
                        "entregar un modelo con una relación que no se sostiene. Es lo más "
                        "estricto y obliga a revisar los tramos antes de seguir."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "model.iv_contribution.action",
            "question": "¿Qué hacer si una sola variable concentra casi todo el poder predictivo?",
            "help": (
                "Un modelo que descansa en una única variable es frágil: si esa fuente se degrada "
                "o deja de llegar, se cae entero. El umbral que fijes define desde qué proporción "
                "del total se considera excesiva esa concentración."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "exclude",
                    "label": "Sacar la variable dominante",
                    "help": (
                        "Retira la que se pasa del umbral y reajusta, dejando constancia en la "
                        "traza. Ojo: al sacarla el reparto se recalcula sobre las que quedan, así "
                        "que puede caer más de una en cadena. Es la opción de fábrica."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "flag",
                    "label": "Dejarla, pero marcar la concentración",
                    "help": (
                        "Conserva el modelo tal cual y deja la concentración señalada en el "
                        "informe, para que quien valide juzgue si es aceptable en esta cartera."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "fail",
                    "label": "Detener la corrida",
                    "help": (
                        "Aborta el ajuste nombrando la variable y la proporción que concentra, en "
                        "vez de publicar un modelo que descansa en un solo factor."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "selection": (
        {
            "path": "selection.priority_order",
            "question": "¿Con qué criterios se decide cuál de dos variables parecidas se queda?",
            "help": (
                "Cuando dos variables miden casi lo mismo, sólo sobrevive una. Aquí eliges con qué "
                "se comparan y en qué orden: el primero manda y los siguientes sólo resuelven los "
                "empates. Los que no marques no desaparecen — quedan al final de la fila."
            ),
            "multiple": True,
            "options": (
                {
                    "value": "iv",
                    "label": "El poder predictivo de la variable",
                    "help": (
                        "Conserva la que más separa buenos de malos según su Information Value, "
                        "que es el criterio habitual en una tarjeta de scoring."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "auc",
                    "label": "El AUC de la variable por sí sola",
                    "help": (
                        "Conserva la que mejor ordena el riesgo medida sola sobre la muestra de "
                        "Desarrollo, sin la ayuda de las demás."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "ks",
                    "label": "El KS de la variable por sí sola",
                    "help": (
                        "Conserva la que logra la mayor distancia entre las curvas de buenos y "
                        "malos, medida sola sobre la muestra de Desarrollo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "gini",
                    "label": "El Gini de la variable por sí sola",
                    "help": (
                        "Es el AUC reescalado, así que ordena las variables exactamente igual que "
                        "el AUC y no aporta un criterio nuevo."
                    ),
                    "estado": _SIN_EFECTO,
                    "motivo": (
                        "El Gini se obtiene del AUC con una cuenta que no altera el orden, así que "
                        "marcarlo junto al AUC no resuelve ningún empate nuevo, y marcarlo en su "
                        "lugar deja exactamente el mismo resultado."
                    ),
                    "prueba": "src/nikodym/selection/selector.py:850",
                },
                {
                    "value": "name",
                    "label": "El nombre de la variable, en orden alfabético",
                    "help": (
                        "No mide nada: existe para que dos variables empatadas en todo lo anterior "
                        "se resuelvan siempre igual y la corrida sea reproducible."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "selection.correlation.method",
            "question": "¿Cómo quieres medir el parecido entre dos variables?",
            "help": (
                "El motor descarta variables que miden casi lo mismo. Éste es el estadístico con "
                "que se calcula ese parecido sobre la muestra de Desarrollo, y cambiarlo cambia "
                "qué variables llegan al modelo."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "pearson",
                    "label": "Parecido lineal",
                    "help": (
                        "Mide si dos variables se mueven juntas en línea recta. Es la opción "
                        "habitual y la que traen los ejemplos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "spearman",
                    "label": "Parecido en el orden de los valores",
                    "help": (
                        "Compara el orden y no la magnitud, así que reconoce relaciones que suben "
                        "juntas sin ser una línea recta."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "kendall",
                    "label": "Concordancia de pares",
                    "help": (
                        "También compara órdenes, pero entrega cifras más bajas que las otras dos "
                        "sobre el mismo par: con el mismo umbral descarta menos variables."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "selection.correlation.clustering_method",
            "question": (
                "¿Hasta dónde llega el descarte cuando varias variables se parecen entre sí?"
            ),
            "help": (
                "Las dos formas descartan, y ninguna de las dos apaga el filtro: eso se hace con "
                "su propio interruptor. Lo que cambia es el alcance cuando el parecido forma una "
                "cadena, donde la primera y la última ya casi no se parecen."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "none",
                    "label": "De a pares, en orden de prioridad",
                    "help": (
                        "Recorre las variables por prioridad y descarta sólo la que se parece "
                        "demasiado a alguna ya conservada. Sobre una cadena de tres, conserva la "
                        "primera y la última."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "connected_components",
                    "label": "Por grupos completos de variables encadenadas",
                    "help": (
                        "Arma un grupo con todas las variables encadenadas por parecido y conserva "
                        "una sola de cada grupo. Sobre esa misma cadena de tres, conserva una."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "selection.max_iv_action",
            "question": (
                "¿Qué hacer con una variable cuyo poder predictivo es sospechosamente alto?"
            ),
            "help": (
                "Un poder predictivo altísimo suele delatar que la variable ya contiene la "
                "respuesta —por ejemplo, la mora que define al moroso—. El umbral que lo dispara "
                "se fija aparte; aquí decides qué pasa cuando se supera."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "flag",
                    "label": "Dejarla y marcarla para revisión",
                    "help": (
                        "La variable sigue en el modelo y queda señalada en la tabla de selección, "
                        "con el valor observado, para que alguien decida."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "exclude",
                    "label": "Descartarla automáticamente",
                    "help": (
                        "La variable sale del modelo sin intervención, y la tabla de selección "
                        "registra el motivo y el valor que lo gatilló."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "selection.stability.action",
            "question": (
                "¿Qué hacer con una variable que se reparte distinto en las muestras de validación?"
            ),
            "help": (
                "Antes de modelar, el motor compara variable a variable cómo se reparten los "
                "clientes en Desarrollo y en cada muestra de validación. Aquí decides si ese "
                "diagnóstico sólo se informa o además saca variables del modelo."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "report_only",
                    "label": "Sólo informarlo",
                    "help": (
                        "El diagnóstico se publica y ninguna variable se descarta por él: la "
                        "decisión queda en manos de quien lee el informe."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "exclude",
                    "label": "Descartar las variables inestables",
                    "help": (
                        "Saca del modelo toda variable que alcance el umbral de revisión en alguna "
                        "muestra comparada, salvo las que hayas exigido conservar."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "scorecard": (
        {
            "path": "scorecard.rounding_method",
            "question": "¿Cómo quieres redondear los puntos de la tarjeta?",
            "help": (
                "Los puntos salen de la fórmula con decimales y hay que publicarlos de alguna "
                "forma. No es presentación: el puntaje que recibe cada cliente es el publicado."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "none",
                    "label": "Sin redondear, con decimales",
                    "help": (
                        "Publica el puntaje exacto de la fórmula. Es lo más preciso, pero una "
                        "tarjeta con decimales es incómoda de aplicar y de explicar."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "nearest_integer",
                    "label": "Al entero más cercano",
                    "help": (
                        "La opción habitual. Un valor justo en la mitad se lleva al entero par más "
                        "próximo: 12,5 baja a 12 y 13,5 sube a 14."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "floor_integer",
                    "label": "Siempre hacia abajo",
                    "help": (
                        "Trunca cada tramo al entero inferior, así que el puntaje total queda algo "
                        "por debajo del calculado. Con puntos negativos, baja aún más."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "ceil_integer",
                    "label": "Siempre hacia arriba",
                    "help": (
                        "Sube cada tramo al entero superior, así que el puntaje total queda algo "
                        "por encima del calculado. Con puntos negativos, los acerca a cero."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "scorecard.score_direction",
            "question": (
                "En la tarjeta que vas a construir, ¿un puntaje más alto es mejor o peor cliente?"
            ),
            "help": (
                "No hay una convención universal y el motor no la adivina. Define el signo con que "
                "se arman los puntos de cada tramo, así que invierte la tarjeta completa. Es la "
                "respuesta que manda: los indicadores de desempeño y de estabilidad la vuelven a "
                "preguntar para el caso en que traigas un puntaje ya construido, y si contestan "
                "distinto que aquí, se avisa antes de correr y la corrida se detiene."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "higher_is_lower_risk",
                    "label": "Más alto es mejor cliente",
                    "help": (
                        "La convención más habitual: a mayor puntaje, menor probabilidad de "
                        "incumplir. Los tramos de más riesgo suman menos puntos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "higher_is_higher_risk",
                    "label": "Más alto es peor cliente",
                    "help": (
                        "Para escalas donde el puntaje mide riesgo y no calidad crediticia: los "
                        "tramos de más riesgo suman más puntos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "performance": (
        {
            "path": "performance.partitions",
            "question": "¿Sobre qué muestras quieres medir el desempeño del modelo?",
            "help": (
                "Cada muestra que marques recibe su fila de indicadores y su tabla por deciles en "
                "el informe. Si marcas una que tu archivo no trae, se publica como no evaluable en "
                "vez de detener la corrida."
            ),
            "multiple": True,
            "options": (
                {
                    "value": "desarrollo",
                    "label": "Desarrollo",
                    "help": (
                        "La muestra con que se ajustó el modelo. Sus cifras son el techo "
                        "optimista: sirven de referencia, no de prueba de que el modelo sirva."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "holdout",
                    "label": "Validación",
                    "help": (
                        "Clientes del mismo período que no se usaron para ajustar. Responde si el "
                        "modelo generaliza dentro de la ventana con que se construyó."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "oot",
                    "label": "Fuera de tiempo",
                    "help": (
                        "Clientes de un período posterior. Es la cifra que mira quien va a poner "
                        "el modelo en producción y la que exige la validación formal."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "performance.evaluation_source",
            "question": "¿Con qué cifra se ordena a los clientes de más a menos riesgo al medir?",
            "help": (
                "Los indicadores de discriminación y la tabla por deciles necesitan ordenar la "
                "cartera. Las dos formas exigen que la calibración se haya ejecutado: el motor "
                "pide la probabilidad calibrada aunque elijas la otra."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "pd_calibrated",
                    "label": "La probabilidad de incumplir ya calibrada",
                    "help": (
                        "Ordena por la probabilidad calibrada, que es una escala continua y sin "
                        "empates. Es la opción recomendada y la que traen los ejemplos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "score",
                    "label": "El puntaje de la tarjeta",
                    "help": (
                        "Ordena por los puntos que recibe el cliente. Si los publicas redondeados "
                        "aparecen empates y las cifras se mueven un poco; a cambio, el corte del "
                        "KS se informa en puntos de la tarjeta."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "performance.score_direction",
            "question": "Al medir el desempeño, ¿un puntaje más alto es mejor o peor cliente?",
            "help": (
                "Sólo se aplica si ordenas la cartera por el puntaje de la tarjeta; ordenando por "
                "la probabilidad calibrada no cambia ninguna cifra. Tiene que decir lo mismo que "
                "la escala con que construiste la tarjeta: si se contradicen, se avisa antes de "
                "correr y la corrida se detiene, porque medir al revés invierte el signo de los "
                "indicadores de discriminación sin que el número parezca raro."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "higher_is_lower_risk",
                    "label": "Más alto es mejor cliente",
                    "help": (
                        "La convención habitual: los clientes con menos puntos encabezan el "
                        "ordenamiento como los de mayor riesgo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "higher_is_higher_risk",
                    "label": "Más alto es peor cliente",
                    "help": (
                        "Para escalas donde el puntaje mide riesgo: los clientes con más puntos "
                        "encabezan el ordenamiento como los de mayor riesgo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "report": (
        {
            "path": "report.formats",
            "question": "¿En qué formatos quieres el entregable?",
            "help": (
                "Puedes pedir varios a la vez. Unos son el documento del informe y otros son las "
                "tablas por operación completas, que salen como archivos aparte."
            ),
            "multiple": True,
            "options": (
                {
                    "value": "html",
                    "label": "Informe para pantalla",
                    "help": (
                        "Un solo archivo que se abre en cualquier navegador y se puede enviar por "
                        "correo. Sale en toda corrida, lo marques o no."
                    ),
                    "estado": _SIN_EFECTO,
                    "motivo": (
                        "El informe para pantalla se escribe siempre que la corrida tenga carpeta "
                        "de salida: marcarlo o no marcarlo produce exactamente los mismos archivos."
                    ),
                    "prueba": (
                        "src/nikodym/report/step.py:415-428 — el informe para pantalla se escribe "
                        "sin consultar la lista de formatos; medido pidiendo sólo la fuente "
                        "editable: el archivo sale igual."
                    ),
                },
                {
                    "value": "pdf",
                    "label": "Documento para imprimir y firmar",
                    "help": (
                        "El mismo informe paginado, listo para el comité. Se instala aparte y "
                        "además necesita librerías del sistema: si faltan, el informe sale en los "
                        "demás formatos y queda un aviso."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "docx",
                    "label": "Informe en Word",
                    "help": (
                        "Con títulos y tablas nativas, para que Validación comente y firme sobre "
                        "el archivo. Se instala aparte: si falta, el informe sale en los demás "
                        "formatos y queda un aviso."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "md",
                    "label": "Fuente editable en texto plano",
                    "help": (
                        "El informe como texto con sus figuras al lado, para recompilarlo con las "
                        "plantillas de tu institución. No hay que instalar nada."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "csv",
                    "label": "Tablas por operación, un archivo por tabla",
                    "help": (
                        "Las tablas con una fila por operación, completas y sin recortar, fuera "
                        "del documento. No hay que instalar nada, y sólo hay archivo si tu corrida "
                        "produce esas tablas."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "xlsx",
                    "label": "Tablas por operación en un libro de Excel",
                    "help": (
                        "Las mismas tablas completas, una hoja por tabla. Se instala aparte; si "
                        "falta, el informe sale igual con un aviso y sin el libro, salvo que "
                        "pidas lo contrario en «Opciones de la planilla». La opción «csv» entrega "
                        "lo mismo sin instalar nada."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "report.sections.missing_policy",
            "question": "¿Qué hacer si al informe le falta uno de los capítulos que exigiste?",
            "help": (
                "Un capítulo falta cuando el paso que lo produce no dejó su resultado en la "
                "corrida. La decisión se toma al armar el informe, con todo lo demás ya calculado."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "error",
                    "label": "Detener la corrida y nombrar el capítulo que falta",
                    "help": (
                        "Lo correcto cuando el informe va a un comité y un capítulo ausente lo "
                        "invalida: prefieres no tener documento antes que tener uno incompleto."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "warn",
                    "label": "Publicarlo marcado como no disponible",
                    "help": (
                        "El informe sale con ese capítulo declarado ausente y anotado entre las "
                        "limitaciones. Ningún número se inventa para rellenarlo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "skip",
                    "label": "Omitirlo en silencio",
                    "help": (
                        "El capítulo desaparece del documento como si no lo hubieras exigido: el "
                        "informe sale más corto y sin rastro de la ausencia."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "report.html.theme",
            "question": "¿Con qué presentación quieres el informe que se abre en el navegador?",
            "help": (
                "Cambia sólo el aspecto de ese documento y del que sale paginado a partir de él; "
                "los números, las tablas y el texto son exactamente los mismos."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "nikodym",
                    "label": "La presentación editorial de la casa",
                    "help": (
                        "Con índice lateral navegable y el estilo de marca; es la que se ve en los "
                        "informes de ejemplo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "plain",
                    "label": "Una hoja sobria, sin índice lateral",
                    "help": (
                        "Pensada para imprimir o para pegar el contenido dentro de la plantilla "
                        "corporativa de tu institución."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "report.document.placeholders",
            "question": "¿El informe debe traer los bloques que firma quien valida?",
            "help": (
                "Son los espacios en blanco con su guía de redacción —opinión de Validación, "
                "conclusiones, visto bueno— que el motor no llena porque los escribe una persona."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "show",
                    "label": "Publicarlos con su guía de redacción",
                    "help": (
                        "Quien valide ve qué se espera en cada bloque. Es lo útil mientras el "
                        "informe está en revisión y todavía se está escribiendo."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "hide",
                    "label": "Ocultarlos",
                    "help": (
                        "Lo que corresponde en la versión final del entregable, donde un espacio "
                        "en blanco se lee como un descuido y no como una tarea pendiente."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "report.ai.provider",
            "question": "¿Quién redacta el texto de acompañamiento del informe?",
            "help": (
                "Elijas lo que elijas, los números, las tablas y la prosa técnica los escribe el "
                "motor y son reproducibles. Esto sólo aplica si además activas esa ayuda."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "none",
                    "label": "El propio motor, sin salir a la red",
                    "help": (
                        "El texto de acompañamiento se redacta con reglas fijas dentro de tu "
                        "máquina. Es lo que corre de fábrica y no manda nada a ningún servicio."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "anthropic",
                    "label": "Un modelo de lenguaje externo",
                    "help": (
                        "Redacta el acompañamiento a partir de un resumen ya depurado: nunca "
                        "recibe tus datos ni recalcula una cifra. Se instala aparte y pide la "
                        "credencial en una variable de entorno; sin ella el informe sale con el "
                        "texto del motor y un aviso."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
    "provisioning": (
        {
            "path": "provisioning.rule",
            "question": "¿Cómo se constituye la provisión que vas a reportar?",
            "help": (
                "Con dos cálculos sobre la misma cartera hay que declarar cuál manda. La respuesta "
                "depende de qué dos comparas y de si la Comisión evaluó tu método interno."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "max",
                    "label": "El mayor de los dos",
                    "help": (
                        "Entre el método estándar de la CMF y el método interno del banco, y a "
                        "nivel de entidad, es la regla del Capítulo B-1 (Circular N° 2.346). Con "
                        "cualquier otro par es un contraste entre marcos contables, no una "
                        "exigencia chilena."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "use_internal",
                    "label": "El método interno del banco, aunque el estándar sea mayor",
                    "help": (
                        "El mismo párrafo del B-1 lo permite cuando la Comisión evaluó y no objetó "
                        "ese método. Exige que el método interno sea uno de los dos cálculos "
                        "comparados; acreditar la no objeción es tuyo, el motor no la verifica."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning.source_a",
            "question": "¿Cuál es el primer cálculo de provisión que quieres comparar?",
            "help": (
                "No se recalcula nada aquí: se toma el resultado que ese cálculo ya publicó en la "
                "misma corrida, así que su sección tiene que estar activa o la corrida no arranca."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "provisioning_cmf",
                    "label": "El método estándar de la CMF",
                    "help": (
                        "La provisión del Capítulo B-1 con las matrices de la Comisión. Es el "
                        "operando que la norma chilena pone a la izquierda de la regla del mayor."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "provisioning_internal",
                    "label": "El método interno del banco",
                    "help": (
                        "La provisión con la probabilidad de incumplimiento, la severidad y la "
                        "exposición propias de la institución, por grupos homogéneos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "provisioning_ifrs9",
                    "label": "La pérdida esperada bajo IFRS 9",
                    "help": (
                        "La pérdida crediticia esperada por etapas. Útil para contrastar marcos "
                        "contables —por ejemplo, una filial que reporta a una matriz extranjera—, "
                        "no para la provisión que exige la norma chilena."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning.source_b",
            "question": "¿Contra qué segundo cálculo lo quieres comparar?",
            "help": (
                "Tiene que ser distinto del primero: comparar un resultado consigo mismo no es una "
                "comparación. La que exige la norma chilena es contra el método interno del banco."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "provisioning_internal",
                    "label": "Contra el método interno del banco",
                    "help": (
                        "Es el contraste que pide el Capítulo B-1 frente al método estándar. "
                        "Necesita que la sección del método interno esté activa en la corrida."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "provisioning_ifrs9",
                    "label": "Contra la pérdida esperada bajo IFRS 9",
                    "help": (
                        "Contraste entre marcos contables: ninguna norma chilena lo exige, porque "
                        "el deterioro de la NIIF 9 no rige sobre las colocaciones. El informe lo "
                        "declara así en vez de presentarlo como piso regulatorio."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "provisioning_cmf",
                    "label": "Contra el método estándar de la CMF",
                    "help": (
                        "Lo mismo que dejar el estándar en el primer lugar, con los dos cálculos "
                        "en el orden inverso: el informe nombra cuál de los dos terminó mandando."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning.comparison_level",
            "question": "¿A qué nivel de agregación quieres que se aplique la regla?",
            "help": (
                "La norma chilena la fija por entidad. Los niveles más finos sirven para ver dónde "
                "muerde cada cálculo, pero sumar el mayor de cada celda sobre-reporta frente al "
                "mayor de la entidad, así que no son la provisión a constituir."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "total",
                    "label": "Una sola cifra para toda la institución",
                    "help": (
                        "El nivel que manda el Capítulo B-1: la regla se aplica por cada "
                        "institución en Chile que consolida con el banco. Es el que corre de "
                        "fábrica."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "portfolio",
                    "label": "Cartera por cartera",
                    "help": (
                        "Diagnóstico de en qué carteras muerde cada cálculo. Si los dos no usan la "
                        "misma taxonomía hay que declarar la equivalencia a mano: nunca se adivina "
                        "por parecido de nombre."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "segment",
                    "label": "Segmento por segmento",
                    "help": (
                        "El mismo diagnóstico sobre el corte que tú definas. Exige además que "
                        "declares qué columna del resultado marca el segmento, o el formulario no "
                        "acepta la elección."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "operation",
                    "label": "Operación por operación",
                    "help": (
                        "El detalle máximo. Exige que los dos cálculos cubran exactamente las "
                        "mismas operaciones: si uno trae operaciones que el otro no, la corrida se "
                        "detiene nombrando las que sobran."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning.coverage_policy",
            "question": "¿Qué hacer con una celda que sólo cubre uno de los dos cálculos?",
            "help": (
                "Sólo interviene si comparas a un nivel más fino que la institución: con una sola "
                "cifra para toda la cartera, los dos cálculos la cubren siempre."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "use_available",
                    "label": "Reportar lo que hay y marcarlo",
                    "help": (
                        "Se reporta el único cálculo disponible en esa celda y el informe la "
                        "declara como comparación incompleta, con su brecha de dato a la vista."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "fail",
                    "label": "Detener la corrida",
                    "help": (
                        "Lo correcto cuando los dos perímetros deberían calzar y quieres enterarte "
                        "antes de firmar, no leerlo en una nota al pie del informe."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "treat_missing_as_zero",
                    "label": "Suponer cero en el cálculo que falta",
                    "help": (
                        "Deja la celda completa, pero subestima la provisión: el cálculo ausente "
                        "entra como cero. El informe lo declara como brecha de dato, celda a celda."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning.numeric_reconciliation",
            "question": "¿Con qué exactitud quieres que se comparen los dos montos?",
            "help": (
                "El método estándar y el interno publican montos contables exactos; la pérdida "
                "esperada bajo IFRS 9 los publica con coma flotante, así que hay que llevarlos a "
                "un terreno común. No interviene si decides reportar el método interno."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "decimal_quantize",
                    "label": "En el terreno contable exacto",
                    "help": (
                        "Compara sin perder centavos y reporta el monto tal como lo publicó su "
                        "cálculo de origen. Es lo que conserva la exactitud regulatoria."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "float_isclose",
                    "label": "En el terreno económico",
                    "help": (
                        "Compara con la aritmética de coma flotante. Es más laxo con diferencias "
                        "mínimas, pero el monto reportado se reconstruye desde ella y puede perder "
                        "dígitos frente al original."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
        {
            "path": "provisioning.rounding",
            "question": "¿Con cuántos decimales quieres la provisión reportada?",
            "help": (
                "Se aplica a cada celda antes de sumarlas, así que el total reportado es la suma "
                "de las celdas ya redondeadas y no el redondeo de la suma."
            ),
            "multiple": False,
            "options": (
                {
                    "value": "none",
                    "label": "Sin redondear",
                    "help": (
                        "Entrega el valor exacto. Es lo que conviene si el redondeo contable lo "
                        "aplica después tu sistema de cierre y no quieres redondear dos veces."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "currency_2dp",
                    "label": "A dos decimales",
                    "help": (
                        "Redondea a dos decimales, hacia arriba en el medio punto. La forma "
                        "habitual de presentar un monto en una moneda con centavos."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
                {
                    "value": "integer_currency",
                    "label": "A la unidad de moneda",
                    "help": (
                        "Redondea a entero, hacia arriba en el medio punto. Es lo que corresponde "
                        "en monedas sin fracción decimal."
                    ),
                    "estado": _DISPONIBLE,
                    "motivo": None,
                    "prueba": None,
                },
            ),
        },
    ),
}


def _exige_claves(
    entrada: dict[str, Any],
    esperadas: frozenset[str],
    que: str,
    *,
    opcionales: frozenset[str] = frozenset(),
) -> None:
    """Falla si el literal trae una clave que este serializador no sabe publicar.

    🔴 Es el mecanismo que los serializadores de abajo decían tener y no tenían. Escribirlos campo
    a campo hace que una clave nueva **no se cuele** al contrato REST con la forma que tuviera, pero
    por sí solo NO avisa: la descarta en silencio. Medido — añadir una clave al literal de
    ``external_artifacts`` dejaba los 31 gates del catálogo en verde y el dato desaparecía por el
    camino. Eso convierte cualquier campo nuevo en una feature muerta y silenciosa, que es el modo
    de fallo que este repo ya pagó con D-JOB-17 (implementado, probado y sin una sola llamada).

    ⚠️ ``opcionales`` existe para una clave que **sólo tiene sentido en un estado**, y su uso es
    estrecho a propósito: obligar a las 207 opciones del abanico a declarar ``exige: ()`` para las
    tres que lo usan sería ruido que esconde la señal. La contrapartida —que una clave opcional
    puede faltar sin que nadie lo note— la paga un gate que exige la **bicondicional**: ``exige``
    no vacío si y sólo si el estado es ``exige_otro_campo``. Sin ella, «opcional» degeneraría en
    «olvidable», que es la trampa que este mismo mecanismo existe para cerrar.
    """
    sobran = sorted(set(entrada) - esperadas - opcionales)
    faltan = sorted(esperadas - set(entrada))
    if sobran or faltan:
        raise ValueError(
            f"{que}: el literal del catálogo no cuadra con lo que se publica"
            + (f"; sobra(n) {sobran} —decide cómo viaja(n) al contrato REST" if sobran else "")
            + (f"; falta(n) {faltan}" if faltan else "")
        )


_CLAVES_DE_FORMA = frozenset({"id", "label", "help", "template", "slots", "precargas"})
_CLAVES_DE_DECISION = frozenset({"path", "question", "help", "answer_forms"})
_CLAVES_DE_PRECARGA = frozenset({"slot", "desde", "insumo", "nota"})
_CLAVES_DE_ELECCION = frozenset({"path", "question", "help", "multiple", "options"})
#: Sólo la declara un punto que **no aplica siempre** (D-EXI-6). Misma forma que el `when` de
#: `external_artifacts`, que es el precedente vivo: `{"path": ..., "equals": ...}` evaluado por el
#: front con `valueAtPath`. Reutilizarlo evita inventar un segundo lenguaje de condiciones.
_CLAVES_OPCIONALES_DE_ELECCION = frozenset({"when"})
_CLAVES_DE_OPCION = frozenset({"value", "label", "help", "estado", "motivo", "prueba"})
#: Sólo la declaran las opciones en estado ``exige_otro_campo`` (D-EXI-2), y un gate exige la
#: bicondicional en los dos sentidos.
_CLAVES_OPCIONALES_DE_OPCION = frozenset({"exige"})


def _opcion_json(opcion: dict[str, Any]) -> dict[str, Any]:
    """Copia JSON-able de una opción del abanico (D-ABA-4), campo a campo.

    ⚠️ ``prueba`` **no se publica**: es la cita ``archivo:línea`` que sostiene un ``sin_efecto``, o
    sea evidencia interna para quien mantiene el catálogo, no algo que el usuario deba leer. Lo que
    él lee es ``motivo``, en su idioma. Es el mismo criterio con que el `path` viaja pero nunca se
    enseña (D-ABA-11), y con que los códigos de aviso declarado no van al copy público.

    ⚠️ ``exige`` SÍ se publica, y la asimetría con ``prueba`` es el punto: no es evidencia para el
    mantenedor sino la **ruta del control que el usuario tiene que llenar**, o sea exactamente lo
    que el front necesita para llevarlo ahí en vez de dejarlo leyendo una frase (D-EXI-2).
    """
    _exige_claves(
        opcion,
        _CLAVES_DE_OPCION,
        f"opción {opcion.get('value')!r} del abanico",
        opcionales=_CLAVES_OPCIONALES_DE_OPCION,
    )
    return {
        "value": opcion["value"],
        "label": opcion["label"],
        "help": opcion["help"],
        "estado": opcion["estado"],
        "motivo": opcion["motivo"],
        "exige": list(opcion.get("exige", ())),
    }


def _eleccion_json(eleccion: dict[str, Any]) -> dict[str, Any]:
    """Copia JSON-able de un punto de elección del abanico, campo a campo."""
    _exige_claves(
        eleccion,
        _CLAVES_DE_ELECCION,
        f"elección {eleccion.get('path')!r} del abanico",
        opcionales=_CLAVES_OPCIONALES_DE_ELECCION,
    )
    return {
        "path": eleccion["path"],
        "question": eleccion["question"],
        "help": eleccion["help"],
        "multiple": eleccion["multiple"],
        "options": [_opcion_json(o) for o in eleccion["options"]],
        "when": dict(eleccion["when"]) if eleccion.get("when") else None,
    }


def abanico_de(secciones: Iterable[str]) -> list[dict[str, Any]]:
    """Puntos de elección metodológica de un conjunto de secciones (D-ABA-2/3).

    Hermano exacto de :func:`decisiones_de`, y **por separado a propósito** (D-ABA-3): una decisión
    obligatoria no tiene default y el config **no construye** sin ella; un punto del abanico sí lo
    tiene y el motor corre. Fundirlos rompería el gate que impide que la tarjeta de decisiones se
    llene de cosas que el motor sí sabe rellenar — y con ello el sentido de esa tarjeta, porque *si
    todo es una decisión, ninguna lo es*.

    El orden es el del catálogo y no el de ``secciones``, por la misma razón que allí: dos trabajos
    con las mismas secciones tienen que ofrecer lo mismo en el mismo orden.
    """
    presentes = set(secciones)
    return [
        _eleccion_json(eleccion)
        for seccion, elecciones in _ABANICO_POR_SECCION.items()
        if seccion in presentes
        for eleccion in elecciones
    ]


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
        "slots": [_slot_json(s) for s in forma["slots"]],
        "precargas": [_precarga_json(p) for p in forma["precargas"]],
    }


def _precarga_json(precarga: dict[str, Any]) -> dict[str, Any]:
    """Copia JSON-able de una precarga (D-COL-8), campo a campo y exigiendo su forma exacta."""
    _exige_claves(precarga, _CLAVES_DE_PRECARGA, f"precarga de {precarga.get('slot')!r}")
    return {
        "slot": precarga["slot"],
        "desde": precarga["desde"],
        "insumo": list(precarga["insumo"]),
        "nota": precarga["nota"],
    }


def _slot_json(slot: Any) -> Any:
    """Copia JSON-able de un hueco, campo a campo y exigiendo su forma exacta."""
    if isinstance(slot, str):
        return slot
    if "alguno_de" in slot:
        _exige_claves(slot, frozenset({"alguno_de"}), "hueco «alguno de»")
        return {"alguno_de": list(slot["alguno_de"])}
    _exige_claves(slot, frozenset({"path", "salvo_si"}), f"hueco {slot.get('path')!r}")
    condicion = slot["salvo_si"]
    _exige_claves(condicion, frozenset({"path", "vale"}), f"condición de {slot['path']!r}")
    return {
        "path": slot["path"],
        "salvo_si": {"path": condicion["path"], "vale": list(condicion["vale"])},
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
    # 🔴 También en cada columna, y no sólo en la entrada de arriba: la revisión adversarial midió
    # que el mismo modo de fallo seguía vivo un nivel más abajo — una clave nueva dentro de
    # `columns` se reconstruía sin ella y sin protestar.
    for columna in entrada["columns"]:
        _exige_claves(
            columna,
            frozenset({"question", "config_paths"}),
            f"columna {columna.get('question')!r}",
        )
    condicion = entrada["when"]
    if condicion is not None:
        _exige_claves(condicion, frozenset({"path", "equals"}), "condición de un insumo externo")
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
            # Lista de parejas y no un objeto: el orden de aplicación es parte del dato —dos
            # overrides sobre rutas anidadas del mismo bloque tienen que aplicarse como se
            # escribieron— y un objeto JSON no lo garantiza en todos los clientes.
            "overrides": [[ruta, valor] for ruta, valor in job["overrides"]],
            "required_decisions": decisiones_de(job["sections"]),
            "methodology_choices": abanico_de(job["sections"]),
        }
        for job in _JOBS
    ]
