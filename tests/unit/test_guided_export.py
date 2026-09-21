"""Gates de la capa B de FLUJO-GUIADO-SCORECARD por código: Excel opcional y paquete (D-FLU-5).

§3.5 (un libro por etapa, numerado en el orden de §3.2, con las tablas de decisión y las tablas
completas del informe), §6-9 (el Excel reproduce celda a celda las tablas de los exports del
informe), la protección de celdas de planilla (Cami, 2026-09-13), ``export()`` (hallazgo #8 de
INTEGRACION-EXTERNA-1-16) y la serialización JSON de los resúmenes que consume la pantalla
(D-FLU-8). Las corridas usan el frame apilado y el doble determinista de OptBinning, como el resto
de la capa.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from _ui_f1 import write_stacked_behavior_parquet

from nikodym.core.exceptions import MissingDependencyError
from nikodym.guided import Scorecard, ScorecardInputError
from nikodym.guided import export as export_module
from nikodym.guided.export import DECISIONS_BOOK, EXCEL_SUBDIR, STAGE_BOOKS
from nikodym.guided.summaries import STAGE_LABELS, StageSummary, partition_label
from nikodym.report.document import PER_OBSERVATION_TABLES, table_title

openpyxl = pytest.importorskip("openpyxl", reason="el Excel opcional exige nikodym[excel]")


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    del fake_binning_process


@pytest.fixture
def fuente(tmp_path: Path) -> Path:
    ruta = tmp_path / "cartera.parquet"
    write_stacked_behavior_parquet(ruta, repeats=50)
    return ruta


def _puerta(fuente: Path, tmp_path: Path, **kwargs: Any) -> Scorecard:
    base: dict[str, Any] = {
        "target": "bad_flag",
        "id": "loan_id",
        "cohort": "cohort",
        "oot_cohorts": ["oot"],
        "name": "prueba",
        "run_dir": tmp_path / "corridas",
        "min_iv": 0.0,
        # `csv` y `xlsx`: el informe escribe sus exports por observación, que es contra lo que el
        # gate §6-9 compara celda a celda.
        "formats": ["csv", "xlsx"],
    }
    base.update(kwargs)
    sc = Scorecard(fuente, **base)
    sc._echo = lambda _texto: None
    return sc


def _filas(ruta: Path, hoja: str) -> list[tuple[Any, ...]]:
    libro = openpyxl.load_workbook(ruta, read_only=True)
    try:
        return [tuple(fila) for fila in libro[hoja].iter_rows(values_only=True)]
    finally:
        libro.close()


def _hojas(ruta: Path) -> list[str]:
    libro = openpyxl.load_workbook(ruta, read_only=True)
    try:
        return list(libro.sheetnames)
    finally:
        libro.close()


# ─────────────────────────── §3.5: un libro por etapa, numerado ───────────────────────────


def test_export_excel_escribe_un_libro_numerado_por_etapa_y_el_de_decisiones(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path).run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    rutas = sc.export_excel()
    carpeta = sc.project_dir / EXCEL_SUBDIR
    assert all(ruta.parent == carpeta for ruta in rutas)
    assert [ruta.name for ruta in rutas] == [
        "01 Datos y muestras.xlsx",
        "02 Análisis exploratorio.xlsx",
        "03 Tramos y WoE.xlsx",
        "04 Selección de variables.xlsx",
        "05 Modelo.xlsx",
        "06 Tarjeta de puntuación.xlsx",
        "07 Calibración.xlsx",
        "08 Desempeño.xlsx",
        "09 Estabilidad.xlsx",
        "10 Validación formal.xlsx",
        "11 Decisiones.xlsx",
    ]
    # La numeración y los nombres son constantes (D-FLU-12): el orden de §3.2 y sus rótulos.
    assert list(STAGE_BOOKS) == [s for s in STAGE_LABELS if s != "report"]
    assert all(STAGE_LABELS[s] in nombre for s, nombre in STAGE_BOOKS.items())
    assert DECISIONS_BOOK == "11 Decisiones.xlsx"

    # Cada libro: el resumen, la tabla de decisión, las tablas del informe del dominio y el índice.
    binning = carpeta / STAGE_BOOKS["binning"]
    hojas = _hojas(binning)
    assert hojas[0] == "Resumen" and hojas[1] == "Decisión" and hojas[-1] == "Índice"
    resumen = sc.summary("binning")
    assert isinstance(resumen, StageSummary)
    lineas = [fila[0] for fila in _filas(binning, "Resumen")[1:]]
    assert lineas[: len(resumen.lines)] == list(resumen.lines)
    decision = _filas(binning, "Decisión")
    assert decision[0] == tuple(sc.results["binning"].columns)
    assert len(decision) - 1 == len(sc.results["binning"].index)
    # Las tablas del informe de ese dominio, con el título que el informe les da, en el índice.
    indice = pd.DataFrame(_filas(binning, "Índice")[1:], columns=_filas(binning, "Índice")[0])
    assert "Resumen de binning — IV por variable" in set(indice["Contenido"])
    assert any(c.startswith("Tabla de binning WoE — variable") for c in indice["Contenido"])
    assert set(indice["Hoja"]) <= set(hojas)


def test_tras_run_until_quedan_solo_los_libros_de_las_etapas_que_corrieron(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path).run(until="selection")
    rutas = sc.export_excel()
    assert [ruta.name for ruta in rutas] == [
        "01 Datos y muestras.xlsx",
        "02 Análisis exploratorio.xlsx",
        "03 Tramos y WoE.xlsx",
        "04 Selección de variables.xlsx",
        "11 Decisiones.xlsx",
    ]


def test_export_excel_sin_correr_se_detiene_y_sin_openpyxl_dice_el_comando(
    fuente: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = _puerta(fuente, tmp_path)
    with pytest.raises(ScorecardInputError, match="llama a run\\(\\) primero"):
        sc.export_excel()
    sc.run(until="data")
    monkeypatch.setattr(export_module, "_openpyxl_disponible", lambda: False)
    with pytest.raises(MissingDependencyError, match=r"nikodym\[excel\]"):
        sc.export_excel()


# ──────────────── §6-9: celda a celda con los exports del informe ────────────────


def test_el_excel_reproduce_celda_a_celda_las_tablas_de_los_exports_del_informe(
    fuente: Path, tmp_path: Path
) -> None:
    """Cada tabla por observación del informe está en el libro de su etapa, celda a celda igual.

    Las dos escrituras pasan por ``report.exports.write_workbook`` con ``exportable_table``; el
    ``.xlsx`` no es byte-determinista (marcas de tiempo del ZIP), así que la igualdad se mide
    sobre las celdas leídas con el mismo lector, encabezados e índice incluidos.
    """
    sc = _puerta(fuente, tmp_path).run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    rutas = {ruta.name: ruta for ruta in sc.export_excel()}
    basename = sc.config.report.basename
    del_informe = sc.project_dir / "reports" / f"{basename}__por_observacion.xlsx"
    assert del_informe.is_file(), sorted(p.name for p in (sc.project_dir / "reports").iterdir())
    hojas_informe = _hojas(del_informe)
    comparadas = 0
    for clave in sorted(PER_OBSERVATION_TABLES):
        dominio = clave.split(".", 1)[0]
        libro = rutas[STAGE_BOOKS[dominio]]
        indice = _filas(libro, "Índice")
        columnas = list(indice[0])
        hoja = next(
            (
                str(fila[columnas.index("Hoja")])
                for fila in indice[1:]
                if fila[columnas.index("Contenido")] == table_title(clave)
            ),
            None,
        )
        assert hoja is not None, (clave, indice)
        hoja_informe = next(h for h in hojas_informe if h == clave.replace(".", "_")[:31])
        assert _filas(libro, hoja) == _filas(del_informe, hoja_informe), clave
        comparadas += 1
    assert comparadas == len(PER_OBSERVATION_TABLES)
    # Y las tablas del anexo salen ENTERAS: la tabla de deciles trae todas sus filas, no el tope
    # de filas visibles del documento.
    deciles = _filas(rutas[STAGE_BOOKS["performance"]], "Desempeño por tramo de riesgo")
    assert len(deciles) - 1 == len(sc.study.artifacts.get("performance", "performance_table"))


def test_las_celdas_activas_de_planilla_salen_protegidas_tambien_en_las_decisiones(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path).run()
    sc.exclude("score", reason="=SUMA(1;2) no es un motivo, es una fórmula")
    sc.resume()
    ruta = next(r for r in sc.export_excel() if r.name == DECISIONS_BOOK)
    humanas = _filas(ruta, "Decisiones humanas")
    columnas = list(humanas[0])
    motivos = [str(fila[columnas.index("Motivo")]) for fila in humanas[1:]]
    assert motivos == ["'=SUMA(1;2) no es un motivo, es una fórmula"]
    autores = {fila[columnas.index("Autor")] for fila in humanas[1:]}
    assert autores == {"usuario"}
    hojas = _hojas(ruta)
    assert hojas == ["Decisiones humanas", "Inferencias de la puerta", "Decisiones del motor"]
    puerta = _filas(ruta, "Inferencias de la puerta")
    assert {fila[columnas.index("Autor")] for fila in puerta[1:]} == {"puerta_guiada"}


# ─────────────────────────── export(): el paquete de la corrida ───────────────────────────


def test_export_empaqueta_la_corrida_vigente_sin_candado_ni_respaldos(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    with pytest.raises(ScorecardInputError, match="llama a run\\(\\) primero"):
        sc.export(tmp_path / "antes.zip")
    sc.run(until="data")
    sc.exclude("score", reason="prueba de respaldo")
    sc.resume()  # deja un `.run.old.*` y el candado `.lock`
    sc.export_excel()
    destino = sc.export(tmp_path / "corrida")  # sin sufijo: se añade `.zip`
    assert destino == tmp_path / "corrida.zip" and destino.is_file()
    with zipfile.ZipFile(destino) as zf:
        nombres = zf.namelist()
    assert all(n.startswith("prueba/") for n in nombres)
    assert "prueba/config.yaml" in nombres
    assert any(n.startswith("prueba/run/") for n in nombres)
    assert any(n.startswith("prueba/reports/") for n in nombres)
    assert any(n.startswith(f"prueba/{EXCEL_SUBDIR}/") for n in nombres)
    assert any(n.startswith("prueba/input/") for n in nombres)  # la copia de los datos
    assert not any("/.lock" in n or "/.run.old." in n or "/.reports." in n for n in nombres)
    assert any(p.name.startswith(".run.old.") for p in sc.project_dir.iterdir())


# ─────────────────────────── D-FLU-8: la misma fuente para la pantalla ───────────────────────────


def test_los_resumenes_serializados_repiten_lo_que_lee_la_persona(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path).run()
    resumen = sc.summary("selection")
    assert isinstance(resumen, StageSummary)
    volcado = resumen.to_dict()
    assert json.loads(json.dumps(volcado, allow_nan=False)) == volcado
    assert volcado["stage"] == "selection" and volcado["label"] == STAGE_LABELS["selection"]
    assert volcado["lines"] == list(resumen.lines)
    tabla = volcado["table"]
    assert tabla is not None and tabla["columns"] == list(sc.results["selection"].columns)
    # Las celdas viajan como las pinta el notebook: texto ya formateado, sin una segunda regla.
    html = resumen._repr_html_()
    for celda in tabla["rows"][0]:
        assert celda in html
    final = sc.summary().to_dict()
    assert final["execution"] == "completada"
    assert [r for r, _ in final["figures"]] == [r for r, _ in sc.summary().figures]
    assert json.loads(json.dumps(final, allow_nan=False)) == final


@pytest.mark.parametrize(
    ("estrategia", "esperado"),
    [
        (
            {
                "type": "temporal",
                "date_col": "fecha",
                "oot_from": "2024-01-01",
                "holdout_fraction": 0.2,
            },
            "fuera de tiempo desde 2024-01-01 por «fecha»; holdout 20 % del resto",
        ),
        (
            {
                "type": "cohort",
                "cohort_col": "cohorte",
                "oot_cohorts": ["2024Q1", "2024Q2"],
                "holdout_fraction": 0.25,
            },
            "cohortes fuera de tiempo: 2024Q1, 2024Q2 (columna «cohorte»); holdout 25 % del resto",
        ),
        (
            {"type": "random", "dev_fraction": 0.7, "holdout_fraction": 0.3, "oot_fraction": 0.0},
            "partición aleatoria: 70 % desarrollo y 30 % holdout, sin muestra fuera de tiempo",
        ),
        (
            {"type": "random", "dev_fraction": 0.6, "holdout_fraction": 0.2, "oot_fraction": 0.2},
            "partición aleatoria: 60 % desarrollo y 20 % holdout, y 20 % fuera de tiempo "
            "(pseudo-OOT)",
        ),
        (
            {"type": "columna", "partition_col": "muestra"},
            "división ya marcada en la columna «muestra»",
        ),
    ],
)
def test_partition_label_es_la_misma_fuente_para_las_dos_puertas(
    estrategia: dict[str, Any], esperado: str
) -> None:
    assert partition_label(estrategia) == esperado


# ──────────── pasada 2 de Codex sobre la capa B: integridad del Excel y del paquete ────────────


def test_export_excel_reemplaza_la_carpeta_entera_y_un_fallo_no_deja_una_mezcla(
    fuente: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tras una corrida completa exportada, una parcial exportada no conserva los libros viejos.

    Y un fallo a mitad de la escritura deja la exportación anterior intacta: la carpeta se
    construye aparte y se sustituye entera (Codex, pasada 2 de B).
    """
    sc = _puerta(fuente, tmp_path).run()
    completa = {p.name: p.read_bytes() for p in sc.export_excel()}
    assert len(completa) == 11
    sc.run(until="selection")
    parcial = {p.name for p in sc.export_excel()}
    carpeta = sc.project_dir / EXCEL_SUBDIR
    assert {p.name for p in carpeta.iterdir()} == parcial
    assert parcial == {
        "01 Datos y muestras.xlsx",
        "02 Análisis exploratorio.xlsx",
        "03 Tramos y WoE.xlsx",
        "04 Selección de variables.xlsx",
        "11 Decisiones.xlsx",
    }
    antes = {p.name: p.read_bytes() for p in carpeta.iterdir()}

    from nikodym.report import exports as exports_module

    original = exports_module.write_workbook  # el export lo importa al llamar, desde aquí
    llamadas = {"n": 0}

    def revienta(*args: Any, **kwargs: Any) -> Any:
        llamadas["n"] += 1
        if llamadas["n"] == 3:
            raise OSError("disco lleno")
        return original(*args, **kwargs)

    monkeypatch.setattr(exports_module, "write_workbook", revienta)
    with pytest.raises(OSError, match="disco lleno"):
        sc.export_excel()
    assert {p.name: p.read_bytes() for p in carpeta.iterdir()} == antes
    assert not [p for p in sc.project_dir.iterdir() if p.name.startswith(f".{EXCEL_SUBDIR}.")]


def test_export_exige_una_corrida_propia_y_empaqueta_esa_evidencia(
    fuente: Path, tmp_path: Path
) -> None:
    """Un DataFrame ya crea la carpeta al publicar su snapshot y un `name` repetido puede
    encontrar una corrida ajena: sin corrida propia no hay paquete (Codex, pasada 2 de B)."""
    frame = pd.read_parquet(fuente).reset_index()
    sin_correr = _puerta(frame, tmp_path, name="paquete")
    assert sin_correr.project_dir.is_dir()  # el snapshot ya vive ahí
    with pytest.raises(ScorecardInputError, match=r"llama a run\(\) primero"):
        sin_correr.export(tmp_path / "antes.zip")
    sin_correr.run(until="data")
    destino = sin_correr.export(tmp_path / "propia.zip")
    with zipfile.ZipFile(destino) as zf:
        metadatos = json.loads(zf.read("paquete/run/study/run_metadata.json"))
    assert metadatos["run_id"] == sin_correr.study.run_context.run_id
    # Otro objeto con el mismo `name`, sin correr, no empaqueta la corrida del primero.
    ajeno = _puerta(frame, tmp_path, name="paquete")
    with pytest.raises(ScorecardInputError, match=r"llama a run\(\) primero"):
        ajeno.export(tmp_path / "ajeno.zip")
