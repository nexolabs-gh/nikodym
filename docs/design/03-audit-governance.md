# SDD-03 — `audit` + `governance` (audit-trail persistente, model card, inventario, SR 11-7)

| Campo | Valor |
|---|---|
| **SDD** | 03 |
| **Módulo** | `nikodym.audit` + `nikodym.governance` |
| **Fase** | F0 |
| **Tanda de producción** | T1 (Fundación) |
| **Estado** | Aprobado |
| **Depende de** | SDD-01 (`core`: `AuditSink`/`AuditEvent`, `LineageBundle`, `RunContext`, `Study`, excepciones) |
| **Lo consumen** | SDD-04 (`tracking`: provee la infra MLflow Registry que `governance` usa como inventario), SDD-21 (`stress`: registro auditable de escenarios/overlays), SDD-22 (`validation`: effective challenge), SDD-26 (`report`: consume model card), SDD-23 (UI) |
| **Autor / Fecha** | DanIA (fan-out Tanda 1) / 2026-06-23 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** Convierte los hooks de gobernanza que `core` *emite* (eventos `AuditEvent` + `LineageBundle`) en evidencia **persistente y consultable**: un audit-trail en disco, un **model card** automático por corrida y el **inventario de modelos** (SR 11-7), sin que `core` dependa de ellos (inversión de dependencias).

**Responsabilidad única (qué SÍ hace).**
- **`audit/`** — implementa un `AuditSink` concreto que **persiste** el audit-trail (`run_start`/`decision`/`artifact`/`run_end`) a disco en **JSONL append-only**; captura el **registro de entorno** (`library_versions`, OS, Python, hash de `uv.lock`), las **semillas** y coordina el **hash de datos** (`data_hash`, que materializa SDD-02). Es el sink que se inyecta en el `Study` vía `Study.set_audit_sink`.
- **`governance/`** — produce el **model card** por corrida desde el `LineageBundle` + los `AuditEvent` (propósito, supuestos, limitaciones, datos, métricas, fecha, próxima revisión, `determinism_caveats`); define **qué es una entrada de inventario** y la publica en el **inventario = MLflow Registry** (cuya infra provee SDD-04); mantiene el **registro auditable de escenarios y overlays** (foco supervisor: evitar *earnings management*).

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No define ni emite** `AuditEvent`/`LineageBundle`: eso lo hace `core` (SDD-01); SDD-03 **consume** y persiste. No re-deriva semillas ni recomputa el `config_hash`/git SHA (los lee del bundle ya congelado).
- **No provee la infraestructura MLflow** (servidor, tracking URI, `log_*`, `MlflowClient`): eso es **SDD-04** (`tracking`). `governance` define *qué entra al inventario* y *con qué metadatos*; SDD-04 ejecuta las llamadas de Registry. Frontera explícita en §2.
- **No calcula** escenarios/overlays (eso es SDD-20/21) ni valida modelos (effective challenge = SDD-22): `governance` solo **registra auditablemente** lo que esos módulos producen.
- **No genera el reporte HTML/PDF**: el render Quarto es **SDD-26** (`report`), que consume el model card como insumo.
- **No es importado por `core`**: `core` define las interfaces; `audit`/`governance` las implementan y se inyectan (§6.1 ESPEC, D-CORE-1).

---

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Fundación (transversal), F0/T1. Paquetes `src/nikodym/audit/` y `src/nikodym/governance/` (ESPEC §6.3).
- **Quién lo invoca:** la API/CLI o la UI construyen el sink de `audit` y lo inyectan en el `Study` (`study.set_audit_sink(...)`) **antes** de `study.run()`. Tras el run, se invoca `governance` para producir el model card y publicar la entrada de inventario.
- **A quién invoca:** `audit` no invoca dominios (es un *sink* pasivo que reacciona a eventos). `governance` invoca a **SDD-04** (`tracking`) para escribir en el MLflow Registry, vía una interfaz `ModelInventory` que SDD-04 implementa (inversión: `governance` define el contrato, `tracking` lo cumple).

```
        Study.run()  (SDD-01, core)
            │ emite AuditEvent  + congela LineageBundle
            ▼
   ┌──────── AuditSink (Protocol, core) ────────┐
   │   JsonlAuditSink (SDD-03, audit/)          │  ← persiste trail a disco (JSONL)
   └───────────────┬────────────────────────────┘
                   │ trail + bundle (al cierre del run)
                   ▼
        ModelCardBuilder (SDD-03, governance/)
                   │ model card (objeto + JSON + markdown)
       ┌───────────┴───────────────┐
       ▼                           ▼
  ModelInventory (Protocol, SDD-03) ScenarioLog (SDD-03, governance/)
       │ implementa                 ↑ registra escenarios/overlays
       ▼                            (lo llaman SDD-20/21)
  impl. de ModelInventory (SDD-04, tracking)  →  MLflow Registry
```

**Interacción con el `Study` y el config.** El comportamiento de ambos paquetes se parametriza por `AuditConfig` y `GovernanceConfig` (sub-secciones de `NikodymConfig`, §5). El sink lee de esas secciones dónde escribir el JSONL, qué nivel de detalle capturar y qué política de próxima revisión aplicar al model card.

---

## 3. Conceptos y fundamentos

> SDD-03 **no contiene fórmulas cuantitativas** (no calcula riesgo). Los conceptos son de gobernanza de modelos (SR 11-7) y de trazabilidad; se citan desde ESPEC §9, no se reescriben parámetros normativos.

- **SR 11-7 (Model Risk Management, Fed) — tres pilares** (ESPEC §9, conceptual): (1) **desarrollo sólido** (los dominios producen el modelo; `audit` deja evidencia de cada decisión); (2) **effective challenge** = validación independiente (la ejecuta SDD-22; `governance` deja el rastro auditable que el validador consume); (3) **governance con documentación + inventario de modelos** (el corazón de SDD-03: model card + inventario versionado). SDD-03 **materializa el pilar 3** y deja la evidencia que habilita 1 y 2.
- **Audit-trail** — secuencia ordenada e inmutable de `AuditEvent` (`run_start`, `decision`, `artifact`, `run_end`; SDD-01 §4). `decision` lleva la **regla, el umbral gatillante y el valor** (auditabilidad por construcción, §4 principio 2). Se persiste en **JSONL** (un evento JSON por línea, *append-only*): formato auditor-friendly, diffeable, *streamable*, sin dependencias (stdlib `json`).
- **Lineage bundle** — `git SHA + data_hash + config_hash + root_seed + uv_lock_hash + library_versions + determinism_caveats + created_at` (SDD-01 §4/§9). `core` lo **ensambla y congela**; `audit` lo **persiste** y `governance` lo **resume** en el model card.
- **Model card** — documento estructurado por corrida (propósito, supuestos, limitaciones, datos, métricas, fecha, próxima revisión, caveats de determinismo). Es la "ficha" del modelo que lee un validador/regulador. Automático: se deriva del bundle + trail + `results` del `Study`, sin redacción manual.
- **Inventario de modelos** — catálogo versionado de modelos en producción/desarrollo = **MLflow Registry** (ESPEC §9). `governance` define la **entrada de inventario** (qué metadatos: `config_hash`, `data_hash`, git SHA, métricas clave, model card adjunto, próxima revisión) y delega la escritura a SDD-04.
- **Registro de escenarios y overlays** — los *overlays* (ajustes manuales a la provisión/ECL) y los escenarios macro son el punto donde un supervisor teme **earnings management** (suavizar resultados ajustando provisiones discrecionalmente). El `ScenarioLog` registra cada escenario/overlay con su justificación, autor, valor antes/después y timestamp → trazabilidad anti-discrecionalidad.

---

## 4. API pública (contrato)

> Firmas **ilustrativas** (contratos, no código final). Identificadores en inglés técnico (D-CONV-1); docstrings y mensajes en español. Estas clases **no son estimadores sklearn** (no llevan `fit`/`predict`): son infraestructura de gobernanza, contrato funcional propio (SDD-05 §4.2, fila "NO es estimador").

### 4.1 `nikodym.audit`

```python
# nikodym/audit/sink.py
class JsonlAuditSink:                                   # implementa core.audit.AuditSink (Protocol)
    """Sink que persiste el audit-trail a un archivo JSONL append-only."""
    def __init__(self, path: str | Path, *, config: "AuditConfig" | None = None,
                 flush_each: bool = True) -> None: ...
    path: Path                                          # <run_dir>/audit_trail.jsonl
    def emit(self, event: "AuditEvent") -> None: ...     # serializa event a 1 línea JSON + '\n'; append; flush
    def close(self) -> None: ...                        # cierra el handle (idempotente)
    def __enter__(self) -> "JsonlAuditSink": ...        # context manager: cierre garantizado
    def __exit__(self, *exc) -> None: ...
    # invariante: append-only; nunca reescribe líneas previas (inmutabilidad del trail)

# nikodym/audit/replay.py
def read_trail(path: str | Path) -> list["AuditEvent"]: ...   # parsea JSONL -> AuditEvent (re-valida con Pydantic)
def iter_trail(path: str | Path) -> Iterator["AuditEvent"]: ...  # lazy, para trails grandes

# nikodym/audit/environment.py  (registro de entorno)
class EnvironmentSnapshot(BaseModel):                   # Pydantic, serializable
    python_version: str                                 # platform.python_version()
    platform: str                                       # platform.platform() (OS + arch)
    library_versions: dict[str, str]                    # {pkg: version} del entorno corriente
    uv_lock_hash: str | None                            # sha256 de uv.lock (None + warning si ausente)
    captured_at: datetime                               # UTC
def capture_environment(*, packages: list[str] | None = None,
                        uv_lock_path: str | Path | None = None) -> EnvironmentSnapshot: ...
    # packages=None -> set por defecto (deps declaradas de nikodym); ver §7

# nikodym/audit/hashing.py  (coordina el data_hash con SDD-02)
def hash_dataframe(df: "pandas.DataFrame", *, algo: str = "sha256") -> str: ...
    # contrato del data_hash: hash canónico y estable de un DataFrame (ver §7 y D-AUD-3)
def hash_file(path: str | Path, *, algo: str = "sha256") -> str: ...   # uv.lock, parquet, etc.
```

### 4.2 `nikodym.governance`

```python
# nikodym/governance/model_card.py
class ModelCard(BaseModel):                             # Pydantic, serializable a JSON y markdown
    # --- identidad / lineage (del LineageBundle) ---
    run_id: str
    config_hash: str
    data_hash: str | None
    git_sha: str | None
    git_dirty: bool
    root_seed: int
    schema_version: str
    created_at: datetime
    # --- contenido SR 11-7 (ESPEC §9) ---
    purpose: str                                        # propósito declarado (de GovernanceConfig)
    assumptions: list[str]                              # supuestos (config + del trail)
    limitations: list[str]                              # limitaciones (incl. caveats de determinismo)
    data_description: "DataCardSection"                 # fuente, particiones, ventana, tasa de default (de SDD-02)
    metrics: dict[str, float]                           # métricas clave (de study.results; KS/AUC/PSI/...)
    decisions: list["DecisionRecord"]                   # descartes/cortes/umbrales (de los AuditEvent "decision")
    determinism_caveats: list[str]                      # del bundle (p.ej. GBDT multihilo)
    review_date: datetime                               # fecha de emisión
    next_review_date: datetime                          # = review_date + GovernanceConfig.review_period_months
    environment: "EnvironmentSnapshot"
    def to_markdown(self) -> str: ...                   # render markdown (insumo de SDD-26 / Quarto)
    def to_json(self) -> str: ...                       # JSON canónico (auditoría/diff)

class DecisionRecord(BaseModel):
    # NOTA (D-CONV-1): los campos regla/umbral/valor/accion están en español por DISEÑO — reflejan
    # 1:1 los kwargs de core.AuditableMixin.log_decision(*, regla, umbral, valor, accion) de SDD-01 §4
    # (el evento "decision" que este record materializa). Excepción heredada del contrato de auditoría de
    # core, no descuido: mantener el mismo nombre evita una traducción que rompería la trazabilidad 1:1.
    step: str | None; regla: str; umbral: Any; valor: Any; accion: str; ts: datetime

class ModelCardBuilder:
    """Ensambla un ModelCard desde un Study finalizado + su trail persistido."""
    def __init__(self, config: "GovernanceConfig") -> None: ...
    def build(self, study: "Study", *, trail_path: str | Path | None = None) -> ModelCard: ...
        # lee study.lineage_bundle() (congelado) + study.results + el trail JSONL (decisions);
        # study.run_context.status debe ser "done" o "failed"; "created"/"running" -> GovernanceError (§8).
        # Resolución del trail (§8): trail_path es la ÚNICA fuente del trail. trail_path=None (o archivo
        # ausente) -> card SIN decisions + warning. RunContext (SDD-01 §4) no expone run_dir, así que el
        # Builder no adivina la ruta: el llamador la pasa explícita (ver ejemplo §4.2: trail_path=sink.path).

# nikodym/governance/inventory.py
class InventoryEntry(BaseModel):                        # QUÉ es una entrada de inventario (lo define governance)
    model_name: str                                     # nombre lógico del modelo (de GovernanceConfig.model_name)
    config_hash: str; data_hash: str | None; git_sha: str | None
    run_id: str; metrics: dict[str, float]
    model_card: ModelCard                               # ficha completa adjunta
    next_review_date: datetime
    tags: dict[str, str]                                # `dict[str,str]` por exigencia del Registry (str->str).
                                                        # Clave CANÓNICA obligatoria: "config_hash" (ancla de
                                                        # idempotencia, §6). Opcionales: "cartera", "motor", "estado".

class InventoryRecord(BaseModel):                       # salida de LECTURA del inventario (rehidratable desde tags)
    model_name: str; version: str
    config_hash: str; data_hash: str | None; git_sha: str | None; run_id: str
    aliases: list[str]                                  # p.ej. ["champion"]
    tags: dict[str, str]
    model_card_uri: str | None                          # PUNTERO al model_card.json artefacto (NO el card completo)
    created_at: datetime

class ModelInventory(Protocol):                         # CONTRATO de inventario; lo implementa SDD-04 (tracking)
    """Contrato del inventario de modelos (SR 11-7). SDD-03 lo DEFINE; SDD-04 (MLflowInventory) lo cumple.
    ESCRITURA: register(InventoryEntry) — ficha completa; el ModelCard se guarda como ARTEFACTO.
    LECTURA: get_active / list_versions devuelven InventoryRecord (liviano, rehidratable desde los tags
    str->str del Registry; el ModelCard NO se reconstruye desde tags: se referencia por model_card_uri).
    Idempotencia (impuesta al implementador, ver §6): register DEBE ser idempotente por config_hash —
    dos llamadas con el mismo InventoryEntry.config_hash devuelven la MISMA versión, sin duplicar."""
    def register(self, entry: "InventoryEntry") -> str: ...  # ESCRITURA -> version id del Registry; idempotente por config_hash
    def get_active(self, model_name: str) -> "InventoryRecord | None": ...   # versión con alias activo (default @champion)
    def list_versions(self, model_name: str) -> list["InventoryRecord"]: ...
class NullInventory:  ...   # default no-op (sin SDD-04 instalado): governance funciona sin MLflow (register -> "" + warning)

# nikodym/governance/scenarios.py  (registro auditable; foco anti earnings-management)
class OverlayRecord(BaseModel):
    overlay_id: str; scope: str                         # p.ej. "ifrs9.stage2.consumo"
    justification: str                                  # OBLIGATORIO no vacío (§8)
    author: str
    value_before: float; value_after: float
    approved_by: str | None
    ts: datetime
class ScenarioRecord(BaseModel):
    scenario_id: str; kind: Literal["base", "adverso", "severo"] | str
    weight: float | None                                # peso de escenario (ECL ponderada)
    params: dict[str, Any]
    ts: datetime
class ScenarioLog:
    """Diario append-only de escenarios y overlays (JSONL). Lo alimentan SDD-20/21/17."""
    def __init__(self, path: str | Path) -> None: ...
    def log_scenario(self, rec: ScenarioRecord) -> None: ...
    def log_overlay(self, rec: OverlayRecord) -> None: ...   # justification vacía -> GovernanceError
    def read(self) -> list[ScenarioRecord | OverlayRecord]: ...

# nikodym/governance/inventory.py  (punto de inyección del inventario)
def publish_inventory(entry: InventoryEntry, *,
                      inventory: ModelInventory | None = None) -> str:
    """Publica una entrada en el inventario. inventory=None -> NullInventory() (default, sin MLflow).
    La capa de orquestación/API/CLI resuelve MLflowInventory (SDD-04) si el extra 'tracking' está
    instalado y lo pasa aquí — patrón análogo a Study.set_audit_sink para el sink (SDD-01)."""
    ...
```

**Ejemplo de uso (extremo a extremo, pseudocódigo):**

```python
from nikodym.core import Study
from nikodym.core.config import load_config
from nikodym.audit import JsonlAuditSink
from nikodym.governance import ModelCardBuilder, InventoryEntry, publish_inventory

config = load_config("experimento.yaml")
study  = Study(config, name="scorecard-comportamiento")

with JsonlAuditSink("runs/2026-06-23/audit_trail.jsonl", config=config.audit) as sink:
    study.set_audit_sink(sink)          # ANTES de run (invariante SDD-01 §7)
    study.run()                          # core emite eventos -> sink los persiste

card = ModelCardBuilder(config.governance).build(study, trail_path=sink.path)
card.to_markdown()                       # ficha lista (insumo SDD-26)

# inventario: la API/CLI resuelve MLflowInventory (SDD-04) si el extra 'tracking' está instalado;
# si no, publish_inventory cae a NullInventory (no-op + warning). Patrón análogo a set_audit_sink.
entry = InventoryEntry(model_name=config.governance.model_name, ..., model_card=card)
publish_inventory(entry, inventory=resolved_inventory)   # resolved_inventory=None -> NullInventory
```

---

## 5. Configuración (schema Pydantic)

Dos sub-configs, anidados en `NikodymConfig` (secciones `audit` y `governance`, SDD-05 §5.1). Ambos `NikodymBaseConfig` (`extra="forbid"`, `frozen=True`); cada campo con `title`+`description` (contrato UI, SDD-05 §5.5).

```python
# nikodym/audit/config.py
class AuditConfig(NikodymBaseConfig):
    enabled: bool = Field(True, title="Auditoría activa",
        description="Si False, el Study cae al NullAuditSink (sin persistencia de trail).")
    trail_filename: str = Field("audit_trail.jsonl", title="Archivo del audit-trail",
        description="Nombre del JSONL dentro del directorio del run.")
    flush_each: bool = Field(True, title="Flush por evento",
        description="True: durabilidad por evento (no se pierde el trail ante crash). False: buffer (más rápido).")
    capture_environment: bool = Field(True, title="Capturar entorno",
        description="Registrar python/OS/library_versions/uv.lock hash.")
    tracked_packages: tuple[str, ...] | None = Field(None, title="Paquetes a versionar",
        description="Subconjunto a capturar en library_versions. None = deps declaradas de nikodym.")

# nikodym/governance/config.py
class GovernanceConfig(NikodymBaseConfig):
    model_name: str = Field("nikodym-model", title="Nombre lógico del modelo",
        description="Identidad en el inventario (clave del MLflow Registry).")
    purpose: str = Field(..., title="Propósito del modelo",
        description="Declaración de propósito (SR 11-7). Obligatorio para el model card.")
    assumptions: tuple[str, ...] = Field((), title="Supuestos declarados")
    limitations: tuple[str, ...] = Field((), title="Limitaciones declaradas")
    review_period_months: int = Field(12, ge=1, le=60, title="Periodicidad de revisión (meses)",
        description="next_review_date = fecha de emisión + este periodo (SR 11-7).")
    publish_to_inventory: bool = Field(False, title="Publicar al inventario",
        description="True requiere el extra 'tracking' (SDD-04/MLflow). False = solo model card local.")
    scenario_log_filename: str = Field("scenario_log.jsonl", title="Diario de escenarios/overlays")
    require_overlay_justification: bool = Field(True, title="Exigir justificación de overlays",
        description="True: un overlay sin justificación es error (anti earnings-management, foco supervisor).")
```

**Defaults defendibles.** `audit.enabled=True` (un proyecto regulatorio audita por defecto); `flush_each=True` (durabilidad > velocidad en gobernanza); `purpose` **obligatorio** (`...`) — un modelo sin propósito declarado no es auditable (SR 11-7); `review_period_months=12` (revisión anual, práctica estándar de model risk); `publish_to_inventory=False` (no forzar la dependencia MLflow; opt-in); `require_overlay_justification=True` (la discrecionalidad sin rastro es el riesgo supervisor central).

**Serialización YAML/UI.** Igual que el resto (SDD-05 §5.5): `model_validate`/`model_dump(mode="json")`, round-trip YAML legible, UI generada desde `model_json_schema()`. **`audit` y `governance` son secciones de infraestructura → EXCLUIDAS del `config_hash`** (`INFRA_SECTIONS`, SDD-01 §5 / SDD-05 §5.5): cambiar la política de auditoría/gobernanza **no** altera la identidad del experimento (si la alterara, rompería la idempotencia del inventario, §6). El cambio queda registrado en el bundle/audit-trail, no vía el `config_hash`.

---

## 6. Contratos de datos (I/O)

**Input.**
- `audit`: una secuencia de `AuditEvent` (de `core` en tiempo de run) + el `LineageBundle` congelado; opcionalmente un `DataFrame`/archivos para hashear.
- `governance`: un `Study` finalizado (`status ∈ {done, failed}`), el trail JSONL persistido, y `GovernanceConfig`.

**Output.**
- `audit/`: un archivo **JSONL append-only** (`audit_trail.jsonl`), un `EnvironmentSnapshot` (JSON) y hashes (`str` hex).
- `governance/`: un `ModelCard` (objeto Pydantic → `model_card.json` + `model_card.md`), una `InventoryEntry` (publicada en MLflow Registry si `publish_to_inventory`), y `scenario_log.jsonl`.

Layout en el directorio del run (extiende el de SDD-01 §6):

```
runs/<run_id>/
├── config.yaml · run_metadata.json · lineage.json   (SDD-01)
├── audit_trail.jsonl        # SDD-03 audit/  (append-only, 1 evento/línea)
├── environment.json         # EnvironmentSnapshot
├── scenario_log.jsonl       # SDD-03 governance/ (escenarios + overlays)
├── model_card.json          # ModelCard serializado
└── model_card.md            # ModelCard render markdown (insumo SDD-26)
```

**Formato JSONL (contrato).** Cada línea es `json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n"`. **UTF-8**, `ensure_ascii=False` (los mensajes son en español: tildes/ñ legibles). Sin coma final, sin array envolvente → *append* O(1) y lectura *streaming*. Un evento corrupto al final (crash a media línea) se tolera en lectura (se descarta la última línea incompleta con warning; las previas son válidas — ventaja clave de JSONL sobre un JSON único).

**Invariantes (pre/post).**
- *Append-only:* `JsonlAuditSink.emit` solo añade; nunca reescribe ni trunca. El trail es **inmutable** una vez escrito (requisito auditor).
- *Round-trip del trail:* `read_trail(path)` devuelve `AuditEvent` semánticamente iguales a los emitidos (re-validados por Pydantic), en el mismo orden.
- *Orden:* el trail empieza con `run_start` y (si el run completó) termina con `run_end`; entre medias, eventos en orden de emisión.
- *Determinismo del model card:* dado el mismo `Study` + trail, `ModelCardBuilder.build` produce el mismo `ModelCard` salvo `review_date`/`next_review_date` (que dependen del reloj de emisión, no del run). Todo lo demás se deriva del bundle congelado → reproducible.
- *Coherencia de lineage:* `ModelCard.config_hash/data_hash/git_sha == study.lineage_bundle()` (no recomputa; copia del bundle).
- *Inventario (contrato impuesto al implementador):* `InventoryEntry.config_hash` identifica unívocamente la corrida; dos entradas con el mismo `config_hash`+`data_hash` son la misma corrida. SDD-03 **impone** como contrato del `Protocol ModelInventory` que `register` sea **idempotente por `config_hash`** (dos llamadas con el mismo `config_hash` devuelven la misma versión, sin duplicar). La **implementación** de ese contrato vive en SDD-04 (`MLflowInventory` lo cumple vía el tag `config_hash`, §7.2); aquí solo se define el contrato (frontera coordinada §12).

---

## 7. Algoritmos y flujo

> Pseudocódigo de alto nivel. SDD-03 reacciona a eventos y ensambla documentos; no calcula riesgo.

**Flujo `audit` (durante el run).**
1. La API construye `JsonlAuditSink(path, config=audit_cfg)` y lo inyecta con `study.set_audit_sink(sink)` **antes** de `run()`.
2. Cada vez que `core` emite (`run_start`/`decision`/`artifact`/`run_end`), `sink.emit(event)`:
   a. `line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)`.
   b. `append(line + "\n")`; si `flush_each`, `flush()` + `os.fsync` opcional (durabilidad).
3. En `run_end`, el sink ya tiene el trail completo. El `EnvironmentSnapshot` se captura **una vez** (al primer evento o explícitamente) y se vuelca a `environment.json`.

**Captura de entorno (`capture_environment`).**
- `python_version = platform.python_version()`; `platform = platform.platform()`.
- `library_versions`: por cada paquete en `tracked_packages` (o el set por defecto = deps declaradas de `nikodym` resueltas con `importlib.metadata.version`), `{pkg: version}`. Un paquete ausente se omite con warning (no aborta).
- `uv_lock_hash = hash_file("uv.lock")` si existe; si no, `None` + warning (coherente con SDD-01 §8).

**Hash de datos (`hash_dataframe`) — coordinación con SDD-02 (D-AUD-3).** `audit` provee la **utilidad de hashing**; **SDD-02 decide cuándo y sobre qué dataset** llamarla (es quien carga los datos) y escribe el resultado en el `LineageBundle.data_hash` durante su step (SDD-01 §7.3.d). Contrato del hash: **estable y canónico** — orden de filas/columnas fijado, dtypes normalizados, NaN representados de forma única (p.ej. `sha256` sobre `df.to_parquet` canónico, o `pandas.util.hash_pandas_object` agregado). La elección exacta (parquet canónico vs `hash_pandas_object` vs muestreo para datasets grandes) es **decisión abierta de SDD-02** (§12); `audit` expone la firma y un default razonable.

**Flujo `governance` (post-run).**
1. `ModelCardBuilder(gov_cfg).build(study, trail_path)`:
   a. Validar `study.run_context.status ∈ {done, failed}` (si `created`/`running` → `GovernanceError`). Un run **fallido** sí produce model card (documenta el fallo — útil para el validador).
   b. `bundle = study.lineage_bundle()` (congelado); copiar `config_hash/data_hash/git_sha/git_dirty/root_seed/schema_version/created_at/determinism_caveats`.
   c. `decisions`: filtrar el trail (`kind == "decision"`) → `DecisionRecord` (regla/umbral/valor/acción).
   d. `metrics`: extraer de `study.results` las claves de métrica (KS/AUC/PSI/…); `data_description` de la sección `data`/artefactos de SDD-02.
   e. `purpose/assumptions/limitations` de `gov_cfg`; `limitations` += `determinism_caveats` del bundle.
   f. `review_date = now(UTC)`; `next_review_date = review_date + review_period_months` (aritmética de meses sobre `datetime`, **sin dependencia nueva**: stdlib o `pandas.DateOffset(months=...)` — pandas ya es dependencia; ver §10).
   g. Devolver `ModelCard`; `to_markdown`/`to_json` para persistir.
2. **Publicación al inventario** (si `publish_to_inventory`): construir `InventoryEntry` y llamar `inventory.register(entry)`. Si SDD-04 no está instalado → `inventory` es `NullInventory` (no-op + warning "extra 'tracking' ausente"). **Frontera con SDD-04:** `governance` arma el `InventoryEntry` (qué metadatos, qué tags); `MLflowInventory` (SDD-04) traduce a llamadas `MlflowClient.create_model_version` + `set_registered_model_tag`/`set_model_version_tag` (tags y aliases reemplazan los *stages* deprecados — verificado context7). `config_hash` va como tag → idempotencia: si ya existe una versión con ese `config_hash`, `register` la devuelve sin duplicar.

**Registro de escenarios/overlays (`ScenarioLog`).** *Append-only* JSONL, igual mecánica que el trail. Lo alimentan SDD-20 (escenarios macro), SDD-21 (stress) y SDD-17 (overlays de provisión). `log_overlay` **exige `justification` no vacía** si `require_overlay_justification` (default True): la trazabilidad del ajuste discrecional es el control anti *earnings management* (ESPEC §9).

**Decisiones algorítmicas y alternativas descartadas.**
- **JSONL vs JSON único vs SQLite** para el trail: JSONL gana por *append* O(1), tolerancia a crash (líneas previas válidas), diff/grep directo y cero dependencias. SQLite (consultas ricas) descartado en v1 (sobre-ingeniería; un trail es secuencial, no relacional). JSON único descartado (no *append*, se corrompe entero ante crash).
- **`governance` no importa MLflow**: define el `Protocol ModelInventory` y SDD-04 lo implementa. Así `governance` funciona sin el extra `tracking` (NullInventory) y `core`/`governance` quedan libres de MLflow (núcleo liviano, §4 principio 9).

**Complejidad/rendimiento.** `emit` es O(1) por evento (append). `build` es O(nº eventos) (un pase por el trail). `flush_each=True` añade syscall por evento; para runs con miles de `decision` se puede desactivar (buffer) a costa de durabilidad ante crash.

---

## 8. Casos borde y manejo de errores

- **Sink no inyectado:** si nunca se llama `set_audit_sink`, el `Study` usa el `NullAuditSink` de `core` (no-op) → `run()` funciona, **no hay trail persistido**. `ModelCardBuilder.build` con `trail_path=None` o archivo ausente produce un model card **sin `decisions`** (lista vacía) + warning "trail no disponible: model card parcial". No es error (un run sin auditoría persistida sigue siendo válido), pero el card lo marca.
- **`trail_path=None` con sink persistente sí inyectado** (omisión por olvido del argumento): `trail_path` es la **única fuente** del trail para el Builder. Como `RunContext` (SDD-01 §4) **no expone `run_dir`** (solo `run_id`), el Builder **no adivina** la ruta del JSONL: con `trail_path=None` produce card **sin `decisions`** + warning, aunque el trail exista en disco. Contrato sin ambigüedad: **para incluir las `decisions` hay que pasar `trail_path` explícito** (vía obligatoria, como el ejemplo §4.2 `trail_path=sink.path`). El warning lo hace evidente para no perder decisiones por olvido.
- **Bundle incompleto:** `git_sha=None` (repo ausente/dirty), `data_hash=None` (run sin datos), `uv_lock_hash=None` → el model card registra los `None` **explícitamente** y los suma a `limitations` ("lineage parcial: sin git SHA / sin hash de datos"). No aborta — la transparencia del faltante es preferible a fallar.
- **Run fallido (`status="failed"`):** `build` **sí** produce model card (documenta hasta dónde llegó + la excepción registrada en el `run_end`). El card se marca `status=failed` en `limitations`. Un run **`created`/`running`** → `GovernanceError` (no hay nada que documentar).
- **JSONL corrupto** (crash a media línea): `read_trail`/`iter_trail` descartan la **última** línea si no parsea como JSON completo, con warning; las anteriores son válidas. Una línea intermedia corrupta (no debería ocurrir con append+flush) → `DataValidationError` (trail manipulado).
- **Overlay sin justificación** y `require_overlay_justification=True` → `GovernanceError` ("overlay '<id>' sin justificación: requerido por política anti earnings-management"). Mensaje en español con la regla gatillada (§4 principio 2).
- **`publish_to_inventory=True` sin extra `tracking`:** `inventory` resuelve a `NullInventory` → warning claro ("publicación al inventario requiere `pip install nikodym[tracking]`"); el model card local sí se genera. No aborta el pipeline por falta de un extra opcional.
- **`config.audit.enabled=False`:** la API no inyecta `JsonlAuditSink` (usa NullAuditSink); el resto del flujo funciona sin trail.
- **Doble emisión / sink reusado entre runs:** `JsonlAuditSink` es **un archivo por run**; reusar la misma instancia/path en dos runs mezclaría trails → contrato: una instancia por run (la API construye una nueva por `Study`). `close()` es idempotente.

**Excepciones propias.** SDD-03 define **`AuditError(NikodymError)`** (en `nikodym/audit/exceptions.py`) y **`GovernanceError(NikodymError)`** (en `nikodym/governance/exceptions.py`), siguiendo la **regla única** de SDD-01 §4: la raíz `NikodymError` y las excepciones del núcleo viven en `core.exceptions`, pero **cada módulo de dominio define sus propias subclases en su propio módulo** (igual que `TrackingError` en SDD-04). Así `except NikodymError` captura todo (incl. los `except` de SDD-17 overlays y SDD-22 validación) sin centralizar cada clase en `core`. Para faltas de datos al hashear se reutiliza `DataValidationError` (de `core`); para trail manipulado/inconsistente, `DataValidationError` o `ReproducibilityError` según el caso. Toda excepción desciende de `NikodymError`, mensaje en español con regla/umbral/valor cuando aplique.

---

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos:** **ninguno**. `audit`/`governance` son determinísticos (serializan y resumen estado ya producido). No piden `Generator` ni siembran nada. La única no-determinación es el **reloj** (`captured_at`, `review_date`), que es metadato de emisión, no del cómputo — excluido de los hashes.
- **Qué registra (es el módulo que *materializa* el audit-trail).** `audit` persiste **todo** lo que `core` emite (`run_start`/`decision`/`artifact`/`run_end`) más el `EnvironmentSnapshot`. `governance` deja el **model card** (con el lineage embebido) y el **scenario_log**. Juntos son la evidencia SR 11-7 pilar 3.
- **Determinismo del model card:** reproducible salvo `review_date`/`next_review_date`. Para tests, el reloj se inyecta (`now` parametrizable) → card bit-idéntico (§11).
- **Caveats:** SDD-03 **propaga** (no genera) los `determinism_caveats` del bundle al model card (p.ej. "GBDT multihilo no determinista"); no los oculta. Si el run fue `git_dirty`, el card lo declara como limitación de reproducibilidad.
- **Inmutabilidad del trail:** *append-only* + recomendación de almacenamiento WORM/permisos de solo-lectura post-run (operacional, fuera del código). El `config_hash` en el card permite detectar manipulación cruzando con `lineage.json`.

---

## 10. Dependencias

**Internas:** SDD-01 (`core`: `AuditSink`/`AuditEvent`, `LineageBundle`/`RunContext`, `Study`, `NikodymBaseConfig`, excepciones). Coordina con **SDD-02** (provee el `DataFrame` y decide el `data_hash`) y **SDD-04** (implementa `ModelInventory` sobre MLflow Registry). **No importa SDD-04** (inversión: define el `Protocol`).

**Externas:**

| Librería | Versión mín. | Licencia | Uso |
|---|---|---|---|
| pydantic | ≥ 2.5 | MIT ✅ | `ModelCard`, `EnvironmentSnapshot`, `InventoryEntry`, records. Verificado (context7, SDD-01): `model_dump(mode="json")`, `model_validate`. |
| (stdlib) | — | PSF | `json` (JSONL), `hashlib`, `platform`, `importlib.metadata`, `pathlib`, `datetime`, `os` (fsync). **JSONL es stdlib puro** — sin dependencia externa. |
| pandas | ≥ 2.0 | BSD ✅ | `hash_dataframe` (firma; el DataFrame lo provee SDD-02) y `DateOffset(months=...)` para `next_review_date`. Import perezoso. |

**Extra opcional `tracking` (SDD-04):** `mlflow` (Apache-2.0 ✅) **no es dependencia de SDD-03**. `governance.publish_to_inventory` solo funciona si el extra está instalado; sin él, `NullInventory` (import perezoso + mensaje al usuario). Frontera verificada (context7): el inventario usa `MlflowClient.create_model_version` + `set_registered_model_tag`/`set_model_version_tag` y **aliases** (los *stages* están deprecados) — pero esas llamadas viven en SDD-04, no aquí.

**Vetado:** todo copyleft (GPL). `audit`/`governance` no instalan MLflow por defecto (queda en el extra `tracking`).

---

## 11. Estrategia de tests

Detalle transversal en **SDD-24**; lo específico de SDD-03:

- **Round-trip del trail.** Emitir una secuencia conocida (`run_start → decision → artifact → run_end`) con `JsonlAuditSink`, releer con `read_trail` → `AuditEvent` iguales y en orden. Verificar **append-only** (el archivo solo crece; líneas previas intactas).
- **JSONL UTF-8.** Un `decision` con tildes/ñ en español round-trip sin mojibake (`ensure_ascii=False`). Una última línea truncada se descarta con warning; las previas se leen.
- **Model card determinístico.** Con reloj inyectado y mismo `Study`+trail, `build` produce un `ModelCard` bit-idéntico (golden JSON). `next_review_date == review_date + review_period_months`.
- **Casos borde** (cada uno un test): sink no inyectado → card sin `decisions` + warning; bundle con `git_sha=None`/`data_hash=None` → `None` explícitos + limitación registrada; run `failed` → card producido y marcado; run `created` → `GovernanceError`.
- **Overlay sin justificación** con `require_overlay_justification=True` → `GovernanceError` con la regla en el mensaje; con `False` → se registra.
- **Inventario con `NullInventory`** (sin extra): `publish_to_inventory=True` → warning, no aborta, card local generado. Test de `MLflowInventory` real **delegado a SDD-04** (allí vive la infra MLflow); aquí se testea contra un *fake* del `Protocol ModelInventory`.
- **`capture_environment`.** `library_versions` contiene las deps declaradas con versión válida; `uv_lock_hash` estable (mismo `uv.lock` → mismo hash); ausencia de `uv.lock` → `None` + warning.
- **`hash_dataframe`** estable: mismo DataFrame (reordenado por índice canónico) → mismo hash; cambiar una celda → hash distinto. (El contrato fino lo cierra SDD-02.)
- **Fixtures.** Un `Study` *dummy* finalizado con trail conocido; `InMemoryAuditSink` (de `core`) para comparar contra `JsonlAuditSink`; un `GovernanceConfig`/`AuditConfig` mínimos; un *fake* `ModelInventory`.

---

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas (trazabilidad).**
- **D-AUD-1 — Trail en JSONL append-only** (no JSON único ni SQLite en v1). *Porqué:* append O(1), tolerancia a crash (líneas previas válidas), diff/grep, cero dependencias (stdlib `json`). *Alternativa descartada:* SQLite (consultas ricas pero sobre-ingeniería para un log secuencial). **Reversible** si la consulta del trail lo exige (migración a SQLite/parquet en v2).
- **D-AUD-2 — `governance` define el `Protocol ModelInventory`; SDD-04 lo implementa sobre MLflow Registry** (inversión de dependencias). *Porqué:* `governance` no debe arrastrar MLflow (núcleo liviano); funciona con `NullInventory` sin el extra. La frontera: governance = *qué* metadatos/tags de la entrada de inventario; tracking = *cómo* se escriben en el Registry (verificado context7: `create_model_version` + tags + aliases, *stages* deprecados).
- **D-AUD-3 — `audit` provee `hash_dataframe`; SDD-02 decide cuándo/sobre-qué llamarlo y escribe `data_hash` en el bundle.** *Porqué:* separa la utilidad (hashing canónico) de la política (qué dataset, cuándo, muestreo) que es de quien posee los datos. El default razonable se da aquí; el contrato fino es de SDD-02.
- **D-AUD-4 — Model card también para runs `failed`.** *Porqué:* un fallo documentado es evidencia SR 11-7 valiosa para el validador; ocultarlo sería peor. Solo `created`/`running` no producen card.
- **D-AUD-5 — `purpose` obligatorio en `GovernanceConfig`.** *Porqué:* SR 11-7 — un modelo sin propósito declarado no es gobernable. Es la única fricción de config que se impone.
- **D-AUD-6 — `AuditError`/`GovernanceError` viven en su propio módulo (no en `core.exceptions`).** *Porqué:* la regla única de SDD-01 §4 aloja en `core` solo la raíz `NikodymError` y las del núcleo; cada dominio define sus subclases en su módulo (heredando de `NikodymError`), de modo que `except NikodymError` captura todo (incl. SDD-17/22) sin centralizar. Coherente con `TrackingError` (SDD-04). *No es decisión abierta:* el contrato del molde ya lo habilita.

**Decisiones abiertas (delegadas).**
- **Contrato exacto del `data_hash`** (parquet canónico vs `hash_pandas_object` vs muestreo para datasets grandes). *Responsable:* **autor SDD-02** (ya abierta en SDD-01 §12; SDD-03 solo expone la firma).
- **Esquema fino de tags/aliases del inventario en el Registry.** *Cerrado lo crítico:* `config_hash` es **tag canónico obligatorio** (ancla de la idempotencia afirmada en §6/§7.2) y los **aliases** (no *stages* deprecados) marcan el estado activo (p.ej. `@production`). *Abierto (coordinación):* tags descriptivos opcionales (`cartera`, `motor`, `estado`) y la convención exacta de aliases. *Responsable:* **SDD-03 ↔ SDD-04** (governance define las claves; tracking las escribe).
- **Idempotencia de `register` por `config_hash`** (contrato del `Protocol ModelInventory` que SDD-03 impone, §6). *Implementación responsable:* **SDD-04** (`MLflowInventory` lo cumple vía el tag `config_hash`); SDD-03 lo testea contra un *fake* del Protocol (§11).
- **Persistencia WORM/permisos de inmutabilidad del trail** (operacional). *Responsable:* SDD-25 (packaging/deploy) o guía de despliegue.

**Riesgos.**
- **Trail muy grande** (runs con miles de `decision`): JSONL crece linealmente. *Mitigación:* `iter_trail` lazy; `flush_each=False` para velocidad; rotación/compresión diferida a v2.
- **Acoplamiento con SDD-04** si la frontera se difumina (que `governance` empiece a hablar MLflow directo). *Mitigación:* el `Protocol ModelInventory` + tests contra un *fake* mantienen la inversión; cualquier `import mlflow` en `governance` es un fallo de revisión.
- **Earnings management no detectado** si los overlays no pasan por `ScenarioLog`. *Mitigación:* SDD-17 debe canalizar **todo** overlay por `log_overlay`; test de integración en SDD-22 (validación) que verifica que no haya overlays fuera del log.
- **Manipulación del trail post-run** (es un archivo de texto). *Mitigación:* `config_hash` en el card cruzado con `lineage.json`; recomendación WORM; firma/hash del trail completo diferida a v2.

---

### Citas

- ESPECIFICACIONES.md §1 (auditabilidad/reproducibilidad como producto), §4 (principio 2 auditabilidad por construcción, 3 gobernanza en el núcleo, 9 núcleo liviano, 10 calidad ejemplar), §6.1 (core agnóstico; UI importa el núcleo, no al revés → inversión de dependencias), §6.3 (árbol: `governance/` model card+inventario+lineage; `audit/` semillas+entorno+hash de datos+audit-trail), §8 (entregables: model card + audit log + run MLflow), §9 (SR 11-7 tres pilares; lineage bundle; model card automático con propósito/supuestos/limitaciones/datos/métricas/fecha/próxima revisión; inventario = MLflow Registry; registro auditable de escenarios y overlays = anti earnings-management), §11 (DoD F0: `audit`+`governance` = semillas/lineage/model card), §14 (SR 11-7 = Model Risk Management, Fed).
- 00-INDICE.md: SDD-03 (depende de 01; lo consume SDD-04 que provee la infra MLflow), §Convenciones (fórmulas/parámetros se citan, no se reescriben).
- SDD-01 (`core`): `AuditEvent`/`AuditSink`/`NullAuditSink`/`InMemoryAuditSink` (§4), `LineageBundle`/`RunContext` (§4), `Study.set_audit_sink`/`lineage_bundle` (§4, invariante "antes de run" §7), emisión de eventos en `run()` (§7.3), `core.exceptions` (§4, fuente única), `data_hash` completado por el step de datos (§7.3.d, §9), persistencia del run como directorio (§6), D-CORE-1 (inversión de dependencias), §12 (data_hash abierto).
- SDD-05: §4.2 (fila "NO es estimador" → contrato funcional propio, sin base de estimador), §4.3 (jerarquía de excepciones, mensajes en español con regla/umbral/valor), §4.4 (D-CONV-1 naming: inglés stats/IFRS9, prosa español), §5.1 (secciones `audit`/`governance` de `NikodymConfig`), §5.3 (defaults defendibles, `title`+`description` obligatorios), §5.5 (config_hash, round-trip YAML, UI desde model_json_schema).
- SDD-04 (`tracking`): provee la implementación de `ModelInventory` sobre MLflow Registry; frontera coordinada en §2/§7/§12.
- Verificado vía context7: **MLflow Model Registry** (`/mlflow/mlflow`) — `MlflowClient.set_registered_model_tag`/`set_model_version_tag` para metadatos de inventario; **aliases** (`set_registered_model_alias`, p.ej. `@production`) reemplazan los *stages* deprecados (`transition_model_version_stage`); `create_model_version`/`register_model` para versionar. Estas llamadas viven en SDD-04; SDD-03 solo define qué entra. **JSONL** es formato sobre stdlib `json` (sin librería externa): un objeto JSON por línea, `ensure_ascii=False` para UTF-8.
