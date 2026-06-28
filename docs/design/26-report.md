# SDD-26 — `report` (reporte y documentación automática)

| Campo | Valor |
|---|---|
| **SDD** | 26 |
| **Módulo** | `nikodym.report` |
| **Dominio** | Reporte |
| **Fase** | F1 |
| **Tanda de producción** | T2 (Scoring) |
| **Estado** | 🟡 Borrador |
| **Depende de** | SDD-01 (`core`), SDD-03 (`audit` + `governance`), SDD-05 (convenciones + config), SDD-06/07/08/09/10/11/27 (cards/results de scoring F1) |
| **Lo consumen** | Usuario final, validadores/auditores, release público `v0.1.0`, SDD-23 (`ui`) |
| **Autor / Fecha** | DanIA (redacción SDD-26 para T2) / 2026-06-28 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `report` ensambla un **reporte auditable de scorecard** a partir de los resultados/cards ya publicados por todos los dominios F1 y del `LineageBundle`, produciendo un HTML básico determinístico y standalone por defecto, con una capa de narrativa IA opcional que enriquece el texto sin tocar ni recalcular números.

**Restricción dura de producto (Cami, 2026-06-28).**
- **(a)** Interfaz **HTML + documentación automática básica sin IA** por default: funciona standalone, con **cero dependencia de API key** para lo básico.
- **(b)** Capa **IA opcional** activada por API key que enriquece la documentación ("casi completa"), con **degradación elegante**: sin key -> reporte básico funcional y completo; con key -> enriquecido. La IA es **opt-in, nunca obligatoria**.
- **(c)** Trampa env-gated crítica: el código gateado por API key/DSN puede quedar no-op en local/tests y dar "gates verdes que mienten". La ruta básica **nunca** depende de la capa IA. La capa IA se prueba **sin key real** mediante cliente/narrador inyectable y mock sin red; la ruta básica tiene cobertura 100% independiente. Los números los produce el pipeline determinístico; la IA **solo genera narrativa** y **nunca toca, recalcula ni inventa números**.

**Responsabilidad única (qué SÍ hace).**
- Recolecta, valida y ordena los `CardSection`/results de `eda`, `binning`, `selection`, `model`, `scorecard`, `calibration`, `performance` y `stability`.
- Construye un **model card consolidado** para la scorecard de comportamiento F1, respetando CT-2 (`metric_sections`) y sin romper futuros payloads estructurados.
- Embebe el `LineageBundle` SR 11-7: git SHA, `git_dirty`, `data_hash`, `config_hash`, `root_seed`, hash de `uv.lock`, versiones de librerías y caveats de determinismo.
- Renderiza un HTML básico determinístico con tablas, figuras estáticas/embebidas y narrativa estándar generada por reglas/plantillas.
- Opcionalmente invoca una capa IA para enriquecer redacción ejecutiva e interpretación **a partir de un payload derivado y sanitizado**, etiquetando cada bloque como "generado por IA".
- Exporta artefactos de reporte y deja constancia auditable de motor, plantilla, secciones incluidas, secciones omitidas y estado de la capa IA.

**Frontera dura de responsabilidad (qué NO hace, y quién lo hace).**
- **No calcula métricas ni fórmulas de riesgo.** KS/AUC/Gini/PSI/CSI vienen de SDD-11; WoE/IV de SDD-06/07; score y PD de SDD-09/10. `report` solo lee artefactos ya materializados.
- **No valida formalmente el modelo.** Hosmer-Lemeshow, binomial, traffic-light, Brier y backtesting formal son SDD-22 (`validation`).
- **No gobierna ni persiste el audit trail.** SDD-03/01 construyen y persisten eventos/lineage/model cards; `report` los presenta.
- **No publica a destinos externos por defecto.** Exportar/subir a un repositorio, portal o destino cliente es evento sensible y queda como decisión R0 (§12).
- **No depende de Quarto ni de un SDK IA para la ruta crítica.** HTML básico por Jinja2 puro-Python es el fallback siempre disponible; Quarto/PDF/Word y la IA son capas opcionales.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Reporte transversal, ejecutado al final de F1/T2. En el pipeline de scorecard de comportamiento corre después de `stability` y antes del cierre/publicación del release `v0.1.0`.
- **Quién lo invoca:** `Study.run()` como sección `report` de `NikodymConfig`, la API programática (`study.report(...)` o helper equivalente) y, en F7, la UI (SDD-23).
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `LineageBundle`, `AuditableMixin`, excepciones), cards/results F1 ya publicados, `jinja2` para HTML básico, y opcionalmente Quarto/plotly/matplotlib/SDK IA con import o detección perezosa.

```
data -> eda -> binning -> selection -> model -> scorecard -> calibration -> performance -> stability
                                                                                              |
                                                                                              v
                                                                                    report (SDD-26)
                                                                                    cards + lineage
                                                                                    HTML básico
                                                                                    Quarto/PDF opcional
                                                                                    IA opcional
```

**Interacción con `Study` y config declarativo.** `ReportStep` es un `Step` nativo registrado con `@register("standard", domain="report")`. Declara `requires`/`provides` (CT-1), lee del `ArtifactStore` las cards/results disponibles y escribe sus propios artefactos bajo `"report"`. El `rng` se recibe por contrato homogéneo, pero la ruta básica no usa azar y debe hacer `del rng`.

**No es dependencia de build de dominios.** `report` consume resultados ya construidos; ningún dominio F1 debe importar `nikodym.report` para funcionar. Esta frontera mantiene el núcleo liviano de SDD-01 y evita ciclos: `eda`/`binning`/`selection`/`model`/`scorecard`/`calibration`/`performance`/`stability` publican cards; `report` las lee.

**Cableado futuro en `core.study`.** Al implementar SDD-26:
- `_DOMAIN_MODULES["report"] = "nikodym.report"`;
- `_DOMAIN_CONFIG_CLASSES["report"] = ("nikodym.report.config", "ReportConfig")`;
- `_DEFAULT_DOMAIN_ORDER` agrega `"report"` inmediatamente después de `"stability"`;
- `report` permanece en la zona de **infraestructura** de SDD-05, no en el tramo computacional del pipeline.

## 3. Conceptos y fundamentos

**Documentación automática.** Documento generado por máquina desde artefactos estructurados del pipeline. No es una narración manual posterior: el contenido cuantitativo se toma de DTOs/tables/cards ya versionados y se renderiza bajo una plantilla canónica.

**Model card consolidado.** Vista de lectura para validadores y usuarios: propósito del modelo, población, datos, binning, selección, modelo, scorecard, calibración, performance, estabilidad, limitaciones y lineage. No reemplaza los `CardSection` de cada dominio: los agrega en orden canónico y conserva sus `metric_sections` CT-2 para secciones estructuradas.

**Narrativa básica determinística.** Texto generado por plantillas y reglas simples, sin IA. Ejemplos: "El modelo usa N variables finales"; "La partición OOT no está disponible"; "El PSI máximo del score cae en banda review". Este texto es función pura del `ReportInputBundle` + `ReportConfig`.

**Narrativa IA opt-in.** Texto opcional generado por un proveedor externo. Debe:
- estar marcada explícitamente como **"generada por IA"** en el HTML;
- recibir solo un payload derivado/sanitizado: métricas agregadas, nombres de secciones, flags y conclusiones estructuradas; **nunca datos crudos de cliente, PII, filas individuales, IDs, documentos internos ni secretos**;
- no poder modificar tablas, números, gráficos, lineage ni decisiones auditadas;
- degradar a narrativa básica si falta la key, el proveedor falla o se excede timeout.

**Determinismo de la ruta básica.** Mismo `ReportInputBundle`, misma plantilla, mismo `ReportConfig`, mismo `uv.lock` -> mismo HTML básico byte a byte. Para lograrlo: orden estable de secciones/tablas, formato numérico fijo, IDs determinísticos, sin timestamps de pared, sin UUIDs aleatorios y con assets embebidos o nombres derivados por hash estable.

**CMF / SR 11-7.** El reporte no contiene parámetros CMF nuevos. Su obligación regulatoria es de evidencia/documentación: trazabilidad, metodología, supuestos, limitaciones, validación disponible y lineage reproducible. Esto se ancla en ESPECIFICACIONES §4/§9 y en el rol SR 11-7 de SDD-03.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/report/config.py
class ReportConfig(NikodymBaseConfig): ...
class HtmlRenderConfig(NikodymBaseConfig): ...
class QuartoRenderConfig(NikodymBaseConfig): ...
class AiNarrationConfig(NikodymBaseConfig): ...
class SectionPolicyConfig(NikodymBaseConfig): ...

# nikodym/report/exceptions.py
class ReportError(NikodymError): ...
class ReportInputError(ReportError): ...
class ReportRenderError(ReportError): ...
class ReportExportError(ReportError): ...
class ReportAIError(ReportError): ...
class ReportDependencyError(ReportError): ...
```

```python
# nikodym/report/results.py
class ReportSection(BaseModel):
    id: str
    title: str
    status: Literal["included", "missing", "skipped", "failed"]
    source_domain: str | None
    source_key: str | None
    payload: dict[str, Any] = Field(default_factory=dict)
    metric_sections: dict[str, Any] = Field(default_factory=dict)  # CT-2.

class ReportInputBundle(BaseModel):
    lineage: "LineageBundle"
    cards: dict[str, Any]
    tables: dict[str, "pandas.DataFrame"]
    figures: dict[str, Any]
    sections: tuple[ReportSection, ...]
    missing_sections: tuple[str, ...] = ()
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

class AiNarrationBlock(BaseModel):
    section_id: str
    text: str
    provider: str
    model: str
    generated: bool
    prompt_hash: str
    input_payload_hash: str
    warning: str | None = None

class ReportManifest(BaseModel):
    report_id: str
    title: str
    created_from_lineage_at: str
    template_id: str
    template_version: str
    output_format: Literal["html", "pdf", "docx", "json", "csv", "xlsx"]
    path: str
    sha256: str
    deterministic: bool
    ai_enabled: bool
    ai_used: bool
    sections: tuple[ReportSection, ...]

class ReportResult(BaseModel):
    manifest: ReportManifest
    input_bundle: ReportInputBundle
    html_path: str | None = None
    pdf_path: str | None = None
    docx_path: str | None = None
    data_exports: dict[str, str] = Field(default_factory=dict)
    ai_blocks: tuple[AiNarrationBlock, ...] = ()
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
```

```python
# nikodym/report/builder.py
class ReportBuilder:
    """Ensambla el documento lógico desde cards/results. No renderiza."""
    def __init__(self, config: "ReportConfig") -> None: ...
    @classmethod
    def from_config(cls, cfg: "ReportConfig") -> "ReportBuilder": ...
    def collect(self, study: "Study") -> "ReportInputBundle": ...
    def build_sections(self, bundle: "ReportInputBundle") -> tuple[ReportSection, ...]: ...
    def build_manifest(self, bundle: "ReportInputBundle", *, path: str) -> "ReportManifest": ...

# nikodym/report/renderer.py
class HtmlReportRenderer:
    """Render HTML standalone determinístico con Jinja2."""
    def render(self, bundle: ReportInputBundle, *, ai_blocks: tuple[AiNarrationBlock, ...] = ()) -> str: ...
    def write(self, html: str, *, output_dir: str) -> ReportManifest: ...

class QuartoReportRenderer:
    """Render opcional vía binario externo quarto para PDF/Word."""
    def render(self, bundle: ReportInputBundle, *, output_dir: str) -> ReportManifest: ...
```

```python
# nikodym/report/ai.py
@runtime_checkable
class AIClient(Protocol):
    def generate(self, request: "AIRequest") -> "AIResponse": ...

class RuleBasedNarrator:
    """Narrador determinístico sin red: ruta básica y fallback."""
    def narrate(self, bundle: ReportInputBundle) -> tuple[AiNarrationBlock, ...]: ...

class AINarrator:
    """Narrador opt-in con cliente inyectable; nunca modifica bundle ni números."""
    def __init__(self, config: AiNarrationConfig, *, client: AIClient | None = None) -> None: ...
    def enrich(self, bundle: ReportInputBundle) -> tuple[AiNarrationBlock, ...]: ...
```

```python
# nikodym/report/step.py
@register("standard", domain="report")
class ReportStep(AuditableMixin):
    name: str = "report"
    requires: tuple[ArtifactKey, ...] = (
        ("eda", "eda_card"),
        ("binning", "binning_card"),
        ("selection", "selection_card"),
        ("model", "model_card"),
        ("scorecard", "card"),
        ("calibration", "card"),
        ("performance", "card"),
        ("stability", "card"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("report", "input_bundle"),
        ("report", "manifest"),
        ("report", "result"),
    )
    @classmethod
    def from_config(cls, cfg: ReportConfig) -> "ReportStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "ReportResult": ...
```

**Nota sobre secciones ausentes y CT-1.** El `ReportStep` canónico de F1 exige las cards de scorecard completas. Para uso exploratorio/standalone, `ReportBuilder.collect(..., missing_policy="warn"|"skip")` puede construir un reporte parcial sin registrarse como `Step` F1 completo. Así la corrida de release falla ruidosamente si falta una pieza obligatoria, pero la API de reporte puede degradar cuando el usuario pide un documento parcial.

**Artefactos que `ReportStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"input_bundle"` | `ReportInputBundle` | snapshot lógico de cards/tables/figuras/lineage usados para renderizar |
| `"manifest"` | `ReportManifest` | outputs, hashes, secciones, motor, plantilla, estado IA |
| `"result"` | `ReportResult` | contenedor agregado con rutas y bloques de narrativa |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=[
    "data", "eda", "binning", "selection", "model",
    "scorecard", "calibration", "performance", "stability", "report",
])
manifest = study.artifacts.get("report", "manifest")
```

## 5. Configuración (schema Pydantic)

`ReportConfig` es el sub-config de la sección `report` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, campos con `title`/`description`, `Literal` en categóricos, rangos `ge/le` y metadatos `ui_*` para SDD-23. A diferencia de `performance`/`stability`, **`report` es infraestructura** y está en `INFRA_SECTIONS` (SDD-05 §5.5).

```python
# nikodym/report/config.py
class HtmlRenderConfig(NikodymBaseConfig):
    template_id: str = Field("scorecard_basic_v1", title="Plantilla HTML")
    theme: Literal["nikodym", "plain"] = Field("nikodym", title="Tema visual")
    embed_assets: bool = Field(True, title="Embeder assets")
    include_interactive_charts: bool = Field(False, title="Gráficos interactivos")
    deterministic_ids: bool = Field(True, title="IDs determinísticos")

class QuartoRenderConfig(NikodymBaseConfig):
    enabled: bool = Field(False, title="Activar Quarto")
    formats: tuple[Literal["pdf", "docx"], ...] = Field((), title="Formatos Quarto")
    fail_if_unavailable: bool = Field(False, title="Fallar si Quarto no está disponible")

class AiNarrationConfig(NikodymBaseConfig):
    enabled: bool = Field(False, title="Activar narrativa IA")
    provider: Literal["anthropic", "none"] = Field("none", title="Proveedor IA")
    model: str | None = Field(None, title="Modelo IA")
    api_key_env: str = Field("ANTHROPIC_API_KEY", title="Variable de API key")
    timeout_seconds: float = Field(20.0, ge=1.0, le=120.0, title="Timeout IA")
    max_input_tokens: int = Field(12_000, ge=1_000, title="Máximo tokens entrada")
    send_raw_data: Literal[False] = Field(False, title="Enviar datos crudos")
    label_ai_text: bool = Field(True, title="Etiquetar texto generado por IA")

class SectionPolicyConfig(NikodymBaseConfig):
    required_sections: tuple[str, ...] = Field(
        ("eda", "binning", "selection", "model", "scorecard", "calibration", "performance", "stability"),
        title="Secciones obligatorias F1",
    )
    missing_policy: Literal["error", "warn", "skip"] = Field("error", title="Política de sección ausente")
    include_raw_tables: bool = Field(False, title="Incluir tablas completas")
    max_table_rows: int = Field(200, ge=10, title="Máximo filas por tabla renderizada")

class ReportConfig(NikodymBaseConfig):
    schema_version: str = "1.0.0"
    type: Literal["standard"] = "standard"
    output_dir: str = Field("reports", title="Directorio de salida")
    basename: str = Field("scorecard_report", title="Nombre base")
    language: Literal["es"] = Field("es", title="Idioma")
    formats: tuple[Literal["html", "json", "csv", "xlsx"], ...] = Field(("html",), title="Formatos básicos")
    html: HtmlRenderConfig = Field(default_factory=HtmlRenderConfig, title="HTML")
    quarto: QuartoRenderConfig = Field(default_factory=QuartoRenderConfig, title="Quarto")
    ai: AiNarrationConfig = Field(default_factory=AiNarrationConfig, title="Narrativa IA")
    sections: SectionPolicyConfig = Field(default_factory=SectionPolicyConfig, title="Secciones")
```

**Defaults defendibles.**
- `formats=("html",)`: satisface la ruta básica standalone sin binarios externos.
- `quarto.enabled=False`: Quarto no puede ser dependencia crítica porque es binario externo.
- `ai.enabled=False` y `provider="none"`: la IA es opt-in y no existe requisito de key.
- `send_raw_data=False` como `Literal[False]`: no hay modo soportado en F1 para enviar datos crudos.
- `missing_policy="error"` en el Step canónico F1: release `v0.1.0` debe demostrar scorecard end-to-end completa; la degradación parcial queda para API standalone.

**`config_hash` y `GOLDEN_DEFAULT_CONFIG_HASH`.** SDD-05 define `INFRA_SECTIONS = {"name", "governance", "audit", "tracking", "report"}`. Por tanto:
- Cambiar `output_dir`, plantilla, formatos, Quarto o IA **no cambia** el `config_hash` del experimento.
- Al cablear `ReportConfig` en `NikodymConfig`, el `GOLDEN_DEFAULT_CONFIG_HASH` **no debería moverse** si la implementación respeta `exclude=INFRA_SECTIONS` y el default `report=None`/`ReportConfig()` queda excluido del JSON canónico.
- Si un test golden se mueve al agregar `report`, eso indica bug en exclusión canónica o en el fixture, no una decisión de diseño como `performance`/`stability` (que sí son computacionales y sí mueven hash).
- El hash del **artefacto HTML** vive en `ReportManifest.sha256` y es distinto del `config_hash`.

**Hook diferido en `core.config.schema`.** Al implementar:
- declarar `_REPORT_CONFIG_CLS`;
- añadir validator `_valida_report` siguiendo el patrón de `data`/dominios T2;
- `nikodym.report.__init__` puebla el hook y registra `ReportStep`;
- `report` permanece en `INFRA_SECTIONS`.

## 6. Contratos de datos (I/O)

**Inputs de `ReportStep` vía `Study`.**

| dominio | clave(s) | uso |
|---|---|---|
| `core` / run context | `LineageBundle` y audit summary | reproducibilidad, SR 11-7, versiones, seeds |
| `eda` | `eda_card`, `default_rate`, `stability`, `quality`, `figures` | tasa de default por período, perfil descriptivo, figuras |
| `binning` | `binning_card`, `summary`, `tables` | cortes, WoE, IV, variables binneadas/omitidas |
| `selection` | `selection_card`, `selection_table`, `correlation_matrix`, `vif_table`, `stability_table` | razones de selección/descarte, correlación/VIF/PSI/CSI pre-modelo |
| `model` | `model_card`, `coefficients`, `fit_statistics`, `stepwise_trace`, `raw_pd_frame` | logística, coeficientes, p-values, trazas, PD cruda |
| `scorecard` | `card`, `scorecard`, `score` | escala PDO/offset/factor, puntos por atributo, score |
| `calibration` | `card`, `parameters`, `calibrated_pd_frame` | ancla, método, PD calibrada |
| `performance` | `card`, `performance_table`, `discriminant_metrics` | KS/AUC/Gini, deciles/gains |
| `stability` | `card`, `psi_table`, `stability_metrics` | PSI score/PD, CSI y estabilidad temporal |

**Estructura canónica interna.** `ReportBuilder.collect` normaliza los nombres heterogéneos de cards (`binning_card`, `selection_card`, `model_card`, `card`) a:

```text
cards = {
  "eda": EdaCardSection,
  "binning": BinningCardSection,
  "selection": SelectionCardSection,
  "model": ModelCardSection,
  "scorecard": ScorecardCardSection,
  "calibration": CalibrationCardSection,
  "performance": PerformanceCardSection,
  "stability": StabilityCardSection,
}
```

**Outputs.**
- **HTML básico:** archivo `.html` standalone, UTF-8, con CSS/figuras embebidas o referenciadas por hashes determinísticos.
- **Manifest:** JSON serializable con ruta, sha256, plantilla, motor, secciones, estado IA, estado Quarto y lineage.
- **Exports tabulares:** CSV/JSON/XLSX opcionales de tablas ya producidas por dominios; `report` no cambia columnas ni reordena semántica, solo normaliza orden de filas/columnas para export.
- **Quarto/PDF/Word opcional:** artefactos derivados del mismo `ReportInputBundle`, nunca fuente primaria.
- **DTO `ReportResult`:** contenedor agregado publicado en `study.artifacts`.

**Invariantes.**
- `ReportInputBundle` es snapshot de lectura; no muta artefactos aguas arriba.
- Toda tabla renderizada declara dominio, clave fuente y timestamp/lineage de la corrida, si está disponible.
- Todo número visible viene de un artefacto F1 o del lineage; la IA no puede aportar valores numéricos nuevos.
- Secciones y tablas se ordenan por lista canónica: `lineage`, `eda`, `binning`, `selection`, `model`, `scorecard`, `calibration`, `performance`, `stability`, `limitations`, `appendix`.
- Si una sección está ausente en modo parcial, se registra en `missing_sections` y se renderiza una nota explícita; no se oculta.

## 7. Algoritmos y flujo

**`ReportStep.execute(study, rng)` - secuencia canónica.**
1. **Descartar azar.** `del rng`; la ruta básica no usa aleatoriedad.
2. **Leer config.** Resolver `study.config.report` o `ReportConfig()` para invocación programática.
3. **Validar prerequisitos CT-1.** En modo F1 completo, exigir las cards de §4; una ausencia es `ArtifactNotFoundError` antes de renderizar.
4. **Recolectar lineage.** Tomar `LineageBundle`/run context de `core`: git SHA, dirty flag, `data_hash`, `config_hash`, `root_seed`, `uv.lock`, versiones y caveats.
5. **Recolectar cards/tables.** Leer artefactos de cada dominio, con copias defensivas para tablas.
6. **Normalizar bundle.** Construir `ReportInputBundle`: secciones canónicas, `metric_sections` CT-2, tablas acotadas, figuras declarativas, faltantes.
7. **Generar narrativa básica.** `RuleBasedNarrator` produce bloques determinísticos a partir del bundle.
8. **Enriquecer con IA (opcional).** Si `ai.enabled=True` y hay key/cliente inyectado, `AINarrator` envía solo payload derivado/sanitizado. Si falta key, hay timeout o error, registra warning y usa narrativa básica.
9. **Render HTML básico.** `HtmlReportRenderer` genera HTML standalone con IDs determinísticos, formato numérico estable y bloques IA etiquetados si existen.
10. **Export opcional.** Escribir CSV/JSON/XLSX de tablas seleccionadas; si `quarto.enabled=True`, detectar binario y renderizar PDF/DOCX según config.
11. **Hash y manifest.** Calcular sha256 de cada artefacto, construir `ReportManifest`.
12. **Auditar decisiones.** `log_decision` para secciones omitidas, Quarto ausente, fallback IA, uso de IA y publicación/export externo si se habilita.
13. **Publicar artefactos.** Escribir `"input_bundle"`, `"manifest"` y `"result"` bajo dominio `"report"`.

**Determinismo del HTML básico.**
- `float_format` fijo por métrica (p.ej. PD/PSI con 6 decimales; porcentajes con 2 o 4 decimales según tabla).
- Sin fecha/hora de generación tomada del reloj; usar `LineageBundle.created_at` si ya existe.
- Sin IDs aleatorios de Plotly en ruta básica; si hay gráficos interactivos opcionales, IDs derivados de `section_id + figure_id`.
- Orden estable de dicts y tablas antes de renderizar.

**Manejo de secciones ausentes.**
- `missing_policy="error"`: error ruidoso, default del Step F1 completo.
- `missing_policy="warn"`: sección renderizada como ausente y evento de auditoría; útil para notebook/documento parcial.
- `missing_policy="skip"`: omite sección y la lista en el apéndice `missing_sections`; no se permite para release `v0.1.0`.

**Alternativas descartadas.**
- *Quarto como única ruta de HTML:* descartado para la ruta básica porque un binario externo rompe portabilidad CI/local y contradice la degradación standalone.
- *Narrativa IA como fuente de números:* descartado por ESPEC §4 ("La IA documenta, nunca calcula") y por riesgo regulatorio.
- *Enviar tablas crudas completas a la API IA:* descartado por privacidad, PII y reproducibilidad.
- *Generar reporte desde notebooks ad hoc:* descartado; el reporte debe consumir contratos tipados/cards para ser auditable.

## 8. Casos borde y manejo de errores

- **Sin API key IA:** no es error. `ai_used=False`, warning en manifest, narrativa básica completa.
- **`ai.enabled=True` pero proveedor/modelo no configurado:** `ReportAIError` solo si `fail_on_ai_error=True` (no default); por defecto fallback básico y evento auditado.
- **Proveedor IA caído, timeout, rate limit o respuesta inválida:** capturar, registrar `log_decision(regla="ai_fallback", accion="usar_narrativa_basica")`, continuar HTML básico. La ruta crítica nunca cae por IA.
- **Cliente IA mock/in-memory:** debe poder inyectarse por constructor; si existe, no se lee env var ni se abre red.
- **Quarto ausente:** si `quarto.enabled=False`, no se detecta. Si `enabled=True` y `fail_if_unavailable=False`, se emite HTML básico y warning. Si `fail_if_unavailable=True`, `ReportDependencyError` con mensaje claro ("instala Quarto desde quarto.org").
- **Dominio obligatorio ausente en Step F1:** `ArtifactNotFoundError` por CT-1 antes de renderizar.
- **Dominio ausente en builder parcial:** sección `missing`, sin números inventados.
- **Card presente pero `metric_sections` no serializable:** `ReportInputError`; el dominio debe publicar payload estructurado serializable/aditivo.
- **Tabla demasiado grande:** truncar visualmente a `max_table_rows` con indicador explícito; export completo opcional si `include_raw_tables=True` y está permitido. Nunca truncar silenciosamente.
- **Datos sensibles en nombres/columnas:** `report` no puede garantizar anonimización si un dominio publica PII en una card; debe detectar columnas con patrones obvios (`rut`, `email`, `phone`, `id_cliente`) y bloquear envío a IA. Render local HTML puede mostrar lo que el dominio publicó, pero el payload IA se sanitiza.
- **Output dir no escribible:** `ReportExportError` antes de llamar IA o Quarto; no producir reporte parcial invisible.
- **Render sin datos:** en modo parcial, HTML con portada, lineage disponible y secciones ausentes; en modo F1 completo, error.

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen dominio, clave, sección y acción recomendada.

## 9. Reproducibilidad y auditoría

- **Ruta básica determinística.** `ReportInputBundle + ReportConfig básico + plantilla + uv.lock -> HTML sha256 idéntico`. Esta garantía excluye explícitamente narrativa IA y renderizadores externos no controlados.
- **Narrativa IA no determinística y aislada.** Los bloques IA se marcan `generated=True`, proveedor/modelo, `prompt_hash`, `input_payload_hash`, timeout y warning si aplica. No entran al `config_hash`; sí quedan en `ReportManifest` y audit trail como evidencia de documentación auxiliar.
- **Lineage embebido.** El reporte muestra git SHA, dirty flag, `data_hash`, `config_hash`, `root_seed`, hash de `uv.lock`, versiones de librerías y caveats. Esto viene de SDD-01/03; `report` no lo recalcula.
- **No mutación de inputs.** Copias defensivas de DataFrames; ninguna escritura en dominios aguas arriba.
- **Audit trail (`log_decision`).** Registrar:
  - secciones obligatorias ausentes o secciones omitidas;
  - truncamiento visual de tablas;
  - fallback de IA por key ausente/error/timeout;
  - uso exitoso de IA (sin incluir prompt completo si contiene información sensible; guardar hashes y metadata);
  - Quarto ausente o fallback a HTML;
  - export/publicación externa, si se habilita.
- **Byte reproducibility.** El HTML básico no incluye fecha actual, rutas absolutas locales, UUIDs, orden de dict dependiente de hash ni IDs aleatorios. Rutas locales se relativizan dentro del manifest.
- **Privacidad IA.** El payload a la API contiene solo agregados derivados y texto de cards sanitizado. No se envían datos crudos, PII, IDs de cliente, nombres de personas, rutas locales ni secretos.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `LineageBundle`, excepciones, `AuditableMixin`.
- SDD-03 (`audit` + `governance`): model card, audit trail, SR 11-7, `metric_sections`.
- SDD-05: `ReportConfig`, `INFRA_SECTIONS`, round-trip YAML, `config_hash`.
- SDD-06/07/08/09/10/11/27: cards, tablas y results de F1.
- SDD-25: packaging/extras, detección de binario externo Quarto, CI.

**Externas.**

| Dependencia | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| jinja2 | `>=3.1` | BSD-3 ✅ | HTML básico determinístico | base o extra `[report]` obligatorio para usar `nikodym.report` |
| matplotlib | `>=3.7` | PSF-based/BSD-compatible ✅ | figuras estáticas opcionales | extra `[report]`, import perezoso |
| plotly | `>=5.0` | MIT ✅ | figuras interactivas HTML opcionales | extra `[report]`, import perezoso |
| Quarto | binario externo | permisiva ✅ | PDF/DOCX/HTML avanzado | opcional, detección por `PATH` |
| anthropic | SDK Python | licencia de SDK/API | narrativa IA opcional | extra `[ai]` o `[report-ai]`, import perezoso |

**Portabilidad CI/tests.**
- HTML básico por Jinja2 puro-Python debe correr en CI sin Quarto, sin Chrome, sin LaTeX y sin API key.
- Quarto/PDF/Word se prueban con detección explícita: tests unitarios mockean el binario; integración real puede ser marcada `requires_quarto`.
- `import nikodym.report` no debe importar matplotlib, plotly ni SDK IA en top-level. Si `jinja2` se deja en extra, el error debe ser `MissingDependencyError("instale nikodym[report]")` al renderizar, no al importar `core`.

**Decisión pendiente de packaging.** SDD-25 reservó el extra `report` porque Quarto no es pip-installable. Recomendación técnica: `jinja2` debe estar disponible para la ruta básica F1; matplotlib/plotly/SDK IA permanecen opcionales y perezosos. Cami decide si `jinja2` entra en base o en `[report]`.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos:

- **HTML básico determinístico (golden).** Fixture F1 completo con cards sintéticas -> HTML sha256 fijo; segunda corrida idéntica byte a byte.
- **Cobertura 100% de ruta básica independiente de IA.** Tests de `ReportBuilder`, `RuleBasedNarrator` y `HtmlReportRenderer` sin env vars ni mocks de SDK IA.
- **IA sin key real, sin red.** `AINarrator` acepta `AIClient` inyectable; test con `FakeAIClient` devuelve narrativa controlada, verifica etiquetas "generada por IA", `prompt_hash`, `input_payload_hash` y que ninguna tabla/número cambie.
- **Degradación IA.** Fake client levanta timeout/error/rate limit -> HTML básico se produce igual, `ai_used=False`, evento `ai_fallback`, manifest con warning.
- **Trampa env-gated.** Test fuerza `ai.enabled=True` sin `ANTHROPIC_API_KEY`: no se salta la rama por no-op invisible; se ejecuta explícitamente la ruta de fallback y se asevera el warning. Otro test usa cliente inyectado aunque no haya env var.
- **No red en tests.** Bloquear sockets o usar monkeypatch para garantizar que los tests IA no contactan proveedor real.
- **No mutación.** Snapshots de cards/tables antes/después de `ReportStep.execute` permanecen iguales.
- **Contratos CT-1.** Faltan cards obligatorias -> `ArtifactNotFoundError` en Step completo. Builder parcial con `missing_policy="warn"` renderiza sección ausente explícita.
- **Contratos CT-2.** `metric_sections` estructurado dummy se renderiza/serializa sin filtrar a escalares; cubre la puerta F4/F5.
- **Privacidad IA.** Payload sanitizado no contiene filas crudas, IDs, columnas PII obvias ni rutas locales. Si aparece patrón sensible, se excluye o falla antes de llamar cliente.
- **Quarto portable.** Sin binario Quarto: HTML básico pasa; Quarto enabled con `fail_if_unavailable=False` warning; con `True` error claro. Test con binario fake verifica invocación sin requerir Quarto real.
- **Import liviano.** `import nikodym.core` no importa `nikodym.report`; `import nikodym.report` no importa matplotlib/plotly/anthropic. Si se elige `jinja2` perezoso, tampoco se exige hasta render.
- **Config.** Round-trip YAML de `ReportConfig`; cambiar plantilla/output/IA/Quarto no cambia `config_hash` porque `report ∈ INFRA_SECTIONS`; manifest hash sí cambia si cambia HTML.
- **Tooling.** `filterwarnings=["error"]`, `mypy --strict`, ruff con docstrings en español, cobertura 100% del módulo `report` para v0.1.0.

Fixtures: `ReportInputBundle` sintético completo, `LineageBundle` fijo, cards F1 mínimas, tablas pequeñas con valores conocidos, `FakeAIClient`, `InMemoryAuditSink`, directorio temporal de outputs.

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Reporte que recalcula métricas.** Mitigación: `report` solo lee cards/results; tests verifican que no llama evaluadores de dominios ni modifica números.
- **Falsos verdes env-gated.** Mitigación: cliente IA inyectable, tests sin key real, fallback ejercitado explícitamente y cobertura independiente de ruta básica.
- **Quarto rompe CI/local.** Mitigación: HTML básico Jinja2 como ruta primaria; Quarto opcional y testeado con mock/detección.
- **Filtración de datos a IA.** Mitigación: `send_raw_data=False` literal, sanitización, bloqueo de PII obvia, tests de payload y decisión de Cami sobre proveedor/costos/privacidad.
- **HTML no reproducible por timestamps/IDs aleatorios.** Mitigación: usar lineage timestamp, IDs determinísticos, orden estable y golden sha256.
- **Confundir documentación con validación formal.** Mitigación: el reporte etiqueta qué métricas son F1 y que SDD-22 contiene backtesting/validación avanzada.
- **Publicación externa accidental.** Mitigación: export local por defecto; destinos externos requieren config explícito y evento auditado R0.

**Fuentes verificadas / citas.**
- **ESPECIFICACIONES.md** §3.1 (documentación automática Quarto + narrativa IA opcional), §4 principios 1/2/3/7/9/10/11 (reproducibilidad, auditabilidad, SR 11-7, IA documenta/no calcula, núcleo liviano, calidad, doble verificación), §5.8 (Quarto HTML+PDF+Word, IA opcional, sin key -> reporte base determinístico completo, exports), §6.3 (`report/`), §7 (dependencias reporte permisivas), §8 (reporte Quarto HTML+PDF), §9 (lineage bundle), §11 F1 (Reporte Quarto y release público `v0.1.0`).
- **ROADMAP.md** F1: scorecard de comportamiento end-to-end + reporte Quarto HTML+PDF; DoD release `v0.1.0` con dataset de ejemplo, reporte, PyPI/GitHub, README/tutorial.
- **_CONTRATOS-TRANSVERSALES.md** CT-1 (`requires`/`provides`), CT-2 (`metric_sections`, estructuras aditivas), CT-4 (core liviano/ensamblado fuera de core).
- **SDD-01** §4/§7/§9/§12: `Step`, `ArtifactKey`, `LineageBundle`, `config_hash`, core no importa Quarto.
- **SDD-03**: model card, SR 11-7, audit trail y `metric_sections`.
- **SDD-05** §5.1/§5.5: sección `report` reservada en `NikodymConfig`; `report ∈ INFRA_SECTIONS`.
- **SDD-06/07/08/09/10/11/27**: cards/results F1 que `report` consume; `report` no recalcula sus métricas.
- **SDD-25** §5/§8/§12: extra `report` reservado; Quarto es binario externo y requiere contrato de detección/mensaje en SDD-26.
- **CMF / SR 11-7:** uso metodológico-documental: el reporte presenta evidencia, trazabilidad y lineage; no introduce parámetros regulatorios nuevos.

## Decisiones para revisión de Cami

- **D-REP-1 - Proveedor/modelo IA, costos y privacidad.** Recomendación: proveedor opt-in vía API key del usuario; payload a API = solo narrativa derivada, cards sanitizadas y métricas agregadas; **nunca datos crudos del cliente, PII, IDs ni tablas row-level**. Cami decide proveedor/modelo concreto y política de costo/privacidad.
- **D-REP-2 - Ruta básica: Quarto vs HTML puro-Python.** Recomendación: HTML básico Jinja2 como ruta obligatoria y determinística; Quarto como capa adicional para PDF/Word. Trade-off: Quarto da outputs más ricos, pero agrega binario externo y fragilidad CI/local.
- **D-REP-3 - Formatos obligatorios para `v0.1.0`.** Recomendación mínima robusta: HTML obligatorio; PDF opcional si Quarto está instalado; Word diferido u opcional. Roadmap menciona HTML+PDF, por lo que Cami decide si PDF es DoD duro o artefacto opcional.
- **D-REP-4 - Export/publicación externa.** Recomendación: export local por defecto. Publicar/subir reporte a destino externo para release público o cliente es evento sensible R0: requiere config explícito, confirmación del usuario, audit event y revisión de privacidad.
- **D-REP-5 - Packaging de `jinja2`.** Recomendación: incluir `jinja2` en la instalación base de v0.1.0 si `report` es parte del MVP; mantener matplotlib/plotly/SDK IA como extras perezosos. Alternativa: `[report]` obligatorio, pero debilita "reporte básico por default".
- **D-REP-6 - Política de secciones ausentes.** Recomendación: `missing_policy="error"` para release F1 completo; `warn` solo para API exploratoria. Evita reportes públicos que parezcan completos sin todos los dominios.
