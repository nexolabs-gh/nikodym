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
    _behavior_frame().to_parquet(path)


def _behavior_frame() -> pd.DataFrame:
    """El frame crudo de comportamiento de 30 filas, con ``loan_id`` como índice."""
    index = pd.Index([f"op-{position:03d}" for position in range(30)], name="loan_id")
    score = [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
        3,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
        3,
        1,
        2,
    ]
    segment = [
        "A",
        "B",
        "A",
        "B",
        "A",
        "B",
        "A",
        "B",
        "Z",
        "A",
        "B",
        "Z",
        "A",
        "Z",
        "A",
        "B",
        "B",
        "Z",
        "A",
        "Z",
        "A",
        "B",
        "Z",
        "A",
        "B",
        "Z",
        "A",
        "B",
        "Z",
        "A",
    ]
    bad = [1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1]
    cohort = ["dev"] * 24 + ["oot"] * 6
    return pd.DataFrame(
        {"score": score, "segment": segment, "bad_flag": bad, "cohort": cohort}, index=index
    )


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


def _stacked_behavior_frame(repeats: int) -> pd.DataFrame:
    """El frame de comportamiento apilado ``repeats`` veces, con el índice vuelto único."""
    base = _behavior_frame()
    frame = pd.concat([base] * repeats, ignore_index=True)
    frame.index = pd.Index([f"op-{position:05d}" for position in range(len(frame))], name="loan_id")
    return frame


def write_stacked_behavior_parquet(path: Path, *, repeats: int = 50) -> int:
    """Materializa el frame de comportamiento apilado ``repeats`` veces (1.500 filas de fábrica).

    Es el observado de S10: con cuatro valores distintos de ``score`` y 1.500 filas, cada decil
    del F1 trae decenas de PD calibradas bit a bit idénticas, y ``performance`` moría porque la
    media en coma flotante quedaba 2 ULP por encima del máximo. Devuelve el número de filas.
    """
    frame = _stacked_behavior_frame(repeats)
    frame.to_parquet(path)
    return len(frame)


#: Columna casi única que los tests del tope de EDA usan como eje de cohorte: un identificador.
NEAR_UNIQUE_COHORT_COL = "operacion"


def write_near_unique_cohort_parquet(path: Path, *, repeats: int = 80) -> int:
    """Materializa el frame de comportamiento repetido ``repeats`` veces más un identificador.

    Es el caso adversarial de la cuarta pasada de Codex en S9: agrupar la tasa por una columna
    casi única produce **una cohorte por operación**. El frame de 30 filas se apila ``repeats``
    veces (2.400 filas de fábrica), el índice vuelve a ser único y :data:`NEAR_UNIQUE_COHORT_COL`
    lleva un identificador distinto por fila. Devuelve el número de filas escritas; con los
    defaults de ``eda`` —población de desarrollo— quedan más de 1.000 cohortes, que es lo que el
    tope de la respuesta tiene que recortar.
    """
    frame = _stacked_behavior_frame(repeats)
    frame[NEAR_UNIQUE_COHORT_COL] = [f"ID-{position:05d}" for position in range(len(frame))]
    frame.to_parquet(path)
    return len(frame)


def eda_only_config(source: str, *, cohort_col: str = NEAR_UNIQUE_COHORT_COL) -> NikodymConfig:
    """Config ``data`` + ``eda`` con la tasa agrupada por ``cohort_col`` (sin modelar nada).

    Sólo corre el análisis exploratorio: es lo que el tope de la respuesta acota; el F1 entero
    sobre un frame apilado es el otro caso, el de :func:`write_stacked_behavior_parquet`.
    ``min_obs_per_period=1`` para que cada cohorte de una sola operación tenga tasa y la tabla sea
    tan larga como el identificador.
    """
    from nikodym.eda.config import DefaultRateConfig, EdaConfig, UnivariateConfig

    data = _data_config(source=source)
    schema = data.schema_.model_copy(
        update={
            "columns": (
                *data.schema_.columns,
                ColumnSpec(name=cohort_col, dtype="str", nullable=False),
            )
        }
    )
    return NikodymConfig(
        repro=ReproConfig(seed=ROOT_SEED),
        data=data.model_copy(update={"schema_": schema}),
        eda=EdaConfig(
            default_rate=DefaultRateConfig(
                axis="cohort", cohort_col=cohort_col, min_obs_per_period=1
            ),
            univariate=UnivariateConfig(columns=("score",), n_quantile_bins=2),
        ),
    )
