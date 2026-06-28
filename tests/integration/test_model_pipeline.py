"""Integración ``data`` → ``binning`` → ``selection`` → ``model`` vía ``Study.run``."""

from __future__ import annotations

from typing import Any

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
from nikodym.model.config import IvContributionConfig, ModelConfig, SignPolicyConfig, StepwiseConfig
from nikodym.model.exceptions import ModelFitError
from nikodym.model.step import MODEL_ARTIFACTS
from nikodym.scorecard.config import ScorecardConfig
from nikodym.scorecard.results import ScorecardCardSection, ScorecardResult
from nikodym.scorecard.step import SCORECARD_ARTIFACTS
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.testing import assert_bitwise_reproducible

ROOT_SEED = 20_240_628


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita importar OR-Tools dentro del proceso pytest."""
    del fake_binning_process


def _bad_rule() -> Rule:
    """Regla canónica de default para el fixture de integración."""
    return Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),))


def _raw_frame() -> pd.DataFrame:
    """Dataset crudo estable con Desarrollo/Holdout por hash y OOT por cohorte."""
    index = pd.Index([f"op-{position:03d}" for position in range(30)], name="loan_id")
    return pd.DataFrame(
        {
            "score": [
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
            ],
            "segment": [
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
            ],
            "bad_flag": [
                1,
                0,
                1,
                0,
                0,
                1,
                0,
                1,
                0,
                1,
                0,
                0,
                1,
                0,
                1,
                0,
                0,
                1,
                0,
                1,
                1,
                0,
                1,
                0,
                0,
                1,
                0,
                1,
                0,
                1,
            ],
            "cohort": ["dev"] * 24 + ["oot"] * 6,
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
                holdout_fraction=0.20,
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


def _selection_config() -> SelectionConfig:
    """Config de selection estable para aislar el contrato de model."""
    return SelectionConfig(
        min_iv=0.0,
        correlation=CorrelationSelectionConfig(enabled=False),
        vif=VifSelectionConfig(enabled=False),
        stability=StabilitySelectionConfig(enabled=False),
    )


def _model_config(
    *,
    force_exclude: tuple[str, ...] = (),
    fail_if_no_features: bool = True,
) -> ModelConfig:
    """Config de model que evita cruces con scorecard/calibración."""
    return ModelConfig(
        stepwise=StepwiseConfig(direction="none"),
        sign_policy=SignPolicyConfig(action="flag", fail_on_forced_inverted=False),
        iv_contribution=IvContributionConfig(action="flag"),
        force_exclude=force_exclude,
        fail_if_no_features=fail_if_no_features,
    )


def _study(*, model: ModelConfig | None = None) -> Study:
    """Study con secciones ``data``, ``binning``, ``selection`` y ``model`` activas."""
    return Study(
        NikodymConfig(
            repro=ReproConfig(seed=ROOT_SEED),
            data=_data_config(),
            binning=_binning_config(),
            selection=_selection_config(),
            model=model or _model_config(),
        )
    )


def _study_with_scorecard() -> Study:
    """Study con el pipeline de scorecard completo activado."""
    return Study(
        NikodymConfig(
            repro=ReproConfig(seed=ROOT_SEED),
            data=_data_config(),
            binning=_binning_config(),
            selection=_selection_config(),
            model=_model_config(),
            scorecard=ScorecardConfig(rounding_method="none"),
        )
    )


def _inject_frame(study: Study, frame: pd.DataFrame | None = None) -> None:
    """Inyecta el frame crudo bajo la clave pública de ``DataStep``."""
    study.artifacts.set("data", INPUT_FRAME_KEY, _raw_frame() if frame is None else frame)


def _model_snapshot(study: Study) -> dict[str, Any]:
    """Devuelve una vista serializable de artefactos de model para reproducibilidad."""
    result = study.artifacts.get("model", "result")
    return {
        "final_features": result.final_features,
        "final_woe_columns": result.final_woe_columns,
        "coefficients": result.coefficients.to_dict("split"),
        "stepwise_trace": [decision.model_dump(mode="json") for decision in result.stepwise_trace],
        "fit_statistics": result.fit_statistics.model_dump(mode="json"),
        "raw_pd_frame": result.raw_pd_frame.to_dict("split"),
        "model_card": result.model_card.model_dump(mode="json"),
    }


def _run_pipeline_snapshot() -> dict[str, Any]:
    """Ejecuta la corrida completa y devuelve artefactos deterministas de model."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data", "binning", "selection", "model"])
    return _model_snapshot(study)


def test_study_run_data_binning_selection_model_puebla_los_nueve_artefactos() -> None:
    """``Study.run`` publica todos los artefactos namespaced de ``model``."""
    study = _study()
    _inject_frame(study)

    assert study.run(steps=["data", "binning", "selection", "model"]) is study

    assert study.run_context.status == "done"
    for key in MODEL_ARTIFACTS:
        assert study.artifacts.has("model", key)
    result = study.artifacts.get("model", "result")
    raw_pd_frame = study.artifacts.get("model", "raw_pd_frame")
    selected_woe_frame = study.artifacts.get("selection", "selected_woe_frame")
    assert result.final_features == ("score", "segment")
    assert result.final_woe_columns == ("score__woe", "segment__woe")
    assert raw_pd_frame.index.tolist() == selected_woe_frame.index.tolist()
    assert raw_pd_frame.columns.tolist() == ["partition", "target", "linear_predictor", "pd_raw"]


def test_model_requires_faltante_falla_antes_de_execute() -> None:
    """Si falta un artefacto requerido, CT-1 levanta ``ArtifactNotFoundError`` claro."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data", "binning", "selection"])
    study.artifacts._store.pop(("selection", "selected_woe_frame"))

    with pytest.raises(ArtifactNotFoundError, match=r"\('selection', 'selected_woe_frame'\)"):
        study.run_step("model")


def test_model_no_muta_data_binning_ni_selection_en_corrida_cross_domain() -> None:
    """Correr ``model`` deja intactos los artefactos upstream publicados."""
    study = _study()
    _inject_frame(study)
    study.run(steps=["data", "binning", "selection"])
    selected_before = study.artifacts.get("selection", "selected_woe_frame").copy(deep=True)
    summary_before = study.artifacts.get("binning", "summary").copy(deep=True)
    labels_before = study.artifacts.get("data", "labels").frame.copy(deep=True)
    splits_before = study.artifacts.get("data", "splits").frame.copy(deep=True)

    study.run(steps=["model"])

    assert_frame_equal(study.artifacts.get("selection", "selected_woe_frame"), selected_before)
    assert_frame_equal(study.artifacts.get("binning", "summary"), summary_before)
    assert_frame_equal(study.artifacts.get("data", "labels").frame, labels_before)
    assert_frame_equal(study.artifacts.get("data", "splits").frame, splits_before)


def test_model_pipeline_emite_decisiones_auditables_esperadas() -> None:
    """El step registra convergencia del ajuste en el sink inyectado."""
    study = _study()
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    _inject_frame(study)

    study.run(steps=["data", "binning", "selection", "model"])

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert "statsmodels_convergence" in rules


def test_model_anti_leakage_holdout_oot_no_mueve_coeficientes() -> None:
    """Cambiar HO/OOT después de selection no altera fit, coeficientes ni trazas."""
    base = _study()
    _inject_frame(base)
    base.run(steps=["data", "binning", "selection"])

    altered = _study()
    _inject_frame(altered)
    altered.run(steps=["data", "binning", "selection"])
    frame = altered.artifacts.get("selection", "selected_woe_frame").copy(deep=True)
    non_dev = frame["partition"].ne("desarrollo")
    frame.loc[non_dev, ["score__woe", "segment__woe"]] = (
        frame.loc[
            non_dev,
            ["score__woe", "segment__woe"],
        ]
        * -50.0
    )
    frame.loc[non_dev, "target"] = 1 - frame.loc[non_dev, "target"]
    altered.artifacts._store[("selection", "selected_woe_frame")] = frame

    base.run(steps=["model"])
    altered.run(steps=["model"])

    base_result = base.artifacts.get("model", "result")
    altered_result = altered.artifacts.get("model", "result")
    assert altered_result.final_features == base_result.final_features
    assert altered_result.final_woe_columns == base_result.final_woe_columns
    assert_frame_equal(altered_result.coefficients, base_result.coefficients)
    assert altered_result.stepwise_trace == base_result.stepwise_trace
    assert altered_result.fit_statistics == base_result.fit_statistics


def test_pipeline_model_es_bitwise_reproducible_sin_muestreo() -> None:
    """La corrida completa sin muestreo es reproducible bit a bit."""
    assert_bitwise_reproducible(_run_pipeline_snapshot)


def test_fail_if_no_features_true_con_todo_excluido_falla_en_pipeline_real() -> None:
    """Excluir todas las candidatas aborta con ``ModelFitError`` cuando el config lo exige."""
    study = _study(model=_model_config(force_exclude=("score", "segment")))
    _inject_frame(study)

    with pytest.raises(ModelFitError, match="mínimo"):
        study.run(steps=["data", "binning", "selection", "model"])


def test_study_run_data_binning_selection_model_scorecard_end_to_end_goldens() -> None:
    """``Study.run`` ejecuta scorecard y publica sus cuatro artefactos con goldens estables."""
    study = _study_with_scorecard()
    _inject_frame(study)

    assert study.run(steps=["data", "binning", "selection", "model", "scorecard"]) is study

    for key in SCORECARD_ARTIFACTS:
        assert study.artifacts.has("scorecard", key)
    result = study.artifacts.get("scorecard", "result")
    card = study.artifacts.get("scorecard", "card")
    scorecard = study.artifacts.get("scorecard", "scorecard")
    score = study.artifacts.get("scorecard", "score")
    raw_pd_frame = study.artifacts.get("model", "raw_pd_frame")

    assert isinstance(result, ScorecardResult)
    assert isinstance(card, ScorecardCardSection)
    assert result.factor == pytest.approx(28.85390081777927)
    assert result.offset == pytest.approx(487.1228762045055)
    assert result.points_columns == ("score__points", "segment__points")
    assert card.n_variables == 2
    assert score.index.equals(raw_pd_frame.index)
    assert score.columns.tolist() == [
        "partition",
        "target",
        "linear_predictor",
        "pd_raw",
        "score__points",
        "segment__points",
        "score",
    ]

    assert scorecard["feature"].tolist() == [
        "score",
        "score",
        "score",
        "score",
        "segment",
        "segment",
        "segment",
        "segment",
        "segment",
    ]
    assert scorecard["bin_label"].tolist() == [
        "(-inf, 1.50)",
        "[1.50, inf)",
        "Special",
        "Missing",
        "[A]",
        "[B]",
        "[Z]",
        "Special",
        "Missing",
    ]
    assert scorecard["raw_points"].tolist()[:6] == pytest.approx(
        [
            243.35076202549377,
            254.55593289723237,
            249.42241946163548,
            249.42241946163548,
            237.3249636184908,
            264.6634107745877,
        ]
    )
    assert score.loc["op-000", "score"] == pytest.approx(480.67572564398454)
    assert score.loc["op-005", "score"] == pytest.approx(519.2193436718201)
    assert score.loc["op-029", "score"] == pytest.approx(491.8808965167223)
