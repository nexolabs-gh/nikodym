"""Los cortes del semáforo por grado en el informe (D-VAL-15, capa A de VALIDACION-COTEJADA).

Tres contratos sobre el artefacto que la persona consume, no sobre la función intermedia:

1. **La prosa nombra los cortes sólo cuando corrió el contraste por grado** (test (c) de §6 de la
   enmienda), leídos de ``metric_sections.validation.traffic_light_cuts`` y no del config, y sin
   atribuir a nadie la elección: el motor no sabe si un corte lo declaró la institución o es el
   default (medido en la enmienda §3.1).
2. **Las dos columnas nuevas de ``calibration`` no se pintan en el documento** (gate (f)): la tabla
   «Validación formal · calibración» del HTML, del Word y del PDF —donde el extra esté— conserva
   exactamente las trece columnas de antes, con y sin contraste; ``green_alpha``/``red_alpha``
   viajan en el JSON, en el CSV y en la card, y el hecho que publican está en prosa (la condición
   que ``_AUDIT_ONLY_COLUMNS`` exige para retirar una columna).
3. **El filtro de columnas de auditoría es por clave de tabla, no por nombre global**: una tabla
   ajena con una columna llamada ``green_alpha`` la sigue pintando (hallazgo 2 de la pasada 8 de
   Codex sobre la enmienda; su control negativo es volver al filtro global por nombre).
"""

from __future__ import annotations

import importlib.util
import io
import re
from datetime import UTC, datetime

import pandas as pd
import pytest

from nikodym.core.lineage import LineageBundle
from nikodym.report.builder import ReportBuilder
from nikodym.report.config import ReportConfig
from nikodym.report.renderer import HtmlReportRenderer, _table_view
from nikodym.report.results import ReportInputBundle
from nikodym.validation.config import CalibrationValidationConfig, ValidationConfig
from nikodym.validation.evaluator import ValidationEvaluator
from nikodym.validation.results import ValidationResult

#: Las trece columnas que la tabla del documento pintaba antes de la capa A, en su orden. Es un
#: literal a propósito —no ``_CALIBRATION_COLUMNS[:-2]``—: el gate promete que el documento no
#: cambia, y una constante que cambie con el motor no puede prometer eso.
_COLUMNAS_PINTADAS: tuple[str, ...] = (
    "partition",
    "test",
    "grade",
    "n",
    "observed_defaults",
    "expected_pd",
    "observed_dr",
    "statistic",
    "degrees_of_freedom",
    "p_value",
    "alpha",
    "decision",
    "traffic_light",
)
_COLUMNAS_DE_AUDITORIA: tuple[str, ...] = ("green_alpha", "red_alpha")
_FRASE_CORTES = "Los cortes son un parámetro de la política de validación de la institución"

_HAS_DOCX = importlib.util.find_spec("docx") is not None


def _weasyprint_utilizable() -> bool:
    """Mismo criterio que ``test_report_pdf``: el paquete instalado no basta, hacen falta las
    librerías nativas; en un Windows sin Pango el import muere con ``OSError``."""
    if importlib.util.find_spec("weasyprint") is None:
        return False
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def _analytic_frame() -> pd.DataFrame:
    """Frame analítico con tres grados y tres particiones (120 operaciones, PD en (0, 1))."""
    partition = ["desarrollo"] * 60 + ["holdout"] * 30 + ["oot"] * 30
    pd_calibrated = [0.02 + (index % 10) * 0.01 for index in range(120)]
    target = [1 if index % 20 == 0 else 0 for index in range(120)]
    grade = ["A" if value < 0.06 else ("B" if value < 0.09 else "C") for value in pd_calibrated]
    return pd.DataFrame(
        {"partition": partition, "target": target, "pd_calibrated": pd_calibrated, "grade": grade},
        index=[f"r{i}" for i in range(120)],
    )


def _resultado(*, contraste: bool) -> ValidationResult:
    """Un ``ValidationResult`` real del evaluador, con cortes distintos de ``alpha`` a propósito.

    Los cortes 0,10/0,02 con ``alpha=0.05`` son los mismos del test (e) del step: si el informe
    dijera 0,05 estaría leyendo la significancia, no un corte.
    """
    cfg = ValidationConfig(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5,
            min_rows_per_group=10,
            binomial_by_grade=contraste,
            alpha=0.05,
            traffic_light_green_alpha=0.10,
            traffic_light_red_alpha=0.02,
        ),
    )
    return ValidationEvaluator.from_config(cfg).validate(
        calibrated_pd=_analytic_frame(), model_ref="scorecard-cortes"
    )


def _lineage() -> LineageBundle:
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123456789abcdef",
        config_hash="cfg123456789abcdef",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "1.16.0"},
        determinism_caveats=[],
        created_at=datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _bundle(result: ValidationResult) -> ReportInputBundle:
    """El bundle como lo arma el builder: card volcada, resultado y la tabla de la única familia
    corrida (las otras tres saldrían vacías al anexo y ensuciarían el censo de encabezados)."""
    cfg = ReportConfig(sections={"missing_policy": "skip"})
    bundle = ReportInputBundle(
        lineage=_lineage(),
        cards={"validation": result.card.model_dump(mode="python")},
        results={"validation": result},
        tables={"validation.calibration": result.calibration},
        figures={},
        sections=(),
    )
    return bundle.model_copy(update={"sections": ReportBuilder(cfg).build_sections(bundle)})


def _html(result: ValidationResult) -> str:
    return HtmlReportRenderer(ReportConfig(sections={"missing_policy": "skip"})).render(
        _bundle(result)
    )


def _encabezados_html(html: str) -> list[str]:
    tabla = re.search(
        r'<table[^>]*data-table-key="validation\.calibration"[^>]*>(.*?)</table>', html, re.S
    )
    assert tabla is not None, "el documento no trae la tabla validation.calibration"
    return re.findall(r"<th>(.*?)</th>", tabla.group(1))


def _seccion_calibracion(html: str) -> str:
    seccion = re.search(
        r'<section[^>]*id="section-validation-calibration"[^>]*>(.*?)</section>', html, re.S
    )
    assert seccion is not None, "el documento no trae la sección validation.calibration"
    return seccion.group(1)


# ─────────────────── (c) la prosa nombra los cortes sólo con contraste ───────────────────


def test_la_prosa_nombra_los_dos_cortes_leidos_de_la_card_cuando_corrio_el_contraste() -> None:
    """Con el contraste corrido, el capítulo dice con qué p-valor un grado queda en verde, ámbar o
    rojo, con los cortes de la corrida (0,10/0,02, no los defaults 0,05/0,01 que también nombra
    como lo que trae el motor) y sin atribuir la elección a nadie."""
    seccion = _seccion_calibracion(_html(_resultado(contraste=True)))
    assert _FRASE_CORTES in seccion
    assert "p-valor de al menos 0,10" in seccion
    assert "entre 0,02 y 0,10" in seccion
    assert "por debajo de 0,02" in seccion
    assert "el motor trae 0,05 y 0,01 por defecto" in seccion
    assert "no un umbral fijado por norma" in seccion
    assert "la institución fijó" not in seccion
    assert "Basilea" not in seccion


def test_la_prosa_no_redondea_un_corte_hasta_describir_otra_politica() -> None:
    """Pasada 1 de Codex sobre la capa A: la config admite cualquier ``0 < rojo < verde < 1``, y
    con cortes de más de cuatro decimales la frase decía «0,05» para un corte 0,05004 —un grado
    con p = 0,05002 queda en ámbar en el motor mientras el informe afirma que debería estar en
    verde—. Los cortes se escriben con todos sus dígitos, sin notación científica."""
    from nikodym.report.prose import _cut

    assert _cut(0.05004) == "0,05004"
    assert _cut(0.01004) == "0,01004"
    assert _cut(0.05) == "0,05"
    assert _cut(0.1) == "0,10"
    assert _cut(0.00001) == "0,00001"
    assert _cut(1.5e-7) == "0,00000015"
    assert _cut(0.123456789) == "0,123456789"
    # Pasada 2 de Codex: un exponente menor que −100 es válido para la config y tiene que salir
    # entero, en posicional, sin que ningún formateador reviente.
    assert _cut(1e-101) == "0," + "0" * 100 + "1"

    cfg = ValidationConfig(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5,
            min_rows_per_group=10,
            traffic_light_green_alpha=0.05004,
            traffic_light_red_alpha=0.01004,
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    seccion = _seccion_calibracion(_html(result))
    assert "p-valor de al menos 0,05004" in seccion
    assert "entre 0,01004 y 0,05004" in seccion
    assert "al menos 0,05," not in seccion


def test_sin_contraste_por_grado_la_prosa_calla_los_cortes() -> None:
    """Sin contraste no hay semáforo que explicar: ninguna frase de cortes, ningún número."""
    html = _html(_resultado(contraste=False))
    seccion = _seccion_calibracion(html)
    assert _FRASE_CORTES not in seccion
    assert "p-valor de al menos" not in seccion
    assert _FRASE_CORTES not in html


# ─────────────────── (f) el documento no pinta las columnas nuevas ───────────────────


@pytest.mark.parametrize("contraste", [True, False], ids=["con_contraste", "sin_contraste"])
def test_el_html_conserva_las_trece_columnas_de_la_tabla_de_calibracion(contraste: bool) -> None:
    """La tabla del documento es byte a byte la de antes en sus encabezados: las dos columnas
    nuevas van en el JSON/CSV y en la card, y el hecho que publican está en prosa."""
    result = _resultado(contraste=contraste)
    assert tuple(result.calibration.columns) == (*_COLUMNAS_PINTADAS, *_COLUMNAS_DE_AUDITORIA)
    html = _html(result)
    assert tuple(_encabezados_html(html)) == _COLUMNAS_PINTADAS
    for columna in _COLUMNAS_DE_AUDITORIA:
        assert f"<th>{columna}</th>" not in html
        assert f"<td>{columna}</td>" not in html


@pytest.mark.skipif(not _HAS_DOCX, reason="requiere el extra docx (python-docx)")
@pytest.mark.parametrize("contraste", [True, False], ids=["con_contraste", "sin_contraste"])
def test_el_word_conserva_las_trece_columnas_y_lleva_los_cortes_en_prosa(contraste: bool) -> None:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    from nikodym.report.docx import DocxReportRenderer

    payload = DocxReportRenderer.from_config(
        ReportConfig(sections={"missing_policy": "skip"})
    ).render(_bundle(_resultado(contraste=contraste)))
    word = docx.Document(io.BytesIO(payload))
    # Sólo el CUERPO del documento: los anexos de auditoría vuelcan la card entera (con sus
    # cortes) y ahí el nombre del campo es el dato, como los códigos de aviso en el anexo del HTML.
    parrafos: list[str] = []
    tablas: list[Table] = []
    for hijo in word.element.body.iterchildren():
        if hijo.tag.endswith("}p"):
            parrafo = Paragraph(hijo, word)
            if parrafo.style.name == "Heading 1" and parrafo.text.startswith("Anexo"):
                break
            parrafos.append(parrafo.text)
        elif hijo.tag.endswith("}tbl"):
            tablas.append(Table(hijo, word))
    assert parrafos and tablas, "el cuerpo del Word no se pudo recorrer"
    encabezados = [
        tuple(cell.text for cell in table.rows[0].cells)
        for table in tablas
        if table.rows and table.rows[0].cells[0].text == "partition"
    ]
    assert encabezados == [_COLUMNAS_PINTADAS]
    texto = "\n".join(parrafos)
    for columna in _COLUMNAS_DE_AUDITORIA:
        assert columna not in texto
        assert not any(
            columna in cell.text for table in tablas for row in table.rows for cell in row.cells
        )
    assert (_FRASE_CORTES in texto) is contraste


@pytest.mark.skipif(not _weasyprint_utilizable(), reason="requiere WeasyPrint con sus nativas")
def test_el_pdf_lleva_los_cortes_en_prosa_y_no_como_columnas() -> None:
    from pypdf import PdfReader

    from nikodym.report.pdf import render_pdf

    pdf = render_pdf(_html(_resultado(contraste=True)))
    texto = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "política de validación de la institución" in texto
    for columna in _COLUMNAS_DE_AUDITORIA:
        assert columna not in texto


# ─────────────────── el filtro de auditoría es por clave de tabla ───────────────────


def test_el_renderer_retira_las_columnas_de_auditoria_solo_en_la_tabla_de_calibracion() -> None:
    """Una variable del usuario llamada ``green_alpha`` en otra tabla se sigue pintando: el filtro
    se indexa por clave de tabla. Control negativo: volver al filtro global por nombre pone rojo
    la segunda mitad."""
    tabla = pd.DataFrame({"feature": ["x"], "green_alpha": [0.5], "red_alpha": [0.1]})
    calibracion = _table_view("validation.calibration", tabla, max_rows=10)
    assert calibracion["columns"] == ["feature"]
    ajena = _table_view("selection.correlations", tabla, max_rows=10)
    assert ajena["columns"] == ["feature", "green_alpha", "red_alpha"]


def test_warning_codes_conserva_su_alcance_global() -> None:
    """La columna de códigos de aviso sigue retirada en TODAS las tablas, como hasta ahora."""
    tabla = pd.DataFrame({"stage": [1], "warning_codes": ["FALTA-DATO-IFRS-4"]})
    for clave in ("provisioning_ifrs9.ecl_by_stage", "validation.calibration", "otra.tabla"):
        assert _table_view(clave, tabla, max_rows=10)["columns"] == ["stage"]
