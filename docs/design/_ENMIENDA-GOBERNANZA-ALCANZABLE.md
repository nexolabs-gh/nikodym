# Enmienda — la gobernanza tiene que ser ALCANZABLE desde `pip install`

> Estado canónico: **APROBADA por Cami el 2026-08-28. D-GOB-1…8 IMPLEMENTADAS y gateadas.
> D-GOB-9 (recaptura de la demo) NO ejecutada: conserva su OK propio.**
> El estado y la interpretación finales los manda
> [`DECISIONES-VIGENTES.md`](DECISIONES-VIGENTES.md) §D-GOB, que además recoge **una corrección
> medida a §D-GOB-8** (abajo) y los abiertos que quedaron. Este documento conserva el razonamiento
> y las mediciones de la propuesta, incluido lo que después resultó inexacto.
>
> ⚠️ El texto que sigue es el de la propuesta, sin reescribir. Donde diga «sigue vacío», «hoy no
> existe» o «se propone», léase en presente del 2026-08-27.
>
> Nace del **bloqueador 3** del censo de módulos del 2026-08-26: *«la gobernanza —el titular del
> README— no existe en ninguna ruta entregada»*. El censo midió sobre
> `cd534025f8ca803a32f7685d33270755123b7206`; **todo lo que sigue está remedido sobre
> `ddb616fe8efd253f056a5b6e6f4ae00e6717987e` (tag `v1.12.0`)**, que es el árbol vigente.
>
> Decisiones propuestas: `D-GOB-1…D-GOB-9`. Prefijo `D-GOB` verificado libre contra los 63 prefijos
> `D-*` en uso.
>
> Enmienda a **SDD-01 §6** (namespace canónico de métricas), **SDD-03 §6/§7.1.d** (layout del run y
> fuente de métricas del model card) y **CT-2** (puerta de extensión tipada). No toca el motor de
> riesgo, no cambia ningún cálculo y —salvo D-GOB-8, que se declara aparte— **no mueve ningún
> `config_hash`**.

---

## 0. La premisa del censo, remedida: cierta en el qué, incompleta en el porqué

El censo enunció cuatro hechos. **Los cuatro son ciertos hoy** y se reproducen abajo con su
medición. Pero el censo también dejó dicho que la causa raíz *«no tiene dueño asignado»* y que la
salida es *«llenar `study.results['metrics']` **o** cambiar por enmienda la fuente del
`ModelCardBuilder` a `study.artifacts`»*. Medir el árbol refuta esa disyuntiva y estrecha el trabajo:

| afirmación | veredicto | evidencia medida |
|---|---|---|
| los 4 presets traen `audit`/`governance`/`tracking` en `None` | **CIERTA** | los 4, no 3: ver §1.3 |
| ningún paso llena `study.results['metrics']` | **CIERTA** | 0 escritores en `src/`; `results == {}` tras F1 completa: §1.1 |
| nada del layout de SDD-03 §6 se escribe a disco | **CIERTA, y es peor** | no es que falten 4 archivos: **no existe el directorio de corrida**: §1.4 |
| los fixtures de la demo traen `model_card: null` | **CIERTA** | 3 archivos, línea 5: §1.5 |
| *(implícita)* la fuente de métricas está por decidir entre `results` y `artifacts` | 🔴 **FALSA** | **los dos consumidores ya están escritos contra `results['metrics']`**, y uno de ellos flexiona el namespace canónico entero: §2.1 |
| *(implícita)* la forma del payload por dominio está sin decidir | 🔴 **FALSA en 9 de 13 dominios** | la puerta CT-2 `metric_sections` **ya está implementada** en 9 `CardSection`, con validador y copia profunda: §2.2 |
| *(no dicha)* bastaría con volcar los escalares de cada card | 🔴 **FALSA** | AUC/KS/Gini/PSI **no son campos escalares de ninguna card**; volcarlas publicaría `n_deciles` y `pdo` como «las métricas del modelo»: §2.3 |

Eso cambia el trabajo. No hay que elegir una fuente ni inventar una forma: hay que **escribir el
único extremo que falta —el productor— y fijar la forma exacta que los dos consumidores ya
esperan**, que hoy no coinciden entre sí (§2.1). El resto de la cadena está construido.

Corrección menor de paso: el comentario de `core/study.py:253` dice *«los **tres** [presets] traen
`governance: null`»*. Son **cuatro** (§1.3). Se corrige al implementar.

---

## 1. El defecto, medido

Todas las mediciones de esta sección se hicieron sobre `ddb616f` con el intérprete del checkout,
corriendo el pipeline **F1 completo y real** (`nikodym.run`, `status == "done"`) sobre el frame de
comportamiento de `tests/unit/_ui_f1.py`.

### 1.1 El canal de métricas está vacío y no tiene ni un solo escritor

```
status            : done
study.results     : {}
results == {}     : True
```

`rg "\.results\[" src/nikodym/` devuelve **dos** coincidencias, y las dos son **lecturas
defensivas** dentro del propio consumidor (`governance/model_card.py:242` y `:260`, los mensajes de
error). **Cero escrituras.** No es que el canal esté mal llenado: no lo llena nadie.

El model card construido sobre esa corrida real, con gobernanza válida:

```
metrics          : {}
metric_sections  : {}
decisions        : 0
```

Un model card sin métricas y sin decisiones no cumple el bloque que SR 11-7 exige y que
`AGENTS.md` y el README venden como titular.

### 1.2 Los consumidores, remedidos

- `governance/model_card.py:189-190` — `metrics=_metrics(study.results)` y
  `metric_sections=_metric_sections(study.results)`. Coordenadas del censo **confirmadas sin
  desplazamiento**.
- `tracking/sink.py:47` — `self.recorder.log_metrics(self.study.results)`, en `run_end`.
  Confirmada sin desplazamiento.

### 1.3 La gobernanza está apagada de fábrica en los cuatro presets

Medido llamando a `get_preset(id)` para cada id de `list_presets()`:

```
f1-estandar-consumo            -> {'audit': None, 'governance': None, 'tracking': None}
f3-provisiones-consumo         -> {'audit': None, 'governance': None, 'tracking': None}
f4-ifrs9-retail                -> {'audit': None, 'governance': None, 'tracking': None}
f5-provision-interna-generica  -> {'audit': None, 'governance': None, 'tracking': None}
```

Las tres claves salen del mismo bloque compartido, `ui/presets.py:491-493`.

### 1.4 No falta el contenido del directorio de corrida: falta el directorio

SDD-03 §6 fija `runs/<run_id>/` con `audit_trail.jsonl`, `environment.json`, `scenario_log.jsonl`,
`model_card.json` y `model_card.md`. La búsqueda de esos cuatro nombres en `src/`, `scripts/` y
`web/src` devuelve **una** coincidencia, y es el *default* de un campo de config
(`governance/config.py:95`), no una escritura.

Pero el hueco es más ancho que «faltan cuatro archivos». Medido con `cwd` en un directorio temporal
vacío:

```
cwd tras run(): VACÍO
run_id: 3e40f5ca183f40ed84a1e0802eb9e346
```

**`nikodym.run()` no crea ningún directorio de corrida.** `Study.save(path)` (`core/study.py:768`)
sí escribe un layout —`config.yaml`, `run_metadata.json`, `lineage.json`, `artifacts/`— pero es una
llamada **explícita y separada**, y su directorio lo elige quien llama, no el `run_id`. El layout de
SDD-03 §6 no tiene hoy dónde anclarse: no es que esté mal escrito, es que **no existe la carpeta que
lo contendría**. Decidir eso es D-GOB-6, y es más que un detalle de implementación.

Consecuencia colateral ya medible: `api.py:319` abre
`JsonlAuditSink(Path(audit_cfg.trail_filename), …)` con la ruta **relativa al `cwd`**, mientras
`audit/config.py:22` describe ese campo como *«nombre del JSONL dentro del directorio del run»*. Dos
corridas desde el mismo `cwd` concatenan sus trails en el mismo archivo *append-only*, que es
exactamente lo que SDD-03 §8 prohíbe («una instancia por run»).

### 1.5 La demo publicada muestra cero de su titular

`web/src/fixtures/demo/{results,results-f1,results-ifrs9}.json`, línea 5 de cada uno:
`"model_card": null`. Los tres. La cadena que lo produce es la de §1.3 → `api.py:330`
(`NullAuditSink`) → `ui/serializers.py:609-623` (`_serialize_model_card` devuelve `None` si no hay
gobernanza).

---

## 2. Lo que el censo no vio: la mitad de la cadena ya está construida

Esta sección es la que cambia el tamaño del trabajo, y por eso va antes de las decisiones.

### 2.1 Los dos consumidores ya leen el namespace canónico — y **no se ponen de acuerdo en su forma**

`tracking/recorder.py:75-102` no es un volcado ciego. Su `_metric_items`:

- línea 77: `source = results.get("metrics", results)` — **desenvuelve el namespace canónico de
  SDD-01 §6 por su nombre exacto**;
- líneas 84-96: recorre en profundidad y aplana los `Mapping` anidados a claves punteadas
  (`performance.auc_oot`), separando finitos de no finitos;
- líneas 100-102: todo lo que no es `metrics` —incluido `metric_sections`— va a `results.json` como
  artefacto.

Es decir: **`tracking` ya está escrito contra el contrato de SDD-01 §6**, y acepta forma anidada.

`governance/model_card.py:238-253` (`_metrics`) exige lo contrario: `dict[str, float]` **plano**, y
levanta `GovernanceError` ante cualquier valor no numérico, incluido un `dict`.

Probado contra los dos consumidores sobre la misma corrida real:

| forma de `results["metrics"]` | `governance` | `tracking` |
|---|---|---|
| anidada `{"performance": {"auc_oot": 0.78}}` | 🔴 `GovernanceError: La métrica 'performance' debe ser numérica finita.` | ✅ `{'performance.auc_oot': 0.78}` |
| plana `{"performance.auc_oot": 0.78}` | ✅ `{'performance.auc_oot': 0.78}` | ✅ `{'performance.auc_oot': 0.78}` |

**Sólo la forma plana con clave punteada satisface a los dos sin tocar ninguno.** Esto no es una
preferencia estética: es una contradicción latente y medida entre dos consumidores del mismo
contrato, que hoy nadie nota **porque el canal está vacío**. Llenarlo con la forma anidada —la que
`tracking` sugiere— rompería el model card en tiempo de ejecución. Es D-GOB-2.

### 2.2 La puerta CT-2 ya está implementada en 9 de 13 dominios

`metric_sections` no es un campo por inventar. Censo estático de las `*CardSection` del árbol:

| tiene `metric_sections` (9) | no lo tiene (4) |
|---|---|
| `calibration`, `explain`, `ml`, `model`, `performance`, `scorecard`, `stability`, `tuning`, `validation` | `binning`, `data`, `eda`, `selection` |

Y no son campos decorativos: cada uno trae `_COPY_ON_ACCESS_FIELDS`, un
`@field_validator(mode="before")` que copia en profundidad y, en varios dominios
(`survival`, `markov`, `forward`, `stress`), un `_with_required_metric_sections()` que impone claves
obligatorias. Los docstrings citan **«Cumplimiento CT-2»** literalmente.

Además hay ya **un productor vivo**: `performance/evaluator.py:272` puebla
`metric_sections={"discrimination": {...}}`, y se observa lleno en la corrida real
(`metric_sections claves=['discrimination']`).

O sea: la forma del payload estructurado **por dominio** ya está decidida e implementada. Lo que no
existe es la **agregación** hacia el namespace que `governance`/`tracking` leen.

### 2.3 Volcar los escalares de las cards sería una respuesta incorrecta

La salida aparentemente barata —«que un agregador copie los campos numéricos de cada card»— publica
las métricas equivocadas. Censo estático de campos escalares declarados:

| card | escalares numéricos declarados |
|---|---|
| `PerformanceCardSection` | `n_deciles` |
| `ScorecardCardSection` | `pdo`, `target_score`, `target_odds`, `factor`, `offset`, `n_variables`, `overrides_count`, `min_score?`, `max_score?` |
| `StabilityCardSection` | `psi_bins`, `stable_threshold`, `review_threshold`, `worst_csi_value?` |
| `ModelCardSection` | `n_candidates`, `n_final_features` |

**AUC, Gini, KS y PSI no aparecen.** Viven en estructuras anidadas que sólo el dominio sabe reducir:
`PerformanceCardSection.max_metrics_by_partition` (`dict` por partición), el frame
`("performance","discriminant_metrics")`, y `StabilityCardSection.max_psi_by_comparison`. Medido en
la corrida real:

```
max_metrics_by_partition = {"desarrollo": {"auc": …, "gini": …, "ks": …},
                            "holdout":    {…},  "oot": {…}}
```

Un agregador genérico publicaría `scorecard.pdo = 20.0` y `performance.n_deciles = 10` como «las
métricas del modelo» y omitiría el AUC. La reducción —*¿qué partición? ¿la peor? ¿la `oot`?*— es
**conocimiento de dominio**, y por eso la decide cada SDD, no un agregador central. Es D-GOB-1.

---

## 3. Las decisiones

### D-GOB-1 — El productor es el paso, por un método declarado; el escritor es `core`

`Step` gana un método **opcional** `metrics() -> Mapping[str, float]` y
`metric_sections() -> Mapping[str, Any]`, con default vacío en la clase base. Tras `execute`,
`Study.run` llama a ambos y escribe el resultado bajo el namespace canónico, prefijando por el
`domain` del paso. Un paso que no los implemente no aporta nada y no falla.

Por qué así y no de otra forma:

- **Respeta SDD-01 §6 al pie de la letra** («cada SDD productor de métricas escribe bajo este
  namespace»): la lista de claves la posee el dominio, que es quien sabe reducir §2.3.
- **`core` sigue siendo *domain-agnostic***. Llama a un método del `Protocol`, exactamente como ya
  hace con `requires`/`provides` (CT-1). No importa ningún dominio ni conoce el mapa no uniforme de
  claves de card que hoy vive en `report/builder.py:75-103` y se replica a propósito en
  `ui/serializers.py:45-66`.
- **El punto de escritura es único y auditable**: ningún paso puede pisar el namespace de otro ni
  corromper su forma, porque el prefijo lo pone `core`.
- **No toca los dos consumidores**, que ya están escritos (§2.1).

Alternativas descartadas, con motivo:

| alternativa | por qué se descarta |
|---|---|
| cada paso escribe `study.results` directamente dentro de `execute` | sin punto único de escritura, el prefijo y la forma dependen de la disciplina de 13 pasos; no hay dónde poner el gate |
| agregador central en `core` que lea las cards | mete conocimiento de dominio en `core` (el mapa no uniforme de claves) y publica las métricas equivocadas (§2.3) |
| cambiar la fuente del `ModelCardBuilder` a `study.artifacts` | abandona el namespace canónico que `tracking` ya flexiona (§2.1) y deja a `tracking` leyendo `{}`: arregla un consumidor y no el otro |

### D-GOB-2 — `metrics` es **plano**, con clave `"<dominio>.<metrica>"` y `float` finito

`study.results["metrics"]: dict[str, float]`. La clave la compone `core` como
`f"{domain}.{nombre}"`; el dominio devuelve sólo `nombre`. Valores `float` finitos; `None`, `NaN` e
`inf` **se omiten**, no se publican como `0.0` ni rompen la corrida (una métrica no evaluable es
una ausencia honesta, y `not_evaluable` ya es un estado de primera clase en
`performance.discriminant_metrics`).

Es la única forma que los dos consumidores aceptan hoy sin modificarlos (§2.1, tabla medida).

### D-GOB-3 — `metric_sections` es **un nivel por dominio**, tomado de la puerta CT-2 que ya existe

`study.results["metric_sections"]: dict[str, dict[str, Any]]`, con
`results["metric_sections"][domain] = card.metric_sections` cuando esa sección no está vacía. Sin
aplanar, sin fusionar entre dominios, copiado en profundidad (los DTO ya lo hacen en su validador).
`governance` lo copia tal cual; `tracking` lo manda entero a `results.json`.

### D-GOB-4 — Cada SDD de dominio declara su lista de métricas, cerrada y gateada

La lista es **corta y explícita**, no «todo lo numérico». Cada SDD de dominio la publica en su §6 y
un gate la ata al código en ambos sentidos (D-GOB-9). Conjunto inicial propuesto para el pipeline
F1, derivado de lo medido en §2.3:

| dominio | métricas propuestas |
|---|---|
| `data` | `n_rows`, `n_features`, `bad_rate` |
| `binning` | `n_variables_binned`, `n_variables_skipped` |
| `selection` | `n_candidates`, `n_selected`, `max_abs_correlation_after_selection` |
| `model` | `n_final_features` |
| `scorecard` | `n_variables` |
| `calibration` | `target_pd`, `calibrated_mean_pd_dev`, `observed_default_rate_dev` |
| `performance` | `auc_<partición>`, `gini_<partición>`, `ks_<partición>` por cada partición evaluable |
| `stability` | `worst_psi`, `worst_csi_value` |

`performance` y `stability` son los que exigen reducción real; el resto es proyección directa. Los
dominios fuera de F1 (`ml`, `tuning`, `explain`, `validation`, `survival`, `markov`, `forward`,
`stress`, `provisioning*`) declaran la suya en su propio SDD cuando se aborden: la puerta queda
abierta y vacía, que es honesto, no un hueco.

**Esta tabla es la que más merece la revisión de Cami**, porque es la que aparecerá impresa en cada
model card publicado.

### D-GOB-5 — Los 4 dominios sin `metric_sections` no reciben el campo ahora

`binning`, `data`, `eda` y `selection` (§2.2) publican escalares en `metrics` y **nada** en
`metric_sections`. Añadirles el campo sería aditivo y barato, pero hoy no hay payload estructurado
que poner dentro, y fabricar uno para llenar el hueco es inventar. Se añade cuando su SDD declare
qué va dentro.

### D-GOB-6 — El directorio de corrida existe sólo si el llamador lo pide

Éste es el punto donde la enmienda **necesita una decisión de producto**, no una técnica: hoy
`run()` no escribe nada (§1.4) y una librería que empieza a dejar archivos en el `cwd` por defecto
es una regresión, no una mejora.

Propuesta: `nikodym.run(config, *, run_dir: str | Path | None = None)`. Con `None` (default), el
comportamiento actual es **idéntico** y nada toca el disco. Con un `run_dir`, `api.run` crea
`<run_dir>/` y escribe allí el layout de SDD-03 §6 —`audit_trail.jsonl`, `environment.json`,
`model_card.json`, `model_card.md`— más lo que ya produce `Study.save`. Los archivos de gobernanza
se escriben **sólo si la sección correspondiente está activa**; `audit` sin `governance` deja trail
y entorno, y no card.

`scenario_log.jsonl` queda fuera: no tiene productor (medido: cero llamadas a
`log_scenario`/`log_overlay` fuera de `governance/`), y crear un archivo vacío para cumplir el
layout sería teatro. Se declara como límite, no se disimula.

Alternativas: (a) que el directorio sea siempre `runs/<run_id>/` bajo el `cwd` —rechazada: efecto
lateral no pedido—; (b) que lo gobierne un campo nuevo de `GovernanceConfig` —rechazada: movería el
`config_hash` y ataría la evidencia de `audit` a la sección `governance`, que puede estar apagada.

### D-GOB-7 — El trail se escribe dentro del directorio del run

Con D-GOB-6 aprobada, `api.py:319` deja de resolver `trail_filename` contra el `cwd` y lo resuelve
contra el `run_dir`. Sin `run_dir`, `audit.enabled=True` con una ruta **relativa** pasa a ser un
error explícito en vez de escribir en el `cwd` en silencio; una ruta **absoluta** se sigue
respetando. Esto cierra la violación de SDD-03 §8 medida en §1.4.

### D-GOB-8 — Los presets: `audit` se enciende; `governance` se hace alcanzable, no automático

Medición que gobierna esta decisión: `GovernanceConfig.purpose` es
`Field(default=...)` —**obligatorio, sin default**— en `governance/config.py:67-71`, y su
descripción lo ata a SR 11-7. El propósito de un modelo es `DATO-INSTITUCIONAL` puro: sólo la
institución puede fijarlo. **Un preset no puede rellenarlo sin violar la regla de `AGENTS.md` de que
el motor no inventa ninguna de las dos marcas.**

Por eso la propuesta separa las dos secciones:

- **`audit`: encendido en los cuatro presets.** No tiene ningún campo obligatorio, y es lo que hace
  que el model card lleve `decisions` en vez de una lista vacía con warning.
- **`governance`: sigue en `None` en el preset, y la UI lo ofrece como trabajo con `purpose` como
  campo requerido.** Así deja de ser inalcanzable —hoy no hay ninguna ruta de UI para encenderlo—
  sin que el motor invente el dato institucional.
- **`tracking`: sigue en `None`.** Exige un servidor MLflow; encenderlo de fábrica rompería la
  corrida por defecto de quien no lo tiene.

~~⚠️ **Esta decisión mueve el `config_hash` de los cuatro presets** (`audit` deja de ser `None`), y
con él los fixtures que lo firman. Es la única parte de la enmienda que lo hace, y es el motivo de
que D-GOB-9 exista por separado.~~

🔴 **FALSO, medido al implementar (2026-08-28).** `audit` está en
[`INFRA_SECTIONS`](../../src/nikodym/core/config/hashing.py) junto con `governance`, `tracking`,
`report` y `name`: **no entra al `config_hash`**. Los cuatro presets producen un hash idéntico con
`audit` encendido y apagado, y los tres fixtures de la demo siguen firmando el hash correcto. Lo
fija `test_presets_gobernanza.py::test_encender_audit_no_mueve_el_config_hash_de_ningun_preset`.

Consecuencia: **D-GOB-9 deja de ser obligatoria por identidad.** Sigue pendiente por *contenido*
—los fixtures traen `"model_card": null` y ahora el motor sabe producirlo— y conserva su OK propio.

Lo que esta decisión sí destapó fue otra cosa, que la enmienda no vio: con `audit` encendido el
dominio `survival` era **inalcanzable** (`TypeError: cannot pickle 'TextIOWrapper' instances` al
copiar en profundidad un estimador con el sink inyectado). Defecto preexistente, reproducido sobre
`5d6aa68` sin nada de D-GOB. Ver `DECISIONES-VIGENTES.md` §D-GOB.

### D-GOB-9 — La demo se recaptura en un paso aparte, con su propio OK

`AGENTS.md` exige OK específico para recapturar la demo. Con D-GOB-1…8 implementadas, los fixtures
de §1.5 quedan desalineados con el árbol —traen `model_card: null` y el `config_hash` viejo—, así
que la recaptura es **consecuencia necesaria**, no un extra. Pero no se hereda del OK de esta
enmienda: se pide por separado, y se ejecuta con `recapture-demo.yml` (la recaptura no es ejecutable
en Windows: WeasyPrint no carga sus nativas, medido y documentado en el runbook).

Hasta que ocurra, la demo sigue mostrando `model_card: null` y **eso se dice en el cierre**, no se
declara resuelto.

---

## 4. Contratos de datos (I/O)

**Input del canal.** Un `Step` ejecutado, con su card ya publicada en `study.artifacts`.

**Output.**

```python
study.results = {
    "metrics": {                       # D-GOB-2: plano, float finito
        "data.n_rows": 30.0,
        "performance.auc_oot": 0.78,
        "stability.worst_psi": 0.11,
    },
    "metric_sections": {               # D-GOB-3: un nivel por dominio
        "performance": {"discrimination": {...}},
    },
}
```

**Invariantes.**

- *Forma:* todo valor de `results["metrics"]` es `float` finito. Ninguna clave sin punto; el prefijo
  antes del primer punto es un `domain` que corrió en esta corrida.
- *No invención:* una métrica no evaluable **se omite**. Nunca se publica `0.0`, `NaN` ni `None` en
  su lugar.
- *Determinismo:* mismo config + mismos datos + misma semilla → mismo `results` bit a bit. Es un
  caso particular del invariante de SDD-01 §6, que ya nombra `results`.
- *No altera identidad:* llenar el canal no toca `config_hash` ni `data_hash`. El único movimiento de
  `config_hash` de esta enmienda es D-GOB-8, y se declara allí.
- *Compatibilidad de consumidores:* `ModelCardBuilder.build` y `TrackingSink.emit` siguen
  funcionando **sin modificarse** (§2.1).

---

## 5. Casos borde y errores

| caso | comportamiento |
|---|---|
| paso sin `metrics()` | no aporta; no es error (la mayoría de dominios empieza así) |
| métrica `None`/`NaN`/`inf` | se omite del namespace, con evento `decision` en el trail para que la ausencia quede trazada |
| paso que devuelve una clave con punto | `ConfigError` al escribir: el prefijo lo pone `core`, el dominio no lo compone |
| dos pasos del mismo `domain` | imposible por SDD-01 §7 (el `domain` es la sección del config); si ocurriera, colisión explícita, no sobrescritura silenciosa |
| corrida `failed` | se publica lo que alcanzaron a producir los pasos completados; el model card de un run fallido es explícitamente válido (SDD-03 §7.1.a) |
| `run_dir` existente y no vacío | se aplica la misma política que `Study.save` al sobrescribir (aparta el previo), no se mezcla |
| `audit.enabled=True`, ruta relativa, sin `run_dir` | error explícito (D-GOB-7), en vez de escribir en el `cwd` |

---

## 6. Tests y controles negativos preespecificados

Preespecificados a propósito: un gate escrito después del arreglo tiende a describirlo en vez de
vigilarlo.

1. **El canal se llena de verdad, sobre el artefacto final.** Corrida F1 completa por
   `nikodym.run` → `results["metrics"]` no vacío y con las claves que D-GOB-4 declara para cada
   dominio activo. *Control negativo:* borrar el `metrics()` de un dominio → el gate lo nombra por
   dominio, no falla genéricamente.
2. **La forma es la que los dos consumidores aceptan.** El mismo `results` pasa por
   `ModelCardBuilder.build` **y** por `_metric_items` y ambos devuelven las mismas claves.
   *Control negativo:* devolver una sección anidada desde un dominio → `GovernanceError`. Este test
   es el que impide que la contradicción de §2.1 se reabra en silencio.
3. **Bidireccional sobre D-GOB-4** (la regla de `AGENTS.md` para censos y la lección de D-VIS-6):
   quitar una métrica declarada → rojo; **añadir un dominio nuevo sin declarar su lista** → rojo
   también. Un gate que sólo comprueba las que ya existen no afirma completitud.
4. **El model card llega con métricas al usuario de `pip install`**, medido sobre el
   `model_card.json` escrito en el `run_dir`, no sobre el objeto en memoria.
5. **Dos corridas desde el mismo `cwd` producen dos trails separados** (cierra §1.4/D-GOB-7).
   *Control negativo:* revertir a la ruta relativa → el gate observa un solo archivo con los eventos
   de las dos.
6. **La ausencia no se rellena.** Un dominio cuya métrica sale `not_evaluable` → la clave **no está**
   en `metrics`. *Control negativo:* publicar `0.0` en su lugar → rojo.

---

## 7. Lo que esta enmienda NO hace

Se enumera para que nada quede pateado en silencio. Todo lo de abajo está **medido en `ddb616f`** y
sigue abierto después de esta enmienda:

- **`ScenarioLog` sigue sin productor.** Cero llamadas a `log_scenario`/`log_overlay` fuera de
  `governance/`. El control anti *earnings-management* seguirá existiendo como API sin cubrir
  ninguna corrida. Cablearlo cruza SDD-17/20/21 y es una enmienda propia.
- **Cinco campos de config siguen inertes**, cada uno con una sola aparición en `src/` (su
  declaración): `GovernanceConfig.require_overlay_justification` (`:99`),
  `GovernanceConfig.scenario_log_filename` (`:94`), `AuditConfig.capture_environment` (`:33`),
  `AuditConfig.tracked_packages` (`:38`) y `TrackingConfig.log_models` (`:74`).
- **`MLflowInventory.register` sigue apuntando a un artefacto fantasma** (`runs:/<run_id>/model`),
  porque `log_models` no lo crea.
- **El esquema de tags D5 sigue incompleto** (`nikodym.model_card_uri` nunca poblado; aliases sin
  campo declarativo).
- **El informe sigue sin capítulo de model card**, pese a que SDD-03 §1 declara a SDD-26 consumidor.
- **La evidencia de la frontera MLflow sigue corriendo sólo contra fakes.**
- No se toca el motor de riesgo, ni CMF, ni el arnés H9R, ni A.1d.

---

## 8. Lo que Cami decide

Todo lo anterior es una propuesta. Estas son las elecciones que no puede tomar el agente, en orden
de peso:

1. **¿Se aprueba D-GOB-1…5 —el canal de métricas— tal como está propuesto?**
   Recomendación: **sí**. Es la parte mejor medida: los dos consumidores ya existen, la forma plana
   está probada contra ambos, y la alternativa «volcar escalares» está refutada (§2.3).
   La tabla de D-GOB-4 es lo que conviene mirar con lupa: es lo que se imprimirá en cada model card.

2. **¿`run()` gana `run_dir` opcional (D-GOB-6), o la gobernanza se queda sólo en memoria?**
   Recomendación: **ganarlo, opcional y apagado por defecto**. Sin él, `model_card.json` no existe
   para nadie y el bloqueador sigue abierto aunque el canal esté lleno. Opcional y apagado evita que
   una librería empiece a escribir en el `cwd` de quien la importa.

3. **¿Se enciende `audit` en los cuatro presets (D-GOB-8), asumiendo que mueve su `config_hash`?**
   Recomendación: **sí**, y **no** encender `governance` de fábrica: `purpose` es
   `DATO-INSTITUCIONAL` y el motor no lo inventa. La alternativa —dejar los cuatro apagados— mantiene
   el `config_hash` intacto pero deja el titular del README sin ninguna ruta entregada, que es
   exactamente el bloqueador.

4. **¿Se autoriza, por separado y después, recapturar la demo (D-GOB-9)?**
   Recomendación: **sí, pero en su propio paso y con su propio OK**, una vez el resto esté verde.
   No se pide ahora.

Si 1 se aprueba y 2 o 3 no, la enmienda sigue siendo coherente: el canal se llena y lo consumen
`governance` en memoria y `tracking` si está encendido, pero **el bloqueador 3 no se cierra**, y así
hay que declararlo.
