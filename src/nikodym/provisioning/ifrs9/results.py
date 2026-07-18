"""DTOs puros de resultados de provisiones IFRS 9 / ECL (SDD-16 §4/§6).

Este módulo fija los contenedores Pydantic publicados por ``provisioning.ifrs9``: registro de
staging por operación, registro de ECL por operación, fila tidy de ECL marginal por
período/escenario, tarjeta CT-2 de gobierno y resultado agregado con ``staging``/``detail``/
``ecl_term_structure``/``summary``. No calcula ECL, no transforma PD y no importa ``pandas``,
``numpy``, ``scipy`` ni ``statsmodels`` en runtime al cargar el módulo; los DataFrames son solo
contrato de I/O validado por estructura para preservar el import liviano del núcleo.

``IfrsProvisionResult.term_structure()`` cumple CT-2 y **nunca** devuelve ``None`` para IFRS 9 (a
diferencia del CMF B-1 agregado): retorna la term-structure de ECL en forma **larga**
``[row_id, scenario, period, time_value, component, value]`` para que SDD-17 (comparativos) y los
reportes consuman el desglose auditable por escenario/período. ``metric_sections`` conserva la
puerta CT-2 como payload aditivo. Las colecciones mutables y DataFrames se copian defensivamente al
validar y al acceder desde los DTOs; los floats publicados normalizan ``-0.0`` como ``0.0``.

Nomenclatura IFRS 9 (regla dura D-CONV-1): ``pd``/``lgd``/``ead``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    import pandas

    DataFrameLike: TypeAlias = pandas.DataFrame
else:
    DataFrameLike: TypeAlias = Any

_STAGING_COLUMNS: tuple[str, ...] = (
    "row_id",
    "portfolio",
    "stage",
    "days_past_due",
    "pd_life_current",
    "pd_life_origination",
    "sicr_triggers",
    "low_credit_risk_exempt",
    "warning_codes",
)
_DETAIL_COLUMNS: tuple[str, ...] = (
    "row_id",
    "portfolio",
    "stage",
    "ead",
    "lgd",
    "eir",
    "pd_12m",
    "pd_life",
    "ecl_12m",
    "ecl_lifetime",
    "ecl_reported",
    "scenario_weights",
    "pd_basis",
    "warning_codes",
)
_ECL_TERM_STRUCTURE_COLUMNS: tuple[str, ...] = (
    "row_id",
    "scenario",
    "period",
    "time_value",
    "pd_marginal",
    "lgd",
    "ead",
    "discount_factor",
    "ecl_marginal",
)
_SUMMARY_COLUMNS: tuple[str, ...] = (
    "portfolio",
    "stage",
    "scenario",
    "n_rows",
    "total_ead",
    "total_ecl_reported",
    "coverage_ratio",
    "warning_codes",
)
# Componentes que se apilan en la forma larga de ``term_structure()`` (orden canónico auditable).
_ECL_TERM_COMPONENTS: tuple[str, ...] = (
    "pd_marginal",
    "lgd",
    "ead",
    "discount_factor",
    "ecl_marginal",
)
# Columnas de la salida larga CT-2 de ``IfrsProvisionResult.term_structure()``.
_TERM_STRUCTURE_OUTPUT_COLUMNS: tuple[str, ...] = (
    "row_id",
    "scenario",
    "period",
    "time_value",
    "component",
    "value",
)

# Tolerancia absoluta para exigir que los pesos de escenario sumen 1 (SDD-16 §5/§6).
_WEIGHT_SUM_TOL: float = 1e-9
_FLOAT_RTOL: float = 1e-12
_FLOAT_ATOL: float = 1e-12

__all__ = [
    "IfrsEclRecord",
    "IfrsEclTermRecord",
    "IfrsProvisionCard",
    "IfrsProvisionResult",
    "IfrsStageRecord",
]


class IfrsStageRecord(BaseModel):
    """Registro de staging IFRS 9 publicado para una operación (SDD-16 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_id: str
    stage: Literal[1, 2, 3]
    days_past_due: int | None
    pd_life_current: float | None
    pd_life_origination: float | None
    sicr_triggers: tuple[str, ...] = ()
    low_credit_risk_exempt: bool = False
    warnings: tuple[str, ...] = ()

    @field_validator("pd_life_current", "pd_life_origination", mode="before")
    @classmethod
    def _normaliza_pd_life(cls, value: Any) -> float | None:
        """Exige PD lifetime finita cuando se publica y normaliza ``-0.0``."""
        return _normalize_optional_required_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida rangos de mora y de PD lifetime en ``[0, 1]`` (SDD-16 §6)."""
        if self.days_past_due is not None and self.days_past_due < 0:
            raise ValueError("days_past_due debe ser mayor o igual a 0.")
        if self.pd_life_current is not None:
            _check_unit_interval(self.pd_life_current, field_name="pd_life_current")
        if self.pd_life_origination is not None:
            _check_unit_interval(self.pd_life_origination, field_name="pd_life_origination")
        return self


class IfrsEclRecord(BaseModel):
    """Registro de ECL por operación con horizonte por stage (SDD-16 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"scenario_weights"})

    row_id: str
    stage: Literal[1, 2, 3]
    ead: float
    lgd: float
    eir: float
    ecl_12m: float
    ecl_lifetime: float
    ecl_reported: float
    scenario_weights: dict[str, float]
    pd_basis: Literal["pit", "ttc", "mixed"]
    warnings: tuple[str, ...] = ()

    @field_validator(
        "ead",
        "lgd",
        "eir",
        "ecl_12m",
        "ecl_lifetime",
        "ecl_reported",
        mode="before",
    )
    @classmethod
    def _normaliza_float_requerido(cls, value: Any) -> float:
        """Exige floats finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @field_validator("scenario_weights", mode="before")
    @classmethod
    def _normaliza_pesos(cls, value: Any) -> Any:
        """Copia los pesos y exige distribución positiva que sume 1 (SDD-16 §6)."""
        return _normalize_scenario_weights(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida rangos económicos y la consistencia stage/horizonte (SDD-16 §6)."""
        if self.ead < 0.0:
            raise ValueError("ead debe ser mayor o igual a 0.")
        _check_unit_interval(self.lgd, field_name="lgd")
        for field_name in ("ecl_12m", "ecl_lifetime", "ecl_reported"):
            if getattr(self, field_name) < 0.0:
                raise ValueError(f"{field_name} debe ser mayor o igual a 0.")
        expected = self.ecl_12m if self.stage == 1 else self.ecl_lifetime
        if not math.isclose(self.ecl_reported, expected, rel_tol=_FLOAT_RTOL, abs_tol=_FLOAT_ATOL):
            raise ValueError(
                "ecl_reported debe ser ecl_12m en Stage 1 y ecl_lifetime en Stage 2/3."
            )
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de los pesos aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class IfrsEclTermRecord(BaseModel):
    """Fila tidy de ECL marginal por ``row_id``, ``scenario`` y ``period`` (SDD-16 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_id: str
    scenario: str
    period: int = Field(ge=1)
    time_value: float
    pd_marginal: float
    lgd: float
    ead: float
    discount_factor: float
    ecl_marginal: float
    warnings: tuple[str, ...] = ()

    @field_validator(
        "time_value",
        "pd_marginal",
        "lgd",
        "ead",
        "discount_factor",
        "ecl_marginal",
        mode="before",
    )
    @classmethod
    def _normaliza_float_requerido(cls, value: Any) -> float:
        """Exige floats finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida rangos de PD/LGD/EAD, ``ECL >= 0`` y ``DF ∈ (0, 1]`` (SDD-16 §6)."""
        if self.time_value < 0.0:
            raise ValueError("time_value debe ser mayor o igual a 0.")
        _check_unit_interval(self.pd_marginal, field_name="pd_marginal")
        _check_unit_interval(self.lgd, field_name="lgd")
        if self.ead < 0.0:
            raise ValueError("ead debe ser mayor o igual a 0.")
        if not 0.0 < self.discount_factor <= 1.0:
            raise ValueError("discount_factor debe estar en (0, 1].")
        if self.ecl_marginal < 0.0:
            raise ValueError("ecl_marginal debe ser mayor o igual a 0.")
        return self


class IfrsProvisionCard(BaseModel):
    """Resumen determinista CT-2 de provisiones IFRS 9 para governance y report (SDD-16 §4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"scenario_weights", "dependency_versions", "metric_sections"}
    )

    as_of_date: str
    term_structure_source: str
    pit_mode: str
    n_rows: int = Field(ge=0)
    n_stage1: int = Field(ge=0)
    n_stage2: int = Field(ge=0)
    n_stage3: int = Field(ge=0)
    total_ead: float
    total_ecl_reported: float
    scenarios: tuple[str, ...]
    scenario_weights: dict[str, float]
    dependency_versions: dict[str, str]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("as_of_date", "term_structure_source", "pit_mode")
    @classmethod
    def _valida_texto_no_vacio(cls, value: str) -> str:
        """Valida que los descriptores de la card no estén vacíos."""
        if not value.strip():
            raise ValueError("as_of_date, term_structure_source y pit_mode no pueden estar vacíos.")
        return value

    @field_validator("total_ead", "total_ecl_reported", mode="before")
    @classmethod
    def _normaliza_float_requerido(cls, value: Any) -> float:
        """Exige totales finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @field_validator("scenario_weights", mode="before")
    @classmethod
    def _normaliza_pesos(cls, value: Any) -> Any:
        """Copia los pesos y exige distribución positiva que sume 1 (SDD-16 §6)."""
        return _normalize_scenario_weights(value)

    @field_validator("dependency_versions", mode="before")
    @classmethod
    def _copia_dependency_versions(cls, value: Any) -> Any:
        """Copia versiones de dependencias preservando orden de inserción."""
        if isinstance(value, Mapping):
            return {str(key): str(item) for key, item in value.items()}
        return value

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia el payload CT-2 sin ordenar sus llaves."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(value)
        return value

    @model_validator(mode="after")
    def _check_card(self) -> Self:
        """Valida totales no negativos, conteos por stage y coherencia de escenarios."""
        if self.total_ead < 0.0:
            raise ValueError("total_ead debe ser mayor o igual a 0.")
        if self.total_ecl_reported < 0.0:
            raise ValueError("total_ecl_reported debe ser mayor o igual a 0.")
        if self.n_stage1 + self.n_stage2 + self.n_stage3 != self.n_rows:
            raise ValueError("n_stage1 + n_stage2 + n_stage3 debe ser igual a n_rows.")
        if set(self.scenarios) != set(self.scenario_weights):
            raise ValueError("scenarios debe coincidir con las llaves de scenario_weights.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de dicts mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class IfrsProvisionResult(BaseModel):
    """Contenedor agregado de artefactos publicados por ``provisioning.ifrs9`` (SDD-16 §4)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"staging", "detail", "ecl_term_structure", "summary"}
    )

    staging: DataFrameLike
    detail: DataFrameLike
    ecl_term_structure: DataFrameLike
    summary: DataFrameLike
    stage_records: tuple[IfrsStageRecord, ...]
    ecl_records: tuple[IfrsEclRecord, ...]
    card: IfrsProvisionCard

    @field_validator("staging", mode="before")
    @classmethod
    def _copia_staging(cls, value: Any) -> Any:
        """Copia y valida la tabla ``staging`` con sus columnas canónicas SDD-16 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_STAGING_COLUMNS,
            field_name="staging",
        )

    @field_validator("detail", mode="before")
    @classmethod
    def _copia_detail(cls, value: Any) -> Any:
        """Copia y valida la tabla ``detail`` con sus columnas canónicas SDD-16 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_DETAIL_COLUMNS,
            field_name="detail",
        )

    @field_validator("ecl_term_structure", mode="before")
    @classmethod
    def _copia_ecl_term_structure(cls, value: Any) -> Any:
        """Copia y valida la tabla ``ecl_term_structure`` con columnas canónicas SDD-16 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_ECL_TERM_STRUCTURE_COLUMNS,
            field_name="ecl_term_structure",
        )

    @field_validator("summary", mode="before")
    @classmethod
    def _copia_summary(cls, value: Any) -> Any:
        """Copia y valida la tabla ``summary`` con sus columnas canónicas SDD-16 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_SUMMARY_COLUMNS,
            field_name="summary",
        )

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value

    def term_structure(self) -> pandas.DataFrame | None:
        """Retorna la term-structure de ECL en forma larga CT-2; nunca es ``None`` en IFRS 9.

        Apila ``ecl_term_structure`` (ancho por componente) en la forma larga
        ``[row_id, scenario, period, time_value, component, value]`` que consumen SDD-17 y los
        reportes. Los componentes se preservan en orden canónico dentro de cada
        ``(row_id, scenario, period)`` y ``-0.0`` se normaliza a ``0.0``.
        """
        frame = self.ecl_term_structure
        long_frame = frame.melt(
            id_vars=["row_id", "scenario", "period", "time_value"],
            value_vars=list(_ECL_TERM_COMPONENTS),
            var_name="component",
            value_name="value",
        )
        long_frame = long_frame.sort_values(
            ["row_id", "scenario", "period"],
            kind="mergesort",
        ).reset_index(drop=True)
        long_frame = long_frame[list(_TERM_STRUCTURE_OUTPUT_COLUMNS)]
        long_frame["value"] = long_frame["value"].mask(long_frame["value"] == 0.0, 0.0)
        return long_frame


def _copy_and_validate_dataframe(
    value: Any,
    *,
    expected_columns: tuple[str, ...],
    field_name: str,
) -> Any:
    if not _is_dataframe_like(value):
        raise ValueError(f"{field_name} debe ser un pandas.DataFrame.")

    copied = _copy_dataframe(value)
    observed_columns = tuple(str(column) for column in copied.columns)
    if observed_columns != expected_columns:
        raise ValueError(
            f"{field_name} debe tener exactamente las columnas canónicas de SDD-16 §6."
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
    return copied


def _normalize_scenario_weights(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    if not value:
        raise ValueError("scenario_weights no puede estar vacío.")
    normalized: dict[str, float] = {}
    for key, weight in value.items():
        name = str(key)
        if not name.strip():
            raise ValueError("scenario_weights exige nombres de escenario no vacíos.")
        normalized_weight = _normalize_required_float(weight)
        if normalized_weight <= 0.0:
            raise ValueError("scenario_weights exige pesos estrictamente positivos.")
        normalized[name] = normalized_weight
    total = math.fsum(normalized.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=_WEIGHT_SUM_TOL):
        raise ValueError(f"scenario_weights debe sumar 1; suma observada={total!r}.")
    return normalized


def _check_unit_interval(value: float, *, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} debe estar en [0, 1].")


def _normalize_required_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Los valores float deben ser números finitos.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("Los valores float deben ser números finitos.")
    return _normalize_float(candidate)


def _normalize_optional_required_float(value: Any) -> float | None:
    if value is None:
        return None
    return _normalize_required_float(value)


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value


def _normalize_metric_payload(value: Any) -> Any:
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
