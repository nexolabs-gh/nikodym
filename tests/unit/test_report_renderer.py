"""Tests de ``report.renderer``: HTML determinístico, export y PDF opcional."""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import BaseModel

import nikodym.report as report_pkg
import nikodym.report.renderer as renderer_module
from nikodym.core.lineage import LineageBundle
from nikodym.report.config import (
    AiNarrationConfig,
    DocumentStructureConfig,
    HtmlRenderConfig,
    PdfRenderConfig,
    ReportConfig,
    SectionPolicyConfig,
)
from nikodym.report.exceptions import (
    ReportDependencyError,
    ReportExportError,
    ReportRenderError,
)
from nikodym.report.renderer import HtmlReportRenderer, PdfReportRenderer
from nikodym.report.results import (
    AiNarrationBlock,
    PlaceholderBlock,
    ReportInputBundle,
    ReportSection,
)

# Golden del ``_digest_html`` (excluye los bytes ``<svg>``, ver renderer): con el extra ``report``
# el bundle golden embebe un único gráfico (forest de coeficientes) cuyo slot cuenta en el digest.
# Recalculado al pasar el reporte de log a documento: el HTML cambió a propósito (portada con
# metadatos, índice, resumen ejecutivo con métricas, capítulos de prosa y dump degradado a anexos).
# Recalculado (SDD-28 G5) al retirar del resumen ejecutivo y de Limitaciones la frase que declaraba
# las provisiones "fase posterior": el capítulo de provisiones ya existe (condicional, no en este
# bundle F1). Verificado que el HTML cambió SOLO en esas dos frases (el orden canónico intacto).
# Recalculado (re-skin Quarto): el tema "nikodym" adoptó un layout editorial de 3 columnas (sidebar
# de secciones + índice lateral "En esta página") con un CSS nuevo y marca oficial, ambos inline en
# el HTML → el digest se mueve. El markup del documento (data-section-id y orden canónico, tablas
# con id/thead/tbody, literales config_hash=/data_hash=/git_sha=/root_seed=) queda intacto.
GOLDEN_HTML_SHA256 = "83ae8bc82a01eeb51542db18e6821db5dd7594e2da01d41d830a5c59869756cd"

_HAS_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None


class MiniFigure(BaseModel):
    """Figura declarativa mínima para cubrir serialización de BaseModel."""

    figure_id: str
    title: str


class FrameLike:
    """Objeto con forma de DataFrame para cubrir ramas defensivas."""

    columns: tuple[str, ...] = ("valor",)

    def copy(self, *, deep: bool) -> FrameLike:
        """Devuelve copia sintética."""
        del deep
        return FrameLike()

    def select_dtypes(self) -> tuple[object, ...]:
        """Imita ``DataFrame.select_dtypes``."""
        return ()

    def to_dict(self, *, orient: str) -> list[dict[str, float]]:
        """Entrega registros determinísticos."""
        assert orient == "records"
        return [{"valor": -0.0}]


def test_html_golden_deterministico_y_orden_canonico() -> None:
    """El HTML queda byte-idéntico y respeta el orden canónico del documento."""
    renderer = _renderer()
    bundle = _bundle()

    first = renderer.render(bundle)
    second = renderer.render(bundle)
    digest = renderer_module._digest_html(first)

    assert first == second
    # El golden vale sólo con matplotlib (extra ``report``) instalado y el gráfico embebido; en los
    # jobs mínimos el gráfico degrada con gracia y el digest no lleva el slot.
    if _HAS_MATPLOTLIB:
        assert digest == GOLDEN_HTML_SHA256
    assert "2026-06-29" not in first
    assert "datetime.now" not in first
    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        first,
        flags=re.IGNORECASE,
    )
    assert "/Users/" not in first
    assert "config_hash=cfg123456789abcdef" in first
    assert "data_hash=data123456789abcdef" in first
    assert "git_sha=abc123" in first
    assert "0.743210" in first
    assert "-0.0" not in first

    # Las secciones del documento salen en el orden canónico aunque el bundle llegue desordenado.
    positions = [first.index(f'data-section-id="{section_id}"') for section_id in _CANONICAL_IDS]
    assert positions == sorted(positions)

    performance_table = _table_fragment(first, "table-performance-performance_table")
    decile_markers = [f"<td>{decile}</td>" for decile in range(12, 2, -1)]
    decile_positions = [performance_table.index(marker) for marker in decile_markers]
    assert decile_positions == sorted(decile_positions)
    assert "<td>11</td>" in performance_table
    assert "<td>2</td>" not in performance_table
    assert "<td>1</td>" not in performance_table

    coefficients_table = _table_fragment(first, "table-model-coefficients")
    column_positions = [
        coefficients_table.index(f"<th>{column}</th>") for column in ("feature", "beta", "p_value")
    ]
    assert column_positions == sorted(column_positions)


def test_documento_tiene_indice_metricas_ejecutivas_y_titulos_legibles() -> None:
    """El HTML es un documento: índice, métricas clave y tablas con nombre humano.

    Los tres agujeros del reporte-log: no había índice, el ``exec-metrics-slot`` estaba vacío
    ("se completa en B3", nunca se completó) y las tablas se titulaban con el nombre de la variable
    interna (``Tabla binning.tables.antiguedad_meses``).
    """
    html = _renderer(
        ReportConfig(
            document=DocumentStructureConfig(entity="Banco Ejemplo S.A."),
            sections=SectionPolicyConfig(max_table_rows=10),
        )
    ).render(_bundle_con_cards())

    # Índice generado, con anclas reales a las secciones.
    assert '<section id="section-toc"' in html
    assert '<a href="#section-results-model">' in html
    assert '<a href="#exec-summary">' in html

    # El slot ejecutivo ya no está vacío: trae las métricas clave y su banda.
    assert '<div class="exec-metrics-slot"></div>' not in html
    assert '<table class="exec-metrics">' in html
    assert "0.7432" in html  # AUC de la card de performance
    assert "Sin alertas" in html
    assert "No se configuraron umbrales de discriminación" in html

    # Títulos de tabla legibles, con la clave interna degradada a atributo de trazabilidad.
    assert '<figcaption class="table-title">Coeficientes del modelo PD</figcaption>' in html
    assert "Tabla model.coefficients" not in html
    assert 'data-table-key="model.coefficients"' in html

    # La portada imprime los metadatos declarados y deja en blanco lo no declarado.
    assert "Banco Ejemplo S.A." in html
    assert '<span class="to-fill"' in html


def test_placeholders_show_y_hide() -> None:
    """El bloque POR COMPLETAR trae guía de redacción y desaparece en el entregable final."""
    con_bloque = _renderer().render(_bundle())
    sin_bloque = _renderer().render(
        _bundle(
            sections_override=tuple(
                section.model_copy(update={"placeholder": None}) for section in _bundle().sections
            )
        )
    )

    assert "POR COMPLETAR — Contexto del modelo" in con_bloque
    assert "Describe la cartera: producto, segmento, volumen y período." in con_bloque
    assert '<div class="placeholder">' in con_bloque
    assert '<div class="placeholder">' not in sin_bloque
    assert "POR COMPLETAR — Contexto del modelo" not in sin_bloque
    # El capítulo y su prosa determinista siguen ahí: sólo desaparece la caja de guía.
    assert "La tasa de incumplimiento observada es de 12.35 %." in sin_bloque


def test_el_dump_se_degrada_a_anexo_pero_no_se_duplica() -> None:
    """El anexo COMPLETA al cuerpo; no lo repite. La evidencia no se pierde, deja de duplicarse.

    La tanda 1 dejó el Anexo B publicando **todas** las tablas, incluidas las que el cuerpo ya
    mostraba: cada tabla clave salía dos veces en el mismo documento (9 tablas duplicadas en una
    corrida real). Repetir una tabla íntegra no añade trazabilidad, añade páginas. Ahora el cuerpo
    muestra las tablas que sostienen el juicio y el anexo publica **el resto**.
    """
    correlacion = pd.DataFrame({"variable": ["mora"], "saldo": [0.31]})
    html = _renderer().render(
        _bundle(tables={**_tables(), "selection.correlation_matrix": correlacion})
    )

    anexo_b = _section_fragment(html, "appendix_tables")
    anexo_c_eda = _section_fragment(html, "appendix_parameters.eda")
    resultados_modelo = _section_fragment(html, "results.model")

    # Las tablas clave viven en el CUERPO y no se repiten en el anexo.
    for key in ("performance.performance_table", "model.coefficients"):
        assert html.count(f'data-table-key="{key}"') == 1
        assert f'data-table-key="{key}"' not in anexo_b
    assert 'data-table-key="model.coefficients"' in resultados_modelo

    # Lo que el cuerpo NO muestra sigue íntegro en el anexo: la trazabilidad no se pierde.
    assert 'data-table-key="selection.correlation_matrix"' in anexo_b
    assert 'data-figure="eda.figures"' in anexo_b

    # Anexo C: el payload crudo, con su artefacto de origen.
    assert "minus_zero" in anexo_c_eda
    assert "default_rate" in anexo_c_eda

    # El cuerpo NO repite el dump: lleva prosa y las tablas que importan.
    assert "El modelo final incluye 2 variables." in resultados_modelo
    assert "<h4>Parámetros y payload</h4>" not in resultados_modelo


def test_las_tablas_por_observacion_salen_del_documento_y_se_referencian() -> None:
    """El dataset no es el informe: las tablas por observación salen y el anexo dice dónde están.

    Cinco tablas por observación (puntaje, PD cruda, PD calibrada y los dos frames WoE) ocupaban
    **1.005 de las 1.510 filas** del informe, truncadas a 200: no servían ni como dato (incompletas)
    ni como informe (ruido). Salen del documento y se entregan completas como adjuntos.
    """
    score = pd.DataFrame(
        {"score": [640, 712], "pd_calibrated": [0.08, 0.03]},
        index=pd.Index(["op-000", "op-001"], name="loan_id"),
    )
    bundle = _bundle(tables={**_tables(), "scorecard.score": score})

    sin_export = _renderer(ReportConfig(formats=("html",))).render(bundle)
    con_export = _renderer(ReportConfig(formats=("html", "csv"))).render(bundle)

    # La tabla por observación no se renderiza en ninguna sección, ni en el anexo.
    assert 'data-table-key="scorecard.score"' not in sin_export
    assert 'data-table-key="scorecard.score"' not in con_export

    # Pedida como export: el documento la nombra y dice en qué archivo va, con su tamaño REAL.
    assert "scorecard_report__scorecard_score.csv" in con_export
    assert "Puntaje por observación" in con_export

    # Sin export: el documento declara que existe y que NO se emitió; no la calla ni la inventa.
    assert "no se exportaron" in sin_export
    assert "scorecard_report__scorecard_score.csv" not in sin_export


def test_plantilla_y_css_empaquetados_en_el_paquete() -> None:
    """Plantilla, parciales y ambos CSS viven en el paquete (blindaje del wheel).

    La plantilla dejó de ser un monolito: si un parcial no se empaqueta, el render revienta en
    producción con un ``TemplateNotFound`` que los tests locales (que leen del árbol de fuentes) no
    verían. De ahí que la lista sea explícita.
    """
    from importlib import resources

    root = resources.files("nikodym.report.templates")
    for nombre in (
        "scorecard_report.html.j2",
        "_base.html.j2",
        "_cover.html.j2",
        "_exec_summary.html.j2",
        "_toc.html.j2",
        "_prose_section.html.j2",
        "_data_section.html.j2",
        "_appendix.html.j2",
        "_placeholder.html.j2",
        "_narration.html.j2",
        "_tables.html.j2",
        "scorecard_report.css",
        "scorecard_report_plain.css",
    ):
        assert root.joinpath(nombre).is_file(), nombre


def test_truncado_bloques_ia_y_write_manifest(tmp_path: Path) -> None:
    """Tablas grandes muestran indicador; ``write`` calcula manifest desde bytes reales."""
    renderer = _renderer(
        ReportConfig(
            ai=AiNarrationConfig(enabled=True, provider="anthropic", label_ai_text=True),
            sections=SectionPolicyConfig(max_table_rows=10),
        )
    )
    bundle = _bundle()
    ai_block = _ai_block()
    html = renderer.render(bundle, ai_blocks=(ai_block,))
    manifest = renderer.write(html, output_dir=str(tmp_path))
    output = tmp_path / "scorecard_report.html"

    assert "… (mostrando 10 de 12 filas)" in html
    assert "Narrativa generada por IA" in html
    assert ai_block.text in html
    assert output.read_bytes() == html.encode("utf-8")
    assert manifest.sha256 == renderer_module._digest_html(output.read_text(encoding="utf-8"))
    assert manifest.created_from_lineage_at == _lineage().created_at.isoformat()
    assert manifest.path == "scorecard_report.html"
    assert manifest.output_format == "html"
    assert manifest.deterministic is False
    assert manifest.ai_enabled is True
    assert manifest.ai_used is True
    assert tuple(section.id for section in manifest.sections) == _CANONICAL_IDS
    assert manifest.report_id == "45760c500091db31"


def test_write_relativo_y_errores_de_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Export falla ruidosamente antes del archivo final si permisos o escritura fallan."""
    renderer = _renderer()
    html = renderer.render(_bundle())

    monkeypatch.chdir(tmp_path)
    manifest = renderer.write(html, output_dir="reports")
    assert manifest.path == "reports/scorecard_report.html"

    not_rendered = _renderer()
    with pytest.raises(ReportExportError, match="render"):
        not_rendered.write(html, output_dir=str(tmp_path))

    monkeypatch.setattr(renderer_module.os, "access", lambda path, mode: False)
    with pytest.raises(ReportExportError, match="no es escribible"):
        renderer.write(html, output_dir=str(tmp_path / "bloqueado"))
    monkeypatch.setattr(renderer_module.os, "access", lambda path, mode: True)

    original_mkdir = renderer_module.Path.mkdir

    def fail_mkdir(self: Path, *, parents: bool, exist_ok: bool) -> None:
        del self, parents, exist_ok
        raise OSError("mkdir denegado")

    monkeypatch.setattr(renderer_module.Path, "mkdir", fail_mkdir)
    with pytest.raises(ReportExportError, match="crear el directorio"):
        renderer.write(html, output_dir=str(tmp_path / "sin_padre"))
    monkeypatch.setattr(renderer_module.Path, "mkdir", original_mkdir)

    def fail_write(self: Path, data: bytes) -> int:
        del self, data
        raise OSError("write denegado")

    monkeypatch.setattr(renderer_module.Path, "write_bytes", fail_write)
    with pytest.raises(ReportExportError, match="No se pudo escribir"):
        renderer.write(html, output_dir=str(tmp_path))


def test_pdf_render_deshabilitado_y_degradacion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """PDF deshabilitado escribe solo HTML; habilitado sin WeasyPrint degrada o falla.

    Los modos que exigen WeasyPrint real (PDF válido en disco) viven en ``test_report_pdf.py`` con
    ``skipif``; aquí se cubre la ausencia de la dependencia bloqueando su import.
    """
    bundle = _bundle()
    default_pdf = PdfReportRenderer()
    from_config_pdf = PdfReportRenderer.from_config(ReportConfig())

    assert default_pdf.config == ReportConfig()
    assert from_config_pdf.config == ReportConfig()

    # (i) Deshabilitado: escribe HTML y devuelve su manifest, sin tocar el PDF.
    disabled = PdfReportRenderer(ReportConfig(pdf=PdfRenderConfig(enabled=False)))
    disabled_manifest = disabled.render(bundle, output_dir=str(tmp_path / "disabled"))
    assert disabled_manifest.output_format == "html"
    assert (tmp_path / "disabled" / "scorecard_report.html").is_file()
    assert not (tmp_path / "disabled" / "scorecard_report.pdf").exists()

    # Bloquea el import de weasyprint para forzar la ausencia de la dependencia opcional.
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "weasyprint":
            raise ModuleNotFoundError("weasyprint")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # (ii) Habilitado sin WeasyPrint + fail_if_unavailable=False → RuntimeWarning + HTML intacto.
    fallback = PdfReportRenderer(
        ReportConfig(pdf=PdfRenderConfig(enabled=True, fail_if_unavailable=False))
    )
    with pytest.warns(RuntimeWarning, match="WeasyPrint no está disponible"):
        fallback_manifest = fallback.render(bundle, output_dir=str(tmp_path / "fallback"))
    assert fallback_manifest.output_format == "html"
    assert (tmp_path / "fallback" / "scorecard_report.html").is_file()
    assert not (tmp_path / "fallback" / "scorecard_report.pdf").exists()

    # (iii) Habilitado sin WeasyPrint + fail_if_unavailable=True → re-lanza la dependencia ausente.
    # Construido desde ``PdfRenderConfig`` directo (constructor alternativo).
    strict_pdf = PdfRenderConfig(enabled=True, fail_if_unavailable=True)
    strict = PdfReportRenderer(strict_pdf)
    assert strict.config == ReportConfig(pdf=strict_pdf)
    with pytest.raises(ReportDependencyError, match="WeasyPrint"):
        strict.render(bundle, output_dir=str(tmp_path / "strict"))


def test_render_errores_dependencia_jinja_template_y_tabla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errores de dependencia, plantilla y tabla se traducen a excepciones propias."""
    renderer = _renderer()
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "jinja2":
            raise ModuleNotFoundError("jinja2")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ReportDependencyError, match="Jinja2"):
        renderer.render(_bundle())
    monkeypatch.setattr(builtins, "__import__", real_import)

    original_loader = renderer_module._load_template

    def broken_template(environment: Any) -> Any:
        # Simula una plantilla rota: `from_string` compila y lanza TemplateSyntaxError, que el
        # renderer debe traducir a ReportRenderError con mensaje claro sobre la plantilla.
        return environment.from_string("{% if")

    monkeypatch.setattr(renderer_module, "_load_template", broken_template)
    with pytest.raises(ReportRenderError, match="plantilla"):
        renderer.render(_bundle())
    monkeypatch.setattr(renderer_module, "_load_template", original_loader)

    with pytest.raises(ReportRenderError, match="Tabla no renderizable"):
        renderer.render(_bundle(tables={"model.bad": object()}))


def test_constructores_helpers_y_reexports_livianos_por_subprocess() -> None:
    """Constructores alternativos y helpers preservan formato estable e import liviano."""
    assert HtmlReportRenderer().config == ReportConfig()
    assert HtmlReportRenderer(None, basename="custom").config.basename == "custom"
    assert HtmlReportRenderer(HtmlRenderConfig()).config.html == HtmlRenderConfig()

    html_cfg = HtmlRenderConfig(theme="plain", deterministic_ids=False)
    renderer = HtmlReportRenderer(
        html_cfg,
        basename="otro",
        sections=SectionPolicyConfig(max_table_rows=10),
        ai=AiNarrationConfig(label_ai_text=False),
    )
    html = renderer.render(_bundle(figures={"eda.figures": MiniFigure(figure_id="a", title="A")}))

    assert "font-family:Arial" in html
    assert "figure-eda-figures" in html
    assert "MiniFigure" not in html
    assert report_pkg.HtmlReportRenderer is HtmlReportRenderer
    assert report_pkg.PdfReportRenderer is PdfReportRenderer

    assert renderer_module._display_scalar(None, key_path=("x",)) == "No disponible"
    assert renderer_module._display_scalar(True, key_path=("x",)) == "true"
    assert renderer_module._display_scalar(7, key_path=("x",)) == "7"
    assert renderer_module._display_scalar({"b": 2, "a": -0.0}, key_path=("x",)) == (
        '{\n  "a": "0.000000",\n  "b": 2\n}'
    )
    assert renderer_module._display_value({"z", "a"}, key_path=("set",)) == ('[\n  "a",\n  "z"\n]')
    assert renderer_module._display_scalar(MiniFigure(figure_id="m", title="T"), key_path=("m",))
    assert renderer_module._display_scalar([1, 2], key_path=("lista",)) == "[\n  1,\n  2\n]"
    assert renderer_module._display_value(FrameLike(), key_path=("frame",)) == (
        "[tabla referenciada]"
    )
    assert renderer_module._display_json_value(
        {"nested": {"x": 1.2}},
        key_path=("root",),
    ) == {"nested": {"x": "1.200000"}}
    assert renderer_module._display_json_value([1, -0.0], key_path=("list",)) == [
        1,
        "0.000000",
    ]
    assert renderer_module._display_json_value({"b", "a"}, key_path=("set",)) == ["a", "b"]
    assert renderer_module._display_json_value(
        MiniFigure(figure_id="m", title="T"),
        key_path=("model",),
    ) == {"figure_id": "m", "title": "T"}
    assert renderer_module._display_json_value(FrameLike(), key_path=("frame",)) == (
        "[tabla referenciada]"
    )
    assert renderer_module._display_json_value(False, key_path=("bool",)) is False
    assert renderer_module._display_json_value(None, key_path=("none",)) is None
    assert renderer_module._display_json_value("texto", key_path=("str",)) == "texto"
    assert renderer_module._display_json_value(object(), key_path=("obj",)) == {
        "unsupported_type": "object"
    }
    assert renderer_module._table_view("x.frame", FrameLike(), max_rows=10)["rows"] == [
        ("0.000000",)
    ]
    assert renderer_module._format_float(float("nan"), key_path=("x",)) == "nan"
    assert renderer_module._format_float(float("inf"), key_path=("x",)) == "inf"
    assert renderer_module._format_float(float("-inf"), key_path=("x",)) == "-inf"
    assert renderer_module._stable_json({"b": -0.0, "a": object()}) == (
        '{"a":{"unsupported_type":"object"},"b":0.0}'
    )
    assert renderer_module._canonical_value((1, -0.0)) == [1, 0.0]
    assert renderer_module._canonical_value({"z", "a"}) == ["a", "z"]
    assert renderer_module._canonical_value(False) is False
    assert renderer_module._canonical_value(5) == 5
    assert renderer_module._canonical_value(1.25) == 1.25
    assert renderer_module._canonical_value(float("nan")) == {"non_finite_float": "nan"}
    assert renderer_module._canonical_value(float("inf")) == {"non_finite_float": "inf"}
    assert renderer_module._canonical_value(float("-inf")) == {"non_finite_float": "-inf"}
    assert renderer_module._normalize_newlines("a\r\nb") == "a\nb\n"
    assert renderer_module._element_id("section", "  !!!  ") == "section-sin-id"
    assert (
        renderer_module._section_views(
            _bundle(tables={}, figures={}, sections_override=(_section("lineage", "Lineage"),)),
            (),
            ReportConfig(),
        )[0]["id"]
        == "lineage"
    )

    code = (
        "import sys;"
        "import nikodym.report as report;"
        "blocked=[m for m in ('jinja2','matplotlib','plotly','anthropic') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert report.HtmlReportRenderer.__name__ == 'HtmlReportRenderer';"
        "blocked=[m for m in ('jinja2','matplotlib','plotly','anthropic') if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_digest_html_excluye_los_bytes_svg() -> None:
    """``_digest_html`` iguala HTML que sólo difieren dentro de ``<svg>`` (cross-OS)."""
    base = (
        "<html><body>"
        '<figure><svg width="1" xmlns="x"><title>A</title><path d="M0 0"/></svg></figure>'
        '<figure><svg viewBox="0 0 2 2"><rect/></svg></figure>'
        "</body></html>"
    )
    other = (
        "<html><body>"
        '<figure><svg width="999" data-z="q"><title>B</title><rect x="7"/></svg></figure>'
        '<figure><svg viewBox="0 0 9 9"><circle/></svg></figure>'
        "</body></html>"
    )
    assert renderer_module._digest_html(base) == renderer_module._digest_html(other)

    # Sin SVG, el digest es el sha256 del HTML normalizado (con salto final garantizado).
    no_svg = "<html><body><p>hola</p></body></html>"
    assert (
        renderer_module._digest_html(no_svg)
        == hashlib.sha256((no_svg + "\n").encode("utf-8")).hexdigest()
    )
    # Cambiar contenido FUERA del SVG sí mueve el digest.
    assert renderer_module._digest_html(base) != renderer_module._digest_html(
        base.replace("<body>", "<body><p>fuera</p>")
    )


@pytest.mark.skipif(not _HAS_MATPLOTLIB, reason="requiere el extra report (matplotlib)")
def test_charts_embebidos_con_bundle_rico_del_fixture() -> None:
    """Bundle rico (datos del fixture real) embebe los 5 gráficos con digest estable."""
    bundle = _bundle(tables=_rich_tables_desde_fixture())
    renderer = _renderer()

    first = renderer.render(bundle)
    second = renderer.render(bundle)

    assert first.count("<svg") >= 5
    for chart_id in (
        "chart-performance-gains",
        "chart-performance-discrimination",
        "chart-model-coefficients",
        "chart-stability-stability",
        "chart-calibration-reliability",
    ):
        assert f'id="{chart_id}"' in first
    # Los gráficos viven dentro de la subsección de Resultados de su dominio, no en otra.
    performance_section = _section_fragment(first, "results.performance")
    assert 'id="chart-performance-gains"' in performance_section
    assert 'id="chart-performance-discrimination"' in performance_section
    assert renderer_module._digest_html(first) == renderer_module._digest_html(second)


def test_charts_degradan_con_gracia_sin_crashear() -> None:
    """``render_charts=False`` y tablas incompletas producen 0 gráficos sin romper el render."""
    disabled = HtmlReportRenderer.from_config(
        ReportConfig(
            html=HtmlRenderConfig(render_charts=False),
            sections=SectionPolicyConfig(max_table_rows=10),
        )
    )
    html_off = disabled.render(_bundle())
    assert 'id="chart-' not in html_off

    renderer = _renderer()
    incompleto = renderer.render(
        _bundle(tables={"performance.performance_table": pd.DataFrame({"decile": [1, 2]})})
    )
    assert 'id="chart-' not in incompleto
    assert "report-section" in incompleto


def _section_fragment(html: str, section_id: str) -> str:
    """Extrae el ``<section>`` de una sección concreta para asserts de pertenencia."""
    start = html.index(f'data-section-id="{section_id}"')
    end = html.index("</section>", start) + len("</section>")
    return html[start:end]


def _fixture_results() -> dict[str, Any]:
    """Carga el fixture de una corrida REAL usado por el preview/demo del front."""
    path = (
        Path(__file__).resolve().parents[2] / "web" / "src" / "fixtures" / "demo" / "results.json"
    )
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _rich_tables_desde_fixture() -> dict[str, pd.DataFrame]:
    """Tablas de gráficos con columnas y valores del fixture real (SDD-26 B3).

    El fixture UI expone la reliability ya DERIVADA pero no el ``calibrated_pd_frame`` crudo que el
    renderer consume; para el slot de confiabilidad se sintetiza un frame determinista mínimo.
    """
    data = _fixture_results()
    return {
        "performance.performance_table": pd.DataFrame(data["performance"]["deciles"]),
        "performance.discriminant_metrics": pd.DataFrame(data["performance"]["discriminant"]),
        "model.coefficients": pd.DataFrame(data["model"]["coefficients"]),
        "stability.stability_metrics": pd.DataFrame(data["stability"]["stability_metrics"]),
        "calibration.calibrated_pd_frame": _calibrated_pd_frame_sintetico(),
    }


def _calibrated_pd_frame_sintetico() -> pd.DataFrame:
    """Frame calibrado determinista (partition/target/pd_calibrated) para el slot de reliability."""
    rows: list[dict[str, Any]] = []
    for partition in ("desarrollo", "holdout", "oot"):
        for index in range(40):
            rows.append(
                {
                    "partition": partition,
                    "pd_calibrated": (index + 1) / 50.0,
                    "target": 1 if index % 3 == 0 else 0,
                }
            )
    return pd.DataFrame(rows)


def _renderer(config: ReportConfig | None = None) -> HtmlReportRenderer:
    """Construye renderer HTML con límite de tablas usado por el golden."""
    return HtmlReportRenderer.from_config(
        config or ReportConfig(sections=SectionPolicyConfig(max_table_rows=10))
    )


def _bundle_con_cards() -> ReportInputBundle:
    """Bundle con las cards reales que alimentan el semáforo del resumen ejecutivo."""
    bundle = _bundle()
    return bundle.model_copy(
        update={
            "cards": {
                "performance": {
                    "partitions": ("desarrollo",),
                    "max_metrics_by_partition": {
                        "desarrollo": {"auc": 0.74321, "gini": 0.48642, "ks": 0.31234}
                    },
                    "bands_by_partition": {"desarrollo": "ok"},
                    "thresholds": {},
                },
            }
        }
    )


def _table_fragment(html: str, table_id: str) -> str:
    """Extrae una tabla concreta para asserts de orden semántico."""
    start = html.index(f'<table id="{table_id}"')
    end = html.index("</table>", start) + len("</table>")
    return html[start:end]


def _lineage() -> LineageBundle:
    """Lineage fijo para el reporte sintético."""
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123456789abcdef",
        config_hash="cfg123456789abcdef",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "0.1.0", "pandas": "2.2.0"},
        determinism_caveats=["fixture controlado"],
        created_at=datetime(2026, 6, 24, 9, 30, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _bundle(
    *,
    tables: dict[str, Any] | None = None,
    figures: dict[str, Any] | None = None,
    sections_override: tuple[ReportSection, ...] | None = None,
) -> ReportInputBundle:
    """Documento sintético completo, con las secciones en orden intencionalmente desordenado."""
    lineage = _lineage()
    sections = (
        _section("results.performance", "Desempeño y discriminación", level=2, number="4.6"),
        _section("toc", "Índice", kind="toc", domain="report"),
        _section(
            "appendix_parameters.performance",
            "Desempeño y discriminación",
            kind="appendix",
            level=2,
            number="C.6",
            metric_sections={"auc": 0.74321, "ks": 0.31234},
        ),
        _section(
            "context",
            "Contexto del modelo y de la cartera",
            kind="prose",
            number="2",
            domain="report",
            body=("La tasa de incumplimiento observada es de 12.35 %.",),
            placeholder=PlaceholderBlock(
                title="Contexto del modelo",
                guidance=("Describe la cartera: producto, segmento, volumen y período.",),
            ),
        ),
        _section("methodology", "Metodología", kind="prose", number="3", domain="report"),
        _section(
            "methodology.binning",
            "Binning WoE",
            kind="prose",
            level=2,
            number="3.2",
            body=("Se discretizó cada variable con OptBinning.",),
        ),
        _section("results", "Resultados", kind="prose", number="4", domain="report"),
        _section("results.selection", "Selección de variables", level=2, status="missing"),
        _section(
            "results.model",
            "Modelo PD",
            level=2,
            number="4.3",
            body=("El modelo final incluye 2 variables.",),
        ),
        _section("results.stability", "Estabilidad", level=2, number="4.7"),
        _section("results.calibration", "Calibración", level=2, number="4.5"),
        _section(
            "appendix_parameters.eda",
            "Población y calidad de datos",
            kind="appendix",
            level=2,
            number="C.1",
            payload={"default_rate": 0.123456, "minus_zero": -0.0},
        ),
        _section(
            "limitations",
            "Limitaciones y supuestos",
            kind="prose",
            number="6",
            domain="report",
            payload={"missing_sections": ("selection",)},
            body=("Secciones obligatorias ausentes en esta corrida: selection.",),
        ),
        _section(
            "appendix_lineage",
            "Lineage y reproducibilidad",
            kind="appendix",
            number="A",
            domain="report",
            payload=lineage.model_dump(mode="json"),
        ),
        _section(
            "appendix_tables",
            "Tablas detalladas",
            kind="appendix",
            number="B",
            domain="report",
            payload={"table_keys": ("performance.performance_table", "model.coefficients")},
        ),
        _section(
            "appendix_parameters",
            "Parámetros completos",
            kind="appendix",
            number="C",
            domain="report",
        ),
    )
    return ReportInputBundle(
        lineage=lineage,
        cards={"model": {"selected_features": ("saldo", "mora")}},
        tables=_tables() if tables is None else tables,
        figures={"eda.figures": MiniFigure(figure_id="default_rate", title="Default rate")}
        if figures is None
        else figures,
        sections=sections if sections_override is None else sections_override,
        missing_sections=("selection",),
    )


def _section(
    section_id: str,
    title: str,
    *,
    status: str = "included",
    kind: str = "data",
    level: int = 1,
    number: str = "",
    domain: str | None = None,
    payload: dict[str, Any] | None = None,
    metric_sections: dict[str, Any] | None = None,
    body: tuple[str, ...] = (),
    placeholder: PlaceholderBlock | None = None,
) -> ReportSection:
    """Sección sintética del documento; el dominio se deriva del id salvo que se fije."""
    source_domain = domain if domain is not None else (section_id.partition(".")[2] or "report")
    return ReportSection(
        id=section_id,
        title=title,
        status=status,  # type: ignore[arg-type]
        source_domain=source_domain,
        source_key="card",
        payload={} if payload is None else payload,
        metric_sections={} if metric_sections is None else metric_sections,
        kind=kind,  # type: ignore[arg-type]
        level=level,
        number=number,
        body=body,
        placeholder=placeholder,
    )


def _tables() -> dict[str, pd.DataFrame]:
    """Tablas sintéticas, incluyendo una más grande que ``max_table_rows``."""
    return {
        "performance.performance_table": pd.DataFrame(
            {
                "decile": list(range(12, 0, -1)),
                "pd": [index / 1000 for index in range(12)],
                "default_rate": [index / 100 for index in range(12)],
            }
        ),
        "model.coefficients": pd.DataFrame(
            {
                "feature": ["mora", "saldo"],
                "beta": [-0.0, 1.25],
                "p_value": [0.04, 0.03],
            }
        ),
    }


def _ai_block() -> AiNarrationBlock:
    """Bloque IA generado para verificar etiqueta visible y manifest."""
    return AiNarrationBlock(
        section_id="results.performance",
        text="Narrativa controlada para desempeño.",
        provider="anthropic",
        model="modelo-test",
        generated=True,
        prompt_hash="0" * 64,
        input_payload_hash="1" * 64,
        warning=None,
    )


# Orden canónico del DOCUMENTO (fuente única: nikodym.report.document), no del pipeline.
_CANONICAL_IDS = (
    "toc",
    "context",
    "methodology",
    "methodology.binning",
    "results",
    "results.selection",
    "results.model",
    "results.calibration",
    "results.performance",
    "results.stability",
    "limitations",
    "appendix_lineage",
    "appendix_tables",
    "appendix_parameters",
    "appendix_parameters.eda",
    "appendix_parameters.performance",
)
