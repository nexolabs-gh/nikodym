# Enmienda SDD — la puerta de artefactos por HTTP/UI: traer tu PD y tu score desde la interfaz

> **Estado:** **APROBADA e IMPLEMENTADA** (OK explícito de Cami, 2026-08-01). Verificada en vivo con
> Playwright de punta a punta, no sólo con tests. Ver §7 para lo que la implementación corrigió.
> **Enmienda a:** [`_ENMIENDA-PUERTA-ARTEFACTOS.md`](_ENMIENDA-PUERTA-ARTEFACTOS.md) §D-ART-9 (que
> dejó HTTP/UI fuera con su razón), [`_SDD-UI-POR-TRABAJOS.md`](_SDD-UI-POR-TRABAJOS.md) §D-JOB-7,
> SDD-23 §7/§10 (contrato REST y seguridad local) y la enmienda B2.2 (E-B2.2-2, guardas locales).
> **Decisiones:** D-PUE-1 … D-PUE-13, **más D-PUE-6-bis** (§8, aprobada el 2026-08-02).
> **Nodo de roadmap:** P1 · D-JOB-7, y con él P2 («validar un modelo existente»).
> **Autor / Fecha:** DanIA · 2026-08-01 (medido contra `main` = `5ef2dff`, CI 16/16).
>
> 🔴 **D-PUE-6 quedó CORREGIDA por §8 el 2026-08-02**: el modo «con llave» que la decisión llamaba
> *el correcto* indexaba **un solo lado** y cruzaba las filas en silencio. La decisión vigente sobre
> alineación es **D-PUE-6-bis**; el texto original de D-PUE-6 se conserva porque es lo que se
> implementó y explica el defecto.

---

## 0. La carencia que la origina

Dos trabajos del catálogo están declarados **no disponibles**, y los dos por la misma razón exacta,
escrita en el propio catálogo (`ui/jobs.py:143` y `:208`):

- **Provisión interna / LGD** — «Necesita que traigas la PD ya calibrada de tu modelo, y por ahora
  eso sólo se puede hacer desde Python.»
- **Validar un modelo existente** — «La ruta todavía no existe: falta poder traer un scorecard y una
  PD de fuera.»

El motor **sí sabe correrlos**. La puerta de artefactos por código existe, está probada y es pública
(`nikodym.run(config, artifacts=…)`, `api.py:169`). Lo que falta es la superficie: quien instala el
paquete y trabaja por la interfaz no puede alcanzarla. Es la definición de *no entregado* que el
repo ya fijó (`AGENTS.md` §Decisiones fijadas).

D-ART-9 dejó HTTP fuera **a propósito y con su razón**, y nombró las tres preguntas que había que
contestar antes: *cómo viaja un artefacto por la red*, *qué tope de tamaño*, y *qué se hace con el
vector de deserialización que `Study.load(trust=False)` rechaza*. Esta enmienda las contesta.

---

## 1. Lo que la medición corrigió del plan escrito

Van once veces en este repo. Cinco correcciones antes de decidir nada.

### 1.1 🔴 «El archivo del usuario tiene que ser un `calibrated_pd_frame`» — **falso**

El contrato canónico de SDD-10 §6 —ocho columnas en orden fijo— lo impone
`CalibrationResult._copia_dataframe` (`calibration/results.py:192-204`), que es el **DTO agregado**.
Pero el artefacto que viaja por el `ArtifactStore` es el `DataFrame` suelto, y **ningún consumidor
lo valida contra esas ocho columnas**. Medido, los tres consumidores piden columnas *configurables*:

| consumidor | qué exige del frame de PD | dónde |
|---|---|---|
| `provisioning_internal` | la columna `pd_column`, índice único, **cobertura total** del índice de `data.frame` | `provisioning/internal/engine.py:225-242` |
| `performance` | `partition_column`, `target_column`, `pd_column` | `performance/step.py:177-181` |
| `stability` | `partition_column`, `pd_column` | `stability/step.py:216-219` |
| `performance` / `stability` | de `scorecard.score`: `score_column` (+ columnas de puntos, opcionales) | `performance/step.py:177`, `stability/step.py:210-214` |

**Consecuencia de alcance, y es la que abarata toda la enmienda:** el usuario no tiene que fabricar
un artefacto del motor. Le basta **una tabla con dos a cuatro columnas**, y los nombres los declara
él en campos de config que **ya existen**. El backend no necesita saber qué columna cumple qué rol:
siembra el frame completo y cada consumidor toma `.loc[:, […]]` con las columnas que su propio
config nombra.

### 1.2 🔴 Los dos artefactos de «validar un modelo» tienen que compartir índice, y el motor lo exige

`performance/step.py:183-190` levanta si `scorecard.score` y `calibration.calibrated_pd_frame` no
tienen el **mismo** índice, en los dos sentidos (`difference` de ida y de vuelta); `stability` repite
la comprobación (`stability/step.py:256-262`). Pedir dos archivos separados hace ese fallo
*alcanzable por construcción*: dos exportaciones distintas del mismo modelo, con una fila filtrada,
producen una corrida que muere después de haber pedido dos subidas. Lo resuelve D-PUE-4.

### 1.3 ⚠️ El tope de 100 MiB es **post-hoc**, y hoy ya lo es

`routes.py:639` hace `content = await file.read()` —el cuerpo entero en memoria— y el chequeo del
límite ocurre después, en `datasets.py:282`. No hay verificación de `Content-Length` ni lectura por
streaming. No es un defecto que esta enmienda introduzca, pero **sí sería un defecto que esta
enmienda duplicara** si abriera un segundo canal de subida. Lo resuelve D-PUE-3.

⚠️ Y el campo que *parece* gobernar ese tope no lo gobierna: `UiConfig.upload_max_mb`
(`settings.py:30`, declara 200 MB) **no lo lee nadie** — sus únicas apariciones en el repo son su
declaración y tres líneas de su propio test. El límite efectivo son los 100 MiB *hardcoded*.

### 1.4 🔴 No existe gate estructural de clasificación de rutas — verificado, no supuesto

`MUTATING_PATHS` (`security.py:25`) y `CREDENTIALED_PATHS` (`security.py:34`) las consume **un solo
sitio**: el middleware `_guardas_locales` (`security.py:45-57`). Ningún test enumera las rutas reales
del router para exigir que cada una esté clasificada. Un `grep` de las dos constantes en todo el repo
devuelve sólo `security.py`, una mención en un docstring de test, y `CLAUDE.md`/`AGENTS.md` — o sea,
la carencia está **escrita** pero no **ejecutada**.

Hoy quedan sin `Origin` ni token, entre otras, `POST /api/validate` (`routes.py:603`),
`POST /api/config/to-yaml` (`routes.py:697`) y `POST /api/config/from-yaml` (`routes.py:708`). Eso es
correcto —no escriben ni ejecutan— pero **nadie lo declaró**: es indistinguible de un olvido. Y ése
es exactamente el estado en que `/api/preflight` se coló sin token hasta el 2026-07-28. Lo cierra
D-PUE-9.

### 1.5 🔴 `/api/validate` mentiría justo en el caso que esta enmienda habilita

`_pipeline_payload` (`routes.py:241`) llama `nikodym.check_pipeline(model)` **sin artefactos**. Con
las secciones productoras apagadas —que es la forma del config de estos dos trabajos— el veredicto
sale `executable=False` sobre un config que **sí corre**. Es la familia de D-PRE-9 y D-INV-1: una
superficie que responde «no se puede» sobre lo que no miró. Y `PipelineCheck.inert_artifacts`
(`api.py:73`) no se proyecta al contrato REST (`routes.py:251-255`), así que por HTTP el aviso de
clave inerte **no tiene por dónde salir**, contradiciendo la §6.1 de la enmienda de la puerta.

---

## 2. Decisiones

### D-PUE-1 · Por HTTP no se deserializa ningún objeto: el insumo externo es una **tabla**

La puerta HTTP admite exactamente los mismos tres formatos que `/api/upload` ya admite —`.csv`,
`.xlsx`, `.parquet`— leídos por los mismos tres lectores de pandas (`datasets.py:460-464`). Nada más.

**Prohibido de forma explícita y con gate:** `pickle`, `joblib`, `Study.load`, `dill`, `marshal`,
`yaml.unsafe_load`/`yaml.Loader`, y cualquier ruta que reconstruya un objeto Python arbitrario desde
bytes del cliente. Hoy la capa `nikodym/ui/` no importa ninguno de ellos (verificado: la única
aparición de la palabra «pickle» es el docstring de `runs.py:5` explicando que se evita), y el
código que sí los usa vive fuera de la UI y ya tiene su puerta `trust=False`
(`core/study.py:791-794`).

**Consecuencia declarada, y es el corazón de la seguridad de esta enmienda: la puerta HTTP es
estrictamente MENOS poderosa que la puerta por código.** Por código se puede inyectar un
`OptimalBinning` fiteado, un `LabeledFrame` o cualquier objeto; por HTTP sólo entra un
`pandas.DataFrame` leído de una tabla. Un artefacto que no sea una tabla plana **no se puede traer
por la interfaz**, y el trabajo que lo necesite seguirá declarándose no disponible en vez de abrir
un vector de deserialización. Es la respuesta directa a la tercera pregunta que D-ART-9 dejó
abierta.

### D-PUE-2 · La puerta HTTP no acepta claves de artefacto arbitrarias: acepta lo que el trabajo declara

Por código, `artifacts=` es general: cualquier `(dominio, clave)` válida. **Por HTTP es una
allowlist**, derivada del catálogo de trabajos. Un cuerpo que nombre una clave que ningún trabajo
declara → **422**, sin materializar nada.

Esto es D-JOB-7 al pie de la letra —«no es una puerta general: el trabajo dice qué acepta de
fuera»— y tiene una razón de seguridad propia: sin allowlist, un cliente local podría sembrar
cualquier clave del vocabulario de dominios y desplazar cálculos que el usuario cree que el motor
está haciendo. Con allowlist, la superficie es la que el catálogo publica y un gate mide.

**El campo es NUEVO, no se reutiliza `external_input`** (que es copy y vive bajo el gate de jerga
`test_ui_no_reimplementa_formulas_de_dominio` y el de copy público). El catálogo gana:

```python
"external_artifacts": (
    {
        "artifact": ("calibration", "calibrated_pd_frame"),   # máquina-legible
        "label": "La PD calibrada de tu modelo",              # copy (gate de jerga)
        "columns": (                                          # qué preguntar por clicks (D-PUE-5)
            {
                "config_path": "provisioning_internal.pd_column",
                "question": "¿Qué columna trae la probabilidad de incumplimiento?",
            },
        ),
    },
)
```

`artifact` y `config_path` son **datos**, no copy: se declaran exentos del gate de jerga con su
razón escrita, igual que `warning_codes` y `card.falta_dato` ya lo están (`AGENTS.md` §copy público).
`label` y `question` **sí** son copy y entran al gate.

### D-PUE-3 · La puerta **no añade ningún endpoint**: el artefacto se sube por `/api/upload` y viaja como `dataset_id`

Es la decisión de seguridad más importante de la enmienda, y la que hace que casi no haya superficie
nueva que auditar. El archivo del usuario sube por el endpoint que **ya existe**, y con él hereda,
sin escribir una línea:

| guarda existente | dónde |
|---|---|
| `Host` exacto contra el bind de loopback | `security.py:48` |
| `allow_live_execution` | `security.py:58` |
| `Origin` same-origin exacto | `security.py:64` |
| token efímero, comparado en tiempo constante | `security.py:69`, `runtime.py:72-83` |
| tope de 100 MiB | `datasets.py:282` |
| allowlist de formatos por sufijo | `datasets.py:288` |
| nombre en disco = `sha256` del contenido, nunca el del usuario | `datasets.py:293` |
| contención bajo `workdir/datasets`, symlinks incluidos | `datasets.py:427-445` |
| perfil de columnas medido en la ingesta (D-PERF-1) | `datasets.py:315-335` |

En el cuerpo de `/api/run` viaja entonces **una referencia, no un archivo**:

```jsonc
POST /api/run
{
  "config": { … },
  "dataset_id": "uploaded_<sha256…>",
  "external_artifacts": [
    {
      "artifact": ["calibration", "calibrated_pd_frame"],
      "dataset_id": "uploaded_<sha256…>",   // otro upload, o el MISMO si la tabla es una sola
      "key_column": "id_operacion"          // null ⇒ alineación por orden de filas (D-PUE-6)
    }
  ]
}
```

**Por qué no un endpoint nuevo `/api/artifacts`.** (a) Duplicaría el tope post-hoc de §1.3 en un
segundo canal; (b) sería una ruta nueva que clasificar, que es la clase de defecto que D-PUE-9
cierra; (c) el artefacto es, físicamente, exactamente lo mismo que un dataset: una tabla que hay que
materializar a parquet bajo el `workdir`. Un canal separado sería el mismo código con otra puerta.

**Ninguna ruta cambia de categoría de seguridad**, y esa es la prueba de que la puerta no amplía la
superficie de ataque: `/api/upload` y `/api/run` siguen en `MUTATING_PATHS`, `/api/preflight` sigue
en `CREDENTIALED_PATHS`, y no nace ninguna ruta.

### D-PUE-4 · Una sola tabla puede alimentar varios artefactos, y por eso los índices no se pueden desalinear

Para «validar un modelo existente» el motor pide dos claves —`scorecard.score` y
`calibration.calibrated_pd_frame`— y exige que compartan índice (§1.2). El usuario sube **una** tabla
con su llave, su partición, su target, su PD y su score, y la declara en las dos entradas de
`external_artifacts` con el mismo `dataset_id`. El backend siembra **el mismo `DataFrame`** en las
dos claves.

Que el frame lleve columnas de sobra no molesta a nadie: cada consumidor hace `.loc[:, […]]` con lo
que su config nombra (§1.1). Y el fallo de índices desalineados deja de ser alcanzable por esta vía.

Pedir dos archivos sigue siendo posible (dos `dataset_id` distintos); simplemente no es lo que la
interfaz propone.

### D-PUE-5 · El mapeo de columnas se hace **por clicks**, y escribe en los campos de config que ya existen

Decisión de Cami (2026-08-01): la tabla se pide en idioma de negocio **y** el usuario puede
resolverla sin escribir nombres a mano.

Los roles ya son campos de config —`provisioning_internal.pd_column`, `performance.score_column`,
`performance.pd_column`, `performance.partition_column`, `performance.target_column`,
`stability.pd_column`, `stability.partition_column`, `stability.score_column`—, así que el mapeo
**no inventa un canal paralelo**: pinta esos campos como selectores poblados con las columnas reales
del archivo de artefacto, en vez de como texto libre. El `column_map` de la §D-PUE-2 sólo dice
*qué campo de config pregunta por qué rol*, y la pregunta va en idioma de negocio (D-JOB-14).

*Qué preserva:* la paridad UI ↔ código (requisito 1 de la visión). Quien trabaja por código escribe
los mismos campos; el `config_hash` es el mismo por los dos caminos; y el preflight, la validación y
el formulario siguen viendo un config normal.

⚠️ **Hay un dato que NO es config: cuál columna del archivo es la llave.** Por código el artefacto
llega ya indexado, así que el motor nunca necesitó ese campo. Va en el cuerpo de la petición
(`key_column`), junto al `dataset_id`, **no en el config** — mismo criterio y mismo precedente que
`dataset_id` mismo, que la UI cablea a `data.load.source` sin que forme parte del config canónico
(`routes.py:450-459`, y `data.load.source` está excluido del `config_hash` desde `1.4.0`).

### D-PUE-6 · La alineación: por llave si la hay, **por orden de filas si no**, y siempre declarada

> 🔴 **CORREGIDA el 2026-08-02 — leer la §8 antes que esta sección.** Lo que sigue describe el
> diseño tal como se aprobó, y su primer punto resultó **falso al medirlo**: indexar sólo el frame
> externo no produce una alineación por etiqueta, produce un cruce silencioso. La decisión vigente
> es **D-PUE-6-bis** (§8). Esta redacción se conserva sin editar porque es lo que se implementó y
> explica los defectos que la corrección cierra.

Decisión de Cami (2026-08-01), tomada con el riesgo a la vista.

- **Con `key_column`:** esa columna pasa a ser el índice del frame sembrado. Es el modo correcto y el
  que la interfaz propone primero.
- **Sin `key_column` (`null`):** el frame entra con su `RangeIndex` y alinea **posicionalmente** con
  el dataset. Es lo que un CSV exportado de Excel produce sin trabajo extra.

Tres cosas son obligatorias en el modo posicional, y no son opcionales de implementación:

1. 🔴 **Si el número de filas no coincide con el del dataset, es error duro**, no aviso. Es el único
   desalineamiento detectable sin leer los datos —el perfil de la ingesta ya guarda `n_filas`
   (`datasets.py:323`)— y dejarlo pasar sería regalar el caso barato.
2. **El aviso es prominente en la pantalla**, antes de correr, y dice qué asume: que las filas de los
   dos archivos van en el mismo orden.
3. **La corrida se declara en el lineage** con un caveat propio, además del que D-ART-7 ya emite:
   `alineación posicional: <n> artefacto(s) externo(s) sin llave declarada`.

⚠️ **Contrapartida asumida y escrita, porque es real:** si las filas del archivo están reordenadas
respecto del dataset y el conteo coincide, la corrida termina **sin un solo error** con la PD de
cada cliente asignada a otro. El número sale plausible y es falso. Ésa es la razón de que el aviso y
el caveat sean obligatorios: quien firma el documento tiene que poder ver que se alineó por posición.

### D-PUE-7 · `/api/validate` deja de mentir, y no necesita credenciales nuevas para eso

`_pipeline_payload` pasa a recibir las **claves** declaradas en `external_artifacts` y a llamar
`nikodym.check_pipeline(model, artifacts=<claves>)`. D-ART-2 ya previó exactamente este uso:
*acepta claves sueltas además del mapping, porque comprobar no necesita el valor*.

**Por eso `/api/validate` no cambia de categoría de seguridad:** consume sólo `artifact` de cada
entrada e **ignora `dataset_id` y `key_column`**, así que no toca el disco ni materializa nada —
sigue siendo el endpoint «siempre 200» sin token que es hoy. El contrato del cuerpo es **el mismo**
en los tres endpoints (una sola forma que aprender), y lo que cambia es cuánto mira cada uno.

El payload REST gana además `inert_artifacts`, que hoy se calcula y se tira (§1.5):

```jsonc
{ "executable": true, "steps": [ … ], "message": null, "inert_artifacts": [["scorecard", "score"]] }
```

### D-PUE-8 · El preflight comprueba lo que puede **sin leer los datos**, y dice qué no comprobó

`POST /api/preflight` extiende su veredicto al insumo externo, **respetando D-PRE-1** (el preflight
no lee los datos). Con el esquema del parquet y el perfil de la ingesta alcanza para:

- que las columnas mapeadas **existan** en el archivo de artefacto (esquema del parquet);
- que la `key_column` sea **única** — el perfil ya guarda `n_unicos` por columna (`datasets.py:327`),
  así que `n_unicos == n_filas` responde la pregunta sin abrir el archivo;
- que el **conteo de filas** coincida, en el modo posicional (D-PUE-6.1).

⚠️ **Lo que el preflight NO puede comprobar, y se declara en vez de callarse:** que las etiquetas de
la llave **cubran** el índice del dataset. Eso exige comparar valores, o sea leer los datos, y
D-PRE-1 lo prohíbe. Lo verifica el motor al correr, con mensajes que ya existen y son buenos
(`engine.py:239-242`, `performance/step.py:186-190`). Se declara aquí con su razón, mismo patrón que
D-PRE-4 con el alcance F1: una lista corta sin explicación se lee como cobertura total.

Sigue D-PRE-5: **avisa, no bloquea** — salvo el conteo de filas del modo posicional, que es error de
entrada.

### D-PUE-9 · Se cierra la CLASE: un gate estructural obliga a clasificar toda ruta nueva

Medido en §1.4: la carencia está escrita en `CLAUDE.md` pero nada la ejecuta, así que el defecto del
preflight —un endpoint que se coló sin token— se puede repetir con la suite entera en verde.

Nace `PUBLIC_PATHS` en `ui/security.py`: las rutas que **a propósito** no exigen credenciales, cada
una con su razón escrita al lado. Y un gate enumera las rutas reales del router construido y exige
que **cada una** esté en `MUTATING_PATHS`, `CREDENTIALED_PATHS` o `PUBLIC_PATHS`. Una ruta nueva sin
clasificar → **rojo**, con un mensaje que nombra la ruta y las tres categorías.

Se verifica **inyectando el defecto** (añadir una ruta y comprobar que el gate se pone rojo), como
exige la regla del repo: un gate que declara barrer una clase y no se prueba inyectando no prueba
nada.

⚠️ El gate compara el *template* de la ruta (`/api/report/{run_id}`), no la URL concreta, porque es
lo que expone el router. Las tres listas pasan a hablar ese vocabulario.

### D-PUE-10 · Lo que entró de fuera llega al informe, no sólo al lineage

D-ART-7 ya publica `injected_artifacts` y el caveat de determinismo en el `LineageBundle`, y la §6.3
de la enmienda de la puerta decidió que eso se publique en el anexo de auditoría del informe. Está
**sin cumplir**: hoy sólo viaja el caveat en texto (deuda anotada el 2026-08-01).

Se cierra aquí, y no es alcance ajeno: hasta ahora ninguna corrida de la interfaz podía tener
artefactos externos, así que la §6.3 no tenía casos. Con esta enmienda los tiene todos. Quien firma
un informe de validación tiene que poder leer qué entró de fuera y cómo se alineó — misma razón que
`git_dirty`.

### D-PUE-11 · Los dos trabajos pasan a `available`, y su motivo desaparece del catálogo

Decisión de alcance de Cami (2026-08-01): **los dos**, porque son el mismo mecanismo.

| trabajo | claves que declara | qué pide la interfaz |
|---|---|---|
| Provisión interna / LGD | `calibration.calibrated_pd_frame` **o** `model.raw_pd_frame` | una tabla con la PD por operación |
| Validar un modelo existente | `calibration.calibrated_pd_frame` **y** `scorecard.score` | una tabla con la PD, el score, la partición y el target |

⚠️ **La clave NO es constante para el primero:** `provisioning_internal` pide una u otra según
`pd_source` (`provisioning/internal/step.py:56-58, 199-201`). El catálogo declara **las dos** y la
interfaz pide la que corresponde al valor elegido en el config. Un catálogo que fijara una sola
clave se rompería en silencio al cambiar `pd_source`.

### D-PUE-12 · Lo que esta enmienda NO desbloquea

- **`LabeledFrame` y los demás artefactos no tabulares** siguen fuera por HTTP (D-PUE-1). El trabajo
  T7 completo del documento rector —«traigo mis scores, dame el informe de validación» con
  `validation` incluida— necesita `('data','labels')`, que es un `LabeledFrame` y no una tabla
  (medido en la §1.1 de la enmienda de la puerta). Aquí no entra, y no se promete: el trabajo
  «validar un modelo existente» de este catálogo declara `performance` y `stability`, **no**
  `validation`.
- **LGD modelada por regresión** sigue no disponible: le falta que el método interno pueda delegar en
  `LgdEngine` (D-JOB-11), que es capacidad de motor con su propio SDD.
- **`UiConfig.upload_max_mb`** se queda muerto o se conecta: es deuda anotada aparte y no se resuelve
  aquí de tapadillo. ✅ **Resuelto el 2026-08-02** (decisión de Cami): se conecta como fuente única
  y el tope se comprueba **antes** de traer el cuerpo a memoria. El §1.3 de esta enmienda queda
  cerrado.

### D-PUE-13 · Contrato SemVer: MINOR, y no rompe a nadie

- El cuerpo de `/api/run`, `/api/validate` y `/api/preflight` gana un campo **opcional**; omitirlo
  deja el camino byte a byte el de hoy.
- El payload de pipeline gana `inert_artifacts` con default `[]` → **extensión aditiva** (CT-3).
- El catálogo de trabajos gana `external_artifacts` y dos trabajos cambian de `status` — es contenido
  del catálogo, no forma del contrato.
- **Ningún `config_hash` se mueve** (D-JOB-9): el trabajo es navegación, y `key_column`/`dataset_id`
  no son config.
- Ninguna ruta cambia de categoría de seguridad; `PUBLIC_PATHS` **declara** el estado actual, no lo
  cambia.

---

## 3. Casos borde y errores

| caso | comportamiento | por qué |
|---|---|---|
| `external_artifacts` ausente o `[]` | idéntico a hoy | aditivo puro (D-PUE-13) |
| clave que ningún trabajo declara | **422**, sin materializar | allowlist (D-PUE-2) |
| clave que un paso activo produce | **422** con el mensaje de D-ART-4 (paso y clave nombrados) | ya lo levanta el núcleo antes del primer paso |
| clave inerte | corre; se declara en `inert_artifacts` y en el trail | D-ART-5, ahora visible por REST (D-PUE-7) |
| `dataset_id` del artefacto inexistente | **404**, igual que un dataset | misma vía, mismo error |
| `key_column` que el archivo no tiene | aviso del preflight; **422** al correr | el motor no puede indexar por lo que no existe |
| `key_column` que la cartera no declara como `index_col` | aviso del preflight; **422** al correr, nombrando las dos salidas | **D-PUE-6-bis** (§8): por etiqueta sólo con la llave en los dos lados |
| `key_column` con valores repetidos | aviso del preflight (por el perfil); el motor lo rechaza | `engine.py:231-235` ya tiene su mensaje |
| sin `key_column` y distinto nº de filas | **error duro**, antes de correr | D-PUE-6.1 |
| sin `key_column` y mismo nº de filas | corre, con aviso en pantalla y caveat en lineage e informe | D-PUE-6.2/6.3 |
| la llave no cubre el índice del dataset | el motor lo rechaza al correr, con su mensaje | el preflight no puede saberlo sin leer (D-PUE-8) |
| archivo que no es tabla (pickle renombrado a `.csv`) | lo rechaza el lector de pandas → **422** | D-PUE-1: nunca hay un `loads` de objeto |
| `allow_live_execution=false` | `/api/upload` y `/api/run` → 403; `/api/preflight` sigue vivo | sin cambios: comprobar no es correr |

---

## 4. Estrategia de tests (gates)

1. **El gate de la clase (D-PUE-9):** enumerar las rutas del router y exigir clasificación. Se
   verifica **inyectando** una ruta nueva sin clasificar y comprobando el rojo.
2. **El gate de la prohibición (D-PUE-1):** test estático sobre el fuente de `nikodym/ui/` que veta
   `pickle`, `joblib`, `dill`, `marshal`, `yaml.unsafe_load`, `Loader=yaml.Loader` y `Study.load`.
   Se verifica inyectando el import.
3. **Allowlist (D-PUE-2):** una clave fuera del catálogo da 422 **y no escribe nada** en el
   `workdir` — el mismo criterio que `test_preflight_exige_token_aunque_no_ejecute` ya aplica.
4. **Paridad `/api/validate` ↔ `/api/run` (D-PUE-7):** para el mismo `(config, claves)`,
   `executable` debe predecir si `/api/run` llega a `done`. En los dos sentidos, y con el control
   negativo de hoy (sin las claves, `executable=false`).
5. **Bidireccional sobre el catálogo (D-PUE-11):** todo trabajo `available` con
   `external_artifacts` declara claves que existen en el vocabulario de dominios, **y** todo trabajo
   con claves declaradas está `available` o dice por qué no. Los dos sentidos, o el gate deja pasar
   un trabajo que promete lo que no puede.
6. **`pd_source` (D-PUE-11):** cambiar `pd_source` cambia la clave que la interfaz pide. Un test que
   fije una sola clave sería verde y falso.
7. **Modo posicional (D-PUE-6):** conteo distinto → error duro; conteo igual → corre **con** el
   caveat en el lineage, verificado sobre un `Study` **guardado y recargado**, no sólo en memoria.
8. **Config opaco:** esta enmienda toca un consumidor nuevo de `NikodymConfig` → **debe declarar su
   política** en `test_seccion_opaca_invariante.py` (`comprobado` o `exento: <razón>`).
9. **End-to-end en vivo (Playwright, no sólo tests):** entrar por «Validar un modelo existente»,
   subir la tabla, mapear por clicks, llegar a «Corrida completada» con informe. Es el único gate que
   demuestra que la puerta sirve para algo — y las dos últimas sesiones dejaron escrito que lo que
   más vale sale de abrir la pantalla.
10. **Negativos de seguridad heredados:** los cuatro de `/api/upload` (`Host`, `Origin`, token,
    `allow_live_execution`) se ejercitan también con `external_artifacts` en el cuerpo.

---

## 5. Orden de implementación

D-PUE-9 (el gate de rutas, primero: es el que impide que lo demás se cuele mal) → D-PUE-2 (campo del
catálogo + su gate bidireccional) → D-PUE-3/4/6 (materialización desde `dataset_id`, índice y modo
posicional) → D-PUE-7 (`/api/validate` deja de mentir + `inert_artifacts` por REST) → D-PUE-8
(preflight del insumo externo) → D-PUE-5 (mapeo por clicks en el front) → D-PUE-10 (el informe) →
D-PUE-11 (los dos trabajos a `available`) → los diez gates de §4.

---

## 7. Lo que la implementación corrigió del diseño

Reabrir un SDD por feedback del código es barato; dejar que documento y código se separen en
silencio, no. Cuatro correcciones, todas medidas.

### 7.1 🔴 D-PUE-10 ya estaba cumplido, y la deuda que lo pedía era FALSA

El HANDOFF traía anotado que «`injected_artifacts` no llega al informe pese a la §6.3 de su
enmienda». **Medido sobre el HTML de una corrida real: llega.** El anexo de lineage lo publica
(`report/builder.py:255-257`), aparece en el documento con las claves íntegras, y ya tenía **dos
gates** que nadie miró antes de anotar la deuda: `test_report_builder.py:144` y
`test_report_renderer.py:157-158`.

Lo que **no** lo trae es `results.json` de la interfaz — que nunca serializó lineage, para ninguno
de sus campos, así que tampoco publica `git_dirty` ni los caveats. Eso es otra carencia, más
pequeña y de otra familia: el panel de resultados no muestra procedencia. Se deja anotada como
deuda **con su medición**, en vez de ampliar esta enmienda para cubrirla de tapadillo.

Quinta premisa heredada que sale falsa al medirla en dos sesiones seguidas. La regla ya escrita
—«un ítem de roadmap es hipótesis de alcance hasta que se mide contra el código»— vale igual para
una deuda anotada por uno mismo.

### 7.2 🔴 Indexar el catálogo por clave con un `dict` perdía entradas

`_preflight_insumos` construía `{clave: entrada}` recorriendo los trabajos. La PD calibrada la
declaran **tres** trabajos, cada uno con un campo de config distinto —`provisioning_internal.
pd_column` en uno, `performance.pd_column` en otro—, así que el dict se quedaba con la última y el
preflight no avisaba de nada. Lo encontró su propio test, no una lectura.

Se acumulan **todas** las entradas de cada clave. No produce falsos positivos, y la razón vale la
pena dejarla escrita: el campo de un trabajo que no es el actual vive en una sección **apagada**, y
ahí el lector del config devuelve `None`. El config activo filtra solo, sin que la capa de interfaz
tenga que saber por qué trabajo entró el usuario.

### 7.3 🔴 El selector de la llave pintaba su valor centinela crudo

`__por_orden__` se leía tal cual en el control, donde debía leerse «No tengo esa columna: usa el
mismo orden de filas». Es la trampa que el repo ya tenía documentada en otra forma —las opciones se
pintan con `String(option)`—: `Select.Value` muestra el **valor**, no el texto del item. Va con
render explícito.

**Sólo se vio abriendo la pantalla.** Ningún test podía cazarlo: vitest corre sin DOM, y el string
correcto estaba escrito en el `<SelectItem>` que el test habría inspeccionado.

### 7.4 `onJump` del preflight recibe el path, no el desajuste

Desde D-PUE-8 llegan por ese canal dos clases de aviso con vocabularios de `kind` distintos —el del
motor, que es un `Literal` cerrado, y el de la interfaz—. Pasar el objeto entero obligaba a falsear
el tipo de uno de los dos; pasar el path, que es lo único que los dos llamadores usaban, no.

### 7.5 Lo que la verificación en vivo destapó, y que no es de esta enmienda

- La primera corrida murió en `stability` por el eje temporal, y **el preflight ya lo había
  avisado** con su salto al campo: el aviso funcionó exactamente como D-INV-2 lo diseñó.
- **«Validar un modelo existente» hereda las decisiones obligatorias de `data`** —qué define a un
  malo, cómo se separa la muestra— aunque el usuario traiga su target y su partición **dentro** del
  archivo del modelo. Se contestan y la corrida llega a `done`, pero es fricción real. No se cambia
  aquí: las decisiones se reparten por sección (D-OBL-6) y acotarlas por trabajo es una decisión de
  alcance, no un arreglo.

---

## 8. Corrección de D-PUE-6 · el modo «con llave» estaba mal diseñado

> **Estado:** **APROBADA** (OK explícito de Cami, 2026-08-02), tras una revisión adversarial cruzada
> con Codex sobre `5ef2dff..cf79931`. **Decisión: D-PUE-6-bis**, que reemplaza el primer punto de
> D-PUE-6 y deja el resto en pie.

### 8.1 🔴 Lo que D-PUE-6 prometía y no era cierto

D-PUE-6 dice: *«Con `key_column`: esa columna pasa a ser el índice del frame sembrado. **Es el modo
correcto** y el que la interfaz propone primero.»* La implementación hace exactamente eso
(`routes.py:713` → `datasets.load_frame(..., key_column=…)`), y aun así **el modo no es correcto**:
indexa **sólo un lado**. La cartera conserva su `RangeIndex` salvo que el usuario haya declarado
`data.schema.index_col`, que es un campo distinto que nada obliga a llenar.

Medido, no razonado. Dos escenarios, y ninguno de los dos funciona:

| llaves | qué ocurre | quién se entera |
|---|---|---|
| **numéricas** (`id_operacion = 0,1,2…`) | coinciden **por accidente** con el `RangeIndex` y alinean en el orden equivocado | **nadie**: la corrida termina sin un solo error |
| **de texto** (`OP-0`, `OP-1`…) | no hay intersección; el motor rechaza | el usuario, con un mensaje del motor sobre filas faltantes |

Reproducción del primero: cartera `id_operacion=[1,0]`, artefacto `id_operacion=[0,1]` con
PD `[0.1,0.9]` → la operación `1` recibe `0.1` cuando le corresponde `0.9`. La verificación en vivo
de la sesión anterior no lo vio porque su fixture usaba llaves de texto, o sea el escenario ruidoso.

⚠️ **Y es peor que el modo posicional**, que D-PUE-6 presenta como el arriesgado: el posicional lleva
aviso en pantalla y caveat en el informe, y el «seguro» no avisa nada. Un modo silenciosamente
incorrecto es peor que uno correctamente declarado como aproximado.

⚠️ **Segundo defecto de la misma decisión:** al declarar llave se **omite** el control de conteo de
filas (`routes.py:714`, el `if key_column is None`). Con llave genuina eso es correcto —el artefacto
puede legítimamente tener más filas que la cartera y el motor comprueba cobertura—, pero combinado
con lo anterior deja el modo sin ninguna guarda.

### 8.2 D-PUE-6-bis · La alineación por etiqueta exige la llave en **los dos lados**

Decisión de Cami (2026-08-02), y su criterio explícito fue que el diseño tiene que servir a **dos
usuarios a la vez**: el que está probando algo rápido para ver qué da, y el que hace el modelo en
serio. De ahí que la regla sea dura pero la salida exista.

**La regla dura:** el motor alinea por etiqueta **sólo** cuando la cartera y el artefacto declaran la
**misma** llave. Nunca implícitamente. En concreto, con `key_column` declarada:

1. Si `data.schema.index_col` **coincide** con `key_column` → alineación por etiqueta, genuina.
   Es el modo correcto y el único que merece llamarse así. Medido: con los dos lados indexados, la
   operación `1` recibe su `0.9`.
2. Si **no coincide** (o `data` está activo sin `index_col`) → **422 antes de correr**, con un
   mensaje que nombra las **dos** salidas y no sólo el problema.
3. Si `data` está **apagado** —el trabajo que no pide cartera— la llave se acepta sin más: no hay
   índice contra el que cruzar, y la coherencia entre los dos artefactos externos ya la exige el
   motor (`performance/step.py:183-190`).

**La salida para quien está probando, y es la razón de que esto no sea un muro.** El usuario puede
decir «no quiero declarar identificador, sigue igual», y entonces la corrida se hace **en modo
posicional declarado**: con su aviso en pantalla, su error duro de conteo de filas y su caveat en el
lineage y el informe. Nunca se degrada a la alineación por etiqueta contra un índice no vinculado,
que es justamente la que cruza en silencio.

⚠️ **Esa salida NO añade contrato:** «continuar igual» es, literalmente, mandar `key_column: null`,
que es el modo posicional que D-PUE-6 ya definió. El cuerpo de la petición no gana ni un campo, y
la interfaz gana un botón, no una forma nueva que aprender. Se prefirió a inventar un
`align: "key" | "row_order"` por la misma razón que D-PUE-3 prefirió no abrir un endpoint: la
superficie que no nace no hay que auditarla.

### 8.3 Qué hace la interfaz, para que la regla dura no se note

Al elegir la llave del artefacto (el selector que D-PUE-5 ya pinta), la interfaz escribe **también**
`data.schema.index_col` con esa columna, si la cartera la tiene. El caso correcto pasa a ser el que
ocurre sin pedir nada. Si la cartera **no** trae esa columna, se dice en pantalla y quedan las dos
salidas honestas: elegir otra llave, o continuar por orden de filas con su aviso.

⚠️ `data.schema.index_col` **sí entra en el `config_hash`** —sólo `data.load.source` está excluido
(`hashing.py:38-46`)—, y por eso lo escribe **el formulario** y no el backend a espaldas del usuario.
Cablearlo en la petición, como se cablea `data.load.source`, habría hecho que el config ejecutado
dejara de ser el que el usuario ve y valida: exactamente la clase de defecto que el paquete D cerró.

### 8.4 El preflight lo avisa antes, sin leer los datos

D-PUE-8 se extiende: comparar `key_column` con `data.schema.index_col` es comparar **dos campos
declarados**, así que no toca los datos y respeta D-PRE-1 íntegro. El aviso viaja por el canal de
`external_mismatches` que D-PUE-8 ya abrió, con su salto al campo.

### 8.5 Contrato

Sigue siendo **MINOR** y **no rompe a nadie**: ninguna corrida que hoy funcione bien deja de
funcionar. Lo que cambia es que una corrida que hoy produce un resultado **falso** pasa a detenerse
con un mensaje, y una que hoy muere con jerga del motor se detiene antes y en idioma de negocio.
Ningún `config_hash` se mueve por este cambio: `index_col` lo escribe el usuario, y un config que ya
lo declaraba tiene el mismo hash que antes.
