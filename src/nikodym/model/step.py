"""Paso orquestable de la capa ``model`` (SDD-08 §4/§6/§7; CT-1).

``ModelStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``model``: lee
artefactos publicados por ``data``, ``binning`` y ``selection``, ajusta ``LogisticPDModel`` sólo
sobre Desarrollo, predice PD cruda en particiones modelables y publica coeficientes, trazas,
estadísticas y model card bajo el dominio ``model``.

El módulo evita importar ``pandas``, ``sklearn``, ``statsmodels``, ``scipy`` y
``nikodym.model.estimator`` en import time. ``nikodym.model`` lo importa para ejecutar
``@register("standard", domain="model")`` sin contaminar el núcleo liviano; las dependencias
tabulares y de scoring se cargan dentro de ``execute``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping
from importlib import metadata
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.model.config import ModelConfig
from nikodym.model.exceptions import ModelFitError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.study import Study
    from nikodym.data.partition import PartitionResult
    from nikodym.data.target import LabeledFrame
    from nikodym.model.estimator import LogisticPDModel
    from nikodym.model.results import (
        ModelCardSection,
        ModelFitStatistics,
        ModelResult,
        StepwiseDecision,
    )

    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series[Any]
else:
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any
    LabeledFrame: TypeAlias = Any
    LogisticPDModel: TypeAlias = Any
    ModelCardSection: TypeAlias = Any
    ModelFitStatistics: TypeAlias = Any
    ModelResult: TypeAlias = Any
    PartitionResult: TypeAlias = Any
    StepwiseDecision: TypeAlias = Any

__all__ = ["MODEL_ARTIFACTS", "ModelStep"]

MODEL_ARTIFACTS: Final[tuple[str, ...]] = (
    "estimator",
    "final_features",
    "final_woe_columns",
    "coefficients",
    "stepwise_trace",
    "fit_statistics",
    "raw_pd_frame",
    "result",
    "model_card",
)
_MODEL_PARTITIONS: Final[frozenset[str]] = frozenset({"desarrollo", "holdout", "oot"})
_SCORING_EXTRA_MESSAGE: Final = (
    "ModelStep requiere LogisticPDModel y el extra de scoring; instale nikodym[scoring]."
)
_DEPENDENCY_DISTRIBUTIONS: Final[tuple[str, ...]] = (
    "statsmodels",
    "scikit-learn",
    "scipy",
    "pandas",
    "numpy",
)


@register("standard", domain="model")
class ModelStep(AuditableMixin):
    """Orquesta ajuste logístico PD y publica artefactos ``domain='model'``."""

    name: str = "model"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "labels"),
        ("data", "splits"),
        ("binning", "summary"),
        ("selection", "selected_features"),
        ("selection", "selected_woe_columns"),
        ("selection", "selected_woe_frame"),
    )
    provides: tuple[ArtifactKey, ...] = tuple(("model", key) for key in MODEL_ARTIFACTS)

    def __init__(self, config: ModelConfig) -> None:
        """Construye el paso desde la sección ``ModelConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: ModelConfig) -> ModelStep:
        """Construye ``ModelStep`` desde ``NikodymConfig.model``."""
        return cls(cfg)

    def execute(self, study: Study, rng: np.random.Generator) -> ModelResult:
        """Ejecuta fit en Desarrollo y predicción PD determinista sin consumir ``rng``.

        ``rng`` se recibe por el protocolo homogéneo de ``Step``; model v1 no introduce muestreo ni
        azar propio. La reproducibilidad depende de datos, config y versiones instaladas.
        """
        del rng
        pd = _import_pandas()

        labels = _as_labeled_frame(study.artifacts.get("data", "labels"))
        splits = _as_partition_result(study.artifacts.get("data", "splits"))
        summary = _as_dataframe(study.artifacts.get("binning", "summary"), pd, "binning.summary")
        summary = summary.copy(deep=True)
        selected_features = _as_string_tuple(
            study.artifacts.get("selection", "selected_features"),
            "selection",
            "selected_features",
        )
        selected_woe_columns = _as_string_tuple(
            study.artifacts.get("selection", "selected_woe_columns"),
            "selection",
            "selected_woe_columns",
        )
        selected_woe_frame = _as_dataframe(
            study.artifacts.get("selection", "selected_woe_frame"),
            pd,
            "selection.selected_woe_frame",
        ).copy(deep=True)

        _validate_selected_mapping(selected_features, selected_woe_columns)
        target_col = labels.target_col
        partition_col = splits.partition_col
        _validate_required_columns(
            selected_woe_frame,
            (target_col, partition_col, *selected_woe_columns),
            "selection.selected_woe_frame",
        )
        iv_by_feature = _iv_by_feature(summary, selected_features)

        cfg = _model_config_from_study(study, fallback=self.config)
        _validate_force_overrides(cfg, selected_features)
        self._log_force_overrides(cfg)

        dev_mask = _development_mask(selected_woe_frame, target_col, partition_col)
        dev_frame = selected_woe_frame.loc[dev_mask, list(selected_woe_columns)].copy(deep=True)
        dev_target = selected_woe_frame.loc[dev_mask, target_col].copy(deep=True)
        _validate_development_target(dev_target)

        estimator = _build_estimator(cfg)
        estimator.fit(
            dev_frame,
            dev_target,
            feature_names=selected_features,
            woe_columns=selected_woe_columns,
            iv_by_feature=iv_by_feature,
            audit=self._audit,
        )
        dependency_versions = _dependency_versions()
        estimator.dependency_versions_ = dict(dependency_versions)

        raw_pd_frame = _build_raw_pd_frame(
            frame=selected_woe_frame,
            target_col=target_col,
            partition_col=partition_col,
            estimator=estimator,
            pd=pd,
        )
        result = _build_model_result(
            estimator=estimator,
            config=cfg,
            raw_pd_frame=raw_pd_frame,
            dependency_versions=dependency_versions,
        )
        self._log_stepwise_decisions(result.stepwise_trace, iv_by_feature=iv_by_feature)
        self._log_convergence(result.fit_statistics, config=cfg)
        self._log_filtered_partitions(selected_woe_frame, partition_col=partition_col)
        self._publish_artifacts(study, result)
        return result

    def _log_force_overrides(self, config: ModelConfig) -> None:
        """Registra overrides de negocio usados por ``model`` antes del ajuste."""
        for feature in config.force_include:
            self.log_decision(
                regla="force_include",
                umbral="force_include",
                valor={"feature": feature},
                accion="forzar_inclusion",
            )
        for feature in config.force_exclude:
            self.log_decision(
                regla="force_exclude",
                umbral="force_exclude",
                valor={"feature": feature},
                accion="forzar_exclusion",
            )

    def _log_stepwise_decisions(
        self,
        decisions: tuple[StepwiseDecision, ...],
        *,
        iv_by_feature: Mapping[str, float],
    ) -> None:
        """Registra la traza final del stepwise con payload auditable completo."""
        for decision in decisions:
            valor: dict[str, object] = {
                "iteration": decision.iteration,
                "feature": decision.feature,
                "woe_column": decision.woe_column,
                "criterion": decision.criterion,
                "p_value": decision.p_value,
                "lr_stat": decision.lr_stat,
                "beta": decision.beta,
                "detail": decision.detail,
            }
            if decision.criterion == "sign":
                valor["expected_sign"] = "negative"
            if decision.criterion == "iv_contribution":
                valor["iv"] = iv_by_feature.get(decision.feature)
                valor["iv_contribution"] = _iv_contribution_from_detail(decision.detail)
            self.log_decision(
                regla=_decision_rule(decision),
                umbral=decision.threshold,
                valor=valor,
                accion=_decision_action(decision.action),
            )

    def _log_convergence(self, statistics: ModelFitStatistics, *, config: ModelConfig) -> None:
        """Registra convergencia statsmodels aceptada para trazabilidad del ajuste."""
        self.log_decision(
            regla="statsmodels_convergence",
            umbral={"fit_maxiter": config.fit_maxiter, "tol": config.tol},
            valor={
                "converged": statistics.converged,
                "optimizer": statistics.optimizer,
                "n_iterations": statistics.n_iterations,
            },
            accion="aceptar_ajuste" if statistics.converged else "fallar_corrida",
        )

    def _log_filtered_partitions(self, frame: DataFrame, *, partition_col: str) -> None:
        """Registra filas fuera de particiones modelables cuando existen."""
        mask = _modelable_mask(frame, partition_col)
        filtered_count = int((~mask).sum())
        if filtered_count == 0:
            return
        self.log_decision(
            regla="partition_fuera_de_modelo",
            umbral=tuple(sorted(_MODEL_PARTITIONS)),
            valor={"partition_col": partition_col, "conteo": filtered_count},
            accion="no_puntuar",
        )

    def _publish_artifacts(self, study: Study, result: ModelResult) -> None:
        """Publica los nueve artefactos estables del dominio ``model``."""
        study.artifacts.set("model", "estimator", result.estimator)
        study.artifacts.set("model", "final_features", result.final_features)
        study.artifacts.set("model", "final_woe_columns", result.final_woe_columns)
        study.artifacts.set("model", "coefficients", result.coefficients.copy(deep=True))
        study.artifacts.set("model", "stepwise_trace", result.stepwise_trace)
        study.artifacts.set("model", "fit_statistics", result.fit_statistics)
        study.artifacts.set("model", "raw_pd_frame", result.raw_pd_frame.copy(deep=True))
        study.artifacts.set("model", "result", result)
        study.artifacts.set("model", "model_card", result.model_card)


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "ModelStep requiere pandas; instale las dependencias base de nikodym."
        ) from exc


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular de entrada antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise ModelFitError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_labeled_frame(value: object) -> LabeledFrame:
    """Valida el artefacto ``data.labels`` con import local de ``data``."""
    from nikodym.data.target import LabeledFrame

    if isinstance(value, LabeledFrame):
        return value
    raise ModelFitError(
        "El artefacto ('data', 'labels') debe ser un LabeledFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_partition_result(value: object) -> PartitionResult:
    """Valida el artefacto ``data.splits`` con import local de ``data``."""
    from nikodym.data.partition import PartitionResult

    if isinstance(value, PartitionResult):
        return value
    raise ModelFitError(
        "El artefacto ('data', 'splits') debe ser un PartitionResult; "
        f"tipo observado={type(value).__name__}."
    )


def _as_string_tuple(value: object, domain: str, key: str) -> tuple[str, ...]:
    """Valida artefactos ``tuple[str, ...]`` publicados por ``selection``."""
    if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ModelFitError(
        f"El artefacto ('{domain}', '{key}') debe ser tuple[str, ...]; "
        f"tipo observado={type(value).__name__}."
    )


def _validate_selected_mapping(
    selected_features: tuple[str, ...],
    selected_woe_columns: tuple[str, ...],
) -> None:
    """Valida que features y columnas WoE preserven el mapping 1:1 de ``selection``."""
    if len(selected_features) != len(selected_woe_columns):
        raise ModelFitError(
            "selection.selected_features y selection.selected_woe_columns deben tener el mismo "
            f"largo: features={len(selected_features)}, woe_columns={len(selected_woe_columns)}."
        )


def _validate_required_columns(
    frame: DataFrame,
    columns: tuple[str, ...],
    artifact: str,
) -> None:
    """Falla con una lista completa si faltan columnas requeridas."""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise ModelFitError(f"{artifact} no contiene columnas requeridas: {joined}.")


def _iv_by_feature(summary: DataFrame, selected_features: tuple[str, ...]) -> dict[str, float]:
    """Construye ``feature -> IV`` desde ``binning.summary`` sin recalcular IV."""
    _validate_required_columns(summary, ("name", "iv"), "binning.summary")
    selected = set(selected_features)
    observed: dict[str, float] = {}
    for row in cast("list[dict[str, object]]", summary.loc[:, ["name", "iv"]].to_dict("records")):
        feature = str(row["name"])
        if feature not in selected:
            continue
        if feature in observed:
            raise ModelFitError(f"binning.summary contiene IV duplicado para feature='{feature}'.")
        observed[feature] = _finite_nonnegative_float(row["iv"], label=f"IV feature='{feature}'")

    missing = [feature for feature in selected_features if feature not in observed]
    if missing:
        raise ModelFitError(
            "binning.summary no contiene IV para todas las features seleccionadas; "
            f"faltantes={missing}."
        )
    return {feature: observed[feature] for feature in selected_features}


def _finite_nonnegative_float(value: object, *, label: str) -> float:
    """Convierte un escalar a float finito no negativo normalizado."""
    if isinstance(value, bool):
        raise ModelFitError(f"{label} debe ser numérico finito, no booleano.")
    try:
        candidate = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ModelFitError(f"{label} no es numérico: {value!r}.") from exc
    if not math.isfinite(candidate) or candidate < 0.0:
        raise ModelFitError(f"{label} debe ser finito y no negativo: {candidate!r}.")
    return _normalize_float(candidate)


def _model_config_from_study(study: Study, *, fallback: ModelConfig) -> ModelConfig:
    """Lee ``NikodymConfig.model`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "model", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, ModelConfig):
        return raw_config
    return ModelConfig.model_validate(raw_config)


def _validate_force_overrides(config: ModelConfig, selected_features: tuple[str, ...]) -> None:
    """Valida que overrides de negocio apunten a features candidatas reales."""
    candidates = set(selected_features)
    missing = sorted((set(config.force_include) | set(config.force_exclude)) - candidates)
    if missing:
        available = ", ".join(f"'{feature}'" for feature in sorted(candidates))
        raise ModelFitError(
            "Los overrides de model deben referirse a features seleccionadas; "
            f"faltantes={missing}, disponibles=[{available}]."
        )


def _development_mask(frame: DataFrame, target_col: str, partition_col: str) -> Series:
    """Selecciona Desarrollo con target no nulo para el fit anti-leakage."""
    partition = frame[partition_col].astype("string")
    mask = partition.eq("desarrollo") & frame[target_col].notna()
    return cast(Series, mask.fillna(False).astype("bool"))


def _modelable_mask(frame: DataFrame, partition_col: str) -> Series:
    """Selecciona particiones elegibles para PD cruda preservando el orden original."""
    mask = frame[partition_col].astype("string").isin(_MODEL_PARTITIONS)
    return cast(Series, mask.fillna(False).astype("bool"))


def _validate_development_target(target: Series) -> None:
    """Valida target 0/1 con ambas clases antes de llamar al estimador."""
    if target.empty:
        raise ModelFitError("No hay filas de Desarrollo con target no nulo para ajustar model.")
    invalid = ~target.isin((0, 1))
    if bool(invalid.any()):
        observed = sorted(str(value) for value in target.loc[invalid].unique())
        raise ModelFitError(
            "El target de Desarrollo para model debe contener sólo 0/1; "
            f"valores observados inválidos={observed}."
        )
    classes = {int(value) for value in target.unique()}
    if classes != {0, 1}:
        raise ModelFitError(
            "Target degenerado para model: Desarrollo requiere al menos un 0 y un 1; "
            f"clases observadas={sorted(classes)}."
        )


def _build_estimator(config: ModelConfig) -> LogisticPDModel:
    """Importa ``LogisticPDModel`` bajo demanda y traduce la ausencia del extra scoring."""
    try:
        module = importlib.import_module("nikodym.model.estimator")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    estimator_cls = module.LogisticPDModel
    return cast(LogisticPDModel, estimator_cls.from_config(config))


def _build_raw_pd_frame(
    *,
    frame: DataFrame,
    target_col: str,
    partition_col: str,
    estimator: LogisticPDModel,
    pd: Any,
) -> DataFrame:
    """Construye PD cruda para Desarrollo, Holdout y OOT sin usar target fuera de Desarrollo."""
    modelable = _modelable_mask(frame, partition_col)
    final_columns = list(estimator.final_woe_columns_)
    scoring_frame = frame.loc[modelable, final_columns].copy(deep=True)
    linear = estimator.decision_function(scoring_frame)
    pd_raw = estimator.predict_pd(scoring_frame)

    raw = frame.loc[modelable, [partition_col, target_col]].copy(deep=True)
    raw["linear_predictor"] = linear
    raw["pd_raw"] = pd_raw
    for column in ("linear_predictor", "pd_raw"):
        raw[column] = raw[column].map(lambda value: _normalize_float(float(value)))
    return raw.loc[scoring_frame.index].copy(deep=True)


def _build_model_result(
    *,
    estimator: LogisticPDModel,
    config: ModelConfig,
    raw_pd_frame: DataFrame,
    dependency_versions: Mapping[str, str],
) -> ModelResult:
    """Ensambla ``ModelResult`` y ``ModelCardSection`` sin recalcular inferencia."""
    from nikodym.model.results import ModelCardSection, ModelResult

    final_features = tuple(estimator.final_features_)
    final_woe_columns = tuple(estimator.final_woe_columns_)
    coefficients = estimator.coefficient_table_.copy(deep=True)
    trace = tuple(estimator.stepwise_trace_)
    statistics = estimator.fit_statistics_
    placeholder = ModelCardSection(
        engine=config.engine,
        n_candidates=len(tuple(estimator.feature_names_in_)),
        n_final_features=len(final_features),
        final_features=final_features,
        thresholds={},
        sign_flags=(),
        iv_contribution_flags=(),
        fit_statistics=statistics,
        dependency_versions=dict(dependency_versions),
    )
    provisional = ModelResult(
        estimator=estimator,
        final_features=final_features,
        final_woe_columns=final_woe_columns,
        coefficients=coefficients,
        stepwise_trace=trace,
        fit_statistics=statistics,
        raw_pd_frame=raw_pd_frame.copy(deep=True),
        model_card=placeholder,
    )
    card = ModelCardSection.from_result(
        provisional,
        engine=config.engine,
        thresholds=_thresholds_from_config(config),
        dependency_versions=dict(dependency_versions),
    )
    return ModelResult(
        estimator=estimator,
        final_features=final_features,
        final_woe_columns=final_woe_columns,
        coefficients=coefficients,
        stepwise_trace=trace,
        fit_statistics=statistics,
        raw_pd_frame=raw_pd_frame.copy(deep=True),
        model_card=card,
    )


def _thresholds_from_config(config: ModelConfig) -> dict[str, float | str | None]:
    """Serializa umbrales activos de model para card/report."""
    direction = config.stepwise.direction if config.stepwise.enabled else "none"
    return {
        "alpha": config.alpha,
        "engine": config.engine,
        "fit_intercept": "true" if config.fit_intercept else "false",
        "fit_maxiter": float(config.fit_maxiter),
        "optimizer": config.optimizer,
        "stepwise.direction": direction,
        "stepwise.criterion": config.stepwise.criterion,
        "entry_p_value": config.stepwise.entry_p_value,
        "exit_p_value": config.stepwise.exit_p_value,
        "stepwise.min_features": float(config.stepwise.min_features),
        "stepwise.max_iter": float(config.stepwise.max_iter),
        "sign_policy.expected_beta_sign": config.sign_policy.expected_beta_sign,
        "sign_policy.action": config.sign_policy.action,
        "iv_contribution.threshold": config.iv_contribution.threshold,
        "iv_contribution.action": config.iv_contribution.action,
        "fail_if_no_features": "true" if config.fail_if_no_features else "false",
    }


def _dependency_versions() -> dict[str, str]:
    """Obtiene versiones instaladas sin importar módulos pesados."""
    versions: dict[str, str] = {}
    for distribution in _DEPENDENCY_DISTRIBUTIONS:
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = "no_instalado"
    return versions


def _decision_rule(decision: StepwiseDecision) -> str:
    """Normaliza la regla auditable desde una decisión de model."""
    if decision.action == "enter":
        return "model_stepwise_enter"
    if decision.action == "remove":
        return "model_stepwise_remove"
    if decision.criterion == "sign":
        return "model_sign_inverted"
    if decision.criterion == "iv_contribution":
        return "model_iv_contribution"
    return f"model_{decision.criterion}"


def _decision_action(action: str) -> str:
    """Traduce acciones del DTO a verbos auditables en español."""
    actions = {
        "enter": "entrar",
        "remove": "salir",
        "keep": "conservar",
        "flag": "flag",
        "exclude": "excluir",
        "fail": "fallar",
    }
    return actions.get(action, action)


def _iv_contribution_from_detail(detail: str) -> float | None:
    """Extrae ``iv_contribution`` desde el detalle normalizado del estimador si existe."""
    prefix = "iv_contribution="
    if not detail.startswith(prefix):
        return None
    try:
        value = float(detail.removeprefix(prefix))
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return _normalize_float(value)


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` para salidas reproducibles."""
    if value == 0.0:
        return 0.0
    return value
