# SDD-14 — `explain` (explicabilidad unificada: scorecard WoE·β + SHAP + reason codes)

| Campo | Valor |
|---|---|
| **SDD** | 14 |
| **Módulo** | `nikodym.explain` |
| **Dominio** | Machine Learning / explicabilidad (unificada scorecard + challenger ML) |
| **Fase** | F2 |
| **Tanda de producción** | T3 (ML) |
| **Estado** | ✅ Implementado; API experimental |
| **Depende de** | SDD-01 (`core`), SDD-05 (convenciones + config), **SDD-12 (`ml`)**; **reúsa** SDD-06 (`binning`, features/tablas WoE); **opcionalmente** SDD-08 (`model`) + SDD-09 (`scorecard`) para la mitad scorecard; SDD-07 (`selection`) condicional (fuente de features heredada de `ml`) |
| **Lo consumen** | SDD-26 (`report`, comparativa scorecard-vs-ML + SHAP summary + reason codes); SDD-22 (`validation`, estabilidad de explicaciones — consumo opcional, no dura) |
| **Autor / Fecha** | DanIA (worker A15, redacción SDD-14 para T3 — cierre de F2) / 2026-07-04 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `explain` es la **capa de explicabilidad unificada** de Nikodym: descompone la predicción de riesgo en **contribuciones por atributo** para (a) el **scorecard logístico** de F1 (contribución exacta y analítica, `puntos = WoE·β`) y (b) el **challenger ML** de SDD-12 vía **SHAP**, y produce **reason codes** (top-N drivers de la PD con dirección y magnitud, en un formato regulatoriamente defendible) más una **comparativa scorecard-vs-ML** pensada para el reporte SDD-26. Cierra la fase F2 (Machine Learning).

**Responsabilidad única (qué SÍ hace).**
- Explica el **scorecard logístico** (campeón) de forma **exacta y determinista**: la contribución de cada atributo al log-odds es `β_j·(WoE_ij − baseline_j)`, equivalente a los `puntos` de SDD-09; **no** necesita SHAP ni muestreo (es álgebra cerrada). Consume la tabla de scorecard (SDD-09) y los coeficientes (SDD-08); **no** los recalcula.
- Explica el **challenger ML** (SDD-12) vía **SHAP**, **seleccionando el explainer por backend** (TreeExplainer para GBDT/RF, LinearExplainer para modelos lineales, KernelExplainer como fallback model-agnóstico). Consume el `estimator` fiteado por SDD-12 por su **API sklearn-like** (`predict_proba`/`predict_pd`, `get_params`/`set_params`, `from_config`); **no** reentrena ni reimplementa el wrapper.
- Produce **valores SHAP globales** (importancia media |SHAP| por feature, con dirección) y **locales** (contribución por observación) sobre un scope configurable, y expone el explainer para **explicar cualquier fila on-demand**.
- Traduce las contribuciones (SHAP del ML o analíticas del scorecard) a **reason codes**: para cada observación, los **top-N drivers** que empujan la PD, con **dirección** (sube/baja la PD) y **magnitud**, en un formato de "factores principales" defendible ante auditoría (ver §3 y FALTA-DATO-EXP-1 sobre la norma de jurisdicción).
- Emite una **comparativa scorecard-vs-ML**: solapamiento y acuerdo de ranking entre los drivers del campeón (por `|β·WoE|`/IV) y los del challenger (por media |SHAP|), para que SDD-26 muestre "qué explica cada modelo" (ESPECIFICACIONES.md:L121).
- Publica artefactos namespaced bajo `"explain"`: SHAP global/local, reason codes, contribuciones del scorecard, comparativa, metadata del explainer, resultado y card CT-2 (SHAP summary como `metric_sections`).
- Aporta `ExplainConfig` como sección **computacional** de `NikodymConfig`; por tanto, cambios de explainer, tamaño de background, N de reason codes o unidad de contribución mueven el `config_hash`.
- Registra con `log_decision` el explainer elegido por modelo, la semilla derivada, el tamaño y la fuente del background, la unidad de contribución, la política de reason codes y cada gate de reproducibilidad/determinismo.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No entrena, tunea ni compara modelos por performance.** El challenger, su PD y la comparación cabeza-a-cabeza de **discriminación/estabilidad** son SDD-12 (`ml`); el tuning es SDD-13; `explain` explica modelos **ya ajustados**. La "comparativa" de `explain` es de **drivers/atribución**, no de AUC/Gini/PSI (esas viven en `ml.comparison`).
- **No reimplementa SHAP ni el algoritmo de Shapley.** Toda atribución del ML sale de la librería `shap` (TreeExplainer/LinearExplainer/KernelExplainer); `explain` la orquesta, normaliza y traduce a reason codes, pero no recodifica el cálculo de valores de Shapley (test AST anti-reimplementación, §11).
- **No recalcula el scorecard ni las tablas WoE.** Los `puntos`/`β`/WoE vienen de SDD-09/08/06; `explain` los lee y los descompone; su mitad scorecard es álgebra sobre esos artefactos.
- **No ejecuta tests formales de validación ni calibración.** Hosmer-Lemeshow, Brier, traffic-light, backtesting son SDD-22; discriminación/estabilidad son SDD-11; calibración es SDD-10. `explain` no duplica performance/calibration/validation.
- **No decide adopción del challenger ni umbrales de gobierno.** Qué driver "justifica" una acción es del comité de modelos; `explain` reporta atribuciones, no dictamina.
- **No explica LGD/EAD en v1.** La abstracción se diseña **target-agnóstica** (reusable para LGD/EAD en F4), pero v1 solo cablea **PD/binario** (mismo alcance scoring-first que `ml`/`tuning`).
- **No hace narrativa en lenguaje natural.** La capa IA opcional (SDD-26 §report, extra `[ai]`) narra/documenta a partir de estos artefactos, **nunca calcula**; `explain` le entrega estructura, no prosa.
- **No usa `eval` ni expresiones ejecutables de usuario.** La config es Pydantic tipada; el mapeo de features es declarativo.
- **No trae la capa de datos longitudinal (CT-3).** Opera sobre el **panel transversal de scorecard** (SDD-02); IFRS 9/forward traen su propio panel.
- **No promete SHAP byte-a-byte con explainers muestrales multihilo.** KernelExplainer/PermutationExplainer con background muestreado y `n_threads>1` no son 100% deterministas; v1 default a explainers **exactos** (Tree/Linear, sin muestreo) y, cuando se cae a Kernel, **single-thread + background seedeado**, marcando los otros modos como no byte-reproducibles.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Machine Learning (F2/T3), **inmediatamente después** de `ml` (y, si corre, de `tuning`): `explain` es el **último paso de F2**, cuando ya existen el challenger fiteado y —opcionalmente— el scorecard campeón (ROADMAP.md:L64-L72; DoD "SHAP integrado al reporte", "tests de determinismo", ROADMAP.md:L71).
- **Quién lo invoca:** `Study.run()` como sección `explain` de `NikodymConfig`, o API programática `UnifiedExplainer.from_config(...)` + `ExplainStep`.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `SeedManager`, excepciones, lineage); `ml` (`MLChallenger`, `backend_metadata` — API sklearn-like, para seleccionar el explainer y predecir); `binning`/`selection` (features WoE, tablas para el nombre y el bin del atributo); **opcionalmente** `model` (`coefficients`) y `scorecard` (`scorecard`) para la mitad scorecard.
- **Quién lo consume aguas abajo:** SDD-26 (`report`) renderiza el SHAP summary, los reason codes y la comparativa scorecard-vs-ML (ESPECIFICACIONES.md:L245, L121); SDD-22 (`validation`) puede consumir la estabilidad de las explicaciones (consumo **opcional**, no dependencia dura).

```text
                    lee ml.backend_metadata (backend → elige explainer)
                                     │
data.labels + data.splits ─┐        ▼
binning.woe_frame ─────────┼──► explain ──► explain.shap_global  (importancia media |SHAP|)
ml.estimator ──────────────┤       │      ├─► explain.shap_local   (SHAP por observación, scope config)
ml.pd_frame ───────────────┘       │      ├─► explain.reason_codes (top-N drivers PD, dirección+magnitud)
  (OPCIONAL, mitad scorecard):     │      ├─► explain.scorecard_contributions (β·WoE analítico; None si ausente)
model.coefficients ────────┐       │      ├─► explain.comparison   (scorecard-vs-ML: solape de drivers)
scorecard.scorecard ───────┼──►    │      └─► explain.card (CT-2: SHAP summary + figuras)
binning.tables ────────────┘       ▼
                        SHAP vía librería `shap` (NUNCA reimplementado); scorecard = álgebra exacta
```

**Anclaje normativo/metodológico interno.**
- ESPECIFICACIONES §5.3: "**SHAP + reason codes** (sustituyen a la scorecard en modelos no lineales)" y la nota "scorecard (interpretable, regulatoria) y SHAP (post-hoc) **no son intercambiables 1:1**" (ESPECIFICACIONES.md:L119-L121).
- ESPECIFICACIONES §6.3 ubica el paquete `explain/` en el árbol con el comentario "**scorecard (WoE+β) y SHAP + reason codes**" — es decir, explicabilidad **unificada** de ambos mundos (ESPECIFICACIONES.md:L192).
- ESPECIFICACIONES §8 lista "**Reason codes / SHAP según modelo**" como artefacto de salida (ESPECIFICACIONES.md:L245) y `shap` (MIT) en el stack de explicabilidad (ESPECIFICACIONES.md:L224).
- ROADMAP F2: objetivo "modelos ML como benchmark **con explicabilidad**"; entregable "**SHAP + reason codes; comparativa scorecard vs ML en el reporte**"; DoD "**SHAP integrado al reporte; tests de determinismo**" (ROADMAP.md:L64-L72).
- Principio 9 (núcleo liviano): `shap` tras extra opcional con import perezoso; `core` no lo arrastra.
- CT-1 exige `requires`/`provides`; CT-2 exige card estructurada aditiva (`metric_sections`); CT-3 mantiene el panel transversal.

**Interacción con `Study` y config declarativo.** `ExplainStep` es un `Step` nativo registrado con `@register("standard", domain="explain")`. Se construye desde `ExplainConfig`; sus `requires` son **dinámicos** según `targets` y la `feature_source` **heredada de `NikodymConfig.ml`** (no se duplica):
- siempre requiere `("data","labels")` y `("data","splits")`;
- si `targets ∈ {"ml","both"}` (default `"both"`): requiere `("ml","estimator")`, `("ml","backend_metadata")`, `("ml","pd_frame")` y la fuente de features de `ml.feature_source` (`("binning","woe_frame")` por default; `("selection","selected_woe_frame")`+`("selection","selected_woe_columns")` si `selection_woe`);
- si `targets == "scorecard"` (solo scorecard, sin challenger): requiere `("model","coefficients")`, `("scorecard","scorecard")`, `("binning","tables")` y la fuente de features; **no** requiere `("ml",…)`;
- si `targets == "both"`: la mitad scorecard (`model.coefficients`/`scorecard.scorecard`/`binning.tables`) es **best-effort**, **no** entra a `requires` (no es gate duro): si está presente se explica, si falta se degrada a ML con `log_decision` (`explain_scorecard_skipped`). Así una corrida ML-only no falla por no tener scorecard.

Esto cumple CT-1: `ExplainStep` expone su DAG efectivo antes de ejecutar; el motor v1 valida prerequisitos; el scheduler topológico sigue diferido a F5 por CT-1.

**Cableado implementado en `core.study`.**
- `_DOMAIN_MODULES["explain"] = "nikodym.explain"`;
- `_DOMAIN_CONFIG_CLASSES["explain"] = ("nikodym.explain.config", "ExplainConfig")`;
- `_DEFAULT_DOMAIN_ORDER` ubica `"explain"` **después** de `"ml"` (y de `"scorecard"`), de modo que existan el challenger fiteado y —si aplica— el scorecard cuando `explain` ejecute; el orden real efectivo lo resuelve CT-1 por `requires`, no por suposición lineal;
- mientras el scheduler topológico no exista, el usuario debe declarar `ml` (y, para la mitad scorecard, `model`+`scorecard`) antes de `explain`.

**Paquete físico y troceo B14.x.**

```text
src/nikodym/explain/
  __init__.py
  config.py
  exceptions.py
  results.py
  explainers.py      # factory: resolve_explainer(backend/kind) → SHAP explainer + decomposición lineal exacta
  reason_codes.py    # contribuciones (SHAP o analíticas) → reason codes regulatorios (top-N, dirección, magnitud)
  engine.py          # UnifiedExplainer (mitad scorecard analítica + mitad ML SHAP); orquesta explainers + reason_codes
  step.py
```

**B14.1 — `config.py` + `exceptions.py`.** `ExplainConfig`, sub-schemas (explainer, reason codes, scope local, scorecard), jerarquía de errores, hook diferido `_EXPLAIN_CONFIG_CLS` en `NikodymConfig`, round-trip YAML, defaults D-EXP y validaciones sin imports pesados. Aquí se **mueve** `GOLDEN_DEFAULT_CONFIG_HASH` (ver §5).
**B14.2 — `explainers.py` + `results.py`.** Factory `resolve_explainer` (selección por backend, import perezoso de `shap`) + descomposición lineal exacta del scorecard; DTOs frozen (SHAP global/local, reason codes, contribuciones scorecard, comparativa, card CT-2). Sin imports de `shap`/`matplotlib` en top-level.
**B14.3 — `reason_codes.py` + `engine.py`.** Traducción de contribuciones a reason codes (dirección/magnitud/orden estable); `UnifiedExplainer` que orquesta la mitad scorecard (analítica) y la mitad ML (SHAP), reúsa `MLChallenger` (SDD-12), normaliza numéricamente y arma la comparativa. Import perezoso de `shap`/`pandas`/`numpy`.
**B14.4 — `step.py` + cableado + `__init__.py`.** `ExplainStep`, `@register(domain="explain")`, CT-1 dinámico (hereda `feature_source` de `ml`; scorecard best-effort), `int_seed_for("explain")`, publicación de artefactos, audit trail, hook `importlib`, import guards y prueba end-to-end `Study` (`explain` después de `ml`).

## 3. Conceptos y fundamentos

**Fuente normativa/metodológica interna.**
- ESPECIFICACIONES §5.3 (SHAP + reason codes; no intercambiables 1:1; ESPECIFICACIONES.md:L119-L121), §6.3 (paquete `explain/`: scorecard WoE+β y SHAP; L192), §7 (`shap` MIT; L224), §8 (reason codes/SHAP como artefacto; L245).
- ROADMAP F2 objetivo/entregables/DoD (ROADMAP.md:L64-L72).
- CT-1/CT-2/CT-3 (`_CONTRATOS-TRANSVERSALES.md`).
- SDD-12 §4 (API sklearn-like de `MLChallenger`), §9 (determinismo, `int_seed_for`); SDD-09 §7 (fórmula de puntos `puntos_{j,b} = Offset/n − Factor·(β_j·WoE_{j,b} + α/n)`); SDD-08 §4 (`coefficients` con `β`); SDD-06 §3 (convención WoE).

**Explicabilidad = atribución aditiva de la predicción.** Un modelo de PD `f(x)` se explica descomponiendo cada predicción en una **contribución por feature** que suma la salida: `f(x) = φ_0 + Σ_j φ_j(x)`, donde `φ_0` es un **valor base** (expectativa sobre una población de referencia) y `φ_j` es cuánto empuja la feature `j` la predicción de `x` respecto de esa base. Es el marco de los **valores de Shapley** (SHAP), que reparten la predicción entre features con axiomas de eficiencia, simetría y aditividad.

**Dos mundos, un contrato.**
- **Scorecard logístico (campeón, F1).** Es **lineal en el espacio WoE**: `η_i = α + Σ_j β_j·WoE_ij` (SDD-09 §7). La atribución de Shapley de un modelo lineal es **cerrada y exacta**: `φ_j(x_i) = β_j·(WoE_ij − E[WoE_j])`, con `φ_0 = α + Σ_j β_j·E[WoE_j]`. **No requiere muestreo**: es álgebra sobre `β` (SDD-08) y las tablas WoE (SDD-06), y es **idéntica** (salvo la escala de negocio `Factor`/`Offset`) a los `puntos` de SDD-09. Por eso `explain` calcula la mitad scorecard **analíticamente** (determinista, sin `shap`); `shap.LinearExplainer` sería el equivalente numérico y se ofrece como verificación cruzada.
- **Challenger ML (SDD-12).** Es no lineal (GBDT/RF/SVM). La atribución **no es cerrada**: se calcula con `shap`, eligiendo el explainer que la librería recomienda por tipo de modelo (§D-EXP-1). Aquí SHAP "**sustituye a la scorecard**" como forma de interpretar el modelo (ESPECIFICACIONES.md:L119).

**Selección de explainer por backend (D-EXP-1, default defendible, configurable).**

| Modelo / backend | Explainer SHAP | Exactitud | Determinismo | Semilla |
|---|---|---|---|---|
| scorecard logístico (WoE·β) | **analítico** (≡ LinearExplainer) | exacto (cerrado) | total | no usa |
| `xgboost` / `lightgbm` / `catboost` | **TreeExplainer** (`tree_path_dependent`) | exacto para el árbol | total (sin muestreo) | no usa |
| `random_forest` | **TreeExplainer** | exacto para el bosque | total | no usa |
| `svm` kernel lineal | **LinearExplainer** | exacto | total | no usa |
| `svm` kernel `rbf` / no soportado | **KernelExplainer** (fallback) | aproximado (muestral) | condicionado a seed+single-thread | `int_seed_for("explain")` |

`explainer.ml_explainer="auto"` (default) resuelve la fila según `ml.backend`/`backend_metadata`; el usuario puede forzar `"tree"`/`"linear"`/`"kernel"`, con validación de compatibilidad (§5). **TreeExplainer y LinearExplainer son exactos y sin muestreo → byte-reproducibles independientemente del threading**; solo el fallback KernelExplainer introduce estocasticidad (elección del background y `nsamples`), que se controla con la semilla.

**Reason codes.** Un **reason code** es un **driver principal** de la predicción para una observación, expresado como `(rank, feature, dirección, magnitud)`, donde la dirección indica si la feature **sube** (`increases_pd`, adverso) o **baja** (`decreases_pd`, protector) la PD respecto de la base, y la magnitud es la contribución (`|φ_j|`). Se obtienen ordenando las contribuciones (SHAP del ML o `β·WoE` del scorecard) por magnitud y tomando los **top-N**. Es el mismo objeto para ambos mundos: por eso el contrato de reason codes es **común** (scorecard y ML producen `ReasonCode` con la misma forma), habilitando la comparativa.

> **Marco regulatorio y honestidad de fuente (FALTA-DATO-EXP-1).** El concepto de "reason codes / adverse action key factors" está **codificado como norma en EE. UU.** (ECOA / Regulation B y FCRA exigen comunicar los "principal reasons"/"key factors" de una decisión de crédito adversa, típicamente hasta ~4-5 factores). En **Chile / CMF no existe una norma que mande un formato o un número fijo de reason codes** para scoring; la buena práctica de gobierno de modelos (SR 11-7 / transparencia) sí pide poder explicar cada decisión. Por eso `explain` **no hardcodea** un número normativo: entrega `top_n` **configurable** (default `5`, alineado con la convención ECOA/FCRA como referencia, no como norma chilena) y documenta que el formato/umbral exacto de la jurisdicción es dato del usuario. **No se inventa una norma CMF de reason codes.**

**Unidad de contribución (D-EXP-4).** SHAP puede explicar la **salida cruda / margen** (log-odds, aditiva) o la **probabilidad** (`predict_proba`, no aditiva de forma simple). Default: **log-odds (margen)** — es la escala en la que el scorecard es aditivo (`η = α + Σβ·WoE`), de modo que **scorecard y ML quedan en la misma unidad** y la comparativa es limpia; además la aditividad exacta permite el *additivity check* de SHAP. Alternativa `"probability"` disponible para interpretabilidad directa (∆PD), marcada como no perfectamente aditiva.

**Baseline / población de referencia (D-EXP-7, D-EXP-2).** Las contribuciones son relativas a una **base**: para el scorecard, `baseline_j = E[WoE_j]` (media poblacional, default) o `WoE=0` (bin neutro); para SHAP, el **background** — la población sobre la que se calcula `φ_0`. TreeExplainer `tree_path_dependent` **no necesita background** (usa la distribución de los caminos del árbol → determinista); `interventional` y KernelExplainer sí usan un background, que se **muestrea de `desarrollo`** (`background_size`, default `100`, **seedeado**). Se usa `desarrollo` (nunca `holdout`/`oot` como referencia, para no filtrar información de evaluación en la explicación).

**Comparativa scorecard-vs-ML (drivers).** No es una comparación de performance (eso es `ml.comparison`). Es de **atribución**: se rankean las features del campeón por importancia (`|β·E[WoE]|` o IV de `binning.summary`) y las del challenger por media |SHAP|, y se reporta el **solapamiento de top-K** y una medida de acuerdo de ranking (p. ej. cuántos drivers top-K comparten). Responde: **¿el ML apoya su decisión en las mismas variables que el scorecard, o en otras?** (input directo del reporte SDD-26).

**Notación.**
- `X_p`, `y_p`: features WoE y target binario de la partición `p`.
- `φ_j(x_i)`: contribución (SHAP o analítica) de la feature `j` a la predicción de la observación `i`.
- `φ_0`: valor base (expectativa del modelo sobre el background/población de referencia).
- `Φ_j = mean_i |φ_j(x_i)|`: importancia global de la feature `j`.
- `RC_i = top_N_j |φ_j(x_i)|`: reason codes de la observación `i`.

**Frameworks conceptuales.** No se embeben umbrales de "qué contribución es material" ni un número normativo de reason codes: `explain` reporta las contribuciones y los top-N; la política de comunicación (cuántos factores, con qué texto) es del usuario/jurisdicción (FALTA-DATO-EXP-1).

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/explain/exceptions.py
class ExplainError(NikodymError): ...
class ExplainConfigError(ExplainError): ...
class ExplainDataError(ExplainError): ...
class ExplainBackendError(ExplainError): ...          # explainer no construible / incompatible
class ExplainExplainerError(ExplainBackendError): ...  # fallo del cálculo SHAP (additivity, etc.)
class ExplainReasonCodeError(ExplainError): ...
class ExplainDeterminismError(ExplainError): ...
```

`MissingDependencyError` (de `core`) se levanta cuando falta el extra `[explain]` (shap); no es una excepción propia de `explain`.

```python
# nikodym/explain/explainers.py
ExplainerKind = Literal["analytic_linear", "tree", "linear", "kernel"]

@runtime_checkable
class ContributionExplainer(Protocol):
    kind: ExplainerKind
    is_exact: bool
    needs_background: bool
    def base_value(self) -> float: ...                      # φ_0 en la unidad de contribución
    def contributions(self, X) -> "numpy.ndarray": ...      # matriz (n_obs, n_features) de φ_j
    def shap_version(self) -> "str | None": ...             # None para analytic_linear

# Explicador exacto del scorecard (sin shap): φ_j = β_j·(WoE_ij − baseline_j)
class AnalyticLinearExplainer(ContributionExplainer): ...

# Envoltorios perezosos sobre la librería `shap` (import dentro del método):
class TreeShapExplainer(ContributionExplainer): ...
class LinearShapExplainer(ContributionExplainer): ...
class KernelShapExplainer(ContributionExplainer): ...

def resolve_explainer(
    *, backend: "str | None", model_kind: Literal["scorecard", "ml"],
    forced: "ExplainerKind | None", supports_tree: bool,
) -> ContributionExplainer: ...   # factory; no importa shap para el scorecard analítico
```

```python
# nikodym/explain/reason_codes.py
def build_reason_codes(
    contributions: "numpy.ndarray", feature_names: "tuple[str, ...]", *,
    top_n: int, adverse_direction: Literal["increases_pd"],
    include_protective: bool, min_abs_contribution: float,
) -> "tuple[tuple[ReasonCode, ...], ...]": ...   # una tupla de reason codes por observación
```

```python
# nikodym/explain/engine.py
class UnifiedExplainer(BaseNikodymEstimator):
    config_cls: ClassVar[type[ExplainConfig]] = ExplainConfig

    @classmethod
    def from_config(cls, cfg: ExplainConfig) -> "UnifiedExplainer": ...

    def explain_ml(
        self, estimator: "MLChallenger", X: "pandas.DataFrame", *,
        background: "pandas.DataFrame | None" = None, seed: int,
        audit: "AuditSink | None" = None,
    ) -> "ExplanationBundle": ...          # SHAP global/local + reason codes del challenger

    def explain_scorecard(
        self, coefficients: "pandas.DataFrame", woe_tables: object,
        X_woe: "pandas.DataFrame", *, audit: "AuditSink | None" = None,
    ) -> "ExplanationBundle": ...          # contribuciones β·WoE analíticas + reason codes

    def compare_drivers(
        self, scorecard_bundle: "ExplanationBundle | None",
        ml_bundle: "ExplanationBundle", *, top_k: int,
    ) -> "tuple[DriverComparisonRecord, ...]": ...
```

**Atributos fiteados (convención `_`).** `explainer_kind_` (por modelo), `base_value_`, `shap_version_`, `background_size_`, `feature_names_in_`, `contribution_space_`, `seed_`, `deterministic_`.

```python
# nikodym/explain/results.py
class ShapGlobalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    feature: str
    mean_abs_contribution: float          # Φ_j (≥ 0)
    mean_signed_contribution: float       # dirección global (signo)
    rank: int
    source_model: Literal["scorecard", "ml"]

class ReasonCode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    rank: int
    feature: str
    direction: Literal["increases_pd", "decreases_pd"]
    contribution: float                   # φ_j en la unidad de contribución (log-odds por default)
    bin_label: str | None = None          # bin/atributo (si la fuente WoE lo aporta)

class LocalExplanationRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    row_key: str                          # índice pandas serializado (identidad de la observación)
    partition: str
    base_value: float                     # φ_0
    prediction: float                     # f(x) en la unidad de contribución
    pd_hat: float                         # PD en [0,1] (para contexto)
    reason_codes: tuple[ReasonCode, ...]

class DriverComparisonRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    feature: str
    scorecard_rank: int | None            # None si la feature no está en el campeón
    ml_rank: int | None
    in_scorecard_topk: bool
    in_ml_topk: bool
    agreement: Literal["both", "scorecard_only", "ml_only"]

class ExplainerMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ml_explainer_kind: str | None          # tree/linear/kernel; None si targets="scorecard"
    scorecard_explained: bool
    shap_version: str | None
    contribution_space: Literal["log_odds", "probability"]
    background_size: int | None
    seed: int
    deterministic: bool
    top_n_reason_codes: int

class ExplainCardSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    summary: dict[str, str | int | float | bool]
    metric_sections: dict[str, object] = Field(default_factory=dict)   # CT-2: SHAP summary + dependence + comparativa
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

class ExplainResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    shap_global: tuple[ShapGlobalRecord, ...]                     # ML (y/o scorecard) importancia global
    shap_local: tuple[LocalExplanationRecord, ...]               # scope configurable (muestra/partición/todo)
    reason_codes: tuple[LocalExplanationRecord, ...]             # vista de reason codes (≡ shap_local con top-N)
    scorecard_contributions: "pandas.DataFrame | None"          # β·WoE por atributo; None si scorecard ausente
    comparison: tuple[DriverComparisonRecord, ...]
    explainer_metadata: ExplainerMetadata
    card: ExplainCardSection
    def term_structure(self) -> "pandas.DataFrame | None": ...   # CT-2: None (explain no es multi-período)
    def global_frame(self) -> "pandas.DataFrame": ...            # tidy de ShapGlobalRecord
    def reason_codes_frame(self) -> "pandas.DataFrame": ...      # tidy explotado de reason codes
```

```python
# nikodym/explain/step.py
@register("standard", domain="explain")
class ExplainStep(AuditableMixin):
    name: str = "explain"
    requires: tuple[ArtifactKey, ...]     # dinámico según targets / ml.feature_source (§2)
    provides: tuple[ArtifactKey, ...] = (
        ("explain", "shap_global"),
        ("explain", "shap_local"),
        ("explain", "reason_codes"),
        ("explain", "scorecard_contributions"),
        ("explain", "comparison"),
        ("explain", "result"),
        ("explain", "card"),
    )
    @classmethod
    def from_config(cls, cfg: ExplainConfig) -> "ExplainStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "ExplainResult": ...
```

**Artefactos que `ExplainStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"shap_global"` | `tuple[ShapGlobalRecord, ...]` | importancia global por feature (media |SHAP| del ML; y del scorecard si aplica) |
| `"shap_local"` | `tuple[LocalExplanationRecord, ...]` | contribución por observación (scope configurable) |
| `"reason_codes"` | `tuple[LocalExplanationRecord, ...]` | reason codes top-N por observación (dirección + magnitud) |
| `"scorecard_contributions"` | `pandas.DataFrame` \| `None` | contribuciones analíticas `β·WoE` por atributo/bin; `None` si no hay scorecard |
| `"comparison"` | `tuple[DriverComparisonRecord, ...]` | solape de drivers scorecard-vs-ML |
| `"result"` | `ExplainResult` | contenedor agregado |
| `"card"` | `ExplainCardSection` | resumen governance/report con `metric_sections` CT-2 |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning", "selection", "model", "scorecard",
                 "calibration", "tuning", "ml", "explain"])   # explain CIERRA F2
result = study.artifacts.get("explain", "result")
top_drivers = result.global_frame()                 # features por media |SHAP|
rc = result.reason_codes_frame()                    # reason codes explotados (obs × factor)
cmp = result.comparison                             # ¿ML usa las mismas variables que el scorecard?

# API programática (explicar una fila on-demand):
explainer = UnifiedExplainer.from_config(cfg.explain)
bundle = explainer.explain_ml(
    ml_challenger, X_oot, seed=study.seed_manager.int_seed_for("explain")
)
one = explainer.explain_ml(ml_challenger, X_oot.loc[[cliente_id]],
                           seed=study.seed_manager.int_seed_for("explain"))
```

## 5. Configuración (schema Pydantic)

`ExplainConfig` es el sub-config de la sección `explain` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, `Literal` para categóricos, rangos explícitos, defaults defendibles y metadata UI. **`explain ∉ INFRA_SECTIONS`**: todo cambio computacional mueve `config_hash`.

**Impacto en `GOLDEN_DEFAULT_CONFIG_HASH` (verificado contra `core/config/hashing.py`).** `config_hash()` serializa `cfg.model_dump(mode="json", by_alias=True, exclude=INFRA_SECTIONS)` **sin** `exclude_none`, e `INFRA_SECTIONS = {"name","governance","audit","tracking","report"}` (`core/config/hashing.py:L24`) **no incluye `explain`**. Las secciones computacionales en `None` **sí entran** al payload canónico (mismo precedente que `ml`/`tuning`/`validation`/`stress`). Por tanto, **añadir el campo `explain` (default `None`) a `NikodymConfig` agrega la clave `"explain":null` al JSON canónico y MUEVE `GOLDEN_DEFAULT_CONFIG_HASH`**. Esto es **esperado** al codificar B14.1: se recalcula y actualiza el golden en los tests de config, igual que hicieron `ml`/`tuning`/`validation`/`survival`/`stress`. En este ítem solo-docs **no** se mueve ningún hash ni se toca código.

```python
# nikodym/explain/config.py
ExplainTargets = Literal["both", "ml", "scorecard"]
MLExplainerChoice = Literal["auto", "tree", "linear", "kernel"]
TreePerturbation = Literal["tree_path_dependent", "interventional"]
ContributionSpace = Literal["log_odds", "probability"]
ScorecardBaseline = Literal["population_mean", "neutral_zero"]
LocalScope = Literal["sample", "partition", "all", "none"]

class MLExplainerConfig(NikodymBaseConfig):
    ml_explainer: MLExplainerChoice = "auto"          # auto ⇒ resuelto por backend (D-EXP-1)
    feature_perturbation: TreePerturbation = "tree_path_dependent"  # exacto sin background
    background_size: int = Field(default=100, ge=1, le=100_000)     # solo si needs_background
    background_partition: str = "desarrollo"          # nunca holdout/oot como referencia
    check_additivity: bool = True                     # gate de SHAP (Σφ + φ0 ≈ f(x))
    nsamples: int | Literal["auto"] = "auto"          # KernelExplainer

class ReasonCodesConfig(NikodymBaseConfig):
    top_n: int = Field(default=5, ge=1, le=50)        # D-EXP-3 (referencia ECOA/FCRA, no norma CMF)
    include_protective: bool = False                  # solo drivers adversos (suben PD) por default
    min_abs_contribution: float = Field(default=0.0, ge=0.0)
    adverse_direction: Literal["increases_pd"] = "increases_pd"

class LocalScopeConfig(NikodymBaseConfig):
    strategy: LocalScope = "sample"                   # muestra representativa (no toda la base: pesa)
    sample_size: int = Field(default=200, ge=1, le=1_000_000)
    partition: str = "holdout"                        # partición de la que se toma la muestra local
    top_by_pd: bool = False                           # si True, prioriza las PD más altas en la muestra

class ScorecardExplainConfig(NikodymBaseConfig):
    baseline: ScorecardBaseline = "population_mean"   # E[WoE] (default) o WoE=0
    baseline_partition: str = "desarrollo"

class ExplainOutputConfig(NikodymBaseConfig):
    publish_local: bool = True
    top_k_global: int = Field(default=30, ge=1)
    top_k_comparison: int = Field(default=15, ge=1)
    emit_figures: bool = True                         # SHAP summary/dependence al card (matplotlib perezoso)

class ExplainConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"
    schema_version: str = "1.0.0"
    targets: ExplainTargets = "both"
    explainer: MLExplainerConfig = Field(default_factory=MLExplainerConfig)
    contribution_space: ContributionSpace = "log_odds"
    reason_codes: ReasonCodesConfig = Field(default_factory=ReasonCodesConfig)
    local_scope: LocalScopeConfig = Field(default_factory=LocalScopeConfig)
    scorecard: ScorecardExplainConfig = Field(default_factory=ScorecardExplainConfig)
    output: ExplainOutputConfig = Field(default_factory=ExplainOutputConfig)
    deterministic: bool = True
    n_threads: int = Field(default=1, ge=1, le=256)
    target_column: str = "target"
    partition_column: str = "partition"
    pd_hat_column: str = "pd_hat"
```

**Herencia desde `ml` (no duplicar).** `ExplainConfig` **no** declara `backend`, `feature_source` ni columnas de features: las **lee de `NikodymConfig.ml`** en runtime (para resolver el explainer y las mismas features WoE que consumió el challenger). Si `targets ∈ {"ml","both"}` y `NikodymConfig.ml is None` ⇒ `ExplainConfigError` (no hay challenger que explicar). Si `targets="scorecard"`, `ml` puede ser `None` (solo se explica el campeón).

**Validaciones de config.**
- `explainer.ml_explainer="tree"` con backend no arbóreo (`svm`) ⇒ `ExplainConfigError` (TreeExplainer exige modelo de árboles).
- `explainer.ml_explainer="linear"` con backend no lineal (GBDT/RF/`svm` rbf) ⇒ `ExplainConfigError`.
- `deterministic=True` con `n_threads>1` **y** explainer efectivo muestral (Kernel) ⇒ `ExplainConfigError` (o coacción a `n_threads=1` con warning, D-EXP-det). Con explainers exactos (Tree/Linear) el threading no rompe determinismo y no se restringe.
- `targets="scorecard"` sin `("scorecard","scorecard")`/`("model","coefficients")` en el DAG ⇒ falla la validación pre-run CT-1 con el contrato incumplido.
- `reason_codes.top_n` mayor que el nº de features ⇒ se acota al nº de features con `log_decision` (no es error).
- `local_scope.strategy="partition"`/`"sample"` exige que `local_scope.partition` sea una partición conocida; `"all"` explica todas las filas modelables (advertencia de costo si es grande).
- `contribution_space="probability"` ⇒ se documenta que la aditividad exacta no se garantiza; el *additivity check* se relaja a la escala de probabilidad.
- `explainer.background_partition`/`scorecard.baseline_partition` deben ser `desarrollo` u otra partición **no** de evaluación pura; usar `holdout`/`oot` como referencia emite `log_decision` de caveat (fuga de referencia).

**Campos, defaults y sentido.**
- `targets`: default D-EXP-target `"both"` (explica scorecard **y** ML si ambos existen; degrada a `ml` si falta el scorecard, §2).
- `explainer.ml_explainer`: default D-EXP-1 `"auto"` (Tree para GBDT/RF, Linear para lineales, Kernel fallback).
- `explainer.feature_perturbation`: default D-EXP-9 `"tree_path_dependent"` (exacto para el árbol, sin background, determinista); `"interventional"` disponible (semántica causal, requiere background).
- `contribution_space`: default D-EXP-4 `"log_odds"` (aditivo, misma unidad que el scorecard; habilita additivity check y comparativa limpia).
- `reason_codes.top_n`: default D-EXP-3 `5` (referencia ECOA/FCRA "key factors"; **no** norma CMF — FALTA-DATO-EXP-1). **A confirmar por Cami** el N y si se comunican también los protectores.
- `local_scope`: default D-EXP-6 `"sample"`/`200` sobre `holdout` (evita materializar SHAP de toda la base; el explainer queda disponible on-demand).
- `scorecard.baseline`: default D-EXP-7 `"population_mean"` (`E[WoE]`, coincide con LinearExplainer interventional); `"neutral_zero"` (`WoE=0`) disponible.
- `explainer.background_size`: default D-EXP-2 `100`, muestreado de `desarrollo`, seedeado (solo relevante para Kernel/interventional).
- `deterministic`/`n_threads`: default D-EXP-det `True`/`1` (byte-reproducibilidad y golden; solo el fallback Kernel lo necesita).

**Round-trip YAML y UI.** Sigue SDD-05: dump JSON-mode, `sort_keys=False`, carga vía `load_config`. La UI (SDD-23) renderiza `targets` como selector, el explainer como selector con auto-resolución mostrada, `reason_codes.top_n` como número, el scope local como selector partición/muestra, y advierte cuando el modo efectivo es Kernel no byte-reproducible o cuando la referencia usa `holdout`/`oot`.

**Hook diferido en `core.config.schema`.**
- declarar `_EXPLAIN_CONFIG_CLS: type[BaseModel] | None = None` (junto a `_ML_CONFIG_CLS`/`_TUNING_CONFIG_CLS`);
- añadir `explain` como campo `Any` en runtime y `ExplainConfig | None` bajo `TYPE_CHECKING` (patrón idéntico a `ml`);
- añadir `@field_validator("explain", mode="before")` (`_valida_explain`) que coacciona vía el hook, con fallback a blob JSON-canónico si el hook no está cargado (patrón de `_valida_ml`);
- no importar `nikodym.explain` desde `core`;
- al importar `nikodym.explain`, poblar `_schema._EXPLAIN_CONFIG_CLS = ExplainConfig`;
- **actualizar `GOLDEN_DEFAULT_CONFIG_HASH`** en B14.1.

## 6. Contratos de datos (I/O)

**Input duro/condicional del Step según `targets`.**

| artefacto | requerido | contrato |
|---|---|---|
| `("data","labels")` | siempre | `LabeledFrame` de SDD-02; provee `target_col` |
| `("data","splits")` | siempre | `PartitionResult` de SDD-02; provee `partition_col` |
| `("ml","estimator")` | si `targets ∈ {ml,both}` | `MLChallenger` fiteado de SDD-12 |
| `("ml","backend_metadata")` | si `targets ∈ {ml,both}` | `MLBackendMetadata` (backend/versión → selección de explainer) |
| `("ml","pd_frame")` | si `targets ∈ {ml,both}` | PD del challenger: `partition`, `target`, `pd_hat` (contexto/alineación) |
| `("binning","woe_frame")` | si `ml.feature_source="binning_woe"` | features WoE a explicar (índice, `partition`, `target`, `<feature>__woe`) |
| `("selection","selected_woe_frame")`+`("selection","selected_woe_columns")` | si `ml.feature_source="selection_woe"` | subconjunto WoE + nombres |
| `("model","coefficients")` | si `targets="scorecard"` (duro) / best-effort si `both` | `β`, α por feature (SDD-08) |
| `("scorecard","scorecard")` | si `targets="scorecard"` (duro) / best-effort si `both` | tabla de puntos por atributo/bin (SDD-09) |
| `("binning","tables")` | si `targets="scorecard"` (duro) / best-effort si `both` | tablas WoE por feature (nombre/bin del atributo) |

Cada clave `requires` **existe como `provides`** en su SDD vecino (DAG cerrado): `data.labels`/`data.splits` (SDD-02), `binning.woe_frame`/`binning.tables` (SDD-06), `selection.*` (SDD-07), `ml.estimator`/`ml.backend_metadata`/`ml.pd_frame` (SDD-12), `model.coefficients` (SDD-08), `scorecard.scorecard` (SDD-09). La mitad scorecard bajo `targets="both"` es **best-effort** (no gate duro): se comprueba presencia en runtime y se degrada con `log_decision` si falta.

**Consumo del challenger sin reimplementarlo.** `explain` usa `MLChallenger` (SDD-12) por su API sklearn-like: `predict_proba`/`predict_pd` para el margen/PD, `feature_names_in_`/`classes_` para alinear columnas y clase positiva, y el `estimator_` nativo para pasarlo al explainer SHAP correspondiente. **No** reentrena, no toca hiperparámetros y no muta el estimador (copias defensivas del frame de features).

**Poblaciones.** El **background/baseline** se toma de `explainer.background_partition`/`scorecard.baseline_partition` (`desarrollo` por default). El **scope local** (qué observaciones se explican y publican) se toma de `local_scope` (`holdout` por default). `explain` **no muta** los frames de entrada.

**Output `explain.shap_global`.** `tuple[ShapGlobalRecord, ...]`; tidy (`global_frame()`): `feature`, `mean_abs_contribution`, `mean_signed_contribution`, `rank`, `source_model`. Incluye el ML siempre (si `targets ∈ {ml,both}`) y el scorecard si se explicó.

**Output `explain.shap_local` / `explain.reason_codes`.** `tuple[LocalExplanationRecord, ...]` sobre el scope local: `row_key` (índice serializado), `partition`, `base_value` (φ_0), `prediction` (f(x) en la unidad), `pd_hat`, `reason_codes` (top-N `ReasonCode`). `reason_codes` es la vista de `shap_local` filtrada/ordenada a los top-N drivers; el tidy `reason_codes_frame()` explota a `row_key`, `rank`, `feature`, `direction`, `contribution`, `bin_label`.

**Output `explain.scorecard_contributions`.** `DataFrame` (o `None` si no hay scorecard): una fila por atributo/bin con `feature`, `bin_label`, `woe`, `beta`, `contribution` (`β·(WoE − baseline)` en log-odds), `points` (referencia a SDD-09 para trazabilidad), `direction`. Es **exacto** y coincide, salvo escala, con los `puntos` de SDD-09 (test de consistencia, §11).

**Output `explain.comparison`.** `tuple[DriverComparisonRecord, ...]`: `feature`, `scorecard_rank`, `ml_rank`, `in_scorecard_topk`, `in_ml_topk`, `agreement` (`both`/`scorecard_only`/`ml_only`).

**Invariantes.**
- Todas las contribuciones son **finitas**: sin `NaN`/`inf`/`-inf`; `-0.0 → 0.0`. `pd_hat ∈ [0,1]`.
- **Aditividad** (si `contribution_space="log_odds"` y `check_additivity=True`): `φ_0 + Σ_j φ_j(x_i) ≈ f(x_i)` (margen) dentro de la tolerancia de SHAP; violarla ⇒ `ExplainExplainerError`.
- Las contribuciones del ML se calculan sobre las **mismas features** (mismas columnas y orden) que consumió el challenger (`estimator.feature_names_in_`); desalineación ⇒ `ExplainDataError`.
- **Orden estable**: `shap_global` desc por `mean_abs_contribution` con desempate lexicográfico por `feature`; `reason_codes` por `rank` (magnitud desc, desempate lexicográfico); `shap_local` en el orden del scope (índice de la fuente).
- No se mutan `data.*`, `binning.*`, `selection.*`, `ml.*`, `model.*`, `scorecard.*`.

**Nota de DAG aguas abajo.** SDD-26 (`report`) consume `explain.card`/`shap_global`/`reason_codes`/`comparison` para el reporte (SHAP summary + comparativa scorecard-vs-ML); es un consumo de **lectura**, no impone `requires` sobre `explain` en `report` más allá de lo que el reporte declare. SDD-22 (`validation`) **puede** consumir la estabilidad de las explicaciones (p. ej. drift de reason codes) como **rev. menor aditiva** si se decide en T6 (deuda **B-VAL-EXP**); no es dependencia dura de `explain`.

## 7. Algoritmos y flujo

**`ExplainStep.execute(study, rng)` — secuencia canónica.**
1. **Resolver config.** Leer `study.config.explain`; en API programática, exigir `ExplainConfig`. Leer `study.config.ml` (para backend/feature_source) si `targets ∈ {ml,both}`.
2. **Construir `requires`.** Desde `targets` y `ml.feature_source`; validar CT-1 antes de ejecutar (mitad scorecard best-effort bajo `both`).
3. **Derivar azar.** `seed = study.seed_manager.int_seed_for("explain")` (entropía compuesta `[root_seed, sha256("explain")]`; nunca `hash()` builtin sensible a `PYTHONHASHSEED`). El `rng` del contrato se usa para el muestreo del background/scope local (solo si el explainer lo necesita); con Tree/Linear exactos, `rng` no altera el resultado.
4. **Leer artefactos.** Copiar defensivamente features (`woe_frame`/`selected_woe_frame`), `labels`, `splits`; si `targets ∈ {ml,both}`, `ml.estimator`/`ml.backend_metadata`/`ml.pd_frame`; si mitad scorecard presente, `model.coefficients`/`scorecard.scorecard`/`binning.tables`.
5. **Mitad ML (si aplica).**
   a. Resolver explainer: `resolve_explainer(backend=ml.backend, model_kind="ml", forced=cfg.explainer.ml_explainer, supports_tree=backend∈{GBDT,RF})` (import perezoso de `shap`; si falta el extra ⇒ `MissingDependencyError("instale nikodym[explain]")`).
   b. Construir background si `needs_background`: muestra seedeada de `background_partition` (tamaño `background_size`).
   c. Calcular contribuciones sobre el scope local (`local_scope`): `φ = explainer.contributions(X_scope)` en la unidad `contribution_space` (log-odds/margen por default); `φ_0 = explainer.base_value()`.
   d. *Additivity check* (si `log_odds` y `check_additivity`): `φ_0 + Σφ ≈ margen(X_scope)`; si no, `ExplainExplainerError`.
   e. Global: `Φ_j = mean|φ_j|`, dirección `mean(φ_j)`, rank → `ShapGlobalRecord`.
   f. Local + reason codes: por observación, ordenar `|φ_j|` desc, tomar top-N adversos (y protectores si `include_protective`), etiquetar dirección y `bin_label` (desde `binning.tables`) → `LocalExplanationRecord`.
6. **Mitad scorecard (si aplica).**
   a. Baseline `baseline_j` = `E[WoE_j]` sobre `baseline_partition` (o `0` si `neutral_zero`).
   b. Contribución analítica `φ_j(x_i) = β_j·(WoE_ij − baseline_j)` (log-odds); `φ_0 = α + Σ_j β_j·baseline_j`. **Exacto, sin shap.**
   c. `scorecard_contributions` por atributo/bin (con `points` de SDD-09 para trazabilidad) + reason codes analógos (mismo `build_reason_codes`).
7. **Comparativa de drivers.** Rankear features del campeón (por `|β·baseline|`/IV de `binning.summary`) y del challenger (por `Φ_j`); `top_k_comparison`; construir `DriverComparisonRecord` (solape/acuerdo).
8. **Normalizar numéricamente.** `-0.0 → 0.0`, finitud, orden estable.
9. **Validar invariantes.** Aditividad, alineación de features, rango de PD, determinismo declarado.
10. **Construir DTOs.** `ExplainerMetadata`, `ExplainCardSection` (con `metric_sections` CT-2: `"shap_summary"`, `"shap_dependence"` [figuras si `emit_figures`], `"global_importances"`, `"reason_codes_example"`, `"scorecard_vs_ml"`), `ExplainResult`.
11. **Auditar decisiones.** Explainer por modelo, semilla, background, unidad, política de reason codes, baseline scorecard, comparativa, determinismo.
12. **Publicar artefactos.** Escribir las siete claves `provides` bajo `"explain"`.

**Reúso de SHAP (sin reimplementar Shapley).** `explain` **no** recodifica el cálculo de valores de Shapley (ni Tree SHAP, ni Kernel SHAP): importa perezosamente `shap` y usa `shap.TreeExplainer`/`LinearExplainer`/`KernelExplainer`. Un test AST impide que aparezca una implementación propia del algoritmo (§11). La única atribución "a mano" es la del **scorecard lineal**, que es **álgebra cerrada exacta** (no una aproximación de Shapley), y se verifica contra `shap.LinearExplainer` en un test de consistencia.

**Selección de explainer — detalle.** `resolve_explainer` mapea (backend, forced) a la clase concreta según la tabla D-EXP-1. `"auto"` elige Tree para `{xgboost,lightgbm,catboost,random_forest}`, Linear para modelos lineales, Kernel para lo demás (SVM rbf). Un `forced` incompatible con el backend ⇒ `ExplainConfigError` (validado en config; §5). Para GBDT/RF, TreeExplainer es **exacto y determinista** sin background; solo el fallback Kernel muestrea (seedeado, single-thread por default).

**Alternativas descartadas.**
- *SHAP para el scorecard:* innecesario; el scorecard es lineal y su atribución es cerrada/exacta (`β·(WoE−E[WoE])`) e idéntica a los puntos de SDD-09. Se calcula analíticamente (determinista, sin dependencia de `shap`); LinearExplainer queda como verificación cruzada.
- *KernelExplainer por default:* descartado; es aproximado y muestral (no determinista sin seed, caro). Solo fallback para modelos sin explainer exacto.
- *Explicar en espacio de probabilidad por default:* descartado como default; la probabilidad no es aditiva de forma simple y rompe el additivity check y la unidad común con el scorecard. Disponible como opción.
- *Materializar SHAP de toda la base por default:* descartado; pesa (n_obs × n_features por partición). Default a muestra/partición con el explainer disponible on-demand.
- *Usar `holdout`/`oot` como background/baseline:* descartado; filtra información de evaluación a la referencia de la explicación. Default `desarrollo`.
- *Reimplementar Shapley/Tree SHAP:* descartado; se reúsa `shap` (test AST anti-reimplementación).
- *Hardcodear un número normativo de reason codes:* descartado; no hay norma CMF de reason codes (FALTA-DATO-EXP-1). `top_n` configurable con default de referencia.
- *`dict[str, Any]` de config de explainer:* descartado; sub-schemas Pydantic tipados (sin `eval`, validables).

**Complejidad / rendimiento.** TreeExplainer: `O(n_obs · n_trees · depth · leaves)` (rápido, exacto). LinearExplainer/analítico: `O(n_obs · n_features)` (trivial). KernelExplainer: `O(n_obs · nsamples · costo_predict)` (caro; por eso es fallback y el scope local se acota). `explain` registra `n_obs_explained`, `n_features`, `explainer_kind`, `background_size` y `shap_seconds` en diagnostics.

## 8. Casos borde y manejo de errores

- **Falta el extra `[explain]`:** `MissingDependencyError("instale nikodym[explain]")`, al resolver un explainer SHAP (la mitad scorecard **no** lo requiere: una corrida `targets="scorecard"` funciona sin `shap`).
- **`targets ∈ {ml,both}` con `NikodymConfig.ml` ausente:** `ExplainConfigError` (no hay challenger que explicar).
- **`targets="both"` sin artefactos de scorecard:** se degrada a ML con `log_decision("explain_scorecard_skipped")`; **no** es error.
- **`targets="scorecard"` sin `scorecard`/`coefficients`/`tables`:** `ArtifactNotFoundError` por CT-1 antes de ejecutar.
- **Backend sin explainer exacto y sin extra Kernel disponible:** `ExplainBackendError` con el backend y el explainer requerido.
- **`ml_explainer` forzado incompatible con el backend:** `ExplainConfigError` (validado en config).
- **Fallo del additivity check de SHAP:** `ExplainExplainerError` con la brecha observada; no se silencia (no se "arregla" recortando).
- **Features del scope no coinciden con `estimator.feature_names_in_`:** `ExplainDataError` con las columnas faltantes/sobrantes.
- **SHAP produce valores no finitos:** `ExplainExplainerError`; no se propaga `NaN`/`inf`.
- **`deterministic=True` con `n_threads>1` y explainer efectivo Kernel:** `ExplainConfigError` (o coacción a 1 con warning, D-EXP-det).
- **`local_scope="all"` con base grande:** `log_decision` de costo (no error); se respeta la petición.
- **`top_n` > nº de features:** se acota con `log_decision` (no error).
- **Versión de `shap` no soportada:** `ExplainBackendError` con la versión detectada; los golden se pinean a versión (§9, §11).
- **`filterwarnings=["error"]`:** los warnings de `shap`/`matplotlib`/`numba` se convierten en diagnostics explícitos o excepciones controladas; no se silencian (p. ej. `NumbaDeprecationWarning`, warnings de additivity se gestionan explícitamente).

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen modelo (scorecard/ml), backend, explainer, semilla, feature y valor observado cuando aplique.

## 9. Reproducibilidad y auditoría

- **Componente estocástico (acotado).** La **mitad scorecard** es exacta y **sin azar**. La **mitad ML** con Tree/Linear es **exacta y sin muestreo** (byte-reproducible independientemente del threading). Solo el **fallback KernelExplainer** y el **muestreo de background/scope** son estocásticos: se siembran con `seed = SeedManager.int_seed_for("explain")` (entropía compuesta `[root_seed, sha256("explain")]`; nunca `hash()` builtin).
- **Siembra.** El muestreo del background (`background_size`) y del scope local (`sample_size`) usa `np.random.default_rng(seed)` (reconstruido de forma determinista); KernelExplainer recibe la semilla para su selección. `apply_global()` propaga `PYTHONHASHSEED` como en el resto del núcleo.
- **Determinismo esperado.** `(data_hash + config_hash + root_seed + shap_version + model_fiteado + single_thread_si_kernel) → shap_global, reason_codes, scorecard_contributions, comparison, card idénticos`. Con Tree/Linear el resultado es determinista siempre; con Kernel multihilo solo se garantiza estabilidad estadística, no byte-a-byte (se marca en `explainer_metadata`/card).
- **Versión de `shap` pineada.** Los golden dependen de la versión exacta de `shap` (algoritmos de Tree/Kernel SHAP pueden cambiar). `shap_version` se registra y los tests golden fijan el rango (`shap>=0.44`, D-EXP-golden); un cambio de versión que mueva el golden es un evento **auditado**, no un fallo silencioso.
- **Herencia del caveat GBDT.** El **modelo** puede ser no byte-reproducible si `ml` corrió multihilo (SDD-12 §9); pero **dado un modelo fiteado fijo**, TreeExplainer es determinista. `explain` audita que la explicación es reproducible **condicional al modelo**; si `ml.backend_metadata.deterministic=False`, el card hereda el caveat (la explicación es estable, el modelo explicado puede no serlo).
- **Normalización numérica.** `-0.0 → 0.0`; sin `NaN`/`inf` en contribuciones/PD; hashes auxiliares (si se hashean frames) con `pandas.util.hash_pandas_object(...).astype("<u8")`, nunca bytes Parquet ni `hash()` builtin.
- **Núcleo liviano.** `import nikodym.explain` **no** importa `shap`/`matplotlib`/`numba`/`llvmlite`/`sklearn`/`pandas`/`numpy`; solo registra `ExplainConfig` + `ExplainStep` y puebla el hook. Imports pesados dentro de `execute`/`explainers`. Anotaciones de DataFrame/estimador/explainer bajo `TYPE_CHECKING` o strings. `pandera` siempre `import pandera.pandas as pa` dentro de función.
- **Audit trail (`log_decision`).** Registrar como mínimo:
  - `explain_targets`: qué se explicó (scorecard/ml/ambos) y si el scorecard se saltó;
  - `explain_explainer`: explainer por modelo (kind, `feature_perturbation`), `shap_version`;
  - `explain_seed`: semilla derivada, `n_threads`, flag de determinismo;
  - `explain_background`: fuente y tamaño del background/baseline;
  - `explain_contribution_space`: unidad (log-odds/probabilidad) y resultado del additivity check;
  - `explain_reason_codes`: `top_n`, dirección, si incluye protectores;
  - `explain_scorecard`: baseline, consistencia con puntos de SDD-09;
  - `explain_comparison`: solape de drivers scorecard-vs-ML;
  - `explain_determinism`: si el modo (Kernel multihilo) no es byte-reproducible.
- **Card / report.** `ExplainCardSection.metric_sections` incluye `"shap_summary"` (importancia global), `"shap_dependence"` (figuras si `emit_figures`), `"reason_codes_example"` (ejemplo local), `"scorecard_vs_ml"` (comparativa) y `"determinism"` cuando el modo no sea byte-reproducible. `ExplainResult.term_structure()` retorna `None` (explain no es multi-período; CT-2).
- **Lineage.** `explain` consume `config_hash` y hashes aguas arriba (incluye el hash del modelo explicado); agrega el hash de su `shap_global`/`reason_codes`, no reemplaza el lineage base.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `BaseNikodymEstimator`, `AuditableMixin`, `SeedManager`, `NikodymError`, `MissingDependencyError`, lineage, `config_hash`, patrón CT-2 `term_structure()`.
- SDD-05 (convenciones): Pydantic v2, hooks diferidos, `extra="forbid"`, `frozen=True`, naming inglés APIs/español docs/errores.
- SDD-12 (`ml`): `MLChallenger` (API sklearn-like `predict_proba`/`predict_pd`/`from_config`/`get_params`/`set_params`, `feature_names_in_`, `classes_`, `estimator_`), `MLBackendMetadata`, `MLBackendName`. **Dependencia de código + artefactos DAG** (`ml.estimator`/`backend_metadata`/`pd_frame`).
- SDD-06 (`binning`): `("binning","woe_frame")` (features), `("binning","tables")` (nombre/bin del atributo), `("binning","summary")` (IV para la comparativa).
- SDD-07 (`selection`): `selected_woe_frame`/`selected_woe_columns` (fuente condicional, heredada de `ml.feature_source`).
- SDD-08 (`model`): `("model","coefficients")` (β/α para la mitad scorecard) — **opcional**.
- SDD-09 (`scorecard`): `("scorecard","scorecard")` (puntos por atributo, trazabilidad) — **opcional**.

**Aguas abajo.**
- SDD-26 (`report`) renderiza SHAP summary, reason codes y comparativa scorecard-vs-ML.
- SDD-22 (`validation`) puede consumir estabilidad de explicaciones (rev. menor aditiva B-VAL-EXP; no dura).

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| shap | `>=0.44` (verificado en `pyproject.toml:L67`) | MIT ✅ | TreeExplainer/LinearExplainer/KernelExplainer | extra `nikodym[explain]`; import perezoso |
| matplotlib | `>=3.7` (`pyproject.toml:L68`) | PSF/BSD-compat ✅ | figuras SHAP summary/dependence (si `emit_figures`) | extra `nikodym[explain]`; import perezoso |
| numba / llvmlite | `>=0.60` / `>=0.43` (`pyproject.toml:L69-L70`) | BSD ✅ | aceleración de `shap` (constraint explícito Py 3.12) | extra `nikodym[explain]`; import perezoso |
| scikit-learn | `>=1.6` (vía backend de `ml`) | BSD-3 ✅ | modelo nativo a explicar | presente vía el extra del backend (`[ml]`/`[xgboost]`/…) |
| pandas / numpy | base de `data` | BSD ✅ | frames, arrays, contribuciones | base; import perezoso |
| pydantic | `>=2` | MIT ✅ | config/DTOs frozen | base |

El extra `[explain] = ["shap>=0.44", "matplotlib>=3.7", "numba>=0.60", "llvmlite>=0.43"]` **ya está declarado** en `pyproject.toml` (L66-L71). En la práctica `explain` co-requiere el extra del backend de `ml` (explica challengers), p. ej. `nikodym[explain,xgboost]`. **Sin copyleft**: shap es MIT. Optuna (SDD-13) **no** es dependencia de `explain`. El build de B14.4 añade el marker `requires_explain: requiere el extra [explain]` en `pyproject.toml` (junto a los `requires_xgboost`/… existentes, `pyproject.toml:L184-L188`).

**Núcleo liviano.**
- `nikodym.core` no importa `nikodym.explain`.
- `import nikodym.explain` no importa shap/matplotlib/numba/llvmlite/sklearn/pandas/numpy ni los backends ML.
- `explain.__init__` expone config/errores/registro con anotaciones string y `TYPE_CHECKING`, y hace `importlib.import_module("nikodym.explain.step")` para el `@register` sin arrastrar `shap` (patrón idéntico a `ml.__init__`, `src/nikodym/ml/__init__.py:L96`).
- Mensaje de dependencia faltante nombra el extra `[explain]`.

## 11. Estrategia de tests

Marco transversal en SDD-24. Cobertura objetivo 100% para `explain` (no es módulo regulatorio, pero la marca exige calidad ejemplar). `filterwarnings=["error"]`, `mypy --strict`, ruff `E,F,I,N,UP,B,SIM,RUF,D` y docstrings públicas en español. Los tests que ejecutan SHAP usan `requires_explain`; los que ajustan/explican un challenger real usan además el marker del backend. La mitad scorecard (analítica) corre **sin** `shap`.

- **Golden lineal exacto (scorecard).** Con un modelo logístico de 1-2 features y WoE conocidos, `φ_j = β_j·(WoE_ij − E[WoE_j])` se computa a mano y se verifica exacto; el `φ_0 + Σφ` reconstruye el `η_i` de SDD-09; consistencia con los `puntos` de la tabla de scorecard (salvo `Factor`/`Offset`).
- **Golden lineal cruzado (Linear SHAP).** `shap.LinearExplainer` sobre la misma logística reproduce las contribuciones analíticas dentro de tolerancia (verificación cruzada del camino exacto).
- **Golden tree stump.** TreeExplainer sobre un árbol de profundidad 1 con un split conocido: las contribuciones SHAP son las diferencias de valor de hoja respecto de la base, computables a mano; se verifica exacto.
- **Aditividad.** `φ_0 + Σ_j φ_j(x_i) ≈ margen(x_i)` (log-odds) dentro de tolerancia para Tree/Linear; violarla ⇒ `ExplainExplainerError`.
- **Reason codes correctos.** Contribución positiva ⇒ `direction="increases_pd"`; el top-N respeta el orden por magnitud con desempate lexicográfico; `include_protective` añade los negativos; `top_n` > nº features se acota con log.
- **Reproducibilidad byte-a-byte.** Dos corridas con misma semilla y mismos datos ⇒ `shap_global`/`reason_codes`/`scorecard_contributions` idénticos tras normalización; Tree/Linear deterministas siempre; Kernel determinista con seed + single-thread.
- **No determinismo declarado.** Con Kernel + `n_threads>1`, `explainer_metadata.deterministic=False` y el card marca el caveat; no se asevera igualdad byte-a-byte.
- **Selección de explainer.** `resolve_explainer` mapea GBDT/RF → Tree, lineal → Linear, SVM rbf → Kernel; un `forced` incompatible ⇒ `ExplainConfigError`.
- **No reimplementación de Shapley.** Test AST/grep impide una implementación propia de Tree/Kernel SHAP en `explain`; la atribución del ML solo entra como llamada a `shap.*`. La única atribución "a mano" permitida es la lineal exacta del scorecard (verificada contra LinearExplainer).
- **Extra faltante.** `targets` con ML sin `[explain]` ⇒ `MissingDependencyError("instale nikodym[explain]")`; `targets="scorecard"` funciona **sin** `shap`.
- **Import guard.** Subproceso verifica que `import nikodym.explain` no deja shap/matplotlib/numba/llvmlite/sklearn/pandas/numpy en `sys.modules`.
- **Config round-trip/hash.** YAML dump/load preserva `targets`/explainer/reason_codes; cambiar `targets`/`ml_explainer`/`top_n`/`contribution_space`/`background_size` mueve `config_hash`; el default de `NikodymConfig()` con `explain=None` mueve `GOLDEN_DEFAULT_CONFIG_HASH` respecto al golden previo sin `explain` (test no tautológico, cálculo independiente).
- **Degradación scorecard.** `targets="both"` sin artefactos de scorecard ⇒ explica ML y `log_decision("explain_scorecard_skipped")`; `scorecard_contributions=None`.
- **Comparativa.** El solape de drivers scorecard-vs-ML es correcto sobre rankings conocidos (features compartidas marcadas `both`; exclusivas marcadas `*_only`).
- **No mutación.** Snapshots de `woe_frame`, `ml.estimator`, `coefficients`, `scorecard`, `labels`, `splits` permanecen iguales.
- **Endianness/hash.** Cualquier hash auxiliar usa `.astype("<u8")`; grep impide `hash()` builtin en rutas de identidad.
- **Sin Optuna.** Grep/test documental impide importar `optuna` en `explain`.

Fixtures: `woe_frame_small.parquet` sintético con particiones y monotonía conocida, `MLChallenger` fiteado pequeño (`random_forest` para velocidad; GBDT tras marker), `coefficients`/`scorecard` del campeón alineados, `binning.tables` mínimas, `labels`/`splits` mínimos, `ExplainConfig` por `targets`/explainer, `FakeExplainer` para aislar el reúso de `shap`, `InMemoryAuditSink`, y datasets degenerados (features desalineadas, additivity roto, backend sin explainer exacto, base grande, scorecard ausente).

## 12. Decisiones abiertas y riesgos

**R0 (Cami).** **Ninguno.** `explain` no fija producto irreversible, release público, PyPI, repo-público, deploy ni plata. Las decisiones D-EXP son **defaults metodológicos editables** y se listan para revisión de Cami; **la metodología de explicabilidad no es R0** (así lo pide el encargo). El único punto sensible —el formato/número normativo de reason codes— se trata como **FALTA-DATO configurable**, no como norma inventada.

**D-EXP para revisión de Cami.**
- **D-EXP-1 — Explainer por backend.** Recomendación: TreeExplainer (GBDT/RF), LinearExplainer/analítico (logística/SVM lineal), KernelExplainer (fallback SVM rbf). `ml_explainer="auto"` resuelve; forzable. Tree/Linear exactos; Kernel aproximado.
- **D-EXP-2 — Tamaño de background.** Recomendación: `100` observaciones muestreadas de `desarrollo`, seedeadas (solo relevante para Kernel/interventional). **A confirmar por Cami** el tamaño según costo/estabilidad.
- **D-EXP-3 — N de reason codes.** Recomendación: `top_n=5` (referencia ECOA/FCRA "key factors"; **no** norma CMF — FALTA-DATO-EXP-1). **A confirmar por Cami**; configurable.
- **D-EXP-4 — Unidad de contribución.** Recomendación: `"log_odds"` (aditiva, misma unidad que el scorecard, habilita additivity check y comparativa limpia); `"probability"` disponible (∆PD, no perfectamente aditiva).
- **D-EXP-5 — Clase explicada.** Recomendación: explicar la **clase positiva (PD, clase 1)** siempre (coherente con `predict_pd` de SDD-12).
- **D-EXP-6 — Scope local.** Recomendación: `"sample"`/`200` sobre `holdout`, con el explainer disponible on-demand; `"all"`/`"partition"` disponibles (con caveat de costo). Evita materializar SHAP de toda la base.
- **D-EXP-7 — Baseline del scorecard.** Recomendación: `"population_mean"` (`E[WoE]` sobre `desarrollo`, coincide con LinearExplainer interventional); `"neutral_zero"` (`WoE=0`) disponible.
- **D-EXP-8 — Valores de interacción SHAP.** Recomendación: **off** por default (caros); expuestos como opción futura si el reporte lo pide.
- **D-EXP-9 — `feature_perturbation` de TreeExplainer.** Recomendación: `"tree_path_dependent"` (exacto para el árbol, sin background, determinista); `"interventional"` disponible (semántica causal, requiere background). Documentar que difieren con features correlacionadas.
- **D-EXP-det — Determinismo default.** Recomendación: `deterministic=True`/`n_threads=1` (byte-reproducibilidad y golden); Tree/Linear deterministas siempre. Abierta: ¿`deterministic=True`+`n_threads>1` con Kernel debe fallar (recomendado) o coaccionar a 1 con warning?
- **D-EXP-golden — Golden por versión de `shap`.** Recomendación: pinear el rango (`shap>=0.44`) para los golden; un cambio de versión que mueva el golden es un evento auditado (no fallo silencioso).
- **D-EXP-target-agnóstico — Explicabilidad reusable para LGD/EAD.** Recomendación: diseñar `UnifiedExplainer`/`ContributionExplainer` sin acoplarlos a clasificación binaria (permitir una salida/`task` futura), pero **implementar solo PD/binario en v1**; LGD/EAD entran cuando F4 los requiera.

**FALTA-DATO explícitos.**
- **FALTA-DATO-EXP-1 — Formato/número normativo de reason codes por jurisdicción.** El régimen de "adverse action reason codes / key factors" es **norma en EE. UU.** (ECOA/Reg B, FCRA), **no en Chile/CMF** (que no manda un formato ni un N fijo). `explain` entrega `top_n` configurable (default de referencia `5`) y dirección/magnitud estructuradas; el formato de comunicación al cliente y el N exigido son **dato del usuario/jurisdicción**, **no se inventa una norma CMF**.
- **FALTA-DATO-EXP-2 — Umbral de "driver material".** Qué magnitud de contribución justifica listar un reason code (o una acción) es decisión de gobierno; `explain` reporta todas y el `min_abs_contribution`/`top_n`, no fija un umbral normativo.
- **FALTA-DATO-EXP-3 — Garantías de determinismo cross-versión de `shap`.** Documentadas como caveat; los golden se pinean a versión (D-EXP-golden).

**Riesgos y mitigaciones.**
- **Reason codes leídos como norma que no existe.** Mitigación: FALTA-DATO-EXP-1 explícito; default de referencia declarado como convención, no como norma CMF; formato configurable.
- **SHAP reimplementado por inercia.** Mitigación: reúso de `shap` + test AST anti-reimplementación; solo la atribución lineal del scorecard es "a mano" (exacta, verificada contra LinearExplainer).
- **Explicación no determinista tomada por bug.** Mitigación: default Tree/Linear exactos; Kernel seedeado + single-thread + golden pineados a versión.
- **Fuga de referencia (`holdout`/`oot` como background).** Mitigación: background/baseline default `desarrollo`; `log_decision` de caveat si se usa evaluación.
- **Additivity silenciosamente roto.** Mitigación: `check_additivity` por default + `ExplainExplainerError` ruidoso.
- **Confundir la comparativa de drivers con la de performance.** Mitigación: frontera dura en §1 (drivers/atribución, no AUC/PSI); la comparación de performance vive en `ml.comparison`.
- **`shap`/`numba` pesados en import.** Mitigación: import perezoso + test `sys.modules` + constraint `numba>=0.60`/`llvmlite>=0.43` (Py 3.12) ya en el extra.
- **Materializar SHAP de toda la base.** Mitigación: scope local acotado por default + explainer on-demand.

**Citas internas.** ESPECIFICACIONES.md §5.3 (L116-L121, SHAP+reason codes, no intercambiables), §6.3 (L192, `explain/` scorecard WoE+β y SHAP), §7 (L224, shap MIT), §8 (L245, reason codes/SHAP artefacto); ROADMAP.md F2 (L64-L72, DoD "SHAP integrado al reporte; tests de determinismo"); `00-INDICE.md` fila SDD-14 (`explain`, ML, F2, T3, dep 12, ⬜→🟡); `_CONTRATOS-TRANSVERSALES.md` CT-1/CT-2/CT-3; SDD-12 §4/§9 (`ml`); SDD-11 (`performance`, frontera); SDD-10 (`calibration`, frontera); SDD-09 §7 (`scorecard`, puntos WoE·β); SDD-08 §4 (`model`, coefficients); SDD-06 §3 (`binning`, convención WoE); SDD-24 (`testing`); SDD-25 (`packaging/CI`); `pyproject.toml:L66-L71` (extra `[explain]`), `L184-L188` (markers); `core/config/hashing.py:L24` (INFRA_SECTIONS); `core/config/schema.py` (hook `_ML_CONFIG_CLS`/`_valida_ml` como molde); `src/nikodym/ml/__init__.py:L96` (hook `importlib`); `src/nikodym/ml/estimator.py:L98,L215-L227` (API `MLChallenger`).
</content>
</invoke>
