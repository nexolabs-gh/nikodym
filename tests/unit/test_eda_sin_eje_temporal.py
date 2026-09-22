"""`eda` sin eje temporal: la tasa por período se declara «No evaluable» (D-SC-17/18).

Sin columna de fecha **y** sin cohorte declarada, la tasa de incumplimiento por período no se puede
agrupar por nada. Hasta la 1.19.0 eso levantaba ``EdaError`` y mataba la corrida en la segunda
etapa del pipeline, con las nueve siguientes; el contrato (SDD-31 §8) promete lo contrario. Estos
tests fijan la regla nueva y, sobre todo, **sus bordes**: los cinco errores que el motor conserva y
las tres validaciones de población que la rama degradada no puede saltarse.

Contrato: `docs/design/_ENMIENDA-EDA-SIN-EJE-TEMPORAL.md` (D-SC-17 y D-SC-18).
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest
from _ui_f1 import full_f1_config, write_behavior_parquet
from pydantic import ValidationError
from test_eda_step import (
    _data_config_aleatorio,
    _data_config_por_cohorte,
    _eda_defaults,
    _frame_sin_fecha,
    _labels,
    _splits,
    _study_con_data,
    _study_with_data,
)

import nikodym
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.core.study import Study
from nikodym.data.config import RandomSplitConfig
from nikodym.eda.config import DefaultRateConfig, EdaConfig, UnivariateConfig
from nikodym.eda.default_rate import (
    _RESULT_COLUMNS,
    DEFAULT_RATE_NOT_EVALUABLE_REASON_LABELS,
    DefaultRateResult,
    tasa_no_evaluable,
)
from nikodym.eda.exceptions import EdaError
from nikodym.eda.stability import NOT_EVALUABLE_REASON_LABELS
from nikodym.eda.step import EdaStep
from nikodym.guided.summaries import SummaryContext, build_stage_summary
from nikodym.performance.config import PerformanceConfig
from nikodym.report import prose
from nikodym.report.builder import ReportBuilder
from nikodym.report.config import ReportConfig
from nikodym.report.renderer import HtmlReportRenderer
from nikodym.stability.config import StabilityConfig

# ───────────────────────── la regla nueva ─────────────────────────


def _correr_sin_eje(frame: pd.DataFrame | None = None) -> tuple[object, InMemoryAuditSink, Study]:
    """Corre ``EdaStep`` con los defaults de ``eda``, sin fecha y con partición aleatoria."""
    cfg = _eda_defaults(columns=("score",))
    study = _study_con_data(
        _frame_sin_fecha() if frame is None else frame, cfg, _data_config_aleatorio()
    )
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    return study._run_one(EdaStep.from_config(cfg)), sink, study


def test_sin_fecha_ni_cohorte_la_tasa_es_no_evaluable_y_la_corrida_sigue() -> None:
    """🔴 Nace rojo: hoy ``EdaStep`` levanta ``EdaError`` y la corrida muere en la 2.ª etapa."""
    result, _, study = _correr_sin_eje()

    assert result.default_rate.not_evaluable_reason == "sin_eje_temporal"
    assert result.default_rate.axis == "period"
    assert result.axis_inferred is False
    # El resto del análisis exploratorio corrió completo: no se degrada lo que sí se puede hacer.
    assert len(result.univariate.profiles) == 1
    assert not result.quality.by_column.empty
    for clave in ("default_rate", "stability", "univariate", "quality", "figures", "eda_card"):
        assert study.artifacts.has("eda", clave)


def test_la_tabla_vacia_conserva_las_seis_columnas_del_contrato() -> None:
    """Una tabla vacía sigue siendo la tabla: sus consumidores leen columnas, no adivinan."""
    result, _, _ = _correr_sin_eje()

    assert list(result.default_rate.by_period.columns) == list(_RESULT_COLUMNS)
    assert len(result.default_rate.by_period) == 0


def test_la_causa_y_la_tabla_vacia_van_juntas_en_los_dos_sentidos() -> None:
    """Invariante de D-SC-17: hay causa **si y sólo si** ``by_period`` está vacía."""
    degradado, _, _ = _correr_sin_eje()
    assert degradado.default_rate.not_evaluable_reason is not None
    assert degradado.default_rate.by_period.empty

    cfg = _eda_defaults(columns=("score",))
    normal = _study_con_data(_frame_sin_fecha(), cfg, _data_config_por_cohorte())._run_one(
        EdaStep.from_config(cfg)
    )
    assert normal.default_rate.not_evaluable_reason is None
    assert not normal.default_rate.by_period.empty


def test_la_tasa_global_se_conserva_y_es_la_de_toda_la_poblacion() -> None:
    """La tasa global no necesita eje: ``n_bad / n_eligible`` sobre el frame analizado."""
    frame = _frame_sin_fecha()
    result, _, _ = _correr_sin_eje(frame)

    elegibles = frame["target"].isin((0, 1)).fillna(False)
    esperada = float(frame["target"].eq(1).fillna(False).sum()) / float(elegibles.sum())
    assert result.default_rate.overall_rate == esperada
    assert math.isfinite(result.default_rate.overall_rate)


def test_sin_operaciones_elegibles_la_tasa_global_sigue_siendo_nan() -> None:
    """El cruce «sin eje **y** sin elegibles»: la ausencia de hoy se conserva, no se rellena.

    Son dos ausencias independientes y se publican juntas sin contradecirse: la causa dice que no
    hubo eje, y el ``NaN`` de la tasa global dice lo que ya decía antes de esta enmienda
    (``test_n_eligible_cero_produce_nan_sin_excepcion``).
    """
    frame = _frame_sin_fecha()
    sin_elegibles = frame.assign(target=pd.Series(pd.NA, index=frame.index, dtype="Int8"))
    cfg = _eda_defaults(columns=("score",))
    study = _study_con_data(frame, cfg, _data_config_aleatorio())
    # Las etiquetas conservan su resumen (es metadato del paso anterior); lo que cambia es el
    # frame que `eda` describe, que es de donde sale la elegibilidad.
    study.artifacts.set("data", "frame", sin_elegibles, overwrite=True)

    result = study._run_one(EdaStep.from_config(cfg))

    assert result.default_rate.not_evaluable_reason == "sin_eje_temporal"
    assert math.isnan(result.default_rate.overall_rate)
    card = study.artifacts.get("eda", "eda_card")
    assert math.isnan(card.overall_default_rate)
    # El canal de métricas omite lo no finito (D-GOB-2): no viaja un cero inventado.
    metricas = study.results["metrics"]
    assert metricas["eda.n_periods"] == 0.0
    assert "eda.overall_default_rate" not in metricas


def test_la_decision_de_no_evaluabilidad_va_al_trail_una_sola_vez() -> None:
    """Auditable como todas: la degradación se registra, no se supone."""
    _, sink, _ = _correr_sin_eje()

    decisiones = [
        event.payload
        for event in sink.events
        if event.kind == "decision" and event.payload.get("regla") == "tasa_por_periodo"
    ]
    assert decisiones == [
        {
            "regla": "tasa_por_periodo",
            "umbral": "una columna de fecha o una cohorte declarada",
            "valor": "sin eje temporal",
            "accion": "no_evaluable",
        }
    ]


def test_la_estabilidad_declara_su_propia_causa_y_no_la_de_pocos_periodos() -> None:
    """«Menos de dos períodos» sería verdadero y engañoso: lo que falta es la columna."""
    result, _, study = _correr_sin_eje()

    assert result.stability.not_evaluable_reason == "sin_eje_temporal"
    assert math.isnan(result.stability.cv)
    assert result.stability.flagged is False
    assert study.artifacts.get("eda", "eda_card").stability_not_evaluable_reason == (
        "sin_eje_temporal"
    )


def test_la_card_publica_la_causa_de_la_tasa_y_cero_periodos() -> None:
    """La card es lo que leen el panel, el informe y el resumen: la causa viaja ahí."""
    _, _, study = _correr_sin_eje()
    card = study.artifacts.get("eda", "eda_card")

    assert card.default_rate_not_evaluable_reason == "sin_eje_temporal"
    assert card.n_periods == 0
    assert card.axis == "period"
    assert card.axis_inferred is False


def test_no_se_emite_la_figura_de_la_tasa_y_si_la_de_los_perfiles() -> None:
    """Una figura sobre una tabla vacía no se puede dibujar y ``n_figures`` la contaría igual."""
    result, _, study = _correr_sin_eje()

    titulos = [figura.title for figura in result.figures]
    assert "Tasa de default por período" not in titulos
    assert any(titulo.startswith("Tasa de default por tramo") for titulo in titulos)
    assert study.artifacts.get("eda", "eda_card").n_figures == len(result.figures)


def test_el_rotulo_publico_de_la_causa_existe_y_esta_en_espanol() -> None:
    """Ni el panel ni el informe publican ``sin_eje_temporal`` crudo."""
    assert DEFAULT_RATE_NOT_EVALUABLE_REASON_LABELS["sin_eje_temporal"] == (
        "el archivo no trae columna de fecha ni cohorte declarada"
    )
    assert NOT_EVALUABLE_REASON_LABELS["sin_eje_temporal"] == (
        "el archivo no trae un eje temporal que ordenar"
    )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        pytest.param(
            {"by_period": "con_filas", "not_evaluable_reason": "sin_eje_temporal"},
            "tabla no vacía",
            id="causa-con-filas",
        ),
        pytest.param(
            {"by_period": "vacia", "not_evaluable_reason": None},
            "sin causa",
            id="vacia-sin-causa",
        ),
        pytest.param(
            {"by_period": "vacia_incompleta", "not_evaluable_reason": "sin_eje_temporal"},
            "columna",
            id="vacia-sin-las-columnas",
        ),
    ],
)
def test_el_dto_rechaza_un_resultado_inconsistente(kwargs: dict, match: str) -> None:
    """🔴 La invariante se COMPRUEBA, no sólo se documenta (hallazgo adversarial del rango).

    La causa apaga aguas abajo la figura, la tabla del informe y la validación de columnas de la
    estabilidad. El motor nunca produce un resultado inconsistente, pero esta es API estable y
    quien la use a mano sí puede: con causa y filas escondería evidencia calculada; sin causa y
    sin filas dejaría al lector sin saber por qué no hay tabla.
    """
    tablas = {
        "con_filas": pd.DataFrame(
            {
                "period": ["2024-01"],
                "n_total": [10],
                "n_eligible": [10],
                "n_bad": [2],
                "default_rate": [0.2],
                "low_confidence": [False],
            }
        ),
        "vacia": tasa_no_evaluable(
            _frame_sin_fecha(), target_col="target", axis="period", reason="sin_eje_temporal"
        ).by_period,
        "vacia_incompleta": pd.DataFrame({"period": pd.Series([], dtype="object")}),
    }
    with pytest.raises(ValidationError, match=match):
        DefaultRateResult(
            by_period=tablas[kwargs["by_period"]],
            axis="period",
            overall_rate=0.2,
            not_evaluable_reason=kwargs["not_evaluable_reason"],
        )


# ───────────────────── los bordes que NO se ablandan ─────────────────────


def test_sin_seccion_data_tambien_degrada() -> None:
    """Sin ``data`` no hay cohorte que tomar prestada, que es justo la condición 4."""
    cfg = _eda_defaults(columns=("score",))
    study = _study_with_data(_frame_sin_fecha(), cfg)

    result = study._run_one(EdaStep.from_config(cfg))

    assert result.default_rate.not_evaluable_reason == "sin_eje_temporal"


@pytest.mark.parametrize(
    ("config", "frame", "match"),
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
            id="date_col-declarada-y-no-datetime",
        ),
        pytest.param(
            DefaultRateConfig(min_obs_per_period=1),
            "dos_fechas",
            "más de una columna datetime",
            id="dos-columnas-datetime-sin-date_col",
        ),
        pytest.param(
            DefaultRateConfig(axis="cohort", min_obs_per_period=1),
            None,
            "requiere declarar eda.default_rate.cohort_col",
            id="cohort-sin-cohort_col",
        ),
        pytest.param(
            DefaultRateConfig(axis="cohort", cohort_col="no_existe", min_obs_per_period=1),
            None,
            "columna inexistente",
            id="cohort_col-inexistente",
        ),
    ],
)
def test_los_cinco_errores_del_motor_siguen_siendo_errores(
    config: DefaultRateConfig, frame: str | None, match: str
) -> None:
    """La regla nueva degrada la **ausencia** de eje, nunca una contradicción de lo declarado."""
    datos = _frame_sin_fecha()
    if frame == "dos_fechas":
        datos = datos.assign(
            fecha_1=pd.to_datetime(["2024-01-01"] * len(datos)),
            fecha_2=pd.to_datetime(["2024-02-01"] * len(datos)),
        )
    cfg = EdaConfig(default_rate=config, univariate=UnivariateConfig(columns=("score",)))
    study = _study_con_data(datos, cfg, _data_config_aleatorio())

    with pytest.raises(EdaError, match=match):
        EdaStep.from_config(cfg).execute(study, study.seed_manager.generator_for("eda"))


# ───────────────────── las superficies que lo cuentan ─────────────────────


@pytest.fixture(autouse=True)
def _sin_ortools_en_proceso(fake_binning_process: object) -> None:
    """OR-Tools revienta el proceso de pytest con un *access violation* (trampa ya pagada).

    Los tests de esta capa que corren el pipeline entero usan el doble determinista de OptBinning,
    como el resto de la suite in-process. Lo que aquí se mide es que la corrida **llegue** a
    `done` con `eda` degradada, no los números del binning; la evidencia con OptBinning real son
    las tres corridas del criterio de Cami, fuera de la suite.
    """
    del fake_binning_process


def _corrida_f1_sin_eje(tmp_path: Path) -> Study:
    """Pipeline F1 completo con partición **aleatoria** sobre un archivo sin fecha.

    Es el gate de aceptación de D-SC-17 y el caso exacto que SDD-31 §8 declara soportado: hasta la
    1.19.0 esta corrida moría en `eda` con `EdaError` y arrastraba las nueve etapas siguientes.
    """
    fuente = tmp_path / "behavior.parquet"
    write_behavior_parquet(fuente)
    config = full_f1_config(str(fuente))
    config = config.model_copy(
        update={
            "data": config.data.model_copy(
                update={
                    "partition": config.data.partition.model_copy(
                        update={"strategy": RandomSplitConfig()}
                    )
                }
            ),
            # Con partición aleatoria el frame de 30 filas deja un bin de `segment` con una clase
            # en cero: se describe `score`, que es lo que esta capa necesita ejercer.
            "binning": config.binning.model_copy(
                update={"feature_columns": ("score",), "categorical_columns": ()}
            ),
            "eda": EdaConfig(
                default_rate=DefaultRateConfig(min_obs_per_period=1),
                univariate=UnivariateConfig(columns=("score",), n_quantile_bins=2),
            ),
            "performance": PerformanceConfig(min_rows_per_partition=4),
            "stability": StabilityConfig(psi_bins=2, csi_bins=2, temporal_axis="none"),
        }
    )
    return nikodym.run(config, run_dir=str(tmp_path / "run"))


def test_el_pipeline_f1_completo_termina_done_sin_eje_temporal(tmp_path: Path) -> None:
    """🔴 GATE DE ACEPTACIÓN. Hoy la corrida termina ``failed`` en la segunda etapa."""
    study = _corrida_f1_sin_eje(tmp_path)

    assert study.run_context.status == "done", study.run_context.error
    card = study.artifacts.get("eda", "eda_card")
    assert card.default_rate_not_evaluable_reason == "sin_eje_temporal"
    # Las nueve etapas que `eda` mataba llegaron a publicar lo suyo.
    for dominio, clave in (
        ("binning", "summary"),
        ("selection", "selection_table"),
        ("model", "coefficients"),
        ("scorecard", "scorecard"),
        ("calibration", "parameters"),
    ):
        assert study.artifacts.has(dominio, clave), (dominio, clave)


def test_el_resumen_de_la_etapa_dice_la_tasa_y_su_causa(tmp_path: Path) -> None:
    """Dos líneas, sin denominador inventado y sin decir «0 períodos»."""
    study = _corrida_f1_sin_eje(tmp_path)

    resumen = build_stage_summary(
        "eda",
        study,
        SummaryContext(
            project_dir=None,
            run_dir=None,
            source_label="behavior.parquet",
            partition_label="partición aleatoria",
        ),
    )
    lineas = list(resumen.lines)
    assert lineas[0].startswith("Tasa de malos: ")
    assert lineas[1] == (
        "Tasa de malos en el tiempo: no evaluable "
        "(el archivo no trae columna de fecha ni cohorte declarada)"
    )
    assert resumen.table is None
    texto = "\n".join(lineas)
    for prohibida in ("0 períodos", "por fecha de observación", "sin_eje_temporal"):
        assert prohibida not in texto, prohibida


def test_el_informe_publica_la_causa_una_vez_y_ninguna_frase_falsa(tmp_path: Path) -> None:
    """🔴 El documento entero: sin tabla de la tasa y sin las dos frases que dependían del eje.

    ``_eda_context`` (capítulo «Contexto») y ``_results_eda`` (capítulo «Resultados») leen la
    MISMA card: sin esta rama el informe traía la explicación correcta y, unas páginas antes, «la
    tasa se agrupó por fecha de observación en 0 períodos» y «Con un solo período … la tasa se
    reproduce en la tabla».
    """
    study = _corrida_f1_sin_eje(tmp_path)
    cfg = ReportConfig()
    bundle = ReportBuilder.from_config(cfg).collect(study)
    html = HtmlReportRenderer.from_config(cfg).render(bundle)

    assert "eda.default_rate.by_period" not in bundle.tables
    # DOS veces y no una: los dos capítulos que leen la card la nombran —«Contexto» al describir
    # la población y «Resultados» al anunciar qué tablas siguen—. El número se ancla para que una
    # tercera mención accidental ponga rojo.
    assert html.count("el archivo no trae columna de fecha ni cohorte declarada") == 2
    for falsa in ("en 0 períodos", "Con un solo período", "0 períodos"):
        assert falsa not in html, falsa
    # Ningún identificador del motor llega a la PROSA. En el volcado de auditoría del anexo el
    # slug sí aparece, y el contrato de copy público lo permite ahí y sólo ahí.
    parrafos = (*prose.context_body(bundle), *prose.results_body(bundle, "eda"))
    assert parrafos, "el capítulo tiene que decir algo"
    for parrafo in parrafos:
        assert "sin_eje_temporal" not in parrafo, parrafo
    # 🔴 Y NO exagera el alcance: `eda` describe la partición de `analysis_partition` —de fábrica,
    # desarrollo— y puede muestrearla, así que el informe no puede atribuir los perfiles ni la
    # calidad al archivo entero. Hallazgo de la revisión adversarial del rango, verificado: la
    # corrida de este test usa el default, así que describe 8 de las 30 filas del archivo.
    from nikodym.data.partition import PARTITION_COL

    frame = study.artifacts.get("data", "frame")
    assert study.config.eda.analysis_partition == "desarrollo"
    descritas = int(frame[PARTITION_COL].astype("string").eq("desarrollo").sum())
    assert 0 < descritas < len(frame), (descritas, len(frame))
    for frase in ("población completa", "cartera completa", "todo el archivo"):
        assert frase not in html, frase


@pytest.mark.parametrize(
    ("mutar", "match"),
    [
        pytest.param("vaciar", "no tiene filas para describir", id="frame-vacio"),
        pytest.param("duplicar_indice", "índice único", id="indice-duplicado"),
        pytest.param("sin_target", "columna target existente", id="target-ausente"),
    ],
)
def test_el_constructor_degradado_valida_la_poblacion_igual_que_compute(
    mutar: str, match: str
) -> None:
    """🔴 Los tres guards viven hoy DENTRO de ``compute``, que la rama degradada no llama.

    Se mide **sobre el constructor**, no sobre el paso, y la diferencia la destapó el control
    negativo (f): con el helper quitado, el paso seguía levantando el MISMO ``EdaError`` porque
    ``univariate`` valida el índice otra vez unas líneas después. El test pasaba por la razón
    equivocada y el oráculo no vigilaba nada. Aquí sólo puede levantar quien tiene que levantar.
    """
    frame = _frame_sin_fecha()
    if mutar == "vaciar":
        frame = frame.iloc[:0]
    elif mutar == "duplicar_indice":
        frame = pd.concat([frame, frame.iloc[[0]]])
    else:
        frame = frame.drop(columns=["target"])

    with pytest.raises(EdaError, match=match):
        tasa_no_evaluable(frame, target_col="target", axis="period", reason="sin_eje_temporal")


@pytest.mark.parametrize(
    ("mutar", "match"),
    [
        pytest.param("vaciar", "no tiene filas para describir", id="frame-vacio"),
        pytest.param("duplicar_indice", "índice único", id="indice-duplicado"),
        pytest.param("sin_target", "columna target existente", id="target-ausente"),
    ],
)
def test_la_rama_degradada_valida_la_poblacion_igual_que_la_normal(mutar: str, match: str) -> None:
    """El mismo contrato visto desde el paso: la corrida se detiene con el error de siempre.

    Complementa al anterior —que es el que vigila el guard— midiendo que el paso no publica un
    resultado degradado sobre una población que no valida.
    """
    frame = _frame_sin_fecha()
    if mutar == "vaciar":
        frame = frame.iloc[:0]
    elif mutar == "duplicar_indice":
        frame = pd.concat([frame, frame.iloc[[0]]])
    else:
        frame = frame.drop(columns=["target"])
    # `analysis_partition="todas"` para que el guard que se mide sea el de la TASA y no el filtro
    # de partición del paso, que con un frame vacío corta antes con otro mensaje.
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

    with pytest.raises(EdaError, match=match):
        EdaStep.from_config(cfg).execute(study, study.seed_manager.generator_for("eda"))
