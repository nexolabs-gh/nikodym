"""DTOs puros de resultados de la validación avanzada (SDD-22 §4/§6).

Este módulo publica los contenedores Pydantic *frozen* que la capa ``validation`` (calibración,
backtesting, semáforo) expone a ``report``/``governance``. **No** calcula Hosmer-Lemeshow, Brier,
binomial/Jeffreys ni el t-test ECB; solo fija contratos de I/O tidy, normalización numérica y copias
defensivas. Tampoco importa ``pandas``, ``pandera``, ``scipy`` ni ``sklearn`` en runtime para
preservar el import liviano de ``nikodym.validation`` (pandas vive solo bajo ``TYPE_CHECKING``).

Cumplimiento CT-2: la puerta de extensión es ``metric_sections`` tidy + DTOs *frozen* + copias
defensivas bidireccionales; **no** hay método económico ``term_structure()`` (la validación no
produce estructura temporal, alimenta a ``report``/``governance`` por ``card`` + ``metric_sections``
sin curva económica).

Discrepancia SDD resuelta: §2 enumeraba un ``BrierRecord``, pero §4 (API) y el nitpick (a) lo
resuelven como fila ``test="brier"`` de :class:`CalibrationTestRecord` (``p_value=None``,
``n_groups=None``, ``decision="not_evaluable"``: el Brier no es un test pass/fail). Se sigue §4: no
existe ``BrierRecord``.

Columnas canónicas §6: para ``calibration`` y ``backtesting`` la §6 fija tablas explícitas y se
respetan al pie de la letra. Para ``discrimination`` el frame es la proyección tidy exacta del
:class:`DiscriminationRecord` (§4, autoritativo: ``partition``, ``n_total``, ``n_bad``, ``auc``,
``gini``, ``ks``, ``source``, ``status``), no el espejo ancho de SDD-11, para conservar la
correspondencia frame-record. Para ``stability`` (sin record propio en §4) el frame refleja
``stability_metrics`` de SDD-11 §6 más las columnas de procedencia (``source``, ``status``,
``decision``) que añade §6.

Los floats publicados normalizan ``-0.0`` como ``0.0`` (escalares y columnas ``float64``/``Float64``
/``float32``, preservando ``NaN``/``NA``); las métricas jamás publican ``NaN``/``inf`` (se usa
``None`` o el estado ``not_evaluable``). Finitud antes de comparar.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nikodym.validation.config import BacktestParameter, PdTest, ValidationFamily

if TYPE_CHECKING:
    import pandas as pd

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any

DiscriminationSource: TypeAlias = Literal["performance_artifact", "recomputed"]
DiscriminationStatus: TypeAlias = Literal["ok", "not_evaluable"]
CalibrationTest: TypeAlias = Literal["hosmer_lemeshow", "brier"]
CalibrationDecision: TypeAlias = Literal["pass", "fail", "not_evaluable"]
TrafficLight: TypeAlias = Literal["green", "amber", "red"]
BacktestTest: TypeAlias = Literal["t_test", "binomial", "jeffreys"]
BacktestDecision: TypeAlias = Literal["pass", "fail", "not_evaluable"]
OverallStatus: TypeAlias = Literal["pass", "warn", "fail"]

# Familias de validación válidas para ``card.families_run`` (SDD-22 §4), derivadas del Literal.
_VALID_FAMILIES: frozenset[str] = frozenset(get_args(ValidationFamily))

# Columnas canónicas de los cuatro artefactos tidy (SDD-22 §6).
_DISCRIMINATION_COLUMNS: tuple[str, ...] = (
    "partition",
    "n_total",
    "n_bad",
    "auc",
    "gini",
    "ks",
    "source",
    "status",
)
_CALIBRATION_COLUMNS: tuple[str, ...] = (
    "partition",
    "test",
    "grade",
    "n",
    "observed_defaults",
    "expected_pd",
    "observed_dr",
    "statistic",
    "degrees_of_freedom",
    "p_value",
    "alpha",
    "decision",
    "traffic_light",
)
_STABILITY_COLUMNS: tuple[str, ...] = (
    "metric",
    "comparison",
    "feature",
    "value",
    "stable_threshold",
    "review_threshold",
    "band",
    "action",
    "source",
    "status",
    "decision",
)
_BACKTESTING_COLUMNS: tuple[str, ...] = (
    "parameter",
    "segment",
    "n",
    "predicted_mean",
    "realised_mean",
    "test",
    "statistic",
    "p_value",
    "alpha",
    "one_sided",
    "decision",
)

__all__ = [
    "BacktestParameter",
    "BacktestRecord",
    "CalibrationTestRecord",
    "DiscriminationRecord",
    "GradeBinomialRecord",
    "PdTest",
    "ValidationCardSection",
    "ValidationFamily",
    "ValidationResult",
]


class DiscriminationRecord(BaseModel):
    """Fila publicada de ``discrimination``: AUC/Gini/KS consumido o reúsado (SDD-22 §4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    n_total: int = Field(ge=0)
    n_bad: int = Field(ge=0)
    auc: float | None
    gini: float | None
    ks: float | None
    source: DiscriminationSource
    status: DiscriminationStatus

    @field_validator("partition")
    @classmethod
    def _valida_partition(cls, value: str) -> str:
        """Valida que la partición no esté vacía."""
        if not value.strip():
            raise ValueError("partition no puede estar vacío.")
        return value

    @field_validator("auc", "gini", "ks", mode="before")
    @classmethod
    def _normaliza_metricas(cls, value: Any) -> float | None:
        """Descarta no-finitos y publica ``-0.0`` como ``0.0`` en AUC/Gini/KS opcionales."""
        return _normalize_optional_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida población y presencia de métricas según el estado de la partición."""
        if self.n_bad > self.n_total:
            raise ValueError("n_bad no puede exceder n_total.")

        metrics = (self.auc, self.gini, self.ks)
        if self.status == "not_evaluable":
            if metrics != (None, None, None):
                raise ValueError("Una discriminación not_evaluable no debe publicar AUC/Gini/KS.")
            return self
        if None in metrics:
            raise ValueError("Una discriminación evaluable (ok) exige AUC, Gini y KS.")
        return self


class CalibrationTestRecord(BaseModel):
    """Fila de ``calibration`` para Hosmer-Lemeshow o Brier (SDD-22 §4).

    HL lleva ``n_groups``/``degrees_of_freedom`` (``G-2``), ``p_value`` y ``decision`` pass/fail;
    Brier es un puntaje, no un test: ``n_groups``/``degrees_of_freedom``/``p_value``/``alpha`` son
    ``None`` y ``decision`` es ``not_evaluable``. El binomial/Jeffreys por grado vive en
    :class:`GradeBinomialRecord`, no aquí.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    test: CalibrationTest
    n_groups: int | None
    degrees_of_freedom: int | None
    statistic: float
    p_value: float | None
    alpha: float | None
    decision: CalibrationDecision

    @field_validator("partition")
    @classmethod
    def _valida_partition(cls, value: str) -> str:
        """Valida que la partición no esté vacía."""
        if not value.strip():
            raise ValueError("partition no puede estar vacío.")
        return value

    @field_validator("statistic", mode="before")
    @classmethod
    def _normaliza_statistic(cls, value: Any) -> float:
        """Exige estadístico float finito y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @field_validator("p_value", "alpha", mode="before")
    @classmethod
    def _normaliza_opcionales(cls, value: Any) -> float | None:
        """Descarta no-finitos y publica ``-0.0`` como ``0.0`` en ``p_value``/``alpha``."""
        return _normalize_optional_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida rangos y la coherencia HL vs Brier del registro de calibración."""
        if self.p_value is not None and not 0.0 <= self.p_value <= 1.0:
            raise ValueError("p_value debe estar en [0, 1].")
        if self.alpha is not None and not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha debe estar en (0, 1).")

        if self.test == "brier":
            if (self.n_groups, self.degrees_of_freedom, self.p_value, self.alpha) != (
                None,
                None,
                None,
                None,
            ):
                raise ValueError("El Brier score no publica n_groups, gl, p_value ni alpha.")
            if self.decision != "not_evaluable":
                raise ValueError("El Brier score no es pass/fail: decision debe ser not_evaluable.")
            if not 0.0 <= self.statistic <= 1.0:
                raise ValueError("El Brier score debe estar en [0, 1].")
            return self

        if self.n_groups is None or self.degrees_of_freedom is None:
            raise ValueError("Hosmer-Lemeshow exige n_groups y degrees_of_freedom.")
        if self.degrees_of_freedom != self.n_groups - 2 or self.degrees_of_freedom < 1:
            raise ValueError("degrees_of_freedom debe ser G-2 (>=1) en Hosmer-Lemeshow.")
        if self.statistic < 0.0:
            raise ValueError("El estadístico Hosmer-Lemeshow no puede ser negativo.")
        if self.decision == "not_evaluable":
            if self.p_value is not None:
                raise ValueError("Un Hosmer-Lemeshow not_evaluable no publica p_value.")
            return self
        if self.p_value is None or self.alpha is None:
            raise ValueError("Un Hosmer-Lemeshow evaluable exige p_value y alpha.")
        return self


class GradeBinomialRecord(BaseModel):
    """Fila de ``calibration`` para el test binomial/Jeffreys de PD por grado (SDD-22 §4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grade: str
    n: int = Field(ge=0)
    expected_pd: float
    observed_defaults: int = Field(ge=0)
    observed_dr: float
    test: PdTest
    p_value: float
    z_stat: float | None
    alpha: float
    traffic_light: TrafficLight

    @field_validator("grade")
    @classmethod
    def _valida_grade(cls, value: str) -> str:
        """Valida que el grado de rating no esté vacío."""
        if not value.strip():
            raise ValueError("grade no puede estar vacío.")
        return value

    @field_validator("expected_pd", "observed_dr", "p_value", "alpha", mode="before")
    @classmethod
    def _normaliza_requeridos(cls, value: Any) -> float:
        """Exige floats finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @field_validator("z_stat", mode="before")
    @classmethod
    def _normaliza_z(cls, value: Any) -> float | None:
        """Descarta no-finitos y publica ``-0.0`` como ``0.0`` en el ``z`` asintótico opcional."""
        return _normalize_optional_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida conteos y rangos de probabilidad/p-valor del grado."""
        if self.observed_defaults > self.n:
            raise ValueError("observed_defaults no puede exceder n.")
        if not 0.0 <= self.expected_pd <= 1.0:
            raise ValueError("expected_pd debe estar en [0, 1].")
        if not 0.0 <= self.observed_dr <= 1.0:
            raise ValueError("observed_dr debe estar en [0, 1].")
        if not 0.0 <= self.p_value <= 1.0:
            raise ValueError("p_value debe estar en [0, 1].")
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha debe estar en (0, 1).")
        return self


class BacktestRecord(BaseModel):
    """Fila de ``backtesting``: un contraste realizado-vs-estimado por parámetro y segmento (§4).

    LGD/EAD usan el t-test ECB; PD usa binomial/Jeffreys (D-VAL-6). ``not_evaluable`` conserva el
    estadístico y el p-valor reportados (SDD-22 §8: se reporta el estadístico aun con ``N`` chico).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    parameter: BacktestParameter
    segment: str
    n: int = Field(ge=0)
    predicted_mean: float
    realised_mean: float
    test: BacktestTest
    statistic: float
    p_value: float
    alpha: float
    one_sided: bool
    decision: BacktestDecision

    @field_validator("segment")
    @classmethod
    def _valida_segment(cls, value: str) -> str:
        """Valida que el segmento no esté vacío."""
        if not value.strip():
            raise ValueError("segment no puede estar vacío.")
        return value

    @field_validator(
        "predicted_mean",
        "realised_mean",
        "statistic",
        "p_value",
        "alpha",
        mode="before",
    )
    @classmethod
    def _normaliza_requeridos(cls, value: Any) -> float:
        """Exige floats finitos y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida rangos del p-valor y alfa, y que el test corresponda al parámetro (§3.4/§7)."""
        if not 0.0 <= self.p_value <= 1.0:
            raise ValueError("p_value debe estar en [0, 1].")
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha debe estar en (0, 1).")
        if self.parameter == "pd":
            if self.test not in ("binomial", "jeffreys"):
                raise ValueError("El backtesting de PD usa binomial/jeffreys, no el t-test.")
        elif self.test != "t_test":
            raise ValueError("El backtesting de LGD/EAD usa el t-test.")
        return self


class ValidationCardSection(BaseModel):
    """Resumen determinista de la validación para model card, governance y reportes (§4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"dependency_versions", "metric_sections"}
    )

    model_ref: str
    families_run: tuple[str, ...]
    overall_status: OverallStatus
    n_tests: int = Field(ge=0)
    n_failed: int = Field(ge=0)
    dependency_versions: dict[str, str]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)

    @field_validator("model_ref")
    @classmethod
    def _valida_model_ref(cls, value: str) -> str:
        """Valida que la referencia al modelo validado no esté vacía."""
        if not value.strip():
            raise ValueError("model_ref no puede estar vacío.")
        return value

    @field_validator("families_run")
    @classmethod
    def _valida_families(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Valida que las familias corridas sean no vacías, únicas y válidas (SDD-22 §4)."""
        if not value:
            raise ValueError("families_run no puede estar vacío.")
        if len(set(value)) != len(value):
            raise ValueError("families_run no debe contener familias duplicadas.")
        invalid = set(value) - _VALID_FAMILIES
        if invalid:
            raise ValueError(f"families_run solo admite familias de validación: {sorted(invalid)}.")
        return value

    @field_validator("dependency_versions")
    @classmethod
    def _ordena_versiones(cls, values: dict[str, str]) -> dict[str, str]:
        """Ordena las versiones de dependencias para serialización determinista."""
        return {name: values[name] for name in sorted(values)}

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia profundamente la puerta CT-2 de métricas aditivas y normaliza sus floats."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(dict(value))
        return value

    @model_validator(mode="after")
    def _check_conteos(self) -> Self:
        """Valida que los tests fallados no excedan el total de tests."""
        if self.n_failed > self.n_tests:
            raise ValueError("n_failed no puede exceder n_tests.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias de estructuras mutables aunque el DTO sea frozen."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            if name == "metric_sections":
                return copy.deepcopy(value)
            return dict(value)
        return value


class ValidationResult(BaseModel):
    """Contenedor agregado de los artefactos publicados por la capa ``validation`` (§4/§6)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"discrimination", "calibration", "stability", "backtesting"}
    )

    discrimination: DataFrameLike
    calibration: DataFrameLike
    stability: DataFrameLike
    backtesting: DataFrameLike
    discrimination_records: tuple[DiscriminationRecord, ...]
    calibration_records: tuple[CalibrationTestRecord, ...]
    grade_records: tuple[GradeBinomialRecord, ...]
    backtest_records: tuple[BacktestRecord, ...]
    card: ValidationCardSection

    @field_validator("discrimination", mode="before")
    @classmethod
    def _copia_discrimination(cls, value: Any) -> Any:
        """Copia el frame de discriminación y valida sus columnas canónicas SDD-22 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_DISCRIMINATION_COLUMNS,
            field_name="discrimination",
        )

    @field_validator("calibration", mode="before")
    @classmethod
    def _copia_calibration(cls, value: Any) -> Any:
        """Copia el frame de calibración y valida sus columnas canónicas SDD-22 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_CALIBRATION_COLUMNS,
            field_name="calibration",
        )

    @field_validator("stability", mode="before")
    @classmethod
    def _copia_stability(cls, value: Any) -> Any:
        """Copia el frame de estabilidad consumido y valida sus columnas canónicas SDD-22 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_STABILITY_COLUMNS,
            field_name="stability",
        )

    @field_validator("backtesting", mode="before")
    @classmethod
    def _copia_backtesting(cls, value: Any) -> Any:
        """Copia el frame de backtesting y valida sus columnas canónicas SDD-22 §6."""
        return _copy_and_validate_dataframe(
            value,
            expected_columns=_BACKTESTING_COLUMNS,
            field_name="backtesting",
        )

    @model_validator(mode="after")
    def _check_consistencia_con_card(self) -> Self:
        """Valida el paralelismo frame↔records y que la card resuma cada familia con evidencia."""
        if len(self.discrimination) != len(self.discrimination_records):
            raise ValueError("discrimination debe tener una fila por discrimination_record.")
        if len(self.calibration) != len(self.calibration_records) + len(self.grade_records):
            raise ValueError("calibration debe tener una fila por test de calibración/grado.")
        if len(self.backtesting) != len(self.backtest_records):
            raise ValueError("backtesting debe tener una fila por backtest_record.")

        declared = set(self.card.families_run)
        if self.discrimination_records and "discrimination" not in declared:
            raise ValueError("discrimination_records exige 'discrimination' en card.families_run.")
        if (self.calibration_records or self.grade_records) and "calibration" not in declared:
            raise ValueError("los tests de calibración exigen 'calibration' en card.families_run.")
        if self.backtest_records and "backtesting" not in declared:
            raise ValueError("backtest_records exige 'backtesting' en card.families_run.")
        if len(self.stability) > 0 and "stability" not in declared:
            raise ValueError("stability exige 'stability' en card.families_run.")
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value


def _copy_and_validate_dataframe(
    value: Any,
    *,
    expected_columns: tuple[str, ...],
    field_name: str,
) -> Any:
    if not _is_dataframe_like(value):
        raise ValueError(f"{field_name} debe ser un pandas.DataFrame.")

    copied = _copy_dataframe(value)
    observed_columns = tuple(str(column) for column in copied.columns)
    if observed_columns != expected_columns:
        raise ValueError(
            f"{field_name} debe tener exactamente las columnas canónicas de SDD-22 §6."
        )
    return copied


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))


def _copy_dataframe(frame: Any) -> Any:
    copied = frame.copy(deep=True)
    for column in copied.columns:
        series = copied[column]
        if getattr(series.dtype, "kind", "") != "f":
            continue
        zero_mask = (series == 0.0).fillna(False)
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _normalize_metric_payload(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return _normalize_float(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_metric_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_metric_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_metric_payload(item) for item in value)
    return copy.deepcopy(value)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    candidate = float(value)
    if not math.isfinite(candidate):
        return None
    return _normalize_float(candidate)


def _normalize_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return _finite_number(value)


def _normalize_required_float(value: Any) -> float:
    finite = _finite_number(value)
    if finite is None:
        raise ValueError("Las métricas float deben ser números finitos.")
    return finite


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value
