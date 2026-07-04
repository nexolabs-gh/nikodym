"""Motor de explicabilidad unificada ``explain`` (SDD-14 §4/§7).

:class:`UnifiedExplainer` orquesta las **dos mitades** del contrato de ``explain`` sobre el mismo
espacio de contribuciones:

- :meth:`UnifiedExplainer.explain_ml` explica el **challenger ML** (``MLChallenger``) vía SHAP:
  resuelve el explainer por ``backend`` (D-EXP-1), arma —si hace falta— un *background* seedeado,
  calcula ``φ`` sobre el scope local en la unidad efectiva, verifica la **aditividad**
  (``φ₀ + Σφ ≈ margen``, gateada por backend/espacio, nitpick A15(1)), arma la importancia global
  ``Φ_j = mean|φ_j|`` con dirección y traduce a reason codes con ``build_reason_codes``.
- :meth:`UnifiedExplainer.explain_scorecard` explica el **scorecard logístico** de forma **exacta y
  analítica** (``β·(WoE - baseline)``, sin ``shap``), publica las contribuciones por bin con los
  ``points`` de referencia (SDD-09, salvo ``Factor``/``Offset``) y reusa el **mismo**
  ``build_reason_codes``.
- :meth:`UnifiedExplainer.compare_drivers` contrasta los drivers del campeón (IV de ``summary`` si
  está presente; si no, ``|β·baseline|`` — nitpick A15(2)) con los del challenger (``Φ_j``) y
  reporta el solape/acuerdo de los top-K.

**Reúso sin mutación (SDD-14 §6).** ``explain`` consume ``MLChallenger`` por su API sklearn-like
(``predict_pd``/``feature_names_in_``/``estimator_``); **no** reentrena ni muta el estimador ni los
frames (copias defensivas). Explica **siempre la clase positiva** (PD, clase 1; D-EXP-5).

**No reimplementa Shapley (SDD-14 §7).** La única atribución "a mano" es la lineal exacta del
scorecard (ya en :mod:`nikodym.explain.explainers`); el ML solo llama a ``shap.*`` vía
:func:`~nikodym.explain.explainers.resolve_explainer`. ``shap``/``pandas``/``numpy`` se importan de
forma **perezosa** dentro de los métodos (núcleo liviano, SDD-14 §9).

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias, cast

from nikodym.core.base import BaseNikodymEstimator
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import MissingDependencyError
from nikodym.explain.config import (
    ContributionSpace,
    ExplainConfig,
    ExplainTargets,
    MLExplainerChoice,
    ScorecardBaseline,
    TreePerturbation,
)
from nikodym.explain.exceptions import ExplainDataError, ExplainExplainerError
from nikodym.explain.explainers import resolve_explainer, resolve_explainer_kind
from nikodym.explain.reason_codes import build_reason_codes
from nikodym.explain.results import (
    Agreement,
    DriverComparisonRecord,
    LocalExplanationRecord,
    ShapGlobalRecord,
    SourceModel,
)

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink
    from nikodym.ml.estimator import MLChallenger

    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    DataFrame: TypeAlias = pd.DataFrame
else:
    NDArrayFloat: TypeAlias = Any
    DataFrame: TypeAlias = Any
    AuditSink: TypeAlias = Any
    MLChallenger: TypeAlias = Any

__all__ = ["ExplanationBundle", "UnifiedExplainer"]

# Backends arbóreos (TreeExplainer exacto sin muestreo, D-EXP-1); el resto usa Linear/Kernel.
_TREE_BACKENDS: frozenset[str] = frozenset({"xgboost", "lightgbm", "catboost", "random_forest"})
# Tolerancia absoluta del additivity check en la unidad de contribución (SDD-14 §6, §8).
_ADDITIVITY_ATOL: float = 1e-5
# Etiquetas de fila agregada en las tablas WoE de OptBinning que NO son un bin (se saltan).
_AGGREGATE_BIN_LABELS: frozenset[str] = frozenset({"", "Totals"})
# Partición por defecto de las explicaciones locales en la API programática (el step la fija).
_LOCAL_PARTITION: str = "local"
# Columnas canónicas del tidy de contribuciones analíticas del scorecard (SDD-14 §6).
_SCORECARD_CONTRIB_COLUMNS: tuple[str, ...] = (
    "feature",
    "woe_column",
    "bin_label",
    "woe",
    "beta",
    "baseline",
    "contribution",
    "points",
    "direction",
)


@dataclass(frozen=True)
class ExplanationBundle:
    """Paquete intermedio de una mitad explicada (ML o scorecard) que consume el motor (SDD-14 §7).

    No es un DTO publicado: es el resultado de ``explain_ml`` / ``explain_scorecard`` que alimenta a
    ``compare_drivers`` y al ensamblado de ``ExplainResult`` (que arma el step, B14.5). Reúsa los
    DTOs *frozen* de :mod:`nikodym.explain.results`; ``driver_ranking`` es el orden de features (por
    IV/``Φ_j`` o ``|β·baseline|``) que habilita la comparativa.
    """

    source_model: SourceModel
    shap_global: tuple[ShapGlobalRecord, ...] = ()
    shap_local: tuple[LocalExplanationRecord, ...] = ()
    reason_codes: tuple[LocalExplanationRecord, ...] = ()
    scorecard_contributions: DataFrame | None = None
    driver_ranking: tuple[str, ...] = ()
    explainer_kind: str | None = None
    shap_version: str | None = None
    contribution_space: ContributionSpace = "log_odds"
    base_value: float = 0.0
    background_size: int | None = None
    deterministic: bool = True


class UnifiedExplainer(BaseNikodymEstimator):
    """Orquestador de la explicabilidad unificada scorecard + SHAP (SDD-14 §4).

    Se construye con :meth:`from_config` desde :class:`~nikodym.explain.config.ExplainConfig`; sus
    hiperparámetros son planos (semántica sklearn). Tras ``explain_ml``/``explain_scorecard``
    publica los atributos fiteados con sufijo ``_`` (``explainer_kind_``, ``base_value_``,
    ``shap_version_``, ``background_size_``, ``feature_names_in_``, ``contribution_space_``,
    ``seed_``, ``deterministic_``).
    """

    config_cls: ClassVar[type[ExplainConfig]] = ExplainConfig

    def __init__(
        self,
        *,
        targets: ExplainTargets = "both",
        ml_explainer: MLExplainerChoice = "auto",
        feature_perturbation: TreePerturbation = "tree_path_dependent",
        background_size: int = 100,
        check_additivity: bool = True,
        nsamples: int | Literal["auto"] = "auto",
        contribution_space: ContributionSpace = "log_odds",
        top_n: int = 5,
        include_protective: bool = False,
        min_abs_contribution: float = 0.0,
        adverse_direction: Literal["increases_pd"] = "increases_pd",
        scorecard_baseline: ScorecardBaseline = "population_mean",
        top_k_comparison: int = 15,
        deterministic: bool = True,
        n_threads: int = 1,
    ) -> None:
        """Asigna los hiperparámetros planos sin cargar dependencias pesadas (semántica sklearn)."""
        self.targets = targets
        self.ml_explainer = ml_explainer
        self.feature_perturbation = feature_perturbation
        self.background_size = background_size
        self.check_additivity = check_additivity
        self.nsamples = nsamples
        self.contribution_space = contribution_space
        self.top_n = top_n
        self.include_protective = include_protective
        self.min_abs_contribution = min_abs_contribution
        self.adverse_direction = adverse_direction
        self.scorecard_baseline = scorecard_baseline
        self.top_k_comparison = top_k_comparison
        self.deterministic = deterministic
        self.n_threads = n_threads

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> UnifiedExplainer:
        """Construye el explicador desde ``ExplainConfig`` aplanando sus sub-configs (SDD-14 §4)."""
        validated = cfg if isinstance(cfg, ExplainConfig) else ExplainConfig.model_validate(cfg)
        return cls(
            targets=validated.targets,
            ml_explainer=validated.explainer.ml_explainer,
            feature_perturbation=validated.explainer.feature_perturbation,
            background_size=validated.explainer.background_size,
            check_additivity=validated.explainer.check_additivity,
            nsamples=validated.explainer.nsamples,
            contribution_space=validated.contribution_space,
            top_n=validated.reason_codes.top_n,
            include_protective=validated.reason_codes.include_protective,
            min_abs_contribution=validated.reason_codes.min_abs_contribution,
            adverse_direction=validated.reason_codes.adverse_direction,
            scorecard_baseline=validated.scorecard.baseline,
            top_k_comparison=validated.output.top_k_comparison,
            deterministic=validated.deterministic,
            n_threads=validated.n_threads,
        )

    def explain_ml(
        self,
        estimator: MLChallenger,
        X: DataFrame,  # noqa: N803
        *,
        background: DataFrame | None = None,
        seed: int,
        audit: AuditSink | None = None,
        partition: str = _LOCAL_PARTITION,
    ) -> ExplanationBundle:
        """Explica el challenger ML vía SHAP sobre el scope ``X`` (SDD-14 §7, pasos 5a-5f).

        Resuelve el explainer por ``estimator.backend`` (D-EXP-1), arma un *background* seedeado
        si el explainer lo necesita, calcula ``φ`` en la unidad ``contribution_space`` efectiva,
        verifica la aditividad (gateada por backend/espacio) y arma la importancia global + reason
        codes. **No** reentrena ni muta ``estimator``/``X`` (copias defensivas).
        """
        np = _import_numpy()
        pd = _import_pandas()
        self._audit_sink = audit
        feature_names = _estimator_features(estimator)
        frame = _align_features(X, feature_names, pd, context="explain_ml")
        backend = getattr(estimator, "backend", None)
        supports_tree = backend in _TREE_BACKENDS
        is_linear = _is_linear_backend(estimator, backend)
        kind = resolve_explainer_kind(
            backend=backend,
            model_kind="ml",
            forced=self.ml_explainer,
            supports_tree=supports_tree,
            is_linear_model=is_linear,
        )
        needs_background = _needs_background(kind, self.feature_perturbation)
        resolved_background = background
        if needs_background and resolved_background is None:
            resolved_background = self._seeded_background(frame, seed, np)
        explainer = resolve_explainer(
            backend=backend,
            model_kind="ml",
            forced=self.ml_explainer,
            supports_tree=supports_tree,
            is_linear_model=is_linear,
            model=getattr(estimator, "estimator_", None),
            predict_fn=estimator.predict_pd,
            background=resolved_background,
            feature_perturbation=self.feature_perturbation,
            contribution_space=self.contribution_space,
            nsamples=self.nsamples,
        )
        phi = explainer.contributions(frame)
        phi0 = explainer.base_value()
        space = cast(
            ContributionSpace, getattr(explainer, "contribution_space_", self.contribution_space)
        )
        pd_hat = _predict_pd(estimator, frame, np)
        prediction = _prediction_vector(pd_hat, space, np)
        self._check_additivity(explainer, phi0, phi, prediction, np)
        background_size = (
            len(resolved_background)
            if needs_background and resolved_background is not None
            else None
        )
        deterministic = self.deterministic and (explainer.is_exact or self.n_threads == 1)
        bundle = self._assemble_bundle(
            source_model="ml",
            feature_names=feature_names,
            phi=phi,
            phi0=phi0,
            prediction=prediction,
            pd_hat=pd_hat,
            row_index=frame.index,
            partition=partition,
            space=space,
            explainer_kind=explainer.kind,
            shap_version=explainer.shap_version(),
            background_size=background_size,
            deterministic=deterministic,
            scorecard_contributions=None,
            driver_ranking=None,
            np=np,
        )
        self._set_fitted_state(
            explainer_kind=explainer.kind,
            base_value=phi0,
            shap_version=explainer.shap_version(),
            background_size=background_size,
            feature_names=feature_names,
            contribution_space=space,
            seed=int(seed),
            deterministic=deterministic,
        )
        _emit_audit_decision(
            audit,
            regla="explain_explainer",
            umbral={"forced": self.ml_explainer, "n_threads": self.n_threads},
            valor={
                "kind": explainer.kind,
                "shap_version": explainer.shap_version(),
                "contribution_space": space,
                "background_size": background_size,
                "seed": int(seed),
                "deterministic": deterministic,
            },
            accion="explain_ml",
        )
        return bundle

    def explain_scorecard(
        self,
        coefficients: DataFrame,
        woe_tables: object,
        X_woe: DataFrame,  # noqa: N803
        *,
        audit: AuditSink | None = None,
        binning_summary: DataFrame | None = None,
        partition: str = _LOCAL_PARTITION,
    ) -> ExplanationBundle:
        """Explica el scorecard logístico de forma exacta y analítica (SDD-14 §7, paso 6).

        Descompone ``η_i = intercepto + Σ_j β_j·WoE_ij`` en ``φ_j = β_j·(WoE_ij - baseline_j)`` (sin
        ``shap``), publica las contribuciones por bin con los ``points`` de referencia de SDD-09 y
        reusa ``build_reason_codes``. ``binning_summary`` (si se pasa) aporta el IV para el ranking
        de la comparativa; si no, se usa ``|β·baseline|`` (nitpick A15(2)).
        """
        np = _import_numpy()
        pd = _import_pandas()
        self._audit_sink = audit
        betas, woe_columns, feature_by_woecol, intercept = _parse_coefficients(coefficients)
        frame = _align_features(X_woe, woe_columns, pd, context="explain_scorecard")
        baseline = self._scorecard_baseline(frame, woe_columns, np)
        explainer = resolve_explainer(
            backend=None,
            model_kind="scorecard",
            forced=None,
            supports_tree=False,
            coefficients=betas,
            intercept=intercept,
            baseline=baseline,
            feature_names=woe_columns,
            contribution_space="log_odds",
        )
        phi = explainer.contributions(frame)
        phi0 = explainer.base_value()
        prediction = phi0 + phi.sum(axis=1)
        pd_hat = _sigmoid(prediction, np)
        contributions_frame = _scorecard_contributions(
            woe_columns, feature_by_woecol, betas, baseline, woe_tables, pd
        )
        driver_ranking = self._scorecard_driver_ranking(
            woe_columns, feature_by_woecol, betas, baseline, binning_summary
        )
        bundle = self._assemble_bundle(
            source_model="scorecard",
            feature_names=woe_columns,
            phi=phi,
            phi0=phi0,
            prediction=prediction,
            pd_hat=pd_hat,
            row_index=frame.index,
            partition=partition,
            space="log_odds",
            explainer_kind="analytic_linear",
            shap_version=None,
            background_size=None,
            deterministic=True,
            scorecard_contributions=contributions_frame,
            driver_ranking=driver_ranking,
            np=np,
        )
        self._set_fitted_state(
            explainer_kind="analytic_linear",
            base_value=phi0,
            shap_version=None,
            background_size=None,
            feature_names=woe_columns,
            contribution_space="log_odds",
            seed=0,
            deterministic=True,
        )
        _emit_audit_decision(
            audit,
            regla="explain_scorecard",
            umbral={"baseline": self.scorecard_baseline},
            valor={
                "n_features": len(woe_columns),
                "intercept": intercept,
                "used_iv": binning_summary is not None,
            },
            accion="explain_scorecard",
        )
        return bundle

    def compare_drivers(
        self,
        scorecard_bundle: ExplanationBundle | None,
        ml_bundle: ExplanationBundle,
        *,
        top_k: int,
    ) -> tuple[DriverComparisonRecord, ...]:
        """Contrasta los drivers del campeón y del challenger por su ranking top-K (SDD-14 §7).

        Rankea el challenger por ``Φ_j`` y el campeón por el ``driver_ranking`` que fijó
        ``explain_scorecard`` (IV o ``|β·baseline|``). Con ``scorecard_bundle=None`` y
        ``targets='both'`` audita la degradación (``explain_scorecard_skipped``); la comparativa
        queda solo con drivers del ML.
        """
        if top_k < 1:
            raise ExplainDataError(f"top_k debe ser >= 1 para la comparativa; top_k={top_k}.")
        ml_ranking = ml_bundle.driver_ranking
        ml_rank = {feature: index + 1 for index, feature in enumerate(ml_ranking)}
        ml_topk = set(ml_ranking[:top_k])
        if scorecard_bundle is None:
            if self.targets == "both":
                _emit_audit_decision(
                    getattr(self, "_audit_sink", None),
                    regla="explain_scorecard_skipped",
                    umbral={"targets": self.targets},
                    valor={"reason": "scorecard_bundle_ausente"},
                    accion="degrade_to_ml",
                )
            sc_rank: dict[str, int] = {}
            sc_topk: set[str] = set()
        else:
            sc_ranking = scorecard_bundle.driver_ranking
            sc_rank = {feature: index + 1 for index, feature in enumerate(sc_ranking)}
            sc_topk = set(sc_ranking[:top_k])
        union = sc_topk | ml_topk
        ordered = sorted(
            union,
            key=lambda feature: (
                min(sc_rank.get(feature, math.inf), ml_rank.get(feature, math.inf)),
                feature,
            ),
        )
        records = [
            DriverComparisonRecord(
                feature=feature,
                scorecard_rank=sc_rank.get(feature),
                ml_rank=ml_rank.get(feature),
                in_scorecard_topk=feature in sc_topk,
                in_ml_topk=feature in ml_topk,
                agreement=_agreement(feature in sc_topk, feature in ml_topk),
            )
            for feature in ordered
        ]
        return tuple(records)

    # ── helpers de instancia ──────────────────────────────────────────────────────────────────
    def _seeded_background(self, frame: DataFrame, seed: int, np: Any) -> DataFrame:
        """Muestrea un *background* seedeado de ``frame`` (``background_size``), orden estable."""
        n_rows = len(frame)
        size = min(self.background_size, n_rows)
        rng = np.random.default_rng(seed)
        positions = np.sort(rng.permutation(n_rows)[:size])
        return cast(DataFrame, frame.iloc[positions].copy(deep=True))

    def _check_additivity(
        self, explainer: Any, phi0: float, phi: Any, prediction: Any, np: Any
    ) -> None:
        """Verifica ``φ₀ + Σφ ≈ margen`` si el explainer es exacto (SDD-14 §6/§8, A15(1)).

        El gate solo aplica a explainers con aditividad exacta (Tree/Linear/analítico); el fallback
        Kernel es muestral y no se asevera. Una brecha mayor a la tolerancia levanta
        :class:`~nikodym.explain.exceptions.ExplainExplainerError` (no se silencia ni se recorta).
        """
        should_check = self.check_additivity and bool(
            getattr(explainer, "exact_additivity_", False)
        )
        if not should_check:
            return
        reconstructed = phi0 + phi.sum(axis=1)
        gap = float(np.max(np.abs(reconstructed - prediction)))
        if gap > _ADDITIVITY_ATOL:
            raise ExplainExplainerError(
                "aditividad rota: φ₀ + Σφ se aparta del margen en "
                f"{gap:.3e} (tolerancia {_ADDITIVITY_ATOL:.0e}); no se silencia ni se recorta."
            )

    def _scorecard_baseline(
        self, frame: DataFrame, woe_columns: tuple[str, ...], np: Any
    ) -> tuple[float, ...]:
        """Resuelve el baseline: ``E[WoE_j]`` (population_mean) o ``0`` (neutral_zero)."""
        if self.scorecard_baseline == "neutral_zero":
            return tuple(0.0 for _ in woe_columns)
        matrix = np.asarray(frame.loc[:, list(woe_columns)].to_numpy(), dtype="float64")
        return tuple(float(value) for value in matrix.mean(axis=0))

    def _scorecard_driver_ranking(
        self,
        woe_columns: tuple[str, ...],
        feature_by_woecol: dict[str, str],
        betas: tuple[float, ...],
        baseline: tuple[float, ...],
        binning_summary: DataFrame | None,
    ) -> tuple[str, ...]:
        """Ordena las features del campeón por IV (``summary``) o ``|β·baseline|`` (A15(2))."""
        if binning_summary is not None:
            iv_by_feature = _iv_by_feature(binning_summary)
            keyed = [
                (woe_col, iv_by_feature.get(feature_by_woecol[woe_col], 0.0))
                for woe_col in woe_columns
            ]
        else:
            keyed = [
                (woe_col, abs(beta * base))
                for woe_col, beta, base in zip(woe_columns, betas, baseline, strict=True)
            ]
        keyed.sort(key=lambda item: (-item[1], item[0]))
        return tuple(woe_col for woe_col, _ in keyed)

    def _assemble_bundle(
        self,
        *,
        source_model: SourceModel,
        feature_names: tuple[str, ...],
        phi: Any,
        phi0: float,
        prediction: Any,
        pd_hat: Any,
        row_index: Any,
        partition: str,
        space: ContributionSpace,
        explainer_kind: str | None,
        shap_version: str | None,
        background_size: int | None,
        deterministic: bool,
        scorecard_contributions: DataFrame | None,
        driver_ranking: tuple[str, ...] | None,
        np: Any,
    ) -> ExplanationBundle:
        """Arma el :class:`ExplanationBundle` (global + local + reason codes + ranking)."""
        shap_global = _global_records(phi, feature_names, source_model, np)
        reason_codes_per_obs = build_reason_codes(
            phi,
            feature_names,
            top_n=self.top_n,
            adverse_direction=self.adverse_direction,
            include_protective=self.include_protective,
            min_abs_contribution=self.min_abs_contribution,
        )
        local_records = _local_records(
            row_index, prediction, pd_hat, phi0, partition, reason_codes_per_obs
        )
        ranking = (
            driver_ranking
            if driver_ranking is not None
            else tuple(record.feature for record in shap_global)
        )
        return ExplanationBundle(
            source_model=source_model,
            shap_global=shap_global,
            shap_local=local_records,
            reason_codes=local_records,
            scorecard_contributions=scorecard_contributions,
            driver_ranking=ranking,
            explainer_kind=explainer_kind,
            shap_version=shap_version,
            contribution_space=space,
            base_value=phi0,
            background_size=background_size,
            deterministic=deterministic,
        )

    def _set_fitted_state(
        self,
        *,
        explainer_kind: str | None,
        base_value: float,
        shap_version: str | None,
        background_size: int | None,
        feature_names: tuple[str, ...],
        contribution_space: ContributionSpace,
        seed: int,
        deterministic: bool,
    ) -> None:
        """Publica los atributos fiteados con sufijo ``_`` (SDD-14 §4)."""
        self.explainer_kind_ = explainer_kind
        self.base_value_ = base_value
        self.shap_version_ = shap_version
        self.background_size_ = background_size
        self.feature_names_in_ = feature_names
        self.contribution_space_ = contribution_space
        self.seed_ = seed
        self.deterministic_ = deterministic


# ── imports perezosos (núcleo liviano, SDD-14 §9) ─────────────────────────────────────────────────
def _import_numpy() -> Any:
    """Importa ``numpy`` localmente y traduce su ausencia a un mensaje accionable."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:  # pragma: no cover - numpy es dep base de data
        raise MissingDependencyError("instale nikodym[ml]") from exc


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente y traduce su ausencia a un mensaje accionable."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:  # pragma: no cover - pandas es dep base de data
        raise MissingDependencyError("instale nikodym[ml]") from exc


# ── helpers puros (features, predicción, contribuciones) ──────────────────────────────────────────
def _estimator_features(estimator: Any) -> tuple[str, ...]:
    """Lee ``estimator.feature_names_in_``; falla si el estimador no está fiteado."""
    names = getattr(estimator, "feature_names_in_", None)
    if names is None:
        raise ExplainDataError(
            "el estimador no expone feature_names_in_; explique un MLChallenger ya fiteado."
        )
    return tuple(str(name) for name in names)


def _align_features(
    X: Any,  # noqa: N803
    feature_names: tuple[str, ...],
    pd: Any,
    *,
    context: str,
) -> Any:
    """Alinea ``X`` a ``feature_names`` (copia defensiva); desalineación ⇒ ``ExplainDataError``."""
    if not isinstance(X, pd.DataFrame):
        raise ExplainDataError(
            f"{context} requiere pandas.DataFrame; tipo observado={type(X).__name__}."
        )
    if len(X.index) == 0:
        raise ExplainDataError(f"{context} recibió un DataFrame vacío.")
    missing = [name for name in feature_names if name not in X.columns]
    if missing:
        faltantes = ", ".join(f"'{name}'" for name in missing)
        raise ExplainDataError(
            f"{context}: las features del scope no coinciden con feature_names_in_; "
            f"faltan {faltantes}."
        )
    return X.loc[:, list(feature_names)].copy(deep=True)


def _is_linear_backend(estimator: Any, backend: str | None) -> bool:
    """Detecta un SVM de kernel lineal (LinearExplainer aplica); el resto no es lineal exacto."""
    if backend != "svm":
        return False
    hyperparameters = getattr(estimator, "hyperparameters", None)
    return getattr(hyperparameters, "kernel", None) == "linear"


def _needs_background(kind: str, feature_perturbation: TreePerturbation) -> bool:
    """Determina si el explainer necesita un *background* sin importar ``shap`` (SDD-14 §7, 5b)."""
    if kind in ("kernel", "linear"):
        return True
    return kind == "tree" and feature_perturbation == "interventional"


def _predict_pd(estimator: Any, frame: Any, np: Any) -> Any:
    """Obtiene la PD (clase positiva) del challenger sin mutarlo; valida forma y finitud."""
    pd_hat = np.asarray(estimator.predict_pd(frame), dtype="float64")
    if pd_hat.ndim != 1 or pd_hat.shape[0] != len(frame):
        raise ExplainDataError(
            f"predict_pd debe devolver un vector (n,); forma observada={pd_hat.shape}."
        )
    return pd_hat


def _prediction_vector(pd_hat: Any, space: ContributionSpace, np: Any) -> Any:
    """Traduce la PD a la unidad de contribución: margen log-odds o probabilidad (D-EXP-4)."""
    if not bool(np.isfinite(pd_hat).all()):
        raise ExplainDataError("las PD del estimador no son finitas (NaN/inf).")
    if bool(((pd_hat < 0.0) | (pd_hat > 1.0)).any()):
        raise ExplainDataError("las PD del estimador están fuera de [0, 1].")
    if space == "log_odds":
        if bool(((pd_hat <= 0.0) | (pd_hat >= 1.0)).any()):
            raise ExplainDataError(
                "PD en {0, 1} impiden el margen log-odds; use contribution_space='probability'."
            )
        return np.log(pd_hat / (1.0 - pd_hat))
    return np.array(pd_hat, dtype="float64", copy=True)


def _sigmoid(margin: Any, np: Any) -> Any:
    """Sigmoide numéricamente estable (sin overflow bajo ``filterwarnings=error``)."""
    out = np.empty_like(margin)
    positive = margin >= 0.0
    out[positive] = 1.0 / (1.0 + np.exp(-margin[positive]))
    exp_negative = np.exp(margin[~positive])
    out[~positive] = exp_negative / (1.0 + exp_negative)
    return out


def _global_records(
    phi: Any, feature_names: tuple[str, ...], source_model: SourceModel, np: Any
) -> tuple[ShapGlobalRecord, ...]:
    """Construye la importancia global ``Φ_j = mean|φ_j|`` con dirección y orden estable."""
    mean_abs = np.abs(phi).mean(axis=0)
    mean_signed = phi.mean(axis=0)
    order = sorted(
        range(len(feature_names)),
        key=lambda index: (-float(mean_abs[index]), feature_names[index]),
    )
    return tuple(
        ShapGlobalRecord(
            feature=feature_names[index],
            mean_abs_contribution=float(mean_abs[index]),
            mean_signed_contribution=float(mean_signed[index]),
            rank=rank,
            source_model=source_model,
        )
        for rank, index in enumerate(order, start=1)
    )


def _local_records(
    row_index: Any,
    prediction: Any,
    pd_hat: Any,
    phi0: float,
    partition: str,
    reason_codes_per_obs: tuple[tuple[Any, ...], ...],
) -> tuple[LocalExplanationRecord, ...]:
    """Arma un :class:`LocalExplanationRecord` por observación con sus reason codes (SDD-14 §6)."""
    records = []
    for position, reason_codes in enumerate(reason_codes_per_obs):
        records.append(
            LocalExplanationRecord(
                row_key=str(row_index[position]),
                partition=partition,
                base_value=float(phi0),
                prediction=float(prediction[position]),
                pd_hat=float(pd_hat[position]),
                reason_codes=reason_codes,
            )
        )
    return tuple(records)


def _agreement(in_scorecard_topk: bool, in_ml_topk: bool) -> Agreement:
    """Deriva el acuerdo de un driver según su pertenencia a cada top-K (SDD-14 §6)."""
    if in_scorecard_topk and in_ml_topk:
        return "both"
    if in_scorecard_topk:
        return "scorecard_only"
    return "ml_only"


# ── helpers del scorecard analítico ───────────────────────────────────────────────────────────────
def _parse_coefficients(
    coefficients: Any,
) -> tuple[tuple[float, ...], tuple[str, ...], dict[str, str], float]:
    """Extrae ``β_j``, las columnas WoE, el mapa WoE→feature y el intercepto (SDD-08)."""
    required = {"feature", "woe_column", "beta"}
    present = {str(column) for column in coefficients.columns}
    missing = required - present
    if missing:
        raise ExplainDataError(
            f"coefficients requiere las columnas {sorted(required)}; faltan {sorted(missing)}."
        )
    betas: list[float] = []
    woe_columns: list[str] = []
    feature_by_woecol: dict[str, str] = {}
    intercept = 0.0
    for _, row in coefficients.iterrows():
        feature = str(row["feature"])
        beta = float(row["beta"])
        if feature == "intercept":
            intercept = beta
            continue
        woe_column = str(row["woe_column"])
        betas.append(beta)
        woe_columns.append(woe_column)
        feature_by_woecol[woe_column] = feature
    if not woe_columns:
        raise ExplainDataError("coefficients no contiene features (solo intercepto).")
    return tuple(betas), tuple(woe_columns), feature_by_woecol, intercept


def _scorecard_contributions(
    woe_columns: tuple[str, ...],
    feature_by_woecol: dict[str, str],
    betas: tuple[float, ...],
    baseline: tuple[float, ...],
    woe_tables: object,
    pd: Any,
) -> Any:
    """Tabula ``β·(WoE - baseline)`` por bin con los ``points`` de referencia (SDD-14 §6)."""
    rows: list[dict[str, Any]] = []
    for woe_column, beta, base in zip(woe_columns, betas, baseline, strict=True):
        feature = feature_by_woecol[woe_column]
        table = woe_tables.get(feature) if hasattr(woe_tables, "get") else None
        if table is None:
            continue
        for bin_label, woe in _iter_bins(table, pd):
            contribution = beta * (woe - base)
            rows.append(
                {
                    "feature": feature,
                    "woe_column": woe_column,
                    "bin_label": bin_label,
                    "woe": woe,
                    "beta": beta,
                    "baseline": base,
                    "contribution": _normalize_zero(contribution),
                    "points": _normalize_zero(beta * woe),
                    "direction": _bin_direction(contribution),
                }
            )
    return pd.DataFrame(rows, columns=list(_SCORECARD_CONTRIB_COLUMNS))


def _iter_bins(table: Any, pd: Any) -> list[tuple[str, float]]:
    """Itera ``(bin_label, woe)`` de una tabla WoE, saltando filas agregadas o sin WoE (SDD-06)."""
    columns = {str(column) for column in table.columns}
    if not ({"Bin", "WoE"} <= columns):
        raise ExplainDataError("cada tabla WoE debe exponer columnas 'Bin' y 'WoE'.")
    pairs: list[tuple[str, float]] = []
    for _, row in table.iterrows():
        bin_label = str(row["Bin"])
        woe_value = row["WoE"]
        if bin_label in _AGGREGATE_BIN_LABELS or bool(pd.isna(woe_value)):
            continue
        pairs.append((bin_label, float(woe_value)))
    return pairs


def _iv_by_feature(binning_summary: Any) -> dict[str, float]:
    """Mapea ``feature → IV`` desde ``summary`` para el ranking de la comparativa (SDD-14 §6)."""
    columns = {str(column) for column in binning_summary.columns}
    if not ({"name", "iv"} <= columns):
        raise ExplainDataError("binning_summary requiere las columnas 'name' e 'iv'.")
    return {str(row["name"]): float(row["iv"]) for _, row in binning_summary.iterrows()}


def _bin_direction(contribution: float) -> str:
    """Dirección del bin: sube, baja o es neutra respecto de la PD (traza, no un ``ReasonCode``)."""
    if contribution > 0.0:
        return "increases_pd"
    if contribution < 0.0:
        return "decreases_pd"
    return "neutral"


def _normalize_zero(value: float) -> float:
    """Publica ``-0.0`` como ``0.0`` (normalización numérica, SDD-14 §9)."""
    return 0.0 if value == 0.0 else value


# ── auditoría (patrón de StressTestEngine: helper de módulo con el sink explícito) ────────────────
def _emit_audit_decision(
    audit: AuditSink | None,
    *,
    regla: str,
    umbral: Mapping[str, Any],
    valor: Mapping[str, Any],
    accion: str,
) -> None:
    """Registra un evento ``"decision"`` de :mod:`nikodym.core.audit` si hay un sink (SDD-14 §9)."""
    if audit is None:
        return
    from nikodym.core.audit import AuditEvent

    audit.emit(
        AuditEvent(
            kind="decision",
            step="explain",
            payload={
                "regla": regla,
                "umbral": dict(umbral),
                "valor": dict(valor),
                "accion": accion,
            },
            ts=datetime.now(tz=UTC),
        )
    )
