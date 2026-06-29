"""Tests de ``SurvivalStep``: CT-1, publicación, auditoría e import liviano."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.core.study as study_module
import nikodym.survival as survival_pkg
import nikodym.survival.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.survival.config import (
    CoxAftConfig,
    DiscreteHazardConfig,
    SurvivalConfig,
    SurvivalInputConfig,
    SurvivalMethod,
    SurvivalTimeGridConfig,
)
from nikodym.survival.exceptions import SurvivalConfigError, SurvivalInputError
from nikodym.survival.results import SurvivalCard, SurvivalDiagnostics, SurvivalResult
from nikodym.survival.step import SURVIVAL_ARTIFACTS, SurvivalStep

ROOT_SEED = 20_260_629


def test_from_config_registro_reexport_contrato_orden_e_import_liviano() -> None:
    """``SurvivalStep`` queda registrado sin cargar pandas/lifelines/statsmodels al importar."""
    cfg = _cfg()
    step = SurvivalStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("survival", "standard") is SurvivalStep
    assert survival_pkg.__getattr__("SurvivalStep") is SurvivalStep
    assert step.config is cfg
    assert step.name == "survival"
    assert step.requires == (("data", "frame"), ("model", "raw_pd_frame"))
    assert step.provides == tuple(("survival", key) for key in SURVIVAL_ARTIFACTS)
    assert study_module._DEFAULT_DOMAIN_ORDER == (
        "data",
        "markov",
        "eda",
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "survival",
        "performance",
        "stability",
        "report",
        "provisioning_cmf",
    )

    step.emit(
        AuditEvent(
            kind="decision",
            step="survival",
            payload={"regla": "x"},
            ts=datetime.now(UTC),
        )
    )

    code = (
        "import nikodym.core, sys;"
        "assert 'nikodym.survival' not in sys.modules;"
        "import nikodym.survival;"
        "blocked=[m for m in ('pandas','lifelines','statsmodels','sksurv') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'SurvivalStep' in nikodym.survival.__all__"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert sink.events[-1].payload == {"regla": "x"}


def test_run_default_discrete_publica_artifacts_invariantes_y_auditoria() -> None:
    """El flujo default ``discrete_hazard`` publica las 7 claves e invariantes lifetime PD."""
    cfg = _cfg()
    frame = _hazard_frame()
    pd_frame = _pd_frame(frame.index, with_partition=True)
    original_frame = frame.copy(deep=True)
    original_pd = pd_frame.copy(deep=True)
    study = _study(cfg, frame=frame, pd_frame=pd_frame)
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    study.run(steps=["survival"])
    result = study.artifacts.get("survival", "result")
    term = study.artifacts.get("survival", "term_structure")

    assert isinstance(result, SurvivalResult)
    assert isinstance(term, pd.DataFrame)
    assert study.artifacts.keys()[-7:] == [("survival", key) for key in SURVIVAL_ARTIFACTS]
    assert result.card.method == "discrete_hazard"
    assert result.card.metric_sections["person_period"]["n_rows"] == 228
    assert result.card.metric_sections["time_grid"]["warnings"] == ("FALTA-DATO-SUR-1",)
    assert result.card.falta_dato == ("FALTA-DATO-SUR-1",)
    assert set(term["warning_codes"]) == {("FALTA-DATO-SUR-1",)}
    _assert_term_invariants(term)
    assert_frame_equal(study.artifacts.get("data", "frame"), original_frame)
    assert_frame_equal(study.artifacts.get("model", "raw_pd_frame"), original_pd)
    assert {
        "survival_method",
        "survival_time_grid",
        "survival_input_quality",
        "survival_pd_source",
        "survival_person_period",
        "survival_km_greenwood",
        "survival_schoenfeld",
        "survival_aft",
    }.issubset({event.payload["regla"] for event in sink.events if event.kind == "decision"})


def test_determinismo_no_leakage_y_no_mutacion_en_particiones_no_desarrollo() -> None:
    """Cambiar targets Holdout/OOT no mueve el ajuste ni las predicciones del step."""
    cfg = _cfg()
    frame = _partitioned_frame()
    pd_frame = _pd_frame(frame.index, with_partition=True)
    original_frame = frame.copy(deep=True)
    original_pd = pd_frame.copy(deep=True)
    first = _execute(cfg, frame=frame, pd_frame=pd_frame)
    second = _execute(cfg, frame=frame, pd_frame=pd_frame)
    changed = frame.copy(deep=True)
    changed.loc[changed.index.str.startswith(("H", "O")), "event"] = (
        1 - changed.loc[changed.index.str.startswith(("H", "O")), "event"]
    )
    no_leakage = _execute(cfg, frame=changed, pd_frame=pd_frame)

    assert_frame_equal(first.term_structure(), second.term_structure())
    assert_frame_equal(first.term_structure(), no_leakage.term_structure())
    assert_frame_equal(frame, original_frame)
    assert_frame_equal(pd_frame, original_pd)


def test_ct1_y_calibration_condicional_conserva_partition_de_model_raw() -> None:
    """CT-1 falla claro y ``pd_source='calibration'`` exige/calza su artefacto condicional."""
    cfg = _cfg()
    step = SurvivalStep.from_config(cfg)
    study = Study(NikodymConfig(survival=cfg))

    with pytest.raises(ArtifactNotFoundError, match=r"\('data', 'frame'\)"):
        step.execute(study, np.random.default_rng(ROOT_SEED))

    frame = _hazard_frame()
    study.artifacts.set("data", "frame", frame)
    with pytest.raises(ArtifactNotFoundError, match=r"\('model', 'raw_pd_frame'\)"):
        step.execute(study, np.random.default_rng(ROOT_SEED))

    calibration_cfg = _cfg(pd_source="calibration")
    calibration_study = _study(
        calibration_cfg,
        frame=frame,
        pd_frame=_pd_frame(frame.index, with_partition=True),
    )
    with pytest.raises(ArtifactNotFoundError, match="pd_source='calibration'"):
        SurvivalStep.from_config(calibration_cfg).execute(
            calibration_study,
            np.random.default_rng(ROOT_SEED),
        )

    calibration = _pd_frame(frame.index).drop(columns=["partition"], errors="ignore")
    calibration_study.artifacts.set("calibration", "calibrated_pd_frame", calibration)
    result = SurvivalStep.from_config(calibration_cfg).execute(
        calibration_study,
        np.random.default_rng(ROOT_SEED),
    )

    assert result.card.pd_source == "calibration"
    assert result.card.metric_sections["pd_source"]["source_artifact"] == (
        "calibration.calibrated_pd_frame"
    )
    assert result.term_structure()["partition"].unique().tolist() == ["desarrollo"]


def test_kaplan_meier_y_helpers_defensivos_del_step() -> None:
    """Kaplan-Meier usa DTOs del step y los helpers defensivos fallan con errores propios."""
    cfg = _cfg(
        method="kaplan_meier",
        pd_source="none",
        time_grid=SurvivalTimeGridConfig(horizon_periods=3),
    )
    frame = _km_frame()
    pd_frame = _pd_frame(frame.index)
    result = _execute(cfg, frame=frame, pd_frame=pd_frame)

    assert result.card.method == "kaplan_meier"
    assert result.card.metric_sections["km_greenwood"]["n_curves"] == 1
    assert result.diagnostics.method == "kaplan_meier"
    assert result.term_structure()["warning_codes"].tolist() == [("FALTA-DATO-SUR-3",)] * 3
    assert (
        step_module._time_grid_from_config_or_data(
            frame,
            cfg=_cfg(time_grid=SurvivalTimeGridConfig(evaluation_times=(1.0, 2.0))),
        )[1]["source"]
        == "evaluation_times"
    )
    assert (
        step_module._time_grid_from_config_or_data(
            frame,
            cfg=_cfg(time_grid=SurvivalTimeGridConfig(horizon_periods=2)),
        )[1]["source"]
        == "horizon_periods"
    )
    assert step_module._term_structure_summary(pd.DataFrame()) == {"n_rows": 0, "n_periods": 0}
    assert (
        step_module._pd_source_column(_cfg(pd_source="model_raw", pd_role="offset"))
        == "linear_predictor"
    )
    assert step_module._pd_source_column(_cfg(pd_source="none", pd_role="covariate")) is None
    assert (
        step_module._survival_config_from_study(
            cast("Study", SimpleNamespace(config=SimpleNamespace(survival=None))),
            fallback=cfg,
        )
        is cfg
    )
    mapped_cfg = _cfg().model_dump()
    assert (
        step_module._survival_config_from_study(
            cast("Study", SimpleNamespace(config=SimpleNamespace(survival=mapped_cfg))),
            fallback=cfg,
        )
        == _cfg()
    )
    assert (
        step_module._pd_match_context(
            frame,
            pd_frame.drop(columns=["pd_raw"]),
            cfg=_cfg(),
        )["pd_coverage"]
        == 0.0
    )

    with pytest.raises(SurvivalInputError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd, "x")
    with pytest.raises(SurvivalInputError, match="duplicados"):
        step_module._validate_unique_index(
            pd.DataFrame(index=pd.Index(["x", "x"])),
            artifact="x",
        )
    with pytest.raises(SurvivalInputError, match="Faltan columnas"):
        step_module._validate_frame_contracts(
            frame.drop(columns=["event"]),
            pd_frame,
            cfg=_cfg(),
        )
    with pytest.raises(SurvivalInputError, match="segment"):
        step_module._validate_frame_contracts(
            frame,
            pd_frame,
            cfg=SurvivalConfig(
                input=SurvivalInputConfig(
                    duration_col="duration",
                    event_col="event",
                    segment_col="segment",
                    id_col="loan_code",
                ),
                fail_on_falta_dato=False,
            ),
        )
    with pytest.raises(SurvivalInputError, match="filas_sin_match"):
        step_module._validate_frame_contracts(
            frame,
            pd_frame.iloc[:-1],
            cfg=_cfg(),
        )
    broken_calibration_study = Study(NikodymConfig(survival=_cfg(pd_source="calibration")))
    broken_calibration_study.artifacts.set(
        "calibration",
        "calibrated_pd_frame",
        pd_frame.copy(deep=True),
    )
    with pytest.raises(SurvivalInputError, match="calibrated_pd_frame"):
        step_module._pd_frame_for_config(
            broken_calibration_study,
            cfg=_cfg(pd_source="calibration"),
            model_raw_frame=_pd_frame(pd_frame.index[:-1], with_partition=True),
            pd=pd,
        )
    with pytest.raises(SurvivalInputError, match="tiempos observados"):
        step_module._observed_times(
            pd.DataFrame({"duration": [None]}),
            duration_col="duration",
        )

    no_warning_frame = pd.DataFrame({"warning_codes": [()]})
    assert step_module._with_step_warnings(no_warning_frame, ()) is no_warning_frame
    without_warning_column = pd.DataFrame({"x": [1]})
    assert step_module._with_step_warnings(without_warning_column, ("FALTA-DATO-SUR-1",)).equals(
        without_warning_column
    )
    assert step_module._warning_codes(pd.DataFrame({"x": [1]})) == ()
    assert step_module._warning_codes(pd.DataFrame({"warning_codes": ["A", None]})) == ("A",)
    assert step_module._as_warning_tuple("A") == ("A",)
    assert step_module._as_warning_tuple(None) == ()
    assert step_module._clean_float(-0.0) == 0.0


def test_dependencias_ramas_modelo_publicacion_y_versiones(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dependencias faltantes y ramas defensivas del step quedan traducidas y cubiertas."""
    real_import = step_module.importlib.import_module

    def blocked_import(name: str) -> Any:
        if name == "pandas" or name.startswith("statsmodels") or name.startswith("lifelines"):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", blocked_import)
    with pytest.raises(MissingDependencyError, match=r"nikodym\[scoring\]"):
        step_module._require_method_dependency("discrete_hazard")
    with pytest.raises(MissingDependencyError, match=r"nikodym\[survival\]"):
        step_module._require_method_dependency("kaplan_meier")
    with pytest.raises(MissingDependencyError, match="pandas"):
        step_module._import_pandas()
    monkeypatch.setattr(step_module.importlib, "import_module", real_import)

    cox = step_module._new_model(_cfg(method="cox_ph", pd_source="none", covariate_cols=("x",)))
    aft = step_module._new_model(
        _cfg(
            method="aft",
            pd_source="none",
            covariate_cols=("x",),
            cox_aft=CoxAftConfig(aft_family="weibull"),
        )
    )
    with pytest.raises(SurvivalConfigError, match="no soportado"):
        step_module._new_model(cast("SurvivalConfig", SimpleNamespace(method="otro")))

    term = _minimal_term_frame()
    aft_sections = step_module._metric_sections(
        aft,
        cfg=_cfg(
            method="aft",
            pd_source="none",
            covariate_cols=("x",),
            cox_aft=CoxAftConfig(aft_family="weibull"),
        ),
        term_structure=term,
        pd_context={},
        time_context={},
    )
    assert type(cox).__name__ == "CoxPHSurvivalModel"
    assert aft_sections["aft"]["aft_family"] == "weibull"

    diagnostics = SurvivalDiagnostics(
        method="kaplan_meier",
        n_rows=0,
        n_events=0,
        n_censored=0,
        max_observed_time=0.0,
    )
    card = SurvivalCard(
        method="kaplan_meier",
        pd_source="none",
        duration_col="duration",
        event_col="event",
        time_unit="period",
        n_rows=0,
        n_events=0,
        n_periods=0,
        output_columns=step_module._TERM_STRUCTURE_COLUMNS,
        diagnostics=diagnostics,
        dependency_versions={},
    )
    fake_result = SimpleNamespace(
        estimator=object(),
        term_structure_frame=None,
        survival_curve_frame=pd.DataFrame(),
        hazard_frame=pd.DataFrame(),
        diagnostics=diagnostics,
        card=card,
        model_copy=lambda deep: SimpleNamespace(card=card, deep=deep),
    )
    publish_study = Study(NikodymConfig())
    SurvivalStep.from_config(_cfg())._publish_artifacts(publish_study, fake_result)
    assert publish_study.artifacts.get("survival", "term_structure") is None

    def missing_version(package: str) -> str:
        if package == "numpy":
            raise step_module.PackageNotFoundError(package)
        return f"{package}-version"

    monkeypatch.setattr(step_module, "version", missing_version)
    assert step_module._dependency_versions_for_method("discrete_hazard") == {
        "pandas": "pandas-version",
        "statsmodels": "statsmodels-version",
    }


def _cfg(
    *,
    method: SurvivalMethod = "discrete_hazard",
    pd_source: str = "model_raw",
    pd_role: str = "covariate",
    covariate_cols: tuple[str, ...] = (),
    time_grid: SurvivalTimeGridConfig | None = None,
    cox_aft: CoxAftConfig | None = None,
) -> SurvivalConfig:
    """Config survival sintético para el step."""
    return SurvivalConfig(
        method=method,
        input=SurvivalInputConfig(
            duration_col="duration",
            event_col="event",
            pd_source=cast(Any, pd_source),
            covariate_cols=covariate_cols,
        ),
        time_grid=SurvivalTimeGridConfig() if time_grid is None else time_grid,
        discrete_hazard=DiscreteHazardConfig(pd_role=cast(Any, pd_role)),
        cox_aft=CoxAftConfig() if cox_aft is None else cox_aft,
        fail_on_falta_dato=False,
    )


def _study(cfg: SurvivalConfig, *, frame: pd.DataFrame, pd_frame: pd.DataFrame) -> Study:
    """Construye un ``Study`` con artefactos survival preinyectados."""
    study = Study(NikodymConfig(survival=cfg))
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("model", "raw_pd_frame", pd_frame)
    return study


def _execute(
    cfg: SurvivalConfig,
    *,
    frame: pd.DataFrame,
    pd_frame: pd.DataFrame,
) -> SurvivalResult:
    """Ejecuta el step con semilla fija y devuelve el resultado agregado."""
    study = _study(cfg, frame=frame, pd_frame=pd_frame)
    return SurvivalStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))


def _hazard_frame() -> pd.DataFrame:
    """Dataset discreto con hazards empíricos 10% y 20%."""
    rows: list[dict[str, int]] = []
    index: list[str] = []
    for position in range(120):
        index.append(f"L{position:03d}")
        if position < 12:
            rows.append({"duration": 1, "event": 1})
        elif position < 36:
            rows.append({"duration": 2, "event": 1})
        else:
            rows.append({"duration": 2, "event": 0})
    return pd.DataFrame(rows, index=pd.Index(index, name="loan_id"))


def _partitioned_frame() -> pd.DataFrame:
    """Dataset con Desarrollo, Holdout y OOT para probar no-leakage."""
    desarrollo = _hazard_frame()
    holdout = _hazard_frame().iloc[:12].copy(deep=True)
    holdout.index = pd.Index([f"H{idx:03d}" for idx in range(len(holdout))], name="loan_id")
    oot = _hazard_frame().iloc[12:24].copy(deep=True)
    oot.index = pd.Index([f"O{idx:03d}" for idx in range(len(oot))], name="loan_id")
    return pd.concat([desarrollo, holdout, oot])


def _km_frame() -> pd.DataFrame:
    """Dataset Kaplan-Meier pequeño con eventos y censura derecha."""
    return pd.DataFrame(
        {"duration": [1, 2, 3, 4, 4], "event": [1, 1, 1, 0, 0]},
        index=pd.Index([f"K{idx}" for idx in range(5)], name="loan_id"),
    )


def _pd_frame(index: pd.Index, *, with_partition: bool = False) -> pd.DataFrame:
    """``model.raw_pd_frame`` sintético con PD, predictor lineal y particiones opcionales."""
    frame = pd.DataFrame(
        {
            "pd_raw": [0.02 + 0.001 * (position % 7) for position in range(len(index))],
            "linear_predictor": [-3.9 + 0.02 * (position % 5) for position in range(len(index))],
            "target": [0] * len(index),
        },
        index=index.copy(),
    )
    if with_partition:
        frame["partition"] = [
            "desarrollo"
            if str(label).startswith(("L", "K"))
            else "holdout"
            if str(label).startswith("H")
            else "oot"
            for label in index
        ]
    return frame


def _assert_term_invariants(term: pd.DataFrame) -> None:
    """Valida identidades survival/PD en una term-structure tidy."""
    for _row_id, group in term.groupby("row_id", sort=False):
        assert group["survival"].is_monotonic_decreasing
        assert (group["pd_marginal"] >= 0.0).all()
        assert group["pd_cumulative"].tolist() == pytest.approx(
            (1.0 - group["survival"]).tolist(),
            abs=1e-12,
        )
        assert group["pd_marginal"].sum() == pytest.approx(group["pd_cumulative"].iloc[-1])


def _minimal_term_frame() -> pd.DataFrame:
    """Term-structure mínima válida para helpers CT-2."""
    return pd.DataFrame(
        {
            "row_id": ["x"],
            "segment": [None],
            "partition": [None],
            "period": [1],
            "time_value": [1.0],
            "hazard": [0.1],
            "survival": [0.9],
            "pd_marginal": [0.1],
            "pd_cumulative": [0.1],
            "method": ["discrete_hazard"],
            "pd_source": ["model_raw"],
            "scenario": [None],
            "warning_codes": [()],
        },
        index=pd.Index(["x|1"], name="curve_id"),
    )
