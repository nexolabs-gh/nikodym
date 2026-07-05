"""Paso orquestable de la capa ``forward`` (SDD-20 §4/§7/§9; CT-1).

``ForwardStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``forward``. Sus dependencias son dinámicas: dependen de las term-structures declaradas en
``ForwardConfig.input.term_structure_sources`` y, si aplica, de la clave macro configurada como
artefacto. El paso ensambla el flujo macro → satellite → reversión TTC → contrato ECL sin importar
``pandas``, ``statsmodels``, ``pmdarima`` ni ``scipy`` en import time.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import hashlib
import importlib
import math
import warnings
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, TypeAlias, cast

from nikodym.core.audit import AuditEvent
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.forward.config import ForwardConfig
from nikodym.forward.exceptions import ForwardInputError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.study import Study
    from nikodym.forward.macro import MacroProjectionModel
    from nikodym.forward.results import (
        ForwardCard,
        ForwardDiagnostics,
        ForwardEclInput,
        ForwardResult,
        MacroDiagnostics,
        SatelliteDiagnostics,
        ScenarioDiagnostics,
    )
    from nikodym.forward.satellite import SatelliteModel
    from nikodym.forward.scenarios import ScenarioWeighting

    DataFrame: TypeAlias = pd.DataFrame
else:
    DataFrame: TypeAlias = Any
    MacroProjectionModel: TypeAlias = Any
    SatelliteModel: TypeAlias = Any
    ScenarioWeighting: TypeAlias = Any
    Study: TypeAlias = Any

__all__ = ["FORWARD_ARTIFACTS", "ForwardStep"]

FORWARD_ARTIFACTS: Final[tuple[str, ...]] = (
    "macro_model",
    "macro_projection",
    "satellite_model",
    "term_structure",
    "scenario_weights",
    "scenario_weighting",
    "ecl_input",
    "diagnostics",
    "result",
    "card",
)
_FORWARD_TERM_STRUCTURE_COLUMNS: Final[tuple[str, ...]] = (
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
_SCENARIO_WEIGHT_COLUMNS: Final[tuple[str, ...]] = (
    "scenario",
    "weight",
    "is_default",
    "source",
    "description",
)
_WEIGHT_VALUE_COLUMNS: Final[tuple[str, ...]] = (
    "pd_marginal",
    "pd_cumulative",
    "hazard",
    "survival",
)
_WEIGHT_GROUP_COLUMNS: Final[tuple[str, ...]] = (
    "row_id",
    "segment",
    "partition",
    "source_model",
    "period",
    "time_value",
    "method",
    "pd_source",
)
_MACRO_HISTORY_ARTIFACT: Final[ArtifactKey] = ("forward", "macro_history")
_PANDAS_EXTRA_MESSAGE: Final = "ForwardStep requiere pandas; instale las dependencias base."


@register("standard", domain="forward")
class ForwardStep(AuditableMixin):
    """Orquesta forward-looking y publica ``domain='forward'``."""

    name: str = "forward"
    config_cls: ClassVar[type[ForwardConfig]] = ForwardConfig
    # Pares objeto+frame: el objeto contiene lógica reusable y estado fiteado; el frame es el dato
    # materializado y auditable. Por eso coexisten macro_model/macro_projection,
    # satellite_model/term_structure y scenario_weighting/scenario_weights sin doble fuente de
    # verdad: los consumidores tabulares leen frames; los consumidores avanzados reutilizan objetos.
    provides: tuple[ArtifactKey, ...] = tuple(("forward", key) for key in FORWARD_ARTIFACTS)

    def __init__(self, config: ForwardConfig) -> None:
        """Construye el paso desde la sección ``ForwardConfig`` ya validada."""
        self.config = config
        self.requires = _requires_from_config(config)

    @classmethod
    def from_config(cls, cfg: ForwardConfig) -> ForwardStep:
        """Construye ``ForwardStep`` desde ``NikodymConfig.forward``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` sin exponer el sink interno."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> ForwardResult:
        """Ejecuta el flujo forward determinista y publica las diez claves del dominio."""
        cfg = _forward_config_from_study(study, fallback=self.config)
        self.requires = _requires_from_config(cfg)
        _validate_requires(study, self.requires)
        random_state = _resolve_random_state(cfg, rng)

        pd = _import_pandas()
        macro_history, macro_source_context = _macro_history_from_source(study, cfg=cfg, pd=pd)
        base_term_structure, term_context = _term_structures_from_study(study, cfg=cfg, pd=pd)

        scenario_weighting = _new_scenario_weighting(cfg)
        scenario_weight_frame = scenario_weighting.scenario_weight_frame()
        macro_model = _new_macro_model(cfg)
        macro_model.fit(macro_history.copy(deep=True))
        scenario_frame = _macro_scenario_frame(cfg, pd=pd)
        macro_projection = macro_model.predict(
            horizon=cfg.macro.horizon_periods,
            scenario_frame=scenario_frame,
        )
        scenario_weighting.validate_macro_projection(macro_projection.copy(deep=True))

        satellite_model = _new_satellite_model(cfg)
        satellite_model.fit(base_term_structure.copy(deep=True), macro_history.copy(deep=True))
        satellite_term_structure = satellite_model.predict(
            base_term_structure.copy(deep=True),
            macro_projection.copy(deep=True),
            scenarios=scenario_weighting,
        )
        reverted, ttc_warning_codes = _apply_ttc_reversion(
            scenario_weighting,
            satellite_term_structure,
            ttc_anchor=base_term_structure,
        )
        forward_term_structure = _finalize_forward_term_structure(
            reverted,
            extra_warning_codes=ttc_warning_codes,
        )
        _validate_no_mean_and_weight_outputs(scenario_weighting, forward_term_structure)

        macro_diagnostics = macro_model.residual_diagnostics()
        satellite_diagnostics = satellite_model.diagnostics_
        scenario_diagnostics = _scenario_diagnostics(scenario_weight_frame)
        diagnostics = _forward_diagnostics(
            cfg=cfg,
            macro=macro_diagnostics,
            satellite=satellite_diagnostics,
            scenario=scenario_diagnostics,
            base_term_structure=base_term_structure,
            forward_term_structure=forward_term_structure,
            ttc_warning_codes=ttc_warning_codes,
        )
        ecl_input = _ecl_input(
            forward_term_structure=forward_term_structure,
            scenario_weight_frame=scenario_weight_frame,
            diagnostics=diagnostics,
        )
        card = _card(
            cfg=cfg,
            diagnostics=diagnostics,
            macro_source_context=macro_source_context,
            term_context=term_context,
            scenario_weight_frame=scenario_weight_frame,
            macro_projection=macro_projection,
            forward_term_structure=forward_term_structure,
        )
        from nikodym.forward.results import ForwardResult

        result = ForwardResult(
            macro_projection_frame=macro_projection.copy(deep=True),
            forward_term_structure_frame=forward_term_structure.copy(deep=True),
            scenario_weight_frame=scenario_weight_frame.copy(deep=True),
            diagnostics=diagnostics,
            card=card,
            ecl_input=ecl_input,
        )
        self._log_forward_decisions(
            cfg=cfg,
            random_state=random_state,
            macro_source_context=macro_source_context,
            term_context=term_context,
            result=result,
        )
        self._publish_artifacts(
            study,
            result=result,
            macro_model=macro_model,
            satellite_model=satellite_model,
            scenario_weighting=scenario_weighting,
        )
        return result

    def _publish_artifacts(
        self,
        study: Study,
        *,
        result: ForwardResult,
        macro_model: MacroProjectionModel,
        satellite_model: SatelliteModel,
        scenario_weighting: ScenarioWeighting,
    ) -> None:
        """Publica objetos reutilizables y frames materializados sin mezclar responsabilidades."""
        term_structure = result.forward_term_structure_frame
        assert term_structure is not None
        study.artifacts.set("forward", "macro_model", macro_model)
        study.artifacts.set("forward", "macro_projection", result.macro_projection_frame)
        study.artifacts.set("forward", "satellite_model", satellite_model)
        study.artifacts.set("forward", "term_structure", term_structure)
        study.artifacts.set("forward", "scenario_weights", result.scenario_weight_frame)
        study.artifacts.set("forward", "scenario_weighting", scenario_weighting)
        study.artifacts.set("forward", "ecl_input", result.ecl_input.model_copy(deep=True))
        study.artifacts.set("forward", "diagnostics", result.diagnostics.model_copy(deep=True))
        study.artifacts.set("forward", "result", result.model_copy(deep=True))
        study.artifacts.set("forward", "card", result.card.model_copy(deep=True))

    def _log_forward_decisions(
        self,
        *,
        cfg: ForwardConfig,
        random_state: int | None,
        macro_source_context: dict[str, Any],
        term_context: dict[str, Any],
        result: ForwardResult,
    ) -> None:
        """Registra las once decisiones auditables exigidas por SDD-20 §9."""
        diagnostics = result.diagnostics
        macro = diagnostics.macro
        satellite = diagnostics.satellite
        scenario = diagnostics.scenario
        card_sections = result.card.metric_sections
        self.log_decision(
            regla="forward_macro_model",
            umbral={
                "method": macro.method,
                "variables": macro.macro_variables,
                "frequency": macro.frequency,
                "orders_lags": macro.orders_lags,
                "horizon": macro.horizon,
                "auto_arima_random": cfg.macro.auto_arima_random,
                "random_state": random_state,
            },
            valor={"dependency_versions": macro.dependency_versions, "warnings": macro.warnings},
            accion="fit_macro_forward",
        )
        self.log_decision(
            regla="forward_macro_input_quality",
            umbral={"source": macro_source_context},
            valor={
                "input_rows": macro.input_rows,
                "input_gaps": macro.input_gaps,
                "input_missing": macro.input_missing,
                "input_time_range": macro.input_time_range,
                "macro_data_hash": macro.macro_data_hash,
            },
            accion="validar_historico_macro",
        )
        self.log_decision(
            regla="forward_ljung_box",
            umbral={"lags": macro.ljung_box_lags},
            valor={
                "statistics": macro.ljung_box_statistics,
                "p_values": macro.ljung_box_p_values,
                "action": macro.ljung_box_action,
                "warnings": macro.warnings,
            },
            accion="diagnosticar_residuos_macro",
        )
        self.log_decision(
            regla="forward_scenarios",
            umbral={"require_at_least_three": cfg.scenarios.require_at_least_three},
            valor={
                "names": scenario.scenarios,
                "weights": scenario.scenario_weights,
                "sources": scenario.scenario_sources,
                "defaults_a_confirmar": scenario.default_scenarios_to_confirm,
                "weight_sum": scenario.weight_sum,
            },
            accion="resolver_escenarios_forward",
        )
        self.log_decision(
            regla="forward_no_mean_scenario_guard",
            umbral={"forbid_mean_scenario": cfg.scenarios.forbid_mean_scenario},
            valor={
                "executed": scenario.no_mean_scenario_guard_executed,
                "result": scenario.no_mean_scenario_guard_result,
            },
            accion="bloquear_escenario_medio",
        )
        self.log_decision(
            regla="forward_satellite_model",
            umbral={
                "mode": satellite.mode,
                "factors": satellite.factor_columns,
                "target_components": satellite.target_components,
            },
            valor={
                "coefficients": satellite.coefficients,
                "segments": satellite.segments,
                "fit_statistics": satellite.fit_statistics,
                "warnings": satellite.warnings,
            },
            accion="fit_satellite_forward",
        )
        self.log_decision(
            regla="forward_term_structure_sources",
            umbral={"sources": cfg.input.term_structure_sources},
            valor=term_context,
            accion="leer_term_structures_base",
        )
        self.log_decision(
            regla="forward_pit_consistency",
            umbral={"require_pit_consistency": cfg.input.require_pit_consistency},
            valor={
                "pd_basis": diagnostics.pd_basis,
                "basis_states": diagnostics.basis_states,
                "pit_warnings": diagnostics.pit_warnings,
                "pit_decisions": diagnostics.pit_decisions,
            },
            accion="validar_consistencia_pit_ttc",
        )
        self.log_decision(
            regla="forward_ttc_reversion",
            umbral={
                "H_RS": cfg.ttc_reversion.reasonable_supportable_periods,
                "R": cfg.ttc_reversion.reversion_periods,
                "method": cfg.ttc_reversion.method,
                "anchor": cfg.ttc_reversion.ttc_anchor,
            },
            valor={
                "blended_periods": diagnostics.blended_periods,
                "basis_states": diagnostics.basis_states,
            },
            accion="aplicar_reversion_ttc",
        )
        self.log_decision(
            regla="forward_ecl_contract",
            umbral={"contract_version": result.ecl_input.contract_version},
            valor={
                "columns": result.card.output_columns,
                "chain": result.ecl_input.chain,
                "calcula_ecl": False,
            },
            accion="publicar_contrato_ecl_sin_dependencia_ifrs9",
        )
        self.log_decision(
            regla="forward_falta_dato",
            umbral={"fail_on_falta_dato": cfg.fail_on_falta_dato},
            valor={
                "falta_dato": diagnostics.falta_dato,
                "warnings": diagnostics.warnings,
                "term_structure_summary": card_sections["term_structure_summary"],
            },
            accion="registrar_brechas_falta_dato_forward",
        )


def _requires_from_config(cfg: ForwardConfig) -> tuple[ArtifactKey, ...]:
    """Deriva las dependencias CT-1 dinámicas desde ``ForwardConfig``."""
    requires: list[ArtifactKey] = []
    for source in cfg.input.term_structure_sources:
        requires.append((source, "term_structure"))
    macro_key = _macro_artifact_key(cfg)
    if macro_key is not None:
        requires.append(macro_key)
    return tuple(dict.fromkeys(requires))


def _macro_artifact_key(cfg: ForwardConfig) -> ArtifactKey | None:
    """Devuelve la clave macro requerida cuando ``macro_source.type='artifact'``."""
    source = cfg.input.macro_source
    if source.type != "artifact":
        return None
    assert source.artifact_domain is not None
    assert source.artifact_key is not None
    return (source.artifact_domain, source.artifact_key)


def _forward_config_from_study(study: Study, *, fallback: ForwardConfig) -> ForwardConfig:
    """Lee ``NikodymConfig.forward`` y usa el config del paso como respaldo."""
    raw_config = getattr(study.config, "forward", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, ForwardConfig):
        return raw_config
    return ForwardConfig.model_validate(raw_config)


def _validate_requires(study: Study, requires: tuple[ArtifactKey, ...]) -> None:
    """Replica la validación CT-1 para ejecuciones directas del step."""
    for domain, key in requires:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso 'forward' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


def _resolve_random_state(cfg: ForwardConfig, rng: Any) -> int | None:
    """Controla el azar: por default no consume ``rng``; auto_arima exige semilla auditada."""
    if cfg.macro.auto_arima_random:
        return cfg.macro.random_state
    del rng
    return None


def _macro_history_from_source(
    study: Study,
    *,
    cfg: ForwardConfig,
    pd: Any,
) -> tuple[DataFrame, dict[str, Any]]:
    """Carga el histórico macro desde path, artefacto o frame programático."""
    source = cfg.input.macro_source
    if source.type == "path":
        assert source.path is not None
        frame = _read_table_path(source.path, pd=pd, field_name="macro_history")
        return frame.copy(deep=True), {"type": "path", "path": source.path}
    if source.type == "artifact":
        key = _macro_artifact_key(cfg)
        assert key is not None
        frame = _as_dataframe(study.artifacts.get(*key), pd, f"{key[0]}.{key[1]}")
        return frame.copy(deep=True), {"type": "artifact", "artifact_key": key}
    if study.artifacts.has(*_MACRO_HISTORY_ARTIFACT):
        frame = _as_dataframe(
            study.artifacts.get(*_MACRO_HISTORY_ARTIFACT),
            pd,
            "forward.macro_history",
        )
        return frame.copy(deep=True), {"type": "dataframe", "artifact_key": _MACRO_HISTORY_ARTIFACT}
    raise ForwardInputError(
        "macro_source.type='dataframe' exige publicar el artefacto "
        "('forward', 'macro_history') antes de ejecutar ForwardStep."
    )


def _term_structures_from_study(
    study: Study,
    *,
    cfg: ForwardConfig,
    pd: Any,
) -> tuple[DataFrame, dict[str, Any]]:
    """Lee term-structures base y documenta el cruce ``warnings``/``warning_codes``.

    NOTA DE CONTRATO: SDD-18 nombró ``warnings`` en el DTO Pydantic, pero la tabla tidy que
    ``forward`` consume usa la columna canónica ``warning_codes``. No se corrige esa inconsistencia
    aquí: se lee ``warning_codes`` desde survival/markov y el test cruzado de B20.6 blinda esa
    frontera.
    """
    frames: list[DataFrame] = []
    source_context: dict[str, Any] = {}
    for source in cfg.input.term_structure_sources:
        raw = study.artifacts.get(source, "term_structure")
        frame = _as_dataframe(raw, pd, f"{source}.term_structure").copy(deep=True)
        frame["source_model"] = source
        frames.append(frame)
        source_context[source] = {
            "rows": len(frame.index),
            "columns": tuple(str(column) for column in frame.columns),
            "pd_basis": _observed_texts(frame, "pd_basis"),
            "warning_codes": _warning_codes_from_frame(frame),
            "logical_hash": _logical_frame_hash(frame, pd=pd),
        }
    combined = pd.concat(frames, ignore_index=True, sort=False)
    return cast("DataFrame", combined), source_context


def _macro_scenario_frame(cfg: ForwardConfig, *, pd: Any) -> DataFrame | None:
    """Carga paths macro por escenario cuando la configuración los declara."""
    frames: list[DataFrame] = []
    for scenario in cfg.scenarios.scenarios:
        if scenario.macro_path_path is None:
            continue
        frame = _read_table_path(
            scenario.macro_path_path,
            pd=pd,
            field_name=f"macro_scenario_paths[{scenario.name}]",
        )
        if "scenario" not in frame.columns:
            frame["scenario"] = scenario.name
        frames.append(frame.copy(deep=True))
    if not frames:
        return None
    return cast("DataFrame", pd.concat(frames, ignore_index=True, sort=False))


def _new_macro_model(cfg: ForwardConfig) -> MacroProjectionModel:
    """Instancia el modelo macro con import perezoso."""
    from nikodym.forward.macro import MacroProjectionModel

    return MacroProjectionModel.from_config(cfg)


def _new_satellite_model(cfg: ForwardConfig) -> SatelliteModel:
    """Instancia el modelo satellite con import perezoso."""
    from nikodym.forward.satellite import SatelliteModel

    return SatelliteModel.from_config(cfg)


def _new_scenario_weighting(cfg: ForwardConfig) -> ScenarioWeighting:
    """Instancia el ponderador de escenarios con import perezoso."""
    from nikodym.forward.scenarios import ScenarioWeighting

    return ScenarioWeighting.from_config(cfg)


def _apply_ttc_reversion(
    scenario_weighting: ScenarioWeighting,
    forward_term_structure: DataFrame,
    *,
    ttc_anchor: DataFrame,
) -> tuple[DataFrame, tuple[str, ...]]:
    """Aplica reversión TTC capturando warnings ruidosos como diagnostics explícitos."""
    forward_for_reversion = forward_term_structure.copy(deep=True)
    lgd_absent = "lgd" in forward_for_reversion.columns and _all_missing(
        forward_for_reversion["lgd"].tolist()
    )
    if lgd_absent:
        forward_for_reversion = forward_for_reversion.drop(columns=["lgd"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reverted = scenario_weighting.apply_ttc_reversion(
            forward_for_reversion,
            ttc_anchor=ttc_anchor.copy(deep=True),
        )
    if lgd_absent:
        reverted["lgd"] = None
    return reverted, _warning_codes_from_warnings(caught)


def _finalize_forward_term_structure(
    frame: DataFrame,
    *,
    extra_warning_codes: tuple[str, ...],
) -> DataFrame:
    """Normaliza columnas, ``pd_basis`` y warnings antes de construir los DTOs finales."""
    working = frame.copy(deep=True)
    # pd_basis="pit" es la etiqueta SEMÁNTICA del output forward y es intencional: forward publica
    # una proyección PIT (que en la cola revierte hacia el ancla TTC), y así la consume el gate
    # pit_mode="consume_pit" de IFRS9 (provisioning/ifrs9/engine.py exige pd_basis='pit'). El
    # diagnóstico por fila (pit/ttc/blended) vive en la columna basis_state, que queda intacta. El
    # pd_basis per-fila que calcula scenarios.apply_ttc_reversion se sobrescribe aquí a propósito:
    # su valor por fila no forma parte del contrato de salida (cambiarlo por basis_state falsearía
    # la etiqueta y rompería el contrato con IFRS9).
    working["pd_basis"] = "pit"
    if extra_warning_codes:
        working["warning_codes"] = [
            _dedupe((*_as_warning_tuple(raw), *extra_warning_codes))
            for raw in working["warning_codes"].tolist()
        ]
    for column in working.select_dtypes(include=["float"]).columns:
        zero_mask = working[column] == 0.0
        if bool(zero_mask.any()):
            working[column] = working[column].mask(zero_mask, 0.0)
    return working.loc[:, list(_FORWARD_TERM_STRUCTURE_COLUMNS)].copy(deep=True)


def _validate_no_mean_and_weight_outputs(
    scenario_weighting: ScenarioWeighting,
    forward_term_structure: DataFrame,
) -> None:
    """Ejecuta el guard anti-media ponderando outputs ya calculados y descartando el agregado."""
    scenario_weighting.weight_outputs(
        forward_term_structure.copy(deep=True),
        value_cols=_WEIGHT_VALUE_COLUMNS,
        group_cols=_WEIGHT_GROUP_COLUMNS,
    )


def _scenario_diagnostics(scenario_weight_frame: DataFrame) -> ScenarioDiagnostics:
    """Construye diagnósticos de escenarios desde el frame tidy de pesos."""
    from nikodym.forward.results import ScenarioDiagnostics

    records = cast("list[dict[str, Any]]", scenario_weight_frame.to_dict("records"))
    weights = {
        str(row["scenario"]): _clean_float(float(cast("Any", row["weight"]))) for row in records
    }
    sources = {str(row["scenario"]): str(row["source"]) for row in records}
    default_scenarios = tuple(
        str(row["scenario"]) for row in records if str(row["source"]) == "default_a_confirmar"
    )
    return ScenarioDiagnostics(
        scenarios=tuple(weights),
        scenario_weights=weights,
        scenario_sources=sources,
        default_scenarios_to_confirm=default_scenarios,
        weight_sum=_clean_float(math.fsum(weights.values())),
        no_mean_scenario_guard_executed=True,
        no_mean_scenario_guard_result="passed",
    )


def _forward_diagnostics(
    *,
    cfg: ForwardConfig,
    macro: MacroDiagnostics,
    satellite: SatelliteDiagnostics,
    scenario: ScenarioDiagnostics,
    base_term_structure: DataFrame,
    forward_term_structure: DataFrame,
    ttc_warning_codes: tuple[str, ...],
) -> ForwardDiagnostics:
    """Construye el agregador ``ForwardDiagnostics`` con PIT/TTC y FALTA-DATO."""
    from nikodym.forward.results import ForwardDiagnostics

    basis_states = _ordered_basis_states(forward_term_structure)
    pit_warnings = _dedupe((*_pit_warnings(base_term_structure, cfg=cfg), *ttc_warning_codes))
    warnings_seen = _dedupe(
        (
            *macro.warnings,
            *satellite.warnings,
            *scenario.warnings,
            *pit_warnings,
            *_warning_codes_from_frame(forward_term_structure),
        )
    )
    return ForwardDiagnostics(
        macro=macro,
        satellite=satellite,
        scenario=scenario,
        pd_basis=_pd_basis_from_input(base_term_structure, cfg=cfg),
        basis_states=basis_states,
        pit_warnings=pit_warnings,
        pit_decisions=_pit_decisions(base_term_structure, cfg=cfg),
        ttc_reversion_method=cfg.ttc_reversion.method,
        ttc_anchor=cfg.ttc_reversion.ttc_anchor,
        reasonable_supportable_periods=cfg.ttc_reversion.reasonable_supportable_periods,
        reversion_periods=cfg.ttc_reversion.reversion_periods,
        blended_periods=_blended_periods(forward_term_structure),
        no_mean_scenario_guard_executed=True,
        no_mean_scenario_guard_result="passed",
        falta_dato=tuple(code for code in warnings_seen if code.startswith("FALTA-DATO")),
        warnings=warnings_seen,
    )


def _ecl_input(
    *,
    forward_term_structure: DataFrame,
    scenario_weight_frame: DataFrame,
    diagnostics: ForwardDiagnostics,
) -> ForwardEclInput:
    """Construye el gancho ECL sin importar ``nikodym.provisioning.ifrs9``."""
    from nikodym.forward.results import FORWARD_ECL_CONTRACT_VERSION, ForwardEclInput

    return ForwardEclInput(
        term_structure_frame=forward_term_structure.copy(deep=True),
        scenario_weight_frame=scenario_weight_frame.copy(deep=True),
        pit_consistency={
            "pd_basis": diagnostics.pd_basis,
            "basis_states": diagnostics.basis_states,
            "pit_warnings": diagnostics.pit_warnings,
            "pit_decisions": diagnostics.pit_decisions,
        },
        contract_version=FORWARD_ECL_CONTRACT_VERSION,
    )


def _card(
    *,
    cfg: ForwardConfig,
    diagnostics: ForwardDiagnostics,
    macro_source_context: dict[str, Any],
    term_context: dict[str, Any],
    scenario_weight_frame: DataFrame,
    macro_projection: DataFrame,
    forward_term_structure: DataFrame,
) -> ForwardCard:
    """Construye una ``ForwardCard`` CT-2 con secciones estructuradas."""
    from nikodym.forward.results import ForwardCard

    metric_sections = {
        "macro_projection_summary": _macro_projection_summary(
            macro_projection,
            macro_source_context=macro_source_context,
        ),
        "ljung_box": {
            "lags": diagnostics.macro.ljung_box_lags,
            "statistics": diagnostics.macro.ljung_box_statistics,
            "p_values": diagnostics.macro.ljung_box_p_values,
            "action": diagnostics.macro.ljung_box_action,
        },
        "scenario_weights": _scenario_weights_summary(scenario_weight_frame),
        "satellite_coefficients": {
            "mode": diagnostics.satellite.mode,
            "factor_columns": diagnostics.satellite.factor_columns,
            "segments": diagnostics.satellite.segments,
            "coefficients": diagnostics.satellite.coefficients,
            "fit_statistics": diagnostics.satellite.fit_statistics,
        },
        "pit_ttc_consistency": {
            "pd_basis": diagnostics.pd_basis,
            "basis_states": diagnostics.basis_states,
            "pit_warnings": diagnostics.pit_warnings,
            "pit_decisions": diagnostics.pit_decisions,
            "ttc_anchor": cfg.ttc_reversion.ttc_anchor,
        },
        "term_structure_summary": _term_structure_summary(
            forward_term_structure,
            term_context=term_context,
        ),
    }
    return ForwardCard(
        output_columns=_FORWARD_TERM_STRUCTURE_COLUMNS,
        diagnostics=diagnostics,
        dependency_versions=_dependency_versions(cfg),
        falta_dato=diagnostics.falta_dato,
        metric_sections=metric_sections,
    )


def _macro_projection_summary(
    frame: DataFrame,
    *,
    macro_source_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Resume la proyección macro publicada sin serializar el frame completo."""
    return {
        "n_rows": len(frame.index),
        "scenarios": _observed_texts(frame, "scenario"),
        "macro_variables": _observed_texts(frame, "macro_variable"),
        "n_periods": int(frame["period"].nunique(dropna=True)),
        "macro_source": dict(macro_source_context),
    }


def _scenario_weights_summary(frame: DataFrame) -> dict[str, Any]:
    """Resume pesos de escenarios en formato compacto."""
    records = cast(
        "list[dict[str, Any]]",
        frame.loc[:, list(_SCENARIO_WEIGHT_COLUMNS)].to_dict("records"),
    )
    return {
        "n_scenarios": len(frame.index),
        "weights": {str(row["scenario"]): _clean_float(float(row["weight"])) for row in records},
        "sources": {str(row["scenario"]): str(row["source"]) for row in records},
        "default_scenarios_to_confirm": tuple(
            str(row["scenario"]) for row in records if str(row["source"]) == "default_a_confirmar"
        ),
    }


def _term_structure_summary(frame: DataFrame, *, term_context: Mapping[str, Any]) -> dict[str, Any]:
    """Resume la term-structure forward-looking final y sus fuentes base."""
    return {
        "n_rows": len(frame.index),
        "sources": _observed_texts(frame, "source_model"),
        "scenarios": _observed_texts(frame, "scenario"),
        "n_periods": int(frame["period"].nunique(dropna=True)),
        "basis_states": _ordered_basis_states(frame),
        "max_pd_cumulative": _clean_float(float(frame["pd_cumulative"].max())),
        "max_pd_marginal": _clean_float(float(frame["pd_marginal"].max())),
        "base_sources": dict(term_context),
        "logical_hash": _logical_frame_hash(frame, pd=_import_pandas()),
    }


def _dependency_versions(cfg: ForwardConfig) -> dict[str, str]:
    """Resuelve versiones sin importar módulos pesados."""
    packages = ["pandas", "numpy", "statsmodels"]
    if cfg.macro.kind == "auto_arima" or cfg.macro.use_pmdarima_auto_order:
        packages.append("pmdarima")
    return {package: _package_version(package) for package in packages}


def _pd_basis_from_input(
    base_term_structure: DataFrame,
    *,
    cfg: ForwardConfig,
) -> Literal["pit", "ttc"] | None:
    """Determina la base PIT/TTC de entrada para diagnostics."""
    observed = _observed_texts(base_term_structure, "pd_basis")
    if len(observed) == 1 and observed[0] in {"pit", "ttc"}:
        return cast("Literal['pit', 'ttc']", observed[0])
    return cfg.input.pd_basis_assumption


def _pit_warnings(base_term_structure: DataFrame, *, cfg: ForwardConfig) -> tuple[str, ...]:
    """Extrae warnings de consistencia PIT/TTC visibles para ECL."""
    warnings_seen: list[str] = []
    observed = set(_observed_texts(base_term_structure, "pd_basis"))
    if "pd_basis" not in base_term_structure.columns:
        warnings_seen.append("pd_basis_asumida_desde_config")
    elif not observed <= {"pit", "ttc"}:
        warnings_seen.append("pd_basis_no_resuelta")
    if cfg.ttc_reversion.ttc_anchor == "input_term_structure" and observed and observed != {"ttc"}:
        warnings_seen.append("FALTA-DATO-FWD-4")
    return _dedupe(warnings_seen)


def _pit_decisions(base_term_structure: DataFrame, *, cfg: ForwardConfig) -> tuple[str, ...]:
    """Describe cómo quedó resuelta la base PIT/TTC."""
    if "pd_basis" in base_term_structure.columns and _observed_texts(
        base_term_structure,
        "pd_basis",
    ):
        return ("pd_basis explícito en term_structure",)
    if cfg.input.pd_basis_assumption is not None:
        return (f"pd_basis asumido desde config: {cfg.input.pd_basis_assumption}",)
    return ("pd_basis no resuelto permitido por config",)


def _ordered_basis_states(frame: DataFrame) -> tuple[Literal["pit", "blended", "ttc"], ...]:
    """Devuelve estados PIT/TTC en orden regulatorio estable."""
    observed = set(_observed_texts(frame, "basis_state"))
    return cast(
        "tuple[Literal['pit', 'blended', 'ttc'], ...]",
        tuple(state for state in ("pit", "blended", "ttc") if state in observed),
    )


def _blended_periods(frame: DataFrame) -> tuple[int, ...]:
    """Lista períodos que quedaron en reversión blended."""
    if "basis_state" not in frame.columns:
        return ()
    selected = frame.loc[frame["basis_state"].astype(str) == "blended", "period"]
    return tuple(sorted({int(value) for value in selected.tolist()}))


def _read_table_path(path: str, *, pd: Any, field_name: str) -> DataFrame:
    """Lee CSV/Parquet con errores propios de input forward."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".parquet":
            return cast("DataFrame", pd.read_parquet(file_path))
        if suffix == ".csv":
            return cast("DataFrame", pd.read_csv(file_path))
    except Exception as exc:
        raise ForwardInputError(f"No se pudo leer {field_name} desde '{path}': {exc}.") from exc
    raise ForwardInputError(
        f"{field_name} debe venir en archivo .csv o .parquet; recibido '{path}'."
    )


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast("DataFrame", value)
    raise ForwardInputError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _observed_texts(frame: DataFrame, column: str) -> tuple[str, ...]:
    """Extrae textos no vacíos preservando orden de aparición."""
    if column not in frame.columns:
        return ()
    values: list[str] = []
    for raw in frame[column].tolist():
        if _is_missing(raw):
            continue
        text = str(raw).strip()
        if text:
            values.append(text)
    return tuple(dict.fromkeys(values))


def _warning_codes_from_frame(frame: DataFrame) -> tuple[str, ...]:
    """Extrae ``warning_codes`` únicos desde una tabla tidy."""
    if "warning_codes" not in frame.columns:
        return ()
    codes: list[str] = []
    for raw in frame["warning_codes"].tolist():
        codes.extend(_as_warning_tuple(raw))
    return _dedupe(codes)


def _warning_codes_from_warnings(caught: Sequence[warnings.WarningMessage]) -> tuple[str, ...]:
    """Convierte warnings capturados en códigos deterministas y auditables."""
    codes: list[str] = []
    for item in caught:
        message = str(item.message)
        if "FALTA-DATO-FWD-4" in message:
            codes.append("FALTA-DATO-FWD-4")
        else:
            codes.append(f"{item.category.__name__}:{message}")
    return _dedupe(codes)


def _as_warning_tuple(value: Any) -> tuple[str, ...]:
    """Normaliza una celda ``warning_codes`` a tupla de texto."""
    if value is None or _is_missing(value):
        return ()
    if isinstance(value, str):
        return () if value == "" else (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if item not in (None, ""))
    return (str(value),)


def _logical_frame_hash(frame: DataFrame, *, pd: Any) -> str:
    """Hash lógico por contenido con endianness explícito ``<u8``."""
    digest = hashlib.sha256()
    digest.update(b"nikodym.forward.step.logical_frame.v1")
    logical = frame.copy(deep=True)
    for column in logical.select_dtypes(include=["float"]).columns:
        zero_mask = logical[column] == 0.0
        if bool(zero_mask.any()):
            logical[column] = logical[column].mask(zero_mask, 0.0)
    hashed = pd.util.hash_pandas_object(logical, index=True).to_numpy(dtype="uint64")
    digest.update(hashed.astype("<u8", copy=False).tobytes())
    return str(digest.hexdigest())


def _clean_float(value: float) -> float:
    """Normaliza floats publicados y rechaza no finitos."""
    if not math.isfinite(value):
        raise ForwardInputError(f"Valor numérico no finito en ForwardStep: {value!r}.")
    if value == 0.0:
        return 0.0
    return value


def _is_missing(value: Any) -> bool:
    """Detecta nulos escalares sin depender de pandas en import time."""
    return value is None or (isinstance(value, float) and math.isnan(value))


def _all_missing(values: Sequence[Any]) -> bool:
    """Indica si todos los valores de una columna opcional están ausentes."""
    return all(_is_missing(value) for value in values)


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    """Deduplica preservando orden."""
    return tuple(dict.fromkeys(values))


def _package_version(package: str) -> str:
    """Devuelve versión instalada o ``no-disponible`` sin importar el paquete."""
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "no-disponible"


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_PANDAS_EXTRA_MESSAGE) from exc
