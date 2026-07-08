"""Config declarativo de la capa ``performance`` (SDD-11 §5).

:class:`PerformanceConfig` es la sección ``performance`` de
:class:`~nikodym.core.config.NikodymConfig`: evaluación determinista de discriminación y tabla de
deciles/gains sobre el score y la PD calibrada post-modelo. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError

ScoreDirection = Literal["higher_is_lower_risk", "higher_is_higher_risk"]
EvaluationSource = Literal["pd_calibrated", "score"]
PerformancePartition = Literal["desarrollo", "holdout", "oot"]

__all__ = [
    "EvaluationSource",
    "PerformanceConfig",
    "PerformancePartition",
    "ScoreDirection",
]

_COLUMN_FIELDS: tuple[str, ...] = (
    "score_column",
    "pd_column",
    "target_column",
    "partition_column",
)
_OPTIONAL_THRESHOLD_KEYS: frozenset[str] = frozenset(
    {"auc_min", "gini_min", "ks_min", "psi_max", "csi_max"}
)


class PerformanceConfig(NikodymBaseConfig):
    """Sección ``performance`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-11 §5)."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema performance",
        description="Versión local del schema de performance para migraciones futuras.",
        json_schema_extra={
            "ui_widget": "hidden",
            "ui_group": "General",
            "ui_order": 0,
            "ui_help": (
                "Versión interna del formato de esta sección, usada para migraciones "
                "automáticas de configuraciones antiguas; no requiere edición manual."
            ),
        },
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección performance",
        description="== @register('standard', domain='performance') (SDD-11 §4).",
        json_schema_extra={
            "ui_widget": "hidden",
            "ui_group": "General",
            "ui_order": 1,
            "ui_help": "Identificador interno del tipo de sección; no requiere edición.",
        },
    )
    score_column: str = Field(
        default="score",
        title="Columna score",
        description="Columna con el score operacional publicado por scorecard.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 1,
            "ui_help": (
                "Nombre de la columna con el score operacional a evaluar. Ajústalo si en "
                "tu tabla la columna se llama distinto a 'score'."
            ),
        },
    )
    pd_column: str = Field(
        default="pd_calibrated",
        title="Columna PD calibrada",
        description="Columna con la probabilidad de default calibrada post-modelo.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 2,
            "ui_help": (
                "Nombre de la columna con la PD ya calibrada que se usa para métricas y "
                "deciles. Ajústalo si en tu tabla la columna se llama distinto a "
                "'pd_calibrated'."
            ),
        },
    )
    target_column: str = Field(
        default="target",
        title="Columna target",
        description="Columna binaria 0/1 usada para métricas supervisadas de desempeño.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 3,
            "ui_help": (
                "Nombre de la columna target (1 = default, 0 = no default) contra la que "
                "se miden KS, AUC/Gini y tasas de malos. Debe coincidir con tus datos."
            ),
        },
    )
    partition_column: str = Field(
        default="partition",
        title="Columna partición",
        description="Columna que identifica Desarrollo, Holdout y OOT.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 4,
            "ui_help": (
                "Nombre de la columna que indica a qué población pertenece cada registro "
                "(desarrollo, holdout u OOT), para reportar métricas separadas por cada una."
            ),
        },
    )
    score_direction: ScoreDirection = Field(
        default="higher_is_lower_risk",
        title="Dirección del score",
        description="Define si un score mayor representa menor riesgo o mayor riesgo.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Ranking",
            "ui_order": 1,
            "ui_help": (
                "Indica si un score más alto significa menor riesgo (lo habitual en "
                "scorecards) o mayor riesgo. Se usa para ordenar correctamente los "
                "deciles y calcular KS/AUC/Gini hacia el default."
            ),
        },
    )
    evaluation_source: EvaluationSource = Field(
        default="pd_calibrated",
        title="Fuente principal de ranking",
        description="Fuente primaria para ordenar riesgo al calcular KS, AUC, Gini y gains.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Ranking",
            "ui_order": 2,
            "ui_help": (
                "Define si el riesgo se ordena por la PD calibrada o por el score "
                "operacional al calcular KS, AUC/Gini y la tabla de deciles. La PD "
                "calibrada es la opción por defecto y recomendada."
            ),
        },
    )
    partitions: tuple[PerformancePartition, ...] = Field(
        default=("desarrollo", "holdout", "oot"),
        title="Particiones a evaluar",
        description="Particiones sobre las que se reportan métricas de desempeño.",
        json_schema_extra={
            "ui_widget": "multiselect",
            "ui_group": "Población",
            "ui_order": 1,
            "ui_help": (
                "Poblaciones (desarrollo, holdout, oot) sobre las que se calculan las "
                "métricas de desempeño. Quita una si no quieres evaluarla, por ejemplo "
                "si aún no tienes datos OOT."
            ),
        },
    )
    n_deciles: int = Field(
        default=10,
        ge=2,
        le=50,
        title="Número de grupos de gains",
        description="Cantidad de grupos ordenados por riesgo para la tabla de deciles/gains.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Métricas",
            "ui_order": 1,
            "ui_help": (
                "Cantidad de grupos (típicamente 10, es decir deciles) en que se ordena "
                "la población por riesgo para la tabla de gains. Con pocos registros el "
                "motor puede usar menos grupos de los pedidos."
            ),
        },
    )
    min_rows_per_partition: int = Field(
        default=30,
        ge=1,
        title="Mínimo técnico de filas",
        description="Mínimo de filas por partición para aceptar el cálculo de desempeño.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Población",
            "ui_order": 2,
            "ui_help": (
                "Filas mínimas que debe tener una partición para calcular sus métricas. "
                "Si no se alcanza, esa partición se reporta como no evaluable en vez de "
                "entregar un número poco confiable."
            ),
        },
    )
    min_events_per_partition: int = Field(
        default=1,
        ge=1,
        title="Mínimo técnico de malos",
        description="Mínimo de eventos de default por partición para métricas supervisadas.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Población",
            "ui_order": 3,
            "ui_help": (
                "Cantidad mínima de casos de default (malos) que debe tener una "
                "partición para calcular KS/AUC/Gini. Evita reportar métricas de "
                "discriminación calculadas con muy pocos eventos."
            ),
        },
    )
    optional_thresholds: dict[str, float] = Field(
        default_factory=dict,
        title="Umbrales institucionales opcionales",
        description="Ej.: {'auc_min': 0.60, 'ks_min': 0.20}. Vacío por defecto.",
        json_schema_extra={
            "ui_widget": "key_value",
            "ui_group": "Métricas",
            "ui_order": 2,
            "ui_help": (
                "Pisos institucionales opcionales para AUC, Gini y KS (auc_min, "
                "gini_min, ks_min). Si una partición queda bajo el umbral se marca con "
                "una alerta (threshold_flag), pero igual se reporta. Las claves "
                "psi_max/csi_max quedan reservadas para estabilidad, aún sin cálculo "
                "automático."
            ),
        },
    )

    @field_validator("optional_thresholds", mode="before")
    @classmethod
    def _check_optional_thresholds_pre(cls, valor: Any) -> Any:
        """Rechaza claves no documentadas y números no finitos antes de coaccionar."""
        if valor is None:
            return valor
        if not isinstance(valor, Mapping):
            return valor
        for clave, umbral in valor.items():
            if clave not in _OPTIONAL_THRESHOLD_KEYS:
                raise ConfigError(
                    "optional_thresholds solo admite claves documentadas: "
                    f"{sorted(_OPTIONAL_THRESHOLD_KEYS)}."
                )
            if isinstance(umbral, bool):
                raise ConfigError("optional_thresholds debe contener valores numéricos finitos.")
            if isinstance(umbral, (int, float)) and not math.isfinite(float(umbral)):
                raise ConfigError("optional_thresholds debe contener valores numéricos finitos.")
        return valor

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida columnas y thresholds definidos por SDD-11 §5."""
        columns = _column_values(self)
        vacias = [nombre for nombre, columna in columns.items() if not columna.strip()]
        if vacias:
            raise ConfigError(f"Las columnas de performance no pueden estar vacías: {vacias}.")

        normalizadas: dict[str, str] = {}
        duplicadas: list[tuple[str, str, str]] = []
        for nombre, columna in columns.items():
            clave = columna.strip()
            previo = normalizadas.get(clave)
            if previo is not None:
                duplicadas.append((previo, nombre, clave))
            normalizadas[clave] = nombre
        if duplicadas:
            raise ConfigError(f"Las columnas de performance no pueden colisionar: {duplicadas}.")

        for clave, umbral in self.optional_thresholds.items():
            if clave not in _OPTIONAL_THRESHOLD_KEYS:
                raise ConfigError(
                    "optional_thresholds solo admite claves documentadas: "
                    f"{sorted(_OPTIONAL_THRESHOLD_KEYS)}."
                )
            _require_finite(f"optional_thresholds.{clave}", umbral)

        return self


def _column_values(cfg: PerformanceConfig) -> dict[str, str]:
    """Devuelve nombres de columnas configurados para validar colisiones."""
    return {nombre: getattr(cfg, nombre) for nombre in _COLUMN_FIELDS}


def _require_finite(nombre: str, valor: float) -> None:
    """Valida finitud para campos float que participan del ``config_hash``."""
    if not math.isfinite(valor):
        raise ConfigError(f"{nombre} debe ser un número finito.")
