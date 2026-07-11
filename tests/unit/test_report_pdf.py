"""Tests de ``report.pdf`` y ``PdfReportRenderer``: render PDF real (WeasyPrint) y degradación.

Los tests que ejecutan WeasyPrint real (grupos (a) y (b)) van gateados con ``skipif``: WeasyPrint
exige librerías nativas (Pango/HarfBuzz/libffi) que no están en todos los entornos de desarrollo, y
se validan en el job ``test-pdf`` del CI (ubuntu, extra ``pdf`` instalado). El PDF NO es
byte-determinista, por lo que la verificación es estructural (``%PDF``, ≥1 página, texto extraíble
con ``pypdf``), nunca por digest cross-OS. Los grupos (c) y (d) corren SIEMPRE: cubren la ausencia
de WeasyPrint (bloqueando su import) y el import liviano del paquete ``report``.
"""

from __future__ import annotations

import builtins
import importlib.util
import subprocess
import sys
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from nikodym.core.lineage import LineageBundle
from nikodym.report.config import PdfRenderConfig, ReportConfig
from nikodym.report.exceptions import ReportDependencyError
from nikodym.report.pdf import render_pdf
from nikodym.report.renderer import PdfReportRenderer
from nikodym.report.results import ReportInputBundle, ReportSection

_HAS_WEASYPRINT = importlib.util.find_spec("weasyprint") is not None
_MARCA = "marcaunicaxyznikodym"


def _lineage() -> LineageBundle:
    """Lineage fijo mínimo para el bundle sintético."""
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123456789abcdef",
        config_hash="cfg123456789abcdef",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "0.1.0"},
        determinism_caveats=["fixture controlado"],
        created_at=datetime(2026, 6, 24, 9, 30, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _bundle() -> ReportInputBundle:
    """Bundle mínimo válido que renderiza HTML y sirve para escribir el PDF."""
    lineage = _lineage()
    sections = (
        ReportSection(
            id="model",
            title="Modelo PD",
            status="included",
            source_domain="model",
            source_key="card",
            payload={"pdo": 20, "offset": 600},
        ),
    )
    return ReportInputBundle(
        lineage=lineage,
        cards={"model": {"selected_features": ("saldo", "mora")}},
        tables={},
        figures={},
        sections=sections,
        missing_sections=(),
    )


# ─────────────────────────── (a) render_pdf real (skipif weasyprint) ───────────────────────────


@pytest.mark.skipif(
    not _HAS_WEASYPRINT,
    reason="requiere el extra pdf (WeasyPrint + nativas Pango/HarfBuzz/libffi)",
)
def test_render_pdf_genera_pdf_valido_con_texto_extraible() -> None:
    """``render_pdf`` produce un PDF válido (``%PDF``, ≥1 página) con el texto extraíble."""
    from pypdf import PdfReader

    pdf = render_pdf(f"<h1>Nikodym</h1><p>{_MARCA}</p>")

    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 0
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) >= 1
    text = "".join(page.extract_text() for page in reader.pages)
    assert _MARCA in text


# ─────────────────────── (b) PdfReportRenderer real (skipif weasyprint) ───────────────────────


@pytest.mark.skipif(
    not _HAS_WEASYPRINT,
    reason="requiere el extra pdf (WeasyPrint + nativas Pango/HarfBuzz/libffi)",
)
def test_pdf_renderer_escribe_pdf_valido_y_devuelve_manifest_html(tmp_path: Path) -> None:
    """``PdfReportRenderer`` habilitado escribe ``{basename}.pdf`` válido y devuelve manifest."""
    renderer = PdfReportRenderer(ReportConfig(pdf=PdfRenderConfig(enabled=True)))
    manifest = renderer.render(_bundle(), output_dir=str(tmp_path))

    assert manifest.output_format == "html"
    html_path = tmp_path / "scorecard_report.html"
    pdf_path = tmp_path / "scorecard_report.pdf"
    assert html_path.is_file()
    assert pdf_path.is_file()
    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 0


# ─────────────────────── (c) fallback SIN weasyprint (corre SIEMPRE) ───────────────────────


def _bloquear_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fuerza ``ModuleNotFoundError`` al importar ``weasyprint`` (ausencia determinista)."""
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


def test_render_pdf_sin_weasyprint_lanza_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``render_pdf`` traduce la ausencia de WeasyPrint a ``ReportDependencyError`` accionable."""
    _bloquear_weasyprint(monkeypatch)
    with pytest.raises(ReportDependencyError, match="WeasyPrint"):
        render_pdf("<h1>Nikodym</h1>")


def test_pdf_renderer_degrada_o_falla_sin_weasyprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Sin WeasyPrint: ``fail_if_unavailable=False`` degrada a HTML; ``True`` re-lanza."""
    _bloquear_weasyprint(monkeypatch)
    bundle = _bundle()

    fallback = PdfReportRenderer(
        ReportConfig(pdf=PdfRenderConfig(enabled=True, fail_if_unavailable=False))
    )
    with pytest.warns(RuntimeWarning, match="WeasyPrint no está disponible"):
        manifest = fallback.render(bundle, output_dir=str(tmp_path / "fallback"))
    assert manifest.output_format == "html"
    assert (tmp_path / "fallback" / "scorecard_report.html").is_file()
    assert not (tmp_path / "fallback" / "scorecard_report.pdf").exists()

    strict = PdfReportRenderer(
        ReportConfig(pdf=PdfRenderConfig(enabled=True, fail_if_unavailable=True))
    )
    with pytest.raises(ReportDependencyError, match="WeasyPrint"):
        strict.render(bundle, output_dir=str(tmp_path / "strict"))


# ─────────────────────── (d) import liviano (corre SIEMPRE) ───────────────────────


def test_import_report_no_arrastra_weasyprint_por_subprocess() -> None:
    """``import nikodym.report`` NO importa WeasyPrint (import perezoso en ``render_pdf``)."""
    code = (
        "import sys;"
        # Bloquea weasyprint: si algo intentara importarlo en import-time, `import nikodym.report`
        # reventaría (ImportError) en vez de continuar.
        "sys.modules['weasyprint'] = None;"
        "import nikodym.report as report;"
        "assert report.__name__ == 'nikodym.report';"
        "assert sys.modules.get('weasyprint') is None;"
        "blocked=[m for m in ('matplotlib', 'plotly') if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
