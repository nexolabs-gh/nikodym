# SDD-11 — `performance` + `stability` (desempeño y estabilidad post-modelo)

| Campo | Valor |
|---|---|
| **SDD** | 11 |
| **Módulos** | `nikodym.performance` + `nikodym.stability` |
| **Dominio** | Scoring |
| **Fase** | F1 |
| **Tanda de producción** | T2 (Scoring) |
| **Estado** | ✅ Implementado; pipeline F1 estable |
| **Depende de** | SDD-09 (`scorecard`), SDD-10 (`calibration`) |
| **Lo consumen** | SDD-22 (`validation`), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (redacción SDD-11 para T2) / 2026-06-28 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `performance` y `stability` miden, de forma determinista y auditable, la calidad de discriminación y la estabilidad del **score/PD post-modelo** de la scorecard de comportamiento: KS, AUC/ROC, Gini, tabla de deciles/gains, PSI del score, CSI por característica final y estabilidad temporal del score.

**Responsabilidad única de `performance` (qué SÍ hace).**
- Consume `scorecard.score` y `calibration.calibrated_pd_frame` ya publicados por SDD-09/10.
- Evalúa la discriminación del score/PD final por partición: Desarrollo, Holdout y OOT.
- Calcula KS con valor máximo y punto de corte, AUC/ROC, Gini (`2*AUC - 1`) y tabla de deciles/gains.
- Publica una tabla de rendimiento con deciles ordenados por riesgo, PD media por decil, buenos/malos, tasas, acumulados, gains, lift y KS acumulado.
- Aporta el sub-config **`PerformanceConfig`** (sección `performance` de `NikodymConfig`, ya reservada en SDD-05 como sección separada de `stability`).
- Expone `PerformanceCardSection` con `metric_sections` como puerta CT-2 para reporte/model card.
- Registra con `log_decision(regla, umbral, valor, accion)` cualquier umbral opcional de performance gatillado, si la institución lo configura.

**Responsabilidad única de `stability` (qué SÍ hace).**
- Mide estabilidad poblacional del score entre muestras: Desarrollo contra Holdout y Desarrollo contra OOT.
- Calcula CSI por característica final del scorecard, usando la distribución de contribuciones de puntos por atributo en v1, salvo que Cami ratifique un contrato adicional con bins WoE de `binning` (D-STAB-5).
- Mide estabilidad temporal del score por período/cohorte: distribución, medias, cuantiles y PSI de cada cohorte contra Desarrollo.
- Documenta y aplica defaults configurables de PSI: `<0.10` estable, `0.10-0.25` vigilar, `>0.25` redesarrollar.
- Aporta el sub-config **`StabilityConfig`** (sección `stability` de `NikodymConfig`), computacional e independiente de `performance`.
- Expone `StabilityCardSection` con `metric_sections` como puerta CT-2.
- Registra con `log_decision` cada cruce de banda PSI/CSI o umbral temporal.

**Frontera dura de responsabilidad (qué NO hace, y quién lo hace).**
- **No hace EDA pre-modelo.** SDD-27 (`eda`) mide tasa de default cruda por período/cohorte **antes** de binning y modelo. SDD-11 mide el **score/PD post-modelo** ya construido.
- **No reemplaza la selección pre-modelo.** SDD-07 (`selection`) calcula `stability_table` por variable/bin como diagnóstico de selección y, por defecto, `report_only`. SDD-11 mide estabilidad del score final y de sus características finales, sin decidir variables.
- **No ajusta ni reestima el modelo.** SDD-08 decide coeficientes, stepwise y PD cruda; SDD-09 escala a puntos; SDD-10 calibra PD.
- **No calibra PD ni ejecuta tests formales de calibración.** Hosmer-Lemeshow, binomial, Brier, traffic-light y backtesting formal pertenecen a SDD-22 (`validation`).
- **No aplica matrices CMF ni IFRS 9/ECL.** Esta capa produce evidencia de modelo; provisiones viven en SDD-15/16/17.
- **No muta artefactos aguas arriba.** Lee `data`/`model`/`scorecard`/`calibration` y publica copias defensivas bajo `"performance"` y `"stability"`.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Scoring (F1/T2). Corre después de `calibration`; `performance` corre primero y `stability` después, ambos antes de `report` y antes de la validación formal de F6.
- **Quién lo invoca:** `Study.run()` como secciones `performance` y `stability` de `NikodymConfig`. SDD-05 ya las define como dos secciones separadas; este SDD respeta esa frontera.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `AuditableMixin`, excepciones), artefactos de `data`, `model`, `scorecard` y `calibration`, pandas/numpy, pandera y scikit-learn con import perezoso.

```
data ─► eda ─► binning ─► selection ─► model ─► scorecard ─► calibration ─► performance ─► stability ─► report/validation
                                            η, PD cruda     score        PD calibrada      KS/AUC/deciles   PSI/CSI
```

**Interacción con `Study` y config declarativo.**

`PerformanceStep` y `StabilityStep` son `Step` nativos registrados con:

```python
@register("standard", domain="performance")
@register("standard", domain="stability")
```

Ambos declaran `requires`/`provides` (CT-1) y reciben `rng: numpy.random.Generator` por contrato homogéneo de `Step`. En v1 no tienen ningún componente estocástico: cada `execute` debe hacer `del rng` al inicio.

**Cableado implementado en `core.study`.** Los registros vigentes incluyen:

- `_DOMAIN_MODULES["performance"] = "nikodym.performance"` y `_DOMAIN_MODULES["stability"] = "nikodym.stability"`;
- `_DOMAIN_CONFIG_CLASSES["performance"] = ("nikodym.performance.config", "PerformanceConfig")`;
- `_DOMAIN_CONFIG_CLASSES["stability"] = ("nikodym.stability.config", "StabilityConfig")`;
- `_DEFAULT_DOMAIN_ORDER`: inmediatamente después de `"calibration"`, primero `"performance"` y luego `"stability"`.

**Normativa CMF relevante.** CMF CNC Capítulo B-1 exige que las metodologías internas tengan evidencia de predictibilidad, robustez, estabilidad, discriminación, validación y backtesting cuando se usen como componente PI. La norma no fija umbrales numéricos de PSI, KS, AUC o Gini para esta capa; por tanto los umbrales de alerta de SDD-11 son defaults institucionales/configurables, no parámetros regulatorios hardcodeados.

## 3. Conceptos y fundamentos

**Target y orientación.** El proyecto fija `target=1` como malo/default y `target=0` como bueno/no-default. SDD-09 propone `score_direction="higher_is_lower_risk"`: mayor score significa menor riesgo. Para métricas de discriminación, SDD-11 usa una columna de riesgo con orientación positiva hacia default:

`risk_score = pd_calibrated` cuando se evalúa PD calibrada.

`risk_score = -score` cuando se evalúa score con `higher_is_lower_risk`.

**AUC/ROC.** La curva ROC compara, para todos los cortes posibles de `risk_score`, la tasa de verdaderos malos capturados (`TPR`) contra la tasa de buenos mal clasificados como malos (`FPR`). `AUC` es el área bajo esa curva. AUC se reporta por partición y se calcula solo cuando hay ambas clases.

**Gini.** `Gini = 2*AUC - 1`. Con AUC orientado al riesgo, Gini cercano a 0 indica discriminación nula; valores mayores indican mejor ranking. SDD-11 no define banda regulatoria para Gini.

**KS.** `KS = max_t |TPR(t) - FPR(t)|`, evaluado sobre cortes de `risk_score`. Se publica:
- `ks`: valor máximo;
- `cutoff`: corte de `risk_score` donde ocurre;
- `tpr_at_ks`, `fpr_at_ks`;
- `score_cutoff` equivalente cuando la fuente es `score`.

**Tabla de deciles/gains.** Se ordena cada partición de mayor a menor riesgo. `decile=1` es el decil de mayor riesgo. Para cada decil se publica número de observaciones, buenos, malos, tasa observada de default, PD media, score medio/rango, acumulados, gain de malos y lift.

**PSI del score.** Population Stability Index compara la distribución de una variable entre una población esperada y una actual:

`PSI = Σ_b (actual_pct_b - expected_pct_b) * ln(actual_pct_b / expected_pct_b)`

Default de bandas configurable:
- `<0.10`: estable;
- `0.10-0.25`: vigilar;
- `>0.25`: redesarrollar.

Estas bandas vienen de práctica estándar ya recogida en ESPECIFICACIONES §5.2, no de un umbral CMF numérico. SDD-11 las publica como criterio institucional default.

**CSI por característica.** Characteristic Stability Index aplica la misma fórmula PSI a la distribución de cada característica final. En v1 recomendado se calcula sobre las columnas `<feature>__points` que publica `scorecard.score`, porque son la contribución auditable del scorecard final. Si Cami exige CSI sobre bins WoE exactos, `StabilityStep.requires` deberá sumar `("binning", "tables")`, `("binning", "woe_frame")` y `("binning", "result")` (D-STAB-5).

**Estabilidad temporal del score.** Agrega el score/PD por período o cohorte y mide drift de distribución contra Desarrollo o contra un período base: `n`, score medio, cuantiles, PD media calibrada y PSI temporal. No duplica la tasa de default cruda de SDD-27: aquí la unidad monitoreada es el **score/PD post-modelo**.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/performance/config.py
class PerformanceConfig(NikodymBaseConfig): ...

# nikodym/performance/exceptions.py
class PerformanceError(NikodymError): ...
class PerformanceDataError(PerformanceError): ...
class PerformanceMetricError(PerformanceError): ...
```

```python
# nikodym/performance/results.py
class DiscriminantMetricRecord(BaseModel): ...
class DecilePerformanceRecord(BaseModel): ...
class PerformanceCardSection(BaseModel): ...
class PerformanceResult(BaseModel): ...

# nikodym/performance/evaluator.py
class PerformanceEvaluator:
    def evaluate(
        self,
        frame: "pandas.DataFrame",
        *,
        score_column: str,
        pd_column: str,
        target_column: str,
        partition_column: str,
    ) -> "PerformanceResult": ...
```

```python
# nikodym/performance/step.py
@register("standard", domain="performance")
class PerformanceStep(AuditableMixin):
    name: str = "performance"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "labels"),
        ("data", "splits"),
        ("model", "raw_pd_frame"),
        ("model", "final_features"),
        ("scorecard", "score"),
        ("calibration", "calibrated_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("performance", "performance_table"),
        ("performance", "discriminant_metrics"),
        ("performance", "result"),
        ("performance", "card"),
    )
    @classmethod
    def from_config(cls, cfg: PerformanceConfig) -> "PerformanceStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "PerformanceResult": ...
```

**Artefactos que `PerformanceStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"performance_table"` | `pandas.DataFrame` | tabla de deciles/gains por partición |
| `"discriminant_metrics"` | `pandas.DataFrame` | KS, cutoff, AUC, Gini, n, malos/buenos por partición |
| `"result"` | `PerformanceResult` | contenedor agregado |
| `"card"` | `PerformanceCardSection` | resumen para governance/report |

```python
# nikodym/stability/config.py
class StabilityConfig(NikodymBaseConfig): ...

# nikodym/stability/exceptions.py
class StabilityError(NikodymError): ...
class StabilityDataError(StabilityError): ...
class StabilityMetricError(StabilityError): ...
```

```python
# nikodym/stability/results.py
class StabilityMetricRecord(BaseModel): ...
class PsiRecord(BaseModel): ...
class CsiRecord(BaseModel): ...
class TemporalStabilityRecord(BaseModel): ...
class StabilityCardSection(BaseModel): ...
class StabilityResult(BaseModel): ...

# nikodym/stability/evaluator.py
class StabilityEvaluator:
    def evaluate(
        self,
        frame: "pandas.DataFrame",
        *,
        score_column: str,
        pd_column: str,
        partition_column: str,
        feature_point_columns: tuple[str, ...],
    ) -> "StabilityResult": ...
```

```python
# nikodym/stability/step.py
@register("standard", domain="stability")
class StabilityStep(AuditableMixin):
    name: str = "stability"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "frame"),
        ("data", "labels"),
        ("data", "splits"),
        ("model", "raw_pd_frame"),
        ("model", "final_features"),
        ("scorecard", "score"),
        ("calibration", "calibrated_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("stability", "psi_table"),
        ("stability", "stability_metrics"),
        ("stability", "result"),
        ("stability", "card"),
    )
    @classmethod
    def from_config(cls, cfg: StabilityConfig) -> "StabilityStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "StabilityResult": ...
```

**Artefactos que `StabilityStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"psi_table"` | `pandas.DataFrame` | PSI de score/PD por comparación y bins |
| `"stability_metrics"` | `pandas.DataFrame` | resumen PSI, CSI y estabilidad temporal por banda |
| `"result"` | `StabilityResult` | contenedor agregado |
| `"card"` | `StabilityCardSection` | resumen para governance/report |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=[
    "data", "eda", "binning", "selection", "model",
    "scorecard", "calibration", "performance", "stability",
])
perf = study.artifacts.get("performance", "discriminant_metrics")
psi = study.artifacts.get("stability", "psi_table")
```

## 5. Configuración (schema Pydantic)

`PerformanceConfig` y `StabilityConfig` son sub-configs independientes de `NikodymConfig`. Siguen SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, campos con `title`/`description`, rangos `ge/le`, categóricos `Literal`, metadatos `ui_*`, y `type: Literal["standard"] = "standard"` como discriminador de nivel sección.

Este SDD declara además `schema_version: str = "1.0.0"` en cada sub-config como versión local del sub-schema del paquete. No reemplaza el `schema_version` raíz de SDD-05; permite migraciones locales futuras si estos dominios cambian su shape.

```python
# nikodym/performance/config.py
class PerformanceConfig(NikodymBaseConfig):
    schema_version: str = "1.0.0"
    type: Literal["standard"] = "standard"
    score_column: str = Field("score", title="Columna score")
    pd_column: str = Field("pd_calibrated", title="Columna PD calibrada")
    target_column: str = Field("target", title="Columna target")
    partition_column: str = Field("partition", title="Columna partición")
    score_direction: Literal["higher_is_lower_risk", "higher_is_higher_risk"] = Field(
        "higher_is_lower_risk", title="Dirección del score")
    evaluation_source: Literal["pd_calibrated", "score"] = Field(
        "pd_calibrated", title="Fuente principal de ranking")
    partitions: tuple[Literal["desarrollo", "holdout", "oot"], ...] = Field(
        ("desarrollo", "holdout", "oot"), title="Particiones a evaluar")
    n_deciles: int = Field(10, ge=2, le=50, title="Número de grupos de gains")
    min_rows_per_partition: int = Field(30, ge=1, title="Mínimo técnico de filas")
    min_events_per_partition: int = Field(1, ge=1, title="Mínimo técnico de malos")
    optional_thresholds: dict[str, float] = Field(
        default_factory=dict,
        title="Umbrales institucionales opcionales",
        description="Ej.: {'auc_min': 0.60, 'ks_min': 0.20}. Vacío por defecto.",
    )
```

```python
# nikodym/stability/config.py
class StabilityConfig(NikodymBaseConfig):
    schema_version: str = "1.0.0"
    type: Literal["standard"] = "standard"
    score_column: str = Field("score", title="Columna score")
    pd_column: str = Field("pd_calibrated", title="Columna PD calibrada")
    partition_column: str = Field("partition", title="Columna partición")
    score_direction: Literal["higher_is_lower_risk", "higher_is_higher_risk"] = Field(
        "higher_is_lower_risk", title="Dirección del score")
    psi_bins: int = Field(10, ge=2, le=50, title="Bins para PSI de score")
    csi_bins: int = Field(10, ge=2, le=50, title="Bins para CSI si no hay puntos discretos")
    psi_stable_threshold: float = Field(0.10, ge=0.0, title="PSI estable hasta")
    psi_review_threshold: float = Field(0.25, ge=0.0, title="PSI vigilar hasta")
    smoothing: float = Field(1e-6, gt=0.0, title="Suavizado de proporciones")
    comparisons: tuple[Literal["dev_vs_holdout", "dev_vs_oot"], ...] = Field(
        ("dev_vs_holdout", "dev_vs_oot"), title="Comparaciones de estabilidad")
    temporal_axis: Literal["none", "period", "cohort"] = Field(
        "period", title="Eje temporal del score")
    temporal_column: str | None = Field(
        None,
        title="Columna de período/cohorte",
        description="Si None, se infiere solo si hay una columna inequívoca en data.frame.",
    )
    temporal_freq: Literal["M", "Q", "Y"] = Field("M", title="Frecuencia temporal")
    include_pd_stability: bool = Field(True, title="Incluir estabilidad de PD calibrada")
    csi_source: Literal["score_points", "woe_bins"] = Field(
        "score_points",
        title="Fuente de CSI",
        description="woe_bins exige ratificar requires adicionales de binning.",
    )
```

**Validaciones de config.**
- `psi_stable_threshold < psi_review_threshold`.
- `score_column`, `pd_column`, `target_column`, `partition_column` no pueden ser vacíos ni colisionar.
- `optional_thresholds` solo admite claves documentadas (`auc_min`, `gini_min`, `ks_min`, `psi_max`, `csi_max`) y valores finitos.
- `temporal_axis != "none"` con `temporal_column=None` permite inferencia solo si `data.frame` tiene una columna temporal/cohorte inequívoca; si no, runtime falla con error claro.
- `csi_source="woe_bins"` requiere que el SDD aprobado agregue los `requires` de `binning`; en este borrador queda decisión de Cami (D-STAB-5).

**Defaults defendibles.**
- `evaluation_source="pd_calibrated"`: la PD calibrada es el artefacto final de probabilidad; el score se conserva para tabla de deciles y lectura operacional.
- `n_deciles=10`: coincide con ESPECIFICACIONES §5.2 y práctica de tabla de gains.
- Umbrales de KS/AUC/Gini vacíos por defecto: no hay parámetro CMF numérico que autorice hardcodearlos.
- PSI `0.10/0.25`: estándar de monitoreo recogido en ESPECIFICACIONES, configurable y auditado.
- `csi_source="score_points"`: no introduce dependencia dura adicional con `binning` hasta que Cami confirme la frontera.

**Hook implementado en `core.config.schema`.** El contrato vigente:
- declarar `_PERFORMANCE_CONFIG_CLS` y `_STABILITY_CONFIG_CLS`;
- añadir validators `_valida_performance` y `_valida_stability`;
- importar `nikodym.performance` y `nikodym.stability` para poblar hooks y registrar Steps;
- ninguna de las dos secciones entra a `INFRA_SECTIONS`: cambiar métricas, bins o thresholds cambia `config_hash`.

## 6. Contratos de datos (I/O)

**Inputs de `PerformanceStep` vía `Study` (nombres reales de SDD vecinos).**
- `("calibration", "calibrated_pd_frame")`: índice original modelable + `partition`, `target`, `linear_predictor`, `pd_raw`, `linear_predictor_calibrated`, `pd_calibrated`.
- `("scorecard", "score")`: filas modelables con columnas `<feature>__points`, `score`, y estructurales disponibles (`partition`, `target`, `linear_predictor`, `pd_raw`).
- `("model", "raw_pd_frame")`: PD cruda y predictor lineal para trazabilidad y reconciliación.
- `("model", "final_features")`: tuple de features finales, usado para card y trazabilidad.
- `("data", "labels")`: `LabeledFrame`, fuente de nombres reales de target/status cuando la implementación los exponga.
- `("data", "splits")`: `PartitionResult`, fuente de partición/catálogos de split.

**Inputs de `StabilityStep` vía `Study`.**
- Los mismos artefactos de `scorecard`, `calibration`, `model`, `labels` y `splits`.
- `("data", "frame")`: se usa solo para recuperar una columna de período/cohorte cuando `scorecard.score` no la propagó. No se recalcula target ni partición.

**Frame analítico común.** Ambos Steps construyen una tabla interna alineada por índice, con copias profundas (`copy(deep=True)`):

| columna | fuente | uso |
|---|---|---|
| `partition` | calibration/scorecard/data | split Desarrollo/HO/OOT |
| `target` | calibration/scorecard/data | métricas supervisadas de performance |
| `score` | scorecard.score | score operacional |
| `pd_calibrated` | calibration.calibrated_pd_frame | PD final |
| `pd_raw` | model/calibration | trazabilidad |
| `risk_score` | derivada | ranking orientado a default |
| `<feature>__points` | scorecard.score | CSI por característica |
| `period`/`cohort` | data.frame o scorecard.score | estabilidad temporal |

**Output `performance_table`.** `pandas.DataFrame`, orden canónico por `partition`, `decile` ascendente:

| columna | significado |
|---|---|
| `partition` | desarrollo/holdout/oot |
| `decile` | 1 = mayor riesgo |
| `n_total`, `n_bad`, `n_good` | conteos |
| `bad_rate`, `good_rate` | tasas del decil |
| `mean_pd`, `min_pd`, `max_pd` | PD calibrada por decil |
| `mean_score`, `min_score`, `max_score` | score por decil |
| `cum_total`, `cum_bad`, `cum_good` | acumulados hasta el decil |
| `cum_bad_capture_rate` | `cum_bad / total_bad` |
| `cum_good_capture_rate` | `cum_good / total_good` |
| `lift` | `bad_rate / bad_rate_partition` |
| `ks_at_decile` | diferencia acumulada de tasas malos/buenos |

**Output `discriminant_metrics`.** `pandas.DataFrame`, una fila por partición:

| columna | significado |
|---|---|
| `partition` | split evaluado |
| `n_total`, `n_bad`, `n_good` | población supervisada |
| `auc`, `gini`, `ks` | métricas de discriminación |
| `ks_cutoff_risk_score` | corte de `risk_score` en KS máximo |
| `ks_cutoff_score` | corte equivalente de score cuando aplica |
| `tpr_at_ks`, `fpr_at_ks` | componentes del KS |
| `source` | `pd_calibrated` o `score` |
| `status` | `ok`, `not_evaluable`, `threshold_flag` |

**Output `psi_table`.** `pandas.DataFrame`, una fila por comparación, variable y bin:

| columna | significado |
|---|---|
| `metric` | `score_psi`, `pd_psi` o `csi` |
| `comparison` | `dev_vs_holdout`, `dev_vs_oot` o período/cohorte |
| `feature` | feature final para CSI, o `score`/`pd_calibrated` |
| `bin_label` | bin de score/PD/puntos |
| `expected_count`, `actual_count` | conteos |
| `expected_pct`, `actual_pct` | proporciones suavizadas |
| `component_value` | aporte al PSI/CSI |
| `total_value` | PSI/CSI total repetido para lectura |
| `band` | `stable`, `review`, `redevelop` |

**Output `stability_metrics`.** `pandas.DataFrame`, resumen por métrica/comparación:

| columna | significado |
|---|---|
| `metric` | `score_psi`, `pd_psi`, `csi`, `temporal_score` |
| `comparison` | muestra o cohorte |
| `feature` | feature final o `score` |
| `value` | PSI/CSI o indicador temporal |
| `stable_threshold`, `review_threshold` | umbrales usados |
| `band` | banda asignada |
| `action` | `none`, `vigilar`, `redesarrollar` |

**Validación pandera.** Los módulos definen schemas de entrada/salida con `import pandera.pandas as pa`, nunca `import pandera as pa`, para evitar warnings del top-level bajo `filterwarnings=["error"]`.

**Invariantes.**
- Índice único y alineado entre `scorecard.score` y `calibration.calibrated_pd_frame`.
- `score` y `pd_calibrated` finitos; `0 < pd_calibrated < 1`.
- `target` supervisado en `{0,1}` para métricas AUC/KS/Gini; filas sin target pueden existir para estabilidad no supervisada pero no para performance.
- Ningún Step escribe bajo dominios aguas arriba.
- Deciles y bins tienen orden estable; empates se resuelven por índice estable, no por orden accidental de pandas.
- Floats publicados normalizan `-0.0 -> 0.0`.

## 7. Algoritmos y flujo

**`PerformanceStep.execute(study, rng)` - secuencia canónica.**
1. **Descartar azar.** `del rng`; performance v1 es determinista.
2. **Leer artefactos.** Validar CT-1 y tipos de `calibrated_pd_frame`, `score`, `raw_pd_frame`, `final_features`, `labels`, `splits`.
3. **Copias defensivas.** Trabajar sobre `copy(deep=True)` de cada DataFrame.
4. **Alinear por índice.** Unir score y PD calibrada por índice; validar que no se pierden filas modelables sin evento auditado.
5. **Construir `risk_score`.** Usar PD calibrada o score según config, con orientación positiva hacia default.
6. **Validar particiones.** Iterar Desarrollo/Holdout/OOT configuradas; particiones vacías se marcan `not_evaluable` y se auditan.
7. **Calcular AUC/Gini/ROC.** Usar `sklearn.metrics.roc_auc_score`/`roc_curve` con import perezoso y target binario.
8. **Calcular KS.** Desde la curva ROC o desde acumulados ordenados por `risk_score`; elegir el primer cutoff en orden canónico si hay empate.
9. **Construir deciles/gains.** Ordenar por `risk_score` descendente; asignar grupos de tamaño lo más uniforme posible; calcular conteos, tasas, acumulados, lift y KS acumulado.
10. **Aplicar thresholds opcionales.** Si `optional_thresholds` trae mínimos/máximos, emitir `log_decision` por cada cruce.
11. **Construir DTOs/card.** Incluir versiones de pandas/numpy/sklearn, thresholds, particiones evaluadas y `metric_sections`.
12. **Publicar artefactos.** Escribir `"performance_table"`, `"discriminant_metrics"`, `"result"` y `"card"`.

**`StabilityStep.execute(study, rng)` - secuencia canónica.**
1. **Descartar azar.** `del rng`; stability v1 es determinista.
2. **Leer artefactos.** Validar `score`, `calibrated_pd_frame`, `raw_pd_frame`, `final_features`, `data.frame`, `labels`, `splits`.
3. **Copias defensivas y alineación.** Alinear por índice y conservar solo filas modelables con score finito.
4. **PSI de score.** Definir bins con Desarrollo como población esperada; aplicar los mismos cortes a Holdout/OOT; suavizar proporciones cero; calcular componentes y total.
5. **PSI de PD calibrada.** Si `include_pd_stability=True`, repetir el cálculo sobre `pd_calibrated`.
6. **CSI por característica.** Para cada feature final, localizar `<feature>__points` en `scorecard.score`; comparar distribución Desarrollo contra Holdout/OOT. Si `csi_source="woe_bins"`, exigir contrato de binning ratificado.
7. **Estabilidad temporal.** Resolver `temporal_column` desde `data.frame` o fallar si es ambiguo; agregar score/PD por período/cohorte y calcular PSI temporal contra Desarrollo o período base.
8. **Asignar bandas.** `stable`, `review`, `redevelop` según thresholds configurados.
9. **Auditar umbrales.** Por cada métrica en `review` o `redevelop`, emitir `log_decision(regla="psi_score"|"csi_feature"|"score_temporal", umbral=..., valor=..., accion=...)`.
10. **Construir DTOs/card.** Incluir máximos, comparaciones, features con peor CSI, bandas y `metric_sections`.
11. **Publicar artefactos.** Escribir `"psi_table"`, `"stability_metrics"`, `"result"` y `"card"`.

**Alternativas descartadas.**
- *Un solo Step combinado `performance_stability`:* descartado como default; SDD-05 ya separa `performance` y `stability`, y las responsabilidades/auditoría son distintas.
- *Calcular KS/AUC/Gini en `model`:* descartado; `model` puede tener diagnósticos in-sample, pero la validación formal multi-partición vive aquí.
- *Usar thresholds regulatorios hardcodeados de KS/AUC/Gini:* descartado; CMF no fija esos números para scorecards.
- *Usar `df.eval`/`eval` para reglas de bins o thresholds:* descartado por seguridad y consistencia con SDD-02. Toda regla se codifica como operaciones estructuradas.
- *Rebinnear score con Holdout/OOT:* descartado; los bins esperados se fijan en Desarrollo para evitar drift de definición.

**Complejidad / rendimiento.** Las métricas son O(n log n) por partición por el ordenamiento de scores; PSI/CSI son O(n * p) para `p` características finales. Scorecards tienen p acotado por `selection`/`model`; no se requiere paralelismo v1.

## 8. Casos borde y manejo de errores

- **Faltan artefactos aguas arriba:** `ArtifactNotFoundError` por CT-1 antes de ejecutar.
- **Índices no únicos o no alineables:** `PerformanceDataError`/`StabilityDataError`; no se hace merge ambiguo.
- **Partición vacía:** se publica fila `not_evaluable` y se audita; no aborta salvo que todas las particiones sean vacías.
- **Partición con una sola clase:** AUC/KS/Gini `not_evaluable` para esa partición; stability puede seguir.
- **`pd_calibrated` fuera de `(0,1)` o no finita:** error ruidoso; SDD-11 no corrige PD aguas arriba.
- **Score no finito:** error en performance/stability; no se imputa ni se filtra silenciosamente.
- **Score constante:** AUC puede ser 0.5 y KS 0.0 si hay ambas clases; se audita como discriminación nula si hay threshold opcional.
- **Deciles con pocos registros o muchos empates:** se usa asignación determinista por ranking estable; deciles efectivos pueden ser menos que `n_deciles` y se reporta.
- **OOT no configurado o ausente:** `dev_vs_oot` se marca `not_evaluable` sin bloquear Dev/HO.
- **Proporciones cero en PSI/CSI:** aplicar `smoothing`; el valor queda trazado en config/card.
- **Columna temporal ambigua:** `StabilityDataError` pidiendo `stability.temporal_column`.
- **`csi_source="woe_bins"` sin contrato de binning aprobado:** `ConfigError` claro, salvo que el SDD se haya actualizado con los `requires` adicionales.
- **CMF no fija umbral:** cualquier umbral institucional se etiqueta como config/decisión interna, no como norma.

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen regla, umbral, valor observado, partición/feature y acción.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno en v1. Ambos Steps reciben `rng` por contrato y hacen `del rng`.
- **Determinismo esperado.** `(data_hash + config_hash + scorecard.score + calibrated_pd_frame + uv.lock) -> métricas, tablas y cards idénticos`.
- **Copias defensivas.** Todo DataFrame de entrada se copia con `deep=True`; nunca se mutan artefactos aguas arriba.
- **Orden estable.** Particiones en orden `desarrollo`, `holdout`, `oot`; deciles ascendente; features en orden de `model.final_features`; bins por cortes de Desarrollo e índice estable para empates.
- **Normalización numérica.** Publicar `-0.0` como `0.0`; floats finitos salvo estados `not_evaluable` documentados. Si algún módulo emite hashes auxiliares para goldens, usar endianness explícito (`astype("<u8")`) y nunca `hash()` builtin.
- **Audit trail (`log_decision`).** Registrar:
  - umbrales opcionales de `performance` gatillados (`auc_min`, `gini_min`, `ks_min`);
  - particiones no evaluables por una sola clase o bajo mínimo;
  - PSI score/PD que cruza `review` o `redevelop`;
  - CSI por feature que cruza banda;
  - estabilidad temporal que cruza banda;
  - uso de smoothing por proporciones cero cuando afecte una comparación.
- **Card / report.** `PerformanceCardSection` y `StabilityCardSection` deben permitir reconstruir fuente de ranking, particiones, thresholds, bins, máximos, bandas, features afectadas y versiones de dependencias.
- **Lineage.** SDD-11 no completa `data_hash` ni `config_hash`; su contribución son config computacional, versiones, resultados estructurados y decisiones auditadas.

Convenciones obligatorias de implementación: `import pandera.pandas as pa`; prohibido `eval`/`df.eval`; `mypy --strict`; ruff con regla `D` y docstrings en español; identificadores/API en inglés técnico; tests con `filterwarnings=["error"]`.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymError`, `MissingDependencyError`, `Registry`.
- SDD-02 (`data`): `frame`, `labels`, `splits`, particiones Desarrollo/HO/OOT y target binario.
- SDD-05: config Pydantic, hooks diferidos, `config_hash`, naming y UI metadata.
- SDD-08 (`model`): `raw_pd_frame`, `final_features`.
- SDD-09 (`scorecard`): `score` y columnas `<feature>__points`.
- SDD-10 (`calibration`): `calibrated_pd_frame`.
- SDD-22 (`validation`): consumidor de métricas y cards para validación formal.
- SDD-26 (`report`): consumidor de tablas y cards.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | `>=2.0` | BSD-3 ✅ | DataFrames, groupby, ranking, tablas | base |
| numpy | `>=1.22` | BSD ✅ | arrays, cuantiles, finitud, normalización | base |
| pandera | `>=0.24` | MIT ✅ | schemas I/O con `import pandera.pandas as pa` | base |
| scikit-learn | `>=1.6`, `<1.8` por constraint | BSD-3 ✅ | `roc_auc_score`, `roc_curve`, `auc` | extra `[scoring]`, import perezoso |

**Núcleo liviano.** `nikodym.core` no importa `performance`, `stability` ni sklearn. `import nikodym.performance` y `import nikodym.stability` registran config/step sin importar sklearn en top-level; el import de métricas ocurre dentro de `execute`/evaluators y levanta `MissingDependencyError("instale nikodym[scoring]")` si falta el extra.

**Normativa.** No hay dependencia de tablas CMF en SDD-11. La evidencia regulatoria es metodológica: discriminación, estabilidad, trazabilidad y backtesting formal aguas abajo.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **Golden AUC/Gini.** Dataset pequeño con ranking conocido; verificar AUC y `Gini = 2*AUC - 1`.
- **Golden KS.** Caso con corte manual conocido; verificar `ks`, `cutoff`, `tpr_at_ks` y `fpr_at_ks`.
- **Tabla deciles/gains.** Fixture con 20 filas y score ordenado; verificar deciles, malos/buenos, acumulados, lift y `ks_at_decile` con valores de oro.
- **Orientación del score.** Con `higher_is_lower_risk`, `risk_score=-score`; con dirección inversa, `risk_score=score`. Verificar que AUC no queda invertido por error de signo.
- **Golden PSI.** Distribuciones esperada/actual con proporciones conocidas; verificar fórmula, smoothing y bandas `<0.10`, `0.10-0.25`, `>0.25`.
- **Golden CSI.** Dos características con columnas `<feature>__points`; verificar CSI por feature y feature de peor estabilidad.
- **Estabilidad temporal.** Frame con períodos/cohortes conocidos; verificar agregados de score/PD y PSI temporal.
- **No duplicar EDA.** Test de frontera conceptual: cambiar solo tasa de default cruda por período sin cambiar score/PD no altera PSI del score; SDD-27 cubre la tasa cruda.
- **No duplicar SDD-22.** Hosmer-Lemeshow/binomial/traffic-light no aparecen en outputs de SDD-11.
- **Contratos `Step`.** `PerformanceStep.requires` y `StabilityStep.requires` exigen las claves exactas de §4; falta una -> `ArtifactNotFoundError`. `provides` publica las cuatro claves por dominio.
- **No mutación.** Snapshots profundos de `scorecard.score`, `calibrated_pd_frame`, `raw_pd_frame` y `data.frame` permanecen iguales.
- **Audit trail.** Thresholds opcionales y PSI/CSI que cruzan banda emiten exactamente los `AuditEvent(kind="decision")` esperados con `regla`, `umbral`, `valor`, `accion`.
- **Config.** Round-trip YAML de `PerformanceConfig`/`StabilityConfig`; cambiar bins, thresholds, fuente de ranking o dirección de score cambia `config_hash`; performance/stability no están en `INFRA_SECTIONS`.
- **Pandera.** Validar schemas con `import pandera.pandas as pa`; no usar top-level pandera.
- **Seguridad.** Buscar en AST que no haya `eval` ni `df.eval`/`DataFrame.query` para reglas de thresholds o bins.
- **Reproducibilidad.** Dos corridas con mismos artefactos/config producen tablas bit-idénticas; `-0.0 -> 0.0`; hashes auxiliares con endianness explícito.
- **Import liviano.** `import nikodym.core` no importa `nikodym.performance`, `nikodym.stability` ni sklearn; importar cada dominio no importa sklearn hasta ejecutar métricas.
- **Tooling.** Suite bajo `filterwarnings=["error"]`; `mypy --strict`; ruff con regla `D`; cobertura objetivo global según SDD-24 y tests canónicos con golden values.

Fixtures: `behavior_performance_small.parquet`, `calibrated_pd_frame` sintético, `scorecard.score` sintético con puntos por atributo, `PerformanceConfig` y `StabilityConfig` mínimos/completos, `InMemoryAuditSink`.

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Confundir métricas crudas con validación regulatoria completa.** Mitigación: SDD-11 publica performance/stability; SDD-22 ejecuta validación formal y backtesting.
- **Falsos umbrales regulatorios.** Mitigación: PSI defaults marcados como criterio institucional; KS/AUC/Gini sin semáforo regulatorio default.
- **Orientación invertida del score.** Mitigación: `score_direction` explícito, `risk_score` derivado y tests de orientación.
- **Leakage en estabilidad.** Mitigación: bins/cortes de PSI definidos en Desarrollo y aplicados a HO/OOT.
- **CSI ambiguo.** Mitigación: default sobre puntos por atributo; decisión D-STAB-5 antes de implementar si se requiere WoE-bin CSI.
- **Muestras pequeñas.** Mitigación: estados `not_evaluable` auditados, no métricas engañosas.
- **Duplicación con SDD-27/07/22.** Mitigación: fronteras escritas en §1, §3 y tests específicos.

**Fuentes verificadas / citas.**
- **ESPECIFICACIONES.md** §5.2: estabilidad del score, tabla de rendimiento, PSI fórmula y bandas, ROC/AUC, KS, Gini; §5.7: validación formal separada; §6.3: paquetes `performance/` y `stability/`.
- **SDD-05** §5.1: `performance` y `stability` son secciones separadas de `NikodymConfig`; §5.5 `config_hash`; §9 `log_decision`.
- **SDD-07** §1/§3/§6: `stability_table` por variable/bin en selección es diagnóstico pre-modelo, no estabilidad del score final.
- **SDD-08** §4/§6: artefactos reales `raw_pd_frame` y `final_features`.
- **SDD-09** §4/§6/§9: artefactos reales `scorecard.score`, dirección del score y uso de `risk_score=-score` para discriminación.
- **SDD-10** §4/§6: artefacto real `calibrated_pd_frame`; tests formales de calibración quedan fuera.
- **SDD-27** §1/§12: EDA mide tasa de default cruda pre-modelo; SDD-11 mide score/PD post-modelo.
- **_CONTRATOS-TRANSVERSALES.md** CT-1 (`requires`/`provides`) y CT-2 (`metric_sections`).
- **CMF oficial:** CNC Capítulo B-1, Anexos 1 y 2, versión 2022 publicada por CMF. Revisión 2026-06-28: exige documentación, validación, estabilidad/robustez y backtesting para metodologías internas, pero no fija umbrales numéricos de PSI/KS/AUC/Gini. Fuente oficial: `https://www.cmfchile.cl/institucional/mercados/ver_archivo.php?archivo=/web/compendio/cir/cir_2249_2020.pdf`.

## Decisiones para revisión de Cami

- **D-PERF-1 - Métricas obligatorias v0.1.0.** Recomendación: obligatorias KS, AUC, Gini, tabla deciles/gains, PSI score Dev-HO/Dev-OOT, CSI por característica final y estabilidad temporal del score si hay columna temporal. Diferibles: intervalos bootstrap, curvas ROC como objeto gráfico avanzado y swap-set/swap-analysis.
- **D-PERF-2 - Umbrales PSI/KS/AUC/Gini.** Recomendación: PSI configurable con defaults `0.10/0.25`; KS/AUC/Gini sin umbral default, solo valores crudos y umbrales institucionales opt-in. CMF no fija números.
- **D-PERF-3 - Semáforo regulatorio para KS/AUC/Gini.** Recomendación: no crear traffic-light regulatorio en v0.1.0. Si un banco lo exige, que entre por config con etiqueta institucional. Traffic-light formal de calibración queda en SDD-22.
- **D-PERF-4 - Dos Steps separados.** Recomendación: mantener `performance` y `stability` separados, coherente con SDD-05 y con auditoría distinta. Un Step combinado reduciría superficie pero mezclaría responsabilidades.
- **D-STAB-5 - CSI y bins WoE.** Recomendación MVP: CSI sobre `<feature>__points` de `scorecard.score`, porque mide la característica publicada de la scorecard final sin nuevo `requires`. Si Cami quiere CSI regulatorio por bins WoE exactos, añadir `("binning","tables")`, `("binning","woe_frame")`, `("binning","result")` a `StabilityStep.requires`.
- **D-PERF-6 - Swap-set / swap-analysis.** Recomendación: futuro, no v0.1.0. Consume score operacional y cutoffs de negocio que aún no están fijados.
- **D-PERF-7 - Umbrales CMF no fijados por norma.** Recomendación: no inventar umbrales regulatorios. Todo número no publicado por CMF vive como default institucional configurable y auditado.
- **D-PERF-8 - Fuente principal de ranking.** Recomendación: `pd_calibrated` para métricas principales y `score` para deciles/reporting; reportar ambos cuando diverjan por redondeo.
- **D-STAB-9 - Estabilidad temporal.** Recomendación: si no hay columna temporal inequívoca, fallar con mensaje claro y permitir `temporal_axis="none"`; no inferir en silencio.
