"""Config declarativo de la capa ``stability`` (SDD-11 §5).

:class:`StabilityConfig` es la sección ``stability`` de
:class:`~nikodym.core.config.NikodymConfig`: monitoreo determinista de PSI del score/PD, CSI de
características finales y estabilidad temporal post-modelo. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError

ScoreDirection = Literal["higher_is_lower_risk", "higher_is_higher_risk"]
StabilityComparison = Literal["dev_vs_holdout", "dev_vs_oot"]
TemporalAxis = Literal["none", "period", "cohort"]
TemporalFrequency = Literal["M", "Q", "Y"]
CsiSource = Literal["score_points", "woe_bins"]

__all__ = [
    "CsiSource",
    "ScoreDirection",
    "StabilityComparison",
    "StabilityConfig",
    "TemporalAxis",
    "TemporalFrequency",
]

_COLUMN_FIELDS: tuple[str, ...] = (
    "score_column",
    "pd_column",
    "partition_column",
)


class StabilityConfig(NikodymBaseConfig):
    """Mide la estabilidad del score y de la PD calibrada con PSI y CSI."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema stability",
        description="Versión local del schema de stability para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección stability",
        description="Variante de la sección de estabilidad; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    score_column: str = Field(
        default="score",
        title="Columna score",
        description="Columna con el score operacional publicado por scorecard.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    pd_column: str = Field(
        default="pd_calibrated",
        title="Columna PD calibrada",
        description="Columna con la probabilidad de default calibrada post-modelo.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    partition_column: str = Field(
        default="partition",
        title="Columna partición",
        description="Columna que identifica Desarrollo, Holdout y OOT.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )
    score_direction: ScoreDirection = Field(
        default="higher_is_lower_risk",
        title="Dirección del score",
        description="Define si un score mayor representa menor riesgo o mayor riesgo.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Ranking", "ui_order": 1},
    )
    psi_bins: int = Field(
        default=10,
        ge=2,
        le=50,
        title="Bins para PSI de score",
        description="Cantidad de bins definidos en Desarrollo para comparar score/PD.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 1},
    )
    csi_bins: int = Field(
        default=10,
        ge=2,
        le=50,
        title="Bins para CSI si no hay puntos discretos",
        description="Cantidad de bins para CSI cuando la fuente no provee puntos discretos.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 2},
    )
    psi_stable_threshold: float = Field(
        default=0.10,
        ge=0.0,
        title="PSI estable hasta",
        description="Umbral bajo el cual el PSI se considera estable.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 3},
    )
    psi_review_threshold: float = Field(
        default=0.25,
        ge=0.0,
        title="PSI vigilar hasta",
        description="Umbral sobre el cual el PSI gatilla revisión/redesarrollo.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 4},
    )
    smoothing: float = Field(
        default=1e-6,
        gt=0.0,
        title="Suavizado de proporciones",
        description="Valor positivo aplicado a proporciones cero en PSI/CSI.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 5},
    )
    comparisons: tuple[StabilityComparison, ...] = Field(
        default=("dev_vs_holdout", "dev_vs_oot"),
        title="Comparaciones de estabilidad",
        description="Pares de particiones a comparar usando Desarrollo como población esperada.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Población", "ui_order": 1},
    )
    temporal_axis: TemporalAxis = Field(
        default="period",
        title="Eje temporal del score",
        description="Eje usado para estabilidad temporal: período, cohorte o ninguno.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Temporal", "ui_order": 1},
    )
    temporal_column: str | None = Field(
        default=None,
        title="Columna de período/cohorte",
        description=(
            "Si se deja vacía y el eje temporal no es 'none', se infiere de los datos cuando hay "
            "una sola columna candidata; si hay varias o ninguna, la corrida se detiene con error."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Temporal", "ui_order": 2},
    )
    temporal_freq: TemporalFrequency = Field(
        default="M",
        title="Frecuencia temporal",
        description=(
            "Frecuencia de agregación para estabilidad temporal: mensual, trimestral o anual."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Temporal", "ui_order": 3},
    )
    include_pd_stability: bool = Field(
        default=True,
        title="Incluir estabilidad de PD calibrada",
        description="Activa el cálculo de PSI sobre la PD calibrada además del score.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Métricas", "ui_order": 6},
    )
    csi_source: CsiSource = Field(
        default="score_points",
        title="Fuente de CSI",
        description=(
            "Fuente de las distribuciones del CSI. 'woe_bins' está reservada y aún no "
            "implementada: si se elige, la corrida se detiene con error."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Métricas", "ui_order": 7},
    )

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida columnas, umbrales y decisiones diferidas de SDD-11 §5."""
        columns = _column_values(self)
        vacias = [nombre for nombre, columna in columns.items() if not columna.strip()]
        if vacias:
            raise ConfigError(f"Las columnas de stability no pueden estar vacías: {vacias}.")

        normalizadas: dict[str, str] = {}
        duplicadas: list[tuple[str, str, str]] = []
        for nombre, columna in columns.items():
            clave = columna.strip()
            previo = normalizadas.get(clave)
            if previo is not None:
                duplicadas.append((previo, nombre, clave))
            normalizadas[clave] = nombre
        if duplicadas:
            raise ConfigError(f"Las columnas de stability no pueden colisionar: {duplicadas}.")

        _require_finite("psi_stable_threshold", self.psi_stable_threshold)
        _require_finite("psi_review_threshold", self.psi_review_threshold)
        _require_finite("smoothing", self.smoothing)

        if self.psi_stable_threshold >= self.psi_review_threshold:
            raise ConfigError(
                "psi_stable_threshold debe ser estrictamente menor que psi_review_threshold."
            )
        if self.csi_source == "woe_bins":
            raise ConfigError(
                "csi_source='woe_bins' aún no está soportado: falta ratificar el contrato de "
                "binning con los artefactos WoE requeridos por SDD-11 D-STAB-5."
            )

        return self


def _column_values(cfg: StabilityConfig) -> dict[str, str]:
    """Devuelve nombres de columnas configurados para validar colisiones."""
    columns: dict[str, str] = {nombre: getattr(cfg, nombre) for nombre in _COLUMN_FIELDS}
    if cfg.temporal_column is not None:
        columns["temporal_column"] = cfg.temporal_column
    return columns


def _require_finite(nombre: str, valor: float) -> None:
    """Valida finitud para campos float que participan del ``config_hash``."""
    if not math.isfinite(valor):
        raise ConfigError(f"{nombre} debe ser un número finito.")
