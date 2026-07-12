"""Config declarativo de la capa ``validation`` (SDD-22 §5).

:class:`ValidationConfig` es la sección ``validation`` de
:class:`~nikodym.core.config.NikodymConfig`: la **validación formal** de un modelo del repo, que
consolida la discriminación (reúso de SDD-11), la estabilidad (reúso de SDD-11) y **añade** la
calibración (Hosmer-Lemeshow, binomial/Jeffreys por grado, Brier, semáforo) y el backtesting
realizado-vs-estimado (t-test LGD/EAD, binomial/Jeffreys PD). Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config.

La sección es **computacional, no infraestructura** (``validation`` ∉ ``INFRA_SECTIONS``): cambiar
las familias activas, el nº de deciles Hosmer-Lemeshow, el nivel de significancia, las bandas del
semáforo o el test de PD/LGD/EAD **cambia el ``config_hash`` global**. Al cablear B22.1 se mueve
``GOLDEN_DEFAULT_CONFIG_HASH`` (mismo precedente que ``provisioning_ifrs9``/``provisioning``).

Frontera B22.1: aquí solo viven el schema y sus validaciones determinables sin datos. La *presencia*
de artefactos/columnas aguas arriba es un contrato de runtime que valida el evaluador/step en
bloques posteriores (§6/§8), de modo que ``ValidationConfig()`` siga construyendo sin argumentos.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.validation.exceptions import ValidationConfigError

ValidationFamily = Literal["discrimination", "calibration", "stability", "backtesting"]
DiscriminationPartition = Literal["desarrollo", "holdout", "oot"]
HlGrouping = Literal["deciles", "fixed_bands"]
PdTest = Literal["binomial", "jeffreys"]
BacktestParameter = Literal["pd", "lgd", "ead"]

__all__ = [
    "BacktestParameter",
    "BacktestingValidationConfig",
    "CalibrationValidationConfig",
    "DiscriminationPartition",
    "DiscriminationValidationConfig",
    "HlGrouping",
    "PdTest",
    "StabilityValidationConfig",
    "ValidationConfig",
    "ValidationFamily",
]


def _require_non_empty(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de columnas declarativos no queden vacíos."""
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise ValidationConfigError(f"Las columnas de {context} no pueden estar vacías: {empty}.")


def _require_no_collision(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de columnas declarativos no colisionen entre sí."""
    normalizadas: dict[str, str] = {}
    duplicadas: list[tuple[str, str, str]] = []
    for nombre, columna in values.items():
        clave = columna.strip()
        previo = normalizadas.get(clave)
        if previo is not None:
            duplicadas.append((previo, nombre, clave))
        normalizadas[clave] = nombre
    if duplicadas:
        raise ValidationConfigError(
            f"Las columnas de {context} no pueden colisionar: {duplicadas}."
        )


class DiscriminationValidationConfig(NikodymBaseConfig):
    """Discriminación: reúso/consumo de AUC/Gini/KS de SDD-11 (no recálculo)."""

    consume_performance: bool = Field(
        default=True,
        title="Consumir discriminant_metrics de SDD-11",
        description=(
            "True consume ('performance','discriminant_metrics'); False fuerza el fallback por "
            "reúso de PerformanceEvaluator (nunca reimplementa AUC/Gini/KS)."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Discriminación", "ui_order": 1},
    )
    partitions: tuple[DiscriminationPartition, ...] = Field(
        default=("desarrollo", "holdout", "oot"),
        title="Particiones a validar",
        description="Particiones sobre las que se reporta la discriminación consumida/reúsada.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Discriminación", "ui_order": 2},
    )


class CalibrationValidationConfig(NikodymBaseConfig):
    """Calibración: Hosmer-Lemeshow, binomial/Jeffreys por grado, Brier y semáforo."""

    hosmer_lemeshow: bool = Field(
        default=True,
        title="Ejecutar Hosmer-Lemeshow",
        description="Activa el estadístico Hosmer-Lemeshow por grupos de PD (chi2 con G-2 gl).",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Calibración", "ui_order": 1},
    )
    hl_n_groups: int = Field(
        default=10,
        ge=5,
        le=20,
        title="Nº de grupos HL (deciles)",
        description="Nº de grupos G del Hosmer-Lemeshow; convención estándar G=10 -> G-2=8 gl.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Calibración", "ui_order": 2},
    )
    hl_grouping: HlGrouping = Field(
        default="deciles",
        title="Criterio de agrupación HL",
        description="deciles (default estándar); fixed_bands reservado (exige bandas declaradas).",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Calibración", "ui_order": 3},
    )
    brier: bool = Field(
        default=True,
        title="Calcular Brier score",
        description="Activa el Brier score (1/N)*suma((p-y)^2) por partición.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Calibración", "ui_order": 4},
    )
    binomial_by_grade: bool = Field(
        default=True,
        title="Test binomial/Jeffreys por grado",
        description="Activa el contraste binomial/Jeffreys de PD por grado de rating.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Calibración", "ui_order": 5},
    )
    grade_col: str = Field(
        default="grade",
        title="Columna de grado de rating",
        description="Columna que identifica el grado de rating para el test binomial por grado.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    pd_test: PdTest = Field(
        default="jeffreys",
        title="Test de PD por grado",
        description="jeffreys (ECB feb 2019, robusto con D=0) o binomial (BCBS WP14).",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Calibración", "ui_order": 6},
    )
    alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=0.5,
        title="Nivel de significancia",
        description="Nivel de significancia estándar de los tests de calibración; configurable.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Calibración", "ui_order": 7},
    )
    traffic_light_green_alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=1.0,
        title="Corte verde/ámbar (p-valor)",
        description=(
            "Corte del semáforo verde/ámbar sobre el p-valor del test por grado (default "
            "institucional; FALTA-DATO-VAL-2 para el anclaje regulatorio exacto)."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Semáforo", "ui_order": 1},
    )
    traffic_light_red_alpha: float = Field(
        default=0.01,
        gt=0.0,
        lt=1.0,
        title="Corte ámbar/rojo (p-valor)",
        description=(
            "Corte del semáforo ámbar/rojo sobre el p-valor del test por grado; debe ser más "
            "estricto que el corte verde (rojo < verde)."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Semáforo", "ui_order": 2},
    )
    target_column: str = Field(
        default="target",
        title="Columna target binario",
        description="Columna con el resultado binario (0/1) para la calibración.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    pd_column: str = Field(
        default="pd_calibrated",
        title="Columna PD calibrada",
        description="Columna con la PD calibrada consumida de SDD-10 para HL/Brier/binomial.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )
    partition_column: str = Field(
        default="partition",
        title="Columna partición",
        description="Columna que identifica Desarrollo, Holdout y OOT.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 4},
    )
    min_rows_per_group: int = Field(
        default=30,
        ge=1,
        title="Mínimo técnico por grupo HL/grado",
        description="Grupos HL/grados bajo este mínimo se auditan como not_evaluable, no NaN.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Calibración", "ui_order": 8},
    )

    @model_validator(mode="after")
    def _check_calibration(self) -> Self:
        """Valida columnas, semáforo y la agrupación HL de SDD-22 §5."""
        columns = {
            "grade_col": self.grade_col,
            "pd_column": self.pd_column,
            "target_column": self.target_column,
            "partition_column": self.partition_column,
        }
        _require_non_empty(columns, context="calibration")
        _require_no_collision(columns, context="calibration")
        if self.traffic_light_red_alpha >= self.traffic_light_green_alpha:
            raise ValidationConfigError(
                "traffic_light_red_alpha debe ser estrictamente menor que "
                "traffic_light_green_alpha (rojo más estricto que ámbar)."
            )
        if self.hl_grouping == "fixed_bands":
            raise ValidationConfigError(
                "hl_grouping='fixed_bands' aún no está soportado: exige bandas declaradas "
                "(reservado; use el default 'deciles')."
            )
        return self


class StabilityValidationConfig(NikodymBaseConfig):
    """Estabilidad: reúso/consumo del PSI de SDD-11 (no recálculo)."""

    consume_stability: bool = Field(
        default=True,
        title="Consumir stability_metrics de SDD-11",
        description=(
            "True consume ('stability','stability_metrics'); False fuerza el fallback por reúso "
            "de StabilityEvaluator (nunca reimplementa PSI)."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Estabilidad", "ui_order": 1},
    )
    psi_stable_threshold: float = Field(
        default=0.10,
        ge=0.0,
        title="PSI estable hasta",
        description="Umbral bajo el cual el PSI consumido se considera estable.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Estabilidad", "ui_order": 2},
    )
    psi_review_threshold: float = Field(
        default=0.25,
        ge=0.0,
        title="PSI vigilar hasta",
        description="Umbral sobre el cual el PSI consumido gatilla revisión/redesarrollo.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Estabilidad", "ui_order": 3},
    )

    @model_validator(mode="after")
    def _check_stability(self) -> Self:
        """Valida el orden de las bandas PSI de SDD-22 §5."""
        if self.psi_stable_threshold >= self.psi_review_threshold:
            raise ValidationConfigError(
                "psi_stable_threshold debe ser estrictamente menor que psi_review_threshold."
            )
        return self


class BacktestingValidationConfig(NikodymBaseConfig):
    """Backtesting realizado-vs-estimado IFRS 9 (t-test LGD/EAD, binomial/Jeffreys PD)."""

    enabled: bool = Field(
        default=False,
        title="Ejecutar backtesting IFRS 9",
        description=(
            "Opt-in: exige artefactos F4 (provisioning_ifrs9) + columnas de resultado realizado "
            "que no todo modelo del repo tiene."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Backtesting", "ui_order": 1},
    )
    parameters: tuple[BacktestParameter, ...] = Field(
        default=("pd", "lgd", "ead"),
        title="Parámetros a backtestear",
        description="Parámetros IFRS 9 a contrastar realizado-vs-estimado.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Backtesting", "ui_order": 2},
    )
    segment_col: str = Field(
        default="portfolio",
        title="Segmento de agregación",
        description="Columna de segmento/cartera para agregar el backtesting.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=0.5,
        title="Nivel de significancia",
        description="Nivel de significancia de los contrastes de backtesting; configurable.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Backtesting", "ui_order": 3},
    )
    one_sided: bool = Field(
        default=True,
        title="Contraste unilateral (subestimación)",
        description="El interés supervisor es la subestimación del parámetro (ECB); configurable.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Backtesting", "ui_order": 4},
    )
    realised_pd_col: str = Field(
        default="realised_default",
        title="Default realizado (0/1)",
        description="Columna con el default efectivo realizado del período de desempeño.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    realised_lgd_col: str = Field(
        default="realised_lgd",
        title="LGD realizada",
        description="Columna con la LGD realizada del período de desempeño.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )
    realised_ead_col: str = Field(
        default="realised_ead",
        title="EAD realizada a default",
        description="Columna con la EAD realizada a default del período de desempeño.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 4},
    )
    pd_test: PdTest = Field(
        default="jeffreys",
        title="Test de PD",
        description="jeffreys (ECB feb 2019) o binomial (BCBS WP14) para el backtesting de PD.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Backtesting", "ui_order": 5},
    )

    @model_validator(mode="after")
    def _check_backtesting(self) -> Self:
        """Valida que las columnas de resultado realizado no queden vacías ni colisionen."""
        columns = {
            "segment_col": self.segment_col,
            "realised_pd_col": self.realised_pd_col,
            "realised_lgd_col": self.realised_lgd_col,
            "realised_ead_col": self.realised_ead_col,
        }
        _require_non_empty(columns, context="backtesting")
        _require_no_collision(columns, context="backtesting")
        return self


class ValidationConfig(NikodymBaseConfig):
    """Sección ``validation`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-22 §5)."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema validation",
        description="Versión local del schema de validación para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección validation",
        description="== @register('standard', domain='validation') (SDD-22 §4).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    families: tuple[ValidationFamily, ...] = Field(
        default=("discrimination", "calibration", "stability"),
        title="Familias de validación activas",
        description=(
            "Familias que corren; backtesting es opt-in (exige artefactos F4 + realizados que no "
            "todo modelo del repo tiene, DoD F6)."
        ),
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "General", "ui_order": 2},
    )
    discrimination: DiscriminationValidationConfig = Field(
        default_factory=DiscriminationValidationConfig,
        title="Discriminación",
        description="Reúso/consumo de AUC/Gini/KS de SDD-11 (no recálculo).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Discriminación", "ui_order": 1},
    )
    calibration: CalibrationValidationConfig = Field(
        default_factory=CalibrationValidationConfig,
        title="Calibración",
        description="Hosmer-Lemeshow, binomial/Jeffreys por grado, Brier y semáforo.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Calibración", "ui_order": 1},
    )
    stability: StabilityValidationConfig = Field(
        default_factory=StabilityValidationConfig,
        title="Estabilidad",
        description="Reúso/consumo del PSI de SDD-11 (no recálculo).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Estabilidad", "ui_order": 1},
    )
    backtesting: BacktestingValidationConfig = Field(
        default_factory=BacktestingValidationConfig,
        title="Backtesting IFRS 9",
        description="Backtesting realizado-vs-estimado IFRS 9 (t-test LGD/EAD, binomial PD).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Backtesting", "ui_order": 1},
    )
    fail_on_falta_dato: bool = Field(
        default=True,
        title="Fallar ante brechas críticas de dato",
        description=(
            "Si es True, una brecha crítica (p. ej. backtesting activo sin insumos) falla en vez "
            "de marcar FALTA-DATO."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "General", "ui_order": 3},
    )

    @model_validator(mode="after")
    def _check_validation(self) -> Self:
        """Valida la coherencia entre ``families`` y el backtesting (SDD-22 §5)."""
        if (
            "backtesting" in self.families
            and not self.backtesting.enabled
            and self.fail_on_falta_dato
        ):
            raise ValidationConfigError(
                "families incluye 'backtesting' pero backtesting.enabled=False: el backtesting "
                "IFRS 9 exige enabled=True y las columnas realizadas declaradas "
                "(o fail_on_falta_dato=False para diferirlo a FALTA-DATO)."
            )
        return self
