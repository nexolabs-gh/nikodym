# SDD-08 — `model` (regresión logística PD + stepwise sobre variables WoE)

| Campo | Valor |
|---|---|
| **SDD** | 08 |
| **Módulo** | `nikodym.model` |
| **Fase** | F1 |
| **Tanda de producción** | T2 (Scoring) |
| **Estado** | 🟡 Borrador |
| **Depende de** | SDD-01 (`core`), SDD-02 (`data`), SDD-05 (convenciones + config), SDD-06 (`binning`), SDD-07 (`selection`) |
| **Lo consumen** | SDD-09 (`scorecard`), SDD-10 (`calibration`), SDD-11 (`performance` + `stability`), SDD-12 (`ml`, benchmark), SDD-18 (`survival`, reuso conceptual, no contrato de datos), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (redacción SDD-08 para T2) / 2026-06-27 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `model` ajusta la regresión logística de PD sobre las variables WoE seleccionadas por `selection`, decide la especificación final mediante stepwise auditable y publica coeficientes, inferencia estadística y PD cruda no calibrada para las etapas aguas abajo.

**Responsabilidad única (qué SÍ hace).**
- Ajusta un modelo logístico binario `target=1` malo/default, `target=0` bueno/no-default, usando `statsmodels` (`Logit` por defecto; `GLM(..., family=Binomial())` cuando la configuración lo requiera).
- Ejecuta **stepwise** forward/backward/bidireccional sobre el conjunto candidato que ya publica SDD-07, con criterio configurable por p-value Wald, LR-test o ambos.
- Estima y publica coeficientes `β`, errores estándar, estadísticos Wald/z, p-values, intervalos de confianza, log-likelihood, AIC/BIC y pseudo-`R²` de McFadden.
- Valida la coherencia de signos de `β` con la convención WoE de SDD-06 (`WoE = ln(%Goods/%Bads)`): para `target=1` malo, el signo esperado del coeficiente de una columna WoE es **negativo**.
- Aplica el límite de **IV-contribution** sobre el IV ya publicado por `binning.summary`: por defecto ninguna variable final puede explicar más de `90%` del IV total de las variables finales.
- Respeta anti-leakage: ajusta y decide **solo con Desarrollo**; aplica/predice PD cruda en Desarrollo/Holdout/OOT sin re-ajustar.
- Publica artefactos namespaced bajo `"model"`: estimador fiteado, features finales, tabla de coeficientes, traza stepwise, diagnósticos in-sample de Desarrollo, PD cruda, `model_card` y resultado agregado.
- Aporta el sub-config **`ModelConfig`** (sección `model` de `NikodymConfig`), computacional y por tanto incluido en el `config_hash`.
- Registra con `log_decision` cada entrada/salida del stepwise y cada flag/exclusión por signo, p-value o IV-contribution.

**Frontera dura de responsabilidad (qué NO hace, y quién lo hace).**
- **No hace binning ni WoE.** SDD-06 aprende bins, calcula WoE/IV y publica `binning.summary`; `model` los consume.
- **No selecciona variables pre-modelo por IV/correlación/VIF/negocio.** SDD-07 publica el conjunto candidato limpio. `model` solo hace stepwise e inferencia dentro de la logística.
- **No recalcula IV ni WoE.** El IV-contribution usa exclusivamente `binning.summary.iv` para las variables finales; cualquier IV faltante es error de contrato, no motivo para recomputar.
- **No traduce coeficientes a puntos, PDO, Factor ni Offset.** Eso es SDD-09 (`scorecard`).
- **No calibra PD a tendencia central ni PIT/TTC.** Eso es SDD-10 (`calibration`). La salida `raw_pd_frame` es PD logística cruda, no calibrada.
- **No hace evaluación formal multi-partición de performance/estabilidad.** SDD-11 calcula métricas formales por Desarrollo/HO/OOT y estabilidad. `model` puede reportar bondad de ajuste **in-sample en Desarrollo** para diagnosticar el ajuste estadístico; no sustituye validación.
- **No aplica matrices CMF ni IFRS 9.** La logística produce PD de scorecard; provisiones CMF/IFRS 9 viven en SDD-15/16/17.
- **No muta artefactos aguas arriba.** Lee `selection`, `binning` y `data`; publica copias defensivas bajo `"model"`.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Scoring (F1/T2). Corre después de `selection` y antes de `scorecard`, `calibration`, `performance` y `report`.
- **Quién lo invoca:** `Study.run()` como sección `model` de `NikodymConfig` (orden canónico: `data → eda → binning → selection → model → scorecard → calibration → performance → report`). También puede usarse standalone como estimador sklearn-like en notebooks/tests.
- **A quién invoca:** `core` (`Step`, `ArtifactStore`, `AuditableMixin`, `NikodymClassifier`, excepciones), artefactos de `data`/`binning`/`selection`, y dependencias del extra `[scoring]` con import perezoso.

```
data ─► binning ─► selection ─► model ─► scorecard ─► calibration ─► performance/report
         WoE/IV      candidatos      β, p-values      puntos          PD calibrada
                     WoE filtrado    PD cruda
```

**Interacción con `Study` y config declarativo.** `ModelStep` es un `Step` nativo registrado con `@register("standard", domain="model")`. Declara `requires`/`provides` (CT-1) y `execute(study, rng)`: lee los artefactos publicados por `selection`, toma metadatos de `data` y el IV de `binning.summary`, ajusta en Desarrollo, predice en particiones modelables y escribe sus artefactos bajo `"model"`. El `rng` se recibe por contrato homogéneo de `Step`; v1 no introduce muestreo y debe hacer `del rng` con comentario local.

**Integración exacta con `selection`.** `model` consume los artefactos estables:
- `("selection", "selected_woe_frame")`
- `("selection", "selected_features")`
- `("selection", "selected_woe_columns")`

El código actual de `selection` publica esos nombres y su `SelectionDecisionReason` real incluye `low_gini`, `high_stability` y `forced_conflict`, además de los motivos del SDD-07. `model` **no debe acoplarse** a un `Literal` teórico de motivos de selección: si necesita mostrar decisiones aguas arriba, las trata como strings auditables/opacos. El contrato fuerte son los nombres de artefactos y el mapping `selected_features ↔ selected_woe_columns`.

**Normativa CMF relevante para `model`.** La CMF no prescribe que la scorecard use logística, ni fija `p_value=0.05`, LR-test, Wald o signo de `β`. Sí exige, para metodologías internas de provisiones basadas en PI/PDI, que las metodologías de calificación tengan predictibilidad, discriminación constatable, robustez, validación, estabilidad, poder discriminante y backtesting; y que la documentación del componente PI detalle algoritmo de selección, criterios, pasos hasta el modelo definitivo, tests estadísticos y parámetros en construcción y validación. Por eso `model` prioriza inferencia statsmodels, trazabilidad stepwise y model card; los umbrales concretos son decisiones Nikodym/config, no parámetros CMF hardcodeados.

## 3. Conceptos y fundamentos

- **PD logística.** Para una observación `i` con variables WoE finales `x_ij`, el modelo estima:
  `logit(PD_i) = ln(PD_i / (1 - PD_i)) = β0 + Σ_j β_j · x_ij`  
  `PD_i = 1 / (1 + exp(-(β0 + Σ_j β_j · x_ij)))`.
- **Target.** SDD-02 fija `target=1` como malo/default y `target=0` como bueno/no-default. Las filas `target=<NA>` o `partition="fuera_de_modelo"` no participan en ajuste ni en predicción modelable.
- **Convención WoE.** SDD-06 fija `WoE_b = ln(%Goods_b / %Bads_b)`. Un bin más riesgoso tiene menor WoE. Dado que la logística modela la probabilidad de `target=1`, un incremento de WoE debe reducir la PD; por tanto el signo esperado de `β_j` es **negativo**. Esta es una regla de dirección económica y de consistencia con ESPEC §5.2.
- **Wald p-value.** Para cada coeficiente, `z_j = β_j / SE(β_j)` y el p-value contrasta `H0: β_j = 0`. En `statsmodels 0.14.6`, `Logit.fit(...)` publica `params`, `bse`, `pvalues` y `tvalues` en el `BinaryResultsWrapper`; se usan esos valores, no una fórmula casera.
- **LR-test (Likelihood Ratio).** Para comparar un modelo reducido contra uno completo anidado: `LR = 2 · (LL_full - LL_reduced)`, con `df = k_full - k_reduced`; `p = scipy.stats.chi2.sf(LR, df)`. `statsmodels` publica `llf`; para el test global de Logit publica además `llr` y `llr_pvalue`.
- **Pseudo-`R²` de McFadden.** `R²_McFadden = 1 - LL_full / LL_null`. Para `Logit`, `statsmodels` expone `prsquared`; para `GLM Binomial` Nikodym debe calcular el mismo indicador de forma explícita desde `llf`/`llnull` o usar `pseudo_rsquared(kind="mcf")` si la API lo soporta.
- **Stepwise.** Procedimiento determinista para agregar y/o remover variables candidatas según criterio estadístico configurado. Es parte de `model`, no de `selection` (frontera D-SEL-2 de SDD-07).
- **IV-contribution.** Para el conjunto final `F`, `iv_contribution_j = IV_j / Σ_{k∈F} IV_k`, donde `IV_j` viene de `binning.summary`. Si `Σ IV = 0`, no hay base estadística para usar este guard y se levanta `ModelFitError` salvo política `flag`.
- **Anti-leakage.** Todo lo que decide `β`, stepwise, signos, p-values e IV-contribution ve solo Desarrollo. Holdout/OOT se puntúan con parámetros fijos para downstream, no influyen en el modelo.

> **Fórmulas / parámetros normativos:** las fórmulas de WoE/IV y scorecard vienen de ESPECIFICACIONES §5.2 y SDD-06. La CMF (CNC Capítulo B-1, Anexos 1 y 2) exige documentación, validación y robustez para metodologías internas de PI, pero no fija umbrales específicos de p-value, signo o stepwise para esta logística. Las matrices PI/PDI/PE CMF de `normativa_cmf_parametros.md` son de provisiones, no de ajuste de scorecard.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/model/config.py
class StepwiseConfig(NikodymBaseConfig): ...
class SignPolicyConfig(NikodymBaseConfig): ...
class IvContributionConfig(NikodymBaseConfig): ...
class ModelConfig(NikodymBaseConfig): ...

# nikodym/model/exceptions.py
class ModelError(NikodymError): ...
class ModelFitError(ModelError): ...
class ModelTransformError(ModelError): ...

# nikodym/model/estimator.py
class LogisticPDModel(ClassifierMixin, BaseEstimator, NikodymClassifier):
    """Modelo logístico PD sobre columnas WoE seleccionadas."""
    config_cls: ClassVar[type[ModelConfig]] = ModelConfig
    def __init__(
        self,
        *,
        engine: Literal["logit", "glm_binomial"] = "logit",
        fit_intercept: bool = True,
        stepwise_direction: Literal["none", "forward", "backward", "bidirectional"] = "bidirectional",
        stepwise_criterion: Literal["wald_pvalue", "lr_test", "both"] = "wald_pvalue",
        entry_p_value: float = 0.05,
        exit_p_value: float = 0.05,
        max_iter: int = 100,
        optimizer: str = "newton",
        fit_maxiter: int = 100,
        tol: float = 1e-8,
        expected_beta_sign: Literal["negative"] = "negative",
        sign_policy: Literal["exclude", "flag", "fail"] = "exclude",
        iv_contribution_threshold: float = 0.90,
        iv_contribution_policy: Literal["exclude", "flag", "fail"] = "exclude",
        force_include: tuple[str, ...] = (),
        force_exclude: tuple[str, ...] = (),
        alpha: float = 0.05,
    ) -> None: ...
    @classmethod
    def from_config(cls, cfg: ModelConfig) -> "LogisticPDModel": ...
    def fit(
        self,
        X: "pandas.DataFrame",
        y: "pandas.Series",
        *,
        feature_names: tuple[str, ...],
        woe_columns: tuple[str, ...],
        iv_by_feature: Mapping[str, float],
        audit: "AuditSink | None" = None,
        sample_weight: "pandas.Series | None" = None,
    ) -> "Self": ...
    def predict_proba(self, X: "pandas.DataFrame") -> "numpy.ndarray": ...
    def predict_pd(self, X: "pandas.DataFrame") -> "pandas.Series": ...
    def decision_function(self, X: "pandas.DataFrame") -> "pandas.Series": ...
```

**Atributos fiteados de `LogisticPDModel` (sufijo `_`).**
- `result_`: wrapper de resultado statsmodels (`BinaryResultsWrapper` o `GLMResultsWrapper`).
- `engine_`: engine usado efectivamente.
- `feature_names_in_`: tuple de features raw candidatas recibidas desde `selection`.
- `woe_columns_in_`: tuple de columnas WoE candidatas recibidas desde `selection`.
- `final_features_`: tuple de features raw que quedaron en el modelo final.
- `final_woe_columns_`: tuple de columnas WoE finales, mismo orden que `final_features_`.
- `params_`: `pandas.Series` con `const` + coeficientes finales.
- `coef_`: `numpy.ndarray` shape `(1, n_features)` para compatibilidad sklearn.
- `intercept_`: `numpy.ndarray` shape `(1,)`.
- `bse_`, `pvalues_`, `wald_z_`: `pandas.Series` alineadas con `params_`.
- `conf_int_`: `pandas.DataFrame` con `lower`, `upper` para `alpha`.
- `fit_statistics_`: `ModelFitStatistics` con log-likelihood, pseudo-R2, AIC/BIC, nobs, convergencia.
- `coefficient_table_`: `pandas.DataFrame` lista para auditor/reporte.
- `stepwise_trace_`: tuple de `StepwiseDecision`.
- `iv_contribution_`: `pandas.DataFrame` con IV consumido de `binning.summary` y contribución por feature.
- `dependency_versions_`: dict de versiones de `statsmodels`, `scikit-learn`, `scipy`, `pandas`, `numpy`.

```python
# nikodym/model/results.py
StepwiseAction = Literal["enter", "remove", "keep", "flag", "exclude", "fail"]
StepwiseCriterion = Literal["wald_pvalue", "lr_test", "both", "sign", "iv_contribution"]

class StepwiseDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    iteration: int
    feature: str
    woe_column: str
    action: StepwiseAction
    criterion: StepwiseCriterion
    p_value: float | None
    lr_stat: float | None
    beta: float | None
    threshold: float | None
    detail: str

class CoefficientRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    feature: str | Literal["intercept"]
    woe_column: str | Literal["const"]
    beta: float
    standard_error: float | None
    wald_z: float | None
    p_value: float | None
    conf_low: float | None
    conf_high: float | None
    expected_sign: Literal["negative", "none"]
    sign_ok: bool | None
    iv: float | None
    iv_contribution: float | None

class ModelFitStatistics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    n_obs_dev: int
    n_events_dev: int
    n_nonevents_dev: int
    log_likelihood: float
    null_log_likelihood: float
    pseudo_r2_mcfadden: float
    aic: float
    bic: float
    llr: float | None
    llr_p_value: float | None
    converged: bool
    optimizer: str
    n_iterations: int | None

class ModelCardSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    engine: Literal["logit", "glm_binomial"]
    n_candidates: int
    n_final_features: int
    final_features: tuple[str, ...]
    thresholds: dict[str, float | str | None]
    sign_flags: tuple[str, ...]
    iv_contribution_flags: tuple[str, ...]
    fit_statistics: ModelFitStatistics
    dependency_versions: dict[str, str]
    metric_sections: dict[str, Any] = {}  # CT-2: puerta aditiva; vacío en scoring v1.

class ModelResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    estimator: LogisticPDModel
    final_features: tuple[str, ...]
    final_woe_columns: tuple[str, ...]
    coefficients: "pandas.DataFrame"
    stepwise_trace: tuple[StepwiseDecision, ...]
    fit_statistics: ModelFitStatistics
    raw_pd_frame: "pandas.DataFrame"
    model_card: ModelCardSection
```

```python
# nikodym/model/step.py
@register("standard", domain="model")
class ModelStep(AuditableMixin):
    name: str = "model"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "labels"),
        ("data", "splits"),
        ("binning", "summary"),
        ("selection", "selected_features"),
        ("selection", "selected_woe_columns"),
        ("selection", "selected_woe_frame"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("model", "estimator"),
        ("model", "final_features"),
        ("model", "final_woe_columns"),
        ("model", "coefficients"),
        ("model", "stepwise_trace"),
        ("model", "fit_statistics"),
        ("model", "raw_pd_frame"),
        ("model", "result"),
        ("model", "model_card"),
    )
    @classmethod
    def from_config(cls, cfg: ModelConfig) -> "ModelStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "ModelResult": ...
```

**Artefactos que `ModelStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"estimator"` | `LogisticPDModel` | estimador fiteado, serializable |
| `"final_features"` | `tuple[str, ...]` | features raw que quedaron tras stepwise/signos/IV-contribution |
| `"final_woe_columns"` | `tuple[str, ...]` | columnas WoE finales para scorecard/calibración |
| `"coefficients"` | `pandas.DataFrame` | `β`, SE, Wald/z, p-values, IC, signo, IV y contribución |
| `"stepwise_trace"` | `tuple[StepwiseDecision, ...]` | decisiones de entrada/salida/flags |
| `"fit_statistics"` | `ModelFitStatistics` | bondad de ajuste in-sample en Desarrollo |
| `"raw_pd_frame"` | `pandas.DataFrame` | índice original + `partition` + `target` + `linear_predictor` + `pd_raw` |
| `"result"` | `ModelResult` | contenedor agregado |
| `"model_card"` | `ModelCardSection` | resumen para governance/report |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning", "selection", "model"])
coef = study.artifacts.get("model", "coefficients")
pd_raw = study.artifacts.get("model", "raw_pd_frame")
features = study.artifacts.get("model", "final_features")
```

## 5. Configuración (schema Pydantic)

`ModelConfig` es el sub-config de la sección `model` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig` (`extra="forbid"`, `frozen=True`), campos con `title`/`description`, rangos `ge/le`, `Literal` en categóricos y metadatos `ui_*`. **No es infraestructura** (`model ∉ INFRA_SECTIONS`): cambiar engine, umbrales, stepwise u overrides cambia el `config_hash`.

```python
# nikodym/model/config.py
from typing import Literal
from pydantic import Field, model_validator
from nikodym.core.config import NikodymBaseConfig

class StepwiseConfig(NikodymBaseConfig):
    enabled: bool = Field(True, title="Activar stepwise")
    direction: Literal["none", "forward", "backward", "bidirectional"] = Field(
        "bidirectional", title="Dirección del stepwise")
    criterion: Literal["wald_pvalue", "lr_test", "both"] = Field(
        "wald_pvalue", title="Criterio estadístico")
    entry_p_value: float = Field(0.05, ge=0.0, le=1.0, title="p-value máximo de entrada")
    exit_p_value: float = Field(0.05, ge=0.0, le=1.0, title="p-value máximo para permanecer")
    max_iter: int = Field(100, ge=1, title="Máximo de iteraciones stepwise")
    min_features: int = Field(1, ge=1, title="Mínimo de variables finales")

class SignPolicyConfig(NikodymBaseConfig):
    expected_beta_sign: Literal["negative"] = Field(
        "negative", title="Signo esperado de beta para WoE")
    action: Literal["exclude", "flag", "fail"] = Field("exclude", title="Acción ante signo invertido")
    fail_on_forced_inverted: bool = Field(
        True, title="Fallar si una variable forzada queda con signo invertido")

class IvContributionConfig(NikodymBaseConfig):
    threshold: float = Field(0.90, ge=0.0, le=1.0, title="Máximo aporte individual de IV")
    action: Literal["exclude", "flag", "fail"] = Field(
        "exclude", title="Acción ante IV-contribution excesivo")

class ModelConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"  # == @register("standard", domain="model")
    engine: Literal["logit", "glm_binomial"] = Field(
        "logit",
        title="Motor statsmodels",
        description="Logit por defecto; GLM Binomial para casos que requieran pesos/familia GLM.",
    )
    fit_intercept: bool = Field(True, title="Incluir intercepto")
    optimizer: Literal["newton", "bfgs", "lbfgs"] = Field("newton", title="Optimizador Logit")
    fit_maxiter: int = Field(100, ge=1, title="Iteraciones máximas del ajuste")
    tol: float = Field(1e-8, gt=0.0, title="Tolerancia de convergencia")
    alpha: float = Field(0.05, gt=0.0, lt=1.0, title="Nivel alpha para intervalos")

    stepwise: StepwiseConfig = Field(default_factory=StepwiseConfig, title="Stepwise")
    sign_policy: SignPolicyConfig = Field(default_factory=SignPolicyConfig, title="Signos beta")
    iv_contribution: IvContributionConfig = Field(
        default_factory=IvContributionConfig, title="IV-contribution")

    force_include: tuple[str, ...] = Field(default_factory=tuple, title="Forzar inclusión")
    force_exclude: tuple[str, ...] = Field(default_factory=tuple, title="Forzar exclusión")
    fail_if_no_features: bool = Field(True, title="Fallar si no queda ninguna variable")
```

**Validaciones de config.**
- `force_include` y `force_exclude` no pueden intersectar.
- `stepwise.direction="none"` implica `stepwise.enabled=False` en la instancia normalizada, o se acepta como alias explícito de "usar todos los candidatos salvo exclusiones/signos/IV".
- `entry_p_value <= exit_p_value` no es obligatorio en v1 porque se admiten políticas simétricas; si Cami prefiere hysteresis, el default futuro puede ser `entry=0.05`, `exit=0.10`.
- `engine="logit"` no acepta `sample_weight`; si se pasan pesos, `ModelFitError` debe indicar usar `engine="glm_binomial"` o diferir pesos a una extensión aprobada.

**Defaults defendibles.**
- `engine="logit"`: ESPEC §5.2 pide inferencia/stepwise con `statsmodels`; `Logit` publica directamente `params`, `bse`, `pvalues`, `llf`, `prsquared`, `llr`.
- `stepwise.direction="bidirectional"`: captura la práctica esperada de agregar señal y remover redundancia dentro del modelo, después de `selection`.
- `criterion="wald_pvalue"` y `p=0.05`: criterio simple, auditable y convencional; CMF exige tests estadísticos documentados, pero no fija este umbral.
- `sign_policy.action="exclude"`: ESPEC §4/§5.2 define como regla dura eliminar efectos contrarios al riesgo. `flag` queda para análisis exploratorio, no default regulatorio.
- `iv_contribution.threshold=0.90` y `action="exclude"`: refleja ESPEC §5.2; impide que el modelo final dependa casi por completo de una sola variable dominante.
- `fit_intercept=True`: la logística necesita intercepto para estimar la tasa base antes de scorecard/calibración.

**Hook diferido en `core.config.schema`.** F1 debe extender el patrón real ya usado por `data`/`eda`/`binning`/`selection`:
- declarar `_MODEL_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir `model` como campo `Any` en runtime y `ModelConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("model", mode="before")` con nombre `_valida_model` que, si `_MODEL_CONFIG_CLS` está poblado, valida con `ModelConfig.model_validate(valor)`, y si no lo está exige JSON canónico determinista;
- `nikodym.model.__init__` asigna `_schema._MODEL_CONFIG_CLS = ModelConfig` al importarse y luego importa `nikodym.model.step` para ejecutar `@register`;
- `core.study` agrega `"model"` a `_DOMAIN_MODULES`, `_DOMAIN_CONFIG_CLASSES` y `_DEFAULT_DOMAIN_ORDER` inmediatamente después de `"selection"`.

## 6. Contratos de datos (I/O)

**Input vía `Study`.**
- `("selection", "selected_woe_frame")`: `pandas.DataFrame` con columnas estructurales (`target`, `label_status`, `partition`, `ttd`) y solo las columnas WoE candidatas seleccionadas por SDD-07.
- `("selection", "selected_features")`: tuple de nombres raw candidatos.
- `("selection", "selected_woe_columns")`: tuple de columnas WoE candidatas, mismo largo y orden que `selected_features`.
- `("binning", "summary")`: `pandas.DataFrame` con al menos `name` e `iv`; fuente única para IV-contribution.
- `("data", "labels")`: `LabeledFrame`, fuente de `target_col`.
- `("data", "splits")`: `PartitionResult`, fuente de `partition_col`.

**Poblaciones.**
- **Fit / stepwise / inferencia:** filas con `partition == "desarrollo"` y `target ∈ {0,1}`.
- **Predicción PD cruda:** filas con `partition ∈ {"desarrollo", "holdout", "oot"}` y columnas WoE finales finitas.
- **Fuera de modelo:** `partition="fuera_de_modelo"` no se ajusta ni se puntúa; si aparece en `selected_woe_frame`, se filtra fuera con evento auditado.

**Output `coefficients`.** `pandas.DataFrame` con una fila por `intercept` y por variable final:

| columna | significado |
|---|---|
| `feature` | nombre raw o `"intercept"` |
| `woe_column` | columna WoE o `"const"` |
| `beta` | coeficiente estimado |
| `standard_error` | error estándar statsmodels |
| `wald_z` | `beta / standard_error` |
| `p_value` | p-value del contraste Wald |
| `conf_low`, `conf_high` | intervalo de confianza según `alpha` |
| `expected_sign` | `"negative"` para variables WoE; `"none"` para intercepto |
| `sign_ok` | `True/False/None` |
| `iv` | IV consumido de `binning.summary` |
| `iv_contribution` | `iv / sum(iv_final)` |

**Output `raw_pd_frame`.** `pandas.DataFrame` con mismo índice que las filas modelables de `selected_woe_frame`:
- `partition`
- `target`
- `linear_predictor`
- `pd_raw`
- opcionalmente `score_input_complete` para marcar filas puntuadas sin missing/no finitos.

**Invariantes.**
- *No leakage:* cambiar Holdout/OOT no cambia `final_features`, coeficientes, p-values, stepwise ni fit statistics de Desarrollo.
- *No mutación:* no modifica `selected_woe_frame`, `binning.summary`, `labels` ni `splits`; publica copias `deep=True`.
- *Consistencia:* `final_features` y `final_woe_columns` tienen la misma longitud y orden; cada feature final existe en `selected_features`.
- *Finitud:* ningún coeficiente, p-value, `pd_raw` o `linear_predictor` publicable puede ser `NaN`/`inf`. Statsmodels warnings de separación/convergencia se convierten en `ModelFitError` salvo política explícita de flag no-default.
- *Signo:* con `sign_policy.action="exclude"`, toda variable final tiene `beta < 0`. `beta == -0.0` se normaliza a `0.0` y no pasa como negativo.
- *IV-contribution:* con `iv_contribution.action="exclude"`, toda variable final cumple `iv_contribution <= threshold`.
- *Orden estable:* outputs tabulares se ordenan por `final_features`; empates del stepwise se resuelven por nombre raw lexicográfico.

## 7. Algoritmos y flujo

**`ModelStep.execute(study, rng)` — secuencia canónica.**
1. **Descartar azar.** `del rng` porque v1 no usa muestreo; queda recibido por contrato `Step`.
2. **Leer artefactos.** Validar presencia y tipos de `selected_woe_frame`, `selected_features`, `selected_woe_columns`, `binning.summary`, `labels`, `splits`.
3. **Copias defensivas.** Trabajar sobre copias profundas de frames/tablas de entrada.
4. **Resolver target/partición.** Tomar `target_col` desde `LabeledFrame` y `partition_col` desde `PartitionResult`.
5. **Resolver IV.** Construir `iv_by_feature` desde `binning.summary[["name", "iv"]]`; validar que toda feature candidata tenga IV finito. No recalcular IV.
6. **Validar overrides.** `force_include`/`force_exclude` deben referirse a features candidatas, no a columnas raw fuera de selección. Conflicto include/exclude → `ConfigError`.
7. **Partición Desarrollo.** `dev = frame[partition == "desarrollo" & target.notna()]`; verificar ambas clases, tamaño mínimo implícito y columnas WoE finitas.
8. **Instanciar estimador.** `LogisticPDModel.from_config(cfg)`; inyectar `_audit` desde el `ModelStep`.
9. **Ajustar stepwise.** Llamar `fit(...)` con `dev[woe_columns]`, `dev[target]`, metadata y `iv_by_feature`.
10. **Predecir PD cruda.** Aplicar `predict_pd`/`decision_function` sobre filas Desarrollo/HO/OOT con columnas finales. No usar target de HO/OOT para decidir.
11. **Construir DTOs.** `ModelFitStatistics`, tabla de coeficientes, `StepwiseDecision`, `ModelCardSection`, `ModelResult`.
12. **Publicar artefactos.** Escribir las nueve claves `provides` bajo `"model"`; frames con `copy(deep=True)`.

**`LogisticPDModel.fit(...)` — stepwise de alto nivel.**
1. **Preparar matriz.** Seleccionar columnas candidatas, agregar intercepto si `fit_intercept=True`, conservar nombres.
2. **Pool inicial.**
   - `direction="forward"`: empezar con `force_include`.
   - `direction="backward"`: empezar con todas las candidatas salvo `force_exclude`.
   - `direction="bidirectional"`: empezar con `force_include` y alternar entrada/salida.
   - `direction="none"` o `enabled=False`: usar candidatas salvo exclusiones y luego aplicar signos/IV.
3. **Ajuste statsmodels.** Fitear `Logit(y, X, check_rank=True).fit(method=optimizer, maxiter=fit_maxiter, disp=False)` o `GLM(y, X, family=Binomial()).fit(...)`. `PerfectSeparationWarning`, `ConvergenceWarning`, `LinAlgError` o no convergencia → `ModelFitError`, salvo que el caso esté explícitamente configurado como `flag` para diagnóstico.
4. **Forward.** Para cada candidata fuera del modelo:
   - fitear modelo completo con candidata;
   - calcular p-value por Wald y/o LR-test;
   - elegir la menor p-value; desempate por feature lexicográfico;
   - si pasa `entry_p_value`, registrar `log_decision(regla="stepwise_enter", ...)` y agregar.
5. **Backward.** Para cada variable no forzada dentro del modelo:
   - calcular p-value de permanencia por Wald y/o LR-test de remoción;
   - elegir la peor candidata a salir; desempate por mayor p-value y luego feature lexicográfico;
   - si excede `exit_p_value`, registrar `log_decision(regla="stepwise_remove", ...)` y remover.
6. **Signos.** Tras cada cambio y en el modelo final, revisar `beta` de variables WoE:
   - `beta < 0` pasa;
   - `beta >= 0` gatilla `sign_policy.action`: `exclude` remueve y reitera; `flag` conserva y marca; `fail` levanta `ModelFitError`;
   - si la variable está en `force_include` y `fail_on_forced_inverted=True`, se levanta `ModelFitError`.
7. **IV-contribution.** Con las variables vigentes, calcular `iv / sum(iv)` desde `iv_by_feature`:
   - si alguna supera `threshold`, aplicar `iv_contribution.action`;
   - `exclude` remueve la variable de mayor contribución no forzada y reitera;
   - si todas las excedidas están forzadas, levantar `ModelFitError` salvo `flag`.
8. **Convergencia del stepwise.** Termina cuando no hay entrada/salida/guard activo o se alcanza `max_iter`; alcanzar `max_iter` sin converger → `ModelFitError`.
9. **Fit final.** Fitear una última vez con variables finales, construir atributos `_`, normalizar floats y devolver `self`.

**Criterios cuando `criterion="both"`.**
- Entrada: una variable entra solo si Wald y LR cumplen `p <= entry_p_value`.
- Salida: una variable sale si Wald o LR incumplen `p > exit_p_value`.
- Esto es conservador: evita que una variable entre por un solo contraste y permite remover una variable que falla cualquiera de los dos lentes.

**Alternativas descartadas.**
- *Usar `sklearn.linear_model.LogisticRegression` como motor principal:* descartado; no publica inferencia estadística nativa (SE/p-values/Wald/LR) y chocaría con ESPEC §5.2.
- *Mover stepwise a `selection`:* descartado; `selection` no mira coeficientes ni likelihood.
- *Recalcular IV desde `selected_woe_frame`:* descartado; rompe trazabilidad con SDD-06 y puede divergir por smoothing/partición.
- *Usar HO/OOT para decidir stepwise:* descartado por leakage.
- *Aceptar signos invertidos como warning default:* descartado; ESPEC exige eliminar efectos contrarios al riesgo por defecto.
- *Penalización L1/L2 en v1:* descartado; statsmodels regularized cambia inferencia/p-values y pertenece a una extensión futura o benchmark ML, no al scorecard regulatorio mínimo.

**Complejidad / rendimiento.** Stepwise requiere múltiples fits: en el peor caso O(p²) fits para `p` candidatas. En scorecard de comportamiento, `selection` ya reduce p; si p sigue alto, el coste es explícito en `stepwise_trace` y el usuario debe endurecer `selection` o configurar `max_iter`.

## 8. Casos borde y manejo de errores

- **Faltan artefactos de `selection`/`binning`/`data`:** `ArtifactNotFoundError` por CT-1 antes de entrar a `execute`.
- **`selected_features` y `selected_woe_columns` tienen largo distinto:** `ModelFitError` con ambos largos y nombres.
- **Feature final sin IV en `binning.summary`:** `ModelFitError`; no se calcula IV dentro de `model`.
- **Desarrollo sin ambas clases:** `ModelFitError`; no hay logística defendible.
- **Todas las variables caen por stepwise/signos/IV:** con `fail_if_no_features=True`, `ModelFitError`; con `False`, se permite solo modelo intercepto para diagnóstico y se marca en el model card como no apto para scorecard.
- **Separación perfecta/cuasi-perfecta:** warning/resultado no convergente de statsmodels → `ModelFitError` con sugerencia de revisar bins/variables dominantes.
- **Matriz singular / rank deficiente:** `ModelFitError`; SDD-07 debió reducir colinealidad, pero `model` falla ruidosamente si persiste.
- **Coeficiente con SE no finito o p-value no finito:** `ModelFitError`.
- **Signo invertido en variable no forzada:** acción según `sign_policy`; default exclusión auditada.
- **Signo invertido en `force_include`:** default `ModelFitError`, porque un override de negocio no puede convertir una relación contraria al riesgo en aceptable sin revisión explícita.
- **IV-contribution excedido:** default exclusión auditada; si solo queda una variable, normalmente su contribución es `1.0` y falla salvo política `flag`, lo que debe quedar en D-MOD-4.
- **`force_include` de variable no seleccionada por SDD-07:** error ruidoso; `model` no revive variables descartadas pre-modelo.
- **Valores `NaN`, `inf`, `-inf` en columnas WoE:** `ModelFitError` antes de statsmodels.
- **Predicción con columnas faltantes:** `ModelTransformError` listando columnas requeridas y faltantes.
- **`sample_weight` con `engine="logit"`:** `ModelFitError`; usar `glm_binomial` cuando se apruebe flujo ponderado.
- **Warnings externos bajo `filterwarnings=error`:** la implementación captura localmente warnings esperados de statsmodels y los convierte en `ModelFitError`/flags; no relaja la política global.

Toda excepción del módulo desciende de `NikodymError`; los mensajes son en español e incluyen feature, regla, umbral/config y valor observado.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno en v1. `ModelStep.execute(study, rng)` recibe `rng` por contrato y debe hacer `del rng` con nota local.
- **Determinismo esperado.** `(data_hash + config_hash + root_seed + uv.lock) → final_features, coeficientes, p-values, PD cruda y trazas idénticas`, salvo cambios de backend BLAS/statsmodels documentados en `dependency_versions`.
- **Stepwise determinista.** Orden de candidatas estable desde `selection`; empates por p-value/LR dentro de tolerancia se resuelven por nombre raw lexicográfico. No se usa orden accidental de columnas como razón auditable.
- **Normalización numérica.** Publicar `-0.0` como `0.0`; redondeos solo para reporte, no para cálculo. Si se materializan hashes auxiliares en tests, usar enteros con endian explícito (`astype("<u8")`) y nunca `hash()` builtin.
- **Audit trail (`log_decision`).** Registrar, como mínimo:
  - cada variable que entra al stepwise: regla, criterio, p-value, LR si aplica, umbral y acción `"entrar"`;
  - cada variable que sale: regla, criterio, p-value/LR, umbral y acción `"salir"`;
  - variable no elegida por p-value sobre umbral cuando sea la mejor candidata rechazada de una iteración;
  - signo invertido: feature, `beta`, signo esperado, acción (`excluir`, `flag`, `fallar`);
  - IV-contribution excedido: feature, IV, contribución, umbral, acción;
  - convergencia/no convergencia de statsmodels;
  - uso de `force_include`/`force_exclude`.
- **Model card / report.** `ModelCardSection` debe permitir reconstruir el modelo final: engine, umbrales, variables candidatas/finales, decisiones stepwise, flags de signo/IV, fit statistics y versiones de dependencias.
- **Lineage.** `model` no completa `data_hash` ni `config_hash`; su contribución al lineage son su config computacional, sus dependencias y decisiones auditadas.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymClassifier`, `MissingDependencyError`, `NikodymError`, `Registry`.
- SDD-02 (`data`): `labels`, `splits`, partición Desarrollo/HO/OOT, target binario.
- SDD-05 (convenciones): config Pydantic, hook diferido, `config_hash`, API sklearn-like.
- SDD-06 (`binning`): `summary.iv` como fuente única del IV-contribution.
- SDD-07 (`selection`): `selected_woe_frame`, `selected_features`, `selected_woe_columns`.

**Aguas abajo.**
- SDD-09 (`scorecard`) consume `final_features`, `final_woe_columns` y `coefficients`.
- SDD-10 (`calibration`) consume `raw_pd_frame` para anclar PD a tendencia central.
- SDD-11 (`performance`/`stability`) consume `raw_pd_frame`, `final_features` y `model_card` para validación formal.
- SDD-26 (`report`) consume coeficientes, stepwise trace, diagnósticos y model card.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| statsmodels | 0.14.6 en `uv.lock` (`pyproject`: `>=0.14`) | BSD ✅ | `Logit`, `GLM`, `Binomial`, inferencia, likelihood | extra `[scoring]` |
| scikit-learn | 1.7.2 en `uv.lock` (`pyproject`: `>=1.6`, constraint `<1.8`) | BSD-3 ✅ | `BaseEstimator`, `ClassifierMixin`, checks sklearn | extra `[scoring]` |
| scipy | 1.18.0 en `uv.lock` para Python >=3.12 (`pyproject`: `>=1.10`) | BSD ✅ | `scipy.stats.chi2.sf` para LR-test | extra `[scoring]` |
| pandas | 2.3.3 en `uv.lock` (`pyproject`: `>=2.0`) | BSD-3 ✅ | DataFrame/Series, tablas de salida | base |
| numpy | 2.4.6 en `uv.lock` (`pyproject`: `>=1.22`) | BSD ✅ | arrays, expit/logit, finitud | base |

**Núcleo liviano.** `nikodym.core` no importa `model`, `statsmodels`, `sklearn` ni `scipy`. `import nikodym.model` debe registrar `ModelConfig` y `ModelStep` sin importar `statsmodels/sklearn/scipy` en top-level: `model.step` no importa el estimador a nivel de módulo; lo carga dentro de `execute` o mediante `__getattr__`. Si falta `[scoring]`, se levanta `MissingDependencyError` con mensaje `"instale nikodym[scoring]"`.

**Verificación local 2026-06-27 contra `.venv` y `uv.lock`.**
- `statsmodels.__version__ == "0.14.6"`.
- `statsmodels.discrete.discrete_model.Logit(endog, exog, offset=None, check_rank=True, **kwargs)`.
- `Logit.fit(start_params=None, method="newton", maxiter=35, full_output=1, disp=1, callback=None, **kwargs)`; en resultados publica `params`, `bse`, `pvalues`, `tvalues`, `llf`, `llnull`, `prsquared`, `aic`, `bic`, `llr`, `llr_pvalue`, `mle_retvals`.
- `statsmodels.genmod.generalized_linear_model.GLM(endog, exog, family=None, offset=None, exposure=None, freq_weights=None, var_weights=None, missing="none", **kwargs)` con `Binomial()`.
- `GLM.fit(..., method="IRLS", tol=1e-8, ...)` publica `params`, `bse`, `pvalues`, `llf`, `llnull`, `aic`, `bic` y método `pseudo_rsquared(kind="cs")`; para McFadden se puede calcular explícitamente.
- Separación perfecta emite `PerfectSeparationWarning`; falta de convergencia emite `ConvergenceWarning` y `mle_retvals["converged"] == False`.

**Normativa oficial verificada 2026-06-27.** Se contrastó `docs/normativa_cmf_parametros.md` contra el PDF oficial CMF `cir_2249_2020.pdf` (Compendio de Normas Contables Bancos, versión 2022) descargado desde `cmfchile.cl`, con `pdftotext` y render visual local de las páginas 35 y 40. Para `model` solo aplican requisitos generales de metodologías internas y documentación del componente PI; los parámetros PI/PDI/PE estándar pertenecen a SDD-15.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **Canónicos de Logit.** Caso intercept-only con solución cerrada `β0 = log(n_bad/n_good)`, `LL` y pseudo-R2 verificables a mano. Caso pequeño con dos variables y golden values de `statsmodels 0.14.6` para `params`, `bse`, `pvalues`, `llf`, `prsquared`.
- **LR-test.** Dos modelos anidados con `LL_full` y `LL_reduced` conocidos desde statsmodels; verificar `LR = 2*(LL_full-LL_reduced)` y `scipy.stats.chi2.sf`.
- **Stepwise determinista.** Dataset con una variable informativa, una noise y una redundante: dos corridas con misma semilla y distinto orden de columnas producen `final_features` y `stepwise_trace` idénticos; empates se resuelven por nombre.
- **Signo β.** Construir un caso donde una columna WoE queda con `β >= 0`; default `exclude` la remueve y registra evento. Con `force_include` + `fail_on_forced_inverted=True` levanta `ModelFitError`.
- **IV-contribution.** `binning.summary` sintético con IV dominante (`0.95` de contribución) gatilla exclusión/fallo según política. Verificar que el valor viene de `binning.summary`; alterar `selected_woe_frame` no cambia IV.
- **Anti-leakage.** Cambiar valores/target de HO/OOT no cambia coeficientes, p-values, features finales ni trace; solo cambia predicciones HO/OOT si cambian las columnas WoE de esas particiones.
- **No mutación.** Snapshots profundos de `selection.selected_woe_frame`, `selection.selected_features`, `selection.selected_woe_columns` y `binning.summary` permanecen iguales tras `ModelStep.execute`.
- **Warnings como errores.** Separación perfecta y no convergencia se convierten en `ModelFitError` con `filterwarnings=error` global; no se relaja la suite.
- **Contrato `Step`.** `ModelStep.requires` exige `data`, `binning.summary` y los tres artefactos exactos de `selection`; falta uno → `ArtifactNotFoundError`. `provides` se verifica tras ejecución.
- **Config.** Round-trip YAML de `ModelConfig`; cambiar `entry_p_value`, `sign_policy.action`, `iv_contribution.threshold` o `engine` cambia `config_hash`; `model` sin importar `nikodym.model` se mantiene como JSON canónico opaco y al importar se valida como `ModelConfig`.
- **Import liviano duro.** `import nikodym.core` no importa `nikodym.model`; `import nikodym.model` no importa `statsmodels`, `sklearn` ni `scipy` salvo que ya estén cargados. Ejecutar `ModelStep` o importar `LogisticPDModel` sí puede cargarlos.
- **Clone/sklearn.** `LogisticPDModel` tiene `__init__` keyword-only sin lógica, `get_params/set_params` clone-safe, `config_cls` correcto y atributos fiteados con sufijo `_`.
- **Propiedades.** `predict_proba` devuelve probabilidades en `[0,1]` y filas suman 1; `predict_pd` preserva índice; `raw_pd_frame` conserva orden modelable.

Fixtures: `behavior_model_small.parquet` derivado del pipeline `data → binning → selection`, `ModelConfig` mínimo y variantes por policy, `InMemoryAuditSink`, y `binning.summary` sintético con IV controlado.

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Sobreajuste por stepwise.** Mitigación: `selection` reduce candidatos, stepwise auditable, límites de p-value/IV-contribution y validación formal aguas abajo en SDD-11.
- **Falsa sensación de validación.** `model` reporta fit in-sample; SDD-11 sigue siendo obligatorio para performance/estabilidad multi-partición.
- **Signos dependientes de convención WoE.** Si Cami cambia la convención de WoE en SDD-06, `expected_beta_sign` debe cambiar de forma coordinada con SDD-08/09.
- **Separación perfecta por variables dominantes.** Mitigación: `max_iv`/correlación/VIF en `selection`, IV-contribution en `model`, error ruidoso en statsmodels.
- **Dependencia pesada en imports.** Mitigación: imports perezosos y `MissingDependencyError`.
- **CMF internal-methods vs scorecard de comportamiento.** El modelo F1 no es el motor CMF estándar; si un banco usa esta PD como componente PI de una metodología interna, governance/calibration/performance deben completar la evidencia exigida por los Anexos CMF.

**Fuentes verificadas / citas.**
- **ESPECIFICACIONES.md** §4 (principios 1, 2, 4, 8, 9, 10, 11), §5.2 (pipeline scorecard: stepwise Wald/LR, signos de β, IV-contribution ≤ 90%, scorecard/calibración/performance aguas abajo), §6.3 (`model/` = logística + stepwise statsmodels), §7 (statsmodels/sklearn/scipy BSD), §9 (gobernanza).
- **ROADMAP.md** F1 (stepwise Wald/LR, statsmodels, signos, IV-contribution).
- **SDD-01 (`core`)** §4/§7 (Step, `requires`/`provides`, `ArtifactKey`, `AuditableMixin.log_decision`, clases base, CT-1), §9 (reproducibilidad).
- **SDD-02 (`data`)** §6 (target, `partition`, Desarrollo/HO/OOT/fuera_de_modelo), §12 (frontera transversal scorecard).
- **SDD-05** §4/§5 (API sklearn-like, `ModelConfig`, hooks diferidos, `config_hash`, `INFRA_SECTIONS`).
- **SDD-06 (`binning`)** §3/§6/§12 (WoE `ln(%Goods/%Bads)`, IV final, artefactos y signo esperado aguas abajo).
- **SDD-07 (`selection`)** §1/§2/§4/§6/§12 (frontera con stepwise; artefactos exactos consumidos por `model`).
- **docs/normativa_cmf_parametros.md** Advertencias y §7 (parámetros CMF son para provisiones; vigilancia regulatoria).
- **CMF oficial:** Compendio de Normas Contables Bancos, versión 2022, Circular N° 2.243/2019, Capítulo B-1 Anexos 1 y 2 (`https://www.cmfchile.cl/institucional/mercados/ver_archivo.php?archivo=/web/compendio/cir/cir_2249_2020.pdf`), verificado por texto extraído y render visual local.
- **Verificación local 2026-06-27 contra `.venv`/`uv.lock`:** `statsmodels 0.14.6`, `scikit-learn 1.7.2`, `scipy 1.18.0`, `pandas 2.3.3`, `numpy 2.4.6`; firmas y atributos de `Logit`/`GLM` descritos en §10.

## Decisiones para revisión de Cami

- **D-MOD-1 — Motor default `statsmodels.Logit`.** Default defendible por inferencia nativa (`params`, SE, p-values, LL, pseudo-R2). `GLM Binomial` queda como alternativa configurada, especialmente si se aprueba un flujo ponderado.
- **D-MOD-2 — Stepwise default bidireccional por Wald p-value `0.05`.** CMF exige tests estadísticos documentados pero no fija umbral; `0.05` es estándar y simple. Confirmar si Cami prefiere LR-test default o `criterion="both"`.
- **D-MOD-3 — Signo esperado `β < 0` para WoE y política default `exclude`.** Deriva de `WoE=ln(%Goods/%Bads)` y `target=1` malo. Confirmar que se mantiene la convención WoE de SDD-06; si cambia, cambia este signo y SDD-09.
- **D-MOD-4 — IV-contribution threshold `0.90` con acción default `exclude`.** Fija como hard guard el límite de ESPEC. Confirmar si una scorecard de una sola variable debe fallar por defecto o permitirse con `flag`.
- **D-MOD-5 — Métricas que reporta `model`: likelihood, AIC/BIC, pseudo-R2 y trazas in-sample Dev; SDD-11 conserva performance formal multi-partición.** Confirmar si incluir AUC/KS/Gini Dev como diagnóstico opcional en `model_card` o dejarlos exclusivamente a SDD-11.
- **D-MOD-6 — `ModelConfig.type="standard"` y `ModelStep @register("standard", domain="model")`.** Sigue el patrón de `binning`/`selection`; no usa `type="logit"` en v1 porque `ml` vive en SDD-12. Confirmar si Cami quiere preparar una unión `LogitModelConfig` desde ya.
- **D-MOD-7 — `force_include` no puede violar signos por defecto.** Un override de negocio puede forzar entrada frente a p-value, pero no aceptar `β` contrario al riesgo salvo `sign_policy.action="flag"` explícito y revisión.
- **D-MOD-8 — `raw_pd_frame` es PD cruda no calibrada.** Es útil para calibración y performance, pero debe etiquetarse como no calibrada para evitar uso directo en provisiones.
- **D-MOD-9 — Sin dependencia nueva.** `statsmodels`, `sklearn`, `scipy`, `pandas`, `numpy` ya están en `uv.lock` y son permisivas. Confirmar que `model` vive en extra `[scoring]`.
