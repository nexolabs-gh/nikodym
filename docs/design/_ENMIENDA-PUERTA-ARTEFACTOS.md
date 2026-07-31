# Enmienda SDD — la puerta de artefactos: traer un resultado ya calculado y seguir desde ahí

> **Estado:** **APROBADA en sus decisiones de fondo** (OK explícito de Cami, 2026-07-30). Ninguna
> línea de motor escrita, y **sin commitear hasta después del webinar** (esa misma noche).
> **Enmienda a:** SDD-01 §4/§6/§7 (`Study`, `ArtifactStore`, `LineageBundle`), SDD-05 (convenciones
> de API pública), y al alcance de
> [`_ENMIENDA-VALIDACION-PIPELINE.md`](_ENMIENDA-VALIDACION-PIPELINE.md) (D-PIPE-1…D-PIPE-6).
> **Decisiones:** D-ART-1 … D-ART-12.
> **Nodo de roadmap:** F1.1 de [`privado/FIGURA-Y-ROADMAP-2026-07-30.md`](../../privado/FIGURA-Y-ROADMAP-2026-07-30.md).
> **Autor / Fecha:** DanIA · 2026-07-30 (medido contra `main` = `c6513aa`).

---

## 0. La carencia que la origina

Nikodym sabe correr un pipeline de punta a punta. No sabe **entrar por la mitad**. Y entrar por la
mitad es lo que pide el trabajo con más valor comercial del roadmap (T7, «traigo mis scores, dame el
informe de validación»), más los dos que hoy no existen aislados (T3 LGD, T4 EAD).

La carencia **no es de capacidad del motor**. Es de superficie: la capacidad existe, está probada, y
el usuario de `pip install` no puede alcanzarla. Es literalmente la definición de *no entregado* que
el repo ya fijó — ver `AGENTS.md` §Decisiones fijadas, «instalable y usable».

### 0.1 Lo que se midió (2026-07-30, `main` = `c6513aa`)

Config del preset F1 con `data: null` —o sea, sin el paso que produce los cuatro artefactos que
`binning` exige—, resuelto **sin ejecutar ningún paso**:

```
config_hash                                   e63452ed89e0…

(1) store vacío        → ConfigError: "El paso 'binning' necesita 'frame', que produce
                         'data', y ningún paso anterior lo genera…"
(2) nikodym.check_pipeline → executable=False
(3) store sembrado a mano con ('data', frame|labels|splits|special)
                       → EJECUTABLE, 9 pasos:
                         binning → selection → model → scorecard → calibration →
                         performance → stability → validation → report
(4) sink del Study recién construido → NullAuditSink
```

**(3) es el hallazgo:** con los artefactos ya en el `ArtifactStore`, el paso que los produciría
desaparece del pipeline y la cadena entera queda ejecutable. No es una inferencia de lectura: es el
motor respondiendo. La mecánica está en `core/study.py:510` —`_validate_pipeline` siembra
`disponibles` con `set(self.artifacts.keys())` antes de recorrer los pasos— y `ArtifactStore.set` es
público desde SDD-01 (`core/artifacts.py:33`).

**Y ya hay dos precedentes de primera clase, no uno:**

| precedente | dónde | qué demuestra |
|---|---|---|
| `('data','input_frame')` | `data/step.py:44,101-111` | un paso que **acepta** su insumo por el store en vez de por disco, con mensaje de error que enseña la vía |
| `Study.load()` | `core/study.py:668-669` | el núcleo ya **repuebla** un store completo desde fuera de una corrida |
| la suite | 20+ archivos de `tests/unit/` inyectan con `artifacts.set(...)` | la vía está ejercitada de facto en todo el repo |

### 0.2 Dónde se corta

`nikodym.run(config)` construye el `Study` dentro de sí (`api.py:179`) y no acepta nada más. No hay
parámetro, no hay `Study` de entrada, no hay hueco. La UI llama exactamente a eso
(`ui/routes.py:408`). El precedente `input_frame` **tampoco es descubrible**: no aparece en
`README.md` ni en `docs_site/`; sólo en `docs/design/23-ui.md` y en el texto de un error que hay que
provocar para leer.

Resultado: la capacidad existe, está probada por la propia suite, y **es inalcanzable para quien
instala el paquete**.

---

## 1. Lo que la medición corrigió del plan escrito

Van diez veces en este repo. Tres correcciones antes de decidir nada:

### 1.1 🔴 «Los cuatro artefactos que `validation` exige son DataFrames planos» — **falso en uno**

El documento rector lo afirma (§B.4) y de ahí sale la estimación «trabajo mediano» para T7. Medido
sobre `validation/step.py:303-324`, las claves que compone `_requires_for` son:

| clave | tipo real | ¿plano? |
|---|---|---|
| `('calibration','calibrated_pd_frame')` | `DataFrame` | ✅ |
| `('data','labels')` | **`LabeledFrame`** — BaseModel con `frame`, `target_col`, `status_col`, `summary: TargetSummary` (`data/target.py:58-67`) | 🔴 **no** |
| `('stability','stability_metrics')` | `DataFrame` | ✅ |
| `('stability','psi_table')` | `DataFrame` | ✅ |
| `('performance','discriminant_metrics')` | `DataFrame` (sólo si `consume_performance=True`) | ✅ |
| `('provisioning_ifrs9','detail')` + `('…','staging')` + `('data','frame')` | sólo con `backtesting.enabled` | — |

**Consecuencia de alcance:** la puerta hace T7 *posible*, no *inmediato*. T7 necesita además un
adaptador que construya un `LabeledFrame` desde un CSV de `score/pd/target/fecha`. Eso es F4.1, no
esta enmienda, y esta enmienda no debe prometerlo (D-ART-11).

### 1.2 La identidad de la corrida deja de identificar el cálculo

`config_hash` es el SHA-256 del config computacional (`core/config/hashing.py:91`). Un artefacto
inyectado **no está en el config**. Luego dos corridas con el mismo config y artefactos distintos
—dos carteras, dos modelos, dos scorings— producen **el mismo `config_hash`**. Y de ese digest
cuelgan el lineage, el model card, el informe y el ancla de idempotencia de MLflow
(`(model_name, config_hash)`, `api.py:212-233`).

Esto no es un detalle: es el contrato central del producto («el pipeline integrado y reproducible»,
§1 del documento rector). Sin resolverlo, la puerta introduce corridas indistinguibles entre sí. Lo
resuelve D-ART-7.

### 1.3 El `data_hash` se cae solo, en silencio

`_build_lineage` inicializa `data_hash=None` (`core/study.py:563`) y **el único sitio que lo llena es
`DataStep._update_lineage`** (`data/step.py:114-117`). Si `data` no corre —que es justo el caso de
esta enmienda— el lineage sale con `data_hash=None`, y con él el model card y el informe. Un
entregable de validación sin `data_hash` no puede presentarse como reproducible. Lo resuelve
D-ART-8.

---

## 2. Decisiones

### D-ART-1 · La puerta es un parámetro de `nikodym.run`, no un `Study` armado fuera

```python
def run(
    config: NikodymConfig,
    *,
    artifacts: Mapping[ArtifactKey, Any] | None = None,
) -> Study: ...
```

`ArtifactKey` es `tuple[str, str]` y ya existe (`core/steps.py`). *Keyword-only* y con default
`None`: **aditivo puro**, ninguna llamada existente cambia.

**Por qué no aceptar un `Study` ya construido.** `run` es la superficie pública **única** de
ejecución (CT-4): ensambla el `AuditSink` compuesto y el inventario (`assemble_run`), y publica la
`ModelCard` en éxito. Admitir un `Study` de fuera obliga a decidir qué pasa si ya trae sink, si ya
corrió, o si su config no es el que se pasó — y crea un segundo camino de ejecución que habría que
mantener en paridad para siempre. Un `Mapping` no tiene estado.

### D-ART-2 · `check_pipeline` recibe la misma puerta, o las dos superficies se contradicen

```python
def check_pipeline(
    config: NikodymConfig,
    *,
    artifacts: Iterable[ArtifactKey] | Mapping[ArtifactKey, Any] | None = None,
) -> PipelineCheck: ...
```

Medido en §0.1: hoy el mismo config da `executable=False` en (2) y **corre** en (3). Sin este
parámetro, la función que existe para responder *«¿puedo correr esto?»* mentiría exactamente en el
caso que esta enmienda habilita — la familia que persiguen D-PRE-9 y D-INV-1 («todo bien», o aquí
«no se puede», sobre lo que no se miró).

**Acepta claves sueltas además del mapping** porque comprobar **no necesita el valor**: sólo consume
`.keys()`. Quien edita un formulario o valida un plan puede declarar *qué va a traer* sin tenerlo
todavía cargado. Se documenta que el valor, si viene, se ignora.

`Study.check_pipeline()` (el primitivo del núcleo) **no cambia de firma**: lee el store del propio
`Study`, que es donde ya vive la información.

### D-ART-3 · La inyección ocurre después de `set_audit_sink` y antes de `run()`

Orden obligatorio dentro de `run`:

```
study = Study(config)
study.set_audit_sink(sink)      # ← primero el sink
_inyectar(study, artifacts)     # ← después la inyección
study.run()
```

Medido en §0.1 (4): el sink de un `Study` recién construido es `NullAuditSink`. Inyectar antes
mandaría al vacío el evento `"artifact"` que `ArtifactStore.set` **ya emite** por cada escritura
(`core/artifacts.py:49-56`), con su `payload` `{domain, key, overwrite}`.

**Con este orden la procedencia se audita sin inventar un mecanismo**: el trail registra cada
artefacto que entró de fuera, con su clave y su marca de tiempo, por el mismo canal que registra los
que produjo el motor. Es la razón por la que esta enmienda no crea un `ProvenanceRecord` nuevo.

⚠️ Con el preset F1 (`audit: null`) el sink sigue siendo nulo y no hay trail — por eso la
trazabilidad **no descansa sólo aquí**, sino también en el lineage (D-ART-7), que existe siempre.

### D-ART-4 · Un artefacto que un paso activo también produce es un error de config, y se avisa antes de correr

Si una clave inyectada coincide con el `provides` de algún paso del pipeline resuelto, se levanta
`ConfigError` **antes del primer paso**, con el paso y la clave nombrados y la salida escrita
(apagar esa sección del config).

Hoy eso ocurre igual, pero **tarde y con otro disfraz**: `artifacts.set` sin `overwrite` levanta
`ArtifactExistsError` dentro del paso productor (`core/artifacts.py:44-47`), con todo el cómputo
anterior ya pagado y un mensaje que habla de sobrescritura, no de la contradicción real. Adelantarlo
es la misma familia que D-INV-1: la contradicción es del config y se puede saber antes.

**No se admite `overwrite`.** Un artefacto inyectado que el pipeline volvería a producir es una
ambigüedad sobre cuál de los dos vale, y esa ambigüedad viajaría al informe.

### D-ART-5 · Las claves se validan contra el vocabulario de dominios; una clave inerte se declara, no se ignora

- **Dominio desconocido** (no está en `_DOMAIN_MODULES`, `core/study.py:55-78`) → `ConfigError`, con
  la lista de dominios válidos. Un typo silencioso es el peor resultado posible: el paso se ejecuta
  igual y el usuario cree que inyectó.
- **Dominio válido, clave que ningún paso del pipeline requiere** → **no bloquea**, pero se registra
  en el trail y se declara en el veredicto de `check_pipeline`. Es un artefacto inerte: puede ser un
  typo de clave o material para un paso que se activará después.

**No hay allowlist central de `(dominio, clave)`.** Cada dominio ya declara lo suyo en `provides`, y
un registro central es el acoplamiento que D-INV-1 evita: crecería con cada dominio nuevo y se
desincronizaría en silencio (precedente medido: la constante triplicada de `TEMPORAL_CANDIDATE_NAMES`).

### D-ART-6 · El tipo del artefacto NO se valida en la puerta

Lo valida el consumidor, que es el único que conoce el contrato. **Precedente exacto y ya
implementado:** `data/step.py:101-111` comprueba que `input_frame` sea un `pandas.DataFrame` y
levanta `ConfigError` con el texto que enseña la vía correcta.

La alternativa —una tabla `(dominio, clave) → tipo` en el núcleo— obligaría a `core` a importar los
DTO de todos los dominios (`LabeledFrame`, `PartitionResult`, `MaskedFrame`, …), que es exactamente
lo que el núcleo liviano prohíbe (SDD-23 §4.1/§9) y lo que sostiene los 18 tests
`test_core_valida_<X>_como_blob_opaco_sin_importar_<X>`.

**Contrapartida asumida y declarada:** un tipo equivocado se detecta al ejecutar el paso consumidor,
no en la puerta. Se mitiga con el mensaje del consumidor, no con validación central.

### D-ART-7 · La identidad: el lineage declara qué entró de fuera; `config_hash` no se toca

Extensión **aditiva** de `LineageBundle` (`core/lineage.py:26`):

```python
injected_artifacts: tuple[str, ...] = ()   # "dominio.clave", orden canónico (sorted)
```

Y un caveat de determinismo por corrida con artefactos inyectados, por el canal que ya existe
para esto (`determinism_caveats`, el mismo que usa `git_dirty`):

> `artefactos inyectados desde fuera de la corrida: <n> clave(s) no reconstruibles desde config+datos`

**Por qué no entra al `config_hash`.** (a) Recalcularía la identidad de **todas** las corridas
existentes, y el precedente del repo es que eso va en minor con nota de contrato (`1.4.0`, `1.8.0`)
— pagar ese costo para el caso que no usa la puerta es desproporcionado. (b) El contenido de un
artefacto arbitrario **no es hasheable en general**: un `DataFrame` sí (`data_hash` existe), un
`LabeledFrame` o un `OptimalBinning` fiteado no, sin inventar una serialización canónica por tipo.

**Por qué el nombre de la clave basta.** La pregunta que el lineage debe contestar no es «¿qué
contenía?» sino «¿esta corrida es reconstruible desde su config y sus datos?». Con una sola clave
inyectada la respuesta es **no**, y eso es lo que hay que publicar. Es la misma semántica exacta que
`git_dirty`: no se guarda el diff, se declara que no es reconstruible.

⚠️ `LineageBundle` tiene `extra="forbid"`: el campo lleva default `()` para que un `lineage.json`
escrito **antes** de esta enmienda siga recargando (mismo criterio que D-ERR-7 con `RunError`). Un
`lineage.json` nuevo leído por una versión vieja falla — eso ya es así y no se promete lo contrario.

### D-ART-8 · `data_hash` con `data` apagado: se adopta del store si está, y si no se declara ausente

Al cerrar el lineage, si el store trae `('data','data_hash')` **y** el lineage lo tiene en `None`, se
adopta. La clave ya existe en el contrato del dominio (`DATA_ARTIFACTS`, `data/step.py:36-43`), así
que **inyectarla es legal hoy** y no hay que inventar campo.

Si no está, `data_hash` queda `None` y se suma el caveat:

> `data_hash ausente: la corrida no ejecutó el paso de datos`

Sin esto, la evidencia de reproducibilidad se pierde **en silencio**, que es el modo de fallo que
este repo ya pagó tres veces (el `save`→`load` de `1.7.0`, los dos `config_hash` de `1.8.0`, el
`compatible=True` del preflight).

### D-ART-9 · La puerta es de código en esta enmienda; la interfaz queda fuera, con su razón

`ui/routes.py:408` compone el config y llama `nikodym.run(resolved)`. Abrirla por HTTP exige decidir
**cómo viaja un artefacto por la red**: formato de serialización, tope de tamaño (hoy 100 MiB con el
buffer completo antes del chequeo, `routes.py:602`), y el vector de deserialización que
`Study.load(trust=False)` rechaza a propósito (`core/study.py:648-652`). Eso es un diseño de
seguridad propio, y es el trabajo T7/F3, no éste.

Se declara aquí para que la ausencia **no se lea como olvido** — mismo patrón que D-PRE-4 con el
alcance F1 del preflight.

### D-ART-10 · La documentación es parte del entregable, no un extra

El precedente `input_frame` demuestra el modo de fallo: existe desde SDD-02, funciona, y es
inalcanzable porque nadie lo documentó fuera de `docs/design/`. Esta enmienda **no está cumplida**
hasta que la puerta aparezca en `docs_site/` con un ejemplo ejecutable y en el docstring de
`nikodym.run`, con las tres cosas que el usuario necesita saber: qué claves acepta cada dominio
(`provides`), que hay que apagar la sección productora, y que la corrida queda declarada como no
reconstruible.

### D-ART-11 · Lo que esta enmienda NO desbloquea sola

Medido en §1.1. La puerta es condición **necesaria** de T7/T3/T4, no suficiente:

- **T7** necesita además un adaptador CSV → `LabeledFrame` + `calibrated_pd_frame`.
- **T3/T4** necesitan que el step de IFRS 9 **publique** `('provisioning_ifrs9','lgd')` y `('…','ead')`,
  que hoy no publica (F4.4 del roadmap).
- El **informe** de una corrida parcial no está medido en esta enmienda: `ReportStep` deriva sus
  `requires` filtrando `REPORT_REQUIRED_CARDS` por las cards presentes (`report/step.py:81`), así que
  *probablemente* degrada bien — **no verificado**, y no se afirma.

### D-ART-12 · Contrato SemVer: MINOR, y no rompe a nadie

- Firma pública ampliada de forma **aditiva** (parámetro *keyword-only* con default `None`).
- `LineageBundle` gana un campo con default → **aditivo** (CT-3, extensión sin ruptura).
- **Ninguna corrida existente cambia de resultado ni de `config_hash`**: sin `artifacts=`, el
  camino es byte a byte el de hoy.
- El pipeline F1 sigue estable bajo SemVer 1.x; la orquestación ya está declarada experimental
  (SDD-01 encabezado), y esto la amplía dentro de esa declaración.

---

## 3. Contrato de uso (ilustrativo, no código final)

```python
import nikodym

# 1. Comprobar antes de tener los objetos cargados: sólo las claves.
veredicto = nikodym.check_pipeline(
    config,                                   # con data: null
    artifacts=[("data", "frame"), ("data", "labels"),
               ("data", "splits"), ("data", "special")],
)
assert veredicto.executable          # sin `artifacts=`, esto sería False

# 2. Correr entrando por la mitad.
study = nikodym.run(config, artifacts={
    ("data", "frame"):  mi_frame,
    ("data", "labels"): mi_labeled_frame,
    ("data", "splits"): mi_particion,
    ("data", "special"): mi_masked_frame,
})

assert study.run_context.status == "done"
study.run_context.lineage.injected_artifacts
# → ('data.frame', 'data.labels', 'data.special', 'data.splits')
study.run_context.lineage.determinism_caveats
# → ['artefactos inyectados desde fuera de la corrida: 4 clave(s) no reconstruibles…',
#    'data_hash ausente: la corrida no ejecutó el paso de datos']
```

---

## 4. Casos borde y errores

| caso | comportamiento | por qué |
|---|---|---|
| `artifacts=None` / `{}` | idéntico a hoy, sin caveat ni campo poblado | aditivo puro (D-ART-12) |
| dominio inexistente | `ConfigError` antes de correr, con los dominios válidos | un typo silencioso es el peor resultado (D-ART-5) |
| clave que un paso activo produce | `ConfigError` antes de correr, nombrando paso y clave | D-ART-4 |
| clave que ningún paso requiere | corre; se declara inerte en el trail y en `check_pipeline` | D-ART-5 |
| tipo equivocado | lo rechaza el paso consumidor con su mensaje | D-ART-6 |
| se inyecta todo el pipeline (0 pasos) | `run` termina `done` con 0 pasos y el lineage completo | no es un error: es una corrida vacía legítima, y el motor ya lo soporta (`steps=[]`) |
| `artifacts=` + `data:` activo | `ConfigError` de D-ART-4 si colisiona; si no colisiona, conviven | el caso `input_frame` es exactamente éste y ya funciona |

---

## 5. Estrategia de tests (gates)

1. **El gate de la clase:** un test que **inyecta el defecto** —quitar el parámetro— y por tanto
   falla con el código de hoy. Sin eso no prueba nada (lección `test_copy_del_formulario.py`: su
   primera versión daba verde recorriendo cero campos).
2. **Paridad `run` ↔ `check_pipeline`**: para el mismo `(config, claves)`, `executable` de
   `check_pipeline` debe predecir si `run` llega a `done`. En los dos sentidos.
3. **El caveat y el campo del lineage**, verificados sobre un `Study` **guardado y recargado**
   (`save`→`load`), no sólo en memoria: es donde vive la familia de defectos de `1.7.0`.
4. **La procedencia en el trail**: con un `JsonlAuditSink` real, los eventos `"artifact"` de las
   claves inyectadas están presentes y llevan `overwrite: false`.
5. **Config opaco**: la puerta debe comportarse igual con las secciones de dominio como `dict`. El
   estado opaco es el **default** (`test_seccion_opaca_invariante.py`), y esta enmienda toca un
   consumidor nuevo de `NikodymConfig` → **debe declarar su política** en ese gate (`comprobado` o
   `exento: <razón>`).
6. **`data_hash` adoptado del store**, y ausente con su caveat cuando no se inyecta.
7. **Un test end-to-end** con el preset F1 partido en dos: correr entero, guardar los cuatro
   artefactos de `data`, y volver a correr desde `binning` inyectándolos → **mismos coeficientes**.
   Es el único que demuestra que la puerta sirve para algo.

---

## 6. Decisiones cerradas por Cami (2026-07-30)

1. **La clave inerte avisa, no bloquea** (D-ART-5), por coherencia con D-PRE-5 y D-INV-3. ⚠️
   Contrapartida asumida: un typo de clave produce una corrida que **ignora lo inyectado y sale
   adelante**. Por eso el aviso tiene que llegar a las dos superficies —el trail y el veredicto de
   `check_pipeline`—, no sólo al trail: el trail no existe con el preset F1 (`audit: null`).
2. **Entra en `1.11.0` junto con la fuga del target.** La nota del CHANGELOG debe separar las dos:
   **ésta no mueve ningún número** (aditiva pura, sin `artifacts=` el camino es byte a byte el de
   hoy); la otra sí. ⚠️ El release sigue exigiendo **OK específico de Cami** y auditoría adversarial
   previa.
3. **`injected_artifacts` se publica en el anexo de auditoría del informe.** Misma razón que
   `git_dirty`: quien firma el documento tiene que saber qué entró de fuera. Es superficie donde el
   dato es la evidencia, así que las claves van íntegras, sin sanear.

**Orden de implementación** (a partir del 2026-07-31, ninguna línea escrita todavía):
D-ART-1/2 (las dos firmas, juntas o `check_pipeline` miente) → D-ART-3/4/5 (inyección, colisión,
clave inerte) → D-ART-7/8 (lineage, caveats, `data_hash`) → D-ART-10 (documentación, que es parte
del entregable) → los siete gates de §5.
