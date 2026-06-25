"""Tests de ``DataStep`` (SDD-02 §4/§7): pipeline data end-to-end y artefactos."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.core.exceptions import ConfigError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.data import (
    DataCardSection,
    DataConfig,
    DataLoader,
    DataStep,
    LabeledFrame,
    MaskedFrame,
    Partitioner,
    PartitionResult,
    SchemaValidator,
    SpecialValuePolicy,
    TargetDefinition,
    data_hash,
)
from nikodym.data.config import (
    ColumnSpec,
    LoadingConfig,
    MissingConfig,
    PartitionConfig,
    Predicate,
    RandomSplitConfig,
    Rule,
    SchemaConfig,
    SpecialValueSpec,
    TargetConfig,
)
from nikodym.data.step import INPUT_FRAME_KEY, _source_label

ROOT_SEED = 20_240_624
EXPECTED_DATA_HASH = "3cd64170edcc04ffb69a1379da2218af27037c79b698cd15ad03397881394c5d"
EXPECTED_SIZES = {
    "desarrollo": 7,
    "holdout": 2,
    "oot": 3,
    "fuera_de_modelo": 0,
}
EXPECTED_BAD_RATES = {
    "desarrollo": 1 / 7,
    "holdout": 0.0,
    "oot": 1.0,
    "fuera_de_modelo": 0.0,
}
EXPECTED_PARTITIONS = {
    "op-00": "oot",
    "op-01": "holdout",
    "op-02": "desarrollo",
    "op-03": "oot",
    "op-04": "desarrollo",
    "op-05": "desarrollo",
    "op-06": "oot",
    "op-07": "desarrollo",
    "op-08": "holdout",
    "op-09": "desarrollo",
    "op-10": "desarrollo",
    "op-11": "desarrollo",
}


def _bad_rule() -> Rule:
    """Regla canónica de incumplimiento: mora máxima >= 90 días."""
    return Rule(all_of=(Predicate(col="max_dpd_12m", op=">=", value=90),))


def _raw_frame() -> pd.DataFrame:
    """DataFrame sintético determinista con índice regulatorio estable."""
    index = pd.Index([f"op-{i:02d}" for i in range(12)], name="loan_id")
    return pd.DataFrame(
        {
            "max_dpd_12m": [120, 0, 0, 120, 0, 0, 120, 0, 0, 120, 0, 0],
            "income": [
                1000.0,
                1200.0,
                -99999.0,
                900.0,
                800.0,
                700.0,
                500.0,
                1300.0,
                1100.0,
                400.0,
                950.0,
                1050.0,
            ],
        },
        index=index,
    )


def _data_config(**updates: object) -> DataConfig:
    """DataConfig mínimo válido para ejecutar todo el pipeline sin I/O."""
    cfg = DataConfig(
        schema_=SchemaConfig(
            columns=(
                ColumnSpec(name="max_dpd_12m", dtype="int", nullable=False),
                ColumnSpec(name="income", dtype="float", nullable=True),
            ),
            index_col="loan_id",
        ),
        missing=MissingConfig(
            special_values=(
                SpecialValueSpec(columns=("income",), sentinels=(-99999.0,), label="sin_ingreso"),
            ),
            max_missing_rate=0.9,
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
    return cfg.model_copy(update=updates) if updates else cfg


def _study(cfg: DataConfig | None = None) -> Study:
    """Construye un Study con semilla fija para golden values reproducibles."""
    return Study(NikodymConfig(repro=ReproConfig(seed=ROOT_SEED), data=cfg or _data_config()))


def _inject_frame(study: Study, frame: pd.DataFrame) -> None:
    """Inyecta el DataFrame en memoria bajo la clave acordada por ``DataStep``."""
    study.artifacts.set("data", INPUT_FRAME_KEY, frame)


def test_datastep_registrado_y_reexports_publicos() -> None:
    """``DataStep`` se registra como ``standard`` y B2d reexporta la superficie pública."""
    cfg = _data_config()
    step = DataStep.from_config(cfg)

    assert REGISTRY.resolve("data", "standard") is DataStep
    assert step.config is cfg
    assert step.name == "data"
    assert step.requires == ()
    assert step.provides == (
        ("data", "frame"),
        ("data", "splits"),
        ("data", "labels"),
        ("data", "special"),
        ("data", "data_hash"),
        ("data", "data_card"),
    )
    assert set(step.provides) == {
        ("data", "frame"),
        ("data", "splits"),
        ("data", "labels"),
        ("data", "special"),
        ("data", "data_hash"),
        ("data", "data_card"),
    }
    assert DataLoader
    assert SchemaValidator
    assert data_hash
    assert SpecialValuePolicy
    assert TargetDefinition
    assert Partitioner


def test_execute_publica_artefactos_golden_y_no_muta_input() -> None:
    """Unit: ``execute`` publica seis artefactos con golden values exactos y no muta el input."""
    cfg = _data_config()
    study = _study(cfg)
    raw = _raw_frame()
    original = raw.copy(deep=True)
    _inject_frame(study, raw)

    result = DataStep.from_config(cfg).execute(study, study.seed_manager.generator_for("data"))

    assert isinstance(result, PartitionResult)
    assert result.strategy_used == "random"
    assert result.frame["partition"].astype(str).to_dict() == EXPECTED_PARTITIONS
    assert result.sizes == EXPECTED_SIZES
    assert result.bad_rates == pytest.approx(EXPECTED_BAD_RATES)
    assert study.artifacts.get("data", "data_hash") == EXPECTED_DATA_HASH
    assert study.run_context.lineage is None
    assert_frame_equal(raw, original)

    frame = study.artifacts.get("data", "frame")
    splits = study.artifacts.get("data", "splits")
    labels = study.artifacts.get("data", "labels")
    special = study.artifacts.get("data", "special")
    data_card = study.artifacts.get("data", "data_card")

    assert isinstance(frame, pd.DataFrame)
    assert isinstance(splits, PartitionResult)
    assert isinstance(labels, LabeledFrame)
    assert isinstance(special, MaskedFrame)
    assert isinstance(data_card, DataCardSection)
    assert special.special_catalog == {"income": [-99999.0]}
    assert special.special_mask["income"].tolist() == [
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    assert labels.summary.class_counts == {
        "bueno": 8,
        "malo": 4,
        "indeterminado": 0,
        "excluido": 0,
    }
    assert labels.summary.bad_rate == pytest.approx(1 / 3)
    assert data_card.source == "<dataframe>"
    assert data_card.n_rows == 12
    assert data_card.n_features == 2
    assert data_card.target_col == "target"
    assert data_card.bad_rate == pytest.approx(1 / 3)
    assert data_card.class_counts == {"bueno": 8, "malo": 4, "indeterminado": 0, "excluido": 0}
    assert data_card.partition_sizes == EXPECTED_SIZES
    assert data_card.partition_bad_rates == pytest.approx(EXPECTED_BAD_RATES)
    assert data_card.model_dump(exclude={"bad_rate", "partition_bad_rates"}) == {
        "source": "<dataframe>",
        "n_rows": 12,
        "n_features": 2,
        "target_col": "target",
        "class_counts": {"bueno": 8, "malo": 4, "indeterminado": 0, "excluido": 0},
        "partition_sizes": EXPECTED_SIZES,
        "performance_window_months": None,
        "exclusions_by_reason": {},
        "data_hash": EXPECTED_DATA_HASH,
    }


def test_execute_sin_source_ni_dataframe_inyectado_levanta_configerror() -> None:
    """``source=None`` sin DataFrame inyectado falla antes de entrar a ``DataLoader``."""
    cfg = _data_config()
    study = _study(cfg)

    with pytest.raises(ConfigError, match="DataStep no tiene fuente"):
        DataStep.from_config(cfg).execute(study, study.seed_manager.generator_for("data"))


def test_execute_rechaza_artefacto_inyectado_no_dataframe() -> None:
    """La inyección en memoria exige un ``pandas.DataFrame`` explícito."""
    cfg = _data_config()
    study = _study(cfg)
    study.artifacts.set("data", INPUT_FRAME_KEY, object())

    with pytest.raises(ConfigError, match=r"pandas\.DataFrame"):
        DataStep.from_config(cfg).execute(study, study.seed_manager.generator_for("data"))


def test_source_de_config_delega_a_dataloader_y_normaliza_basename_sin_io() -> None:
    """Una ruta en config no requiere artefacto inyectado y se resume con basename."""
    cfg = _data_config(load=LoadingConfig(source="/tmp/cartera.csv"))
    step = DataStep.from_config(cfg)

    assert step._resolve_load_source(_study(cfg)) is None
    assert _source_label("/tmp/cartera.csv") == "cartera.csv"


def test_study_run_steps_data_end_to_end_y_determinismo() -> None:
    """End-to-end: ``Study.run(steps=['data'])`` encadena, llena lineage y es determinista."""
    cfg = _data_config()
    first = _study(cfg)
    second = _study(cfg)
    raw = _raw_frame()
    _inject_frame(first, raw)
    _inject_frame(second, raw)

    assert first.run(steps=["data"]) is first
    second.run(steps=["data"])

    assert first.run_context.status == "done"
    assert first.run_context.lineage is not None
    assert first.run_context.lineage.data_hash == EXPECTED_DATA_HASH
    assert first.artifacts.get("data", "data_hash") == second.artifacts.get("data", "data_hash")
    assert first.artifacts.get("data", "splits").sizes == EXPECTED_SIZES
