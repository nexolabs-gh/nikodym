# SDD-04 — `tracking` (MLflow: runs, params, metrics, artifacts, Model Registry/inventario)

| Campo | Valor |
|---|---|
| **SDD** | 04 |
| **Módulo** | `nikodym.tracking` |
| **Fase** | F0 |
| **Tanda de producción** | T1 (Fundación) |
| **Estado** | Aprobado |
| **Depende de** | SDD-01 (`core`), SDD-03 (`audit`+`governance`) |
| **Lo consumen** | SDD-03 (governance lee el inventario), SDD-23 (UI: vincula corridas/modelos), SDD-26 (report: enlaza al run), dominios (vía orquestación del `Study`) |
| **Autor / Fecha** | DanIA (fan-out Tanda 1) / 2026-06-23 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `tracking` es la **frontera MLflow** de Nikodym: el único módulo que importa MLflow y traduce un `Study` ejecutado (config + métricas + artefactos + `LineageBundle`) a un **run** persistido y, opcionalmente, a una **versión registrada** en el MLflow Model Registry — que es el **inventario de modelos** (SR 11-7) que consume `governance` (SDD-03).

**Responsabilidad única (qué SÍ hace).**
- Provee la **infraestructura MLflow**: configura el tracking URI (file store local en F0), abre/cierra el **run**, loguea **params** (el config aplanado), **metrics** (los `results` numéricos del `Study`), **artifacts** (el directorio del `Study`, el `lineage.json`, el modelo serializado) y **tags** (git SHA, `config_hash`, `schema_version`).
- Registra el `LineageBundle` y el config como artefactos/tags del run → un run es **autocontenido y reproducible**.
- Implementa el **inventario** vía MLflow Model Registry: `MLflowInventory` **cumple el `Protocol ModelInventory` que define `governance`** (SDD-03 §4.2, inversión de dependencias) — escritura con `register(entry: InventoryEntry)` (`create_model_version` + tags + aliases) e idempotencia por `config_hash`; además expone lectura del inventario (`list_models`, `get_version`, `latest_version`) que `governance`/UI consumen.
- Provee un **`TrackingSink`** que implementa la interfaz `AuditSink` de `core` (SDD-01 §4) y vuelca cada `AuditEvent` como tag/metric/artefacto del run, de modo que el tracking se engancha al `Study` **sin** que `core` conozca MLflow.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No produce el model card ni define la política de inventario/aprobación**: eso es `governance` (SDD-03). `tracking` *persiste* el run y la versión registrada; `governance` *documenta* (model card) y *gobierna* (qué alias —`champion`/`production`— se asigna, próxima revisión). `governance` arma el `InventoryEntry` y **lee/escribe** el inventario que `tracking` materializa (vía el `Protocol ModelInventory`).
- **No calcula nada**: no toca PD/PI ni métricas; solo **registra** lo que el `Study` ya produjo. Coherente con "la IA documenta, nunca calcula" (ESPEC §4): el tracking **no debe alterar el cálculo** (de ahí `autolog=False` por defecto, §5/§12).
- **No genera el reporte Quarto** (SDD-26) ni la UI (SDD-23); expone IDs/URIs para que ellos enlacen.
- **No corre un servidor MLflow remoto en F0**: DoD F0 = tracking **local (file store)**. El modo servidor/DB es config-driven y queda habilitado pero no es el camino por defecto (§8, §12).
- **No vive en `core`**: `core` no importa MLflow (SDD-01 §1, §10). `tracking` es un módulo de infraestructura aparte; MLflow es **extra opcional** (§10, D-TRK-1).

---

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Fundación / infraestructura (transversal), fase F0. Árbol `src/nikodym/tracking/` (ESPEC §6.3, línea `tracking/`).
- **Quién lo invoca:** la **orquestación del `Study`** (SDD-01) al cierre de un `run()` (si `config.tracking` está activo), inyectando el `TrackingSink`; `governance` (SDD-03) para **escribir/leer** el inventario (vía `MLflowInventory.register(entry)`/lectura) y adjuntar el model card al run; la UI (SDD-23) para mostrar/enlazar runs; el report (SDD-26) para enlazar.
- **A quién invoca:** a **MLflow** (única dependencia direccional hacia afuera) y a `core` (lee `Study.config`, `Study.results`, `Study.lineage_bundle()`, implementa `core.audit.AuditSink`). Nunca importa dominios.

```
        ┌──────────── governance (SDD-03) ────────────┐
        │  model card · política de inventario        │
        │            lee inventario ▲                  │
        ▼                            │                 │
   Study.run() (core, SDD-01) ──inyecta TrackingSink──►│
        │   config · results · lineage_bundle()        │
        ▼                                               ▼
   ┌──────────────── tracking (SDD-04) ────────────────┐
   │  TrackingRecorder · TrackingSink(AuditSink)        │
   │  MLflowInventory  (implementa Protocol             │
   │     ModelInventory de SDD-03; MLflow Registry)     │
   └───────────────────────▼────────────────────────────┘
                        MLflow (Apache-2.0)
                   file store local (F0) | server+DB (futuro)
```

**Interacción con el `Study` y el config declarativo.** `tracking` lee su sub-config `TrackingConfig` de `NikodymConfig.tracking` (SDD-05 §5.1). El `TrackingSink` se inyecta como `AuditSink` del `Study` **antes** de `run()` (mismo hook `Study.set_audit_sink`, SDD-01 §4): así cada `AuditEvent` (`run_start`/`decision`/`artifact`/`run_end`) se refleja en el run MLflow sin acoplar `core`. Como `Study.set_audit_sink` toma **un** sink (SDD-01 §4) y `governance` (SDD-03) también inyecta su `JsonlAuditSink`, para que ambos coexistan en un mismo `Study` la orquestación los envuelve en el **`FanOutSink`** de `core.audit` (SDD-01 §4) — `FanOutSink([governance_sink, tracking_sink])` reparte cada `emit()` a todos; `tracking` no define un compositor propio. El `config_hash` (SDD-05) es la **clave de idempotencia/trazabilidad** del run (tag `nikodym.config_hash`).

---

## 3. Conceptos y fundamentos

> `tracking` **no contiene fórmulas ni parámetros normativos** (las cuantitativas viven en sus dominios y se citan desde `ESPECIFICACIONES.md`/`normativa_cmf_parametros.md`, 00-INDICE §Convenciones). Aquí los conceptos de la infraestructura MLflow.

- **Run** — unidad de tracking de MLflow: un contexto con params (config), metrics (resultados), artifacts (ficheros) y tags (metadatos). Un `Study.run()` exitoso ↦ exactamente **un** run MLflow. Se abre con `mlflow.start_run(...)` y se cierra al salir del contexto (verificado context7).
- **Experiment** — agrupador de runs (`mlflow.set_experiment(name)`); por convención `experiment_name = config.tracking.experiment_name` (default = `config.name`). Crear/seleccionar el experiment materializa el directorio `mlruns/` local (verificado context7).
- **Tracking URI** — destino del almacenamiento (`mlflow.set_tracking_uri(uri)`). En F0 es **file store local**: una ruta del filesystem (p.ej. `./mlruns`, o `file:///abs/path`). Si no se fija, MLflow usa `./mlruns` por defecto (verificado context7).
- **Model Registry / inventario** — almacén versionado de modelos: `MlflowClient.create_model_version(name, source, run_id, tags)` (o el atajo `register_model`) crea una **versión** bajo un **nombre registrado**; la promoción se hace con **aliases** mutables (`set_registered_model_alias`, `models:/<name>@<alias>`) y metadatos con **tags** (`set_model_version_tag`) — **los `stages` están deprecados desde MLflow 2.9** (verificado context7, D-TRK-8). Es la materialización del **"inventario versionado = MLflow Registry"** (ESPEC §9). **Restricción dura verificada (context7):** el Model Registry **requiere un backend de base de datos** (sqlite/postgres); el **file store NO soporta el Registry**. Consecuencia de diseño en §5/§7/§12 (D-TRK-2).
- **Artifact** — fichero/directorio asociado al run (`mlflow.log_artifact(path)` / `log_artifacts(dir)`). Nikodym loguea el **directorio del `Study`** (config.yaml + lineage.json + run_metadata.json + artifacts/), de modo que el run MLflow es superconjunto del `Study` serializado.
- **Autolog** — `mlflow.autolog()` instrumenta librerías (sklearn, etc.) para loguear automáticamente. Nikodym lo deja **desactivado por defecto** (`autolog=False`): el logging debe ser **explícito y trazado** (no mágico), y autolog puede envolver/alterar el flujo del estimador (parchea `fit`), lo que riñe con "el tracking no altera el cálculo" (§12, D-TRK-3).
- **`AuditSink` / `AuditEvent`** — interfaces de gobernanza de `core` (SDD-01 §4). `TrackingSink` es una **implementación** que enruta eventos a MLflow (tags/metrics), hermana del `JsonlAuditSink` de SDD-03. Se componen con el **`FanOutSink(AuditSink)` de `core.audit`** (SDD-01 §4), cuyo `__init__(sinks: list[AuditSink])` reparte cada `emit()` a todos los sinks: la orquestación construye `FanOutSink([governance_sink, tracking_sink])` y lo pasa por el hook único `Study.set_audit_sink`. `tracking` **no** define un compositor propio.

---

## 4. API pública (contrato)

> Firmas **ilustrativas** (contratos, no código final). Identificadores en inglés técnico (convención SDD-05 D-CONV-1); docstrings y mensajes en español. MLflow importado de forma **perezosa** (§10).

```python
# nikodym/tracking/recorder.py
class TrackingRecorder:
    """Frontera MLflow: traduce un Study ejecutado a un run (y opcionalmente a una versión del Registry)."""
    def __init__(self, config: "TrackingConfig") -> None: ...
        # resuelve tracking_uri/registry_uri/experiment_name; NO abre run en __init__ (sin lógica, SDD-05 §4.1)

    # ciclo de vida del run (context manager) ---------------------------------
    def start_run(self, study: "Study", *, run_name: str | None = None) -> "RunHandle": ...
        # set_tracking_uri + set_registry_uri + set_experiment; mlflow.start_run(run_name=...)
        # loguea de inmediato params(config) + tags(lineage); devuelve un handle con run_id/artifact_uri
    def __enter__(self) -> "RunHandle": ...      # azúcar: start_run sobre el study inyectado
    def __exit__(self, *exc) -> None: ...        # cierra el run; status="FAILED" si hubo excepción

    # logging explícito (lo llama la orquestación del Study al cierre) ---------
    def log_config(self, config: "NikodymConfig") -> None: ...   # params aplanados + tags de identidad
    def log_metrics(self, results: dict[str, Any], *, step: int | None = None) -> None: ...
        # filtra a numéricos finitos; los no-numéricos van como artefacto results.json (§6/§8)
    def log_lineage(self, bundle: "LineageBundle") -> None: ...   # tags + lineage.json como artefacto
    def log_study_dir(self, path: "str | Path") -> None: ...      # log_artifacts del directorio del Study
    def log_artifact_file(self, path: "str | Path", *, artifact_path: str | None = None) -> None: ...

    # inventario (Model Registry) — atajo de bajo nivel; el camino canónico es MLflowInventory.register(entry)
    def register_model(self, model_uri: str, *, name: str | None = None,
                       tags: dict[str, str] | None = None) -> "ModelVersionRef | None": ...
        # name default = config.tracking.registered_model_name or config.name
        # PRE-CHEQUEA el backend (registry_db_backed, §7): si es file store, NO invoca mlflow.register_model
        #   y devuelve None + warning (NO aborta el run; §8, D-TRK-2). No es MLflow quien "devuelve None".
        # Camino canónico del inventario = MLflowInventory.register(InventoryEntry) (Protocol de SDD-03).

class RunHandle(BaseModel):                 # serializable; lo consumen governance/UI/report
    run_id: str
    experiment_id: str
    artifact_uri: str
    tracking_uri: str

# nikodym/tracking/sink.py
class TrackingSink:                          # implementa core.audit.AuditSink (Protocol)
    """Enruta cada AuditEvent del Study a tags/metrics del run MLflow vivo."""
    def __init__(self, recorder: "TrackingRecorder") -> None: ...
    def emit(self, event: "AuditEvent") -> None: ...
        # run_start -> abre/asegura run; decision -> tag/param contable; artifact -> log_artifact;
        # run_end  -> log_metrics(results)+log_lineage+log_study_dir y cierra el run. NUNCA levanta hacia core (§8)

# nikodym/tracking/inventory.py
class MLflowInventory:
    """IMPLEMENTA el Protocol `ModelInventory` que DEFINE governance (SDD-03 §4.2, inversión de
    dependencias): tracking provee la infraestructura MLflow Registry, governance arma el
    `InventoryEntry` y lo escribe vía este adaptador. Cumple `register`/`get_active`/`list_versions`
    del Protocol; los métodos de LECTURA extra (`list_models`, `get_version`, `latest_version`) son
    propios de tracking (no colisionan con el Protocol)."""
    def __init__(self, config: "TrackingConfig") -> None: ...   # usa registry_uri; abre MlflowClient perezoso

    # --- métodos del Protocol ModelInventory (SDD-03 §4.2): lo que governance consume ---
    def register(self, entry: "InventoryEntry") -> str: ...
        # ESCRITURA: client.create_model_version(name, source=runs:/<run_id>/model, run_id, tags={...})
        # + set_model_version_tag (config_hash, data_hash, git_sha, métricas clave, cartera/motor)
        # + set_registered_model_alias para los aliases declarados (champion/production, gobernados por SDD-03).
        # Idempotencia por config_hash (§7, D-TRK-7): si ya existe una versión con tag
        # nikodym.config_hash == entry.config_hash, NO crea otra; devuelve esa version id.
        # -> version id del Registry. Sin backend DB -> RegistryUnavailableError o None (§8, D-TRK-2).
    def get_active(self, model_name: str) -> "InventoryRecord | None": ...
        # versión apuntada por el alias activo (default 'champion'); None si no hay alias. Devuelve InventoryRecord (liviano).
    def list_versions(self, model_name: str) -> list["InventoryRecord"]: ...   # del Protocol; rehidrata InventoryRecord desde tags

    # --- lectura adicional de tracking (NO en el Protocol; la usa la UI/diagnóstico) ---
    def list_models(self) -> list["RegisteredModelInfo"]: ...
    def get_version(self, name: str, version: str | int) -> "ModelVersionRef": ...   # ausente -> ModelNotFoundError
    def latest_version(self, name: str, *, alias: str | None = None) -> "ModelVersionRef | None": ...
        # alias provisto -> client.get_model_version_by_alias(name, alias); None -> última versión numérica.

class ModelVersionRef(BaseModel):
    name: str
    version: str
    run_id: str | None
    source_uri: str
    aliases: list[str]               # p.ej. ["champion", "production"] (mutables; governance los gobierna)
    tags: dict[str, str]             # metadatos del Registry (incl. estado, cartera, motor)
    config_hash: str | None          # tag propagado: liga la versión al experimento Nikodym
    created_at: datetime

class RegisteredModelInfo(BaseModel):
    name: str
    n_versions: int
    latest: "ModelVersionRef | None"
```

> **Frontera con SDD-03 (contrato de inventario).** `MLflowInventory` **implementa** el `Protocol ModelInventory` que **define** `governance` (SDD-03 §4.2): `governance` arma el `InventoryEntry` (qué metadatos/tags) y `tracking` ejecuta la escritura sobre el Registry (`create_model_version` + `set_model_version_tag` + `set_registered_model_alias`; **aliases y tags reemplazan los `stages` deprecados** — verificado context7). `tracking` **no redefine** el Protocol; lo cumple. `InventoryEntry` (escritura) e `InventoryRecord` (lectura) son de SDD-03 (`governance`); `ModelVersionRef`/`RegisteredModelInfo` son tipos de lectura de **bajo nivel** propios de `tracking` (`get_version`/`latest_version`, UI/diagnóstico). Sin el extra `tracking`, `governance` usa su `NullInventory` (SDD-03 §4.2).

**Convenciones de naming en MLflow (claves estables, contrato auditable).** Tags y params con prefijo `nikodym.` para no colisionar con autolog ni con MLflow:

| Clave MLflow | Tipo | Origen |
|---|---|---|
| `nikodym.config_hash` | tag | `core.config.io.config_hash(study.config)` (identidad, SDD-05) |
| `nikodym.schema_version` | tag | `config.schema_version` |
| `nikodym.git_sha` / `nikodym.git_dirty` | tag | `LineageBundle` |
| `nikodym.root_seed` | tag | `LineageBundle.root_seed` |
| `nikodym.uv_lock_hash` / `nikodym.data_hash` | tag | `LineageBundle` |
| `cfg.<sección>.<campo>` | param | config aplanado (§7) |
| `<dominio>.<métrica>` | metric | `Study.results` numérico |

**Ejemplo de uso (extremo a extremo, pseudocódigo) — el camino que activa la orquestación:**

```python
from nikodym.tracking import TrackingRecorder, TrackingSink

# 1) La orquestación del Study, si config.tracking is not None, antes de run():
recorder = TrackingRecorder(study.config.tracking)
study.set_audit_sink(TrackingSink(recorder))   # mismo hook AuditSink de core (SDD-01 §4)
study.run()                                     # el sink abre el run, loguea decisiones y al run_end vuelca todo

# 2) governance (SDD-03), tras el run, arma el InventoryEntry y lo escribe vía el adaptador de tracking:
inv = MLflowInventory(study.config.tracking)     # implementa el Protocol ModelInventory de SDD-03
version_id = inv.register(entry)                  # entry: InventoryEntry (lo construye governance, SDD-03 §4.2)
recorder.log_artifact_file("model_card.html")    # governance produce el card; tracking solo lo adjunta

# 3) governance lee el inventario para su política SR 11-7:
for e in inv.list_versions("scorecard-comportamiento"):
    ...   # decide aliases (champion/production) y próxima revisión sobre las entradas del inventario
```

---

## 5. Configuración (schema Pydantic)

`tracking` aporta `TrackingConfig(NikodymBaseConfig)`, anidado en `NikodymConfig.tracking: TrackingConfig | None = None` (SDD-05 §5.1). Cerrado e inmutable; cada campo con `title`+`description`; defaults defendibles; `ge/le`/`Literal` donde aplica.

```python
# nikodym/tracking/config.py
from pydantic import Field
from nikodym.core.config import NikodymBaseConfig

class TrackingConfig(NikodymBaseConfig):
    """Configuración del tracking MLflow. Sección 'tracking' de NikodymConfig."""

    enabled: bool = Field(
        True, title="Tracking activo",
        description="Si False, la orquestación no inyecta el TrackingSink ni abre runs (no-op).")
    tracking_uri: str | None = Field(
        None, title="Tracking URI (destino de runs)",
        description="Destino MLflow. None => file store local './mlruns' (DoD F0). "
                    "Acepta 'file:///ruta', 'sqlite:///mlflow.db' o 'http(s)://host' (servidor).")
    registry_uri: str | None = Field(
        None, title="Registry URI (inventario)",
        description="Destino del Model Registry. None => igual que tracking_uri. "
                    "El Registry REQUIERE backend de base de datos (sqlite/servidor): "
                    "con file store, register_model se omite con warning (D-TRK-2).")
    experiment_name: str | None = Field(
        None, title="Nombre del experimento",
        description="Agrupa los runs. None => se usa config.name (resuelto en runtime).")
    registered_model_name: str | None = Field(
        None, title="Nombre del modelo en el inventario",
        description="Nombre bajo el que se versiona en el Model Registry. None => config.name.")
    register_on_success: bool = Field(
        False, title="Registrar modelo al terminar",
        description="Si True y hay backend de Registry, registra el artefacto-modelo al cerrar el run. "
                    "Default False: el registro es una decisión de gobierno (SDD-03), no automática.")
    autolog: bool = Field(
        False, title="Autologging de MLflow",
        description="Default False (regla dura): el tracking NO debe alterar el cálculo ('la IA documenta, "
                    "nunca calcula'); autolog parchea fit() de las librerías. Activar solo con intención explícita.")
    log_study_artifacts: bool = Field(
        True, title="Loguear el directorio del Study",
        description="Adjunta config.yaml + lineage.json + artifacts/ al run (run autocontenido).")
    log_models: bool = Field(
        True, title="Loguear el/los modelo(s) fiteados",
        description="Adjunta el modelo serializado como artefacto 'model/' (prerequisito de register_model).")
    fail_on_tracking_error: bool = Field(
        False, title="Abortar si falla el tracking",
        description="Default False: un fallo de MLflow degrada a no-op + warning, NUNCA tumba el cálculo "
                    "(el tracking es accesorio al resultado). True solo para entornos de auditoría estrictos.")
```

**Defaults defendibles (porqué).** `enabled=True` (DoD F0 lo exige como fundacional); `tracking_uri=None` ⇒ file store local (DoD F0 = "tracking LOCAL", sin servidor que montar); `autolog=False` (no alterar el cálculo, D-TRK-3); `register_on_success=False` (registrar al inventario es una decisión de **gobierno** SR 11-7, no un efecto colateral — D-TRK-4); `fail_on_tracking_error=False` (el tracking es accesorio: su fallo no debe invalidar una corrida regulatoria válida — D-TRK-5).

**Serialización YAML y UI.** Round-trip estándar (SDD-05 §5.5): `model_dump(mode="json")` ↔ `model_validate`. La UI (SDD-23) renderiza desde `model_json_schema()`: `tracking_uri`/`registry_uri`/`experiment_name` → `text_input`, los `bool` → `checkbox`.

**`TrackingConfig` y el `config_hash` (resuelto, requiere coordinación con SDD-05).** El destino de tracking **no es parte del cálculo**, pero el `config_hash` es la **clave de idempotencia del inventario** (D-TRK-7; SDD-03 §7): si `tracking_uri`/`registry_uri` entraran al hash, **mover el destino de tracking rompería la idempotencia del registro del mismo modelo** (otro hash → versión duplicada). Por eso la decisión se cierra a favor de **excluir las secciones de infraestructura (`tracking`/`report`/`audit`) del `config_hash` de cálculo** que indexa el inventario; opcionalmente se mantiene un hash separado "de corrida completa" para auditoría. La materialización del hash vive en SDD-05 (`core.config.io.config_hash`): **requiere un PR a SDD-05** para fijar el conjunto de secciones excluidas. *Trazado en §12 (D-TRK-8); impacto de molde reportado al integrador.*

---

## 6. Contratos de datos (I/O)

**Input.**
- `Study` ejecutado (`run_context.status == "done"` o `"failed"`): se leen `config` (NikodymConfig frozen), `results` (dict), `lineage_bundle()` (LineageBundle), y el directorio `Study.save(...)` si `log_study_artifacts`.
- `TrackingConfig` válido.
- Para `register_model`: un `model_uri` MLflow (`runs:/<run_id>/<artifact_path>` o `models:/...`).

**Output.**
- Un **run MLflow** persistido en el tracking store (file store en F0): params, metrics, tags, artifacts. Estructura local resultante:
  ```
  <tracking_uri>/<experiment_id>/<run_id>/
  ├── params/        # cfg.<sección>.<campo>
  ├── metrics/       # <dominio>.<métrica>
  ├── tags/          # nikodym.config_hash, nikodym.git_sha, ...
  └── artifacts/
      ├── study/     # config.yaml, lineage.json, run_metadata.json, artifacts/*.joblib
      ├── model/     # modelo serializado (si log_models)
      └── results.json   # results no-numéricos (tablas/strings)
  ```
- Un `RunHandle` (run_id, artifact_uri, experiment_id, tracking_uri) para que governance/UI/report enlacen.
- Opcional: una **versión del Registry** (`InventoryEntry`/`ModelVersionRef`) si el registro tuvo backend válido.

> **Caveat de servibilidad (v1).** El artefacto `model/` se serializa con `joblib` del `SerializationMixin` (D-TRK-6), **no** como un MLflow Model con `MLmodel`/flavor. Por tanto, la entrada de inventario en v1 apunta a un artefacto de **trazabilidad/auditoría**, **no** a un modelo `pyfunc`-cargable (`mlflow.pyfunc.load_model(runs:/.../model)` **no** lo reconoce como servible). El serving vía flavors MLflow queda en T2+ (§12). Un validador no debe esperar servir directamente la versión registrada de v1.

**Aplanado del config (params).** El árbol `NikodymConfig` se aplana a claves punteadas `cfg.<sección>.<campo>` con valores escalares; `list`/`dict` se serializan a su JSON compacto (MLflow params son strings; **límite verificado: MLflow trunca params largos**, §8). El config completo y fiel va **siempre** como artefacto `study/config.yaml` (la fuente de verdad; los params son índice navegable, no la copia canónica).

**Invariantes (pre/post).**
- *Pre:* `config.tracking is not None and config.tracking.enabled` (si no, el módulo es no-op); MLflow importable (si no y `fail_on_tracking_error=False` → warning + no-op).
- *Identidad:* todo run lleva tag `nikodym.config_hash == config_hash(study.config)` → un run es rastreable a su experimento exacto.
- *Run ↔ Study:* un `Study.run()` ⇒ **a lo sumo un** run MLflow (idempotencia por contexto; no se abren runs anidados salvo `mlflow.start_run(nested=True)` explícito, fuera de v1).
- *Inventario:* `MLflowInventory.register(entry)` ⇒ una `version` bajo `name` con el `run_id` ligado; **idempotente por `config_hash`** (si ya existe una versión con ese `config_hash`, la devuelve sin duplicar — D-TRK-7, contrato de SDD-03 §7).
- *No-mutación:* `tracking` nunca modifica `Study.config`, `Study.results` ni los artefactos (solo lee/copia).

---

## 7. Algoritmos y flujo

> `tracking` traduce y persiste; no calcula. Pseudocódigo de alto nivel.

**Resolución de URIs (en `start_run`, no en `__init__`).**
1. `tracking_uri = config.tracking_uri or "<cwd>/mlruns"`; `mlflow.set_tracking_uri(tracking_uri)`.
2. `registry_uri = config.registry_uri or tracking_uri`; `mlflow.set_registry_uri(registry_uri)`.
3. `experiment = config.experiment_name or study.config.name`; `mlflow.set_experiment(experiment)`.
4. Determinar `registry_db_backed = registry_uri.startswith(("sqlite", "postgresql", "mysql", "http", "https"))` → habilita o no `register_model` (D-TRK-2).

**Apertura y logging del run (`start_run` + `run_end`).**
1. `run = mlflow.start_run(run_name=run_name or study.name)` → `RunHandle(run_id, experiment_id, artifact_uri, tracking_uri)`.
2. `log_config(study.config)`: aplanar a `cfg.<sección>.<campo>` → `mlflow.log_params({...})`; tags de identidad (`nikodym.config_hash`, `nikodym.schema_version`).
3. `log_lineage(study.lineage_bundle())`: tags (`nikodym.git_sha`, `nikodym.root_seed`, …) + `mlflow.log_dict(bundle.model_dump(mode="json"), "study/lineage.json")`.
4. Al `run_end` (lo dispara el `TrackingSink`):
   a. `log_metrics(study.results)`: por cada par cuyo valor es numérico finito → `mlflow.log_metric(key, value)`; los no-numéricos → acumular en `results.json` y `mlflow.log_dict(..., "results.json")`.
   b. Si `log_study_artifacts`: `study.save(tmp)` y `mlflow.log_artifacts(tmp, "study")` (run autocontenido).
   c. Si `log_models`: cada estimador fiteado del `ArtifactStore` → `mlflow.log_artifact(joblib, "model")` (serialización ya definida por `SerializationMixin`, SDD-01; **no** se usa `mlflow.sklearn.log_model` en v1 para no acoplar a sklearn — D-TRK-6).
   d. Si `register_on_success and registry_db_backed and log_models`: governance arma el `InventoryEntry` y `MLflowInventory.register(entry)` lo escribe (idempotente por `config_hash`, ver abajo). En F0 el registro lo gatilla normalmente `governance` (SDD-03), no la orquestación del run (D-TRK-4).
   e. Cerrar el run (status `FINISHED`/`FAILED` según excepción del `Study`).

**Idempotencia del inventario por `config_hash` (en `MLflowInventory.register`, D-TRK-7).** Es el contrato que `governance` promete (SDD-03 §7): `register(entry)` **no duplica** versiones del mismo experimento.
1. Pre-chequeo del backend: si `not registry_db_backed` → no se invoca `create_model_version` (D-TRK-2); se devuelve `None`+warning o `RegistryUnavailableError` (§8) según `fail_on_tracking_error`.
2. Buscar versión existente con tag `nikodym.config_hash == entry.config_hash` (`client.search_model_versions(f"name='{name}'")` filtrando por el tag, verificado context7). Si existe → **devolver esa version id** (idempotente; no crea otra).
3. Si no existe → `client.create_model_version(name, source=f"runs:/{entry.run_id}/model", run_id=entry.run_id, tags={...})`; luego `set_model_version_tag` para `nikodym.config_hash`/`data_hash`/`git_sha`/métricas/cartera/motor y `set_registered_model_alias` para los aliases declarados por governance. Devolver la nueva version id.

> Esta idempotencia es a nivel de **versión del Registry por `config_hash`** (barata, es lo que pide SDD-03), **distinta** de "deduplicar runs" (que sí se difiere; §12): dos `Study.run()` idénticos siguen produciendo dos runs MLflow, pero `register` los consolida en **una sola** versión de inventario.

**Mapeo `AuditEvent` → MLflow (en `TrackingSink.emit`).**
- `run_start` → asegura run abierto (lo abre `start_run` si la orquestación no lo hizo); tag `nikodym.run_started_at`.
- `decision` → cada `log_decision(regla, umbral, valor, accion)` se acumula en un `decisions.jsonl` (artefacto) y se cuenta como metric `nikodym.n_decisions` (no se crea un tag por decisión: explotaría la cardinalidad).
- `artifact` → si el payload trae una ruta, `log_artifact`; si no, se anota en `decisions.jsonl`.
- `run_end` → ejecuta el bloque de cierre (metrics+lineage+study_dir+register) y cierra el run.

**Auto-discovery / registro.** `tracking` se importa de forma perezosa desde la orquestación de `core` (SDD-01 §7, lista explícita tolerante a `ImportError`): si el extra `[tracking]` no está instalado, `core` simplemente no inyecta el sink (no rompe). `TrackingSink`/`TrackingRecorder` no necesitan registrarse en el `Registry` (no son estimadores de dominio); se instancian directo desde `TrackingConfig`.

**Reproducibilidad de un run (decisión clave).** Un run es **determinista en lo que registra** porque sus entradas son deterministas: `config_hash`, `LineageBundle` y `results` provienen de un `Study` reproducible (SDD-01 §9). El único campo no determinista es el `run_id`/timestamp que MLflow genera (metadato de la corrida, no del cálculo). Re-ejecutar el mismo `Study` produce **otro** run con **idéntico** `nikodym.config_hash` → trazabilidad sin falsa unicidad. **No se deduplican `run`s por hash en v1** (queda como mejora; §12); en cambio la **idempotencia del inventario** sí se implementa en `register` (una versión por `config_hash`, D-TRK-7) porque es el contrato que `governance` consume (SDD-03 §7).

**Complejidad / rendimiento.** O(nº de params + nº de metrics + tamaño de artefactos). El logging ocurre **una vez** al cierre del run; no está en el camino caliente del cálculo. `log_artifacts` del directorio del `Study` es la operación más pesada (copia de ficheros), aceptable porque es terminal.

**Alternativas descartadas.** (a) Importar MLflow en `core` y loguear inline en cada paso → viola "core no importa MLflow" (SDD-01) y mete I/O en el camino caliente. (b) `mlflow.autolog()` por defecto → parchea `fit`, altera/ralentiza el cálculo y produce logs no trazados (D-TRK-3). (c) `mlflow.sklearn.log_model` como serializador base → acopla a sklearn y a su flavor; se prefiere joblib del `SerializationMixin` (D-TRK-6), dejando los flavors MLflow como opción futura por dominio.

---

## 8. Casos borde y manejo de errores

- **MLflow no instalado** (extra `[tracking]` ausente): import perezoso falla → si `fail_on_tracking_error=False` (default), warning claro ("instala `nikodym[tracking]` para habilitar tracking") y **no-op**; si `True`, `TrackingError`. `core` nunca depende de que esté.
- **Servidor MLflow ausente / tracking_uri remoto inalcanzable** → **fallback a file store local** con warning (no aborta el cálculo): se reintenta con `./mlruns`. Coherente con DoD F0 (local) y con `fail_on_tracking_error=False`.
- **Registry sin backend de base de datos** (file store) y se pide registrar → el wrapper de Nikodym **pre-chequea** el esquema del `registry_uri` (`registry_db_backed == False`, §7 paso 4), **OMITE** la llamada a `mlflow.register_model`/`create_model_version` y devuelve `None`+warning (no aborta; verificado context7: "Model Registry requires a database-backed store"). No es MLflow quien devuelve `None`: si por defensa se invocara contra un file store, MLflow lanzaría `MlflowException` (capturada y traducida a `RegistryUnavailableError`). El run y sus artefactos sí se persisten; el modelo queda como artefacto `runs:/.../model`, registrable luego contra un backend DB (D-TRK-2).
- **Artefacto no serializable** (objeto sin pickle/joblib): se captura por artefacto, se omite ese fichero con warning y se anota en `results.json` la causa; el resto del run no se pierde (degradación elegante).
- **Métrica no numérica o `NaN`/`inf`** en `Study.results`: no se loguea como metric (MLflow rechaza no-finitos); va a `results.json`.
- **Param demasiado largo** (config con listas grandes): MLflow trunca/limita params → el valor en param es el JSON compacto recortado; la copia fiel siempre está en `study/config.yaml` (la verdad canónica, §6).
- **`Study` no ejecutado** (`status == "created"`) al intentar `log_metrics`/`register`: `TrackingError` ("el Study no fue ejecutado; corre run() antes de registrar").
- **Run ya cerrado / doble cierre**: `__exit__`/`run_end` son idempotentes (verifican `mlflow.active_run()`); cerrar dos veces no levanta.
- **`enabled=False`**: el módulo es **no-op total** (no abre run, no inyecta sink); útil para correr cálculo puro sin efectos.
- **Config inválido** (`extra="forbid"`, tipo erróneo): `ValidationError` → `ConfigError` en la construcción del `NikodymConfig` (validación temprana de `core`, SDD-01 §8).

**Excepciones propias.** `tracking` **define sus subclases en su propio módulo**, conforme a la regla de SDD-01 §4: `core.exceptions` aloja la raíz `NikodymError` y las excepciones del núcleo; los módulos de dominio/infraestructura definen sus subclases en su módulo (p.ej. `GovernanceError`/`AuditError` en SDD-03), todas descendiendo de `NikodymError`. Las de la frontera MLflow viven aquí:

```python
class TrackingError(NikodymError): ...          # raíz del módulo (desciende de NikodymError, SDD-01 §4)
class ModelNotFoundError(TrackingError): ...     # MLflowInventory.get_version de una versión inexistente
class RegistryUnavailableError(TrackingError): ...# registrar sin backend DB y fail_on_tracking_error=True
```

Todas descienden de `NikodymError` (regla de SDD-01 §4); mensajes en español con la regla/valor cuando aplica.

---

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos:** `tracking` **no tiene** azar propio (no siembra ni consume `Generator`). Su salida es función determinista de las entradas del `Study` salvo el `run_id`/timestamp que MLflow asigna (metadato de corrida, no de cálculo). No requiere `SeedManager`.
- **Qué registra en el audit-trail/lineage:** `tracking` es uno de los **consumidores** del `LineageBundle` (SDD-01 lo ensambla, SDD-03 lo persiste como model card): lo refleja como tags (`nikodym.git_sha`, `root_seed`, `config_hash`, `uv_lock_hash`, `data_hash`) y como artefacto `study/lineage.json`. Vía `TrackingSink`, además **enruta cada `AuditEvent`** (`decision`/`artifact`) a `decisions.jsonl` y al contador `nikodym.n_decisions` → el run MLflow es un espejo auditable del `Study`.
- **Inventario auditable (SR 11-7):** el Model Registry da el **inventario versionado** (ESPEC §9). Cada `ModelVersionRef`/`InventoryEntry` liga la versión a su `run_id` y `config_hash` → un validador/regulador puede ir del **alias `@production`** hasta el config, datos, semilla y git SHA que lo produjeron. La **promoción vía aliases** (p.ej. `champion`/`production`; los `stages` están **deprecados** desde MLflow 2.9 — verificado context7) y la **próxima revisión** son política de `governance` (SDD-03), que *escribe* (vía `MLflowInventory.register`/`set_registered_model_alias`) sobre el inventario que `tracking` *mantiene*.
- **Garantía de determinismo y caveats:** el tracking **no introduce** indeterminismo en el cálculo (se ejecuta al cierre, fuera del camino caliente, con `autolog=False`). Caveat: dos corridas idénticas producen dos runs distintos (distinto `run_id`); la igualdad se verifica por `nikodym.config_hash`, no por unicidad de run.

---

## 10. Dependencias

**Internas:** `nikodym.core` (SDD-01): `Study`, `NikodymConfig`/`TrackingConfig` base, `LineageBundle`, `core.config.io.config_hash`, `core.audit.AuditSink`/`AuditEvent`/**`FanOutSink`**, `core.exceptions.NikodymError`. `nikodym.governance` (SDD-03) define el **`Protocol ModelInventory`**, el **`InventoryEntry`** (escritura) y el **`InventoryRecord`** (lectura) que `tracking` **implementa** (`MLflowInventory`). Dirección de dependencia (inversión clásica): `tracking` **importa** esos tipos de `governance` (es la dependencia normal **04 → 03** del índice) y `governance` **no importa** `tracking` (evita el ciclo: `governance` programa contra el `Protocol`, no contra `MLflowInventory`). El esquema fino de tags/aliases lo coordinan SDD-03 ↔ SDD-04.

**Externas:**

| Librería | Versión mín. | Licencia | Uso |
|---|---|---|---|
| mlflow | ≥ 2.10 | Apache-2.0 ✅ | toda la frontera: `set_tracking_uri`/`set_registry_uri`/`set_experiment`/`start_run`/`log_params`/`log_metrics`/`log_artifact(s)`/`log_dict`/`MlflowClient.create_model_version`/`search_model_versions`/`set_model_version_tag`/`set_registered_model_alias`/`get_model_version_by_alias`. Verificado (context7): API, **aliases+tags vigentes (stages deprecados desde 2.9)** y restricción "Registry requiere backend DB". *Piso ≥ 2.10* (alineado con SDD-25, fuente única del piso): los aliases/tags existen desde 2.3/2.9 (release que deprecó stages); se fija ≥ 2.10 por estabilidad de la API que el SDD usa y CI consistente. |
| pydantic | ≥ 2.5 | MIT ✅ | `TrackingConfig`, `RunHandle`, `ModelVersionRef` (vía `core`). |
| (stdlib) | — | PSF | `pathlib`, `json`, `tempfile`, `warnings`, `importlib` (import perezoso). |

> **Nota de licencia (verificada).** MLflow es **Apache-2.0** (ESPEC §7 tabla de stack, "Tracking | mlflow | Apache-2.0 ✅") → compatible con la licencia del proyecto, sin copyleft. MLflow arrastra deps transitivas pesadas (sqlalchemy, scipy, etc.), lo que **refuerza** mantenerlo como **extra opcional**, no en el core liviano.

**Extra opcional + import perezoso (D-TRK-1).** `tracking` es el **extra `[tracking]`** del packaging (SDD-25): `pip install nikodym[tracking]`. MLflow se importa **dentro de los métodos** (no a nivel de módulo); si falta, mensaje accionable y no-op (§8). Así un usuario que solo calcula provisiones no paga el peso de MLflow, y DoD F0 ("tracking MLflow local") se cumple instalando el extra. *Tensión núcleo-liviano vs DoD F0 resuelta en §12 (D-TRK-1).*

---

## 11. Estrategia de tests

Detalle transversal en SDD-24; lo específico de `tracking`:

- **MLflow local temporal (integración).** Fixture que fija `tracking_uri`/`registry_uri` a un `tmp_path` (file store): correr un `Study` mínimo (fixture de SDD-01) con `TrackingSink`, y verificar que en `mlruns/` aparece un run con (a) tag `nikodym.config_hash` == `config_hash(study.config)`, (b) los params `cfg.*` esperados, (c) las metrics numéricas, (d) los artefactos `study/config.yaml` y `study/lineage.json`. Sin servidor (file store, DoD F0).
- **Registry sobre sqlite temporal (contrato del Protocol de SDD-03).** `registry_uri="sqlite:///<tmp>/registry.db"`: `MLflowInventory.register(InventoryEntry)` crea una versión con tags (`config_hash`/`data_hash`/...) y alias; `list_versions`/`get_version`/`latest_version(alias=...)` la recuperan con `run_id` y `config_hash` ligados. Verifica que `MLflowInventory` **cumple el `Protocol ModelInventory`** que consume governance (SDD-03 §4.2), contra un `InventoryEntry` real.
- **Idempotencia por `config_hash` (D-TRK-7).** Dos `register(entry)` con el mismo `config_hash` → **una sola** versión (la segunda devuelve la version id existente, no duplica). `entry` con `config_hash` distinto → versión nueva.
- **Aliases (no stages, D-TRK-8).** `register` con aliases declarados → `get_model_version_by_alias(name, "champion")` resuelve a la versión; reasignar el alias a otra versión lo mueve (sin tocar `stages`).
- **Caso borde Registry sin DB.** Con file store, el wrapper pre-chequea el backend, **omite** la llamada y devuelve `None` + warning (no levanta `MlflowException`); el run sí persiste. (Aísla la restricción verificada de MLflow.)
- **Degradación elegante (mock).** `monkeypatch` que hace fallar `mlflow.start_run`: con `fail_on_tracking_error=False` el `Study.run()` **termina OK** (cálculo intacto) y emite warning; con `True` levanta `TrackingError`. Test de que **el tracking jamás tumba el cálculo** por defecto.
- **`enabled=False` / MLflow ausente.** Simular ausencia de MLflow (mock de import) → no-op, sin error, `Study` corre.
- **`autolog=False` por defecto.** Verificar que no se llama `mlflow.autolog()` salvo `config.autolog=True` (test de que el tracking no parchea el cálculo).
- **Reproducibilidad de lo registrado.** Dos corridas del mismo `Study` → dos runs con **igual** `nikodym.config_hash` y mismas metrics (salvo `run_id`/timestamp). Property: `config_hash(run.tags) == config_hash(study.config)`.
- **Aplanado del config.** `flatten(config)` ↔ claves `cfg.<sección>.<campo>`; round-trip de que el `study/config.yaml` artefacto re-valida a un `NikodymConfig` igual al original.
- **Fixtures.** `tracking_config_local` (file store en tmp), `tracking_config_sqlite` (registry DB en tmp), `study_minimo` (de SDD-01), `mlflow_unavailable` (mock de import fallido), `InMemoryAuditSink` para comparar el espejo de eventos.

---

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas en este SDD (trazabilidad).**
- **D-TRK-1 — MLflow es extra opcional `[tracking]` con import perezoso, NO dependencia base.** *Tensión:* DoD F0 pide "tracking MLflow local" como fundacional, lo que sugeriría dep base; pero el principio "núcleo liviano" (ESPEC §4.9) y el hecho de que MLflow arrastra sqlalchemy/scipy lo desaconsejan. *Resolución:* extra opcional; DoD F0 se cumple con `nikodym[tracking]` (el packaging de SDD-25 lo lista en los extras "de fundación"). `core` jamás importa MLflow (SDD-01); su ausencia degrada a no-op, nunca rompe. *Alternativa descartada:* dep base (más simple de instalar, pero infla todo despliegue —p.ej. solo-provisiones— con MLflow). **Reversible** si Cami prioriza "todo incluido" sobre liviandad.
- **D-TRK-2 — `register_model` exige backend de base de datos; con file store se omite (no aborta).** *Porqué:* restricción **verificada (context7)**: el MLflow Model Registry requiere backend DB; el file store no lo soporta. *Consecuencia:* en F0 puro (file store) el **tracking de runs funciona**, pero el **inventario** (Registry) requiere `registry_uri` sqlite (un paso trivial: `sqlite:///mlflow.db`). Se documenta y se degrada con warning + `None`, no se finge soporte.
- **D-TRK-3 — `autolog=False` por defecto.** *Porqué:* "la IA documenta, nunca calcula" (ESPEC §4) y "el tracking no debe alterar el cálculo": autolog parchea `fit()` de las librerías, puede cambiar timing/comportamiento y produce logs no trazados. El logging Nikodym es **explícito**. *Alternativa descartada:* autolog on (menos código en dominios, pero logging mágico no auditable).
- **D-TRK-4 — `register_on_success=False` por defecto.** Registrar al inventario es una **decisión de gobierno** (SR 11-7), no un efecto colateral del cálculo: lo gatilla `governance` (SDD-03), no toda corrida.
- **D-TRK-5 — `fail_on_tracking_error=False` por defecto.** El tracking es **accesorio** al resultado: su fallo no debe invalidar una corrida regulatoria válida. Solo entornos de auditoría estricta lo ponen en `True`.
- **D-TRK-6 — Serialización de modelos vía `joblib` (SerializationMixin de core), no `mlflow.<flavor>.log_model` en v1.** *Porqué:* no acoplar a sklearn ni a un flavor; el `SerializationMixin` (SDD-01) ya define el formato. Los flavors MLflow (señales, `pyfunc`) quedan como mejora por dominio en T2+. *Consecuencia (caveat §6):* la versión de inventario v1 es un artefacto joblib de trazabilidad, **no** un modelo `pyfunc`-servible.
- **D-TRK-7 — Idempotencia del inventario por `config_hash` en `MLflowInventory.register`.** *Porqué:* es el contrato que `governance` consume (SDD-03 §7): `register(entry)` busca una versión con tag `nikodym.config_hash == entry.config_hash` y, si existe, la devuelve sin crear otra (verificado context7: `search_model_versions` + tags). *Distinción:* esto es idempotencia **a nivel de versión del Registry**, NO "deduplicación de runs" (que sí se difiere). `tracking` **implementa** el `Protocol ModelInventory` de SDD-03 (`MLflowInventory`), no lo redefine.
- **D-TRK-8 — Promoción del inventario vía `aliases`+`tags`, NO `stages` (deprecados).** *Porqué:* los Model Stages (`Staging`/`Production`/`Archived`) están **deprecados desde MLflow 2.9** y serán removidos (verificado context7); el inventario regulatorio (evidencia SR 11-7, vive años) no debe atarse a una API que MLflow va a quitar. *Resolución:* `ModelVersionRef.aliases: list[str]` + `tags: dict[str,str]`; promoción con `client.set_registered_model_alias`/`set_model_version_tag`. Alineado con SDD-03 §7. *Compat:* no se mantiene `stage` ni siquiera como legacy en v1 (API limpia desde el inicio).
- **D-TRK-9 — `TrackingConfig`/infra (`tracking`/`report`/`audit`) EXCLUIDOS del `config_hash` de cálculo.** *Porqué:* el destino de tracking no es parte del cómputo y el `config_hash` indexa el inventario (D-TRK-7); incluirlo rompería la idempotencia al mover el destino (§5). *Resolución:* excluir esas secciones del hash de cálculo; opcional hash separado de "corrida completa". *Requiere PR a SDD-05* (la materialización del hash vive en `core.config.io.config_hash`).

**Decisiones abiertas (delegadas).**
- **Política de promoción del inventario** (qué alias —`champion`/`production`— se asigna, quién aprueba, próxima revisión). *Responsable:* **SDD-03 (governance)** — `tracking` solo expone la escritura/lectura del Registry (aliases+tags, D-TRK-8). El **esquema fino de tags/aliases canónicos** (`cartera`, `motor`, `estado`, `config_hash`) lo cierra SDD-03 ↔ SDD-04 (ya abierto en SDD-03 §12).
- **Exclusión de infra del `config_hash`** (D-TRK-9): la decisión está tomada en este SDD; su **materialización requiere PR a SDD-05** (`core.config.io.config_hash` con conjunto de secciones excluidas). *Responsable de aplicar el PR:* integrador ↔ autor SDD-05.
- **Deduplicación de `run`s por `config_hash`** (evitar runs redundantes idénticos a nivel de run MLflow, distinto de la idempotencia del inventario que sí va en v1, D-TRK-7). *Sugerencia:* fuera de v1; el `config_hash` ya permite agrupar a posteriori. *Responsable:* DanIA.
- **Flavors MLflow por dominio** (`pyfunc`/`signature` para scorecards y motores de provisión, despliegue/serving → modelo servible, cf. caveat §6). *Responsable:* SDD del dominio en T2+.

**Riesgos.**
- **Peso de MLflow** (sqlalchemy/scipy transitivos) → mitigado por extra opcional (D-TRK-1).
- **Confusión file-store vs Registry** (un usuario espera inventario con file store y no lo obtiene) → mitigado por warning explícito (D-TRK-2) y doc del `registry_uri` sqlite en F0.
- **Cardinalidad de tags** si se taguea cada decisión → mitigado: las decisiones van a `decisions.jsonl` + contador, no a tags individuales (§7).
- **Acoplamiento de versión MLflow** (params/registry API evolucionan) → versión mínima fijada y verificada (context7); tests de integración con MLflow local en CI (SDD-24/25).

---

### Citas

- **ESPECIFICACIONES.md** §4 (principio 1 reproducibilidad, 2 auditabilidad, 3 gobernanza en el núcleo, 8 no reinventar, 9 núcleo liviano; "la IA documenta, nunca calcula"), §6.1 (core agnóstico, la UI importa el núcleo nunca al revés), §6.3 (árbol: `tracking/  # MLflow (runs, registry, artefactos)`), §7 (stack: "Tracking | mlflow | Apache-2.0 ✅"; outputs: "Study serializado + modelo(s) (joblib/MLflow)"; "Model card + audit log + run MLflow"), §9 (SR 11-7: lineage bundle, model card, **"Inventario versionado = MLflow Registry"**, registro auditable), §11 (DoD F0: "`tracking` (MLflow local)").
- **ROADMAP.md** Fase 0: "`tracking` (MLflow local). Todo lo posterior es auditable desde aquí."
- **00-INDICE.md** SDD-04 (`tracking` (MLflow), F0/T1, depende de 01, 03); §Convenciones (fórmulas/parámetros se citan, no se reescriben — `tracking` no tiene ninguno).
- **SDD-01 (`core`):** `Study` + `set_audit_sink`/`lineage_bundle`/`save`; `AuditSink`/`AuditEvent`/`NullAuditSink`/**`FanOutSink(AuditSink)`** con `__init__(sinks: list[AuditSink])` (§4, usado para combinar governance+tracking en un único hook); `LineageBundle`/`RunContext`; `SerializationMixin` (joblib); `config_hash` (core.config.io); `NikodymError` y **regla de alojamiento de excepciones** (§4: la raíz vive en `core.exceptions`; los módulos definen sus subclases en su módulo heredando de `NikodymError`); D-CORE-4 (Study como directorio); "core no importa MLflow" (§1, §10).
- **SDD-03 (`audit`+`governance`):** **define el `Protocol ModelInventory`** (`register(entry: InventoryEntry) -> str`, `get_active`, `list_versions`) y el **`InventoryEntry`** que SDD-04 implementa (`MLflowInventory`) — inversión de dependencias (§4.2, §7, D-AUD-2); idempotencia por `config_hash` (§7); `NullInventory` sin el extra; frontera aliases+tags (stages deprecados).
- **SDD-05 (convenciones):** §4.1 (sin lógica en `__init__`, params espejo del sub-config), §4.4 (naming D-CONV-1: inglés stats / español CMF; prosa en español), §5.1 (`tracking: TrackingConfig | None = None` en la lista canónica; secciones opcionales), §5.3 (defaults defendibles, `title`+`description` obligatorios, `extra="forbid"`/`frozen`), §5.5 (`config_hash` JSON canónico, round-trip YAML, UI desde `model_json_schema`).
- **Verificado vía context7** (`/mlflow/mlflow`): `mlflow.set_tracking_uri` (file store por defecto `./mlruns`), `mlflow.set_experiment` (crea `mlruns/`), `mlflow.set_registry_uri`, `mlflow.start_run`, `mlflow.log_params`/`log_metrics`, `MlflowClient.log_artifacts(run_id, local_dir, artifact_path)`, `mlflow.register_model`/`MlflowClient.create_model_version(name, source, run_id, tags)`, `MlflowClient.search_model_versions` (idempotencia por tag `config_hash`), `MlflowClient.set_model_version_tag`, **`MlflowClient.set_registered_model_alias`/`get_model_version_by_alias`/`delete_registered_model_alias` (aliases mutables `models:/<name>@<alias>`; reemplazan los `stages` DEPRECADOS desde MLflow 2.9)**, `mlflow.autolog()`/`mlflow.<lib>.autolog(disable=…)`, y la **restricción dura: el Model Registry requiere un backend de base de datos (sqlite/servidor); el file store no soporta el Registry** ("database-backed store ... Model Registry functionality requires a database-backed store").
