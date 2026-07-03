"""Tests de ``provisioning.ifrs9.ead``: motor EAD/CCF provided/ccf y perfil por período.

Goldens verificables a mano (SDD-16 §11): ``EAD = drawn + CCF*(limite - drawn)`` con
``drawn=800``, ``limite=1000``, ``CCF=0.5`` -> ``EAD=900``; EAD provista directa; despliegue por
período (constante con aviso CT-3 ``FALTA-DATO-IFRS-4`` cuando no hay perfil longitudinal, y por la
columna ``exposure_profile_col`` cuando sí); piso D-IFRS-13 ``EAD >= drawn`` ante ``credit_limit <
drawn``; y errores controlados (``IfrsEadError``) ante EAD negativa, falta de fuente CCF, columnas
faltantes o ``periods`` inválidos. Cobertura de los guards de dependencia perezosa.
"""

from __future__ import annotations

import importlib
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym.provisioning.ifrs9.ead as ead_module
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9 import EadEngine
from nikodym.provisioning.ifrs9.config import IfrsEadConfig
from nikodym.provisioning.ifrs9.exceptions import IfrsEadError

_CT3 = "FALTA-DATO-IFRS-4"
_FLOORED = "ead_floored_limit_below_drawn"


# ─────────────── ccf: golden EAD = drawn + CCF*(limite - drawn) ───────────────


def test_ccf_golden_ccf_value() -> None:
    cfg = IfrsEadConfig(method="ccf", ccf_value=0.5)
    frame = pd.DataFrame({"drawn": [800.0], "credit_limit": [1000.0]})
    out = EadEngine.from_config(cfg).estimate(frame, periods=[1])

    assert list(out.columns) == ["period", "ead", "warning_codes"]
    # Golden SDD-16 §11: 800 + 0.5·(1000-800) = 900.
    np.testing.assert_allclose(out["ead"].to_numpy(), [900.0], rtol=1e-12)


def test_ccf_ccf_col_por_fila() -> None:
    cfg = IfrsEadConfig(method="ccf", ccf_col="ccf")
    frame = pd.DataFrame(
        {"drawn": [800.0, 500.0], "credit_limit": [1000.0, 1000.0], "ccf": [0.5, 0.2]}
    )
    out = EadEngine.from_config(cfg).estimate(frame, periods=[1])
    # 800+0.5·200=900 ; 500+0.2·500=600.
    np.testing.assert_allclose(out["ead"].to_numpy(), [900.0, 600.0], rtol=1e-12)


def test_ccf_sin_fuente_de_ccf_levanta() -> None:
    # El config permite method='ccf' sin ccf_col ni ccf_value; el runtime exige la fuente.
    cfg = IfrsEadConfig(method="ccf")
    frame = pd.DataFrame({"drawn": [800.0], "credit_limit": [1000.0]})
    with pytest.raises(IfrsEadError, match="fuente de CCF"):
        EadEngine.from_config(cfg).estimate(frame, periods=[1])


# ─────────────────────────── provided: EAD entregada ───────────────────────────


def test_provided_ead_col_directa() -> None:
    cfg = IfrsEadConfig(method="provided")  # ead_col='ead'
    frame = pd.DataFrame({"ead": [100.0, 250.0, 900.0]})
    out = EadEngine.from_config(cfg).estimate(frame, periods=[1])
    np.testing.assert_allclose(out["ead"].to_numpy(), [100.0, 250.0, 900.0], rtol=1e-12)


def test_from_config_devuelve_ead_engine() -> None:
    assert isinstance(EadEngine.from_config(IfrsEadConfig()), EadEngine)


# ─────────────────────────── despliegue por período + aviso CT-3 ───────────────────────────


def test_perfil_ausente_constante_con_ct3() -> None:
    cfg = IfrsEadConfig(method="provided")
    frame = pd.DataFrame({"ead": [900.0]}, index=["op1"])
    out = EadEngine.from_config(cfg).estimate(frame, periods=[1, 2, 3])

    assert list(out["period"].to_numpy()) == [1, 2, 3]
    np.testing.assert_allclose(out["ead"].to_numpy(), [900.0, 900.0, 900.0], rtol=1e-12)
    # EAD constante por período con aviso CT-3 en cada fila.
    assert list(out["warning_codes"]) == [(_CT3,), (_CT3,), (_CT3,)]
    assert list(out.index) == ["op1", "op1", "op1"]


def test_perfil_presente_usa_columna_sin_ct3() -> None:
    cfg = IfrsEadConfig(method="provided", exposure_profile_col="exposure_profile")
    frame = pd.DataFrame({"ead": [900.0], "exposure_profile": [750.0]})
    out = EadEngine.from_config(cfg).estimate(frame, periods=[1, 2])

    # Con perfil longitudinal declarado se usa la columna de perfil y no se marca CT-3.
    np.testing.assert_allclose(out["ead"].to_numpy(), [750.0, 750.0], rtol=1e-12)
    assert list(out["warning_codes"]) == [(), ()]


def test_perfil_configurado_pero_ausente_cae_a_constante_ct3() -> None:
    # exposure_profile_col configurado pero no presente en el frame → fallback constante + CT-3.
    cfg = IfrsEadConfig(method="provided", exposure_profile_col="exposure_profile")
    frame = pd.DataFrame({"ead": [900.0]})
    out = EadEngine.from_config(cfg).estimate(frame, periods=[1])
    np.testing.assert_allclose(out["ead"].to_numpy(), [900.0], rtol=1e-12)
    assert list(out["warning_codes"]) == [(_CT3,)]


def test_orden_operacion_mayor_multiples_filas() -> None:
    cfg = IfrsEadConfig(method="provided")
    frame = pd.DataFrame({"ead": [10.0, 20.0]}, index=["a", "b"])
    out = EadEngine.from_config(cfg).estimate(frame, periods=[1, 2])
    # Orden operación-mayor: cada fila con sus períodos contiguos.
    assert list(out.index) == ["a", "a", "b", "b"]
    assert list(out["period"].to_numpy()) == [1, 2, 1, 2]
    np.testing.assert_allclose(out["ead"].to_numpy(), [10.0, 10.0, 20.0, 20.0], rtol=1e-12)


# ─────────────────────────── piso D-IFRS-13 (EAD ≥ drawn) ───────────────────────────


def test_piso_dirfs13_limite_bajo_drawn() -> None:
    cfg = IfrsEadConfig(method="ccf", ccf_value=0.5)
    # Fila 0: límite<drawn → EAD acotada a drawn=800 (+aviso floor). Fila 1: normal, sin floor.
    frame = pd.DataFrame({"drawn": [800.0, 500.0], "credit_limit": [600.0, 1000.0]})
    out = EadEngine.from_config(cfg).estimate(frame, periods=[1])

    # 800 + 0.5·(600-800) = 700 sin piso; acotado a drawn=800. Fila 1: 500+0.5·500=750.
    np.testing.assert_allclose(out["ead"].to_numpy(), [800.0, 750.0], rtol=1e-12)
    assert list(out["warning_codes"]) == [(_FLOORED, _CT3), (_CT3,)]


# ─────────────────────────── errores: EAD negativa y no finita ───────────────────────────


def test_ead_provided_negativa_levanta() -> None:
    cfg = IfrsEadConfig(method="provided")
    frame = pd.DataFrame({"ead": [-1.0]})
    with pytest.raises(IfrsEadError, match="finita y no negativa"):
        EadEngine.from_config(cfg).estimate(frame, periods=[1])


def test_ccf_drawn_negativo_vuelve_ead_negativa() -> None:
    # drawn negativo: el piso deja EAD=drawn<0 → error de no negatividad.
    cfg = IfrsEadConfig(method="ccf", ccf_value=0.5)
    frame = pd.DataFrame({"drawn": [-10.0], "credit_limit": [-20.0]})
    with pytest.raises(IfrsEadError, match="finita y no negativa"):
        EadEngine.from_config(cfg).estimate(frame, periods=[1])


def test_normaliza_signo_de_cero() -> None:
    cfg = IfrsEadConfig(method="provided")
    frame = pd.DataFrame({"ead": [-0.0]})
    out = EadEngine.from_config(cfg).estimate(frame, periods=[1])
    valores = out["ead"].to_numpy()
    np.testing.assert_allclose(valores, [0.0], rtol=1e-12)
    assert not bool(np.signbit(valores[0]))


def test_columna_no_numerica() -> None:
    cfg = IfrsEadConfig(method="provided")
    frame = pd.DataFrame({"ead": ["a", "b"]})
    with pytest.raises(IfrsEadError, match="debe ser numérico"):
        EadEngine.from_config(cfg).estimate(frame, periods=[1])


def test_columna_no_finita() -> None:
    cfg = IfrsEadConfig(method="provided")
    frame = pd.DataFrame({"ead": [100.0, np.inf]})
    with pytest.raises(IfrsEadError, match="valores finitos"):
        EadEngine.from_config(cfg).estimate(frame, periods=[1])


def test_columna_faltante() -> None:
    cfg = IfrsEadConfig(method="ccf", ccf_value=0.5)
    frame = pd.DataFrame({"drawn": [800.0]})  # falta credit_limit
    with pytest.raises(IfrsEadError, match="'credit_limit'"):
        EadEngine.from_config(cfg).estimate(frame, periods=[1])


def test_no_muta_el_frame() -> None:
    cfg = IfrsEadConfig(method="ccf", ccf_value=0.5)
    frame = pd.DataFrame({"drawn": [800.0], "credit_limit": [1000.0]})
    snapshot = frame.copy(deep=True)
    EadEngine.from_config(cfg).estimate(frame, periods=[1, 2])
    pd.testing.assert_frame_equal(frame, snapshot)


# ─────────────────────────── validación de periods ───────────────────────────


def test_periods_vacio_levanta() -> None:
    cfg = IfrsEadConfig(method="provided")
    frame = pd.DataFrame({"ead": [900.0]})
    with pytest.raises(IfrsEadError, match="no puede estar vacío"):
        EadEngine.from_config(cfg).estimate(frame, periods=[])


def test_periods_no_entero_levanta() -> None:
    cfg = IfrsEadConfig(method="provided")
    frame = pd.DataFrame({"ead": [900.0]})
    with pytest.raises(IfrsEadError, match="debe ser un entero"):
        EadEngine.from_config(cfg).estimate(frame, periods=[1.5])  # type: ignore[list-item]


def test_periods_menor_que_uno_levanta() -> None:
    cfg = IfrsEadConfig(method="provided")
    frame = pd.DataFrame({"ead": [900.0]})
    with pytest.raises(IfrsEadError, match=">= 1"):
        EadEngine.from_config(cfg).estimate(frame, periods=[0])


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
    monkeypatch.setattr(ead_module.importlib, "import_module", _blocker("numpy"))
    with pytest.raises(MissingDependencyError, match="numpy"):
        EadEngine.from_config(IfrsEadConfig(method="provided")).estimate(
            pd.DataFrame({"ead": [900.0]}), periods=[1]
        )


def test_estimate_pandas_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ead_module.importlib, "import_module", _blocker("pandas"))
    with pytest.raises(MissingDependencyError, match="pandas"):
        EadEngine.from_config(IfrsEadConfig(method="provided")).estimate(
            pd.DataFrame({"ead": [900.0]}), periods=[1]
        )
