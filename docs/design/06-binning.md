# SDD-06 — `binning` (binning supervisado óptimo, WoE e IV para scorecard)

| Campo | Valor |
|---|---|
| **SDD** | 06 |
| **Módulo** | `nikodym.binning` |
| **Versión** | 0.1 |
| **Fecha** | 2026-06-27 |
| **Fase** | F1 |
| **Tanda de producción** | T2 (Scoring) |
| **Estado** | 🟡 Borrador |
| **Depende de** | SDD-01 (`core`), SDD-02 (`data`), SDD-05 (convenciones + config) |
| **Lo consumen** | SDD-07 (`selection`), SDD-08 (`model`), SDD-09 (`scorecard`), SDD-11 (`performance` + `stability`), SDD-12 (`ml`, como benchmark opcional), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (redacción SDD-06 para T2) / 2026-06-27 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `binning` convierte las variables predictoras crudas del frame validado por `data` en **variables WoE auditables**, mediante **binning supervisado óptimo** respecto del target binario (`1 = default/malo`, `0 = no-default/bueno`), y produce las tablas de cortes/grupos, WoE e IV que alimentan la scorecard y el reporte.

**Responsabilidad única (qué SÍ hace).**
- Ajusta bins supervisados por variable, numérica o categórica, **solo sobre la partición de Desarrollo** (`partition == "desarrollo"`) para evitar leakage.
- Transforma **todas** las particiones modelables (Desarrollo, Holdout, OOT) con los bins ajustados en Desarrollo; no re-ajusta fuera de Desarrollo.
- Calcula y publica **WoE (Weight of Evidence)** por bin y **IV (Information Value)** por variable, con tablas auditables.
- Trata **missing** y **special values** como bins explícitos y trazables, siguiendo el contrato de `SpecialValuePolicy` de SDD-02.
- Controla monotonía del binning respecto de la tasa de evento / riesgo, con default conservador para scorecard regulatoria.
- Publica artefactos namespaced bajo `"binning"`: proceso fiteado, tablas, resumen, frame WoE, card de binning y resultado agregado.
- Aporta el sub-config **`BinningConfig`** (sección `binning` de `NikodymConfig`), que **sí entra al `config_hash`** por ser computacional.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No carga ni valida datos crudos**: eso es `data` (SDD-02). `binning` consume `("data", "frame")`, `("data", "labels")`, `("data", "splits")` y `("data", "special")`.
- **No hace EDA descriptivo**: eso es `eda` (SDD-27). El `qcut` de `eda/univariate.py` es **descriptivo**, no supervisado, no transforma datos para el modelo y no produce los WoE finales. `binning` puede leer diagnósticos de `eda` si existen, pero no depende de ellos.
- **No selecciona variables por IV/PSI/correlación**: eso es `selection` (SDD-07). `binning` reporta IV y flags; no elimina por poder predictivo salvo variables no binneables.
- **No ajusta la regresión logística ni impone signos de β**: eso es `model` (SDD-08). `binning` solo entrega WoE con orientación documentada.
- **No escala puntos ni calcula scorecard**: eso es `scorecard` (SDD-09).
- **No calcula provisiones CMF ni ECL IFRS 9**: esos motores usan PD/modelos aguas abajo; las fórmulas y parámetros regulatorios se citan desde `ESPECIFICACIONES.md` y `normativa_cmf_parametros.md`.
- **No muta el dominio `"data"`**: el frame original validado queda intacto; el frame transformado vive bajo `"binning"`.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Scoring (F1/T2). Es el paso posterior a `data` y, en el pipeline de scorecard, posterior al diagnóstico `eda` si la sección `eda` está activa.
- **Quién lo invoca:** el orquestador de `core` como sección `binning` de `NikodymConfig` (orden canónico: `data → eda → binning → selection → model → ...`). También se usa standalone desde API programática para pruebas y notebooks.
- **A quién invoca:** `core` (Step, ArtifactStore, AuditSink, `NikodymTransformer`, excepciones), `data` solo por sus artefactos/contratos, y `optbinning` del extra `[scoring]`. **`core` no importa `binning` ni `optbinning`**: el sub-config se conecta por hook diferido.

```
config.data ─► data (SDD-02) ─► artifacts["data"]: frame, splits, labels, special
                          │
config.eda  ─► eda  (SDD-27) ─► artifacts["eda"] diagnósticos descriptivos (opcional)
                          │
                          ▼
config.binning ─► Study.run() ─► binning (SDD-06)
                                  fit en Desarrollo
                                  transform en Desarrollo/HO/OOT
                                  tablas WoE/IV + frame WoE
                                  │
                                  ▼
                         selection · model · scorecard · performance · report
```

**Interacción con `Study` y config declarativo.** `BinningStep` es un `Step` nativo registrado con `@register("standard", domain="binning")`. Declara `requires`/`provides` (CT-1) y `execute(study, rng)`: lee artefactos de `data`, ajusta el binner en Desarrollo, transforma todas las particiones elegibles y escribe artefactos bajo `"binning"`. El `rng` se recibe para mantener el contrato homogéneo, aunque el binning v1 debe ser determinista sin muestreo.

**Frontera con `eda`.** SDD-27 usa cuantiles fijos (`pandas.qcut`) para **mirar** perfiles univariados. SDD-06 usa OptBinning para **aprender** cortes/grupos supervisados contra el target y transforma el dataset a WoE. Los nombres de artefactos y tablas no se mezclan: `eda.univariate.descriptive_iv` es pre-binning; `binning.summary.iv` es el IV final sobre bins óptimos.

## 3. Conceptos y fundamentos

- **Target binario.** SDD-02 produce `target` con `1 = malo/default/event` y `0 = bueno/no-default/non-event`; indeterminados/excluidos tienen `<NA>` y `partition="fuera_de_modelo"`. `binning` ajusta solo sobre filas con target no nulo y partición Desarrollo.
- **Binning supervisado óptimo.** Discretización de una variable `x` en bins que maximizan una medida de separación respecto de `y` (default: IV) bajo restricciones de tamaño mínimo, número máximo de bins, eventos/no-eventos mínimos y monotonía. Numéricas producen intervalos; categóricas producen grupos de niveles.
- **Pre-binning.** OptBinning 0.20.0 usa por defecto `prebinning_method="cart"`: genera prebins candidatos y luego resuelve el problema combinatorio. Nikodym mantiene el default salvo override; `max_n_prebins` y `min_prebin_size` controlan complejidad.
- **WoE (Weight of Evidence).** Convención de F1 (ESPECIFICACIONES §5.2):  
  `WoE_b = ln(%Goods_b / %Bads_b)`  
  donde `%Goods_b = goods_b / goods_total` y `%Bads_b = bads_b / bads_total`. Dado `target=1` como evento/malo, esta convención coincide con la columna `WoE` que construye `optbinning.binning_table.build()` en 0.20.0 (`Non-event` = buenos, `Event` = malos). Un bin con más malos relativos tiene WoE más bajo.
- **IV (Information Value).** `IV = Σ_b (%Goods_b - %Bads_b) · WoE_b`. Se reportan umbrales clásicos como etiquetas de diagnóstico: `<0.02` débil/no predictivo, `0.02–0.10` bajo, `0.10–0.30` medio, `0.30–0.50` fuerte, `>0.50` revisar posible leakage o proxy demasiado dominante. `binning` **no filtra** por esos umbrales por defecto; SDD-07 decide selección.
- **Monotonicidad.** Para scorecards regulatorias se prefiere una relación monotónica entre la variable y el riesgo: aumenta interpretabilidad, reduce sobreajuste y facilita defensa ante validadores. OptBinning define `monotonic_trend` sobre la **event rate** (tasa de malos), no sobre WoE. Con `WoE = ln(%Goods/%Bads)`, una event rate ascendente implica WoE descendente.
- **Missing.** Missing genuino (`NaN`) se conserva como bin `"Missing"` con WoE propio cuando existe en Desarrollo. En transform, se usa el WoE empírico del bin missing (`metric_missing="empirical"`), no imputación previa.
- **Special values.** SDD-02 normaliza centinelas a `NaN` y conserva `special_mask`/`special_catalog`. SDD-06 reconstruye `special_codes` desde ese catálogo para que OptBinning los trate como bin `"Special"` separado de missing genuino cuando sea posible.
- **Categóricas.** OptBinning agrupa niveles por relación con el target. Niveles raros pueden entrar en un grupo `"others"` vía `cat_cutoff`. Niveles no vistos en transform se asignan por default a WoE neutral `0.0` (`cat_unknown=None` en OptBinning para métrica WoE), con conteo auditado.
- **Anti-leakage.** Cualquier corte, grupo, WoE e IV se estima **solo con Desarrollo**. Holdout/OOT sirven para evaluación y estabilidad, no para aprender bins.

> **Fórmulas / parámetros normativos:** `binning` no contiene parámetros CMF ni IFRS 9. Las fórmulas regulatorias y matrices oficiales se citan desde `docs/ESPECIFICACIONES.md` y `docs/normativa_cmf_parametros.md`, no se reescriben aquí.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/binning/config.py
class BinningConfig(NikodymBaseConfig): ...
class VariableBinningConfig(NikodymBaseConfig): ...

# nikodym/binning/exceptions.py
class BinningError(NikodymError): ...
class BinningFitError(BinningError): ...
class BinningTransformError(BinningError): ...

# nikodym/binning/transformer.py
class WoEBinner(TransformerMixin, BaseEstimator, NikodymTransformer):
    """Wrapper sklearn-like sobre optbinning.BinningProcess para scorecard."""
    config_cls: ClassVar[type[BinningConfig]] = BinningConfig
    def __init__(
        self,
        *,
        feature_columns: tuple[str, ...] | Literal["*"] = "*",
        exclude_columns: tuple[str, ...] = (),
        categorical_columns: tuple[str, ...] = (),
        max_n_prebins: int = 20,
        min_prebin_size: float = 0.05,
        max_n_bins: int | None = 8,
        min_bin_size: float | None = 0.05,
        monotonic_trend: str | None = "auto_asc_desc",
        solver: str = "cp",
        mip_solver: str = "bop",
        time_limit: int = 100,
        special_handling: str = "separate",
        metric_special: str | float = "empirical",
        metric_missing: str | float = "empirical",
        cat_cutoff: float | None = 0.01,
        cat_unknown: float | str | None = None,
        split_digits: int | None = None,
        require_optimal: bool = True,
    ) -> None: ...
    @classmethod
    def from_config(cls, cfg: BinningConfig) -> "WoEBinner": ...
    def fit(
        self,
        X: "pandas.DataFrame",
        y: "pandas.Series",
        *,
        special: "MaskedFrame | None" = None,
        sample_weight: "pandas.Series | None" = None,
    ) -> "Self": ...
    def transform(self, X: "pandas.DataFrame") -> "pandas.DataFrame": ...
    def fit_transform(self, X: "pandas.DataFrame", y: "pandas.Series", **kwargs) -> "pandas.DataFrame": ...
```

**Atributos fiteados de `WoEBinner` (sufijo `_`).**
- `process_`: instancia fiteada de `optbinning.BinningProcess`.
- `feature_columns_`: columnas finalmente binneadas (excluye estructurales y no binneables).
- `skipped_variables_`: dict `variable -> reason` para constantes, 100% missing, sin ambas clases, error de solver, etc.
- `tables_`: dict `variable -> pandas.DataFrame` con tabla de bins (`Bin`, `Count`, `Count (%)`, `Non-event`, `Event`, `Event rate`, `WoE`, `IV`, `JS`).
- `summary_`: `pandas.DataFrame` con una fila por variable (`name`, `dtype`, `status`, `selected`, `n_bins`, `iv`, `js`, `gini`, `quality_score`, flags Nikodym).
- `woe_column_map_`: dict `raw_feature -> woe_column` (default `monto__woe`).
- `special_codes_`: dict `variable -> list` pasado a OptBinning.

```python
# nikodym/binning/results.py
class BinningVariableSummary(BaseModel):
    name: str
    dtype: Literal["numerical", "categorical"]
    status: str
    selected: bool
    n_bins: int
    iv: float
    iv_band: Literal["none", "weak", "medium", "strong", "suspicious"]
    monotonic_trend: str | None
    skipped_reason: str | None = None

class BinningResult(BaseModel):
    woe_frame: "pandas.DataFrame"
    tables: dict[str, "pandas.DataFrame"]
    summary: "pandas.DataFrame"
    variable_summaries: tuple[BinningVariableSummary, ...]
    woe_column_map: dict[str, str]
    skipped_variables: dict[str, str]
    model_config = ConfigDict(arbitrary_types_allowed=True)

class BinningCardSection(BaseModel):
    n_variables_requested: int
    n_variables_binned: int
    n_variables_skipped: int
    iv_by_variable: dict[str, float]
    monotonicity_by_variable: dict[str, str | None]
    special_handling: str
    missing_handling: str
    optbinning_version: str
```

```python
# nikodym/binning/step.py
@register("standard", domain="binning")
class BinningStep(AuditableMixin):
    name: str = "binning"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "frame"),
        ("data", "labels"),
        ("data", "splits"),
        ("data", "special"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("binning", "process"),
        ("binning", "tables"),
        ("binning", "summary"),
        ("binning", "woe_frame"),
        ("binning", "result"),
        ("binning", "binning_card"),
    )
    @classmethod
    def from_config(cls, cfg: BinningConfig) -> "BinningStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "BinningResult": ...
```

**Artefactos que `BinningStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"process"` | `WoEBinner` | transformer fiteado, serializable, con `process_` de OptBinning |
| `"tables"` | `dict[str, pandas.DataFrame]` | tabla auditable por variable con cortes/grupos, conteos, event rate, WoE, IV |
| `"summary"` | `pandas.DataFrame` | resumen por variable: status, selected, nº bins, IV, JS, Gini, quality score, flags |
| `"woe_frame"` | `pandas.DataFrame` | frame modelable con columnas estructurales de `data` + columnas `feature__woe` |
| `"result"` | `BinningResult` | contenedor agregado de las salidas principales |
| `"binning_card"` | `BinningCardSection` | resumen para model card / report |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=["data", "binning"])
woe = study.artifacts.get("binning", "woe_frame")
tables = study.artifacts.get("binning", "tables")
iv = study.artifacts.get("binning", "summary")[["name", "iv"]]
```

## 5. Configuración (schema Pydantic)

`BinningConfig` es el sub-config de la sección `binning` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig` (`extra="forbid"`, `frozen=True`), campos con `title`/`description`, rangos `ge/le`, `Literal` en categóricos y metadatos `ui_*`. **No es infraestructura** (`binning ∉ INFRA_SECTIONS`): cambiar `max_n_bins`, monotonía o tratamiento de special values cambia el `config_hash`.

```python
# nikodym/binning/config.py
from typing import Literal
from pydantic import Field, model_validator
from nikodym.core.config import NikodymBaseConfig

MonotonicTrend = Literal[
    "auto",
    "auto_heuristic",
    "auto_asc_desc",
    "ascending",
    "descending",
    "concave",
    "convex",
    "peak",
    "peak_heuristic",
    "valley",
    "valley_heuristic",
]

class VariableBinningConfig(NikodymBaseConfig):
    name: str = Field(..., title="Variable")
    dtype: Literal["numerical", "categorical", "auto"] = Field("auto", title="Tipo")
    monotonic_trend: MonotonicTrend | None = Field(None, title="Monotonía específica")
    max_n_bins: int | None = Field(None, ge=2, le=50, title="Máximo de bins específico")
    min_bin_size: float | None = Field(None, ge=0.0, le=0.5, title="Tamaño mínimo específico")
    cat_cutoff: float | None = Field(None, ge=0.0, le=0.5, title="Umbral rare levels específico")

class BinningConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"   # == @register("standard", domain="binning")
    feature_columns: tuple[str, ...] | Literal["*"] = Field(
        "*",
        title="Variables candidatas",
        description="'*' = todas las no estructurales del frame de data.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 1},
    )
    exclude_columns: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Variables excluidas",
        description="Columnas a excluir del binning aunque entren por feature_columns='*'.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 2},
    )
    categorical_columns: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Variables categóricas",
        description="Variables que OptBinning debe tratar como categóricas aunque pandas no lo infiera.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 3},
    )
    variable_overrides: tuple[VariableBinningConfig, ...] = Field(
        default_factory=tuple,
        title="Overrides por variable",
        description="Ajustes específicos de tipo, monotonía, nº bins o rare levels.",
        json_schema_extra={"ui_group": "Variables", "ui_order": 4},
    )

    max_n_prebins: int = Field(20, ge=2, le=200, title="Máximo de prebins")
    min_prebin_size: float = Field(0.05, gt=0.0, le=0.5, title="Tamaño mínimo de prebin")
    min_n_bins: int | None = Field(None, ge=2, le=50, title="Mínimo de bins")
    max_n_bins: int | None = Field(8, ge=2, le=50, title="Máximo de bins")
    min_bin_size: float | None = Field(0.05, ge=0.0, le=0.5, title="Tamaño mínimo de bin")
    min_bin_n_event: int | None = Field(1, ge=1, title="Mínimo de malos por bin")
    min_bin_n_nonevent: int | None = Field(1, ge=1, title="Mínimo de buenos por bin")

    monotonic_trend: MonotonicTrend | None = Field(
        "auto_asc_desc",
        title="Monotonía por defecto",
        description="Default Nikodym: escoger automáticamente entre event rate ascendente/descendente.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Monotonía", "ui_order": 1},
    )
    min_event_rate_diff: float = Field(0.0, ge=0.0, le=1.0, title="Diferencia mínima de event rate")
    max_pvalue: float | None = Field(None, ge=0.0, le=1.0, title="p-valor máximo entre bins")
    max_pvalue_policy: Literal["consecutive", "all"] = Field("consecutive", title="Política p-valor")

    solver: Literal["cp", "mip"] = Field("cp", title="Solver")
    mip_solver: Literal["bop", "cbc"] = Field("bop", title="MIP solver")
    time_limit: int = Field(100, ge=1, le=3600, title="Límite de tiempo por variable (segundos)")
    require_optimal: bool = Field(True, title="Exigir status óptimo")
    n_jobs: int | None = Field(None, title="Paralelismo de BinningProcess",
        description="None = 1 core. Para reproducibilidad regulatoria se recomienda no usar -1.")

    special_handling: Literal["separate", "as_missing"] = Field(
        "separate",
        title="Tratamiento de special values",
        description="'separate' usa special_codes; 'as_missing' los deja como missing.",
    )
    metric_special: Literal["empirical"] | float = Field("empirical", title="WoE para special")
    metric_missing: Literal["empirical"] | float = Field("empirical", title="WoE para missing")
    cat_cutoff: float | None = Field(0.01, ge=0.0, le=0.5, title="Umbral de rare levels")
    cat_unknown: float | str | None = Field(
        None,
        title="Valor para categoría no vista",
        description="None en OptBinning asigna WoE neutral 0 cuando metric='woe'.",
    )
    split_digits: int | None = Field(None, ge=0, le=10, title="Dígitos de cortes")
    output_suffix: str = Field("__woe", title="Sufijo de columnas WoE")
    keep_structural_columns: bool = Field(True, title="Conservar columnas estructurales de data")
    fail_on_non_binnable: bool = Field(False, title="Fallar ante variable no binneable")
```

**Defaults defendibles.**
- `feature_columns="*"` acelera el primer scorecard, pero excluye columnas estructurales (`target`, `label_status`, `partition`, `ttd`, fechas/cohortes usadas por partición y columnas de auditoría).
- `max_n_bins=8`, `min_bin_size=0.05`, `min_prebin_size=0.05` equilibran granularidad, estabilidad y tamaño muestral.
- `monotonic_trend="auto_asc_desc"` se desvía del default de OptBinning (`"auto"`) para forzar una relación monotónica ascendente/descendente de event rate, defendible ante regulador. Si una variable tiene forma genuinamente U-shaped, se usa override (`"peak"`, `"valley"`, `"concave"`, `"convex"`) con decisión auditable.
- `special_handling="separate"` conserva información de negocio de centinelas; `as_missing` queda como override si Cami prefiere simplificar.
- `metric_special="empirical"` y `metric_missing="empirical"` usan el WoE observado de esos bins; evitar `0` por defecto impide neutralizar missing/special informativos.
- `require_optimal=True` falla ruidosamente si el solver no prueba optimalidad dentro de `time_limit`; un `FEASIBLE` no probado requiere decisión explícita.

**Hook diferido en `core.config.schema`.** Para mantener el núcleo liviano, F1 debe extender el patrón ya usado por `data`/`eda`:
- declarar `_BINNING_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir `binning` como campo `Any` en runtime y `BinningConfig | None` bajo `TYPE_CHECKING`;
- añadir `@field_validator("binning", mode="before")` que, si `_BINNING_CONFIG_CLS` está poblado, valida con `BinningConfig.model_validate(valor)`, y si no lo está exige JSON canónico determinista;
- `nikodym.binning.__init__` asigna `_schema._BINNING_CONFIG_CLS = BinningConfig` al importarse y luego importa `nikodym.binning.step` para ejecutar `@register`.

## 6. Contratos de datos (I/O)

**Input vía `Study`.**
- `("data", "frame")`: `pandas.DataFrame` validado, etiquetado, particionado, con special→NaN y columnas `target`, `label_status`, `partition`, `ttd`.
- `("data", "labels")`: `LabeledFrame`, fuente de `target_col` y `status_col`.
- `("data", "splits")`: `PartitionResult`, fuente de `partition_col`.
- `("data", "special")`: `MaskedFrame`, fuente de `special_mask` y `special_catalog`.
- Opcional: `("eda", "univariate")` para reportar contraste descriptivo, sin dependencia dura ni requisito CT-1.

**Poblaciones.**
- **Fit:** filas con `partition == "desarrollo"` y `target ∈ {0,1}`.
- **Transform:** filas con `partition ∈ {"desarrollo", "holdout", "oot"}`. `fuera_de_modelo` no se transforma para modelado; puede quedar fuera del `woe_frame` o conservarse solo si `keep_structural_columns=True` y `transform_out_of_model=True` se agrega en una versión futura.
- **Target degenerado:** si Desarrollo no tiene al menos un bueno y un malo, se levanta `BinningFitError`.

**Output `woe_frame`.** `pandas.DataFrame` con el mismo índice de las filas transformadas y:
- columnas estructurales mínimas: `target`, `label_status`, `partition`, `ttd` si `keep_structural_columns=True`;
- una columna WoE por variable binneada, con sufijo configurable (`edad__woe`, `mora_ult_6m__woe`);
- ninguna columna cruda de feature por defecto, para evitar que `selection`/`model` usen accidentalmente valores sin transformar.

**Output tablas de binning.** Cada tabla por variable contiene, como mínimo:

| columna | significado |
|---|---|
| `Bin` | intervalo numérico, grupo categórico, `Special` o `Missing` |
| `Count`, `Count (%)` | conteo y proporción en Desarrollo |
| `Non-event`, `Event` | buenos y malos (`target=0/1`) en Desarrollo |
| `Event rate` | `Event / Count` |
| `WoE` | `ln(%Goods/%Bads)` |
| `IV` | contribución del bin al IV de la variable |
| `JS` | Jensen-Shannon reportado por OptBinning |

**Invariantes.**
- *No leakage:* ningún corte, grupo, WoE o IV usa Holdout/OOT.
- *No mutación:* `BinningStep` nunca escribe bajo dominio `"data"` ni modifica el objeto `data.frame` in-place.
- *Índice estable:* `woe_frame.index` es subconjunto ordenado del índice de `data.frame`; no se resetea.
- *Columnas nombradas:* todo output tabular es `DataFrame` con columnas explícitas; no se expone `ndarray` pelado.
- *Consistencia WoE:* `woe_frame[feature__woe]` solo contiene floats finitos salvo que una política explícita marque error; missing/special/unknown categórico se resuelven antes de publicar.
- *Trazabilidad:* cada columna WoE tiene entrada en `woe_column_map` y tabla en `tables`.

## 7. Algoritmos y flujo

**`BinningStep.execute(study, rng)` — secuencia canónica.**
1. **Leer artefactos.** Validar tipos de `frame`, `labels`, `splits`, `special`. Resolver `target_col`, `status_col`, `partition_col`.
2. **Resolver features.** Si `feature_columns="*"`, excluir columnas estructurales (`target`, `label_status`, `partition`, `ttd`), columnas de fecha/cohorte declaradas en `data`, columnas de target/exclusión si se identifican, y `exclude_columns`. Si el usuario declara columnas inexistentes, `BinningFitError` con lista completa.
3. **Particionar.** `train = frame[partition == "desarrollo" & target.notna()]`; verificar ambas clases. Separar `X_train`, `y_train`. Construir `X_all` para Desarrollo/HO/OOT.
4. **Reconstruir special codes.** Si `special_handling="separate"`, usar `MaskedFrame.special_catalog` para pasar `special_codes` a OptBinning. Si `as_missing`, no pasar special codes: los centinelas quedan como missing ya normalizados por `data`.
5. **Configurar OptBinning.** Instanciar `BinningProcess(variable_names, categorical_variables, max_n_prebins, min_prebin_size, max_n_bins, min_bin_size, max_pvalue, special_codes, split_digits, binning_fit_params, binning_transform_params, n_jobs, verbose=False)`. Los overrides por variable se materializan en `binning_fit_params`.
6. **Fit solo en Desarrollo.** `process.fit(X_train, y_train, check_input=True)`. Capturar `status` por variable. Si `require_optimal=True` y una variable queda en status no óptimo por solver/time limit, fallar o saltar según `fail_on_non_binnable`; en ambos casos registrar `log_decision`.
7. **Construir tablas.** Para cada variable seleccionada/fiteada, `get_binned_variable(name).binning_table.build(add_totals=True)`. Calcular `iv_band` y flags Nikodym (IV sospechoso, bins colapsados, monotonicidad override).
8. **Transformar todas las particiones elegibles.** `process.transform(X_all, metric="woe", metric_special=cfg.metric_special, metric_missing=cfg.metric_missing, check_input=True)`. Renombrar columnas con `output_suffix`.
9. **Manejar categorías no vistas.** Contar niveles categóricos fuera del entrenamiento en Holdout/OOT. Default OptBinning con `cat_unknown=None` asigna WoE neutral 0 para métrica WoE; registrar `log_decision` si el conteo > 0.
10. **Publicar artefactos.** Construir `BinningResult` y `BinningCardSection`; escribir las seis claves `provides` bajo `"binning"`.

**Ajuste por variable vs batch.** Nikodym usa **`BinningProcess` como motor batch** para mantener un wrapper simple y un `summary()` global. Internamente, cada variable se recupera como `OptimalBinning` con `get_binned_variable(name)` para construir tablas y decisiones de auditoría.

**Solvers y determinismo.**
- Default `solver="cp"` (constraint programming de OptBinning/OR-Tools), `mip_solver="bop"` solo si se usa `solver="mip"`.
- `solver="ls"` no se expone en v1: requiere LocalSolver externo y no está en el stack definido.
- `n_jobs=None` (1 core) por defecto. Paralelismo (`n_jobs=-1`) queda permitido solo si las pruebas de reproducibilidad lo validan para la matriz de versiones.
- `time_limit` se registra en el model card. Si se alcanza sin optimalidad y `require_optimal=True`, se falla ruidosamente.

**Alternativas descartadas.**
- *Binning por cuantiles de EDA como input del modelo:* descartado; no es supervisado y duplica SDD-27.
- *String rules o cortes manuales como default:* descartado; pierde optimalidad y reproducibilidad. Cortes manuales podrían añadirse después como `user_splits` por variable, pero no son el default F1.
- *Filtrar por IV dentro de `binning`:* descartado; mezcla responsabilidades con SDD-07 y dificulta explicar por qué una variable no llegó a selección.
- *Reemplazar columnas en `data.frame`:* descartado; genera ambigüedad y viola la no mutación del dominio `"data"`.

**Complejidad / rendimiento.** Pre-binning y optimización escalan por variable. `max_n_prebins`, `max_n_bins` y `time_limit` acotan el coste. Para datasets grandes, F1 prefiere batch con `BinningProcess` y `n_jobs=None` por determinismo; cualquier paralelismo debe quedar trazado en `BinningCardSection`.

## 8. Casos borde y manejo de errores

- **Target degenerado en Desarrollo** (todo 0 o todo 1): `BinningFitError` antes de llamar a OptBinning.
- **Variable constante / un solo valor no-missing:** se marca como no binneable, se registra `log_decision(regla="variable_constante", ...)` y se omite del `woe_frame` salvo `fail_on_non_binnable=True`, que levanta `BinningFitError`.
- **Variable 100% missing:** se omite con razón `"all_missing"`; si todas las variables quedan omitidas, `BinningFitError`.
- **IV = 0:** si la variable tiene bins válidos pero IV 0, se conserva y se reporta `iv_band="none"`; SDD-07 decide si descarta.
- **Bins con cero buenos o cero malos:** OptBinning refina/mezcla prebins puros; si persiste una tabla con WoE no finito, Nikodym falla antes de publicar `woe_frame` (`BinningFitError`) porque WoE infinito no es defendible en F1.
- **Missing sin observaciones en Desarrollo pero presente en OOT/HO:** transform usa `metric_missing` configurado; con `metric_missing="empirical"` y sin bin empírico disponible, debe caer a WoE neutral 0 o error según la API real validada en implementación. La decisión se registra.
- **Special values declarados pero ausentes:** no es error; se registra conteo 0 en el card si `special_handling="separate"`.
- **Special values presentes en OOT/HO pero no en Desarrollo:** se tratan con `metric_special`; default neutral/empírico según disponibilidad, con `log_decision`.
- **Categórica con rare levels:** niveles bajo `cat_cutoff` se agrupan; se registra nº de niveles agrupados.
- **Categoría no vista en transform:** default WoE neutral 0 (`cat_unknown=None` en OptBinning con `metric="woe"`); se registra conteo por variable y partición.
- **`+inf`/`-inf`:** no se aceptan como numéricos ordinarios. Deben venir declarados como special values en `data.missing.special_values` o se levanta `BinningFitError`/`DataValidationError` con columna y conteo.
- **Variable con dtype no soportado** (listas, dicts, objetos mixtos): error claro con dtype observado y sugerencia de excluir o declarar categórica tras normalizar.
- **Solver timeout / status no óptimo:** con `require_optimal=True`, `BinningFitError`; con `False`, se acepta solo si OptBinning entrega solución factible y se registra `log_decision(regla="solver_no_optimo", ...)`.
- **Falta extra `[scoring]`:** import perezoso de `optbinning` → `MissingDependencyError` con mensaje `"instale nikodym[scoring]"`.
- **Artefactos de `data` ausentes:** `ArtifactNotFoundError` por CT-1 antes de entrar al `execute`.

Toda excepción del módulo desciende de `NikodymError`; los mensajes son en español e incluyen variable, regla, umbral/config y valor observado.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** El diseño v1 no introduce muestreo. OptBinning usa algoritmos deterministas para una misma matriz de versiones, datos y config; el wrapper no consume `rng` salvo que una versión futura active muestreo o pre-binning estocástico.
- **Determinismo esperado.** `(data_hash + config_hash + root_seed + uv.lock) → cortes/WoE/IV idénticos`. Aunque no se use azar explícito, `root_seed` queda en lineage por contrato de `core`.
- **Paralelismo.** `n_jobs=None` por defecto. Si se habilita paralelismo, debe quedar en `BinningCardSection` y pasar `assert_bitwise_reproducible`.
- **Solver y `time_limit`.** La reproducibilidad regulatoria exige no aceptar soluciones parciales silenciosas. `require_optimal=True` es el default; cualquier factible no óptimo es decisión auditada.
- **Golden values.** Tests con dataset pequeño deben fijar cortes, WoE por bin, IV total y transform de missing/special. Los valores se comparan contra cálculos manuales y contra OptBinning 0.20.0 bloqueado.
- **Audit trail (`log_decision`).** Registrar, como mínimo:
  - variable no binneable y razón (`constant`, `all_missing`, `single_class`, `solver_status`);
  - monotonía forzada u override por variable;
  - special values separados vs tratados como missing;
  - bins colapsados o nº de bins efectivo menor al solicitado;
  - IV sospechoso (`>0.50`) o bajo (`<0.02`) como diagnóstico, sin eliminar;
  - categorías no vistas en transform;
  - solver no óptimo / timeout si se permite.
- **Model card / report.** `BinningCardSection` y las tablas por variable alimentan SDD-26: el auditor debe poder reconstruir qué cortes se aprendieron, con qué población, qué WoE/IV resultó y qué variables no pasaron.
- **Lineage.** `binning` no completa `data_hash` ni `config_hash`; los consume implícitamente vía `Study`. Su contribución al lineage es el conjunto de artefactos y decisiones emitidas.

**Riesgo verificado de entorno (2026-06-27, resuelto en B6.0).** En este repo, `uv.lock` resuelve `optbinning==0.20.0`, `ortools==9.15.6755` y `scikit-learn==1.7.2`. La matriz se fija con dos constraints de resolución: `ortools>=9.12` mantiene wheels cp313 y `scikit-learn<1.8` evita el `TypeError` introducido cuando sklearn eliminó el keyword deprecado `force_all_finite`. El piso `scikit-learn>=1.6` del extra `scoring` se mantiene por D-CONV-4. Smoke empírico real en Python 3.12 y 3.13: `OptimalBinning.fit(...)` termina `status=OPTIMAL` con un split válido; solo emite el `FutureWarning` esperado (`force_all_finite` renombrado a `ensure_all_finite`), capturado puntualmente en el test de compatibilidad. La solución es reversible: retirar/subir el techo cuando OptBinning publique una versión que use `ensure_all_finite` y no fije `ortools<9.12`.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymTransformer`, `SeedManager`, `MissingDependencyError`, `NikodymError`, `Registry`.
- SDD-02 (`data`): artefactos `frame`, `labels`, `splits`, `special`; `SpecialValuePolicy`/`MaskedFrame`; particiones Dev/HO/OOT; target binario.
- SDD-05 (convenciones): config Pydantic, hook diferido, `config_hash`, naming, UI metadata.
- Opcional de lectura: SDD-27 (`eda`) para contraste descriptivo; no dependencia dura.

**Aguas abajo.**
- SDD-07 (`selection`) consume `summary`, `tables` y `woe_frame`.
- SDD-08 (`model`) consume `woe_frame` y `woe_column_map` para logística.
- SDD-09 (`scorecard`) consume bins/WoE + coeficientes del modelo.
- SDD-11 (`performance`/`stability`) consume transformaciones y tablas por muestra/período.
- SDD-26 (`report`) consume `tables`, `summary`, `binning_card` y figuras derivadas.

**Externas.**

| Librería | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| optbinning | **0.20.0 en `uv.lock`** (`pyproject`: `>=0.19`) | Apache-2.0 ✅ | `OptimalBinning`, `BinningProcess`, WoE/IV, monotonía | extra `[scoring]` |
| ortools | 9.15.6755 en `uv.lock` por constraint `>=9.12` | Apache-2.0 ✅ | solver CP/MIP transitivo de OptBinning | transitive `[scoring]` |
| scikit-learn | 1.7.2 en `uv.lock` (`pyproject`: `>=1.6`; constraint uv `<1.8`) | BSD-3 ✅ | CART pre-binning, `BaseEstimator`/`TransformerMixin`, compat sklearn | extra `[scoring]` |
| scipy | transitiva/extra scoring | BSD ✅ | dependencia científica de OptBinning/sklearn | extra `[scoring]` |
| pandas/numpy | base | BSD ✅ | DataFrame/Series y arrays | base |
| ropwr | 1.2.0 transitiva | Apache-2.0 ✅ | dependencia de OptBinning | transitive `[scoring]` |

**Núcleo liviano.** `nikodym.core` no importa `optbinning`, `sklearn` ni `scipy`. `nikodym.binning` hace imports perezosos y falla con `MissingDependencyError` si falta el extra.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **Canónicos WoE/IV a mano.** Dataset 2×2 o 3 bins con conteos conocidos: verificar WoE `ln(%Goods/%Bads)`, contribución IV y total. No reimplementar la fórmula en el test de forma opaca: los golden values se calculan y se documentan.
- **Anti-leakage.** Dataset donde OOT contiene una distribución distinta: los cortes/WoE deben ser idénticos a fit en Desarrollo; cambiar OOT no cambia `tables` ni `summary`, solo el `woe_frame` transformado.
- **Special vs missing.** Un centinela declarado por SDD-02 y missing genuino deben producir bins/transformaciones diferenciables cuando `special_handling="separate"`. Con `as_missing`, ambos se fusionan.
- **Categóricas.** Niveles raros agrupados por `cat_cutoff`; categoría no vista en OOT → WoE neutral 0 y evento auditado.
- **Monotonía.** Variable sintética con riesgo creciente: `monotonic_trend="auto_asc_desc"` debe producir event rate monótona. Variable U-shaped: override `valley`/`peak` produce bins válidos y registra decisión.
- **Casos borde.** Constante, un solo valor no-missing, 100% missing, IV=0, target todo 0/1, `inf`, special ausente, variable inexistente en config.
- **Reproducibilidad.** Dos corridas con mismo `data_hash`, config y `uv.lock` producen cortes, tablas y `woe_frame` bit-idénticos. Reordenar filas no cambia cortes si el índice y partición son estables.
- **Contrato `Step`.** `BinningStep.requires` exige los cuatro artefactos de `data`; falta uno → `ArtifactNotFoundError` antes de ejecutar. `provides` se verifica tras ejecución.
- **No mutación.** Snapshot de `study.artifacts.get("data","frame")` antes/después de `BinningStep.execute` permanece igual.
- **Config.** Round-trip YAML de `BinningConfig`; cambio de `max_n_bins` o `monotonic_trend` cambia `config_hash`; `binning` sin importar `nikodym.binning` se mantiene como JSON canónico opaco y al importar se valida como `BinningConfig`.
- **Compatibilidad OptBinning.** Test explícito de import y fit real contra la matriz bloqueada (`optbinning 0.20.0`, `ortools 9.15.6755`, `scikit-learn 1.7.2`). Debe fallar si reaparece el `TypeError` por `force_all_finite`; el `FutureWarning` esperado de sklearn 1.6/1.7 se captura solo dentro del test para no relajar `filterwarnings=error`.
- **Contrato sklearn.** `WoEBinner` multihereda sklearn en el módulo de dominio y pasa checks relevantes de transformer (ajustados para DataFrame/feature names si el check estándar exige ndarray).

Fixtures: `behavior_binning_small.parquet` con variables numéricas/categóricas, special values, missing, particiones Dev/HO/OOT y target conocido; `BinningConfig` mínimo y otro con overrides; `InMemoryAuditSink`.

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas en este borrador (sujetas a revisión de Cami).**
- **D-BIN-1 — WoE con signo `ln(%Goods/%Bads)`.** Es la convención explícita de ESPECIFICACIONES §5.2 y coincide con OptBinning 0.20.0 cuando `Event=bad` y `Non-event=good`. Implica que mayor riesgo → WoE menor. SDD-08/09 deben usar el mismo signo.
- **D-BIN-2 — Default de monotonía `auto_asc_desc`.** Default regulatorio conservador: OptBinning escoge ascendente/descendente de event rate, no formas no monotónicas. Overrides `peak`/`valley`/`convex`/`concave` quedan disponibles con decisión auditada.
- **D-BIN-3 — Special values en bin propio por defecto.** `special_handling="separate"` usa `special_codes` desde SDD-02; `as_missing` queda como override.
- **D-BIN-4 — IV se reporta, no filtra.** La selección por IV vive en SDD-07; `binning` solo etiqueta bands y audita valores extremos.
- **D-BIN-5 — WoE no reemplaza `data.frame`.** Se publica `("binning","woe_frame")` separado, con columnas nuevas `feature__woe` y columnas estructurales; no se escriben columnas en `"data"`.
- **D-BIN-6 — `BinningProcess` batch como motor principal.** Simplifica fit/transform y resumen; tablas por variable se recuperan desde `get_binned_variable`.
- **D-BIN-7 — `require_optimal=True`.** En un proyecto regulatorio, solución factible no probada no pasa en silencio; se falla o se acepta solo con override auditado.

**Decisiones para revisión de Cami.**
- **DEUDA A2/optbinning — RESUELTA en B6.0.** `optbinning 0.21.0` sigue sin servir para Python 3.13 porque fija `ortools<9.12`; por eso la matriz queda en **OptBinning 0.20.0 + OR-Tools 9.15.6755 + scikit-learn 1.7.2**. La incompatibilidad runtime observada con sklearn 1.9.0 se cerró con el constraint reversible `scikit-learn<1.8`: sklearn 1.6/1.7 mantiene `force_all_finite` como keyword deprecado y emite solo `FutureWarning`. El test `tests/unit/test_binning_compatibility.py` ejerce un fit real y captura ese warning de forma local.
- **Convención de signo WoE.** Confirmar `ln(%Goods/%Bads)` frente a la alternativa `ln(%Bads/%Goods)`, y propagar a SDD-08/09 (signos de β, puntos de scorecard y reason codes).
- **Monotonicidad por defecto.** Confirmar `auto_asc_desc` vs `auto`. `auto_asc_desc` es más defendible pero puede perder poder si hay U-shapes genuinas; `auto` puede elegir tendencias no monotónicas.
- **Special values.** Confirmar default `separate` vs tratarlos como missing. La separación es más informativa pero aumenta nº de bins y requiere explicar centinelas.
- **IV.** Confirmar que SDD-06 solo reporta IV y que SDD-07 hace el filtro formal por IV/PSI/correlación.
- **Forma del `woe_frame`.** Confirmar columnas nuevas `feature__woe` sin crudas, vs reemplazar columnas con mismo nombre. La opción propuesta reduce errores aguas abajo.
- **Solver / determinismo / `time_limit`.** Confirmar `solver="cp"`, `mip_solver="bop"`, `time_limit=100`, `require_optimal=True`, `n_jobs=None`. Si `cp` cuelga o no respeta `time_limit` en la matriz real, evaluar `mip`/`bop` o constraint de versiones.
- **Variables no binneables.** Confirmar default `fail_on_non_binnable=False` (omitir y auditar) vs fallar toda la corrida ante cualquier variable problemática.

**Riesgos.**
- **Compatibilidad de dependencias.** Mitigado en B6.0 con matriz lockeada `optbinning 0.20.0` + `ortools 9.15.6755` + `scikit-learn 1.7.2`. Riesgo residual: retirar el techo `<1.8` solo cuando OptBinning use `ensure_all_finite` y mantenga compatibilidad con `ortools>=9.12`.
- **Sobreajuste por bins finos.** Mitigación: `min_bin_size`, `max_n_bins`, monotonía, y revisión de IV sospechoso.
- **Leakage accidental.** Mitigación: tests que demuestren que cambiar OOT no cambia cortes/WoE/IV.
- **Confusión EDA vs binning final.** Mitigación: nombres de artefactos separados y etiquetas `descriptive_iv` vs `iv`.
- **WoE infinito por clases vacías.** Mitigación: restricciones de eventos/no-eventos mínimos y fallo antes de publicar tablas no finitas.
- **Categóricas de alta cardinalidad.** Mitigación: `cat_cutoff`, flags en summary, selección aguas abajo.
- **Dependencia pesada en extra.** Mitigación: imports perezosos y `MissingDependencyError`; `core` permanece liviano.

---

### Citas

- **ESPECIFICACIONES.md** §4 (principios 1 reproducibilidad, 2 auditabilidad, 4 monotonía con riesgo, 8 no reinventar, 9 núcleo liviano, 10 calidad ejemplar), §5.2 (pipeline scorecard: OptBinning, WoE, monotonía, ajuste solo en Desarrollo → transform al resto; WoE/IV y umbrales), §6.3 (árbol de paquetes: `binning/` wrapper OptBinning, WoE, monotonía), §7 (OptBinning Apache-2.0; extras), §8 (tablas binning/WoE como artefactos), §9 (lineage/model card/SR 11-7), §11 (F1 scorecard comportamiento).
- **ROADMAP.md** F1 (Scorecard de comportamiento: binning OptBinning monótono, WoE, ajuste Dev → transform resto; release público v0.1.0).
- **00-INDICE.md** SDD-06 (`binning`, Scoring, F1/T2, depende de 02 y 05), §Convenciones (fórmulas/parámetros regulatorios se citan, no se reescriben).
- **SDD-01 (`core`)** §4 (`Step`, `ArtifactKey`, `requires`/`provides`, `StepAdapter`, `AuditableMixin.log_decision`, `NikodymTransformer`, `MissingDependencyError`), §6 (ArtifactStore namespaced, outputs tabulares con columnas nombradas), §7 (orquestación por orden canónico y validación CT-1), §9 (reproducibilidad y audit trail), §12 D-CORE-7 (CT-1).
- **SDD-02 (`data`)** §1 (data no hace binning ni WoE; solo marca missing/special), §4 (artefactos `frame`, `splits`, `labels`, `special`), §6 (target, `label_status`, `partition`, `ttd`; relación `fuera_de_modelo`), §7 (special values normalizados a NaN con máscara/catalogo), §12 (frontera transversal scorecard vs longitudinal).
- **SDD-05 (convenciones+config)** §4 (API sklearn-like y bases propias; excepciones; naming), §5.1 (sección `binning` en `NikodymConfig`), §5.5 (`config_hash`, `INFRA_SECTIONS`, UI metadata), §6 (DataFrame con columnas nombradas), §11 (round-trip config y cruce Registry).
- **SDD-27 (`eda`)** §1/§7/§12 (EDA usa `qcut` descriptivo, no supervisado, no transforma para modelo; IV descriptivo pre-binning es opt-in y distinto del IV final de SDD-06).
- **docs/normativa_cmf_parametros.md** Advertencias y §7 (parámetros CMF verificados se usan en motores regulatorios, no en `binning`; no confundir scorecard con cálculo de provisión estándar).
- **Verificación local 2026-06-27 — OptBinning 0.20.0 en `uv.lock`:** `OptimalBinning(name='', dtype='numerical', prebinning_method='cart', solver='cp', divergence='iv', max_n_prebins=20, min_prebin_size=0.05, min_n_bins=None, max_n_bins=None, min_bin_size=None, ..., monotonic_trend='auto', ..., cat_cutoff=None, cat_unknown=None, special_codes=None, split_digits=None, mip_solver='bop', time_limit=100, ...)`; `BinningProcess(variable_names, max_n_prebins=20, min_prebin_size=0.05, ..., categorical_variables=None, special_codes=None, binning_fit_params=None, binning_transform_params=None, n_jobs=None, ...)`; `transform(metric='woe', metric_special=0, metric_missing=0, ...)`; `BinningTable.build()` columnas `Bin`, `Count`, `Count (%)`, `Non-event`, `Event`, `Event rate`, `WoE`, `IV`, `JS`; `monotonic_trend` soporta `auto`, `auto_heuristic`, `auto_asc_desc`, `ascending`, `descending`, `concave`, `convex`, `peak`, `peak_heuristic`, `valley`, `valley_heuristic`; licencia Apache-2.0.
