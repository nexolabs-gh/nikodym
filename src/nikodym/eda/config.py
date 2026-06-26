"""Config declarativo de la capa ``eda`` (SDD-27 §5).

:class:`EdaConfig` es la sección ``eda`` de :class:`~nikodym.core.config.NikodymConfig`:
diagnóstico exploratorio orientado a riesgo de crédito, sin transformar el dataset para el modelo.
Toda clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y
``frozen=True``); cada campo declara ``title``/``description`` y metadatos ``ui_*`` para que la UI
(SDD-23) sea un editor del mismo config. La sección es computacional, por lo que entra al
``config_hash`` global cuando está activa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from nikodym.core.config import NikodymBaseConfig

__all__ = [
    "DefaultRateConfig",
    "EdaConfig",
    "QualityConfig",
    "SamplingConfig",
    "TemporalStabilityConfig",
    "UnivariateConfig",
]


class DefaultRateConfig(NikodymBaseConfig):
    """Configuración de tasa de default por período o cohorte."""

    axis: Literal["period", "cohort"] = Field(
        default="period",
        title="Eje de agregación",
        description="'period' discretiza una fecha; 'cohort' usa una columna de añada/vintage.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Tasa de default",
            "ui_order": 1,
        },
    )
    date_col: str | None = Field(
        default=None,
        title="Columna de fecha (eje period)",
        description=(
            "Fecha de observación a discretizar. Debe ser dtype datetime (validado por data)."
        ),
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Tasa de default",
            "ui_order": 2,
        },
    )
    period_freq: Literal["M", "Q", "Y"] = Field(
        default="M",
        title="Frecuencia del período",
        description="Mensual/Trimestral/Anual para discretizar date_col.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Tasa de default",
            "ui_order": 3,
        },
    )
    cohort_col: str | None = Field(
        default=None,
        title="Columna de cohorte (eje cohort)",
        description="Categórica de añada/vintage; misma noción que data.partition.cohort_col.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Tasa de default",
            "ui_order": 4,
        },
    )
    min_obs_per_period: int = Field(
        default=50,
        ge=1,
        title="Mínimo de observaciones por período",
        description=(
            "Períodos con menos elegibles se marcan como poco fiables en la tabla (no se eliminan)."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Tasa de default",
            "ui_order": 5,
        },
    )


class TemporalStabilityConfig(NikodymBaseConfig):
    """Configuración del diagnóstico de estabilidad temporal descriptiva."""

    metric: Literal["cv", "max_relative_drift", "trend_slope"] = Field(
        default="cv",
        title="Indicador de estabilidad",
        description="Indicador comparado contra el umbral para señalar redesarrollo.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Estabilidad temporal",
            "ui_order": 1,
        },
    )
    threshold: float = Field(
        default=0.25,
        ge=0.0,
        title="Umbral del indicador",
        description="Por encima, se emite log_decision señalando posible redesarrollo (no aborta).",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Estabilidad temporal",
            "ui_order": 2,
        },
    )


class UnivariateConfig(NikodymBaseConfig):
    """Configuración de perfiles univariados descriptivos."""

    n_quantile_bins: int = Field(
        default=10,
        ge=2,
        le=50,
        title="Tramos por cuantiles (numéricas, descriptivo)",
        description="Troceo DESCRIPTIVO para el perfil; NO es el binning de SDD-06.",
        json_schema_extra={
            "ui_widget": "slider",
            "ui_group": "Perfiles univariados",
            "ui_order": 1,
        },
    )
    rare_level_threshold: float = Field(
        default=0.01,
        ge=0.0,
        le=0.5,
        title="Umbral de nivel raro (categóricas)",
        description=(
            "Niveles con frecuencia menor se agrupan en '_otros_' solo para la tabla descriptiva."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Perfiles univariados",
            "ui_order": 2,
        },
    )
    compute_descriptive_iv: bool = Field(
        default=False,
        title="Calcular IV univariado descriptivo (pre-binning)",
        description="Diagnóstico rápido; NO es el IV final de SDD-06. Etiquetado 'pre-binning'.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Perfiles univariados",
            "ui_order": 3,
        },
    )
    columns: tuple[str, ...] | None = Field(
        default=None,
        title="Columnas a perfilar",
        description=(
            "None = todas las no-estructurales (excluye target/status/partition/fecha/cohorte). "
            "Qué columnas son features lo decide SDD-06/07; aquí es solo el alcance del perfil."
        ),
        json_schema_extra={
            "ui_widget": "multiselect",
            "ui_group": "Perfiles univariados",
            "ui_order": 4,
        },
    )


class QualityConfig(NikodymBaseConfig):
    """Configuración de diagnóstico descriptivo de calidad de datos."""

    near_constant_threshold: float = Field(
        default=0.99,
        ge=0.5,
        le=1.0,
        title="Umbral casi-constante",
        description="Si un valor concentra >= este % de filas no nulas, se marca near_constant.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Calidad de datos",
            "ui_order": 1,
        },
    )
    high_cardinality_threshold: int = Field(
        default=50,
        ge=2,
        title="Umbral de alta cardinalidad (categóricas)",
        description="Categóricas con más niveles se marcan high_cardinality (solo reporte).",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Calidad de datos",
            "ui_order": 2,
        },
    )


class SamplingConfig(NikodymBaseConfig):
    """Configuración de muestreo opcional para datasets grandes."""

    enabled: bool = Field(
        default=False,
        title="Muestrear para los perfiles univariados",
        description=(
            "Si True, los perfiles/figuras se calculan sobre una muestra (usa el rng de core). "
            "La tasa de default por período se calcula SIEMPRE sobre el total (no se muestrea)."
        ),
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Muestreo",
            "ui_order": 1,
        },
    )
    max_rows: int = Field(
        default=500_000,
        ge=1000,
        title="Máximo de filas en la muestra",
        description="Límite de filas para perfiles univariados cuando el muestreo está activo.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Muestreo",
            "ui_order": 2,
        },
    )


class EdaConfig(NikodymBaseConfig):
    """Sección ``eda`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-27 §5)."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección EDA",
        description="== @register('standard', domain='eda') (D-CONV-2).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    analysis_partition: Literal["desarrollo", "holdout", "oot", "todas"] = Field(
        default="desarrollo",
        title="Partición a describir",
        description=(
            "Población base del análisis (default: Desarrollo, donde se ajusta el modelo). "
            "Los 'fuera_de_modelo' nunca entran al denominador de default_rate."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "General", "ui_order": 1},
    )
    default_rate: DefaultRateConfig = Field(
        default_factory=DefaultRateConfig,
        title="Tasa de default",
        description="Parámetros de agregación de la tasa de default descriptiva.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Tasa de default", "ui_order": 2},
    )
    stability: TemporalStabilityConfig = Field(
        default_factory=TemporalStabilityConfig,
        title="Estabilidad temporal",
        description="Parámetros del diagnóstico descriptivo de estabilidad temporal.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": "Estabilidad temporal",
            "ui_order": 3,
        },
    )
    univariate: UnivariateConfig = Field(
        default_factory=UnivariateConfig,
        title="Perfiles univariados",
        description="Parámetros de perfiles feature-target descriptivos.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": "Perfiles univariados",
            "ui_order": 4,
        },
    )
    quality: QualityConfig = Field(
        default_factory=QualityConfig,
        title="Calidad de datos",
        description="Parámetros de diagnóstico descriptivo de calidad de columnas.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": "Calidad de datos",
            "ui_order": 5,
        },
    )
    sampling: SamplingConfig = Field(
        default_factory=SamplingConfig,
        title="Muestreo",
        description="Parámetros de muestreo opt-in para perfiles sobre datasets grandes.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Muestreo", "ui_order": 6},
    )
