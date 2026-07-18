# SDD-28 — Método interno y la regla del máximo (dataset → preset → UI → informe)

| Campo | Valor |
|---|---|
| **SDD** | 28 |
| **Módulo** | `nikodym.provisioning.internal` (**nuevo**) + transversal: `ui` (datasets, presets, serializers, routes) · `report` · `core.study` · `web/` |
| **Fase** | F8 (post-1.0) |
| **Tanda de producción** | T7 |
| **Estado** | ✅ Implementado; capacidad experimental y gate humano CMF pendiente |
| **Depende de** | SDD-08 (`model`), SDD-10 (`calibration`), SDD-15 (`provisioning/cmf`), SDD-17 (orquestación), SDD-23 (`ui`), SDD-26 (`report`) |
| **Lo consumen** | — (capa de producto) |
| **Autor / Fecha** | DanIA · 2026-07-13 (v2 — v1 descartada, ver §0) |

---

## 0. Por qué existe la v2 de este SDD

La **v1 de este documento estaba equivocada en su premisa central** y no se salva parcheándola. Se conserva la historia porque el error es instructivo:

1. **La v1 daba por buena una regla normativa que no existe.** Diseñaba una demo alrededor de `max(CMF, ECL IFRS 9)` presentado como "el piso prudencial de la CMF". Al verificarlo contra el Compendio (ver §3) resultó **falso**: la regla del máximo del B-1 es entre **método estándar y método interno del banco**, y el Cap. A-2 **excluye** el ECL de NIIF 9 sobre las colocaciones. La "fuente" era un markdown interno que no citaba nada — una cita circular que este proyecto arrastraba desde el SDD-17.
2. **Cinco revisiones adversariales independientes** (normativa, refutación factual, implementabilidad, dataset, producto) coincidieron en que el preset de la v1 producía *"un IFRS 9 que un validador rechazaría y un piso que no puede morder de forma informativa"*.
3. La v1 contenía además **errores factuales propios**: un preset que no validaba (`survival.horizon_periods` no existe), un ejemplo que lanzaba `KeyError`, una lista de goldens mayormente equivocada, y —con ironía— **un gate anti-mentira que buscaba un literal en singular cuando el código lo escribe en plural**, y por tanto habría pasado en verde para siempre.

**La lección, que este SDD adopta como regla de trabajo:** *una afirmación normativa sin capítulo, numeral y circular es una hipótesis, no un requisito.* Igual que una columna verificada por lectura y no por ejecución.

---

## 1. Propósito y responsabilidad

**Qué resuelve en una frase:** que un gerente de riesgo chileno vea, en la demo y en el informe, **la provisión que la norma le obliga a constituir** — el mayor valor entre el **método estándar de la CMF** y **su propio método interno**, alimentado por el scorecard que Nikodym ya construye.

**Por qué esto y no otra cosa.** Es la única versión del producto que a la vez: (a) se apoya en **norma citable** (Circular N° 2.346, Cap. B-1, hoja 10-11); (b) **usa el scorecard** — respondiendo la pregunta que hundía a la v1: *"¿dónde entra mi modelo en el número que reportas?"*; y (c) no exige construir `forward` para ser defendible.

**Situación de partida (verificada en código, no supuesta):**

| Pieza | Estado |
|---|---|
| Motor CMF B-1/B-3 (método **estándar**) | ✅ Completo (`provisioning/cmf/engine.py`, 2.025 LOC, matrices selladas con SHA-256) |
| Capa de orquestación + regla del máximo | ✅ Completa (`provisioning/orchestrator.py`) — pero hoy compara los operandos equivocados |
| **Motor del método INTERNO** | ❌ **NO EXISTE.** Es la pieza nueva de este SDD |
| Dataset con columnas de provisiones | ❌ Los 3 datasets tienen 9 columnas de puro scorecard (`ui/datasets.py:39-49`) |
| Preset / serializer / pantalla / capítulo | ❌ Ninguno |

**Límites explícitos:**
- **No toca los motores CMF ni IFRS 9.** Salvo dos correcciones de bug (§8: D7 markov, y el mensaje del extra inexistente).
- **IFRS 9 sale del camino crítico.** No se borra: cambia de destinatario (§3.4).
- **No diseña la CLI** → SDD-29.
- **No generaliza el wizard a N dominios.**

---

## 2. Contexto y ubicación en la arquitectura

```
dataset (nuevo)
  └─► data ─► binning ─► selection ─► model ─► scorecard ─► calibration
                                          │
                     ┌────────────────────┴─────────────────────┐
                     ▼                                          ▼
         provisioning_internal  (NUEVO)              provisioning_cmf
         PD(calibrada) × LGD × EAD                   PE = PI · PDI · Exposición
         por grupo homogéneo  [B-1 §3]               matrices normativas  [B-1 §3.1.3]
                     └────────────────────┬─────────────────────┘
                                          ▼
                                   provisioning
                        reported = max(estándar, interno)   [B-1, hoja 10-11]
                                          │
                          serializers ────┴──── report (capítulo condicional)
                                │                    │
                           ResultsTab            ReporteTab
```

**El orden de dominios hay que tocarlo** (la v1 afirmaba lo contrario y era falso): `_DEFAULT_DOMAIN_ORDER` (`core/study.py:104-126`) sitúa **`report` en la posición 121, ANTES** de las provisiones (122-124). Con ese orden, `ReportBuilder._collect_cards` **nunca vería** una card de provisiones y el capítulo sería inalcanzable. → **D8**.

---

## 3. Conceptos y fundamentos — la norma, citada

> **Todo lo de esta sección está verificado contra el texto oficial del Compendio de Normas Contables para Bancos (CMF), descargado de `cmfchile.cl`. Ninguna afirmación normativa de este SDD carece de cita.**

### 3.1 La regla del máximo (Cap. B-1, hoja 10-11 — Circular N° 2.346 / 06.03.2024)

> *"La constitución de provisiones se efectuará considerando **el mayor valor obtenido entre el respectivo método estándar y el método interno**. En el caso de uso de los métodos internos evaluados y no objetados, según lo dispuesto en el Anexo N° 1 de este Capítulo, la constitución de provisiones se efectuará de acuerdo con los resultados de su aplicación. **Esta regla se deberá aplicar para cada institución en Chile que consolida con el banco**, separando así la matriz de sus filiales."*

Tres consecuencias duras:
1. El máximo es **estándar vs. interno**. No contra IFRS 9.
2. El nivel es **la entidad** (cada institución en Chile que consolida). **No** por operación, **no** por celda de cartera. La v1 discutía si `portfolio` u `operation`: la norma ya lo resolvió, y ninguna de las dos era la respuesta.
3. Si el método interno está **evaluado y no objetado** por la Comisión, se usa **el interno directamente** (no el máximo). Es un **modo de operación distinto** que el config debe representar (§5).

### 3.2 Ambos métodos son obligatorios (mismo capítulo, párrafo anterior)

> *"en la medida en que esta Comisión disponga de metodologías estándar, los bancos deberán reconocer **provisiones mínimas** de acuerdo con ellas. El uso de esta **base mínima prudencial** para las provisiones, en ningún caso exime a las instituciones financieras de su responsabilidad de contar con **metodologías propias** para determinar provisiones que sean suficientes para resguardar el riesgo crediticio de cada una de sus carteras, **debiendo por tanto disponer de ambos métodos**."*

**Este párrafo es el pitch comercial entero, escrito por el regulador:** el banco *está obligado* a tener un método interno. Nikodym lo construye.

### 3.3 Qué es, textualmente, el método interno (Cap. B-1, §3, "modelos basados en análisis grupal")

> *"los bancos segmentarán a los deudores en **grupos homogéneos** (…) asociando a cada grupo una determinada **probabilidad de incumplimiento** y un **porcentaje de recuperación** basado en un análisis histórico fundamentado. El monto de provisiones a constituir se obtendrá **multiplicando el monto total de colocaciones del grupo respectivo por los porcentajes de incumplimiento estimado y de pérdida dado el incumplimiento**."*

O sea, literalmente:

```
provisión_interna(g) = Exposición(g) · PD(g) · LGD(g)      para cada grupo homogéneo g
```

La norma también admite un **primer método** (estimar directamente el porcentaje de pérdida esperada por grupo, sin descomponer en PD y LGD). Y añade: *"En ambos métodos, las pérdidas estimadas deben guardar relación con **el tipo de cartera y el plazo** de las operaciones."*

**Esto es exactamente lo que el pipeline F1 produce.** La PD sale del scorecard calibrado (`calibration.calibrated_pd_frame`); la agrupación homogénea, del propio scorecard (bandas de score) o de un segmento declarado.

### 3.4 Dónde queda IFRS 9 (Cap. A-2, num. 5)

> *"Lo establecido en el **Capítulo 5.5 (deterioro de valor) de la NIIF9** (…) **no será aplicado respecto de las colocaciones** ("Adeudado por bancos" y "Créditos y cuentas por cobrar a clientes"), en la categoría "Activos financieros a costo amortizado", **ni sobre los "Créditos contingentes"**, ya que los criterios para estos temas **se definen en los Capítulos B-1 a B-3** de este Compendio."*

El ECL de NIIF 9 **no aplica a la cartera de colocaciones de un banco chileno**. El motor `provisioning_ifrs9` **no se tira**: su destinatario son entidades que sí aplican NIIF 9 completa (filiales que reportan ECL a una matriz extranjera; entidades no bancarias; instrumentos distintos de colocaciones). **Fuera del camino crítico de este SDD.**

### 3.5 El número que vende el producto

No es un ratio de conteo. Es **plata**:

```
sobrecosto_del_estándar = Σ provisión_reportada − Σ provisión_interna     [en CLP]
```

*"Tu modelo interno pide X. El estándar de la CMF pide Y. La norma te obliga a constituir el mayor: Z. Ese delta — en pesos, y como % de tus colocaciones — es lo que el modelo estándar te cuesta."*

Esa frase abre presupuesto. `source_a_binding_ratio` es sólo un diagnóstico neutral de cuántas
celdas vincula la fuente A: con nivel `total` hay una sola celda y el ratio sólo puede valer 0 o 1.

---

## 4. API pública (contrato)

### 4.1 El motor nuevo — `nikodym.provisioning.internal`

Sigue la forma de `cmf` e `ifrs9` (registro por `@register`, config Pydantic, engine puro, step que publica artefactos).

```python
class InternalProvisioningEngine:
    config_cls: ClassVar[type[InternalProvisioningConfig]] = InternalProvisioningConfig

    @classmethod
    def from_config(cls, cfg: InternalProvisioningConfig) -> InternalProvisioningEngine: ...

    def calculate(
        self,
        frame: DataFrame,
        *,
        pd_frame: DataFrame,          # de `calibration` (o `model`), PD por operación
        as_of_date: str,
        audit: AuditSink | None = None,
    ) -> InternalProvisionResult: ...
```

**Artefactos** (`domain="provisioning_internal"`): `detail`, `groups`, `summary`, `result`, `card`.

- `groups` es el frame **por grupo homogéneo** — es el objeto que la norma describe y el que un validador va a pedir: `group_id, n_operaciones, exposicion_total, pd_grupo, lgd_grupo, tasa_perdida_esperada, provision`.
- `card.total_internal_provision: Decimal`.

### 4.2 Qué compara el orquestador

`ProvisioningConfig` gana el par de fuentes, en vez de asumir CMF/IFRS 9 (§5.2). La regla del máximo, la reconciliación `Decimal`↔`float` y las políticas de cobertura **ya están implementadas y no se tocan**: el orquestador es agnóstico de qué compara.

### 4.3 Ejemplo end-to-end (corre; el de la v1 no)

```python
from nikodym.ui.presets import provisioning_preset
from nikodym.ui.datasets import materialize
from nikodym.core.config import NikodymConfig
import nikodym

preset = provisioning_preset()
cfg = preset["config"]
cfg["data"]["load"]["source"] = str(materialize(preset["dataset_id"], workdir=workdir))

study = nikodym.run(NikodymConfig.model_validate(cfg))
assert study.run_context.status == "done"

card = study.artifacts.get("provisioning", "card")
card.total_reported_provision            # lo que la norma obliga a constituir
card.metric_sections["provisioning_orchestration"]["source_a_binding_ratio"]
```

---

## 5. Configuración

### 5.1 `InternalProvisioningConfig` (nueva)

| Campo | Tipo | Default | Nota |
|---|---|---|---|
| `type` | `Literal["standard"]` | `"standard"` | |
| `as_of_date_col` | `str` | `"as_of_date"` | fecha única, como CMF |
| `portfolio_col` | `str` | `"cmf_portfolio"` | **una sola columna de cartera** en todo el sistema (la v1 duplicaba `portfolio` y `cmf_portfolio`) |
| `exposure_col` | `str` | `"exposure_amount"` | la misma que CMF: **es la misma exposición vista por dos métodos** |
| `pd_source` | `Literal["calibration","model"]` | `"calibration"` | la PD **calibrada**, no la cruda: el B-1 pide PD "basada en análisis histórico fundamentado" |
| `pd_column` | `str` | `"pd_calibrated"` | |
| `grouping` | `Literal["score_band","segment","provided"]` | `"score_band"` | cómo se forman los **grupos homogéneos** |
| `group_col` | `str \| None` | `None` | obligatorio si `grouping="provided"` o `"segment"` |
| `n_score_bands` | `int` | `10` | `ge=2`; solo con `grouping="score_band"` |
| `lgd` | `InternalLgdConfig` | factory | |
| `method` | `Literal["pd_lgd","direct_loss_rate"]` | `"pd_lgd"` | los **dos** métodos que el B-1 admite (§3.3) |
| `rounding` | `Literal["none","currency_2dp","integer_currency"]` | `"currency_2dp"` | |
| `fail_on_falta_dato` | `bool` | `True` | |

`InternalLgdConfig`: `method: Literal["provided","group_historical"] = "provided"`, `lgd_col: str = "lgd"`, `lgd_floor: float = 0.0`, `lgd_cap: float = 1.0`.

**Aritmética en `Decimal`**, como CMF — es una cifra contable que se compara con otra cifra contable.

### 5.2 `ProvisioningConfig` — qué compara (cambio acotado)

Se añaden dos campos, con defaults que **preservan el comportamiento actual** (retrocompatible):

| Campo | Tipo | Default | Nota |
|---|---|---|---|
| `source_a` | `Literal["provisioning_cmf","provisioning_internal","provisioning_ifrs9"]` | `"provisioning_cmf"` | |
| `source_b` | `Literal[…same…]` | `"provisioning_ifrs9"` | el preset nuevo lo pone en `provisioning_internal` |
| `rule` | `Literal["max","use_internal"]` | `"max"` | `use_internal` = método interno **evaluado y no objetado** por la CMF (§3.1) |
| `comparison_level` | *(existente)* | **`"total"`** en el preset | la norma manda a nivel de **entidad** (§3.1) |

`consume_cmf`/`consume_ifrs9` quedan **deprecados** en favor de `source_a`/`source_b` (se mantienen un ciclo con aviso).

> **`rule="use_internal"` no es una comodidad: es la norma.** Un enum sin ruta real degrada en silencio — si se declara, se implementa.

### 5.3 El preset — `f3-provisiones-consumo`

Preset **nuevo e independiente** (no ampliar el F1: sus secciones son computacionales y moverían el `config_hash` de todas las corridas existentes; verificado en `core/config/hashing.py:24`).

> ### 🔴 La calibración NO se hereda tal cual — invierte el resultado del producto
>
> El preset F1 calibra con `anchor_source: business_input` y **`target_pd: 0.20`**, coherente con su dataset (23 % de default). Sobre la cartera de provisiones (6,9 %), esa ancla **infla la PD casi 3×** y con ella la provisión interna. Medido, corriendo la cadena real:
>
> | Ancla | Provisión interna | Provisión estándar CMF | Regla del máximo |
> |---|---|---|---|
> | `target_pd: 0.20` (heredada de F1) | **878 M** (10,87 %) | 697 M (8,63 %) | manda el **interno** → *el estándar no muerde* |
> | `development_observed` (**correcta**) | **309 M** (3,82 %) | 697 M (8,63 %) | manda el **ESTÁNDAR** → sobrecosto **+389 M (+126 %)** |
>
> Con el ancla heredada la demo cuenta la historia **equivocada** (el modelo interno pide más que la norma, el piso no muerde y el producto no tiene titular). Con el ancla correcta cuenta la real: **el estándar de la CMF le cuesta al banco 389 millones por encima de lo que su propio modelo pediría.**
>
> El preset **debe** fijar `calibration.anchor_source: development_observed` (que además es el default que el SDD-10 resolvió como correcto, D-CAL-2). *Esto no se ve leyendo el código: solo se ve corriendo la cadena entera. Es la razón de ser del gate G2.*

```yaml
# hereda de f1-estandar-consumo: data (dataset nuevo), binning, selection, model, scorecard
calibration:
  # NO heredar el `target_pd: 0.20` del F1 (ver el recuadro de arriba): ancla la PD al 20 % cuando
  # la cartera tiene 6,9 % de default, infla la provisión interna 3x e invierte la regla del máximo.
  anchor_source: development_observed

provisioning_internal:
  as_of_date_col: as_of_date
  portfolio_col: cmf_portfolio
  exposure_col: exposure_amount
  pd_source: calibration
  grouping: score_band
  n_score_bands: 10
  method: pd_lgd
  lgd: { method: provided, lgd_col: lgd }
  rounding: currency_2dp

provisioning_cmf:
  as_of_date_col: as_of_date
  portfolio_col: cmf_portfolio
  # pd_mapping se deja en su default: en cartera `consumer` NO se usa (la categoría la deriva
  # el motor de dpd+producto+flags). Ver §6.2 — `cmf_category` NO va en el dataset.
  exposure: { rounding: currency_2dp }

provisioning:
  source_a: provisioning_cmf
  source_b: provisioning_internal
  rule: max
  comparison_level: total          # la norma: "para cada institución en Chile que consolida"
  require_both: true
  coverage_policy: fail            # un máximo con un solo operando no es un máximo

report:
  sections:
    # NO añadir "provisioning" a required_sections: haría que TODA corrida F1 exija su card.
    # El capítulo es CONDICIONAL (D5).
```

**Ni `survival`, ni `forward`, ni `provisioning_ifrs9` en este preset.** La cadena es F1 → interno + CMF → máximo. Es más corta, más rápida y es la que la norma describe.

---

## 6. Contratos de datos

### 6.1 Regla de oro

> **La lista de columnas de este SDD es una HIPÓTESIS hasta que el gate G1 la ejecute contra los motores reales.** No se escribe una línea del preset ni del front antes de que G1 congele el contrato. (La v1 dio la lista por buena leyendo el código y se equivocó en al menos tres columnas.)

### 6.2 El dataset nuevo — `provisiones_consumo`

Dataset **nuevo**; no se amplían los tres existentes (cambiaría su `data_hash` y arrastraría goldens y fixtures — ya se intentó con EDA y hubo que revertirlo).

**Columnas** (las 9 primeras, idénticas a F1, para que el pipeline de scorecard corra sin cambios):

| Columna | Tipo | Consumidor |
|---|---|---|
| `loan_id` (índice) | str | todos |
| `ingreso_mensual`, `deuda_ingreso`, `utilizacion_linea`, `mora_max_12m`, `antiguedad_meses` | float/int | binning, model |
| `segmento` | str | data |
| `cohorte` | str | partición Dev/HO/OOT |
| `bad_flag` | int | model (target) |
| `as_of_date` | str | CMF, interno, orquestador (**valor único en todo el frame**) |
| `debtor_id` | str | CMF (**consolida consumo a nivel deudor**) |
| `cmf_portfolio` | str | CMF **e** interno — literal `"consumer"` |
| `cmf_product_type` | str | CMF — `creditos_en_cuotas` \| `tarjetas_lineas_otros` \| `leasing_auto` |
| `days_past_due` | int | CMF (bucket de PI) |
| `has_housing_loan_system` | bool | CMF — **nombre hardcodeado** en `cmf/engine.py:504` |
| `system_dpd30_last_3m` | bool | CMF — **nombre hardcodeado** en `cmf/engine.py:505` |
| `exposure_amount` | float (CLP) | CMF **e** interno |
| `lgd` | float ∈ [0,1] | interno |

**Columnas que NO van** (y por qué — cada una es un error de la v1):
- ❌ **`cmf_category`** — en cartera `consumer` el motor **nunca la lee**: deriva la categoría de `(bucket_dpd, hipotecario_sistema, mora_sistema)` (`cmf/engine.py:1023-1071`). Las categorías A1–C6 son de **cartera comercial individual**. Ponerla induce a creer que la categoría de consumo es un input.
- ❌ **`is_default`** — CMF **no la lee** en esta ruta (deriva el incumplimiento de `max(dpd) ≥ 90` por deudor, `engine.py:524`). Sin IFRS 9 en el preset, nadie la consume. Incluirla crea **dos verdades** que pueden discrepar.
- ❌ `portfolio`, `ead`, `eir` — eran para IFRS 9. Fuera del camino crítico.
- ❌ `duration`, `event` — eran para `survival`. Fuera.
- ☠️ **`guarantee_type`, `financial_guarantee_*`, `aval_*`, `contingent_*`** — el motor CMF **olfatea estos nombres** y con la política por defecto (`fail`) **aborta la corrida** (`engine.py:118-135`, `:1320-1344`). **Bautizar mal una columna mata la corrida.**

### 6.3 El proceso generador — coherencia, no seis muestreos independientes

Un solo proceso latente. Las reglas (todas verificables en G1):

1. **Deudores, no operaciones sueltas.** ~4.200 deudores para 6.000 operaciones (≈30 % con ≥2). **Sin esto, la consolidación por deudor del B-1 —la regla central de la norma en consumo— nunca se ejercita.**
2. **`days_past_due` deriva del riesgo latente**, no se muestrea aparte: `P(dpd=0)` decreciente en `prob_bad`; y **nunca `bad_flag=1` con `dpd=0`**.
3. **Coherencia con las features**: `mora_max_12m ≥ days_past_due` (la mora máxima de 12 meses no puede ser menor que la actual). Un revisor cruza esas dos columnas.
4. **Los flags son POR DEUDOR** (CMF hace `any()` sobre el deudor, `engine.py:516-523`), no por operación. `has_housing_loan_system` ≈ 35 % de deudores, **correlacionado negativamente** con el riesgo. `system_dpd30_last_3m` **casi implicado** por la mora propia: quien tiene 60 días de mora contigo, los tiene en el sistema.
   > **Estos dos booleanos SON la provisión CMF de la demo**: la PI va de **3,3 %** (con hipotecario, sin mora sistema) a **19,8 %** (sin hipotecario, con mora sistema) *con la misma mora en el banco*. Un factor **6×**. Si el generador los saca Bernoulli(0.5) independientes, el número final es ruido — y un gerente conoce de memoria qué fracción de su cartera tiene hipotecario en el sistema.
5. **`cmf_product_type` correlacionado con `utilizacion_linea`**: la utilización alta vive en `tarjetas_lineas_otros`. Una utilización de línea del 85 % en un crédito en cuotas no existe. Mix realista (cuotas ≫ tarjetas ≫ leasing), no 33/33/33.
6. **`exposure_amount` explicado por las features**: `≈ ingreso_mensual · deuda_ingreso · κ`, lognormal con cola pesada, en **CLP plausible**. Un revisor cruza saldo contra DTI.
7. **`lgd` distribuida (Beta), nunca constante**, y anclada **por debajo** de la PDI normativa del producto (PDI: 33,2 % leasing / 47,7–56,6 % cuotas / 49,5–60,3 % tarjetas). Racional defendible: *la PDI regulatoria es más conservadora que la LGD interna*. **Y es el mecanismo que hace morder el estándar de forma creíble en vez de arbitraria.**
8. **Tasa de default plausible.** El intercepto de F1 (`-2,2`) hay que **medirlo y recalibrarlo**: un *bad rate* de consumo chileno vive en un dígito, no en un 20 %.
9. **Sin fuga de información.** `bad_flag` es **forward-looking** (ventana de desempeño); `days_past_due` es el **estado en T**. Hacerlos "coherentes" hasta la identidad mete leakage: el scorecard predeciría el presente y saldría con un KS de 65, que **no existe en consumo** y que un gerente lee como fraude. Regla: correlacionados por el riesgo latente, **nunca deterministas** el uno del otro.
10. **Moneda y unidades explícitas** en el informe y la UI: **CLP**, con separador de miles. Una cifra sin unidad es ilegible para quien lee provisiones en millones.

**Determinismo:** `seed` constante por dataset, jamás derivada de reloj o `hash()`.

### 6.4 Serializer

Añadir al mapa `_CARD_KEY_BY_DOMAIN` (`ui/serializers.py:42`): `provisioning_cmf`, `provisioning_internal`, `provisioning` → `"card"`.

Frames a exponer: `provisioning.comparison` (con `comparison_level: total` son **1-2 filas**, trivial), `provisioning_internal.groups` (10 bandas — **es la tabla que un validador pide**) y `provisioning_cmf.summary` (agregado por cartera/categoría).

**NUNCA** los frames por observación (`cmf.detail`, `internal.detail`): 6.000 filas revientan el payload. Van al informe como adjunto.

> **D9 — `Decimal` → JSON.** *Verificado ejecutando:* `ui/serializers._to_json_native` **no conoce `Decimal`** y `_ensure_json_safe` **levanta**, tumbando **todo el payload de `/api/results`**, no solo provisiones. Y `report/renderer` emite `{"unsupported_type": "Decimal"}`.
> **Decisión: coaccionar en la frontera, una sola vez.** `Decimal → float` en `serializers._to_json_native` y en `renderer._display_json_value`/`_canonical_value`. JSON no tiene decimales y la cifra ya viene cuantizada por `rounding: currency_2dp`. **No** se filtra `Decimal` como string al front: TypeScript tampoco puede representarlo y `results-format.ts` (780 LOC) asume `number`.

---

## 7. Decisiones de diseño

### D1 — El producto es `max(estándar, interno)`. IFRS 9 sale del camino crítico.
Fundamento en §3. Es la única versión citable, y la única en la que **el scorecard entra en el número final**.

### D2 — Dataset nuevo, no ampliar los existentes. *(Sin cambios respecto de v1: el argumento del `data_hash` se sostiene.)*

### D3 — Preset nuevo e independiente.
> ⚠️ **El argumento original era falso y hay que decirlo.** Este SDD justificaba el preset nuevo con *"ampliar el F1 movería el `config_hash` de todas las corridas"*. **No se sostiene:** el `config_hash` se mueve igual **por el mero hecho de declarar la sección** en `NikodymConfig`, aunque su default sea `None` — el dump canónico incluye `"provisioning_internal": null`. Verificado al construir el motor: movió 21 goldens de hash en módulos que nada tienen que ver con provisiones.

La decisión **sigue en pie**, por los motivos que sí valen:
- El preset de provisiones necesita **otro dataset** (`provisiones_consumo`), y el estándar F1 debe seguir corriendo sobre el suyo.
- Son **dos casos de uso distintos**: el usuario no piensa "compongo dominios", piensa "quiero mi scorecard" o "quiero mis provisiones".
- Ampliar el F1 obligaría a que el dataset estándar tuviera columnas económico-regulatorias que no le corresponden, y rompería el ejemplo canónico del README.

> **Nota de arquitectura para Cami (no la decido yo):** que añadir un dominio mueva el `config_hash` de **todas** las corridas históricas es un comportamiento **conocido y aceptado** por el proyecto (hay un `GOLDEN_PREVIO_SIN_X` por cada dominio y un test que lo declara "no regresión"). Pero el docstring de `hashing.py` promete un hash *"estable entre versiones"*, y ante la **extensión de la librería** no lo es: cada release con un dominio nuevo invalida la identidad de las corridas anteriores y rompe la idempotencia del inventario (SR 11-7). Excluir del hash las secciones en `None` lo arreglaría de raíz. **Es un cambio de contrato SemVer: decisión de producto, no técnica.**

### D4 — El wizard no se generaliza; se amplía la lista blanca.
`F1_SECTIONS` (`web/src/lib/schema.ts:38`) → `CONFIG_SECTIONS_ALLOWED`, más su entrada en `CONFIG_SECTIONS` (`App.tsx:60`). El tramo schema-driven (**los campos dentro de una sección**) sale gratis. Los **resultados** no tienen forma genérica honesta: un gráfico de la regla del máximo no se deriva de un JSON Schema.
> ⚠️ **Corrección a la v1:** el fixture `web/src/fixtures/schema.json` **NO está stale** — se regeneró hoy (~303 KB) y ya trae las tres secciones de provisiones. El "64 kB contra 259 kB" describía un estado pasado. El test de staleness (G7) **nace en verde** y es una guardia de regresión, no una deuda. Y **debe tolerar** que un extra ausente deje una sección opaca (`schema.py:1132`), o enrojecerá en los jobs mínimos del CI.

### D5 — Capítulo condicional en el informe.
`ChapterSpec` (`report/document.py:176`) gana `requires_domain: str = ""`; `build_sections` (`builder.py:159-168`) hace `continue` si el dominio no tiene card. La numeración ya se reflowa sola.
> ⚠️ **El agujero que la v1 no vio:** `CANONICAL_SECTION_ORDER` (`document.py:255`) se **deriva** de `CHAPTER_SPECS` y está en `__all__` — es **API pública**. Con un capítulo condicional, la constante promete una sección que no siempre se emite, y `test_report_builder.py:89-92` (que compara las secciones emitidas contra ella) **falla**. → `CANONICAL_SECTION_ORDER` debe pasar a ser **el orden de los capítulos posibles**, y el test comparar contra **el subconjunto emitido**.

**Subsecciones `kind="data"`, no un capítulo `kind="prose"` a secas** — `renderer` solo emite tablas y gráficos si `kind == "data"` (`:558`, `:761`). Un capítulo de pura prosa saldría sin la tabla del máximo y sin el gráfico.

**Titular del capítulo: el sobrecosto en CLP** (§3.5), no un ratio.

### D6 — CLI fuera del alcance → SDD-29. *(Sin cambios.)*

### D7 — `markov` como fuente de term-structure de IFRS 9: **BLOQUEAR** (bug real).
Markov emite `row_id = "state:A"` (una curva **por estado**, `markov/term_structure.py:497`); IFRS 9 exige **igualdad exacta de conjuntos** de `row_id` contra la cartera (`ifrs9/engine.py:840-846`). Con datos reales, revienta. El test que lo "cubre" (`test_ifrs9_step.py:222`) **inyecta a mano** una term-structure con `row_id="op1"` en el dominio `"markov"` y **nunca ejecuta `MarkovStep`**.
→ El validador de `IfrsPdConfig` **rechaza** `term_structure_source="markov"`. **Y el test se corrige**: o corre `MarkovStep` de verdad, o se borra la parte que miente.
*(Confirmado de forma independiente por dos revisiones. Sigue vigente aunque IFRS 9 salga del camino crítico: es un bug live en el paquete publicado.)*

### D8 — `report` corre al final del pipeline. **(NUEVO — bloqueador que la v1 negó.)**
Mover `"report"` al final de `_DEFAULT_DOMAIN_ORDER` (`core/study.py:104-126`), después de `validation`. Es lo que el informe **es** semánticamente: una foto de todo lo que corrió. `report` es INFRA (**no** entra al `config_hash`, `hashing.py:24`), así que es un cambio barato.
**Verificar** que el SHA del HTML del preset F1 **no se mueva** (las cards emitidas son las mismas). Si se mueve, regenerar los dos goldens a conciencia.

### D9 — `Decimal` se coacciona en la frontera. *(Ver §6.4.)*

---

## 8. Casos borde y errores

- **`as_of_date` única**: CMF lo exige (`cmf/step.py:247-272`). El generador lo garantiza; el validador de `data` **no** lo cubre.
- **Perímetros**: interno y CMF corren sobre **la misma exposición y la misma columna de cartera** → sin crosswalk. (La v1 duplicaba columnas sin motivo.)
- **Consolidación por deudor**: CMF sube a incumplimiento **todas** las operaciones de un deudor si **alguna** supera 90 dpd; el método interno agrupa **por banda de score**. Esa asimetría es **real y normativa**, y **el informe debe declararla** — si no, parece un bug.
- **Corrida parcial**: con `coverage_policy: fail`, si un motor no corre la corrida termina en `failed` — y el front muestra un mensaje **genérico** (`serializers.py:56-59`). Aceptable en F1; **no** en provisiones, donde el fallo típico será "te falta la columna `lgd`".
  > ⚠️ La v1 exigía "propagar el motivo del `NikodymError`" **sin ver que `run_context` no persiste el mensaje** (`serializers.py:52-59` lo documenta): solo va al audit-trail. Cumplirlo exige tocar `core` (publicar un artefacto `run_error` o persistir el mensaje). **Es un cambio de motor: entra al alcance explícitamente, o se cae del SDD.** No puede quedar como una frase.
- **Mensaje del extra inexistente**: `markov/step.py:626-633` sugiere `nikodym[markov]`, **que no existe**. El extra correcto es **`scoring`** (Markov necesita `scipy.linalg.expm`, y `scipy` vive ahí). *(La v1 iba a "corregirlo" diciendo que Markov corre con deps base: también falso.)*

---

## 9. Reproducibilidad y auditoría

- Motores deterministas (CMF y el interno en `Decimal`, sin RNG). Dataset con `seed` fija.
- Test de determinismo: dos corridas → **mismo `total_reported_provision`**, byte a byte.
- **El audit-trail debe registrar la regla aplicada**: qué método ganó, en qué entidad, y con qué `rule` (`max` vs `use_internal`). Es la traza que un validador de modelos pide primero.
- El capítulo del informe **imprime los warnings** del orquestador
  (`comparacion_incompleta`, `cobertura_imputada_cero`…), no se los traga.

---

## 10. Dependencias

**Ninguna nueva.** El motor interno es `PD × LGD × EAD` en `Decimal`: pandas y la stdlib. CMF, igual. **Calcular las provisiones que la CMF exige no añade una sola dependencia sobre lo que ya se instala para un scorecard** — y eso merece decirse en la doc pública.

---

## 11. Gates — la ruta HASTA EL GERENTE

*Una feature sin dataset, sin preset, sin pantalla y sin capítulo no existe.* Ninguno es opcional.

| Gate | Qué verifica |
|---|---|
| **G0 — Replicación a mano** | **~10 operaciones calculadas en planilla por una persona con criterio de riesgo**, cubriendo las 4 filas del bucket de mora × las 3 PDI de producto × los 2 flags de sistema × un caso en incumplimiento. El test compara **al centavo** contra el motor. *Es lo primero que un validador de modelos pide, y es el único test que acepta como evidencia.* **Sin G0, nada sale a un cliente.** |
| **G1 — El dataset alimenta los motores REALES** | `materialize()` → `CmfProvisioningEngine.calculate()` e `InternalProvisioningEngine.calculate()`. **Congela la lista de columnas de §6.2**, que hoy es hipótesis. Asserta además: mix de producto realista, los 5 buckets de mora poblados, y **`0 < floor_bite < 1`** (que el estándar muerda **y** no muerda). Si falla, **se ajusta el generador, no el preset**. |
| **G2 — La cadena corre** | `nikodym.run(provisioning_preset())` → `status == "done"` **y** `total_reported_provision > 0` **y** `total_internal_provision > 0`. Con **presupuesto de tiempo medido** (ver R2). |
| **G3 — La UI puede lanzarla** | `POST /api/run` → 200 + las tres secciones no nulas en `/api/results`. |
| **G4 — El gerente lo VE** | La demo renderiza la sección con **el sobrecosto en CLP**. Verificación **en el navegador**. ⚠️ No hay Playwright en el repo: o se añade un harness, o G4 es checklist manual **declarado como tal** (no un gate que finge serlo). |
| **G5 — El informe lo DICE** | El capítulo existe con la cifra, **y** el informe ya no dice que las provisiones "corresponden a fases posteriores". ⚠️ El literal real es **"corresponden"** (plural), en **tres** sitios: `prose.py:1192`, `_exec_summary.html.j2:42` **y el fixture `web/src/fixtures/demo/report.html`**. *(El gate de la v1 buscaba el singular: habría pasado en verde para siempre.)* **Esas frases son VERDADERAS hoy y solo pueden borrarse cuando el capítulo exista** — borrarlas antes las volvería falsas. |
| **G6 — Demo estática** | Fixtures de una **corrida real**, nunca inventados. **D10:** un **único** fixture set, el de provisiones (que es superset de F1) — no dos (ahorra ~1,1 MB y el selector de presets). |
| **G7 — Fixture del schema no stale** | Guardia de regresión (nace en verde, ver D4). Debe tolerar secciones opacas por extras ausentes. |
| **G8 — Coherencia del material público** | **NUEVO.** Ninguna superficie (README, docs, landing, glosario) puede afirmar algo que el producto no haga, **ni al revés**. Cuando la UI muestre provisiones, seis superficies que hoy dicen "solo el scorecard tiene UI" pasarán a ser falsas. *En un proyecto cuya historia son tres correcciones públicas, esto es bloqueante.* |

**Regla:** cada test nuevo **debe fallar con el código viejo**. Uno que pasa antes y después no prueba nada.

**Goldens** *(la lista de la v1 estaba mayormente equivocada; esta está verificada)*: se rompen los **dos SHA-256 del HTML** (`test_report_renderer.py:48`, `test_report_step.py:74`) — por borrar el literal de `_exec_summary`, no por el capítulo — y **`test_report_builder.py:89-92`** (`CANONICAL_SECTION_ORDER`, ver D5). **No** se rompen: el dict del manifest (es autorreferencial) ni `_CANONICAL_IDS` (ese bundle se construye a mano).

---

## 12. Plan de trabajo y riesgos

### Orden (T0 bloquea todo; T7-T9 van en paralelo desde el día 1)

| # | Tarea | Bloquea | Bloqueada por |
|---|---|---|---|
| **T0** | Decisiones cerradas en este SDD (D8 orden de `report`, D9 `Decimal`, nivel = entidad, roles de columnas) | todo | — |
| **T1** | Dataset: `_COLUMNS` per-dataset + generador con los invariantes de §6.3 | T2 | T0 |
| **T1b** | *(paralelo)* `Decimal` → JSON en serializer y renderer | T3, T4 | T0 |
| **T2** | **Motor `provisioning.internal`** + **G0** + **G1**. **Congela el contrato de columnas.** | T3 | T1 |
| **T3** | `ProvisioningConfig.source_a/source_b/rule` + preset + rutas REST + **G2/G3** | T5 | T2 |
| **T4** | *(paralelo desde T2)* Informe: capítulo condicional, `document.py`/`builder.py`/`prose.py`, D8, goldens. **G5** | — | T2, T1b |
| **T5** | Front: DTOs (**derivados de un payload real, nunca inventados**), `ResultsTab`, charts, selector de preset | T6 | T3 |
| **T6** | Fixtures + `scripts/gen_schema_fixture.py` + script de captura. **G6/G7** | — | T5, T4 |
| **T7-T9** | *(paralelo, día 1)* D7 (bloquear markov + arreglar el test que miente) · mensaje `nikodym[markov]` → `scoring` · **G8** | — | — |

**Cuello de botella real: T2.** Hasta que el dataset alimente los motores de verdad, nada aguas abajo significa nada.

### Riesgos

**R1 — La credibilidad del dataset (el mayor, y no es técnico).** Un dato inverosímil —un default con cero días de mora, una LGD constante, un KS de 65, un mix de producto 33/33/33— lo detecta un gerente **en segundos**, y a partir de ahí no vuelve a creer ninguna cifra de la pantalla. **Mitigación:** los invariantes de §6.3 son parte de G1, y **el dataset lo revisa una persona con criterio de riesgo (Cami/Eduardo) antes de publicarlo.**
> ⚠️ Y un riesgo que la v1 se **auto-infligió**: escribió *"la cartera debe tener celdas donde el piso muerda y donde no, si no la demo no demuestra nada"*. Eso, leído por un due diligence, es **la instrucción escrita de calibrar los datos para que el resultado salga bonito**. La formulación correcta —y la que este SDD adopta— es: **el dataset se calibra contra los agregados públicos que la CMF publica** (índice de riesgo y morosidad del sistema), y **el informe declara que es sintético y muestra esa comparación**. Un sintético que cae dentro del rango del sistema es defendible. Uno tuneado para el titular, no.

**R2 — Tiempo de corrida (medido, no estimado).** El preset F1 tarda **5,8 s**. Sin `survival` (que costaba 6,5 s y 126.000 filas person-period), la cadena de este SDD es **notablemente más barata que la de la v1**. Aun así, `POST /api/run` es **síncrono y bloquea el event loop** de FastAPI: dos usuarios concurrentes cuelgan el servidor. **Medir en G2 y fijar presupuesto.** *(Nota: la demo pública es estática — `demoRunPipeline()` devuelve un resultado enlatado —, así que este riesgo no afecta a la reunión de Eduardo, solo a un despliegue con backend.)*

**R3 — Procedencia de las matrices CMF.** Están **transcritas del compendio con asistencia de IA y verificación visual, sin validar por la CMF** — y así está confesado en el README y la landing. Un gerente pregunta *"¿de dónde salen estos parámetros?"* en los primeros cinco minutos. **Para una cartera de consumo se usa UNA sola matriz** (`consumer_standard_v2025`). **Validarla a mano contra el compendio, celda por celda, es el trabajo de mayor retorno de todo el track** — y G0 lo materializa.

**R4 — El front es la mitad del esfuerzo** y la más fácil de subestimar: DTOs, formateadores, sección, charts, fixtures. Nada de eso se deriva del schema.

### Lo que este SDD deja fuera, explícitamente
- IFRS 9 + `forward` (PIT real y escenarios ponderados) → **fase 2**, con destinatario distinto (§3.4). El mapa técnico ya está hecho: la cadena `survival → forward → ifrs9` **cierra a nivel de contratos**, no tiene dependencias nuevas, y le falta un único test de integración que nunca existió.
- Markov como fuente de term-structure (exige resolver estado→operación).
- Provisiones por operación en la UI (el detalle va al informe).
- CLI → SDD-29.
