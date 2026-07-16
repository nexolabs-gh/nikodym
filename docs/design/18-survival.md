# SDD-18 — `survival` (survival analysis y lifetime PD)

| Campo | Valor |
|---|---|
| **SDD** | 18 |
| **Módulo** | `nikodym.survival` |
| **Dominio** | Forward / lifetime PD |
| **Fase** | F5 |
| **Tanda de producción** | T5 (Forward-looking & dinámica) |
| **Estado** | 🟡 Borrador |
| **Depende de** | SDD-01 (`core`), SDD-02 (`data`), SDD-05 (convenciones + config), SDD-08 (`model`) |
| **Lo consumen** | SDD-16 (`provisioning/ifrs9`), SDD-17 (`provisioning`), SDD-20 (`forward`), SDD-21 (`stress`), SDD-22 (`validation`), SDD-23 (`ui`), SDD-26 (`report`) |
| **Autor / Fecha** | Codex (worker A7, redacción SDD-18 para T5) / 2026-06-29 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `survival` estima curvas de supervivencia y una term-structure de PD lifetime, con PD marginal y acumulada por período, para alimentar ECL IFRS 9 y la cadena forward-looking.

**Responsabilidad única (qué SÍ hace).**
- Ajusta modelos de survival para riesgo de crédito con entrada estructurada `tiempo + evento`: Kaplan-Meier, discrete-time hazard, Cox PH y AFT.
- Publica curvas `S(t)`, hazard `h(t)`, `PD_marginal(t)` y `PD_acumulada(t)` en una tabla tidy auditable.
- Implementa la ruta estándar IFRS 9 lifetime indicada por ESPECIFICACIONES §5.6: discrete-time hazard en formato person-period con link logit/cloglog, reutilizando el stack de scoring y la PD de F1/SDD-08.
- Usa la PD/logit de SDD-08 como insumo trazable de riesgo transversal; por default no sustituye ni recalibra ese modelo.
- Publica artefactos namespaced bajo `"survival"`: estimador fiteado, curvas, hazards, term-structure, diagnósticos, resultado agregado y card.
- Aporta el sub-config **`SurvivalConfig`** (sección `survival` de `NikodymConfig`), computacional y por tanto incluido en el `config_hash`.
- Registra con `log_decision` método, definición de evento/tiempo, fuente PD, expansión person-period, link, ruta Cox/AFT/KM, diagnósticos y brechas `FALTA-DATO`.

**Frontera dura de responsabilidad (qué NO hace, y quién lo hace).**
- **No calcula ECL.** SDD-16 consume `survival.term_structure` para calcular ECL con LGD/EAD, escenarios y descuento a EIR según ESPECIFICACIONES §5.5.
- **No calcula LGD, EAD, staging ni SICR.** Esos componentes viven en SDD-16/17.
- **No construye escenarios macro ni satellite models.** SDD-20 proyecta macro, aplica satellite models y mantiene consistencia PIT en la cadena `macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting` de ESPECIFICACIONES §5.6.
- **No reemplaza `data` longitudinal de IFRS 9/forward.** SDD-02 modela el panel transversal de scorecard; CT-3 difiere la capa longitudinal a F4/F5. `survival` puede expandir person-period para ajuste, pero no diseña el panel EAD/LGD por cuenta-periodo.
- **No entrena la scorecard F1.** SDD-08 produce `model.raw_pd_frame`; SDD-10 puede producir `calibration.calibrated_pd_frame`. `survival` los consume si la config lo declara.
- **No usa `scikit-survival` en el core distribuido.** ESPECIFICACIONES §7 lo marca GPL-3.0 y fuera del core; este SDD usa lifelines + statsmodels.
- **No inventa horizonte lifetime, granularidad temporal, definición de evento/default ni umbrales de diagnóstico.** Si no están en ESPECIFICACIONES §5.6 o en SDD aguas arriba, quedan como config requerida o `FALTA-DATO`.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Forward-looking / dinámica (F5/T5). Corre después de F1 (`model`) y antes de IFRS 9/forward/stress cuando esos módulos pidan lifetime PD.
- **Quién lo invoca:** `Study.run()` como sección `survival` de `NikodymConfig`, o API programática para ajustar un survival model sobre un frame con duración/evento.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, excepciones, lineage), `data.frame` de SDD-02 y, condicionalmente según `pd_source`, `model.raw_pd_frame` de SDD-08 (`model_raw`/`calibration`) y `calibration.calibrated_pd_frame` de SDD-10 (`calibration`). Con `pd_source="none"` el ajuste es **standalone**: solo consume `data.frame` y la cadena mínima queda en `data → survival`.

```text
data ─► binning ─► selection ─► model ──┐            (pd_source = model_raw | calibration)
                                        ├──► survival ─► ifrs9/forward/stress/report
calibration (opcional, si existe) ──────┘       term_structure lifetime PD

data ─► survival ─► ifrs9/…                          (pd_source = none: standalone,
        covariables propias del dataset               sin scorecard de por medio)
```

**Interacción con `Study` y config declarativo.** `SurvivalStep` es un `Step` nativo registrado con `@register("standard", domain="survival")`. Declara `requires`/`provides` (CT-1, `requires` **dinámico** según `pd_source` — patrón SDD-20 §81) y `execute(study, rng)`: lee `data.frame` (y `model.raw_pd_frame` solo si la config declara una fuente PD de F1), resuelve la configuración, ajusta el método seleccionado, predice curvas en el horizonte configurado y escribe sus artefactos bajo `"survival"`. El `rng` se recibe por contrato homogéneo de `Step`; los métodos v1 son deterministas y deben hacer `del rng`.

**Cableado futuro en `core.study`.** Al implementar SDD-18:
- `_DOMAIN_MODULES["survival"] = "nikodym.survival"`;
- `_DOMAIN_CONFIG_CLASSES["survival"] = ("nikodym.survival.config", "SurvivalConfig")`;
- `_DEFAULT_DOMAIN_ORDER` ubica `"survival"` después de `"model"` y, si `"calibration"` está presente, después de `"calibration"` solo cuando `pd_source="calibration"`. Debe quedar antes de `"provisioning_ifrs9"`, `"forward"` y `"stress"`.

El orden no reemplaza CT-1: los prerequisitos reales se expresan por `requires`/`provides`. El scheduler topológico sigue diferido a F5 según `_CONTRATOS-TRANSVERSALES.md` CT-1; este SDD solo usa la firma ya estabilizada.

**Paquete físico troceable.**

```text
src/nikodym/survival/
  __init__.py
  base.py
  config.py
  exceptions.py
  results.py
  kaplan_meier.py
  discrete_hazard.py
  cox_aft.py
  step.py
```

**Responsabilidad por módulo.**
- `base.py`: `BaseSurvivalModel` como Protocol/base propia, porque ESPECIFICACIONES §6.1 dice que survival tiene entrada estructurada evento+tiempo y no calza con un `predict` único sklearn.
- `config.py`: schemas Pydantic v2 (`SurvivalConfig`, inputs, horizonte, método, discrete hazard, KM, Cox/AFT).
- `exceptions.py`: jerarquía de errores propia, todos descendientes de `NikodymError`.
- `results.py`: DTOs Pydantic frozen, term-structure tidy, diagnostics y card con `metric_sections` CT-2.
- `kaplan_meier.py`: estimador no paramétrico KM, curva `S(t)` y varianza/IC Greenwood si la config trae nivel de confianza.
- `discrete_hazard.py`: expansión person-period y ajuste con statsmodels (logit/cloglog), ruta estándar IFRS 9 lifetime de ESPECIFICACIONES §5.6.
- `cox_aft.py`: wrappers lifelines para Cox PH, test de Schoenfeld y AFT paramétrico.
- `step.py`: `SurvivalStep`, registro, CT-1, publicación de artefactos y auditoría.

**Troceo implementable un módulo/commit.**
- **B18.1 - config/exceptions/base:** schemas, errores, `BaseSurvivalModel`, sin dependencias pesadas top-level.
- **B18.2 - results:** `SurvivalResult`, `SurvivalCard`, `SurvivalDiagnostics`, `term_structure()`.
- **B18.3 - kaplan_meier:** KM determinista con goldens de fórmula.
- **B18.4 - discrete_hazard:** person-period + statsmodels, ruta default.
- **B18.5 - cox_aft:** lifelines Cox/AFT + Schoenfeld.
- **B18.6 - step/cableado:** `SurvivalStep`, hooks de config, orden canónico, integración Study end-to-end.

Cada bloque debe cerrar con ruff, ruff D, mypy `--strict`, tests del módulo tocado y sin tocar módulos Python fuera del alcance del bloque.

## 3. Conceptos y fundamentos

**Fuente normativa/metodológica interna.**
- ESPECIFICACIONES §5.5 fija que ECL usa `PD_marg_k(t)` dentro de `ECL = Σ_k w_k · Σ_t [ PD_marg_k(t) · LGD_k(t) · EAD_k(t) / (1+EIR)^t ]`; Stage 1 suma 12m y Stage 2/3 usa lifetime.
- ESPECIFICACIONES §5.6 fija survival como ruta lifetime PD: Kaplan-Meier, Cox PH con Schoenfeld, AFT y discrete-time hazard logit/cloglog person-period. También fija las fórmulas `S(t)=∏(1−h_j)` y `PD_marg(t)=S(t−1)·h(t)`.
- ESPECIFICACIONES §7 fija la licencia: lifelines MIT permitido; `scikit-survival` GPL-3.0 queda research-only y no entra al core distribuido.

**Notación.**
- `T_i`: tiempo hasta default/evento para la observación `i`.
- `E_i`: indicador de evento (`1` default observado, `0` censura derecha).
- `t`: período discreto de proyección lifetime.
- `h_i(t) = P(T_i = t | T_i ≥ t, x_i)`: hazard discreto.
- `S_i(t) = P(T_i > t)`: supervivencia hasta el fin del período `t`.
- `PD_marginal_i(t) = P(T_i = t)`: PD marginal del período.
- `PD_acumulada_i(t) = P(T_i ≤ t) = 1 - S_i(t)`.

**Kaplan-Meier no paramétrico.** Para tiempos de evento ordenados `t_j`, con `n_j` exposiciones en riesgo justo antes de `t_j` y `d_j` eventos en `t_j`:

```text
S_hat(t) = ∏_{t_j <= t} (1 - d_j / n_j)
```

La varianza Greenwood asociada es:

```text
Var[S_hat(t)] = S_hat(t)^2 · Σ_{t_j <= t} d_j / (n_j · (n_j - d_j))
```

ESPECIFICACIONES §5.6 autoriza Kaplan-Meier, pero no fija nivel de confianza, transformación de intervalo ni política de clipping. Por eso `confidence_level` queda como config opcional y **FALTA-DATO-SUR-3** queda marcado para Cami.

**Discrete-time hazard (person-period).** Es la ruta estándar IFRS 9 lifetime señalada en ESPECIFICACIONES §5.6. Cada observación se expande a filas `i,t` hasta evento/censura. Se ajusta:

```text
g(h_i(t)) = α_t + β' x_i(t)
```

donde `g` es `logit` o `cloglog`, ambos permitidos por ESPECIFICACIONES §5.6. Con hazards predichos:

```text
S_i(0) = 1
S_i(t) = ∏_{j <= t} (1 - h_i(j))
PD_marginal_i(t) = S_i(t-1) · h_i(t)
PD_acumulada_i(t) = 1 - S_i(t)
```

Esta ruta reusa el stack de scoring: `model.raw_pd_frame.linear_predictor` o `model.raw_pd_frame.pd_raw` viajan como covariable/insumo de riesgo. La forma exacta en que la PD F1 entra en el hazard (covariable, offset o segmento) no está fijada por ESPECIFICACIONES; queda como **D-SUR-3**.

**Cox proportional hazards.** Cox PH modela:

```text
λ(t | x) = λ_0(t) · exp(β' x)
```

ESPECIFICACIONES §5.6 exige Cox PH con diagnóstico Schoenfeld. La implementación debe usar lifelines para el ajuste y publicar el resultado del test de proporcionalidad de hazards. ESPECIFICACIONES no fija umbral de p-value ni acción ante incumplimiento; queda en **D-SUR-7**.

**AFT paramétrico.** AFT modela el tiempo al evento en escala logarítmica:

```text
log(T_i) = μ(x_i) + σ · ε_i
```

ESPECIFICACIONES §5.6 incluye AFT, pero no fija familia paramétrica. Por tanto `aft_family` no tiene default normativo en este borrador: si `method="aft"`, la familia debe venir configurada o aprobarse en **D-SUR-8**.

**PIT/TTC y forward-looking.** `survival` estima lifetime PD base con los insumos F1 disponibles. La consistencia PIT y el ajuste macro por escenarios pertenecen a SDD-20, que debe consumir o transformar la term-structure manteniendo la cadena de ESPECIFICACIONES §5.6. Este SDD no inventa factores macro ni pesos de escenarios.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/survival/config.py
SurvivalMethod = Literal["discrete_hazard", "kaplan_meier", "cox_ph", "aft"]
DiscreteHazardLink = Literal["logit", "cloglog"]
PdSource = Literal["model_raw", "calibration", "none"]
AftFamily = Literal["weibull", "lognormal", "loglogistic"]

class SurvivalInputConfig(NikodymBaseConfig): ...
class SurvivalTimeGridConfig(NikodymBaseConfig): ...
class KaplanMeierConfig(NikodymBaseConfig): ...
class DiscreteHazardConfig(NikodymBaseConfig): ...
class CoxAftConfig(NikodymBaseConfig): ...
class SurvivalConfig(NikodymBaseConfig): ...
```

```python
# nikodym/survival/exceptions.py
class SurvivalError(NikodymError): ...
class SurvivalConfigError(SurvivalError): ...
class SurvivalInputError(SurvivalError): ...
class SurvivalFitError(SurvivalError): ...
class SurvivalTransformError(SurvivalError): ...
class SurvivalLicenseError(SurvivalError): ...
```

```python
# nikodym/survival/base.py
@runtime_checkable
class BaseSurvivalModel(Protocol):
    """Contrato mínimo para modelos de survival Nikodym."""
    config_cls: ClassVar[type[SurvivalConfig]]
    def fit(
        self,
        frame: "pandas.DataFrame",
        *,
        duration_col: str,
        event_col: str,
        covariate_cols: tuple[str, ...] = (),
        pd_frame: "pandas.DataFrame | None" = None,
        audit: "AuditSink | None" = None,
    ) -> "Self": ...
    def predict_survival(
        self,
        frame: "pandas.DataFrame",
        *,
        times: "Sequence[int | float]",
    ) -> "pandas.DataFrame": ...
    def predict_hazard(
        self,
        frame: "pandas.DataFrame",
        *,
        times: "Sequence[int | float]",
    ) -> "pandas.DataFrame": ...
    def term_structure(
        self,
        frame: "pandas.DataFrame",
        *,
        times: "Sequence[int | float]",
    ) -> "pandas.DataFrame": ...
```

```python
# nikodym/survival/results.py
class SurvivalTermRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    row_id: str
    period: int
    time_value: float
    survival: float
    hazard: float | None
    pd_marginal: float
    pd_cumulative: float
    method: SurvivalMethod
    pd_source: PdSource
    segment: str | None = None
    scenario: str | None = None
    warnings: tuple[str, ...] = ()

class SurvivalDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: SurvivalMethod
    n_rows: int
    n_events: int
    n_censored: int
    max_observed_time: float
    link: DiscreteHazardLink | None = None
    schoenfeld_test: dict[str, Any] | None = None
    aft_family: AftFamily | None = None
    fit_statistics: dict[str, float | int | str | None] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

class SurvivalCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: SurvivalMethod
    pd_source: PdSource
    duration_col: str
    event_col: str
    time_unit: str
    n_rows: int
    n_events: int
    n_periods: int
    output_columns: tuple[str, ...]
    diagnostics: SurvivalDiagnostics
    dependency_versions: dict[str, str]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)  # CT-2.

class SurvivalResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    estimator: BaseSurvivalModel
    term_structure_frame: "pandas.DataFrame"
    survival_curve_frame: "pandas.DataFrame"
    hazard_frame: "pandas.DataFrame"
    diagnostics: SurvivalDiagnostics
    card: SurvivalCard
    def term_structure(self) -> "pandas.DataFrame | None": ...
```

`SurvivalResult.term_structure()` cumple CT-2: retorna la tabla tidy lifetime PD cuando existe; retorna `None` solo si el método configurado se ejecutó en modo diagnóstico sin proyección publicable. SDD-16 debe consumir esta salida como PD lifetime y añadir LGD/EAD/stage/escenario/descuento.

```python
# nikodym/survival/kaplan_meier.py
class KaplanMeierSurvivalModel:
    config_cls: ClassVar[type[SurvivalConfig]] = SurvivalConfig
    @classmethod
    def from_config(cls, cfg: SurvivalConfig) -> "KaplanMeierSurvivalModel": ...
    def fit(... ) -> "Self": ...
    def predict_survival(... ) -> "pandas.DataFrame": ...
    def predict_hazard(... ) -> "pandas.DataFrame": ...
    def term_structure(... ) -> "pandas.DataFrame": ...
```

```python
# nikodym/survival/discrete_hazard.py
class DiscreteTimeHazardModel:
    config_cls: ClassVar[type[SurvivalConfig]] = SurvivalConfig
    @classmethod
    def from_config(cls, cfg: SurvivalConfig) -> "DiscreteTimeHazardModel": ...
    def fit(... ) -> "Self": ...
    def predict_survival(... ) -> "pandas.DataFrame": ...
    def predict_hazard(... ) -> "pandas.DataFrame": ...
    def term_structure(... ) -> "pandas.DataFrame": ...
```

```python
# nikodym/survival/cox_aft.py
class CoxPHSurvivalModel:
    config_cls: ClassVar[type[SurvivalConfig]] = SurvivalConfig
    @classmethod
    def from_config(cls, cfg: SurvivalConfig) -> "CoxPHSurvivalModel": ...
    def fit(... ) -> "Self": ...
    def predict_survival(... ) -> "pandas.DataFrame": ...
    def predict_hazard(... ) -> "pandas.DataFrame": ...
    def term_structure(... ) -> "pandas.DataFrame": ...
    def proportional_hazard_diagnostics(self) -> dict[str, Any]: ...

class AFTSurvivalModel:
    config_cls: ClassVar[type[SurvivalConfig]] = SurvivalConfig
    @classmethod
    def from_config(cls, cfg: SurvivalConfig) -> "AFTSurvivalModel": ...
    def fit(... ) -> "Self": ...
    def predict_survival(... ) -> "pandas.DataFrame": ...
    def predict_hazard(... ) -> "pandas.DataFrame": ...
    def term_structure(... ) -> "pandas.DataFrame": ...
```

```python
# nikodym/survival/step.py
@register("standard", domain="survival")
class SurvivalStep(AuditableMixin):
    name: str = "survival"
    # ``requires`` es DINÁMICO (CT-1, patrón SDD-20 §81): ``__init__`` lo deriva de la config.
    # Default (pd_source = model_raw | calibration); con pd_source="none" queda (("data","frame"),).
    requires: tuple[ArtifactKey, ...] = (
        ("data", "frame"),
        ("model", "raw_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("survival", "estimator"),
        ("survival", "term_structure"),
        ("survival", "survival_curves"),
        ("survival", "hazards"),
        ("survival", "diagnostics"),
        ("survival", "result"),
        ("survival", "card"),
    )
    @classmethod
    def from_config(cls, cfg: SurvivalConfig) -> "SurvivalStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "SurvivalResult": ...
```

**Dependencias condicionales.**
- `("model", "raw_pd_frame")` es prerequisito solo cuando la config declara una fuente PD de F1 (`pd_source ∈ {model_raw, calibration}`): la ruta estándar lifetime reusa scoring y de ahí también se arrastra `partition`. Con `pd_source="none"` el prerequisito desaparece (`requires` dinámico): el hazard se ajusta standalone sobre `covariate_cols` propias del dataset, sin `partition` que arrastrar (el ajuste usa todas las filas).
- `("calibration", "calibrated_pd_frame")` no es prerequisito duro del Step: se exige dentro de `execute` solo si `cfg.input.pd_source == "calibration"`.
- Cox/AFT/KM requieren lifelines; discrete hazard requiere statsmodels. Si falta el extra correspondiente, se levanta `MissingDependencyError` con mensaje en español.

**Artefactos que `SurvivalStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"estimator"` | `BaseSurvivalModel` | estimador fiteado de la ruta seleccionada |
| `"term_structure"` | `pandas.DataFrame` | tabla tidy lifetime PD con `survival`, `hazard`, `pd_marginal`, `pd_cumulative` |
| `"survival_curves"` | `pandas.DataFrame` | curvas `S(t)` por fila/segmento/período |
| `"hazards"` | `pandas.DataFrame` | hazards `h(t)` si el método los publica; KM puede derivarlos por períodos observados |
| `"diagnostics"` | `SurvivalDiagnostics` | conteos, fit statistics, Schoenfeld/AFT/KM warnings |
| `"result"` | `SurvivalResult` | contenedor agregado |
| `"card"` | `SurvivalCard` | resumen para governance/report |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning", "selection", "model", "survival"])
lifetime_pd = study.artifacts.get("survival", "term_structure")
result = study.artifacts.get("survival", "result")
ecl_input = result.term_structure()
```

## 5. Configuración (schema Pydantic)

`SurvivalConfig` es el sub-config de la sección `survival` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig` (`extra="forbid"`, `frozen=True`), campos con `title`/`description`, rangos `ge/le`, `Literal` en categóricos y metadatos `ui_*`. **No es infraestructura** (`survival ∉ INFRA_SECTIONS`): cambiar método, link, columnas, fuente PD u horizonte cambia el `config_hash`.

```python
# nikodym/survival/config.py
from typing import Literal
from pydantic import Field, model_validator
from nikodym.core.config import NikodymBaseConfig

class SurvivalInputConfig(NikodymBaseConfig):
    duration_col: str = Field(..., title="Columna de tiempo hasta evento/censura")
    event_col: str = Field(..., title="Columna indicador de evento")
    id_col: str | None = Field(default=None, title="Columna identificador estable")
    segment_col: str | None = Field(default=None, title="Segmento/pool opcional")
    pd_source: PdSource = Field(default="model_raw", title="Fuente PD F1")
    pd_column: str = Field(default="pd_raw", title="Columna PD cruda")
    linear_predictor_column: str = Field(default="linear_predictor", title="Columna logit crudo")
    covariate_cols: tuple[str, ...] = Field(default=(), title="Covariables adicionales")

class SurvivalTimeGridConfig(NikodymBaseConfig):
    time_unit: str = Field(default="period", title="Unidad temporal declarada")
    horizon_periods: int | None = Field(default=None, ge=1, title="Horizonte lifetime")
    evaluation_times: tuple[float, ...] = Field(default=(), title="Tiempos explícitos de evaluación")

class KaplanMeierConfig(NikodymBaseConfig):
    confidence_level: float | None = Field(default=None, gt=0.0, lt=1.0)
    confidence_transform: Literal["plain", "loglog"] | None = Field(default=None)

class DiscreteHazardConfig(NikodymBaseConfig):
    link: DiscreteHazardLink = Field(default="logit", title="Link del hazard discreto")
    include_period_dummies: bool = Field(default=True, title="Interceptos por período")
    pd_role: Literal["covariate", "offset", "segment", "none"] = Field(
        default="covariate", title="Rol de la PD/logit F1")
    min_events_per_period: int | None = Field(default=None, ge=1)

class CoxAftConfig(NikodymBaseConfig):
    ph_test_enabled: bool = Field(default=True, title="Diagnóstico Schoenfeld")
    ph_p_value_threshold: float | None = Field(default=None, gt=0.0, lt=1.0)
    aft_family: AftFamily | None = Field(default=None, title="Familia AFT")

class SurvivalConfig(NikodymBaseConfig):
    type: Literal["standard"] = Field(default="standard")
    method: SurvivalMethod = Field(default="discrete_hazard", title="Método survival")
    input: SurvivalInputConfig
    time_grid: SurvivalTimeGridConfig = Field(default_factory=SurvivalTimeGridConfig)
    kaplan_meier: KaplanMeierConfig = Field(default_factory=KaplanMeierConfig)
    discrete_hazard: DiscreteHazardConfig = Field(default_factory=DiscreteHazardConfig)
    cox_aft: CoxAftConfig = Field(default_factory=CoxAftConfig)
    fail_on_falta_dato: bool = Field(default=True, title="Fallar ante brechas de dato críticas")
```

**Validaciones de config.**
- `duration_col` y `event_col` son requeridas: SDD-02 no fija columnas survival; inventarlas sería incorrecto.
- `duration_col != event_col`; ninguna columna configurable puede ser string vacío.
- `event_col` debe mapear a `{0,1}` al validar entrada; `1` significa evento/default observado.
- `duration_col` debe ser finita y positiva en filas modelables; `duration <= 0` levanta `SurvivalInputError`.
- `time_grid.horizon_periods` y `evaluation_times` no pueden estar ambos vacíos si el usuario exige proyección fuera del rango observado. Si ambos faltan, el motor solo evalúa hasta `max(duration_col)` observado y registra `FALTA-DATO-SUR-1`.
- `method="aft"` exige `cox_aft.aft_family` distinto de `None` hasta que Cami ratifique un default.
- `kaplan_meier.confidence_level` exige `confidence_transform` si se van a publicar bounds de IC; sin ambos, se publica Greenwood variance y se registra `FALTA-DATO-SUR-3`.
- `discrete_hazard.pd_role="offset"` exige `linear_predictor_column` finita y documenta que el coeficiente queda fijado; esto requiere ratificación en D-SUR-3.
- `input.pd_source="calibration"` exige artefacto `("calibration", "calibrated_pd_frame")` y columna `pd_calibrated` o una columna configurada futura.

**Defaults defendibles, sujetos a revisión.**
- `method="discrete_hazard"`: ESPECIFICACIONES §5.6 la llama ruta estándar IFRS 9 lifetime y reusa scoring.
- `link="logit"`: reusa el stack conceptual de scoring; `cloglog` queda disponible porque ESPECIFICACIONES §5.6 lo permite.
- `pd_source="model_raw"`: respeta la dependencia formal del índice (SDD-18 depende de SDD-08) sin exigir SDD-10.
- `pd_role="covariate"`: conserva trazabilidad de F1 sin fijar la PD como offset; queda para revisión en D-SUR-3.
- `confidence_level=None`, `ph_p_value_threshold=None`, `aft_family=None`, `horizon_periods=None`: no se inventan parámetros no presentes en ESPECIFICACIONES.

**Hook diferido en `core.config.schema`.** F5 debe extender el patrón real ya usado por dominios previos:
- declarar `_SURVIVAL_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir `survival` como campo `Any` en runtime y `SurvivalConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("survival", mode="before")` con nombre `_valida_survival`;
- sin `nikodym.survival` importado, conservar JSON canónico determinista; al importar, validar como `SurvivalConfig`.

## 6. Contratos de datos (I/O)

**Input duro del Step.**

| artefacto | requerido | contrato |
|---|---:|---|
| `("data", "frame")` | sí | `pandas.DataFrame` con columnas configuradas `duration_col`, `event_col`, y covariables opcionales |
| `("model", "raw_pd_frame")` | sí | output SDD-08 con índice original, `partition`, `target`, `linear_predictor`, `pd_raw` |
| `("calibration", "calibrated_pd_frame")` | condicional | requerido solo si `cfg.input.pd_source == "calibration"` |

**Input de `data.frame`.**
- Índice único o `id_col` único; si ambos existen, se valida consistencia.
- `duration_col`: numérico finito, positivo, unidad declarada en `time_grid.time_unit`.
- `event_col`: binario, `1` evento/default, `0` censura derecha.
- `segment_col`: opcional; si existe, se usa para agregados y KM por segmento cuando la config lo pida.
- `covariate_cols`: opcionales, finitas tras validación; categorías deben preprocesarse antes o ser manejadas por fórmula explícita futura. No se infiere encoding silencioso.

**Input de `model.raw_pd_frame`.**
- Mismo índice que las filas modelables de `data.frame` o superset alineable.
- Columnas reales SDD-08: `partition`, `target`, `linear_predictor`, `pd_raw`.
- `pd_raw ∈ (0,1)` y `linear_predictor` finito para filas modelables si se usan.
- Solo Desarrollo ajusta parámetros cuando el método es supervisado; Holdout/OOT se predicen con parámetros fijos.

**Output `term_structure`.** `pandas.DataFrame` tidy, una fila por `row_id/period` o por `segment/period` según granularidad configurada:

| columna | significado |
|---|---|
| `row_id` | identificador de observación; puede ser `None` si la salida es agregada por segmento |
| `segment` | segmento/pool opcional |
| `partition` | partición de F1 cuando aplica |
| `period` | entero ordinal de proyección |
| `time_value` | tiempo en la unidad declarada |
| `hazard` | `h(t)` si el método lo publica/deriva |
| `survival` | `S(t)` |
| `pd_marginal` | `S(t-1) * h(t)` según ESPECIFICACIONES §5.6 |
| `pd_cumulative` | `1 - S(t)` |
| `method` | ruta usada |
| `pd_source` | fuente PD F1 usada |
| `scenario` | `None` en SDD-18 base; SDD-20 puede poblarla o transformar |
| `warning_codes` | brechas/datos sospechosos por fila/período |

**Output `survival_curves`.** Contiene `row_id`/`segment`, `period`, `time_value`, `survival`, y si aplica `survival_lower`, `survival_upper`, `greenwood_variance`.

**Output `hazards`.** Contiene `row_id`/`segment`, `period`, `time_value`, `hazard`, `link`, `linear_predictor_hazard` cuando existe.

**Invariantes.**
- `survival` está en `[0,1]`, no aumenta con `t` dentro de cada curva salvo tolerancia numérica cero.
- `pd_marginal >= 0`, `pd_cumulative >= 0` y `pd_cumulative(t) = 1 - survival(t)` dentro de tolerancia.
- Para discrete hazard, `pd_marginal(t) = survival(t-1) * hazard(t)` y `survival(t) = survival(t-1) * (1 - hazard(t))`.
- `sum_t pd_marginal(t)` hasta el horizonte es igual a `pd_cumulative(horizon)` dentro de tolerancia.
- No muta `data.frame`, `model.raw_pd_frame` ni `calibration.calibrated_pd_frame`.
- Orden estable: el output preserva orden de entrada y orden ascendente de períodos.
- No se publican `NaN`, `inf` ni `-inf` en métricas numéricas finales; valores no estimables se representan con columna warning o falla, no con silencios.

## 7. Algoritmos y flujo

**`SurvivalStep.execute(study, rng)` - secuencia canónica.**
1. **Descartar azar.** `del rng`; survival v1 es determinista.
2. **Leer config.** Resolver `study.config.survival`; si falta en invocación programática, exigir `SurvivalConfig` explícito.
3. **Validar prerequisitos CT-1.** Exigir `data.frame` y `model.raw_pd_frame`.
4. **Validar prerequisitos condicionales.** Si `pd_source="calibration"`, exigir `calibration.calibrated_pd_frame`; si `method ∈ {"kaplan_meier","cox_ph","aft"}`, exigir lifelines; si `method="discrete_hazard"`, exigir statsmodels.
5. **Copias defensivas.** Copiar frames y validar índice único/alineación.
6. **Validar tiempo/evento.** Chequear duración positiva, evento binario, censura derecha y particiones.
7. **Unir PD F1.** Alinear `pd_raw`/`linear_predictor` por índice; registrar fuente y cobertura.
8. **Resolver grilla temporal.** Usar `evaluation_times`; si no existen, usar `horizon_periods`; si tampoco existe, usar tiempos observados y registrar `FALTA-DATO-SUR-1`.
9. **Ajustar método.** Instanciar `KaplanMeierSurvivalModel`, `DiscreteTimeHazardModel`, `CoxPHSurvivalModel` o `AFTSurvivalModel`.
10. **Predecir term-structure.** Calcular `hazard`, `survival`, `pd_marginal`, `pd_cumulative`.
11. **Construir DTOs.** `SurvivalDiagnostics`, `SurvivalCard`, `SurvivalResult`; poblar `metric_sections` con resumen estructurado.
12. **Auditar decisiones.** Método, link, PD source, cobertura de datos, tiempos, `FALTA-DATO`, Schoenfeld/AFT/KM.
13. **Publicar artefactos.** Escribir las siete claves `provides` bajo `"survival"`.

**`KaplanMeierSurvivalModel.fit(...)`.**
1. Ordenar por `duration_col`, preservando mapping a índice original.
2. En cada tiempo de evento `t_j`, computar `n_j`, `d_j` y censuras.
3. Calcular `S_hat(t)` por producto acumulado.
4. Calcular `greenwood_variance`; publicar IC solo si config trae `confidence_level` y `confidence_transform`.
5. Derivar `pd_cumulative = 1 - S_hat(t)` y `pd_marginal` como diferencia de acumulada por período o desde hazard discreto derivado si la grilla lo permite.

**`DiscreteTimeHazardModel.fit(...)`.**
1. Expandir `data.frame` a person-period hasta evento/censura/horizonte observado.
2. Construir target de período: `event_it = 1` solo en el período de default, `0` antes; no crear filas después del evento.
3. Construir covariables: interceptos por período, PD/logit F1 según `pd_role`, `covariate_cols` configuradas.
4. Ajustar con statsmodels:
   - `link="logit"`: GLM Binomial/Logit según disponibilidad y necesidad de fórmula;
   - `link="cloglog"`: GLM Binomial con link complementary log-log.
5. Convertir predicción lineal a `h_i(t)`.
6. Calcular `S_i(t)`, `PD_marginal_i(t)` y `PD_acumulada_i(t)` con la fórmula de ESPECIFICACIONES §5.6.

**`CoxPHSurvivalModel.fit(...)`.**
1. Preparar frame lifelines con `duration_col`, `event_col` y covariables.
2. Ajustar Cox PH con lifelines.
3. Ejecutar diagnóstico Schoenfeld si `ph_test_enabled=True`.
4. Publicar curva base y curvas por fila/segmento en la grilla temporal.
5. Si el test de PH falla según umbral configurado, aplicar política futura: en este borrador, registrar warning si no hay umbral y fallar solo si config lo exige.

**`AFTSurvivalModel.fit(...)`.**
1. Exigir `aft_family` configurada.
2. Ajustar el fitter lifelines correspondiente.
3. Predecir supervivencia/hazard o derivar hazard desde curvas cuando lifelines no lo entregue directo.
4. Publicar diagnósticos de familia, convergencia y warnings.

**Alternativas descartadas.**
- *Usar `scikit-survival`:* descartado por licencia GPL-3.0; ESPECIFICACIONES §7 lo permite solo research-only, nunca core distribuido.
- *Calcular lifetime PD como multiplicador plano de la PD 12m:* descartado; ESPECIFICACIONES §5.6 fija supervivencia/hazard y §5.5 consume PD marginal por período.
- *Usar bytes de parquet o `hash()` para reproducibilidad de outputs:* descartado; se conserva la regla del proyecto: contenido lógico por bloques y, si se materializan hashes auxiliares, endian explícito `astype("<u8")`.
- *Forzar SDD-02 a panel longitudinal IFRS 9:* descartado por CT-3; survival expande person-period localmente, pero no redefine el contrato de datos longitudinal.
- *Elegir familia AFT o nivel de confianza KM sin fuente:* descartado; queda config requerida/`FALTA-DATO`.

**Complejidad / rendimiento.** KM es O(n log n) por ordenamiento. Discrete hazard expande a O(n × T) filas; es la ruta de mayor costo y debe validar tamaño antes de materializar. Cox/AFT dependen del solver lifelines y del número de covariables; `selection`/F1 debe haber reducido dimensionalidad si se reutilizan covariables de scoring.

## 8. Casos borde y manejo de errores

- **Falta `data.frame` o `model.raw_pd_frame`:** `ArtifactNotFoundError` por CT-1 antes de entrar a `execute`.
- **`pd_source="calibration"` sin `calibrated_pd_frame`:** `ArtifactNotFoundError` o `SurvivalConfigError` con mensaje que cite `pd_source`.
- **Columnas `duration_col`/`event_col` ausentes:** `SurvivalInputError` listando columnas faltantes.
- **Duración no positiva, no finita o booleana:** `SurvivalInputError`.
- **Evento no binario:** `SurvivalInputError`; no se infieren defaults por strings.
- **Índice duplicado o unión PD ambigua:** `SurvivalInputError`.
- **Todas las filas censuradas:** KM puede publicar supervivencia plana con warning; discrete hazard/Cox/AFT levantan `SurvivalFitError` salvo modo diagnóstico futuro.
- **Sin censura o sin eventos suficientes por período:** warning o `SurvivalFitError` según método; si se usa `min_events_per_period`, se valida de forma ruidosa.
- **Separación perfecta o no convergencia en discrete hazard:** warning de statsmodels convertido a `SurvivalFitError` bajo `filterwarnings=["error"]`.
- **Hazard predicho fuera de `[0,1]`:** `SurvivalTransformError`; no se clipea silenciosamente.
- **Cox PH viola proporcionalidad:** si hay `ph_p_value_threshold` y el test incumple, acción según política futura; en este borrador se registra warning y D-SUR-7.
- **AFT sin familia:** `SurvivalConfigError`; no se elige familia por default.
- **Horizon/evaluation_times fuera del soporte observado:** se permite extrapolación solo si el método la soporta y la config lo declara; si no, `SurvivalTransformError`.
- **Valores missing en covariables:** error por default; imputación pertenece a `data`/preprocesamiento, no a `survival`.
- **Dependencia faltante:** `MissingDependencyError("instale nikodym[scoring]")` para statsmodels o `MissingDependencyError("instale nikodym[survival]")` para lifelines.

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen método, columna, partición, período y valor observado cuando aplique.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno en v1. `SurvivalStep.execute(study, rng)` recibe `rng` por contrato y debe hacer `del rng`.
- **Determinismo esperado.** `(data_hash + config_hash + model.raw_pd_frame + calibration.calibrated_pd_frame si aplica + uv.lock) → term_structure, diagnostics y card idénticos`.
- **Orden estable.** Frames de salida se ordenan por orden de entrada y período ascendente; no dependen de orden accidental de dict.
- **Normalización numérica.** Publicar `-0.0` como `0.0`; no usar `hash()` builtin; si se prueban hashes de frames, usar `pandas.util.hash_pandas_object` y convertir a enteros con endian explícito `.astype("<u8")`.
- **Audit trail (`log_decision`).** Registrar, como mínimo:
  - `survival_method`: método, link/familia, fuente PD y columnas de entrada;
  - `survival_time_grid`: unidad, horizonte, tiempos de evaluación y si hubo `FALTA-DATO-SUR-1`;
  - `survival_input_quality`: filas, eventos, censuras, missing/exclusiones;
  - `survival_pd_source`: artefacto fuente, columna PD/logit, cobertura y filas sin match;
  - `survival_person_period`: número de filas expandidas, períodos y eventos por período;
  - `survival_km_greenwood`: si aplica, varianza/IC y configuración de intervalo;
  - `survival_schoenfeld`: resultado del test Cox PH si aplica;
  - `survival_aft`: familia, convergencia y warnings si aplica.
- **Card / report.** `SurvivalCard` debe permitir reconstruir el ajuste: método, definición de tiempo/evento, fuente PD, grilla temporal, conteos, diagnósticos, versiones de dependencias y `FALTA-DATO`.
- **Lineage.** `survival` no completa `data_hash` ni `config_hash`; los consume. Su aporte al lineage son config computacional, versiones de dependencias, fuente PD, term-structure hashable y decisiones auditadas.
- **Gobernanza CT-2.** `metric_sections` puede incluir secciones estructuradas como `"term_structure_summary"`, `"schoenfeld"`, `"km_greenwood"` y `"person_period"`, sin romper consumidores escalares.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymError`, `MissingDependencyError`, lineage, `config_hash`, `ProvisionResultLike.term_structure()` como patrón CT-2.
- SDD-02 (`data`): `frame`, `data_hash`, particiones, frontera transversal de scorecard y mecanismo de hash lógico.
- SDD-05 (convenciones): config Pydantic, hooks diferidos, API sklearn-like donde calza y clase base propia donde no calza.
- SDD-08 (`model`): `raw_pd_frame` con `partition`, `target`, `linear_predictor`, `pd_raw`; fuente PD default del Step.
- SDD-10 (`calibration`): dependencia condicional si `pd_source="calibration"`.

**Aguas abajo.**
- SDD-16 (`provisioning/ifrs9`) consume `term_structure()` para ECL 12m/lifetime y añade LGD/EAD/staging/descuento.
- SDD-17 (`provisioning`) usa la salida IFRS 9 resultante para comparar contra piso CMF.
- SDD-20 (`forward`) ajusta/transforma term-structures con macro/satellite y escenarios ponderados.
- SDD-21 (`stress`) consume term-structures bajo escenarios severos.
- SDD-22 (`validation`) backtestea lifetime PD y diagnósticos survival.
- SDD-23 (`ui`) edita config y muestra brechas `FALTA-DATO`.
- SDD-26 (`report`) renderiza curvas, diagnostics y card.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | `>=2.0` (`pyproject.toml`) | BSD-3 ✅ | I/O tabular, person-period, term-structure | base |
| numpy | `>=1.22` (`pyproject.toml`) | BSD ✅ | operaciones vectoriales, finitud | base |
| pydantic | `>=2` | MIT ✅ | config/DTOs frozen | base |
| statsmodels | `>=0.14` (`pyproject.toml`, extra `scoring`) | BSD ✅ | discrete hazard logit/cloglog vía GLM/Logit | extra `[scoring]` |
| scipy | `>=1.10` (`pyproject.toml`, extra `scoring`) | BSD ✅ | funciones numéricas transitivas/diagnósticas | extra `[scoring]` |
| lifelines | `>=0.28` (`pyproject.toml`, extra `survival`) | MIT ✅ | Kaplan-Meier, Cox PH, Schoenfeld, AFT | extra `[survival]` |
| scikit-survival | no permitido en core | GPL-3.0 ❌ | research-only fuera del paquete distribuido | vetado |

**Licencia crítica D-LIC.** ESPECIFICACIONES §7 y `pyproject.toml` excluyen dependencias copyleft del core distribuido. `scikit-survival` no puede aparecer en imports, extras redistribuibles, tests obligatorios ni documentación de instalación del core. Si se explora en research, debe vivir fuera del paquete y sin path de ejecución en Nikodym.

**Núcleo liviano.** `nikodym.core` no importa `nikodym.survival`, lifelines ni statsmodels. `import nikodym.survival` registra config/step sin cargar lifelines/statsmodels en top-level. Las dependencias pesadas se importan dentro de `fit`/`execute` y fallan con `MissingDependencyError` claro.

**Packaging a ratificar.** Hoy `pyproject.toml` define `survival = ["lifelines>=0.28"]` y `scoring = ["statsmodels>=0.14", ...]`. Como la ruta default `discrete_hazard` requiere statsmodels, el uso completo del Step requiere `nikodym[scoring,survival]` o que Cami ratifique mover/duplicar statsmodels en el extra `survival` (D-SUR-9).

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **Golden KM simple.** Dataset pequeño con tiempos/eventos conocidos; verificar `S_hat(t)=∏(1-d/n)` y `greenwood_variance` a mano.
- **Greenwood sin IC default.** Con `confidence_level=None`, se publica varianza y `FALTA-DATO-SUR-3`; con nivel/transformación configurados, se publican bounds finitos y ordenados.
- **Golden discrete hazard.** Hazards fijos `h(1)=0.10`, `h(2)=0.20`: `S(1)=0.90`, `PD_marginal(1)=0.10`, `S(2)=0.72`, `PD_marginal(2)=0.18`, `PD_acumulada(2)=0.28`.
- **Person-period.** Una fila con evento en período 3 genera filas `t=1,2,3` y target de período `0,0,1`; una censurada en período 2 genera `0,0` y no filas posteriores.
- **Contrato con F1.** `SurvivalStep.requires` exige `data.frame` y `model.raw_pd_frame`; falta uno → `ArtifactNotFoundError`. `pd_source="calibration"` exige `calibration.calibrated_pd_frame`.
- **No leakage.** Cambiar target de Holdout/OOT no cambia coeficientes/hazards ajustados; solo Desarrollo ajusta parámetros supervisados.
- **No mutación.** Snapshots profundos de `data.frame`, `model.raw_pd_frame` y `calibrated_pd_frame` permanecen iguales.
- **Invariantes term-structure.** `survival` monótona no creciente, `PD_marginal >= 0`, `PD_acumulada = 1 - survival`, suma de marginales igual a acumulada.
- **Statsmodels warnings.** Separación perfecta/no convergencia en discrete hazard se convierte en `SurvivalFitError` bajo `filterwarnings=["error"]`.
- **Cox Schoenfeld.** Fixture donde el diagnóstico se publica en `SurvivalDiagnostics.schoenfeld_test`; sin umbral configurado no se falla por default.
- **AFT sin familia.** `method="aft"` con `aft_family=None` levanta `SurvivalConfigError`.
- **Licencia/import guard.** `import nikodym.core` no importa `nikodym.survival`; `import nikodym.survival` no importa lifelines/statsmodels; no existe import de `sksurv`/`scikit-survival`.
- **Config.** Round-trip YAML; cambiar método, link, `pd_source`, columnas o horizonte cambia `config_hash`; campos requeridos sin valor fallan.
- **Endianness/hash.** Si se comparan hashes de outputs, usar contenido lógico y `.astype("<u8")`; nunca bytes de parquet ni `hash()`.
- **Mypy/ruff.** `mypy --strict` sobre el paquete; wrappers sin stubs usan `cast()`/`ignore` localizados y justificados. Ruff D exige docstrings públicas en español.

Fixtures: `survival_small.parquet` sintético con duración/evento, `raw_pd_frame` de SDD-08, `calibrated_pd_frame` opcional, `SurvivalConfig` mínimo por método, `InMemoryAuditSink`, y datasets degenerados para censura total, índice duplicado, missing y hazards extremos.

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Confundir PD 12m/transversal con PD lifetime.** Mitigación: `model.raw_pd_frame` es insumo, no salida final; `survival.term_structure` publica PD marginal/acumulada por período.
- **Inventar horizonte o unidad temporal.** Mitigación: `duration_col` es requerido; `horizon_periods=None` registra `FALTA-DATO-SUR-1`; SDD-16 debe traer maturities/ECL.
- **Sobreajustar person-period por expansión O(n×T).** Mitigación: validar tamaño, eventos por período y publicar diagnostics.
- **Violación de proporcionalidad en Cox.** Mitigación: diagnóstico Schoenfeld obligatorio cuando `method="cox_ph"`; política de acción queda para Cami.
- **Uso accidental de GPL.** Mitigación: veto explícito a `scikit-survival`, test de import y revisión de extras.
- **Term-structure incompatible con SDD-16.** Mitigación: output tidy mínimo y CT-2; SDD-16 puede añadir columnas económicas sin romper SDD-18.
- **Datos longitudinales forzados sobre SDD-02.** Mitigación: CT-3; `survival` solo expande localmente para hazard, no redefine la capa longitudinal IFRS 9.
- **Defaults estadísticos malinterpretados como normativos.** Mitigación: los parámetros no fijados en ESPEC quedan `None`, requeridos o `FALTA-DATO`.

**FALTA-DATO explícitos.**
- **FALTA-DATO-SUR-1 — Horizonte lifetime y granularidad temporal.** ESPECIFICACIONES §5.6 no fija `horizon_periods`, unidad mensual/trimestral/anual ni regla de extrapolación; SDD-16 debe aportar maturities o Cami debe fijar default.
- **FALTA-DATO-SUR-2 — Definición operacional de evento/default y censura.** SDD-02 tiene target binario de scorecard, pero no define duración, cura, refinanciación, prepago ni competing risks.
- **FALTA-DATO-SUR-3 — Nivel y transformación de IC Kaplan-Meier.** ESPECIFICACIONES §5.6 autoriza KM, pero no fija `confidence_level` ni `plain` vs `loglog`.
- **FALTA-DATO-SUR-4 — Rol exacto de la PD F1 en discrete hazard.** ESPECIFICACIONES dice que reusa scoring, pero no fija covariable vs offset vs segmentación.
- **FALTA-DATO-SUR-5 — Grano de salida.** Cuenta, operación, cliente o segmento/pool debe definirse por datos/negocio; el SDD soporta fila o segmento.
- **FALTA-DATO-SUR-6 — Shape final IFRS 9.** SDD-18 publica lifetime PD; SDD-16 debe fijar columnas económicas finales de ECL/stage/EIR/LGD/EAD/escenario.
- **FALTA-DATO-SUR-7 — Umbrales de diagnóstico Cox/Schoenfeld.** No hay p-value ni acción normativa en ESPECIFICACIONES.
- **FALTA-DATO-SUR-8 — Familia AFT default.** ESPECIFICACIONES menciona AFT, pero no Weibull/lognormal/loglogistic.
- **FALTA-DATO-SUR-9 — Pesos de observación/exposición.** No está definido si survival pondera por exposición, saldo, cuenta o peso muestral.

**Fuentes verificadas / citas.**
- **ESPECIFICACIONES.md** §5.5: ECL multi-período, `PD_marg_k(t)`, Stage 1 12m y Stage 2/3 lifetime.
- **ESPECIFICACIONES.md** §5.6: forward-looking, survival lifetime PD, Kaplan-Meier, Cox PH (Schoenfeld), AFT, discrete-time hazard logit/cloglog person-period, `S(t)=∏(1−h_j)`, `PD_marg(t)=S(t−1)·h(t)`, cadena forward y consistencia PIT.
- **ESPECIFICACIONES.md** §6.1/§6.3: survival usa clase base propia por entrada evento+tiempo; paquete `survival/` = KM, Cox, AFT, discrete-time hazard lifetime PD.
- **ESPECIFICACIONES.md** §7: lifelines MIT permitido; `scikit-survival` GPL-3.0 no entra al core distribuido.
- **ROADMAP.md** F5: Survival (KM, Cox, AFT, discrete-time hazard) → lifetime PD; reusa stack de regresión; DoD con curvas lifetime PD reproducibles.
- **docs/design/00-INDICE.md** fila SDD-18: `survival` (KM/Cox/AFT/discrete-time), Forward, F5, T5, depende de SDD-08.
- **_CONTRATOS-TRANSVERSALES.md** CT-1/CT-2/CT-3: `requires`/`provides`, `term_structure()`, frontera transversal vs longitudinal.
- **SDD-08 (`model`)**: `raw_pd_frame` con `partition`, `target`, `linear_predictor`, `pd_raw`; PD cruda no calibrada.
- **SDD-10 (`calibration`)**: `calibrated_pd_frame` como dependencia condicional, no dura, porque el índice de SDD-18 depende formalmente de SDD-08.

## Decisiones para revisión de Cami

- **D-SUR-1 — Método default.** Recomendación: `method="discrete_hazard"`, porque ESPECIFICACIONES §5.6 lo llama estándar IFRS 9 lifetime y reusa el stack de scoring. KM/Cox/AFT quedan como rutas diagnósticas o alternativas configuradas.
- **D-SUR-2 — Link default discrete hazard.** Recomendación: `link="logit"` por continuidad con scoring/statsmodels; `cloglog` queda disponible. Confirmar si Cami prefiere `cloglog` como default por interpretación de hazard discreto aproximando tiempo continuo.
- **D-SUR-3 — Rol de la PD F1.** Recomendación inicial: usar `model.raw_pd_frame.linear_predictor`/`pd_raw` como covariable (`pd_role="covariate"`), no como offset fijo. Offset conserva más la PD F1 pero impone una restricción no especificada; segmentación reduce granularidad.
- **D-SUR-4 — Fuente PD default.** Recomendación: `pd_source="model_raw"` para respetar la dependencia SDD-08 del índice. Permitir `pd_source="calibration"` como opt-in cuando SDD-10 esté presente y Cami quiera partir de PD calibrada.
- **D-SUR-5 — Horizonte lifetime.** Recomendación: no fijar horizonte por default; usar observado solo para diagnóstico y exigir `horizon_periods`/maturities para ECL. Confirmar si F5 debe adoptar un default mensual/anual.
- **D-SUR-6 — Shape de `term_structure`.** Recomendación: tidy mínimo `row_id/segment/period/time_value/hazard/survival/pd_marginal/pd_cumulative/method/pd_source/scenario`. SDD-16 añade campos económicos; no duplicar ECL aquí.
- **D-SUR-7 — Política Schoenfeld.** Recomendación: publicar test siempre en Cox PH; sin umbral configurado, warning no bloqueante. Confirmar p-value y acción default si se quiere fail-fast.
- **D-SUR-8 — AFT family.** Recomendación: no default hasta ratificación; exigir `aft_family`. Si Cami quiere default, elegirlo explícitamente y documentar fuente.
- **D-SUR-9 — Packaging de extras.** Recomendación: documentar que la ruta F5 completa requiere `nikodym[scoring,survival]`. Alternativa: añadir `statsmodels>=0.14` también al extra `survival` cuando se implemente, para que el método default funcione con un solo extra.
- **D-SUR-10 — KM confidence intervals.** Recomendación: publicar Greenwood variance siempre; publicar IC solo si config trae `confidence_level` y `confidence_transform`. Confirmar si se fija 95% log-log como convención Nikodym.
- **D-SUR-11 — Pesos.** Recomendación: v1 sin pesos por default; si la institución requiere exposure-weighted lifetime PD, que entre por config y card, no por inferencia silenciosa.
- **D-SUR-12 — Competing risks/prepayment.** Recomendación: fuera de v1; default single-event default/censura derecha. Si SDD-16 necesita prepago para EAD, diseñarlo allí o en capa longitudinal.
