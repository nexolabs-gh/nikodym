"""DTOs puros de resultados de la orquestación de provisiones (SDD-17 §4/§6).

Este módulo fija los contenedores Pydantic publicados por :mod:`nikodym.provisioning` (la capa fina
que compara **dos fuentes configurables** de provisión): registro de comparación por celda, resumen
por nivel, tarjeta CT-2 de gobierno y resultado agregado con ``comparison``/``summary``. **No**
aplica la regla (eso es del ``ProvisioningOrchestrator``), no recalcula PI/PDI/PE, ECL ni el método
interno, y no importa ``pandas`` en runtime al cargar el módulo; los DataFrames son solo contrato de
I/O validado por estructura para preservar el import liviano del núcleo.

**Las fuentes son datos, no nombres cableados.** Cada registro declara ``source_a``/``source_b`` (el
nombre legible de la fuente: ``cmf``, ``internal``, ``ifrs9``) y guarda sus montos en
``provision_a``/``provision_b``. ``binding`` y ``coverage`` usan **el nombre real de la fuente**
(``'cmf'``, ``'internal'``, ``'ifrs9'``, ``'tie'``, ``'<fuente>_only'``), de modo que la card diga
QUÉ fuente ganó sin que el lector tenga que traducir un rol.

Reconciliación de dominios (SDD-17 §3/§6, D-PROV-4): cada registro **preserva** el dominio numérico
original de su fuente —CMF y el método interno publican ``Decimal``; IFRS 9 publica ``float``— sin
forzarlos a un tipo común que destruya el original; la provisión reportada vive en ``Decimal``
(dominio regulatorio de reporte). Toda salida numérica normaliza ``-0.0`` como ``0.0`` y **jamás**
publica ``NaN`` ni ``inf`` (falla explícito).

:meth:`ProvisionOrchestrationResult.term_structure` cumple CT-2 delegando en la curva ECL de IFRS 9
(``IfrsProvisionResult.term_structure()``): el orchestrator la precomputa y la guarda en
``ifrs9_term_structure``; este resultado la expone (copia defensiva) cuando IFRS 9 es una de las
fuentes y retorna ``None`` en otro caso (ni el CMF ni el método interno publican term-structure:
son puntuales, D-CORE-7). **Nunca** fabrica una term-structure de la provisión reportada (que es
escalar por celda). Las colecciones mutables y DataFrames se copian defensivamente al validar y al
acceder desde los DTOs.

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

from nikodym.provisioning.config import SOURCE_NAMES, ProvisioningComparisonLevel

if TYPE_CHECKING:
    import pandas

    DataFrameLike: TypeAlias = pandas.DataFrame
else:
    DataFrameLike: TypeAlias = Any

# La fuente vinculante y la cobertura de cada celda, por NOMBRE REAL de fuente (SDD-17 §4).
ProvisionBinding: TypeAlias = Literal[
    "cmf", "internal", "ifrs9", "tie", "cmf_only", "internal_only", "ifrs9_only"
]
ProvisionCoverage: TypeAlias = Literal["both", "cmf_only", "internal_only", "ifrs9_only"]
# Monto de una fuente: ``Decimal`` (CMF, método interno) o ``float`` (IFRS 9). Se preserva el
# dominio de origen; la unión NO coacciona (Pydantic resuelve por tipo exacto).
ProvisionAmount: TypeAlias = Decimal | float

_COMPARISON_COLUMNS: tuple[str, ...] = (
    "cell_id",
    "level",
    "source_a",
    "source_b",
    "provision_a",
    "provision_b",
    "reported_provision",
    "binding",
    "coverage",
    "warning_codes",
)
_SUMMARY_COLUMNS: tuple[str, ...] = (
    "level",
    "source_a",
    "source_b",
    "n_cells",
    "n_binding_a",
    "n_binding_b",
    "n_binding_tie",
    "total_provision_a",
    "total_provision_b",
    "total_reported_provision",
    "warning_codes",
)
# Fuentes admitidas en ``engines_present``/``source_a``/``source_b`` (SDD-17 §4, SDD-28).
_VALID_SOURCES: frozenset[str] = frozenset(SOURCE_NAMES.values())

__all__ = [
    "ProvisionComparisonRecord",
    "ProvisionComparisonSummary",
    "ProvisionOrchestrationCard",
    "ProvisionOrchestrationResult",
]


class ProvisionComparisonRecord(BaseModel):
    """Registro de comparación de dos fuentes de provisión en una celda (SDD-17 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cell_id: str
    level: ProvisioningComparisonLevel
    source_a: str
    source_b: str
    provision_a: ProvisionAmount | None
    provision_b: ProvisionAmount | None
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

    @field_validator("source_a", "source_b")
    @classmethod
    def _valida_source(cls, value: str) -> str:
        """Valida que la fuente sea uno de los nombres canónicos (cmf/internal/ifrs9)."""
        if value not in _VALID_SOURCES:
            raise ValueError(f"source solo admite {sorted(_VALID_SOURCES)}: {value!r}.")
        return value

    @field_validator("provision_a", "provision_b", mode="before")
    @classmethod
    def _normaliza_monto(cls, value: Any) -> Any:
        """Exige montos finitos no negativos y normaliza el cero, sin cambiar de dominio."""
        return _normalize_optional_amount(value)

    @field_validator("reported_provision")
    @classmethod
    def _normaliza_reported(cls, value: Decimal) -> Decimal:
        """Exige la provisión reportada Decimal no negativa y normaliza el cero."""
        return _normalize_non_negative_decimal(value)

    @model_validator(mode="after")
    def _check_cobertura(self) -> Self:
        """Valida la coherencia entre fuentes, ``coverage``, ``binding`` y los montos (§6)."""
        if self.source_a == self.source_b:
            raise ValueError("source_a y source_b deben ser fuentes distintas.")
        if self.coverage == "both":
            if self.provision_a is None or self.provision_b is None:
                raise ValueError("coverage='both' exige provision_a y provision_b no nulos.")
            if self.binding not in (self.source_a, self.source_b, "tie"):
                raise ValueError(
                    f"coverage='both' exige binding en {{{self.source_a}, {self.source_b}, tie}}."
                )
            return self
        if self.coverage not in (f"{self.source_a}_only", f"{self.source_b}_only"):
            raise ValueError(
                f"coverage={self.coverage!r} no corresponde a las fuentes declaradas "
                f"({self.source_a}, {self.source_b})."
            )
        presente, ausente, monto_presente, monto_ausente = (
            (self.source_a, self.source_b, self.provision_a, self.provision_b)
            if self.coverage == f"{self.source_a}_only"
            else (self.source_b, self.source_a, self.provision_b, self.provision_a)
        )
        if monto_presente is None or monto_ausente is not None:
            raise ValueError(
                f"coverage='{presente}_only' exige solo el monto de {presente} presente "
                f"(el de {ausente} debe ser nulo)."
            )
        if self.binding != f"{presente}_only":
            raise ValueError(f"coverage='{presente}_only' exige binding='{presente}_only'.")
        return self


class ProvisionComparisonSummary(BaseModel):
    """Resumen agregado de la comparación de dos fuentes por nivel (SDD-17 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: ProvisioningComparisonLevel
    source_a: str
    source_b: str
    n_cells: int = Field(ge=0)
    n_binding_a: int = Field(ge=0)
    n_binding_b: int = Field(ge=0)
    n_binding_tie: int = Field(ge=0)
    total_provision_a: Decimal
    total_provision_b: Decimal
    total_reported_provision: Decimal
    warnings: tuple[str, ...] = ()

    @field_validator("source_a", "source_b")
    @classmethod
    def _valida_source(cls, value: str) -> str:
        """Valida que la fuente sea uno de los nombres canónicos (cmf/internal/ifrs9)."""
        if value not in _VALID_SOURCES:
            raise ValueError(f"source solo admite {sorted(_VALID_SOURCES)}: {value!r}.")
        return value

    @field_validator("total_provision_a", "total_provision_b", "total_reported_provision")
    @classmethod
    def _normaliza_totales(cls, value: Decimal) -> Decimal:
        """Exige totales Decimal no negativos y normaliza el cero."""
        return _normalize_non_negative_decimal(value)

    @model_validator(mode="after")
    def _check_conteos(self) -> Self:
        """Valida que las celdas vinculantes no excedan el total de celdas (§6)."""
        if self.n_binding_a + self.n_binding_b + self.n_binding_tie > self.n_cells:
            raise ValueError("n_binding_a + n_binding_b + n_binding_tie no puede exceder n_cells.")
        return self


class ProvisionOrchestrationCard(BaseModel):
    """Tarjeta CT-2 de gobierno de la comparación de dos fuentes (SDD-17 §4/§9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"metric_sections"})

    as_of_date: str
    comparison_level: str
    rule: str
    source_a: str
    source_b: str
    engines_present: tuple[str, ...]
    binding: str | None = None
    n_cells: int = Field(ge=0)
    n_binding_a: int = Field(ge=0)
    n_binding_b: int = Field(ge=0)
    n_binding_tie: int = Field(ge=0)
    total_provision_a: Decimal
    total_provision_b: Decimal
    total_reported_provision: Decimal
    cmf_matrix_version: str | None = None
    ifrs9_term_structure_source: str | None = None
    internal_method: str | None = None
    regulatory_sources: tuple[str, ...] = ()
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("as_of_date", "comparison_level", "rule")
    @classmethod
    def _valida_texto_no_vacio(cls, value: str) -> str:
        """Valida que ``as_of_date``, ``comparison_level`` y ``rule`` no estén vacíos."""
        if not value.strip():
            raise ValueError("as_of_date, comparison_level y rule no pueden estar vacíos.")
        return value

    @field_validator("source_a", "source_b")
    @classmethod
    def _valida_source(cls, value: str) -> str:
        """Valida que la fuente sea uno de los nombres canónicos (cmf/internal/ifrs9)."""
        if value not in _VALID_SOURCES:
            raise ValueError(f"source solo admite {sorted(_VALID_SOURCES)}: {value!r}.")
        return value

    @field_validator("engines_present")
    @classmethod
    def _valida_engines(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida que haya al menos una fuente y que sean 'cmf'/'internal'/'ifrs9' (SDD-17 §4)."""
        if not value:
            raise ValueError("engines_present no puede estar vacío.")
        invalidos = [engine for engine in value if engine not in _VALID_SOURCES]
        if invalidos:
            raise ValueError(f"engines_present solo admite {sorted(_VALID_SOURCES)}: {invalidos}.")
        return value

    @field_validator("total_provision_a", "total_provision_b", "total_reported_provision")
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
        if self.n_binding_a + self.n_binding_b + self.n_binding_tie > self.n_cells:
            raise ValueError("n_binding_a + n_binding_b + n_binding_tie no puede exceder n_cells.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias del payload CT-2 mutable aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class ProvisionOrchestrationResult(BaseModel):
    """Contenedor agregado del comparativo de dos fuentes de provisión (SDD-17 §4/§6)."""

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
        """Copia la curva ECL IFRS 9 delegada (o ``None``); no valida sus columnas."""
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
        """Retorna la curva ECL de IFRS 9 (CT-2) o ``None`` si IFRS 9 no es fuente (SDD-17 §4).

        Delega en la curva larga que ``IfrsProvisionResult.term_structure()`` publicó y que el
        orchestrator guardó en ``ifrs9_term_structure``; la expone como copia defensiva. **No**
        fabrica una term-structure de la provisión reportada (que es escalar por celda): si IFRS 9
        no participa retorna ``None`` — ni el CMF ni el método interno publican curva (D-CORE-7).
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


def _normalize_optional_amount(value: Any) -> Any:
    """Normaliza el monto de una fuente **preservando su dominio** (Decimal o float)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return _normalize_non_negative_decimal(value)
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
