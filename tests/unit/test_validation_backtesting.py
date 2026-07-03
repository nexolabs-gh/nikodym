"""Tests de los kernels de backtesting de ``validation`` (SDD-22 §3.4/§4/§7/§8).

Golden values calculados de forma independiente (``T = √N·ē/s`` a mano, ``scipy`` aparte para el
p-valor; ``z`` binomial a mano, p-valor reusado de ``calibration_tests``) y cobertura de robustez:
muestra pequeña o degenerada a ``not_evaluable`` sin división por cero, PD por binomial/Jeffreys
(nunca t-test), verdicto pass/fail e import perezoso de ``scipy``.
"""

from __future__ import annotations

import importlib
import math
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from scipy import stats

import nikodym.validation.backtesting as bt
from nikodym.core.exceptions import MissingDependencyError
from nikodym.validation.backtesting import (
    binomial_realised_vs_predicted,
    ttest_realised_vs_predicted,
)
from nikodym.validation.exceptions import BacktestError, ValidationDataError

# ─────────────────────────── t-test LGD/EAD ────────────────────────────


def test_ttest_golden_subestimacion_rechaza() -> None:
    # errores e = realizado - estimado = [0.1, 0.2, 0.3, 0.4]; ē=0.25, s=std(ddof=1), T=√4·ē/s.
    realised = np.array([0.5, 0.6, 0.7, 0.8])
    predicted = np.full(4, 0.4)
    errors = realised - predicted
    expected_t = math.sqrt(4) * float(np.mean(errors)) / float(np.std(errors, ddof=1))
    expected_p = float(stats.t.sf(expected_t, 3))

    record = ttest_realised_vs_predicted(realised, predicted, parameter="lgd", segment="cartera")

    assert record.parameter == "lgd"
    assert record.segment == "cartera"
    assert record.test == "t_test"
    assert record.n == 4
    assert record.one_sided is True
    assert record.predicted_mean == pytest.approx(0.4)
    assert record.realised_mean == pytest.approx(0.65)
    assert record.statistic == pytest.approx(expected_t)
    assert record.statistic == pytest.approx(3.8729833462074166)
    assert record.p_value == pytest.approx(expected_p)
    assert record.alpha == 0.05
    assert record.decision == "fail"  # el realizado supera al estimado → subestimación


def test_ttest_golden_sobreestimacion_aprueba() -> None:
    # e = [-0.1, -0.2, -0.3, -0.4]; ē<0 → cola superior ~1 → no hay subestimación → pass.
    realised = np.array([0.3, 0.2, 0.1, 0.0])
    predicted = np.full(4, 0.4)
    errors = realised - predicted
    expected_t = math.sqrt(4) * float(np.mean(errors)) / float(np.std(errors, ddof=1))

    record = ttest_realised_vs_predicted(realised, predicted, parameter="ead")

    assert record.parameter == "ead"
    assert record.statistic == pytest.approx(expected_t)
    assert record.statistic < 0.0
    assert record.p_value == pytest.approx(float(stats.t.sf(expected_t, 3)))
    assert record.decision == "pass"


def test_ttest_bilateral_usa_dos_colas() -> None:
    realised = np.array([0.5, 0.6, 0.7, 0.8])
    predicted = np.full(4, 0.4)
    errors = realised - predicted
    expected_t = math.sqrt(4) * float(np.mean(errors)) / float(np.std(errors, ddof=1))
    expected_p = 2.0 * float(stats.t.sf(abs(expected_t), 3))

    record = ttest_realised_vs_predicted(realised, predicted, one_sided=False)

    assert record.one_sided is False
    assert record.statistic == pytest.approx(expected_t)
    assert record.p_value == pytest.approx(expected_p)
    assert record.decision == "fail"


def test_ttest_normaliza_menos_cero() -> None:
    # errores simétricos → ē=0 → T=0; el estadístico publicado normaliza -0.0 a 0.0.
    realised = np.array([0.3, 0.5])
    predicted = np.array([0.5, 0.3])

    record = ttest_realised_vs_predicted(realised, predicted)

    assert record.statistic == 0.0
    assert math.copysign(1.0, record.statistic) == 1.0
    assert record.p_value == pytest.approx(0.5)
    assert record.decision == "pass"


def test_ttest_muestra_pequena_not_evaluable_reporta_estadistico() -> None:
    # N=3 computable pero bajo el mínimo técnico → not_evaluable reportando igual T y p-valor (§8).
    realised = np.array([0.5, 0.6, 0.7])
    predicted = np.full(3, 0.4)
    errors = realised - predicted
    expected_t = math.sqrt(3) * float(np.mean(errors)) / float(np.std(errors, ddof=1))

    record = ttest_realised_vs_predicted(realised, predicted, min_obs=5)

    assert record.decision == "not_evaluable"
    assert record.statistic == pytest.approx(expected_t)
    assert record.p_value == pytest.approx(float(stats.t.sf(expected_t, 2)))


def test_ttest_una_observacion_not_evaluable() -> None:
    # N=1 → sin desviación muestral (ddof=1) → not_evaluable con estadístico/p-valor neutros.
    record = ttest_realised_vs_predicted(np.array([0.5]), np.array([0.4]))

    assert record.n == 1
    assert record.decision == "not_evaluable"
    assert record.statistic == 0.0
    assert record.p_value == 1.0


def test_ttest_desviacion_cero_not_evaluable() -> None:
    # Todos los errores iguales → s=0 → not_evaluable (nunca división por cero).
    record = ttest_realised_vs_predicted(np.array([0.5, 0.6]), np.array([0.4, 0.5]))

    assert record.decision == "not_evaluable"
    assert record.statistic == 0.0
    assert record.p_value == 1.0


def test_ttest_desviacion_no_finita_not_evaluable() -> None:
    # Errores simétricos gigantes: la media de realised es 0 (sin overflow), pero s desborda a inf
    # dentro del errstate del kernel → not_evaluable, jamás NaN/inf.
    record = ttest_realised_vs_predicted(
        np.array([1e308, -1e308]), np.array([0.0, 0.0]), parameter="ead"
    )

    assert record.decision == "not_evaluable"
    assert record.statistic == 0.0
    assert record.p_value == 1.0


def test_ttest_rechaza_parameter_pd() -> None:
    with pytest.raises(BacktestError, match="PD usa binomial/Jeffreys"):
        ttest_realised_vs_predicted(np.array([0.5, 0.6]), np.array([0.4, 0.4]), parameter="pd")


def test_ttest_rechaza_alpha_fuera_de_rango() -> None:
    with pytest.raises(BacktestError, match="alpha"):
        ttest_realised_vs_predicted(np.array([0.5, 0.6]), np.array([0.4, 0.4]), alpha=0.0)


def test_ttest_rechaza_segment_vacio() -> None:
    with pytest.raises(BacktestError, match="segment"):
        ttest_realised_vs_predicted(np.array([0.5, 0.6]), np.array([0.4, 0.4]), segment="  ")


def test_ttest_rechaza_min_obs_invalido() -> None:
    with pytest.raises(BacktestError, match="min_obs"):
        ttest_realised_vs_predicted(np.array([0.5, 0.6]), np.array([0.4, 0.4]), min_obs=0)


# ─────────────────────────── binomial / Jeffreys PD ────────────────────


def _pd_arrays(pd_value: float, n: int, defaults: int) -> tuple[np.ndarray, np.ndarray]:
    realised = np.array([1.0] * defaults + [0.0] * (n - defaults))
    predicted = np.full(n, pd_value)
    return realised, predicted


def test_binomial_pd_golden_subestimacion_rechaza() -> None:
    realised, predicted = _pd_arrays(0.05, 100, 10)
    expected_z = (10 - 100 * 0.05) / math.sqrt(100 * 0.05 * 0.95)
    expected_p = float(stats.binomtest(10, 100, 0.05, alternative="greater").pvalue)

    record = binomial_realised_vs_predicted(
        realised, predicted, segment="retail", test="binomial", alpha=0.05
    )

    assert record.parameter == "pd"
    assert record.segment == "retail"
    assert record.test == "binomial"
    assert record.n == 100
    assert record.one_sided is True
    assert record.predicted_mean == pytest.approx(0.05)
    assert record.realised_mean == pytest.approx(0.10)
    assert record.statistic == pytest.approx(expected_z)
    assert record.p_value == pytest.approx(expected_p)
    assert record.decision == ("fail" if expected_p < 0.05 else "pass")
    assert record.decision == "fail"


def test_binomial_pd_golden_jeffreys() -> None:
    realised, predicted = _pd_arrays(0.05, 100, 10)
    expected_z = (10 - 100 * 0.05) / math.sqrt(100 * 0.05 * 0.95)
    expected_p = float(stats.beta.cdf(0.05, 10 + 0.5, 100 - 10 + 0.5))

    record = binomial_realised_vs_predicted(realised, predicted, test="jeffreys")

    assert record.test == "jeffreys"
    assert record.statistic == pytest.approx(expected_z)
    assert record.p_value == pytest.approx(expected_p)
    assert record.decision == ("fail" if expected_p < 0.05 else "pass")


def test_binomial_pd_sobreestimacion_aprueba() -> None:
    # PD estimada 0.5 muy por encima de la tasa realizada 0.10 → sin subestimación → pass.
    realised, predicted = _pd_arrays(0.5, 100, 10)

    record = binomial_realised_vs_predicted(realised, predicted, test="jeffreys")

    assert record.statistic < 0.0
    assert record.p_value > 0.05
    assert record.decision == "pass"


def test_binomial_pd_varianza_cero_not_evaluable() -> None:
    # PD estimada 0 para todos → varianza binomial 0 → z indefinido → not_evaluable neutro.
    realised = np.zeros(10)
    predicted = np.zeros(10)

    record = binomial_realised_vs_predicted(realised, predicted, test="jeffreys")

    assert record.decision == "not_evaluable"
    assert record.statistic == 0.0
    assert record.p_value == 1.0
    assert record.predicted_mean == 0.0


def test_binomial_pd_muestra_pequena_not_evaluable_reporta() -> None:
    # N=100 bajo el mínimo técnico → not_evaluable reportando igual z y p-valor (§8).
    realised, predicted = _pd_arrays(0.05, 100, 10)
    expected_z = (10 - 100 * 0.05) / math.sqrt(100 * 0.05 * 0.95)
    expected_p = float(stats.beta.cdf(0.05, 10.5, 90.5))

    record = binomial_realised_vs_predicted(realised, predicted, test="jeffreys", min_obs=200)

    assert record.decision == "not_evaluable"
    assert record.statistic == pytest.approx(expected_z)
    assert record.p_value == pytest.approx(expected_p)


def test_binomial_pd_rechaza_test_invalido() -> None:
    realised, predicted = _pd_arrays(0.05, 10, 1)
    with pytest.raises(BacktestError, match="binomial"):
        binomial_realised_vs_predicted(realised, predicted, test="chi2")


def test_binomial_pd_rechaza_alpha_fuera_de_rango() -> None:
    realised, predicted = _pd_arrays(0.05, 10, 1)
    with pytest.raises(BacktestError, match="alpha"):
        binomial_realised_vs_predicted(realised, predicted, alpha=1.0)


def test_binomial_pd_rechaza_segment_vacio() -> None:
    realised, predicted = _pd_arrays(0.05, 10, 1)
    with pytest.raises(BacktestError, match="segment"):
        binomial_realised_vs_predicted(realised, predicted, segment="")


def test_binomial_pd_rechaza_min_obs_invalido() -> None:
    realised, predicted = _pd_arrays(0.05, 10, 1)
    with pytest.raises(BacktestError, match="min_obs"):
        binomial_realised_vs_predicted(realised, predicted, min_obs=-1)


def test_binomial_pd_rechaza_realizado_no_binario() -> None:
    # El realizado de PD debe ser 0/1; el kernel reusado lo valida.
    realised = np.array([0.0, 0.5, 1.0])
    predicted = np.full(3, 0.1)
    with pytest.raises(ValidationDataError, match="binaria"):
        binomial_realised_vs_predicted(realised, predicted)


def test_binomial_pd_rechaza_pd_fuera_de_rango() -> None:
    realised = np.array([0.0, 1.0])
    predicted = np.array([0.1, 1.5])
    with pytest.raises(ValidationDataError, match=r"\[0, 1\]"):
        binomial_realised_vs_predicted(realised, predicted)


# ─────────────────────── validación de arreglos ────────────────────────


@pytest.mark.parametrize(
    ("realised", "predicted", "expected"),
    [
        (np.array([0.5, 0.6]), np.array([0.4]), "mismo largo"),
        (np.array([]), np.array([]), "vacíos"),
        (np.array([[0.5], [0.6]]), np.array([[0.4], [0.4]]), "1-D"),
        (np.array([0.5, np.nan]), np.array([0.4, 0.4]), "finitos"),
        (np.array([0.5, 0.6]), np.array(["a", "b"]), "float64-compatible"),
    ],
)
def test_ttest_rechaza_arreglos_invalidos(
    realised: np.ndarray, predicted: np.ndarray, expected: str
) -> None:
    with pytest.raises(ValidationDataError, match=expected):
        ttest_realised_vs_predicted(realised, predicted)


def test_binomial_pd_rechaza_arreglos_invalidos() -> None:
    with pytest.raises(ValidationDataError, match="mismo largo"):
        binomial_realised_vs_predicted(np.array([0.0, 1.0]), np.array([0.1]))


# ────────────────────── import perezoso de scipy ───────────────────────


def test_ttest_error_accionable_si_falta_scipy(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("scipy"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(bt.importlib, "import_module", fake_import)

    with pytest.raises(MissingDependencyError, match=r"nikodym\[scoring\]"):
        ttest_realised_vs_predicted(np.array([0.5, 0.6, 0.7, 0.8]), np.full(4, 0.4))


def test_import_backtesting_no_arrastra_scipy_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.validation.backtesting as bt;"
        "blocked=[m for m in ('scipy','sklearn','statsmodels') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert callable(bt.ttest_realised_vs_predicted);"
        "assert callable(bt.binomial_realised_vs_predicted)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_ttest_no_muta_entradas() -> None:
    realised = np.array([0.5, 0.6, 0.7, 0.8])
    predicted = np.full(4, 0.4)
    realised_copy = realised.copy()
    predicted_copy = predicted.copy()

    ttest_realised_vs_predicted(realised, predicted)

    assert np.array_equal(realised, realised_copy)
    assert np.array_equal(predicted, predicted_copy)


def test_binomial_pd_no_muta_entradas() -> None:
    realised, predicted = _pd_arrays(0.05, 100, 10)
    realised_copy = realised.copy()
    predicted_copy = predicted.copy()

    binomial_realised_vs_predicted(realised, predicted)

    assert np.array_equal(realised, realised_copy)
    assert np.array_equal(predicted, predicted_copy)


def test_binomial_pd_acepta_dataframe_pandas_sin_mutar() -> None:
    # La construcción del frame efímero no debe depender del tipo exacto de entrada array-like.
    realised = pd.Series([1.0, 0.0, 1.0, 0.0]).to_numpy()
    predicted = pd.Series([0.2, 0.2, 0.2, 0.2]).to_numpy()

    record = binomial_realised_vs_predicted(realised, predicted, test="binomial")

    assert record.parameter == "pd"
    assert record.n == 4
