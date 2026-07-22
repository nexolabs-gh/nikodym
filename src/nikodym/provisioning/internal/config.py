"""Config declarativo de la capa ``provisioning.internal`` (SDD-28 §5.1).

:class:`InternalProvisioningConfig` es la sección ``provisioning_internal`` de
:class:`~nikodym.core.config.NikodymConfig`: el **método interno** que el Capítulo B-1 de la CMF
obliga a todo banco a mantener junto al método estándar (B-1 §3, Circular N° 2.346). El motor
agrupa a los deudores en **grupos homogéneos** y aplica, por grupo,
``provisión = Exposición · PD · LGD`` (o directamente la tasa de pérdida esperada del grupo).

Toda clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y
``frozen=True``); cada campo declara ``title``/``description`` y metadatos ``ui_*`` para que la UI
(SDD-23) sea un editor del mismo config. La sección es **computacional**: entra al ``config_hash``
global cuando está activa.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.provisioning.internal.exceptions import InternalConfigError

InternalPdSourceDomain = Literal["calibration", "model"]
InternalGroupingMethod = Literal["score_band", "segment", "provided"]
InternalLgdMethod = Literal["provided", "group_historical"]
InternalProvisioningMethod = Literal["pd_lgd", "direct_loss_rate"]
InternalRoundingPolicy = Literal["none", "currency_2dp", "integer_currency"]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]

__all__ = [
    "InternalGroupingMethod",
    "InternalLgdConfig",
    "InternalLgdMethod",
    "InternalPdSourceDomain",
    "InternalProvisioningConfig",
    "InternalProvisioningMethod",
    "InternalRoundingPolicy",
]

_GROUP_COL_GROUPINGS: tuple[str, ...] = ("segment", "provided")
_ROOT_COLUMN_FIELDS: tuple[str, ...] = (
    "as_of_date_col",
    "portfolio_col",
    "exposure_col",
    "pd_column",
)


class InternalLgdConfig(NikodymBaseConfig):
    """Configuración de la LGD (``porcentaje de pérdida dado el incumplimiento``, B-1 §3)."""

    method: InternalLgdMethod = Field(
        default="provided",
        title="Método LGD",
        description=(
            "provided: la LGD del grupo es la media de la columna PONDERADA POR EXPOSICIÓN. "
            "group_historical: es la media SIMPLE (histórica) del grupo, aplicada a todo el grupo."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "LGD", "ui_order": 1},
    )
    lgd_col: str = Field(
        default="lgd",
        title="Columna LGD",
        description="Columna con la pérdida dado el incumplimiento observada por operación.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "LGD", "ui_order": 2},
    )
    lgd_floor: UnitInterval = Field(
        default=0.0,
        title="Piso de LGD",
        description="Piso explícito aplicado tras validar la LGD; nunca clipa un valor inválido.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LGD", "ui_order": 3},
    )
    lgd_cap: UnitInterval = Field(
        default=1.0,
        title="Techo de LGD",
        description="Techo explícito aplicado tras validar la LGD; nunca clipa un valor inválido.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LGD", "ui_order": 4},
    )

    @model_validator(mode="after")
    def _check_lgd(self) -> Self:
        """Valida columna no vacía y ``lgd_floor <= lgd_cap`` (SDD-28 §5.1)."""
        if not self.lgd_col.strip():
            raise InternalConfigError("lgd.lgd_col no puede estar vacío.")
        if self.lgd_floor > self.lgd_cap:
            raise InternalConfigError(
                f"lgd.lgd_floor ({self.lgd_floor}) no puede superar lgd.lgd_cap ({self.lgd_cap})."
            )
        return self


class InternalProvisioningConfig(NikodymBaseConfig):
    """Calcula las provisiones del método interno del banco (Cap. B-1 §3) por grupo homogéneo.

    Motor experimental: fuera de la garantía SemVer 1.x.
    """

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema provisioning_internal",
        description="Versión local del schema del método interno para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección provisioning_internal",
        description="Variante de la sección del método interno; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    as_of_date_col: str = Field(
        default="as_of_date",
        title="Fecha de cálculo",
        description="Columna con la fecha de cierre contable; debe traer un valor único.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    portfolio_col: str = Field(
        default="cmf_portfolio",
        title="Cartera CMF",
        description="Columna de cartera regulatoria; la misma que consume el método estándar.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    exposure_col: str = Field(
        default="exposure_amount",
        title="Exposición",
        description="Columna con el monto de colocaciones; la misma exposición que ve el estándar.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )
    pd_source: InternalPdSourceDomain = Field(
        default="calibration",
        title="Fuente de PD",
        description=(
            "Dominio del artefacto de PD: calibration (PD calibrada, la que exige el B-1) o model."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "PD", "ui_order": 1},
    )
    pd_column: str = Field(
        default="pd_calibrated",
        title="Columna PD",
        description="Columna de PD dentro del artefacto de la fuente declarada en pd_source.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "PD", "ui_order": 2},
    )
    grouping: InternalGroupingMethod = Field(
        default="score_band",
        title="Formación de grupos homogéneos",
        description=(
            "score_band: bandas por cuantil de PD dentro de cada cartera. "
            "segment/provided: grupos leídos de group_col (segmento de negocio o grupo ya formado)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Grupos", "ui_order": 1},
    )
    group_col: str | None = Field(
        default=None,
        title="Columna de grupo",
        description="Columna con el grupo homogéneo; obligatoria con grouping segment o provided.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Grupos", "ui_order": 2},
    )
    n_score_bands: int = Field(
        default=10,
        ge=2,
        title="Número de bandas de score",
        description="Cantidad de bandas por cuantil de PD; solo aplica con grouping='score_band'.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Grupos", "ui_order": 3},
    )
    lgd: InternalLgdConfig = Field(
        default_factory=InternalLgdConfig,
        title="LGD",
        description="Configuración de la pérdida dado el incumplimiento del grupo homogéneo.",
        json_schema_extra={"ui_widget": "section", "ui_group": "LGD", "ui_order": 1},
    )
    method: InternalProvisioningMethod = Field(
        default="pd_lgd",
        title="Método del B-1 §3",
        description=(
            "pd_lgd: Exposición · PD · LGD por grupo. direct_loss_rate: tasa de pérdida esperada "
            "del grupo tomada directamente de loss_rate_col, sin descomponer."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Método", "ui_order": 1},
    )
    loss_rate_col: str | None = Field(
        default=None,
        title="Columna de tasa de pérdida",
        description="Columna con la pérdida esperada por peso expuesto; exige direct_loss_rate.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Método", "ui_order": 2},
    )
    rounding: InternalRoundingPolicy = Field(
        default="currency_2dp",
        title="Redondeo de provisión",
        description="Política explícita de redondeo contable de la provisión publicada.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Método", "ui_order": 3},
    )
    fail_on_falta_dato: bool = Field(
        default=True,
        title="Fallar ante falta de dato",
        description=(
            "True: un nulo en exposición, PD, LGD o tasa de pérdida detiene la corrida con error. "
            "False: se imputa cero, la operación queda marcada como falta de dato y el resultado "
            "lo deja trazado."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Método", "ui_order": 4},
    )

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida columnas no vacías y las dependencias cruzadas de SDD-28 §5.1.

        Un enum declarado sin ruta real degrada en silencio: por eso ``group_col`` y
        ``loss_rate_col`` son obligatorias cuando el modo las lee, y **prohibidas** cuando no las
        lee (una columna declarada que el motor nunca abre es una mentira del config).
        """
        _require_non_empty_strings(
            {field: getattr(self, field) for field in _ROOT_COLUMN_FIELDS},
            context="provisioning_internal",
        )
        if self.grouping in _GROUP_COL_GROUPINGS:
            if self.group_col is None or not self.group_col.strip():
                raise InternalConfigError(
                    f"grouping='{self.grouping}' exige group_col con el nombre de la columna "
                    "que trae el grupo homogéneo."
                )
        elif self.group_col is not None:
            raise InternalConfigError(
                "grouping='score_band' forma los grupos desde la PD y nunca lee group_col: "
                "elimine group_col o cambie grouping a 'segment'/'provided'."
            )
        if self.method == "direct_loss_rate":
            if self.loss_rate_col is None or not self.loss_rate_col.strip():
                raise InternalConfigError(
                    "method='direct_loss_rate' exige loss_rate_col con la tasa de pérdida "
                    "esperada por operación."
                )
        elif self.loss_rate_col is not None:
            raise InternalConfigError(
                "method='pd_lgd' descompone la pérdida en PD y LGD y nunca lee loss_rate_col: "
                "elimine loss_rate_col o cambie method a 'direct_loss_rate'."
            )
        return self


def _require_non_empty_strings(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de columnas declarativos no sean vacíos."""
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise InternalConfigError(f"Los campos de {context} no pueden estar vacíos: {empty}.")
