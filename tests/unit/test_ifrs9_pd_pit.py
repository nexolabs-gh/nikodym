"""Tests de ``provisioning.ifrs9.pd_pit``: Vasicek PIT y agregación marginal->horizonte.

Goldens verificables a mano (SDD-16 §11): transformación PIT monofactorial con orientación
``Z<0 => PD sube`` / ``Z>0 => PD baja`` y efecto Jensen (``Z=0 != PD_TTC``); derivación de PD 12m /
PD lifetime desde la term-structure tidy de PD marginal. Cobertura de todos los caminos de error
(``IfrsPdError``) y de los guards de dependencia perezosa (``MissingDependencyError``).
"""

from __future__ import annotations

import importlib
from typing import Any

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

import nikodym.provisioning.ifrs9.pd_pit as pd_pit_module
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9 import marginal_to_horizon, vasicek_pit
from nikodym.provisioning.ifrs9.exceptions import IfrsPdError

# ─────────────────────────── vasicek_pit: golden y orientación ───────────────────────────


def _vasicek_ref(pd_ttc: np.ndarray, *, rho: float, z: np.ndarray) -> np.ndarray:
    """Fórmula de referencia recomputada con scipy (mismo clip epsilon que el módulo)."""
    clipped = np.clip(pd_ttc, 1e-12, 1.0 - 1e-12)
    argument = (norm.ppf(clipped) - np.sqrt(rho) * z) / np.sqrt(1.0 - rho)
    return np.asarray(norm.cdf(argument), dtype=np.float64)


def test_vasicek_pit_golden_orientacion_y_jensen() -> None:
    pd_ttc = np.array([0.02, 0.02, 0.02])
    z = np.array([-3.0, 0.0, 3.0])
    result = vasicek_pit(pd_ttc, rho=0.15, z=z)

    # Golden numérico anclado (SDD-16 §11): recesión sube la PD, expansión la baja.
    np.testing.assert_allclose(result[0], 0.16674, rtol=1e-3)
    np.testing.assert_allclose(result[1], 0.012959, rtol=1e-3)
    np.testing.assert_allclose(result[2], 0.0002438, rtol=1e-2)

    # Cross-check exacto contra la fórmula de referencia scipy a doble precisión.
    np.testing.assert_allclose(result, _vasicek_ref(pd_ttc, rho=0.15, z=z), rtol=1e-12, atol=0.0)

    # Orientación: Z<0 => PD sube ; Z>0 => PD baja.
    assert result[0] > result[1] > result[2]
    # Efecto Jensen: la PD PIT en Z=0 NO coincide con la PD TTC (0.02).
    assert not np.isclose(result[1], 0.02, rtol=1e-3)


def test_vasicek_pit_clip_en_bordes_no_produce_inf() -> None:
    result = vasicek_pit(np.array([0.0, 1.0]), rho=0.2, z=np.array([0.0, 0.0]))
    assert np.all(np.isfinite(result))
    assert np.all((result >= 0.0) & (result <= 1.0))


def test_vasicek_pit_normaliza_signo_de_cero() -> None:
    result = vasicek_pit(np.array([0.02]), rho=0.15, z=np.array([0.0]))
    # Ningún cero publicado conserva el signo negativo (reproducibilidad).
    assert not np.any(np.signbit(result) & (result == 0.0))


# ─────────────────────────── vasicek_pit: validaciones de entrada ───────────────────────────


@pytest.mark.parametrize("rho", [0.0, 1.0, -0.1, 1.5, float("nan"), float("inf")])
def test_vasicek_pit_rho_fuera_de_rango(rho: float) -> None:
    with pytest.raises(IfrsPdError, match="rho debe estar"):
        vasicek_pit(np.array([0.02]), rho=rho, z=np.array([0.0]))


@pytest.mark.parametrize("bad", [1.5, -0.1])
def test_vasicek_pit_pd_ttc_fuera_de_rango(bad: float) -> None:
    with pytest.raises(IfrsPdError, match="pd_ttc debe estar en"):
        vasicek_pit(np.array([bad]), rho=0.15, z=np.array([0.0]))


def test_vasicek_pit_pd_ttc_no_finita() -> None:
    with pytest.raises(IfrsPdError, match="pd_ttc debe contener"):
        vasicek_pit(np.array([np.nan]), rho=0.15, z=np.array([0.0]))


def test_vasicek_pit_z_no_finito() -> None:
    with pytest.raises(IfrsPdError, match="factor sistémico Z"):
        vasicek_pit(np.array([0.02]), rho=0.15, z=np.array([np.inf]))


# ─────────────────────────── vasicek_pit: validación de salida ───────────────────────────


class _FakeNorm:
    """Norm falso: ``ppf`` finito, ``cdf`` inyecta el valor patológico bajo prueba."""

    def __init__(self, cdf_value: float) -> None:
        self._cdf_value = cdf_value

    def ppf(self, x: Any) -> Any:
        return np.asarray(x, dtype=np.float64)

    def cdf(self, x: Any) -> Any:
        return np.full(np.shape(x), self._cdf_value, dtype=np.float64)


def test_vasicek_pit_salida_no_finita(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pd_pit_module, "_import_scipy_norm", lambda: _FakeNorm(np.nan))
    with pytest.raises(IfrsPdError, match="no es finita"):
        vasicek_pit(np.array([0.02]), rho=0.15, z=np.array([0.0]))


def test_vasicek_pit_salida_fuera_de_rango_sin_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pd_pit_module, "_import_scipy_norm", lambda: _FakeNorm(1.5))
    with pytest.raises(IfrsPdError, match="cayó fuera de"):
        vasicek_pit(np.array([0.02]), rho=0.15, z=np.array([0.0]))


# ─────────────────────────── marginal_to_horizon: golden ───────────────────────────


def test_marginal_to_horizon_golden_12m_y_lifetime() -> None:
    ts = pd.DataFrame(
        {"row_id": ["op1", "op1", "op1"], "period": [1, 2, 3], "pd_marginal": [0.10, 0.08, 0.05]}
    )
    out = marginal_to_horizon(ts, horizon_periods=1)

    assert list(out.columns) == ["row_id", "pd_12m", "pd_life"]
    assert len(out) == 1
    fila = out.iloc[0]
    assert fila["row_id"] == "op1"
    np.testing.assert_allclose(fila["pd_12m"], 0.10, rtol=1e-12)
    np.testing.assert_allclose(fila["pd_life"], 0.23, rtol=1e-12)


def test_marginal_to_horizon_horizonte_cubre_dos_periodos() -> None:
    ts = pd.DataFrame(
        {"row_id": ["op1", "op1", "op1"], "period": [1, 2, 3], "pd_marginal": [0.10, 0.08, 0.05]}
    )
    out = marginal_to_horizon(ts, horizon_periods=2)
    np.testing.assert_allclose(out.iloc[0]["pd_12m"], 0.18, rtol=1e-12)
    np.testing.assert_allclose(out.iloc[0]["pd_life"], 0.23, rtol=1e-12)


def test_marginal_to_horizon_agrupa_por_escenario() -> None:
    ts = pd.DataFrame(
        {
            "row_id": ["op1", "op1", "op1", "op1"],
            "scenario": ["base", "base", "adverso", "adverso"],
            "period": [1, 2, 1, 2],
            "pd_marginal": [0.10, 0.05, 0.20, 0.15],
        }
    )
    out = marginal_to_horizon(ts, horizon_periods=1)

    assert list(out.columns) == ["row_id", "scenario", "pd_12m", "pd_life"]
    assert len(out) == 2
    indexado = out.set_index("scenario")
    np.testing.assert_allclose(indexado.loc["base", "pd_12m"], 0.10, rtol=1e-12)
    np.testing.assert_allclose(indexado.loc["base", "pd_life"], 0.15, rtol=1e-12)
    np.testing.assert_allclose(indexado.loc["adverso", "pd_12m"], 0.20, rtol=1e-12)
    np.testing.assert_allclose(indexado.loc["adverso", "pd_life"], 0.35, rtol=1e-12)


def test_marginal_to_horizon_entidad_sin_periodo_dentro_del_horizonte() -> None:
    # op2 sólo tiene period=3; con horizonte 2 su PD_12m es 0 (sin períodos <= 2).
    ts = pd.DataFrame(
        {"row_id": ["op1", "op1", "op2"], "period": [1, 2, 3], "pd_marginal": [0.10, 0.08, 0.05]}
    )
    out = marginal_to_horizon(ts, horizon_periods=2).set_index("row_id")
    np.testing.assert_allclose(out.loc["op1", "pd_12m"], 0.18, rtol=1e-12)
    np.testing.assert_allclose(out.loc["op2", "pd_12m"], 0.0, rtol=1e-12)
    np.testing.assert_allclose(out.loc["op2", "pd_life"], 0.05, rtol=1e-12)
    assert not np.signbit(out.loc["op2", "pd_12m"])


def test_marginal_to_horizon_no_muta_la_entrada() -> None:
    ts = pd.DataFrame({"row_id": ["op1", "op1"], "period": [1, 2], "pd_marginal": [0.10, 0.05]})
    snapshot = ts.copy(deep=True)
    marginal_to_horizon(ts, horizon_periods=1)
    assert "_pd_marginal_12m" not in ts.columns
    pd.testing.assert_frame_equal(ts, snapshot)


# ─────────────────────────── marginal_to_horizon: validaciones ───────────────────────────


def test_marginal_to_horizon_horizonte_menor_a_uno() -> None:
    ts = pd.DataFrame({"row_id": ["op1"], "period": [1], "pd_marginal": [0.10]})
    with pytest.raises(IfrsPdError, match="horizon_periods debe ser"):
        marginal_to_horizon(ts, horizon_periods=0)


def test_marginal_to_horizon_columnas_faltantes() -> None:
    ts = pd.DataFrame({"row_id": ["op1"], "period": [1]})
    with pytest.raises(IfrsPdError, match="term_structure debe contener"):
        marginal_to_horizon(ts, horizon_periods=1)


@pytest.mark.parametrize("bad", [1.5, -0.1])
def test_marginal_to_horizon_pd_marginal_fuera_de_rango(bad: float) -> None:
    ts = pd.DataFrame({"row_id": ["op1"], "period": [1], "pd_marginal": [bad]})
    with pytest.raises(IfrsPdError, match="pd_marginal debe estar en"):
        marginal_to_horizon(ts, horizon_periods=1)


def test_marginal_to_horizon_pd_marginal_no_finita() -> None:
    ts = pd.DataFrame({"row_id": ["op1"], "period": [1], "pd_marginal": [np.inf]})
    with pytest.raises(IfrsPdError, match="pd_marginal debe contener"):
        marginal_to_horizon(ts, horizon_periods=1)


def test_marginal_to_horizon_period_menor_a_uno() -> None:
    ts = pd.DataFrame({"row_id": ["op1"], "period": [0], "pd_marginal": [0.10]})
    with pytest.raises(IfrsPdError, match="period debe ser un entero"):
        marginal_to_horizon(ts, horizon_periods=1)


def test_marginal_to_horizon_period_no_entero() -> None:
    ts = pd.DataFrame({"row_id": ["op1"], "period": [1.5], "pd_marginal": [0.10]})
    with pytest.raises(IfrsPdError, match="period debe ser un entero"):
        marginal_to_horizon(ts, horizon_periods=1)


def test_marginal_to_horizon_period_no_finito() -> None:
    ts = pd.DataFrame({"row_id": ["op1"], "period": [np.nan], "pd_marginal": [0.10]})
    with pytest.raises(IfrsPdError, match="period debe contener"):
        marginal_to_horizon(ts, horizon_periods=1)


def test_marginal_to_horizon_pd_lifetime_supera_uno() -> None:
    ts = pd.DataFrame({"row_id": ["op1", "op1"], "period": [1, 2], "pd_marginal": [0.6, 0.6]})
    with pytest.raises(IfrsPdError, match="PD lifetime acumulada superó 1"):
        marginal_to_horizon(ts, horizon_periods=1)


# ─────────────────────────── guards de dependencia perezosa ───────────────────────────


def test_vasicek_pit_scipy_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def block(name: str) -> Any:
        if name.startswith("scipy"):
            raise ModuleNotFoundError("No module named 'scipy'", name="scipy")
        return real_import(name)

    monkeypatch.setattr(pd_pit_module.importlib, "import_module", block)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        vasicek_pit(np.array([0.02]), rho=0.15, z=np.array([0.0]))


def test_vasicek_pit_numpy_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def block(name: str) -> Any:
        if name == "numpy":
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return real_import(name)

    monkeypatch.setattr(pd_pit_module.importlib, "import_module", block)
    with pytest.raises(MissingDependencyError, match="numpy"):
        vasicek_pit(np.array([0.02]), rho=0.15, z=np.array([0.0]))


def test_marginal_to_horizon_numpy_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    ts = pd.DataFrame({"row_id": ["op1"], "period": [1], "pd_marginal": [0.10]})
    real_import = importlib.import_module

    def block(name: str) -> Any:
        if name == "numpy":
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return real_import(name)

    monkeypatch.setattr(pd_pit_module.importlib, "import_module", block)
    with pytest.raises(MissingDependencyError, match="numpy"):
        marginal_to_horizon(ts, horizon_periods=1)
