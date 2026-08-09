# Enmienda — una opción del abanico puede exigir OTRO campo, y hoy se ofrece como si no

> Estado: **APROBADA E IMPLEMENTADA ENTERA — Cami, 2026-08-08**, en dos tandas: primero
> D-EXI-1/2/3/7 y después D-EXI-5 y D-EXI-6. Escrita sobre la deuda 2 del HANDOFF del 2026-08-07,
> medida por tres agentes y atacada por dos lentes adversariales. Decisiones `D-EXI-1…D-EXI-7`.
>
> 🔴 **D-EXI-6 se implementó de OTRA FORMA que la escrita, y la decisión la tomó Cami con el coste
> medido delante.** Esta enmienda decía «el validador deja de aplicar cuando el método no abre la
> subsección»; al implementarlo se midió que los validadores viven en las **ramas**, que Pydantic
> valida **antes de que el padre exista**, así que hacerlo obligaría a (a) que `InternalLgdWorkout()`
> dejara de fallar —dos clases del `__all__` público—, (b) invertir dos tests que expresan D-LGD
> textual («la rama ES el método, así que la regla deja de ser condicional») y (c) divergir de
> `provisioning_ifrs9`, que seguiría exigiéndolo en la misma regla. Nada de eso estaba evaluado aquí.
> **La salida elegida cierra el defecto en la SUPERFICIE**: el punto de elección gana `when` —el
> mecanismo ya existía para `external_artifacts`— y con `method='direct_loss_rate'` no se ofrece.
> Ver §2 de D-EXI-6, reescrito.
>
> ✅ **D-EXI-5 se implementó como la forma más los dos `raise` de LGD.** Los otros 121 quedan
> migrables uno a uno sin tocar contrato, que es lo que esta enmienda propone: decide la forma, no
> hace el barrido.
>
> ⚠️ **Y el criterio de D-EXI-3 se afinó al implementarlo, contra la recomendación del revisor.**
> «Medir constructibilidad de CADA rama» acusa **9** ramas y **6 son inocentes** (las tres de
> `data.partition.strategy`, cuyo campo es `is_required()` ⇒ D-OBL las pregunta, y los tres
> `X | None`, que no son uniones de método). El criterio que acusa exactamente 3: unión
> **discriminada** + campo **no requerido** + rama que no construye.
>
> Enmienda a **D-ABA-3/D-ABA-5** (`_SDD-ABANICO-METODOLOGICO`) y a **D-ANC-11/12**
> (`_ENMIENDA-ANCLA-DESCARTADA.md`). Toca **D-OBL-6** sólo para declarar que **no** aplica.

## 0. La deuda estaba mal planteada, y medirlo cambió el trabajo

El HANDOFF decía: *«elegir una rama modelada da un `InternalConfigError` inmediato, no un aviso de
preflight. Es la salida honesta (el patrón de `bad_rule`), pero no está trasladada a ninguna
superficie que el usuario lea»*. De sus seis afirmaciones, **cuatro son ciertas, una es FALSA y una
es PARCIAL** — y la falsa es justo la que sostenía la prescripción:

| afirmación del HANDOFF | veredicto | evidencia |
|---|---|---|
| `covariate_cols`/`recovery_col` tienen default ⇒ `is_required()` False | **CIERTA** | medido |
| `_DECISIONES_POR_SECCION` no tiene entrada para `provisioning_internal` | **CIERTA** | `jobs.py:576` → sólo `data` y `survival` |
| elegir una rama modelada da un `InternalConfigError` inmediato | **CIERTA** | `internal/config.py:293` y `:443`, al validar |
| …y no un aviso de preflight | **CIERTA** | el preflight queda **mudo**, ver §1.2 |
| «es la salida honesta, el patrón de `bad_rule`» | **PARCIAL** | `bad_rule` es `is_required()=True` **sin default**: el config no construye sin él, y por eso el trabajo lo **pregunta**. Aquí el hueco viene **solo**, sin pregunta que lo acompañe |
| «no está trasladada a ninguna superficie que el usuario lea» | 🔴 **FALSA** | `/api/validate` da **200** con `valid=false` y el mensaje, y el front lo pinta bajo «Config inválido · 1 error» vía `unanchoredError` (`validation.ts:60`, `ConfigTab.tsx:516`) — el hueco que **D-ANC-12 ya cerró** |

⇒ **La prescripción «que avise en vez de reventar» es inejecutable, y lo que queda debajo es peor
para el usuario.** Las dos lentes lo dictaminaron por separado como bloqueante:

1. Para que el preflight pueda avisar, el config tiene que **construir**; para que construya hay que
   quitar el `model_validator`. Medido ejecutando el motor con la guarda saltada: **no** sale un
   error de dominio nombrado, sale un fallo del cálculo aguas abajo. Eso viola **CRP-5** de frente
   (la validación no se mueve al medio del cálculo) y **degrada** la calidad del diagnóstico.
2. **No hay ningún resultado silencioso equivocado que justifique preferir el aviso.** La corrida no
   arranca, el mensaje se lee, y el criterio de **D-ANC** dice por escrito que *«avisar de algo que
   el propio repo declara inadmisible es más débil que rechazarlo»*.

**Por tanto el ERROR se conserva.** Lo que falla es otra cosa, y son tres defectos reales.

## 1. Los tres defectos medidos

### 1.1 🔴 D-ABA-3 está violado hoy en producción, y su oráculo no puede verlo

El abanico publica las **cinco** opciones de `provisioning_internal.lgd.method` con
`estado='disponible'` y `motivo=None` — incluidas las tres que **no se pueden elegir** sin traer otro
dato. D-ABA-3 dice que una opción que el motor rechaza no se ofrece como disponible.

Y su gate es **estructuralmente incapaz** de cazarlo, por dos razones medidas: no comprueba
**constructibilidad**, y sobre una unión discriminada **inspecciona la primera rama**, no las cinco.
Es la tercera vez en este repo que un oráculo que no puede fallar convive con la suite verde.

### 1.2 🔴 El error llega SIN ANCLA, y el gesto simétrico sí ancla

El mismo gesto —elegir una rama de una unión discriminada— tiene dos resultados opuestos:

- `data.partition.strategy = 'temporal'` sin su columna de fecha → el desajuste **marca el campo** y
  el salto del preflight lleva al control.
- `provisioning_internal.lgd.method = 'beta_regression'` → `loc: []`, «Config inválido · 1 error»
  **sin campo al que saltar**. El usuario lee qué falta y no tiene dónde ponerlo.

La causa está en `ui/routes.py:1005-1020` (`_error_de_dominio`), que pone `loc: []` **con la razón
correcta**: no se puede adivinar el campo del texto del mensaje. La salida no es adivinarlo: es que
**el emisor lo declare**.

⚠️ Y el preflight tampoco rescata el caso: va **encadenado detrás de la validación** y sólo dispara
con `config_hash` en mano (`appStore.tsx:223-231`). Con la rama modelada la validación queda inválida
⇒ `validHash === null` ⇒ `setPreflight({kind:'idle'})` y retorna. **No da 422: queda mudo.** Su propio
comentario ya lo declaraba.

### 1.3 🔴 Con la subsección INERTE, una rama modelada rechaza el config completo

Con `provisioning_internal.method='direct_loss_rate'` la subsección `lgd` **entera** es inerte —el
motor no abre una sola columna suya, eso es D-SUB-2— y aun así elegir una rama modelada de `lgd`
**rechaza el config entero**. Es el simétrico exacto del defecto que D-SUB acaba de cerrar en el
preflight, ahora en el validador. ⚠️ Y el `help` del propio control promete lo contrario.

## 2. Decisiones

### D-EXI-1 — El error se CONSERVA en su momento actual

No se relaja ningún `model_validator`, no se mueve el rechazo, no se toca la unión discriminada.
Cerrado contra la prescripción del HANDOFF, con las dos razones del §0.

### D-EXI-2 — El abanico gana un CUARTO estado declarado: «exige que declares otro campo»

`_ESTADOS_DE_OPCION` es hoy un frozenset **cerrado** de tres (`_DISPONIBLE`, `_NO_IMPLEMENTADA`,
`_SIN_EFECTO`) y `_CLAVES_DE_OPCION` otro de seis, así que **la exigencia sólo puede viajar como
prosa dentro de `help`** — y ahí no la puede leer ninguna máquina ni pintar el front de otro color.
Nace un cuarto estado, con el campo que exige **declarado y legible**.

🔴 **Lo que este estado NO es**, y hay que vetarlo por escrito porque es la salida barata:
rotular las tres ramas `no_implementada` cerraría la deuda **con todos los gates verdes publicando
una falsedad** —que la librería no tiene LGD modelada— el día después de implementarla. El gate de
D-ABA-5 exige exactamente lo contrario.

### D-EXI-3 — El criterio y el oráculo de D-ABA-3 se reescriben para medir CONSTRUCTIBILIDAD por rama

El gate pasa a intentar construir **cada** rama de una unión discriminada, no la primera, y a exigir
que una rama inelegible no se publique como `disponible`. Nace **rojo** acusando las tres ramas
modeladas, que es la prueba de que mide algo.

🔴 **Y el criterio no es «la rama no construye»: eso acusa a seis inocentes.** Medido al
implementarlo, ese criterio a secas señala **9** ramas, y las otras seis están correctamente
cubiertas: las tres de `data.partition.strategy` viven bajo un campo `is_required()`, así que
**D-OBL las declara** y el trabajo las pregunta en idioma de negocio con sus huecos a la vista; y
`good_rule`/`indeterminate_rule`/`window` son `X | None` —submodelos **opcionales**, no uniones de
método—, cuyos campos se abren en el formulario al activarlos. El criterio que acusa exactamente las
tres culpables: unión **discriminada** + campo **no requerido** + rama que no construye. Esa
conjunción es lo que significa «nadie le pregunta al usuario por lo que falta», y va con control
negativo que exige que las seis inocentes **no** entren.

### D-EXI-4 — El requisito se emite desde el PADRE, nunca desde la rama

Si además se emite un `Requisito` por el canal del preflight —para el caso en que el config **sí**
construye pero le falta el dato— tiene que vivir en `InternalProvisioningConfig`, con path relativo
`lgd.covariate_cols`, y **no** en las ramas de LGD. Dos razones medidas:

1. **`_requisitos` NO consulta `columnas_inactivas`** (`dataset_check.py:605-656` nunca llama a
   `:552`). Un requisito dentro de la rama dispararía igual con `direct_loss_rate`, reintroduciendo
   por el canal de requisitos **la clase que D-SUB-1…4 acaba de cerrar**.
2. **Una rama no ve a su padre, y es diseño escrito** (`internal/config.py:727-729`). El padre sí ve
   `self.method`, así que respeta D-SUB-2 por construcción.

✅ Y el mecanismo **ya está probado en esta forma exacta**: `TemporalSplitConfig` —que es una rama de
la unión `PartitionStrategy`— ya implementa `requisitos_incumplidos`, ignora `columnas`, y el núcleo
compone su ruta anidada a absoluta (`data/config.py:612`, `:626`). ⚠️ Y `provisioning_internal` **ya
implementa los dos métodos** (`requisitos_incumplidos` por D-AMB-2 en `:741`, `columnas_inactivas`
por D-SUB-2 en `:726`), lo que el HANDOFF no menciona.

### D-EXI-5 — El error de dominio gana ANCLA, y eso cierra una CLASE de 123 `raise`

Los dos `raise` de `internal/config.py:293` y `:443` pasan a declarar a qué campo pertenecen, y
`_error_de_dominio` emite ese `loc` en vez de `[]`. **No se adivina del texto** —eso es lo que el
comentario actual prohíbe con razón—: lo declara el emisor.

Alcance: son **123 `raise` en 18 de las 22 secciones de dominio** (censo de D-ANC-10), así que esto es
mecanismo, no parche. La enmienda decide **la forma**; migrar los 123 es incremental y no bloquea.

### D-EXI-6 — Con la subsección inerte, el punto de la severidad NO SE OFRECE

🔴 **Reescrita al implementarla, con decisión de Cami.** La redacción original —«el validador de las
ramas modeladas deja de aplicar cuando `provisioning_internal.method` no abre la subsección»— **no es
implementable sin cambiar contrato público**, y eso se midió al programarla:

1. Los validadores viven en las **ramas** (`_check_regresion`, `_check_workout`), y Pydantic las
   valida **antes de que el padre exista**. No hay forma de que el padre las suprima.
2. Moverlos al padre obliga a que `InternalLgdWorkout()` y `InternalLgdBetaRegression()` **dejen de
   fallar**. Las dos están en el `__all__` de `provisioning.internal`: es cambio de API pública.
3. Y contradice **D-LGD**, aprobado el día anterior y escrito en dos tests: *«se rechaza en el
   config, no en la corrida; con la unión la regla deja de ser condicional porque la rama ES el
   método»*. `IfrsLgdConfig` seguiría exigiéndolo, así que los dos motores divergirían en la misma
   regla.

✅ **Lo que se hizo: cerrarlo en la SUPERFICIE.** El punto de elección del abanico gana `when`, y con
`provisioning_internal.method='direct_loss_rate'` **no se ofrece** — no se pinta en gris, se filtra:
no es una elección bloqueada que el usuario podría desbloquear, es una pregunta que con ese método no
tiene sentido hacer. Y el `help` deja de prometer que «esta elección no cambia el resultado», que era
falso en el peor sentido: no daba igual, **rechazaba el config entero**.

⚠️ **El mecanismo no es nuevo**: es el mismo `when` (`{"path": …, "equals": …}`) que
`external_artifacts` ya declara y que el front evalúa con `valueAtPath`. Reutilizarlo evita meter un
segundo lenguaje de condiciones en el front, y por eso el coste fue una clave opcional y un filtro.

⚠️ **Coste: cero identidad, cero API pública, cero validador.** Ningún `config_hash` se mueve, ninguna
clase se relaja y ningún config que hoy corre cambia de resultado. Lo que cambia es qué se ofrece.

### D-EXI-7 — D-OBL queda FUERA, con su razón medida

Declarar esto como decisión obligatoria (el patrón de `bad_rule`) **no es una opción**, y no por
coste: el gate lo **prohíbe**. Control negativo ejecutado: inyectar una entrada para
`provisioning_internal` pone **tres tests en rojo**. Y por construcción, `_hojas_obligatorias` **no
desciende por una unión** (su anotación no es un `type`), y el campo `lgd` tiene
`default_factory=InternalLgdProvided` ⇒ `is_required()` False. ⚠️ Portarlo a la fuerza produciría
además un falso **«Respondida»** sobre un config que el motor rechaza —la clase exacta que D-RES
existe para cerrar—, porque el `loc` viene vacío.

## 3. Coste, medido

> **Nota de cierre:** esta tabla conserva el presupuesto previo a implementar. D-EXI-6 terminó en
> la superficie con `when`; no tocó el validador. Véase el estado canónico en
> [`DECISIONES-VIGENTES.md`](DECISIONES-VIGENTES.md), §D-EXI.

| qué | medido |
|---|---|
| los cuatro `config_hash` | **cero** para D-EXI-2/3/5; D-EXI-6 terminó también en cero al resolverse con `when`, sin tocar el validador |
| archivos | `ui/jobs.py` (estado + 3 opciones), `web/src/lib/jobs.ts` (espejo cerrado) + su render, `ui/routes.py` (`_error_de_dominio`), `internal/config.py` (2 `raise` y el validador) |
| gates | `test_jobs_abanico.py` (criterio y oráculo), `test_jobs_decisiones.py` (declarar que no aplica), fixture de trabajos y bundle |
| API pública | **cero**: ningún nombre, firma ni default cambia |

## 4. Las tres decisiones aprobadas

1. **D-EXI-2 + D-EXI-3** (el cuarto estado y el oráculo por rama) — el núcleo de la enmienda.
2. **D-EXI-5** (el ancla del error) — cierra una clase de 123 `raise`; se puede aprobar aparte.
3. **D-EXI-6** (la subsección inerte) — implementada filtrando el punto con `when`; no se relajó el
   validador.

## 5. Menores medidos, que la enmienda declara y no necesariamente resuelve

- **El selector de la unión pinta el tag crudo en snake_case inglés** (`beta_regression`, `workout`)
  mientras las etiquetas de negocio ya están escritas en el abanico y viajan por otro canal. No
  verificado en pantalla.
- **En el estado OPACO el backend SÍ publica el motivo del rechazo y el front lo descarta**,
  imprimiendo una frase que en este caso es **falsa** («esta instalación no sabe leerla» — sí la
  sabe: la rechazó).
