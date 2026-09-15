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
#: Por qué un Hosmer-Lemeshow quedó sin veredicto (D-VAL-17): la partición entera bajo el mínimo
#: de operaciones, el grupo de PD más chico bajo ese mismo mínimo, un grupo degenerado (vacío o
#: con ``n_g * p_g * (1 - p_g) = 0``) o un estadístico que desbordó con PD extremas. Cuatro valores
#: cerrados; el kernel fija los tres últimos y el evaluador el primero.
HlNotEvaluableReason: TypeAlias = Literal[
    "partition_below_min",
    "group_below_min",
    "degenerate_group",
    "non_finite_statistic",
]
TrafficLight: TypeAlias = Literal["green", "amber", "red"]
BacktestTest: TypeAlias = Literal["t_test", "binomial", "jeffreys"]
BacktestDecision: TypeAlias = Literal["pass", "fail", "not_evaluable"]
#: Estado técnico consolidado. ``not_evaluable`` (D-VAL-17, §8-9 de la enmienda) es «no hay
#: evidencia evaluable alguna»: ninguna decisión ``pass``/``fail`` en calibración, grado o
#: backtesting y ninguna fila de estabilidad con decisión; antes ese caso terminaba en ``pass``.
OverallStatus: TypeAlias = Literal["pass", "warn", "fail", "not_evaluable"]

#: Las decisiones que cuentan como evidencia: ``not_evaluable`` no es una prueba corrida sin
#: veredicto, es una prueba que no se pudo correr, y no entra a ``n_tests`` ni al estado.
_EVALUABLE_DECISIONS: frozenset[str] = frozenset({"pass", "fail"})
_EVALUABLE_STABILITY_DECISIONS: frozenset[str] = frozenset({"pass", "warn", "fail"})

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
    # D-VAL-15: los dos cortes con que se decidió el color de cada fila de grado, nulos en las filas
    # de Hosmer-Lemeshow y Brier. Van al final para que las trece anteriores no se muevan; el
    # informe no las pinta (son de auditoría: el hecho va en prosa) y el JSON, el CSV y la card sí.
    "green_alpha",
    "red_alpha",
    # D-VAL-17: por qué un Hosmer-Lemeshow quedó sin veredicto; nula en toda otra fila. Misma
    # condición que las dos anteriores: el informe no la pinta y el hecho va en prosa, con la
    # causa en palabras; el panel la traduce junto al «Sin veredicto» de la fila.
    "not_evaluable_reason",
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

#: Rótulo público del estado técnico: la **única** fuente de esas cuatro palabras (D-SC-9).
#:
#: El slug (``pass``/``warn``/``fail``/``not_evaluable``) es el dato y no se toca —viaja en la
#: card, en el JSON y en el anexo—; estas palabras son el copy que lee una persona. Hasta la capa 2
#: convivían dos vocabularios: la prosa del informe decía «Pass técnico / Requiere revisión / Falla
#: técnica» y la pantalla no decía nada, porque no había panel. La cuarta, «No evaluable» (D-VAL-17,
#: aprobada por Cami el 2026-09-14), es la misma palabra que las bandas del PSI y sale sólo cuando
#: no hay evidencia evaluable alguna: antes ese caso decía «Pasa». Consumidores:
#: :mod:`nikodym.report.prose`, el panel de Resultados (espejo en ``web/src/lib/results-format.ts``,
#: gateado en los dos sentidos por ``tests/unit/test_vocabulario_en_pantalla.py``) y la guía del
#: sitio.
#:
#: ⚠️ Va bajo el rótulo **«Estado técnico»** y no «Resultado»: es evidencia del motor, y el
#: veredicto sobre el modelo lo firma quien valida.
VALIDATION_STATUS_LABELS: dict[str, str] = {
    "pass": "Pasa",
    "warn": "Revisar",
    "fail": "Falla",
    "not_evaluable": "No evaluable",
}

#: Por qué un Hosmer-Lemeshow quedó sin veredicto, en palabras (D-VAL-17). El panel las pinta junto
#: al «Sin veredicto» de la fila y la prosa del informe las completa con los números de la
#: partición (operaciones, grupo más chico, mínimo). Espejo en el front, gateado en ambos sentidos.
HL_NOT_EVALUABLE_REASON_LABELS: dict[str, str] = {
    "partition_below_min": "la muestra quedó bajo el mínimo de operaciones",
    "group_below_min": "un grupo de PD quedó bajo el mínimo de operaciones",
    "degenerate_group": "un grupo de PD quedó sin variabilidad",
    "non_finite_statistic": "el estadístico no fue finito con PD extremas",
}

#: Rótulo público de cada familia de pruebas. En la pantalla titula su sección; en la prosa del
#: informe entra dentro de una frase, así que allí se minuscula la inicial en el punto de uso.
VALIDATION_FAMILY_LABELS: dict[str, str] = {
    "discrimination": "Discriminación",
    "calibration": "Calibración",
    "stability": "Estabilidad",
    "backtesting": "Backtesting",
}

#: Rótulo público de cada prueba de calibración por partición.
CALIBRATION_TEST_LABELS: dict[str, str] = {
    "hosmer_lemeshow": "Hosmer-Lemeshow",
    "brier": "Puntaje de Brier",
}

#: Rótulo público del veredicto de una fila, de calibración o de backtesting.
#:
#: ⚠️ ``not_evaluable`` cubre DOS situaciones y por eso la palabra no puede ser «no evaluado»: un
#: Hosmer-Lemeshow bajo el mínimo técnico (no hay potencia) y el puntaje de Brier (no es una prueba
#: de pasa/falla, es un puntaje). «Sin veredicto» es cierto en las dos.
VALIDATION_DECISION_LABELS: dict[str, str] = {
    "pass": "Pasa",
    "fail": "Falla",
    "not_evaluable": "Sin veredicto",
}

#: Rótulo público del semáforo por grado de rating.
TRAFFIC_LIGHT_LABELS: dict[str, str] = {
    "green": "Verde",
    "amber": "Ámbar",
    "red": "Rojo",
}

#: Rótulo público del estado de una partición en la tabla de discriminación.
DISCRIMINATION_STATUS_LABELS: dict[str, str] = {
    "ok": "Evaluada",
    "not_evaluable": "No evaluable",
}

#: De dónde salió el AUC/Gini/KS de esa partición: reúso o recálculo con el mismo motor.
DISCRIMINATION_SOURCE_LABELS: dict[str, str] = {
    "performance_artifact": "Reusada de la etapa de desempeño",
    "recomputed": "Recalculada en esta etapa",
}

#: Rótulo público de cada parámetro contrastado contra lo realizado.
BACKTEST_PARAMETER_LABELS: dict[str, str] = {
    "pd": "Probabilidad de incumplimiento",
    "lgd": "Severidad",
    "ead": "Exposición",
}

#: Rótulo público de la prueba usada en una fila de backtesting.
BACKTEST_TEST_LABELS: dict[str, str] = {
    "t_test": "t de Student",
    "binomial": "Binomial",
    "jeffreys": "Jeffreys",
}

#: Rótulo público de la prueba de PD por grado, tanto en calibración como en backtesting.
PD_TEST_LABELS: dict[str, str] = {
    "jeffreys": "Jeffreys",
    "binomial": "Binomial",
}

__all__ = [
    "BACKTEST_PARAMETER_LABELS",
    "BACKTEST_TEST_LABELS",
    "CALIBRATION_TEST_LABELS",
    "DISCRIMINATION_SOURCE_LABELS",
    "DISCRIMINATION_STATUS_LABELS",
    "HL_NOT_EVALUABLE_REASON_LABELS",
    "NOT_EVALUABLE_PARTITION_FIELDS",
    "PD_TEST_LABELS",
    "TRAFFIC_LIGHT_LABELS",
    "VALIDATION_DECISION_LABELS",
    "VALIDATION_FAMILY_LABELS",
    "VALIDATION_STATUS_LABELS",
    "BacktestParameter",
    "BacktestRecord",
    "CalibrationTestRecord",
    "DiscriminationRecord",
    "GradeBinomialRecord",
    "HlNotEvaluableReason",
    "NotEvaluablePartition",
    "PdTest",
    "ValidationCardSection",
    "ValidationFamily",
    "ValidationResult",
    "derive_overall_status",
    "derive_test_counts",
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

    Un Hosmer-Lemeshow **sin veredicto** (D-VAL-17) publica ``statistic=None`` —antes publicaba
    ``0.0``, que es el valor de un ajuste perfecto, y ninguna superficie decía por qué no se
    evaluó— y una de las cuatro causas cerradas en ``not_evaluable_reason``. Un HL con veredicto y
    el Brier no llevan causa.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    test: CalibrationTest
    n_groups: int | None
    degrees_of_freedom: int | None
    statistic: float | None
    p_value: float | None
    alpha: float | None
    decision: CalibrationDecision
    not_evaluable_reason: HlNotEvaluableReason | None = None

    @field_validator("partition")
    @classmethod
    def _valida_partition(cls, value: str) -> str:
        """Valida que la partición no esté vacía."""
        if not value.strip():
            raise ValueError("partition no puede estar vacío.")
        return value

    @field_validator("statistic", mode="before")
    @classmethod
    def _normaliza_statistic(cls, value: Any) -> float | None:
        """Admite ``None`` (HL sin veredicto); un número debe ser finito, y ``-0.0`` sale ``0.0``.

        Un ``NaN``/``inf`` no se degrada a ``None`` en silencio: sería declarar «sin veredicto» lo
        que es un defecto del productor.
        """
        if value is None:
            return None
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
            if self.statistic is None:
                raise ValueError("El Brier score es un puntaje: exige statistic.")
            if not 0.0 <= self.statistic <= 1.0:
                raise ValueError("El Brier score debe estar en [0, 1].")
            if self.not_evaluable_reason is not None:
                raise ValueError("El Brier score no es una prueba: no lleva not_evaluable_reason.")
            return self

        if self.n_groups is None or self.degrees_of_freedom is None:
            raise ValueError("Hosmer-Lemeshow exige n_groups y degrees_of_freedom.")
        if self.degrees_of_freedom != self.n_groups - 2 or self.degrees_of_freedom < 1:
            raise ValueError("degrees_of_freedom debe ser G-2 (>=1) en Hosmer-Lemeshow.")
        if self.decision == "not_evaluable":
            if self.p_value is not None:
                raise ValueError("Un Hosmer-Lemeshow not_evaluable no publica p_value.")
            if self.statistic is not None:
                raise ValueError(
                    "Un Hosmer-Lemeshow not_evaluable no publica statistic: 0.0 sería el valor de "
                    "un ajuste perfecto."
                )
            if self.not_evaluable_reason is None:
                raise ValueError("Un Hosmer-Lemeshow not_evaluable exige not_evaluable_reason.")
            return self
        if self.statistic is None or self.p_value is None or self.alpha is None:
            raise ValueError("Un Hosmer-Lemeshow evaluable exige statistic, p_value y alpha.")
        if self.statistic < 0.0:
            raise ValueError("El estadístico Hosmer-Lemeshow no puede ser negativo.")
        if self.not_evaluable_reason is not None:
            raise ValueError("Un Hosmer-Lemeshow evaluable no lleva not_evaluable_reason.")
        return self


class NotEvaluablePartition(BaseModel):
    """Un Hosmer-Lemeshow sin veredicto tal como lo enumera la card (D-VAL-17).

    Es cada entrada de ``metric_sections.validation.not_evaluable_partitions``: la partición, sus
    operaciones, los grupos pedidos, el tamaño del grupo más chico que ``np.array_split`` formó
    (``None`` cuando la partición entera quedó bajo el mínimo y los grupos nunca se formaron), el
    mínimo configurado y la causa. Cerrado y con sus invariantes (pasada 1 de Codex sobre la capa
    B: una entrada de la card se aceptaba como cualquier mapping y sus números no se cotejaban con
    nada): la partición bajo el mínimo tiene ``n < min_rows`` y no forma grupos; las otras tres
    causas pasaron la puerta de la partición (``n >= min_rows``) y su grupo más chico es
    ``n // n_groups``, y la causa sigue la **precedencia exacta del kernel** (pasada 3 de Codex):
    un grupo vacío sólo puede ser ``degenerate_group`` (el kernel lo mira antes que el mínimo); un
    grupo no vacío bajo el mínimo sólo puede ser ``group_below_min`` (la puerta va antes del
    estadístico); ``degenerate_group`` por denominador nulo y ``non_finite_statistic`` exigen un
    grupo que superó el mínimo. El evaluador construye cada entrada con este modelo y
    ``ValidationResult`` lo revalida al reconciliar la card con los records y la tabla.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    n: int = Field(ge=0)
    n_groups: int = Field(ge=3)
    min_group_size: int | None = Field(default=None, ge=0)
    min_rows: int = Field(ge=1)
    reason: HlNotEvaluableReason

    @field_validator("partition")
    @classmethod
    def _valida_partition(cls, value: str) -> str:
        """Valida que la partición no esté vacía."""
        if not value.strip():
            raise ValueError("partition no puede estar vacío.")
        return value

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Los números explican la causa, o la entrada no vale."""
        if self.reason == "partition_below_min":
            if self.min_group_size is not None:
                raise ValueError(
                    "Con partition_below_min los grupos nunca se formaron: min_group_size debe "
                    "ser None."
                )
            if self.n >= self.min_rows:
                raise ValueError(
                    f"partition_below_min exige n < min_rows; n={self.n} no está bajo el mínimo "
                    f"{self.min_rows}."
                )
            return self
        if self.n < self.min_rows:
            raise ValueError(
                f"{self.reason} exige que la partición pasara la puerta: n={self.n} está bajo el "
                f"mínimo {self.min_rows}."
            )
        esperado = self.n // self.n_groups
        if self.min_group_size != esperado:
            raise ValueError(
                f"min_group_size debe ser el grupo más chico de np.array_split, n // n_groups = "
                f"{esperado}; observado {self.min_group_size!r}."
            )
        # La precedencia del kernel decide qué causa es posible con estos números.
        if esperado == 0:
            posibles: tuple[str, ...] = ("degenerate_group",)
            por_que = "un grupo vacío es degenerado antes de mirar el mínimo"
        elif esperado < self.min_rows:
            posibles = ("group_below_min",)
            por_que = "la puerta del mínimo por grupo va antes que el estadístico"
        else:
            posibles = ("degenerate_group", "non_finite_statistic")
            por_que = "con el grupo más chico sobre el mínimo no hay group_below_min"
        if self.reason not in posibles:
            raise ValueError(
                f"El kernel no produce {self.reason!r} con n={self.n}, n_groups={self.n_groups} y "
                f"min_rows={self.min_rows} (grupo más chico {esperado}): {por_que}; las causas "
                f"posibles son {list(posibles)!r}."
            )
        return self


#: Claves —y su orden— de cada entrada de ``not_evaluable_partitions``: las del DTO. El evaluador
#: las escribe, la prosa y el panel las leen, el tipo del front las espeja (gate en
#: ``test_vocabulario_en_pantalla``).
NOT_EVALUABLE_PARTITION_FIELDS: tuple[str, ...] = tuple(NotEvaluablePartition.model_fields)


class GradeBinomialRecord(BaseModel):
    """Fila de ``calibration`` para el test binomial/Jeffreys de PD por grado (SDD-22 §4).

    ``alpha`` es el nivel de significancia con que corrió el contraste; **no** es un corte del
    semáforo. Los cortes con que se decidió ``traffic_light`` viajan aparte —``green_alpha`` y
    ``red_alpha``— para que la fila explique su propio color (D-VAL-15): antes el resultado sólo
    guardaba el color, y con cortes personalizados no había forma de reconstruirlo sin el config.
    El kernel los fija con los que usó (``alpha`` y ``0.2·alpha``) y el evaluador los resella,
    junto al color, con los de ``CalibrationValidationConfig``.
    """

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
    green_alpha: float
    red_alpha: float

    @field_validator("grade")
    @classmethod
    def _valida_grade(cls, value: str) -> str:
        """Valida que el grado de rating no esté vacío."""
        if not value.strip():
            raise ValueError("grade no puede estar vacío.")
        return value

    @field_validator(
        "expected_pd", "observed_dr", "p_value", "alpha", "green_alpha", "red_alpha", mode="before"
    )
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
        """Valida conteos, rangos de probabilidad/p-valor y los cortes del semáforo del grado."""
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
        if not 0.0 < self.green_alpha < 1.0:
            raise ValueError("green_alpha debe estar en (0, 1).")
        if not 0.0 < self.red_alpha < 1.0:
            raise ValueError("red_alpha debe estar en (0, 1).")
        if not self.red_alpha < self.green_alpha:
            raise ValueError("El semáforo exige red_alpha < green_alpha.")
        # La fila explica su propio color, así que el color tiene que ser el que sus cortes
        # deciden (pasada 3 de Codex sobre la capa A). Es la misma regla que
        # ``calibration_tests.traffic_light`` —replicada porque ese módulo importa a éste—, atada
        # por un gate sobre una malla de valores.
        if self.p_value >= self.green_alpha:
            esperado = "green"
        elif self.p_value >= self.red_alpha:
            esperado = "amber"
        else:
            esperado = "red"
        if self.traffic_light != esperado:
            raise ValueError(
                f"traffic_light no corresponde a p_value y los cortes: p_value={self.p_value!r}, "
                f"green_alpha={self.green_alpha!r}, red_alpha={self.red_alpha!r} deciden "
                f"{esperado!r}, no {self.traffic_light!r}."
            )
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
        self._check_semaforo_reconciliado()
        self._check_calibracion_reconciliada()
        self._check_consolidado_derivado()
        return self

    def _check_calibracion_reconciliada(self) -> None:
        """Las filas sin semáforo, sus records y la card dicen lo mismo de cada HL/Brier.

        D-VAL-17; misma clase que la pasada 4 de Codex sobre la capa A, extendida a las filas de HL
        y Brier y a la lista de particiones sin veredicto de la card. La tabla es lo que pinta el
        informe; los records, lo que lee el trail; ``metric_sections.validation.
        not_evaluable_partitions``, lo que leen la prosa y el panel. Se exige que las filas de
        HL/Brier coincidan una a una y en orden con ``calibration_records`` en partición, prueba,
        estadístico, p-valor, veredicto y causa —``None`` y ``NaN`` cuentan como la misma
        ausencia—, y que la lista de la card tenga exactamente las particiones sin veredicto de los
        records, en su orden y con su causa. Sin HL sin veredicto, una card sin la clave vale.
        """
        frame = super().__getattribute__("calibration")
        filas = frame[frame["traffic_light"].isna()]
        if len(filas) != len(self.calibration_records):
            raise ValueError(
                "calibration debe traer exactamente una fila sin semáforo por calibration_record."
            )
        campos = (
            "partition",
            "test",
            "statistic",
            "degrees_of_freedom",
            "p_value",
            "alpha",
            "decision",
            "not_evaluable_reason",
        )
        sin_veredicto: list[tuple[CalibrationTestRecord, int]] = []
        for (_, fila), record in zip(filas.iterrows(), self.calibration_records, strict=True):
            for campo in campos:
                if not _same_cell(fila[campo], getattr(record, campo)):
                    raise ValueError(
                        f"La fila {record.test!r} de {record.partition!r} de calibration no "
                        f"coincide con su record en {campo}: {fila[campo]!r} frente a "
                        f"{getattr(record, campo)!r}."
                    )
            if record.test == "hosmer_lemeshow" and record.decision == "not_evaluable":
                sin_veredicto.append((record, int(fila["n"])))
        section = self.card.metric_sections.get("validation")
        if not isinstance(section, Mapping) or section.get("not_evaluable_partitions") is None:
            if sin_veredicto:
                raise ValueError(
                    "Un resultado con Hosmer-Lemeshow sin veredicto exige "
                    "metric_sections['validation']['not_evaluable_partitions'] en la card."
                )
            return
        publicadas_raw = section["not_evaluable_partitions"]
        # Cada entrada es un DTO cerrado con sus invariantes; una malformada no se descarta en
        # silencio (pasada 1 de Codex sobre la capa B).
        try:
            publicadas = [NotEvaluablePartition.model_validate(item) for item in publicadas_raw]
        except ValueError as exc:
            raise ValueError(
                f"not_evaluable_partitions de la card trae una entrada inválida: {exc}"
            ) from exc
        if len(publicadas) != len(sin_veredicto):
            raise ValueError(
                "not_evaluable_partitions de la card no coincide con los Hosmer-Lemeshow sin "
                f"veredicto de los records: {len(publicadas)} entradas frente a "
                f"{len(sin_veredicto)} records."
            )
        for publicada, (record, n_fila) in zip(publicadas, sin_veredicto, strict=True):
            esperada = {
                "partition": record.partition,
                "reason": record.not_evaluable_reason,
                "n_groups": record.n_groups,
                "n": n_fila,
            }
            observada = {clave: getattr(publicada, clave) for clave in esperada}
            if observada != esperada:
                raise ValueError(
                    "not_evaluable_partitions de la card no coincide con el record y la fila de "
                    f"{record.partition!r}: {observada!r} frente a {esperada!r}."
                )
        self._check_min_rows_canonico(section, publicadas)

    def _check_min_rows_canonico(
        self, section: Mapping[str, Any], publicadas: list[NotEvaluablePartition]
    ) -> None:
        """Cada ``min_rows`` de la card es el umbral efectivo que la propia card publica una vez.

        Pasada 4 de Codex sobre la capa B: la homogeneidad entre entradas es vacua con una sola y
        se burla alterándolas juntas. ``metric_sections.validation.min_rows_per_group`` es la
        fuente canónica —mismo patrón que ``traffic_light_cuts``— y contra ella se cotejan las
        particiones y los grados sin veredicto. Límite declarado, el mismo de la capa A: adulterar
        todas las copias a la vez no se detecta sin el config.
        """
        grados = [item for item in _sequence_of_mappings(section.get("not_evaluable_grades"))]
        if not publicadas and not grados:
            return
        canonico = section.get("min_rows_per_group")
        if isinstance(canonico, bool) or not isinstance(canonico, int) or canonico < 1:
            raise ValueError(
                "Con particiones o grados sin veredicto la card exige "
                "metric_sections['validation']['min_rows_per_group'] entero >= 1: es la fuente "
                f"canónica de cada min_rows; observado {canonico!r}."
            )
        for publicada in publicadas:
            if publicada.min_rows != canonico:
                raise ValueError(
                    f"not_evaluable_partitions de {publicada.partition!r} declara min_rows="
                    f"{publicada.min_rows}, y el umbral efectivo de la corrida es {canonico}."
                )
        for grado in grados:
            if grado.get("min_rows") != canonico:
                raise ValueError(
                    f"not_evaluable_grades de {grado.get('grade')!r} declara min_rows="
                    f"{grado.get('min_rows')!r}, y el umbral efectivo de la corrida es {canonico}."
                )

    def _check_consolidado_derivado(self) -> None:
        """La card cuenta y consolida exactamente lo que sus records y su estabilidad derivan.

        D-VAL-17: ``n_tests``, ``n_failed`` y ``overall_status`` son derivables, y la card no puede
        decir otra cosa.
        Antes ``n_tests`` contaba también los HL y backtests ``not_evaluable`` y el estado caía en
        ``pass`` sin evidencia alguna; ahora la regla vive en :func:`derive_test_counts` y
        :func:`derive_overall_status` —la misma que usa el evaluador— y aquí se exige que la card
        (y la sección CT-2, cuando repite el resumen) la cumpla, también rehidratada.
        """
        n_tests, n_failed = derive_test_counts(
            calibration_records=self.calibration_records,
            grade_records=self.grade_records,
            backtest_records=self.backtest_records,
        )
        if (self.card.n_tests, self.card.n_failed) != (n_tests, n_failed):
            raise ValueError(
                f"La card cuenta n_tests={self.card.n_tests}, n_failed={self.card.n_failed}; las "
                f"decisiones evaluables de los records son n_tests={n_tests}, n_failed={n_failed}."
            )
        esperado = derive_overall_status(
            calibration_records=self.calibration_records,
            grade_records=self.grade_records,
            backtest_records=self.backtest_records,
            stability_frame=super().__getattribute__("stability"),
        )
        if self.card.overall_status != esperado:
            raise ValueError(
                f"La card publica overall_status={self.card.overall_status!r}; lo derivado de los "
                f"records y de la estabilidad es {esperado!r}."
            )
        section = self.card.metric_sections.get("validation")
        if not isinstance(section, Mapping):
            return
        for clave, valor in (
            ("overall_status", self.card.overall_status),
            ("n_tests", self.card.n_tests),
            ("n_failed", self.card.n_failed),
        ):
            if clave in section and section[clave] != valor:
                raise ValueError(
                    f"metric_sections['validation'][{clave!r}] dice {section[clave]!r} y la card "
                    f"{valor!r}: el resumen repetido tiene que ser el mismo."
                )

    def _check_semaforo_reconciliado(self) -> None:
        """Las tres copias del semáforo por grado dicen lo mismo (D-VAL-15; pasada 4 de Codex).

        La tabla ``calibration`` es lo que pinta el informe, ``grade_records`` lo que lee el trail
        y ``metric_sections.validation`` lo que leen la prosa y el panel. Se exige que las filas de
        grado de la tabla (las que traen semáforo) coincidan una a una y en orden con los records
        en grado, p-valor, color y cortes; que los records compartan cortes; que, habiendo
        records, la card traiga la sección CT-2 con ``traffic_light_cuts`` igual al par de los
        records y el recuento de colores ``traffic_light``; y que ese recuento sea el derivado.
        Sin records de grado no hay semáforo que reconciliar y una card mínima vale. Lo que no se
        puede verificar aquí —si los cortes debían estar o ser nulos según el config— queda
        declarado en la enmienda.
        """
        frame = super().__getattribute__("calibration")
        filas = frame[frame["traffic_light"].notna()]
        if len(filas) != len(self.grade_records):
            raise ValueError(
                "calibration debe traer exactamente una fila con semáforo por grade_record."
            )
        # Todos los campos que la fila y el record comparten (pasada 1 de Codex sobre la capa B:
        # antes sólo el semáforo, y un ``n`` o un ``alpha`` adulterados pasaban). El ``statistic``
        # de la fila es el ``z`` asintótico del record.
        campos = (
            ("grade", "grade"),
            ("test", "test"),
            ("n", "n"),
            ("observed_defaults", "observed_defaults"),
            ("expected_pd", "expected_pd"),
            ("observed_dr", "observed_dr"),
            ("statistic", "z_stat"),
            ("p_value", "p_value"),
            ("alpha", "alpha"),
            ("traffic_light", "traffic_light"),
            ("green_alpha", "green_alpha"),
            ("red_alpha", "red_alpha"),
        )
        for (_, fila), record in zip(filas.iterrows(), self.grade_records, strict=True):
            for columna, atributo in campos:
                if not _same_cell(fila[columna], getattr(record, atributo)):
                    raise ValueError(
                        f"La fila de grado {record.grade!r} de calibration no coincide con su "
                        f"record en {columna}: {fila[columna]!r} frente a "
                        f"{getattr(record, atributo)!r}."
                    )
        cortes = {(record.green_alpha, record.red_alpha) for record in self.grade_records}
        if len(cortes) > 1:
            raise ValueError("Todos los grade_records deben compartir los mismos cortes.")
        section = self.card.metric_sections.get("validation")
        if not isinstance(section, Mapping):
            if self.grade_records:
                # Pasada 5 de Codex: la prosa y el panel leen los cortes de la card; una card que
                # perdió la sección CT-2 los callaría en silencio.
                raise ValueError(
                    "Un resultado con grade_records exige metric_sections['validation'] en la "
                    "card, con traffic_light_cuts y traffic_light."
                )
            return
        if self.grade_records:
            esperado = {
                "green_alpha": self.grade_records[0].green_alpha,
                "red_alpha": self.grade_records[0].red_alpha,
            }
            if section.get("traffic_light_cuts") != esperado:
                raise ValueError(
                    "traffic_light_cuts de la card no coincide con los cortes de los records: "
                    f"{section.get('traffic_light_cuts')!r} frente a {esperado!r}."
                )
            if "traffic_light" not in section:
                raise ValueError(
                    "Un resultado con grade_records exige el recuento de colores "
                    "metric_sections['validation']['traffic_light'] en la card."
                )
        if "traffic_light" in section:
            conteo = {
                color: sum(record.traffic_light == color for record in self.grade_records)
                for color in ("green", "amber", "red")
            }
            if dict(section["traffic_light"]) != conteo:
                raise ValueError(
                    "El recuento de colores de la card no es el derivado de los records: "
                    f"{dict(section['traffic_light'])!r} frente a {conteo!r}."
                )

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value


def derive_test_counts(
    *,
    calibration_records: tuple[CalibrationTestRecord, ...],
    grade_records: tuple[GradeBinomialRecord, ...],
    backtest_records: tuple[BacktestRecord, ...],
) -> tuple[int, int]:
    """Cuenta las decisiones **evaluables** y las rechazadas en las cuatro familias (D-VAL-17).

    Un Hosmer-Lemeshow o un backtest ``not_evaluable`` no es una prueba corrida sin veredicto: es
    una prueba que no se pudo correr, y no entra a ``n_tests`` ni a ``n_failed`` —como no entraban
    ya los grados bajo mínimo, que nunca llegan a ``grade_records``—. El Brier es un puntaje y
    tampoco cuenta. Es la regla única que usa el evaluador y que :class:`ValidationResult` exige.
    """
    hl_evaluables = [
        record
        for record in calibration_records
        if record.test == "hosmer_lemeshow" and record.decision in _EVALUABLE_DECISIONS
    ]
    bt_evaluables = [
        record for record in backtest_records if record.decision in _EVALUABLE_DECISIONS
    ]
    n_tests = len(hl_evaluables) + len(grade_records) + len(bt_evaluables)
    n_failed = (
        sum(record.decision == "fail" for record in hl_evaluables)
        + sum(record.traffic_light == "red" for record in grade_records)
        + sum(record.decision == "fail" for record in bt_evaluables)
    )
    return n_tests, n_failed


def derive_overall_status(
    *,
    calibration_records: tuple[CalibrationTestRecord, ...],
    grade_records: tuple[GradeBinomialRecord, ...],
    backtest_records: tuple[BacktestRecord, ...],
    stability_frame: Any,
) -> OverallStatus:
    """Consolida el estado técnico en una de las cuatro palabras (SDD-22 §7; D-VAL-17).

    ``fail`` ante cualquier prueba rechazada, ``warn`` si hay ámbar o PSI en revisión,
    ``not_evaluable`` si no hay evidencia evaluable alguna (§8-9 de la enmienda) y ``pass`` en otro
    caso.
    «Evidencia evaluable» es una decisión ``pass``/``fail`` de calibración, grado o backtesting, o
    una fila de estabilidad con decisión ``pass``/``warn``/``fail``. Antes, con ``n_tests == 0`` y
    sin estabilidad con decisión, el estado caía en ``pass``: una validación que no evaluó nada
    decía que pasaba.
    """
    hard_fail = (
        any(record.decision == "fail" for record in calibration_records)
        or any(record.decision == "fail" for record in backtest_records)
        or any(record.traffic_light == "red" for record in grade_records)
        or _stability_has(stability_frame, "fail")
    )
    if hard_fail:
        return "fail"
    warn = any(record.traffic_light == "amber" for record in grade_records) or _stability_has(
        stability_frame, "warn"
    )
    if warn:
        return "warn"
    n_tests, _ = derive_test_counts(
        calibration_records=calibration_records,
        grade_records=grade_records,
        backtest_records=backtest_records,
    )
    if n_tests == 0 and not any(
        _stability_has(stability_frame, decision) for decision in _EVALUABLE_STABILITY_DECISIONS
    ):
        return "not_evaluable"
    return "pass"


def _stability_has(stability_frame: Any, decision: str) -> bool:
    """Indica si el frame de estabilidad consumido registra alguna decisión dada."""
    if stability_frame.shape[0] == 0:
        return False
    return bool((stability_frame["decision"] == decision).any())


def _sequence_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    """Las entradas de una lista de la card que son mappings (las demás no llevan ``min_rows``)."""
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _same_cell(observado: Any, esperado: Any) -> bool:
    """Compara una celda de la tabla con el campo del record; ``None`` y ``NaN`` son lo mismo.

    Una columna float degrada ``None`` a ``NaN``; una ``object`` lo conserva.
    """
    if _is_missing(observado) or _is_missing(esperado):
        return _is_missing(observado) and _is_missing(esperado)
    return bool(observado == esperado)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, float) and math.isnan(value)


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
