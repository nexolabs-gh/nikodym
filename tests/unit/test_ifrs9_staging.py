"""Tests de ``provisioning.ifrs9.staging``: motor SICR / Stage 1/2/3 con gatillos.

Goldens verificables a mano (SDD-16 §8/§11): ratio ``PD_life 0.11/0.05 = 2.2 >= 2.0`` → Stage 2;
backstop PIT ``0.15/0.04 = 3.75 >= 3.0`` → Stage 2; downgrade por notches → Stage 2; override
cualitativo → Stage 2/3; ``dpd=35 >= 30`` → Stage 2; ``dpd=95 >= 90`` → Stage 3; ``is_default`` →
Stage 3; y la exención de bajo riesgo rescata los gatillos cuantitativos a Stage 1, pero la política
conservadora v1 da prioridad a las presunciones DPD. Además, errores controlados
(``IfrsStagingError``/``IfrsInputError``) ante
columnas faltantes, PD en origen no positiva, override/flags inválidos, días de mora negativos/no
enteros y desalineación de series; cobertura de los guards de dependencia perezosa.
"""

from __future__ import annotations

import importlib
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym.provisioning.ifrs9.staging as staging_module
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9 import StagingEngine
from nikodym.provisioning.ifrs9.config import IfrsStagingConfig
from nikodym.provisioning.ifrs9.exceptions import IfrsInputError, IfrsStagingError


def _assign(cfg: IfrsStagingConfig, frame: pd.DataFrame, **series: Any) -> pd.DataFrame:
    """Corre ``StagingEngine.assign`` completando ``pd_life``/``pd_pit`` neutros por defecto."""
    n = frame.shape[0]
    pd_life = series.get("pd_life", pd.Series([0.02] * n, dtype=float))
    pd_pit = series.get("pd_pit", pd.Series([0.01] * n, dtype=float))
    return StagingEngine.from_config(cfg).assign(frame, pd_life=pd_life, pd_pit=pd_pit)


# ─────────────────────────── from_config y Stage 1 base ───────────────────────────


def test_from_config_devuelve_staging_engine() -> None:
    assert isinstance(StagingEngine.from_config(IfrsStagingConfig()), StagingEngine)


def test_stage1_sin_gatillos() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [0]}, index=["op1"])
    out = _assign(cfg, frame)

    assert list(out.columns) == ["stage", "sicr_triggers", "low_credit_risk_exempt"]
    assert list(out.index) == ["op1"]
    assert out["stage"].tolist() == [1]
    assert out["sicr_triggers"].tolist() == [()]
    assert out["low_credit_risk_exempt"].tolist() == [False]


# ─────────────────────────── gatillo 1: ratio PD lifetime ───────────────────────────


def test_ratio_pd_life_golden_stage2() -> None:
    # Golden SDD-16 §8: 0.11 / 0.05 = 2.2 >= 2.0 → Stage 2.
    cfg = IfrsStagingConfig(is_default_col=None, origination_pd_life_col="pd_life_orig")
    frame = pd.DataFrame({"days_past_due": [0], "pd_life_orig": [0.05]})
    out = _assign(cfg, frame, pd_life=pd.Series([0.11]), pd_pit=pd.Series([0.01]))

    assert out["stage"].tolist() == [2]
    assert out["sicr_triggers"].tolist() == [("sicr_pd_ratio",)]


def test_ratio_pd_life_justo_bajo_umbral_stage1() -> None:
    # 0.09 / 0.05 = 1.8 < 2.0 → no dispara.
    cfg = IfrsStagingConfig(is_default_col=None, origination_pd_life_col="pd_life_orig")
    frame = pd.DataFrame({"days_past_due": [0], "pd_life_orig": [0.05]})
    out = _assign(cfg, frame, pd_life=pd.Series([0.09]), pd_pit=pd.Series([0.01]))

    assert out["stage"].tolist() == [1]
    assert out["sicr_triggers"].tolist() == [()]


def test_ratio_sin_columna_de_origen_levanta() -> None:
    # origination_pd_life_col configurada pero ausente del frame → error duro (no degrada).
    cfg = IfrsStagingConfig(is_default_col=None, origination_pd_life_col="pd_life_orig")
    frame = pd.DataFrame({"days_past_due": [0]})
    with pytest.raises(IfrsStagingError, match="pd_life_orig"):
        _assign(cfg, frame, pd_life=pd.Series([0.11]), pd_pit=pd.Series([0.01]))


def test_ratio_pd_origen_no_positiva_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None, origination_pd_life_col="pd_life_orig")
    frame = pd.DataFrame({"days_past_due": [0], "pd_life_orig": [0.0]})
    with pytest.raises(IfrsStagingError, match="estrictamente positiva"):
        _assign(cfg, frame, pd_life=pd.Series([0.11]), pd_pit=pd.Series([0.01]))


# ─────────────────────────── gatillo 2: backstop PIT ───────────────────────────


def test_backstop_pit_golden_stage2() -> None:
    # Golden: 0.15 / 0.04 = 3.75 >= 3.0 → Stage 2 (columna convencional pd_pit_origination).
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [0], "pd_pit_origination": [0.04]})
    out = _assign(cfg, frame, pd_life=pd.Series([0.02]), pd_pit=pd.Series([0.15]))

    assert out["stage"].tolist() == [2]
    assert out["sicr_triggers"].tolist() == [("sicr_pd_pit_backstop",)]


def test_backstop_pit_origen_no_positiva_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [0], "pd_pit_origination": [0.0]})
    with pytest.raises(IfrsStagingError, match="PD PIT en origen"):
        _assign(cfg, frame, pd_life=pd.Series([0.02]), pd_pit=pd.Series([0.15]))


# ─────────────────────────── gatillo 3: downgrade por notches ───────────────────────────


def test_notch_downgrade_stage2() -> None:
    # Rating 5 vs origen 2 → caída de 3 notches >= 3 → Stage 2.
    cfg = IfrsStagingConfig(
        is_default_col=None,
        rating_col="rating",
        origination_rating_col="rating_orig",
        notch_downgrade_threshold=3,
    )
    frame = pd.DataFrame({"days_past_due": [0], "rating": [5.0], "rating_orig": [2.0]})
    out = _assign(cfg, frame)

    assert out["stage"].tolist() == [2]
    assert out["sicr_triggers"].tolist() == [("notch_downgrade",)]


def test_notch_downgrade_insuficiente_stage1() -> None:
    cfg = IfrsStagingConfig(
        is_default_col=None,
        rating_col="rating",
        origination_rating_col="rating_orig",
        notch_downgrade_threshold=3,
    )
    frame = pd.DataFrame({"days_past_due": [0], "rating": [4.0], "rating_orig": [2.0]})
    out = _assign(cfg, frame)
    assert out["stage"].tolist() == [1]


def test_notch_rating_no_numerico_levanta() -> None:
    cfg = IfrsStagingConfig(
        is_default_col=None,
        rating_col="rating",
        origination_rating_col="rating_orig",
        notch_downgrade_threshold=3,
    )
    frame = pd.DataFrame({"days_past_due": [0], "rating": ["AA"], "rating_orig": [2.0]})
    with pytest.raises(IfrsStagingError, match="debe ser numérico"):
        _assign(cfg, frame)


# ─────────────────────────── gatillo 4: override cualitativo ───────────────────────────


def test_override_stage2_y_stage3() -> None:
    cfg = IfrsStagingConfig(is_default_col=None, stage_override_col="ovr")
    frame = pd.DataFrame({"days_past_due": [0, 0, 0], "ovr": [1, 2, 3]}, index=["a", "b", "c"])
    out = _assign(cfg, frame)

    assert out["stage"].tolist() == [1, 2, 3]
    assert out["sicr_triggers"].tolist() == [(), ("stage_override",), ("stage_override",)]


def test_override_no_entero_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None, stage_override_col="ovr")
    frame = pd.DataFrame({"days_past_due": [0], "ovr": [2.5]})
    with pytest.raises(IfrsStagingError, match="debe ser entero"):
        _assign(cfg, frame)


def test_override_fuera_de_rango_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None, stage_override_col="ovr")
    frame = pd.DataFrame({"days_past_due": [0], "ovr": [4]})
    with pytest.raises(IfrsStagingError, match="1 = sin override"):
        _assign(cfg, frame)


def test_override_columna_faltante_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None, stage_override_col="ovr")
    frame = pd.DataFrame({"days_past_due": [0]})
    with pytest.raises(IfrsStagingError, match="override 'ovr'"):
        _assign(cfg, frame)


# ───────────────────── gatillos 5/6: presunciones dpd + default ─────────────────────


def test_backstop_30dpd_golden_stage2() -> None:
    # Golden SDD-16 §8: dpd=35 >= 30 → Stage 2.
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [35]})
    out = _assign(cfg, frame)

    assert out["stage"].tolist() == [2]
    assert out["sicr_triggers"].tolist() == [("dpd_sicr_backstop",)]


def test_backstop_90dpd_golden_stage3() -> None:
    # Golden SDD-16 §8: dpd=95 >= 90 → Stage 3 (dispara también el backstop 30).
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [95]})
    out = _assign(cfg, frame)

    assert out["stage"].tolist() == [3]
    assert out["sicr_triggers"].tolist() == [("dpd_sicr_backstop", "dpd_default_backstop")]


def test_is_default_flag_stage3() -> None:
    # Flag booleano de default → Stage 3 aunque dpd=0 (columna is_default por default).
    cfg = IfrsStagingConfig()
    frame = pd.DataFrame({"days_past_due": [0], "is_default": [True]})
    out = _assign(cfg, frame)

    assert out["stage"].tolist() == [3]
    assert out["sicr_triggers"].tolist() == [("is_default",)]


def test_is_default_columna_ausente_se_ignora() -> None:
    # is_default_col con default 'is_default' pero sin la columna → opcional (§6): se ignora.
    cfg = IfrsStagingConfig()
    frame = pd.DataFrame({"days_past_due": [0]})
    out = _assign(cfg, frame)
    assert out["stage"].tolist() == [1]


def test_is_default_desactivado_col_none() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [0], "is_default": [True]})
    out = _assign(cfg, frame)
    # Con is_default_col=None el flag se ignora por completo.
    assert out["stage"].tolist() == [1]


def test_is_default_valor_no_binario_levanta() -> None:
    cfg = IfrsStagingConfig()
    frame = pd.DataFrame({"days_past_due": [0], "is_default": [2]})
    with pytest.raises(IfrsStagingError, match="0/1 o booleanos"):
        _assign(cfg, frame)


def test_is_default_no_numerico_levanta() -> None:
    cfg = IfrsStagingConfig()
    frame = pd.DataFrame({"days_past_due": [0], "is_default": ["x"]})
    with pytest.raises(IfrsStagingError, match="debe ser numérico"):
        _assign(cfg, frame)


# ─────────────────────────── stage = máximo severo disparado ───────────────────────────


def test_stage_maximo_de_gatillos_multiples() -> None:
    # Ratio (S2) + default 90dpd (S3) → máximo = Stage 3, ambos gatillos listados.
    cfg = IfrsStagingConfig(is_default_col=None, origination_pd_life_col="pd_life_orig")
    frame = pd.DataFrame({"days_past_due": [95], "pd_life_orig": [0.05]})
    out = _assign(cfg, frame, pd_life=pd.Series([0.11]), pd_pit=pd.Series([0.01]))

    assert out["stage"].tolist() == [3]
    triggers = out["sicr_triggers"].tolist()[0]
    assert "sicr_pd_ratio" in triggers
    assert "dpd_default_backstop" in triggers


# ─────────────────────────── gatillo 7: exención de bajo riesgo ───────────────────────────


def test_exencion_rescata_gatillo_blando_a_stage1() -> None:
    # Ratio blando (S2) + fila de bajo riesgo con exención activa → rescatada a Stage 1.
    cfg = IfrsStagingConfig(
        is_default_col=None,
        origination_pd_life_col="pd_life_orig",
        low_credit_risk_exemption=True,
        low_credit_risk_col="low_risk",
    )
    frame = pd.DataFrame({"days_past_due": [0], "pd_life_orig": [0.05], "low_risk": [True]})
    out = _assign(cfg, frame, pd_life=pd.Series([0.11]), pd_pit=pd.Series([0.01]))

    assert out["stage"].tolist() == [1]
    assert out["low_credit_risk_exempt"].tolist() == [True]
    # El gatillo disparó y queda registrado, aunque la exención lo rescató.
    assert out["sicr_triggers"].tolist() == [("sicr_pd_ratio",)]


def test_exencion_no_rescata_presuncion_dpd_bajo_politica_v1() -> None:
    # Política conservadora Nikodym v1: la exención no rescata el gatillo DPD → Stage 2.
    cfg = IfrsStagingConfig(
        is_default_col=None,
        low_credit_risk_exemption=True,
        low_credit_risk_col="low_risk",
    )
    frame = pd.DataFrame({"days_past_due": [35], "low_risk": [1]})
    out = _assign(cfg, frame)

    assert out["stage"].tolist() == [2]
    assert out["low_credit_risk_exempt"].tolist() == [True]
    assert out["sicr_triggers"].tolist() == [("dpd_sicr_backstop",)]


def test_exencion_sin_flag_de_fila_no_rescata() -> None:
    # Exención activa en config pero la fila no es de bajo riesgo → no rescata.
    cfg = IfrsStagingConfig(
        is_default_col=None,
        origination_pd_life_col="pd_life_orig",
        low_credit_risk_exemption=True,
        low_credit_risk_col="low_risk",
    )
    frame = pd.DataFrame({"days_past_due": [0], "pd_life_orig": [0.05], "low_risk": [False]})
    out = _assign(cfg, frame, pd_life=pd.Series([0.11]), pd_pit=pd.Series([0.01]))

    assert out["stage"].tolist() == [2]
    assert out["low_credit_risk_exempt"].tolist() == [False]


def test_exencion_sin_columna_configurada_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None, low_credit_risk_exemption=True)
    frame = pd.DataFrame({"days_past_due": [0]})
    with pytest.raises(IfrsStagingError, match="low_credit_risk_col"):
        _assign(cfg, frame)


def test_exencion_columna_ausente_levanta() -> None:
    cfg = IfrsStagingConfig(
        is_default_col=None, low_credit_risk_exemption=True, low_credit_risk_col="low_risk"
    )
    frame = pd.DataFrame({"days_past_due": [0]})
    with pytest.raises(IfrsStagingError, match="booleana 'low_risk'"):
        _assign(cfg, frame)


# ─────────────────────────── días de mora: validación (IfrsInputError) ───────────────────────────


def test_dpd_columna_faltante_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"otra": [0]})
    with pytest.raises(IfrsStagingError, match="días de mora 'days_past_due'"):
        _assign(cfg, frame)


def test_dpd_no_numerico_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": ["x"]})
    with pytest.raises(IfrsInputError, match="debe ser numérica"):
        _assign(cfg, frame)


def test_dpd_no_finito_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [np.inf]})
    with pytest.raises(IfrsInputError, match="debe ser finita"):
        _assign(cfg, frame)


def test_dpd_negativo_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [-5]})
    with pytest.raises(IfrsInputError, match="no puede ser negativa"):
        _assign(cfg, frame)


def test_dpd_no_entero_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [1.5]})
    with pytest.raises(IfrsInputError, match="debe ser entera"):
        _assign(cfg, frame)


# ─────────────────────────── series PD actuales: validación ───────────────────────────


def test_pd_life_desalineada_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [0, 0]})
    with pytest.raises(IfrsStagingError, match="alinear su longitud"):
        StagingEngine.from_config(cfg).assign(
            frame, pd_life=pd.Series([0.02]), pd_pit=pd.Series([0.01, 0.01])
        )


def test_pd_pit_no_finita_levanta() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [0]})
    with pytest.raises(IfrsStagingError, match="valores finitos"):
        StagingEngine.from_config(cfg).assign(
            frame, pd_life=pd.Series([0.02]), pd_pit=pd.Series([np.inf])
        )


# ─────────────────────────── no mutación e índice ───────────────────────────


def test_no_muta_el_frame() -> None:
    cfg = IfrsStagingConfig(is_default_col=None, origination_pd_life_col="pd_life_orig")
    frame = pd.DataFrame({"days_past_due": [35], "pd_life_orig": [0.05]})
    snapshot = frame.copy(deep=True)
    _assign(cfg, frame, pd_life=pd.Series([0.11]), pd_pit=pd.Series([0.01]))
    pd.testing.assert_frame_equal(frame, snapshot)


def test_preserva_indice_y_orden() -> None:
    cfg = IfrsStagingConfig(is_default_col=None)
    frame = pd.DataFrame({"days_past_due": [0, 35, 95]}, index=["x", "y", "z"])
    out = _assign(cfg, frame)
    assert list(out.index) == ["x", "y", "z"]
    assert out["stage"].tolist() == [1, 2, 3]


# ─────────────────────────── guards de dependencia perezosa ───────────────────────────


def _blocker(*modules: str) -> Any:
    """Construye un reemplazo de ``import_module`` que bloquea los módulos indicados."""
    real_import = importlib.import_module

    def block(name: str) -> Any:
        if name in modules:
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return real_import(name)

    return block


def test_assign_numpy_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(staging_module.importlib, "import_module", _blocker("numpy"))
    with pytest.raises(MissingDependencyError, match="numpy"):
        _assign(IfrsStagingConfig(is_default_col=None), pd.DataFrame({"days_past_due": [0]}))


def test_assign_pandas_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(staging_module.importlib, "import_module", _blocker("pandas"))
    with pytest.raises(MissingDependencyError, match="pandas"):
        _assign(IfrsStagingConfig(is_default_col=None), pd.DataFrame({"days_past_due": [0]}))
