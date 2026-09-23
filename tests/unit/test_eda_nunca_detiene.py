"""El análisis exploratorio nunca detiene la corrida (D-SC-19/20).

`eda` es descriptivo y ninguna etapa del modelo lo necesita, así que un error ahí debe costar un
sub-análisis, no la corrida. Estos tests fijan la regla —el paso nunca levanta, siempre publica sus
seis artefactos y cada sub-análisis falla por separado— y, sobre todo, lo que la regla **no** puede
hacer: publicar lo que falló como si hubiera salido bien.

Contrato: `docs/design/_ENMIENDA-EDA-NUNCA-DETIENE.md`.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_eda_step import (
    _data_config_aleatorio,
    _eda_defaults,
    _frame,
    _frame_sin_fecha,
    _labels,
    _splits,
    _study_con_data,
)

import nikodym
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.core.dataset_check import check_dataset
from nikodym.core.study import Study
from nikodym.eda.config import DefaultRateConfig, EdaConfig, UnivariateConfig
from nikodym.eda.default_rate import _RESULT_COLUMNS, tasa_no_calculable
from nikodym.eda.stability import TemporalStabilityAnalyzer
from nikodym.eda.step import EDA_ARTIFACTS, EdaStep
from nikodym.eda.univariate import UnivariateProfiler
from nikodym.guided.summaries import SummaryContext, build_stage_summary

# ───────────────────────── ayudas ─────────────────────────


def _correr(frame: pd.DataFrame, cfg: EdaConfig) -> tuple[object, InMemoryAuditSink, Study]:
    """Corre `EdaStep` con partición aleatoria y devuelve resultado, trail y estudio."""
    study = _study_con_data(frame, cfg, _data_config_aleatorio())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    return study._run_one(EdaStep.from_config(cfg)), sink, study


def _dos_fechas(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """El archivo de banco más común: fecha de originación y fecha de corte."""
    datos = _frame_sin_fecha() if frame is None else frame
    return datos.assign(
        fecha_origen=pd.to_datetime(["2024-01-15", "2024-02-15", "2024-03-15"] * 4),
        fecha_corte=pd.Timestamp("2024-06-30"),
    )


def _resumen(study: Study) -> object:
    return build_stage_summary(
        "eda",
        study,
        SummaryContext(
            project_dir=None,
            run_dir=None,
            source_label="cartera.parquet",
            partition_label="partición aleatoria",
        ),
    )


def _decisiones_parciales(sink: InMemoryAuditSink) -> list[dict]:
    return [
        event.payload
        for event in sink.events
        if event.kind == "decision"
        and event.payload.get("regla") == "analisis_exploratorio_parcial"
    ]


# ───────────────────────── la regla ─────────────────────────


def test_dos_columnas_de_fecha_ya_no_matan_la_corrida() -> None:
    """🔴 El caso que destapó la enmienda: hoy levanta «más de una columna datetime plausible»."""
    result, _, study = _correr(_dos_fechas(), _eda_defaults(columns=("score",)))

    card = study.artifacts.get("eda", "eda_card")
    assert card.default_rate_not_evaluable_reason == "no_calculable"
    assert "más de una columna datetime" in card.failed_analyses["default_rate"]
    # Los otros sub-análisis corrieron bien: la falla fue sólo de la tasa en el tiempo.
    assert set(card.failed_analyses) == {"default_rate"}
    assert len(result.univariate.profiles) == 1
    assert not result.quality.by_column.empty
    # Y la estabilidad dice que no hay tasa que mirar, no «pocos períodos».
    assert result.stability.not_evaluable_reason == "tasa_no_calculable"


def test_la_tasa_global_se_conserva_cuando_solo_falla_la_agrupacion() -> None:
    """Con dos fechas la población es buena: la tasa global es la de siempre."""
    frame = _dos_fechas()
    result, _, _ = _correr(frame, _eda_defaults(columns=("score",)))

    esperada = float(frame["target"].eq(1).sum()) / float(frame["target"].isin((0, 1)).sum())
    assert result.default_rate.overall_rate == esperada


@pytest.mark.parametrize(
    ("config", "frame", "fragmento"),
    [
        pytest.param(
            DefaultRateConfig(date_col="fecha_que_no_existe", min_obs_per_period=1),
            None,
            "fecha_que_no_existe",
            id="date_col-declarada-y-ausente",
        ),
        pytest.param(
            DefaultRateConfig(date_col="segment", min_obs_per_period=1),
            None,
            "requiere una columna datetime",
            id="date_col-no-datetime",
        ),
        pytest.param(
            DefaultRateConfig(min_obs_per_period=1),
            "dos_fechas",
            "más de una columna datetime",
            id="dos-columnas-datetime",
        ),
        pytest.param(
            DefaultRateConfig(axis="cohort", min_obs_per_period=1),
            None,
            "cohort_col",
            id="cohort-sin-cohort_col",
        ),
        pytest.param(
            DefaultRateConfig(axis="cohort", cohort_col="no_existe", min_obs_per_period=1),
            None,
            "no_existe",
            id="cohort_col-inexistente",
        ),
    ],
)
def test_los_cinco_errores_que_d_sc_17_dejo_intactos_ahora_degradan(
    config: DefaultRateConfig, frame: str | None, fragmento: str
) -> None:
    """🔴 D-SC-17 §2 los declaraba errores; D-SC-19 lo deroga: desde el PASO, degradan."""
    datos = _dos_fechas() if frame == "dos_fechas" else _frame_sin_fecha()
    cfg = EdaConfig(default_rate=config, univariate=UnivariateConfig(columns=("score",)))

    _, _, study = _correr(datos, cfg)

    card = study.artifacts.get("eda", "eda_card")
    assert card.default_rate_not_evaluable_reason == "no_calculable"
    assert fragmento in card.failed_analyses["default_rate"]


def test_el_analizador_suelto_sigue_levantando() -> None:
    """La regla es del PASO del pipeline: la pieza, usada por código, conserva su contrato."""
    from nikodym.eda.default_rate import DefaultRateAnalyzer
    from nikodym.eda.exceptions import EdaError

    with pytest.raises(EdaError, match="más de una columna datetime"):
        DefaultRateAnalyzer.from_config(DefaultRateConfig(min_obs_per_period=1)).compute(
            _dos_fechas(), target_col="target"
        )


@pytest.mark.parametrize(
    ("mutar", "fragmento"),
    [
        pytest.param("vaciar", "no tiene filas", id="particion-vacia"),
        pytest.param("duplicar_indice", "índice único", id="indice-duplicado"),
        pytest.param("sin_target", "target", id="target-ausente"),
    ],
)
def test_una_poblacion_rota_degrada_todo_y_publica_los_seis_artefactos(
    mutar: str, fragmento: str
) -> None:
    """Sin población no hay nada que describir, pero la corrida sigue: la detiene binning."""
    frame = _frame_sin_fecha()
    if mutar == "vaciar":
        frame = frame.iloc[:0]
    elif mutar == "duplicar_indice":
        frame = pd.concat([frame, frame.iloc[[0]]])
    else:
        frame = frame.drop(columns=["target"])
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",)),
        analysis_partition="todas",
    )
    study = Study(
        NikodymConfig(repro=ReproConfig(seed=20_240_626), data=_data_config_aleatorio(), eda=cfg)
    )
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("data", "labels", _labels(_frame_sin_fecha()))
    study.artifacts.set("data", "splits", _splits(_frame_sin_fecha()))

    study._run_one(EdaStep.from_config(cfg))

    for clave in EDA_ARTIFACTS:
        assert study.artifacts.has("eda", clave), clave
    card = study.artifacts.get("eda", "eda_card")
    assert set(card.failed_analyses) >= {"default_rate", "univariate", "quality"}
    for causa in card.failed_analyses.values():
        assert fragmento in causa, causa


def test_los_perfiles_fallan_solos_sin_arrastrar_la_tasa_ni_la_calidad() -> None:
    """Una columna de perfil que no existe cuesta los perfiles, no el resto."""
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("no_existe",)),
    )
    result, _, study = _correr(_frame(), cfg)

    card = study.artifacts.get("eda", "eda_card")
    assert set(card.failed_analyses) == {"univariate"}
    assert "no_existe" in card.failed_analyses["univariate"]
    assert result.univariate.profiles == {}
    assert not result.default_rate.by_period.empty
    assert not result.quality.by_column.empty


def test_la_estabilidad_falla_sola_y_la_tasa_se_conserva(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una unidad de fallo propia: perder la tasa por la estabilidad sería perder evidencia."""

    def explota(self: object, *args: object, **kwargs: object) -> object:
        raise RuntimeError("fallo inyectado en la estabilidad")

    monkeypatch.setattr(TemporalStabilityAnalyzer, "assess", explota)
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",)),
    )
    result, _, study = _correr(_frame(), cfg)

    card = study.artifacts.get("eda", "eda_card")
    assert set(card.failed_analyses) == {"stability"}
    assert not result.default_rate.by_period.empty
    assert result.default_rate.not_evaluable_reason is None
    assert result.stability.not_evaluable_reason == "no_calculable"


def test_una_excepcion_inesperada_degrada_pero_se_publica_con_su_tipo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Se atrapa todo, pero un defecto del motor NO se esconde: lleva su tipo al resumen y trail."""

    def explota(self: object, *args: object, **kwargs: object) -> object:
        raise KeyError("columna_fantasma")

    monkeypatch.setattr(UnivariateProfiler, "profile", explota)
    _, sink, study = _correr(_frame(), _eda_defaults(columns=("score",)))

    causa = study.artifacts.get("eda", "eda_card").failed_analyses["univariate"]
    assert causa.startswith("error inesperado del motor (KeyError)")
    decision = next(d for d in _decisiones_parciales(sink) if d["valor"] == "univariate")
    # `DecisionRecord` no cambia: el tipo viaja en la causa, que es el `umbral` de la decisión.
    assert "(KeyError)" in decision["umbral"]


def test_una_decision_por_sub_analisis_caido_y_ninguna_en_una_corrida_sana() -> None:
    """Auditable: cada degradación queda en el trail; una corrida sana no escribe ninguna."""
    _, sink, _ = _correr(_dos_fechas(), _eda_defaults(columns=("score",)))
    decisiones = _decisiones_parciales(sink)
    assert [d["valor"] for d in decisiones] == ["default_rate"]
    assert decisiones[0]["accion"] == "no_evaluable"

    cfg = EdaConfig(
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",)),
    )
    _, sano, _ = _correr(_frame(), cfg)
    assert _decisiones_parciales(sano) == []


# ───────────────────── nada caído se publica como negativo ─────────────────────


def test_la_calidad_caida_no_publica_ceros(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ceros se leerían «el archivo no tiene problemas de calidad»."""
    from nikodym.eda.quality import DataQualityProfiler

    def explota(self: object, *args: object, **kwargs: object) -> object:
        raise ValueError("fallo inyectado en la calidad")

    monkeypatch.setattr(DataQualityProfiler, "profile", explota)
    _, _, study = _correr(_frame(), _eda_defaults(columns=("score",)))

    card = study.artifacts.get("eda", "eda_card")
    assert "quality" in card.failed_analyses
    assert card.quality_flag_counts == {}


def test_el_canal_de_metricas_omite_lo_que_no_se_calculo() -> None:
    """`stability_flagged = 0.0` se leería «estable» y `n_periods = 0` como un dato."""
    _, _, study = _correr(_dos_fechas(), _eda_defaults(columns=("score",)))

    metricas = study.results["metrics"]
    assert "eda.stability_flagged" not in metricas
    assert "eda.n_periods" not in metricas
    assert math.isfinite(metricas["eda.overall_default_rate"])


# ───────────────────────── el constructor nuevo ─────────────────────────


@pytest.mark.parametrize(
    "caso",
    ["none", "vacio", "indice_duplicado", "sin_target", "sin_elegibles"],
)
def test_tasa_no_calculable_nunca_levanta(caso: str) -> None:
    """La red de D-SC-19: construye siempre, con la tabla vacía y sus seis columnas."""
    base = _frame_sin_fecha()
    frames: dict[str, pd.DataFrame | None] = {
        "none": None,
        "vacio": base.iloc[:0],
        "indice_duplicado": pd.concat([base, base.iloc[[0]]]),
        "sin_target": base.drop(columns=["target"]),
        "sin_elegibles": base.assign(target=pd.Series(pd.NA, index=base.index, dtype="Int8")),
    }
    resultado = tasa_no_calculable(frames[caso], target_col="target", axis="period")

    assert resultado.not_evaluable_reason == "no_calculable"
    assert list(resultado.by_period.columns) == list(_RESULT_COLUMNS)
    assert resultado.by_period.empty
    if caso == "indice_duplicado":
        assert math.isfinite(resultado.overall_rate)
    else:
        assert math.isnan(resultado.overall_rate)


# ───────────────────────── las superficies ─────────────────────────


def test_el_resumen_de_la_etapa_trae_una_alerta_por_analisis_caido() -> None:
    """Una falla es algo que revisar: va a las alertas, que el resumen final recoge."""
    _, _, study = _correr(_dos_fechas(), _eda_defaults(columns=("score",)))
    resumen = _resumen(study)

    alertas = " ".join(resumen.alerts)
    assert "La tasa de malos en el tiempo no se pudo calcular" in alertas
    assert "más de una columna datetime" in alertas
    texto = "\n".join(resumen.lines)
    assert "Tasa de malos: " in texto
    assert "0 períodos" not in texto
    assert "no_calculable" not in texto + alertas


def test_sin_poblacion_la_tasa_dice_no_disponible_y_no_sin_elegibles() -> None:
    """«Sin operaciones elegibles» afirmaría algo que nadie midió."""
    frame = _frame_sin_fecha().iloc[:0]
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",)),
        analysis_partition="todas",
    )
    study = Study(
        NikodymConfig(repro=ReproConfig(seed=20_240_626), data=_data_config_aleatorio(), eda=cfg)
    )
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("data", "labels", _labels(_frame_sin_fecha()))
    study.artifacts.set("data", "splits", _splits(_frame_sin_fecha()))
    study._run_one(EdaStep.from_config(cfg))

    texto = "\n".join(_resumen(study).lines)
    assert "Tasa de malos: no disponible" in texto
    assert "sin operaciones elegibles" not in texto


# ───────────────────────── preflight y catálogo ─────────────────────────


def _config_preflight(**eda: object) -> NikodymConfig:
    return NikodymConfig(
        repro=ReproConfig(seed=1),
        data=_data_config_aleatorio(),
        eda=EdaConfig(**eda),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "eda",
    [
        pytest.param({"default_rate": DefaultRateConfig(axis="cohort")}, id="cohort-sin-columna"),
        pytest.param(
            {"default_rate": DefaultRateConfig(date_col="fecha_que_no_existe")},
            id="date_col-ausente",
        ),
        pytest.param(
            {"default_rate": DefaultRateConfig(axis="cohort", cohort_col="no_existe")},
            id="cohort_col-ausente",
        ),
        pytest.param({"univariate": UnivariateConfig(columns=("no_existe",))}, id="perfil-ausente"),
    ],
)
def test_el_preflight_no_predice_un_corte_que_ya_no_ocurre(eda: dict) -> None:
    """🔴 Un desajuste sólo de `eda` cuesta un sub-análisis, no la corrida: compatible."""
    resultado = check_dataset(_config_preflight(**eda), ["score", "segment", "bad_flag", "cohorte"])
    assert resultado.compatible, resultado.mismatches


def test_la_exencion_del_preflight_no_se_derrama_a_binning() -> None:
    """Control: la misma columna ausente en `binning` SÍ detiene la corrida y se sigue diciendo."""
    from nikodym.binning.config import BinningConfig

    config = _config_preflight().model_copy(
        update={"binning": BinningConfig(feature_columns=("no_existe",))}
    )
    resultado = check_dataset(config, ["score", "segment", "bad_flag", "cohorte"])
    assert not resultado.compatible
    assert any(m.declared == "no_existe" for m in resultado.mismatches)


def test_la_opcion_por_cohorte_del_catalogo_ya_no_exige_otro_campo() -> None:
    """Igual que D-SC-18 hizo con «period»: «exige otro campo» dejó de ser verdad."""
    from nikodym.ui import jobs

    opcion = next(
        o
        for eleccion in jobs._ABANICO_POR_SECCION["eda"]
        if eleccion["path"] == "eda.default_rate.axis"
        for o in eleccion["options"]
        if o["value"] == "cohort"
    )
    assert opcion["estado"] == jobs._DISPONIBLE
    assert opcion["motivo"] is None and opcion["prueba"] is None
    assert not opcion.get("exige")
    assert "la corrida sigue" in opcion["help"]


# ───────────────────────── de punta a punta ─────────────────────────


@pytest.fixture
def _cartera_dos_fechas(tmp_path: Path) -> Path:
    from nikodym.ui import datasets

    base = pd.read_parquet(datasets.materialize("hipotecario_comportamiento", workdir=tmp_path))
    rng = np.random.default_rng(7)
    base["fecha_origen"] = pd.Timestamp("2021-01-01") + pd.to_timedelta(
        rng.integers(0, 900, size=len(base)), unit="D"
    )
    base["fecha_corte"] = pd.Timestamp("2024-06-30")
    ruta = tmp_path / "cartera_dos_fechas.parquet"
    base.to_parquet(ruta)
    return ruta


def test_gate_de_aceptacion_la_cartera_con_dos_fechas_llega_al_final(
    _cartera_dos_fechas: Path, tmp_path: Path
) -> None:
    """🔴 GATE DE ACEPTACIÓN: hoy muere en `eda` en 3,5 s; con D-SC-19 termina `done`."""
    pytest.importorskip("optbinning")
    sc = nikodym.Scorecard(
        _cartera_dos_fechas,
        target={"col": "bad_flag", "op": "==", "value": 1},
        partition="random",
        name="dos_fechas",
        run_dir=tmp_path / "run",
    )
    sc.run()

    assert sc.study.run_context.status == "done", sc.study.run_context.error
    final = sc.summary()
    assert final.execution == "completada — con el análisis exploratorio parcial"
    assert any("no se pudo calcular" in alerta for alerta in final.review)
    # La página ejecutiva del informe, escrita DURANTE la corrida, no dice «sin fallos».
    html = next((tmp_path / "run" / "dos_fechas" / "reports").glob("*.html")).read_text(
        encoding="utf-8"
    )
    assert "corrieron sin fallos" not in html
    assert "de forma parcial" in html
    # Test 8: el informe dice la causa y no afirma lo que no hay —ni «0 períodos», ni «un solo
    # período», ni una tabla vacía de la tasa—, y ningún slug del motor llega a la prosa.
    from nikodym.report import prose
    from nikodym.report.builder import ReportBuilder
    from nikodym.report.config import ReportConfig

    bundle = ReportBuilder.from_config(ReportConfig()).collect(sc.study)
    assert "eda.default_rate.by_period" not in bundle.tables
    parrafos = (*prose.context_body(bundle), *prose.results_body(bundle, "eda"))
    texto = " ".join(parrafos)
    assert "más de una columna datetime" in texto
    assert "La tasa de malos en el tiempo no se pudo calcular" in texto
    for falsa in ("0 períodos", "0 cohortes", "Con un solo período", "un solo período"):
        assert falsa not in html, falsa
    for slug in ("no_calculable", "failed_analyses"):
        assert slug not in texto, slug


# ───────────────────────── el informe ─────────────────────────


def _prosa_eda(study: Study) -> tuple[str, str]:
    """Contexto y Resultados de `eda`, leídos de la card como los lee el informe."""
    from types import SimpleNamespace

    from nikodym.report import prose

    card = study.artifacts.get("eda", "eda_card").model_dump(mode="python")
    bundle = SimpleNamespace(cards={"eda": card})
    return " ".join(prose._eda_context(card)), " ".join(prose._results_eda(bundle))  # type: ignore[arg-type]


def test_el_informe_no_dice_sin_alertas_de_calidad_si_la_calidad_cayo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 `quality_flag_counts == {}` se leía «no levantó alertas»: un negativo que nadie midió."""
    from nikodym.eda.quality import DataQualityProfiler
    from nikodym.report.builder import ReportBuilder
    from nikodym.report.config import ReportConfig

    def explota(self: object, *args: object, **kwargs: object) -> object:
        raise ValueError("fallo inyectado en la calidad")

    monkeypatch.setattr(DataQualityProfiler, "profile", explota)
    _, _, study = _correr(_frame(), _eda_defaults(columns=("score",)))
    contexto, resultados = _prosa_eda(study)

    assert "no levantó alertas" not in contexto
    assert "La revisión de calidad del archivo no se pudo calcular" in contexto
    assert "error inesperado del motor (ValueError): fallo inyectado en la calidad" in contexto
    assert "de forma parcial" in contexto
    assert "la calidad de datos por columna" not in resultados
    # Y el builder no reproduce una tabla de sólo encabezados.
    tablas = ReportBuilder.from_config(ReportConfig())._collect_tables(study)
    assert not any(nombre.startswith("eda.quality") for nombre in tablas), sorted(tablas)


def test_el_informe_no_cuenta_variables_descritas_si_los_perfiles_cayeron() -> None:
    """«Se describieron 0 variables» sería un resultado; lo que hubo fue una falla."""
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("no_existe",)),
    )
    _, _, study = _correr(_frame(), cfg)
    contexto, resultados = _prosa_eda(study)

    assert "se describieron 0" not in contexto
    assert "La descripción de las columnas frente al incumplimiento no se pudo calcular" in contexto
    assert "no_existe" in contexto
    assert "perfil por tramo" not in resultados


def test_una_corrida_sana_no_menciona_nada_parcial() -> None:
    """Control: sin fallas, ni la prosa ni el resumen dicen «parcial» ni «no se pudo calcular»."""
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",)),
    )
    _, _, study = _correr(_frame(), cfg)
    contexto, resultados = _prosa_eda(study)
    resumen = _resumen(study)

    for texto in (contexto, resultados, " ".join(resumen.lines), " ".join(resumen.alerts)):
        assert "parcial" not in texto, texto
        assert "no se pudo calcular" not in texto, texto


def _estado(study: Study, **contexto: object) -> str:
    from nikodym.guided.summaries import _estado_de_ejecucion

    base = {
        "project_dir": None,
        "run_dir": None,
        "source_label": "cartera.parquet",
        "partition_label": "partición aleatoria",
    }
    return _estado_de_ejecucion(study, (), SummaryContext(**{**base, **contexto}))  # type: ignore[arg-type]


@pytest.mark.parametrize("parcial", [False, True], ids=["sana", "parcial"])
def test_el_estado_de_ejecucion_dice_parcial_solo_si_algo_cayo(parcial: bool) -> None:
    """10g: con `eda` parcial nunca «sin fallos»; una corrida sana conserva sus frases exactas."""
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("no_existe",) if parcial else ("score",)),
    )
    _, _, study = _correr(_frame(), cfg)

    study.run_context.status = "running"
    en_curso = _estado(study)
    con_pendientes = _estado(study, pending_stages=("stability",))
    study.run_context.status = "done"
    terminada = _estado(study)
    hasta = _estado(study, until="eda")

    if not parcial:
        assert (
            en_curso
            == "corrieron sin fallos ninguna etapa; este informe es la última etapa de la corrida"
        )
        assert con_pendientes.startswith("corrieron sin fallos ninguna etapa antes de este informe")
        assert terminada == "completada"
        assert hasta == "completada hasta «Análisis exploratorio» (corrida parcial)"
        return
    for texto in (en_curso, con_pendientes):
        assert "sin fallos" not in texto
        assert "1 de sus análisis no se pudo calcular" in texto
    assert "quedan por correr" in con_pendientes
    assert terminada == "completada — con el análisis exploratorio parcial"
    assert hasta.endswith("(corrida parcial) — con el análisis exploratorio parcial")


# ───────────────────────── revisión adversarial del código ─────────────────────────


def test_la_red_final_de_la_estabilidad_tampoco_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 Pasada 1 de Codex: con la preparación caída, la estabilidad se construía al publicar
    llamando a `assess()` sin protección; si ese cálculo también fallaba, el paso levantaba."""

    def explota(self: object, *args: object, **kwargs: object) -> object:
        raise RuntimeError("fallo inyectado al publicar")

    monkeypatch.setattr(TemporalStabilityAnalyzer, "assess", explota)
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",)),
        analysis_partition="todas",
    )
    study = Study(
        NikodymConfig(repro=ReproConfig(seed=20_240_626), data=_data_config_aleatorio(), eda=cfg)
    )
    study.artifacts.set("data", "frame", _frame_sin_fecha().iloc[:0])
    study.artifacts.set("data", "labels", _labels(_frame_sin_fecha()))
    study.artifacts.set("data", "splits", _splits(_frame_sin_fecha()))

    study._run_one(EdaStep.from_config(cfg))

    for clave in EDA_ARTIFACTS:
        assert study.artifacts.has("eda", clave), clave
    card = study.artifacts.get("eda", "eda_card")
    assert "(RuntimeError)" in card.failed_analyses["stability"]
    assert card.stability_not_evaluable_reason == "no_calculable"


def test_sin_eje_y_con_perfiles_caidos_nada_dice_que_el_resto_se_hizo_completo() -> None:
    """🔴 Pasada 1 de Codex: la frase de D-SC-17 «el resto del análisis se hizo igual» seguía
    saliendo aunque los perfiles o la calidad hubieran caído."""
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("no_existe",)),
    )
    _, _, study = _correr(_frame_sin_fecha(), cfg)
    card = study.artifacts.get("eda", "eda_card")
    assert card.default_rate_not_evaluable_reason == "sin_eje_temporal"
    assert set(card.failed_analyses) == {"univariate"}

    contexto, resultados = _prosa_eda(study)
    assert "se hizo igual" not in resultados
    assert "el archivo no trae columna de fecha ni cohorte declarada" in resultados
    assert "no_existe" in contexto


def test_una_falla_de_las_figuras_se_declara_y_no_se_publica_como_cero_figuras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 Pasada 2 de Codex: si las recetas de figura fallaban, la card publicaba `n_figures = 0`
    sin causa ni alerta —un negativo publicado y un defecto del motor escondido—."""
    from nikodym.eda import step as modulo_step

    def explota(**kwargs: object) -> object:
        raise ValueError("fallo inyectado en las figuras")

    monkeypatch.setattr(modulo_step, "_build_figure_specs", explota)
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",)),
    )
    _, sink, study = _correr(_frame(), cfg)

    card = study.artifacts.get("eda", "eda_card")
    assert set(card.failed_analyses) == {"figures"}
    assert "(ValueError)" in card.failed_analyses["figures"]
    assert [d["valor"] for d in _decisiones_parciales(sink)] == ["figures"]
    alertas = " ".join(_resumen(study).alerts)
    assert "Las figuras del análisis exploratorio no se pudieron calcular" in alertas
    contexto, resultados = _prosa_eda(study)
    assert "Las figuras del análisis exploratorio no se pudieron calcular" in contexto
    # Los gráficos del informe salen de las tablas, que están: nada que diga «no se reproduce».
    assert "no se reproduce" not in resultados.lower()
