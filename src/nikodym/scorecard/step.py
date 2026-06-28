"""Paso orquestable de la capa ``scorecard`` (SDD-09 §4/§6/§7; CT-1).

``ScorecardStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``scorecard``: lee artefactos publicados por ``binning`` y ``model``, delega el escalamiento
log-odds a puntos en :class:`~nikodym.scorecard.scaler.PointsScaler`, alinea el score con la PD
cruda del modelo y publica los artefactos auditables bajo el dominio ``scorecard``.

El módulo evita importar ``pandas``, ``numpy``, ``sklearn``, ``statsmodels`` y ``optbinning`` en
import time. ``nikodym.scorecard`` lo importa para ejecutar
``@register("standard", domain="scorecard")`` sin contaminar el núcleo liviano; las dependencias
tabulares se cargan dentro de ``execute``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping
from importlib import metadata
from typing import TYPE_CHECKING, Any, Final, Protocol, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.scorecard.config import ScorecardConfig
from nikodym.scorecard.exceptions import ScorecardFitError
from nikodym.scorecard.scaler import PointsScaler

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study
    from nikodym.scorecard.results import ScorecardCardSection, ScorecardResult

    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series[Any]
else:
    AuditEvent: TypeAlias = Any
    DataFrame: TypeAlias = Any
    ScorecardCardSection: TypeAlias = Any
    ScorecardResult: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["SCORECARD_ARTIFACTS", "ScorecardStep"]

SCORECARD_ARTIFACTS: Final[tuple[str, ...]] = ("scorecard", "score", "result", "card")
_SCORING_EXTRA_MESSAGE: Final = (
    "ScorecardStep requiere pandas/numpy; instale las dependencias base de nikodym."
)
_DEPENDENCY_DISTRIBUTIONS: Final[tuple[str, ...]] = ("pandas", "numpy")
_MODEL_PARTITIONS: Final[frozenset[str]] = frozenset({"desarrollo", "holdout", "oot"})
_PARTITION_COLUMN: Final = "partition"
_RAW_PD_COLUMNS: Final[tuple[str, ...]] = (
    "partition",
    "target",
    "linear_predictor",
    "pd_raw",
)
_INTERCEPT_FEATURE: Final = "intercept"
_INTERCEPT_WOE_COLUMN: Final = "const"


class _BinningResultLike(Protocol):
    """Contrato estructural mínimo consumido desde ``BinningResult``."""

    woe_column_map: dict[str, str]


class _ModelEstimatorLike(Protocol):
    """Contrato estructural mínimo consumido desde ``LogisticPDModel``."""

    fit_intercept: bool


@register("standard", domain="scorecard")
class ScorecardStep(AuditableMixin):
    """Orquesta el escalamiento log-odds a puntos y publica ``domain='scorecard'``."""

    name: str = "scorecard"
    requires: tuple[ArtifactKey, ...] = (
        ("binning", "tables"),
        ("binning", "summary"),
        ("binning", "woe_frame"),
        ("binning", "result"),
        ("model", "estimator"),
        ("model", "final_features"),
        ("model", "final_woe_columns"),
        ("model", "coefficients"),
        ("model", "raw_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = tuple(("scorecard", key) for key in SCORECARD_ARTIFACTS)

    def __init__(self, config: ScorecardConfig) -> None:
        """Construye el paso desde la sección ``ScorecardConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: ScorecardConfig) -> ScorecardStep:
        """Construye ``ScorecardStep`` desde ``NikodymConfig.scorecard``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` a ``PointsScaler``."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> ScorecardResult:
        """Ejecuta scorecard determinista sin consumir ``rng`` y publica cuatro artefactos."""
        del rng
        pd = _import_pandas()

        tables = _as_tables(study.artifacts.get("binning", "tables"), pd)
        summary = _as_dataframe(study.artifacts.get("binning", "summary"), pd, "binning.summary")
        woe_frame = _as_dataframe(
            study.artifacts.get("binning", "woe_frame"),
            pd,
            "binning.woe_frame",
        ).copy(deep=True)
        binning_result = _as_binning_result(study.artifacts.get("binning", "result"))
        estimator = _as_model_estimator(study.artifacts.get("model", "estimator"))
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
        summary = summary.copy(deep=True)
        del summary

        cfg = _scorecard_config_from_study(study, fallback=self.config)
        woe_column_map = _woe_column_map_from_binning_result(binning_result)
        _validate_feature_mapping(final_features, final_woe_columns, woe_column_map)
        _validate_woe_frame_columns(woe_frame, final_woe_columns)
        _validate_raw_pd_frame(raw_pd_frame)
        beta_by_feature, alpha = _extract_coefficients(
            coefficients,
            final_features=final_features,
            final_woe_columns=final_woe_columns,
            fit_intercept=estimator.fit_intercept,
        )
        del beta_by_feature, alpha
        factor, offset = _scale_parameters(cfg)

        scaler = PointsScaler.from_config(cfg)
        scaler.fit(
            coefficients=coefficients.copy(deep=True),
            final_features=final_features,
            final_woe_columns=final_woe_columns,
            binning_tables=tables,
            woe_column_map=woe_column_map,
            audit=self,
        )

        modelable_woe_frame = self._filter_modelable_rows(woe_frame)
        scored = scaler.transform(modelable_woe_frame)
        score_frame = _assemble_score_frame(
            transformed=scored,
            raw_pd_frame=raw_pd_frame,
            points_columns=tuple(scaler.points_columns_),
            score_column=str(scaler.score_column),
        )
        card = _build_card(
            config=cfg,
            factor=factor,
            offset=offset,
            points_columns=tuple(scaler.points_columns_),
            dependency_versions=_dependency_versions(),
        )
        result = _build_result(
            scorecard=scaler.scorecard_.copy(deep=True),
            score=score_frame,
            card=card,
            factor=factor,
            offset=offset,
            config=cfg,
            points_columns=tuple(scaler.points_columns_),
        )
        self._publish_artifacts(study, result)
        return result

    def _filter_modelable_rows(self, frame: DataFrame) -> DataFrame:
        """Filtra filas ``fuera_de_modelo`` y registra la decisión agregada si aparecen."""
        if _PARTITION_COLUMN not in frame.columns:
            return frame.copy(deep=True)
        mask = _modelable_mask(frame)
        filtered = frame.loc[~mask]
        if not filtered.empty:
            counts = {
                str(partition): int(count)
                for partition, count in filtered[_PARTITION_COLUMN]
                .astype("string")
                .value_counts(dropna=False)
                .sort_index()
                .items()
            }
            self.log_decision(
                regla="scorecard_fuera_de_modelo",
                umbral=tuple(sorted(_MODEL_PARTITIONS)),
                valor={"partition_col": _PARTITION_COLUMN, "conteo_por_particion": counts},
                accion="no_puntuar",
            )
        return frame.loc[mask].copy(deep=True)

    def _publish_artifacts(self, study: Study, result: ScorecardResult) -> None:
        """Publica los cuatro artefactos estables del dominio ``scorecard``."""
        study.artifacts.set("scorecard", "scorecard", result.scorecard.copy(deep=True))
        study.artifacts.set("scorecard", "score", result.score.copy(deep=True))
        study.artifacts.set("scorecard", "result", result)
        study.artifacts.set("scorecard", "card", result.card)


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
    raise ScorecardFitError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_tables(value: object, pd: Any) -> dict[str, DataFrame]:
    """Valida las tablas por variable publicadas por ``binning``."""
    if not isinstance(value, Mapping):
        raise ScorecardFitError(
            "El artefacto ('binning', 'tables') debe ser un mapping de DataFrames; "
            f"tipo observado={type(value).__name__}."
        )
    tables: dict[str, DataFrame] = {}
    for name, table in value.items():
        if not isinstance(table, pd.DataFrame):
            raise ScorecardFitError(
                "El artefacto ('binning', 'tables') contiene una tabla no tabular: "
                f"feature={name!r}, tipo observado={type(table).__name__}."
            )
        tables[str(name)] = cast(DataFrame, table.copy(deep=True))
    return tables


def _as_string_tuple(value: object, domain: str, key: str) -> tuple[str, ...]:
    """Valida artefactos ``tuple[str, ...]`` publicados por ``model``."""
    if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ScorecardFitError(
        f"El artefacto ('{domain}', '{key}') debe ser tuple[str, ...]; "
        f"tipo observado={type(value).__name__}."
    )


def _as_binning_result(value: object) -> _BinningResultLike:
    """Valida estructuralmente el ``BinningResult`` consumido por scorecard."""
    mapping = getattr(value, "woe_column_map", None)
    if isinstance(mapping, dict) and all(
        isinstance(feature, str) and isinstance(column, str) for feature, column in mapping.items()
    ):
        return cast(_BinningResultLike, value)
    raise ScorecardFitError(
        "El artefacto ('binning', 'result') debe exponer woe_column_map: dict[str, str]; "
        f"tipo observado={type(value).__name__}."
    )


def _as_model_estimator(value: object) -> _ModelEstimatorLike:
    """Valida estructuralmente el estimador de ``model`` sin importar sklearn."""
    fit_intercept = getattr(value, "fit_intercept", None)
    if isinstance(fit_intercept, bool):
        return cast(_ModelEstimatorLike, value)
    raise ScorecardFitError(
        "El artefacto ('model', 'estimator') debe exponer fit_intercept: bool; "
        f"tipo observado={type(value).__name__}."
    )


def _scorecard_config_from_study(study: Study, *, fallback: ScorecardConfig) -> ScorecardConfig:
    """Lee ``NikodymConfig.scorecard`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "scorecard", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, ScorecardConfig):
        return raw_config
    return ScorecardConfig.model_validate(raw_config)


def _woe_column_map_from_binning_result(result: _BinningResultLike) -> dict[str, str]:
    """Devuelve una copia del mapping real ``feature -> columna WoE``."""
    return dict(result.woe_column_map)


def _validate_feature_mapping(
    final_features: tuple[str, ...],
    final_woe_columns: tuple[str, ...],
    woe_column_map: Mapping[str, str],
) -> None:
    """Valida coherencia de features finales, columnas WoE y mapping de binning."""
    if len(final_features) != len(final_woe_columns):
        raise ScorecardFitError(
            "model.final_features y model.final_woe_columns deben tener el mismo largo: "
            f"features={len(final_features)}, woe_columns={len(final_woe_columns)}."
        )
    if not final_features:
        raise ScorecardFitError("ScorecardStep requiere al menos una variable final.")
    if len(set(final_features)) != len(final_features):
        raise ScorecardFitError(f"model.final_features contiene duplicados: {final_features!r}.")
    if len(set(final_woe_columns)) != len(final_woe_columns):
        raise ScorecardFitError(
            f"model.final_woe_columns contiene duplicados: {final_woe_columns!r}."
        )
    for feature, woe_column in zip(final_features, final_woe_columns, strict=True):
        observed = woe_column_map.get(feature)
        if observed is None:
            raise ScorecardFitError(
                "binning.result.woe_column_map no contiene una feature final: "
                f"feature='{feature}', disponibles={sorted(woe_column_map)}."
            )
        if observed != woe_column:
            raise ScorecardFitError(
                "binning.result.woe_column_map no coincide con model.final_woe_columns: "
                f"feature='{feature}', esperado='{woe_column}', observado='{observed}'."
            )


def _validate_woe_frame_columns(frame: DataFrame, final_woe_columns: tuple[str, ...]) -> None:
    """Valida columnas WoE finales antes de llamar a ``PointsScaler.transform``."""
    _validate_unique_columns(frame, artifact="binning.woe_frame")
    missing = [column for column in final_woe_columns if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise ScorecardFitError(f"binning.woe_frame no contiene columnas WoE finales: {joined}.")


def _validate_raw_pd_frame(frame: DataFrame) -> None:
    """Valida columnas e índice del artefacto ``model.raw_pd_frame``."""
    _validate_unique_columns(frame, artifact="model.raw_pd_frame")
    _validate_unique_index(frame, artifact="model.raw_pd_frame")
    missing = [column for column in _RAW_PD_COLUMNS if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise ScorecardFitError(f"model.raw_pd_frame no contiene columnas requeridas: {joined}.")


def _validate_unique_columns(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise ScorecardFitError(f"{artifact} contiene columnas duplicadas: {joined}.")


def _validate_unique_index(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza índices duplicados antes de alinear por índice."""
    if frame.index.is_unique:
        return
    duplicated = frame.index[frame.index.duplicated()].astype(str).tolist()
    joined = ", ".join(f"'{item}'" for item in duplicated[:5])
    raise ScorecardFitError(f"{artifact} contiene índice duplicado; ejemplos: {joined}.")


def _extract_coefficients(
    coefficients: DataFrame,
    *,
    final_features: tuple[str, ...],
    final_woe_columns: tuple[str, ...],
    fit_intercept: bool,
) -> tuple[dict[str, float], float]:
    """Extrae betas finales y ``alpha`` para validar el contrato antes del scaler."""
    _validate_unique_columns(coefficients, artifact="model.coefficients")
    required = {"feature", "woe_column", "beta"}
    missing = sorted(required - set(coefficients.columns))
    if missing:
        raise ScorecardFitError(f"model.coefficients no contiene columnas requeridas: {missing}.")
    features = coefficients["feature"].astype(str)
    woe_columns = coefficients["woe_column"].astype(str)
    intercept_mask = features.eq(_INTERCEPT_FEATURE) | woe_columns.eq(_INTERCEPT_WOE_COLUMN)
    intercept_rows = coefficients.loc[intercept_mask]
    if len(intercept_rows.index) > 1:
        raise ScorecardFitError("model.coefficients contiene más de una fila de intercepto.")
    if fit_intercept and len(intercept_rows.index) == 0:
        raise ScorecardFitError(
            "model.coefficients no contiene intercepto aunque model.estimator.fit_intercept=True."
        )
    alpha = 0.0 if intercept_rows.empty else _finite_float(intercept_rows["beta"].iloc[0], "alpha")

    non_intercept = coefficients.loc[~intercept_mask].copy(deep=True)
    beta_by_feature: dict[str, float] = {}
    for feature, woe_column in zip(final_features, final_woe_columns, strict=True):
        match = non_intercept.loc[
            non_intercept["feature"].astype(str).eq(feature)
            | non_intercept["woe_column"].astype(str).eq(woe_column)
        ]
        if len(match.index) == 0:
            raise ScorecardFitError(f"Feature final sin coeficiente: feature='{feature}'.")
        if len(match.index) > 1:
            raise ScorecardFitError(f"Coeficiente ambiguo para feature='{feature}'.")
        row = match.iloc[0]
        observed = (str(row["feature"]), str(row["woe_column"]))
        expected = (feature, woe_column)
        if observed != expected:
            raise ScorecardFitError(
                "La fila de model.coefficients no coincide con el mapping final: "
                f"esperado={expected!r}, observado={observed!r}."
            )
        beta_by_feature[feature] = _finite_float(row["beta"], f"beta feature='{feature}'")
    return beta_by_feature, _normalize_float(alpha)


def _finite_float(value: object, label: str) -> float:
    """Convierte un escalar a float finito normalizado."""
    try:
        candidate = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ScorecardFitError(f"{label} no es numérico: {value!r}.") from exc
    if not math.isfinite(candidate):
        raise ScorecardFitError(f"{label} no es finito: {candidate!r}.")
    return _normalize_float(candidate)


def _scale_parameters(config: ScorecardConfig) -> tuple[float, float]:
    """Calcula ``Factor`` y ``Offset`` de la escala de scorecard."""
    factor = _normalize_float(float(config.pdo) / math.log(2.0))
    offset = _normalize_float(
        float(config.target_score) - factor * math.log(float(config.target_odds))
    )
    return factor, offset


def _modelable_mask(frame: DataFrame) -> Series:
    """Selecciona particiones elegibles para recibir score."""
    mask = frame[_PARTITION_COLUMN].astype("string").isin(_MODEL_PARTITIONS)
    return cast(Series, mask.fillna(False).astype("bool"))


def _assemble_score_frame(
    *,
    transformed: DataFrame,
    raw_pd_frame: DataFrame,
    points_columns: tuple[str, ...],
    score_column: str,
) -> DataFrame:
    """Alinea puntos con PD cruda por índice sin recalcular probabilidades."""
    _validate_unique_index(transformed, artifact="scorecard.transform")
    missing_in_raw = transformed.index.difference(raw_pd_frame.index)
    extra_raw = raw_pd_frame.index.difference(transformed.index)
    if len(missing_in_raw) or len(extra_raw):
        raise ScorecardFitError(
            "model.raw_pd_frame y binning.woe_frame modelable no tienen el mismo índice: "
            f"faltan_en_raw={missing_in_raw.astype(str).tolist()}, "
            f"sobran_en_raw={extra_raw.astype(str).tolist()}."
        )
    structural = raw_pd_frame.loc[transformed.index, list(_RAW_PD_COLUMNS)].copy(deep=True)
    points = transformed.loc[:, [*points_columns, score_column]].copy(deep=True)
    pd = _import_pandas()
    result = cast(DataFrame, pd.concat([structural, points], axis=1))
    return _normalize_float_frame(result, pd=pd)


def _build_card(
    *,
    config: ScorecardConfig,
    factor: float,
    offset: float,
    points_columns: tuple[str, ...],
    dependency_versions: Mapping[str, str],
) -> ScorecardCardSection:
    """Construye la sección de model card resolviendo versiones fuera de ``results.py``."""
    from nikodym.scorecard.results import ScorecardCardSection

    return ScorecardCardSection(
        pdo=config.pdo,
        target_score=config.target_score,
        target_odds=config.target_odds,
        factor=factor,
        offset=offset,
        score_direction=config.score_direction,
        rounding_method=config.rounding_method,
        n_variables=len(points_columns),
        score_column=config.score_column,
        points_columns=points_columns,
        min_score=config.min_score,
        max_score=config.max_score,
        overrides_count=len(config.point_overrides),
        dependency_versions=dict(dependency_versions),
        metric_sections={},
    )


def _build_result(
    *,
    scorecard: DataFrame,
    score: DataFrame,
    card: ScorecardCardSection,
    factor: float,
    offset: float,
    config: ScorecardConfig,
    points_columns: tuple[str, ...],
) -> ScorecardResult:
    """Construye ``ScorecardResult`` con copias defensivas de las tablas publicadas."""
    from nikodym.scorecard.results import ScorecardResult

    return ScorecardResult(
        scorecard=scorecard.copy(deep=True),
        score=score.copy(deep=True),
        factor=factor,
        offset=offset,
        score_direction=config.score_direction,
        points_columns=points_columns,
        score_column=config.score_column,
        card=card,
    )


def _dependency_versions() -> dict[str, str]:
    """Obtiene versiones instaladas sin importar módulos pesados."""
    versions: dict[str, str] = {}
    for distribution in _DEPENDENCY_DISTRIBUTIONS:
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = "no_instalado"
    return versions


def _normalize_float_frame(frame: DataFrame, *, pd: Any) -> DataFrame:
    """Normaliza ``-0.0`` en columnas float sin alterar enteros."""
    result = frame.copy(deep=True)
    for column in result.select_dtypes(include=["float"]).columns:
        result[column] = result[column].map(lambda value: _normalize_float(float(value)))
    return result


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` para salidas reproducibles."""
    if value == 0.0:
        return 0.0
    return value
