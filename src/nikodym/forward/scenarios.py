"""Ponderación de escenarios y reversión TTC forward-looking (SDD-20 B20.5).

``ScenarioWeighting`` valida escenarios macro en runtime, bloquea el anti-patrón de construir un
escenario medio de inputs y pondera únicamente outputs económicos ya calculados por escenario. El
módulo mantiene liviano ``import nikodym.forward``: ``pandas`` se importa solo dentro de métodos de
ejecución.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
import warnings
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias, cast

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import MissingDependencyError
from nikodym.forward.config import ForwardConfig
from nikodym.forward.exceptions import (
    ForwardInputError,
    ForwardPredictionError,
    ForwardScenarioError,
)

if TYPE_CHECKING:
    import pandas as pd

    DataFrame: TypeAlias = pd.DataFrame
else:
    DataFrame: TypeAlias = Any

__all__ = ["ScenarioWeighting"]

_RESERVED_SCENARIOS: frozenset[str] = frozenset({"mean", "average", "weighted_mean_input"})
_DEFAULT_SCENARIO_WEIGHTS: Mapping[str, float] = {"base": 0.60, "adverse": 0.30, "severe": 0.10}
_SCENARIO_WEIGHT_COLUMNS: tuple[str, ...] = (
    "scenario",
    "weight",
    "is_default",
    "source",
    "description",
)
_PROBABILITY_COLUMNS: tuple[str, ...] = (
    "pd_marginal",
    "pd_cumulative",
    "hazard",
    "survival",
    "lgd",
)
_IDENTITY_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "partition",
    "source_model",
    "method",
    "pd_source",
)
_ANCHOR_KEY_COLUMNS: tuple[str, ...] = (*_IDENTITY_COLUMNS, "period")
_CURVE_KEY_COLUMNS: tuple[str, ...] = (*_IDENTITY_COLUMNS, "scenario")
_WARNING_FALTA_DATO_FWD_4 = (
    "FALTA-DATO-FWD-4: ttc_anchor='input_term_structure' no trae pd_basis='ttc' "
    "resuelto; se usará como ancla TTC con base PIT/desconocida explícitamente advertida."
)


class ScenarioWeighting:
    """Valida escenarios, aplica reversión TTC y pondera outputs por escenario."""

    config_cls: ClassVar[type[ForwardConfig]] = ForwardConfig

    def __init__(self, *, config: ForwardConfig | Mapping[str, Any]) -> None:
        """Asigna configuración forward y valida pesos sin cargar dependencias pesadas."""
        cfg = config if isinstance(config, ForwardConfig) else ForwardConfig.model_validate(config)
        weights = _scenario_weights_from_config(cfg)
        self.config = cfg
        self.scenario_weights_ = dict(weights)
        self.weights_ = dict(weights)
        self.weights = dict(weights)
        self._default_scenario_set = _is_default_scenario_set(cfg)

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig | Mapping[str, Any]) -> ScenarioWeighting:
        """Construye el ponderador desde ``ForwardConfig`` o un mapping equivalente."""
        if not isinstance(cfg, ForwardConfig):
            cfg = ForwardConfig.model_validate(cfg)
        return cls(config=cfg)

    def scenario_weight_frame(self) -> DataFrame:
        """Publica ``scenario_weights`` tidy con fuente y descripción auditables."""
        pd = _import_pandas()
        rows: list[dict[str, Any]] = []
        for scenario in self.config.scenarios.scenarios:
            is_default = self._default_scenario_set
            rows.append(
                {
                    "scenario": scenario.name,
                    "weight": _clean_float(float(scenario.weight), error_cls=ForwardScenarioError),
                    "is_default": is_default,
                    "source": "default_a_confirmar" if is_default else "config",
                    "description": scenario.description,
                }
            )
        return cast("DataFrame", pd.DataFrame.from_records(rows, columns=_SCENARIO_WEIGHT_COLUMNS))

    def validate_macro_projection(self, frame: DataFrame) -> None:
        """Valida una proyección macro tidy y bloquea escenarios medios."""
        pd = _import_pandas()
        copied = _as_dataframe(
            frame,
            pd=pd,
            field_name="macro_projection",
            error_cls=ForwardScenarioError,
        )
        _reject_weighted_mean_columns(copied)
        _require_columns(copied, ("scenario",), error_cls=ForwardScenarioError)
        _validate_scenario_frame(copied, weights=self.scenario_weights_, cfg=self.config)
        if "scenario_weight" in copied.columns:
            _validate_scenario_weight_column(
                copied,
                weights=self.scenario_weights_,
                cfg=self.config,
            )
        for column in ("projected_value", "model_value", "shock_value"):
            if column in copied.columns:
                _finite_numeric_column(copied[column], field_name=column)

    def apply_ttc_reversion(
        self,
        forward_term_structure: DataFrame,
        *,
        ttc_anchor: DataFrame,
    ) -> DataFrame:
        """Mezcla hazard PIT con ancla TTC en escala logit y recompone la curva lifetime."""
        pd = _import_pandas()
        forward = _as_dataframe(
            forward_term_structure,
            pd=pd,
            field_name="forward_term_structure",
            error_cls=ForwardInputError,
        )
        anchor = _as_dataframe(
            ttc_anchor,
            pd=pd,
            field_name="ttc_anchor",
            error_cls=ForwardInputError,
        )
        _reject_weighted_mean_columns(forward)
        _require_columns(forward, ("scenario", "period"), error_cls=ForwardPredictionError)
        _validate_scenario_frame(forward, weights=self.scenario_weights_, cfg=self.config)
        _ensure_hazard_column(forward, pd=pd, error_cls=ForwardPredictionError)

        cfg = self.config
        if not cfg.ttc_reversion.enabled or cfg.ttc_reversion.method == "none":
            normalized = _normalize_frame(forward)
            _validate_term_structure_invariants(normalized, cfg=cfg)
            return _sort_term_structure(normalized, cfg=cfg)

        _require_columns(anchor, ("period",), error_cls=ForwardPredictionError)
        _ensure_hazard_column(anchor, pd=pd, error_cls=ForwardPredictionError)
        _warn_if_anchor_basis_unresolved(anchor, cfg=cfg)
        if cfg.ttc_reversion.ttc_anchor == "historical_mean":
            anchor = _historical_mean_anchor(anchor, cfg=cfg)
        anchor_lookup = _anchor_lookup(forward, anchor)
        working = forward.copy(deep=True)
        lambdas: list[float] = []
        basis_states: list[str] = []
        hazards: list[float] = []
        for row in working.itertuples(index=False):
            row_any = cast("Any", row)
            period = _positive_int(row_any.period, field_name="period")
            weight = _ttc_lambda(period, cfg=cfg)
            pit_hazard = _probability(
                float(row_any.hazard),
                field_name="hazard PIT",
                tol=cfg.validation.probability_tol,
                error_cls=ForwardPredictionError,
            )
            ttc_hazard = anchor_lookup[_anchor_key(row_any, anchor_lookup.key_columns)]
            hazards.append(_blend_hazard(pit_hazard, ttc_hazard, weight, cfg=cfg))
            lambdas.append(weight)
            basis_states.append(_basis_state(weight))

        working["hazard"] = hazards
        working["ttc_reversion_weight"] = lambdas
        working["basis_state"] = basis_states
        working["pd_basis"] = ["ttc" if state == "ttc" else "pit" for state in basis_states]
        recomposed = _recompose_lifetime(working, cfg=cfg)
        normalized = _normalize_frame(recomposed)
        _validate_term_structure_invariants(normalized, cfg=cfg)
        return _sort_term_structure(normalized, cfg=cfg)

    def weight_outputs(
        self,
        output_by_scenario: DataFrame,
        *,
        value_cols: tuple[str, ...],
        group_cols: tuple[str, ...],
    ) -> DataFrame:
        """Pondera outputs por escenario sin promediar inputs macroeconómicos."""
        pd = _import_pandas()
        copied = _as_dataframe(
            output_by_scenario,
            pd=pd,
            field_name="output_by_scenario",
            error_cls=ForwardScenarioError,
        )
        _reject_weighted_mean_columns(copied)
        _require_columns(copied, ("scenario",), error_cls=ForwardScenarioError)
        _validate_weight_columns(copied, value_cols=value_cols, group_cols=group_cols)
        _validate_scenario_frame(copied, weights=self.scenario_weights_, cfg=self.config)
        _validate_group_coverage(copied, group_cols=group_cols, weights=self.scenario_weights_)
        working = copied.copy(deep=True)
        scenario_weights = {
            scenario: self.scenario_weights_[scenario]
            for scenario in _observed_scenarios(working["scenario"])
        }
        working["_scenario_weight"] = [
            scenario_weights[str(scenario)] for scenario in working["scenario"].tolist()
        ]
        for column in value_cols:
            values = _finite_numeric_column(working[column], field_name=column)
            working[column] = [
                value * weight
                for value, weight in zip(values, working["_scenario_weight"], strict=True)
            ]

        if group_cols:
            grouped = (
                working.groupby(list(group_cols), sort=False, dropna=False)[list(value_cols)]
                .sum()
                .reset_index()
            )
            result = grouped.loc[:, [*group_cols, *value_cols]].copy(deep=True)
        else:
            result = cast(
                "DataFrame",
                pd.DataFrame([{column: float(working[column].sum()) for column in value_cols}]),
            )
        return _normalize_frame(result)


def _scenario_weights_from_config(cfg: ForwardConfig) -> dict[str, float]:
    names: list[str] = []
    weights: dict[str, float] = {}
    for scenario in cfg.scenarios.scenarios:
        name = str(scenario.name).strip()
        if not name:
            raise ForwardScenarioError("scenario.name no puede estar vacío.")
        names.append(name)
        if name.lower() in _RESERVED_SCENARIOS and cfg.scenarios.forbid_mean_scenario:
            raise ForwardScenarioError(f"Escenario medio reservado no permitido: {name!r}.")
        if name in weights:
            raise ForwardScenarioError(f"Escenario duplicado en config: {name!r}.")
        weight = _non_negative_float(float(scenario.weight), error_cls=ForwardScenarioError)
        weights[name] = weight
    if cfg.scenarios.require_at_least_three and len(names) < 3:
        raise ForwardScenarioError("Se requieren al menos tres escenarios forward-looking.")
    total = math.fsum(weights.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=cfg.validation.weight_sum_tol):
        raise ForwardScenarioError(
            f"Los pesos de escenarios deben sumar 1; suma observada={total!r}."
        )
    return weights


def _is_default_scenario_set(cfg: ForwardConfig) -> bool:
    observed = {scenario.name: float(scenario.weight) for scenario in cfg.scenarios.scenarios}
    if observed != dict(_DEFAULT_SCENARIO_WEIGHTS):
        return False
    return all(
        not scenario.shocks and scenario.macro_path_path is None and scenario.description is None
        for scenario in cfg.scenarios.scenarios
    )


def _reject_weighted_mean_columns(frame: DataFrame) -> None:
    if any(str(column).strip().lower() == "weighted_mean_input" for column in frame.columns):
        raise ForwardScenarioError(
            "weighted_mean_input está prohibido: se ponderan outputs, no inputs macro."
        )


def _require_columns(
    frame: DataFrame,
    columns: Sequence[str],
    *,
    error_cls: type[Exception],
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise error_cls(f"Faltan columnas requeridas: {missing}.")


def _validate_scenario_frame(
    frame: DataFrame,
    *,
    weights: Mapping[str, float],
    cfg: ForwardConfig,
) -> None:
    observed = _observed_scenarios(frame["scenario"])
    lowered = {scenario.lower() for scenario in observed}
    reserved = sorted(lowered & _RESERVED_SCENARIOS)
    if reserved and cfg.scenarios.forbid_mean_scenario:
        raise ForwardScenarioError(
            f"Escenario medio prohibido: {reserved}; se ponderan outputs por escenario."
        )
    unknown = sorted(set(observed) - set(weights))
    if unknown:
        raise ForwardScenarioError(f"Escenarios no configurados en input: {unknown}.")
    missing = sorted(
        scenario
        for scenario, weight in weights.items()
        if weight > 0.0 and scenario not in observed
    )
    if missing:
        raise ForwardScenarioError(f"Faltan escenarios con peso positivo en input: {missing}.")


def _validate_scenario_weight_column(
    frame: DataFrame,
    *,
    weights: Mapping[str, float],
    cfg: ForwardConfig,
) -> None:
    for scenario, group in frame.groupby("scenario", sort=False, dropna=False):
        configured = weights[str(scenario)]
        observed = {
            _non_negative_float(float(value), error_cls=ForwardScenarioError)
            for value in group["scenario_weight"].dropna().tolist()
        }
        if len(observed) > 1:
            raise ForwardScenarioError(f"scenario_weight inconsistente para {scenario!r}.")
        if observed:
            value = observed.pop()
            if not math.isclose(
                value,
                configured,
                rel_tol=0.0,
                abs_tol=cfg.validation.weight_sum_tol,
            ):
                raise ForwardScenarioError(
                    "scenario_weight no coincide con config: "
                    f"scenario={scenario!r}, observado={value}, esperado={configured}."
                )


def _validate_group_coverage(
    frame: DataFrame,
    *,
    group_cols: tuple[str, ...],
    weights: Mapping[str, float],
) -> None:
    positive = {scenario for scenario, weight in weights.items() if weight > 0.0}
    if not group_cols:
        return
    for key, group in frame.groupby(list(group_cols), sort=False, dropna=False):
        observed = set(_observed_scenarios(group["scenario"]))
        missing = sorted(positive - observed)
        if missing:
            raise ForwardScenarioError(
                f"Faltan escenarios con peso positivo para grupo {key!r}: {missing}."
            )


def _validate_weight_columns(
    frame: DataFrame,
    *,
    value_cols: tuple[str, ...],
    group_cols: tuple[str, ...],
) -> None:
    if not value_cols:
        raise ForwardScenarioError("value_cols debe contener al menos una columna.")
    if "scenario" in group_cols:
        raise ForwardScenarioError("group_cols no puede incluir 'scenario'.")
    duplicated = set(value_cols) & set(group_cols)
    if duplicated:
        raise ForwardScenarioError(f"value_cols y group_cols se solapan: {sorted(duplicated)}.")
    _require_columns(frame, (*value_cols, *group_cols), error_cls=ForwardScenarioError)


def _observed_scenarios(series: Any) -> tuple[str, ...]:
    values: list[str] = []
    for raw in series.tolist():
        if _is_missing(raw):
            raise ForwardScenarioError("scenario contiene valores nulos.")
        scenario = str(raw).strip()
        if not scenario:
            raise ForwardScenarioError("scenario contiene valores vacíos.")
        values.append(scenario)
    return tuple(dict.fromkeys(values))


def _historical_mean_anchor(anchor: DataFrame, *, cfg: ForwardConfig) -> DataFrame:
    """Colapsa el ancla TTC a la media histórica de hazards por curva (ancla plana).

    Implementa ``ttc_anchor='historical_mean'`` de verdad: en vez de revertir hacia la
    term-structure de entrada período a período (``input_term_structure``), la PIT revierte
    hacia un ancla TTC **plana** igual a la media aritmética de los hazards de cada curva. El
    ancla deja de ser la curva base y pasa a ser una media de largo plazo real, coherente con
    la etiqueta ``historical_mean`` que publican card/diagnostics/log. La media se computa por
    curva (columnas de identidad, sin ``period``) y se difunde a todos sus períodos.
    """
    working = anchor.copy(deep=True)
    identity_columns = tuple(column for column in _IDENTITY_COLUMNS if column in working.columns)
    keys = [_row_key(cast("Any", row), identity_columns) for row in working.itertuples(index=False)]
    hazards = [
        _probability(
            float(value),
            field_name="hazard TTC histórico",
            tol=cfg.validation.probability_tol,
            error_cls=ForwardPredictionError,
        )
        for value in working["hazard"].tolist()
    ]
    grouped: dict[tuple[Any, ...], list[float]] = {}
    for key, hazard in zip(keys, hazards, strict=True):
        grouped.setdefault(key, []).append(hazard)
    means = {
        key: _probability(
            math.fsum(values) / len(values),
            field_name="hazard TTC medio",
            tol=cfg.validation.probability_tol,
            error_cls=ForwardPredictionError,
        )
        for key, values in grouped.items()
    }
    working["hazard"] = [means[key] for key in keys]
    return working


def _anchor_lookup(forward: DataFrame, anchor: DataFrame) -> _AnchorLookup:
    key_columns = tuple(
        column
        for column in _ANCHOR_KEY_COLUMNS
        if column in forward.columns and column in anchor.columns
    )
    values: dict[tuple[Any, ...], float] = {}
    duplicates: set[tuple[Any, ...]] = set()
    for row in anchor.itertuples(index=False):
        row_any = cast("Any", row)
        key = _anchor_key(row_any, key_columns)
        if key in values:
            duplicates.add(key)
        values[key] = _probability(
            float(row_any.hazard),
            field_name="hazard TTC",
            tol=1e-10,
            error_cls=ForwardPredictionError,
        )
    if duplicates:
        raise ForwardPredictionError(
            f"ttc_anchor contiene llaves duplicadas: {sorted(duplicates)!r}."
        )
    missing = [
        _anchor_key(cast("Any", row), key_columns)
        for row in forward.itertuples(index=False)
        if _anchor_key(cast("Any", row), key_columns) not in values
    ]
    if missing:
        raise ForwardPredictionError(f"ttc_anchor no cubre llaves forward: {missing[:5]!r}.")
    return _AnchorLookup(values=values, key_columns=key_columns)


class _AnchorLookup:
    """Lookup interno de hazards TTC por llave de curva."""

    def __init__(
        self,
        *,
        values: Mapping[tuple[Any, ...], float],
        key_columns: tuple[str, ...],
    ) -> None:
        self.values = dict(values)
        self.key_columns = key_columns

    def __getitem__(self, key: tuple[Any, ...]) -> float:
        return float(self.values[key])


def _anchor_key(row: Any, key_columns: Sequence[str]) -> tuple[Any, ...]:
    return tuple(_key_value(getattr(row, column)) for column in key_columns)


def _warn_if_anchor_basis_unresolved(anchor: DataFrame, *, cfg: ForwardConfig) -> None:
    if cfg.ttc_reversion.ttc_anchor != "input_term_structure":
        return
    if "pd_basis" not in anchor.columns:
        warnings.warn(_WARNING_FALTA_DATO_FWD_4, RuntimeWarning, stacklevel=2)
        return
    observed = {
        str(value).strip().lower()
        for value in anchor["pd_basis"].dropna().tolist()
        if str(value).strip()
    }
    if observed != {"ttc"}:
        warnings.warn(_WARNING_FALTA_DATO_FWD_4, RuntimeWarning, stacklevel=2)


def _ttc_lambda(period: int, *, cfg: ForwardConfig) -> float:
    reasonable_supportable = cfg.ttc_reversion.reasonable_supportable_periods
    reversion = cfg.ttc_reversion.reversion_periods
    if period <= reasonable_supportable:
        return 1.0
    if period <= reasonable_supportable + reversion:
        return _clean_float(max(0.0, 1.0 - (period - reasonable_supportable) / reversion))
    return 0.0


def _blend_hazard(
    pit_hazard: float,
    ttc_hazard: float,
    weight: float,
    *,
    cfg: ForwardConfig,
) -> float:
    del cfg
    if weight == 1.0:
        return pit_hazard
    if weight == 0.0:
        return ttc_hazard
    blended = weight * _logit(pit_hazard) + (1.0 - weight) * _logit(ttc_hazard)
    return _sigmoid(blended)


def _basis_state(weight: float) -> str:
    if weight == 1.0:
        return "pit"
    if weight == 0.0:
        return "ttc"
    return "blended"


def _ensure_hazard_column(frame: DataFrame, *, pd: Any, error_cls: type[Exception]) -> None:
    if "hazard" in frame.columns:
        frame["hazard"] = [
            _probability(
                float(value),
                field_name="hazard",
                tol=1e-10,
                error_cls=error_cls,
            )
            for value in frame["hazard"].tolist()
        ]
        return
    _require_columns(frame, ("pd_marginal",), error_cls=error_cls)
    working = frame.copy(deep=True)
    working["_ordinal"] = range(len(working.index))
    key_columns = tuple(column for column in _CURVE_KEY_COLUMNS if column in working.columns)
    if "scenario" not in key_columns and "pd_basis" not in working.columns:
        key_columns = tuple(column for column in _IDENTITY_COLUMNS if column in working.columns)
    working["_curve_key"] = [
        _row_key(cast("Any", row), key_columns) for row in working.itertuples(index=False)
    ]
    working = working.sort_values(["_curve_key", "period", "_ordinal"], kind="mergesort")
    hazards: dict[int, float] = {}
    for _key, group in working.groupby("_curve_key", sort=False, dropna=False):
        previous_survival = 1.0
        previous_period = 0
        for _index, row in group.iterrows():
            period = _positive_int(row["period"], field_name="period")
            if period <= previous_period:
                raise error_cls("period debe crecer estrictamente para derivar hazard.")
            pd_marginal = _probability(
                float(row["pd_marginal"]),
                field_name="pd_marginal",
                tol=1e-10,
                error_cls=error_cls,
            )
            if previous_survival <= 1e-10 and pd_marginal > 1e-10:
                raise error_cls("hazard ausente no derivable: survival(t-1) es cero.")
            hazard = 0.0 if previous_survival <= 1e-10 else pd_marginal / previous_survival
            ordinal = int(row["_ordinal"])
            hazards[ordinal] = _probability(
                hazard,
                field_name="hazard",
                tol=1e-10,
                error_cls=error_cls,
            )
            previous_survival = _clean_float(previous_survival * (1.0 - hazards[ordinal]))
            previous_period = period
    frame["hazard"] = [hazards[position] for position in range(len(frame.index))]


def _recompose_lifetime(frame: DataFrame, *, cfg: ForwardConfig) -> DataFrame:
    working = frame.copy(deep=True)
    working["_ordinal"] = range(len(working.index))
    curve_columns = tuple(column for column in _CURVE_KEY_COLUMNS if column in working.columns)
    working["_curve_key"] = [
        _row_key(cast("Any", row), curve_columns) for row in working.itertuples(index=False)
    ]
    working = _sort_term_structure(working, cfg=cfg)
    working["_curve_key"] = [
        _row_key(cast("Any", row), curve_columns) for row in working.itertuples(index=False)
    ]
    for _key, group in working.groupby("_curve_key", sort=False, dropna=False):
        previous_survival = 1.0
        previous_period = 0
        for index, row in group.iterrows():
            period = _positive_int(row["period"], field_name="period")
            if period <= previous_period:
                raise ForwardPredictionError("period debe crecer estrictamente por curva.")
            hazard = _probability(
                float(row["hazard"]),
                field_name="hazard",
                tol=cfg.validation.probability_tol,
                error_cls=ForwardPredictionError,
            )
            pd_marginal = _clean_float(previous_survival * hazard)
            survival = _clean_float(previous_survival * (1.0 - hazard))
            pd_cumulative = _clean_float(1.0 - survival)
            working.at[index, "pd_marginal"] = pd_marginal
            working.at[index, "survival"] = survival
            working.at[index, "pd_cumulative"] = pd_cumulative
            previous_survival = survival
            previous_period = period
    return working.drop(columns=["_curve_key", "_ordinal"], errors="ignore")


def _sort_term_structure(frame: DataFrame, *, cfg: ForwardConfig) -> DataFrame:
    working = frame.copy(deep=True)
    scenario_rank = {scenario.name: index for index, scenario in enumerate(cfg.scenarios.scenarios)}
    for column in ("source_model", "row_id", "segment", "partition", "method", "pd_source"):
        if column in working.columns:
            working[f"_sort_{column}"] = [_sort_value(value) for value in working[column].tolist()]
        else:
            working[f"_sort_{column}"] = ""
    if "scenario" in working.columns:
        working["_sort_scenario"] = [
            scenario_rank.get(str(value), len(scenario_rank))
            for value in working["scenario"].tolist()
        ]
    else:
        working["_sort_scenario"] = 0
    if "_ordinal" not in working.columns:
        working["_ordinal"] = range(len(working.index))
    sort_columns = [
        "_sort_source_model",
        "_sort_row_id",
        "_sort_segment",
        "_sort_partition",
        "_sort_scenario",
        "period",
        "_ordinal",
    ]
    sorted_frame = working.sort_values(sort_columns, kind="mergesort")
    helper_columns = [column for column in sorted_frame.columns if column.startswith("_sort_")]
    helper_columns.extend(
        column for column in ("_ordinal", "_curve_key") if column in sorted_frame.columns
    )
    return sorted_frame.drop(columns=helper_columns).reset_index(drop=True)


def _validate_term_structure_invariants(frame: DataFrame, *, cfg: ForwardConfig) -> None:
    if "scenario" in frame.columns:
        _validate_scenario_frame(frame, weights=_scenario_weights_from_config(cfg), cfg=cfg)
    _validate_probability_columns(frame, cfg=cfg)
    if {"survival", "pd_cumulative"} <= set(frame.columns):
        for row in frame.itertuples(index=False):
            row_any = cast("Any", row)
            expected = _clean_float(1.0 - float(row_any.pd_cumulative))
            observed = float(row_any.survival)
            if not math.isclose(
                observed,
                expected,
                rel_tol=0.0,
                abs_tol=cfg.validation.probability_tol,
            ):
                raise ForwardPredictionError(
                    "survival debe ser 1 - pd_cumulative; "
                    f"observado={observed}, esperado={expected}."
                )
    if "pd_cumulative" in frame.columns:
        _validate_monotonicity(frame, cfg=cfg)


def _validate_probability_columns(frame: DataFrame, *, cfg: ForwardConfig) -> None:
    for column in _PROBABILITY_COLUMNS:
        if column not in frame.columns:
            continue
        for value in frame[column].tolist():
            _probability(
                _float_probability_value(value, field_name=column),
                field_name=column,
                tol=cfg.validation.probability_tol,
                error_cls=ForwardPredictionError,
            )


def _validate_monotonicity(frame: DataFrame, *, cfg: ForwardConfig) -> None:
    previous: dict[tuple[Any, ...], tuple[int, float]] = {}
    key_columns = tuple(column for column in _CURVE_KEY_COLUMNS if column in frame.columns)
    for row in frame.itertuples(index=False):
        row_any = cast("Any", row)
        key = _row_key(row_any, key_columns)
        period = _positive_int(row_any.period, field_name="period")
        cumulative = float(row_any.pd_cumulative)
        prior = previous.get(key)
        if prior is not None:
            prior_period, prior_cumulative = prior
            if period <= prior_period:
                raise ForwardPredictionError("period debe crecer estrictamente por curva.")
            if cumulative < prior_cumulative - cfg.validation.monotonic_tol:
                raise ForwardPredictionError("Monotonicidad rota en pd_cumulative.")
        previous[key] = (period, cumulative)


def _finite_numeric_column(series: Any, *, field_name: str) -> tuple[float, ...]:
    values: list[float] = []
    for raw in series.tolist():
        value = _clean_float(float(raw), error_cls=ForwardScenarioError)
        values.append(value)
    return tuple(values)


def _float_probability_value(value: Any, *, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ForwardPredictionError(
            f"{field_name} contiene valor no numérico o nulo: {value!r}."
        ) from exc


def _positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ForwardPredictionError(f"{field_name} no puede ser booleano.")
    numeric = float(value)
    rounded = round(numeric)
    if not math.isfinite(numeric) or not math.isclose(numeric, rounded, rel_tol=0.0, abs_tol=1e-12):
        raise ForwardPredictionError(f"{field_name} debe ser entero.")
    if rounded < 1:
        raise ForwardPredictionError(f"{field_name} debe ser mayor o igual a 1.")
    return int(rounded)


def _probability(
    value: float,
    *,
    field_name: str,
    tol: float,
    error_cls: type[Exception],
    open_interval: bool = False,
) -> float:
    cleaned = _clean_float(value, error_cls=error_cls)
    if open_interval:
        if cleaned <= 0.0 or cleaned >= 1.0:
            raise error_cls(f"{field_name} debe estar en (0, 1); valor={cleaned}.")
        return cleaned
    if cleaned < -tol or cleaned > 1.0 + tol:
        raise error_cls(f"{field_name} debe estar en [0, 1]; valor={cleaned}.")
    if cleaned <= tol:
        return 0.0
    if cleaned >= 1.0 - tol:
        return 1.0
    return cleaned


def _non_negative_float(value: float, *, error_cls: type[Exception]) -> float:
    cleaned = _clean_float(value, error_cls=error_cls)
    if cleaned < 0.0:
        raise error_cls(f"Valor debe ser no negativo: {cleaned}.")
    return cleaned


def _logit(value: float) -> float:
    probability = _probability(
        value,
        field_name="probabilidad logit",
        tol=0.0,
        error_cls=ForwardPredictionError,
        open_interval=True,
    )
    return math.log(probability / (1.0 - probability))


def _sigmoid(value: float) -> float:
    if not math.isfinite(value):
        raise ForwardPredictionError(f"Overflow logit en reversión TTC: eta={value!r}.")
    if value >= 0.0:
        exp_value = math.exp(-value)
        probability = 1.0 / (1.0 + exp_value)
    else:
        exp_value = math.exp(value)
        probability = exp_value / (1.0 + exp_value)
    if not math.isfinite(probability) or probability <= 0.0 or probability >= 1.0:
        raise ForwardPredictionError(
            f"Probabilidad fuera de rango por overflow logit: eta={value!r}."
        )
    return probability


def _clean_float(value: float, *, error_cls: type[Exception] = ForwardPredictionError) -> float:
    if not math.isfinite(value):
        raise error_cls(f"Valor numérico no finito en forward.scenarios: {value!r}.")
    if value == 0.0:
        return 0.0
    return value


def _normalize_frame(frame: DataFrame) -> DataFrame:
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        zero_mask = copied[column] == 0.0
        if bool(zero_mask.any()):
            copied[column] = copied[column].mask(zero_mask, 0.0)
    return copied


def _row_key(row: Any, key_columns: Sequence[str]) -> tuple[Any, ...]:
    return tuple(_key_value(getattr(row, column)) for column in key_columns)


def _key_value(value: Any) -> Any:
    if _is_missing(value):
        return None
    if isinstance(value, float):
        return _clean_float(value)
    return value


def _sort_value(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value)


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _as_dataframe(
    frame: Any,
    *,
    pd: Any,
    field_name: str,
    error_cls: type[Exception],
) -> DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise error_cls(f"{field_name} requiere un pandas.DataFrame.")
    return cast("DataFrame", frame.copy(deep=True))


def _import_pandas() -> Any:
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("ScenarioWeighting requiere pandas.") from exc
