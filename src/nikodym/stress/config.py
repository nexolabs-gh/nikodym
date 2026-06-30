"""Config declarativo de la capa ``stress`` (SDD-21 §5).

:class:`StressConfig` es la sección ``stress`` de
:class:`~nikodym.core.config.NikodymConfig`: escenarios macro severos, barridos de sensibilidad y
reverse stress determinista sobre la cadena ``forward``. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from itertools import pairwise
from math import isfinite
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.stress.exceptions import (
    StressConfigError,
    StressDependencyError,
    StressError,
    StressFaltaDatoError,
    StressScenarioError,
)

StressOperation = Literal["additive", "relative"]
StressMetric = Literal["pd_marginal", "pd_cumulative", "lgd", "ecl", "provision", "loss", "ratio"]
StressDirection = Literal["at_least", "at_most"]

__all__ = [
    "ReverseStressConfig",
    "SensitivitySweepConfig",
    "StressConfig",
    "StressDirection",
    "StressInputConfig",
    "StressMetric",
    "StressOperation",
    "StressOutputConfig",
    "StressScenarioConfig",
    "StressShockConfig",
    "StressTargetConfig",
    "StressValidationConfig",
]

_RESERVED_SCENARIO_NAMES: frozenset[str] = frozenset({"mean", "average", "weighted_mean_input"})
_ECONOMIC_METRICS: frozenset[str] = frozenset({"ecl", "provision", "loss", "ratio"})


class StressInputConfig(NikodymBaseConfig):
    """Configuración de artefactos forward consumidos por stress."""

    forward_domain: str = Field(
        default="forward",
        title="Dominio forward",
        description="Dominio del ArtifactStore desde el que se leen artefactos forward.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 1},
    )
    macro_projection_key: str = Field(
        default="macro_projection",
        title="Clave macro_projection",
        description="Clave del artefacto de proyección macro publicado por ForwardStep.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 2},
    )
    satellite_model_key: str = Field(
        default="satellite_model",
        title="Clave satellite_model",
        description="Clave del modelo satellite publicado por ForwardStep.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 3},
    )
    term_structure_key: str = Field(
        default="term_structure",
        title="Clave term_structure",
        description="Clave de la term-structure forward-looking publicada por ForwardStep.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 4},
    )
    scenario_weighting_key: str = Field(
        default="scenario_weighting",
        title="Clave scenario_weighting",
        description="Clave del ponderador de escenarios publicado por ForwardStep.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 5},
    )
    ecl_input_key: str = Field(
        default="ecl_input",
        title="Clave ecl_input",
        description="Clave del contrato ForwardEclInput publicado por ForwardStep.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 6},
    )
    ecl_engine_artifact: tuple[str, str] | None = Field(
        default=None,
        title="Artefacto engine ECL",
        description="Artefacto opcional con engine ECL futuro de SDD-16, sin import duro.",
        json_schema_extra={"ui_widget": "artifact_key", "ui_group": "Engines", "ui_order": 1},
    )
    provision_engine_artifact: tuple[str, str] | None = Field(
        default=None,
        title="Artefacto engine provisión",
        description="Artefacto opcional con engine de provisión futura de SDD-17.",
        json_schema_extra={"ui_widget": "artifact_key", "ui_group": "Engines", "ui_order": 2},
    )

    @model_validator(mode="after")
    def _check_claves(self) -> Self:
        """Valida que las claves declarativas no estén vacías."""
        _require_non_empty_strings(
            {
                "forward_domain": self.forward_domain,
                "macro_projection_key": self.macro_projection_key,
                "satellite_model_key": self.satellite_model_key,
                "term_structure_key": self.term_structure_key,
                "scenario_weighting_key": self.scenario_weighting_key,
                "ecl_input_key": self.ecl_input_key,
            },
            context="input",
            error_cls=StressConfigError,
        )
        return self


class StressShockConfig(NikodymBaseConfig):
    """Shock macro declarado para un escenario de stress."""

    factor: str = Field(
        default=...,
        title="Factor macro",
        description="Nombre del factor macro a estresar.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Shock", "ui_order": 1},
    )
    operation: StressOperation = Field(
        default="additive",
        title="Operación",
        description="Operación del shock: aditiva o relativa.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Shock", "ui_order": 2},
    )
    value: float = Field(
        default=...,
        title="Magnitud del shock",
        description="Magnitud base del shock; no tiene default para no inventar escenarios.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Shock", "ui_order": 3},
    )
    unit: str | None = Field(
        default=None,
        title="Unidad",
        description="Unidad declarativa opcional del shock.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Shock", "ui_order": 4},
    )
    periods: tuple[int, ...] | Literal["all"] = Field(
        default="all",
        title="Períodos afectados",
        description="'all' o tupla no vacía de períodos positivos dentro del horizonte forward.",
        json_schema_extra={"ui_widget": "number_list", "ui_group": "Shock", "ui_order": 5},
    )
    source: Literal["user", "institutional", "official", "default_a_confirmar"] = Field(
        default="user",
        title="Fuente",
        description="Fuente declarada del shock; official exige evidencia externa versionada.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Shock", "ui_order": 6},
    )
    description: str | None = Field(
        default=None,
        title="Descripción",
        description="Descripción humana opcional del shock.",
        json_schema_extra={"ui_widget": "text_area", "ui_group": "Shock", "ui_order": 7},
    )

    @field_validator("value", mode="before")
    @classmethod
    def _check_value_finito(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` y rechaza magnitudes no finitas."""
        return _finite_float(value, field="shock.value", error_cls=StressScenarioError)

    @field_validator("periods", mode="before")
    @classmethod
    def _check_periodos_raw(cls, value: Any) -> Any:
        """Rechaza booleanos en períodos antes de que Pydantic los convierta a enteros."""
        if value == "all":
            return value
        try:
            periods = tuple(value)
        except TypeError:
            return value
        if any(isinstance(period, bool) for period in periods):
            raise StressConfigError("periods debe contener enteros, no booleanos.")
        return value

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida factor no vacío y períodos positivos."""
        _require_non_empty_strings(
            {"factor": self.factor}, context="shock", error_cls=StressConfigError
        )
        _check_periods(self.periods)
        return self


class StressScenarioConfig(NikodymBaseConfig):
    """Escenario severo o custom compuesto por shocks macro."""

    name: str = Field(
        default=...,
        title="Nombre",
        description="Nombre único del escenario de stress.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Escenario", "ui_order": 1},
    )
    kind: Literal["severe", "custom"] = Field(
        default="severe",
        title="Tipo",
        description="Tipo declarativo del escenario: severe o custom.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Escenario", "ui_order": 2},
    )
    base_forward_scenario: str = Field(
        default="severe",
        title="Escenario forward base",
        description="Escenario forward desde el que parte el stress.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Escenario", "ui_order": 3},
    )
    severity: float = Field(
        default=1.0,
        ge=0.0,
        title="Severidad",
        description="Multiplicador aplicado a todos los shocks del escenario.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Escenario", "ui_order": 4},
    )
    shocks: tuple[StressShockConfig, ...] = Field(
        default=...,
        min_length=1,
        title="Shocks",
        description="Shocks macro del escenario; debe haber al menos uno.",
        json_schema_extra={"ui_widget": "editable_table", "ui_group": "Escenario", "ui_order": 5},
    )
    weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        title="Peso",
        description="Peso opcional para reportes; no sustituye ponderación IFRS 9 oficial.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Escenario", "ui_order": 6},
    )
    require_dominates_forward_adverse: bool = Field(
        default=True,
        title="Exigir dominancia adverse",
        description="Exige demostrar que el shock domina el adverse forward comparable.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Escenario", "ui_order": 7},
    )
    description: str | None = Field(
        default=None,
        title="Descripción",
        description="Descripción humana opcional del escenario.",
        json_schema_extra={"ui_widget": "text_area", "ui_group": "Escenario", "ui_order": 8},
    )

    @field_validator("severity", mode="before")
    @classmethod
    def _check_severity_finita(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` y rechaza severidades no finitas."""
        return _finite_float(value, field="scenario.severity", error_cls=StressScenarioError)

    @field_validator("weight", mode="before")
    @classmethod
    def _check_weight_finito(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` y rechaza pesos no finitos."""
        if value is None:
            return value
        return _finite_float(value, field="scenario.weight", error_cls=StressScenarioError)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida nombre, escenario base y shocks del escenario."""
        _check_stress_scenario_name(self.name)
        _check_forward_scenario_name(self.base_forward_scenario, field="base_forward_scenario")
        return self


class SensitivitySweepConfig(NikodymBaseConfig):
    """Barrido de sensibilidad determinista para un factor macro."""

    name: str = Field(
        default=...,
        title="Nombre",
        description="Nombre único del barrido de sensibilidad.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Sensibilidad", "ui_order": 1},
    )
    factor: str = Field(
        default=...,
        title="Factor",
        description="Factor macro sobre el que se aplica la grilla de severidades.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Sensibilidad", "ui_order": 2},
    )
    operation: StressOperation = Field(
        default="additive",
        title="Operación",
        description="Operación del shock de sensibilidad.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Sensibilidad", "ui_order": 3},
    )
    base_forward_scenario: str = Field(
        default="severe",
        title="Escenario forward base",
        description="Escenario forward desde el que parte la sensibilidad.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Sensibilidad", "ui_order": 4},
    )
    shock_value: float = Field(
        default=...,
        title="Shock base",
        description="Magnitud base del shock que multiplica la grilla de severidad.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Sensibilidad", "ui_order": 5},
    )
    severity_grid: tuple[float, ...] = Field(
        default=(0.0, 0.5, 1.0, 1.5, 2.0),
        title="Grilla de severidad",
        description="Grilla determinista, finita, no negativa y estrictamente creciente.",
        json_schema_extra={"ui_widget": "number_list", "ui_group": "Sensibilidad", "ui_order": 6},
    )
    metric: StressMetric = Field(
        default="ecl",
        title="Métrica",
        description="Métrica analizada en el barrido.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Sensibilidad", "ui_order": 7},
    )
    group_cols: tuple[str, ...] = Field(
        default=("scenario",),
        title="Columnas de grupo",
        description="Columnas usadas para agrupar la métrica de sensibilidad.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Sensibilidad", "ui_order": 8},
    )
    require_monotonic: bool = Field(
        default=False,
        title="Exigir monotonicidad",
        description="Si es True, el resultado no monotónico falla en el motor.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Sensibilidad", "ui_order": 9},
    )

    @field_validator("shock_value", mode="before")
    @classmethod
    def _check_shock_value_finito(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` y rechaza shocks no finitos."""
        return _finite_float(value, field="sensitivity.shock_value", error_cls=StressConfigError)

    @field_validator("severity_grid", mode="before")
    @classmethod
    def _check_severity_grid_finita(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` elemento a elemento antes del hash."""
        return _finite_float_tuple(
            value, field="sensitivity.severity_grid", error_cls=StressConfigError
        )

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida nombre, factor, grilla y columnas de grupo."""
        _require_non_empty_strings(
            {"name": self.name, "factor": self.factor},
            context="sensitivity",
            error_cls=StressConfigError,
        )
        _check_forward_scenario_name(self.base_forward_scenario, field="base_forward_scenario")
        _check_non_empty_string_tuple(self.group_cols, field="group_cols")
        _check_severity_grid(self.severity_grid)
        return self


class StressTargetConfig(NikodymBaseConfig):
    """Target económico o probabilístico para reverse stress."""

    name: str = Field(
        default=...,
        title="Nombre",
        description="Nombre único del target de reverse stress.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Target", "ui_order": 1},
    )
    metric: StressMetric = Field(
        default=...,
        title="Métrica",
        description="Métrica objetivo del reverse stress.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Target", "ui_order": 2},
    )
    threshold: float = Field(
        default=...,
        title="Umbral",
        description="Umbral objetivo que la métrica debe cruzar.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Target", "ui_order": 3},
    )
    direction: StressDirection = Field(
        default="at_least",
        title="Dirección",
        description="Dirección del cruce: al menos o a lo más el umbral.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Target", "ui_order": 4},
    )
    scenario_name: str = Field(
        default=...,
        title="Escenario",
        description="Nombre del escenario de stress al que aplica el target.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Target", "ui_order": 5},
    )
    group_filter: dict[str, str | int | float | bool] = Field(
        default_factory=dict,
        title="Filtro de grupo",
        description="Filtro exacto por columnas de grupo para evaluar el target.",
        json_schema_extra={"ui_widget": "key_value", "ui_group": "Target", "ui_order": 6},
    )
    requires_economic_engine: bool = Field(
        default=True,
        title="Requiere engine económico",
        description="Indica si la métrica exige engine ECL/provisión conectado.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Target", "ui_order": 7},
    )

    @field_validator("threshold", mode="before")
    @classmethod
    def _check_threshold_finito(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` y rechaza umbrales no finitos."""
        return _finite_float(value, field="target.threshold", error_cls=StressConfigError)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida texto y filtros del target."""
        _require_non_empty_strings(
            {"name": self.name, "scenario_name": self.scenario_name},
            context="target",
            error_cls=StressConfigError,
        )
        _check_group_filter(self.group_filter)
        return self


class ReverseStressConfig(NikodymBaseConfig):
    """Configuración de reverse stress por bisección monotónica."""

    enabled: bool = Field(
        default=False,
        title="Activar reverse stress",
        description="Activa la búsqueda de severidad que cruza el target.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Reverse", "ui_order": 1},
    )
    target: StressTargetConfig | None = Field(
        default=None,
        title="Target",
        description="Target obligatorio cuando enabled=True.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Reverse", "ui_order": 2},
    )
    factor: str = Field(
        default=...,
        title="Factor",
        description="Factor macro ajustado por la severidad buscada.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Reverse", "ui_order": 3},
    )
    operation: StressOperation = Field(
        default="additive",
        title="Operación",
        description="Operación del shock usado por reverse stress.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Reverse", "ui_order": 4},
    )
    shock_value: float = Field(
        default=...,
        title="Shock base",
        description="Magnitud base del shock multiplicada por la severidad buscada.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Reverse", "ui_order": 5},
    )
    bracket: tuple[float, float] = Field(
        default=(0.0, 5.0),
        title="Bracket",
        description="Intervalo [lo, hi] finito, no negativo y con lo < hi.",
        json_schema_extra={"ui_widget": "number_tuple", "ui_group": "Reverse", "ui_order": 6},
    )
    severity_tol: float = Field(
        default=1e-6,
        gt=0.0,
        lt=1e-2,
        title="Tolerancia de severidad",
        description="Tolerancia de ancho de bracket para detener la bisección.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Reverse", "ui_order": 7},
    )
    metric_tol: float = Field(
        default=1e-8,
        gt=0.0,
        lt=1e-2,
        title="Tolerancia de métrica",
        description="Tolerancia de diferencia contra el umbral objetivo.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Reverse", "ui_order": 8},
    )
    max_iterations: int = Field(
        default=64,
        ge=1,
        le=256,
        title="Iteraciones máximas",
        description="Máximo de iteraciones de bisección determinista.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Reverse", "ui_order": 9},
    )
    monotonicity_check_points: tuple[float, ...] = Field(
        default=(0.0, 0.5, 1.0, 2.0, 5.0),
        title="Puntos de monotonicidad",
        description="Puntos diagnósticos donde el motor verifica monotonicidad.",
        json_schema_extra={"ui_widget": "number_list", "ui_group": "Reverse", "ui_order": 10},
    )

    @field_validator("shock_value", "severity_tol", "metric_tol", mode="before")
    @classmethod
    def _check_float_finito(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` y rechaza floats no finitos."""
        return _finite_float(value, field="reverse.float", error_cls=StressConfigError)

    @field_validator("bracket", mode="before")
    @classmethod
    def _check_bracket_finito(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` en el bracket antes del hash."""
        return _finite_float_tuple(value, field="reverse.bracket", error_cls=StressConfigError)

    @field_validator("monotonicity_check_points", mode="before")
    @classmethod
    def _check_monotonicity_check_points_finitos(cls, value: Any) -> Any:
        """Normaliza ``-0.0`` en los puntos de diagnóstico antes del hash."""
        return _finite_float_tuple(
            value, field="reverse.monotonicity_check_points", error_cls=StressConfigError
        )

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida bracket, target obligatorio y puntos de diagnóstico."""
        _require_non_empty_strings(
            {"factor": self.factor}, context="reverse", error_cls=StressConfigError
        )
        _check_bracket(self.bracket)
        _check_monotonicity_points(self.monotonicity_check_points)
        if self.enabled and self.target is None:
            raise StressConfigError("reverse.target es obligatorio cuando reverse.enabled=True.")
        return self


class StressOutputConfig(NikodymBaseConfig):
    """Configuración de métricas y artefactos publicados por stress."""

    metrics: tuple[StressMetric, ...] = Field(
        default=("pd_marginal", "pd_cumulative", "ecl"),
        title="Métricas",
        description="Métricas publicadas por stress; ecl exige engine si se calcula.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Salida", "ui_order": 1},
    )
    publish_stressed_macro: bool = Field(
        default=True,
        title="Publicar macro estresada",
        description="Publica el frame macro estresado cuando el motor lo materializa.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 2},
    )
    publish_stressed_term_structure: bool = Field(
        default=True,
        title="Publicar term-structure",
        description="Publica la term-structure estresada CT-2.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 3},
    )
    publish_reverse_path: bool = Field(
        default=True,
        title="Publicar path reverse",
        description="Publica el path de bisección de reverse stress.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 4},
    )
    include_baseline_rows: bool = Field(
        default=True,
        title="Incluir baseline",
        description="Incluye filas baseline para medir impactos absolutos y relativos.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 5},
    )

    @model_validator(mode="after")
    def _check_metrics(self) -> Self:
        """Valida que la lista de métricas no esté vacía."""
        if not self.metrics:
            raise StressConfigError("output.metrics no puede estar vacío.")
        return self


class StressValidationConfig(NikodymBaseConfig):
    """Configuración de tolerancias y políticas de falla de stress."""

    probability_tol: float = Field(
        default=1e-10,
        gt=0.0,
        lt=1e-3,
        title="Tolerancia de probabilidad",
        description="Tolerancia para validar probabilidades dentro de [0, 1].",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Validación", "ui_order": 1},
    )
    metric_tol: float = Field(
        default=1e-8,
        gt=0.0,
        lt=1e-2,
        title="Tolerancia de métrica",
        description="Tolerancia numérica para comparar métricas de salida.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Validación", "ui_order": 2},
    )
    weight_sum_tol: float = Field(
        default=1e-12,
        gt=0.0,
        lt=1e-3,
        title="Tolerancia suma pesos",
        description="Tolerancia para validar sumas de pesos cuando se declaren.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Validación", "ui_order": 3},
    )
    require_forward_severe: bool = Field(
        default=True,
        title="Exigir forward severe",
        description="Exige que exista escenario severe forward para comparación.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Validación", "ui_order": 4},
    )
    require_dominates_forward_adverse: bool = Field(
        default=True,
        title="Exigir dominancia adverse",
        description="Exige demostrar dominancia frente a adverse cuando aplique.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Validación", "ui_order": 5},
    )
    fail_on_missing_ecl_engine: bool = Field(
        default=True,
        title="Fallar sin engine ECL",
        description="Falla si una métrica económica requiere engine ECL ausente.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Validación", "ui_order": 6},
    )
    fail_on_falta_dato: bool = Field(
        default=True,
        title="Fallar ante FALTA-DATO",
        description="Falla ante brechas FALTA-DATO-STR en vez de solo advertir.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Validación", "ui_order": 7},
    )

    @field_validator("probability_tol", "metric_tol", "weight_sum_tol", mode="before")
    @classmethod
    def _check_tolerancia_finita(cls, value: Any) -> Any:
        """Rechaza tolerancias no finitas antes de entrar al ``config_hash``."""
        return _finite_float(value, field="validation.tolerance", error_cls=StressConfigError)


class StressConfig(NikodymBaseConfig):
    """Sección ``stress`` de :class:`~nikodym.core.config.NikodymConfig`."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección stress",
        description="== @register('standard', domain='stress') (SDD-21 §4).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    input: StressInputConfig = Field(
        default_factory=StressInputConfig,
        title="Entrada",
        description="Artefactos forward y hooks opcionales de engines económicos.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Entrada", "ui_order": 1},
    )
    scenarios: tuple[StressScenarioConfig, ...] = Field(
        default_factory=tuple,
        title="Escenarios",
        description="Escenarios severos o custom declarados por el usuario.",
        json_schema_extra={"ui_widget": "editable_table", "ui_group": "Escenarios", "ui_order": 1},
    )
    sensitivities: tuple[SensitivitySweepConfig, ...] = Field(
        default_factory=tuple,
        title="Sensibilidades",
        description="Barridos deterministas de severidad por factor.",
        json_schema_extra={
            "ui_widget": "editable_table",
            "ui_group": "Sensibilidades",
            "ui_order": 1,
        },
    )
    reverse: tuple[ReverseStressConfig, ...] = Field(
        default_factory=tuple,
        title="Reverse stress",
        description="Targets y brackets de reverse stress por bisección.",
        json_schema_extra={"ui_widget": "editable_table", "ui_group": "Reverse", "ui_order": 1},
    )
    output: StressOutputConfig = Field(
        default_factory=StressOutputConfig,
        title="Salida",
        description="Métricas y artefactos publicados por stress.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Salida", "ui_order": 1},
    )
    validation: StressValidationConfig = Field(
        default_factory=StressValidationConfig,
        title="Validación",
        description="Tolerancias y políticas de falla FALTA-DATO.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Validación", "ui_order": 1},
    )

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida invariantes cruzados de SDD-21 §5."""
        if not self.scenarios and not self.sensitivities and not self.reverse:
            raise StressConfigError(
                "stress exige al menos un escenario, una sensibilidad o un reverse stress."
            )
        _check_unique_scenario_names(self.scenarios)
        _check_reverse_targets(self)
        _check_relative_policy(self)
        _check_missing_economic_engine(self)
        _check_falta_dato(self)
        return self


def _finite_float(value: Any, *, field: str, error_cls: type[StressError]) -> float:
    """Convierte a float finito y normaliza ``-0.0`` para identidad reproducible."""
    if isinstance(value, bool):
        raise error_cls(f"{field} debe ser un número finito, no booleano.")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise error_cls(f"{field} debe ser un número finito.") from exc
    if not isfinite(numeric):
        raise error_cls(f"{field} debe ser un número finito.")
    return 0.0 if numeric == 0.0 else numeric


def _finite_float_tuple(
    value: Any, *, field: str, error_cls: type[StressError]
) -> tuple[float, ...] | Any:
    """Normaliza secuencias de floats finitos preservando el orden declarado."""
    if not isinstance(value, (list, tuple)):
        return value
    return tuple(
        _finite_float(item, field=f"{field}[{index}]", error_cls=error_cls)
        for index, item in enumerate(value)
    )


def _require_non_empty_strings(
    values: dict[str, str], *, context: str, error_cls: type[StressError]
) -> None:
    """Valida que los textos declarativos no estén vacíos."""
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise error_cls(f"Los campos de {context} no pueden estar vacíos: {empty}.")


def _check_non_empty_string_tuple(values: tuple[str, ...], *, field: str) -> None:
    """Valida que una tupla de strings no esté vacía ni contenga blanks."""
    if not values:
        raise StressConfigError(f"{field} no puede estar vacío.")
    empty = [idx for idx, value in enumerate(values) if not value.strip()]
    if empty:
        raise StressConfigError(f"{field} no puede contener strings vacíos: {empty}.")


def _check_periods(periods: tuple[int, ...] | Literal["all"]) -> None:
    """Valida períodos positivos; el horizonte exacto se verifica contra artefactos forward."""
    if periods == "all":
        return
    if not periods:
        raise StressConfigError("periods debe ser 'all' o una tupla no vacía.")
    non_positive = [idx for idx, period in enumerate(periods) if period <= 0]
    if non_positive:
        raise StressConfigError(f"periods debe contener períodos positivos: {non_positive}.")


def _check_severity_grid(values: tuple[float, ...]) -> None:
    """Valida que la grilla sea finita, no negativa y estrictamente creciente."""
    if not values:
        raise StressConfigError("severity_grid no puede estar vacío.")
    invalid = [idx for idx, value in enumerate(values) if not isfinite(value) or value < 0.0]
    if invalid:
        raise StressConfigError(
            f"severity_grid debe contener valores finitos y no negativos: {invalid}."
        )
    if any(next_value <= current for current, next_value in pairwise(values)):
        raise StressConfigError("severity_grid debe ser estrictamente creciente.")


def _check_bracket(bracket: tuple[float, float]) -> None:
    """Valida bracket no negativo y ordenado."""
    lo, hi = bracket
    if lo < 0.0 or hi < 0.0:
        raise StressConfigError("reverse.bracket debe contener valores no negativos.")
    if lo >= hi:
        raise StressConfigError("reverse.bracket debe cumplir lo < hi.")


def _check_monotonicity_points(values: tuple[float, ...]) -> None:
    """Valida puntos diagnósticos de reverse stress."""
    if not values:
        raise StressConfigError("monotonicity_check_points no puede estar vacío.")
    invalid = [idx for idx, value in enumerate(values) if not isfinite(value) or value < 0.0]
    if invalid:
        raise StressConfigError(
            f"monotonicity_check_points debe contener valores finitos y no negativos: {invalid}."
        )
    if any(next_value <= current for current, next_value in pairwise(values)):
        raise StressConfigError("monotonicity_check_points debe ser estrictamente creciente.")


def _check_stress_scenario_name(name: str) -> None:
    """Valida nombre no vacío y no reservado para escenarios de stress."""
    stripped = name.strip()
    if not stripped:
        raise StressScenarioError("scenario.name no puede estar vacío.")
    if stripped in _RESERVED_SCENARIO_NAMES:
        raise StressScenarioError(
            f"scenario.name usa un nombre reservado para escenarios medios: {stripped!r}."
        )


def _check_forward_scenario_name(name: str, *, field: str) -> None:
    """Valida forma del escenario forward; la existencia se verifica contra artefactos."""
    stripped = name.strip()
    if not stripped:
        raise StressScenarioError(f"{field} no puede estar vacío.")
    if stripped in _RESERVED_SCENARIO_NAMES:
        raise StressScenarioError(
            f"{field} usa un nombre reservado para escenarios medios: {stripped!r}."
        )


def _check_unique_scenario_names(scenarios: tuple[StressScenarioConfig, ...]) -> None:
    """Valida unicidad de nombres de escenarios de stress."""
    names = [scenario.name.strip() for scenario in scenarios]
    if len(set(names)) != len(names):
        raise StressScenarioError("stress.scenarios no puede contener nombres duplicados.")


def _check_group_filter(group_filter: dict[str, str | int | float | bool]) -> None:
    """Valida filtros de grupo JSON-canónicos y sin floats no finitos."""
    empty_keys = [key for key in group_filter if not key.strip()]
    if empty_keys:
        raise StressConfigError(f"group_filter no puede contener claves vacías: {empty_keys}.")
    invalid_values = [
        key
        for key, value in group_filter.items()
        if isinstance(value, float) and not isfinite(value)
    ]
    if invalid_values:
        raise StressConfigError(
            f"group_filter debe contener valores float finitos: {invalid_values}."
        )


def _check_reverse_targets(cfg: StressConfig) -> None:
    """Valida que los reverse habilitados apunten a escenarios existentes cuando aplica."""
    scenario_names = {scenario.name.strip() for scenario in cfg.scenarios}
    for reverse in cfg.reverse:
        if reverse.target is None:
            continue
        if scenario_names and reverse.target.scenario_name.strip() not in scenario_names:
            raise StressScenarioError(
                "reverse.target.scenario_name debe existir en stress.scenarios: "
                f"{reverse.target.scenario_name!r}."
            )


def _check_relative_policy(cfg: StressConfig) -> None:
    """Falla ante shocks relativos sin política de factores cero/negativos (FALTA-DATO-STR-7)."""
    relative_fields: list[str] = []
    for scenario in cfg.scenarios:
        relative_fields.extend(
            f"scenario:{scenario.name}:{shock.factor}"
            for shock in scenario.shocks
            if shock.operation == "relative"
        )
    relative_fields.extend(
        f"sensitivity:{sweep.name}:{sweep.factor}"
        for sweep in cfg.sensitivities
        if sweep.operation == "relative"
    )
    relative_fields.extend(
        f"reverse:{reverse.factor}" for reverse in cfg.reverse if reverse.operation == "relative"
    )
    if relative_fields:
        raise StressConfigError(
            "FALTA-DATO-STR-7: operation='relative' exige política explícita para factores que "
            f"pueden ser cero o negativos; pendientes={relative_fields}."
        )


def _check_missing_economic_engine(cfg: StressConfig) -> None:
    """Valida targets económicos que requieren engine conectado."""
    if not cfg.validation.fail_on_missing_ecl_engine:
        return
    has_engine = (
        cfg.input.ecl_engine_artifact is not None or cfg.input.provision_engine_artifact is not None
    )
    missing = [
        reverse.target.name
        for reverse in cfg.reverse
        if reverse.target is not None
        and reverse.target.requires_economic_engine
        and reverse.target.metric in _ECONOMIC_METRICS
        and not has_engine
    ]
    if missing:
        raise StressDependencyError(
            "Targets económicos requieren ecl_engine_artifact/provision_engine_artifact o un "
            f"engine pasado por API: {missing}."
        )


def _check_falta_dato(cfg: StressConfig) -> None:
    """Valida brechas FALTA-DATO-STR que no pueden demostrarse desde config puro."""
    if not cfg.validation.fail_on_falta_dato:
        return
    official_shocks = [
        f"{scenario.name}:{shock.factor}"
        for scenario in cfg.scenarios
        for shock in scenario.shocks
        if shock.source == "official"
    ]
    if official_shocks:
        raise StressFaltaDatoError(
            "FALTA-DATO-STR-2: source='official' exige metadata externa de archivo/hash/fuente; "
            f"sin evidencia={official_shocks}."
        )
    if cfg.validation.require_dominates_forward_adverse:
        undemonstrated = [
            scenario.name
            for scenario in cfg.scenarios
            if scenario.require_dominates_forward_adverse
        ]
        if undemonstrated:
            raise StressFaltaDatoError(
                "FALTA-DATO-STR-1: no se puede demostrar dominancia frente a forward adverse "
                f"sin metadata comparable; escenarios={undemonstrated}."
            )
