"""Gates de la capa A2 de FLUJO-GUIADO-SCORECARD: decidir, seguir, comparar y no perder nada.

D-FLU-3 (``exclude``/``keep`` con motivo → hojas coordinadas, un evento ``decision`` del usuario
por corrida, ``resume()`` como corrida nueva), §6-4 (paridad computacional ``run()`` frente a
``run(until) + resume()``), D-FLU-6 (``compare``) y los cinco hallazgos de la pasada 1 de Codex
sobre la capa A1: snapshot inmutable publicado sólo tras validar, cohortes numéricas, el informe
que un reintento no puede borrar, el preámbulo dentro del manejo de fallos y el resumen que no
se pudo armar como fallo con diagnóstico.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from _proyeccion_canonica import diferencias, proyeccion_canonica
from _ui_f1 import write_stacked_behavior_parquet

from nikodym.audit.exceptions import AuditError
from nikodym.core.config import config_hash
from nikodym.core.study import Study
from nikodym.guided import Scorecard, ScorecardInputError
from nikodym.guided import scorecard as scorecard_module
from nikodym.guided.scorecard import GUIDED_STEP


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    del fake_binning_process


@pytest.fixture
def fuente(tmp_path: Path) -> Path:
    ruta = tmp_path / "cartera.parquet"
    write_stacked_behavior_parquet(ruta, repeats=50)
    return ruta


def _puerta(fuente: Path | pd.DataFrame, tmp_path: Path, **kwargs: Any) -> Scorecard:
    """La puerta sobre el frame apilado; ``min_iv=0.0`` porque con el doble de OptBinning el IV
    de ``score`` queda bajo el 0,02 de fábrica y las decisiones necesitan dos candidatas."""
    base: dict[str, Any] = {
        "target": "bad_flag",
        "id": "loan_id",
        "cohort": "cohort",
        "oot_cohorts": ["oot"],
        "name": "prueba",
        "run_dir": tmp_path / "corridas",
        "min_iv": 0.0,
    }
    base.update(kwargs)
    sc = Scorecard(fuente, **base)
    sc._echo = lambda _texto: None
    return sc


def _eventos(trail: Path) -> list[dict[str, Any]]:
    return [json.loads(linea) for linea in trail.read_text(encoding="utf-8").splitlines()]


# ─────────────────────────── D-FLU-3: decidir con motivo ───────────────────────────


def test_exclude_escribe_las_dos_hojas_y_retira_de_las_contrarias(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    sc.keep("score", reason="la exige el negocio")
    assert sc.config.selection.force_include == ("score",)
    assert sc.config.model.force_include == ("score",)
    sc.exclude(["score"], reason="cambió de opinión el comité")
    # D-EXC-1: `exclude` escribe SÓLO `binning.exclude_columns`; la variable no se tramifica, y
    # selección y modelo rechazan forzar una variable que el binning no publica.
    assert sc.config.binning.exclude_columns == ("score",)
    assert sc.config.selection.force_exclude == ()
    # `model.force_exclude` NO se escribe: la variable ya no llega al modelo, y el motor rechaza
    # un override de `model` sobre una variable que la selección descartó (medido).
    assert sc.config.model.force_exclude == ()
    assert sc.config.selection.force_include == ()
    assert sc.config.model.force_include == ()
    assert [d["accion"] for d in sc._decisions] == ["keep", "exclude"]
    assert config_hash(sc.config) == sc.config_hash  # la identidad sigue al config vigente
    with pytest.raises(ScorecardInputError, match="exige reason="):
        sc.exclude("segment", reason="  ")
    with pytest.raises(ScorecardInputError, match="no está entre las predictoras"):
        sc.exclude("no_existe", reason="motivo")


def test_la_decision_llega_una_vez_al_trail_con_autor_y_motivo_y_resume_la_aplica(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    sc.run(until="selection")
    assert "score" in sc.study.artifacts.get("selection", "selected_features")
    sc.exclude("score", reason="dato no disponible en originación")
    final = sc.summary()
    assert any("resume()" in linea for linea in final.decisions)
    sc.resume()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert "score" not in sc.study.artifacts.get("selection", "selected_features")
    assert "score" not in sc.study.artifacts.get("model", "final_features")
    trail = tmp_path / "corridas" / "prueba" / "run" / "audit_trail.jsonl"
    decisiones = [
        e
        for e in _eventos(trail)
        if e["step"] == GUIDED_STEP and e["payload"]["regla"] == "decision_del_usuario"
    ]
    assert len(decisiones) == 1
    payload = decisiones[0]["payload"]
    assert payload["accion"] == "exclude"
    assert payload["autor"] == "usuario"
    assert payload["motivo"] == "dato no disponible en originación"
    assert payload["umbral"] is None
    assert payload["valor"] == {"binning.exclude_columns": ["score"]}
    # Desde la capa C el evento lleva también el SUJETO de la decisión (`variables`), además de
    # la hoja acumulada en `valor`: es lo que la línea «exclude score — «motivo»» necesita para
    # decirse igual desde el trail (la página ejecutiva del informe) que desde la memoria (el
    # resumen final). Clave aditiva del payload; `DecisionRecord` la ignora como a `autor`.
    assert payload["variables"] == ["score"]
    final = sc.summary()
    assert final.decisions == ("exclude score — «dato no disponible en originación»",)
    # D-EXC-1: la exclusión se ejecuta en el binning —la variable no se tramifica—, así que no
    # llega ni a la tabla de binning ni a la de selección; la intención queda en el trail.
    assert "score" not in sc.study.artifacts.get("binning", "tables")
    tabla = sc.study.artifacts.get("selection", "selection_table").set_index("feature")
    assert "score" not in tabla.index


def test_la_decision_del_usuario_llega_a_la_ficha_con_purpose(fuente: Path, tmp_path: Path) -> None:
    sc = _puerta(fuente, tmp_path, purpose="Decidir consumo.")
    sc.exclude("score", reason="dato que no estará en producción")
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    card = json.loads(
        (tmp_path / "corridas" / "prueba" / "run" / "model_card.json").read_text(encoding="utf-8")
    )
    usuario = [d for d in card["decisions"] if d["regla"] == "decision_del_usuario"]
    assert len(usuario) == 1
    assert usuario[0]["accion"] == "exclude"
    # D-GOB-17 (capa C): la ficha materializa el autor y el motivo de la decisión humana.
    assert usuario[0]["autor"] == "usuario"
    assert usuario[0]["motivo"] == "dato que no estará en producción"
    # Las reglas del motor no traen autor ni motivo; las declaraciones de la puerta (entrada e
    # inferencias) firman como `puerta_guiada`.
    del_motor = [d for d in card["decisions"] if d["step"] != GUIDED_STEP]
    assert del_motor and all(d["autor"] is None and d["motivo"] is None for d in del_motor)


# ─────────────────────────── §6-4: paridad computacional ───────────────────────────


def test_run_completo_y_run_until_mas_resume_dejan_la_misma_proyeccion(
    fuente: Path, tmp_path: Path
) -> None:
    directo = _puerta(fuente, tmp_path, run_dir=tmp_path / "directo")
    directo.run()
    parcial = _puerta(fuente, tmp_path, run_dir=tmp_path / "parcial")
    parcial.run(until="model")
    parcial.resume()
    assert directo.study.run_context.status == "done", directo.study.run_context.error
    assert parcial.study.run_context.status == "done", parcial.study.run_context.error
    assert diferencias(proyeccion_canonica(directo.study), proyeccion_canonica(parcial.study)) == []
    assert directo.config_hash == parcial.config_hash
    assert directo.study.run_context.run_id != parcial.study.run_context.run_id
    assert (
        directo.study.run_context.lineage.created_at != parcial.study.run_context.lineage.created_at
    )


# ─────────────────────────── D-FLU-6: comparar ───────────────────────────


def test_compare_pone_dos_corridas_lado_a_lado(fuente: Path, tmp_path: Path) -> None:
    base = _puerta(fuente, tmp_path, name="v01")
    base.run()
    otra = _puerta(fuente, tmp_path, name="v02")
    otra.exclude("score", reason="prueba sin la variable fuerte")
    otra.run()
    comparacion = base.compare(otra)
    assert comparacion.label == "Comparación: v01 frente a v02"
    tabla = comparacion.table
    assert list(tabla.columns) == ["Cifra", "v01", "v02"]
    assert set(tabla["Cifra"]) >= {
        "Ejecución",
        "Validación técnica",
        "Variables finales",
        "Decisiones humanas",
    }
    fila = tabla.set_index("Cifra")
    assert "score" in fila.loc["Variables finales", "v01"]
    assert "score" not in fila.loc["Variables finales", "v02"]
    assert fila.loc["Decisiones humanas", "v01"] == "ninguna"
    assert "exclude score" in fila.loc["Decisiones humanas", "v02"]
    assert "<table" in comparacion._repr_html_()
    with pytest.raises(ScorecardInputError, match="hayan corrido"):
        base.compare(_puerta(fuente, tmp_path, name="v03"))


# ─────────────────────── pasada 1 de Codex sobre A1: cinco hallazgos ───────────────────────


def test_el_snapshot_es_inmutable_y_se_publica_solo_tras_validar(tmp_path: Path) -> None:
    frame = pd.read_parquet(_parquet(tmp_path)).reset_index()
    primera = _puerta(frame, tmp_path, name="snap")
    ruta_1 = Path(primera.config.data.load.source)
    assert ruta_1.is_file()
    # El mismo DataFrame otra vez: el mismo archivo, no una copia.
    assert Path(_puerta(frame, tmp_path, name="snap").config.data.load.source) == ruta_1
    # Otro DataFrame con el mismo nombre: otro archivo; el primero sigue intacto.
    otro = frame.iloc[:-30]
    segunda = _puerta(otro, tmp_path, name="snap")
    ruta_2 = Path(segunda.config.data.load.source)
    assert ruta_2 != ruta_1 and ruta_2.is_file() and ruta_1.is_file()
    # Una construcción que falla después de cargar los datos no deja ningún snapshot nuevo.
    antes = sorted(p.name for p in ruta_1.parent.iterdir())
    with pytest.raises(ScorecardInputError):
        _puerta(frame.iloc[:-60], tmp_path, name="snap", target="no_existe")
    assert sorted(p.name for p in ruta_1.parent.iterdir()) == antes


def test_una_cohorte_numerica_se_coacciona_a_texto_y_la_frontera_casa(tmp_path: Path) -> None:
    frame = pd.read_parquet(_parquet(tmp_path))
    frame["cohort"] = frame["cohort"].map({"dev": 2023, "oot": 2024}).astype("int64")
    sc = _puerta(frame, tmp_path, name="entera", oot_cohorts=[2024])
    columna = next(c for c in sc.config.data.schema_.columns if c.name == "cohort")
    assert (columna.dtype, columna.coerce) == ("str", True)
    assert sc.config.data.partition.strategy.oot_cohorts == ("2024",)
    sc.run(until="data")
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    tamanos = sc.study.artifacts.get("data", "data_card").partition_sizes
    assert tamanos["oot"] == 300 and tamanos["desarrollo"] + tamanos["holdout"] == 1200
    with pytest.raises(ScorecardInputError, match="no trae"):
        _puerta(frame, tmp_path, name="entera", oot_cohorts=[2025])


def test_un_reintento_tras_un_fallo_inesperado_no_borra_el_informe_archivado(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    proyecto = tmp_path / "corridas" / "prueba"
    informe = proyecto / "reports" / "scorecard_report.html"
    assert informe.is_file()
    contenido = informe.read_bytes()

    def revienta(self: Study, *args: Any, **kwargs: Any) -> Study:
        raise RuntimeError("se cayó la luz")

    # Un `MonkeyPatch` propio: `monkeypatch.undo()` desharía también la semilla de hash que fija
    # el conftest para toda la suite.
    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(Study, "run", revienta)
        with pytest.raises(RuntimeError, match="se cayó la luz"):
            sc.run()
    assert informe.read_bytes() == contenido, "sin consolidación, el informe previo vuelve"
    assert not (proyecto / "run" / "reports").exists()
    # El reintento vuelve a fallar del mismo modo: nada se borra.
    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(Study, "run", revienta)
        with pytest.raises(RuntimeError):
            sc.run()
    assert informe.read_bytes() == contenido
    assert not any(p.name.startswith(".reports.") for p in proyecto.iterdir())
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    respaldos = [p for p in proyecto.iterdir() if p.name.startswith(".run.old.")]
    assert len(respaldos) == 1
    assert (respaldos[0] / "reports" / "scorecard_report.html").read_bytes() == contenido
    assert informe.is_file()


def test_el_informe_de_una_primera_corrida_fallida_no_lo_pisa_el_reintento(
    fuente: Path, tmp_path: Path
) -> None:
    """La primera corrida escribe el informe y falla antes de consolidar: no hay `run/` y el
    informe queda en `reports/`; el reintento lo lleva junto a la evidencia fallida
    (`.run.failed.*/reports`) y nunca lo pisa (Codex sobre A2 y A2-bis)."""
    import nikodym.api as api_module

    sc = _puerta(fuente, tmp_path)
    proyecto = tmp_path / "corridas" / "prueba"

    def revienta(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disco lleno al escribir la evidencia")

    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(api_module, "_escribir_layout_del_run", revienta)
        with pytest.raises(RuntimeError, match="disco lleno"):
            sc.run()
    informe = proyecto / "reports" / "scorecard_report.html"
    assert not (proyecto / "run").exists()
    fallidas = [p for p in proyecto.iterdir() if p.name.startswith(".run.failed.")]
    assert len(fallidas) == 1 and (fallidas[0] / "audit_trail.jsonl").is_file()
    fallido = fallidas[0] / "reports" / "scorecard_report.html"
    assert fallido.is_file(), "el informe del intento fallido viaja con su evidencia al fallar"
    assert not informe.exists()
    contenido = fallido.read_bytes()
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert fallido.read_bytes() == contenido
    assert not any(p.name.startswith(".reports.") for p in proyecto.iterdir())
    assert informe.is_file() and informe.read_bytes() != contenido


def test_cada_informe_queda_solo_con_la_evidencia_de_su_corrida(
    fuente: Path, tmp_path: Path
) -> None:
    """Éxito A → B falla después de escribir su informe → éxito C (Codex sobre A2-bis): el informe
    de A viaja con A a `.run.old.*`, el de B con su evidencia fallida a `.run.failed.*`, y el de
    C queda en `reports/`. Ninguno se mezcla con el trail de otra corrida."""
    import nikodym.api as api_module

    sc = _puerta(fuente, tmp_path)
    proyecto = tmp_path / "corridas" / "prueba"
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    informe = proyecto / "reports" / "scorecard_report.html"
    (proyecto / "reports" / "marca-A.txt").write_text("A", encoding="utf-8")
    informe_a = informe.read_bytes()
    trail_a = (proyecto / "run" / "audit_trail.jsonl").read_bytes()

    def revienta(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disco lleno al escribir la evidencia")

    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(api_module, "_escribir_layout_del_run", revienta)
        with pytest.raises(RuntimeError, match="disco lleno"):
            sc.run()
    fallidas = [p for p in proyecto.iterdir() if p.name.startswith(".run.failed.")]
    assert len(fallidas) == 1 and (fallidas[0] / "audit_trail.jsonl").is_file()
    informe_b = (fallidas[0] / "reports" / "scorecard_report.html").read_bytes()
    assert informe_b != informe_a, "cada corrida deja su propio informe (sellos distintos)"
    assert not (fallidas[0] / "reports" / "marca-A.txt").exists()
    assert (proyecto / "run" / "audit_trail.jsonl").read_bytes() == trail_a, "A sigue intacta"
    assert informe.read_bytes() == informe_a, "sin consolidación, el informe de A vuelve"
    assert (proyecto / "reports" / "marca-A.txt").is_file()

    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    viejas = [p for p in proyecto.iterdir() if p.name.startswith(".run.old.")]
    assert len(viejas) == 1
    assert (viejas[0] / "audit_trail.jsonl").read_bytes() == trail_a
    assert (viejas[0] / "reports" / "scorecard_report.html").read_bytes() == informe_a
    assert (viejas[0] / "reports" / "marca-A.txt").is_file()
    assert not (viejas[0] / "reports.1").exists()
    assert (fallidas[0] / "reports" / "scorecard_report.html").read_bytes() == informe_b
    assert informe.read_bytes() not in {informe_a, informe_b}
    assert not (proyecto / "reports" / "marca-A.txt").exists()
    assert not (proyecto / "run" / "reports").exists()
    assert not any(p.name.startswith(".reports.") for p in proyecto.iterdir())


def test_una_corrida_parcial_no_se_apropia_del_informe_de_una_fallida_posterior(
    fuente: Path, tmp_path: Path
) -> None:
    """Parcial A (sin informe) → B completa falla tras escribir su informe → C (Codex sobre
    A2-ter): el informe de B sólo puede estar en la evidencia fallida de B."""
    import nikodym.api as api_module

    sc = _puerta(fuente, tmp_path)
    proyecto = tmp_path / "corridas" / "prueba"
    sc.run(until="data")
    assert not _tiene_archivos(proyecto / "reports")

    def revienta(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disco lleno al escribir la evidencia")

    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(api_module, "_escribir_layout_del_run", revienta)
        with pytest.raises(RuntimeError, match="disco lleno"):
            sc.run()
    fallidas = [p for p in proyecto.iterdir() if p.name.startswith(".run.failed.")]
    assert len(fallidas) == 1
    assert (fallidas[0] / "reports" / "scorecard_report.html").is_file()
    assert not _tiene_archivos(proyecto / "reports")
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    viejas = [p for p in proyecto.iterdir() if p.name.startswith(".run.old.")]
    assert len(viejas) == 1 and not (viejas[0] / "reports").exists()
    assert (proyecto / "reports" / "scorecard_report.html").is_file()
    assert not (proyecto / "run" / "reports").exists()


def _tiene_archivos(ruta: Path) -> bool:
    return ruta.is_dir() and any(p.is_file() for p in ruta.rglob("*"))


def test_compare_con_el_mismo_nombre_no_pierde_ninguna_columna(
    fuente: Path, tmp_path: Path
) -> None:
    una = _puerta(fuente, tmp_path, name="scorecard", run_dir=tmp_path / "a")
    una.run()
    otra = _puerta(fuente, tmp_path, name="scorecard", run_dir=tmp_path / "b")
    otra.exclude("score", reason="sin la variable fuerte")
    otra.run()
    tabla = una.compare(otra).table
    assert list(tabla.columns) == ["Cifra", "scorecard (esta)", "scorecard (otra)"]
    fila = tabla.set_index("Cifra")
    assert "score" in fila.loc["Variables finales", "scorecard (esta)"]
    assert "score" not in fila.loc["Variables finales", "scorecard (otra)"]
    assert fila.loc["Carpeta", "scorecard (esta)"] != fila.loc["Carpeta", "scorecard (otra)"]


def test_un_sink_que_no_puede_escribir_el_preambulo_deja_la_corrida_fallida(
    fuente: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = _puerta(fuente, tmp_path)
    original = Study._emit

    def emit_roto(self: Study, kind: str, step: str | None, payload: dict[str, Any]) -> None:
        if kind == "decision" and step == GUIDED_STEP:
            raise AuditError("disco lleno")
        original(self, kind, step, payload)

    monkeypatch.setattr(Study, "_emit", emit_roto)
    sc.run()
    assert sc.study.run_context.status == "failed"
    assert sc.study.run_context.error is not None
    assert sc.study.run_context.error.step is None
    assert "disco lleno" in sc.study.run_context.error.message
    assert sc.study.run_context.finished_at is not None
    assert sc.summary().execution.startswith("fallida antes del primer paso")


def test_un_resumen_que_no_se_puede_armar_es_un_fallo_con_diagnostico(
    fuente: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = _puerta(fuente, tmp_path)

    def roto(stage: str, study: Any, context: Any) -> Any:
        if stage == "binning":
            raise KeyError("columna que ya no existe")
        return scorecard_module.build_stage_summary.__wrapped__(stage, study, context)  # type: ignore[attr-defined]

    monkeypatch.setattr(scorecard_module, "build_stage_summary", _con_wrapped(roto))
    sc.run()
    assert sc.study.run_context.status == "failed"
    assert sc.study.run_context.error.step == "binning"
    assert "no se pudo armar" in sc.study.run_context.error.message
    assert sc.summary().execution.startswith("fallida en «Tramos y WoE»")
    assert sc.study.artifacts.has("binning", "summary"), "lo calculado queda en la evidencia"


def _con_wrapped(func: Any) -> Any:
    func.__wrapped__ = scorecard_module.build_stage_summary
    return func


def _parquet(tmp_path: Path) -> Path:
    ruta = tmp_path / "cartera.parquet"
    if not ruta.exists():
        write_stacked_behavior_parquet(ruta, repeats=50)
    return ruta


# ─────────────────────────── §8-9 (a): merge_bins / set_bins ───────────────────────────


def _cortes(sc: Scorecard, columna: str) -> tuple[float, ...] | None:
    override = next((o for o in sc.config.binning.variable_overrides if o.name == columna), None)
    return None if override is None else override.user_splits


def test_set_bins_escribe_la_hoja_user_splits_y_la_corrida_siguiente_la_aplica(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    with pytest.raises(ScorecardInputError, match=r"llama a run\(\) primero"):
        sc.set_bins("score", [0.5, 2.5], reason="antes de correr")
    sc.run(until="binning")
    tramos = sc.bins("score")
    assert list(tramos["Tramo"]) == [1, 2]  # el doble de OptBinning parte en 1,5
    sc.set_bins("score", [0.5, 2.5], reason="los cortes del manual")
    assert _cortes(sc, "score") == (0.5, 2.5)
    override = next(o for o in sc.config.binning.variable_overrides if o.name == "score")
    assert override.user_splits_fixed == (True, True)
    assert config_hash(sc.config) == sc.config_hash
    sc.resume()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert list(sc.bins("score")["Tramo"]) == [1, 2, 3]
    tabla = sc.study.artifacts.get("binning", "tables")["score"]
    assert "[0.50, 2.50)" in set(tabla["Bin"].astype(str))
    trail = tmp_path / "corridas" / "prueba" / "run" / "audit_trail.jsonl"
    decisiones = [
        e["payload"]
        for e in _eventos(trail)
        if e["step"] == GUIDED_STEP and e["payload"]["regla"] == "decision_del_usuario"
    ]
    assert len(decisiones) == 1
    assert decisiones[0]["accion"] == "set_bins"
    assert decisiones[0]["motivo"] == "los cortes del manual"
    assert decisiones[0]["valor"]["binning.variable_overrides"][0]["user_splits"] == [0.5, 2.5]
    assert sc.summary().decisions == ("set_bins score — «los cortes del manual»",)


def test_merge_bins_junta_dos_tramos_adyacentes_y_rechaza_los_demas(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    sc.run(until="binning")
    # Con dos tramos, juntarlos dejaría uno solo: no hay tramificación posible.
    with pytest.raises(ScorecardInputError, match="un solo tramo"):
        sc.merge_bins("score", [1, 2], reason="prueba")
    sc.set_bins("score", [0.5, 1.5, 2.5], reason="cuatro tramos")
    sc.resume()
    assert list(sc.bins("score")["Tramo"]) == [1, 2, 3, 4]
    with pytest.raises(ScorecardInputError, match="no son adyacentes"):
        sc.merge_bins("score", [1, 3], reason="prueba")
    with pytest.raises(ScorecardInputError, match="exactamente dos"):
        sc.merge_bins("score", [1, 2, 3], reason="prueba")
    with pytest.raises(ScorecardInputError, match="no existe"):
        sc.merge_bins("score", [4, 5], reason="prueba")
    sc.merge_bins("score", [2, 3], reason="misma tasa de malos")
    assert _cortes(sc, "score") == (0.5, 2.5)
    sc.resume()
    assert list(sc.bins("score")["Tramo"]) == [1, 2, 3]
    assert sc.summary().decisions[-1] == "merge_bins score — «misma tasa de malos»"


def test_los_cortes_solo_aplican_a_variables_numericas_y_exigen_motivo(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    sc.run(until="binning")
    with pytest.raises(ScorecardInputError, match="categórica"):
        sc.set_bins("segment", [0.5], reason="prueba")
    with pytest.raises(ScorecardInputError, match="categórica"):
        sc.merge_bins("segment", [1, 2], reason="prueba")
    with pytest.raises(ScorecardInputError, match="exige reason="):
        sc.set_bins("score", [0.5], reason="")
    with pytest.raises(ScorecardInputError, match="estrictamente crecientes"):
        sc.set_bins("score", [2.5, 0.5], reason="prueba")
    with pytest.raises(ScorecardInputError, match="no está entre las predictoras"):
        sc.set_bins("no_existe", [0.5], reason="prueba")
    with pytest.raises(ScorecardInputError, match="no está entre las predictoras"):
        sc.bins("no_existe")
