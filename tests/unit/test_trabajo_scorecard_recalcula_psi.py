"""El trabajo «Scorecard de comportamiento (PD)» con el reúso del PSI apagado (D-VAL-16).

Gate de ejecución real, hermano de ``test_trabajo_scorecard_llega_a_done``: el esqueleto que la
interfaz siembra, sobre el dataset de la demo, con la casilla «Reusar el PSI que ya calculó la
etapa de estabilidad» **apagada** —el valor que hasta la capa C de VALIDACION-COTEJADA abortaba la
corrida y por eso estaba oculto—. Se exige lo que la persona ve: la corrida llega a ``done``, el
payload que lee Resultados dice ``recomputed`` en cada fila y en la card con la receta declarada
(la sección de estabilidad va en el trabajo), las filas recalculadas son **las mismas** que las del
paso de estabilidad —identidad, cantidad y valor, ``np.array_equal``: es el mismo motor por la
misma llamada— y el informe HTML dice de dónde salió el PSI.

⚠️ Es lento a propósito (el pipeline F1 completo, una vez para el módulo).
"""

from __future__ import annotations

import copy
import re
from typing import Any

import numpy as np
import pytest

pytest.importorskip("fastapi", reason="el catálogo de trabajos vive en la capa ui")
pytest.importorskip("optbinning", reason="el pipeline del scorecard exige nikodym[scoring]")

from test_trabajo_scorecard_llega_a_done import DATASET, _config_del_trabajo, _corre

_CORRIDA: dict[str, Any] = {}


def _config_con_recalculo() -> dict[str, Any]:
    config = _config_del_trabajo()
    assert config["stability"] is not None, "el trabajo lleva la sección de estabilidad"
    assert config["validation"]["stability"]["consume_stability"] is True
    config = copy.deepcopy(config)
    config["validation"]["stability"]["consume_stability"] = False
    return config


@pytest.fixture
def corrida(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if not _CORRIDA:
        workdir = tmp_path_factory.mktemp("workdir-recalculo")
        _CORRIDA.update(resultado=_corre(_config_con_recalculo(), workdir), workdir=workdir)
    return _CORRIDA


def _resultados(corrida: dict[str, Any]) -> dict[str, Any]:
    from nikodym.ui import runs

    return runs.load_results(corrida["resultado"]["run_id"], workdir=corrida["workdir"])


def test_la_corrida_con_el_reuso_apagado_llega_a_done(corrida: dict[str, Any]) -> None:
    assert corrida["resultado"]["status"] == "done", _resultados(corrida).get("error")


def test_el_payload_dice_recomputed_en_cada_fila_y_en_la_card(corrida: dict[str, Any]) -> None:
    validation = _resultados(corrida)["validation"]
    assert validation["stability"], "la familia de estabilidad no publicó filas"
    assert {fila["source"] for fila in validation["stability"]} == {"recomputed"}
    section = validation["metric_sections"]["validation"]
    assert section["stability_source"] == "recomputed"
    # La receta es la sección de estabilidad que el trabajo siembra, tal cual (eje y fuente
    # del CSI).
    sembrada = _config_con_recalculo()["stability"]
    assert section["stability_recompute"] == {
        "recipe": "declared",
        "temporal_axis": sembrada["temporal_axis"],
        "csi_source": sembrada["csi_source"],
    }


def test_las_filas_recalculadas_son_las_del_paso_de_estabilidad(corrida: dict[str, Any]) -> None:
    """Mismo motor por la misma llamada: identidad, cantidad y valor, sin tolerancia."""
    resultados = _resultados(corrida)
    artefacto = resultados["stability"]["stability_metrics"]
    recalculo = resultados["validation"]["stability"]
    assert len(artefacto) == len(recalculo) > 0
    identidad = lambda filas: np.array(  # noqa: E731
        [[str(f["metric"]), str(f["comparison"]), str(f["feature"])] for f in filas]
    )
    assert np.array_equal(identidad(artefacto), identidad(recalculo))
    valores = lambda filas: np.array(  # noqa: E731
        [np.nan if f["value"] is None else float(f["value"]) for f in filas], dtype=float
    )
    assert np.array_equal(valores(artefacto), valores(recalculo), equal_nan=True)


def test_el_informe_dice_de_donde_salio_el_psi(corrida: dict[str, Any]) -> None:
    from nikodym.ui import runs

    html = runs.load_report(corrida["resultado"]["run_id"], workdir=corrida["workdir"])
    assert html
    bloque = re.search(
        r'<section[^>]*id="section-validation-stability"[^>]*>(.*?)</section>', html, re.S
    )
    assert bloque is not None, "el informe no trae la subsección de estabilidad de la validación"
    seccion = bloque.group(1)
    assert "Recalculado en esta etapa con el motor de estabilidad" in seccion
    assert "con la configuración de la sección de estabilidad" in seccion
    assert "no está declarada" not in seccion
    # La tabla del documento lleva la procedencia en su columna `source`.
    tabla = re.search(
        r'<table[^>]*data-table-key="validation\.stability"[^>]*>(.*?)</table>', html, re.S
    )
    assert tabla is not None, "el informe no trae la tabla validation.stability"
    assert "stability_artifact" not in tabla.group(1)
    assert DATASET == "consumo_comportamiento"
