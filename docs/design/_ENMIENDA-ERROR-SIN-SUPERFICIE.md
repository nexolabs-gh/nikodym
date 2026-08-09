# Enmienda — un error de validación no puede quedarse SIN SUPERFICIE

> Estado canónico: **APROBADA; D-VIS-1…5/7 IMPLEMENTADAS; COMPLETITUD D-VIS-6 ABIERTA**. Las 98
> anclas existentes fueron revisadas y son correctas, pero un censo nuevo probó que la migración no
> fue exhaustiva y que el gate omite los `raise` sin `loc`. Detalle y evidencia en
> [`DECISIONES-VIGENTES.md`](DECISIONES-VIGENTES.md), §D-VIS, y en el `HANDOFF` actual.
>
> La cifra de 133 que sigue en el cuerpo pertenece al alcance propuesto el 2026-08-08; no es el
> censo vigente ni prueba cierre.
> Nace de verificar en pantalla la deuda 4 del HANDOFF («el front no salta al `loc` todavía»).
> Decisiones `D-VIS-1…D-VIS-7`.
>
> ⚠️ **D-VIS-7 se añadió DESPUÉS del OK, y hay que decirlo.** Cami aprobó D-VIS-1…6; al medir el
> alcance apareció el flanco del **tag del discriminador** (§1.2), que D-VIS-2 **no cubre** y que deja
> **falsa la invariante D-VIS-1**, que sí está aprobada. D-VIS-7 es lo que hace cierta esa invariante,
> no alcance nuevo: sin ella la enmienda no entrega lo que promete. Se implementa y se declara.
>
> ⚠️ **Y dos afirmaciones del borrador las refutó la medición** (§1.2): ni el `loc` en un ancestro ni
> el `loc` con índice de lista son flancos — los dos se pintan hoy. Quedan escritas como refutadas
> para que nadie las «arregle».
>
> Enmienda a **D-ANC-12** (`_ENMIENDA-ANCLA-DESCARTADA.md`) y a **D-EXI-5**
> (`_ENMIENDA-OPCION-QUE-EXIGE-OTRO-CAMPO.md`). No toca backend, no toca contrato REST, no mueve
> ningún `config_hash`. Es enteramente de la capa de interfaz.

## 0. La deuda estaba mal planteada, otra vez, y medirla cambió el trabajo

El HANDOFF decía: *«`_error_de_dominio` sólo publica el `loc`; el front no salta a él todavía. El
mensaje ya llega anclado por el contrato REST, pero comprobar el salto en pantalla para este caso
quedó sin hacer»*. Se leía como una verificación pendiente de media hora.

Verificado en pantalla (UI local por `127.0.0.1`, trabajo «Provisión interna / LGD»), sus tres
afirmaciones se reparten así:

| afirmación del HANDOFF | veredicto | evidencia medida |
|---|---|---|
| el mensaje llega anclado por el contrato REST | **CIERTA** | `/api/validate` devuelve `loc: ["provisioning_internal","lgd","covariate_cols"]` |
| el mensaje se pinta en el campo | **CIERTA, y se verificó** | el `<p class="text-xs text-destructive">` cuelga del mismo contenedor que el control, 19 px bajo él |
| «el front no salta a él todavía» | **CIERTA pero MENOR** | no existe ningún consumidor de `setFocusField` alimentado por la validación |
| *(no dicha)* migrar los 121 restantes es seguro | 🔴 **FALSA** | migrar **pierde** la visibilidad global del mensaje: ver §1 |

🔴 **Lo que la deuda no decía es lo que importa: anclar un error lo hace INVISIBLE fuera de su
sección.** No es que falte un salto; es que el mensaje deja de existir para el usuario.

## 1. El defecto, medido con su control

Mismo trabajo, mismo gesto de navegar a otra sección. La única diferencia entre los dos casos es si
el `raise` declara `loc`:

| error | `loc` | en su propia sección | en otra sección |
|---|---|---|---|
| `portfolio_col` vacío — **sin migrar** | `[]` | mensaje en la barra | **mensaje visible** ✅ |
| `covariate_cols` — **migrado por D-EXI-5** | `["provisioning_internal","lgd","covariate_cols"]` | anclado al campo ✅ | 🔴 **mensaje INVISIBLE** |

En el segundo caso, estando en «Esquema y target», la pantalla entera contiene exactamente un texto
en rojo: `Config inválido · 1 error`. Medido: el campo no está montado (`getElementById` → `null`),
el mensaje no aparece en `document.body.innerText`, y **el sidebar no marca la sección** que lo
contiene (ninguno de sus 7 ítems lleva marca ni icono de alerta). El usuario sabe que hay un error y
no tiene forma de saber cuál ni dónde.

La causa es de una línea y está escrita: `unanchoredError` recupera `lookup.get("")`
(`web/src/lib/validation.ts:61`), o sea **sólo** la clave vacía. Un `loc` no vacío deja de caer ahí y
pasa a depender por completo de que exista un `FieldRenderer` montado cuyo `path.join(".")` sea
idéntico (`errorAtPath`, `validation.ts:44`, un `Map.get` sin prefijo ni degradación).

### 1.1 La clase es PREEXISTENTE y mayor que D-EXI-5

D-EXI-5 no creó el agujero: **metió dentro los errores de dominio, que hasta ayer estaban a salvo por
accidente** (su `loc: []` los mandaba a la barra). Los errores de **Pydantic** siempre trajeron `loc`
no vacío y siempre sufrieron esto. Medido con el config `{binning: {max_n_bins: -3}, model: {c: -1},
performance: {partitions: []}}`:

```
loc= ['binning', 'max_n_bins']      | greater_than_equal | Tiene que ser mayor o igual que 2.
loc= ['model', 'c']                 | extra_forbidden    | Este campo no existe en la configuración.
loc= ['performance', 'partitions']  | too_short          | Faltan elementos en la lista.
```

Tres errores simultáneos en tres secciones. Mirando `binning`, **dos de los tres son invisibles**.

### 1.2 Y hay un segundo modo de fallo, también preexistente: el TAG del discriminador

Un `loc` puede no casar con ningún control **aunque estés en su sección**. Se midieron los tres
candidatos y **sólo uno resultó real**:

| candidato | veredicto | evidencia |
|---|---|---|
| **El tag del discriminador** | 🔴 **REAL** | el motor devuelve `data.partition.strategy.cohort.holdout_fraction`; el DOM monta `data.partition.strategy.holdout_fraction`. Verificado en las tres capas: API, DOM y `errorAtPath` |
| Un `loc` que nombra un **ancestro** objeto | **NO es flanco** | `GroupField` (`:598`) y `FieldShell` (`:249`) pintan el error de **su propio** path. `data.partition` y `data.partition.strategy` se pintan; el `id` existe, verificado en el DOM |
| Un `loc` con **índice de lista** | **NO es flanco** | `filaPath = [...path, indice]` (`FieldRenderer.tsx:1190`) ⇒ el id es `data.schema.columns.3.name`, idéntico a `pathKey(loc)`. Verificado: `getElementById` → `true` |

⚠️ **Los dos últimos los daba por rotos el borrador de esta enmienda y la medición los refutó.** Se
deja escrito para que nadie los «arregle».

La causa del que sí es real está en el render: `DiscriminatedField` (`FieldRenderer.tsx:709`) pasa
`path={path}` a `GroupFieldList` **sin insertar el tag**, mientras Pydantic sí lo inserta. Alcance
medido sobre el schema compuesto: **3 uniones discriminadas, 12 ramas, 58 hojas** —
`data.partition.strategy` (18), `provisioning_internal.lgd` (29), `tuning.search_space.params.*`
(11)—, o sea **8,3 % del config**.

🔴 **D-VIS-2 no lo cubre**, y hay que decirlo: su `loc[0]` **es** la sección activa, así que el
criterio por sección lo da por anclado y no lo lista, mientras `errorAtPath` no lo casa. Sin cerrarlo,
la invariante D-VIS-1 es falsa. Lo cierra **D-VIS-7**.

### 1.4 Cuántos `raise` y dónde — el alcance real de la deuda 1

Censo AST de hoy (cierre transitivo de subclases de `NikodymError`, dentro de funciones decoradas con
`field_validator`/`model_validator`, en `src/nikodym/**/config.py` + `tuning/search_space.py`):

| | n |
|---|---|
| `raise` migrables | **135** en 18 secciones (2 ya migrados ⇒ **133 restantes**) |
| … en las 14 secciones que el formulario pinta | 77 |
| … en las **8 secciones sin pestaña** | **58 (43 %)** — `forward` 19, `markov` 11, `tuning` 10, `stress` 7, `ml` 6, `validation` 4, `explain` 1 |

⚠️ **La cifra escrita en el repo estaba corta.** `validation.ts:57`, `_ENMIENDA-ANCLA-DESCARTADA.md`
y el HANDOFF dicen «123»; hoy son **135**. Se corrige donde se cite.

🔴 **Y esto es lo que hace a esta enmienda prerequisito, no complemento**: para 58 de los 133, migrar
sin D-VIS-3 los saca de la barra —donde hoy **sí** se leen— y los manda a un campo que no existe en
ninguna pestaña. De las 700 hojas del config, **267 (38 %) viven en esas 8 secciones**.

### 1.3 Cuántos errores conviven — calibra el ruido de la salida

Medido: **un error de dominio siempre viene solo.** `ConfigError` no hereda de `ValueError`, así que
Pydantic no lo acumula: aborta la validación entera y sale uno. Con `{provisioning_internal roto +
calibration roto}` la respuesta trae **1** error, no 2. Los de Pydantic sí se acumulan (3 en el
ejemplo de §1.1).

⇒ Listar los errores no anclados en la barra **no puede producir una lista larga** en el caso de
dominio, y en el de Pydantic la lista es exactamente lo que hoy falta.

## 2. El precedente: el preflight ya resolvió esta clase

No hace falta mecanismo nuevo. `web/src/lib/preflight.ts` ya trae, con su razón escrita:

- `sectionOfPath(path)` (`:78`) — la sección a la que pertenece un path.
- `sectionIsEditable(section)` (`:92`) — si el formulario ofrece esa pestaña. Su docstring ya dice lo
  que aquí hace falta: *«hoy el motor trae 22 secciones de dominio y `CONFIG_SECTIONS` ofrece 14, así
  que un desajuste puede caer en una sección sin pestaña a la que saltar. **Ofrecer un salto a una
  pestaña que no existe sería peor que no ofrecerlo: el aviso lo dice en vez de fingir.**»*
- `jumpToField(path)` (`App.tsx:309`) — navega a la sección **y** pide el foco.

Hoy `jumpToField` se pasa a **un solo consumidor**, `DatosTab`. Los errores de validación no lo usan.

## 3. Las decisiones

### D-VIS-1 — Un error de validación SIEMPRE tiene superficie

Invariante: para todo error que devuelva `/api/validate`, existe al menos un sitio de la pantalla
actual donde el usuario lee su mensaje, **sea cual sea la sección abierta**. Anclarlo a un campo es
una mejora *encima* de eso, nunca un sustituto.

Es la generalización de D-ANC-12, cuyo criterio («el usuario no puede quedarse con un contador y nada
que corregir») era correcto y su implementación cubría un solo caso: `loc: []`.

### D-VIS-2 — `unanchoredError` pasa de «sin `loc`» a «sin superficie en esta vista»

Se sustituye por una función pura `erroresSinSuperficie(state, seccionActiva)` que devuelve la lista
de errores no anclados aquí, cada uno con `{ loc, msg, seccion, alcanzable }`. El criterio de «no
anclado aquí» es **por sección**: `loc` vacío, o `loc[0] !== seccionActiva`.

⚠️ **Se elige el criterio por sección, y no medir el DOM, a propósito.** Un criterio que pregunte al
DOM qué claves reclamó alguien cubriría también §1.2, pero exige un efecto que corra tras cada render
y deja el resultado dependiendo del orden de montaje. El criterio por sección es **puro** —testeable
con vitest, que corre sin DOM— y determinista. Lo que §1.2 deja fuera lo cubre D-VIS-4.

### D-VIS-3 — Lo no anclado se lista bajo el contador, con su sección y su salto

`HashStatus` deja de pintar un único texto suelto y pinta la lista. Cada entrada: el mensaje del
motor **tal cual** (el front no lo reescribe, SDD-23 §3.3), el nombre legible de su sección, y un
botón «Ir al campo» que llama `jumpToField(pathKey(loc))`.

Si `sectionIsEditable(seccion)` es falso —las 8 secciones de dominio que el formulario no ofrece— se
pinta el mensaje **sin botón**, nombrando la sección. Es literalmente el criterio que `preflight.ts`
ya declara: decirlo en vez de fingir un salto a una pestaña que no existe.

⇒ Para que `ConfigTab` pueda ofrecer el salto, `App.tsx` le pasa `onJumpToField={jumpToField}`, el
mismo prop que ya le pasa a `DatosTab`. Ningún efecto nuevo en `ConfigTab` (gate de
`bootstrap.test.ts`, que protege la regresión UX1).

### D-VIS-4 — El sidebar marca la sección que tiene errores

Una sección con al menos un error lleva marca en el sidebar. Cubre el caso de §1.2 que D-VIS-2 no ve
—un `loc` de la sección activa que no casa con ningún control— porque al menos orienta: el usuario
sabe **dónde** mirar aunque el mensaje no encuentre su campo.

Coste de ruido: cero. Es la información que hoy existe (el contador ya sabe que hay N errores) sin
publicar dónde.

### D-VIS-5 — El gate mide la INVARIANTE, no la implementación

Un test de vitest sobre `erroresSinSuperficie` con **oráculo escrito a mano** (nunca derivado de la
misma función): para un conjunto de errores y una sección activa, la unión de {los anclados en la
sección activa} ∪ {los devueltos por `erroresSinSuperficie`} tiene que ser **todos** los errores.
Ningún error puede quedar fuera de las dos listas.

⚠️ Se prueba **inyectando el defecto**: con el criterio viejo (`lookup.get("")`) el test se pone rojo
sobre un `loc` no vacío de otra sección. Un gate que no falla con el código de ayer no prueba nada.

### D-VIS-6 — Migrar los 133 `raise` deja de ser un intercambio

Con D-VIS-1…4 puestas, declarar un `loc` sólo **añade** (el anclaje al campo) y ya no **quita** (la
visibilidad en la barra). Esta enmienda es, por tanto, **prerequisito de la deuda 1**: migrarlos
antes empeora la interfaz en **58 de los 133** sitios (§1.4).

#### Lo que la migración destapó: la CUARTA reincidencia del contrato «siempre 200»

Migrar los 133 sacó a la luz un defecto **preexistente y grave**, ajeno a esta enmienda:
`POST /api/validate` devolvía **HTTP 500** sobre configs alcanzables desde el formulario. Bastan
**dos escenarios de stress con el mismo nombre**; reproducido.

Causa: el endpoint atrapaba `ConfigError`, y hay **18 `raise` en 6 clases** dentro de los `config.py`
que cuelgan **directas de `NikodymError`** — las siete de `ForwardScenarioError`, las siete de
`StressScenarioError`, más `PitConsistencyError`, `SatelliteModelError`, `StressDependencyError` y
`StressFaltaDatoError`.

🔴 **Es la cuarta vez que este contrato se rompe, y las tres anteriores se parchearon como caso.** Lo
peor: **el repo ya había medido exactamente estas clases** en D-ANC-10 —*«`ConfigError` NO basta:
cuatro clases de `stress`/`forward` cuelgan directas de `NikodymError`»*— y amplió la captura de
`_coaccionar_secciones_opacas`. **El endpoint se quedó atrás**: la misma clase, cerrada en un sitio y
no en el otro.

⚠️ **Se amplía la CAPTURA (`except NikodymError`), no la jerarquía.** Hacer que esas 6 clases hereden
de `ConfigError` tocaría **109 `raise` de runtime** y convertiría un fallo de cálculo en un error de
config. En ese punto del endpoint no hay cálculo: lo único que corrió es `model_validate`, así que
todo `NikodymError` que salga de ahí es, por definición, «este config no reconstruye».

Y se cierra como **clase**: un gate barre **todo `config.py`** —no sólo los validadores, porque el
`raise` que reprodujo el 500 vive en un auxiliar llamado *desde* uno— y exige que lo que se levanta
al validar sea atrapable. Con su control positivo por la puerta pública.

### D-VIS-7 — El `loc` se NORMALIZA a la convención del formulario antes de indexarlo

El segmento del **tag** que Pydantic inserta en una unión discriminada se elide antes de construir la
clave del lookup: `data.partition.strategy.cohort.holdout_fraction` →
`data.partition.strategy.holdout_fraction`, que es el `id` que el formulario monta.

**No se elide por nombre.** Se elide sólo si, bajando por el JSON Schema, el segmento coincide con un
tag **declarado de la unión en esa posición exacta**. Un campo que se llamara como un tag en otra
posición no se toca.

🔴 **Y se recorren TODAS las ramas de la unión, no la primera.** Es el patrón que esta sesión pagó
tres veces («inspecciona la primera rama»); aquí se declara por escrito para que el gate lo mida.

⚠️ **Se normaliza el `loc`, NUNCA el `path` del formulario.** Insertar el tag en los `id` del render
sería el arreglo simétrico y es el equivocado: movería los `id` de 58 controles, rompiendo el salto
del preflight, `candidateFieldIds` y los guardrails estáticos de `form-engine.test.ts`. La
traducción de convenciones es lo que el preflight ya hace con `fieldIdForPath` (corchetes → puntos).

Efecto medido esperado: **58 hojas** que hoy no casan con ningún control pasan a anclarse, en las tres
uniones. Es, de las siete decisiones, la única que además **mejora** el anclaje en vez de sólo
publicar lo no anclado.

## 4. Lo que esta enmienda NO hace

- **No toca el backend.** El contrato de `/api/validate` no cambia; `_error_de_dominio` se queda como
  está.
- **No adivina el `loc`** de un mensaje que no lo declara. Lo prohíbe el comentario de
  `_error_de_dominio` y sigue vigente.
- **No cambia `errorAtPath`.** El anclaje exacto se conserva: es correcto y está verificado en
  pantalla. Lo que se añade es la red de seguridad de debajo.
- **No mueve ningún `config_hash`**, ni fixtures del motor, ni el schema. Toca `web/` y el bundle.
