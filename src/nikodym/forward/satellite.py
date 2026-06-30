"""Modelo satellite Wilson/CreditPortfolioView para PD/LGD forward-looking.

``SatelliteModel`` ajusta coeficientes macroeconómicos en escala logit y los aplica sobre una
term-structure base de ``survival`` o ``markov``. El módulo mantiene liviano ``import
nikodym.forward``: ``pandas``, ``numpy`` y ``statsmodels`` se importan sólo dentro de ``fit``,
``predict`` y helpers de ejecución.

**Experimental (SemVer 0.x).**
"""

# ruff: noqa: UP037

from __future__ import annotations

import importlib
import math
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, Self, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError, NotFittedError
from nikodym.core.mixins import AuditableMixin
from nikodym.forward.config import ForwardConfig, TargetComponent
from nikodym.forward.exceptions import (
    ForwardInputError,
    ForwardPredictionError,
    PitConsistencyError,
    SatelliteModelError,
)
from nikodym.forward.results import SatelliteDiagnostics

if TYPE_CHECKING:
    import numpy as np
    import pandas

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pandas.DataFrame
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]

    class ScenarioWeighting(Protocol):
        """Protocolo mínimo hasta que B20.5 publique ``forward.scenarios``."""

        def validate_macro_projection(self, frame: pandas.DataFrame) -> None:
            """Valida una proyección macro tidy por escenarios."""

else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any

__all__ = ["SatelliteModel"]

_FORECASTING_EXTRA_MESSAGE = "instale nikodym[forecasting]"
_INTERCEPT_NAMES: frozenset[str] = frozenset({"alpha", "intercept", "const", "__alpha__"})
_SEGMENT_ALL = "__all__"
_PD_COMPONENT: TargetComponent = "pd"
_LGD_COMPONENT: TargetComponent = "lgd"
_HAZARD_DERIVED_WARNING = "hazard_derivado_desde_pd_marginal"
_LGD_MISSING_WARNING = "lgd_base_ausente"
_PD_BASIS_ASSUMED_WARNING = "pd_basis_asumida_desde_config"
_PD_BASIS_UNRESOLVED_WARNING = "pd_basis_no_resuelta"
_SATELLITE_METHOD = "wilson_credit_portfolio_view"
_SATELLITE_MODEL_ID = "satellite:wilson:v1"
_FORWARD_TERM_STRUCTURE_COLUMNS: tuple[str, ...] = (
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


@dataclass(frozen=True)
class _PreparedMacroHistory:
    frame: DataFrame
    reference_macro: dict[str, float]


@dataclass(frozen=True)
class _PreparedTermStructure:
    frame: DataFrame
    warnings: tuple[str, ...]
    has_lgd_base: bool


@dataclass(frozen=True)
class _MacroProjectionPrepared:
    frame: DataFrame
    scenarios: tuple[str, ...]
    scenario_weights: dict[str, float]
    deltas: dict[tuple[str, int, str], float]
    macro_model_ids: dict[tuple[str, int], str]
    warning_codes: dict[tuple[str, int], tuple[str, ...]]


class SatelliteModel(AuditableMixin):
    """Ajusta y aplica un modelo satellite Wilson/CreditPortfolioView."""

    config_cls: ClassVar[type[ForwardConfig]] = ForwardConfig

    def __init__(self, *, config: ForwardConfig) -> None:
        """Asigna configuración forward sin importar dependencias estadísticas pesadas."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: ForwardConfig) -> "SatelliteModel":
        """Construye el modelo satellite desde ``ForwardConfig``."""
        if not isinstance(cfg, ForwardConfig):
            cfg = ForwardConfig.model_validate(cfg)
        return cls(config=cfg)

    def fit(
        self,
        historical_term_structure: "pandas.DataFrame",
        macro_history: "pandas.DataFrame",
        *,
        audit: "AuditSink | None" = None,
    ) -> "Self":
        """Ajusta coeficientes PD/LGD o carga una tabla fija auditada."""
        pd = _import_pandas()
        np = _import_numpy()
        if audit is not None:
            self._audit = audit

        cfg = self.config
        prepared_macro = _prepare_macro_history(macro_history, cfg=cfg, pd=pd, np=np)
        prepared_term = _prepare_term_structure(historical_term_structure, cfg=cfg, pd=pd, np=np)
        fit_statistics: dict[str, float | int | str | None]
        if cfg.satellite.mode == "fixed_coefficients":
            coefficients = _load_fixed_coefficients(cfg, pd=pd, np=np)
            fit_statistics = {
                "engine": "fixed_coefficients",
                "n_obs_pd": len(prepared_term.frame),
                "pandas_version": _package_version("pandas"),
            }
        else:
            merged = _align_history(
                prepared_term.frame,
                prepared_macro.frame,
                cfg=cfg,
                pd=pd,
            )
            coefficients, fit_statistics = _fit_coefficients(
                merged,
                reference_macro=prepared_macro.reference_macro,
                has_lgd_base=prepared_term.has_lgd_base,
                cfg=cfg,
                pd=pd,
                np=np,
            )

        warnings_seen = _fit_warnings(prepared_term, cfg=cfg)
        self.config_ = cfg
        self.target_components_ = cfg.satellite.target_components
        self.factor_columns_ = cfg.satellite.factor_cols
        self.coefficients_ = coefficients
        self.reference_macro_ = dict(prepared_macro.reference_macro)
        self.fit_statistics_ = dict(fit_statistics)
        self.diagnostics_ = SatelliteDiagnostics(
            mode=cfg.satellite.mode,
            target_components=self.target_components_,
            factor_columns=self.factor_columns_,
            segments=_segments_from_coefficients(coefficients),
            coefficients=coefficients,
            fit_statistics=fit_statistics,
            warnings=warnings_seen,
        )
        self._log_fit_decisions(warnings_seen)
        return self

    def predict(
        self,
        term_structure: "pandas.DataFrame",
        macro_projection: "pandas.DataFrame",
        *,
        scenarios: "ScenarioWeighting",
    ) -> "pandas.DataFrame":
        """Aplica ajustes macro por escenario y recompone curvas lifetime completas."""
        pd = _import_pandas()
        np = _import_numpy()
        _check_fitted(self)

        prepared_term = _prepare_term_structure(term_structure, cfg=self.config_, pd=pd, np=np)
        prepared_macro = _prepare_macro_projection(
            macro_projection,
            scenarios=scenarios,
            cfg=self.config_,
            pd=pd,
            np=np,
        )
        rows = _project_rows(
            prepared_term,
            prepared_macro,
            coefficients=self.coefficients_,
            cfg=self.config_,
            pd=pd,
        )
        frame = pd.DataFrame.from_records(rows, columns=_FORWARD_TERM_STRUCTURE_COLUMNS)
        frame.index = pd.Index(
            [
                _curve_index(
                    row["row_id"],
                    row["source_model"],
                    row["scenario"],
                    int(cast("int", row["period"])),
                )
                for row in rows
            ],
            name="curve_id",
        )
        normalized = _normalize_frame(frame)
        _validate_forward_monotonicity(normalized, cfg=self.config_)
        return normalized

    def _log_fit_decisions(self, warnings_seen: tuple[str, ...]) -> None:
        self.log_decision(
            regla="forward_satellite_model",
            umbral={
                "mode": self.config_.satellite.mode,
                "factor_columns": self.factor_columns_,
                "target_components": self.target_components_,
            },
            valor={
                "coefficients": self.coefficients_,
                "segments": self.diagnostics_.segments,
                "fit_statistics": self.fit_statistics_,
                "warnings": warnings_seen,
            },
            accion="fit_satellite_model",
        )


def _prepare_macro_history(
    frame: DataFrame,
    *,
    cfg: ForwardConfig,
    pd: Any,
    np: Any,
) -> _PreparedMacroHistory:
    copied = _as_dataframe(frame, pd=pd, field_name="macro_history")
    time_col = cfg.input.macro_source.time_col
    required = (time_col, *cfg.satellite.factor_cols)
    missing = [column for column in required if column not in copied.columns]
    if missing:
        raise ForwardInputError(f"Faltan columnas macro históricas requeridas: {missing}.")
    if bool(copied.duplicated(subset=[time_col], keep=False).any()):
        raise ForwardInputError("macro_history contiene períodos duplicados.")
    copied = copied.sort_values(time_col, kind="mergesort").reset_index(drop=True)
    if len(copied.index) < cfg.satellite.min_history_periods:
        raise SatelliteModelError(
            "FALTA-DATO-FWD-5: historia insuficiente para ajustar satellite; "
            f"observaciones={len(copied.index)}, "
            f"min_history_periods={cfg.satellite.min_history_periods}."
        )
    for column in cfg.satellite.factor_cols:
        values = copied[column].to_numpy(dtype="float64")
        if not bool(np.all(np.isfinite(values))):
            raise ForwardInputError(f"El factor macro {column!r} contiene valores no finitos.")
        if (
            int(pd.Series(values).nunique(dropna=False)) < 2
            and cfg.satellite.mode != "fixed_coefficients"
        ):
            raise SatelliteModelError(f"El factor macro {column!r} es constante.")
        copied[column] = values
    reference = {
        column: _clean_float(float(copied[column].mean())) for column in cfg.satellite.factor_cols
    }
    return _PreparedMacroHistory(frame=copied, reference_macro=reference)


def _prepare_term_structure(
    frame: DataFrame,
    *,
    cfg: ForwardConfig,
    pd: Any,
    np: Any,
) -> _PreparedTermStructure:
    copied = _as_dataframe(frame, pd=pd, field_name="term_structure")
    _ensure_optional_columns(copied)
    _validate_required_term_columns(copied)
    _validate_segment_column(copied, cfg=cfg)
    warnings_seen: list[str] = []
    if "hazard" not in copied.columns:
        copied["hazard"] = _derive_hazard(copied, cfg=cfg, pd=pd)
        warnings_seen.append(_HAZARD_DERIVED_WARNING)
    else:
        copied["hazard"] = _probability_array(
            copied["hazard"],
            field_name="hazard",
            open_interval=True,
            np=np,
        )
    for column in ("survival", "pd_marginal", "pd_cumulative"):
        copied[column] = _probability_array(
            copied[column],
            field_name=column,
            open_interval=False,
            np=np,
        )
    warnings_seen.extend(_resolve_pd_basis(copied, cfg=cfg))
    has_lgd_base = _prepare_lgd_base(copied, cfg=cfg, np=np)
    if _LGD_COMPONENT in cfg.satellite.target_components and not has_lgd_base:
        warnings_seen.append(_LGD_MISSING_WARNING)
    return _PreparedTermStructure(
        frame=_normalize_frame(copied),
        warnings=_dedupe(warnings_seen),
        has_lgd_base=has_lgd_base,
    )


def _ensure_optional_columns(frame: DataFrame) -> None:
    for column in ("row_id", "segment", "partition", "scenario"):
        if column not in frame.columns:
            frame[column] = None
    if "source_model" not in frame.columns:
        frame["source_model"] = None


def _validate_required_term_columns(frame: DataFrame) -> None:
    required = (
        "period",
        "time_value",
        "survival",
        "pd_marginal",
        "pd_cumulative",
        "method",
        "pd_source",
    )
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ForwardInputError(f"Faltan columnas requeridas en term_structure: {missing}.")


def _validate_segment_column(frame: DataFrame, *, cfg: ForwardConfig) -> None:
    segment_col = cfg.satellite.segment_col
    if segment_col is not None and segment_col not in frame.columns:
        raise ForwardInputError(
            f"Falta segment_col configurado en term_structure: {segment_col!r}."
        )


def _resolve_pd_basis(frame: DataFrame, *, cfg: ForwardConfig) -> tuple[str, ...]:
    if "pd_basis" in frame.columns:
        observed = {
            str(value) for value in frame["pd_basis"].dropna().tolist() if str(value).strip() != ""
        }
        unknown = sorted(observed - {"pit", "ttc"})
        if unknown and cfg.input.require_pit_consistency:
            raise PitConsistencyError(f"pd_basis desconocida en term_structure: {unknown}.")
        if unknown:
            frame["pd_basis"] = "pit"
            return (_PD_BASIS_UNRESOLVED_WARNING,)
        if observed:
            return ()
    if cfg.input.pd_basis_assumption is None:
        if cfg.input.require_pit_consistency:
            raise PitConsistencyError("pd_basis no resuelta para term_structure forward.")
        frame["pd_basis"] = "pit"
        return (_PD_BASIS_UNRESOLVED_WARNING,)
    frame["pd_basis"] = cfg.input.pd_basis_assumption
    return (_PD_BASIS_ASSUMED_WARNING,)


def _prepare_lgd_base(frame: DataFrame, *, cfg: ForwardConfig, np: Any) -> bool:
    del cfg
    if "lgd_base" in frame.columns:
        source = "lgd_base"
    elif "lgd" in frame.columns:
        source = "lgd"
        frame["lgd_base"] = frame["lgd"]
    else:
        frame["lgd_base"] = None
        return False
    non_missing = frame[source].notna()
    if not bool(non_missing.any()):
        return False
    values = _probability_array(
        frame.loc[non_missing, source],
        field_name=source,
        open_interval=False,
        np=np,
    )
    frame.loc[non_missing, "lgd_base"] = values
    return True


def _derive_hazard(frame: DataFrame, *, cfg: ForwardConfig, pd: Any) -> Any:
    working = frame.copy(deep=True)
    working["_ordinal"] = range(len(working.index))
    working["_curve_key"] = [_base_curve_key(row) for row in working.itertuples(index=False)]
    working = working.sort_values(["_curve_key", "period", "_ordinal"], kind="mergesort")
    hazards: dict[int, float] = {}
    for _key, group in working.groupby("_curve_key", sort=False, dropna=False):
        previous_survival = 1.0
        previous_period = 0
        for _index, row in group.iterrows():
            period = _positive_int(row["period"], field_name="period")
            if period <= previous_period:
                raise ForwardInputError("period debe crecer estrictamente para derivar hazard.")
            pd_marginal = _probability(float(row["pd_marginal"]), field_name="pd_marginal")
            if previous_survival <= cfg.validation.probability_tol:
                raise ForwardInputError(
                    "hazard ausente no derivable: survival(t-1) es cero o numéricamente nulo."
                )
            hazards[int(row["_ordinal"])] = _probability(
                pd_marginal / previous_survival,
                field_name="hazard",
                open_interval=True,
            )
            previous_survival = _probability(float(row["survival"]), field_name="survival")
            previous_period = period
    return pd.Series(hazards).sort_index()


def _align_history(
    term_structure: DataFrame,
    macro_history: DataFrame,
    *,
    cfg: ForwardConfig,
    pd: Any,
) -> DataFrame:
    time_col = cfg.input.macro_source.time_col
    term_key = time_col if time_col in term_structure.columns else "period"
    selected_macro = macro_history.loc[:, [time_col, *cfg.satellite.factor_cols]]
    merged = term_structure.merge(
        selected_macro,
        left_on=term_key,
        right_on=time_col,
        how="left",
        validate="many_to_one",
        suffixes=("", "_macro"),
    )
    missing_macro = merged[list(cfg.satellite.factor_cols)].isna().any(axis=1)
    if bool(missing_macro.any()):
        periods = sorted({str(value) for value in merged.loc[missing_macro, term_key].tolist()})
        raise ForwardInputError(f"macro_history no cubre períodos de term_structure: {periods}.")
    return merged.reset_index(drop=True)


def _fit_coefficients(
    frame: DataFrame,
    *,
    reference_macro: Mapping[str, float],
    has_lgd_base: bool,
    cfg: ForwardConfig,
    pd: Any,
    np: Any,
) -> tuple[dict[str, Any], dict[str, float | int | str | None]]:
    components: dict[str, Any] = {}
    statistics: dict[str, float | int | str | None] = {"engine": "statsmodels.OLS"}
    components[_PD_COMPONENT] = _fit_component(
        frame,
        target_column="hazard",
        reference_macro=reference_macro,
        cfg=cfg,
        pd=pd,
        np=np,
    )
    statistics["n_obs_pd"] = len(frame.index)
    if _LGD_COMPONENT in cfg.satellite.target_components and has_lgd_base:
        components[_LGD_COMPONENT] = _fit_component(
            frame,
            target_column="lgd_base",
            reference_macro=reference_macro,
            cfg=cfg,
            pd=pd,
            np=np,
        )
        statistics["n_obs_lgd"] = int(frame["lgd_base"].notna().sum())
    return components, statistics


def _fit_component(
    frame: DataFrame,
    *,
    target_column: str,
    reference_macro: Mapping[str, float],
    cfg: ForwardConfig,
    pd: Any,
    np: Any,
) -> dict[str, Any]:
    coefficients: dict[str, Any] = {}
    for segment, group in _segment_groups(frame, cfg=cfg):
        clean = group.loc[group[target_column].notna()].copy(deep=True)
        if len(clean.index) < len(cfg.satellite.factor_cols) + 1:
            raise SatelliteModelError(
                f"FALTA-DATO-FWD-5: observaciones insuficientes para {target_column} "
                f"en segmento {segment!r}."
            )
        design = pd.DataFrame(index=clean.index)
        for factor in cfg.satellite.factor_cols:
            design[factor] = clean[factor].astype("float64") - reference_macro[factor]
        response = clean[target_column].map(lambda value: _logit(float(value)))
        response = response.astype("float64") - float(response.mean())
        result = _fit_ols(response, design, np=np)
        coefficients[segment] = {
            "alpha": 0.0,
            "factors": {
                factor: _clean_float(float(result.params[factor]))
                for factor in cfg.satellite.factor_cols
            },
            "n_obs": len(clean.index),
            "rsquared": _optional_stat_float(getattr(result, "rsquared", math.nan)),
        }
    return coefficients


def _segment_groups(frame: DataFrame, *, cfg: ForwardConfig) -> tuple[tuple[str, DataFrame], ...]:
    segment_col = cfg.satellite.segment_col
    if segment_col is None:
        return ((_SEGMENT_ALL, frame),)
    groups: list[tuple[str, DataFrame]] = []
    for raw_segment, group in frame.groupby(segment_col, sort=True, dropna=False):
        groups.append((str(raw_segment), group.copy(deep=True)))
    return tuple(groups)


def _fit_ols(response: Any, design: DataFrame, *, np: Any) -> Any:
    statsmodels_api = _import_statsmodels_api()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = statsmodels_api.OLS(response, design).fit()
    except Warning as exc:
        raise SatelliteModelError(
            "statsmodels reportó un warning al ajustar el satellite; revise colinealidad."
        ) from exc
    except np.linalg.LinAlgError as exc:
        raise SatelliteModelError(
            "statsmodels no pudo resolver el ajuste satellite; revise colinealidad."
        ) from exc
    except ValueError as exc:
        raise SatelliteModelError(f"statsmodels rechazó el ajuste satellite: {exc}") from exc
    return result


def _optional_stat_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return 0.0 if numeric == 0.0 else numeric


def _load_fixed_coefficients(
    cfg: ForwardConfig,
    *,
    pd: Any,
    np: Any,
) -> dict[str, Any]:
    path = cfg.satellite.coefficient_table_path
    if path is None:
        raise SatelliteModelError(
            "FALTA-DATO-FWD-5: mode='fixed_coefficients' exige coefficient_table_path."
        )
    table = _read_coefficient_table(path, pd=pd)
    required = ("target_component", "factor_col", "coefficient", "sign")
    missing = [column for column in required if column not in table.columns]
    if missing:
        raise SatelliteModelError(
            f"Coeficientes fijos sin columna requerida o signo documentado: faltan {missing}."
        )
    coefficients: dict[str, Any] = {}
    for row in table.itertuples(index=False):
        row_any = cast("Any", row)
        component = str(row_any.target_component)
        if component not in cfg.satellite.target_components:
            continue
        factor = str(row_any.factor_col)
        segment = str(row_any.segment) if "segment" in table.columns else _SEGMENT_ALL
        coefficient = _clean_float(float(row_any.coefficient))
        sign = str(row_any.sign).strip().lower()
        _validate_documented_sign(coefficient, sign=sign)
        component_coeffs = coefficients.setdefault(component, {})
        segment_coeffs = component_coeffs.setdefault(segment, {"alpha": 0.0, "factors": {}})
        if factor in _INTERCEPT_NAMES:
            segment_coeffs["alpha"] = coefficient
        elif factor in cfg.satellite.factor_cols:
            segment_coeffs["factors"][factor] = coefficient
        else:
            raise SatelliteModelError(
                f"Coeficiente fijo referencia factor desconocido: {factor!r}."
            )
    for component in cfg.satellite.target_components:
        if component == _LGD_COMPONENT and component not in coefficients:
            continue
        _validate_component_coefficients(coefficients, component=component, cfg=cfg)
    return coefficients


def _read_coefficient_table(path: str, *, pd: Any) -> DataFrame:
    suffix = Path(path).suffix.lower()
    if suffix == ".parquet":
        return cast("DataFrame", pd.read_parquet(path))
    return cast("DataFrame", pd.read_csv(path))


def _validate_documented_sign(coefficient: float, *, sign: str) -> None:
    if sign in {"positive", "pos", "+"} and coefficient <= 0.0:
        raise SatelliteModelError("Coeficiente fijo documentado positive no es positivo.")
    if sign in {"negative", "neg", "-"} and coefficient >= 0.0:
        raise SatelliteModelError("Coeficiente fijo documentado negative no es negativo.")
    if sign in {"zero", "0"} and coefficient != 0.0:
        raise SatelliteModelError("Coeficiente fijo documentado zero no es cero.")
    if sign not in {"positive", "pos", "+", "negative", "neg", "-", "zero", "0"}:
        raise SatelliteModelError(f"Signo documentado no reconocido en coeficientes: {sign!r}.")


def _validate_component_coefficients(
    coefficients: Mapping[str, Any],
    *,
    component: str,
    cfg: ForwardConfig,
) -> None:
    if component not in coefficients:
        raise SatelliteModelError(f"Faltan coeficientes fijos para target {component!r}.")
    for segment, payload in coefficients[component].items():
        factors = payload["factors"]
        missing = sorted(set(cfg.satellite.factor_cols) - set(factors))
        if missing:
            raise SatelliteModelError(
                f"Faltan coeficientes fijos para segmento {segment!r}: {missing}."
            )


def _fit_warnings(prepared_term: _PreparedTermStructure, *, cfg: ForwardConfig) -> tuple[str, ...]:
    warnings_seen = list(prepared_term.warnings)
    if _LGD_COMPONENT in cfg.satellite.target_components and not prepared_term.has_lgd_base:
        warnings_seen.append(_LGD_MISSING_WARNING)
    return _dedupe(warnings_seen)


def _segments_from_coefficients(coefficients: Mapping[str, Any]) -> tuple[str, ...]:
    segments: dict[str, None] = {}
    for component in coefficients.values():
        if isinstance(component, Mapping):
            for segment in component:
                if str(segment) != _SEGMENT_ALL:
                    segments.setdefault(str(segment), None)
    return tuple(segments)


def _prepare_macro_projection(
    frame: DataFrame,
    *,
    scenarios: Any,
    cfg: ForwardConfig,
    pd: Any,
    np: Any,
) -> _MacroProjectionPrepared:
    copied = _as_dataframe(frame, pd=pd, field_name="macro_projection")
    validator = getattr(scenarios, "validate_macro_projection", None)
    if callable(validator):
        validator(copied.copy(deep=True))
    required = ("scenario", "period", "macro_variable", "projected_value")
    missing = [column for column in required if column not in copied.columns]
    if missing:
        raise SatelliteModelError(f"macro_projection no trae columnas requeridas: {missing}.")
    missing_factors = sorted(
        set(cfg.satellite.factor_cols) - set(copied["macro_variable"].astype(str))
    )
    if missing_factors:
        raise SatelliteModelError(f"Factor satellite no proyectado: {missing_factors}.")
    copied["period"] = [_positive_int(value, field_name="period") for value in copied["period"]]
    copied["projected_value"] = _finite_array(
        copied["projected_value"],
        field_name="projected_value",
        np=np,
    )
    scenarios_order = _scenario_order(copied, cfg=cfg)
    scenario_weights = _scenario_weights(copied, scenarios=scenarios, cfg=cfg)
    deltas = _macro_deltas(copied, cfg=cfg)
    model_ids = _macro_model_ids(copied, cfg=cfg)
    warnings_by_period = _macro_warnings(copied, cfg=cfg)
    return _MacroProjectionPrepared(
        frame=_normalize_frame(copied),
        scenarios=scenarios_order,
        scenario_weights=scenario_weights,
        deltas=deltas,
        macro_model_ids=model_ids,
        warning_codes=warnings_by_period,
    )


def _scenario_order(frame: DataFrame, *, cfg: ForwardConfig) -> tuple[str, ...]:
    observed = tuple(dict.fromkeys(str(value) for value in frame["scenario"].tolist()))
    configured = tuple(scenario.name for scenario in cfg.scenarios.scenarios)
    ordered = tuple(scenario for scenario in configured if scenario in observed)
    extras = tuple(scenario for scenario in observed if scenario not in configured)
    return (*ordered, *extras)


def _scenario_weights(frame: DataFrame, *, scenarios: Any, cfg: ForwardConfig) -> dict[str, float]:
    for attribute in ("scenario_weights_", "weights_", "weights"):
        candidate = getattr(scenarios, attribute, None)
        if isinstance(candidate, Mapping):
            return {str(key): _non_negative_float(float(value)) for key, value in candidate.items()}
    if "scenario_weight" in frame.columns:
        weights: dict[str, float] = {}
        for scenario, group in frame.groupby("scenario", sort=False, dropna=False):
            values = {
                _non_negative_float(float(value))
                for value in group["scenario_weight"].dropna().tolist()
            }
            if len(values) == 1:
                weights[str(scenario)] = values.pop()
        if weights:
            return weights
    return {
        scenario.name: _clean_float(float(scenario.weight)) for scenario in cfg.scenarios.scenarios
    }


def _macro_deltas(frame: DataFrame, *, cfg: ForwardConfig) -> dict[tuple[str, int, str], float]:
    deltas: dict[tuple[str, int, str], float] = {}
    reference = cfg.satellite.reference_scenario
    for (period, factor), group in frame.groupby(
        ["period", "macro_variable"],
        sort=False,
        dropna=False,
    ):
        factor_name = str(factor)
        if factor_name not in cfg.satellite.factor_cols:
            continue
        reference_rows = group[group["scenario"].astype(str) == reference]
        if len(reference_rows.index) != 1:
            raise SatelliteModelError(
                "macro_projection debe contener exactamente una fila de referencia "
                f"para scenario={reference!r}, period={period!r}, factor={factor_name!r}."
            )
        reference_value = float(cast("Any", reference_rows["projected_value"].iloc[0]))
        seen: set[str] = set()
        for row in group.itertuples(index=False):
            row_any = cast("Any", row)
            scenario = str(row_any.scenario)
            if scenario in seen:
                raise SatelliteModelError(
                    "macro_projection contiene duplicados para "
                    f"scenario={scenario!r}, period={period!r}, factor={factor_name!r}."
                )
            seen.add(scenario)
            deltas[(scenario, _positive_int(period, field_name="period"), factor_name)] = (
                _clean_float(float(row_any.projected_value) - reference_value)
            )
    return deltas


def _macro_model_ids(frame: DataFrame, *, cfg: ForwardConfig) -> dict[tuple[str, int], str]:
    if "model_id" not in frame.columns:
        return {
            (str(scenario), _positive_int(period, field_name="period")): "macro:unknown"
            for scenario in frame["scenario"].unique()
            for period in frame["period"].unique()
        }
    model_ids: dict[tuple[str, int], str] = {}
    for (scenario, period), group in frame.groupby(
        ["scenario", "period"],
        sort=False,
        dropna=False,
    ):
        selected = group[group["macro_variable"].astype(str).isin(cfg.satellite.factor_cols)]
        values = tuple(dict.fromkeys(str(value) for value in selected["model_id"].tolist()))
        model_ids[(str(scenario), _positive_int(period, field_name="period"))] = ";".join(values)
    return model_ids


def _macro_warnings(
    frame: DataFrame,
    *,
    cfg: ForwardConfig,
) -> dict[tuple[str, int], tuple[str, ...]]:
    del cfg
    if "warning_codes" not in frame.columns:
        return {}
    warnings_by_period: dict[tuple[str, int], tuple[str, ...]] = {}
    for (scenario, period), group in frame.groupby(
        ["scenario", "period"],
        sort=False,
        dropna=False,
    ):
        codes: list[str] = []
        for raw in group["warning_codes"].tolist():
            codes.extend(_warning_tuple(raw))
        warnings_by_period[(str(scenario), _positive_int(period, field_name="period"))] = _dedupe(
            codes
        )
    return warnings_by_period


def _project_rows(
    prepared_term: _PreparedTermStructure,
    prepared_macro: _MacroProjectionPrepared,
    *,
    coefficients: Mapping[str, Any],
    cfg: ForwardConfig,
    pd: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base = prepared_term.frame.copy(deep=True)
    base["_curve_key"] = [_base_curve_key(row) for row in base.itertuples(index=False)]
    base["_ordinal"] = range(len(base.index))
    base = base.sort_values(["source_model", "_curve_key", "period", "_ordinal"], kind="mergesort")
    for scenario in prepared_macro.scenarios:
        for _curve_key, group in base.groupby("_curve_key", sort=False, dropna=False):
            previous_survival = 1.0
            previous_cumulative = 0.0
            for row in group.itertuples(index=False):
                row_any = cast("Any", row)
                period = int(row_any.period)
                adjustment = _satellite_adjustment(
                    row,
                    scenario=scenario,
                    period=period,
                    prepared_macro=prepared_macro,
                    coefficients=coefficients,
                    cfg=cfg,
                    component=_PD_COMPONENT,
                )
                hazard = _sigmoid(_logit(float(row_any.hazard)) + adjustment)
                pd_marginal = _probability(previous_survival * hazard, field_name="pd_marginal")
                survival = _probability(previous_survival * (1.0 - hazard), field_name="survival")
                pd_cumulative = _probability(1.0 - survival, field_name="pd_cumulative")
                monotonic_floor = previous_cumulative - cfg.validation.monotonic_tol
                if pd_cumulative < monotonic_floor:  # pragma: no cover
                    # La cobertura real vive en _validate_forward_monotonicity.
                    raise ForwardPredictionError("Monotonicidad rota en pd_cumulative.")
                rows.append(
                    _output_row(
                        row,
                        scenario=scenario,
                        scenario_weight=prepared_macro.scenario_weights.get(scenario, 0.0),
                        hazard=hazard,
                        survival=survival,
                        pd_marginal=pd_marginal,
                        pd_cumulative=pd_cumulative,
                        satellite_adjustment=adjustment,
                        macro_model_id=prepared_macro.macro_model_ids.get(
                            (scenario, period),
                            "macro:unknown",
                        ),
                        warning_codes=_combined_warnings(
                            getattr(row, "warning_codes", ()),
                            prepared_term.warnings,
                            prepared_macro.warning_codes.get((scenario, period), ()),
                        ),
                        lgd=_project_lgd(
                            row,
                            scenario=scenario,
                            period=period,
                            prepared_macro=prepared_macro,
                            coefficients=coefficients,
                            cfg=cfg,
                        ),
                    )
                )
                previous_survival = survival
                previous_cumulative = pd_cumulative
    return rows


def _satellite_adjustment(
    row: Any,
    *,
    scenario: str,
    period: int,
    prepared_macro: _MacroProjectionPrepared,
    coefficients: Mapping[str, Any],
    cfg: ForwardConfig,
    component: TargetComponent,
) -> float:
    segment = _segment_value(row, cfg=cfg)
    payload = _coefficient_payload(coefficients, component=component, segment=segment)
    adjustment = float(payload.get("alpha", 0.0))
    factors = cast("Mapping[str, float]", payload.get("factors", {}))
    for factor in cfg.satellite.factor_cols:
        try:
            delta = prepared_macro.deltas[(scenario, period, factor)]
        except KeyError as exc:
            raise SatelliteModelError(
                f"Factor satellite no proyectado: scenario={scenario!r}, "
                f"period={period}, factor={factor!r}."
            ) from exc
        adjustment += factors[factor] * delta
    return _clean_float(adjustment)


def _coefficient_payload(
    coefficients: Mapping[str, Any],
    *,
    component: TargetComponent,
    segment: str,
) -> Mapping[str, Any]:
    component_coeffs = coefficients.get(component)
    if not isinstance(component_coeffs, Mapping):
        raise SatelliteModelError(f"Modelo satellite sin coeficientes para {component!r}.")
    payload = component_coeffs.get(segment) or component_coeffs.get(_SEGMENT_ALL)
    if not isinstance(payload, Mapping):
        raise SatelliteModelError(f"Modelo satellite sin coeficientes para segmento {segment!r}.")
    return payload


def _project_lgd(
    row: Any,
    *,
    scenario: str,
    period: int,
    prepared_macro: _MacroProjectionPrepared,
    coefficients: Mapping[str, Any],
    cfg: ForwardConfig,
) -> float | None:
    if _LGD_COMPONENT not in cfg.satellite.target_components:
        return None
    lgd_base = getattr(row, "lgd_base", None)
    if _is_missing(lgd_base) or _LGD_COMPONENT not in coefficients:
        return None
    adjustment = _satellite_adjustment(
        row,
        scenario=scenario,
        period=period,
        prepared_macro=prepared_macro,
        coefficients=coefficients,
        cfg=cfg,
        component=_LGD_COMPONENT,
    )
    return _sigmoid(_logit(float(cast("Any", lgd_base))) + adjustment)


def _output_row(
    row: Any,
    *,
    scenario: str,
    scenario_weight: float,
    hazard: float,
    survival: float,
    pd_marginal: float,
    pd_cumulative: float,
    satellite_adjustment: float,
    macro_model_id: str,
    warning_codes: tuple[str, ...],
    lgd: float | None,
) -> dict[str, Any]:
    source_model = _source_model(row)
    lgd_base = _none_if_missing(getattr(row, "lgd_base", None))
    return {
        "row_id": getattr(row, "row_id", None),
        "segment": getattr(row, "segment", None),
        "partition": getattr(row, "partition", None),
        "source_model": source_model,
        "period": int(row.period),
        "time_value": _clean_float(float(row.time_value)),
        "scenario": scenario,
        "scenario_weight": _non_negative_float(float(scenario_weight)),
        "hazard": hazard,
        "survival": survival,
        "pd_marginal": pd_marginal,
        "pd_cumulative": pd_cumulative,
        "pd_marginal_base": _clean_float(float(row.pd_marginal)),
        "pd_cumulative_base": _clean_float(float(row.pd_cumulative)),
        "lgd": lgd,
        "lgd_base": None if lgd_base is None else _clean_float(float(lgd_base)),
        "pd_basis": "pit",
        "basis_state": "pit",
        "ttc_reversion_weight": 1.0,
        "satellite_adjustment": satellite_adjustment,
        "macro_model_id": macro_model_id,
        "satellite_model_id": _SATELLITE_MODEL_ID,
        "method": row.method,
        "pd_source": row.pd_source,
        "warning_codes": warning_codes,
    }


def _source_model(row: Any) -> str:
    explicit = getattr(row, "source_model", None)
    if explicit is not None and not (isinstance(explicit, float) and math.isnan(explicit)):
        text = str(explicit)
        if text and text != "<NA>":
            return text
    pd_source = str(row.pd_source)
    if pd_source in {"survival", "markov"}:
        return pd_source
    return str(row.method)


def _segment_value(row: Any, *, cfg: ForwardConfig) -> str:
    if cfg.satellite.segment_col is None:
        return _SEGMENT_ALL
    value = getattr(row, cfg.satellite.segment_col)
    return str(value)


def _base_curve_key(row: Any) -> tuple[Any, ...]:
    return (
        _none_if_missing(getattr(row, "row_id", None)),
        _none_if_missing(getattr(row, "segment", None)),
        _none_if_missing(getattr(row, "partition", None)),
        _source_model(row),
        _none_if_missing(getattr(row, "method", None)),
        _none_if_missing(getattr(row, "pd_source", None)),
    )


def _forward_curve_key(row: Any) -> tuple[Any, ...]:
    return (*_base_curve_key(row), _none_if_missing(getattr(row, "scenario", None)))


def _curve_index(row_id: Any, source_model: Any, scenario: str, period: int) -> str:
    return f"{_none_if_missing(row_id) or '__all__'}|{source_model}|{scenario}|{period}"


def _validate_forward_monotonicity(frame: DataFrame, *, cfg: ForwardConfig) -> None:
    previous: dict[tuple[Any, ...], tuple[int, float]] = {}
    for row in frame.itertuples(index=False):
        row_any = cast("Any", row)
        key = _forward_curve_key(row_any)
        period = int(row_any.period)
        cumulative = float(row_any.pd_cumulative)
        prior = previous.get(key)
        if prior is not None:
            prior_period, prior_cumulative = prior
            if period <= prior_period:
                raise ForwardPredictionError("period debe crecer estrictamente por curva.")
            if cumulative < prior_cumulative - cfg.validation.monotonic_tol:
                raise ForwardPredictionError("Monotonicidad rota en pd_cumulative.")
        previous[key] = (period, cumulative)


def _as_dataframe(frame: DataFrame, *, pd: Any, field_name: str) -> DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise ForwardInputError(f"{field_name} requiere un pandas.DataFrame.")
    return cast("DataFrame", frame.copy(deep=True))


def _probability_array(
    series: Any,
    *,
    field_name: str,
    open_interval: bool,
    np: Any,
) -> NDArrayFloat:
    values = np.asarray(series, dtype="float64")
    if not bool(np.all(np.isfinite(values))):
        raise ForwardInputError(f"{field_name} contiene valores no finitos.")
    for value in values:
        _probability(float(value), field_name=field_name, open_interval=open_interval)
    values[values == 0.0] = 0.0
    return cast("NDArrayFloat", values)


def _finite_array(series: Any, *, field_name: str, np: Any) -> NDArrayFloat:
    values = np.asarray(series, dtype="float64")
    if not bool(np.all(np.isfinite(values))):
        raise ForwardInputError(f"{field_name} contiene valores no finitos.")
    values[values == 0.0] = 0.0
    return cast("NDArrayFloat", values)


def _probability(value: float, *, field_name: str, open_interval: bool = False) -> float:
    cleaned = _clean_float(value)
    if open_interval:
        if cleaned <= 0.0 or cleaned >= 1.0:
            raise ForwardInputError(f"{field_name} debe estar en (0, 1); valor={cleaned}.")
        return cleaned
    if cleaned < 0.0 or cleaned > 1.0:
        raise ForwardInputError(f"{field_name} debe estar en [0, 1]; valor={cleaned}.")
    return cleaned


def _non_negative_float(value: float) -> float:
    cleaned = _clean_float(value)
    if cleaned < 0.0:
        raise ForwardInputError(f"Valor debe ser no negativo: {cleaned}.")
    return cleaned


def _positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ForwardInputError(f"{field_name} no puede ser booleano.")
    numeric = float(value)
    rounded = round(numeric)
    if not math.isfinite(numeric) or not math.isclose(
        numeric,
        rounded,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ForwardInputError(f"{field_name} debe ser entero.")
    if rounded < 1:
        raise ForwardInputError(f"{field_name} debe ser mayor o igual a 1.")
    return int(rounded)


def _logit(value: float) -> float:
    probability = _probability(value, field_name="probabilidad logit", open_interval=True)
    return math.log(probability / (1.0 - probability))


def _sigmoid(value: float) -> float:
    if not math.isfinite(value):
        raise ForwardPredictionError(f"Overflow logit en satellite: eta={value!r}.")
    cleaned = 0.0 if value == 0.0 else value
    try:
        if cleaned >= 0.0:
            exp_value = math.exp(-cleaned)
            probability = 1.0 / (1.0 + exp_value)
        else:
            exp_value = math.exp(cleaned)
            probability = exp_value / (1.0 + exp_value)
    except OverflowError as exc:  # pragma: no cover
        # La fórmula estable evita esta ruta para floats finitos normales; queda como defensa.
        raise ForwardPredictionError(f"Overflow logit en satellite: eta={value!r}.") from exc
    if not math.isfinite(probability) or probability <= 0.0 or probability >= 1.0:
        raise ForwardPredictionError(
            f"Probabilidad fuera de rango por overflow logit: eta={value!r}."
        )
    return probability


def _clean_float(value: float) -> float:
    if not math.isfinite(value):
        raise ForwardInputError(f"Valor numérico no finito en satellite: {value!r}.")
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


def _combined_warnings(*values: Any) -> tuple[str, ...]:
    warnings_seen: list[str] = []
    for value in values:
        warnings_seen.extend(_warning_tuple(value))
    return _dedupe(warnings_seen)


def _warning_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return () if value == "" else (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if item not in (None, ""))
    return (str(value),)


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _none_if_missing(value: Any) -> Any:
    if _is_missing(value):
        return None
    return value


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _check_fitted(model: SatelliteModel) -> None:
    if not hasattr(model, "coefficients_"):
        raise NotFittedError("SatelliteModel no está fiteado; llame fit(...) antes de proyectar.")


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "no-disponible"


def _import_pandas() -> Any:
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("SatelliteModel requiere pandas.") from exc


def _import_numpy() -> Any:
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError("SatelliteModel requiere numpy.") from exc


def _import_statsmodels_api() -> Any:
    try:
        return importlib.import_module("statsmodels.api")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            f"SatelliteModel requiere statsmodels; {_FORECASTING_EXTRA_MESSAGE}."
        ) from exc
