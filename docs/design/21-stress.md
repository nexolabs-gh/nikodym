# SDD-21 — `stress` (stress testing, sensibilidad y reverse stress)

| Campo | Valor |
|---|---|
| **SDD** | 21 |
| **Módulo** | `nikodym.stress` |
| **Dominio** | Forward / stress testing / sensibilidad macro |
| **Fase** | F5 |
| **Tanda de producción** | T5 (Forward-looking & dinámica) |
| **Estado** | ✅ Implementado; API experimental |
| **Depende de** | SDD-01 (`core`), SDD-02 (`data` base/hash), SDD-05 (convenciones + config), SDD-18 (`survival`), SDD-19 (`markov`), SDD-20 (`forward`) |
| **Lo consumen** | SDD-16 (`provisioning/ifrs9`), SDD-17 (`provisioning`), SDD-22 (`validation`), SDD-23 (`ui`), SDD-26 (`report`) |
| **Autor / Fecha** | Codex (worker A10, redacción SDD-21 para T5) / 2026-06-30 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `stress` aplica escenarios macro severos y barridos de sensibilidad sobre la cadena `forward`, estima el impacto en PD/term-structure/ECL/provisiones cuando existe un motor económico conectado, y ejecuta reverse stress testing determinista para encontrar la severidad de shock que cruza un umbral objetivo.

**Responsabilidad única (qué SÍ hace).**
- Consume los artefactos de SDD-20: `macro_projection`, `satellite_model`, `pd_lgd_term_structure`, `scenario_weighting` y `ForwardEclInput`.
- Define escenarios severos parametrizables por usuario, más allá del escenario `adverse` de `forward`, sin traer escenarios oficiales embebidos.
- Aplica shocks macro aditivos o relativos sobre factores configurados y propaga esos shocks por el satellite model de SDD-20.
- Recalcula PD/hazard/LGD forward-looking y term-structure por escenario de estrés, preservando las identidades lifetime de SDD-18/19/20.
- Ejecuta barridos de sensibilidad de un factor: una grilla determinista de severidades sobre un factor macro y un conjunto de métricas de salida.
- Ejecuta reverse stress testing: dado un umbral objetivo de pérdida, ECL, provisión, ratio o métrica declarada, busca por bisección monotónica la severidad mínima que lo alcanza.
- Publica artefactos namespaced bajo `"stress"`: escenarios aplicados, term-structure estresada, impactos tidy, sensitivity results, reverse results, diagnostics, result y card.
- Aporta `StressConfig` como sección computacional de `NikodymConfig`; por tanto, cambios de shocks, tolerancias, grillas o targets mueven el `config_hash`.
- Registra con `log_decision` cada escenario, cada severidad de sensibilidad, cada iteración relevante de reverse stress y cada resultado económico disponible.
- Cierra la cadena SDD-18/19/20/21 de F5 Lifetime: lifetime PD base, Markov, forward macro y stress quedan especificados como bloque antes de que SDD-16 consuma la cadena para IFRS 9/ECL.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No valida modelos ni hace backtesting formal.** ESPECIFICACIONES separa la validación avanzada en F6/SDD-22: discriminación, calibración, estabilidad y backtesting aparecen como sucesor, no como responsabilidad de `stress` (ESPECIFICACIONES.md:L150-L155).
- **No calcula métricas ROC/AUC/Gini/KS, Hosmer-Lemeshow, binomial, traffic-light, Brier, PSI ni t-test ECB.** Todas esas métricas pertenecen a SDD-22/F6.
- **No inventa escenarios regulatorios EBA, CCAR/DFAST, ICAAP ni CMF.** ESPECIFICACIONES solo los cita como frameworks conceptuales y reverse stress (ESPECIFICACIONES.md:L153-L154); los shocks entran por config o fallan como `FALTA-DATO-STR`.
- **No recalibra el satellite model.** SDD-20 ajusta/carga satellite models; `stress` los aplica bajo shocks y registra la fuente.
- **No rediseña `forward`, `survival` ni `markov`.** Reusa la term-structure y los contratos CT-2 ya publicados por SDD-18/19/20.
- **No implementa staging, SICR, LGD/EAD faltantes, EIR, descuento ni piso prudencial CMF.** SDD-16/17 calculan ECL/provisiones completas.
- **No crea un motor ECL propio.** Si se pide impacto ECL/provisión, `stress` invoca un `EclEngineLike`/`ProvisionEngineLike` conectado como artefacto o dependencia futura; si falta, falla ruidoso cuando la métrica lo requiere.
- **No promedia inputs macro ni sustituye la ponderación por escenario.** Mantiene el guard de SDD-20 contra escenario medio y solo compara outputs por escenario/severidad.
- **No usa `eval`, `df.eval` ni expresiones ejecutables de usuario.** Los shocks son estructuras tipadas: factor, operación, magnitud y unidad.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Forward-looking & dinámica (F5/T5), inmediatamente después de `forward` y antes de provisiones/reportes/validación.
- **Quién lo invoca:** `Study.run()` como sección `stress` de `NikodymConfig`, o API programática `StressTestEngine.run(...)`.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, excepciones, lineage), `forward` (artefactos y DTOs), y motores económicos futuros mediante Protocols livianos.
- **Dependencia dura de dominio:** SDD-20. `stress` no debe ejecutarse si no existen los artefactos forward requeridos.
- **Dependencias indirectas:** SDD-18/19 porque la term-structure que `forward` entrega viene de survival/markov; `stress` no las importa directamente salvo para metadata.

```text
survival.term_structure ─┐
                         ├──► forward ─► ForwardEclInput ─┐
markov.term_structure ───┘                                 │
                                                            ▼
macro_projection + satellite_model + scenario_weighting ─► stress
                                                            │
                                                            ├─► stressed_term_structure
                                                            ├─► sensitivity_results
                                                            ├─► reverse_stress_results
                                                            └─► ecl/provision impact, si hay engine conectado
```

**Anclaje normativo interno.**
- ESPECIFICACIONES §5.6 fija la cadena `macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting` y la consistencia PIT (ESPECIFICACIONES.md:L142-L148).
- ESPECIFICACIONES §5.7 ubica `stress/` en T5/F5 porque consume la cadena forward, y separa validación/backtesting para F6/SDD-22 (ESPECIFICACIONES.md:L150-L155).
- ROADMAP F5 declara `stress` como parte de Forward-looking & dinámica y como entregable de escenarios severos/sensibilidad (ROADMAP.md:L94-L103).
- SDD-20 declara que no hace stress testing y delega ese alcance a SDD-21 (20-forward.md:L35-L43).

**Cadena obligatoria que `stress` reutiliza.**
- `macro_projection`: base y escenarios forward ya proyectados por SDD-20.
- `satellite_model`: función macro↔PD/LGD en escala logit.
- `pd_lgd_term_structure`: term-structure forward-looking por escenario.
- `ecl_engine`: hook futuro de SDD-16; `stress` lo recibe como Protocol, no como import duro.
- `scenario_weighting`: ponderación de outputs, nunca de inputs macro.

SDD-20 ya define esa cadena y el contrato `ForwardEclInput` sin depender de SDD-16 (20-forward.md:L67-L72, 20-forward.md:L321-L342). `stress` debe respetar el mismo límite: puede preparar y pasar inputs a ECL, pero no calcula IFRS 9 internamente.

**Interacción con `Study` y config declarativo.** `StressStep` es un `Step` nativo registrado con `@register("standard", domain="stress")`. Se construye desde `StressConfig`; sus `requires` son dinámicos:
- siempre requiere `("forward","macro_projection")`;
- siempre requiere `("forward","satellite_model")`;
- siempre requiere `("forward","term_structure")`;
- siempre requiere `("forward","scenario_weighting")`;
- siempre requiere `("forward","ecl_input")`;
- requiere `cfg.input.ecl_engine_artifact` si alguna métrica objetivo usa `ecl`, `provision`, `loss` o `ratio` calculado por un motor económico;
- requiere `cfg.input.provision_engine_artifact` si el target pide una provisión económica calculada por un motor inyectado.

Esto cumple CT-1: el objeto `StressStep` expone el DAG efectivo antes de ejecutar. El motor v1 valida prerequisitos; el scheduler topológico real sigue diferido a F5 por CT-1.

**Cableado implementado en `core.study`.**
- `_DOMAIN_MODULES["stress"] = "nikodym.stress"`;
- `_DOMAIN_CONFIG_CLASSES["stress"] = ("nikodym.stress.config", "StressConfig")`;
- `_DEFAULT_DOMAIN_ORDER` ubica `"stress"` después de `"forward"`;
- si `"provisioning_ifrs9"` existe en el mismo run y se usa como motor económico de stress, CT-1 debe resolver el orden por `requires`, no por suposición lineal;
- mientras el scheduler topológico no exista, el usuario debe declarar `forward` antes de `stress` y cualquier engine económico antes de los targets que lo requieran.

**Paquete físico y troceo B21.x.**

```text
src/nikodym/stress/
  __init__.py
  config.py
  exceptions.py
  results.py
  engine.py
  step.py
```

**B21.1 - `config.py` + `exceptions.py`.**
`StressConfig`, sub-schemas, jerarquía de errores, hook diferido en `NikodymConfig`, round-trip YAML, defaults D-STR y validaciones sin imports pesados.

**B21.2 - `results.py` + `engine.py`.**
DTOs frozen, `StressTestEngine`, aplicación de escenarios, sensibilidad, reverse stress por bisección, contratos ECL/provision mediante Protocols y sin dependencia dura sobre SDD-16/17.

**B21.3 - `step.py` + cableado.**
`StressStep`, `@register(domain="stress")`, CT-1 dinámico, publicación de artefactos, audit trail, import guards y prueba end-to-end `Study` después de `forward`.

## 3. Conceptos y fundamentos

**Fuente normativa/metodológica interna.**
- ESPECIFICACIONES §5.7 fija stress testing F5, frameworks conceptuales EBA/Fed/ICAAP, reverse stress y sensibilidad de provisiones/ECL a shocks macro vía satellite models (ESPECIFICACIONES.md:L150-L154).
- ESPECIFICACIONES §5.6 fija que stress depende de la cadena forward y de la consistencia PIT (ESPECIFICACIONES.md:L142-L148).
- ROADMAP F5 ubica `stress` junto a survival, Markov y forward, y declara que F5 cierra el lifetime requerido por F4 (ROADMAP.md:L94-L103).
- CT-1 exige `requires`/`provides`; CT-2 exige resultados estructurados aditivos; CT-3 mantiene separada la capa longitudinal económica.

**Notación.**
- `k ∈ K`: escenario forward original (`base`, `adverse`, `severe`, u otros).
- `s ∈ S`: escenario de stress definido por usuario.
- `q ∈ Q`: punto de severidad en un barrido de sensibilidad o reverse stress.
- `x_{k,t}`: vector macro proyectado por `forward`.
- `δ_s`: vector de shocks macro del escenario de stress.
- `a_s`: multiplicador de severidad aplicado sobre `δ_s`.
- `x^{STR}_{s,k,t}`: macro estresada.
- `h^0_{i,k,t}`: hazard/PD base antes del shock.
- `h^{STR}_{i,s,k,t}`: hazard/PD después del shock.
- `M(a)`: métrica objetivo bajo severidad `a`, por ejemplo ECL, provisión o pérdida.
- `τ`: umbral objetivo de reverse stress.

**Escenarios severos parametrizables.** Un escenario de stress es una colección declarativa de shocks:

```text
x^{STR}_{s,k,t,j} = apply(x_{k,t,j}, a_s · δ_{s,j}, operation_j)
```

con `operation_j ∈ {"additive", "relative"}`:

```text
additive: x_str = x + a_s · δ
relative: x_str = x · (1 + a_s · δ)
```

`stress` no decide si `δ` es macroeconómicamente plausible. Valida que el shock esté declarado, que los factores existan, que no produzca valores no finitos, y que la fuente quede auditada. La plausibilidad regulatoria/institucional es responsabilidad del usuario o de una fuente oficial que se conecte como input; si no existe, queda `FALTA-DATO-STR`.

**Más severo que `adverse`.** SDD-20 ya define escenarios base/adverse/severe para forward. `stress` se ubica fuera del caso base IFRS 9: puede tomar el escenario `severe` forward como punto de partida o aplicar shocks adicionales sobre cualquier escenario forward. Si `cfg.validation.require_dominates_forward_adverse=True`, cada shock comparable debe cumplir:

```text
abs(a_s · δ_{s,j}) >= abs(δ_adverse,j)
```

para factores y operaciones comparables. Si no existe `δ_adverse,j` trazable en forward, el motor no inventa la comparación: registra `FALTA-DATO-STR-1` y falla cuando `fail_on_falta_dato=True`.

**Satellite bajo stress.** La propagación central reutiliza la forma de SDD-20:

```text
logit(h_{i,s,k,t}) = logit(h^0_{i,k,t}) + β' · Δx^{STR}_{s,k,t}
```

donde `Δx^{STR}` es la diferencia entre la macro estresada y la referencia configurada del satellite. La salida se transforma con `sigmoid`, se recomponen `survival`, `pd_marginal` y `pd_cumulative`, y se preservan las columnas PIT/TTC publicadas por forward.

**Sensibilidad de un factor.** Un barrido de sensibilidad fija un factor `j`, una grilla ordenada de severidades `a_1, ..., a_m`, y una métrica:

```text
Sensitivity(j, a_r) = M(x + a_r · δ_j) - M(x)
```

La grilla es determinista. No hay simulación Monte Carlo en v1. Si se agregara simulación futura, quedaría detrás de config explícita y semilla auditada; no pertenece al alcance B21.

**Reverse stress testing.** Dado un target `M(a) >= τ` o `M(a) <= τ`, `stress` busca la severidad mínima dentro de un bracket `[lo, hi]` usando bisección monotónica:

```text
lo = bracket_min
hi = bracket_max
for iter in 1..max_iterations:
    mid = (lo + hi) / 2
    value = M(mid)
    if abs(value - τ) <= metric_tol or (hi - lo) <= severity_tol:
        return mid, value
    if target es creciente:
        if value >= τ: hi = mid
        else: lo = mid
    si target es decreciente:
        if value <= τ: hi = mid
        else: lo = mid
```

Antes de iterar se evalúan `M(lo)` y `M(hi)`. Si el umbral no queda bracketed, se levanta `ReverseStressError` con valores observados. Si `M` no es monotónica en puntos de diagnóstico configurados, se levanta `NonMonotonicStressError`; no se cambia a un optimizador heurístico.

**Frameworks conceptuales.** EBA EU-wide, Fed CCAR/DFAST e ICAAP aparecen solo como referencias conceptuales porque ESPECIFICACIONES los nombra en §5.7 (ESPECIFICACIONES.md:L153). Este SDD no copia escenarios, trayectorias, horizontes, shocks, umbrales de capital ni criterios de aprobación de esos marcos. En v1 todo shock oficial debe entrar como input versionado del usuario.

**Relación con validación F6.** Stress testing responde "qué pasa si" y "qué shock rompe un umbral". Validación/backtesting responde "qué tan bien modeló". Aunque ambos usan outputs de PD/ECL, sus métricas y tests formales pertenecen a SDD-22 por la nota de fase de ESPECIFICACIONES (ESPECIFICACIONES.md:L152-L155).

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

`config.py` expone `StressConfig` y submodelos `StressInputConfig`, `StressShockConfig`, `StressScenarioConfig`, `SensitivitySweepConfig`, `StressTargetConfig`, `ReverseStressConfig`, `StressOutputConfig` y `StressValidationConfig` (§5).

```python
# nikodym/stress/exceptions.py
class StressError(NikodymError): ...
class StressConfigError(StressError): ...
class StressInputError(StressError): ...
class StressScenarioError(StressError): ...
class StressEngineError(StressError): ...
class StressOutputError(StressError): ...
class ReverseStressError(StressEngineError): ...
class NonMonotonicStressError(ReverseStressError): ...
class StressDependencyError(StressError): ...
class StressFaltaDatoError(StressError): ...
```

```python
# nikodym/stress/results.py
class StressScenarioResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    scenario_name: str
    scenario_kind: Literal["severe", "custom", "sensitivity", "reverse"]
    severity: float
    stressed_macro_frame: "pandas.DataFrame"
    stressed_term_structure_frame: "pandas.DataFrame"
    impact_frame: "pandas.DataFrame"
    warning_codes: tuple[str, ...] = ()

class StressSensitivityResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    sweep_name: str
    factor: str
    severity_grid: tuple[float, ...]
    sensitivity_frame: "pandas.DataFrame"
    baseline_metric_frame: "pandas.DataFrame"
    monotonicity_flag: Literal["increasing", "decreasing", "flat", "non_monotonic"]

class ReverseStressResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    target_name: str
    metric: str
    threshold: float
    direction: Literal["at_least", "at_most"]
    severity: float
    metric_value: float
    iterations: int
    bracket: tuple[float, float]
    converged: bool
    reverse_path_frame: "pandas.DataFrame"

class StressDiagnostics(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    scenario_count: int
    sensitivity_count: int
    reverse_count: int
    falta_dato_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()
    dependency_versions: dict[str, str] = Field(default_factory=dict)

class StressCard(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    summary: dict[str, str | int | float | bool]
    metric_sections: dict[str, object] = Field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

class StressResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    scenario_results: tuple[StressScenarioResult, ...]
    sensitivity_results: tuple[StressSensitivityResult, ...] = ()
    reverse_results: tuple[ReverseStressResult, ...] = ()
    stress_term_structure_frame: "pandas.DataFrame"
    stress_impact_frame: "pandas.DataFrame"
    diagnostics: StressDiagnostics
    card: StressCard
    def term_structure(self) -> "pandas.DataFrame | None": ...
    def tidy(self) -> "pandas.DataFrame": ...
```

`StressResult.term_structure()` cumple CT-2 y retorna la term-structure estresada tidy cuando existe. `tidy()` retorna la tabla de impactos por escenario/severidad/métrica, apta para reportes y UI.

```python
# nikodym/stress/engine.py
@runtime_checkable
class EclEngineLike(Protocol):
    def calculate(self, ecl_input: "ForwardEclInput") -> "pandas.DataFrame": ...

@runtime_checkable
class ProvisionEngineLike(Protocol):
    def calculate(self, ecl_frame: "pandas.DataFrame") -> "pandas.DataFrame": ...

class StressTestEngine:
    config_cls: ClassVar[type[StressConfig]] = StressConfig

    @classmethod
    def from_config(cls, cfg: StressConfig) -> "StressTestEngine": ...

    def run(
        self,
        *,
        forward_ecl_input: "ForwardEclInput",
        macro_projection: "pandas.DataFrame",
        satellite_model: object,
        forward_term_structure: "pandas.DataFrame",
        scenario_weighting: object,
        ecl_engine: "EclEngineLike | None" = None,
        provision_engine: "ProvisionEngineLike | None" = None,
        audit: "AuditSink | None" = None,
    ) -> StressResult: ...

    def run_scenario(
        self,
        scenario: StressScenarioConfig,
        *,
        severity: float = 1.0,
    ) -> StressScenarioResult: ...

    def run_sensitivity(
        self,
        sweep: SensitivitySweepConfig,
    ) -> StressSensitivityResult: ...

    def run_reverse_stress(
        self,
        target: StressTargetConfig,
        reverse: ReverseStressConfig,
    ) -> ReverseStressResult: ...
```

**Atributos fiteados/ejecutados.** `forward_hash_`, `config_hash_`, `scenario_results_`, `sensitivity_results_`, `reverse_results_`, `diagnostics_`, `dependency_versions_` y `run_started_at_`. No hay estado entrenado permanente; el engine es un executor determinista.

```python
# nikodym/stress/step.py
@register("standard", domain="stress")
class StressStep(AuditableMixin):
    name: str = "stress"
    requires: tuple[ArtifactKey, ...]
    provides: tuple[ArtifactKey, ...] = (
        ("stress", "engine"),
        ("stress", "scenarios"),
        ("stress", "term_structure"),
        ("stress", "impact"),
        ("stress", "sensitivity"),
        ("stress", "reverse"),
        ("stress", "diagnostics"),
        ("stress", "result"),
        ("stress", "card"),
    )
    @classmethod
    def from_config(cls, cfg: StressConfig) -> "StressStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "StressResult": ...
```

**Artefactos que `StressStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"engine"` | `StressTestEngine` | executor configurado |
| `"scenarios"` | `pandas.DataFrame` | escenarios/severidades aplicadas y shocks usados |
| `"term_structure"` | `pandas.DataFrame` | term-structure estresada CT-2 |
| `"impact"` | `pandas.DataFrame` | impactos por métrica, escenario y severidad |
| `"sensitivity"` | `tuple[StressSensitivityResult, ...]` | resultados de barridos |
| `"reverse"` | `tuple[ReverseStressResult, ...]` | resultados de reverse stress |
| `"diagnostics"` | `StressDiagnostics` | warnings, FALTA-DATO, monotonicidad y dependencias |
| `"result"` | `StressResult` | contenedor agregado |
| `"card"` | `StressCard` | resumen governance/report con `metric_sections` CT-2 |

```python
# nikodym/stress/config.py
StressOperation = Literal["additive", "relative"]
StressMetric = Literal["pd_marginal", "pd_cumulative", "lgd", "ecl", "provision", "loss", "ratio"]
StressDirection = Literal["at_least", "at_most"]

class StressInputConfig(NikodymBaseConfig): ...
class StressShockConfig(NikodymBaseConfig): ...
class StressScenarioConfig(NikodymBaseConfig): ...
class SensitivitySweepConfig(NikodymBaseConfig): ...
class StressTargetConfig(NikodymBaseConfig): ...
class ReverseStressConfig(NikodymBaseConfig): ...
class StressOutputConfig(NikodymBaseConfig): ...
class StressValidationConfig(NikodymBaseConfig): ...
class StressConfig(NikodymBaseConfig): ...
```

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "model", "survival", "markov", "forward", "stress"])
stress_result = study.artifacts.get("stress", "result")
stress_term_structure = stress_result.term_structure()
reverse = study.artifacts.get("stress", "reverse")

# Futuro SDD-16/17, no implementado aquí:
# ifrs9_engine = study.artifacts.get("provisioning_ifrs9", "engine")
# stress = StressTestEngine.from_config(cfg.stress)
# result = stress.run(..., ecl_engine=ifrs9_engine)
```

## 5. Configuración (schema Pydantic)

`StressConfig` es el sub-config de la sección `stress` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, `Literal` para categóricos, rangos explícitos, defaults defendibles y metadata UI. `stress ∉ INFRA_SECTIONS`: todo cambio computacional mueve `config_hash`. En este ítem solo-docs no se mueve `GOLDEN_DEFAULT_CONFIG_HASH`; al implementar B21.1 debe moverse si `stress` se cablea en `NikodymConfig`, igual que SDD-20 anticipa para `forward` (20-forward.md:L700).

```python
# nikodym/stress/config.py
class StressInputConfig(NikodymBaseConfig):
    forward_domain: str = "forward"
    macro_projection_key: str = "macro_projection"
    satellite_model_key: str = "satellite_model"
    term_structure_key: str = "term_structure"
    scenario_weighting_key: str = "scenario_weighting"
    ecl_input_key: str = "ecl_input"
    ecl_engine_artifact: tuple[str, str] | None = None
    provision_engine_artifact: tuple[str, str] | None = None

class StressShockConfig(NikodymBaseConfig):
    factor: str
    operation: Literal["additive", "relative"] = "additive"
    value: float
    unit: str | None = None
    periods: tuple[int, ...] | Literal["all"] = "all"
    source: Literal["user", "institutional", "official", "default_a_confirmar"] = "user"
    description: str | None = None

class StressScenarioConfig(NikodymBaseConfig):
    name: str
    kind: Literal["severe", "custom"] = "severe"
    base_forward_scenario: str = "severe"
    severity: float = Field(default=1.0, ge=0.0)
    shocks: tuple[StressShockConfig, ...] = Field(..., min_length=1)
    weight: float | None = Field(default=None, ge=0.0, le=1.0)
    require_dominates_forward_adverse: bool = True
    description: str | None = None

class SensitivitySweepConfig(NikodymBaseConfig):
    name: str
    factor: str
    operation: Literal["additive", "relative"] = "additive"
    base_forward_scenario: str = "severe"
    shock_value: float
    severity_grid: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5, 2.0)
    metric: StressMetric = "ecl"
    group_cols: tuple[str, ...] = ("scenario",)
    require_monotonic: bool = False

class StressTargetConfig(NikodymBaseConfig):
    name: str
    metric: StressMetric
    threshold: float
    direction: Literal["at_least", "at_most"] = "at_least"
    scenario_name: str
    group_filter: dict[str, str | int | float | bool] = Field(default_factory=dict)
    requires_economic_engine: bool = True

class ReverseStressConfig(NikodymBaseConfig):
    enabled: bool = False
    target: StressTargetConfig | None = None
    factor: str
    operation: Literal["additive", "relative"] = "additive"
    shock_value: float
    bracket: tuple[float, float] = (0.0, 5.0)
    severity_tol: float = Field(default=1e-6, gt=0.0, lt=1e-2)
    metric_tol: float = Field(default=1e-8, gt=0.0, lt=1e-2)
    max_iterations: int = Field(default=64, ge=1, le=256)
    monotonicity_check_points: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0, 5.0)

class StressOutputConfig(NikodymBaseConfig):
    metrics: tuple[StressMetric, ...] = ("pd_marginal", "pd_cumulative", "ecl")
    publish_stressed_macro: bool = True
    publish_stressed_term_structure: bool = True
    publish_reverse_path: bool = True
    include_baseline_rows: bool = True

class StressValidationConfig(NikodymBaseConfig):
    probability_tol: float = Field(default=1e-10, gt=0.0, lt=1e-3)
    metric_tol: float = Field(default=1e-8, gt=0.0, lt=1e-2)
    weight_sum_tol: float = Field(default=1e-12, gt=0.0, lt=1e-3)
    require_forward_severe: bool = True
    require_dominates_forward_adverse: bool = True
    fail_on_missing_ecl_engine: bool = True
    fail_on_falta_dato: bool = True

class StressConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"
    input: StressInputConfig = Field(default_factory=StressInputConfig)
    scenarios: tuple[StressScenarioConfig, ...] = Field(default_factory=tuple)
    sensitivities: tuple[SensitivitySweepConfig, ...] = Field(default_factory=tuple)
    reverse: tuple[ReverseStressConfig, ...] = Field(default_factory=tuple)
    output: StressOutputConfig = Field(default_factory=StressOutputConfig)
    validation: StressValidationConfig = Field(default_factory=StressValidationConfig)
```

**Validaciones de config.**
- `scenarios`, `sensitivities` o `reverse` deben tener al menos un elemento; una config de stress vacía levanta `StressConfigError`.
- `StressScenarioConfig.name` debe ser único y no puede ser `mean`, `average` ni `weighted_mean_input`.
- `base_forward_scenario` debe existir en `forward.scenario_weighting` o en `macro_projection`.
- `shocks.factor` debe existir en `macro_projection.macro_variable` o en la metadata del satellite model.
- `operation="relative"` exige que el factor acepte escala relativa; si el factor puede ser cero o negativo y no se declaró política, `StressConfigError`.
- `periods` debe ser `"all"` o una tupla no vacía de períodos positivos dentro del horizonte forward.
- `severity_grid` debe estar ordenada de forma estrictamente creciente, contener valores finitos y no negativos.
- `reverse.bracket` debe cumplir `lo < hi`, ambos finitos y no negativos.
- `reverse.target` es obligatorio cuando `reverse.enabled=True`.
- Targets `ecl`, `provision`, `loss` o `ratio` requieren `ecl_engine_artifact` o un engine pasado por API si `requires_economic_engine=True`.
- Si `require_dominates_forward_adverse=True` y no se puede demostrar dominancia frente a forward adverse, se registra `FALTA-DATO-STR-1` y por default falla.
- Si se marca `source="official"` sin metadata de archivo/hash/fuente externa en el input, se registra `FALTA-DATO-STR-2` y por default falla.

**Campos, defaults y sentido.**
- `input.forward_domain`: dominio desde el que se leen artefactos forward; default `"forward"` por convención SDD-20.
- `input.*_key`: claves de artefactos forward; defaults alineados con `ForwardStep.provides` (20-forward.md:L344-L380).
- `input.ecl_engine_artifact`: hook opcional hacia SDD-16; sin import duro.
- `input.provision_engine_artifact`: hook opcional hacia SDD-17; solo requerido para provisión final.
- `StressShockConfig.value`: magnitud base del shock. No tiene default porque inventar un shock es regulatorio-metodológicamente incorrecto.
- `StressScenarioConfig.severity`: multiplicador sobre todos los shocks del escenario; default `1.0` es identidad del shock declarado, no severidad regulatoria.
- `StressScenarioConfig.weight`: opcional; si se declara, sirve para reportes de escenario, pero stress no sustituye la ponderación IFRS 9 oficial.
- `SensitivitySweepConfig.severity_grid`: default D-STR-1 `(0.0,0.5,1.0,1.5,2.0)`, **default a confirmar por Cami**.
- `ReverseStressConfig.bracket`: default D-STR-2 `(0.0,5.0)`, **default a confirmar por Cami**; no es límite regulatorio.
- `ReverseStressConfig.severity_tol`: default D-STR-3 `1e-6`, **default a confirmar por Cami**.
- `ReverseStressConfig.metric_tol`: default D-STR-4 `1e-8`, **default a confirmar por Cami**.
- `ReverseStressConfig.max_iterations`: default D-STR-5 `64`, suficiente para bisección doble precisión en brackets razonables, **default a confirmar por Cami**.
- `StressOutputConfig.metrics`: incluye `ecl` por defecto para exponer el alcance pedido; si no hay engine, se falla ruidoso o se reduce por config.

**Round-trip YAML y UI.** El round-trip sigue SDD-05: dump JSON-mode, `sort_keys=False`, carga vía `load_config`. La UI debe renderizar escenarios como tabla de shocks, grilla de sensibilidad como control numérico, reverse stress como target + bracket + tolerancias, y advertencias visibles para `FALTA-DATO-STR`.

**Hook diferido en `core.config.schema`.**
- declarar `_STRESS_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir `stress` como campo `Any` en runtime y `StressConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("stress", mode="before")`;
- no importar `nikodym.stress` desde `core`;
- al importar `nikodym.stress`, poblar el hook de forma análoga a `data`/`forward`;
- actualizar `GOLDEN_DEFAULT_CONFIG_HASH` en B21.1 si el campo `stress` queda dentro del hash canónico.

## 6. Contratos de datos (I/O)

**Input duro del Step según config.**

| artefacto | requerido | contrato |
|---|---:|---|
| `("forward","macro_projection")` | siempre | DataFrame tidy de SDD-20 con escenario/período/factor/valor |
| `("forward","satellite_model")` | siempre | objeto con contrato de predicción satellite o metadata suficiente |
| `("forward","term_structure")` | siempre | term-structure forward-looking tidy |
| `("forward","scenario_weighting")` | siempre | objeto/payload de ponderación de outputs |
| `("forward","ecl_input")` | siempre | `ForwardEclInput` de SDD-20 |
| `ecl_engine_artifact` | condicional | Protocol `EclEngineLike` si se calculan ECL/loss/ratio |
| `provision_engine_artifact` | condicional | Protocol `ProvisionEngineLike` si se calcula provisión final |

**Input `macro_projection` desde SDD-20.** Debe contener, como mínimo:
- `scenario`;
- `scenario_weight`;
- `period`;
- `time_value`;
- `macro_variable`;
- `projected_value`;
- `model_value`;
- `shock_value`;
- `method`;
- `model_id`;
- `is_reasonable_supportable`;
- `warning_codes`.

Estas columnas vienen del contrato forward (20-forward.md:L539-L555). `stress` agrega shocks sobre `projected_value` y conserva `model_value` para auditoría.

**Input `forward.term_structure`.** Debe contener, como mínimo:
- `row_id`, `segment`, `partition` si aplican;
- `source_model`;
- `period`, `time_value`;
- `scenario`, `scenario_weight`;
- `hazard`, `survival`, `pd_marginal`, `pd_cumulative`;
- `pd_marginal_base`, `pd_cumulative_base`;
- `pd_basis`, `basis_state`;
- `satellite_adjustment`, `macro_model_id`, `satellite_model_id`;
- `method`, `pd_source`, `warning_codes`.

El contrato forward está documentado en SDD-20 (20-forward.md:L556-L585). Si faltan columnas necesarias para recomponer lifetime, `StressInputError`.

**Input `ForwardEclInput`.** Se consume como DTO opaco:
- `term_structure_frame`;
- `scenario_weight_frame`;
- `pit_consistency`;
- `chain`;
- `contract_version`.

`stress` puede clonar y reemplazar `term_structure_frame` por la versión estresada antes de invocar `EclEngineLike`. No debe mutar el DTO original.

**Output `stress.scenarios`.** DataFrame tidy con `stress_scenario`, `scenario_kind`, `base_forward_scenario`, `severity`, `macro_variable`, `operation`, `shock_value`, `applied_shock`, `period`, `source` y `warning_codes`. La tabla registra exactamente qué shocks se aplicaron; no reemplaza la term-structure ni los impactos económicos.

**Output `stress.term_structure`.** DataFrame tidy CT-2:

| columna | significado |
|---|---|
| `stress_scenario` | escenario stress |
| `scenario_kind` | tipo de corrida |
| `severity` | severidad usada |
| `base_forward_scenario` | escenario forward base |
| `row_id` | id de observación/cuenta inicial si existe |
| `segment` | segmento/pool opcional |
| `partition` | partición si aplica |
| `source_model` | `"survival"` o `"markov"` heredado |
| `period` | horizonte ordinal |
| `time_value` | tiempo en unidad declarada |
| `macro_variable_set` | factores alterados, serializados de forma estable |
| `hazard_base` | hazard antes de stress |
| `hazard_stress` | hazard después de stress |
| `survival_stress` | supervivencia recomputada |
| `pd_marginal_base` | PD marginal forward original |
| `pd_marginal_stress` | PD marginal estresada |
| `pd_cumulative_base` | PD acumulada forward original |
| `pd_cumulative_stress` | PD acumulada estresada |
| `lgd_base` | LGD forward original si existe |
| `lgd_stress` | LGD estresada si existe |
| `pd_basis` | metadata PIT/TTC heredada |
| `basis_state` | `"pit"`, `"blended"` o `"ttc"` heredado |
| `satellite_adjustment_base` | delta logit forward original |
| `satellite_adjustment_stress` | delta logit adicional/final |
| `warning_codes` | warnings acumulados |

**Output `stress.impact`.** DataFrame tidy:

| columna | significado |
|---|---|
| `stress_scenario` | escenario stress |
| `scenario_kind` | tipo de corrida |
| `severity` | severidad |
| `metric` | `pd_marginal`, `pd_cumulative`, `lgd`, `ecl`, `provision`, `loss` o `ratio` |
| `value_base` | valor baseline comparable |
| `value_stress` | valor bajo stress |
| `absolute_delta` | `value_stress - value_base` |
| `relative_delta` | delta relativo si `value_base != 0` |
| `group_key` | grupo estable serializado (segmento, escenario, stage futuro) |
| `period` | período si aplica |
| `engine_source` | `"forward_only"`, `"ecl_engine"` o `"provision_engine"` |
| `warning_codes` | warnings acumulados |

**Output `stress.reverse_path`.** DataFrame tidy por target con `target_name`, `iteration`, `lo`, `hi`, `mid`, `metric_value`, `threshold` y `decision` (`"move_lo"`, `"move_hi"` o `"converged"`). Debe permitir reconstruir la bisección completa sin repetir la corrida.

**Invariantes.**
- No se publican `NaN`, `inf`, `-inf` ni `-0.0`; `-0.0` se normaliza a `0.0`.
- Las probabilidades quedan en `[0,1]` dentro de `probability_tol`.
- `pd_cumulative_stress` es no decreciente por `row_id/source_model/stress_scenario/severity`.
- `pd_marginal_stress(t) = survival_stress(t-1) * hazard_stress(t)` si `hazard` está disponible.
- No se mutan `forward.macro_projection`, `forward.term_structure`, `ForwardEclInput` ni engines conectados.
- Orden estable: escenarios en orden de config, severidades ascendentes, factores en orden declarado y períodos ascendentes.
- Si un target requiere ECL/provisión y el engine falta, no se publica un cero ni `None` silencioso: `StressDependencyError`.
- `StressResult.term_structure()` siempre retorna un DataFrame tidy o `None` solo si la config deshabilitó explícitamente `publish_stressed_term_structure`.

## 7. Algoritmos y flujo

**`StressStep.execute(study, rng)` - secuencia canónica.**
1. **Resolver config.** Leer `study.config.stress`; si falta en API programática, exigir `StressConfig`.
2. **Construir `requires`.** Desde `StressInputConfig` y targets; validar CT-1 antes de ejecutar.
3. **Controlar azar.** Hacer `del rng`; v1 no usa RNG.
4. **Leer artefactos forward.** Copiar defensivamente `macro_projection`, `forward.term_structure`, `scenario_weighting` y `ForwardEclInput`.
5. **Leer engines económicos condicionales.** Resolver `EclEngineLike`/`ProvisionEngineLike` solo si los targets/metrics lo requieren.
6. **Validar inputs.** Columnas, escenarios, factores, horizonte, finitud, PIT/TTC, ausencia de `scenario="mean"`.
7. **Construir escenarios stress.** Validar shocks, fuentes, severidad, períodos y dominancia frente a `adverse` si aplica.
8. **Aplicar shocks macro.** Generar `stressed_macro_frame` por escenario/severidad sin mutar el frame forward.
9. **Aplicar satellite.** Reusar `satellite_model` para producir hazard/PD/LGD bajo macro estresada.
10. **Recomponer lifetime.** Recalcular survival, PD marginal y acumulada desde hazards estresados.
11. **Construir input ECL estresado.** Clonar `ForwardEclInput` y sustituir la term-structure si hay engine.
12. **Calcular métricas.** PD/LGD desde frames; ECL/provisión vía engines conectados.
13. **Ejecutar sensibilidades.** Para cada `SensitivitySweepConfig`, iterar grilla, calcular impactos y monotonicidad.
14. **Ejecutar reverse stress.** Para cada `ReverseStressConfig.enabled`, validar bracket, chequear monotonicidad y correr bisección.
15. **Validar invariantes.** Probabilidades, monotonicidad, columnas, no finitos, engines requeridos y outputs.
16. **Construir DTOs.** `StressDiagnostics`, `StressCard`, `StressResult` y subresultados frozen.
17. **Auditar decisiones.** Escenarios, shocks, FALTA-DATO, sensibilidad, reverse path, engines y resultados.
18. **Publicar artefactos.** Escribir todas las claves `provides` bajo `"stress"`.

**Flujos internos por clase.**
- `StressTestEngine.run` prepara el contexto immutable de forward, valida engines y orquesta escenarios/sensibilidades/reverse.
- `run_scenario` aplica un `StressScenarioConfig` a una severidad concreta y devuelve macro, term-structure e impactos.
- `run_sensitivity` llama `run_scenario` por cada severidad de la grilla, concatena impactos y calcula monotonicidad por métrica/grupo.
- `run_reverse_stress` evalúa la métrica target en `lo` y `hi`, comprueba bracket, ejecuta bisección y devuelve el path completo si `publish_reverse_path=True`.

**Bisección determinista.**
- No usa `scipy.optimize`, métodos aleatorios ni heurísticas.
- El punto medio se calcula como `lo + (hi - lo) / 2` para estabilidad.
- Con `bracket=(0,5)` y `severity_tol=1e-6`, el máximo teórico de iteraciones para contraer el bracket es `ceil(log2(5/1e-6)) = 23`; `max_iterations=64` deja margen sin ocultar no convergencia.
- Si el target es `at_least`, el resultado reportado es el menor `hi` conocido que cumple el umbral dentro de tolerancia.
- Si el target es `at_most`, el resultado reportado es el menor o mayor extremo según la dirección declarada, pero siempre se documenta la convención en `ReverseStressResult`.

**Alternativas descartadas.**
- *Monte Carlo stress por default:* descartado; v1 requiere determinismo y auditabilidad completa.
- *Optimización genérica no monotónica:* descartada; reverse stress v1 exige monotonicidad para que el resultado sea interpretable.
- *Escenarios oficiales embebidos:* descartado; la especificación no entrega parámetros y no se inventan números regulatorios.
- *Calcular ECL internamente:* descartado; violaría la frontera con SDD-16.
- *Recalibrar satellite bajo stress:* descartado; stress evalúa sensibilidad de una cadena ya aprobada, no reentrena.
- *Promediar macro o PD antes de ECL:* descartado por la no linealidad ya documentada en SDD-20 (20-forward.md:L195-L207).
- *Importar pandas/numpy/scipy/statsmodels en `__init__`:* descartado; viola núcleo liviano.

**Complejidad / rendimiento.** El tamaño dominante es `O(N·H·K·S·Q·F)` para filas de term-structure, horizonte, escenarios forward, escenarios stress, severidades y factores. Reverse stress multiplica por `iterations`. B21 debe validar tamaño estimado antes de materializar y registrar `n_rows_stress_term_structure`, `n_sensitivity_evaluations` y `n_reverse_evaluations`.

## 8. Casos borde y manejo de errores

- **Falta `forward` completo:** `ArtifactNotFoundError` por CT-1 antes de ejecutar.
- **`ForwardEclInput` ausente o versión incompatible:** `StressDependencyError`.
- **Macro projection sin factor shockeado:** `StressInputError` listando factores faltantes.
- **Term-structure sin columnas de recomposición lifetime:** `StressInputError`.
- **Satellite model sin método compatible de predicción:** `StressDependencyError`.
- **Escenario stress sin shocks:** `StressConfigError`.
- **Shock con `value=0` y escenario marcado severe:** permitido solo si se declara `kind="custom"`; si no, `StressScenarioError`.
- **Operación relativa sobre factor con ceros/negativos sin política:** `StressConfigError`.
- **Períodos fuera del horizonte forward:** `StressConfigError`.
- **No existe `base_forward_scenario`:** `StressScenarioError`.
- **No se puede comparar dominancia frente a adverse:** `FALTA-DATO-STR-1`; por default falla.
- **Fuente oficial declarada sin evidencia/hash:** `FALTA-DATO-STR-2`; por default falla.
- **Probabilidades fuera de `[0,1]`:** `StressEngineError`; no se clipea silenciosamente fuera de tolerancia.
- **PD acumulada decrece tras stress:** `StressEngineError`.
- **Engine ECL requerido y ausente:** `StressDependencyError`.
- **Engine económico devuelve columnas no esperadas o no finitas:** `StressOutputError`.
- **Sensitivity grid vacía, duplicada o no ordenada:** `StressConfigError`.
- **Target reverse sin bracket:** `StressConfigError`.
- **Target reverse no bracketed:** `ReverseStressError` con `M(lo)`, `M(hi)` y `threshold`.
- **Métrica reverse no monotónica:** `NonMonotonicStressError` con puntos evaluados.
- **Bisección no converge en `max_iterations`:** `ReverseStressError` salvo que `allow_non_converged=True` se agregue en un futuro SDD; v1 falla.
- **Warnings de dependencias:** se convierten en diagnostics explícitos o excepciones controladas; `filterwarnings=["error"]` debe mantenerse.

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen escenario, factor, severidad, período, métrica y valor observado cuando aplique.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno por default. `StressTestEngine` es determinista dados forward artifacts, config y engines deterministas.
- **RNG explícito.** `StressStep.execute` recibe `rng` por contrato homogéneo y hace `del rng`.
- **Reverse stress determinista.** Bisección monotónica con `severity_tol`, `metric_tol`, `max_iterations` y bracket explícitos.
- **Determinismo esperado.** `(forward_hash + config_hash + shock_config + engine_versions) → stress_term_structure, impacts, reverse paths, diagnostics y card idénticos`.
- **Orden estable.** Escenarios en orden de config, severidades ascendentes, factores en orden declarado, grupos ordenados por claves serializadas y períodos ascendentes.
- **Copias defensivas.** No muta artefactos forward ni outputs de engines económicos.
- **Normalización numérica.** `-0.0 → 0.0`; valores dentro de tolerancia se normalizan con warning; fuera de tolerancia fallan.
- **Hashes auxiliares.** Si se hashean macro frames o term-structures, usar `pandas.util.hash_pandas_object` con conversión endian explícita `.astype("<u8")`; nunca bytes Parquet ni `hash()` builtin.
- **Núcleo liviano.** `import nikodym.stress` no debe importar `pandas`, `numpy`, `scipy`, `statsmodels` ni `nikodym.provisioning`; imports dentro de `run`, `execute` o validadores runtime.
- **TYPE_CHECKING.** Las anotaciones de DataFrame, `ForwardEclInput`, `AuditSink` y Protocols económicos usan strings o imports bajo `TYPE_CHECKING`.
- **Pandera.** Si se usa para validación, importar `pandera.pandas as pa` dentro de función; nunca `import pandera` top-level.
- **Audit trail (`log_decision`).** Registrar como mínimo:
  - `stress_forward_inputs`: claves, hashes auxiliares, escenarios forward y contract_version;
  - `stress_scenario_config`: nombres, fuentes, factores, operaciones, severidades y períodos;
  - `stress_dominance_check`: comparación frente a adverse/severe forward o `FALTA-DATO`;
  - `stress_macro_application`: filas afectadas, valores base, shocks aplicados y warnings;
  - `stress_satellite_application`: modelo satellite, factores, coeficientes/metadata y delta logit;
  - `stress_term_structure`: filas, probabilidades, monotonicidad y basis PIT/TTC;
  - `stress_economic_engine`: engine usado, versión, métricas calculadas y ausencia si no aplica;
  - `stress_sensitivity`: grilla, métrica, resultados, monotonicidad y warnings;
  - `stress_reverse`: target, bracket, tolerancias, iteraciones, convergencia y path;
  - `stress_falta_dato`: brechas `FALTA-DATO-STR` y si bloquearon.
- **Card / report.** `StressCard.metric_sections` debe incluir `"scenario_impacts"`, `"sensitivity_curves"`, `"reverse_stress"`, `"term_structure_summary"` y `"falta_dato"` cuando existan.
- **Lineage.** `stress` consume `config_hash` y hashes auxiliares de forward; agrega hashes de stress inputs/outputs, no reemplaza el lineage base.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymError`, `MissingDependencyError`, lineage, `config_hash` y patrón CT-2 `term_structure()`.
- SDD-02 (`data`): mecanismo de hash lógico y helpers de validación si se reutilizan sin acoplar datos longitudinales.
- SDD-05 (convenciones): Pydantic v2, hooks diferidos, `extra="forbid"`, `frozen=True`, naming inglés para APIs/stats y español para docs/errores.
- SDD-18 (`survival`): fuente indirecta de term-structure lifetime PD.
- SDD-19 (`markov`): fuente indirecta de term-structure lifetime PD.
- SDD-20 (`forward`): dependencia directa; macro projection, satellite model, term-structure, scenario weighting y `ForwardEclInput`.

**Aguas abajo.**
- SDD-16 (`provisioning/ifrs9`) consume resultados stress para entender sensibilidad de ECL y puede proveer `EclEngineLike`.
- SDD-17 (`provisioning`) puede proveer `ProvisionEngineLike` para provisión final y piso prudencial.
- SDD-22 (`validation`) valida/backtestea modelos y puede usar outputs stress como insumos de análisis, pero no al revés.
- SDD-23 (`ui`) edita config y muestra shocks/reverse paths.
- SDD-26 (`report`) renderiza escenarios, sensibilidad, reverse stress y model card.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | `>=2.0` | BSD-3 ✅ | frames tidy, joins, outputs | base de `data`; import perezoso en `stress` |
| numpy | `>=1.22` | BSD ✅ | sigmoid/logit, finitud, arrays | base; import perezoso |
| pydantic | `>=2` | MIT ✅ | config/DTOs frozen | base |

**Sin nueva dependencia pesada.**
- Reverse stress usa bisección propia; no requiere `scipy.optimize`.
- `stress` no importa `statsmodels`; el ajuste macro/satellite pertenece a SDD-20.
- No se agregan paquetes GPL/LGPL/AGPL.
- Si un engine económico futuro trae dependencias propias, las declara SDD-16/17, no SDD-21.

**Núcleo liviano.**
- `nikodym.core` no importa `nikodym.stress`.
- `import nikodym.stress` no importa `pandas`, `numpy`, `scipy`, `statsmodels` ni `nikodym.provisioning`.
- `stress.__init__` debe exponer config/errores/registro usando anotaciones string y `TYPE_CHECKING`.
- Mensajes de dependencia faltante deben nombrar el extra correcto del owner futuro; `stress` no inventa `nikodym[stress]` si no existe.

## 11. Estrategia de tests

Marco transversal en SDD-24. Cobertura objetivo 100% para módulos `stress`. `filterwarnings=["error"]`, `mypy --strict`, ruff `E,F,I,N,UP,B,SIM,RUF,D` y docstrings públicas en español.

- **Golden shock satellite logit.** Base hazard `0.02`, shock macro `x=1`, `β=0.5`: `logit(0.02)=-3.8918202981`, ajuste `-3.3918202981`, PD esperada `0.0325520809`, alineado con SDD-20 (20-forward.md:L748-L752).
- **Golden ECL un período por engine stub.** Con `PD=0.0325520809`, `LGD=0.45`, `EAD=1000`, sin descuento: `ECL=14.6484363909`. Baseline sin shock `PD=0.02` da `ECL=9.0`; impacto absoluto `5.6484363909`.
- **Golden sensibilidad de un factor.** Mismo setup, severidad `1.25` produce `PD=0.0367271551`, `ECL=16.5272197816`; frente a severidad `1.0`, `ΔECL=1.8787833907`.
- **Golden reverse stress.** Target `ECL >= 25.0`, `LGD=0.45`, `EAD=1000`, shock `x=severity`, `β=0.5`: `PD_target=25/(0.45*1000)=0.0555555556`; severidad esperada `2.1172139081` dentro de `1e-6`.
- **Golden recomposición lifetime identidad.** Si el shock es cero sobre hazards `0.10`, `0.20`, la salida conserva `survival(1)=0.90`, `pd_marginal(1)=0.10`, `survival(2)=0.72`, `pd_marginal(2)=0.18`, `pd_cumulative(2)=0.28`, alineado con SDD-20.
- **Bisección bracket.** Si `M(lo) < τ < M(hi)`, converge en menos de 64 iteraciones y publica `reverse_path_frame` estable.
- **Bisección sin bracket.** Si target queda fuera de `[lo,hi]`, `ReverseStressError` incluye `M(lo)`, `M(hi)` y `threshold`.
- **No monotonicidad.** Un engine stub no monotónico activa `NonMonotonicStressError` cuando `require_monotonic=True`.
- **Dominancia adverse.** Si `require_dominates_forward_adverse=True` y el shock severo es menor que adverse comparable, `StressScenarioError`.
- **FALTA-DATO escenarios oficiales.** `source="official"` sin hash/fuente registra `FALTA-DATO-STR-2` y falla con `fail_on_falta_dato=True`.
- **Engine faltante.** Métrica `ecl` sin `EclEngineLike` levanta `StressDependencyError` si `fail_on_missing_ecl_engine=True`.
- **Forward-only.** Métricas `pd_marginal`/`pd_cumulative` funcionan sin ECL engine y publican `engine_source="forward_only"`.
- **CT-1 dinámico.** `StressStep.from_config` requiere artefactos forward y agrega engine artifacts solo si targets lo necesitan.
- **CT-2.** `StressResult.term_structure()` retorna DataFrame tidy; `StressCard.metric_sections` acepta sensibilidad y reverse stress estructurados.
- **No mutación.** Snapshots profundos de macro projection, term-structure y `ForwardEclInput` permanecen iguales.
- **Determinismo.** Dos corridas con mismos frames/config/engine stub producen outputs byte-equivalentes tras normalización.
- **Import guard.** Subproceso verifica que `import nikodym.stress` no deja `pandas`, `numpy`, `scipy`, `statsmodels` ni `nikodym.provisioning` en `sys.modules`.
- **Config round-trip/hash.** YAML dump/load preserva shocks, grillas, brackets y tolerancias; cambiar esos campos mueve `config_hash`.
- **Warnings como error.** Warnings de engines se convierten en exceptions controladas o diagnostics explícitos.
- **Endianness/hash.** Cualquier hash auxiliar usa `.astype("<u8")`; test de grep impide `hash()` builtin en rutas de identidad.
- **Sin métricas SDD-22.** Grep/test documental impide implementar AUC/Gini/KS/PSI/Hosmer/Brier en `stress`; esos nombres pueden aparecer solo como frontera hacia SDD-22.

Fixtures: `forward_macro_projection_small.parquet` sintético, `forward_term_structure_small.parquet`, `ForwardEclInput` mínimo, `FakeSatelliteModel`, `FakeEclEngine`, `FakeProvisionEngine`, `StressConfig` mínimo, escenarios severos con shocks explícitos, sensibilidad de un factor, reverse target bracketed/no bracketed, `InMemoryAuditSink`, y datasets degenerados para factores faltantes, no finitos, probabilidades fuera de rango y monotonicidad rota.
## 12. Decisiones abiertas y riesgos

**R0 (Cami).** Ninguno por ahora. No se fija producto irreversible, release público, escenarios oficiales, umbrales regulatorios ni parámetros de capital. Las decisiones D-STR son defaults metodológicos editables y se listan para revisión de Cami; no improvisan alcance regulatorio.

**D-STR para revisión de Cami.**
- **D-STR-1 — Grilla default de sensibilidad.** Recomendación: `(0.0, 0.5, 1.0, 1.5, 2.0)`, **default a confirmar por Cami**. Es útil para smoke tests y UI, no para regulación.
- **D-STR-2 — Bracket default de reverse stress.** Recomendación: `(0.0, 5.0)`, **default a confirmar por Cami**. Debe ser editable por cartera/factor.
- **D-STR-3 — Tolerancia de severidad.** Recomendación: `severity_tol=1e-6`, **default a confirmar por Cami**.
- **D-STR-4 — Tolerancia de métrica.** Recomendación: `metric_tol=1e-8`, **default a confirmar por Cami**.
- **D-STR-5 — Iteraciones máximas reverse.** Recomendación: `max_iterations=64`, **default a confirmar por Cami**.
- **D-STR-6 — Reverse stress en v0.1.0 de stress.** Recomendación: incluirlo en B21.2 porque ESPECIFICACIONES lo nombra explícitamente, pero con targets configurados por usuario.
- **D-STR-7 — ECL como métrica default.** Recomendación: dejar `ecl` en `output.metrics` para representar el objetivo económico, pero fallar ruidoso si no hay engine.
- **D-STR-8 — Dominancia frente a adverse.** Recomendación: exigir dominancia cuando los shocks sean comparables y fallar con `FALTA-DATO` si no se puede demostrar.
- **D-STR-9 — Operación de shock default.** Recomendación: `additive` por transparencia en factores macro expresados en puntos/tasas, **default a confirmar por Cami**.
- **D-STR-10 — Sin Monte Carlo en v1.** Recomendación: no incluir simulación hasta tener validación y governance de semillas; stress v1 determinista.

**FALTA-DATO explícitos.**
- **FALTA-DATO-STR-1 — Shocks adverse/severe comparables de forward.** Si forward no trae magnitudes trazables por factor, no se puede probar que stress domina adverse.
- **FALTA-DATO-STR-2 — Escenarios oficiales EBA/CCAR/DFAST/ICAAP.** No hay paths ni parámetros oficiales embebidos; deben venir de fuente institucional/oficial versionada.
- **FALTA-DATO-STR-3 — Umbrales de capital o pérdida regulatorios chilenos.** No se inventan thresholds para reverse stress; el usuario los declara.
- **FALTA-DATO-STR-4 — Calibración institucional de severidades.** Magnitudes de shocks por cartera/factor deben venir del usuario o análisis aprobado.
- **FALTA-DATO-STR-5 — Motor ECL/provisión conectado.** Los impactos económicos completos requieren un artefacto de engine explícito; `stress` no importa ni adivina SDD-16/17.
- **FALTA-DATO-STR-6 — Métricas ratio específicas.** Denominadores como capital, patrimonio efectivo, RWA o cartera vigente no están definidos en SDD-21.
- **FALTA-DATO-STR-7 — Política de shock relativo sobre factores negativos.** Debe declararse por factor si se usa `operation="relative"`.

**Riesgos y mitigaciones.**
- **Stress se confunde con validación.** Mitigación: frontera dura hacia SDD-22 en §1/§2 y test anti métricas de validación.
- **Defaults confundidos con escenarios regulatorios.** Mitigación: D-STR marcados como "default a confirmar por Cami" y `source="default_a_confirmar"` nunca usado como escenario oficial.
- **Falsa precisión de reverse stress.** Mitigación: bisección con bracket/tolerancias auditadas y error si no hay monotonicidad.
- **Sobreacoplamiento a IFRS 9.** Mitigación: Protocols `EclEngineLike`/`ProvisionEngineLike`, cero imports runtime de SDD-16/17 y modo forward-only.
- **Dependencias pesadas en import.** Mitigación: imports perezosos y tests `sys.modules`.
- **Explosión de tamaño de salida.** Mitigación: estimación previa, límites configurables y diagnostics de filas/evaluaciones.
- **Shocks macro incompatibles con satellite.** Mitigación: validación de factores, operaciones y períodos antes de ejecutar.
- **Pérdida de PIT/TTC metadata.** Mitigación: heredar `pd_basis`/`basis_state` y validar term-structure CT-2.
- **No monotonicidad económica real.** Mitigación: reverse stress v1 exige monotonicidad declarada/diagnosticada; no devuelve resultados heurísticos.

**Citas internas.** ESPECIFICACIONES.md §5.6/§5.7; ROADMAP.md F5; `00-INDICE.md` fila SDD-21; `_CONTRATOS-TRANSVERSALES.md` CT-1/CT-2/CT-3; SDD-18 (`survival`); SDD-19 (`markov`); SDD-20 (`forward`); SDD-24 (`testing`); SDD-25 (`packaging/CI`).
