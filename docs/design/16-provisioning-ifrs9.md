# SDD-16 — `provisioning/ifrs9` (IFRS 9 / ECL: PD/LGD/EAD, staging, motor ECL)

| Campo | Valor |
|---|---|
| **SDD** | 16 |
| **Módulo** | `nikodym.provisioning.ifrs9` |
| **Dominio** | Provisiones |
| **Fase** | F4 |
| **Tanda de producción** | T4 (Provisiones) |
| **Estado** | ✅ Implementado; API experimental |
| **Depende de** | SDD-01 (`core`), SDD-02 (`data`), SDD-05 (convenciones + config), SDD-10 (`calibration`); SDD-18 (`survival`) / SDD-19 (`markov`) como proveedores intercambiables de term-structure lifetime; SDD-20 (`forward`) como proveedor opcional de term-structure multiescenario PIT |
| **Lo consumen** | SDD-17 (`provisioning`, comparativo configurable no normativo frente a CMF), SDD-22 (`validation`), SDD-23 (`ui`), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (redacción SDD-16 para T4/F4) / 2026-07-02 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `provisioning.ifrs9` calcula la pérdida esperada contable **IFRS 9 (ECL)** de tres etapas: transforma la PD a base PIT/lifetime, estima LGD y EAD/CCF, asigna Stage 1/2/3 por SICR y evalúa `ECL = Σ_k w_k · Σ_t [ PD_marg_k(t) · LGD_k(t) · EAD_k(t) / (1+EIR)^t ]`, publicando resultados auditables por operación y agregados.

**Responsabilidad única (qué SÍ hace).**
- Consume la **term-structure lifetime PD** publicada por `survival` (SDD-18) o `markov` (SDD-19) a través del **contrato tidy hermano** (`term_structure()` CT-2), y opcionalmente la term-structure forward-looking multiescenario de `forward` (SDD-20); nunca importa internals de esos módulos.
- Aplica la **transformación PIT/TTC de Vasicek monofactorial** `PD_PIT(Z)=Φ[(Φ⁻¹(PD_TTC)−√ρ·Z)/√(1−ρ)]` cuando la curva entrante es TTC y hay factor sistémico por escenario; o consume curvas ya PIT cuando `forward` las entrega.
- Deriva **PD 12m** (suma truncada de PD marginal a 12 meses) y **PD lifetime** (horizonte completo) desde la misma term-structure.
- Estima **LGD** por los enfoques `provided` / `beta_regression` / `fractional_response` / `workout` (nunca OLS plano), con identidad `LGD = 1 − recovery`.
- Calcula **EAD/CCF** con `EAD = drawn + CCF·(límite − drawn)` y perfil de exposición por período cuando existe.
- Asigna **staging IFRS 9** (Stage 1/2/3) por SICR: gatillos cuantitativos (ratio PD lifetime vs origen, backstop PIT), downgrade por notches, cualitativos, backstops `30 dpd` (SICR) / `90 dpd` (default) y *low credit risk exemption*, con **umbrales parametrizables por cartera**.
- Ejecuta el **motor ECL marginal por período** con descuento a la **EIR** del instrumento, ponderando por escenario (`w_k`), truncando a 12m en Stage 1 y a lifetime en Stage 2/3.
- Publica artefactos namespaced bajo `"provisioning_ifrs9"`: staging, detalle de ECL por fila, term-structure de ECL (escenario × t × componente), resumen, resultado agregado y card.
- Aporta el sub-config **`IfrsProvisioningConfig`** (sección `provisioning_ifrs9` de `NikodymConfig`), computacional y por tanto incluido en el `config_hash`.
- Registra con `log_decision` la fuente de term-structure, base PIT/TTC y `rho` usados, enfoque LGD/EAD, gatillos SICR disparados por fila, pesos de escenario, convención de descuento y cualquier `FALTA-DATO`.

**Frontera dura de responsabilidad (qué NO hace, y quién lo hace).**
- **No implementa la regla del máximo B-1.** Esa regla compara estándar CMF frente a método interno
  por institución. SDD-16 sólo expone `IfrsProvisionResult`, `summary` y `card`; SDD-17 puede usarlos
  en comparativos configurables entre marcos, sin atribuirles carácter prudencial chileno.
- **No estima la term-structure lifetime PD.** SDD-18 (`survival`) y SDD-19 (`markov`) la producen; SDD-16 la consume por el contrato tidy y añade la capa económica (PIT, LGD, EAD, stage, EIR, escenario).
- **No proyecta macro ni ajusta satellite models.** SDD-20 (`forward`) mantiene la cadena `macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting`; SDD-16 es el `ecl_engine` que consume esa cadena, no la construye.
- **No ancla la PD transversal de scorecard.** SDD-10 (`calibration`) produce `calibrated_pd_frame`; SDD-16 lo consume como PD 12m base cuando la config lo declara.
- **No entrena ni calibra la scorecard F1.** SDD-08 produce `raw_pd_frame`; SDD-10 la PD calibrada; SDD-16 solo los consume como insumos declarados.
- **No define la definición de default ni la ventana de desempeño aplicables, ni el panel longitudinal por cuenta-período.** CT-3 difiere esa capa de datos; SDD-16 consume columnas económicas ya validadas y term-structures ya proyectadas.
- **No inventa `rho`, pesos de escenario, umbrales SICR ni EIR.** Si no vienen de una fuente citada (ESPEC/IFRS 9/EBA/Basel) o de config, se exige config o se marca `FALTA-DATO`.
- **No arrastra `provisioning` al núcleo.** `import nikodym.core` no importa `nikodym.provisioning`; scipy/pandas pesados se importan perezosamente dentro de `execute`/`calculate`.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Provisiones contables IFRS 9 (F4/T4). Corre después de `calibration` (PD 12m base) y después de `survival`/`markov` (term-structure lifetime); consume opcionalmente `forward` (multiescenario PIT). Su salida alimenta la orquestación `provisioning` (SDD-17).
- **Quién lo invoca:** `Study.run()` como sección `provisioning_ifrs9` de `NikodymConfig`, o API programática para calcular ECL sobre una term-structure ya disponible.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, excepciones, lineage), `data.frame` (columnas económicas: exposición, dpd, EIR, rating, garantías), `calibration.calibrated_pd_frame` (PD 12m base), y el artefacto `term_structure` del proveedor lifetime configurado (`survival`/`markov`/`forward`).

```text
data ─► ... ─► model ─► calibration ──┐
                                      │  calibrated_pd_frame (PD 12m base)
survival / markov ─► term_structure ──┤
forward ─► term_structure (PIT, k) ───┴─► provisioning_ifrs9 (SDD-16) ─► provisioning (SDD-17) ─► report/validation
                                          PD_PIT · LGD · EAD · staging · ECL         comparativo configurable
```

**Interacción con `Study` y config declarativo.** `IfrsProvisioningStep` es un `Step` nativo registrado con `@register("standard", domain="provisioning_ifrs9")`. Como el proveedor de term-structure es configurable, sus `requires` (CT-1) se construyen en `from_config`: siempre `("data","frame")`; condicionalmente `("calibration","calibrated_pd_frame")` y `(<term_structure_source>, "term_structure")`. Luego resuelve la config, transforma PD a PIT/lifetime, estima LGD/EAD, asigna stage, calcula ECL y escribe sus artefactos bajo `"provisioning_ifrs9"`. El `rng` se recibe por contrato homogéneo de `Step`; el motor v1 es determinista y debe hacer `del rng`.

**Cableado implementado en `core.study`.** El registro vigente:
- `_DOMAIN_MODULES["provisioning_ifrs9"] = "nikodym.provisioning.ifrs9"`;
- `_DOMAIN_CONFIG_CLASSES["provisioning_ifrs9"] = ("nikodym.provisioning.ifrs9.config", "IfrsProvisioningConfig")`;
- `_DEFAULT_DOMAIN_ORDER` ubica `"provisioning_ifrs9"` **después** de `"calibration"`, `"survival"`/`"markov"` y `"forward"` cuando esas secciones estén presentes, y **antes** de `"provisioning"` (SDD-17). El orden lineal no reemplaza CT-1: los prerequisitos reales se expresan por `requires`/`provides`; el scheduler topológico sigue diferido a F5.

**Paquete físico troceable.**

```text
src/nikodym/provisioning/
  __init__.py            # ya existe por SDD-15
  ifrs9/
    __init__.py
    config.py
    exceptions.py
    results.py
    base.py              # BaseEclModel (ESPEC §6.1: salida económica multi-componente)
    pd_pit.py            # Vasicek PIT/TTC + PD 12m/lifetime desde term-structure
    lgd.py               # enfoques provided/beta/fractional/workout
    ead.py               # EAD/CCF y perfil de exposición
    staging.py           # SICR / Stage 1/2/3 / backstops
    ecl.py               # motor ECL marginal, descuento EIR, ponderación de escenarios
    engine.py            # IfrsProvisioningEngine orquesta los componentes
    step.py              # IfrsProvisioningStep + @register + cableado core.study
```

**Troceo implementable un módulo/commit.**
- **B16.1 — config/exceptions:** `config.py`, `exceptions.py`, hook diferido `_PROVISIONING_IFRS9_CONFIG_CLS` en `core.config.schema`, round-trip YAML. **Mueve `GOLDEN_DEFAULT_CONFIG_HASH`** (§5).
- **B16.2 — results/base:** DTOs Pydantic frozen (`IfrsStageRecord`, `IfrsEclRecord`, `IfrsEclTermRecord`, `IfrsProvisionCard`, `IfrsProvisionResult`), `term_structure()` CT-2, `BaseEclModel`.
- **B16.3 — pd_pit:** transformador Vasicek determinista + derivación PD 12m/lifetime desde term-structure, con goldens de fórmula.
- **B16.4 — lgd:** enfoques `provided`/`beta_regression`/`fractional_response`/`workout`, identidad `LGD=1−recovery`, descuento de recuperaciones workout.
- **B16.5 — ead:** `EAD = drawn + CCF·(límite − drawn)`, perfil de exposición por período.
- **B16.6 — staging:** motor SICR con gatillos, backstops 30/90 dpd y *low credit risk exemption*.
- **B16.7 — ecl:** motor ECL marginal por período, descuento EIR, truncado 12m/lifetime por stage, ponderación de escenarios con guard anti escenario medio.
- **B16.8 — engine/step:** `IfrsProvisioningEngine`, `IfrsProvisioningStep`, `@register`, `requires`/`provides` dinámicos, cableado `core.study` e integración end-to-end.

Cada bloque cierra con ruff (regla `D` docstrings en español), mypy `--strict`, tests 100% del módulo tocado y **cobertura regulatoria 100%** para `nikodym.provisioning.ifrs9` (declarado regulatorio en `_CONTRATOS-TRANSVERSALES.md` §4).

## 3. Conceptos y fundamentos

**Fuente normativa/metodológica interna.**
- ESPECIFICACIONES §5.5 fija los cinco pilares IFRS 9 de F4: PD 12m/lifetime + PIT/TTC Vasicek, LGD bimodal, EAD/CCF, staging/SICR y motor ECL con descuento a EIR y multi-escenario. `ROADMAP.md` F4 los enumera como entregables y su DoD exige *tests de fórmula (Vasicek, ECL marginal) contra valores canónicos*.
- ESPECIFICACIONES §6.1 fija la clase base propia `BaseECLModel` (salida económica multi-componente, no un `predict` único).
- La decisión de diseño dura ESPEC §5.4/§5.5 separa CMF de IFRS 9 en **dos motores**; SDD-16 es solo el motor ECL, no la orquestación del máximo.

**Notación.**
- `t`: período discreto de proyección lifetime (unidad declarada por la term-structure: mensual/trimestral/anual).
- `k`: escenario macro; `w_k`: peso de probabilidad del escenario, `Σ_k w_k = 1`.
- `PD_marg(t)`: PD marginal del período `t` (probabilidad de default exactamente en `t`), tomada de la term-structure.
- `PD_cum(t) = 1 − S(t)`: PD acumulada; `S(t)`: supervivencia.
- `Z_k(t)`: factor sistémico del escenario `k` en `t` (índice de ciclo, `Z ~ N(0,1)`).
- `ρ`: correlación de activos (asset correlation) monofactorial.
- `LGD(t)`, `EAD(t)`, `EIR`: pérdida dado default, exposición y tasa efectiva.

**Transformación PIT Vasicek monofactorial (ESPEC §5.5).**

```text
PD_PIT_k(t) = Φ[ (Φ⁻¹(PD_TTC(t)) − √ρ · Z_k(t)) / √(1 − ρ) ]
```

Convención de orientación (verificada, ESPEC §5.5): `Z_k(t) ~ N(0,1)`, con **`Z>0` = expansión → menor PD** y **`Z<0` = recesión → mayor PD**; el signo `−√ρ·Z` implementa esa orientación. *Al portar fórmulas ASRF/Basilea —factor sistémico con signo `+` y peor caso en el cuantil superior— se invierte el signo.* Nota de corrección importante: la PD condicional evaluada en `Z=0` **no** es igual a `PD_TTC` (efecto Jensen: `Φ⁻¹(PD_TTC)/√(1−ρ) ≠ Φ⁻¹(PD_TTC)`); la PD TTC es el valor esperado `E_Z[PD_PIT_k(t)]`, no la evaluación en el centro. `Φ`/`Φ⁻¹` se calculan con `scipy.stats.norm.cdf/ppf` (import perezoso).

`PD_TTC(t)` es la PD marginal (o el hazard) de la term-structure entrante cuando esta es TTC. En v1 `ρ` viene **solo** por config escalar (por cartera); `rho_col` (correlación heterogénea por fila) se rechaza fail-fast en construcción porque el motor no la consume — su consumo real queda diferido. No hay default hardcodeado (D-IFRS-7). Si la term-structure ya es PIT (etiqueta `pd_basis="pit"` de `forward`, SDD-20 §74), `apply_vasicek` se rechaza con guard anti doble ajuste y la vía es `pit_mode="consume_pit"`.

**PD 12m vs lifetime.**

```text
PD_12m   = Σ_{t ≤ H_12m} PD_marg(t)      # H_12m = nº de períodos que cubren 12 meses (D-IFRS-11)
PD_life  = Σ_{t ≤ T_max} PD_marg(t) = PD_cum(T_max)
```

`H_12m` depende de la unidad temporal de la term-structure: mensual → 12, trimestral → 4, anual → 1. Se declara en config, no se infiere.

**LGD (ESPEC §5.5, distribución bimodal → nunca OLS plano).**
- `provided`: LGD entregada por el usuario/institución, validada en `[0,1]`.
- `beta_regression`: regresión Beta sobre `recovery`/`LGD ∈ (0,1)` en función de covariables (statsmodels `BetaModel`).
- `fractional_response`: GLM binomial con link logit (Papke–Wooldridge) sobre `LGD ∈ [0,1]`, admite masas en 0/1.
- `workout`: `LGD = 1 − PV(recuperaciones − costos)/EAD`, con flujos de recupero descontados a EIR (o tasa contractual configurada, D-IFRS-12).
- Identidad transversal `LGD = 1 − recovery` (ESPEC §5.5). Los cuatro enfoques publican LGD por fila y, si aplica, LGD por período `LGD(t)`.

**EAD / CCF (ESPEC §5.5).**

```text
EAD = drawn + CCF · (límite − drawn)
```

`CCF` viene por columna (`ccf_col`) o valor de config. El **perfil de exposición por período** `EAD(t)` proviene de una columna longitudinal (si existe) o de una regla de amortización configurada; si solo hay un `EAD` escalar, se usa constante en todos los períodos y se registra warning (CT-3: el panel longitudinal económico se difiere).

**Staging / SICR (ESPEC §5.5).** Se asigna el stage máximo (más severo) disparado por cualquiera de estos gatillos, parametrizables por cartera:
1. **Cuantitativo lifetime:** `PD_life_actual / PD_life_origen ≥ sicr_pd_ratio_threshold` (default 2.0) → Stage 2.
2. **Backstop PIT:** `PD_PIT_actual / PD_PIT_origen ≥ sicr_pd_pit_backstop_multiple` (default 3.0) → Stage 2.
3. **Downgrade por notches:** caída de rating `≥ notch_downgrade_threshold` respecto a origen → Stage 2.
4. **Cualitativo:** flag `stage_override_col` (watchlist, forbearance) → Stage 2/3 según valor.
5. **Backstop 30 dpd:** `days_past_due ≥ 30` → Stage 2 (presunción rebatible IFRS 9 5.5.11).
6. **Default 90 dpd:** `days_past_due ≥ 90` (o flag `is_default`) → Stage 3 (presunción de default IFRS 9 B5.5.37).
7. **Low credit risk exemption** (opcional, IFRS 9 5.5.10): un instrumento de bajo riesgo crediticio puede permanecer en Stage 1 aunque dispare gatillos cuantitativos. Las referencias de 30/90 dpd son **presunciones rebatibles**. Por política conservadora explícita del motor v1, los gatillos DPD prevalecen sobre la exención; esa precedencia es una decisión de Nikodym, no una irrebatibilidad prescrita por IFRS 9.

**Motor ECL (ESPEC §5.5, descuento a EIR).**

```text
ECL = Σ_k w_k · Σ_t [ PD_marg_k(t) · LGD_k(t) · EAD_k(t) / (1 + EIR)^t ]
```

- **Stage 1:** suma truncada a 12m (`t ≤ H_12m`).
- **Stage 2/3:** suma lifetime (`t ≤ T_max`).
- **Stage 3** (credit-impaired): el instrumento ya está en default; se calcula ECL lifetime con la PD ya absorbida (la term-structure concentra la masa en `t=0`), lo que económicamente tiende a `EAD·LGD` descontado. Si la institución prefiere el cálculo directo `EAD·LGD` para Stage 3, entra por config (D-IFRS-14).
- **Guard anti escenario medio:** se ponderan **outputs por escenario**, nunca inputs macro promediados (ESPEC §5.6; heredado del contrato de `forward` SDD-20 §26). Con un solo escenario, `w = 1`.
- **Convención de descuento:** `DF(t) = (1 + EIR)^{−τ(t)}` con `τ(t)` el tiempo en años derivado de `time_value`/unidad temporal; la convención exacta (EIR anual + fracción de año vs EIR por período) se fija en config (D-IFRS-9).

**Interfaz abstracta a la term-structure lifetime.** SDD-16 lee el artefacto `(<source>, "term_structure")` (o `result.term_structure()`), un `DataFrame` tidy con las columnas compartidas por SDD-18 y SDD-19: `[row_id?, segment?, partition?, period, time_value, hazard, survival, pd_marginal, pd_cumulative, method, pd_source, scenario, warning_codes]`. SDD-16 **valida** ese contrato y opera de forma agnóstica al método (KM/Cox/AFT/discrete-hazard/cohort/duration/Aalen-Johansen). No importa `nikodym.survival` ni `nikodym.markov`; el acoplamiento es solo el shape tidy (CT-2). `forward` (SDD-20) publica el mismo shape ya multiescenario y PIT-etiquetado, poblando la columna `scenario`.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/provisioning/ifrs9/config.py
class IfrsPdConfig(NikodymBaseConfig): ...
class IfrsLgdConfig(NikodymBaseConfig): ...
class IfrsEadConfig(NikodymBaseConfig): ...
class IfrsStagingConfig(NikodymBaseConfig): ...
class IfrsScenarioConfig(NikodymBaseConfig): ...
class IfrsEclConfig(NikodymBaseConfig): ...
class IfrsProvisioningConfig(NikodymBaseConfig): ...

# nikodym/provisioning/ifrs9/exceptions.py
class IfrsProvisioningError(NikodymError): ...
class IfrsConfigError(IfrsProvisioningError): ...
class IfrsInputError(IfrsProvisioningError): ...
class IfrsTermStructureError(IfrsInputError): ...   # contrato tidy incumplido
class IfrsPdError(IfrsProvisioningError): ...        # Vasicek/PIT/lifetime
class IfrsLgdError(IfrsProvisioningError): ...
class IfrsEadError(IfrsProvisioningError): ...
class IfrsStagingError(IfrsProvisioningError): ...
class IfrsEclError(IfrsProvisioningError): ...
```

```python
# nikodym/provisioning/ifrs9/base.py
@runtime_checkable
class BaseEclModel(Protocol):
    """Contrato mínimo del motor económico ECL Nikodym (ESPEC §6.1)."""
    config_cls: ClassVar[type["IfrsProvisioningConfig"]]
    @classmethod
    def from_config(cls, cfg: "IfrsProvisioningConfig") -> "Self": ...
    def calculate(
        self,
        frame: "pandas.DataFrame",
        *,
        term_structure: "pandas.DataFrame",
        calibrated_pd: "pandas.DataFrame | None" = None,
        as_of_date: str,
        audit: "AuditSink | None" = None,
    ) -> "IfrsProvisionResult": ...
```

```python
# nikodym/provisioning/ifrs9/results.py
class IfrsStageRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    row_id: str
    stage: Literal[1, 2, 3]
    days_past_due: int | None
    pd_life_current: float | None
    pd_life_origination: float | None
    sicr_triggers: tuple[str, ...] = ()          # gatillos disparados
    low_credit_risk_exempt: bool = False
    warnings: tuple[str, ...] = ()

class IfrsEclRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    row_id: str
    stage: Literal[1, 2, 3]
    ead: float
    lgd: float
    eir: float
    ecl_12m: float
    ecl_lifetime: float
    ecl_reported: float                          # 12m si Stage 1, lifetime si Stage 2/3
    scenario_weights: dict[str, float]
    pd_basis: Literal["pit", "ttc", "mixed"]
    warnings: tuple[str, ...] = ()

class IfrsEclTermRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    row_id: str
    scenario: str
    period: int
    time_value: float
    pd_marginal: float
    lgd: float
    ead: float
    discount_factor: float
    ecl_marginal: float                          # PD_marg·LGD·EAD·DF
    warnings: tuple[str, ...] = ()

class IfrsProvisionCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    as_of_date: str
    term_structure_source: str
    pit_mode: str
    n_rows: int
    n_stage1: int
    n_stage2: int
    n_stage3: int
    total_ead: float
    total_ecl_reported: float
    scenarios: tuple[str, ...]
    scenario_weights: dict[str, float]
    dependency_versions: dict[str, str]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)   # CT-2

class IfrsProvisionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    staging: "pandas.DataFrame"
    detail: "pandas.DataFrame"
    ecl_term_structure: "pandas.DataFrame"
    summary: "pandas.DataFrame"
    stage_records: tuple[IfrsStageRecord, ...]
    ecl_records: tuple[IfrsEclRecord, ...]
    card: IfrsProvisionCard
    def term_structure(self) -> "pandas.DataFrame | None": ...
```

`term_structure()` cumple CT-2: retorna el `DataFrame` tidy de ECL (`[row_id, scenario, period, time_value, component, value]` en forma larga, o el `ecl_term_structure` por período/escenario) para que SDD-17 y `report` lo consuman; nunca es `None` para IFRS 9 (a diferencia de CMF agregado, que retorna `None`).

```python
# nikodym/provisioning/ifrs9/pd_pit.py
def vasicek_pit(pd_ttc: "numpy.ndarray", *, rho: float, z: "numpy.ndarray") -> "numpy.ndarray": ...
def marginal_to_horizon(term_structure: "pandas.DataFrame", *, horizon_periods: int) -> "pandas.DataFrame": ...

# nikodym/provisioning/ifrs9/lgd.py
class LgdEngine:
    @classmethod
    def from_config(cls, cfg: IfrsLgdConfig) -> "LgdEngine": ...
    def estimate(self, frame: "pandas.DataFrame", *, eir: "pandas.Series | None" = None) -> "pandas.DataFrame": ...

# nikodym/provisioning/ifrs9/ead.py
class EadEngine:
    @classmethod
    def from_config(cls, cfg: IfrsEadConfig) -> "EadEngine": ...
    def estimate(self, frame: "pandas.DataFrame", *, periods: "Sequence[int]") -> "pandas.DataFrame": ...

# nikodym/provisioning/ifrs9/staging.py
class StagingEngine:
    @classmethod
    def from_config(cls, cfg: IfrsStagingConfig) -> "StagingEngine": ...
    def assign(self, frame: "pandas.DataFrame", *, pd_life: "pandas.Series", pd_pit: "pandas.Series") -> "pandas.DataFrame": ...

# nikodym/provisioning/ifrs9/ecl.py
class EclEngine:
    @classmethod
    def from_config(cls, cfg: IfrsEclConfig) -> "EclEngine": ...
    def compute(
        self,
        *,
        pd_marginal_by_scenario: "pandas.DataFrame",
        lgd: "pandas.DataFrame",
        ead: "pandas.DataFrame",
        eir: "pandas.Series",
        stages: "pandas.Series",
        weights: "Mapping[str, float]",
    ) -> "IfrsProvisionResult": ...
```

```python
# nikodym/provisioning/ifrs9/engine.py
class IfrsProvisioningEngine:
    config_cls: ClassVar[type[IfrsProvisioningConfig]] = IfrsProvisioningConfig
    def __init__(self, config: IfrsProvisioningConfig) -> None: ...
    @classmethod
    def from_config(cls, cfg: IfrsProvisioningConfig) -> "IfrsProvisioningEngine": ...
    def calculate(
        self,
        frame: "pandas.DataFrame",
        *,
        term_structure: "pandas.DataFrame",
        calibrated_pd: "pandas.DataFrame | None" = None,
        as_of_date: str,
        audit: "AuditSink | None" = None,
    ) -> IfrsProvisionResult: ...
```

```python
# nikodym/provisioning/ifrs9/step.py
@register("standard", domain="provisioning_ifrs9")
class IfrsProvisioningStep(AuditableMixin):
    name: str = "provisioning_ifrs9"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "frame"),
    )   # las claves condicionales se agregan en from_config según config
    provides: tuple[ArtifactKey, ...] = (
        ("provisioning_ifrs9", "staging"),
        ("provisioning_ifrs9", "detail"),
        ("provisioning_ifrs9", "ecl_term_structure"),
        ("provisioning_ifrs9", "summary"),
        ("provisioning_ifrs9", "result"),
        ("provisioning_ifrs9", "card"),
    )
    @classmethod
    def from_config(cls, cfg: IfrsProvisioningConfig) -> "IfrsProvisioningStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "IfrsProvisionResult": ...
```

**`requires` dinámicos (CT-1, patrón SDD-20 §81).** `from_config` añade a `requires`:
- `("calibration", "calibrated_pd_frame")` si `cfg.pd.base_pd_source == "calibration"`;
- `(cfg.pd.term_structure_source, "term_structure")` con `term_structure_source ∈ {"survival","markov","forward"}`.

La validación pre-run del motor v1 exige que cada `requires` esté presente en el `ArtifactStore`; su ausencia es `ArtifactNotFoundError` con el contrato incumplido antes de correr.

**Artefactos que `IfrsProvisioningStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"staging"` | `pandas.DataFrame` | una fila por operación: stage, dpd, gatillos SICR, PD lifetime actual/origen |
| `"detail"` | `pandas.DataFrame` | ECL por fila: EAD, LGD, EIR, ECL 12m/lifetime/reportado, pesos de escenario |
| `"ecl_term_structure"` | `pandas.DataFrame` | ECL marginal por `row_id × scenario × period` con factor de descuento |
| `"summary"` | `pandas.DataFrame` | agregados por stage/cartera/escenario |
| `"result"` | `IfrsProvisionResult` | contenedor agregado |
| `"card"` | `IfrsProvisionCard` | resumen para governance/report/orquestación (SDD-17) |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning", "selection", "model", "calibration",
                 "survival", "forward", "provisioning_ifrs9"])
ecl = study.artifacts.get("provisioning_ifrs9", "result")
staging = study.artifacts.get("provisioning_ifrs9", "staging")
ecl_curve = ecl.term_structure()

# Cadena standalone (SDD-18, survival con pd_source="none" y covariables propias):
# el área IFRS 9 no depende del scorecard de originación.
study.run(steps=["data", "survival", "provisioning_ifrs9"])
```

## 5. Configuración (schema Pydantic)

`IfrsProvisioningConfig` es el sub-config de la sección `provisioning_ifrs9` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, campos con `title`/`description`, rangos `ge/le`, `Literal` en categóricos y metadatos `ui_*`. **No es infraestructura** (`provisioning_ifrs9 ∉ INFRA_SECTIONS`; verificado contra `core/config/hashing.py`: `INFRA_SECTIONS = {"name","governance","audit","tracking","report"}`): cambiar fuente de term-structure, `rho`, enfoque LGD/EAD, umbrales SICR, pesos de escenario o convención de descuento **cambia el `config_hash`**. Al cablear B16.1 se **moverá `GOLDEN_DEFAULT_CONFIG_HASH`** (mismo precedente que `provisioning_cmf`, `survival` y `markov`); el implementador debe barrer el literal en tests y repros, no tratarlo como regresión inesperada.

```python
class IfrsPdConfig(NikodymBaseConfig):
    term_structure_source: Literal["survival", "markov", "forward"] = Field(
        "survival", title="Proveedor de term-structure lifetime")
    base_pd_source: Literal["calibration", "term_structure"] = Field(
        "term_structure", title="Fuente de PD 12m base")
    pit_mode: Literal["consume_pit", "apply_vasicek", "ttc_only"] = Field(
        "consume_pit", title="Cómo obtener PD PIT")
    rho: float | None = Field(default=None, ge=0.0, lt=1.0, title="Correlación de activos monofactorial")
    rho_col: str | None = Field(default=None, title="Columna de rho por fila (override)")  # rechazada fail-fast en v1 (no consumida; diferida)
    systemic_factor_col: str | None = Field(default=None, title="Columna Z por escenario/período")
    horizon_12m_periods: int = Field(default=12, ge=1, title="Períodos que cubren 12 meses")
    max_lifetime_periods: int | None = Field(default=None, ge=1, title="Tope de horizonte lifetime")

class IfrsLgdConfig(NikodymBaseConfig):
    method: Literal["provided", "beta_regression", "fractional_response", "workout"] = Field(
        "provided", title="Enfoque LGD")
    lgd_col: str = Field("lgd", title="Columna LGD (provided)")
    recovery_col: str | None = Field(default=None, title="Columna recovery (workout/identidad)")
    lgd_floor: float = Field(default=0.0, ge=0.0, le=1.0, title="Piso LGD")
    lgd_cap: float = Field(default=1.0, ge=0.0, le=1.0, title="Techo LGD")
    covariate_cols: tuple[str, ...] = Field(default=(), title="Covariables para beta/fractional")
    workout_discount: Literal["eir", "contractual"] = Field(default="eir", title="Descuento de recuperos workout")

class IfrsEadConfig(NikodymBaseConfig):
    method: Literal["provided", "ccf"] = Field("ccf", title="Enfoque EAD")
    ead_col: str = Field("ead", title="Columna EAD (provided)")
    drawn_col: str = Field("drawn", title="Saldo dispuesto")
    limit_col: str = Field("credit_limit", title="Límite")
    ccf_col: str | None = Field(default=None, title="Columna CCF por fila")
    ccf_value: float | None = Field(default=None, ge=0.0, le=1.0, title="CCF único de config")
    exposure_profile_col: str | None = Field(default=None, title="Perfil EAD(t) longitudinal")

class IfrsStagingConfig(NikodymBaseConfig):
    sicr_pd_ratio_threshold: float = Field(default=2.0, gt=1.0, title="Ratio PD lifetime actual/origen")
    sicr_pd_pit_backstop_multiple: float = Field(default=3.0, gt=1.0, title="Backstop PIT")
    dpd_sicr_backstop: int = Field(default=30, ge=0, title="Backstop dpd Stage 2")
    dpd_default_backstop: int = Field(default=90, ge=0, title="Backstop dpd Stage 3")
    days_past_due_col: str = Field("days_past_due", title="Días de mora")
    is_default_col: str | None = Field(default="is_default", title="Flag de default")
    origination_pd_life_col: str | None = Field(default=None, title="PD lifetime en origen")
    rating_col: str | None = Field(default=None, title="Rating actual")
    origination_rating_col: str | None = Field(default=None, title="Rating en origen")
    notch_downgrade_threshold: int | None = Field(default=None, ge=1, title="Downgrade por notches")
    stage_override_col: str | None = Field(default=None, title="Override cualitativo de stage")
    low_credit_risk_exemption: bool = Field(default=False, title="Aplicar exención de bajo riesgo crediticio")
    low_credit_risk_col: str | None = Field(default=None, title="Flag de bajo riesgo crediticio")

class IfrsScenarioConfig(NikodymBaseConfig):
    source: Literal["forward", "config", "single"] = Field("forward", title="Fuente de escenarios/pesos")
    weights: dict[str, float] = Field(default_factory=dict, title="Pesos por escenario (source='config')")
    forbid_mean_scenario: bool = Field(default=True, title="Prohibir promediar inputs macro")

class IfrsEclConfig(NikodymBaseConfig):
    eir_col: str = Field("eir", title="Tasa efectiva por instrumento")
    discount_convention: Literal["annual_eir_year_fraction", "period_eir"] = Field(
        "annual_eir_year_fraction", title="Convención de descuento")
    stage3_direct: bool = Field(default=False, title="Stage 3 como EAD·LGD directo")
    rounding: Literal["none", "currency_2dp", "integer_currency"] = Field("none", title="Redondeo de ECL")

class IfrsProvisioningConfig(NikodymBaseConfig):
    schema_version: str = "1.0.0"
    type: Literal["standard"] = "standard"
    as_of_date_col: str = Field("as_of_date", title="Fecha de cálculo")
    row_id_col: str | None = Field(default=None, title="Identificador de operación")
    portfolio_col: str = Field("portfolio", title="Cartera")
    pd: IfrsPdConfig = Field(default_factory=IfrsPdConfig, title="PD 12m/lifetime + PIT")
    lgd: IfrsLgdConfig = Field(default_factory=IfrsLgdConfig, title="LGD")
    ead: IfrsEadConfig = Field(default_factory=IfrsEadConfig, title="EAD/CCF")
    staging: IfrsStagingConfig = Field(default_factory=IfrsStagingConfig, title="Staging/SICR")
    scenarios: IfrsScenarioConfig = Field(default_factory=IfrsScenarioConfig, title="Escenarios")
    ecl: IfrsEclConfig = Field(default_factory=IfrsEclConfig, title="Motor ECL")
    fail_on_falta_dato: bool = Field(default=True, title="Fallar ante brechas críticas de dato")
```

**Validaciones de config.**
- `rho_col` informada levanta `IfrsConfigError` en la construcción de `IfrsPdConfig` (guard fail-fast, mismo criterio que `exposure_profile_col`): el motor v1 no la consume y honrarla en silencio con el `rho` escalar sería una degradación con etiqueta falsa. El campo se conserva por compatibilidad de schema/UI; su consumo real queda diferido post-P0.
- `pit_mode="apply_vasicek"` con `fail_on_falta_dato=True` exige en construcción `rho` escalar **y** `systemic_factor_col` explícita, sin exención por `scenarios.source="forward"`: `forward` no publica un factor sistémico `Z` (sus curvas ya son PIT), así que el `Z` implícito que el validador previo presuponía no existe; el mensaje dirige a `pit_mode="consume_pit"`. Con `fail_on_falta_dato=False` el config construye igual, pero el motor levanta `IfrsConfigError` en runtime: **no existe ruta FALTA-DATO degradada para `rho`/`Z`** (comportamiento fijado por tests).
- `pit_mode="consume_pit"` exige que la term-structure entrante traiga `pd_basis="pit"` (de `forward`); si es TTC, `IfrsConfigError`. Espejo inverso: `pit_mode="apply_vasicek"` rechaza una term-structure etiquetada con `pd_basis` distinto de todo-`ttc` (guard anti doble ajuste macro; columna ausente, como en survival/markov, sigue permitida).
- `scenarios.forbid_mean_scenario=True` veta los nombres reservados `mean`/`average`/`weighted_mean_input` (case-insensitive) tanto en `weights` (`source="config"`, en construcción) como en la term-structure entrante (guard del motor en `_resolve_weights`, cubre las tres fuentes); `forbid_mean_scenario=False` es el escape hatch consciente y auditado.
- `staging.sicr_pd_ratio_threshold` y `sicr_pd_pit_backstop_multiple` deben ser `> 1`; el ratio lifetime exige `origination_pd_life_col`, salvo que solo se usen backstops dpd.
- `staging.notch_downgrade_threshold` exige `rating_col` y `origination_rating_col`.
- `ead.method="ccf"` exige `drawn_col`, `limit_col` y exactamente uno de `ccf_col`/`ccf_value`.
- `lgd.method="workout"` exige `recovery_col` (o flujos configurados) y `eir` para descontar.
- `lgd.method ∈ {"beta_regression","fractional_response"}` exige `covariate_cols` no vacías y statsmodels.
- `scenarios.source="config"` exige `weights` con `Σ = 1` (dentro de tolerancia) y todos `> 0`; `source="single"` fija `w = 1`.
- `dpd_default_backstop ≥ dpd_sicr_backstop`.

**Defaults defendibles (con fuente).**
- `term_structure_source="survival"`: ESPEC §5.6 llama a survival discrete-time la **ruta estándar IFRS 9 lifetime**; `markov`/`forward` quedan opt-in.
- `base_pd_source="term_structure"`: la PD 12m se deriva de la misma curva lifetime (consistencia); `calibration` como alternativa cuando se ancla la PD 12m transversal.
- `pit_mode="consume_pit"`: si `forward` (SDD-20) ya entregó curvas PIT multiescenario, SDD-16 no re-aplica Vasicek; evita doble ajuste macro.
- `sicr_pd_ratio_threshold=2.0`, `sicr_pd_pit_backstop_multiple=3.0`: valores citados por ESPEC §5.5 (ratio lifetime `≥2×`, backstop PIT `≥3×`); **parametrizables por cartera** — deben calibrarse por la institución (D-IFRS-3).
- `dpd_sicr_backstop=30`, `dpd_default_backstop=90`: presunciones rebatibles IFRS 9 (5.5.11 / B5.5.37); la prioridad sobre la exención es política conservadora v1 de Nikodym.
- `low_credit_risk_exemption=False`: la exención IFRS 9 5.5.10 es opt-in porque su uso es criterio de la entidad.
- `scenarios.source="forward"`: los escenarios y pesos los define `forward`/la institución (D-IFRS-5, R0); nunca hardcodeados.
- `rho=None`: sin default hardcodeado; `rho` es un parámetro metodológico/model risk. Las correlaciones Basel para capital no se trasladan automáticamente a ECL contable.
- `discount_convention="annual_eir_year_fraction"`: EIR anual descontada por fracción de año, convención contable usual; `rounding="none"` publica el ECL económico exacto.

**Hook implementado en `core.config.schema`.** El cableado vigente:
- declarar `_PROVISIONING_IFRS9_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir campo `provisioning_ifrs9` como `Any` en runtime y `IfrsProvisioningConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("provisioning_ifrs9", mode="before")` (`_valida_provisioning_ifrs9`) que valida con `IfrsProvisioningConfig` si el hook está poblado, o exige JSON canónico determinista si no;
- `nikodym.provisioning.ifrs9.__init__` puebla el hook y registra `IfrsProvisioningStep`;
- `provisioning_ifrs9` **no** entra a `INFRA_SECTIONS`.

## 6. Contratos de datos (I/O)

**Inputs de `IfrsProvisioningStep` vía `Study`.**

| dominio | clave | obligatoriedad | uso |
|---|---|---|---|
| `data` | `"frame"` | duro (`requires`) | columnas económicas: exposición/drawn/límite, dpd, EIR, rating, LGD/recovery, garantías, `is_default` |
| `<source>` | `"term_structure"` | duro dinámico | term-structure tidy lifetime PD (survival/markov/forward), contrato §3 |
| `calibration` | `"calibrated_pd_frame"` | condicional (`base_pd_source="calibration"`) | PD 12m anclada por SDD-10, columna `pd_calibrated` |

**Contrato de la term-structure entrante.** `DataFrame` tidy con las columnas hermanas de SDD-18/19: `period` (entero ≥1), `time_value` (float), `pd_marginal` (∈[0,1]), `pd_cumulative`, `survival`, `hazard?`, `method`, `pd_source`, `scenario` (`None` en base; poblado por `forward`), `warning_codes`, e identificador (`row_id` o `segment`). Invariantes verificadas antes de calcular: `pd_cumulative = 1 − survival`, `Σ_t pd_marginal ≈ pd_cumulative(T_max)`, sin `NaN`/`inf`. Incumplimiento → `IfrsTermStructureError`.

**Columnas mínimas de `data.frame` por función.**

| función | columnas requeridas principales |
|---|---|
| EAD (`ccf`) | `drawn`, `credit_limit`, y `ccf_col` o `ccf_value`; opcional `exposure_profile` |
| EAD (`provided`) | `ead` |
| LGD (`provided`) | `lgd ∈ [0,1]` |
| LGD (`workout`) | `recovery` o flujos de recupero + costos; `eir` para descontar |
| LGD (`beta`/`fractional`) | `covariate_cols` y objetivo `lgd`/`recovery` en Desarrollo |
| Staging | `days_past_due`, `is_default?`; `origination_pd_life?`, `rating?`/`origination_rating?`, `stage_override?` según gatillos activos |
| ECL | `eir` por instrumento |
| PIT (`apply_vasicek`) | `rho` escalar por config y `systemic_factor` (Z) explícita por escenario/período en la term-structure; la term-structure debe ser TTC (guard anti doble ajuste). `rho_col` diferida (rechazada en config) |

**Output `staging`.** Una fila por operación: `row_id`, `portfolio`, `stage`, `days_past_due`, `pd_life_current`, `pd_life_origination`, `sicr_triggers`, `low_credit_risk_exempt`, `warning_codes`.

**Output `detail`.** Una fila por operación: `row_id`, `portfolio`, `stage`, `ead`, `lgd`, `eir`, `pd_12m`, `pd_life`, `ecl_12m`, `ecl_lifetime`, `ecl_reported`, `scenario_weights` (serializado), `pd_basis`, `warning_codes`.

**Output `ecl_term_structure`.** Larga por `row_id × scenario × period`: `time_value`, `pd_marginal`, `lgd`, `ead`, `discount_factor`, `ecl_marginal`. Es la evidencia auditable de la suma ECL y la fuente de `IfrsProvisionResult.term_structure()`.

**Output `summary`.** Agregado por `portfolio × stage` (y `scenario` cuando aplica): `n_rows`, `total_ead`, `total_ecl_reported`, `coverage_ratio = total_ecl_reported / total_ead`, `warning_codes`.

**Interfaz hacia SDD-17.** SDD-16 garantiza: (a) `IfrsProvisionResult.summary`/`card` con
`total_ecl_reported` por cartera; (b) `term_structure()` no nula con el desglose por
escenario/período; y (c) claves `provides` estables. SDD-17 puede usar el resultado en un comparativo
configurable entre marcos. La regla normativa B-1 se aplica entre método estándar CMF y método
interno por institución; IFRS 9 no es uno de sus operandos.

**Invariantes.**
- *No mutación:* no modifica `data.frame`, `calibrated_pd_frame` ni la term-structure de survival/markov/forward; usa copias defensivas.
- *Rango:* `LGD ∈ [floor, cap] ⊆ [0,1]`, `EAD ≥ 0`, `PD_PIT ∈ [0,1]`, `ECL ≥ 0`, `discount_factor ∈ (0,1]`.
- *Consistencia stage/horizonte:* `ecl_reported = ecl_12m` sii `stage == 1`; `= ecl_lifetime` sii `stage ∈ {2,3}`.
- *Ponderación:* `ECL_reportado = Σ_k w_k · ECL_k`; con un escenario, `w = 1`; nunca se promedian inputs macro.
- *Trazabilidad:* cada fila referencia fuente de term-structure, `pit_mode`, gatillos SICR y escenarios.
- *Orden estable:* `detail`/`staging` preservan el orden de `data.frame`; `summary` se ordena por orden canónico de cartera/stage.
- *Finitud:* no se publican `NaN`/`inf`/`-inf`; `-0.0` se normaliza a `0.0`.

## 7. Algoritmos y flujo

**`IfrsProvisioningStep.execute(study, rng)` — secuencia canónica.**
1. **Descartar azar.** `del rng`; el motor IFRS 9 v1 es determinista.
2. **Leer config.** Resolver `study.config.provisioning_ifrs9` o `IfrsProvisioningConfig()` en invocación programática.
3. **Validar prerequisitos CT-1.** Exigir `data.frame`, la term-structure del `term_structure_source` configurado y, si `base_pd_source="calibration"`, `calibration.calibrated_pd_frame`.
4. **Copias defensivas.** Copiar frame, term-structure y PD calibrada; validar índices únicos y alineables.
5. **Validar contrato term-structure.** Verificar columnas/invariantes tidy (§6); `IfrsTermStructureError` si falla.
6. **Resolver PD PIT.** Según `pit_mode`: `consume_pit` (usar curvas PIT de `forward`), `apply_vasicek` (transformar TTC con `rho` y `Z_k(t)`), `ttc_only` (usar TTC sin ajuste, solo diagnóstico).
7. **Derivar PD 12m/lifetime.** `PD_12m = Σ_{t≤H_12m} PD_marg`; `PD_life = PD_cum(T_max)` por fila/segmento y escenario.
8. **Estimar LGD.** `LgdEngine.estimate` según enfoque; aplicar floor/cap; `LGD(t)` si el enfoque lo produce.
9. **Estimar EAD.** `EadEngine.estimate`: `EAD = drawn + CCF·(límite − drawn)` o `EAD` provisto; perfil `EAD(t)` si existe, constante con warning si no.
10. **Asignar staging.** `StagingEngine.assign`: evaluar gatillos 1–7 (§3); stage = máximo disparado; por política conservadora v1, DPD/default prevalecen sobre la exención de bajo riesgo.
11. **Calcular ECL marginal.** Para cada fila/escenario/período: `ecl_marginal = PD_marg_k(t)·LGD_k(t)·EAD_k(t)·DF(t)`; sumar truncado a `H_12m` (Stage 1) o lifetime (Stage 2/3).
12. **Ponderar escenarios.** `ECL_reportado = Σ_k w_k · ECL_k`; guard anti escenario medio bloqueante (`IfrsConfigError` ante nombres reservados, antes del branch por fuente).
13. **Construir DTOs.** `IfrsStageRecord`, `IfrsEclRecord`, `IfrsEclTermRecord`, `IfrsProvisionCard`, `IfrsProvisionResult`; poblar `metric_sections` CT-2.
14. **Auditar decisiones.** Fuente term-structure, `pit_mode`/`rho`, enfoque LGD/EAD, gatillos SICR por fila, pesos de escenario, convención de descuento, redondeo, `FALTA-DATO`.
15. **Publicar artefactos.** Escribir las seis claves `provides` bajo `"provisioning_ifrs9"`.

**`vasicek_pit(pd_ttc, rho, z)` — detalle.**
1. Importar `scipy.stats.norm` de forma perezosa.
2. `x = norm.ppf(clip(pd_ttc, ε, 1−ε))` con `ε` mínimo para evitar `±inf` en 0/1.
3. `pd_pit = norm.cdf((x − sqrt(rho)·z) / sqrt(1 − rho))`.
4. Validar `pd_pit ∈ [0,1]`; normalizar `-0.0 → 0.0`; nunca clipear silenciosamente valores fuera de tolerancia (levantar `IfrsPdError`).

**`EclEngine.compute(...)` — detalle.**
1. Para cada escenario `k` con peso `w_k`, alinear `PD_marg_k(t)`, `LGD_k(t)`, `EAD_k(t)` por `row_id × period`.
2. `DF(t) = (1+EIR)^{−τ(t)}` según convención; `τ(t)` en años desde `time_value`.
3. `ECL_k(row) = Σ_{t≤H(stage)} PD_marg_k(t)·LGD_k(t)·EAD_k(t)·DF(t)` con `H(1)=H_12m`, `H(2)=H(3)=T_max`.
4. `ECL_reportado(row) = Σ_k w_k · ECL_k(row)`.
5. Publicar `ecl_12m`, `ecl_lifetime`, `ecl_reported`; para Stage 3 con `stage3_direct=True`, `ECL = EAD·LGD·DF(0)`.

**Alternativas descartadas.**
- *Un solo "motor ECL" que incluya CMF:* descartado; ESPEC §5.4/§5.5 exige dos motores separados y el máximo en SDD-17.
- *OLS plano para LGD:* descartado; ESPEC §5.5 exige beta/fractional/workout por bimodalidad.
- *Promediar factores macro (escenario medio):* descartado; la PD es no-lineal en macro (ESPEC §5.6); se ponderan outputs.
- *Aplicar Vasicek sobre curvas ya PIT de `forward`:* descartado y **bloqueado por guard del motor** (`IfrsConfigError` si la term-structure declara `pd_basis` distinto de todo-`ttc`); `pit_mode="consume_pit"` es la vía para curvas PIT.
- *Importar internals de survival/markov:* descartado; acoplamiento solo por el contrato tidy CT-2.
- *`df.eval`/`eval` para reglas de staging o satellite:* descartado; gatillos como comparaciones tipadas, coeficientes explícitos.

**Complejidad / rendimiento.** El costo dominante es la suma ECL `O(n · T · K)` (filas × períodos × escenarios). El horizonte lifetime `T` y el número de escenarios `K` deben validarse antes de materializar `ecl_term_structure`; para volumen alto se vectoriza por período/escenario manteniendo resultados bit-idénticos contra el motor de referencia fila-a-fila.

## 8. Casos borde y manejo de errores

- **Falta `data.frame` o la term-structure configurada:** `ArtifactNotFoundError` por CT-1 antes de `execute`.
- **`base_pd_source="calibration"` sin `calibrated_pd_frame`:** `ArtifactNotFoundError` o `IfrsConfigError` citando `base_pd_source`.
- **Term-structure con columnas faltantes o invariantes rotas:** `IfrsTermStructureError` listando la columna/regla y la primera fila afectada.
- **`pit_mode="apply_vasicek"` sin `rho` o sin `Z`:** `IfrsConfigError` siempre — en construcción con `fail_on_falta_dato=True`, o en runtime si se difirió con `False`; no existe ruta FALTA-DATO degradada para `rho`/`Z` (FALTA-DATO-IFRS-1 documenta el requisito, no una degradación).
- **`pit_mode="apply_vasicek"` con term-structure etiquetada `pd_basis="pit"` (o mixta/faltante en la columna presente):** `IfrsConfigError` — guard anti doble ajuste macro; columna ausente (survival/markov) o toda `"ttc"` permitida.
- **`pit_mode="consume_pit"` con term-structure TTC:** `IfrsConfigError` (no se re-etiqueta una curva TTC como PIT).
- **Escenario con nombre reservado (`mean`/`average`/`weighted_mean_input`, case-insensitive) y guard activo:** `IfrsConfigError` en las tres fuentes (`single`/`config`/`forward`); `forbid_mean_scenario=False` calcula y la decisión queda auditada.
- **Term-structure `forward` con `scenario_weight=0`:** `IfrsEclError` («estrictamente positivo») dentro de `EclEngine`, tras staging — fallo tardío fijado por tests como límite explícito de la frontera SDD-20→SDD-16. La vía soportada es excluir aguas arriba el escenario peso-0 (ECL idéntica: contribución nula); los DTO de `results` también rechazan `w=0`, así que la resolución de fondo (aceptar peso 0 vs fail-fast temprano) toca tres guards y queda como decisión de política pendiente.
- **Term-structure entrante con columna `lgd` no nula:** el motor v1 la ignora — la LGD sale de `IfrsLgdConfig` — y lo declara con `FALTA-DATO-IFRS-6` en `warning_codes` por fila y `card.falta_dato`; la columna toda-nula (forward sin satellite LGD) no emite el aviso. `lgd_base` (linaje de la LGD base de entrada, sin condicionamiento macro) queda fuera del aviso por diseño: no hay información forward-looking perdida.
- **`rho` fuera de `[0,1)`:** `IfrsConfigError`.
- **PD marginal fuera de `[0,1]` o `PD_PIT` no finita:** `IfrsPdError`; no se clipea fuera de tolerancia.
- **LGD fuera de `[0,1]` tras floor/cap:** `IfrsLgdError`.
- **Workout sin `recovery` ni flujos:** `IfrsLgdError`; no estima recuperación.
- **EAD negativa (`drawn > límite` con CCF que la vuelve negativa):** `IfrsEadError` salvo config que lo permita explícitamente.
- **`credit_limit < drawn`:** warning y `CCF·(límite−drawn)` puede ser negativo; por default se acota a `EAD ≥ drawn` (D-IFRS-13) o se levanta `IfrsEadError`.
- **Ratio SICR sin `origination_pd_life_col`:** `IfrsStagingError` si el gatillo lifetime está activo; los backstops dpd siguen operando.
- **`days_past_due` negativo o no entero:** `IfrsInputError`.
- **Pesos de escenario que no suman 1 (`source="config"`):** `IfrsConfigError`.
- **EIR faltante o negativa que produce `DF` no finito:** `IfrsEclError`.
- **Horizonte `H_12m > T_max`:** warning; PD 12m usa todo el soporte disponible y se registra `FALTA-DATO-IFRS-2`.
- **`scipy` faltante para Vasicek/beta:** `MissingDependencyError("instale nikodym[...]")` en español.
- **Índice duplicado o unión ambigua term-structure/frame:** `IfrsInputError`.

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen cartera, fila, escenario/período, regla y valor observado cuando aplique.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno en v1. `IfrsProvisioningStep.execute(study, rng)` recibe `rng` por contrato y debe hacer `del rng`. (El ajuste beta/fractional de LGD es un GLM determinista dado el solver; se ancla el solver y se registran diagnósticos.)
- **Determinismo esperado.** `(data_hash + config_hash + term_structure hasheable + calibrated_pd si aplica + uv.lock) → staging, detail, ecl_term_structure, summary, card idénticos; term_structure() no nula`.
- **Orden estable.** Salidas ordenadas por orden de entrada y período/escenario ascendente; ningún set/dict sin orden determina el output.
- **Normalización numérica.** `-0.0 → 0.0`; no usar `hash()` builtin; si se hashea un frame, usar `pandas.util.hash_pandas_object` con endian explícito `.astype("<u8")`; nunca bytes de parquet.
- **Audit trail (`log_decision`).** Registrar como mínimo:
  - `ifrs9_term_structure_source`: proveedor, método, columnas, cobertura;
  - `ifrs9_pit`: `pit_mode`, `rho`/`rho_col`, fuente de `Z`, orientación Vasicek;
  - `ifrs9_pd_horizon`: `H_12m`, `T_max`, unidad temporal, `FALTA-DATO` de horizonte;
  - `ifrs9_lgd`: enfoque, floor/cap, descuento workout, diagnósticos de ajuste y `lgd_forward_presente` (descarte FALTA-DATO-IFRS-6);
  - `ifrs9_ead`: método, CCF usado, perfil de exposición o constancia con warning;
  - `ifrs9_staging`: gatillos SICR disparados por conteo, backstops, exención de bajo riesgo;
  - `ifrs9_scenarios`: fuente, pesos, guard anti escenario medio;
  - `ifrs9_ecl`: convención de descuento, redondeo, totales por stage/cartera.
- **Model card / report.** `IfrsProvisionCard` expone totales de ECL/EAD, conteo por stage, escenarios/pesos, fuente de term-structure, `pit_mode` y `falta_dato`. `metric_sections` (CT-2) puede incluir `"staging_migration"`, `"ecl_by_scenario"`, `"term_structure_summary"` sin romper consumidores escalares.
- **Lineage.** `provisioning_ifrs9` no completa `data_hash` ni `config_hash`; los consume. Su aporte al lineage son config computacional, versiones de dependencias, fuente de term-structure, hashes auxiliares de las curvas y decisiones auditadas.
- **Vigilancia regulatoria.** Antes de release productivo F4, revalidar los umbrales SICR, `rho` y pesos de escenario contra la política vigente de la institución y la norma IFRS 9/EBA; son parámetros de la entidad, no constantes Nikodym.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymError`, `MissingDependencyError`, lineage, `config_hash`, patrón CT-2 `term_structure()`.
- SDD-02 (`data`): `frame` con columnas económicas; `data_hash`, frontera transversal CT-3 (el panel longitudinal económico se difiere).
- SDD-05: `NikodymBaseConfig`, hooks diferidos, `INFRA_SECTIONS`, round-trip YAML.
- SDD-10 (`calibration`): `calibrated_pd_frame` como PD 12m base condicional.
- SDD-18 (`survival`) / SDD-19 (`markov`): proveedores intercambiables de term-structure lifetime por el contrato tidy hermano (CT-2); **sin importar internals**.
- SDD-20 (`forward`): proveedor opcional de term-structure multiescenario PIT (no publica factor sistémico `Z`; FALTA-DATO-IFRS-1).
- Aguas abajo: SDD-17 (orquestación/piso), SDD-22 (validación/backtesting ECL), SDD-23 (ui), SDD-26 (report).

**Externas.**

| Dependencia | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | `>=2.0` | BSD-3 ✅ | frames de I/O, agregaciones, term-structure | base |
| numpy | `>=1.22` | BSD ✅ | vectorización, finitud | base |
| scipy | `>=1.10` | BSD-3 ✅ | `scipy.stats.norm.cdf/ppf` (Vasicek Φ/Φ⁻¹) | extra (import perezoso) |
| statsmodels | `>=0.14` | BSD ✅ | GLM fractional/beta LGD | extra `[scoring]` (import perezoso) |
| pydantic | `>=2` | MIT ✅ | DTOs/config frozen | base |

**Núcleo liviano.** `nikodym.core` no importa `nikodym.provisioning`. `import nikodym.provisioning.ifrs9` registra config/step sin cargar scipy/statsmodels/pandas pesado en top-level; las dependencias numéricas se importan dentro de `calculate`/`execute` y fallan con `MissingDependencyError` claro. No hay dependencia copyleft (GPL) en el core.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos con goldens verificables a mano:

- **Golden Vasicek.** Con `PD_TTC=0.02`, `ρ=0.15`: `Z=−3` (recesión severa) → `PD_PIT ≈ 0.1667`; `Z=0` → `PD_PIT ≈ Φ(Φ⁻¹(0.02)/√0.85)` (≠ `PD_TTC`, efecto Jensen); `Z=+3` (expansión) → `PD_PIT ≈ 0.00024`. El test computa contra `scipy.stats.norm.ppf/cdf`; los decimales se verifican a doble precisión en implementación (regla de proyecto: no aproximar números regulatorios). Verifica también la orientación `Z<0 ⇒ PD↑`, `Z>0 ⇒ PD↓`.
- **Golden PD 12m/lifetime.** Term-structure con `PD_marg=(0.10, 0.08, 0.05)` y `H_12m` cubriendo `t≤1` (anual): `PD_12m=0.10`, `PD_life=0.23`, `PD_cum(3)=0.23`.
- **Golden EAD/CCF.** `drawn=800`, `límite=1000`, `CCF=0.5` → `EAD = 800 + 0.5·200 = 900`.
- **Golden LGD identidad.** `recovery=0.6` → `LGD=0.40`; floor/cap acotan; workout con recuperos descontados a EIR reproduce `1 − PV(recuperos)/EAD`.
- **Golden ECL marginal (1 escenario, anual).** `PD_marg=(0.10,0.08)`, `LGD=0.40`, `EAD=(1000,900)`, `EIR=0.10`:
  `t=1: 0.10·0.40·1000/1.1 = 36.363636…`; `t=2: 0.08·0.40·900/1.21 = 23.801652…`; **`ECL = 60.165289…`**.
- **Golden ECL multiescenario.** Con `w=(0.5,0.3,0.2)` y ECL por escenario `(50, 80, 120)`: `ECL = 0.5·50 + 0.3·80 + 0.2·120 = 73.0`.
- **Golden staging.** `PD_life_origen=0.05`, `PD_life_actual=0.11` → ratio `2.2 ≥ 2.0` → Stage 2; `dpd=35 ≥ 30` → Stage 2; `dpd=95 ≥ 90` → Stage 3; bajo la política v1, la exención no rescata una presunción DPD disparada.
- **Truncado por stage.** Stage 1 usa solo `t≤H_12m` (12m); Stage 2/3 usan lifetime; `ecl_reported` cuadra con el stage.
- **Guard anti escenario medio.** Un nombre reservado en `weights` o en la term-structure levanta `IfrsConfigError` (config y motor, case-insensitive; escape hatch `forbid_mean_scenario=False` con golden invariante); `Σ w_k = 1` validado.
- **Interfaz term-structure.** Contrato tidy incompleto o invariante roto → `IfrsTermStructureError`; survival y markov como fuentes producen el mismo ECL dado el mismo `pd_marginal`.
- **CT-1.** `requires` dinámicos según `term_structure_source`/`base_pd_source`; falta de un `requires` → `ArtifactNotFoundError`.
- **No mutación.** Snapshots profundos de `data.frame`, term-structure y `calibrated_pd_frame` permanecen iguales tras `execute`.
- **Config.** Round-trip YAML; cambiar `term_structure_source`, `rho`, `pit_mode`, umbrales SICR, pesos o convención de descuento cambia `config_hash`; **B16.1 mueve `GOLDEN_DEFAULT_CONFIG_HASH`** (test explícito, no regresión).
- **Import liviano.** `import nikodym.core` no importa `nikodym.provisioning`; `import nikodym.provisioning.ifrs9` no carga scipy/statsmodels hasta pedirlos (test de `sys.modules` en subproceso).
- **Warnings como error.** `filterwarnings=["error"]`; overflow en `expm`-equivalentes, casting o no convergencia de GLM se convierten en error controlado.
- **Cobertura regulatoria 100%.** `src/nikodym/provisioning/ifrs9/**` en el grupo de cobertura 100% (declarado regulatorio en CT §4). `mypy --strict`; ruff `E,F,I,N,UP,B,SIM,RUF,D` con docstrings en español; wrappers sin stubs con `cast()`/`ignore` localizados.

Fixtures: `ifrs9_exposures.parquet` sintético (drawn/límite/dpd/EIR/rating/recovery, sin datos reales), `term_structure_small` de survival y de markov, `forward_term_structure` multiescenario, `calibrated_pd_frame` de SDD-10, `IfrsProvisioningConfig` mínimo por enfoque, `InMemoryAuditSink`, y datasets degenerados (LGD fuera de rango, EAD negativa, term-structure inconsistente, pesos que no suman 1).

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Doble ajuste macro (Vasicek sobre curva ya PIT).** Mitigación: guard implementado en el motor (`IfrsConfigError` sobre term-structures etiquetadas no-TTC), además del default `pit_mode="consume_pit"`.
- **Umbrales SICR mal calibrados.** Mitigación: parametrizables por cartera; defaults citan ESPEC/IFRS 9 pero se marcan como requerir calibración de la institución (D-IFRS-3).
- **`rho` inventada.** Mitigación: sin default hardcodeado; config por cartera o `FALTA-DATO` (D-IFRS-7).
- **Confundir PD 12m/transversal con lifetime.** Mitigación: ambas se derivan explícitamente de la term-structure con `H_12m` declarado.
- **Escenario medio.** Mitigación: guard bloqueante en config y motor (nombres reservados vetados); se ponderan outputs.
- **Panel longitudinal ausente (EAD(t)/LGD(t)).** Mitigación: CT-3; perfil por período si existe, constante con warning si no; no se fuerza SDD-02.
- **Acoplamiento frágil con survival/markov.** Mitigación: contrato tidy CT-2; tests cruzados; sin imports de internals.
- **Rendimiento `O(n·T·K)`.** Mitigación: validar tamaño antes de materializar; vectorización con equivalencia bit-a-bit al motor de referencia.

**FALTA-DATO explícitos.**
- **FALTA-DATO-IFRS-1 — Factor sistémico `Z` y `rho`.** `apply_vasicek` requiere columna `Z` y `rho` escalar explícitos; `forward` no los aporta implícitamente (la exención del validador por `scenarios.source="forward"` se eliminó) y la política es `IfrsConfigError` siempre — no existe ruta degradada. La derivación de `Z` implícito desde datos observados es capacidad futura con SDD propio.
- **FALTA-DATO-IFRS-2 — Horizonte 12m vs unidad temporal.** `H_12m` depende de la granularidad de la term-structure (mensual/trimestral/anual); debe declararse.
- **FALTA-DATO-IFRS-3 — Definición de default y ventana aplicables.** Heredadas de la capa longitudinal (CT-3); SDD-16 consume `is_default`/dpd ya definidos.
- **FALTA-DATO-IFRS-4 — Perfil de exposición EAD(t).** Sin panel longitudinal, la amortización por período no está disponible.
- **FALTA-DATO-IFRS-5 — EIR por instrumento.** Debe venir en `data.frame`; no se infiere una tasa.
- **FALTA-DATO-IFRS-6 — LGD forward descartada.** Si la term-structure entrante trae columna `lgd` con valores no nulos (SDD-20), el motor v1 la ignora — la LGD sale de `IfrsLgdConfig` — y lo declara en `warning_codes` por fila y `card.falta_dato`; la auditoría `ifrs9_lgd` expone `lgd_forward_presente`. El gatillo es la columna `lgd` (LGD condicionada); `lgd_base` — linaje de la LGD base de entrada, sin condicionamiento macro — queda fuera del aviso por diseño. La precedencia de la LGD condicionada (FALTA-DATO-FWD-6 de SDD-20) queda pendiente de un SDD propio; el golden invariante de tests debe fallar si alguien la implementa sin ese SDD.

**Fuentes verificadas / citas.**
- **ESPECIFICACIONES.md** §5.5: PD 12m/lifetime + Vasicek monofactorial (fórmula y orientación), LGD beta/fractional/workout, EAD/CCF, staging/SICR (ratio ≥2×, backstop ≥3×, 30/90 dpd, low credit risk exemption), motor ECL con descuento a EIR y multiescenario, Stage 1 = 12m / Stage 2-3 = lifetime.
- **ESPECIFICACIONES.md** §5.6: cadena forward `macro→satellite→term-structure→ecl→scenario_weighting`, consistencia PIT, guard anti escenario medio.
- **ESPECIFICACIONES.md** §6.1: `BaseECLModel` con salida económica multi-componente.
- **ROADMAP.md** F4: entregables (PD/LGD/EAD, staging, motor ECL, orquestación) y DoD (tests de fórmula Vasicek/ECL marginal contra valores canónicos; term-structure conectada por interfaz a F5).
- **_CONTRATOS-TRANSVERSALES.md** CT-1 (`requires`/`provides`), CT-2 (`term_structure()`, `metric_sections`, `payload`), CT-3 (frontera transversal vs longitudinal), §4 (`provisioning/ifrs9` declarado regulatorio a 100% de cobertura).
- **SDD-18 (`survival`) / SDD-19 (`markov`)**: contrato tidy hermano de term-structure lifetime PD (`pd_marginal`, `pd_cumulative`, `survival`, `hazard`, `scenario`); FALTA-DATO-SUR-6 (shape final IFRS 9) y FALTA-DATO-MKV-3 (horizonte económico) que SDD-16 resuelve.
- **SDD-20 (`forward`)**: term-structure multiescenario PIT, `pd_basis`/`basis_state`, pesos de escenario; delega la transformación Vasicek a SDD-16 (§40).
- **SDD-10 (`calibration`)**: `calibrated_pd_frame`; delega la conversión PIT/TTC macro a SDD-16/18/20 (§37).
- **SDD-15 (`provisioning/cmf`)**: motor hermano; SDD-17 puede comparar ambos con fines
  informativos, sin atribuir carácter prudencial a ese comparativo.
- **core/config/hashing.py**: `INFRA_SECTIONS = {"name","governance","audit","tracking","report"}` — `provisioning_ifrs9` no pertenece → mueve `GOLDEN_DEFAULT_CONFIG_HASH`.

## Decisiones implementadas y parámetros institucionales pendientes

- **Implementado:** dominio plano `provisioning_ifrs9`; LGD `provided` por default; salidas 12m y lifetime; EIR anual por fracción de año; fuente lifetime configurable; ECL Stage 3 lifetime; comparativo SDD-17 separado y no normativo para CMF↔IFRS 9.
- **Requiere decisión/calibración institucional antes de uso productivo:** umbrales SICR, pesos de escenario, `rho`, definición de default, horizonte 12m, reglas workout y perfil EAD/LGD. Nikodym no certifica esos parámetros.
- **Deuda contractual del P0 (cerrada o caracterizada, 2026-07-20):** `rho_col` rechazada fail-fast en config (consumo real diferido); exención del `Z` implícito eliminada (Z siempre explícito; derivación desde datos = capacidad futura con SDD); guard anti doble ajuste PIT/TTC implementado en el motor; guard anti escenario medio bloqueante en config y motor; pesos cero caracterizados como frontera con tests (resolución de fondo = decisión de política pendiente, toca tres guards); LGD forward ignorada con aviso `FALTA-DATO-IFRS-6` auditado (precedencia pendiente de SDD propio).
- Ninguna de estas decisiones autoriza release, tag o PyPI; la API IFRS 9 continúa experimental.
