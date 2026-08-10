"""Censo interno bidireccional de literales y superficie seleccionable (SDD-30 D-RDY-ABA-6)."""

from __future__ import annotations

import types
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel


class UnclassifiedOptionSurfaceError(RuntimeError):
    """El censo medido y las disposiciones explícitas dejaron de reconciliar."""


_COMPAT_ALIASES: tuple[dict[str, str], ...] = (
    {
        "path": "model.engine",
        "value": "glm_binomial",
        "canonical": "logit",
        "classification": "compat_alias_hidden",
        "reason": "Alias SemVer 1.x normalizado a la rama canónica y excluido del selector.",
        "authority": "SDD-30 D-RDY-ABA-5",
    },
    {
        "path": "selection.priority_order",
        "value": "gini",
        "canonical": "auc",
        "classification": "compat_alias_hidden",
        "reason": "Alias SemVer 1.x normalizado a la rama canónica y excluido del selector.",
        "authority": "SDD-30 D-RDY-ABA-5",
    },
    {
        "path": "report.formats",
        "value": "html",
        "canonical": "html_always_on",
        "classification": "compat_alias_hidden",
        "reason": "Alias SemVer 1.x de una base always-on, fuera del selector de formatos.",
        "authority": "SDD-30 D-RDY-ABA-5",
    },
    {
        "path": "markov.dynamics.projection_mode",
        "value": "period_matrices",
        "canonical": "unsupported_reserved",
        "classification": "unsupported_hidden",
        "reason": "Valor reservado rechazado hasta una enmienda que implemente su rama.",
        "authority": "SDD-30 D-RDY-ABA-6",
    },
)

# D-RDY-ABA-6: estas políticas son deliberadamente exhaustivas y exactas. No existe fallback:
# agregar o quitar un Literal obliga a revisar aquí su superficie, razón y autoridad.
_DETAIL_POLICIES: dict[str, tuple[str, ...]] = {
    "binning.feature_columns": ("*",),
    "binning.metric_missing": ("empirical",),
    "binning.metric_special": ("empirical",),
    "calibration.fit_partition": ("desarrollo",),
    "data.missing.special_values.columns": ("*",),
    "data.schema.columns.dtype": ("bool", "category", "datetime", "float", "int", "str"),
    "data.schema.strict": ("False", "True", "filter"),
    "data.target.bad_rule.all_of.op": (
        "!=",
        "<",
        "<=",
        "==",
        ">",
        ">=",
        "in",
        "isna",
        "notin",
        "notna",
    ),
    "data.target.bad_rule.any_of.op": (
        "!=",
        "<",
        "<=",
        "==",
        ">",
        ">=",
        "in",
        "isna",
        "notin",
        "notna",
    ),
    "data.target.exclusion_rules.rule.all_of.op": (
        "!=",
        "<",
        "<=",
        "==",
        ">",
        ">=",
        "in",
        "isna",
        "notin",
        "notna",
    ),
    "data.target.exclusion_rules.rule.any_of.op": (
        "!=",
        "<",
        "<=",
        "==",
        ">",
        ">=",
        "in",
        "isna",
        "notin",
        "notna",
    ),
    "data.target.good_rule.all_of.op": (
        "!=",
        "<",
        "<=",
        "==",
        ">",
        ">=",
        "in",
        "isna",
        "notin",
        "notna",
    ),
    "data.target.good_rule.any_of.op": (
        "!=",
        "<",
        "<=",
        "==",
        ">",
        ">=",
        "in",
        "isna",
        "notin",
        "notna",
    ),
    "data.target.indeterminate_rule.all_of.op": (
        "!=",
        "<",
        "<=",
        "==",
        ">",
        ">=",
        "in",
        "isna",
        "notin",
        "notna",
    ),
    "data.target.indeterminate_rule.any_of.op": (
        "!=",
        "<",
        "<=",
        "==",
        ">",
        ">=",
        "in",
        "isna",
        "notin",
        "notna",
    ),
    "model.sign_policy.expected_beta_sign": ("negative",),
    "report.ai.send_raw_data": ("False",),
    "report.language": ("es",),
    "scorecard.intercept_allocation": ("uniform",),
    "selection.feature_columns": ("*",),
}

_OUTSIDE_JOB_FORM_POLICIES: dict[str, tuple[str, ...]] = {
    "eda.analysis_partition": ("desarrollo", "holdout", "oot", "todas"),
    "eda.default_rate.axis": ("cohort", "period"),
    "eda.default_rate.period_freq": ("M", "Q", "Y"),
    "eda.stability.metric": ("cv", "max_relative_drift", "trend_slope"),
    "explain.contribution_space": ("log_odds", "probability"),
    "explain.explainer.feature_perturbation": ("interventional", "tree_path_dependent"),
    "explain.explainer.ml_explainer": ("auto", "kernel", "linear", "tree"),
    "explain.explainer.nsamples": ("auto",),
    "explain.local_scope.strategy": ("all", "none", "partition", "sample"),
    "explain.reason_codes.adverse_direction": ("increases_pd",),
    "explain.scorecard.baseline": ("neutral_zero", "population_mean"),
    "explain.targets": ("both", "ml", "scorecard"),
    "forward.input.pd_basis_assumption": ("pit", "ttc"),
    "forward.input.term_structure_sources": ("markov", "survival"),
    "forward.macro.kind": ("arima", "arimax", "auto_arima", "sarima", "var", "vecm"),
    "forward.satellite.mode": ("fit", "fixed_coefficients"),
    "forward.satellite.target_components": ("lgd", "pd"),
    "forward.ttc_reversion.method": ("linear_logit", "none"),
    "forward.ttc_reversion.ttc_anchor": ("historical_mean", "input_term_structure"),
    "markov.dynamics.embedding_policy": ("diagnose", "forbid", "regularize"),
    "markov.dynamics.projection_mode": ("aalen_johansen", "homogeneous"),
    "markov.estimation.method": ("cohort", "duration"),
    "ml.backend": ("catboost", "lightgbm", "random_forest", "svm", "xgboost"),
    "ml.comparison.metrics": ("auc", "gini", "ks", "psi"),
    "ml.feature_source": ("binning_woe", "data_raw", "selection_woe"),
    "ml.hyperparameters.gamma": ("auto", "scale"),
    "ml.hyperparameters.kernel": ("linear", "rbf"),
    "ml.hyperparameters.max_features": ("log2", "sqrt"),
    "ml.monotonic.mode": ("explicit", "from_binning", "off"),
    "ml.monotonic.on_unsupported": ("error", "warn"),
    "ml.train.class_weight": ("balanced", "none"),
    "stress.output.metrics": (
        "ecl",
        "lgd",
        "loss",
        "pd_cumulative",
        "pd_marginal",
        "provision",
        "ratio",
    ),
    "stress.reverse.operation": ("additive", "relative"),
    "stress.reverse.target.direction": ("at_least", "at_most"),
    "stress.reverse.target.metric": (
        "ecl",
        "lgd",
        "loss",
        "pd_cumulative",
        "pd_marginal",
        "provision",
        "ratio",
    ),
    "stress.scenarios.kind": ("custom", "severe"),
    "stress.scenarios.shocks.operation": ("additive", "relative"),
    "stress.scenarios.shocks.periods": ("all",),
    "stress.scenarios.shocks.source": ("default_a_confirmar", "institutional", "official", "user"),
    "stress.sensitivities.metric": (
        "ecl",
        "lgd",
        "loss",
        "pd_cumulative",
        "pd_marginal",
        "provision",
        "ratio",
    ),
    "stress.sensitivities.operation": ("additive", "relative"),
    "tuning.objective.direction": ("maximize",),
    "tuning.objective.metric": ("auc", "gini", "ks"),
    "tuning.optimizer.pruner": ("median", "none"),
    "tuning.optimizer.sampler": ("random", "tpe"),
    "tuning.validation.strategy": ("cv", "holdout"),
    "validation.backtesting.parameters": ("ead", "lgd", "pd"),
    "validation.backtesting.pd_test": ("binomial", "jeffreys"),
    "validation.calibration.hl_grouping": ("deciles", "fixed_bands"),
    "validation.calibration.pd_test": ("binomial", "jeffreys"),
    "validation.discrimination.partitions": ("desarrollo", "holdout", "oot"),
    "validation.families": ("backtesting", "calibration", "discrimination", "stability"),
}

_INTERNAL_DISCRIMINATOR_POLICIES: dict[str, tuple[str, ...]] = {
    "binning.type": ("standard",),
    "calibration.type": ("standard",),
    "data.type": ("standard",),
    "eda.type": ("standard",),
    "explain.type": ("standard",),
    "forward.type": ("standard",),
    "markov.type": ("standard",),
    "ml.type": ("standard",),
    "model.type": ("standard",),
    "performance.type": ("standard",),
    "provisioning.type": ("standard",),
    "provisioning_cmf.type": ("standard",),
    "provisioning_ifrs9.type": ("standard",),
    "provisioning_internal.type": ("standard",),
    "report.type": ("standard",),
    "scorecard.type": ("standard",),
    "selection.type": ("standard",),
    "stability.type": ("standard",),
    "stress.type": ("standard",),
    "survival.type": ("standard",),
    "tuning.type": ("standard",),
    "validation.type": ("standard",),
}

_GRAMMAR_POLICIES: dict[str, tuple[str, ...]] = {
    "data.partition.strategy.type": ("cohort", "columna", "random", "temporal"),
}

_GRAMMAR_OUTSIDE_JOB_FORM_POLICIES: dict[str, tuple[str, ...]] = {
    "forward.input.macro_source.type": ("artifact", "dataframe", "path"),
}


def _literal_values(annotation: Any) -> tuple[str, ...]:
    if get_origin(annotation) is Literal:
        return tuple(str(value) for value in get_args(annotation))
    if get_origin(annotation) in (Union, types.UnionType, tuple, list, frozenset, set):
        return tuple(
            value
            for branch in get_args(annotation)
            if branch is not Ellipsis and branch is not type(None)
            for value in _literal_values(branch)
        )
    return ()


def _submodels(annotation: Any) -> tuple[type[BaseModel], ...]:
    return tuple(
        candidate
        for candidate in (annotation, *get_args(annotation))
        if isinstance(candidate, type) and issubclass(candidate, BaseModel)
    )


def measured_literal_pairs() -> tuple[tuple[str, str], ...]:
    """Lee todos los ``Literal`` alcanzables desde las configs, sin usar el catálogo UI."""
    from nikodym.core.config.schema import cargar_configs_de_dominio

    found: set[tuple[str, str]] = set()

    def walk(classes: tuple[type[BaseModel], ...], prefix: str, depth: int = 0) -> None:
        if depth > 8:
            raise RuntimeError(f"profundidad inesperada al censar {prefix}")
        names = sorted({name for cls in classes for name in cls.model_fields})
        for name in names:
            infos = [cls.model_fields[name] for cls in classes if name in cls.model_fields]
            path = f"{prefix}{infos[0].alias or name}"
            for value in {value for info in infos for value in _literal_values(info.annotation)}:
                found.add((path, value))
            children = tuple(
                child
                for info in infos
                for child in _submodels(info.annotation)
                if child not in classes
            )
            if children:
                walk(children, f"{path}.", depth + 1)

    for section, config_cls in sorted(cargar_configs_de_dominio().items()):
        walk((config_cls,), f"{section}.")
    return tuple(sorted(found))


def classified_option_surface() -> dict[str, Any]:
    """Clasifica cada par del motor y los cuatro aliases ocultos contra contratos UI internos."""
    from nikodym.ui import jobs

    catalog = {
        (str(choice["path"]), str(option["value"])): str(option["estado"])
        for choices in jobs._ABANICO_POR_SECCION.values()
        for choice in choices
        for option in choice["options"]
    }
    decisions = {
        str(decision["path"])
        for choices in jobs._DECISIONES_POR_SECCION.values()
        for decision in choices
    }
    state_classification = {
        jobs._DISPONIBLE: "methodology_selectable",
        jobs._EXIGE_OTRO_CAMPO: "methodology_selectable_conditioned",
        jobs._NO_IMPLEMENTADA: "not_implemented_visible_disabled",
    }
    policy_groups = (
        (
            _DETAIL_POLICIES,
            "configuration_detail_selectable",
            "Config de detalle alcanzable por el formulario genérico; no es metodología D-JOB.",
            "SDD-30 D-RDY-ABA-6 / D-JOB-15",
        ),
        (
            _OUTSIDE_JOB_FORM_POLICIES,
            "outside_job_form",
            "Capacidad fuera del formulario por trabajos vigente; permanece alcanzable por API.",
            "SDD-30 D-RDY-ABA-6 / D-JOB-15",
        ),
        (
            _INTERNAL_DISCRIMINATOR_POLICIES,
            "internal_discriminator",
            "Discriminador estructural fijo; no representa una elección de producto.",
            "SDD-30 D-RDY-ABA-6",
        ),
        (
            _GRAMMAR_POLICIES,
            "configuration_grammar_selectable",
            "Variante de la gramática del config visible en el formulario, no metodología D-JOB.",
            "SDD-30 D-RDY-ABA-6 / SDD-23",
        ),
        (
            _GRAMMAR_OUTSIDE_JOB_FORM_POLICIES,
            "configuration_grammar_outside_job_form",
            "Variante de gramática fuera del formulario por trabajos vigente.",
            "SDD-30 D-RDY-ABA-6 / D-JOB-15",
        ),
    )
    policies: dict[tuple[str, str], tuple[str, str, str]] = {}
    for group, classification, reason, authority in policy_groups:
        for path, values in group.items():
            for value in values:
                pair = (path, value)
                if pair in policies:
                    raise UnclassifiedOptionSurfaceError(f"Política solapada para {pair!r}.")
                policies[pair] = (classification, reason, authority)

    measured = set(measured_literal_pairs())
    declared_non_methodology = set(policies)
    methodology = set(catalog)
    required = {(path, value) for path, value in measured if path in decisions}
    overlap = (declared_non_methodology & methodology) | (declared_non_methodology & required)
    if overlap:
        raise UnclassifiedOptionSurfaceError(
            f"Políticas no metodológicas solapan catálogo/decisiones: {sorted(overlap)!r}."
        )
    stale = declared_non_methodology - measured
    if stale:
        raise UnclassifiedOptionSurfaceError(f"Políticas sin Literal vigente: {sorted(stale)!r}.")
    unclassified = measured - methodology - required - declared_non_methodology
    if unclassified:
        raise UnclassifiedOptionSurfaceError(
            f"Literales sin disposición explícita: {sorted(unclassified)!r}."
        )
    entries = []
    for path, value in measured_literal_pairs():
        state = catalog.get((path, value))
        if state is not None:
            classification = state_classification[state]
            reason = "Par metodológico declarado en el catálogo D-JOB y sujeto a su gate de efecto."
            authority = "SDD-30 D-RDY-ABA-1…4"
        elif path in decisions:
            classification = "required_decision"
            reason = "Decisión institucional obligatoria separada del abanico metodológico."
            authority = "D-JOB / D-OBL"
        else:
            classification, reason, authority = policies[(path, value)]
        entries.append(
            {
                "path": path,
                "value": value,
                "classification": classification,
                "reason": reason,
                "authority": authority,
            }
        )
    aliases = [dict(alias) for alias in _COMPAT_ALIASES]
    alias_pairs = {(alias["path"], alias["value"]) for alias in aliases}
    if alias_pairs & (measured | methodology):
        raise UnclassifiedOptionSurfaceError("Un alias oculto reapareció en motor o catálogo.")
    return {
        "schema_version": 2,
        "entries": entries,
        "aliases": aliases,
    }
