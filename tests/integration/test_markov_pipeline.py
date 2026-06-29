"""Integración ``data`` → ``markov`` vía ``Study.run`` (SDD-19 §11)."""

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
from nikodym.markov.config import MarkovConfig, MarkovDynamicsConfig, MarkovInputConfig
from nikodym.markov.results import MarkovResult
from nikodym.markov.step import MARKOV_ARTIFACTS
from nikodym.testing import assert_bitwise_reproducible

ROOT_SEED = 20_260_629


def _raw_frame() -> pd.DataFrame:
    """Panel crudo de migraciones con índice único y pares consecutivos."""
    index = pd.Index([f"obs-{i:02d}" for i in range(12)], name="obs_id")
    states = [
        "A",
        "A",
        "A",
        "A",
        "A",
        "B",
        "A",
        "default",
        "B",
        "B",
        "B",
        "default",
    ]
    return pd.DataFrame(
        {
            "entity_id": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6],
            "period": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            "rating": states,
            "bad_flag": [1 if state == "default" else 0 for state in states],
        },
        index=index,
    )


def _bad_rule() -> Rule:
    """Regla target mínima para que ``DataStep`` produz artefactos completos."""
    return Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),))


def _data_config() -> DataConfig:
    """Config de datos para cargar el panel en memoria y particionar de forma estable."""
    return DataConfig(
        schema_=SchemaConfig(
            columns=(
                ColumnSpec(name="entity_id", dtype="int", nullable=False),
                ColumnSpec(name="period", dtype="int", nullable=False),
                ColumnSpec(name="rating", dtype="str", nullable=False),
                ColumnSpec(name="bad_flag", dtype="int", nullable=False),
            ),
            index_col="obs_id",
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


def _markov_config() -> MarkovConfig:
    """Config Markov que consume todo ``data.frame`` sin filtrar por partición."""
    return MarkovConfig(
        input=MarkovInputConfig(
            id_col="entity_id",
            time_col="period",
            state_col="rating",
            partition_col=None,
        ),
        states={"states": ("A", "B", "default")},
        dynamics=MarkovDynamicsConfig(horizon_periods=(1, 2), embedding_policy="diagnose"),
    )


def _study() -> Study:
    """Study con secciones ``data`` y ``markov`` activas."""
    return Study(
        NikodymConfig(
            repro=ReproConfig(seed=ROOT_SEED),
            data=_data_config(),
            markov=_markov_config(),
        )
    )


def _inject_frame(study: Study) -> None:
    """Inyecta el panel crudo bajo la clave pública de ``DataStep``."""
    study.artifacts.set("data", INPUT_FRAME_KEY, _raw_frame())


def _run_pipeline_artifacts() -> tuple[object, ...]:
    """Ejecuta la corrida completa y devuelve artefactos deterministas de Markov."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data", "markov"])
    return tuple(study.artifacts.get("markov", key) for key in MARKOV_ARTIFACTS)


def test_study_run_data_markov_end_to_end_cohort_default() -> None:
    """``Study.run(steps=['data','markov'])`` publica todos los artefactos Markov."""
    study = _study()
    _inject_frame(study)

    assert study.run(steps=["data", "markov"]) is study

    assert study.run_context.status == "done"
    for key in MARKOV_ARTIFACTS:
        assert study.artifacts.has("markov", key)
    result = study.artifacts.get("markov", "result")
    term = study.artifacts.get("markov", "term_structure")
    assert isinstance(result, MarkovResult)
    assert term.loc["state:A|2", "pd_cumulative"] == pytest.approx(0.50)
    assert term.loc["state:B|2", "pd_cumulative"] == pytest.approx(0.75)


def test_markov_no_muta_frame_de_data_en_corrida_cross_domain() -> None:
    """Correr ``markov`` después de ``data`` deja intacto el frame publicado por ``data``."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data"])
    frame_before = study.artifacts.get("data", "frame").copy(deep=True)

    study.run(steps=["markov"])

    assert_frame_equal(study.artifacts.get("data", "frame"), frame_before)


def test_pipeline_data_markov_es_bitwise_reproducible() -> None:
    """La corrida completa es reproducible bit a bit."""
    assert_bitwise_reproducible(_run_pipeline_artifacts)
