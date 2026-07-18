# SDD-19 — `markov` (matrices de transición y term-structure)

| Campo | Valor |
|---|---|
| **SDD** | 19 |
| **Módulo** | `nikodym.markov` |
| **Fase** | F5 |
| **Tanda de producción** | T5 |
| **Estado** | ✅ Implementado; API experimental |
| **Depende de** | SDD-02 |
| **Lo consumen** | SDD-16/SDD-20 |
| **Autor / Fecha** | DanIA / 2026-06-29 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `markov` estima matrices de transición de estados/rating y publica una term-structure de PD por absorción en default, intercambiable con la salida de `survival`, para IFRS 9 lifetime y forward-looking.

**Responsabilidad única (qué SÍ hace).**
- Estima matrices de transición discretas por método **cohort**: MLE multinomial por fila, `P_ij = N_ij / N_i`.
- Estima generadores de tiempo continuo por método **duration**: intensidades `q_ij = N_ij / ∫Y_i(t)dt`, diagonal conservativa y `P(t)=expm(Q·t)`.
- Proyecta multi-período con Chapman-Kolmogorov: homogéneo `P(0,t)=P^t`; general `P(0,t)=∏_k P(k,k+1)` con producto ordenado.
- Implementa la ruta no-homogénea Aalen-Johansen como product-integral `P(s,t)=∏_{(s,t]}(I+dΛ(u))`.
- Diagnostica el **embedding problem** de Israel, Rosenthal & Wei (2001): si un `P` discreto admite un generador válido `Q` tal que `P=expm(Q)`.
- Deriva `PD_cum(t | state_0)` y `PD_marginal(t | state_0)` desde la probabilidad de absorción en el estado default.
- Publica artefactos namespaced bajo `"markov"`: estimador, matriz de transición, generador, term-structure, diagnósticos, result y card.
- Aporta el sub-config **`MarkovConfig`** (sección `markov` de `NikodymConfig`), computacional y por tanto incluido en el `config_hash`.
- Registra en auditoría el método, estados, absorbentes, validaciones estocásticas, diagnóstico de embedding, horizonte y cualquier `FALTA-DATO-MKV`.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No calcula ECL.** SDD-16 consume `markov.term_structure` y añade LGD/EAD/staging/descuento según ESPECIFICACIONES §5.5.
- **No construye escenarios macro ni satellite models.** SDD-20 mantiene la cadena `macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting` y la consistencia PIT de ESPECIFICACIONES §5.6.
- **No transforma TTC a PIT por sí mismo.** Markov publica la term-structure base desde las migraciones observadas; SDD-20 aplica ajustes macro/PIT cuando corresponda.
- **No define LGD, EAD, SICR, stage, EIR ni pesos de escenario.** Esos campos son económicos y viven en SDD-16/20.
- **No rediseña SDD-02 como capa longitudinal IFRS 9 completa.** Consume un frame tabular validado por `data`; para Markov ese frame debe ser un panel mínimo `entidad × período × estado`, no el panel económico completo `cuenta × período × escenario × EAD/LGD`.
- **No hace imputación ni reparación silenciosa de estados.** Missing, estados desconocidos, filas duplicadas o matrices inválidas fallan con excepciones propias o quedan en diagnostics si la política lo permite.
- **No usa RNG.** Todas las rutas son conteo, MLE por fila y álgebra lineal determinista.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Forward-looking / dinámica (F5/T5), ruta paralela a `survival` para producir lifetime PD/term-structure.
- **Quién lo invoca:** `Study.run()` como sección `markov` de `NikodymConfig`, o API programática sobre un panel de migraciones.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, excepciones, lineage), `data.frame` de SDD-02, y dependencias numéricas perezosas (`pandas`, `numpy`, `scipy`) dentro de `fit`/`transform`.
- **Quién lo consume:** SDD-16 (`provisioning/ifrs9`) y SDD-20 (`forward`) mediante el mismo contrato tidy que `SurvivalResult.term_structure()`.

```text
data.frame (panel estado x período) ─► markov ─┬─► ifrs9 / ECL lifetime
                                               └─► forward / satellite / PIT scenarios

survival ───────────────────────────────────────► mismo contrato term_structure tidy
```

**Interacción con `Study` y config declarativo.** `MarkovStep` es un `Step` nativo registrado con `@register("standard", domain="markov")`. Declara `requires`/`provides` (CT-1), lee `("data","frame")`, ajusta la ruta configurada, valida matrices/generadores y publica sus artefactos bajo `"markov"`. El `rng` se recibe por el contrato homogéneo de `Step`, pero la implementación debe hacer `del rng`.

**Relación con CT-3.** SDD-02 modela el panel transversal de scorecard. `markov` depende de SDD-02 porque reusa su mecanismo de carga, validación, hash lógico, lineage y artifact store. Para F5, el dataset cargado por `data` debe ser un panel de migraciones con columnas `id`, `time` y `state` declaradas en `MarkovConfig.input`. Esto no convierte a SDD-02 en el panel longitudinal económico IFRS 9; ese diseño completo sigue diferido a F4/F5.

**Cableado implementado en `core.study`.** El registro vigente:
- `_DOMAIN_MODULES["markov"] = "nikodym.markov"`;
- `_DOMAIN_CONFIG_CLASSES["markov"] = ("nikodym.markov.config", "MarkovConfig")`;
- `_DEFAULT_DOMAIN_ORDER` ubica `"markov"` después de `"data"` y antes de `"provisioning_ifrs9"`/`"forward"`;
- el orden lineal no reemplaza CT-1: los prerequisitos reales se expresan por `requires`/`provides`; el scheduler topológico sigue diferido a F5.

**Paquete físico y troceo B19.x.**

```text
src/nikodym/markov/
  __init__.py
  config.py
  exceptions.py
  transition.py
  term_structure.py
  results.py
  step.py
```

**B19.1 - `config.py` + `exceptions.py`.**
Schemas Pydantic v2, jerarquía de errores, hooks de config global, round-trip YAML, sin dependencias pesadas top-level.

**B19.2 - `transition.py`.**
`TransitionMatrixEstimator`, cohort MLE, duration/generator, validación estocástica y atributos fiteados.

**B19.3 - `term_structure.py`.**
Chapman-Kolmogorov homogéneo/no-homogéneo, Aalen-Johansen, embedding diagnostic y conversión a PD cumulative/marginal.

**B19.4 - `results.py`.**
`MarkovResult`, `MarkovDiagnostics`, `MarkovCard`, DTOs frozen CT-2, método `term_structure()` consistente con `SurvivalResult.term_structure()`.

**B19.5 - `step.py` + cableado.**
`MarkovStep`, `@register(domain="markov")`, publicación de artefactos, auditoría, import guards y pruebas end-to-end con `Study`.

## 3. Conceptos y fundamentos

**Fuente normativa/metodológica interna.**
- ESPECIFICACIONES §5.5 consume `PD_marg_k(t)` en `ECL = Σ_k w_k · Σ_t [ PD_marg_k(t) · LGD_k(t) · EAD_k(t) / (1+EIR)^t ]`.
- ESPECIFICACIONES §5.6 fija Markov: cohort, duration/generador con `scipy.linalg.expm`, Chapman-Kolmogorov, Aalen-Johansen y embedding problem con flag de diagnóstico.
- ESPECIFICACIONES §5.6 exige la cadena forward `macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting` con consistencia PIT.

**Notación.**
- `S = {1, ..., m}`: conjunto finito ordenado de estados/rating.
- `d ∈ S`: estado absorbente de default.
- `p ∈ S`: estado absorbente opcional de prepago u otra salida, si la config lo declara.
- `X_n`: estado observado al período discreto `n`.
- `P`: matriz de transición de un período, `P_ij = P(X_{n+1}=j | X_n=i)`.
- `Q`: generador de tiempo continuo, con intensidades `q_ij` para `i≠j`.
- `e_i`: vector fila unitario que representa el estado inicial `i`.
- `PD_cum_i(t)`: probabilidad acumulada de haber alcanzado default al horizonte `t` partiendo de `i`.
- `PD_marg_i(t) = PD_cum_i(t) - PD_cum_i(t-1)`.

**Estimación cohort (discreto/multinomial).** Con conteos de migraciones `N_ij` desde estado `i` hacia estado `j` en un intervalo de observación común:

```text
N_i = Σ_j N_ij
P_hat_ij = N_ij / N_i
```

Cada fila de `P_hat` es el MLE multinomial condicionado en haber partido desde `i`. Si se declara `weight_col`, los conteos son sumas de pesos no negativos; por default son conteos unitarios. Si `i` es absorbente, la fila se fuerza por contrato a identidad `P_ii=1`, `P_ij=0` para `j≠i`, y cualquier transición observada desde `i` a otro estado es error de input salvo política diagnóstica explícita.

**Estimación duration / generador.** En tiempo continuo, con `N_ij` transiciones observadas de `i` a `j` y tiempo-en-riesgo acumulado en el estado `i`:

```text
T_i = ∫ Y_i(t) dt
q_hat_ij = N_ij / T_i       para i ≠ j
q_hat_ii = -Σ_{j≠i} q_hat_ij
```

`Q` es conservativa: cada fila suma cero; las entradas fuera de la diagonal son no negativas; la diagonal es no positiva. Para un horizonte `t` en la unidad declarada:

```text
P(t) = expm(Q · t)
```

La ruta requiere `scipy.linalg.expm` con import perezoso dentro de `fit`/`predict_transition`. Si `T_i=0` para un estado no absorbente con transiciones esperadas, se levanta `InvalidGeneratorError` o `MarkovFitError` según el punto de falla.

**Multi-período / Chapman-Kolmogorov.**

Caso homogéneo:

```text
P(0,t) = P^t
```

Caso no homogéneo por matrices de un período:

```text
P(0,t) = P(0,1) · P(1,2) · ... · P(t-1,t)
```

El producto es ordenado en el tiempo; no se conmutan matrices. La implementación debe preservar el orden estable de los períodos configurados y validar cada matriz antes de multiplicar.

**Aalen-Johansen no-homogéneo.** Cuando las intensidades dependen del tiempo y hay tiempos de transición observados, se usa el estimador product-limit/product-integral:

```text
P_hat(s,t) = ∏_{u ∈ (s,t]} (I + dΛ_hat(u))
```

Para cada tiempo de evento `u`, con riesgo `Y_i(u-)` justo antes de `u` y saltos `dN_ij(u)`:

```text
dΛ_hat_ij(u) = dN_ij(u) / Y_i(u-)   para i ≠ j
dΛ_hat_ii(u) = -Σ_{j≠i} dΛ_hat_ij(u)
```

Se usa cuando `cfg.dynamics.homogeneous=False` y `cfg.dynamics.nonhomogeneous_method="aalen_johansen"`. Su salida es una secuencia de matrices `P(s,t_k)` validadas y una term-structure de default por estado inicial. Si el panel solo tiene snapshots discretos sin tiempos de evento/riesgo, se usa el producto ordenado de matrices de un período, no Aalen-Johansen.

**Embedding problem.** Dada una matriz discreta `P`, se pregunta si existe un generador markoviano válido `Q` tal que:

```text
P = expm(Q)
```

El diagnóstico v1 usa el logaritmo principal de matriz:

```text
L = logm(P)
Q_candidate = Re(L) / Δt
```

Condiciones verificadas:
- `logm(P)` debe ser real dentro de `imaginary_tol`;
- las filas de `Q_candidate` deben sumar cero dentro de `generator_tol`;
- las entradas fuera de la diagonal deben ser `>= -generator_tol`;
- la diagonal debe ser `q_ii = -Σ_{j≠i}q_ij` dentro de tolerancia;
- los estados absorbentes deben tener fila cero en `Q_candidate`.

Si las condiciones fallan, el resultado lleva `embedding_status` y `embedding_flags`; no se arregla nada en silencio. Con `embedding_policy="forbid"` se levanta `MarkovEmbeddingError`. Con `embedding_policy="diagnose"` se conserva la ruta discreta `P^t` y `generator=None`. Con `embedding_policy="regularize"`, se proyecta el candidato real al cono de generadores conservativos, se recalcula `P_regularized=expm(Q_regularized·Δt)`, se reporta la distancia `||P_regularized-P||_F` y se marca `embedding_adjusted=True`.

**Term-structure de PD desde Markov.** Para estado inicial `i`, estado default `d` y matriz acumulada `P(0,t)`:

```text
PD_cum_i(t) = [e_i · P(0,t)]_d
PD_marg_i(t) = PD_cum_i(t) - PD_cum_i(t-1), con PD_cum_i(0)=1 si i=d, 0 si i≠d
survival_i(t) = 1 - PD_cum_i(t)
```

`survival` se define como "no haber absorbido en default" para alinear columnas con `survival.term_structure()`. Si existe prepago absorbente, su probabilidad se publica en matrices/probabilidades de estado o diagnostics; no se resta de `survival` salvo que SDD-16/20 lo transforme con reglas económicas propias.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/markov/config.py
MarkovMethod = Literal["cohort", "duration"]
EmbeddingPolicy = Literal["diagnose", "regularize", "forbid"]
ProjectionMode = Literal["homogeneous", "period_matrices", "aalen_johansen"]

class MarkovInputConfig(NikodymBaseConfig): ...
class MarkovStateConfig(NikodymBaseConfig): ...
class MarkovEstimationConfig(NikodymBaseConfig): ...
class MarkovDynamicsConfig(NikodymBaseConfig): ...
class MarkovValidationConfig(NikodymBaseConfig): ...
class MarkovConfig(NikodymBaseConfig): ...
```

```python
# nikodym/markov/exceptions.py
class MarkovError(NikodymError): ...
class MarkovConfigError(MarkovError): ...
class MarkovInputError(MarkovError): ...
class MarkovFitError(MarkovError): ...
class MarkovTransformError(MarkovError): ...
class NonStochasticMatrixError(MarkovTransformError): ...
class InvalidGeneratorError(MarkovTransformError): ...
class MarkovEmbeddingError(MarkovTransformError): ...
```

```python
# nikodym/markov/transition.py
class TransitionMatrixEstimator:
    config_cls: ClassVar[type[MarkovConfig]] = MarkovConfig

    @classmethod
    def from_config(cls, cfg: MarkovConfig) -> "TransitionMatrixEstimator": ...

    def fit(
        self,
        frame: "pandas.DataFrame",
        *,
        audit: "AuditSink | None" = None,
    ) -> "Self": ...

    def predict_transition(
        self,
        *,
        horizons: "Sequence[int | float]",
    ) -> "dict[float, pandas.DataFrame]": ...

    def term_structure(
        self,
        *,
        horizons: "Sequence[int | float]",
    ) -> "pandas.DataFrame": ...
```

**Atributos fiteados.**
- `states_`: tupla ordenada de estados.
- `default_state_`: estado absorbente default.
- `transition_matrix_`: matriz de un período `P` o matriz base homogénea.
- `period_transition_matrices_`: matrices `P(k,k+1)` para ruta no homogénea discreta.
- `generator_`: `Q` si `method="duration"` o si embedding produjo un generador válido/regularizado; `None` si no aplica.
- `state_counts_`: conteos/riesgos por estado.
- `transition_counts_`: matriz de conteos `N_ij`.
- `diagnostics_`: `MarkovDiagnostics`.

```python
# nikodym/markov/term_structure.py
def validate_transition_matrix(
    matrix: "numpy.ndarray",
    *,
    states: tuple[str, ...],
    absorbing_states: tuple[str, ...],
    tol: float,
) -> None: ...

def validate_generator(
    generator: "numpy.ndarray",
    *,
    states: tuple[str, ...],
    absorbing_states: tuple[str, ...],
    tol: float,
) -> None: ...

def chapman_kolmogorov(
    matrices: "Sequence[numpy.ndarray]",
    *,
    homogeneous: bool,
    horizons: "Sequence[int]",
) -> "dict[int, numpy.ndarray]": ...

def aalen_johansen(
    frame: "pandas.DataFrame",
    *,
    config: MarkovConfig,
) -> "dict[float, numpy.ndarray]": ...

def diagnose_embedding(
    matrix: "numpy.ndarray",
    *,
    delta_t: float,
    config: MarkovConfig,
) -> "EmbeddingDiagnostics": ...

def markov_term_structure(
    transitions: "Mapping[int | float, numpy.ndarray]",
    *,
    config: MarkovConfig,
) -> "pandas.DataFrame": ...
```

```python
# nikodym/markov/results.py
class MarkovDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: MarkovMethod
    projection_mode: ProjectionMode
    states: tuple[str, ...]
    default_state: str
    absorbing_states: tuple[str, ...]
    n_entities: int
    n_observations: int
    n_transitions: int
    n_periods: int
    stochastic_tol: float
    generator_tol: float
    embedding_status: str | None = None
    embedding_flags: tuple[str, ...] = ()
    embedding_adjusted: bool = False
    embedding_distance_fro: float | None = None
    fit_statistics: dict[str, float | int | str | None] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

class MarkovCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: MarkovMethod
    projection_mode: ProjectionMode
    time_unit: str
    horizon_periods: tuple[int, ...]
    states: tuple[str, ...]
    default_state: str
    absorbing_states: tuple[str, ...]
    output_columns: tuple[str, ...]
    diagnostics: MarkovDiagnostics
    dependency_versions: dict[str, str]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)  # CT-2

class MarkovResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    estimator: TransitionMatrixEstimator
    transition_matrix_frame: "pandas.DataFrame"
    generator_frame: "pandas.DataFrame | None"
    term_structure_frame: "pandas.DataFrame"
    diagnostics: MarkovDiagnostics
    card: MarkovCard
    def term_structure(self) -> "pandas.DataFrame | None": ...
```

`MarkovResult.term_structure()` cumple CT-2 y debe ser intercambiable con `SurvivalResult.term_structure()`: retorna el DataFrame tidy cuando hay proyección publicable; retorna `None` solo si se ejecutó un modo diagnóstico sin horizonte o sin matriz válida. SDD-16/20 no deben necesitar distinguir Markov vs Survival para leer `pd_marginal` y `pd_cumulative`.

```python
# nikodym/markov/step.py
@register("standard", domain="markov")
class MarkovStep(AuditableMixin):
    name: str = "markov"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "frame"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("markov", "estimator"),
        ("markov", "transition_matrix"),
        ("markov", "term_structure"),
        ("markov", "generator"),
        ("markov", "diagnostics"),
        ("markov", "result"),
        ("markov", "card"),
    )
    @classmethod
    def from_config(cls, cfg: MarkovConfig) -> "MarkovStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "MarkovResult": ...
```

**Artefactos que `MarkovStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"estimator"` | `TransitionMatrixEstimator` | estimador fiteado |
| `"transition_matrix"` | `pandas.DataFrame` | matriz o matrices tidy `from_state/to_state/probability/period` |
| `"term_structure"` | `pandas.DataFrame` | tabla tidy lifetime PD compatible con `survival` |
| `"generator"` | `pandas.DataFrame | None` | generador `Q` tidy si existe; `None` con key presente si no aplica |
| `"diagnostics"` | `MarkovDiagnostics` | validaciones, embedding, conteos y warnings |
| `"result"` | `MarkovResult` | contenedor agregado |
| `"card"` | `MarkovCard` | resumen para governance/report |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "markov"])
markov_ts = study.artifacts.get("markov", "term_structure")
result = study.artifacts.get("markov", "result")
ecl_input = result.term_structure()
```

## 5. Configuración (schema Pydantic)

`MarkovConfig` es el sub-config de la sección `markov` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, `Literal` para categóricos, rangos explícitos y metadatos `title`/`description`/`ui_*`.

```python
# nikodym/markov/config.py
from typing import Literal
from pydantic import Field, model_validator
from nikodym.core.config import NikodymBaseConfig

class MarkovInputConfig(NikodymBaseConfig):
    id_col: str = Field(..., title="Identificador de entidad")
    time_col: str = Field(..., title="Período o timestamp de observación")
    state_col: str = Field(..., title="Estado/rating observado")
    segment_col: str | None = Field(default=None, title="Segmento/pool opcional")
    partition_col: str | None = Field(default="partition", title="Partición si existe")
    weight_col: str | None = Field(default=None, title="Peso opcional de transición")
    exposure_time_col: str | None = Field(default=None, title="Tiempo en riesgo para duration")
    transition_time_col: str | None = Field(default=None, title="Tiempo exacto de transición")

class MarkovStateConfig(NikodymBaseConfig):
    states: tuple[str, ...] = Field(..., min_length=2, title="Estados en orden canónico")
    default_state: str = Field(default="default", title="Estado absorbente default")
    absorbing_states: tuple[str, ...] = Field(default=("default",), title="Estados absorbentes")
    allow_unknown_states: bool = Field(default=False, title="Permitir estados fuera de catálogo")

class MarkovEstimationConfig(NikodymBaseConfig):
    method: MarkovMethod = Field(default="cohort", title="Método de estimación")
    interval: float = Field(default=1.0, gt=0.0, title="Longitud del intervalo base")
    use_weights: bool = Field(default=False, title="Usar weight_col si existe")
    min_origin_count: int = Field(default=1, ge=1, title="Mínimo de salidas por estado no absorbente")

class MarkovDynamicsConfig(NikodymBaseConfig):
    projection_mode: ProjectionMode = Field(default="homogeneous", title="Modo de proyección")
    time_unit: str = Field(default="period", title="Unidad temporal declarada")
    horizon_periods: tuple[int, ...] = Field(default=(1, 2, 3, 4, 5), title="Horizontes discretos")
    evaluation_times: tuple[float, ...] = Field(default=(), title="Horizontes continuos")
    embedding_policy: EmbeddingPolicy = Field(default="diagnose", title="Política de embedding")

class MarkovValidationConfig(NikodymBaseConfig):
    stochastic_tol: float = Field(default=1e-10, gt=0.0, lt=1e-3)
    generator_tol: float = Field(default=1e-10, gt=0.0, lt=1e-3)
    imaginary_tol: float = Field(default=1e-10, gt=0.0, lt=1e-3)
    normalize_within_tolerance: bool = Field(default=True)
    fail_on_missing_periods: bool = Field(default=True)

class MarkovConfig(NikodymBaseConfig):
    type: Literal["standard"] = Field(default="standard")
    input: MarkovInputConfig
    states: MarkovStateConfig
    estimation: MarkovEstimationConfig = Field(default_factory=MarkovEstimationConfig)
    dynamics: MarkovDynamicsConfig = Field(default_factory=MarkovDynamicsConfig)
    validation: MarkovValidationConfig = Field(default_factory=MarkovValidationConfig)
    fail_on_falta_dato: bool = Field(default=True, title="Fallar ante brechas críticas")
```

**Validaciones de config.**
- `states.states` no puede tener duplicados y debe contener `default_state`.
- `absorbing_states` debe ser subconjunto de `states.states` y debe contener `default_state`.
- `id_col`, `time_col` y `state_col` son requeridos y distintos entre sí.
- `method="duration"` exige `exposure_time_col` o tiempos ordenables que permitan derivar tiempo-en-riesgo; si no, `MarkovConfigError`.
- `projection_mode="aalen_johansen"` exige `transition_time_col` o una convención explícita de tiempo de evento; si no, `MarkovConfigError`.
- `use_weights=True` exige `weight_col`; pesos negativos o no finitos fallan en input.
- `horizon_periods` debe contener enteros positivos estrictamente crecientes; `evaluation_times` debe contener positivos estrictamente crecientes.
- Si `projection_mode="homogeneous"` y `method="duration"`, se permite `evaluation_times`; si faltan, se usan `horizon_periods` como múltiplos de `interval`.
- `allow_unknown_states=False` es default: estados fuera de catálogo levantan `MarkovInputError`.

**Defaults defendibles.**
- `method="cohort"`: es el camino discreto estándar para paneles de rating/snapshot y no requiere `scipy`.
- `default_state="default"` y `absorbing_states=("default",)`: convención mínima; la taxonomía completa de ratings es obligatoria en `states`.
- `projection_mode="homogeneous"`: produce una matriz base y `P^t`; matrices por período/Aalen-Johansen son opt-in.
- `embedding_policy="diagnose"`: cumple ESPECIFICACIONES §5.6 con flag de diagnóstico y evita regularización silenciosa.
- tolerancias `1e-10`: estrictas, pero permiten ruido de álgebra lineal en sumas de fila y logm/expm.
- `normalize_within_tolerance=True`: solo corrige `-0.0`, residuos numéricos dentro de tolerancia y cierre de fila; registra la normalización en diagnostics.

**Round-trip YAML y UI.** El round-trip sigue SDD-05: `yaml.safe_dump(cfg.model_dump(mode="json", by_alias=True), sort_keys=False)` y carga vía `load_config`. La UI renderiza selectores para método, embedding policy, projection mode y estados absorbentes; nunca permite editar una matriz sin mostrar validación estocástica.

**Hook diferido en `core.config.schema`.** F5 debe extender el patrón usado por dominios previos:
- declarar `_MARKOV_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir `markov` como campo `Any` en runtime y `MarkovConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("markov", mode="before")`;
- sin importar `nikodym.markov`, conservar núcleo liviano y JSON canónico determinista.

**Impacto en `config_hash`.** `markov` **no** pertenece a `INFRA_SECTIONS`. Al cablear `MarkovConfig` en `NikodymConfig`, cualquier cambio en método, estados, horizonte, política de embedding o tolerancias debe mover el `config_hash`. Como en survival B18.1, implementar B19.1 moverá `GOLDEN_DEFAULT_CONFIG_HASH`; el implementador debe hacer barrido del literal en tests y repros, no tratarlo como regresión inesperada.

## 6. Contratos de datos (I/O)

**Input duro del Step.**

| artefacto | requerido | contrato |
|---|---:|---|
| `("data", "frame")` | sí | `pandas.DataFrame` con panel mínimo `id × time × state` validado por SDD-02 |

**Input `data.frame` esperado por `markov`.**
- `id_col`: identificador estable de entidad/cuenta/cliente, no nulo.
- `time_col`: período ordinal o timestamp ordenable; dentro de cada `id_col` debe ser estrictamente creciente o deduplicable por política explícita.
- `state_col`: estado observado; todos los valores deben pertenecer a `states.states` salvo `allow_unknown_states=True`.
- `segment_col`: opcional; si existe, permite estimar matrices por segmento/pool o publicar salida agregada por segmento.
- `partition_col`: opcional; si existe, por default se ajusta en `desarrollo` y se publica diagnostics por partición. No se usan Holdout/OOT para estimar parámetros salvo configuración futura explícita.
- `weight_col`: opcional; pesos no negativos y finitos.
- `exposure_time_col`: opcional; requerido para duration si no se puede derivar `Δt` desde `time_col`.
- `transition_time_col`: opcional; requerido para Aalen-Johansen con tiempos exactos.

**Estructura de transición derivada.**

| columna lógica | significado |
|---|---|
| `from_state` | estado al inicio del intervalo |
| `to_state` | estado al fin del intervalo |
| `from_time` | tiempo inicial |
| `to_time` | tiempo final |
| `delta_time` | longitud del intervalo |
| `weight` | peso unitario o configurado |
| `segment` | segmento/pool opcional |

**Output `transition_matrix`.** `pandas.DataFrame` tidy:

| columna | significado |
|---|---|
| `period` | período base o `None` para matriz homogénea |
| `from_state` | estado origen |
| `to_state` | estado destino |
| `probability` | `P_ij` |
| `count` | conteo o peso agregado `N_ij` si aplica |
| `origin_count` | `N_i` de la fila origen |
| `method` | `"cohort"` o `"duration"` |
| `segment` | segmento/pool opcional |

**Output `generator`.** `pandas.DataFrame | None` tidy:

| columna | significado |
|---|---|
| `from_state` | estado origen |
| `to_state` | estado destino |
| `intensity` | `q_ij` |
| `time_at_risk` | `T_i` si aplica |
| `transition_count` | `N_ij` si aplica |
| `source` | `"duration"`, `"embedding"` o `"regularized_embedding"` |

**Output `term_structure`.** Debe igualar el contrato de `survival` en nombres mínimos y semántica de PD:

| columna | significado |
|---|---|
| `row_id` | id de observación inicial; `None` si la salida es por estado/segmento |
| `segment` | segmento/pool opcional |
| `partition` | partición si aplica |
| `period` | entero ordinal de proyección |
| `time_value` | tiempo en `time_unit` |
| `hazard` | PD condicional de default del período, derivada como `pd_marginal / survival(t-1)` cuando es definible |
| `survival` | `1 - pd_cumulative` |
| `pd_marginal` | `PD_cum(t)-PD_cum(t-1)` |
| `pd_cumulative` | probabilidad acumulada de absorción en default |
| `method` | ruta usada: `cohort`, `duration`, `aalen_johansen` |
| `pd_source` | `"markov"` en SDD-19 base |
| `scenario` | `None` en base; SDD-20 puede poblarla |
| `warning_codes` | códigos por fila/período si hubo advertencias |

**Compatibilidad con `survival`.**
- Las columnas `period`, `time_value`, `hazard`, `survival`, `pd_marginal`, `pd_cumulative`, `method`, `pd_source`, `scenario` y `warning_codes` tienen el mismo significado operativo que en SDD-18.
- `survival` no significa "seguir en el mismo rating"; significa "no haber llegado a default".
- `pd_cumulative` y `pd_marginal` son la interfaz económica para SDD-16/20.

**Invariantes.**
- Toda matriz de transición tiene entradas en `[0,1]` dentro de `stochastic_tol` y filas que suman `1`.
- Todo generador tiene filas que suman `0`, off-diagonal `>=0` y diagonal `<=0`.
- Todo estado absorbente tiene fila identidad en `P` y fila cero en `Q`.
- `pd_cumulative` es no decreciente por estado inicial, `pd_marginal >= 0`, `survival = 1 - pd_cumulative`.
- La suma de `pd_marginal` hasta el horizonte es `pd_cumulative(horizon)` dentro de tolerancia.
- No se publican `NaN`, `inf`, `-inf` ni `-0.0` en outputs finales; `-0.0` se normaliza a `0.0`.
- La implementación no muta `data.frame`; trabaja con copias defensivas.
- Orden estable: estados en el orden de `MarkovStateConfig.states`, períodos ascendentes, ids en orden estable de entrada.

## 7. Algoritmos y flujo

**`MarkovStep.execute(study, rng)` - secuencia canónica.**
1. **Descartar azar.** `del rng`; Markov v1 es determinista.
2. **Resolver config.** Leer `study.config.markov`; si falta en API programática, exigir `MarkovConfig` explícito.
3. **Validar CT-1.** Exigir `("data","frame")` antes de ejecutar.
4. **Copias defensivas.** Copiar el frame y no mutar artefactos de `data`.
5. **Validar input.** Columnas requeridas, estado en catálogo, tiempos ordenados, duplicados, pesos, absorbentes.
6. **Derivar transiciones.** Ordenar por `id_col,time_col`; construir pares consecutivos y `delta_time`.
7. **Seleccionar ruta.** Cohort, duration o no-homogéneo según `cfg.estimation.method` y `cfg.dynamics.projection_mode`.
8. **Ajustar estimador.** Producir `P`, `Q` o secuencia de matrices.
9. **Validar estocasticidad.** Aplicar `validate_transition_matrix`/`validate_generator`; normalizar solo residuos dentro de tolerancia.
10. **Diagnosticar embedding.** Si hay `P` discreta y la config lo pide, ejecutar `logm(P)` con política `diagnose/regularize/forbid`.
11. **Proyectar horizontes.** Chapman-Kolmogorov, `expm(Q·t)` o Aalen-Johansen.
12. **Construir term-structure.** Derivar `pd_cumulative`, `pd_marginal`, `survival` y `hazard`.
13. **Construir DTOs.** `MarkovDiagnostics`, `MarkovCard`, `MarkovResult`; poblar `metric_sections` CT-2 con resumen de matrices y embedding.
14. **Auditar decisiones.** Método, estados, absorbentes, horizonte, embedding, validaciones y `FALTA-DATO`.
15. **Publicar artefactos.** Escribir las siete claves `provides` bajo `"markov"`.

**Cohort MLE.**
1. Filtrar filas modelables según `partition_col` si aplica.
2. Para cada `id`, ordenar por tiempo y construir transiciones consecutivas.
3. Excluir transiciones posteriores a un estado absorbente; si existen, error o warning según política diagnóstica.
4. Acumular `N_ij` por estado origen/destino, segmento y período si no homogéneo.
5. Para cada estado no absorbente `i`, validar `N_i >= min_origin_count`.
6. Calcular `P_ij=N_ij/N_i`.
7. Fijar filas absorbentes como identidad.
8. Validar matriz y publicar conteos.

**Duration/generator.**
1. Construir eventos de transición y tiempo-en-riesgo por estado.
2. Acumular `T_i=Σ delta_time` o `Σ exposure_time_col`.
3. Acumular `N_ij` para `i≠j`; no contar permanencias como transiciones.
4. Calcular `q_ij=N_ij/T_i`; diagonal `q_ii=-Σ_{j≠i}q_ij`.
5. Fijar filas absorbentes a cero.
6. Validar `Q`.
7. Calcular `P(t)=expm(Q·t)` para cada horizonte y validar cada `P(t)`.

**Chapman-Kolmogorov homogéneo.**
1. Inicializar `P_power = I`.
2. Para cada período `t` ascendente, multiplicar `P_power = P_power @ P` hasta llegar a `t`.
3. Validar `P_power` y guardarlo como `P(0,t)`.

**Chapman-Kolmogorov no homogéneo discreto.**
1. Obtener matrices `P(k,k+1)` estimadas por período.
2. Inicializar `P_cum=I`.
3. En orden temporal, `P_cum = P_cum @ P(k,k+1)`.
4. Publicar `P(0,t)` solo para horizontes cubiertos; si faltan períodos y `fail_on_missing_periods=True`, levantar `MarkovTransformError`.

**Aalen-Johansen.**
1. Ordenar tiempos de evento.
2. En cada tiempo `u`, calcular riesgo `Y_i(u-)` por estado.
3. Calcular incrementos `dΛ(u)` con filas conservativas.
4. Actualizar `P_cum = P_cum @ (I + dΛ(u))`.
5. Validar `P_cum` en cada horizonte de evaluación.
6. Convertir a term-structure por probabilidad de default.

**Embedding diagnostic.**
1. Validar que `P` sea cuadrada, estocástica y con filas absorbentes correctas.
2. Importar `scipy.linalg.logm` de forma perezosa.
3. Calcular `L=logm(P)`; medir norma imaginaria.
4. Construir `Q_candidate=Re(L)/interval`.
5. Validar conservatividad y off-diagonal.
6. Si válido, publicar `generator` con `source="embedding"` y `embedding_status="valid_principal_log"`.
7. Si inválido, aplicar política:
   - `diagnose`: flag y continuar con `P^t`;
   - `forbid`: `MarkovEmbeddingError`;
   - `regularize`: proyectar al generador conservativo, recomputar `P_regularized`, medir distancia y flaggear ajuste.

**Alternativas descartadas.**
- *Reparar matrices por clipping silencioso:* descartado; ocultaría fallas regulatorias. Solo se corrigen residuos dentro de tolerancia y queda registrado.
- *Usar `hash()` para ordenar estados o transiciones:* descartado; no es reproducible entre procesos.
- *Forzar Markov a producir ECL:* descartado; SDD-16 es dueño del cálculo económico.
- *Convertir Markov en satellite model macro:* descartado; SDD-20 es dueño de macro/PIT.
- *Importar scipy/pandas/numpy en `__init__`:* descartado; viola núcleo liviano e import guard.

**Complejidad / rendimiento.** Cohort es O(n log n) por ordenamiento y O(n) en conteo. Duration es O(n log n) por ordenamiento y O(n + m²) en acumulación. Proyección homogénea es O(T·m³) si usa multiplicación densa; para `m` pequeño de ratings es aceptable. Aalen-Johansen es O(E·m²) para `E` tiempos de evento. Matrices grandes o muchos segmentos deben publicar diagnostics de tamaño antes de materializar todas las curvas.

## 8. Casos borde y manejo de errores

- **Falta `data.frame`:** `ArtifactNotFoundError` por CT-1 antes de entrar al estimador.
- **Columnas requeridas ausentes:** `MarkovInputError` con lista de columnas faltantes.
- **Estado fuera de catálogo:** `MarkovInputError` si `allow_unknown_states=False`; si `True`, se registra warning y se excluye o agrupa según política futura explícita.
- **`states` duplicados o sin default:** `MarkovConfigError`.
- **Tiempos duplicados por `id`:** `MarkovInputError`, salvo que se defina una política explícita de deduplicación futura.
- **Tiempos no ordenables o `delta_time<=0`:** `MarkovInputError`.
- **Peso negativo/no finito:** `MarkovInputError`.
- **Transición desde estado absorbente hacia otro estado:** `MarkovInputError` por default; no se reabre un default sin regla de negocio.
- **Estado no absorbente sin origen suficiente:** `MarkovFitError` si `N_i < min_origin_count`.
- **Fila de transición con suma cero en estado no absorbente:** `NonStochasticMatrixError` o `MarkovFitError`, según ocurra antes o después de construir `P`.
- **Matriz con entradas fuera de `[0,1]`:** `NonStochasticMatrixError`; valores dentro de tolerancia se normalizan y quedan en diagnostics.
- **Filas de `P` no suman 1:** `NonStochasticMatrixError` si exceden `stochastic_tol`.
- **Generador con off-diagonal negativa:** `InvalidGeneratorError`.
- **Generador con filas que no suman cero:** `InvalidGeneratorError`.
- **Diagonal de generador inconsistente:** `InvalidGeneratorError`.
- **`scipy` faltante para duration/embedding:** `MissingDependencyError` con mensaje en español que sugiera instalar `nikodym[markov]`.
- **`logm(P)` complejo o generador inválido:** flag en diagnostics, `MarkovEmbeddingError` si `embedding_policy="forbid"`.
- **Embedding no único o no probado único:** no se afirma unicidad; `embedding_flags` incluye `uniqueness_not_proven` o `non_unique_suspected` cuando corresponda.
- **Horizonte fuera de soporte no homogéneo:** `MarkovTransformError` si faltan matrices y `fail_on_missing_periods=True`.
- **`pd_marginal` negativa por ruido numérico:** normalizar a cero solo si `abs(valor)<=stochastic_tol`; si excede, `MarkovTransformError`.
- **`hazard` no definible porque `survival(t-1)=0`:** publicar `hazard=None` o `0.0` solo con warning; `pd_marginal`/`pd_cumulative` siguen siendo la fuente económica.

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen método, estado, período, tolerancia y valor observado cuando aplique.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno. `MarkovStep.execute(study, rng)` debe hacer `del rng`.
- **Determinismo esperado.** `(data_hash + config_hash + uv.lock + frame de migraciones) → P/Q/term_structure/diagnostics/card idénticos`.
- **Orden estable.** Estados según `MarkovStateConfig.states`; ids y períodos en orden estable; ningún set/dict sin orden determina el output.
- **Copias defensivas.** El frame de entrada no se muta; transiciones derivadas se materializan en objetos internos.
- **Normalización numérica.** `-0.0 → 0.0`; residuos dentro de tolerancia se ajustan y quedan en `MarkovDiagnostics.warnings`.
- **Hashes auxiliares.** Si se hashean matrices o term-structures, se usa contenido lógico con `pandas.util.hash_pandas_object` y conversión endian explícita `.astype("<u8")`; nunca bytes de parquet ni `hash()` builtin.
- **Import reproducible.** `import nikodym.markov` no debe cargar `scipy`, `pandas` ni `numpy` en top-level; las dependencias pesadas se importan dentro de métodos.
- **Audit trail (`log_decision`).** Registrar como mínimo:
  - `markov_method`: cohort/duration, projection mode y unidad temporal;
  - `markov_states`: estados, default, absorbentes, estados ausentes;
  - `markov_input_quality`: entidades, observaciones, transiciones, duplicados/exclusiones;
  - `markov_transition_counts`: `N_ij`, `N_i`, segmentos y períodos;
  - `markov_stochastic_validation`: tolerancias, normalizaciones y fallas;
  - `markov_generator`: `T_i`, intensidades, validación de Q;
  - `markov_embedding`: status, flags, distancia de regularización si aplica;
  - `markov_term_structure`: horizontes, PD acumulada/marginal y warnings.
- **Card / report.** `MarkovCard` debe permitir reconstruir el ajuste: método, estados, horizonte, tolerancias, conteos, matriz/generador, embedding, versions y `FALTA-DATO`.
- **Lineage.** `markov` consume `data_hash` y `config_hash`; no los redefine. Aporta hashes auxiliares solo como secciones estructuradas del card si se implementan.
- **Gobernanza CT-2.** `metric_sections` puede incluir `"transition_matrix_summary"`, `"generator_summary"`, `"embedding_diagnostics"` y `"term_structure_summary"` sin romper consumidores escalares.
- **Golden hash.** `MarkovConfig` ya forma parte del contrato computacional; cualquier cambio mueve `GOLDEN_DEFAULT_CONFIG_HASH` y debe actualizarse con test explícito y nota de reproducibilidad.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymError`, `MissingDependencyError`, lineage, `config_hash`, patrón CT-2 `term_structure()`.
- SDD-02 (`data`): `frame`, validación tabular, `data_hash` de contenido lógico y frontera transversal/longitudinal CT-3.
- SDD-05 (convenciones): Pydantic v2, hooks diferidos de config, `extra="forbid"`, `frozen=True`, naming inglés para APIs/stats.
- SDD-18 (`survival`): contrato hermano de term-structure tidy que SDD-16/20 consume de forma intercambiable.

**Aguas abajo.**
- SDD-16 (`provisioning/ifrs9`) consume `MarkovResult.term_structure()` para PD lifetime y añade LGD/EAD/stage/descuento.
- SDD-20 (`forward`) transforma o pondera term-structures con macro/satellite y escenarios PIT.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | `>=2.0` | BSD-3-Clause | I/O tabular, matrices tidy, term-structure | base de `data`, import perezoso en `markov` |
| numpy | `>=1.22` | BSD modificada | arrays, álgebra densa, potencias de matriz | base numérica, import perezoso |
| scipy | `>=1.10` | BSD-3-Clause | `scipy.linalg.expm`, `scipy.linalg.logm` | extra recomendado `[markov]`, import perezoso |
| pydantic | `>=2` | MIT | config/DTOs frozen | base |

**Licencias.** SciPy se distribuye bajo licencia BSD modificada de 3 cláusulas; NumPy y pandas usan licencias BSD permisivas. No hay dependencia copyleft en core. Queda vetado introducir paquetes GPL para embedding o estimación Markov.

**Base vs extra.** Recomendación D-MKV-6: `scipy` vive en el extra `[markov]`. La ruta cohort homogénea puede calcular `P^t` con `numpy`; duration, Aalen-Johansen con álgebra avanzada y embedding requieren `scipy`. Si falta, se levanta `MissingDependencyError` accionable. Aunque SciPy sea permisiva y apta para distribución, el import debe ser perezoso para conservar núcleo liviano.

**Núcleo liviano.** `nikodym.core` no importa `nikodym.markov`. `import nikodym.markov` expone config, errores y registro sin cargar `scipy`/`pandas`/`numpy`. Los tests deben verificar `sys.modules`.

**Fuentes externas verificadas para este SDD.**
- Israel, Rosenthal & Wei (2001), *Finding generators for Markov chains via empirical transition matrices, with applications to credit ratings*: https://www.probability.ca/jeff/ftpdir/wei.pdf y ficha Wiley https://onlinelibrary.wiley.com/doi/abs/10.1111/1467-9965.00114.
- SciPy `logm`/`expm`: https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.logm.html y licencia BSD-3-Clause en https://docs.scipy.org/doc/scipy/dev/core-dev/index.html.
- NumPy license: https://numpy.org/doc/stable/license.html; pandas license: https://pandas.pydata.org/docs/getting_started/overview.html#license.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **Golden cohort 3 estados.** Estados `A,B,default`; conteos `A→A=2`, `A→B=1`, `A→default=1`, `B→B=1`, `B→default=1`, default absorbente. Esperado:
  `P_A=[0.50,0.25,0.25]`, `P_B=[0,0.50,0.50]`, `P_D=[0,0,1]`.
- **Golden Chapman-Kolmogorov.** Con la matriz anterior: desde `A`, `PD_cum(1)=0.25`, `PD_cum(2)=0.50`, `PD_marg(2)=0.25`; desde `B`, `PD_cum(1)=0.50`, `PD_cum(2)=0.75`.
- **Golden duration 2 estados.** `Q=[[-0.2,0.2],[0,0]]`; `P_D(t)=1-exp(-0.2t)`. Verificar `t=1 ≈ 0.1812692469` y `t=2 ≈ 0.329679954`.
- **Golden embedding válido.** `P=[[0.8,0.2],[0,1]]`; `logm(P)` debe producir `Q=[[-a,a],[0,0]]`, `a=-log(0.8)≈0.223143551`, y `expm(Q)=P`.
- **Embedding inválido.** `P=[[0.1,0.9],[0.9,0.1]]` tiene determinante negativo; `embedding_policy="diagnose"` publica flag, `forbid` levanta `MarkovEmbeddingError`.
- **Aalen-Johansen simple.** Fixture con dos tiempos de evento y riesgos conocidos; verificar manualmente `P_cum = Π(I+dΛ)` y PD acumulada de default.
- **Validación estocástica.** Filas con suma `1+1e-8` fallan con `stochastic_tol=1e-10`; suma `1+1e-12` se normaliza y queda warning.
- **Validación de generador.** Off-diagonal negativa, fila no conservativa o absorbente con fila no cero levantan `InvalidGeneratorError`.
- **Estados absorbentes.** Transición observada desde default a vivo levanta `MarkovInputError`.
- **Contrato `term_structure`.** Columnas mínimas idénticas a `survival`; `pd_cumulative=1-survival`; suma de marginales igual a acumulada.
- **CT-1.** `MarkovStep.requires == (("data","frame"),)`; falta el artefacto produce `ArtifactNotFoundError`.
- **CT-2.** `MarkovResult.term_structure()` retorna DataFrame tidy o `None` solo en modo diagnóstico no publicable; `MarkovCard.metric_sections` admite matrices/embedding.
- **No mutación.** Snapshot profundo de `data.frame` permanece igual tras `fit`.
- **Determinismo.** Dos corridas con mismo frame/config producen matrices, term-structure, diagnostics y card idénticos.
- **Import guard.** Subproceso verifica que `import nikodym.markov` no deja `scipy`, `pandas` ni `numpy` en `sys.modules`.
- **Config.** Round-trip YAML; cambiar método, estados, horizonte, embedding policy o tolerancia cambia `config_hash`.
- **Golden default config hash.** Al cablear B19.1, actualizar literal `GOLDEN_DEFAULT_CONFIG_HASH` y probar que `markov` no está en `INFRA_SECTIONS`.
- **Warnings como error.** `filterwarnings=["error"]`; warnings de `logm`, casting complejo o overflow se convierten en error controlado.
- **Mypy/ruff.** `mypy --strict` global; ruff reglas `E,F,I,N,UP,B,SIM,RUF,D`; docstrings públicas en español; APIs/variables en inglés técnico.
- **Endianness/hash.** Cualquier hash auxiliar usa `.astype("<u8")`; test que falla si aparece `hash()` builtin en rutas de ordenamiento/hash.
- **Licencia.** Test/revisión de imports que impide dependencias GPL o imports de paquetes no declarados.

Fixtures: `markov_panel_small.parquet` sintético con `id/time/state`, `MarkovConfig` cohort mínimo, `MarkovConfig` duration con `exposure_time_col`, fixture de matriz no embeddable, `InMemoryAuditSink`, y datasets degenerados para estados desconocidos, default no absorbente, períodos faltantes y pesos inválidos.

## 12. Decisiones abiertas y riesgos

**R0.** Ninguno en SDD-19. No se introducen datos externos regulatorios, parámetros CMF/IFRS nuevos, release público, PyPI ni cambios de licencia. Las fuentes externas citadas son metodológicas/licencias permisivas y quedan trazadas en §10.

**Decisiones para revisión de Cami.**
- **D-MKV-1 — Método default.** Recomendación: `method="cohort"` porque los paneles de migración/rating suelen venir como snapshots discretos y permite una ruta base sin SciPy. `duration` queda disponible cuando hay tiempo-en-riesgo confiable.
- **D-MKV-2 — Taxonomía de estados.** Recomendación: `states` obligatorio y sin rating canónico universal; solo `default_state="default"` como convención mínima. Evita imponer nomenclatura bancaria no especificada.
- **D-MKV-3 — Política de embedding default.** Recomendación: `embedding_policy="diagnose"`; cumple ESPECIFICACIONES con flag y evita ajustes silenciosos.
- **D-MKV-4 — Proyección default.** Recomendación: `projection_mode="homogeneous"`; no-homogéneo/Aalen-Johansen requiere más datos y queda opt-in.
- **D-MKV-5 — Tolerancias.** Recomendación: `1e-10` para estocasticidad, generador e imaginario de `logm`; residuos menores se normalizan con warning, mayores fallan.
- **D-MKV-6 — SciPy como extra.** Recomendación: `scipy>=1.10` en `[markov]`, no import top-level. Es permisiva, pero no debe pesar sobre `import nikodym.markov`.
- **D-MKV-7 — Grano de salida.** Recomendación: salida por estado inicial/segmento por default; si `id_col` debe proyectarse fila a fila, repetir la term-structure según estado inicial preservando `row_id`.
- **D-MKV-8 — Regularización de embedding.** Recomendación: solo opt-in; proyectar `logm(P)` real al cono conservativo, recomputar `P_regularized`, reportar distancia Frobenius y marcar `embedding_adjusted=True`.
- **D-MKV-9 — Pesos.** Recomendación: sin pesos por default; `weight_col` opt-in para instituciones que pidan conteos ponderados por exposición u otra métrica.
- **D-MKV-10 — PIT/forward.** Recomendación: `markov` no aplica satellite macro ni Vasicek; SDD-20 transforma la term-structure y garantiza consistencia PIT.
- **D-MKV-11 — Artefacto `generator`.** Recomendación: publicar siempre la key `("markov","generator")`; valor `None` cuando no aplica para que CT-1/validación de provides sea estable.

**FALTA-DATO explícitos.**
- **FALTA-DATO-MKV-1 — Fuente exacta del panel de migraciones.** SDD-02 entrega el mecanismo de frame/hash, pero no fija columnas de `id/time/state`; se resuelve por `MarkovInputConfig`.
- **FALTA-DATO-MKV-2 — Taxonomía institucional de estados/rating.** No hay catálogo universal en ESPECIFICACIONES; cada cartera debe declarar `states`, `default_state` y absorbentes.
- **FALTA-DATO-MKV-3 — Horizonte económico IFRS 9.** SDD-19 trae horizontes de proyección; SDD-16 debe fijar maturities/EIR/stage que determinan qué horizontes se consumen.
- **FALTA-DATO-MKV-4 — Prepago/cura/competing exits.** Se permite `absorbing_states`, pero el tratamiento económico de prepago/cura pertenece a SDD-16/20.
- **FALTA-DATO-MKV-5 — Ponderación por exposición.** `weight_col` existe, pero no se asume por default si la institución no lo declara.
- **FALTA-DATO-MKV-6 — Naturaleza PIT/TTC de la matriz histórica.** Markov publica la matriz observada y su term-structure; SDD-20 debe documentar si la usa como PIT, TTC o base ajustada por macro.

**Riesgos y mitigaciones.**
- **Term-structure incompatible con `survival`.** Mitigación: columnas tidy idénticas y `MarkovResult.term_structure()` CT-2; tests de contrato cruzado con SDD-18.
- **Arreglo silencioso de matrices inválidas.** Mitigación: solo normalización dentro de tolerancia con warning; fuera de tolerancia se levanta excepción.
- **Embedding malinterpretado como siempre posible.** Mitigación: `embedding_status`, flags de no existencia/no unicidad/no probado y política default `diagnose`.
- **Datos escasos por estado.** Mitigación: `min_origin_count`, diagnostics por fila/estado y error temprano si no se puede estimar.
- **Falsa consistencia PIT.** Mitigación: Markov no declara PIT/TTC por sí solo; SDD-20 registra transformación macro y escenario.
- **Aalen-Johansen sobre snapshots sin tiempos de evento.** Mitigación: config exige `transition_time_col` o falla; snapshots usan producto de matrices discretas.
- **Dependencias pesadas en import.** Mitigación: imports perezosos y test de subproceso `sys.modules`.
- **Cambio inesperado del config hash.** Mitigación: §5/§9 documentan que `markov` mueve `GOLDEN_DEFAULT_CONFIG_HASH`.

**Citas internas.**
- **ESPECIFICACIONES.md** §5.5: ECL multi-período con `PD_marg_k(t)`.
- **ESPECIFICACIONES.md** §5.6: Markov cohort/duration, `scipy.linalg.expm`, Chapman-Kolmogorov, Aalen-Johansen, embedding problem Israel-Rosenthal-Wei y cadena forward con consistencia PIT.
- **docs/design/_CONTRATOS-TRANSVERSALES.md** CT-1/CT-2/CT-3: `requires`/`provides`, `term_structure()`, frontera transversal vs longitudinal.
- **SDD-02 (`data`)**: `data.frame`, `data_hash` lógico por bloques, `LineageBundle`, frontera CT-3.
- **SDD-18 (`survival`)**: contrato hermano de `term_structure` tidy para lifetime PD.
