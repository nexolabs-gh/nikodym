# SDD-20 — `forward` (forward-looking macro, satellite models y escenarios)

| Campo | Valor |
|---|---|
| **SDD** | 20 |
| **Módulo** | `nikodym.forward` |
| **Dominio** | Forward / dinámica macro / IFRS 9 forward-looking |
| **Fase** | F5 |
| **Tanda de producción** | T5 (Forward-looking & dinámica) |
| **Estado** | ✅ Implementado; API experimental |
| **Depende de** | SDD-01 (`core`), SDD-02 (`data` base/hash), SDD-05 (convenciones + config), SDD-18 (`survival`), SDD-19 (`markov`) |
| **Lo consumen** | SDD-16 (`provisioning/ifrs9`), SDD-17 (`provisioning`), SDD-21 (`stress`), SDD-22 (`validation`), SDD-23 (`ui`), SDD-26 (`report`) |
| **Autor / Fecha** | Codex (worker A9, redacción SDD-20 para T5) / 2026-06-29 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `forward` proyecta factores macroeconómicos, los propaga mediante modelos satellite a PD/LGD forward-looking por escenario, y entrega una term-structure PIT multiescenario lista para que el motor IFRS 9/ECL la consuma.

**Responsabilidad única (qué SÍ hace).**
- Ajusta modelos de proyección macroeconómica: ARIMA, SARIMA, ARIMAX, VAR y VECM.
- Ejecuta diagnóstico Ljung-Box sobre residuos de modelos macro cuando el método lo permite.
- Produce proyecciones macro con horizonte explícito y trazabilidad de método, variables, frecuencia y versión de dependencias.
- Por política default de Nikodym (`require_at_least_three=True`), exige escenarios `base`, `adverse` y `severe`, con pesos explícitos que suman 1. IFRS 9 no prescribe ese número fijo.
- Implementa un guard ruidoso contra el "escenario medio": se ponderan outputs por escenario, nunca inputs macro promediados.
- Ajusta y aplica `SatelliteModel` en forma Wilson/CreditPortfolioView: `logit(PD)` y, si aplica, `logit(LGD)` como función de factores macro.
- Consume la term-structure base de `survival` (SDD-18) y/o `markov` (SDD-19), sin rediseñar esos motores.
- Recalcula `hazard`, `survival`, `pd_marginal` y `pd_cumulative` para cada escenario preservando identidades lifetime.
- Aplica reversión a media TTC más allá del horizonte reasonable & supportable mediante una regla configurada y auditada.
- Publica artefactos namespaced bajo `"forward"`: proyección macro, term-structure forward-looking, pesos de escenario, diagnostics, result, card y bundle consumido por el ECL vigente.
- Aporta `ForwardConfig` como sección computacional de `NikodymConfig`; por tanto, cambios de modelo, horizonte, escenarios o reversiones mueven el `config_hash`.
- Registra con `log_decision` la cadena completa `macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting`.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No calcula ECL.** SDD-16 (`provisioning/ifrs9`) consume la term-structure forward-looking y calcula `Σ_t PD_marg_k(t)·LGD_k(t)·EAD_k(t)/(1+EIR)^t`.
- **No implementa staging, SICR, EAD, CCF, EIR ni descuento.** Esos contratos pertenecen a SDD-16.
- **No aplica la regla del máximo B-1.** SDD-17 compara fuentes configurables; el binding normativo
  chileno es método estándar CMF frente a método interno, por institución. Un comparativo con IFRS 9
  es informativo entre marcos y no constituye el piso prudencial.
- **No rediseña `survival` ni `markov`.** SDD-18 y SDD-19 son dueños de lifetime PD/term-structure base; `forward` solo las consume y transforma.
- **No implementa la transformación PIT Vasicek monofactorial.** Es una opción metodológica de Nikodym ubicada en SDD-16; IFRS 9 exige información forward-looking y ponderación probabilística, pero no prescribe esa fórmula. `forward` conserva la metadata PIT/TTC para que SDD-16 decida cómo consumirla.
- **No diseña el panel longitudinal económico completo.** CT-3 reserva esa capa para IFRS 9/forward; este SDD fija solo los contratos de entrada/salida que `forward` necesita.
- **No hace stress testing.** SDD-21 consume escenarios y satellite models para sensibilidad, reverse stress y escenarios severos fuera del caso base IFRS 9.
- **No inventa shocks macro regulatorios, tasas EIR, maturities, umbrales SICR ni parámetros externos.** Lo no especificado queda como config requerida o `FALTA-DATO-FWD`.
- **No usa `df.eval`, `eval` ni expresiones de usuario ejecutables.** Fórmulas satellite se representan como listas de columnas y coeficientes tipados.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Forward-looking & dinámica (F5/T5), puente entre lifetime PD (SDD-18/19) y ECL IFRS 9 (SDD-16).
- **Quién lo invoca:** `Study.run()` como sección `forward` de `NikodymConfig`, o API programática para ajustar/proyectar macro y aplicar satellite models.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, excepciones, lineage), `data` base solo para hash lógico/validación de frames cuando se reutilicen helpers, y dependencias estadísticas perezosas.
- **Dependencias duras de dominio:** SDD-18 y SDD-19. La term-structure base debe venir de `survival`, de `markov` o de ambas según config.
- **Dependencias duras base:** SDD-01, SDD-02 y SDD-05. No hay dependencia runtime sobre SDD-16: el motor IFRS 9 vigente consume el DTO estable sin ser importado por `forward`.

```text
macro_history ─► macro_projection ─► projected_macro_by_scenario ─┐
                                                                   ▼
survival.term_structure ─┐                              satellite_model
                         ├──► pd_lgd_term_structure ───────────────┤
markov.term_structure ───┘                                         ▼
                                                       forward_term_structure
                                                                   ▼
                                              ecl_engine vigente (SDD-16)
                                                                   ▼
                                                 scenario_weighting outputs
```

**Cadena obligatoria de ESPECIFICACIONES §5.6.**
- `macro_projection`: proyecta factores macro por horizonte y escenario.
- `satellite_model`: traduce macro a ajustes de PD/LGD en escala logit.
- `pd_lgd_term_structure`: frame tidy compatible con SDD-18/19, extendido con columnas forward.
- `ecl_engine`: motor IFRS 9 vigente; `forward` define el contrato de input y SDD-16 calcula ECL.
- `scenario_weighting`: SDD-16 pondera outputs del ECL por escenario; nunca inputs macro.

**Consistencia PIT.** Toda fila de salida debe declarar `pd_basis` y `basis_state`:
- `pd_basis="pit"` para el tramo reasonable & supportable ajustado por macro;
- `basis_state="blended"` durante reversión;
- `basis_state="ttc"` cuando la reversión ya llegó completamente al ancla TTC.

La consistencia no significa que `forward` convierta todo con Vasicek. Significa que no mezcla curvas TTC/PIT sin etiqueta, no promedia macro inputs, y entrega a SDD-16 la metadata suficiente para aplicar la transformación PIT/TTC que le corresponde.

**Interacción con `Study` y config declarativo.** `ForwardStep` es un `Step` nativo registrado con `@register("standard", domain="forward")`. Se construye desde `ForwardConfig`; por eso sus `requires` pueden ser dinámicos:
- si `cfg.input.term_structure_sources=("survival",)`, requiere `("survival","term_structure")`;
- si `("markov",)`, requiere `("markov","term_structure")`;
- si ambas, requiere ambas claves;
- si `cfg.input.macro_source.type="artifact"`, requiere la clave macro configurada;
- si `cfg.input.macro_source.type="path"`, no requiere artefacto macro, pero registra hash/fuente en lineage.

Esto cumple CT-1: el objeto `Step` ya resuelto expone el DAG efectivo antes de ejecutar y el motor v1 puede validar prerequisitos.

**Cableado implementado en `core.study`.**
- `_DOMAIN_MODULES["forward"] = "nikodym.forward"`;
- `_DOMAIN_CONFIG_CLASSES["forward"] = ("nikodym.forward.config", "ForwardConfig")`;
- `_DEFAULT_DOMAIN_ORDER` ubica `"forward"` después de `"survival"`/`"markov"` cuando estén presentes y antes de `"stress"`/`"provisioning_ifrs9"` si se ejecutan en el mismo run;
- el scheduler topológico real sigue siendo la deuda F5 de CT-1, pero la firma `requires`/`provides` ya expresa el grafo.

**Paquete físico y troceo B20.x.**

```text
src/nikodym/forward/
  __init__.py
  config.py
  exceptions.py
  results.py
  macro.py
  satellite.py
  scenarios.py
  step.py
```

**B20.1 - `config.py` + `exceptions.py`.**
`ForwardConfig`, jerarquía de errores, hook diferido en `NikodymConfig`, round-trip YAML, defaults D-FWD y validaciones sin imports pesados.

**B20.2 - `results.py`.**
DTOs frozen para proyección macro, satellite diagnostics, term-structure forward, pesos de escenario, card y bundle de input para el ECL vigente.

**B20.3 - `macro.py`.**
`MacroProjectionModel`, ARIMA/SARIMA/ARIMAX/VAR/VECM, `fit/predict(horizon=...)`, Ljung-Box y determinismo.

**B20.4 - `satellite.py`.**
`SatelliteModel`, ajuste Wilson/CreditPortfolioView, predicción de ajustes PD/LGD por escenario y recomposición de curvas lifetime.

**B20.5 - `scenarios.py`.**
`ScenarioWeighting`, validación de pesos, guard anti escenario medio, reversión TTC y ponderación de outputs.

**B20.6 - `step.py` + cableado.**
`ForwardStep`, `@register(domain="forward")`, CT-1 dinámico, publicación de artefactos, audit trail y prueba end-to-end `Study`.

## 3. Conceptos y fundamentos

**Fuente normativa/metodológica interna.**
- ESPECIFICACIONES §5.5 adopta Vasicek como opción metodológica de Nikodym para TTC→PIT. IFRS 9 exige información forward-looking y resultados ponderados por probabilidad, sin prescribir esa fórmula.
- ESPECIFICACIONES §5.6 fija macro ARIMA/SARIMA/ARIMAX, VAR/VECM, Ljung-Box, escenarios ponderados, satellite models y cadena forward.
- ROADMAP F5 ubica `forward` como entregable macro + satellite + escenarios ponderados, cerrando el lifetime requerido por F4.
- CT-1 exige `requires`/`provides`; CT-2 exige term-structure tidy; CT-3 separa datos transversales de longitudinales.

**Notación.**
- `k ∈ K`: escenario macro (`base`, `adverse`, `severe`, u otros configurados).
- `w_k`: peso de probabilidad del escenario, `w_k ≥ 0` y `Σ_k w_k = 1`.
- `t = 1, ..., H`: horizonte explícito de proyección.
- `x_{k,t}`: vector de factores macro proyectados en escenario `k` y período `t`.
- `PD^0_{i,t}`: PD base de la term-structure de `survival`/`markov`.
- `h^0_{i,t}`: hazard base del período `t`.
- `η^PD_{i,k,t}`: predictor lineal satellite para PD/hazard.
- `λ_t`: peso de tramo reasonable & supportable; `λ_t=1` antes de la reversión y `λ_t=0` al llegar a TTC.
- `PD^{FWD}_{i,k,t}`: PD forward-looking del período `t` bajo escenario `k`.

**Macro projection.** Para series univariadas se permiten:

```text
ARIMA(p,d,q): φ(B)(1-B)^d y_t = c + θ(B)ε_t
SARIMA(p,d,q)(P,D,Q)_s: agrega polinomios estacionales
ARIMAX: y_t = β'z_t + componente ARIMA en el error
```

Para sistemas multivariados se permiten:

```text
VAR(p): y_t = c + A_1 y_{t-1} + ... + A_p y_{t-p} + ε_t
VECM: Δy_t = αβ'y_{t-1} + Γ_1Δy_{t-1} + ... + Γ_{p-1}Δy_{t-p+1} + ε_t
```

`statsmodels` es la ruta primaria por transparencia y cobertura ARIMA/VAR/VECM. `pmdarima` queda como ruta opcional para `auto_arima` cuando la institución quiere búsqueda de orden. Si `auto_arima` usa búsqueda aleatoria, debe tener `random_state` explícito; por default se prohíbe `random=True`.

**Diagnóstico Ljung-Box.** Sobre residuos `e_t`, se contrasta autocorrelación conjunta hasta lags configurados:

```text
H0: ρ_1 = ρ_2 = ... = ρ_m = 0
```

El resultado se publica en diagnostics con estadístico, p-value, lags y acción configurada. No se elige ni cambia el modelo automáticamente por un p-value; se audita y, si `fail_on_ljung_box=True`, se falla de forma ruidosa.

**Satellite model Wilson/CreditPortfolioView.** La forma central es:

```text
logit(h_{i,k,t}) = logit(h^0_{i,t}) + α_s + β_s' · Δx_{k,t}
```

donde `s` es segmento/pool opcional y `Δx_{k,t}` se define respecto de una ruta base o una media histórica configurada. A partir del hazard ajustado:

```text
S_{i,k,0} = 1
PD_marg_{i,k,t} = S_{i,k,t-1} · h_{i,k,t}
S_{i,k,t} = S_{i,k,t-1} · (1 - h_{i,k,t})
PD_cum_{i,k,t} = 1 - S_{i,k,t}
```

Esta ruta preserva monotonicidad de PD acumulada y compatibilidad con las columnas de `survival`/`markov`. Si la term-structure trae LGD base, el satellite LGD usa escala logit para mantener `[0,1]`:

```text
logit(LGD_{i,k,t}) = logit(LGD^0_{i,t}) + γ_s' · Δx_{k,t}
```

Si no hay LGD base, `forward` solo ajusta PD y deja `lgd` ausente; SDD-16 podrá aportar LGD/EAD.

**Escenarios ponderados.** El resultado económico final de IFRS 9 debe calcularse como:

```text
ECL_weighted = Σ_k w_k · ECL_k
```

No es válido construir `x_mean,t = Σ_k w_k x_{k,t}` y correr el satellite una sola vez, porque `logit^{-1}` es no lineal:

```text
Σ_k w_k · sigmoid(a + β'x_{k,t}) ≠ sigmoid(a + β'Σ_k w_k x_{k,t})
```

El guard anti escenario medio es parte del contrato: si config, API o input intentan marcar una fila `scenario="mean"` como reemplazo de escenarios ponderados, `ForwardScenarioError`.

**Reversión TTC.** Más allá del horizonte reasonable & supportable `H_RS`, la salida debe converger al ancla TTC:

```text
λ_t = 1                                  si t <= H_RS
λ_t = max(0, 1 - (t - H_RS) / R)          si H_RS < t <= H_RS + R
λ_t = 0                                  si t > H_RS + R
logit(h^{final}_{i,k,t}) = λ_t·logit(h^{PIT}_{i,k,t}) + (1-λ_t)·logit(h^{TTC}_{i,t})
```

El default defendible propuesto es `H_RS=12` períodos y `R=24` períodos con reversión lineal en escala logit, **default a confirmar por Cami**. No es número regulatorio; es una convención metodológica editable.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

`config.py` expone `ForwardConfig` y submodelos `MacroSourceConfig`, `MacroModelConfig`, `SatelliteConfig`, `ScenarioDefinitionConfig`, `ScenarioConfig`, `TtcReversionConfig`, `ForwardInputConfig` y `ForwardValidationConfig` (§5).

```python
# nikodym/forward/exceptions.py
class ForwardError(NikodymError): ...
class ForwardConfigError(ForwardError): ...
class ForwardInputError(ForwardError): ...
class ForwardFitError(ForwardError): ...
class ForwardPredictionError(ForwardError): ...
class ForwardScenarioError(ForwardError): ...
class PitConsistencyError(ForwardError): ...
class MacroProjectionError(ForwardPredictionError): ...
class SatelliteModelError(ForwardPredictionError): ...
```

```python
# nikodym/forward/macro.py
class MacroProjectionModel:
    config_cls: ClassVar[type[ForwardConfig]] = ForwardConfig

    @classmethod
    def from_config(cls, cfg: ForwardConfig) -> "MacroProjectionModel": ...

    def fit(
        self,
        macro_frame: "pandas.DataFrame",
        *,
        audit: "AuditSink | None" = None,
    ) -> "Self": ...

    def predict(
        self,
        *,
        horizon: int,
        scenario_frame: "pandas.DataFrame | None" = None,
    ) -> "pandas.DataFrame": ...

    def residual_diagnostics(self) -> "MacroDiagnostics": ...
```

**Atributos fiteados macro.** `macro_variables_`, `time_index_`, `frequency_`, `models_`, `residuals_`, `diagnostics_` y `dependency_versions_`.

```python
# nikodym/forward/satellite.py
class SatelliteModel:
    config_cls: ClassVar[type[ForwardConfig]] = ForwardConfig

    @classmethod
    def from_config(cls, cfg: ForwardConfig) -> "SatelliteModel": ...

    def fit(
        self,
        historical_term_structure: "pandas.DataFrame",
        macro_history: "pandas.DataFrame",
        *,
        audit: "AuditSink | None" = None,
    ) -> "Self": ...

    def predict(
        self,
        term_structure: "pandas.DataFrame",
        macro_projection: "pandas.DataFrame",
        *,
        scenarios: "ScenarioWeighting",
    ) -> "pandas.DataFrame": ...
```

**Atributos fiteados satellite.** `target_components_`, `factor_columns_`, `coefficients_`, `reference_macro_`, `fit_statistics_` y `diagnostics_`.

```python
# nikodym/forward/scenarios.py
class ScenarioWeighting:
    config_cls: ClassVar[type[ForwardConfig]] = ForwardConfig

    @classmethod
    def from_config(cls, cfg: ForwardConfig) -> "ScenarioWeighting": ...

    def validate_macro_projection(self, frame: "pandas.DataFrame") -> None: ...

    def apply_ttc_reversion(
        self,
        forward_term_structure: "pandas.DataFrame",
        *,
        ttc_anchor: "pandas.DataFrame",
    ) -> "pandas.DataFrame": ...

    def weight_outputs(
        self,
        output_by_scenario: "pandas.DataFrame",
        *,
        value_cols: tuple[str, ...],
        group_cols: tuple[str, ...],
    ) -> "pandas.DataFrame": ...
```

`weight_outputs` solo acepta outputs ya calculados por escenario. Si el frame no tiene columna `scenario`, si falta algún escenario con peso positivo o si aparece `scenario="mean"` como sustituto, levanta `ForwardScenarioError`.

```python
# nikodym/forward/results.py
class MacroDiagnostics(BaseModel): ...
class SatelliteDiagnostics(BaseModel): ...
class ScenarioDiagnostics(BaseModel): ...
class ForwardCard(BaseModel): ...
class MacroProjectionResult(BaseModel): ...
class SatelliteResult(BaseModel): ...
class ForwardEclInput(BaseModel): ...

class ForwardResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    macro_projection_frame: "pandas.DataFrame"
    forward_term_structure_frame: "pandas.DataFrame"
    scenario_weight_frame: "pandas.DataFrame"
    diagnostics: ForwardDiagnostics
    card: ForwardCard
    ecl_input: ForwardEclInput
    def term_structure(self) -> "pandas.DataFrame | None": ...
```

`ForwardResult.term_structure()` cumple CT-2 y retorna la term-structure forward-looking tidy cuando existe. `ForwardEclInput` es el gancho hacia SDD-16: contiene term-structure por escenario, pesos, metadata PIT/TTC y advertencias; no importa ni instancia el motor ECL.

```python
# nikodym/forward/step.py
@register("standard", domain="forward")
class ForwardStep(AuditableMixin):
    name: str = "forward"
    requires: tuple[ArtifactKey, ...]
    provides: tuple[ArtifactKey, ...] = (
        ("forward", "macro_model"),
        ("forward", "macro_projection"),
        ("forward", "satellite_model"),
        ("forward", "term_structure"),
        ("forward", "scenario_weights"),
        ("forward", "scenario_weighting"),
        ("forward", "ecl_input"),
        ("forward", "diagnostics"),
        ("forward", "result"),
        ("forward", "card"),
    )
    @classmethod
    def from_config(cls, cfg: ForwardConfig) -> "ForwardStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "ForwardResult": ...
```

**Artefactos que `ForwardStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"macro_model"` | `MacroProjectionModel` | modelo macro fiteado |
| `"macro_projection"` | `pandas.DataFrame` | proyección macro por escenario/período/variable |
| `"satellite_model"` | `SatelliteModel` | modelo satellite fiteado o cargado desde coeficientes |
| `"term_structure"` | `pandas.DataFrame` | PD/LGD forward-looking tidy por escenario |
| `"scenario_weights"` | `pandas.DataFrame` | escenarios, pesos, fuente y flags |
| `"scenario_weighting"` | `ScenarioWeighting` | objeto para ponderar outputs ECL por escenario |
| `"ecl_input"` | `ForwardEclInput` | contrato sin dependencia dura hacia SDD-16 |
| `"diagnostics"` | `ForwardDiagnostics` | macro, satellite, PIT, reversion, guard anti media |
| `"result"` | `ForwardResult` | contenedor agregado |
| `"card"` | `ForwardCard` | resumen governance/report con `metric_sections` CT-2 |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "model", "survival", "markov", "forward"])
ecl_input = study.artifacts.get("forward", "ecl_input")
scenario_weighting = study.artifacts.get("forward", "scenario_weighting")

# Futuro SDD-16, no implementado aquí:
# ecl_by_scenario = ifrs9_engine.calculate(ecl_input)
# ecl_weighted = scenario_weighting.weight_outputs(ecl_by_scenario, ...)
```

## 5. Configuración (schema Pydantic)

`ForwardConfig` es el sub-config de la sección `forward` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, `Literal` para categóricos, rangos explícitos, defaults defendibles y metadata UI. `forward ∉ INFRA_SECTIONS`: todo cambio computacional mueve `config_hash`.

```python
# nikodym/forward/config.py
class MacroSourceConfig(NikodymBaseConfig):
    type: Literal["path", "artifact", "dataframe"] = "path"
    path: str | None = None
    artifact_domain: str | None = None
    artifact_key: str | None = None
    time_col: str = "period"
    frequency: str | None = None
    variable_cols: tuple[str, ...] = Field(..., min_length=1)
    exogenous_cols: tuple[str, ...] = ()

class MacroModelConfig(NikodymBaseConfig):
    kind: Literal["arima", "sarima", "arimax", "auto_arima", "var", "vecm"] = "arima"
    horizon_periods: int = Field(default=12, ge=1)
    arima_order: tuple[int, int, int] = (1, 0, 0)
    seasonal_order: tuple[int, int, int, int] | None = None
    var_lags: int | None = Field(default=None, ge=1)
    vecm_rank: int | None = Field(default=None, ge=1)
    use_pmdarima_auto_order: bool = False
    auto_arima_random: bool = False
    random_state: int | None = None
    ljung_box_lags: tuple[int, ...] = (6, 12)
    fail_on_ljung_box: bool = False

class SatelliteConfig(NikodymBaseConfig):
    mode: Literal["fit", "fixed_coefficients"] = Field(default="fit")
    factor_cols: tuple[str, ...] = Field(..., min_length=1)
    segment_col: str | None = Field(default=None)
    target_components: tuple[Literal["pd", "lgd"], ...] = Field(default=("pd",))
    reference_scenario: str = "base"
    coefficient_table_path: str | None = None
    min_history_periods: int = Field(default=12, ge=3)

class ScenarioDefinitionConfig(NikodymBaseConfig):
    name: str
    weight: float = Field(..., ge=0.0, le=1.0)
    macro_path_path: str | None = None
    shocks: dict[str, float] = Field(default_factory=dict)
    description: str | None = None

class ScenarioConfig(NikodymBaseConfig):
    scenarios: tuple[ScenarioDefinitionConfig, ...] = Field(
        default=(
            ScenarioDefinitionConfig(name="base", weight=0.60),
            ScenarioDefinitionConfig(name="adverse", weight=0.30),
            ScenarioDefinitionConfig(name="severe", weight=0.10),
        )
    )
    forbid_mean_scenario: bool = Field(default=True)
    require_at_least_three: bool = Field(default=True)

class TtcReversionConfig(NikodymBaseConfig):
    enabled: bool = True
    reasonable_supportable_periods: int = Field(default=12, ge=1)
    reversion_periods: int = Field(default=24, ge=1)
    method: Literal["linear_logit", "none"] = "linear_logit"
    ttc_anchor: Literal["input_term_structure", "historical_mean"] = Field(default="input_term_structure")

class ForwardInputConfig(NikodymBaseConfig):
    macro_source: MacroSourceConfig
    term_structure_sources: tuple[Literal["survival", "markov"], ...] = ("survival", "markov")
    pd_basis_assumption: Literal["pit", "ttc"] | None = Field(default=None)
    require_pit_consistency: bool = True

class ForwardValidationConfig(NikodymBaseConfig):
    probability_tol: float = Field(default=1e-10, gt=0.0, lt=1e-3)
    weight_sum_tol: float = Field(default=1e-12, gt=0.0, lt=1e-3)
    monotonic_tol: float = Field(default=1e-10, gt=0.0, lt=1e-3)
    fail_on_missing_scenario_paths: bool = True

class ForwardConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"
    input: ForwardInputConfig
    satellite: SatelliteConfig
    macro: MacroModelConfig = Field(default_factory=MacroModelConfig)
    scenarios: ScenarioConfig = Field(default_factory=ScenarioConfig)
    ttc_reversion: TtcReversionConfig = Field(default_factory=TtcReversionConfig)
    validation: ForwardValidationConfig = Field(default_factory=ForwardValidationConfig)
    fail_on_falta_dato: bool = True
```

**Validaciones de config.**
- `macro_source.variable_cols` no puede estar vacío y no puede contener `time_col`.
- `type="path"` exige `path`; `type="artifact"` exige `artifact_domain` y `artifact_key`.
- `kind in {"var","vecm"}` exige al menos dos `variable_cols`.
- `kind="arimax"` exige `exogenous_cols` no vacío.
- `use_pmdarima_auto_order=True` solo aplica a ARIMA/SARIMA/ARIMAX univariado.
- `auto_arima_random=True` exige `random_state`; sin semilla explícita se levanta `ForwardConfigError`.
- `horizon_periods >= reasonable_supportable_periods` o se registra que no habrá tramo TTC dentro del horizonte.
- `scenario.scenarios` debe tener nombres únicos, incluir `base`, `adverse` y `severe` si `require_at_least_three=True`, y pesos que sumen 1. La terna es política default de Nikodym, no mínimo normativo IFRS 9.
- `forbid_mean_scenario=True` impide nombres reservados `mean`, `average`, `weighted_mean_input`.
- Si `adverse`/`severe` no traen `macro_path_path` ni shocks, se marca `FALTA-DATO-FWD-1`; por default falla porque no se inventan shocks macro.
- `satellite.factor_cols` debe ser subconjunto de variables macro proyectadas.
- `pd_basis_assumption` es requerido si la term-structure de SDD-18/19 no trae columna `pd_basis`.

**Defaults defendibles, todos editables por Cami.**
- **D-FWD-1:** pesos `base=0.60`, `adverse=0.30`, `severe=0.10`, **default a confirmar por Cami**. Justificación: caso central mayoritario con masa adversa material; no pretende ser regulatorio.
- **D-FWD-2:** `kind="arima"` y `arima_order=(1,0,0)`, **default a confirmar por Cami**. Justificación: AR(1) interpretable, determinista y suficiente como baseline; `auto_arima` queda opt-in.
- **D-FWD-3:** `horizon_periods=12`, `reasonable_supportable_periods=12`, **default a confirmar por Cami**. Justificación: coincide con un horizonte operativo típico de corto plazo sin fijar unidad calendario.
- **D-FWD-4:** `reversion_periods=24`, `method="linear_logit"`, **default a confirmar por Cami**. Justificación: transición gradual y preserva probabilidades en `[0,1]`.
- **D-FWD-5:** `fail_on_ljung_box=False`. Justificación: Ljung-Box es diagnóstico; bloquear por default puede impedir exploración. La institución puede endurecerlo.
- **D-FWD-6:** `term_structure_sources=("survival","markov")`. Justificación: F5 espera ambas rutas reproducibles; el usuario puede reducir a una.

**Round-trip YAML y UI.** El round-trip sigue SDD-05: dump JSON-mode, `sort_keys=False`, carga vía `load_config`. La UI debe renderizar pesos con validación de suma, escenario con tabla editable, horizonte/reversión con inputs numéricos y alerta visible si faltan paths/shocks adversos.

**Hook implementado en `core.config.schema`.**
- declarar `_FORWARD_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir `forward` como campo `Any` en runtime y `ForwardConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("forward", mode="before")`;
- no importar `nikodym.forward` desde `core`;
- al importar `nikodym.forward`, poblar el hook de forma análoga a `data`/dominios F5.

## 6. Contratos de datos (I/O)

**Input duro del Step según config.**

| artefacto | requerido | contrato |
|---|---:|---|
| `("survival","term_structure")` | condicional | requerido si `term_structure_sources` contiene `"survival"` |
| `("markov","term_structure")` | condicional | requerido si `term_structure_sources` contiene `"markov"` |
| clave macro configurada | condicional | requerido si `macro_source.type="artifact"` |

**Input `macro_history`.** `pandas.DataFrame` o archivo CSV/Parquet leído con import perezoso:
- `time_col`: período o timestamp ordenable, único por fila de historia.
- `variable_cols`: variables macro numéricas, finitas, sin `inf`.
- `exogenous_cols`: opcionales, requeridas para ARIMAX si config las declara.
- frecuencia regular o frecuencia declarada; gaps no se reparan silenciosamente.
- orden temporal estrictamente creciente tras normalización.
- sin `scenario` histórico salvo que se use como etiqueta descriptiva no modelable.

**Input `macro_scenario_paths` opcional.** Si la institución entrega paths explícitos, el frame debe traer `scenario`, `period`, `time_value`, `macro_variable`, `value` y `source`. Si no hay path, los shocks configurados se aplican sobre el forecast base.

**Input `term_structure` desde SDD-18/19.** Columnas mínimas consistentes:
- `row_id`, `segment`, `partition` si aplican;
- `period`, `time_value`;
- `hazard`, `survival`, `pd_marginal`, `pd_cumulative`;
- `method`, `pd_source`, `scenario`, `warning_codes`.

`forward` puede aceptar columnas adicionales `lgd`, `lgd_source`, `pd_basis` y `basis_state`. Si faltan `pd_basis`/`basis_state`, usa `cfg.input.pd_basis_assumption`; si también falta, `PitConsistencyError` o `FALTA-DATO-FWD-4`.

**Output `macro_projection`.** `pandas.DataFrame` tidy:

| columna | significado |
|---|---|
| `scenario` | escenario macro |
| `scenario_weight` | peso validado |
| `period` | horizonte ordinal |
| `time_value` | fecha/período futuro |
| `macro_variable` | factor macro |
| `projected_value` | valor final usado por satellite |
| `model_value` | forecast puro del modelo, antes de override/shock |
| `shock_value` | ajuste configurado, si aplica |
| `method` | ARIMA/SARIMA/ARIMAX/VAR/VECM/auto_arima |
| `model_id` | identificador estable del modelo macro |
| `is_reasonable_supportable` | `period <= H_RS` |
| `warning_codes` | advertencias por variable/período |

**Output `forward.term_structure`.** DataFrame tidy, compatible con SDD-18/19 y extendido:

| columna | significado |
|---|---|
| `row_id` | id de observación/cuenta inicial si existe |
| `segment` | segmento/pool opcional |
| `partition` | partición si aplica |
| `source_model` | `"survival"` o `"markov"` |
| `period` | horizonte ordinal |
| `time_value` | tiempo en unidad declarada |
| `scenario` | escenario macro |
| `scenario_weight` | peso del escenario |
| `hazard` | hazard forward-looking final |
| `survival` | supervivencia final |
| `pd_marginal` | PD marginal forward-looking |
| `pd_cumulative` | PD acumulada forward-looking |
| `pd_marginal_base` | PD marginal base antes de macro |
| `pd_cumulative_base` | PD acumulada base antes de macro |
| `lgd` | LGD forward-looking si existe input/coeficientes |
| `lgd_base` | LGD base si existe |
| `pd_basis` | `"pit"` en tramo forward; metadata para IFRS 9 |
| `basis_state` | `"pit"`, `"blended"` o `"ttc"` |
| `ttc_reversion_weight` | `λ_t` |
| `satellite_adjustment` | delta logit aplicado a PD/hazard |
| `macro_model_id` | id del modelo macro |
| `satellite_model_id` | id del satellite |
| `method` | método de term-structure base |
| `pd_source` | fuente PD original |
| `warning_codes` | warnings acumulados |

**Output `scenario_weights`.** Frame tidy con `scenario`, `weight`, `is_default`, `source` (`"config"` o `"default_a_confirmar"`) y `description`.

**Output `ecl_input`.** DTO `ForwardEclInput` con:
- `term_structure_frame`: salida forward por escenario;
- `scenario_weight_frame`: pesos validados;
- `pit_consistency`: estado y warnings;
- `chain`: literal `macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting`;
- `contract_version`: versión del contrato SDD-20 para que SDD-16 pueda adaptarse sin dependencia dura.

**Invariantes.**
- Pesos de escenarios finitos, no negativos y suma `1 ± weight_sum_tol`.
- Siempre existen al menos tres escenarios si `require_at_least_three=True`.
- No existe salida final con `scenario="mean"` ni `scenario="average"`.
- `pd_marginal`, `pd_cumulative`, `hazard`, `survival`, `lgd` están en `[0,1]` dentro de tolerancia.
- `pd_cumulative` es no decreciente por `row_id/source_model/scenario`.
- `pd_marginal(t) = survival(t-1) * hazard(t)` si `hazard` es definible.
- `survival = 1 - pd_cumulative` dentro de tolerancia.
- No se publican `NaN`, `inf`, `-inf` ni `-0.0`; `-0.0` se normaliza a `0.0`.
- No se mutan artefactos de entrada; toda transformación usa copias defensivas.
- Orden estable: source_model, row_id/segment, scenario en orden de config, períodos ascendentes.

## 7. Algoritmos y flujo

**`ForwardStep.execute(study, rng)` - secuencia canónica.**
1. **Resolver config.** Leer `study.config.forward`; si falta en API programática, exigir `ForwardConfig`.
2. **Construir `requires`.** Desde `term_structure_sources` y `macro_source`; validar CT-1 antes de ejecutar.
3. **Controlar azar.** Por default `del rng`; si `auto_arima_random=True`, derivar/usar `random_state` explícito y auditarlo.
4. **Leer macro history.** Desde path o artifact; copiar defensivamente, validar tiempo, frecuencia, variables y finitud.
5. **Leer term-structures.** Traer survival/markov configurados, copiar y normalizar columnas mínimas.
6. **Validar PIT/TTC.** Resolver `pd_basis`; fallar si queda desconocido y `require_pit_consistency=True`.
7. **Construir escenarios.** Validar nombres, pesos, paths/shocks y guard anti escenario medio.
8. **Ajustar macro.** `MacroProjectionModel.fit`; capturar versiones y residuos.
9. **Diagnosticar macro.** Ljung-Box por variable/lag; registrar p-values y acciones.
10. **Predecir macro.** `predict(horizon=cfg.macro.horizon_periods)` y aplicar overrides/shocks por escenario.
11. **Ajustar satellite.** `SatelliteModel.fit` o cargar coeficientes fijos auditados.
12. **Aplicar satellite.** Producir hazard/PD/LGD PIT por escenario y período.
13. **Aplicar reversión TTC.** Calcular `λ_t`; mezclar en escala logit con el ancla TTC configurada.
14. **Validar invariantes.** Probabilidades, monotonicidad, columnas, escenarios completos y ausencia de medias.
15. **Construir DTOs.** `ForwardDiagnostics`, `ForwardCard`, `ForwardEclInput`, `ForwardResult`.
16. **Auditar decisiones.** Macro, satellite, escenarios, PIT/TTC, reversion, FALTA-DATO y guard anti media.
17. **Publicar artefactos.** Escribir todas las claves `provides` bajo `"forward"`.

**Flujos internos por clase.**
- `MacroProjectionModel.fit/predict` valida series, selecciona backend (`statsmodels` o `pmdarima` opt-in), ajusta sin mutar inputs, exige `horizon` explícito, materializa forecast tidy y ejecuta Ljung-Box sobre residuos.
- `SatelliteModel.fit/predict` alinea term-structure con macro histórico, ajusta `logit(hazard)` y opcionalmente `logit(LGD)`, calcula `Δx` por escenario, transforma en escala logit y recomputa curvas lifetime completas.
- `ScenarioWeighting.apply_ttc_reversion` calcula `λ_t`, mezcla con ancla TTC en escala logit, marca `basis_state` y valida probabilidades.
- `ScenarioWeighting.weight_outputs` valida que recibe outputs por escenario, verifica cobertura de escenarios, multiplica por `w_k`, suma por grupos y publica diagnostics.

**Alternativas descartadas.**
- *Escenario medio macro:* descartado por no linealidad de PD; queda prohibido por config/API.
- *Promediar PD antes de ECL:* descartado como default; la cadena oficial pondera ECL outputs. `forward` puede producir diagnósticos de PD ponderada, pero no sustituye el input por escenario.
- *Hard dependency runtime sobre SDD-16:* descartado; el motor vigente consume un contrato estable y no es importado por `forward`.
- *Recalibrar `survival`/`markov` dentro de `forward`:* descartado; esos SDD son dueños de la term-structure base.
- *Elegir shocks macro adversos/severos inventados:* descartado; si no vienen de usuario/fuente institucional, `FALTA-DATO-FWD-1`.
- *Importar `statsmodels`, `pmdarima`, `pandas` o `scipy` en `__init__`:* descartado; viola núcleo liviano.

**Complejidad / rendimiento.** Macro univariado es O(T·p²) aproximado según solver; VAR/VECM escala peor con número de variables y lags. Satellite es O(n·H·K·f) sobre filas de term-structure, horizonte, escenarios y factores. La salida puede crecer rápido; B20 debe validar tamaño antes de materializar y registrar `n_rows_output`.

## 8. Casos borde y manejo de errores

- **Falta term-structure configurada:** `ArtifactNotFoundError` por CT-1 antes de ejecutar.
- **Macro source ausente o ilegible:** `ForwardInputError` con path/clave y causa.
- **Columnas macro faltantes:** `ForwardInputError` listando variables faltantes.
- **Tiempo duplicado, no ordenable o con gaps no declarados:** `ForwardInputError`.
- **Series macro constante o demasiado corta:** `ForwardFitError` si no cumple `min_history_periods`.
- **ARIMAX sin exógenas futuras suficientes:** `MacroProjectionError`.
- **VAR/VECM con una sola variable:** `ForwardConfigError`.
- **VECM sin rank configurado cuando statsmodels no puede inferirlo de forma estable:** `ForwardConfigError` o `FALTA-DATO-FWD`.
- **`pmdarima` faltante con `use_pmdarima_auto_order=True`:** `MissingDependencyError("instale nikodym[forecasting]")`.
- **`auto_arima_random=True` sin `random_state`:** `ForwardConfigError`.
- **Ljung-Box falla con `fail_on_ljung_box=True`:** `ForwardFitError`; con default solo warning auditado.
- **Escenarios con pesos que no suman 1:** `ForwardScenarioError`.
- **Menos de tres escenarios:** `ForwardScenarioError` si `require_at_least_three=True`.
- **Escenario `mean`/`average`:** `ForwardScenarioError` siempre que `forbid_mean_scenario=True`.
- **Adverse/severe sin path ni shocks:** `FALTA-DATO-FWD-1`; por default falla.
- **Factor satellite no proyectado:** `SatelliteModelError`.
- **Coeficientes fijos sin columna requerida o signo documentado:** `SatelliteModelError`.
- **Input PD fuera de `(0,1)` para logit:** `PitConsistencyError` o `ForwardInputError`.
- **`hazard` ausente:** derivar desde `pd_marginal/survival(t-1)` si es matemáticamente posible; si no, `ForwardInputError`.
- **LGD ausente:** permitido; se ajusta solo PD y se registra en diagnostics.
- **LGD fuera de `[0,1]`:** `ForwardInputError`.
- **`pd_basis` desconocida:** `PitConsistencyError` si `require_pit_consistency=True`; si no, warning explícito.
- **Reversión con `H_RS + R` menor que horizonte:** permitido; los períodos posteriores quedan TTC.
- **Probabilidades fuera de rango por overflow logit:** `ForwardPredictionError`; no se clipea fuera de tolerancia.
- **Monotonicidad rota en `pd_cumulative`:** `ForwardPredictionError`.

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen método, variable, escenario, período y valor observado cuando aplique.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno por default. `MacroProjectionModel` y `SatelliteModel` son deterministas dados datos/config.
- **RNG explícito.** Solo `pmdarima.auto_arima(random=True)` puede requerir aleatoriedad; queda deshabilitado por default y exige `random_state`.
- **Determinismo esperado.** `(macro_hash + term_structure_hash + data_hash/config_hash + uv.lock + scenario_config) → macro_projection, term_structure, diagnostics y card idénticos`.
- **Orden estable.** Escenarios en orden de config, variables en `variable_cols`, períodos ascendentes, filas base en orden estable de entrada.
- **Copias defensivas.** No muta `macro_history`, `survival.term_structure`, `markov.term_structure` ni cualquier artifact upstream.
- **Normalización numérica.** `-0.0 → 0.0`; residuos dentro de tolerancia se ajustan con warning; fuera de tolerancia fallan.
- **Hashes auxiliares.** Si se hashean macro frames o term-structures, usar `pandas.util.hash_pandas_object` con conversión endian explícita `.astype("<u8")`; nunca bytes Parquet ni `hash()` builtin.
- **Núcleo liviano.** `import nikodym.forward` no debe importar `statsmodels`, `pmdarima`, `pandas` ni `scipy`; imports dentro de `fit`, `predict`, `execute` o validadores runtime.
- **Pandera.** Si se usa para validación, importar `pandera.pandas as pa` dentro de la función; nunca `import pandera` top-level ni `pandera` top-level.
- **Audit trail (`log_decision`).** Registrar como mínimo:
  - `forward_macro_model`: método, variables, frecuencia, órdenes/lags, horizon y versiones;
  - `forward_macro_input_quality`: filas, gaps, missing, rango temporal y hash lógico macro;
  - `forward_ljung_box`: lags, estadísticos, p-values, acción y warnings;
  - `forward_scenarios`: nombres, pesos, fuentes, defaults a confirmar y suma;
  - `forward_no_mean_scenario_guard`: validación ejecutada y resultado;
  - `forward_satellite_model`: factores, coeficientes, segmentos, target PD/LGD y estadísticas;
  - `forward_term_structure_sources`: survival/markov, columnas, basis asumida y hash auxiliar;
  - `forward_pit_consistency`: `pd_basis`, `basis_state`, warnings y decisiones PIT/TTC;
  - `forward_ttc_reversion`: `H_RS`, `R`, método, ancla y períodos blended;
  - `forward_ecl_contract`: columnas entregadas, contract_version y ausencia de cálculo ECL;
  - `forward_falta_dato`: brechas FALTA-DATO-FWD y si bloquearon.
- **Card / report.** `ForwardCard` debe permitir reconstruir la corrida: macro, escenarios, satellite, term-structure, reversion, PIT/TTC, versions, diagnostics y `FALTA-DATO`.
- **Gobernanza CT-2.** `metric_sections` puede incluir `"macro_projection_summary"`, `"ljung_box"`, `"scenario_weights"`, `"satellite_coefficients"`, `"pit_ttc_consistency"` y `"term_structure_summary"`.
- **Lineage.** `forward` consume `data_hash`/`config_hash`; agrega hashes auxiliares para macro history y term-structure en card/diagnostics, no reemplaza el lineage base.
- **Golden hash.** El cableado de `ForwardConfig` ya fue incorporado al contrato de hash; cualquier cambio computacional debe actualizar el golden explícitamente.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymError`, `MissingDependencyError`, lineage, `config_hash` y patrón CT-2 `term_structure()`.
- SDD-02 (`data`): mecanismo de frame/hash lógico, frontera CT-3 y helpers de validación cuando se reutilicen sin acoplar datos longitudinales.
- SDD-05 (convenciones): Pydantic v2, hooks diferidos, `extra="forbid"`, `frozen=True`, naming inglés para APIs/stats y español para docs/errores.
- SDD-18 (`survival`): term-structure lifetime PD tidy, columnas mínimas `hazard/survival/pd_marginal/pd_cumulative`.
- SDD-19 (`markov`): term-structure lifetime PD tidy intercambiable con survival.

**Aguas abajo.**
- SDD-16 (`provisioning/ifrs9`) consume `ForwardEclInput`; calcula ECL por escenario, staging, LGD/EAD, descuento y, si corresponde, Vasicek PIT/TTC. La LGD que publique `forward` se ignora hoy y SDD-16 la reconstruye desde su config: deuda contractual explícita.
- SDD-17 (`provisioning`) puede comparar el resultado IFRS 9 con otra fuente, con carácter diagnóstico; eso no constituye la regla B-1.
- SDD-21 (`stress`) consume macro/satellite/escenarios y extiende a stress testing.
- SDD-22 (`validation`) backtestea macro, satellite y PD forward.
- SDD-23 (`ui`) edita config y muestra warnings/FALTA-DATO.
- SDD-26 (`report`) renderiza escenarios, diagnostics y model card.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | `>=2.0` | BSD-3 ✅ | frames tidy, joins, outputs | base de `data`; import perezoso en `forward` |
| numpy | `>=1.22` | BSD ✅ | arrays, logit/sigmoid, finitud | base; aceptable por core |
| pydantic | `>=2` | MIT ✅ | config/DTOs frozen | base |
| statsmodels | `>=0.14` | BSD-3 ✅ | ARIMA/SARIMA/ARIMAX, VAR/VECM, Ljung-Box, regresión satellite | extra `[forecasting]`, import perezoso |
| pmdarima | `>=2.0` | MIT ✅ | `auto_arima` opcional | extra `[forecasting]`, import perezoso |
| scipy | transitiva/`>=1.10` si se usa | BSD ✅ | funciones numéricas/stats transitivas | no top-level |

**Licencias verificadas.** `statsmodels` declara Modified 3-clause BSD en su documentación oficial; `pmdarima` declara `License Expression: MIT` en PyPI. Ambas son permisivas y compatibles con Apache-2.0; queda vetado introducir paquetes GPL/LGPL/AGPL.

**Núcleo liviano.**
- `nikodym.core` no importa `nikodym.forward`.
- `import nikodym.forward` no importa `statsmodels`, `pmdarima`, `pandas` ni `scipy`.
- `forward.__init__` debe exponer config/errores/registro usando anotaciones string y `TYPE_CHECKING`.
- Mensajes de dependencia faltante deben recomendar `nikodym[forecasting]`.

**Packaging actual.** `pyproject.toml` ya reserva `forecasting = ["statsmodels>=0.14", "pmdarima>=2.0"]`. SDD-25 mapea ese extra a SDD-20 y lo considera BSD/MIT. B20 debe respetar ese mapa y no duplicar dependencias fuera del extra.

**Fuentes externas verificadas para este SDD.**
- statsmodels Developer Page, sección License: https://www.statsmodels.org/stable/dev/index.html#license.
- pmdarima PyPI, metadata `License Expression: MIT`: https://pypi.org/project/pmdarima/.

## 11. Estrategia de tests

Marco transversal en SDD-24. Cobertura objetivo 100% para módulos `forward`. `filterwarnings=["error"]`, `mypy --strict`, ruff `E,F,I,N,UP,B,SIM,RUF,D` y docstrings públicas en español.

- **Golden AR(1) cerrado + horizonte explícito.** Con `y_{t+1}=1+0.5·y_t` y último `y_t=4`, forecast esperado `3.0`, `2.5`, `2.25`; `predict()` sin `horizon` levanta `MacroProjectionError`.
- **Golden Ljung-Box passthrough.** Residuos sintéticos conocidos publican lags configurados y p-values finitos; si `fail_on_ljung_box=True` y el p-value cae bajo umbral configurado, falla.
- **Golden satellite logit.** Base hazard `0.02`, delta macro `x=1`, `β=0.5`: `logit(0.02)=-3.8918202981`, ajuste `-3.3918202981`, PD esperada `0.0325520809`.
- **Golden recomposición lifetime.** Hazards ajustados `0.10`, `0.20`: `survival(1)=0.90`, `pd_marginal(1)=0.10`, `survival(2)=0.72`, `pd_marginal(2)=0.18`, `pd_cumulative(2)=0.28`.
- **Golden ponderación de outputs vs media de inputs.** Pesos `0.60/0.30/0.10`; macro `x=(1.0,1.5,2.4)`; base hazard `0.02`; `β=0.5`. Ponderar outputs da `0.0383014617`; correr sobre media input `1.29` da `0.0374413137`. El test debe probar que no son iguales y que el método permitido devuelve el primero.
- **Guard anti escenario medio.** Input con `scenario="mean"` o config `weighted_mean_input` levanta `ForwardScenarioError`.
- **Pesos.** Suma distinta de 1 fuera de tolerancia, pesos negativos o escenarios duplicados fallan.
- **Tres escenarios mínimos.** Config con solo base/adverse falla si `require_at_least_three=True`.
- **FALTA-DATO shocks.** Defaults de adverse/severe sin path/shocks registran `FALTA-DATO-FWD-1` y fallan con `fail_on_falta_dato=True`.
- **Reversión TTC.** Con `H_RS=2`, `R=2`, los pesos `λ_t` esperados son `1,1,0.5,0,0`; la salida marca `pit,pit,blended,ttc,ttc`.
- **Invariantes term-structure.** `survival=1-pd_cumulative`, `pd_marginal=S(t-1)·hazard`, PD acumulada no decrece.
- **PIT consistency.** Term-structure sin `pd_basis` y sin `pd_basis_assumption` levanta `PitConsistencyError`.
- **CT-1 dinámico.** `ForwardStep.from_config` con fuente survival requiere `("survival","term_structure")`; con markov requiere `("markov","term_structure")`; con ambas requiere ambas.
- **CT-2.** `ForwardResult.term_structure()` retorna DataFrame tidy con columnas compatibles; `ForwardCard.metric_sections` acepta secciones estructuradas.
- **ECL hook sin dependencia dura.** `ForwardEclInput` se construye sin importar `nikodym.provisioning.ifrs9`.
- **No mutación.** Snapshots profundos de macro history y term-structure base permanecen iguales.
- **Determinismo.** Dos corridas con mismos frames/config producen outputs byte-equivalentes tras normalización.
- **Import guard.** Subproceso verifica que `import nikodym.forward` no deja `statsmodels`, `pmdarima`, `pandas` ni `scipy`; si se usa pandera, debe ser `import pandera.pandas as pa` en scope local.
- **Config round-trip/hash.** YAML dump/load preserva escenarios, pesos, órdenes ARIMA y reversion; cambiar esos campos mueve `config_hash`.
- **Warnings como error.** Warnings de statsmodels/pmdarima se convierten en excepciones controladas o diagnostics explícitos.
- **Endianness/hash.** Cualquier hash auxiliar usa `.astype("<u8")`; test de grep impide `hash()` builtin en rutas de identidad.
- **Mypy/ruff/licencias.** Wrappers sin stubs usan `cast()`/`ignore` localizados; docstrings públicas en español; meta-test anti copyleft sobre `[forecasting]`.

Fixtures: `macro_history_small.parquet` sintético, term-structures pequeñas de survival/markov, `ForwardConfig` mínimo, config con coeficientes satellite fijos, escenarios con paths explícitos, `InMemoryAuditSink`, y datasets degenerados para missing, duplicados, pesos inválidos y PD fuera de rango.

## 12. Decisiones implementadas, faltantes y riesgos

Los defaults D-FWD-1…9 están implementados como política metodológica editable y no como parámetros regulatorios. Se mantienen el guard anti escenario medio, la reversión TTC configurable, los shocks externos obligatorios y la ausencia de dependencia runtime sobre IFRS 9. `default_a_confirmar` permanece deliberadamente visible para impedir que un valor de conveniencia se presente como aprobado.

**FALTA-DATO explícitos.**
- **FALTA-DATO-FWD-1 — Paths/shocks macro adverso y severo.** No hay valores externos en ESPECIFICACIONES; deben venir de institución/config.
- **FALTA-DATO-FWD-2 — Variables macro canónicas por cartera.** No se fija PIB, desempleo, inflación u otras; `factor_cols` lo declara el usuario.
- **FALTA-DATO-FWD-3 — Frecuencia temporal institucional.** Mensual/trimestral/anual no está fijado; `macro_source.frequency` y `time_unit` deben declararse.
- **FALTA-DATO-FWD-4 — Naturaleza PIT/TTC de la term-structure base.** SDD-18/19 publican PD lifetime, pero no siempre conocen si es PIT/TTC; se requiere columna o config.
- **FALTA-DATO-FWD-5 — Coeficientes satellite iniciales.** Si no hay historia suficiente para ajustar, deben venir como coeficientes fijos auditados.
- **FALTA-DATO-FWD-6 — Tratamiento LGD forward-looking.** `forward` puede publicar LGD, pero SDD-16 la ignora hoy y reconstruye LGD con `IfrsLgdConfig`; falta fijar precedencia o validación cruzada.
- **FALTA-DATO-FWD-7 — Panel longitudinal IFRS 9.** SDD-16 ya fija cuenta×período×escenario con EAD/EIR/stage; la disponibilidad temporal y el perfil institucional de EAD/LGD siguen siendo inputs externos.

**Riesgos y mitigaciones.**
- **Promedio de inputs macro usado por conveniencia.** Mitigación: guard de config/API, golden test no lineal y auditoría `forward_no_mean_scenario_guard`.
- **Falsa consistencia PIT.** Mitigación: columnas `pd_basis`/`basis_state`, `PitConsistencyError` y `ForwardEclInput` explícito.
- **Defaults confundidos con parámetros regulatorios.** Mitigación: D-FWD marcados como "default a confirmar por Cami" y source `"default_a_confirmar"`.
- **Sobreacoplamiento a IFRS 9.** Mitigación: DTO `ForwardEclInput` y cero imports runtime de SDD-16.
- **Dependencias pesadas en import.** Mitigación: imports perezosos y tests `sys.modules`.
- **Modelos macro inestables con poca historia.** Mitigación: `min_history_periods`, diagnostics, fail-fast configurable y coeficientes/rutas externas.
- **LGD ajustada sin base económica.** Mitigación: LGD opcional; si falta base, `forward` no inventa LGD.
- **Term-structure incompatible con survival/markov.** Mitigación: columnas mínimas heredadas y tests de contrato cruzado SDD-18/19.
- **Reversión TTC mal aplicada a acumuladas.** Mitigación: aplicar en escala hazard/logit y recomputar curvas lifetime completas.

**Citas internas.** ESPECIFICACIONES.md §5.5/§5.6; ROADMAP.md F5; `_CONTRATOS-TRANSVERSALES.md` CT-1/CT-2/CT-3; SDD-18 (`survival`); SDD-19 (`markov`); SDD-25 (`packaging/CI`).
