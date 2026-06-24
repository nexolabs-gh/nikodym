# SDD-27 — `eda` (análisis exploratorio de riesgo: tasa de default por período, estabilidad temporal, perfiles univariados)

| Campo | Valor |
|---|---|
| **SDD** | 27 |
| **Módulo** | `nikodym.eda` |
| **Fase** | F1 |
| **Tanda de producción** | T2 (Scoring) |
| **Estado** | 🟡 Borrador |
| **Depende de** | SDD-01 (`core`), SDD-02 (`data`), SDD-05 (convenciones + config) |
| **Lo consumen** | SDD-06 (`binning`), SDD-11 (`performance` + `stability`, deslindado), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (creado en **Tanda 1 Rev**, decisión D1; redacción para T2) / 2026-06-24 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `eda` es el **paso 1 del pipeline de scorecard** (ESPECIFICACIONES §5.2): sobre el frame ya cargado, validado y particionado por `data` (SDD-02), produce el **análisis exploratorio orientado a riesgo** —**tasa de incumplimiento (default rate) por período/cohorte**, **estabilidad temporal de esa tasa** (señal temprana de necesidad de redesarrollo), **perfiles univariados de features frente al target** y diagnóstico de **missing/cardinalidad**— y emite tablas y gráficos auditables que `report` (SDD-26) consumirá, **sin transformar el dato para el modelo**.

**Responsabilidad única (qué SÍ hace).**
- Calcula la **tasa de default por período/cohorte** (`default_rate` por bucket temporal) sobre la población elegible (good/bad; ignora `<NA>` de indeterminados/excluidos).
- Diagnostica la **estabilidad temporal** de esa tasa (tendencia, dispersión, drift relativo) y **emite una decisión auditable** (`log_decision`) cuando supera un umbral (señal de redesarrollo), sin abortar el pipeline.
- Calcula **perfiles univariados** de cada feature candidata frente al target: tasa de default por tramo (numéricas binned por cuantiles **solo para describir**, categóricas por nivel), conteos y cobertura.
- Diagnostica **calidad de datos descriptiva**: tasa de missing por columna, cardinalidad de categóricas, columnas casi-constantes o casi-únicas (solo **reporta**, no elimina).
- Emite los **artefactos** (tablas `pandas.DataFrame` + especificaciones de figura) que `report` (SDD-26) renderiza y que `binning`/`stability` pueden leer como insumo descriptivo.
- Aporta el sub-config **`EdaConfig`** (la sección `eda` de `NikodymConfig`, ya reservada en SDD-05 §5.1).

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No hace binning ni WoE/IV**: el binning supervisado óptimo (OptBinning) y los WoE/IV son **SDD-06 (`binning`)**. El troceo de `eda` es **descriptivo** (cuantiles fijos), nunca alimenta el modelo. `eda` puede *reportar* un IV univariado **rápido/descriptivo** como diagnóstico, claramente etiquetado «pre-binning, no es el IV final» (ver §12, decisión abierta D-EDA-3).
- **No gobierna el dato**: cargar, validar esquema, definir target, particionar, normalizar special values y calcular `data_hash` es **SDD-02**. `eda` **consume** el `frame`/`PartitionResult` que SDD-02 publicó; no los recalcula ni los muta.
- **No calcula métricas de discriminación ni PSI del modelo**: KS/AUC/Gini, PSI de score y estabilidad del **scorecard ya entrenado** son **SDD-11 (`performance`+`stability`)**. `eda` mira la **tasa de default cruda pre-modelo**; SDD-11 mira el **score post-modelo** (frontera explícita, §2 y §12 D-EDA-1).
- **No selecciona variables**: descartar features por IV/correlación/missing es **SDD-07 (`selection`)**. `eda` reporta diagnósticos; **qué columnas son features lo decide SDD-06/07**, no `eda`.
- **No ajusta nada ni produce estimadores**: es un **componente no-estimador** (SDD-05 §4.2), sin `fit/predict`.
- **No orquesta ni persiste el audit-trail**: es un `Step` que `core` invoca (SDD-01 §7); emite `AuditEvent`/`log_decision` vía `core`; los persiste **SDD-03**. No renderiza el reporte: emite especificaciones de figura/tabla que **SDD-26** renderiza.

---

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Scoring (F1/T2). Primer módulo del pipeline de scorecard que corre **después** de `data` (SDD-02) y **antes** de `binning` (SDD-06). Vive en `src/nikodym/eda/` (ESPECIFICACIONES §6.3: `eda/` = "tasa de default por período, estabilidad temporal").
- **Quién lo invoca:** el orquestador de `core` (es la sección `eda`, segunda en el orden canónico de `NikodymConfig` tras `data`; SDD-05 §5.1). También se usa *standalone* desde la API programática y desde la UI (editor del `EdaConfig`).
- **A quién invoca:** a `core` (clases base no-estimador, excepciones, `SeedManager`, `AuditSink`, `ArtifactStore`, `LineageBundle`); a `pandas` para el cálculo; a `matplotlib`/`plotly` **solo para construir especificaciones de figura** (ver §10 y D-EDA-4). Lee del `ArtifactStore` el dominio `"data"` (artefactos `"frame"`, `"splits"`, `"labels"`). **No** importa ningún módulo de dominio aguas abajo (binning/model).

```
        config.data ─► data (SDD-02) ─► artifacts["data"]: frame, splits, labels
                                                   │
                            study.artifacts.get("data", ...)
                                                   ▼
        config.eda (EdaConfig) ──► Study.run() ──► ┌──── eda (SDD-27) ─────────────────┐
                                                   │  default_rate por período/cohorte  │
                                                   │  estabilidad temporal (+decisión)   │
                                                   │  perfiles univariados vs target     │
                                                   │  missing/cardinalidad descriptivos  │
                                                   └───────┬───────────────────┬─────────┘
                                       escribe artifacts["eda"]                 │ emite log_decision
                                       (tablas + figure specs)                  ▼ (estabilidad) → SDD-03
                              binning (SDD-06) · stability (SDD-11) · report (SDD-26)
```

**Interacción con el `Study` y el config declarativo.** `eda` es un componente **no-estimador** (SDD-05 §4.2: análisis exploratorio → no hereda base de estimador; contrato funcional propio). Se registra con `@register("standard", domain="eda")` (D-CONV-2: `type` == key del Registry == nombre de sección). Su `execute(study, rng)` (contrato `Step`, SDD-01 §4) lee `study.config.eda` y los artefactos del dominio `"data"`, produce los resultados y los escribe **namespaced** bajo el dominio `"eda"`. Usa el `rng` que `core` inyecta **solo** si hay muestreo activado (datasets grandes); por defecto el cálculo es exhaustivo y determinista sin azar (§9). La UI (SDD-23) edita `EdaConfig` y previsualiza tablas/figuras.

---

## 3. Conceptos y fundamentos

> `eda` es **descriptivo**: no contiene fórmulas de scoring (WoE/score/calibración). Define los conceptos de exploración orientada a riesgo que el resto del pipeline usa como diagnóstico de entrada.

- **Tasa de default / tasa de incumplimiento (`default_rate`).** Proporción de "malos" sobre la población elegible (good + bad) en un grupo. Sobre el frame de SDD-02, con `target ∈ {0,1}` y `<NA>` para indeterminado/excluido (SDD-02 §6):

  $$\text{default\_rate}(g) = \frac{\#\{i \in g : \text{target}_i = 1\}}{\#\{i \in g : \text{target}_i \in \{0,1\}\}}$$

  El denominador **excluye los `<NA>`** (indeterminados/excluidos no son ni bueno ni malo limpio). Es el "paso 1" de ESPECIFICACIONES §5.2 ("tasa de incumplimiento por período").

- **Período / cohorte.** Bucket temporal sobre el que se agrega la tasa. `eda` soporta dos ejes (config-driven):
  - **Por fecha de observación** (`period`): se discretiza una columna fecha en buckets mensuales/trimestrales/anuales (`observation_date_col`, que SDD-02 ya validó como datetime cuando hay `window`).
  - **Por cohorte / vintage** (`cohort`): una columna categórica de añada (la misma noción que `CohortSplitConfig.cohort_col` de SDD-02).
  La tasa por período es la **base de la estabilidad temporal**: una tendencia creciente/quebrada de la tasa de default es la **señal temprana clásica de que el scorecard necesita redesarrollo** (ESPECIFICACIONES §5.2; AGENTS «estabilidad temporal de la tasa de default»).

- **Estabilidad temporal de la tasa de default.** Diagnóstico de cuánto se mueve `default_rate` entre períodos. `eda` reporta indicadores **descriptivos, sin supuestos distribucionales fuertes** (esto es exploración, no validación formal):
  - **Coeficiente de variación temporal**: $\text{CV} = \sigma(\text{rates}) / \bar{\text{rate}}$ sobre las tasas por período.
  - **Drift relativo extremo**: $\max_t |\text{rate}_t - \bar{\text{rate}}| / \bar{\text{rate}}$ (peor desviación relativa respecto a la media).
  - **Tendencia**: signo y magnitud de la pendiente de una regresión lineal simple `rate ~ índice_de_período` (solo descriptiva; orientación, no test de hipótesis).
  Si el indicador configurado supera su umbral, `eda` **emite una decisión auditable** `log_decision(regla="estabilidad_temporal", umbral=…, valor=…, accion="senalar_redesarrollo")` — **señala**, no aborta (es un diagnóstico que el analista interpreta). Nota de frontera: el **PSI** (Population Stability Index) sobre el **score del modelo** es de SDD-11; `eda` se queda en la **tasa de default cruda** (D-EDA-1).

- **Perfil univariado feature↔target.** Para cada columna candidata, tabla de `default_rate`, conteo y cobertura por tramo:
  - **Numéricas**: troceo en **cuantiles fijos** (p.ej. deciles) — **descriptivo**, para ver la forma de la relación; **no** es el binning supervisado de SDD-06.
  - **Categóricas**: un tramo por nivel (colapsando niveles raros bajo un umbral de frecuencia en un grupo `"_otros_"` solo para la tabla descriptiva).
  Permite leer monotonía aparente, niveles de alto riesgo y muestras vacías antes de binning.

- **Diagnóstico de calidad descriptivo.** Por columna: tasa de missing (tras la normalización de special→NaN que ya hizo SDD-02), cardinalidad (nº de niveles distintos), y flags de columna **casi-constante** (un valor domina > umbral) o **casi-única** (cardinalidad ≈ nº de filas, típico de identificadores). Solo **reporta**; eliminar es de `selection` (SDD-07).

- **Población de análisis.** Por defecto `eda` describe sobre la **partición de Desarrollo** (Dev), que es donde se ajustará el modelo (SDD-02 §3), y compara Dev vs Holdout/OOT cuando procede (estabilidad). Configurable (`analysis_partition`). Los `fuera_de_modelo` (indeterminados/excluidos) se reportan en conteos pero **no** entran al denominador de `default_rate` (no tienen target válido).

> **Fórmulas / parámetros normativos:** `eda` no contiene ninguno regulatorio. La única fórmula es la tasa de default (cociente de conteos) y estadísticos descriptivos estándar (media, desviación, CV, pendiente OLS). Las fórmulas cuantitativas de riesgo (WoE/IV/PSI/score) viven en sus dominios (SDD-06/09/11) y se citan, no se reescriben (00-INDICE §Convenciones).

---

## 4. API pública (contrato)

> Firmas **ilustrativas** (contratos, no código final). Identificadores en inglés técnico (SDD-05 D-CONV-1: dominio de datos/stats → inglés, p.ej. `default_rate`, `compute`); docstrings y mensajes en **español**. Los componentes son **no-estimador** (SDD-05 §4.2): no heredan `BaseNikodymEstimator`, no tienen `fit/predict`; usan `AuditableMixin` de `core` para `log_decision` y se construyen con `from_config` (helper propio espejo del de estimadores, mismo patrón que SDD-02 §4).

```python
# nikodym/eda/default_rate.py
class DefaultRateAnalyzer:
    """Tasa de default por período/cohorte sobre la población elegible (target en {0,1})."""
    def __init__(self, config: "DefaultRateConfig") -> None: ...
    @classmethod
    def from_config(cls, cfg: "DefaultRateConfig") -> "DefaultRateAnalyzer": ...
    def compute(self, frame: "pandas.DataFrame", *, target_col: str,
                audit: "AuditSink | None" = None) -> "DefaultRateResult": ...

class DefaultRateResult(BaseModel):
    by_period: "pandas.DataFrame"   # cols: period | n_total | n_eligible | n_bad | default_rate
    axis: str                       # "period" | "cohort" (eje usado)
    overall_rate: float             # tasa global sobre la población elegible
    model_config = ConfigDict(arbitrary_types_allowed=True)

# nikodym/eda/stability.py
class TemporalStabilityAnalyzer:
    """Estabilidad temporal de la tasa de default (CV, drift, tendencia) + decisión auditable."""
    def __init__(self, config: "TemporalStabilityConfig") -> None: ...
    @classmethod
    def from_config(cls, cfg: "TemporalStabilityConfig") -> "TemporalStabilityAnalyzer": ...
    def assess(self, default_rate: "DefaultRateResult", *,
               audit: "AuditSink | None" = None) -> "StabilityResult": ...

class StabilityResult(BaseModel):
    cv: float                       # coeficiente de variación temporal
    max_relative_drift: float       # peor desviación relativa vs media
    trend_slope: float              # pendiente OLS rate ~ índice de período (descriptiva)
    flagged: bool                   # True si superó el umbral configurado (señal de redesarrollo)
    metric_used: str                # indicador que gatilló ("cv" | "max_relative_drift" | "trend_slope")
    threshold: float                # umbral configurado contra el que se comparó

# nikodym/eda/univariate.py
class UnivariateProfiler:
    """Perfil descriptivo de cada feature candidata frente al target (default_rate por tramo)."""
    def __init__(self, config: "UnivariateConfig") -> None: ...
    @classmethod
    def from_config(cls, cfg: "UnivariateConfig") -> "UnivariateProfiler": ...
    def profile(self, frame: "pandas.DataFrame", *, target_col: str, columns: "tuple[str, ...]",
                audit: "AuditSink | None" = None) -> "UnivariateResult": ...

class UnivariateResult(BaseModel):
    profiles: dict[str, "pandas.DataFrame"]   # columna -> tabla (tramo | n | coverage | default_rate)
    descriptive_iv: dict[str, float]          # IV univariado PRE-binning, descriptivo (D-EDA-3); puede ir vacío
    model_config = ConfigDict(arbitrary_types_allowed=True)

# nikodym/eda/quality.py
class DataQualityProfiler:
    """Diagnóstico descriptivo: missing, cardinalidad, casi-constante/casi-única. Solo reporta."""
    def __init__(self, config: "QualityConfig") -> None: ...
    @classmethod
    def from_config(cls, cfg: "QualityConfig") -> "DataQualityProfiler": ...
    def profile(self, frame: "pandas.DataFrame", *,
                audit: "AuditSink | None" = None) -> "QualityResult": ...

class QualityResult(BaseModel):
    by_column: "pandas.DataFrame"   # col | dtype | missing_rate | cardinality | near_constant | near_unique
    model_config = ConfigDict(arbitrary_types_allowed=True)

# nikodym/eda/figures.py
class FigureSpec(BaseModel):
    """Especificación declarativa de una figura para que SDD-26 (report) la renderice.
    eda NO renderiza ni guarda imágenes en el pipeline; produce la receta (datos + tipo + ejes)."""
    kind: Literal["line", "bar", "heatmap"]   # default_rate trend=line; univariate=bar; etc.
    title: str                                 # en español
    data: "pandas.DataFrame"                    # los datos a graficar (tabla ya agregada)
    x: str; y: str
    series: str | None = None                   # agrupación opcional (p.ej. partición)
    model_config = ConfigDict(arbitrary_types_allowed=True)

# nikodym/eda/step.py
@register("standard", domain="eda")     # type == key Registry == sección de config (D-CONV-2)
class EdaStep:                          # NO-estimador; implementa el Protocol Step de core (SDD-01 §4)
    name: str = "eda"
    @classmethod
    def from_config(cls, cfg: "EdaConfig") -> "EdaStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "EdaResult":
        ...  # lee artifacts["data"], orquesta default_rate -> stability -> univariate -> quality -> figuras

class EdaResult(BaseModel):
    default_rate: "DefaultRateResult"
    stability: "StabilityResult"
    univariate: "UnivariateResult"
    quality: "QualityResult"
    figures: tuple["FigureSpec", ...]
    model_config = ConfigDict(arbitrary_types_allowed=True)
```

**Artefactos que `EdaStep.execute` escribe en `study.artifacts`** (dominio `"eda"`, claves estables — consumidas por SDD-06/11/26):

| clave | tipo | contenido |
|---|---|---|
| `"default_rate"` | `DefaultRateResult` | tasa de default por período/cohorte + tasa global |
| `"stability"` | `StabilityResult` | indicadores de estabilidad temporal + flag de redesarrollo |
| `"univariate"` | `UnivariateResult` | perfiles univariados feature↔target + IV descriptivo |
| `"quality"` | `QualityResult` | missing/cardinalidad/flags por columna |
| `"figures"` | `tuple[FigureSpec, ...]` | recetas de figura para SDD-26 (no imágenes) |

**Ejemplo de uso (extremo a extremo, pseudocódigo):**

```python
from nikodym.core import Study
from nikodym.core.config import load_config

config = load_config("experimento.yaml")          # incluye secciones data: {...} y eda: {...}
study  = Study(config, name="scorecard-comportamiento")
study.run(steps=["data", "eda"])                   # data primero (eda consume sus artefactos)

eda = study.artifacts.get("eda", "default_rate")   # DefaultRateResult
print(eda.by_period)                               # tabla: period | n_eligible | n_bad | default_rate
stab = study.artifacts.get("eda", "stability")     # StabilityResult
if stab.flagged:
    print(f"Estabilidad: posible redesarrollo (CV={stab.cv:.3f} > {stab.threshold}).")

# Uso standalone (sin Study), p.ej. en notebook/UI:
from nikodym.eda import DefaultRateAnalyzer
res = DefaultRateAnalyzer.from_config(cfg.eda.default_rate).compute(df, target_col="target")
```

---

## 5. Configuración (schema Pydantic)

`EdaConfig` es el sub-config de la sección `eda` de `NikodymConfig` (SDD-05 §5.1). Sigue las convenciones D-CONV: `NikodymBaseConfig` (→ `ConfigDict(extra="forbid", frozen=True)`), todo campo con `title`+`description`, `ge/le` en numéricos, `Literal`/`Enum` en categóricos, y **metadatos `ui_*`** (`json_schema_extra`) para que la UI (SDD-23) sea editor del mismo config (SDD-05 §5.5). No hay uniones discriminadas anidadas (los analizadores son fijos, no polimórficos); `type` discriminador a **nivel sección** (D-CONV-2).

```python
# nikodym/eda/config.py
from typing import Literal
from pydantic import Field
from nikodym.core.config import NikodymBaseConfig

# ── tasa de default por período/cohorte ───────────────────────────────────────
class DefaultRateConfig(NikodymBaseConfig):
    axis: Literal["period", "cohort"] = Field("period", title="Eje de agregación",
        description="'period' discretiza una fecha; 'cohort' usa una columna de añada/vintage.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Tasa de default", "ui_order": 1})
    date_col: str | None = Field(None, title="Columna de fecha (eje period)",
        description="Fecha de observación a discretizar. Debe ser dtype datetime (validado por data).",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Tasa de default", "ui_order": 2})
    period_freq: Literal["M", "Q", "Y"] = Field("M", title="Frecuencia del período",
        description="Mensual/Trimestral/Anual para discretizar date_col.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Tasa de default", "ui_order": 3})
    cohort_col: str | None = Field(None, title="Columna de cohorte (eje cohort)",
        description="Categórica de añada/vintage; misma noción que data.partition.cohort_col.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Tasa de default", "ui_order": 4})
    min_obs_per_period: int = Field(50, ge=1, title="Mínimo de observaciones por período",
        description="Períodos con menos elegibles se marcan como poco fiables en la tabla (no se eliminan).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Tasa de default", "ui_order": 5})

# ── estabilidad temporal ──────────────────────────────────────────────────────
class TemporalStabilityConfig(NikodymBaseConfig):
    metric: Literal["cv", "max_relative_drift", "trend_slope"] = Field("cv", title="Indicador de estabilidad",
        description="Indicador comparado contra el umbral para señalar redesarrollo.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Estabilidad temporal", "ui_order": 1})
    threshold: float = Field(0.25, ge=0.0, title="Umbral del indicador",
        description="Por encima, se emite log_decision señalando posible redesarrollo (no aborta).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Estabilidad temporal", "ui_order": 2})

# ── perfiles univariados ──────────────────────────────────────────────────────
class UnivariateConfig(NikodymBaseConfig):
    n_quantile_bins: int = Field(10, ge=2, le=50, title="Tramos por cuantiles (numéricas, descriptivo)",
        description="Troceo DESCRIPTIVO para el perfil; NO es el binning de SDD-06.",
        json_schema_extra={"ui_widget": "slider", "ui_group": "Perfiles univariados", "ui_order": 1})
    rare_level_threshold: float = Field(0.01, ge=0.0, le=0.5, title="Umbral de nivel raro (categóricas)",
        description="Niveles con frecuencia menor se agrupan en '_otros_' solo para la tabla descriptiva.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Perfiles univariados", "ui_order": 2})
    compute_descriptive_iv: bool = Field(False, title="Calcular IV univariado descriptivo (pre-binning)",
        description="Diagnóstico rápido; NO es el IV final de SDD-06. Etiquetado 'pre-binning'.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Perfiles univariados", "ui_order": 3})
    columns: tuple[str, ...] | None = Field(None, title="Columnas a perfilar",
        description="None = todas las no-estructurales (excluye target/status/partition/fecha/cohorte). "
                    "Qué columnas son features lo decide SDD-06/07; aquí es solo el alcance del perfil.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Perfiles univariados", "ui_order": 4})

# ── calidad descriptiva ───────────────────────────────────────────────────────
class QualityConfig(NikodymBaseConfig):
    near_constant_threshold: float = Field(0.99, ge=0.5, le=1.0, title="Umbral casi-constante",
        description="Si un valor concentra >= este % de filas no nulas, se marca near_constant (solo reporte).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Calidad de datos", "ui_order": 1})
    high_cardinality_threshold: int = Field(50, ge=2, title="Umbral de alta cardinalidad (categóricas)",
        description="Categóricas con más niveles se marcan high_cardinality (solo reporte).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Calidad de datos", "ui_order": 2})

# ── muestreo (datasets grandes) ───────────────────────────────────────────────
class SamplingConfig(NikodymBaseConfig):
    enabled: bool = Field(False, title="Muestrear para los perfiles univariados",
        description="Si True, los perfiles/figuras se calculan sobre una muestra (usa el rng de core). "
                    "La tasa de default por período se calcula SIEMPRE sobre el total (no se muestrea).",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Muestreo", "ui_order": 1})
    max_rows: int = Field(500_000, ge=1000, title="Máximo de filas en la muestra",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Muestreo", "ui_order": 2})

# ── raíz del sub-config ────────────────────────────────────────────────────────
class EdaConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"        # == @register("standard", domain="eda") (D-CONV-2)
    analysis_partition: Literal["desarrollo", "holdout", "oot", "todas"] = Field(
        "desarrollo", title="Partición a describir",
        description="Población base del análisis (default: Desarrollo, donde se ajusta el modelo). "
                    "Los 'fuera_de_modelo' nunca entran al denominador de default_rate.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "General", "ui_order": 1})
    default_rate: DefaultRateConfig = Field(default_factory=DefaultRateConfig, title="Tasa de default")
    stability: TemporalStabilityConfig = Field(default_factory=TemporalStabilityConfig, title="Estabilidad temporal")
    univariate: UnivariateConfig = Field(default_factory=UnivariateConfig, title="Perfiles univariados")
    quality: QualityConfig = Field(default_factory=QualityConfig, title="Calidad de datos")
    sampling: SamplingConfig = Field(default_factory=SamplingConfig, title="Muestreo")
```

**Defaults defendibles.** `analysis_partition="desarrollo"` (se describe donde se ajustará el modelo; SDD-02 §3). `axis="period"` + `period_freq="M"` (la tasa mensual es la vista estándar de la señal temporal). `stability.metric="cv"`, `threshold=0.25` (un CV de la tasa de default > 25% es un disparador conservador de "mírate la estabilidad"; **editable** — es un umbral de exploración, no regulatorio). `n_quantile_bins=10` (deciles, lectura cómoda de la forma). `compute_descriptive_iv=False` (el IV "de verdad" es de SDD-06; el descriptivo es opt-in para no confundir). `sampling.enabled=False` (cálculo exhaustivo y determinista por defecto; el muestreo es optimización opt-in para datasets grandes). Ningún campo es obligatorio (`...`): `EdaConfig()` es construible con defaults razonables; `date_col`/`cohort_col` se resuelven por inferencia si son `None` (ver §7/§8).

**Serialización YAML y UI.** Round-trip estándar de SDD-05 §5.5: `yaml.safe_dump(cfg.model_dump(mode="json", by_alias=True), sort_keys=False)`. No hay alias (ningún nombre colisiona con métodos de Pydantic). La UI (SDD-23) renderiza `EdaConfig` desde `model_json_schema()`; los `ui_group` agrupan los controles por panel (Tasa de default / Estabilidad / Perfiles / Calidad / Muestreo).

---

## 6. Contratos de datos (I/O)

**Input.**
- Vía `Study`: `eda` lee del `ArtifactStore` los artefactos del dominio `"data"` (SDD-02 §4): **`"frame"`** (`pandas.DataFrame` validado, etiquetado, particionado, con special→NaN), **`"splits"`** (`PartitionResult`) y **`"labels"`** (`LabeledFrame`, para `target_col`/`status_col`). **Pre-condición:** el paso `data` ya corrió (si los artefactos faltan → `ArtifactNotFoundError` de core; en orquestación normal el orden canónico lo garantiza, SDD-01 §7).
- Vía API standalone: cada analizador recibe directamente un `pandas.DataFrame` con la columna target y, según el eje, la columna fecha o cohorte.
- **Columnas que `eda` lee del frame** (todas producidas por SDD-02, no las crea `eda`): `target` (nombre configurable, Int8 0/1/`<NA>`), `label_status`, `partition`, `ttd`, más la columna fecha/cohorte y las features a perfilar.

**Output.** El `EdaResult` (y sus cinco artefactos namespaced bajo `"eda"`). Todas las tablas son `pandas.DataFrame` con **columnas nombradas** (SDD-05 §6: no ndarray pelado), serializables; las figuras son `FigureSpec` (datos + receta, no bytes de imagen). `eda` **no añade columnas al frame** ni lo muta: el frame que `binning` (SDD-06) consume es el de `data`, no uno transformado por `eda` (refuerza el límite "no transforma el dato para el modelo").

**Invariantes (pre/post) — verificables en tests (§11):**
- *No mutación del input:* el `frame` del dominio `"data"` es idéntico antes y después de `eda.execute` (igualdad estructural; `eda` opera sobre copias/agregaciones). `eda` nunca llama `artifacts.set("data", ...)`.
- *Denominador correcto:* en toda tabla de `default_rate`, `n_eligible ≤ n_total` y `0 ≤ n_bad ≤ n_eligible` (con `n_good := n_eligible − n_bad`, derivado — la tabla `by_period` expone `n_total`/`n_eligible`/`n_bad`, no una columna `n_good`); los `<NA>` (indeterminado/excluido) cuentan en `n_total` pero **no** en `n_eligible`. `default_rate == n_bad / n_eligible` (con `n_eligible > 0`).
- *Consistencia con el total:* la suma de `n_bad` por período == nº de malos de la partición analizada; `overall_rate` == `Σ n_bad / Σ n_eligible` (agregado de la tabla por período, ponderado por elegibles, no media simple de tasas).
- *Cobertura univariada:* en cada perfil, `Σ n` por tramo == nº de filas elegibles de la columna (incluido un tramo explícito de missing si la columna tiene NaN); `coverage` suma 1.0 (± tolerancia float).
- *Decisión de estabilidad trazada:* si `stability.flagged`, existe **exactamente un** `AuditEvent(kind="decision")` con `regla="estabilidad_temporal"`, el umbral y el valor observado (auditabilidad, SDD-01 §9).
- *Determinismo:* sin muestreo, `eda` es función pura del `frame` + `EdaConfig` (mismo input → mismo output bit a bit). Con muestreo, determinista dado el `rng` derivado por nombre (`generator_for("eda")`), independiente del orden de pasos (§9).
- *Solo lectura del dominio data:* `eda` escribe solo bajo el dominio `"eda"`; no toca `"data"` ni el `LineageBundle` (no completa `data_hash` — eso es de SDD-02).

---

## 7. Algoritmos y flujo

> Pseudocódigo de alto nivel. `eda` es no-estimador: agrega un DataFrame en tablas/figuras descriptivas; no ajusta parámetros.

**`EdaStep.execute(study, rng)` — secuencia canónica.**
1. **Leer insumos.** `frame = study.artifacts.get("data", "frame")`; `labels = study.artifacts.get("data", "labels")` → `target_col = labels.target_col`. Seleccionar la subpoblación según `cfg.analysis_partition` (filtrar por columna `partition`; `"todas"` = sin filtro). Los `fuera_de_modelo` quedan en `n_total` pero el cálculo de tasa los excluye por `target ∈ {0,1}`.
2. **Resolver el eje temporal.**
   - `axis="period"`: si `cfg.default_rate.date_col` es `None`, **inferir** una columna datetime plausible (la única datetime, o `window.observation_date_col` si SDD-02 la declaró); si no hay ninguna → `EdaError` (mensaje en español explicando que se requiere una fecha para la tasa por período). Discretizar con `pandas.Series.dt.to_period(freq)` → columna `period`.
   - `axis="cohort"`: usar `cfg.default_rate.cohort_col`; si `None` y no hay cohorte → `EdaError`.
3. **Tasa de default por período.** `DefaultRateAnalyzer.compute`: agrupar por `period`/`cohort`; por grupo `n_total`, `n_eligible = #(target∈{0,1})`, `n_bad = #(target==1)`, `default_rate = n_bad/n_eligible` (NaN si `n_eligible==0`, marcado). Marcar períodos con `n_eligible < min_obs_per_period` como `low_confidence=True` en la tabla (no se eliminan). Calcular `overall_rate` ponderado por elegibles.
4. **Estabilidad temporal.** `TemporalStabilityAnalyzer.assess`: sobre las tasas por período (ordenadas por tiempo, excluyendo `low_confidence` del cálculo del indicador), calcular `cv`, `max_relative_drift`, `trend_slope` (OLS simple `rate ~ índice`). `flagged = (indicador[cfg.metric] > cfg.threshold)`. Si `flagged`: `log_decision(regla="estabilidad_temporal", umbral=cfg.threshold, valor=indicador, accion="senalar_redesarrollo")`. **Nunca aborta** (es diagnóstico).
5. **Perfiles univariados.** `UnivariateProfiler.profile` sobre `cfg.univariate.columns` (o todas las no-estructurales si `None` — excluye `target`/`label_status`/`partition`/`ttd`/fecha/cohorte). Para cada columna:
   - numérica: `pandas.qcut(col, n_quantile_bins, duplicates="drop")` → tramos por cuantiles; tabla `tramo | n | coverage | default_rate`; tramo explícito para NaN.
   - categórica: un tramo por nivel; niveles con frecuencia < `rare_level_threshold` → `"_otros_"`.
   - si `compute_descriptive_iv`: IV univariado **descriptivo** sobre esos tramos (con suavizado de Laplace para celdas vacías), etiquetado `pre-binning` (D-EDA-3).
   - **Muestreo:** si `cfg.sampling.enabled` y `len(frame_part) > max_rows`, perfilar sobre `frame_part.sample(n=max_rows, random_state=rng)` (usa el `rng` inyectado; §9). La tasa por período (paso 3) **no** se muestrea.
6. **Calidad descriptiva.** `DataQualityProfiler.profile`: por columna `dtype`, `missing_rate` (NaN ya incluye special→NaN de SDD-02), `cardinality`; flags `near_constant` (un valor concentra ≥ `near_constant_threshold` de no-nulos) y `near_unique`/`high_cardinality`. Solo tabla; ninguna eliminación.
7. **Figuras.** Construir `FigureSpec` (datos + receta): línea de `default_rate` por período (señal temporal), barras de `default_rate` por tramo para las top-N columnas por IV descriptivo (o por orden de config), heatmap opcional cohorte×período de la tasa. **No** se renderiza imagen aquí: SDD-26 (report) las dibuja con matplotlib/plotly.
8. **Publicar artefactos** (`study.artifacts.set("eda", k, v)` para los cinco). Devolver `EdaResult`.

**`Partitioner`-independencia.** `eda` **no** re-particiona: lee la columna `partition` que SDD-02 ya fijó. Si SDD-02 expone en T2 los **accessors de particiones** que propone su §12 (`PartitionResult.subset(partition) -> DataFrame` / `mask(partition) -> Series[bool]`), `eda` usará `subset(...)` en lugar de filtrar la columna a mano (frontera a confirmar, §12 D-EDA-2).

**Decisiones algorítmicas y alternativas descartadas.**
- **Troceo por cuantiles fijos (no supervisado) para el perfil** — descriptivo y barato; el binning supervisado (OptBinning) es de SDD-06. *Alternativa descartada:* binnear aquí con el algoritmo final → duplicaría SDD-06 y borraría la frontera "eda no transforma para el modelo".
- **Indicadores de estabilidad descriptivos (CV/drift/tendencia), no test estadístico formal** — exploración rápida, sin supuestos; el PSI/tests formales del score son de SDD-11. *Alternativa descartada:* PSI de la tasa de default aquí → invade SDD-11 (D-EDA-1).
- **Tasa global ponderada por elegibles, no media simple de tasas por período** — evita que períodos con pocos datos sesguen el agregado.
- **`overall_rate` y denominador excluyen `<NA>`** — coherente con SDD-02 (indeterminado/excluido no son target válido).

**Complejidad / rendimiento.** Todo es agregación `groupby`/`qcut` en pandas: O(n·c) (n filas, c columnas perfiladas). Para datasets grandes, el muestreo (opt-in) acota el coste de los perfiles univariados/figuras; la tasa por período se mantiene exhaustiva (es barata: una agregación por la columna de período).

---

## 8. Casos borde y manejo de errores

- **Sin columna temporal/cohorte (eje `period`/`cohort`) y no inferible:** `EdaError` con mensaje en español ("la tasa de default por período requiere una columna de fecha; declárala en `eda.default_rate.date_col` o usa `axis='cohort'`"). No se inventa un eje.
- **Un solo período (o cero):** `default_rate` se calcula igual; la **estabilidad** no es evaluable con < 2 períodos → `StabilityResult` con `cv=NaN`, `flagged=False`, y un `log_decision(regla="estabilidad_temporal", accion="no_evaluable", valor="<2 períodos")` informativo (no error: es un diagnóstico que no aplica).
- **Período con `n_eligible == 0`** (todos `<NA>`): `default_rate = NaN`, marcado `low_confidence`; **no** divide por cero ni rompe; se excluye del cálculo del indicador de estabilidad.
- **Partición vacía** (p.ej. `analysis_partition` sin filas): `EdaError` ("la partición '<x>' no tiene filas elegibles para EDA"), porque no hay nada que describir.
- **Columna casi-única / identificador en el perfil univariado:** `qcut` con `duplicates="drop"` evita el fallo por bordes repetidos; si tras el drop queda 1 solo tramo, se reporta el perfil con un tramo y un flag (no error).
- **Columna 100% missing:** perfil con un único tramo "missing" (coverage 1.0, `default_rate` sobre 0 elegibles → NaN marcado); en calidad `missing_rate==1.0`. Reportado, no eliminado (eso es SDD-07).
- **`target_col` ausente del frame:** no debería ocurrir (SDD-02 lo crea), pero se valida: `EdaError` claro en vez de `KeyError` críptico.
- **Configuración inválida** (p.ej. `n_quantile_bins=1`): rechazada por Pydantic en el parse (`ge=2`) → `ConfigError` (SDD-05 §8), nunca en runtime.
- **Eje `period` sobre columna no-datetime:** `eda` asume que SDD-02 ya validó/coaccionó la fecha a datetime (SDD-02 §6); si llega no-datetime (uso standalone sin validar), `EdaError` ("la columna de período debe ser datetime; valídala con `data` antes de EDA").

**Excepciones propias** (en `nikodym/eda/exceptions.py`, descienden de `NikodymError`, regla única SDD-01 §4 / SDD-05 §4.3):

```python
from nikodym.core.exceptions import NikodymError
class EdaError(NikodymError): ...            # raíz del módulo eda
```

Mensajes en **español**, incluyendo la regla/columna/valor observado cuando aplica (SDD-05 §4.3). `eda` reutiliza `ArtifactNotFoundError` de core cuando faltan los artefactos de `data`.

---

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Solo el **muestreo opcional** (`sampling.enabled`). Usa el `rng` que `core` inyecta en `execute` (`seed_manager.generator_for("eda")`, derivado por nombre, independiente del orden de pasos — SDD-01 §7/§9). `frame.sample(random_state=rng)` con ese `Generator` es determinista: mismo `root_seed` → misma muestra. **Sin muestreo, `eda` no consume azar** (es función pura del frame + config).
- **Qué registra en el audit-trail (vía `log_decision` → `AuditEvent(kind="decision")`, persistido por SDD-03).**
  - **Estabilidad temporal**: la decisión central de `eda` — `regla="estabilidad_temporal"`, `umbral`, `valor` (indicador observado), `accion ∈ {"senalar_redesarrollo", "no_evaluable"}`. Es la "señal temprana de redesarrollo" que AGENTS/ESPEC piden como salida auditable de `eda`.
  - **Muestreo aplicado** (si se activó): `log_decision(regla="muestreo_eda", umbral=max_rows, valor=n_filas_original, accion="muestrear")` — para que el reporte deje constancia de que los perfiles se calcularon sobre una muestra.
  - `eda` **no** marca decisiones de eliminación de columnas (eso es SDD-07); reporta diagnósticos, no actúa sobre el dato.
- **Contribución al `LineageBundle`.** Ninguna: `eda` no completa `data_hash` (es de SDD-02) ni `config_hash` (es de core). Su `EdaConfig` ya entra al `config_hash` global como sección computacional (no infraestructura: `eda ∉ INFRA_SECTIONS`, SDD-05 §5.5), de modo que cambiar parámetros de `eda` cambia la identidad del experimento, como debe ser.
- **Garantía de determinismo y caveats.** Determinismo bit a bit sin muestreo; con muestreo, determinismo dado `root_seed` (la muestra se re-deriva, no se serializa — coherente con SDD-01 §6). No hay caveat tipo GBDT (no hay nada multihilo no determinista). Caveat menor: `pandas.qcut` puede colapsar tramos por bordes duplicados (`duplicates="drop"`) → el nº de tramos efectivos de una columna muy concentrada puede ser < `n_quantile_bins`; es determinista y se refleja en la tabla.

---

## 10. Dependencias

**Internas:** SDD-01 (`core`: `Study`/`ArtifactStore`, `AuditableMixin.log_decision`, `AuditSink`/`NullAuditSink`, `SeedManager`, `NikodymError`, `Step`), SDD-02 (`data`: consume `frame`/`splits`/`labels`, los contratos `PartitionResult`/`LabeledFrame`, columnas `target`/`label_status`/`partition`/`ttd`), SDD-05 (convenciones de config, `NikodymBaseConfig`, metadatos `ui_*`). **No** importa SDD-06+ (no depende de binning/model).

**Externas:**

| Librería | Versión mín. | Licencia | Uso en eda | Distribución |
|---|---|---|---|---|
| pandas | ≥ 2.0 | BSD-3 ✅ | `groupby`, `qcut`, `to_period`, agregaciones (contrato I/O universal, SDD-05 §6) | base (dep de la distribución) |
| numpy | ≥ 1.22 | BSD ✅ | estadísticos descriptivos (media/desv/CV), pendiente OLS, `Generator` del muestreo | base |
| matplotlib | ≥ 3.7 | PSF-based / BSD-compatible ✅ | construcción de `FigureSpec` de respaldo si SDD-26 las renderiza estáticas | **extra** (import perezoso) |
| plotly | ≥ 5.0 | MIT ✅ | figuras interactivas para el reporte HTML (SDD-26) | **extra** (import perezoso) |

> **Decisión (D-EDA-4): `eda` produce `FigureSpec` declarativas, no imágenes — matplotlib/plotly son `extra` con import perezoso.** El cálculo (tasas, perfiles, calidad) depende **solo** de pandas/numpy (deps base). Las librerías de gráficos se importan **perezosamente** dentro del paso de figuras (con `MissingDependencyError` claro si falta el extra, patrón SDD-01 §4/§8), y el **render real** lo hace SDD-26 (report). Así, correr `eda` para obtener las **tablas** (lo que `binning`/`stability` consumen) no exige el stack de gráficos. **Licencias verificadas (proyecto regulatorio, sin copyleft, D-LIC):** matplotlib usa licencia *PSF-based / BSD-compatible*; plotly es *MIT*; ninguna es GPL. *Frontera con SDD-26:* `eda` decide **qué** graficar (receta + datos); SDD-26 decide **cómo** (motor, tema, export HTML/PDF). El nombre/agrupación exacta del extra de gráficos (¿propio de `eda` o compartido con `report`?) se confirma con SDD-25/SDD-26 (§12 D-EDA-4).

`eda` **no** es copyleft ni arrastra dependencias pesadas en su núcleo de cálculo. No usa sklearn, OptBinning, statsmodels (esos llegan en SDD-06+).

---

## 11. Estrategia de tests

> Marco transversal en **SDD-24** (`eda` es no-estimador: usa las **utilidades genéricas** de `nikodym.testing` —fixtures de config, `assert_bitwise_reproducible`, `nikodym_config_strategy`—, **no** el harness de contrato sklearn ni la batería Nikodym, que son para estimadores/familias propias). Casos específicos de `eda`:

- **Canónicos numéricos (valores conocidos a mano).** Frame sintético con conteos exactos por período: p.ej. período `2024-01` con 100 elegibles y 10 malos → `default_rate == 0.10` exacto; `overall_rate` ponderado verificable a mano (`Σ n_bad / Σ n_eligible`). IV univariado descriptivo sobre una tabla 2×2 conocida (valor de oro). El test **asevera el resultado**, no reescribe fórmula (00-INDICE §Convenciones; SDD-24 §7.4).
- **Invariantes (verificables) — §6.** `0 ≤ n_bad ≤ n_eligible ≤ n_total` (con `n_good := n_eligible − n_bad`, derivado); `Σ n_bad por período == #malos de la partición`; `<NA>` cuentan en `n_total` y no en `n_eligible`; `coverage` univariada suma 1.0; el frame del dominio `"data"` no muta tras `eda.execute` (igualdad estructural antes/después).
- **Propiedades (Hypothesis).** Sobre frames sintéticos generados: `0 ≤ default_rate ≤ 1` siempre que `n_eligible > 0`; `overall_rate` está entre el min y el max de las tasas por período; reordenar las filas del frame **no** cambia ninguna tabla (determinismo independiente del orden). `EdaConfig` participa de `nikodym_config_strategy(sections=["eda"])` (round-trip y `config_hash`).
- **Estabilidad y auditoría.** Con una serie de tasas que dispara el umbral: `stability.flagged == True` y se emitió **exactamente un** `AuditEvent(kind="decision", regla="estabilidad_temporal")` (aseverado con `InMemoryAuditSink` de core, SDD-24 §9). Con < 2 períodos: `flagged == False` y decisión `no_evaluable`.
- **Reproducibilidad (`assert_bitwise_reproducible`, SDD-24 §4).** Sin muestreo: dos `execute` con mismo frame+config → tablas bit-idénticas. Con muestreo: dos corridas con `SeedManager(42).generator_for("eda")` → misma muestra y mismas tablas; muestra re-derivada (no serializada).
- **Casos borde (§8).** Período `n_eligible==0` → `default_rate` NaN marcado, sin `ZeroDivisionError`; columna 100% missing → perfil con tramo "missing"; partición vacía → `EdaError`; eje `period` sin fecha → `EdaError`; config inválida (`n_quantile_bins=1`) → `ConfigError` en parse.
- **Integración (`integration/`, SDD-24).** Pipeline `data → eda` end-to-end sobre `tests/data/synthetic_behavior.parquet`: `study.run(steps=["data","eda"])` puebla `artifacts["eda"]` con los cinco artefactos y un `StabilityResult` coherente; `eda` consume `artifacts["data"]` sin tocarlo.
- **Fixtures.** Frame sintético con eje temporal de varios meses y tasa de default conocida por período (determinista, seed fija, en `tests/data/`); `EdaConfig` mínimo y completo; `InMemoryAuditSink` para aseverar la decisión de estabilidad.

---

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas en este borrador (trazabilidad — sujetas a la revisión de integración de DanIA).**
- **D-EDA-1 — `eda` se queda en la tasa de default cruda pre-modelo; PSI/KS/AUC/Gini del score son de SDD-11.** Frontera: `eda` mira el **target por período** (pre-binning, pre-modelo); SDD-11 mira el **score post-modelo** y su PSI/estabilidad. *Porqué:* evita duplicar estabilidad en dos módulos; cada uno mira un objeto distinto (tasa de default vs distribución de score). **A confirmar con el autor de SDD-11** que la estabilidad de la *tasa de default* vive en `eda` y la del *score* en `stability`.
- **D-EDA-2 — `eda` lee la columna `partition` de SDD-02; no re-particiona.** Si SDD-02 expone en T2 los **accessors de particiones** que su §12 propone (`subset(partition)` / `mask(partition)`), `eda` usará `subset(...)`. *Frontera a confirmar:* la firma exacta del accessor (hoy SDD-02 §4 expone `PartitionResult` con columna `partition`, suficiente para filtrar; el accessor es azúcar aditiva).
- **D-EDA-3 — IV univariado de `eda` es DESCRIPTIVO (pre-binning), opt-in y etiquetado.** El IV "de verdad" (sobre el binning supervisado) es de SDD-06. *Riesgo:* que un usuario confunda ambos. *Mitigación:* `compute_descriptive_iv=False` por defecto + etiqueta explícita "pre-binning" en la tabla/figura. **A confirmar con SDD-06** que no haya solapamiento de nombres.
- **D-EDA-4 — `eda` emite `FigureSpec` declarativas; SDD-26 las renderiza; matplotlib/plotly son extra perezoso.** *Frontera a confirmar:* el contrato exacto de `FigureSpec` debe casar con lo que SDD-26 (report) espera consumir; el nombre/agrupación del extra de gráficos (propio vs compartido con report) lo fija SDD-25/SDD-26.

**Decisiones abiertas (delegadas a la revisión de Tanda 2).**
- **Qué columnas son "features" lo decide SDD-06/07, no `eda`.** `UnivariateConfig.columns=None` perfila todas las no-estructurales como **alcance del diagnóstico**, sin pronunciarse sobre cuáles entran al modelo. *Responsable:* DanIA (integración) + autores SDD-06/07.
- **Contrato exacto de `FigureSpec`** (campos, tipos de gráfico soportados) ↔ lo que SDD-26 consume. *Responsable:* DanIA + autor SDD-26 (T2).
- **Accessor de particiones de SDD-02** (firma exacta de `subset(partition)` / `mask(partition)`, propuestos en SDD-02 §12). *Responsable:* DanIA + autor SDD-02 al revisar T2.
- **Umbral por defecto de estabilidad** (`metric="cv"`, `threshold=0.25`): es un disparador de exploración, no regulatorio; conviene calibrarlo con un caso real antes de fijarlo. *Responsable:* DanIA.

**Riesgos.**
- **Solapamiento de responsabilidad con SDD-11** (estabilidad) → mitigado por D-EDA-1 (tasa de default vs score) y por la revisión de integración; si la frontera no convence, se mueve toda la estabilidad temporal a un solo módulo.
- **Confusión IV descriptivo vs IV de binning** → D-EDA-3 (opt-in + etiqueta).
- **Inferencia de la columna de fecha** (cuando `date_col=None`) puede elegir mal si hay varias datetime → mitigado fallando con `EdaError` claro si la inferencia es ambigua (no adivina en silencio).
- **Coste en datasets grandes** (perfiles univariados de muchas columnas) → mitigado con muestreo opt-in (la tasa por período se mantiene exhaustiva).

---

### Citas

- **ESPECIFICACIONES.md** §5.2 (paso 1 del pipeline de scorecard: "tasa de incumplimiento por período"; señal temporal de redesarrollo), §6.3 (árbol de paquetes: `eda/` = "tasa de default por período, estabilidad temporal"), §4 (principios 1 reproducibilidad, 2 auditabilidad por construcción, 9 núcleo liviano, 10 calidad ejemplar, 11 doble verificación de datos externos), §7 (stack/licencias, veto a copyleft).
- **00-INDICE.md** §Convenciones (fórmulas/parámetros se **citan**, no se reescriben); tabla de SDD (SDD-27 `eda`, F1/T2, depende de 02; lo consumen 06, 11, 26 — **ya registrado** en el índice y en la tanda T2 durante la integración de Tanda 1 Rev; total 27 SDD).
- **SDD-01 (`core`)** §4 (`Step` Protocol, `AuditableMixin.log_decision`, `AuditSink`/`NullAuditSink`, `ArtifactStore`, `NikodymError`, `from_config`), §6 (el azar no se serializa), §7 (orquestación; seeding por nombre independiente del orden; auto-registro), §9 (auditoría; determinismo).
- **SDD-02 (`data`)** §1/§4/§6 (consume `frame`/`splits`/`labels`, contratos `PartitionResult`/`LabeledFrame`, columnas `target`/`label_status`/`partition`/`ttd`; relación status↔partición; `<NA>` para indeterminado/excluido; "`data` NO calcula la tasa de incumplimiento por período ni la estabilidad temporal: eso es `eda`").
- **SDD-05 (convenciones+config)** §3 (uniones discriminadas de nivel sección, factory local para anidadas), §4.2 (qué base usar; no-estimador → contrato funcional propio), §4.3/§4.4 (excepciones descienden de `NikodymError`; naming inglés stats, español prosa), §5 (`NikodymBaseConfig` `extra="forbid"`/`frozen`; `title`+`description`; `ge/le`/`Literal`; metadatos `ui_*`), §5.1 (sección `eda` reservada en `NikodymConfig`), §5.5 (round-trip YAML; `config_hash` JSON canónico; `eda ∉ INFRA_SECTIONS`), §6 (output con columnas nombradas).
- **SDD-24 (testing)** §4 (`assert_bitwise_reproducible`, `nikodym_config_strategy`, `InMemoryAuditSink`), §7.4 (canónicos numéricos: aseverar valor, no reescribir fórmula), §7.5 (round-trip config, `config_hash`), §10 (utilidades genéricas para módulos no-estimador; el harness de contrato es solo para estimadores/familias propias).
- **Licencias verificadas (web, 2026-06-24):** matplotlib — licencia *PSF-based, solo código BSD-compatible* (matplotlib.org/stable/project/license.html); plotly.py — *MIT* (github.com/plotly/plotly.py/blob/main/LICENSE.txt). Ninguna copyleft (D-LIC).
