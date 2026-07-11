"""Tests de ``report.renderer``: HTML determinístico, export y Quarto opcional."""

from __future__ import annotations

import builtins
import hashlib
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
    QuartoRenderConfig,
    ReportConfig,
    SectionPolicyConfig,
)
from nikodym.report.exceptions import (
    ReportDependencyError,
    ReportExportError,
    ReportRenderError,
)
from nikodym.report.renderer import HtmlReportRenderer, QuartoReportRenderer
from nikodym.report.results import AiNarrationBlock, ReportInputBundle, ReportSection

GOLDEN_HTML_SHA256 = "f93a87ebe9bb2852eac14e9cf5d125621b64620ba6289257e563a0830e67295e"


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
    digest = hashlib.sha256(first.encode("utf-8")).hexdigest()

    assert first == second
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
    assert manifest.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
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


def test_quarto_tres_modos_y_error_de_subproceso(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Quarto deshabilitado no detecta; ausente degrada o falla; detectado se invoca."""
    bundle = _bundle()
    default_quarto = QuartoReportRenderer()
    from_config_quarto = QuartoReportRenderer.from_config(ReportConfig())

    assert default_quarto.config == ReportConfig()
    assert from_config_quarto.config == ReportConfig()

    def forbidden_which(name: str) -> str | None:
        raise AssertionError(f"No se debía detectar {name}")

    monkeypatch.setattr(renderer_module.shutil, "which", forbidden_which)
    disabled = QuartoReportRenderer(ReportConfig(quarto=QuartoRenderConfig(enabled=False)))
    assert disabled.render(bundle, output_dir=str(tmp_path / "disabled")).output_format == "html"

    monkeypatch.setattr(renderer_module.shutil, "which", lambda name: None)
    fallback = QuartoReportRenderer(
        ReportConfig(quarto=QuartoRenderConfig(enabled=True, fail_if_unavailable=False))
    )
    with pytest.warns(RuntimeWarning, match="Quarto no está disponible"):
        fallback_manifest = fallback.render(bundle, output_dir=str(tmp_path / "fallback"))
    assert fallback_manifest.output_format == "html"

    strict = QuartoReportRenderer(
        ReportConfig(quarto=QuartoRenderConfig(enabled=True, fail_if_unavailable=True))
    )
    with pytest.raises(ReportDependencyError, match=re.escape("https://quarto.org")):
        strict.render(bundle, output_dir=str(tmp_path / "strict"))

    calls: list[dict[str, Any]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, "kwargs": kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(renderer_module.shutil, "which", lambda name: "/fake/quarto")
    monkeypatch.setattr(renderer_module.subprocess, "run", fake_run)
    detected = QuartoReportRenderer(
        ReportConfig(
            quarto=QuartoRenderConfig(enabled=True, formats=("docx",)),
            basename="informe",
        )
    )
    detected_manifest = detected.render(bundle, output_dir=str(tmp_path / "detected"))
    assert detected_manifest.path == "informe.html"
    assert calls[0]["command"] == [
        "/fake/quarto",
        "render",
        "scorecard_report.qmd",
        "--to",
        "docx",
        "--output",
        "informe.docx",
    ]
    assert calls[0]["kwargs"]["cwd"] == tmp_path / "detected"
    assert calls[0]["kwargs"]["check"] is True

    def fail_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        raise subprocess.CalledProcessError(1, command, output="", stderr="fallo")

    monkeypatch.setattr(renderer_module.subprocess, "run", fail_run)
    failing = QuartoReportRenderer(QuartoRenderConfig(enabled=True))
    with pytest.raises(ReportRenderError, match="Quarto falló"):
        failing.render(bundle, output_dir=str(tmp_path / "failing"))


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
    assert report_pkg.QuartoReportRenderer is QuartoReportRenderer

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
