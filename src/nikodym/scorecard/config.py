"""Config declarativo de la capa ``scorecard`` (SDD-09 §5).

:class:`ScorecardConfig` es la sección ``scorecard`` de
:class:`~nikodym.core.config.NikodymConfig`: escalamiento determinista de log-odds a puntos de
scorecard desde el modelo logístico PD. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import math
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError

ScoreDirection = Literal["higher_is_lower_risk", "higher_is_higher_risk"]
RoundingMethod = Literal["none", "nearest_integer", "floor_integer", "ceil_integer"]
InterceptAllocation = Literal["uniform"]

__all__ = [
    "InterceptAllocation",
    "PointOverrideConfig",
    "RoundingMethod",
    "ScoreDirection",
    "ScorecardConfig",
]


class PointOverrideConfig(NikodymBaseConfig):
    """Override manual auditado para una pareja ``feature``/``bin_label``."""

    feature: str = Field(
        default=...,
        title="Variable",
        description="Nombre de la variable cuyo bin recibe un override manual de puntos.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Overrides",
            "ui_order": 1,
            "ui_help": (
                "Nombre exacto de la variable, tal como aparece en el modelo, cuyo bin se "
                "fuerza manualmente."
            ),
        },
    )
    bin_label: str = Field(
        default=...,
        title="Bin",
        description="Etiqueta del bin al que se le fuerza un puntaje publicado.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Overrides",
            "ui_order": 2,
            "ui_help": (
                "Etiqueta exacta del bin, tal como aparece en la tabla de binning de esa "
                "variable. Si no calza exactamente, el override no se aplica."
            ),
        },
    )
    points: int | float = Field(
        default=...,
        title="Puntos forzados",
        description="Puntos publicados para la pareja variable/bin indicada.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Overrides",
            "ui_order": 3,
            "ui_help": (
                "Puntaje que se publica para esta variable/bin en vez del calculado por "
                "fórmula a partir del WoE y el coeficiente."
            ),
        },
    )
    reason: str = Field(
        default=...,
        title="Justificación",
        description="Razón auditable que explica por qué el override manual es necesario.",
        json_schema_extra={
            "ui_widget": "text_area",
            "ui_group": "Overrides",
            "ui_order": 4,
            "ui_help": (
                "Explicación obligatoria de por qué se fuerza este puntaje manualmente; "
                "queda registrada para auditoría y no puede quedar vacía."
            ),
        },
    )

    @model_validator(mode="after")
    def _check_override_valido(self) -> Self:
        """Valida que el override sea auditable y numéricamente finito."""
        if not self.reason.strip():
            raise ConfigError("point_overrides.reason no puede estar vacío.")
        if isinstance(self.points, float) and not math.isfinite(self.points):
            raise ConfigError("point_overrides.points debe ser un número finito.")
        return self


class ScorecardConfig(NikodymBaseConfig):
    """Sección ``scorecard`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-09 §5)."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección scorecard",
        description="== @register('standard', domain='scorecard') (D-SCR-7).",
        json_schema_extra={
            "ui_widget": "hidden",
            "ui_group": "General",
            "ui_order": 0,
            "ui_help": "Identificador interno del tipo de sección; no requiere edición.",
        },
    )
    pdo: float = Field(
        default=20.0,
        gt=0.0,
        title="PDO",
        description="Puntos necesarios para duplicar los odds definidos por la dirección.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Escala",
            "ui_order": 1,
            "ui_help": (
                "Cuántos puntos de score se necesitan para duplicar el ratio de buenos "
                "sobre malos (odds). Un PDO menor hace el score más sensible: la misma "
                "diferencia de riesgo se traduce en más puntos de separación."
            ),
        },
    )
    target_score: float = Field(
        default=600.0,
        title="Score objetivo",
        description="Score asignado a una observación con los odds objetivo configurados.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Escala",
            "ui_order": 2,
            "ui_help": (
                "Puntaje que recibe una observación cuyos odds de buenos/malos son "
                "exactamente los odds objetivo. Es el punto de anclaje de toda la escala."
            ),
        },
    )
    target_odds: float = Field(
        default=50.0,
        gt=0.0,
        title="Odds objetivo buenos/malos",
        description="Odds de referencia asociados al score objetivo según la dirección.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Escala",
            "ui_order": 3,
            "ui_help": (
                "Odds buenos/malos (ej. 50 significa 50 buenos por cada malo) usados como "
                "referencia para anclar la escala junto con el score objetivo."
            ),
        },
    )
    score_direction: ScoreDirection = Field(
        default="higher_is_lower_risk",
        title="Dirección del score",
        description="Define si un score mayor representa menor riesgo o mayor riesgo.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Escala",
            "ui_order": 4,
            "ui_help": (
                "Define si un score más alto significa menor riesgo (convención habitual) "
                "o mayor riesgo. Cambiarlo invierte el sentido de todos los puntajes."
            ),
        },
    )
    intercept_allocation: InterceptAllocation = Field(
        default="uniform",
        title="Distribución del intercepto",
        description="Distribuye el intercepto de forma uniforme entre variables finales.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Escala",
            "ui_order": 5,
            "ui_help": (
                "Cómo se reparte el intercepto del modelo entre las variables finales al "
                "calcular los puntos. Hoy solo existe reparto uniforme (a partes iguales)."
            ),
        },
    )
    rounding_method: RoundingMethod = Field(
        default="nearest_integer",
        title="Redondeo de puntos",
        description="Método para publicar puntos por atributo a partir de puntos crudos.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Publicación",
            "ui_order": 1,
            "ui_help": (
                "Cómo se redondean los puntos calculados por fórmula antes de publicarlos: "
                "sin redondeo, al entero más cercano, hacia abajo o hacia arriba. Afecta el "
                "puntaje final, no solo su presentación."
            ),
        },
    )
    output_suffix: str = Field(
        default="__points",
        title="Sufijo columnas de puntos",
        description="Sufijo usado para crear una columna de puntos por variable final.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Salida",
            "ui_order": 1,
            "ui_help": (
                "Texto que se agrega al nombre de cada variable para nombrar su columna de "
                "puntos (variable + este sufijo). No puede quedar vacío."
            ),
        },
    )
    score_column: str = Field(
        default="score",
        title="Columna score total",
        description="Nombre de la columna que contendrá el score total por registro.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Salida",
            "ui_order": 2,
            "ui_help": (
                "Nombre de la columna con el puntaje total por registro (suma de los "
                "puntos de todas las variables). No puede coincidir en terminación con el "
                "sufijo de puntos ni quedar vacío."
            ),
        },
    )
    min_score: float | None = Field(
        default=None,
        title="Score mínimo permitido",
        description="Límite inferior opcional para diagnóstico o clipping del score total.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Rango",
            "ui_order": 1,
            "ui_help": (
                "Puntaje mínimo de referencia para detectar scores fuera de rango. Si "
                "además se activa recortar, los scores por debajo se ajustan a este valor."
            ),
        },
    )
    max_score: float | None = Field(
        default=None,
        title="Score máximo permitido",
        description="Límite superior opcional para diagnóstico o clipping del score total.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Rango",
            "ui_order": 2,
            "ui_help": (
                "Puntaje máximo de referencia para detectar scores fuera de rango. Si "
                "además se activa recortar, los scores por encima se ajustan a este valor."
            ),
        },
    )
    clip: bool = Field(
        default=False,
        title="Recortar scores fuera de rango",
        description="Si True, recorta el score total a los límites configurados y lo audita.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Rango",
            "ui_order": 3,
            "ui_help": (
                "Si se activa, los scores fuera de los límites mínimo/máximo se recortan a "
                "esos límites y la operación queda auditada. Requiere haber definido al "
                "menos un límite."
            ),
        },
    )
    point_overrides: tuple[PointOverrideConfig, ...] = Field(
        default_factory=tuple,
        title="Overrides manuales de puntos",
        description="Overrides manuales auditables por pareja variable/bin; vacío por defecto.",
        json_schema_extra={
            "ui_widget": "table",
            "ui_group": "Overrides",
            "ui_order": 1,
            "ui_help": (
                "Lista de overrides manuales de puntaje por variable/bin, cada uno con su "
                "justificación auditada. Vacía por defecto: el scorecard se calcula "
                "íntegramente por fórmula."
            ),
        },
    )

    @field_validator("pdo", "target_odds", mode="before")
    @classmethod
    def _check_positivo(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` para los positivos estrictos del SDD-09 §5."""
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            observado = float(valor)
            if not math.isfinite(observado) or observado <= 0.0:
                raise ConfigError("pdo y target_odds deben ser números finitos mayores que 0.")
        return valor

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida invariantes de nombres, rango y overrides definidos por SDD-09 §5."""
        _require_finite("target_score", self.target_score)
        if self.min_score is not None:
            _require_finite("min_score", self.min_score)
        if self.max_score is not None:
            _require_finite("max_score", self.max_score)
        if not self.output_suffix.strip():
            raise ConfigError("output_suffix no puede estar vacío.")
        if not self.score_column.strip():
            raise ConfigError("score_column no puede estar vacío.")
        if self.score_column.endswith(self.output_suffix):
            raise ConfigError("score_column no puede terminar con output_suffix.")
        if (
            self.min_score is not None
            and self.max_score is not None
            and self.min_score >= self.max_score
        ):
            raise ConfigError("min_score debe ser menor que max_score.")
        if self.clip and self.min_score is None and self.max_score is None:
            raise ConfigError("clip=True exige configurar min_score o max_score.")

        vistos: set[tuple[str, str]] = set()
        for override in self.point_overrides:
            clave = (override.feature, override.bin_label)
            if clave in vistos:
                raise ConfigError(
                    "point_overrides no puede repetir la misma pareja "
                    f"(feature, bin_label): {clave!r}."
                )
            vistos.add(clave)
        return self


def _require_finite(nombre: str, valor: float) -> None:
    """Valida finitud para campos float que participan del ``config_hash``."""
    if not math.isfinite(valor):
        raise ConfigError(f"{nombre} debe ser un número finito.")
