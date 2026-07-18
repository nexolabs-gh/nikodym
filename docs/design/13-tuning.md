# SDD-13 — `tuning` (optimización de hiperparámetros con Optuna)

| Campo | Valor |
|---|---|
| **SDD** | 13 |
| **Módulo** | `nikodym.tuning` |
| **Dominio** | Machine Learning / búsqueda de hiperparámetros |
| **Fase** | F2 |
| **Tanda de producción** | T3 (ML) |
| **Estado** | ✅ Implementado; API experimental |
| **Depende de** | SDD-01 (`core`), SDD-05 (convenciones + config), **SDD-12 (`ml`)**; **reúsa** SDD-11 (`performance`) para la métrica objetivo; SDD-06 (`binning`)/SDD-07 (`selection`) como fuente de features (heredada de `ml`) |
| **Lo consumen** | SDD-12 (`ml`, consume los hiperparámetros tuneados; rev. menor aditiva), SDD-26 (`report`, curva de optimización + trials) |
| **Autor / Fecha** | DanIA (worker A14, redacción SDD-13 para T3) / 2026-07-04 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `tuning` **busca los hiperparámetros óptimos del challenger ML** (SDD-12) con **Optuna** —sampler seedeado, espacio de búsqueda editable por config, función objetivo reproducible— optimizando una métrica de discriminación (AUC por default) sobre un **recorte interno de `desarrollo`**, **sin contaminar** `holdout`/`oot`, y publica los hiperparámetros ganadores listos para que `ml` los consuma.

**Responsabilidad única (qué SÍ hace).**
- Expone un **optimizador genérico** (`TuningOptimizer`) que **envuelve** el `MLChallenger` de SDD-12 vía su **API sklearn-like** (`MLChallenger.from_config` + `get_params`/`set_params`, SDD-12 §4) para instanciar, ajustar y evaluar un challenger por cada trial. La abstracción es **target-agnóstica por diseño** (reusable a futuro para LGD/EAD), pero v1 solo cablea **clasificación binaria / PD** (mismo alcance scoring-first que `ml`).
- Define un **espacio de búsqueda editable por config, tipado por backend** (`search_space.py`): por cada hiperparámetro, su distribución (entera / real / logarítmica / categórica) y sus rangos, **sin `eval`** ni expresiones ejecutables de usuario.
- Corre un **estudio Optuna** determinista: `TPESampler` seedeado vía `SeedManager.int_seed_for("tuning")`, pruner opcional, `n_trials`, `direction`, `timeout` opcional.
- Evalúa cada trial **reusando** `PerformanceEvaluator` de SDD-11 (AUC/Gini/KS); **nunca reimplementa** una métrica de discriminación.
- Aplica una **política anti-leakage explícita**: la optimización ocurre sobre CV estratificado (o un holdout interno seeded) de `desarrollo`; `holdout`/`oot` nunca se ven durante la búsqueda.
- **Hereda** de `ml` (lee `NikodymConfig.ml`) el `backend`, la `feature_source`, la monotonía y las columnas: **no duplica** esa configuración ni el preprocesamiento (consume las mismas features WoE de `binning`/`selection`).
- Mantiene **fijas** las restricciones de monotonía durante la búsqueda (constraint regulatoria, no un hiperparámetro a optimizar).
- Publica artefactos namespaced bajo `"tuning"`: mejores hiperparámetros (sub-config tipado), `MLConfig` tuneada lista para `ml`, `best_estimator` reajustado, historial de trials, importancia de hiperparámetros, resultado y card CT-2.
- Aporta `TuningConfig` como sección **computacional** de `NikodymConfig`; por tanto, cambios de espacio de búsqueda, sampler, `n_trials` o métrica mueven el `config_hash`.
- Registra con `log_decision` el sampler y su semilla, el espacio de búsqueda, la métrica objetivo, la política anti-leakage, el mejor trial y cada gate de reproducibilidad/determinismo.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No entrena ni compara el challenger contra el campeón.** El ajuste final del challenger, su PD, la comparación cabeza-a-cabeza y la calibración opcional son **SDD-12 `ml`**; `tuning` solo busca hiperparámetros y se los entrega a `ml`. El `best_estimator` que publica es de conveniencia/inspección, no reemplaza el challenger autoritativo de la comparación.
- **No calcula SHAP ni reason codes.** La explicabilidad es SDD-14 `explain`.
- **No reimplementa métricas.** AUC/Gini/KS salen de `PerformanceEvaluator` (SDD-11); `tuning` los llama, no los recodifica (test AST anti-reimplementación, §11).
- **No define ni preprocesa features.** Consume las features WoE aguas arriba (`binning`/`selection`), igual que `ml`; el manejo de missing/special lo resolvió `binning`.
- **No optimiza LGD/EAD en v1.** La abstracción se diseña extensible, pero solo PD/binario se implementa.
- **No selecciona el backend por búsqueda.** El backend es fijo (el de `NikodymConfig.ml`); `tuning` optimiza **los hiperparámetros de ese backend**, no compite entre backends (eso sería una capa AutoML fuera de alcance v1).
- **No usa `eval` ni expresiones ejecutables.** El espacio de búsqueda es una estructura Pydantic tipada por backend.
- **No promete determinismo byte-a-byte con paralelismo o `timeout`.** El paralelismo de trials (`n_jobs>1`) y el corte por `timeout` (reloj de pared) rompen la reproducibilidad; v1 default a **secuencial single-thread sin timeout**, y marca los otros modos como no byte-reproducibles.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Machine Learning (F2/T3), inmediatamente **antes** de `ml` en el pipeline: `tuning` produce los hiperparámetros que `ml` consume para ajustar el challenger definitivo (ROADMAP.md:L69 "Optuna (samplers seedeados, search spaces editables)"; DoD "tuning reproducible (seed)" y "mismo pipeline de datos que F1", ROADMAP.md:L71).
- **Quién lo invoca:** `Study.run()` como sección `tuning` de `NikodymConfig`, o API programática `TuningOptimizer.from_config(...)` + `TuningStep`.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `SeedManager`, excepciones, lineage); `ml` (`MLChallenger`, `MLConfig`, backends — API sklearn-like); y —reusado programáticamente— `PerformanceEvaluator` (SDD-11) para la métrica objetivo. Lee el frame de features de `binning`/`selection`.
- **Quién lo consume aguas abajo:** SDD-12 (`ml`) consume `("tuning","best_hyperparameters")`/`("tuning","best_config")` para ajustar el challenger con los hiperparámetros óptimos (rev. menor aditiva de SDD-12, ver §6); SDD-26 (`report`) renderiza la curva de optimización y los trials.

```text
                          lee NikodymConfig.ml (backend, feature_source, monotonía)
                                        │
data.labels + data.splits ─┐           ▼
binning.woe_frame ─────────┼──► tuning ──► tuning.best_hyperparameters ─┐
  (mismas features que ml) │      │      ├─► tuning.best_config (MLConfig tuneada) ──► ml
     reúsa PerformanceEval ─┘      │      ├─► tuning.best_estimator (refit conveniencia)
     envuelve MLChallenger         │      ├─► tuning.trials / tuning.importance
       (from_config/set_params)    │      └─► tuning.card (CT-2: curva de optimización + trials)
                                   ▼
                        NUNCA holdout/oot durante la búsqueda (anti-leakage §7)
```

**Anclaje normativo/metodológico interno.**
- ESPECIFICACIONES §5.3 fija Optuna (samplers seedeados) para el tuning de F2 y monotonic constraints donde el modelo lo soporte (ESPECIFICACIONES.md:L116-L118). El paquete `tuning/` figura en el árbol como "Optuna (samplers seedeados)" (ESPECIFICACIONES.md:L191) y `optuna` está listado con licencia **MIT** (permisiva, permitida en el core; ESPECIFICACIONES.md:L223).
- ROADMAP F2 declara "Optuna (samplers seedeados, search spaces editables)" como entregable y "tuning reproducible (seed)" en el DoD (ROADMAP.md:L69,L71).
- CT-1 exige `requires`/`provides` explícitos; CT-2 exige card estructurada aditiva (`metric_sections`); CT-3 mantiene el panel transversal de scorecard (`tuning` opera sobre él, igual que `ml`).
- Principio 9 (núcleo liviano) exige `optuna` tras extra opcional con import perezoso.

**Interacción con `Study` y config declarativo.** `TuningStep` es un `Step` nativo registrado con `@register("standard", domain="tuning")`. Se construye desde `TuningConfig`; sus `requires` son **dinámicos** según la `feature_source` **heredada de `NikodymConfig.ml`** (no de `TuningConfig`, para no duplicar):
- siempre requiere `("data","labels")` y `("data","splits")`;
- si la `ml.feature_source="binning_woe"` (default): requiere `("binning","woe_frame")` y `("binning","result")`;
- si `ml.feature_source="selection_woe"`: requiere `("selection","selected_woe_frame")` y `("selection","selected_woe_columns")`;
- si `ml.monotonic.mode="from_binning"`: añade `("binning","tables")` y `("binning","result")` para derivar la monotonía por variable (misma lógica que `ml`, §7);
- **no** requiere `("model","raw_pd_frame")`: `tuning` no compara contra el campeón (eso es `ml`).

Esto cumple CT-1: `TuningStep` expone su DAG efectivo antes de ejecutar. El motor v1 valida prerequisitos; el scheduler topológico sigue diferido a F5 por CT-1. **`tuning` requiere que `NikodymConfig.ml` exista** (no se puede tunear un challenger sin saber qué backend): si `study.config.ml is None`, `TuningConfigError`.

**Cableado implementado en `core.study`.**
- `_DOMAIN_MODULES["tuning"] = "nikodym.tuning"`;
- `_DOMAIN_CONFIG_CLASSES["tuning"] = ("nikodym.tuning.config", "TuningConfig")`;
- `_DEFAULT_DOMAIN_ORDER` ubica `"tuning"` **antes** de `"ml"` (tras `"calibration"`), de modo que sus hiperparámetros existan cuando `ml` ejecute; el orden real efectivo lo resuelve CT-1 por `requires`, no por suposición lineal;
- mientras el scheduler topológico no exista, el usuario debe declarar `binning` (y, si aplica, `selection`) antes de `tuning`, y `tuning` antes de `ml`.

**Paquete físico y troceo B13.x.**

```text
src/nikodym/tuning/
  __init__.py
  config.py
  exceptions.py
  results.py
  search_space.py
  optimizer.py
  step.py
```

**B13.1 — `config.py` + `exceptions.py`.** `TuningConfig`, sub-schemas (objetivo, sampler/pruner, validación anti-leakage), jerarquía de errores, hook diferido `_TUNING_CONFIG_CLS` en `NikodymConfig`, round-trip YAML, defaults D-TUN y validaciones sin imports pesados. Aquí se **mueve** `GOLDEN_DEFAULT_CONFIG_HASH` (ver §5).
**B13.2 — `search_space.py` + `results.py`.** Schema del espacio de búsqueda tipado por backend + traducción a distribuciones Optuna; DTOs frozen del estudio (trials, importancia, best, card CT-2). Sin imports de optuna en top-level.
**B13.3 — `optimizer.py`.** `TuningOptimizer`: estudio Optuna (sampler seedeado, pruner, direction), función objetivo que envuelve `MLChallenger` (SDD-12) y reúsa `PerformanceEvaluator` (SDD-11) sobre CV seeded de `desarrollo`; import perezoso de optuna/pandas/numpy.
**B13.4 — `step.py` + cableado + `__init__.py`.** `TuningStep`, `@register(domain="tuning")`, CT-1 dinámico (hereda `feature_source` de `ml`), `del rng` + `int_seed_for("tuning")`, publicación de artefactos, audit trail, hook `importlib`, y prueba end-to-end `Study` (`tuning` antes de `ml`).

## 3. Conceptos y fundamentos

**Fuente normativa/metodológica interna.**
- ESPECIFICACIONES §5.3 (Optuna samplers seedeados, monotonic constraints; ESPECIFICACIONES.md:L116-L118), §6.3 (paquete `tuning/`; L191), §7 (optuna MIT; L223).
- ROADMAP F2 objetivo/entregables/DoD (ROADMAP.md:L64-L72).
- CT-1/CT-2/CT-3 (`_CONTRATOS-TRANSVERSALES.md`).
- SDD-12 §4 (API sklearn-like de `MLChallenger`: `from_config`, `get_params`/`set_params`), §5 (`MLConfig`, hiperparámetros tipados por backend), §9 (determinismo, `int_seed_for`).

**Qué es el tuning de hiperparámetros.** El challenger ML (SDD-12) tiene hiperparámetros (p.ej. `max_depth`, `learning_rate`, `n_estimators` en XGBoost) que gobiernan su capacidad y regularización. `ml` los recibe **fijados** por config (defaults D-ML-9 conservadores). `tuning` los **busca**: define un espacio de valores admisibles y explora combinaciones para maximizar una métrica de discriminación en validación interna, entregando la combinación ganadora a `ml`. El scorecard sigue siendo el campeón regulatorio; tunear el challenger solo afila el **benchmark de poder predictivo**.

**Optuna (define-by-run).** Optuna optimiza una **función objetivo** `objective(trial) -> float`: en cada trial, el `trial` **sugiere** valores de hiperparámetros (`trial.suggest_int/suggest_float/suggest_categorical`) desde las distribuciones del espacio de búsqueda; se ajusta y evalúa el challenger con esos valores; se devuelve la métrica. Un **sampler** (TPE por default) propone la próxima combinación con base en el historial; un **pruner** puede abortar trials poco prometedores. El **`study`** acumula los trials y expone `best_params`/`best_value`/`best_trial`.

**Reproducibilidad del sampler.** El `TPESampler` es determinista dada su **semilla** y ejecución **secuencial** (`n_jobs=1`). La semilla se deriva de `SeedManager.int_seed_for("tuning")` (entropía compuesta `[root_seed, sha256("tuning")]`, uint32 estable cross-proceso; SDD-01 §7), **no** del `rng` por-paso del motor (que `tuning` descarta con `del rng`, §9). El paralelismo de trials o el corte por `timeout` (reloj de pared) introducen no-determinismo y se marcan como no byte-reproducibles.

**Función objetivo sin leakage.** El objetivo se evalúa **solo sobre `desarrollo`** (la partición de ajuste de `ml`), particionada internamente por **CV estratificado seeded** (K folds) o un **holdout interno seeded**. `holdout`/`oot` **nunca** se pasan al objetivo: quedan como particiones de evaluación limpias para que `ml`/`validation` midan sin sesgo de selección de hiperparámetros. Las **folds son fijas entre trials** (misma semilla) para que la comparación de hiperparámetros no se confunda con la varianza del split.

**Métrica objetivo (reúso de SDD-11).** Por default la métrica es **AUC** (dirección `maximize`), calculada por `PerformanceEvaluator.evaluate(...)` (SDD-11); `gini`/`ks` son alternativas (también `maximize`, monótonas respecto de AUC en el caso de gini). `tuning` **nunca** recodifica la métrica: arma el frame analítico (score = logit de `pd_hat`, `pd_raw` = `pd_hat` recortada a (0,1)) y lo pasa al evaluator, exactamente como `ml` en su comparación (SDD-12 §7). La discriminación es **invariante a la calibración**, así que se optimiza sobre PD cruda del challenger sin calibrar.

**Monotonía fija durante la búsqueda.** Las constraints de monotonía son una **restricción regulatoria** (principio 4), no un hiperparámetro. `tuning` las deriva una vez (igual que `ml`: `from_binning` ⇒ `-1` por variable WoE monótona, `0` si no monótona; SDD-12 §7) y las mantiene **fijas** en cada trial. Buscar "sin monotonía" para ganar AUC violaría la interpretación de riesgo; no se ofrece.

**Notación.**
- `θ`: vector de hiperparámetros del backend; `Θ`: espacio de búsqueda (producto de distribuciones por HP).
- `X_dev`, `y_dev`: features WoE y target binario de `desarrollo`.
- `(train_k, val_k)`: k-ésima fold estratificada de `desarrollo` (K folds, seeded).
- `m(θ)`: métrica objetivo (AUC por default) promediada sobre las folds de validación con hiperparámetros `θ`.
- `θ*`: `argmax_θ m(θ)` sobre los trials evaluados.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/tuning/exceptions.py
class TuningError(NikodymError): ...
class TuningConfigError(TuningError): ...
class TuningSearchSpaceError(TuningConfigError): ...
class TuningDataError(TuningError): ...
class TuningOptimizeError(TuningError): ...
class TuningDeterminismError(TuningError): ...
```

`MissingDependencyError` (de `core`) se levanta cuando falta el extra `[tuning]` (optuna); no es una excepción propia de `tuning`.

```python
# nikodym/tuning/search_space.py
class IntSpec(NikodymBaseConfig):        # entero: low..high, opcional log/step
    kind: Literal["int"] = "int"
    low: int
    high: int
    log: bool = False
    step: int = 1

class FloatSpec(NikodymBaseConfig):      # real: low..high, opcional log
    kind: Literal["float"] = "float"
    low: float
    high: float
    log: bool = False

class CategoricalSpec(NikodymBaseConfig):
    kind: Literal["categorical"] = "categorical"
    choices: tuple[str | int | float | bool, ...]

ParamSpec = IntSpec | FloatSpec | CategoricalSpec   # unión discriminada por `kind` (factory local)

class SearchSpaceConfig(NikodymBaseConfig):
    # mapa hiperparámetro → distribución; las claves deben ser campos del params-model del backend
    params: dict[str, ParamSpec] = Field(default_factory=dict)

def default_search_space(backend: "MLBackendName") -> SearchSpaceConfig: ...   # rangos por backend
def suggest_params(trial: object, space: SearchSpaceConfig) -> dict[str, object]: ...  # traduce a suggest_*
```

```python
# nikodym/tuning/optimizer.py
class TuningOptimizer(BaseNikodymEstimator):
    config_cls: ClassVar[type[TuningConfig]] = TuningConfig

    @classmethod
    def from_config(cls, cfg: TuningConfig, ml_cfg: "MLConfig") -> "TuningOptimizer": ...

    def optimize(
        self, X: "pandas.DataFrame", y: "pandas.Series", *,
        seed: int,                              # SeedManager.int_seed_for("tuning")
        monotone_directions: "dict[str, int] | None" = None,
        audit: "AuditSink | None" = None,
    ) -> "TuningResult": ...
    # Envuelve MLChallenger.from_config(ml_cfg) + set_params(**θ) por trial; evalúa con
    # PerformanceEvaluator (SDD-11) sobre CV seeded de X/y (nunca holdout/oot).
```

**Atributos fiteados (convención `_`).** `study_` (objeto Optuna, no serializable), `best_params_`, `best_value_`, `best_config_` (`MLConfig` tuneada), `best_estimator_` (`MLChallenger` reajustado si `refit_best`), `trials_`, `param_importances_`, `sampler_seed_`, `n_trials_effective_`, `deterministic_`.

```python
# nikodym/tuning/results.py
class TuningTrialRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    number: int
    params: dict[str, str | int | float | bool]
    value: float | None                 # None si el trial fue podado/fallido
    state: Literal["complete", "pruned", "fail"]

class SamplerMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sampler: str
    pruner: str
    seed: int
    n_trials_requested: int
    n_trials_complete: int
    optuna_version: str
    direction: Literal["maximize", "minimize"]
    metric: Literal["auc", "gini", "ks"]
    deterministic: bool

class TuningCardSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    summary: dict[str, str | int | float | bool]
    metric_sections: dict[str, object] = Field(default_factory=dict)   # CT-2: curva + trials + importancia
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

class TuningResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    best_hyperparameters: "SvmParams | RandomForestParams | XGBoostParams | LightGBMParams | CatBoostParams"
    best_config: "MLConfig"                              # MLConfig con los HP ganadores sustituidos
    best_estimator: "MLChallenger | None"               # refit sobre desarrollo si refit_best
    best_value: float
    trials: tuple[TuningTrialRecord, ...]
    param_importances: tuple[tuple[str, float], ...]    # (hiperparámetro, importancia), desc
    sampler_metadata: SamplerMetadata
    card: TuningCardSection
    def term_structure(self) -> "pandas.DataFrame | None": ...   # CT-2: None (tuning no es multi-período)
    def trials_frame(self) -> "pandas.DataFrame": ...            # tidy de TuningTrialRecord
```

```python
# nikodym/tuning/step.py
@register("standard", domain="tuning")
class TuningStep(AuditableMixin):
    name: str = "tuning"
    requires: tuple[ArtifactKey, ...]     # dinámico según ml.feature_source / ml.monotonic (§2)
    provides: tuple[ArtifactKey, ...] = (
        ("tuning", "best_hyperparameters"),
        ("tuning", "best_config"),
        ("tuning", "best_estimator"),
        ("tuning", "trials"),
        ("tuning", "importance"),
        ("tuning", "result"),
        ("tuning", "card"),
    )
    @classmethod
    def from_config(cls, cfg: TuningConfig) -> "TuningStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "TuningResult": ...  # del rng
```

**Artefactos que `TuningStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"best_hyperparameters"` | sub-config tipado por backend | los HP ganadores `θ*` (mismo schema que `MLConfig.hyperparameters`) |
| `"best_config"` | `MLConfig` | copia de `NikodymConfig.ml` con `hyperparameters=θ*` (lista para `ml`) |
| `"best_estimator"` | `MLChallenger` \| `None` | challenger reajustado sobre `desarrollo` con `θ*` (si `refit_best`) |
| `"trials"` | `tuple[TuningTrialRecord, ...]` | historial de trials (número, params, valor, estado) |
| `"importance"` | `tuple[tuple[str, float], ...]` | importancia de hiperparámetros (Optuna) |
| `"result"` | `TuningResult` | contenedor agregado |
| `"card"` | `TuningCardSection` | resumen governance/report con `metric_sections` CT-2 |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning", "selection", "model", "scorecard",
                 "calibration", "tuning", "ml"])   # tuning ANTES de ml
tuning_result = study.artifacts.get("tuning", "result")
best = tuning_result.best_hyperparameters           # p.ej. XGBoostParams(max_depth=4, learning_rate=0.03, ...)
curve = tuning_result.trials_frame()                # nº de trial vs valor objetivo

# API programática:
optimizer = TuningOptimizer.from_config(cfg.tuning, ml_cfg=cfg.ml)
result = optimizer.optimize(X_dev, y_dev, seed=study.seed_manager.int_seed_for("tuning"))
tuned_ml_cfg = result.best_config                   # se lo pasa a MLChallenger.from_config
```

## 5. Configuración (schema Pydantic)

`TuningConfig` es el sub-config de la sección `tuning` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, `Literal` para categóricos, rangos explícitos, defaults defendibles y metadata UI. **`tuning ∉ INFRA_SECTIONS`**: todo cambio computacional mueve `config_hash`.

**Impacto en `GOLDEN_DEFAULT_CONFIG_HASH` (verificado contra `core/config/hashing.py`).** `config_hash()` serializa `cfg.model_dump(mode="json", by_alias=True, exclude=INFRA_SECTIONS)` **sin** `exclude_none`, e `INFRA_SECTIONS = {"name","governance","audit","tracking","report"}` (`core/config/hashing.py:L24`) **no incluye `tuning`**. Las secciones computacionales en `None` **sí entran** al payload canónico (mismo precedente que `ml`/`validation`/`stress`). Por tanto, **añadir el campo `tuning` (default `None`) a `NikodymConfig` agrega la clave `"tuning":null` al JSON canónico y MUEVE `GOLDEN_DEFAULT_CONFIG_HASH`** (hoy `33e1dcce…0cf746`). Esto es **esperado** al codificar B13.1: se recalcula y actualiza el golden en los tests de config, igual que hicieron `ml`/`validation`/`survival`/`stress`. En este ítem solo-docs **no** se mueve ningún hash ni se toca código.

```python
# nikodym/tuning/config.py
TuningSampler = Literal["tpe", "random"]
TuningPruner = Literal["none", "median"]
TuningMetric = Literal["auc", "gini", "ks"]
ValidationStrategy = Literal["cv", "holdout"]

class TuningObjectiveConfig(NikodymBaseConfig):
    metric: TuningMetric = "auc"               # se maximiza (auc/gini/ks son «mayor = mejor»)
    direction: Literal["maximize"] = "maximize"

class TuningSamplerConfig(NikodymBaseConfig):
    sampler: TuningSampler = "tpe"
    pruner: TuningPruner = "none"
    n_trials: int = Field(default=50, ge=1, le=10000)
    timeout_seconds: int | None = Field(default=None, ge=1)   # None ⇒ byte-reproducible

class TuningValidationConfig(NikodymBaseConfig):
    strategy: ValidationStrategy = "cv"
    n_folds: int = Field(default=5, ge=2, le=20)               # aplica a strategy="cv"
    holdout_fraction: float = Field(default=0.2, gt=0.0, lt=1.0)  # aplica a strategy="holdout"
    fit_partition: str = "desarrollo"          # partición sobre la que se busca (nunca holdout/oot)

class TuningConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"
    schema_version: str = "1.0.0"
    objective: TuningObjectiveConfig = Field(default_factory=TuningObjectiveConfig)
    optimizer: TuningSamplerConfig = Field(default_factory=TuningSamplerConfig)
    validation: TuningValidationConfig = Field(default_factory=TuningValidationConfig)
    search_space: SearchSpaceConfig = Field(default_factory=SearchSpaceConfig)   # vacío ⇒ default por backend
    refit_best: bool = True                    # publica best_estimator reajustado sobre desarrollo
    deterministic: bool = True
    n_jobs: int = Field(default=1, ge=1, le=256)
```

**Herencia desde `ml` (no duplicar).** `TuningConfig` **no** declara `backend`, `feature_source`, `monotonic` ni columnas: los **lee de `NikodymConfig.ml`** en runtime. Así el espacio de búsqueda por default se resuelve para el backend de `ml`, la fuente de features y la monotonía son las mismas, y no hay dos fuentes de verdad. Si `NikodymConfig.ml is None` ⇒ `TuningConfigError` (no hay challenger que tunear).

**Espacio de búsqueda por default (D-TUN-space).** Si `search_space.params` está vacío, `default_search_space(ml.backend)` provee rangos defendibles alrededor de los defaults D-ML-9, p.ej. XGBoost:
`max_depth: Int(2, 8)`, `learning_rate: Float(0.01, 0.3, log=True)`, `n_estimators: Int(100, 1500)`, `subsample: Float(0.6, 1.0)`, `colsample_bytree: Float(0.6, 1.0)`, `reg_lambda: Float(1e-3, 10, log=True)`, `min_child_weight: Float(0.0, 10.0)`. Los rangos por backend se documentan en `search_space.py`; **a confirmar por Cami** (D-TUN-space).

**Validaciones de config.**
- Cada clave de `search_space.params` debe ser un **campo válido** del params-model del backend de `ml` (cross-check contra `_PARAMS_BY_BACKEND[backend]`, SDD-12 §5); clave desconocida ⇒ `TuningSearchSpaceError`.
- Coherencia de tipo: p.ej. un `FloatSpec` sobre un HP entero ⇒ `TuningSearchSpaceError`; `low >= high` ⇒ error; `log=True` con `low <= 0` ⇒ error.
- `CategoricalSpec.choices` no vacío y homogéneo con el tipo del HP.
- `deterministic=True` con `n_jobs>1` ⇒ `TuningConfigError` (el paralelismo de trials rompe el determinismo; ver §9). Alternativa: forzar `n_jobs=1` con warning (D-TUN-det).
- `deterministic=True` con `timeout_seconds` no nulo ⇒ `TuningConfigError` (el corte por reloj de pared es no byte-reproducible).
- `validation.strategy="cv"` exige `n_folds>=2`; `"holdout"` usa `holdout_fraction`.
- `pruner != "none"` con `strategy="holdout"` (un solo valor de validación, sin pasos intermedios que podar) ⇒ `TuningConfigError` (el pruner necesita valores intermedios; con CV se reportan por fold).

**Campos, defaults y sentido.**
- `objective.metric`: default D-TUN-metric `"auc"` (discriminación estándar; invariante a calibración). `gini`/`ks` disponibles.
- `optimizer.sampler`: default D-TUN-sampler `"tpe"` (Bayesiano, eficiente en pocos trials; seedeable). `"random"` como baseline.
- `optimizer.pruner`: default D-TUN-pruner `"none"` (búsqueda completa, determinismo simple); `"median"` disponible con `strategy="cv"`.
- `optimizer.n_trials`: default D-TUN-trials `50` (equilibrio costo/mejora para un espacio de ~6 HP). **a confirmar por Cami.**
- `validation.strategy`/`n_folds`: default D-TUN-leakage `"cv"`/`5`, estratificado y seeded sobre `desarrollo`; `holdout`/`oot` intactos.
- `refit_best`: default `True` (publica `best_estimator` de conveniencia).
- `deterministic`/`n_jobs`: default D-TUN-det `True`/`1` (byte-reproducibilidad; ver §9).

**Round-trip YAML y UI.** Sigue SDD-05: dump JSON-mode, `sort_keys=False`, carga vía `load_config`. La UI (SDD-23) renderiza el sampler/pruner/n_trials como formulario, la validación como selector CV/holdout, y el espacio de búsqueda como tabla `hiperparámetro → distribución` **dependiente del backend de `ml`** (los HP disponibles salen del params-model del backend).

**Hook diferido en `core.config.schema`.**
- declarar `_TUNING_CONFIG_CLS: type[BaseModel] | None = None` (junto a `_ML_CONFIG_CLS`, `core/config/schema.py:L68`);
- añadir `tuning` como campo `Any` en runtime y `TuningConfig | None` bajo `TYPE_CHECKING` (patrón idéntico a `ml`, `schema.py:L238-L250`);
- añadir `@field_validator("tuning", mode="before")` (`_valida_tuning`) que coacciona vía el hook, con fallback a blob JSON-canónico si el hook no está cargado (patrón de `_valida_ml`, `schema.py:L606-L629`);
- no importar `nikodym.tuning` desde `core`;
- al importar `nikodym.tuning`, poblar `_schema._TUNING_CONFIG_CLS = TuningConfig`;
- **actualizar `GOLDEN_DEFAULT_CONFIG_HASH`** en B13.1.

## 6. Contratos de datos (I/O)

**Input duro del Step según config.**

| artefacto | requerido | contrato |
|---|---|---|
| `("data","labels")` | siempre | `LabeledFrame` de SDD-02; provee `target_col` |
| `("data","splits")` | siempre | `PartitionResult` de SDD-02; provee `partition_col` |
| `("binning","woe_frame")` + `("binning","result")` | si `ml.feature_source="binning_woe"` | DataFrame WoE + `woe_column_map` |
| `("selection","selected_woe_frame")` + `("selection","selected_woe_columns")` | si `ml.feature_source="selection_woe"` | subconjunto WoE + nombres |
| `("binning","tables")` + `("binning","result")` | si `ml.monotonic.mode="from_binning"` | tablas WoE por feature (para derivar monotonía) |

Además, `tuning` **lee `NikodymConfig.ml`** (no un artefacto) para el backend, `feature_source`, monotonía y columnas. Cada clave `requires` **existe como `provides`** en su SDD vecino (DAG cerrado); son las **mismas** que `ml` **excepto** `("model","raw_pd_frame")`, que `tuning` no consume.

**Poblaciones (anti-leakage).** La búsqueda usa **solo** `ml.train.fit_partition` (`desarrollo`) con `target` no nulo, particionada internamente (CV seeded o holdout interno). `holdout`/`oot`/`fuera_de_modelo` **nunca** entran al objetivo. Copias defensivas: `tuning` **no muta** los frames de entrada.

**Output `tuning.best_hyperparameters`.** Instancia del params-model del backend (`XGBoostParams`, etc.) con los valores ganadores `θ*`. Es exactamente el tipo que consume `MLConfig.hyperparameters` (SDD-12 §5), de modo que `ml` lo integra sin conversión.

**Output `tuning.best_config`.** Una `MLConfig` = `NikodymConfig.ml` con `hyperparameters=θ*` sustituido (resto invariante). Es el artefacto que `ml` consume para ajustar el challenger definitivo.

**Output `tuning.trials` / `tuning.importance`.** `tuple[TuningTrialRecord, ...]` (número, params, valor, estado) y `tuple[tuple[str, float], ...]` (hiperparámetro → importancia, desc). El tidy `trials_frame()`: `number`, `param_*`, `value`, `state`.

**Invariantes.**
- Los valores objetivo son finitos (`-0.0 → 0.0`); un trial fallido/podado lleva `value=None` y `state∈{fail,pruned}`, nunca `NaN`/`inf`.
- `best_value` = máximo (o mínimo, según `direction`) de los trials `complete`.
- `best_config` difiere de `ml` **solo** en `hyperparameters`.
- El orden de `trials` es el orden de ejecución (número de trial ascendente); `importance` desc por valor con desempate lexicográfico.
- No se mutan `data.*`, `binning.*`, `selection.*` ni `NikodymConfig.ml`.
- `best_estimator` (si `refit_best`) se ajusta con `θ*` y semilla fija sobre `desarrollo`, coherente con lo que `ml` obtendría con `best_config`.

**Nota de DAG aguas abajo (consumo por `ml`).** Que `ml` consuma `("tuning","best_hyperparameters")`/`("tuning","best_config")` es una **rev. menor aditiva de SDD-12** (deuda **B-ML-TUN**): `MLStep` gana un `requires` **opcional** sobre `("tuning","best_config")` que, si está presente, sustituye sus `hyperparameters` por los tuneados; ausente `tuning`, `ml` usa su config como hoy (comportamiento SDD-12 intacto). Es **aditivo**, no rompe el contrato cerrado de SDD-12 (mismo patrón con que SDD-12 trató el consumo de su PD por `validation`, "deuda B-VAL"). Alternativamente, el usuario cablea manualmente `ml.hyperparameters = tuning.best_hyperparameters`. Default v1: la rev. aditiva de `ml`. `tuning` **no** depende de `ml` en el DAG (corre antes); su dependencia sobre SDD-12 es de **código** (importa `MLChallenger`/`MLConfig`).

## 7. Algoritmos y flujo

**`TuningStep.execute(study, rng)` — secuencia canónica.**
1. **`del rng`.** `tuning` no consume el `rng` por-paso del motor; deriva su azar de `SeedManager` (auditable, coherente con `int_seed_for`).
2. **Resolver configs.** Leer `study.config.tuning` (fallback al config del paso) y `study.config.ml`; si `ml is None` ⇒ `TuningConfigError`.
3. **Construir `requires`.** Desde `ml.feature_source`/`ml.monotonic.mode`; validar CT-1 antes de ejecutar (mismas claves que `ml` menos el campeón).
4. **Derivar semilla.** `seed = study.seed_manager.int_seed_for("tuning")` (uint32 estable; SDD-01 §7). Esta semilla siembra el sampler, las folds de CV y el `fit` del challenger por trial (constante entre trials).
5. **Leer artefactos.** Copiar defensivamente el frame de features (`woe_frame`/`selected_woe_frame`), `labels`, `splits`; extraer columnas WoE (misma lógica que `ml`, SDD-12 §7).
6. **Construir `X_dev`/`y_dev`.** Filtrar a `ml.train.fit_partition` con `target` no nulo; validar clases y filas mínimas.
7. **Derivar monotonía fija.** Según `ml.monotonic.mode` (idéntico a `ml`: `from_binning` ⇒ `-1`/`0` por variable desde `binning.tables`; `explicit` ⇒ mapa; `off` ⇒ ninguna). Se mantiene constante en todos los trials.
8. **Resolver espacio de búsqueda.** `search_space.params` o `default_search_space(ml.backend)`; validar contra el params-model del backend.
9. **Construir el estudio Optuna.** `optuna.create_study(direction=..., sampler=TPESampler(seed=seed) | RandomSampler(seed=seed), pruner=...)`. Import perezoso de optuna (extra `[tuning]`); si falta ⇒ `MissingDependencyError("instale nikodym[tuning]")`.
10. **Definir el objetivo.** `objective(trial)`:
    a. `θ = suggest_params(trial, space)` (traduce cada spec a `trial.suggest_int/float/categorical`; sin `eval`).
    b. Construir el challenger: `MLChallenger.from_config(ml_cfg).set_params(hyperparameters=<params-model(θ)>, deterministic=True, n_threads=1)` (o `from_config` de una `MLConfig` con `θ`).
    c. Sobre cada fold `(train_k, val_k)` de un CV estratificado seeded de `X_dev` (folds fijas entre trials): `challenger.fit(X_train_k, y_train_k, rng=np.random.default_rng(seed))` (semilla de fit constante), `pd_hat = challenger.predict_pd(X_val_k)`.
    d. Métrica por fold: armar el frame analítico (score = logit de `pd_hat` recortada a (0,1), `pd_raw` = `pd_hat`) y llamar `PerformanceEvaluator.evaluate(...)`; leer AUC/Gini/KS de `discriminant_records`. **No** se recodifica la métrica.
    e. (Si `pruner != "none"`) `trial.report(valor_parcial, step=k)` y `if trial.should_prune(): raise TrialPruned`.
    f. Devolver el **promedio** de la métrica sobre las folds de validación.
11. **Optimizar.** `study.optimize(objective, n_trials=cfg.optimizer.n_trials, timeout=cfg.optimizer.timeout_seconds, n_jobs=cfg.n_jobs)`.
12. **Extraer resultados.** `best_params_`/`best_value_` desde `study.best_trial`; construir `θ*` como params-model; `best_config_` = `ml_cfg` con `hyperparameters=θ*`; `trials_` desde `study.trials`; `param_importances_` con `optuna.importance.get_param_importances(study)`.
13. **Refit (opcional).** Si `refit_best`, ajustar `best_estimator_ = MLChallenger.from_config(best_config_).fit(X_dev, y_dev, rng=np.random.default_rng(seed))`.
14. **Validar invariantes.** Valores finitos, `best_config` difiere solo en HP, folds no tocaron `holdout`/`oot`, determinismo declarado.
15. **Construir DTOs.** `SamplerMetadata`, `TuningCardSection` (con `metric_sections` CT-2: `optimization_history`, `param_importances`, `trials`), `TuningResult`.
16. **Auditar decisiones.** Sampler/semilla, espacio de búsqueda, métrica/estrategia de validación, mejor trial, determinismo.
17. **Publicar artefactos.** Escribir las siete claves `provides` bajo `"tuning"`.

**Reúso del evaluator (sin reimplementar métricas).** `tuning` **no** recodifica AUC/Gini/KS: importa perezosamente `PerformanceEvaluator` (SDD-11) y le pasa el frame de cada fold de validación. Un test AST impide que aparezcan `roc_auc_score`/KS reimplementados en `tuning` (§11). Es el mismo reúso que `ml` en su comparación (SDD-12 §7).

**Reúso del challenger (sin reimplementar el fit).** Cada trial usa `MLChallenger` (SDD-12) vía `from_config`/`set_params`/`fit`/`predict_pd`. `tuning` **no** reimplementa el manejo de backends, monotonía, early stopping ni la normalización de PD: los hereda del wrapper. Un test AST impide importar los backends ML (`xgboost`/`lightgbm`/…) directamente en `tuning`.

**Alternativas descartadas.**
- *Optimizar sobre `holdout`/`oot`:* descartado; contamina las particiones de evaluación (leakage de selección de hiperparámetros). Se usa CV/holdout interno de `desarrollo`.
- *Buscar el backend (AutoML):* descartado v1; el backend es fijo (`ml.backend`). `tuning` optimiza sus HP.
- *Tunear la monotonía:* descartado; es restricción regulatoria fija, no un HP.
- *Semilla de fit variable por trial:* descartado; confundiría la señal de HP con la varianza del split/semilla. Semilla de fit constante entre trials.
- *`dict[str, Any]` de espacio de búsqueda con `eval`:* descartado; specs Pydantic tipadas y discriminadas por `kind`.
- *Sembrar el sampler con `study.seeds`/`rng`:* descartado; Optuna exige un `int`, y `int_seed_for("tuning")` da un uint32 estable coherente con la misma `SeedSequence` (§9).
- *Paralelismo/timeout por default:* descartado; rompen byte-reproducibilidad. Default secuencial sin timeout.

**Complejidad / rendimiento.** Costo `≈ n_trials · K · costo_fit(challenger)`; el CV multiplica por `K` el costo de un solo fit. Single-thread encarece el wall-clock a cambio de determinismo; el modo performance (`n_jobs>1`/`timeout`) queda disponible pero marcado no byte-reproducible. `tuning` registra `n_trials_complete`, `n_folds`, `n_features` y el mejor valor en diagnostics.

## 8. Casos borde y manejo de errores

- **Falta el extra `[tuning]`:** `MissingDependencyError("instale nikodym[tuning]")`, al construir el estudio Optuna.
- **`NikodymConfig.ml` ausente:** `TuningConfigError` (no hay challenger que tunear).
- **Falta artefacto `requires`:** `ArtifactNotFoundError` por CT-1 antes de ejecutar.
- **Clave de `search_space` desconocida para el backend / tipo incompatible / `low>=high` / `log` con `low<=0`:** `TuningSearchSpaceError`.
- **`desarrollo` con una sola clase o filas insuficientes para `n_folds`:** `TuningDataError` (respetando `require_both_classes` de `ml`).
- **Una fold queda de una sola clase (dataset chico):** `TuningDataError`; se sugiere bajar `n_folds` o usar `strategy="holdout"`.
- **Todos los trials fallan/podados:** `TuningOptimizeError` (no hay `best_trial`); se reporta el nº de fallos.
- **`deterministic=True` con `n_jobs>1` o `timeout` no nulo:** `TuningConfigError` (o coacción a `n_jobs=1` con warning, D-TUN-det).
- **`pruner != "none"` con `strategy="holdout"`:** `TuningConfigError` (sin pasos intermedios que podar).
- **Optuna produce un valor no finito:** `TuningOptimizeError`; no se propaga `NaN`/`inf` al `best_value`.
- **Versión de optuna no soportada:** `TuningError` con la versión detectada; los golden se pinean a versión (§9, §11).
- **`filterwarnings=["error"]`:** los warnings de Optuna/backends se convierten en diagnostics explícitos o excepciones controladas; no se silencian (p.ej. `ExperimentalWarning` de importancia se gestiona explícitamente).

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen sampler, semilla, backend, trial y valor observado cuando aplique.

## 9. Reproducibilidad y auditoría

- **Componente estocástico.** El sampler de Optuna y las folds de CV son estocásticos; ambos se siembran desde `seed = SeedManager.int_seed_for("tuning")` (entropía compuesta `[root_seed, sha256("tuning")]`; nunca `hash()` builtin sensible a `PYTHONHASHSEED`). `tuning` hace `del rng` en `execute`: **no** consume el `Generator` por-paso del motor (a diferencia de `ml`), porque Optuna exige un `int` y `int_seed_for` lo entrega de forma coherente con la misma `SeedSequence` (SDD-01 §7).
- **Sampler seedeado.** `TPESampler(seed=seed)` / `RandomSampler(seed=seed)`; ejecución **secuencial** (`n_jobs=1`) para determinismo trial-a-trial. La semilla de fit del challenger es **constante** entre trials (`np.random.default_rng(seed)` reconstruido por trial), aislando la señal de HP.
- **Determinismo esperado.** `(data_hash + config_hash + root_seed + optuna_version + backend_version + single_thread) → trials, best_params, importance, card idénticos`. Con `n_jobs>1` o `timeout` solo se garantiza estabilidad estadística, no byte-a-byte; ambos exigen `deterministic=False` y se marcan en `sampler_metadata`/card.
- **Versión de optuna pineada.** Los golden dependen de la versión exacta de optuna (el algoritmo del TPE puede cambiar). `optuna_version` se registra y los tests golden fijan el rango (`optuna>=3.5`, D-TUN-golden); un cambio de versión que mueva el golden es un evento auditado, no un fallo silencioso.
- **Normalización numérica.** `-0.0 → 0.0` en los valores objetivo; sin `NaN`/`inf` en `best_value`; hashes auxiliares (si se hashean frames) con `pandas.util.hash_pandas_object(...).astype("<u8")`.
- **Núcleo liviano.** `import nikodym.tuning` **no** importa `optuna`/`sklearn`/`pandas`/`numpy` ni los backends ML; solo registra `TuningConfig` + `TuningStep` y puebla el hook. Imports pesados dentro de `execute`/`optimize`. Anotaciones de DataFrame/estudio bajo `TYPE_CHECKING` o strings.
- **Audit trail (`log_decision`).** Registrar como mínimo:
  - `tuning_sampler`: sampler, pruner, semilla, `n_trials`, `optuna_version`;
  - `tuning_search_space`: hiperparámetros y distribuciones efectivas;
  - `tuning_objective`: métrica, dirección, estrategia de validación (CV/holdout), `n_folds`;
  - `tuning_leakage`: partición de búsqueda (`desarrollo`), confirmación de que `holdout`/`oot` no se usaron;
  - `tuning_best`: mejor trial, `θ*`, `best_value`, nº de trials completos;
  - `tuning_importance`: importancia de hiperparámetros;
  - `tuning_determinism`: si el modo no es byte-reproducible (`n_jobs>1`/`timeout`).
- **Card / report.** `TuningCardSection.metric_sections` incluye `"optimization_history"` (valor por trial), `"param_importances"` y `"trials"`; `"determinism"` cuando el modo no sea byte-reproducible. `TuningResult.term_structure()` retorna `None` (tuning no es multi-período; CT-2).
- **Lineage.** `tuning` consume `config_hash` y hashes aguas arriba; agrega el hash de su historial de trials/best_config, no reemplaza el lineage base.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `BaseNikodymEstimator`, `AuditableMixin`, `SeedManager`, `NikodymError`, `MissingDependencyError`, lineage, `config_hash`, patrón CT-2 `term_structure()`.
- SDD-05 (convenciones): Pydantic v2, hooks diferidos, `extra="forbid"`, `frozen=True`, naming inglés APIs/español docs/errores.
- SDD-12 (`ml`): `MLChallenger` (API sklearn-like `from_config`/`get_params`/`set_params`/`fit`/`predict_pd`), `MLConfig`, params-models por backend, `MLBackendName`. **Dependencia de código**, no de artefacto DAG.
- SDD-11 (`performance`): `PerformanceEvaluator` reusado para la métrica objetivo (AUC/Gini/KS).
- SDD-06/07 (`binning`/`selection`): fuente de features WoE (heredada de `ml.feature_source`).

**Aguas abajo.**
- SDD-12 (`ml`) consume `("tuning","best_config")` (rev. menor aditiva B-ML-TUN).
- SDD-26 (`report`) renderiza la curva de optimización y los trials.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| optuna | `>=3.5` (verificado en `pyproject.toml:L65`) | MIT ✅ | estudio, sampler TPE/random, pruner, importancia | extra `nikodym[tuning]`; import perezoso |
| scikit-learn | `>=1.6` (vía backend de `ml`) | BSD-3 ✅ | estratificación / importancia fANOVA (si aplica) | presente vía el extra del backend (`[ml]`/`[xgboost]`/…) |
| pandas / numpy | base de `data` | BSD ✅ | frames, arrays, folds | base; import perezoso |
| pydantic | `>=2` | MIT ✅ | config/DTOs frozen | base |

El extra `[tuning] = ["optuna>=3.5"]` **ya está declarado** en `pyproject.toml` (L65); no se pliega en `[ml]` (D-TUN-extra: extra propio). En la práctica `tuning` co-requiere el extra del backend de `ml` (ajusta challengers), p.ej. `nikodym[tuning,xgboost]`. **Sin copyleft**: optuna es MIT; SHAP (SDD-14) **no** es dependencia de `tuning`.

**Núcleo liviano.**
- `nikodym.core` no importa `nikodym.tuning`.
- `import nikodym.tuning` no importa optuna/sklearn/pandas/numpy ni los backends ML.
- `tuning.__init__` expone config/errores/registro con anotaciones string y `TYPE_CHECKING`, y hace `importlib.import_module("nikodym.tuning.step")` para el `@register` sin arrastrar optuna (patrón idéntico a `ml.__init__`, `src/nikodym/ml/__init__.py:L96`).
- Mensaje de dependencia faltante nombra el extra `[tuning]`.

## 11. Estrategia de tests

Marco transversal en SDD-24. Cobertura objetivo 100% para `tuning` (no es módulo regulatorio, pero la marca exige calidad ejemplar). `filterwarnings=["error"]`, `mypy --strict`, ruff `E,F,I,N,UP,B,SIM,RUF,D` y docstrings públicas en español. Los tests que ajustan challengers usan el marker del backend (`requires_xgboost`/…) y `requires_tuning`.

- **Reproducibilidad byte-a-byte.** Dos corridas con misma semilla, `deterministic=True`, `n_jobs=1`, sin `timeout` y mismos datos ⇒ `trials`/`best_params`/`importance` idénticos tras normalización.
- **No determinismo declarado.** Con `n_jobs>1` o `timeout`, `sampler_metadata.deterministic=False` y el card marca el caveat; no se asevera igualdad byte-a-byte.
- **Anti-leakage.** Snapshot de índices usados en el objetivo ⊆ `desarrollo`; `holdout`/`oot` nunca aparecen (test de aislamiento de particiones).
- **No reimplementación de métricas.** Test AST/grep impide `roc_auc_score`/KS/Gini recodificados en `tuning`; la métrica solo entra como llamada a `PerformanceEvaluator` (SDD-11).
- **No reimplementación del fit.** Test AST impide importar `xgboost`/`lightgbm`/`catboost`/`sklearn` directamente en `tuning`; el ajuste solo entra vía `MLChallenger` (SDD-12).
- **Espacio de búsqueda válido.** Clave desconocida / tipo incompatible / `low>=high` / `log` con `low<=0` ⇒ `TuningSearchSpaceError`; `search_space` vacío usa `default_search_space(backend)`.
- **Traducción de specs.** Un `IntSpec`/`FloatSpec`/`CategoricalSpec` se mapea al `trial.suggest_*` correcto (con un `trial` fake que registra las llamadas), sin `eval`.
- **Best config bien formado.** `best_config` = `ml` con `hyperparameters=θ*` y el resto invariante; `best_hyperparameters` es el params-model del backend.
- **Extra faltante.** Sin `[tuning]` ⇒ `MissingDependencyError("instale nikodym[tuning]")`; sin `NikodymConfig.ml` ⇒ `TuningConfigError`.
- **Import guard.** Subproceso verifica que `import nikodym.tuning` no deja optuna/sklearn/xgboost/lightgbm/catboost/pandas/numpy en `sys.modules`.
- **Config round-trip/hash.** YAML dump/load preserva sampler/espacio/validación; cambiar `search_space`/`sampler`/`n_trials`/`metric` mueve `config_hash`; el default de `NikodymConfig()` con `tuning=None` mueve `GOLDEN_DEFAULT_CONFIG_HASH` respecto al golden previo sin `tuning` (test no tautológico, cálculo independiente).
- **Objetivo determinista.** Con un backend liviano (`random_forest`) y dataset diminuto, el valor objetivo de un trial fijo es estable; el CV seeded produce las mismas folds entre trials.
- **Pruner coherente.** `pruner="median"` con `strategy="cv"` reporta valores por fold y puede podar; `pruner!="none"` con `strategy="holdout"` ⇒ `TuningConfigError`.
- **No mutación.** Snapshots de `woe_frame`, `labels`, `splits`, `NikodymConfig.ml` permanecen iguales.
- **Sin SHAP.** Grep/test documental impide importar `shap` en `tuning`.

Fixtures: `woe_frame_small.parquet` sintético con particiones, `labels`/`splits` mínimos, `MLConfig` por backend, `TuningConfig` con espacio reducido (`n_trials` bajo, `random_forest` para velocidad), `FakePerformanceEvaluator` para aislar el reúso, `FakeTrial` que registra las `suggest_*`, `InMemoryAuditSink`, y datasets degenerados (una sola clase, folds imposibles, todos los trials fallidos, espacio inválido).

## 12. Decisiones abiertas y riesgos

**R0 (Cami).** Ninguno. `tuning` no fija producto irreversible, release público, PyPI, repo-público, deploy ni plata. Las decisiones D-TUN son **defaults metodológicos editables**; **la metodología ML no es R0** (así lo pide el encargo de la tarea).

**D-TUN para revisión de Cami.**
- **D-TUN-sampler — Sampler default.** Recomendación: `"tpe"` (Bayesiano, eficiente en pocos trials, seedeable). `"random"` como baseline reproducible.
- **D-TUN-metric — Métrica objetivo default.** Recomendación: `"auc"` en validación interna (discriminación estándar, invariante a calibración); `gini`/`ks` disponibles. Todas se **maximizan**.
- **D-TUN-trials — `n_trials` default.** Recomendación: `50` (equilibrio costo/mejora para ~6 HP). **A confirmar por Cami** (podría subirse a 100 si el presupuesto de CI lo permite).
- **D-TUN-pruner — Pruner default.** Recomendación: `"none"` (búsqueda completa, determinismo simple); `"median"` disponible solo con `strategy="cv"` (valores por fold).
- **D-TUN-leakage — Política anti-leakage default.** Recomendación: CV estratificado seeded (`n_folds=5`) sobre `desarrollo`; `holdout`/`oot` intactos. `strategy="holdout"` (split interno único) disponible para datasets grandes o presupuesto ajustado.
- **D-TUN-extra — Nombre del extra.** **Resuelto:** extra propio `[tuning] = ["optuna>=3.5"]` (ya en `pyproject.toml:L65`), no plegado en `[ml]`. En la práctica se instala junto al extra del backend (`nikodym[tuning,xgboost]`).
- **D-TUN-det — Determinismo default.** Recomendación: `deterministic=True`/`n_jobs=1`/`timeout=None` (byte-reproducibilidad y golden values). Abierta: ¿`deterministic=True`+`n_jobs>1`/`timeout` debe fallar (recomendado) o coaccionar a secuencial con warning?
- **D-TUN-space — Espacios de búsqueda por default por backend.** Recomendación: rangos conservadores alrededor de los defaults D-ML-9 (§5); **a confirmar por Cami** por backend.
- **D-TUN-golden — Golden values por versión de optuna.** Recomendación: pinear el rango (`optuna>=3.5`) para los golden; un cambio de versión que mueva el golden es un evento auditado.
- **D-TUN-consumo — Consumo por `ml`.** Recomendación: rev. menor aditiva de SDD-12 (`ml` gana un `requires` opcional sobre `("tuning","best_config")`, deuda B-ML-TUN); ausente `tuning`, `ml` intacto.
- **D-TUN-tarea-agnóstico — Optimizador reusable para LGD/EAD.** Recomendación: diseñar `TuningOptimizer`/objetivo sin acoplarlos a clasificación binaria (permitir una métrica/`task` futura), pero **implementar solo PD/binario en v1**.

**FALTA-DATO explícitos.**
- **FALTA-DATO-TUN-1 — Presupuesto de CI para el tuning.** `n_trials · K · fit` puede ser caro en CI; el default (`n_trials=50`, `random_forest` en tests) debe validarse contra el presupuesto de la matriz (CT-5 diferido, `_CONTRATOS-TRANSVERSALES.md` §5).
- **FALTA-DATO-TUN-2 — Evaluador de importancia de HP.** Optuna ofrece fANOVA (requiere sklearn, presente vía el backend) y PedAnova (puro). Default: el evaluador por default de la versión pineada; a documentar como caveat si cambia entre versiones.

**Riesgos y mitigaciones.**
- **Leakage de selección de hiperparámetros.** Mitigación: CV/holdout **interno de `desarrollo`**; `holdout`/`oot` nunca en el objetivo; test de aislamiento de particiones.
- **No determinismo del sampler tomado por bug.** Mitigación: sampler seedeado + secuencial + semilla de fit constante + golden pineados a versión de optuna.
- **Reimplementar métricas/fit por inercia.** Mitigación: reúso de `PerformanceEvaluator` (SDD-11) y `MLChallenger` (SDD-12) + tests AST anti-reimplementación.
- **Tunear la monotonía y romper la interpretación de riesgo.** Mitigación: monotonía **fija** durante la búsqueda; no es un HP.
- **Costo de CI explosivo.** Mitigación: default modesto (`n_trials=50`), tests con backend liviano y espacio reducido; documentar el presupuesto (FALTA-DATO-TUN-1).
- **Acoplamiento circular con `ml`.** Mitigación: `tuning` corre **antes** de `ml` y depende de `ml` solo por **código** (importa clases); el consumo por `ml` es aditivo (B-ML-TUN), no un ciclo DAG.
- **optuna pesado en import.** Mitigación: import perezoso + test `sys.modules`.

**Citas internas.** ESPECIFICACIONES.md §5.3 (L116-L118), §6.3 (L191), §7 optuna MIT (L223); ROADMAP.md F2 (L64-L72); `00-INDICE.md` fila SDD-13 (`tuning`, ML, F2, T3, dep 12, ⬜→🟡); `_CONTRATOS-TRANSVERSALES.md` CT-1/CT-2/CT-3; SDD-12 §4/§5/§7/§9 (`ml`); SDD-11 (`performance`); SDD-24 (`testing`); SDD-25 (`packaging/CI`); `pyproject.toml:L65` (extra `[tuning]`), `L184-L187` (markers); `core/config/hashing.py:L24` (INFRA_SECTIONS); `core/config/schema.py:L68,L238-L250,L606-L629` (hook `_ML_CONFIG_CLS`/`_valida_ml` como molde); `core/study.py:L54-L119` (cableado de dominios); `core/seeding.py:L56` (`int_seed_for`); `src/nikodym/ml/__init__.py:L96` (hook `importlib`).
