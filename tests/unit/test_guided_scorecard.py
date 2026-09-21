"""Gates de la puerta guiada ``nikodym.Scorecard`` (enmienda FLUJO-GUIADO-SCORECARD, capa A).

Cubre D-FLU-1 (entrada mínima e inferencias declaradas), D-FLU-3 (``run(until=)`` como prefijo
con hash propio y ``resume()`` como corrida nueva completa), D-FLU-4 (los dos estados y
``raise_on_error``), D-FLU-9 (``track=``), D-GOB-8 (ficha sólo con ``purpose=``), §6-3 (el hash
del YAML exportado) y D-SIM-1 (los mismos resultados por las dos puertas). Las corridas usan el
frame de comportamiento apilado (1.500 filas) y el doble determinista de OptBinning, como el resto
de la capa F1.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from _proyeccion_canonica import diferencias, proyeccion_canonica
from _ui_f1 import write_stacked_behavior_parquet

import nikodym
from nikodym.core.config import config_hash, loads_config
from nikodym.guided import Scorecard, ScorecardInputError, ScorecardRunError
from nikodym.guided.scorecard import GUIDED_STEP
from nikodym.ui.presets import _STANDARD_CONFIG


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita OR-Tools dentro del proceso pytest para las corridas F1 in-process."""
    del fake_binning_process


@pytest.fixture
def fuente(tmp_path: Path) -> Path:
    """Frame de comportamiento apilado: 1.500 filas, cohortes dev/oot, índice ``loan_id``."""
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
    }
    base.update(kwargs)
    return Scorecard(fuente, **base)


def _eventos(trail: Path) -> list[dict[str, Any]]:
    return [json.loads(linea) for linea in trail.read_text(encoding="utf-8").splitlines()]


# ─────────────────────────── D-FLU-1: entrada mínima e inferencias ───────────────────────────


def test_la_entrada_minima_infiere_esquema_predictoras_y_categoricas(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    data = sc.config.data
    assert data is not None
    assert data.schema_.index_col == "loan_id"
    assert data.schema_.unique_keys is None
    assert {c.name: c.dtype for c in data.schema_.columns} == {
        "score": "int",
        "segment": "str",
        "bad_flag": "int",
        "cohort": "str",
    }
    assert data.target.bad_rule.all_of[0].col == "bad_flag"
    assert data.partition.strategy.type == "cohort"
    assert sc.config.binning.feature_columns == ("score", "segment")
    assert sc.config.binning.categorical_columns == ("segment",)
    assert sc.config.selection.feature_columns == "*"
    assert sc.config.eda.default_rate.axis == "cohort"
    assert sc.config.eda.default_rate.cohort_col == "cohort"
    assert sc.config.stability.temporal_axis == "cohort"
    assert sc.config.stability.temporal_column == "cohort"
    assert sc.config.governance is None and sc.config.tracking is None
    assert sc.config.name == "prueba"
    reglas = [inferencia.regla for inferencia in sc.inferences]
    assert reglas == [
        "inferencia_esquema",
        "inferencia_predictoras",
        "inferencia_categoricas",
        "inferencia_muestras",
    ]
    predictoras = next(i for i in sc.inferences if i.regla == "inferencia_predictoras").valor
    assert predictoras["incluidas"] == ["score", "segment"]
    assert set(predictoras["excluidas"]) == {"bad_flag", "cohort"}
    assert sc.steps[0] == "data" and sc.steps[-1] == "report"
    assert sc.study is None and sc.results == {}


def test_el_identificador_como_columna_va_a_unique_keys_y_ausente_se_declara(
    fuente: Path, tmp_path: Path
) -> None:
    frame = pd.read_parquet(fuente).reset_index()
    sc = _puerta(frame, tmp_path, id="loan_id")
    assert sc.config.data.schema_.unique_keys == ("loan_id",)
    assert sc.config.data.schema_.index_col is None
    assert "loan_id" not in sc.config.binning.feature_columns

    sin_id = _puerta(frame, tmp_path, id=None, name="sin-id")
    assert sin_id.config.data.schema_.unique_keys is None
    assert sin_id.config.data.schema_.index_col is None
    assert any(i.regla == "inferencia_identificador" for i in sin_id.inferences)
    # Sin declararla, la columna de identificación es una predictora más: la puerta no adivina.
    assert "loan_id" in sin_id.config.binning.feature_columns

    with pytest.raises(ScorecardInputError, match="no es una columna ni el índice"):
        _puerta(fuente, tmp_path, id="no_existe")


def test_el_target_admite_columna_0_1_o_una_regla(fuente: Path, tmp_path: Path) -> None:
    regla = _puerta(fuente, tmp_path, target={"col": "score", "op": ">=", "value": 3})
    predicado = regla.config.data.target.bad_rule.all_of[0]
    assert (predicado.col, predicado.op, predicado.value) == ("score", ">=", 3)
    # La columna de la regla sale de las predictoras por fuga de información (D-FUGA); la
    # columna 0/1 original es una columna más del archivo y sólo el usuario puede apartarla.
    assert regla.config.binning.feature_columns == ("segment", "bad_flag")

    with pytest.raises(ScorecardInputError, match="tiene que ser una columna 0/1"):
        _puerta(fuente, tmp_path, target="score")
    with pytest.raises(ScorecardInputError, match="no es una columna del archivo"):
        _puerta(fuente, tmp_path, target="no_existe")
    with pytest.raises(ScorecardInputError, match="necesita las claves col, op y value"):
        _puerta(fuente, tmp_path, target={"col": "score"})


def test_los_resultados_vacios_del_target_quedan_indeterminados_y_fuera_del_ajuste(
    fuente: Path, tmp_path: Path
) -> None:
    """Pasada de cierre de Codex sobre la capa A: con `good_rule` vacía el motor toma por bueno
    todo lo que no es malo, también los resultados vacíos (operaciones sin desempeño maduro). La
    puerta arma las tres reglas y los vacíos quedan indeterminados: se puntúan, no se ajustan."""
    from nikodym.guided.summaries import _card

    frame = pd.read_parquet(fuente)
    frame["bad_flag"] = frame["bad_flag"].astype("Int64")
    frame.loc[frame.index[:40], "bad_flag"] = pd.NA
    sc = _puerta(frame, tmp_path)
    objetivo = sc.config.data.target
    assert objetivo.bad_rule.all_of[0].value == 1
    assert objetivo.good_rule is not None and objetivo.good_rule.all_of[0].value == 0
    assert objetivo.indeterminate_rule is not None
    vacio = objetivo.indeterminate_rule.all_of[0]
    assert (vacio.col, vacio.op) == ("bad_flag", "isna")
    inferencia = next(i for i in sc.inferences if i.regla == "inferencia_resultado_vacio")
    assert inferencia.valor == {"columnas": ["bad_flag"], "filas": 40}
    sc.run(until="data")
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    card = _card(sc.study, "data", "data_card")
    assert card is not None and card["class_counts"]["indeterminado"] == 40
    texto = sc.summary("data").text()
    assert "40 indeterminadas" in texto
    assert "Resultado vacío en 40 filas (bad_flag)" in texto

    # Con una regla, la columna de la regla vacía también es desconocida, no «bueno».
    con_huecos = frame.assign(score=frame["score"].mask(frame.index.isin(frame.index[:10])))
    regla = _puerta(
        con_huecos, tmp_path, target={"col": "score", "op": ">=", "value": 3}, name="regla"
    )
    objetivo = regla.config.data.target
    assert objetivo.good_rule is None
    assert objetivo.indeterminate_rule is not None
    vacio = objetivo.indeterminate_rule.all_of[0]
    assert (vacio.col, vacio.op) == ("score", "isna")
    inferencia = next(i for i in regla.inferences if i.regla == "inferencia_resultado_vacio")
    assert inferencia.valor == {"columnas": ["score"], "filas": 10}

    # Sin vacíos no hay nada que declarar: las reglas van igual, la inferencia no.
    limpio = _puerta(fuente, tmp_path, name="limpio")
    assert limpio.config.data.target.indeterminate_rule is not None
    assert not any(i.regla == "inferencia_resultado_vacio" for i in limpio.inferences)


def test_features_explicitas_se_respetan_y_una_fuga_se_rechaza(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path, features=["score"], categorical=[])
    assert sc.config.binning.feature_columns == ("score",)
    assert sc.config.binning.categorical_columns == ()
    assert not any(i.regla == "inferencia_predictoras" for i in sc.inferences)
    with pytest.raises(ScorecardInputError, match="definen el incumplimiento"):
        _puerta(fuente, tmp_path, features=["score", "bad_flag"])
    with pytest.raises(ScorecardInputError, match="no trae"):
        _puerta(fuente, tmp_path, features=["score", "no_existe"])


# ───────────────────────── D-OBL-5: la frontera OOT se exige, no se siembra ─────────────────────


def test_con_cohorte_y_sin_frontera_se_detiene_antes_de_correr_con_la_sugerencia(
    fuente: Path, tmp_path: Path
) -> None:
    with pytest.raises(ScorecardInputError) as excinfo:
        _puerta(fuente, tmp_path, oot_cohorts=None)
    mensaje = str(excinfo.value)
    assert "oot_cohorts=" in mensaje
    assert "2 cohortes (dev, oot)" in mensaje
    assert "oot_cohorts=['oot']" in mensaje
    assert not (tmp_path / "corridas" / "prueba" / "run").exists()


def test_con_fecha_y_sin_frontera_dice_el_rango_y_el_valor_que_usaria(tmp_path: Path) -> None:
    frame = _frame_con_fecha()
    with pytest.raises(ScorecardInputError) as excinfo:
        Scorecard(
            frame, target="bad_flag", id="loan_id", date="fecha", run_dir=tmp_path / "corridas"
        )
    mensaje = str(excinfo.value)
    assert "oot_from=" in mensaje
    assert "de 2022-01-15 a 2024-12-15 (36 meses)" in mensaje
    assert "oot_from='2024-01-01'" in mensaje


def test_sin_eje_y_sin_partition_random_se_detiene(fuente: Path, tmp_path: Path) -> None:
    with pytest.raises(ScorecardInputError, match='partition="random"'):
        Scorecard(fuente, target="bad_flag", id="loan_id", run_dir=tmp_path / "corridas")
    with pytest.raises(ScorecardInputError, match="un solo eje"):
        _puerta(fuente, tmp_path, partition="random")
    with pytest.raises(ScorecardInputError, match="no existe en la puerta guiada"):
        Scorecard(
            fuente,
            target="bad_flag",
            id="loan_id",
            partition="temporal",
            run_dir=tmp_path / "corridas",
        )


def test_partition_random_fija_las_fracciones_y_ajusta_las_listas_de_muestras(
    fuente: Path, tmp_path: Path
) -> None:
    sc = Scorecard(
        fuente,
        target="bad_flag",
        id="loan_id",
        partition="random",
        holdout=0.3,
        run_dir=tmp_path / "corridas",
    )
    estrategia = sc.config.data.partition.strategy
    assert estrategia.type == "random"
    assert (estrategia.dev_fraction, estrategia.holdout_fraction, estrategia.oot_fraction) == (
        0.7,
        0.3,
        0.0,
    )
    assert sc.config.performance.partitions == ("desarrollo", "holdout")
    assert sc.config.validation.discrimination.partitions == ("desarrollo", "holdout")
    assert sc.config.stability.comparisons == ("dev_vs_holdout",)
    assert sc.config.stability.temporal_axis == "none"
    assert sc.config.stability.temporal_column is None
    muestras = next(i for i in sc.inferences if i.regla == "inferencia_muestras").valor
    assert muestras == {
        "muestras": ["desarrollo", "holdout"],
        "comparaciones": ["dev_vs_holdout"],
        "eje_temporal": "none",
    }
    with pytest.raises(ScorecardInputError, match="holdout > 0"):
        Scorecard(
            fuente,
            target="bad_flag",
            partition="random",
            holdout=0.0,
            run_dir=tmp_path / "corridas",
        )


def _frame_con_fecha() -> pd.DataFrame:
    fechas = pd.date_range("2022-01-01", periods=36, freq="MS") + pd.Timedelta(days=14)
    filas = []
    for i in range(720):
        filas.append(
            {
                "loan_id": f"op-{i:04d}",
                "fecha": fechas[i % 36].strftime("%Y-%m-%d"),
                "score": i % 4,
                "segment": ["A", "B", "Z"][i % 3],
                "bad_flag": int((i * 7) % 5 < 2),
            }
        )
    return pd.DataFrame(filas).set_index("loan_id")


def test_con_fecha_declara_partition_temporal_eje_de_periodo_y_snapshot_del_dataframe(
    tmp_path: Path,
) -> None:
    sc = Scorecard(
        _frame_con_fecha(),
        target="bad_flag",
        id="loan_id",
        date="fecha",
        oot_from="2024-01-01",
        name="con-fecha",
        run_dir=tmp_path / "corridas",
    )
    estrategia = sc.config.data.partition.strategy
    assert (estrategia.type, estrategia.date_col, estrategia.oot_from) == (
        "temporal",
        "fecha",
        "2024-01-01",
    )
    fecha = next(c for c in sc.config.data.schema_.columns if c.name == "fecha")
    assert (fecha.dtype, fecha.coerce) == ("datetime", True)
    assert sc.config.eda.default_rate.axis == "period"
    assert sc.config.eda.default_rate.date_col == "fecha"
    assert sc.config.stability.temporal_axis == "period"
    assert sc.config.stability.temporal_column == "fecha"
    assert "fecha" not in sc.config.binning.feature_columns
    snapshot = Path(sc.config.data.load.source)
    assert snapshot.is_file()
    assert snapshot.parent == tmp_path / "corridas" / "con-fecha" / "input"
    assert snapshot.name.startswith("data-") and snapshot.suffix == ".parquet"
    # El snapshot conserva el índice nombrado, que es lo que `index_col` exige.
    assert pd.read_parquet(snapshot).index.name == "loan_id"


# ─────────────────────────── el config es la verdad (§6-3, D-SIM-4) ───────────────────────────


def test_el_config_hash_coincide_con_el_del_yaml_exportado(fuente: Path, tmp_path: Path) -> None:
    sc = _puerta(fuente, tmp_path)
    yaml = sc.to_yaml()
    assert config_hash(loads_config(yaml)) == sc.config_hash
    assert sc.config_hash == config_hash(sc.config)


def test_los_defaults_de_la_firma_son_los_del_preset_f1() -> None:
    """Cada argumento esencial escribe una hoja existente y su default es el del preset (§3.8)."""
    defaults = {k: v.default for k, v in inspect.signature(Scorecard.__init__).parameters.items()}
    p = _STANDARD_CONFIG
    esperado = {
        "holdout": p["data"]["partition"]["strategy"]["holdout_fraction"],
        "max_bins": p["binning"]["max_n_bins"],
        "min_bin_size": p["binning"]["min_bin_size"],
        "monotonic": p["binning"]["monotonic_trend"],
        "min_iv": p["selection"]["min_iv"],
        "max_correlation": p["selection"]["correlation"]["threshold"],
        "max_vif": p["selection"]["vif"]["threshold"],
        "stepwise": p["model"]["stepwise"]["enabled"],
        "p_enter": p["model"]["stepwise"]["entry_p_value"],
        "p_exit": p["model"]["stepwise"]["exit_p_value"],
        "sign_policy": p["model"]["sign_policy"]["action"],
        "pdo": p["scorecard"]["pdo"],
        "target_score": p["scorecard"]["target_score"],
        "target_odds": p["scorecard"]["target_odds"],
        "anchor": p["calibration"]["anchor_source"],
        "target_pd": p["calibration"]["target_pd"],
        "deciles": p["performance"]["n_deciles"],
        "psi_thresholds": (
            p["stability"]["psi_stable_threshold"],
            p["stability"]["psi_review_threshold"],
        ),
        "validation": tuple(p["validation"]["families"]),
        "name": "scorecard",
        "run_dir": "nikodym-runs",
        "review_every": 12,
    }
    for argumento, valor in esperado.items():
        assert defaults[argumento] == valor, argumento


def test_purpose_enciende_la_gobernanza_y_track_el_tracking(fuente: Path, tmp_path: Path) -> None:
    sc = _puerta(
        fuente,
        tmp_path,
        purpose="Decidir consumo.",
        owner="riesgo@banco",
        review_every=6,
        track=tmp_path / "mlruns",
    )
    assert sc.config.governance.purpose == "Decidir consumo."
    assert sc.config.governance.author == "riesgo@banco"
    assert sc.config.governance.review_period_months == 6
    assert sc.config.governance.model_name == "prueba"
    assert sc.config.tracking.enabled is True
    assert sc.config.tracking.tracking_uri == str(tmp_path / "mlruns")
    with pytest.raises(ScorecardInputError, match="purpose= está en blanco"):
        _puerta(fuente, tmp_path, purpose="   ")


def test_las_secciones_infra_llegan_tipadas_sin_importar_sus_capas(
    fuente: Path, tmp_path: Path
) -> None:
    """En un intérprete fresco nadie importó `nikodym.governance` ni `nikodym.tracking`; el
    core deja esas secciones opacas (`dict`) y la puerta las coacciona igual: leer
    `sc.config.governance.purpose` no puede depender de qué se importó antes."""
    codigo = textwrap.dedent(
        f"""
        import nikodym

        sc = nikodym.Scorecard(
            {str(fuente)!r}, target="bad_flag", id="loan_id", cohort="cohort",
            oot_cohorts=["oot"], name="prueba", run_dir={str(tmp_path / "corridas")!r},
            purpose="Decidir consumo.", owner="riesgo@banco",
            track={str(tmp_path / "mlruns")!r},
        )
        print("|".join([
            type(sc.config.audit).__name__, type(sc.config.governance).__name__,
            type(sc.config.tracking).__name__, sc.config.governance.purpose,
        ]))
        """
    )
    salida = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True, encoding="utf-8"
    )
    assert salida.returncode == 0, salida.stderr[-2000:]
    assert salida.stdout.strip().splitlines()[-1] == (
        "AuditConfig|GovernanceConfig|TrackingConfig|Decidir consumo."
    )


def test_un_argumento_fuera_de_rango_se_rechaza_antes_de_correr(
    fuente: Path, tmp_path: Path
) -> None:
    with pytest.raises(ScorecardInputError, match="max_n_bins"):
        _puerta(fuente, tmp_path, max_bins=1)


def test_nikodym_scorecard_es_un_export_perezoso() -> None:
    assert nikodym.Scorecard is Scorecard
    assert "Scorecard" in dir(nikodym)


# ─────────────────────────── correr, parar y seguir (D-FLU-3, D-FLU-4) ──────────────────────────


def test_run_completo_cuenta_cada_etapa_y_declara_su_procedencia_al_trail(
    fuente: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sc = _puerta(fuente, tmp_path)
    assert sc.run() is sc
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert tuple(sc._stage_summaries) == sc.steps
    salida = capsys.readouterr().out
    for etapa in sc.steps:
        assert sc.summary(etapa).label in salida, etapa
    assert "Ejecución: completada" in salida
    assert "Validación técnica:" in salida
    proyecto = tmp_path / "corridas" / "prueba"
    assert (proyecto / "config.yaml").is_file()
    assert (proyecto / "run" / "audit_trail.jsonl").is_file()
    assert (proyecto / "run" / "study" / "config.yaml").is_file()
    assert (proyecto / "reports" / "scorecard_report.html").is_file()
    assert not (proyecto / "run" / "model_card.json").exists()
    eventos = _eventos(proyecto / "run" / "audit_trail.jsonl")
    assert eventos[0]["kind"] == "run_start"
    declaradas = [e for e in eventos if e["step"] == GUIDED_STEP]
    assert [e["payload"]["regla"] for e in declaradas] == [
        "puerta_de_entrada",
        "inferencia_esquema",
        "inferencia_predictoras",
        "inferencia_categoricas",
        "inferencia_muestras",
    ]
    assert eventos[1] is declaradas[0] or eventos[1]["payload"]["regla"] == "puerta_de_entrada"
    assert all(e["payload"]["autor"] == "puerta_guiada" for e in declaradas)
    assert all(e["payload"]["motivo"] for e in declaradas)
    assert declaradas[0]["payload"]["valor"]["puerta"] == "guiada"
    final = sc.summary()
    assert final.execution == "completada"
    assert final.validation.split(" — ")[0] in {"Pasa", "Revisar", "Falla", "No evaluable"}
    assert [rotulo for rotulo, _ in final.figures][:3] == [
        "AUC en Fuera de tiempo (OOT)",
        "Gini en Fuera de tiempo (OOT)",
        "KS en Fuera de tiempo (OOT)",
    ]
    assert final.decisions == ()
    assert dict(final.files)["Informe HTML"].endswith("scorecard_report.html")
    assert set(sc.results) >= {"data", "binning", "selection", "model", "scorecard"}


def test_run_until_corre_el_prefijo_con_su_propio_hash(fuente: Path, tmp_path: Path) -> None:
    sc = _puerta(fuente, tmp_path)
    sc.run(until="selection")
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert sc.study.config.run.steps == ["data", "eda", "binning", "selection"]
    assert tuple(sc._stage_summaries) == ("data", "eda", "binning", "selection")
    assert not sc.study.artifacts.has("model", "coefficients")
    assert config_hash(sc.study.config) != sc.config_hash
    assert sc.config.run.steps is None
    final = sc.summary()
    assert "corrida parcial" in final.execution
    assert "Selección de variables" in final.execution
    assert final.validation.startswith("no corrió")
    with pytest.raises(ScorecardInputError, match="no es una etapa"):
        sc.run(until="provisiones")
    with pytest.raises(ScorecardInputError, match="no corrió todavía"):
        sc.summary("model")


def test_resume_es_una_corrida_nueva_y_completa_con_respaldo_lateral(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    sc.run(until="binning")
    primero = sc.study
    proyecto = tmp_path / "corridas" / "prueba"
    (proyecto / "reports" / "marca.txt").write_text(
        "informe de la corrida parcial", encoding="utf-8"
    )
    sc.resume()
    assert sc.study is not primero
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert sc.study.run_context.run_id != primero.run_context.run_id
    assert sc.study.config.run.steps is None
    assert sc.study.artifacts.has("report", "result")
    assert "corrida parcial" not in sc.summary().execution
    respaldos = sorted(p for p in proyecto.iterdir() if p.name.startswith(".run.old."))
    assert len(respaldos) == 1
    assert (respaldos[0] / "audit_trail.jsonl").is_file()
    assert (respaldos[0] / "reports" / "marca.txt").is_file(), (
        "el informe de la corrida anterior viaja con su evidencia al respaldo lateral"
    )
    assert not (proyecto / "reports" / "marca.txt").exists()
    assert (proyecto / "reports" / "scorecard_report.html").is_file()


def test_dos_corridas_a_la_vez_sobre_la_misma_carpeta_se_rechazan(
    fuente: Path, tmp_path: Path
) -> None:
    """Pasada de cierre de Codex: dos procesos sobre el mismo `run_dir/name` mezclarían informe y
    evidencia. Un candado por carpeta rechaza la segunda corrida antes de mover nada."""
    from nikodym.guided.scorecard import _bloquear_carpeta, _liberar_carpeta

    sc = _puerta(fuente, tmp_path)
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    proyecto = tmp_path / "corridas" / "prueba"
    informe = (proyecto / "reports" / "scorecard_report.html").read_bytes()
    candado = _bloquear_carpeta(proyecto / ".lock")  # «otro proceso» tiene la carpeta
    try:
        with pytest.raises(ScorecardRunError, match="Otra corrida está en curso"):
            sc.run()
    finally:
        _liberar_carpeta(candado)
    assert (proyecto / "reports" / "scorecard_report.html").read_bytes() == informe
    assert not any(p.name.startswith((".reports.", ".run.")) for p in proyecto.iterdir())
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error


def test_run_fallido_devuelve_el_estado_y_raise_on_error_levanta(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path, holdout=0.97)  # Desarrollo queda sin los 30 malos mínimos
    sc.run()
    assert sc.study.run_context.status == "failed"
    final = sc.summary()
    assert final.execution.startswith("fallida en «Datos y muestras»")
    assert final.validation.startswith("no corrió")
    assert final.figures == ()
    with pytest.raises(ScorecardRunError, match="fallida en «Datos y muestras»"):
        sc.run(raise_on_error=True)


def test_purpose_deja_la_ficha_en_disco(fuente: Path, tmp_path: Path) -> None:
    sc = _puerta(fuente, tmp_path, purpose="Decidir consumo.")
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    ficha = tmp_path / "corridas" / "prueba" / "run" / "model_card.json"
    assert ficha.is_file()
    card = json.loads(ficha.read_text(encoding="utf-8"))
    assert card["purpose"] == "Decidir consumo."
    reglas = [d["regla"] for d in card["decisions"]]
    assert "puerta_de_entrada" in reglas and "inferencia_predictoras" in reglas
    assert dict(sc.summary().files)["Ficha del modelo"] == str(ficha)


# ───────────────────── D-SIM-1: mismos resultados por las dos puertas ─────────────────────


def test_los_resultados_son_bit_a_bit_los_mismos_por_la_puerta_completa(
    fuente: Path, tmp_path: Path
) -> None:
    sc = _puerta(fuente, tmp_path)
    sc.run()
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    completa = nikodym.run(loads_config(sc.to_yaml()), run_dir=tmp_path / "completa")
    assert completa.run_context.status == "done", completa.run_context.error
    assert diferencias(proyeccion_canonica(sc.study), proyeccion_canonica(completa)) == []
    assert completa.run_context.run_id != sc.study.run_context.run_id
    assert config_hash(completa.config) == sc.config_hash


# ──────────── pasada 1 de Codex sobre la capa B (dos hallazgos de la capa A) ────────────


@pytest.mark.parametrize(
    "nombre", ["..", "../otra", "sub/carpeta", r"C:\fuera", "/fuera", ".", " "]
)
def test_name_es_un_solo_componente_de_ruta_y_no_escapa_de_run_dir(
    fuente: Path, tmp_path: Path, nombre: str
) -> None:
    """`name` compone `<run_dir>/<name>`: con `..` o una ruta, la carpeta del proyecto salía de
    `run_dir` y las corridas escribían y apartaban directorios ajenos (Codex, pasada 1 de B).
    """
    with pytest.raises(ScorecardInputError, match="name="):
        _puerta(fuente, tmp_path, name=nombre)
    assert not (tmp_path / "corridas").exists() or not any((tmp_path / "corridas").iterdir())


def test_si_el_archivo_cambia_tras_construir_la_puerta_no_corre(
    fuente: Path, tmp_path: Path
) -> None:
    """La puerta infiere sobre los bytes que leyó; `run()` y `resume()` vuelven a cargar la ruta.

    Si el archivo se reemplazó entre medio, la corrida aplicaría inferencias viejas a datos nuevos
    con el mismo config: se detiene antes de correr y pide reconstruir el Scorecard (Codex,
    pasada 1 de B).
    """
    sc = _puerta(fuente, tmp_path)
    sc._echo = lambda _texto: None
    copia = Path(sc.config.data.load.source)  # la copia del proyecto, la que el motor lee
    frame = pd.read_parquet(copia)
    frame.iloc[: len(frame) // 2].to_parquet(copia)  # el mismo archivo, otro contenido
    with pytest.raises(ScorecardInputError, match="cambió desde que se construyó"):
        sc.run(until="data")
    assert sc.study is None
    # Reconstruir la puerta sobre el archivo nuevo vuelve a inferir y corre.
    de_nuevo = _puerta(fuente, tmp_path, name="de-nuevo")
    de_nuevo._echo = lambda _texto: None
    de_nuevo.run(until="data")
    assert de_nuevo.study.run_context.status == "done"


def test_un_archivo_por_ruta_se_copia_al_proyecto_y_la_corrida_lee_esa_copia(
    fuente: Path, tmp_path: Path
) -> None:
    """La inferencia y la corrida consumen los MISMOS bytes: la puerta copia el archivo a
    `input/` con su huella en el nombre y el config referencia la copia. Reemplazar el original
    después no cambia nada; editar la copia sí detiene la corrida (Codex, pasada 2 de B)."""
    sc = _puerta(fuente, tmp_path)
    sc._echo = lambda _texto: None
    copia = Path(sc.config.data.load.source)
    assert copia.parent == sc.project_dir / "input" and copia.suffix == fuente.suffix
    assert copia.is_file() and copia != fuente.resolve()
    assert not [p for p in copia.parent.iterdir() if p.name.endswith(".tmp")]
    frame = pd.read_parquet(fuente)
    frame.iloc[: len(frame) // 2].to_parquet(fuente)  # el original cambia: no importa
    sc.run(until="data")
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert sc.study.artifacts.get("data", "data_card").n_rows == len(frame)
    # Un Scorecard que no valida no deja su copia a medias en `input/`.
    with pytest.raises(ScorecardInputError):
        _puerta(fuente, tmp_path, name="invalido", target="no_existe")
    assert not (tmp_path / "corridas" / "invalido").exists() or not [
        p for p in (tmp_path / "corridas" / "invalido").rglob("*.tmp")
    ]
