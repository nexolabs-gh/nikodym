"""DTOs puros de resultados de la orquestación de provisiones (SDD-17 §4/§6).

Este módulo fija los contenedores Pydantic publicados por :mod:`nikodym.provisioning` (la capa fina
de orquestación, piso prudencial CMF vs IFRS 9): registro de comparación por celda, resumen por
nivel, tarjeta CT-2 de gobierno y resultado agregado con ``comparison``/``summary``. **No** calcula
el máximo (eso es del ``ProvisioningOrchestrator``, B17.3), no recalcula PI/PDI/PE ni ECL y no
importa ``pandas`` en runtime al cargar el módulo; los DataFrames son solo contrato de I/O validado
por estructura para preservar el import liviano del núcleo.

Reconciliación de dominios (SDD-17 §3/§6, D-PROV-4): cada registro **preserva** el monto CMF en
``Decimal`` y el ECL IFRS 9 en ``float`` sin forzarlos a un tipo común que destruya el original; la
provisión reportada vive en ``Decimal`` (dominio regulatorio de reporte). Toda salida numérica
normaliza ``-0.0`` como ``0.0`` y **jamás** publica ``NaN`` ni ``inf`` (falla explícito).

:meth:`ProvisionOrchestrationResult.term_structure` cumple CT-2 delegando en la curva ECL de IFRS 9
(``IfrsProvisionResult.term_structure()``): el orchestrator la precomputa y la guarda en
``ifrs9_term_structure``; este resultado la expone (copia defensiva) cuando IFRS 9 está presente y
retorna ``None`` cuando solo hay CMF (que no publica term-structure, D-CORE-7). **Nunca** fabrica
una term-structure del máximo (que es escalar por celda). Las colecciones mutables y DataFrames se
copian defensivamente al validar y al acceder desde los DTOs.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from decimal import Decimal
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.provisioning.config import ProvisioningComparisonLevel

if TYPE_CHECKING:
    import pandas

    DataFrameLike: TypeAlias = pandas.DataFrame
else:
    DataFrameLike: TypeAlias = Any

# El motor vinculante y la cobertura de cada celda de comparación (SDD-17 §4).
ProvisionBinding: TypeAlias = Literal["cmf", "ifrs9", "tie", "cmf_only", "ifrs9_only"]
ProvisionCoverage: TypeAlias = Literal["both", "cmf_only", "ifrs9_only"]

_COMPARISON_COLUMNS: tuple[str, ...] = (
    "cell_id",
    "level",
    "cmf_provision",
    "ifrs9_ecl",
    "reported_provision",
    "binding",
    "coverage",
    "warning_codes",
)
_SUMMARY_COLUMNS: tuple[str, ...] = (
    "level",
    "n_cells",
    "n_binding_cmf",
    "n_binding_ifrs9",
    "n_binding_tie",
    "total_cmf_provision",
    "total_ifrs9_ecl",
    "total_reported_provision",
    "warning_codes",
)
# Motores admitidos en ``engines_present`` (SDD-17 §4): el par CMF / IFRS 9.
_VALID_ENGINES: frozenset[str] = frozenset({"cmf", "ifrs9"})

__all__ = [
    "ProvisionComparisonRecord",
    "ProvisionComparisonSummary",
    "ProvisionOrchestrationCard",
    "ProvisionOrchestrationResult",
]


class ProvisionComparisonRecord(BaseModel):
    """Registro de comparación CMF vs IFRS 9 por celda del máximo (SDD-17 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cell_id: str
    level: ProvisioningComparisonLevel
    cmf_provision: Decimal | None
    ifrs9_ecl: float | None
    reported_provision: Decimal
    binding: ProvisionBinding
    coverage: ProvisionCoverage
    warnings: tuple[str, ...] = ()

    @field_validator("cell_id")
    @classmethod
    def _valida_cell_id(cls, value: str) -> str:
        """Valida que el identificador de celda no esté vacío."""
        if not value.strip():
            raise ValueError("cell_id no puede estar vacío.")
        return value

    @field_validator("ifrs9_ecl", mode="before")
    @classmethod
    def _normaliza_ifrs9_ecl(cls, value: Any) -> float | None:
        """Exige ECL IFRS 9 finito no negativo y normaliza ``-0.0`` (float original preservado)."""
        return _normalize_optional_non_negative_float(value)

    @field_validator("cmf_provision")
    @classmethod
    def _normaliza_cmf_provision(cls, value: Decimal | None) -> Decimal | None:
        """Exige provisión CMF Decimal no negativa y normaliza el cero (Decimal original)."""
        return None if value is None else _normalize_non_negative_decimal(value)

    @field_validator("reported_provision")
    @classmethod
    def _normaliza_reported(cls, value: Decimal) -> Decimal:
        """Exige la provisión reportada Decimal no negativa y normaliza el cero."""
        return _normalize_non_negative_decimal(value)

    @model_validator(mode="after")
    def _check_cobertura(self) -> Self:
        """Valida la coherencia entre ``coverage``, ``binding`` y los montos presentes (§6)."""
        if self.coverage == "both":
            if self.cmf_provision is None or self.ifrs9_ecl is None:
                raise ValueError("coverage='both' exige cmf_provision e ifrs9_ecl no nulos.")
            if self.binding not in ("cmf", "ifrs9", "tie"):
                raise ValueError("coverage='both' exige binding en {cmf, ifrs9, tie}.")
        elif self.coverage == "cmf_only":
            if self.cmf_provision is None or self.ifrs9_ecl is not None:
                raise ValueError("coverage='cmf_only' exige solo cmf_provision presente.")
            if self.binding != "cmf_only":
                raise ValueError("coverage='cmf_only' exige binding='cmf_only'.")
        else:
            if self.ifrs9_ecl is None or self.cmf_provision is not None:
                raise ValueError("coverage='ifrs9_only' exige solo ifrs9_ecl presente.")
            if self.binding != "ifrs9_only":
                raise ValueError("coverage='ifrs9_only' exige binding='ifrs9_only'.")
        return self


class ProvisionComparisonSummary(BaseModel):
    """Resumen agregado de la comparación CMF vs IFRS 9 por nivel (SDD-17 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: ProvisioningComparisonLevel
    n_cells: int = Field(ge=0)
    n_binding_cmf: int = Field(ge=0)
    n_binding_ifrs9: int = Field(ge=0)
    n_binding_tie: int = Field(ge=0)
    total_cmf_provision: Decimal
    total_ifrs9_ecl: Decimal
    total_reported_provision: Decimal
    warnings: tuple[str, ...] = ()

    @field_validator("total_cmf_provision", "total_ifrs9_ecl", "total_reported_provision")
    @classmethod
    def _normaliza_totales(cls, value: Decimal) -> Decimal:
        """Exige totales Decimal no negativos y normaliza el cero."""
        return _normalize_non_negative_decimal(value)

    @model_validator(mode="after")
    def _check_conteos(self) -> Self:
        """Valida que las celdas vinculantes no excedan el total de celdas (§6)."""
        if self.n_binding_cmf + self.n_binding_ifrs9 + self.n_binding_tie > self.n_cells:
            raise ValueError(
                "n_binding_cmf + n_binding_ifrs9 + n_binding_tie no puede exceder n_cells."
            )
        return self


class ProvisionOrchestrationCard(BaseModel):
    """Tarjeta CT-2 de gobierno del piso prudencial CMF vs IFRS 9 (SDD-17 §4/§9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"metric_sections"})

    as_of_date: str
    comparison_level: str
    engines_present: tuple[str, ...]
    n_cells: int = Field(ge=0)
    n_binding_cmf: int = Field(ge=0)
    n_binding_ifrs9: int = Field(ge=0)
    n_binding_tie: int = Field(ge=0)
    total_cmf_provision: Decimal
    total_ifrs9_ecl: Decimal
    total_reported_provision: Decimal
    cmf_matrix_version: str | None = None
    ifrs9_term_structure_source: str | None = None
    regulatory_sources: tuple[str, ...] = ()
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("as_of_date", "comparison_level")
    @classmethod
    def _valida_texto_no_vacio(cls, value: str) -> str:
        """Valida que ``as_of_date`` y ``comparison_level`` no estén vacíos."""
        if not value.strip():
            raise ValueError("as_of_date y comparison_level no pueden estar vacíos.")
        return value

    @field_validator("engines_present")
    @classmethod
    def _valida_engines(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida que haya al menos un motor y que sean 'cmf'/'ifrs9' (SDD-17 §4)."""
        if not value:
            raise ValueError("engines_present no puede estar vacío.")
        invalidos = [engine for engine in value if engine not in _VALID_ENGINES]
        if invalidos:
            raise ValueError(f"engines_present solo admite 'cmf'/'ifrs9': {invalidos}.")
        return value

    @field_validator("total_cmf_provision", "total_ifrs9_ecl", "total_reported_provision")
    @classmethod
    def _normaliza_totales(cls, value: Decimal) -> Decimal:
        """Exige totales Decimal no negativos y normaliza el cero."""
        return _normalize_non_negative_decimal(value)

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia el payload CT-2 sin ordenar sus llaves y normaliza sus floats."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(value)
        return value

    @model_validator(mode="after")
    def _check_conteos(self) -> Self:
        """Valida que las celdas vinculantes no excedan el total de celdas (§6)."""
        if self.n_binding_cmf + self.n_binding_ifrs9 + self.n_binding_tie > self.n_cells:
            raise ValueError(
                "n_binding_cmf + n_binding_ifrs9 + n_binding_tie no puede exceder n_cells."
            )
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias del payload CT-2 mutable aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class ProvisionOrchestrationResult(BaseModel):
    """Contenedor agregado del comparativo y piso prudencial CMF vs IFRS 9 (SDD-17 §4/§6)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"comparison", "summary", "ifrs9_term_structure"}
    )

    comparison: DataFrameLike
    summary: DataFrameLike
    records: tuple[ProvisionComparisonRecord, ...]
    card: ProvisionOrchestrationCard
    ifrs9_term_structure: DataFrameLike | None = None

    @field_validator("comparison", mode="before")
    @classmethod
    def _copia_comparison(cls, value: Any) -> Any:
        """Copia y valida ``comparison`` con sus columnas canónicas SDD-17 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_COMPARISON_COLUMNS,
            field_name="comparison",
        )

    @field_validator("summary", mode="before")
    @classmethod
    def _copia_summary(cls, value: Any) -> Any:
        """Copia y valida ``summary`` con sus columnas canónicas SDD-17 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_SUMMARY_COLUMNS,
            field_name="summary",
        )

    @field_validator("ifrs9_term_structure", mode="before")
    @classmethod
    def _copia_term_structure(cls, value: Any) -> Any:
        """Copia la curva ECL IFRS 9 delegada (o ``None`` si solo CMF); no valida sus columnas."""
        if value is None:
            return None
        if not _is_dataframe_like(value):
            raise ValueError("ifrs9_term_structure debe ser un pandas.DataFrame o None.")
        return _copy_dataframe(value)

    @model_validator(mode="after")
    def _check_paralelismo(self) -> Self:
        """Valida que haya exactamente un registro por fila de ``comparison`` (§6)."""
        if len(self.records) != len(self.comparison):
            raise ValueError("records debe tener exactamente una entrada por fila de comparison.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value

    def term_structure(self) -> pandas.DataFrame | None:
        """Retorna la curva ECL de IFRS 9 (CT-2) o ``None`` si solo hay CMF (SDD-17 §4).

        Delega en la curva larga que ``IfrsProvisionResult.term_structure()`` publicó y que el
        orchestrator guardó en ``ifrs9_term_structure``; la expone como copia defensiva. **No**
        fabrica una term-structure del máximo (que es escalar por celda): si IFRS 9 no está
        presente retorna ``None`` (D-CORE-7).
        """
        curve = self.ifrs9_term_structure
        if curve is None:
            return None
        return curve


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
            f"{field_name} debe tener exactamente las columnas canónicas de SDD-17 §6."
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


def _normalize_non_negative_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("Los montos Decimal deben ser finitos (ni NaN ni infinito).")
    if value < 0:
        raise ValueError("Los montos Decimal no pueden ser negativos.")
    if value.is_zero():
        return Decimal("0")
    return value


def _normalize_non_negative_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Los montos float deben ser números reales finitos.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("Los montos float no pueden ser NaN ni inf.")
    if candidate < 0.0:
        raise ValueError("Los montos float no pueden ser negativos.")
    return abs(candidate) or 0.0


def _normalize_optional_non_negative_float(value: Any) -> float | None:
    if value is None:
        return None
    return _normalize_non_negative_float(value)


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
