# SDD-26 — `report` (informe auditable multipropósito)

| Campo | Valor |
|---|---|
| **SDD** | 26 |
| **Módulo** | `nikodym.report` |
| **Dominio** | Reporte y documentación automática |
| **Fase** | F1, con extensiones aditivas F3/F4 y validación |
| **Tanda de producción** | T2 (Scoring); ampliado hasta 1.3.0 |
| **Estado** | ✅ Implementado; fachada pública estable SemVer 1.x; estructura documental interna experimental |
| **Depende de** | SDD-01 (`core`), SDD-03 (`audit`/`governance`), SDD-05 (config), cards/results de los dominios ejecutados |
| **Lo consumen** | API pública, UI, validadores, auditoría y entregables institucionales |
| **Actualización** | 2026-07-18 — consolidado contra el código vigente |

---

## 1. Propósito y fronteras

`report` transforma los artefactos estructurados de una corrida en un **informe auditable,
determinístico y standalone**. El HTML es la representación canónica; PDF, fuente editable,
Word y adjuntos tabulares se derivan del mismo snapshot.

Responsabilidades:

- tomar un snapshot defensivo de cards, resultados, tablas, figuras, config efectivo y lineage;
- ordenar la evidencia como documento, no como volcado del pipeline;
- generar prosa técnica determinística desde reglas y plantillas;
- renderizar HTML standalone y los formatos solicitados que tienen motor real;
- registrar secciones ausentes, truncamientos visuales, narrativa y exports;
- publicar `input_bundle`, `manifest` y `result` bajo el dominio `report`.

Fronteras duras:

- no calcula ni corrige métricas de riesgo;
- no muta artefactos aguas arriba;
- no inventa datos de entidad, cartera, autor, versión ni juicio de validación;
- no usa IA para calcular, seleccionar o cambiar números;
- no envía datos crudos, PII ni config efectivo a un proveedor IA;
- no publica externamente: todos los exports son locales;
- no invoca ni requiere Quarto. El archivo `.qmd` es una fuente editable de texto que el usuario
  puede compilar fuera de Nikodym.

## 2. Arquitectura implementada

```text
ArtifactStore + LineageBundle + NikodymConfig
                  │
                  ▼
            ReportBuilder
      snapshot defensivo y documento
                  │
                  ├──► RuleBasedNarrator ───────────────┐
                  └──► AINarrator opt-in ──fallback─────┤
                                                        ▼
                                              documento común
                                                        │
                ┌──────────────┬───────────────┬─────────┴─────────┐
                ▼              ▼               ▼                   ▼
          HTML/Jinja2     PDF/WeasyPrint   QMD + DOCX       CSV + XLSX
                │              │               │                   │
                └──────────────┴───────────────┴─────────┬─────────┘
                                                        ▼
                                  ReportManifest + ReportResult
```

El paquete conserva import liviano:

- `import nikodym.core` no importa `report`;
- `import nikodym.report` registra config y step sin cargar Jinja2, WeasyPrint, matplotlib,
  python-docx ni un SDK IA;
- DTOs y componentes pesados se reexportan perezosamente.

## 3. API pública

La fachada `nikodym.report` exporta:

- config: `ReportConfig`, `DocumentStructureConfig`, `SectionPolicyConfig`,
  `HtmlRenderConfig`, `PdfRenderConfig`, `AiNarrationConfig`;
- orquestación: `ReportStep`, `ReportBuilder`;
- render: `HtmlReportRenderer`, `PdfReportRenderer`, `render_pdf`;
- DTOs: `ReportInputBundle`, `ReportSection`, `ReportManifest`, `ReportResult`,
  `PlaceholderBlock`, `AiNarrationBlock`;
- narrativa: `AIClient`, `AIRequest`, `AIResponse`, `AINarrator`, `RuleBasedNarrator`;
- errores: `ReportError`, `ReportInputError`, `ReportRenderError`, `ReportExportError`,
  `ReportDependencyError`, `ReportAIError`.

`ReportStep` está registrado como:

```python
@register("standard", domain="report")
class ReportStep(AuditableMixin):
    name = "report"
    provides = (
        ("report", "input_bundle"),
        ("report", "manifest"),
        ("report", "result"),
    )
```

Sus prerequisitos se derivan de `sections.required_sections` usando el mapeo canónico:

| Dominio | Card requerida |
|---|---|
| `eda` | `eda_card` |
| `binning` | `binning_card` |
| `selection` | `selection_card` |
| `model` | `model_card` |
| `scorecard` | `card` |
| `calibration` | `card` |
| `performance` | `card` |
| `stability` | `card` |

Las cards de `data`, provisiones, IFRS 9, supervivencia y validación se recolectan cuando existen,
pero no se vuelven prerequisitos implícitos de una corrida F1.

## 4. Configuración

`ReportConfig` hereda de `NikodymBaseConfig`: es frozen, rechaza campos extra y tiene schema local
`1.0.0`. `report` es infraestructura y queda excluido del `config_hash` computacional.

Campos principales:

```python
class ReportConfig(NikodymBaseConfig):
    schema_version: str = "1.0.0"
    type: Literal["standard"] = "standard"
    output_dir: str = "reports"
    basename: str = "scorecard_report"
    language: Literal["es"] = "es"
    formats: tuple[Literal["html", "pdf", "md", "docx", "csv", "xlsx"], ...] = ("html",)
    document: DocumentStructureConfig
    html: HtmlRenderConfig
    pdf: PdfRenderConfig
    docx: DocxRenderConfig
    ai: AiNarrationConfig
    sections: SectionPolicyConfig
```

Reglas:

- todo formato aceptado por el schema tiene un motor implementado;
- el HTML canónico se construye siempre; `formats` gobierna los derivados y adjuntos;
- `output_dir=""` permite resultado en memoria sin inventar rutas;
- `missing_policy` es `error`, `warn` o `skip`, nunca relleno silencioso;
- `max_table_rows` limita sólo la visualización, no los adjuntos completos;
- `document.placeholders` controla bloques `POR COMPLETAR` para juicio humano;
- `send_raw_data` tiene tipo literal `False`.

Dependencias por formato:

| Formato | Motor | Dependencia |
|---|---|---|
| HTML | Jinja2 + CSS/SVG embebido | Jinja2 en base |
| PDF | mismo HTML → WeasyPrint | extra `pdf` |
| `md` | renderer de texto; escribe `.qmd` | sin extra |
| DOCX | python-docx | extra `docx` |
| CSV | pandas | base |
| XLSX | writer Excel | extra `excel` |

La ausencia de una dependencia opcional degrada con aviso o falla según la política explícita del
formato. Nunca se informa éxito con un formato solicitado y omitido silenciosamente.

## 5. Modelo documental

`report/document.py` es la fuente única de estructura, orden y títulos. Su evolución es aditiva y
experimental; no altera la estabilidad de la fachada pública.

El documento puede contener:

1. portada e índice;
2. resumen ejecutivo determinístico;
3. contexto de población, particiones y exclusiones;
4. metodología derivada del config efectivo;
5. resultados del scorecard;
6. validación formal, si existe un `ValidationResult` atómico;
7. provisiones estándar CMF, método interno y regla de constitución, si corrieron;
8. IFRS 9/ECL como capítulo separado, si corrió;
9. conclusiones y limitaciones;
10. anexos de lineage, tablas agregadas y parámetros efectivos.

Las tablas por observación no se incrustan truncadas en el documento. Cuando se piden `csv` o
`xlsx`, se entregan completas como adjuntos y el informe las referencia. Las tablas agregadas sí
permanecen en el cuerpo o anexos porque constituyen evidencia revisable.

El capítulo de provisiones mantiene la distinción normativa:

- Chile B-1: máximo entre método estándar CMF y método interno por institución, salvo uso del
  interno evaluado y no objetado;
- IFRS 9: ECL contable independiente, nunca presentada como operando del piso prudencial chileno.

## 6. Contratos de datos e invariantes

Los DTOs son Pydantic frozen con `extra="forbid"`. `ReportInputBundle` es un snapshot atómico:

- copia mappings, secuencias y DataFrames al validar y al exponerlos;
- conserva `metric_sections` sin aplanar su estructura extensible;
- guarda `pipeline_params` por dominio para documentar lo realmente ejecutado;
- usa el `ValidationResult` atómico para evitar mezclar card y tablas de instantes distintos;
- conserva lineage y hashes de la corrida;
- ordena secciones, tablas, IDs y serialización de forma determinística.

Invariantes de salida:

- el mismo bundle y config producen el mismo HTML normalizado y SHA-256;
- ningún renderer recalcula métricas;
- una sección ausente sigue la política declarada y queda trazada;
- `ReportManifest.path` es un basename portable;
- `ReportResult.*_path` contiene la ruta operativa del archivo escrito;
- el manifiesto HTML contiene template, formato, hash, secciones, flags IA y lineage;
- los formatos derivados nacen del mismo documento, sin bifurcar la evidencia.

## 7. Narrativa determinística e IA

`RuleBasedNarrator` es la ruta base, completa y sin red. Construye texto técnico sólo desde
artefactos estructurados y prosa versionada.

`AINarrator` es opt-in:

- el adaptador implementado usa Anthropic, pero el cliente es inyectable;
- el payload contiene únicamente métricas agregadas y texto sanitizado;
- excluye datos crudos, PII evidente, secretos, rutas sensibles y `effective_config`;
- cada bloque registra proveedor, modelo, condición `generated`, hashes de prompt/input y warning;
- key ausente, error, timeout, respuesta vacía o proveedor desactivado producen fallback explícito
  a la narrativa determinística;
- el texto IA queda etiquetado cuando `label_ai_text=True`;
- la IA nunca modifica números ni rellena un veredicto humano.

## 8. Algoritmo de ejecución

```text
1. Validar cards CT-1 y preflight del output_dir.
2. Recolectar snapshot defensivo de lineage/cards/results/tables/figures/config.
3. Construir capítulos y secciones en orden canónico.
4. Generar narrativa determinística o IA con fallback.
5. Renderizar y, si corresponde, escribir HTML.
6. Derivar PDF, QMD, DOCX, CSV y XLSX solicitados.
7. Construir manifest y ReportResult.
8. Registrar decisiones auditables.
9. Publicar input_bundle, manifest y result con copias defensivas.
```

`execute(study, rng)` descarta `rng`: el paso es determinístico.

## 9. Errores y auditoría

Errores tipados:

- `ReportInputError`: bundle/card/config efectivo incoherente;
- `ReportRenderError`: fallo de construcción o render;
- `ReportExportError`: ruta no escribible o escritura fallida;
- `ReportDependencyError`: dependencia opcional exigida y ausente;
- `ReportAIError`: contrato del cliente/narrador IA inválido.

El preflight del directorio ocurre antes de cualquier llamada IA. La auditoría registra:

- secciones incluidas y ausentes;
- tablas con truncamiento visual;
- uso o degradación de IA;
- ruta y hash del HTML;
- cada export documental;
- adjuntos tabulares producidos.

## 10. Seguridad y privacidad

- export local por defecto; sin subida automática;
- paths de salida controlados por config y verificados antes de escribir;
- HTML con assets embebidos para evitar dependencias remotas;
- sin datos por observación dentro del documento;
- payload IA sanitizado y sin datos crudos;
- sin API keys en config, manifest, logs o reportes;
- sin pickle ni ejecución de plantillas del usuario;
- `.qmd` es texto generado, no código ejecutado por Nikodym.

## 11. Verificación y Definition of Done

La batería dedicada cubre config, DTOs, builder, estructura documental, prosa, charts, HTML, PDF,
Markdown/QMD, DOCX, CSV/XLSX, IA y step.

Criterios permanentes:

- ruff y mypy `--strict` verdes;
- imports livianos verificados en subprocess;
- round-trip del config y exclusión de `report` del `config_hash`;
- determinismo entre procesos y valores de `PYTHONHASHSEED`;
- no mutación de inputs y copias defensivas;
- goldens de HTML/manifest y formatos con firmas reales;
- políticas de sección faltante y dependencia opcional;
- sanitización y fallback IA sin key real;
- capítulos condicionales F1/F3/F4/IFRS 9/validación;
- pipeline end-to-end que publica exactamente los tres artefactos estables.

## 12. Decisiones fijadas

- **D-REP-1:** HTML Jinja2 standalone es la representación canónica.
- **D-REP-2:** WeasyPrint deriva PDF desde el mismo HTML.
- **D-REP-3:** `.qmd` es fuente editable; Quarto no es dependencia ni renderer.
- **D-REP-4:** Word usa python-docx; datos completos usan CSV/XLSX.
- **D-REP-5:** la prosa base es determinística; IA es opt-in, inyectable y no computacional.
- **D-REP-6:** cards/results crecen de forma aditiva; la estructura documental interna puede
  evolucionar mientras la fachada pública SemVer 1.x permanece estable.
- **D-REP-7:** `report` es infraestructura y no cambia la identidad computacional de la corrida.
- **D-REP-8:** veredictos y campos institucionales no declarados quedan `POR COMPLETAR`.

## 13. Fuentes internas vigentes

- `src/nikodym/report/`: implementación y contratos ejecutables.
- `tests/unit/test_report_*.py`: especificación verificable por comportamiento.
- `docs/ESPECIFICACIONES.md`: arquitectura y principios del producto.
- `docs/ROADMAP.md`: estado y evolución; no redefine contratos del módulo.
- SDD-01/03/05/22/25/28: orquestación, auditoría, config, validación, packaging y provisiones.

No quedan decisiones de implementación abiertas en este SDD. Nuevos formatos o cambios de
contrato requieren una extensión aditiva y tests antes de publicarse en el schema.
