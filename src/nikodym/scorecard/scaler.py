"""Escalamiento log-odds a puntos de scorecard (SDD-09 §4/§7).

``PointsScaler`` deriva una tabla de puntos auditable desde coeficientes logísticos WoE y tablas
de binning ya fiteadas. La transformación usa una clave determinista ``(feature, woe)``: si dos
bins de la misma variable comparten exactamente el mismo WoE, el primer bin en el orden publicado
por ``scorecard_`` define el punto usado en ``transform``. Sin overrides, esos puntos son idénticos
por fórmula; con overrides, esta regla evita ambigüedad silenciosa y queda trazada por orden
estable de feature/bin.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias, cast

from pydantic import ValidationError

from nikodym.core.base import NikodymTransformer
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.scorecard.config import (
    InterceptAllocation,
    PointOverrideConfig,
    RoundingMethod,
    ScorecardConfig,
    ScoreDirection,
)
from nikodym.scorecard.exceptions import ScorecardFitError, ScorecardTransformError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    Series: TypeAlias = pd.Series[Any]
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["PointsScaler"]

_SCORING_EXTRA_MESSAGE = "PointsScaler requiere pandas/numpy; instale nikodym[scoring]."
_REQUIRED_COEFFICIENT_COLUMNS = frozenset({"feature", "woe_column", "beta"})
_REQUIRED_BINNING_COLUMNS = frozenset({"Bin", "WoE"})
_INTERCEPT_FEATURE = "intercept"
_INTERCEPT_WOE_COLUMN = "const"


class PointsScaler(NikodymTransformer):
    """Escala componentes log-odds de una logística WoE a puntos de scorecard."""

    config_cls: ClassVar[type[ScorecardConfig]] = ScorecardConfig

    def __init__(
        self,
        *,
        pdo: float = 20.0,
        target_score: float = 600.0,
        target_odds: float = 50.0,
        score_direction: ScoreDirection = "higher_is_lower_risk",
        intercept_allocation: InterceptAllocation = "uniform",
        rounding_method: RoundingMethod = "nearest_integer",
        output_suffix: str = "__points",
        score_column: str = "score",
        min_score: float | None = None,
        max_score: float | None = None,
        clip: bool = False,
        point_overrides: tuple[PointOverrideConfig, ...] = (),
    ) -> None:
        """Asigna hiperparámetros sin lógica para preservar ``clone`` de sklearn."""
        self.pdo = pdo
        self.target_score = target_score
        self.target_odds = target_odds
        self.score_direction = score_direction
        self.intercept_allocation = intercept_allocation
        self.rounding_method = rounding_method
        self.output_suffix = output_suffix
        self.score_column = score_column
        self.min_score = min_score
        self.max_score = max_score
        self.clip = clip
        self.point_overrides = point_overrides

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> PointsScaler:
        """Construye ``PointsScaler`` desde ``ScorecardConfig`` excluyendo ``type``."""
        if not isinstance(cfg, ScorecardConfig):
            cfg = ScorecardConfig.model_validate(cfg)
        kwargs = cfg.model_dump(exclude={"type"})
        kwargs["point_overrides"] = cfg.point_overrides
        return cls(**kwargs)

    def fit(
        self,
        *,
        coefficients: DataFrame,
        final_features: tuple[str, ...],
        final_woe_columns: tuple[str, ...],
        binning_tables: Mapping[str, DataFrame],
        woe_column_map: Mapping[str, str],
        audit: AuditSink | None = None,
    ) -> Self:
        """Deriva puntos por bin desde coeficientes y tablas WoE sin mutar entradas."""
        pd = _import_pandas()
        np = _import_numpy()
        _validate_runtime_config(self)
        if audit is not None:
            self._audit = audit

        features, woe_columns = _validate_feature_mapping(
            final_features=final_features,
            final_woe_columns=final_woe_columns,
            woe_column_map=woe_column_map,
        )
        coefficients_frame = _normalize_coefficients(coefficients, pd=pd)
        coefficient_specs, alpha = _coefficient_specs(
            coefficients_frame,
            features=features,
            woe_columns=woe_columns,
        )
        tables = _copy_binning_tables(
            binning_tables,
            features=features,
            pd=pd,
            np=np,
        )

        n_variables = len(features)
        factor = _normalize_float(float(self.pdo) / math.log(2.0))
        offset = _normalize_float(
            float(self.target_score) - factor * math.log(float(self.target_odds))
        )
        intercept_share = _normalize_float(alpha / n_variables)
        offset_share = _normalize_float(offset / n_variables)
        overrides = _override_map(self.point_overrides)
        rows = _scorecard_rows(
            estimator=self,
            features=features,
            woe_columns=woe_columns,
            coefficients=coefficient_specs,
            tables=tables,
            overrides=overrides,
            factor=factor,
            offset_share=offset_share,
            intercept_share=intercept_share,
        )
        scorecard = _normalize_float_frame(pd.DataFrame(rows), pd=pd)
        point_lookup, duplicate_woe = _point_lookup(scorecard)
        if duplicate_woe:
            self.log_decision(
                regla="woe_duplicado",
                umbral="primera_aparicion_feature_woe",
                valor=duplicate_woe,
                accion="usar_punto_determinista",
            )
        if self.rounding_method != "none":
            rounding_delta = scorecard["rounding_delta"].astype("float64")
            self.log_decision(
                regla="scorecard_rounding",
                umbral=self.rounding_method,
                valor={
                    "n_variables": n_variables,
                    "delta_max_abs": _normalize_float(float(rounding_delta.abs().max())),
                    "delta_suma": _normalize_float(float(rounding_delta.sum())),
                },
                accion="publicar_puntos_redondeados",
            )

        self.factor_ = factor
        self.offset_ = offset
        self.pdo_ = _normalize_float(float(self.pdo))
        self.target_score_ = _normalize_float(float(self.target_score))
        self.target_odds_ = _normalize_float(float(self.target_odds))
        self.score_direction_ = self.score_direction
        self.rounding_method_ = self.rounding_method
        self.intercept_allocation_ = self.intercept_allocation
        self.final_features_ = features
        self.final_woe_columns_ = woe_columns
        self.points_columns_ = tuple(f"{feature}{self.output_suffix}" for feature in features)
        self.coefficients_ = coefficients_frame.copy(deep=True)
        self.scorecard_ = scorecard.copy(deep=True)
        self.feature_points_ = {
            feature: scorecard.loc[scorecard["feature"].eq(feature)].copy(deep=True)
            for feature in features
        }
        self.dependency_versions_ = _dependency_versions(self)
        self.intercept_ = alpha
        self.intercept_share_ = intercept_share
        self.beta_by_feature_ = {feature: coefficient_specs[feature].beta for feature in features}
        self._point_lookup_ = point_lookup
        self._duplicate_woe_keys_ = tuple(duplicate_woe)
        return self

    def transform(self, woe_frame: DataFrame) -> DataFrame:
        """Publica columnas de puntos y score total desde un frame WoE ya validado."""
        self._check_fitted()
        pd = _import_pandas()
        np = _import_numpy()
        frame = _as_dataframe(woe_frame, pd, context="transform")
        _validate_unique_columns(frame, error_cls=ScorecardTransformError)
        _validate_transform_columns(
            frame,
            final_woe_columns=self.final_woe_columns_,
            output_columns=(*self.points_columns_, self.score_column),
        )

        result = frame.copy(deep=True)
        unseen_counts: dict[str, int] = {}
        for feature, woe_column, points_column in zip(
            self.final_features_,
            self.final_woe_columns_,
            self.points_columns_,
            strict=True,
        ):
            values = _finite_woe_array(
                frame[woe_column],
                feature=feature,
                woe_column=woe_column,
                np=np,
            )
            points, unseen_count = _points_for_values(
                estimator=self,
                feature=feature,
                values=values,
                beta=self.beta_by_feature_[feature],
            )
            result[points_column] = pd.Series(points, index=frame.index).map(_normalize_point)
            if unseen_count:
                unseen_counts[feature] = unseen_count
                self.log_decision(
                    regla="bin_no_visto",
                    umbral="woe_tabular",
                    valor={"feature": feature, "conteo": unseen_count},
                    accion="calcular_por_formula",
                )

        score = result.loc[:, list(self.points_columns_)].sum(axis=1)
        score = score.map(lambda value: _normalize_float(float(value)))
        score = _apply_score_limits(self, score, pd=pd)
        result[self.score_column] = score.map(lambda value: _normalize_float(float(value)))
        self.unseen_bins_ = dict(unseen_counts)
        return result


@dataclass(frozen=True)
class CoefficientSpec:
    """Coeficiente beta trazable para una feature final."""

    feature: str
    woe_column: str
    beta: float


def _import_pandas() -> Any:
    """Importa pandas localmente y traduce ausencias a un mensaje accionable."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _import_numpy() -> Any:
    """Importa numpy localmente y traduce ausencias a un mensaje accionable."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _validate_runtime_config(estimator: PointsScaler) -> None:
    """Revalida hiperparámetros planos contra ``ScorecardConfig``."""
    try:
        ScorecardConfig(
            pdo=estimator.pdo,
            target_score=estimator.target_score,
            target_odds=estimator.target_odds,
            score_direction=estimator.score_direction,
            intercept_allocation=estimator.intercept_allocation,
            rounding_method=estimator.rounding_method,
            output_suffix=estimator.output_suffix,
            score_column=estimator.score_column,
            min_score=estimator.min_score,
            max_score=estimator.max_score,
            clip=estimator.clip,
            point_overrides=estimator.point_overrides,
        )
    except (ConfigError, ValidationError) as exc:
        raise ConfigError(f"Hiperparámetros inválidos para PointsScaler: {exc}") from exc


def _validate_feature_mapping(
    *,
    final_features: tuple[str, ...],
    final_woe_columns: tuple[str, ...],
    woe_column_map: Mapping[str, str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Valida el mapping 1:1 ``feature -> columna WoE`` preservando orden."""
    if len(final_features) != len(final_woe_columns):
        raise ScorecardFitError(
            "final_features y final_woe_columns deben tener el mismo largo: "
            f"len(final_features)={len(final_features)}, "
            f"len(final_woe_columns)={len(final_woe_columns)}."
        )
    if not final_features:
        raise ScorecardFitError("Scorecard requiere al menos una variable final.")
    if len(set(final_features)) != len(final_features):
        raise ScorecardFitError(f"final_features contiene duplicados: {final_features!r}.")
    if len(set(final_woe_columns)) != len(final_woe_columns):
        raise ScorecardFitError(f"final_woe_columns contiene duplicados: {final_woe_columns!r}.")

    for feature, woe_column in zip(final_features, final_woe_columns, strict=True):
        observed = woe_column_map.get(feature)
        if observed is None:
            raise ScorecardFitError(
                "woe_column_map no contiene una feature final: "
                f"feature='{feature}', disponibles={sorted(woe_column_map)}."
            )
        if observed != woe_column:
            raise ScorecardFitError(
                "woe_column_map no coincide con model.final_woe_columns: "
                f"feature='{feature}', esperado='{woe_column}', observado='{observed}'."
            )
    return final_features, final_woe_columns


def _as_dataframe(df: object, pd: Any, *, context: Literal["fit", "transform"]) -> DataFrame:
    """Valida y copia defensivamente una entrada tabular."""
    if not isinstance(df, pd.DataFrame):
        error_cls = ScorecardFitError if context == "fit" else ScorecardTransformError
        raise error_cls(
            f"PointsScaler.{context} requiere pandas.DataFrame; tipo observado={type(df).__name__}."
        )
    if len(df.index) == 0:
        error_cls = ScorecardFitError if context == "fit" else ScorecardTransformError
        raise error_cls(f"PointsScaler.{context} recibió un DataFrame vacío.")
    return cast(DataFrame, df.copy(deep=True))


def _validate_unique_columns(frame: DataFrame, *, error_cls: type[Exception]) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise error_cls(f"PointsScaler requiere nombres de columnas únicos; duplicadas: {joined}.")


def _normalize_coefficients(coefficients: DataFrame, *, pd: Any) -> DataFrame:
    """Copia, valida columnas mínimas y normaliza betas finitos."""
    frame = _as_dataframe(coefficients, pd, context="fit")
    _validate_unique_columns(frame, error_cls=ScorecardFitError)
    missing = sorted(_REQUIRED_COEFFICIENT_COLUMNS - set(frame.columns))
    if missing:
        raise ScorecardFitError(f"coefficients no contiene columnas requeridas: {missing}.")
    frame["feature"] = frame["feature"].astype(str)
    frame["woe_column"] = frame["woe_column"].astype(str)
    frame["beta"] = [
        _finite_float(value, label="beta", error_cls=ScorecardFitError)
        for value in frame["beta"].tolist()
    ]
    return frame.copy(deep=True)


def _coefficient_specs(
    coefficients: DataFrame,
    *,
    features: tuple[str, ...],
    woe_columns: tuple[str, ...],
) -> tuple[dict[str, CoefficientSpec], float]:
    """Extrae betas finales y el intercepto único ``alpha``."""
    intercept_mask = coefficients["feature"].eq(_INTERCEPT_FEATURE) | coefficients["woe_column"].eq(
        _INTERCEPT_WOE_COLUMN
    )
    intercept_rows = coefficients.loc[intercept_mask]
    if len(intercept_rows.index) > 1:
        raise ScorecardFitError("coefficients contiene más de una fila de intercepto.")
    alpha = 0.0
    if len(intercept_rows.index) == 1:
        alpha = _normalize_float(float(intercept_rows["beta"].iloc[0]))

    non_intercept = coefficients.loc[~intercept_mask].copy(deep=True)
    specs: dict[str, CoefficientSpec] = {}
    for feature, woe_column in zip(features, woe_columns, strict=True):
        match = non_intercept.loc[
            non_intercept["feature"].eq(feature) | non_intercept["woe_column"].eq(woe_column)
        ]
        if len(match.index) == 0:
            raise ScorecardFitError(f"Feature final sin coeficiente: feature='{feature}'.")
        if len(match.index) > 1:
            raise ScorecardFitError(f"Coeficiente ambiguo para feature='{feature}'.")
        row = match.iloc[0]
        observed_feature = str(row["feature"])
        observed_woe = str(row["woe_column"])
        if observed_feature != feature or observed_woe != woe_column:
            raise ScorecardFitError(
                "La fila de coefficients no coincide con el mapping final: "
                f"feature='{feature}', woe_column='{woe_column}', "
                f"observado=('{observed_feature}', '{observed_woe}')."
            )
        specs[feature] = CoefficientSpec(
            feature=feature,
            woe_column=woe_column,
            beta=_normalize_float(float(row["beta"])),
        )
    return specs, alpha


def _copy_binning_tables(
    binning_tables: Mapping[str, DataFrame],
    *,
    features: tuple[str, ...],
    pd: Any,
    np: Any,
) -> dict[str, DataFrame]:
    """Copia y valida tablas WoE por feature final."""
    tables: dict[str, DataFrame] = {}
    for feature in features:
        if feature not in binning_tables:
            raise ScorecardFitError(
                "Feature final sin tabla de binning: "
                f"feature='{feature}', disponibles={sorted(binning_tables)}."
            )
        table = _as_dataframe(binning_tables[feature], pd, context="fit")
        _validate_unique_columns(table, error_cls=ScorecardFitError)
        missing = sorted(_REQUIRED_BINNING_COLUMNS - set(table.columns))
        if missing:
            raise ScorecardFitError(
                f"binning_tables['{feature}'] no contiene columnas requeridas: {missing}."
            )
        model_rows = table.loc[~_total_row_mask(table)].copy(deep=True)
        if model_rows.empty:
            raise ScorecardFitError(f"binning_tables['{feature}'] no contiene bins publicables.")
        woe = pd.to_numeric(model_rows["WoE"], errors="coerce")
        finite = np.isfinite(woe.to_numpy(dtype="float64", copy=True))
        if not bool(finite.all()):
            observed = model_rows.loc[~finite, "WoE"].iloc[0]
            raise ScorecardFitError(
                "WoE no finito en tabla de binning: "
                f"feature='{feature}', valor observado={observed!r}."
            )
        model_rows["WoE"] = [_normalize_float(float(value)) for value in woe.tolist()]
        model_rows["Bin"] = model_rows["Bin"].astype(str)
        tables[feature] = model_rows.copy(deep=True)
    return tables


def _total_row_mask(table: DataFrame) -> Series:
    """Identifica filas auxiliares de totales sin depender de bytes del backend."""
    index_is_total = table.index.astype(str) == "Totals"
    bin_is_total = table["Bin"].astype(str).isin({"Totals", "Total"})
    return cast(Series, index_is_total | bin_is_total)


def _scorecard_rows(
    *,
    estimator: PointsScaler,
    features: tuple[str, ...],
    woe_columns: tuple[str, ...],
    coefficients: Mapping[str, CoefficientSpec],
    tables: Mapping[str, DataFrame],
    overrides: Mapping[tuple[str, str], PointOverrideConfig],
    factor: float,
    offset_share: float,
    intercept_share: float,
) -> list[dict[str, object]]:
    """Construye filas de puntos en orden estable feature/bin."""
    rows: list[dict[str, object]] = []
    for feature, woe_column in zip(features, woe_columns, strict=True):
        beta = coefficients[feature].beta
        table = tables[feature]
        for bin_index, row in enumerate(table.to_dict(orient="records")):
            bin_label = str(row["Bin"])
            woe = _finite_float(row["WoE"], label="WoE", error_cls=ScorecardFitError)
            raw_points = _raw_points(
                direction=estimator.score_direction,
                factor=factor,
                offset_share=offset_share,
                beta=beta,
                woe=woe,
                intercept_share=intercept_share,
            )
            points = _published_points(raw_points, estimator.rounding_method)
            source = "binning_table"
            override = overrides.get((feature, bin_label))
            if override is not None:
                previous = points
                points = _normalize_point(override.points)
                source = "override"
                estimator.log_decision(
                    regla="point_override",
                    umbral=override.reason,
                    valor={
                        "feature": feature,
                        "bin_label": bin_label,
                        "puntos_anterior": previous,
                        "puntos_nuevo": points,
                    },
                    accion="aplicar_override",
                )
            rows.append(
                {
                    "feature": feature,
                    "woe_column": woe_column,
                    "bin_label": bin_label,
                    "bin_index": int(bin_index),
                    "woe": woe,
                    "beta": beta,
                    "intercept_share": intercept_share,
                    "raw_points": raw_points,
                    "points": points,
                    "rounding_delta": _normalize_float(float(points) - raw_points),
                    "source": source,
                }
            )
    return rows


def _override_map(
    overrides: tuple[PointOverrideConfig, ...],
) -> dict[tuple[str, str], PointOverrideConfig]:
    """Indexa overrides ya validados por config."""
    return {(override.feature, override.bin_label): override for override in overrides}


def _raw_points(
    *,
    direction: ScoreDirection,
    factor: float,
    offset_share: float,
    beta: float,
    woe: float,
    intercept_share: float,
) -> float:
    """Calcula puntos crudos para la dirección de score configurada."""
    component = _normalize_float((beta * woe) + intercept_share)
    if direction == "higher_is_lower_risk":
        value = offset_share - factor * component
    else:
        value = offset_share + factor * component
    if not math.isfinite(value):
        raise ScorecardFitError(f"raw_points no es finito: valor={value!r}.")
    return _normalize_float(value)


def _published_points(raw_points: float, method: RoundingMethod) -> float | int:
    """Aplica el redondeo configurado de forma determinista."""
    if method == "none":
        return _normalize_float(raw_points)
    if method == "nearest_integer":
        return round(raw_points)
    if method == "floor_integer":
        return math.floor(raw_points)
    return math.ceil(raw_points)


def _point_lookup(
    scorecard: DataFrame,
) -> tuple[dict[tuple[str, float], float | int], list[dict[str, object]]]:
    """Construye lookup determinista ``(feature, woe) -> points`` con primer bin ganador."""
    lookup: dict[tuple[str, float], float | int] = {}
    duplicate_rows: list[dict[str, object]] = []
    for row in scorecard.to_dict(orient="records"):
        feature = str(row["feature"])
        woe = _normalize_float(float(row["woe"]))
        key = (feature, woe)
        if key in lookup:
            duplicate_rows.append(
                {
                    "feature": feature,
                    "woe": woe,
                    "bin_label": str(row["bin_label"]),
                    "points_usados": lookup[key],
                    "points_descartados": cast(float | int, row["points"]),
                }
            )
            continue
        lookup[key] = cast(float | int, row["points"])
    return lookup, duplicate_rows


def _validate_transform_columns(
    frame: DataFrame,
    *,
    final_woe_columns: tuple[str, ...],
    output_columns: tuple[str, ...],
) -> None:
    """Valida columnas de entrada y evita sobrescrituras de salida."""
    missing = [column for column in final_woe_columns if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise ScorecardTransformError(f"Faltan columnas WoE finales para scorecard: {joined}.")
    collisions = [column for column in output_columns if column in frame.columns]
    if collisions:
        joined = ", ".join(f"'{column}'" for column in collisions)
        raise ScorecardTransformError(
            f"Scorecard.transform no sobrescribe columnas existentes; colisiones: {joined}."
        )


def _finite_woe_array(
    series: Series,
    *,
    feature: str,
    woe_column: str,
    np: Any,
) -> NDArrayFloat:
    """Devuelve valores WoE finitos como float64."""
    values = series.to_numpy(dtype="float64", copy=True)
    finite = np.isfinite(values)
    if not bool(finite.all()):
        observed = series.loc[~finite].iloc[0]
        raise ScorecardTransformError(
            "Scorecard.transform recibió WoE no finita: "
            f"feature='{feature}', columna='{woe_column}', valor observado={observed!r}."
        )
    return cast(NDArrayFloat, np.asarray([_normalize_float(float(value)) for value in values]))


def _points_for_values(
    *,
    estimator: PointsScaler,
    feature: str,
    values: NDArrayFloat,
    beta: float,
) -> tuple[list[float | int], int]:
    """Mapea WoE a puntos tabulares o por fórmula directa para bins no vistos."""
    points: list[float | int] = []
    unseen_count = 0
    lookup = estimator._point_lookup_
    for value in values.tolist():
        woe = _normalize_float(float(value))
        key = (feature, woe)
        if key in lookup:
            points.append(lookup[key])
            continue
        unseen_count += 1
        raw_points = _raw_points(
            direction=estimator.score_direction_,
            factor=estimator.factor_,
            offset_share=_normalize_float(estimator.offset_ / len(estimator.final_features_)),
            beta=beta,
            woe=woe,
            intercept_share=estimator.intercept_share_,
        )
        points.append(_published_points(raw_points, estimator.rounding_method_))
    return points, unseen_count


def _apply_score_limits(estimator: PointsScaler, score: Series, *, pd: Any) -> Series:
    """Aplica o audita límites de score según ``clip``."""
    lower = estimator.min_score
    upper = estimator.max_score
    if lower is None and upper is None:
        return score
    below = score.lt(lower) if lower is not None else pd.Series(False, index=score.index)
    above = score.gt(upper) if upper is not None else pd.Series(False, index=score.index)
    affected = int((below | above).sum())
    if affected == 0:
        return score
    if estimator.clip:
        clipped = score.clip(lower=lower, upper=upper)
        estimator.log_decision(
            regla="score_clip",
            umbral={"min_score": lower, "max_score": upper},
            valor={"filas_afectadas": affected},
            accion="recortar_score",
        )
        return clipped.map(lambda value: _normalize_float(float(value)))
    estimator.log_decision(
        regla="score_fuera_de_rango",
        umbral={"min_score": lower, "max_score": upper},
        valor={
            "filas_afectadas": affected,
            "min_observado": _normalize_float(float(score.min())),
            "max_observado": _normalize_float(float(score.max())),
        },
        accion="publicar_sin_recorte",
    )
    return score


def _normalize_float_frame(frame: DataFrame, *, pd: Any) -> DataFrame:
    """Normaliza ``-0.0`` en columnas float sin alterar enteros publicados."""
    result = frame.copy(deep=True)
    for column in result.columns:
        if pd.api.types.is_float_dtype(result[column]):
            result[column] = result[column].map(lambda value: _normalize_float(float(value)))
    return result


def _dependency_versions(estimator: PointsScaler) -> dict[str, str]:
    """Publica versiones que afectan el scorecard; sklearn sólo si está en el MRO."""
    modules = {
        "numpy": "numpy",
        "pandas": "pandas",
    }
    if _inherits_sklearn_base(estimator):
        modules["scikit-learn"] = "sklearn"

    versions: dict[str, str] = {}
    for public_name, module_name in modules.items():
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
        versions[public_name] = str(getattr(module, "__version__", "unknown"))
    return {name: versions[name] for name in sorted(versions)}


def _inherits_sklearn_base(estimator: PointsScaler) -> bool:
    """Detecta herencia sklearn sin importar nuevos módulos."""
    return any(cls.__module__.startswith("sklearn.") for cls in type(estimator).mro())


def _finite_float(
    value: object,
    *,
    label: str,
    error_cls: type[Exception],
) -> float:
    """Convierte un escalar a float finito normalizado."""
    try:
        candidate = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise error_cls(f"{label} no es numérico: {value!r}.") from exc
    if not math.isfinite(candidate):
        raise error_cls(f"{label} no es finito: {candidate!r}.")
    return _normalize_float(candidate)


def _normalize_point(value: float | int) -> float | int:
    """Normaliza ``-0.0`` en puntos sin convertir enteros."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return _normalize_float(float(value))


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` sin redondear otros valores."""
    if value == 0.0:
        return 0.0
    return value
