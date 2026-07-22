"""Config declarativo de la capa ``survival`` (SDD-18 §5).

:class:`SurvivalConfig` es la sección ``survival`` de
:class:`~nikodym.core.config.NikodymConfig`: estima lifetime PD con Kaplan-Meier,
discrete-time hazard, Cox PH o AFT. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.survival.exceptions import SurvivalConfigError

SurvivalMethod = Literal["discrete_hazard", "kaplan_meier", "cox_ph", "aft"]
DiscreteHazardLink = Literal["logit", "cloglog"]
PdSource = Literal["model_raw", "calibration", "none"]
AftFamily = Literal["weibull", "lognormal", "loglogistic"]
PdRole = Literal["covariate", "offset", "segment", "none"]

__all__ = [
    "AftFamily",
    "CoxAftConfig",
    "DiscreteHazardConfig",
    "DiscreteHazardLink",
    "KaplanMeierConfig",
    "PdSource",
    "SurvivalConfig",
    "SurvivalInputConfig",
    "SurvivalMethod",
    "SurvivalTimeGridConfig",
]

_INPUT_COLUMN_FIELDS: tuple[str, ...] = (
    "duration_col",
    "event_col",
    "id_col",
    "segment_col",
    "pd_column",
    "linear_predictor_column",
)


class SurvivalInputConfig(NikodymBaseConfig):
    """Configuración de columnas de entrada para survival."""

    duration_col: str = Field(
        default=...,
        title="Columna de duración",
        description="Columna con el tiempo hasta evento observado o censura derecha.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 1},
    )
    event_col: str = Field(
        default=...,
        title="Columna de evento",
        description="Columna indicadora de evento/default observado; 1=evento y 0=censura.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 2},
    )
    id_col: str | None = Field(
        default=None,
        title="Columna de identificador",
        description="Columna opcional con identificador estable de fila, cuenta o cliente.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 3},
    )
    segment_col: str | None = Field(
        default=None,
        title="Columna de segmento",
        description="Columna opcional de segmento o pool para agregación y diagnósticos.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 4},
    )
    pd_source: PdSource = Field(
        default="model_raw",
        title="Fuente PD",
        description="Origen de la PD del scorecard usada como insumo del modelo lifetime.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "PD del scorecard",
            "ui_order": 1,
        },
    )
    pd_column: str = Field(
        default="pd_raw",
        title="Columna PD cruda",
        description="Columna con PD cruda o calibrada según la fuente configurada.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "PD del scorecard",
            "ui_order": 2,
        },
    )
    linear_predictor_column: str = Field(
        default="linear_predictor",
        title="Columna predictor lineal",
        description=(
            "Columna con el logit o predictor lineal del scorecard, usada como covariable u offset."
        ),
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "PD del scorecard",
            "ui_order": 3,
        },
    )
    covariate_cols: tuple[str, ...] = Field(
        default=(),
        title="Covariables adicionales",
        description="Columnas adicionales ya preprocesadas que entran al ajuste survival.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Covariables", "ui_order": 1},
    )

    @model_validator(mode="after")
    def _check_columnas_input(self) -> Self:
        """Valida columnas no vacías y duración distinta de evento."""
        _require_non_empty_strings(_column_values(self, _INPUT_COLUMN_FIELDS), context="input")
        empty_covariates = [
            idx for idx, column in enumerate(self.covariate_cols) if not column.strip()
        ]
        if empty_covariates:
            raise SurvivalConfigError(
                f"Las covariables de input no pueden estar vacías: {empty_covariates}."
            )
        if self.duration_col.strip() == self.event_col.strip():
            raise SurvivalConfigError("duration_col y event_col deben ser columnas distintas.")
        return self


class SurvivalTimeGridConfig(NikodymBaseConfig):
    """Configuración de grilla temporal para proyecciones lifetime."""

    time_unit: str = Field(
        default="period",
        title="Unidad temporal",
        description="Unidad declarativa de duración y evaluación; por defecto, período genérico.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Horizonte", "ui_order": 1},
    )
    horizon_periods: int | None = Field(
        default=None,
        ge=1,
        title="Horizonte en períodos",
        description="Horizonte lifetime explícito; si falta, el motor usa la grilla observada.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Horizonte", "ui_order": 2},
    )
    evaluation_times: tuple[float, ...] = Field(
        default=(),
        title="Tiempos de evaluación",
        description="Tiempos explícitos de evaluación, en la unidad temporal declarada.",
        json_schema_extra={"ui_widget": "number_list", "ui_group": "Horizonte", "ui_order": 3},
    )

    @model_validator(mode="after")
    def _check_time_unit(self) -> Self:
        """Valida que la unidad temporal declarativa no esté vacía."""
        if not self.time_unit.strip():
            raise SurvivalConfigError("time_unit no puede estar vacío.")
        return self


class KaplanMeierConfig(NikodymBaseConfig):
    """Configuración de Kaplan-Meier y sus intervalos opcionales."""

    confidence_level: float | None = Field(
        default=None,
        gt=0.0,
        lt=1.0,
        title="Nivel de confianza",
        description="Nivel de confianza opcional para publicar bandas Kaplan-Meier.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Kaplan-Meier", "ui_order": 1},
    )
    confidence_transform: Literal["plain", "loglog"] | None = Field(
        default=None,
        title="Transformación de intervalo",
        description="Transformación usada para bandas de confianza de Kaplan-Meier.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Kaplan-Meier", "ui_order": 2},
    )

    @model_validator(mode="after")
    def _check_confidence_interval(self) -> Self:
        """Exige transformación cuando se declara nivel de confianza."""
        if self.confidence_level is not None and self.confidence_transform is None:
            raise SurvivalConfigError("kaplan_meier.confidence_level exige confidence_transform.")
        return self


class DiscreteHazardConfig(NikodymBaseConfig):
    """Configuración del modelo discrete-time hazard."""

    link: DiscreteHazardLink = Field(
        default="logit",
        title="Link del hazard",
        description="Función de enlace para el hazard discreto person-period.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Discrete hazard", "ui_order": 1},
    )
    include_period_dummies: bool = Field(
        default=True,
        title="Interceptos por período",
        description="Incluye dummies/interceptos por período en el ajuste person-period.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Discrete hazard", "ui_order": 2},
    )
    pd_role: PdRole = Field(
        default="covariate",
        title="Rol de la PD del scorecard",
        description="Rol de la PD o el logit del scorecard en el modelo de hazard discreto.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Discrete hazard", "ui_order": 3},
    )
    min_events_per_period: int | None = Field(
        default=None,
        ge=1,
        title="Mínimo de eventos por período",
        description="Mínimo técnico opcional de eventos por período para aceptar el ajuste.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Discrete hazard",
            "ui_order": 4,
        },
    )


class CoxAftConfig(NikodymBaseConfig):
    """Configuración compartida de Cox PH y AFT."""

    ph_test_enabled: bool = Field(
        default=True,
        title="Activar test PH",
        description="Activa diagnóstico de proporcionalidad de hazards para Cox PH.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Cox/AFT", "ui_order": 1},
    )
    ph_p_value_threshold: float | None = Field(
        default=None,
        gt=0.0,
        lt=1.0,
        title="Umbral p-value PH",
        description="Umbral opcional de p-value para fallar o advertir en diagnóstico PH.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Cox/AFT", "ui_order": 2},
    )
    aft_family: AftFamily | None = Field(
        default=None,
        title="Familia AFT",
        description="Familia paramétrica AFT; requerida si method='aft'.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Cox/AFT", "ui_order": 3},
    )


class SurvivalConfig(NikodymBaseConfig):
    """Modela el tiempo hasta el incumplimiento y obtiene de ahí la PD lifetime."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema survival",
        description="Versión local del schema de survival para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección survival",
        description="Variante de la sección de survival; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    method: SurvivalMethod = Field(
        default="discrete_hazard",
        title="Método survival",
        description="Ruta estadística usada para estimar supervivencia y PD lifetime.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Método", "ui_order": 1},
    )
    input: SurvivalInputConfig = Field(
        default=...,
        title="Entrada",
        description="Columnas de duración, evento, PD del scorecard y covariables.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Entrada", "ui_order": 1},
    )
    time_grid: SurvivalTimeGridConfig = Field(
        default_factory=SurvivalTimeGridConfig,
        title="Grilla temporal",
        description="Horizonte y tiempos explícitos de evaluación lifetime.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Horizonte", "ui_order": 1},
    )
    kaplan_meier: KaplanMeierConfig = Field(
        default_factory=KaplanMeierConfig,
        title="Kaplan-Meier",
        description="Parámetros no paramétricos e intervalos opcionales de Kaplan-Meier.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Kaplan-Meier", "ui_order": 1},
    )
    discrete_hazard: DiscreteHazardConfig = Field(
        default_factory=DiscreteHazardConfig,
        title="Discrete hazard",
        description="Parámetros de la ruta discrete-time hazard person-period.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Discrete hazard", "ui_order": 1},
    )
    cox_aft: CoxAftConfig = Field(
        default_factory=CoxAftConfig,
        title="Cox/AFT",
        description="Parámetros de Cox PH y AFT paramétrico.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Cox/AFT", "ui_order": 1},
    )
    fail_on_falta_dato: bool = Field(
        default=True,
        title="Fallar ante falta de dato",
        description=(
            "Campo reservado: hoy no altera la corrida, cualquiera sea su valor. Las brechas de "
            "datos de esta etapa quedan siempre registradas como aviso `FALTA-DATO-SUR-*` en su "
            "resultado."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Gobernanza", "ui_order": 1},
    )

    @model_validator(mode="before")
    @classmethod
    def _check_offset_raw(cls, data: Any) -> Any:
        """Valida temprano el requisito de predictor lineal para ``pd_role='offset'``."""
        if not isinstance(data, dict):
            return data
        discrete_raw = data.get("discrete_hazard")
        input_raw = data.get("input")
        if not isinstance(discrete_raw, dict) or discrete_raw.get("pd_role") != "offset":
            return data
        if not isinstance(input_raw, dict):
            return data
        linear_predictor = input_raw.get("linear_predictor_column", "linear_predictor")
        if not isinstance(linear_predictor, str) or not linear_predictor.strip():
            raise SurvivalConfigError(
                "discrete_hazard.pd_role='offset' exige linear_predictor_column no vacío."
            )
        return data

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida invariantes cruzados de SDD-18 §5."""
        if self.method == "aft" and self.cox_aft.aft_family is None:
            raise SurvivalConfigError("method='aft' exige cox_aft.aft_family.")
        return self


def _column_values(cfg: object, fields: tuple[str, ...]) -> dict[str, str]:
    """Devuelve nombres de columnas configurados para validar strings no vacíos."""
    values: dict[str, str] = {}
    for field in fields:
        value = getattr(cfg, field)
        if value is not None:
            values[field] = value
    return values


def _require_non_empty_strings(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de columnas declarativos no sean vacíos."""
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise SurvivalConfigError(f"Los campos de {context} no pueden estar vacíos: {empty}.")
