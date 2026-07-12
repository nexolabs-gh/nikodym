"""DTOs puros de resultados forward-looking (SDD-20 §4/§6).

Este módulo fija los contenedores Pydantic publicados por ``forward``: diagnósticos macro,
diagnósticos satellite, escenarios, tarjeta CT-2, contrato hacia ECL y resultado agregado. No
estima modelos macro, no ajusta satellite models y no importa ``pandas``, ``numpy``, ``scipy``,
``statsmodels`` ni ``pmdarima`` en runtime al cargar el módulo.

``ForwardDiagnostics`` cierra el gap del SDD-20: §4 referencia el tipo en ``ForwardResult`` y §9
lo lista como artefacto, pero §4 no define sus campos. Es un agregador de ``MacroDiagnostics``,
``SatelliteDiagnostics`` y ``ScenarioDiagnostics`` más el estado PIT/TTC, la reversión TTC y el
guard anti escenario medio enumerados por §9.

``ForwardResult.term_structure()`` cumple CT-2: devuelve la term-structure forward-looking tidy
cuando existe y ``None`` solo para modos diagnósticos sin salida publicable. Las colecciones
mutables y DataFrames se copian defensivamente al validar y al acceder; los floats publicados
normalizan ``-0.0`` como ``0.0``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from decimal import Decimal
from numbers import Integral, Real
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.forward.config import (
    MacroModelKind,
    PdBasisAssumption,
    SatelliteMode,
    TargetComponent,
    TtcAnchor,
    TtcReversionMethod,
)
from nikodym.forward.exceptions import ForwardPredictionError

if TYPE_CHECKING:
    import pandas

    DataFrameLike: TypeAlias = pandas.DataFrame
else:
    DataFrameLike: TypeAlias = Any

_MACRO_PROJECTION_COLUMNS: tuple[str, ...] = (
    "scenario",
    "scenario_weight",
    "period",
    "time_value",
    "macro_variable",
    "projected_value",
    "model_value",
    "shock_value",
    "method",
    "model_id",
    "is_reasonable_supportable",
    "warning_codes",
)
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
_FORWARD_TERM_STRUCTURE_OPTIONAL_ECL_COLUMNS: frozenset[str] = frozenset({"lgd", "lgd_base"})
_SCENARIO_WEIGHT_COLUMNS: tuple[str, ...] = (
    "scenario",
    "weight",
    "is_default",
    "source",
    "description",
)
_METRIC_SECTION_KEYS: tuple[str, ...] = (
    "macro_projection_summary",
    "ljung_box",
    "scenario_weights",
    "satellite_coefficients",
    "pit_ttc_consistency",
    "term_structure_summary",
)
_RESERVED_SCENARIOS: frozenset[str] = frozenset({"mean", "average"})
_EclChain: TypeAlias = Literal[
    "macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting"
]
_ECL_CHAIN: _EclChain = (
    "macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting"
)
FORWARD_ECL_CONTRACT_VERSION: Final = "SDD-20:1.0.0"
_FLOAT_ATOL = 1e-12
_FLOAT_RTOL = 1e-12

__all__ = [
    "FORWARD_ECL_CONTRACT_VERSION",
    "ForwardCard",
    "ForwardDiagnostics",
    "ForwardEclInput",
    "ForwardResult",
    "MacroDiagnostics",
    "MacroModelKind",
    "MacroProjectionResult",
    "PdBasisAssumption",
    "SatelliteDiagnostics",
    "SatelliteMode",
    "SatelliteResult",
    "ScenarioDiagnostics",
    "TargetComponent",
    "TtcAnchor",
    "TtcReversionMethod",
]


class MacroDiagnostics(BaseModel):
    """Diagnóstico macro publicado por la capa ``forward`` sin motores de forecasting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"dependency_versions", "ljung_box_p_values", "ljung_box_statistics", "orders_lags"}
    )

    method: MacroModelKind
    macro_variables: tuple[str, ...]
    frequency: str | None = None
    orders_lags: dict[str, Any] = Field(default_factory=dict)
    horizon: int = Field(ge=1)
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    input_rows: int = Field(ge=0)
    input_gaps: int = Field(ge=0)
    input_missing: int = Field(ge=0)
    input_time_range: tuple[str | int | float | None, str | int | float | None] | None = None
    macro_data_hash: str | None = None
    ljung_box_lags: tuple[int, ...] = ()
    ljung_box_statistics: dict[str, Any] = Field(default_factory=dict)
    ljung_box_p_values: dict[str, Any] = Field(default_factory=dict)
    ljung_box_action: str
    warnings: tuple[str, ...] = ()

    @field_validator("macro_variables")
    @classmethod
    def _valida_macro_variables(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida variables macro no vacías."""
        return _validate_string_tuple(value, field_name="macro_variables", allow_empty=False)

    @field_validator("frequency", "macro_data_hash", mode="before")
    @classmethod
    def _normaliza_texto_opcional(cls, value: Any) -> Any:
        """Rechaza textos opcionales vacíos cuando existen."""
        return _normalize_optional_text(value)

    @field_validator("ljung_box_action")
    @classmethod
    def _valida_ljung_box_action(cls, value: str) -> str:
        """Valida acción Ljung-Box no vacía."""
        return _validate_non_empty_text(value, field_name="ljung_box_action")

    @field_validator("orders_lags", "ljung_box_statistics", "ljung_box_p_values", mode="before")
    @classmethod
    def _copia_metricas_macro(cls, value: Any) -> Any:
        """Copia payloads macro y normaliza floats publicados."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(value)
        return value

    @field_validator("dependency_versions", mode="before")
    @classmethod
    def _copia_dependency_versions(cls, value: Any) -> Any:
        """Copia versiones de dependencias preservando orden de inserción."""
        return _normalize_dependency_versions(value)

    @field_validator("input_time_range", mode="before")
    @classmethod
    def _normaliza_rango_temporal(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` en el rango temporal declarativo."""
        if value is None:
            return None
        items = tuple(value)
        if len(items) != 2:
            raise ValueError("input_time_range debe tener inicio y fin.")
        return tuple(_normalize_time_value(item) for item in items)

    @field_validator("ljung_box_lags", mode="before")
    @classmethod
    def _valida_lags(cls, value: Any) -> Any:
        """Valida lags Ljung-Box positivos."""
        lags = tuple(value)
        for lag in lags:
            if _integer_value(lag, field_name="ljung_box_lags") < 1:
                raise ValueError("ljung_box_lags debe contener enteros positivos.")
        return lags

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class SatelliteDiagnostics(BaseModel):
    """Diagnóstico del modelo satellite PD/LGD sin depender de un estimador concreto."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"coefficients", "fit_statistics"})

    mode: SatelliteMode
    target_components: tuple[TargetComponent, ...]
    factor_columns: tuple[str, ...]
    segments: tuple[str, ...] = ()
    coefficients: dict[str, Any] = Field(default_factory=dict)
    fit_statistics: dict[str, float | int | str | None] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @field_validator("factor_columns")
    @classmethod
    def _valida_factores(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida factores macro no vacíos."""
        return _validate_string_tuple(value, field_name="factor_columns", allow_empty=False)

    @field_validator("segments")
    @classmethod
    def _valida_segmentos(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida segmentos declarados cuando existen."""
        return _validate_string_tuple(value, field_name="segments", allow_empty=True)

    @field_validator("target_components")
    @classmethod
    def _valida_targets(cls, value: tuple[TargetComponent, ...]) -> tuple[TargetComponent, ...]:
        """Valida que exista al menos un componente objetivo."""
        if not value:
            raise ValueError("target_components debe contener al menos un componente.")
        return value

    @field_validator("coefficients", mode="before")
    @classmethod
    def _copia_coefficients(cls, value: Any) -> Any:
        """Copia coeficientes satellite y normaliza floats publicados."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(value)
        return value

    @field_validator("fit_statistics", mode="before")
    @classmethod
    def _copia_fit_statistics(cls, value: Any) -> Any:
        """Copia estadísticas de ajuste y neutraliza floats no finitos."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {str(key): _normalize_stat_value(item) for key, item in value.items()}
        return value

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class ScenarioDiagnostics(BaseModel):
    """Diagnóstico de escenarios, pesos y guard anti escenario medio."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"scenario_sources", "scenario_weights"}
    )

    scenarios: tuple[str, ...]
    scenario_weights: dict[str, float]
    scenario_sources: dict[str, str] = Field(default_factory=dict)
    default_scenarios_to_confirm: tuple[str, ...] = ()
    weight_sum: float
    no_mean_scenario_guard_executed: bool
    no_mean_scenario_guard_result: str
    warnings: tuple[str, ...] = ()

    @field_validator("scenarios")
    @classmethod
    def _valida_escenarios(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida nombres de escenarios no vacíos ni reservados."""
        normalized = _validate_string_tuple(value, field_name="scenarios", allow_empty=False)
        for scenario in normalized:
            _validate_scenario_name(scenario)
        if len(set(normalized)) != len(normalized):
            raise ValueError("scenarios no puede contener duplicados.")
        return normalized

    @field_validator("scenario_weights", mode="before")
    @classmethod
    def _copia_scenario_weights(cls, value: Any) -> Any:
        """Copia pesos de escenarios y exige floats finitos no negativos."""
        if isinstance(value, Mapping):
            return {
                _validate_non_empty_text(str(key), field_name="scenario_weights"): (
                    _normalize_non_negative_float(item)
                )
                for key, item in value.items()
            }
        return value

    @field_validator("scenario_sources", mode="before")
    @classmethod
    def _copia_scenario_sources(cls, value: Any) -> Any:
        """Copia fuentes de escenarios preservando orden."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {
                _validate_non_empty_text(str(key), field_name="scenario_sources"): (
                    _validate_non_empty_text(str(item), field_name="scenario_sources")
                )
                for key, item in value.items()
            }
        return value

    @field_validator("default_scenarios_to_confirm")
    @classmethod
    def _valida_defaults(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida defaults pendientes de confirmación."""
        return _validate_string_tuple(
            value,
            field_name="default_scenarios_to_confirm",
            allow_empty=True,
        )

    @field_validator("weight_sum", mode="before")
    @classmethod
    def _normaliza_weight_sum(cls, value: Any) -> float:
        """Normaliza suma de pesos publicada."""
        return _normalize_non_negative_float(value)

    @field_validator("no_mean_scenario_guard_result")
    @classmethod
    def _valida_guard_result(cls, value: str) -> str:
        """Valida resultado declarativo del guard anti escenario medio."""
        return _validate_non_empty_text(value, field_name="no_mean_scenario_guard_result")

    @model_validator(mode="after")
    def _check_pesos(self) -> ScenarioDiagnostics:
        """Valida que los pesos cubran exactamente los escenarios diagnosticados."""
        scenario_set = set(self.scenarios)
        if set(self.scenario_weights) != scenario_set:
            raise ValueError("scenario_weights debe cubrir exactamente scenarios.")
        observed_sum = sum(self.scenario_weights.values())
        if not math.isclose(
            observed_sum,
            self.weight_sum,
            rel_tol=_FLOAT_RTOL,
            abs_tol=_FLOAT_ATOL,
        ):
            raise ValueError("weight_sum debe coincidir con la suma de scenario_weights.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class ForwardDiagnostics(BaseModel):
    """Agregador de diagnósticos forward: macro, satellite, escenarios, PIT/TTC y TTC."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    macro: MacroDiagnostics
    satellite: SatelliteDiagnostics
    scenario: ScenarioDiagnostics
    pd_basis: PdBasisAssumption | None
    basis_states: tuple[Literal["pit", "blended", "ttc"], ...]
    pit_warnings: tuple[str, ...] = ()
    pit_decisions: tuple[str, ...] = ()
    ttc_reversion_method: TtcReversionMethod
    ttc_anchor: TtcAnchor
    reasonable_supportable_periods: int = Field(ge=0)
    reversion_periods: int = Field(ge=0)
    blended_periods: tuple[int, ...] = ()
    no_mean_scenario_guard_executed: bool
    no_mean_scenario_guard_result: str
    falta_dato: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @field_validator("basis_states")
    @classmethod
    def _valida_basis_states(
        cls,
        value: tuple[Literal["pit", "blended", "ttc"], ...],
    ) -> tuple[Literal["pit", "blended", "ttc"], ...]:
        """Valida que exista al menos un estado PIT/TTC publicado."""
        if not value:
            raise ValueError("basis_states debe contener al menos un estado.")
        return value

    @field_validator("blended_periods", mode="before")
    @classmethod
    def _valida_blended_periods(cls, value: Any) -> Any:
        """Valida períodos blended de reversión TTC."""
        periods = tuple(value)
        for period in periods:
            if _integer_value(period, field_name="blended_periods") < 1:
                raise ValueError("blended_periods debe contener enteros positivos.")
        return periods

    @field_validator("no_mean_scenario_guard_result")
    @classmethod
    def _valida_guard_result(cls, value: str) -> str:
        """Valida resultado agregado del guard anti escenario medio."""
        return _validate_non_empty_text(value, field_name="no_mean_scenario_guard_result")


class ForwardCard(BaseModel):
    """Resumen determinista CT-2 para governance, inventario y reportes forward."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"dependency_versions", "metric_sections"}
    )

    output_columns: tuple[str, ...]
    diagnostics: ForwardDiagnostics
    dependency_versions: dict[str, str]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=lambda: _default_metric_sections())

    @field_validator("output_columns")
    @classmethod
    def _valida_output_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida columnas publicadas sin exigir salida en modo diagnóstico."""
        return _validate_string_tuple(value, field_name="output_columns", allow_empty=True)

    @field_validator("dependency_versions", mode="before")
    @classmethod
    def _copia_dependency_versions(cls, value: Any) -> Any:
        """Copia versiones de dependencias preservando orden de inserción."""
        return _normalize_dependency_versions(value)

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia y completa las secciones CT-2 de SDD-20 §9."""
        if value is None:
            normalized: dict[str, Any] = {}
        elif isinstance(value, Mapping):
            normalized = _normalize_metric_payload(value)
        else:
            return value
        return _with_required_metric_sections(normalized)

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class MacroProjectionResult(BaseModel):
    """Resultado macro declarado en §4.

    Consumidor no especificado por el SDD; no inventar campos.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class SatelliteResult(BaseModel):
    """Resultado satellite declarado en §4.

    Consumidor no especificado por el SDD; no inventar campos.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ForwardEclInput(BaseModel):
    """Contrato de entrada hacia el motor ECL futuro sin dependencia dura a IFRS 9."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"pit_consistency", "scenario_weight_frame", "term_structure_frame"}
    )

    term_structure_frame: DataFrameLike | None
    scenario_weight_frame: DataFrameLike
    pit_consistency: dict[str, Any]
    chain: _EclChain = _ECL_CHAIN
    contract_version: str

    @field_validator("term_structure_frame", mode="before")
    @classmethod
    def _copia_term_structure(cls, value: Any) -> Any:
        """Copia y valida la term-structure forward para ECL cuando existe."""
        if value is None:
            return None
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_FORWARD_TERM_STRUCTURE_COLUMNS,
            optional_columns=_FORWARD_TERM_STRUCTURE_OPTIONAL_ECL_COLUMNS,
            field_name="term_structure_frame",
        )

    @field_validator("scenario_weight_frame", mode="before")
    @classmethod
    def _copia_scenario_weights(cls, value: Any) -> Any:
        """Copia y valida pesos de escenario para ECL."""
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_SCENARIO_WEIGHT_COLUMNS,
            field_name="scenario_weight_frame",
        )
        _validate_scenario_weight_values(copied)
        return copied

    @field_validator("pit_consistency", mode="before")
    @classmethod
    def _copia_pit_consistency(cls, value: Any) -> Any:
        """Copia metadata PIT/TTC del contrato ECL."""
        if isinstance(value, Mapping):
            return _normalize_metric_payload(value)
        return value

    @field_validator("contract_version")
    @classmethod
    def _valida_contract_version(cls, value: str) -> str:
        """Valida versión de contrato no vacía."""
        return _validate_non_empty_text(value, field_name="contract_version")

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de frames y metadata ECL."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            if _is_dataframe_like(value):
                return _copy_dataframe(value)
            return copy.deepcopy(value)
        return value


class ForwardResult(BaseModel):
    """Contenedor agregado de artefactos publicados por la capa ``forward``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"forward_term_structure_frame", "macro_projection_frame", "scenario_weight_frame"}
    )

    macro_projection_frame: DataFrameLike
    forward_term_structure_frame: DataFrameLike | None
    scenario_weight_frame: DataFrameLike
    diagnostics: ForwardDiagnostics
    card: ForwardCard
    ecl_input: ForwardEclInput

    @field_validator("macro_projection_frame", mode="before")
    @classmethod
    def _copia_macro_projection(cls, value: Any) -> Any:
        """Copia y valida la proyección macro tidy de SDD-20 §6."""
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_MACRO_PROJECTION_COLUMNS,
            field_name="macro_projection_frame",
        )
        _validate_macro_projection_values(copied)
        return copied

    @field_validator("forward_term_structure_frame", mode="before")
    @classmethod
    def _copia_forward_term_structure(cls, value: Any) -> Any:
        """Copia y valida la term-structure forward-looking cuando existe."""
        if value is None:
            return None
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_FORWARD_TERM_STRUCTURE_COLUMNS,
            field_name="forward_term_structure_frame",
        )
        _validate_forward_term_structure_values(copied)
        return copied

    @field_validator("scenario_weight_frame", mode="before")
    @classmethod
    def _copia_scenario_weight_frame(cls, value: Any) -> Any:
        """Copia y valida la tabla tidy de pesos de escenario."""
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_SCENARIO_WEIGHT_COLUMNS,
            field_name="scenario_weight_frame",
        )
        _validate_scenario_weight_values(copied)
        return copied

    @model_validator(mode="after")
    def _check_consistencia(self) -> ForwardResult:
        """Valida consistencia entre resultado, card y contrato ECL."""
        if self.diagnostics != self.card.diagnostics:
            raise ValueError("card.diagnostics debe coincidir con diagnostics.")
        if (
            self.forward_term_structure_frame is not None
            and self.card.output_columns != _FORWARD_TERM_STRUCTURE_COLUMNS
        ):
            raise ValueError("card.output_columns debe listar las columnas canónicas SDD-20 §6.")
        if (self.forward_term_structure_frame is None) != (
            self.ecl_input.term_structure_frame is None
        ):
            raise ValueError("ecl_input.term_structure_frame debe coincidir con la salida forward.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value

    def term_structure(self) -> pandas.DataFrame | None:
        """Retorna la term-structure forward-looking tidy o ``None`` si no existe.

        Cumple CT-2: SDD-16 puede consumir esta salida sin que ``forward`` importe ni instancie el
        motor ECL. ``pandas`` se importa perezosamente aquí para mantener liviano
        ``import nikodym.forward.results``.
        """
        frame = self.forward_term_structure_frame
        if frame is None:
            return None

        import pandas as pd

        if not isinstance(frame, pd.DataFrame):
            raise ForwardPredictionError(
                "forward_term_structure_frame debe ser un pandas.DataFrame."
            )
        return cast("pandas.DataFrame", _copy_dataframe(frame))


def _copy_and_validate_dataframe(
    value: Any,
    *,
    expected_columns: tuple[str, ...],
    optional_columns: frozenset[str] = frozenset(),
    field_name: str,
) -> Any:
    if not _is_dataframe_like(value):
        raise ValueError(f"{field_name} debe ser un pandas.DataFrame.")

    copied = _copy_dataframe(value)
    observed_columns = tuple(str(column) for column in copied.columns)
    expected_observed_columns = tuple(
        column
        for column in expected_columns
        if column in observed_columns or column not in optional_columns
    )
    if observed_columns != expected_observed_columns:
        raise ValueError(
            f"{field_name} debe tener exactamente las columnas canónicas de SDD-20 §6."
        )
    return copied


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))


def _copy_dataframe(frame: Any) -> Any:
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include=["float"]).columns:
        series = copied[column]
        zero_mask = series == 0.0
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    for column in copied.select_dtypes(include=["object"]).columns:
        copied[column] = copied[column].map(_normalize_object_cell)
    return copied


def _validate_macro_projection_values(frame: Any) -> None:
    for row in frame.itertuples(index=False):
        values = dict(zip(_MACRO_PROJECTION_COLUMNS, row, strict=True))
        _validate_scenario_name(str(values["scenario"]))
        _normalize_non_negative_float(values["scenario_weight"])
        if _integer_value(values["period"], field_name="period") < 1:
            raise ValueError("period debe ser mayor o igual a 1.")
        time_value = _required_frame_float(values["time_value"], field_name="time_value")
        if time_value < 0.0:
            raise ValueError("time_value debe ser mayor o igual a 0.")
        _validate_non_empty_text(str(values["macro_variable"]), field_name="macro_variable")
        _validate_non_empty_text(str(values["method"]), field_name="method")
        _validate_non_empty_text(str(values["model_id"]), field_name="model_id")


def _validate_scenario_weight_values(frame: Any) -> None:
    observed_sum = 0.0
    for row in frame.itertuples(index=False):
        values = dict(zip(_SCENARIO_WEIGHT_COLUMNS, row, strict=True))
        _validate_scenario_name(str(values["scenario"]))
        observed_sum += _normalize_non_negative_float(values["weight"])
        source = str(values["source"])
        if source not in {"config", "default_a_confirmar"}:
            raise ValueError("scenario_weight_frame.source debe ser config o default_a_confirmar.")
    if not math.isclose(observed_sum, 1.0, rel_tol=0.0, abs_tol=_FLOAT_ATOL):
        raise ValueError("Los pesos de escenario deben sumar 1.")


def _validate_forward_term_structure_values(frame: Any) -> None:
    previous_by_curve: dict[tuple[Any, ...], tuple[int, float, float]] = {}
    columns = tuple(str(column) for column in frame.columns)
    for row in frame.itertuples(index=False):
        values = dict(zip(columns, row, strict=True))
        period = _integer_value(values["period"], field_name="period")
        if period < 1:
            raise ValueError("period debe ser mayor o igual a 1.")
        _validate_scenario_name(str(values["scenario"]))
        _validate_basis_fields(values)
        time_value = _required_frame_float(values["time_value"], field_name="time_value")
        if time_value < 0.0:
            raise ValueError("time_value debe ser mayor o igual a 0.")
        _normalize_non_negative_float(values["scenario_weight"])
        hazard = _optional_probability(values["hazard"], field_name="hazard")
        survival = _required_probability(values["survival"], field_name="survival")
        pd_marginal = _required_frame_float(values["pd_marginal"], field_name="pd_marginal")
        if pd_marginal < 0.0:
            raise ValueError("pd_marginal debe ser mayor o igual a 0.")
        pd_cumulative = _required_probability(
            values["pd_cumulative"],
            field_name="pd_cumulative",
        )
        for field_name in (
            "pd_marginal_base",
            "pd_cumulative_base",
            "ttc_reversion_weight",
        ):
            _optional_probability(values[field_name], field_name=field_name)
        for field_name in ("lgd", "lgd_base"):
            if field_name in values:
                _optional_probability(values[field_name], field_name=field_name)
        _optional_frame_float(values["satellite_adjustment"], field_name="satellite_adjustment")
        _check_pd_cumulative_consistency(survival, pd_cumulative)

        curve_key = _curve_key(values)
        previous = previous_by_curve.get(curve_key)
        previous_survival = 1.0
        if previous is not None:
            previous_period, previous_survival, previous_cumulative = previous
            if period <= previous_period:
                raise ValueError("period debe crecer estrictamente dentro de cada curva.")
            if pd_cumulative < previous_cumulative - _FLOAT_ATOL:
                raise ValueError("pd_cumulative no puede decrecer dentro de una curva.")
        if hazard is not None and not math.isclose(
            previous_survival * hazard,
            pd_marginal,
            rel_tol=_FLOAT_RTOL,
            abs_tol=_FLOAT_ATOL,
        ):
            raise ValueError("pd_marginal debe ser survival(t-1) * hazard.")
        previous_by_curve[curve_key] = (period, survival, pd_cumulative)


def _validate_basis_fields(values: Mapping[str, Any]) -> None:
    if values["pd_basis"] != "pit":
        raise ValueError("pd_basis debe ser pit en la salida forward.")
    if values["basis_state"] not in {"pit", "blended", "ttc"}:
        raise ValueError("basis_state debe ser pit, blended o ttc.")


def _curve_key(values: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _missing_to_none(values["row_id"]),
        _missing_to_none(values["segment"]),
        _missing_to_none(values["partition"]),
        _missing_to_none(values["source_model"]),
        _missing_to_none(values["scenario"]),
        _missing_to_none(values["method"]),
        _missing_to_none(values["pd_source"]),
    )


def _missing_to_none(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _required_probability(value: Any, *, field_name: str) -> float:
    normalized = _required_frame_float(value, field_name=field_name)
    _check_unit_interval(normalized, field_name=field_name)
    return normalized


def _optional_probability(value: Any, *, field_name: str) -> float | None:
    if _is_missing_float(value):
        return None
    normalized = _required_probability(value, field_name=field_name)
    return normalized


def _required_frame_float(value: Any, *, field_name: str) -> float:
    try:
        return _normalize_required_float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} debe ser un número finito.") from exc


def _optional_frame_float(value: Any, *, field_name: str) -> float | None:
    if _is_missing_float(value):
        return None
    try:
        return _normalize_required_float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} debe ser None o un número finito.") from exc


def _is_missing_float(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _check_unit_interval(value: float, *, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} debe estar en [0, 1].")


def _check_pd_cumulative_consistency(survival: float, pd_cumulative: float) -> None:
    expected = 1.0 - survival
    if not math.isclose(pd_cumulative, expected, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL):
        raise ValueError("pd_cumulative debe ser igual a 1 - survival dentro de tolerancia.")


def _validate_scenario_name(value: str) -> str:
    normalized = _validate_non_empty_text(value, field_name="scenario")
    if normalized in _RESERVED_SCENARIOS:
        raise ValueError("scenario no puede ser mean ni average.")
    return normalized


def _validate_string_tuple(
    value: tuple[str, ...],
    *,
    field_name: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not allow_empty and not value:
        raise ValueError(f"{field_name} no puede estar vacío.")
    for item in value:
        _validate_non_empty_text(item, field_name=field_name)
    return value


def _validate_non_empty_text(value: str, *, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} no puede estar vacío.")
    return value


def _normalize_optional_text(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        if value.strip():
            return value
        raise ValueError("Los textos opcionales no pueden estar vacíos.")
    return value


def _normalize_dependency_versions(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): str(item) for key, item in value.items()}
    return value


def _integer_value(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} debe ser entero.")
    return value


def _normalize_time_value(value: Any) -> str | int | float | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise ValueError("input_time_range no puede contener booleanos.")
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return _normalize_required_float(value)
    raise ValueError("input_time_range debe contener texto, enteros, floats o None.")


def _normalize_non_negative_float(value: Any) -> float:
    normalized = _normalize_required_float(value)
    if normalized < 0.0:
        raise ValueError("Los valores float deben ser mayores o iguales a 0.")
    return normalized


def _normalize_required_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Los valores float deben ser números finitos.")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Los valores float deben ser números finitos.")
        return _normalize_float(float(value))
    if not isinstance(value, Real):
        raise ValueError("Los valores float deben ser números finitos.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("Los valores float deben ser números finitos.")
    return _normalize_float(candidate)


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value


def _normalize_object_cell(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        if value.is_finite() and float(value) == 0.0:
            return 0.0
        return value
    if isinstance(value, Real):
        candidate = float(value)
        if math.isfinite(candidate) and candidate == 0.0:
            return 0.0
    return value


def _normalize_stat_value(value: Any) -> float | int | str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return _normalize_float(float(value))
    if isinstance(value, Real):
        candidate = float(value)
        if not math.isfinite(candidate):
            return None
        return _normalize_float(candidate)
    return str(value)


def _normalize_metric_payload(value: Any) -> Any:
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return _normalize_float(float(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return _normalize_float(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_metric_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_metric_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_metric_payload(item) for item in value)
    return copy.deepcopy(value)


def _default_metric_sections() -> dict[str, Any]:
    return {key: {} for key in _METRIC_SECTION_KEYS}


def _with_required_metric_sections(value: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    for key in _METRIC_SECTION_KEYS:
        if key not in normalized:
            normalized[key] = {}
    return normalized
