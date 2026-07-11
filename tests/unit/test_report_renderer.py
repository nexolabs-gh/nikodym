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
from nikodym.report.results import AiNarrationBlock, ReportInputBundle, ReportSection

# Golden del ``_digest_html`` (excluye los bytes ``<svg>``, ver renderer): con el extra ``report``
# el bundle golden embebe un único gráfico (forest de coeficientes) cuyo slot cuenta en el digest.
GOLDEN_HTML_SHA256 = "1c8cbdb63f127052287cb92deb29d60ba1de45e596ebcdbb0443a7dc59c80442"

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
    """El HTML básico queda byte-idéntico y sigue el orden canónico."""
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


def test_plantilla_y_css_empaquetados_en_el_paquete() -> None:
    """La plantilla editorial y ambos CSS viven en el paquete (blindaje del wheel)."""
    from importlib import resources

    root = resources.files("nikodym.report.templates")
    assert root.joinpath("scorecard_report.html.j2").is_file()
    assert root.joinpath("scorecard_report.css").is_file()
    assert root.joinpath("scorecard_report_plain.css").is_file()


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
    # Los gráficos viven dentro de la sección esperada, no en otra.
    performance_section = _section_fragment(first, "performance")
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


def _table_fragment(html: str, table_id: str) -> str:
    """Extrae una tabla concreta para asserts de orden semántico."""
    start = html.index(f'<table id="{table_id}">')
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
    """Bundle completo con secciones en orden intencionalmente desordenado."""
    lineage = _lineage()
    sections = (
        _section("performance", "Desempeño", metric_sections={"auc": 0.74321, "ks": 0.31234}),
        _section("lineage", "Lineage", payload=lineage.model_dump(mode="json")),
        _section("eda", "EDA", payload={"default_rate": 0.123456, "minus_zero": -0.0}),
        _section("binning", "Binning WoE", metric_sections={"iv": {"saldo": 0.204567}}),
        _section("selection", "Selección", status="missing"),
        _section("model", "Modelo PD", payload={"selected_features": ("saldo", "mora")}),
        _section("scorecard", "Scorecard", payload={"pdo": 20, "offset": 600}),
        _section("calibration", "Calibración", metric_sections={"pd_anchor": 0.0444444}),
        _section("stability", "Estabilidad", metric_sections={"score_psi": 0.271}),
        _section("limitations", "Limitaciones", payload={"missing_sections": ("selection",)}),
        _section(
            "appendix",
            "Apéndice",
            payload={"table_keys": ("performance.performance_table", "model.coefficients")},
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
    payload: dict[str, Any] | None = None,
    metric_sections: dict[str, Any] | None = None,
) -> ReportSection:
    """Sección sintética con fuente canónica."""
    return ReportSection(
        id=section_id,
        title=title,
        status=status,
        source_domain=(
            section_id if section_id not in {"lineage", "appendix", "limitations"} else "report"
        ),
        source_key="card",
        payload={} if payload is None else payload,
        metric_sections={} if metric_sections is None else metric_sections,
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
        section_id="performance",
        text="Narrativa controlada para desempeño.",
        provider="anthropic",
        model="modelo-test",
        generated=True,
        prompt_hash="0" * 64,
        input_payload_hash="1" * 64,
        warning=None,
    )


_CANONICAL_IDS = (
    "lineage",
    "eda",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
    "limitations",
    "appendix",
)
