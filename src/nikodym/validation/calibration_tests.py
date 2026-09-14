"""Tests de calibración puros de la validación avanzada (SDD-22 §3.2/§4/§7/§8).

Kernels numéricos deterministas que la capa ``validation`` usa para evaluar la calibración de PD:
Hosmer-Lemeshow, test binomial/Jeffreys por grado, Brier score y el semáforo verde/ámbar/rojo. Las
funciones son puras: reciben arreglos/frames, no auditan ni mutan sus entradas (copias defensivas) y
devuelven los DTOs *frozen* de :mod:`nikodym.validation.results`. El evaluador (B22.5) las orquesta,
re-sella la partición por :meth:`model_copy` y emite el ``log_decision`` de los estados
``not_evaluable`` (§8/§9): estos kernels no tienen sink de auditoría.

``scipy`` se importa de forma **perezosa** dentro de las funciones (mapeando su ausencia a
:class:`~nikodym.core.exceptions.MissingDependencyError`), de modo que importar este módulo no
arrastra ``scipy``/``sklearn``. ``numpy`` y ``pandas`` son dependencias base y sí se cargan al
importar. El Brier score no requiere ``scipy``.

Robustez regulatoria (§8): ningún grupo/grado produce división por cero ni ``NaN`` silencioso. Un
grupo Hosmer-Lemeshow degenerado (``n_g = 0`` o ``mean_pd*(1-mean_pd) = 0``), un grupo con menos
operaciones que ``min_rows_per_group`` (D-VAL-17) o un estadístico no finito marca el test
``not_evaluable`` **con su causa** y sin estadístico —``0.0`` sería el valor de un ajuste
perfecto—; el ``z`` asintótico se vuelve ``None`` cuando su varianza es cero. Los floats publicados
normalizan ``-0.0`` a ``0.0``.

Cotejo contra las fuentes oficiales (enmienda VALIDACION-COTEJADA §2, 2026-09-13; registro en
SDD-22 §12): el Jeffreys por grado es exactamente el del BCE (*Instructions for reporting the
validation results of internal models*, feb. 2019, §2.5.3.1, y su plantilla de reporte de PD) y el
binomial es el de BCBS WP14 (2005, p. 47). Los cortes del semáforo **no tienen anclaje regulatorio
que cotejar**: el BCE no fija cortes sobre el p-valor y las zonas de Basilea 1996 son otra
herramienta (conteo de excepciones de VaR); son un parámetro con default (D-VAL-5) que cada fila
de grado publica junto a su color (D-VAL-15).

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
from typing import Any, Literal, TypeAlias, cast

import numpy as np
import pandas as pd

from nikodym.core.exceptions import MissingDependencyError
from nikodym.validation.config import PdTest
from nikodym.validation.exceptions import CalibrationTestError, ValidationDataError
from nikodym.validation.results import (
    CalibrationTestRecord,
    GradeBinomialRecord,
    HlNotEvaluableReason,
)

TrafficLight: TypeAlias = Literal["green", "amber", "red"]

__all__ = [
    "binomial_by_grade",
    "brier_score",
    "hosmer_lemeshow",
    "traffic_light",
]

_SCORING_EXTRA_MESSAGE = "calibration_tests requiere scipy; instale nikodym[scoring]."
# Nivel de significancia estándar del Hosmer-Lemeshow (D-VAL-4). El kernel es agnóstico a la config:
# el evaluador (B22.5) puede re-decidir el verdicto con el alfa configurado vía model_copy.
_DEFAULT_ALPHA: float = 0.05
# Partición-marcador: los kernels no conocen la partición; el evaluador la re-sella por model_copy.
_DEFAULT_PARTITION: str = "ALL"
# Corte rojo del semáforo por defecto = 0.2*verde: reproduce el default institucional D-VAL-5 (verde
# 0.05 / rojo 0.01) para cualquier alfa y garantiza red_alpha < green_alpha. No es un anclaje
# regulatorio: no existe corte normativo sobre el p-valor (cotejado; el traffic-light de VaR de
# Basilea-1996 es otra herramienta y no aplica a la calibración de PD).
_RED_TO_GREEN_RATIO: float = 0.2


def hosmer_lemeshow(
    y_true: np.ndarray,
    pd_pred: np.ndarray,
    *,
    n_groups: int = 10,
    min_rows_per_group: int = 1,
) -> CalibrationTestRecord:
    """Estadístico Hosmer-Lemeshow por ``G`` deciles de PD y su p-valor chi2 (SDD-22 §3.2).

    Ordena por PD predicha, forma ``G`` grupos de tamaño aproximadamente igual y calcula
    ``HL = sum_g (O_g - n_g*mean_pd_g)^2 / [n_g*mean_pd_g*(1-mean_pd_g)]`` con el factor
    ``(1-mean_pd_g)`` completo (nitpick b). El p-valor es la **cola superior** ``chi2.sf(HL, G-2)``
    (nitpick d); ``G=10`` da ``8`` gl. El verdicto usa el alfa estándar 0.05 (D-VAL-4).

    Sin potencia no hay veredicto (§8; D-VAL-17): el test queda ``not_evaluable`` con
    ``statistic=None`` y una causa cerrada. Un grupo vacío es ``degenerate_group``; un grupo de PD
    con menos operaciones que ``min_rows_per_group`` —la puerta mira el **menor** grupo que deja
    ``np.array_split``; el default ``1`` es inerte y reproduce el comportamiento anterior— es
    ``group_below_min``; un denominador ``n_g*mean_pd_g*(1-mean_pd_g) = 0`` es ``degenerate_group``;
    y un estadístico que desborda con PD extremas es ``non_finite_statistic``. Nunca división por
    cero. El evaluador añade la cuarta causa, ``partition_below_min``, antes de llamar aquí.
    """
    if n_groups < 3:
        raise CalibrationTestError(
            f"n_groups debe ser >= 3 para gl = G-2 >= 1; n_groups={n_groups}."
        )
    if min_rows_per_group < 1:
        raise CalibrationTestError(
            f"min_rows_per_group debe ser >= 1; min_rows_per_group={min_rows_per_group}."
        )
    y, p = _validate_pair(y_true, pd_pred)
    degrees_of_freedom = n_groups - 2

    order = np.argsort(p, kind="stable")
    y_split = np.array_split(y[order], n_groups)
    p_split = np.array_split(p[order], n_groups)
    counts = np.array([group.shape[0] for group in p_split], dtype=np.float64)
    if bool(np.any(counts == 0.0)):
        return _hl_not_evaluable(n_groups, degrees_of_freedom, reason="degenerate_group")
    if float(np.min(counts)) < min_rows_per_group:
        return _hl_not_evaluable(n_groups, degrees_of_freedom, reason="group_below_min")

    observed = np.array([float(np.sum(group)) for group in y_split], dtype=np.float64)
    mean_pd = np.array([float(np.mean(group)) for group in p_split], dtype=np.float64)
    denom = counts * mean_pd * (1.0 - mean_pd)
    if bool(np.any(denom <= 0.0)):
        return _hl_not_evaluable(n_groups, degrees_of_freedom, reason="degenerate_group")

    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        statistic = float(np.sum((observed - counts * mean_pd) ** 2 / denom))
    if not math.isfinite(statistic):
        return _hl_not_evaluable(n_groups, degrees_of_freedom, reason="non_finite_statistic")

    stats = _import_scipy_stats()
    p_value = min(1.0, max(0.0, float(stats.chi2.sf(statistic, degrees_of_freedom))))
    decision: Literal["pass", "fail"] = "fail" if p_value < _DEFAULT_ALPHA else "pass"
    return CalibrationTestRecord(
        partition=_DEFAULT_PARTITION,
        test="hosmer_lemeshow",
        n_groups=n_groups,
        degrees_of_freedom=degrees_of_freedom,
        statistic=_normalize_float(statistic),
        p_value=_normalize_float(p_value),
        alpha=_DEFAULT_ALPHA,
        decision=decision,
    )


def binomial_by_grade(
    frame: pd.DataFrame,
    *,
    grade_col: str,
    pd_col: str,
    target_col: str,
    test: str = "jeffreys",
    alpha: float = 0.05,
) -> list[GradeBinomialRecord]:
    """Contraste binomial/Jeffreys de PD por grado, unilateral superior (subestimación; §3.2).

    Por cada grado con ``N`` operaciones, PD media ``p_hat`` y ``D`` defaults observados:
    ``test='binomial'`` usa ``binomtest(D, N, p_hat, alternative='greater')`` más el ``z``
    asintótico; ``test='jeffreys'`` (default ECB, robusto con ``D=0``) usa la posterior
    ``Beta(D+1/2, N-D+1/2)`` con p-valor unilateral ``beta.cdf(p_hat, D+1/2, N-D+1/2)``: es la
    forma literal del BCE (§2.5.3.1; la plantilla oficial calcula ``BETA.DIST(PD, D+0.5, N-D+0.5,
    TRUE)`` sobre la PD media del grado), cotejada por doble vía (D-VAL-13). El semáforo
    provisional usa ``green_alpha=alpha`` y ``red_alpha=0.2*alpha`` (default institucional D-VAL-5)
    y cada record publica esos dos cortes junto a su color (D-VAL-15); el evaluador los resella con
    los de la config. El ``z`` es ``None`` cuando ``p_hat*(1-p_hat)=0``. Los grados se recorren en
    orden de aparición.
    """
    if test not in ("binomial", "jeffreys"):
        raise CalibrationTestError(
            f"test debe ser 'binomial' o 'jeffreys'; test observado={test!r}."
        )
    resolved_test = cast(PdTest, test)
    green_alpha = _as_open_unit(alpha, label="alpha")
    red_alpha = _normalize_float(green_alpha * _RED_TO_GREEN_RATIO)
    work = _validate_grade_frame(frame, grade_col=grade_col, pd_col=pd_col, target_col=target_col)
    stats = _import_scipy_stats()

    records: list[GradeBinomialRecord] = []
    for grade_value, subset in work.groupby(grade_col, sort=False, observed=True):
        pd_values = subset[pd_col].to_numpy(dtype=np.float64)
        target_values = subset[target_col].to_numpy(dtype=np.float64)
        n = int(pd_values.shape[0])
        p_hat = float(np.mean(pd_values))
        defaults = int(np.sum(target_values))
        observed_dr = float(defaults / n)
        if resolved_test == "binomial":
            p_value = float(stats.binomtest(defaults, n, p_hat, alternative="greater").pvalue)
            z_stat = _asymptotic_z(defaults, n, p_hat)
        else:
            p_value = float(stats.beta.cdf(p_hat, defaults + 0.5, n - defaults + 0.5))
            z_stat = None
        p_value = min(1.0, max(0.0, p_value))
        light = traffic_light(p_value, green_alpha=green_alpha, red_alpha=red_alpha)
        records.append(
            GradeBinomialRecord(
                grade=str(grade_value),
                n=n,
                expected_pd=_normalize_float(p_hat),
                observed_defaults=defaults,
                observed_dr=_normalize_float(observed_dr),
                test=resolved_test,
                p_value=_normalize_float(p_value),
                z_stat=z_stat,
                alpha=green_alpha,
                traffic_light=light,
                green_alpha=green_alpha,
                red_alpha=red_alpha,
            )
        )
    return records


def brier_score(y_true: np.ndarray, pd_pred: np.ndarray) -> CalibrationTestRecord:
    """Calcula el Brier score ``(1/N)*sum(p_i - y_i)^2`` (SDD-22 §3.2).

    El Brier es un puntaje, no un test pass/fail (nitpick a): se persiste como
    :class:`CalibrationTestRecord` con ``test='brier'`` y ``p_value``/``n_groups``
    /``degrees_of_freedom``/``alpha`` en ``None`` y ``decision='not_evaluable'``. No requiere
    ``scipy``.
    """
    y, p = _validate_pair(y_true, pd_pred)
    brier = float(np.mean((p - y) ** 2))
    return CalibrationTestRecord(
        partition=_DEFAULT_PARTITION,
        test="brier",
        n_groups=None,
        degrees_of_freedom=None,
        statistic=_normalize_float(brier),
        p_value=None,
        alpha=None,
        decision="not_evaluable",
    )


def traffic_light(p_value: float, *, green_alpha: float, red_alpha: float) -> TrafficLight:
    """Mapea un p-valor a semáforo verde/ámbar/rojo, monótono (SDD-22 §3.2, D-VAL-5).

    ``p >= green_alpha`` da ``'green'``; ``red_alpha <= p < green_alpha`` da ``'amber'``;
    ``p < red_alpha`` da ``'red'``. Las zonas de Basilea-1996 (conteo de excepciones de VaR) NO
    aplican a la calibración de PD y el BCE no fija cortes sobre el p-valor: ``green_alpha``/
    ``red_alpha`` son un parámetro con default institucional (D-VAL-5), no una norma. Exige
    ``red_alpha < green_alpha``.
    """
    probability = _as_finite_probability(p_value, label="p_value")
    green = _as_open_unit(green_alpha, label="green_alpha")
    red = _as_open_unit(red_alpha, label="red_alpha")
    if not red < green:
        raise CalibrationTestError(
            f"El semáforo exige red_alpha < green_alpha; red_alpha={red!r}, green_alpha={green!r}."
        )
    if probability >= green:
        return "green"
    if probability >= red:
        return "amber"
    return "red"


def _hl_not_evaluable(
    n_groups: int, degrees_of_freedom: int, *, reason: HlNotEvaluableReason
) -> CalibrationTestRecord:
    """Construye el registro Hosmer-Lemeshow ``not_evaluable`` con su causa (§8; D-VAL-17).

    Sin estadístico: el ``0.0`` que publicaba antes es el valor de un ajuste perfecto y ninguna
    superficie podía distinguirlo de una prueba que no corrió.
    """
    return CalibrationTestRecord(
        partition=_DEFAULT_PARTITION,
        test="hosmer_lemeshow",
        n_groups=n_groups,
        degrees_of_freedom=degrees_of_freedom,
        statistic=None,
        p_value=None,
        alpha=None,
        decision="not_evaluable",
        not_evaluable_reason=reason,
    )


def _asymptotic_z(defaults: int, n: int, p_hat: float) -> float | None:
    """Calcula el ``z`` asintótico del test binomial; ``None`` si degenera en el origen (§8).

    La degeneración se decide en el ORIGEN: ``p_hat`` fuera del intervalo abierto ``(0, 1)`` anula
    la varianza binomial ``N*p_hat*(1-p_hat)`` (criterio robusto consistente con el
    t-test/backtesting, decidido en el parámetro, no en la varianza). La varianza binomial es un
    **producto** de positivos, sin resta de la media: no sufre cancelación catastrófica, así que el
    chequeo en el origen es equivalente a ``variance <= 0`` para los insumos válidos y se adopta por
    consistencia.
    """
    if not 0.0 < p_hat < 1.0:
        return None
    variance = n * p_hat * (1.0 - p_hat)
    z = (defaults - n * p_hat) / math.sqrt(variance)
    return _normalize_float(float(z))


def _validate_pair(y_true: Any, pd_pred: Any) -> tuple[np.ndarray, np.ndarray]:
    """Valida y copia ``(y_true, pd_pred)``: igual largo, ``y`` binario y ``pd`` en [0, 1]."""
    y = _as_float_vector(y_true, label="y_true")
    p = _as_float_vector(pd_pred, label="pd_pred")
    if y.shape[0] != p.shape[0]:
        raise ValidationDataError(
            f"y_true y pd_pred deben tener el mismo largo; {y.shape[0]} vs {p.shape[0]}."
        )
    if y.shape[0] == 0:
        raise ValidationDataError("y_true y pd_pred no pueden estar vacíos.")
    if not bool(np.all((y == 0.0) | (y == 1.0))):
        raise ValidationDataError("y_true debe ser binario 0/1.")
    if bool(np.any((p < 0.0) | (p > 1.0))):
        raise ValidationDataError("pd_pred debe estar en [0, 1].")
    return y, p


def _as_float_vector(values: Any, *, label: str) -> np.ndarray:
    """Copia una entrada a un vector ``float64`` 1-D finito sin mutar el original."""
    try:
        array = np.array(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValidationDataError(f"{label} debe ser numérico float64-compatible.") from exc
    if array.ndim != 1:
        raise ValidationDataError(f"{label} debe ser un arreglo 1-D; ndim observado={array.ndim}.")
    if not bool(np.all(np.isfinite(array))):
        raise ValidationDataError(f"{label} debe contener sólo valores finitos.")
    return array


def _validate_grade_frame(
    frame: Any, *, grade_col: str, pd_col: str, target_col: str
) -> pd.DataFrame:
    """Copia y valida el frame por grado: columnas presentes, PD/target finitos, grados no nulos."""
    if not isinstance(frame, pd.DataFrame):
        raise ValidationDataError(
            "binomial_by_grade requiere un pandas.DataFrame; "
            f"tipo observado={type(frame).__name__}."
        )
    work = frame.copy(deep=True)
    for column in (grade_col, pd_col, target_col):
        if column not in work.columns:
            raise ValidationDataError(f"binomial_by_grade requiere la columna '{column}'.")
    if work.shape[0] == 0:
        raise ValidationDataError("binomial_by_grade recibió un frame vacío.")
    if bool(work[grade_col].isna().any()):
        raise ValidationDataError(f"La columna de grado '{grade_col}' no admite valores nulos.")
    pd_values = _column_float(work, pd_col)
    target_values = _column_float(work, target_col)
    if bool(np.any((pd_values < 0.0) | (pd_values > 1.0))):
        raise ValidationDataError(f"La columna de PD '{pd_col}' debe estar en [0, 1].")
    if not bool(np.all((target_values == 0.0) | (target_values == 1.0))):
        raise ValidationDataError(f"La columna target '{target_col}' debe ser binaria 0/1.")
    return work


def _column_float(frame: pd.DataFrame, column: str) -> np.ndarray:
    """Convierte una columna a ``float64`` finito y valida su finitud."""
    try:
        values = frame[column].to_numpy(dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:
        raise ValidationDataError(
            f"La columna '{column}' debe ser numérica float64-compatible."
        ) from exc
    if not bool(np.all(np.isfinite(values))):
        raise ValidationDataError(f"La columna '{column}' debe contener sólo valores finitos.")
    return values


def _as_finite_probability(value: float, *, label: str) -> float:
    """Valida que un p-valor sea un número finito en ``[0, 1]``."""
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise CalibrationTestError(f"{label} debe ser un número finito en [0, 1]; valor={value!r}.")
    return _normalize_float(number)


def _as_open_unit(value: float, *, label: str) -> float:
    """Valida que un corte/alfa sea un número finito en el intervalo abierto ``(0, 1)``."""
    number = float(value)
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        raise CalibrationTestError(f"{label} debe ser un número finito en (0, 1); valor={value!r}.")
    return _normalize_float(number)


def _import_scipy_stats() -> Any:
    """Importa ``scipy.stats`` bajo demanda y traduce su ausencia a un error accionable."""
    try:
        return importlib.import_module("scipy.stats")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` sin alterar los demás valores."""
    number = float(value)
    if number == 0.0:
        return 0.0
    return number
