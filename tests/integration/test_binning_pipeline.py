"""Integración ``data`` → ``binning`` vía ``Study.run`` (SDD-06 §10)."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from nikodym.binning.config import BinningConfig
from nikodym.binning.step import BINNING_ARTIFACTS
from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.core.exceptions import ArtifactNotFoundError
from nikodym.core.study import Study
from nikodym.data.config import (
    CohortSplitConfig,
    ColumnSpec,
    DataConfig,
    PartitionConfig,
    Predicate,
    Rule,
    SchemaConfig,
    TargetConfig,
)
from nikodym.data.partition import PARTITION_COL, TTD_COL, PartitionResult
from nikodym.data.step import INPUT_FRAME_KEY
from nikodym.data.target import LabeledFrame, TargetSummary
from nikodym.testing import assert_bitwise_reproducible

ROOT_SEED = 20_240_627


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita importar OR-Tools dentro del proceso pytest."""
    del fake_binning_process


def _bad_rule() -> Rule:
    """Regla canónica de default para el fixture de integración."""
    return Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),))


def _raw_frame() -> pd.DataFrame:
    """Dataset crudo con cohorte determinista: ocho Desarrollo y cuatro OOT."""
    index = pd.Index([f"op-{position:03d}" for position in range(12)], name="loan_id")
    return pd.DataFrame(
        {
            "score": [0, 0, 1, 1, 2, 2, 3, 3, 0, 3, 1, 2],
            "segment": ["A", "A", "A", "A", "B", "B", "B", "B", "Z", "A", "B", "Z"],
            "bad_flag": [0, 0, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1],
            "cohort": ["dev"] * 8 + ["oot"] * 4,
        },
        index=index,
    )


def _data_config() -> DataConfig:
    """Config de datos mínima para correr sin I/O mediante ``input_frame``."""
    return DataConfig(
        schema_=SchemaConfig(
            columns=(
                ColumnSpec(name="score", dtype="int", nullable=False),
                ColumnSpec(name="segment", dtype="str", nullable=False),
                ColumnSpec(name="bad_flag", dtype="int", nullable=False),
                ColumnSpec(name="cohort", dtype="str", nullable=False),
            ),
            index_col="loan_id",
        ),
        target=TargetConfig(bad_rule=_bad_rule()),
        partition=PartitionConfig(
            strategy=CohortSplitConfig(
                cohort_col="cohort",
                oot_cohorts=("oot",),
                holdout_fraction=0.0,
            ),
            min_bads_per_partition=0,
        ),
    )


def _binning_config() -> BinningConfig:
    """Config de binning determinista para el pipeline de integración."""
    return BinningConfig(
        feature_columns=("score", "segment"),
        categorical_columns=("segment",),
        solver="mip",
        max_n_prebins=4,
        max_n_bins=4,
        min_bin_size=0.1,
        time_limit=5,
        monotonic_trend=None,
    )


def _study() -> Study:
    """Study con secciones ``data`` y ``binning`` activas."""
    return Study(
        NikodymConfig(
            repro=ReproConfig(seed=ROOT_SEED),
            data=_data_config(),
            binning=_binning_config(),
        )
    )


def _inject_frame(study: Study) -> None:
    """Inyecta el frame crudo bajo la clave pública de ``DataStep``."""
    study.artifacts.set("data", INPUT_FRAME_KEY, _raw_frame())


def _run_pipeline_artifacts() -> tuple[object, ...]:
    """Ejecuta la corrida completa y devuelve artefactos deterministas de binning."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data", "binning"])
    return tuple(study.artifacts.get("binning", key) for key in BINNING_ARTIFACTS)


def _manual_data_artifacts(study: Study) -> None:
    """Publica artefactos mínimos de data para verificar CT-1 sin ejecutar ``DataStep``."""
    frame = pd.DataFrame(
        {
            "score": [0, 1],
            "target": [0, 1],
            "label_status": ["bueno", "malo"],
            PARTITION_COL: ["desarrollo", "desarrollo"],
            TTD_COL: [True, True],
        },
        index=pd.Index(["a", "b"], name="loan_id"),
    )
    labels = LabeledFrame(
        frame=frame.copy(deep=True),
        target_col="target",
        status_col="label_status",
        summary=TargetSummary(
            class_counts={"bueno": 1, "malo": 1, "indeterminado": 0, "excluido": 0},
            bad_rate=0.5,
            exclusions_by_reason={},
            ambiguous_rows=0,
        ),
    )
    splits = PartitionResult(
        frame=frame.copy(deep=True),
        partition_col=PARTITION_COL,
        ttd_col=TTD_COL,
        sizes={"desarrollo": 2, "holdout": 0, "oot": 0, "fuera_de_modelo": 0},
        bad_rates={"desarrollo": 0.5, "holdout": 0.0, "oot": 0.0, "fuera_de_modelo": 0.0},
        strategy_used="manual",
    )
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("data", "labels", labels)
    study.artifacts.set("data", "splits", splits)


def test_study_run_data_binning_end_to_end_puebla_los_seis_artefactos() -> None:
    """``Study.run(steps=['data','binning'])`` publica todos los artefactos de binning."""
    study = _study()
    _inject_frame(study)

    assert study.run(steps=["data", "binning"]) is study

    assert study.run_context.status == "done"
    for key in BINNING_ARTIFACTS:
        assert study.artifacts.has("binning", key)
    woe_frame = study.artifacts.get("binning", "woe_frame")
    assert woe_frame.index.equals(study.artifacts.get("data", "frame").index)
    assert woe_frame.columns.tolist() == [
        "target",
        "label_status",
        PARTITION_COL,
        TTD_COL,
        "score__woe",
        "segment__woe",
    ]


def test_binning_requires_exige_los_cuatro_artefactos_de_data_antes_de_execute() -> None:
    """Si falta ``data.special``, CT-1 levanta ``ArtifactNotFoundError`` antes de ejecutar."""
    study = Study(NikodymConfig(binning=BinningConfig(feature_columns=("score",))))
    _manual_data_artifacts(study)

    with pytest.raises(ArtifactNotFoundError, match=r"\('data', 'special'\)"):
        study.run_step("binning")


def test_binning_no_muta_frame_de_data_en_corrida_cross_domain() -> None:
    """Correr ``binning`` después de ``data`` deja intacto el frame publicado por ``data``."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data"])
    frame_before = study.artifacts.get("data", "frame").copy(deep=True)

    study.run(steps=["binning"])

    assert_frame_equal(study.artifacts.get("data", "frame"), frame_before)


def test_pipeline_data_binning_es_bitwise_reproducible_sin_muestreo() -> None:
    """La corrida completa sin muestreo es reproducible bit a bit."""
    assert_bitwise_reproducible(_run_pipeline_artifacts)
