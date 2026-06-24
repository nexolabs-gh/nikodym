# SDD-01 — `core` (núcleo: Study, config, registry, seeding, lineage, orquestación)

| Campo | Valor |
|---|---|
| **SDD** | 01 |
| **Módulo** | `nikodym.core` |
| **Fase** | F0 |
| **Tanda de producción** | T1 (Fundación) |
| **Estado** | Aprobado |
| **Depende de** | — (es la raíz del árbol; no depende de ningún módulo `nikodym`) |
| **Lo consumen** | Todos: SDD-02…25 (toda la librería cuelga de `core`) |
| **Autor / Fecha** | DanIA (síntesis multi-agente + verificación adversarial, context7) / 2026-06-23 · rev. **Tanda 1 Rev** 2026-06-24 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `core` es la fundación *stateful* y agnóstica al dominio de la que cuelga toda la librería: mantiene el estado de un experimento (`Study`), valida y versiona el config declarativo, resuelve componentes por nombre (`Registry`), siembra el azar de forma determinista (`SeedManager`), ensambla el bundle de trazabilidad (`LineageBundle`) y orquesta el pipeline — sin contener lógica de riesgo de crédito ni dependencias pesadas.

**Responsabilidad única (qué SÍ hace).**
- Define el objeto **`Study`** (estado end-to-end serializable y recargable) y orquesta la ejecución de los pasos del pipeline.
- Aloja físicamente las **clases base** de estimadores (`BaseNikodymEstimator` y familias: transformer, classifier, forecaster, survival, provision/ECL), los **mixins** transversales y la **jerarquía de excepciones** (`core.exceptions`).
- Provee la infraestructura de **config** (carga/validación/volcado YAML, `config_hash` canónico, versionado + migraciones) sobre el schema raíz `NikodymConfig`.
- Provee el **`Registry`** con `@register` para resolver `config → clase`.
- Provee el **`SeedManager`** (reproducibilidad total: §4 principio 1) y el ensamblado del **`LineageBundle`** (gobernanza en el núcleo: §4 principio 3).
- Define las **interfaces de gobernanza** (`AuditSink`, `AuditEvent`) que `audit`/`governance` (SDD-03) implementan.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No calcula riesgo de crédito**: ni binning, ni scoring, ni provisiones (eso es de los dominios SDD-06+).
- **No persiste el audit-trail ni produce el model card ni el inventario**: `core` *ensambla* el `LineageBundle` y *emite* `AuditEvent`; **SDD-03 (`audit`+`governance`)** los registra y produce el model card / inventario.
- **No hace tracking MLflow** (SDD-04) **ni reporte Quarto** (SDD-26): `core` no importa MLflow ni Quarto.
- **No define los sub-schemas de config de cada dominio**: `core` aloja el schema **raíz** `NikodymConfig` y la base común; cada dominio aporta su sub-config (contrato y convenciones en **SDD-05**).
- **No depende de scikit-learn ni de ningún backend de ML/forecasting/UI** (ver D-CORE-1, §12).

---

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Fundación (transversal). Es la raíz del árbol `src/nikodym/` (ESPECIFICACIONES §6.3).
- **Quién lo invoca:** todos los módulos de dominio (heredan las clases base, registran sus componentes, leen su sub-config del `NikodymConfig`, escriben/leen artefactos del `Study`) y las dos interfaces de uso (API programática y UI Streamlit).
- **A quién invoca:** a nadie del proyecto en tiempo de cálculo. **Inversión de dependencias:** `core` define interfaces (`AuditSink`, `Step`, `ProvisionResultLike`) que las capas externas implementan; nunca importa hacia arriba (la UI importa el núcleo, jamás al revés — §6.1). El único acoplamiento es un *auto-discovery* perezoso y tolerante a ausencia para forzar el registro de componentes instalados (§7).

```
            ┌─────────────── ui (SDD-23) ───────────────┐
            │                                            │
  dominios (binning, model, provisioning, …)            │
            │  heredan base classes, registran,          │
            ▼  leen sub-config, usan Study               ▼
        ┌────────────────────  core (SDD-01)  ───────────────┐
        │  Study · Registry · SeedManager · config raíz      │
        │  base classes · LineageBundle · AuditSink (iface)  │
        └───────────────▲───────────────────▲────────────────┘
                        │ implementa AuditSink │ ensambla bundle, lo consume
                 audit+governance (SDD-03)   tracking (SDD-04)
```

**Interacción con el `Study` y el config declarativo.** El `Study` se **construye desde un `NikodymConfig`** validado (la única fuente de verdad del experimento, §4 principio 5). La API y los pasos del pipeline operan **sobre el `Study`**: leen su config, leen/escriben artefactos en su `ArtifactStore`, piden su `Generator` seedeado y emiten eventos de auditoría. La UI es un editor visual del mismo config (§4 principio 6); produce un `NikodymConfig` y desde él un `Study`.

---

## 3. Conceptos y fundamentos

- **`Study` / `Project`** — contenedor mutable del estado end-to-end: config, artefactos producidos por cada paso, resultados/tablas intermedias y metadatos de corrida. Serializable y recargable (§5.1, §6.2). **No es un estimador sklearn** (no tiene `fit/predict`): es el *orquestador* de los estimadores que sí lo son.
- **Config declarativo** — árbol de modelos Pydantic v2 cuya raíz es `NikodymConfig`; **el config ES el experimento** (§4 principio 5). Su contrato y convenciones están en **SDD-05**; su infraestructura (carga/validación/volcado/hash/migración) vive aquí.
- **`Registry`** — tabla de componentes registrados con `@register("logit", domain="model")`, *namespaced* por dominio. El `domain` **es** el nombre de la sección de config (p.ej. `model`, `binning`); resuelve el identificador del config (el discriminador `type` de las uniones discriminadas de SDD-05) a la clase concreta.
- **Reproducibilidad total** (§4 principio 1) — `(datos + config + semilla) → resultado idéntico`. Se materializa con un único `root_seed` y **derivación por nombre** del stream de cada paso: `SeedSequence(entropy=[root_seed, hash_estable(nombre)])`. Como `SeedSequence.spawn(n)` de NumPy es **posicional** (genera `n` hijos por orden), NO se usa para nombrar streams; se usa la **entropía compuesta** `[root_seed, hash(nombre)]`, que es independiente del orden de los pasos. Caveat: los GBDT multihilo no son 100% deterministas.
- **Gobernanza por construcción** (§4 principio 3, §9, SR 11-7) — cada corrida emite un **model card** + un **lineage bundle** (git SHA + hash de datos + config + seed + `uv.lock`). `core` *ensambla* el bundle y *emite* los eventos; SDD-03 los persiste y documenta.
- **`config_hash`** — identidad criptográfica del config: `sha256` del **JSON canónico** (claves ordenadas), no del texto YAML ni del `__hash__` del modelo (ver §5 y D-CORE-3).

> **Fórmulas / parámetros normativos:** `core` no contiene ninguno. Las fórmulas cuantitativas (WoE/IV/PSI, scorecard, Vasicek, ECL, matrices CMF) viven en sus dominios y se citan desde `ESPECIFICACIONES.md` y `normativa_cmf_parametros.md` (00-INDICE, §Convenciones: no se reescriben).

---

## 4. API pública (contrato)

> Firmas **ilustrativas** (contratos, no código final). Identificadores en inglés técnico (convención SDD-05); docstrings y mensajes en español.

```python
# nikodym/core/study.py
class Study:
    def __init__(self, config: NikodymConfig, *, name: str | None = None) -> None: ...
    config: NikodymConfig            # fuente de verdad, frozen (ver §5)
    artifacts: ArtifactStore         # objetos producidos por los pasos (namespaced)
    results: dict[str, Any]          # métricas/tablas intermedias serializables (namespace results["metrics"]: dict[str,float] — contrato §6)
    run_context: RunContext          # presente desde __init__ (status="created"); poblado en run() (lineage, estado, timestamps)
    seed_manager: SeedManager        # reconstruible desde config.repro.seed; NO se serializa (§6)
    # orquestación (modelo de pasos en §7)
    def run(self, steps: list[str] | None = None) -> "Study": ...   # ejecuta el pipeline; devuelve self
    def run_step(self, name: str) -> Any: ...                       # ejecuta UN paso aislado (ver §7)
    # persistencia (como DIRECTORIO, ver §6)
    def save(self, path: str | Path) -> Path: ...
    @classmethod
    def load(cls, path: str | Path, *, trust: bool = False) -> "Study": ...
    # gobernanza (hooks hacia SDD-03; core no la implementa)
    def set_audit_sink(self, sink: "AuditSink") -> None: ...        # invariante: antes de run() (§7)
    def lineage_bundle(self) -> "LineageBundle": ...               # devuelve run_context.lineage (congelado)

# nikodym/core/artifacts.py
class ArtifactStore:
    def __init__(self, audit: "AuditSink" | None = None) -> None: ...   # el Study le inyecta el sink
    def set(self, domain: str, key: str, value: Any, *, overwrite: bool = False) -> None: ...
        # clave existente y overwrite=False -> ArtifactExistsError; overwrite=True -> sobrescribe + AuditEvent("artifact")
    def get(self, domain: str, key: str) -> Any: ...               # ausente -> ArtifactNotFoundError
    def has(self, domain: str, key: str) -> bool: ...
    def keys(self) -> list[tuple[str, str]]: ...

# nikodym/core/registry.py
T = TypeVar("T")
class Registry:
    def register(self, name: str, *, domain: str) -> Callable[[type[T]], type[T]]: ...  # decorador
    def resolve(self, domain: str, name: str) -> type: ...         # ausente -> UnknownComponentError
    def available(self, domain: str) -> list[str]: ...
REGISTRY: Registry                                                 # singleton del paquete
def register(name: str, *, domain: str) -> Callable[[type[T]], type[T]]: ...   # azúcar -> REGISTRY.register

# nikodym/core/seeding.py
class SeedManager:
    def __init__(self, root_seed: int) -> None: ...
    root_seed: int
    def generator_for(self, name: str) -> numpy.random.Generator: ...
        # = numpy.random.default_rng(SeedSequence(entropy=[root_seed, _stable_hash(name)]))
        # determinista, independiente del orden, independiente entre nombres distintos
    def int_seed_for(self, name: str) -> int: ...                  # uint32 estable para random_state (sklearn/GBDT)
    def apply_global(self) -> None: ...                            # ver §7/§9: random.seed; warnea PYTHONHASHSEED
    @staticmethod
    def _stable_hash(name: str) -> int: ...                        # hashlib (NO hash() builtin; ver §9)

# nikodym/core/lineage.py  (modelos Pydantic, serializables)
class LineageBundle(BaseModel):
    git_sha: str | None
    git_dirty: bool
    data_hash: str | None            # sha256 del dataset de entrada; se completa al cierre del run (§9)
    config_hash: str                 # sha256 del JSON canónico del config (core.config.io.config_hash)
    root_seed: int
    uv_lock_hash: str | None
    library_versions: dict[str, str]
    determinism_caveats: list[str]   # p.ej. "GBDT multihilo no determinista"
    created_at: datetime             # UTC
    schema_version: str

class RunContext(BaseModel):
    # run_id/started_at son None hasta run(); así un Study recién construido (status="created") serializa
    # a run_metadata.json SIN valores ficticios (DoD F0: un Study vacío se crea, serializa y recarga).
    run_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: Literal["created", "running", "done", "failed"] = "created"
    lineage: LineageBundle | None = None

# nikodym/core/audit.py  (interfaces hacia SDD-03)
class AuditEvent(BaseModel):
    kind: Literal["run_start", "decision", "artifact", "run_end"]   # los umbrales gatillados van como "decision"
    step: str | None
    payload: dict[str, Any]
    ts: datetime
class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None: ...
class NullAuditSink:      ...   # default en core (no-op); NUNCA None -> log_decision siempre seguro
class InMemoryAuditSink:  ...   # vive en core.audit (sin deps de test); .events: list[AuditEvent]
class FanOutSink:         ...   # AuditSink compositor: __init__(sinks: list[AuditSink]); emit() reparte a todos
                                # (permite combinar el sink de governance (SDD-03) y el de tracking (SDD-04))

# nikodym/core/steps.py
@runtime_checkable              # permite isinstance(obj, Step) en el despacho de §7 (StepAdapter)
class Step(Protocol):           # lo que un dominio implementa para ser orquestable (ver §7)
    name: str                   # == nombre de su sección de config (== domain)
    def execute(self, study: "Study", rng: numpy.random.Generator) -> Any: ...

# Los estimadores de dominio (fit/transform/predict/compute) NO implementan execute ni name: el orquestador
# los envuelve en un StepAdapter que los adapta al Protocol Step (así core no conoce la API de cada dominio).
class StepAdapter:              # adapta un BaseNikodymEstimator al Protocol Step (ver §7 y "Claves de I/O", §6)
    def __init__(self, domain: str, estimator: "BaseNikodymEstimator") -> None: ...
    name: str                   # == domain
    def execute(self, study: "Study", rng: numpy.random.Generator) -> Any: ...
        # 1) lee sus inputs de study.artifacts bajo las CLAVES DE I/O del dominio (§6);
        # 2) llama estimator.fit(...) y luego transform/predict/predict_proba/compute según la familia;
        # 3) escribe la salida en study.artifacts bajo la clave namespaced estándar del dominio (§6);
        # 4) devuelve el resultado. El mapeo (familia -> método; claves de entrada/salida por dominio) lo fija §6.

# nikodym/core/results.py  (protocolos de salida económica; los implementan SDD-15/16; ver D-CORE-6)
@runtime_checkable
class ProvisionResultLike(Protocol):   # contrato mínimo de la salida de provisión (resuelve la circularidad, §12)
    componentes: "pandas.DataFrame"    # incluye PI, PDI, exposicion, PE (CMF) — invariante PE=PI·PDI·exposicion (lo VALIDA SDD-15, no el Protocol)
    total: float                       # provisión agregada
    por_cartera: "Mapping[str, float]" # total desglosado por cartera (comercial/consumo/vivienda) — lo leen report/governance sin reabrir componentes
    motor: str                         # etiqueta del motor que lo produjo (p.ej. "cmf_standard", "ifrs9_ecl") — distingue origen sin isinstance
    def to_frame(self) -> "pandas.DataFrame": ...   # vista tabular plana para report/export; método (no materializa hasta pedirlo)
@runtime_checkable
class ECLResultLike(ProvisionResultLike, Protocol):   # añade lo específico IFRS 9
    por_instrumento: "pandas.DataFrame"  # columnas PD, LGD, EAD, ECL, stage (Literal 1/2/3) — granularidad por instrumento
    por_escenario: "Mapping[str, float]" # ECL por escenario ponderado (base/adverso/severo; nunca el escenario medio, ESPEC §5.6)
    # La herencia ECL<-Provision es reutilización del contrato de LECTURA (total/componentes/to_frame para report/governance),
    # NO parentesco de dominio: CMF e IFRS 9 son dos motores SEPARADOS (§5.4). El piso prudencial (max) lo aplica SDD-17.
# (@runtime_checkable solo verifica PRESENCIA de atributos para asserts defensivos; la verificación estructural real es estática (mypy).)
```

**Jerarquía de excepciones** (`nikodym/core/exceptions.py`) — aloja la **raíz `NikodymError`** y las excepciones del **núcleo**. **Regla única:** toda excepción de la librería **desciende de `NikodymError`**; los módulos de dominio **pueden definir sus propias subclases** (de `NikodymError` o de la excepción de core que corresponda) **alojadas en su propio módulo** (p.ej. `DataValidationError` ya en core, pero `GovernanceError`/`TrackingError` viven en su módulo). Así `except NikodymError` captura todo sin centralizar cada clase. SDD-05 §4.3 referencia este árbol y fija mensajes/uso:

```python
class NikodymError(Exception): ...
class ConfigError(NikodymError): ...
class ConfigVersionError(ConfigError): ...        # schema_version "del futuro"
class MigrationNotFoundError(ConfigError): ...     # falta un salto de migración
class DataValidationError(NikodymError): ...
class NotFittedError(NikodymError): ...            # desciende solo de NikodymError (ver D-CORE-5)
class RegistryError(NikodymError): ...
class UnknownComponentError(RegistryError): ...
class DuplicateRegistrationError(RegistryError): ...
class ArtifactNotFoundError(NikodymError): ...
class ArtifactExistsError(NikodymError): ...
class ReproducibilityError(NikodymError): ...      # config_hash no coincide al recargar (manipulación)
class UntrustedStudyError(NikodymError): ...        # load(trust=False) de origen no verificado
class RegulatoryError(NikodymError): ...            # p.ej. violación del piso prudencial CMF (lo usa SDD-15/17)
class MissingDependencyError(NikodymError): ...     # extra no instalado al usar un backend opcional (import perezoso; SDD-25)
```

**Clases base de estimadores** (`nikodym/core/base.py`) — contrato y convenciones en **SDD-05**; viven físicamente aquí:

```python
class BaseNikodymEstimator:          # raíz PROPIA (no hereda de sklearn; ver D-CORE-1)
    config_cls: ClassVar[type[NikodymBaseConfig]]          # cada estimador concreto fija su clase de sub-config (espejo de @register)
        # GANCHO instancia -> clase de sub-config: from_config/_validate_config y el check de SDD-24 §7.2 lo usan.
        # Sin él ese puente no existe (el Registry mapea (domain,name)->clase de estimador, no estimador->config).
    def get_params(self, deep: bool = True) -> dict: ...   # introspección de la firma de __init__ (semántica sklearn)
    def set_params(self, **params) -> "Self": ...          # clave inexistente -> ValueError propio -> ConfigError
    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> "Self": ...   # mapea campos del sub-config a kwargs; EXCLUYE `type` (no es kwarg de __init__) -> evita TypeError
    def _validate_config(self) -> None: ...                # reconstruye cls.config_cls desde get_params() y re-valida
    def _check_fitted(self) -> None: ...                   # levanta NotFittedError propio
    # convención: sin lógica en __init__; validación en fit/compute; atributos fiteados con sufijo _
    # invariante (SDD-24 §7.2): set(get_params()) == set(config_cls.model_fields) − {"type"}  ("_audit" no es campo de sub-config)

class NikodymTransformer(AuditableMixin, BaseNikodymEstimator): ...   # fit/transform (+ fit_transform)
class NikodymClassifier(AuditableMixin, BaseNikodymEstimator): ...    # fit/predict/predict_proba
class BaseForecaster(AuditableMixin, BaseNikodymEstimator): ...       # fit(y,X,fh)/predict(fh,X); cutoff_
class BaseSurvivalEstimator(AuditableMixin, BaseNikodymEstimator): ...# y estructurado (event,time); S(t)/h(t)
class BaseProvisionModel(AuditableMixin, BaseNikodymEstimator): ...   # compute(exposures) -> ProvisionResultLike
class BaseECLModel(BaseProvisionModel): ...                          # compute(...) -> ECLResultLike
    # NOTA anti-acoplamiento: la herencia ECL<-Provision es solo reutilización del contrato compute();
    # NO implica que ECL (IFRS 9) derive de CMF. Son dos motores SEPARADOS (§5.4); SDD-17 toma el máximo.
```

> **Compatibilidad sklearn (mecánica de D-CORE-1).** Las clases de arriba **no** importan sklearn y por sí solas **no** pasan `check_estimator` (en sklearn ≥1.6 los tags exigen heredar `sklearn.base.BaseEstimator`). Un estimador de dominio que requiera el ecosistema sklearn (Pipeline, `check_estimator`, GridSearchCV) **multihereda** sklearn en su propio módulo (donde sklearn ya es dep vía su extra), con sklearn **primero** en el MRO:
> `class WoEBinner(sklearn.base.TransformerMixin, sklearn.base.BaseEstimator, NikodymTransformer): ...`
> Regla dura: `BaseNikodymEstimator.get_params/set_params` replican la **semántica exacta** de sklearn (misma introspección de `__init__`), de modo que el MRO es indiferente al comportamiento. `check_estimator` se corre **solo** sobre esos estimadores de dominio (SDD-24), nunca sobre las bases de `core`.

**Mixins** (`nikodym/core/mixins.py`):

```python
class AuditableMixin:
    _audit: "AuditSink" = NullAuditSink()   # atributo de CLASE (nunca None); el orquestador lo setea por instancia
    # EXCLUIDO de get_params (no es un hiperparámetro); tras clone()/check_estimator cae al NullAuditSink de clase
    def log_decision(self, *, regla: str, umbral: Any, valor: Any, accion: str) -> None: ...
        # construye AuditEvent(kind="decision") y lo emite por self._audit (auditabilidad §4 principio 2)
class SerializationMixin:
    def save(self, path: str | Path) -> None: ...   # joblib de UN estimador fiteado + metadata (versión/hash)
    @classmethod
    def load(cls, path: str | Path, *, trust: bool = False) -> "Self": ...
```

> `Study.save` (directorio, §6) y `SerializationMixin.save` (un estimador *standalone*) son contratos **distintos**: el `ArtifactStore` del `Study` persiste cada artefacto con `joblib` directo bajo `artifacts/<domain>/<key>.joblib`; `SerializationMixin` sirve para guardar/recargar un estimador fuera de un `Study`. Comparten el caveat `trust` (pickle), no el formato.

**Ejemplo de uso (extremo a extremo, pseudocódigo):**

```python
from nikodym.core import Study
from nikodym.core.config import load_config

config = load_config("experimento.yaml")     # valida, migra si aplica, devuelve NikodymConfig frozen
study  = Study(config, name="scorecard-comportamiento")
study.set_audit_sink(governance_sink)          # SDD-03 inyecta el sink real (ANTES de run; opcional)
study.run()                                    # orquesta los pasos del config, seedeados y auditados
study.save("runs/2026-06-23-scorecard")        # directorio: config.yaml + run_metadata + lineage + artifacts/
bundle = study.lineage_bundle()                # SDD-03 lo persiste y arma el model card
```

---

## 5. Configuración (schema Pydantic)

`core` aloja físicamente el schema **raíz** y la base común; **SDD-05** especifica el contrato completo (composición, uniones discriminadas, metadatos UI, versionado). La **lista canónica completa de secciones** de `NikodymConfig` está en SDD-05 §5.1; aquí los campos transversales que `core` necesita para arrancar:

```python
# nikodym/core/config/schema.py
from pydantic import BaseModel, ConfigDict, Field

class NikodymBaseConfig(BaseModel):
    """Base de todo sub-config. Convención SDD-05: cerrado e inmutable."""
    model_config = ConfigDict(extra="forbid", frozen=True)   # typo en YAML -> ValidationError; sin mutación accidental

class ReproConfig(NikodymBaseConfig):
    seed: int = Field(default=42, ge=0)  # default defendible y explícito (§4 principio 1); ge=0 porque SeedSequence rechaza entropía negativa
    strict_determinism: bool = False     # True -> fuerza single-thread en GBDT (caveat multihilo)

class RunConfig(NikodymBaseConfig):
    steps: list[str] | None = None       # None = pipeline por defecto (orden de secciones no-None; ver §7)
    fail_fast: bool = True               # v1: forzado True (ver §8); fail_fast=False reservado

class NikodymConfig(NikodymBaseConfig):  # raíz; la UI genera su formulario desde aquí (§4 principio 6)
    schema_version: str = "1.0.0"        # SemVer del schema; gobierna migración (§8)
    name: str = "nikodym-study"
    repro: ReproConfig = Field(default_factory=ReproConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    data: "DataConfig | None" = None     # opcional (permite el "Study mínimo" del DoD F0; ver §6 y SDD-05 §5.1)
    # … resto de secciones de dominio, todas `<Dominio>Config | None = None` (lista canónica en SDD-05 §5.1).
    # Polimórficas: uniones discriminadas Field(discriminator="type") con tag == key del Registry.
```

**Defaults defendibles.** `extra="forbid"` (un campo desconocido es error, no se ignora — proyecto regulatorio); `frozen=True` (evita mutación accidental; **no** congela contenedores anidados ni vuelve el modelo hashable — la identidad es el `config_hash`, no `__hash__`; ver D-CORE-3); `seed=42` (reproducible *out of the box*, siempre en el lineage); `data` opcional (un `Study` se construye y serializa sin datos; el orquestador exige `data` presente al ejecutar un paso que lo requiera — §8).

**`config_hash` (identidad de lineage).** `config_hash = sha256(json_canónico)` donde `json_canónico = json.dumps(cfg.model_dump(mode="json", by_alias=True, exclude=INFRA_SECTIONS), sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. (`by_alias=True` para que un campo con alias —p.ej. `schema` por colisión con `BaseModel.schema()`— se serialice por su nombre canónico YAML; ver SDD-05 §5.3.) El hash representa el **experimento** (datos + método + semilla), no la *plomería*: se **excluyen las secciones de infraestructura** `INFRA_SECTIONS = {"name", "governance", "audit", "tracking", "report"}` para que cambiar el URI de MLflow, la plantilla de reporte o el nombre del estudio **no** altere la identidad ni la idempotencia del inventario (SDD-03/04). Hashear el **JSON con claves ordenadas** (no el texto YAML) desacopla además la identidad del estilo y la versión de PyYAML y del orden de declaración de campos → el mismo experimento produce el mismo hash entre releases (mitiga R3/R5). **Rutas en `data`.** La sección `data` **sí** entra al `config_hash` (sus parámetros de método: target, particiones, reglas), pero la **ruta de origen** (`data.load.source`) es infraestructura local: el contenido de los datos lo ancla el `data_hash` del lineage, no la ruta. Para que el hash sea estable cross-máquina, `data.load.source` se **normaliza** antes de hashear (se aporta su basename, no la ruta absoluta); el mecanismo exacto lo fija SDD-02/05. (Ver Riesgos §12.)

**Serialización YAML y UI.** El YAML es el formato de persistencia/edición legible (§5.1, §6.2). Carga: `NikodymConfig.model_validate(yaml.safe_load(...))`. Volcado legible: `yaml.safe_dump(cfg.model_dump(mode="json", by_alias=True), sort_keys=False)` (orden de declaración, para revisores). La UI Streamlit (SDD-23) se genera desde `NikodymConfig.model_json_schema()` + introspección, sin duplicar lógica (§4 principio 6). Edición incremental: la UI trabaja sobre un **borrador mutable** (dict) y materializa un `NikodymConfig` *frozen* al correr (reconcilia `frozen=True` con la edición). Preservación de comentarios (ruamel) **diferida** a la UI/CLI.

---

## 6. Contratos de datos (I/O)

**Input.** Un `NikodymConfig` válido. En `run()`, los datasets que los pasos de dominio leen/escriben en el `ArtifactStore` o vía `data/` (SDD-02). `core` no parsea datos crudos.

**Claves de I/O entre pasos (contrato que usa el `StepAdapter`, §4).** Los pasos se comunican **solo** por el `ArtifactStore`, con claves *namespaced* `(domain, key)`. `core` fija el **esqueleto del contrato** (qué método lee/escribe qué) y cada SDD de dominio declara sus claves concretas en su §6:
- El `StepAdapter` de un transformer lee `study.artifacts.get("data", "frame")` (o la salida del paso previo) y escribe su resultado bajo `(domain, "output")` o la clave que el dominio documente.
- El `StepAdapter` de un classifier/forecaster lee features/target del artefacto upstream y escribe predicciones/scores bajo su `domain`.
- **`results` (métricas).** Las métricas escalares van a `study.results["metrics"]` como `dict[str, float]` (namespace canónico que `governance`/SDD-03 lee para el model card sin adivinar claves); el resto de `results[domain]` es libre por dominio. Cada SDD productor de métricas (06+) escribe bajo este namespace.



**Output.** El `Study` con `artifacts`, `results` y `run_context` poblados, persistible como **directorio**:

```
<path>/
├── config.yaml            # round-trip Pydantic↔YAML, legible y diffeable (requisito auditor)
├── run_metadata.json      # RunContext (run_id, timestamps, status)
├── lineage.json           # LineageBundle serializado
└── artifacts/
    └── <domain>/<key>.joblib   # un joblib por artefacto (recarga selectiva, robustez)
```

`save` es **atómico** (escribe a un temporal y renombra). `load(path, trust=False)` reconstruye config, artefactos y `run_context`, y **reconstruye `SeedManager(config.repro.seed)`** (el azar **no** se serializa).

**El azar no se persiste (invariante de reproducibilidad).** El `SeedManager` se reconstruye en `load()` desde `config.repro.seed`; los `Generator` son **efímeros por paso** (se re-derivan por nombre). Un `Generator` con estado consumido nunca se guarda. Invariante post-load: `load(save(s))` reconstruye un `seed_manager` **equivalente** (mismo `root_seed`, misma derivación por nombre), no idéntico en estado interno de `Generator`. Re-ejecutar un paso desde un `Study` recargado es bit-idéntico porque el stream se re-deriva de `[root_seed, hash(nombre)]`, no de un estado serializado.

**Invariantes (pre/post).**
- *Pre-run:* `config` válido; `seed_manager.root_seed == config.repro.seed`; si un paso del pipeline requiere `data`, `config.data is not None` (si no, `ConfigError`).
- *Round-trip config:* `NikodymConfig.model_validate(yaml.safe_load(yaml.safe_dump(c.model_dump(mode="json")))) == c`.
- *Identidad:* misma instancia semántica → mismo `config_hash` (independiente de orden de claves y versión de PyYAML).
- *Determinismo:* dos `Study.run()` con (mismo config + mismos datos + misma semilla + mismo `uv.lock`) → `results` idénticos bit a bit, salvo caveat GBDT multihilo (eliminable con `strict_determinism=True`).
- *Registry:* `resolve(domain, name)` resuelve sii `name` se registró en `domain`; la pareja `(domain, name)` es única.
- *ArtifactStore:* `(domain, key)` se escribe una vez salvo `overwrite=True` (que emite `AuditEvent`).
- *Post-run:* `run_context.lineage` no vacío; `status ∈ {done, failed}`.

---

## 7. Algoritmos y flujo

> Pseudocódigo de alto nivel. `core` orquesta; no implementa lógica de dominio.

**Modelo de orquestación (qué es un paso y cómo se mapea).** Un **paso** es una sección de dominio activa (no-`None`) del `NikodymConfig`. El nombre de la sección **es** el `domain` (p.ej. `binning`, `model`), y el discriminador `type` de esa sección **es** el `name` del componente en el `Registry` (p.ej. `model.type == "logit"` → `REGISTRY.resolve("model", "logit")`). Esto reusa el invariante de SDD-05 (D-CONV-2: `type` == key del Registry). El **pipeline por defecto** es la lista de secciones no-`None` en su **orden canónico de declaración** en `NikodymConfig` (SDD-05 §5.1); `config.run.steps` puede restringir/reordenar. Así el orquestador es **agnóstico al dominio**: no importa dominios, solo resuelve `(sección → (domain, type) → clase → from_config(sub_cfg))`.

**Construcción del `Study`.**
1. `config` (frozen) validado. Crear `SeedManager(config.repro.seed)`; `apply_global()` (ver §9).
2. Inicializar `ArtifactStore(audit=NullAuditSink())`, `results = {}`, `run_context = RunContext()` (con `status="created"` por default; serializable sin correr — §4/§6).

**Auto-registro de componentes** (import time). Cada dominio decora sus clases con `@register(name, domain=...)`. `core` mantiene una **lista explícita** de subpaquetes de dominio y los importa con `try/except ImportError` (tolerante a extras ausentes: un extra no instalado solo omite sus registros, no rompe `core`), disparado al importar `nikodym` (no `entry_points` en v1, coherente con §6.1). Colisión `(domain, name)` → `DuplicateRegistrationError` en import time.

**`Study.run(steps=None)`.**
1. Determinar la lista de pasos (ver "Modelo de orquestación"). Validar prerequisitos (p.ej. un paso que requiere `data` exige `config.data`).
2. `run_context.status = "running"`; emitir `AuditEvent("run_start")`; **iniciar** el `LineageBundle` (git SHA + dirty, `config_hash`, `root_seed`, `uv.lock` hash, `library_versions`, `determinism_caveats`). `data_hash` queda pendiente (los datos se cargan en el primer step).
3. Por cada paso `name`:
   a. `cls = REGISTRY.resolve(domain, type)`; `obj = cls.from_config(sub_cfg)`; `step = obj if isinstance(obj, Step) else StepAdapter(domain, obj)` — un `Step` nativo (p.ej. `DataStep` de SDD-02) se usa tal cual; un estimador de dominio se **envuelve** en `StepAdapter` (§4), que conoce las claves de I/O (§6).
   b. `rng = seed_manager.generator_for(name)` (Generator determinista por nombre).
   c. Inyectar el `AuditSink` en el componente (`step._audit = self._audit`).
   d. `result = step.execute(study, rng)` — el paso lee/escribe `study.artifacts` con claves *namespaced* y registra decisiones vía `log_decision(...)`. El step de datos (SDD-02) completa el `data_hash` del bundle.
   e. Excepción con `fail_fast=True`: `status = "failed"`, emitir `run_end` con la excepción, re-levantar (el `Study` parcial es guardable).
4. `status = "done"`; **congelar** `run_context.lineage` (incl. `data_hash`, `created_at`); emitir `AuditEvent("run_end")`.

**`Study.run_step(name)`.** Ejecuta **un** paso aislado (útil en UI/debug). Resuelve `(domain, type)` igual que `run`; exige que los artefactos prerequisito estén presentes (si no, `ArtifactNotFoundError`); emite solo los eventos del paso (no `run_start`/`run_end` ni re-congela el lineage). No altera `run_context.status`.

**`lineage_bundle()`.** Devuelve `run_context.lineage` **congelado en `run()`** (no recomputa git SHA ni hashes; evita divergencia con la corrida que produjo los artefactos). Levanta si `status == "created"`.

**`set_audit_sink(sink)`.** Debe llamarse **antes** de `run()`; durante/después no afecta el run en curso (ya emitió `run_start` con el sink vigente). Toma **un** sink; para combinar varios (p.ej. el de governance de SDD-03 y el de tracking de SDD-04) se envuelven en `FanOutSink([s1, s2])` (lo construye la capa de orquestación/UI, no el core).

**Seeding (decisión algorítmica clave).** `generator_for(name) = default_rng(SeedSequence(entropy=[root_seed, _stable_hash(name)]))`. La entropía compuesta hace la semilla de cada paso **independiente del orden** y robusta a reordenamientos/inserciones. Alternativas descartadas: `SeedSequence.spawn()` posicional (depende del orden de llamada); un `Generator` global consumido en orden (frágil); `np.random.seed()` legacy (estado global mutable, deprecado). Para libs que exigen `int`: `int_seed_for(name)`.

**Complejidad / rendimiento.** `core` es coordinación: O(nº de pasos). El `Study` v1 asume un único hilo de orquestación; la ejecución paralela de pasos independientes queda fuera de v1, pero el `SeedManager` por-nombre ya la habilitaría sin reescritura.

---

## 8. Casos borde y manejo de errores

- **Config inválido** (campo desconocido por `extra="forbid"`, tipo/rango erróneo, discriminador no registrado): `pydantic.ValidationError` → `ConfigError`, en la **construcción** del `Study` (validación temprana).
- **Paso requiere `data` y `config.data is None`**: `ConfigError` antes de ejecutar el paso.
- **`schema_version` ≠ actual** al `load`: mayor → `ConfigVersionError`; menor sin migración → `MigrationNotFoundError(from, to)`. **Nunca** migración silenciosa. (Detalle del migrador en SDD-05 §5.4.)
- **`load` sin `config_hash` registrado y `trust=False`**: `UntrustedStudyError` (vector pickle, §10). **Divergencia de versiones de librerías** al recargar: **warning** (no aborta); **`config_hash` que no coincide** con el guardado: `ReproducibilityError` (señal de manipulación).
- **Registry**: nombre/dominio inexistente → `UnknownComponentError`; registro duplicado → `DuplicateRegistrationError` (import time).
- **ArtifactStore**: `get` ausente → `ArtifactNotFoundError`; `set` sobre clave existente sin `overwrite` → `ArtifactExistsError`.
- **`fail_fast`**: en v1 está **forzado a `True`** (un paso que falla aborta la corrida con `status="failed"`). `fail_fast=False` (continuar pasos independientes y recolectar errores) queda **reservado** para v2; el campo existe pero v1 ignora `False` con warning.
- **Repo git ausente o *working tree* sucio**: `git_sha=None` / `git_dirty=True` registrados (no aborta; el bundle se marca *no-reproducible-garantizado*). **`uv.lock` ausente**: `uv_lock_hash=None` con warning.
- **Componente estocástico que solo acepta `int`** (XGBoost/LightGBM/CatBoost/sklearn legacy): `int_seed_for(name)`, no `generator_for(name)`.
- **Mutar el config frozen**: Pydantic levanta → `ConfigError`.

Toda excepción de `core` desciende de `NikodymError` y su mensaje (español) incluye, cuando aplica, la **regla, el umbral gatillante y el valor** (§4 principio 2).

---

## 9. Reproducibilidad y auditoría

- **Estocásticos y semilla.** Único `root_seed` (`config.repro.seed`) → cada paso deriva su stream con `SeedSequence(entropy=[root_seed, _stable_hash(name)])` (determinista, por nombre, independiente del orden). `_stable_hash` usa `hashlib` (regla dura: **no** `hash()` builtin, que no es estable entre procesos aun con `PYTHONHASHSEED`). Para libs que exigen `int`: `int_seed_for(name)`.
- **`apply_global()`** (límites honestos). `PYTHONHASHSEED` **solo** tiene efecto si se fija en el **entorno antes** de arrancar el intérprete; setearlo en runtime **no** cambia el *hash randomization* del proceso vivo. Por eso `apply_global()` (a) **verifica y warnea** si `PYTHONHASHSEED` no está fijo, (b) lo propaga como hint a subprocesos *spawneados*, y (c) siembra `random.seed(int_seed_for("python-random"))`. **No** llama `np.random.seed()` legacy (coherente con §7: el azar de NumPy va por `Generator` derivado, no por el estado global).
- **Qué ensambla `core` en el `LineageBundle`** (lo *persiste* SDD-03): git SHA + `git_dirty`, `data_hash` (sha256 del dataset de entrada, completado al cierre del run), `config_hash` (sha256 del JSON canónico), `root_seed`, hash de `uv.lock`, `library_versions`, `created_at` (UTC), `schema_version`, `determinism_caveats`.
- **Qué eventos emite `core`** (vía `AuditSink`): `run_start`; `decision` (cada descarte/corte/umbral gatillado que un paso reporte con `log_decision(regla, umbral, valor, accion)`); `artifact` (escritura/sobrescritura); `run_end`. SDD-03 consume estos eventos + el bundle para el model card y el inventario.
- **Determinismo y caveats.** `(datos + config + semilla + uv.lock) → resultado idéntico bit a bit`. Caveat documentado: GBDT multihilo (XGBoost/LightGBM/CatBoost) no 100% deterministas por la reducción en paralelo; mitigación opcional `strict_determinism=True` → single-thread. `core` **no oculta** el caveat: lo marca en `determinism_caveats`, y el model card (SDD-03) lo refleja.

---

## 10. Dependencias

**Internas:** ninguna. `core` es la raíz. Importa subpaquetes de dominio solo para forzar auto-registro, vía import **diferido y tolerante a ausencia**.

**Externas (todas permisivas — núcleo liviano, §4 principio 9):**

| Librería | Versión mín. | Licencia | Uso en core |
|---|---|---|---|
| pydantic | ≥ 2.5 | MIT ✅ | config, modelos `LineageBundle`/`AuditEvent`. Verificado (context7): `model_validate`/`model_dump(mode="json")`, `Field(discriminator=...)`, `ConfigDict(extra="forbid", frozen=True)`, `model_json_schema`. |
| numpy | ≥ 1.22 | BSD ✅ | `SeedSequence(entropy=…)`/`default_rng`/`Generator`. Verificado: `SeedSequence` admite entropía compuesta; `spawn()` es posicional (no se usa para nombrar). |
| joblib | ≥ 1.3 | BSD ✅ | persistencia de artefactos. **Caveat de seguridad** (verificado): `joblib.load` ejecuta código arbitrario (pickle) → flag `trust`. |
| PyYAML | ≥ 6.0 | MIT ✅ | round-trip YAML legible (`safe_load`/`safe_dump`). *No* interviene en el `config_hash` (que usa JSON canónico). |
| (stdlib) | — | PSF | `hashlib`, `json`, `pathlib`, `datetime`, `importlib`, `subprocess` (git SHA). |

> **Nota (deps de distribución vs imports de `core`).** La tabla lista lo que el **paquete `core`** importa. `pandas` **no** lo importa `core`, pero **sí** es dependencia base de la **distribución** (`pip install nikodym`), porque `data/` y los dominios la usan como contrato de I/O universal (SDD-05 §6); el mapa completo de deps base y extras lo fija **SDD-25**.

**Vetado en `core`:** scikit-learn (y scipy), MLflow (→ SDD-04), Streamlit (→ SDD-23), xgboost/lightgbm/catboost/lifelines/statsmodels (→ dominios, extras opcionales), y **todo copyleft** (GPL; en particular `scikit-survival` GPL-3.0, §7). El patrón sklearn es una **convención** (SDD-05) que cumplen los estimadores de dominio, **no** una dependencia de `core` (D-CORE-1).

`core` no es un *extra*: lo instala siempre `pip install nikodym`.

---

## 11. Estrategia de tests

Detalle transversal en **SDD-24**; lo específico de `core`:

- **Canónicos con resultado conocido.** (a) Round-trip config: `NikodymConfig` → YAML → igual. (b) Seeding: `SeedManager(42).generator_for("binning")` produce una secuencia fija (*golden values*), independiente de `generator_for("selection")`; reordenar los pasos **no** cambia el stream de un paso. (c) `int_seed_for` estable entre procesos (usa `hashlib`). (d) `config_hash` estable: dos instancias semánticamente iguales (distinto orden de kwargs, distinta versión de PyYAML) → mismo hash; cambiar un campo → hash distinto.
- **Propiedades / invariantes (Hypothesis).** Round-trip para configs arbitrarios; `ArtifactStore.get` tras `set` devuelve el mismo objeto, sin `set` levanta, `set` duplicado sin `overwrite` levanta; `Registry.resolve(register(X)) == X` y duplicados levantan; `Study.load(Study.save(s))` reconstruye config, artefactos y un `seed_manager` equivalente.
- **Reproducibilidad.** Dos `Study.run()` con misma (config+datos+semilla) → `results` idénticos (exacto para no-GBDT; `xfail`/caveat para GBDT multihilo salvo `strict_determinism`). Re-ejecución desde un `Study` recargado = bit-idéntica (valida la no-serialización del azar).
- **Lineage.** Un run trivial emite un `LineageBundle` con todos los campos poblados (o `None` justificado con warning), reproducible salvo `created_at`. Secuencia de `AuditEvent` esperada (`run_start → decision → artifact → run_end`) verificada con `InMemoryAuditSink`.
- **Fixtures.** `NikodymConfig()` mínimo construible sin argumentos (DoD F0: se crea, serializa y recarga); dataset sintético pequeño determinista; un `Step` *dummy* que consume su `rng` y escribe un artefacto; `InMemoryAuditSink`.

---

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas en esta síntesis (trazabilidad).**
- **D-CORE-1 — `core` NO depende de scikit-learn.** `BaseNikodymEstimator` es raíz propia (get_params/set_params por introspección, **semántica idéntica a sklearn**). *Porqué:* "núcleo liviano sin backends pesados" (§4 principio 9, §6.1) es no-negociable; sklearn arrastra scipy; permite usar `provisioning`/`governance` sin stack ML. *Consecuencia (especificada):* los estimadores de dominio que requieran compat sklearn **multiheredan** `sklearn.base.*` en su módulo, sklearn **primero** en el MRO; como ambos get_params son semánticamente idénticos, el MRO es indiferente. **`check_estimator` corre solo sobre esos estimadores de dominio** (en sklearn ≥1.6 los tags exigen heredar `BaseEstimator`; las bases de `core` por sí solas no lo pasan, y no lo pretenden). *Alternativa descartada:* heredar sklearn en `core` (más simple, viola el núcleo liviano). **Reversible** si Cami prioriza simplicidad sobre liviandad.
- **D-CORE-2 — `seed` con default explícito 42** (bajo `repro:`), nunca `None`. *Porqué:* reproducibilidad *out of the box* (§4 principio 1) y siempre auditable.
- **D-CORE-3 — Identidad del config vía `config_hash` (sha256 del JSON canónico), no `__hash__`.** `frozen=True` evita mutación accidental pero **no** vuelve el modelo hashable (campos `list`/`dict`) ni congela anidados. *Regla:* los sub-configs evitan `dict`/`list` crudos cuando sea posible (preferir modelos/tuplas); la igualdad/identidad para lineage es el `config_hash`. *Porqué:* el hash debe ser estable, no atado a `__hash__` ni a PyYAML.
- **D-CORE-4 — Persistencia del `Study` como directorio** (YAML legible + JSON + joblib por artefacto), no un blob único. *Porqué:* auditabilidad/diff; recarga selectiva; robustez. **El azar no se persiste** (se reconstruye desde `root_seed`).
- **D-CORE-5 — `NotFittedError` desciende solo de `NikodymError`** (coherente con D-CORE-1). *Caveat (documentado):* un `except sklearn.exceptions.NotFittedError` no atrapa el de Nikodym; los estimadores de dominio que usen `check_is_fitted` de sklearn reciben además el tipo de sklearn, y pueden definir un `NotFittedError(NikodymError, sklearn.exceptions.NotFittedError)` local si necesitan capturar ambos.
- **D-CORE-6 — `ProvisionResultLike`/`ECLResultLike` se quedan como `Protocol` (structural typing), no `dataclass`/Pydantic en core** (Tanda 1 Rev, decisión D4). *Porqué:* un tipo concreto en `core` invertiría la dependencia (forzaría a `provisioning/cmf` e `ifrs9` —SDD-15/16— a importar y heredar un tipo económico de `core`, violando el núcleo liviano §4.9 y reabriendo la circularidad que el Protocol resuelve), y un base compartido difuminaría que **CMF≠IFRS 9 son dos motores separados** (§5.4). *Contrato mínimo endurecido* (§4 `results.py`): `componentes`, `total`, `por_cartera`, `motor`, `to_frame()`; ECL añade `por_instrumento`, `por_escenario`. El Protocol **declara** el invariante `PE=PI·PDI·exposicion` y el piso prudencial, pero **no los ejecuta**: la validación cuantitativa es de los dominios (SDD-15/16/17), no de `core` (§1: "core no calcula riesgo"). El `dataclass` vs Pydantic de la *implementación* sigue delegado a SDD-15/16 (T4).

**Decisiones abiertas (delegadas).**
- **Alcance de SDD-04 — RESUELTO (checkpoint Cami, 2026-06-23).** SDD-04 = `tracking` (MLflow) en F0/T1; el reporte Quarto se separa a **SDD-26 `report`** en T2/F1 (índice actualizado, alineado con el ROADMAP).
- **Formato del `data_hash` — RESUELTO (Tanda 1 Rev, D2):** hash del **contenido lógico por bloques** (`hash_pandas_object` + esquema canónico), que **reemplaza** el sha256 de los bytes del Parquet (no canónico cross-versión) y elimina el fallback muestreado. Detalle en **SDD-02** (D-DATA-2 revisado).
- **Política de migración de `schema_version` — RESUELTO (Tanda 1 Rev, D3):** *version-gate* + migradores `@migration` dict→dict (registro **vacío en v1**; `fail` ruidoso si falta el migrador, nunca migración silenciosa). Detalle en **SDD-05 §5.4**.
- Granularidad de los `AuditEvent` que emiten `core` vs los dominios. *Responsable:* **SDD-03**.

**Riesgos.**
- **Pickle/joblib ata la recarga a versiones de libs.** *Mitigación:* `library_versions` en el lineage + warning en `load`; formatos estables por dominio a futuro.
- **Determinismo frágil** (R3): `hash()` builtin no estable → `_stable_hash` usa `hashlib`; GBDT multihilo → caveat + `strict_determinism`.
- **Drift discriminador `type` vs keys del Registry** → test de propiedad cruzado (SDD-24).
- **`config_hash` cross-máquina:** la sección `data` entra al hash; sin normalizar `data.load.source` (ruta absoluta), el mismo experimento en otra máquina daría hash distinto. *Mitigación:* normalizar la ruta (basename) antes de hashear; el contenido lo ancla el `data_hash`. Mecanismo en SDD-02/05; test de estabilidad cross-máquina en SDD-24.

---

### Citas

- ESPECIFICACIONES.md §4 (principios 1 reproducibilidad, 2 auditabilidad, 3 gobernanza en el núcleo, 5 config declarativo, 6 un núcleo dos interfaces, 8 no reinventar, 9 núcleo liviano, 10 calidad ejemplar), §5.1 (Fundaciones: `Study` serializable), §5.4 (CMF≠IFRS 9, dos motores), §6.1 (core agnóstico; Registry con decoradores; clases base propias), §6.2 (`Study` + config; round-trip YAML; Hydra solo capa fina), §6.3 (árbol de paquetes), §7 (stack y licencias; `scikit-survival` GPL-3.0 vetado), §9 (lineage bundle, model card, SR 11-7), §11 (DoD F0), §12 (R3, R5).
- 00-INDICE.md: SDD-01 (depende de —; lo consumen todos), SDD-03/04/05, §Convenciones (fórmulas/parámetros se citan, no se reescriben).
- Verificado vía context7: **Pydantic v2** (`model_validate`/`model_dump`, `Field(discriminator=...)`, `ConfigDict(extra="forbid", frozen=True)` — no implica hashabilidad con campos mutables), **NumPy** (`SeedSequence` con entropía compuesta; `spawn()` posicional), **joblib** (`load` ejecuta código vía pickle), **scikit-learn** (`BaseEstimator`/atributos `_`/`check_is_fitted`; en ≥1.6 `check_estimator` exige heredar `BaseEstimator`).
