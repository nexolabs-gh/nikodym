# SDD-22 — `validation` (validación avanzada: calibración, backtesting, semáforo)

| Campo | Valor |
|---|---|
| **SDD** | 22 |
| **Módulo** | `nikodym.validation` |
| **Dominio** | Validación |
| **Fase** | F6 |
| **Tanda de producción** | T6 (Validación + UI) |
| **Estado** | ✅ Implementado; API experimental. Enmendado por [`_ENMIENDA-VALIDACION-COTEJADA.md`](_ENMIENDA-VALIDACION-COTEJADA.md) (D-VAL-13…18, aprobada el 2026-09-14): la capa A (D-VAL-13/14/15/18) está implementada; B y C, pendientes |
| **Depende de** | SDD-01 (`core`), SDD-05 (convenciones + config), SDD-11 (`performance` + `stability`), SDD-16 (`provisioning/ifrs9`); SDD-02 (`data`), SDD-10 (`calibration`) como proveedores de PD/target/outcomes |
| **Lo consumen** | SDD-26 (`report`), SDD-23 (`ui`), SDD-03 (`governance`, vía card) |
| **Autor / Fecha** | DanIA (redacción SDD-22 para T6/F6) / 2026-07-03 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `validation` ejecuta, de forma determinista y auditable, la **validación formal** de un modelo del repo: consolida la **discriminación** (ROC/AUC, Gini, KS) y la **estabilidad** (PSI) ya producidas por `performance`/`stability`, **añade** la **calibración** que aquellas capas excluyen (Hosmer-Lemeshow, test binomial por grado, semáforo/traffic-light, Brier) y el **backtesting realizado-vs-estimado** (t-test estilo ECB para LGD/EAD y test binomial/Jeffreys para PD contra las salidas IFRS 9 de SDD-16), publicando un resultado tidy consumible por `report` y `governance`.

**Responsabilidad única (qué SÍ hace).**
- **Discriminación (reúso, no recálculo).** **Consume** `("performance","discriminant_metrics")` como resultado canónico de AUC/Gini/KS; para modelos donde `performance` no corrió (p.ej. un modelo `ml` de SDD-12), **reúsa** el `PerformanceEvaluator` de SDD-11 (nunca reimplementa la fórmula). Ver D-VAL-1.
- **Estabilidad (reúso, no recálculo).** **Consume** `("stability","psi_table")` / `("stability","stability_metrics")` como resultado canónico de PSI; nunca reimplementa el PSI (D-VAL-2).
- **Calibración (aporte propio).** Calcula el estadístico **Hosmer-Lemeshow** por deciles de PD (χ² con `G−2` gl), el **test binomial por grado** de rating, el **Brier score** y asigna un **semáforo verde/ámbar/rojo** por grado y a nivel cartera.
- **Backtesting realizado-vs-estimado (aporte propio).** Compara PD/LGD/EAD estimados (salidas IFRS 9 de SDD-16) contra los realizados del período de desempeño: **t-test** para LGD y EAD/CCF, **test binomial/Jeffreys** para PD, con verdicto por segmento y cartera.
- **Suite ejecutable sobre cualquier modelo del repo** (DoD F6): las familias activas y los `requires` (CT-1) se construyen en `from_config` según el modelo objetivo y los artefactos presentes.
- Aporta el sub-config **`ValidationConfig`** (sección `validation` de `NikodymConfig`), **computacional** → entra en el `config_hash`.
- Expone DTOs frozen tidy y `metric_sections` (puerta CT-2) para `report`/`governance`; registra con `log_decision` cada test fallado, banda de semáforo cruzada, nivel de significancia usado y cualquier `FALTA-DATO`.

**Frontera dura de responsabilidad (qué NO hace, y quién lo hace).**
- **No recomputa AUC/Gini/KS ni PSI cuando ya existen aguas arriba.** SDD-11 es la fuente canónica; SDD-22 los consume y sólo los **reúsa** (misma función pública) en el camino de fallback para un modelo sin `performance`/`stability`.
- **No calibra PD ni reestima el modelo.** SDD-10 (`calibration`) produce `calibrated_pd_frame`; SDD-08 estima; SDD-22 sólo **evalúa** la calidad de esa PD ya construida.
- **No calcula ECL ni aplica la regla B-1.** SDD-16 produce el ECL y SDD-17 orquesta fuentes
  configurables; SDD-22 **valida** salidas, no las genera ni las orquesta. El binding prudencial
  chileno es estándar CMF frente a método interno, no CMF frente a IFRS 9.
- **No define la ventana de desempeño, la definición regulatoria de default ni el panel longitudinal por cuenta-período.** CT-3 difiere esa capa de datos a F4/F5; SDD-22 consume columnas de resultado realizado ya validadas y declaradas por config (D-VAL-9).
- **No renderiza reportes.** SDD-26 (`report`) consume el `card`/`metric_sections`; SDD-22 no importa `report` (acoplamiento sólo por artefacto/DTO).
- **No inventa umbrales ni cifras regulatorias.** Todo umbral sin fuente citada se marca `FALTA-DATO` o se declara **default institucional configurable y auditado**, nunca hardcodeado como norma.
- **No muta artefactos aguas arriba.** Lee y publica **copias defensivas** bajo el namespace `"validation"`.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Validación (F6/T6). Corre **al final del pipeline**, después de `performance`/`stability` (F1) y de `provisioning_ifrs9` (F4); antes de `report`. Es la última capa analítica del `Study`.
- **Quién lo invoca:** `Study.run()` como sección `validation` de `NikodymConfig`, o API programática para validar un modelo ya materializado (`ValidationEngine.validate(...)`).
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, excepciones, lineage), artefactos de `performance`, `stability`, `calibration`, `provisioning_ifrs9`, `data`; `scipy.stats` (χ², binomial, beta, t) e `import` perezoso de `PerformanceEvaluator`/`StabilityEvaluator` sólo en el camino de fallback.

```text
                       ┌── performance ─► discriminant_metrics ─┐
data ─► ... ─► model ─► calibration ─► (perf/stab) ─────────────┤
                       └── stability   ─► psi_table ────────────┤
survival/markov/forward ─► provisioning_ifrs9 ─► detail/staging ─┴─► validation (SDD-22) ─► report/governance
                                          PD·LGD·EAD estimados        HL · binomial · semáforo · Brier · t-test ECB
```

**Interacción con `Study` y config declarativo.** `ValidationStep` es un `Step` nativo registrado con `@register("standard", domain="validation")`. Como valida "cualquier modelo", sus `requires` (CT-1) **se construyen en `from_config`** según las familias activas (patrón dinámico de SDD-16 §4 / SDD-20 §81): la familia `calibration` exige `("calibration","calibrated_pd_frame")` + target; `discrimination`/`stability` prefieren consumir los artefactos de SDD-11 y sólo caen al fallback si no existen; `backtesting` exige artefactos `provisioning_ifrs9` + columnas de resultado realizado. Recibe `rng` por contrato homogéneo de `Step`; el motor v1 es determinista y hace `del rng`.

**Cableado implementado en `core.study`.** El registro vigente:
- `_DOMAIN_MODULES["validation"] = "nikodym.validation"`;
- `_DOMAIN_CONFIG_CLASSES["validation"] = ("nikodym.validation.config", "ValidationConfig")`;
- `_DEFAULT_DOMAIN_ORDER`: `"validation"` **al final**, después de `"performance"`, `"stability"` y `"provisioning_ifrs9"` cuando esas secciones estén presentes. El orden lineal no reemplaza CT-1: los prerequisitos reales se expresan por `requires`/`provides`; el scheduler topológico sigue diferido a F5.

**Normativa relevante.** CMF CNC B-1 exige *validación y backtesting* de las metodologías internas, pero **no fija umbrales numéricos** (mismo hallazgo que SDD-11 §2). Los métodos formales de esta capa provienen de fuentes metodológicas/regulatorias externas citadas en §3 (Hosmer-Lemeshow, ECB, BCBS); ningún umbral se hardcodea como regulatorio sin fuente.

**Paquete físico troceable.**

```text
src/nikodym/validation/
  __init__.py            # puebla hook _VALIDATION_CONFIG_CLS y registra ValidationStep
  config.py              # ValidationConfig + sub-configs por familia
  exceptions.py          # ValidationError + subclases por familia
  results.py             # DTOs Pydantic frozen + metric_sections (CT-2)
  discrimination.py      # reúso/consumo de performance (AUC/Gini/KS) — no reimplementa
  calibration_tests.py   # Hosmer-Lemeshow, binomial por grado, semáforo, Brier
  stability.py           # reúso/consumo de stability (PSI) — no reimplementa
  backtesting.py         # t-test (LGD/EAD) + binomial/Jeffreys (PD) vs IFRS 9
  evaluator.py           # ValidationEvaluator orquesta las familias activas
  step.py                # ValidationStep + @register + cableado core.study
```

**Troceo implementable un módulo/commit.**
- **B22.1 — config/exceptions:** `config.py`, `exceptions.py`, hook diferido `_VALIDATION_CONFIG_CLS` en `core.config.schema`, round-trip YAML. **Mueve `GOLDEN_DEFAULT_CONFIG_HASH`** (§5).
- **B22.2 — results:** DTOs Pydantic frozen (`DiscriminationRecord`, `CalibrationTestRecord`, `GradeBinomialRecord`, `BrierRecord`, `BacktestRecord`, `ValidationCardSection`, `ValidationResult`), `metric_sections` CT-2.
- **B22.3 — calibration_tests:** Hosmer-Lemeshow (goldens de fórmula), binomial por grado, Brier, semáforo.
- **B22.4 — backtesting:** t-test LGD/EAD, binomial/Jeffreys PD, verdicto por segmento; goldens contra casos canónicos.
- **B22.5 — discrimination/stability:** consumo de SDD-11 + fallback por reúso de `PerformanceEvaluator`/`StabilityEvaluator`.
- **B22.6 — evaluator/step:** `ValidationEvaluator`, `ValidationStep`, `@register`, `requires`/`provides` dinámicos, cableado `core.study` e integración end-to-end sobre un modelo scorecard y un modelo IFRS 9.

Cada bloque cierra con ruff (regla `D`, docstrings en español), mypy `--strict`, tests 100% del módulo tocado y **cobertura 100%** del paquete `nikodym.validation` (D-VAL-12).

## 3. Conceptos y fundamentos

> **Regla dura del proyecto (principio #11):** cada fórmula y umbral se cita contra su fuente oficial. Donde la convención numérica exacta requiera verificación por **render visual** del documento original, se marca **`FALTA-DATO`** y se enumera como decisión para Cami — **no se rellena con un número inventado**. Las tres marcas que este SDD llevó desde el Borrador (`VAL-1/2/3`) se cotejaron el 2026-09-13 por doble vía y se retiraron con D-VAL-13/14/15 (registro del cotejo en §12).

### 3.1 Discriminación (reúso de SDD-11)

`AUC`/`ROC`, `Gini = 2·AUC − 1` y `KS = max_t |TPR(t) − FPR(t)|` están **definidos y verificados en SDD-11 §3** y publicados en `("performance","discriminant_metrics")`. SDD-22 **no los redefine**: los consume tal cual y, en el fallback, invoca el mismo `PerformanceEvaluator`. Fuente: ESPEC §5.2/§5.7; SDD-11 §3.

### 3.2 Calibración

**Hosmer-Lemeshow (HL).** Prueba de bondad de ajuste/calibración para modelos de probabilidad. Se ordenan las observaciones por PD predicha, se parten en `G` grupos aproximadamente iguales (**convención `G = 10` deciles**) y se calcula:

```text
HL = Σ_{g=1}^{G} (O_g − n_g·p̄_g)² / [ n_g · p̄_g · (1 − p̄_g) ]
```

donde `O_g` = defaults observados en el grupo `g`, `n_g` = nº de observaciones y `p̄_g` = PD media predicha del grupo. Bajo H0 (modelo bien calibrado) el estadístico sigue asintóticamente **χ² con `G−2` grados de libertad** (con `G=10` → **8 gl**). Un p-valor bajo indica mala calibración. *Fuente:* Hosmer, D.W. & Lemeshow, S., *Applied Logistic Regression* (Wiley), definición estándar del estadístico y de los `G−2` gl (verificado: `G=10` deciles → 8 gl). `χ².sf` vía `scipy.stats.chi2` (import perezoso).

**Test binomial por grado.** Para cada grado/segmento de rating con PD estimada `p̂` y `N` operaciones, bajo H0 (la PD estimada es correcta) el nº de defaults `D` sigue `Binomial(N, p̂)`. Contraste unilateral de **subestimación** de PD; aproximación normal:

```text
z = (D − N·p̂) / sqrt( N · p̂ · (1 − p̂) )
```

Se reporta el p-valor exacto (`scipy.stats.binomtest`, unilateral superior) y el `z` asintótico. *Fuente:* BCBS Working Paper No. 14, *Studies on the Validation of Internal Rating Systems* (2005), test binomial para PD por grado.

**Jeffreys (variante regulatoria ECB para PD).** El estándar de la ECB para *predictive ability* de PD es el **Jeffreys test**: partiendo del prior de Jeffreys `Beta(½, ½)`, la posterior de la tasa de default es `Beta(D + ½, N − D + ½)` y el p-valor unilateral se deriva de esa posterior evaluada en la PD estimada. Es un test binomial regularizado que se comporta mejor con `D=0`. *Fuente:* ECB, *Instructions for reporting the validation results of internal models — credit risk* (feb 2019), §2.5.3.1 (Jeffreys test). **Cotejado el 2026-09-13 por doble vía (D-VAL-13, §12):** `p = β_{D+½, N−D+½}(PD)`, la CDF de la posterior evaluada en la PD media del grado, con `H0: PD aplicada ≥ PD verdadera`; la plantilla oficial lo calcula como `BETA.DIST(PD, D+0.5, N−D+0.5, TRUE)`. Es exactamente `calibration_tests.py::binomial_by_grade` con `test="jeffreys"` (reproducido: N=200, D=7, PD=0,025 → 0,177852704399066 en motor, fórmula e integral numérica).

**Semáforo / traffic-light (verde/ámbar/rojo).** El concepto de semáforo nace del backtesting de riesgo de mercado de Basilea (zonas verde/amarillo/rojo por nº de excepciones, probabilidad binomial acumulada; *fuente:* BCBS, *Supervisory framework for the use of "backtesting"...*, 1996) y la ECB lo usa para reportar *predictive ability*. **No existe un umbral regulatorio para el semáforo de calibración de PD por grado, y está verificado (D-VAL-15, §12):** el BCE no fija cortes sobre el p-valor, las zonas de Basilea 1996 son fronteras discretas e inclusivas sobre el conteo de excepciones de un VaR (dependientes de `N`; no equivalen a ningún corte fijo de p-valor) y el *traffic lights* de BCBS WP14 es otra herramienta. SDD-22 lo mapea al p-valor del test por grado con dos cortes configurables (default en §5, D-VAL-5), y **cada fila de grado publica los dos cortes con que se decidió su color** (`green_alpha`/`red_alpha`), la card los resume en `traffic_light_cuts`, el trail los registra y el informe los nombra sin atribuir la elección a nadie: el motor no sabe si un corte lo declaró la institución o es el default.

**Brier score.** Error cuadrático medio de la probabilidad:

```text
Brier = (1/N) · Σ_i ( p_i − y_i )²
```

con `p_i` la PD predicha e `y_i ∈ {0,1}` el resultado. Rango `[0,1]`, menor es mejor; descomponible en *reliability*/*resolution*/*uncertainty*. *Fuente:* Brier, G.W. (1950), *Verification of forecasts expressed in terms of probability*, Monthly Weather Review 78(1):1–3.

### 3.3 Estabilidad (reúso de SDD-11)

`PSI = Σ_b (actual_b − expected_b)·ln(actual_b/expected_b)` con bandas default `<0.10` estable / `0.10≤PSI<0.25` vigilar / `≥0.25` redesarrollar está **definido y publicado por SDD-11 §3** en `("stability","psi_table")`. SDD-22 lo **consume** como verdicto de estabilidad; no lo reimplementa. Fuente: ESPEC §5.2; SDD-11 §3.

### 3.4 Backtesting realizado-vs-estimado

Compara los parámetros **estimados** por IFRS 9 (SDD-16) contra los **realizados** en el período de desempeño declarado.

**t-test para LGD y EAD/CCF (estilo ECB).** El estándar ECB de *predictive ability* para LGD y CCF/EAD es un **t-test** sobre el error `e_i = realizado_i − estimado_i`. Con `N` operaciones, error medio `ē` y desviación muestral `s`:

```text
T = sqrt(N) · ē / s          # H0: el parámetro no está subestimado; contraste unilateral
```

comparado con una `t` de Student (`N−1` gl) o la normal para `N` grande. *Fuente:* ECB, *Instructions for reporting the validation results of internal models — credit risk* (feb 2019), §2.6.2.1 (LGD) y §2.9.3.2 (EAD).
**Cotejado el 2026-09-13 por doble vía (D-VAL-14, §12):** `T = √N · ē / s` con `s²` muestral (`N−1`), **sin ponderar por exposición** (promedios *number-weighted* en la plantilla oficial), unilateral con `H0: estimado ≥ realizado` y p-valor `1 − S_{N−1}(T)`. Es exactamente `backtesting.py::ttest_realised_vs_predicted` con `one_sided=True` (reproducido con N=50: `T` 2,70272856597448 y `p` 0,00471202123926); `one_sided=False` es la convención bilateral del ELBE (§2.7.2.1). La fórmula del CCF impresa en §2.9.3.1 omite el `1/R` del numerador: errata del PDF (la plantilla calcula con la diferencia de medias); el motor sigue la forma con media.

**Test binomial/Jeffreys para PD.** Para PD, el backtesting realizado-vs-estimado usa el mismo contraste binomial/Jeffreys de §3.2 (defaults observados vs PD estimada por grado). El spec (ESPEC §5.5/§5.7) escopa el **t-test a LGD/EAD**; para PD el contraste natural es el binomial (BCBS) / Jeffreys (ECB), no un t-test (D-VAL-6).

**Insumos IFRS 9.** Los **estimados** provienen de `("provisioning_ifrs9","detail")` (columnas `pd_12m`/`pd_life`, `lgd`, `ead` — SDD-16 §6) y `("provisioning_ifrs9","staging")`. Los **realizados** (default efectivo, LGD realizada, EAD a default) provienen de columnas declaradas por config en `("data","frame")`; su panel longitudinal multi-fecha se difiere a la capa de datos longitudinal (CT-3, D-VAL-9).

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/validation/config.py
class DiscriminationValidationConfig(NikodymBaseConfig): ...
class CalibrationValidationConfig(NikodymBaseConfig): ...
class StabilityValidationConfig(NikodymBaseConfig): ...
class BacktestingValidationConfig(NikodymBaseConfig): ...
class ValidationConfig(NikodymBaseConfig): ...

# nikodym/validation/exceptions.py
class ValidationError(NikodymError): ...
class ValidationConfigError(ValidationError): ...
class ValidationDataError(ValidationError): ...
class CalibrationTestError(ValidationError): ...
class BacktestError(ValidationError): ...
```

```python
# nikodym/validation/results.py
class DiscriminationRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    partition: str
    n_total: int
    n_bad: int
    auc: float | None          # None si not_evaluable (una sola clase)
    gini: float | None
    ks: float | None
    source: Literal["performance_artifact", "recomputed"]
    status: Literal["ok", "not_evaluable"]

class CalibrationTestRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    partition: str
    test: Literal["hosmer_lemeshow", "brier"]
    n_groups: int | None          # G (HL); None en Brier
    degrees_of_freedom: int | None  # G-2 (HL)
    statistic: float
    p_value: float | None         # None para Brier (no es test)
    alpha: float | None
    decision: Literal["pass", "fail", "not_evaluable"]

class GradeBinomialRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    grade: str
    n: int
    expected_pd: float
    observed_defaults: int
    observed_dr: float
    test: Literal["binomial", "jeffreys"]
    p_value: float
    z_stat: float | None
    alpha: float
    traffic_light: Literal["green", "amber", "red"]

class BacktestRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    parameter: Literal["pd", "lgd", "ead"]
    segment: str
    n: int
    predicted_mean: float
    realised_mean: float
    test: Literal["t_test", "binomial", "jeffreys"]
    statistic: float
    p_value: float
    alpha: float
    one_sided: bool
    decision: Literal["pass", "fail", "not_evaluable"]

class ValidationCardSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    model_ref: str                       # qué modelo se validó (config_hash / nombre)
    families_run: tuple[str, ...]         # discrimination/calibration/stability/backtesting
    overall_status: Literal["pass", "warn", "fail"]
    n_tests: int
    n_failed: int
    dependency_versions: dict[str, str]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)   # CT-2

class ValidationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    discrimination: "pandas.DataFrame"
    calibration: "pandas.DataFrame"
    stability: "pandas.DataFrame"
    backtesting: "pandas.DataFrame"
    discrimination_records: tuple[DiscriminationRecord, ...]
    calibration_records: tuple[CalibrationTestRecord, ...]
    grade_records: tuple[GradeBinomialRecord, ...]
    backtest_records: tuple[BacktestRecord, ...]
    card: ValidationCardSection
```

> **Nota CT-2.** El cumplimiento de CT-2 en validación es **`metric_sections` tidy + DTOs frozen + copias defensivas**, *no* el método económico `term_structure()` (que CT-2 reserva a `ProvisionResultLike`/`ECLResultLike`, SDD-01 §4). `validation` no produce estructura temporal económica; alimenta `report`/`governance` por `card` + `metric_sections`.

```python
# nikodym/validation/calibration_tests.py
def hosmer_lemeshow(y_true: "numpy.ndarray", pd_pred: "numpy.ndarray", *, n_groups: int = 10) -> "CalibrationTestRecord": ...
def binomial_by_grade(frame: "pandas.DataFrame", *, grade_col: str, pd_col: str, target_col: str,
                      test: str = "jeffreys", alpha: float = 0.05) -> "list[GradeBinomialRecord]": ...
def brier_score(y_true: "numpy.ndarray", pd_pred: "numpy.ndarray") -> "CalibrationTestRecord": ...
def traffic_light(p_value: float, *, green_alpha: float, red_alpha: float) -> str: ...

# nikodym/validation/backtesting.py
def ttest_realised_vs_predicted(realised: "numpy.ndarray", predicted: "numpy.ndarray", *,
                                one_sided: bool = True, alpha: float = 0.05) -> "BacktestRecord": ...

# nikodym/validation/evaluator.py
class ValidationEvaluator:
    @classmethod
    def from_config(cls, cfg: "ValidationConfig") -> "ValidationEvaluator": ...
    def validate(
        self,
        *,
        calibrated_pd: "pandas.DataFrame | None" = None,
        target: "pandas.Series | None" = None,
        performance_metrics: "pandas.DataFrame | None" = None,
        stability_metrics: "pandas.DataFrame | None" = None,
        ifrs9_detail: "pandas.DataFrame | None" = None,
        realised: "pandas.DataFrame | None" = None,
    ) -> "ValidationResult": ...
```

```python
# nikodym/validation/step.py
@register("standard", domain="validation")
class ValidationStep(AuditableMixin):
    name: str = "validation"
    requires: tuple[ArtifactKey, ...] = ()   # se construyen en from_config según familias/artefactos
    provides: tuple[ArtifactKey, ...] = (
        ("validation", "discrimination"),
        ("validation", "calibration"),
        ("validation", "stability"),
        ("validation", "backtesting"),
        ("validation", "result"),
        ("validation", "card"),
    )
    @classmethod
    def from_config(cls, cfg: "ValidationConfig") -> "ValidationStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "ValidationResult": ...
```

**`requires` dinámicos (CT-1, patrón SDD-16 §4).** `from_config` compone `requires` según `families`:
- `calibration` activa → `("calibration","calibrated_pd_frame")` + `("data","labels")` (target).
- `discrimination` activa → **prefiere** `("performance","discriminant_metrics")`; si el modelo objetivo no tiene `performance`, cae a `("calibration","calibrated_pd_frame")` + `("data","labels")` y reúsa `PerformanceEvaluator`.
- `stability` activa → `("stability","stability_metrics")` (y `("stability","psi_table")` para el detalle).
- `backtesting` activa → `("provisioning_ifrs9","detail")`, `("provisioning_ifrs9","staging")` y `("data","frame")` (columnas de resultado realizado).

La validación pre-run del motor v1 exige que cada `requires` compuesto esté presente en el `ArtifactStore`; su ausencia es `ArtifactNotFoundError` con el contrato incumplido **antes** de correr.

**Artefactos que `ValidationStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"discrimination"` | `pandas.DataFrame` | AUC/Gini/KS por partición (consumido o reúso), con `source` y `status` |
| `"calibration"` | `pandas.DataFrame` | HL, Brier y semáforo por grado; una fila por test/grado |
| `"stability"` | `pandas.DataFrame` | resumen PSI consumido de SDD-11 con verdicto de estabilidad |
| `"backtesting"` | `pandas.DataFrame` | t-test/binomial por parámetro (PD/LGD/EAD) y segmento |
| `"result"` | `ValidationResult` | contenedor agregado |
| `"card"` | `ValidationCardSection` | resumen para governance/report |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning", "selection", "model", "scorecard",
                 "calibration", "performance", "stability",
                 "provisioning_ifrs9", "validation"])
val = study.artifacts.get("validation", "result")
calib = study.artifacts.get("validation", "calibration")   # HL, Brier, semáforo
bt = study.artifacts.get("validation", "backtesting")      # t-test LGD/EAD, binomial PD
assert val.card.overall_status in {"pass", "warn", "fail"}
```

## 5. Configuración (schema Pydantic)

`ValidationConfig` es el sub-config de la sección `validation` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, campos con `title`/`description`, rangos `ge/le`, `Literal` en categóricos, metadatos `ui_*`, `type: Literal["standard"] = "standard"`. **No es infraestructura** (`validation ∉ INFRA_SECTIONS = {"name","governance","audit","tracking","report"}`; verificado contra SDD-16 §5): cambiar familias activas, nº de deciles HL, nivel de significancia, bandas del semáforo o el test de PD/LGD/EAD **cambia el `config_hash`**. Al cablear B22.1 se **moverá `GOLDEN_DEFAULT_CONFIG_HASH`** (mismo precedente que `provisioning_ifrs9`); el implementador debe barrer el literal en tests/repros, no tratarlo como regresión.

```python
class DiscriminationValidationConfig(NikodymBaseConfig):
    consume_performance: bool = Field(True, title="Consumir discriminant_metrics de SDD-11")
    partitions: tuple[Literal["desarrollo", "holdout", "oot"], ...] = Field(
        ("desarrollo", "holdout", "oot"), title="Particiones a validar")

class CalibrationValidationConfig(NikodymBaseConfig):
    hosmer_lemeshow: bool = Field(True, title="Ejecutar Hosmer-Lemeshow")
    hl_n_groups: int = Field(10, ge=5, le=20, title="Nº de grupos HL (deciles)")
    hl_grouping: Literal["deciles", "fixed_bands"] = Field("deciles", title="Criterio de agrupación HL")
    brier: bool = Field(True, title="Calcular Brier score")
    binomial_by_grade: bool = Field(True, title="Test binomial/Jeffreys por grado")
    grade_col: str = Field("grade", title="Columna de grado de rating")
    pd_test: Literal["binomial", "jeffreys"] = Field("jeffreys", title="Test de PD por grado")
    alpha: float = Field(0.05, gt=0.0, lt=0.5, title="Nivel de significancia")
    traffic_light_green_alpha: float = Field(0.05, gt=0.0, lt=1.0, title="Corte verde/ámbar (p-valor)")
    traffic_light_red_alpha: float = Field(0.01, gt=0.0, lt=1.0, title="Corte ámbar/rojo (p-valor)")
    target_column: str = Field("target", title="Columna target binario")
    pd_column: str = Field("pd_calibrated", title="Columna PD calibrada")
    partition_column: str = Field("partition", title="Columna partición")
    min_rows_per_group: int = Field(30, ge=1, title="Mínimo técnico por grupo HL/grado")

class StabilityValidationConfig(NikodymBaseConfig):
    consume_stability: bool = Field(True, title="Consumir stability_metrics de SDD-11")
    psi_stable_threshold: float = Field(0.10, ge=0.0, title="Umbral PSI de revisión")
    psi_review_threshold: float = Field(0.25, ge=0.0, title="Umbral PSI de redesarrollo")

class BacktestingValidationConfig(NikodymBaseConfig):
    enabled: bool = Field(False, title="Ejecutar backtesting IFRS 9")
    parameters: tuple[Literal["pd", "lgd", "ead"], ...] = Field(
        ("pd", "lgd", "ead"), title="Parámetros a backtestear")
    segment_col: str = Field("portfolio", title="Segmento de agregación")
    alpha: float = Field(0.05, gt=0.0, lt=0.5, title="Nivel de significancia")
    one_sided: bool = Field(True, title="Contraste unilateral (subestimación)")
    realised_pd_col: str = Field("realised_default", title="Default realizado (0/1)")
    realised_lgd_col: str = Field("realised_lgd", title="LGD realizada")
    realised_ead_col: str = Field("realised_ead", title="EAD realizada a default")
    pd_test: Literal["binomial", "jeffreys"] = Field("jeffreys", title="Test de PD")

class ValidationConfig(NikodymBaseConfig):
    schema_version: str = "1.0.0"
    type: Literal["standard"] = "standard"
    families: tuple[Literal["discrimination", "calibration", "stability", "backtesting"], ...] = Field(
        ("discrimination", "calibration", "stability"), title="Familias de validación activas")
    discrimination: DiscriminationValidationConfig = Field(default_factory=DiscriminationValidationConfig)
    calibration: CalibrationValidationConfig = Field(default_factory=CalibrationValidationConfig)
    stability: StabilityValidationConfig = Field(default_factory=StabilityValidationConfig)
    backtesting: BacktestingValidationConfig = Field(default_factory=BacktestingValidationConfig)
    fail_on_falta_dato: bool = Field(True, title="Fallar ante brechas críticas de dato")
```

**Validaciones de config.**
- `traffic_light_red_alpha < traffic_light_green_alpha` (rojo más estricto que ámbar).
- `psi_stable_threshold < psi_review_threshold`.
- `"backtesting" ∈ families` exige `backtesting.enabled=True` y las columnas realizadas declaradas; su omisión → `ValidationConfigError` o aviso declarado según `fail_on_falta_dato`. La marca del aviso depende de **de quién es la carencia**: `DATO-INSTITUCIONAL` cuando lo resuelve quien corre (config, encadenar IFRS 9, sus columnas realizadas) y `FALTA-DATO` cuando el `detail` de IFRS 9 llegó sin las columnas estimadas que ese mismo motor produce.
- `hl_grouping="fixed_bands"` exige bandas declaradas (reservado; default deciles).
- `grade_col`/`pd_column`/`target_column`/`partition_column` no vacíos ni colisionando.
- `discrimination.consume_performance=False` fuerza el fallback por reúso de `PerformanceEvaluator` (no reimplementación).

**Defaults defendibles (con fuente).**
- `families=("discrimination","calibration","stability")`: backtesting IFRS 9 **opt-in** porque exige artefactos F4 + resultados realizados que no todo modelo del repo tiene (DoD F6: ejecutable sobre *cualquier* modelo, no *todas las familias* sobre todo modelo).
- `hl_n_groups=10`: deciles, convención estándar de Hosmer-Lemeshow (§3.2) → `G−2=8` gl.
- `pd_test="jeffreys"`: alineado con la ECB (feb 2019) para *predictive ability* de PD; `binomial` (BCBS WP14) como alternativa.
- `alpha=0.05`: nivel de significancia estándar; configurable.
- `traffic_light_green_alpha=0.05`, `red_alpha=0.01`: **default institucional** mapeado al p-valor del test por grado, **persistido en el resultado** (cada fila de grado, la card, el trail y la prosa; D-VAL-15). Verificado que no existe corte regulatorio que cotejar (D-VAL-5, §12).
- PSI `0.10/0.25`: heredado de SDD-11/ESPEC §5.2, criterio institucional configurable.
- `one_sided=True`: el interés supervisor es la **subestimación** del parámetro (ECB); configurable.

**Hook implementado en `core.config.schema`.** El contrato vigente:
- declarar `_VALIDATION_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir campo `validation` como `Any` en runtime y `ValidationConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("validation", mode="before")` (`_valida_validation`) que valida con `ValidationConfig` si el hook está poblado, o exige JSON canónico determinista si no;
- `nikodym.validation.__init__` puebla el hook y registra `ValidationStep`;
- `validation` **no** entra a `INFRA_SECTIONS`.

## 6. Contratos de datos (I/O)

**Inputs de `ValidationStep` vía `Study` (nombres reales de SDD vecinos, con origen citado).**

| dominio | clave | proveedor (SDD/§) | obligatoriedad | uso |
|---|---|---|---|---|
| `calibration` | `"calibrated_pd_frame"` | SDD-10 §4/§6 (confirmado por SDD-11 §6 y SDD-16 §6) | familia `calibration`/fallback | PD calibrada + `partition`, `target` |
| `data` | `"labels"` | SDD-02 (confirmado por SDD-11 §4) | familia `calibration`/fallback | target binario, grado de rating |
| `data` | `"frame"` | SDD-02 §6 (confirmado por SDD-16 §6) | familia `backtesting` | columnas de resultado realizado (default/LGD/EAD) |
| `performance` | `"discriminant_metrics"` | **SDD-11 §4 `provides`** | familia `discrimination` (preferente) | AUC/Gini/KS por partición |
| `stability` | `"stability_metrics"`, `"psi_table"` | **SDD-11 §4 `provides`** | familia `stability` | PSI y bandas |
| `provisioning_ifrs9` | `"detail"`, `"staging"` | **SDD-16 §4 `provides`** | familia `backtesting` | PD/LGD/EAD estimados, stage |

**Cierre del DAG (verificación `requires` → `provides`).** Cada clave `requires` de SDD-22 existe como `provides` de su SDD vecino:
- `("performance","discriminant_metrics")` ✓ SDD-11 §4.
- `("stability","stability_metrics")` / `("stability","psi_table")` ✓ SDD-11 §4.
- `("calibration","calibrated_pd_frame")` ✓ SDD-10 (consumida idénticamente por SDD-11 §6 y SDD-16 §6).
- `("data","labels")` / `("data","frame")` ✓ SDD-02 (consumidas por SDD-11 §4 y SDD-16 §6).
- `("provisioning_ifrs9","detail")` / `("provisioning_ifrs9","staging")` ✓ SDD-16 §4.

**Frame analítico común.** El evaluador alinea por índice, con copias profundas (`copy(deep=True)`):

| columna | fuente | uso |
|---|---|---|
| `partition` | calibration/labels | HL/Brier por partición |
| `target` | labels | resultado binario |
| `pd_calibrated` | calibration | PD para HL/Brier/binomial |
| `grade` | labels/frame | test binomial por grado |
| `realised_default`/`realised_lgd`/`realised_ead` | data.frame | backtesting realizado |
| `pd_12m`/`pd_life`, `lgd`, `ead` | provisioning_ifrs9.detail | backtesting estimado |

**Output `calibration`.** `pandas.DataFrame`, orden canónico por `partition`, `test`, `grade`:

| columna | significado |
|---|---|
| `partition` | desarrollo/holdout/oot |
| `test` | `hosmer_lemeshow`, `binomial`/`jeffreys`, `brier` |
| `grade` | grado de rating (binomial) o `ALL` |
| `n`, `observed_defaults`, `expected_pd`, `observed_dr` | conteos y tasas |
| `statistic`, `degrees_of_freedom`, `p_value` | estadístico y p-valor; `statistic` es **nulo** en un Hosmer-Lemeshow sin veredicto (D-VAL-17: antes publicaba `0.0`, el valor de un ajuste perfecto) |
| `alpha`, `decision`, `traffic_light` | umbral, verdicto y semáforo |
| `green_alpha`, `red_alpha` | los dos cortes con que se decidió el color de cada fila de grado (D-VAL-15); nulos en HL y Brier. Columnas de auditoría: el informe no las pinta, la prosa nombra los cortes |
| `not_evaluable_reason` | por qué un Hosmer-Lemeshow quedó sin veredicto (D-VAL-17): `partition_below_min`, `group_below_min`, `degenerate_group` o `non_finite_statistic`; nula en toda otra fila. Columna de auditoría: el informe no la pinta, la prosa la traduce con sus números y el panel la muestra junto al «Sin veredicto» |

**Output `backtesting`.** `pandas.DataFrame`, una fila por `parameter × segment`:

| columna | significado |
|---|---|
| `parameter` | `pd`, `lgd`, `ead` |
| `segment` | cartera/segmento |
| `n`, `predicted_mean`, `realised_mean` | población y medias |
| `test`, `statistic`, `p_value`, `alpha`, `one_sided` | contraste |
| `decision` | `pass`, `fail`, `not_evaluable` |

**Output `discrimination`** y **`stability`.** Espejo tidy de los artefactos consumidos de SDD-11 más columnas `source`/`status`/`decision`; nunca recomputan la métrica salvo fallback documentado.

**Validación pandera.** Los módulos definen schemas de entrada/salida con `import pandera.pandas as pa`, nunca `import pandera as pa`, para evitar warnings del top-level bajo `filterwarnings=["error"]`.

**Invariantes.**
- Índice único y alineado entre `calibrated_pd_frame`, `labels` y (si aplica) `ifrs9.detail`.
- `0 < pd_calibrated < 1`, finita; `target ∈ {0,1}`.
- Grupos HL/grados con `n < min_rows_per_group` → estado `not_evaluable` auditado, **nunca** métrica engañosa ni `NaN` silencioso. **Desde D-VAL-17 el mínimo protege también cada grupo de PD del Hosmer-Lemeshow** (la puerta mira el menor grupo que deja `np.array_split`), no sólo la partición entera: con diez grupos y el mínimo de fábrica una partición necesita ≥ 300 operaciones. El HL sin veredicto publica `statistic=None` y su causa; la card enumera esas particiones en `metric_sections.validation.not_evaluable_partitions` (partición, `n`, `n_groups`, `min_group_size`, `min_rows`, `reason`).
- `n_tests`/`n_failed` cuentan **sólo decisiones evaluables** en las cuatro familias (D-VAL-17): un HL o un backtest `not_evaluable` no es una prueba corrida sin veredicto sino una que no se pudo correr; el Brier tampoco cuenta. `overall_status` gana `not_evaluable` («No evaluable») cuando no hay evidencia evaluable alguna —ninguna decisión `pass`/`fail` y ninguna fila de estabilidad con decisión—; antes ese caso decía `pass`. La regla vive en `results.derive_test_counts`/`derive_overall_status`, la usa el evaluador y `ValidationResult` la exige a la card (también rehidratada).
- Ningún Step escribe bajo dominios aguas arriba.
- Floats publicados normalizan `-0.0 → 0.0`; jamás se publica `NaN`/`inf` (se usa `None`/`not_evaluable`).
- Orden estable de grupos/grados; empates por índice estable, no por orden accidental de pandas.

## 7. Algoritmos y flujo

**`ValidationStep.execute(study, rng)` — secuencia canónica.**
1. **Descartar azar.** `del rng`; validación v1 es determinista.
2. **Leer artefactos.** Validar CT-1 y tipos según familias activas; construir el frame analítico con copias profundas.
3. **Discriminación.** Si `consume_performance` y existe `("performance","discriminant_metrics")` → **consumir** y anexar `source="performance_artifact"`. Si no, **reúso**: invocar `PerformanceEvaluator.evaluate(...)` (SDD-11 §4) sobre `(pd_calibrated, target, partition)`, `source="recomputed"`. **Nunca** reimplementar AUC/KS/Gini.
4. **Calibración.**
   a. Por partición, calcular **Hosmer-Lemeshow**: ordenar por PD, formar `G` grupos (deciles), aplicar la fórmula §3.2, p-valor con `chi2.sf(HL, G−2)`.
   b. **Brier** por partición (§3.2).
   c. **Binomial/Jeffreys por grado** (§3.2): p-valor unilateral por grado; asignar `traffic_light` con `traffic_light(p, green_alpha, red_alpha)`.
   d. Grupos/grados bajo mínimo → `not_evaluable` auditado.
5. **Estabilidad.** Consumir `("stability","stability_metrics")`; mapear bandas PSI a verdicto de estabilidad. Sin recomputar (fallback: reúso de `StabilityEvaluator` sólo si el artefacto no existe).
6. **Backtesting** (si activo). Para cada `parameter ∈ {pd,lgd,ead}` y segmento:
   - `lgd`/`ead`: **t-test** sobre `e_i = realizado − estimado` (§3.4), `scipy.stats.ttest_*`/estadístico manual unilateral.
   - `pd`: **binomial/Jeffreys** por segmento/grado contra defaults realizados.
   - Verdicto `pass`/`fail` según `alpha`; segmentos sin realizado suficiente → `not_evaluable`.
7. **Consolidar verdicto.** `overall_status`: `fail` si algún test crítico falla; `warn` si sólo ámbar/vigilar; `pass` si todo verde/no rechazado. Registrar cada fallo/banda con `log_decision`.
8. **Construir DTOs/card.** Incluir versiones de pandas/numpy/scipy, familias corridas, `alpha`, bandas, `falta_dato` y `metric_sections` tidy.
9. **Publicar artefactos.** Escribir `"discrimination"`, `"calibration"`, `"stability"`, `"backtesting"`, `"result"` y `"card"`.

**Alternativas descartadas.**
- *Recomputar AUC/KS/Gini/PSI en `validation`:* **descartado** (duplicaría lógica de SDD-11 y arriesgaría divergencia numérica); se consume/reúsa. D-VAL-1/D-VAL-2.
- *Un t-test para PD:* descartado; el spec escopa el t-test a LGD/EAD y para PD el contraste correcto es binomial/Jeffreys (§3.4).
- *Hardcodear cortes del semáforo desde el traffic-light de riesgo de mercado (Basilea 1996):* descartado por *category error* (VaR ≠ calibración de PD; verificado en §12): default configurable, publicado en cada fila con su color (D-VAL-15).
- *Usar `eval`/`df.eval` para reglas de bandas/tests:* descartado por seguridad y consistencia con SDD-02/SDD-11; toda regla es operación estructurada.
- *Varios Steps por familia:* descartado como default; un `ValidationStep` con toggles comparte el frame alineado y produce un card consolidado (D-VAL-8).

**Complejidad / rendimiento.** HL/Brier son O(n log n) por el ordenamiento; binomial/t-test O(n) por segmento. Sin paralelismo v1.

## 8. Casos borde y manejo de errores

- **Faltan artefactos aguas arriba:** `ArtifactNotFoundError` por CT-1 antes de ejecutar (contrato incumplido nombrado).
- **`performance`/`stability` ausentes (modelo no scorecard):** fallback por reúso de evaluadores SDD-11; se audita `source="recomputed"`.
- **Grupo HL/grado con una sola clase o bajo mínimo:** `not_evaluable` auditado con su causa (D-VAL-17: `partition_below_min` cuando la partición entera queda bajo `min_rows_per_group`; `group_below_min` cuando lo hace el menor de los `G` grupos; `degenerate_group` con un grupo vacío o `n_g·p̄_g·(1−p̄_g) = 0`; `non_finite_statistic` cuando el cociente desborda con PD extremas), `statistic` nulo, fuera de `n_tests`. No aborta: si **ninguna** prueba de ninguna familia es evaluable y la estabilidad no trae decisión, el estado consolidado es `not_evaluable`, nunca `pass`.
- **`pd_calibrated` fuera de `(0,1)` o no finita:** `ValidationDataError` ruidoso; SDD-22 no corrige PD aguas arriba.
- **`p̄_g·(1−p̄_g)=0` en HL (grupo degenerado):** grupo `not_evaluable`; nunca división por cero silenciosa.
- **Backtesting activo sin columnas realizadas:** `ValidationConfigError`/`DATO-INSTITUCIONAL` según `fail_on_falta_dato`; no se inventa el realizado.
- **Backtesting activo con `provisioning_ifrs9.detail` sin columnas estimadas:** `ValidationConfigError`/`FALTA-DATO` según `fail_on_falta_dato`. Es el único motivo del blocker que **no** es institucional: lo que falta es una salida del propio motor IFRS 9.
- **`N` pequeño en t-test:** se reporta el estadístico con `not_evaluable` si `N < min` técnico; no se afirma significancia con muestras degeneradas.
- **Semáforo sin anclaje regulatorio:** el `traffic_light` sale de los dos cortes configurables (default institucional 0,05/0,01) y cada fila publica los cortes con que se decidió su color; la card lleva `traffic_light_cuts` cuando corrió el contraste y `null` sin él (D-VAL-15). No hay marca: no hay nada que verificar.
- **Índices no alineables:** `ValidationDataError`; no se hace merge ambiguo.

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen test, partición/grado/segmento, estadístico, umbral, valor observado y verdicto.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno en v1. `ValidationStep.execute` recibe `rng` por contrato y hace `del rng`. (No hay bootstrap en v1; intervalos por remuestreo → D-VAL abierta.)
- **Determinismo esperado.** `(calibrated_pd_frame + labels + performance/stability metrics + ifrs9.detail + config_hash + uv.lock) → tests, p-valores, semáforos y card idénticos`.
- **Copias defensivas.** Todo DataFrame de entrada se copia con `deep=True`; nunca se mutan artefactos aguas arriba.
- **Orden estable.** Particiones `desarrollo`/`holdout`/`oot`; grupos HL por deciles con desempate por índice estable; grados en orden declarado; parámetros de backtesting `pd`/`lgd`/`ead`.
- **Normalización numérica.** Publicar `-0.0` como `0.0`; floats finitos salvo estados `not_evaluable` (representados por `None`, nunca `NaN`/`inf`). Si algún módulo emite hashes auxiliares para goldens, usar endianness explícito (`astype("<u8")`) y nunca `hash()` builtin.
- **Audit trail (`log_decision`).** Registrar:
  - cada test de calibración fallado (HL/binomial/Brier) con `regla`, `umbral`(α), `valor`(p/estadístico), `accion`;
  - cada Hosmer-Lemeshow sin veredicto (`calibration_hl_not_evaluable`; una regla, cuatro causas; D-VAL-17) con `umbral={min_rows, n_groups}` y `valor={partition, n, min_group_size, reason}`, leído de la misma lista que publica la card;
  - cada grado que cruza banda del semáforo (verde→ámbar→rojo);
  - cada backtest fallado (t-test/binomial) por parámetro/segmento;
  - PSI consumido que cae en `review`/`redevelop`;
  - `source="recomputed"` cuando se usó el fallback de discriminación;
  - cada `FALTA-DATO` gatillado (convención de test no verificada).
- **Card / report.** `ValidationCardSection` permite reconstruir familias corridas, α usado, nº de tests/fallos, semáforos, `falta_dato` y versiones de dependencias.
- **Lineage.** SDD-22 no completa `data_hash` ni `config_hash`; su contribución son config computacional, versiones, resultados estructurados y decisiones auditadas.

Convenciones obligatorias de implementación: `import pandera.pandas as pa`; **prohibido `eval`/`df.eval`**; `mypy --strict`; ruff con regla `D` y docstrings en español; identificadores/API en inglés técnico; tests con `filterwarnings=["error"]`; **cobertura 100%** del paquete.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymError`, `MissingDependencyError`, `Registry`.
- SDD-05: config Pydantic, hooks diferidos, `config_hash`, naming y UI metadata.
- SDD-02 (`data`): `frame`, `labels` (target, grado, columnas realizadas).
- SDD-10 (`calibration`): `calibrated_pd_frame`.
- SDD-11 (`performance`+`stability`): `discriminant_metrics`, `stability_metrics`, `psi_table`, y **reúso** de `PerformanceEvaluator`/`StabilityEvaluator`.
- SDD-16 (`provisioning/ifrs9`): `detail`, `staging` (PD/LGD/EAD estimados).
- SDD-26 (`report`) / SDD-03 (`governance`): consumidores del `card`/`metric_sections`.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | `>=2.0` | BSD-3 ✅ | DataFrames, groupby, tablas | base |
| numpy | `>=1.22` | BSD ✅ | arrays, cuantiles, finitud, normalización | base |
| pandera | `>=0.24` | MIT ✅ | schemas I/O con `import pandera.pandas as pa` | base |
| scipy | `>=1.10` | BSD-3 ✅ | `stats.chi2`, `binomtest`, `beta`, `t`/`ttest` | extra (import perezoso) |
| scikit-learn | `>=1.6`, `<1.8` | BSD-3 ✅ | sólo vía reúso de `PerformanceEvaluator` (fallback) | extra `[scoring]`, import perezoso |

**Núcleo liviano.** `nikodym.core` no importa `validation`, scipy ni sklearn. `import nikodym.validation` registra config/step **sin** importar scipy/sklearn en top-level; el import de los tests estadísticos ocurre dentro de `execute`/evaluators y levanta `MissingDependencyError("instale nikodym[...]")` si falta el extra. **D-VAL-10**: nombre del extra (`[validation]` propio vs reúso de `[scoring]`) — recomendación reúso `[scoring]` (ya arrastra scipy/sklearn).

**Normativa.** No hay dependencia de tablas CMF numéricas. La evidencia regulatoria es metodológica (calibración, backtesting) con fuentes ECB/BCBS/estadística estándar citadas en §3/§12.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **Golden Hosmer-Lemeshow.** Fixture pequeño con `O_g`, `n_g`, `p̄_g` conocidos; verificar `HL`, `gl=G−2` y p-valor `chi2.sf` con valor de oro calculado a mano.
- **Golden Brier.** Vector `(p_i, y_i)` conocido; verificar `(1/N)Σ(p−y)²`.
- **Golden binomial/Jeffreys.** Grado con `N`, `p̂`, `D` conocidos; verificar p-valor `binomtest` unilateral y la posterior `Beta(D+½, N−D+½)` de Jeffreys; caso `D=0` (Jeffreys se comporta, binomial degenerado documentado).
- **Golden t-test (LGD/EAD).** Vectores realizado/estimado conocidos; verificar `T = √N·ē/s`, p-valor unilateral y verdicto.
- **Semáforo.** Verificar mapeo `p ≥ green_alpha → green`, `red_alpha ≤ p < green_alpha → amber`, `p < red_alpha → red`, y monotonía.
- **Reúso, no duplicación (discriminación).** Con `("performance","discriminant_metrics")` presente, `validation.discrimination` **iguala** esos valores (`source="performance_artifact"`); sin él, el fallback por `PerformanceEvaluator` produce el mismo número (`source="recomputed"`). Test AST: `validation` no reimplementa `roc_auc_score`/KS/Gini.
- **Reúso, no duplicación (estabilidad).** `validation.stability` refleja `("stability","stability_metrics")`; test AST: no reimplementa PSI.
- **Cierre del DAG.** `ValidationStep.from_config` compone los `requires` exactos de §6; falta uno → `ArtifactNotFoundError`. `provides` publica las seis claves.
- **No mutación.** Snapshots profundos de `calibrated_pd_frame`, `labels`, `ifrs9.detail`, artefactos de SDD-11 permanecen iguales.
- **Casos borde.** Grupo/grado bajo mínimo o de una clase → `not_evaluable`; backtesting sin columnas realizadas → error/`DATO-INSTITUCIONAL`; backtesting con `detail` sin columnas estimadas → error/`FALTA-DATO`; PD fuera de `(0,1)` → error.
- **Audit trail.** Tests fallados y bandas cruzadas emiten exactamente los `AuditEvent(kind="decision")` esperados con `regla`, `umbral`, `valor`, `accion`.
- **Config.** Round-trip YAML de `ValidationConfig`; cambiar deciles, α, bandas del semáforo, test de PD o familias cambia `config_hash`; `validation ∉ INFRA_SECTIONS`.
- **Pandera.** Validar schemas con `import pandera.pandas as pa`.
- **Seguridad.** AST sin `eval`/`df.eval`/`DataFrame.query` para reglas de tests o bandas.
- **Reproducibilidad.** Dos corridas con mismos artefactos/config producen tablas bit-idénticas; `-0.0 → 0.0`; nunca `NaN`/`inf`.
- **Import liviano.** `import nikodym.core` no importa `nikodym.validation`, scipy ni sklearn; importar `validation` no importa scipy/sklearn hasta ejecutar tests.
- **Tooling.** Suite bajo `filterwarnings=["error"]`; `mypy --strict`; ruff regla `D`; **cobertura 100%** del paquete y goldens numéricos.

Fixtures: `validation_calibration_small.parquet` (PD, target, grado, partición), `ifrs9_detail` sintético con realizados, `discriminant_metrics`/`stability_metrics` sintéticos, `ValidationConfig` mínimo/completo, `InMemoryAuditSink`.

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Duplicar métricas de SDD-11 y divergir numéricamente.** Mitigación: consumir el artefacto canónico; fallback por **reúso** del evaluador, nunca reimplementación (D-VAL-1/2, tests AST).
- **Inventar umbrales regulatorios.** Mitigación: HL/Brier son estadística estándar; el semáforo es un default institucional configurable y publicado con cada fila, jamás hardcodeado como norma; las convenciones del BCE están cotejadas (abajo).
- **Backtesting sin panel longitudinal.** Mitigación: v1 soporta backtesting de cohorte única sobre realizados declarados; el panel multi-fecha se difiere a la capa longitudinal (CT-3, D-VAL-9), documentado, no simulado.
- **Semáforo mal fundado.** Mitigación: no portar el traffic-light de VaR (Basilea 1996) a PD; verificado que no hay mapeo posible (zonas discretas sobre un conteo, dependientes de `N`), y la prosa ya no lo atribuye.
- **Muestras pequeñas.** Mitigación: estados `not_evaluable` auditados, no p-valores engañosos.

**Fuentes verificadas / citas.**
- **Hosmer-Lemeshow:** Hosmer, D.W. & Lemeshow, S., *Applied Logistic Regression* (Wiley). Estadístico `Σ(O−E)²/E` por deciles, **χ² con `G−2` gl** (verificado: `G=10` → 8 gl). Definición estadística estándar confirmada 2026-07-03.
- **Brier score:** Brier, G.W. (1950), *Verification of forecasts expressed in terms of probability*, Monthly Weather Review 78(1):1–3.
- **Test binomial por grado (PD):** BCBS Working Paper No. 14, *Studies on the Validation of Internal Rating Systems* (2005).
- **Jeffreys (PD) + t-test (LGD/CCF/EAD):** ECB, *Instructions for reporting the validation results of internal models — credit risk* (feb 2019). URL oficial: `https://www.bankingsupervision.europa.eu/activities/internal_models/shared/pdf/instructions_validation_reporting_credit_risk.en.pdf`. Confirmado 2026-07-03: Jeffreys test para *predictive ability* de PD; t-test para LGD y CCF. **Verificado por render y por las plantillas oficiales el 2026-09-13** (tabla del cotejo, abajo): forma, ponderación, orientación y distribución coinciden con el motor.
- **Traffic-light (concepto):** BCBS, *Supervisory framework for the use of "backtesting" in conjunction with the internal models approach to market risk capital requirements* (1996) — origen del semáforo verde/amarillo/rojo; **no aplicable** a la calibración de PD (verificado: zonas discretas sobre el conteo de excepciones de VaR; tabla del cotejo, abajo).
- **Discriminación / PSI:** ESPEC §5.2/§5.7; SDD-11 §3 (reúso).
- **CMF:** CNC B-1 exige validación y backtesting de metodologías internas, sin fijar umbrales numéricos (consistente con SDD-11 §2/§12).
- **_CONTRATOS-TRANSVERSALES.md:** CT-1 (`requires`/`provides`) y CT-2 (`metric_sections`).

**Cotejo doble y trazado de las convenciones del motor (D-VAL-18; sustituye al bloque «`FALTA-DATO` a resolver por verificación de render» que este SDD llevó desde el Borrador).** Todo se descargó de la URL oficial el 2026-09-13 y se verificó por dos vías independientes: extracción de texto (`pypdf`) del PDF oficial y render de la página a PNG (`pymupdf 1.28.2`, zoom 2×) leído visualmente; para el BCE, además, las fórmulas de Excel de sus plantillas oficiales de reporte. Verificador: Claude Code, sesión S12; revisión adversarial de Codex sobre la enmienda (ocho pasadas, anotadas en el `HANDOFF` privado). Regla para los cotejos siguientes: toda convención del motor que no sea normativa local (las de CMF tienen manifiesto propio, D-COT/D-FTE) se registra aquí con este formato mínimo —fuente, URL oficial, sha256, página/sección, método, verificador, fecha—; sin ese registro, la convención sigue marcada.

| # | Fuente | URL oficial | sha256 del archivo descargado | Qué se leyó (página del PDF · sección) | Resultado |
|---|---|---|---|---|---|
| F1 | BCE, *Instructions for reporting the validation results of internal models — IRB Pillar I models for credit risk*, febrero 2019 (70 pp.; metadata `creationDate 2019-02-28`, `modDate 2019-03-05`) | `https://www.bankingsupervision.europa.eu/activities/internal_models/shared/pdf/instructions_validation_reporting_credit_risk.en.pdf` (enlazado desde `…/activities/internal_models/omm/html/index.en.html`; no existe versión posterior) | `f0bef87b1c636b8dc493e0d8e8b0690a5660a0663086ea6f676ccae2a7685d01` | p. 20-21 (impresas; 21-22 del PDF) · §2.5.3.1 «PD back-testing using a Jeffreys test»; p. 31 (impresa; 32 del PDF) · §2.6.2.1 «LGD back-testing using a t-test»; p. 53 (impresa; 54 del PDF) · §2.9.3.1 (CCF); p. 55 (impresa; 56 del PDF) · §2.9.3.2 (EAD); p. 40-41 · §2.7.2.1 (ELBE, bilateral) | Jeffreys y t-test **coinciden** con el motor (§3.2/§3.4); errata del `1/R` en CCF; ningún corte de semáforo |
| F2 | BCE, plantillas oficiales de reporte (ZIP, 6 libros `.xlsx`, 2020-11-24 … 2021-03-16) | `https://www.bankingsupervision.europa.eu/banking/tasks/internal_models/shared/pdf/templates_validation_reporting_credit_risk.zip` | `68a86250453166c6dde3f0e45d8d2c7cd44bde0b73f575808f3786a77119e5fa` | `LEICode_PD_…xlsx` hoja `3.0`, col. N (`BETA.DIST(E,G+0.5,F−G+0.5,TRUE)` con E = PD media, F = N, G = D) y col. O (tolerancia 10⁻⁵); `LEICode_LGD_…xlsx` hoja `2.0` col. AI (`1−T.DIST(SQRT(E)*(H−G)/SQRT(U),E−1,TRUE)` con H/G promedios *number-weighted*); `LEICode_CCF_…xlsx` hojas `3.1` col. AI y `3.2` fila 12 | **Coinciden** con el motor; confirma la errata de F1 §2.9.3.1 |
| F3 | BCBS, *Supervisory framework for the use of "backtesting" in conjunction with the internal models approach to market risk capital requirements*, enero 1996 (15 pp.) | `https://www.bis.org/publications/199601-standards-supervisory-framework-use-backtesting-conjunction-internal-models-approach-market-risk-capital.pdf` (landing `https://www.bis.org/publ/bcbs22.htm`) | `e3dd0e08100ad19dd88f0305cf25c0af5384b5272f2e72aa9c10daa79fd73f28` | p. 7-8 (impresas) · (c)-(f) definición de zonas; p. 15 del PDF · Tabla 2 | Zonas discretas e inclusivas sobre el conteo de excepciones de VaR, definidas por `P(X ≤ k) ≥ 95 %` (amarilla, k = 5 con N = 250) y `≥ 99,99 %` (roja, k = 10); colas superiores en la frontera `P(X ≥ 5) = 0,1078` y `P(X ≥ 10) = 0,00025`, dependientes de `N`; **no aplica** a la calibración de PD y no equivale a ningún corte fijo de p-valor, menos aún a 0,05/0,01 |
| F4 | BCBS, Working Paper No. 14, *Studies on the Validation of Internal Rating Systems* (revised), mayo 2005 (120 pp.) | `https://www.bis.org/publications/studies-validation-internal-rating-systems-revised.pdf` (landing `https://www.bis.org/publ/bcbs_wp14.htm`) | `49cfd1cea68f7e7491f34d97b9660dfb4d4a0b23041868012c835728d9358188` | p. 47 (impresa; 55 del PDF) · «Binomial test»; p. 34-35 (impresas; 42-43 del PDF) · «traffic lights approach» (Blochwitz, Hohl y Wehn 2003) | Binomial **coincide** con el motor; el traffic lights de WP14 es multi-período, cuatro colores, otra herramienta: no ancla el semáforo por p-valor |

Lo que **no** se pudo verificar y se declara: el texto de Hosmer & Lemeshow (*Applied Logistic Regression*) no está en línea; el estadístico y los `G − 2` gl ya estaban confirmados arriba (2026-07-03). La regla de «mínimo por grupo» de D-VAL-17 es una elección metodológica del motor, no una prescripción de fuente.

## Decisiones para revisión de Cami

> Ninguna bloquea el diseño; se proponen defaults defendibles. Sólo las revisa Cami al final.

- **D-VAL-1 — Discriminación: reúso vs recálculo.** *Recomendación:* **consumir** `("performance","discriminant_metrics")` como resultado canónico y **reúsar** `PerformanceEvaluator` (SDD-11) sólo en el fallback para modelos sin `performance`. **Nunca reimplementar** AUC/KS/Gini. Evita divergencia numérica y cumple DRY.
- **D-VAL-2 — Estabilidad: reúso vs recálculo.** *Recomendación:* **consumir** `("stability","stability_metrics")`/`psi_table`; fallback por reúso de `StabilityEvaluator`. No reimplementar PSI.
- **D-VAL-3 — Nº de grupos Hosmer-Lemeshow.** *Recomendación:* `G=10` deciles (convención estándar) → `G−2=8` gl. Configurable `5..20`; agrupación alternativa por bandas fijas reservada.
- **D-VAL-4 — Nivel de significancia.** *Recomendación:* `α=0.05` (HL bilateral; binomial/t-test unilateral hacia subestimación). Configurable.
- **D-VAL-5 — Bandas del semáforo.** *Recomendación (default institucional):* verde `p ≥ 0.05`, ámbar `0.01 ≤ p < 0.05`, rojo `p < 0.01`, sobre el p-valor del test por grado. **Cerrada con D-VAL-15 (2026-09-14):** default institucional **persistido en el resultado**, sin marca; verificado que no existe corte regulatorio (F1, F3, F4 del cotejo de §12).
- **D-VAL-6 — Test de PD (binomial vs Jeffreys).** *Recomendación:* **Jeffreys** por defecto (alineado con ECB feb 2019, robusto con `D=0`); `binomial` (BCBS WP14) como alternativa. El t-test se reserva a LGD/EAD (spec).
- **D-VAL-7 — Convención del t-test LGD/EAD.** *Recomendación:* t-test pareado sobre `e_i = realizado − estimado`, unilateral (subestimación). **Confirmada con D-VAL-14 (2026-09-14):** pareado simple, sin ponderación por exposición, Student con `N − 1` gl; `one_sided=False` es la convención bilateral del ELBE, no una desviación.
- **D-VAL-8 — Un Step vs Steps por familia.** *Recomendación:* **un** `ValidationStep` con toggles `families`; comparte el frame alineado y consolida un card. Steps separados aumentarían superficie sin beneficio.
- **D-VAL-9 — Fuente y ventana del realizado (backtesting).** *Recomendación:* v1 = backtesting de **cohorte única** desde columnas realizadas declaradas en `data.frame`; el **panel longitudinal multi-fecha** (SICR dinámico, migraciones) se difiere a la capa de datos longitudinal (CT-3, F4/F5). Documentado, no simulado.
- **D-VAL-10 — Extra de empaquetado.** *Recomendación:* reúsar el extra `[scoring]` (ya arrastra scipy/sklearn) en vez de crear `[validation]`. Confirmar al cablear B22.1.
- **D-VAL-11 — Alcance por modelo.** *Recomendación:* discriminación/calibración/estabilidad sobre el scorecard transversal por defecto; **backtesting IFRS 9 opt-in** (exige artefactos F4 + realizados). "Ejecutable sobre cualquier modelo" = las familias aplicables corren según artefactos presentes, no todas sobre todo modelo.
- **D-VAL-12 — Cobertura 100% del paquete.** *Recomendación:* tratar `nikodym.validation` como código sensible (evidencia regulatoria) y exigir **cobertura 100%** del paquete completo, no sólo del subconjunto declarado regulatorio.
