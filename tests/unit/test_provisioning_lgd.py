"""Tests de ``provisioning.lgd``: motor LGD provided/beta/fractional/workout.

Goldens verificables a mano (SDD-16 §11): identidad ``LGD = 1 - recovery`` (``recovery=0.6`` →
``LGD=0.40``), enfoque ``workout`` reproduciendo ``1 - PV/EAD`` con descuento a EIR/contractual,
clip explícito floor/cap, y errores controlados (``LgdError``) ante columnas faltantes, valores
fuera de rango o no convergencia del ajuste de regresión. Cobertura de los guards de dependencia
perezosa (``MissingDependencyError``).
"""

from __future__ import annotations

import importlib
import inspect
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym.provisioning.lgd as lgd_module
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.exceptions import LgdError
from nikodym.provisioning.ifrs9.config import IfrsLgdConfig
from nikodym.provisioning.lgd import (
    WORKOUT_COST_COLUMN,
    WORKOUT_EAD_COLUMN,
    WORKOUT_RATE_COLUMN,
    WORKOUT_TIME_COLUMN,
    LgdEngine,
)


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


def test_workout_descuento_contractual_con_costo_cero_explicito() -> None:
    """El costo cero es una declaración de la institución, no un supuesto del motor (CRP-5).

    Este test asumía el costo en cero cuando la columna faltaba. Esa comodidad subestimaba la LGD
    en silencio —el censo lo midió en 20 pp— y era asimétrica con ``recovery_time_years``, que
    siempre levantó. Ahora el cero se escribe.
    """
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")
    frame = pd.DataFrame(
        {
            "recovery": [800.0],
            "recovery_cost": [0.0],
            "ead": [1000.0],
            "recovery_time_years": [2.0],
            "contractual_rate": [0.05],
        }
    )
    out = LgdEngine.from_config(cfg).estimate(frame)

    # PV = 800/1.05^2; el golden no cambia, cambia quién declara el cero.
    expected = 1.0 - 800.0 / (1.05**2.0) / 1000.0
    np.testing.assert_allclose(out["lgd"].to_numpy(), [expected], rtol=1e-12)


def test_workout_sin_columna_de_costo_levanta() -> None:
    """La columna ausente ya no se imputa: el enfoque *workout* la exige (CRP-5)."""
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")
    frame = pd.DataFrame(
        {
            "recovery": [800.0],
            "ead": [1000.0],
            "recovery_time_years": [2.0],
            "contractual_rate": [0.05],
        }
    )

    with pytest.raises(LgdError, match="recovery_cost"):
        LgdEngine.from_config(cfg).estimate(frame)


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
    with pytest.raises(LgdError, match="finita y estar en"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_workout_sin_columna_recovery() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery")
    frame = pd.DataFrame({"ead": [1000.0], "recovery_time_years": [1.0]})
    with pytest.raises(LgdError, match="La columna 'recovery'"):
        LgdEngine.from_config(cfg).estimate(frame, eir=pd.Series([0.1]))


def test_workout_sin_columna_ead() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery")
    frame = pd.DataFrame({"recovery": [600.0], "recovery_time_years": [1.0]})
    with pytest.raises(LgdError, match="La columna 'ead'"):
        LgdEngine.from_config(cfg).estimate(frame, eir=pd.Series([0.1]))


def test_workout_sin_columna_tiempo() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery")
    frame = pd.DataFrame({"recovery": [600.0], "ead": [1000.0]})
    with pytest.raises(LgdError, match="recovery_time_years"):
        LgdEngine.from_config(cfg).estimate(frame, eir=pd.Series([0.1]))


def test_workout_eir_ausente() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="eir")
    frame = pd.DataFrame(
        {
            "recovery": [600.0],
            "recovery_cost": [0.0],
            "ead": [1000.0],
            "recovery_time_years": [1.0],
        }
    )
    with pytest.raises(LgdError, match="requiere la serie eir"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_workout_eir_longitud_no_alinea() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="eir")
    frame = pd.DataFrame(
        {
            "recovery": [600.0, 600.0],
            "recovery_cost": [0.0, 0.0],
            "ead": [1000.0, 1000.0],
            "recovery_time_years": [1.0, 1.0],
        }
    )
    with pytest.raises(LgdError, match="alinear su longitud"):
        LgdEngine.from_config(cfg).estimate(frame, eir=pd.Series([0.1]))


def test_workout_ead_no_positiva() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")
    frame = pd.DataFrame(
        {
            "recovery": [600.0],
            "recovery_cost": [0.0],
            "ead": [0.0],
            "recovery_time_years": [1.0],
            "contractual_rate": [0.05],
        }
    )
    with pytest.raises(LgdError, match="EAD estrictamente positiva"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_workout_tiempo_negativo() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")
    frame = pd.DataFrame(
        {
            "recovery": [600.0],
            "recovery_cost": [0.0],
            "ead": [1000.0],
            "recovery_time_years": [-1.0],
            "contractual_rate": [0.05],
        }
    )
    with pytest.raises(LgdError, match="tiempo de recupero no negativo"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_workout_tasa_menor_o_igual_menos_uno() -> None:
    cfg = IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")
    frame = pd.DataFrame(
        {
            "recovery": [600.0],
            "recovery_cost": [0.0],
            "ead": [1000.0],
            "recovery_time_years": [1.0],
            "contractual_rate": [-1.5],
        }
    )
    with pytest.raises(LgdError, match="mayor que -1"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_columna_no_numerica() -> None:
    cfg = IfrsLgdConfig(method="provided")
    frame = pd.DataFrame({"lgd": ["a", "b"]})
    with pytest.raises(LgdError, match="debe ser numérico"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_columna_no_finita() -> None:
    cfg = IfrsLgdConfig(method="provided")
    frame = pd.DataFrame({"lgd": [0.3, np.inf]})
    with pytest.raises(LgdError, match="valores finitos"):
        LgdEngine.from_config(cfg).estimate(frame)


# ─────────────────────────── regresión: objetivo fuera de soporte ───────────────────────────


def test_beta_target_fuera_de_0_1() -> None:
    cfg = IfrsLgdConfig(method="beta_regression", covariate_cols=("x",))
    frame = pd.DataFrame({"x": [0.1, 0.2, 0.3], "lgd": [0.0, 0.5, 0.9]})  # 0.0 ∉ (0,1)
    with pytest.raises(LgdError, match=r"\(0, 1\)"):
        LgdEngine.from_config(cfg).estimate(frame)


def test_fractional_target_fuera_de_0_1() -> None:
    cfg = IfrsLgdConfig(method="fractional_response", covariate_cols=("x",))
    frame = pd.DataFrame({"x": [0.1, 0.2, 0.3], "lgd": [0.3, 0.5, 1.5]})  # 1.5 > 1
    with pytest.raises(LgdError, match=r"\[0, 1\]"):
        LgdEngine.from_config(cfg).estimate(frame)


# ─────────────────── regresión: no convergencia (error controlado) ───────────────────


def test_beta_ajuste_falla_error_controlado(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeBetaFail:
        def __init__(self, endog: Any, exog: Any) -> None: ...

        def fit(self, disp: int = 0) -> Any:
            raise ValueError("hessiano singular")

    monkeypatch.setattr(lgd_module, "_import_beta_model", lambda: _FakeBetaFail)
    cfg = IfrsLgdConfig(method="beta_regression", covariate_cols=("x",))
    with pytest.raises(LgdError, match="no convergió o falló"):
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
    with pytest.raises(LgdError, match="no convergió o falló"):
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


# ─────────────────── D-LGD-2: el motor vive en el nivel compartido ───────────────────


def test_el_motor_no_vive_dentro_de_ifrs9() -> None:
    """El motor de LGD no puede colgar del paquete de una norma contable concreta.

    Lo consumen los dos motores de provisiones, y uno de ellos —el método interno— es
    jurisdiccional y contablemente **neutro**: hacerle importar ``provisioning.ifrs9`` para estimar
    una severidad sería el acoplamiento equivocado, y el que ``internal/config.py`` descarta por
    escrito en su propio docstring.
    """
    assert LgdEngine.__module__ == "nikodym.provisioning.lgd"
    assert LgdError.__module__ == "nikodym.provisioning.exceptions"
    # El motor movido no puede arrastrar de vuelta el paquete que acaba de dejar.
    fuente = Path(inspect.getfile(lgd_module)).read_text(encoding="utf-8")
    runtime = [
        linea
        for linea in fuente.splitlines()
        if linea.startswith(("import ", "from ")) and "ifrs9" in linea
    ]
    assert runtime == [], f"imports de ifrs9 en top-level del motor compartido: {runtime}"


def test_el_reexport_de_ifrs9_es_el_mismo_objeto() -> None:
    """``from nikodym.provisioning.ifrs9 import LgdEngine`` seguía existiendo: no se rompe.

    Un re-export que devolviera otra clase pasaría un ``import`` y fallaría en el primer
    ``isinstance``; y un ``IfrsLgdError`` que no fuera el mismo objeto dejaría en verde un
    ``pytest.raises`` que ya no atrapa lo que el motor levanta.
    """
    import nikodym.provisioning.ifrs9 as ifrs9_pkg
    from nikodym.provisioning.ifrs9.exceptions import IfrsLgdError

    assert ifrs9_pkg.LgdEngine is LgdEngine
    assert IfrsLgdError is LgdError
    assert "LgdEngine" in ifrs9_pkg.__all__


# ────────── D-LGD-3: los nombres de las columnas workout los declara el config ──────────


@dataclass(frozen=True)
class _SpecWorkoutRenombrado:
    """Un config que satisface ``LgdSpec`` con OTROS nombres para las cuatro columnas workout.

    No es un mock de conveniencia: es el control negativo del propio D-LGD-3. Mientras el motor
    leyera los nombres de una constante de módulo, este frame —que no tiene ni una sola columna
    llamada ``ead``, ``recovery_cost``, ``recovery_time_years`` ni ``contractual_rate``— fallaba con
    «La columna 'ead' … no está en el frame».
    """

    method: str = "workout"
    lgd_col: str = "lgd"
    recovery_col: str | None = "recupero"
    covariate_cols: tuple[str, ...] = ()
    workout_discount: str = "contractual"
    lgd_floor: float = 0.0
    lgd_cap: float = 1.0
    workout_ead_col: str = "exposure_amount"
    workout_cost_col: str = "costos_recupero"
    workout_time_col: str = "anios_recupero"
    workout_rate_col: str = "tasa_contractual"


def test_workout_lee_los_nombres_que_declara_el_config() -> None:
    """Con nombres propios, el motor los usa: ninguno de los cuatro convencionales existe aquí."""
    frame = pd.DataFrame(
        {
            "recupero": [60.0, 80.0],
            "exposure_amount": [100.0, 100.0],
            "costos_recupero": [0.0, 0.0],
            "anios_recupero": [0.0, 0.0],
            "tasa_contractual": [0.10, 0.10],
        }
    )
    spec = _SpecWorkoutRenombrado()
    assert not {WORKOUT_EAD_COLUMN, WORKOUT_COST_COLUMN, WORKOUT_TIME_COLUMN} & set(frame.columns)
    out = LgdEngine.from_config(spec).estimate(frame)
    # LGD = 1 - (recupero - costos) / EAD, sin descuento porque el tiempo es cero.
    assert out["lgd"].tolist() == [pytest.approx(0.40), pytest.approx(0.20)]


def test_el_error_de_costos_nombra_la_columna_declarada_y_no_la_convencional() -> None:
    """Nombrar `recovery_cost` mandaría a crear una columna que este config no pide."""
    frame = pd.DataFrame(
        {
            "recupero": [60.0],
            "exposure_amount": [100.0],
            "anios_recupero": [0.0],
            "tasa_contractual": [0.10],
        }
    )
    with pytest.raises(LgdError, match="costos_recupero"):
        LgdEngine.from_config(_SpecWorkoutRenombrado()).estimate(frame)


def test_ifrs9_publica_los_nombres_convencionales_y_no_cambia_de_comportamiento() -> None:
    """IFRS 9 conserva los cuatro nombres de siempre: D-LGD-3 no le cambia una sola corrida."""
    cfg = IfrsLgdConfig()
    assert cfg.workout_ead_col == WORKOUT_EAD_COLUMN == "ead"
    assert cfg.workout_cost_col == WORKOUT_COST_COLUMN == "recovery_cost"
    assert cfg.workout_time_col == WORKOUT_TIME_COLUMN == "recovery_time_years"
    assert cfg.workout_rate_col == WORKOUT_RATE_COLUMN == "contractual_rate"


def test_los_nombres_workout_de_ifrs9_no_entran_al_config_ni_a_su_identidad() -> None:
    """Van como propiedades, no como campos, y por eso no mueven el `config_hash` del preset F4.

    De ese digest cuelgan el lineage, la ficha del modelo y el ancla de idempotencia del
    inventario — y el de F4 está impreso dentro de la demo publicada, que no se recaptura. Un campo
    entra al `model_dump`; una propiedad no. El gate mide las dos caras.
    """
    campos = set(IfrsLgdConfig.model_fields)
    propiedades = {"workout_ead_col", "workout_cost_col", "workout_time_col", "workout_rate_col"}
    assert propiedades & campos == set(), "columnas workout como campos moverían el hash"
    assert propiedades & set(IfrsLgdConfig().model_dump(mode="json", by_alias=True)) == set()
    # Y siguen siendo alcanzables por el protocolo, que es de lo que vive el motor.
    assert propiedades <= set(dir(IfrsLgdConfig()))
