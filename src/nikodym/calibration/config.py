"""Config declarativo de la capa ``calibration`` (SDD-10 §5).

:class:`CalibrationConfig` es la sección ``calibration`` de
:class:`~nikodym.core.config.NikodymConfig`: calibración determinista de la PD cruda del modelo
logístico contra una tasa central aprobada. Toda clase hereda de
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

CalibrationMethod = Literal["intercept_offset", "platt_scaling", "isotonic"]
AnchorKind = Literal["through_the_cycle", "point_in_time"]
AnchorSource = Literal[
    "business_input",
    "historical_default_rate",
    "development_observed",
    "external_regulatory",
]

__all__ = [
    "AnchorKind",
    "AnchorSource",
    "CalibrationConfig",
    "CalibrationMethod",
]

_SUPERVISED_METHODS: frozenset[str] = frozenset({"platt_scaling", "isotonic"})
_COLUMN_FIELDS: tuple[str, ...] = (
    "pd_raw_column",
    "linear_predictor_column",
    "pd_calibrated_column",
    "linear_predictor_calibrated_column",
    "partition_column",
    "target_column",
)


class CalibrationConfig(NikodymBaseConfig):
    """Sección ``calibration`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-10 §5)."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección calibration",
        description="== @register('standard', domain='calibration') (SDD-10 §4).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    method: CalibrationMethod = Field(
        default="intercept_offset",
        title="Método de calibración",
        description="Método usado para transformar PD cruda en PD calibrada.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Método", "ui_order": 1},
    )
    target_pd: float = Field(
        default=0.05,
        gt=0.0,
        lt=1.0,
        title="PD objetivo",
        description=(
            "Placeholder ilustrativo. Con anchor_source='development_observed' no se usa: "
            "la tasa central TTC se estima como promedio de largo plazo observado en Desarrollo. "
            "Sólo aplica con anchor_source en {'business_input', 'historical_default_rate', "
            "'external_regulatory'}."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Ancla", "ui_order": 1},
    )
    anchor_kind: AnchorKind = Field(
        default="through_the_cycle",
        title="Tipo de ancla",
        description="Define si el anclaje representa una visión TTC o PIT.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Ancla", "ui_order": 2},
    )
    anchor_source: AnchorSource = Field(
        default="development_observed",
        title="Fuente de la ancla",
        description=(
            "Origen auditable de la tasa central. Por default se deriva del target de Desarrollo "
            "como long-run average TTC."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Ancla", "ui_order": 3},
    )
    fit_partition: Literal["desarrollo"] = Field(
        default="desarrollo",
        title="Partición de ajuste",
        description="Partición fija usada para ajustar calibration; no se parametriza en v1.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Ajuste", "ui_order": 1},
    )
    target_tolerance: float = Field(
        default=1e-12,
        gt=0.0,
        title="Tolerancia de media PD",
        description="Tolerancia máxima entre la media PD calibrada y la PD objetivo.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Ajuste", "ui_order": 2},
    )
    max_abs_offset: float | None = Field(
        default=None,
        title="Máximo offset absoluto",
        description=(
            "Guard opcional del desplazamiento de reanclaje a tasa central. Con None se audita "
            "el offset extremo sin fallar; si se informa, debe ser finito y mayor que 0."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Ajuste", "ui_order": 3},
    )
    max_iter: int = Field(
        default=100,
        ge=1,
        title="Iteraciones máximas del solver",
        description="Máximo de iteraciones permitidas al resolver parámetros de calibración.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Ajuste", "ui_order": 4},
    )
    min_fit_rows: int = Field(
        default=30,
        ge=1,
        title="Mínimo de filas de Desarrollo",
        description="Guard técnico mínimo de filas en Desarrollo para aceptar el ajuste.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Ajuste", "ui_order": 5},
    )
    require_both_classes_for_supervised: bool = Field(
        default=True,
        title="Exigir ambas clases para Platt/isotónica",
        description="Si el método es supervisado, exige clases 0 y 1 en Desarrollo durante fit.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Ajuste", "ui_order": 6},
    )
    pd_raw_column: str = Field(
        default="pd_raw",
        title="Columna PD cruda",
        description="Columna de entrada con la probabilidad de default cruda del modelo.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    linear_predictor_column: str = Field(
        default="linear_predictor",
        title="Columna logit crudo",
        description="Columna de entrada con el predictor lineal crudo del modelo.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    pd_calibrated_column: str = Field(
        default="pd_calibrated",
        title="Columna PD calibrada",
        description="Columna de salida que contendrá la probabilidad de default calibrada.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )
    linear_predictor_calibrated_column: str = Field(
        default="linear_predictor_calibrated",
        title="Columna logit calibrado",
        description="Columna de salida que contendrá el predictor lineal calibrado.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 4},
    )
    partition_column: str = Field(
        default="partition",
        title="Columna partición",
        description="Columna estructural que identifica Desarrollo, Holdout, OOT y exclusiones.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 5},
    )
    target_column: str = Field(
        default="target",
        title="Columna target",
        description="Columna binaria 0/1 usada por métodos supervisados durante fit.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 6},
    )

    @field_validator("target_pd", mode="before")
    @classmethod
    def _check_target_pd(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` si ``target_pd`` no está estrictamente en ``(0, 1)``."""
        if isinstance(valor, bool):
            raise ConfigError("target_pd debe ser un número finito estrictamente entre 0 y 1.")
        if isinstance(valor, (int, float)):
            observado = float(valor)
            if not math.isfinite(observado) or observado <= 0.0 or observado >= 1.0:
                raise ConfigError("target_pd debe ser un número finito estrictamente entre 0 y 1.")
        return valor

    @field_validator("target_tolerance", mode="before")
    @classmethod
    def _check_target_tolerance(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` si ``target_tolerance`` no es positivo y finito."""
        if isinstance(valor, bool):
            raise ConfigError("target_tolerance debe ser un número finito mayor que 0.")
        if isinstance(valor, (int, float)):
            observado = float(valor)
            if not math.isfinite(observado) or observado <= 0.0:
                raise ConfigError("target_tolerance debe ser un número finito mayor que 0.")
        return valor

    @field_validator("max_abs_offset", mode="before")
    @classmethod
    def _check_max_abs_offset(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` si ``max_abs_offset`` no es ``None`` o positivo finito."""
        if valor is None:
            return None
        if isinstance(valor, bool):
            raise ConfigError("max_abs_offset debe ser None o un número finito mayor que 0.")
        if isinstance(valor, (int, float)):
            observado = float(valor)
            if not math.isfinite(observado) or observado <= 0.0:
                raise ConfigError("max_abs_offset debe ser None o un número finito mayor que 0.")
        return valor

    @field_validator("max_iter", "min_fit_rows", mode="before")
    @classmethod
    def _check_enteros_positivos(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` si los contadores enteros son menores que 1."""
        if isinstance(valor, bool):
            raise ConfigError("max_iter y min_fit_rows deben ser enteros mayores o iguales a 1.")
        if isinstance(valor, int) and valor < 1:
            raise ConfigError("max_iter y min_fit_rows deben ser enteros mayores o iguales a 1.")
        return valor

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida finitud, ancla y nombres de columnas definidos por SDD-10 §5/§8."""
        _require_finite("target_pd", self.target_pd)
        _require_finite("target_tolerance", self.target_tolerance)
        if self.max_abs_offset is not None:
            _require_positive_finite("max_abs_offset", self.max_abs_offset)

        if self.anchor_kind == "point_in_time" and self.anchor_source == "external_regulatory":
            raise ConfigError(
                "anchor_kind='point_in_time' no es compatible con "
                "anchor_source='external_regulatory' en v1."
            )

        columns = _column_values(self)
        vacias = [nombre for nombre, columna in columns.items() if not columna.strip()]
        if vacias:
            raise ConfigError(f"Las columnas de calibration no pueden estar vacías: {vacias}.")

        normalizadas: dict[str, str] = {}
        duplicadas: list[tuple[str, str, str]] = []
        for nombre, columna in columns.items():
            clave = columna.strip()
            previo = normalizadas.get(clave)
            if previo is not None:
                duplicadas.append((previo, nombre, clave))
            normalizadas[clave] = nombre
        if duplicadas:
            raise ConfigError(f"Las columnas de calibration no pueden colisionar: {duplicadas}.")

        if self.method in _SUPERVISED_METHODS and not self.require_both_classes_for_supervised:
            raise ConfigError(
                "platt_scaling e isotonic requieren require_both_classes_for_supervised=True en v1."
            )

        return self


def _column_values(cfg: CalibrationConfig) -> dict[str, str]:
    """Devuelve nombres de columnas configurados para validar colisiones."""
    return {nombre: getattr(cfg, nombre) for nombre in _COLUMN_FIELDS}


def _require_finite(nombre: str, valor: float) -> None:
    """Valida finitud para campos float que participan del ``config_hash``."""
    if not math.isfinite(valor):
        raise ConfigError(f"{nombre} debe ser un número finito.")


def _require_positive_finite(nombre: str, valor: float) -> None:
    """Valida positividad y finitud para guards numéricos opcionales."""
    if not math.isfinite(valor) or valor <= 0.0:
        raise ConfigError(f"{nombre} debe ser None o un número finito mayor que 0.")
