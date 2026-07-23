# SDD-07 — `selection` (selección pre-modelo de variables WoE para scorecard)

| Campo | Valor |
|---|---|
| **SDD** | 07 |
| **Módulo** | `nikodym.selection` |
| **Fase** | F1 |
| **Tanda de producción** | T2 (Scoring) |
| **Estado** | ✅ Implementado; pipeline F1 estable |
| **Depende de** | SDD-01 (`core`), SDD-02 (`data`), SDD-05 (convenciones + config), SDD-06 (`binning`) |
| **Lo consumen** | SDD-08 (`model`), SDD-09 (`scorecard`), SDD-11 (`performance` + `stability`), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (redacción SDD-07 para T2) / 2026-06-27 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `selection` toma las variables ya transformadas a WoE por `binning` (SDD-06), aplica filtros pre-modelo auditables sobre la partición de Desarrollo, y publica el subconjunto de features que entra al modelo logístico de SDD-08.

**Responsabilidad única (qué SÍ hace).**
- Selecciona variables **antes** del ajuste del modelo, usando diagnósticos univariados y multivariados independientes del modelo: IV mínimo, correlación entre columnas WoE, VIF y descartes/manual overrides de negocio.
- Consume el IV final sobre bins óptimos que publica `binning.summary`; **no recalcula bins**.
- Calcula diagnósticos univariados por variable WoE sobre bins fijados: ROC/AUC, KS, Gini y, cuando hay partición/período disponible, PSI/CSI como estabilidad descriptiva.
- Decide inclusión/exclusión **solo con Desarrollo** para evitar leakage. Holdout/OOT se reportan como diagnóstico posterior, pero no influyen en la selección.
- Publica artefactos namespaced bajo `"selection"`: features seleccionadas, tabla de selección, matriz de correlación, tabla VIF, tabla de estabilidad, frame WoE filtrado, card y resultado agregado.
- Aporta el sub-config **`SelectionConfig`** (sección `selection` de `NikodymConfig`), computacional y por tanto incluido en el `config_hash`.
- Registra cada exclusión/flag relevante con `log_decision(regla=..., umbral=..., valor=..., accion=...)`.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No hace binning ni WoE.** SDD-06 aprende bins, calcula WoE/IV y transforma el dataset. SDD-07 usa esos artefactos.
- **No hace EDA descriptivo pre-binning.** SDD-27 puede reportar `descriptive_iv` opt-in sobre cuantiles descriptivos; `selection` usa el IV final de SDD-06 (`binning.summary.iv`), no el IV de EDA.
- **No ajusta regresión logística ni hace stepwise.** `stepwise` forward/backward por Wald/LR, p-values, regla dura de signos de β e IV-contribution ≤ 90 % son de SDD-08 (`model`). SDD-07 no mira coeficientes, p-values ni likelihood.
- **No calibra PD ni escala puntos.** SDD-10 calibra; SDD-09 construye la scorecard.
- **No calcula estabilidad del score final.** SDD-11 calcula PSI del score/modelo; SDD-07 solo puede reportar estabilidad pre-modelo por característica/bin.
- **No muta artefactos aguas arriba.** Nunca escribe bajo `"data"` ni `"binning"`; publica un `selected_woe_frame` propio bajo `"selection"`.
- **No aplica parámetros CMF ni IFRS 9.** Las matrices y fórmulas regulatorias se usan en provisiones, no para seleccionar features de scorecard.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Scoring (F1/T2). Corre después de `binning` y antes de `model` en el pipeline de scorecard de comportamiento.
- **Quién lo invoca:** `Study.run()` como sección `selection` de `NikodymConfig` (orden canónico: `data → eda → binning → selection → model → ...`). También puede usarse standalone en notebooks/tests.
- **A quién invoca:** `core` (`Step`, `ArtifactStore`, `AuditableMixin`, excepciones), artefactos de `data` y `binning`, y librerías estadísticas del extra `[scoring]` con import perezoso.

```
data ─► eda (opcional, diagnóstico) ─► binning ─► selection ─► model ─► scorecard
                                  tablas WoE/IV       │
                                  woe_frame            ▼
                                  process       selected_features
                                                selected_woe_frame
                                                selection_table
```

**Interacción con `Study` y config declarativo.** `SelectionStep` es un `Step` nativo registrado con `@register("standard", domain="selection")`. Declara `requires`/`provides` (CT-1) y `execute(study, rng)`: lee artefactos de `data` y `binning`, ajusta la selección en Desarrollo, transforma el `woe_frame` completo a columnas seleccionadas y escribe sus artefactos bajo `"selection"`. El `rng` se recibe por contrato homogéneo de `Step`, pero v1 no introduce azar.

**Frontera crítica con `model` / stepwise.** La ESPEC separa dos momentos: primero filtros pre-modelo sobre bins fijados (IV, métricas univariadas, correlación, VIF, negocio) y después **stepwise** dentro de la logística con statsmodels. Este SDD fija la frontera así:
- `selection` decide un **conjunto candidato limpio y defendible** antes de estimar coeficientes.
- `model` decide la **especificación final del modelo logístico** con p-values, Wald/LR, signos de β, IV-contribution y ajuste.
- Si Cami prefiere mover algún filtro (p.ej. discriminación mínima por ROC) a `model`, queda marcado en D-SEL-2; el default propuesto aquí lo reporta en `selection` y solo usa IV/correlación/VIF/negocio como filtros activos.

## 3. Conceptos y fundamentos

- **Feature candidata.** Variable raw que `binning` logró transformar a una columna WoE (`raw_feature -> raw_feature__woe`). `selection` trabaja sobre columnas WoE, pero conserva el nombre raw para auditoría y reporte.
- **IV (Information Value).** SDD-06 calcula `IV = Σ_b (%Goods_b - %Bads_b) · WoE_b`, con `WoE_b = ln(%Goods_b / %Bads_b)`. SDD-07 aplica el corte de selección sobre ese IV final de Desarrollo. Bandas de ESPEC/SDD-06: `<0.02` débil/no predictivo, `0.02-0.10` bajo, `0.10-0.30` medio, `0.30-0.50` fuerte, `>0.50` sospechoso por posible leakage/proxy dominante.
- **Métricas univariadas de discriminación.** Para cada feature WoE, se calcula `AUC` usando como score de riesgo `-WoE` (porque la convención del proyecto es `WoE = ln(%Goods/%Bads)`: mayor riesgo implica WoE menor), `Gini = 2·AUC - 1`, y `KS = max_t |TPR(t) - FPR(t)|`. Estas métricas se reportan y pueden activar filtros configurables, pero por defecto no reemplazan el corte IV.
- **PSI / CSI.** La ESPEC define `PSI = Σ(%a - %e)·ln(%a/%e)` con bandas `<0.1` estable, `0.1-0.25` revisar, `>0.25` redesarrollar. En selección se usa como **Characteristic Stability Index** por variable/bin: compara la distribución de una característica en HO/OOT/período (`actual`) contra Desarrollo (`expected`). Default: `report_only` para no usar HO/OOT como criterio de inclusión.
- **Correlación entre features WoE.** Se calcula sobre Desarrollo, con método `pearson`/`spearman`/`kendall`. Si `|ρ|` supera el umbral (ESPEC: 0.7-0.8), se conserva la variable de mayor prioridad predictiva (IV, luego AUC/KS, luego nombre para desempate determinista).
- **VIF (Variance Inflation Factor).** Mide multicolinealidad de una feature respecto del resto: `VIF_j = 1 / (1 - R_j^2)`, donde `R_j^2` proviene de la regresión auxiliar de la feature `j` contra las demás. ESPEC fija el rango de alerta `VIF > 5-10`; el default propuesto es `5.0` por prudencia regulatoria.
- **Clustering de variables.** Opción de agrupar variables por componentes conectados del grafo de correlación (`|ρ| > threshold`) y elegir un representante por grupo. En v1 queda desactivado por defecto porque el pruning greedy de correlación ya resuelve el caso común sin introducir otra dependencia.
- **Anti-leakage.** Todo filtro que **decide** inclusión se ajusta exclusivamente con `partition == "desarrollo"` y target no nulo. HO/OOT/período solo alimentan columnas de diagnóstico del `selection_table`.

> **Fórmulas / parámetros normativos:** `selection` no contiene parámetros CMF ni IFRS 9. Sus umbrales vienen de ESPECIFICACIONES §5.2 y SDD-06; `normativa_cmf_parametros.md` aplica a motores de provisión, no a filtros de scorecard.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/selection/config.py
class SelectionConfig(NikodymBaseConfig): ...
class CorrelationSelectionConfig(NikodymBaseConfig): ...
class VifSelectionConfig(NikodymBaseConfig): ...
class StabilitySelectionConfig(NikodymBaseConfig): ...

# nikodym/selection/exceptions.py
class SelectionError(NikodymError): ...
class SelectionFitError(SelectionError): ...
class SelectionTransformError(SelectionError): ...

# nikodym/selection/selector.py
class FeatureSelector(TransformerMixin, BaseEstimator, NikodymTransformer):
    """Selector sklearn-like de columnas WoE para scorecard."""
    config_cls: ClassVar[type[SelectionConfig]] = SelectionConfig
    def __init__(
        self,
        *,
        feature_columns: tuple[str, ...] | Literal["*"] = "*",
        exclude_columns: tuple[str, ...] = (),
        force_include: tuple[str, ...] = (),
        force_exclude: tuple[str, ...] = (),
        min_iv: float = 0.02,
        max_iv: float | None = 0.50,
        max_iv_action: Literal["flag", "exclude"] = "flag",
        min_auc: float | None = None,
        min_ks: float | None = None,
        correlation_method: Literal["pearson", "spearman", "kendall"] = "pearson",
        correlation_threshold: float = 0.75,
        vif_threshold: float = 5.0,
        clustering_method: Literal["none", "connected_components"] = "none",
        keep_structural_columns: bool = True,
    ) -> None: ...
    @classmethod
    def from_config(cls, cfg: SelectionConfig) -> "FeatureSelector": ...
    def fit(
        self,
        woe_frame: "pandas.DataFrame",
        *,
        target_col: str,
        partition_col: str,
        binning_summary: "pandas.DataFrame",
        woe_column_map: dict[str, str],
        audit: "AuditSink | None" = None,
    ) -> "Self": ...
    def transform(self, woe_frame: "pandas.DataFrame") -> "pandas.DataFrame": ...
    def fit_transform(self, woe_frame: "pandas.DataFrame", **kwargs) -> "pandas.DataFrame": ...
```

**Atributos fiteados de `FeatureSelector` (sufijo `_`).**
- `selected_features_`: tuple de nombres raw seleccionados.
- `selected_woe_columns_`: tuple de columnas WoE seleccionadas.
- `excluded_features_`: dict `feature -> reason_code`.
- `selection_table_`: `pandas.DataFrame` con una fila por feature candidata y decisión final.
- `correlation_matrix_`: matriz Dev de correlación de columnas WoE candidatas.
- `vif_table_`: tabla por iteración de VIF y variable eliminada.
- `stability_table_`: PSI/CSI por variable × muestra/período cuando se puede calcular.
- `decision_log_`: tuple de decisiones normalizadas para model card/report.

```python
# nikodym/selection/results.py
SelectionDecisionReason = Literal[
    "included",
    "business_exclude",
    "business_include",
    "low_iv",
    "high_iv",
    "low_auc",
    "low_ks",
    "high_correlation",
    "high_vif",
    "cluster_representative_lost",
    "constant_or_nonfinite",
    "missing_binning_artifact",
]

class VariableSelectionDecision(BaseModel):
    feature: str
    woe_column: str
    included: bool
    reason: SelectionDecisionReason
    iv: float
    iv_band: Literal["none", "weak", "medium", "strong", "suspicious"]
    auc: float | None
    gini: float | None
    ks: float | None
    max_abs_corr: float | None
    max_corr_with: str | None
    vif: float | None
    max_csi: float | None
    forced: Literal["include", "exclude"] | None = None

class SelectionResult(BaseModel):
    selected_features: tuple[str, ...]
    selected_woe_columns: tuple[str, ...]
    selected_woe_frame: "pandas.DataFrame"
    selection_table: "pandas.DataFrame"
    correlation_matrix: "pandas.DataFrame"
    vif_table: "pandas.DataFrame"
    stability_table: "pandas.DataFrame"
    decisions: tuple[VariableSelectionDecision, ...]
    model_config = ConfigDict(arbitrary_types_allowed=True)

class SelectionCardSection(BaseModel):
    n_candidates: int
    n_selected: int
    n_excluded: int
    thresholds: dict[str, float | str | None]
    excluded_by_reason: dict[str, int]
    selected_features: tuple[str, ...]
    high_iv_flags: tuple[str, ...]
    stability_flags: tuple[str, ...]
    max_abs_correlation_after_selection: float | None
    max_vif_after_selection: float | None
    dependency_versions: dict[str, str]
```

```python
# nikodym/selection/step.py
@register("standard", domain="selection")
class SelectionStep(AuditableMixin):
    name: str = "selection"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "labels"),
        ("data", "splits"),
        ("binning", "process"),
        ("binning", "summary"),
        ("binning", "tables"),
        ("binning", "woe_frame"),
        ("binning", "result"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("selection", "selected_features"),
        ("selection", "selected_woe_columns"),
        ("selection", "selected_woe_frame"),
        ("selection", "selection_table"),
        ("selection", "correlation_matrix"),
        ("selection", "vif_table"),
        ("selection", "stability_table"),
        ("selection", "result"),
        ("selection", "selection_card"),
    )
    @classmethod
    def from_config(cls, cfg: SelectionConfig) -> "SelectionStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "SelectionResult": ...
```

**Artefactos que `SelectionStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"selected_features"` | `tuple[str, ...]` | nombres raw de variables seleccionadas |
| `"selected_woe_columns"` | `tuple[str, ...]` | columnas WoE seleccionadas para SDD-08 |
| `"selected_woe_frame"` | `pandas.DataFrame` | columnas estructurales + WoE seleccionadas, mismo índice que `binning.woe_frame` |
| `"selection_table"` | `pandas.DataFrame` | decisión por variable, métricas y motivo auditable |
| `"correlation_matrix"` | `pandas.DataFrame` | matriz Dev de correlación entre candidatas |
| `"vif_table"` | `pandas.DataFrame` | VIF por iteración y variable removida |
| `"stability_table"` | `pandas.DataFrame` | PSI/CSI por variable × muestra/período (diagnóstico) |
| `"result"` | `SelectionResult` | contenedor agregado |
| `"selection_card"` | `SelectionCardSection` | resumen para model card / report |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning", "selection"])
features = study.artifacts.get("selection", "selected_features")
X = study.artifacts.get("selection", "selected_woe_frame")
tabla = study.artifacts.get("selection", "selection_table")
```

## 5. Configuración (schema Pydantic)

`SelectionConfig` es el sub-config de la sección `selection` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig` (`extra="forbid"`, `frozen=True`), campos con `title`/`description`, rangos `ge/le`, `Literal` en categóricos y metadatos `ui_*`. **No es infraestructura** (`selection ∉ INFRA_SECTIONS`): cambiar umbrales o overrides cambia el `config_hash`.

```python
# nikodym/selection/config.py
from typing import Literal
from pydantic import Field, model_validator
from nikodym.core.config import NikodymBaseConfig

class CorrelationSelectionConfig(NikodymBaseConfig):
    enabled: bool = Field(True, title="Filtrar por correlación")
    method: Literal["pearson", "spearman", "kendall"] = Field("pearson", title="Método")
    threshold: float = Field(0.75, ge=0.0, le=1.0, title="Umbral |rho|")
    clustering_method: Literal["none", "connected_components"] = Field(
        "none", title="Clustering por correlación")

class VifSelectionConfig(NikodymBaseConfig):
    enabled: bool = Field(True, title="Filtrar por VIF")
    threshold: float = Field(5.0, ge=1.0, title="Umbral VIF")
    add_intercept: bool = Field(True, title="Agregar intercepto en regresiones auxiliares")
    max_iterations: int | None = Field(None, ge=1, title="Máximo de iteraciones")

class StabilitySelectionConfig(NikodymBaseConfig):
    enabled: bool = Field(True, title="Calcular PSI/CSI por característica")
    action: Literal["report_only", "exclude"] = Field("report_only", title="Acción ante inestabilidad")
    stable_threshold: float = Field(0.10, ge=0.0, title="PSI/CSI estable hasta")
    review_threshold: float = Field(0.25, ge=0.0, title="PSI/CSI revisar hasta")
    smoothing: float = Field(1e-6, gt=0.0, title="Suavizado de proporciones")

class SelectionConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"   # == @register("standard", domain="selection")
    feature_columns: tuple[str, ...] | Literal["*"] = Field(
        "*",
        title="Variables candidatas",
        description="'*' = todas las variables seleccionadas por el proceso de binning.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 1},
    )
    exclude_columns: tuple[str, ...] = Field(default_factory=tuple, title="Exclusiones técnicas")
    force_include: tuple[str, ...] = Field(default_factory=tuple, title="Forzar inclusión")
    force_exclude: tuple[str, ...] = Field(default_factory=tuple, title="Forzar exclusión")

    min_iv: float = Field(0.02, ge=0.0, title="IV mínimo")
    max_iv: float | None = Field(0.50, ge=0.0, title="IV sospechoso")
    max_iv_action: Literal["flag", "exclude"] = Field("flag", title="Acción ante IV alto")

    compute_univariate_metrics: bool = Field(True, title="Calcular AUC/KS/Gini univariado")
    min_auc: float | None = Field(None, ge=0.5, le=1.0, title="AUC mínimo")
    min_ks: float | None = Field(None, ge=0.0, le=1.0, title="KS mínimo")
    min_gini: float | None = Field(None, ge=0.0, le=1.0, title="Gini mínimo")

    priority_order: tuple[Literal["iv", "auc", "ks", "gini", "name"], ...] = Field(
        ("iv", "auc", "ks", "name"),
        title="Orden de prioridad para desempates",
    )
    correlation: CorrelationSelectionConfig = Field(default_factory=CorrelationSelectionConfig)
    vif: VifSelectionConfig = Field(default_factory=VifSelectionConfig)
    stability: StabilitySelectionConfig = Field(default_factory=StabilitySelectionConfig)
    keep_structural_columns: bool = Field(True, title="Conservar columnas estructurales")
    fail_if_no_features: bool = Field(True, title="Fallar si no queda ninguna variable")
```

**Defaults defendibles.**
- `min_iv=0.02` usa el umbral mínimo explícito de ESPEC/SDD-06 para separar variables no predictivas.
- `max_iv=0.50` con `max_iv_action="flag"` refleja la banda sospechosa de ESPEC/SDD-06 sin excluir automáticamente una señal que puede ser legítima y requiere revisión.
- `correlation.threshold=0.75` toma el punto medio del rango ESPEC `0.7-0.8`.
- `vif.threshold=5.0` toma el extremo conservador del rango ESPEC `5-10`.
- `stability.action="report_only"` evita leakage: HO/OOT no decide inclusión. Si Cami quiere usar PSI/CSI como filtro activo, debe ratificarlo explícitamente.
- `priority_order=("iv","auc","ks","name")` conserva la variable de mayor poder univariado y desempata de forma determinista.

**Hook diferido en `core.config.schema`.** F1 debe extender el patrón ya usado por `data`/`eda`/`binning`:
- declarar `_SELECTION_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir `selection` como campo `Any` en runtime y `SelectionConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("selection", mode="before")` que, si `_SELECTION_CONFIG_CLS` está poblado, valida con `SelectionConfig.model_validate(valor)`, y si no lo está exige JSON canónico determinista;
- `nikodym.selection.__init__` asigna `_schema._SELECTION_CONFIG_CLS = SelectionConfig` al importarse y luego importa `nikodym.selection.step` para ejecutar `@register`.

## 6. Contratos de datos (I/O)

**Input vía `Study`.**
- `("binning", "woe_frame")`: `pandas.DataFrame` con columnas estructurales (`target`, `label_status`, `partition`, `ttd`) y columnas WoE finitas.
- `("binning", "process")`: transformer fiteado, usado para recuperar o reconstruir asignación a bins cuando PSI/CSI por característica requiere etiquetas de bin estables.
- `("binning", "summary")`: `pandas.DataFrame` con `name`, `selected`, `iv`, `gini`, `quality_score` y flags de binning.
- `("binning", "tables")`: tablas por variable con bins, conteos, WoE e IV; fuente para CSI/PSI por característica.
- `("binning", "result")`: `BinningResult`, especialmente `woe_column_map` y `skipped_variables`.
- `("data", "labels")`: `LabeledFrame`, fuente de `target_col`.
- `("data", "splits")`: `PartitionResult`, fuente de `partition_col` y rol `ttd`.

**Poblaciones.**
- **Fit de selección:** filas con `partition == "desarrollo"` y `target ∈ {0,1}`.
- **Transform/publicación:** filas con `partition ∈ {"desarrollo", "holdout", "oot"}` del `woe_frame`, filtradas a columnas seleccionadas. `fuera_de_modelo` queda fuera del frame modelable salvo una extensión futura explícita.
- **Diagnósticos HO/OOT/período:** pueden calcularse después de fijar la selección, pero no alteran `selected_features`.

**Output `selected_woe_frame`.** `pandas.DataFrame` con el mismo índice y orden de filas que `binning.woe_frame` para filas modelables:
- columnas estructurales mínimas si `keep_structural_columns=True`;
- solo las columnas WoE seleccionadas;
- ninguna columna raw de feature.

**Output `selection_table`.** Una fila por feature candidata con, como mínimo:

| columna | significado |
|---|---|
| `feature` | nombre raw de la variable |
| `woe_column` | columna WoE asociada |
| `included` | decisión final |
| `reason` | motivo normalizado de inclusión/exclusión |
| `iv`, `iv_band` | IV de SDD-06 y banda |
| `auc`, `gini`, `ks` | métricas univariadas en Desarrollo |
| `max_abs_corr`, `max_corr_with` | peor correlación contra una feature retenida |
| `vif` | VIF final o VIF al momento de exclusión |
| `max_csi` | peor CSI/PSI diagnóstico reportado |
| `forced` | `include`/`exclude` si hubo override de negocio |

**Invariantes.**
- *No leakage:* ninguna decisión de inclusión usa Holdout/OOT.
- *No mutación:* `selection` nunca escribe bajo `"data"` ni `"binning"` y no modifica objetos in-place.
- *Trazabilidad:* toda feature candidata aparece exactamente una vez en `selection_table`.
- *Consistencia:* `selected_features` y `selected_woe_columns` tienen la misma longitud y orden; cada feature tiene mapping en `woe_column_map`.
- *Orden estable:* el orden final sigue `priority_order` y desempate lexicográfico por `feature`, para reproducibilidad.
- *Finitud:* no se publican columnas WoE no finitas ni VIF no finito como si fueran aceptables; `inf` se trata como señal de colinealidad perfecta y gatilla exclusión/error según la política de overrides.

## 7. Algoritmos y flujo

**`SelectionStep.execute(study, rng)` — secuencia canónica.**
1. **Leer artefactos.** Validar presencia y tipos de `woe_frame`, `summary`, `tables`, `result`, `labels`, `splits`.
2. **Resolver candidatos.** Desde `BinningResult.woe_column_map` y `binning.summary`, tomar variables con binning exitoso. Aplicar `feature_columns`, `exclude_columns`, `force_include`, `force_exclude`. Cada identificador puede ser el nombre raw o su alias WoE; ambos se canonicalizan al nombre raw antes de aplicar los overrides. `woe_column_map` debe ser inyectivo entre las features publicables y alcanzables por `feature_columns` o por cualquier override/exclusión: un alias WoE compartido se rechaza con todas sus raws ordenadas, sin precedencia por inserción; las features no publicables y los aliases completamente fuera de ese alcance no participan en la validación. Si un identificador coincide con una feature raw y con el alias WoE de otra feature, se rechaza como ambiguo; el match doble solo es válido cuando ambas rutas convergen a la misma feature. Variables inexistentes en overrides levantan `SelectionFitError`.
3. **Partición Desarrollo.** Construir `dev = woe_frame[partition == "desarrollo" & target.notna()]`. Verificar ambas clases y que todas las columnas WoE candidatas sean finitas.
4. **Métricas univariadas.** Para cada candidata:
   - traer `iv` de `binning.summary` (no recalcular);
   - calcular `AUC`, `Gini`, `KS` sobre `risk_score = -WoE`;
   - asignar `iv_band` con las bandas ESPEC/SDD-06.
5. **Filtros hard/negocio iniciales.**
   - `force_exclude` excluye siempre y registra `business_exclude`;
   - columnas constantes/no finitas se excluyen con `constant_or_nonfinite`;
   - `min_iv` excluye salvo `force_include`;
   - `max_iv` flaggea o excluye según `max_iv_action`;
   - `min_auc`/`min_ks`/`min_gini`, si no son `None`, excluyen salvo `force_include`.
6. **Ranking determinista.** Ordenar candidatas sobrevivientes por `priority_order` descendente (`iv`, `auc`, `ks`, `gini`) y luego `feature` ascendente.
7. **Correlación / clustering.**
   - Calcular matriz `corr = dev[woe_columns].corr(method=cfg.correlation.method)`.
   - Si `clustering_method="connected_components"`, construir componentes por aristas `|ρ| > threshold` y retener el representante mejor rankeado por componente.
   - Si `clustering_method="none"`, aplicar pruning greedy: iterar el ranking; incluir una candidata si no supera `threshold` contra ninguna ya incluida; si supera, excluir la candidata de menor prioridad y registrar par/valor.
8. **VIF iterativo.**
   - Construir matriz Dev con features retenidas; agregar intercepto si `add_intercept=True`.
   - Calcular VIF por feature con `statsmodels.stats.outliers_influence.variance_inflation_factor(exog, exog_idx)`.
   - Si `max(VIF) > threshold`, eliminar la variable no forzada con mayor VIF; desempatar por menor prioridad. Repetir hasta cumplir umbral o llegar a `max_iterations`.
   - Si solo quedan variables `force_include` y VIF sigue sobre umbral, levantar `SelectionFitError` con conflicto auditable, salvo que Cami ratifique una política de override más laxa.
9. **Estabilidad diagnóstica.** Calcular PSI/CSI por variable retenida y/o excluida usando Desarrollo como expected y HO/OOT/período como actual. Default `report_only`: registrar flags, no cambiar selección.
10. **Publicar artefactos.** Construir `SelectionResult` y `SelectionCardSection`; escribir las nueve claves `provides` bajo `"selection"`.

**Criterios de desempate.** Si dos variables empatan en IV/AUC/KS/Gini dentro de tolerancia numérica, gana `feature` lexicográficamente. No se usa orden de columnas de entrada como desempate silencioso.

**Uso de VIF de statsmodels.** La API verificada localmente en `uv.lock` es `variance_inflation_factor(exog, exog_idx)`. No agrega constante automáticamente. Nikodym debe agregar un intercepto explícito para las regresiones auxiliares y reportar VIF solo de features, no del intercepto. En colinealidad perfecta emite `RuntimeWarning: divide by zero encountered in scalar divide` y devuelve `inf`; la implementación debe capturar localmente ese warning específico para mapearlo a `inf` y luego excluir/error, sin relajar `filterwarnings=error` global.

**Alternativas descartadas.**
- *Seleccionar por stepwise aquí:* descartado; invade SDD-08 y mezclaría filtros pre-modelo con ajuste de coeficientes.
- *Usar HO/OOT para excluir variables inestables:* descartado por default; introduce leakage. Se deja `stability.action="exclude"` como decisión explícita para Cami/usuario.
- *Recalcular bins o IV desde datos raw:* descartado; duplica SDD-06 y rompe trazabilidad.
- *Clustering jerárquico con scipy como default:* descartado en v1; componentes conectados sobre la matriz de correlación cubren el caso regulatorio sin dependencia nueva.
- *Quitar variables correlacionadas por orden de columnas:* descartado; el orden de entrada no es una razón auditable.

**Complejidad / rendimiento.** Correlación O(n·p²) y VIF iterativo O(k·p³) en el peor caso (p features, n filas Dev, k iteraciones), aceptable para scorecards de comportamiento donde p ya viene reducido por binning. Configurar `feature_columns` permite acotar p.

## 8. Casos borde y manejo de errores

- **Faltan artefactos de `binning`/`data`:** `ArtifactNotFoundError` por CT-1 antes de entrar a `execute`.
- **`woe_column_map` no contiene una candidata:** `SelectionFitError` con la variable y el mapping disponible.
- **Desarrollo sin ambas clases:** `SelectionFitError`; no hay AUC/KS/IV defendible.
- **Todas las variables caen por filtros:** con `fail_if_no_features=True`, `SelectionFitError` y card parcial con razones; con `False`, se publica selección vacía solo para diagnóstico.
- **Variable constante en Desarrollo:** exclusión técnica `constant_or_nonfinite`.
- **Valores `NaN`, `inf`, `-inf` en columnas WoE:** `SelectionFitError` antes de calcular correlación/VIF, salvo que la variable se excluya técnicamente y no participe en el resto.
- **Correlación perfecta:** se elimina la de menor prioridad; si ambas están `force_include`, se registra conflicto y se deriva a VIF/error.
- **VIF infinito o warning de divide-by-zero:** se interpreta como colinealidad perfecta; se elimina la variable no forzada de peor prioridad.
- **`force_include` de variable con IV bajo:** se permite, pero se registra `log_decision(regla="business_include", umbral=min_iv, valor=iv, accion="incluir")`.
- **`force_include` de variable inexistente/no binneada/no finita:** error ruidoso; un override de negocio no puede crear una feature válida.
- **`force_include` y `force_exclude` sobre la misma variable:** `ConfigError` si el identificador declarado coincide; si uno usa el nombre raw y otro su alias WoE, `SelectionFitError` después de canonicalizar `woe_column_map`.
- **Kendall/Spearman con demasiados empates:** se calcula igual; si pandas devuelve `NaN`, se trata como correlación no evaluable y se registra flag. No se usa para incluir por encima de umbral.
- **Muestra pequeña para VIF (`n_dev <= p + 1`):** `SelectionFitError` si VIF está habilitado; el usuario debe reducir candidatos o desactivar VIF explícitamente y auditarlo.
- **PSI/CSI con proporciones cero:** aplicar suavizado `smoothing` antes de `ln(actual/expected)`; la tabla marca que se usó suavizado.

Toda excepción del módulo desciende de `NikodymError`; los mensajes son en español e incluyen variable, regla, umbral/config y valor observado.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno en v1. El `rng` recibido por `SelectionStep.execute` no se consume.
- **Determinismo esperado.** `(data_hash + config_hash + root_seed + uv.lock) → selected_features y tablas idénticas`. El orden de candidatos, desempates y outputs es canónico.
- **Normalización numérica.** Los outputs tabulares deben normalizar `-0.0 → 0.0` para golden values y usar orden fijo de columnas/filas. No se hashea aquí el dato, pero los tests deben evitar diferencias espurias de representación.
- **Audit trail (`log_decision`).** Registrar, como mínimo:
  - exclusión manual (`business_exclude`) e inclusión manual que sobrepasa filtros;
  - exclusión por `min_iv`, `min_auc`, `min_ks`, `min_gini`;
  - flag/exclusión por `max_iv`;
  - exclusión por correlación, con feature retenida, método, umbral y `ρ` observado;
  - exclusión por VIF, con VIF observado, umbral e iteración;
  - conflicto de variables forzadas;
  - PSI/CSI sobre bandas de estabilidad cuando `stability.enabled`.
- **Model card / report.** `SelectionCardSection` debe permitir al auditor reconstruir cuántas variables entraron, por qué se excluyó cada una, qué umbrales estaban activos y qué señales quedaron bajo revisión.
- **Lineage.** `selection` no completa `data_hash` ni `config_hash`; su contribución al lineage es su config computacional y sus decisiones de audit trail.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymTransformer`, `MissingDependencyError`, `NikodymError`, `Registry`.
- SDD-02 (`data`): `labels`, `splits`, partición Desarrollo/HO/OOT, target binario.
- SDD-05 (convenciones): config Pydantic, hook diferido, `config_hash`, naming y UI metadata.
- SDD-06 (`binning`): `summary`, `tables`, `woe_frame`, `result`, `BinningResult.woe_column_map`.

**Aguas abajo.**
- SDD-08 (`model`) consume `selected_woe_frame`, `selected_features` y `selected_woe_columns`.
- SDD-09 (`scorecard`) consume features finales junto con coeficientes del modelo.
- SDD-11 (`performance`/`stability`) consume la selección para reportar estabilidad/rendimiento del score.
- SDD-26 (`report`) consume `selection_table`, `selection_card`, matrices y flags.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | 2.3.3 en `uv.lock` (`pyproject`: `>=2.0`) | BSD-3 ✅ | correlación, DataFrame I/O, tablas | base |
| numpy | 2.4.6 en `uv.lock` (`pyproject`: `>=1.22`) | BSD ✅ | arrays, finitud, álgebra auxiliar | base |
| scikit-learn | 1.7.2 en `uv.lock` (`pyproject`: `>=1.6`, constraint `<1.8`) | BSD-3 ✅ | `roc_auc_score`, `roc_curve`, mixins sklearn del selector | extra `[scoring]` |
| statsmodels | 0.14.6 en `uv.lock` (`pyproject`: `>=0.14`) | BSD ✅ | `variance_inflation_factor` para VIF | extra `[scoring]` |
| scipy | 1.18.0 en `uv.lock` para Python >=3.12 | BSD ✅ | transitiva/extra scoring; no requerida directamente por v1 | extra `[scoring]` |

**Núcleo liviano.** `nikodym.core` no importa `selection`, `sklearn` ni `statsmodels`. `import nikodym.selection` debe registrar `SelectionConfig` y `SelectionStep` sin arrastrar pandas/sklearn/statsmodels; `FeatureSelector`, métricas y VIF se cargan perezosamente en `execute` o por `__getattr__`. Si falta `[scoring]`, se levanta `MissingDependencyError` con mensaje `"instale nikodym[scoring]"`.

**Verificación local 2026-06-27 contra `uv.lock`.**
- `statsmodels.__version__ == "0.14.6"`; `variance_inflation_factor` firma `(exog, exog_idx)`.
- `scikit-learn.__version__ == "1.7.2"`; `roc_auc_score(y_true, y_score, *, average="macro", sample_weight=None, max_fpr=None, multi_class="raise", labels=None)`; `roc_curve(y_true, y_score, *, pos_label=None, sample_weight=None, drop_intermediate=True)`.
- `pandas.DataFrame.corr(method="pearson", min_periods=1, numeric_only=False)` soporta `pearson`/`spearman`/`kendall`.
- VIF con colinealidad perfecta devuelve `inf` y emite `RuntimeWarning`; debe tratarse localmente.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **Canónicos IV/correlación/VIF.** Dataset pequeño con IV conocido desde `binning.summary`; dos columnas perfectamente correlacionadas y una independiente. Verificar que se retiene la de mayor IV y que VIF infinito excluye la redundante.
- **AUC/KS/Gini a mano.** Caso 2×2/4 filas con `AUC=0.75`, `Gini=0.50`, `KS=0.50` usando `risk_score=-WoE`.
- **Anti-leakage.** Cambiar valores HO/OOT no cambia `selected_features`, `selection_table.reason` ni correlación/VIF; solo cambia `stability_table`.
- **Overrides de negocio.** `force_exclude` elimina siempre; `force_include` permite IV bajo con evento auditado; conflicto include/exclude levanta `ConfigError`.
- **VIF y warnings.** Caso colineal que dispara `RuntimeWarning` de statsmodels: el test debe pasar con `filterwarnings=error` porque la implementación captura localmente ese warning específico.
- **PSI/CSI.** Distribuciones de bins con proporciones conocidas: verificar fórmula `Σ(%a-%e)·ln(%a/%e)` y bandas `<0.1`, `0.1-0.25`, `>0.25` contra golden values.
- **Propiedades.** Reordenar columnas/filas no cambia selección; empates se resuelven por nombre; `selected_woe_frame` conserva índice y columnas estructurales.
- **Contrato `Step`.** `SelectionStep.requires` exige artefactos de `data` y `binning`; falta uno → `ArtifactNotFoundError`. `provides` se verifica tras ejecución.
- **No mutación.** Snapshots de `data.frame`, `binning.woe_frame` y `binning.summary` antes/después permanecen iguales.
- **Config.** Round-trip YAML de `SelectionConfig`; cambiar `min_iv`, `correlation.threshold` o `vif.threshold` cambia `config_hash`; `selection` sin importar `nikodym.selection` se mantiene como JSON canónico opaco y al importar se valida como `SelectionConfig`.
- **Import liviano.** `import nikodym.selection` no importa `sklearn`, `statsmodels` ni `pandas` salvo que ya estén cargados por otro módulo; acceder a `FeatureSelector` o ejecutar el step sí puede cargarlos.

Fixtures: pipeline `data → binning` sintético ya usado por SDD-06, más un `SelectionConfig` mínimo y otro con overrides; `InMemoryAuditSink` para decisiones.

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Leakage por estabilidad.** Si se usa HO/OOT para excluir variables, la validación queda contaminada. Mitigación: `stability.action="report_only"` por defecto y prueba anti-leakage.
- **Sobre-pruning.** Correlación + VIF pueden eliminar demasiadas variables antes del stepwise. Mitigación: umbrales configurables, tabla de razones y revisión de Cami.
- **Multicolinealidad entre variables forzadas.** Mitigación: conflicto ruidoso en vez de aceptar un diseño singular.
- **Falsa precisión en métricas univariadas.** AUC/KS/Gini pre-modelo son diagnósticos, no validación del score final. Mitigación: etiquetas claras y frontera con SDD-11.
- **Dependencias pesadas en imports.** Mitigación: reexports perezosos y `MissingDependencyError` accionable.

## Decisiones para revisión de Cami

- **D-SEL-1 — IV mínimo `0.02` y IV alto `>0.50` como flag, no exclusión.** El mínimo sí filtra; el IV alto queda para revisión por posible leakage/proxy dominante. Confirmar si `max_iv_action` debe ser `"exclude"` en entornos conservadores.
- **D-SEL-2 — Frontera con SDD-08:** stepwise Wald/LR, p-values, signos de β e IV-contribution ≤ 90 % quedan fuera de SDD-07. `selection` reporta AUC/KS/Gini univariados y, por defecto, no filtra por ellos salvo que el usuario configure mínimos.
- **D-SEL-3 — Correlación default `pearson`, umbral `0.75`.** Está dentro del rango ESPEC `0.7-0.8`. Confirmar si Cami prefiere `0.80` (menos agresivo) o `spearman` como default para WoE.
- **D-SEL-4 — VIF default `5.0`.** Es el extremo conservador del rango ESPEC `5-10`. Confirmar si el default operativo debe ser `10.0` para evitar sobre-pruning antes del stepwise.
- **D-SEL-5 — Clustering de variables desactivado por defecto.** Se especifica `connected_components` como opción sin dependencia nueva, pero el pruning por correlación cubre v1. Confirmar si el reporte debe mostrar grupos aunque no se usen para filtrar.
- **D-SEL-6 — PSI/CSI en `selection` es diagnóstico `report_only`.** Esto preserva anti-leakage. Confirmar si algún flujo institucional exige excluir por inestabilidad pre-modelo y cómo separar esa decisión de la validación HO/OOT.
- **D-SEL-7 — Dependencias nuevas.** No se propone dependencia nueva: `statsmodels` y `scikit-learn` ya están en extra `[scoring]`. Confirmar que `selection` vive en `[scoring]` y no como dependencia base.

### Citas

- **ESPECIFICACIONES.md** §4 (principios 1 reproducibilidad, 2 auditabilidad, 8 no reinventar, 9 núcleo liviano, 10 calidad ejemplar, 11 doble verificación), §5.2 (pipeline scorecard: WoE/IV con umbrales 0.02/0.1/0.3/0.5; PSI fórmula y bandas; correlación Pearson/Spearman/Kendall `|ρ|>0.7-0.8`; VIF `>5-10`; stepwise Wald/LR con statsmodels separado), §6.3 (árbol: `selection/` = PSI/CSI, IV, ROC/KS/Gini, correlación, filtros, negocio), §7 (statsmodels/scikit-learn BSD), §8 (tablas IV/PSI/ROC/KS por variable), §11 (F1 scorecard comportamiento).
- **ROADMAP.md** F1 (selección: PSI/CSI, IV, ROC/KS/Gini por muestra y período; correlación; descarte por negocio; stepwise como punto separado).
- **SDD-01 (`core`)** §4 (`Step`, `ArtifactKey`, `requires`/`provides`, `AuditableMixin.log_decision`, `NikodymTransformer`, `MissingDependencyError`), §6 (ArtifactStore namespaced), §7 (validación CT-1), §9 (reproducibilidad y audit trail).
- **SDD-02 (`data`)** §1/§3/§6/§12 (particiones Desarrollo/HO/OOT; `data` no selecciona variables; fit solo en Desarrollo; frontera transversal scorecard).
- **SDD-05 (convenciones+config)** §4 (patrón sklearn-like y bases propias; excepciones; naming), §5.1 (sección `selection` reservada en `NikodymConfig`), §5.5 (`config_hash`, `INFRA_SECTIONS`, UI metadata), §6 (DataFrame con columnas nombradas).
- **SDD-06 (`binning`)** §1/§3/§4/§6/§12 (WoE/IV final, artefactos `process`/`tables`/`summary`/`woe_frame`/`result`/`binning_card`, IV se reporta pero no filtra, anti-leakage Dev).
- **SDD-27 (`eda`)** §1/§3/§12 (IV descriptivo pre-binning es opt-in y distinto del IV final de SDD-06; EDA no selecciona variables).
- **docs/normativa_cmf_parametros.md** Advertencias y §7 (parámetros CMF pertenecen al motor de provisiones; no hay umbrales CMF aplicables a selección de variables de scorecard).
- **Verificación local 2026-06-27 contra `uv.lock`:** `statsmodels 0.14.6`, `scikit-learn 1.7.2`, `scipy 1.18.0`, `pandas 2.3.3`, `numpy 2.4.6`; `variance_inflation_factor(exog, exog_idx)`; `roc_auc_score` y `roc_curve` con firmas indicadas en §10; VIF perfecto devuelve `inf` con `RuntimeWarning` localizado.
