# SDD-02 — `data` (carga, validación de esquema, definición de target, particiones, missing/special, `data_hash`)

| Campo | Valor |
|---|---|
| **SDD** | 02 |
| **Módulo** | `nikodym.data` |
| **Fase** | F0 |
| **Tanda de producción** | T1 (Fundación) |
| **Estado** | Aprobado |
| **Depende de** | SDD-01 (`core`) |
| **Lo consumen** | SDD-06 (`binning`), 07 (`selection`), 08 (`model`), 09–11, 15/16 (`provisioning`), 19 (`markov`), 22 (`validation`); en general todo dominio que parta de un dataset particionado |
| **Autor / Fecha** | DanIA (fan-out Tanda 1) / 2026-06-23 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `data` es la **puerta de entrada de datos** de la librería: carga el dataset crudo, **valida su esquema** (columnas, tipos, rangos, supuestos) de forma trazable, **define el target** (bueno/malo/indeterminado con su ventana de desempeño y exclusiones), **particiona** en Desarrollo / Holdout / Out-of-Time / Through-the-Door sin fuga de información, fija la **política de missing y special values** y produce el **`data_hash`** que ancla la reproducibilidad del experimento en el `LineageBundle` de `core`.

**Responsabilidad única (qué SÍ hace).**
- Define **`DataLoader`** (carga de CSV/Parquet/DataFrame en memoria, tras una interfaz que permite un backend polars interno opcional — D-DATA).
- Define **`SchemaValidator`** (validación declarativa de esquema con **pandera**: columnas, dtypes, nulabilidad, rangos, unicidad, checks de dominio).
- Define **`TargetDefinition`** (deriva la etiqueta binaria `target` y la marca de `indeterminado`/`excluido` desde reglas declarativas: definición de "malo", ventana de desempeño, exclusiones).
- Define **`Partitioner`** (asigna cada observación a Desarrollo/Holdout/OOT/TTD según una **estrategia discriminada** — temporal | aleatoria | por-cohorte —; sugerencia automática **editable**).
- Fija la **política de missing y special values** (catálogo de centinelas, normalización a `NaN`, marcado para que `binning` los trate como bin propio).
- Calcula y **publica el `data_hash`** (sha256 del Parquet canónico del DataFrame de entrada validado) y completa ese campo del `LineageBundle` durante el run (SDD-01 §9).
- Aporta el sub-config **`DataConfig`** (la sección `data` de `NikodymConfig`).

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No hace binning ni WoE**: solo *marca* missing/special; el bin propio para esos valores lo construye **SDD-06 (`binning`)**.
- **No ajusta modelos ni selecciona variables**: solo entrega particiones; la regla *"ajustar solo en Desarrollo → transform al resto"* la **aplican** `binning`/`selection`/`model` (SDD-06/07/08). `data` **garantiza** que las particiones existen y son disjuntas; **no** entrena nada en ellas.
- **No calcula la tasa de incumplimiento por período ni la estabilidad temporal**: eso es **`eda`** (módulo aparte del árbol §6.3).
- **No orquesta**: es un `Step` que `core` invoca (SDD-01 §7); no decide el pipeline.
- **No define el esquema de negocio del cliente**: ofrece el *mecanismo* para declararlo en config; el catálogo de columnas concreto lo aporta el usuario.
- **No persiste el audit-trail**: emite `AuditEvent`/`log_decision` (vía `core`); los registra **SDD-03**.

---

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Fundación (F0/T1). Segundo módulo del árbol, raíz de la rama de datos (`src/nikodym/data/`, ESPECIFICACIONES §6.3).
- **Quién lo invoca:** el orquestador de `core` (es el **primer paso** del pipeline por defecto: `data` es la primera sección no-`None` en el orden canónico de `NikodymConfig`, SDD-05 §5.1). También se usa *standalone* desde la API programática y desde la UI (editor del `DataConfig`).
- **A quién invoca:** a `core` (clases base de no-estimador, excepciones, `SeedManager`, `AuditSink`, contribución al `LineageBundle`). A `pandera` y `pandas` (y opcionalmente `polars`/`pyarrow`). **No** importa ningún módulo de dominio aguas arriba.

```
         config.data (DataConfig)  ──►  Study.run() (core, SDD-01 §7)
                                            │  resuelve (domain="data", type)
                                            ▼
        ┌──────────────────  data (SDD-02)  ──────────────────┐
        │  DataLoader → SchemaValidator → TargetDefinition →   │
        │  Partitioner → política missing/special → data_hash  │
        └──────────────┬───────────────────────────┬──────────┘
                       │ escribe artifacts          │ completa LineageBundle.data_hash
                       ▼ ("data", "dataset"/"splits")▼  + emite log_decision (→ SDD-03)
            binning · selection · model · provisioning · markov · validation
```

**Interacción con el `Study` y el config declarativo.** `data` es un componente **no-estimador** (SDD-05 §4.2: "splitter de particiones / validador de esquema" → no hereda base de estimador; contrato funcional propio). Se registra con `@register("standard", domain="data")` (D-CONV-2: `type` == key del Registry == nombre de sección). Su `execute(study, rng)` (contrato `Step`, SDD-01 §4) lee `study.config.data`, produce los artefactos y los escribe **namespaced** en `study.artifacts` bajo el dominio `"data"`. La UI Streamlit edita el `DataConfig` y previsualiza el resultado de validación/particiones.

---

## 3. Conceptos y fundamentos

> `data` es **agnóstico a fórmulas de riesgo**: no contiene WoE/IV/PD. Define los conceptos de *gobierno del dato* sobre los que el resto del pipeline opera.

- **Definición de target (bueno/malo/indeterminado).** El target es binario (`1 = malo`, `0 = bueno`). En riesgo de crédito el **malo** se define típicamente por mora máxima alcanzada en una **ventana de desempeño** (p.ej. ≥90 días de atraso en 12 meses). Las observaciones en zona gris (p.ej. 30–89 dpd) son **indeterminadas** y se **excluyen** del ajuste (no son ni bueno ni malo limpio). Además hay **exclusiones** estructurales (fraude, fallecidos, cuentas inactivas, ventana de desempeño incompleta). Referencia metodológica: práctica estándar de scorecard de comportamiento (ESPECIFICACIONES §5.1, §5.2). `data` materializa esto como **reglas declarativas sobre columnas** mediante un **mini-DSL** (`columna · operador · valor`, ver §5 `Predicate`/`Rule`), **no** expresiones pandas libres ni fórmulas hardcodeadas.
- **Mini-DSL de reglas (target/exclusión).** Las reglas de "malo", "bueno", "indeterminado" y exclusión se declaran como **predicados estructurados** (`{col, op, value}` con `op` de una **allowlist cerrada**: `==, !=, <, <=, >, >=, in, notin, isna, notna`) combinados por `all_of` (AND) / `any_of` (OR). Un **evaluador propio** traduce cada predicado a una máscara booleana vectorizada de pandas (`df[col] >= value`, `df[col].isin(value)`, `df[col].isna()`, …) y compone las máscaras. **No se usa `DataFrame.eval` ni `eval()` de Python**: la doc oficial de pandas advierte de **inyección de código** con `DataFrame.eval`/`query` ante input no confiable, y **no** existe un "engine seguro" que lo sandboxee (`engine="python"` ejecuta Python top-level; `engine="numexpr"` no es garantía de seguridad). El mini-DSL elimina ese vector por construcción: solo hay operadores de la allowlist y nombres de columna validados contra el esquema (D-DATA-6). Verificado vía context7 (pandas user-guide *enhancingperf*): `DataFrame.eval`/`query` admiten el prefijo `@` para alcanzar **variables locales del entorno** y expresiones NumPy (`@np.floor(a)`), por lo que una expresión libre **no** es un sandbox y no debe construirse desde input no confiable.
- **Ventana de desempeño (performance window).** Período tras la fecha de observación durante el cual se observa el comportamiento que define el target. Una observación cuya ventana **no ha madurado** (la fecha de corte de datos no cubre toda la ventana) se marca `excluido` por *ventana incompleta* (evita target censurado mal etiquetado como bueno).
- **Particiones (ESPECIFICACIONES §5.1).**
  - **Desarrollo (Dev / train):** donde se *ajustan* binning, selección y modelo. (El ajuste lo hacen esos módulos; `data` solo delimita la partición.)
  - **Holdout (HO):** muestra **aleatoria** reservada del mismo período, para validación *out-of-sample* in-time.
  - **Out-of-Time (OOT):** período **posterior** (o anterior) reservado por fecha, para validar estabilidad temporal.
  - **Through-the-Door (TTD):** **toda la población que pasó por la puerta** (incl. indeterminados/excluidos y, en originación, rechazados), usada para análisis de representatividad y *swap-set*; en F1 (comportamiento) sin reject inference (ESPECIFICACIONES §5.2). TTD es un **rol superpuesto**, no una partición disjunta de Dev/HO/OOT (ver §6, invariantes).
- **Fuga de información (leakage).** Que un parámetro estimado vea datos que luego se usan para evaluar. `data` lo previene **estructuralmente**: las particiones son **disjuntas** (Dev ∩ HO ∩ OOT = ∅) y la asignación es **determinista por semilla** y **estable** (una observación no cambia de partición entre corridas). La regla operativa *"fit en Dev, transform en el resto"* la cumplen los módulos consumidores; `data` la **habilita** entregando particiones limpias.
- **Missing vs special values.** *Missing* = ausencia genuina (`NaN`/`null`). *Special values* = **centinelas** con significado de negocio (p.ej. `-99999` = "sin historia crediticia", `-1` = "no aplica"). No se imputan ciegamente: se **normalizan a `NaN` pero se conserva su etiqueta** para que `binning` (SDD-06) les dé un **bin propio** (información, no ruido). `data` produce el **catálogo de special values** y la máscara correspondiente.
- **`data_hash`.** Huella criptográfica del dataset de entrada **ya validado**. Ancla la reproducibilidad: `(data_hash + config_hash + root_seed) → resultado`. Default propuesto (resuelve la decisión abierta de SDD-01 §12): **sha256 del Parquet canónico** del DataFrame de entrada (ver §7 y D-DATA-2).

> **Fórmulas / parámetros normativos:** `data` no contiene ninguno. Los umbrales de mora, ventanas y exclusiones son **parámetros del usuario** en `DataConfig`, no constantes regulatorias. Las fórmulas cuantitativas viven en sus dominios y se citan desde `ESPECIFICACIONES.md` (00-INDICE §Convenciones).

---

## 4. API pública (contrato)

> Firmas **ilustrativas** (contratos, no código final). Identificadores en inglés técnico (convención SDD-05 D-CONV-1: dominio de datos/stats → inglés; no es regulatorio CMF); docstrings y mensajes en **español**. Los cuatro componentes son **no-estimador** (SDD-05 §4.2): no heredan `BaseNikodymEstimator`, no tienen `fit/predict`; usan `AuditableMixin` de `core` para `log_decision` y se construyen con `from_config` (helper propio espejo del de estimadores).

```python
# nikodym/data/loading.py
class DataLoader:
    """Carga el dataset crudo a un pandas.DataFrame. Backend polars opcional tras la misma interfaz (D-DATA-1)."""
    def __init__(self, config: "LoadingConfig") -> None: ...
    @classmethod
    def from_config(cls, cfg: "LoadingConfig") -> "DataLoader": ...
    def load(self, source: "str | Path | pandas.DataFrame", *, audit: "AuditSink | None" = None) -> "pandas.DataFrame":
        ...  # fuente=DataFrame -> passthrough (copia defensiva); ruta -> lee por extensión (csv/parquet)

# nikodym/data/schema.py
class SchemaValidator:
    """Valida columnas/tipos/rangos/supuestos vía pandera. NO muta valores salvo coerción declarada."""
    def __init__(self, config: "SchemaConfig") -> None: ...
    @classmethod
    def from_config(cls, cfg: "SchemaConfig") -> "SchemaValidator": ...
    def build_schema(self) -> "pandera.DataFrameSchema": ...           # traduce SchemaConfig -> pandera
    def validate(self, df: "pandas.DataFrame", *, audit: "AuditSink | None" = None) -> "pandas.DataFrame":
        ...  # lazy=True: agrega TODOS los errores -> SchemaErrors -> DataValidationError (ver §8)

# nikodym/data/target.py
class TargetDefinition:
    """Deriva la etiqueta binaria y la marca bueno/malo/indeterminado/excluido desde reglas declarativas."""
    def __init__(self, config: "TargetConfig") -> None: ...
    @classmethod
    def from_config(cls, cfg: "TargetConfig") -> "TargetDefinition": ...
    def apply(self, df: "pandas.DataFrame", *, audit: "AuditSink | None" = None) -> "LabeledFrame": ...

class LabeledFrame(BaseModel):   # contenedor serializable del resultado de etiquetado
    frame: "pandas.DataFrame"    # df + columnas añadidas: target (Int8 0/1, NA si no-bueno-no-malo), label_status
    target_col: str              # nombre de la columna target (config-driven)
    status_col: str              # "label_status": Enum {bueno, malo, indeterminado, excluido}
    summary: "TargetSummary"     # conteos por clase, tasa de malos, exclusiones por motivo
    model_config = ConfigDict(arbitrary_types_allowed=True)

# nikodym/data/partition.py
class Partitioner:
    """Asigna cada fila a una partición (Dev/HO/OOT) + rol TTD, de forma determinista y editable."""
    def __init__(self, config: "PartitionConfig") -> None: ...
    @classmethod
    def from_config(cls, cfg: "PartitionConfig") -> "Partitioner": ...
    def split(self, lf: "LabeledFrame", *, rng: "numpy.random.Generator",
              audit: "AuditSink | None" = None) -> "PartitionResult": ...
    def suggest(self, lf: "LabeledFrame") -> "PartitionConfig": ...   # sugerencia automática EDITABLE (ver §7)

class Partition(str, Enum):
    # 'fuera_de_modelo' (NO 'excluido') para no colisionar con label_status="excluido":
    # la partición es un concepto distinto del status (ver §6, relación status↔partición).
    DESARROLLO = "desarrollo"; HOLDOUT = "holdout"; OOT = "oot"; FUERA_DE_MODELO = "fuera_de_modelo"

class PartitionResult(BaseModel):
    frame: "pandas.DataFrame"        # df + columna 'partition' (Partition) + columna booleana 'ttd' (rol superpuesto)
    partition_col: str = "partition"
    ttd_col: str = "ttd"
    sizes: dict[str, int]            # tamaños por partición (claves = valores de Partition)
    bad_rates: dict[str, float]      # tasa de malos por partición (clave = valor de Partition)
    strategy_used: str               # discriminador 'type' de la estrategia aplicada (auditoría)
    model_config = ConfigDict(arbitrary_types_allowed=True)

# nikodym/data/special.py
class SpecialValuePolicy:
    """Normaliza centinelas a NaN conservando su etiqueta para que binning (SDD-06) les dé bin propio."""
    def __init__(self, config: "MissingConfig") -> None: ...
    def apply(self, df: "pandas.DataFrame", *, audit: "AuditSink | None" = None) -> "MaskedFrame": ...

class MaskedFrame(BaseModel):
    frame: "pandas.DataFrame"            # special values -> NaN
    special_mask: "pandas.DataFrame"     # bool por (fila, columna): True si era special (no missing genuino)
    special_catalog: dict[str, list]     # columna -> lista de centinelas detectados (para el bin de binning)
    model_config = ConfigDict(arbitrary_types_allowed=True)

# nikodym/data/hashing.py
def data_hash(df: "pandas.DataFrame") -> str: ...
    # sha256 del Parquet canónico (orden de columnas estable, índice incluido); D-DATA-2

# nikodym/data/step.py
@register("standard", domain="data")     # type == key Registry == sección de config (D-CONV-2)
class DataStep:                          # NO-estimador; implementa el Protocol Step de core (SDD-01 §4)
    name: str = "data"
    @classmethod
    def from_config(cls, cfg: "DataConfig") -> "DataStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "PartitionResult":
        ...  # orquesta load -> schema -> special -> target -> partition -> data_hash (ver §7)
```

**Artefactos que `DataStep.execute` escribe en `study.artifacts`** (dominio `"data"`, claves estables — consumidas por SDD-06+):

| clave | tipo | contenido |
|---|---|---|
| `"frame"` | `pandas.DataFrame` | dataset final: validado, etiquetado, particionado, con special→NaN |
| `"splits"` | `PartitionResult` | asignación de particiones + roles TTD + tamaños |
| `"labels"` | `LabeledFrame` | etiquetado (target + status + summary) |
| `"special"` | `MaskedFrame` | máscara y catálogo de special values (input de binning) |
| `"data_hash"` | `str` | sha256 del Parquet canónico (también escrito en `LineageBundle.data_hash`) |

**Ejemplo de uso (extremo a extremo, pseudocódigo):**

```python
from nikodym.core import Study
from nikodym.core.config import load_config

config = load_config("experimento.yaml")          # incluye la sección data: {...}
study  = Study(config, name="scorecard-comportamiento")
study.run(steps=["data"])                          # ejecuta solo el paso de datos

splits = study.artifacts.get("data", "splits")     # PartitionResult
df     = study.artifacts.get("data", "frame")      # listo para binning (SDD-06)
print(splits.sizes)                                # {'desarrollo': 70000, 'holdout': 15000, 'oot': 15000, 'fuera_de_modelo': 4200}
# 'fuera_de_modelo' agrupa indeterminados + excluidos (label_status); ver §6.

# Uso standalone (sin Study), p.ej. en notebook/UI:
from nikodym.core import SeedManager
from nikodym.data import DataLoader, SchemaValidator, TargetDefinition, Partitioner
rng    = SeedManager(seed=42).generator_for("data")   # mismo rng derivado por nombre que usa core
raw    = DataLoader.from_config(cfg.load).load("cartera.parquet")
valid  = SchemaValidator.from_config(cfg.schema).validate(raw)      # DataValidationError si falla
labeled = TargetDefinition.from_config(cfg.target).apply(valid)
result  = Partitioner.from_config(cfg.partition).split(labeled, rng=rng)
```

---

## 5. Configuración (schema Pydantic)

`DataConfig` es el sub-config de la sección `data` de `NikodymConfig` (SDD-05 §5.1). Sigue las convenciones D-CONV: `ConfigDict(extra="forbid", frozen=True)`, todo campo con `title`+`description`, `ge/le` en numéricos, `Literal`/`Enum` en categóricos, **unión discriminada anidada** en la estrategia de partición (`type` resuelto por **factory local** de `data`, **no** por el Registry global — es unión anidada, SDD-05 §3; ver §7).

```python
# nikodym/data/config.py
from enum import Enum
from typing import Annotated, Literal, Union
from pydantic import Field, model_validator
from nikodym.core.config import NikodymBaseConfig

# ── carga ───────────────────────────────────────────────────────────────────
# NOTA DE ORDEN (Pydantic v2): cada clase se define ANTES de usarse como tipo/
# default_factory para no requerir forward refs. Si por organización del módulo
# alguna anotación quedara como string (forward ref), debe cerrarse con
# Model.model_rebuild() tras definir todas las clases del módulo.
class CsvOptions(NikodymBaseConfig):
    sep: str = Field(",", title="Separador")
    decimal: str = Field(".", title="Separador decimal")
    encoding: str = Field("utf-8", title="Codificación")

class LoadingConfig(NikodymBaseConfig):
    source: str | None = Field(None, title="Ruta del dataset",
        description="CSV/Parquet. None si se inyecta un DataFrame en memoria por API.")
    file_format: Literal["auto", "csv", "parquet"] = Field("auto", title="Formato",
        description="'auto' infiere por extensión.")
    backend: Literal["pandas", "polars"] = Field("pandas", title="Backend de carga",
        description="polars interno opcional si el volumen lo exige (D-DATA-1); la API expone pandas.")
    csv_options: CsvOptions = Field(default_factory=CsvOptions, title="Opciones CSV")

# ── esquema ─────────────────────────────────────────────────────────────────
class ColumnSpec(NikodymBaseConfig):
    name: str = Field(..., title="Nombre de columna")
    dtype: Literal["int", "float", "str", "bool", "category", "datetime"] = Field(..., title="Tipo")
    nullable: bool = Field(True, title="Admite nulos")
    required: bool = Field(True, title="Obligatoria",
        description="Si False y ausente, se omite sin error (strict respeta esto).")
    coerce: bool = Field(False, title="Coercionar tipo",
        description="Castea al dtype declarado en validación (pandera coerce).")
    ge: float | None = Field(None, title="Mínimo (>=)")
    le: float | None = Field(None, title="Máximo (<=)")
    isin: tuple[str, ...] | None = Field(None, title="Valores permitidos (categórico)")
    unique: bool = Field(False, title="Valores únicos")

class SchemaConfig(NikodymBaseConfig):
    columns: tuple[ColumnSpec, ...] = Field(default_factory=tuple, title="Columnas esperadas")
    strict: Literal[True, False, "filter"] = Field(False, title="Estrictez de columnas",
        description="True: exige exactamente las columnas declaradas. 'filter': descarta extras. "
                    "False: permite columnas no declaradas.")
    ordered: bool = Field(False, title="Validar orden de columnas")
    index_col: str | None = Field(None, title="Columna índice (identificador de observación)")
    unique_keys: tuple[str, ...] | None = Field(None, title="Llave(s) de unicidad de fila")

# ── target ──────────────────────────────────────────────────────────────────
class PerformanceWindow(NikodymBaseConfig):
    observation_date_col: str = Field(..., title="Fecha de observación")
    months: int = Field(12, ge=1, le=120, title="Meses de ventana de desempeño")
    data_cutoff_col: str | None = Field(None, title="Fecha de corte de datos",
        description="Si se da, una ventana no madurada se marca 'excluido' por ventana incompleta.")

# ── mini-DSL declarativo de reglas (NO expresiones pandas libres; D-DATA-6) ───
class Predicate(NikodymBaseConfig):
    """Comparación atómica 'columna op valor' evaluada por un parser propio con allowlist."""
    col: str = Field(..., title="Columna sobre la que opera")
    op: Literal["==", "!=", "<", "<=", ">", ">=", "in", "notin", "isna", "notna"] = Field(
        ..., title="Operador (allowlist cerrada)",
        description="Único conjunto permitido. 'isna'/'notna' ignoran 'value'.")
    value: float | int | str | bool | tuple[float | int | str | bool, ...] | None = Field(
        None, title="Valor de comparación",
        description="Escalar para comparadores; tupla para 'in'/'notin'; None para 'isna'/'notna'.")

class Rule(NikodymBaseConfig):
    """Conjunción/disyunción de predicados (un nivel). Se evalúa vectorizado; sin eval de Python."""
    all_of: tuple[Predicate, ...] = Field(default_factory=tuple, title="Predicados unidos por AND")
    any_of: tuple[Predicate, ...] = Field(default_factory=tuple, title="Predicados unidos por OR")
    # Semántica: (AND de all_of) AND (OR de any_of). Al menos uno de los dos no vacío
    # (validado por model_validator → ConfigError si la regla es vacía).

class ExclusionRule(NikodymBaseConfig):
    name: str = Field(..., title="Motivo de exclusión", description="Se registra en el audit-trail.")
    rule: Rule = Field(..., title="Regla de exclusión (mini-DSL declarativo)")

class TargetConfig(NikodymBaseConfig):
    target_col: str = Field("target", title="Nombre de la columna target derivada")
    bad_rule: Rule = Field(..., title="Regla de 'malo' (mini-DSL declarativo)",
        description="Mini-DSL columna/op/valor, p.ej. all_of=[{col:max_dpd_12m, op:'>=', value:90}]. malo=1.")
    good_rule: Rule | None = Field(None, title="Regla de 'bueno'",
        description="Si None: bueno = NOT bad AND NOT indeterminate AND NOT excluded.")
    indeterminate_rule: Rule | None = Field(None, title="Regla de 'indeterminado' (zona gris)",
        description="Mini-DSL; estas filas se excluyen del ajuste (target NA). "
                    "Ej.: all_of=[{col:max_dpd_12m,op:'>=',value:30}, {col:max_dpd_12m,op:'<',value:90}].")
    exclusion_rules: tuple[ExclusionRule, ...] = Field(default_factory=tuple, title="Exclusiones estructurales")
    window: PerformanceWindow | None = Field(None, title="Ventana de desempeño")

# ── missing / special values ────────────────────────────────────────────────
class SpecialValueSpec(NikodymBaseConfig):
    columns: tuple[str, ...] | Literal["*"] = Field("*", title="Columnas afectadas")
    sentinels: tuple[float | str, ...] = Field(..., title="Centinelas",
        description="Valores que significan ausencia/no-aplica; se normalizan a NaN conservando etiqueta.")
    label: str = Field(..., title="Etiqueta del special", description="Nombre del bin que usará SDD-06.")

class MissingConfig(NikodymBaseConfig):
    special_values: tuple[SpecialValueSpec, ...] = Field(default_factory=tuple, title="Catálogo de special values")
    max_missing_rate: float = Field(0.99, ge=0.0, le=1.0, title="Tasa máxima de missing por columna",
        description="Columnas por encima se reportan como decisión (no se eliminan aquí; lo hace selection).")

# ── particiones (unión discriminada ANIDADA en data.partition.strategy) ───────
# Polimorfismo por 'type' vía factory LOCAL de data (mapping type→clase), NO el
# Registry global de core: es una unión ANIDADA (no de nivel sección), por lo que
# D-CONV-2 (type == key del Registry) NO aplica (SDD-05 §3, amendment uniones anidadas).
class TemporalSplitConfig(NikodymBaseConfig):
    type: Literal["temporal"] = "temporal"                   # clave del factory local _SPLITTERS
    date_col: str = Field(..., title="Columna de fecha para el corte OOT")
    oot_from: str = Field(..., title="Fecha inicio OOT (ISO 8601)",
        description="Filas con date_col >= oot_from van a OOT; el resto a Dev/HO.")
    holdout_fraction: float = Field(0.2, ge=0.0, lt=1.0, title="Fracción Holdout dentro de in-time")

class RandomSplitConfig(NikodymBaseConfig):
    type: Literal["random"] = "random"                       # clave del factory local _SPLITTERS
    dev_fraction: float = Field(0.7, gt=0.0, lt=1.0, title="Fracción Desarrollo")
    holdout_fraction: float = Field(0.15, ge=0.0, lt=1.0, title="Fracción Holdout")
    oot_fraction: float = Field(0.15, ge=0.0, lt=1.0, title="Fracción OOT (pseudo-OOT aleatorio)")
    stratify_by: str | None = Field(None, title="Estratificar por columna (p.ej. target)")

    @model_validator(mode="after")
    def _fracciones_suman_uno(self) -> "RandomSplitConfig":
        total = self.dev_fraction + self.holdout_fraction + self.oot_fraction
        if abs(total - 1.0) > 1e-9:                       # tolerancia float
            raise ValueError(
                f"dev+holdout+oot debe sumar 1.0; suma observada = {total:.4f}.")
        return self                                       # ValueError → ConfigError (SDD-05 §5.3)

class CohortSplitConfig(NikodymBaseConfig):
    type: Literal["cohort"] = "cohort"                       # clave del factory local _SPLITTERS
    cohort_col: str = Field(..., title="Columna de cohorte (p.ej. añada/vintage)")
    oot_cohorts: tuple[str, ...] = Field(..., title="Cohortes reservadas como OOT")
    holdout_fraction: float = Field(0.2, ge=0.0, lt=1.0, title="Fracción Holdout dentro de in-cohort")

PartitionStrategy = Annotated[
    Union[TemporalSplitConfig, RandomSplitConfig, CohortSplitConfig],
    Field(discriminator="type"),
]

class PartitionConfig(NikodymBaseConfig):
    strategy: PartitionStrategy = Field(..., title="Estrategia de partición")
    ttd_includes_excluded: bool = Field(True, title="TTD incluye indeterminados/excluidos",
        description="TTD = toda la población que pasó por la puerta (rol superpuesto a Dev/HO/OOT).")
    min_bads_per_partition: int = Field(30, ge=0, title="Mínimo de malos por partición",
        description="Por debajo se emite DataValidationError (partición no evaluable; ver §8).")

# ── raíz del sub-config ──────────────────────────────────────────────────────
class DataConfig(NikodymBaseConfig):
    type: Literal["standard"] = "standard"        # == @register("standard", domain="data") (D-CONV-2)
    load: LoadingConfig = Field(default_factory=lambda: LoadingConfig(), title="Carga")
    schema_: SchemaConfig = Field(default_factory=lambda: SchemaConfig(), alias="schema", title="Esquema")
    missing: MissingConfig = Field(default_factory=lambda: MissingConfig(), title="Missing/special")
    target: TargetConfig = Field(..., title="Definición de target")
    partition: PartitionConfig = Field(..., title="Particiones")
```

> **Nota de naming `schema_`.** El riesgo no es un campo de datos sino la **colisión con el método deprecado `BaseModel.schema()`** de Pydantic v2 (reemplazado por `model_json_schema()`): un **campo** llamado `schema` es técnicamente permitido pero ensombrece ese método y Pydantic emite warning. Para evitarlo se usa el atributo Python `schema_` con `alias="schema"`, de modo que en YAML la clave siga siendo `schema:` (legible para el revisor) y el `config_hash` la serialice como `schema`. El round-trip usa `by_alias=True` (§Serialización), por lo que la **carga desde YAML** (por alias `schema:`) y la **serialización** (a `schema`) funcionan con el `NikodymBaseConfig` base (`ConfigDict(extra="forbid", frozen=True)`, SDD-05 §5). **Decisión local de `DataConfig`:** para permitir además construir el modelo por **nombre Python** (`DataConfig(schema_=...)`, p.ej. en tests/UI) sin pasar por el alias, `DataConfig` añade `populate_by_name=True` a su `model_config` (no lo trae el base). (Verificado context7: Pydantic v2 `Field(alias=...)` admite carga por alias por defecto y por nombre solo con `populate_by_name=True`; `by_alias=True` controla la serialización.) Esto es **coherente con el molde**: SDD-05 §5.5 fija que tanto el YAML como el `config_hash` usan `by_alias=True` (serialización canónica única) y autoriza el alias **solo** para evitar colisiones como ésta.

**Defaults defendibles.** `backend="pandas"` (la interfaz expuesta es pandas, D-DATA-1; polars es optimización opt-in). `strict=False` (no romper ante columnas extra del cliente por defecto; el usuario sube a `True`/`"filter"` cuando quiere control total). `window.months=12` (ventana de comportamiento estándar de scorecard). `min_bads_per_partition=30` (piso para que las métricas de discriminación sean evaluables). `holdout/oot` por defecto 70/15/15 (`random`) — práctica común, **editable**. `bad_rule` y `target`/`partition.strategy` son **obligatorios** (`...`): no hay default universal para "qué es malo" ni "cómo se parte"; forzar la decisión explícita es correcto en un proyecto regulatorio.

**Serialización YAML y UI.** Round-trip estándar de SDD-05 §5.5: `yaml.safe_dump(cfg.model_dump(mode="json", by_alias=True), sort_keys=False)`. La UI (SDD-23) renderiza `DataConfig` desde `model_json_schema()`; la unión discriminada `PartitionStrategy` controla el render condicional (selectbox `type` → campos de la variante).

---

## 6. Contratos de datos (I/O)

**Input.**
- `DataLoader.load`: ruta a CSV/Parquet, o un `pandas.DataFrame` en memoria (passthrough con copia defensiva). Índice = identificador de observación (SDD-05 §6: "índice = identificador de observación").
- Cada etapa siguiente recibe el `DataFrame`/contenedor de la anterior. **Pre-condición global:** el dataset tiene las columnas declaradas en `SchemaConfig.columns` y la(s) usadas por `TargetConfig`/`PartitionConfig` (validado por `SchemaValidator`; ausencia → `DataValidationError`, no `KeyError` críptico).

**Output.** El `PartitionResult` (artefacto `"splits"`) + el `frame` final + `data_hash`. Estructura del `frame` final (columnas añadidas por `data`, todas con prefijo neutro para no colisionar con columnas del cliente):
- `target` (Int8, `0/1`, `<NA>` para indeterminado/excluido) — nombre configurable.
- `label_status` (categórica: `bueno`/`malo`/`indeterminado`/`excluido`).
- `partition` (categórica: `desarrollo`/`holdout`/`oot`/`fuera_de_modelo`).
- `ttd` (bool: rol Through-the-Door superpuesto).
- special values originales → `NaN` en sus columnas; máscara en el artefacto `"special"`.

**Relación exacta `label_status` ↔ `partition`** (son **conceptos distintos**: `status` clasifica la *etiqueta*; `partition` ubica la *muestra de modelado*). La correspondencia es total y unívoca:

| `label_status` | ¿elegible para modelar? | `partition` resultante |
|---|---|---|
| `bueno` | sí | `desarrollo` / `holdout` / `oot` (según splitter) |
| `malo` | sí | `desarrollo` / `holdout` / `oot` (según splitter) |
| `indeterminado` | no (target `<NA>`) | `fuera_de_modelo` |
| `excluido` | no (target `<NA>`) | `fuera_de_modelo` |

Regla: `partition == "fuera_de_modelo"` ⟺ `label_status ∈ {indeterminado, excluido}`. Por eso el valor de partición se llama `fuera_de_modelo` y **no** `excluido`: un `indeterminado` **no** es un `excluido` a nivel status, pero ambos quedan fuera del modelado. En `sizes`, la clave `fuera_de_modelo` agrupa indeterminados + excluidos.

**Invariantes (pre/post) — verificables en tests (§11):**
- *Esquema:* tras `validate`, todas las columnas `required=True` existen con su dtype; `strict=True` ⇒ no hay columnas fuera del esquema. Falla ⇒ `DataValidationError` con **todos** los errores agregados (pandera `lazy=True`).
- *Tipo de las columnas de fecha:* si `TargetConfig.window` está presente, `observation_date_col` y (si se da) `data_cutoff_col` deben tener `dtype` datetime **antes** de evaluar la madurez de la ventana — declarándolas `ColumnSpec(dtype="datetime")` o con `coerce=True` en el esquema; si no son datetime, `DataValidationError` (no se evalúa la ventana sobre tipos no comparables).
- *Target exhaustivo y excluyente:* cada fila tiene exactamente **un** `label_status` ∈ {bueno, malo, indeterminado, excluido}. `target` no-nulo **sii** `label_status ∈ {bueno, malo}`. No hay solapamiento entre `bad_rule`, `indeterminate_rule` y exclusiones (si una fila matchea malo *y* exclusión → gana **exclusión**, con precedencia documentada §7; se registra `log_decision`).
- *Particiones disjuntas:* `Dev`, `HO`, `OOT`, `fuera_de_modelo` particionan el conjunto de filas (∪ = total, ∩ = ∅). Las filas con `label_status ∈ {indeterminado, excluido}` van a `partition="fuera_de_modelo"` (no entran a Dev/HO/OOT), por la equivalencia de la tabla de arriba. **TTD es un rol booleano superpuesto**, no una cuarta partición disjunta.
- *Determinismo de partición:* dada `(misma data + misma config + mismo root_seed)`, la asignación `partition` es **idéntica fila a fila** entre corridas (asignación por hash estable del índice + semilla, no por orden de filas — ver §7). Reordenar las filas de entrada **no** cambia la partición de una observación.
- *Sin leakage estructural:* `OOT` (estrategia temporal/cohorte) no comparte ninguna fila con `Dev`/`HO`; en estrategia `random`, las tres son disjuntas por construcción.
- *Piso de malos:* cada partición no-excluida tiene `≥ min_bads_per_partition` malos; si no, error (§8).
- *`data_hash` estable:* `data_hash(df)` es invariante ante reordenamiento de columnas declarado estable (orden canónico) e idéntico para datasets idénticos; cambia si cambia cualquier valor (D-DATA-2).

---

## 7. Algoritmos y flujo

> Pseudocódigo de alto nivel. `data` es no-estimador: transforma un DataFrame en un DataFrame etiquetado y particionado; no ajusta parámetros.

**`DataStep.execute(study, rng)` — secuencia canónica.**
1. **Cargar.** `df = DataLoader.from_config(cfg.load).load(cfg.load.source or study-injected-df)`. Si `backend="polars"`: leer con polars (lazy) y **`.collect().to_pandas()`** en la frontera (la interfaz pública es pandas; D-DATA-1). Copia defensiva si la fuente es un DataFrame en memoria.
2. **Validar esquema.** `df = SchemaValidator.from_config(cfg.schema_).validate(df)` con **`lazy=True`** (agrega todos los errores). `build_schema()` traduce cada `ColumnSpec` a `pa.Column(dtype, checks=[...], nullable=, coerce=, required=, unique=)`; `ge/le` → `pa.Check.in_range`/`ge`/`le`; `isin` → `pa.Check.isin`; `unique_keys` → `DataFrameSchema(unique=[...])`; `strict`/`ordered`/`index` mapean directo. (API verificada, ver Citas.)
3. **Normalizar special values.** `masked = SpecialValuePolicy(cfg.missing).apply(df)`: por cada `SpecialValueSpec`, reemplaza centinelas por `NaN` en las columnas afectadas, construye `special_mask` y `special_catalog`. Emite `log_decision(regla="special_value", umbral=sentinel, valor=conteo, accion="normalizar_a_nan")` por cada centinela detectado. Reporta columnas con missing > `max_missing_rate` (decisión, **no** elimina).
4. **Definir target.** `labeled = TargetDefinition(cfg.target).apply(masked.frame)`:
   a. Si hay `window` y `data_cutoff_col`: marcar `excluido(ventana_incompleta)` donde `observation_date + months > data_cutoff`. **Pre-requisito:** `observation_date_col` y `data_cutoff_col` deben ser `dtype` datetime (validado/coaccionado por el schema, ver §6); si no, `DataValidationError` antes de evaluar la madurez.
   b. Evaluar `exclusion_rules` con el **evaluador del mini-DSL** (`_eval_rule(df, Rule)` → máscara booleana vectorizada, sin `eval` de Python); marcar `excluido(<name>)`. **Precedencia: exclusión > indeterminado > malo > bueno.**
   c. Evaluar `indeterminate_rule` (mini-DSL) sobre lo no-excluido → `indeterminado`.
   d. Evaluar `bad_rule` (mini-DSL) sobre lo restante → `malo (target=1)`; el resto (o `good_rule` si se dio) → `bueno (target=0)`.
   e. `target = <NA>` para indeterminado/excluido. Construir `TargetSummary` (conteos, tasa de malos, exclusiones por motivo) y `log_decision` por cada motivo de exclusión con su conteo.
5. **Particionar.** `result = Partitioner(cfg.partition).split(labeled, rng=rng)` (usa el `rng` que `core` inyectó en `execute`; ver §9). Resolución del splitter por unión discriminada **anidada** vía **factory local** de `data` — `splitter = _SPLITTERS[cfg.partition.strategy.type](cfg.partition.strategy)` con `_SPLITTERS = {"temporal": TemporalSplitter, "random": RandomSplitter, "cohort": CohortSplitter}` —, **no** el Registry global de `core` (`splitter` no es un dominio/sección de `NikodymConfig`; D-CONV-2 y el test cruzado union↔Registry de SDD-05 §11/SDD-24 aplican solo a uniones de **nivel sección**). Asignación **determinista y estable** (ver "Decisión de partición" abajo). Las filas indeterminadas/excluidas → `partition="fuera_de_modelo"`. Calcular `ttd` (True para todas salvo, si `ttd_includes_excluded=False`, las fuera-de-modelo). Verificar `min_bads_per_partition`.
6. **`data_hash`.** `h = data_hash(masked.frame_final)`; escribir en artefacto `"data_hash"` **y** completar `study.run_context.lineage.data_hash` (SDD-01 §7 paso 3.d: "el step de datos completa el `data_hash` del bundle").
7. **Publicar artefactos** (`study.artifacts.set("data", k, v)` para `frame/splits/labels/special/data_hash`). Devolver `PartitionResult`.

**`Partitioner.suggest(labeled)` — sugerencia automática editable.** Heurística (editable por el usuario; **nunca** se aplica sin pasar por config):
- Si existe una columna fecha plausible (dtype datetime) con rango temporal amplio → proponer `temporal` con `oot_from` = percentil 80 de fechas (último ~20% como OOT) y `holdout_fraction=0.2`.
- Si hay columna de cohorte declarada → proponer `cohort` con las 1–2 cohortes más recientes como OOT.
- Si no hay señal temporal → `random` 70/15/15 estratificado por target.
Devuelve un `PartitionConfig` que la UI/usuario **edita y confirma**; `suggest` no muta el `Study`.

**Decisión de partición (algoritmo clave — anti-leakage y determinismo).**
- **Estable por observación, no por orden:** la asignación usa un hash determinista del **identificador de fila** (índice) combinado con `root_seed`, no el orden posicional ni el estado de un `Generator` consumido en barrido. Para `random`/`holdout`: `u = uniform01(hashlib.blake2b(f"{root_seed}:{idx}"))`; se compara `u` contra los cortes acumulados de fracciones. Así reordenar/insertar filas **no** reasigna observaciones existentes (estabilidad cross-run, requisito anti-leakage del §6). El `rng` que entrega `core` (`generator_for("data")`) se usa para sorteos auxiliares (p.ej. desempates de estratificación), pero la **identidad de partición** cuelga del hash del índice → idéntica aunque cambie el orden.
- **Temporal/cohorte:** OOT se define por **regla determinista** (fecha ≥ `oot_from` / cohorte ∈ `oot_cohorts`); el split Dev/HO dentro del in-time usa el mismo hash-por-índice. Sin azar de orden.

**Decisiones algorítmicas y alternativas descartadas.**
- *Pandera vs Pydantic para esquema tabular.* **Pandera** (D-DATA-3): API declarativa nativa para DataFrames (`DataFrameSchema`/`Column`/`Check`), validación vectorizada, `lazy=True` que **agrega todos los errores** (un solo `DataValidationError` con el reporte completo, no falla en el primer error — crítico para auditoría), soporta backend pandas **y** polars con la misma definición. Pydantic valida fila a fila (lento, sin agregación vectorizada). *Descartada:* Pydantic por-fila.
- *`sklearn.model_selection.train_test_split`.* Descartado para la identidad de partición: depende del orden/estado y no da estabilidad por-observación cross-run. Se usa hash-por-índice propio (también evita meter sklearn en un módulo de Fundación, coherente con núcleo liviano).
- *`data_hash` = sha256 del Parquet canónico* (D-DATA-2) vs hash del CSV crudo o de `pd.util.hash_pandas_object`. Parquet canónico (vía `pyarrow`, orden de columnas fijado, índice incluido, compresión desactivada o fija) da un hash **estable cross-plataforma** del *contenido lógico* (no del estilo de serialización CSV). `hash_pandas_object` es por-fila y sensible a dtype/orden; el CSV crudo es sensible a formato. Para datasets muy grandes (decisión abierta de SDD-01 §12) se ofrece `data_hash` sobre una **muestra determinista + metadatos de forma** como fallback (no default v1).

**Complejidad / rendimiento.** Carga y validación O(n·c) (n filas, c columnas), vectorizado. Particionado O(n) (un hash por fila). El `data_hash` materializa un Parquet en memoria: O(n·c) en tiempo y espacio temporal; para n grande, el fallback muestreado lo acota (decisión abierta §12). Backend polars (lazy) opcional para n que no entra en memoria pandas (D-DATA-1).

---

## 8. Casos borde y manejo de errores

- **Columnas faltantes / tipo errado / fuera de rango:** `SchemaValidator.validate` con `lazy=True` recolecta **todos** los `pandera.errors.SchemaErrors` y los re-empaqueta en **`DataValidationError`** (de `core.exceptions`) con el reporte completo (columna, check, valor) en **español** (auditabilidad SDD-05 §4.3). Nunca un `KeyError`/`TypeError` críptico.
- **Target ambiguo** (una fila matchea `bad_rule` *y* `indeterminate_rule`, o malo *y* exclusión): se resuelve por **precedencia documentada** (exclusión > indeterminado > malo > bueno, §7) y se registra `log_decision`. **No** se levanta error (es ambigüedad esperable); sí se reporta en el `summary` el conteo de solapamientos para revisión.
- **Clase vacía** (cero malos, o cero buenos, en el total o en una partición): `DataValidationError` (`"La partición 'oot' tiene 0 malos; mínimo configurado = 30."`). Un modelo no es entrenable/evaluable sin ambas clases — fallar temprano y claro.
- **Partición vacía** (p.ej. `oot_from` posterior a todas las fechas → OOT vacío): `DataValidationError` con la regla y el rango de fechas observado.
- **`bad_rule`/`exclusion_rule` inválida** (columna inexistente, operador fuera de la allowlist, o tipo de `value` incompatible con `op`): el evaluador del mini-DSL valida que **cada `Predicate.col` exista** en el DataFrame y que `op` ∈ allowlist **antes** de construir máscara alguna → `ConfigError` con la regla y la columna/operador ofensor (no un `pandas` error opaco). **No se ejecuta código arbitrario**: el mini-DSL solo compone máscaras booleanas vectorizadas (`==`, `<`, `isin`, `isna`, …); no hay `DataFrame.eval` ni `eval()` de Python, por lo que no existe vector de inyección (D-DATA-6, ver §3).
- **Regla vacía** (`Rule` con `all_of` y `any_of` ambos vacíos): `ConfigError` (un `model_validator` de `Rule` exige al menos un predicado).
- **Fracciones `random` que no suman 1.0** (`dev+holdout+oot ≠ 1.0`): `ConfigError` (el `model_validator` de `RandomSplitConfig` lo valida al construir el config, con la suma observada en el mensaje). Validación temprana, antes de cargar datos.
- **Special values:** un centinela declarado que **no aparece** en la columna → warning (no error; configuración conservadora). Un centinela que es también un valor legítimo (colisión semántica) → responsabilidad del usuario; `data` lo normaliza según lo declarado y lo deja en el audit-trail.
- **Todo missing / columna constante:** se reportan como `log_decision` (no se eliminan aquí; lo hace `selection`, SDD-07). Columna > `max_missing_rate` → decisión registrada.
- **Fuente ausente** (`source` apunta a archivo inexistente y no se inyectó DataFrame): `DataValidationError` (mensaje con la ruta). `source=None` y sin DataFrame inyectado en `execute` → `ConfigError`.
- **`backend="polars"` sin polars instalado:** import perezoso → mensaje accionable (`"backend='polars' requiere el extra [polars]: pip install nikodym[polars]"`), no `ImportError` pelado.
- **Índice no único** cuando `unique_keys`/`index_col` lo exige: `DataValidationError` (filas duplicadas reportadas vía `report_duplicates`).
- **`min_bads_per_partition` no alcanzable** con las fracciones dadas: `DataValidationError` sugiriendo reducir particiones o ampliar la ventana.

Toda excepción de `data` desciende de `NikodymError` (`DataValidationError`/`ConfigError` de `core.exceptions`, SDD-01 §4) y su mensaje en español incluye **regla, umbral gatillante y valor** observado.

---

## 9. Reproducibilidad y auditoría

- **Estocásticos y semilla.** El único componente con azar es `Partitioner` (estrategia `random` y desempates de estratificación). `DataStep.execute(study, rng)` **usa el `rng` que `core` le inyecta** (`generator_for("data")`, derivado por nombre, SDD-01 §7 paso 3.b/3.d) y lo **propaga** a `Partitioner.split(..., rng=rng)`; **no** vuelve a llamar `seed_manager.generator_for("data")` dentro de `execute` (sería redundante y podría divergir). En uso *standalone* (sin `Study`) el rng se obtiene explícito: `SeedManager(seed).generator_for("data")` (ver §4), para mantener idéntica la derivación. **La identidad de partición cuelga de un hash determinista del `root_seed` (crudo) + índice de fila** —`u = uniform01(blake2b(f"{root_seed}:{idx}"))`—, no del estado del `Generator` ni del orden de filas → re-ejecutar es bit-idéntico y reordenar la entrada no reasigna observaciones (invariante §6). *Por qué `root_seed` crudo y no `generator_for("data")` para la identidad:* la identidad de partición debe ser **estable e independiente del nombre del step** que la calcule (anclada solo a la semilla raíz del experimento), mientras que `generator_for("data")` se reserva para los **sorteos auxiliares** (desempates de estratificación) que sí siguen el patrón único de derivación-por-nombre de `core`. Ambos caminos son deterministas; la separación es deliberada. `_stable_hash` usa `hashlib`/`blake2b`, **nunca** `hash()` builtin (regla dura de `core` §9).
- **Qué completa `data` en el `LineageBundle`.** El campo **`data_hash`** (sha256 del Parquet canónico del dataset validado) — resuelve la decisión abierta de SDD-01 §12 (D-DATA-2). Se escribe durante el run (SDD-01 §7 paso 3.d), no antes (los datos se cargan en este paso).
- **Qué eventos emite** (vía `AuditSink`, los persiste SDD-03): `log_decision` por cada **exclusión** (motivo + conteo), cada **special value** normalizado (centinela + conteo), cada **columna sobre `max_missing_rate`**, el **resumen de target** (tasa de malos por clase) y el **resumen de particiones** (tamaños + tasa de malos por partición). Cada uno con `(regla, umbral, valor, accion)` en español. Estas decisiones alimentan el model card (SDD-03) — un auditor reconstruye *qué población entró, qué se excluyó y por qué*.
- **Determinismo y caveats.** `(data + config + seed) → frame/splits/data_hash idénticos`. Sin caveat de paralelismo (no hay GBDT aquí). Único caveat: el `data_hash` requiere que el orden canónico de columnas sea estable (lo fija `data_hash()`); por eso se serializa con orden de columnas ordenado determinísticamente, no el orden de llegada.

---

## 10. Dependencias

**Internas:** `nikodym.core` (`NikodymBaseConfig`, `DataValidationError`/`ConfigError`, `SeedManager`, `AuditableMixin`/`AuditSink`, `REGISTRY`/`@register`, `Study`/`Step`, `LineageBundle`). Ninguna otra (`data` es Fundación; no importa dominios aguas arriba).

**Externas:**

| Librería | Versión mín. | Licencia | Uso en `data` | Extra |
|---|---|---|---|---|
| pandas | ≥ 2.0 | BSD-3 ✅ | DataFrame, máscaras del mini-DSL (sin `df.eval`), I/O CSV. *Piso ≥ 2.0 alineado con SDD-25 (fuente única del piso).* | siempre (data) |
| pandera | ≥ 0.20 | **MIT** ✅ | `DataFrameSchema`/`Column`/`Check`, `validate(lazy=True)`, `SchemaErrors`, `register_check_method`. Verificado (context7): API y backend pandas+polars. | siempre (data) |
| numpy | ≥ 1.22 | BSD ✅ | máscaras, `Generator` (heredado de core) | siempre (data) |
| pyarrow | ≥ 12 | Apache-2.0 ✅ | Parquet canónico para `data_hash`; lectura Parquet | siempre (data) |
| (stdlib) | — | PSF | `hashlib` (blake2b/sha256), `pathlib`, `datetime` | — |
| polars | ≥ 0.20 | **MIT** ✅ | backend de carga opcional (D-DATA-1), lazy para volúmenes grandes | **`[polars]`** opcional, import perezoso |

**Licencias — sin copyleft (D-LIC).** pandera MIT, polars MIT, pyarrow/pandas/numpy permisivas. Ninguna GPL. `polars` es **extra opcional** con import perezoso (mensaje accionable si falta, §8). `pandera` es dependencia base de `data` (no de `core`: `core` no la conoce — coherente con núcleo liviano de SDD-01 §10; `data` es un dominio y puede traer deps propias).

> **Verificación context7 (pandera):** `DataFrameSchema(columns, checks, index, coerce, strict∈{True,False,'filter'}, ordered, unique, add_missing_columns, ...)`; `Column(dtype, checks, nullable, coerce, required, unique)`; `Check.isin/.in_range/.gt/.ge/.le`; `validate(check_obj, lazy=bool, ...)` con `lazy=True` agregando errores en `pandera.errors.SchemaErrors`; `@pandera.extensions.register_check_method(statistics=[...])` para checks de dominio; soporte de backend polars con la misma definición. (Fuente: pandera.readthedocs.io/en/stable.)

---

## 11. Estrategia de tests

Detalle transversal en **SDD-24**; lo específico de `data`:

- **Canónicos con resultado conocido.**
  (a) *Target:* dataset sintético con `max_dpd_12m` conocido → conteos exactos de bueno/malo/indeterminado/excluido; precedencia (fila que matchea malo+exclusión cae en `excluido`) verificada a mano.
  (b) *Particiones:* fracciones 70/15/15 sobre N=10.000 → tamaños dentro de tolerancia y **disjuntos** (Dev∩HO∩OOT=∅, ∪=no-excluidos); estrategia temporal con `oot_from` conocido → OOT == exactamente las filas con fecha ≥ corte.
  (c) *`data_hash`:* dos DataFrames idénticos → mismo hash; permutar columnas (con orden canónico) → mismo hash; cambiar una celda → hash distinto.
  (d) *Esquema:* dataset con 3 violaciones (columna faltante + tipo errado + valor fuera de rango) → un único `DataValidationError` que lista **las tres** (valida `lazy=True`).
- **Propiedades / invariantes (Hypothesis).**
  - *Estabilidad cross-run:* para cualquier permutación de filas de la entrada, la partición de cada observación (por índice) es **idéntica** (no leakage por orden).
  - *Exhaustividad/exclusión:* cada fila tiene exactamente un `label_status`; `target` no-nulo ⟺ `label_status∈{bueno,malo}`.
  - *Disjunción:* `partition` particiona el conjunto; `ttd` es superpuesto.
  - *Determinismo:* mismo `(data, config, seed)` → `splits` idénticos; `data_hash` idéntico.
  - *Round-trip config:* `DataConfig` ↔ YAML (por alias `schema`) preserva igualdad y `config_hash`.
- **Casos borde (tests dirigidos):** clase vacía → `DataValidationError`; OOT vacío por `oot_from` futuro → error; mini-DSL con `Predicate.col` inexistente o `op` fuera de allowlist → `ConfigError`; `Rule` vacía (sin `all_of`/`any_of`) → `ConfigError`; fracciones `random` que no suman 1.0 → `ConfigError` (validación temprana); `backend="polars"` sin extra → mensaje accionable; `min_bads_per_partition` violado → error con la regla.
- **Seguridad del mini-DSL:** un valor de config con sintaxis tipo expresión (p.ej. `value` o `col` conteniendo `@`/`__import__`/llamadas) se trata como **dato literal**, nunca se evalúa como código → test que confirma que no hay ejecución (no existe `eval`/`df.eval` en la ruta).
- **Fixtures.** `cartera_sintetica.parquet` (N pequeño, determinista, con fechas/cohortes y un par de special values `-99999`); `DataConfig` mínimo válido (`random` 70/15/15 + `bad_rule` mini-DSL simple, p.ej. `all_of=[{col:"max_dpd_12m", op:">=", value:90}]`); `InMemoryAuditSink` (de `core`) para capturar la secuencia de `log_decision` esperada (exclusiones + special + summaries).

---

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas en este SDD (trazabilidad).**
- **D-DATA-1 — Interfaz pandas, backend polars opcional.** La API pública (`DataLoader.load`, artefactos) es **pandas**; `polars` es un **extra opcional** (`[polars]`, import perezoso) que solo acelera la carga/normalización internamente y colapsa a pandas en la frontera. *Porqué:* respeta D-DATA de la spec ("pandas; polars interno opcional si el volumen lo exige") sin obligar a todo el ecosistema a conocer polars; mantiene contratos I/O uniformes (SDD-05 §6). *Alternativa descartada:* exponer polars en la API (rompería la uniformidad pandas de todos los dominios consumidores). **Reversible** si los volúmenes reales lo exigen (decisión D2 de la spec, depende de clientes).
- **D-DATA-2 — `data_hash` = sha256 del Parquet canónico** (orden de columnas estable + índice; vía pyarrow). Resuelve la decisión abierta de SDD-01 §12. *Porqué:* hash del *contenido lógico* estable cross-plataforma e independiente del formato de origen (CSV vs Parquet vs DataFrame en memoria). *Alternativa descartada:* `hash_pandas_object` (sensible a dtype/orden) y hash del archivo crudo (sensible a formato). *Fallback documentado* para datasets enormes: muestra determinista + metadatos de forma (no default v1).
- **D-DATA-3 — Esquema con pandera (no Pydantic por-fila).** *Porqué:* validación vectorizada, `lazy=True` que agrega todos los errores (auditoría), misma definición para pandas y polars; licencia MIT. *Alternativa descartada:* Pydantic fila a fila (lento, sin agregación). SDD-05 ya admite "pandera o pydantic"; aquí se fija **pandera**.
- **D-DATA-4 — Componentes de `data` son no-estimador** (SDD-05 §4.2): contrato funcional propio (`load`/`validate`/`apply`/`split`), no `fit/predict`; usan `AuditableMixin` para `log_decision`. *Porqué:* un validador/splitter no tiene parámetros que "aprender"; meterlo en el contrato sklearn sería forzado. La regla *"fit en Dev"* la cumplen binning/selection/model, no `data`.
- **D-DATA-5 — TTD es rol booleano superpuesto**, no una cuarta partición disjunta. *Porqué:* TTD = "toda la población que pasó por la puerta" (incl. indeterminados/excluidos y, futuro, rechazados), conceptualmente ortogonal a Dev/HO/OOT; modelarlo como partición disjunta rompería la unicidad. *Consecuencia:* `partition ∈ {dev,ho,oot,fuera_de_modelo}` + columna `ttd` aparte.
- **D-DATA-6 — Reglas de target/exclusión por un mini-DSL declarativo** (`Predicate`/`Rule`: `columna · operador · valor`, allowlist cerrada de operadores, combinación `all_of`/`any_of`), evaluado por un **parser propio** que compone máscaras booleanas vectorizadas. *Porqué:* declarativo, auditable y serializable en YAML, y **seguro por construcción** — a diferencia de `DataFrame.eval`/`query`, que la doc de pandas advierte como vector de **inyección de código** ante input no confiable y que **no** ofrece un "engine seguro" (`engine="python"` ejecuta Python; `@`-prefix alcanza variables locales; verificado context7, ver §3 y Citas). *Alternativas descartadas:* (a) `df.eval` con expresiones libres — falso sandbox, riesgo regulatorio inaceptable; (b) callables Python en config — no serializables, no auditables, vector de inyección directo. *Riesgo residual:* el mini-DSL es menos expresivo que una expresión libre; reglas complejas se modelan combinando predicados (cobertura suficiente para target/exclusiones de scorecard).

**Decisiones abiertas (delegadas).**
- **Reject inference / muestra TTD de originación.** Fuera de F1 (comportamiento; ESPECIFICACIONES §5.2 y "sub-fase originación"). `data` deja el **gancho** `ttd` y la noción de "rechazados"; el tratamiento (parcelling/fuzzy/reweighting) es de la sub-fase de originación. *Responsable:* DanIA + SDD de originación (post-F1).
- **Política de imputación de missing** (más allá de marcar special→NaN). Decisión: **no imputar en `data`** (binning trata NaN como bin propio, SDD-06). Si algún modelo ML (SDD-12) exige imputación previa, vivirá en su pipeline, no aquí. *Responsable:* SDD-06/SDD-12 (confirmar que ningún consumidor exige imputación en `data`).
- **`data_hash` para datasets que no caben en memoria** (muestra+metadatos vs hash incremental por chunks Parquet). *Sugerencia v1:* Parquet canónico completo; fallback muestreado documentado. *Responsable:* DanIA (cuando haya volumen real, D2 de la spec).
- **Catálogo de columnas estándar de salida** (`target`/`label_status`/`partition`/`ttd`): nombres fijos vs configurables. *Sugerencia:* `target_col` configurable; `label_status`/`partition`/`ttd` con nombres fijos prefijables. *Responsable:* SDD-05↔SDD-06 (que los consume).

**Riesgos.**
- **Mini-DSL mal especificado por el cliente** (regla que silenciosamente etiqueta mal, p.ej. operador o umbral equivocado) → mitigación: validar columnas/operadores referidos + reportar conteos por clase en el `summary` + `log_decision` (un revisor ve la tasa de malos y detecta una regla absurda). El mini-DSL **no** introduce riesgo de inyección (sin `eval`), solo riesgo de *configuración errónea*, mitigado por la traza.
- **Leakage sutil por orden de filas** → mitigado por hash-por-índice (estabilidad cross-run, test de propiedad §11).
- **`data_hash` no estable cross-versión de pyarrow** (cambios de formato Parquet entre releases) → mitigación: fijar opciones de escritura (compresión, versión de formato) en `data_hash()` y registrar `pyarrow` en `library_versions` del lineage (SDD-01); test de golden-hash con la versión pineada en `uv.lock`.
- **Explosión de reglas de exclusión** difícil de auditar → mitigación: cada `ExclusionRule` lleva `name` obligatorio y emite `log_decision` con su conteo (trazabilidad por motivo).

---

### Citas

- **ESPECIFICACIONES.md** §5.1 (Fundaciones: datos — carga, validación de esquema pandera/pydantic, definición de target bueno/malo/indeterminado, ventana de desempeño, exclusiones, política missing/special; particiones Dev/HO/OOT/TTD con sugerencia automática editable), §5.2 (scorecard de comportamiento: *ajuste solo en Desarrollo → transform al resto*, sin reject inference en F1), §6.1 (núcleo liviano, API estilo sklearn donde aplica, clases base propias donde no), §6.3 (árbol de paquetes: `data/` = carga, validación, target, particiones, missing/special), §3.3 (D-DATA: pandas, polars interno opcional; D-LIC sin copyleft; D-CFG Pydantic), §4 (principios 1 reproducibilidad, 2 auditabilidad, 3 gobernanza en el núcleo, 11 doble verificación de datos externos), §12 (D2: polars interno depende de volúmenes reales).
- **ROADMAP.md** F0 (DoD: `data` con validación de esquema, definición de target, particiones Dev/HO/OOT/TTD, missing/special; corrida trivial con lineage reproducible).
- **00-INDICE.md** SDD-02 (`data`, Fundación, F0/T1, depende de 01; lo consumen los dominios de scoring y provisiones), §Convenciones (fórmulas/parámetros se citan, no se reescriben).
- **SDD-01 (`core`)**: `NikodymBaseConfig`/`NikodymConfig` (§5), `DataValidationError`/`ConfigError`/`ReproducibilityError` (`core.exceptions` §4), `SeedManager.generator_for`/`_stable_hash` (§9), `AuditableMixin.log_decision`/`AuditSink` (§4), `Registry`/`@register` (§4), `Study`/`Step.execute`/`ArtifactStore` (§4, §7), `LineageBundle.data_hash` y su decisión abierta delegada a SDD-02 (§12: "Formato del `data_hash`… Responsable: DanIA + autor SDD-02").
- **SDD-05 (convenciones+config)**: sección `data: DataConfig | None` en la lista canónica (§5.1), patrón de unión discriminada `type`==key Registry **para uniones de nivel sección** y **factory local** para uniones **anidadas** como `data.partition.strategy` (§3, §4 D-CONV-2; el test cruzado union↔Registry de §11 aplica solo a nivel sección), base `ConfigDict(extra="forbid", frozen=True)` + `title`/`description`/`ge`/`le`/`Literal` obligatorios (§5.3), componentes **no-estimador** sin base de estimador (§4.2), naming inglés para dominio de datos/stats (§4.4 D-CONV-1), round-trip YAML y `config_hash` con `by_alias=True` (§5.5), input estándar `pandas.DataFrame` con índice = identificador de observación (§6).
- **Verificado vía context7 — pandas** (`/pandas-dev/pandas`, user-guide *enhancingperf*): `DataFrame.eval`/`query` admiten el prefijo `@` para referenciar **variables locales** y atributos/funciones NumPy (`@np.floor(a)`) → una expresión libre **no** es un sandbox y no debe construirse desde input no confiable (fundamento de D-DATA-6: mini-DSL en vez de `df.eval`).
- **Verificado vía context7 — Pydantic v2** (`/pydantic/pydantic`): `Field(alias=...)` se usa para validación por alias por defecto; construir por nombre Python requiere `ConfigDict(populate_by_name=True)`; `model_dump(by_alias=True)`/`serialize_by_alias` controlan la serialización por alias; `model_validator(mode="after")` para validación cruzada de campos (fracciones `random`, regla no vacía).
- **Verificado vía context7 — pandera** (`/websites/pandera_readthedocs_io_en_stable`): `DataFrameSchema(columns, checks, index, coerce, strict∈{True,False,'filter'}, ordered, unique, add_missing_columns, name, description, metadata, drop_invalid_rows)`; `Column(dtype, checks, nullable, coerce, required, unique)`; `Check.isin/.in_range/.gt/.ge/.le` y `Check(callable, element_wise=)`; `validate(check_obj, head, tail, sample, random_state, lazy, inplace)` con `lazy=True` → `pandera.errors.SchemaErrors` agregando todos los errores; `@pandera.extensions.register_check_method(statistics=[...])` para checks de dominio; backend pandas y polars (LazyFrame) con la misma definición de esquema; licencia **MIT**.
