"""Orquestador de la validación avanzada: :class:`ValidationEvaluator` (SDD-22 §4/§7).

``ValidationEvaluator`` ejecuta, de forma **determinista**, las familias de validación *activas*
(``config.families``) en la secuencia canónica §7 y consolida un :class:`ValidationResult` tidy:

* **discriminación** -- reúsa/consume SDD-11 vía :mod:`nikodym.validation.discrimination` (nunca
  reimplementa AUC/Gini/KS);
* **calibración** -- Hosmer-Lemeshow y Brier por partición y binomial/Jeffreys por grado, reúsando
  los kernels de :mod:`nikodym.validation.calibration_tests`. El **semáforo se recomputa aquí** con
  los cortes independientes de la config (``traffic_light_green_alpha``/``red_alpha``) y no con el
  semáforo provisional que guarda ``binomial_by_grade``;
* **estabilidad** -- reúsa/consume el PSI de SDD-11 vía :mod:`nikodym.validation.stability`;
* **backtesting** -- t-test LGD/EAD y binomial/Jeffreys PD contra las salidas IFRS 9 (SDD-16),
  reúsando :mod:`nikodym.validation.backtesting`.

**Frame analítico común (§6).** ``validate`` recibe el frame de PD calibrada + target + grado ya
alineado (``calibrated_pd``) y los artefactos consumidos; internamente trabaja siempre sobre
**copias profundas** (``copy(deep=True)``): nunca muta artefactos aguas arriba. Los umbrales
técnicos (``min_rows``/``min_events`` de la discriminación por reúso, ``min_obs`` del backtesting)
los **posee el evaluador** y se pasan explícitos a los kernels/evaluadores reúsados: no se dejan en
su default interno (nitpicks B22.4/B22.5). ``min_rows`` viene de config (``min_rows_per_group``).

**Desviación respecto de la firma ilustrativa §4.** §4 dibuja ``validate(calibrated_pd, target,
...)`` con ``target`` como ``Series`` aparte; se implementa el **frame analítico común de §6**: un
único frame con las columnas ``partition``/``target``/``pd_calibrated``/``grade`` (nombres por
config), que evita una segunda alineación por índice. El evaluador no emite auditoría (kernels puros
sin sink): el ``log_decision`` §9 lo emite el :class:`~nikodym.validation.step.ValidationStep`.

``pandas``/``numpy`` se importan al tope (son dependencias base); ``scipy``/``sklearn`` sólo se
cargan de forma perezosa **dentro** de los kernels/evaluadores reúsados, de modo que importar este
módulo no arrastra el stack estadístico. El módulo se importa perezosamente desde el step para
preservar el import liviano de ``nikodym.validation``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from importlib import metadata
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np
import pandas as pd

from nikodym.validation.backtesting import (
    binomial_realised_vs_predicted,
    ttest_realised_vs_predicted,
)
from nikodym.validation.calibration_tests import (
    binomial_by_grade,
    brier_score,
    hosmer_lemeshow,
    traffic_light,
)
from nikodym.validation.config import (
    BacktestingValidationConfig,
    BacktestParameter,
    CalibrationValidationConfig,
    ValidationConfig,
)
from nikodym.validation.discrimination import (
    discrimination_from_artifact,
    discrimination_recomputed,
)
from nikodym.validation.exceptions import (
    ValidationConfigError,
    ValidationDataError,
)
from nikodym.validation.results import (
    _BACKTESTING_COLUMNS,
    _CALIBRATION_COLUMNS,
    _DISCRIMINATION_COLUMNS,
    _STABILITY_COLUMNS,
    BacktestRecord,
    CalibrationTestRecord,
    DiscriminationRecord,
    GradeBinomialRecord,
    OverallStatus,
    ValidationCardSection,
    ValidationResult,
)
from nikodym.validation.stability import evaluate_stability

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["ValidationEvaluator"]

# Orden canónico de las familias en ``families_run`` y en la ejecución (SDD-22 §7).
_FAMILY_ORDER: tuple[str, ...] = ("discrimination", "calibration", "stability", "backtesting")
# Columnas estimadas canónicas del artefacto ``provisioning_ifrs9.detail`` (SDD-16 §6).
_IFRS9_PD_COLUMN: str = "pd_12m"
_IFRS9_LGD_COLUMN: str = "lgd"
_IFRS9_EAD_COLUMN: str = "ead"
# Mínimo de eventos por partición para el fallback de discriminación (reúso PerformanceEvaluator).
# El evaluador lo posee explícitamente (no se hereda del default del kernel; nitpick B22.5).
_MIN_EVENTS_PER_PARTITION: int = 1
# Mínimo de observaciones por segmento del backtesting (piso de computabilidad; nitpick B22.4).
_MIN_OBS_BACKTEST: int = 2
# Marcador de partición para las filas de grado (el binomial agrupa la población, no la partición).
_POOLED_PARTITION: str = "ALL"
# Marcador de grado para las filas de Hosmer-Lemeshow/Brier (no son por grado de rating).
_POOLED_GRADE: str = "ALL"
# Dependencias cuya versión se registra en la card (evidencia reproducible; SDD-22 §8/§9).
_DEPENDENCY_LIBRARIES: tuple[str, ...] = ("pandas", "numpy", "scipy")
# Marcas FALTA-DATO por convención metodológica no verificada por render oficial (§3/§12).
_FALTA_DATO_TRAFFIC_LIGHT: str = "FALTA-DATO-VAL-2"
_FALTA_DATO_JEFFREYS: str = "FALTA-DATO-VAL-3"
_FALTA_DATO_TTEST: str = "FALTA-DATO-VAL-1"


class ValidationEvaluator:
    """Orquesta las familias de validación activas y consolida un :class:`ValidationResult` (§4)."""

    def __init__(self, config: ValidationConfig) -> None:
        """Construye el evaluador desde la sección ``ValidationConfig`` ya validada."""
        self.config = config
        self.families: tuple[str, ...] = tuple(
            family for family in _FAMILY_ORDER if family in config.families
        )
        # Umbrales técnicos que el evaluador posee y pasa explícitos a los kernels reúsados.
        self.min_rows: int = config.calibration.min_rows_per_group
        self.min_events: int = _MIN_EVENTS_PER_PARTITION
        self.min_obs: int = _MIN_OBS_BACKTEST

    @classmethod
    def from_config(cls, cfg: ValidationConfig) -> ValidationEvaluator:
        """Construye ``ValidationEvaluator`` desde ``NikodymConfig.validation``."""
        return cls(cfg)

    def validate(
        self,
        *,
        calibrated_pd: pd.DataFrame | None = None,
        performance_metrics: pd.DataFrame | None = None,
        stability_metrics: pd.DataFrame | None = None,
        stability_frame: pd.DataFrame | None = None,
        ifrs9_detail: pd.DataFrame | None = None,
        realised: pd.DataFrame | None = None,
        model_ref: str = "validation",
    ) -> ValidationResult:
        """Ejecuta las familias activas en la secuencia canónica §7 y publica el resultado tidy.

        ``calibrated_pd`` es el frame analítico común (§6): ``partition``/``target``/
        ``pd_calibrated``/``grade`` (nombres por ``config.calibration``). Los artefactos consumidos
        (``performance_metrics``/``stability_metrics``) y los insumos de backtesting
        (``ifrs9_detail``/``realised``) se pasan tal cual; el evaluador copia todo en profundidad.
        ``model_ref`` identifica el modelo validado en la card. Levanta un
        :class:`~nikodym.validation.exceptions.ValidationConfigError` si no hay familias activas o
        si una brecha crítica gatilla con ``fail_on_falta_dato=True``.
        """
        if not self.families:
            raise ValidationConfigError(
                "La validación exige al menos una familia activa en config.families."
            )
        analytic = _deep_copy(calibrated_pd)
        falta_dato: list[str] = []

        discrimination_records: tuple[DiscriminationRecord, ...] = ()
        calibration_records: tuple[CalibrationTestRecord, ...] = ()
        grade_records: tuple[GradeBinomialRecord, ...] = ()
        not_evaluable_grades: tuple[dict[str, Any], ...] = ()
        backtest_records: tuple[BacktestRecord, ...] = ()
        calibration_frame = _empty_frame(_CALIBRATION_COLUMNS)
        stability_frame_out = _empty_frame(_STABILITY_COLUMNS)

        if "discrimination" in self.families:
            discrimination_records = self._run_discrimination(analytic, performance_metrics)
        if "calibration" in self.families:
            calibration_records, grade_records, calibration_frame, not_evaluable_grades = (
                self._run_calibration(analytic)
            )
            falta_dato.extend(self._calibration_falta_dato())
        if "stability" in self.families:
            stability_frame_out = self._run_stability(stability_metrics, stability_frame)
        if "backtesting" in self.families:
            backtest_records, backtesting_falta = self._resolve_backtesting(ifrs9_detail, realised)
            falta_dato.extend(backtesting_falta)

        discrimination_frame = _discrimination_frame(discrimination_records)
        backtesting_frame = _backtesting_frame(backtest_records)

        overall = _overall_status(
            calibration_records=calibration_records,
            grade_records=grade_records,
            backtest_records=backtest_records,
            stability_frame=stability_frame_out,
        )
        n_tests, n_failed = _test_counts(
            calibration_records=calibration_records,
            grade_records=grade_records,
            backtest_records=backtest_records,
        )
        card = ValidationCardSection(
            model_ref=model_ref,
            families_run=self.families,
            overall_status=overall,
            n_tests=n_tests,
            n_failed=n_failed,
            dependency_versions=_dependency_versions(),
            falta_dato=tuple(falta_dato),
            metric_sections=_metric_sections(
                families=self.families,
                overall=overall,
                n_tests=n_tests,
                n_failed=n_failed,
                grade_records=grade_records,
                not_evaluable_grades=not_evaluable_grades,
            ),
        )
        return ValidationResult(
            discrimination=discrimination_frame,
            calibration=calibration_frame,
            stability=stability_frame_out,
            backtesting=backtesting_frame,
            discrimination_records=discrimination_records,
            calibration_records=calibration_records,
            grade_records=grade_records,
            backtest_records=backtest_records,
            card=card,
        )

    # --- Discriminación (reúso/consumo SDD-11) -------------------------------------------------

    def _run_discrimination(
        self, analytic: pd.DataFrame | None, performance_metrics: pd.DataFrame | None
    ) -> tuple[DiscriminationRecord, ...]:
        """Consume ``discriminant_metrics`` o cae al fallback por reúso de ``PerformanceEvaluator``.

        Pasa ``min_rows``/``min_events`` explícitos al fallback (nitpick B22.5). Una celda mal
        formada del artefacto consumido se traduce a ``ValidationDataError`` (nitpick B22.5).
        """
        disc = self.config.discrimination
        calib = self.config.calibration
        if disc.consume_performance and performance_metrics is not None:
            try:
                records = discrimination_from_artifact(
                    performance_metrics, partitions=disc.partitions
                )
            except (ValueError, TypeError) as exc:
                raise ValidationDataError(
                    f"El artefacto discriminant_metrics contiene celdas malformadas: {exc}."
                ) from exc
            return tuple(records)
        if analytic is None:
            raise ValidationDataError(
                "La discriminación por fallback (reúso de PerformanceEvaluator) exige el frame de "
                "PD calibrada: no hay artefacto discriminant_metrics consumible ni frame analítico."
            )
        records = discrimination_recomputed(
            analytic,
            pd_column=calib.pd_column,
            target_column=calib.target_column,
            partition_column=calib.partition_column,
            partitions=disc.partitions,
            min_rows_per_partition=self.min_rows,
            min_events_per_partition=self.min_events,
        )
        return tuple(records)

    # --- Calibración (aporte propio) -----------------------------------------------------------

    def _run_calibration(
        self, analytic: pd.DataFrame | None
    ) -> tuple[
        tuple[CalibrationTestRecord, ...],
        tuple[GradeBinomialRecord, ...],
        pd.DataFrame,
        tuple[dict[str, Any], ...],
    ]:
        """Calcula HL/Brier por partición y binomial/Jeffreys por grado, y arma el frame tidy §6.

        El semáforo por grado se **recomputa** con los cortes independientes de la config vía
        ``model_copy`` (nitpick B22.3): ``binomial_by_grade`` sólo entrega un semáforo provisional.
        Devuelve además la tupla de grados bajo mínimo (``not_evaluable``) que el step auditará:
        éstos NO entran al frame tidy ni a ``grade_records`` (ver :meth:`_grade_records`).
        """
        if analytic is None:
            raise ValidationDataError(
                "La calibración exige el frame de PD calibrada (calibrated_pd)."
            )
        calib = self.config.calibration
        frame = _validate_calibration_frame(
            analytic,
            partition_column=calib.partition_column,
            target_column=calib.target_column,
            pd_column=calib.pd_column,
        )

        calibration_records: list[CalibrationTestRecord] = []
        rows: list[dict[str, Any]] = []
        for partition in _ordered_partitions(frame, calib.partition_column):
            subset = frame[frame[calib.partition_column] == partition]
            stats = _partition_stats(subset, calib.target_column, calib.pd_column)
            y_true = subset[calib.target_column].to_numpy()
            pd_pred = subset[calib.pd_column].to_numpy()
            if calib.hosmer_lemeshow:
                hl_record = self._hosmer_lemeshow_record(partition, y_true, pd_pred)
                calibration_records.append(hl_record)
                rows.append(_hl_row(hl_record, partition, stats))
            if calib.brier:
                brier_record = brier_score(y_true, pd_pred).model_copy(
                    update={"partition": partition}
                )
                calibration_records.append(brier_record)
                rows.append(_brier_row(brier_record, partition, stats))

        grade_records, not_evaluable_grades = self._grade_records(frame)
        rows.extend(_grade_row(record) for record in grade_records)

        calibration_frame = _build_frame(
            rows,
            _CALIBRATION_COLUMNS,
            nullable=("degrees_of_freedom", "p_value", "alpha", "traffic_light"),
        )
        return (
            tuple(calibration_records),
            grade_records,
            calibration_frame,
            not_evaluable_grades,
        )

    def _hosmer_lemeshow_record(
        self, partition: str, y_true: np.ndarray, pd_pred: np.ndarray
    ) -> CalibrationTestRecord:
        """Evalúa Hosmer-Lemeshow re-sellando partición y alfa; bajo mínimo → ``not_evaluable``."""
        calib = self.config.calibration
        if y_true.shape[0] < self.min_rows:
            return CalibrationTestRecord(
                partition=partition,
                test="hosmer_lemeshow",
                n_groups=calib.hl_n_groups,
                degrees_of_freedom=calib.hl_n_groups - 2,
                statistic=0.0,
                p_value=None,
                alpha=None,
                decision="not_evaluable",
            )
        record = hosmer_lemeshow(y_true, pd_pred, n_groups=calib.hl_n_groups)
        return _reseal_hosmer_lemeshow(record, partition=partition, alpha=calib.alpha)

    def _grade_records(
        self, frame: pd.DataFrame
    ) -> tuple[tuple[GradeBinomialRecord, ...], tuple[dict[str, Any], ...]]:
        """Ejecuta el binomial/Jeffreys por grado y aplica la puerta ``min_rows`` (SDD-22 §6/§8).

        Invariante regulatorio SDD-22 §6/§7.4d/§8: un grado con ``n < min_rows_per_group`` no tiene
        potencia estadística, así que **nunca** produce semáforo/decisión: queda ``not_evaluable``
        auditado y no contamina ``overall_status``/``n_failed`` (mismo trato que un grupo
        Hosmer-Lemeshow bajo mínimo). La puerta se aplica **antes** de recomponer el semáforo y
        **antes** de que el grado alimente el verdicto.

        Opción mínima y fiel al invariante (SDD-22 §4): ``GradeBinomialRecord`` (aprobado en B22.2)
        no tiene estado ``not_evaluable`` —su ``traffic_light`` es ``green/amber/red`` obligatorio—,
        así que los grados bajo mínimo se **excluyen** de ``grade_records`` (que alimenta el frame
        tidy y el verdicto) y se devuelven como descriptores honestos (sin p-valor/semáforo
        engañoso) que :class:`~nikodym.validation.step.ValidationStep` audita con ``log_decision``
        §9. Reabrir el DTO para representarlos ampliaría el alcance de B22.2 sin aportar al
        invariante.
        """
        calib = self.config.calibration
        if not calib.binomial_by_grade:
            return (), ()
        records = binomial_by_grade(
            frame,
            grade_col=calib.grade_col,
            pd_col=calib.pd_column,
            target_col=calib.target_column,
            test=calib.pd_test,
            alpha=calib.alpha,
        )
        evaluable: list[GradeBinomialRecord] = []
        not_evaluable: list[dict[str, Any]] = []
        for record in records:
            if record.n < self.min_rows:
                not_evaluable.append(_not_evaluable_grade(record, self.min_rows))
            else:
                evaluable.append(_reseal_traffic_light(record, calib))
        return tuple(evaluable), tuple(not_evaluable)

    def _calibration_falta_dato(self) -> list[str]:
        """Enumera las brechas metodológicas de la calibración (semáforo / Jeffreys)."""
        calib = self.config.calibration
        marks: list[str] = []
        if calib.binomial_by_grade:
            marks.append(_FALTA_DATO_TRAFFIC_LIGHT)
            if calib.pd_test == "jeffreys":
                marks.append(_FALTA_DATO_JEFFREYS)
        return marks

    # --- Estabilidad (reúso/consumo SDD-11) ----------------------------------------------------

    def _run_stability(
        self, stability_metrics: pd.DataFrame | None, stability_frame: pd.DataFrame | None
    ) -> pd.DataFrame:
        """Consume ``stability_metrics`` o cae al fallback por reúso de ``StabilityEvaluator``.

        Una celda malformada del artefacto consumido se traduce a ``ValidationDataError``.
        """
        stab = self.config.stability
        try:
            return evaluate_stability(
                stab,
                stability_metrics=stability_metrics,
                frame=stability_frame,
            )
        except (ValueError, TypeError) as exc:
            raise ValidationDataError(
                f"El artefacto stability_metrics contiene celdas malformadas: {exc}."
            ) from exc

    # --- Backtesting (aporte propio) -----------------------------------------------------------

    def _resolve_backtesting(
        self, ifrs9_detail: pd.DataFrame | None, realised: pd.DataFrame | None
    ) -> tuple[tuple[BacktestRecord, ...], list[str]]:
        """Corre el backtesting IFRS 9 o difiere a ``FALTA-DATO`` según ``fail_on_falta_dato``."""
        blocker = self._backtesting_blocker(ifrs9_detail, realised)
        if blocker is not None:
            if self.config.fail_on_falta_dato:
                raise ValidationConfigError(blocker)
            return (), [f"FALTA-DATO: {blocker}"]
        # blocker None garantiza ambos frames no nulos; ``cast`` estrecha sin abrir una rama.
        records = self._run_backtesting(
            cast(pd.DataFrame, ifrs9_detail), cast(pd.DataFrame, realised)
        )
        marks: list[str] = []
        parameters = self.config.backtesting.parameters
        if "lgd" in parameters or "ead" in parameters:
            marks.append(_FALTA_DATO_TTEST)
        if "pd" in parameters and self.config.backtesting.pd_test == "jeffreys":
            marks.append(_FALTA_DATO_JEFFREYS)
        return records, marks

    def _backtesting_blocker(
        self, ifrs9_detail: pd.DataFrame | None, realised: pd.DataFrame | None
    ) -> str | None:
        """Devuelve el motivo por el que el backtesting no puede correr, o ``None`` si sí puede."""
        bt = self.config.backtesting
        if not bt.enabled:
            return "families incluye 'backtesting' pero backtesting.enabled=False."
        if ifrs9_detail is None:
            return "falta el artefacto provisioning_ifrs9.detail para el backtesting."
        if realised is None:
            return "falta data.frame con las columnas de resultado realizado para el backtesting."
        required_realised = _required_realised_columns(bt)
        missing_realised = [col for col in required_realised if col not in realised.columns]
        if missing_realised:
            return f"data.frame no contiene columnas de resultado realizado: {missing_realised}."
        required_estimated = _required_estimated_columns(bt)
        missing_estimated = [col for col in required_estimated if col not in ifrs9_detail.columns]
        if missing_estimated:
            return f"provisioning_ifrs9.detail no contiene columnas estimadas: {missing_estimated}."
        return None

    def _run_backtesting(
        self, ifrs9_detail: pd.DataFrame, realised: pd.DataFrame
    ) -> tuple[BacktestRecord, ...]:
        """Alinea estimado-vs-realizado por índice y contrasta cada ``parameter x segment`` (§7)."""
        bt = self.config.backtesting
        frame = _assemble_backtest_frame(ifrs9_detail, realised, bt)
        records: list[BacktestRecord] = []
        for parameter in bt.parameters:
            for segment, subset in _segments(frame):
                records.append(self._backtest_record(parameter, segment, subset))
        return tuple(records)

    def _backtest_record(
        self, parameter: BacktestParameter, segment: str, subset: pd.DataFrame
    ) -> BacktestRecord:
        """Aplica el contraste correcto: binomial/Jeffreys para PD, t-test para LGD/EAD."""
        bt = self.config.backtesting
        if parameter == "pd":
            return binomial_realised_vs_predicted(
                subset["__realised_pd__"].to_numpy(),
                subset["__pd_est__"].to_numpy(),
                segment=segment,
                test=bt.pd_test,
                alpha=bt.alpha,
                min_obs=self.min_obs,
            )
        if parameter == "lgd":
            realised_col, estimated_col = "__realised_lgd__", "__lgd_est__"
        else:
            realised_col, estimated_col = "__realised_ead__", "__ead_est__"
        return ttest_realised_vs_predicted(
            subset[realised_col].to_numpy(),
            subset[estimated_col].to_numpy(),
            one_sided=bt.one_sided,
            alpha=bt.alpha,
            parameter=parameter,
            segment=segment,
            min_obs=self.min_obs,
        )


# ─────────────────────────── helpers puros (testables) ───────────────────────────


def _deep_copy(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    """Copia defensiva profunda; ``None`` se propaga sin tocar (artefacto ausente)."""
    if frame is None:
        return None
    if not isinstance(frame, pd.DataFrame):
        raise ValidationDataError(
            f"Se esperaba un pandas.DataFrame; tipo observado={type(frame).__name__}."
        )
    return frame.copy(deep=True)


def _empty_frame(columns: tuple[str, ...]) -> pd.DataFrame:
    """Construye un frame tidy vacío con las columnas canónicas de §6."""
    return pd.DataFrame({name: [] for name in columns}, columns=list(columns))


def _build_frame(
    rows: list[dict[str, Any]],
    columns: tuple[str, ...],
    *,
    nullable: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Construye un frame tidy desde filas dict respetando el orden canónico de columnas.

    Las columnas ``nullable`` (que mezclan valor y ausencia) se fuerzan a dtype ``object`` para
    preservar ``None`` en vez de degradarlo a ``NaN`` (invariante §6/§9: jamás se publica ``NaN``).
    """
    if not rows:
        return _empty_frame(columns)
    series: dict[str, Any] = {}
    for name in columns:
        values = [row[name] for row in rows]
        series[name] = pd.Series(values, dtype=object) if name in nullable else pd.Series(values)
    return pd.DataFrame(series, columns=list(columns))


def _ordered_partitions(frame: pd.DataFrame, partition_column: str) -> list[str]:
    """Devuelve las particiones presentes en orden estable de aparición (reproducibilidad §9)."""
    seen: dict[str, None] = {}
    for value in frame[partition_column].tolist():
        seen.setdefault(str(value), None)
    return list(seen)


def _validate_calibration_frame(
    frame: pd.DataFrame, *, partition_column: str, target_column: str, pd_column: str
) -> pd.DataFrame:
    """Valida el frame analítico de calibración: columnas presentes, PD en (0,1), target binario."""
    for column in (partition_column, target_column, pd_column):
        if column not in frame.columns:
            raise ValidationDataError(f"El frame de calibración requiere la columna '{column}'.")
    if frame.shape[0] == 0:
        raise ValidationDataError("El frame de calibración no puede estar vacío.")
    pd_values = _as_float_array(frame[pd_column], label=pd_column)
    target_values = _as_float_array(frame[target_column], label=target_column)
    if bool(np.any((pd_values <= 0.0) | (pd_values >= 1.0))):
        raise ValidationDataError(
            f"La columna de PD calibrada '{pd_column}' debe estar en el intervalo abierto (0, 1)."
        )
    if not bool(np.all((target_values == 0.0) | (target_values == 1.0))):
        raise ValidationDataError(f"La columna target '{target_column}' debe ser binaria 0/1.")
    return frame


def _partition_stats(
    subset: pd.DataFrame, target_column: str, pd_column: str
) -> tuple[int, int, float, float]:
    """Resume ``(n, defaults, expected_pd, observed_dr)`` de una partición para el frame tidy."""
    target_values = _as_float_array(subset[target_column], label=target_column)
    pd_values = _as_float_array(subset[pd_column], label=pd_column)
    n = int(target_values.shape[0])
    defaults = int(np.sum(target_values))
    expected_pd = _normalize_float(float(np.mean(pd_values)))
    observed_dr = _normalize_float(float(defaults / n))
    return n, defaults, expected_pd, observed_dr


def _as_float_array(series: pd.Series, *, label: str) -> np.ndarray:
    """Convierte una columna a ``float64`` finito; celdas malformadas → ``ValidationDataError``."""
    try:
        array = np.asarray(series.to_numpy(), dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValidationDataError(
            f"La columna '{label}' debe ser numérica float64-compatible."
        ) from exc
    if not bool(np.all(np.isfinite(array))):
        raise ValidationDataError(f"La columna '{label}' debe contener sólo valores finitos.")
    return array


def _reseal_hosmer_lemeshow(
    record: CalibrationTestRecord, *, partition: str, alpha: float
) -> CalibrationTestRecord:
    """Re-sella el HL del kernel con la partición y el alfa de config, re-decidiendo pass/fail."""
    if record.decision == "not_evaluable" or record.p_value is None:
        return record.model_copy(update={"partition": partition})
    decision: Literal["pass", "fail"] = "fail" if record.p_value < alpha else "pass"
    return record.model_copy(update={"partition": partition, "alpha": alpha, "decision": decision})


def _reseal_traffic_light(
    record: GradeBinomialRecord, calib: CalibrationValidationConfig
) -> GradeBinomialRecord:
    """Recompone el semáforo con los cortes independientes de config (nitpick B22.3)."""
    light = traffic_light(
        record.p_value,
        green_alpha=calib.traffic_light_green_alpha,
        red_alpha=calib.traffic_light_red_alpha,
    )
    return record.model_copy(update={"traffic_light": light})


def _not_evaluable_grade(record: GradeBinomialRecord, min_rows: int) -> dict[str, Any]:
    """Descriptor auditable de un grado bajo mínimo (SDD-22 §6/§8): conteos honestos, sin semáforo.

    Conserva sólo la evidencia descriptiva del grado (``grade``/``n``/``observed_defaults``/
    ``expected_pd``/``observed_dr``) y el mínimo técnico que gatilló la exclusión; **omite**
    deliberadamente el ``p_value``/``traffic_light`` que ``binomial_by_grade`` calcula, porque una
    muestra sin potencia no debe publicar un veredicto engañoso. El step lo audita con
    ``log_decision``.
    """
    return {
        "grade": record.grade,
        "n": record.n,
        "observed_defaults": record.observed_defaults,
        "expected_pd": record.expected_pd,
        "observed_dr": record.observed_dr,
        "min_rows": min_rows,
        "status": "not_evaluable",
    }


def _hl_row(
    record: CalibrationTestRecord, partition: str, stats: tuple[int, int, float, float]
) -> dict[str, Any]:
    """Proyecta un registro Hosmer-Lemeshow a una fila tidy del artefacto ``calibration``."""
    n, defaults, expected_pd, observed_dr = stats
    return {
        "partition": partition,
        "test": "hosmer_lemeshow",
        "grade": _POOLED_GRADE,
        "n": n,
        "observed_defaults": defaults,
        "expected_pd": expected_pd,
        "observed_dr": observed_dr,
        "statistic": record.statistic,
        "degrees_of_freedom": record.degrees_of_freedom,
        "p_value": record.p_value,
        "alpha": record.alpha,
        "decision": record.decision,
        "traffic_light": None,
    }


def _brier_row(
    record: CalibrationTestRecord, partition: str, stats: tuple[int, int, float, float]
) -> dict[str, Any]:
    """Proyecta un registro Brier a una fila tidy del artefacto ``calibration``."""
    n, defaults, expected_pd, observed_dr = stats
    return {
        "partition": partition,
        "test": "brier",
        "grade": _POOLED_GRADE,
        "n": n,
        "observed_defaults": defaults,
        "expected_pd": expected_pd,
        "observed_dr": observed_dr,
        "statistic": record.statistic,
        "degrees_of_freedom": None,
        "p_value": None,
        "alpha": None,
        "decision": record.decision,
        "traffic_light": None,
    }


def _grade_row(record: GradeBinomialRecord) -> dict[str, Any]:
    """Proyecta un registro binomial/Jeffreys por grado a una fila tidy de ``calibration``."""
    decision: Literal["pass", "fail"] = "fail" if record.traffic_light == "red" else "pass"
    return {
        "partition": _POOLED_PARTITION,
        "test": record.test,
        "grade": record.grade,
        "n": record.n,
        "observed_defaults": record.observed_defaults,
        "expected_pd": record.expected_pd,
        "observed_dr": record.observed_dr,
        "statistic": record.z_stat if record.z_stat is not None else 0.0,
        "degrees_of_freedom": None,
        "p_value": record.p_value,
        "alpha": record.alpha,
        "decision": decision,
        "traffic_light": record.traffic_light,
    }


def _discrimination_frame(records: tuple[DiscriminationRecord, ...]) -> pd.DataFrame:
    """Proyecta los DiscriminationRecords a su frame tidy §6 (una fila por registro)."""
    rows = [
        {
            "partition": record.partition,
            "n_total": record.n_total,
            "n_bad": record.n_bad,
            "auc": record.auc,
            "gini": record.gini,
            "ks": record.ks,
            "source": record.source,
            "status": record.status,
        }
        for record in records
    ]
    return _build_frame(rows, _DISCRIMINATION_COLUMNS, nullable=("auc", "gini", "ks"))


def _backtesting_frame(records: tuple[BacktestRecord, ...]) -> pd.DataFrame:
    """Proyecta los BacktestRecords a su frame tidy §6 (una fila por registro)."""
    rows = [
        {
            "parameter": record.parameter,
            "segment": record.segment,
            "n": record.n,
            "predicted_mean": record.predicted_mean,
            "realised_mean": record.realised_mean,
            "test": record.test,
            "statistic": record.statistic,
            "p_value": record.p_value,
            "alpha": record.alpha,
            "one_sided": record.one_sided,
            "decision": record.decision,
        }
        for record in records
    ]
    return _build_frame(rows, _BACKTESTING_COLUMNS)


def _required_realised_columns(bt: BacktestingValidationConfig) -> list[str]:
    """Columnas de resultado realizado exigidas por los parámetros de backtesting activos."""
    columns: list[str] = []
    if "pd" in bt.parameters:
        columns.append(bt.realised_pd_col)
    if "lgd" in bt.parameters:
        columns.append(bt.realised_lgd_col)
    if "ead" in bt.parameters:
        columns.append(bt.realised_ead_col)
    return columns


def _required_estimated_columns(bt: BacktestingValidationConfig) -> list[str]:
    """Columnas estimadas (SDD-16) exigidas por los parámetros de backtesting activos."""
    columns: list[str] = [bt.segment_col]
    if "pd" in bt.parameters:
        columns.append(_IFRS9_PD_COLUMN)
    if "lgd" in bt.parameters:
        columns.append(_IFRS9_LGD_COLUMN)
    if "ead" in bt.parameters:
        columns.append(_IFRS9_EAD_COLUMN)
    return columns


def _assemble_backtest_frame(
    ifrs9_detail: pd.DataFrame, realised: pd.DataFrame, bt: BacktestingValidationConfig
) -> pd.DataFrame:
    """Alinea estimado (IFRS 9) y realizado (data.frame) por índice para el backtesting (§6).

    ``ifrs9_detail`` puede traer celdas ``Decimal``/``float`` (nitpick c): se convierten a
    ``float64`` con ``ValidationDataError`` ante celdas mal formadas. El segmento sale del lado
    estimado (``segment_col`` de SDD-16). Índices no alineables → ``ValidationDataError``.
    """
    estimated = ifrs9_detail.copy(deep=True)
    observed = realised.copy(deep=True)
    if not estimated.index.equals(observed.index):
        raise ValidationDataError(
            "provisioning_ifrs9.detail y data.frame no comparten índice: el backtesting exige "
            "estimado y realizado alineados por operación (sin merge ambiguo)."
        )
    data: dict[str, Any] = {
        "__segment__": [str(value) for value in estimated[bt.segment_col].tolist()],
    }
    if "pd" in bt.parameters:
        data["__pd_est__"] = _as_float_array(estimated[_IFRS9_PD_COLUMN], label=_IFRS9_PD_COLUMN)
        data["__realised_pd__"] = _as_float_array(
            observed[bt.realised_pd_col], label=bt.realised_pd_col
        )
    if "lgd" in bt.parameters:
        data["__lgd_est__"] = _as_float_array(estimated[_IFRS9_LGD_COLUMN], label=_IFRS9_LGD_COLUMN)
        data["__realised_lgd__"] = _as_float_array(
            observed[bt.realised_lgd_col], label=bt.realised_lgd_col
        )
    if "ead" in bt.parameters:
        data["__ead_est__"] = _as_float_array(estimated[_IFRS9_EAD_COLUMN], label=_IFRS9_EAD_COLUMN)
        data["__realised_ead__"] = _as_float_array(
            observed[bt.realised_ead_col], label=bt.realised_ead_col
        )
    return pd.DataFrame(data, index=estimated.index)


def _segments(frame: pd.DataFrame) -> Iterator[tuple[str, pd.DataFrame]]:
    """Itera los segmentos del backtesting en orden estable de aparición (reproducibilidad §9)."""
    seen: dict[str, None] = {}
    for value in frame["__segment__"].tolist():
        seen.setdefault(str(value), None)
    for segment in seen:
        yield segment, frame[frame["__segment__"] == segment]


def _overall_status(
    *,
    calibration_records: tuple[CalibrationTestRecord, ...],
    grade_records: tuple[GradeBinomialRecord, ...],
    backtest_records: tuple[BacktestRecord, ...],
    stability_frame: pd.DataFrame,
) -> OverallStatus:
    """Consolida el verdicto: ``fail`` ante cualquier test crítico rechazado; ``warn`` si ámbar."""
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
    return "warn" if warn else "pass"


def _stability_has(stability_frame: pd.DataFrame, decision: str) -> bool:
    """Indica si el frame de estabilidad consumido registra alguna decisión dada."""
    if stability_frame.shape[0] == 0:
        return False
    return bool((stability_frame["decision"] == decision).any())


def _test_counts(
    *,
    calibration_records: tuple[CalibrationTestRecord, ...],
    grade_records: tuple[GradeBinomialRecord, ...],
    backtest_records: tuple[BacktestRecord, ...],
) -> tuple[int, int]:
    """Cuenta tests ejecutados y rechazados (Brier no es test pass/fail: no cuenta)."""
    hl_records = [record for record in calibration_records if record.test == "hosmer_lemeshow"]
    n_tests = len(hl_records) + len(grade_records) + len(backtest_records)
    n_failed = (
        sum(record.decision == "fail" for record in hl_records)
        + sum(record.traffic_light == "red" for record in grade_records)
        + sum(record.decision == "fail" for record in backtest_records)
    )
    return n_tests, n_failed


def _metric_sections(
    *,
    families: tuple[str, ...],
    overall: OverallStatus,
    n_tests: int,
    n_failed: int,
    grade_records: tuple[GradeBinomialRecord, ...],
    not_evaluable_grades: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Arma la puerta CT-2 ``metric_sections`` tidy para report/governance (SDD-22 §4).

    Publica los grados bajo mínimo como ``not_evaluable_grades`` (traza aditiva CT-2): deja
    constancia de que existían pero se omitieron por falta de potencia, sin inflar el semáforo ni el
    verdicto. El step los audita además con ``log_decision`` §9.
    """
    return {
        "validation": {
            "families_run": list(families),
            "overall_status": overall,
            "n_tests": n_tests,
            "n_failed": n_failed,
            "traffic_light": {
                "green": sum(record.traffic_light == "green" for record in grade_records),
                "amber": sum(record.traffic_light == "amber" for record in grade_records),
                "red": sum(record.traffic_light == "red" for record in grade_records),
            },
            "not_evaluable_grades": [dict(item) for item in not_evaluable_grades],
        }
    }


def _dependency_versions() -> dict[str, str]:
    """Recolecta las versiones de pandas/numpy/scipy sin importar el stack estadístico."""
    versions: dict[str, str] = {}
    for library in _DEPENDENCY_LIBRARIES:
        try:
            versions[library] = metadata.version(library)
        except metadata.PackageNotFoundError:
            continue
    return versions


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` sin alterar los demás valores."""
    number = float(value)
    if number == 0.0:
        return 0.0
    return number
