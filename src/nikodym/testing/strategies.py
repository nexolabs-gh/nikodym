"""Estrategias Hypothesis públicas para configs Nikodym (SDD-24).

``hypothesis`` es una dependencia de desarrollo, no del wheel. Por eso este módulo no la importa al
cargarse: la función que construye estrategias hace el import perezoso y falla con un mensaje
explícito si el usuario no la instaló en su entorno de test.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Literal, cast, get_args, get_origin

from nikodym.core.config import NikodymConfig, ReproConfig, RunConfig
from nikodym.core.config import schema as core_schema
from nikodym.core.exceptions import MissingDependencyError

if TYPE_CHECKING:
    from hypothesis.strategies import SearchStrategy

__all__ = ["discriminated_union_tags", "nikodym_config_strategy"]

_SECTION_MODULES: dict[str, str] = {
    "binning": "nikodym.binning",
    "calibration": "nikodym.calibration",
    "data": "nikodym.data",
    "eda": "nikodym.eda",
    "model": "nikodym.model",
    "performance": "nikodym.performance",
    "provisioning_cmf": "nikodym.provisioning.cmf",
    "scorecard": "nikodym.scorecard",
    "selection": "nikodym.selection",
    "stability": "nikodym.stability",
}
_REGISTRY_SECTION_MODULES: dict[str, str] = {"data": "nikodym.data"}


def _hypothesis_strategies() -> Any:
    """Importa ``hypothesis.strategies`` de forma perezosa."""
    try:
        return importlib.import_module("hypothesis.strategies")
    except ImportError as exc:
        raise MissingDependencyError(
            "Las estrategias Hypothesis de nikodym.testing requieren `hypothesis` (MPL-2.0). "
            "Instálalo en tu entorno de test (`pip install hypothesis`) o usa el grupo de "
            "desarrollo del proyecto."
        ) from exc


def nikodym_config_strategy(
    *,
    sections: list[str] | None = None,
    require_data: bool = False,
) -> SearchStrategy[NikodymConfig]:
    """Construye una estrategia Hypothesis que genera ``NikodymConfig`` válidos.

    Parameters
    ----------
    sections : list[str] | None
        Subconjunto de secciones opcionales que pueden venir activas.
    require_data : bool
        Si es ``True``, la sección ``data`` se genera siempre y se importa perezosamente
        ``nikodym.data`` para activar su hook de Pydantic.
    """
    st = _hypothesis_strategies()
    allowed = set(sections or [])
    if require_data:
        allowed.add("data")
    unknown = allowed - set(_SECTION_MODULES)
    if unknown:
        raise ValueError(f"Secciones no soportadas por nikodym_config_strategy: {sorted(unknown)}.")

    repro = st.builds(
        ReproConfig,
        seed=st.integers(min_value=0, max_value=2**32 - 1),
        strict_determinism=st.booleans(),
    )
    run = st.builds(RunConfig, steps=st.none(), fail_fast=st.booleans())
    data = _data_config_strategy(st) if "data" in allowed else st.none()
    eda = _eda_config_strategy(st) if "eda" in allowed else st.none()
    binning = _binning_config_strategy(st) if "binning" in allowed else st.none()
    selection = _selection_config_strategy(st) if "selection" in allowed else st.none()
    model = _model_config_strategy(st) if "model" in allowed else st.none()
    scorecard = _scorecard_config_strategy(st) if "scorecard" in allowed else st.none()
    calibration = _calibration_config_strategy(st) if "calibration" in allowed else st.none()
    provisioning_cmf = (
        _cmf_provisioning_config_strategy(st) if "provisioning_cmf" in allowed else st.none()
    )
    performance = _performance_config_strategy(st) if "performance" in allowed else st.none()
    stability = _stability_config_strategy(st) if "stability" in allowed else st.none()
    return cast(
        "SearchStrategy[NikodymConfig]",
        st.builds(
            NikodymConfig,
            schema_version=st.just("1.0.0"),
            name=st.sampled_from(["nikodym-study", "contrato-testing", "riesgo-crediticio"]),
            repro=repro,
            run=run,
            data=data,
            eda=eda,
            binning=binning,
            selection=selection,
            model=model,
            scorecard=scorecard,
            calibration=calibration,
            provisioning_cmf=provisioning_cmf,
            performance=performance,
            stability=stability,
            audit=st.none(),
            governance=st.none(),
            tracking=st.none(),
        ),
    )


def _data_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``DataConfig`` que respeta validadores cross-field."""
    importlib.import_module("nikodym.data")
    from nikodym.data.config import (
        CohortSplitConfig,
        DataConfig,
        PartitionConfig,
        Predicate,
        RandomSplitConfig,
        Rule,
        TargetConfig,
        TemporalSplitConfig,
    )

    bad_rule = st.builds(
        Rule,
        all_of=st.tuples(
            st.builds(Predicate, col=st.just("dpd_12m"), op=st.just(">="), value=st.just(90))
        ),
        any_of=st.just(()),
    )
    partition_strategy = st.one_of(
        st.builds(
            RandomSplitConfig,
            dev_fraction=st.just(0.7),
            holdout_fraction=st.just(0.15),
            oot_fraction=st.just(0.15),
            stratify_by=st.none(),
        ),
        st.builds(
            TemporalSplitConfig,
            date_col=st.just("fecha_obs"),
            oot_from=st.just("2025-01-01"),
            holdout_fraction=st.floats(min_value=0.0, max_value=0.8, allow_nan=False),
        ),
        st.builds(
            CohortSplitConfig,
            cohort_col=st.just("cohorte"),
            oot_cohorts=st.just(("2025Q1",)),
            holdout_fraction=st.floats(min_value=0.0, max_value=0.8, allow_nan=False),
        ),
    )
    return st.builds(
        DataConfig,
        target=st.builds(TargetConfig, bad_rule=bad_rule),
        partition=st.builds(
            PartitionConfig,
            strategy=partition_strategy,
            ttd_includes_excluded=st.booleans(),
            min_bads_per_partition=st.integers(min_value=0, max_value=100),
        ),
    )


def _binning_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``BinningConfig`` que respeta rangos y literales."""
    importlib.import_module("nikodym.binning")
    from nikodym.binning.config import BinningConfig, VariableBinningConfig

    monotonic_trends = [
        "auto",
        "auto_heuristic",
        "auto_asc_desc",
        "ascending",
        "descending",
        "concave",
        "convex",
        "peak",
        "peak_heuristic",
        "valley",
        "valley_heuristic",
    ]
    override = st.builds(
        VariableBinningConfig,
        name=st.sampled_from(["ingreso", "saldo", "mora_ult_6m"]),
        dtype=st.sampled_from(["numerical", "categorical", "auto"]),
        monotonic_trend=st.one_of(st.none(), st.sampled_from(monotonic_trends)),
        max_n_bins=st.one_of(st.none(), st.integers(min_value=2, max_value=20)),
        min_bin_size=st.one_of(st.none(), st.floats(min_value=0.0, max_value=0.5, allow_nan=False)),
        cat_cutoff=st.one_of(st.none(), st.floats(min_value=0.0, max_value=0.5, allow_nan=False)),
    )
    return st.builds(
        BinningConfig,
        feature_columns=st.one_of(st.just("*"), st.just(("ingreso", "saldo"))),
        exclude_columns=st.just(()),
        categorical_columns=st.just(()),
        variable_overrides=st.one_of(st.just(()), st.tuples(override)),
        max_n_prebins=st.integers(min_value=2, max_value=50),
        min_prebin_size=st.floats(min_value=0.001, max_value=0.5, allow_nan=False),
        min_n_bins=st.none(),
        max_n_bins=st.one_of(st.none(), st.integers(min_value=2, max_value=20)),
        min_bin_size=st.one_of(st.none(), st.floats(min_value=0.0, max_value=0.5, allow_nan=False)),
        min_bin_n_event=st.one_of(st.none(), st.integers(min_value=1, max_value=20)),
        min_bin_n_nonevent=st.one_of(st.none(), st.integers(min_value=1, max_value=20)),
        monotonic_trend=st.one_of(st.none(), st.sampled_from(monotonic_trends)),
        min_event_rate_diff=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        max_pvalue=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        max_pvalue_policy=st.sampled_from(["consecutive", "all"]),
        solver=st.sampled_from(["cp", "mip"]),
        mip_solver=st.sampled_from(["bop", "cbc"]),
        time_limit=st.integers(min_value=1, max_value=3600),
        require_optimal=st.booleans(),
        n_jobs=st.one_of(st.none(), st.sampled_from([-1, 1, 2])),
        special_handling=st.sampled_from(["separate", "as_missing"]),
        metric_special=st.one_of(st.just("empirical"), st.floats(allow_nan=False)),
        metric_missing=st.one_of(st.just("empirical"), st.floats(allow_nan=False)),
        cat_cutoff=st.one_of(st.none(), st.floats(min_value=0.0, max_value=0.5, allow_nan=False)),
        cat_unknown=st.one_of(st.none(), st.just("empirical"), st.floats(allow_nan=False)),
        split_digits=st.one_of(st.none(), st.integers(min_value=0, max_value=10)),
        output_suffix=st.sampled_from(["__woe", "_woe"]),
        keep_structural_columns=st.booleans(),
        fail_on_non_binnable=st.booleans(),
    )


def _eda_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``EdaConfig`` que respeta rangos y literales."""
    importlib.import_module("nikodym.eda")
    from nikodym.eda.config import (
        DefaultRateConfig,
        EdaConfig,
        QualityConfig,
        SamplingConfig,
        TemporalStabilityConfig,
        UnivariateConfig,
    )

    return st.builds(
        EdaConfig,
        analysis_partition=st.sampled_from(["desarrollo", "holdout", "oot", "todas"]),
        default_rate=st.builds(
            DefaultRateConfig,
            axis=st.sampled_from(["period", "cohort"]),
            date_col=st.one_of(st.none(), st.sampled_from(["fecha_obs", "fecha_corte"])),
            period_freq=st.sampled_from(["M", "Q", "Y"]),
            cohort_col=st.one_of(st.none(), st.sampled_from(["cohorte", "vintage"])),
            min_obs_per_period=st.integers(min_value=1, max_value=500),
        ),
        stability=st.builds(
            TemporalStabilityConfig,
            metric=st.sampled_from(["cv", "max_relative_drift", "trend_slope"]),
            threshold=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
        ),
        univariate=st.builds(
            UnivariateConfig,
            n_quantile_bins=st.integers(min_value=2, max_value=50),
            rare_level_threshold=st.floats(min_value=0.0, max_value=0.5, allow_nan=False),
            compute_descriptive_iv=st.booleans(),
            columns=st.one_of(st.none(), st.just(("ingreso", "saldo"))),
        ),
        quality=st.builds(
            QualityConfig,
            near_constant_threshold=st.floats(min_value=0.5, max_value=1.0, allow_nan=False),
            high_cardinality_threshold=st.integers(min_value=2, max_value=500),
        ),
        sampling=st.builds(
            SamplingConfig,
            enabled=st.booleans(),
            max_rows=st.integers(min_value=1000, max_value=1_000_000),
        ),
    )


def _selection_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``SelectionConfig`` que respeta rangos y overrides."""
    importlib.import_module("nikodym.selection")
    from nikodym.selection.config import (
        CorrelationSelectionConfig,
        SelectionConfig,
        StabilitySelectionConfig,
        VifSelectionConfig,
    )

    prioridades = ("iv", "auc", "ks", "gini", "name")
    return st.builds(
        SelectionConfig,
        feature_columns=st.one_of(st.just("*"), st.just(("ingreso", "saldo"))),
        exclude_columns=st.just(()),
        force_include=st.just(()),
        force_exclude=st.one_of(st.just(()), st.just(("mora_ult_6m",))),
        min_iv=st.floats(min_value=0.0, max_value=0.5, allow_nan=False),
        max_iv=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        max_iv_action=st.sampled_from(["flag", "exclude"]),
        compute_univariate_metrics=st.booleans(),
        min_auc=st.one_of(st.none(), st.floats(min_value=0.5, max_value=1.0, allow_nan=False)),
        min_ks=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        min_gini=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        priority_order=st.one_of(
            st.just(("iv", "auc", "ks", "name")),
            st.permutations(prioridades),
        ),
        correlation=st.builds(
            CorrelationSelectionConfig,
            enabled=st.booleans(),
            method=st.sampled_from(["pearson", "spearman", "kendall"]),
            threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            clustering_method=st.sampled_from(["none", "connected_components"]),
        ),
        vif=st.builds(
            VifSelectionConfig,
            enabled=st.booleans(),
            threshold=st.floats(min_value=1.0, max_value=20.0, allow_nan=False),
            add_intercept=st.booleans(),
            max_iterations=st.one_of(st.none(), st.integers(min_value=1, max_value=20)),
        ),
        stability=st.builds(
            StabilitySelectionConfig,
            enabled=st.booleans(),
            action=st.sampled_from(["report_only", "exclude"]),
            stable_threshold=st.floats(min_value=0.0, max_value=0.25, allow_nan=False),
            review_threshold=st.floats(min_value=0.0, max_value=0.5, allow_nan=False),
            smoothing=st.floats(min_value=1e-9, max_value=1e-3, allow_nan=False),
        ),
        keep_structural_columns=st.booleans(),
        fail_if_no_features=st.booleans(),
    )


def _model_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``ModelConfig`` que respeta rangos y overrides."""
    importlib.import_module("nikodym.model")
    from nikodym.model.config import (
        IvContributionConfig,
        ModelConfig,
        SignPolicyConfig,
        StepwiseConfig,
    )

    return st.builds(
        ModelConfig,
        engine=st.sampled_from(["logit", "glm_binomial"]),
        fit_intercept=st.booleans(),
        optimizer=st.sampled_from(["newton", "bfgs", "lbfgs"]),
        fit_maxiter=st.integers(min_value=1, max_value=500),
        tol=st.floats(min_value=1e-12, max_value=1e-3, allow_nan=False),
        alpha=st.floats(min_value=1e-6, max_value=0.5, allow_nan=False),
        stepwise=st.builds(
            StepwiseConfig,
            enabled=st.booleans(),
            direction=st.sampled_from(["none", "forward", "backward", "bidirectional"]),
            criterion=st.sampled_from(["wald_pvalue", "lr_test", "both"]),
            entry_p_value=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            exit_p_value=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            max_iter=st.integers(min_value=1, max_value=200),
            min_features=st.integers(min_value=1, max_value=20),
        ),
        sign_policy=st.builds(
            SignPolicyConfig,
            expected_beta_sign=st.just("negative"),
            action=st.sampled_from(["exclude", "flag", "fail"]),
            fail_on_forced_inverted=st.booleans(),
        ),
        iv_contribution=st.builds(
            IvContributionConfig,
            threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            action=st.sampled_from(["exclude", "flag", "fail"]),
        ),
        force_include=st.just(()),
        force_exclude=st.one_of(st.just(()), st.just(("mora_ult_6m",))),
        fail_if_no_features=st.booleans(),
    )


def _scorecard_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``ScorecardConfig`` que respeta rangos y overrides."""
    importlib.import_module("nikodym.scorecard")
    from nikodym.scorecard.config import PointOverrideConfig, ScorecardConfig

    override = st.builds(
        PointOverrideConfig,
        feature=st.sampled_from(["ingreso", "saldo", "mora_ult_6m"]),
        bin_label=st.sampled_from(["(-inf, 0]", "(0, 1]", "missing"]),
        points=st.integers(min_value=-500, max_value=500),
        reason=st.sampled_from(["alineamiento negocio", "corrección auditoría"]),
    )
    return st.builds(
        ScorecardConfig,
        pdo=st.floats(min_value=1.0, max_value=100.0, allow_nan=False),
        target_score=st.floats(min_value=100.0, max_value=1000.0, allow_nan=False),
        target_odds=st.floats(min_value=1.0, max_value=500.0, allow_nan=False),
        score_direction=st.sampled_from(["higher_is_lower_risk", "higher_is_higher_risk"]),
        intercept_allocation=st.just("uniform"),
        rounding_method=st.sampled_from(
            ["none", "nearest_integer", "floor_integer", "ceil_integer"]
        ),
        output_suffix=st.sampled_from(["__points", "_points"]),
        score_column=st.sampled_from(["score", "score_total"]),
        min_score=st.one_of(st.none(), st.floats(min_value=0.0, max_value=500.0, allow_nan=False)),
        max_score=st.one_of(
            st.none(),
            st.floats(min_value=501.0, max_value=1200.0, allow_nan=False),
        ),
        clip=st.just(False),
        point_overrides=st.one_of(st.just(()), st.tuples(override)),
    )


def _calibration_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``CalibrationConfig`` que respeta rangos y columnas."""
    importlib.import_module("nikodym.calibration")
    from nikodym.calibration.config import CalibrationConfig

    return st.builds(
        CalibrationConfig,
        method=st.sampled_from(["intercept_offset", "platt_scaling", "isotonic"]),
        target_pd=st.floats(min_value=1e-6, max_value=0.5, allow_nan=False),
        anchor_kind=st.sampled_from(["through_the_cycle", "point_in_time"]),
        anchor_source=st.sampled_from(
            ["business_input", "historical_default_rate", "development_observed"]
        ),
        target_tolerance=st.floats(min_value=1e-12, max_value=1e-4, allow_nan=False),
        max_abs_offset=st.one_of(
            st.none(),
            st.floats(min_value=1e-6, max_value=10.0, allow_nan=False),
        ),
        max_iter=st.integers(min_value=1, max_value=500),
        min_fit_rows=st.integers(min_value=1, max_value=10_000),
        require_both_classes_for_supervised=st.just(True),
        pd_raw_column=st.just("pd_raw"),
        linear_predictor_column=st.just("linear_predictor"),
        pd_calibrated_column=st.just("pd_calibrated"),
        linear_predictor_calibrated_column=st.just("linear_predictor_calibrated"),
        partition_column=st.just("partition"),
        target_column=st.just("target"),
    )


def _performance_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``PerformanceConfig`` que respeta rangos y columnas."""
    importlib.import_module("nikodym.performance")
    from nikodym.performance.config import PerformanceConfig

    threshold_values = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
    return st.builds(
        PerformanceConfig,
        score_column=st.just("score"),
        pd_column=st.just("pd_calibrated"),
        target_column=st.just("target"),
        partition_column=st.just("partition"),
        score_direction=st.sampled_from(["higher_is_lower_risk", "higher_is_higher_risk"]),
        evaluation_source=st.sampled_from(["pd_calibrated", "score"]),
        partitions=st.one_of(
            st.just(("desarrollo", "holdout", "oot")),
            st.just(("desarrollo",)),
            st.just(("holdout", "oot")),
        ),
        n_deciles=st.integers(min_value=2, max_value=50),
        min_rows_per_partition=st.integers(min_value=1, max_value=10_000),
        min_events_per_partition=st.integers(min_value=1, max_value=1_000),
        optional_thresholds=st.dictionaries(
            keys=st.sampled_from(["auc_min", "gini_min", "ks_min", "psi_max", "csi_max"]),
            values=threshold_values,
            max_size=3,
        ),
    )


def _cmf_provisioning_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``CmfProvisioningConfig`` que respeta validadores CMF."""
    importlib.import_module("nikodym.provisioning.cmf")
    from nikodym.provisioning.cmf.config import (
        CmfExposureConfig,
        CmfGuaranteeConfig,
        CmfPdMappingConfig,
        CmfProvisioningConfig,
    )

    pd_mapping = st.one_of(
        st.builds(CmfPdMappingConfig),
        st.builds(
            CmfPdMappingConfig,
            method=st.just("pd_breaks"),
            pd_breaks=st.just((0.02, 0.10, 0.30)),
            categories=st.just(("A1", "A4", "B2", "B4")),
        ),
    )
    guarantees = st.one_of(
        st.builds(
            CmfGuaranteeConfig,
            financial_guarantee_policy=st.sampled_from(["fail", "ignore_if_missing"]),
        ),
        st.builds(
            CmfGuaranteeConfig,
            financial_guarantee_policy=st.just("use_recoverable_amount"),
            recoverable_amount_col=st.just("recoverable_amount"),
        ),
    )
    return st.builds(
        CmfProvisioningConfig,
        category_col=st.just("cmf_category"),
        pd_mapping=pd_mapping,
        exposure=st.builds(
            CmfExposureConfig,
            allow_negative_exposure=st.booleans(),
            rounding=st.sampled_from(["none", "currency_2dp", "integer_currency"]),
        ),
        guarantees=guarantees,
    )


def _stability_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``StabilityConfig`` que respeta rangos y columnas."""
    importlib.import_module("nikodym.stability")
    from nikodym.stability.config import StabilityConfig

    stable = st.floats(min_value=0.0, max_value=0.24, allow_nan=False)
    gap = st.floats(min_value=1e-6, max_value=0.76, allow_nan=False)
    return st.builds(
        lambda psi_stable_threshold, threshold_gap, **kwargs: StabilityConfig(
            psi_stable_threshold=psi_stable_threshold,
            psi_review_threshold=psi_stable_threshold + threshold_gap,
            **kwargs,
        ),
        score_column=st.just("score"),
        pd_column=st.just("pd_calibrated"),
        partition_column=st.just("partition"),
        score_direction=st.sampled_from(["higher_is_lower_risk", "higher_is_higher_risk"]),
        psi_bins=st.integers(min_value=2, max_value=50),
        csi_bins=st.integers(min_value=2, max_value=50),
        psi_stable_threshold=stable,
        threshold_gap=gap,
        smoothing=st.floats(min_value=1e-12, max_value=1.0, allow_nan=False),
        comparisons=st.one_of(
            st.just(("dev_vs_holdout", "dev_vs_oot")),
            st.just(("dev_vs_holdout",)),
            st.just(("dev_vs_oot",)),
        ),
        temporal_axis=st.sampled_from(["none", "period", "cohort"]),
        temporal_column=st.one_of(st.none(), st.just("periodo"), st.just("cohorte")),
        temporal_freq=st.sampled_from(["M", "Q", "Y"]),
        include_pd_stability=st.booleans(),
        csi_source=st.just("score_points"),
    )


def discriminated_union_tags() -> dict[str, list[str]]:
    """Devuelve tags ``type`` de uniones discriminadas de nivel sección.

    Solo cruza secciones resueltas por el ``REGISTRY`` global. Las uniones anidadas, como
    ``data.partition.strategy``, son factories locales y no aparecen aquí.
    """
    result: dict[str, list[str]] = {}
    for domain, module_name in _REGISTRY_SECTION_MODULES.items():
        importlib.import_module(module_name)
        config_cls = _config_cls_for_domain(domain)
        tags = _literal_tags(config_cls.model_fields["type"].annotation)
        result[domain] = tags
    return result


def _config_cls_for_domain(domain: str) -> type[Any]:
    """Resuelve la clase de config de una sección cargada por hook diferido."""
    if domain == "data" and core_schema._DATA_CONFIG_CLS is not None:
        return core_schema._DATA_CONFIG_CLS
    if domain == "eda" and core_schema._EDA_CONFIG_CLS is not None:
        return core_schema._EDA_CONFIG_CLS
    if domain == "binning" and core_schema._BINNING_CONFIG_CLS is not None:
        return core_schema._BINNING_CONFIG_CLS
    if domain == "selection" and core_schema._SELECTION_CONFIG_CLS is not None:
        return core_schema._SELECTION_CONFIG_CLS
    if domain == "model" and core_schema._MODEL_CONFIG_CLS is not None:
        return core_schema._MODEL_CONFIG_CLS
    if domain == "scorecard" and core_schema._SCORECARD_CONFIG_CLS is not None:
        return core_schema._SCORECARD_CONFIG_CLS
    if domain == "calibration" and core_schema._CALIBRATION_CONFIG_CLS is not None:
        return core_schema._CALIBRATION_CONFIG_CLS
    if domain == "provisioning_cmf" and core_schema._PROVISIONING_CMF_CONFIG_CLS is not None:
        return core_schema._PROVISIONING_CMF_CONFIG_CLS
    if domain == "performance" and core_schema._PERFORMANCE_CONFIG_CLS is not None:
        return core_schema._PERFORMANCE_CONFIG_CLS
    if domain == "stability" and core_schema._STABILITY_CONFIG_CLS is not None:
        return core_schema._STABILITY_CONFIG_CLS
    raise AssertionError(f"No hay config_cls cargada para el dominio '{domain}'.")


def _literal_tags(annotation: Any) -> list[str]:
    """Extrae tags string desde ``Literal[...]``."""
    if get_origin(annotation) is not Literal:
        return []
    return [value for value in get_args(annotation) if isinstance(value, str)]
