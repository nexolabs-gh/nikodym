"""Integración ``data`` → ``binning`` → ``selection`` vía ``Study.run`` (SDD-07 §11)."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from nikodym.binning.config import BinningConfig
from nikodym.core.audit import InMemoryAuditSink
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
from nikodym.data.step import INPUT_FRAME_KEY
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.selection.exceptions import SelectionFitError
from nikodym.selection.step import SELECTION_ARTIFACTS
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


def _selection_config(*, min_iv: float = 0.0) -> SelectionConfig:
    """Config de selection estable para aislar el contrato del pipeline."""
    return SelectionConfig(
        min_iv=min_iv,
        correlation=CorrelationSelectionConfig(enabled=False),
        vif=VifSelectionConfig(enabled=False),
        stability=StabilitySelectionConfig(enabled=True),
    )


def _study(*, selection: SelectionConfig | None = None) -> Study:
    """Study con secciones ``data``, ``binning`` y ``selection`` activas."""
    return Study(
        NikodymConfig(
            repro=ReproConfig(seed=ROOT_SEED),
            data=_data_config(),
            binning=_binning_config(),
            selection=selection or _selection_config(),
        )
    )


def _inject_frame(study: Study) -> None:
    """Inyecta el frame crudo bajo la clave pública de ``DataStep``."""
    study.artifacts.set("data", INPUT_FRAME_KEY, _raw_frame())


def _run_pipeline_artifacts() -> tuple[object, ...]:
    """Ejecuta la corrida completa y devuelve artefactos deterministas de selection."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data", "binning", "selection"])
    return tuple(study.artifacts.get("selection", key) for key in SELECTION_ARTIFACTS)


def test_study_run_data_binning_selection_puebla_los_nueve_artefactos() -> None:
    """``Study.run`` publica todos los artefactos namespaced de ``selection``."""
    study = _study()
    _inject_frame(study)

    assert study.run(steps=["data", "binning", "selection"]) is study

    assert study.run_context.status == "done"
    for key in SELECTION_ARTIFACTS:
        assert study.artifacts.has("selection", key)
    result = study.artifacts.get("selection", "result")
    selected_woe_frame = study.artifacts.get("selection", "selected_woe_frame")
    assert result.selected_features == ("score", "segment")
    assert result.selected_woe_columns == ("score__woe", "segment__woe")
    assert selected_woe_frame.index.equals(study.artifacts.get("binning", "woe_frame").index)
    assert selected_woe_frame.columns.tolist() == [
        "target",
        "label_status",
        "partition",
        "ttd",
        "score__woe",
        "segment__woe",
    ]


def test_selection_requires_faltante_falla_antes_de_execute() -> None:
    """Si falta un artefacto requerido, CT-1 levanta ``ArtifactNotFoundError`` claro."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data", "binning"])
    study.artifacts._store.pop(("binning", "summary"))

    with pytest.raises(ArtifactNotFoundError, match=r"\('binning', 'summary'\)"):
        study.run_step("selection")


def test_selection_no_muta_data_ni_binning_en_corrida_cross_domain() -> None:
    """Correr ``selection`` deja intactos los artefactos publicados por ``data`` y ``binning``."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data", "binning"])
    data_before = study.artifacts.get("data", "frame").copy(deep=True)
    woe_before = study.artifacts.get("binning", "woe_frame").copy(deep=True)
    summary_before = study.artifacts.get("binning", "summary").copy(deep=True)

    study.run(steps=["selection"])

    assert_frame_equal(study.artifacts.get("data", "frame"), data_before)
    assert_frame_equal(study.artifacts.get("binning", "woe_frame"), woe_before)
    assert_frame_equal(study.artifacts.get("binning", "summary"), summary_before)


def test_selection_pipeline_emite_decisiones_auditables_esperadas() -> None:
    """El step registra flags de IV alto y CSI inestable en el sink inyectado."""
    study = _study()
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    _inject_frame(study)

    study.run(steps=["data", "binning", "selection"])

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert "high_iv" in rules
    assert "stability_csi" in rules


def test_pipeline_aplica_overrides_con_alias_woe_y_conserva_config() -> None:
    """Los aliases WoE llegan al selector como overrides raw equivalentes."""
    selection = SelectionConfig(
        min_iv=999.0,
        force_include=("segment__woe",),
        force_exclude=("score__woe",),
        correlation=CorrelationSelectionConfig(enabled=False),
        vif=VifSelectionConfig(enabled=False),
        stability=StabilitySelectionConfig(enabled=False),
    )
    study = _study(selection=selection)
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    _inject_frame(study)

    study.run(steps=["data", "binning", "selection"])
    table = study.artifacts.get("selection", "selection_table").set_index("feature")

    assert study.artifacts.get("selection", "selected_features") == ("segment",)
    assert table.loc["segment", "reason"] == "business_include"
    assert table.loc["segment", "forced"] == "include"
    assert table.loc["score", "reason"] == "business_exclude"
    assert table.loc["score", "forced"] == "exclude"
    rules = {event.payload["regla"] for event in sink.events if event.kind == "decision"}
    assert {"business_include", "business_exclude"} <= rules
    assert study.config.selection.force_include == ("segment__woe",)
    assert study.config.selection.force_exclude == ("score__woe",)


def test_pipeline_data_binning_selection_es_bitwise_reproducible_sin_muestreo() -> None:
    """La corrida completa sin muestreo es reproducible bit a bit."""
    assert_bitwise_reproducible(_run_pipeline_artifacts)


def test_fail_if_no_features_true_falla_en_pipeline_real() -> None:
    """Un umbral IV imposible aborta con ``SelectionFitError`` antes de publicar selección vacía."""
    study = _study(selection=_selection_config(min_iv=999.0))
    _inject_frame(study)

    with pytest.raises(SelectionFitError, match="No quedó ninguna variable"):
        study.run(steps=["data", "binning", "selection"])
