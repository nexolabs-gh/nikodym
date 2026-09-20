"""Gates de los resúmenes por etapa y del resumen final (D-FLU-2, D-FLU-4, D-SIM-5).

Tres contratos: (1) **sin identificadores del motor** —el gate de códigos internos del informe,
extendido a los resúmenes: ni marcas de aviso ni los slugs que los mapas de rótulos traducen—;
(2) **una sola fuente** para texto y ``_repr_html_``; (3) **cada resumen usa sólo su etapa o una
anterior**: se arma en cada prefijo del pipeline sin fallar ni degradarse.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pytest
from _ui_f1 import write_stacked_behavior_parquet

from nikodym.binning.results import IV_BAND_LABELS
from nikodym.core.markers import DECLARED_MARKERS
from nikodym.eda.default_rate import AXIS_LABELS
from nikodym.eda.quality import QUALITY_FLAG_LABELS
from nikodym.eda.stability import NOT_EVALUABLE_REASON_LABELS, STABILITY_INDICATOR_LABELS
from nikodym.guided import STAGE_LABELS, Scorecard, StageSummary
from nikodym.guided.summaries import STAGE_ORDER, build_stage_summary
from nikodym.report.prose import (
    _ANCHOR_KINDS,
    _ANCHOR_SOURCES,
    _CALIBRATION_METHODS,
    _COMPARISON_LABELS,
    _DISCRIMINANT_BANDS,
    _MONOTONIC_LABELS,
    _STEPWISE_DIRECTIONS,
)
from nikodym.selection.results import REASON_LABELS
from nikodym.stability.results import BAND_LABELS, PSI_METRIC_LABELS, STABILITY_METRIC_LABELS
from nikodym.validation.results import (
    CALIBRATION_TEST_LABELS,
    HL_NOT_EVALUABLE_REASON_LABELS,
    VALIDATION_DECISION_LABELS,
    VALIDATION_FAMILY_LABELS,
    VALIDATION_STATUS_LABELS,
)

#: Columnas del frame de prueba: son nombres del usuario y pueden coincidir con un slug.
_COLUMNAS_DEL_USUARIO = {"score", "segment", "bad_flag", "cohort", "loan_id"}


def _slugs_del_motor() -> set[str]:
    """Los identificadores que los mapas de rótulos traducen: si uno llega a un resumen, se
    filtró crudo."""
    mapas: list[dict[str, Any]] = [
        REASON_LABELS,
        BAND_LABELS,
        PSI_METRIC_LABELS,
        STABILITY_METRIC_LABELS,
        VALIDATION_STATUS_LABELS,
        VALIDATION_DECISION_LABELS,
        VALIDATION_FAMILY_LABELS,
        CALIBRATION_TEST_LABELS,
        HL_NOT_EVALUABLE_REASON_LABELS,
        IV_BAND_LABELS,
        QUALITY_FLAG_LABELS,
        NOT_EVALUABLE_REASON_LABELS,
        STABILITY_INDICATOR_LABELS,
        AXIS_LABELS,
        _MONOTONIC_LABELS,
        _ANCHOR_SOURCES,
        _ANCHOR_KINDS,
        _CALIBRATION_METHODS,
        _STEPWISE_DIRECTIONS,
        _COMPARISON_LABELS,
        _DISCRIMINANT_BANDS,
    ]
    slugs = {str(k) for mapa in mapas for k in mapa}
    # Palabras que también son español corriente o nombres de columna del usuario.
    return {s for s in slugs if "_" in s and s not in _COLUMNAS_DEL_USUARIO}


_SLUGS = _slugs_del_motor()
_MARCAS = re.compile("|".join(re.escape(m) for m in DECLARED_MARKERS))


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    del fake_binning_process


@pytest.fixture(scope="module")
def corrida(tmp_path_factory: pytest.TempPathFactory) -> Scorecard:
    """Una corrida completa de la puerta guiada, compartida por los gates de este módulo.

    Con alcance de módulo, los fixtures de función del ``conftest`` (semilla de hash y doble de
    OptBinning) todavía no actuaron: se aplican aquí con el mismo mecanismo y el mismo doble.
    """
    from conftest import FakeBinningProcess

    import nikodym.binning.transformer as transformer_module

    with pytest.MonkeyPatch.context() as parche:
        parche.setenv("PYTHONHASHSEED", "0")
        parche.setattr(transformer_module, "_import_binning_process", lambda: FakeBinningProcess)
        raiz = tmp_path_factory.mktemp("guiada")
        fuente = raiz / "cartera.parquet"
        write_stacked_behavior_parquet(fuente, repeats=50)
        sc = Scorecard(
            fuente,
            target="bad_flag",
            id="loan_id",
            cohort="cohort",
            oot_cohorts=["oot"],
            name="resumenes",
            run_dir=raiz / "corridas",
        )
        sc._echo = lambda _texto: None
        sc.run()
        assert sc.study.run_context.status == "done", sc.study.run_context.error
        yield sc


def _ofensores(texto: str) -> list[str]:
    encontrados = [s for s in _SLUGS if re.search(rf"(?<![\w.]){re.escape(s)}(?![\w.])", texto)]
    if _MARCAS.search(texto):
        encontrados.append("<marca de aviso declarado>")
    return sorted(encontrados)


def test_el_gate_de_slugs_no_esta_vacio() -> None:
    assert len(_SLUGS) > 30
    assert {"low_iv", "dev_vs_oot", "hosmer_lemeshow", "not_evaluable"} <= _SLUGS


@pytest.mark.parametrize("etapa", STAGE_ORDER)
def test_cada_resumen_habla_en_espanol_sin_identificadores_del_motor(
    corrida: Scorecard, etapa: str
) -> None:
    resumen = corrida.summary(etapa)
    assert isinstance(resumen, StageSummary)
    assert resumen.label == STAGE_LABELS[etapa]
    assert 1 <= len(resumen.lines) <= 8, resumen.lines
    assert "no se pudo armar" not in resumen.text()
    assert _ofensores(resumen.text()) == []
    assert _ofensores(resumen._repr_html_()) == []


def test_el_resumen_final_separa_ejecucion_de_validacion_y_no_filtra_slugs(
    corrida: Scorecard,
) -> None:
    final = corrida.summary()
    texto = final.text()
    assert texto.index("Ejecución: completada") < texto.index("Validación técnica:")
    assert "Cifras clave:" in texto and "Qué revisar:" in texto
    assert "Decisiones humanas registradas:" in texto and "Dónde quedó cada archivo:" in texto
    assert len(final.figures) == 5, final.figures
    assert final.figures[4][0] == "Peor PSI entre score y PD"
    assert _ofensores(texto) == []
    assert _ofensores(final._repr_html_()) == []


@pytest.mark.parametrize("etapa", STAGE_ORDER)
def test_texto_y_html_salen_de_la_misma_fuente(corrida: Scorecard, etapa: str) -> None:
    resumen = corrida.summary(etapa)
    pagina = resumen._repr_html_()
    for linea in resumen.lines:
        assert html.escape(linea) in pagina, linea
    for alerta in resumen.alerts:
        assert html.escape(alerta) in pagina, alerta
    if resumen.table is not None:
        for columna in resumen.table.columns:
            assert html.escape(str(columna)) in pagina


def test_las_tablas_de_decision_llevan_rotulos_en_espanol(corrida: Scorecard) -> None:
    resultados = corrida.results
    assert {
        "data",
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
        "stability",
        "validation",
    } <= set(resultados)
    for etapa, tabla in resultados.items():
        for columna in tabla.columns:
            assert re.fullmatch(r"[A-ZÁÉÍÓÚa-záéíóúñ][^_]*", str(columna)), (etapa, columna)
    assert list(resultados["data"].columns) == ["Muestra", "Filas", "Malos", "Tasa de malos"]
    assert "Motivo" in resultados["selection"].columns
    assert "Puntos" in resultados["scorecard"].columns
    assert list(resultados["validation"].columns) == [
        "Familia",
        "Prueba",
        "Muestra",
        "Valor",
        "p-valor",
        "Veredicto",
    ]


def test_el_resumen_de_datos_abre_con_la_ruta_absoluta_y_lo_inferido(corrida: Scorecard) -> None:
    resumen = corrida.summary("data")
    assert resumen.lines[0].startswith("Archivo: ")
    assert Path(resumen.lines[0].removeprefix("Archivo: ")).is_absolute()
    assert any(linea.startswith("Se infirió: ") for linea in resumen.lines)
    assert any(linea.startswith("Identificador: loan_id") for linea in resumen.lines)
    assert any(linea.startswith("Evidencia de la corrida: ") for linea in resumen.lines)


def test_cada_resumen_usa_solo_su_etapa_o_una_anterior(corrida: Scorecard) -> None:
    """Se arma sobre el store de la corrida completa etapa a etapa, sin mirar hacia adelante."""
    study = corrida.study
    contexto = corrida._context()
    for etapa in corrida.steps:
        resumen = build_stage_summary(etapa, study, contexto)
        assert "no publicó" not in resumen.text(), (etapa, resumen.text())
        assert "no se pudo armar" not in resumen.text(), etapa


@pytest.mark.parametrize("hasta", ["data", "binning", "model", "performance"])
def test_una_corrida_parcial_arma_los_resumenes_de_su_prefijo(hasta: str, tmp_path: Path) -> None:
    fuente = tmp_path / "cartera.parquet"
    write_stacked_behavior_parquet(fuente, repeats=50)
    sc = Scorecard(
        fuente,
        target="bad_flag",
        id="loan_id",
        cohort="cohort",
        oot_cohorts=["oot"],
        run_dir=tmp_path / "corridas",
    )
    sc._echo = lambda _texto: None
    sc.run(until=hasta)
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    prefijo = sc.steps[: sc.steps.index(hasta) + 1]
    assert tuple(sc._stage_summaries) == prefijo
    for etapa in prefijo:
        assert "no se pudo armar" not in sc.summary(etapa).text(), etapa
        assert _ofensores(sc.summary(etapa).text()) == []
    final = sc.summary()
    assert "corrida parcial" in final.execution
    assert _ofensores(final.text()) == []
