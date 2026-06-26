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
from nikodym.data.partition import PARTITION_COL, TTD_COL, PartitionResult
from nikodym.data.target import STATUS_COL, LabeledFrame, TargetSummary
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
    assert eda.__getattr__("EdaStep") is EdaStep
    assert eda.__getattr__("EdaResult") is EdaResult
    assert eda.__getattr__("FigureSpec") is FigureSpec
    assert step.config is cfg
    assert step.name == "eda"
    assert step.requires == (("data", "frame"), ("data", "labels"))
    assert EDA_ARTIFACTS == ("default_rate", "stability", "univariate", "quality", "figures")
    assert step.provides == tuple(("eda", key) for key in EDA_ARTIFACTS)


def test_execute_publica_cinco_artefactos_figures_y_no_muta_data() -> None:
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
