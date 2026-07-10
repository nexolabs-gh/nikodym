# Binning, WoE/IV y selección de variables

Esta guía cubre las dos primeras etapas computacionales del pipeline de scorecard (Fase 1):
el **binning** supervisado con *Weight of Evidence* (WoE) e *Information Value* (IV), y la
**selección** de variables previa al modelo. Son los pasos que transforman variables crudas en
predictores estables e interpretables y descartan lo que no aporta o rompe la regresión.

!!! note "Dónde encaja"
    En el pipeline F1 el orden es `binning → selección → modelo → scorecard → calibración →
    desempeño/estabilidad` (ver [Conceptos](../concepts.md)). El binning produce columnas WoE (una
    por variable cruda, con sufijo `__woe`); la selección filtra ese universo y publica el
    subconjunto que entra a la regresión logística. Ambas etapas son secciones declarativas del
    mismo `NikodymConfig`: `config.binning` y `config.selection`.

!!! warning "Superficie experimental (SemVer 0.x)"
    Las secciones `binning` y `selection` del config y las claves de artefactos son experimentales
    y pueden cambiar antes de la 1.0.

## Weight of Evidence (WoE)

El binning discretiza cada variable en *bins* (tramos numéricos o grupos de categorías) y reemplaza
el valor crudo por el WoE de su bin. El WoE mide, para cada bin, cuánto se aparta la mezcla
buenos/malos de ese tramo respecto de la población total.

Con la convención del motor (el **evento** es el *malo* / *default*), para el bin \(i\):

```text
WoE_i = ln( (Non-event_i / Non-event_total) / (Event_i / Event_total) )
      = ln( distribución_de_buenos_i / distribución_de_malos_i )
```

Interpretación del signo (clave para leer una scorecard):

- **WoE > 0**: el bin concentra *más buenos* que la media → **menor riesgo**.
- **WoE < 0**: el bin concentra *más malos* que la media → **mayor riesgo**.
- **WoE = 0**: el bin replica la mezcla poblacional (neutral).

Trabajar en escala WoE tiene tres ventajas que importan para una scorecard regulatoria: linealiza
la relación variable–log-odds (encaja directo en la regresión logística), es monótono respecto de
la tasa de evento del bin, y da un tratamiento explícito y auditable a *missing* y valores
especiales (cada uno recibe su propio bin y su propio WoE).

### Ejemplo: bins reales de `ingreso_mensual`

De la corrida de ejemplo (`web/src/fixtures/demo/results.json`, tabla del dominio `binning` para
`ingreso_mensual`), el motor resolvió 6 bins numéricos más los bins técnicos *Special* y *Missing*:

| Bin | Count | Tasa de evento | WoE |
|---|---:|---:|---:|
| (-inf, 242795.88) | 210 | 0.4286 | -0.9022 |
| [242795.88, 354256.50) | 587 | 0.3526 | -0.5825 |
| [354256.50, 464805.09) | 806 | 0.2816 | -0.2536 |
| [464805.09, 631639.47) | 917 | 0.2268 | +0.0364 |
| [631639.47, 913196.97) | 876 | 0.1655 | +0.4278 |
| [913196.97, inf) | 565 | 0.0832 | +1.2099 |
| **Total** | **3961** | **0.2333** | — |

A mayor ingreso, la tasa de evento (default) baja de forma monótona (0.4286 → 0.0832) y el WoE sube
de forma monótona (-0.9022 → +1.2099): el tramo de ingreso más bajo es el de mayor riesgo y el más
alto el de menor riesgo. Este es exactamente el comportamiento que fuerza la restricción de
monotonía (ver más abajo). Los bins *Special* y *Missing* existen aunque en este dataset sintético
estén vacíos; en datos reales capturan centinelas y faltantes con su propio WoE.

## Information Value (IV)

El IV resume, en un solo número por variable, cuánto separa a buenos de malos el binning completo.
Se obtiene sumando el aporte de cada bin:

```text
IV_i = (distribución_de_buenos_i - distribución_de_malos_i) * WoE_i
IV   = Σ_i IV_i     (suma sobre todos los bins de la variable)
```

Cada término combina la *diferencia* de masa entre buenos y malos del bin con su WoE, así que
premia bins que además de estar sesgados hacia un lado concentran volumen. En el ejemplo de
`ingreso_mensual`, el bin de ingreso más alto aporta el grueso del IV (≈0.145 de un IV total de
0.3048): pocos malos y muchos buenos, bien separados.

### Bandas diagnósticas de IV

Nikodym clasifica el IV en bandas fijas (helper `iv_band`, SDD-06 §3; frontera con **límite
inferior inclusivo**). Estas bandas son diagnósticas, **no** son el filtro de corte (eso lo define
`selection.min_iv`):

| Banda | Rango de IV | Lectura |
|---|---|---|
| `none` | IV < 0.02 | Sin poder predictivo útil |
| `weak` | 0.02 ≤ IV < 0.10 | Débil |
| `medium` | 0.10 ≤ IV < 0.30 | Predictor sólido |
| `strong` | 0.30 ≤ IV < 0.50 | Fuerte |
| `suspicious` | IV ≥ 0.50 | Sospechosamente alto (posible *fuga de información*) |

Un IV muy alto no es automáticamente bueno: suele delatar una variable que filtra el resultado
(*leakage*) o que es un proxy casi directo del target. Por eso la selección trata el extremo
superior como una alerta, no como una virtud (`max_iv`, abajo).

### IV por variable en la corrida de ejemplo

Del mismo fixture (`binning.iv_by_variable` y `monotonicity_by_variable`):

| Variable | IV | Banda | Monotonía (tasa de evento) |
|---|---:|---|---|
| `ingreso_mensual` | 0.3048 | `strong` | descending |
| `deuda_ingreso` | 0.1635 | `medium` | ascending |
| `utilizacion_linea` | 0.0610 | `weak` | ascending |
| `antiguedad_meses` | 0.0414 | `weak` | descending |
| `mora_max_12m` | 0.0219 | `weak` | ascending |
| `segmento` | 0.0029 | `none` | — (categórica, sin monotonía) |

`optbinning_version` registrado en la corrida: `0.20.0`.

## Binning óptimo monotónico (OptBinning)

El binning de Nikodym es **supervisado y óptimo**: no usa cortes arbitrarios (cuantiles fijos, ancho
constante), sino que resuelve un problema de optimización sobre el target. El motor es
[OptBinning](https://gnpalencia.org/optbinning/), envuelto por la sección `binning`.

El proceso, por variable, es en dos fases:

1. **Prebinning**: se generan hasta `max_n_prebins` cortes candidatos (por defecto 20), cada uno con
   al menos `min_prebin_size` de la masa (por defecto 5%).
2. **Optimización**: se agrupan los prebins en el conjunto final de bins que **maximiza el IV**
   sujeto a las restricciones declaradas: número de bins (`max_n_bins`, `min_n_bins`), tamaño mínimo
   por bin (`min_bin_size`), mínimos de eventos/no-eventos por bin, y sobre todo la **forma
   monótona** exigida.

### Por qué monotonía

La monotonía obliga a que la tasa de evento (riesgo) se mueva en una sola dirección a través de los
bins ordenados. No es un capricho estadístico; es un requisito de negocio y regulatorio:

- **Interpretabilidad y defensa ante el regulador (CMF, SR 11-7)**: "a mayor deuda/ingreso, mayor
  riesgo" es una relación que se puede explicar y validar. Un binning no monótono (riesgo que sube,
  baja y vuelve a subir) casi siempre está ajustando ruido de la muestra.
- **Robustez fuera de muestra**: las reversiones locales de riesgo raramente sobreviven en Holdout u
  OOT. Forzar monotonía es una forma de regularización que reduce el sobreajuste del binning.
- **Coherencia con la scorecard**: si el WoE es monótono, el puntaje que asigna la scorecard también
  lo es, y no aparecen puntajes contraintuitivos.

El default de Nikodym es `monotonic_trend="auto_asc_desc"`: el solver elige automáticamente entre
tendencia **ascendente** o **descendente** de la tasa de evento según los datos, sin permitir formas
no monótonas. En el ejemplo, eligió `descending` para `ingreso_mensual` (más ingreso → menos riesgo)
y `ascending` para `deuda_ingreso` (más carga → más riesgo).

Valores admitidos por `monotonic_trend` (tipo `MonotonicTrend`): `auto`, `auto_heuristic`,
`auto_asc_desc`, `ascending`, `descending`, `concave`, `convex`, `peak`, `peak_heuristic`, `valley`,
`valley_heuristic`. Las formas `peak`/`valley` (U o U invertida) se usan cuando la relación con el
riesgo genuinamente no es monótona; deben justificarse, no ser el default.

### Parámetros de la sección `binning`

Los nombres y defaults salen directo de `nikodym.binning.config.BinningConfig`:

| Parámetro | Default | Qué controla |
|---|---|---|
| `feature_columns` | `"*"` | Variables a binear (`"*"` = todas las no estructurales). |
| `categorical_columns` | `()` | Fuerza tratamiento categórico (p. ej. códigos numéricos). |
| `max_n_prebins` | `20` | Cortes candidatos antes de optimizar. |
| `min_prebin_size` | `0.05` | Masa mínima por prebin candidato. |
| `max_n_bins` | `8` | Tope de bins finales por variable. |
| `min_n_bins` | `None` | Piso de bins finales (None = lo decide el solver). |
| `min_bin_size` | `0.05` | Masa mínima por bin final. |
| `min_bin_n_event` / `min_bin_n_nonevent` | `1` / `1` | Mínimo de malos / buenos por bin. |
| `monotonic_trend` | `"auto_asc_desc"` | Forma monótona exigida (ver arriba). |
| `min_event_rate_diff` | `0.0` | Separación mínima de tasa de evento entre bins vecinos. |
| `max_pvalue` | `None` | Exige significancia estadística entre bins (opcional). |
| `solver` / `mip_solver` | `"mip"` / `"bop"` | Solver óptimo (`"cp"` está deshabilitado a propósito). |
| `require_optimal` | `True` | Descarta variables cuyo solver no probó optimalidad. |
| `n_jobs` | `None` | 1 core por defecto, por reproducibilidad exacta. |
| `special_handling` | `"separate"` | Bin propio para valores especiales (vs. fusionar con missing). |
| `metric_special` / `metric_missing` | `"empirical"` | WoE de special/missing (empírico o forzado a un valor). |
| `cat_cutoff` | `0.01` | Frecuencia bajo la cual se agrupan niveles categóricos raros. |
| `output_suffix` | `"__woe"` | Sufijo de las columnas transformadas (p. ej. `ingreso_mensual__woe`). |
| `fail_on_non_binnable` | `False` | Si `True`, una variable constante o 100% missing aborta el fit. |

!!! tip "Overrides por variable"
    `variable_overrides` permite ajustar `monotonic_trend`, `max_n_bins`, `min_bin_size`,
    `cat_cutoff` o `dtype` para una variable puntual sin tocar los globales — útil cuando una sola
    variable tiene una forma en U (`valley`) o necesita más granularidad que el resto.

## Selección de variables

Tras el binning, la sección `selection` (`nikodym.selection.config.SelectionConfig`) aplica una
batería de filtros **auditables y deterministas** sobre las columnas WoE candidatas. El objetivo es
entregar a la regresión un conjunto que sea predictivo, no redundante y estable. Los filtros se
aplican en cascada y cada decisión queda registrada (variable, motivo, métricas).

### 1. Filtro por IV

- `min_iv` (default `0.02`): descarta variables con IV bajo el umbral por poder predictivo
  insuficiente. Coincide con la frontera `none`/`weak` de `iv_band`.
- `max_iv` (default `0.50`) + `max_iv_action` (`"flag"` | `"exclude"`): trata el IV
  *sospechosamente alto*. Por defecto solo **marca** la variable para revisión manual (posible
  *leakage*); con `"exclude"` la descarta automáticamente.

### 2. Métricas univariadas (diagnóstico y filtro opcional)

Con `compute_univariate_metrics=True` (default) se calculan **AUC, KS y Gini** de cada variable por
separado en Desarrollo. Son diagnóstico por defecto; se vuelven filtro si se define `min_auc`,
`min_ks` o `min_gini` (todos `None` por defecto). En la corrida de ejemplo, `ingreso_mensual`
alcanzó AUC 0.6473 / KS 0.2118 / Gini 0.2946 univariados, y `segmento` apenas AUC 0.5146 /
KS 0.0234 — coherente con su IV nulo.

### 3. Filtro por correlación

Descarta redundancia lineal entre columnas WoE (sub-config `correlation`):

- `method` (default `"pearson"`; también `"spearman"`, `"kendall"`).
- `threshold` (default `0.75`): si `|rho|` entre dos variables lo supera, se **conserva la de mayor
  prioridad** (ver ranking) y se descarta la otra.
- `clustering_method` (default `"none"`): `"none"` poda de a una en orden de prioridad;
  `"connected_components"` agrupa variables mutuamente correlacionadas y conserva solo la mejor de
  cada grupo.

### 4. Filtro por VIF (multicolinealidad)

El *Variance Inflation Factor* captura colinealidad **multivariada** (una variable explicada por una
combinación de otras), que la correlación por pares puede no ver. Sub-config `vif`:

- `threshold` (default `5.0`): VIF máximo tolerado (rangos de corte típicos 5–10).
- Poda **iterativa**: en cada ronda se elimina la variable con peor VIF y se recalcula, hasta que
  todas queden bajo el umbral (`max_iterations` acota las rondas; `None` = hasta cumplir).
- `add_intercept` (default `True`): incluye constante en las regresiones auxiliares del VIF.

### 5. Estabilidad (PSI/CSI por característica)

Sub-config `stability`: mide el *Population Stability Index* / *Characteristic Stability Index* de
cada variable en Holdout/OOT contra Desarrollo, para detectar variables cuya distribución se corre
en el tiempo.

- `action` (default `"report_only"`): solo informa; con `"exclude"` descarta las inestables.
- `stable_threshold` (default `0.10`) y `review_threshold` (default `0.25`): bajo `stable_threshold`
  la variable es estable; entre ambos umbrales queda "en revisión"; por sobre `review_threshold`
  pasa a "rediseñar" y, si `action="exclude"`, se descarta.

### 6. Ranking y overrides de negocio

- `priority_order` (default `("iv", "auc", "ks", "name")`): ranking determinista para decidir **qué
  variable conservar** en los desempates de correlación y VIF (`"name"` rompe empates
  alfabéticamente, garantizando reproducibilidad).
- `force_include` / `force_exclude`: negocio conserva o descarta variables por criterio experto.
  `force_include` mantiene una variable aunque no pase los filtros (salvo que sea inválida o genere
  un conflicto de VIF irresoluble); `force_exclude` tiene prioridad sobre todo. No pueden compartir
  variables.
- `fail_if_no_features` (default `True`): si ninguna variable sobrevive, la corrida aborta en vez de
  publicar solo diagnóstico.

### Selección en la corrida de ejemplo

Del fixture (`selection` en `web/src/fixtures/demo/results.json`), con los umbrales del preset
estándar (`min_iv=0.02`, `max_iv=0.5` acción `flag`, `correlation.threshold=0.75` pearson,
`vif.threshold=5.0`):

- **6 candidatas → 5 seleccionadas, 1 excluida.**
- La única exclusión fue `segmento`, por `low_iv`: `iv=0.00292 < min_iv=0.02`.
- Sin banderas de IV alto ni de estabilidad.
- Tras la selección, la máxima correlación absoluta entre variables retenidas fue **0.0303** y el
  máximo VIF **1.0016**: el conjunto final es prácticamente ortogonal, así que ni el filtro de
  correlación ni el de VIF necesitaron podar nada (el trabajo lo hizo el filtro de IV).

## Configurar y leer los resultados

Ambas secciones se editan como cualquier otra parte del `NikodymConfig`. Partiendo del preset
estándar (ver [Quickstart](../index.md#quickstart)):

```python
import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.ui.presets import standard_preset

cfg_dict = standard_preset()["config"]

# Binning: forma monótona automática y tope de 6 bins por variable.
cfg_dict["binning"]["monotonic_trend"] = "auto_asc_desc"
cfg_dict["binning"]["max_n_bins"] = 6

# Selección: umbrales de IV, correlación y VIF.
cfg_dict["selection"]["min_iv"] = 0.02
cfg_dict["selection"]["correlation"]["threshold"] = 0.75
cfg_dict["selection"]["vif"]["threshold"] = 5.0

config = NikodymConfig.model_validate(cfg_dict)
```

Tras `study = nikodym.run(config)` (y verificar `study.run_context.status == "done"`), los
resultados viven *namespaced* en `study.artifacts`. Claves reales que publican estas etapas:

```python
study = nikodym.run(config)
assert study.run_context.status == "done"

# --- Binning ---
tablas = study.artifacts.get("binning", "tables")        # dict: variable -> tabla WoE/IV
tabla_ingreso = tablas["ingreso_mensual"]                # bins, tasa de evento, WoE, IV por bin
resumen = study.artifacts.get("binning", "summary")      # IV, banda, monotonía y nº de bins
woe_frame = study.artifacts.get("binning", "woe_frame")  # dataset ya transformado a WoE

# --- Selección ---
elegidas = study.artifacts.get("selection", "selected_features")   # variables que pasan
tabla_sel = study.artifacts.get("selection", "selection_table")    # decisión + motivo por variable
vif = study.artifacts.get("selection", "vif_table")                # VIF final por variable
```

Además, cada etapa deja una sección compacta para la *model card* (`binning_card` y
`selection_card`), que es lo que consume la gobernanza automática (SR 11-7).

## Ver también

- [Conceptos](../concepts.md) — el pipeline F1 y el modelo `run → Study`.
- [Referencia de la API](../api.md) — `NikodymConfig`, `run` y `Study`.
