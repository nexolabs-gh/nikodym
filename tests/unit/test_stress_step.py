"""Tests de ``StressStep`` (B21.6): CT-1 dinámico, publicación, auditoría, Study y frontera F6."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.stress as stress_pkg
import nikodym.stress.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError
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
from nikodym.forward.results import FORWARD_ECL_CONTRACT_VERSION, ForwardEclInput
from nikodym.markov.config import (
    MarkovConfig,
    MarkovDynamicsConfig,
    MarkovEstimationConfig,
    MarkovInputConfig,
    MarkovStateConfig,
)
from nikodym.stress.config import (
    ReverseStressConfig,
    SensitivitySweepConfig,
    StressConfig,
    StressInputConfig,
    StressOutputConfig,
    StressScenarioConfig,
    StressShockConfig,
    StressTargetConfig,
    StressValidationConfig,
)
from nikodym.stress.exceptions import StressDependencyError
from nikodym.stress.results import StressResult
from nikodym.stress.step import STRESS_ARTIFACTS, StressStep
from nikodym.survival.config import (
    DiscreteHazardConfig,
    SurvivalConfig,
    SurvivalInputConfig,
    SurvivalTimeGridConfig,
)

ROOT_SEED = 20_260_702

_FORWARD_TERM_COLUMNS: tuple[str, ...] = (
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
)
_SCENARIO_WEIGHT_COLUMNS: tuple[str, ...] = (
    "scenario",
    "weight",
    "is_default",
    "source",
    "description",
)


class SatelliteStub:
    """Satellite con coeficientes fijos auditables compatibles con el engine de stress."""

    coefficients_: ClassVar[dict[str, dict[str, dict[str, object]]]] = {
        "pd": {"retail": {"alpha": 0.0, "factors": {"x": 0.5}}},
        "lgd": {"retail": {"alpha": 0.0, "factors": {"x": 0.0}}},
    }


class ScenarioWeightingStub:
    """Validador forward mínimo usado por el engine."""

    def validate_macro_projection(self, frame: pd.DataFrame) -> None:
        """Comprueba que el engine entrega una copia con la columna escenario."""
        assert "scenario" in frame.columns


class EclStub:
    """Engine ECL determinista: ECL = PD marginal * LGD * 1000."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Calcula ECL por período desde el contrato forward."""
        term = ecl_input.term_structure_frame
        assert term is not None
        return pd.DataFrame(
            {
                "period": term["period"].tolist(),
                "ecl": (term["pd_marginal"].astype(float) * term["lgd"].astype(float) * 1000.0),
            }
        )


class ProvisionStub:
    """Engine de provisión determinista: 110% del ECL."""

    def calculate(self, ecl_frame: pd.DataFrame) -> pd.DataFrame:
        """Publica provisión como 110% del ECL calculado."""
        return pd.DataFrame(
            {
                "period": ecl_frame["period"].tolist(),
                "provision": ecl_frame["ecl"].astype(float) * 1.1,
            }
        )


# ─────────────────────────────── registro, CT-1 y núcleo liviano ───────────────────────────────


def test_from_config_registro_provides_emit_e_import_liviano() -> None:
    """``StressStep`` queda registrado, expone las nueve claves y no arrastra pesados."""
    cfg = _stress_cfg(metrics=("pd_marginal", "pd_cumulative"))
    step = StressStep.from_config(cfg)

    assert REGISTRY.resolve("stress", "standard") is StressStep
    assert stress_pkg.StressStep is StressStep
    assert step.config is cfg
    assert step.name == "stress"
    assert step.provides == tuple(("stress", key) for key in STRESS_ARTIFACTS)
    assert STRESS_ARTIFACTS == (
        "engine",
        "scenarios",
        "term_structure",
        "impact",
        "sensitivity",
        "reverse",
        "diagnostics",
        "result",
        "card",
    )
    assert step.requires == (
        ("forward", "macro_projection"),
        ("forward", "satellite_model"),
        ("forward", "term_structure"),
        ("forward", "scenario_weighting"),
        ("forward", "ecl_input"),
    )

    sink = InMemoryAuditSink()
    step._audit = sink
    step.emit(
        AuditEvent(kind="decision", step="stress", payload={"regla": "x"}, ts=datetime.now(UTC))
    )
    assert sink.events[-1].payload == {"regla": "x"}

    code = (
        "import nikodym.core, sys;"
        "assert 'nikodym.stress' not in sys.modules;"
        "import nikodym.stress;"
        "assert 'nikodym.stress.step' in sys.modules;"
        "assert nikodym.stress.StressStep.__name__ == 'StressStep';"
        "blocked=[m for m in ('pandas','numpy','scipy','statsmodels','nikodym.provisioning',"
        "'nikodym.stress.results','nikodym.stress.engine') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'StressStep' in nikodym.stress.__all__"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_requires_ct1_dinamico_por_metricas_y_engines() -> None:
    """``requires`` agrega engines económicos sólo cuando alguna métrica los necesita."""
    forward = (
        ("forward", "macro_projection"),
        ("forward", "satellite_model"),
        ("forward", "term_structure"),
        ("forward", "scenario_weighting"),
        ("forward", "ecl_input"),
    )
    # Forward-only: sólo los cinco artefactos forward.
    assert StressStep.from_config(_stress_cfg(metrics=("pd_marginal",))).requires == forward

    # Métrica económica pero sin engine declarado: no se puede requerir un artefacto None.
    assert StressStep.from_config(_stress_cfg(metrics=("ecl",))).requires == forward

    # Métrica ECL con engine declarado: agrega el hook ECL.
    ecl_cfg = _stress_cfg(
        metrics=("pd_marginal", "ecl"),
        input=StressInputConfig(ecl_engine_artifact=("provisioning_ifrs9", "engine")),
    )
    assert StressStep.from_config(ecl_cfg).requires == (
        *forward,
        ("provisioning_ifrs9", "engine"),
    )

    # Métrica de provisión con ambos engines: agrega ECL y provisión.
    provision_cfg = _stress_cfg(
        metrics=("provision",),
        input=StressInputConfig(
            ecl_engine_artifact=("provisioning_ifrs9", "engine"),
            provision_engine_artifact=("provisioning", "engine"),
        ),
    )
    assert StressStep.from_config(provision_cfg).requires == (
        *forward,
        ("provisioning_ifrs9", "engine"),
        ("provisioning", "engine"),
    )

    # La métrica económica puede venir de una sensibilidad o de un reverse habilitado.
    sweep_cfg = StressConfig(
        input=StressInputConfig(ecl_engine_artifact=("provisioning_ifrs9", "engine")),
        scenarios=(_scenario(),),
        sensitivities=(
            SensitivitySweepConfig(name="sw", factor="x", shock_value=1.0, metric="loss"),
        ),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=_lax_validation(),
    )
    assert ("provisioning_ifrs9", "engine") in StressStep.from_config(sweep_cfg).requires

    reverse_cfg = StressConfig(
        input=StressInputConfig(ecl_engine_artifact=("provisioning_ifrs9", "engine")),
        scenarios=(_scenario(),),
        reverse=(
            ReverseStressConfig(
                enabled=True,
                factor="x",
                shock_value=1.0,
                target=StressTargetConfig(
                    name="tgt",
                    metric="ratio",
                    threshold=0.5,
                    scenario_name="severe_plus",
                ),
            ),
            # Un reverse deshabilitado no aporta métricas ni requires.
            ReverseStressConfig(factor="x", shock_value=1.0),
        ),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=_lax_validation(),
    )
    assert ("provisioning_ifrs9", "engine") in StressStep.from_config(reverse_cfg).requires

    # Dominios/keys de entrada configurables se reflejan en el DAG.
    custom = _stress_cfg(
        metrics=("pd_marginal",),
        input=StressInputConfig(forward_domain="fwd", macro_projection_key="macro"),
    )
    assert StressStep.from_config(custom).requires[0] == ("fwd", "macro")


def test_helpers_config_y_engines_economicos() -> None:
    """Cubre resolución de config y lectura condicional de engines económicos."""
    cfg = _stress_cfg(metrics=("pd_marginal",))
    # Sección ya tipada.
    typed = SimpleNamespace(config=SimpleNamespace(stress=cfg))
    assert step_module._stress_config_from_study(typed, fallback=cfg) is cfg
    # Sección None: cae al fallback del paso.
    none_study = SimpleNamespace(config=SimpleNamespace(stress=None))
    assert step_module._stress_config_from_study(none_study, fallback=cfg) is cfg
    # Sección como mapping opaco: se coacciona vía model_validate.
    mapped = SimpleNamespace(config=SimpleNamespace(stress=cfg.model_dump(mode="json")))
    coerced = step_module._stress_config_from_study(mapped, fallback=cfg)
    assert isinstance(coerced, StressConfig)
    assert coerced.model_dump() == cfg.model_dump()

    # Lectura de engines: presentes sólo si la métrica los requiere.
    provision_cfg = _stress_cfg(
        metrics=("provision",),
        input=StressInputConfig(
            ecl_engine_artifact=("provisioning_ifrs9", "engine"),
            provision_engine_artifact=("provisioning", "engine"),
        ),
    )
    ecl_obj, provision_obj = object(), object()
    study = Study(NikodymConfig())
    study.artifacts.set("provisioning_ifrs9", "engine", ecl_obj)
    study.artifacts.set("provisioning", "engine", provision_obj)
    assert step_module._read_economic_engines(study, cfg=provision_cfg) == (ecl_obj, provision_obj)
    # Forward-only: sin engines.
    assert step_module._read_economic_engines(study, cfg=cfg) == (None, None)


# ─────────────────────────────── ejecución, CT-2 y auditoría ───────────────────────────────


def test_execute_publica_artifacts_ct2_auditoria_no_mutacion() -> None:
    """El flujo real publica nueve claves, cumple CT-2, audita y no muta forward."""
    cfg = _stress_cfg(metrics=("pd_marginal", "pd_cumulative", "ecl"), with_ecl_engine=True)
    study, macro_snapshot, term_snapshot = _stress_study(cfg, ecl_engine=EclStub())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    assert study.run(steps=["stress"]) is study

    result = study.artifacts.get("stress", "result")
    assert isinstance(result, StressResult)
    stored_keys = study.artifacts.keys()
    assert [key for key in stored_keys if key[0] == "stress"] == [
        ("stress", key) for key in STRESS_ARTIFACTS
    ]
    # CT-2: term_structure() tidy y card.metric_sections estructuradas.
    assert result.term_structure() is not None
    assert isinstance(study.artifacts.get("stress", "term_structure"), pd.DataFrame)
    assert {
        "scenario_impacts",
        "sensitivity_curves",
        "reverse_stress",
        "term_structure_summary",
        "falta_dato",
    } <= set(result.card.metric_sections)
    engine = study.artifacts.get("stress", "engine")
    assert engine.forward_hash_ is not None
    assert study.artifacts.get("stress", "sensitivity") == ()
    assert study.artifacts.get("stress", "reverse") == ()

    impact = result.tidy()
    ecl_row = impact[impact["metric"] == "ecl"].iloc[0]
    assert ecl_row["value_base"] == pytest.approx(9.0, abs=1e-10)
    assert ecl_row["value_stress"] == pytest.approx(14.6484363909, abs=1e-10)

    # Auditoría delegada al engine con step='stress'.
    rules = {
        event.payload["regla"]
        for event in sink.events
        if event.kind == "decision" and event.step == "stress"
    }
    assert {
        "stress_forward_inputs",
        "stress_scenario_config",
        "stress_dominance_check",
        "stress_macro_application",
        "stress_satellite_application",
        "stress_term_structure",
        "stress_economic_engine",
    } <= rules

    # No mutación de los artefactos forward.
    assert_frame_equal(study.artifacts.get("forward", "macro_projection"), macro_snapshot)
    assert_frame_equal(study.artifacts.get("forward", "term_structure"), term_snapshot)


def test_execute_audita_las_diez_decisiones() -> None:
    """Una config con escenario, sensibilidad, reverse y FALTA-DATO emite las diez decisiones."""
    scenario = StressScenarioConfig(
        name="severe_plus",
        base_forward_scenario="severe",
        shocks=(StressShockConfig(factor="x", value=1.0, source="official"),),
        require_dominates_forward_adverse=True,
    )
    sweep = SensitivitySweepConfig(
        name="sw",
        factor="x",
        shock_value=1.0,
        severity_grid=(0.0, 1.0, 2.0),
        metric="pd_cumulative",
    )
    reverse = ReverseStressConfig(
        enabled=True,
        factor="x",
        shock_value=1.0,
        bracket=(0.0, 5.0),
        target=StressTargetConfig(
            name="tgt",
            metric="pd_cumulative",
            threshold=0.05,
            direction="at_least",
            scenario_name="severe_plus",
            requires_economic_engine=False,
        ),
    )
    cfg = StressConfig(
        scenarios=(scenario,),
        sensitivities=(sweep,),
        reverse=(reverse,),
        output=StressOutputConfig(metrics=("pd_marginal", "pd_cumulative")),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=True,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    study, _, _ = _stress_study(cfg, hazards=[0.02, 0.03], periods=(1, 2))
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    study.run(steps=["stress"])

    rules = {
        event.payload["regla"]
        for event in sink.events
        if event.kind == "decision" and event.step == "stress"
    }
    assert {
        "stress_forward_inputs",
        "stress_scenario_config",
        "stress_dominance_check",
        "stress_macro_application",
        "stress_satellite_application",
        "stress_term_structure",
        "stress_economic_engine",
        "stress_sensitivity",
        "stress_reverse",
        "stress_falta_dato",
    } <= rules
    result = study.artifacts.get("stress", "result")
    assert result.diagnostics.sensitivity_count == 1
    assert result.diagnostics.reverse_count == 1
    assert study.artifacts.get("stress", "reverse")[0].converged


def test_execute_sin_publicar_term_structure() -> None:
    """Con ``publish_stressed_term_structure=False`` la clave publica ``None``."""
    cfg = _stress_cfg(
        metrics=("pd_marginal",),
        output=StressOutputConfig(
            metrics=("pd_marginal",),
            publish_stressed_term_structure=False,
        ),
    )
    study, _, _ = _stress_study(cfg)

    study.run(steps=["stress"])

    assert study.artifacts.has("stress", "term_structure")
    assert study.artifacts.get("stress", "term_structure") is None
    assert study.artifacts.get("stress", "result").term_structure() is None


def test_determinismo_byte_equivalente() -> None:
    """Dos corridas con los mismos frames/config producen salidas idénticas."""
    cfg = _stress_cfg(metrics=("pd_marginal", "pd_cumulative", "ecl"), with_ecl_engine=True)
    first = _run_stress(cfg, ecl_engine=EclStub())
    second = _run_stress(cfg, ecl_engine=EclStub())

    assert_frame_equal(first.tidy(), second.tidy())
    assert_frame_equal(first.term_structure(), second.term_structure())
    assert_frame_equal(first.scenarios(), second.scenarios())
    assert first.diagnostics == second.diagnostics
    assert first.card == second.card


def test_ct1_falta_forward_y_ecl_input_incompatible() -> None:
    """CT-1 exige artefactos forward; un contrato ECL incompatible falla como dependencia."""
    cfg = _stress_cfg(metrics=("pd_marginal",))
    empty_study = Study(NikodymConfig(stress=cfg))
    with pytest.raises(ArtifactNotFoundError, match=r"\('forward', 'macro_projection'\)"):
        StressStep.from_config(cfg).execute(empty_study, np.random.default_rng(ROOT_SEED))

    study, _, _ = _stress_study(cfg)
    term = _forward_term_structure([0.02])
    study.artifacts.set(
        "forward",
        "ecl_input",
        _ecl_input(term, contract_version="incompatible"),
        overwrite=True,
    )
    with pytest.raises(StressDependencyError, match="contract_version"):
        StressStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))


def test_study_end_to_end_survival_markov_forward_stress(tmp_path: Path) -> None:
    """``Study`` encadena survival + markov + forward + stress y publica el resultado stress."""
    coefficients = _coefficient_table(tmp_path)
    study = Study(
        NikodymConfig(
            survival=_survival_cfg(),
            markov=_markov_cfg(),
            forward=_forward_cfg(coefficients),
            stress=_stress_cfg(metrics=("pd_marginal", "pd_cumulative")),
        )
    )
    frame = _study_frame()
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("model", "raw_pd_frame", _pd_frame(frame.index))
    study.artifacts.set("forward", "macro_history", _macro_history())

    study.run(steps=["survival", "markov", "forward", "stress"])

    result = study.artifacts.get("stress", "result")
    assert isinstance(result, StressResult)
    assert result.diagnostics.scenario_count == 1
    assert result.term_structure() is not None
    assert sorted(set(result.tidy()["metric"])) == ["pd_cumulative", "pd_marginal"]
    stored_keys = study.artifacts.keys()
    assert [key for key in stored_keys if key[0] == "stress"] == [
        ("stress", key) for key in STRESS_ARTIFACTS
    ]


def test_step_no_declara_metricas_frontera_sdd22() -> None:
    """El paso no implementa métricas de validación/backtesting (frontera SDD-22/F6)."""
    assert step_module.__file__ is not None
    source = Path(step_module.__file__).read_text(encoding="utf-8").lower()
    forbidden = ("roc", "auc", "gini", "ks", "psi", "hosmer", "lemeshow", "brier")
    found = [token for token in forbidden if re.search(rf"\b{token}\b", source)]
    assert not found, f"nombres de métricas SDD-22 en step.py: {found}"


# ─────────────────────────────── helpers ───────────────────────────────


def _lax_validation() -> StressValidationConfig:
    """Validación permisiva para tests que no ejercen dominancia ni FALTA-DATO."""
    return StressValidationConfig(
        require_dominates_forward_adverse=False,
        fail_on_falta_dato=False,
        fail_on_missing_ecl_engine=True,
    )


def _scenario() -> StressScenarioConfig:
    """Escenario severo canónico con un shock aditivo sobre ``x``."""
    return StressScenarioConfig(
        name="severe_plus",
        base_forward_scenario="severe",
        shocks=(StressShockConfig(factor="x", value=1.0),),
        require_dominates_forward_adverse=False,
    )


def _stress_cfg(
    *,
    metrics: tuple[str, ...],
    input: StressInputConfig | None = None,
    output: StressOutputConfig | None = None,
    with_ecl_engine: bool = False,
) -> StressConfig:
    """Config stress mínimo con un escenario severo determinista."""
    input_cfg = input
    if input_cfg is None and with_ecl_engine:
        input_cfg = StressInputConfig(ecl_engine_artifact=("provisioning_ifrs9", "engine"))
    return StressConfig(
        input=input_cfg or StressInputConfig(),
        scenarios=(_scenario(),),
        output=output or StressOutputConfig(metrics=metrics),  # type: ignore[arg-type]
        validation=_lax_validation(),
    )


def _macro_projection(periods: tuple[int, ...] = (1,)) -> pd.DataFrame:
    """Proyección macro con escenarios adverse y severe deterministas."""
    rows: list[dict[str, Any]] = []
    for scenario in ("adverse", "severe"):
        for period in periods:
            projected = 1.0 if scenario == "adverse" else 0.0
            rows.append(
                {
                    "scenario": scenario,
                    "scenario_weight": 1.0,
                    "period": period,
                    "time_value": float(period),
                    "macro_variable": "x",
                    "projected_value": projected,
                    "model_value": 0.0,
                    "shock_value": projected,
                    "method": "test",
                    "model_id": "macro:test",
                    "is_reasonable_supportable": True,
                    "warning_codes": (),
                }
            )
    return pd.DataFrame(rows)


def _forward_term_structure(hazards: list[float]) -> pd.DataFrame:
    """Term-structure forward-looking severa compatible con el engine de stress."""
    rows: list[dict[str, Any]] = []
    previous_survival = 1.0
    for period, hazard in enumerate(hazards, start=1):
        pd_marginal = previous_survival * hazard
        survival = previous_survival * (1.0 - hazard)
        pd_cumulative = 1.0 - survival
        rows.append(
            {
                "row_id": "id-1",
                "segment": "retail",
                "partition": "desarrollo",
                "source_model": "survival",
                "period": period,
                "time_value": float(period),
                "scenario": "severe",
                "scenario_weight": 1.0,
                "hazard": hazard,
                "survival": survival,
                "pd_marginal": pd_marginal,
                "pd_cumulative": pd_cumulative,
                "pd_marginal_base": pd_marginal,
                "pd_cumulative_base": pd_cumulative,
                "lgd": 0.45,
                "lgd_base": 0.45,
                "pd_basis": "pit",
                "basis_state": "pit",
                "ttc_reversion_weight": 1.0,
                "satellite_adjustment": 0.0,
                "macro_model_id": "macro:test",
                "satellite_model_id": "sat:test",
                "method": "survival",
                "pd_source": "survival",
                "warning_codes": (),
            }
        )
        previous_survival = survival
    return pd.DataFrame(rows, columns=_FORWARD_TERM_COLUMNS)


def _ecl_input(
    term: pd.DataFrame,
    *,
    contract_version: str = FORWARD_ECL_CONTRACT_VERSION,
) -> ForwardEclInput:
    """Contrato ``ForwardEclInput`` mínimo consistente con la term-structure severa."""
    return ForwardEclInput(
        term_structure_frame=term,
        scenario_weight_frame=pd.DataFrame(
            [
                {
                    "scenario": name,
                    "weight": 1.0 if name == "severe" else 0.0,
                    "is_default": False,
                    "source": "config",
                    "description": name,
                }
                for name in ("base", "adverse", "severe")
            ],
            columns=_SCENARIO_WEIGHT_COLUMNS,
        ),
        pit_consistency={"basis": "pit"},
        contract_version=contract_version,
    )


def _stress_study(
    cfg: StressConfig,
    *,
    hazards: list[float] | None = None,
    periods: tuple[int, ...] = (1,),
    ecl_engine: object | None = None,
) -> tuple[Study, pd.DataFrame, pd.DataFrame]:
    """Arma un ``Study`` con artefactos forward sintéticos y devuelve snapshots profundos."""
    term = _forward_term_structure(hazards if hazards is not None else [0.02])
    macro = _macro_projection(periods)
    study = Study(NikodymConfig(stress=cfg))
    study.artifacts.set("forward", "macro_projection", macro)
    study.artifacts.set("forward", "satellite_model", SatelliteStub())
    study.artifacts.set("forward", "term_structure", term)
    study.artifacts.set("forward", "scenario_weighting", ScenarioWeightingStub())
    study.artifacts.set("forward", "ecl_input", _ecl_input(term))
    if ecl_engine is not None:
        study.artifacts.set("provisioning_ifrs9", "engine", ecl_engine)
    return study, macro.copy(deep=True), term.copy(deep=True)


def _run_stress(cfg: StressConfig, *, ecl_engine: object | None = None) -> StressResult:
    """Ejecuta ``StressStep`` directamente y devuelve el ``StressResult``."""
    study, _, _ = _stress_study(cfg, ecl_engine=ecl_engine)
    return StressStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))


def _scenario_def(name: str, weight: float, shock: float = 0.0) -> ScenarioDefinitionConfig:
    """Escenario forward con descripción auditable requerida por el contrato ECL."""
    shocks = {} if name == "base" else {"x": shock}
    return ScenarioDefinitionConfig(
        name=name,
        weight=weight,
        shocks=shocks,
        description=name,
    )


def _forward_cfg(coefficient_path: Path) -> ForwardConfig:
    """Config forward mínimo, determinista y con coeficientes satellite fijos."""
    return ForwardConfig(
        input=ForwardInputConfig(
            macro_source=MacroSourceConfig(
                type="artifact",
                variable_cols=("x",),
                artifact_domain="forward",
                artifact_key="macro_history",
            ),
            term_structure_sources=("survival", "markov"),
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
                _scenario_def("base", 0.60),
                _scenario_def("adverse", 0.30, 0.50),
                _scenario_def("severe", 0.10, 1.00),
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
    """Frame de PD cruda requerido por ``SurvivalStep`` aunque ``pd_source='none'``."""
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
