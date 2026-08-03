# Enmienda SDD — «Respondida» lo dice el motor, no la forma del hueco

> **Estado: APROBADA por Cami (2026-08-03) e IMPLEMENTADA.** Aprobó el camino tras leer la medición
> que lo cambió: no son dos casos sino 49 de 63, y no hace falta ningún campo de contrato nuevo.
>
> **Base:** `main` = `58a3940`. **Autor / Fecha:** DanIA / 2026-08-03.
>
> **Enmienda a:** `_ENMIENDA-DECISIONES-OBLIGATORIAS.md` (D-OBL-5, qué significa que una decisión
> esté contestada) y `_ENMIENDA-DECISIONES-COMO-DATO.md` (D-COL-6, los `slots` de una forma).
>
> **No toca:** el `config_hash` de ningún config, el catálogo de secciones, el criterio de qué
> secciones muestra un trabajo (D-JOB-1), ni la puerta de artefactos.

| Campo | Valor |
|---|---|
| **Problema** | La interfaz pone el tilde de «Respondida» sobre decisiones que el motor **rechaza**. Medido: **49 de 63** valores probados, no los 2 casos conocidos |
| **Release** | Cambio de comportamiento de UI ⇒ **minor**. Esta enmienda no autoriza bump, tag ni publicación |

## 1. Evidencia medida

Todo lo de esta sección se ejecutó contra `50e06e4`. La reimplementación en Python del criterio del
front se **contrastó contra el `jobs.ts` real** del repo, cargado con `node --experimental-strip-types`
sobre los mismos 63 casos: **0 discrepancias**. Lo que sigue es el veredicto del front real, no el de
una lectura del front.

### 1.1 🔴 No son dos casos: son 49 de 63

El criterio vigente (`decisionStatuses`, `huecosPendientes`) marca «Respondida» cuando la clave del
path existe y ningún `slot` **declarado y presente** está vacío. Eso deja pasar tres familias enteras:

1. **Todo hueco AUSENTE se ignora** —y es a propósito, porque `bad_rule` no lleva discriminador y el
   front no puede saber qué forma eligió el usuario—. Consecuencia: `{"type": "temporal"}`,
   `{"type": "cohort"}` y `{"type": "columna"}` pelados salen con tilde verde.
2. **Todo tipo incorrecto pasa.** `estaVacio` sólo reconoce `""`, `null` y colección vacía, así que
   un número donde va una lista, un string donde va un objeto o un `None` en la raíz de la decisión
   son «no vacíos» ⇒ «Respondida».
3. **La forma `random` no declara ningún slot**, así que **cualquier** valor con `type: "random"`
   sale «Respondida» sin excepción — incluidas las fracciones que no suman 1.

### 1.2 Y hay tres falsos NEGATIVOS, que importan igual

Los templates crudos de `columna_marcada`, `temporal` y `cohort` —con sus huecos en `""`— **los
acepta el motor**. Salen «Te falta un dato» sobre un config que `model_validate` valida.

⇒ **«Válido para el motor» NO equivale a «respondida»**, en ninguna de las dos direcciones. Un
criterio que sustituyera los `slots` por `model_validate` cambiaría de falla, no la eliminaría:
`date_col = ""` valida y muere en ejecución.

### 1.3 El `loc` del error casa con la decisión — 46 de 49

`/api/validate` ya devuelve `errors[].loc`, y el front ya lo recibe. Medido sobre los 49:

| familia | `loc` | ¿casa con el path de la decisión? |
|---|---|---|
| `bad_rule` con listas vacías, `{}`, o de tipo incorrecto | `data.target.bad_rule` | ✅ exacto |
| predicado sin `col`/`op`, `op` inválido, claves extra | `data.target.bad_rule.all_of.0.…` | ✅ descendiente |
| `strategy` sin discriminador, o de tipo incorrecto | `data.partition.strategy` | ✅ exacto |
| rama sin sus campos, campos de otra rama, rangos | `data.partition.strategy.<tag>.…` | ✅ descendiente |
| `survival.input.*` con `None` o numérico | `survival.input.duration_col` | ✅ exacto |
| **`survival.input.*` con cadena vacía** | **`[]`** | ❌ **no casa** |

⚠️ **Dos trampas medidas del `loc`, que hay que respetar al implementarlo.**

1. **Pydantic inserta el tag del discriminador**, y ese segmento **no existe en el config**: el
   error de `date_col` llega como `data.partition.strategy.temporal.date_col`, mientras el campo
   real es `data.partition.strategy.date_col`. De 6 `loc` probados, **5 no son paths reales**. Casar
   por prefijo funciona; **enfocar el campo con ese `loc` no**.
2. Los 3 que no casan traen `loc = []` **por construcción**: `_error_de_dominio` (`ui/routes.py:991`)
   se niega a fabricar un `loc` a partir del texto del mensaje, y **tiene razón** — sería adivinar.

### 1.4 El bloqueante previo, ya cerrado en esta misma sesión

Sin esto, nada de lo anterior era alcanzable: **doce clases `*ConfigError` de dominio no heredaban
de `ConfigError`**, así que el `except` del endpoint no las veía y `/api/validate` devolvía **500**
sobre configs alcanzables desde el formulario. Con un 500 no hay `errors` que casar con nada.
Corregido en `58a3940`, con gate nominal y funcional.

### 1.5 Dos premisas del plan, refutadas al medirlas

1. **«El front no puede saber qué forma eligió el usuario».** Cierto **sólo para `bad_rule`**. Para
   `data.partition.strategy` **sí puede, hoy**: es una unión discriminada por `type`, y los `id` de
   forma del catálogo son **el mismo conjunto** que los tags de la unión —hay un gate bidireccional
   vigente que lo obliga—. El comentario de `huecosPendientes` generalizó de 2 formas sin
   discriminador a las 6.
2. **«Cerrarlo exige que el backend publique qué forma aplica».** No hace falta: para `strategy` el
   discriminador ya viaja en el propio valor, y para `bad_rule` el `loc` del error casa exacto. **No
   nace ningún campo de contrato nuevo.** Es la conclusión que abarata la enmienda entera.

## 2. Decisiones

**D-RES-1 — Una decisión está contestada si el motor la acepta Y no le falta ningún hueco de su
forma.** Los dos criterios, conjuntos. Ninguno basta solo, y §1.2 lo mide en las dos direcciones:
los `slots` cazan lo que el motor acepta pero está incompleto (`date_col = ""`); el veredicto del
motor caza lo que los `slots` no ven (rama sin sus campos, tipo incorrecto, `random` con cualquier
cosa).

**D-RES-2 — El veredicto del motor llega por el `loc` de `/api/validate`, casado por PREFIJO.** Un
error cuyo `loc` sea el path de la decisión o descienda de él la deja sin contestar. No nace ningún
endpoint, ni campo, ni llamada: el front ya recibe esos errores y ya los tiene en el store.

**D-RES-3 — El `loc` sirve para CASAR, nunca para enfocar.** Lleva el tag del discriminador, que no
existe en el config (§1.3). El salto al campo sigue usando el mecanismo vigente del preflight, que ya
degrada del id más específico al más general.

**D-RES-4 — Mientras la validación no ha vuelto, el estado no se inventa.** El criterio de huecos
sigue mandando en solitario: es lo que hay hoy y es correcto en su alcance. Marcar «no contestada»
por el hecho de no tener veredicto todavía haría parpadear la tarjeta en cada tecleo.

**D-RES-5 — Los 3 casos con `loc = []` se declaran, no se adivinan.** `survival.input` con cadena
vacía produce un error de dominio sin coordenada, y su mensaje nombra los campos **en el copy**.
Parsear copy público para fabricar un `loc` es exactamente lo que `_error_de_dominio` se niega a
hacer, y esta enmienda no lo reabre. ⚠️ Quedan como limitación **escrita**: son 3 de 49, y su
desenlace no es un falso «ya está» silencioso sino un error visible al ejecutar.

⚠️ **Y hay un cuarto modo de fallo genuinamente indivisible**, medido: `duration_col == event_col` es
una relación **entre** las dos decisiones. Ninguna asignación a una sola sería correcta, así que
tampoco se intenta.

**D-RES-6 — Esto no toca el motor ni ninguna identidad.** No hay campo nuevo de config, no se mueve
ningún `config_hash`, y el catálogo de trabajos no cambia. Es criterio de interfaz sobre datos que
ya viajan.

## 3. Alternativas rechazadas

1. **Que el backend publique «qué forma aplica»** (el camino que el plan traía escrito). Medido
   innecesario: para `strategy` el discriminador ya está en el valor y para `bad_rule` el `loc` casa
   exacto. Añadiría un campo de contrato para comprar algo que ya se tiene.
2. **Sustituir los `slots` por `model_validate`.** Cambia de falla en vez de cerrarla: 3 casos
   válidos para el motor están incompletos de verdad (§1.2).
3. **Declarar los slots de `random`** para taparle el agujero. No hay nada que declarar: sus tres
   fracciones son defaults del motor, no criterio de la institución. Su agujero lo cierra el
   veredicto, no un hueco inventado.
4. **Endurecer `estaVacio` para que reconozca tipos incorrectos.** Sería reimplementar el schema del
   dominio en el front (SDD-23 §11), y encima parcialmente.
5. **Parsear el mensaje para fabricar un `loc`.** Es adivinar, y `_error_de_dominio` ya lo rechazó
   con su razón escrita.

## 4. Gates de aceptación

- **Los 49 casos medidos dejan de decir «Respondida»**, y los 3 falsos negativos dejan de decir «Te
  falta un dato». La tabla se escribe **a mano** en el test: derivarla del mismo criterio que se
  comprueba sería el gate autorreferencial que este repo ya pagó dos veces.
- **Control positivo obligatorio**: los tres presets siguen con sus decisiones «Respondida». Sin él,
  un criterio que dijera «nunca contestada» pasaría todos los casos negativos.
- **El `loc` con tag no se usa para enfocar**: un test comprueba que el salto sigue llegando al campo
  real de una rama discriminada.
- **Sin veredicto, el estado no cambia** (D-RES-4), con su control negativo.
- **Ninguna llamada nueva a la red**: gate estático sobre el fuente, igual que el guardrail de
  `ConfigTab`.
- Suite, mypy, ruff, vitest, typecheck, bundle y fixture sin drift, `mkdocs --strict`.
- **Verificación en vivo con Playwright**: vitest corre sin DOM y no puede probar lo que se ve.

## 5. Lo que esta enmienda NO resuelve, dicho y no escondido

1. **Los 3 casos con `loc = []`** (D-RES-5), y el modo relacional `duration_col == event_col`.
2. **No mejora los mensajes**: el usuario verá que la decisión sigue pendiente, con el error del
   motor donde ya aparece. Redactar un copy propio por familia de error es trabajo aparte.
3. **No cubre lo que el motor acepta y falla al ejecutar.** `oot_from` no parseable valida y muere en
   la corrida; eso es alcance de `requisitos_incumplidos` (D-INV), no de aquí.
4. **No toca el criterio de presencia** con que se decide si la decisión fue siquiera empezada: un
   `0`, un `false` o un `""` siguen siendo respuestas del usuario (D-FX-7).

## 6. D-RES-7 — «no acepta lo que dice» no es «te falta un dato» (2026-08-03, tarde)

> Enmienda a la propia §2 de este documento, tras la reproducción de la revisión adversarial
> cruzada. **Aprobada e implementada.**

**El defecto.** Este documento fundió el rechazo del motor con el estado `inProgress`, que ya
existía para «elegiste una forma y le faltan huecos». El punto 2 de la §5 de arriba lo daba por
inocuo —*«el usuario verá que la decisión sigue pendiente, con el error del motor donde ya
aparece»*— y **las dos mitades de esa frase eran falsas**:

1. El copy de `inProgress` dice literalmente *«Elegiste cómo contestarla; abajo te faltan los datos
   de tu cartera»*. Con fracciones de partición `0.9/0.9/0.9` **no falta ningún dato**: los tres
   están escritos y son inconsistentes entre sí. El mensaje manda a buscar un vacío que no existe.
2. **El error del motor NO «aparece donde ya aparecía».** `errorAtPath` casa por igualdad exacta, y
   el `loc` de ese caso es `data.partition.strategy.random` —con el tag del discriminador que la §3
   de este mismo documento declara inexistente en el config—, así que **ningún control lo pinta**.
   La tarjeta mandaba «abajo» a una pantalla sin una sola marca roja.

**D-RES-7.** El estado de una decisión tiene **tres** valores excluyentes además de «sin empezar»:
contestada, con huecos (`inProgress`) y **rechazada** (`rejected`). El hueco **gana** al veredicto:
es más específico, más accionable y casi siempre la causa del rechazo — decir «revisa lo que
escribiste» sobre una plantilla recién elegida sería la mentira simétrica.

Y `rejected` **transporta el motivo tal como lo dio el motor**, que se cita sin reescribir: una
segunda redacción del mismo mensaje en el front es como las dos se separan en silencio. Medido, el
motivo es útil y ya viene en español —*«dev+holdout+oot debe sumar 1.0; suma observada = 2.1300»*—
porque la traducción por `type` de Pydantic ya estaba resuelta.

**Gate.** Los cinco casos de la tabla escrita a mano **no** pueden decir `inProgress` (el ancla
anti-vacua ya demuestra que a ninguno le falta un hueco: sin veredicto salían «Respondida»), más un
caso nuevo con hueco **y** rechazo que comprueba la prioridad, más un guardrail de fuente sobre
`ConfigTab`. Control negativo ejecutado: refundir los dos estados pone dos tests en rojo.
