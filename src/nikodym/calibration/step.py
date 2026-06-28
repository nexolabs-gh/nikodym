"""Paso orquestable de la capa ``calibration`` (SDD-10 §4/§6/§7/§9; CT-1).

``CalibrationStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``calibration``: lee los artefactos publicados por ``model``, delega el ajuste numérico a
:class:`~nikodym.calibration.calibrator.PDCalibrator`, emite las decisiones auditables del dominio
y publica la PD calibrada bajo ``domain='calibration'``.

El módulo evita importar ``pandas``, ``numpy``, ``scipy`` y ``sklearn`` en import time.
``nikodym.calibration`` lo importa para ejecutar ``@register("standard", domain="calibration")``
sin contaminar el núcleo liviano; las dependencias científicas se cargan dentro de ``execute`` y
del calibrador.

DECISIÓN B10.4: ``PDCalibrator`` de B10.3 calcula ``post_offset`` en ``platt_scaling`` siempre.
El step deja explícita esa política en el evento ``calibration_platt``; cortar el caso "sólo si el
target externo difiere" requiere cambiar el motor puro y queda trazado, no silencioso.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping
from importlib import metadata
from typing import TYPE_CHECKING, Any, Final, Protocol, TypeAlias, cast

from nikodym.calibration.calibrator import PDCalibrator
from nikodym.calibration.config import CalibrationConfig, CalibrationMethod
from nikodym.calibration.exceptions import CalibrationFitError
from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.calibration.results import (
        CalibrationCardSection,
        CalibrationParameters,
        CalibrationResult,
    )
    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditEvent: TypeAlias = Any
    CalibrationCardSection: TypeAlias = Any
    CalibrationParameters: TypeAlias = Any
    CalibrationResult: TypeAlias = Any
    DataFrame: TypeAlias = Any

__all__ = ["CALIBRATION_ARTIFACTS", "CalibrationStep"]

CALIBRATION_ARTIFACTS: Final[tuple[str, ...]] = (
    "calibrated_pd_frame",
    "parameters",
    "result",
    "card",
)
_SCORING_EXTRA_MESSAGE: Final = (
    "CalibrationStep requiere pandas/numpy/scipy; instale nikodym[scoring]."
)
_MODELABLE_PARTITIONS: Final[frozenset[str]] = frozenset({"desarrollo", "holdout", "oot"})
_FIT_PARTITION: Final = "desarrollo"
_COEFFICIENT_COLUMNS: Final[frozenset[str]] = frozenset({"feature", "woe_column", "beta"})
_OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "linear_predictor_calibrated",
    "pd_calibrated",
    "calibration_method",
    "anchor_kind",
)


class _ModelEstimatorLike(Protocol):
    """Contrato estructural mínimo consumido desde ``LogisticPDModel``."""

    fit_intercept: bool


@register("standard", domain="calibration")
class CalibrationStep(AuditableMixin):
    """Orquesta la calibración de PD cruda y publica ``domain='calibration'``."""

    name: str = "calibration"
    requires: tuple[ArtifactKey, ...] = (
        ("model", "estimator"),
        ("model", "final_features"),
        ("model", "final_woe_columns"),
        ("model", "coefficients"),
        ("model", "raw_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = tuple(("calibration", key) for key in CALIBRATION_ARTIFACTS)

    def __init__(self, config: CalibrationConfig) -> None:
        """Construye el paso desde la sección ``CalibrationConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: CalibrationConfig) -> CalibrationStep:
        """Construye ``CalibrationStep`` desde ``NikodymConfig.calibration``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` si un motor futuro lo requiere."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> CalibrationResult:
        """Ejecuta calibration determinista sin consumir ``rng`` y publica cuatro artefactos."""
        del rng
        pd = _import_pandas()

        _as_model_estimator(study.artifacts.get("model", "estimator"))
        final_features = _as_string_tuple(
            study.artifacts.get("model", "final_features"),
            "model",
            "final_features",
        )
        final_woe_columns = _as_string_tuple(
            study.artifacts.get("model", "final_woe_columns"),
            "model",
            "final_woe_columns",
        )
        coefficients = _as_dataframe(
            study.artifacts.get("model", "coefficients"),
            pd,
            "model.coefficients",
        ).copy(deep=True)
        raw_pd_frame = _as_dataframe(
            study.artifacts.get("model", "raw_pd_frame"),
            pd,
            "model.raw_pd_frame",
        ).copy(deep=True)

        cfg = _calibration_config_from_study(study, fallback=self.config)
        _validate_model_metadata(final_features, final_woe_columns)
        _validate_coefficients(
            coefficients,
            final_features=final_features,
            final_woe_columns=final_woe_columns,
        )
        _validate_raw_pd_frame(raw_pd_frame, cfg)
        modelable_frame = self._filter_modelable_rows(raw_pd_frame, cfg)

        calibrator = PDCalibrator.from_config(cfg)
        # B10.4 concentra la auditoría visible en el Step: no se inyecta el sink al calibrador.
        calibrator.fit(modelable_frame.copy(deep=True))
        calibrated = calibrator.transform(modelable_frame.copy(deep=True))

        parameters = _build_parameters(calibrator)
        card = _build_card(
            calibrator=calibrator,
            config=cfg,
            dependency_versions=_dependency_versions(parameters.method),
        )
        result = _build_result(
            calibrated_pd_frame=calibrated,
            parameters=parameters,
            card=card,
        )
        self._log_fit_decisions(calibrator, parameters=parameters, card=card)
        self._publish_artifacts(study, result)
        return result

    def _filter_modelable_rows(self, frame: DataFrame, config: CalibrationConfig) -> DataFrame:
        """Filtra filas fuera de Dev/HO/OOT y registra la decisión agregada si aparecen."""
        partition_col = config.partition_column
        mask = frame[partition_col].astype("string").isin(_MODELABLE_PARTITIONS)
        filtered = frame.loc[~mask.fillna(False).astype("bool")]
        if not filtered.empty:
            counts = {
                str(partition): int(count)
                for partition, count in filtered[partition_col]
                .astype("string")
                .value_counts(dropna=False)
                .sort_index()
                .items()
            }
            self.log_decision(
                regla="calibration_fuera_de_modelo",
                umbral=tuple(sorted(_MODELABLE_PARTITIONS)),
                valor={"partition_col": partition_col, "conteo_por_particion": counts},
                accion="no_calibrar",
            )
        modelable = frame.loc[mask.fillna(False).astype("bool")].copy(deep=True)
        if modelable.empty:
            raise CalibrationFitError(
                "calibration requiere al menos una fila modelable Dev/HO/OOT."
            )
        return modelable

    def _log_fit_decisions(
        self,
        calibrator: PDCalibrator,
        *,
        parameters: CalibrationParameters,
        card: CalibrationCardSection,
    ) -> None:
        """Registra las decisiones auditables de SDD-10 §9 desde el step."""
        self.log_decision(
            regla="calibration_anchor",
            umbral=parameters.fit_partition,
            valor={
                "target_pd": parameters.target_pd,
                "anchor_kind": parameters.anchor_kind,
                "anchor_source": parameters.anchor_source,
            },
            accion="fijar_ancla",
        )
        self.log_decision(
            regla="calibration_method",
            umbral=parameters.target_tolerance,
            valor={"method": parameters.method, "n_fit": parameters.n_fit},
            accion="ajustar_calibracion",
        )
        self.log_decision(
            regla="calibration_offset",
            umbral=parameters.target_tolerance,
            valor={
                "offset": parameters.offset,
                "raw_mean_pd_dev": parameters.raw_mean_pd_dev,
                "calibrated_mean_pd_dev": parameters.achieved_mean_pd_dev,
            },
            accion="publicar_pd_calibrada",
        )
        if parameters.method == "platt_scaling":
            self.log_decision(
                regla="calibration_platt",
                umbral="slope>0",
                valor={
                    "slope": parameters.slope,
                    "intercept": parameters.intercept,
                    "post_offset": parameters.post_offset,
                    "post_offset_policy": (
                        "PDCalibrator B10.3 lo resuelve siempre; B10.4 lo deja explícito."
                    ),
                },
                accion="preservar_ranking",
            )
        if parameters.method == "isotonic":
            self.log_decision(
                regla="calibration_isotonic",
                umbral="monotona_no_decreciente",
                valor={
                    "n_knots": len(parameters.isotonic_knots),
                    "ties_created": card.ties_created,
                },
                accion="registrar_empates",
            )
        self.log_decision(
            regla="calibration_ranking",
            umbral="rank(pd_raw)==rank(pd_calibrated)",
            valor={
                "ranking_preserved": card.ranking_preserved,
                "ties_created": card.ties_created,
            },
            accion="registrar_ranking",
        )
        del calibrator

    def _publish_artifacts(self, study: Study, result: CalibrationResult) -> None:
        """Publica los cuatro artefactos estables del dominio ``calibration``."""
        study.artifacts.set(
            "calibration",
            "calibrated_pd_frame",
            result.calibrated_pd_frame.copy(deep=True),
        )
        study.artifacts.set(
            "calibration",
            "parameters",
            result.parameters.model_copy(deep=True),
        )
        study.artifacts.set("calibration", "result", result.model_copy(deep=True))
        study.artifacts.set("calibration", "card", result.card.model_copy(deep=True))


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular de entrada antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise CalibrationFitError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_string_tuple(value: object, domain: str, key: str) -> tuple[str, ...]:
    """Valida artefactos ``tuple[str, ...]`` publicados por ``model``."""
    if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise CalibrationFitError(
        f"El artefacto ('{domain}', '{key}') debe ser tuple[str, ...]; "
        f"tipo observado={type(value).__name__}."
    )


def _as_model_estimator(value: object) -> _ModelEstimatorLike:
    """Valida estructuralmente el estimador de ``model`` sin importar sklearn."""
    fit_intercept = getattr(value, "fit_intercept", None)
    if isinstance(fit_intercept, bool):
        return cast(_ModelEstimatorLike, value)
    raise CalibrationFitError(
        "El artefacto ('model', 'estimator') debe exponer fit_intercept: bool; "
        f"tipo observado={type(value).__name__}."
    )


def _calibration_config_from_study(
    study: Study,
    *,
    fallback: CalibrationConfig,
) -> CalibrationConfig:
    """Lee ``NikodymConfig.calibration`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "calibration", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, CalibrationConfig):
        return raw_config
    return CalibrationConfig.model_validate(raw_config)


def _validate_model_metadata(
    final_features: tuple[str, ...],
    final_woe_columns: tuple[str, ...],
) -> None:
    """Valida trazabilidad mínima de features y columnas WoE finales."""
    if len(final_features) != len(final_woe_columns):
        raise CalibrationFitError(
            "model.final_features y model.final_woe_columns deben tener el mismo largo: "
            f"features={len(final_features)}, woe_columns={len(final_woe_columns)}."
        )
    if not final_features:
        raise CalibrationFitError("CalibrationStep requiere al menos una variable final.")
    if len(set(final_features)) != len(final_features):
        raise CalibrationFitError(f"model.final_features contiene duplicados: {final_features!r}.")
    if len(set(final_woe_columns)) != len(final_woe_columns):
        raise CalibrationFitError(
            f"model.final_woe_columns contiene duplicados: {final_woe_columns!r}."
        )


def _validate_coefficients(
    coefficients: DataFrame,
    *,
    final_features: tuple[str, ...],
    final_woe_columns: tuple[str, ...],
) -> None:
    """Valida que la tabla de coeficientes documente el modelo que se calibra."""
    _validate_unique_columns(coefficients, artifact="model.coefficients")
    missing = sorted(_COEFFICIENT_COLUMNS - set(str(column) for column in coefficients.columns))
    if missing:
        raise CalibrationFitError(f"model.coefficients no contiene columnas requeridas: {missing}.")

    feature_series = coefficients["feature"].astype(str)
    woe_series = coefficients["woe_column"].astype(str)
    for feature, woe_column in zip(final_features, final_woe_columns, strict=True):
        match = coefficients.loc[feature_series.eq(feature) | woe_series.eq(woe_column)]
        if len(match.index) == 0:
            raise CalibrationFitError(f"Feature final sin coeficiente: feature='{feature}'.")
        if len(match.index) > 1:
            raise CalibrationFitError(f"Coeficiente ambiguo para feature='{feature}'.")
        row = match.iloc[0]
        observed = (str(row["feature"]), str(row["woe_column"]))
        expected = (feature, woe_column)
        if observed != expected:
            raise CalibrationFitError(
                "La fila de model.coefficients no coincide con el mapping final: "
                f"esperado={expected!r}, observado={observed!r}."
            )
        _finite_float(row["beta"], f"beta feature='{feature}'")


def _validate_raw_pd_frame(frame: DataFrame, config: CalibrationConfig) -> None:
    """Valida columnas, unicidad y colisiones del artefacto ``model.raw_pd_frame``."""
    _validate_unique_columns(frame, artifact="model.raw_pd_frame")
    _validate_unique_index(frame, artifact="model.raw_pd_frame")
    required = (
        config.partition_column,
        config.target_column,
        config.linear_predictor_column,
        config.pd_raw_column,
    )
    missing = [column for column in required if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise CalibrationFitError(f"model.raw_pd_frame no contiene columnas requeridas: {joined}.")
    collisions = [column for column in _OUTPUT_COLUMNS if column in frame.columns]
    if collisions:
        joined = ", ".join(f"'{column}'" for column in collisions)
        raise CalibrationFitError(
            f"model.raw_pd_frame ya contiene columnas de salida de calibration: {joined}."
        )


def _validate_unique_columns(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise CalibrationFitError(f"{artifact} contiene columnas duplicadas: {joined}.")


def _validate_unique_index(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza índices duplicados antes de preservar orden/índice."""
    if frame.index.is_unique:
        return
    duplicated = frame.index[frame.index.duplicated()].astype(str).tolist()
    joined = ", ".join(f"'{item}'" for item in duplicated[:5])
    raise CalibrationFitError(f"{artifact} contiene índice duplicado; ejemplos: {joined}.")


def _finite_float(value: object, label: str) -> float:
    """Convierte un escalar a float finito normalizado."""
    try:
        candidate = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise CalibrationFitError(f"{label} no es numérico: {value!r}.") from exc
    if not math.isfinite(candidate):
        raise CalibrationFitError(f"{label} no es finito: {candidate!r}.")
    if candidate == 0.0:
        return 0.0
    return candidate


def _build_parameters(calibrator: PDCalibrator) -> CalibrationParameters:
    """Construye ``CalibrationParameters`` desde atributos fiteados del calibrador."""
    from nikodym.calibration.results import CalibrationParameters

    fitted = cast(Any, calibrator)
    return CalibrationParameters(
        method=cast(CalibrationMethod, fitted.method_),
        target_pd=float(fitted.target_pd_),
        anchor_kind=fitted.anchor_kind_,
        anchor_source=fitted.anchor_source_,
        fit_partition=_FIT_PARTITION,
        offset=fitted.offset_,
        slope=fitted.slope_,
        intercept=fitted.intercept_,
        isotonic_knots=tuple(fitted.isotonic_knots_),
        post_offset=fitted.post_offset_,
        target_tolerance=float(fitted.target_tolerance),
        achieved_mean_pd_dev=float(fitted.achieved_mean_pd_dev_),
        raw_mean_pd_dev=float(fitted.raw_mean_pd_dev_),
        observed_default_rate_dev=fitted.observed_default_rate_dev_,
        n_fit=int(fitted.n_fit_),
    )


def _build_card(
    *,
    calibrator: PDCalibrator,
    config: CalibrationConfig,
    dependency_versions: Mapping[str, str],
) -> CalibrationCardSection:
    """Construye la sección de model card resolviendo versiones fuera de ``results.py``."""
    from nikodym.calibration.results import CalibrationCardSection

    fitted = cast(Any, calibrator)
    return CalibrationCardSection(
        method=cast(CalibrationMethod, fitted.method_),
        target_pd=float(fitted.target_pd_),
        anchor_kind=fitted.anchor_kind_,
        anchor_source=fitted.anchor_source_,
        fit_partition=_FIT_PARTITION,
        n_fit=int(fitted.n_fit_),
        raw_mean_pd_dev=float(fitted.raw_mean_pd_dev_),
        calibrated_mean_pd_dev=float(fitted.achieved_mean_pd_dev_),
        observed_default_rate_dev=fitted.observed_default_rate_dev_,
        offset=fitted.offset_,
        slope=fitted.slope_,
        intercept=fitted.intercept_,
        ranking_preserved=bool(fitted.ranking_preserved_),
        ties_created=int(fitted.ties_created_),
        pd_raw_column=config.pd_raw_column,
        pd_calibrated_column=config.pd_calibrated_column,
        dependency_versions=dict(dependency_versions),
        metric_sections={},
    )


def _build_result(
    *,
    calibrated_pd_frame: DataFrame,
    parameters: CalibrationParameters,
    card: CalibrationCardSection,
) -> CalibrationResult:
    """Construye ``CalibrationResult`` con copia defensiva del frame calibrado."""
    from nikodym.calibration.results import CalibrationResult

    return CalibrationResult(
        calibrated_pd_frame=calibrated_pd_frame.copy(deep=True),
        parameters=parameters.model_copy(deep=True),
        card=card.model_copy(deep=True),
    )


def _dependency_versions(method: CalibrationMethod) -> dict[str, str]:
    """Obtiene versiones instaladas con ``importlib.metadata`` según el método ejercido."""
    distributions: dict[str, str] = {"pandas": "pandas", "numpy": "numpy", "scipy": "scipy"}
    if method in {"platt_scaling", "isotonic"}:
        distributions["scikit-learn"] = "scikit-learn"

    versions: dict[str, str] = {}
    for public_name, distribution in distributions.items():
        try:
            versions[public_name] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[public_name] = "no_instalado"
    return versions
