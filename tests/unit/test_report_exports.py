"""Tests de ``report.exports``: las tablas por observación, completas y fuera del documento.

El criterio de aceptación es que el adjunto sirva **como dato**: completo (sin truncar), con el
identificador de la operación intacto y abrible por quien lo reciba. Los tests que escriben
``.xlsx`` van gateados con ``skipif`` sobre ``openpyxl`` (extra ``excel``), como en
``test_data_loading``: el job mínimo del CI instala sin extras y correrlos allí lo reventaría.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from nikodym.report.config import ReportConfig, SectionPolicyConfig
from nikodym.report.document import PER_OBSERVATION_TABLES
from nikodym.report.exceptions import ReportExportError
from nikodym.report.exports import (
    DATA_EXPORT_FORMATS,
    data_export_refs,
    per_observation_tables,
    write_data_exports,
)

_HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None


def _score_frame(rows: int = 350) -> pd.DataFrame:
    """Frame por observación de ``rows`` filas, con ``loan_id`` como índice (el identificador)."""
    return pd.DataFrame(
        {
            "score": [600 + index for index in range(rows)],
            "pd_calibrated": [0.01 + index / 10_000 for index in range(rows)],
            "partición": ["desarrollo"] * rows,  # acento: el CSV debe conservarlo legible
        },
        index=pd.Index([f"op-{index:06d}" for index in range(rows)], name="loan_id"),
    )


def _tables() -> dict[str, pd.DataFrame]:
    """Bundle con una tabla por observación y una agregada (que NO debe exportarse)."""
    return {
        "scorecard.score": _score_frame(),
        "model.coefficients": pd.DataFrame({"feature": ["mora"], "beta": [1.25]}),
    }


def test_solo_las_tablas_por_observacion_son_adjuntos() -> None:
    """El criterio es la NATURALEZA de la tabla, no su tamaño: una agregada no sale del informe."""
    assert per_observation_tables(_tables()) == ("scorecard.score",)
    assert "model.coefficients" not in PER_OBSERVATION_TABLES
    assert frozenset({"csv", "xlsx"}) == DATA_EXPORT_FORMATS


def test_sin_csv_ni_xlsx_no_hay_adjuntos_ni_archivos(tmp_path: Path) -> None:
    """Sin formato de datos pedido no se escribe nada: el documento lo declara, no lo inventa."""
    config = ReportConfig(formats=("html",))

    assert data_export_refs(_tables(), config=config) == ()
    assert write_data_exports(_tables(), config=config, output_dir=str(tmp_path)) == {}
    assert list(tmp_path.iterdir()) == []


def test_csv_completo_sin_truncar_y_con_el_identificador(tmp_path: Path) -> None:
    """El adjunto se escribe COMPLETO: ``max_table_rows`` acota lo que se muestra, no lo que se da.

    Es el punto entero del cambio: truncada a 200 filas, la tabla no servía ni como dato (estaba
    incompleta) ni como informe. Aquí se exige lo contrario: 350 filas dentro, 350 filas fuera.
    """
    config = ReportConfig(
        formats=("html", "csv"),
        sections=SectionPolicyConfig(max_table_rows=10),  # el documento trunca; el dato NO
    )

    exports = write_data_exports(_tables(), config=config, output_dir=str(tmp_path))

    assert set(exports) == {"scorecard_report__scorecard_score.csv"}
    path = Path(exports["scorecard_report__scorecard_score.csv"])
    assert path.is_file()

    leido = pd.read_csv(path, encoding="utf-8-sig")
    assert len(leido) == 350  # completo, pese a max_table_rows=10
    assert leido.columns[0] == "loan_id"  # el índice es el identificador: no se pierde
    assert leido.iloc[0]["loan_id"] == "op-000000"
    assert leido.iloc[-1]["loan_id"] == "op-000349"
    assert "partición" in leido.columns  # el acento sobrevive al round-trip

    # La tabla agregada NO se exporta: se queda en el documento, que es donde se revisa.
    assert not list(tmp_path.glob("*coefficients*"))


def test_csv_es_byte_determinista(tmp_path: Path) -> None:
    """Dos escrituras del mismo frame producen bytes idénticos (reproducibilidad regulatoria)."""
    config = ReportConfig(formats=("csv",))

    primero = write_data_exports(_tables(), config=config, output_dir=str(tmp_path / "a"))
    segundo = write_data_exports(_tables(), config=config, output_dir=str(tmp_path / "b"))

    assert (
        Path(next(iter(primero.values()))).read_bytes()
        == Path(next(iter(segundo.values()))).read_bytes()
    )


def test_referencias_de_adjunto_son_puras_y_nombran_el_archivo_real(tmp_path: Path) -> None:
    """``data_export_refs`` (sin tocar disco) nombra exactamente los archivos que se escribirán.

    Es lo que permite que el documento diga "el detalle va en el archivo X" en el mismo render en
    que se decide emitirlo, sin adivinar el nombre ni referenciar un archivo inexistente.
    """
    config = ReportConfig(formats=("csv",))

    refs = data_export_refs(_tables(), config=config)
    exports = write_data_exports(_tables(), config=config, output_dir=str(tmp_path))

    assert [ref.filename for ref in refs] == list(exports)
    assert refs[0].table_key == "scorecard.score"
    assert refs[0].title == "Puntaje por observación"  # título legible, no la clave interna
    assert refs[0].rows == 350  # el tamaño REAL, no el truncado
    assert refs[0].sheet == ""  # el csv es un archivo por tabla, sin hojas


def test_export_crea_el_directorio_de_salida_si_falta(tmp_path: Path) -> None:
    """El export crea su directorio, igual que el HTML, el PDF y el ``.docx``: sin preflight."""
    destino = tmp_path / "aun" / "no" / "existe"

    exports = write_data_exports(
        _tables(), config=ReportConfig(formats=("csv",)), output_dir=str(destino)
    )

    assert Path(exports["scorecard_report__scorecard_score.csv"]).is_file()


def test_export_falla_con_error_accionable_si_la_ruta_no_es_escribible(tmp_path: Path) -> None:
    """Un fallo de escritura es un ``ReportExportError`` con acción, no un ``OSError`` desnudo."""
    ocupado = tmp_path / "ocupado"
    ocupado.write_text("no soy un directorio", encoding="utf-8")

    with pytest.raises(ReportExportError, match="acción="):
        write_data_exports(
            _tables(), config=ReportConfig(formats=("csv",)), output_dir=str(ocupado)
        )


@pytest.mark.skipif(not _HAS_OPENPYXL, reason="requiere el extra excel (openpyxl)")
def test_xlsx_un_libro_con_una_hoja_por_tabla(tmp_path: Path) -> None:
    """El ``.xlsx`` es UN libro con una hoja por tabla por observación, completa y con su índice."""
    import openpyxl

    config = ReportConfig(formats=("html", "xlsx"), sections=SectionPolicyConfig(max_table_rows=10))
    tables = {**_tables(), "model.raw_pd_frame": _score_frame(rows=12)}

    exports = write_data_exports(tables, config=config, output_dir=str(tmp_path))

    assert set(exports) == {"scorecard_report__por_observacion.xlsx"}
    libro = openpyxl.load_workbook(exports["scorecard_report__por_observacion.xlsx"])
    assert libro.sheetnames == ["model_raw_pd_frame", "scorecard_score"]
    hoja = libro["scorecard_score"]
    assert hoja.max_row == 351  # 350 filas + encabezado: completo
    assert hoja.cell(row=1, column=1).value == "loan_id"
    assert hoja.cell(row=2, column=1).value == "op-000000"


@pytest.mark.skipif(not _HAS_OPENPYXL, reason="requiere el extra excel (openpyxl)")
def test_csv_y_xlsx_conviven_como_adjuntos_distintos(tmp_path: Path) -> None:
    """Pedir ambos formatos entrega ambos archivos; ninguno pisa al otro."""
    config = ReportConfig(formats=("csv", "xlsx"))

    exports = write_data_exports(_tables(), config=config, output_dir=str(tmp_path))

    assert set(exports) == {
        "scorecard_report__scorecard_score.csv",
        "scorecard_report__por_observacion.xlsx",
    }
    assert all(Path(path).is_file() for path in exports.values())


def test_nombre_de_hoja_excel_respeta_el_limite_de_31_caracteres() -> None:
    """Excel rechaza hojas de más de 31 caracteres: el nombre se recorta, no revienta al abrir."""
    config = ReportConfig(formats=("xlsx",))
    tables = {key: _score_frame(rows=2) for key in PER_OBSERVATION_TABLES}

    refs = data_export_refs(tables, config=config)

    assert len(refs) == len(PER_OBSERVATION_TABLES)
    hojas = [ref.sheet for ref in refs]
    assert all(len(hoja) <= 31 for hoja in hojas)
    assert len(set(hojas)) == len(hojas)  # sin colisiones tras el recorte
