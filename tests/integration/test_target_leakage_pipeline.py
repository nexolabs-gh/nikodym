"""Regresión end-to-end: la fuga desde una regla del target infla el AUC."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nikodym.binning.config import BinningConfig
from nikodym.calibration.config import CalibrationConfig
from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.core.study import Study
from nikodym.data.config import (
    CohortSplitConfig,
    DataConfig,
    PartitionConfig,
    Predicate,
    Rule,
    TargetConfig,
)
from nikodym.data.step import INPUT_FRAME_KEY
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


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita importar OR-Tools sin sustituir ningún otro paso del pipeline."""
    del fake_binning_process


def _leakage_frame() -> pd.DataFrame:
    """Cartera donde ``dpd`` define el target, pero no forma bins puros en el doble."""
    dpd = np.array(
        [0] * 80 + [1] * 20 + [2] * 20 + [3] * 80 + [0] * 16 + [1] * 4 + [2] * 4 + [3] * 16
    )
    bad = np.isin(dpd, [1, 3]).astype(int)
    bad_count = 0
    good_count = 0
    signal: list[int] = []
    for value in bad:
        if value:
            signal.append(2 if bad_count % 5 < 3 else 0)
            bad_count += 1
        else:
            signal.append(2 if good_count % 5 < 2 else 0)
            good_count += 1
    return pd.DataFrame(
        {
            "dpd": dpd,
            "signal": signal,
            "cohort": ["dev"] * 200 + ["oot"] * 40,
        },
        index=pd.Index([f"op-{index}" for index in range(240)], name="loan_id"),
    )


def _run_pipeline(feature_columns: tuple[str, ...] | str) -> Study:
    """Corre el F1 completo desde datos crudos hasta métricas discriminantes."""
    config = NikodymConfig(
        repro=ReproConfig(seed=42),
        data=DataConfig(
            target=TargetConfig(
                bad_rule=Rule(
                    any_of=(
                        Predicate(col="dpd", op="==", value=1),
                        Predicate(col="dpd", op="==", value=3),
                    )
                )
            ),
            partition=PartitionConfig(
                strategy=CohortSplitConfig(
                    cohort_col="cohort",
                    oot_cohorts=("oot",),
                    holdout_fraction=0.0,
                ),
                min_bads_per_partition=0,
            ),
        ),
        binning=BinningConfig(
            feature_columns=feature_columns,
            solver="mip",
            monotonic_trend=None,
            max_n_prebins=4,
            max_n_bins=4,
            min_bin_size=0.05,
        ),
        selection=SelectionConfig(
            min_iv=0.0,
            max_iv_action="flag",
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
            anchor_source="development_observed",
            min_fit_rows=1,
        ),
        performance=PerformanceConfig(
            partitions=("desarrollo",),
            n_deciles=5,
            min_rows_per_partition=1,
            min_events_per_partition=1,
        ),
    )
    study = Study(config)
    study.artifacts.set("data", INPUT_FRAME_KEY, _leakage_frame())
    study.run()
    assert study.run_context.status == "done"
    return study


def _development_auc(study: Study) -> float:
    """Lee el AUC publicado por ``performance``, sin recalcularlo en el test."""
    metrics = study.artifacts.get("performance", "discriminant_metrics")
    return float(metrics.loc[metrics["partition"].eq("desarrollo"), "auc"].iloc[0])


def test_auc_baja_al_excluir_del_wildcard_la_columna_que_define_el_target() -> None:
    """D-FUGA-8: el arreglo cambia el número que importa, no sólo una lista interna."""
    with_leak = _run_pipeline(("dpd", "signal"))
    corrected = _run_pipeline("*")

    assert with_leak.artifacts.get("binning", "process").feature_columns_ == ("dpd", "signal")
    assert corrected.artifacts.get("binning", "process").feature_columns_ == ("signal",)
    assert _development_auc(with_leak) == pytest.approx(0.832)
    assert _development_auc(corrected) == pytest.approx(0.600)
    assert _development_auc(corrected) < _development_auc(with_leak)
