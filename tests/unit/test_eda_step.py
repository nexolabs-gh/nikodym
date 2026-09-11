"""Tests de ``EdaStep`` (SDD-27 §4/§6/§7): integración local de analizadores EDA."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.eda as eda
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.data.config import (
    CohortSplitConfig,
    DataConfig,
    LoadingConfig,
    PartitionConfig,
    Predicate,
    RandomSplitConfig,
    Rule,
    TargetConfig,
)
from nikodym.data.partition import PARTITION_COL, TTD_COL, PartitionResult
from nikodym.data.target import STATUS_COL, LabeledFrame, TargetSummary
from nikodym.eda.card import EdaCardSection
from nikodym.eda.config import (
    DefaultRateConfig,
    EdaConfig,
    SamplingConfig,
    TemporalStabilityConfig,
    UnivariateConfig,
)
from nikodym.eda.default_rate import DefaultRateResult
from nikodym.eda.exceptions import EdaError
from nikodym.eda.figures import FigureSpec, _build_figure_specs
from nikodym.eda.step import EDA_ARTIFACTS, EdaResult, EdaStep
from nikodym.eda.univariate import UnivariateResult
from nikodym.testing import assert_bitwise_reproducible

ROOT_SEED = 20_240_626


def _frame(n_rows: int = 12) -> pd.DataFrame:
    """Frame etiquetado y particionado que simula la salida de ``DataStep``."""
    index = pd.Index([f"op-{position:04d}" for position in range(n_rows)], name="loan_id")
    months = ["2024-01-15", "2024-02-15", "2024-03-15"]
    targets = [1 if position % 4 == 0 else 0 for position in range(n_rows)]
    return pd.DataFrame(
        {
            "fecha": pd.Series(
                pd.to_datetime([months[position % len(months)] for position in range(n_rows)]),
                index=index,
            ),
            "score": pd.Series([float(position) for position in range(n_rows)], index=index),
            "segment": pd.Series(
                [["A", "B", "A", "C"][position % 4] for position in range(n_rows)],
                index=index,
                dtype="object",
            ),
            "target": pd.Series(targets, index=index, dtype="Int8"),
            STATUS_COL: pd.Categorical(
                ["malo" if target == 1 else "bueno" for target in targets],
                categories=["bueno", "malo", "indeterminado", "excluido"],
            ),
            PARTITION_COL: pd.Categorical(
                ["desarrollo"] * n_rows,
                categories=["desarrollo", "holdout", "oot", "fuera_de_modelo"],
            ),
            TTD_COL: pd.Series([True] * n_rows, index=index, dtype="bool"),
        },
        index=index,
    )


def _labels(frame: pd.DataFrame) -> LabeledFrame:
    """Construye el contenedor de etiquetas mínimo para ``EdaStep``."""
    n_bad = int(frame["target"].eq(1).sum())
    n_good = int(frame["target"].eq(0).sum())
    return LabeledFrame(
        frame=frame.copy(deep=True),
        target_col="target",
        status_col=STATUS_COL,
        summary=TargetSummary(
            class_counts={
                "bueno": n_good,
                "malo": n_bad,
                "indeterminado": 0,
                "excluido": 0,
            },
            bad_rate=n_bad / (n_bad + n_good),
            exclusions_by_reason={},
            ambiguous_rows=0,
        ),
    )


def _splits(frame: pd.DataFrame) -> PartitionResult:
    """Construye un ``PartitionResult`` coherente con la columna ``partition``."""
    n_rows = len(frame)
    n_bad = int(frame["target"].eq(1).sum())
    return PartitionResult(
        frame=frame.copy(deep=True),
        sizes={
            "desarrollo": n_rows,
            "holdout": 0,
            "oot": 0,
            "fuera_de_modelo": 0,
        },
        bad_rates={
            "desarrollo": n_bad / n_rows,
            "holdout": 0.0,
            "oot": 0.0,
            "fuera_de_modelo": 0.0,
        },
        strategy_used="fixture",
    )


def _config(*, sampling: SamplingConfig | None = None) -> EdaConfig:
    """Config EDA determinista con columnas explícitas para evitar heurísticas de test."""
    return EdaConfig(
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        stability=TemporalStabilityConfig(threshold=10.0),
        univariate=UnivariateConfig(
            columns=("score",),
            n_quantile_bins=3,
            compute_descriptive_iv=True,
        ),
        sampling=sampling or SamplingConfig(),
    )


def _study_with_data(frame: pd.DataFrame, cfg: EdaConfig | None = None) -> Study:
    """Crea un ``Study`` con artefactos de ``data`` precargados."""
    study = Study(NikodymConfig(repro=ReproConfig(seed=ROOT_SEED), eda=cfg or _config()))
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("data", "labels", _labels(frame))
    study.artifacts.set("data", "splits", _splits(frame))
    return study


def _run_step(frame: pd.DataFrame | None = None, cfg: EdaConfig | None = None) -> EdaResult:
    """Ejecuta ``EdaStep`` aislado y devuelve su resultado."""
    study = _study_with_data(_frame() if frame is None else frame, cfg)
    return EdaStep.from_config(study.config.eda).execute(
        study,
        study.seed_manager.generator_for("eda"),
    )


def test_edastep_registrado_requires_provides_from_config_y_reexports() -> None:
    """``EdaStep`` se registra como ``standard`` y expone el contrato CT-1 exacto."""
    cfg = _config()
    step = EdaStep.from_config(cfg)

    assert REGISTRY.resolve("eda", "standard") is EdaStep
    assert eda.__getattr__("EdaCardSection") is EdaCardSection
    assert eda.__getattr__("EdaStep") is EdaStep
    assert eda.__getattr__("EdaResult") is EdaResult
    assert eda.__getattr__("FigureSpec") is FigureSpec
    assert step.config is cfg
    assert step.name == "eda"
    assert step.requires == (("data", "frame"), ("data", "labels"))
    assert EDA_ARTIFACTS == (
        "default_rate",
        "stability",
        "univariate",
        "quality",
        "figures",
        "eda_card",
    )
    assert step.provides == tuple(("eda", key) for key in EDA_ARTIFACTS)


def test_execute_publica_seis_artefactos_figures_card_y_no_muta_data() -> None:
    """``execute`` puebla artefactos EDA, no muta frame/labels y produce figuras golden."""
    frame = _frame()
    study = _study_with_data(frame)
    frame_before = study.artifacts.get("data", "frame").copy(deep=True)
    labels_before = study.artifacts.get("data", "labels").frame.copy(deep=True)

    result = EdaStep.from_config(study.config.eda).execute(
        study,
        study.seed_manager.generator_for("eda"),
    )

    assert isinstance(result, EdaResult)
    for key in EDA_ARTIFACTS:
        assert study.artifacts.has("eda", key)
    assert study.artifacts.get("eda", "default_rate") is result.default_rate
    assert study.artifacts.get("eda", "stability") is result.stability
    assert study.artifacts.get("eda", "univariate") is result.univariate
    assert study.artifacts.get("eda", "quality") is result.quality
    assert study.artifacts.get("eda", "figures") == result.figures
    eda_card = study.artifacts.get("eda", "eda_card")
    assert isinstance(eda_card, EdaCardSection)
    assert eda_card.overall_default_rate == result.default_rate.overall_rate
    assert eda_card.n_figures == len(result.figures)
    assert_frame_equal(study.artifacts.get("data", "frame"), frame_before)
    assert_frame_equal(study.artifacts.get("data", "labels").frame, labels_before)

    line = result.figures[0]
    assert line.kind == "line"
    assert line.title == "Tasa de default por período"
    assert line.x == "period"
    assert line.y == "default_rate"
    assert line.series is None
    assert_frame_equal(
        line.data,
        result.default_rate.by_period.loc[:, ["period", "default_rate"]],
    )

    bar = result.figures[1]
    assert bar.kind == "bar"
    assert bar.title == "Tasa de default por tramo: score"
    assert bar.x == "tramo"
    assert bar.y == "default_rate"
    assert bar.series is None
    assert_frame_equal(
        bar.data,
        result.univariate.profiles["score"].loc[:, ["tramo", "default_rate"]],
    )


def test_muestreo_emite_exactamente_un_evento_decision_y_sin_muestreo_no_emite() -> None:
    """El muestreo opt-in registra una sola decisión ``muestreo_eda``."""
    sampled_cfg = _config(sampling=SamplingConfig(enabled=True, max_rows=1000))
    sampled_study = _study_with_data(_frame(n_rows=1200), sampled_cfg)
    sampled_sink = InMemoryAuditSink()
    sampled_study.set_audit_sink(sampled_sink)

    sampled_study._run_one(EdaStep.from_config(sampled_cfg))

    sampling_events = [
        event
        for event in sampled_sink.events
        if event.kind == "decision" and event.payload.get("regla") == "muestreo_eda"
    ]
    assert len(sampling_events) == 1
    assert sampling_events[0].payload == {
        "regla": "muestreo_eda",
        "umbral": 1000,
        "valor": 1200,
        "accion": "muestrear",
    }

    unsampled_cfg = _config(sampling=SamplingConfig(enabled=True, max_rows=1000))
    unsampled_study = _study_with_data(_frame(n_rows=12), unsampled_cfg)
    unsampled_sink = InMemoryAuditSink()
    unsampled_study.set_audit_sink(unsampled_sink)

    unsampled_study._run_one(EdaStep.from_config(unsampled_cfg))

    assert [
        event
        for event in unsampled_sink.events
        if event.kind == "decision" and event.payload.get("regla") == "muestreo_eda"
    ] == []


def test_reproducibilidad_bitwise_sin_muestreo() -> None:
    """Sin muestreo, ``EdaStep`` es función determinista del frame y config."""
    assert_bitwise_reproducible(lambda: _run_step())


def test_columns_none_excluye_estructurales_fecha_y_cohorte() -> None:
    """La resolución automática perfila sólo features no estructurales."""
    frame = _frame().assign(cohort="2024Q1")
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(
            date_col="fecha",
            cohort_col="cohort",
            min_obs_per_period=1,
        ),
        stability=TemporalStabilityConfig(threshold=10.0),
        univariate=UnivariateConfig(columns=None, n_quantile_bins=3),
    )
    result = _run_step(frame, cfg)

    assert tuple(result.univariate.profiles) == ("score", "segment")


def test_columns_none_con_fecha_inferida_excluye_datetime() -> None:
    """Si ``date_col`` se infiere, la columna datetime no se perfila como feature."""
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(date_col=None, min_obs_per_period=1),
        stability=TemporalStabilityConfig(threshold=10.0),
        univariate=UnivariateConfig(columns=None, n_quantile_bins=3),
    )
    result = _run_step(_frame(), cfg)

    assert tuple(result.univariate.profiles) == ("score", "segment")


@pytest.mark.parametrize(
    ("particion", "esperadas"),
    [("desarrollo", 6), ("holdout", 3), ("oot", 2), ("todas", 12)],
)
def test_analysis_partition_despacha_cada_muestra(particion: str, esperadas: int) -> None:
    """Oráculo de despacho y de efecto de ``eda.analysis_partition`` (registry D-RDY-ABA-2/3).

    Las cuatro opciones cambian la POBLACIÓN que se describe, y se mide por el total de
    operaciones que entra a la tasa de incumplimiento: cada muestra su conteo, y «todas» el
    archivo entero —incluida la operación fuera del modelo, que cuenta pero no entra en la tasa—.
    """
    n_rows = 12
    frame = _frame(n_rows)
    frame[PARTITION_COL] = pd.Categorical(
        ["desarrollo"] * 6 + ["holdout"] * 3 + ["oot"] * 2 + ["fuera_de_modelo"],
        categories=["desarrollo", "holdout", "oot", "fuera_de_modelo"],
    )
    cfg = EdaConfig(
        analysis_partition=particion,  # type: ignore[arg-type]
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",), n_quantile_bins=2),
    )

    result = _run_step(frame, cfg)

    assert int(result.default_rate.by_period["n_total"].sum()) == esperadas


# ─────────────── D-SC-3: el eje se infiere de lo que el usuario ya declaró ───────────────


def _data_config_por_cohorte(*, cohort_col: str = "cohorte") -> DataConfig:
    """Config de ``data`` mínimo con partición por cohorte, como la siembra el esqueleto."""
    return DataConfig(
        load=LoadingConfig(source="cartera.parquet"),
        target=TargetConfig(
            bad_rule=Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),)),
        ),
        partition=PartitionConfig(
            strategy=CohortSplitConfig(cohort_col=cohort_col, oot_cohorts=("2024Q2",)),
            min_bads_per_partition=0,
        ),
    )


def _data_config_aleatorio() -> DataConfig:
    """Partición aleatoria: no declara ninguna cohorte que el eje pueda tomar prestada."""
    return DataConfig(
        load=LoadingConfig(source="cartera.parquet"),
        target=TargetConfig(
            bad_rule=Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),)),
        ),
        partition=PartitionConfig(
            strategy=RandomSplitConfig(),
            min_bads_per_partition=0,
        ),
    )


def _frame_sin_fecha(n_rows: int = 12) -> pd.DataFrame:
    """El frame de la fixture sin su columna datetime, con una cohorte y la columna del target."""
    frame = _frame(n_rows).drop(columns=["fecha"])
    return frame.assign(
        cohorte=[["2024Q1", "2024Q2", "2024Q3"][position % 3] for position in range(n_rows)],
        bad_flag=frame["target"].astype("int64"),
    )


def _study_con_data(frame: pd.DataFrame, cfg: EdaConfig, data: DataConfig) -> Study:
    study = Study(NikodymConfig(repro=ReproConfig(seed=ROOT_SEED), data=data, eda=cfg))
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("data", "labels", _labels(frame))
    study.artifacts.set("data", "splits", _splits(frame))
    return study


def _eda_defaults(**univariate: object) -> EdaConfig:
    """Los defaults de ``eda`` —``axis="period"``, sin ``date_col``— con perfiles acotados."""
    return EdaConfig(
        default_rate=DefaultRateConfig(min_obs_per_period=1),
        stability=TemporalStabilityConfig(threshold=10.0),
        univariate=UnivariateConfig(n_quantile_bins=3, **univariate),  # type: ignore[arg-type]
    )


def test_sin_fecha_y_con_particion_por_cohorte_el_eje_se_infiere_a_la_cohorte() -> None:
    """D-SC-3: sin columna de fecha, el eje pasa a la cohorte con que el usuario particionó.

    🔴 Nació ROJO sobre el árbol anterior: con los defaults de ``eda`` —``axis="period"``,
    ``date_col=None``— y un archivo sin fecha, ``_infer_date_column`` levantaba «requiere una
    columna de fecha» y el preset F1 no podía encender la sección (§0-1 de la enmienda). No se
    inventa un eje: se usa el que ``data.partition.strategy`` ya declaró, y la decisión queda
    en el trail.
    """
    cfg = _eda_defaults(columns=("score",))
    study = _study_con_data(_frame_sin_fecha(), cfg, _data_config_por_cohorte())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    result = study._run_one(EdaStep.from_config(cfg))

    assert result.default_rate.axis == "cohort"
    assert result.axis_inferred is True
    assert sorted(result.default_rate.by_period["period"]) == ["2024Q1", "2024Q2", "2024Q3"]
    # La señal temporal no se evalúa sobre cohortes (D-SC-2), y la causa viaja hasta la card.
    assert result.stability.not_evaluable_reason == "eje_cohorte"
    card = study.artifacts.get("eda", "eda_card")
    assert card.axis == "cohort"
    assert card.axis_inferred is True
    assert card.stability_not_evaluable_reason == "eje_cohorte"
    assert card.n_periods == 3
    decisiones = [
        event.payload
        for event in sink.events
        if event.kind == "decision" and event.payload.get("regla") == "eje_eda_inferido"
    ]
    assert decisiones == [
        {
            "regla": "eje_eda_inferido",
            "umbral": "sin columna de fecha y partición por cohorte",
            "valor": "cohorte",
            "accion": "usar_cohorte",
        }
    ]


def test_sin_fecha_ni_cohorte_declarada_sigue_siendo_un_error_anclado_al_campo() -> None:
    """Sin fecha y sin cohorte no hay eje que tomar prestado: ``EdaError`` con ``loc`` (D-VIS)."""
    cfg = _eda_defaults(columns=("score",))
    study = _study_con_data(_frame_sin_fecha(), cfg, _data_config_aleatorio())

    with pytest.raises(EdaError, match="columna de fecha") as capturado:
        EdaStep.from_config(cfg).execute(study, study.seed_manager.generator_for("eda"))

    assert capturado.value.loc == ("eda", "default_rate", "date_col")


def test_sin_config_de_data_tampoco_se_infiere() -> None:
    """Sin sección ``data`` no hay partición que consultar: error, no adivinanza."""
    cfg = _eda_defaults(columns=("score",))
    study = _study_with_data(_frame_sin_fecha(), cfg)

    with pytest.raises(EdaError, match="columna de fecha") as capturado:
        EdaStep.from_config(cfg).execute(study, study.seed_manager.generator_for("eda"))

    assert capturado.value.loc == ("eda", "default_rate", "date_col")


def test_con_fecha_en_el_archivo_el_eje_no_se_infiere() -> None:
    """Control positivo: con una columna datetime la regla no entra y el eje sigue temporal."""
    cfg = _eda_defaults(columns=("score",))
    frame = _frame().assign(cohorte="2024Q1")
    study = _study_con_data(frame, cfg, _data_config_por_cohorte())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    result = study._run_one(EdaStep.from_config(cfg))

    assert result.default_rate.axis == "period"
    assert result.axis_inferred is False
    assert study.artifacts.get("eda", "eda_card").axis_inferred is False
    assert not any(
        event.payload.get("regla") == "eje_eda_inferido"
        for event in sink.events
        if event.kind == "decision"
    )


def test_con_date_col_declarada_y_ausente_no_se_infiere_nada() -> None:
    """La inferencia sólo entra con ``date_col`` en blanco: una fecha declarada ausente es error."""
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(date_col="fecha_que_no_existe", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",)),
    )
    study = _study_con_data(_frame_sin_fecha(), cfg, _data_config_por_cohorte())

    with pytest.raises(EdaError, match="fecha_que_no_existe"):
        EdaStep.from_config(cfg).execute(study, study.seed_manager.generator_for("eda"))


def test_con_eje_de_cohorte_explicito_no_hay_inferencia_y_la_card_lo_dice() -> None:
    """Elegir «por cohorte» a mano deja ``axis_inferred=False``: la card no atribuye una decisión
    que el motor no tomó."""
    cfg = EdaConfig(
        default_rate=DefaultRateConfig(axis="cohort", cohort_col="cohorte", min_obs_per_period=1),
        univariate=UnivariateConfig(columns=("score",)),
    )
    study = _study_con_data(_frame_sin_fecha(), cfg, _data_config_por_cohorte())

    result = study._run_one(EdaStep.from_config(cfg))
    card = study.artifacts.get("eda", "eda_card")

    assert result.default_rate.axis == "cohort"
    assert result.axis_inferred is False
    assert card.axis == "cohort"
    assert card.axis_inferred is False
    assert card.stability_not_evaluable_reason == "eje_cohorte"


def test_la_cohorte_inferida_es_estructural_y_no_se_perfila() -> None:
    """La columna que hace de eje sale del perfil por variable, igual que una cohorte declarada."""
    cfg = _eda_defaults(columns=None)
    study = _study_con_data(_frame_sin_fecha(), cfg, _data_config_por_cohorte())

    result = study._run_one(EdaStep.from_config(cfg))

    assert "cohorte" not in result.univariate.profiles


# ─────────────── §8-8: las columnas que definen el target no se describen contra él ───────────────


def test_columns_none_excluye_las_columnas_de_las_reglas_del_target() -> None:
    """Respuesta 8 de Cami: ``bad_flag`` —la columna que define la etiqueta— sale del perfil por
    defecto. Describirla «frente al incumplimiento» daba una tasa 0 %/100 % por tramo que no
    dice nada. Mismo criterio que el binning: sólo las reglas de «malo» y «bueno», que definen la
    etiqueta; las de exclusión e indeterminación seleccionan la muestra y no se tocan."""
    cfg = _eda_defaults(columns=None)
    study = _study_con_data(_frame_sin_fecha(), cfg, _data_config_por_cohorte())

    result = study._run_one(EdaStep.from_config(cfg))

    assert "bad_flag" not in result.univariate.profiles
    assert tuple(result.univariate.profiles) == ("score", "segment")


def test_columns_explicitas_si_pueden_pedir_la_columna_del_target() -> None:
    """La exclusión es del alcance POR DEFECTO: quien la pide por su nombre la obtiene."""
    cfg = _eda_defaults(columns=("bad_flag",))
    study = _study_con_data(_frame_sin_fecha(), cfg, _data_config_por_cohorte())

    result = study._run_one(EdaStep.from_config(cfg))

    assert tuple(result.univariate.profiles) == ("bad_flag",)


def test_figures_no_crea_linea_si_default_rate_es_cohorte() -> None:
    """El gráfico de línea sólo existe para el eje temporal especificado por SDD-27."""
    default_rate = DefaultRateResult(
        by_period=pd.DataFrame(
            {
                "period": ["2024Q1"],
                "n_total": [10],
                "n_eligible": [10],
                "n_bad": [2],
                "default_rate": [0.2],
                "low_confidence": [False],
            }
        ),
        axis="cohort",
        overall_rate=0.2,
    )
    univariate = UnivariateResult(
        profiles={
            "score": pd.DataFrame(
                {
                    "tramo": ["bajo"],
                    "n": pd.Series([10], dtype="int64"),
                    "coverage": [1.0],
                    "default_rate": [0.2],
                }
            )
        },
        descriptive_iv={},
    )

    figures = _build_figure_specs(default_rate=default_rate, univariate=univariate)

    assert len(figures) == 1
    assert figures[0].kind == "bar"


@pytest.mark.parametrize(
    ("domain_key", "value", "match"),
    [
        ("frame", object(), "pandas.DataFrame"),
        ("labels", object(), "LabeledFrame"),
    ],
)
def test_execute_rechaza_artefactos_data_mal_tipados(
    domain_key: str,
    value: object,
    match: str,
) -> None:
    """Los artefactos obligatorios de ``data`` fallan con ``EdaError`` claro."""
    frame = _frame()
    study = _study_with_data(frame)
    study.artifacts.set("data", domain_key, value, overwrite=True)

    with pytest.raises(EdaError, match=match):
        EdaStep.from_config(study.config.eda).execute(
            study,
            study.seed_manager.generator_for("eda"),
        )


def test_execute_rechaza_splits_mal_tipado_si_filtra_particion() -> None:
    """``splits`` se lee condicionalmente y debe ser ``PartitionResult``."""
    frame = _frame()
    study = _study_with_data(frame)
    study.artifacts.set("data", "splits", object(), overwrite=True)

    with pytest.raises(EdaError, match="PartitionResult"):
        EdaStep.from_config(study.config.eda).execute(
            study,
            study.seed_manager.generator_for("eda"),
        )


def test_execute_rechaza_frame_sin_columna_partition() -> None:
    """Filtrar particiones requiere la columna producida por ``DataStep``."""
    frame = _frame()
    study = _study_with_data(frame.drop(columns=[PARTITION_COL]))

    with pytest.raises(EdaError, match="columna 'partition'"):
        EdaStep.from_config(study.config.eda).execute(
            study,
            study.seed_manager.generator_for("eda"),
        )


def test_execute_rechaza_particion_sin_filas() -> None:
    """Una partición configurada sin filas falla antes de los analizadores."""
    frame = _frame()
    frame[PARTITION_COL] = pd.Categorical(
        ["holdout"] * len(frame),
        categories=["desarrollo", "holdout", "oot", "fuera_de_modelo"],
    )
    study = _study_with_data(frame)

    with pytest.raises(EdaError, match="no tiene filas"):
        EdaStep.from_config(study.config.eda).execute(
            study,
            study.seed_manager.generator_for("eda"),
        )


def test_figurespec_es_modelo_frozen_con_dataframe() -> None:
    """``FigureSpec`` conserva el DataFrame y no permite reasignar campos."""
    data = pd.DataFrame({"period": [pd.Period("2024-01", freq="M")], "default_rate": [0.1]})
    spec = FigureSpec(
        kind="line",
        title="Tasa de default por período",
        data=data,
        x="period",
        y="default_rate",
    )

    assert spec.kind == "line"
    assert_frame_equal(spec.data, data)
    with pytest.raises(ValidationError, match="frozen"):
        spec.title = "otra"
