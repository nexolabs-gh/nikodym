"""Renderizadores determinísticos de reportes HTML y PDF opcional (SDD-26 §4/§7).

``HtmlReportRenderer`` transforma un :class:`~nikodym.report.results.ReportInputBundle` en HTML
standalone usando Jinja2 con import perezoso. La salida básica es reproducible byte a byte:
no usa reloj, UUIDs, rutas locales absolutas ni orden dependiente de ``hash()``.

``PdfReportRenderer`` mantiene el PDF como ruta derivada y no crítica: renderiza y escribe el HTML
básico como artefacto primario y, si está habilitado, genera un PDF con WeasyPrint (import perezoso)
que escribe como efecto secundario en disco. Degrada con gracia a HTML si WeasyPrint no está
disponible; el manifest devuelto describe siempre el artefacto HTML determinístico.

:func:`build_document_view` es la **proyección canónica del documento** (portada, resumen, índice y
secciones ya resueltas) y la fuente única que consumen los tres renderers: el HTML de aquí, el
``.qmd`` de :mod:`nikodym.report.markdown` y el ``.docx`` de :mod:`nikodym.report.docx`. Un capítulo
nuevo, un título distinto o una tabla que cambia de sitio se escriben **una vez**; los tres formatos
lo heredan. Sin eso, tres renderers son tres documentos que divergen en la primera modificación.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import warnings
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, TypeAlias, cast

from pydantic import BaseModel

from nikodym.report._manifest import (
    DOCUMENT_TITLE,
    IFRS9_DOCUMENT_TITLE,
    REPORT_TEMPLATE_VERSION,
    REPORT_TITLE,
    html_report_id,
)
from nikodym.report.config import (
    AiNarrationConfig,
    HtmlRenderConfig,
    PdfRenderConfig,
    ReportConfig,
    SectionPolicyConfig,
)
from nikodym.report.document import (
    APPENDIX_TABLES_ID,
    KEY_TABLES,
    PER_OBSERVATION_TABLES,
    ordered_sections,
    table_title,
)
from nikodym.report.exceptions import (
    ReportDependencyError,
    ReportExportError,
    ReportRenderError,
)
from nikodym.report.exports import data_export_refs
from nikodym.report.results import (
    AiNarrationBlock,
    ReportInputBundle,
    ReportManifest,
    ReportSection,
)

if TYPE_CHECKING:
    # Sólo el alias de tipo: importar ``charts`` en runtime crearía un borde de import hacia el
    # módulo de matplotlib y rompería el import liviano del paquete que este renderer preserva.
    from nikodym.report.charts import ChartFormat

__all__ = ["HtmlReportRenderer", "PdfReportRenderer", "build_document_view"]

_LOGGER: Final = logging.getLogger(__name__)

JSONValue: TypeAlias = dict[str, Any] | list[Any] | str | int | float | bool | None
TableCell: TypeAlias = str

# Los bytes internos de un ``<svg>`` de matplotlib dependen de freetype y no son idénticos entre
# sistemas operativos; el digest del manifest/golden los reemplaza por un placeholder para ser
# reproducible cross-OS (el HTML en disco conserva los SVG). Non-greedy + DOTALL: cada gráfico se
# recorta por separado (matplotlib no anida ``<svg>``).
_SVG_STRIP_PATTERN: Final = re.compile(r"<svg\b[^>]*>.*?</svg>", re.DOTALL)
_STRIPPED_SVG: Final = '<svg data-chart="stripped"></svg>'

_HTML_TEMPLATE_ID: Final = "scorecard_basic_v1"
_TEMPLATE_PACKAGE: Final = "nikodym.report.templates"
_TEMPLATE_NAME: Final = "scorecard_report.html.j2"
_CSS_FILES: Final[dict[str, str]] = {
    "nikodym": "scorecard_report.css",
    "plain": "scorecard_report_plain.css",
}


class HtmlReportRenderer:
    """Render HTML standalone determinístico con Jinja2."""

    def __init__(
        self,
        config: ReportConfig | HtmlRenderConfig | None = None,
        *,
        basename: str | None = None,
        sections: SectionPolicyConfig | None = None,
        ai: AiNarrationConfig | None = None,
    ) -> None:
        """Construye el renderer desde ``ReportConfig`` o ``HtmlRenderConfig``."""
        self.config = _coerce_report_config(
            config,
            basename=basename,
            sections=sections,
            ai=ai,
        )
        self._last_bundle: ReportInputBundle | None = None
        self._last_ai_blocks: tuple[AiNarrationBlock, ...] = ()

    @classmethod
    def from_config(cls, cfg: ReportConfig) -> HtmlReportRenderer:
        """Construye ``HtmlReportRenderer`` desde ``NikodymConfig.report``."""
        return cls(cfg)

    def render(
        self,
        bundle: ReportInputBundle,
        *,
        ai_blocks: tuple[AiNarrationBlock, ...] = (),
    ) -> str:
        """Renderiza HTML standalone byte-determinístico desde el bundle lógico."""
        try:
            from jinja2 import Environment, PackageLoader, StrictUndefined
        except ModuleNotFoundError as exc:
            raise ReportDependencyError(
                "No se pudo renderizar report.html: falta Jinja2. "
                "Instale nikodym con dependencias base actualizadas y vuelva a ejecutar."
            ) from exc

        self._last_bundle = bundle
        self._last_ai_blocks = ai_blocks
        environment = Environment(
            loader=PackageLoader("nikodym.report", "templates"),
            autoescape=True,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        try:
            document = build_document_view(bundle, config=self.config, ai_blocks=ai_blocks)
            rendered = _load_template(environment).render(
                css=_css_for_theme(self.config.html.theme),
                theme=self.config.html.theme,
                **document,
            )
        except ReportRenderError:
            raise
        except Exception as exc:
            raise ReportRenderError(
                "No se pudo renderizar report.html: dominio='report', plantilla="
                f"'{self.config.html.template_id}', acción='revise el bundle y la plantilla'."
            ) from exc
        return _normalize_newlines(rendered)

    def build_manifest(self, html: str) -> ReportManifest:
        """Construye el manifiesto HTML canónico sin escribir archivos."""
        bundle = self._last_bundle
        if bundle is None:
            raise ReportExportError(
                "No se puede construir el manifest report.html porque no hay bundle "
                "renderizado; acción='llame HtmlReportRenderer.render antes de build_manifest'."
            )

        digest = _digest_html(html)
        ai_used = any(block.generated for block in self._last_ai_blocks)
        return ReportManifest(
            report_id=html_report_id(bundle, self.config),
            title=REPORT_TITLE,
            created_from_lineage_at=bundle.lineage.created_at.isoformat(),
            template_id=self.config.html.template_id,
            template_version=REPORT_TEMPLATE_VERSION,
            output_format="html",
            path="",
            sha256=digest,
            deterministic=self.config.html.deterministic_ids and not ai_used,
            ai_enabled=self.config.ai.enabled or bool(self._last_ai_blocks),
            ai_used=ai_used,
            sections=ordered_sections(bundle.sections),
        )

    def write(self, html: str, *, output_dir: str) -> ReportManifest:
        """Escribe el HTML en disco y devuelve un manifiesto reproducible."""
        bundle = self._last_bundle
        if bundle is None:
            raise ReportExportError(
                "No se puede exportar report.html porque no hay bundle renderizado; "
                "acción='llame HtmlReportRenderer.render antes de write'."
            )

        directory = _prepare_output_dir(output_dir)
        filename = f"{self.config.basename}.html"
        output_path = directory / filename
        normalized_html = _normalize_newlines(html)
        payload = normalized_html.encode("utf-8")
        temp_path = directory / f".{filename}.tmp"

        try:
            temp_path.write_bytes(payload)
            temp_path.replace(output_path)
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            raise ReportExportError(
                "No se pudo escribir el reporte HTML: dominio='report', "
                f"clave='{filename}', output_dir='{output_dir}', "
                "acción='verifique permisos y espacio disponible'."
            ) from exc

        manifest = self.build_manifest(normalized_html)
        return manifest.model_copy(update={"path": _manifest_path(directory, filename)})


class PdfReportRenderer:
    """Render opcional a PDF vía WeasyPrint sobre el HTML básico primario."""

    def __init__(self, config: ReportConfig | PdfRenderConfig | None = None) -> None:
        """Construye el renderer PDF desde ``ReportConfig`` o ``PdfRenderConfig``."""
        if isinstance(config, PdfRenderConfig):
            self.config = ReportConfig(pdf=config)
        elif config is None:
            self.config = ReportConfig()
        else:
            self.config = config

    @classmethod
    def from_config(cls, cfg: ReportConfig) -> PdfReportRenderer:
        """Construye ``PdfReportRenderer`` desde ``NikodymConfig.report``."""
        return cls(cfg)

    def render(self, bundle: ReportInputBundle, *, output_dir: str) -> ReportManifest:
        """Renderiza y escribe el HTML básico y, si procede, un PDF opcional en disco.

        El HTML determinístico es el artefacto primario: se escribe siempre y su manifest es el
        valor de retorno (igual que hoy con la ruta HTML). Con ``pdf.enabled`` se genera además un
        PDF con WeasyPrint (import perezoso) que se escribe como efecto secundario en
        ``{basename}.pdf`` y NO se refleja en el manifest. Si WeasyPrint no está disponible degrada
        a HTML (``fail_if_unavailable=False``) o re-lanza la dependencia ausente (``True``).
        """
        html_renderer = HtmlReportRenderer.from_config(self.config)
        html = html_renderer.render(bundle)
        manifest = html_renderer.write(html, output_dir=output_dir)

        # El uso directo del renderer sigue guiado por ``pdf.enabled``; el step, en cambio, decide
        # por ``formats`` y llama a ``write_pdf_from_html`` sin pasar por ``render`` (SDD-26 §7).
        if self.config.pdf.enabled:
            self.write_pdf_from_html(html, output_dir=output_dir)
        return manifest

    def write_pdf_from_html(self, html: str, *, output_dir: str) -> Path | None:
        """Escribe el PDF desde un HTML ya renderizado; devuelve su ``Path`` o ``None`` al degradar.

        Recibe el HTML primario (que puede incluir la narrativa IA) y produce el PDF con WeasyPrint
        (import perezoso), sin re-renderizar el HTML. Degrada con gracia según
        ``pdf.fail_if_unavailable``: en ausencia de WeasyPrint re-lanza la dependencia (``True``) o
        emite ``RuntimeWarning`` y devuelve ``None`` (``False``). En éxito escribe
        ``{basename}.pdf`` y devuelve el ``Path`` real en disco.
        """
        # Import perezoso: WeasyPrint (y sus nativas) nunca entra al import del paquete.
        from nikodym.report.pdf import render_pdf

        try:
            pdf_bytes = render_pdf(html)
        except ReportDependencyError:
            if self.config.pdf.fail_if_unavailable:
                raise
            warnings.warn(
                "WeasyPrint no está disponible; se usó HTML básico determinístico sin PDF.",
                RuntimeWarning,
                stacklevel=2,
            )
            return None
        return self._write_pdf(pdf_bytes, output_dir=output_dir)

    def _write_pdf(self, pdf_bytes: bytes, *, output_dir: str) -> Path:
        """Escribe el PDF con escritura atómica (tmp + ``replace``), idéntico al HTML."""
        directory = _prepare_output_dir(output_dir)
        filename = f"{self.config.basename}.pdf"
        output_path = directory / filename
        temp_path = directory / f".{filename}.tmp"
        try:
            temp_path.write_bytes(pdf_bytes)
            temp_path.replace(output_path)
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            raise ReportExportError(
                "No se pudo escribir el reporte PDF: dominio='report', formato='pdf', "
                f"clave='{filename}', output_dir='{output_dir}', "
                "acción='verifique permisos y espacio disponible'."
            ) from exc
        return output_path


def _coerce_report_config(
    config: ReportConfig | HtmlRenderConfig | None,
    *,
    basename: str | None,
    sections: SectionPolicyConfig | None,
    ai: AiNarrationConfig | None,
) -> ReportConfig:
    if isinstance(config, HtmlRenderConfig):
        return ReportConfig(
            basename=basename or "scorecard_report",
            html=config,
            sections=sections or SectionPolicyConfig(),
            ai=ai or AiNarrationConfig(),
        )
    if config is None:
        if basename is None and sections is None and ai is None:
            return ReportConfig()
        return ReportConfig(
            basename=basename or "scorecard_report",
            sections=sections or SectionPolicyConfig(),
            ai=ai or AiNarrationConfig(),
        )
    return config


def build_document_view(
    bundle: ReportInputBundle,
    *,
    config: ReportConfig,
    ai_blocks: tuple[AiNarrationBlock, ...] = (),
    chart_format: ChartFormat = "svg",
) -> dict[str, Any]:
    """Proyecta el documento completo a datos planos, sin decidir nada del formato de salida.

    Es el contrato que comparten HTML, Markdown y Word: mismos capítulos, mismo índice, mismas
    tablas y los mismos bloques POR COMPLETAR. Cada renderer sólo decide **cómo se ve** cada bloque,
    nunca **qué bloques hay** ni en qué orden. ``chart_format`` es lo único que varía por destino:
    el HTML y el ``.qmd`` embeben SVG; Word no los admite y pide PNG.
    """
    section_views = _section_views(bundle, ai_blocks, config, chart_format)
    return {
        "title": "Reporte IFRS 9 / ECL" if _is_ifrs9_run(bundle) else REPORT_TITLE,
        "document_title": _document_title(bundle),
        "cover_kicker": (
            "Informe regulatorio — pérdida crediticia esperada"
            if _is_ifrs9_run(bundle)
            else "Informe de validación de modelos"
        ),
        "exec_scope_note": _exec_scope_note(bundle),
        "template_id": config.html.template_id,
        "template_version": REPORT_TEMPLATE_VERSION,
        "created_from_lineage_at": bundle.lineage.created_at.isoformat(),
        "emitted_date": _emitted_date(bundle),
        "lineage": _lineage_view(bundle),
        "cover": _cover_view(bundle, config),
        "executive": _executive_view(bundle),
        "toc": _toc_entries(section_views),
        "sections": section_views,
    }


def _section_views(
    bundle: ReportInputBundle,
    ai_blocks: tuple[AiNarrationBlock, ...],
    config: ReportConfig,
    chart_format: ChartFormat = "svg",
) -> list[dict[str, Any]]:
    """Proyecta cada sección a la vista que consume su parcial, según su ``kind``.

    El dump (payload crudo y tablas completas) sólo se emite donde corresponde —los anexos—; el
    cuerpo lleva prosa, las tablas que importan y sus gráficos. Las tablas que el cuerpo ya mostró
    **no se repiten** en el anexo: se acumulan en ``shown`` a medida que se proyectan las secciones
    (que llegan en orden canónico, con los anexos al final) y el anexo publica el complemento.
    """
    narratives = {block.section_id: block for block in ai_blocks}
    views: list[dict[str, Any]] = []
    shown: set[str] = set()
    for section in ordered_sections(bundle.sections):
        is_appendix = section.kind == "appendix"
        tables = _tables_for_section(bundle, section, config, shown=shown)
        shown.update(table["key"] for table in tables)
        views.append(
            {
                "id": section.id,
                "html_id": _element_id("section", section.id),
                "kind": section.kind,
                "level": section.level,
                "number": section.number,
                "title": section.title,
                "status": section.status,
                "source": _section_source(section),
                "body": list(section.body),
                "placeholder": _placeholder_view(section),
                "payload_items": _mapping_items(section.payload) if is_appendix else [],
                "metric_items": _mapping_items(section.metric_sections) if is_appendix else [],
                "tables": tables,
                "charts": _charts_for_section(bundle, section, config, chart_format),
                "figures": _figures_for_section(bundle, section),
                "data_exports": _data_exports_view(bundle, section, config),
                "narration": _narration_view(narratives.get(section.id), config.ai.label_ai_text),
            }
        )
    return views


def _placeholder_view(section: ReportSection) -> dict[str, Any] | None:
    """Proyecta el bloque POR COMPLETAR; ``None`` cuando el config pide ocultarlo."""
    if section.placeholder is None:
        return None
    return {
        "title": section.placeholder.title,
        "guidance": list(section.placeholder.guidance),
    }


def _toc_entries(views: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Genera el índice desde las secciones ya proyectadas: el documento se indexa a sí mismo."""
    entries: list[dict[str, Any]] = [
        {"href": "#exec-summary", "number": "", "title": "Resumen ejecutivo", "level": 1}
    ]
    for view in views:
        if view["kind"] == "toc":
            continue
        entries.append(
            {
                "href": f"#{view['html_id']}",
                "number": _display_number(view),
                "title": str(view["title"]),
                "level": int(view["level"]),
            }
        )
    return entries


def _display_number(view: Mapping[str, Any]) -> str:
    """Numeración visible: '4.3' en los capítulos, 'Anexo B' en los anexos de primer nivel."""
    number = str(view["number"])
    if not number:
        return ""
    if view["kind"] == "appendix" and int(view["level"]) == 1:
        return f"Anexo {number}"
    return number


def _cover_view(bundle: ReportInputBundle, config: ReportConfig) -> list[dict[str, Any]]:
    """Campos de portada: lo declarado se imprime; lo no declarado queda en blanco, no inventado."""
    document = config.document
    campos = (
        ("Modelo", document.model_name),
        ("Entidad", document.entity),
        ("Cartera", document.portfolio),
        ("Responsable del desarrollo", document.author),
        ("Versión del informe", document.version),
    )
    del bundle
    return [
        {"label": label, "value": value.strip(), "filled": bool(value.strip())}
        for label, value in campos
    ]


def _emitted_date(bundle: ReportInputBundle) -> str:
    """Fecha de emisión legible (``YYYY-MM-DD``) derivada del lineage, no del reloj de pared.

    El timestamp completo con microsegundos sigue íntegro en el manifest y en el Anexo A; en la
    portada de un informe firmable lo que corresponde es una fecha.
    """
    return bundle.lineage.created_at.date().isoformat()


def _is_ifrs9_run(bundle: ReportInputBundle) -> bool:
    """Una corrida ECL «pura»: calculó IFRS 9 y no corrió el scorecard (SDD-16)."""
    return "provisioning_ifrs9" in bundle.cards and "scorecard" not in bundle.cards


def _document_title(bundle: ReportInputBundle) -> str:
    """Titula el documento según lo que la corrida ES, compartido por HTML, ``.qmd`` y Word.

    Una corrida IFRS 9 sin scorecard no es una validación de scorecard; titularla así en la
    portada sería describir otro documento.
    """
    if _is_ifrs9_run(bundle):
        return IFRS9_DOCUMENT_TITLE
    return DOCUMENT_TITLE


def _exec_scope_note(bundle: ReportInputBundle) -> str:
    """Nota de alcance del resumen ejecutivo, coherente con lo que la corrida calculó.

    El texto histórico decía «la integración con IFRS 9 corresponde a fases posteriores»: falso
    —y en la primera página— cuando el capítulo central del informe ES la ECL IFRS 9.
    """
    if _is_ifrs9_run(bundle):
        return (
            "Alcance: cálculo de la pérdida crediticia esperada IFRS 9 (función experimental, "
            "SDD-16 en borrador). La validación completa del scorecard y el backtesting de la "
            "ECL corresponden a fases posteriores; este informe no los cubre ni infiere sus "
            "resultados. Todos los valores provienen de la corrida trazada en la portada: no se "
            "completan con supuestos."
        )
    return (
        "Alcance: validación de scorecard (discriminación, estabilidad y calibración). El "
        "backtesting y la integración con IFRS 9 corresponden a fases posteriores; este informe "
        "no los cubre ni infiere sus resultados. Todos los valores provienen de la corrida "
        "trazada en la portada: no se completan con supuestos."
    )


def _executive_view(bundle: ReportInputBundle) -> dict[str, Any]:
    """Métricas clave del resumen ejecutivo (AUC/Gini/KS y PSI) con la banda del motor."""
    from nikodym.report.prose import executive_view

    view = executive_view(bundle)
    return {
        "metrics": [
            {
                "label": metric.label,
                "scope": metric.scope,
                "value": metric.value,
                "band": metric.band,
                "band_class": _band_class(metric.band),
            }
            for metric in view.metrics
        ],
        "notes": list(view.notes),
    }


def _band_class(band: str) -> str:
    """Clase CSS del semáforo: sólo se colorea lo que el motor sí evaluó."""
    if band in {"Bajo el umbral configurado", "Requiere redesarrollo"}:
        return "band-alert"
    if band == "Requiere revisión":
        return "band-warn"
    if band in {"Sin alertas", "Estable"}:
        return "band-ok"
    return "band-none"


def _lineage_view(bundle: ReportInputBundle) -> dict[str, str]:
    lineage = bundle.lineage
    return {
        "git_sha": _display_scalar(lineage.git_sha, key_path=("git_sha",)),
        "data_hash": _display_scalar(lineage.data_hash, key_path=("data_hash",)),
        "config_hash": _display_scalar(lineage.config_hash, key_path=("config_hash",)),
        "root_seed": _display_scalar(lineage.root_seed, key_path=("root_seed",)),
    }


def _section_source(section: ReportSection) -> str:
    domain = section.source_domain or "sin_dominio"
    key = section.source_key or "sin_clave"
    return f"{domain}.{key}"


def _mapping_items(value: Mapping[str, Any]) -> list[dict[str, str | bool]]:
    items: list[dict[str, str | bool]] = []
    for raw_key in sorted(value, key=str):
        key = str(raw_key)
        rendered = _display_value(value[raw_key], key_path=(key,))
        items.append({"key": key, "value": rendered, "multiline": "\n" in rendered})
    return items


def _narration_view(block: AiNarrationBlock | None, label_ai_text: bool) -> dict[str, str] | None:
    """Muestra el bloque narrativo sólo si aporta algo que la prosa del cuerpo no dice ya.

    La narrativa determinista **es** el cuerpo de la sección (``body``): repetirla como bloque
    aparte duplicaría el texto. Se emite, entonces, sólo cuando la escribió la IA (opt-in) o cuando
    hay que declarar que la IA degradó a la ruta básica.
    """
    if block is None or (not block.generated and not block.warning):
        return None
    label = "Narrativa generada por IA" if label_ai_text and block.generated else ""
    warning = block.warning or ""
    return {"text": block.text, "label": label, "warning": warning}


def _tables_for_section(
    bundle: ReportInputBundle,
    section: ReportSection,
    config: ReportConfig,
    *,
    shown: set[str],
) -> list[dict[str, Any]]:
    """Resuelve qué tablas muestra una sección.

    El cuerpo muestra las de :data:`~nikodym.report.document.KEY_TABLES` del dominio, que son las
    que sostienen el juicio de validación. El anexo de tablas publica **el resto** de las tablas
    agregadas —binning por variable, correlación, estabilidad—: lo que el cuerpo no mostró, no lo
    que ya mostró. Repetir una tabla íntegra en dos sitios no añade trazabilidad, añade páginas.

    Las tablas **por observación** no salen en ninguna de las dos: son el dataset, no el informe, y
    se entregan completas como adjuntos (:func:`_data_exports_view`).
    """
    if section.id == APPENDIX_TABLES_ID:
        keys: tuple[str, ...] = tuple(
            key
            for key in sorted(bundle.tables, key=str)
            if key not in shown and key not in PER_OBSERVATION_TABLES
        )
    elif section.kind == "data" and section.source_domain and section.status == "included":
        keys = tuple(
            key
            for key in KEY_TABLES.get(section.source_domain, ())
            if key in bundle.tables and key not in PER_OBSERVATION_TABLES
        )
    else:
        keys = ()
    max_rows = config.sections.max_table_rows
    return [_table_view(key, bundle.tables[key], max_rows=max_rows) for key in keys]


def _data_exports_view(
    bundle: ReportInputBundle,
    section: ReportSection,
    config: ReportConfig,
) -> dict[str, Any]:
    """Declara, en el anexo de tablas, dónde quedó el detalle por observación.

    El documento no calla lo que sacó: nombra cada tabla por observación, su tamaño real (completo,
    no el truncado que antes se mostraba) y el archivo adjunto que la entrega. Si no se pidió
    ``csv`` ni ``xlsx``, dice exactamente eso —que el detalle no se emitió y cómo pedirlo— en vez de
    referenciar un archivo que no existe.
    """
    if section.id != APPENDIX_TABLES_ID:
        return {}
    keys = tuple(key for key in sorted(bundle.tables, key=str) if key in PER_OBSERVATION_TABLES)
    if not keys:
        return {}
    refs = data_export_refs(bundle.tables, config=config)
    return {
        "requested": bool(refs),
        "attachments": [
            {
                "title": ref.title,
                "key": ref.table_key,
                "rows": _thousands(ref.rows),
                "filename": ref.filename,
                "sheet": ref.sheet,
            }
            for ref in refs
        ],
        "pending": [
            {
                "title": table_title(key),
                "key": key,
                "rows": _thousands(len(bundle.tables[key].index)),
            }
            for key in keys
        ]
        if not refs
        else [],
    }


def _thousands(value: int) -> str:
    """Formatea un conteo con el separador de miles del informe (español: ``1.234``)."""
    return f"{value:,}".replace(",", ".")


def _table_view(key: str, table: Any, *, max_rows: int) -> dict[str, Any]:
    if not _is_dataframe_like(table):
        raise ReportRenderError(
            f"Tabla no renderizable en report: clave='{key}', acción='publique un DataFrame'."
        )
    columns = tuple(table.columns)
    records = cast(list[Mapping[Any, Any]], table.to_dict(orient="records"))
    rows = [
        tuple(
            _display_scalar(record.get(column), key_path=(key, str(column))) for column in columns
        )
        for record in records
    ]
    visible_rows = rows[:max_rows]
    return {
        "key": key,
        "title": table_title(key),
        "html_id": _element_id("table", key),
        "columns": [str(column) for column in columns],
        "rows": visible_rows,
        "total_rows": len(rows),
        "shown_rows": len(visible_rows),
        "truncated": len(rows) > len(visible_rows),
    }


def _figures_for_section(bundle: ReportInputBundle, section: ReportSection) -> list[dict[str, str]]:
    """Las figuras declarativas acompañan al detalle: viven en el Anexo B."""
    if section.id != APPENDIX_TABLES_ID:
        return []
    return [
        {
            "key": key,
            "html_id": _element_id("figure", key),
            "payload": _display_value(bundle.figures[key], key_path=(key,)),
        }
        for key in sorted(bundle.figures, key=str)
    ]


_CHART_TITLES: Final[dict[str, str]] = {
    "gains": "Curva de ganancia acumulada por partición",
    "discrimination": "Discriminación (AUC/Gini/KS) por partición",
    "coefficients": "Coeficientes del modelo (β, IC 95 %)",
    "stability": "Estabilidad PSI/CSI por comparación",
    "reliability": "Curva de calibración (confiabilidad) por partición",
}


def _chart_gains(charts: Any, bundle: ReportInputBundle, fmt: ChartFormat) -> str | bytes:
    """Curva de ganancia desde ``performance.performance_table``."""
    return cast(
        "str | bytes",
        charts.render_gains_chart(
            bundle.tables["performance.performance_table"],
            title=_CHART_TITLES["gains"],
            fmt=fmt,
        ),
    )


def _chart_discrimination(charts: Any, bundle: ReportInputBundle, fmt: ChartFormat) -> str | bytes:
    """Barras de discriminación desde ``performance.discriminant_metrics``."""
    return cast(
        "str | bytes",
        charts.render_discrimination_bars(
            bundle.tables["performance.discriminant_metrics"],
            title=_CHART_TITLES["discrimination"],
            fmt=fmt,
        ),
    )


def _chart_coefficients(charts: Any, bundle: ReportInputBundle, fmt: ChartFormat) -> str | bytes:
    """Forest de coeficientes desde ``model.coefficients``."""
    return cast(
        "str | bytes",
        charts.render_coefficients_forest(
            bundle.tables["model.coefficients"],
            title=_CHART_TITLES["coefficients"],
            fmt=fmt,
        ),
    )


def _chart_stability(charts: Any, bundle: ReportInputBundle, fmt: ChartFormat) -> str | bytes:
    """Barras horizontales PSI/CSI desde ``stability.stability_metrics``."""
    return cast(
        "str | bytes",
        charts.render_stability_chart(
            bundle.tables["stability.stability_metrics"],
            title=_CHART_TITLES["stability"],
            fmt=fmt,
        ),
    )


def _chart_reliability(charts: Any, bundle: ReportInputBundle, fmt: ChartFormat) -> str | bytes:
    """Curva de confiabilidad derivada en render-time desde ``calibration.calibrated_pd_frame``.

    ``reliability_curve`` (capa ``ui``) proyecta el frame calibrado a la lista ``by_partition`` que
    consume ``render_reliability_chart``; el import es perezoso para no arrastrar la capa ``ui`` al
    import del paquete ``report``.
    """
    from nikodym.ui.reliability import reliability_curve

    curve = reliability_curve(bundle.tables["calibration.calibrated_pd_frame"])
    return cast(
        "str | bytes",
        charts.render_reliability_chart(
            curve["by_partition"], title=_CHART_TITLES["reliability"], fmt=fmt
        ),
    )


# Mapeo sección → gráficos (nombre estable + builder). El nombre alimenta el ``id`` HTML del slot.
_CHART_BUILDERS: Final[
    dict[str, tuple[tuple[str, Callable[[Any, ReportInputBundle, ChartFormat], str | bytes]], ...]]
] = {
    "performance": (("gains", _chart_gains), ("discrimination", _chart_discrimination)),
    "model": (("coefficients", _chart_coefficients),),
    "stability": (("stability", _chart_stability),),
    "calibration": (("reliability", _chart_reliability),),
}


def _charts_for_section(
    bundle: ReportInputBundle,
    section: ReportSection,
    config: ReportConfig,
    chart_format: ChartFormat = "svg",
) -> list[dict[str, Any]]:
    """Genera los gráficos deterministas de la sección desde ``bundle.tables`` (import perezoso).

    Los gráficos acompañan al **cuerpo** (las subsecciones de datos de Resultados y Contexto),
    donde sostienen la lectura; no se repiten en los anexos. Cada gráfico se produce aislado y con
    degradación con gracia: si falta ``matplotlib``, faltan columnas o la tabla no está publicada,
    se omite ese gráfico y el reporte se renderiza igual. El import de
    :mod:`nikodym.report.charts` es perezoso para preservar el import liviano del paquete.

    La vista trae el gráfico bajo la clave de su formato (``svg`` texto o ``png`` bytes), de modo
    que cada renderer consuma el suyo sin reconvertir nada.
    """
    if not config.html.render_charts or section.kind != "data" or section.status != "included":
        return []
    domain = section.source_domain
    builders = _CHART_BUILDERS.get(domain) if domain is not None else None
    if builders is None:
        return []
    from nikodym.report import charts  # perezoso: matplotlib no entra al import del paquete.

    results: list[dict[str, Any]] = []
    for name, build in builders:
        try:
            image = build(charts, bundle, chart_format)
        except Exception as exc:  # degradación con gracia: un gráfico nunca tumba el reporte.
            _LOGGER.warning(
                "report: gráfico '%s.%s' omitido por degradación con gracia: %s",
                domain,
                name,
                exc,
            )
            continue
        results.append(
            {
                "html_id": _element_id("chart", f"{domain}-{name}"),
                "title": _CHART_TITLES[name],
                chart_format: image,
            }
        )
    return results


def _display_value(value: Any, *, key_path: tuple[str, ...]) -> str:
    if isinstance(value, Mapping):
        rendered = {
            str(key): _display_json_value(value[key], key_path=(*key_path, str(key)))
            for key in sorted(value, key=str)
        }
        return json.dumps(rendered, sort_keys=True, ensure_ascii=False, indent=2)
    if isinstance(value, tuple | list):
        return json.dumps(
            [_display_json_value(item, key_path=key_path) for item in value],
            ensure_ascii=False,
            indent=2,
        )
    if isinstance(value, set | frozenset):
        ordered = sorted(value, key=lambda item: _stable_json(_canonical_value(item)))
        return json.dumps(
            [_display_json_value(item, key_path=key_path) for item in ordered],
            ensure_ascii=False,
            indent=2,
        )
    if isinstance(value, BaseModel):
        return _display_value(value.model_dump(mode="python"), key_path=key_path)
    if _is_dataframe_like(value):
        return "[tabla referenciada]"
    return _display_scalar(value, key_path=key_path)


def _display_json_value(value: Any, *, key_path: tuple[str, ...]) -> JSONValue:
    if isinstance(value, Mapping):
        return {
            str(key): _display_json_value(value[key], key_path=(*key_path, str(key)))
            for key in sorted(value, key=str)
        }
    if isinstance(value, tuple | list):
        return [_display_json_value(item, key_path=key_path) for item in value]
    if isinstance(value, set | frozenset):
        ordered = sorted(value, key=lambda item: _stable_json(_canonical_value(item)))
        return [_display_json_value(item, key_path=key_path) for item in ordered]
    if isinstance(value, BaseModel):
        return _display_json_value(value.model_dump(mode="python"), key_path=key_path)
    if _is_dataframe_like(value):
        return "[tabla referenciada]"
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        # Los motores de provisiones publican sus cifras contables en Decimal. Sin esta rama, el
        # Anexo de parámetros imprimiría {"unsupported_type": "Decimal"} donde va la provisión.
        return _format_float(float(value), key_path=key_path)
    if isinstance(value, float):
        return _format_float(value, key_path=key_path)
    if isinstance(value, str):
        return value
    return {"unsupported_type": type(value).__name__}


def _display_scalar(value: Any, *, key_path: tuple[str, ...]) -> str:
    if value is None:
        return "No disponible"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return _format_float(value, key_path=key_path)
    if isinstance(value, BaseModel):
        return _display_value(value.model_dump(mode="python"), key_path=key_path)
    if isinstance(value, Mapping | Sequence) and not isinstance(value, str | bytes | bytearray):
        return _display_value(value, key_path=key_path)
    return str(value)


def _format_float(value: float, *, key_path: tuple[str, ...]) -> str:
    if value == 0.0:
        value = 0.0
    if not math.isfinite(value):
        if math.isnan(value):
            return "nan"
        return "inf" if value > 0 else "-inf"
    key = ".".join(key_path).lower()
    if _is_percent_key(key):
        return f"{value:.4f}"
    if _is_six_decimal_key(key):
        return f"{value:.6f}"
    return f"{value:.6f}"


def _is_percent_key(key: str) -> bool:
    return any(token in key for token in ("pct", "percent", "porcentaje", "tasa", "rate"))


def _is_six_decimal_key(key: str) -> bool:
    return any(token in key for token in ("pd", "psi", "csi", "auc", "ks", "gini"))


def _canonical_value(value: Any) -> JSONValue:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_canonical_value(item) for item in sorted(value, key=str)]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Decimal):  # cifras contables de provisiones: al hash van como float
        return _canonical_value(float(value))
    if isinstance(value, float):
        if value == 0.0:
            return 0.0
        if math.isfinite(value):
            return value
        if math.isnan(value):
            return {"non_finite_float": "nan"}
        return {"non_finite_float": "inf" if value > 0 else "-inf"}
    if isinstance(value, str):
        return value
    return {"unsupported_type": type(value).__name__}


def _stable_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _element_id(kind: str, raw_id: str) -> str:
    """Deriva IDs HTML siempre determinísticos desde el tipo y la clave lógica."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw_id.strip().lower()).strip("-")
    return f"{kind}-{slug or 'sin-id'}"


def _load_template(environment: Any) -> Any:
    """Carga la plantilla editorial del paquete; aislada para poder simular fallos en tests."""
    return environment.get_template(_TEMPLATE_NAME)


def _css_for_theme(theme: Literal["nikodym", "plain"]) -> str:
    """Lee el CSS del tema desde los archivos empaquetados bajo ``report/templates``."""
    filename = _CSS_FILES.get(theme, _CSS_FILES["nikodym"])
    return resources.files(_TEMPLATE_PACKAGE).joinpath(filename).read_text("utf-8").strip()


def _normalize_newlines(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        return f"{normalized}\n"
    return normalized


def _digest_html(html: str) -> str:
    """SHA-256 del HTML con cada ``<svg>…</svg>`` reemplazado por un placeholder estable.

    El manifest y los goldens usan este digest en vez del ``sha256`` de los bytes crudos: los SVG de
    los gráficos dependen de freetype y no son byte-idénticos entre sistemas operativos, así que se
    excluyen para que el digest sea reproducible cross-OS. Cubre datos y estructura del reporte; el
    determinismo byte a byte de cada SVG se verifica aparte en ``test_report_charts``. El HTML en
    disco conserva los SVG intactos.
    """
    stripped = _SVG_STRIP_PATTERN.sub(_STRIPPED_SVG, _normalize_newlines(html))
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()


def _prepare_output_dir(output_dir: str) -> Path:
    directory = Path(output_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReportExportError(
            "No se pudo crear el directorio de salida del reporte: dominio='report', "
            f"output_dir='{output_dir}', acción='verifique permisos de la ruta padre'."
        ) from exc
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        raise ReportExportError(
            "El directorio de salida del reporte no es escribible: dominio='report', "
            f"output_dir='{output_dir}', acción='ajuste permisos o use otra ruta'."
        )
    return directory


def _manifest_path(directory: Path, filename: str) -> str:
    if directory.is_absolute():
        return filename
    return (directory / filename).as_posix()


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))
