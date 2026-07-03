"""Motor determinista de stress testing severo (SDD-21 B21.3/B21.4).

El módulo implementa los contratos ejecutables de ``stress``: escenarios severos, shocks macro,
propagación satellite en escala logit, métricas forward/ECL/provisión básicas (B21.3) y barridos
deterministas de sensibilidad por factor (B21.4). El reverse stress queda como error explícito
hasta B21.5.

No importa ``pandas``, ``numpy`` ni motores de provisión al cargar el módulo. Esas dependencias se
cargan perezosamente dentro de los métodos de ejecución.

**Experimental (SemVer 0.x).**
"""

# ruff: noqa: UP037

from __future__ import annotations

import copy
import functools
import hashlib
import importlib
import json
import math
import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, is_dataclass, replace
from dataclasses import fields as dataclass_fields
from datetime import UTC, date, datetime, time
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from numbers import Integral, Real
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    Protocol,
    TypeAlias,
    cast,
    runtime_checkable,
)

from nikodym.forward.results import FORWARD_ECL_CONTRACT_VERSION
from nikodym.stress.config import (
    ReverseStressConfig,
    SensitivitySweepConfig,
    StressConfig,
    StressMetric,
    StressScenarioConfig,
    StressShockConfig,
    StressTargetConfig,
)
from nikodym.stress.exceptions import (
    NonMonotonicStressError,
    ReverseStressError,
    StressDependencyError,
    StressEngineError,
    StressFaltaDatoError,
    StressInputError,
    StressOutputError,
    StressScenarioError,
)
from nikodym.stress.results import (
    ReverseStressResult,
    StressCard,
    StressDiagnostics,
    StressResult,
    StressScenarioResult,
    StressSensitivityResult,
)

if TYPE_CHECKING:
    import pandas

    from nikodym.core.audit import AuditSink
    from nikodym.forward.results import ForwardEclInput

    DataFrame: TypeAlias = pandas.DataFrame
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    ForwardEclInput: TypeAlias = Any

__all__ = ["EclEngineLike", "ProvisionEngineLike", "StressTestEngine"]

_SCENARIO_FRAME_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "base_forward_scenario",
    "severity",
    "macro_variable",
    "operation",
    "shock_value",
    "applied_shock",
    "period",
    "source",
    "warning_codes",
)
_STRESS_TERM_STRUCTURE_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "severity",
    "base_forward_scenario",
    "row_id",
    "segment",
    "partition",
    "source_model",
    "method",
    "pd_source",
    "period",
    "time_value",
    "macro_variable_set",
    "hazard_base",
    "hazard_stress",
    "survival_stress",
    "pd_marginal_base",
    "pd_marginal_stress",
    "pd_cumulative_base",
    "pd_cumulative_stress",
    "lgd_base",
    "lgd_stress",
    "pd_basis",
    "basis_state",
    "satellite_adjustment_base",
    "satellite_adjustment_stress",
    "warning_codes",
)
_IMPACT_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "severity",
    "metric",
    "value_base",
    "value_stress",
    "absolute_delta",
    "relative_delta",
    "group_key",
    "period",
    "engine_source",
    "warning_codes",
)
_SCENARIO_WEIGHT_COLUMNS: tuple[str, ...] = (
    "scenario",
    "weight",
    "is_default",
    "source",
    "description",
)
_MACRO_PROJECTION_REQUIRED_COLUMNS: tuple[str, ...] = (
    "scenario",
    "scenario_weight",
    "period",
    "time_value",
    "macro_variable",
    "projected_value",
    "model_value",
    "shock_value",
    "method",
    "model_id",
    "is_reasonable_supportable",
    "warning_codes",
)
_MACRO_PROJECTION_HASH_KEY_COLUMNS: tuple[str, ...] = (
    "scenario",
    "macro_variable",
    "period",
)
_FORWARD_TERM_STRUCTURE_REQUIRED_COLUMNS: tuple[str, ...] = (
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
_FORWARD_TERM_STRUCTURE_OPTIONAL_LGD_COLUMNS: tuple[str, ...] = ("lgd", "lgd_base")
_FORWARD_TERM_STRUCTURE_OPTIONAL_KEY_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "partition",
)
_FORWARD_TERM_METADATA_COLUMNS: tuple[str, ...] = (
    "source_model",
    "method",
    "pd_source",
    "pd_basis",
    "basis_state",
)
_FORWARD_TERM_TEXT_COLUMNS: tuple[str, ...] = (
    "scenario",
    *_FORWARD_TERM_METADATA_COLUMNS,
)
_FORWARD_TERM_REQUIRED_PROBABILITY_COLUMNS: tuple[str, ...] = (
    "scenario_weight",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "pd_marginal_base",
    "pd_cumulative_base",
)
_FORWARD_TERM_OPTIONAL_PROBABILITY_COLUMNS: tuple[str, ...] = (
    "lgd",
    "lgd_base",
    "ttc_reversion_weight",
)
_FORWARD_TERM_FLOAT_COLUMNS: tuple[str, ...] = ("time_value",)
_FORWARD_TERM_OPTIONAL_FLOAT_COLUMNS: tuple[str, ...] = ("satellite_adjustment",)
_FORWARD_TERM_STRUCTURE_COLUMNS: tuple[str, ...] = (
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
_FORWARD_TERM_HASH_KEY_COLUMNS: tuple[str, ...] = (
    "scenario",
    "row_id",
    "segment",
    "partition",
    "source_model",
    "method",
    "pd_source",
    "period",
)
_SCENARIO_WEIGHT_HASH_KEY_COLUMNS: tuple[str, ...] = ("scenario",)
_FORWARD_ONLY_METRICS: frozenset[str] = frozenset({"pd_marginal", "pd_cumulative", "lgd"})
_ECL_METRICS: frozenset[str] = frozenset({"ecl", "loss", "ratio"})
_PROVISION_METRICS: frozenset[str] = frozenset({"provision"})
_ECONOMIC_METRICS: frozenset[str] = _ECL_METRICS | _PROVISION_METRICS
_METRIC_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "ecl": ("ecl", "expected_credit_loss", "expected_loss"),
    "loss": ("loss", "expected_loss", "ecl"),
    "ratio": ("ratio", "coverage_ratio", "ecl_ratio"),
    "provision": ("provision", "provision_amount", "required_provision"),
}
_ECONOMIC_GROUP_EXCLUDED_COLUMNS: frozenset[str] = frozenset(
    {
        "period",
        "scenario",
        "scenario_weight",
        "weight",
        "warning_codes",
        *(column for aliases in _METRIC_COLUMNS.values() for column in aliases),
    }
)
_ECONOMIC_GROUP_DIMENSION_COLUMNS: frozenset[str] = frozenset(
    {
        "account_id",
        "bucket",
        "contract_id",
        "country",
        "currency",
        "customer_id",
        "entity_id",
        "exposure_id",
        "facility_id",
        "grade",
        "lgd_band",
        "loan_id",
        "method",
        "obligor_id",
        "partition",
        "pd_band",
        "pd_source",
        "portfolio",
        "product",
        "product_type",
        "rating",
        "region",
        "risk_grade",
        "row_id",
        "score_band",
        "segment",
        "source_model",
        "stage",
    }
)
_ECONOMIC_ENGINE_MEASURE_COLUMNS: frozenset[str] = frozenset(
    {
        "balance",
        "balance_outstanding",
        "ead",
        "ead_base",
        "exposure",
        "exposure_at_default",
        "lgd",
        "lgd_base",
        "outstanding_balance",
        "pd",
        "pd_cumulative",
        "pd_cumulative_base",
        "pd_marginal",
        "pd_marginal_base",
    }
)
_SEGMENT_ALL = "__all__"
_FALTA_DATO_DOMINANCE = "FALTA-DATO-STR-1"
_FALTA_DATO_OFFICIAL = "FALTA-DATO-STR-2"
_WARNING_MISSING_ECL = "FALTA-DATO-STR-5"
_FALTA_DATO_LGD = "FALTA-DATO-STR-LGD"
_FORWARD_ECL_CONTRACT_VERSION = FORWARD_ECL_CONTRACT_VERSION
_FORWARD_ECL_CHAIN = (
    "macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting"
)
_STRESS_ENGINE_VERSION = "B21.4"
_SENSITIVITY_BASELINE_COLUMNS: tuple[str, ...] = (
    "sweep_name",
    "factor",
    "metric",
    "engine_source",
    "group_key",
    "period_label",
    "value_base",
)
_REVERSE_PATH_COLUMNS: tuple[str, ...] = (
    "target_name",
    "iteration",
    "lo",
    "hi",
    "mid",
    "metric_value",
    "threshold",
    "decision",
)
_RESERVED_SCENARIO_NAMES = frozenset({"mean", "average", "weighted_mean_input"})
_WEIGHTED_MEAN_INPUT_COLUMN = "weighted_mean_input"
_RUNTIME_STATE_ATTRIBUTE_NAMES = frozenset(
    {
        "calls",
        "call_count",
        "events",
        "weight_calls",
    }
)
_FLOAT_ATOL = 1e-12
_NUMPY_NON_SCALAR = object()


@runtime_checkable
class EclEngineLike(Protocol):
    """Contrato mínimo del engine ECL futuro sin import duro de SDD-16."""

    def calculate(self, ecl_input: "ForwardEclInput") -> "pandas.DataFrame":
        """Calcula ECL desde un ``ForwardEclInput`` compatible."""
        ...


@runtime_checkable
class ProvisionEngineLike(Protocol):
    """Contrato mínimo del engine de provisiones futuro sin import duro de SDD-17."""

    def calculate(self, ecl_frame: "pandas.DataFrame") -> "pandas.DataFrame":
        """Calcula provisiones desde el frame ECL ya calculado."""
        ...


@dataclass(frozen=True)
class _RunContext:
    macro_projection: DataFrame
    forward_term_structure: DataFrame
    forward_ecl_input: ForwardEclInput
    satellite_model: object
    scenario_weighting: object
    ecl_engine: EclEngineLike | None
    provision_engine: ProvisionEngineLike | None
    audit: AuditSink | None
    pd: Any


@dataclass(frozen=True)
class _MacroStressResult:
    scenario_frame: DataFrame
    projection_frame: DataFrame
    delta_lookup: dict[tuple[int, str], float]
    macro_variable_set: tuple[str, ...]
    warning_codes: tuple[str, ...]


@dataclass(frozen=True)
class _TermStructureStressResult:
    stress_term_structure: DataFrame
    forward_ecl_term_structure: DataFrame


@dataclass(frozen=True)
class _SatelliteAdjustmentResult:
    adjustment: float
    contributions: tuple[dict[str, Any], ...]


class StressTestEngine:
    """Ejecutor determinista de escenarios severos de stress testing."""

    config_cls: ClassVar[type[StressConfig]] = StressConfig

    def __init__(self, *, config: StressConfig) -> None:
        """Asigna configuración sin cargar dependencias pesadas."""
        self.config = config
        self._reset_run_state()

    def _reset_run_state(self) -> None:
        """Limpia todo estado derivado de una corrida anterior."""
        self.forward_hash_: str | None = None
        self.config_hash_: str | None = None
        self.scenario_results_: tuple[StressScenarioResult, ...] = ()
        self.sensitivity_results_: tuple[StressSensitivityResult, ...] = ()
        self.reverse_results_: tuple[ReverseStressResult, ...] = ()
        self.diagnostics_: StressDiagnostics | None = None
        self.dependency_versions_: dict[str, str] = {}
        self.run_started_at_: datetime | None = None
        self._context: _RunContext | None = None

    @classmethod
    def from_config(cls, cfg: StressConfig | Mapping[str, Any]) -> StressTestEngine:
        """Construye el engine desde ``StressConfig`` o mapping equivalente."""
        validated = cfg if isinstance(cfg, StressConfig) else StressConfig.model_validate(cfg)
        return cls(config=validated)

    def run(
        self,
        *,
        forward_ecl_input: "ForwardEclInput",
        macro_projection: "pandas.DataFrame",
        satellite_model: object,
        forward_term_structure: "pandas.DataFrame",
        scenario_weighting: object,
        ecl_engine: "EclEngineLike | None" = None,
        provision_engine: "ProvisionEngineLike | None" = None,
        audit: "AuditSink | None" = None,
    ) -> StressResult:
        """Ejecuta escenarios severos y retorna ``StressResult`` CT-2."""
        self._reset_run_state()
        try:
            return self._run(
                forward_ecl_input=forward_ecl_input,
                macro_projection=macro_projection,
                satellite_model=satellite_model,
                forward_term_structure=forward_term_structure,
                scenario_weighting=scenario_weighting,
                ecl_engine=ecl_engine,
                provision_engine=provision_engine,
                audit=audit,
            )
        except Exception:
            self._reset_run_state()
            raise

    def _run(
        self,
        *,
        forward_ecl_input: "ForwardEclInput",
        macro_projection: "pandas.DataFrame",
        satellite_model: object,
        forward_term_structure: "pandas.DataFrame",
        scenario_weighting: object,
        ecl_engine: "EclEngineLike | None" = None,
        provision_engine: "ProvisionEngineLike | None" = None,
        audit: "AuditSink | None" = None,
    ) -> StressResult:
        """Ejecuta con estado limpio; ``run`` gestiona reset ante fallos."""
        pd = _import_pandas()
        _reject_deferred_features(self.config)
        macro = _as_dataframe(macro_projection, pd=pd, field_name="macro_projection")
        macro = _canonicalize_macro_projection(macro, pd=pd)
        term = _as_dataframe(
            forward_term_structure,
            pd=pd,
            field_name="forward_term_structure",
        )
        term = _canonicalize_forward_term_structure(
            term,
            cfg=self.config,
            field_name="forward_term_structure",
            pd=pd,
        )
        _validate_economic_engines(
            self.config,
            ecl_engine=ecl_engine,
            provision_engine=provision_engine,
            audit=audit,
        )
        _validate_run_inputs(
            macro,
            term,
            self.config,
            pd=pd,
        )
        _validate_forward_ecl_input_contract(
            forward_ecl_input,
            cfg=self.config,
            pd=pd,
        )
        _validate_forward_ecl_input_matches_forward_artifacts(
            forward_ecl_input,
            forward_term_structure=term,
            cfg=self.config,
            pd=pd,
        )

        self.run_started_at_ = datetime.now(tz=UTC)
        lineage_components = _run_lineage_components(
            macro_projection=macro,
            forward_term_structure=term,
            forward_ecl_input=forward_ecl_input,
            satellite_model=satellite_model,
            scenario_weighting=scenario_weighting,
            ecl_engine=ecl_engine,
            provision_engine=provision_engine,
            cfg=self.config,
            pd=pd,
        )
        self.forward_hash_ = _canonical_hash(
            {
                "schema": "nikodym.stress.forward_hash.v2",
                "components": lineage_components,
            },
            pd=pd,
        )
        self.config_hash_ = _config_digest(self.config)
        self.dependency_versions_ = _dependency_versions()
        _validate_scenario_weighting_contract(scenario_weighting, macro)
        self._context = _RunContext(
            macro_projection=macro,
            forward_term_structure=term,
            forward_ecl_input=copy.deepcopy(forward_ecl_input),
            satellite_model=satellite_model,
            scenario_weighting=scenario_weighting,
            ecl_engine=ecl_engine,
            provision_engine=provision_engine,
            audit=audit,
            pd=pd,
        )
        _emit_audit_decision(
            audit,
            regla="stress_forward_inputs",
            umbral={
                "scenario_count": len(self.config.scenarios),
                "metrics": tuple(self.config.output.metrics),
            },
            valor={
                "forward_hash": self.forward_hash_,
                "config_hash": self.config_hash_,
                "macro_rows": len(macro.index),
                "term_structure_rows": len(term.index),
                "contract_version": getattr(forward_ecl_input, "contract_version", None),
                "lineage_components": lineage_components,
            },
            accion="run",
        )
        _emit_size_estimate(
            audit,
            cfg=self.config,
            macro_rows=len(macro.index),
            term_structure_rows=len(term.index),
        )

        scenario_results = tuple(
            self.run_scenario(scenario, severity=scenario.severity)
            for scenario in self.config.scenarios
        )
        self.scenario_results_ = scenario_results

        _validate_unique_sensitivity_names(self.config)
        sensitivity_results: list[StressSensitivityResult] = []
        sensitivity_frames: list[DataFrame] = []
        sensitivity_warnings: list[str] = []
        for sweep in self.config.sensitivities:
            sweep_result, sweep_warnings = self._run_sensitivity(sweep)
            sensitivity_results.append(sweep_result)
            sensitivity_frames.append(sweep_result.sensitivity_frame)
            sensitivity_warnings.extend(sweep_warnings)
        self.sensitivity_results_ = tuple(sensitivity_results)
        reverse_results = tuple(
            self.run_reverse_stress(cast("StressTargetConfig", reverse.target), reverse)
            for reverse in self.config.reverse
            if reverse.enabled
        )
        self.reverse_results_ = reverse_results

        stress_scenario_frame = _concat_required_frames(
            tuple(result.scenario_frame for result in scenario_results),
            columns=_SCENARIO_FRAME_COLUMNS,
            pd=pd,
        )
        stress_term_structure: DataFrame | None = _concat_optional_frames(
            tuple(result.stressed_term_structure_frame for result in scenario_results),
            columns=_STRESS_TERM_STRUCTURE_COLUMNS,
            pd=pd,
        )
        if not self.config.output.publish_stressed_term_structure:
            stress_term_structure = None
        stress_impact = _concat_required_frames(
            (
                *tuple(result.impact_frame for result in scenario_results),
                *tuple(sensitivity_frames),
            ),
            columns=_IMPACT_COLUMNS,
            pd=pd,
        )
        warning_codes = _dedupe_iterable(
            (
                *(code for result in scenario_results for code in result.warning_codes),
                *sensitivity_warnings,
            )
        )
        falta_dato_codes = tuple(
            code for code in warning_codes if code.startswith("FALTA-DATO-STR")
        )
        diagnostics = StressDiagnostics(
            scenario_count=len(scenario_results),
            sensitivity_count=len(sensitivity_results),
            reverse_count=len(reverse_results),
            falta_dato_codes=falta_dato_codes,
            warning_codes=warning_codes,
            dependency_versions=self.dependency_versions_,
        )
        card = _build_card(
            scenario_results=scenario_results,
            sensitivity_results=tuple(sensitivity_results),
            reverse_results=reverse_results,
            stress_impact=stress_impact,
            stress_scenarios=stress_scenario_frame,
            stress_term_structure=stress_term_structure,
            diagnostics=diagnostics,
        )
        result = StressResult(
            scenario_results=scenario_results,
            sensitivity_results=tuple(sensitivity_results),
            reverse_results=reverse_results,
            publish_stressed_term_structure=self.config.output.publish_stressed_term_structure,
            stress_scenario_frame=stress_scenario_frame,
            stress_term_structure_frame=stress_term_structure,
            stress_impact_frame=stress_impact,
            diagnostics=diagnostics,
            card=card,
        )
        self.diagnostics_ = diagnostics
        _emit_audit_decision(
            audit,
            regla="stress_result",
            umbral={
                "scenario_count": diagnostics.scenario_count,
                "sensitivity_count": diagnostics.sensitivity_count,
            },
            valor={
                "scenario_rows": len(stress_scenario_frame.index),
                "impact_rows": len(stress_impact.index),
                "sensitivity_rows": sum(len(frame.index) for frame in sensitivity_frames),
                "term_structure_rows": 0
                if stress_term_structure is None
                else len(stress_term_structure.index),
                "warning_codes": diagnostics.warning_codes,
                "falta_dato_codes": diagnostics.falta_dato_codes,
            },
            accion="publish",
        )
        return result

    def run_scenario(
        self,
        scenario: StressScenarioConfig,
        *,
        severity: float = 1.0,
    ) -> StressScenarioResult:
        """Ejecuta un escenario/severidad sobre el contexto cargado por ``run``."""
        return self._run_scenario(
            scenario,
            severity=severity,
            metrics=tuple(self.config.output.metrics),
        )

    def _run_scenario(
        self,
        scenario: StressScenarioConfig,
        *,
        severity: float,
        metrics: tuple[StressMetric, ...],
    ) -> StressScenarioResult:
        """Ejecuta un escenario para el conjunto de métricas efectivas indicado."""
        context = self._require_context()
        severity_value = _non_negative_float(severity, field_name="severity")
        _emit_scenario_config(context.audit, scenario=scenario, severity=severity_value)
        macro_result = _apply_macro_shocks(
            scenario,
            severity=severity_value,
            macro_projection=context.macro_projection,
            forward_term_structure=context.forward_term_structure,
            cfg=self.config,
            pd=context.pd,
            audit=context.audit,
        )
        _emit_audit_decision(
            context.audit,
            regla="stress_macro_application",
            umbral={
                "scenario": scenario.name,
                "severity": severity_value,
                "factors": macro_result.macro_variable_set,
            },
            valor={
                "shock_rows": len(macro_result.scenario_frame.index),
                "projection_rows": len(macro_result.projection_frame.index),
                "warning_codes": macro_result.warning_codes,
            },
            accion="apply",
        )
        term_result = _apply_satellite_stress(
            scenario,
            severity=severity_value,
            macro_result=macro_result,
            forward_term_structure=context.forward_term_structure,
            satellite_model=context.satellite_model,
            cfg=self.config,
            pd=context.pd,
            audit=context.audit,
        )
        term_warning_codes = _frame_warning_codes(term_result.stress_term_structure)
        impact_warning_codes = _dedupe((*macro_result.warning_codes, *term_warning_codes))
        impact_frame, economic_warnings = _build_impact_frame(
            scenario,
            severity=severity_value,
            stress_term_structure=term_result.stress_term_structure,
            forward_ecl_term_structure=term_result.forward_ecl_term_structure,
            context=context,
            cfg=self.config,
            metrics=metrics,
            macro_warning_codes=impact_warning_codes,
            pd=context.pd,
        )
        warning_codes = _dedupe(
            (*macro_result.warning_codes, *term_warning_codes, *economic_warnings)
        )
        _emit_audit_decision(
            context.audit,
            regla="stress_economic_engine",
            umbral={
                "scenario": scenario.name,
                "metrics": tuple(metrics),
            },
            valor={
                "engine_source": tuple(dict.fromkeys(impact_frame["engine_source"].tolist())),
                "impact_rows": len(impact_frame.index),
                "warning_codes": warning_codes,
            },
            accion="calculate",
        )
        return StressScenarioResult(
            scenario_name=scenario.name,
            scenario_kind=scenario.kind,
            severity=severity_value,
            scenario_frame=macro_result.scenario_frame,
            stressed_macro_frame=(
                macro_result.projection_frame if self.config.output.publish_stressed_macro else None
            ),
            stressed_term_structure_frame=(
                term_result.stress_term_structure
                if self.config.output.publish_stressed_term_structure
                else None
            ),
            impact_frame=impact_frame,
            warning_codes=warning_codes,
        )

    def run_sensitivity(self, sweep: SensitivitySweepConfig) -> StressSensitivityResult:
        """Ejecuta un barrido determinista de sensibilidad de un factor (SDD-21 §3/§7 B21.4).

        Fija ``sweep.factor`` y recorre la grilla ordenada de severidades llamando ``run_scenario``
        por severidad. La métrica ``sweep.metric`` se reagrega según ``sweep.group_cols`` antes de
        calcular ``Sensitivity(j, a) = M(x + a·δ) - M(x)`` y la monotonicidad. Exige haber
        ejecutado ``run(...)`` para cargar el contexto forward.
        """
        result, _ = self._run_sensitivity(sweep)
        return result

    def _run_sensitivity(
        self,
        sweep: SensitivitySweepConfig,
    ) -> tuple[StressSensitivityResult, tuple[str, ...]]:
        """Ejecuta el barrido y devuelve el resultado más los warnings acumulados."""
        context = self._require_context()
        scenario = _sensitivity_scenario(sweep)
        grid = tuple(
            _non_negative_float(value, field_name="sensitivity.severity_grid")
            for value in sweep.severity_grid
        )
        per_severity: list[tuple[float, list[dict[str, Any]]]] = []
        warnings_seen: list[str] = []
        for severity in grid:
            scenario_result = self._run_scenario(
                scenario,
                severity=severity,
                metrics=(sweep.metric,),
            )
            warnings_seen.extend(scenario_result.warning_codes)
            metric_rows = [
                row
                for row in _iter_impact_rows(scenario_result.impact_frame)
                if row["metric"] == sweep.metric
            ]
            per_severity.append((severity, _aggregate_sweep_impacts(metric_rows, sweep=sweep)))
        sensitivity_frame = _sensitivity_frame(per_severity, sweep=sweep, pd=context.pd)
        baseline_frame = _sensitivity_baseline_frame(per_severity, sweep=sweep, pd=context.pd)
        monotonicity_flag = _sweep_monotonicity_flag(
            per_severity,
            tol=self.config.validation.metric_tol,
        )
        engine_sources = _dedupe_iterable(
            row["engine_source"] for _, rows in per_severity for row in rows
        )
        warning_codes = _dedupe(warnings_seen)
        blocked = sweep.require_monotonic and monotonicity_flag == "non_monotonic"
        _emit_audit_decision(
            context.audit,
            regla="stress_sensitivity",
            umbral={
                "sweep": sweep.name,
                "factor": sweep.factor,
                "metric": sweep.metric,
                "group_cols": tuple(sweep.group_cols),
                "require_monotonic": sweep.require_monotonic,
            },
            valor={
                "severity_grid": grid,
                "monotonicity_flag": monotonicity_flag,
                "n_sensitivity_evaluations": len(grid),
                "sensitivity_rows": len(sensitivity_frame.index),
                "engine_sources": engine_sources,
                "warning_codes": warning_codes,
            },
            accion="block" if blocked else "evaluate",
        )
        if blocked:
            raise NonMonotonicStressError(
                f"El barrido {sweep.name!r} sobre {sweep.factor!r} no es monotónico en la métrica "
                f"{sweep.metric!r}; grilla evaluada={grid}, flag={monotonicity_flag!r}."
            )
        result = StressSensitivityResult(
            sweep_name=sweep.name,
            factor=sweep.factor,
            severity_grid=grid,
            sensitivity_frame=sensitivity_frame,
            baseline_metric_frame=baseline_frame,
            monotonicity_flag=monotonicity_flag,
        )
        return result, warning_codes

    def run_reverse_stress(
        self,
        target: StressTargetConfig,
        reverse: ReverseStressConfig,
    ) -> ReverseStressResult:
        """Resuelve la severidad mínima que cruza ``target`` por bisección monotónica (SDD-21 §3).

        Evalúa ``M(a)`` fijando ``reverse.factor`` a la severidad ``a`` sobre el escenario forward
        base del escenario de stress referido por ``target.scenario_name`` (obligatorio; si no
        existe se levanta ``StressScenarioError``) y agregando la métrica ``target.metric`` (suma
        económica, media de probabilidad o ratio único) restringida a ``target.group_filter``. La
        bisección usa
        ``mid = lo + (hi - lo) / 2`` (nunca ``(lo + hi) / 2``, por estabilidad numérica) y se
        detiene cuando ``abs(M(mid) - threshold) <= metric_tol`` o ``(hi - lo) <= severity_tol``
        **con el punto ya cumpliendo la dirección**, garantizando un resultado interpretable.

        Convención de dirección (fija la ambigüedad A10-(b) del SDD-21): ``direction='at_least'``
        reporta la **menor severidad** con ``M(a) >= threshold`` (métrica creciente);
        ``direction='at_most'`` reporta la **menor severidad** con ``M(a) <= threshold`` (métrica
        decreciente). Exige haber ejecutado ``run(...)`` para cargar el contexto forward; las
        evaluaciones intermedias de ``M`` se ejecutan sin emitir auditoría por escenario y solo se
        registra el resumen ``stress_reverse``.
        """
        context = self._require_context()
        self._context = replace(context, audit=None)
        try:
            return self._run_reverse_stress(target, reverse, audit=context.audit)
        finally:
            self._context = context

    def _run_reverse_stress(
        self,
        target: StressTargetConfig,
        reverse: ReverseStressConfig,
        *,
        audit: AuditSink | None,
    ) -> ReverseStressResult:
        """Ejecuta la bisección determinista con el contexto ya silenciado."""
        pd = self._require_context().pd
        base_forward_scenario = _reverse_base_forward_scenario(self.config, target)
        scenario = _reverse_scenario(target, reverse, base_forward_scenario=base_forward_scenario)
        threshold = target.threshold
        direction = target.direction
        warnings_seen: list[str] = []
        sources_seen: list[str] = []

        def evaluate(severity: float) -> float:
            scenario_result = self._run_scenario(
                scenario,
                severity=severity,
                metrics=(target.metric,),
            )
            warnings_seen.extend(scenario_result.warning_codes)
            value, sources, warns = _reverse_metric_value(
                scenario_result.impact_frame,
                target=target,
            )
            warnings_seen.extend(warns)
            sources_seen.extend(sources)
            return value

        monotonicity_values = [evaluate(point) for point in reverse.monotonicity_check_points]
        monotonicity_flag = _classify_monotonicity(
            monotonicity_values,
            tol=self.config.validation.metric_tol,
        )
        if monotonicity_flag == "non_monotonic":
            raise NonMonotonicStressError(
                f"La métrica {target.metric!r} del target {target.name!r} no es monotónica en "
                f"monotonicity_check_points={reverse.monotonicity_check_points}; "
                f"valores observados={tuple(monotonicity_values)}."
            )

        lo, hi = reverse.bracket
        metric_lo = evaluate(lo)
        metric_hi = evaluate(hi)
        if not _reverse_satisfies(metric_hi, direction, threshold):
            raise ReverseStressError(
                f"El target {target.name!r} no queda bracketed en {reverse.bracket}: "
                f"M(lo)={metric_lo}, M(hi)={metric_hi}, threshold={threshold}, "
                f"direction={direction!r}; el extremo hi no cruza el umbral."
            )
        if _reverse_satisfies(metric_lo, direction, threshold):
            raise ReverseStressError(
                f"El target {target.name!r} no queda bracketed en {reverse.bracket}: "
                f"M(lo)={metric_lo}, M(hi)={metric_hi}, threshold={threshold}, "
                f"direction={direction!r}; el extremo lo ya cruza el umbral."
            )

        path_rows: list[dict[str, Any]] = []
        converged = False
        severity = 0.0
        metric_value = 0.0
        iterations = 0
        for iteration in range(reverse.max_iterations):
            mid = lo + (hi - lo) / 2.0
            value = evaluate(mid)
            satisfies = _reverse_satisfies(value, direction, threshold)
            within_tol = (
                abs(value - threshold) <= reverse.metric_tol or (hi - lo) <= reverse.severity_tol
            )
            if satisfies and within_tol:
                path_rows.append(
                    _reverse_path_row(
                        target.name, iteration, lo, hi, mid, value, threshold, "converged"
                    )
                )
                converged = True
                severity, metric_value, iterations = mid, value, iteration
                break
            decision = "move_hi" if satisfies else "move_lo"
            path_rows.append(
                _reverse_path_row(target.name, iteration, lo, hi, mid, value, threshold, decision)
            )
            if decision == "move_lo":
                lo = mid
            else:
                hi = mid
        else:
            raise ReverseStressError(
                f"La bisección del target {target.name!r} no convergió en "
                f"{reverse.max_iterations} iteraciones (bracket={reverse.bracket}, "
                f"threshold={threshold})."
            )

        result = ReverseStressResult(
            target_name=target.name,
            metric=target.metric,
            threshold=threshold,
            direction=direction,
            severity=severity,
            metric_value=metric_value,
            iterations=iterations,
            bracket=reverse.bracket,
            converged=converged,
            reverse_path_frame=_reverse_path_frame(path_rows, pd=pd),
        )
        _emit_audit_decision(
            audit,
            regla="stress_reverse",
            umbral={
                "target": target.name,
                "metric": target.metric,
                "threshold": threshold,
                "direction": direction,
                "factor": reverse.factor,
                "bracket": reverse.bracket,
                "severity_tol": reverse.severity_tol,
                "metric_tol": reverse.metric_tol,
                "max_iterations": reverse.max_iterations,
            },
            valor={
                "severity": severity,
                "metric_value": metric_value,
                "iterations": iterations,
                "converged": converged,
                "path_rows": len(path_rows),
                "monotonicity_flag": monotonicity_flag,
                "engine_sources": _dedupe_iterable(sources_seen),
                "warning_codes": _dedupe(warnings_seen),
            },
            accion="solve",
        )
        return result

    def _require_context(self) -> _RunContext:
        if self._context is None:
            raise StressEngineError("run_scenario exige ejecutar run(...) primero.")
        return self._context


def _reject_deferred_features(cfg: StressConfig) -> None:
    if not cfg.output.include_baseline_rows:
        raise StressEngineError(
            "output.include_baseline_rows=False está diferido: stress publica impactos "
            "comparables con value_base/value_stress obligatorios."
        )
    if (
        not cfg.scenarios
        and not cfg.sensitivities
        and not any(reverse.enabled for reverse in cfg.reverse)
    ):
        raise StressEngineError(
            "stress exige al menos un escenario, una sensibilidad o un reverse stress ejecutable."
        )


def _validate_economic_engines(
    cfg: StressConfig,
    *,
    ecl_engine: EclEngineLike | None,
    provision_engine: ProvisionEngineLike | None,
    audit: AuditSink | None,
) -> None:
    metrics = set(cfg.output.metrics)
    if metrics & _ECL_METRICS and ecl_engine is None and cfg.validation.fail_on_missing_ecl_engine:
        message = "output.metrics requiere ECL engine conectado."
        _emit_missing_economic_engine(
            audit,
            reason="missing_ecl_engine",
            message=message,
        )
        raise StressDependencyError(message)
    if metrics & _PROVISION_METRICS:
        if ecl_engine is None and cfg.validation.fail_on_missing_ecl_engine:
            message = "La provisión requiere ECL engine conectado."
            _emit_missing_economic_engine(
                audit,
                reason="missing_ecl_engine",
                message=message,
            )
            raise StressDependencyError(message)
        if provision_engine is None and cfg.validation.fail_on_missing_ecl_engine:
            message = "output.metrics requiere provision_engine conectado."
            _emit_missing_economic_engine(
                audit,
                reason="missing_provision_engine",
                message=message,
            )
            raise StressDependencyError(message)
    if ecl_engine is not None and not callable(getattr(ecl_engine, "calculate", None)):
        raise StressDependencyError("ecl_engine debe exponer calculate(...).")
    if provision_engine is not None and not callable(getattr(provision_engine, "calculate", None)):
        raise StressDependencyError("provision_engine debe exponer calculate(...).")


def _emit_missing_economic_engine(
    audit: AuditSink | None,
    *,
    reason: str,
    message: str,
) -> None:
    _emit_falta_dato(
        audit,
        code=_WARNING_MISSING_ECL,
        blocked=True,
        scenario="all",
        factor=None,
        periods="all",
        reason=reason,
        message=message,
        source="engine_dependency",
    )


def _validate_run_inputs(
    macro_projection: DataFrame,
    forward_term_structure: DataFrame,
    cfg: StressConfig,
    *,
    pd: Any,
) -> None:
    _require_columns(
        macro_projection,
        _MACRO_PROJECTION_REQUIRED_COLUMNS,
        field_name="macro_projection",
    )
    _require_columns(
        forward_term_structure,
        _FORWARD_TERM_STRUCTURE_REQUIRED_COLUMNS,
        field_name="forward_term_structure",
    )
    _reject_weighted_mean_columns(macro_projection, field_name="macro_projection")
    _validate_no_nonfinite_input(macro_projection, field_name="macro_projection")
    _validate_no_nonfinite_input(
        forward_term_structure,
        field_name="forward_term_structure",
        allow_missing_columns=_FORWARD_TERM_STRUCTURE_OPTIONAL_KEY_COLUMNS,
    )
    _validate_scenario_weight_column(macro_projection, field_name="macro_projection")
    _validate_scenario_weight_column(forward_term_structure, field_name="forward_term_structure")
    _reject_reserved_scenarios(macro_projection, field_name="macro_projection")
    _reject_reserved_scenarios(forward_term_structure, field_name="forward_term_structure")
    _validate_macro_projection_values(
        macro_projection,
        metric_tol=cfg.validation.metric_tol,
        pd=pd,
    )
    _validate_forward_term_values(forward_term_structure, cfg=cfg)
    if cfg.validation.require_forward_severe:
        _require_observed_scenario(macro_projection, "severe", field_name="macro_projection")
        _require_observed_scenario(
            forward_term_structure,
            "severe",
            field_name="forward_term_structure",
        )
    for scenario in cfg.scenarios:
        _require_observed_scenario(
            macro_projection,
            scenario.base_forward_scenario,
            field_name="macro_projection",
        )
        _require_observed_scenario(
            forward_term_structure,
            scenario.base_forward_scenario,
            field_name="forward_term_structure",
        )
        base_macro = macro_projection[
            macro_projection["scenario"].astype(str) == scenario.base_forward_scenario
        ]
        base_term = forward_term_structure[
            forward_term_structure["scenario"].astype(str) == scenario.base_forward_scenario
        ]
        for shock in scenario.shocks:
            _validate_shock_periods(shock, base_macro, base_term=base_term, pd=pd)


def _validate_forward_ecl_input_contract(
    forward_ecl_input: object,
    *,
    cfg: StressConfig,
    pd: Any,
) -> None:
    """Valida en runtime el contrato mínimo ``ForwardEclInput`` de SDD-20."""
    if forward_ecl_input is None:
        raise StressDependencyError("forward_ecl_input es obligatorio para stress.")
    contract_version = _forward_ecl_attr(
        forward_ecl_input,
        "contract_version",
        field_name="forward_ecl_input.contract_version",
    )
    if contract_version != _FORWARD_ECL_CONTRACT_VERSION:
        raise StressDependencyError(
            "forward_ecl_input.contract_version incompatible: "
            f"{contract_version!r}; esperado={_FORWARD_ECL_CONTRACT_VERSION!r}."
        )
    chain = _forward_ecl_attr(
        forward_ecl_input,
        "chain",
        field_name="forward_ecl_input.chain",
    )
    if chain != _FORWARD_ECL_CHAIN:
        raise StressDependencyError(
            "forward_ecl_input.chain incompatible con la cadena forward/ECL esperada."
        )
    pit_consistency = _forward_ecl_attr(
        forward_ecl_input,
        "pit_consistency",
        field_name="forward_ecl_input.pit_consistency",
    )
    if not isinstance(pit_consistency, Mapping):
        raise StressDependencyError("forward_ecl_input.pit_consistency debe ser un mapping.")
    if _contains_nonfinite(pit_consistency):
        raise StressDependencyError(
            "forward_ecl_input.pit_consistency no puede contener no finitos."
        )
    scenario_weight_frame = _forward_ecl_attr(
        forward_ecl_input,
        "scenario_weight_frame",
        field_name="forward_ecl_input.scenario_weight_frame",
    )
    _validate_forward_ecl_dataframe(
        scenario_weight_frame,
        expected_columns=_SCENARIO_WEIGHT_COLUMNS,
        field_name="forward_ecl_input.scenario_weight_frame",
        pd=pd,
    )
    _validate_forward_ecl_scenario_weights(
        scenario_weight_frame,
        weight_sum_tol=cfg.validation.weight_sum_tol,
    )
    term_structure_frame = _forward_ecl_attr(
        forward_ecl_input,
        "term_structure_frame",
        field_name="forward_ecl_input.term_structure_frame",
    )
    if term_structure_frame is not None:
        _validate_forward_ecl_dataframe(
            term_structure_frame,
            expected_columns=_FORWARD_TERM_STRUCTURE_COLUMNS,
            optional_columns=_FORWARD_TERM_STRUCTURE_OPTIONAL_LGD_COLUMNS,
            field_name="forward_ecl_input.term_structure_frame",
            pd=pd,
        )
        try:
            _validate_forward_term_values(term_structure_frame, cfg=cfg)
        except StressInputError as exc:
            raise StressDependencyError(str(exc)) from exc


def _validate_forward_ecl_input_matches_forward_artifacts(
    forward_ecl_input: object,
    *,
    forward_term_structure: DataFrame,
    cfg: StressConfig,
    pd: Any,
) -> None:
    term_structure_frame = _forward_ecl_attr(
        forward_ecl_input,
        "term_structure_frame",
        field_name="forward_ecl_input.term_structure_frame",
    )
    if isinstance(term_structure_frame, pd.DataFrame):
        input_hash = _maybe_forward_term_frame_hash(
            term_structure_frame,
            cfg=cfg,
            key_columns=_FORWARD_TERM_HASH_KEY_COLUMNS,
            field_name="forward_ecl_input.term_structure_frame",
            pd=pd,
        )
        authoritative_hash = _maybe_forward_term_frame_hash(
            forward_term_structure,
            cfg=cfg,
            key_columns=_FORWARD_TERM_HASH_KEY_COLUMNS,
            field_name="forward_term_structure",
            pd=pd,
        )
        if input_hash != authoritative_hash:
            raise StressDependencyError(
                "forward_ecl_input.term_structure_frame no coincide con "
                "forward_term_structure autoritativo."
            )
    scenario_weight_frame = _forward_ecl_attr(
        forward_ecl_input,
        "scenario_weight_frame",
        field_name="forward_ecl_input.scenario_weight_frame",
    )
    expected_weights = _term_scenario_weights(
        forward_term_structure,
        scenario_column="scenario",
        weight_column="scenario_weight",
        field_name="forward_term_structure",
    )
    observed_weights = _term_scenario_weights(
        scenario_weight_frame,
        scenario_column="scenario",
        weight_column="weight",
        field_name="forward_ecl_input.scenario_weight_frame",
    )
    missing = sorted(set(expected_weights) - set(observed_weights))
    if missing:
        raise StressDependencyError(
            "forward_ecl_input.scenario_weight_frame no cubre escenarios "
            f"de forward_term_structure: {missing}."
        )
    extra_nonzero = sorted(
        scenario
        for scenario, observed in observed_weights.items()
        if scenario not in expected_weights
        and not math.isclose(
            observed,
            0.0,
            rel_tol=0.0,
            abs_tol=cfg.validation.weight_sum_tol,
        )
    )
    if extra_nonzero:
        raise StressDependencyError(
            "forward_ecl_input.scenario_weight_frame trae escenarios extra con peso no nulo: "
            f"{extra_nonzero}."
        )
    mismatched = sorted(
        scenario
        for scenario, expected in expected_weights.items()
        if not math.isclose(
            observed_weights[scenario],
            expected,
            rel_tol=0.0,
            abs_tol=cfg.validation.weight_sum_tol,
        )
    )
    if mismatched:
        raise StressDependencyError(
            "forward_ecl_input.scenario_weight_frame no coincide con "
            f"forward_term_structure para escenarios: {mismatched}."
        )


def _term_scenario_weights(
    frame: DataFrame,
    *,
    scenario_column: str,
    weight_column: str,
    field_name: str,
) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in frame.itertuples(index=False):
        row_any = cast("Any", row)
        scenario = _validate_non_empty_text(
            getattr(row_any, scenario_column),
            field_name=f"{field_name}.{scenario_column}",
        )
        weight = _required_float(
            getattr(row_any, weight_column),
            field_name=f"{field_name}.{weight_column}",
        )
        previous = weights.get(scenario)
        if previous is not None and not math.isclose(
            previous,
            weight,
            rel_tol=0.0,
            abs_tol=_FLOAT_ATOL,
        ):
            raise StressDependencyError(
                f"{field_name}.{weight_column} debe ser constante por escenario: "
                f"scenario={scenario!r}."
            )
        weights[scenario] = weight
    return weights


def _forward_ecl_attr(obj: object, attr: str, *, field_name: str) -> Any:
    sentinel = object()
    try:
        value = getattr(obj, attr, sentinel)
    except Exception as exc:
        raise StressDependencyError(f"{field_name} no se pudo leer.") from exc
    if value is sentinel:
        raise StressDependencyError(f"{field_name} es obligatorio.")
    return value


def _validate_forward_ecl_dataframe(
    value: object,
    *,
    expected_columns: tuple[str, ...],
    optional_columns: tuple[str, ...] = (),
    field_name: str,
    pd: Any,
) -> None:
    if not isinstance(value, pd.DataFrame):
        raise StressDependencyError(f"{field_name} debe ser pandas.DataFrame.")
    try:
        _require_columns(
            value,
            _required_columns(expected_columns, optional_columns=optional_columns),
            field_name=field_name,
        )
    except StressInputError as exc:
        raise StressDependencyError(str(exc)) from exc


def _validate_forward_ecl_scenario_weights(
    frame: DataFrame,
    *,
    weight_sum_tol: float,
) -> None:
    weights: list[float] = []
    scenarios: list[str] = []
    for row in frame.itertuples(index=False):
        row_any = cast("Any", row)
        try:
            scenario = _validate_non_empty_text(row_any.scenario, field_name="scenario")
            weight = _required_float(row_any.weight, field_name="scenario_weight_frame.weight")
        except StressInputError as exc:
            raise StressDependencyError(str(exc)) from exc
        if scenario.lower() in _RESERVED_SCENARIO_NAMES:
            raise StressDependencyError(
                f"scenario_weight_frame contiene escenario medio prohibido: {scenario!r}."
            )
        scenarios.append(scenario)
        if weight < 0.0:
            raise StressDependencyError("scenario_weight_frame.weight no puede ser negativo.")
        weights.append(weight)
        try:
            source = _validate_non_empty_text(
                row_any.source,
                field_name="scenario_weight_frame.source",
            )
        except StressInputError as exc:
            raise StressDependencyError(str(exc)) from exc
        if source not in {"config", "default_a_confirmar"}:
            raise StressDependencyError(
                "scenario_weight_frame.source debe ser config o default_a_confirmar."
            )
        try:
            _required_bool(row_any.is_default, field_name="scenario_weight_frame.is_default")
            _validate_non_empty_text(
                row_any.description,
                field_name="scenario_weight_frame.description",
            )
        except StressInputError as exc:
            raise StressDependencyError(str(exc)) from exc
    if not weights:
        raise StressDependencyError("forward_ecl_input.scenario_weight_frame no puede estar vacío.")
    duplicated = sorted({scenario for scenario in scenarios if scenarios.count(scenario) > 1})
    if duplicated:
        raise StressDependencyError(
            f"scenario_weight_frame contiene escenarios duplicados: {duplicated}."
        )
    if not math.isclose(math.fsum(weights), 1.0, rel_tol=0.0, abs_tol=weight_sum_tol):
        raise StressDependencyError("Los pesos de scenario_weight_frame deben sumar 1.")


def _validate_scenario_weighting_contract(
    scenario_weighting: object,
    macro_projection: DataFrame,
) -> None:
    if scenario_weighting is None:
        raise StressDependencyError("scenario_weighting es obligatorio para stress.")
    validator = getattr(scenario_weighting, "validate_macro_projection", None)
    if not callable(validator):
        raise StressDependencyError(
            "scenario_weighting debe exponer validate_macro_projection(...)."
        )
    validator(macro_projection.copy(deep=True))


def _validate_scenario_weight_column(frame: DataFrame, *, field_name: str) -> None:
    weights_by_scenario: dict[str, float] = {}
    for row in frame.itertuples(index=False):
        row_any = cast("Any", row)
        scenario = _validate_non_empty_text(row_any.scenario, field_name=f"{field_name}.scenario")
        weight = _probability(
            _required_float(row_any.scenario_weight, field_name=f"{field_name}.scenario_weight"),
            field_name=f"{field_name}.scenario_weight",
            tol=_FLOAT_ATOL,
        )
        previous = weights_by_scenario.get(scenario)
        if previous is not None and not math.isclose(
            previous,
            weight,
            rel_tol=0.0,
            abs_tol=_FLOAT_ATOL,
        ):
            raise StressInputError(
                f"{field_name}.scenario_weight debe ser constante por escenario: "
                f"scenario={scenario!r}."
            )
        weights_by_scenario[scenario] = weight


def _canonicalize_macro_projection(frame: DataFrame, *, pd: Any) -> DataFrame:
    """Ordena la macro por clave lógica antes de hash y publicación pública."""
    del pd
    _require_columns(frame, _MACRO_PROJECTION_REQUIRED_COLUMNS, field_name="macro_projection")
    working = _normalize_frame(frame)
    taken = set(str(column) for column in working.columns)
    scenario_sort_column = _unique_helper_column("_nikodym_macro_sort_scenario", taken=taken)
    macro_variable_sort_column = _unique_helper_column(
        "_nikodym_macro_sort_macro_variable",
        taken=taken,
    )
    period_sort_column = _unique_helper_column("_nikodym_macro_sort_period", taken=taken)
    sort_columns = (scenario_sort_column, macro_variable_sort_column, period_sort_column)

    working[scenario_sort_column] = [
        _validate_non_empty_text(value, field_name="scenario")
        for value in working["scenario"].tolist()
    ]
    working[macro_variable_sort_column] = [
        _validate_non_empty_text(value, field_name="macro_variable")
        for value in working["macro_variable"].tolist()
    ]
    working[period_sort_column] = [
        _positive_int(value, field_name="period") for value in working["period"].tolist()
    ]
    duplicated = working.duplicated(
        subset=list(sort_columns),
        keep=False,
    )
    if bool(duplicated.any()):
        duplicated_frame = working.loc[
            duplicated,
            list(sort_columns),
        ]
        duplicated_keys = [
            (scenario, factor, int(period))
            for scenario, factor, period in zip(
                duplicated_frame[scenario_sort_column].tolist(),
                duplicated_frame[macro_variable_sort_column].tolist(),
                duplicated_frame[period_sort_column].tolist(),
                strict=True,
            )
        ]
        raise StressScenarioError(
            "macro_projection debe tener una fila única por scenario/macro_variable/period: "
            f"{tuple(dict.fromkeys(duplicated_keys))}."
        )
    working.loc[:, "period"] = working[period_sort_column]
    sorted_frame = working.sort_values(
        list(sort_columns),
        kind="mergesort",
    )
    return sorted_frame.drop(columns=list(sort_columns)).reset_index(drop=True)


def _canonicalize_forward_term_structure(
    frame: DataFrame,
    *,
    cfg: StressConfig,
    field_name: str,
    pd: Any,
) -> DataFrame:
    """Normaliza valores aceptados por coerción antes de hash y cálculo."""
    _require_columns(
        frame,
        _required_columns(
            _FORWARD_TERM_STRUCTURE_REQUIRED_COLUMNS,
            optional_columns=_FORWARD_TERM_STRUCTURE_OPTIONAL_LGD_COLUMNS,
        ),
        field_name=field_name,
    )
    working = _normalize_frame(frame)
    for column in _FORWARD_TERM_STRUCTURE_OPTIONAL_KEY_COLUMNS:
        working[column] = pd.Series(
            [
                _normalize_optional_forward_key(value, field_name=f"{field_name}.{column}")
                for value in working[column]
            ],
            index=working.index,
            dtype=object,
        )
    working.loc[:, "period"] = pd.Series(
        [_positive_int(value, field_name=f"{field_name}.period") for value in working["period"]],
        index=working.index,
        dtype=int,
    )
    for column in _FORWARD_TERM_TEXT_COLUMNS:
        working.loc[:, column] = pd.Series(
            [
                _validate_non_empty_text(value, field_name=f"{field_name}.{column}")
                for value in working[column]
            ],
            index=working.index,
            dtype=object,
        )
    for column in _FORWARD_TERM_FLOAT_COLUMNS:
        working.loc[:, column] = pd.Series(
            [
                _required_float(value, field_name=f"{field_name}.{column}")
                for value in working[column]
            ],
            index=working.index,
            dtype=float,
        )
    for column in _FORWARD_TERM_REQUIRED_PROBABILITY_COLUMNS:
        working.loc[:, column] = pd.Series(
            [
                _probability(
                    _required_float(value, field_name=f"{field_name}.{column}"),
                    field_name=f"{field_name}.{column}",
                    tol=cfg.validation.probability_tol,
                )
                for value in working[column]
            ],
            index=working.index,
            dtype=float,
        )
    for column in _FORWARD_TERM_OPTIONAL_PROBABILITY_COLUMNS:
        if column in working.columns:
            values = [
                None
                if _is_missing(value)
                else _probability(
                    _required_float(value, field_name=f"{field_name}.{column}"),
                    field_name=f"{field_name}.{column}",
                    tol=cfg.validation.probability_tol,
                )
                for value in working[column]
            ]
            working.loc[:, column] = pd.Series(
                values,
                index=working.index,
                dtype=object if any(value is None for value in values) else float,
            )
    for column in _FORWARD_TERM_OPTIONAL_FLOAT_COLUMNS:
        values = [
            None
            if _is_missing(value)
            else _required_float(value, field_name=f"{field_name}.{column}")
            for value in working[column]
        ]
        working.loc[:, column] = pd.Series(
            values,
            index=working.index,
            dtype=object if any(value is None for value in values) else float,
        )
    working.loc[:, "warning_codes"] = pd.Series(
        [_warning_tuple(value) for value in working["warning_codes"]],
        index=working.index,
        dtype=object,
    )
    return working


def _canonicalize_scenario_weight_frame(
    frame: DataFrame,
    *,
    field_name: str,
    pd: Any,
) -> DataFrame:
    """Normaliza el frame de pesos forward con las mismas reglas del contrato."""
    _require_columns(frame, _SCENARIO_WEIGHT_COLUMNS, field_name=field_name)
    working = _normalize_frame(frame)
    for column in ("scenario", "source"):
        working.loc[:, column] = pd.Series(
            [
                _validate_non_empty_text(value, field_name=f"{field_name}.{column}")
                for value in working[column]
            ],
            index=working.index,
            dtype=object,
        )
    working.loc[:, "weight"] = pd.Series(
        [_required_float(value, field_name=f"{field_name}.weight") for value in working["weight"]],
        index=working.index,
        dtype=float,
    )
    return working


def _apply_macro_shocks(
    scenario: StressScenarioConfig,
    *,
    severity: float,
    macro_projection: DataFrame,
    forward_term_structure: DataFrame,
    cfg: StressConfig,
    pd: Any,
    audit: AuditSink | None,
) -> _MacroStressResult:
    base = (
        macro_projection[macro_projection["scenario"].astype(str) == scenario.base_forward_scenario]
        .copy(deep=True)
        .reset_index(drop=True)
    )
    projection = base.copy(deep=True)
    _coerce_object_columns(projection, columns=("scenario",))
    projection.loc[:, "scenario"] = scenario.name
    _coerce_float_columns(
        projection,
        columns=("scenario_weight", "projected_value", "model_value", "shock_value", "time_value"),
    )
    projection.loc[:, "period"] = [
        _positive_int(value, field_name="period") for value in projection["period"].tolist()
    ]
    if "scenario_weight" in projection.columns and scenario.weight is not None:
        projection.loc[:, "scenario_weight"] = scenario.weight

    rows: list[dict[str, Any]] = []
    delta_lookup: dict[tuple[int, str], float] = {}
    warnings_seen: list[str] = []
    factors: list[str] = []
    touched: set[tuple[int, str]] = set()
    base_term = forward_term_structure[
        forward_term_structure["scenario"].astype(str) == scenario.base_forward_scenario
    ]
    for shock in scenario.shocks:
        factors.append(shock.factor)
        warning_codes = list(_validate_shock_source(shock, scenario=scenario, cfg=cfg, audit=audit))
        periods = _shock_periods(shock, base, base_term=base_term, pd=pd)
        dominance_warnings = _check_dominance(
            scenario,
            shock,
            severity=severity,
            periods=periods,
            macro_projection=macro_projection,
            cfg=cfg,
            audit=audit,
        )
        warning_codes.extend(dominance_warnings)
        for period in periods:
            key = (period, shock.factor)
            if key in touched:
                raise StressScenarioError(
                    "Un escenario no puede declarar shocks duplicados para el mismo "
                    f"factor/período: {key}."
                )
            touched.add(key)
            mask = _period_equals(projection, period) & (
                projection["macro_variable"].astype(str) == shock.factor
            )
            if int(mask.sum()) != 1:
                raise StressScenarioError(
                    "macro_projection debe tener una fila única por escenario/factor/período."
                )
            idx = projection.index[mask][0]
            original = _required_float(projection.at[idx, "projected_value"], field_name="x")
            applied_shock = _clean_float(severity * shock.value, field_name="applied_shock")
            stressed = _apply_shock_value(original, applied_shock, operation=shock.operation)
            effective_delta = _clean_float(stressed - original, field_name="delta_macro")
            projection.at[idx, "projected_value"] = stressed
            projection.at[idx, "shock_value"] = _clean_float(
                _required_float(projection.at[idx, "shock_value"], field_name="shock_value")
                + effective_delta,
                field_name="shock_value",
            )
            delta_lookup[key] = effective_delta
            macro_warnings = _warning_tuple(projection.at[idx, "warning_codes"])
            row_warnings = _dedupe((*macro_warnings, *warning_codes))
            projection.at[idx, "warning_codes"] = cast("Any", row_warnings)
            warnings_seen.extend(row_warnings)
            rows.append(
                {
                    "stress_scenario": scenario.name,
                    "scenario_kind": scenario.kind,
                    "base_forward_scenario": scenario.base_forward_scenario,
                    "severity": severity,
                    "macro_variable": shock.factor,
                    "operation": shock.operation,
                    "shock_value": shock.value,
                    "applied_shock": applied_shock,
                    "period": period,
                    "source": shock.source,
                    "warning_codes": row_warnings,
                }
            )
    scenario_frame = pd.DataFrame.from_records(rows, columns=_SCENARIO_FRAME_COLUMNS)
    return _MacroStressResult(
        scenario_frame=_normalize_frame(scenario_frame),
        projection_frame=_normalize_frame(
            projection.loc[:, list(_MACRO_PROJECTION_REQUIRED_COLUMNS)]
        ),
        delta_lookup=delta_lookup,
        macro_variable_set=tuple(dict.fromkeys(factors)),
        warning_codes=_dedupe(warnings_seen),
    )


def _validate_shock_source(
    shock: StressShockConfig,
    *,
    scenario: StressScenarioConfig,
    cfg: StressConfig,
    audit: AuditSink | None = None,
) -> tuple[str, ...]:
    if shock.source != "official":
        return ()
    message = (
        f"{_FALTA_DATO_OFFICIAL}: source='official' exige evidencia externa para "
        f"scenario={scenario.name!r}, factor={shock.factor!r}."
    )
    _emit_falta_dato(
        audit,
        code=_FALTA_DATO_OFFICIAL,
        blocked=cfg.validation.fail_on_falta_dato,
        scenario=scenario.name,
        factor=shock.factor,
        periods=shock.periods,
        reason="official_source_without_external_evidence",
        message=message,
        source=shock.source,
    )
    if cfg.validation.fail_on_falta_dato:
        raise StressFaltaDatoError(message)
    return (_FALTA_DATO_OFFICIAL,)


def _coerce_float_columns(frame: DataFrame, *, columns: tuple[str, ...]) -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = frame[column].astype("float64")


def _coerce_object_columns(frame: DataFrame, *, columns: tuple[str, ...]) -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = frame[column].astype("object")


def _check_dominance(
    scenario: StressScenarioConfig,
    shock: StressShockConfig,
    *,
    severity: float,
    periods: tuple[int, ...],
    macro_projection: DataFrame,
    cfg: StressConfig,
    audit: AuditSink | None,
) -> tuple[str, ...]:
    if not (
        cfg.validation.require_dominates_forward_adverse
        and scenario.require_dominates_forward_adverse
    ):
        _emit_audit_decision(
            audit,
            regla="stress_dominance_check",
            umbral={
                "scenario": scenario.name,
                "factor": shock.factor,
                "operation": shock.operation,
                "severity": severity,
                "periods": periods,
                "required": False,
            },
            valor={"result": "skipped", "checks": ()},
            accion="skip",
        )
        return ()
    missing: list[int] = []
    checks: list[dict[str, Any]] = []
    for period in periods:
        stress_delta = _stress_delta_for_dominance(
            scenario,
            shock,
            severity=severity,
            period=period,
            macro_projection=macro_projection,
        )
        adverse_delta = _adverse_delta(
            macro_projection,
            factor=shock.factor,
            period=period,
            metric_tol=cfg.validation.metric_tol,
        )
        if adverse_delta is None:
            missing.append(period)
            checks.append(
                {
                    "period": period,
                    "stress_delta": stress_delta,
                    "adverse_delta": None,
                    "result": "missing_adverse",
                }
            )
            continue
        opposite_direction = (
            not math.isclose(
                adverse_delta,
                0.0,
                rel_tol=0.0,
                abs_tol=cfg.validation.metric_tol,
            )
            and stress_delta * adverse_delta <= 0.0
        )
        insufficient_magnitude = abs(stress_delta) + cfg.validation.metric_tol < abs(adverse_delta)
        if opposite_direction or insufficient_magnitude:
            checks.append(
                {
                    "period": period,
                    "stress_delta": stress_delta,
                    "adverse_delta": adverse_delta,
                    "result": "opposite_direction" if opposite_direction else "not_dominant",
                }
            )
            _emit_audit_decision(
                audit,
                regla="stress_dominance_check",
                umbral={
                    "scenario": scenario.name,
                    "factor": shock.factor,
                    "operation": shock.operation,
                    "severity": severity,
                    "periods": periods,
                    "metric_tol": cfg.validation.metric_tol,
                },
                valor={"result": "not_dominant", "checks": tuple(checks)},
                accion="fail",
            )
            raise StressScenarioError(
                "El shock de stress no domina adverse: "
                f"scenario={scenario.name!r}, factor={shock.factor!r}, period={period}, "
                f"stress={stress_delta}, adverse={adverse_delta}."
            )
        checks.append(
            {
                "period": period,
                "stress_delta": stress_delta,
                "adverse_delta": adverse_delta,
                "result": "dominates",
            }
        )
    if not missing:
        _emit_audit_decision(
            audit,
            regla="stress_dominance_check",
            umbral={
                "scenario": scenario.name,
                "factor": shock.factor,
                "operation": shock.operation,
                "severity": severity,
                "periods": periods,
                "metric_tol": cfg.validation.metric_tol,
            },
            valor={"result": "dominates", "checks": tuple(checks), "warning_codes": ()},
            accion="pass",
        )
        return ()
    message = (
        f"{_FALTA_DATO_DOMINANCE}: no existe delta adverse trazable para "
        f"scenario={scenario.name!r}, factor={shock.factor!r}, periods={tuple(missing)}."
    )
    _emit_audit_decision(
        audit,
        regla="stress_dominance_check",
        umbral={
            "scenario": scenario.name,
            "factor": shock.factor,
            "operation": shock.operation,
            "severity": severity,
            "periods": periods,
            "metric_tol": cfg.validation.metric_tol,
        },
        valor={
            "result": "falta_dato",
            "checks": tuple(checks),
            "warning_codes": (_FALTA_DATO_DOMINANCE,),
        },
        accion="falta_dato",
    )
    _emit_falta_dato(
        audit,
        code=_FALTA_DATO_DOMINANCE,
        blocked=cfg.validation.fail_on_falta_dato,
        scenario=scenario.name,
        factor=shock.factor,
        periods=tuple(missing),
        reason="missing_forward_adverse_delta",
        message=message,
        source="forward_adverse",
    )
    if cfg.validation.fail_on_falta_dato:
        raise StressFaltaDatoError(message)
    return (_FALTA_DATO_DOMINANCE,)


def _stress_delta_for_dominance(
    scenario: StressScenarioConfig,
    shock: StressShockConfig,
    *,
    severity: float,
    period: int,
    macro_projection: DataFrame,
) -> float:
    applied_shock = _clean_float(severity * shock.value, field_name="dominance_shock")
    if shock.operation == "additive":
        return applied_shock
    if shock.operation != "relative":
        raise StressScenarioError(f"Operación de shock no soportada: {shock.operation!r}.")
    base = macro_projection[
        (macro_projection["scenario"].astype(str) == scenario.base_forward_scenario)
        & (macro_projection["macro_variable"].astype(str) == shock.factor)
        & _period_equals(macro_projection, period)
    ]
    if len(base.index) != 1:
        raise StressScenarioError(
            "Dominancia relative requiere una fila base única por escenario/factor/período: "
            f"scenario={scenario.name!r}, factor={shock.factor!r}, period={period}."
        )
    value_base = _required_float(base.iloc[0]["projected_value"], field_name="relative_base")
    _require_positive_relative_base(value_base, factor=shock.factor, period=period)
    return _clean_float(
        value_base * (1.0 + applied_shock) - value_base,
        field_name="dominance_shock",
    )


def _adverse_delta(
    frame: DataFrame,
    *,
    factor: str,
    period: int,
    metric_tol: float = _FLOAT_ATOL,
) -> float | None:
    tol = max(metric_tol, _FLOAT_ATOL)
    adverse = frame[
        (frame["scenario"].astype(str) == "adverse")
        & (frame["macro_variable"].astype(str) == factor)
        & _period_equals(frame, period)
    ]
    if len(adverse.index) != 1:
        return None
    row = adverse.iloc[0]
    projected = _required_float(row["projected_value"], field_name="adverse.projected_value")
    shock = _required_float(row["shock_value"], field_name="adverse.shock_value")
    traced_delta = _macro_projected_delta(
        projected_value=projected,
        model_value=row["model_value"],
        shock_value=shock,
        scenario="adverse",
        macro_variable=factor,
        period=period,
        metric_tol=tol,
    )
    if not math.isclose(shock, 0.0, rel_tol=0.0, abs_tol=tol):
        return traced_delta
    base = frame[
        (frame["scenario"].astype(str) == "base")
        & (frame["macro_variable"].astype(str) == factor)
        & _period_equals(frame, period)
    ]
    if len(base.index) == 1:
        base_projected = _required_float(
            base.iloc[0]["projected_value"],
            field_name="base.projected_value",
        )
        base_delta = _clean_float(
            projected - base_projected,
            field_name="adverse.delta",
        )
        if not math.isclose(base_delta, 0.0, rel_tol=0.0, abs_tol=tol):
            return base_delta
        return traced_delta
    return None


def _apply_satellite_stress(
    scenario: StressScenarioConfig,
    *,
    severity: float,
    macro_result: _MacroStressResult,
    forward_term_structure: DataFrame,
    satellite_model: object,
    cfg: StressConfig,
    pd: Any,
    audit: AuditSink | None,
) -> _TermStructureStressResult:
    base = forward_term_structure[
        forward_term_structure["scenario"].astype(str) == scenario.base_forward_scenario
    ].copy(deep=True)
    base["_ordinal"] = range(len(base.index))
    base = _sort_term_structure(base)
    stress_rows: list[dict[str, Any]] = []
    ecl_rows: list[dict[str, Any]] = []
    satellite_records: list[dict[str, Any]] = []
    for _curve_key, group in base.groupby(_curve_key_columns(base), sort=False, dropna=False):
        previous_survival = 1.0
        previous_period = 0
        for _, row in group.iterrows():
            period = _positive_int(row["period"], field_name="period")
            _validate_contiguous_lifetime_period(
                period,
                previous_period=previous_period,
                curve_key=_curve_key,
            )
            hazard_base = _probability(
                _required_float(row["hazard"], field_name="hazard"),
                field_name="hazard",
                tol=cfg.validation.probability_tol,
            )
            is_ttc = _is_ttc_term_row(row)
            satellite_result = (
                _SatelliteAdjustmentResult(adjustment=0.0, contributions=())
                if is_ttc
                else _satellite_incremental_adjustment(
                    row,
                    period=period,
                    macro_result=macro_result,
                    satellite_model=satellite_model,
                )
            )
            adjustment = satellite_result.adjustment
            hazard_stress = _shift_probability_logit(
                hazard_base,
                adjustment,
                field_name="hazard_stress",
                tol=cfg.validation.probability_tol,
            )
            pd_marginal = _probability(
                previous_survival * hazard_stress,
                field_name="pd_marginal_stress",
                tol=cfg.validation.probability_tol,
            )
            survival = _probability(
                previous_survival * (1.0 - hazard_stress),
                field_name="survival_stress",
                tol=cfg.validation.probability_tol,
            )
            pd_cumulative = _probability(
                1.0 - survival,
                field_name="pd_cumulative_stress",
                tol=cfg.validation.probability_tol,
            )
            lgd_base = _optional_probability_from_row(row, ("lgd", "lgd_base"), cfg=cfg)
            lgd_stress = (
                lgd_base
                if is_ttc
                else _project_lgd(
                    row,
                    period=period,
                    lgd_base=lgd_base,
                    macro_result=macro_result,
                    satellite_model=satellite_model,
                    cfg=cfg,
                )
            )
            satellite_base = _optional_float(row.get("satellite_adjustment"))
            satellite_stress = (
                adjustment if satellite_base is None else _clean_float(satellite_base + adjustment)
            )
            warnings = _warning_tuple(row.get("warning_codes"))
            satellite_records.append(
                {
                    "period": period,
                    "row_id": _none_if_missing(row.get("row_id")),
                    "segment": _segment_value(row),
                    "satellite_model": type(satellite_model).__name__,
                    "satellite_model_id": _none_if_missing(row.get("satellite_model_id")),
                    "factors": satellite_result.contributions,
                    "delta_logit": adjustment,
                    "hazard_base": hazard_base,
                    "hazard_stress": hazard_stress,
                }
            )
            stress_rows.append(
                {
                    "stress_scenario": scenario.name,
                    "scenario_kind": scenario.kind,
                    "severity": severity,
                    "base_forward_scenario": scenario.base_forward_scenario,
                    "row_id": _none_if_missing(row.get("row_id")),
                    "segment": _none_if_missing(row.get("segment")),
                    "partition": _none_if_missing(row.get("partition")),
                    "source_model": _forward_term_text(row, "source_model"),
                    "method": _forward_term_text(row, "method"),
                    "pd_source": _forward_term_text(row, "pd_source"),
                    "period": period,
                    "time_value": _required_float(row["time_value"], field_name="time_value"),
                    "macro_variable_set": macro_result.macro_variable_set,
                    "hazard_base": hazard_base,
                    "hazard_stress": hazard_stress,
                    "survival_stress": survival,
                    "pd_marginal_base": _required_float(
                        row["pd_marginal"],
                        field_name="pd_marginal",
                    ),
                    "pd_marginal_stress": pd_marginal,
                    "pd_cumulative_base": _required_float(
                        row["pd_cumulative"],
                        field_name="pd_cumulative",
                    ),
                    "pd_cumulative_stress": pd_cumulative,
                    "lgd_base": lgd_base,
                    "lgd_stress": lgd_stress,
                    "pd_basis": _forward_term_text(row, "pd_basis"),
                    "basis_state": _forward_term_text(row, "basis_state"),
                    "satellite_adjustment_base": satellite_base,
                    "satellite_adjustment_stress": satellite_stress,
                    "warning_codes": _dedupe((*warnings, *macro_result.warning_codes)),
                }
            )
            ecl_rows.append(
                _forward_ecl_row(
                    row,
                    scenario=scenario,
                    hazard=hazard_stress,
                    survival=survival,
                    pd_marginal=pd_marginal,
                    pd_cumulative=pd_cumulative,
                    lgd=lgd_stress,
                    satellite_adjustment=satellite_stress,
                    warning_codes=_dedupe((*warnings, *macro_result.warning_codes)),
                )
            )
            previous_survival = survival
            previous_period = period
    stress_term = pd.DataFrame.from_records(stress_rows, columns=_STRESS_TERM_STRUCTURE_COLUMNS)
    ecl_columns = _forward_ecl_columns(base.drop(columns=["_ordinal"]).columns, ecl_rows)
    ecl_term = pd.DataFrame.from_records(ecl_rows, columns=ecl_columns)
    normalized_stress = _normalize_frame(stress_term)
    normalized_ecl = _normalize_frame(ecl_term)
    _emit_audit_decision(
        audit,
        regla="stress_satellite_application",
        umbral={
            "scenario": scenario.name,
            "base_forward_scenario": scenario.base_forward_scenario,
            "severity": severity,
        },
        valor={
            "row_count": len(satellite_records),
            "macro_factors": macro_result.macro_variable_set,
            "records": tuple(satellite_records),
        },
        accion="apply",
    )
    _emit_audit_decision(
        audit,
        regla="stress_term_structure",
        umbral={
            "scenario": scenario.name,
            "publish": cfg.output.publish_stressed_term_structure,
        },
        valor=_term_structure_audit_payload(normalized_stress),
        accion="build",
    )
    return _TermStructureStressResult(
        stress_term_structure=normalized_stress,
        forward_ecl_term_structure=normalized_ecl,
    )


def _satellite_incremental_adjustment(
    row: Any,
    *,
    period: int,
    macro_result: _MacroStressResult,
    satellite_model: object,
) -> _SatelliteAdjustmentResult:
    segment = _segment_value(row)
    adjustment = 0.0
    contributions: list[dict[str, Any]] = []
    for factor in macro_result.macro_variable_set:
        delta = macro_result.delta_lookup.get((period, factor), 0.0)
        coefficient = _factor_coefficient(
            satellite_model,
            component="pd",
            factor=factor,
            segment=segment,
            required=True,
        )
        coefficient_value = cast("float", coefficient)
        delta_logit = _clean_float(coefficient_value * delta, field_name="satellite_adjustment")
        adjustment += delta_logit
        contributions.append(
            {
                "factor": factor,
                "coefficient": coefficient_value,
                "macro_delta": delta,
                "delta_logit": delta_logit,
            }
        )
    return _SatelliteAdjustmentResult(
        adjustment=_clean_float(adjustment, field_name="satellite_adjustment"),
        contributions=tuple(contributions),
    )


def _project_lgd(
    row: Any,
    *,
    period: int,
    lgd_base: float | None,
    macro_result: _MacroStressResult,
    satellite_model: object,
    cfg: StressConfig,
) -> float | None:
    if lgd_base is None:
        return None
    segment = _segment_value(row)
    adjustment = 0.0
    has_lgd_factor = False
    for factor in macro_result.macro_variable_set:
        coefficient = _factor_coefficient(
            satellite_model,
            component="lgd",
            factor=factor,
            segment=segment,
            required=False,
        )
        if coefficient is None:
            continue
        has_lgd_factor = True
        adjustment += coefficient * macro_result.delta_lookup.get((period, factor), 0.0)
    if not has_lgd_factor:
        return lgd_base
    return _shift_probability_logit(
        lgd_base,
        adjustment,
        field_name="lgd_stress",
        tol=cfg.validation.probability_tol,
    )


def _factor_coefficient(
    satellite_model: object,
    *,
    component: str,
    factor: str,
    segment: str,
    required: bool,
) -> float | None:
    coefficients = _coefficient_mapping(satellite_model)
    direct = _direct_factor_coefficient(coefficients, factor=factor)
    if direct is not None and component == "pd":
        return direct
    component_coeffs = coefficients.get(component)
    if not isinstance(component_coeffs, Mapping):
        if required:
            raise StressScenarioError(f"Modelo satellite sin coeficientes para {component!r}.")
        return None
    payload = component_coeffs.get(segment) or component_coeffs.get(_SEGMENT_ALL)
    if not isinstance(payload, Mapping):
        if required:
            raise StressScenarioError(
                f"Modelo satellite sin coeficientes para segmento {segment!r}."
            )
        return None
    factors = payload.get("factors")
    if not isinstance(factors, Mapping) or factor not in factors:
        if required:
            raise StressScenarioError(f"Modelo satellite sin coeficiente para factor {factor!r}.")
        return None
    return _required_float(factors[factor], field_name=f"coefficient.{component}.{factor}")


def _coefficient_mapping(satellite_model: object) -> Mapping[str, Any]:
    coefficients = getattr(satellite_model, "coefficients_", None)
    if coefficients is None:
        coefficients = getattr(satellite_model, "coefficients", None)
    if not isinstance(coefficients, Mapping):
        raise StressInputError("satellite_model debe exponer coefficients_ auditables.")
    return coefficients


def _direct_factor_coefficient(coefficients: Mapping[str, Any], *, factor: str) -> float | None:
    if factor in coefficients:
        return _required_float(coefficients[factor], field_name=f"coefficient.{factor}")
    factors = coefficients.get("factors")
    if isinstance(factors, Mapping) and factor in factors:
        return _required_float(factors[factor], field_name=f"coefficient.{factor}")
    return None


def _build_impact_frame(
    scenario: StressScenarioConfig,
    *,
    severity: float,
    stress_term_structure: DataFrame,
    forward_ecl_term_structure: DataFrame,
    context: _RunContext,
    cfg: StressConfig,
    metrics: Sequence[StressMetric],
    macro_warning_codes: tuple[str, ...],
    pd: Any,
) -> tuple[DataFrame, tuple[str, ...]]:
    rows, forward_warnings = _forward_only_impact_rows(
        scenario,
        severity=severity,
        stress_term_structure=stress_term_structure,
        metrics=metrics,
        cfg=cfg,
        audit=context.audit,
        warning_codes=macro_warning_codes,
    )
    economic_rows, warnings = _economic_impact_rows(
        scenario,
        severity=severity,
        forward_ecl_term_structure=forward_ecl_term_structure,
        context=context,
        cfg=cfg,
        metrics=metrics,
        scenario_warning_codes=macro_warning_codes,
    )
    rows.extend(economic_rows)
    frame = pd.DataFrame.from_records(rows, columns=_IMPACT_COLUMNS)
    return _normalize_frame(frame), _dedupe((*forward_warnings, *warnings))


def _forward_only_impact_rows(
    scenario: StressScenarioConfig,
    *,
    severity: float,
    stress_term_structure: DataFrame,
    metrics: Sequence[StressMetric],
    cfg: StressConfig,
    audit: AuditSink | None,
    warning_codes: tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    rows: list[dict[str, Any]] = []
    warnings_seen: list[str] = []
    metric_columns = {
        "pd_marginal": ("pd_marginal_base", "pd_marginal_stress"),
        "pd_cumulative": ("pd_cumulative_base", "pd_cumulative_stress"),
        "lgd": ("lgd_base", "lgd_stress"),
    }
    grouped = stress_term_structure.copy(deep=True)
    grouped["_impact_period"] = [
        _positive_int(value, field_name="period") for value in grouped["period"].tolist()
    ]
    grouped["_impact_group_key"] = [_forward_impact_group_key(row) for _, row in grouped.iterrows()]
    for metric in metrics:
        if metric not in _FORWARD_ONLY_METRICS:
            continue
        base_col, stress_col = metric_columns[metric]
        for (period, group_key), group in grouped.groupby(
            ["_impact_period", "_impact_group_key"],
            sort=True,
            dropna=False,
        ):
            value_base = _mean_optional_probability(group[base_col].tolist(), metric=metric)
            value_stress = _mean_optional_probability(group[stress_col].tolist(), metric=metric)
            if value_base is None or value_stress is None:
                if metric == "lgd":
                    period_value = _positive_int(period, field_name="period")
                    message = (
                        f"{_FALTA_DATO_LGD}: output.metrics incluye 'lgd' pero "
                        "lgd/lgd_base no están disponibles para "
                        f"scenario={scenario.name!r}, period={period_value}."
                    )
                    _emit_falta_dato(
                        audit,
                        code=_FALTA_DATO_LGD,
                        blocked=cfg.validation.fail_on_falta_dato,
                        scenario=scenario.name,
                        factor=None,
                        periods=(period_value,),
                        reason="missing_lgd_metric_inputs",
                        message=message,
                        source="forward_term_structure",
                    )
                    if cfg.validation.fail_on_falta_dato:
                        raise StressFaltaDatoError(message)
                    warnings_seen.append(_FALTA_DATO_LGD)
                continue
            rows.append(
                _impact_row(
                    scenario,
                    severity=severity,
                    metric=metric,
                    value_base=value_base,
                    value_stress=value_stress,
                    period=_positive_int(period, field_name="period"),
                    group_key=str(group_key),
                    engine_source="forward_only",
                    warning_codes=_dedupe(
                        (
                            *warning_codes,
                            *_frame_warning_codes(group),
                        )
                    ),
                )
            )
    return rows, _dedupe(warnings_seen)


def _forward_impact_group_key(row: Any) -> str:
    payload = {
        "row_id": _group_value(row, "row_id"),
        "source_model": _group_value(row, "source_model"),
        "method": _group_value(row, "method"),
        "pd_source": _group_value(row, "pd_source"),
        "segment": _group_value(row, "segment"),
        "partition": _group_value(row, "partition"),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _group_value(row: Any, column: str) -> Any | None:
    value = row.get(column) if hasattr(row, "get") else getattr(row, column, None)
    if _is_missing(value):
        return None
    return _jsonable_hashable(_hashable_cell(value))


def _economic_impact_rows(
    scenario: StressScenarioConfig,
    *,
    severity: float,
    forward_ecl_term_structure: DataFrame,
    context: _RunContext,
    cfg: StressConfig,
    metrics: Sequence[StressMetric],
    scenario_warning_codes: tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    requested = set(metrics) & _ECONOMIC_METRICS
    if not requested:
        return [], ()
    if context.ecl_engine is None:
        message = "Métrica económica requiere ecl_engine conectado."
        _emit_falta_dato(
            context.audit,
            code=_WARNING_MISSING_ECL,
            blocked=cfg.validation.fail_on_missing_ecl_engine,
            scenario=scenario.name,
            factor=None,
            periods="all",
            reason="missing_ecl_engine",
            message=message,
            source="engine_dependency",
        )
        if cfg.validation.fail_on_missing_ecl_engine:
            raise StressDependencyError(message)
        return [], (_WARNING_MISSING_ECL,)

    baseline_term_structure = _scenario_term_structure(
        context.forward_term_structure,
        scenario_name=scenario.base_forward_scenario,
        pd=context.pd,
    )
    baseline_input = _clone_forward_ecl_input(
        context.forward_ecl_input,
        cfg=cfg,
        term_structure_frame=baseline_term_structure,
        scenario_weight_frame=_scenario_weight_frame(
            baseline_term_structure,
            scenario_name=scenario.base_forward_scenario,
            pd=context.pd,
        ),
    )
    stressed_term_structure = _scenario_term_structure(
        forward_ecl_term_structure,
        scenario_name=scenario.name,
        pd=context.pd,
    )
    stressed_input = _clone_forward_ecl_input(
        context.forward_ecl_input,
        cfg=cfg,
        term_structure_frame=stressed_term_structure,
        scenario_weight_frame=_scenario_weight_frame(
            stressed_term_structure,
            scenario_name=scenario.name,
            pd=context.pd,
        ),
    )
    baseline_ecl = _calculate_engine_frame(
        context.ecl_engine,
        baseline_input,
        field_name="ecl_base",
    )
    stressed_ecl = _calculate_engine_frame(
        context.ecl_engine,
        stressed_input,
        field_name="ecl_stress",
    )
    rows: list[dict[str, Any]] = []
    for metric in sorted(requested & _ECL_METRICS):
        rows.extend(
            _metric_rows_from_engine_frames(
                scenario,
                severity=severity,
                metric=metric,
                value_base_frame=baseline_ecl,
                value_stress_frame=stressed_ecl,
                engine_source="ecl_engine",
                warning_codes=scenario_warning_codes,
            )
        )
    if requested & _PROVISION_METRICS:
        if context.provision_engine is None:
            message = "Métrica provision requiere provision_engine conectado."
            _emit_falta_dato(
                context.audit,
                code=_WARNING_MISSING_ECL,
                blocked=cfg.validation.fail_on_missing_ecl_engine,
                scenario=scenario.name,
                factor=None,
                periods="all",
                reason="missing_provision_engine",
                message=message,
                source="engine_dependency",
            )
            if cfg.validation.fail_on_missing_ecl_engine:
                raise StressDependencyError(message)
            return rows, (_WARNING_MISSING_ECL,)
        baseline_provision = _calculate_engine_frame(
            context.provision_engine,
            baseline_ecl,
            field_name="provision_base",
        )
        stressed_provision = _calculate_engine_frame(
            context.provision_engine,
            stressed_ecl,
            field_name="provision_stress",
        )
        rows.extend(
            _metric_rows_from_engine_frames(
                scenario,
                severity=severity,
                metric="provision",
                value_base_frame=baseline_provision,
                value_stress_frame=stressed_provision,
                engine_source="provision_engine",
                warning_codes=scenario_warning_codes,
            )
        )
    return rows, ()


def _metric_rows_from_engine_frames(
    scenario: StressScenarioConfig,
    *,
    severity: float,
    metric: str,
    value_base_frame: DataFrame,
    value_stress_frame: DataFrame,
    engine_source: str,
    warning_codes: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    base_column = _metric_column(value_base_frame, metric=metric, field_name="baseline")
    stress_column = _metric_column(value_stress_frame, metric=metric, field_name="stress")
    if base_column != stress_column:
        raise StressOutputError(
            "El engine publicó aliases distintos entre baseline y stress "
            f"para métrica {metric!r}: baseline={base_column!r}, stress={stress_column!r}."
        )
    column = base_column
    base_values = _aggregate_metric_frame(value_base_frame, column=column, metric=metric)
    stress_values = _aggregate_metric_frame(value_stress_frame, column=column, metric=metric)
    if set(base_values) != set(stress_values):
        raise StressOutputError(
            "El engine publicó períodos/grupos inconsistentes entre baseline y stress "
            f"para métrica {metric!r}."
        )
    periods = tuple(dict.fromkeys((*base_values.keys(), *stress_values.keys())))
    return [
        _impact_row(
            scenario,
            severity=severity,
            metric=metric,
            value_base=base_values[key],
            value_stress=stress_values[key],
            period=key[0],
            group_key=key[1],
            engine_source=engine_source,
            warning_codes=warning_codes,
        )
        for key in periods
    ]


def _metric_column(frame: DataFrame, *, metric: str, field_name: str) -> str:
    matches = [column for column in _METRIC_COLUMNS[metric] if column in frame.columns]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise StressOutputError(
            f"El engine no publicó una columna reconocida en {field_name} para {metric!r}."
        )
    raise StressOutputError(
        f"El engine publicó columnas ambiguas en {field_name} para {metric!r}: {tuple(matches)}."
    )


def _aggregate_metric_frame(
    frame: DataFrame,
    *,
    column: str,
    metric: str,
) -> dict[tuple[int | None, str], float]:
    if frame.empty:
        raise StressOutputError(f"El engine publicó frame vacío para métrica {column!r}.")
    group_columns = _economic_group_columns(frame, metric_column=column)
    if "period" not in frame.columns:
        working_no_period = frame.copy(deep=True)
        working_no_period["_group_key"] = [
            _economic_group_key(row, group_columns=group_columns)
            for _, row in working_no_period.iterrows()
        ]
        return {
            (None, str(group_key)): _aggregate_metric_values(
                group[column].tolist(),
                column=column,
                metric=metric,
                period=None,
            )
            for group_key, group in working_no_period.groupby("_group_key", sort=True, dropna=False)
        }
    working = frame.copy(deep=True)
    working["_period"] = [
        _positive_int(value, field_name="period") for value in working["period"].tolist()
    ]
    working["_group_key"] = [
        _economic_group_key(row, group_columns=group_columns) for _, row in working.iterrows()
    ]
    values: dict[tuple[int | None, str], float] = {}
    for (period, group_key), group in working.groupby(
        ["_period", "_group_key"],
        sort=True,
        dropna=False,
    ):
        normalized_period = _positive_int(period, field_name="period")
        values[(normalized_period, str(group_key))] = _aggregate_metric_values(
            group[column].tolist(),
            column=column,
            metric=metric,
            period=normalized_period,
        )
    return values


def _economic_group_columns(frame: DataFrame, *, metric_column: str) -> tuple[str, ...]:
    group_columns: list[str] = []
    unexpected_columns: list[str] = []
    for raw_column in frame.columns:
        column = str(raw_column)
        if (
            column == metric_column
            or column in _ECONOMIC_GROUP_EXCLUDED_COLUMNS
            or column in _ECONOMIC_ENGINE_MEASURE_COLUMNS
        ):
            continue
        if column in _ECONOMIC_GROUP_DIMENSION_COLUMNS:
            group_columns.append(column)
            continue
        unexpected_columns.append(column)
    if unexpected_columns:
        unique_columns = tuple(dict.fromkeys(unexpected_columns))
        raise StressOutputError(
            f"El engine económico publicó columnas no soportadas para agrupación: {unique_columns}."
        )
    return tuple(dict.fromkeys(group_columns))


def _economic_group_key(row: Any, *, group_columns: tuple[str, ...]) -> str:
    if not group_columns:
        return "portfolio"
    payload = {column: _group_value(row, column) for column in group_columns}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _aggregate_metric_values(
    values: Sequence[Any],
    *,
    column: str,
    metric: str,
    period: int | None,
) -> float:
    if metric == "ratio":
        observed = [_required_float(value, field_name=column) for value in values]
        if len(observed) != 1:
            period_label = "agregado" if period is None else f"period={period}"
            raise StressOutputError(
                "ratio exige una salida ya agregada única por período; "
                f"{period_label} publicó {len(observed)} filas."
            )
        return _non_negative_metric_sum(observed, field_name=column)
    return _non_negative_metric_sum(values, field_name=column)


def _period_equals(frame: DataFrame, period: int) -> Any:
    return frame["period"].map(lambda value: _positive_int(value, field_name="period")) == period


def _impact_row(
    scenario: StressScenarioConfig,
    *,
    severity: float,
    metric: str,
    value_base: float,
    value_stress: float,
    period: int | None,
    group_key: str = "portfolio",
    engine_source: str,
    warning_codes: tuple[str, ...],
) -> dict[str, Any]:
    absolute_delta = _clean_float(value_stress - value_base, field_name="absolute_delta")
    relative_delta = None
    if not math.isclose(value_base, 0.0, rel_tol=0.0, abs_tol=_FLOAT_ATOL):
        relative_delta = _clean_float(absolute_delta / value_base, field_name="relative_delta")
    return {
        "stress_scenario": scenario.name,
        "scenario_kind": scenario.kind,
        "severity": severity,
        "metric": metric,
        "value_base": value_base,
        "value_stress": value_stress,
        "absolute_delta": absolute_delta,
        "relative_delta": relative_delta,
        "group_key": group_key,
        "period": period,
        "engine_source": engine_source,
        "warning_codes": warning_codes,
    }


def _clone_forward_ecl_input(
    forward_ecl_input: ForwardEclInput,
    *,
    cfg: StressConfig,
    term_structure_frame: DataFrame,
    scenario_weight_frame: DataFrame | None = None,
) -> ForwardEclInput:
    pd = _import_pandas()
    _validate_forward_ecl_input_contract(forward_ecl_input, cfg=cfg, pd=pd)
    frame_copy = term_structure_frame.copy(deep=True)
    updates: dict[str, Any] = {"term_structure_frame": frame_copy}
    weight_copy = None if scenario_weight_frame is None else scenario_weight_frame.copy(deep=True)
    if weight_copy is not None:
        updates["scenario_weight_frame"] = weight_copy
    model_copy = getattr(forward_ecl_input, "model_copy", None)
    if callable(model_copy):
        try:
            copied = cast("ForwardEclInput", model_copy(update=updates, deep=True))
        except Exception as exc:
            raise StressDependencyError("forward_ecl_input.model_copy(update=...) falló.") from exc
        _validate_forward_ecl_input_contract(copied, cfg=cfg, pd=pd)
        _validate_cloned_forward_ecl_input(
            copied,
            cfg=cfg,
            term_structure_frame=frame_copy,
            scenario_weight_frame=weight_copy,
            pd=pd,
        )
        return copied
    cloned: Any = copy.deepcopy(forward_ecl_input)
    try:
        cloned.term_structure_frame = frame_copy
        if weight_copy is not None:
            cloned.scenario_weight_frame = weight_copy
    except (AttributeError, TypeError) as exc:
        raise StressDependencyError(
            "forward_ecl_input debe soportar model_copy(update=...) o atributos "
            "term_structure_frame/scenario_weight_frame."
        ) from exc
    _validate_forward_ecl_input_contract(cloned, cfg=cfg, pd=pd)
    _validate_cloned_forward_ecl_input(
        cloned,
        cfg=cfg,
        term_structure_frame=frame_copy,
        scenario_weight_frame=weight_copy,
        pd=pd,
    )
    return cast("ForwardEclInput", cloned)


def _validate_cloned_forward_ecl_input(
    forward_ecl_input: ForwardEclInput,
    *,
    cfg: StressConfig,
    term_structure_frame: DataFrame,
    scenario_weight_frame: DataFrame | None,
    pd: Any,
) -> None:
    cloned_term = _forward_ecl_attr(
        forward_ecl_input,
        "term_structure_frame",
        field_name="forward_ecl_input.term_structure_frame",
    )
    if not isinstance(cloned_term, pd.DataFrame):
        raise StressDependencyError(
            "forward_ecl_input.model_copy(update=...) no aplicó term_structure_frame."
        )
    cloned_term_hash = _maybe_forward_term_frame_hash(
        cloned_term,
        cfg=cfg,
        key_columns=_FORWARD_TERM_HASH_KEY_COLUMNS,
        field_name="forward_ecl_input.term_structure_frame",
        pd=pd,
    )
    expected_term_hash = _maybe_forward_term_frame_hash(
        term_structure_frame,
        cfg=cfg,
        key_columns=_FORWARD_TERM_HASH_KEY_COLUMNS,
        field_name="term_structure_frame",
        pd=pd,
    )
    if cloned_term_hash != expected_term_hash:
        raise StressDependencyError(
            "forward_ecl_input.model_copy(update=...) no aplicó term_structure_frame."
        )
    if scenario_weight_frame is None:
        return
    cloned_weight_frame = _forward_ecl_attr(
        forward_ecl_input,
        "scenario_weight_frame",
        field_name="forward_ecl_input.scenario_weight_frame",
    )
    cloned_weight_hash = _maybe_scenario_weight_frame_hash(
        cloned_weight_frame,
        key_columns=_SCENARIO_WEIGHT_HASH_KEY_COLUMNS,
        field_name="forward_ecl_input.scenario_weight_frame",
        pd=pd,
    )
    expected_weight_hash = _maybe_scenario_weight_frame_hash(
        scenario_weight_frame,
        key_columns=_SCENARIO_WEIGHT_HASH_KEY_COLUMNS,
        field_name="scenario_weight_frame",
        pd=pd,
    )
    if cloned_weight_hash != expected_weight_hash:
        raise StressDependencyError(
            "forward_ecl_input.model_copy(update=...) no aplicó scenario_weight_frame."
        )


def _scenario_term_structure(
    frame: DataFrame,
    *,
    scenario_name: str,
    pd: Any,
) -> DataFrame:
    scenario_mask = frame["scenario"].astype(str) == scenario_name
    selected = frame.loc[scenario_mask].copy(deep=True)
    if selected.empty:
        raise StressInputError(f"forward_term_structure no contiene scenario={scenario_name!r}.")
    selected["_ordinal"] = range(len(selected.index))
    selected = _sort_term_structure(selected)
    selected.loc[:, "period"] = [
        _positive_int(value, field_name="period") for value in selected["period"].tolist()
    ]
    selected.loc[:, "scenario_weight"] = 1.0
    _insert_lgd_from_base_if_available(selected)
    return selected.drop(columns=["_ordinal"], errors="ignore").reset_index(drop=True)


def _scenario_weight_frame(
    term_structure_frame: DataFrame,
    *,
    scenario_name: str,
    pd: Any,
) -> DataFrame:
    weights = tuple(
        _required_float(value, field_name="scenario_weight")
        for value in term_structure_frame["scenario_weight"].tolist()
    )
    if not weights:
        raise StressInputError(f"scenario_weight vacío para scenario={scenario_name!r}.")
    first = weights[0]
    if any(
        not math.isclose(weight, first, rel_tol=0.0, abs_tol=_FLOAT_ATOL) for weight in weights[1:]
    ):
        raise StressInputError(
            "scenario_weight debe ser constante dentro de cada input económico "
            f"para scenario={scenario_name!r}."
        )
    return cast(
        "DataFrame",
        pd.DataFrame.from_records(
            [
                {
                    "scenario": scenario_name,
                    "weight": first,
                    "is_default": False,
                    "source": "config",
                    "description": f"Peso económico comparable para {scenario_name}",
                }
            ],
            columns=_SCENARIO_WEIGHT_COLUMNS,
        ),
    )


def _calculate_engine_frame(engine: object, payload: object, *, field_name: str) -> DataFrame:
    pd = _import_pandas()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            frame = engine.calculate(payload)  # type: ignore[attr-defined]
    except Warning as exc:
        raise StressDependencyError(f"{field_name} emitió warning tratado como error.") from exc
    if not isinstance(frame, pd.DataFrame):
        raise StressDependencyError(f"{field_name} debe retornar pandas.DataFrame.")
    _validate_engine_output_columns(frame, field_name=field_name)
    _validate_no_nonfinite(frame, field_name=field_name)
    return _normalize_frame(frame)


def _validate_engine_output_columns(frame: DataFrame, *, field_name: str) -> None:
    observed_columns = tuple(str(column) for column in frame.columns)
    duplicated_columns = _duplicated_columns(observed_columns)
    if duplicated_columns:
        raise StressOutputError(
            f"{field_name} no puede publicar columnas duplicadas: {duplicated_columns}."
        )


def _forward_ecl_row(
    row: Any,
    *,
    scenario: StressScenarioConfig,
    hazard: float,
    survival: float,
    pd_marginal: float,
    pd_cumulative: float,
    lgd: float | None,
    satellite_adjustment: float,
    warning_codes: tuple[str, ...],
) -> dict[str, Any]:
    record = dict(row.drop(labels=["_ordinal"], errors="ignore"))
    record["scenario"] = scenario.name
    if "period" in record:
        record["period"] = _positive_int(record["period"], field_name="period")
    if "scenario_weight" in record:
        record["scenario_weight"] = (
            scenario.weight if scenario.weight is not None else record["scenario_weight"]
        )
    record["hazard"] = hazard
    record["survival"] = survival
    record["pd_marginal"] = pd_marginal
    record["pd_cumulative"] = pd_cumulative
    if "lgd" in record or (lgd is not None and "lgd_base" in record):
        record["lgd"] = lgd
    if "satellite_adjustment" in record:
        record["satellite_adjustment"] = satellite_adjustment
    if "warning_codes" in record:
        record["warning_codes"] = warning_codes
    return record


def _forward_ecl_columns(
    base_columns: Iterable[Any], rows: Sequence[Mapping[str, Any]]
) -> tuple[str, ...]:
    columns = [str(column) for column in base_columns]
    if any("lgd" in row for row in rows) and "lgd" not in columns:
        insert_at = _forward_lgd_insert_position(columns)
        columns.insert(insert_at, "lgd")
    return tuple(columns)


def _insert_lgd_from_base_if_available(frame: DataFrame) -> None:
    if "lgd" in frame.columns or "lgd_base" not in frame.columns:
        return
    values = frame["lgd_base"].tolist()
    if all(_is_missing(value) for value in values):
        return
    columns = [str(column) for column in frame.columns]
    frame.insert(_forward_lgd_insert_position(columns), "lgd", frame["lgd_base"])


def _forward_lgd_insert_position(columns: Sequence[str]) -> int:
    for anchor in ("lgd_base", "pd_basis"):
        if anchor in columns:
            return columns.index(anchor)
    return len(columns)


def _sensitivity_scenario(sweep: SensitivitySweepConfig) -> StressScenarioConfig:
    """Construye el escenario sintético ``custom`` que ejecuta un barrido de sensibilidad."""
    return StressScenarioConfig(
        name=sweep.name,
        kind="custom",
        base_forward_scenario=sweep.base_forward_scenario,
        shocks=(
            StressShockConfig(
                factor=sweep.factor,
                operation=sweep.operation,
                value=sweep.shock_value,
                source="user",
            ),
        ),
        require_dominates_forward_adverse=False,
    )


def _reverse_base_forward_scenario(cfg: StressConfig, target: StressTargetConfig) -> str:
    """Resuelve el escenario forward base honrando ``target.scenario_name`` (SDD-21 §5).

    ``target.scenario_name`` referencia un escenario de stress declarado (config §5 y
    ``_check_reverse_targets``); reverse stress ancla ``M(a)`` en su ``base_forward_scenario``. El
    escenario forward base define el macro y la term-structure del cálculo, por lo que ignorarlo
    cambiaría el número regulatorio en silencio. Si el nombre no existe, se levanta el error del SDD
    en vez de degradar a un escenario por default.
    """
    for scenario in cfg.scenarios:
        if scenario.name.strip() == target.scenario_name.strip():
            return scenario.base_forward_scenario
    raise StressScenarioError(
        f"El target {target.name!r} referencia scenario_name={target.scenario_name!r}, "
        "ausente en stress.scenarios; reverse stress exige un escenario de stress declarado."
    )


def _reverse_scenario(
    target: StressTargetConfig,
    reverse: ReverseStressConfig,
    *,
    base_forward_scenario: str,
) -> StressScenarioConfig:
    """Construye el escenario sintético ``custom`` que evalúa ``M(a)`` para reverse stress.

    ``base_forward_scenario`` proviene del escenario de stress referido por ``target.scenario_name``
    (ver :func:`_reverse_base_forward_scenario`): define el macro y la term-structure sobre los que
    se calcula ``M(a)``, por lo que honrarlo es requisito regulatorio y no un detalle cosmético.
    """
    return StressScenarioConfig(
        name=target.name,
        kind="custom",
        base_forward_scenario=base_forward_scenario,
        shocks=(
            StressShockConfig(
                factor=reverse.factor,
                operation=reverse.operation,
                value=reverse.shock_value,
                source="user",
            ),
        ),
        require_dominates_forward_adverse=False,
    )


def _reverse_satisfies(value: float, direction: str, threshold: float) -> bool:
    """Indica si ``value`` cumple el target en la dirección declarada, dentro de tolerancia."""
    if math.isclose(value, threshold, rel_tol=_FLOAT_ATOL, abs_tol=_FLOAT_ATOL):
        return True
    if direction == "at_least":
        return value > threshold
    return value < threshold


def _reverse_metric_value(
    impact_frame: DataFrame,
    *,
    target: StressTargetConfig,
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    """Agrega ``M(a)`` desde el impact frame según ``target.metric`` y ``target.group_filter``."""
    values: list[Any] = []
    sources: list[str] = []
    warnings_seen: list[str] = []
    for row in _iter_impact_rows(impact_frame):
        if not _reverse_row_matches_filter(row, target.group_filter):
            continue
        values.append(row["value_stress"])
        sources.append(str(row["engine_source"]))
        warnings_seen.extend(_warning_tuple(row["warning_codes"]))
    if not values:
        raise ReverseStressError(
            f"El target {target.name!r} no produjo filas de métrica {target.metric!r} "
            f"para el filtro de grupo {target.group_filter!r}."
        )
    value = _aggregate_sweep_metric(values, metric=target.metric)
    return value, _dedupe_iterable(sources), _dedupe(warnings_seen)


def _reverse_row_matches_filter(
    row: Mapping[str, Any],
    group_filter: Mapping[str, Any],
) -> bool:
    """Filtra una fila de impacto por ``group_filter`` (period, engine_source o dimensiones)."""
    if not group_filter:
        return True
    view: dict[str, Any] = {
        "period": row["period"],
        "engine_source": row["engine_source"],
    }
    parsed = _parse_impact_group_key(row["group_key"])
    if parsed is not None:
        view.update(parsed)
    return all(view.get(key) == value for key, value in group_filter.items())


def _reverse_path_row(
    target_name: str,
    iteration: int,
    lo: float,
    hi: float,
    mid: float,
    metric_value: float,
    threshold: float,
    decision: str,
) -> dict[str, Any]:
    """Construye una fila del path de bisección reverse (``stress.reverse_path``, SDD-21 §6)."""
    return {
        "target_name": target_name,
        "iteration": iteration,
        "lo": lo,
        "hi": hi,
        "mid": mid,
        "metric_value": metric_value,
        "threshold": threshold,
        "decision": decision,
    }


def _reverse_path_frame(rows: list[dict[str, Any]], *, pd: Any) -> DataFrame:
    """Construye el frame tidy ``stress.reverse_path`` con las columnas canónicas SDD-21 §6."""
    frame = pd.DataFrame.from_records(rows, columns=_REVERSE_PATH_COLUMNS)
    return _normalize_frame(frame)


def _validate_unique_sensitivity_names(cfg: StressConfig) -> None:
    """Valida que los nombres de barridos sean únicos y no colisionen con escenarios."""
    scenario_names = {scenario.name for scenario in cfg.scenarios}
    seen: set[str] = set()
    for sweep in cfg.sensitivities:
        if sweep.name in scenario_names:
            raise StressScenarioError(
                f"El barrido {sweep.name!r} colisiona con un escenario de stress del mismo nombre."
            )
        if sweep.name in seen:
            raise StressScenarioError(
                f"stress.sensitivities no puede repetir el nombre de barrido {sweep.name!r}."
            )
        seen.add(sweep.name)


def _iter_impact_rows(frame: DataFrame) -> Iterable[dict[str, Any]]:
    """Itera un impact frame tidy como dicts keyed por columnas canónicas SDD-21 §6."""
    for row in frame.itertuples(index=False):
        yield dict(zip(_IMPACT_COLUMNS, row, strict=True))


def _aggregate_sweep_impacts(
    metric_rows: list[dict[str, Any]],
    *,
    sweep: SensitivitySweepConfig,
) -> list[dict[str, Any]]:
    """Reagrega los impactos de una severidad según ``group_cols`` (agregación real)."""
    buckets: dict[tuple[str, str, Any], dict[str, Any]] = {}
    order: list[tuple[str, str, Any]] = []
    for row in metric_rows:
        coarse_key = _sweep_group_key(row, sweep=sweep)
        key = (str(row["engine_source"]), coarse_key, row["period"])
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {"value_base": [], "value_stress": [], "warning_codes": []}
            buckets[key] = bucket
            order.append(key)
        bucket["value_base"].append(row["value_base"])
        bucket["value_stress"].append(row["value_stress"])
        bucket["warning_codes"].extend(_warning_tuple(row["warning_codes"]))
    aggregated: list[dict[str, Any]] = []
    for engine_source, coarse_key, period in order:
        bucket = buckets[(engine_source, coarse_key, period)]
        aggregated.append(
            {
                "engine_source": engine_source,
                "group_key": coarse_key,
                "period": period,
                "value_base": _aggregate_sweep_metric(bucket["value_base"], metric=sweep.metric),
                "value_stress": _aggregate_sweep_metric(
                    bucket["value_stress"], metric=sweep.metric
                ),
                "warning_codes": _dedupe(bucket["warning_codes"]),
            }
        )
    return aggregated


def _sweep_group_key(row: Mapping[str, Any], *, sweep: SensitivitySweepConfig) -> str:
    """Deriva la clave de grupo del barrido restringida a ``group_cols``."""
    payload: dict[str, Any] = {}
    parsed: dict[str, Any] | None = None
    parsed_ready = False
    for column in sweep.group_cols:
        if column == "scenario":
            payload[column] = sweep.name
            continue
        if not parsed_ready:
            parsed = _parse_impact_group_key(row["group_key"])
            parsed_ready = True
        if parsed is None or column not in parsed:
            raise StressEngineError(
                f"El barrido {sweep.name!r} agrupa por {column!r}, pero el impacto no publicó esa "
                f"dimensión (group_key={row['group_key']!r})."
            )
        payload[column] = parsed[column]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_impact_group_key(group_key: Any) -> dict[str, Any] | None:
    """Parsea el ``group_key`` del impacto a dict cuando es un JSON de objeto."""
    if not isinstance(group_key, str):
        return None
    try:
        parsed = json.loads(group_key)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, dict):
        return cast("dict[str, Any]", parsed)
    return None


def _aggregate_sweep_metric(values: list[Any], *, metric: str) -> float:
    """Agrega la métrica del barrido: suma económica, media de probabilidad, ratio único."""
    numeric = [_required_float(value, field_name=f"sensitivity.{metric}") for value in values]
    if metric == "ratio":
        if len(numeric) != 1:
            raise StressOutputError(
                "El barrido de métrica 'ratio' exige una fila agregada única por grupo/período; "
                f"se recibieron {len(numeric)}."
            )
        return _clean_float(numeric[0], field_name="sensitivity.ratio")
    if metric in _FORWARD_ONLY_METRICS:
        return _clean_float(math.fsum(numeric) / len(numeric), field_name=f"sensitivity.{metric}")
    return _clean_float(math.fsum(numeric), field_name=f"sensitivity.{metric}")


def _sensitivity_frame(
    per_severity: list[tuple[float, list[dict[str, Any]]]],
    *,
    sweep: SensitivitySweepConfig,
    pd: Any,
) -> DataFrame:
    """Construye el impact frame tidy del barrido con ``scenario_kind='sensitivity'``."""
    rows: list[dict[str, Any]] = []
    for severity, aggregated in per_severity:
        for coarse in aggregated:
            rows.append(_sensitivity_impact_row(sweep=sweep, severity=severity, coarse=coarse))
    frame = pd.DataFrame.from_records(rows, columns=_IMPACT_COLUMNS)
    return _normalize_frame(frame)


def _sensitivity_impact_row(
    *,
    sweep: SensitivitySweepConfig,
    severity: float,
    coarse: Mapping[str, Any],
) -> dict[str, Any]:
    """Construye una fila de impacto tidy del barrido de sensibilidad."""
    value_base = coarse["value_base"]
    value_stress = coarse["value_stress"]
    absolute_delta = _clean_float(value_stress - value_base, field_name="absolute_delta")
    relative_delta: float | None = None
    if not math.isclose(value_base, 0.0, rel_tol=0.0, abs_tol=_FLOAT_ATOL):
        relative_delta = _clean_float(absolute_delta / value_base, field_name="relative_delta")
    return {
        "stress_scenario": sweep.name,
        "scenario_kind": "sensitivity",
        "severity": severity,
        "metric": sweep.metric,
        "value_base": value_base,
        "value_stress": value_stress,
        "absolute_delta": absolute_delta,
        "relative_delta": relative_delta,
        "group_key": coarse["group_key"],
        "period": coarse["period"],
        "engine_source": coarse["engine_source"],
        "warning_codes": coarse["warning_codes"],
    }


def _sensitivity_baseline_frame(
    per_severity: list[tuple[float, list[dict[str, Any]]]],
    *,
    sweep: SensitivitySweepConfig,
    pd: Any,
) -> DataFrame:
    """Construye el baseline público ``M(x)`` (value_base) por grupo/período del barrido."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, aggregated in per_severity:
        for coarse in aggregated:
            period_label = json.dumps(coarse["period"])
            key = (str(coarse["engine_source"]), str(coarse["group_key"]), period_label)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "sweep_name": sweep.name,
                    "factor": sweep.factor,
                    "metric": sweep.metric,
                    "engine_source": coarse["engine_source"],
                    "group_key": coarse["group_key"],
                    "period_label": period_label,
                    "value_base": coarse["value_base"],
                }
            )
    frame = pd.DataFrame.from_records(rows, columns=_SENSITIVITY_BASELINE_COLUMNS)
    return _normalize_frame(frame)


def _sweep_monotonicity_flag(
    per_severity: list[tuple[float, list[dict[str, Any]]]],
    *,
    tol: float,
) -> Literal["increasing", "decreasing", "flat", "non_monotonic"]:
    """Clasifica la monotonicidad por grupo/período/engine, excluyendo severidad y escenario."""
    sequences: dict[tuple[str, str, Any], list[float]] = {}
    order: list[tuple[str, str, Any]] = []
    for _, aggregated in per_severity:
        for coarse in aggregated:
            key = (str(coarse["engine_source"]), str(coarse["group_key"]), coarse["period"])
            if key not in sequences:
                sequences[key] = []
                order.append(key)
            sequences[key].append(coarse["value_stress"])
    flags = [_classify_monotonicity(sequences[key], tol=tol) for key in order]
    return _combine_monotonicity(flags)


def _classify_monotonicity(
    values: list[float],
    *,
    tol: float,
) -> Literal["increasing", "decreasing", "flat", "non_monotonic"]:
    """Clasifica una secuencia ordenada por severidad ascendente dentro de una tolerancia."""
    increasing = False
    decreasing = False
    for index in range(1, len(values)):
        delta = values[index] - values[index - 1]
        if delta > tol:
            increasing = True
        elif delta < -tol:
            decreasing = True
    if increasing and decreasing:
        return "non_monotonic"
    if increasing:
        return "increasing"
    if decreasing:
        return "decreasing"
    return "flat"


def _combine_monotonicity(
    flags: list[Literal["increasing", "decreasing", "flat", "non_monotonic"]],
) -> Literal["increasing", "decreasing", "flat", "non_monotonic"]:
    """Combina las clasificaciones por grupo en una sola bandera del barrido."""
    if "non_monotonic" in flags:
        return "non_monotonic"
    directions = {flag for flag in flags if flag in ("increasing", "decreasing")}
    if len(directions) > 1:
        return "non_monotonic"
    if "increasing" in directions:
        return "increasing"
    if "decreasing" in directions:
        return "decreasing"
    return "flat"


def _build_card(
    *,
    scenario_results: tuple[StressScenarioResult, ...],
    sensitivity_results: tuple[StressSensitivityResult, ...],
    reverse_results: tuple[ReverseStressResult, ...],
    stress_impact: DataFrame,
    stress_scenarios: DataFrame,
    stress_term_structure: DataFrame | None,
    diagnostics: StressDiagnostics,
) -> StressCard:
    metric_names = tuple(dict.fromkeys(str(value) for value in stress_impact["metric"].tolist()))
    term_rows = 0 if stress_term_structure is None else len(stress_term_structure.index)
    scenario_sources = tuple(
        dict.fromkeys(str(value) for value in stress_scenarios["source"].tolist())
    )
    sensitivity_rows = sum(len(result.sensitivity_frame.index) for result in sensitivity_results)
    reverse_rows = sum(len(result.reverse_path_frame.index) for result in reverse_results)
    return StressCard(
        summary={
            "scenario_count": len(scenario_results),
            "sensitivity_count": len(sensitivity_results),
            "reverse_count": len(reverse_results),
            "scenario_rows": len(stress_scenarios.index),
            "impact_rows": len(stress_impact.index),
            "term_structure_rows": term_rows,
            "has_falta_dato": bool(diagnostics.falta_dato_codes),
        },
        metric_sections={
            "scenario_impacts": {
                "metrics": metric_names,
                "rows": len(stress_impact.index),
            },
            "stress_scenarios": {
                "rows": len(stress_scenarios.index),
                "sources": scenario_sources,
            },
            "sensitivity_curves": {
                "sweeps": tuple(result.sweep_name for result in sensitivity_results),
                "monotonicity": tuple(result.monotonicity_flag for result in sensitivity_results),
                "rows": sensitivity_rows,
            },
            "reverse_stress": {
                "targets": tuple(result.target_name for result in reverse_results),
                "converged": tuple(result.converged for result in reverse_results),
                "iterations": tuple(result.iterations for result in reverse_results),
                "rows": reverse_rows,
            },
            "term_structure_summary": {
                "published": stress_term_structure is not None,
                "rows": term_rows,
            },
            "falta_dato": {"codes": diagnostics.falta_dato_codes},
        },
        assumptions=("Stress determinista sin Monte Carlo en B21.3/B21.4/B21.5.",),
        limitations=(
            "Reverse stress por bisección monotónica determinista; sin optimizadores heurísticos.",
        ),
    )


def _emit_scenario_config(
    audit: AuditSink | None,
    *,
    scenario: StressScenarioConfig,
    severity: float,
) -> None:
    shocks = tuple(
        {
            "scenario": scenario.name,
            "factor": shock.factor,
            "operation": shock.operation,
            "severity": severity,
            "periods": shock.periods if shock.periods == "all" else tuple(shock.periods),
            "source": shock.source,
            "shock_value": shock.value,
        }
        for shock in scenario.shocks
    )
    _emit_audit_decision(
        audit,
        regla="stress_scenario_config",
        umbral={
            "scenario": scenario.name,
            "kind": scenario.kind,
            "base_forward_scenario": scenario.base_forward_scenario,
        },
        valor={
            "severity": severity,
            "shocks": shocks,
            "require_dominates_forward_adverse": scenario.require_dominates_forward_adverse,
        },
        accion="configure",
    )


def _emit_falta_dato(
    audit: AuditSink | None,
    *,
    code: str,
    blocked: bool,
    scenario: str,
    factor: str | None,
    periods: tuple[int, ...] | Literal["all"],
    reason: str,
    message: str,
    source: str,
) -> None:
    _emit_audit_decision(
        audit,
        regla="stress_falta_dato",
        umbral={"code": code, "blocked": blocked},
        valor={
            "scenario": scenario,
            "factor": factor,
            "periods": periods,
            "reason": reason,
            "source": source,
            "message": message,
        },
        accion="block" if blocked else "warn",
    )


def _emit_audit_decision(
    audit: AuditSink | None,
    *,
    regla: str,
    umbral: Mapping[str, Any],
    valor: Mapping[str, Any],
    accion: str,
) -> None:
    if audit is None:
        return
    from nikodym.core.audit import AuditEvent

    audit.emit(
        AuditEvent(
            kind="decision",
            step="stress",
            payload={
                "regla": regla,
                "umbral": dict(umbral),
                "valor": dict(valor),
                "accion": accion,
            },
            ts=datetime.now(tz=UTC),
        )
    )


def _emit_size_estimate(
    audit: AuditSink | None,
    *,
    cfg: StressConfig,
    macro_rows: int,
    term_structure_rows: int,
) -> None:
    scenario_count = len(cfg.scenarios)
    sensitivity_evaluations = sum(len(sweep.severity_grid) for sweep in cfg.sensitivities)
    reverse_evaluations = sum(
        len(reverse.monotonicity_check_points) + 2 + reverse.max_iterations
        for reverse in cfg.reverse
        if reverse.enabled
    )
    _emit_audit_decision(
        audit,
        regla="stress_size_estimate",
        umbral={
            "expression": "term_structure_rows * (scenario_count + sensitivity_evaluations)",
            "configurable_limit": None,
        },
        valor={
            "macro_rows": macro_rows,
            "term_structure_rows": term_structure_rows,
            "scenario_count": scenario_count,
            "sensitivity_count": len(cfg.sensitivities),
            "estimated_stress_term_structure_rows": term_structure_rows
            * (scenario_count + sensitivity_evaluations),
            "estimated_sensitivity_evaluations": sensitivity_evaluations,
            "estimated_reverse_evaluations": reverse_evaluations,
            "scope": "B21.3-B21.5 scenarios + sensitivity + reverse",
        },
        accion="diagnose",
    )


def _term_structure_audit_payload(frame: DataFrame) -> dict[str, Any]:
    return {
        "row_count": len(frame.index),
        "probability_ranges": {
            column: _finite_range(frame, column)
            for column in (
                "hazard_base",
                "hazard_stress",
                "survival_stress",
                "pd_marginal_base",
                "pd_marginal_stress",
                "pd_cumulative_base",
                "pd_cumulative_stress",
                "lgd_base",
                "lgd_stress",
            )
            if column in frame.columns
        },
        "basis": tuple(dict.fromkeys(str(value) for value in frame["pd_basis"].tolist())),
        "basis_state": tuple(dict.fromkeys(str(value) for value in frame["basis_state"].tolist())),
        "warning_codes": _frame_warning_codes(frame),
    }


def _finite_range(frame: DataFrame, column: str) -> dict[str, float] | None:
    values = [
        _required_float(value, field_name=column)
        for value in frame[column].tolist()
        if not _is_missing(value)
    ]
    if not values:
        return None
    return {"min": min(values), "max": max(values)}


def _concat_optional_frames(
    frames: tuple[DataFrame | None, ...],
    *,
    columns: tuple[str, ...],
    pd: Any,
) -> DataFrame:
    present = [frame for frame in frames if frame is not None and len(frame.index) > 0]
    if not present:
        return cast("DataFrame", pd.DataFrame(columns=columns))
    return _normalize_frame(pd.concat(present, ignore_index=True).loc[:, list(columns)])


def _concat_required_frames(
    frames: tuple[DataFrame, ...],
    *,
    columns: tuple[str, ...],
    pd: Any,
) -> DataFrame:
    present = [frame for frame in frames if len(frame.index) > 0]
    if not present:
        return cast("DataFrame", pd.DataFrame(columns=columns))
    return _normalize_frame(pd.concat(present, ignore_index=True).loc[:, list(columns)])


def _validate_macro_projection_values(
    frame: DataFrame,
    *,
    metric_tol: float = _FLOAT_ATOL,
    pd: Any | None = None,
) -> None:
    pd = _import_pandas() if pd is None else pd
    _require_columns(frame, _MACRO_PROJECTION_REQUIRED_COLUMNS, field_name="macro_projection")
    scenario_weights: list[float] = []
    time_values: list[float] = []
    projected_values: list[float] = []
    model_values: list[float] = []
    shock_values: list[float] = []
    reasonable_supportable_values: list[bool] = []
    warning_codes_values: list[tuple[str, ...]] = []
    for row in frame.itertuples(index=False):
        row_any = cast("Any", row)
        period = _positive_int(row_any.period, field_name="period")
        scenario = _validate_non_empty_text(row_any.scenario, field_name="scenario")
        macro_variable = _validate_non_empty_text(
            row_any.macro_variable,
            field_name="macro_variable",
        )
        scenario_weights.append(
            _required_non_negative_float(
                row_any.scenario_weight,
                field_name="macro_projection.scenario_weight",
            )
        )
        time_values.append(
            _required_non_negative_float(
                row_any.time_value,
                field_name="macro_projection.time_value",
            )
        )
        projected, model, shock = _macro_projected_values(
            projected_value=row_any.projected_value,
            model_value=row_any.model_value,
            shock_value=row_any.shock_value,
            scenario=scenario,
            macro_variable=macro_variable,
            period=period,
            metric_tol=metric_tol,
        )
        projected_values.append(projected)
        model_values.append(model)
        shock_values.append(shock)
        _validate_non_empty_text(row_any.method, field_name="macro_projection.method")
        _validate_non_empty_text(row_any.model_id, field_name="macro_projection.model_id")
        reasonable_supportable_values.append(
            _required_bool(
                row_any.is_reasonable_supportable,
                field_name="macro_projection.is_reasonable_supportable",
            )
        )
        warning_codes_values.append(
            _validate_warning_codes_input(
                row_any.warning_codes,
                field_name="macro_projection.warning_codes",
            )
        )

    frame["scenario_weight"] = pd.Series(scenario_weights, index=frame.index, dtype=float)
    frame["time_value"] = pd.Series(time_values, index=frame.index, dtype=float)
    frame["projected_value"] = pd.Series(projected_values, index=frame.index, dtype=float)
    frame["model_value"] = pd.Series(model_values, index=frame.index, dtype=float)
    frame["shock_value"] = pd.Series(shock_values, index=frame.index, dtype=float)
    frame["is_reasonable_supportable"] = pd.Series(
        reasonable_supportable_values,
        index=frame.index,
        dtype=object,
    )
    frame["warning_codes"] = pd.Series(
        warning_codes_values,
        index=frame.index,
        dtype=object,
    )


def _macro_projected_delta(
    *,
    projected_value: Any,
    model_value: Any,
    shock_value: Any,
    scenario: str,
    macro_variable: str,
    period: int,
    metric_tol: float,
) -> float:
    return _macro_projected_values(
        projected_value=projected_value,
        model_value=model_value,
        shock_value=shock_value,
        scenario=scenario,
        macro_variable=macro_variable,
        period=period,
        metric_tol=metric_tol,
    )[2]


def _macro_projected_values(
    *,
    projected_value: Any,
    model_value: Any,
    shock_value: Any,
    scenario: str,
    macro_variable: str,
    period: int,
    metric_tol: float,
) -> tuple[float, float, float]:
    projected = _required_float(projected_value, field_name="macro_projection.projected_value")
    model = _required_float(model_value, field_name="macro_projection.model_value")
    shock = _required_float(shock_value, field_name="macro_projection.shock_value")
    expected = _clean_float(model + shock, field_name="macro_projection.model_plus_shock")
    tol = max(metric_tol, _FLOAT_ATOL)
    if math.isclose(projected, expected, rel_tol=0.0, abs_tol=tol):
        return (
            _clean_float(projected, field_name="macro_projection.projected_value"),
            _clean_float(model, field_name="macro_projection.model_value"),
            _clean_float(projected - model, field_name="macro_projection.delta"),
        )
    raise StressInputError(
        "macro_projection trae identidad macro inconsistente: projected_value debe ser "
        "model_value + shock_value; "
        f"scenario={scenario!r}, macro_variable={macro_variable!r}, period={period}, "
        f"projected_value={projected}, model_value={model}, shock_value={shock}, "
        f"esperado={expected}, tol={tol}."
    )


def _validate_forward_term_values(frame: DataFrame, *, cfg: StressConfig) -> None:
    tol = cfg.validation.probability_tol
    working = frame.copy(deep=True)
    working["_validated_period"] = [
        _positive_int(value, field_name="period") for value in working["period"].tolist()
    ]
    key_columns = ["scenario", *_curve_key_columns(working)]
    for curve_key, group in working.groupby(key_columns, sort=False, dropna=False):
        previous_survival = 1.0
        previous_period = 0
        ordered = group.sort_values("_validated_period", kind="mergesort")
        for _, row in ordered.iterrows():
            _validate_forward_term_metadata(row)
            period = _positive_int(row["period"], field_name="period")
            _validate_contiguous_lifetime_period(
                period,
                previous_period=previous_period,
                curve_key=curve_key,
            )
            _required_float(row["time_value"], field_name="time_value")
            hazard = _probability(
                _required_float(row["hazard"], field_name="hazard"),
                field_name="hazard",
                tol=tol,
            )
            survival = _probability(
                _required_float(row["survival"], field_name="survival"),
                field_name="survival",
                tol=tol,
            )
            pd_marginal = _probability(
                _required_float(row["pd_marginal"], field_name="pd_marginal"),
                field_name="pd_marginal",
                tol=tol,
            )
            pd_cumulative = _probability(
                _required_float(row["pd_cumulative"], field_name="pd_cumulative"),
                field_name="pd_cumulative",
                tol=tol,
            )
            _validate_lifetime_identity(
                observed=survival,
                expected=previous_survival * (1.0 - hazard),
                identity="survival_t == survival_{t-1}*(1-hazard_t)",
                period=period,
                curve_key=curve_key,
                tol=tol,
            )
            _validate_lifetime_identity(
                observed=pd_marginal,
                expected=previous_survival * hazard,
                identity="pd_marginal_t == survival_{t-1}*hazard_t",
                period=period,
                curve_key=curve_key,
                tol=tol,
            )
            _validate_lifetime_identity(
                observed=pd_cumulative,
                expected=1.0 - survival,
                identity="pd_cumulative_t == 1-survival_t",
                period=period,
                curve_key=curve_key,
                tol=tol,
            )
            previous_survival = survival
            previous_period = period


def _validate_contiguous_lifetime_period(
    period: int,
    *,
    previous_period: int,
    curve_key: Any,
) -> None:
    expected = 1 if previous_period == 0 else previous_period + 1
    if period == expected:
        return
    key_values = curve_key if isinstance(curve_key, tuple) else (curve_key,)
    curve_label = tuple(_sort_value(value) for value in key_values)
    raise StressInputError(
        "forward_term_structure debe traer períodos lifetime contiguos por curva: "
        f"esperado={expected}, observado={period}, curva={curve_label}."
    )


def _validate_lifetime_identity(
    *,
    observed: float,
    expected: float,
    identity: str,
    period: int,
    curve_key: Any,
    tol: float,
) -> None:
    expected_probability = _probability(expected, field_name=f"{identity}.esperado", tol=tol)
    if math.isclose(observed, expected_probability, rel_tol=0.0, abs_tol=tol):
        return
    key_values = curve_key if isinstance(curve_key, tuple) else (curve_key,)
    curve_label = tuple(_sort_value(value) for value in key_values)
    raise StressInputError(
        "forward_term_structure trae lifetime incoherente antes de stress: "
        f"{identity}, period={period}, curva={curve_label}, "
        f"observado={observed}, esperado={expected_probability}."
    )


def _validate_shock_periods(
    shock: StressShockConfig,
    base_macro: DataFrame,
    *,
    base_term: DataFrame,
    pd: Any,
) -> None:
    del pd
    if shock.factor not in set(base_macro["macro_variable"].astype(str)):
        raise StressScenarioError(
            f"Factor de shock no existe en macro_projection: {shock.factor!r}."
        )
    _shock_periods(shock, base_macro, base_term=base_term, pd=None)


def _shock_periods(
    shock: StressShockConfig,
    base_macro: DataFrame,
    *,
    base_term: DataFrame | None = None,
    pd: Any,
) -> tuple[int, ...]:
    del pd
    factor_rows = base_macro[base_macro["macro_variable"].astype(str) == shock.factor]
    observed_macro = sorted(
        {_positive_int(value, field_name="period") for value in factor_rows["period"]}
    )
    if not observed_macro:
        raise StressScenarioError(f"Factor de shock sin períodos observados: {shock.factor!r}.")
    if shock.periods == "all":
        requested = (
            tuple(
                sorted({_positive_int(value, field_name="period") for value in base_term["period"]})
            )
            if base_term is not None
            else tuple(observed_macro)
        )
    else:
        requested = tuple(
            sorted({_positive_int(value, field_name="shock.periods") for value in shock.periods})
        )
    if base_term is None:
        missing = sorted(set(requested) - set(observed_macro))
        if missing:
            raise StressScenarioError(
                f"shock.periods contiene períodos fuera del horizonte forward: {missing}."
            )
    else:
        observed_forward = {
            _positive_int(value, field_name="forward_term_structure.period")
            for value in base_term["period"]
        }
        missing_forward = sorted(set(requested) - observed_forward)
        if missing_forward:
            raise StressScenarioError(
                f"shock.periods contiene períodos fuera del horizonte forward: {missing_forward}."
            )
        missing_macro = sorted(set(requested) - set(observed_macro))
        if missing_macro:
            raise StressInputError(
                "macro_projection no cubre forward_term_structure para el shock: "
                f"factor={shock.factor!r}, períodos faltantes={missing_macro}."
            )
    if not requested:
        raise StressScenarioError(
            f"shock.periods no resolvió períodos para factor={shock.factor!r}."
        )
    return requested


def _apply_shock_value(value: float, applied_shock: float, *, operation: str) -> float:
    if operation == "additive":
        return _clean_float(value + applied_shock, field_name="x_stress")
    if operation == "relative":
        _require_positive_relative_base(value, factor=None, period=None)
        return _clean_float(value * (1.0 + applied_shock), field_name="x_stress")
    raise StressScenarioError(f"Operación de shock no soportada: {operation!r}.")


def _require_positive_relative_base(
    value: float, *, factor: str | None, period: int | None
) -> None:
    if value > 0.0:
        return
    detail = []
    if factor is not None:
        detail.append(f"factor={factor!r}")
    if period is not None:
        detail.append(f"period={period}")
    suffix = f" ({', '.join(detail)})" if detail else ""
    raise StressScenarioError(
        "operation='relative' exige projected_value base positivo; valores cero o negativos "
        f"requieren política explícita{suffix}."
    )


def _require_columns(frame: DataFrame, columns: tuple[str, ...], *, field_name: str) -> None:
    observed_columns = tuple(str(column) for column in frame.columns)
    duplicated_columns = _duplicated_columns(observed_columns)
    if duplicated_columns:
        raise StressInputError(
            f"{field_name} no puede tener columnas duplicadas: {duplicated_columns}."
        )
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise StressInputError(f"{field_name} no trae columnas requeridas: {missing}.")


def _required_columns(
    columns: tuple[str, ...],
    *,
    optional_columns: tuple[str, ...],
) -> tuple[str, ...]:
    optional = set(optional_columns)
    return tuple(column for column in columns if column not in optional)


def _duplicated_columns(columns: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(column for column in dict.fromkeys(columns) if columns.count(column) > 1)


def _require_observed_scenario(frame: DataFrame, scenario: str, *, field_name: str) -> None:
    observed = {str(value) for value in frame["scenario"].tolist()}
    if scenario not in observed:
        raise StressInputError(f"{field_name} no contiene scenario={scenario!r}.")


def _reject_reserved_scenarios(frame: DataFrame, *, field_name: str) -> None:
    observed = {str(value).strip().lower() for value in frame["scenario"].tolist()}
    reserved = sorted(observed & _RESERVED_SCENARIO_NAMES)
    if reserved:
        raise StressInputError(f"{field_name} contiene escenario medio prohibido: {reserved}.")


def _reject_weighted_mean_columns(frame: DataFrame, *, field_name: str) -> None:
    observed = {str(column).strip().lower() for column in frame.columns}
    if _WEIGHTED_MEAN_INPUT_COLUMN in observed:
        raise StressInputError(
            f"{field_name} contiene columna {_WEIGHTED_MEAN_INPUT_COLUMN!r}, "
            "prohibida porque stress no pondera inputs macro."
        )


def _sort_term_structure(frame: DataFrame) -> DataFrame:
    working = frame.copy(deep=True)
    taken = {str(column) for column in working.columns}
    sort_columns: list[str] = []
    for column in ("row_id", "segment", "partition", "source_model", "method", "pd_source"):
        values = working[column] if column in working.columns else [""] * len(working.index)
        helper_column = _unique_helper_column(f"_nikodym_sort_{column}", taken=taken)
        working[helper_column] = [_sort_value(value) for value in values]
        sort_columns.append(helper_column)
    period_helper_column = _unique_helper_column("_nikodym_sort_period", taken=taken)
    working[period_helper_column] = [
        _positive_int(value, field_name="period") for value in working["period"]
    ]
    sort_columns.append(period_helper_column)
    sorted_frame = working.sort_values(
        [*sort_columns, "_ordinal"],
        kind="mergesort",
    )
    return sorted_frame.drop(columns=sort_columns)


def _unique_helper_column(base_name: str, *, taken: set[str]) -> str:
    candidate = base_name
    suffix = 1
    while candidate in taken:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate


def _curve_key_columns(frame: DataFrame) -> list[str]:
    return [
        column
        for column in ("row_id", "segment", "partition", "source_model", "method", "pd_source")
        if column in frame.columns
    ]


def _segment_value(row: Any) -> str:
    segment = row.get("segment") if hasattr(row, "get") else getattr(row, "segment", None)
    if _is_missing(segment):
        return _SEGMENT_ALL
    return str(segment)


def _validate_forward_term_metadata(row: Any) -> None:
    for column in _FORWARD_TERM_METADATA_COLUMNS:
        _forward_term_text(row, column)
    pd_basis = _forward_term_text(row, "pd_basis")
    if pd_basis not in {"pit", "ttc"}:
        raise StressInputError("forward_term_structure.pd_basis debe ser pit o ttc.")
    basis_state = _forward_term_text(row, "basis_state")
    if basis_state not in {"pit", "blended", "ttc"}:
        raise StressInputError("forward_term_structure.basis_state debe ser pit, blended o ttc.")


def _forward_term_text(row: Any, column: str) -> str:
    value = row.get(column) if hasattr(row, "get") else getattr(row, column, None)
    return _validate_non_empty_text(value, field_name=f"forward_term_structure.{column}")


def _is_ttc_term_row(row: Any) -> bool:
    return _forward_term_text(row, "basis_state") == "ttc"


def _optional_probability_from_row(
    row: Any,
    columns: tuple[str, ...],
    *,
    cfg: StressConfig,
) -> float | None:
    for column in columns:
        if column not in row.index:
            continue
        value = row[column]
        if _is_missing(value):
            continue
        return _probability(
            _required_float(value, field_name=column),
            field_name=column,
            tol=cfg.validation.probability_tol,
        )
    return None


def _mean_optional_probability(values: Sequence[Any], *, metric: str) -> float | None:
    observed = [
        _required_float(value, field_name=metric) for value in values if not _is_missing(value)
    ]
    if not observed:
        return None
    return _clean_float(math.fsum(observed) / len(observed), field_name=metric)


def _non_negative_metric_sum(values: Sequence[Any], *, field_name: str) -> float:
    observed: list[float] = []
    for row_number, value in enumerate(values, start=1):
        numeric = _required_float(value, field_name=field_name)
        if numeric < 0.0:
            raise StressOutputError(
                f"{field_name} no puede ser negativo fila-a-fila; "
                f"fila={row_number}, valor={numeric}."
            )
        observed.append(numeric)
    return _clean_float(math.fsum(observed), field_name=field_name)


def _normalize_optional_forward_key(value: Any, *, field_name: str) -> Any | None:
    numpy_scalar = _numpy_scalar_value(value)
    if numpy_scalar is not _NUMPY_NON_SCALAR:
        value = numpy_scalar
    if _is_missing(value):
        return None
    if _hashable_array(value) is not None:
        raise StressInputError(f"{field_name} debe ser escalar o faltante.")
    if isinstance(value, Mapping) or (
        isinstance(value, Sequence | set | frozenset) and not isinstance(value, str | bytes)
    ):
        raise StressInputError(f"{field_name} debe ser escalar o faltante.")
    try:
        hash(value)
    except TypeError as exc:
        raise StressInputError(f"{field_name} debe ser escalar o faltante.") from exc
    if _is_opaque_hashable_value(value):
        raise StressInputError(
            f"{field_name} debe ser escalar con identidad pública estable o faltante."
        )
    return value


def _is_opaque_hashable_value(value: Any) -> bool:
    payload = _hashable_cell(value)
    return isinstance(payload, tuple) and len(payload) == 2 and payload[0] == "__opaque__"


def _validate_no_nonfinite(frame: DataFrame, *, field_name: str) -> None:
    for row in frame.itertuples(index=False):
        for value in row:
            if _contains_nonfinite(value):
                raise StressOutputError(f"{field_name} no puede publicar NaN ni infinitos.")


def _validate_no_nonfinite_input(
    frame: DataFrame,
    *,
    field_name: str,
    allow_missing_columns: Sequence[str] = (),
) -> None:
    allow_missing = set(allow_missing_columns)
    columns = tuple(str(column) for column in frame.columns)
    for row_number, row in enumerate(frame.itertuples(index=False), start=1):
        for column, value in zip(columns, row, strict=True):
            if column in allow_missing and _is_missing(value):
                continue
            if _contains_nonfinite(value):
                raise StressInputError(
                    f"{field_name}.{column} no puede contener NaN ni infinitos; fila={row_number}."
                )


def _contains_nonfinite(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, Decimal):
        return not value.is_finite()
    if _is_missing(value):
        return True
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Real):
        return not math.isfinite(float(value))
    array_nonfinite = _numpy_array_contains_nonfinite(value)
    if array_nonfinite is not None:
        return array_nonfinite
    if isinstance(value, Mapping):
        return any(_contains_nonfinite(key) for key in value) or any(
            _contains_nonfinite(item) for item in value.values()
        )
    if isinstance(value, list | tuple | set | frozenset):
        return any(_contains_nonfinite(item) for item in value)
    return False


def _numpy_array_contains_nonfinite(value: Any) -> bool | None:
    if type(value).__module__.split(".", maxsplit=1)[0] != "numpy":
        return None
    np = cast("Any", importlib.import_module("numpy"))
    array = np.asarray(value)
    if bool(array.dtype.hasobject):
        return any(_contains_nonfinite(item) for item in array.reshape(-1).tolist())
    if bool(np.issubdtype(array.dtype, np.number)):
        return bool((~np.isfinite(array)).any())
    if bool(np.issubdtype(array.dtype, np.datetime64)) or bool(
        np.issubdtype(array.dtype, np.timedelta64)
    ):
        return bool(np.isnat(array).any())
    return False


def _as_dataframe(frame: Any, *, pd: Any, field_name: str) -> DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise StressInputError(f"{field_name} requiere pandas.DataFrame.")
    return cast("DataFrame", frame.copy(deep=True))


def _normalize_frame(frame: DataFrame) -> DataFrame:
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        zero_mask = copied[column] == 0.0
        if bool(zero_mask.any()):
            copied[column] = copied[column].mask(zero_mask, 0.0)
    return copied


def _config_digest(cfg: StressConfig) -> str:
    payload = cfg.model_dump(mode="json", by_alias=True)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_lineage_components(
    *,
    macro_projection: DataFrame,
    forward_term_structure: DataFrame,
    forward_ecl_input: ForwardEclInput,
    satellite_model: object,
    scenario_weighting: object,
    ecl_engine: EclEngineLike | None,
    provision_engine: ProvisionEngineLike | None,
    cfg: StressConfig,
    pd: Any,
) -> dict[str, Any]:
    """Resume todo insumo que puede cambiar resultados de stress para lineage."""
    forward_term_summary = _logical_frame_summary(
        forward_term_structure,
        key_columns=_FORWARD_TERM_HASH_KEY_COLUMNS,
        field_name="forward_term_structure",
        pd=pd,
    )
    macro_summary = _logical_frame_summary(
        macro_projection,
        key_columns=_MACRO_PROJECTION_HASH_KEY_COLUMNS,
        field_name="macro_projection",
        pd=pd,
    )
    return {
        "macro_projection": macro_summary,
        "forward_term_structure": forward_term_summary,
        "forward_ecl_input": _forward_ecl_input_lineage(forward_ecl_input, cfg=cfg, pd=pd),
        "satellite_model": _satellite_model_lineage(satellite_model, pd=pd),
        "scenario_weighting": _object_lineage(scenario_weighting, pd=pd),
        "ecl_engine": _object_lineage(ecl_engine, pd=pd),
        "provision_engine": _object_lineage(provision_engine, pd=pd),
    }


def _forward_ecl_input_lineage(
    forward_ecl_input: ForwardEclInput,
    *,
    cfg: StressConfig,
    pd: Any,
) -> dict[str, Any]:
    term_frame = getattr(forward_ecl_input, "term_structure_frame", None)
    scenario_weight_frame = getattr(forward_ecl_input, "scenario_weight_frame", None)
    return {
        "type": _type_id(forward_ecl_input),
        "contract_version": getattr(forward_ecl_input, "contract_version", None),
        "chain": getattr(forward_ecl_input, "chain", None),
        "term_structure_frame_hash": _maybe_forward_term_frame_hash(
            term_frame,
            cfg=cfg,
            key_columns=_FORWARD_TERM_HASH_KEY_COLUMNS,
            field_name="forward_ecl_input.term_structure_frame",
            pd=pd,
        ),
        "scenario_weight_frame_hash": _maybe_scenario_weight_frame_hash(
            scenario_weight_frame,
            key_columns=_SCENARIO_WEIGHT_HASH_KEY_COLUMNS,
            field_name="forward_ecl_input.scenario_weight_frame",
            pd=pd,
        ),
        "pit_consistency_hash": _canonical_hash(
            getattr(forward_ecl_input, "pit_consistency", {}),
            pd=pd,
        ),
    }


def _satellite_model_lineage(satellite_model: object, *, pd: Any) -> dict[str, Any]:
    coefficients = getattr(satellite_model, "coefficients_", None)
    if coefficients is None:
        coefficients = getattr(satellite_model, "coefficients", None)
    payload = _object_lineage(satellite_model, pd=pd)
    payload["coefficients_hash"] = (
        _canonical_hash(coefficients, pd=pd) if isinstance(coefficients, Mapping) else None
    )
    return payload


def _object_lineage(obj: object | None, *, pd: Any) -> dict[str, Any]:
    if obj is None:
        return {"present": False}
    if isinstance(obj, Mapping):
        return {
            "present": True,
            "type": _type_id(obj),
            "package_version": _object_package_version(obj),
            "state_hash": _canonical_hash(obj, pd=pd),
        }
    state = _public_state(obj)
    return {
        "present": True,
        "type": _type_id(obj),
        "package_version": _object_package_version(obj),
        "state_hash": _canonical_hash(state, pd=pd) if state else None,
    }


def _public_state(obj: object) -> dict[str, Any]:
    if isinstance(obj, Mapping):
        return {
            "__mapping_type__": _type_id(obj),
            "items": _hashable_mapping_items(obj),
        }
    if isinstance(obj, list | tuple):
        return {"__sequence_type__": _type_id(obj), "items": list(obj)}
    if isinstance(obj, set | frozenset):
        return {
            "__sequence_type__": _type_id(obj),
            "items": sorted(obj, key=lambda item: repr(_hashable_cell(item))),
        }
    state = _public_object_state(obj)
    return state or {}


def _public_object_state(obj: object) -> dict[str, Any] | None:
    if _is_scalar_for_public_state(obj):
        return None
    if isinstance(obj, (Mapping, list, tuple, set, frozenset)):
        return None
    state: dict[str, Any] = {}
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        if isinstance(dumped, Mapping):
            state.update(_public_state_from_items(dumped.items()))
    if is_dataclass(obj) and not isinstance(obj, type):
        state.update(
            _public_state_from_items(
                (field.name, getattr(obj, field.name)) for field in dataclass_fields(obj)
            )
        )
    state.update(_public_state_from_slots(obj))
    attrs = getattr(obj, "__dict__", None)
    if isinstance(attrs, Mapping):
        state.update(_public_state_from_items(attrs.items()))
    return state or None


def _public_state_from_slots(obj: object) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for name in _slot_names(type(obj)):
        try:
            value = getattr(obj, name)
        except AttributeError:
            continue
        state.update(_public_state_from_items(((name, value),)))
    return state


def _slot_names(cls: type[object]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for base in reversed(cls.__mro__):
        slots = getattr(base, "__slots__", ())
        slot_names = (slots,) if isinstance(slots, str) else tuple(slots)
        for name in slot_names:
            if name in {"__dict__", "__weakref__"} or not isinstance(name, str):
                continue
            if name not in seen:
                seen.add(name)
                names.append(name)
    return tuple(names)


def _public_state_from_items(items: Iterable[tuple[Any, Any]]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for key, value in items:
        if not isinstance(key, str):
            continue
        if key.startswith("_") or _is_runtime_state_attribute(key):
            continue
        state[key] = _callable_public_state(value, field_name=key) if callable(value) else value
    return state


def _callable_public_state(value: Any, *, field_name: str) -> dict[str, Any]:
    callable_id, module = _callable_identity(value, field_name=field_name)
    state: dict[str, Any] = {
        "__callable__": callable_id,
        "package_version": _module_package_version(module),
    }
    if isinstance(value, functools.partial):
        state["partial"] = {
            "func": _callable_public_state(value.func, field_name=f"{field_name}.func"),
            "args": tuple(value.args),
            "keywords": dict(value.keywords or {}),
        }
        return state
    bound_function = getattr(value, "__func__", None)
    bound_owner = getattr(value, "__self__", None)
    if callable(bound_function) and bound_owner is not None:
        state["bound_method"] = {
            "func": _callable_public_state(
                bound_function,
                field_name=f"{field_name}.__func__",
            ),
            "self": _bound_callable_owner_state(bound_owner),
        }
        return state
    public_state = _public_object_state(value)
    if public_state:
        state["state"] = public_state
    return state


def _bound_callable_owner_state(owner: object) -> dict[str, Any]:
    if isinstance(owner, type):
        return {
            "type": f"{owner.__module__}.{owner.__qualname__}",
            "package_version": _module_package_version(owner.__module__),
        }
    public_state = _public_object_state(owner)
    return {
        "type": _type_id(owner),
        "package_version": _object_package_version(owner),
        "state": public_state or {},
    }


def _callable_identity(value: Any, *, field_name: str) -> tuple[str, str | None]:
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if not isinstance(module, str) or not isinstance(qualname, str):
        cls = value.__class__
        module = cls.__module__
        qualname = cls.__qualname__
    if "<lambda>" in qualname or "<locals>" in qualname:
        raise StressDependencyError(
            f"El atributo público callable '{field_name}' no tiene identidad estable para lineage."
        )
    return f"{module}.{qualname}", module


def _is_runtime_state_attribute(name: str) -> bool:
    return (
        name in _RUNTIME_STATE_ATTRIBUTE_NAMES
        or name.endswith("_calls")
        or name.endswith("_events")
    )


def _is_scalar_for_public_state(value: object) -> bool:
    if value is None or isinstance(value, bool | str | bytes | bytearray | Decimal):
        return True
    return isinstance(value, Real)


def _type_id(obj: object) -> str:
    cls = obj.__class__
    return f"{cls.__module__}.{cls.__qualname__}"


def _object_package_version(obj: object) -> str:
    return _module_package_version(obj.__class__.__module__)


def _module_package_version(module: str | None) -> str:
    if module is None:
        return "no-disponible"
    package = module.split(".", maxsplit=1)[0]
    if package in {"__main__", "builtins"}:
        return "no-disponible"
    return _package_version(package)


def _logical_frame_summary(
    frame: DataFrame,
    *,
    key_columns: tuple[str, ...],
    field_name: str,
    pd: Any,
) -> dict[str, Any]:
    canonical = _canonical_hash_frame(
        frame,
        key_columns=key_columns,
        field_name=field_name,
    )
    return {
        "hash": _combined_frame_hash((canonical,), pd=pd, include_index=False),
        "rows": len(canonical.index),
        "columns": tuple(str(column) for column in canonical.columns),
    }


def _maybe_logical_frame_hash(
    value: Any,
    *,
    key_columns: tuple[str, ...],
    field_name: str,
    pd: Any,
) -> str | None:
    if isinstance(value, pd.DataFrame):
        canonical = _canonical_hash_frame(
            value,
            key_columns=key_columns,
            field_name=field_name,
        )
        return _combined_frame_hash((canonical,), pd=pd, include_index=False)
    if value is None:
        return None
    return _canonical_hash(value, pd=pd)


def _maybe_forward_term_frame_hash(
    value: Any,
    *,
    cfg: StressConfig,
    key_columns: tuple[str, ...],
    field_name: str,
    pd: Any,
) -> str | None:
    if isinstance(value, pd.DataFrame):
        canonical_value = _canonicalize_forward_term_structure(
            value,
            cfg=cfg,
            field_name=field_name,
            pd=pd,
        )
        canonical = _canonical_hash_frame(
            canonical_value,
            key_columns=key_columns,
            field_name=field_name,
        )
        return _combined_frame_hash((canonical,), pd=pd, include_index=False)
    if value is None:
        return None
    return _canonical_hash(value, pd=pd)


def _maybe_scenario_weight_frame_hash(
    value: Any,
    *,
    key_columns: tuple[str, ...],
    field_name: str,
    pd: Any,
) -> str | None:
    if isinstance(value, pd.DataFrame):
        canonical_value = _canonicalize_scenario_weight_frame(
            value,
            field_name=field_name,
            pd=pd,
        )
        canonical = _canonical_hash_frame(
            canonical_value,
            key_columns=key_columns,
            field_name=field_name,
        )
        return _combined_frame_hash((canonical,), pd=pd, include_index=False)
    if value is None:
        return None
    return _canonical_hash(value, pd=pd)


def _canonical_hash_frame(
    frame: DataFrame,
    *,
    key_columns: tuple[str, ...],
    field_name: str,
) -> DataFrame:
    observed_columns = tuple(str(column) for column in frame.columns)
    missing = [column for column in key_columns if column not in observed_columns]
    if missing:
        raise StressInputError(f"{field_name} no trae columnas de hash lógico: {missing}.")
    duplicated_columns = _duplicated_columns(observed_columns)
    if duplicated_columns:
        raise StressInputError(
            f"{field_name} no puede tener columnas duplicadas para hash lógico: "
            f"{duplicated_columns}."
        )

    columns = _canonical_hash_columns(observed_columns, key_columns=key_columns)
    logical = _hashable_frame(frame).loc[:, list(columns)].copy(deep=True)
    sort_helper_columns, payload_helper_column = _hash_helper_columns(
        observed_columns,
        key_count=len(key_columns),
    )
    for helper_column, column in zip(sort_helper_columns, key_columns, strict=True):
        logical[helper_column] = [
            _hash_sort_key(value, column=column) for value in logical[column].tolist()
        ]
    logical[payload_helper_column] = [
        repr(tuple(zip(columns, row, strict=True)))
        for row in logical.loc[:, list(columns)].itertuples(index=False, name=None)
    ]
    sorted_frame = logical.sort_values(
        [*sort_helper_columns, payload_helper_column],
        kind="mergesort",
    )
    return sorted_frame.drop(columns=[*sort_helper_columns, payload_helper_column]).reset_index(
        drop=True
    )


def _canonical_hash_columns(
    observed_columns: tuple[str, ...],
    *,
    key_columns: tuple[str, ...],
) -> tuple[str, ...]:
    key_set = set(key_columns)
    remainder = sorted((column for column in observed_columns if column not in key_set), key=str)
    return (*key_columns, *remainder)


def _hash_sort_key(value: Any, *, column: str) -> tuple[str, Any]:
    if column == "period":
        return ("period", _positive_int(value, field_name="period"))
    return (column, repr(_hashable_cell(value)))


def _hash_helper_columns(
    observed_columns: tuple[str, ...],
    *,
    key_count: int,
) -> tuple[tuple[str, ...], str]:
    taken = set(observed_columns)
    sort_columns = tuple(
        _unique_hash_helper_column(f"_nikodym_hash_sort_{position}", taken=taken)
        for position in range(key_count)
    )
    payload_column = _unique_hash_helper_column("_nikodym_hash_sort_payload", taken=taken)
    return sort_columns, payload_column


def _unique_hash_helper_column(base_name: str, *, taken: set[str]) -> str:
    candidate = base_name
    suffix = 1
    while candidate in taken:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate


def _canonical_hash(value: Any, *, pd: Any) -> str:
    canonical = json.dumps(
        _canonical_payload(value, pd=pd),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_payload(value: Any, *, pd: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return _tagged_payload(
            "dataframe",
            {
                "hash": _combined_frame_hash((value,), pd=pd),
                "rows": len(value.index),
                "columns": tuple(str(column) for column in value.columns),
            },
        )
    if callable(value):
        return _tagged_payload(
            "callable",
            _canonical_payload(
                _callable_public_state(value, field_name="<callable>"),
                pd=pd,
            ),
        )
    state = _public_object_state(value)
    if state is not None:
        return _tagged_payload(
            "object",
            {
                "type": _type_id(value),
                "state": _canonical_payload(state, pd=pd),
            },
        )
    if isinstance(value, Mapping):
        return _canonical_mapping_payload(value, pd=pd)
    if isinstance(value, list):
        return _tagged_payload("list", [_canonical_payload(item, pd=pd) for item in value])
    if isinstance(value, tuple):
        return _tagged_payload("tuple", [_canonical_payload(item, pd=pd) for item in value])
    if isinstance(value, set | frozenset):
        return _tagged_payload(
            "set",
            {
                "type": _type_id(value),
                "items": [
                    _canonical_payload(item, pd=pd)
                    for item in sorted(value, key=lambda item: repr(_hashable_cell(item)))
                ],
            },
        )
    if isinstance(value, bool):
        return _tagged_payload("bool", value)
    normalized = _hashable_cell(value)
    if (
        isinstance(normalized, tuple)
        and len(normalized) == 2
        and normalized[0] == "__bool__"
        and isinstance(normalized[1], bool)
    ):
        return _tagged_payload("bool", normalized[1])
    if isinstance(normalized, tuple):
        return _tagged_payload(
            "hashable",
            [_canonical_payload(item, pd=pd) for item in normalized],
        )
    if isinstance(normalized, bool | str) or normalized is None:
        return normalized
    if isinstance(normalized, int):
        return normalized
    if isinstance(normalized, Real):
        numeric = float(normalized)
        return numeric if math.isfinite(numeric) else str(normalized)
    return {"__type__": _type_id(normalized)}


def _tagged_payload(kind: str, value: Any) -> dict[str, Any]:
    return {"__nikodym_payload_type__": kind, "value": value}


def _combined_frame_hash(
    frames: tuple[DataFrame, ...],
    *,
    pd: Any,
    include_index: bool = True,
) -> str:
    digest = hashlib.sha256()
    for frame in frames:
        logical = _hashable_frame(frame)
        schema = tuple((str(column), str(dtype)) for column, dtype in logical.dtypes.items())
        digest.update(json.dumps(schema, separators=(",", ":")).encode())
        values = pd.util.hash_pandas_object(
            logical,
            index=include_index,
        ).to_numpy(dtype="<u8", copy=True)
        digest.update(values.astype("<u8", copy=False).tobytes())
    return digest.hexdigest()


def _hashable_frame(frame: DataFrame) -> DataFrame:
    logical = _normalize_frame(frame)
    if "warning_codes" in logical.columns:
        logical["warning_codes"] = logical["warning_codes"].map(_warning_tuple)
    for column in logical.select_dtypes(include=["object"]).columns:
        logical[column] = logical[column].map(_hashable_cell)
    return logical


def _hashable_cell(value: Any) -> Any:
    if isinstance(value, Mapping):
        return (
            "__mapping__",
            _type_id(value),
            _hashable_mapping_items(value),
        )
    if isinstance(value, list):
        return ("__list__", tuple(_hashable_cell(item) for item in value))
    if isinstance(value, tuple):
        return ("__tuple__", tuple(_hashable_cell(item) for item in value))
    if isinstance(value, set | frozenset):
        return (
            "__set__",
            _type_id(value),
            tuple(sorted((_hashable_cell(item) for item in value), key=repr)),
        )
    if isinstance(value, bool):
        return ("__bool__", value)
    if isinstance(value, bytes | bytearray | memoryview):
        return ("__bytes__", bytes(value).hex())
    if isinstance(value, datetime):
        return ("__datetime__", _type_id(value), value.isoformat(), value.fold)
    if isinstance(value, date):
        return ("__date__", _type_id(value), value.isoformat())
    if isinstance(value, time):
        return ("__time__", _type_id(value), value.isoformat(), value.fold)
    numpy_scalar = _numpy_scalar_value(value)
    if numpy_scalar is not _NUMPY_NON_SCALAR:
        return _hashable_cell(numpy_scalar)
    array_payload = _hashable_array(value)
    if array_payload is not None:
        return array_payload
    if isinstance(value, Decimal):
        if not value.is_finite():
            return ("__decimal__", str(value))
        if value.is_zero():
            return 0.0
        return ("__decimal__", format(value.normalize(), "f"))
    if callable(value):
        return (
            "__callable__",
            _hashable_cell(_callable_public_state(value, field_name="<callable>")),
        )
    if isinstance(value, Real):
        numeric = float(value)
        if not math.isfinite(numeric):
            return ("__float__", str(numeric))
        if math.isclose(numeric, 0.0, rel_tol=0.0, abs_tol=0.0):
            return 0.0
        if isinstance(value, Integral):
            return int(value)
        return numeric
    state = _public_object_state(value)
    if state is not None:
        return ("__object__", _type_id(value), _hashable_cell(state))
    if value is None or isinstance(value, str | bytes | bytearray):
        return value
    return ("__opaque__", _type_id(value))


def _numpy_scalar_value(value: Any) -> Any:
    if type(value).__module__.split(".", maxsplit=1)[0] != "numpy":
        return _NUMPY_NON_SCALAR
    np = cast("Any", importlib.import_module("numpy"))
    if isinstance(value, np.generic):
        return value.item()
    array = np.asarray(value)
    if tuple(array.shape) == ():
        return array.item()
    return _NUMPY_NON_SCALAR


def _hashable_array(value: Any) -> tuple[str, str, tuple[int, ...], Any] | None:
    if type(value).__module__.split(".", maxsplit=1)[0] != "numpy":
        return None
    try:
        np = cast("Any", importlib.import_module("numpy"))
    except ModuleNotFoundError:
        return None
    array = np.asarray(value)
    shape = tuple(int(item) for item in array.shape)
    if bool(array.dtype.hasobject):
        dtype = str(array.dtype)
        flattened = tuple(_hashable_cell(item) for item in array.reshape(-1).tolist())
        return ("__ndarray__", dtype, shape, flattened)
    stable_dtype = array.dtype.newbyteorder("<")
    dtype = str(stable_dtype)
    if bool(np.issubdtype(stable_dtype, np.complexfloating)):
        stable_array = np.ascontiguousarray(array.astype(stable_dtype, copy=False))
        flattened = tuple(
            (_hashable_cell(float(item.real)), _hashable_cell(float(item.imag)))
            for item in stable_array.reshape(-1).tolist()
        )
        return ("__ndarray__", dtype, shape, flattened)
    if bool(np.issubdtype(stable_dtype, np.floating)):
        stable_array = np.ascontiguousarray(array.astype(stable_dtype, copy=True))
        stable_array[stable_array == 0.0] = 0.0
        if bool(np.any(~np.isfinite(stable_array))):
            flattened = tuple(_hashable_cell(item) for item in stable_array.reshape(-1).tolist())
            return ("__ndarray__", dtype, shape, flattened)
        digest = hashlib.sha256(stable_array.tobytes(order="C")).hexdigest()
        return ("__ndarray__", dtype, shape, digest)
    stable_array = np.ascontiguousarray(array.astype(stable_dtype, copy=False))
    digest = hashlib.sha256(stable_array.tobytes(order="C")).hexdigest()
    return ("__ndarray__", dtype, shape, digest)


def _hashable_mapping_key(value: Any) -> tuple[str, str, Any]:
    return ("__mapping_key__", _type_id(value), _hashable_cell(value))


def _hashable_mapping_items(value: Mapping[Any, Any]) -> tuple[tuple[Any, Any], ...]:
    items: list[tuple[str, Any, Any]] = []
    seen_sort_keys: set[str] = set()
    for key, item in value.items():
        key_payload = _hashable_mapping_key(key)
        sort_key = repr(key_payload)
        if sort_key in seen_sort_keys:
            raise StressDependencyError(
                "Mapping de lineage contiene claves no distinguibles para hash canónico."
            )
        seen_sort_keys.add(sort_key)
        items.append((sort_key, key_payload, _hashable_cell(item)))
    return tuple(
        (key_payload, value_payload)
        for _, key_payload, value_payload in sorted(items, key=lambda item: item[0])
    )


def _jsonable_hashable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable_hashable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable_hashable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable_hashable(item) for key, item in value.items()}
    return value


def _canonical_mapping_payload(value: Mapping[Any, Any], *, pd: Any) -> dict[str, Any]:
    items: list[tuple[str, Any, Any]] = []
    seen_sort_keys: set[str] = set()
    for key, item in value.items():
        key_payload = [_type_id(key), _canonical_payload(key, pd=pd)]
        value_payload = _canonical_payload(item, pd=pd)
        sort_key = json.dumps(
            key_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if sort_key in seen_sort_keys:
            raise StressDependencyError(
                "Mapping de lineage contiene claves no distinguibles para hash canónico."
            )
        seen_sort_keys.add(sort_key)
        items.append((sort_key, key_payload, value_payload))
    return _tagged_payload(
        "mapping",
        {
            "type": _type_id(value),
            "items": [
                [key_payload, value_payload]
                for _, key_payload, value_payload in sorted(items, key=lambda item: item[0])
            ],
        },
    )


def _frame_warning_codes(frame: DataFrame) -> tuple[str, ...]:
    if "warning_codes" not in frame.columns:
        return ()
    return _warning_codes_from_values(frame["warning_codes"].tolist())


def _warning_codes_from_values(values: Sequence[Any]) -> tuple[str, ...]:
    return _dedupe(tuple(code for value in values for code in _warning_tuple(value)))


def _dependency_versions() -> dict[str, str]:
    return {
        "pandas": _package_version("pandas"),
        "nikodym.stress.engine": _STRESS_ENGINE_VERSION,
    }


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "no-disponible"


def _probability(
    value: float,
    *,
    field_name: str,
    tol: float,
    open_interval: bool = False,
) -> float:
    cleaned = _clean_float(value, field_name=field_name)
    if open_interval:
        if cleaned <= 0.0 or cleaned >= 1.0:
            raise StressInputError(f"{field_name} debe estar en (0, 1); valor={cleaned}.")
        return cleaned
    if cleaned < -tol or cleaned > 1.0 + tol:
        raise StressInputError(f"{field_name} debe estar en [0, 1]; valor={cleaned}.")
    if cleaned < 0.0:
        return 0.0
    if cleaned > 1.0:
        return 1.0
    return cleaned


def _logit(value: float) -> float:
    probability = _probability(value, field_name="probabilidad logit", tol=0.0, open_interval=True)
    return math.log(probability / (1.0 - probability))


def _shift_probability_logit(
    value: float,
    adjustment: float,
    *,
    field_name: str,
    tol: float,
) -> float:
    probability = _probability(value, field_name=field_name, tol=tol)
    if probability == 0.0:
        return 0.0
    if probability == 1.0:
        return 1.0
    if adjustment == 0.0:
        return probability
    return _probability(_sigmoid(_logit(probability) + adjustment), field_name=field_name, tol=tol)


def _sigmoid(value: float) -> float:
    if not math.isfinite(value):
        raise StressEngineError(f"Overflow logit en stress satellite: eta={value!r}.")
    if value >= 0.0:
        exp_value = math.exp(-value)
        probability = 1.0 / (1.0 + exp_value)
    else:
        exp_value = math.exp(value)
        probability = exp_value / (1.0 + exp_value)
    if not math.isfinite(probability) or probability <= 0.0 or probability >= 1.0:
        raise StressEngineError(f"Probabilidad fuera de rango por overflow logit: eta={value!r}.")
    return probability


def _non_negative_float(value: Any, *, field_name: str) -> float:
    numeric = _required_float(value, field_name=field_name)
    if numeric < 0.0:
        raise StressScenarioError(f"{field_name} debe ser no negativo.")
    return numeric


def _required_non_negative_float(value: Any, *, field_name: str) -> float:
    numeric = _required_float(value, field_name=field_name)
    if numeric < 0.0:
        raise StressInputError(f"{field_name} debe ser mayor o igual a 0.")
    return numeric


def _required_float(value: Any, *, field_name: str) -> float:
    if _is_bool_like(value) or _is_missing(value):
        raise StressInputError(f"{field_name} debe ser un número finito.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise StressInputError(f"{field_name} debe ser un número finito.") from exc
    return _clean_float(numeric, field_name=field_name)


def _required_bool(value: Any, *, field_name: str) -> bool:
    if _is_bool_like(value):
        return bool(value)
    raise StressInputError(f"{field_name} debe ser booleano.")


def _validate_warning_codes_input(value: Any, *, field_name: str) -> tuple[str, ...]:
    if _is_missing(value):
        return ()
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, Sequence):
        raise StressInputError(f"{field_name} debe ser lista o tupla de textos.")
    return tuple(_validate_non_empty_text(item, field_name=field_name) for item in value)


def _optional_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    return _required_float(value, field_name="float_opcional")


def _clean_float(value: float, *, field_name: str = "valor") -> float:
    if not math.isfinite(value):
        raise StressInputError(f"{field_name} no puede ser NaN ni infinito.")
    if value == 0.0:
        return 0.0
    return value


def _positive_int(value: Any, *, field_name: str) -> int:
    if _is_bool_like(value) or _is_missing(value):
        raise StressInputError(f"{field_name} debe ser entero positivo.")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise StressInputError(f"{field_name} debe ser entero positivo.") from exc
    if not math.isfinite(numeric):
        raise StressInputError(f"{field_name} debe ser entero positivo.")
    rounded = round(numeric)
    if not math.isclose(
        numeric,
        rounded,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise StressInputError(f"{field_name} debe ser entero positivo.")
    if rounded < 1:
        raise StressInputError(f"{field_name} debe ser mayor o igual a 1.")
    return int(rounded)


def _validate_non_empty_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise StressInputError(f"{field_name} debe ser texto no vacío.")
    text = value.strip()
    if not text:
        raise StressInputError(f"{field_name} no puede estar vacío.")
    return text


def _is_bool_like(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    value_type = type(value)
    if value_type.__module__.split(".", maxsplit=1)[0] != "numpy":
        return False
    if value_type.__name__ in {"bool", "bool_"}:
        return True
    dtype = getattr(value, "dtype", None)
    if getattr(dtype, "kind", None) != "b":
        return False
    shape = getattr(value, "shape", None)
    if shape is None:
        return False
    try:
        return tuple(shape) == ()
    except TypeError:
        return False


def _warning_tuple(value: Any) -> tuple[str, ...]:
    if _is_missing(value):
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if item not in (None, ""))
    return (str(value),)


def _dedupe(values: Sequence[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _dedupe_iterable(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _none_if_missing(value: Any) -> Any:
    if _is_missing(value):
        return None
    return value


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    value_type = type(value)
    if value_type.__name__ in {"NAType", "NaTType"} and value_type.__module__.startswith("pandas"):
        return True
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        return False


def _sort_value(value: Any) -> str:
    if _is_missing(value):
        return ""
    return json.dumps(
        _jsonable_hashable(_hashable_cell(value)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _import_pandas() -> Any:
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise StressDependencyError("StressTestEngine requiere pandas.") from exc
