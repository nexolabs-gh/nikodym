# SDD — El abanico metodológico: elegir el método sabiendo qué cuesta

> **Estado: BORRADOR, pendiente de aprobación de Cami.** Implementa D-JOB-4 y D-JOB-5 del
> [`_SDD-UI-POR-TRABAJOS.md`](_SDD-UI-POR-TRABAJOS.md), que quedaron declarados como contrato el
> 2026-08-01 y sin diseño propio desde entonces.
>
> **Base:** `main` = `c896182` (CI 16/16). **Autor / Fecha:** DanIA / 2026-08-03.
> **Insumo:** [`_CENSO-ABANICO-METODOLOGICO.md`](_CENSO-ABANICO-METODOLOGICO.md), tres barridos
> independientes contra el código. **Ninguna medición de este SDD se re-deriva: se cita.**
>
> **Decisiones:** D-ABA-1 … D-ABA-12.

| Campo | Valor |
|---|---|
| **Problema** | El motor ofrece 50+ puntos de elección metodológica implementados, y la interfaz los sirve como campos sueltos entre otros 394. Qué exige cada opción se descubre **cuando la corrida falla** |
| **Enmienda a** | `_SDD-UI-POR-TRABAJOS.md` (D-JOB-4/5, que declara el qué y no el cómo) · `_ENMIENDA-INVARIANTES-PREVIAS.md` (D-INV-1, la firma del protocolo) · `_ENMIENDA-PREFLIGHT-DATASET.md` (D-PRE-4, el alcance) |
| **No toca** | El motor de cálculo, el `config_hash`, `CONFIG_SECTIONS`, ni el catálogo de defaults efectivos |
| **Release** | Cambio observable de producto; exige CHANGELOG. Este SDD **no** autoriza bump, tag ni publicación |

## 1. El problema, en el idioma del usuario

Un jefe de riesgo que entra a «Provisiones IFRS 9 / ECL» tiene que decidir cuatro cosas de método
—cómo estima la LGD, de dónde sale la curva de PD, si la lleva a condiciones actuales, cómo escalona
el deterioro—. El motor **implementa las cuatro**, con varias alternativas cada una. Lo que la
interfaz le ofrece es un formulario donde esas cuatro decisiones son cuatro desplegables
indistinguibles de un umbral numérico, sin decir qué necesita cada opción ni cuáles puede usar con el
archivo que acaba de subir.

D-JOB-4 y D-JOB-5 ya fijaron el contrato: **el abanico se elige al principio y en idioma de negocio**,
y **una opción que no se puede usar se declara, no se oculta**. Este SDD dice cómo.

### 1.1 Lo que el censo midió, y que no se re-mide aquí

Cinco hechos, con su ubicación en el censo:

1. **El mecanismo que D-JOB-5 necesita ya existe**: `requisitos_incumplidos` (censo §2), llega hasta
   la pantalla y el front **no discrimina por `kind`** — consume `path` y `message`. Ampliarlo es
   aditivo de verdad.
2. **Las exigencias del abanico se reparten en cinco clases** (censo §1), de las que el mecanismo
   actual expresa **una**. La clase **D** —«otra sección activa, o un extra de pip»— es la que no
   tiene mecanismo, y es donde cae medio abanico.
3. **Hay opciones que el config acepta y el motor rechaza al correr** (censo §4). Un abanico que
   derive sus opciones del schema las ofrecería igual.
4. **Hay opciones que no cambian nada** (censo §4, tres casos) y **coacciones silenciosas** donde la
   opción se usa distinto de lo que el usuario cree (censo §5).
5. **La plantilla formal ya está terminada y es `data.partition.strategy`** (censo §9): cuatro ramas,
   roles declarados, requisito propio, y valores ofrecidos sin contestar por el usuario.

## 2. Las tres preguntas abiertas, y sus respuestas

El censo §10 dejó cinco preguntas. Cami contestó las dos de producto (§2.0). Las tres restantes son
el contenido de este SDD.

### 2.0 Lo ya decidido por Cami (2026-08-03), que aquí sólo se registra

**El alcance del preflight se deriva del catálogo de trabajos**: cubre las secciones que algún trabajo
**disponible** declara. Hoy eso son `data`, `binning`, `stability`, las tres de provisiones y
`survival` —las siete ya dentro—, y deja fuera `markov`, `forward` y `stress`, que no pertenecen a
ningún trabajo disponible. **De los cuatro defectos del censo se cerró el de mayor palanca** (los 32
`column_role` de provisiones, 2026-08-03); los otros tres entran en la §7.

## 3. Decisiones

### 3.1 Dónde vive el abanico y de dónde salen sus opciones

**D-ABA-1 — El abanico se declara a mano, con gate bidireccional contra los literales del motor.**
No se deriva del schema. Tres razones, en orden de peso:

1. **Lo que el abanico ES no está en el schema.** D-JOB-4 pide el nombre de negocio y D-JOB-5 pide
   *qué exige cada opción*. Ninguna de las dos cosas se puede derivar de un `Literal[...]`: del schema
   sale `"beta_regression"`, no «la estimo con un modelo sobre mis variables» ni «necesita que tu
   archivo traiga la pérdida observada». Derivarlo del schema entrega el 0 % del valor.
2. **Del schema saldrían las opciones que el motor rechaza.** `binning.solver='cp'` y
   `markov.dynamics.projection_mode='period_matrices'` son `Literal` válidos que abortan al correr
   (censo §4). Ofrecerlas es prometer una elección falsa, que es exactamente lo que D-JOB-5 prohíbe.
3. **El precedente ya está escrito y probado.** D-COL-6 eligió declarar a mano las formas de
   respuesta con gate bidireccional
   (`tests/unit/test_jobs_formas_de_respuesta.py:288`, `test_las_formas_cubren_exactamente_las_ramas_que_el_motor_declara`).
   El riesgo de declarar a mano —desincronizarse en silencio— lo cierra ese gate, y aquí es aún más
   fácil de escribir: un `Literal` es un conjunto cerrado tan derivable como un discriminador.

**D-ABA-2 — Se declara por SECCIÓN, no por trabajo.** Misma razón medida que
`_DECISIONES_POR_SECCION` (`ui/jobs.py:388-390`): ocho de los diez trabajos incluyen `data`, así que
declarar por trabajo copiaría el mismo par ocho veces y la primera vez que alguien afinara el copy,
siete quedarían atrás en silencio. Un trabajo **hereda** el abanico de sus secciones, con la misma
función que ya hereda sus decisiones (`decisiones_de`, `ui/jobs.py:741`).

**D-ABA-3 — El abanico NO se funde con las decisiones obligatorias: es una estructura hermana.**
`_ABANICO_POR_SECCION`, junto a `_DECISIONES_POR_SECCION` y publicada por el mismo `GET /api/jobs`.

*Por qué no fundirlas, que era más barato:* son categorías distintas y medibles. Una **decisión
obligatoria** no tiene default y el config **no construye** sin ella —es criterio institucional que
el motor se niega a inventar (D-OBL-6)—. Un **punto del abanico** tiene default y el motor corre.
Fundirlas rompería `test_toda_decision_declarada_es_de_verdad_obligatoria`
(`tests/unit/test_jobs_decisiones.py:105`), que es justo el gate que impide que la tarjeta de
decisiones se llene de cosas que el motor sí sabe rellenar — y con ello el sentido de esa tarjeta:
*si todo es una decisión, ninguna lo es*.

### 3.2 Qué hacer con las opciones que no sirven — la pregunta 4

**D-ABA-4 — Una opción declara un ESTADO, y son tres declarados más uno computado.** El censo intuyó
«probablemente hace falta una tercera categoría»; medido, hacen falta dos, porque *«el motor no la
tiene»* y *«el motor la acepta y no cambia nada»* no son el mismo caso ni se resuelven igual.

| estado | quién lo fija | qué ve el usuario | ¿puede elegirla? |
|---|---|---|---|
| `disponible` | catálogo | la opción, su ayuda y qué exige | sí |
| `no_implementada` | catálogo | la opción **visible**, en gris, con su motivo | **no** |
| `sin_efecto` | catálogo | la opción, elegible, con la advertencia de que hoy no cambia el resultado | sí |
| *(condicionada)* | **se computa**, no se declara | qué le falta a **sus** datos para poder usarla | sí, con el aviso |

🔴 **El cuarto no se declara a propósito, y es la línea que separa este diseño de una lista de
rótulos.** «No puedes usar `beta_regression` porque tu archivo no trae la pérdida observada» depende
del archivo del usuario, no de la opción. Declararlo en el catálogo sería una afirmación sobre datos
que el catálogo no ha visto — el error de categoría que D-PRE-1 existe para impedir. Lo computa el
preflight, con el mecanismo de §3.3.

**D-ABA-5 — `no_implementada` obliga a las DOS superficies, en el mismo commit: el catálogo lo dice
antes, y el validador del motor lo impide después.** Rotularla sólo en el catálogo deja el defecto
vivo para quien llega por YAML o por código —que es el 100 % de quien usa esto **como librería**—, y
Nikodym es una librería antes que una aplicación. Y al revés: cerrarla sólo en el validador convierte
una elección legítima en un error críptico, que es el estado de hoy.

Es el simétrico de D-PRE-5 —*el preflight informa, nunca bloquea*— aplicado a su otra mitad: **el
preflight informa, el motor decide.** Ninguna de las dos superficies sustituye a la otra.

**D-ABA-6 — `sin_efecto` se declara con su medición citada, nunca por sospecha.** El estado dice al
usuario «esto no va a cambiar tu resultado», que es una afirmación fuerte sobre el motor. Cada
entrada `sin_efecto` lleva en el propio catálogo el `archivo:línea` que lo prueba, y un gate exige
que ese comentario exista. Sin esa disciplina el estado se convierte en un vertedero de dudas.

### 3.3 La clase D sin romper D-INV-1 — la pregunta 5

La clase D del censo son dos cosas distintas metidas en una fila, y sólo una necesita mecanismo.

**D-ABA-7 — La mitad barata no necesita mecanismo nuevo: un extra de pip se comprueba con el
protocolo que YA existe.** `requisitos_incumplidos(columnas)` puede consultar
`importlib.util.find_spec` sin recibir nada más — el preflight corre **en el mismo proceso y el mismo
entorno** que el motor, tanto por HTTP (`ui/routes.py:1026`, mismo servidor que `/api/run`) como por
código. No lee un solo dato, así que no roza D-PRE-1.

Esto abarata el diseño más de lo que parece: los extras son la mitad **más frecuente** de la clase D
(censo §8 — `survival.method` ramifica en dos extras distintos, `forward.macro.kind='auto_arima'`,
`data.load.backend='polars'`, `file_format='excel'`) y hoy se descubren todos con un
`MissingDependencyError` en mitad de la corrida.

🔴 **Y tiene una consecuencia que hay que declarar, no descubrir programando: `check_dataset` deja de
ser función pura de `(config, columnas)`.** Su veredicto pasa a depender del entorno instalado, y eso
es correcto —la pregunta *«¿puedo correr esto?»* siempre dependió del entorno; lo que cambia es que
ahora se contesta antes— pero obliga a tres cosas:

- **El requisito por extra ausente no entra en `compatible`**, o un job mínimo declararía incompatible
  un config que en el entorno del usuario corre. Va como aviso, igual que el resto (D-INV-3).
- **Ningún test puede aseverar `requisitos_incumplidos(...) == ()` sin gatear el extra**, o los jobs
  sin extras se ponen rojos. ⚠️ Y simular la ausencia exige `ModuleNotFoundError`, no un módulo falso
  que reviente al importarse: `importorskip` los distingue y el segundo da **falso rojo**.
- **El gate se mide en los dos sentidos** —con el extra y sin él—, porque un requisito de entorno que
  no se emite nunca es indistinguible de uno que no existe.

**D-ABA-8 — La otra mitad —«esta opción exige que otra sección esté activa»— entra por un método
hermano que recibe un CONTEXTO CERRADO, nunca el config raíz.**

```python
def requisitos_incumplidos_por_contexto(self, contexto: ContextoConfig) -> tuple[Requisito, ...]: ...
```

```python
@dataclass(frozen=True, slots=True)
class ContextoConfig:
    """Lo que una sección puede saber del resto del config, y nada más."""
    secciones_activas: frozenset[str]
```

**Cuál de los tres patrones aplica, y por qué.** El repo tiene hoy dos formas de método hermano, y no
son intercambiables:

| patrón | devuelve | efecto | ejemplos |
|---|---|---|---|
| `requisitos_incumplidos_por_perfil` | `tuple[Requisito, ...]` | **AÑADE** avisos | `BinningConfig` |
| `columnas_inactivas` / `columnas_que_produce` | `frozenset[str]` | **QUITA** avisos | IFRS 9 ×3, `DataConfig` |

La clase D **añade** un aviso —«elegiste consumir la curva PIT y la sección que la produce está
apagada»—, así que es hermano del primero. La distinción no es estética: los supresores heredan la
obligación de D-RAM-4 de medirse en **los dos sentidos** porque pueden **callar** un desajuste, y un
método que sólo añade no puede hacer eso.

**Por qué un DTO y no `frozenset[str]` a secas.** Es el punto de extensión. El censo §6 aisló una
sexta situación —*una propiedad del CONTENIDO de un artefacto que produce otra sección*, donde vive
`pit_mode='consume_pit'`— cuya información **ya existe en tuplas constantes**
(`survival/results.py:42`, `markov/step.py:62-72`, `forward/satellite.py:77-86`) y no está conectada.
El día que se conecte, se añade un campo al DTO y **quien no lo lea sigue funcionando igual**. Un
`frozenset` obligaría a cambiar la firma de todos los implementadores, que es exactamente la rigidez
que D-INV-1 evita.

⚠️ **Y por qué esto NO viola D-INV-1.** La decisión original dice que la invariante la declara el
dominio que la impone, y que no se le da el config raíz a cada dominio para no acoplarlos. Un DTO
cerrado con un campo no es el config raíz: el dominio **no puede leer un campo ajeno** aunque quiera,
porque no está ahí. La restricción se conserva; lo que se amplía es el contexto mínimo, y su tamaño
es la garantía.

### 3.4 El alcance del preflight deja de ser una lista escrita a mano

**D-ABA-9 — La exención «fuera del alcance F1» se DERIVA del catálogo de trabajos; las exenciones con
razón propia siguen escritas.** Hoy `tests/unit/test_invariantes_previas.py:191-216` tiene 17
exenciones, de las que **10 alegan la misma frase** —*«fuera del alcance F1 del preflight
(D-PRE-4)»*— y 7 tienen una razón técnica propia (la de `binning` depende de dtypes, la de `selection`
es que sus cuatro campos son `derived`, la de `report` es que su invariante es **entre** secciones…).

Las dos clases se separan:

- **Derivada**: una sección que no pertenece a ningún trabajo **disponible** está exenta, y nadie tiene
  que acordarse de escribirlo. Cuando un trabajo pase a disponible, sus secciones entran solas y el
  gate obliga a decidir.
- **Escrita**: una sección **dentro** del catálogo que no implementa el protocolo declara su razón
  técnica, como hoy.

Con dos candados: ninguna sección puede estar en las dos clases, y **ninguna exención escrita puede
alegar «fuera de alcance»** — esa razón la da el catálogo o no la da nadie. Sin el segundo candado, la
lista escrita seguiría pudiendo eximir a mano lo que el catálogo ya incluye, que es el agujero que
esto cierra.

#### 🔴 Su coste, medido — no es cosmético

Cruzadas las 17 exenciones vigentes contra las secciones de los **8 trabajos disponibles**
(`jobs.list_jobs()`, medido sobre `c896182`):

| grupo | nº | qué pasa |
|---|---:|---|
| alegan «fuera de alcance» y están **fuera** del catálogo — `explain`, `forward`, `markov`, `ml`, `stress`, `tuning` | 6 | la exención se **deriva**; salen de la lista escrita, gratis |
| alegan «fuera de alcance» y están **DENTRO** — `provisioning`, `provisioning_cmf`, `provisioning_ifrs9`, `provisioning_internal` | **4** | 🔴 **pierden la exención**: o implementan el protocolo, o declaran razón técnica propia |
| razón propia y dentro — `binning`, `calibration`, `model`, `report`, `scorecard`, `selection` | 6 | siguen escritas, sin cambios |
| razón propia y fuera — `eda` | 1 | doble motivo: su razón escrita **sobra** y el candado bidireccional la saca |

**Las cuatro secciones de provisiones son el trabajo real de esta decisión**, y no se puede
descubrir programando: hoy están exentas por una frase —«fuera del alcance F1»— que dejó de ser
cierta el día que «Provisiones CMF», «Provisiones IFRS 9 / ECL» y «Provisión interna / LGD» pasaron a
**disponibles**. La exención llevaba tiempo siendo falsa y la lista escrita a mano no tenía forma de
notarlo: ése *es* el defecto que D-ABA-9 cierra, y el catálogo derivado lo hace visible el primer día.

⚠️ **Ninguna sección queda huérfana**: medido, los dos trabajos no disponibles (`lgd_modelada`,
`stress_testing`) no aportan **ninguna** sección que no esté ya en un trabajo disponible, así que la
derivación no depende de qué trabajo se habilite después.

⚠️ **El alcance dice qué se EXIGE, no qué se permite.** `validation` está fuera del catálogo por
D-JOB-18 —el formulario no la ofrece— y sin embargo **implementa** `requisitos_incumplidos`
(`validation/config.py:430`). Eso no es una incoherencia que haya que resolver: implementar de más es
gratis y correcto. Lo que la derivación decide es a quién se le **reclama**, y por eso el candado
«ninguna exención sobra» sólo puede aplicarse a la lista escrita, nunca al conjunto derivado — que no
es una lista donde algo pueda sobrar.

### 3.5 Dónde se ve

**D-ABA-10 — El abanico se pinta en el mismo paso que las decisiones obligatorias, en bloque propio y
DESPUÉS de ellas.** D-JOB-4 pide que el abanico se elija «al principio, antes de los parámetros de
detalle»; eso es este paso. Dentro de él, las obligatorias van primero porque **impiden correr** y el
abanico no: ponerlo delante colocaría lo opcional por delante de lo que bloquea.

**D-ABA-11 — El `path` sigue sin enseñarse nunca.** Lo que el usuario lee es la pregunta, la etiqueta
de la opción y su ayuda (D-OBL-9), y todo ello entra al gate de jerga. El `path` es la coordenada
interna que ata el catálogo al motor, y su sitio es el gate bidireccional.

### 3.6 Identidad

**D-ABA-12 — Nada de esto mueve un solo `config_hash`.** El abanico no añade ningún campo de config
—declara opciones que ya existen— y los métodos del protocolo son métodos, no campos (D-RAM-2). Elegir
una opción del abanico escribe **exactamente** el mismo valor que escribirla a mano en el formulario,
así que dos usuarios que llegan al mismo config por caminos distintos producen la misma identidad
(D-JOB-9 intacto). Gate sobre los tres presets, byte a byte.

## 4. Alternativas rechazadas

1. **Derivar el abanico del schema.** Sale gratis y completo, pero entrega el 0 % de lo que D-JOB-4/5
   piden (§3.1) y ofrece las opciones que el motor rechaza.
2. **Ampliar la firma de `requisitos_incumplidos` para que reciba el config raíz.** Es lo que D-INV-1
   rechazó por acoplar cada dominio a todos los demás, y no ha cambiado nada que lo justifique.
3. **Ocultar las opciones no implementadas.** Contradice D-JOB-5 en su letra: *deja al usuario creyendo
   que la librería no la tiene*. Y en un producto cuyo argumento es «el motor tiene abanico serio»,
   esconder las que faltan es la peor forma posible de contarlo.
4. **Fundir el abanico con las decisiones obligatorias** (§3.3).
5. **Evaluar las exigencias de TODAS las opciones contra los datos, no sólo la elegida.** Exigiría
   instanciar N configs hipotéticos por punto de elección y mantenerlos válidos. Se rechaza por coste y
   fragilidad; lo que sí se evalúa de una vez para todas las opciones es lo barato —extra de pip y
   sección activa—, que no necesita instanciar nada.
6. **Un registro central de exigencias del abanico.** Mismo criterio con que D-INV-1 rechazó el
   registro central de invariantes y `column_role` rechazó el registro central de roles: la exigencia
   es propiedad de la opción, y un registro aparte se desincroniza.

## 5. Gates de aceptación

- **Bidireccional sobre las opciones**: `{opciones declaradas para un path}` iguala `{literales que el
  motor declara en ese campo}`, leído de `model_fields`. Una opción nueva en el motor sin su entrada ⇒
  rojo; una entrada sin opción detrás ⇒ rojo. Control negativo **ejecutado** en las dos direcciones.
- **Anti-vacuidad**: el barrido recorre ≥ N puntos de elección y ancla tres nombres literales. Un gate
  que recorra cero da verde y no prueba nada — pasó ya dos veces en este repo.
- **`no_implementada` cerrada en las dos superficies**: por cada opción con ese estado, un test
  comprueba que el catálogo la declara **y** que el config la rechaza al construir. Declarar una sin
  cerrar el validador ⇒ rojo.
- **`sin_efecto` con su prueba**: cada entrada cita el `archivo:línea` que lo sostiene, y un gate exige
  que la cita exista.
- **La clase D avisa y no bloquea** (D-PRE-5 y D-INV-3 intactos): un requisito de contexto incumplido
  produce un `unmet_requirement`, no un error.
- **El contexto no filtra el config**: un test comprueba que `ContextoConfig` expone **exactamente** los
  campos declarados. Añadir el config raíz por descuido ⇒ rojo.
- **Cobertura de exenciones, con sus dos candados** (D-ABA-9): ninguna sección en las dos clases, y
  ninguna exención escrita alegando «fuera de alcance».
- **Hash-neutralidad**: los tres presets conservan su `config_hash` byte a byte. Control negativo:
  convertir una opción del abanico en un campo de config lo mueve.
- **Paridad**: elegir una opción del abanico da el mismo `config_hash` que escribirla campo a campo.
- **Copy sin jerga** en toda pregunta, etiqueta, ayuda y motivo (gate vigente, extendido).
- **El front no discrimina por `kind`** y sigue sin hacerlo: un requisito de clase D viaja por el mismo
  `path`/`message` y **no exige una línea de front nueva para MOSTRARSE**. (El bloque del abanico sí es
  front nuevo — D-ABA-10 —; lo que este gate mide es que el mecanismo de aviso no se bifurque.) Si un
  requisito nuevo obligara a tocar `preflight.ts`, el diseño está mal.
- Fixture de trabajos y de schema regenerados y bundle reconstruido **en el mismo commit**; suite,
  mypy, ruff (`check` **y** `format --check`), vitest, typecheck, `mkdocs --strict`, CI 16/16.
- **Verificación en vivo con Playwright**: vitest corre sin DOM.

## 6. Lo que este SDD NO resuelve, dicho y no escondido

1. **La sexta situación del censo (§6): la propiedad del CONTENIDO de un artefacto ajeno.** Es donde
   vive el default de fábrica incoherente de IFRS 9. El DTO de D-ABA-8 está diseñado para admitirla
   después sin romper a nadie, y su información ya existe en tuplas constantes; conectarla es paquete
   propio.
2. **La clase E —los valores de los datos— sigue fuera y debe seguirlo** (D-PRE-1, contrato).
3. **Las coacciones silenciosas del censo §5** son una superficie distinta —«se usa distinto de lo que
   crees», no «no se puede usar»— y necesitan su propio copy. Dos de las cinco son declarables con lo
   que este SDD deja hecho.
4. **No amplía `CONFIG_SECTIONS`**: `markov`, `forward`, `stress` y `validation` siguen fuera del
   formulario, así que su abanico no se puede pintar aunque se declare. Es el mismo límite que
   D-JOB-18 escribió para `validation`.
5. **No convierte `provisioning_cmf` en una sección que declare con su motivo**: hoy todo su faltante
   es excepción dura y no tiene `card.falta_dato` (censo §11).

## 7. Los tres defectos del censo que este SDD arrastra

Independientes del abanico y valen por sí solos; entran en el mismo paquete porque los tres son casos
de D-ABA-4/5 y sin ellos el catálogo tendría que rotular como `no_implementada` algo que se arregla en
una línea.

| # | defecto | estado que le corresponde | qué hay que hacer |
|---|---|---|---|
| E | `markov.dynamics.projection_mode='period_matrices'`: el config la acepta, el motor la rechaza al proyectar | `no_implementada` | cerrar el validador (D-ABA-5) |
| F | `provisioning_cmf.guarantees.require_recoverable_for_default` no se lee nunca; `fail_on_unmapped_contingent_type` promete una elección cuyas dos ramas levantan | `sin_efecto` | declararlo con su cita (D-ABA-6) |
| G | el gate de `lifelines` es más estricto que el motor: exige el extra para `kaplan_meier`, cuyo estimador declara que no lo usa en la ruta core | — | corregir el gate; es el insumo de D-ABA-7 |

## 8. Orden de implementación

1. **`core/dataset_check.py`** — `ContextoConfig` + `METODO_REQUISITOS_CONTEXTO` y su recorrido, con
   el gate del contexto cerrado en el mismo commit.
2. **Los tres defectos del §7**, que son los casos de prueba de D-ABA-4/5/6/7.
3. **`ui/jobs.py`** — `_ABANICO_POR_SECCION` con su gate bidireccional; fixture de trabajos en el
   mismo commit.
4. **Los `requisitos_incumplidos` de extras** (D-ABA-7) en las secciones que ramifican por extra.
5. **`requisitos_incumplidos_por_contexto`** en las secciones de clase D.
6. **`web/`** — el bloque del abanico en el paso de decisiones; bundle en el mismo commit.
7. **Verificación en vivo** de un trabajo con abanico real, de punta a punta.
8. **D-ABA-9** — la exención derivada, al final, porque necesita que el catálogo esté completo.

Ningún paso autoriza bump, tag ni publicación.
