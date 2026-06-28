"""Tests de ``StabilityStep``: contrato CT-1, auditoría, no-mutación e import liviano."""

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
import nikodym.stability as stability_pkg
import nikodym.stability.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.stability.config import StabilityConfig
from nikodym.stability.exceptions import StabilityDataError
from nikodym.stability.results import StabilityCardSection, StabilityResult
from nikodym.stability.step import STABILITY_ARTIFACTS, StabilityStep
from nikodym.testing import assert_bitwise_reproducible


def _config(**kwargs: Any) -> StabilityConfig:
    """Config base de stability con bins pequeños para fixtures sintéticos."""
    params: dict[str, Any] = {
        "psi_bins": 2,
        "csi_bins": 2,
        "temporal_column": "period",
        "include_pd_stability": False,
    }
    params.update(kwargs)
    return StabilityConfig(**params)


def _index() -> pd.Index:
    """Índice modelable compartido por score, calibración y data."""
    return pd.Index(
        [
            *(f"d{i}" for i in range(10)),
            *(f"h{i}" for i in range(10)),
            *(f"o{i}" for i in range(10)),
        ],
        name="loan_id",
    )


def _score_frame(*, include_period: bool = False) -> pd.DataFrame:
    """Artefacto ``scorecard.score`` con score y puntos por característica final."""
    dev = [float(i) for i in range(1, 11)]
    holdout = [1.0] * 8 + [6.0, 10.0]
    oot = dev
    frame = pd.DataFrame(
        {
            "score": [*dev, *holdout, *oot],
            # Orden deliberadamente invertido: el step publica feature_point_columns ordenado.
            "f2__points": [
                *([0.0] * 5 + [10.0] * 5),
                *([0.0] * 8 + [10.0] * 2),
                *([0.0] * 5 + [10.0] * 5),
            ],
            "f1__points": [
                *([0.0] * 5 + [10.0] * 5),
                *([0.0] * 6 + [10.0] * 4),
                *([0.0] * 5 + [10.0] * 5),
            ],
            "extra_score": [f"s{i}" for i in range(30)],
        },
        index=_index(),
    )
    if include_period:
        frame["period"] = ["P0"] * 10 + ["P1"] * 10 + ["P2"] * 10
    return frame


def _calibrated_pd_frame() -> pd.DataFrame:
    """Artefacto ``calibration.calibrated_pd_frame`` canónico para stability."""
    return pd.DataFrame(
        {
            "partition": ["desarrollo"] * 10 + ["holdout"] * 10 + ["oot"] * 10,
            "pd_calibrated": [0.10] * 15 + [0.20] * 15,
            "target": [0, 1] * 15,
            "linear_predictor_calibrated": [float(i) / 10.0 for i in range(30)],
        },
        index=_index(),
    )


def _data_frame() -> pd.DataFrame:
    """Artefacto ``data.frame`` usado sólo para recuperar la columna temporal."""
    return pd.DataFrame(
        {
            "period": ["P0"] * 10 + ["P1"] * 10 + ["P2"] * 10,
            "raw_feature": [float(i) for i in range(30)],
        },
        index=_index(),
    )


def _study_with_artifacts(
    *,
    config: StabilityConfig | None = None,
    score: pd.DataFrame | None = None,
    calibrated_pd_frame: pd.DataFrame | None = None,
    data_frame: pd.DataFrame | None = None,
) -> Study:
    """Construye un ``Study`` con los artefactos mínimos de stability."""
    cfg = config or _config()
    study = Study(NikodymConfig(stability=cfg))
    study.artifacts.set("scorecard", "score", _score_frame() if score is None else score)
    study.artifacts.set(
        "calibration",
        "calibrated_pd_frame",
        _calibrated_pd_frame() if calibrated_pd_frame is None else calibrated_pd_frame,
    )
    if data_frame is not None:
        study.artifacts.set("data", "frame", data_frame)
    return study


def _run_step_snapshot() -> dict[str, Any]:
    """Ejecuta el step aislado y devuelve una vista serializable determinista."""
    study = _study_with_artifacts(data_frame=_data_frame())
    result = StabilityStep.from_config(study.config.stability).execute(
        study,
        np.random.default_rng(20_240_628),
    )
    return {
        "psi_table": result.psi_table.to_dict("split"),
        "stability_metrics": result.stability_metrics.to_dict("split"),
        "card": result.card.model_dump(mode="json"),
        "temporal": [record.model_dump(mode="json") for record in result.temporal_records],
    }


def test_from_config_registro_reexport_y_contrato_step_minimo() -> None:
    """``StabilityStep`` expone el contrato CT-1 mínimo de B11.8."""
    cfg = _config()
    step = StabilityStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("stability", "standard") is StabilityStep
    assert stability_pkg.__getattr__("StabilityStep") is StabilityStep
    assert step.config is cfg
    assert step.name == "stability"
    assert step.requires == (
        ("scorecard", "score"),
        ("calibration", "calibrated_pd_frame"),
    )
    assert step.provides == tuple(("stability", key) for key in STABILITY_ARTIFACTS)
    step.emit(
        AuditEvent(
            kind="decision",
            step="stability",
            payload={"regla": "x"},
            ts=datetime.now(UTC),
        )
    )
    assert sink.events[-1].payload == {"regla": "x"}


def test_core_study_cablea_stability_en_orden_por_defecto() -> None:
    """``Study`` resuelve ``stability`` como dominio perezoso después de ``performance``."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order[order.index("performance") + 1] == "stability"
    assert study_module._DOMAIN_MODULES["stability"] == "nikodym.stability"
    assert study_module._DOMAIN_CONFIG_CLASSES["stability"] == (
        "nikodym.stability.config",
        "StabilityConfig",
    )

    study = Study(NikodymConfig(stability=StabilityConfig(temporal_axis="none")))

    assert study._default_step_names() == ["stability"]
    assert isinstance(study._resolve_step("stability"), StabilityStep)


def test_execute_publica_result_card_goldens_audit_y_no_consume_rng() -> None:
    """El step evalúa estabilidad, publica copias y propaga auditoría del evaluator."""
    study = _study_with_artifacts(data_frame=_data_frame())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = StabilityStep.from_config(study.config.stability)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(20_240_628))

    assert isinstance(result, StabilityResult)
    assert isinstance(result.card, StabilityCardSection)
    for key in STABILITY_ARTIFACTS:
        assert study.artifacts.has("stability", key)

    metrics = {
        (record.metric, record.comparison, record.feature): record
        for record in result.metric_records
    }
    assert metrics[("score_psi", "dev_vs_holdout", "score")].value == pytest.approx(0.41588831)
    assert metrics[("score_psi", "dev_vs_holdout", "score")].band == "redevelop"
    assert metrics[("score_psi", "dev_vs_oot", "score")].value == pytest.approx(0.0)
    assert metrics[("csi", "dev_vs_holdout", "f1__points")].value == pytest.approx(0.04054651)
    assert metrics[("csi", "dev_vs_holdout", "f2__points")].value == pytest.approx(0.41588831)
    assert metrics[("temporal_score", "period", "score")].value == pytest.approx(0.41588831)
    assert result.card.metric_sections["stability"]["csi_features"] == [
        "f1__points",
        "f2__points",
    ]
    assert [record.period for record in result.temporal_records] == ["P0", "P1", "P2"]

    assert_frame_equal(study.artifacts.get("stability", "psi_table"), result.psi_table)
    assert_frame_equal(
        study.artifacts.get("stability", "stability_metrics"),
        result.stability_metrics,
    )
    assert study.artifacts.get("stability", "card") == result.card
    artifact_result = study.artifacts.get("stability", "result")
    assert isinstance(artifact_result, StabilityResult)
    assert_frame_equal(artifact_result.psi_table, result.psi_table)
    assert_frame_equal(artifact_result.stability_metrics, result.stability_metrics)
    assert artifact_result.psi_records == result.psi_records
    assert artifact_result.csi_records == result.csi_records
    assert artifact_result.metric_records == result.metric_records
    assert artifact_result.card == result.card

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert rules == ["psi_score", "csi_feature", "score_temporal"]


def test_execute_no_muta_artefactos_upstream() -> None:
    """Las entradas de scorecard, calibration y data se copian antes de evaluar."""
    study = _study_with_artifacts(data_frame=_data_frame())
    score_before = study.artifacts.get("scorecard", "score").copy(deep=True)
    calibrated_before = study.artifacts.get("calibration", "calibrated_pd_frame").copy(deep=True)
    data_before = study.artifacts.get("data", "frame").copy(deep=True)

    StabilityStep.from_config(study.config.stability).execute(
        study,
        np.random.default_rng(1),
    )

    assert_frame_equal(study.artifacts.get("scorecard", "score"), score_before)
    assert_frame_equal(
        study.artifacts.get("calibration", "calibrated_pd_frame"),
        calibrated_before,
    )
    assert_frame_equal(study.artifacts.get("data", "frame"), data_before)


def test_execute_usa_temporal_del_score_sin_requerir_data_frame() -> None:
    """Si ``scorecard.score`` trae período, ``data.frame`` no participa."""
    cfg = _config(temporal_column="period")
    study = _study_with_artifacts(config=cfg, score=_score_frame(include_period=True))

    result = StabilityStep.from_config(study.config.stability).execute(
        study,
        np.random.default_rng(2),
    )

    assert [record.period for record in result.temporal_records] == ["P0", "P1", "P2"]
    assert not study.artifacts.has("data", "frame")


def test_requires_faltante_falla_con_artifactnotfounderror() -> None:
    """Si falta un artefacto requerido, CT-1 levanta ``ArtifactNotFoundError`` claro."""
    study = _study_with_artifacts(data_frame=_data_frame())
    study.artifacts._store.pop(("calibration", "calibrated_pd_frame"))

    with pytest.raises(ArtifactNotFoundError, match=r"\('calibration', 'calibrated_pd_frame'\)"):
        study.run_step("stability")


def test_data_frame_temporal_es_opcional_pero_falla_si_se_necesita() -> None:
    """``data.frame`` no es ``requires`` estático, pero falta si score no trae período."""
    study = _study_with_artifacts()

    with pytest.raises(ArtifactNotFoundError, match=r"\('data', 'frame'\)"):
        StabilityStep.from_config(study.config.stability).execute(
            study,
            np.random.default_rng(3),
        )


def test_reproducibilidad_bit_identical() -> None:
    """Dos corridas con los mismos artefactos y config producen bytes idénticos."""
    assert_bitwise_reproducible(_run_step_snapshot)


def test_validadores_y_fallback_config_cubren_ramas_defensivas() -> None:
    """Los helpers de ensamblado rechazan contratos inválidos con mensajes propios."""
    pd_mod = step_module._import_pandas()
    fallback = _config()

    with pytest.raises(StabilityDataError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd_mod, "scorecard.score")
    assert (
        step_module._stability_config_from_study(
            SimpleNamespace(
                config=SimpleNamespace(stability={"psi_bins": 3, "temporal_axis": "none"})
            ),
            fallback=fallback,
        ).psi_bins
        == 3
    )
    assert (
        step_module._stability_config_from_study(
            SimpleNamespace(config=SimpleNamespace(stability=None)),
            fallback=fallback,
        )
        is fallback
    )
    assert (
        step_module._stability_config_from_study(
            SimpleNamespace(config=SimpleNamespace(stability=fallback)),
            fallback=StabilityConfig(temporal_axis="none"),
        )
        is fallback
    )

    cfg = _config(temporal_axis="none")
    score = _score_frame()
    calibrated = _calibrated_pd_frame()
    assembled, points = step_module._assemble_stability_frame(
        score=score,
        calibrated_pd_frame=calibrated,
        data_frame=None,
        config=cfg,
        pd=pd_mod,
    )
    assert assembled.columns.tolist() == [
        "partition",
        "pd_calibrated",
        "score",
        "f1__points",
        "f2__points",
    ]
    assert points == ("f1__points", "f2__points")
    assert assembled.index.equals(calibrated.index)

    score_without_points = score.drop(columns=["f1__points", "f2__points"])
    assembled_without_points, no_points = step_module._assemble_stability_frame(
        score=score_without_points,
        calibrated_pd_frame=calibrated,
        data_frame=None,
        config=cfg,
        pd=pd_mod,
    )
    assert assembled_without_points.columns.tolist() == [
        "partition",
        "pd_calibrated",
        "score",
    ]
    assert no_points == ()

    duplicated_score = pd.concat([score, score["score"]], axis=1)
    with pytest.raises(StabilityDataError, match="columnas duplicadas"):
        step_module._assemble_stability_frame(
            score=duplicated_score,
            calibrated_pd_frame=calibrated,
            data_frame=None,
            config=cfg,
            pd=pd_mod,
        )

    duplicated_calibrated = pd.concat([calibrated, calibrated["pd_calibrated"]], axis=1)
    with pytest.raises(StabilityDataError, match="columnas duplicadas"):
        step_module._assemble_stability_frame(
            score=score,
            calibrated_pd_frame=duplicated_calibrated,
            data_frame=None,
            config=cfg,
            pd=pd_mod,
        )

    duplicated_data = pd.concat([_data_frame(), _data_frame()["period"]], axis=1)
    with pytest.raises(StabilityDataError, match="columnas duplicadas"):
        step_module._assemble_stability_frame(
            score=score,
            calibrated_pd_frame=calibrated,
            data_frame=duplicated_data,
            config=_config(),
            pd=pd_mod,
        )

    duplicate_score_index = pd.concat([score, score.iloc[[0]]])
    with pytest.raises(StabilityDataError, match="índice duplicado"):
        step_module._assemble_stability_frame(
            score=duplicate_score_index,
            calibrated_pd_frame=calibrated,
            data_frame=None,
            config=cfg,
            pd=pd_mod,
        )

    duplicate_calibrated_index = pd.concat([calibrated, calibrated.iloc[[0]]])
    with pytest.raises(StabilityDataError, match="índice duplicado"):
        step_module._assemble_stability_frame(
            score=score,
            calibrated_pd_frame=duplicate_calibrated_index,
            data_frame=None,
            config=cfg,
            pd=pd_mod,
        )

    duplicate_data_index = pd.concat([_data_frame(), _data_frame().iloc[[0]]])
    with pytest.raises(StabilityDataError, match="índice duplicado"):
        step_module._assemble_stability_frame(
            score=score,
            calibrated_pd_frame=calibrated,
            data_frame=duplicate_data_index,
            config=_config(),
            pd=pd_mod,
        )

    with pytest.raises(StabilityDataError, match="columnas requeridas"):
        step_module._assemble_stability_frame(
            score=score.drop(columns=["score"]),
            calibrated_pd_frame=calibrated,
            data_frame=None,
            config=cfg,
            pd=pd_mod,
        )

    with pytest.raises(StabilityDataError, match="columnas requeridas"):
        step_module._assemble_stability_frame(
            score=score,
            calibrated_pd_frame=calibrated.drop(columns=["pd_calibrated"]),
            data_frame=None,
            config=cfg,
            pd=pd_mod,
        )

    missing_index = score.drop(index="d0")
    with pytest.raises(StabilityDataError, match="mismo índice"):
        step_module._assemble_stability_frame(
            score=missing_index,
            calibrated_pd_frame=calibrated,
            data_frame=None,
            config=cfg,
            pd=pd_mod,
        )

    data_missing_row = _data_frame().drop(index="d0")
    with pytest.raises(StabilityDataError, match="no contiene todas"):
        step_module._assemble_stability_frame(
            score=score,
            calibrated_pd_frame=calibrated,
            data_frame=data_missing_row,
            config=_config(),
            pd=pd_mod,
        )

    with pytest.raises(StabilityDataError, match="temporal_column"):
        step_module._assemble_stability_frame(
            score=score,
            calibrated_pd_frame=calibrated,
            data_frame=_data_frame().drop(columns=["period"]),
            config=_config(temporal_column="period"),
            pd=pd_mod,
        )


def test_guard_defensivo_si_temporal_exige_data_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El ensamblado falla claro si se pide columna temporal pero no hay fuente."""
    pd_mod = step_module._import_pandas()
    monkeypatch.setattr(
        step_module,
        "_temporal_columns_to_copy",
        lambda **_kwargs: ("period",),
    )

    with pytest.raises(StabilityDataError, match=r"requiere data\.frame"):
        step_module._assemble_stability_frame(
            score=_score_frame(),
            calibrated_pd_frame=_calibrated_pd_frame(),
            data_frame=None,
            config=_config(),
            pd=pd_mod,
        )


def test_helpers_temporales_cubren_ramas_de_recuperacion() -> None:
    """La columna temporal se toma del score salvo que haga falta ``data.frame``."""
    score = _score_frame()
    score_with_period = _score_frame(include_period=True)
    data = _data_frame()
    pd_mod = step_module._import_pandas()
    cfg_none = _config(temporal_axis="none")
    cfg_explicit = _config(temporal_column="period")
    cfg_inferred = _config(temporal_column=None)

    assert (
        step_module._data_frame_for_temporal_if_needed(
            SimpleNamespace(artifacts=SimpleNamespace(get=lambda *_args: data)),
            score=score,
            config=cfg_none,
            pd=pd_mod,
        )
        is None
    )
    assert (
        step_module._data_frame_for_temporal_if_needed(
            SimpleNamespace(artifacts=SimpleNamespace(get=lambda *_args: data)),
            score=score_with_period,
            config=cfg_explicit,
            pd=pd_mod,
        )
        is None
    )
    assert (
        step_module._data_frame_for_temporal_if_needed(
            SimpleNamespace(artifacts=SimpleNamespace(get=lambda *_args: data)),
            score=score_with_period,
            config=cfg_inferred,
            pd=pd_mod,
        )
        is None
    )
    recovered = step_module._data_frame_for_temporal_if_needed(
        SimpleNamespace(artifacts=SimpleNamespace(get=lambda *_args: data)),
        score=score,
        config=cfg_inferred,
        pd=pd_mod,
    )
    assert recovered is not None
    assert_frame_equal(recovered, data)

    assert (
        step_module._temporal_columns_to_copy(
            score=score,
            data_frame=None,
            config=cfg_none,
        )
        == ()
    )
    assert step_module._temporal_columns_to_copy(
        score=score_with_period,
        data_frame=None,
        config=cfg_explicit,
    ) == ("period",)
    assert step_module._temporal_columns_to_copy(
        score=score,
        data_frame=data,
        config=cfg_explicit,
    ) == ("period",)
    assert step_module._temporal_columns_to_copy(
        score=score_with_period,
        data_frame=None,
        config=cfg_inferred,
    ) == ("period",)
    assert (
        step_module._temporal_columns_to_copy(
            score=score,
            data_frame=None,
            config=cfg_inferred,
        )
        == ()
    )

    ambiguous = data.assign(cohort=data["period"])
    assert step_module._temporal_columns_to_copy(
        score=score,
        data_frame=ambiguous,
        config=cfg_inferred,
    ) == ("cohort", "period")


def test_import_pandas_y_stability_step_liviano_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``import nikodym.stability`` registra el step sin cargar tabulares/scoring."""
    real_import = step_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="StabilityStep requiere pandas"):
        step_module._import_pandas()

    code = textwrap.dedent(
        """
        import sys
        import nikodym.stability
        from nikodym.core.registry import REGISTRY

        assert REGISTRY.resolve("stability", "standard").__name__ == "StabilityStep"
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
