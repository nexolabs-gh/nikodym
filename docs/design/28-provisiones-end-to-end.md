# SDD-28 — Provisiones alcanzables (dataset → preset → UI → informe)

| Campo | Valor |
|---|---|
| **SDD** | 28 |
| **Módulo** | Transversal: `nikodym.ui` (datasets, presets, serializers) + `nikodym.report` + `web/` |
| **Fase** | F8 (post-1.0, mejora continua) |
| **Tanda de producción** | T7 |
| **Estado** | Borrador |
| **Depende de** | SDD-15 (`provisioning/cmf`), SDD-16 (`provisioning/ifrs9`), SDD-17 (orquestación), SDD-18 (`survival`), SDD-23 (`ui`), SDD-26 (`report`) |
| **Lo consumen** | — (es la capa de producto; no lo consume ningún módulo) |
| **Autor / Fecha** | DanIA · 2026-07-13 |

---

> **Este SDD no diseña un motor: los tres motores ya existen y funcionan.** Diseña la **ruta que va desde un dato hasta el gerente de riesgo**, que hoy no existe. Es el SDD que la propia historia del proyecto exige: una feature sin dataset, sin preset, sin pantalla y sin capítulo **no existe para el usuario**, por mucho motor que tenga detrás (nos pasó con el export editable, con EDA y con el `?ref`).

## 1. Propósito y responsabilidad

**Qué resuelve en una frase:** que un gerente de riesgo pueda ver, en la demo y en el informe, la provisión de su cartera bajo **CMF B-1**, bajo **IFRS 9 (ECL)** y bajo el **piso prudencial `max(CMF, IFRS9)`** — sin escribir una línea de Python.

**Situación de partida (verificada en el código, no supuesta):**

| Capa | Estado hoy | Evidencia |
|---|---|---|
| Motor CMF | ✅ Completo (2.025 LOC, matrices normativas versionadas con SHA-256) | `provisioning/cmf/engine.py` |
| Motor IFRS 9 | ✅ Completo (PD PIT, LGD, EAD, staging, ECL) | `provisioning/ifrs9/engine.py` |
| Orquestador / piso | ✅ Completo, con tests end-to-end de los 3 motores | `provisioning/orchestrator.py`, `tests/unit/test_provisioning_step.py:252` |
| **Dataset** | ❌ **Ninguno de los 3 datasets sintéticos tiene una sola columna de provisiones** | `ui/datasets.py:39-49` |
| **Preset** | ❌ Los 3 dominios en `None` | `ui/presets.py:319-321` |
| **Serializer** | ❌ No están en el mapa | `ui/serializers.py:42-50` |
| **Pantalla (config)** | ❌ No están en la lista blanca del front | `web/src/lib/schema.ts:38`, `web/src/App.tsx:60` |
| **Pantalla (resultados)** | ❌ Sin DTO, sin helpers, sin sección | `web/src/components/ResultsTab.tsx` |
| **Capítulo del informe** | ❌ Y además el informe **declara por escrito que provisiones "corresponde a fases posteriores"** | `report/prose.py:1189-1192`, `templates/_exec_summary.html.j2:42` |

**Responsabilidad única:** cerrar los seis ❌ de arriba, en ese orden (es una cadena: sin dataset no hay corrida, sin corrida no hay resultado, sin resultado no hay capítulo).

**Límites explícitos — qué NO hace este SDD:**
- **No toca los motores.** Excepción única y deliberada: el validador que bloquea `markov` como fuente de term-structure (§8, D7) y el test que lo enmascara.
- **No diseña la CLI.** Va a un SDD-29 propio (§12, D6).
- **No incorpora `stress`, `markov` ni `validation` a la UI.** El mandato es multi-dominio, pero se ejecuta **de a un dominio por vez** y provisiones es el primero (es el dolor regulatorio del gerente chileno).
- **No generaliza el wizard a N dominios.** Ver §7, D4: el tramo schema-driven ya resuelve los formularios; generalizar la lista blanca es un cambio de dos líneas. Lo caro está en Resultados, y ahí no hay atajo genérico honesto.

## 2. Contexto y ubicación en la arquitectura

La cadena completa que este SDD debe dejar corriendo, de punta a punta:

```
dataset sintético (nuevo)
  └─► data ──► binning ──► selection ──► model ──► scorecard ──► calibration
                                           │
                                           ├─► survival ──────► term_structure
                                           │                        │
                                           ├─► provisioning_ifrs9 ◄─┘   (ECL)
                                           └─► provisioning_cmf         (PE = PI·PDI·Exp)
                                                        │
                                                        └─► provisioning  ──► max(CMF, IFRS9)
                                                                  │
                                                     serializers ─┴─ report (capítulo condicional)
                                                          │             │
                                                       ResultsTab    ReporteTab
```

El orden lo garantiza `_DEFAULT_DOMAIN_ORDER` (`core/study.py:104-126`), que ya sitúa `provisioning_ifrs9 → provisioning_cmf → provisioning` al final. **No hay que tocar la orquestación**: el pipeline se deriva de las secciones no-`None` del config, así que basta con que el preset las declare.

**Por qué `survival` y no `markov` ni `forward`** (decisión D1, ver §7):
- `survival` exige **2 columnas nuevas** (`duration`, `event`) sobre un cross-section que ya existe, y sus `row_id` **son los de la cartera** (`survival/discrete_hazard.py:497`), que es justo lo que exige el gate `_check_row_coverage` de IFRS 9 (`ifrs9/engine.py:840-846`).
- `markov` exige reestructurar el dato a **panel** (≥2 filas por operación, `id`+`time`+`state`) y —crítico— emite `row_id = "state:A"`, **una curva por estado, no por operación**. No encaja con IFRS 9 (§8, D7).
- `forward` es estrictamente el más caro: exige que survival o markov **ya hayan corrido**, más un histórico macro de ≥12 períodos, más 3 escenarios con shocks o paths.

## 3. Conceptos y fundamentos

Los tres números que el informe tiene que poner delante del gerente:

1. **Provisión CMF (B-1)** — `PE = PI · PDI · Exposición`. Modelo estándar, matrices normativas de la CMF. Es lo que el banco **reporta al regulador**.
2. **ECL IFRS 9** — pérdida esperada descontada a EIR, 12 meses (Stage 1) o lifetime (Stage 2/3), ponderada por escenarios. Es lo que el banco **contabiliza**.
3. **Piso prudencial** — `provisión_reportada = max(CMF, ECL)` por celda de comparación. Es la regla que el banco **debe cumplir** (`ESPECIFICACIONES.md §5.4`) y es el diferencial de Nikodym: nadie empaqueta los dos motores y su reconciliación.

**El indicador que vende el producto** ya lo calcula el orquestador y hoy nadie lo ve: `floor_bite_ratio` (`orchestrator.py:525-552`) = fracción de celdas donde **el piso CMF muerde** (es decir, dónde la norma obliga a provisionar más de lo que la contabilidad IFRS 9 pediría). Esa cifra es la respuesta a la pregunta que un gerente hace en los primeros dos minutos. **Debe ser el titular del capítulo del informe y de la sección de la UI** (§6, §7).

Reconciliación numérica: CMF trabaja en `Decimal` y IFRS 9 en `float`; el orquestador reconcilia con `numeric_reconciliation="decimal_quantize"` y `tie_tolerance=1e-9`. Ese detalle no se expone al usuario, pero **sí** se declara en el capítulo de metodología (es exactamente el tipo de rigor que un validador de modelos busca).

## 4. API pública (contrato)

### 4.1 Presets — de uno a varios (compatible hacia atrás)

`ui/presets.py` hoy expone **una** función y **un** preset. Se amplía sin romper la firma existente:

```python
__all__ = ["standard_preset", "provisioning_preset", "list_presets", "get_preset"]

STANDARD_PRESET_ID    = "f1-estandar-consumo"       # existente, INTACTO
PROVISIONING_PRESET_ID = "f3-provisiones-consumo"   # nuevo

def standard_preset() -> dict[str, Any]: ...        # existente, INTACTO (compat: README, docs, tests)
def provisioning_preset() -> dict[str, Any]: ...    # nuevo, misma forma: {id, name, description, config, dataset_id}
def list_presets() -> list[dict[str, Any]]: ...     # descriptores SIN el config (para el selector de la UI)
def get_preset(preset_id: str) -> dict[str, Any]: ...  # levanta UiPresetError si no existe
```

**Contrato del descriptor** (idéntico al actual, para que el front no cambie de forma): `{id, name, description, config, dataset_id}`.

### 4.2 REST — un endpoint nuevo, uno generalizado

| Método | Ruta | Estado | Contrato |
|---|---|---|---|
| GET | `/api/config/presets` | **nuevo** | `[{id, name, description, dataset_id}]` — sin el config (barato) |
| GET | `/api/config/preset` | **se mantiene** | Devuelve el estándar. **No se rompe**: es la ruta que usa el bootstrap del front y el README. |
| GET | `/api/config/preset/{preset_id}` | **nuevo** | `{config, config_hash, dataset_id, name, description}` — 404 si no existe |

**No se toca `POST /api/run`.** El preset de provisiones se ejecuta por la misma ruta síncrona. (Ver §12, R2: el riesgo de tiempo de corrida.)

### 4.3 Ejemplo de uso end-to-end (pseudocódigo)

```python
from nikodym.ui.presets import provisioning_preset
from nikodym.ui.datasets import materialize
from nikodym.core.config import NikodymConfig
import nikodym

preset = provisioning_preset()
data_path = materialize(preset["dataset_id"], workdir=workdir)   # -> provisiones_consumo.parquet
cfg = preset["config"]
cfg["data"]["load"]["source"] = str(data_path)

study = nikodym.run(NikodymConfig.model_validate(cfg))
assert study.run_context.status == "done"

card = study.artifacts.get("provisioning", "card")
card.total_reported_provision      # el número que el gerente reporta
card.metric_sections["floor_bite_ratio"]   # dónde muerde el piso CMF
```

## 5. Configuración (schema Pydantic)

**No se crean configs nuevas.** Los tres dominios ya tienen su schema Pydantic completo (`CmfProvisioningConfig`, `IfrsProvisioningConfig`, `ProvisioningConfig`) y `build_full_json_schema()` (`core/config/schema.py:1124`) **ya los expone en `/api/schema`** — el front simplemente no los mira.

Un solo cambio de schema, en `IfrsPdConfig` (§8, D7): el validador debe **rechazar** `term_structure_source="markov"` mientras el `row_id` de Markov sea por estado.

### 5.1 El preset de provisiones (valores defendibles)

Config del preset nuevo, sobre el dataset nuevo. Los valores no son arbitrarios: son los que hacen que la corrida sea **explicable** ante un gerente.

```yaml
# hereda de f1-estandar-consumo: data (dataset nuevo), binning, selection, model, scorecard, calibration
survival:
  method: discrete_hazard        # statsmodels (extra `scoring`, ya instalado); NO lifelines
  input:
    duration_col: duration
    event_col: event
  horizon_periods: 36            # 3 años: cubre el lifetime de una cartera de consumo

provisioning_cmf:
  as_of_date_col: as_of_date
  portfolio_col: cmf_portfolio
  pd_mapping:
    method: provided_cmf_category   # el dataset trae la categoría; NO derivamos PD→categoría en la demo
  exposure:
    rounding: currency_2dp

provisioning_ifrs9:
  pd:
    term_structure_source: survival
    pit_mode: ttc_only            # sin `forward`, no hay factor sistémico ni escenarios: NO fingimos PIT
    horizon_12m_periods: 12
  lgd:  { method: provided }      # LGD viene en el dataset; estimarla exigiría datos de recupero
  ead:  { method: provided }
  staging:
    dpd_sicr_backstop: 30
    dpd_default_backstop: 90
  scenarios:
    source: single                # coherente con ttc_only
  ecl:
    rounding: currency_2dp

provisioning:
  comparison_level: portfolio     # el gerente compara por cartera, no por operación
  require_both: true
  coverage_policy: fail           # si un motor no corrió, NO inventamos un piso a medias
```

**Dos decisiones honestas que hay que defender ante el revisor:**
- **`pit_mode: ttc_only`.** Sin el dominio `forward` no hay escenarios macro ni factor sistémico. Declarar `consume_pit` o `apply_vasicek` sin esos datos sería **fingir un PIT que no existe** — la clase exacta de mentira que este proyecto se prohíbe. El informe debe **decirlo**: "la PD es TTC; el ajuste PIT/forward-looking requiere el módulo `forward`, fuera del alcance de esta corrida".
- **`coverage_policy: fail`.** Un piso calculado con un solo motor no es un piso. Preferimos que la corrida se caiga a que emita un número que parece un piso y no lo es.

## 6. Contratos de datos (I/O)

### 6.1 El dataset nuevo — `provisiones_consumo`

**Decisión D2: se crea un dataset NUEVO; no se amplían los tres existentes.** Ampliar `consumo_comportamiento` cambiaría su contenido y con él el `data_hash` → arrastraría goldens y fixtures de toda la suite. **Ya se intentó exactamente eso con EDA y hubo que revertirlo** (ver `HANDOFF.md`, "callejones sin salida"). No se repite el error.

Esquema (superset del de F1; las 9 primeras columnas son idénticas para que el pipeline de scorecard corra sin cambios):

| Columna | Tipo | Rol | Consumidor |
|---|---|---|---|
| `loan_id` | str (índice) | id | todos — **es el `row_id` que cruza survival ↔ IFRS 9** |
| `ingreso_mensual`, `deuda_ingreso`, `utilizacion_linea`, `mora_max_12m`, `antiguedad_meses` | float/int | feature | binning, model |
| `segmento` | str | segment | data |
| `cohorte` | str | cohort | partición Dev/HO/OOT |
| `bad_flag` | int | target | model |
| `duration` | int | — | **survival** (períodos hasta evento o censura) |
| `event` | int (0/1) | — | **survival** (1 = default, 0 = censurado) |
| `as_of_date` | str `YYYY-MM-DD` | — | CMF, IFRS 9, orquestador (**una sola fecha en todo el frame**) |
| `debtor_id` | str | — | CMF (consolida consumo a nivel deudor) |
| `cmf_portfolio` | str | — | CMF (`consumer`) |
| `cmf_category` | str | — | CMF |
| `cmf_product_type` | str | — | CMF |
| `days_past_due` | int | — | CMF **e** IFRS 9 (staging: backstops 30/90) |
| `exposure_amount` | float | — | CMF |
| `has_housing_loan_system` | bool | — | CMF (cartera consumo) |
| `system_dpd30_last_3m` | bool | — | CMF (cartera consumo) |
| `is_default` | int (0/1) | — | CMF **e** IFRS 9 (Stage 3) |
| `portfolio` | str | — | IFRS 9 (+ crosswalk con `cmf_portfolio` en el orquestador) |
| `ead` | float | — | IFRS 9 (`method: provided`) |
| `lgd` | float ∈ [0,1] | — | IFRS 9 (`method: provided`) |
| `eir` | float | — | IFRS 9 (descuento del ECL) |

> ⚠️ **Esta lista se derivó leyendo `cmf/engine.py` e `ifrs9/engine.py`, no corriéndolos.** La implementación **no puede darla por buena**: el gate **G1** (§11) es un smoke que corre los motores reales contra el dataset y ajusta la lista con lo que el motor pida de verdad. *Una lista de columnas verificada por lectura es una hipótesis, no un contrato.*

**Coherencia interna obligatoria** (si no, el dataset es una mentira estadística y el gerente lo va a notar):
- `days_past_due` debe ser **coherente con `bad_flag`/`is_default`**: un `is_default=1` con `days_past_due=0` es un absurdo que el propio motor puede aceptar y un validador humano no.
- `duration`/`event` deben **derivarse del mismo proceso** que genera `bad_flag`, no muestrearse aparte: si un caso tiene `event=1`, su `bad_flag` debe ser 1.
- `cmf_category` debe correlacionar con `days_past_due` (la norma la define, en buena parte, por mora).
- `exposure_amount` y `ead` deben ser del mismo orden (son la misma exposición vista por dos normas); no idénticas necesariamente, pero **no puede haber un factor 10 entre ellas**.
- La cartera debe tener **casos en los tres stages** de IFRS 9 y celdas donde el piso CMF **muerda y donde no** — si no, el `floor_bite_ratio` sale 0 o 1 y la demo no demuestra nada.

Determinismo: `seed` constante (como los otros tres, `ui/datasets.py:53`), jamás derivada de reloj o `hash()`.

### 6.2 Serializer

Añadir al mapa `_CARD_KEY_BY_DOMAIN` (`ui/serializers.py:42`):
```python
"provisioning_cmf": "card", "provisioning_ifrs9": "card", "provisioning": "card",
```
Y en `_augment_with_rich_artifacts` (`serializers.py:96`), los frames que la UI necesita graficar:
- `provisioning.comparison` → tabla del piso por celda (CMF vs ECL vs reportado, con `binding`)
- `provisioning_ifrs9.staging` → distribución por stage (agregada, **no** por operación)
- `provisioning_cmf.summary` → provisión por cartera/categoría

**Regla dura:** los frames **por observación** (el `detail` de CMF y el `ecl_term_structure` de IFRS 9) **NO** van al `results.json`. Con 6.000 operaciones × N períodos, el payload explota y el front se cae. Van al informe como adjunto, vía `PER_OBSERVATION_TABLES` (`report/document.py:136`).

## 7. Algoritmos y flujo — las cinco decisiones de diseño

### D1 — Los tres motores, no uno. Term-structure vía `survival`.
**Decidido:** el preset corre CMF **e** IFRS 9 **y** el piso.
**Alternativa descartada — CMF solo:** es más barato (CMF corre standalone, sin survival) pero deja fuera el ECL y, sobre todo, **el piso prudencial, que es el único diferencial real**. CMF a secas es una calculadora de matrices que un banco resuelve en Excel; no justifica una reunión. Si el MVP no muestra el `max()`, no muestra Nikodym.

### D2 — Dataset nuevo, no ampliar los existentes.
Ya justificado en §6.1 (el `data_hash` y el precedente de EDA).

### D3 — Preset nuevo e independiente, no un preset que compone dominios.
**Decidido:** `f3-provisiones-consumo` es un preset completo y separado.
**Alternativa descartada — ampliar `f1-estandar-consumo` con las secciones de provisiones:** cambiaría el `config_hash` de **todas** las corridas F1 existentes, obligaría a que el dataset estándar tuviera columnas de provisiones (volviendo a D2) y rompería el ejemplo canónico del README y de `getting-started.md`.
**Alternativa descartada — un preset "componible" con flags:** es la abstracción prematura clásica. Con **dos** presets no hay evidencia de cuál es el eje de composición correcto. Se decide cuando haya un tercero (stress) y se vea el patrón real.
El usuario no piensa en "dominios que compone": piensa en **"quiero calcular mis provisiones"**. Un preset = un caso de uso.

### D4 — El wizard NO se generaliza; se amplía la lista blanca.
**Decidido:** renombrar `F1_SECTIONS` → `CONFIG_SECTIONS_ALLOWED` (`web/src/lib/schema.ts:38`) y añadir las tres secciones nuevas, más su entrada en `CONFIG_SECTIONS` de `App.tsx:60` (label, icono, descripción).
**Por qué no generalizar:** el tramo genuinamente schema-driven —**los campos dentro de una sección**— ya funciona y saldrá gratis (`form-engine.ts` resuelve widgets desde el JSON Schema). Lo que está hardcodeado es (a) la lista blanca de secciones, que es **una línea**, y (b) los **resultados**, que no tienen forma genérica honesta: un gráfico de piso prudencial no se deriva de un schema. Generalizar (b) sería inventar un motor de visualización genérico para renderizar exactamente una pantalla. **No se hace.**

**Deuda que este SDD SÍ paga** (porque ya nos mordió): el fixture `web/src/fixtures/schema.json` es un snapshot **manual** de `/api/schema` que ya se desincronizó en silencio durante decenas de commits (64 kB contra 259 kB reales). Con un dominio más, el riesgo se dobla. → **Se versiona `scripts/gen_schema_fixture.py`** y se añade un test que falla si el fixture está stale. Sin eso, el modo demo mostrará un schema viejo y nadie se enterará.

### D5 — Capítulo condicional en el informe (el único punto de extensión nuevo).
La estructura de capítulos es declarativa (`CHAPTER_SPECS`, `report/document.py:191`) pero **`build_sections` los emite todos, siempre** (`builder.py:159-168`): no existe el concepto de capítulo condicional. Se añade:

```python
class ChapterSpec(BaseModel):
    ...
    requires_domain: str = ""     # nuevo: si está, el capítulo solo se emite si el dominio corrió
```
```python
# builder.build_sections
if spec.requires_domain and spec.requires_domain not in bundle.cards:
    continue                       # la numeración ya se reflowa sola (builder.py:160-166)
```

Capítulo nuevo: `ChapterSpec(id="provisions", title="Provisiones", kind="prose", requires_domain="provisioning")`, con subsecciones para CMF, IFRS 9 y el piso. **Titular del capítulo: el `floor_bite_ratio`** (§3), no una tabla.

**Y hay que borrar dos afirmaciones que hoy son falsas** en cuanto este SDD se implemente:
- `report/prose.py:1189-1192` — el párrafo de Limitaciones que dice que el cálculo de provisiones "corresponde a fases posteriores".
- `report/templates/_exec_summary.html.j2:42` — lo mismo, en el resumen ejecutivo.

Que el informe del producto declare que las provisiones no están, mientras la landing las promete, es la misma clase de contradicción que ya nos costó dos correcciones públicas. **No se puede lanzar el capítulo sin borrar esas dos frases.**

## 8. Casos borde y manejo de errores

### D7 — `markov` como fuente de term-structure: BLOQUEAR (bug real, no hipótesis)

`IfrsPdConfig.term_structure_source` acepta `Literal["survival", "markov", "forward"]`. **La rama `markov` no funciona con la salida real de Markov:**
- Markov emite `row_id = f"state:{state}"` — una curva **por estado** (`markov/term_structure.py:497`).
- IFRS 9 exige **igualdad exacta de conjuntos** entre los `row_id` de la term-structure y los de la cartera (`ifrs9/engine.py:840-846`).
- Con una cartera real, esa combinación **levanta un error de cobertura**. Nunca produce un ECL.

**Y el test que la "cubre" la enmascara:** `tests/unit/test_ifrs9_step.py:222` (`test_survival_y_markov_mismo_ecl`) inyecta a mano una term-structure con `row_id="op1"` en el dominio `"markov"` — **nunca ejecuta `MarkovStep`**. Es exactamente el patrón que ya nos costó caro: *un test que fabrica un estado que el código real nunca produce no caza nada*.

**Decisión:** hasta que se resuelva el mapeo estado→operación (SDD futuro), el validador de `IfrsPdConfig` **rechaza `term_structure_source="markov"`** con un mensaje explícito. Un enum declarado sin ruta real degrada en silencio, y el step no debe ser más permisivo que el motor.
**Y el test se corrige**: o corre `MarkovStep` de verdad (y entonces documenta el fallo), o se borra la parte que miente.

### Otros bordes
- **`as_of_date` múltiple**: CMF exige una única fecha en el frame (`cmf/step.py:247-272`). El generador del dataset debe garantizarlo; el validador de `data` no lo cubre.
- **Perímetros desalineados**: con `comparison_level: portfolio`, CMF agrupa por `cmf_portfolio` e IFRS 9 por `portfolio`. Si las taxonomías difieren, el orquestador exige `portfolio_crosswalk`. En el dataset sintético **se usa la misma taxonomía** para no necesitarlo (pero el SDD lo declara para el caso de datos reales).
- **Corrida parcial**: si `provisioning_cmf` corre y `provisioning_ifrs9` falla, con `coverage_policy: fail` la corrida termina en `failed`. El front hoy muestra un mensaje **genérico** (`serializers.py:56-59`, `_FAILURE_MESSAGE`): el usuario no sabrá **por qué**. Eso es aceptable en F1 (scorecard) y **no lo es en provisiones**, donde el fallo típico será "te falta la columna `eir`". → **El SDD exige propagar el motivo del `NikodymError` de validación de entrada** al payload (solo los errores de contrato de datos, no las trazas internas).
- **`nikodym[markov]` no existe**: `markov/step.py:626-633` sugiere instalar un extra que **no está en el `pyproject.toml`**. Corregir el mensaje (Markov solo necesita deps base).

## 9. Reproducibilidad y auditoría

- Dataset: `seed` constante por dataset; el parquet se cachea y `materialize()` es idempotente.
- Los tres motores son **deterministas** (CMF en `Decimal`, sin RNG; el orquestador tampoco tiene RNG). `survival/discrete_hazard` usa statsmodels con semilla del `Study`.
- Test de determinismo obligatorio: dos corridas del preset → **mismo `total_reported_provision`, byte a byte** (ya existe el patrón en `test_provisioning_step.py:273`).
- Audit-trail: el orquestador ya emite las notas `FALTA-DATO-PROV-*` y los warnings por celda (`piso_incompleto`, `cobertura_imputada_cero`, `ifrs9_ausente`, `cmf_ausente`). **El capítulo del informe debe imprimirlos**, no tragárselos: si el piso está incompleto en alguna celda, el gerente tiene que leerlo.

## 10. Dependencias

**Ninguna dependencia nueva.** Los tres motores corren con deps **base** (pandas/numpy); `survival` con `discrete_hazard` usa **statsmodels**, que ya viene en el extra `scoring` (el mismo que la demo ya exige). El extra `ui` ya arrastra `excel` y `docx`.

Esto es un punto fuerte del diseño y hay que decirlo en la doc pública: **calcular provisiones CMF + IFRS 9 no añade una sola dependencia** sobre lo que ya se instala para un scorecard.

## 11. Estrategia de tests — los gates que recorren la ruta HASTA EL GERENTE

La regla del proyecto: *una feature sin preset, sin pantalla y sin capítulo no existe*. Estos gates existen para que "listo" signifique **listo para el usuario**, no "el `run()` no tiró excepción". **Ninguno es opcional.**

| Gate | Qué verifica | Cómo |
|---|---|---|
| **G1** | El dataset alimenta los motores **reales** | Smoke en Python: `materialize()` → `CmfProvisioningEngine.calculate()` e `IfrsProvisioningEngine.calculate()`. **Este gate corrige la lista de columnas de §6.1**, que hoy es una hipótesis. |
| **G2** | La cadena completa corre | `nikodym.run(provisioning_preset())` → `status == "done"` **y** `provisioning.card.total_reported_provision > 0`. **Es el primer test del repo que ejecuta `SurvivalStep` antes de IFRS 9** (hoy ese puente no está ejercitado en ningún lado). |
| **G3** | La UI puede lanzarla | `POST /api/run` con el preset nuevo → 200, `done`, y `GET /api/results/{id}` trae las tres secciones de provisiones no-nulas. |
| **G4** | El gerente lo VE | La demo (`web/`) renderiza la sección de provisiones con el piso y el `floor_bite_ratio`. Verificación **en el navegador**, no por typecheck. |
| **G5** | El informe lo DICE | El HTML/PDF trae el capítulo "Provisiones" con la cifra, **y ya no contiene la frase "corresponde a fases posteriores"** (test que busca ese literal y falla si aparece). |
| **G6** | La demo estática funciona sin backend | Fixtures regenerados desde una **corrida real** (nunca inventados) + `VITE_DEMO_MODE=true npm run build`. |
| **G7** | El fixture del schema no está stale | Test que compara `web/src/fixtures/schema.json` contra `build_full_json_schema()` y falla si difieren. |

**Goldens que se romperán y hay que regenerar a conciencia** (no a ciegas): 2 SHA-256 del HTML del informe (`test_report_renderer.py:48`, `test_report_step.py:74`), la tupla `_CANONICAL_IDS` de 16 ids (`test_report_renderer.py:877`), la numeración de capítulos (`test_report_builder.py:100-104` — `limitations == "6"` se moverá) y el dict del manifest (`test_report_builder.py:130`).

**Regla:** cada test nuevo debe **fallar con el código viejo**. Un test que pasa antes y después no está probando lo que crees.

## 12. Decisiones abiertas y riesgos

### D6 — La CLI: FUERA de este SDD (decidido, no abierto)
Hoy **no existe CLI** (`pyproject.toml` sin `[project.scripts]`; cero `argparse`/`typer`/`click`) y la doc pública lo confiesa (`docs_site/index.md:14`). El HANDOFF preguntaba si nace aquí. **No.**
- **El gerente no usa una terminal.** La superficie que Eduardo muestra es la demo web. Una CLI no mueve una sola reunión.
- Es un track **independiente**: toca packaging y crea un **entry-point público** (superficie de compatibilidad que luego no se puede quitar).
- El terreno ya está preparado: existe `load_config`/`dump_config` con round-trip y migración (`core/config/loader.py`), y SDD-23 ya reserva `nikodym-ui` como primer script (B23.6). La CLI es barata **cuando toque**.
→ **SDD-29 `cli`**, después de este. El extra `sweep` (hydra/omegaconf) está declarado en el `pyproject` **sin una sola línea de código que lo importe**: o se implementa en el SDD-29, o se borra del `pyproject` (hoy es una promesa incumplida en un archivo público).

### Riesgos

**R1 — El dataset sintético es la pieza que puede hundir la credibilidad.** Un dataset donde el piso CMF nunca muerde, o donde todos caen en Stage 1, o donde `is_default=1` convive con `days_past_due=0`, es peor que no tener demo: un gerente de riesgo detecta un dato inverosímil **en segundos**, y ahí se acabó la reunión. **Mitigación:** los invariantes de coherencia de §6.1 son parte del gate G1, y el dataset debe revisarlo alguien con criterio de riesgo (Cami/Eduardo) antes de publicarlo. *Es el mayor riesgo de este SDD y no es técnico.*

**R2 — Tiempo de corrida.** `POST /api/run` es **síncrono y sin reporte de progreso** (no hay websocket ni polling: el `status` llega una sola vez, al cerrar el request). La cadena F1 + survival + 3 motores de provisiones sobre 6.000 filas será **notablemente más lenta** que el scorecard solo. Si supera el timeout del navegador o del proxy de Vercel, la demo muere en vivo. **Mitigación:** medir en G2; si pasa de ~30 s, reducir el `n_rows` del dataset **antes** que rediseñar el backend a asíncrono (eso es otro SDD).

**R3 — El bundle de la demo.** Ya pesa ~1,5 MB con el `schema.json` de 259 KB en la primera pantalla. Este SDD **añade** secciones al schema y componentes de resultados. **Mitigación:** el `import()` dinámico del schema (deuda ya identificada en el HANDOFF) deja de ser opcional y entra en el alcance.

**R4 — Alcance del front.** Los pasos 1-3 del checklist (backend) son mecánicos; los pasos 4-6 (componentes de resultados, charts, fixtures) son **trabajo manual real**. Es la mitad del esfuerzo de este SDD y la más fácil de subestimar.

### Lo que este SDD deja explícitamente para después
- Markov como fuente de term-structure (exige resolver estado→operación).
- `forward` (escenarios macro) y con él el PIT real y el `stress`.
- Provisiones por **operación** en la UI (hoy solo agregados; el detalle va al informe).
- CLI (SDD-29).
