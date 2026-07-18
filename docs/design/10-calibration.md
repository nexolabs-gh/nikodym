# SDD-10 — `calibration` (anclaje de PD a tasa central)

| Campo | Valor |
|---|---|
| **SDD** | 10 |
| **Módulo** | `nikodym.calibration` |
| **Dominio** | Scoring |
| **Fase** | F1 |
| **Tanda de producción** | T2 (Scoring) |
| **Estado** | ✅ Implementado; pipeline F1 estable |
| **Depende de** | SDD-08 (`model`) |
| **Lo consumen** | SDD-11 (`performance` + `stability`), SDD-15 (`provisioning/cmf`), SDD-16 (`provisioning/ifrs9`), SDD-17 (`provisioning`), SDD-22 (`validation`), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (redacción SDD-10 para T2) / 2026-06-28 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `calibration` ajusta la PD cruda de la logística de SDD-08 a una **tasa central / PD objetivo** definida por negocio, historia o normativa, preservando el ranking del modelo cuando el método elegido lo permite.

**Responsabilidad única (qué SÍ hace).**
- Consume `model.raw_pd_frame` con las columnas reales `partition`, `target`, `linear_predictor` y `pd_raw`.
- Consume metadatos de `model` (`estimator`, `coefficients`, `final_features`, `final_woe_columns`) para trazabilidad, card y validación de contrato; la calibración default no reestima coeficientes `β`.
- Ajusta parámetros de calibración **solo con la partición Desarrollo**.
- Aplica la calibración a Desarrollo/Holdout/OOT con parámetros fijos, sin usar el target de Holdout/OOT.
- Publica una PD calibrada por observación (`calibrated_pd_frame`) y parámetros auditables (`CalibrationParameters`).
- Aporta el sub-config **`CalibrationConfig`** (sección `calibration` de `NikodymConfig`), computacional y por tanto incluido en el `config_hash`.
- Registra con `log_decision` el método, ancla, tasa objetivo, población de ajuste, shift/slope aprendido, tolerancia alcanzada y cualquier pérdida de ranking estricto.
- Expone `CalibrationCardSection` para model card / reporte, con `metric_sections` como puerta CT-2.

**Frontera dura de responsabilidad (qué NO hace, y quién lo hace).**
- **No ajusta ni selecciona el modelo logístico.** `model` (SDD-08) decide `β`, `α`, stepwise, signos, p-values e IV-contribution.
- **No genera puntos ni scorecard.** `scorecard` (SDD-09) convierte log-odds a puntos; `calibration` ajusta probabilidades.
- **No mide discriminación, estabilidad ni performance formal.** SDD-11 consume `pd_calibrated` y calcula KS/Gini/AUC, PSI, tabla de rendimiento, calibración observada y estabilidad multi-partición.
- **No calcula matrices regulatorias CMF ni provisiones.** SDD-15 usa matrices PI/PDI/PE CMF; SDD-16/17 usan PD calibrada como insumo de ECL/provisión cuando corresponda.
- **No inventa una tasa central exógena del banco.** Por default estima el ancla TTC como long-run average del target en Desarrollo; si la institución trae una tasa de negocio/histórica/regulatoria, entra explícitamente por config.
- **No convierte una PD TTC a PIT macroeconómica de IFRS 9.** La transformación PIT/TTC con Vasicek, term-structure y escenarios vive en SDD-16/18/20. SDD-10 solo ancla la PD transversal de scorecard.
- **No calcula reason codes ni SHAP.** SDD-14 explica el modelo; `calibration` solo publica cómo cambió el nivel de PD.
- **No muta artefactos aguas arriba.** Lee `model` y publica copias defensivas bajo `"calibration"`.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Scoring (F1/T2). Corre después de `model`; en el pipeline canónico se ubica después de `scorecard` para que el score visible y la PD calibrada queden ambos disponibles antes de performance/reporte.
- **Quién lo invoca:** `Study.run()` como sección `calibration` de `NikodymConfig` (orden canónico propuesto: `data → eda → binning → selection → model → scorecard → calibration → performance → report`).
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `AuditableMixin`, excepciones, bases sklearn-like), artefactos de `model`, pandas/numpy y, según método, scipy/sklearn con import perezoso.

```
data ─► binning ─► selection ─► model ─► scorecard ─► calibration ─► performance/report/provisioning
                                    η, PD cruda   puntos       PD calibrada
```

**Interacción con `Study` y config declarativo.** `CalibrationStep` será un `Step` nativo registrado con `@register("standard", domain="calibration")`. Declara `requires`/`provides` (CT-1) y `execute(study, rng)`: lee artefactos publicados por `model`, ajusta el calibrador en Desarrollo, transforma todas las filas modelables y escribe sus artefactos bajo `"calibration"`. El `rng` se recibe por contrato homogéneo de `Step`; v1 es determinista y debe hacer `del rng`.

**Estado del código actual que este SDD debe respetar.**
- `src/nikodym/model/step.py` publica `("model", "raw_pd_frame")` con `partition`, `target`, `linear_predictor`, `pd_raw`, además de `estimator`, `coefficients`, `final_features`, `final_woe_columns`.
- `src/nikodym/model/results.py` ya expone `ModelCardSection.metric_sections` (CT-2), pero **no existe** todavía `CalibrationResult`, `CalibrationCardSection` ni artefactos `"calibration"`.
- `core.config.schema` aún no tiene `_CALIBRATION_CONFIG_CLS`, campo `calibration` ni `_valida_calibration`.
- `core.study` aún no incluye `"calibration"` en `_DOMAIN_MODULES`, `_DOMAIN_CONFIG_CLASSES` ni `_DEFAULT_DOMAIN_ORDER`.

**Frontera con `scorecard`.** SDD-09 escala `η` a puntos (`score`) para operación/reporting. SDD-10 calibra `η`/`pd_raw` a `pd_calibrated`. El default **no calibra el score** ni esconde la calibración dentro del `Offset` de scorecard; la calibración queda como artefacto separado.

**Normativa CMF relevante.**
- `docs/normativa_cmf_parametros.md` §Advertencias y §§1-6 documentan matrices estándar PI/PDI/PE para provisiones CMF; esas tablas **no** son una tasa central universal de scorecard.
- CMF Chile usa matrices fijas de PI/PD para modelos **estándar** como piso prudencial de provisiones. La calibración de SDD-10 aplica a **modelos internos** de scorecard; no se halló texto CMF que prescriba una tasa central concreta para modelos internos, por lo que no se inventa cita CMF.
- En la fuente oficial CMF, CNC Capítulo B-1 Anexo N°1, I y III.2.A/B, las metodologías internas grupales deben estimar riesgo **a través del ciclo**, con medida de largo plazo, al menos 5 años de información histórica e inclusión de un período recesivo cuando aplique; las ponderaciones de PI no deben distorsionar la perspectiva tendencial/largo plazo.
- CNC Capítulo B-1 Anexo N°2 §2.2 exige documentar el procedimiento de calibración cuando la PI se calcula mediante tasas de incumplimiento.
- ESPECIFICACIONES §5.2 ubica “Calibración de PD: anclaje a tendencia central” como paso posterior a scorecard; §5.5 separa PIT/TTC y Vasicek para IFRS 9; §5.7 ubica tests formales de calibración en validación.

## 3. Conceptos y fundamentos

**PD cruda.** SDD-08 publica, por observación modelable:

`η_i = linear_predictor_i = α + Σ_j β_j · WoE_ij`

`pd_raw_i = σ(η_i) = 1 / (1 + exp(-η_i))`

donde `target=1` representa malo/default.

**Tasa central / PD objetivo.** Es el nivel medio de PD que la institución decide usar como ancla de largo plazo, normalmente derivado de historia de defaults, definición de default, horizonte 12m, cartera/segmento y criterio de governance. En CMF internal-methods, el concepto compatible es una PI/tendencia **TTC** de largo plazo; en IFRS 9 puede existir una cadena posterior que transforme TTC a PIT.

**Calibración por offset de intercepto (default).** Se busca un shift `δ` tal que la media de la PD calibrada en Desarrollo iguale la PD objetivo `p*`:

`pd_calibrated_i = σ(η_i + δ)`

`mean_{i∈Dev}(σ(η_i + δ)) = p*`

La función `f(δ)=mean(σ(η_i+δ))` es continua y estrictamente creciente si hay al menos una fila válida, por lo que para `0 < p* < 1` existe solución única finita. Es una transformación monótona estricta de `η`; por tanto:
- preserva exactamente el ranking de `linear_predictor`;
- preserva exactamente Gini/AUC/KS salvo orientación/empates ya existentes;
- cambia solo el nivel medio de PD, no la discriminación.

**Relación con scorecard.** Con la convención SDD-09 `higher_is_lower_risk`, `Score = Offset - Factor·η`. Calibrar por `η + δ` equivale a cambiar el intercepto de la logística, **no** los puntos ni el score publicado. Esto mantiene trazabilidad: score operativo y PD calibrada se reconcilian por la misma `η`.

**Métodos candidatos.**
- `intercept_offset`: ajuste afín del intercepto/log-odds para igualar `target_pd`. Default recomendado (D-CAL-1).
- `platt_scaling`: logística supervisada sobre `linear_predictor`, `logit(pd)=a+bη`, ajustada solo en Desarrollo. Preserva ranking solo si `b>0`; si además se exige tasa central externa, se aplica un offset final sobre `a+bη`.
- `isotonic`: calibración monótona no paramétrica sobre `linear_predictor` o `pd_raw`, ajustada solo en Desarrollo. Puede mejorar calibración empírica local, pero es no estricta y puede colapsar observaciones en empates; no es default regulatorio v1.

**PIT vs TTC.** SDD-10 etiqueta el tipo de ancla (`anchor_kind="through_the_cycle"` o `"point_in_time"`) pero no calcula escenarios macro ni term-structure. Default propuesto: `through_the_cycle`, coherente con la lectura CMF de metodologías internas y con la idea de “tasa central”. Una PD PIT se admite como input explícito si el usuario lo declara, pero la transformación macro queda fuera.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/calibration/config.py
CalibrationMethod = Literal["intercept_offset", "platt_scaling", "isotonic"]
AnchorKind = Literal["through_the_cycle", "point_in_time"]
AnchorSource = Literal[
    "business_input",
    "historical_default_rate",
    "development_observed",
    "external_regulatory",
]

class CalibrationConfig(NikodymBaseConfig): ...

# nikodym/calibration/exceptions.py
class CalibrationError(NikodymError): ...
class CalibrationFitError(CalibrationError): ...
class CalibrationTransformError(CalibrationError): ...
```

```python
# nikodym/calibration/results.py
class CalibrationParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: CalibrationMethod
    target_pd: float
    anchor_kind: AnchorKind
    anchor_source: AnchorSource
    fit_partition: Literal["desarrollo"]
    offset: float | None
    slope: float | None
    intercept: float | None
    isotonic_knots: tuple[tuple[float, float], ...] = ()
    post_offset: float | None
    target_tolerance: float
    achieved_mean_pd_dev: float
    raw_mean_pd_dev: float
    observed_default_rate_dev: float | None
    n_fit: int

class CalibrationCardSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: CalibrationMethod
    target_pd: float
    anchor_kind: AnchorKind
    anchor_source: AnchorSource
    fit_partition: Literal["desarrollo"]
    n_fit: int
    raw_mean_pd_dev: float
    calibrated_mean_pd_dev: float
    observed_default_rate_dev: float | None
    offset: float | None
    slope: float | None
    intercept: float | None
    ranking_preserved: bool
    ties_created: int
    pd_raw_column: str
    pd_calibrated_column: str
    dependency_versions: dict[str, str]
    metric_sections: dict[str, Any] = Field(default_factory=dict)  # CT-2.

class CalibrationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    calibrated_pd_frame: "pandas.DataFrame"
    parameters: CalibrationParameters
    card: CalibrationCardSection
```

```python
# nikodym/calibration/calibrator.py
class PDCalibrator(NikodymTransformer):
    """Calibra PD cruda de una logística a una tasa central."""
    config_cls: ClassVar[type[CalibrationConfig]] = CalibrationConfig

    def __init__(
        self,
        *,
        method: CalibrationMethod = "intercept_offset",
        target_pd: float = 0.05,
        anchor_kind: AnchorKind = "through_the_cycle",
        anchor_source: AnchorSource = "development_observed",
        target_tolerance: float = 1e-12,
        max_abs_offset: float | None = None,
        max_iter: int = 100,
        min_fit_rows: int = 30,
        require_both_classes_for_supervised: bool = True,
        pd_raw_column: str = "pd_raw",
        linear_predictor_column: str = "linear_predictor",
        pd_calibrated_column: str = "pd_calibrated",
        linear_predictor_calibrated_column: str = "linear_predictor_calibrated",
        partition_column: str = "partition",
        target_column: str = "target",
    ) -> None: ...

    @classmethod
    def from_config(cls, cfg: CalibrationConfig) -> "PDCalibrator": ...

    def fit(
        self,
        raw_pd_frame: "pandas.DataFrame",
        *,
        audit: "AuditSink | None" = None,
    ) -> "Self": ...

    def transform(self, raw_pd_frame: "pandas.DataFrame") -> "pandas.DataFrame": ...

    def fit_transform(
        self,
        raw_pd_frame: "pandas.DataFrame",
        *,
        audit: "AuditSink | None" = None,
    ) -> "pandas.DataFrame": ...
```

**Atributos fiteados (sufijo `_`).**
- `method_`, `target_pd_`, `anchor_kind_`, `anchor_source_`.
- `offset_`, `slope_`, `intercept_`, `post_offset_`, según método.
- `parameters_`: `CalibrationParameters`.
- `ranking_preserved_`, `ties_created_`.
- `dependency_versions_`: pandas/numpy/scipy/sklearn según método.

```python
# nikodym/calibration/step.py
@register("standard", domain="calibration")
class CalibrationStep(AuditableMixin):
    name: str = "calibration"
    requires: tuple[ArtifactKey, ...] = (
        ("model", "estimator"),
        ("model", "final_features"),
        ("model", "final_woe_columns"),
        ("model", "coefficients"),
        ("model", "raw_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("calibration", "calibrated_pd_frame"),
        ("calibration", "parameters"),
        ("calibration", "result"),
        ("calibration", "card"),
    )
    @classmethod
    def from_config(cls, cfg: CalibrationConfig) -> "CalibrationStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "CalibrationResult": ...
```

**Artefactos que `CalibrationStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"calibrated_pd_frame"` | `pandas.DataFrame` | índice original modelable + `partition`, `target`, `linear_predictor`, `pd_raw`, `linear_predictor_calibrated`, `pd_calibrated` |
| `"parameters"` | `CalibrationParameters` | método, ancla, offset/slope/intercept, tolerancia y métricas de ajuste |
| `"result"` | `CalibrationResult` | contenedor agregado |
| `"card"` | `CalibrationCardSection` | resumen para governance/report |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning", "selection", "model", "scorecard", "calibration"])
pd_cal = study.artifacts.get("calibration", "calibrated_pd_frame")
params = study.artifacts.get("calibration", "parameters")
```

## 5. Configuración (schema Pydantic)

`CalibrationConfig` es el sub-config de la sección `calibration` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig` (`extra="forbid"`, `frozen=True`), campos con `title`/`description`, rangos `gt/lt/ge/le`, `Literal` en categóricos y metadatos `ui_*`. **No es infraestructura** (`calibration ∉ INFRA_SECTIONS`): cambiar método, `target_pd`, ancla o tolerancia cambia el `config_hash`.

```python
# nikodym/calibration/config.py
from typing import Literal
from pydantic import Field, model_validator
from nikodym.core.config import NikodymBaseConfig

class CalibrationConfig(NikodymBaseConfig):
    type: Literal["standard"] = Field(default="standard")
    method: CalibrationMethod = Field(default="intercept_offset", title="Método de calibración")
    target_pd: float = Field(
        default=0.05,
        gt=0.0,
        lt=1.0,
        title="PD objetivo",
        description=(
            "Placeholder ilustrativo. No se usa cuando "
            "anchor_source='development_observed'."
        ),
    )
    anchor_kind: AnchorKind = Field(default="through_the_cycle", title="Tipo de ancla")
    anchor_source: AnchorSource = Field(
        default="development_observed",
        title="Fuente de la ancla",
    )
    fit_partition: Literal["desarrollo"] = Field(default="desarrollo", title="Partición de ajuste")
    target_tolerance: float = Field(default=1e-12, gt=0.0, title="Tolerancia de media PD")
    max_abs_offset: float | None = Field(default=None, title="Máximo offset absoluto")
    max_iter: int = Field(default=100, ge=1, title="Iteraciones máximas del solver")
    min_fit_rows: int = Field(default=30, ge=1, title="Mínimo de filas de Desarrollo")
    require_both_classes_for_supervised: bool = Field(
        default=True, title="Exigir ambas clases para Platt/isotónica")
    pd_raw_column: str = Field(default="pd_raw", title="Columna PD cruda")
    linear_predictor_column: str = Field(default="linear_predictor", title="Columna logit crudo")
    pd_calibrated_column: str = Field(default="pd_calibrated", title="Columna PD calibrada")
    linear_predictor_calibrated_column: str = Field(
        default="linear_predictor_calibrated", title="Columna logit calibrado")
    partition_column: str = Field(default="partition", title="Columna partición")
    target_column: str = Field(default="target", title="Columna target")
```

**Validaciones de config.**
- `0 < target_pd < 1`; no se admiten `0`, `1`, `NaN`, `inf` ni bool.
- `method="intercept_offset"` admite `anchor_source` externo o `development_observed`; si `development_observed`, `target_pd` puede ser normalizado desde Dev en `fit`, pero el valor final queda materializado en `parameters`.
- `method in {"platt_scaling", "isotonic"}` exige target de Desarrollo 0/1 con ambas clases si `require_both_classes_for_supervised=True`.
- `max_abs_offset=None` conserva el comportamiento audit-only; si se informa, debe ser finito y mayor que 0.
- Columnas de entrada/salida no pueden ser vacías ni colisionar entre sí.
- `fit_partition` queda fijado a `"desarrollo"` en v1; no se parametriza para evitar leakage.
- `anchor_kind="point_in_time"` es permitido solo si `anchor_source` no es `"external_regulatory"` CMF estándar, salvo override explícito futuro; default TTC.

**Defaults defendibles.**
- `method="intercept_offset"`: preserva ranking, es determinista, auditable y coincide con la lógica log-odds de la scorecard.
- `anchor_source="development_observed"`: estima la tasa central TTC como long-run average del target de Desarrollo; fundamento Basel/CRR Art.180 + EBA GL 2017/16 (“PDs from long-run averages of one-year default rates”).
- `target_pd=0.05`: **placeholder ilustrativo**, no normativo. Con `anchor_source="development_observed"` no se usa; solo aplica cuando `anchor_source ∈ {"business_input", "historical_default_rate", "external_regulatory"}`.
- `anchor_kind="through_the_cycle"`: coherente con tasa central y con CMF internal-methods; IFRS 9 PIT se resuelve aguas abajo.
- `target_tolerance=1e-12`: suficientemente estricta para goldens y reproducibilidad en float64.
- `max_abs_offset=None`: por default audita offsets extremos sin fallar; `max_abs_offset>0` activa un guard hard.
- `min_fit_rows=30`: guard técnico mínimo; la suficiencia estadística real se evalúa en SDD-11/22.

**Hook diferido en `core.config.schema`.** F1 debe extender el patrón real ya usado por `data`/`eda`/`binning`/`selection`/`model`/`scorecard`:
- declarar `_CALIBRATION_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir `calibration` como campo `Any` en runtime y `CalibrationConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("calibration", mode="before")` con nombre `_valida_calibration`;
- sin `nikodym.calibration` importado, exigir JSON canónico determinista (`json.dumps(..., allow_nan=False)`);
- `nikodym.calibration.__init__` asigna el hook y registra `CalibrationStep`;
- `core.study` agrega `"calibration"` a `_DOMAIN_MODULES`, `_DOMAIN_CONFIG_CLASSES` y `_DEFAULT_DOMAIN_ORDER` inmediatamente después de `"scorecard"`.

## 6. Contratos de datos (I/O)

**Inputs vía `Study` (nombres reales implementados a 2026-06-28).**

Desde `model`:
- `("model", "raw_pd_frame")`: `pandas.DataFrame` con `partition`, `target`, `linear_predictor`, `pd_raw`.
- `("model", "estimator")`: estimador fiteado; se usa para metadata/card y validación estructural, no para re-fit.
- `("model", "coefficients")`: tabla de coeficientes; se conserva como evidencia de qué intercepto/modelo fue calibrado.
- `("model", "final_features")`: `tuple[str, ...]`.
- `("model", "final_woe_columns")`: `tuple[str, ...]`.

**Contratos que NO existen todavía.**
- No existe `("calibration", "calibrated_pd_frame")`, `("calibration", "parameters")`, `CalibrationResult` ni `CalibrationCardSection` en el código actual.
- No existe campo `calibration` en `NikodymConfig`.
- No existe transformador `PDCalibrator`. SDD-10 especifica el contrato para implementarlo.

**Poblaciones.**
- **Fit de calibración:** filas con `partition == "desarrollo"`, `linear_predictor` finito, `pd_raw` finita y, para métodos supervisados, `target ∈ {0,1}`.
- **Transform/aplicación:** filas con `partition ∈ {"desarrollo", "holdout", "oot"}`. El target de HO/OOT puede viajar en el output para evaluación posterior, pero **no se usa** para ajustar parámetros.
- **Fuera de modelo:** si aparece en `raw_pd_frame`, se filtra y se registra `log_decision(regla="calibration_fuera_de_modelo", accion="no_calibrar")`.

**Output `calibrated_pd_frame`.** `pandas.DataFrame`, mismo índice y orden que filas modelables de `model.raw_pd_frame`:

| columna | significado |
|---|---|
| `partition` | partición original |
| `target` | target original, preservado para SDD-11/22 |
| `linear_predictor` | logit crudo `η` publicado por `model` |
| `pd_raw` | PD cruda publicada por `model` |
| `linear_predictor_calibrated` | logit calibrado cuando el método lo define; `NaN` no permitido en métodos logit |
| `pd_calibrated` | PD calibrada final en `(0,1)` |
| `calibration_method` | método aplicado, constante por corrida |
| `anchor_kind` | `"through_the_cycle"` o `"point_in_time"` |

**Invariantes.**
- `raw_pd_frame` debe tener índice único y columnas únicas.
- `linear_predictor` y `pd_raw` deben ser finitos en filas modelables; `0 < pd_raw < 1`.
- `pd_raw` debe ser consistente con `σ(linear_predictor)` dentro de tolerancia razonable; discrepancia material es `CalibrationFitError`.
- Para `intercept_offset`, `mean(pd_calibrated[Dev]) == target_pd` dentro de `target_tolerance`.
- Para `intercept_offset`, el orden de `pd_calibrated` es exactamente el orden de `pd_raw`/`linear_predictor`; empates preexistentes se conservan.
- Para `platt_scaling`, ranking se preserva solo si `slope > 0`; `slope <= 0` falla por defecto.
- Para `isotonic`, la transformación es monótona no decreciente, pero puede crear empates; `ties_created` debe quedar en `parameters` y `card`.
- No muta `model.raw_pd_frame`, `model.coefficients`, `model.estimator`, `model.final_features` ni `model.final_woe_columns`.
- `-0.0` se publica como `0.0` en todos los floats.

## 7. Algoritmos y flujo

**`CalibrationStep.execute(study, rng)` — secuencia canónica.**
1. **Descartar azar.** `del rng`; calibration v1 es determinista.
2. **Leer artefactos.** Validar presencia/tipos de `model.estimator`, `model.final_features`, `model.final_woe_columns`, `model.coefficients`, `model.raw_pd_frame`.
3. **Resolver config.** Leer `study.config.calibration` o fallback del paso standalone.
4. **Copias defensivas.** Trabajar sobre copias profundas de frames/tablas.
5. **Validar contrato de `raw_pd_frame`.** Columnas exactas requeridas, índice único, finitud, `pd_raw ∈ (0,1)`, `pd_raw ≈ σ(linear_predictor)`.
6. **Seleccionar Desarrollo.** `fit_frame = raw_pd_frame[partition == "desarrollo"]`; validar `n >= min_fit_rows`.
7. **Resolver ancla.** Usar `config.target_pd` salvo política explícita `anchor_source="development_observed"`, que calcula `mean(target)` en Desarrollo y lo materializa como `target_pd_`.
8. **Ajustar método.**
   - `intercept_offset`: resolver `δ` para igualar media PD a `target_pd`.
   - `platt_scaling`: ajustar `a+bη` con target de Desarrollo; exigir `b>0`; si `target_pd` externo difiere de la media calibrada, resolver `post_offset`.
   - `isotonic`: ajustar mapping monótono; contar empates creados; si se exige ancla externa, aplicar reanclaje monótono final o fallar si no puede garantizarse.
9. **Aplicar a Dev/HO/OOT.** Transformar todas las filas modelables con parámetros fijos; no leer target fuera de Desarrollo.
10. **Construir DTOs.** `CalibrationParameters`, `CalibrationCardSection`, `CalibrationResult`, con versiones de dependencias.
11. **Registrar auditoría.** Método, ancla, población de ajuste, offset/slope, media antes/después y ranking.
12. **Publicar artefactos.** Escribir `"calibrated_pd_frame"`, `"parameters"`, `"result"`, `"card"` bajo dominio `"calibration"`.

**`PDCalibrator.fit(...)` con `method="intercept_offset"`.**
1. Tomar `η_dev = raw_pd_frame.loc[Dev, linear_predictor_column]`.
2. Definir `g(δ) = mean(expit(η_dev + δ)) - target_pd`.
3. Resolver `g(δ)=0` con método robusto unidimensional (`scipy.optimize.brentq` o bisección propia acotada si se decide evitar scipy aquí).
4. Guardar `offset_=δ`, `slope_=None`, `intercept_=None`.
5. Verificar `abs(mean(expit(η_dev+δ))-target_pd) <= target_tolerance`.

**`PDCalibrator.transform(...)` default.**
1. Validar que el calibrador está fiteado.
2. Copiar `raw_pd_frame`.
3. Calcular `linear_predictor_calibrated = linear_predictor + offset_`.
4. Calcular `pd_calibrated = expit(linear_predictor_calibrated)`.
5. Normalizar floats y devolver solo filas modelables, preservando índice/orden.

**Alternativas descartadas.**
- *Multiplicar `pd_raw` por un factor y truncar en 1:* descartado; no preserva log-odds, puede distorsionar ranking cerca de clipping y no es natural para logística.
- *Reestimar el intercepto y coeficientes `β` en calibración:* descartado; eso es re-fit de `model` y mezclaría responsabilidades.
- *Usar Holdout/OOT para elegir el offset:* descartado por leakage.
- *Calibrar el `score` de SDD-09 como default:* descartado; el score es una escala operativa derivada de `η`. Calibrar `η` es más directo, auditable y no depende de `PDO`/redondeo.
- *Isotónica como default:* descartado; aunque monótona, puede crear empates y cambiar la granularidad del ranking, lo que complica auditoría y performance.
- *Tomar matrices PI CMF estándar como tasa central de scorecard:* descartado; esas matrices son motores de provisión estándar por cartera/categoría, no ancla universal del modelo interno.

**Complejidad / rendimiento.** `intercept_offset` es O(n_dev × iteraciones) para el fit y O(n_total) para transformar. `platt_scaling` e `isotonic` dependen de sklearn pero siguen siendo livianos para una columna.

## 8. Casos borde y manejo de errores

- **Faltan artefactos de `model`:** `ArtifactNotFoundError` por CT-1 antes de ejecutar, o `CalibrationFitError` si el artefacto existe con tipo/shape inválido.
- **`raw_pd_frame` sin columnas requeridas:** `CalibrationFitError` listando columnas faltantes.
- **Índice o columnas duplicadas:** `CalibrationFitError`; no se arriesga una unión o evaluación ambigua.
- **Desarrollo vacío o bajo `min_fit_rows`:** `CalibrationFitError`.
- **`target_pd` fuera de `(0,1)` o no finito:** `ConfigError`/validación Pydantic.
- **`pd_raw` fuera de `(0,1)` o no finita:** `CalibrationFitError`.
- **`linear_predictor` no finito:** `CalibrationFitError`.
- **`pd_raw` inconsistente con `linear_predictor`:** `CalibrationFitError`; la capa no decide cuál fuente creer.
- **Target de Desarrollo no binario en método supervisado:** `CalibrationFitError`.
- **Desarrollo con una sola clase en Platt/isotónica:** `CalibrationFitError` si `require_both_classes_for_supervised=True`.
- **Solver no converge al offset:** `CalibrationFitError` con `target_pd`, bracket, iteraciones y media alcanzada.
- **Offset extremo:** con `max_abs_offset=None` se publica y se audita; si `abs(offset)`/`abs(post_offset)` excede `max_abs_offset`, falla con `CalibrationOffsetExceededError` y atributos `offset`, `max_abs_offset`, `method`, `partition`.
- **`platt_scaling` con `slope <= 0`:** `CalibrationFitError` por inversión de ranking.
- **`isotonic` crea demasiados empates:** permitido si está configurado, pero `ties_created` se registra; SDD-11 mide impacto.
- **HO/OOT con target missing:** permitido; target no se usa para transformar.
- **Colisión de columnas de salida:** `CalibrationTransformError` salvo política futura explícita de overwrite. Default: no sobrescribir.

Toda excepción propia desciende de `NikodymError`; los mensajes son en español e incluyen regla, método, partición, umbral/config y valor observado.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno en v1. `CalibrationStep.execute(study, rng)` recibe `rng` por contrato y debe hacer `del rng`.
- **Determinismo esperado.** `(data_hash + config_hash + model.raw_pd_frame + uv.lock) → parámetros de calibración y PD calibrada idénticos`.
- **Orden estable.** `calibrated_pd_frame` preserva índice y orden de `model.raw_pd_frame` modelable.
- **Normalización numérica.** Publicar `-0.0` como `0.0`; no usar `hash()` builtin; registrar dependencias.
- **Audit trail (`log_decision`).** Registrar con argumentos keyword-only `regla`, `umbral`, `valor`, `accion`:
  - `calibration_anchor`: `target_pd`, `anchor_kind`, `anchor_source`, `fit_partition`;
  - `calibration_method`: método, `n_fit`, `target_tolerance`;
  - `calibration_offset`: `offset`, `raw_mean_pd_dev`, `calibrated_mean_pd_dev`;
  - `calibration_platt`: `slope`, `intercept`, `post_offset` si aplica;
  - `calibration_isotonic`: nº de knots y `ties_created`;
  - `calibration_ranking`: `ranking_preserved`, empates creados;
  - `calibration_fuera_de_modelo`: filas filtradas por partición.
- **Card / report.** `CalibrationCardSection` debe permitir reconstruir la calibración: método, ancla, fuente, target, población, media antes/después, offset/slope/intercept, ranking y versiones.
- **Lineage.** `calibration` no completa `data_hash` ni `config_hash`; su contribución al lineage son su config computacional, dependencias y decisiones auditadas.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymTransformer`, `MissingDependencyError`, `NikodymError`, `Registry`.
- SDD-05 (convenciones): config Pydantic, hook diferido, `config_hash`, API sklearn-like.
- SDD-08 (`model`): `estimator`, `final_features`, `final_woe_columns`, `coefficients`, `raw_pd_frame`.
- SDD-09 (`scorecard`): frontera conceptual; no es dependencia dura de datos en v1.

**Aguas abajo.**
- SDD-11 (`performance`/`stability`) consume `calibrated_pd_frame` para tests de calibración, tabla de rendimiento y métricas multi-partición.
- SDD-15 (`provisioning/cmf`) puede consumir `pd_calibrated` si se implementan metodologías internas o comparativos; las matrices estándar CMF siguen siendo su propio motor.
- SDD-16/17 (`provisioning/ifrs9`/orquestación) consumen PD calibrada como punto de partida transversal antes de term-structure/PIT/lifetime cuando aplique.
- SDD-22 (`validation`) consume `parameters`, `card` y backtesting realizado-vs-estimado.
- SDD-26 (`report`) consume `calibrated_pd_frame` y `card`.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | según base del proyecto (`>=2.0`) | BSD-3 ✅ | I/O tabular | base |
| numpy | según base del proyecto (`>=1.22`) | BSD ✅ | `expit`/logit vía operaciones numéricas, finitud | base |
| scipy | extra `[scoring]` (`>=1.10`) | BSD ✅ | solver robusto / `special.expit` si se usa | import perezoso |
| scikit-learn | extra `[scoring]` (`>=1.6`, constraint `<1.8`) | BSD-3 ✅ | `LogisticRegression` Platt e `IsotonicRegression` | import perezoso, solo métodos no-default |

**Núcleo liviano.** `nikodym.core` no importa `calibration`. `import nikodym.calibration` registra config/step sin importar pandas/numpy/scipy/sklearn en top-level. `calibration.results` debe usar anotaciones string/`TYPE_CHECKING` para DataFrames y cargar pandas localmente en validators/helpers; `calibration.calibrator` y `calibration.step` cargan pandas/numpy dentro de `fit`/`transform`/`execute`. sklearn/scipy se cargan solo al ejecutar métodos que los requieren y levantan `MissingDependencyError("instale nikodym[scoring]")` si falta el extra.

**Normativa.** No se incorpora dependencia de datos normativos en el paquete `calibration`: la tasa central concreta entra por config. Las tablas PI/PDI/PE de `docs/normativa_cmf_parametros.md` pertenecen a provisiones CMF.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **Golden de offset constante.** Si todos los `η_i` de Desarrollo son `η0`, entonces `offset = logit(target_pd) - η0` y `pd_calibrated == target_pd` para todas las filas. Verificable a mano.
- **Golden de media central.** Dataset pequeño con `η` heterogéneos y `target_pd` conocido; resolver `δ` con una referencia independiente y verificar `mean(pd_calibrated_dev)`.
- **Ranking preservado.** Para `intercept_offset`, dos filas con `η_a < η_b` mantienen `pd_calibrated_a < pd_calibrated_b`; los ranks de `pd_raw` y `pd_calibrated` son idénticos.
- **Anti-leakage.** Cambiar targets de Holdout/OOT no cambia `offset`, `parameters` ni PD calibrada; cambiar solo `η` HO/OOT cambia solo esas predicciones.
- **No mutación.** Snapshots profundos de `model.raw_pd_frame` y `model.coefficients` permanecen iguales.
- **Contrato `Step`.** `CalibrationStep.requires` exige los cinco artefactos reales de `model`; falta uno → `ArtifactNotFoundError`. `provides` publica las cuatro claves de §4.
- **Consistencia `pd_raw`/`linear_predictor`.** Inyectar una discrepancia material levanta `CalibrationFitError`.
- **Platt.** Caso con slope positivo preserva ranking; caso con slope no positivo falla por defecto.
- **Isotónica.** Caso monotónico crea empates conocidos y `ties_created` queda en card/result; SDD-11 evaluará impacto.
- **Config.** Round-trip YAML de `CalibrationConfig`; cambiar `target_pd`, método, `anchor_kind` o tolerancia cambia `config_hash`; `calibration` no está en `INFRA_SECTIONS`.
- **Import liviano.** `import nikodym.core` no importa `nikodym.calibration`; `import nikodym.calibration` no importa sklearn/scipy; usar Platt/isotónica sin extra produce `MissingDependencyError`.
- **DTOs.** Copias defensivas de DataFrames y `metric_sections`; `-0.0→0.0`; `extra="forbid"`.
- **Integración.** Pipeline `data → binning → selection → model → scorecard → calibration` sobre fixture sintético; `calibrated_pd_frame` preserva índice/particiones y SDD-11 puede consumirlo.

Fixtures: `behavior_calibration_small.parquet`, `raw_pd_frame` sintético con `partition/target/linear_predictor/pd_raw`, `CalibrationConfig` mínimo y variantes por método/ancla, `InMemoryAuditSink`.

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Usar un default de tasa central como si fuera normativo.** Mitigación: `target_pd=0.05` se marca explícitamente ilustrativo/R0 y la card publica `anchor_source`.
- **Confundir TTC con PIT.** Mitigación: `anchor_kind` obligatorio en output; IFRS 9 PIT/Vasicek queda aguas abajo.
- **Calibrar con leakage.** Mitigación: `fit_partition="desarrollo"` fijo y tests que alteran HO/OOT.
- **Perder ranking por métodos flexibles.** Mitigación: default `intercept_offset`; Platt exige `slope>0`; isotónica registra empates.
- **Doble conteo con scorecard.** Mitigación: `calibration` usa `linear_predictor`, no `score` ni `Offset` de scorecard.
- **Regulador exige evidencia de tasa central.** Mitigación: `CalibrationCardSection` documenta fuente/ancla/método y SDD-11/22 proveen backtesting/calibración formal.

**Fuentes verificadas / citas.**
- **ESPECIFICACIONES.md** §4 (principios 1 reproducibilidad, 2 auditabilidad, 5 config declarativa, 9 núcleo liviano, 10 calidad, 11 doble verificación), §5.2 (pipeline scorecard; “Calibración de PD: anclaje a tendencia central”), §5.5 (PD 12m/lifetime, PIT/TTC, Vasicek), §5.7 (tests de calibración en validación), §6.3 (`calibration/` = anclaje PD, PIT/TTC).
- **docs/normativa_cmf_parametros.md** Advertencias y §§1-6: matrices estándar CMF PI/PDI/PE y `PE = PI·PDI·Exposición`; no fijan tasa central universal para scorecard.
- **Basel/CRR Art.180 + EBA GL 2017/16:** fundamento prudencial para que las PD provengan de promedios de largo plazo de tasas de default a un año (“PDs from long-run averages of one-year default rates”); se adopta como default TTC de modelos internos vía `development_observed`.
- **CMF oficial:** Compendio de Normas Contables Bancos, versión 2022, Capítulo B-1 Anexo N°1 I, III.2.A y III.2.B: metodologías internas grupales con enfoque “a través del ciclo”, medida de largo plazo, horizonte mínimo de 5 años con período recesivo y PI sin distorsionar perspectiva tendencial/largo plazo. Anexo N°2 §2.2: documentar procedimiento de calibración cuando la PI se calcula mediante tasas de incumplimiento. PDF oficial descargado desde `cmfchile.cl` y verificado localmente con `pdftotext` el 2026-06-28.
- **SDD-08 (`model`)** §1/§4/§6 y código implementado: `raw_pd_frame` real con `partition`, `target`, `linear_predictor`, `pd_raw`; artefactos `estimator`, `coefficients`, `final_features`, `final_woe_columns`.
- **SDD-09 (`scorecard`)** §1/§2/§6: scorecard no calibra PD; `Offset`/`PDO` son escala de puntos.
- **_CONTRATOS-TRANSVERSALES.md** CT-1 (`requires`/`provides`), CT-2 (`metric_sections`), CT-3 (datos transversales vs longitudinales), CT-4 (ensamblado fuera de `core`).

## Decisiones para revisión de Cami

- **D-CAL-1 — Método default.** Recomendación: `method="intercept_offset"`. Ajusta el intercepto/log-odds para igualar la tasa central, preserva ranking exactamente, es determinista y auditable. Platt e isotónica quedan opt-in.
- **D-CAL-2 — Tasa central default (RESUELTA 2026-06-28).** Recomendación de diseño original: `target_pd` es parámetro obligatorio de negocio/normativa en config; el valor `0.05` es solo placeholder ilustrativo para ejemplos/tests, no contrato. Cami debe definir política de ancla por cartera/segmento. **Resolución:** el default de `anchor_source` pasa a `"development_observed"` y la tasa central se estima como long-run average TTC del target en Desarrollo, con fundamento Basel/CRR Art.180 + EBA GL 2017/16 (“PDs from long-run averages of one-year default rates”). `target_pd=0.05` permanece como placeholder explícito y solo aplica si la fuente es `business_input`, `historical_default_rate` o `external_regulatory`. CMF Chile conserva matrices fijas de PD para modelos estándar/piso prudencial de provisiones; esta calibración aplica a modelos internos, y no se halló texto CMF que prescriba una tasa central concreta para ellos.
- **D-CAL-3 — TTC vs PIT.** Recomendación: default `anchor_kind="through_the_cycle"` para SDD-10, por tasa central y lectura CMF. PIT se permite solo como input explícito; transformación macro/Vasicek queda en IFRS 9/forward.
- **D-CAL-4 — Calibrar `linear_predictor`, no `score`.** Recomendación: usar `model.raw_pd_frame.linear_predictor` y publicar `pd_calibrated`. El `score` de SDD-09 es escala operativa y no debe absorber calibración.
- **D-CAL-5 — Artefactos de salida.** Recomendación: publicar `"calibrated_pd_frame"`, `"parameters"`, `"result"`, `"card"` bajo dominio `"calibration"`. Confirmar nombres antes de implementar para evitar churn en SDD-11/26.
- **D-CAL-6 — Métodos supervisados opt-in.** Recomendación: Platt requiere `slope>0`; isotónica permitida pero debe reportar empates. Ninguno desplaza el default offset mientras el objetivo sea preservar ranking regulatorio.
- **D-CAL-7 — Frontera con SDD-11.** Recomendación: SDD-10 solo ancla y reporta medias/tolerancia técnica; Hosmer-Lemeshow, binomial, Brier, traffic-light, deciles, KS/Gini/AUC y PSI viven en SDD-11/22.
- **D-CAL-8 — Frontera con provisiones.** Recomendación: SDD-15/16/17 consumen `pd_calibrated`, pero CMF estándar conserva sus matrices PI/PDI/PE propias; no mezclar calibración de scorecard con motor estándar.
- **D-CAL-9 — Guard de offset extremo (RESUELTA 2026-06-28).** Recomendación inicial: auditar offset extremo sin fallar por defecto. Si Cami quiere una barrera regulatoria dura (`max_abs_offset`), añadirla antes de aprobar SDD-10. **Resolución:** `max_abs_offset: float | None = None` queda implementado como guard opcional. Con `None` se mantiene el default audit-only; con valor positivo finito, `intercept_offset` valida `offset` y Platt/isotónica validan el `post_offset` de reanclaje, fallando con `CalibrationOffsetExceededError` si el umbral se supera.
