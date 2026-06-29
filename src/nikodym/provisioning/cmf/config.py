"""Config declarativo de la capa ``provisioning.cmf`` (SDD-15 §5).

:class:`CmfProvisioningConfig` es la sección ``provisioning_cmf`` de
:class:`~nikodym.core.config.NikodymConfig`: cálculo determinista de provisiones regulatorias CMF
B-1/B-3 con matrices versionadas y defaults conservadores. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.provisioning.cmf.exceptions import CmfConfigError

CmfPdSourceDomain = Literal["model", "calibration"]
CmfPdMappingMethod = Literal["provided_cmf_category", "pd_breaks"]
CmfRoundingPolicy = Literal["none", "currency_2dp", "integer_currency"]
CmfFinancialGuaranteePolicy = Literal["fail", "ignore_if_missing", "use_recoverable_amount"]
ProbabilityBreak = Annotated[float, Field(ge=0.0, le=1.0)]

__all__ = [
    "CmfExposureConfig",
    "CmfFinancialGuaranteePolicy",
    "CmfGuaranteeConfig",
    "CmfMatrixConfig",
    "CmfPdMappingConfig",
    "CmfPdMappingMethod",
    "CmfPdSourceDomain",
    "CmfProvisioningConfig",
    "CmfRoundingPolicy",
]

_ROOT_COLUMN_FIELDS: tuple[str, ...] = (
    "as_of_date_col",
    "portfolio_col",
    "debtor_id_col",
    "category_col",
    "days_past_due_col",
    "product_type_col",
)
_EXPOSURE_COLUMN_FIELDS: tuple[str, ...] = (
    "direct_exposure_col",
    "contingent_amount_col",
    "contingent_type_col",
    "is_default_col",
)


class CmfMatrixConfig(NikodymBaseConfig):
    """Configuración de matrices regulatorias CMF versionadas."""

    active_version: str = Field(
        default="cmf_b1_b3_2025_01",
        title="Versión normativa activa",
        description=(
            "Identificador del bundle B-1/B-3 empaquetado que se usará para el cálculo CMF."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Matrices", "ui_order": 1},
    )
    require_verified_rows: bool = Field(
        default=True,
        title="Exigir filas verificadas",
        description="Si es True, rechaza filas de matriz con estado pending o no verificado.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Matrices", "ui_order": 2},
    )
    fail_on_unmapped_contingent_type: bool = Field(
        default=True,
        title="Fallar ante tipo contingente no mapeado",
        description="Si es True, un tipo contingente sin fila B-3 verificada falla en runtime.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Matrices", "ui_order": 3},
    )
    fail_on_source_mismatch: bool = Field(
        default=True,
        title="Fallar ante hash/fuente inconsistente",
        description="Si es True, inconsistencias de hash, manifest o fuente normativa fallan.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Matrices", "ui_order": 4},
    )


class CmfPdMappingConfig(NikodymBaseConfig):
    """Configuración del mapeo opcional desde PD de modelo a categoría CMF."""

    pd_source_domain: CmfPdSourceDomain = Field(
        default="model",
        title="Dominio fuente PD",
        description="Dominio fuente PD; solo se lee con method='pd_breaks'.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "PD a PI", "ui_order": 1},
    )
    pd_source_key: str = Field(
        default="raw_pd_frame",
        title="Artefacto fuente PD",
        description="Artefacto fuente PD; solo se lee con method='pd_breaks'.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "PD a PI", "ui_order": 2},
    )
    pd_column: str = Field(
        default="pd_raw",
        title="Columna PD",
        description="Columna PD; solo se lee con method='pd_breaks'.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "PD a PI", "ui_order": 3},
    )
    method: CmfPdMappingMethod = Field(
        default="provided_cmf_category",
        title="Método PD a categoría/PI",
        description="Método para usar categoría CMF provista o cortes PD explícitos.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "PD a PI", "ui_order": 4},
    )
    pd_breaks: tuple[ProbabilityBreak, ...] = Field(
        default_factory=tuple,
        title="Cortes PD para categorías",
        description="Cortes PD en [0, 1], estrictamente crecientes, para asignar categorías CMF.",
        json_schema_extra={"ui_widget": "number_list", "ui_group": "PD a PI", "ui_order": 5},
    )
    categories: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Categorías CMF resultantes",
        description="Categorías CMF resultantes; con pd_breaks deben ser len(pd_breaks)+1.",
        json_schema_extra={"ui_widget": "text_list", "ui_group": "PD a PI", "ui_order": 6},
    )

    @field_validator("pd_breaks", mode="after")
    @classmethod
    def _normaliza_pd_breaks(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        """Normaliza ``-0.0`` a ``0.0`` y rechaza cortes no finitos."""
        normalized: list[float] = []
        for item in value:
            if not math.isfinite(item):
                raise CmfConfigError("pd_breaks debe contener números finitos en [0, 1].")
            normalized.append(0.0 if item == 0.0 else float(item))
        return tuple(normalized)

    @model_validator(mode="after")
    def _check_pd_mapping(self) -> Self:
        """Valida monotonicidad y cardinalidad de cortes/categorías de SDD-15 §5."""
        _require_non_empty_strings(
            {
                "pd_source_key": self.pd_source_key,
                "pd_column": self.pd_column,
            },
            context="pd_mapping",
        )
        categorias_vacias = [
            idx for idx, category in enumerate(self.categories) if not category.strip()
        ]
        if categorias_vacias:
            raise CmfConfigError(
                f"Las categorías CMF de pd_mapping no pueden estar vacías: {categorias_vacias}."
            )
        if any(
            next_break <= current
            for current, next_break in zip(self.pd_breaks, self.pd_breaks[1:], strict=False)
        ):
            raise CmfConfigError("pd_breaks debe ser estrictamente creciente.")
        if self.method == "pd_breaks" and len(self.categories) != len(self.pd_breaks) + 1:
            raise CmfConfigError(
                "pd_mapping.method='pd_breaks' exige len(categories) == len(pd_breaks) + 1."
            )
        return self


class CmfExposureConfig(NikodymBaseConfig):
    """Configuración de columnas y políticas de exposición CMF."""

    direct_exposure_col: str = Field(
        default="exposure_amount",
        title="Exposición directa",
        description="Columna con el saldo o exposición directa antes de contingentes.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Exposición", "ui_order": 1},
    )
    contingent_amount_col: str = Field(
        default="contingent_amount",
        title="Monto contingente",
        description="Columna con el monto contingente sujeto a factor B-3.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Exposición", "ui_order": 2},
    )
    contingent_type_col: str = Field(
        default="contingent_type",
        title="Tipo contingente B-3",
        description="Columna con el tipo de crédito contingente para mapear a B-3.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Exposición", "ui_order": 3},
    )
    is_default_col: str = Field(
        default="is_default",
        title="Indicador incumplimiento",
        description="Columna booleana que activa el override B-3 de 100% en incumplimiento.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Exposición", "ui_order": 4},
    )
    allow_negative_exposure: bool = Field(
        default=False,
        title="Permitir exposición negativa",
        description=(
            "Si es False, el runtime rechaza exposiciones directas o contingentes negativas."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Exposición", "ui_order": 5},
    )
    rounding: CmfRoundingPolicy = Field(
        default="none",
        title="Redondeo de provisión",
        description="Política explícita de redondeo contable de la provisión calculada.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Exposición", "ui_order": 6},
    )

    @model_validator(mode="after")
    def _check_columnas_exposure(self) -> Self:
        """Valida que las columnas de exposición no estén vacías."""
        _require_non_empty_strings(
            _column_values(self, _EXPOSURE_COLUMN_FIELDS), context="exposure"
        )
        return self


class CmfGuaranteeConfig(NikodymBaseConfig):
    """Configuración de garantías y brechas regulatorias CMF."""

    enable_aval_substitution: bool = Field(
        default=True,
        title="Aplicar sustitución por aval",
        description="Activa la sustitución proporcional por avales/fianzas cuando aplique.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Garantías", "ui_order": 1},
    )
    financial_guarantee_policy: CmfFinancialGuaranteePolicy = Field(
        default="fail",
        title="Política ante aforos financieros faltantes",
        description=(
            "Tratamiento de garantías financieras con aforos/haircuts no verificados "
            "en la normativa recopilada."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Garantías", "ui_order": 2},
    )
    recoverable_amount_col: str | None = Field(
        default=None,
        title="Columna monto recuperable",
        description=(
            "Columna con recoverable_amount validado por el usuario; obligatoria si "
            "financial_guarantee_policy='use_recoverable_amount'."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Garantías", "ui_order": 3},
    )
    require_recoverable_for_default: bool = Field(
        default=True,
        title="Exigir R para C1-C6",
        description="Si es True, el runtime exige recupero para encasillar incumplimientos C1-C6.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Garantías", "ui_order": 4},
    )

    @model_validator(mode="after")
    def _check_recoverable_amount(self) -> Self:
        """Valida la política ``use_recoverable_amount`` de SDD-15 §5."""
        if self.recoverable_amount_col is not None and not self.recoverable_amount_col.strip():
            raise CmfConfigError("recoverable_amount_col no puede estar vacío si se informa.")
        if (
            self.financial_guarantee_policy == "use_recoverable_amount"
            and self.recoverable_amount_col is None
        ):
            raise CmfConfigError(
                "financial_guarantee_policy='use_recoverable_amount' exige recoverable_amount_col."
            )
        return self


class CmfProvisioningConfig(NikodymBaseConfig):
    """Sección ``provisioning_cmf`` de :class:`~nikodym.core.config.NikodymConfig`."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema provisioning_cmf",
        description="Versión local del schema de provisiones CMF para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección provisioning_cmf",
        description="== @register('standard', domain='provisioning_cmf') (SDD-15 §4).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    as_of_date_col: str = Field(
        default="as_of_date",
        title="Fecha de cálculo",
        description="Columna con la fecha de cálculo o cierre contable de la provisión.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    portfolio_col: str = Field(
        default="cmf_portfolio",
        title="Cartera CMF",
        description="Columna con la cartera regulatoria CMF aplicable a cada exposición.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    debtor_id_col: str = Field(
        default="debtor_id",
        title="Identificador de deudor",
        description="Columna de identificador de deudor para consolidaciones regulatorias.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )
    category_col: str = Field(
        default="cmf_category",
        title="Categoría CMF",
        description="Columna con categoría/tramo CMF provisto para el modo standalone.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 4},
    )
    days_past_due_col: str = Field(
        default="days_past_due",
        title="Días de mora",
        description=(
            "Columna con días de mora usados por matrices de cartera grupal, consumo y vivienda."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 5},
    )
    product_type_col: str = Field(
        default="cmf_product_type",
        title="Tipo producto CMF",
        description="Columna con tipo de producto regulatorio para resolver matrices CMF.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 6},
    )
    matrices: CmfMatrixConfig = Field(
        default_factory=CmfMatrixConfig,
        title="Matrices",
        description="Configuración del bundle normativo B-1/B-3 activo.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Matrices", "ui_order": 1},
    )
    pd_mapping: CmfPdMappingConfig = Field(
        default_factory=CmfPdMappingConfig,
        title="PD a PI",
        description="Configuración de categoría CMF provista o cortes PD explícitos.",
        json_schema_extra={"ui_widget": "section", "ui_group": "PD a PI", "ui_order": 1},
    )
    exposure: CmfExposureConfig = Field(
        default_factory=CmfExposureConfig,
        title="Exposición",
        description="Configuración de columnas de exposición y política de redondeo.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Exposición", "ui_order": 1},
    )
    guarantees: CmfGuaranteeConfig = Field(
        default_factory=CmfGuaranteeConfig,
        title="Garantías",
        description="Configuración de avales, garantías financieras y recuperos.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Garantías", "ui_order": 1},
    )

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida columnas y modo standalone de SDD-15 §5."""
        if self.pd_mapping.method == "provided_cmf_category" and not self.category_col.strip():
            raise CmfConfigError(
                "pd_mapping.method='provided_cmf_category' exige category_col no vacío."
            )
        _require_non_empty_strings(
            _column_values(self, _ROOT_COLUMN_FIELDS),
            context="provisioning_cmf",
        )
        return self


def _column_values(cfg: object, fields: tuple[str, ...]) -> dict[str, str]:
    """Devuelve nombres de columnas configurados para validar strings no vacíos."""
    return {field: getattr(cfg, field) for field in fields}


def _require_non_empty_strings(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de campos/columnas declarativos no sean vacíos."""
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise CmfConfigError(f"Los campos de {context} no pueden estar vacíos: {empty}.")
