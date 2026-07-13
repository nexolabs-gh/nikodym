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

import numpy as np
import pandas as pd
import pytest

from nikodym.core.config import NikodymConfig
from nikodym.core.lineage import LineageBundle
from nikodym.core.study import Study
from nikodym.report.config import PdfRenderConfig, ReportConfig, SectionPolicyConfig
from nikodym.report.exceptions import ReportDependencyError
from nikodym.report.pdf import render_pdf
from nikodym.report.renderer import HtmlReportRenderer, PdfReportRenderer
from nikodym.report.results import ReportInputBundle, ReportResult, ReportSection
from nikodym.report.step import REPORT_REQUIRED_CARDS, ReportStep


def _weasyprint_utilizable() -> bool:
    """¿Se puede RENDERIZAR un PDF aquí? No basta con que el paquete esté instalado.

    ``find_spec("weasyprint")`` sólo dice que existe el paquete de Python. WeasyPrint además carga
    librerías NATIVAS (Pango/HarfBuzz/libffi) por cffi al importarse, y ``pip install nikodym[pdf]``
    no las trae: en un macOS o un Windows sin Pango el import revienta con ``OSError``. Gatear sólo
    por ``find_spec`` hacía que estos tests, en vez de saltarse, FALLARAN en cualquier máquina de
    desarrollo con los extras instalados y sin las nativas del sistema.

    En el CI el job de PDF instala las nativas explícitamente, así que allí esto sigue siendo
    ``True`` y los tests corren de verdad (si las nativas faltaran, ese job falla en su propio paso
    de instalación, no aquí en silencio).
    """
    if importlib.util.find_spec("weasyprint") is None:
        return False
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


_HAS_WEASYPRINT = _weasyprint_utilizable()
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


def _coefficients_table() -> pd.DataFrame:
    """Tabla de coeficientes sintética (artefacto y card embebida) para el step end-to-end."""
    return pd.DataFrame(
        {"feature": ["mora", "saldo"], "beta": [-0.0, 1.25], "p_value": [0.04, 0.03]}
    )


def _performance_table() -> pd.DataFrame:
    """Tabla de performance mínima para el step end-to-end."""
    return pd.DataFrame({"decile": [2, 1], "pd": [0.1, 0.2], "default_rate": [0.05, 0.15]})


def _card(domain: str) -> dict[str, Any]:
    """Card sintética con ``metric_sections`` serializable y una tabla embebida en model."""
    if domain == "model":
        return {
            "summary": "model-card",
            "selected_features": ("saldo", "mora"),
            "embedded_table": _coefficients_table(),
            "metric_sections": {"model": {"p_value_max": 0.041}},
        }
    if domain == "performance":
        return {
            "summary": "performance-card",
            "metric_sections": {"performance": {"auc": 0.74321, "ks": 0.31234}},
        }
    if domain == "stability":
        return {
            "summary": "stability-card",
            "metric_sections": {"stability": {"score_psi": {"max_psi": 0.271, "band": "review"}}},
        }
    return {"summary": f"{domain}-card", "metric_sections": {domain: {"ok": 1}}}


def _study_with_report_artifacts(*, config: ReportConfig) -> Study:
    """``Study`` con las ocho cards requeridas y tablas de reporte, listo para ``ReportStep``."""
    study = Study(NikodymConfig(report=config))
    study.run_context.lineage = _lineage()
    for domain, key in REPORT_REQUIRED_CARDS:
        study.artifacts.set(domain, key, _card(domain))
    study.artifacts.set("performance", "performance_table", _performance_table())
    study.artifacts.set("model", "coefficients", _coefficients_table())
    return study


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


@pytest.mark.skipif(
    not _HAS_WEASYPRINT,
    reason="requiere el extra pdf (WeasyPrint + nativas Pango/HarfBuzz/libffi)",
)
def test_write_pdf_from_html_escribe_pdf_valido_y_devuelve_path(tmp_path: Path) -> None:
    """``write_pdf_from_html`` escribe ``{basename}.pdf`` válido y devuelve su ``Path`` real."""
    renderer = PdfReportRenderer(ReportConfig())
    html = HtmlReportRenderer.from_config(renderer.config).render(_bundle())

    path = renderer.write_pdf_from_html(html, output_dir=str(tmp_path))

    assert path == tmp_path / "scorecard_report.pdf"
    assert path.is_file()
    assert path.read_bytes()[:4] == b"%PDF"


@pytest.mark.skipif(
    not _HAS_WEASYPRINT,
    reason="requiere el extra pdf (WeasyPrint + nativas Pango/HarfBuzz/libffi)",
)
def test_report_step_formats_pdf_escribe_pdf_real(tmp_path: Path) -> None:
    """``ReportStep`` con ``"pdf"`` en ``formats`` escribe un PDF real y lo refleja en ``pdf_path``.

    Cablea el objetivo de B6 de punta a punta: ``formats`` pide el PDF, el step lo genera del MISMO
    HTML renderizado y ``ReportResult.pdf_path`` apunta al archivo en disco. El PDF NO entra al
    manifest (sigue siendo el del HTML determinístico).
    """
    cfg = ReportConfig(
        output_dir=str(tmp_path),
        formats=("html", "pdf"),
        sections=SectionPolicyConfig(max_table_rows=10),
    )
    study = _study_with_report_artifacts(config=cfg)

    result = ReportStep.from_config(cfg).execute(study, np.random.default_rng(20_240_629))

    assert isinstance(result, ReportResult)
    assert result.pdf_path == str(tmp_path / "scorecard_report.pdf")
    pdf_file = tmp_path / "scorecard_report.pdf"
    assert pdf_file.is_file()
    assert pdf_file.read_bytes()[:4] == b"%PDF"
    assert result.manifest.output_format == "html"


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


def _romper_nativas_de_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """WeasyPrint instalado pero SIN sus librerías nativas: el import levanta ``OSError``.

    Es el escenario real de ``pip install nikodym[pdf]`` en un macOS o un Windows sin Pango: el
    paquete de Python está, las librerías del sistema no.
    """
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: Any = None,
        locals_: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name == "weasyprint":
            raise OSError("cannot load library 'libgobject-2.0-0'")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_render_pdf_sin_librerias_nativas_lanza_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Las nativas ausentes se traducen a ``ReportDependencyError``, no escapan como ``OSError``.

    Si el ``OSError`` escapa crudo, ``fail_if_unavailable=False`` no lo atrapa y la corrida entera
    muere: el usuario pierde hasta el HTML, que sí se podía generar.
    """
    _romper_nativas_de_weasyprint(monkeypatch)
    with pytest.raises(ReportDependencyError, match="nativas"):
        render_pdf("<h1>Nikodym</h1>")


def test_pdf_renderer_degrada_sin_librerias_nativas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Con las nativas rotas y ``fail_if_unavailable=False``, la corrida SIGUE y entrega el HTML."""
    _romper_nativas_de_weasyprint(monkeypatch)

    renderer = PdfReportRenderer(
        ReportConfig(pdf=PdfRenderConfig(enabled=True, fail_if_unavailable=False))
    )
    with pytest.warns(RuntimeWarning):
        manifest = renderer.render(_bundle(), output_dir=str(tmp_path / "degradado"))

    assert manifest.output_format == "html"
    assert (tmp_path / "degradado" / "scorecard_report.html").is_file()
    assert not (tmp_path / "degradado" / "scorecard_report.pdf").exists()


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


def test_write_pdf_from_html_degrada_o_falla_sin_weasyprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``write_pdf_from_html`` sin WeasyPrint: degrada a ``None`` (False) o re-lanza (True)."""
    _bloquear_weasyprint(monkeypatch)
    html = "<h1>Nikodym</h1>"

    lenient = PdfReportRenderer(ReportConfig(pdf=PdfRenderConfig(fail_if_unavailable=False)))
    with pytest.warns(RuntimeWarning, match="WeasyPrint no está disponible"):
        path = lenient.write_pdf_from_html(html, output_dir=str(tmp_path / "lenient"))
    assert path is None
    assert not (tmp_path / "lenient" / "scorecard_report.pdf").exists()

    strict = PdfReportRenderer(ReportConfig(pdf=PdfRenderConfig(fail_if_unavailable=True)))
    with pytest.raises(ReportDependencyError, match="WeasyPrint"):
        strict.write_pdf_from_html(html, output_dir=str(tmp_path / "strict"))


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
