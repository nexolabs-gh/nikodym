"""Tests de ``CalibrationStep``: contrato CT-1, auditoría, leakage e import liviano."""

from __future__ import annotations

import math
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.calibration as calibration
import nikodym.calibration.step as step_module
import nikodym.core.study as study_module
from nikodym.binning.config import BinningConfig
from nikodym.calibration.config import CalibrationConfig
from nikodym.calibration.exceptions import CalibrationFitError
from nikodym.calibration.results import (
    CalibrationCardSection,
    CalibrationParameters,
    CalibrationResult,
)
from nikodym.calibration.step import CALIBRATION_ARTIFACTS, CalibrationStep
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
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
from nikodym.scorecard.config import ScorecardConfig
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.testing import assert_bitwise_reproducible

ROOT_SEED = 20_240_628
OFFSET_GOLDEN = -1.5255578438983735
PD_CALIBRATED_GOLDEN = [
    0.0235325270987112,
    0.05595860240909452,
    0.12724307535835755,
    0.20989509924598482,
    0.39518757479331523,
    0.5681831210945367,
    0.08902827497176245,
    0.30458515916156065,
]


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita importar OR-Tools dentro del proceso pytest."""
    del fake_binning_process


def _config(**kwargs: Any) -> CalibrationConfig:
    """Config base de calibration con filas mínimas bajas para fixtures sintéticos."""
    return CalibrationConfig(
        target_pd=0.23,
        anchor_source="business_input",
        min_fit_rows=1,
        **kwargs,
    )


def _coefficients() -> pd.DataFrame:
    """Coeficientes sintéticos del modelo logístico WoE consumidos como evidencia."""
    return pd.DataFrame(
        [
            {"feature": "intercept", "woe_column": "const", "beta": -0.4},
            {"feature": "score", "woe_column": "score__woe", "beta": -0.8},
            {"feature": "segment", "woe_column": "segment__woe", "beta": -1.2},
        ]
    )


def _raw_pd_frame(*, include_filtered: bool = True) -> pd.DataFrame:
    """PD cruda canónica con Dev/HO/OOT y una fila fuera de modelo opcional."""
    eta = [-2.2, -1.3, -0.4, 0.2, 1.1, 1.8, -0.8, 0.7]
    partitions = ["desarrollo"] * 6 + ["holdout", "oot"]
    targets = [0, 0, 1, 0, 1, 1, 0, 1]
    frame = pd.DataFrame(
        {
            "partition": partitions,
            "target": targets,
            "linear_predictor": eta,
            "pd_raw": [_sigmoid(value) for value in eta],
        },
        index=pd.Index([f"c{i}" for i in range(len(eta))], name="loan_id"),
    )
    if not include_filtered:
        return frame
    outside = pd.DataFrame(
        {
            "partition": ["fuera_de_modelo"],
            "target": [1],
            "linear_predictor": [2.4],
            "pd_raw": [_sigmoid(2.4)],
        },
        index=pd.Index(["c8"], name="loan_id"),
    )
    return pd.concat([frame, outside], axis=0)


def _study_with_artifacts(
    *,
    config: CalibrationConfig | None = None,
    estimator: object | None = None,
    final_features: tuple[str, ...] = ("score", "segment"),
    final_woe_columns: tuple[str, ...] = ("score__woe", "segment__woe"),
    coefficients: pd.DataFrame | None = None,
    raw_pd_frame: pd.DataFrame | None = None,
) -> Study:
    """Construye un ``Study`` con los cinco artefactos upstream de ``model``."""
    cfg = config or _config()
    study = Study(NikodymConfig(calibration=cfg))
    study.artifacts.set(
        "model",
        "estimator",
        estimator if estimator is not None else SimpleNamespace(fit_intercept=True),
    )
    study.artifacts.set("model", "final_features", final_features)
    study.artifacts.set("model", "final_woe_columns", final_woe_columns)
    study.artifacts.set(
        "model",
        "coefficients",
        _coefficients() if coefficients is None else coefficients,
    )
    study.artifacts.set(
        "model",
        "raw_pd_frame",
        _raw_pd_frame() if raw_pd_frame is None else raw_pd_frame,
    )
    return study


def _run_step_snapshot() -> dict[str, Any]:
    """Ejecuta el step aislado y devuelve una vista serializable determinista."""
    study = _study_with_artifacts()
    result = CalibrationStep.from_config(study.config.calibration).execute(
        study,
        np.random.default_rng(ROOT_SEED),
    )
    return {
        "frame": result.calibrated_pd_frame.to_dict("split"),
        "parameters": result.parameters.model_dump(mode="json"),
        "card": result.card.model_dump(mode="json"),
    }


def _bad_rule() -> Rule:
    """Regla canónica de default para el fixture de integración."""
    return Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),))


def _raw_frame_pipeline() -> pd.DataFrame:
    """Dataset crudo estable compartido con el smoke end-to-end de scoring."""
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


def _pipeline_study() -> Study:
    """Study canónico ``data``→``scorecard``→``calibration`` con config estable."""
    return Study(
        NikodymConfig(
            repro=ReproConfig(seed=ROOT_SEED),
            data=_data_config(),
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
                target_pd=0.31,
                anchor_source="business_input",
                min_fit_rows=1,
            ),
        )
    )


def _inject_frame(study: Study) -> None:
    """Inyecta el frame crudo bajo la clave pública de ``DataStep``."""
    study.artifacts.set("data", INPUT_FRAME_KEY, _raw_frame_pipeline())


def test_from_config_registro_reexport_y_contrato_step_exacto() -> None:
    """``CalibrationStep`` expone el contrato CT-1 exacto del SDD-10."""
    cfg = _config()
    step = CalibrationStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("calibration", "standard") is CalibrationStep
    assert calibration.__getattr__("CalibrationStep") is CalibrationStep
    assert step.config is cfg
    assert step.name == "calibration"
    assert step.requires == (
        ("model", "estimator"),
        ("model", "final_features"),
        ("model", "final_woe_columns"),
        ("model", "coefficients"),
        ("model", "raw_pd_frame"),
    )
    assert step.provides == tuple(("calibration", key) for key in CALIBRATION_ARTIFACTS)
    step.emit(
        AuditEvent(
            kind="decision",
            step="calibration",
            payload={"regla": "x"},
            ts=datetime.now(UTC),
        )
    )
    assert sink.events[-1].payload == {"regla": "x"}


def test_core_study_cablea_calibration_en_orden_por_defecto() -> None:
    """``Study`` resuelve ``calibration`` como dominio perezoso después de ``scorecard``."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order[order.index("scorecard") + 1] == "calibration"
    assert study_module._DOMAIN_MODULES["calibration"] == "nikodym.calibration"
    assert study_module._DOMAIN_CONFIG_CLASSES["calibration"] == (
        "nikodym.calibration.config",
        "CalibrationConfig",
    )

    study = Study(NikodymConfig(calibration=CalibrationConfig()))

    assert study._default_step_names() == ["calibration"]
    assert isinstance(study._resolve_step("calibration"), CalibrationStep)


def test_execute_publica_result_card_goldens_versiones_audit_y_no_consume_rng(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El step calibra Dev, filtra fuera de modelo, publica copias y audita decisiones."""
    versions = {
        "pandas": "2.3.3",
        "numpy": "2.4.6",
        "scipy": "1.16.2",
        "scikit-learn": "1.7.2",
    }
    monkeypatch.setattr(step_module.metadata, "version", lambda name: versions[name])
    study = _study_with_artifacts()
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = CalibrationStep.from_config(study.config.calibration)
    step._audit = sink

    result = step.execute(study, object())

    assert isinstance(result, CalibrationResult)
    assert isinstance(result.parameters, CalibrationParameters)
    assert isinstance(result.card, CalibrationCardSection)
    for key in CALIBRATION_ARTIFACTS:
        assert study.artifacts.has("calibration", key)
    assert result.parameters.offset == pytest.approx(OFFSET_GOLDEN, abs=1e-12)
    assert result.parameters.achieved_mean_pd_dev == pytest.approx(0.23, abs=1e-12)
    assert result.parameters.raw_mean_pd_dev == pytest.approx(0.4789118139952971)
    assert result.card.dependency_versions == {
        "numpy": "2.4.6",
        "pandas": "2.3.3",
        "scipy": "1.16.2",
    }

    calibrated = result.calibrated_pd_frame
    assert calibrated.index.tolist() == [f"c{i}" for i in range(8)]
    assert calibrated.columns.tolist() == [
        "partition",
        "target",
        "linear_predictor",
        "pd_raw",
        "linear_predictor_calibrated",
        "pd_calibrated",
        "calibration_method",
        "anchor_kind",
    ]
    assert calibrated["pd_calibrated"].tolist() == pytest.approx(PD_CALIBRATED_GOLDEN)
    assert math.copysign(1.0, result.parameters.offset) == -1.0

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert rules == [
        "calibration_fuera_de_modelo",
        "calibration_anchor",
        "calibration_method",
        "calibration_offset",
        "calibration_ranking",
    ]


def test_execute_no_muta_artefactos_upstream() -> None:
    """Las entradas de ``model`` se copian antes de ajustar y transformar."""
    estimator = SimpleNamespace(fit_intercept=True, marker=["intacto"])
    study = _study_with_artifacts(estimator=estimator)
    estimator_before = {"fit_intercept": estimator.fit_intercept, "marker": list(estimator.marker)}
    features_before = tuple(study.artifacts.get("model", "final_features"))
    woe_before = tuple(study.artifacts.get("model", "final_woe_columns"))
    coefficients_before = study.artifacts.get("model", "coefficients").copy(deep=True)
    raw_before = study.artifacts.get("model", "raw_pd_frame").copy(deep=True)

    CalibrationStep.from_config(study.config.calibration).execute(
        study,
        np.random.default_rng(1),
    )

    assert vars(estimator) == estimator_before
    assert study.artifacts.get("model", "final_features") == features_before
    assert study.artifacts.get("model", "final_woe_columns") == woe_before
    assert_frame_equal(study.artifacts.get("model", "coefficients"), coefficients_before)
    assert_frame_equal(study.artifacts.get("model", "raw_pd_frame"), raw_before)


def test_requires_faltante_falla_con_artifactnotfounderror() -> None:
    """Si falta un artefacto requerido, CT-1 levanta ``ArtifactNotFoundError`` claro."""
    study = _study_with_artifacts()
    study.artifacts._store.pop(("model", "raw_pd_frame"))

    with pytest.raises(ArtifactNotFoundError, match=r"\('model', 'raw_pd_frame'\)"):
        study.run_step("calibration")


def test_anti_leakage_target_holdout_oot_no_mueve_parametros_ni_pd() -> None:
    """Cambiar target de HO/OOT no altera offset, parámetros ni PD calibrada."""
    base = _study_with_artifacts(raw_pd_frame=_raw_pd_frame(include_filtered=False))
    altered_frame = _raw_pd_frame(include_filtered=False)
    non_dev = altered_frame["partition"].ne("desarrollo")
    altered_frame.loc[non_dev, "target"] = 1 - altered_frame.loc[non_dev, "target"]
    altered = _study_with_artifacts(raw_pd_frame=altered_frame)

    base_result = CalibrationStep.from_config(base.config.calibration).execute(
        base,
        np.random.default_rng(1),
    )
    altered_result = CalibrationStep.from_config(altered.config.calibration).execute(
        altered,
        np.random.default_rng(2),
    )

    assert altered_result.parameters == base_result.parameters
    assert altered_result.card.model_copy(update={"dependency_versions": {}}) == (
        base_result.card.model_copy(update={"dependency_versions": {}})
    )
    assert_frame_equal(
        altered_result.calibrated_pd_frame[["linear_predictor_calibrated", "pd_calibrated"]],
        base_result.calibrated_pd_frame[["linear_predictor_calibrated", "pd_calibrated"]],
    )


def test_platt_e_isotonic_emiten_eventos_especificos_y_versiones_condicionales() -> None:
    """Los métodos opt-in publican reglas ``calibration_platt``/``calibration_isotonic``."""
    platt_sink = InMemoryAuditSink()
    platt_cfg = CalibrationConfig(
        method="platt_scaling",
        anchor_source="development_observed",
        min_fit_rows=1,
        max_iter=500,
    )
    platt_study = _study_with_artifacts(
        config=platt_cfg,
        raw_pd_frame=_raw_pd_frame(include_filtered=False),
    )
    platt_study.set_audit_sink(platt_sink)
    platt_step = CalibrationStep.from_config(platt_cfg)
    platt_step._audit = platt_sink
    platt_result = platt_step.execute(platt_study, np.random.default_rng(1))

    platt_events = [
        event.payload
        for event in platt_sink.events
        if event.payload.get("regla") == "calibration_platt"
    ]
    assert len(platt_events) == 1
    assert platt_events[0]["valor"]["post_offset_policy"].startswith("PDCalibrator B10.3")
    assert "scikit-learn" in platt_result.card.dependency_versions

    isotonic_sink = InMemoryAuditSink()
    isotonic_cfg = CalibrationConfig(
        method="isotonic",
        anchor_source="development_observed",
        min_fit_rows=1,
    )
    isotonic_study = _study_with_artifacts(
        config=isotonic_cfg,
        raw_pd_frame=_raw_pd_frame(include_filtered=False),
    )
    isotonic_study.set_audit_sink(isotonic_sink)
    isotonic_step = CalibrationStep.from_config(isotonic_cfg)
    isotonic_step._audit = isotonic_sink
    isotonic_result = isotonic_step.execute(isotonic_study, np.random.default_rng(1))

    rules = [event.payload["regla"] for event in isotonic_sink.events if event.kind == "decision"]
    assert "calibration_isotonic" in rules
    assert isotonic_result.card.ties_created > 0
    assert "scikit-learn" in isotonic_result.card.dependency_versions


def test_validadores_y_fallback_config_cubren_ramas_defensivas() -> None:
    """Los helpers ``_as_*`` y validadores rechazan contratos inválidos en español."""
    pd_mod = step_module._import_pandas()
    fallback = _config()

    with pytest.raises(CalibrationFitError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd_mod, "model.raw_pd_frame")
    with pytest.raises(CalibrationFitError, match=r"tuple\[str"):
        step_module._as_string_tuple(object(), "model", "final_features")
    with pytest.raises(CalibrationFitError, match="fit_intercept"):
        step_module._as_model_estimator(object())
    assert (
        step_module._calibration_config_from_study(
            SimpleNamespace(config=SimpleNamespace(calibration={"target_pd": 0.19})),
            fallback=fallback,
        ).target_pd
        == 0.19
    )
    assert (
        step_module._calibration_config_from_study(Study(NikodymConfig()), fallback=fallback)
        is fallback
    )

    with pytest.raises(CalibrationFitError, match="mismo largo"):
        step_module._validate_model_metadata(("score",), ("score__woe", "segment__woe"))
    with pytest.raises(CalibrationFitError, match="al menos una"):
        step_module._validate_model_metadata((), ())
    with pytest.raises(CalibrationFitError, match="duplicados"):
        step_module._validate_model_metadata(("score", "score"), ("a", "b"))
    with pytest.raises(CalibrationFitError, match="duplicados"):
        step_module._validate_model_metadata(("score", "segment"), ("a", "a"))

    duplicated_columns = pd.DataFrame([[1, 2]], columns=["x", "x"])
    with pytest.raises(CalibrationFitError, match="duplicadas"):
        step_module._validate_coefficients(
            duplicated_columns,
            final_features=("score",),
            final_woe_columns=("score__woe",),
        )
    with pytest.raises(CalibrationFitError, match="columnas requeridas"):
        step_module._validate_coefficients(
            pd.DataFrame({"feature": ["score"]}),
            final_features=("score",),
            final_woe_columns=("score__woe",),
        )
    with pytest.raises(CalibrationFitError, match="sin coeficiente"):
        step_module._validate_coefficients(
            _coefficients().loc[lambda df: df["feature"].ne("segment")],
            final_features=("score", "segment"),
            final_woe_columns=("score__woe", "segment__woe"),
        )
    with pytest.raises(CalibrationFitError, match="ambiguo"):
        step_module._validate_coefficients(
            pd.concat(
                [
                    _coefficients(),
                    pd.DataFrame([{"feature": "score", "woe_column": "score__woe", "beta": -0.7}]),
                ],
                ignore_index=True,
            ),
            final_features=("score", "segment"),
            final_woe_columns=("score__woe", "segment__woe"),
        )
    mismatch = _coefficients()
    mismatch.loc[mismatch["feature"].eq("score"), "woe_column"] = "otra"
    with pytest.raises(CalibrationFitError, match="mapping final"):
        step_module._validate_coefficients(
            mismatch,
            final_features=("score", "segment"),
            final_woe_columns=("score__woe", "segment__woe"),
        )
    non_numeric = _coefficients().astype({"beta": "object"})
    non_numeric.loc[1, "beta"] = "x"
    with pytest.raises(CalibrationFitError, match="no es numérico"):
        step_module._validate_coefficients(
            non_numeric,
            final_features=("score", "segment"),
            final_woe_columns=("score__woe", "segment__woe"),
        )
    non_finite = _coefficients()
    non_finite.loc[1, "beta"] = math.inf
    with pytest.raises(CalibrationFitError, match="no es finito"):
        step_module._validate_coefficients(
            non_finite,
            final_features=("score", "segment"),
            final_woe_columns=("score__woe", "segment__woe"),
        )
    assert math.copysign(1.0, step_module._finite_float(-0.0, "zero")) == 1.0

    raw = _raw_pd_frame(include_filtered=False)
    duplicate_index = pd.concat([raw, raw.iloc[[0]]])
    with pytest.raises(CalibrationFitError, match="índice duplicado"):
        step_module._validate_raw_pd_frame(duplicate_index, _config())
    with pytest.raises(CalibrationFitError, match="columnas requeridas"):
        step_module._validate_raw_pd_frame(raw.drop(columns=["pd_raw"]), _config())
    with pytest.raises(CalibrationFitError, match="columnas de salida"):
        step_module._validate_raw_pd_frame(raw.assign(pd_calibrated=0.1), _config())

    step = CalibrationStep.from_config(_config())
    filtered = step._filter_modelable_rows(raw, _config())
    assert_frame_equal(filtered, raw)
    with pytest.raises(CalibrationFitError, match="fila modelable"):
        step._filter_modelable_rows(
            raw.assign(partition="fuera_de_modelo"),
            _config(),
        )


def test_dependency_versions_import_pandas_y_reproducibilidad_bitwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Versiones usan ``metadata`` y el step aislado es reproducible bit a bit."""
    real_import = step_module.importlib.import_module

    def fake_version(name: str) -> str:
        if name == "numpy":
            raise step_module.metadata.PackageNotFoundError(name)
        return f"v-{name}"

    monkeypatch.setattr(step_module.metadata, "version", fake_version)
    assert step_module._dependency_versions("intercept_offset") == {
        "pandas": "v-pandas",
        "numpy": "no_instalado",
        "scipy": "v-scipy",
    }
    assert step_module._dependency_versions("platt_scaling")["scikit-learn"] == ("v-scikit-learn")

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="CalibrationStep requiere pandas"):
        step_module._import_pandas()

    monkeypatch.setattr(step_module.importlib, "import_module", real_import)
    assert_bitwise_reproducible(_run_step_snapshot)


def test_study_run_data_binning_selection_model_scorecard_calibration_end_to_end() -> None:
    """``Study.run`` ejecuta calibration real y publica sus cuatro artefactos con goldens."""
    study = _pipeline_study()
    _inject_frame(study)

    assert study.run(["data", "binning", "selection", "model", "scorecard", "calibration"]) is study

    for key in CALIBRATION_ARTIFACTS:
        assert study.artifacts.has("calibration", key)
    result = study.artifacts.get("calibration", "result")
    card = study.artifacts.get("calibration", "card")
    parameters = study.artifacts.get("calibration", "parameters")
    calibrated = study.artifacts.get("calibration", "calibrated_pd_frame")
    raw_pd_frame = study.artifacts.get("model", "raw_pd_frame")

    assert isinstance(result, CalibrationResult)
    assert isinstance(card, CalibrationCardSection)
    assert isinstance(parameters, CalibrationParameters)
    assert calibrated.index.equals(raw_pd_frame.index)
    assert parameters.target_pd == pytest.approx(0.31)
    expected_offset = _bisect_delta(
        raw_pd_frame.loc[
            raw_pd_frame["partition"].eq("desarrollo"),
            "linear_predictor",
        ].tolist(),
        0.31,
    )
    assert parameters.offset == pytest.approx(expected_offset, abs=1e-12)
    dev_mean = calibrated.loc[calibrated["partition"].eq("desarrollo"), "pd_calibrated"].mean()
    assert dev_mean == pytest.approx(0.31, abs=1e-12)
    assert card.ranking_preserved is True
    assert card.ties_created == 0


def test_import_calibration_step_liviano_no_carga_tabulares_ni_scoring() -> None:
    """``import nikodym.calibration`` registra el step sin arrastrar pandas/scipy/sklearn."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym.calibration
        from nikodym.core.registry import REGISTRY

        assert REGISTRY.resolve("calibration", "standard").__name__ == "CalibrationStep"
        blocked = [name for name in ("pandas", "scipy", "sklearn") if name in sys.modules]
        assert blocked == [], blocked
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def _sigmoid(value: float) -> float:
    """Calcula sigmoid escalar estable para construir fixtures no tautológicos."""
    return 1.0 / (1.0 + math.exp(-value))


def _logit(probability: float) -> float:
    """Calcula logit escalar para la bisección independiente de goldens."""
    return math.log(probability) - math.log1p(-probability)


def _bisect_delta(eta: list[float], target_pd: float) -> float:
    """Resuelve el offset por bisección independiente del código productivo."""
    lower = _logit(target_pd) - max(eta) - 8.0
    upper = _logit(target_pd) - min(eta) + 8.0
    for _ in range(200):
        mid = (lower + upper) / 2.0
        mean = sum(_sigmoid(value + mid) for value in eta) / len(eta)
        if mean < target_pd:
            lower = mid
        else:
            upper = mid
    return (lower + upper) / 2.0
