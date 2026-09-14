"""Un Hosmer-Lemeshow sin veredicto en el informe (D-VAL-17, capa B de VALIDACION-COTEJADA).

Tres contratos sobre el artefacto que la persona consume, no sobre la función intermedia:

1. **La prosa enumera cada partición sin veredicto y su causa en palabras**, leyendo
   ``metric_sections.validation.not_evaluable_partitions`` de la card, con los números que
   explican la causa (operaciones, tamaño del grupo más chico, mínimo); y **una validación sin
   ninguna prueba evaluable dice «No evaluable», nunca «Pasa»** (§8-9 de la enmienda).
2. **La columna de la causa no se pinta en el documento** (gate del artefacto de §6): la tabla
   «Validación formal · calibración» del HTML, del Word y del PDF —donde el extra esté— conserva
   las trece columnas de siempre, y ni el encabezado ``not_evaluable_reason`` ni ninguno de los
   cuatro literales de causa aparece fuera del anexo de auditoría (el anexo vuelca la card, y ahí
   el identificador es el dato). Su control negativo preespecificado: quitar la columna del filtro
   por clave de tabla del renderer.
3. **El filtro sigue siendo por clave de tabla**: una tabla ajena con una columna llamada
   ``not_evaluable_reason`` la sigue pintando.

El resultado se construye con el evaluador real sobre un frame con las CUATRO causas a la vez:
``min_rows_per_group=3`` y diez grupos dejan una partición de 2 filas bajo el mínimo
(``partition_below_min``), una de 25 con grupos de 2 (``group_below_min``), una de 5 con grupos
vacíos (``degenerate_group``) y una de 100 con PD subnormal cuyo estadístico desborda
(``non_finite_statistic``).
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
from nikodym.validation.results import HL_NOT_EVALUABLE_REASON_LABELS, ValidationResult

#: Las trece columnas que la tabla del documento pinta, en su orden (literal a propósito).
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
_COLUMNAS_DE_AUDITORIA: tuple[str, ...] = ("green_alpha", "red_alpha", "not_evaluable_reason")
_CAUSAS: tuple[str, ...] = (
    "partition_below_min",
    "group_below_min",
    "degenerate_group",
    "non_finite_statistic",
)
_FRASE_HL = "Hosmer-Lemeshow no se evaluó"

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


def _frame_con_las_cuatro_causas() -> pd.DataFrame:
    """Cuatro particiones, una por causa, sobre PD en (0, 1) y target binario."""
    filas: list[tuple[str, int, float]] = []
    # 2 filas < mínimo 3 → partition_below_min.
    filas += [("bajo_minimo", 0, 0.2), ("bajo_minimo", 1, 0.2)]
    # 25 filas en 10 grupos → grupos de 3 y 2 → el más chico (2) < 3 → group_below_min.
    filas += [("grupo_bajo_minimo", 1 if i % 5 == 0 else 0, 0.2) for i in range(25)]
    # 5 filas en 10 grupos → grupos vacíos → degenerate_group.
    filas += [("grupo_degenerado", 1 if i == 0 else 0, 0.2) for i in range(5)]
    # 100 filas con PD subnormal (> 0) y un default: el cociente desborda → non_finite_statistic.
    filas += [("no_finito", 1 if i % 10 == 0 else 0, 5e-324) for i in range(100)]
    return pd.DataFrame(
        {
            "partition": [f[0] for f in filas],
            "target": [f[1] for f in filas],
            "pd_calibrated": [f[2] for f in filas],
        },
        index=[f"r{i}" for i in range(len(filas))],
    )


def _resultado() -> ValidationResult:
    cfg = ValidationConfig(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=10, min_rows_per_group=3, binomial_by_grade=False
        ),
    )
    return ValidationEvaluator.from_config(cfg).validate(
        calibrated_pd=_frame_con_las_cuatro_causas(), model_ref="scorecard-hl"
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


def _html_con_tablas(result: ValidationResult, tables: dict[str, pd.DataFrame]) -> str:
    cfg = ReportConfig(sections={"missing_policy": "skip"})
    bundle = ReportInputBundle(
        lineage=_lineage(),
        cards={"validation": result.card.model_dump(mode="python")},
        results={"validation": result},
        tables=tables,
        figures={},
        sections=(),
    )
    bundle = bundle.model_copy(update={"sections": ReportBuilder(cfg).build_sections(bundle)})
    return HtmlReportRenderer(cfg).render(bundle)


def _cuerpo_html(html: str) -> str:
    """El documento hasta el primer anexo: los anexos vuelcan la card entera, con sus slugs."""
    corte = html.find('id="section-appendix')
    assert corte != -1, "el documento no trae anexos"
    return html[:corte]


def _encabezados_html(html: str) -> list[str]:
    tabla = re.search(
        r'<table[^>]*data-table-key="validation\.calibration"[^>]*>(.*?)</table>', html, re.S
    )
    assert tabla is not None, "el documento no trae la tabla validation.calibration"
    return re.findall(r"<th>(.*?)</th>", tabla.group(1))


def _seccion(html: str, seccion: str) -> str:
    bloque = re.search(rf'<section[^>]*id="section-{seccion}"[^>]*>(.*?)</section>', html, re.S)
    assert bloque is not None, f"el documento no trae la sección {seccion}"
    return bloque.group(1)


def _resumen_ejecutivo(html: str) -> str:
    """La sección ejecutiva lleva su propio id (``exec-summary``), sin el prefijo ``section-``."""
    bloque = re.search(r'<section[^>]*id="exec-summary"[^>]*>(.*?)</section>', html, re.S)
    assert bloque is not None, "el documento no trae el resumen ejecutivo"
    return bloque.group(1)


# ─────────────────── el resultado trae las cuatro causas ───────────────────


def test_el_resultado_publica_las_cuatro_causas_y_ninguna_prueba_evaluable() -> None:
    result = _resultado()
    hl = {r.partition: r for r in result.calibration_records if r.test == "hosmer_lemeshow"}
    assert {p: r.not_evaluable_reason for p, r in hl.items()} == {
        "bajo_minimo": "partition_below_min",
        "grupo_bajo_minimo": "group_below_min",
        "grupo_degenerado": "degenerate_group",
        "no_finito": "non_finite_statistic",
    }
    assert all(r.statistic is None for r in hl.values())
    assert result.card.n_tests == 0
    assert result.card.overall_status == "not_evaluable"
    publicadas = result.card.metric_sections["validation"]["not_evaluable_partitions"]
    assert [p["reason"] for p in publicadas] == list(_CAUSAS)
    assert tuple(result.calibration.columns) == (*_COLUMNAS_PINTADAS, *_COLUMNAS_DE_AUDITORIA)


# ─────────────────── (1) la prosa enumera y no dice «Pasa» ───────────────────


def test_la_prosa_enumera_cada_particion_sin_veredicto_con_su_causa_en_palabras() -> None:
    html = _html(_resultado())
    seccion = _seccion(html, "validation-calibration")
    assert seccion.count(_FRASE_HL) == 4
    assert "bajo_minimo" in seccion and "no_finito" in seccion
    # Cada causa con sus números: la partición entera (2 < 3), el grupo más chico (2 < 3), los
    # grupos vacíos y el estadístico que desbordó.
    assert "2 operaciones" in seccion and "bajo el mínimo de 3" in seccion
    assert "grupo de PD más chico quedó con 2 operaciones" in seccion
    assert HL_NOT_EVALUABLE_REASON_LABELS["degenerate_group"] in seccion
    assert HL_NOT_EVALUABLE_REASON_LABELS["non_finite_statistic"] in seccion
    for causa in _CAUSAS:
        assert causa not in seccion, causa


def test_sin_ninguna_prueba_evaluable_el_capitulo_dice_no_evaluable_y_nunca_pasa() -> None:
    html = _html(_resultado())
    cuerpo = _cuerpo_html(html)
    intro = _seccion(html, "validation")
    assert "«No evaluable»" in intro
    assert "«Pasa»" not in cuerpo
    assert "ninguna prueba con veredicto" in intro
    # Con HL sin veredicto de verdad, el capítulo remite a su enumeración en la familia.
    assert "quedaron sin veredicto y se enumeran, con su causa" in intro
    # Y la métrica ejecutiva —la única de este bundle— sale con la banda neutra, no verde, y sin
    # el «0 de 0 pruebas fallidas» que sería cierto y engañoso a la vez.
    ejecutivo = _resumen_ejecutivo(html)
    assert "No evaluable" in ejecutivo
    assert "band-none" in ejecutivo
    assert "band-ok" not in ejecutivo
    assert "0 de 0" not in ejecutivo
    assert "Sin pruebas de pasa o falla" in ejecutivo


@pytest.mark.parametrize(("valor_psi", "estado"), [(0.05, "pass"), (0.18, "warn"), (0.3, "fail")])
def test_con_solo_estabilidad_evaluable_la_prosa_no_niega_la_evidencia(
    valor_psi: float, estado: str
) -> None:
    """Pasada 1 de Codex sobre la capa B: ``n_tests`` excluye la estabilidad pero el estado sí la
    usa; con ``families=("stability",)`` y un PSI con decisión el resultado tiene ``n_tests == 0`` y
    un estado evaluable, y la prosa decía «Sin pruebas evaluables» y atribuía el cero a falta de
    potencia. El capítulo dice ahora que no hay pruebas de pasa o falla y que el estado se
    consolidó sobre la estabilidad; la métrica ejecutiva usa las palabras del panel."""
    cfg = ValidationConfig(families=("stability",))
    metrics = pd.DataFrame(
        {
            "metric": ["score_psi"],
            "comparison": ["dev_vs_oot"],
            "feature": ["score"],
            "value": [valor_psi],
        }
    )
    result = ValidationEvaluator.from_config(cfg).validate(stability_metrics=metrics)
    assert (result.card.n_tests, result.card.overall_status) == (0, estado)
    html = _html_con_tablas(result, {"validation.stability": result.stability})
    intro = _seccion(html, "validation")
    assert "se consolida sobre la estabilidad" in intro
    assert "no alcanzaron potencia" not in intro
    assert "No evaluable" not in intro
    ejecutivo = _resumen_ejecutivo(html)
    assert "Sin pruebas de pasa o falla" in ejecutivo
    assert "Sin pruebas evaluables" not in ejecutivo
    from nikodym.validation.results import VALIDATION_STATUS_LABELS

    assert VALIDATION_STATUS_LABELS[estado] in ejecutivo


def test_la_familia_de_calibracion_no_llama_evaluadas_a_las_filas_sin_veredicto() -> None:
    """Pasada 2 de Codex sobre la capa B: «Filas evaluadas: 8» convivía con cuatro frases de
    «Hosmer-Lemeshow no se evaluó». Con filas sin veredicto la frase cuenta lo publicado y lo que
    quedó sin veredicto (el Brier es un puntaje y no cuenta como sin veredicto); sin ellas, la
    frase de siempre —la demo F1 la lleva con «Filas evaluadas: 6» y no se recaptura—."""
    seccion = _seccion(_html(_resultado()), "validation-calibration")
    assert "Filas evaluadas" not in seccion
    assert "Filas publicadas: 8" in seccion
    assert "4 sin veredicto" in seccion


@pytest.mark.parametrize(
    ("config", "familias_con_filas"),
    [
        (
            ValidationConfig(
                families=("calibration",),
                calibration=CalibrationValidationConfig(
                    hosmer_lemeshow=False, binomial_by_grade=False
                ),
            ),
            ("calibration",),
        ),
        (ValidationConfig(families=("discrimination",)), ("discrimination",)),
    ],
    ids=["solo_brier", "solo_discriminacion"],
)
def test_sin_ninguna_prueba_la_prosa_no_inventa_falta_de_potencia(
    config: ValidationConfig, familias_con_filas: tuple[str, ...]
) -> None:
    """Pasada 2 de Codex sobre la capa B: el estado «No evaluable» también sale con sólo el
    puntaje de Brier, con las pruebas apagadas o con la discriminación sola, y la prosa afirmaba
    que «las pruebas que no alcanzaron potencia … se enumeran, con su causa». Sin ningún
    Hosmer-Lemeshow sin veredicto la frase es neutra: dice qué no hay, no inventa por qué."""
    n = 300
    frame = pd.DataFrame(
        {
            "partition": ["desarrollo"] * n,
            "target": [1 if i % 10 == 0 else 0 for i in range(n)],
            "pd_calibrated": [0.1 + 0.001 * (i % 7) for i in range(n)],
        },
        index=[f"r{i}" for i in range(n)],
    )
    performance = pd.DataFrame(
        {
            "partition": ["desarrollo"],
            "n_total": [n],
            "n_bad": [30],
            "auc": [0.7],
            "gini": [0.4],
            "ks": [0.3],
            "status": ["ok"],
        }
    )
    result = ValidationEvaluator.from_config(config).validate(
        calibrated_pd=frame, performance_metrics=performance
    )
    assert (result.card.n_tests, result.card.overall_status) == (0, "not_evaluable")
    assert result.card.metric_sections["validation"]["not_evaluable_partitions"] == []
    tablas = {f"validation.{f}": getattr(result, f) for f in familias_con_filas}
    html = _html_con_tablas(result, tablas)
    intro = _seccion(html, "validation")
    assert "«No evaluable»" in intro
    assert "ninguna prueba con veredicto de pasa o falla" in intro
    assert "potencia" not in intro
    assert "se enumeran" not in intro
    assert _FRASE_HL not in html
    # Y la familia con filas sigue con la frase de siempre: el Brier o la discriminación se
    # publicaron; nada quedó sin veredicto.
    for familia in familias_con_filas:
        cuerpo = _seccion(html, f"validation-{familia}")
        assert "Filas evaluadas" in cuerpo
        assert "sin veredicto" not in cuerpo


def test_el_backtesting_sin_veredicto_se_cuenta_en_su_familia() -> None:
    """Un contraste realizado-vs-estimado que no se pudo correr (sin dispersión) figura en la
    tabla con ``not_evaluable``; su familia lo cuenta como sin veredicto en vez de llamarlo
    evaluado, y el capítulo no le atribuye una causa que el motor no publica."""
    from nikodym.validation.config import BacktestingValidationConfig

    n = 40
    detail = pd.DataFrame(
        {
            "row_id": [f"r{i}" for i in range(n)],
            "portfolio": ["retail"] * n,
            "pd_12m": [0.05] * n,
            "lgd": [0.45] * n,
            "ead": [1000.0] * n,
        },
        index=[f"r{i}" for i in range(n)],
    )
    realised = pd.DataFrame(
        {
            "realised_default": [1.0 if i % 20 == 0 else 0.0 for i in range(n)],
            "realised_lgd": [0.55] * n,
            "realised_ead": [1100.0] * n,
        },
        index=[f"r{i}" for i in range(n)],
    )
    cfg = ValidationConfig(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(
            enabled=True, segment_col="portfolio", parameters=("lgd", "ead")
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(ifrs9_detail=detail, realised=realised)
    assert all(r.decision == "not_evaluable" for r in result.backtest_records)
    assert (result.card.n_tests, result.card.overall_status) == (0, "not_evaluable")
    html = _html_con_tablas(result, {"validation.backtesting": result.backtesting})
    cuerpo = _seccion(html, "validation-backtesting")
    assert "Filas publicadas: 2" in cuerpo
    assert "2 sin veredicto" in cuerpo
    assert "Filas evaluadas" not in cuerpo
    intro = _seccion(html, "validation")
    assert "potencia" not in intro and "causa" not in intro


def test_con_hosmer_lemeshow_evaluable_la_prosa_no_enumera_nada() -> None:
    n = 300
    frame = pd.DataFrame(
        {
            "partition": ["desarrollo"] * n,
            "target": [1 if i % 10 == 0 else 0 for i in range(n)],
            "pd_calibrated": [0.1] * n,
        },
        index=[f"r{i}" for i in range(n)],
    )
    cfg = ValidationConfig(
        families=("calibration",),
        calibration=CalibrationValidationConfig(binomial_by_grade=False),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=frame)
    assert result.card.metric_sections["validation"]["not_evaluable_partitions"] == []
    html = _html(result)
    assert _FRASE_HL not in html


# ─────────────────── (2) el documento no pinta la causa ───────────────────


def test_el_html_conserva_las_trece_columnas_y_no_pinta_ninguna_causa() -> None:
    html = _html(_resultado())
    assert tuple(_encabezados_html(html)) == _COLUMNAS_PINTADAS
    cuerpo = _cuerpo_html(html)
    for columna in _COLUMNAS_DE_AUDITORIA:
        assert f"<th>{columna}</th>" not in html
        assert f"<td>{columna}</td>" not in html
    for causa in _CAUSAS:
        assert causa not in cuerpo, causa
    # El anexo de auditoría sí las conserva: ahí el identificador es el dato.
    assert "not_evaluable_partitions" in html


@pytest.mark.skipif(not _HAS_DOCX, reason="requiere el extra docx (python-docx)")
def test_el_word_conserva_las_trece_columnas_y_lleva_las_causas_en_prosa() -> None:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    from nikodym.report.docx import DocxReportRenderer

    payload = DocxReportRenderer.from_config(
        ReportConfig(sections={"missing_policy": "skip"})
    ).render(_bundle(_resultado()))
    word = docx.Document(io.BytesIO(payload))
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
    celdas = [cell.text for table in tablas for row in table.rows for cell in row.cells]
    for literal in (*_COLUMNAS_DE_AUDITORIA, *_CAUSAS):
        assert literal not in texto, literal
        assert not any(literal in celda for celda in celdas), literal
    assert texto.count(_FRASE_HL) == 4
    assert "«No evaluable»" in texto
    assert "«Pasa»" not in texto


@pytest.mark.skipif(not _weasyprint_utilizable(), reason="requiere WeasyPrint con sus nativas")
def test_el_pdf_lleva_las_causas_en_prosa_y_no_como_columna() -> None:
    from pypdf import PdfReader

    from nikodym.report.pdf import render_pdf

    pdf = render_pdf(_html(_resultado()))
    paginas = [page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages]
    texto = "".join(paginas)
    assert _FRASE_HL in texto
    # Las páginas del cuerpo: hasta la primera que abre un anexo.
    cuerpo = "".join(
        pagina for pagina in paginas[: next(i for i, p in enumerate(paginas) if "Anexo" in p)]
    )
    for literal in (*_COLUMNAS_DE_AUDITORIA, *_CAUSAS):
        assert literal not in cuerpo, literal


# ─────────────────── (3) el filtro es por clave de tabla ───────────────────


def test_el_renderer_retira_la_causa_solo_en_la_tabla_de_calibracion() -> None:
    """Control negativo: volver al filtro global por nombre pone rojo la segunda mitad; quitar la
    columna del filtro por clave pone rojo la primera (y el gate del HTML de arriba)."""
    tabla = pd.DataFrame({"feature": ["x"], "not_evaluable_reason": ["group_below_min"]})
    calibracion = _table_view("validation.calibration", tabla, max_rows=10)
    assert calibracion["columns"] == ["feature"]
    ajena = _table_view("selection.correlations", tabla, max_rows=10)
    assert ajena["columns"] == ["feature", "not_evaluable_reason"]
