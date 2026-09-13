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


def test_el_archivo_de_la_tasa_neutraliza_las_cohortes_que_excel_leeria_como_formula(
    tmp_path: Path,
) -> None:
    """🔴 Pasada 2 de la revisión adversarial (d99bc9d): la etiqueta de cohorte viene del archivo
    del usuario y el CSV lleva BOM «para Excel»: un valor `=HYPERLINK(...)` llegaba como fórmula
    viva. Al exportar se antepone una comilla a las celdas de texto con prefijo activo; el
    payload y el panel siguen mostrando la etiqueta tal cual."""
    import pandas as pd
    from _ui_f1 import NEAR_UNIQUE_COHORT_COL

    parquet = tmp_path / "cartera.parquet"
    write_near_unique_cohort_parquet(parquet)
    frame = pd.read_parquet(parquet)
    venenosas = {
        "ID-00000": '=HYPERLINK("http://x.invalid";"ver")',
        "ID-00002": "+1+1",
        "ID-00004": "-cmd",
        "ID-00006": "@SUM(A1)",
    }
    frame[NEAR_UNIQUE_COHORT_COL] = frame[NEAR_UNIQUE_COHORT_COL].map(lambda v: venenosas.get(v, v))
    frame.to_parquet(parquet)
    study = nikodym.run(eda_only_config(str(parquet)))
    assert study.run_context.status == "done", study.run_context.error

    workdir = tmp_path / "wd"
    run_id = runs.save(study, workdir=workdir, governance=None)

    payload = runs.load_results(run_id, workdir=workdir)
    publicadas = {fila["period"] for fila in payload["eda"]["default_rate"]}
    assert set(venenosas.values()) <= publicadas  # el payload no se altera: es el dato del motor
    csv = runs.eda_default_rate_path(run_id, workdir=workdir)
    assert csv is not None
    # Se lee como lo leería una planilla (campos entrecomillados incluidos): cada cohorte con
    # prefijo activo llega con la comilla delante, y ninguna celda de la primera columna empieza
    # por un prefijo activo.
    tabla = pd.read_csv(io.BytesIO(csv.read_bytes()), keep_default_na=False)
    assert len(tabla) == payload["eda"]["default_rate_window"]["total_periods"]
    periodos = tabla["period"].tolist()
    for valor in venenosas.values():
        assert f"'{valor}" in periodos, valor
        assert valor not in periodos
    assert not any(str(p).startswith(("=", "+", "-", "@", "\t", "\r")) for p in periodos)
    assert any(str(p).startswith("ID-") for p in periodos)  # una etiqueta normal viaja tal cual


def test_el_archivo_de_la_tasa_no_deja_que_un_separador_regional_abra_una_formula(
    tmp_path: Path,
) -> None:
    """🔴 Pasada 10 de la revisión adversarial (5e5f033): un Excel con `;` como separador de lista
    partía la cohorte `x;=HYPERLINK(1)` en una celda de texto y una fórmula viva. La guarda va
    también tras cada `;`, y todo texto viaja entre comillas."""
    import csv

    import pandas as pd
    from _ui_f1 import NEAR_UNIQUE_COHORT_COL

    parquet = tmp_path / "cartera.parquet"
    write_near_unique_cohort_parquet(parquet)
    frame = pd.read_parquet(parquet)
    frame[NEAR_UNIQUE_COHORT_COL] = frame[NEAR_UNIQUE_COHORT_COL].map(
        lambda v: "x;=HYPERLINK(1)" if v == "ID-00000" else v
    )
    frame.to_parquet(parquet)
    study = nikodym.run(eda_only_config(str(parquet)))
    assert study.run_context.status == "done", study.run_context.error
    workdir = tmp_path / "wd"
    run_id = runs.save(study, workdir=workdir, governance=None)
    csv_path = runs.eda_default_rate_path(run_id, workdir=workdir)
    assert csv_path is not None
    texto = csv_path.read_text(encoding="utf-8-sig")
    assert '"x;\'=HYPERLINK(1)"' in texto
    campos = [c for fila in csv.reader(io.StringIO(texto), delimiter=";") for c in fila]
    assert not any(c.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) for c in campos)


def test_un_fallo_al_escribir_el_csv_no_deja_la_corrida_publicada_a_medias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Pasada 3 de la revisión adversarial (b71f599): `save` escribía `results.json` y DESPUÉS
    el CSV, directo a su nombre final. Un disco lleno a mitad del archivo grande dejaba una
    corrida que se servía —con `truncated: true`— sin su tabla completa, o con un CSV a medias.
    Ahora el CSV se escribe a un temporal y se publica entero, y `results.json` sólo después: si
    el CSV falla, la corrida no existe para `load_results` y no queda ningún archivo servible."""
    import pandas as pd

    parquet = tmp_path / "cartera.parquet"
    write_near_unique_cohort_parquet(parquet)
    study = nikodym.run(eda_only_config(str(parquet)))
    assert study.run_context.status == "done", study.run_context.error
    workdir = tmp_path / "wd"
    run_id = study.run_context.run_id
    assert run_id is not None
    original = pd.DataFrame.to_csv

    def _disco_lleno(self: pd.DataFrame, destino: object, *args: object, **kwargs: object) -> None:
        # Escribe la mitad del archivo y muere, como un disco que se llena a medio camino.
        original(self.head(len(self) // 2), destino, *args, **kwargs)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pd.DataFrame, "to_csv", _disco_lleno)
    with pytest.raises(OSError, match="No space left"):
        runs.save(study, workdir=workdir, governance=None)

    run_dir = workdir / "runs" / run_id
    assert not (run_dir / "results.json").exists()
    assert runs.eda_default_rate_path(run_id, workdir=workdir) is None
    with pytest.raises(UiRunNotFoundError):
        runs.load_results(run_id, workdir=workdir)
    assert not any(run_dir.glob("*.csv*")) if run_dir.exists() else True


def test_un_fallo_despues_del_csv_no_deja_una_corrida_huerfana_con_el_archivo_grande(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Pasada 4 de la revisión adversarial (d5047ff): el CSV grande ya estaba en su nombre final
    cuando fallaba `results.json` o un informe, y quedaba en un directorio de corrida que la UI
    no puede servir; cada reintento acumulaba otro. La corrida se construye en un hermano
    temporal y se publica entera con un `replace`; si algo falla después del CSV, no queda
    `runs/<run_id>` ni ningún CSV bajo `runs/`, y sólo se conserva el trail —la evidencia— en un
    hermano `.<run_id>.failed.*` anotado en la excepción."""
    import json

    parquet = tmp_path / "cartera.parquet"
    write_near_unique_cohort_parquet(parquet)
    study = nikodym.run(eda_only_config(str(parquet)))
    assert study.run_context.status == "done", study.run_context.error
    workdir = tmp_path / "wd"
    run_id = study.run_context.run_id
    assert run_id is not None
    trail = runs.reservar_trail(workdir)
    trail.write_text('{"event": "run_start"}\n', encoding="utf-8")

    def _disco_lleno(*_args: object, **_kwargs: object) -> str:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json, "dumps", _disco_lleno)
    with pytest.raises(OSError, match="No space left") as info:
        runs.save(study, workdir=workdir, governance=None, trail=trail)

    runs_root = workdir / "runs"
    assert not (runs_root / run_id).exists()
    assert not list(runs_root.rglob("*.csv*")), "el archivo grande no puede quedar huérfano"
    assert not list(runs_root.glob(f".{run_id}.*.tmp")), "el temporal no queda a medias"
    conservados = list(runs_root.glob(f".{run_id}.failed.*"))
    assert len(conservados) == 1
    assert [p.name for p in conservados[0].iterdir()] == ["audit_trail.jsonl"]
    assert str(conservados[0]) in "".join(getattr(info.value, "__notes__", []))
    with pytest.raises(UiRunNotFoundError):
        runs.load_results(run_id, workdir=workdir)


def test_si_falla_la_publicacion_la_corrida_previa_vuelve_a_su_sitio(
    f1_study: Study, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Pasada 5 de la revisión adversarial (98871cb): con una corrida previa en `runs/<run_id>`,
    `save` la apartaba a `.old.*` y, si el `replace` del temporal fallaba, no la restauraba: la
    ruta canónica desaparecía y la UI devolvía 404 para una corrida que era válida."""
    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)
    run_dir = workdir / "runs" / run_id
    centinela = (run_dir / "results.json").read_bytes()
    (run_dir / "report.html").write_text("<h1>previo</h1>", encoding="utf-8")

    original = runs._replace_path
    llamadas: list[tuple[Path, Path]] = []

    def _falla_al_publicar(src: Path, dst: Path) -> None:
        llamadas.append((src, dst))
        if dst == run_dir and src.name.endswith(".tmp"):
            raise PermissionError(13, "lock transitorio agotado")
        original(src, dst)

    monkeypatch.setattr(runs, "_replace_path", _falla_al_publicar)
    with pytest.raises(PermissionError):
        runs.save(f1_study, workdir=workdir, governance=None)

    # La corrida previa vuelve a su sitio, byte a byte, y sigue sirviéndose.
    assert (run_dir / "results.json").read_bytes() == centinela
    assert (run_dir / "report.html").read_text(encoding="utf-8") == "<h1>previo</h1>"
    assert runs.load_results(run_id, workdir=workdir) == serialize_study(f1_study, governance=None)
    runs_root = workdir / "runs"
    assert not list(runs_root.glob(f".{run_id}.old.*")), "el respaldo se consumió al restaurar"
    assert not list(runs_root.glob(f".{run_id}.*.tmp")), "el temporal no queda a medias"


def test_re_persistir_desde_el_trail_canonico_no_muta_la_corrida_previa_si_falla(
    f1_study: Study, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Pasada 6 de la revisión adversarial (244f348): `save` MOVÍA el trail al temporal antes de
    construir el reemplazo. Re-persistir un `Study` pasando el trail canónico de la corrida ya
    publicada (`runs/<run_id>/audit_trail.jsonl`) y fallar después dejaba la corrida previa
    restaurada pero sin su audit-trail (`load_audit_trail` → `None`). El trail que vive dentro
    de la corrida que se reemplaza se COPIA, y la previa queda intacta byte a byte."""
    workdir = tmp_path / "wd"
    trail = runs.reservar_trail(workdir)
    trail.write_text('{"event": "run_start"}\n', encoding="utf-8")
    run_id = runs.save(f1_study, workdir=workdir, governance=None, trail=trail)
    run_dir = workdir / "runs" / run_id
    assert not trail.exists(), "el trail reservado se traslada a la corrida al publicarla"
    previa = {p.name: p.read_bytes() for p in run_dir.iterdir() if p.is_file()}
    assert "audit_trail.jsonl" in previa

    def _revienta(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("falla después de archivar el trail")

    monkeypatch.setattr(runs, "serialize_study", _revienta)
    with pytest.raises(RuntimeError):
        runs.save(f1_study, workdir=workdir, governance=None, trail=run_dir / "audit_trail.jsonl")

    assert {p.name: p.read_bytes() for p in run_dir.iterdir() if p.is_file()} == previa
    assert runs.load_audit_trail(run_id, workdir=workdir) == '{"event": "run_start"}\n'
    # El trail canónico era una copia en el temporal: no hay evidencia nueva que conservar, así
    # que no queda ningún hermano `.failed.*`, `.old.*` ni `.tmp`.
    assert sorted(p.name for p in (workdir / "runs").iterdir()) == [run_id]


def test_una_corrida_apartada_por_un_corte_a_mitad_del_swap_se_recupera_al_arrancar(
    f1_study: Study, tmp_path: Path
) -> None:
    """🔴 Pasada 11 de la revisión adversarial (3ce7116): al re-persistir, la corrida previa se
    aparta a `.<run_id>.old.*` y sólo después el temporal ocupa su sitio; un corte del proceso
    entre los dos `replace` dejaba `runs/<run_id>` ausente —404— con la corrida intacta en un
    respaldo que ningún arranque recuperaba. `asegurar_workdir` —el arranque del servidor y cada
    persistencia— devuelve a su sitio todo respaldo cuya ruta canónica falte."""
    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)
    run_dir = workdir / "runs" / run_id
    contenido = {p.name: p.read_bytes() for p in run_dir.iterdir() if p.is_file()}
    # El estado que deja el corte: la previa apartada, el temporal a medias, la canónica ausente.
    apartada = workdir / "runs" / f".{run_id}.old.corte"
    run_dir.rename(apartada)
    temporal = workdir / "runs" / f".{run_id}.corte.tmp"
    temporal.mkdir()
    (temporal / "results.json").write_text("{", encoding="utf-8")
    with pytest.raises(UiRunNotFoundError):
        runs.load_results(run_id, workdir=workdir)

    runs.asegurar_workdir(workdir)

    assert run_dir.is_dir() and not apartada.exists()
    assert {p.name: p.read_bytes() for p in run_dir.iterdir() if p.is_file()} == contenido
    assert runs.load_results(run_id, workdir=workdir) == serialize_study(f1_study, governance=None)
    # El temporal a medias no se toca: no es una corrida y puede llevar evidencia de un corte.
    assert temporal.is_dir()


def test_la_recuperacion_no_pisa_una_corrida_que_si_existe(f1_study: Study, tmp_path: Path) -> None:
    """Un respaldo cuya ruta canónica sí está (una re-persistencia que terminó) se queda."""
    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)
    run_id_2 = runs.save(f1_study, workdir=workdir, governance=None)
    assert run_id == run_id_2
    respaldos = list((workdir / "runs").glob(f".{run_id}.old.*"))
    assert len(respaldos) == 1
    runs.asegurar_workdir(workdir)
    assert respaldos[0].is_dir() and (workdir / "runs" / run_id).is_dir()


def test_una_corrida_publicada_no_deja_temporales_y_un_fallo_sin_evidencia_no_deja_rastro(
    f1_study: Study, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workdir = tmp_path / "wd"
    run_id = runs.save(f1_study, workdir=workdir, governance=None)
    runs_root = workdir / "runs"
    assert sorted(p.name for p in runs_root.iterdir()) == [run_id]

    # Sin trail y con un fallo antes de escribir nada: el temporal se descarta sin rastro.
    otro = tmp_path / "wd2"

    def _revienta(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("x")

    monkeypatch.setattr(runs, "serialize_study", _revienta)
    with pytest.raises(RuntimeError):
        runs.save(f1_study, workdir=otro, governance=None)
    assert not list((otro / "runs").iterdir())


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
