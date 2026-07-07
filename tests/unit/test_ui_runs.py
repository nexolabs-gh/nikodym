"""Tests de la persistencia de corridas por ``run_id`` (SDD-23 §4.3, §7, §9, §11).

Cubre el round-trip ``save``→``load_results``, la presencia/ausencia del reporte, el bloqueo de
*path traversal* y la extracción duck-typed del HTML. No requiere FastAPI.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from _ui_f1 import full_f1_config, write_behavior_parquet

import nikodym
from nikodym.core.study import Study
from nikodym.ui import runs
from nikodym.ui.exceptions import UiError, UiRunNotFoundError
from nikodym.ui.serializers import serialize_study


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
