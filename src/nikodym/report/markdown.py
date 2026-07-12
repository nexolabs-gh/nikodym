"""Export ``.qmd`` (Quarto/Markdown): la **fuente editable** del informe (mejora 1.1, tanda 2).

El informe que produce el motor no es un PDF terminal. Un analista de Validación necesita bajarse la
fuente, escribir su contexto y sus conclusiones encima y compilar **su** documento. Eso es lo que
emite :class:`MarkdownReportRenderer`: un ``.qmd`` con front-matter YAML, los mismos capítulos que
el HTML y los bloques POR COMPLETAR convertidos en *callouts* de Quarto —visibles y accionables, no
un comentario que se pierde—.

Es un **espejo** de :class:`~nikodym.report.renderer.HtmlReportRenderer`: misma firma
(``render``/``write``/``build_manifest``), mismo bundle de entrada, mismo determinismo, y sobre todo
la misma estructura, porque ambos consumen
:func:`~nikodym.report.renderer.build_document_view`. La estructura del documento se declara **una
vez** (en :mod:`nikodym.report.document`) y aquí sólo se decide cómo se escribe cada bloque en
Markdown.

**Quarto no es una dependencia y no se invoca por ``subprocess``**: se retiró a propósito del
proyecto (el PDF lo hace WeasyPrint). Este módulo sólo **emite texto** que Quarto puede compilar si
el usuario lo tiene instalado; sin Quarto, el ``.qmd`` sigue siendo Markdown válido, legible y
editable a mano.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import yaml

from nikodym.report._manifest import REPORT_TEMPLATE_VERSION, REPORT_TITLE, html_report_id
from nikodym.report.config import ReportConfig
from nikodym.report.exceptions import ReportExportError
from nikodym.report.renderer import build_document_view
from nikodym.report.results import AiNarrationBlock, ReportInputBundle, ReportManifest

__all__ = ["FIGURES_SUFFIX", "MarkdownReportRenderer"]

# Directorio hermano del ``.qmd`` donde se materializan las figuras. El ``.qmd`` las referencia con
# ruta RELATIVA, de modo que `quarto render` funcione tal cual desde el directorio del archivo.
FIGURES_SUFFIX: Final = "_figuras"
_MD_EXTENSION: Final = ".qmd"


class MarkdownReportRenderer:
    """Render del informe a ``.qmd`` (Quarto/Markdown) editable y determinista."""

    def __init__(self, config: ReportConfig | None = None) -> None:
        """Construye el renderer desde ``ReportConfig`` (o el default, para uso standalone)."""
        self.config = config if config is not None else ReportConfig()
        self._last_bundle: ReportInputBundle | None = None
        self._last_ai_blocks: tuple[AiNarrationBlock, ...] = ()
        self._last_figures: dict[str, str] = {}

    @classmethod
    def from_config(cls, cfg: ReportConfig) -> MarkdownReportRenderer:
        """Construye ``MarkdownReportRenderer`` desde ``NikodymConfig.report``."""
        return cls(cfg)

    def render(
        self,
        bundle: ReportInputBundle,
        *,
        ai_blocks: tuple[AiNarrationBlock, ...] = (),
    ) -> str:
        """Renderiza el documento a texto ``.qmd`` determinista (no escribe nada en disco)."""
        self._last_bundle = bundle
        self._last_ai_blocks = ai_blocks
        document = build_document_view(bundle, config=self.config, ai_blocks=ai_blocks)

        # Las figuras se acumulan aquí y ``write`` las materializa junto al ``.qmd``: el texto sólo
        # guarda la ruta relativa, que es determinista y no depende del ``output_dir``.
        self._last_figures = {
            chart["html_id"]: chart["svg"]
            for section in document["sections"]
            for chart in section["charts"]
        }

        blocks: list[str] = [_front_matter(document, self.config), _cover(document)]
        blocks.append(_executive(document["executive"]))
        for section in document["sections"]:
            block = _section(section, self.config)
            if block:
                blocks.append(block)
        return _join(blocks)

    def build_manifest(self, markdown: str) -> ReportManifest:
        """Construye el manifiesto del ``.qmd`` sin escribir archivos (espejo del HTML)."""
        bundle = self._last_bundle
        if bundle is None:
            raise ReportExportError(
                "No se puede construir el manifest report.qmd porque no hay bundle renderizado; "
                "acción='llame MarkdownReportRenderer.render antes de build_manifest'."
            )
        ai_used = any(block.generated for block in self._last_ai_blocks)
        return ReportManifest(
            report_id=html_report_id(bundle, self.config),
            title=REPORT_TITLE,
            created_from_lineage_at=bundle.lineage.created_at.isoformat(),
            template_id=self.config.html.template_id,
            template_version=REPORT_TEMPLATE_VERSION,
            output_format="md",
            path="",
            sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            deterministic=self.config.html.deterministic_ids and not ai_used,
            ai_enabled=self.config.ai.enabled or bool(self._last_ai_blocks),
            ai_used=ai_used,
            sections=bundle.sections,
        )

    def write(self, markdown: str, *, output_dir: str) -> ReportManifest:
        """Escribe el ``.qmd`` y sus figuras en disco; devuelve el manifiesto con la ruta real.

        Las figuras se escriben como SVG en ``{basename}_figuras/`` **junto** al ``.qmd``, que las
        referencia con ruta relativa: el par (archivo + carpeta) es autocontenido y ``quarto
        render`` funciona sin tocar nada. Escritura atómica (tmp + ``replace``), como el HTML.
        """
        if self._last_bundle is None:
            raise ReportExportError(
                "No se puede exportar report.qmd porque no hay bundle renderizado; "
                "acción='llame MarkdownReportRenderer.render antes de write'."
            )
        directory = Path(output_dir)
        filename = f"{self.config.basename}{_MD_EXTENSION}"
        _write_bytes(directory / filename, markdown.encode("utf-8"), formato="md")
        if self._last_figures:
            figures_dir = directory / f"{self.config.basename}{FIGURES_SUFFIX}"
            figures_dir.mkdir(parents=True, exist_ok=True)
            for html_id, svg in self._last_figures.items():
                _write_bytes(figures_dir / f"{html_id}.svg", svg.encode("utf-8"), formato="md")

        manifest = self.build_manifest(markdown)
        path = filename if directory.is_absolute() else (directory / filename).as_posix()
        return manifest.model_copy(update={"path": path})


def _write_bytes(path: Path, payload: bytes, *, formato: str) -> None:
    """Escritura atómica (tmp + ``replace``) con el error accionable de la capa ``report``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        temp_path.write_bytes(payload)
        temp_path.replace(path)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise ReportExportError(
            f"No se pudo escribir el reporte: dominio='report', formato='{formato}', "
            f"clave='{path.name}', output_dir='{path.parent}', "
            "acción='verifique permisos y espacio disponible'."
        ) from exc


# ─────────────────────────── bloques del documento ───────────────────────────


def _front_matter(document: Mapping[str, Any], config: ReportConfig) -> str:
    """Front-matter YAML: título, autor, fecha y los metadatos de proyecto de la portada.

    Se serializa con PyYAML (``safe_dump``), no concatenando texto: un valor con comillas, dos
    puntos o un acento rompería un YAML escrito a mano, y este archivo lo va a editar una persona.
    ``toc: true`` deja el índice en manos de Quarto —que lo deriva de los encabezados— en vez de
    fijar una lista que quedaría desincronizada con el primer capítulo que el analista añada.

    El bloque ``nikodym:`` conserva la identidad de la corrida (los cuatro hashes) dentro de la
    fuente editable: si alguien reescribe el informe entero, la trazabilidad sigue en el archivo.
    """
    lineage = document["lineage"]
    meta: dict[str, Any] = {
        "title": document["document_title"],
        "subtitle": config.document.model_name or "Modelo por declarar",
        "author": config.document.author or "Por completar",
        "date": document["emitted_date"],
        "lang": config.language,
        "toc": True,
        "number-sections": False,
        "format": {"html": {"embed-resources": True}, "pdf": "default"},
        "nikodym": {
            "modelo": config.document.model_name,
            "entidad": config.document.entity,
            "cartera": config.document.portfolio,
            "version_informe": config.document.version,
            "config_hash": lineage["config_hash"],
            "data_hash": lineage["data_hash"],
            "git_sha": lineage["git_sha"],
            "root_seed": lineage["root_seed"],
            "template": f"{document['template_id']}@{document['template_version']}",
        },
    }
    body = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{body.strip()}\n---"


def _cover(document: Mapping[str, Any]) -> str:
    """Portada: los metadatos declarados y la trazabilidad de la corrida (nunca inventados)."""
    lines = [
        "::: {.callout-note appearance='simple'}",
        "**USO INTERNO — CONFIDENCIAL**",
        ":::",
        "",
        _pipe_table(
            ("Campo", "Valor"),
            [
                (field["label"], field["value"] if field["filled"] else "_(por completar)_")
                for field in document["cover"]
            ]
            + [("Fecha de emisión", document["emitted_date"])],
        ),
        "",
        "Trazabilidad de la corrida (lineage):",
        "",
        "```",
        f"config_hash={document['lineage']['config_hash']}",
        f"data_hash={document['lineage']['data_hash']}",
        f"git_sha={document['lineage']['git_sha']}",
        f"root_seed={document['lineage']['root_seed']}",
        "```",
        "",
        _pipe_table(
            ("Rol", "Nombre", "Fecha"),
            [("Desarrollo", "", ""), ("Validación independiente", "", ""), ("Aprobación", "", "")],
        ),
    ]
    return "\n".join(lines)


def _executive(executive: Mapping[str, Any]) -> str:
    """Resumen ejecutivo: métricas clave y el veredicto, que firma un humano."""
    lines = ["## Resumen ejecutivo", "", _verdict(), ""]
    metrics = executive["metrics"]
    if metrics:
        lines.append(
            _pipe_table(
                ("Métrica", "Alcance", "Valor", "Estado"),
                [
                    (metric["label"], metric["scope"], metric["value"], metric["band"])
                    for metric in metrics
                ],
            )
        )
    else:
        lines.append("Las métricas clave no están disponibles en esta corrida.")
    for note in executive["notes"]:
        lines.extend(["", f"_{note}_"])
    return "\n".join(lines)


def _verdict() -> str:
    """Veredicto de validación: un *callout* POR COMPLETAR, porque lo firma un humano."""
    return _callout(
        "important",
        "POR COMPLETAR — Veredicto de validación",
        (
            "Marque el veredicto: **Aprobado** · **Aprobado con observaciones** · **Rechazado**.",
            "Campo estructural: lo marca y firma el validador independiente; no es un resultado "
            "calculado por el motor.",
        ),
    )


def _section(section: Mapping[str, Any], config: ReportConfig) -> str:
    """Escribe una sección del documento; el índice lo genera Quarto desde los encabezados."""
    if section["kind"] == "toc":
        return ""
    lines = [_heading(section), ""]
    if section["status"] == "missing":
        lines.extend(
            [
                "::: {.callout-warning}",
                "Sección requerida ausente; el reporte parcial no inventa números ni oculta la "
                "ausencia.",
                ":::",
                "",
            ]
        )
    if section["kind"] == "appendix" and section["level"] == 2:
        lines.extend([f"Artefacto de origen: `{section['source']}`", ""])
    for paragraph in section["body"]:
        lines.extend([paragraph, ""])
    if section["placeholder"]:
        lines.extend([_placeholder(section["placeholder"]), ""])
    for chart in section["charts"]:
        lines.extend([_figure(chart, config), ""])
    for table in section["tables"]:
        lines.extend([_table(table), ""])
    if section["data_exports"]:
        lines.extend([_data_exports(section["data_exports"]), ""])
    lines.extend(_payload_blocks(section))
    if section["narration"]:
        lines.extend([_narration(section["narration"]), ""])
    return "\n".join(lines).rstrip()


def _heading(section: Mapping[str, Any]) -> str:
    """Encabezado Markdown con la numeración explícita del documento (H2 capítulo, H3 subsección).

    La numeración se escribe en el texto (``number-sections: false``) para que el ``.qmd`` sea
    idéntico al HTML y al Word: los tres informes numeran igual, y el que se lea en crudo también.
    """
    level = "##" if section["level"] == 1 else "###"
    number = str(section["number"])
    if number and section["kind"] == "appendix" and section["level"] == 1:
        number = f"Anexo {number} —"
    prefix = f"{number} " if number else ""
    return f"{level} {prefix}{section['title']}"


def _placeholder(placeholder: Mapping[str, Any]) -> str:
    """Bloque POR COMPLETAR como *callout* de Quarto: visible, con la guía de qué escribir.

    La guía va **dentro** del callout, no como comentario HTML: el analista tiene que ver qué se
    espera de él justo donde tiene que escribirlo, y el callout sobrevive al render a HTML/PDF/Word.
    El título va en el atributo ``title`` y no como encabezado dentro del callout: un ``##`` ahí
    dentro entraría en el índice de Quarto y descuadraría la numeración de los capítulos.
    """
    title = f"POR COMPLETAR — {placeholder['title']}"
    return _callout("important", title, placeholder["guidance"])


def _callout(kind: str, title: str, paragraphs: Sequence[str]) -> str:
    """Compone un *callout* de Quarto (``::: {.callout-x}``) con su título y su cuerpo."""
    lines = [f'::: {{.callout-{kind} title="{_escape_attr(title)}"}}']
    for index, paragraph in enumerate(paragraphs):
        if index:
            lines.append("")
        lines.append(paragraph)
    lines.append(":::")
    return "\n".join(lines)


def _figure(chart: Mapping[str, Any], config: ReportConfig) -> str:
    """Figura por ruta relativa al SVG que ``write`` materializa junto al ``.qmd``."""
    path = f"{config.basename}{FIGURES_SUFFIX}/{chart['html_id']}.svg"
    return f"![{_escape_cell(chart['title'])}]({path})"


def _table(table: Mapping[str, Any]) -> str:
    """Tabla en *pipe table* de Markdown, con su título legible y el aviso de truncamiento."""
    lines = [f"**{table['title']}**", ""]
    lines.append(_pipe_table(tuple(table["columns"]), [tuple(row) for row in table["rows"]]))
    if table["truncated"]:
        lines.extend(["", f"_… (mostrando {table['shown_rows']} de {table['total_rows']} filas)_"])
    return "\n".join(lines)


def _data_exports(exports: Mapping[str, Any]) -> str:
    """Declara dónde quedó el detalle por observación (los adjuntos de datos)."""
    lines = ["#### Detalle por observación", ""]
    if exports["requested"]:
        lines.extend(
            [
                "Las tablas con una fila por operación no se reproducen en el informe: se entregan "
                "**completas** como archivos adjuntos a este documento.",
                "",
                _pipe_table(
                    ("Tabla", "Filas", "Archivo adjunto"),
                    [
                        (
                            item["title"],
                            item["rows"],
                            f"`{item['filename']}`"
                            + (f" — hoja `{item['sheet']}`" if item["sheet"] else ""),
                        )
                        for item in exports["attachments"]
                    ],
                ),
            ]
        )
        return "\n".join(lines)
    lines.append(
        "Esta corrida produjo tablas con una fila por operación que no se reproducen en el informe "
        "(son datos, no evidencia de validación) y que **no se exportaron**: añada `csv` o `xlsx` "
        "a `report.formats` para obtenerlas completas."
    )
    lines.append("")
    lines.extend(f"- {item['title']} — {item['rows']} filas" for item in exports["pending"])
    return "\n".join(lines)


def _payload_blocks(section: Mapping[str, Any]) -> list[str]:
    """Payload y métricas del anexo: escalares como lista, JSON anidado como bloque de código."""
    lines: list[str] = []
    for heading, items in (
        ("Parámetros y payload", section["payload_items"]),
        ("Métricas estructuradas", section["metric_items"]),
    ):
        if not items:
            continue
        lines.extend([f"#### {heading}", ""])
        for item in items:
            value = str(item["value"])
            if item["multiline"]:
                lines.extend([f"`{item['key']}`:", "", "```json", value, "```", ""])
            else:
                lines.append(f"- `{item['key']}`: {_escape_cell(value)}")
        lines.append("")
    return lines


def _narration(narration: Mapping[str, Any]) -> str:
    """Narrativa IA opcional, siempre etiquetada como tal."""
    body = [text for text in (narration["text"], narration["warning"]) if text]
    if narration["label"]:
        return _callout("note", narration["label"], body)
    return "\n\n".join(body)


# ─────────────────────────── primitivas Markdown ───────────────────────────


def _pipe_table(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Compone una *pipe table* de Markdown válida, con las celdas escapadas."""
    header = " | ".join(_escape_cell(column) for column in columns)
    separator = " | ".join("---" for _ in columns)
    lines = [f"| {header} |", f"| {separator} |"]
    lines.extend(f"| {' | '.join(_escape_cell(cell) for cell in row)} |" for row in rows)
    return "\n".join(lines)


def _escape_cell(value: object) -> str:
    """Neutraliza lo que rompería una celda: el pipe (separador) y los saltos de línea."""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _escape_attr(value: str) -> str:
    """Neutraliza la comilla doble que delimita el atributo ``title`` de un *callout*."""
    return value.replace('"', "'")


def _join(blocks: Sequence[str]) -> str:
    """Une los bloques con una línea en blanco y garantiza el salto final (determinista)."""
    text = "\n\n".join(block.strip("\n") for block in blocks if block.strip())
    return f"{text}\n"
