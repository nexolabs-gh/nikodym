# Enmienda SDD — lo que sólo tú puedes decidir, se pregunta; no se inventa

> **Estado: APROBADA como contrato (Cami, 2026-08-01).** La aprobación fijó además la superficie de
> D-OBL-8, que era la única decisión de producto abierta: las decisiones se muestran **primero en la
> pestaña Configuración**, no como paso propio del stepper ni como aviso del preflight.
>
> **Base:** `main` = `f848141`. **Autor / Fecha:** DanIA / 2026-08-01.

| Campo | Valor |
|---|---|
| **Problema** | Activar una sección escribe un submodelo obligatorio con valores inventados que el motor rechaza, y la interfaz no pide en ninguna parte las decisiones que sólo el usuario puede tomar |
| **Enmienda a** | `_ENMIENDA-DEFAULTS-EFECTIVOS-UI.md` D-FX-5 (forma del catálogo) y D-FX-8 (proyección canónica); `_SDD-UI-POR-TRABAJOS.md` D-JOB-3 (qué declara un trabajo) y D-JOB-4 (el abanico al principio) |
| **No toca** | El `config_hash`, el motor, los presets, `CONFIG_SECTIONS`, la puerta de artefactos, ni el criterio de qué secciones muestra un trabajo (D-JOB-1) |
| **Release** | Cambio observable de producto; exige CHANGELOG. Esta enmienda no autoriza bump, tag ni publicación |

## 1. Evidencia medida

Todo lo de esta sección se ejecutó contra `f848141`, no se dedujo leyendo.

### 1.1 El defecto, y la causa que la nota heredada atribuía mal

`CLAUDE.md` y el §9 del SDD de trabajos registran el bloqueante así: «`Rule` y `TargetConfig` **no
son construibles**, así que el catálogo las representa como un mapa de hijos en vez de un descriptor
`has_default: false`». **La segunda mitad de esa frase es falsa**, y medirlo cambia el arreglo.

La construibilidad **no interviene** en la decisión mapa-vs-descriptor. Esa decisión la toma
`effective_defaults.py:245-253` mirando **sólo la anotación**:

```python
submodelo = _submodelo_directo(campo.annotation)
if submodelo is None or _submodelo_apagable(campo):
    salida[clave] = _descriptor(campo, volcado, clave)   # única vía que emite has_default
elif submodelo.__name__ in pila:
    salida[clave] = {}
else:
    salida[clave] = _mapa_de_modelo(submodelo, (*pila, submodelo.__name__))
```

`campo.is_required()` **no se consulta nunca** en esa bifurcación. Contraejemplo directo:
`DataConfig.load → LoadingConfig` **sí** es construible y aun así se publica como mapa de hijos; y
`MarkovConfig.input` **no** es construible y **no** es obligatorio, y también sale como mapa. Que hoy
«obligatorio» y «no construible» coincidan es un accidente del config actual, no el mecanismo.

Barrido de las 22 secciones registradas, campos cuyo nodo es mapa de hijos:

| requerido | construible | nº campos |
|---|---|---:|
| sí | sí | **0** |
| sí | no | **8** |
| no | sí | **63** |
| no | no | **2** |

Dónde sí importa la construibilidad: sólo en el **valor de las hojas**
(`_volcado_canonico`, `:135-154`). Para `Rule` devuelve `None` y las hojas caen a `FieldInfo`, de ahí
`all_of: []` / `any_of: []`. Pero **aunque `Rule` fuese construible, `bad_rule` seguiría siendo un
mapa de hijos** y la proyección seguiría escribiéndolo.

⚠️ Y no es un descuido de código: es el contrato escrito. `effective_defaults.py:41-42` declara que
«un campo cuyo tipo es un submodelo no lleva descriptor: lleva el mapa de sus hijos». Por eso esto es
enmienda y no corrección.

### 1.2 El alcance real: no es `data`, es una clase

Proyección canónica aplicada sección a sección y pasada por `validate_config` (el mismo que sirve
`POST /api/validate`):

| sección | veredicto |
|---|---|
| `data` | **INVÁLIDO**: `data.target.bad_rule` → «una Rule debe declarar al menos un predicado…»; `data.partition.strategy` → obligatorio |
| `survival` | **INVÁLIDO**: `survival.input.duration_col`, `survival.input.event_col` → obligatorios |
| las otras 12 del formulario | válido |

Fuera del formulario fallan además `forward` (mismo mecanismo, dos niveles), `markov` y `stress`.

**Y el defecto no está sólo en el interruptor de sección.** Los mismos cuatro gestos de estructura
llaman a `canonicalProjection`: activar sección, activar submodelo apagable, cambiar variante de
unión y **añadir fila de lista**. Medido: añadir una fila a `data.target.exclusion_rules` nace con
`{"rule": {"all_of": [], "any_of": []}}`, o sea inválida el día uno. Dos entradas de `$defs`
proyectan un objeto ya inválido: `data__TargetConfig` y `data__ExclusionRule`.

**Los 10 trabajos nacen con config inválido**, no sólo quien activa `data` a mano:

```
scorecard_pd  provisiones_cmf  provision_interna  pd_y_lgd
comparar_provisiones  validar_modelo  lgd_modelada  stress_testing   → 2 errores
pd_lifetime  provisiones_ifrs9                                        → 4 errores
```

### 1.3 🔴 El hallazgo que cambia el trabajo: arreglar el catálogo NO deja el config válido

Contra-medición del arreglo, antes de escribirlo:

| sección | hoy | con el arreglo |
|---|---|---|
| `data` | `bad_rule` → «una Rule debe declarar al menos un predicado» · `partition.strategy` → obligatorio | `data.target` → obligatorio · `data.partition` → obligatorio |
| `survival` | `input.duration_col`, `input.event_col` → obligatorios | `survival.input` → obligatorio |

**Sigue inválido, y es correcto que lo siga.** `DataConfig` exige dos decisiones que el motor no
puede tomar por nadie:

- **`bad_rule`** — qué es un cliente *malo* en esta cartera. «Más de 90 días de mora» es una
  definición institucional, no un default.
- **`partition.strategy`** — aleatoria, temporal o por cohortes. Es metodología, y la respuesta
  correcta depende de si el panel tiene eje de tiempo.

Lo que cambia el arreglo es la **calidad del hueco**: de un valor inventado que el usuario nunca
eligió y que el motor rechaza con jerga interna, a un hueco honesto que dice qué falta. Es
exactamente la taxonomía del repo: son **DATO-INSTITUCIONAL**, y el motor se niega a inventarlos.

Por eso esta enmienda tiene **dos partes**. La primera sola dejaría el gate de aceptación de P1
—«cada trabajo disponible llega a `done` desde su landing»— dependiendo de que el usuario adivine
qué le falta.

### 1.4 Lo que abarata la segunda parte

Censo de decisiones obligatorias derivadas de `model_fields` en las 14 secciones del formulario:

| sección | decisiones |
|---|---|
| `data` | `target.bad_rule`, `partition.strategy` |
| `survival` | `input.duration_col`, `input.event_col` |
| las otras 12 | **ninguna** |

**Son cuatro en total.** Por trabajo: 2 en ocho trabajos, 4 en los dos que llevan survival. La capa
de negocio no es «adelantar D-JOB-4/5»: son cuatro preguntas con su copy y un gate que impide que se
desincronicen del schema.

## 2. Decisiones

### Parte A — el catálogo dice qué es obligatorio

**D-OBL-1 — Un submodelo obligatorio sin default se publica como DESCRIPTOR, no como mapa desnudo.**
El criterio es `campo.is_required()`, y no la construibilidad de su clase. La pregunta que la
proyección necesita responder es «¿puedo omitir este campo?», y eso lo contesta la obligatoriedad; de
dónde sale el valor de sus hojas es otra pregunta, y la sigue contestando `_volcado_canonico`.

**D-OBL-2 — La forma es un descriptor que conserva sus hijos: `{"has_default": false, "children": {…}}`.**
Se extiende `DESCRIPTOR_KEYS` con `children`. Tres razones medidas:

1. `isDescriptor` discrimina por `typeof node.has_default === "boolean"`, así que el nodo nuevo entra
   por la rama de descriptor **sin tocar esa función**.
2. `canonicalProjection` ya hace lo correcto en esa rama: `has_default: false` ⇒ no escribe. **La
   función no cambia ni una línea**; lo que cambia es el nodo que le llega.
3. `children` conserva el descenso del formulario y los defaults de los hijos. Publicar el
   descriptor *sin* hijos perdería que `target.target_col` vale `"target"` y que
   `target.exclusion_rules` vale `[]`, degradando D-FX-5.

Único cambio en el consumidor: `childMap` devuelve `node.children` cuando el descriptor los trae, en
vez de `undefined`.

**D-OBL-3 — `resolveValue` mantiene su contrato: el nodo nuevo resuelve `missing`.** `has_default:
false` ⇒ no hay valor que pintar para el objeto entero, que es lo cierto. Los hijos se resuelven cada
uno por su cuenta bajando por `children`.

**D-OBL-4 — `markov` y `stress` quedan FUERA, con su razón medida.** No es falta de tiempo:

- **`markov.input`** es un campo **no obligatorio** cuya clase no es construible. Como no es
  obligatorio, D-OBL-1 no lo alcanza — y no debe alcanzarlo: el campo *tiene* default, así que el
  catálogo ya dice la verdad sobre él. Que su proyección no valide es un defecto distinto, de la
  familia «el default de un campo opcional no es instanciable», y exige su propia medición.
- **`stress`** falla en el `model_validator` de su clase **raíz** («stress exige al menos un
  escenario, una sensibilidad o un reverse stress»). Ninguna proyección lo satisface, ni siquiera
  `{}`. No lo arregla ningún cambio del descriptor.

Declararlos aquí evita que la lista corta se lea como cobertura total, que es el error que D-INV-8 ya
documentó.

**D-OBL-5 — Activar una sección deja el config INCOMPLETO Y HONESTO, no válido, y eso es el contrato.**
No se siembra un `bad_rule` plausible ni una `partition.strategy` por defecto. Sembrarlos sería que
el motor invente criterio institucional, que es justo lo que la marca `DATO-INSTITUCIONAL` existe
para impedir.

### Parte B — el trabajo pregunta lo que sólo tú puedes decidir

**D-OBL-6 — Un trabajo declara sus DECISIONES OBLIGATORIAS, en idioma de negocio.** El catálogo de
`ui/jobs.py` gana por trabajo una lista de `{path, question, help}`: el path del config, la pregunta
como la haría un jefe de riesgo, y una ayuda de una línea. Ejemplo:

| path | pregunta | ayuda |
|---|---|---|
| `data.target.bad_rule` | ¿Qué define a un cliente malo en tu cartera? | La condición con la que tu área marca el incumplimiento; por ejemplo, más de 90 días de mora. |
| `data.partition.strategy` | ¿Cómo separas la muestra para validar? | Al azar, por fecha o por cohortes. Si tu panel tiene eje de tiempo, separar por fecha mide mejor. |

**D-OBL-7 — Los paths se DERIVAN del schema; sólo el copy se escribe a mano.** Un gate bidireccional
exige que toda decisión obligatoria derivada de `model_fields` para las secciones de un trabajo tenga
su pregunta declarada, **y** que toda pregunta declarada corresponda a una decisión que de verdad lo
sea. Sin eso, añadir un campo obligatorio al motor dejaría en silencio un trabajo que no se puede
completar — el modo de fallo exacto que el gate bidireccional del catálogo ya evita para las
secciones.

**D-OBL-8 — Las decisiones se piden ANTES que los parámetros de detalle, y su sitio es el principio
de la pestaña Configuración** (D-JOB-4, acotado a lo obligatorio; superficie fijada por Cami el
2026-08-01). Al entrar a un trabajo, lo primero de Configuración son sus 2–4 decisiones y debajo
quedan las secciones de siempre. No es un asistente modal ni bloquea la navegación: se puede
responder ahí o en la sección correspondiente, que es donde ya viven los controles.

*Por qué no un paso propio del stepper:* añadiría un paso al recorrido de todos —incluido quien
carga un ejemplo y no tiene ninguna decisión pendiente— y obligaría a inventar qué hace ese paso
cuando ya están respondidas. *Por qué no el aviso del preflight:* ahí quedarían enterradas entre los
desajustes de columnas y se leerían como error, cuando son lo contrario — el motor preguntando lo
que sólo la institución puede contestar.

**D-OBL-9 — Una decisión sin responder se declara con su nombre de negocio, nunca con el path.** El
usuario lee «Falta definir qué es un cliente malo en tu cartera», no `data.target.bad_rule`. El path
es la coordenada interna; el copy público va en el idioma del lector, como exige la regla de copy del
repo.

**D-OBL-11 — El esqueleto de un trabajo exige del informe sólo los capítulos que ese trabajo
produce.** Añadida el 2026-08-01 al verificar el gate de aceptación: **ningún trabajo llegaba a
`done`**, y no se veía en la suite. El default del motor son ocho capítulos obligatorios, entre ellos
`eda`; un scorecard declara nueve secciones y `eda` no está entre ellas —el formulario ni siquiera la
ofrece—, así que el informe exigía una card que la corrida no iba a producir y el paso `report` moría
con `missing_policy: error`. El preset F1 no lo sufre porque declara sus siete capítulos a mano.

Al sembrar, `required_sections` se recorta a la intersección con las secciones del trabajo. El
criterio no es nuevo: es el de **D-FX-3** —el informe exige sólo lo de los dominios activos de la
invocación— aplicado al sitio que faltaba, la siembra. **No se toca el default del motor**, que sigue
siendo correcto para quien corre el pipeline completo por código.

⚠️ Se recorta, **nunca se añade**: meter un capítulo que el default no pedía sería la mentira
simétrica, exigir del informe algo que el usuario no eligió.

**D-OBL-10 — Esto no toca `config_hash` ni el catálogo de secciones.** Las decisiones son
navegación y copy, igual que el trabajo (D-JOB-9). Responder una decisión escribe el mismo path que
escribiría el control de su sección, así que dos usuarios que llegan al mismo config por caminos
distintos siguen produciendo la misma identidad. Lo verifica un gate.

## 3. Alternativas rechazadas

1. **Sembrar un `bad_rule` y una `partition.strategy` por defecto.** Cierra el gate barato e inventa
   criterio institucional. Contradice `DATO-INSTITUCIONAL` y publicaría un modelo cuyo target lo
   eligió la herramienta.
2. **Publicar el descriptor obligatorio SIN sus hijos.** Más simple, pero pierde los defaults de los
   hijos y degrada D-FX-5; el formulario dejaría de pintar `target_col = "target"`.
3. **Marcar la obligatoriedad con una clave nueva junto a los hijos (`{"required": true, …hijos}`).**
   Colisiona con cualquier campo que se llame `required`, y obliga a tocar `isDescriptor`,
   `childMap`, `resolveValue` y `nodeAtPath` en vez de sólo uno.
4. **Usar «clase no construible» como criterio.** Cubre `markov` pero es la pregunta equivocada:
   deja fuera los construibles-obligatorios (hoy 0, mañana cualquiera) y mete dentro los
   opcionales-no-construibles, que sí tienen default legítimo.
5. **Arreglar sólo `data`.** `survival` tiene el defecto idéntico y afecta a dos trabajos; parchear
   uno dejaría la clase viva, que es lo que este repo ya pagó tres releases seguidos.
6. **Escribir las decisiones obligatorias a mano sin derivarlas.** Se desincronizan del motor en
   silencio en cuanto alguien añada un campo obligatorio.
7. **Un asistente modal que bloquee hasta responder.** Convierte el primer uso en un formulario
   obligatorio y choca con el contrato UX1 («entrar al workspace basta para poder trabajar»).

## 4. Gates de aceptación

**Parte A**

- Activar `data` y activar `survival` desde una sesión vacía dejan un config cuyo error es
  «este campo es obligatorio» sobre el submodelo, y **ningún** valor inventado. Verificado contra
  `validate_config`, en la pantalla y no sólo en la suite.
- Añadir una fila a `data.target.exclusion_rules` ya no nace con una `Rule` vacía.
- Los cuatro gestos de estructura (activar sección, activar submodelo, cambiar variante, añadir fila)
  producen la misma proyección por el mismo camino.
- `isDescriptor`, `resolveValue` y `nodeAtPath` conservan su comportamiento para los nodos que ya
  existían; el caso adversarial `{has_default: <descriptor>}` sigue sin ser descriptor.
- `childMap` devuelve los hijos de un descriptor que los trae, y `undefined` para una hoja.
- Los goldens del catálogo (394 hojas, 1024 descriptores) se recalculan **en el mismo commit**, y el
  gate de paridad sigue exigiendo `has_default is not is_required`.
- 🔴 `test_effective_defaults.py:191` asevera hoy `"has_default" not in objetivo["bad_rule"]`, o sea
  **codifica el defecto**. Se reescribe para exigir lo contrario, con su razón.
- Control negativo: revertir D-OBL-1 pone rojo el gate nuevo.
- `markov` y `stress` siguen fallando, **declarado en el test** para que su exclusión no se lea como
  olvido.

**Parte B**

- Cada trabajo declara exactamente las decisiones obligatorias que su schema impone, en las dos
  direcciones. Control negativo: añadir un campo obligatorio a una sección sin declarar su pregunta
  pone el gate rojo.
- Ninguna pregunta nombra un path, una clase ni un literal de enum interno; lo vigila el gate de copy
  público vigente.
- Responder las decisiones de un trabajo desde la interfaz deja su config **válido**, y de ahí a
  `done` con informe **sin editar YAML** — que es el gate de aceptación de P1.
- El `config_hash` de un config completado por las decisiones es idéntico al del mismo config
  completado campo a campo desde las secciones.

**Comunes**

- Fixture `web/src/fixtures/schema.json` y `web/src/fixtures/jobs.json` regenerados, y bundle
  reconstruido, **en el mismo commit** que el cambio de payload.
- Suite completa, mypy, ruff check y format, vitest, typecheck, build reproducible, mkdocs strict.
- Verificación **en vivo con Playwright**: vitest corre sin DOM y no puede probar lo que se ve.

## 5. Orden de implementación

1. **Parte A, backend**: criterio `is_required()` en `_mapa_de_modelo`, descriptor con `children`,
   `DESCRIPTOR_KEYS`. Goldens y gates en el mismo commit.
2. **Parte A, front**: `childMap` baja por `children`; tipos; fixture y bundle.
3. **Parte B, backend**: `required_decisions` en el catálogo de trabajos + su derivador y el gate
   bidireccional. Fixture de trabajos en el mismo commit.
4. **Parte B, front**: las decisiones al entrar al trabajo; copy; bundle.
5. **Verificación en vivo** del gate de aceptación de P1, trabajo por trabajo.

Ningún paso autoriza bump, tag ni publicación.
