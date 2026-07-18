# SDD-09 — `scorecard` (escalamiento log-odds a puntos)

| Campo | Valor |
|---|---|
| **SDD** | 09 |
| **Módulo** | `nikodym.scorecard` |
| **Dominio** | Scoring |
| **Fase** | F1 |
| **Tanda de producción** | T2 (Scoring) |
| **Estado** | ✅ Implementado; pipeline F1 estable |
| **Depende de** | SDD-08 (`model`) |
| **Lo consumen** | SDD-10 (`calibration`), SDD-11 (`performance` + `stability`), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (redacción SDD-09 para T2) / 2026-06-28 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `scorecard` traduce el modelo logístico PD de SDD-08, ajustado sobre variables WoE, a una **scorecard de puntos determinista y auditable**: puntos por atributo/bin y score total por registro.

**Responsabilidad única (qué SÍ hace).**
- Consume los coeficientes finales `β`, el intercepto `α`, las variables finales y las tablas WoE publicadas por `model`/`binning`.
- Calcula `Factor`, `Offset` y la tabla de puntos por atributo/bin usando el escalamiento clásico de scorecards (`PDO`, `target_score`, `target_odds`).
- Publica una tabla auditable de scorecard: una fila por feature/bin con WoE, coeficiente, componente log-odds, puntos crudos y puntos publicados.
- Transforma registros modelables a columnas de puntos (`<feature>__points`) y a un `score` total por registro.
- Preserva la trazabilidad entre `binning.tables`, `model.coefficients`, `model.final_features` y el score por registro.
- Aporta el sub-config **`ScorecardConfig`** (sección `scorecard` de `NikodymConfig`), computacional y por tanto incluido en el `config_hash`.
- Registra con `log_decision` cualquier ajuste no puramente algebraico: redondeo con ajuste residual, clipping, override manual de puntos, WoE/bin no visto o score fuera de rango.

**Frontera dura de responsabilidad (qué NO hace, y quién lo hace).**
- **No re-ajusta el modelo.** Los coeficientes, variables finales, signos, p-values, stepwise e IV-contribution son de SDD-08 (`model`).
- **No aprende bins ni recalcula WoE/IV.** Las tablas WoE y el `woe_column_map` vienen de SDD-06 (`binning`). `scorecard` solo las lee.
- **No selecciona variables.** Las candidatas y seleccionadas son de SDD-07/08; `scorecard` no revive variables descartadas.
- **No calibra PD a una tasa central, PIT/TTC ni tendencia observada.** Eso es SDD-10 (`calibration`). El score puede ser insumo de calibración, pero no cambia probabilidades.
- **No calcula performance formal, KS/Gini/AUC/PSI ni tabla de deciles.** Eso es SDD-11 (`performance` + `stability`). `scorecard` solo garantiza que el score sea una transformación afín del predictor lineal antes de redondeo.
- **No calcula reason codes ni SHAP.** SDD-14 (`explain`) toma la scorecard/ML y produce explicabilidad local. Los puntos por atributo ayudan a explicar, pero no son el contrato de reason codes.
- **No aplica matrices CMF ni IFRS 9/ECL.** SDD-15/16/17 calculan provisiones. Las matrices PI/PDI de `docs/normativa_cmf_parametros.md` son de provisiones, **no** parámetros de scorecard.
- **No muta artefactos aguas arriba.** Lee `model`/`binning` y publica copias defensivas bajo `"scorecard"`.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Scoring (F1/T2). Corre después de `model` y antes de `calibration`, `performance` y `report`.
- **Quién lo invoca:** `Study.run()` como sección `scorecard` de `NikodymConfig` (orden canónico: `data → eda → binning → selection → model → scorecard → calibration → performance → report`). También puede usarse standalone como transformer sklearn-like.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `AuditableMixin`, excepciones, bases sklearn-like), artefactos de `model` y `binning`, y pandas/numpy. No importa `statsmodels` ni re-ejecuta `LogisticPDModel`.

```
data ─► binning ─► selection ─► model ─► scorecard ─► calibration/performance/report
         tablas WoE               β, α       puntos       PD calibrada / métricas / PDF
         woe_frame                PD cruda   score
```

**Interacción con `Study` y config declarativo.** `ScorecardStep` es un `Step` nativo registrado con `@register("standard", domain="scorecard")`. Declara `requires`/`provides` (CT-1) y `execute(study, rng)`: lee artefactos publicados por `model` y `binning`, construye el escalador de puntos, transforma las filas modelables y escribe sus artefactos bajo `"scorecard"`. El `rng` se recibe por contrato homogéneo de `Step`; v1 no usa azar y debe hacer `del rng`.

**Frontera con `model`.** SDD-08 publica la relación:

`η_i = α + Σ_j β_j · WoE_ij = ln(PD_i / (1 - PD_i))`

con `target=1` malo/default y `WoE = ln(%Goods/%Bads)`, por lo que el signo esperado de `β_j` es negativo. `scorecard` no interpreta p-values ni decide si el modelo es defendible; solo convierte esa relación final a puntos.

**Frontera con `calibration`.** `scorecard` transforma log-odds a puntos con una escala de negocio. SDD-10 ajusta la PD a tendencia central y define PIT/TTC; no debe esconder esa calibración dentro del `Offset`. Cambiar `PDO`/`target_score` cambia la escala visible del score, no la PD cruda del modelo.

**Normativa CMF relevante.** La CMF no fija `PDO`, `target_score`, `target_odds`, redondeo ni distribución de intercepto de una scorecard. Exige metodologías documentadas, predictivas, validadas y trazables cuando se usen como componente PI. Los parámetros CMF de `normativa_cmf_parametros.md` pertenecen a motores de provisión estándar (`PE = PI · PDI · Exposición`) y no se copian a esta capa.

## 3. Conceptos y fundamentos

**Modelo logístico de entrada.** SDD-08 entrega un modelo final:

`η_i = α + Σ_j β_j · x_ij`, con `x_ij = WoE_ij`

`η_i` es el log-odds de malo (`ln(PD/(1-PD))`) porque el target del proyecto es `1 = malo/default`.

**Convención WoE.** SDD-06/07 fijan:

`WoE_b = ln(%Goods_b / %Bads_b)`

Un bin más riesgoso tiene WoE menor. Para `target=1` malo, un aumento de WoE reduce la PD y el signo esperado del coeficiente es `β < 0`.

**Dirección del score propuesta.** Default propuesto para F1: **mayor score = menor riesgo**. Es la convención más común para scorecards de crédito y evita que un puntaje alto se interprete como peor cliente. Queda como decisión de Cami (D-SCR-1) porque es una decisión de producto/reporting.

**Escalamiento clásico log-odds → puntos.** ESPECIFICACIONES §5.2 fija el escalamiento de scorecard:

- `Score = Offset + Factor · ln(odds)`
- `Factor = PDO / ln(2)`
- puntos por atributo desde el componente `β_i · WoE_i + α/n`.

Para que el default "mayor score = menor riesgo" sea coherente con la logística de SDD-08, `odds` se interpreta como **odds buenos/malos**:

`ln(odds_good_bad) = ln((1 - PD) / PD) = -η`

Por tanto:

`Factor = PDO / ln(2)`

`Offset = target_score - Factor · ln(target_odds)`

`Score_i = Offset - Factor · η_i`

Si el modelo tiene `n` variables finales y se distribuye el intercepto uniformemente:

`points_{j,b} = Offset/n - Factor · (β_j · WoE_{j,b} + α/n)`

Equivalente:

`Score_i = Σ_j points_{j,bin(i,j)} = Offset - Factor · (α + Σ_j β_j · WoE_{ij})`

Esta es la fórmula operativa de SDD-09. Si Cami decide dirección inversa ("mayor score = mayor riesgo"), se usa la variante `Score_i = Offset + Factor · η_i` y el signo de los puntos cambia de forma coordinada (D-SCR-1).

**PDO.** `PDO` (*Points to Double the Odds*) es la cantidad de puntos necesaria para duplicar los odds definidos por la dirección del score. Con el default `higher_is_lower_risk`, aumentar `PDO` puntos duplica los odds buenos/malos.

**`target_score` y `target_odds`.** `target_score` es el score asignado a una observación cuyo `odds_good_bad == target_odds`. Ejemplo de industria a ratificar: `target_score=600`, `target_odds=50.0` (50:1 buenos/malos), `PDO=20`.

**Monotonía y ranking.** Antes de redondeo, el score es una transformación afín de `η`. Con el default `higher_is_lower_risk`, es monotona decreciente de `PD`/`η` y monotona creciente de los odds buenos/malos. Preserva el ranking como orden total con orientación conocida; SDD-11 debe evaluar discriminación con `risk_score = -score` si quiere el mismo signo positivo de AUC/Gini que `pd_raw`.

**Redondeo.** ESPEC §5.2 no fija si los puntos se publican como float, decimal o entero. El default propuesto es publicar puntos enteros por atributo y conservar columnas crudas (`raw_points`) para auditoría. Esto introduce una diferencia acotada entre `score` redondeado y el score afín exacto; debe medirse en tests y queda como decisión de Cami (D-SCR-3).

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/scorecard/config.py
class ScorecardConfig(NikodymBaseConfig): ...
class PointOverrideConfig(NikodymBaseConfig): ...

# nikodym/scorecard/exceptions.py
class ScorecardError(NikodymError): ...
class ScorecardFitError(ScorecardError): ...
class ScorecardTransformError(ScorecardError): ...
```

```python
# nikodym/scorecard/results.py
ScoreDirection = Literal["higher_is_lower_risk", "higher_is_higher_risk"]
RoundingMethod = Literal["none", "nearest_integer", "floor_integer", "ceil_integer"]

class ScorecardBinPoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    feature: str
    woe_column: str
    bin_label: str
    bin_index: int | None
    woe: float
    beta: float
    intercept_share: float
    raw_points: float
    points: float | int
    rounding_delta: float
    source: Literal["binning_table", "override"]

class ScorecardCardSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    pdo: float
    target_score: float
    target_odds: float
    factor: float
    offset: float
    score_direction: ScoreDirection
    rounding_method: RoundingMethod
    n_variables: int
    score_column: str
    points_columns: tuple[str, ...]
    min_score: float | None
    max_score: float | None
    overrides_count: int
    dependency_versions: dict[str, str]
    metric_sections: dict[str, Any] = Field(default_factory=dict)  # CT-2, vacío en scoring v1.

class ScorecardResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    scorecard: "pandas.DataFrame"
    score: "pandas.DataFrame"
    factor: float
    offset: float
    score_direction: ScoreDirection
    points_columns: tuple[str, ...]
    score_column: str
    card: ScorecardCardSection
```

```python
# nikodym/scorecard/scaler.py
class PointsScaler(NikodymTransformer):
    """Escala componentes log-odds de una logística WoE a puntos de scorecard."""
    config_cls: ClassVar[type[ScorecardConfig]] = ScorecardConfig
    def __init__(
        self,
        *,
        pdo: float = 20.0,
        target_score: float = 600.0,
        target_odds: float = 50.0,
        score_direction: Literal["higher_is_lower_risk", "higher_is_higher_risk"] = "higher_is_lower_risk",
        intercept_allocation: Literal["uniform"] = "uniform",
        rounding_method: Literal["none", "nearest_integer", "floor_integer", "ceil_integer"] = "nearest_integer",
        output_suffix: str = "__points",
        score_column: str = "score",
        min_score: float | None = None,
        max_score: float | None = None,
        clip: bool = False,
        point_overrides: tuple[PointOverrideConfig, ...] = (),
    ) -> None: ...
    @classmethod
    def from_config(cls, cfg: ScorecardConfig) -> "PointsScaler": ...
    def fit(
        self,
        *,
        coefficients: "pandas.DataFrame",
        final_features: tuple[str, ...],
        final_woe_columns: tuple[str, ...],
        binning_tables: Mapping[str, "pandas.DataFrame"],
        woe_column_map: Mapping[str, str],
        audit: "AuditSink | None" = None,
    ) -> "Self": ...
    def transform(self, woe_frame: "pandas.DataFrame") -> "pandas.DataFrame": ...
```

```python
# nikodym/scorecard/transformer.py
class Scorecard(PointsScaler):
    """Transformer sklearn-like que publica puntos por variable y score total."""
    def fit_from_artifacts(
        self,
        *,
        model_result: "ModelResult | None" = None,
        binning_result: "BinningResult | None" = None,
        coefficients: "pandas.DataFrame | None" = None,
        final_features: tuple[str, ...] | None = None,
        final_woe_columns: tuple[str, ...] | None = None,
        binning_tables: Mapping[str, "pandas.DataFrame"] | None = None,
        audit: "AuditSink | None" = None,
    ) -> "Self": ...
```

**Atributos fiteados (sufijo `_`).**
- `factor_`, `offset_`, `pdo_`, `target_score_`, `target_odds_`.
- `score_direction_`, `rounding_method_`, `intercept_allocation_`.
- `final_features_`, `final_woe_columns_`, `points_columns_`.
- `coefficients_`: copia normalizada de `model.coefficients`.
- `scorecard_`: `pandas.DataFrame` por feature/bin.
- `feature_points_`: mapping `feature -> DataFrame` para inspección rápida.
- `dependency_versions_`: versiones de pandas/numpy y, si aplica, scikit-learn.

```python
# nikodym/scorecard/step.py
@register("standard", domain="scorecard")
class ScorecardStep(AuditableMixin):
    name: str = "scorecard"
    requires: tuple[ArtifactKey, ...] = (
        ("binning", "tables"),
        ("binning", "summary"),
        ("binning", "woe_frame"),
        ("binning", "result"),
        ("model", "estimator"),
        ("model", "final_features"),
        ("model", "final_woe_columns"),
        ("model", "coefficients"),
        ("model", "raw_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("scorecard", "scorecard"),
        ("scorecard", "score"),
        ("scorecard", "result"),
        ("scorecard", "card"),
    )
    @classmethod
    def from_config(cls, cfg: ScorecardConfig) -> "ScorecardStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "ScorecardResult": ...
```

**Artefactos que `ScorecardStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"scorecard"` | `pandas.DataFrame` | tabla de puntos por atributo/bin |
| `"score"` | `pandas.DataFrame` | filas modelables con columnas `<feature>__points`, `score`, y columnas estructurales disponibles |
| `"result"` | `ScorecardResult` | contenedor agregado |
| `"card"` | `ScorecardCardSection` | resumen para governance/report |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning", "selection", "model", "scorecard"])
tabla = study.artifacts.get("scorecard", "scorecard")
score = study.artifacts.get("scorecard", "score")
```

## 5. Configuración (schema Pydantic)

`ScorecardConfig` es el sub-config de la sección `scorecard` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig` (`extra="forbid"`, `frozen=True`), campos con `title`/`description`, rangos `ge/le`, `Literal` en categóricos y metadatos `ui_*`. **No es infraestructura** (`scorecard ∉ INFRA_SECTIONS`): cambiar `PDO`, dirección, redondeo u overrides cambia el `config_hash`.

```python
# nikodym/scorecard/config.py
from typing import Literal
from pydantic import Field, model_validator
from nikodym.core.config import NikodymBaseConfig

class PointOverrideConfig(NikodymBaseConfig):
    feature: str = Field(..., title="Variable")
    bin_label: str = Field(..., title="Bin")
    points: int | float = Field(..., title="Puntos forzados")
    reason: str = Field(..., min_length=1, title="Justificación")

class ScorecardConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"
    pdo: float = Field(20.0, gt=0.0, title="PDO")
    target_score: float = Field(600.0, title="Score objetivo")
    target_odds: float = Field(50.0, gt=0.0, title="Odds objetivo buenos/malos")
    score_direction: Literal["higher_is_lower_risk", "higher_is_higher_risk"] = Field(
        "higher_is_lower_risk", title="Dirección del score")
    intercept_allocation: Literal["uniform"] = Field(
        "uniform", title="Distribución del intercepto")
    rounding_method: Literal[
        "none", "nearest_integer", "floor_integer", "ceil_integer"
    ] = Field("nearest_integer", title="Redondeo de puntos")
    output_suffix: str = Field("__points", title="Sufijo columnas de puntos")
    score_column: str = Field("score", title="Columna score total")
    min_score: float | None = Field(None, title="Score mínimo permitido")
    max_score: float | None = Field(None, title="Score máximo permitido")
    clip: bool = Field(False, title="Recortar scores fuera de rango")
    point_overrides: tuple[PointOverrideConfig, ...] = Field(
        default_factory=tuple, title="Overrides manuales de puntos")
```

**Validaciones de config.**
- `pdo > 0`.
- `target_odds > 0` y se interpreta según `score_direction`.
- `output_suffix` y `score_column` no pueden ser vacíos; `score_column` no puede terminar con `output_suffix`.
- Si `min_score` y `max_score` existen, `min_score < max_score`.
- Si `clip=True`, debe existir al menos uno de `min_score`/`max_score`.
- `point_overrides` no puede tener duplicados `(feature, bin_label)`.
- `intercept_allocation="uniform"` es la única variante de v1; alternativas ponderadas quedan como decisión futura (D-SCR-4).

**Defaults propuestos, todos R0 para Cami.**
- `score_direction="higher_is_lower_risk"`: convención crediticia habitual.
- `pdo=20.0`, `target_score=600.0`, `target_odds=50.0`: defaults de industria útiles para ejemplos, no normativos.
- `rounding_method="nearest_integer"`: produce una scorecard operable y legible; conserva `raw_points` para auditoría.
- `intercept_allocation="uniform"`: simple, reproducible y coincide con la fórmula solicitada (`α/n`).
- `output_suffix="__points"` y `score_column="score"`: espejo de `binning.output_suffix="__woe"`.
- `clip=False`: no esconder scores extremos por defecto; si se recortan, debe ser una decisión auditada.

**Hook diferido en `core.config.schema`.** F1 debe extender el patrón real ya usado por `data`/`eda`/`binning`/`selection`/`model`:
- declarar `_SCORECARD_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir `scorecard` como campo opaco si `nikodym.scorecard` no fue importado y validado como `ScorecardConfig` cuando el módulo se carga;
- `nikodym.scorecard.__init__` asigna el hook y registra `ScorecardStep`;
- `core.study` agrega `"scorecard"` a `_DOMAIN_MODULES`, `_DOMAIN_CONFIG_CLASSES` y `_DEFAULT_DOMAIN_ORDER` inmediatamente después de `"model"`.

## 6. Contratos de datos (I/O)

**Inputs vía `Study` (nombres reales implementados a 2026-06-28).**

Desde `model`:
- `("model", "estimator")`: `LogisticPDModel` fiteado; fuente redundante para atributos fiteados y transform standalone.
- `("model", "final_features")`: `tuple[str, ...]`, features raw finales.
- `("model", "final_woe_columns")`: `tuple[str, ...]`, columnas WoE finales, mismo orden que `final_features`.
- `("model", "coefficients")`: `pandas.DataFrame` con filas `feature`, `woe_column`, `beta`, `iv`, `iv_contribution`; incluye `feature="intercept"`, `woe_column="const"` para el intercepto.
- `("model", "raw_pd_frame")`: `pandas.DataFrame` con `partition`, `target`, `linear_predictor`, `pd_raw`, usado para alinear score con PD cruda y particiones.

Desde `binning`:
- `("binning", "tables")`: `dict[str, pandas.DataFrame]` con tabla por variable. Debe contener `Bin` y `WoE` (según OptBinning/Nikodym) para derivar puntos por bin.
- `("binning", "summary")`: `pandas.DataFrame` con `name`, `iv` y metadata de bins; se usa para auditoría/card, no para recalcular IV.
- `("binning", "woe_frame")`: `pandas.DataFrame` con columnas estructurales de `data` y columnas `feature__woe`.
- `("binning", "result")`: `BinningResult`, fuente real de `woe_column_map: dict[str, str]`. **No existe un artefacto separado `("binning", "woe_column_map")` en el código actual**; consumirlo así sería un contrato fantasma.

**Poblaciones.**
- `fit`: no mira target ni particiones para aprender; deriva puntos solo desde coeficientes y tablas WoE. Por anti-leakage, **no usa Holdout/OOT para decidir nada**.
- `transform`: aplica puntos sobre filas modelables presentes en `binning.woe_frame` (`desarrollo`, `holdout`, `oot`) y alinea con `model.raw_pd_frame` cuando ambos comparten índice.
- `fuera_de_modelo`: no recibe `score` por defecto. Si aparece en el `woe_frame`, se filtra y se registra `log_decision(regla="scorecard_fuera_de_modelo", accion="no_puntuar")`.

**Output `scorecard`.** `pandas.DataFrame`, una fila por feature/bin:

| columna | significado |
|---|---|
| `feature` | nombre raw final |
| `woe_column` | columna WoE final (`feature__woe` por default) |
| `bin_label` | etiqueta del bin desde `binning.tables[feature]` |
| `bin_index` | orden estable del bin dentro de la tabla |
| `woe` | WoE usado para puntos |
| `beta` | coeficiente de `model.coefficients` |
| `intercept_share` | `α/n` con `intercept_allocation="uniform"` |
| `raw_points` | puntos antes de redondeo/clipping |
| `points` | puntos publicados |
| `rounding_delta` | `points - raw_points` |
| `source` | `"binning_table"` u `"override"` |

**Output `score`.** `pandas.DataFrame`, mismo índice y orden que filas modelables:
- columnas estructurales disponibles: `partition`, `target`, opcionalmente `linear_predictor`, `pd_raw`;
- una columna por variable final con sufijo `__points`;
- `score` total.

**Invariantes.**
- `final_features` y `final_woe_columns` tienen el mismo largo `n >= 1`.
- Toda feature final existe en `binning.result.woe_column_map` y toda columna WoE final existe en `binning.woe_frame`.
- Toda feature final tiene fila de coeficiente finita en `model.coefficients`.
- La fila `intercept/const` existe; si SDD-08 se configuró sin intercepto, se documenta como `α=0.0`.
- Antes de redondeo, `score_exact = offset - factor * linear_predictor` para `score_direction="higher_is_lower_risk"`.
- Con redondeo, `abs(score - score_exact)` queda acotado por `n * 0.5` cuando `nearest_integer`; el resultado conserva `raw_points` para reconciliación.
- No muta `model.coefficients`, `binning.tables`, `binning.woe_frame` ni `model.raw_pd_frame`.
- `-0.0` se publica como `0.0` en todos los floats.

## 7. Algoritmos y flujo

**`ScorecardStep.execute(study, rng)` — secuencia canónica.**
1. **Descartar azar.** `del rng`; scorecard v1 es determinista.
2. **Leer artefactos.** Validar presencia/tipos de `binning.tables`, `binning.summary`, `binning.woe_frame`, `binning.result`, `model.estimator`, `model.final_features`, `model.final_woe_columns`, `model.coefficients`, `model.raw_pd_frame`.
3. **Resolver config.** Leer `study.config.scorecard` o fallback del paso standalone.
4. **Copias defensivas.** Trabajar sobre copias profundas de frames/tablas.
5. **Construir mapping.** Leer `woe_column_map` desde `binning.result.woe_column_map`; validar que coincide con `model.final_features`/`model.final_woe_columns`.
6. **Extraer coeficientes.** De `model.coefficients`, construir `beta_by_feature` y `alpha` desde la fila `intercept/const`.
7. **Calcular escala.** `factor = pdo / ln(2)`; `offset = target_score - factor * ln(target_odds)`.
8. **Construir tabla de puntos.** Para cada feature final y cada fila de `binning.tables[feature]`:
   - leer `WoE` finito;
   - calcular `raw_points = offset/n - factor*(beta*woe + alpha/n)` con dirección default;
   - aplicar redondeo configurado;
   - aplicar override manual si existe, con `log_decision`.
9. **Transformar registros.** Tomar `binning.woe_frame[final_woe_columns]`; por cada feature, calcular puntos desde el WoE observado. Si el WoE coincide con un bin conocido, usar el punto de tabla; si no coincide pero es finito, calcular por fórmula y registrar `bin_no_visto`/`woe_no_tabular`.
10. **Sumar score.** `score = Σ points_columns`; si `clip=True`, recortar a `min_score`/`max_score` y registrar cada clipping agregado por conteo.
11. **Alinear con PD cruda.** Unir columnas disponibles de `model.raw_pd_frame` por índice (`partition`, `target`, `linear_predictor`, `pd_raw`) sin recalcular PD.
12. **Construir DTOs.** `ScorecardResult` y `ScorecardCardSection` con versions y parámetros.
13. **Publicar artefactos.** Escribir `"scorecard"`, `"score"`, `"result"`, `"card"` bajo dominio `"scorecard"`.

**`PointsScaler.fit(...)` — derivación de puntos.**
1. Validar mapping 1:1 entre `final_features` y `final_woe_columns`.
2. Validar `n = len(final_features) >= 1`.
3. Normalizar columnas de `coefficients`: nombres string, betas finitos, intercepto único.
4. Validar que cada tabla de binning tenga una columna `WoE` finita. Si OptBinning cambia nombres de columnas, el wrapper debe normalizarlos en `binning` o fallar aquí con `ScorecardFitError`; `scorecard` no adivina.
5. Calcular `factor`, `offset`, `intercept_share`.
6. Generar `scorecard_` ordenada por `final_features` y orden de bins original.
7. Aplicar redondeo/overrides de forma determinista.

**`PointsScaler.transform(woe_frame)` — scoring de registros.**
1. Validar columnas `final_woe_columns_`.
2. Validar finitud de WoE; missing/no finito es `ScorecardTransformError`.
3. Para cada columna WoE final:
   - usar mapping exacto `woe -> points` si existe;
   - si no existe, calcular puntos por fórmula directa y registrar evento agregado si `audit` está disponible;
   - publicar `<feature>__points`.
4. Sumar `score`.
5. Aplicar clipping si está configurado.

**Alternativas descartadas.**
- *Recalibrar `Offset` para igualar una tasa central observada:* descartado; eso es SDD-10.
- *Usar `model.raw_pd_frame.pd_raw` para invertir a puntos sin coeficientes/binning:* descartado; produciría score total pero no puntos por atributo/bin, que son el objetivo auditable de esta capa.
- *Distribuir el intercepto proporcional a IV por defecto:* descartado en v1; hace la tabla menos simple y mezcla `model`/`binning` en una decisión de presentación. Queda como D-SCR-4.
- *Publicar solo score total:* descartado; sin puntos por atributo la scorecard no es defendible ante auditor/model validator.
- *Aceptar bins no vistos silenciosamente:* descartado; puede ocurrir por categoría desconocida → WoE neutral, pero debe quedar trazado.

**Complejidad / rendimiento.** Derivar la tabla de puntos es O(total de bins finales). Transformar registros es O(n_filas × n_variables_finales), vectorizable en pandas/numpy. No hay fits iterativos.

## 8. Casos borde y manejo de errores

- **Faltan artefactos de `model`/`binning`:** `ArtifactNotFoundError` por CT-1 antes de ejecutar, o `ScorecardFitError` si el artefacto existe con tipo/shape inválido.
- **`binning.result` no expone `woe_column_map`:** `ScorecardFitError`; no se busca `("binning", "woe_column_map")` porque no existe como artefacto real.
- **Feature final sin tabla de binning:** `ScorecardFitError` con feature y tablas disponibles.
- **Feature final sin coeficiente:** `ScorecardFitError`; no se asume beta cero.
- **Intercepto faltante:** si `model.estimator.fit_intercept` fue `False` o la tabla documenta ausencia, usar `α=0.0`; si hay ambigüedad, `ScorecardFitError`.
- **WoE no finito en tabla:** `ScorecardFitError`; puntos no defendibles.
- **WoE no finito en transform:** `ScorecardTransformError`; no se puntúa una fila con input no finito.
- **Bin/WoE no visto en transform:** calcular por fórmula directa si el WoE es finito, marcar `source="formula_unseen"` en metadata interna y registrar `log_decision(regla="bin_no_visto", accion="calcular_por_formula")` agregado por feature/conteo. Si Cami prefiere fallo duro, queda como D-SCR-8.
- **Modelo de una sola variable:** soportado; `α/n == α`. Si `model` lo dejó pasar pese a IV-contribution, `scorecard` no lo bloquea.
- **Score fuera de rango:** con `clip=False`, se publica y se registra flag agregado si `min_score`/`max_score` existen; con `clip=True`, se recorta y se audita.
- **Redondeo produce diferencias contra `linear_predictor`:** esperado; se conserva `raw_points` y `rounding_delta`. Tests comparan score exacto antes de redondeo y tolerancia después.
- **Override manual de puntos:** requiere `reason` no vacío; se registra con feature/bin/valor anterior/nuevo. Un override que cambia dirección económica debe quedar visible para revisión.
- **Colisión de nombres:** si `<feature>__points` o `score` ya existen en el input, `ScorecardTransformError` salvo política futura explícita de overwrite. Default: no sobrescribir.

Toda excepción propia desciende de `NikodymError`; los mensajes son en español e incluyen regla, feature/bin, umbral/config y valor observado.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno. `ScorecardStep.execute(study, rng)` recibe `rng` por contrato y debe hacer `del rng`.
- **Determinismo esperado.** `(data_hash + config_hash + coeficientes + tablas WoE + uv.lock) → scorecard y score idénticos`.
- **Orden estable.** La tabla `scorecard` sigue el orden de `model.final_features` y, dentro de cada feature, el orden original de `binning.tables[feature]`. El frame `score` preserva el índice y orden de `binning.woe_frame`/`model.raw_pd_frame` modelable.
- **Normalización numérica.** Publicar `-0.0` como `0.0`; floats finitos únicamente; no usar `hash()` builtin para ninguna identidad auxiliar.
- **Audit trail (`log_decision`).** Registrar con argumentos keyword-only `regla`, `umbral`, `valor`, `accion`:
  - `scorecard_rounding`: método, número de variables, delta máximo y suma de deltas;
  - `point_override`: feature, bin, puntos anterior/nuevo, razón;
  - `bin_no_visto`: feature, conteo, política aplicada;
  - `score_clip`: min/max, conteo de filas afectadas;
  - `score_fuera_de_rango`: min/max observados cuando `clip=False`;
  - `scorecard_fuera_de_modelo`: filas no puntuadas por partición.
- **Card / report.** `ScorecardCardSection` debe permitir reconstruir la escala: `PDO`, `target_score`, `target_odds`, `Factor`, `Offset`, dirección, redondeo, nº de variables, columnas de puntos, score min/max y overrides.
- **Lineage.** `scorecard` no completa `data_hash` ni `config_hash`; su contribución al lineage son su config computacional, dependencias y decisiones auditadas.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymTransformer`, `MissingDependencyError`, `NikodymError`, `Registry`.
- SDD-05 (convenciones): config Pydantic, hook diferido, `config_hash`, API sklearn-like.
- SDD-06 (`binning`): `tables`, `summary`, `woe_frame`, `result.woe_column_map`, sufijo `__woe`.
- SDD-08 (`model`): `estimator`, `final_features`, `final_woe_columns`, `coefficients`, `raw_pd_frame`.

**Aguas abajo.**
- SDD-10 (`calibration`) consume `scorecard.score` junto con `model.raw_pd_frame`/PD cruda para calibrar PD sin cambiar la tabla de puntos.
- SDD-11 (`performance`/`stability`) consume `scorecard.score` para deciles, KS/Gini/AUC, distribución de score y PSI de score.
- SDD-26 (`report`) consume `scorecard.scorecard`, `scorecard.card` y ejemplos de `scorecard.score`.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | según base del proyecto (`>=2.0`) | BSD-3 ✅ | tablas de puntos y score por registro | base |
| numpy | según base del proyecto (`>=1.22`) | BSD ✅ | `ln`, finitud, vectorización | base |
| scikit-learn | extra `[scoring]`, si `Scorecard` multihereda `BaseEstimator` | BSD-3 ✅ | compatibilidad sklearn-like/checks | import perezoso |

**Núcleo liviano.** `nikodym.core` no importa `scorecard`. `import nikodym.scorecard` registra config/step sin importar `statsmodels` ni `optbinning`. `scorecard` puede importar pandas/numpy dentro de métodos; si se decide heredar de sklearn, el import de `Scorecard` debe ser perezoso y levantar `MissingDependencyError("instale nikodym[scoring]")` si falta el extra.

**Sin parámetros normativos.** Este módulo no depende de la CMF ni IFRS 9. Cita `normativa_cmf_parametros.md` solo para deslindar: las tablas PI/PDI/PE son de provisiones, no de scorecard.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **Goldens de escala.** Con `PDO=20`, `target_score=600`, `target_odds=50`, verificar `Factor = 20/ln(2)` y `Offset = 600 - Factor*ln(50)` contra valores calculados a mano.
- **Golden de puntos.** Caso pequeño con dos variables, `α`, `β`, WoE por bin y puntos esperados a mano con intercepto uniforme. Verificar `raw_points`, `points`, `rounding_delta` y suma.
- **Afinidad con el predictor lineal.** Sin redondeo ni clipping, para cada registro: `score == offset - factor*linear_predictor` con dirección default. Con dirección inversa: `score == offset + factor*linear_predictor`.
- **Ranking/Gini.** Verificar que `risk_score=-score` produce el mismo orden y mismo Gini/AUC que `pd_raw` (tolerancia numérica); si se usa `score` directamente con `higher_is_lower_risk`, el test documenta la inversión de orientación.
- **Redondeo.** `nearest_integer` acota el error por registro a `0.5*n_variables`; `none` conserva exactitud afín. `-0.0` se normaliza.
- **Contratos `Step`.** `ScorecardStep.requires` exige los nueve artefactos reales listados en §4; falta uno → `ArtifactNotFoundError`. No debe exigir `("binning","woe_column_map")`.
- **No leakage.** Cambiar target o valores de HO/OOT no cambia la tabla de puntos; solo cambia los scores de filas cuyos WoE cambiaron. `fit` no mira target.
- **No mutación.** Snapshots profundos de `model.coefficients`, `binning.tables`, `binning.woe_frame`, `model.raw_pd_frame` permanecen iguales.
- **Casos borde.** WoE no finito en tabla/transform, feature sin coeficiente, intercepto faltante, una sola variable, bin/WoE no visto, clipping, override duplicado.
- **Config.** Round-trip YAML de `ScorecardConfig`; cambiar `pdo`, `target_score`, `target_odds`, dirección o redondeo cambia `config_hash`; `scorecard` no está en `INFRA_SECTIONS`.
- **Import liviano.** `import nikodym.core` no importa `nikodym.scorecard`; `import nikodym.scorecard` no importa `statsmodels` ni `optbinning`.
- **Clone/sklearn.** Si `Scorecard` hereda sklearn, `__init__` keyword-only sin lógica, `get_params/set_params` clone-safe, `config_cls` correcto y atributos fiteados con sufijo `_`.
- **Integración.** Pipeline `data → binning → selection → model → scorecard` sobre fixture sintético; `scorecard.score` preserva índice, particiones y columna `score`.

Fixtures: `behavior_scorecard_small.parquet`, tablas de binning sintéticas con WoE conocido, `model.coefficients` sintético, `ScorecardConfig` mínimo y variantes de redondeo/dirección, `InMemoryAuditSink`.

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Ambigüedad de orientación del score.** Mitigación: `score_direction` explícito en config/card y tests de Gini con orientación correcta.
- **Confundir scorecard con calibración.** Mitigación: `Offset` solo escala puntos; SDD-10 calibra PD y el reporte debe etiquetar `pd_raw` vs `pd_calibrada`.
- **Redondeo rompe exactitud afín.** Mitigación: conservar `raw_points`, publicar `rounding_delta`, tests de tolerancia y opción `rounding_method="none"`.
- **Contrato fantasma de `woe_column_map`.** Mitigación: documentar que vive en `binning.result.woe_column_map`, no como artefacto separado.
- **Overrides manuales erosionan auditabilidad.** Mitigación: default vacío, razón obligatoria y `log_decision`; report los destaca.
- **Score fuera de rango operativo.** Mitigación: no clipping silencioso; clipping opt-in y auditado.

**Fuentes verificadas / citas.**
- **ESPECIFICACIONES.md** §4 (principios 1 reproducibilidad, 2 auditabilidad, 4 monotonía con riesgo, 5 config declarativa, 8 no reinventar, 9 núcleo liviano, 10 calidad, 11 doble verificación), §5.2 (pipeline scorecard; WoE/IV; stepwise; fórmula `Score`, `Factor`, puntos por atributo; calibración aguas abajo), §6.3 (`scorecard/` = escalado, offset/PDO, puntos por atributo).
- **SDD-02 (`data`)** §6 (target, `partition`, Desarrollo/HO/OOT/fuera_de_modelo), §12 D-DATA-7 (frontera transversal scorecard vs longitudinal IFRS9/forward).
- **SDD-05** §4/§5/§6 (API sklearn-like, `NikodymBaseConfig`, hooks diferidos, `config_hash`, `INFRA_SECTIONS`, outputs tabulares con columnas nombradas).
- **SDD-06 (`binning`)** §3/§4/§6 y código implementado (`BinningStep.provides`): artefactos reales `process`, `tables`, `summary`, `woe_frame`, `result`, `binning_card`; `woe_column_map` vive en `BinningResult`.
- **SDD-07 (`selection`)** §4/§6 y código implementado: `selected_woe_frame` existe, pero `scorecard` puede puntuar desde `binning.woe_frame` + `model.final_woe_columns`.
- **SDD-08 (`model`)** §1/§4/§6 y código implementado: artefactos reales `estimator`, `final_features`, `final_woe_columns`, `coefficients`, `raw_pd_frame`; `raw_pd_frame` es PD cruda no calibrada.
- **_CONTRATOS-TRANSVERSALES.md** CT-1 (requires/provides), CT-2 (`metric_sections`), CT-3 (datos transversales vs longitudinales), CT-4 (ensamblado fuera de `core`).
- **docs/normativa_cmf_parametros.md** Advertencias y §1+ (las matrices PI/PDI/PE son de provisiones regulatorias CMF, no de scorecard).

## Decisiones para revisión de Cami

- **D-SCR-1 — Dirección del score (R0).** Recomendación: `higher_is_lower_risk` (mayor score = menor riesgo). Implica `Score = Offset - Factor*η` porque SDD-08 modela log-odds de malo. Confirmar si la marca Nikodym quiere esta convención o la inversa.
- **D-SCR-2 — Defaults de escala (R0).** Recomendación inicial: `PDO=20`, `target_score=600`, `target_odds=50:1` buenos/malos. Son defaults de industria, no normativos. Confirmar o cambiar antes de aprobar SDD-09.
- **D-SCR-3 — Redondeo de puntos (R0).** Recomendación: publicar enteros (`nearest_integer`) y conservar `raw_points`. Alternativa: floats exactos por defecto. Decide producto/usabilidad vs exactitud afín.
- **D-SCR-4 — Distribución del intercepto (R0).** Recomendación v1: uniforme (`α/n`) como pide ESPEC/esta tarea. Alternativa futura: ponderar por IV, abs(beta) u otro criterio, pero sería menos transparente.
- **D-SCR-5 — Variables forzadas y overrides (R0).** Recomendación: las variables forzadas se resuelven solo en SDD-08; `scorecard` no revive variables. Overrides de puntos permitidos solo con razón obligatoria y audit trail, default vacío.
- **D-SCR-6 — Frontera con calibration (R0).** Recomendación: `Offset` no se usa para calibrar PD a tasa central; SDD-10 debe consumir score/PD cruda y publicar PD calibrada separada.
- **D-SCR-7 — Nombres de artefactos `scorecard` (R0).** Recomendación: publicar claves `"scorecard"`, `"score"`, `"result"`, `"card"` bajo dominio `"scorecard"`. Confirmar si se prefiere patrón más explícito (`"scorecard_card"`) como otros módulos.
- **D-SCR-8 — Política ante WoE/bin no visto (R0).** Recomendación: si WoE es finito, calcular por fórmula directa y auditar; si no finito, fallar. Confirmar si Cami prefiere fallo duro ante cualquier WoE no tabular.
- **D-SCR-9 — Clipping de score (R0).** Recomendación: `clip=False` por defecto; no esconder extremos. Si se requiere rango operativo, configurarlo y auditar conteos.
