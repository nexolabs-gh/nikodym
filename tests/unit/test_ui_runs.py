"""Tests de la persistencia de corridas por ``run_id`` (SDD-23 §4.3, §7, §9, §11).

Cubre el round-trip ``save``→``load_results``, la presencia/ausencia del reporte, el bloqueo de
*path traversal* y la extracción duck-typed del HTML. No requiere FastAPI.
"""

from __future__ import annotations

import io
import types
import zipfile
from pathlib import Path

import pytest
from _ui_f1 import (
    eda_only_config,
    full_f1_config,
    write_behavior_parquet,
    write_near_unique_cohort_parquet,
)

import nikodym
from nikodym.core.study import Study
from nikodym.ui import runs
from nikodym.ui.exceptions import UiError, UiRunNotFoundError
from nikodym.ui.serializers import EDA_MAX_PUBLISHED_PERIODS, serialize_study


@pytest.fixture
def f1_study(fake_binning_process: object, tmp_path: Path) -> Study:
    """``Study`` F1 finalizado para persistir."""
    del fake_binning_process
    parquet = tmp_path / "cartera.parquet"
    write_behavior_parquet(parquet)
    return nikodym.run(full_f1_config(str(parquet)))


# ─────────────────────────────── save / load_results ───────────────────────────────


def test_save_load_results_round_trip(f1_study: Study, tmp_path: Path) -> None:
    """``save`` persiste el payload serializado y ``load_results`` lo devuelve idéntico."""
    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)

    assert run_id == f1_study.run_context.run_id
    assert (workdir / "runs" / run_id / "results.json").is_file()
    assert runs.load_results(run_id, workdir=workdir) == serialize_study(f1_study, governance=None)


def test_save_sin_reporte_no_escribe_html(f1_study: Study, tmp_path: Path) -> None:
    """Una corrida sin artefacto de reporte no persiste ``report.html`` (load_report → None)."""
    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)
    assert not (workdir / "runs" / run_id / "report.html").exists()
    assert runs.load_report(run_id, workdir=workdir) is None


def test_save_con_reporte_persiste_html(f1_study: Study, tmp_path: Path) -> None:
    """Con un artefacto de reporte con ``html_path`` existente, ``save`` escribe ``report.html``."""
    html_file = tmp_path / "reporte.html"
    html_file.write_text("<h1>Reporte Nikodym</h1>", encoding="utf-8")
    f1_study.artifacts.set("report", "result", types.SimpleNamespace(html_path=str(html_file)))

    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)

    assert runs.load_report(run_id, workdir=workdir) == "<h1>Reporte Nikodym</h1>"


def test_save_sin_pdf_no_escribe_pdf(f1_study: Study, tmp_path: Path) -> None:
    """Una corrida sin PDF de reporte no persiste ``report.pdf`` (load_report_pdf → None)."""
    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)
    assert not (workdir / "runs" / run_id / "report.pdf").exists()
    assert runs.load_report_pdf(run_id, workdir=workdir) is None


def test_save_con_pdf_persiste_pdf(f1_study: Study, tmp_path: Path) -> None:
    """Con un artefacto de reporte con ``pdf_path`` existente, ``save`` escribe ``report.pdf``."""
    pdf_file = tmp_path / "reporte.pdf"
    pdf_file.write_bytes(b"%PDF-1.7 nikodym")
    f1_study.artifacts.set(
        "report", "result", types.SimpleNamespace(html_path=None, pdf_path=str(pdf_file))
    )

    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)

    assert runs.load_report_pdf(run_id, workdir=workdir) == b"%PDF-1.7 nikodym"


def test_save_sin_base_editable_no_escribe_qmd_ni_docx(f1_study: Study, tmp_path: Path) -> None:
    """Una corrida sin fuentes editables no persiste ``report.qmd`` ni ``report.docx`` (→ None)."""
    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)

    assert not (workdir / "runs" / run_id / "report.qmd").exists()
    assert not (workdir / "runs" / run_id / "report.docx").exists()
    assert runs.load_report_md(run_id, workdir=workdir) is None
    assert runs.load_report_docx(run_id, workdir=workdir) is None


def test_save_persiste_el_qmd_con_su_carpeta_de_figuras(f1_study: Study, tmp_path: Path) -> None:
    """El ``.qmd`` se guarda **con sus figuras**: copiar sólo el texto entregaría una fuente rota.

    El ``.qmd`` referencia sus SVG con ruta relativa; sin la carpeta hermana, ``quarto render``
    fallaría y la "base editable" no sería editable de verdad.
    """
    reports = tmp_path / "reports"
    (reports / "scorecard_report_figuras").mkdir(parents=True)
    qmd = reports / "scorecard_report.qmd"
    qmd.write_text("![Coef](scorecard_report_figuras/chart-model.svg)\n", encoding="utf-8")
    (reports / "scorecard_report_figuras" / "chart-model.svg").write_text("<svg/>", "utf-8")
    f1_study.artifacts.set(
        "report", "result", types.SimpleNamespace(html_path=None, md_path=str(qmd))
    )

    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)
    run_dir = workdir / "runs" / run_id

    assert runs.load_report_md(run_id, workdir=workdir) is not None
    assert (run_dir / "report.qmd").is_file()
    # La carpeta conserva su nombre: es el que el .qmd referencia.
    assert (run_dir / "scorecard_report_figuras" / "chart-model.svg").is_file()

    # …y el ZIP que se descarga lleva ESA figura, con la ruta que el documento cita. El bug vivía
    # justo en esta costura: `save` persiste el documento como `report.qmd` y el empaquetador
    # derivaba la carpeta de su stem (`report_figuras`), que save nunca escribe. Cada test miraba su
    # mitad, las dos pasaban, y el ZIP real salía sin una sola figura.
    bundle = runs.load_report_md_bundle(run_id, workdir=workdir)
    assert bundle is not None
    with zipfile.ZipFile(io.BytesIO(bundle)) as paquete:
        nombres = set(paquete.namelist())
    assert "report.qmd" in nombres
    assert "scorecard_report_figuras/chart-model.svg" in nombres


def test_save_persiste_el_docx(f1_study: Study, tmp_path: Path) -> None:
    """Con un artefacto de reporte con ``docx_path`` existente, ``save`` escribe ``report.docx``."""
    docx_file = tmp_path / "reporte.docx"
    docx_file.write_bytes(b"PK\x03\x04 nikodym")
    f1_study.artifacts.set(
        "report", "result", types.SimpleNamespace(html_path=None, docx_path=str(docx_file))
    )

    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)

    assert runs.load_report_docx(run_id, workdir=workdir) == b"PK\x03\x04 nikodym"


def test_la_tabla_completa_de_la_tasa_queda_como_archivo_de_la_corrida_si_se_recorto(
    tmp_path: Path,
) -> None:
    """🔴 Cierre 1 de D-SC: la respuesta publica hasta el tope y la tabla ENTERA queda como
    artefacto de la corrida. ``save`` escribe ``eda_default_rate.csv`` con todas las filas y las
    mismas columnas que la fila del payload; ``eda_default_rate_path`` la sirve por trozos."""
    import pandas as pd

    parquet = tmp_path / "cartera.parquet"
    write_near_unique_cohort_parquet(parquet)
    study = nikodym.run(eda_only_config(str(parquet)))
    assert study.run_context.status == "done", study.run_context.error

    workdir = tmp_path / "wd"
    run_id = runs.save(study, workdir=workdir, governance=None)

    payload = runs.load_results(run_id, workdir=workdir)
    assert payload["eda"]["default_rate_window"]["truncated"] is True
    csv = workdir / "runs" / run_id / "eda_default_rate.csv"
    assert csv.is_file()
    # La persistencia entrega la RUTA, no los bytes: el endpoint la sirve por trozos.
    assert runs.eda_default_rate_path(run_id, workdir=workdir) == csv
    contenido = csv.read_bytes()
    assert contenido.startswith(b"\xef\xbb\xbf")  # UTF-8 con BOM, como los exports del informe
    tabla = pd.read_csv(io.BytesIO(contenido))
    assert len(tabla) == payload["eda"]["default_rate_window"]["total_periods"]
    assert len(tabla) > EDA_MAX_PUBLISHED_PERIODS
    assert list(tabla.columns) == list(payload["eda"]["default_rate"][0])
    # Las primeras filas del archivo son las que la respuesta publicó, en el mismo orden.
    assert tabla["period"].tolist()[:EDA_MAX_PUBLISHED_PERIODS] == [
        fila["period"] for fila in payload["eda"]["default_rate"]
    ]


def test_sin_recorte_no_hay_archivo_de_la_tasa(
    fake_binning_process: object, tmp_path: Path
) -> None:
    """El archivo existe si y sólo si la respuesta se recortó: con pocas cohortes el payload ya
    trae la tabla entera y no se duplica en disco (``eda_default_rate_path`` → ``None``)."""
    del fake_binning_process
    from nikodym.eda.config import DefaultRateConfig, EdaConfig, UnivariateConfig

    parquet = tmp_path / "cartera.parquet"
    write_behavior_parquet(parquet)
    config = full_f1_config(str(parquet)).model_copy(
        update={
            "eda": EdaConfig(
                default_rate=DefaultRateConfig(min_obs_per_period=1),
                univariate=UnivariateConfig(columns=("score",), n_quantile_bins=2),
            )
        }
    )
    study = nikodym.run(config)
    assert study.run_context.status == "done", study.run_context.error

    workdir = tmp_path / "wd"
    run_id = runs.save(study, workdir=workdir, governance=None)

    payload = runs.load_results(run_id, workdir=workdir)
    assert payload["eda"]["default_rate_window"]["truncated"] is False
    assert not (workdir / "runs" / run_id / "eda_default_rate.csv").exists()
    assert runs.eda_default_rate_path(run_id, workdir=workdir) is None


def test_sin_eda_no_hay_archivo_de_la_tasa(f1_study: Study, tmp_path: Path) -> None:
    """Una corrida sin ``eda`` no escribe el archivo ni lo fabrica al leer."""
    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)
    assert not (workdir / "runs" / run_id / "eda_default_rate.csv").exists()
    assert runs.eda_default_rate_path(run_id, workdir=workdir) is None


def test_save_study_sin_run_id_falla(tmp_path: Path) -> None:
    """Persistir un Study no ejecutado (sin run_id) es un error de uso."""
    study = Study(full_f1_config("cartera.parquet"))  # no ejecutado → run_id None
    with pytest.raises(UiError, match="run_id"):
        runs.save(study, workdir=tmp_path, governance=None)


def test_load_results_run_id_desconocido(tmp_path: Path) -> None:
    """Un ``run_id`` bien formado pero inexistente levanta ``UiRunNotFoundError`` (→ 404)."""
    with pytest.raises(UiRunNotFoundError):
        runs.load_results("0" * 32, workdir=tmp_path)


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "no-hex", "ABC" * 11, ""])
def test_run_id_invalido_bloqueado(run_id: str, tmp_path: Path) -> None:
    """Un ``run_id`` no-uuid o con separadores se rechaza (path traversal bloqueado, §11)."""
    with pytest.raises(UiRunNotFoundError):
        runs.load_results(run_id, workdir=tmp_path)


# ─────────────────────────────── _report_html (duck-typed) ───────────────────────────────


class _FakeArtifacts:
    """Doble mínimo del ``ArtifactStore`` para probar ``_report_html`` sin correr el pipeline."""

    def __init__(self, store: dict[tuple[str, str], object]) -> None:
        self._store = store

    def has(self, domain: str, key: str) -> bool:
        return (domain, key) in self._store

    def get(self, domain: str, key: str) -> object:
        return self._store[(domain, key)]


def _fake_study(store: dict[tuple[str, str], object]) -> object:
    return types.SimpleNamespace(artifacts=_FakeArtifacts(store))


def test_report_html_sin_artefactos_es_none() -> None:
    """Sin artefactos de reporte, ``_report_html`` devuelve ``None``."""
    assert runs._report_html(_fake_study({})) is None  # type: ignore[arg-type]


def test_report_html_ignora_html_path_no_str() -> None:
    """Un artefacto sin ``html_path`` (None) no produce HTML."""
    store = {("report", "result"): types.SimpleNamespace(html_path=None)}
    assert runs._report_html(_fake_study(store)) is None  # type: ignore[arg-type]


def test_report_html_ignora_archivo_inexistente(tmp_path: Path) -> None:
    """Un ``html_path`` que no apunta a un archivo existente no produce HTML."""
    store = {("report", "manifest"): types.SimpleNamespace(html_path=str(tmp_path / "no.html"))}
    assert runs._report_html(_fake_study(store)) is None  # type: ignore[arg-type]


def test_report_html_lee_archivo_existente(tmp_path: Path) -> None:
    """Un ``html_path`` a un archivo existente devuelve su contenido."""
    html_file = tmp_path / "r.html"
    html_file.write_text("<p>ok</p>", encoding="utf-8")
    store = {("report", "result"): types.SimpleNamespace(html_path=str(html_file))}
    assert runs._report_html(_fake_study(store)) == "<p>ok</p>"  # type: ignore[arg-type]


# ─────────────────────────────── _report_pdf (duck-typed) ───────────────────────────────


def test_report_pdf_sin_artefactos_es_none() -> None:
    """Sin artefactos de reporte, ``_report_pdf`` devuelve ``None``."""
    assert runs._report_pdf(_fake_study({})) is None  # type: ignore[arg-type]


def test_report_pdf_ignora_pdf_path_no_str() -> None:
    """Un artefacto sin ``pdf_path`` (None) no produce PDF."""
    store = {("report", "result"): types.SimpleNamespace(pdf_path=None)}
    assert runs._report_pdf(_fake_study(store)) is None  # type: ignore[arg-type]


def test_report_pdf_ignora_archivo_inexistente(tmp_path: Path) -> None:
    """Un ``pdf_path`` que no apunta a un archivo existente no produce PDF."""
    store = {("report", "manifest"): types.SimpleNamespace(pdf_path=str(tmp_path / "no.pdf"))}
    assert runs._report_pdf(_fake_study(store)) is None  # type: ignore[arg-type]


def test_report_pdf_lee_archivo_existente(tmp_path: Path) -> None:
    """Un ``pdf_path`` a un archivo existente devuelve sus bytes."""
    pdf_file = tmp_path / "r.pdf"
    pdf_file.write_bytes(b"%PDF ok")
    store = {("report", "result"): types.SimpleNamespace(pdf_path=str(pdf_file))}
    assert runs._report_pdf(_fake_study(store)) == b"%PDF ok"  # type: ignore[arg-type]
