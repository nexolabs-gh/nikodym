"""Tests de ``PerformanceStep``: contrato CT-1, auditoría, no-mutación e import liviano."""

from __future__ import annotations

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

import nikodym.core.study as study_module
import nikodym.performance as performance_pkg
import nikodym.performance.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.performance.config import PerformanceConfig
from nikodym.performance.exceptions import PerformanceDataError
from nikodym.performance.results import PerformanceCardSection, PerformanceResult
from nikodym.performance.step import PERFORMANCE_ARTIFACTS, PerformanceStep


def _config(**kwargs: Any) -> PerformanceConfig:
    """Config base de performance con mínimos bajos para fixtures sintéticos."""
    return PerformanceConfig(
        partitions=("desarrollo",),
        n_deciles=2,
        min_rows_per_partition=1,
        **kwargs,
    )


def _score_frame(*, score: list[float] | None = None) -> pd.DataFrame:
    """Artefacto ``scorecard.score`` con score operacional y columnas estructurales extra."""
    scores = score if score is not None else [100.0, 200.0, 300.0, 400.0]
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "desarrollo", "desarrollo", "desarrollo"],
            "target": [1, 0, 1, 0],
            "pd_raw": [0.88, 0.77, 0.66, 0.11],
            "score": scores,
        },
        index=pd.Index(["c0", "c1", "c2", "c3"], name="loan_id"),
    )


def _calibrated_pd_frame(*, pd_values: list[float] | None = None) -> pd.DataFrame:
    """Artefacto ``calibration.calibrated_pd_frame`` canónico del evaluator."""
    calibrated = pd_values if pd_values is not None else [0.90, 0.80, 0.70, 0.10]
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "desarrollo", "desarrollo", "desarrollo"],
            "target": [1, 0, 1, 0],
            "linear_predictor": [2.2, 1.3, 0.4, -2.2],
            "pd_raw": [0.88, 0.77, 0.66, 0.11],
            "linear_predictor_calibrated": [2.4, 1.4, 0.8, -2.4],
            "pd_calibrated": calibrated,
            "calibration_method": ["intercept_offset"] * 4,
            "anchor_kind": ["business_input"] * 4,
        },
        index=pd.Index(["c0", "c1", "c2", "c3"], name="loan_id"),
    )


def _study_with_artifacts(
    *,
    config: PerformanceConfig | None = None,
    score: pd.DataFrame | None = None,
    calibrated_pd_frame: pd.DataFrame | None = None,
) -> Study:
    """Construye un ``Study`` con los dos artefactos upstream mínimos de ``performance``."""
    cfg = config or _config()
    study = Study(NikodymConfig(performance=cfg))
    study.artifacts.set("scorecard", "score", _score_frame() if score is None else score)
    study.artifacts.set(
        "calibration",
        "calibrated_pd_frame",
        _calibrated_pd_frame() if calibrated_pd_frame is None else calibrated_pd_frame,
    )
    return study


def test_from_config_registro_reexport_y_contrato_step_exacto() -> None:
    """``PerformanceStep`` expone el contrato CT-1 exacto de B11.4."""
    cfg = _config()
    step = PerformanceStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("performance", "standard") is PerformanceStep
    assert performance_pkg.__getattr__("PerformanceStep") is PerformanceStep
    assert step.config is cfg
    assert step.name == "performance"
    assert step.requires == (
        ("scorecard", "score"),
        ("calibration", "calibrated_pd_frame"),
    )
    assert step.provides == tuple(("performance", key) for key in PERFORMANCE_ARTIFACTS)
    step.emit(
        AuditEvent(
            kind="decision",
            step="performance",
            payload={"regla": "x"},
            ts=datetime.now(UTC),
        )
    )
    assert sink.events[-1].payload == {"regla": "x"}


def test_core_study_cablea_performance_en_orden_por_defecto() -> None:
    """``Study`` resuelve ``performance`` después de ``survival`` en el orden por defecto."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order.index("calibration") < order.index("survival") < order.index("performance")
    assert study_module._DOMAIN_MODULES["performance"] == "nikodym.performance"
    assert study_module._DOMAIN_CONFIG_CLASSES["performance"] == (
        "nikodym.performance.config",
        "PerformanceConfig",
    )

    study = Study(NikodymConfig(performance=PerformanceConfig()))

    assert study._default_step_names() == ["performance"]
    assert isinstance(study._resolve_step("performance"), PerformanceStep)


def test_execute_publica_result_card_goldens_audit_y_no_consume_rng() -> None:
    """El step evalúa métricas, publica copias y propaga auditoría del evaluator."""
    cfg = _config(optional_thresholds={"auc_min": 0.80, "gini_min": 0.60, "ks_min": 0.40})
    study = _study_with_artifacts(config=cfg)
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = PerformanceStep.from_config(study.config.performance)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(20_240_628))

    assert isinstance(result, PerformanceResult)
    assert isinstance(result.card, PerformanceCardSection)
    for key in PERFORMANCE_ARTIFACTS:
        assert study.artifacts.has("performance", key)

    metric = result.discriminant_records[0]
    assert metric.partition == "desarrollo"
    assert metric.auc == pytest.approx(0.75)
    assert metric.gini == pytest.approx(0.50)
    assert metric.ks == pytest.approx(0.50)
    assert metric.ks_cutoff_risk_score == pytest.approx(0.90)
    assert metric.ks_cutoff_score is None
    assert metric.tpr_at_ks == pytest.approx(0.50)
    assert metric.fpr_at_ks == pytest.approx(0.0)
    assert metric.status == "threshold_flag"

    table = result.performance_table
    assert table["decile"].tolist() == [1, 2]
    assert table["n_bad"].tolist() == [1, 1]
    assert table["n_good"].tolist() == [1, 1]
    assert table["mean_pd"].tolist() == pytest.approx([0.85, 0.40])
    assert table["mean_score"].tolist() == pytest.approx([150.0, 350.0])
    assert result.card.metric_sections["discrimination"] == {
        "effective_deciles_by_partition": {"desarrollo": 2},
        "not_evaluable_reasons_by_partition": {},
        "threshold_flags_by_partition": {"desarrollo": ["auc", "gini"]},
    }
    assert_frame_equal(study.artifacts.get("performance", "performance_table"), table)
    assert_frame_equal(
        study.artifacts.get("performance", "discriminant_metrics"),
        result.discriminant_metrics,
    )
    assert study.artifacts.get("performance", "card") == result.card
    artifact_result = study.artifacts.get("performance", "result")
    assert isinstance(artifact_result, PerformanceResult)
    assert_frame_equal(artifact_result.performance_table, result.performance_table)
    assert_frame_equal(artifact_result.discriminant_metrics, result.discriminant_metrics)
    assert artifact_result.performance_records == result.performance_records
    assert artifact_result.discriminant_records == result.discriminant_records
    assert artifact_result.card == result.card

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert rules == ["performance_auc_min", "performance_gini_min"]


def test_execute_no_muta_artefactos_upstream() -> None:
    """Las entradas de ``scorecard`` y ``calibration`` se copian antes de evaluar."""
    study = _study_with_artifacts()
    score_before = study.artifacts.get("scorecard", "score").copy(deep=True)
    calibrated_before = study.artifacts.get("calibration", "calibrated_pd_frame").copy(deep=True)

    PerformanceStep.from_config(study.config.performance).execute(
        study,
        np.random.default_rng(1),
    )

    assert_frame_equal(study.artifacts.get("scorecard", "score"), score_before)
    assert_frame_equal(
        study.artifacts.get("calibration", "calibrated_pd_frame"),
        calibrated_before,
    )


def test_requires_faltante_falla_con_artifactnotfounderror() -> None:
    """Si falta un artefacto requerido, CT-1 levanta ``ArtifactNotFoundError`` claro."""
    study = _study_with_artifacts()
    study.artifacts._store.pop(("calibration", "calibrated_pd_frame"))

    with pytest.raises(ArtifactNotFoundError, match=r"\('calibration', 'calibrated_pd_frame'\)"):
        study.run_step("performance")


def test_validadores_y_fallback_config_cubren_ramas_defensivas() -> None:
    """Los helpers de ensamblado rechazan contratos inválidos con mensajes propios."""
    pd_mod = step_module._import_pandas()
    fallback = _config()

    with pytest.raises(PerformanceDataError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd_mod, "scorecard.score")
    assert (
        step_module._performance_config_from_study(
            SimpleNamespace(config=SimpleNamespace(performance={"n_deciles": 3})),
            fallback=fallback,
        ).n_deciles
        == 3
    )
    assert (
        step_module._performance_config_from_study(
            SimpleNamespace(config=SimpleNamespace(performance=None)),
            fallback=fallback,
        )
        is fallback
    )
    assert (
        step_module._performance_config_from_study(
            SimpleNamespace(config=SimpleNamespace(performance=fallback)),
            fallback=PerformanceConfig(),
        )
        is fallback
    )

    cfg = _config()
    score = _score_frame()
    calibrated = _calibrated_pd_frame()
    assembled = step_module._assemble_performance_frame(
        score=score,
        calibrated_pd_frame=calibrated,
        config=cfg,
        pd=pd_mod,
    )
    assert assembled.columns.tolist() == ["partition", "target", "pd_calibrated", "score"]
    assert assembled.index.equals(calibrated.index)

    duplicated_score = pd.concat([score, score["score"]], axis=1)
    with pytest.raises(PerformanceDataError, match="columnas duplicadas"):
        step_module._assemble_performance_frame(
            score=duplicated_score,
            calibrated_pd_frame=calibrated,
            config=cfg,
            pd=pd_mod,
        )

    duplicated_calibrated = pd.concat([calibrated, calibrated["target"]], axis=1)
    with pytest.raises(PerformanceDataError, match="columnas duplicadas"):
        step_module._assemble_performance_frame(
            score=score,
            calibrated_pd_frame=duplicated_calibrated,
            config=cfg,
            pd=pd_mod,
        )

    duplicate_score_index = pd.concat([score, score.iloc[[0]]])
    with pytest.raises(PerformanceDataError, match="índice duplicado"):
        step_module._assemble_performance_frame(
            score=duplicate_score_index,
            calibrated_pd_frame=calibrated,
            config=cfg,
            pd=pd_mod,
        )

    duplicate_calibrated_index = pd.concat([calibrated, calibrated.iloc[[0]]])
    with pytest.raises(PerformanceDataError, match="índice duplicado"):
        step_module._assemble_performance_frame(
            score=score,
            calibrated_pd_frame=duplicate_calibrated_index,
            config=cfg,
            pd=pd_mod,
        )

    with pytest.raises(PerformanceDataError, match="columnas requeridas"):
        step_module._assemble_performance_frame(
            score=score.drop(columns=["score"]),
            calibrated_pd_frame=calibrated,
            config=cfg,
            pd=pd_mod,
        )

    with pytest.raises(PerformanceDataError, match="columnas requeridas"):
        step_module._assemble_performance_frame(
            score=score,
            calibrated_pd_frame=calibrated.drop(columns=["pd_calibrated"]),
            config=cfg,
            pd=pd_mod,
        )

    missing_index = score.drop(index="c0")
    with pytest.raises(PerformanceDataError, match="mismo índice"):
        step_module._assemble_performance_frame(
            score=missing_index,
            calibrated_pd_frame=calibrated,
            config=cfg,
            pd=pd_mod,
        )


def test_import_pandas_y_performance_step_liviano_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``import nikodym.performance`` registra el step sin cargar tabulares/scoring."""
    real_import = step_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="PerformanceStep requiere pandas"):
        step_module._import_pandas()

    code = textwrap.dedent(
        """
        import sys
        import nikodym.performance
        from nikodym.core.registry import REGISTRY

        assert REGISTRY.resolve("performance", "standard").__name__ == "PerformanceStep"
        blocked = [
            name
            for name in ("pandas", "pandera", "scipy", "sklearn")
            if name in sys.modules
        ]
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
