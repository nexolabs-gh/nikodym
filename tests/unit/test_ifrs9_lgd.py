"""Tests de ``provisioning.ifrs9.lgd``: motor LGD provided/beta/fractional/workout.

Goldens verificables a mano (SDD-16 §11): identidad ``LGD = 1 - recovery`` (``recovery=0.6`` →
``LGD=0.40``), enfoque ``workout`` reproduciendo ``1 - PV/EAD`` con descuento a EIR/contractual,
clip explícito floor/cap, y errores controlados (``IfrsLgdError``) ante columnas faltantes, valores
fuera de rango o no convergencia del ajuste de regresión. Cobertura de los guards de dependencia
perezosa (``MissingDependencyError``).
"""

from __future__ import annotations

import importlib
import warnings
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym.provisioning.ifrs9.lgd as lgd_module
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9 import LgdEngine
from nikodym.provisioning.ifrs9.config import IfrsLgdConfig
from nikodym.provisioning.ifrs9.exceptions import IfrsLgdError


def _regression_frame() -> pd.DataFrame:
    """Frame determinista de desarrollo LGD que converge sin warnings (beta/fractional)."""
    x = np.linspace(0.05, 1.0, 40)
    lgd = np.clip(0.3 + 0.2 * x + 0.02 * np.cos(x * 7.0), 0.15, 0.85)
    return pd.DataFrame({"x": x, "lgd": lgd})


# ─────────────────────────── provided: identidad y columna directa ───────────────────────────


def test_provided_identidad_recovery_golden() -> None:
    cfg = IfrsLgdConfig(method="provided", recovery_col="recovery")
    frame = pd.DataFrame({"recovery": [0.6, 0.6]})
    out = LgdEngine.from_config(cfg).estimate(frame)

    assert list(out.columns) == ["lgd"]
    # Golden identidad SDD-16 §11: recovery=0.6 -> LGD=0.40.
    np.testing.assert_allclose(out["lgd"].to_numpy(), [0.40, 0.40], rtol=1e-12)


def test_provided_lgd_col_directa() -> None:
    cfg = IfrsLgdConfig(method="provided")  # lgd_col='lgd', recovery_col=None
    frame = pd.DataFrame({"lgd": [0.25, 0.5, 0.75]})
    out = LgdEngine.from_config(cfg).estimate(frame)
    np.testing.assert_allclose(out["lgd"].to_numpy(), [0.25, 0.5, 0.75], rtol=1e-12)


def test_estimate_preserva_indice_del_frame() -> None:
    cfg = IfrsLgdConfig(method="provided")
    frame = pd.DataFrame({"lgd": [0.3, 0.4]}, index=["op1", "op2"])
    out = LgdEngine.from_config(cfg).estimate(frame)
    assert list(out.index) == ["op1", "op2"]


def test_from_config_devuelve_lgd_engine() -> None:
    assert isinstance(LgdEngine.from_config(IfrsLgdConfig()), LgdEngine)


# ─────────────────────── provided: floor/cap y normalización de -0.0 ───────────────────────


def test_floor_acota_lgd_baja() -> None:
    cfg = IfrsLgdConfig(method="provided", lgd_floor=0.10)
    frame = pd.DataFrame({"lgd": [0.02, 0.5]})
    out = LgdEngine.from_config(cfg).estimate(frame)
    np.testing.assert_allclose(out["lgd"].to_numpy(), [0.10, 0.5], rtol=1e-12)


def test_cap_acota_lgd_alta() -> None:
    cfg = IfrsLgdConfig(method="provided", lgd_cap=0.80)
    frame = pd.DataFrame({"lgd": [0.95, 0.5]})
    out = LgdEngine.from_config(cfg).estimate(frame)
    np.testing.assert_allclose(out["lgd"].to_numpy(), [0.80, 0.5], rtol=1e-12)


def test_normaliza_signo_de_cero() -> None:
    cfg = IfrsLgdConfig(method="provided", recovery_col="recovery")
    frame = pd.DataFrame({"recovery": [1.0]})  # LGD = 1 - 1.0 = 0.0
    out = LgdEngine.from_config(cfg).estimate(frame)
    valores = out["lgd"].to_numpy()
    np.testing.assert_allclose(valores, [0.0], rtol=1e-12)
    assert not bool(np.signbit(valores[0]))


def test_no_muta_el_frame() -> None:
    cfg = IfrsLgdConfig(method="provided", recovery_col="recovery")
    frame = pd.DataFrame({"recovery": [0.6, 0.3]})
    snapshot = frame.copy(deep=True)
    LgdEngine.from_config(cfg).estimate(frame)
    pd.testing.assert_frame_equal(frame, snapshot)


# ─────────────────────────── workout: goldens 1 - PV/EAD ───────────────────────────


def test_workout_golden_descuento_eir() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="eir")
    frame = pd.DataFrame(
        {
            "recovery": [600.0],
            "recovery_cost": [100.0],
            "ead": [1000.0],
            "recovery_time_years": [1.0],
        }
    )
    eir = pd.Series([0.10])
    out = LgdEngine.from_config(cfg).estimate(frame, eir=eir)

    # LGD = 1 - PV(recuperos - costos)/EAD = 1 - (600-100)/1.10/1000 = 0.5454545...
    expected = 1.0 - (600.0 - 100.0) / (1.10**1.0) / 1000.0
    np.testing.assert_allclose(out["lgd"].to_numpy(), [expected], rtol=1e-12)
    np.testing.assert_allclose(out["lgd"].to_numpy(), [0.5454545454545454], rtol=1e-9)


def test_workout_descuento_contractual_sin_costo() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")
    frame = pd.DataFrame(
        {
            "recovery": [800.0],
            "ead": [1000.0],
            "recovery_time_years": [2.0],
            "contractual_rate": [0.05],
        }
    )
    out = LgdEngine.from_config(cfg).estimate(frame)

    # Sin columna de costos, el costo es 0; PV = 800/1.05^2.
    expected = 1.0 - 800.0 / (1.05**2.0) / 1000.0
    np.testing.assert_allclose(out["lgd"].to_numpy(), [expected], rtol=1e-12)


# ─────────────────────────── regresión: beta y fractional (nunca OLS) ───────────────────────────


def test_beta_regression_ajusta_en_0_1() -> None:
    cfg = IfrsLgdConfig(method="beta_regression", covariate_cols=("x",))
    out = LgdEngine.from_config(cfg).estimate(_regression_frame())
    valores = out["lgd"].to_numpy()
    assert len(valores) == 40
    assert bool(np.all((valores > 0.0) & (valores < 1.0)))


def test_fractional_response_con_recovery_identidad() -> None:
    cfg = IfrsLgdConfig(
        method="fractional_response", covariate_cols=("x",), recovery_col="recovery"
    )
    x = np.linspace(0.05, 1.0, 40)
    lgd = np.clip(0.3 + 0.2 * x + 0.02 * np.cos(x * 7.0), 0.15, 0.85)
    frame = pd.DataFrame({"x": x, "recovery": 1.0 - lgd})
    out = LgdEngine.from_config(cfg).estimate(frame)
    valores = out["lgd"].to_numpy()
    assert bool(np.all((valores > 0.0) & (valores < 1.0)))


# ─────────────────── errores: rango, columnas y validaciones workout ───────────────────


def test_lgd_fuera_de_rango_levanta() -> None:
    cfg = IfrsLgdConfig(method="provided", recovery_col="recovery")
    frame = pd.DataFrame({"recovery": [1.5]})  # LGD = 1 - 1.5 = -0.5
    with pytest.raises(IfrsLgdError, match="finita y estar en"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_workout_sin_columna_recovery() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery")
    frame = pd.DataFrame({"ead": [1000.0], "recovery_time_years": [1.0]})
    with pytest.raises(IfrsLgdError, match="La columna 'recovery'"):
        LgdEngine.from_config(cfg).estimate(frame, eir=pd.Series([0.1]))


def test_workout_sin_columna_ead() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery")
    frame = pd.DataFrame({"recovery": [600.0], "recovery_time_years": [1.0]})
    with pytest.raises(IfrsLgdError, match="La columna 'ead'"):
        LgdEngine.from_config(cfg).estimate(frame, eir=pd.Series([0.1]))


def test_workout_sin_columna_tiempo() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery")
    frame = pd.DataFrame({"recovery": [600.0], "ead": [1000.0]})
    with pytest.raises(IfrsLgdError, match="recovery_time_years"):
        LgdEngine.from_config(cfg).estimate(frame, eir=pd.Series([0.1]))


def test_workout_eir_ausente() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="eir")
    frame = pd.DataFrame({"recovery": [600.0], "ead": [1000.0], "recovery_time_years": [1.0]})
    with pytest.raises(IfrsLgdError, match="requiere la serie eir"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_workout_eir_longitud_no_alinea() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="eir")
    frame = pd.DataFrame(
        {
            "recovery": [600.0, 600.0],
            "ead": [1000.0, 1000.0],
            "recovery_time_years": [1.0, 1.0],
        }
    )
    with pytest.raises(IfrsLgdError, match="alinear su longitud"):
        LgdEngine.from_config(cfg).estimate(frame, eir=pd.Series([0.1]))


def test_workout_ead_no_positiva() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")
    frame = pd.DataFrame(
        {
            "recovery": [600.0],
            "ead": [0.0],
            "recovery_time_years": [1.0],
            "contractual_rate": [0.05],
        }
    )
    with pytest.raises(IfrsLgdError, match="EAD estrictamente positiva"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_workout_tiempo_negativo() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")
    frame = pd.DataFrame(
        {
            "recovery": [600.0],
            "ead": [1000.0],
            "recovery_time_years": [-1.0],
            "contractual_rate": [0.05],
        }
    )
    with pytest.raises(IfrsLgdError, match="tiempo de recupero no negativo"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_workout_tasa_menor_o_igual_menos_uno() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")
    frame = pd.DataFrame(
        {
            "recovery": [600.0],
            "ead": [1000.0],
            "recovery_time_years": [1.0],
            "contractual_rate": [-1.5],
        }
    )
    with pytest.raises(IfrsLgdError, match="mayor que -1"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_columna_no_numerica() -> None:
    cfg = IfrsLgdConfig(method="provided")
    frame = pd.DataFrame({"lgd": ["a", "b"]})
    with pytest.raises(IfrsLgdError, match="debe ser numérico"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_columna_no_finita() -> None:
    cfg = IfrsLgdConfig(method="provided")
    frame = pd.DataFrame({"lgd": [0.3, np.inf]})
    with pytest.raises(IfrsLgdError, match="valores finitos"):
        LgdEngine.from_config(cfg).estimate(frame)


# ─────────────────────────── regresión: objetivo fuera de soporte ───────────────────────────


def test_beta_target_fuera_de_0_1() -> None:
    cfg = IfrsLgdConfig(method="beta_regression", covariate_cols=("x",))
    frame = pd.DataFrame({"x": [0.1, 0.2, 0.3], "lgd": [0.0, 0.5, 0.9]})  # 0.0 ∉ (0,1)
    with pytest.raises(IfrsLgdError, match=r"\(0, 1\)"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_fractional_target_fuera_de_0_1() -> None:
    cfg = IfrsLgdConfig(method="fractional_response", covariate_cols=("x",))
    frame = pd.DataFrame({"x": [0.1, 0.2, 0.3], "lgd": [0.3, 0.5, 1.5]})  # 1.5 > 1
    with pytest.raises(IfrsLgdError, match=r"\[0, 1\]"):
        LgdEngine.from_config(cfg).estimate(frame)


# ─────────────────── regresión: no convergencia (error controlado) ───────────────────


def test_beta_ajuste_falla_error_controlado(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeBetaFail:
        def __init__(self, endog: Any, exog: Any) -> None: ...

        def fit(self, disp: int = 0) -> Any:
            raise ValueError("hessiano singular")

    monkeypatch.setattr(lgd_module, "_import_beta_model", lambda: _FakeBetaFail)
    cfg = IfrsLgdConfig(method="beta_regression", covariate_cols=("x",))
    with pytest.raises(IfrsLgdError, match="no convergió o falló"):
        LgdEngine.from_config(cfg).estimate(_regression_frame())


def test_fractional_ajuste_no_converge_error_controlado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeGlm:
        def __init__(self, endog: Any, exog: Any, family: Any) -> None: ...

        def fit(self) -> Any:
            warnings.warn("optimización no convergió", stacklevel=2)
            return self  # pragma: no cover - el warning aborta el flujo antes de retornar

    class _FakeFamilies:
        @staticmethod
        def Binomial() -> Any:  # noqa: N802 - espeja statsmodels.api.families.Binomial
            return object()

    class _FakeSm:
        families = _FakeFamilies()
        GLM = _FakeGlm

        @staticmethod
        def add_constant(x: Any, has_constant: str) -> Any:
            return x

    monkeypatch.setattr(lgd_module, "_import_statsmodels", lambda: _FakeSm())
    cfg = IfrsLgdConfig(method="fractional_response", covariate_cols=("x",))
    with pytest.raises(IfrsLgdError, match="no convergió o falló"):
        LgdEngine.from_config(cfg).estimate(_regression_frame())


# ─────────────────────────── guards de dependencia perezosa ───────────────────────────


def _blocker(*modules: str) -> Any:
    """Construye un reemplazo de ``import_module`` que bloquea los módulos indicados."""
    real_import = importlib.import_module

    def block(name: str) -> Any:
        if name in modules:
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return real_import(name)

    return block


def test_estimate_numpy_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lgd_module.importlib, "import_module", _blocker("numpy"))
    with pytest.raises(MissingDependencyError, match="numpy"):
        LgdEngine.from_config(IfrsLgdConfig()).estimate(pd.DataFrame({"lgd": [0.3]}))


def test_estimate_pandas_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lgd_module.importlib, "import_module", _blocker("pandas"))
    with pytest.raises(MissingDependencyError, match="pandas"):
        LgdEngine.from_config(IfrsLgdConfig()).estimate(pd.DataFrame({"lgd": [0.3]}))


def test_estimate_statsmodels_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lgd_module.importlib, "import_module", _blocker("statsmodels.api"))
    cfg = IfrsLgdConfig(method="fractional_response", covariate_cols=("x",))
    with pytest.raises(MissingDependencyError, match="statsmodels"):
        LgdEngine.from_config(cfg).estimate(_regression_frame())


def test_estimate_beta_model_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lgd_module.importlib, "import_module", _blocker("statsmodels.othermod.betareg")
    )
    cfg = IfrsLgdConfig(method="beta_regression", covariate_cols=("x",))
    with pytest.raises(MissingDependencyError, match="statsmodels"):
        LgdEngine.from_config(cfg).estimate(_regression_frame())
