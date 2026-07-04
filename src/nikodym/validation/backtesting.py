"""Kernels de backtesting realizado-vs-estimado de la validación avanzada (SDD-22 §3.4/§4/§7/§8).

Kernels numéricos deterministas que la capa ``validation`` usa para contrastar los parámetros IFRS 9
*estimados* (salidas de SDD-16) contra los *realizados* del período de desempeño, por parámetro y
segmento:

* :func:`ttest_realised_vs_predicted` -- t-test pareado estilo ECB para LGD/EAD sobre el error
  ``e_i = realizado_i - estimado_i`` (media ``e_bar``, desviación muestral ``s``, estadístico
  ``T = sqrt(N)*e_bar/s``), unilateral por defecto (H0: el parámetro no está subestimado);
* :func:`binomial_realised_vs_predicted` -- contraste binomial/Jeffreys para PD (D-VAL-6: PD
  nunca usa t-test), *reutilizando* ``binomial_by_grade`` de ``calibration_tests`` para no
  reimplementar el p-valor exacto/posterior; publica la desviación estandarizada como estadístico.

Las funciones son puras: reciben arreglos, no auditan ni mutan sus entradas (copias defensivas) y
devuelven el DTO *frozen* ``BacktestRecord``. El evaluador (B22.6) las orquesta por
``parameter x segment`` y emite el ``log_decision`` de los ``not_evaluable`` (§8/§9): estos kernels
no tienen sink de auditoría.

``scipy`` se importa de forma **perezosa** dentro de las funciones (mapeando su ausencia a
:class:`~nikodym.core.exceptions.MissingDependencyError` del extra ``[scoring]``), de modo que
importar este módulo no arrastra ``scipy``/``sklearn``. ``numpy``/``pandas`` son dependencias base.

Robustez regulatoria (§8): con ``N < min`` técnico o muestra degenerada no se afirma significancia;
el registro queda ``not_evaluable`` reportando el estadístico/p-valor si son computables. La
degeneración se decide en el **origen** (rango de errores nulo en el t-test; ``p_hat`` fuera de
``(0, 1)`` en el binomial), no en el estadístico derivado, para que un residuo ~1e-17 por
cancelación catastrófica NO produzca un ``fail`` regulatorio falso ni un veredicto no reproducible
entre plataformas. Los floats normalizan ``-0.0`` a ``0.0`` y jamás escapa ``NaN``/``inf``.

FALTA-DATO-VAL-1: la forma exacta del t-test ECB (simple vs ponderado por exposición, orientación y
valor crítico según la versión vigente del PDF) queda por verificar; el default es el t-test pareado
simple unilateral (``e_i = realizado - estimado``), configurable vía ``one_sided`` -- no bloquea ni
escala. FALTA-DATO-VAL-3: la orientación del p-valor Jeffreys se hereda de ``calibration_tests``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from typing import Any, cast

import numpy as np
import pandas as pd

from nikodym.core.exceptions import MissingDependencyError
from nikodym.validation.calibration_tests import binomial_by_grade
from nikodym.validation.config import BacktestParameter, PdTest
from nikodym.validation.exceptions import BacktestError, ValidationDataError
from nikodym.validation.results import BacktestDecision, BacktestRecord

__all__ = [
    "binomial_realised_vs_predicted",
    "ttest_realised_vs_predicted",
]

_SCORING_EXTRA_MESSAGE = "backtesting requiere scipy; instale nikodym[scoring]."
# Segmento-marcador: el kernel no lo conoce; el evaluador lo re-sella por model_copy.
_DEFAULT_SEGMENT: str = "ALL"
# Mínimo técnico por defecto: un contraste con < 2 observaciones no tiene varianza/potencia. Es piso
# de computabilidad, no política supervisora; el evaluador puede subirlo desde la config.
_DEFAULT_MIN_OBS: int = 2
# Columnas internas del frame efímero que reusa el kernel binomial/Jeffreys de calibration_tests.
_PD_SEGMENT_COL: str = "segment"
_PD_COL: str = "pd"
_PD_TARGET_COL: str = "target"


def ttest_realised_vs_predicted(
    realised: np.ndarray,
    predicted: np.ndarray,
    *,
    one_sided: bool = True,
    alpha: float = 0.05,
    parameter: BacktestParameter = "lgd",
    segment: str = _DEFAULT_SEGMENT,
    min_obs: int = _DEFAULT_MIN_OBS,
) -> BacktestRecord:
    """T-test pareado realizado-vs-estimado para LGD/EAD, unilateral por defecto (SDD-22 §3.4).

    Sobre el error ``e_i = realizado_i - estimado_i`` calcula la media ``e_bar``, la desviación
    muestral ``s`` (``ddof=1``) y el estadístico ``T = sqrt(N)*e_bar/s``; el p-valor usa la ``t`` de
    Student con ``N-1`` gl (converge a la normal para ``N`` grande). Con ``one_sided=True`` (H0: el
    parámetro no está subestimado, ``e_bar <= 0``) el p-valor es la cola superior ``t.sf(T, N-1)``;
    bilateral usa ``2*t.sf(abs(T), N-1)``. Verdicto ``fail`` si ``p_value < alpha``. PD no aplica
    (usa :func:`binomial_realised_vs_predicted`, D-VAL-6): ``parameter`` en ``{'lgd', 'ead'}``.

    Con ``N < min_obs`` o degenerada (``N < 2`` o ``s = 0``) el verdicto es ``not_evaluable``: §8
    no afirma significancia con ellas, pero reporta el estadístico/p-valor si son computables
    (``N >= 2`` con ``s > 0``). FALTA-DATO-VAL-1: la forma ECB exacta queda por verificar.
    """
    if parameter not in ("lgd", "ead"):
        raise BacktestError(
            "El t-test de backtesting aplica solo a LGD/EAD; "
            f"parameter observado={parameter!r} (PD usa binomial/Jeffreys, D-VAL-6)."
        )
    resolved_segment = _validate_segment(segment)
    resolved_alpha = _as_open_unit(alpha, label="alpha")
    resolved_min_obs = _validate_min_obs(min_obs)
    realised_vec, predicted_vec = _validate_pair(realised, predicted)
    n = int(realised_vec.shape[0])

    errors = realised_vec - predicted_vec
    predicted_mean = _normalize_float(float(np.mean(predicted_vec)))
    realised_mean = _normalize_float(float(np.mean(realised_vec)))

    computed = _student_t_test(errors, n, one_sided=one_sided) if n >= 2 else None
    decision: BacktestDecision
    if computed is None:
        statistic, p_value = 0.0, 1.0
        decision = "not_evaluable"
    else:
        statistic, p_value = computed
        if n < resolved_min_obs:
            decision = "not_evaluable"
        elif p_value < resolved_alpha:
            decision = "fail"
        else:
            decision = "pass"

    return BacktestRecord(
        parameter=parameter,
        segment=resolved_segment,
        n=n,
        predicted_mean=predicted_mean,
        realised_mean=realised_mean,
        test="t_test",
        statistic=statistic,
        p_value=p_value,
        alpha=resolved_alpha,
        one_sided=one_sided,
        decision=decision,
    )


def binomial_realised_vs_predicted(
    realised: np.ndarray,
    predicted: np.ndarray,
    *,
    segment: str = _DEFAULT_SEGMENT,
    test: str = "jeffreys",
    alpha: float = 0.05,
    min_obs: int = _DEFAULT_MIN_OBS,
) -> BacktestRecord:
    """Backtesting de PD por segmento con el contraste binomial/Jeffreys (SDD-22 §3.4, D-VAL-6).

    Para un segmento con ``N`` operaciones, ``D`` defaults (``realised`` binario 0/1) y PD media
    estimada ``p_hat`` (``predicted`` en ``[0, 1]``), *reutiliza* ``binomial_by_grade`` de
    ``calibration_tests`` para el p-valor (binomial exacto o posterior de Jeffreys
    ``Beta(D+1/2, N-D+1/2)``): PD nunca usa t-test. El estadístico publicado es la desviación
    estandarizada ``z = (D - N*p_hat)/sqrt(N*p_hat*(1-p_hat))``; el p-valor es el reusado del
    kernel. Verdicto ``fail`` si ``p_value < alpha``; el contraste es unilateral hacia la
    subestimación de PD.

    Con varianza binomial cero (``p_hat`` en ``{0, 1}``) el ``z`` es indefinido -> ``not_evaluable``
    con estadístico ``0.0`` y p-valor neutro ``1.0`` (nunca división por cero ni el borde del
    Jeffreys mal orientado). Con ``N < min_obs`` el verdicto es ``not_evaluable`` reportando igual
    el estadístico y el p-valor (§8).
    """
    if test not in ("binomial", "jeffreys"):
        raise BacktestError(
            f"El backtesting de PD usa 'binomial' o 'jeffreys'; test observado={test!r}."
        )
    resolved_test = cast(PdTest, test)
    resolved_segment = _validate_segment(segment)
    resolved_alpha = _as_open_unit(alpha, label="alpha")
    resolved_min_obs = _validate_min_obs(min_obs)
    realised_vec, predicted_vec = _validate_pair(realised, predicted)
    n = int(realised_vec.shape[0])

    # Reúso del kernel B22.3: valida binario/[0,1] y computa el p-valor binomial/Jeffreys (no se
    # reimplementa). Un único segmento => un único GradeBinomialRecord.
    frame = pd.DataFrame(
        {
            _PD_SEGMENT_COL: [resolved_segment] * n,
            _PD_COL: predicted_vec,
            _PD_TARGET_COL: realised_vec,
        }
    )
    grade_record = binomial_by_grade(
        frame,
        grade_col=_PD_SEGMENT_COL,
        pd_col=_PD_COL,
        target_col=_PD_TARGET_COL,
        test=resolved_test,
        alpha=resolved_alpha,
    )[0]

    predicted_mean = grade_record.expected_pd
    realised_mean = grade_record.observed_dr
    z_stat = _standardized_deviation(grade_record.observed_defaults, grade_record.n, predicted_mean)

    decision: BacktestDecision
    if z_stat is None:
        statistic, p_value = 0.0, 1.0
        decision = "not_evaluable"
    else:
        statistic, p_value = z_stat, grade_record.p_value
        if grade_record.n < resolved_min_obs:
            decision = "not_evaluable"
        elif p_value < resolved_alpha:
            decision = "fail"
        else:
            decision = "pass"

    return BacktestRecord(
        parameter="pd",
        segment=resolved_segment,
        n=grade_record.n,
        predicted_mean=predicted_mean,
        realised_mean=realised_mean,
        test=resolved_test,
        statistic=statistic,
        p_value=p_value,
        alpha=resolved_alpha,
        one_sided=True,
        decision=decision,
    )


def _student_t_test(errors: np.ndarray, n: int, *, one_sided: bool) -> tuple[float, float] | None:
    """Estadístico ``T = sqrt(N)*e_bar/s`` y p-valor ``t`` de Student; ``None`` si ``s`` no sirve.

    Se llama solo con ``n >= 2`` (``ddof=1`` exige dos observaciones). La **degeneración se ve en
    el ORIGEN**, comparando ``max(errors) == min(errors)`` (dispersión real nula), **no** en la
    ``np.std`` derivada: con errores estructuralmente idénticos la resta de la media deja un residuo
    ~1e-17 por *cancelación catastrófica* (y su reducción varía por arquitectura/BLAS). Confiar en
    ``std <= 0`` daría un veredicto REGULATORIO ``fail`` desde puro ruido de punto flotante y NO
    reproducible cross-plataforma (SDD-22 §8). El ``max``/``min`` es selección exacta, sin reducción
    sensible: dos segmentos con dispersión real cero reciben SIEMPRE el mismo veredicto
    ``not_evaluable``, sea el error representable o no. ``s`` no finito (desborde a inf) o ``s``
    subdesbordado a ``0`` con rango no nulo también degenera a ``None``.
    """
    error_max = float(np.max(errors))
    error_min = float(np.min(errors))
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        sample_std = float(np.std(errors, ddof=1))
        mean_error = float(np.mean(errors))
    if error_max == error_min or not math.isfinite(sample_std) or sample_std <= 0.0:
        return None
    t_stat = math.sqrt(n) * mean_error / sample_std
    stats = _import_scipy_stats()
    degrees_of_freedom = n - 1
    if one_sided:
        p_value = float(stats.t.sf(t_stat, degrees_of_freedom))
    else:
        p_value = 2.0 * float(stats.t.sf(abs(t_stat), degrees_of_freedom))
    p_value = min(1.0, max(0.0, p_value))
    return _normalize_float(t_stat), _normalize_float(p_value)


def _standardized_deviation(defaults: int, n: int, p_hat: float) -> float | None:
    """Desviación ``z = (D - N*p_hat)/sqrt(N*p_hat*(1-p_hat))``; ``None`` si degenera (§8).

    Estadístico descriptivo del backtesting de PD (aproximación normal). El p-valor del contraste
    lo aporta el kernel reusado; este ``z`` solo resume la magnitud de la desviación. La
    degeneración se decide en el ORIGEN: ``p_hat`` fuera del intervalo abierto ``(0, 1)`` anula la
    varianza binomial ``N*p_hat*(1-p_hat)`` (mismo criterio robusto que el t-test, decidido en el
    parámetro, no en la varianza derivada). A diferencia del t-test, la varianza binomial es un
    **producto** de
    positivos (sin resta de la media): no sufre cancelación catastrófica, así que el chequeo en el
    origen es equivalente a ``variance <= 0`` para los insumos válidos y se adopta por consistencia.
    """
    if not 0.0 < p_hat < 1.0:
        return None
    variance = n * p_hat * (1.0 - p_hat)
    z = (defaults - n * p_hat) / math.sqrt(variance)
    return _normalize_float(float(z))


def _validate_pair(realised: Any, predicted: Any) -> tuple[np.ndarray, np.ndarray]:
    """Valida y copia ``(realised, predicted)``: mismo largo, 1-D, finitos y no vacíos."""
    r = _as_float_vector(realised, label="realised")
    p = _as_float_vector(predicted, label="predicted")
    if r.shape[0] != p.shape[0]:
        raise ValidationDataError(
            f"realised y predicted deben tener el mismo largo; {r.shape[0]} vs {p.shape[0]}."
        )
    if r.shape[0] == 0:
        raise ValidationDataError("realised y predicted no pueden estar vacíos.")
    return r, p


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


def _validate_segment(segment: str) -> str:
    """Valida que el segmento/cartera no esté vacío."""
    if not segment.strip():
        raise BacktestError("segment no puede estar vacío.")
    return segment


def _validate_min_obs(min_obs: int) -> int:
    """Valida que el mínimo técnico de observaciones sea al menos 1."""
    if min_obs < 1:
        raise BacktestError(f"min_obs debe ser >= 1; min_obs={min_obs}.")
    return min_obs


def _as_open_unit(value: float, *, label: str) -> float:
    """Valida que un alfa/corte sea un número finito en el intervalo abierto ``(0, 1)``."""
    number = float(value)
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        raise BacktestError(f"{label} debe ser un número finito en (0, 1); valor={value!r}.")
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
