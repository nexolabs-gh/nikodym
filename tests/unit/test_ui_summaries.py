"""Gate de D-FLU-8 en la interfaz: Resultados consume la misma fuente que ``summary()``.

``results.json`` gana ``summaries`` —los resúmenes por etapa y el final de
:mod:`nikodym.guided.summaries`, serializados por :mod:`nikodym.ui.summaries`— para toda corrida
de la interfaz, con el ``dataset_id`` como nombre de los datos y la partición del config en
palabras. Una corrida fallida conserva los resúmenes de lo que corrió; un resumen que no se pueda
armar publica su motivo y no pierde la corrida.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _ui_f1 import failing_config, full_f1_config, write_behavior_parquet

pytest.importorskip("fastapi", reason="la persistencia de corridas vive en la capa ui")

from nikodym.guided.summaries import STAGE_LABELS
from nikodym.ui import runs


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    del fake_binning_process


def _corrida(tmp_path: Path, *, fallida: bool = False) -> tuple[dict[str, Any], Path]:
    import nikodym

    fuente = tmp_path / "cartera.parquet"
    write_behavior_parquet(fuente)
    config = failing_config(str(fuente)) if fallida else full_f1_config(str(fuente))
    workdir = tmp_path / "workdir"
    trail = runs.reservar_trail(runs.asegurar_workdir(workdir))
    study = nikodym.run(config, artifacts=None)
    run_id = runs.save(
        study, workdir=workdir, governance=None, trail=trail, source_label="mi_cartera"
    )
    return runs.load_results(run_id, workdir=workdir), workdir / "runs" / run_id


def test_results_json_trae_los_resumenes_por_etapa_y_el_final(tmp_path: Path) -> None:
    payload, run_dir = _corrida(tmp_path)
    assert payload["status"] == "done"
    resumenes = payload["summaries"]
    assert resumenes["error"] is None
    etapas = resumenes["stages"]
    orden = [e["stage"] for e in etapas]
    # Las etapas que dejaron artefactos, en el orden del pipeline (el F1 de prueba termina en
    # desempeño: sin estabilidad, validación ni informe).
    assert orden[0] == "data"
    assert orden == [s for s in STAGE_LABELS if s in set(orden)]
    assert {"binning", "selection", "model", "scorecard", "calibration"} <= set(orden)
    assert all(e["label"] == STAGE_LABELS[e["stage"]] for e in etapas)
    datos = etapas[0]
    assert datos["lines"][0] == "Archivo: mi_cartera"
    assert any("cohortes fuera de tiempo" in linea for linea in datos["lines"])
    assert datos["table"] is not None and datos["table"]["columns"][0] == "Muestra"
    # Las rutas que cita son las FINALES de la corrida, no el temporal en que se armó.
    assert any(str(run_dir) in linea for linea in datos["lines"])
    final = resumenes["final"]
    assert final["execution"] == "completada"
    assert final["validation"] not in {"", "sin correr todavía"}
    assert any(rotulo.startswith("AUC en") for rotulo, _ in final["figures"])
    assert ("Evidencia de la corrida", str(run_dir)) in [tuple(f) for f in final["files"]]


def test_una_corrida_fallida_conserva_los_resumenes_de_lo_que_corrio(tmp_path: Path) -> None:
    payload, _run_dir = _corrida(tmp_path, fallida=True)
    assert payload["status"] == "failed"
    resumenes = payload["summaries"]
    assert resumenes["error"] is None
    assert [e["stage"] for e in resumenes["stages"]][:1] == ["data"]
    assert resumenes["final"]["execution"].startswith("fallida")


def test_un_resumen_que_no_se_puede_armar_no_pierde_la_corrida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def revienta(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("la card llegó sin filas")

    # `ui.summaries` importa los constructores al llamar (la capa ui no carga dominios al
    # importarse), así que el doble se instala en su fuente.
    import nikodym.guided.summaries as fuente

    monkeypatch.setattr(fuente, "build_stage_summary", revienta)
    payload, run_dir = _corrida(tmp_path)
    assert payload["status"] == "done" and run_dir.is_dir()
    resumenes = payload["summaries"]
    assert resumenes["stages"] == [] and resumenes["final"] is None
    assert resumenes["error"] == "El resumen por etapa no se pudo armar: la card llegó sin filas"
