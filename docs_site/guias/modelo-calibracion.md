# Modelo, scorecard y calibración

Esta guía cubre el corazón numérico del scorecard F1: cómo se ajusta el **modelo logístico
de PD** sobre las variables WoE seleccionadas, cómo esos coeficientes se **escalan a un puntaje**
entero y cómo la PD cruda se **calibra** a una tasa central de negocio. Son tres pasos
consecutivos del pipeline (`… → selección → **modelo → scorecard → calibración** → desempeño →
estabilidad`), cada uno gobernado por su sección del `NikodymConfig`. Ver
[Conceptos](../concepts.md) para el modelo mental del pipeline completo.

!!! note "Estado pre-1.0 (experimental)"
    Las secciones `model`, `scorecard` y `calibration` son computacionales y entran al
    `config_hash` de la corrida. Su API está versionada como **0.x honesto** (SemVer): los
    nombres de campos son estables dentro de la 0.9.x pero pueden ajustarse hasta la 1.0.

Los valores concretos de esta guía provienen de una **corrida de ejemplo**: el preset estándar
F1 sobre el dataset sintético de consumo de comportamiento (`fixtures/demo`). No son cifras
inventadas ni benchmarks; son la salida de reejecutar ese preset. Para reproducirla:

```python
from pathlib import Path
from tempfile import mkdtemp

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.ui.datasets import materialize
from nikodym.ui.presets import standard_preset

workdir = Path(mkdtemp(prefix="nikodym-guia-"))
preset = standard_preset()
data_path = materialize(preset["dataset_id"], workdir=workdir)

cfg_dict = preset["config"]
cfg_dict["data"]["load"]["source"] = str(data_path)
config = NikodymConfig.model_validate(cfg_dict)

study = nikodym.run(config)
assert study.run_context.status == "done"
```

Los tres pasos publican sus resultados como artefactos *namespaced* en
`study.artifacts.get(<dominio>, <clave>)`.

---

## 1. Modelo logístico de PD

El paso `model` ajusta una **regresión logística** (statsmodels) sobre las columnas WoE que
sobrevivieron al binning y la selección. La probabilidad de incumplimiento es
`PD = sigmoid(η)`, con `η = β₀ + Σ βⱼ · WoEⱼ` (el *predictor lineal* o log-odds). Trabajar sobre
WoE en vez de las variables crudas es lo que hace posible el escalado a puntaje del paso
siguiente: cada bin aporta una cantidad fija de log-odds.

### Parámetros de ajuste (`ModelConfig`)

| Campo | Default | Rol |
|---|---|---|
| `engine` | `logit` | `logit` (statsmodels Logit) o `glm_binomial` (solo si se ponderan observaciones). |
| `fit_intercept` | `True` | Incluye el intercepto β₀ que captura la tasa base antes del scorecard. |
| `optimizer` | `newton` | Newton-Raphson; `bfgs`/`lbfgs` solo si no converge. |
| `fit_maxiter` | `100` | Iteraciones máximas del ajuste (override deliberado sobre el `maxiter=35` de statsmodels). |
| `tol` | `1e-8` | Tolerancia de convergencia. |
| `alpha` | `0.05` | Nivel para los intervalos de confianza de los coeficientes (solo inferencia; no afecta el ajuste). |

### Política de signos de beta (`sign_policy`)

Con la convención de Nikodym `WoE = ln(%Buenos / %Malos)`, una variable que **realmente
discrimina riesgo** debe tener coeficiente **negativo**: más WoE (más "bueno") reduce el
log-odds de incumplimiento. Por eso `expected_beta_sign` es una **constante fija en `negative`**
(no un valor a elegir): es una verdad económica del WoE, no un hiperparámetro.

Cuando una variable queda con beta positivo (signo invertido, económicamente absurdo), `action`
decide qué hacer:

- `exclude` (**default de la librería**) — la saca del modelo.
- `flag` — la conserva pero la marca en el audit-trail.
- `fail` — detiene el ajuste.

`fail_on_forced_inverted=True` protege el caso en que una variable de `force_include` (impuesta
por negocio) termina invertida: en vez de aceptarla, el ajuste falla.

!!! note "El preset relaja a `flag`"
    La corrida de ejemplo usa `sign_policy.action="flag"` e `iv_contribution.action="flag"` en
    lugar del default `exclude`. Es una elección del preset para no descartar variables en un
    dataset didáctico; en producción el default `exclude` es más conservador.

### Stepwise (`stepwise`)

La selección iterativa dentro del ajuste entra/saca variables por significancia estadística:

- `direction` — `bidirectional` (default; revisa entradas y salidas en cada ronda), `forward`,
  `backward` o `none` (alias de `enabled=False`: usa todas las candidatas salvo exclusiones,
  signos e IV-contribution).
- `criterion` — `wald_pvalue` (default), `lr_test` o `both` (más exigente, debe pasar ambos).
- `entry_p_value` / `exit_p_value` — umbrales de entrada y permanencia (default `0.05`). Bajarlos
  hace el modelo más selectivo.
- `max_iter` (default `100`) — rondas del algoritmo stepwise (distinto de `fit_maxiter`, que son
  las iteraciones del optimizador estadístico).
- `min_features` (default `1`) — mínimo de variables finales para aceptar el modelo.

### Guard de concentración de IV (`iv_contribution`)

Evita que el modelo dependa en exceso de una sola variable: `threshold` (default `0.90`) es la
fracción máxima del IV total del modelo que puede aportar una variable individual, con la misma
tríada `action` (`exclude`/`flag`/`fail`). Complementa a `force_include`, `force_exclude` y
`fail_if_no_features` (aborta si la selección final queda vacía en vez de aceptar solo intercepto).

### Interpretación con la corrida de ejemplo

El preset entrega 5 candidatas y conserva las **5** (el stepwise no descarta ninguna). Todas
quedan con beta negativo (`sign_ok=True`), coherente con la política de signos:

| Variable | β | p-value (Wald) | Aporte al IV del modelo |
|---|---|---|---|
| `intercept` (β₀) | −1.1921 | ~3e-190 | — |
| `utilizacion_linea` | −1.1154 | ~8e-12 | 0.103 |
| `antiguedad_meses` | −1.0810 | ~3e-07 | 0.070 |
| `deuda_ingreso` | −1.0783 | ~1e-28 | 0.276 |
| `ingreso_mensual` | −1.0517 | ~3e-42 | 0.514 |
| `mora_max_12m` | −0.9678 | ~3.6e-04 | 0.037 |

Todos los p-values quedan bajo `0.05` (el mayor, `mora_max_12m`, ≈ 3.6e-4). El ajuste convergió
en 6 iteraciones con pseudo-R² de McFadden ≈ **0.097** sobre `n=3961` observaciones de Desarrollo
(924 eventos, tasa observada ≈ 0.233). `ingreso_mensual` concentra ~51% del IV del modelo: es el
factor dominante, y precisamente el tipo de concentración que vigila la política `iv_contribution`.

```python
# DataFrame de coeficientes con inferencia (β, error estándar, z de Wald, p-value, IC).
coefs = study.artifacts.get("model", "coefficients")
print(coefs[["feature", "beta", "p_value", "sign_ok", "iv_contribution"]])

# Estadísticos de ajuste (log-verosimilitud, AIC/BIC, pseudo-R², convergencia).
fit_stats = study.artifacts.get("model", "fit_statistics")
```

---

## 2. Scorecard: escalado a puntaje

El paso `scorecard` convierte el log-odds del modelo en un **puntaje entero** por atributo,
determinista y auditable. La escala se ancla con tres parámetros de negocio (`ScorecardConfig`):

- `pdo` (default `20`) — *Points to Double the Odds*: cuántos puntos separan un odds del doble.
- `target_score` (default `600`) — puntaje asignado a los odds objetivo.
- `target_odds` (default `50`) — odds buenos/malos de referencia (50 buenos por cada malo).
- `score_direction` (default `higher_is_lower_risk`) — un puntaje **mayor** significa **menor**
  riesgo (convención habitual).

### La fórmula de escalado

Nikodym deriva dos constantes de escala a partir de esos tres parámetros:

```
factor = pdo / ln(2)
offset = target_score − factor · ln(target_odds)
```

El intercepto β₀ se reparte de forma uniforme entre las `k` variables finales
(`intercept_allocation="uniform"`): `intercept_share = β₀ / k` y `offset_share = offset / k`. Los
puntos de cada bin (para `higher_is_lower_risk`) son:

```
puntos(bin) = offset_share − factor · ( βⱼ · WoE(bin) + intercept_share )
```

El puntaje total de un registro es la suma de los puntos de sus bins. `rounding_method`
(default `nearest_integer`) redondea los puntos crudos a enteros publicables — afecta el puntaje
final, no solo su presentación. Otros controles: `output_suffix`/`score_column` (nombres de las
columnas de salida), `min_score`/`max_score` con `clip` (recorte auditado de puntajes fuera de
rango) y `point_overrides` (forzar el puntaje de un `feature`/`bin` con `reason` obligatoria para
auditoría).

!!! note "Determinismo y overrides"
    Sin overrides, los puntos salen íntegramente de la fórmula. Un override manual queda trazado
    (variable, bin, puntos, justificación) y es la única forma de romper la derivación por
    fórmula.

### Interpretación con la corrida de ejemplo

Con `pdo=20`, `target_score=600`, `target_odds=50`:

- `factor = 20 / ln(2) ≈ **28.85**`
- `offset = 600 − 28.85 · ln(50) ≈ **487.12**`
- `intercept_share = β₀ / 5 = −1.1921 / 5 ≈ **−0.2384**`

La monotonía es la esperada para `higher_is_lower_risk`: en `antiguedad_meses`, el bin más
riesgoso `(-inf, 12.50)` recibe **94** puntos y el más seguro `[114.50, inf)` recibe **128** —
más antigüedad, más puntaje. Los puntos de `ingreso_mensual` van de **77** a **141** (el rango más
amplio, consistente con ser la variable dominante). En el dataset de ejemplo el puntaje total
observado cae en el rango **446–622**.

```python
# Tabla del scorecard: un registro por (variable, bin) con WoE, beta y puntos publicados.
card = study.artifacts.get("scorecard", "scorecard")
print(card[["feature", "bin_label", "woe", "raw_points", "points"]])

# DataFrame de puntaje total por registro.
score = study.artifacts.get("scorecard", "score")
```

---

## 3. Calibración de PD

La PD que sale del modelo reproduce los *odds* de la muestra de Desarrollo, pero su **nivel** no
tiene por qué coincidir con la tasa central que el banco quiere reconocer. El paso `calibration`
reancla la PD a una tasa aprobada, de forma determinista, sin volver a ajustar el orden de riesgo
cuando el método lo permite.

### Método (`method`)

- `intercept_offset` (**default**) — desplaza el intercepto en log-odds por un escalar `δ`:
  `η_calibrado = η + δ`. **Preserva el ranking** (transformación monótona) y no crea empates.
  `δ` se resuelve numéricamente (búsqueda de raíz con bracketing) para que la media de la PD
  calibrada sobre Desarrollo iguale la tasa objetivo.
- `platt_scaling` / `isotonic` — métodos **supervisados**: reentrenan contra el `target` de
  Desarrollo (regresión logística sobre el logit crudo, o isotónica) y luego reanclan con un
  `post_offset` monótono. Exigen ambas clases presentes en Desarrollo
  (`require_both_classes_for_supervised=True`).

### El ancla: tasa objetivo, fuente y visión

- `anchor_source` (default `development_observed`) — de dónde sale la tasa central:
    - `development_observed` — se **calcula sola** como el promedio de largo plazo observado en
      Desarrollo. En este caso `target_pd` se deja en `None`.
    - `business_input`, `historical_default_rate`, `external_regulatory` — la tasa **no** se
      deriva de los datos; entonces `target_pd` es **obligatorio y explícito** en `(0, 1)`. Sin
      `target_pd`, la configuración **falla** en vez de anclar a un número inventado.
- `anchor_kind` (default `through_the_cycle`) — etiqueta si el ancla es una visión de largo plazo
  (**TTC**) o del momento actual (**PIT**). Debe ser coherente con la fuente: por ejemplo,
  `point_in_time` con `development_observed` es contradictorio (la media observada de Desarrollo
  es una tasa de largo plazo por definición) y la validación lo rechaza.

!!! warning "Fuentes explícitas exigen `target_pd`"
    Con `anchor_source` en `business_input` / `historical_default_rate` / `external_regulatory`,
    omitir `target_pd` es un error de configuración, no un default silencioso. No existe la vieja
    tasa "0.05 por defecto": o se ancla a un número declarado, o falla.

Otros guards: `target_tolerance` (default `1e-12`, error máximo entre media calibrada y objetivo),
`max_abs_offset` (tope opcional al tamaño de `δ`; con `None` solo se audita el offset extremo),
`min_fit_rows` (default `30`) y `fit_partition` fijo en `desarrollo`.

### Through-the-cycle en la práctica

El preset ancla a una tasa **TTC de negocio** deliberadamente por **debajo** de la tasa observada
en Desarrollo:

- `method = intercept_offset`, `anchor_source = business_input`, `anchor_kind = through_the_cycle`
- `target_pd = 0.20`
- tasa observada / media de PD cruda en Desarrollo ≈ **0.2333**
- offset resuelto `δ ≈ **−0.2184**` (log-odds; negativo porque el ancla 0.20 está bajo el 0.233
  observado)
- media de PD calibrada = **0.2000** (iguala el objetivo dentro de tolerancia)
- `ranking_preserved = True`, `ties_created = 0`, `n_fit = 3961`

Esa brecha (0.233 observado → 0.20 anclado) es exactamente el punto de una calibración TTC: la
muestra de Desarrollo refleja un momento del ciclo, y el banco reconoce una PD de largo plazo
distinta. `intercept_offset` traslada el nivel sin tocar el orden de los deudores.

```python
# Parámetros de la calibración (método, ancla, offset, medias).
params = study.artifacts.get("calibration", "parameters")
print(params.method, params.anchor_kind, params.anchor_source)
print("offset (log-odds):", params.offset)
print("PD cruda media (dev):", params.raw_mean_pd_dev)
print("PD calibrada media (dev):", params.achieved_mean_pd_dev)

# Frame con la PD calibrada por registro (columna pd_calibrated, logit calibrado).
calibrated = study.artifacts.get("calibration", "calibrated_pd_frame")
```

---

## Cómo encajan los tres pasos

1. El **modelo** produce coeficientes WoE y la PD cruda (`η`, `pd_raw`), con la política de signos
   garantizando relaciones económicamente sensatas.
2. El **scorecard** traduce esos coeficientes a puntos enteros interpretables por negocio, en una
   escala anclada por `pdo`/`target_score`/`target_odds`.
3. La **calibración** ajusta el nivel de la PD a la tasa central aprobada (TTC o PIT), preservando
   el ranking cuando usa `intercept_offset`.

La PD calibrada es la que consume el paso de **desempeño** (`evaluation_source="pd_calibrated"` en
el preset) y, en fases posteriores, los motores de provisiones **CMF** e **IFRS 9/ECL**. Como toda
la corrida es reproducible por construcción, reejecutar el mismo config con la misma semilla sobre
los mismos datos devuelve estos coeficientes, puntos y offset bit a bit.
