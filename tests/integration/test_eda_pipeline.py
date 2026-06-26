"""Integración ``data`` → ``eda`` vía ``Study.run`` (SDD-27 §10)."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.core.study import Study
from nikodym.data.config import (
    ColumnSpec,
    DataConfig,
    PartitionConfig,
    Predicate,
    RandomSplitConfig,
    Rule,
    SchemaConfig,
    TargetConfig,
)
from nikodym.data.step import INPUT_FRAME_KEY
from nikodym.eda.config import (
    DefaultRateConfig,
    EdaConfig,
    TemporalStabilityConfig,
    UnivariateConfig,
)
from nikodym.eda.step import EDA_ARTIFACTS
from nikodym.testing import assert_bitwise_reproducible

ROOT_SEED = 20_240_626


def _bad_rule() -> Rule:
    """Regla canónica de default para el fixture de integración."""
    return Rule(all_of=(Predicate(col="max_dpd_12m", op=">=", value=90),))


def _raw_frame() -> pd.DataFrame:
    """Dataset crudo pequeño con fecha, target derivable y features EDA."""
    index = pd.Index([f"op-{position:02d}" for position in range(12)], name="loan_id")
    return pd.DataFrame(
        {
            "fecha": pd.Series(
                pd.to_datetime(
                    [
                        "2024-01-15",
                        "2024-01-20",
                        "2024-02-15",
                        "2024-02-20",
                        "2024-03-15",
                        "2024-03-20",
                        "2024-01-25",
                        "2024-02-25",
                        "2024-03-25",
                        "2024-01-28",
                        "2024-02-28",
                        "2024-03-28",
                    ]
                ),
                index=index,
            ),
            "max_dpd_12m": pd.Series([120, 0, 0, 120, 0, 0, 120, 0, 0, 0, 120, 0], index=index),
            "score": pd.Series(
                [10.0, 20.0, 25.0, 30.0, 40.0, 45.0, 55.0, 60.0, 70.0, 75.0, 80.0, 90.0],
                index=index,
            ),
            "segment": pd.Series(["A", "B", "A", "C", "B", "C"] * 2, index=index),
        },
        index=index,
    )


def _data_config() -> DataConfig:
    """Config de datos mínima para correr sin I/O mediante ``input_frame``."""
    return DataConfig(
        schema_=SchemaConfig(
            columns=(
                ColumnSpec(name="fecha", dtype="datetime", nullable=False),
                ColumnSpec(name="max_dpd_12m", dtype="int", nullable=False),
                ColumnSpec(name="score", dtype="float", nullable=False),
                ColumnSpec(name="segment", dtype="str", nullable=False),
            ),
            index_col="loan_id",
        ),
        target=TargetConfig(bad_rule=_bad_rule()),
        partition=PartitionConfig(
            strategy=RandomSplitConfig(
                dev_fraction=0.5,
                holdout_fraction=0.25,
                oot_fraction=0.25,
            ),
            min_bads_per_partition=0,
        ),
    )


def _eda_config() -> EdaConfig:
    """Config EDA determinista y exhaustiva para integración."""
    return EdaConfig(
        analysis_partition="todas",
        default_rate=DefaultRateConfig(date_col="fecha", min_obs_per_period=1),
        stability=TemporalStabilityConfig(threshold=10.0),
        univariate=UnivariateConfig(columns=("score", "segment"), n_quantile_bins=3),
    )


def _study() -> Study:
    """Study con secciones ``data`` y ``eda`` activas."""
    return Study(
        NikodymConfig(
            repro=ReproConfig(seed=ROOT_SEED),
            data=_data_config(),
            eda=_eda_config(),
        )
    )


def _inject_frame(study: Study) -> None:
    """Inyecta el frame crudo bajo la clave pública de ``DataStep``."""
    study.artifacts.set("data", INPUT_FRAME_KEY, _raw_frame())


def _run_pipeline_artifacts() -> tuple[object, ...]:
    """Ejecuta la corrida completa y devuelve sólo artefactos deterministas."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data", "eda"])
    return tuple(study.artifacts.get("eda", key) for key in EDA_ARTIFACTS)


def test_study_run_data_eda_end_to_end_puebla_los_cinco_artefactos() -> None:
    """``Study.run(steps=['data','eda'])`` publica todos los artefactos EDA."""
    study = _study()
    _inject_frame(study)

    assert study.run(steps=["data", "eda"]) is study

    assert study.run_context.status == "done"
    for key in EDA_ARTIFACTS:
        assert study.artifacts.has("eda", key)
    assert study.artifacts.get("eda", "default_rate").overall_rate == pytest.approx(4 / 12)
    assert len(study.artifacts.get("eda", "figures")) == 3


def test_eda_no_muta_frame_de_data_en_corrida_cross_domain() -> None:
    """Correr ``eda`` después de ``data`` deja intacto el frame publicado por ``data``."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data"])
    frame_before = study.artifacts.get("data", "frame").copy(deep=True)

    study.run(steps=["eda"])

    assert_frame_equal(study.artifacts.get("data", "frame"), frame_before)


def test_pipeline_data_eda_es_bitwise_reproducible_sin_muestreo() -> None:
    """La corrida completa sin muestreo es reproducible bit a bit."""
    assert_bitwise_reproducible(_run_pipeline_artifacts)
