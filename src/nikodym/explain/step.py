"""Paso orquestable de la capa ``explain`` (SDD-14 §7/§9; CT-1/CT-2). Cierra F2.

``ExplainStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``explain``:
orquesta el :class:`~nikodym.explain.engine.UnifiedExplainer` (B14.4) para explicar el **challenger
ML** vía SHAP (mitad ML) y —opcionalmente— el **scorecard logístico** de forma analítica exacta
(mitad scorecard), traduce las contribuciones a reason codes, arma la comparativa de drivers
scorecard-vs-ML, emite las decisiones auditables (§9) y publica las siete claves estables bajo
``domain='explain'``. Es el **último paso de F2** (Machine Learning).

**``requires`` dinámicos (CT-1, SDD-14 §2/§6).** ``from_config`` compone las dependencias según
``targets`` y (en ``execute``) la ``feature_source`` **heredada de ``NikodymConfig.ml``**: siempre
``data.labels``/``data.splits``; si ``targets ∈ {ml, both}`` añade ``ml.estimator``/
``ml.backend_metadata``/``ml.pd_frame`` + la fuente de features (``binning.woe_frame`` o
``selection.selected_woe_frame``+``selected_woe_columns``); si ``targets='scorecard'`` añade
``model.coefficients``/``scorecard.scorecard``/``binning.tables`` + la fuente de features (duro),
y **no** exige claves de ``ml``. Bajo ``targets='both'`` la mitad scorecard es **best-effort** (no
entra a ``requires``): si faltan sus artefactos se degrada a ML con
``log_decision('explain_scorecard_skipped')`` y ``scorecard_contributions=None``, sin romper. La
``binning.summary`` (IV para la comparativa) también es best-effort. Un ``requires`` ausente levanta
:class:`~nikodym.core.exceptions.ArtifactNotFoundError` **antes** de ejecutar.

**Núcleo liviano (SDD-14 §9).** El módulo **no** importa ``shap``/``matplotlib``/``pandas``/
``numpy``/``sklearn`` en import time; ``nikodym.explain`` lo importa sólo para ejecutar
``@register('standard', domain='explain')``. Todo lo pesado (``pandas``/``numpy`` y —si
``emit_figures``— ``matplotlib``) se carga **perezosamente** dentro de ``execute``; el ``shap`` lo
importa el motor sólo si hay mitad ML. El motor v1 es determinista y ``explain`` **descarta** el
``rng`` por-paso (``del rng``): todo su azar sale de
``SeedManager.int_seed_for('explain')`` (entropía compuesta ``[root_seed, sha256('explain')]``,
nunca ``hash()`` builtin).

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.explain.config import ExplainConfig
from nikodym.explain.engine import UnifiedExplainer
from nikodym.explain.exceptions import ExplainConfigError, ExplainDataError
from nikodym.explain.results import (
    ExplainCardSection,
    ExplainerMetadata,
    ExplainResult,
    ShapGlobalRecord,
)

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study
    from nikodym.explain.engine import ExplanationBundle

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditEvent: TypeAlias = Any
    Study: TypeAlias = Any
    ExplanationBundle: TypeAlias = Any
    DataFrame: TypeAlias = Any

__all__ = ["EXPLAIN_ARTIFACTS", "ExplainStep"]

EXPLAIN_ARTIFACTS: Final[tuple[str, ...]] = (
    "shap_global",
    "shap_local",
    "reason_codes",
    "scorecard_contributions",
    "comparison",
    "result",
    "card",
)
_EXTRA_MESSAGE: Final = "ExplainStep requiere pandas/numpy; instale nikodym[ml]."
_DATA_DOMAIN: Final = "data"
_ML_DOMAIN: Final = "ml"
_BINNING_DOMAIN: Final = "binning"
_SELECTION_DOMAIN: Final = "selection"
_MODEL_DOMAIN: Final = "model"
_SCORECARD_DOMAIN: Final = "scorecard"
# Fuente de features por defecto sin ``ml`` (targets='scorecard'): la ``binning.woe_frame``.
_DEFAULT_FEATURE_SOURCE: Final = "binning_woe"
# Tolerancia absoluta de la consistencia de ``points`` del scorecard con SDD-09 §7 (deuda B14.4(3)).
_POINTS_CONSISTENCY_ATOL: Final = 1e-6
# Nº de features de mayor importancia global que ilustran la figura SHAP summary del card (§9).
_FIGURE_TOP_FEATURES: Final = 20


@register("standard", domain="explain")
class ExplainStep(AuditableMixin):
    """Orquesta la explicabilidad unificada y publica ``domain='explain'`` (SDD-14 §4/§7)."""

    name: str = "explain"
    requires: tuple[ArtifactKey, ...] = ()
    provides: tuple[ArtifactKey, ...] = tuple(("explain", key) for key in EXPLAIN_ARTIFACTS)

    def __init__(self, config: ExplainConfig) -> None:
        """Construye el paso desde ``ExplainConfig`` y declara ``requires`` (CT-1).

        ``from_config`` no recibe la ``MLConfig``, así que los ``requires`` estáticos usan la fuente
        de features por defecto (``binning_woe``); :meth:`execute` los **re-deriva** desde la
        ``NikodymConfig.ml`` real (``feature_source``) y **re-valida** su presencia (CT-1).
        """
        self.config = config
        self.requires = _requires_for(config.targets, _DEFAULT_FEATURE_SOURCE)

    @classmethod
    def from_config(cls, cfg: ExplainConfig) -> ExplainStep:
        """Construye ``ExplainStep`` desde ``NikodymConfig.explain``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` si un motor futuro lo requiere."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> ExplainResult:
        """Explica ML (SHAP) y/o scorecard (analítico), audita y publica siete artefactos (§7)."""
        del rng  # su azar sale de int_seed_for('explain'), no del rng por-paso (SDD-14 §7.3)
        np = _import_numpy()
        pd = _import_pandas()

        cfg = _explain_config_from_study(study, fallback=self.config)
        ml_cfg = _ml_config_from_study(study)
        if cfg.targets in ("ml", "both") and ml_cfg is None:
            raise ExplainConfigError(
                f"targets='{cfg.targets}' exige una sección 'ml' activa (no hay challenger que "
                "explicar): declare 'ml' o use targets='scorecard'."
            )
        feature_source = _resolve_feature_source(ml_cfg)
        requires = _requires_for(cfg.targets, feature_source)
        _require_present(study, requires)

        seed = study.seed_manager.int_seed_for("explain")
        target_col, partition_col = _read_frame_metadata(study)
        feature_frame, feature_columns = _read_feature_frame(study, feature_source, pd)
        _validate_features(feature_frame, feature_columns, target_col, partition_col)

        engine = UnifiedExplainer.from_config(cfg)

        ml_bundle = self._explain_ml_half(
            study, engine, cfg, feature_frame, feature_columns, partition_col, seed, np, pd
        )
        scorecard_bundle, scorecard_consistency = self._explain_scorecard_half(
            study, engine, cfg, feature_frame, partition_col, pd
        )
        comparison = (
            engine.compare_drivers(scorecard_bundle, ml_bundle, top_k=cfg.output.top_k_comparison)
            if ml_bundle is not None
            else ()
        )

        backend_metadata = (
            study.artifacts.get(_ML_DOMAIN, "backend_metadata") if ml_bundle is not None else None
        )
        result = _assemble_result(
            cfg,
            ml_bundle=ml_bundle,
            scorecard_bundle=scorecard_bundle,
            comparison=comparison,
            backend_metadata=backend_metadata,
            seed=seed,
        )
        self._emit_decisions(
            cfg,
            ml_bundle=ml_bundle,
            scorecard_bundle=scorecard_bundle,
            scorecard_consistency=scorecard_consistency,
            comparison=comparison,
            backend_metadata=backend_metadata,
            n_features=len(feature_columns),
            seed=seed,
        )
        _publish_artifacts(study, result)
        return result

    # --- mitad ML (SHAP vía UnifiedExplainer, SDD-14 §7 paso 5) --------------------------------

    def _explain_ml_half(
        self,
        study: Study,
        engine: UnifiedExplainer,
        cfg: ExplainConfig,
        feature_frame: DataFrame,
        feature_columns: tuple[str, ...],
        partition_col: str,
        seed: int,
        np: Any,
        pd: Any,
    ) -> ExplanationBundle | None:
        """Explica el challenger sobre el scope local; ``None`` si ``targets='scorecard'`` (§7)."""
        if cfg.targets == "scorecard":
            return None
        estimator = study.artifacts.get(_ML_DOMAIN, "estimator")
        _validate_estimator(estimator)
        pd_hat_by_index = _pd_hat_by_index(study, cfg, pd) if cfg.local_scope.top_by_pd else None
        scope_frame = _resolve_scope(
            feature_frame, partition_col, cfg, pd_hat_by_index, seed, np, pd
        )
        background = _resolve_background(
            feature_frame, feature_columns, partition_col, cfg, seed, np
        )
        return engine.explain_ml(
            estimator,
            scope_frame,
            background=background,
            seed=seed,
            audit=self._audit,
            partition=cfg.local_scope.partition,
        )

    # --- mitad scorecard (analítico exacto, SDD-14 §7 paso 6) ----------------------------------

    def _explain_scorecard_half(
        self,
        study: Study,
        engine: UnifiedExplainer,
        cfg: ExplainConfig,
        feature_frame: DataFrame,
        partition_col: str,
        pd: Any,
    ) -> tuple[ExplanationBundle | None, dict[str, Any] | None]:
        """Explica el scorecard si aplica; degrada (best-effort) bajo ``targets='both'`` (§7)."""
        if cfg.targets == "ml":
            return None, None
        if cfg.targets == "both" and not _scorecard_present(study):
            return None, None  # degradación: compare_drivers audita explain_scorecard_skipped
        coefficients = _read_coefficients(study, pd)
        woe_tables = _read_binning_tables(study)
        binning_summary = _read_binning_summary(study, pd)
        baseline_frame = _baseline_partition_frame(feature_frame, partition_col, cfg)
        bundle = engine.explain_scorecard(
            coefficients,
            woe_tables,
            baseline_frame,
            audit=self._audit,
            binning_summary=binning_summary,
            partition=cfg.scorecard.baseline_partition,
        )
        consistency = _scorecard_points_consistency(_read_scorecard_table(study, pd), study)
        return bundle, consistency

    # --- auditoría (§9) ------------------------------------------------------------------------

    def _emit_decisions(
        self,
        cfg: ExplainConfig,
        *,
        ml_bundle: ExplanationBundle | None,
        scorecard_bundle: ExplanationBundle | None,
        scorecard_consistency: dict[str, Any] | None,
        comparison: tuple[Any, ...],
        backend_metadata: Any,
        n_features: int,
        seed: int,
    ) -> None:
        """Registra el ``log_decision`` §9 que el motor no emite (targets/seed/background/…)."""
        self.log_decision(
            regla="explain_targets",
            umbral=cfg.targets,
            valor={
                "targets": cfg.targets,
                "ml_explained": ml_bundle is not None,
                "scorecard_explained": scorecard_bundle is not None,
                "scorecard_skipped": cfg.targets == "both" and scorecard_bundle is None,
            },
            accion="seleccionar_objetivos",
        )
        explanation_deterministic = bool(ml_bundle.deterministic) if ml_bundle is not None else True
        self.log_decision(
            regla="explain_seed",
            umbral=int(seed),
            valor={
                "seed": int(seed),
                "n_threads": int(cfg.n_threads),
                "deterministic": explanation_deterministic,
            },
            accion="derivar_azar",
        )
        effective_top_n = min(cfg.reason_codes.top_n, n_features)
        self.log_decision(
            regla="explain_reason_codes",
            umbral=cfg.reason_codes.top_n,
            valor={
                "top_n": cfg.reason_codes.top_n,
                "effective_top_n": effective_top_n,
                "clamped": effective_top_n < cfg.reason_codes.top_n,
                "include_protective": cfg.reason_codes.include_protective,
                "adverse_direction": cfg.reason_codes.adverse_direction,
            },
            accion="acotar_reason_codes"
            if effective_top_n < cfg.reason_codes.top_n
            else "traducir",
        )
        if ml_bundle is not None:
            self.log_decision(
                regla="explain_background",
                umbral=cfg.explainer.background_partition,
                valor={
                    "background_partition": cfg.explainer.background_partition,
                    "background_size": ml_bundle.background_size,
                    "feature_perturbation": cfg.explainer.feature_perturbation,
                },
                accion="construir_background",
            )
            self.log_decision(
                regla="explain_contribution_space",
                umbral=cfg.contribution_space,
                valor={
                    "requested_space": cfg.contribution_space,
                    "effective_space": ml_bundle.contribution_space,
                    "check_additivity": cfg.explainer.check_additivity,
                },
                accion="fijar_unidad_contribucion",
            )
        if scorecard_bundle is not None and scorecard_consistency is not None:
            self.log_decision(
                regla="explain_scorecard",
                umbral=cfg.scorecard.baseline,
                valor={
                    "baseline": cfg.scorecard.baseline,
                    "baseline_partition": cfg.scorecard.baseline_partition,
                    "points_consistency": scorecard_consistency,
                },
                accion="verificar_consistencia_puntos",
            )
        self.log_decision(
            regla="explain_comparison",
            umbral=cfg.output.top_k_comparison,
            valor={
                "top_k": cfg.output.top_k_comparison,
                "n_records": len(comparison),
                "n_both": sum(1 for record in comparison if record.agreement == "both"),
            },
            accion="comparar_drivers",
        )
        model_deterministic = (
            bool(getattr(backend_metadata, "deterministic", True))
            if backend_metadata is not None
            else True
        )
        if not explanation_deterministic or not model_deterministic:
            self.log_decision(
                regla="explain_determinism",
                umbral=True,
                valor={
                    "explanation_deterministic": explanation_deterministic,
                    "model_deterministic": model_deterministic,
                    "byte_reproducible": explanation_deterministic and model_deterministic,
                },
                accion="marcar_no_byte_reproducible",
            )


# ─────────────────────────── contrato de dependencias (CT-1) ───────────────────────────


def _requires_for(targets: str, feature_source: str) -> tuple[ArtifactKey, ...]:
    """Compone las claves ``requires`` según ``targets`` y ``feature_source`` (§2/§6).

    ``both``/``ml`` exigen las claves de ``ml`` + la fuente de features (la mitad scorecard bajo
    ``both`` es best-effort, no entra aquí); ``scorecard`` exige las del campeón + la fuente y no
    exige ``ml``.
    """
    requires: list[ArtifactKey] = [(_DATA_DOMAIN, "labels"), (_DATA_DOMAIN, "splits")]
    if targets in ("ml", "both"):
        requires += [
            (_ML_DOMAIN, "estimator"),
            (_ML_DOMAIN, "backend_metadata"),
            (_ML_DOMAIN, "pd_frame"),
        ]
        requires += _feature_source_requires(feature_source)
    if targets == "scorecard":
        requires += [
            (_MODEL_DOMAIN, "coefficients"),
            (_SCORECARD_DOMAIN, "scorecard"),
            (_BINNING_DOMAIN, "tables"),
        ]
        requires += _feature_source_requires(feature_source)
    return tuple(dict.fromkeys(requires))


def _feature_source_requires(feature_source: str) -> list[ArtifactKey]:
    """Traduce ``feature_source`` a las claves de la fuente de features WoE (§6)."""
    if feature_source == "selection_woe":
        return [
            (_SELECTION_DOMAIN, "selected_woe_frame"),
            (_SELECTION_DOMAIN, "selected_woe_columns"),
        ]
    return [(_BINNING_DOMAIN, "woe_frame")]  # binning_woe por default (data_raw se rechaza antes)


def _require_present(study: Study, requires: tuple[ArtifactKey, ...]) -> None:
    """Exige que cada artefacto ``requires`` (CT-1) esté en el ``ArtifactStore``."""
    for domain, key in requires:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso 'explain' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


def _resolve_feature_source(ml_cfg: Any) -> str:
    """Deriva la ``feature_source`` heredada de ``ml`` (``binning_woe`` si no hay ``ml``, §2)."""
    if ml_cfg is None:
        return _DEFAULT_FEATURE_SOURCE
    source = str(getattr(ml_cfg, "feature_source", _DEFAULT_FEATURE_SOURCE))
    if source == "data_raw":
        raise ExplainConfigError(
            "feature_source='data_raw' está diferido (FALTA-DATO-ML-1): use 'binning_woe' o "
            "'selection_woe'. El modo crudo exige política de imputación por variable."
        )
    return source


def _scorecard_present(study: Study) -> bool:
    """Indica si están los tres artefactos de la mitad scorecard (best-effort bajo ``both``)."""
    return (
        study.artifacts.has(_MODEL_DOMAIN, "coefficients")
        and study.artifacts.has(_SCORECARD_DOMAIN, "scorecard")
        and study.artifacts.has(_BINNING_DOMAIN, "tables")
    )


# ─────────────────────────── lectura de artefactos ───────────────────────────


def _read_frame_metadata(study: Study) -> tuple[str, str]:
    """Extrae ``target_col``/``partition_col`` de ``data.labels``/``data.splits`` (SDD-02)."""
    labels = study.artifacts.get(_DATA_DOMAIN, "labels")
    splits = study.artifacts.get(_DATA_DOMAIN, "splits")
    target_col = getattr(labels, "target_col", None)
    partition_col = getattr(splits, "partition_col", None)
    if not isinstance(target_col, str):
        raise ExplainDataError(
            "El artefacto ('data', 'labels') debe exponer target_col: str (LabeledFrame de SDD-02)."
        )
    if not isinstance(partition_col, str):
        raise ExplainDataError(
            "El artefacto ('data', 'splits') debe exponer partition_col: str (PartitionResult)."
        )
    return target_col, partition_col


def _read_feature_frame(
    study: Study, feature_source: str, pd: Any
) -> tuple[DataFrame, tuple[str, ...]]:
    """Lee el frame de features WoE y sus columnas según ``feature_source`` (copia defensiva)."""
    if feature_source == "selection_woe":
        frame = _as_dataframe(
            study.artifacts.get(_SELECTION_DOMAIN, "selected_woe_frame"),
            pd,
            "selection.selected_woe_frame",
        )
        columns = _as_string_tuple(
            study.artifacts.get(_SELECTION_DOMAIN, "selected_woe_columns"),
            "selection.selected_woe_columns",
        )
    else:  # binning_woe (data_raw se rechaza en _resolve_feature_source)
        frame = _as_dataframe(
            study.artifacts.get(_BINNING_DOMAIN, "woe_frame"), pd, "binning.woe_frame"
        )
        columns = tuple(str(column) for column in frame.columns if str(column).endswith("__woe"))
    return frame.copy(deep=True), columns


def _read_coefficients(study: Study, pd: Any) -> DataFrame:
    """Lee ``model.coefficients`` (beta/alpha por feature, SDD-08) para la mitad scorecard."""
    return _as_dataframe(
        study.artifacts.get(_MODEL_DOMAIN, "coefficients"), pd, "model.coefficients"
    ).copy(deep=True)


def _read_scorecard_table(study: Study, pd: Any) -> DataFrame:
    """Lee ``scorecard.scorecard`` (puntos por atributo/bin, SDD-09) para la consistencia."""
    return _as_dataframe(
        study.artifacts.get(_SCORECARD_DOMAIN, "scorecard"), pd, "scorecard.scorecard"
    ).copy(deep=True)


def _read_binning_tables(study: Study) -> dict[str, Any]:
    """Lee ``binning.tables`` (una tabla WoE por feature) para el nombre/bin del atributo."""
    tables = study.artifacts.get(_BINNING_DOMAIN, "tables")
    if not isinstance(tables, dict) or not tables:
        raise ExplainDataError(
            "El artefacto ('binning', 'tables') debe ser un dict no vacío de tablas WoE "
            "por feature."
        )
    return {str(key): value for key, value in tables.items()}


def _read_binning_summary(study: Study, pd: Any) -> DataFrame | None:
    """Lee ``binning.summary`` (IV) best-effort para el ranking de la comparativa (§6)."""
    if not study.artifacts.has(_BINNING_DOMAIN, "summary"):
        return None
    summary = study.artifacts.get(_BINNING_DOMAIN, "summary")
    if not isinstance(summary, pd.DataFrame):
        return None
    columns = {str(column) for column in summary.columns}
    if not ({"name", "iv"} <= columns):
        return None
    return cast(DataFrame, summary.copy(deep=True))


def _pd_hat_by_index(study: Study, cfg: ExplainConfig, pd: Any) -> dict[Any, float] | None:
    """Mapea ``índice → pd_hat`` desde ``ml.pd_frame`` para priorizar PD altas (``top_by_pd``)."""
    if not study.artifacts.has(_ML_DOMAIN, "pd_frame"):
        return None
    frame = study.artifacts.get(_ML_DOMAIN, "pd_frame")
    if not isinstance(frame, pd.DataFrame) or cfg.pd_hat_column not in frame.columns:
        return None
    return {index: float(value) for index, value in frame[cfg.pd_hat_column].items()}


# ─────────────────────────── scope local y background (SDD-14 §7 pasos 5b/5c) ───────────────────


def _resolve_scope(
    feature_frame: DataFrame,
    partition_col: str,
    cfg: ExplainConfig,
    pd_hat_by_index: dict[Any, float] | None,
    seed: int,
    np: Any,
    pd: Any,
) -> DataFrame:
    """Selecciona las observaciones a explicar según ``local_scope`` (SDD-14 §5, D-EXP-6)."""
    if cfg.local_scope.strategy == "all":
        scoped = feature_frame
    else:  # sample / partition / none
        mask = (
            feature_frame[partition_col].astype("string").eq(cfg.local_scope.partition).to_numpy()
        )
        scoped = feature_frame.loc[mask]
    if len(scoped.index) == 0:
        raise ExplainDataError(
            f"el scope local '{cfg.local_scope.strategy}' sobre la partición "
            f"'{cfg.local_scope.partition}' no tiene filas que explicar."
        )
    if cfg.local_scope.strategy == "sample":
        scoped = _sample_scope(scoped, cfg, pd_hat_by_index, seed, np)
    return scoped.copy(deep=True)


def _sample_scope(
    scoped: DataFrame,
    cfg: ExplainConfig,
    pd_hat_by_index: dict[Any, float] | None,
    seed: int,
    np: Any,
) -> DataFrame:
    """Muestrea ``sample_size`` filas del scope: por PD alta (``top_by_pd``) o seeded uniforme."""
    n_rows = len(scoped.index)
    size = min(cfg.local_scope.sample_size, n_rows)
    if cfg.local_scope.top_by_pd and pd_hat_by_index is not None:
        pd_values = np.array(
            [pd_hat_by_index.get(index, float("-inf")) for index in scoped.index], dtype="float64"
        )
        order = np.argsort(-pd_values, kind="stable")[:size]
        positions = np.sort(order)
    else:
        rng = np.random.default_rng(seed)
        positions = np.sort(rng.permutation(n_rows)[:size])
    return cast(DataFrame, scoped.iloc[positions])


def _resolve_background(
    feature_frame: DataFrame,
    feature_columns: tuple[str, ...],
    partition_col: str,
    cfg: ExplainConfig,
    seed: int,
    np: Any,
) -> DataFrame | None:
    """Muestrea el background seedeado de ``background_partition`` (None si no hay filas, §7)."""
    mask = (
        feature_frame[partition_col].astype("string").eq(cfg.explainer.background_partition)
    ).to_numpy()
    background = feature_frame.loc[mask, list(feature_columns)]
    if len(background.index) == 0:
        return None
    size = min(cfg.explainer.background_size, len(background.index))
    rng = np.random.default_rng(seed)
    positions = np.sort(rng.permutation(len(background.index))[:size])
    return cast(DataFrame, background.iloc[positions].copy(deep=True))


def _baseline_partition_frame(
    feature_frame: DataFrame, partition_col: str, cfg: ExplainConfig
) -> DataFrame:
    """Aísla la partición de baseline del scorecard (``E[WoE]`` sobre ella, SDD-14 §7 paso 6a)."""
    mask = (
        feature_frame[partition_col].astype("string").eq(cfg.scorecard.baseline_partition)
    ).to_numpy()
    frame = feature_frame.loc[mask]
    if len(frame.index) == 0:
        raise ExplainDataError(
            f"la partición de baseline del scorecard '{cfg.scorecard.baseline_partition}' no tiene "
            "filas para calcular E[WoE]."
        )
    return frame.copy(deep=True)


# ─────────────────── consistencia de puntos del scorecard (deuda B14.4(3), SDD-09 §7) ───────────


def _scorecard_points_consistency(scorecard_table: DataFrame, study: Study) -> dict[str, Any]:
    """Verifica que ``points`` de SDD-09 reconstruya ``offset/n ± factor·(beta·WoE + alpha/n)``.

    El término ``alpha/n`` (``intercept_share``) es el que la deuda B14.4(3) exige considerar: la
    consistencia **no** es ``points ≈ ∓factor·beta·WoE`` (ignorando el intercepto), sino la fórmula
    completa de SDD-09 §7. Necesita el ``scorecard.result`` (factor/offset/dirección); ausente, la
    consistencia queda **no verificable** (best-effort, no rompe).
    """
    required = {"beta", "woe", "intercept_share", "raw_points"}
    present = {str(column) for column in scorecard_table.columns}
    if not (required <= present):
        return {"verified": False, "reason": "scorecard.scorecard sin columnas de trazabilidad"}
    if not study.artifacts.has(_SCORECARD_DOMAIN, "result"):
        return {"verified": None, "reason": "scorecard.result ausente (alpha/n no verificable)"}
    result = study.artifacts.get(_SCORECARD_DOMAIN, "result")
    if not _has_scaling_metadata(result):
        return {"verified": None, "reason": "scorecard.result sin factor/offset/puntos utilizables"}
    n_variables = len(result.points_columns)
    factor = float(result.factor)
    offset = float(result.offset)
    direction = str(result.score_direction)
    offset_share = offset / n_variables
    betas = scorecard_table["beta"].tolist()
    woes = scorecard_table["woe"].tolist()
    shares = scorecard_table["intercept_share"].tolist()
    raw_points = scorecard_table["raw_points"].tolist()
    max_gap = 0.0
    for beta_value, woe_value, share_value, raw_value in zip(
        betas, woes, shares, raw_points, strict=True
    ):
        component = float(beta_value) * float(woe_value) + float(share_value)
        signed = -factor * component if direction == "higher_is_lower_risk" else factor * component
        max_gap = max(max_gap, abs(offset_share + signed - float(raw_value)))
    return {
        "verified": max_gap <= _POINTS_CONSISTENCY_ATOL,
        "max_abs_gap": max_gap,
        "alpha_over_n_considered": True,
    }


def _has_scaling_metadata(result: Any) -> bool:
    """Indica si ``scorecard.result`` expone el escalamiento (factor/offset/dirección/puntos)."""
    points_columns = getattr(result, "points_columns", ())
    return (
        len(points_columns) > 0
        and getattr(result, "factor", None) is not None
        and getattr(result, "offset", None) is not None
        and getattr(result, "score_direction", None) is not None
    )


# ─────────────────────────── ensamblado del resultado (SDD-14 §7 paso 10) ───────────────────────


def _assemble_result(
    cfg: ExplainConfig,
    *,
    ml_bundle: ExplanationBundle | None,
    scorecard_bundle: ExplanationBundle | None,
    comparison: tuple[Any, ...],
    backend_metadata: Any,
    seed: int,
) -> ExplainResult:
    """Ensambla ``ExplainResult`` desde las mitades (global concatenado, local del scope, §6)."""
    shap_global = _merge_global(ml_bundle, scorecard_bundle)
    publish_local = cfg.output.publish_local and cfg.local_scope.strategy != "none"
    local_source = ml_bundle if ml_bundle is not None else scorecard_bundle
    shap_local = local_source.shap_local if (publish_local and local_source is not None) else ()
    scorecard_contributions = (
        scorecard_bundle.scorecard_contributions if scorecard_bundle is not None else None
    )
    explanation_deterministic = bool(ml_bundle.deterministic) if ml_bundle is not None else True
    space = ml_bundle.contribution_space if ml_bundle is not None else "log_odds"
    metadata = ExplainerMetadata(
        ml_explainer_kind=ml_bundle.explainer_kind if ml_bundle is not None else None,
        scorecard_explained=scorecard_bundle is not None,
        shap_version=ml_bundle.shap_version if ml_bundle is not None else None,
        contribution_space=space,
        background_size=ml_bundle.background_size if ml_bundle is not None else None,
        seed=int(seed),
        deterministic=explanation_deterministic,
        top_n_reason_codes=cfg.reason_codes.top_n,
    )
    card = _build_card(
        cfg,
        shap_global=shap_global,
        shap_local=shap_local,
        comparison=comparison,
        space=space,
        ml_explainer_kind=ml_bundle.explainer_kind if ml_bundle is not None else None,
        scorecard_explained=scorecard_bundle is not None,
        explanation_deterministic=explanation_deterministic,
        backend_metadata=backend_metadata,
        seed=seed,
    )
    return ExplainResult(
        shap_global=shap_global,
        shap_local=shap_local,
        reason_codes=shap_local,
        scorecard_contributions=scorecard_contributions,
        comparison=comparison,
        explainer_metadata=metadata,
        card=card,
    )


def _merge_global(
    ml_bundle: ExplanationBundle | None, scorecard_bundle: ExplanationBundle | None
) -> tuple[ShapGlobalRecord, ...]:
    """Concatena la importancia global del ML (si hay) y del scorecard (si se explicó, §6)."""
    records: list[ShapGlobalRecord] = []
    if ml_bundle is not None:
        records.extend(ml_bundle.shap_global)
    if scorecard_bundle is not None:
        records.extend(scorecard_bundle.shap_global)
    return tuple(records)


def _build_card(
    cfg: ExplainConfig,
    *,
    shap_global: tuple[ShapGlobalRecord, ...],
    shap_local: tuple[Any, ...],
    comparison: tuple[Any, ...],
    space: str,
    ml_explainer_kind: str | None,
    scorecard_explained: bool,
    explanation_deterministic: bool,
    backend_metadata: Any,
    seed: int,
) -> ExplainCardSection:
    """Ensambla la tarjeta CT-2 con ``metric_sections`` (summary/dependence/comparativa, §9)."""
    model_deterministic = (
        bool(getattr(backend_metadata, "deterministic", True))
        if backend_metadata is not None
        else True
    )
    summary: dict[str, str | int | float | bool] = {
        "targets": cfg.targets,
        "ml_explainer_kind": ml_explainer_kind if ml_explainer_kind is not None else "none",
        "scorecard_explained": scorecard_explained,
        "contribution_space": space,
        "seed": int(seed),
        "deterministic": explanation_deterministic,
        "n_global_features": len(shap_global),
        "n_local_explained": len(shap_local),
    }
    global_importances = [_global_payload(record) for record in shap_global]
    metric_sections: dict[str, Any] = {
        "shap_summary": global_importances,
        "global_importances": global_importances,
        "reason_codes_example": _reason_codes_example(shap_local),
        "scorecard_vs_ml": [_comparison_payload(record) for record in comparison],
        "determinism": {
            "explanation_deterministic": explanation_deterministic,
            "model_deterministic": model_deterministic,
            "byte_reproducible": explanation_deterministic and model_deterministic,
        },
    }
    dependence = _shap_dependence_section(shap_global, cfg.output.emit_figures)
    if dependence is not None:
        metric_sections["shap_dependence"] = dependence

    assumptions: tuple[str, ...] = (
        "SHAP y scorecard no son intercambiables 1:1; la comparativa es de drivers, no de "
        "performance (SDD-14 §1).",
    )
    limitations: tuple[str, ...] = (
        "Los reason codes son top-N configurables (referencia ECOA/FCRA, no norma CMF — "
        "FALTA-DATO-EXP-1).",
    )
    if not model_deterministic:
        limitations += (
            "El modelo explicado no es byte-reproducible (GBDT multihilo); la explicación es "
            "reproducible condicional al modelo (SDD-14 §9).",
        )
    if not explanation_deterministic:
        limitations += (
            "El explainer efectivo (Kernel multihilo) no es byte-reproducible; sólo estabilidad "
            "estadística (SDD-14 §9).",
        )
    return ExplainCardSection(
        summary=summary,
        metric_sections=metric_sections,
        assumptions=assumptions,
        limitations=limitations,
    )


def _global_payload(record: ShapGlobalRecord) -> dict[str, Any]:
    """Proyecta un ``ShapGlobalRecord`` a un dict serializable (card/report)."""
    return {
        "feature": record.feature,
        "mean_abs_contribution": record.mean_abs_contribution,
        "mean_signed_contribution": record.mean_signed_contribution,
        "rank": record.rank,
        "source_model": record.source_model,
    }


def _reason_codes_example(shap_local: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Toma la primera observación con reason codes como ejemplo para el card (§9)."""
    for record in shap_local:
        if record.reason_codes:
            return [
                {
                    "rank": code.rank,
                    "feature": code.feature,
                    "direction": code.direction,
                    "contribution": code.contribution,
                    "bin_label": code.bin_label,
                }
                for code in record.reason_codes
            ]
    return []


def _comparison_payload(record: Any) -> dict[str, Any]:
    """Proyecta un ``DriverComparisonRecord`` a un dict serializable (card/report)."""
    return {
        "feature": record.feature,
        "scorecard_rank": record.scorecard_rank,
        "ml_rank": record.ml_rank,
        "in_scorecard_topk": record.in_scorecard_topk,
        "in_ml_topk": record.in_ml_topk,
        "agreement": record.agreement,
    }


def _shap_dependence_section(
    shap_global: tuple[ShapGlobalRecord, ...], emit_figures: bool
) -> dict[str, Any] | None:
    """Arma la sección ``shap_dependence`` del card; renderiza la figura si ``emit_figures`` (§9).

    Con ``emit_figures`` importa ``matplotlib`` de forma **perezosa** (vía ``Figure``/``Agg``, sin
    ``pyplot`` ni estado global) y adjunta una figura SHAP summary como PNG base64; el import pesado
    ocurre sólo aquí (nunca en import time). Sin figuras, expone únicamente los descriptores.
    """
    if not shap_global:
        return None
    top = shap_global[:_FIGURE_TOP_FEATURES]
    section: dict[str, Any] = {
        "emitted": emit_figures,
        "features": [record.feature for record in top],
    }
    if emit_figures:
        section["figure_png_base64"] = _render_summary_png(top)
    return section


def _render_summary_png(records: tuple[ShapGlobalRecord, ...]) -> str:
    """Renderiza un SHAP summary (barras horizontales) a PNG base64 con ``matplotlib`` perezoso."""
    import base64
    import io

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(6.0, 4.0))
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    ordered = list(records)[::-1]
    axes.barh(
        [record.feature for record in ordered],
        [record.mean_abs_contribution for record in ordered],
    )
    axes.set_xlabel("media |contribución|")
    axes.set_title("SHAP summary (importancia global)")
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# ─────────────────────────── publicación ───────────────────────────


def _publish_artifacts(study: Study, result: ExplainResult) -> None:
    """Publica las siete claves estables del dominio ``explain`` (copias defensivas)."""
    study.artifacts.set("explain", "shap_global", result.shap_global)
    study.artifacts.set("explain", "shap_local", result.shap_local)
    study.artifacts.set("explain", "reason_codes", result.reason_codes)
    study.artifacts.set(
        "explain",
        "scorecard_contributions",
        None
        if result.scorecard_contributions is None
        else result.scorecard_contributions.copy(deep=True),
    )
    study.artifacts.set("explain", "comparison", result.comparison)
    study.artifacts.set("explain", "result", result.model_copy(deep=True))
    study.artifacts.set("explain", "card", result.card.model_copy(deep=True))


# ─────────────────────────── validación y utilidades de import/config/datos ───────────────────────


def _validate_features(
    frame: DataFrame,
    feature_columns: tuple[str, ...],
    target_col: str,
    partition_col: str,
) -> None:
    """Valida columnas de features presentes, no vacías y sin colisión con partición/target (§6)."""
    if not feature_columns:
        raise ExplainDataError(
            "ExplainStep no encontró columnas de features WoE (terminadas en '__woe') que explicar."
        )
    for column in (partition_col, target_col):
        if column not in frame.columns:
            raise ExplainDataError(
                f"El frame de features no contiene la columna estructural '{column}'."
            )
    missing = [column for column in feature_columns if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise ExplainDataError(f"El frame de features no contiene columnas de features: {joined}.")


def _validate_estimator(estimator: Any) -> None:
    """Valida el contrato sklearn-like de ``ml.estimator`` con falla ruidosa (deuda B14.4(2))."""
    if getattr(estimator, "feature_names_in_", None) is None or not callable(
        getattr(estimator, "predict_pd", None)
    ):
        raise ExplainDataError(
            "El artefacto ('ml', 'estimator') debe exponer feature_names_in_ y predict_pd "
            f"(MLChallenger fiteado de SDD-12); tipo observado={type(estimator).__name__}."
        )


def _import_numpy() -> Any:
    """Importa ``numpy`` localmente para preservar el import liviano del paquete ``explain``."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:  # pragma: no cover - numpy es dep base de data
        raise MissingDependencyError(_EXTRA_MESSAGE) from exc


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete ``explain``."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:  # pragma: no cover - pandas es dep base de data
        raise MissingDependencyError(_EXTRA_MESSAGE) from exc


def _explain_config_from_study(study: Study, *, fallback: ExplainConfig) -> ExplainConfig:
    """Lee ``NikodymConfig.explain`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "explain", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, ExplainConfig):
        return raw_config
    return ExplainConfig.model_validate(raw_config)


def _ml_config_from_study(study: Study) -> Any:
    """Lee ``NikodymConfig.ml`` (``None`` si no hay challenger; targets='scorecard' lo permite)."""
    raw_config = getattr(study.config, "ml", None)
    if raw_config is None:
        return None
    from nikodym.ml.config import MLConfig

    if isinstance(raw_config, MLConfig):
        return raw_config
    return MLConfig.model_validate(raw_config)


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular de entrada antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise ExplainDataError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_string_tuple(value: object, artifact: str) -> tuple[str, ...]:
    """Valida un artefacto ``tuple[str, ...]`` (p.ej. ``selection.selected_woe_columns``)."""
    if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
        return tuple(cast("list[str]", list(value)))
    raise ExplainDataError(
        f"El artefacto '{artifact}' debe ser tuple[str, ...]; "
        f"tipo observado={type(value).__name__}."
    )
