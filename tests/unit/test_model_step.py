"""Tests de ``ModelStep``: contrato CT-1, auditoría, import liviano y publicación."""

from __future__ import annotations

import math
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.model.step as step_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.study import Study
from nikodym.data.partition import PARTITION_COL, TTD_COL, PartitionResult
from nikodym.data.target import LabeledFrame, TargetSummary
from nikodym.model.config import IvContributionConfig, ModelConfig, SignPolicyConfig, StepwiseConfig
from nikodym.model.exceptions import ModelFitError
from nikodym.model.results import ModelCardSection, ModelResult, StepwiseDecision
from nikodym.model.step import MODEL_ARTIFACTS, ModelStep


def _model_config(
    *,
    force_include: tuple[str, ...] = (),
    force_exclude: tuple[str, ...] = (),
    fail_if_no_features: bool = True,
) -> ModelConfig:
    """Config estable para pruebas directas del step."""
    return ModelConfig(
        stepwise=StepwiseConfig(direction="none"),
        sign_policy=SignPolicyConfig(action="flag", fail_on_forced_inverted=False),
        iv_contribution=IvContributionConfig(action="flag"),
        force_include=force_include,
        force_exclude=force_exclude,
        fail_if_no_features=fail_if_no_features,
    )


def _selected_woe_frame(*, include_filtered: bool = True) -> pd.DataFrame:
    """Frame WoE canónico con Desarrollo, Holdout, OOT y una fila fuera de modelo."""
    saldo = [
        -2.0,
        -1.6,
        -1.3,
        -1.1,
        -0.8,
        -0.4,
        0.2,
        0.5,
        0.9,
        1.2,
        1.6,
        2.0,
        -1.8,
        -0.6,
        0.1,
        0.7,
        1.4,
        -1.4,
        0.3,
        1.8,
    ]
    mora = [
        -1.5,
        -1.2,
        -0.9,
        0.1,
        -0.4,
        -0.2,
        0.3,
        0.6,
        1.1,
        1.4,
        1.8,
        2.2,
        -1.7,
        -0.8,
        0.0,
        0.8,
        1.6,
        -1.0,
        0.2,
        2.0,
    ]
    target = [1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 0, 1, 0, 0]
    extra = pd.DataFrame(
        {
            "target": [1, 0, 1, 0, 1],
            "label_status": ["malo", "bueno", "malo", "bueno", "malo"],
            PARTITION_COL: ["holdout", "holdout", "oot", "oot", "fuera_de_modelo"],
            TTD_COL: [True, True, True, True, False],
            "saldo__woe": [-1.7, 1.1, -0.9, 1.5, 0.4],
            "mora__woe": [-1.4, 1.0, -0.7, 1.8, 0.2],
        },
        index=pd.Index([f"op-extra-{i}" for i in range(5)], name="loan_id"),
    )
    frame = pd.DataFrame(
        {
            "target": target,
            "label_status": ["malo" if value == 1 else "bueno" for value in target],
            PARTITION_COL: ["desarrollo"] * len(target),
            TTD_COL: [True] * len(target),
            "saldo__woe": saldo,
            "mora__woe": mora,
        },
        index=pd.Index([f"op-{i:03d}" for i in range(len(target))], name="loan_id"),
    )
    if include_filtered:
        return pd.concat([frame, extra], axis=0)
    return frame


def _summary(*, saldo_iv: object = 0.12, mora_iv: object = 0.08) -> pd.DataFrame:
    """Summary mínimo de binning con IV consumido por ``ModelStep``."""
    return pd.DataFrame(
        {
            "name": ["saldo", "mora"],
            "selected": [True, True],
            "iv": [saldo_iv, mora_iv],
            "gini": [0.4, 0.3],
        }
    )


def _labels(frame: pd.DataFrame) -> LabeledFrame:
    """Artefacto ``data.labels`` mínimo."""
    target = frame["target"]
    return LabeledFrame(
        frame=frame.copy(deep=True),
        target_col="target",
        status_col="label_status",
        summary=TargetSummary(
            class_counts={
                "bueno": int(target.eq(0).sum()),
                "malo": int(target.eq(1).sum()),
                "indeterminado": 0,
                "excluido": 0,
            },
            bad_rate=float(target.mean()),
            exclusions_by_reason={},
            ambiguous_rows=0,
        ),
    )


def _splits(frame: pd.DataFrame) -> PartitionResult:
    """Artefacto ``data.splits`` mínimo."""
    partitions = frame[PARTITION_COL].astype("string")
    return PartitionResult(
        frame=frame.copy(deep=True),
        partition_col=PARTITION_COL,
        ttd_col=TTD_COL,
        sizes={
            "desarrollo": int(partitions.eq("desarrollo").sum()),
            "holdout": int(partitions.eq("holdout").sum()),
            "oot": int(partitions.eq("oot").sum()),
            "fuera_de_modelo": int(partitions.eq("fuera_de_modelo").sum()),
        },
        bad_rates={"desarrollo": 0.5, "holdout": 0.5, "oot": 0.5, "fuera_de_modelo": 1.0},
        strategy_used="fixture",
    )


def _study_with_artifacts(
    *,
    config: ModelConfig | None = None,
    frame: pd.DataFrame | None = None,
    summary: pd.DataFrame | None = None,
    selected_features: tuple[str, ...] = ("saldo", "mora"),
    selected_woe_columns: tuple[str, ...] = ("saldo__woe", "mora__woe"),
) -> Study:
    """Construye un ``Study`` con artefactos upstream ya publicados."""
    selected_frame = _selected_woe_frame() if frame is None else frame
    study = Study(NikodymConfig(model=config or _model_config()))
    study.artifacts.set("data", "labels", _labels(selected_frame))
    study.artifacts.set("data", "splits", _splits(selected_frame))
    study.artifacts.set("binning", "summary", _summary() if summary is None else summary)
    study.artifacts.set("selection", "selected_features", selected_features)
    study.artifacts.set("selection", "selected_woe_columns", selected_woe_columns)
    study.artifacts.set("selection", "selected_woe_frame", selected_frame.copy(deep=True))
    return study


def test_from_config_y_contrato_step_exacto() -> None:
    """``ModelStep`` expone el contrato CT-1 exacto del SDD-08."""
    cfg = _model_config()
    step = ModelStep.from_config(cfg)

    assert isinstance(step, ModelStep)
    assert step.config is cfg
    assert step.name == "model"
    assert step.requires == (
        ("data", "labels"),
        ("data", "splits"),
        ("binning", "summary"),
        ("selection", "selected_features"),
        ("selection", "selected_woe_columns"),
        ("selection", "selected_woe_frame"),
    )
    assert step.provides == tuple(("model", key) for key in MODEL_ARTIFACTS)


def test_execute_publica_result_card_versiones_raw_pd_y_no_consume_rng(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El step ensambla resultados/card, resuelve versiones y no toca ``rng``."""
    versions = {
        "statsmodels": "0.14.6",
        "scikit-learn": "1.7.2",
        "scipy": "1.18.0",
        "pandas": "2.3.3",
        "numpy": "2.4.6",
    }
    monkeypatch.setattr(step_module.metadata, "version", lambda name: versions[name])
    study = _study_with_artifacts()

    result = ModelStep.from_config(study.config.model).execute(study, object())

    assert isinstance(result, ModelResult)
    assert isinstance(study.artifacts.get("model", "model_card"), ModelCardSection)
    for key in MODEL_ARTIFACTS:
        assert study.artifacts.has("model", key)
    assert result.final_features == ("mora", "saldo")
    assert result.final_woe_columns == ("mora__woe", "saldo__woe")
    assert result.model_card.dependency_versions == versions
    assert result.model_card.thresholds["iv_contribution.threshold"] == 0.90
    raw_pd = result.raw_pd_frame
    assert raw_pd.columns.tolist() == [PARTITION_COL, "target", "linear_predictor", "pd_raw"]
    assert raw_pd.index.tolist() == _selected_woe_frame().index[:-1].tolist()
    assert raw_pd["pd_raw"].between(0.0, 1.0).all()


def test_execute_no_muta_artefactos_upstream() -> None:
    """Las entradas de selection/binning/data se copian defensivamente antes del ajuste."""
    study = _study_with_artifacts()
    selected_before = study.artifacts.get("selection", "selected_woe_frame").copy(deep=True)
    summary_before = study.artifacts.get("binning", "summary").copy(deep=True)
    labels_before = study.artifacts.get("data", "labels").frame.copy(deep=True)
    splits_before = study.artifacts.get("data", "splits").frame.copy(deep=True)

    ModelStep.from_config(study.config.model).execute(study, np.random.default_rng(1))

    assert_frame_equal(study.artifacts.get("selection", "selected_woe_frame"), selected_before)
    assert_frame_equal(study.artifacts.get("binning", "summary"), summary_before)
    assert_frame_equal(study.artifacts.get("data", "labels").frame, labels_before)
    assert_frame_equal(study.artifacts.get("data", "splits").frame, splits_before)


def test_validadores_de_artefactos_fallan_con_mensajes_en_espanol() -> None:
    """Los helpers ``_as_*`` rechazan artefactos mal tipados con contexto claro."""
    pd_mod = step_module._import_pandas()
    frame = _selected_woe_frame(include_filtered=False)

    with pytest.raises(ModelFitError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd_mod, "selection.selected_woe_frame")
    with pytest.raises(ModelFitError, match="LabeledFrame"):
        step_module._as_labeled_frame(object())
    with pytest.raises(ModelFitError, match="PartitionResult"):
        step_module._as_partition_result(object())
    with pytest.raises(ModelFitError, match=r"tuple\[str"):
        step_module._as_string_tuple(object(), "selection", "selected_features")
    with pytest.raises(ModelFitError, match="mismo largo"):
        step_module._validate_selected_mapping(("saldo",), ("saldo__woe", "mora__woe"))
    with pytest.raises(ModelFitError, match="columnas requeridas"):
        step_module._validate_required_columns(frame.drop(columns=["target"]), ("target",), "x")


def test_iv_by_feature_y_targets_cubren_errores_defensivos() -> None:
    """IV y target de Desarrollo fallan temprano sin llegar a statsmodels."""
    with pytest.raises(ModelFitError, match="columnas requeridas"):
        step_module._iv_by_feature(pd.DataFrame({"name": ["saldo"]}), ("saldo",))
    with pytest.raises(ModelFitError, match="duplicado"):
        step_module._iv_by_feature(
            pd.DataFrame({"name": ["saldo", "saldo"], "iv": [0.1, 0.2]}),
            ("saldo",),
        )
    with pytest.raises(ModelFitError, match="no es numérico"):
        step_module._iv_by_feature(_summary(saldo_iv="x"), ("saldo", "mora"))
    with pytest.raises(ModelFitError, match="finito y no negativo"):
        step_module._iv_by_feature(_summary(saldo_iv=math.inf), ("saldo", "mora"))
    with pytest.raises(ModelFitError, match="booleano"):
        step_module._finite_nonnegative_float(True, label="IV")
    with pytest.raises(ModelFitError, match="faltantes"):
        step_module._iv_by_feature(_summary(), ("saldo", "fantasma"))

    with pytest.raises(ModelFitError, match="No hay filas"):
        step_module._validate_development_target(pd.Series([], dtype="float64"))
    with pytest.raises(ModelFitError, match="inválidos"):
        step_module._validate_development_target(pd.Series([0, 1, 2]))
    with pytest.raises(ModelFitError, match="0 y un 1"):
        step_module._validate_development_target(pd.Series([1, 1, 1]))


def test_config_desde_study_overrides_y_dependency_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El step coacciona config opaco y versiona paquetes ausentes como ``no_instalado``."""
    fallback = _model_config()
    study = SimpleNamespace(config=SimpleNamespace(model={"engine": "glm_binomial"}))
    assert step_module._model_config_from_study(study, fallback=fallback).engine == "glm_binomial"
    study_without_model = Study(NikodymConfig())
    assert step_module._model_config_from_study(study_without_model, fallback=fallback) is fallback

    with pytest.raises(ModelFitError, match=r"overrides.*faltantes"):
        step_module._validate_force_overrides(
            _model_config(force_include=("fantasma",)),
            ("saldo",),
        )

    def fake_version(name: str) -> str:
        if name == "scipy":
            raise step_module.metadata.PackageNotFoundError(name)
        return f"v-{name}"

    monkeypatch.setattr(step_module.metadata, "version", fake_version)
    assert step_module._dependency_versions() == {
        "statsmodels": "v-statsmodels",
        "scikit-learn": "v-scikit-learn",
        "scipy": "no_instalado",
        "pandas": "v-pandas",
        "numpy": "v-numpy",
    }


def test_log_decision_del_step_cubre_traza_overrides_convergencia_y_particiones() -> None:
    """La auditoría del step registra decisiones ricas desde la traza final del modelo."""
    cfg = _model_config(force_include=("saldo",), force_exclude=("mora",))
    decisions = (
        StepwiseDecision(
            iteration=1,
            feature="saldo",
            woe_column="saldo__woe",
            action="enter",
            criterion="wald_pvalue",
            p_value=0.01,
            lr_stat=None,
            beta=-0.2,
            threshold=0.05,
            detail="wald_p=0.01",
        ),
        StepwiseDecision(
            iteration=2,
            feature="mora",
            woe_column="mora__woe",
            action="remove",
            criterion="lr_test",
            p_value=0.30,
            lr_stat=1.2,
            beta=-0.1,
            threshold=0.05,
            detail="lr_p=0.3",
        ),
        StepwiseDecision(
            iteration=3,
            feature="ingreso",
            woe_column="ingreso__woe",
            action="flag",
            criterion="sign",
            p_value=None,
            lr_stat=None,
            beta=0.2,
            threshold=0.0,
            detail="sign_policy=flag",
        ),
        StepwiseDecision(
            iteration=4,
            feature="saldo",
            woe_column="saldo__woe",
            action="exclude",
            criterion="iv_contribution",
            p_value=None,
            lr_stat=None,
            beta=None,
            threshold=0.9,
            detail="iv_contribution=0.95",
        ),
        StepwiseDecision(
            iteration=5,
            feature="saldo",
            woe_column="saldo__woe",
            action="keep",
            criterion="both",
            p_value=0.04,
            lr_stat=2.0,
            beta=-0.3,
            threshold=0.05,
            detail="sin movimiento",
        ),
    )
    sink = InMemoryAuditSink()
    step = ModelStep.from_config(cfg)
    step._audit = sink

    step._log_force_overrides(cfg)
    step._log_stepwise_decisions(decisions, iv_by_feature={"saldo": 0.12, "mora": 0.08})
    step._log_convergence(
        SimpleNamespace(converged=True, optimizer="newton", n_iterations=7),
        config=cfg,
    )
    step._log_filtered_partitions(_selected_woe_frame(), partition_col=PARTITION_COL)

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert rules == [
        "force_include",
        "force_exclude",
        "model_stepwise_enter",
        "model_stepwise_remove",
        "model_sign_inverted",
        "model_iv_contribution",
        "model_both",
        "statsmodels_convergence",
        "partition_fuera_de_modelo",
    ]
    iv_payload = sink.events[5].payload["valor"]
    assert iv_payload["iv"] == 0.12
    assert iv_payload["iv_contribution"] == 0.95
    assert sink.events[-1].payload["accion"] == "no_puntuar"
    assert step_module._decision_action("desconocida") == "desconocida"
    assert step_module._iv_contribution_from_detail("otro") is None
    assert step_module._iv_contribution_from_detail("iv_contribution=no") is None
    assert step_module._iv_contribution_from_detail("iv_contribution=inf") is None
    assert step_module._normalize_float(-0.0) == 0.0


def test_missing_dependency_en_import_perezoso_del_estimator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La ausencia de ``model.estimator`` se traduce a ``MissingDependencyError`` accionable."""
    real_import = step_module.importlib.import_module

    def fake_import(name: str) -> Any:
        if name == "nikodym.model.estimator":
            raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", fake_import)

    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        step_module._build_estimator(_model_config())


def test_import_model_step_liviano_no_carga_estimator_ni_scoring() -> None:
    """``import nikodym.model.step`` no arrastra estimator ni dependencias de scoring."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym.model.step

        blocked = [
            name for name in (
                "nikodym.model.estimator",
                "pandas",
                "sklearn",
                "statsmodels",
                "scipy",
            )
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


def test_import_pandas_faltante_se_traduce(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ausencia de pandas en el step conserva mensaje accionable."""
    real_import = step_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)

    with pytest.raises(MissingDependencyError, match="ModelStep requiere pandas"):
        step_module._import_pandas()
