# Desempeño, estabilidad y gobernanza

Los dos últimos pasos del pipeline F1 —**desempeño** y **estabilidad**— responden dos preguntas
distintas sobre un scorecard:

- **¿Discrimina?** ¿Separa el modelo a los buenos de los malos? Lo miden KS, Gini y AUC.
- **¿Se sostiene?** ¿La población y los puntajes de hoy se parecen a los de desarrollo? Lo miden
  PSI y CSI.

Sobre ambos se apoya el tercer pilar, el que convierte a Nikodym en algo defendible frente a un
validador o a la CMF: la **gobernanza por construcción** (lineage, model card, audit-trail y
reproducibilidad bit a bit). Un número de AUC solo vale si se puede reproducir y trazar cómo se
obtuvo.

!!! note "Los números de esta guía"
    Todas las cifras concretas provienen de una **corrida de ejemplo** real (dataset sintético de
    consumo, preset estándar F1, `status="done"`) incluida como fixture de la demo. No son
    benchmarks: ilustran la forma y las magnitudes que produce el pipeline. Reejecutar el mismo
    config sobre los mismos datos las reproduce idénticas.

---

## 1. Discriminación: KS, Gini y AUC

El paso de **desempeño** evalúa qué tan bien el modelo ordena el riesgo. Nikodym reporta las tres
métricas estándar por cada partición (desarrollo, *holdout*, *out-of-time*), calculadas sobre la
misma fuente —en la corrida de ejemplo, la **PD calibrada** (`evaluation_source="pd_calibrated"`)—.

### Qué mide cada una

- **AUC** (área bajo la curva ROC). Probabilidad de que, tomando un malo y un bueno al azar, el
  modelo asigne más riesgo al malo. `0.5` es azar puro; `1.0` es separación perfecta. Es la métrica
  de ordenamiento más citada.
- **Gini**. Reescalado lineal de la AUC — `Gini = 2·AUC − 1` — que mapea el rango `[0, 1]` de la AUC
    a `[−1, 1]`: para modelos mejores que el azar (`AUC ≥ 0.5`) cae
    en `[0, 1]` —`0` es azar, `1` es perfecto—; un modelo peor que el azar da Gini negativo. Mismo
    contenido informativo que la AUC, expresado como "cuánto mejor que el azar". En la corrida de
    ejemplo, desarrollo tiene AUC `0.712` y Gini `0.425`: la identidad es exacta sobre los valores sin
    redondear (AUC `0.71235` → Gini `0.42469` → `0.425`); con el AUC ya redondeado, `2 × 0.712 − 1 = 0.424`.
- **KS** (Kolmogorov–Smirnov). Máxima distancia vertical entre las distribuciones acumuladas de
  buenos y malos a lo largo del score. Responde: *en el punto de corte óptimo, ¿cuánta más
  proporción de malos que de buenos deja el modelo por debajo?* Nikodym reporta además el punto de
  corte donde se alcanza (`ks_cutoff_risk_score`) y las tasas asociadas (`tpr_at_ks`, `fpr_at_ks`).

### La corrida de ejemplo

| Partición | n | malos | AUC | Gini | KS |
|---|---:|---:|---:|---:|---:|
| desarrollo | 3.961 | 924 | 0,712 | 0,425 | 0,320 |
| holdout | 1.031 | 244 | 0,695 | 0,389 | 0,312 |
| oot | 1.008 | 239 | 0,656 | 0,312 | 0,252 |

*Fuente: corrida de ejemplo, `performance.discriminant`.*

La lectura relevante no es un número aislado sino el **patrón entre particiones**: el desempeño cae
de desarrollo a *holdout* y, más marcadamente, a *out-of-time* (AUC `0,712 → 0,695 → 0,656`). Una
degradación moderada es esperable y sana; una caída brusca en *oot* es señal de sobreajuste o de un
cambio poblacional que el paso de estabilidad debe explicar.

### Umbrales de referencia

Nikodym **no impone** umbrales fijos de discriminación: en la corrida de ejemplo el bloque de
`thresholds` va vacío y todas las particiones quedan en banda `"ok"`. Los umbrales de corte son
**configurables**, porque el nivel aceptable depende de la cartera, el horizonte y la práctica del
banco. Como orientación de industria (no como regla que el motor aplique):

| Métrica | Débil | Aceptable | Fuerte |
|---|---|---|---|
| KS | < 0,20 | 0,20 – 0,40 | > 0,40 |
| Gini | < 0,30 | 0,30 – 0,50 | > 0,50 |
| AUC | < 0,65 | 0,65 – 0,75 | > 0,75 |

!!! warning "Contexto sobre benchmark"
    Estos rangos son heurísticos y varían por segmento. En carteras de consumo *retail* un KS de
    `0,30` puede ser un modelo sólido; en un scorecard de comportamiento con información de mora
    reciente se esperaría más. Lo que Nikodym garantiza no es que el número sea "bueno", sino que
    sea **reproducible y trazable**: quién lo calculó, sobre qué datos y con qué config.

### Deciles y lift

Además de los agregados, desempeño produce una **tabla de deciles** por partición
(`performance.deciles`): tasa de malos, PD media, score medio, captura acumulada de malos/buenos,
*lift* y KS acumulado por decil. Es la vista que un analista usa para verificar **monotonía** (el
riesgo debe caer decil a decil) y para dimensionar políticas de corte. En la corrida de ejemplo el
primer decil de desarrollo concentra una tasa de malos de `0,51` frente a un promedio de cartera
mucho menor, con un *lift* de `2,19`.

---

## 2. Estabilidad poblacional: PSI y CSI

Un modelo puede discriminar bien en desarrollo y aun así fallar en producción si la población
cambió. El paso de **estabilidad** cuantifica ese *drift*.

### PSI — Population Stability Index

El PSI compara dos distribuciones —la de referencia (*expected*, desarrollo) contra la actual
(*actual*, la partición o el período que se monitorea)— discretizadas en *bins* (10 en la corrida
de ejemplo). Para cada *bin* `i`:

```text
PSI = Σᵢ (aᵢ − eᵢ) · ln(aᵢ / eᵢ)
```

donde `eᵢ` y `aᵢ` son las proporciones esperada y actual en el *bin*. Cada término es siempre
positivo (penaliza el desvío en ambas direcciones) y el PSI total es la suma. Nikodym aplica esta
fórmula sobre el **score** y sobre la **PD calibrada**.

### CSI — Characteristic Stability Index

El CSI es el **mismo cálculo que el PSI**, pero aplicado a una característica individual del
scorecard en lugar de al score global. Responde: *¿qué variable movió la distribución?* En la
corrida de ejemplo se computa sobre los puntos de cada característica
(`csi_source="score_points"`): `antiguedad_meses__points`, `deuda_ingreso__points`,
`ingreso_mensual__points`, `mora_max_12m__points`, `utilizacion_linea__points`. El PSI global te
dice *que* algo se movió; el CSI te dice *cuál* característica lo hizo, que es lo que orienta el
diagnóstico.

### Umbrales 0,1 y 0,25

A diferencia de la discriminación, aquí los umbrales **sí son fijos y estándar de industria**, y
Nikodym los aplica para asignar una banda a cada comparación:

| PSI / CSI | Banda | Interpretación | Acción |
|---|---|---|---|
| < 0,10 | `stable` | Sin cambio material | `none` |
| 0,10 – 0,25 | `review` | Desvío moderado, investigar | `vigilar` |
| > 0,25 | `redevelop` | Cambio significativo | `redesarrollar` |

En la corrida de ejemplo estos son los campos reales del config de estabilidad:
`stable_threshold=0.1`, `review_threshold=0.25`.

### La corrida de ejemplo

El modelo es muy estable: todas las comparaciones caen holgadamente en banda `stable`
(`action="none"`).

| Métrica | Comparación | Valor | Banda |
|---|---|---:|---|
| PSI de score | dev vs holdout | 0,0127 | stable |
| PSI de score | dev vs oot | 0,0068 | stable |
| PSI de PD | dev vs holdout | 0,0132 | stable |
| PSI de PD | dev vs oot | 0,0065 | stable |
| CSI (peor característica) | dev vs holdout | 0,0102 (`mora_max_12m`) | stable |

*Fuente: corrida de ejemplo, `stability.stability_metrics` y `stability.worst_csi_*`.*

Todos los valores están uno o dos órdenes de magnitud por debajo del umbral `0,10`. Es el
resultado esperable en un dataset sintético con particiones bien comportadas; en producción real la
gracia del monitoreo es detectar cuándo un `mora_max_12m__points` cruza `0,10` y pasa a `review`
**antes** de que la discriminación se caiga.

!!! tip "Estabilidad ≠ desempeño"
    Son señales independientes y complementarias. Un modelo puede tener PSI bajo (población estable)
    y aun así perder Gini (el mundo cambió de una forma que el modelo no captura), o al revés. Por
    eso Nikodym reporta ambos por partición: el diagnóstico correcto necesita las dos vistas.

---

## 3. Gobernanza: el diferenciador

Aquí está el ángulo que separa a Nikodym de un notebook con `sklearn`. Cada corrida —además de las
métricas— emite **evidencia auditable por construcción**, sin trabajo extra del analista. Es lo que
un validador (SR 11-7) o un regulador (CMF) pide antes de aceptar un modelo en producción.

### Reproducibilidad bit a bit

El principio rector es `(datos + config + semilla) → resultado idéntico`. Al cerrar cada corrida,
`run` congela un **lineage bundle** (`nikodym.core.lineage.LineageBundle`) con la identidad
computacional completa del experimento:

- `git_sha` y `git_dirty` — commit del código y si el árbol tenía cambios sin commitear.
- `config_hash` — hash canónico del config (la identidad del experimento).
- `data_hash` — hash del contenido lógico de los datos (por bloques, no los bytes del Parquet).
- `root_seed` — semilla raíz de todo el azar de la corrida.
- `uv_lock_hash` — hash del `uv.lock`, que fija el entorno de dependencias resuelto.
- `schema_version`, `created_at` y `determinism_caveats` — versión del esquema, sello temporal y
  advertencias explícitas de no-determinismo.

Se accede con `study.lineage_bundle()`. Al recargar un `Study` persistido, Nikodym **verifica el
`config_hash`**: si el `config.yaml` en disco no coincide con el del lineage, levanta un error en
vez de devolver resultados con identidad divergente. La reproducibilidad no es una promesa del
README; es una invariante chequeada.

!!! note "El config *es* el experimento"
    Como el config declarativo captura todo el pipeline (binning, selección, modelo, scorecard,
    calibración, umbrales), el `config_hash` es una huella completa. Dos corridas con el mismo
    hash sobre el mismo `data_hash` y `root_seed` son, por diseño, idénticas bit a bit.

### Model card (SR 11-7)

Cada corrida finalizada produce una **model card** (`nikodym.governance.ModelCard`): la ficha
auditable del modelo, serializable a **JSON canónico** (para *diff* y control de versiones) y a
**markdown** (para lectura humana). Reúne en un solo objeto lo que un comité de modelos necesita:

- **Identidad y lineage**: `run_id`, `config_hash`, `data_hash`, `git_sha`, `root_seed`,
  `schema_version`.
- **Propósito, supuestos y limitaciones**: declarados en el `GovernanceConfig` (el `purpose` es
  **obligatorio**) y copiados a la ficha. Nikodym además **agrega limitaciones automáticas** cuando
  detecta lineage parcial (p. ej. "lineage parcial: sin hash de datos") o un run fallido: la ficha
  no oculta sus propias lagunas.
- **Métricas**: los agregados de desempeño y estabilidad, validados como escalares finitos.
- **Decisiones**: cada decisión gobernada del pipeline (regla, umbral, valor, acción) materializada
  desde el audit-trail.
- **Ciclo de revisión**: `review_date` y `next_review_date` calculada como emisión + un período
  configurable (por defecto 12 meses), en línea con la revisión periódica que exige SR 11-7.

### Audit-trail e inventario

- **Audit-trail**. Un registro append-only de eventos de la corrida (decisiones, inicio/fin de
  pasos). La model card lee de ahí las decisiones; si el trail no está disponible, la ficha lo
  declara explícitamente en vez de fingir completitud.
- **Inventario de modelos**. Contrato (`ModelInventory`) para registrar cada corrida en un
  *registry* (p. ej. MLflow) con anclaje idempotente `(model_name, config_hash)` y *tags* con
  naming CMF: `cartera` (comercial/consumo/hipotecario/grupal), `motor` (scoring/cmf/ifrs9),
  `fase`, `estado_validacion` (desarrollo → en_validacion → validado → retirado). Cuando la
  publicación está apagada, un `NullInventory` deja el flujo como no-op consciente y genera solo
  evidencia local.

### Por qué esto le habla a un regulador

Un banco no compra un AUC alto: compra un modelo que pueda **defender** ante la CMF y ante su propia
validación interna. Nikodym entrega, sin esfuerzo adicional del analista, exactamente lo que esos
procesos exigen: identidad reproducible de cada corrida, propósito y limitaciones documentados,
métricas trazables a los datos y al código que las generó, decisiones registradas y un calendario
de revisión. La gobernanza deja de ser un anexo que alguien redacta a mano después del modelo y pasa
a ser un subproducto verificable de haberlo corrido.

---

## 4. Acceso desde código

Los resultados viven en el `ArtifactStore` del `Study`, *namespaced* por dominio y clave. Las claves
reales de estos dos pasos:

```python
import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.ui.datasets import materialize
from nikodym.ui.presets import standard_preset
from pathlib import Path
from tempfile import mkdtemp

# Corrida completa con el preset estándar F1 (ver Quickstart).
workdir = Path(mkdtemp(prefix="nikodym-"))
preset = standard_preset()
data_path = materialize(preset["dataset_id"], workdir=workdir)
cfg = preset["config"]
cfg["data"]["load"]["source"] = str(data_path)
study = nikodym.run(NikodymConfig.model_validate(cfg))
assert study.run_context.status == "done"

# Discriminación: AUC / Gini / KS por partición.
discriminant = study.artifacts.get("performance", "discriminant_metrics")

# Estabilidad: PSI de score/PD y CSI por característica, con banda y acción.
stability = study.artifacts.get("stability", "stability_metrics")
psi_table = study.artifacts.get("stability", "psi_table")

# Lineage bundle: identidad reproducible de la corrida.
lineage = study.lineage_bundle()
print(lineage.config_hash, lineage.git_sha, lineage.root_seed)
```

!!! warning "Chequea el estado antes de leer"
    `nikodym.run` es *fail-loud pero no explosivo*: ante un fallo devuelve un `Study` **parcial** con
    `study.run_context.status == "failed"` y el error registrado en el audit-trail, no una
    excepción. Verifica siempre `study.run_context.status == "done"` antes de usar los artefactos.

Para el detalle de firmas ver la [Referencia de la API](../api.md); para el modelo mental completo,
[Conceptos](../concepts.md).
