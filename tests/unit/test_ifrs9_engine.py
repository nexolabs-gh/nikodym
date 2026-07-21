"""Tests de ``provisioning.ifrs9.engine``: secuencia canónica, goldens y contratos (SDD-16 §7).

Goldens verificables a mano (SDD-16 §11): la ECL de una operación anual con ``pd_marginal=(0.10,
0.08)``, ``LGD=0.40``, ``EAD=900`` (``drawn=800`` + ``0.5·(1000-800)``) y ``EIR=0.10`` da
``ECL_12m = 0.10·0.40·900/1.1 = 32.7272…`` y ``ECL_lifetime = +0.08·0.40·900/1.21 = 56.5289…``; el
multiescenario forward ``w=(0.5,0.3,0.2)`` con ``ECL_k=(50,80,120)`` da ``73.0``; el staging
Stage 2 por ratio lifetime ``0.11/0.05=2.2`` y Stage 3 por ``dpd=95``. Cubre modos PIT
(ttc_only/consume_pit/apply_vasicek), fuentes de escenario (single/config/forward), la PD base por
calibración, el contrato tidy de la term-structure y la no-mutación.
"""

from __future__ import annotations

import importlib
from typing import Any

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

import nikodym.provisioning.ifrs9.engine as engine_module
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9 import IfrsProvisioningConfig, IfrsProvisioningEngine
from nikodym.provisioning.ifrs9.config import (
    IfrsEadConfig,
    IfrsEclConfig,
    IfrsLgdConfig,
    IfrsPdConfig,
    IfrsScenarioConfig,
    IfrsStagingConfig,
)
from nikodym.provisioning.ifrs9.exceptions import (
    IfrsConfigError,
    IfrsEclError,
    IfrsInputError,
    IfrsTermStructureError,
)
from nikodym.provisioning.ifrs9.results import IfrsProvisionResult

# Golden SDD-16 §11 (EAD constante 900): 36/1.1 y 36/1.1 + 28.8/1.21.
_ECL_12M = 32.72727272727273
_ECL_LIFETIME = 56.528925619834716
# Golden Stage 2/3 (EAD 1000, LGD 0.5, pd_marg 0.06/0.05): 30/1.1 y 30/1.1 + 25/1.21.
_ECL_S2_12M = 27.272727272727273
_ECL_S2_LIFETIME = 47.93388429752066


def _frame(**overrides: Any) -> pd.DataFrame:
    """Frame económico mínimo de una operación ``op1`` (CCF EAD=900, recovery→LGD=0.40)."""
    base: dict[str, Any] = {
        "portfolio": "retail",
        "drawn": 800.0,
        "credit_limit": 1000.0,
        "ccf": 0.5,
        "recovery": 0.6,
        "ead": 900.0,
        "lgd": 0.40,
        "eir": 0.10,
        "days_past_due": 0,
        "is_default": False,
    }
    base.update(overrides)
    index = base.pop("_index", pd.Index(["op1"], name="loan_id"))
    return pd.DataFrame([base], index=index)


def _ts(
    *,
    pd_marginal: list[float] | None = None,
    periods: list[int] | None = None,
    scenario: list[Any] | None = None,
    row_id: list[str] | None = None,
    with_curve: bool = True,
    extra: dict[str, list[Any]] | None = None,
) -> pd.DataFrame:
    """Term-structure tidy (survival) de ``op1`` con invariante ``pd_cumulative = 1 - survival``."""
    marginal = pd_marginal if pd_marginal is not None else [0.10, 0.08]
    n = len(marginal)
    period = periods if periods is not None else list(range(1, n + 1))
    cumulative = np.cumsum(marginal).tolist()
    data: dict[str, list[Any]] = {
        "row_id": row_id if row_id is not None else ["op1"] * n,
        "period": period,
        "time_value": [float(p) for p in period],
        "pd_marginal": marginal,
        "scenario": scenario if scenario is not None else [None] * n,
        "warning_codes": [()] * n,
    }
    if with_curve:
        data["survival"] = [1.0 - c for c in cumulative]
        data["pd_cumulative"] = cumulative
    if extra:
        data.update(extra)
    return pd.DataFrame(data)


def _cfg(**pd_overrides: Any) -> IfrsProvisioningConfig:
    """Config base: survival, ttc_only, single, CCF EAD, LGD por recovery, horizonte 12m=1."""
    pd_kwargs: dict[str, Any] = {
        "term_structure_source": "survival",
        "pit_mode": "ttc_only",
        "horizon_12m_periods": 1,
    }
    pd_kwargs.update(pd_overrides)
    return IfrsProvisioningConfig(
        row_id_col=None,
        portfolio_col="portfolio",
        pd=IfrsPdConfig(**pd_kwargs),
        lgd=IfrsLgdConfig(method="provided", recovery_col="recovery"),
        ead=IfrsEadConfig(method="ccf", ccf_value=0.5),
        scenarios=IfrsScenarioConfig(source="single"),
        staging=IfrsStagingConfig(),
    )


def _run(
    cfg: IfrsProvisioningConfig,
    frame: pd.DataFrame,
    ts: pd.DataFrame,
    **kwargs: Any,
) -> IfrsProvisionResult:
    """Ejecuta ``calculate`` con la fecha de cálculo canónica de los tests."""
    return IfrsProvisioningEngine.from_config(cfg).calculate(
        frame, term_structure=ts, as_of_date="2026-01-31", **kwargs
    )


# ─────────────────────────── golden secuencia (Stage 1, ttc_only, CCF) ───────────────────────────


def test_golden_secuencia_stage1() -> None:
    result = _run(_cfg(), _frame(), _ts())

    detail = result.detail
    assert list(detail.columns) == [
        "row_id",
        "portfolio",
        "stage",
        "ead",
        "lgd",
        "eir",
        "pd_12m",
        "pd_life",
        "ecl_12m",
        "ecl_lifetime",
        "ecl_reported",
        "scenario_weights",
        "pd_basis",
        "warning_codes",
    ]
    row = detail.iloc[0]
    assert row["stage"] == 1
    np.testing.assert_allclose(row["ead"], 900.0)
    np.testing.assert_allclose(row["lgd"], 0.40)
    np.testing.assert_allclose(row["pd_life"], 0.18)
    np.testing.assert_allclose(row["ecl_12m"], _ECL_12M, rtol=1e-12)
    np.testing.assert_allclose(row["ecl_lifetime"], _ECL_LIFETIME, rtol=1e-12)
    # Stage 1 → reportado = 12m.
    np.testing.assert_allclose(row["ecl_reported"], _ECL_12M, rtol=1e-12)
    assert row["pd_basis"] == "ttc"
    assert row["scenario_weights"] == {"base": 1.0}

    staging = result.staging
    assert list(staging.columns) == [
        "row_id",
        "portfolio",
        "stage",
        "days_past_due",
        "pd_life_current",
        "pd_life_origination",
        "sicr_triggers",
        "low_credit_risk_exempt",
        "warning_codes",
    ]
    assert staging.iloc[0]["sicr_triggers"] == ()
    assert staging.iloc[0]["pd_life_origination"] is None
    assert staging.iloc[0]["warning_codes"] == ("FALTA-DATO-IFRS-4",)

    ts_out = result.ecl_term_structure
    np.testing.assert_allclose(
        ts_out["ecl_marginal"].to_numpy(),
        [_ECL_12M, 23.801652892561982],
        rtol=1e-12,
    )
    assert list(ts_out["scenario"]) == ["base", "base"]

    card = result.card
    assert card.n_rows == 1
    assert card.n_stage1 == 1
    np.testing.assert_allclose(card.total_ecl_reported, _ECL_12M, rtol=1e-12)
    assert card.scenarios == ("base",)
    assert card.falta_dato == ("FALTA-DATO-IFRS-4",)
    assert card.metric_sections["staging_migration"] == {
        "stage_1": 1,
        "stage_2": 0,
        "stage_3": 0,
    }


def test_records_por_operacion() -> None:
    result = _run(_cfg(), _frame(), _ts())
    assert len(result.stage_records) == 1
    assert len(result.ecl_records) == 1
    stage_record = result.stage_records[0]
    assert stage_record.row_id == "op1"
    assert stage_record.stage == 1
    ecl_record = result.ecl_records[0]
    np.testing.assert_allclose(ecl_record.ecl_reported, _ECL_12M, rtol=1e-12)
    assert ecl_record.pd_basis == "ttc"


def test_engine_from_config_devuelve_engine() -> None:
    assert isinstance(IfrsProvisioningEngine.from_config(_cfg()), IfrsProvisioningEngine)
    assert IfrsProvisioningEngine.config_cls is IfrsProvisioningConfig


# ─────────────────────────── staging Stage 2 (ratio) y Stage 3 (dpd) ───────────────────────────


def test_golden_staging_stage2_ratio() -> None:
    cfg = _cfg()
    cfg = cfg.model_copy(
        update={
            "ead": IfrsEadConfig(method="provided"),
            "lgd": IfrsLgdConfig(method="provided"),
            "staging": IfrsStagingConfig(origination_pd_life_col="origination_pd_life"),
        }
    )
    frame = _frame(ead=1000.0, lgd=0.5, origination_pd_life=0.05)
    result = _run(cfg, frame, _ts(pd_marginal=[0.06, 0.05]))

    row = result.detail.iloc[0]
    assert row["stage"] == 2
    np.testing.assert_allclose(row["pd_life"], 0.11, rtol=1e-12)
    # Stage 2 → reportado = lifetime.
    np.testing.assert_allclose(row["ecl_reported"], _ECL_S2_LIFETIME, rtol=1e-12)
    np.testing.assert_allclose(row["ecl_12m"], _ECL_S2_12M, rtol=1e-12)
    assert "sicr_pd_ratio" in result.staging.iloc[0]["sicr_triggers"]
    np.testing.assert_allclose(result.staging.iloc[0]["pd_life_origination"], 0.05)


def test_golden_staging_stage3_dpd() -> None:
    cfg = _cfg().model_copy(
        update={
            "ead": IfrsEadConfig(method="provided"),
            "lgd": IfrsLgdConfig(method="provided"),
        }
    )
    frame = _frame(ead=1000.0, lgd=0.5, days_past_due=95)
    result = _run(cfg, frame, _ts(pd_marginal=[0.06, 0.05]))

    row = result.detail.iloc[0]
    assert row["stage"] == 3
    np.testing.assert_allclose(row["ecl_reported"], _ECL_S2_LIFETIME, rtol=1e-12)
    assert "dpd_default_backstop" in result.staging.iloc[0]["sicr_triggers"]


# ─────────────────────────── multiescenario forward (consume_pit) ───────────────────────────


def test_multiescenario_forward_consume_pit_golden_73() -> None:
    cfg = IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="forward", pit_mode="consume_pit", horizon_12m_periods=1
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="forward"),
        ecl=IfrsEclConfig(),
    )
    frame = _frame(ead=1000.0, lgd=1.0, eir=0.0)
    ts = _ts(
        pd_marginal=[0.05, 0.08, 0.12],
        periods=[1, 1, 1],
        scenario=["base", "adverso", "severo"],
        extra={"scenario_weight": [0.5, 0.3, 0.2], "pd_basis": ["pit", "pit", "pit"]},
    )
    result = _run(cfg, frame, ts)

    # 0.5·50 + 0.3·80 + 0.2·120 = 73.0 (DF=1 con EIR=0).
    np.testing.assert_allclose(result.detail.iloc[0]["ecl_reported"], 73.0, rtol=1e-12)
    assert result.detail.iloc[0]["pd_basis"] == "pit"
    assert result.card.metric_sections["ecl_by_scenario"] == {
        "adverso": 80.0,
        "base": 50.0,
        "severo": 120.0,
    }


def test_ecl_by_scenario_viaja_con_su_rotulo() -> None:
    """``ecl_by_scenario`` publica el rótulo que explica por qué no cuadra con la reportada.

    Las dos cifras salen pegadas en el anexo de auditoría y difieren por construcción (aquí
    250 crudo vs. 73 reportada): sin rótulo la diferencia se lee como descuadre contable. El
    test ata el texto al hecho numérico que describe —si alguna vez reconciliaran, el rótulo
    estaría mintiendo— y comprueba que nombra los dos motivos de la brecha.
    """
    cfg = IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="forward", pit_mode="consume_pit", horizon_12m_periods=1
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="forward"),
        ecl=IfrsEclConfig(),
    )
    ts = _ts(
        pd_marginal=[0.05, 0.08, 0.12],
        periods=[1, 1, 1],
        scenario=["base", "adverso", "severo"],
        extra={"scenario_weight": [0.5, 0.3, 0.2], "pd_basis": ["pit", "pit", "pit"]},
    )
    metric_sections = _run(cfg, _frame(ead=1000.0, lgd=1.0, eir=0.0), ts).card.metric_sections
    basis = metric_sections["ecl_by_scenario_basis"]

    crudo = sum(metric_sections["ecl_by_scenario"].values())
    np.testing.assert_allclose(crudo, 250.0, rtol=1e-12)
    assert crudo != pytest.approx(73.0)

    assert "total_ecl_reported" in basis
    assert "scenario_weights" in basis  # motivo 1: la cruda no pondera por escenario.
    assert "Stage 1" in basis  # motivo 2: la reportada trunca Stage 1 a 12 meses.
    assert "no reconcilian" in basis

    # Ordenado alfabéticamente por el anexo, el rótulo cae inmediatamente bajo la cifra que
    # explica; si dejaran de ser adyacentes, volvería a leerse una cifra huérfana.
    claves = sorted(metric_sections)
    assert claves[claves.index("ecl_by_scenario") + 1] == "ecl_by_scenario_basis"


def test_scenarios_source_config_pondera() -> None:
    cfg = _cfg().model_copy(
        update={
            "ead": IfrsEadConfig(method="provided"),
            "lgd": IfrsLgdConfig(method="provided"),
            "scenarios": IfrsScenarioConfig(source="config", weights={"base": 0.5, "adverso": 0.5}),
        }
    )
    frame = _frame(ead=1000.0, lgd=1.0, eir=0.0)
    ts = _ts(
        pd_marginal=[0.10, 0.20],
        periods=[1, 1],
        scenario=["base", "adverso"],
    )
    result = _run(cfg, frame, ts)
    # 0.5·(0.10·1000) + 0.5·(0.20·1000) = 50 + 100 = 150.
    np.testing.assert_allclose(result.detail.iloc[0]["ecl_reported"], 150.0, rtol=1e-12)


# ─────────────────────────── PD PIT: apply_vasicek ───────────────────────────


def test_apply_vasicek_transforma_pd() -> None:
    cfg = IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="survival",
            pit_mode="apply_vasicek",
            rho=0.15,
            systemic_factor_col="Z",
            horizon_12m_periods=1,
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="single"),
    )
    frame = _frame(ead=1000.0, lgd=0.5, eir=0.0)
    ts = _ts(
        pd_marginal=[0.02],
        periods=[1],
        with_curve=False,
        extra={"Z": [0.0]},
    )
    result = _run(cfg, frame, ts)
    # Vasicek con Z=0: Phi(PhiInv(0.02)/sqrt(0.85)) (efecto Jensen, != 0.02).
    expected = float(norm.cdf(norm.ppf(0.02) / np.sqrt(0.85)))
    np.testing.assert_allclose(
        result.ecl_term_structure.iloc[0]["pd_marginal"], expected, rtol=1e-12
    )
    assert result.detail.iloc[0]["pd_basis"] == "pit"


def test_apply_vasicek_sin_rho_falla() -> None:
    """Sin rho el motor levanta en runtime aunque ``fail_on_falta_dato=False`` difiera el config.

    Fija que NO existe ruta degradada FALTA-DATO para rho: el config con
    ``fail_on_falta_dato=False`` construye, pero ``_apply_vasicek`` falla igual.
    """
    cfg = IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="survival",
            pit_mode="apply_vasicek",
            rho=None,
            systemic_factor_col="Z",
            horizon_12m_periods=1,
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="single"),
        fail_on_falta_dato=False,
    )
    frame = _frame(ead=1000.0, lgd=0.5, eir=0.0)
    ts = _ts(pd_marginal=[0.02], periods=[1], with_curve=False, extra={"Z": [0.0]})
    with pytest.raises(IfrsConfigError, match="rho escalar"):
        _run(cfg, frame, ts)


def test_apply_vasicek_sin_columna_z_falla() -> None:
    cfg = IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="survival",
            pit_mode="apply_vasicek",
            rho=0.15,
            systemic_factor_col="Z",
            horizon_12m_periods=1,
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="single"),
    )
    frame = _frame(ead=1000.0, lgd=0.5, eir=0.0)
    ts = _ts(pd_marginal=[0.02], periods=[1], with_curve=False)  # sin columna Z
    with pytest.raises(IfrsConfigError, match="factor sistémico Z"):
        _run(cfg, frame, ts)


def test_apply_vasicek_sin_systemic_factor_col_falla_en_runtime() -> None:
    """``fail_on_falta_dato=False`` tampoco habilita una ruta degradada para el Z ausente."""
    cfg = IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="survival",
            pit_mode="apply_vasicek",
            rho=0.15,
            horizon_12m_periods=1,
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="single"),
        fail_on_falta_dato=False,
    )
    frame = _frame(ead=1000.0, lgd=0.5, eir=0.0)
    ts = _ts(pd_marginal=[0.02], periods=[1], with_curve=False)
    with pytest.raises(IfrsConfigError, match="factor sistémico Z"):
        _run(cfg, frame, ts)


# ─────────────────────────── PD PIT: guard anti doble ajuste (pd_basis) ───────────────────────────


def _cfg_vasicek() -> IfrsProvisioningConfig:
    """Config ``apply_vasicek`` completa (rho y columna Z) para los tests del guard TTC."""
    return IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="survival",
            pit_mode="apply_vasicek",
            rho=0.15,
            systemic_factor_col="Z",
            horizon_12m_periods=1,
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="single"),
    )


def test_apply_vasicek_sobre_pd_basis_pit_falla() -> None:
    """Aplicar Vasicek a una term-structure ya PIT (forward) se rechaza: doble ajuste macro."""
    frame = _frame(ead=1000.0, lgd=0.5, eir=0.0)
    ts = _ts(
        pd_marginal=[0.02],
        periods=[1],
        with_curve=False,
        extra={"Z": [0.0], "pd_basis": ["pit"]},
    )
    with pytest.raises(IfrsConfigError, match="doble ajuste"):
        _run(_cfg_vasicek(), frame, ts)


def test_apply_vasicek_pd_basis_mixto_falla() -> None:
    """Una term-structure con ``pd_basis`` mixto tampoco es elegible para Vasicek."""
    frame = _frame(ead=1000.0, lgd=0.5, eir=0.0)
    ts = _ts(
        pd_marginal=[0.02, 0.02],
        periods=[1, 2],
        with_curve=False,
        extra={"Z": [0.0, 0.0], "pd_basis": ["ttc", "pit"]},
    )
    with pytest.raises(IfrsConfigError, match="doble ajuste"):
        _run(_cfg_vasicek(), frame, ts)


def test_apply_vasicek_pd_basis_nan_falla() -> None:
    """``pd_basis`` faltante (NaN) en la columna presente se rechaza conservadoramente."""
    frame = _frame(ead=1000.0, lgd=0.5, eir=0.0)
    ts = _ts(
        pd_marginal=[0.02],
        periods=[1],
        with_curve=False,
        extra={"Z": [0.0], "pd_basis": [float("nan")]},
    )
    with pytest.raises(IfrsConfigError, match="doble ajuste"):
        _run(_cfg_vasicek(), frame, ts)


def test_apply_vasicek_pd_basis_ttc_explicito_ok() -> None:
    """Etiquetar TTC explícito no rompe la ruta legítima: mismo golden Jensen del caso base."""
    frame = _frame(ead=1000.0, lgd=0.5, eir=0.0)
    ts = _ts(
        pd_marginal=[0.02],
        periods=[1],
        with_curve=False,
        extra={"Z": [0.0], "pd_basis": ["ttc"]},
    )
    result = _run(_cfg_vasicek(), frame, ts)
    expected = float(norm.cdf(norm.ppf(0.02) / np.sqrt(0.85)))
    np.testing.assert_allclose(
        result.ecl_term_structure.iloc[0]["pd_marginal"], expected, rtol=1e-12
    )
    assert result.detail.iloc[0]["pd_basis"] == "pit"


# ─────────────────────────── PD PIT: consume_pit ───────────────────────────


def test_consume_pit_sin_pd_basis_falla() -> None:
    cfg = _cfg(pit_mode="consume_pit").model_copy(
        update={"ead": IfrsEadConfig(method="provided"), "lgd": IfrsLgdConfig(method="provided")}
    )
    frame = _frame(ead=1000.0, lgd=0.5)
    with pytest.raises(IfrsConfigError, match="pd_basis"):
        _run(cfg, frame, _ts())  # survival sin pd_basis


def test_consume_pit_pd_basis_ttc_falla() -> None:
    cfg = _cfg(pit_mode="consume_pit").model_copy(
        update={"ead": IfrsEadConfig(method="provided"), "lgd": IfrsLgdConfig(method="provided")}
    )
    frame = _frame(ead=1000.0, lgd=0.5)
    ts = _ts(extra={"pd_basis": ["ttc", "ttc"]})
    with pytest.raises(IfrsConfigError, match="pd_basis='pit'"):
        _run(cfg, frame, ts)


# ─────────────────────────── PD base por calibración ───────────────────────────


def _calibration_cfg() -> IfrsProvisioningConfig:
    """Config con ``base_pd_source='calibration'`` y EAD/LGD provistas."""
    return _cfg(base_pd_source="calibration").model_copy(
        update={"ead": IfrsEadConfig(method="provided"), "lgd": IfrsLgdConfig(method="provided")}
    )


def test_base_pd_source_calibration_ancla_pd_12m() -> None:
    frame = _frame(ead=1000.0, lgd=0.5)
    calibrated = pd.DataFrame({"pd_calibrated": [0.033]}, index=["op1"])
    result = _run(_calibration_cfg(), frame, _ts(), calibrated_pd=calibrated)
    # pd_12m anclada a la calibrada; pd_life sigue viniendo de la term-structure.
    np.testing.assert_allclose(result.detail.iloc[0]["pd_12m"], 0.033)
    np.testing.assert_allclose(result.detail.iloc[0]["pd_life"], 0.18)


def test_calibration_sin_frame_falla() -> None:
    frame = _frame(ead=1000.0, lgd=0.5)
    with pytest.raises(IfrsConfigError, match="frame de PD calibrada"):
        _run(_calibration_cfg(), frame, _ts(), calibrated_pd=None)


def test_calibration_sin_columna_falla() -> None:
    frame = _frame(ead=1000.0, lgd=0.5)
    calibrated = pd.DataFrame({"otra": [0.033]}, index=["op1"])
    with pytest.raises(IfrsConfigError, match="pd_calibrated"):
        _run(_calibration_cfg(), frame, _ts(), calibrated_pd=calibrated)


def test_calibration_sin_cobertura_falla() -> None:
    frame = _frame(ead=1000.0, lgd=0.5)
    calibrated = pd.DataFrame({"pd_calibrated": [0.033]}, index=["otra"])
    with pytest.raises(IfrsConfigError, match="no cubre"):
        _run(_calibration_cfg(), frame, _ts(), calibrated_pd=calibrated)


# ─────────────────────────── contrato tidy de la term-structure ───────────────────────────


def test_term_structure_columna_faltante() -> None:
    ts = _ts().drop(columns=["pd_marginal"])
    with pytest.raises(IfrsTermStructureError, match="columnas faltantes"):
        _run(_cfg(), _frame(), ts)


def test_term_structure_vacia() -> None:
    ts = _ts().iloc[0:0]
    with pytest.raises(IfrsTermStructureError, match="no puede estar vacía"):
        _run(_cfg(), _frame(), ts)


def test_term_structure_pd_marginal_fuera_de_rango() -> None:
    ts = _ts(pd_marginal=[1.5, 0.08])
    with pytest.raises(IfrsTermStructureError, match=r"\[0, 1\]"):
        _run(_cfg(), _frame(), ts)


def test_term_structure_invariante_rota() -> None:
    ts = _ts()
    ts["survival"] = [0.5, 0.5]  # rompe pd_cumulative = 1 - survival
    with pytest.raises(IfrsTermStructureError, match="invariante"):
        _run(_cfg(), _frame(), ts)


def test_term_structure_no_finita() -> None:
    ts = _ts(pd_marginal=[np.inf, 0.08])
    with pytest.raises(IfrsTermStructureError, match="finita"):
        _run(_cfg(), _frame(), ts)


def test_term_structure_no_numerica() -> None:
    ts = _ts()
    ts["pd_marginal"] = ["x", "y"]
    with pytest.raises(IfrsTermStructureError, match="numérica"):
        _run(_cfg(), _frame(), ts)


def test_term_structure_period_invalido() -> None:
    ts = _ts(periods=[0, 1])
    with pytest.raises(IfrsTermStructureError, match="entero mayor o igual a 1"):
        _run(_cfg(), _frame(), ts)


def test_term_structure_cobertura_incompleta() -> None:
    ts = _ts(row_id=["opX", "opX"])
    with pytest.raises(IfrsTermStructureError, match="cubrir exactamente"):
        _run(_cfg(), _frame(), ts)


# ─────────────────────────── identificadores y columnas raíz ───────────────────────────


def test_row_id_col_explicito() -> None:
    cfg = _cfg().model_copy(update={"row_id_col": "loan_ref"})
    frame = _frame(loan_ref="op1")
    result = _run(cfg, frame, _ts())
    assert result.detail.iloc[0]["row_id"] == "op1"


def test_row_id_col_faltante() -> None:
    cfg = _cfg().model_copy(update={"row_id_col": "no_existe"})
    with pytest.raises(IfrsInputError, match="row_id_col"):
        _run(cfg, _frame(), _ts())


def test_row_id_no_unico() -> None:
    frame = pd.concat([_frame(), _frame(_index=pd.Index(["op1"]))])
    with pytest.raises(IfrsInputError, match="únicos"):
        _run(_cfg(), frame, _ts())


def test_portfolio_col_faltante() -> None:
    frame = _frame().drop(columns=["portfolio"])
    with pytest.raises(IfrsInputError, match="portfolio_col"):
        _run(_cfg(), frame, _ts())


def test_eir_col_faltante() -> None:
    frame = _frame().drop(columns=["eir"])
    with pytest.raises(IfrsInputError, match=r"\(eir\)"):
        _run(_cfg(), frame, _ts())


def test_eir_no_numerico() -> None:
    frame = _frame(eir="x")
    with pytest.raises(IfrsInputError, match="numérico"):
        _run(_cfg(), frame, _ts())


def test_eir_no_finito() -> None:
    frame = _frame(eir=np.inf)
    with pytest.raises(IfrsInputError, match="finitos"):
        _run(_cfg(), frame, _ts())


def test_as_of_date_vacio() -> None:
    with pytest.raises(IfrsInputError, match="as_of_date"):
        IfrsProvisioningEngine.from_config(_cfg()).calculate(
            _frame(), term_structure=_ts(), as_of_date="  "
        )


@pytest.mark.parametrize("kwarg", ["frame", "term_structure"])
def test_insumo_no_dataframe(kwarg: str) -> None:
    args: dict[str, Any] = {"frame": _frame(), "term_structure": _ts()}
    args[kwarg] = object()
    with pytest.raises(IfrsInputError, match=r"pandas\.DataFrame"):
        IfrsProvisioningEngine.from_config(_cfg()).calculate(
            args["frame"], term_structure=args["term_structure"], as_of_date="2026-01-31"
        )


def test_calibrated_no_dataframe() -> None:
    with pytest.raises(IfrsInputError, match=r"pandas\.DataFrame"):
        _run(_calibration_cfg(), _frame(ead=1000.0, lgd=0.5), _ts(), calibrated_pd=object())


# ─────────────────────────── horizonte lifetime (max_lifetime) ───────────────────────────


def test_max_lifetime_trunca_soporte() -> None:
    cfg = _cfg(max_lifetime_periods=1).model_copy(
        update={"ead": IfrsEadConfig(method="provided"), "lgd": IfrsLgdConfig(method="provided")}
    )
    frame = _frame(ead=1000.0, lgd=0.5)
    result = _run(cfg, frame, _ts(pd_marginal=[0.10, 0.08]))
    # Sólo el período 1 sobrevive: pd_life = 0.10 y la evidencia trae 1 fila.
    np.testing.assert_allclose(result.detail.iloc[0]["pd_life"], 0.10)
    assert len(result.ecl_term_structure.index) == 1


def test_max_lifetime_sin_periodos() -> None:
    cfg = _cfg(max_lifetime_periods=1)
    ts = _ts(pd_marginal=[0.08], periods=[2])
    with pytest.raises(IfrsTermStructureError, match="No quedan períodos"):
        _run(cfg, _frame(), ts)


# ─────────────────────────── fuentes de escenario (guards) ───────────────────────────


def test_single_con_multiples_escenarios_falla() -> None:
    cfg = _cfg().model_copy(
        update={"ead": IfrsEadConfig(method="provided"), "lgd": IfrsLgdConfig(method="provided")}
    )
    ts = _ts(pd_marginal=[0.10, 0.10], periods=[1, 1], scenario=["base", "adverso"])
    with pytest.raises(IfrsConfigError, match="exactamente un escenario"):
        _run(cfg, _frame(ead=1000.0, lgd=0.5), ts)


def test_config_pesos_no_cubren_escenarios() -> None:
    cfg = _cfg().model_copy(
        update={
            "ead": IfrsEadConfig(method="provided"),
            "lgd": IfrsLgdConfig(method="provided"),
            "scenarios": IfrsScenarioConfig(source="config", weights={"base": 1.0}),
        }
    )
    ts = _ts(pd_marginal=[0.10, 0.10], periods=[1, 1], scenario=["base", "adverso"])
    with pytest.raises(IfrsConfigError, match="cubran exactamente"):
        _run(cfg, _frame(ead=1000.0, lgd=0.5), ts)


def test_forward_sin_columna_scenario_weight() -> None:
    cfg = IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="forward", pit_mode="ttc_only", horizon_12m_periods=1
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="forward"),
    )
    ts = _ts(pd_marginal=[0.10], periods=[1], scenario=["base"])
    with pytest.raises(IfrsConfigError, match="scenario_weight"):
        _run(cfg, _frame(ead=1000.0, lgd=0.5), ts)


def test_forward_peso_no_constante() -> None:
    cfg = IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="forward", pit_mode="ttc_only", horizon_12m_periods=1
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="forward"),
    )
    ts = _ts(
        pd_marginal=[0.10, 0.08],
        periods=[1, 2],
        scenario=["base", "base"],
        extra={"scenario_weight": [1.0, 0.9]},
    )
    with pytest.raises(IfrsConfigError, match="no es constante"):
        _run(cfg, _frame(ead=1000.0, lgd=0.5), ts)


# ─────────────────────────── normalización de escenario ───────────────────────────


def test_scenario_nan_normaliza_a_base() -> None:
    ts = _ts(scenario=[float("nan"), float("nan")])
    result = _run(_cfg(), _frame(), ts)
    assert list(result.ecl_term_structure["scenario"]) == ["base", "base"]


def test_sin_columna_scenario_normaliza_a_base() -> None:
    ts = _ts().drop(columns=["scenario"])
    result = _run(_cfg(), _frame(), ts)
    assert list(result.ecl_term_structure["scenario"]) == ["base", "base"]


# ─────────────────────────── LGD provista por columna y resumen ───────────────────────────


def test_lgd_provided_por_columna() -> None:
    cfg = _cfg().model_copy(
        update={"ead": IfrsEadConfig(method="provided"), "lgd": IfrsLgdConfig(method="provided")}
    )
    frame = _frame(ead=1000.0, lgd=0.7)
    result = _run(cfg, frame, _ts())
    np.testing.assert_allclose(result.detail.iloc[0]["lgd"], 0.7)


def test_summary_agrega_por_cartera_stage() -> None:
    cfg = _cfg().model_copy(
        update={"ead": IfrsEadConfig(method="provided"), "lgd": IfrsLgdConfig(method="provided")}
    )
    frame = pd.DataFrame(
        [
            {"portfolio": "retail", "ead": 1000.0, "lgd": 0.5, "eir": 0.0, "days_past_due": 0},
            {"portfolio": "sme", "ead": 0.0, "lgd": 0.5, "eir": 0.0, "days_past_due": 0},
        ],
        index=pd.Index(["op1", "op2"]),
    )
    ts = _ts(pd_marginal=[0.10, 0.10], periods=[1, 1], row_id=["op1", "op2"])
    result = _run(cfg, frame, ts)
    summary = result.summary
    assert list(summary["portfolio"]) == ["retail", "sme"]
    assert list(summary.columns) == [
        "portfolio",
        "stage",
        "scenario",
        "n_rows",
        "total_ead",
        "total_ecl_reported",
        "coverage_ratio",
        "warning_codes",
    ]
    # La cartera sme tiene EAD=0 → coverage_ratio=0.0 (rama sin división).
    sme = summary.loc[summary["portfolio"] == "sme"].iloc[0]
    assert sme["coverage_ratio"] == 0.0
    retail = summary.loc[summary["portfolio"] == "retail"].iloc[0]
    np.testing.assert_allclose(retail["coverage_ratio"], 50.0 / 1000.0, rtol=1e-12)


# ─────────────────────────── no-mutación e insumos ───────────────────────────


def test_no_muta_insumos() -> None:
    frame = _frame(ead=1000.0, lgd=0.5)
    ts = _ts()
    calibrated = pd.DataFrame({"pd_calibrated": [0.033]}, index=["op1"])
    frame_snapshot = frame.copy(deep=True)
    ts_snapshot = ts.copy(deep=True)
    calibrated_snapshot = calibrated.copy(deep=True)
    _run(_calibration_cfg(), frame, ts, calibrated_pd=calibrated)
    pd.testing.assert_frame_equal(frame, frame_snapshot)
    pd.testing.assert_frame_equal(ts, ts_snapshot)
    pd.testing.assert_frame_equal(calibrated, calibrated_snapshot)


def test_reproducibilidad() -> None:
    first = _run(_cfg(), _frame(), _ts())
    second = _run(_cfg(), _frame(), _ts())
    pd.testing.assert_frame_equal(first.detail, second.detail)
    pd.testing.assert_frame_equal(first.ecl_term_structure, second.ecl_term_structure)
    assert first.card.model_dump(mode="json") == second.card.model_dump(mode="json")


# ─────────────────────────── dependencias perezosas ───────────────────────────


def _blocker(*modules: str) -> Any:
    """Construye un reemplazo de ``import_module`` que bloquea los módulos indicados."""
    real_import = importlib.import_module

    def block(name: str) -> Any:
        if name in modules:
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return real_import(name)

    return block


def test_calculate_numpy_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module.importlib, "import_module", _blocker("numpy"))
    with pytest.raises(MissingDependencyError, match="numpy"):
        _run(_cfg(), _frame(), _ts())


def test_calculate_pandas_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module.importlib, "import_module", _blocker("pandas"))
    with pytest.raises(MissingDependencyError, match="pandas"):
        _run(_cfg(), _frame(), _ts())


def test_dependency_versions_ramas() -> None:
    base = engine_module._dependency_versions(_cfg())
    assert set(base) == {"pandas", "numpy"}
    vasicek_cfg = _cfg(pit_mode="apply_vasicek", rho=0.15, systemic_factor_col="Z")
    with_scipy = engine_module._dependency_versions(vasicek_cfg)
    assert "scipy" in with_scipy
    beta_cfg = _cfg().model_copy(
        update={
            "lgd": IfrsLgdConfig(method="beta_regression", covariate_cols=("x",)),
        }
    )
    assert "statsmodels" in engine_module._dependency_versions(beta_cfg)


def test_dependency_versions_no_instalado(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(_distribution: str) -> str:
        raise engine_module.metadata.PackageNotFoundError

    monkeypatch.setattr(engine_module.metadata, "version", raise_not_found)
    versions = engine_module._dependency_versions(_cfg())
    assert versions == {"pandas": "no_instalado", "numpy": "no_instalado"}


# ─────────────────────────── guard anti escenario medio (runtime) ───────────────────────────


def test_forbid_mean_scenario_single_falla() -> None:
    """Con el guard activo, un escenario 'mean' en la term-structure aborta el cálculo."""
    ts = _ts(scenario=["mean", "mean"])
    with pytest.raises(IfrsConfigError, match="reservados"):
        _run(_cfg(), _frame(), ts)


def test_forbid_mean_scenario_case_insensitive() -> None:
    """El veto de nombres reservados es case-insensitive ('Mean', 'AVERAGE')."""
    ts = _ts(scenario=["Mean", "AVERAGE"])
    with pytest.raises(IfrsConfigError, match="reservados"):
        _run(_cfg(), _frame(), ts)


def test_forbid_mean_scenario_escape_hatch_calcula() -> None:
    """Con ``forbid_mean_scenario=False`` el cálculo procede (decisión consciente y auditada).

    El nombre del escenario no cambia ningún número: mismo golden Stage 1 del caso base.
    """
    cfg = _cfg().model_copy(
        update={
            "scenarios": IfrsScenarioConfig(source="single", forbid_mean_scenario=False),
        }
    )
    result = _run(cfg, _frame(), _ts(scenario=["mean", "mean"]))
    np.testing.assert_allclose(result.detail.iloc[0]["ecl_reported"], _ECL_12M, rtol=1e-12)
    assert result.card.scenarios == ("mean",)


def test_forbid_mean_scenario_source_forward_falla() -> None:
    """El guard cubre ``source='forward'``: 'weighted_mean_input' aborta antes de ponderar."""
    cfg = _cfg().model_copy(
        update={
            "ead": IfrsEadConfig(method="provided"),
            "lgd": IfrsLgdConfig(method="provided"),
            "scenarios": IfrsScenarioConfig(source="forward"),
        }
    )
    frame = _frame(ead=1000.0, lgd=1.0, eir=0.0)
    ts = _ts(
        pd_marginal=[0.10, 0.20],
        periods=[1, 1],
        scenario=["base", "weighted_mean_input"],
        extra={"scenario_weight": [0.7, 0.3]},
    )
    with pytest.raises(IfrsConfigError, match="reservados"):
        _run(cfg, frame, ts)


# ─────────────────────────── LGD forward ignorada (FALTA-DATO-IFRS-6) ───────────────────────────


def _cfg_forward_consume_pit() -> IfrsProvisioningConfig:
    """Config del golden 73.0: forward + consume_pit, EAD/LGD provistas, horizonte 12m=1."""
    return IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="forward", pit_mode="consume_pit", horizon_12m_periods=1
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="forward"),
        ecl=IfrsEclConfig(),
    )


def _ts_forward_multiescenario(**extra_cols: list[Any]) -> pd.DataFrame:
    """Term-structure forward del golden 73.0, con columnas extra opcionales (p. ej. ``lgd``)."""
    extra: dict[str, list[Any]] = {
        "scenario_weight": [0.5, 0.3, 0.2],
        "pd_basis": ["pit", "pit", "pit"],
    }
    extra.update(extra_cols)
    return _ts(
        pd_marginal=[0.05, 0.08, 0.12],
        periods=[1, 1, 1],
        scenario=["base", "adverso", "severo"],
        extra=extra,
    )


def test_lgd_forward_ignorada_golden_invariante() -> None:
    """La ECL es invariante ante ``ts['lgd']``: la LGD forward NO precede en v1.

    Golden de contraste (documenta la materialidad del descarte): si la LGD forward
    ``[0.9, 0.5, 0.2]`` precediera a la del frame (1.0), la ECL sería
    ``0.5·(50·0.9) + 0.3·(80·0.5) + 0.2·(120·0.2) = 39.3``, no 73.0. Este test es el guard
    que DEBE fallar cuando alguien implemente la precedencia sin pasar por su SDD.
    """
    frame = _frame(ead=1000.0, lgd=1.0, eir=0.0)
    ts = _ts_forward_multiescenario(lgd=[0.9, 0.5, 0.2])
    result = _run(_cfg_forward_consume_pit(), frame, ts)
    np.testing.assert_allclose(result.detail.iloc[0]["ecl_reported"], 73.0, rtol=1e-12)
    np.testing.assert_allclose(result.detail.iloc[0]["lgd"], 1.0)
    assert set(result.ecl_term_structure["lgd"].tolist()) == {1.0}
    assert "FALTA-DATO-IFRS-6" in result.card.falta_dato
    assert "FALTA-DATO-IFRS-6" in result.staging.iloc[0]["warning_codes"]


def test_lgd_forward_toda_nula_no_emite_warning() -> None:
    """La columna ``lgd`` toda-``None`` (forward sin satellite LGD) no cuenta como LGD forward."""
    frame = _frame(ead=1000.0, lgd=1.0, eir=0.0)
    result = _run(_cfg_forward_consume_pit(), frame, _ts_forward_multiescenario(lgd=[None] * 3))
    np.testing.assert_allclose(result.detail.iloc[0]["ecl_reported"], 73.0, rtol=1e-12)
    assert "FALTA-DATO-IFRS-6" not in result.card.falta_dato


def test_lgd_forward_ausente_no_emite_warning() -> None:
    """Sin columna ``lgd`` en la ts (survival/markov) no se emite el aviso: no hay qué descartar."""
    result = _run(_cfg(), _frame(), _ts())
    assert "FALTA-DATO-IFRS-6" not in result.card.falta_dato


def test_lgd_base_sola_no_emite_warning() -> None:
    """``lgd_base`` poblada con ``lgd`` toda-``None`` NO emite el aviso (exclusión por diseño).

    Es el output real de forward con ``target_components=('pd',)``: ``lgd_base`` es linaje de la
    LGD base de entrada, sin condicionamiento macro — no hay información forward-looking perdida
    (SDD-16 FALTA-DATO-IFRS-6, SDD-20 FALTA-DATO-FWD-6).
    """
    frame = _frame(ead=1000.0, lgd=1.0, eir=0.0)
    ts = _ts_forward_multiescenario(lgd=[None] * 3, lgd_base=[0.4] * 3)
    result = _run(_cfg_forward_consume_pit(), frame, ts)
    np.testing.assert_allclose(result.detail.iloc[0]["ecl_reported"], 73.0, rtol=1e-12)
    assert "FALTA-DATO-IFRS-6" not in result.card.falta_dato


# ─────────────────────────── pesos cero: frontera forward→IFRS 9 ───────────────────────────


def test_peso_cero_forward_aborta_en_ecl_engine() -> None:
    """Una ts forward con un escenario de peso 0 aborta con IfrsEclError (fallo tardío, fijado).

    Caracterización de la brecha 'pesos cero incompatibles': forward permite w=0 (SDD-20) pero
    ningún ``scenarios.source`` de IFRS 9 puede consumir esa ts; el rechazo ocurre dentro de
    ``EclEngine`` tras staging. La resolución de fondo queda como decisión posterior (SDD-16 §8).
    """
    frame = _frame(ead=1000.0, lgd=1.0, eir=0.0)
    ts = _ts_forward_multiescenario(scenario_weight=[0.7, 0.3, 0.0])
    with pytest.raises(IfrsEclError, match="estrictamente positivo"):
        _run(_cfg_forward_consume_pit(), frame, ts)


def test_peso_cero_filtrado_aguas_arriba_calcula() -> None:
    """La vía soportada: excluir las filas del escenario peso-0 antes de entregar la ts.

    Con pesos ``{base: 0.7, adverso: 0.3}`` el golden es ``0.7·50 + 0.3·80 = 59.0`` — idéntico
    al teórico con peso 0 (contribución nula), lo que documenta el workaround sin cambio numérico.
    """
    frame = _frame(ead=1000.0, lgd=1.0, eir=0.0)
    ts = _ts(
        pd_marginal=[0.05, 0.08],
        periods=[1, 1],
        scenario=["base", "adverso"],
        extra={"scenario_weight": [0.7, 0.3], "pd_basis": ["pit", "pit"]},
    )
    result = _run(_cfg_forward_consume_pit(), frame, ts)
    np.testing.assert_allclose(result.detail.iloc[0]["ecl_reported"], 59.0, rtol=1e-12)
