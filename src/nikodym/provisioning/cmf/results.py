"""DTOs puros de resultados de provisiones regulatorias CMF (SDD-15 §4/§6).

Este módulo fija los contenedores Pydantic publicados por ``provisioning.cmf``: registros por
operación, resumen por cartera, tarjeta de gobierno y resultado agregado con ``detail``/
``summary``. No calcula provisiones, no carga matrices y no importa ``pandas`` en runtime; los
DataFrames son solo contrato de I/O validado por estructura para preservar el import liviano.

``metric_sections`` conserva la puerta CT-2 como payload aditivo para gobierno y reportes. Las
colecciones mutables y DataFrames se copian defensivamente al validar y al acceder desde los DTOs.

**Experimental (SemVer 0.x).**
"""

import copy
from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nikodym.provisioning.cmf.matrices import CmfMatrixBundle

if TYPE_CHECKING:
    import pandas

    DataFrameLike: TypeAlias = pandas.DataFrame
else:
    DataFrameLike: TypeAlias = Any

_DETAIL_COLUMNS: tuple[str, ...] = (
    "portfolio",
    "method",
    "cmf_category",
    "matrix_id",
    "matrix_row_id",
    "direct_exposure_amount",
    "contingent_exposure_amount",
    "exposure_amount",
    "pd_source_value",
    "pi_percent",
    "pdi_percent",
    "pe_percent",
    "provision_amount",
    "guarantee_treatment",
    "ccf_percent",
    "warning_codes",
    "source_reference",
    "matrix_version",
)
_SUMMARY_COLUMNS: tuple[str, ...] = (
    "portfolio",
    "method",
    "cmf_category",
    "n_rows",
    "total_exposure_amount",
    "total_provision_amount",
    "weighted_pe_percent",
    "matrix_version",
    "warning_codes",
)

__all__ = [
    "CmfPortfolioSummary",
    "CmfProvisionCard",
    "CmfProvisionRecord",
    "CmfProvisionResult",
]


class CmfProvisionRecord(BaseModel):
    """Registro de provisión CMF publicado para una operación o exposición calculada."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_id: str
    portfolio: str
    method: str
    exposure_amount: Decimal
    direct_exposure_amount: Decimal
    contingent_exposure_amount: Decimal
    pi_percent: Decimal | None
    pdi_percent: Decimal | None
    pe_percent: Decimal
    provision_amount: Decimal
    matrix_id: str
    matrix_row_id: str
    cmf_category: str | None = None
    pd_source_value: Decimal | None = None
    guarantee_treatment: str | None = None
    warnings: tuple[str, ...] = ()

    @field_validator(
        "exposure_amount",
        "direct_exposure_amount",
        "contingent_exposure_amount",
        "pe_percent",
        "provision_amount",
    )
    @classmethod
    def _normaliza_decimal_requerido(cls, value: Decimal) -> Decimal:
        return _normalize_non_negative_decimal(value)

    @field_validator("pi_percent", "pdi_percent", "pd_source_value")
    @classmethod
    def _normaliza_decimal_opcional(cls, value: Decimal | None) -> Decimal | None:
        return None if value is None else _normalize_non_negative_decimal(value)


class CmfPortfolioSummary(BaseModel):
    """Resumen agregado de provisión CMF para una cartera regulatoria."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    portfolio: str
    n_rows: int = Field(ge=0)
    total_exposure_amount: Decimal
    total_provision_amount: Decimal
    weighted_pe_percent: Decimal
    warnings: tuple[str, ...] = ()

    @field_validator(
        "total_exposure_amount",
        "total_provision_amount",
        "weighted_pe_percent",
    )
    @classmethod
    def _normaliza_decimal_requerido(cls, value: Decimal) -> Decimal:
        return _normalize_non_negative_decimal(value)


class CmfProvisionCard(BaseModel):
    """Resumen determinista de provisiones CMF para governance y report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"metric_sections"})

    matrix_version: str
    as_of_date: str
    n_rows: int = Field(ge=0)
    total_exposure_amount: Decimal
    total_provision_amount: Decimal
    portfolios: tuple[CmfPortfolioSummary, ...]
    regulatory_sources: tuple[str, ...]
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("total_exposure_amount", "total_provision_amount")
    @classmethod
    def _normaliza_decimal_requerido(cls, value: Decimal) -> Decimal:
        return _normalize_non_negative_decimal(value)

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(value)
        return value

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de payloads mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class CmfProvisionResult(BaseModel):
    """Contenedor agregado de artefactos publicados por ``provisioning.cmf``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset({"detail", "summary"})

    detail: DataFrameLike
    summary: DataFrameLike
    records: tuple[CmfProvisionRecord, ...]
    card: CmfProvisionCard
    matrix_bundle: CmfMatrixBundle

    @field_validator("detail", mode="before")
    @classmethod
    def _copia_detail(cls, value: Any) -> Any:
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_DETAIL_COLUMNS,
            field_name="detail",
        )

    @field_validator("summary", mode="before")
    @classmethod
    def _copia_summary(cls, value: Any) -> Any:
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

    def term_structure(self) -> "pandas.DataFrame | None":
        """Retorna ``None`` en CMF B-1 agregado, cumpliendo CT-2/D-CORE-7.

        El modelo estándar CMF B-1 publica provisión agregada y por operación, no una curva
        lifetime ni una estructura multi-período. SDD-16/17 deben usar ``summary``/``card`` para
        el piso prudencial CMF y consumir este método solo cuando una extensión futura retorne un
        DataFrame.
        """
        return None


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
            f"{field_name} debe tener exactamente las columnas canónicas de SDD-15 §6."
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
        raise ValueError("Los montos y porcentajes CMF deben ser Decimal finitos.")
    if value < 0:
        raise ValueError("Los montos y porcentajes CMF no pueden ser negativos.")
    if value.is_zero():
        return Decimal("0")
    return value


def _normalize_metric_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_metric_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_metric_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_metric_payload(item) for item in value)
    return copy.deepcopy(value)
