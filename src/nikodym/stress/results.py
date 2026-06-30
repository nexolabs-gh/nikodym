"""DTOs puros de resultados de stress testing (SDD-21 §4/§6).

Este módulo fija los contenedores Pydantic publicados por ``stress``: resultados por escenario,
barridos de sensibilidad, reverse stress, diagnósticos, tarjeta CT-2 y resultado agregado. No
ejecuta shocks, no calcula ECL/provisiones y no importa ``pandas``, ``numpy``, ``scipy``,
``statsmodels`` ni ``nikodym.provisioning`` en runtime al cargar el módulo.

``StressResult.term_structure()`` cumple CT-2: devuelve la term-structure estresada tidy cuando
``publish_stressed_term_structure=True`` y ``None`` solo si la publicación fue deshabilitada
explícitamente. ``tidy()`` devuelve la tabla de impactos por escenario/severidad/métrica. Las
colecciones mutables y DataFrames se copian defensivamente al validar y al acceder; los floats
publicados normalizan ``-0.0`` como ``0.0``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from decimal import Decimal
from itertools import pairwise
from numbers import Integral, Real
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    import pandas

    DataFrameLike: TypeAlias = pandas.DataFrame
else:
    DataFrameLike: TypeAlias = Any

_SCENARIO_FRAME_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "base_forward_scenario",
    "severity",
    "macro_variable",
    "operation",
    "shock_value",
    "applied_shock",
    "period",
    "source",
    "warning_codes",
)
_STRESS_TERM_STRUCTURE_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "severity",
    "base_forward_scenario",
    "row_id",
    "segment",
    "partition",
    "source_model",
    "period",
    "time_value",
    "macro_variable_set",
    "hazard_base",
    "hazard_stress",
    "survival_stress",
    "pd_marginal_base",
    "pd_marginal_stress",
    "pd_cumulative_base",
    "pd_cumulative_stress",
    "lgd_base",
    "lgd_stress",
    "pd_basis",
    "basis_state",
    "satellite_adjustment_base",
    "satellite_adjustment_stress",
    "warning_codes",
)
_IMPACT_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "severity",
    "metric",
    "value_base",
    "value_stress",
    "absolute_delta",
    "relative_delta",
    "group_key",
    "period",
    "engine_source",
    "warning_codes",
)
_REVERSE_PATH_COLUMNS: tuple[str, ...] = (
    "target_name",
    "iteration",
    "lo",
    "hi",
    "mid",
    "metric_value",
    "threshold",
    "decision",
)
_SCENARIO_OPTIONAL_MISSING_COLUMNS: frozenset[str] = frozenset({"warning_codes"})
_STRESS_TERM_STRUCTURE_OPTIONAL_MISSING_COLUMNS: frozenset[str] = frozenset(
    {
        "hazard_base",
        "lgd_base",
        "lgd_stress",
        "partition",
        "pd_cumulative_base",
        "pd_marginal_base",
        "row_id",
        "satellite_adjustment_base",
        "satellite_adjustment_stress",
        "segment",
        "warning_codes",
    }
)
_IMPACT_OPTIONAL_MISSING_COLUMNS: frozenset[str] = frozenset(
    {"period", "relative_delta", "warning_codes"}
)
_METRIC_SECTION_KEYS: tuple[str, ...] = (
    "scenario_impacts",
    "sensitivity_curves",
    "reverse_stress",
    "term_structure_summary",
    "falta_dato",
)
_SCENARIO_KINDS: frozenset[str] = frozenset({"severe", "custom", "sensitivity", "reverse"})
_OPERATIONS: frozenset[str] = frozenset({"additive", "relative"})
_METRICS: frozenset[str] = frozenset(
    {"pd_marginal", "pd_cumulative", "lgd", "ecl", "provision", "loss", "ratio"}
)
_PROBABILITY_METRICS: frozenset[str] = frozenset({"pd_marginal", "pd_cumulative", "lgd"})
_NON_NEGATIVE_METRICS: frozenset[str] = frozenset({"ecl", "provision", "loss", "ratio"})
_ENGINE_SOURCES: frozenset[str] = frozenset({"forward_only", "ecl_engine", "provision_engine"})
_BASIS_STATES: frozenset[str] = frozenset({"pit", "blended", "ttc"})
_REVERSE_DECISIONS: frozenset[str] = frozenset({"move_lo", "move_hi", "converged"})
_RESERVED_SCENARIOS: frozenset[str] = frozenset({"mean", "average", "weighted_mean_input"})
_FLOAT_ATOL = 1e-12
_FLOAT_RTOL = 1e-12

__all__ = [
    "ReverseStressResult",
    "StressCard",
    "StressDiagnostics",
    "StressResult",
    "StressScenarioResult",
    "StressSensitivityResult",
]


class StressScenarioResult(BaseModel):
    """Resultado publicado para un escenario/severidad de stress."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"impact_frame", "stressed_macro_frame", "stressed_term_structure_frame"}
    )

    scenario_name: str
    scenario_kind: Literal["severe", "custom", "sensitivity", "reverse"]
    severity: float
    stressed_macro_frame: DataFrameLike | None
    stressed_term_structure_frame: DataFrameLike | None
    impact_frame: DataFrameLike
    warning_codes: tuple[str, ...] = ()

    @field_validator("scenario_name")
    @classmethod
    def _valida_scenario_name(cls, value: str) -> str:
        """Valida nombre de escenario no vacío ni reservado."""
        return _validate_scenario_name(value)

    @field_validator("severity", mode="before")
    @classmethod
    def _normaliza_severity(cls, value: Any) -> float:
        """Exige severidad finita y no negativa."""
        return _normalize_non_negative_float(value)

    @field_validator("stressed_macro_frame", mode="before")
    @classmethod
    def _copia_macro_frame(cls, value: Any) -> Any:
        """Copia y valida el frame de shocks macro cuando fue publicado."""
        if value is None:
            return None
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_SCENARIO_FRAME_COLUMNS,
            field_name="stressed_macro_frame",
            optional_missing_columns=_SCENARIO_OPTIONAL_MISSING_COLUMNS,
        )
        _validate_scenario_frame_values(copied)
        return copied

    @field_validator("stressed_term_structure_frame", mode="before")
    @classmethod
    def _copia_term_structure(cls, value: Any) -> Any:
        """Copia y valida la term-structure estresada cuando fue publicada."""
        if value is None:
            return None
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_STRESS_TERM_STRUCTURE_COLUMNS,
            field_name="stressed_term_structure_frame",
            optional_missing_columns=_STRESS_TERM_STRUCTURE_OPTIONAL_MISSING_COLUMNS,
        )
        _validate_stress_term_structure_values(copied)
        return copied

    @field_validator("impact_frame", mode="before")
    @classmethod
    def _copia_impact_frame(cls, value: Any) -> Any:
        """Copia y valida impactos tidy SDD-21 §6."""
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_IMPACT_COLUMNS,
            field_name="impact_frame",
            optional_missing_columns=_IMPACT_OPTIONAL_MISSING_COLUMNS,
        )
        _validate_impact_values(copied)
        return copied

    @field_validator("warning_codes")
    @classmethod
    def _valida_warning_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida códigos de warning declarativos."""
        return _validate_string_tuple(value, field_name="warning_codes")

    @model_validator(mode="after")
    def _check_frames_del_escenario(self) -> StressScenarioResult:
        """Valida que los frames publicados pertenezcan al escenario envolvente."""
        _validate_scenario_context_frame(
            self.stressed_macro_frame,
            field_name="stressed_macro_frame",
            scenario_name=self.scenario_name,
            scenario_kind=self.scenario_kind,
            severity=self.severity,
        )
        _validate_scenario_context_frame(
            self.stressed_term_structure_frame,
            field_name="stressed_term_structure_frame",
            scenario_name=self.scenario_name,
            scenario_kind=self.scenario_kind,
            severity=self.severity,
        )
        _validate_scenario_context_frame(
            self.impact_frame,
            field_name="impact_frame",
            scenario_name=self.scenario_name,
            scenario_kind=self.scenario_kind,
            severity=self.severity,
        )
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames del resultado por escenario."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value


class StressSensitivityResult(BaseModel):
    """Resultado publicado para un barrido determinista de sensibilidad."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"baseline_metric_frame", "sensitivity_frame"}
    )

    sweep_name: str
    factor: str
    severity_grid: tuple[float, ...]
    sensitivity_frame: DataFrameLike
    baseline_metric_frame: DataFrameLike
    monotonicity_flag: Literal["increasing", "decreasing", "flat", "non_monotonic"]

    @field_validator("sweep_name", "factor")
    @classmethod
    def _valida_texto(cls, value: str) -> str:
        """Valida identificadores no vacíos."""
        return _validate_non_empty_text(value, field_name="sweep_name/factor")

    @field_validator("severity_grid", mode="before")
    @classmethod
    def _valida_severity_grid(cls, value: Any) -> tuple[float, ...]:
        """Valida grilla de severidad finita, no negativa y estrictamente creciente."""
        try:
            raw_grid = tuple(value)
        except TypeError as exc:
            raise ValueError("severity_grid debe ser una colección de severidades.") from exc
        grid = tuple(_normalize_non_negative_float(item) for item in raw_grid)
        if not grid:
            raise ValueError("severity_grid no puede estar vacío.")
        for previous, current in pairwise(grid):
            if current <= previous:
                raise ValueError("severity_grid debe crecer estrictamente.")
        return grid

    @field_validator("sensitivity_frame", mode="before")
    @classmethod
    def _copia_sensitivity_frame(cls, value: Any) -> Any:
        """Copia y valida impactos tidy del barrido."""
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_IMPACT_COLUMNS,
            field_name="sensitivity_frame",
            optional_missing_columns=_IMPACT_OPTIONAL_MISSING_COLUMNS,
        )
        _validate_impact_values(copied)
        return copied

    @field_validator("baseline_metric_frame", mode="before")
    @classmethod
    def _copia_baseline_metric_frame(cls, value: Any) -> Any:
        """Copia y valida el baseline comparable del barrido."""
        copied = _copy_required_dataframe(value, field_name="baseline_metric_frame")
        _validate_no_nonfinite_frame(
            copied,
            field_name="baseline_metric_frame",
            allow_none=False,
        )
        return copied

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames de sensibilidad."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value


class ReverseStressResult(BaseModel):
    """Resultado publicado por reverse stress monotónico.

    La convención de ``direction='at_most'`` queda fijada para B21.5: el motor debe reportar la
    menor severidad encontrada que cumple ``M(a) <= threshold`` dentro de tolerancias.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset({"reverse_path_frame"})

    target_name: str
    metric: str
    threshold: float
    direction: Literal["at_least", "at_most"]
    severity: float
    metric_value: float
    iterations: int
    bracket: tuple[float, float]
    converged: bool
    reverse_path_frame: DataFrameLike

    @field_validator("target_name", "metric")
    @classmethod
    def _valida_textos(cls, value: str) -> str:
        """Valida textos declarativos no vacíos."""
        return _validate_non_empty_text(value, field_name="target_name/metric")

    @field_validator("threshold", "metric_value", mode="before")
    @classmethod
    def _normaliza_float(cls, value: Any) -> float:
        """Exige floats finitos publicados por reverse stress."""
        return _normalize_required_float(value)

    @field_validator("severity", mode="before")
    @classmethod
    def _normaliza_severity(cls, value: Any) -> float:
        """Exige severidad reverse finita y no negativa."""
        return _normalize_non_negative_float(value)

    @field_validator("iterations", mode="before")
    @classmethod
    def _valida_iterations(cls, value: Any) -> int:
        """Valida iteraciones de bisección no negativas."""
        iterations = _integer_value(value, field_name="iterations")
        if iterations < 0:
            raise ValueError("iterations debe ser mayor o igual a 0.")
        return iterations

    @field_validator("bracket", mode="before")
    @classmethod
    def _valida_bracket(cls, value: Any) -> tuple[float, float]:
        """Valida bracket finito, no negativo y ordenado."""
        try:
            raw_bracket = tuple(value)
        except TypeError as exc:
            raise ValueError("bracket debe tener dos extremos.") from exc
        bracket = tuple(_normalize_non_negative_float(item) for item in raw_bracket)
        if len(bracket) != 2:
            raise ValueError("bracket debe tener dos extremos.")
        lo, hi = bracket
        if lo >= hi:
            raise ValueError("bracket debe cumplir lo < hi.")
        return (lo, hi)

    @field_validator("reverse_path_frame", mode="before")
    @classmethod
    def _copia_reverse_path(cls, value: Any) -> Any:
        """Copia y valida el path de bisección publicado."""
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_REVERSE_PATH_COLUMNS,
            field_name="reverse_path_frame",
        )
        _validate_reverse_path_values(copied)
        return copied

    @model_validator(mode="after")
    def _check_bracket_y_target(self) -> ReverseStressResult:
        """Valida coherencia auditable del resultado reverse stress."""
        lo, hi = self.bracket
        if not lo <= self.severity <= hi:
            raise ValueError("severity debe caer dentro del bracket.")
        if self.metric not in _METRICS:
            raise ValueError("metric no es una métrica de stress reconocida.")
        _validate_metric_threshold(self.metric, self.threshold)
        _validate_metric_value(self.metric, self.metric_value, field_name="metric_value")
        if self.iterations > 0 and _dataframe_is_empty(self.reverse_path_frame):
            raise ValueError("reverse_path_frame no puede estar vacío cuando iterations > 0.")
        _validate_reverse_result_path(
            self.reverse_path_frame,
            target_name=self.target_name,
            metric=self.metric,
            threshold=self.threshold,
            direction=self.direction,
            bracket=self.bracket,
            severity=self.severity,
            metric_value=self.metric_value,
            iterations=self.iterations,
            converged=self.converged,
        )
        if self.converged:
            _validate_reverse_direction(
                self.direction,
                threshold=self.threshold,
                metric_value=self.metric_value,
            )
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copia defensiva del path reverse cuando existe."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value


class StressDiagnostics(BaseModel):
    """Diagnósticos agregados de stress sin depender de engines económicos."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"dependency_versions"})

    scenario_count: int = Field(ge=0)
    sensitivity_count: int = Field(ge=0)
    reverse_count: int = Field(ge=0)
    falta_dato_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()
    dependency_versions: dict[str, str] = Field(default_factory=dict)

    @field_validator("falta_dato_codes", "warning_codes")
    @classmethod
    def _valida_codigos(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida códigos declarativos no vacíos."""
        return _validate_string_tuple(value, field_name="diagnostic_codes")

    @field_validator("dependency_versions", mode="before")
    @classmethod
    def _copia_dependency_versions(cls, value: Any) -> Any:
        """Copia versiones de dependencias preservando orden de inserción."""
        return _normalize_dependency_versions(value)

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class StressCard(BaseModel):
    """Resumen determinista CT-2 para governance, inventario y reportes stress."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"metric_sections", "summary"})

    summary: dict[str, str | int | float | bool]
    metric_sections: dict[str, object] = Field(default_factory=lambda: _default_metric_sections())
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @field_validator("summary", mode="before")
    @classmethod
    def _copia_summary(cls, value: Any) -> Any:
        """Copia resumen CT-2 y rechaza métricas no finitas."""
        if isinstance(value, Mapping):
            _ensure_no_missing_or_nonfinite(value, field_name="summary")
            return {
                _normalize_public_string_atom(key): _normalize_summary_value(item)
                for key, item in value.items()
            }
        return value

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia y completa secciones CT-2 de SDD-21 §9."""
        if value is None:
            normalized: dict[str, Any] = {}
        elif isinstance(value, Mapping):
            normalized = _normalize_metric_payload(value)
        else:
            return value
        return _with_required_metric_sections(normalized)

    @field_validator("assumptions", "limitations")
    @classmethod
    def _valida_textos(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida textos declarativos de card."""
        return _validate_string_tuple(value, field_name="card_texts")

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class StressResult(BaseModel):
    """Contenedor agregado de artefactos publicados por la capa ``stress``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"stress_impact_frame", "stress_term_structure_frame"}
    )

    scenario_results: tuple[StressScenarioResult, ...]
    sensitivity_results: tuple[StressSensitivityResult, ...] = ()
    reverse_results: tuple[ReverseStressResult, ...] = ()
    publish_stressed_term_structure: bool = True
    stress_term_structure_frame: DataFrameLike | None
    stress_impact_frame: DataFrameLike
    diagnostics: StressDiagnostics
    card: StressCard

    @field_validator("stress_term_structure_frame", mode="before")
    @classmethod
    def _copia_stress_term_structure(cls, value: Any) -> Any:
        """Copia y valida la term-structure stress CT-2 cuando fue publicada."""
        if value is None:
            return None
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_STRESS_TERM_STRUCTURE_COLUMNS,
            field_name="stress_term_structure_frame",
            optional_missing_columns=_STRESS_TERM_STRUCTURE_OPTIONAL_MISSING_COLUMNS,
        )
        _validate_stress_term_structure_values(copied)
        return copied

    @field_validator("stress_impact_frame", mode="before")
    @classmethod
    def _copia_stress_impact(cls, value: Any) -> Any:
        """Copia y valida impactos agregados tidy."""
        copied = _copy_and_validate_dataframe(
            value,
            expected_columns=_IMPACT_COLUMNS,
            field_name="stress_impact_frame",
            optional_missing_columns=_IMPACT_OPTIONAL_MISSING_COLUMNS,
        )
        _validate_impact_values(copied)
        return copied

    @model_validator(mode="after")
    def _check_consistencia(self) -> StressResult:
        """Valida que diagnostics cuente los resultados envueltos."""
        if self.publish_stressed_term_structure and self.stress_term_structure_frame is None:
            raise ValueError(
                "stress_term_structure_frame es obligatorio cuando "
                "publish_stressed_term_structure=True."
            )
        if (
            not self.publish_stressed_term_structure
            and self.stress_term_structure_frame is not None
        ):
            raise ValueError(
                "stress_term_structure_frame debe ser None cuando "
                "publish_stressed_term_structure=False."
            )
        if self.publish_stressed_term_structure:
            if any(
                result.stressed_term_structure_frame is None for result in self.scenario_results
            ):
                raise ValueError(
                    "scenario_results no puede omitir stressed_term_structure_frame cuando "
                    "publish_stressed_term_structure=True."
                )
        elif any(
            result.stressed_term_structure_frame is not None for result in self.scenario_results
        ):
            raise ValueError(
                "scenario_results debe omitir stressed_term_structure_frame cuando "
                "publish_stressed_term_structure=False."
            )
        if self.diagnostics.scenario_count != len(self.scenario_results):
            raise ValueError("diagnostics.scenario_count debe coincidir con scenario_results.")
        if self.diagnostics.sensitivity_count != len(self.sensitivity_results):
            raise ValueError(
                "diagnostics.sensitivity_count debe coincidir con sensitivity_results."
            )
        if self.diagnostics.reverse_count != len(self.reverse_results):
            raise ValueError("diagnostics.reverse_count debe coincidir con reverse_results.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el agregado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value

    def term_structure(self) -> pandas.DataFrame | None:
        """Retorna la term-structure estresada tidy o ``None`` si no fue publicada.

        Cumple CT-2: SDD-16/17 y reportes pueden consumir esta salida cuando existe. ``pandas`` se
        importa perezosamente aquí para mantener liviano ``import nikodym.stress.results``.
        """
        frame = self.stress_term_structure_frame
        if frame is None:
            return None

        import pandas as pd

        if not isinstance(frame, pd.DataFrame):
            from nikodym.stress.exceptions import StressOutputError

            raise StressOutputError("stress_term_structure_frame debe ser un pandas.DataFrame.")
        return cast("pandas.DataFrame", _copy_dataframe(frame))

    def tidy(self) -> pandas.DataFrame:
        """Retorna una copia de la tabla de impactos de stress."""
        frame = self.stress_impact_frame

        import pandas as pd

        if not isinstance(frame, pd.DataFrame):
            from nikodym.stress.exceptions import StressOutputError

            raise StressOutputError("stress_impact_frame debe ser un pandas.DataFrame.")
        return cast("pandas.DataFrame", _copy_dataframe(frame))


def _copy_and_validate_dataframe(
    value: Any,
    *,
    expected_columns: tuple[str, ...],
    field_name: str,
    optional_missing_columns: frozenset[str] = frozenset(),
) -> Any:
    copied = _copy_required_dataframe(value, field_name=field_name)
    observed_columns = tuple(str(column) for column in copied.columns)
    if observed_columns != expected_columns:
        raise ValueError(
            f"{field_name} debe tener exactamente las columnas canónicas de SDD-21 §6."
        )
    _normalize_optional_missing_cells(copied, optional_missing_columns=optional_missing_columns)
    _validate_no_nonfinite_frame(copied, field_name=field_name)
    return copied


def _copy_required_dataframe(value: Any, *, field_name: str) -> Any:
    if not _is_dataframe_like(value):
        raise ValueError(f"{field_name} debe ser un pandas.DataFrame.")
    return _copy_dataframe(value)


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))


def _copy_dataframe(frame: Any) -> Any:
    copied = frame.copy(deep=True)
    if not all(hasattr(copied, attribute) for attribute in ("iloc", "iat")):
        return copied
    for column_position in range(len(copied.columns)):
        series = copied.iloc[:, column_position]
        dtype_kind = getattr(series.dtype, "kind", None)
        if dtype_kind == "f":
            zero_mask = series == 0.0
            if bool(zero_mask.any()):
                copied.iloc[:, column_position] = series.mask(zero_mask, 0.0)
        elif dtype_kind == "O":
            copied.iloc[:, column_position] = series.astype("object")
            for row_position in range(len(copied.index)):
                copied.iat[row_position, column_position] = _normalize_frame_cell(
                    copied.iat[row_position, column_position]
                )
    return copied


def _dataframe_is_empty(frame: Any) -> bool:
    return bool(getattr(frame, "empty", False))


def _normalize_optional_missing_cells(
    frame: Any,
    *,
    optional_missing_columns: frozenset[str],
) -> None:
    if not optional_missing_columns or not all(
        hasattr(frame, attribute) for attribute in ("columns", "iat", "iloc", "index")
    ):
        return

    columns = tuple(str(column) for column in frame.columns)
    for column_position, column_name in enumerate(columns):
        if column_name not in optional_missing_columns:
            continue

        series = frame.iloc[:, column_position].astype("object")
        changed = False
        for row_position in range(len(frame.index)):
            if _is_missing_optional_cell(series.iat[row_position]):
                series.iat[row_position] = None
                changed = True
        if changed:
            frame[frame.columns[column_position]] = series


def _validate_scenario_frame_values(frame: Any) -> None:
    for row in frame.itertuples(index=False):
        values = dict(zip(_SCENARIO_FRAME_COLUMNS, row, strict=True))
        _validate_scenario_name(values["stress_scenario"])
        _validate_kind(values["scenario_kind"])
        _validate_scenario_name(values["base_forward_scenario"])
        _normalize_non_negative_float(values["severity"])
        _validate_non_empty_text(values["macro_variable"], field_name="macro_variable")
        if values["operation"] not in _OPERATIONS:
            raise ValueError("operation debe ser additive o relative.")
        _normalize_required_float(values["shock_value"])
        _normalize_required_float(values["applied_shock"])
        period = _integer_value(values["period"], field_name="period")
        if period < 1:
            raise ValueError("period debe ser mayor o igual a 1.")
        _validate_non_empty_text(values["source"], field_name="source")
        _validate_warning_codes_cell(values["warning_codes"])


def _validate_stress_term_structure_values(frame: Any) -> None:
    previous_by_curve: dict[tuple[Any, ...], tuple[int, float, float]] = {}
    for row in frame.itertuples(index=False):
        values = dict(zip(_STRESS_TERM_STRUCTURE_COLUMNS, row, strict=True))
        _validate_scenario_name(values["stress_scenario"])
        _validate_kind(values["scenario_kind"])
        severity = _normalize_non_negative_float(values["severity"])
        _validate_scenario_name(values["base_forward_scenario"])
        _validate_optional_scalar_cell(values["row_id"], field_name="row_id")
        _validate_optional_scalar_cell(values["segment"], field_name="segment")
        _validate_optional_scalar_cell(values["partition"], field_name="partition")
        period = _integer_value(values["period"], field_name="period")
        if period < 1:
            raise ValueError("period debe ser mayor o igual a 1.")
        _required_non_negative_float(values["time_value"], field_name="time_value")
        _validate_non_empty_text(values["source_model"], field_name="source_model")
        _validate_macro_variable_set_cell(values["macro_variable_set"])
        hazard_stress = _required_probability(values["hazard_stress"], field_name="hazard_stress")
        survival_stress = _required_probability(
            values["survival_stress"],
            field_name="survival_stress",
        )
        pd_marginal_stress = _required_non_negative_float(
            values["pd_marginal_stress"],
            field_name="pd_marginal_stress",
        )
        pd_cumulative_stress = _required_probability(
            values["pd_cumulative_stress"],
            field_name="pd_cumulative_stress",
        )
        _optional_probability(values["hazard_base"], field_name="hazard_base")
        _optional_probability(values["pd_marginal_base"], field_name="pd_marginal_base")
        _optional_probability(values["pd_cumulative_base"], field_name="pd_cumulative_base")
        _optional_probability(values["lgd_base"], field_name="lgd_base")
        _optional_probability(values["lgd_stress"], field_name="lgd_stress")
        _optional_frame_float(
            values["satellite_adjustment_base"],
            field_name="satellite_adjustment_base",
        )
        _optional_frame_float(
            values["satellite_adjustment_stress"],
            field_name="satellite_adjustment_stress",
        )
        _validate_non_empty_text(values["pd_basis"], field_name="pd_basis")
        if values["basis_state"] not in _BASIS_STATES:
            raise ValueError("basis_state debe ser pit, blended o ttc.")
        _validate_warning_codes_cell(values["warning_codes"])
        _check_pd_cumulative_consistency(survival_stress, pd_cumulative_stress)

        curve_key = _stress_curve_key(values, severity)
        previous = previous_by_curve.get(curve_key)
        previous_survival = 1.0
        if previous is not None:
            previous_period, previous_survival, previous_cumulative = previous
            if period <= previous_period:
                raise ValueError("period debe crecer estrictamente dentro de cada curva.")
            if pd_cumulative_stress < previous_cumulative - _FLOAT_ATOL:
                raise ValueError("pd_cumulative_stress no puede decrecer dentro de una curva.")
        if not math.isclose(
            previous_survival * hazard_stress,
            pd_marginal_stress,
            rel_tol=_FLOAT_RTOL,
            abs_tol=_FLOAT_ATOL,
        ):
            raise ValueError("pd_marginal_stress debe ser survival_stress(t-1) * hazard_stress.")
        previous_by_curve[curve_key] = (period, survival_stress, pd_cumulative_stress)


def _validate_impact_values(frame: Any) -> None:
    for row in frame.itertuples(index=False):
        values = dict(zip(_IMPACT_COLUMNS, row, strict=True))
        _validate_scenario_name(values["stress_scenario"])
        _validate_kind(values["scenario_kind"])
        _normalize_non_negative_float(values["severity"])
        metric = _validate_non_empty_text(values["metric"], field_name="metric")
        if metric not in _METRICS:
            raise ValueError("metric no es una métrica de stress reconocida.")
        value_base = _normalize_required_float(values["value_base"])
        value_stress = _normalize_required_float(values["value_stress"])
        _validate_metric_values(metric, value_base, value_stress)
        absolute_delta = _normalize_required_float(values["absolute_delta"])
        if not math.isclose(
            value_stress - value_base,
            absolute_delta,
            rel_tol=_FLOAT_RTOL,
            abs_tol=_FLOAT_ATOL,
        ):
            raise ValueError("absolute_delta debe ser value_stress - value_base.")
        _validate_relative_delta(values["relative_delta"], value_base, absolute_delta)
        period = values["period"]
        if period is not None:
            normalized_period = _optional_integer_value(period, field_name="period")
            if normalized_period < 1:
                raise ValueError("period debe ser mayor o igual a 1.")
        _validate_non_empty_text(values["group_key"], field_name="group_key")
        if values["engine_source"] not in _ENGINE_SOURCES:
            raise ValueError("engine_source debe ser forward_only, ecl_engine o provision_engine.")
        _validate_warning_codes_cell(values["warning_codes"])


def _validate_reverse_path_values(frame: Any) -> None:
    for row in frame.itertuples(index=False):
        values = dict(zip(_REVERSE_PATH_COLUMNS, row, strict=True))
        _validate_non_empty_text(values["target_name"], field_name="target_name")
        iteration = _integer_value(values["iteration"], field_name="iteration")
        if iteration < 0:
            raise ValueError("iteration debe ser mayor o igual a 0.")
        lo = _normalize_non_negative_float(values["lo"])
        hi = _normalize_non_negative_float(values["hi"])
        mid = _normalize_non_negative_float(values["mid"])
        if not lo <= mid <= hi:
            raise ValueError("mid debe caer dentro de [lo, hi].")
        _normalize_required_float(values["metric_value"])
        _normalize_required_float(values["threshold"])
        if values["decision"] not in _REVERSE_DECISIONS:
            raise ValueError("decision debe ser move_lo, move_hi o converged.")


def _validate_reverse_result_path(
    frame: Any,
    *,
    target_name: str,
    metric: str,
    threshold: float,
    direction: str,
    bracket: tuple[float, float],
    severity: float,
    metric_value: float,
    iterations: int,
    converged: bool,
) -> None:
    rows = [
        dict(zip(_REVERSE_PATH_COLUMNS, row, strict=True)) for row in frame.itertuples(index=False)
    ]
    if len(rows) != iterations + 1:
        raise ValueError("reverse_path_frame debe tener una fila por iteración 0..iterations.")

    first = rows[0]
    first_lo = _normalize_required_float(first["lo"])
    first_hi = _normalize_required_float(first["hi"])
    bracket_lo, bracket_hi = bracket
    if not _floats_close(first_lo, bracket_lo) or not _floats_close(first_hi, bracket_hi):
        raise ValueError("reverse_path_frame debe iniciar en el bracket declarado.")

    for expected_iteration, values in enumerate(rows):
        if values["iteration"] != expected_iteration:
            raise ValueError("reverse_path_frame.iteration debe ser la secuencia 0..iterations.")
        if values["target_name"] != target_name:
            raise ValueError("reverse_path_frame.target_name debe coincidir con target_name.")
        lo = _normalize_required_float(values["lo"])
        hi = _normalize_required_float(values["hi"])
        mid = _normalize_required_float(values["mid"])
        path_threshold = _normalize_required_float(values["threshold"])
        path_metric_value = _normalize_required_float(values["metric_value"])
        if not math.isclose(path_threshold, threshold, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL):
            raise ValueError("reverse_path_frame.threshold debe coincidir con threshold.")
        _validate_metric_threshold(metric, path_threshold)
        _validate_metric_value(metric, path_metric_value, field_name="metric_value")
        _validate_reverse_decision_against_threshold(
            values["decision"],
            direction=direction,
            threshold=threshold,
            metric_value=path_metric_value,
        )
        expected_mid = lo + (hi - lo) / 2.0
        if not _floats_close(mid, expected_mid):
            raise ValueError("reverse_path_frame.mid debe ser lo + (hi - lo) / 2.")
        if expected_iteration < iterations:
            _validate_reverse_transition(values, rows[expected_iteration + 1])

    last = rows[-1]
    if converged and last["decision"] != "converged":
        raise ValueError("reverse_path_frame debe terminar en converged si converged=True.")
    if not converged and last["decision"] == "converged":
        raise ValueError("reverse_path_frame no puede terminar en converged si converged=False.")
    if not math.isclose(
        _normalize_required_float(last["mid"]),
        severity,
        rel_tol=_FLOAT_RTOL,
        abs_tol=_FLOAT_ATOL,
    ):
        raise ValueError("severity debe coincidir con el último mid de reverse_path_frame.")
    if not math.isclose(
        _normalize_required_float(last["metric_value"]),
        metric_value,
        rel_tol=_FLOAT_RTOL,
        abs_tol=_FLOAT_ATOL,
    ):
        raise ValueError(
            "metric_value debe coincidir con el último metric_value de reverse_path_frame."
        )


def _validate_reverse_transition(current: Mapping[str, Any], next_row: Mapping[str, Any]) -> None:
    decision = current["decision"]
    if decision == "converged":
        raise ValueError("reverse_path_frame solo puede marcar converged en la última fila.")

    current_lo = _normalize_required_float(current["lo"])
    current_hi = _normalize_required_float(current["hi"])
    current_mid = _normalize_required_float(current["mid"])
    next_lo = _normalize_required_float(next_row["lo"])
    next_hi = _normalize_required_float(next_row["hi"])

    if decision == "move_lo":
        expected_lo = current_mid
        expected_hi = current_hi
    else:
        expected_lo = current_lo
        expected_hi = current_mid

    if not _floats_close(next_lo, expected_lo) or not _floats_close(next_hi, expected_hi):
        raise ValueError("reverse_path_frame.decision debe reconstruir el bracket siguiente.")


def _floats_close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL)


def _validate_scenario_context_frame(
    frame: Any,
    *,
    field_name: str,
    scenario_name: str,
    scenario_kind: str,
    severity: float,
) -> None:
    if frame is None:
        return
    columns = tuple(str(column) for column in frame.columns)
    for row in frame.itertuples(index=False):
        values = dict(zip(columns, row, strict=True))
        if values["stress_scenario"] != scenario_name:
            raise ValueError(f"{field_name}.stress_scenario debe coincidir con scenario_name.")
        if values["scenario_kind"] != scenario_kind:
            raise ValueError(f"{field_name}.scenario_kind debe coincidir con scenario_kind.")
        row_severity = _normalize_non_negative_float(values["severity"])
        if not math.isclose(row_severity, severity, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL):
            raise ValueError(f"{field_name}.severity debe coincidir con severity.")


def _validate_reverse_direction(direction: str, *, threshold: float, metric_value: float) -> None:
    if (
        direction == "at_least"
        and metric_value < threshold
        and not math.isclose(
            metric_value,
            threshold,
            rel_tol=_FLOAT_RTOL,
            abs_tol=_FLOAT_ATOL,
        )
    ):
        raise ValueError(
            "direction=at_least exige metric_value >= threshold cuando converged=True."
        )
    if (
        direction == "at_most"
        and metric_value > threshold
        and not math.isclose(
            metric_value,
            threshold,
            rel_tol=_FLOAT_RTOL,
            abs_tol=_FLOAT_ATOL,
        )
    ):
        raise ValueError("direction=at_most exige metric_value <= threshold cuando converged=True.")


def _validate_reverse_decision_against_threshold(
    decision: Any,
    *,
    direction: str,
    threshold: float,
    metric_value: float,
) -> None:
    if decision == "converged":
        return
    if direction == "at_least":
        expected_decision = (
            "move_hi"
            if metric_value > threshold
            or math.isclose(metric_value, threshold, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL)
            else "move_lo"
        )
    else:
        expected_decision = (
            "move_hi"
            if metric_value < threshold
            or math.isclose(metric_value, threshold, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL)
            else "move_lo"
        )
    if decision != expected_decision:
        raise ValueError("reverse_path_frame.decision debe ser coherente con direction/threshold.")


def _validate_no_nonfinite_frame(
    frame: Any,
    *,
    field_name: str,
    allow_none: bool = True,
) -> None:
    for row in frame.itertuples(index=False):
        for value in row:
            if _contains_nonfinite(value, allow_none=allow_none):
                raise ValueError(f"{field_name} no puede publicar NaN ni infinitos.")


def _contains_nonfinite(value: Any, *, allow_none: bool = True) -> bool:
    if value is None:
        return not allow_none
    if isinstance(value, bool):
        return False
    if _is_missing_optional_cell(value):
        return True
    if isinstance(value, Decimal):
        return not value.is_finite()
    if isinstance(value, Real):
        return not math.isfinite(float(value))
    if isinstance(value, Mapping):
        return any(_contains_nonfinite(key, allow_none=allow_none) for key in value) or any(
            _contains_nonfinite(item, allow_none=allow_none) for item in value.values()
        )
    if isinstance(value, list | tuple | set | frozenset):
        return any(_contains_nonfinite(item, allow_none=allow_none) for item in value)
    return False


def _validate_relative_delta(value: Any, value_base: float, absolute_delta: float) -> None:
    if math.isclose(value_base, 0.0, rel_tol=0.0, abs_tol=_FLOAT_ATOL):
        if value is not None:
            raise ValueError("relative_delta debe ser None cuando value_base es 0.")
        return
    normalized = _normalize_required_float(value)
    expected = absolute_delta / value_base
    if not math.isclose(normalized, expected, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL):
        raise ValueError("relative_delta debe ser absolute_delta / value_base.")


def _validate_metric_values(metric: str, value_base: float, value_stress: float) -> None:
    if metric in _PROBABILITY_METRICS:
        _check_unit_interval(value_base, field_name="value_base")
        _check_unit_interval(value_stress, field_name="value_stress")
    elif metric in _NON_NEGATIVE_METRICS and (value_base < 0.0 or value_stress < 0.0):
        raise ValueError("value_base y value_stress deben ser mayores o iguales a 0.")


def _validate_metric_threshold(metric: str, threshold: float) -> None:
    try:
        _validate_metric_value(metric, threshold, field_name="threshold")
    except ValueError as exc:
        raise ValueError("threshold no pertenece al dominio de la métrica target.") from exc


def _validate_metric_value(metric: str, value: float, *, field_name: str) -> None:
    if metric in _PROBABILITY_METRICS:
        _check_unit_interval(value, field_name=field_name)
    elif metric in _NON_NEGATIVE_METRICS and value < 0.0:
        raise ValueError(f"{field_name} debe ser mayor o igual a 0.")


def _stress_curve_key(values: Mapping[str, Any], severity: float) -> tuple[Any, ...]:
    return (
        _missing_to_none(values["row_id"]),
        _missing_to_none(values["segment"]),
        _missing_to_none(values["partition"]),
        _missing_to_none(values["source_model"]),
        _missing_to_none(values["stress_scenario"]),
        _missing_to_none(values["base_forward_scenario"]),
        severity,
    )


def _missing_to_none(value: Any) -> Any:
    if _is_missing_optional_cell(value):
        return None
    return value


def _validate_kind(value: Any) -> None:
    if value not in _SCENARIO_KINDS:
        raise ValueError("scenario_kind no es válido.")


def _validate_scenario_name(value: Any) -> str:
    normalized = _validate_non_empty_text(value, field_name="scenario")
    if normalized in _RESERVED_SCENARIOS:
        raise ValueError("scenario no puede ser mean, average ni weighted_mean_input.")
    return normalized


def _validate_string_tuple(value: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    for item in value:
        _validate_non_empty_text(item, field_name=field_name)
    return value


def _validate_warning_codes_cell(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, tuple | list):
        raise ValueError("warning_codes debe ser una lista o tupla de textos.")
    if any(not isinstance(item, str) for item in value):
        raise ValueError("warning_codes debe contener textos.")
    _validate_string_tuple(tuple(value), field_name="warning_codes")


def _validate_macro_variable_set_cell(value: Any) -> None:
    if isinstance(value, str):
        _validate_non_empty_text(value, field_name="macro_variable_set")
        return
    if isinstance(value, tuple | list):
        if not value:
            raise ValueError("macro_variable_set no puede estar vacío.")
        if _contains_missing_cell(value):
            raise ValueError("macro_variable_set no puede contener faltantes.")
        return
    raise ValueError("macro_variable_set debe ser texto o una colección no vacía.")


def _validate_optional_scalar_cell(value: Any, *, field_name: str) -> None:
    if value is None:
        return
    if _contains_nonfinite(value, allow_none=False) or isinstance(
        value,
        Mapping | list | tuple | set | frozenset,
    ):
        raise ValueError(f"{field_name} debe ser escalar o None.")


def _contains_missing_cell(value: Any) -> bool:
    if _is_missing_optional_cell(value):
        return True
    if isinstance(value, Mapping):
        return any(_contains_missing_cell(key) for key in value) or any(
            _contains_missing_cell(item) for item in value.values()
        )
    if isinstance(value, list | tuple | set | frozenset):
        return any(_contains_missing_cell(item) for item in value)
    return False


def _validate_non_empty_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} debe ser texto no vacío.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} no puede estar vacío.")
    return normalized


def _integer_value(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} debe ser entero.")
    return value


def _optional_integer_value(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} debe ser entero.")
    if isinstance(value, int):
        return value
    if isinstance(value, Real):
        candidate = float(value)
        if math.isfinite(candidate) and candidate.is_integer():
            return int(candidate)
    raise ValueError(f"{field_name} debe ser entero.")


def _required_probability(value: Any, *, field_name: str) -> float:
    normalized = _normalize_required_float(value)
    _check_unit_interval(normalized, field_name=field_name)
    return normalized


def _optional_probability(value: Any, *, field_name: str) -> float | None:
    if _is_missing_optional_cell(value):
        return None
    return _required_probability(value, field_name=field_name)


def _required_non_negative_float(value: Any, *, field_name: str) -> float:
    normalized = _normalize_required_float(value)
    if normalized < 0.0:
        raise ValueError(f"{field_name} debe ser mayor o igual a 0.")
    return normalized


def _optional_frame_float(value: Any, *, field_name: str) -> float | None:
    if _is_missing_optional_cell(value):
        return None
    try:
        return _normalize_required_float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} debe ser None o un número finito.") from exc


def _is_missing_optional_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, Real):
        return math.isnan(float(value))
    value_type = type(value)
    if value_type.__name__ in {"NAType", "NaTType"} and value_type.__module__.startswith("pandas."):
        return True
    return (
        value_type.__name__ in {"datetime64", "timedelta64"}
        and value_type.__module__.startswith("numpy")
        and str(value) == "NaT"
    )


def _check_unit_interval(value: float, *, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} debe estar en [0, 1].")


def _check_pd_cumulative_consistency(survival: float, pd_cumulative: float) -> None:
    expected = 1.0 - survival
    if not math.isclose(pd_cumulative, expected, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL):
        raise ValueError("pd_cumulative_stress debe ser igual a 1 - survival_stress.")


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


def _normalize_summary_value(value: Any) -> str | int | float | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Decimal):
        return _normalize_float(float(value))
    if isinstance(value, Real):
        return _normalize_float(float(value))
    raise ValueError("summary solo admite str, int, float o bool.")


def _normalize_frame_cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value.is_finite() and float(value) == 0.0:
            return 0.0
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        candidate = float(value)
        if math.isfinite(candidate) and candidate == 0.0:
            return 0.0
    if isinstance(value, Mapping):
        return {
            _normalize_frame_cell(key): _normalize_frame_cell(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_frame_cell(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_frame_cell(item) for item in value)
    if isinstance(value, set):
        return {_normalize_frame_cell(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_normalize_frame_cell(item) for item in value)
    return copy.deepcopy(value)


def _normalize_metric_payload(value: Any) -> Any:
    _ensure_no_missing_or_nonfinite(value, field_name="metric_sections")
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Decimal):
        return _normalize_float(float(value))
    if isinstance(value, Real):
        return _normalize_float(float(value))
    if isinstance(value, Mapping):
        return {
            _normalize_public_string_atom(key): _normalize_metric_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_metric_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_metric_payload(item) for item in value)
    if isinstance(value, set):
        return {_normalize_metric_payload(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_normalize_metric_payload(item) for item in value)
    return copy.deepcopy(value)


def _normalize_dependency_versions(value: Any) -> Any:
    if isinstance(value, Mapping):
        _ensure_no_missing_or_nonfinite(value, field_name="dependency_versions")
        return {
            _normalize_public_string_atom(key): _normalize_public_string_atom(item)
            for key, item in value.items()
        }
    return value


def _ensure_no_missing_or_nonfinite(value: Any, *, field_name: str) -> None:
    if _contains_nonfinite(value, allow_none=False):
        raise ValueError(f"{field_name} no puede contener faltantes, NaN ni infinitos.")


def _normalize_public_string_atom(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Decimal):
        return str(_normalize_float(float(value)))
    if isinstance(value, Real):
        return str(_normalize_float(float(value)))
    return str(value)


def _default_metric_sections() -> dict[str, Any]:
    return {key: {} for key in _METRIC_SECTION_KEYS}


def _with_required_metric_sections(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    for key in _METRIC_SECTION_KEYS:
        if key not in normalized:
            normalized[key] = {}
    return normalized
