"""Tests de ``ForwardStep``: CT-1 dinámico, publicación, auditoría y Study."""

from __future__ import annotations

import subprocess
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.forward as forward_pkg
import nikodym.forward.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.forward.config import (
    ForwardConfig,
    ForwardInputConfig,
    MacroModelConfig,
    MacroSourceConfig,
    SatelliteConfig,
    ScenarioConfig,
    ScenarioDefinitionConfig,
    TtcReversionConfig,
)
from nikodym.forward.exceptions import ForwardInputError, PitConsistencyError
from nikodym.forward.results import ForwardResult
from nikodym.forward.step import FORWARD_ARTIFACTS, ForwardStep
from nikodym.markov.config import (
    MarkovConfig,
    MarkovDynamicsConfig,
    MarkovEstimationConfig,
    MarkovInputConfig,
    MarkovStateConfig,
)
from nikodym.survival.config import (
    DiscreteHazardConfig,
    SurvivalConfig,
    SurvivalInputConfig,
    SurvivalTimeGridConfig,
)

ROOT_SEED = 20_260_630
_FORWARD_COLUMNS = [
    "row_id",
    "segment",
    "partition",
    "source_model",
    "period",
    "time_value",
    "scenario",
    "scenario_weight",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "pd_marginal_base",
    "pd_cumulative_base",
    "lgd",
    "lgd_base",
    "pd_basis",
    "basis_state",
    "ttc_reversion_weight",
    "satellite_adjustment",
    "macro_model_id",
    "satellite_model_id",
    "method",
    "pd_source",
    "warning_codes",
]


def test_from_config_registro_exports_ct1_dinamico_e_import_liviano(tmp_path: Path) -> None:
    """``ForwardStep`` queda registrado y resuelve ``requires`` desde la config."""
    coeffs = _coefficient_table(tmp_path)
    survival_cfg = _forward_cfg(coeffs, sources=("survival",), macro_type="path")
    markov_cfg = _forward_cfg(coeffs, sources=("markov",), macro_type="artifact")
    both_cfg = _forward_cfg(coeffs, sources=("survival", "markov"), macro_type="artifact")
    step = ForwardStep.from_config(survival_cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("forward", "standard") is ForwardStep
    assert forward_pkg.__getattr__("ForwardStep") is ForwardStep
    assert step.config is survival_cfg
    assert step.name == "forward"
    assert step.requires == (("survival", "term_structure"),)
    assert ForwardStep.from_config(markov_cfg).requires == (
        ("markov", "term_structure"),
        ("forward", "macro_history"),
    )
    assert ForwardStep.from_config(both_cfg).requires == (
        ("survival", "term_structure"),
        ("markov", "term_structure"),
        ("forward", "macro_history"),
    )
    assert step.provides == tuple(("forward", key) for key in FORWARD_ARTIFACTS)

    step.emit(
        AuditEvent(
            kind="decision",
            step="forward",
            payload={"regla": "x"},
            ts=datetime.now(UTC),
        )
    )

    code = (
        "import nikodym.core, sys;"
        "assert 'nikodym.forward' not in sys.modules;"
        "import nikodym.forward;"
        "blocked=[m for m in ('statsmodels','pmdarima','pandas','scipy') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'nikodym.provisioning.ifrs9' not in sys.modules;"
        "assert 'nikodym.forward.step' in sys.modules;"
        "assert 'nikodym.forward.results' not in sys.modules;"
        "assert 'ForwardStep' in nikodym.forward.__all__"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert sink.events[-1].payload == {"regla": "x"}


def test_execute_publica_artifacts_ct2_auditoria_warning_codes_no_mutacion(
    tmp_path: Path,
) -> None:
    """El flujo real publica diez claves, lee ``warning_codes`` y no muta snapshots."""
    cfg = _forward_cfg(_coefficient_table(tmp_path), sources=("survival",))
    macro_history = _macro_history()
    term_structure = _term_structure("survival", pd_basis="ttc")
    macro_snapshot = macro_history.copy(deep=True)
    term_snapshot = term_structure.copy(deep=True)
    study = Study(NikodymConfig(forward=cfg))
    study.artifacts.set("forward", "macro_history", macro_history)
    study.artifacts.set("survival", "term_structure", term_structure)
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    assert study.run(steps=["forward"]) is study

    result = study.artifacts.get("forward", "result")
    term = study.artifacts.get("forward", "term_structure")
    assert isinstance(result, ForwardResult)
    assert tuple(term.columns) == tuple(_FORWARD_COLUMNS)
    assert result.term_structure() is not None
    assert result.card.metric_sections["term_structure_summary"]["sources"] == ("survival",)
    assert result.card.metric_sections["scenario_weights"]["weights"] == {
        "base": 0.6,
        "adverse": 0.3,
        "severe": 0.1,
    }
    assert set(term["pd_basis"]) == {"pit"}
    assert set(term["basis_state"]) == {"pit", "ttc"}
    # El invariante del test es la NO-mutación del código inyectado. ``warning_codes`` puede además
    # contener códigos upstream legítimos que varían por plataforma/BLAS (p. ej.
    # ``ConvergenceWarning`` del MLE de statsmodels: en x86/Linux avisa, en arm64/macOS no); eso es
    # información de auditoría honesta, no debe tragarse. Por eso se valida presencia, no igualdad.
    assert "UPSTREAM-CODE" in term.loc[term.index[0], "warning_codes"]
    assert study.artifacts.keys()[-10:] == [("forward", key) for key in FORWARD_ARTIFACTS]

    assert_frame_equal(study.artifacts.get("forward", "macro_history"), macro_snapshot)
    assert_frame_equal(study.artifacts.get("survival", "term_structure"), term_snapshot)
    _assert_forward_invariants(term)

    decision_rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert decision_rules == [
        "forward_macro_model",
        "forward_macro_input_quality",
        "forward_ljung_box",
        "forward_scenarios",
        "forward_no_mean_scenario_guard",
        "forward_satellite_model",
        "forward_term_structure_sources",
        "forward_pit_consistency",
        "forward_ttc_reversion",
        "forward_ecl_contract",
        "forward_falta_dato",
    ]


def test_determinismo_byte_equivalente(tmp_path: Path) -> None:
    """Dos corridas con los mismos frames/config producen salidas idénticas."""
    cfg = _forward_cfg(_coefficient_table(tmp_path), sources=("survival",))
    first = _run_forward(cfg, {"survival": _term_structure("survival", pd_basis="ttc")})
    second = _run_forward(cfg, {"survival": _term_structure("survival", pd_basis="ttc")})

    assert_frame_equal(first.macro_projection_frame, second.macro_projection_frame)
    assert_frame_equal(first.term_structure(), second.term_structure())
    assert_frame_equal(first.scenario_weight_frame, second.scenario_weight_frame)
    assert first.diagnostics == second.diagnostics
    assert first.card == second.card


def test_ct1_y_casos_borde_fallan_con_excepciones_propias(tmp_path: Path) -> None:
    """CT-1, macro ausente y PIT desconocido fallan en la frontera correcta."""
    coeffs = _coefficient_table(tmp_path)
    artifact_cfg = _forward_cfg(coeffs, sources=("survival",))
    missing_term_study = Study(NikodymConfig(forward=artifact_cfg))
    missing_term_study.artifacts.set("forward", "macro_history", _macro_history())

    with pytest.raises(ArtifactNotFoundError, match=r"\('survival', 'term_structure'\)"):
        ForwardStep.from_config(artifact_cfg).execute(
            missing_term_study,
            np.random.default_rng(ROOT_SEED),
        )

    dataframe_cfg = _forward_cfg(coeffs, sources=("survival",), macro_type="dataframe")
    missing_macro_study = Study(NikodymConfig(forward=dataframe_cfg))
    missing_macro_study.artifacts.set("survival", "term_structure", _term_structure("survival"))
    with pytest.raises(ForwardInputError, match="macro_history"):
        ForwardStep.from_config(dataframe_cfg).execute(
            missing_macro_study,
            np.random.default_rng(ROOT_SEED),
        )

    unknown_basis = _term_structure("survival", pd_basis="misterio")
    pit_study = Study(NikodymConfig(forward=artifact_cfg))
    pit_study.artifacts.set("forward", "macro_history", _macro_history())
    pit_study.artifacts.set("survival", "term_structure", unknown_basis)
    with pytest.raises(PitConsistencyError, match="pd_basis"):
        ForwardStep.from_config(artifact_cfg).execute(pit_study, np.random.default_rng(ROOT_SEED))


def test_path_macro_source_y_helpers_defensivos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La fuente path no entra a ``requires`` y los helpers traducen dependencias faltantes."""
    coeffs = _coefficient_table(tmp_path)
    macro_path = tmp_path / "macro.csv"
    _macro_history().to_csv(macro_path, index=False)
    cfg = _forward_cfg(
        coeffs,
        sources=("markov",),
        macro_type="path",
        macro_path=str(macro_path),
    )
    study = Study(NikodymConfig(forward=cfg))
    study.artifacts.set("markov", "term_structure", _term_structure("markov", pd_basis="ttc"))

    result = ForwardStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))

    assert result.card.metric_sections["macro_projection_summary"]["macro_source"] == {
        "type": "path",
        "path": str(macro_path),
    }
    assert ForwardStep.from_config(cfg).requires == (("markov", "term_structure"),)

    with pytest.raises(ForwardInputError, match=r"\.csv o \.parquet"):
        step_module._read_table_path(str(tmp_path / "macro.txt"), pd=pd, field_name="macro")

    real_import = step_module.importlib.import_module

    def blocked_import(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError(name)
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", blocked_import)
    with pytest.raises(MissingDependencyError, match="pandas"):
        step_module._import_pandas()


def test_helpers_defensivos_y_ramas_perezosas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cubre rutas auxiliares de fuentes, warnings, hashes y dependencias opcionales."""
    coeffs = _coefficient_table(tmp_path)
    cfg = _forward_cfg(coeffs, sources=("survival",), macro_type="dataframe")
    study = Study(NikodymConfig(forward=cfg))
    macro_history = _macro_history()
    study.artifacts.set("forward", "macro_history", macro_history)
    loaded_macro, macro_context = step_module._macro_history_from_source(study, cfg=cfg, pd=pd)
    assert_frame_equal(loaded_macro, macro_history)
    assert macro_context == {"type": "dataframe", "artifact_key": ("forward", "macro_history")}

    mapped_cfg = cfg.model_dump(mode="json")
    namespace_study = SimpleNamespace(config=SimpleNamespace(forward=mapped_cfg))
    assert step_module._forward_config_from_study(namespace_study, fallback=cfg) == cfg
    none_study = SimpleNamespace(config=SimpleNamespace(forward=None))
    assert step_module._forward_config_from_study(none_study, fallback=cfg) is cfg

    random_cfg = cfg.model_copy(
        update={"macro": MacroModelConfig(auto_arima_random=True, random_state=7)}
    )
    assert step_module._resolve_random_state(random_cfg, np.random.default_rng(ROOT_SEED)) == 7
    assert "pmdarima" in step_module._dependency_versions(
        random_cfg.model_copy(update={"macro": MacroModelConfig(kind="auto_arima")})
    )

    scenario_path = tmp_path / "scenario.csv"
    pd.DataFrame({"period": [1], "x": [2.0]}).to_csv(scenario_path, index=False)
    scenario_cfg = ScenarioConfig(
        scenarios=(
            ScenarioDefinitionConfig(name="base", weight=0.60, macro_path_path=str(scenario_path)),
            _scenario("adverse", 0.30, 0.50),
            _scenario("severe", 0.10, 1.00),
        )
    )
    scenario_frame = step_module._macro_scenario_frame(
        cfg.model_copy(update={"scenarios": scenario_cfg}),
        pd=pd,
    )
    assert scenario_frame is not None
    assert scenario_frame["scenario"].tolist() == ["base"]

    scenario_path_with_name = tmp_path / "scenario_named.csv"
    pd.DataFrame({"scenario": ["base"], "period": [1], "x": [2.0]}).to_csv(
        scenario_path_with_name,
        index=False,
    )
    named_scenario_cfg = ScenarioConfig(
        scenarios=(
            ScenarioDefinitionConfig(
                name="base",
                weight=0.60,
                macro_path_path=str(scenario_path_with_name),
            ),
            _scenario("adverse", 0.30, 0.50),
            _scenario("severe", 0.10, 1.00),
        )
    )
    named_scenario_frame = step_module._macro_scenario_frame(
        cfg.model_copy(update={"scenarios": named_scenario_cfg}),
        pd=pd,
    )
    assert named_scenario_frame is not None
    assert named_scenario_frame["scenario"].tolist() == ["base"]

    weighting = step_module._new_scenario_weighting(_forward_cfg(coeffs, sources=("survival",)))
    forward_with_lgd = _forward_for_reversion_with_lgd()
    anchor = _term_structure("survival", pd_basis="ttc")
    anchor["source_model"] = "survival"
    reverted, warning_codes = step_module._apply_ttc_reversion(
        weighting,
        forward_with_lgd,
        ttc_anchor=anchor,
    )
    assert warning_codes == ()
    assert reverted["lgd"].notna().all()

    no_basis = _term_structure("survival", pd_basis=None)
    pit_basis = _term_structure("survival", pd_basis="pit")
    unknown_basis = _term_structure("survival", pd_basis="misterio")
    assert step_module._pit_warnings(unknown_basis, cfg=cfg) == (
        "pd_basis_no_resuelta",
        "FALTA-DATO-FWD-4",
    )
    assert step_module._pit_warnings(pit_basis, cfg=cfg) == ("FALTA-DATO-FWD-4",)
    no_assumption_cfg = cfg.model_copy(
        update={
            "input": ForwardInputConfig(
                macro_source=MacroSourceConfig(type="dataframe", variable_cols=("x",)),
                term_structure_sources=("survival",),
                pd_basis_assumption=None,
                require_pit_consistency=False,
            )
        }
    )
    assert step_module._pit_decisions(no_basis, cfg=no_assumption_cfg) == (
        "pd_basis no resuelto permitido por config",
    )
    assert step_module._pd_basis_from_input(pit_basis, cfg=cfg) == "pit"
    assert step_module._blended_periods(pd.DataFrame({"x": [1]})) == ()

    parquet_path = tmp_path / "macro.parquet"
    macro_history.to_parquet(parquet_path)
    assert_frame_equal(
        step_module._read_table_path(str(parquet_path), pd=pd, field_name="macro"),
        macro_history,
    )
    with pytest.raises(ForwardInputError, match="No se pudo leer"):
        step_module._read_table_path(str(tmp_path / "missing.csv"), pd=pd, field_name="macro")
    with pytest.raises(ForwardInputError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd, "x")

    text_frame = pd.DataFrame({"x": [None, float("nan"), "a", "", "a"]})
    assert step_module._observed_texts(text_frame, "x") == ("a",)
    assert step_module._observed_texts(text_frame, "missing") == ()
    assert step_module._warning_codes_from_frame(pd.DataFrame({"x": [1]})) == ()
    assert step_module._as_warning_tuple(None) == ()
    assert step_module._as_warning_tuple("") == ()
    assert step_module._as_warning_tuple("A") == ("A",)
    assert step_module._as_warning_tuple(3) == ("3",)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warnings.warn("otro-warning", RuntimeWarning, stacklevel=1)
    assert step_module._warning_codes_from_warnings(caught) == ("RuntimeWarning:otro-warning",)

    with pytest.raises(ForwardInputError, match="no finito"):
        step_module._clean_float(float("inf"))
    assert step_module._clean_float(-0.0) == 0.0

    def missing_version(package: str) -> str:
        raise step_module.metadata.PackageNotFoundError(package)

    monkeypatch.setattr(step_module.metadata, "version", missing_version)
    assert step_module._package_version("pmdarima") == "no-disponible"


def test_study_end_to_end_con_survival_markov_forward(tmp_path: Path) -> None:
    """``Study`` ejecuta survival + markov + forward y publica ``ForwardResult`` final."""
    coeffs = _coefficient_table(tmp_path)
    forward_cfg = _forward_cfg(coeffs, sources=("survival", "markov"))
    study = Study(
        NikodymConfig(
            survival=_survival_cfg(),
            markov=_markov_cfg(),
            forward=forward_cfg,
        )
    )
    frame = _study_frame()
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("model", "raw_pd_frame", _pd_frame(frame.index))
    study.artifacts.set("forward", "macro_history", _macro_history())

    study.run(steps=["survival", "markov", "forward"])

    result = study.artifacts.get("forward", "result")
    term = study.artifacts.get("forward", "term_structure")
    assert isinstance(result, ForwardResult)
    assert set(term["source_model"]) == {"survival", "markov"}
    assert set(term["scenario"]) == {"base", "adverse", "severe"}
    assert result.term_structure() is not None


def _scenario(name: str, weight: float, shock: float = 0.0) -> ScenarioDefinitionConfig:
    """Escenario canónico para forward."""
    shocks = {} if name == "base" else {"x": shock}
    return ScenarioDefinitionConfig(name=name, weight=weight, shocks=shocks)


def _forward_cfg(
    coefficient_path: Path,
    *,
    sources: tuple[str, ...],
    macro_type: str = "artifact",
    macro_path: str | None = None,
) -> ForwardConfig:
    """Config forward mínimo, determinista y con coeficientes satellite fijos."""
    macro_source_kwargs: dict[str, object] = {
        "type": macro_type,
        "variable_cols": ("x",),
    }
    if macro_type == "artifact":
        macro_source_kwargs.update({"artifact_domain": "forward", "artifact_key": "macro_history"})
    if macro_type == "path":
        macro_source_kwargs["path"] = macro_path or "macro.csv"
    return ForwardConfig(
        input=ForwardInputConfig(
            macro_source=MacroSourceConfig(**macro_source_kwargs),  # type: ignore[arg-type]
            term_structure_sources=sources,  # type: ignore[arg-type]
            pd_basis_assumption="ttc",
        ),
        satellite=SatelliteConfig(
            mode="fixed_coefficients",
            factor_cols=("x",),
            coefficient_table_path=str(coefficient_path),
            min_history_periods=5,
        ),
        macro=MacroModelConfig(horizon_periods=2, arima_order=(1, 0, 0), ljung_box_lags=(1,)),
        scenarios=ScenarioConfig(
            scenarios=(
                _scenario("base", 0.60),
                _scenario("adverse", 0.30, 0.50),
                _scenario("severe", 0.10, 1.00),
            )
        ),
        ttc_reversion=TtcReversionConfig(
            reasonable_supportable_periods=1,
            reversion_periods=1,
        ),
    )


def _coefficient_table(tmp_path: Path) -> Path:
    """Crea coeficientes fijos auditados para el satellite."""
    path = tmp_path / "satellite_coefficients.csv"
    pd.DataFrame(
        [
            {
                "target_component": "pd",
                "factor_col": "x",
                "coefficient": 0.50,
                "sign": "positive",
            }
        ]
    ).to_csv(path, index=False)
    return path


def _macro_history() -> pd.DataFrame:
    """Histórico macro no constante con períodos suficientes."""
    return pd.DataFrame(
        {
            "period": range(1, 9),
            "x": [1.00, 1.20, 1.10, 1.35, 1.50, 1.65, 1.80, 2.00],
        }
    )


def _term_structure(source: str, *, pd_basis: str | None = "ttc") -> pd.DataFrame:
    """Term-structure base compatible con SDD-18/19 y warning_codes canónico."""
    rows: list[dict[str, Any]] = []
    previous_survival = 1.0
    for period, hazard in enumerate((0.02, 0.03), start=1):
        pd_marginal = previous_survival * hazard
        survival = previous_survival * (1.0 - hazard)
        pd_cumulative = 1.0 - survival
        row: dict[str, Any] = {
            "row_id": f"{source}-loan-1",
            "segment": "retail",
            "partition": "desarrollo",
            "period": period,
            "time_value": float(period),
            "hazard": hazard,
            "survival": survival,
            "pd_marginal": pd_marginal,
            "pd_cumulative": pd_cumulative,
            "method": f"{source}_method",
            "pd_source": "model_raw",
            "scenario": None,
            "warning_codes": ("UPSTREAM-CODE",) if period == 1 else (),
        }
        if pd_basis is not None:
            row["pd_basis"] = pd_basis
        rows.append(row)
        previous_survival = survival
    return pd.DataFrame(rows)


def _run_forward(cfg: ForwardConfig, terms: dict[str, pd.DataFrame]) -> ForwardResult:
    """Ejecuta forward directo con artefactos sintéticos."""
    study = Study(NikodymConfig(forward=cfg))
    study.artifacts.set("forward", "macro_history", _macro_history())
    for source, frame in terms.items():
        study.artifacts.set(source, "term_structure", frame)
    return ForwardStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))


def _assert_forward_invariants(term: pd.DataFrame) -> None:
    """Verifica identidades lifetime de la salida forward."""
    assert np.allclose(term["pd_cumulative"], 1.0 - term["survival"])
    for _key, group in term.groupby(
        ["row_id", "source_model", "scenario", "method", "pd_source"],
        sort=False,
        dropna=False,
    ):
        previous_survival = 1.0
        for row in group.itertuples(index=False):
            assert row.pd_marginal == pytest.approx(previous_survival * row.hazard, abs=1e-12)
            previous_survival = row.survival


def _forward_for_reversion_with_lgd() -> pd.DataFrame:
    """Salida satellite mínima con LGD numérica para probar reversión TTC."""
    rows: list[dict[str, Any]] = []
    weights = {"base": 0.60, "adverse": 0.30, "severe": 0.10}
    for scenario, weight in weights.items():
        previous_survival = 1.0
        for period, hazard in enumerate((0.02, 0.03), start=1):
            pd_marginal = previous_survival * hazard
            survival = previous_survival * (1.0 - hazard)
            pd_cumulative = 1.0 - survival
            rows.append(
                {
                    "row_id": "survival-loan-1",
                    "segment": "retail",
                    "partition": "desarrollo",
                    "source_model": "survival",
                    "period": period,
                    "time_value": float(period),
                    "scenario": scenario,
                    "scenario_weight": weight,
                    "hazard": hazard,
                    "survival": survival,
                    "pd_marginal": pd_marginal,
                    "pd_cumulative": pd_cumulative,
                    "pd_marginal_base": pd_marginal,
                    "pd_cumulative_base": pd_cumulative,
                    "lgd": 0.40,
                    "lgd_base": 0.40,
                    "pd_basis": "pit",
                    "basis_state": "pit",
                    "ttc_reversion_weight": 1.0,
                    "satellite_adjustment": 0.0,
                    "macro_model_id": "macro:x",
                    "satellite_model_id": "satellite:test",
                    "method": "survival_method",
                    "pd_source": "model_raw",
                    "warning_codes": (),
                }
            )
            previous_survival = survival
    return pd.DataFrame(rows)


def _study_frame() -> pd.DataFrame:
    """Frame único con columnas suficientes para survival y markov."""
    return pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6],
            "time": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            "state": [
                "A",
                "A",
                "A",
                "default",
                "A",
                "B",
                "B",
                "default",
                "B",
                "B",
                "A",
                "A",
            ],
            "duration": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            "event": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],
        },
        index=pd.Index([f"obs-{idx:02d}" for idx in range(12)], name="obs_id"),
    )


def _pd_frame(index: pd.Index) -> pd.DataFrame:
    """Frame de PD cruda requerido por ``SurvivalStep`` aunque pd_source='none'."""
    return pd.DataFrame(
        {
            "pd_raw": [0.02 + 0.001 * (position % 3) for position in range(len(index))],
            "linear_predictor": [-3.9 + 0.01 * (position % 4) for position in range(len(index))],
            "target": [0] * len(index),
            "partition": ["desarrollo"] * len(index),
        },
        index=index.copy(),
    )


def _survival_cfg() -> SurvivalConfig:
    """Config survival rápido para smoke end-to-end."""
    return SurvivalConfig(
        method="discrete_hazard",
        input=SurvivalInputConfig(
            duration_col="duration",
            event_col="event",
            pd_source="none",
        ),
        time_grid=SurvivalTimeGridConfig(horizon_periods=2),
        discrete_hazard=DiscreteHazardConfig(pd_role="none"),
        fail_on_falta_dato=False,
    )


def _markov_cfg() -> MarkovConfig:
    """Config Markov cohort rápido para smoke end-to-end."""
    return MarkovConfig(
        input=MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            partition_col=None,
        ),
        states=MarkovStateConfig(
            states=("A", "B", "default"),
            default_state="default",
            absorbing_states=("default",),
        ),
        estimation=MarkovEstimationConfig(method="cohort"),
        dynamics=MarkovDynamicsConfig(horizon_periods=(1, 2), embedding_policy="diagnose"),
    )
