"""Helpers F1 compartidos por los tests de la capa ``ui`` (B23.3).

Reproduce el mecanismo de ``tests/unit/test_api_run.py`` (frame crudo de 30 filas + config F1
completa + ``fake_binning_process`` para evitar OR-Tools in-process). NO es un módulo de test (el
prefijo ``_`` lo excluye de la colección de pytest); solo provee builders reutilizables para no
duplicar la config F1 en cada archivo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from nikodym.binning.config import BinningConfig
from nikodym.calibration.config import CalibrationConfig
from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.data.config import (
    CohortSplitConfig,
    ColumnSpec,
    DataConfig,
    LoadingConfig,
    PartitionConfig,
    Predicate,
    Rule,
    SchemaConfig,
    TargetConfig,
)
from nikodym.model.config import (
    IvContributionConfig,
    ModelConfig,
    SignPolicyConfig,
    StepwiseConfig,
)
from nikodym.performance.config import PerformanceConfig
from nikodym.scorecard.config import ScorecardConfig
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)

ROOT_SEED = 20_240_628


def write_behavior_parquet(path: Path) -> None:
    """Materializa un frame crudo de comportamiento (30 filas) que la fake binning predice bien."""
    index = pd.Index([f"op-{position:03d}" for position in range(30)], name="loan_id")
    score = [0, 0, 1, 1, 2, 2, 3, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 1, 2]  # noqa: E501
    segment = [
        "A", "B", "A", "B", "A", "B", "A", "B", "Z", "A", "B", "Z", "A", "Z", "A",
        "B", "B", "Z", "A", "Z", "A", "B", "Z", "A", "B", "Z", "A", "B", "Z", "A",
    ]
    bad = [1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1]
    cohort = ["dev"] * 24 + ["oot"] * 6
    frame = pd.DataFrame(
        {"score": score, "segment": segment, "bad_flag": bad, "cohort": cohort}, index=index
    )
    frame.to_parquet(path)


def _data_config(*, source: str | None) -> DataConfig:
    """Config de datos F1; ``source=None`` fuerza el fallo "sin fuente de datos"."""
    return DataConfig(
        load=LoadingConfig(source=source),
        schema_=SchemaConfig(
            columns=(
                ColumnSpec(name="score", dtype="int", nullable=False),
                ColumnSpec(name="segment", dtype="str", nullable=False),
                ColumnSpec(name="bad_flag", dtype="int", nullable=False),
                ColumnSpec(name="cohort", dtype="str", nullable=False),
            ),
            index_col="loan_id",
        ),
        target=TargetConfig(bad_rule=Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),))),
        partition=PartitionConfig(
            strategy=CohortSplitConfig(
                cohort_col="cohort", oot_cohorts=("oot",), holdout_fraction=0.20
            ),
            min_bads_per_partition=0,
        ),
    )


def full_f1_config(source: str, **overrides: Any) -> NikodymConfig:
    """Config F1 completa data→binning→selection→model→scorecard→calibration→performance."""
    return NikodymConfig(
        repro=ReproConfig(seed=ROOT_SEED),
        data=_data_config(source=source),
        binning=BinningConfig(
            feature_columns=("score", "segment"),
            categorical_columns=("segment",),
            solver="mip",
            max_n_prebins=4,
            max_n_bins=4,
            min_bin_size=0.1,
            time_limit=5,
            monotonic_trend=None,
        ),
        selection=SelectionConfig(
            min_iv=0.0,
            correlation=CorrelationSelectionConfig(enabled=False),
            vif=VifSelectionConfig(enabled=False),
            stability=StabilitySelectionConfig(enabled=False),
        ),
        model=ModelConfig(
            stepwise=StepwiseConfig(direction="none"),
            sign_policy=SignPolicyConfig(action="flag", fail_on_forced_inverted=False),
            iv_contribution=IvContributionConfig(action="flag"),
        ),
        scorecard=ScorecardConfig(rounding_method="none"),
        calibration=CalibrationConfig(
            target_pd=0.31, anchor_source="business_input", min_fit_rows=1
        ),
        performance=PerformanceConfig(),
        **overrides,
    )


def failing_config(source: str) -> NikodymConfig:
    """Config estructuralmente válida que falla en runtime (binning de columna inexistente)."""
    return NikodymConfig(
        repro=ReproConfig(seed=ROOT_SEED),
        data=_data_config(source=source),
        binning=BinningConfig(feature_columns=("no_existe",), categorical_columns=()),
    )
