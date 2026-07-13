"""DTOs puros de resultados del método interno de provisiones (SDD-28 §4.1/§6).

Este módulo fija los contenedores Pydantic publicados por ``provisioning.internal``: el registro por
operación, la tarjeta de gobierno y el resultado agregado con ``detail``/``groups``/``summary``. No
calcula provisiones y no importa ``pandas`` en runtime; los DataFrames son sólo contrato de I/O
validado por estructura, para preservar el import liviano del paquete.

``groups`` es el frame que la norma describe y el que un validador pide primero: **una fila por
grupo homogéneo**, con su exposición, su PD, su LGD y la provisión resultante. Las colecciones
mutables y los DataFrames se copian defensivamente al validar y al acceder desde los DTOs.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

import copy
from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    import pandas

    DataFrameLike: TypeAlias = pandas.DataFrame
else:
    DataFrameLike: TypeAlias = Any

DETAIL_COLUMNS: tuple[str, ...] = (
    "row_id",
    "portfolio",
    "group_id",
    "exposure_amount",
    "pd",
    "lgd",
    "loss_rate",
    "provision_amount",
    "warning_codes",
)
GROUP_COLUMNS: tuple[str, ...] = (
    "group_id",
    "portfolio",
    "n_operations",
    "total_exposure",
    "pd_group",
    "lgd_group",
    "expected_loss_rate",
    "provision_amount",
    "warning_codes",
)
SUMMARY_COLUMNS: tuple[str, ...] = (
    "portfolio",
    "n_groups",
    "n_operations",
    "total_exposure",
    "total_provision",
    "weighted_expected_loss_rate",
    "warning_codes",
)

__all__ = [
    "DETAIL_COLUMNS",
    "GROUP_COLUMNS",
    "SUMMARY_COLUMNS",
    "InternalProvisionCard",
    "InternalProvisionRecord",
    "InternalProvisionResult",
]


class InternalProvisionRecord(BaseModel):
    """Provisión interna imputada a una operación del grupo homogéneo.

    ``provision_amount`` **no** es ``exposure_amount · pd · lgd`` de la operación: la norma calcula
    la provisión **por grupo** y este monto es el prorrateo de esa cifra por participación de
    exposición dentro del grupo (SDD-28 §4.1). ``lgd`` es ``None`` con
    ``method='direct_loss_rate'``, donde la pérdida no se descompone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_id: str
    portfolio: str
    group_id: str
    exposure_amount: Decimal
    pd: Decimal
    lgd: Decimal | None
    loss_rate: Decimal
    provision_amount: Decimal
    warnings: tuple[str, ...] = ()

    @field_validator("exposure_amount", "pd", "loss_rate", "provision_amount")
    @classmethod
    def _normaliza_decimal_requerido(cls, value: Decimal) -> Decimal:
        return _normalize_non_negative_decimal(value)

    @field_validator("lgd")
    @classmethod
    def _normaliza_decimal_opcional(cls, value: Decimal | None) -> Decimal | None:
        return None if value is None else _normalize_non_negative_decimal(value)


class InternalProvisionCard(BaseModel):
    """Resumen determinista del método interno para governance y report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"metric_sections"})

    as_of_date: str
    method: str
    grouping: str
    pd_source: str
    n_groups: int = Field(ge=0)
    n_rows: int = Field(ge=0)
    total_exposure: Decimal
    total_internal_provision: Decimal
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("total_exposure", "total_internal_provision")
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


class InternalProvisionResult(BaseModel):
    """Contenedor agregado de artefactos publicados por ``provisioning.internal``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset({"detail", "groups", "summary"})

    detail: DataFrameLike
    groups: DataFrameLike
    summary: DataFrameLike
    records: tuple[InternalProvisionRecord, ...]
    card: InternalProvisionCard

    @field_validator("detail", mode="before")
    @classmethod
    def _copia_detail(cls, value: Any) -> Any:
        return _copy_and_validate_dataframe(value, columns=DETAIL_COLUMNS, field_name="detail")

    @field_validator("groups", mode="before")
    @classmethod
    def _copia_groups(cls, value: Any) -> Any:
        return _copy_and_validate_dataframe(value, columns=GROUP_COLUMNS, field_name="groups")

    @field_validator("summary", mode="before")
    @classmethod
    def _copia_summary(cls, value: Any) -> Any:
        return _copy_and_validate_dataframe(value, columns=SUMMARY_COLUMNS, field_name="summary")

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value

    def term_structure(self) -> "pandas.DataFrame | None":
        """Retorna ``None``: el método interno del B-1 §3 es puntual, no lifetime (CT-2)."""
        return None


def _copy_and_validate_dataframe(value: Any, *, columns: tuple[str, ...], field_name: str) -> Any:
    """Copia y valida que el frame traiga exactamente las columnas canónicas de SDD-28 §4.1."""
    if not _is_dataframe_like(value):
        raise ValueError(f"{field_name} debe ser un pandas.DataFrame.")
    copied = _copy_dataframe(value)
    observed = tuple(str(column) for column in copied.columns)
    if observed != columns:
        raise ValueError(
            f"{field_name} debe tener exactamente las columnas canónicas de SDD-28 §4.1."
        )
    return copied


def _is_dataframe_like(value: object) -> bool:
    """Detecta un DataFrame por estructura, sin importar ``pandas`` en runtime."""
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))


def _copy_dataframe(frame: Any) -> Any:
    """Copia profunda defensiva del frame.

    A diferencia de ``provisioning.cmf``, aquí **no** hay que normalizar ``-0.0``: los montos y
    tasas del método interno viajan como ``Decimal`` (dtype ``object``), no como ``float``, de modo
    que el cero negativo binario no existe en estos frames.
    """
    return frame.copy(deep=True)


def _normalize_non_negative_decimal(value: Decimal) -> Decimal:
    """Exige montos y tasas no negativos y normaliza el cero.

    La finitud **no** se revalida aquí: la validación núcleo de ``Decimal`` de Pydantic ya rechaza
    ``NaN`` e ``Infinity`` (``finite_number``) antes de que este validador ``mode='after'`` corra.
    Repetir la guarda sería código que jamás se ejecuta.
    """
    if value < 0:
        raise ValueError("Los montos y tasas del método interno no pueden ser negativos.")
    if value.is_zero():
        return Decimal("0")
    return value


def _normalize_metric_payload(value: Any) -> Any:
    """Copia en profundidad el payload de métricas preservando tipos contenedores."""
    if isinstance(value, Mapping):
        return {str(key): _normalize_metric_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_metric_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_metric_payload(item) for item in value)
    return copy.deepcopy(value)
