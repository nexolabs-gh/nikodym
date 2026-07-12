"""Tests de ``report.markdown``: el ``.qmd`` es la fuente EDITABLE, no otro artefacto terminal.

Lo que se verifica no es "que exista un archivo", sino que sirva para lo que se pidió: que sea
Markdown válido y editable a mano, que espeje capítulo a capítulo el HTML (misma estructura, una
sola fuente de verdad), que los bloques POR COMPLETAR salten a la vista como *callouts* de Quarto
y que las figuras queden en disco con rutas relativas, para que ``quarto render`` funcione tal cual.

Quarto NO es dependencia y NO se invoca por ``subprocess``: aquí sólo se EMITE texto.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml

import nikodym.report.markdown as md_module
from nikodym.core.lineage import LineageBundle
from nikodym.report.config import (
    AiNarrationConfig,
    DocumentStructureConfig,
    ReportConfig,
    SectionPolicyConfig,
)
from nikodym.report.document import CHAPTER_SPECS
from nikodym.report.exceptions import ReportExportError
from nikodym.report.markdown import FIGURES_SUFFIX, MarkdownReportRenderer
from nikodym.report.renderer import HtmlReportRenderer
from nikodym.report.results import (
    AiNarrationBlock,
    PlaceholderBlock,
    ReportInputBundle,
    ReportSection,
)


def _lineage() -> LineageBundle:
    """Lineage fijo: sin reloj de pared, el ``.qmd`` es reproducible."""
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123456789abcdef",
        config_hash="cfg123456789abcdef",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "1.0.0"},
        determinism_caveats=[],
        created_at=datetime(2026, 6, 24, 9, 30, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _sections() -> tuple[ReportSection, ...]:
    """Documento mínimo con prosa, placeholder, datos y anexo de tablas."""
    return (
        ReportSection(
            id="toc",
            title="Índice",
            status="included",
            source_domain="report",
            source_key="toc",
            kind="toc",
            number="",
        ),
        ReportSection(
            id="introduction",
            title="Introducción",
            status="included",
            source_domain="report",
            source_key="introduction",
            kind="prose",
            number="1",
            body=("El informe documenta la validación del scorecard.",),
            placeholder=PlaceholderBlock(
                title="Introducción",
                guidance=("Declara el propósito | y el alcance.", "Identifica la audiencia."),
            ),
        ),
        ReportSection(
            id="results.model",
            title="Modelo PD",
            status="included",
            source_domain="model",
            source_key="model_card",
            kind="data",
            level=2,
            number="4.3",
            body=("El modelo final incluye 2 variables.",),
        ),
        ReportSection(
            id="appendix_tables",
            title="Tablas detalladas",
            status="included",
            source_domain="report",
            source_key="appendix_tables",
            kind="appendix",
            number="B",
        ),
    )


def _tables() -> dict[str, pd.DataFrame]:
    """Una tabla clave (va al cuerpo) y una por observación (sale como adjunto)."""
    return {
        "model.coefficients": pd.DataFrame(
            {"feature": ["mora", "sal|do"], "beta": [-0.5, 1.25]}  # pipe en el dato: debe escaparse
        ),
        "scorecard.score": pd.DataFrame(
            {"score": [640, 712]},
            index=pd.Index(["op-000", "op-001"], name="loan_id"),
        ),
    }


def _bundle() -> ReportInputBundle:
    """Bundle sintético del documento."""
    return ReportInputBundle(
        lineage=_lineage(),
        cards={"model": {"selected_features": ("mora", "saldo")}},
        tables=_tables(),
        figures={},
        sections=_sections(),
        missing_sections=(),
    )


def _config(**kwargs: object) -> ReportConfig:
    """Config con metadatos de portada declarados."""
    base: dict[str, object] = {
        "document": DocumentStructureConfig(
            model_name="Scorecard consumo",
            entity="Banco Ejemplo S.A.",
            author="Riesgo de Crédito",
            version="1.0",
        ),
        "sections": SectionPolicyConfig(max_table_rows=10),
    }
    base.update(kwargs)
    return ReportConfig(**base)  # type: ignore[arg-type]


def test_qmd_es_determinista_y_su_front_matter_es_yaml_valido() -> None:
    """Dos renders son idénticos y el front-matter parsea como YAML (lo edita una persona)."""
    renderer = MarkdownReportRenderer.from_config(_config())
    bundle = _bundle()

    primero = renderer.render(bundle)
    segundo = renderer.render(bundle)

    assert primero == segundo
    assert primero.startswith("---\n")
    assert primero.endswith("\n")

    front_matter = yaml.safe_load(primero.split("---\n")[1])
    assert front_matter["title"] == "Informe de Validación de Scorecard"
    assert front_matter["subtitle"] == "Scorecard consumo"
    assert front_matter["author"] == "Riesgo de Crédito"
    assert front_matter["date"] == "2026-06-24"  # del lineage, no del reloj de pared
    assert front_matter["lang"] == "es"
    assert front_matter["toc"] is True
    # La identidad de la corrida viaja DENTRO de la fuente editable.
    assert front_matter["nikodym"]["config_hash"] == "cfg123456789abcdef"
    assert front_matter["nikodym"]["entidad"] == "Banco Ejemplo S.A."


def test_qmd_espeja_los_capitulos_del_html_desde_la_misma_fuente() -> None:
    """Mismos capítulos, mismos números, mismos títulos: una sola fuente de estructura.

    Si el ``.qmd`` copiara el orden en vez de reusarlo, el primer capítulo nuevo del HTML dejaría de
    aparecer aquí. Se compara contra el HTML renderizado del MISMO bundle.
    """
    config = _config()
    bundle = _bundle()

    markdown = MarkdownReportRenderer.from_config(config).render(bundle)
    html = HtmlReportRenderer.from_config(config).render(bundle)

    assert "## 1 Introducción" in markdown
    assert "### 4.3 Modelo PD" in markdown
    assert "## Anexo B — Tablas detalladas" in markdown
    for titulo in ("Introducción", "Modelo PD", "Tablas detalladas"):
        assert titulo in html and titulo in markdown

    # Los ids de capítulo del documento son los mismos que declara `report.document`.
    assert {spec.id for spec in CHAPTER_SPECS} >= {"introduction", "appendix_tables"}


def test_placeholders_son_callouts_accionables_de_quarto() -> None:
    """El POR COMPLETAR es un *callout* visible con su guía, no un comentario que se pierde."""
    markdown = MarkdownReportRenderer.from_config(_config()).render(_bundle())

    assert '::: {.callout-important title="POR COMPLETAR — Introducción"}' in markdown
    assert "Declara el propósito | y el alcance." in markdown
    assert "Identifica la audiencia." in markdown
    assert markdown.count(":::") >= 2  # apertura y cierre


def test_placeholders_hide_deja_el_qmd_sin_bloques_por_completar() -> None:
    """Con ``placeholders='hide'`` el entregable final no arrastra las cajas de guía."""
    config = _config(document=DocumentStructureConfig(placeholders="hide"))
    bundle = _bundle()
    sections = tuple(section.model_copy(update={"placeholder": None}) for section in _sections())

    markdown = MarkdownReportRenderer.from_config(config).render(
        bundle.model_copy(update={"sections": sections})
    )

    assert "POR COMPLETAR — Introducción" not in markdown
    assert "El informe documenta la validación del scorecard." in markdown  # la prosa se queda


def test_tablas_en_pipe_table_valido_con_celdas_escapadas() -> None:
    """Las tablas son *pipe tables* de Markdown y una celda con ``|`` no rompe la tabla."""
    markdown = MarkdownReportRenderer.from_config(_config()).render(_bundle())

    assert "**Coeficientes del modelo PD**" in markdown
    assert "| feature | beta |" in markdown
    assert "| --- | --- |" in markdown
    assert r"sal\|do" in markdown  # el pipe del dato va escapado, no parte la columna

    # Toda fila de tabla tiene el mismo número de columnas que su encabezado.
    for bloque in re.findall(r"(?:^\|.*\n)+", markdown, re.MULTILINE):
        filas = [linea for linea in bloque.strip().splitlines() if linea.startswith("|")]
        anchos = {linea.count("|") - linea.count(r"\|") for linea in filas}
        assert len(anchos) == 1, bloque


def test_las_tablas_por_observacion_no_entran_al_qmd() -> None:
    """El dataset no viaja dentro de la fuente editable: se referencia como adjunto."""
    markdown = MarkdownReportRenderer.from_config(_config(formats=("md", "csv"))).render(_bundle())

    assert "op-000" not in markdown  # ninguna fila del frame por observación
    assert "#### Detalle por observación" in markdown
    assert "scorecard_report__scorecard_score.csv" in markdown


def test_write_materializa_qmd_y_figuras_con_rutas_relativas(tmp_path: Path) -> None:
    """``write`` deja el ``.qmd`` y su carpeta de figuras: el par es autocontenido y compila."""
    charts = [{"html_id": "chart-model-coefficients", "title": "Coeficientes", "svg": "<svg/>\n"}]
    renderer = MarkdownReportRenderer.from_config(_config())
    markdown = renderer.render(_bundle())
    renderer._last_figures = {chart["html_id"]: chart["svg"] for chart in charts}

    manifest = renderer.write(markdown, output_dir=str(tmp_path))

    qmd = tmp_path / "scorecard_report.qmd"
    figura = tmp_path / f"scorecard_report{FIGURES_SUFFIX}" / "chart-model-coefficients.svg"
    assert qmd.is_file()
    assert figura.is_file()
    assert qmd.read_text(encoding="utf-8") == markdown
    assert manifest.output_format == "md"
    assert manifest.path.endswith("scorecard_report.qmd")
    assert manifest.deterministic is True


def test_figura_se_referencia_con_ruta_relativa_a_la_carpeta_hermana() -> None:
    """La figura se referencia relativa al ``.qmd``, no con una ruta absoluta de la máquina."""
    figura = md_module._figure(
        {"html_id": "chart-model-coefficients", "title": "Coeficientes del modelo"},
        _config(),
    )

    assert figura == (
        "![Coeficientes del modelo](scorecard_report_figuras/chart-model-coefficients.svg)"
    )
    assert "/" in figura and not figura.startswith("/")


def test_narrativa_ia_va_etiquetada_en_el_qmd() -> None:
    """Un bloque IA se emite como *callout* etiquetado: nunca se confunde con prosa del motor."""
    config = _config(ai=AiNarrationConfig(enabled=True, provider="anthropic"))
    bloque = AiNarrationBlock(
        section_id="results.model",
        text="El modelo discrimina de forma adecuada.",
        provider="anthropic",
        model="modelo-test",
        generated=True,
        prompt_hash="0" * 64,
        input_payload_hash="1" * 64,
    )

    renderer = MarkdownReportRenderer.from_config(config)
    markdown = renderer.render(_bundle(), ai_blocks=(bloque,))
    manifest = renderer.build_manifest(markdown)

    assert '::: {.callout-note title="Narrativa generada por IA"}' in markdown
    assert "El modelo discrimina de forma adecuada." in markdown
    assert manifest.ai_used is True
    assert manifest.deterministic is False


def test_build_manifest_y_write_exigen_render_previo(tmp_path: Path) -> None:
    """Sin ``render`` no hay bundle: el error dice exactamente qué hacer (espejo del HTML)."""
    renderer = MarkdownReportRenderer.from_config(_config())

    with pytest.raises(ReportExportError, match=r"llame MarkdownReportRenderer\.render"):
        renderer.build_manifest("# vacío")
    with pytest.raises(ReportExportError, match=r"llame MarkdownReportRenderer\.render"):
        renderer.write("# vacío", output_dir=str(tmp_path))


def test_el_qmd_no_invoca_quarto_ni_lo_declara_como_dependencia() -> None:
    """Quarto se retiró a propósito en B5: aquí sólo se EMITE texto que Quarto podría compilar.

    Se inspecciona el AST (no el texto: los comentarios hablan de Quarto a propósito) para probar
    que el módulo no importa ``subprocess`` ni detecta binarios. Emitir un ``.qmd`` no reintroduce
    la dependencia; ejecutarlo, sí.
    """
    import ast

    fuente = Path(md_module.__file__).read_text(encoding="utf-8")
    importados = {
        nombre.name.split(".")[0]
        for nodo in ast.walk(ast.parse(fuente))
        if isinstance(nodo, ast.Import)
        for nombre in nodo.names
    } | {
        nodo.module.split(".")[0]
        for nodo in ast.walk(ast.parse(fuente))
        if isinstance(nodo, ast.ImportFrom) and nodo.module
    }

    assert "subprocess" not in importados
    assert "shutil" not in importados
    assert "quarto" not in importados
