"""Tests de los kernels de calibración de ``validation`` (SDD-22 §3.2/§4/§7/§8).

Golden values calculados de forma independiente (formula HL a mano, ``scipy`` aparte para el
p-valor) y cobertura de robustez: grupos/grados degenerados a ``not_evaluable`` sin division por
cero, ``z`` asintotico ``None`` con varianza cero, semaforo monotono e import perezoso de ``scipy``.
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

import nikodym.validation.calibration_tests as ct
from nikodym.core.exceptions import MissingDependencyError
from nikodym.validation.calibration_tests import (
    binomial_by_grade,
    brier_score,
    hosmer_lemeshow,
    traffic_light,
)
from nikodym.validation.exceptions import CalibrationTestError, ValidationDataError

# ─────────────────────────── Hosmer-Lemeshow ───────────────────────────


def test_hosmer_lemeshow_golden_calibracion_perfecta() -> None:
    # 10 deciles iguales: n_g=10, mean_pd=0.1, O_g=1 -> termino (1 - 10*0.1)^2/(10*0.1*0.9) = 0.
    pd_pred = np.full(100, 0.1)
    y_true = np.tile(np.array([1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), 10)

    record = hosmer_lemeshow(y_true, pd_pred, n_groups=10)

    assert record.test == "hosmer_lemeshow"
    assert record.n_groups == 10
    assert record.degrees_of_freedom == 8
    assert record.statistic == 0.0
    assert math.copysign(1.0, record.statistic) == 1.0  # -0.0 → 0.0
    assert record.p_value == pytest.approx(1.0)
    assert record.alpha == 0.05
    assert record.decision == "pass"


def test_hosmer_lemeshow_golden_miscalibrado_rechaza() -> None:
    # 10 deciles iguales: n_g=10, mean_pd=0.2, O_g=4 -> termino (4 - 2)^2/(10*0.2*0.8) = 2.5; HL=25.
    pd_pred = np.full(100, 0.2)
    y_true = np.tile(np.array([1.0, 1, 1, 1, 0, 0, 0, 0, 0, 0]), 10)

    record = hosmer_lemeshow(y_true, pd_pred, n_groups=10)

    assert record.statistic == pytest.approx(25.0)
    assert record.degrees_of_freedom == 8
    assert record.p_value == pytest.approx(float(stats.chi2.sf(25.0, 8)))
    assert record.p_value < 0.05
    assert record.decision == "fail"


def test_hosmer_lemeshow_golden_ordena_por_pd_predicha() -> None:
    # Deciles con PD y defaults distintos, en orden inverso para ejercer el ordenamiento.
    levels = [0.02, 0.04, 0.06, 0.10, 0.15, 0.22, 0.30, 0.42, 0.55, 0.75]
    defaults = [0, 1, 1, 2, 2, 3, 3, 4, 5, 7]
    pd_blocks: list[float] = []
    y_blocks: list[float] = []
    for level, o_g in zip(levels, defaults, strict=True):
        pd_blocks.extend([level] * 10)
        y_blocks.extend([1.0] * o_g + [0.0] * (10 - o_g))
    pd_pred = np.array(pd_blocks)[::-1].copy()
    y_true = np.array(y_blocks)[::-1].copy()

    expected_hl = sum(
        (o_g - 10 * level) ** 2 / (10 * level * (1 - level))
        for level, o_g in zip(levels, defaults, strict=True)
    )
    record = hosmer_lemeshow(y_true, pd_pred, n_groups=10)

    assert record.statistic == pytest.approx(expected_hl)
    assert record.degrees_of_freedom == 8
    assert record.n_groups == 10
    assert record.p_value == pytest.approx(float(stats.chi2.sf(expected_hl, 8)))


def test_hosmer_lemeshow_not_evaluable_grupo_degenerado() -> None:
    # El decil de menor PD queda con p̄_g = 0 → denominador 0 → not_evaluable (nunca div/0).
    pd_pred = np.concatenate([np.zeros(10), np.full(90, 0.3)])
    y_true = np.concatenate([np.zeros(10), np.tile(np.array([1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), 9)])

    record = hosmer_lemeshow(y_true, pd_pred, n_groups=10)

    assert record.decision == "not_evaluable"
    assert record.p_value is None
    assert record.alpha is None
    assert record.statistic == 0.0
    assert record.n_groups == 10
    assert record.degrees_of_freedom == 8


def test_hosmer_lemeshow_not_evaluable_muestra_pequena() -> None:
    # 5 observaciones y 10 grupos → grupos vacíos (n_g = 0) → not_evaluable.
    record = hosmer_lemeshow(
        np.array([1.0, 0.0, 1.0, 0.0, 1.0]),
        np.array([0.1, 0.2, 0.3, 0.4, 0.5]),
        n_groups=10,
    )

    assert record.decision == "not_evaluable"
    assert record.p_value is None


def test_hosmer_lemeshow_not_evaluable_estadistico_no_finito() -> None:
    # PD subnormal → denominador > 0 pero el término desborda a inf → estadístico no finito.
    pd_pred = np.full(100, 5e-324)
    y_true = np.tile(np.array([1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), 10)

    record = hosmer_lemeshow(y_true, pd_pred, n_groups=10)

    assert record.decision == "not_evaluable"
    assert record.p_value is None


def test_hosmer_lemeshow_rechaza_n_groups_menor_a_tres() -> None:
    with pytest.raises(CalibrationTestError, match="n_groups"):
        hosmer_lemeshow(np.array([1.0, 0.0]), np.array([0.5, 0.5]), n_groups=2)


# ─────────────────────────────── Brier ─────────────────────────────────


def test_brier_score_golden() -> None:
    # ((0.9-1)^2 + (0.2-0)^2 + (0.7-1)^2 + (0.4-0)^2) / 4 = (0.01+0.04+0.09+0.16)/4 = 0.075.
    record = brier_score(np.array([1.0, 0.0, 1.0, 0.0]), np.array([0.9, 0.2, 0.7, 0.4]))

    assert record.test == "brier"
    assert record.statistic == pytest.approx(0.075)
    assert record.p_value is None
    assert record.n_groups is None
    assert record.degrees_of_freedom is None
    assert record.alpha is None
    assert record.decision == "not_evaluable"


def test_brier_score_normaliza_menos_cero() -> None:
    record = brier_score(np.array([1.0, 0.0]), np.array([1.0, 0.0]))

    assert record.statistic == 0.0
    assert math.copysign(1.0, record.statistic) == 1.0


# ─────────────────────────── binomial / Jeffreys ───────────────────────


def _single_grade_frame(
    pd_value: float, n: int, defaults: int, *, grade: str = "A"
) -> pd.DataFrame:
    target = [1.0] * defaults + [0.0] * (n - defaults)
    return pd.DataFrame({"grade": [grade] * n, "pd": [pd_value] * n, "target": target})


def test_binomial_by_grade_golden_binomial() -> None:
    frame = _single_grade_frame(0.05, 100, 10)

    records = binomial_by_grade(
        frame, grade_col="grade", pd_col="pd", target_col="target", test="binomial", alpha=0.05
    )

    assert len(records) == 1
    record = records[0]
    assert record.grade == "A"
    assert record.n == 100
    assert record.observed_defaults == 10
    assert record.expected_pd == pytest.approx(0.05)
    assert record.observed_dr == pytest.approx(0.10)
    assert record.test == "binomial"
    assert record.alpha == 0.05
    assert record.p_value == pytest.approx(
        float(stats.binomtest(10, 100, 0.05, alternative="greater").pvalue)
    )
    assert record.z_stat == pytest.approx((10 - 5) / math.sqrt(100 * 0.05 * 0.95))
    assert record.traffic_light == traffic_light(record.p_value, green_alpha=0.05, red_alpha=0.01)
    assert record.traffic_light == "amber"


def test_binomial_by_grade_golden_jeffreys() -> None:
    frame = _single_grade_frame(0.05, 100, 10)

    records = binomial_by_grade(
        frame, grade_col="grade", pd_col="pd", target_col="target", test="jeffreys", alpha=0.05
    )

    record = records[0]
    assert record.test == "jeffreys"
    assert record.z_stat is None
    assert record.p_value == pytest.approx(float(stats.beta.cdf(0.05, 10 + 0.5, 100 - 10 + 0.5)))


def test_binomial_by_grade_defaults_cero() -> None:
    frame = _single_grade_frame(0.02, 50, 0, grade="Z")

    binomial = binomial_by_grade(
        frame, grade_col="grade", pd_col="pd", target_col="target", test="binomial"
    )[0]
    assert binomial.observed_defaults == 0
    assert binomial.p_value == pytest.approx(1.0)  # P(X ≥ 0) = 1
    assert binomial.z_stat == pytest.approx((0 - 50 * 0.02) / math.sqrt(50 * 0.02 * 0.98))
    assert binomial.traffic_light == "green"

    jeffreys = binomial_by_grade(
        frame, grade_col="grade", pd_col="pd", target_col="target", test="jeffreys"
    )[0]
    assert jeffreys.p_value == pytest.approx(float(stats.beta.cdf(0.02, 0.5, 50.5)))
    assert jeffreys.z_stat is None


def test_binomial_by_grade_z_none_con_varianza_cero() -> None:
    # p_hat = 0 -> varianza N*p_hat*(1-p_hat) = 0 -> z asintotico None (nunca NaN).
    frame = _single_grade_frame(0.0, 5, 0, grade="F")

    record = binomial_by_grade(
        frame, grade_col="grade", pd_col="pd", target_col="target", test="binomial"
    )[0]

    assert record.expected_pd == 0.0
    assert record.z_stat is None
    assert record.p_value == pytest.approx(1.0)
    assert record.traffic_light == "green"


def test_binomial_by_grade_respeta_orden_de_aparicion() -> None:
    frame = pd.DataFrame(
        {
            "grade": ["B"] * 3 + ["A"] * 4 + ["C"] * 2,
            "pd": [0.1] * 9,
            "target": [0.0] * 9,
        }
    )

    records = binomial_by_grade(frame, grade_col="grade", pd_col="pd", target_col="target")

    assert [record.grade for record in records] == ["B", "A", "C"]


def test_binomial_by_grade_rechaza_test_invalido() -> None:
    frame = _single_grade_frame(0.05, 10, 1)
    with pytest.raises(CalibrationTestError, match="binomial"):
        binomial_by_grade(frame, grade_col="grade", pd_col="pd", target_col="target", test="chi2")


def test_binomial_by_grade_rechaza_alpha_fuera_de_rango() -> None:
    frame = _single_grade_frame(0.05, 10, 1)
    with pytest.raises(CalibrationTestError, match="alpha"):
        binomial_by_grade(frame, grade_col="grade", pd_col="pd", target_col="target", alpha=0.0)


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (pd.DataFrame({"grade": ["A"], "pd": [0.1]}), "columna 'target'"),
        (pd.DataFrame({"grade": ["A"] * 0, "pd": [], "target": []}), "frame vacío"),
        (
            pd.DataFrame({"grade": ["A", None], "pd": [0.1, 0.2], "target": [0.0, 1.0]}),
            "no admite valores nulos",
        ),
        (
            pd.DataFrame({"grade": ["A", "A"], "pd": [0.1, 1.5], "target": [0.0, 1.0]}),
            r"\[0, 1\]",
        ),
        (
            pd.DataFrame({"grade": ["A", "A"], "pd": [0.1, np.inf], "target": [0.0, 1.0]}),
            "finitos",
        ),
        (
            pd.DataFrame({"grade": ["A", "A"], "pd": [0.1, 0.2], "target": [0.0, 2.0]}),
            "binaria",
        ),
        (
            pd.DataFrame({"grade": ["A", "A"], "pd": ["x", "y"], "target": [0.0, 1.0]}),
            "float64-compatible",
        ),
    ],
)
def test_binomial_by_grade_rechaza_frames_invalidos(frame: pd.DataFrame, expected: str) -> None:
    with pytest.raises(ValidationDataError, match=expected):
        binomial_by_grade(frame, grade_col="grade", pd_col="pd", target_col="target")


def test_binomial_by_grade_rechaza_entrada_no_dataframe() -> None:
    with pytest.raises(ValidationDataError, match=r"pandas\.DataFrame"):
        binomial_by_grade([1, 2, 3], grade_col="grade", pd_col="pd", target_col="target")  # type: ignore[arg-type]


# ─────────────────────────────── semáforo ──────────────────────────────


def test_traffic_light_mapeo_y_bordes() -> None:
    assert traffic_light(0.10, green_alpha=0.05, red_alpha=0.01) == "green"
    assert traffic_light(0.05, green_alpha=0.05, red_alpha=0.01) == "green"
    assert traffic_light(0.03, green_alpha=0.05, red_alpha=0.01) == "amber"
    assert traffic_light(0.01, green_alpha=0.05, red_alpha=0.01) == "amber"
    assert traffic_light(0.009, green_alpha=0.05, red_alpha=0.01) == "red"
    assert traffic_light(0.0, green_alpha=0.05, red_alpha=0.01) == "red"


def test_traffic_light_monotonia() -> None:
    rank = {"green": 2, "amber": 1, "red": 0}
    p_values = [1.0, 0.5, 0.06, 0.05, 0.04, 0.02, 0.01, 0.005, 0.0]
    ranks = [rank[traffic_light(p, green_alpha=0.05, red_alpha=0.01)] for p in p_values]

    assert all(ranks[i] >= ranks[i + 1] for i in range(len(ranks) - 1))


def test_traffic_light_rechaza_entradas_invalidas() -> None:
    with pytest.raises(CalibrationTestError, match="p_value"):
        traffic_light(math.nan, green_alpha=0.05, red_alpha=0.01)
    with pytest.raises(CalibrationTestError, match="p_value"):
        traffic_light(1.5, green_alpha=0.05, red_alpha=0.01)
    with pytest.raises(CalibrationTestError, match="green_alpha"):
        traffic_light(0.5, green_alpha=1.0, red_alpha=0.01)
    with pytest.raises(CalibrationTestError, match="red_alpha"):
        traffic_light(0.5, green_alpha=0.05, red_alpha=0.0)
    with pytest.raises(CalibrationTestError, match="red_alpha < green_alpha"):
        traffic_light(0.5, green_alpha=0.01, red_alpha=0.05)


# ────────────────────────── validación de arreglos ─────────────────────


@pytest.mark.parametrize(
    ("y_true", "pd_pred", "expected"),
    [
        (np.array([1.0, 0.0]), np.array([0.5]), "mismo largo"),
        (np.array([]), np.array([]), "vacíos"),
        (np.array([2.0, 0.0]), np.array([0.5, 0.5]), "binario"),
        (np.array([1.0, 0.0]), np.array([1.5, 0.5]), r"\[0, 1\]"),
        (np.array([[1.0], [0.0]]), np.array([[0.5], [0.5]]), "1-D"),
        (np.array([1.0, 0.0]), np.array([np.nan, 0.5]), "finitos"),
        (np.array([1.0, 0.0]), np.array(["a", "b"]), "float64-compatible"),
    ],
)
def test_brier_score_rechaza_arreglos_invalidos(
    y_true: np.ndarray, pd_pred: np.ndarray, expected: str
) -> None:
    with pytest.raises(ValidationDataError, match=expected):
        brier_score(y_true, pd_pred)


# ────────────────────── import perezoso de scipy ───────────────────────


def test_hosmer_lemeshow_error_accionable_si_falta_scipy(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("scipy"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ct.importlib, "import_module", fake_import)
    y_true = np.tile(np.array([1.0, 1, 1, 1, 0, 0, 0, 0, 0, 0]), 10)
    pd_pred = np.full(100, 0.2)

    with pytest.raises(MissingDependencyError, match=r"nikodym\[scoring\]"):
        hosmer_lemeshow(y_true, pd_pred)


def test_import_calibration_tests_no_arrastra_scipy_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.validation.calibration_tests as ct;"
        "blocked=[m for m in ('scipy','sklearn','statsmodels') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert callable(ct.hosmer_lemeshow) and callable(ct.brier_score)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
