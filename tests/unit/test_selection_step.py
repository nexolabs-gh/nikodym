"""Tests de ``SelectionStep``: contrato CT-1, auditoría, import liviano y publicación."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.selection.step as step_module
from nikodym.binning.results import iv_band
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.study import Study
from nikodym.data.partition import PARTITION_COL, TTD_COL, PartitionResult
from nikodym.data.target import LabeledFrame, TargetSummary
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.selection.exceptions import SelectionFitError, SelectionForcedVifConflictError
from nikodym.selection.results import (
    SelectionCardSection,
    SelectionResult,
    VariableSelectionDecision,
)
from nikodym.selection.step import SELECTION_ARTIFACTS, SelectionStep


@dataclass
class _FakeBinningProcess:
    """Proceso mínimo compatible con la validación estructural del step."""

    woe_column_map_: dict[str, str]

    def transform(self) -> None:
        """Método centinela; el step sólo valida que exista."""


@dataclass
class _FakeBinningResult:
    """Resultado mínimo de binning con ``woe_column_map``."""

    woe_column_map: dict[str, str]


def _woe_frame() -> pd.DataFrame:
    """Frame WoE canónico para pruebas directas del step."""
    return pd.DataFrame(
        {
            "target": [0, 0, 1, 1, 0, 1],
            PARTITION_COL: [
                "desarrollo",
                "desarrollo",
                "desarrollo",
                "desarrollo",
                "oot",
                "oot",
            ],
            TTD_COL: [True, True, True, True, True, True],
            "score__woe": [0.3, -0.2, -0.1, -0.4, 0.3, -0.4],
        },
        index=pd.Index([f"op-{i}" for i in range(6)], name="loan_id"),
    )


def _summary(iv: float = 0.12) -> pd.DataFrame:
    """Summary mínimo de binning para una variable seleccionada."""
    return pd.DataFrame(
        {
            "name": ["score"],
            "selected": [True],
            "iv": [iv],
            "gini": [0.5],
            "quality_score": [0.1],
        }
    )


def _tables() -> dict[str, pd.DataFrame]:
    """Tablas de bins mínimas, sólo validadas por ``SelectionStep``."""
    return {"score": pd.DataFrame({"Bin": ["A"], "WoE": [0.3], "IV": [0.12]})}


def _labels(frame: pd.DataFrame) -> LabeledFrame:
    """Artefacto ``data.labels`` mínimo."""
    return LabeledFrame(
        frame=frame.copy(deep=True),
        target_col="target",
        status_col="label_status",
        summary=TargetSummary(
            class_counts={"bueno": 3, "malo": 3, "indeterminado": 0, "excluido": 0},
            bad_rate=0.5,
            exclusions_by_reason={},
            ambiguous_rows=0,
        ),
    )


def _splits(frame: pd.DataFrame) -> PartitionResult:
    """Artefacto ``data.splits`` mínimo."""
    return PartitionResult(
        frame=frame.copy(deep=True),
        partition_col=PARTITION_COL,
        ttd_col=TTD_COL,
        sizes={"desarrollo": 4, "holdout": 0, "oot": 2, "fuera_de_modelo": 0},
        bad_rates={"desarrollo": 0.5, "holdout": 0.0, "oot": 0.5, "fuera_de_modelo": 0.0},
        strategy_used="fixture",
    )


def _study_with_artifacts(config: SelectionConfig | None = None) -> Study:
    """Construye un ``Study`` con artefactos upstream ya publicados."""
    cfg = config or SelectionConfig(
        min_iv=0.0,
        correlation=CorrelationSelectionConfig(enabled=False),
        vif=VifSelectionConfig(enabled=False),
        stability=StabilitySelectionConfig(enabled=False),
    )
    frame = _woe_frame()
    study = Study(NikodymConfig(selection=cfg))
    study.artifacts.set("data", "labels", _labels(frame))
    study.artifacts.set("data", "splits", _splits(frame))
    study.artifacts.set(
        "binning",
        "process",
        _FakeBinningProcess(woe_column_map_={"score": "score__woe"}),
    )
    study.artifacts.set("binning", "summary", _summary())
    study.artifacts.set("binning", "tables", _tables())
    study.artifacts.set("binning", "woe_frame", frame)
    study.artifacts.set("binning", "result", _FakeBinningResult({"score": "score__woe"}))
    return study


def _study_with_custom_binning(
    *,
    frame: pd.DataFrame,
    summary: pd.DataFrame,
    woe_column_map: dict[str, str],
    config: SelectionConfig,
) -> Study:
    """Construye un ``Study`` con artefactos de binning sintéticos."""
    study = Study(NikodymConfig(selection=config))
    study.artifacts.set("data", "labels", _labels(frame))
    study.artifacts.set("data", "splits", _splits(frame))
    study.artifacts.set("binning", "process", _FakeBinningProcess(woe_column_map))
    study.artifacts.set("binning", "summary", summary)
    study.artifacts.set(
        "binning",
        "tables",
        {
            feature: pd.DataFrame({"Bin": ["A"], "WoE": [0.0], "IV": [0.1]})
            for feature in woe_column_map
        },
    )
    study.artifacts.set("binning", "woe_frame", frame)
    study.artifacts.set("binning", "result", _FakeBinningResult(woe_column_map))
    return study


def _decision(
    feature: str,
    reason: str,
    *,
    included: bool = False,
    iv: float = 0.12,
    **kwargs: object,
) -> VariableSelectionDecision:
    """Construye una decisión válida para ejercitar auditoría del step."""
    data: dict[str, object] = {
        "feature": feature,
        "woe_column": f"{feature}__woe",
        "included": included,
        "reason": reason,
        "iv": iv,
        "iv_band": iv_band(iv),
        "auc": None,
        "gini": None,
        "ks": None,
        "max_abs_corr": None,
        "max_corr_with": None,
        "vif": None,
        "max_csi": None,
        "forced": None,
        "detail": None,
    }
    data.update(kwargs)
    return VariableSelectionDecision.model_validate(data)


def test_from_config_y_contrato_step_exacto() -> None:
    """``SelectionStep`` expone el contrato CT-1 exacto del SDD-07."""
    cfg = SelectionConfig()
    step = SelectionStep.from_config(cfg)

    assert isinstance(step, SelectionStep)
    assert step.config is cfg
    assert step.name == "selection"
    assert step.requires == (
        ("data", "labels"),
        ("data", "splits"),
        ("binning", "process"),
        ("binning", "summary"),
        ("binning", "tables"),
        ("binning", "woe_frame"),
        ("binning", "result"),
    )
    assert step.provides == tuple(("selection", key) for key in SELECTION_ARTIFACTS)


def test_execute_publica_result_card_versiones_y_no_consume_rng(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El step ensambla resultados/card, resuelve versiones y no toca ``rng``."""
    study = _study_with_artifacts()
    versions = {
        "scikit-learn": "1.7.2",
        "statsmodels": "0.14.6",
        "scipy": "1.18.0",
        "pandas": "2.3.3",
        "numpy": "2.4.6",
    }
    monkeypatch.setattr(step_module.metadata, "version", lambda name: versions[name])

    result = SelectionStep.from_config(study.config.selection).execute(study, object())

    assert isinstance(result, SelectionResult)
    assert isinstance(study.artifacts.get("selection", "selection_card"), SelectionCardSection)
    assert result.selected_features == ("score",)
    assert result.selected_woe_columns == ("score__woe",)
    assert_frame_equal(
        study.artifacts.get("selection", "selected_woe_frame"),
        result.selected_woe_frame,
    )
    card = study.artifacts.get("selection", "selection_card")
    assert card.dependency_versions == versions
    assert card.thresholds["min_iv"] == 0.0
    assert card.n_selected == 1


def test_execute_canonicaliza_force_include_alias_sin_mutar_config() -> None:
    """El step aplica el alias WoE, audita en raw y conserva el config declarado."""
    cfg = SelectionConfig(
        min_iv=999.0,
        force_include=("score__woe",),
        correlation=CorrelationSelectionConfig(enabled=False),
        vif=VifSelectionConfig(enabled=False),
        stability=StabilitySelectionConfig(enabled=False),
    )
    study = _study_with_artifacts(cfg)
    sink = InMemoryAuditSink()
    step = SelectionStep.from_config(cfg)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(1))
    decision = result.selection_table.set_index("feature").loc["score"]

    assert result.selected_features == ("score",)
    assert decision["reason"] == "business_include"
    assert decision["forced"] == "include"
    assert [event.payload["regla"] for event in sink.events] == ["business_include"]
    assert cfg.force_include == ("score__woe",)
    assert step.config is cfg


def test_validadores_de_artefactos_fallan_con_mensajes_en_espanol() -> None:
    """Los helpers ``_as_*`` rechazan artefactos mal tipados con contexto claro."""
    pd_mod = step_module._import_pandas()
    frame = _woe_frame()

    with pytest.raises(SelectionFitError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd_mod, "summary")
    with pytest.raises(SelectionFitError, match="LabeledFrame"):
        step_module._as_labeled_frame(object())
    with pytest.raises(SelectionFitError, match="PartitionResult"):
        step_module._as_partition_result(object())
    with pytest.raises(SelectionFitError, match="WoEBinner fiteado"):
        step_module._as_binning_process(object())
    with pytest.raises(SelectionFitError, match="mapping de DataFrames"):
        step_module._as_tables(object(), pd_mod)
    with pytest.raises(SelectionFitError, match="tabla no tabular"):
        step_module._as_tables({"score": object()}, pd_mod)
    with pytest.raises(SelectionFitError, match="woe_column_map"):
        step_module._as_binning_result(object())
    with pytest.raises(SelectionFitError, match="columnas requeridas"):
        step_module._validate_required_columns(frame.drop(columns=["target"]), ("target",))
    with pytest.raises(SelectionFitError, match="columna ttd"):
        step_module._validate_optional_ttd_column(frame.drop(columns=[TTD_COL]), TTD_COL)
    step_module._validate_optional_ttd_column(frame.drop(columns=[TTD_COL]), None)


def test_dependency_versions_cubre_paquete_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Las versiones faltantes se serializan como ``no_instalado`` sin importar módulos."""

    def fake_version(name: str) -> str:
        if name == "scipy":
            raise step_module.metadata.PackageNotFoundError(name)
        return f"v-{name}"

    monkeypatch.setattr(step_module.metadata, "version", fake_version)

    assert step_module._dependency_versions() == {
        "scikit-learn": "v-scikit-learn",
        "statsmodels": "v-statsmodels",
        "scipy": "no_instalado",
        "pandas": "v-pandas",
        "numpy": "v-numpy",
    }


def test_log_decision_del_step_cubre_exclusiones_flags_y_estabilidad() -> None:
    """La auditoría vive en ``SelectionStep`` y registra cada motivo relevante."""
    cfg = SelectionConfig(
        min_iv=0.05,
        max_iv=0.50,
        min_auc=0.60,
        min_ks=0.20,
        min_gini=0.10,
        stability=StabilitySelectionConfig(enabled=True, stable_threshold=0.10),
    )
    decisions = (
        _decision("inc", "business_include", included=True, iv=0.01, forced="include"),
        _decision("exc", "business_exclude", forced="exclude"),
        _decision("iv", "low_iv", iv=0.01),
        _decision("hi", "high_iv", included=True, iv=0.60),
        _decision("auc", "low_auc", auc=0.55),
        _decision("ks", "low_ks", ks=0.10),
        _decision("gini", "low_gini", gini=0.05),
        _decision("corr", "high_correlation", max_abs_corr=0.91, max_corr_with="hi"),
        _decision("vif", "high_vif", vif=float("inf")),
        _decision("const", "constant_or_nonfinite", detail="sin variación"),
        _decision("stab", "high_stability", max_csi=0.30),
    )
    result = SelectionResult(
        candidate_features=tuple(decision.feature for decision in decisions),
        candidate_woe_columns=tuple(decision.woe_column for decision in decisions),
        selected_features=("inc", "hi"),
        selected_woe_columns=("inc__woe", "hi__woe"),
        selected_woe_frame=pd.DataFrame({"inc__woe": [0.1], "hi__woe": [0.2]}),
        selection_table=pd.DataFrame(),
        correlation_matrix=pd.DataFrame(),
        vif_table=pd.DataFrame(
            [{"iteration": 2, "feature": "vif", "removed": True, "vif": float("inf")}]
        ),
        stability_table=pd.DataFrame(
            [
                {
                    "feature": "stab",
                    "woe_column": "stab__woe",
                    "sample": "oot",
                    "csi": 0.30,
                    "csi_band": "redevelop",
                    "smoothing": 1e-6,
                },
                {
                    "feature": "ok",
                    "woe_column": "ok__woe",
                    "sample": "oot",
                    "csi": 0.01,
                    "csi_band": "stable",
                    "smoothing": 1e-6,
                },
            ]
        ),
        decisions=decisions,
    )
    sink = InMemoryAuditSink()
    step = SelectionStep.from_config(cfg)
    step._audit = sink

    step._log_selection_decisions(result=result, config=cfg)

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert rules == [
        "business_include",
        "business_exclude",
        "low_iv",
        "high_iv",
        "low_auc",
        "low_ks",
        "low_gini",
        "high_correlation",
        "high_vif",
        "constant_or_nonfinite",
        "high_stability",
        "stability_csi",
    ]
    corr = sink.events[7].payload["valor"]
    assert corr == {
        "feature": "corr",
        "woe_column": "corr__woe",
        "feature_retenida": "hi",
        "rho": 0.91,
        "method": "pearson",
    }
    vif = sink.events[8].payload["valor"]
    assert vif["iteration"] == 2
    assert sink.events[-1].payload["accion"] == "diagnosticar_sin_eliminar"


def test_conflicto_vif_real_entre_forzadas_se_audita_antes_de_relevantar() -> None:
    """El conflicto VIF real entre ``force_include`` emite ``forced_conflict``."""
    frame = pd.DataFrame(
        {
            "target": [0, 0, 1, 1, 0, 1],
            "label_status": ["bueno", "bueno", "malo", "malo", "bueno", "malo"],
            PARTITION_COL: ["desarrollo"] * 4 + ["oot"] * 2,
            TTD_COL: [True] * 6,
            "x1__woe": [0.0, 1.0, 2.0, 3.0, 0.0, 3.0],
            "x2__woe": [0.0, 1.0, 2.0, 3.0, 0.0, 3.0],
        },
        index=pd.Index([f"op-{i}" for i in range(6)], name="loan_id"),
    )
    cfg = SelectionConfig(
        min_iv=0.0,
        force_include=("x1", "x2"),
        stability=StabilitySelectionConfig(enabled=False),
    )
    study = _study_with_custom_binning(
        frame=frame,
        summary=pd.DataFrame({"name": ["x1", "x2"], "selected": [True, True], "iv": [0.20, 0.30]}),
        woe_column_map={"x1": "x1__woe", "x2": "x2__woe"},
        config=cfg,
    )
    sink = InMemoryAuditSink()
    step = SelectionStep.from_config(cfg)
    step._audit = sink

    with pytest.raises(SelectionForcedVifConflictError):
        step.execute(study, np.random.default_rng(1))

    decisions = [event for event in sink.events if event.kind == "decision"]
    assert [event.payload["regla"] for event in decisions] == ["forced_conflict"]
    assert decisions[0].payload["umbral"] == 5.0
    assert "VIF excede" in decisions[0].payload["valor"]["detalle"]


def test_force_include_constante_no_emite_forced_conflict() -> None:
    """Una forzada constante falla sin registrar conflicto VIF espurio."""
    frame = _woe_frame().assign(score__woe=[1.0] * 6)
    cfg = SelectionConfig(
        min_iv=0.0,
        force_include=("score",),
        vif=VifSelectionConfig(enabled=False),
        stability=StabilitySelectionConfig(enabled=False),
    )
    study = _study_with_custom_binning(
        frame=frame,
        summary=_summary(),
        woe_column_map={"score": "score__woe"},
        config=cfg,
    )
    sink = InMemoryAuditSink()
    step = SelectionStep.from_config(cfg)
    step._audit = sink

    with pytest.raises(SelectionFitError, match="constante o no finita"):
        step.execute(study, np.random.default_rng(1))

    assert "forced_conflict" not in {
        event.payload["regla"] for event in sink.events if event.kind == "decision"
    }


def test_force_include_inexistente_no_emite_forced_conflict() -> None:
    """Una forzada no binneada falla sin registrar conflicto VIF espurio."""
    cfg = SelectionConfig(
        min_iv=0.0,
        force_include=("fantasma",),
        vif=VifSelectionConfig(enabled=False),
        stability=StabilitySelectionConfig(enabled=False),
    )
    study = _study_with_custom_binning(
        frame=_woe_frame(),
        summary=_summary(),
        woe_column_map={"score": "score__woe"},
        config=cfg,
    )
    sink = InMemoryAuditSink()
    step = SelectionStep.from_config(cfg)
    step._audit = sink

    with pytest.raises(SelectionFitError, match="fantasma"):
        step.execute(study, np.random.default_rng(1))

    assert "forced_conflict" not in {
        event.payload["regla"] for event in sink.events if event.kind == "decision"
    }


def test_missing_dependency_en_import_perezoso_del_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La ausencia de ``selection.selector`` se traduce a ``MissingDependencyError`` accionable."""
    real_import = step_module.importlib.import_module

    def fake_import(name: str) -> Any:
        if name == "nikodym.selection.selector":
            raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", fake_import)

    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        step_module._build_selector(SelectionConfig())


def test_import_selection_step_liviano_no_carga_selector_ni_scoring() -> None:
    """``import nikodym.selection.step`` no arrastra selector ni dependencias de scoring."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym.selection.step

        blocked = [
            name for name in (
                "nikodym.selection.selector",
                "pandas",
                "sklearn",
                "statsmodels",
                "scipy",
                "optbinning",
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


def test_config_desde_study_coacciona_dict_y_fallback_standalone() -> None:
    """El step lee ``study.config.selection`` y conserva respaldo para uso standalone."""
    fallback = SelectionConfig(min_iv=0.01)
    study = SimpleNamespace(config=SimpleNamespace(selection={"min_iv": 0.03}))
    assert step_module._selection_config_from_study(study, fallback=fallback).min_iv == 0.03

    study_without_selection = Study(NikodymConfig())
    assert step_module._selection_config_from_study(study_without_selection, fallback=fallback) is (
        fallback
    )


def test_execute_no_muta_woe_frame_ni_summary_de_binning() -> None:
    """Las entradas de binning se copian defensivamente antes del ajuste."""
    study = _study_with_artifacts()
    woe_before = study.artifacts.get("binning", "woe_frame").copy(deep=True)
    summary_before = study.artifacts.get("binning", "summary").copy(deep=True)

    SelectionStep.from_config(study.config.selection).execute(study, np.random.default_rng(1))

    assert_frame_equal(study.artifacts.get("binning", "woe_frame"), woe_before)
    assert_frame_equal(study.artifacts.get("binning", "summary"), summary_before)


def test_ramas_defensivas_de_helpers_de_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cubre rutas defensivas que sostienen núcleo liviano y auditoría determinista."""
    real_import = step_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="pandas"):
        step_module._import_pandas()
    monkeypatch.setattr(step_module.importlib, "import_module", real_import)

    assert step_module._removed_vif_iterations(pd.DataFrame()) == {}
    assert step_module._removed_vif_iterations(pd.DataFrame({"feature": ["x"]})) == {}
    assert step_module._optional_float(None) is None
    assert step_module._optional_float("no-numero") is None
    assert step_module._optional_float(-0.0) == 0.0

    disabled = SelectionConfig(
        correlation=CorrelationSelectionConfig(enabled=False),
        vif=VifSelectionConfig(enabled=False),
        stability=StabilitySelectionConfig(enabled=False),
    )
    enabled = SelectionConfig()
    assert step_module._thresholds_from_config(disabled)["correlation.threshold"] is None
    assert step_module._thresholds_from_config(disabled)["vif.threshold"] is None
    assert step_module._thresholds_from_config(disabled)["stability.stable_threshold"] is None
    assert step_module._thresholds_from_config(enabled)["correlation.threshold"] == 0.75
    assert step_module._thresholds_from_config(enabled)["vif.threshold"] == 5.0
    assert step_module._thresholds_from_config(enabled)["stability.review_threshold"] == 0.25

    included_manual = _decision("manual", "low_iv", included=True, iv=0.01)
    assert step_module._decision_action(included_manual) == "incluir"
    missing = _decision("missing", "missing_binning_artifact")
    assert step_module._decision_value(missing, enabled, {}) == {
        "feature": "missing",
        "woe_column": "missing__woe",
    }
