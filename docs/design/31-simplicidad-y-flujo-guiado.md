# SDD-31 — Simplicidad y flujo guiado (contrato transversal)

> **Estado: APROBADO por Cami el 2026-09-18** (sesión S16), de forma interactiva y con la
> recomendación de cada uno de los cinco puntos de §12, sobre seis decisiones que tomó ese mismo
> día (§0.2). Aprobar el contrato **no programa nada por sí solo**: cada módulo entra con su
> enmienda de simplicidad (la primera, la del scorecard, aprobada el mismo día). Es un contrato
> **transversal**, como SDD-30: no crea un paquete. Fija cómo se diseña, se expone y se entrega
> cada capacidad de `nikodym` desde ahora, y qué gate lo hace cumplir cuando, diez sesiones
> después, nadie se acuerde de por qué.
>
> **Base medida:** `main` = `fcd058d` (1.16.0). **Enmienda a:** [`../../AGENTS.md`](../../AGENTS.md)
> «Método de trabajo» (la directriz), [`_PLANTILLA-SDD.md`](_PLANTILLA-SDD.md) (sección §13 nueva),
> [`../ROADMAP.md`](../ROADMAP.md) (plan vigente) y [`../ESPECIFICACIONES.md`](../ESPECIFICACIONES.md)
> §2/§4/§5.9. **Primera aplicación:**
> [`_ENMIENDA-FLUJO-GUIADO-SCORECARD.md`](_ENMIENDA-FLUJO-GUIADO-SCORECARD.md).
>
> **No toca:** ningún motor, el `config_hash`, la garantía SemVer 1.x del pipeline F1, D-JUR,
> D-GOB, D-EST, D-SUB, D-OBL, D-JOB, D-PAR, D-SC, D-VAL, el arnés H9R ni CMF. **No autoriza** bump,
> tag, PyPI ni recaptura.

| Campo | Valor |
|---|---|
| **SDD** | 31 |
| **Módulo** | Contrato transversal de `nikodym`: cómo se usa la librería. No crea un paquete |
| **Fase** | F1…F8, todas; se aplica módulo a módulo en el orden de §10 |
| **Tanda de producción** | T9 (nueva): una enmienda de simplicidad por módulo, cada una con su implementación |
| **Estado** | Aprobado por Cami el 2026-09-18 con la recomendación de cada punto de §12 |
| **Depende de** | CT-1…4, SDD-01/05/23/26, D-JOB (UI por trabajos), D-SUB (subsección inerte), D-OBL (decisiones obligatorias), D-PAR (paridad 1:1), SCORECARD-COMPLETO |
| **Lo consumen** | Toda enmienda y SDD posterior, la plantilla, `ROADMAP.md`, `docs_site/`, la UI, los notebooks públicos |
| **Autor / Fecha** | Claude Code / 2026-09-18 |

## Recomendación ejecutiva

Adoptar **tres puertas de uso sobre un solo motor** —guiada, completa y de pantalla— y hacer de la
guiada la que se documenta primero. La puerta guiada se construye con lo que sólo la institución
sabe (datos, qué es «malo», identificador, eje temporal, cómo se separa la muestra), corre de punta
a punta con **defaults que funcionan**, **habla en cada etapa** con un resumen legible en español,
permite **parar en una etapa, decidir y seguir**, y deja como opcional el Excel numerado por etapa.
La puerta completa (el `NikodymConfig`) no desaparece: es la verdad que las otras dos rellenan, y
la identidad de la corrida sigue siendo el `config_hash`. Cada perilla nueva exige la evidencia de
que el default falla en un caso real; si no la tiene, es una constante. El contrato se hace cumplir
con una sección obligatoria en la plantilla de SDD y con goldens medibles por módulo (§5–§6), no
con prosa.

## 0. Por qué existe

### 0.1 La directriz, literal

Cami, 2026-09-15 (cierre 3 de la S15): «a veces siento que metemos muchas cosas, muchas
configuraciones que quizás nunca usarán; siento que a veces hay más valor en algo no con mil
configuraciones pero que funcione, y eso es para toda la librería… eso es más profundo».

Cami, 2026-09-18 (S16): «está demasiado difícil de usar en general y cada módulo […] en el banco
que trabajaba gente que no sabía Python pero sí estadística modelaba con eso y resultaba bien
porque veían los Excel, los resultados, y era sencillo […] la interfaz gráfica pasa similar: miles
de cosas opcionales que está bien que estén pero deberían estar contraídas […] Siento que tenemos
el fondo; esto es cosa de forma […] es casi un cambio de paradigma […] el modo de trabajo y la
simplicidad tienen que aplicarse a la librería completa».

### 0.2 Lo que Cami decidió el 2026-09-18, de forma interactiva

1. **Paradigma:** `run()` de una línea con defaults; **se puede parar en una etapa y seguir**
   (descartes, recategorizar, tramos) desde esa etapa.
2. **Público primario:** el modelador que sabe estadística y no Python. Los resultados se ven **por
   etapa, dentro del notebook o de la interfaz**, según lo que elija para modelar; el Excel
   numerado por etapa es **opcional**, no obligatorio.
3. **Interfaz:** cada sección muestra sus campos **esenciales** y pliega el resto en «Avanzado».
4. **MLflow:** opt-in de una línea, apagado por defecto.
5. **Idioma:** identificadores en inglés; todo lo que se lee, en español.
6. **Plan:** se pausa ENTREGABLES-LEGIBLES → INTEGRACION-EXTERNA; este contrato va primero, se
   aplica a la librería entera, y el roadmap se pavimenta hasta terminar la librería con el
   scorecard e IFRS 9 como urgentes.

### 0.3 Medido sobre `fcd058d`, y contra el flujo del banco

El contraste se midió contra el flujo de modelación que Cami diseñó y operó en un banco (una clase
`modelacion` con 39 métodos, más un notebook de 79 celdas; la carpeta privada `codigo_modelacion`,
que **no entra a ningún repo**: trae credenciales y un project id reales, y `ROADMAP.md` prohíbe
copiar SQL, defaults o metodología institucional; de ahí se toma el **patrón**, no el código).

| Qué | Flujo del banco | Nikodym hoy |
|---|---|---|
| Lo que el modelador escribe para correr | 27 llamadas, **79 parámetros** como máximo (la mayoría con default), un Excel de dos columnas con las variables | Un `NikodymConfig`: el preset F1 son ~380 líneas de literal (`ui/presets.py`); la Clase 6 de Academia Bayes necesitó una celda de **83 líneas** con el esquema de 108 columnas |
| Lo que ve al correr | Cada paso imprime 1–5 líneas («Eliminados por IV: […] · puede revisar el archivo excel») | `nikodym.run()` **no imprime nada**; los resultados se buscan con `study.artifacts.get(dominio, clave)` |
| Entregable por etapa | 15 archivos numerados (`02 Analisis Bivariado`, `05 Modelo`, `06 Scorecard`, `10 TDR`…) | Ninguno por etapa; al final un informe HTML de **8 + 3 secciones, 126 tablas y 614 KiB** (Clase 6) |
| Decisiones humanas entre pasos | Son pasos: listas de descarte por negocio, recategorización manual, exclusión en el modelo final; quedan en `01 Registro de Parametros.txt` | Por config (`force_exclude`, `variable_overrides`), antes de correr y sin motivo registrado |
| Perillas visibles en pantalla | — | **572 campos** en 17 secciones (`HOJAS_DEL_FORMULARIO`, `tests/unit/test_effective_defaults.py:106`): `data` 158, `provisioning_ifrs9` 48, `provisioning_internal` 44, `binning` 42, `selection` 33, `report` 33, `validation` 28, `provisioning_cmf` 28, `survival` 24, `model` 23, `provisioning` 19, `eda` 17, `scorecard` 17, `calibration` 16, `stability` 16, `governance` 14, `performance` 12; los grupos de cada sección se pintan **todos abiertos** (`web/src/components/ConfigTab.tsx:748-752`) |
| Perillas que la receta curada toca de verdad | ≈30 de las 79 (las demás quedan en default) | **14 de 202** hojas comparables (medido el 2026-09-15 sobre el preset F1) |
| Lo que Nikodym tiene y el banco no tenía | — | Reproducibilidad (`config_hash`, `data_hash`, semilla, lock), audit-trail con 300+ decisiones, ficha del modelo, informe, validación formal, bundle de aplicación, 276 archivos de test, UI |

La conclusión que sostiene este contrato: **el fondo existe** (cada paso del banco tiene su motor en
Nikodym, y Nikodym tiene lo que el banco nunca tuvo); lo que falta es la **forma** de usarlo, y esa
forma hay que fijarla por contrato para que no vuelva a crecer por acumulación.

## 1. Propósito y responsabilidad

- **Qué resuelve:** que una persona que sabe riesgo de crédito y estadística construya, revise y
  documente un modelo con Nikodym **sin conocer el config completo**, y que quien sí lo conoce no
  pierda nada.
- **Sí hace:** fija las tres puertas de uso (§4, D-SIM-1), la entrada mínima (D-SIM-2), la regla de
  los defaults y las perillas (D-SIM-3/4), el resumen por etapa (D-SIM-5), parar y seguir (D-SIM-6),
  los entregables (D-SIM-7/8), el idioma (D-SIM-9), MLflow (D-SIM-10), las métricas de simplicidad
  (D-SIM-11), la poda (D-SIM-12), y cómo se hace cumplir (§6).
- **No hace:** no diseña ningún módulo (eso lo hace la enmienda de simplicidad de cada uno, la
  primera es la del scorecard), no toca motores, no retira perillas en 1.x, no cambia qué es una
  decisión institucional (D-OBL) ni cómo se muestra un error (D-VIS).

## 2. Contexto y ubicación en la arquitectura

Se apoya en contratos que ya existen y **no los reabre**:

- **CT-1…4:** el DAG por `requires`/`provides`, los resultados aditivos, el ensamblado en `api`. La
  puerta guiada es un cliente más de `nikodym.run`/`Study`; no crea un segundo orquestador.
- **D-JOB:** la interfaz se organiza por trabajo y cada trabajo decide sus secciones. «Esencial /
  avanzado» actúa **dentro** de cada sección, después de ese filtro.
- **D-SUB y `hidden`:** ya existe la mecánica de ocultar un campo con su razón medida (ocho campos de
  `validation` en la capa 2 de SCORECARD-COMPLETO). «Avanzado» es la misma mecánica con otra
  política: se pliega, no se esconde.
- **D-OBL:** lo que sólo la institución puede fijar se pregunta; nunca se inventa. La entrada mínima
  de D-SIM-2 son exactamente esas decisiones, y nada más.
- **D-PAR:** paridad 1:1 Python ↔ interfaz. Las tres puertas son la misma corrida (mismo config,
  mismo `config_hash`), o no son puertas.
- **SDD-26 (informe) y D-GOB (ficha):** siguen siendo los entregables de cierre; el resumen por
  etapa no los sustituye, los precede.

## 3. Conceptos

- **Perilla:** una hoja del config que el formulario pinta o que un `Field` expone. Se cuenta con el
  barrido de `HOJAS_DEL_FORMULARIO`.
- **Decisión institucional:** lo que el motor no puede rellenar por nadie (D-OBL): qué es «malo»,
  cómo se separa la muestra, el propósito del modelo, la tasa de largo plazo. No es una perilla: no
  tiene default.
- **Default que funciona:** un valor con el que la corrida termina y produce un resultado
  defendible sobre los datasets del paquete **y** sobre el caso real disponible, sin que nadie lo
  toque.
- **Esencial:** un campo que un modelador toca en una corrida normal. Se declara por sección, con
  tope (§12.1), y es lo único que se ve sin desplegar «Avanzado».
- **Etapa:** un paso del pipeline con nombre estable en inglés (`data`, `binning`, `selection`,
  `model`, …) y rótulo en español; es la unidad del resumen, de la parada y del Excel opcional.
- **Resumen por etapa:** 3–8 líneas en español más una tabla de decisión (lo que un modelador mira
  para decidir el paso siguiente), sin identificadores del motor.
- **Decisión humana:** una acción del usuario entre etapas (descartar, recategorizar, fijar cortes)
  con **motivo**, que modifica el config y queda en el trail como decisión con autor.
- **Presupuesto de perillas:** cuántas hojas nuevas entra una capa y por qué cada una no puede ser
  una constante. Nace en cero para toda enmienda.

## 4. Las reglas (D-SIM-1 … D-SIM-12)

**D-SIM-1 — Tres puertas, un motor.** Toda capacidad entregada se usa por (a) la **puerta guiada**
—una línea con defaults, resúmenes por etapa, parar y seguir—, (b) la **puerta completa** —el
`NikodymConfig` íntegro, por YAML o por código— y (c) la **pantalla**. Las tres producen el mismo
config, el mismo `config_hash` y **los mismos resultados** (artefactos, métricas, informe); la
**procedencia** puede diferir —la guiada registra además sus inferencias y las decisiones humanas
con autor y motivo— y el trail declara por qué puerta entró la corrida. Una capacidad se declara
**entregada** cuando cierran las tres puertas (misma regla que D-PAR); una puerta puede publicarse
antes que las otras **sólo marcada «experimental»** en el copy público y en el CHANGELOG, como el
resto de superficies experimentales bajo SemVer 1.x (cláusula aprobada por Cami el 2026-09-18 tras
la pasada 1 de Codex). La guiada es la que se documenta primero en `docs_site/`.

**D-SIM-2 — Entrada mínima = decisiones institucionales.** La puerta guiada se construye sólo con lo
que el motor no puede saber: los datos, qué es «malo», el identificador, el eje temporal (fecha o
cohorte) y cómo se separa la muestra; en módulos con insumos propios, sus columnas de negocio
(exposición, fecha de corte, severidad…). Lo que se puede inferir **se infiere y se declara** (el
esquema de las columnas, los tipos, cuáles son categóricas, qué columnas son predictoras), con la
inferencia registrada en el trail como decisión, para que quien la quiera cambiar sepa qué cambió.
Lo que es decisión institucional **no se infiere** (D-OBL-5: el motor no siembra criterio
institucional): la regla del target se pasa; la estrategia de partición **sigue a lo declarado**
(`date` → por fecha, `cohort` → por cohortes; sin eje, `partition="random"` explícito) y la frontera
OOT se exige; si falta, la puerta se detiene **antes de correr** y dice qué valor usaría.

**D-SIM-3 — Defaults que funcionan, o constantes.** Cada default se prueba sobre los datasets del
paquete y sobre el caso real disponible; una perilla nueva entra sólo con la evidencia escrita de
que el default falla en un caso real (una corrida que termina mal o un resultado indefendible). Sin
esa evidencia, el valor es una constante del motor. El presupuesto de perillas de toda enmienda nace
en **cero** y cada excepción se justifica en su §13.

**D-SIM-4 — Esencial y avanzado.** Cada sección declara sus campos esenciales (tope en §12.1) con
una marca en el schema, y las tres puertas la respetan: la guiada sólo expone esenciales como
argumentos; la pantalla pinta los esenciales abiertos y el resto en un único bloque «Avanzado»
plegado; el resumen por etapa nombra sólo esenciales. Nada deja de ser accesible: «Avanzado» se
despliega, y la puerta completa lo ve todo.

**D-SIM-5 — Cada etapa habla.** Toda corrida produce, por etapa, un resumen legible en español con
la misma fuente para consola (texto), notebook (`_repr_html_`) y pantalla (panel): qué se hizo, el
resultado en cifras que un comité entiende, y la **tabla de decisión** de esa etapa (IV por variable,
coeficientes con signo y p-valor, puntos por tramo, deciles por muestra, PSI con banda…). Sin
identificadores del motor: el gate de códigos internos (`test_report_codigos_internos`) se extiende
a estos resúmenes.

**D-SIM-6 — Parar y seguir.** La puerta guiada corre completa por defecto y admite detenerse en una
etapa (`run(until="selection")`) y continuar (`resume()`). **`run(until=)` corre el prefijo del
pipeline (`run.steps`) y `resume()` es una corrida nueva y completa sobre el config vigente**
—`run_id`, lineage y `run_dir` propios; la anterior queda como respaldo—: no se reutilizan
artefactos entre corridas (la puerta de artefactos D-ART queda como candidata, con evidencia de
costo, para carteras grandes). Entre etapas el usuario toma decisiones humanas con motivo
(descartar, mantener, recategorizar, fijar cortes); cada una **modifica el config** y se emite al
trail como `decision` con autor `usuario` y su motivo. Así el config final sigue siendo la verdad:
`run()` completo sobre ese config reproduce los resultados, y las decisiones se leen en el trail y,
cuando hay `governance`, en la ficha.

**D-SIM-7 — Entregable por etapa, opcional.** La guiada exporta a pedido un libro Excel numerado por
etapa (`export_excel()`), con las mismas tablas del resumen y las tablas completas del anexo. Nunca
es obligatorio ni la vía para ver un resultado: el resultado se ve en el notebook o en pantalla. El
informe HTML/PDF/Word y la ficha siguen siendo el cierre.

**D-SIM-8 — Un notebook público por módulo.** Cada módulo entregado tiene un notebook que corre de
punta a punta con datos del paquete en **≤ N líneas de usuario** (N en §12.2), se ejecuta en CI como
los ejemplos de `docs_site/` y es el primer documento de su guía. Es el gate de simplicidad del
módulo: si el notebook necesita más líneas, el módulo no está sencillo.

**D-SIM-9 — Idioma.** Identificadores (clases, métodos, argumentos, claves de artefactos) en
inglés; todo lo que una persona lee (rótulos, resúmenes, Excel, informe, mensajes de error,
descripciones de campos) en español. Es la política vigente de copy público; aquí sólo se extiende
a los resúmenes por etapa.

**D-SIM-10 — MLflow, opt-in de una línea.** `tracking` sigue apagado de fábrica (exige instalar el
extra y decidir un destino). Encenderlo desde la puerta guiada es un argumento
(`track="./mlruns"` o una URI) y registra por corrida lo que ya define SDD-04: métricas planas,
config, lineage y artefactos. El registro por defecto sigue siendo el `run_dir` con trail y lineage.

**D-SIM-11 — La simplicidad se mide.** Cada módulo publica y ancla en gate cinco cifras: (1)
líneas de usuario del notebook mínimo; (2) campos esenciales por sección; (3) perillas totales de
sus secciones; (4) segundos hasta el primer resumen sobre el dataset del paquete; (5) conceptos que
el usuario debe conocer antes del primer resultado (identificadores distintos que aparecen en el
notebook mínimo). Cambiar una cifra es legítimo; cambiarla sin actualizar el golden y decir por qué,
no (misma regla que `HOJAS_DEL_FORMULARIO`).

**D-SIM-12 — Poda sin ruptura.** En 1.x ninguna perilla se retira (SemVer): se pliega en
«Avanzado», se oculta por D-SUB o se fija como constante con su razón. Retirar espera a un 2.0 con
un censo de uso (qué preset, trabajo, test o página movió cada hoja alguna vez; los oráculos ya
existen: `option_effect_oracles.txt`, el abanico, `option_surface_ledger`,
`HOJAS_DEL_FORMULARIO`). Es la enmienda SIMPLICIDAD-DEL-CONFIG que el HANDOFF anotó; entra después
de las dos primeras aplicaciones (§10).

## 5. Cómo se mide la simplicidad

Las cinco cifras de D-SIM-11 se anclan **por módulo** en un golden con el mismo estilo que
`HOJAS_DEL_FORMULARIO`: un número, una fecha y la razón del último cambio. Valores objetivo para el
scorecard (la primera aplicación los mide y los fija; §12.2 decide N):

| Cifra | Hoy (scorecard, Clase 6) | Objetivo |
|---|---|---|
| Líneas de usuario del notebook mínimo | 83 (config) + ~60 (lectura) | ≤ N |
| Campos esenciales por sección | todos (572 en 17) | ≤ tope de §12.1 por sección |
| Perillas de las doce secciones que tocan los dos trabajos del scorecard | 409 | sin crecer; poda en 2.0 |
| Segundos al primer resumen (dataset del paquete) | — (no hay resumen) | ≤ 30 s en el entorno de referencia |
| Conceptos antes del primer resultado | `standard_preset`, `materialize`, `NikodymConfig`, `run`, `Study`, `run_context`, `artifacts.get`, dominio/clave… | ≤ 5 |

## 6. Cómo se hace cumplir

1. **La plantilla de SDD gana la sección §13 «Simplicidad (SDD-31)»**, obligatoria: entrada mínima,
   qué NO se configura y por qué, esenciales por sección con su tope, presupuesto de perillas con
   la evidencia de cada excepción, resumen por etapa (qué dice), notebook mínimo (cuántas líneas) y
   las cinco cifras de D-SIM-11. Una enmienda sin §13 no se revisa.
2. **AGENTS.md** lleva la directriz en «Método de trabajo» (la frase de §12.3) y remite aquí.
3. **Gates:** el golden de esenciales por sección (barrido del schema por la marca), el golden de
   las cinco cifras por módulo, el notebook mínimo ejecutado en CI, el gate de códigos internos
   extendido a los resúmenes, y el gate de copy existente sobre los rótulos nuevos.
4. **Revisión:** Codex revisa cada enmienda de simplicidad con el §13 como lista de comprobación.

## 7. Qué debe entregar cada módulo para llamarse «sencillo»

1. Entrada mínima declarada (D-SIM-2) y probada con datos del paquete y con un caso real.
2. Puerta guiada con `run()`, `run(until=…)`/`resume()`, resumen por etapa y decisiones humanas
   propias del módulo (qué se descarta, qué se fija).
3. Esenciales por sección declarados y plegado en pantalla.
4. Notebook mínimo público en CI, y la guía de `docs_site/` empieza por él.
5. Excel opcional por etapa; informe y ficha como cierre (los que ya existen).
6. Las cinco cifras ancladas.

## 8. Casos borde del contrato

- **Sin eje temporal en los datos:** el usuario declara `partition="random"` (D-OBL-5: no se
  siembra) y la estabilidad temporal queda «No evaluable» con causa (regla que ya existe en
  `eda`/`stability`).
- **Frontera OOT ausente con `date`/`cohort`:** la puerta se detiene antes de correr, con el rango
  del archivo y el valor que usaría (D-OBL-5).
- **Sin identificador:** se usa el índice del archivo y se declara en el trail.
- **Target con nulos:** son solicitudes recientes sin desempeño (TTD); se puntúan, no se ajustan (implementado el 2026-09-25 por [`_ENMIENDA-PUNTUAR-POBLACION-TTD.md`](_ENMIENDA-PUNTUAR-POBLACION-TTD.md));
  el resumen de datos lo cuenta.
- **Decisión humana que deja el modelo sin variables:** la etapa siguiente falla con el mensaje del
  motor y el resumen anterior sigue disponible; nada se pierde.
- **Cambio del config después de parar:** `resume()` corre el pipeline completo de nuevo sobre el
  config vigente; nada se reutiliza y nada queda obsoleto.
- **Un campo esencial sin default (decisión institucional):** se pregunta; no hay valor de fábrica
  que lo tape (D-OBL).

## 9. Reproducibilidad y auditoría

- El config final de una corrida guiada es un `NikodymConfig` completo; su `config_hash` es la
  identidad, y `run()` sobre ese config reproduce la corrida sin la puerta guiada.
- Cada inferencia (esquema, categóricas, predictoras) y cada decisión humana se emite al trail como
  `decision` con `autor` y `motivo`, y un evento de entrada nombra la puerta; la ficha del modelo
  —cuando hay `governance`— las lista en su sección de decisiones. La **procedencia es declarada,
  no idéntica** entre puertas (D-SIM-1); el lineage no cambia.
- El Excel opcional y los resúmenes se derivan de los mismos artefactos que el informe: no hay una
  segunda aritmética.

## 10. Orden de aplicación por módulo

Uno a la vez, cada uno con su enmienda medida, su implementación por capas y su notebook:

1. **Scorecard** (`_ENMIENDA-FLUJO-GUIADO-SCORECARD.md`) — urgente.
2. **IFRS 9 / ECL** — urgente; misma entrada mínima de cartera (fecha de corte, exposición, mora,
   tasa efectiva, PD del scorecard o curva propia).
3. **LGD/EAD y provisión interna** (el trabajo «PD + LGD»).
4. **Validación y monitoreo periódico** (incluye el módulo de monitoreo con historia que hoy falta).
5. **Escala maestra y puntos de corte** (módulo pequeño que hoy falta).
6. **ML retador** (bloque B de PARIDAD-1-1).
7. **Forward, survival, Markov y stress** (bloque C).
8. **Originación y reject inference** (nuevo).

El detalle, con hitos y lo que falta para que la librería sea de referencia, vive en
[`../ROADMAP.md`](../ROADMAP.md) («Plan vigente desde 2026-09-18»).

## 11. Estrategia de tests

- Golden de esenciales por sección (bidireccional: una marca sin campo y un campo esencial sin
  marca ponen rojo).
- Golden de las cinco cifras por módulo.
- Notebook mínimo ejecutado en CI (como los bloques `quickstart:start/end` de `docs_site/`).
- Gate de códigos internos sobre los resúmenes por etapa.
- Control negativo por enmienda: inyectar una perilla sin evidencia en un §13 y ver que la revisión
  la rechaza; añadir un campo esencial de más y ver el golden en rojo.

## 12. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 12.1 | Tope de campos esenciales por sección | (a) **6**; (b) 4; (c) sin tope, sólo medido | **(a)**: cabe en una pantalla sin desplazarse y en una firma legible; `data` necesitará las 5 decisiones institucionales |
| 12.2 | N líneas de usuario del notebook mínimo (D-SIM-8) | (a) **≤ 25**; (b) ≤ 40; (c) sin tope | **(a)**: el flujo del banco arrancaba con 14 líneas; 25 deja espacio a dos decisiones humanas y al informe |
| 12.3 | La frase en `AGENTS.md` («Método de trabajo») | (a) **la propuesta**: «Menos configuraciones, defaults que funcionan. Antes de añadir una perilla, medir que el default falla en un caso real; si no falla, es una constante. Cada enmienda declara qué NO se configura, sus campos esenciales y su presupuesto de perillas (SDD-31). El escaparate se juzga por lo que funciona sin tocar nada»; (b) otra redacción de Cami | **(a)** |
| 12.4 | Horizonte de la poda (D-SIM-12) | (a) **2.0 con censo de uso**; (b) plegar y fijar bastan, no habrá retiro | **(a)**: fijar sin retirar deja 572 hojas que alguien debe seguir documentando y gateando |
| 12.5 | Orden de módulos de §10 | (a) **el propuesto**; (b) IFRS 9 antes que el scorecard; (c) otro | **(a)**: el scorecard produce la PD que IFRS 9 consume, y su enmienda ya está escrita |

**Respuestas de Cami (2026-09-18, interactivas): (a) en las cinco.** Valores vigentes: tope de
**6** campos esenciales por sección; notebook mínimo de **≤ 25** líneas de usuario; la frase de
12.3 ya vive en `AGENTS.md` («Método de trabajo»); la poda espera al **2.0 con censo de uso**; el
orden de §10 es el vigente.

**Respuestas de Cami a la pasada 1 de Codex (2026-09-18, cuatro hallazgos contractuales):**
D-OBL-5 **se respeta** (la frontera OOT se exige y la estrategia sigue a lo declarado; D-SIM-2);
D-SIM-1 gana la **cláusula de adelanto declarado** (una puerta puede salir antes marcada
«experimental»); la paridad es de **config, `config_hash` y resultados**, con la procedencia
declarada (D-SIM-1/6, §9); `resume()` es una **corrida nueva y completa** (D-SIM-6).
