"""Tests de ``provisioning.ifrs9.ecl``: motor ECL marginal, descuento EIR y multiescenario.

Goldens verificables a mano (SDD-16 §11): 1 escenario anual con
``PD_marg=(0.10, 0.08)``, ``LGD=0.40``, ``EAD=(1000, 900)``, ``EIR=0.10`` ->
``ECL = 0.10·0.40·1000/1.1 + 0.08·0.40·900/1.1² = 60.165289…``; multiescenario
``w=(0.5, 0.3, 0.2)`` con ``ECL_k=(50, 80, 120)`` -> ``73.0``; truncado por stage (Stage 1 corta en
``H_12m``, Stage 2/3 hasta ``T_max``); las dos convenciones de descuento; Stage 3 directo
``EAD·LGD·DF(0)``; el invariante ``ecl_reported == ecl_12m ⟺ stage==1``; y errores controlados
(``IfrsEclError``) ante malla/pesos/EIR/stage inválidos o factor de descuento fuera de ``(0, 1]``.
Cobertura de los guards de dependencia perezosa.
"""

from __future__ import annotations

import importlib
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym.provisioning.ifrs9.ecl as ecl_module
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9 import EclEngine
from nikodym.provisioning.ifrs9.config import IfrsEclConfig
from nikodym.provisioning.ifrs9.exceptions import IfrsEclError

# Golden SDD-16 §11: 0.10·0.40·1000/1.1 + 0.08·0.40·900/1.1² = 60.165289256198344.
_ECL_GOLDEN = 60.16528925619835


def _components(
    *,
    row_id: list[Any],
    scenario: list[Any],
    period: list[int],
    time_value: list[float],
    pd_marginal: list[float],
    lgd: list[float],
    ead: list[float],
    index: Any = None,
) -> pd.DataFrame:
    """Arma una malla tidy de componentes por ``(row_id, scenario, period)``."""
    return pd.DataFrame(
        {
            "row_id": row_id,
            "scenario": scenario,
            "period": period,
            "time_value": time_value,
            "pd_marginal": pd_marginal,
            "lgd": lgd,
            "ead": ead,
        },
        index=index,
    )


def _single_scenario_two_periods(stage: int = 2) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Malla del golden de 1 escenario anual y sus parámetros de ``compute``."""
    components = _components(
        row_id=["op1", "op1"],
        scenario=["base", "base"],
        period=[1, 2],
        time_value=[1.0, 2.0],
        pd_marginal=[0.10, 0.08],
        lgd=[0.40, 0.40],
        ead=[1000.0, 900.0],
    )
    params: dict[str, Any] = {
        "eir": pd.Series([0.10], index=["op1"]),
        "stages": pd.Series([stage], index=["op1"]),
        "weights": {"base": 1.0},
        "horizon_12m": 1,
    }
    return components, params


# ─────────────────────────── golden ECL marginal (1 escenario, anual) ───────────────────────────


def test_ecl_marginal_golden_un_escenario() -> None:
    components, params = _single_scenario_two_periods(stage=2)
    ts, detail = EclEngine.from_config(IfrsEclConfig()).compute(components, **params)

    assert list(ts.columns) == [
        "row_id",
        "scenario",
        "period",
        "time_value",
        "pd_marginal",
        "lgd",
        "ead",
        "discount_factor",
        "ecl_marginal",
    ]
    # Marginal por período: 0.10·0.40·1000/1.1 = 36.363636… ; 0.08·0.40·900/1.21 = 23.801652….
    np.testing.assert_allclose(
        ts["ecl_marginal"].to_numpy(), [36.36363636363636, 23.801652892561975], rtol=1e-12
    )
    np.testing.assert_allclose(
        ts["discount_factor"].to_numpy(), [1.0 / 1.1, 1.0 / 1.21], rtol=1e-12
    )
    # Golden lifetime SDD-16 §11.
    assert list(detail.columns) == ["row_id", "stage", "ecl_12m", "ecl_lifetime", "ecl_reported"]
    np.testing.assert_allclose(detail["ecl_lifetime"].to_numpy(), [_ECL_GOLDEN], rtol=1e-12)
    # Stage 2 → reportado = lifetime; 12m corta en H_12m=1 → solo el primer período.
    np.testing.assert_allclose(detail["ecl_reported"].to_numpy(), [_ECL_GOLDEN], rtol=1e-12)
    np.testing.assert_allclose(detail["ecl_12m"].to_numpy(), [36.36363636363636], rtol=1e-12)
    assert detail["stage"].tolist() == [2]
    assert detail["row_id"].tolist() == ["op1"]


def test_from_config_devuelve_ecl_engine() -> None:
    assert isinstance(EclEngine.from_config(IfrsEclConfig()), EclEngine)


# ─────────────────────────── golden multiescenario (Σ w_k · ECL_k = 73) ───────────────────────────


def test_ecl_multiescenario_golden_ponderacion() -> None:
    # Un período por escenario con EIR=0 (DF=1) → ecl_marginal_k = pd·lgd·ead = 50/80/120.
    components = _components(
        row_id=["op1", "op1", "op1"],
        scenario=["base", "adverso", "severo"],
        period=[1, 1, 1],
        time_value=[1.0, 1.0, 1.0],
        pd_marginal=[0.05, 0.08, 0.12],
        lgd=[1.0, 1.0, 1.0],
        ead=[1000.0, 1000.0, 1000.0],
    )
    _, detail = EclEngine.from_config(IfrsEclConfig()).compute(
        components,
        eir=pd.Series([0.0], index=["op1"]),
        stages=pd.Series([2], index=["op1"]),
        weights={"base": 0.5, "adverso": 0.3, "severo": 0.2},
        horizon_12m=1,
    )
    # 0.5·50 + 0.3·80 + 0.2·120 = 73.0.
    np.testing.assert_allclose(detail["ecl_reported"].to_numpy(), [73.0], rtol=1e-12)
    np.testing.assert_allclose(detail["ecl_lifetime"].to_numpy(), [73.0], rtol=1e-12)


# ─────────────────────────── truncado por stage (12m vs lifetime) ───────────────────────────


def test_truncado_stage1_corta_en_h12m() -> None:
    components, params = _single_scenario_two_periods(stage=1)
    _, detail = EclEngine.from_config(IfrsEclConfig()).compute(components, **params)
    # Stage 1 → reportado = 12m = solo período 1 (H_12m=1).
    np.testing.assert_allclose(detail["ecl_reported"].to_numpy(), [36.36363636363636], rtol=1e-12)
    np.testing.assert_allclose(detail["ecl_12m"].to_numpy(), [36.36363636363636], rtol=1e-12)
    np.testing.assert_allclose(detail["ecl_lifetime"].to_numpy(), [_ECL_GOLDEN], rtol=1e-12)


def test_max_lifetime_trunca_soporte() -> None:
    # max_lifetime=1 descarta el período 2 tanto de la evidencia como del lifetime.
    components, params = _single_scenario_two_periods(stage=2)
    ts, detail = EclEngine.from_config(IfrsEclConfig()).compute(
        components, max_lifetime=1, **params
    )
    assert ts["period"].tolist() == [1]
    np.testing.assert_allclose(detail["ecl_lifetime"].to_numpy(), [36.36363636363636], rtol=1e-12)


def test_invariante_reportado_por_stage() -> None:
    # ecl_reported == ecl_12m ⟺ stage==1 (SDD-16 §6).
    components, params_s1 = _single_scenario_two_periods(stage=1)
    _, detail1 = EclEngine.from_config(IfrsEclConfig()).compute(components, **params_s1)
    reportado1 = detail1["ecl_reported"].to_numpy()
    np.testing.assert_allclose(reportado1, detail1["ecl_12m"].to_numpy(), rtol=1e-12)
    assert not np.allclose(reportado1, detail1["ecl_lifetime"].to_numpy())

    components2, params_s2 = _single_scenario_two_periods(stage=2)
    _, detail2 = EclEngine.from_config(IfrsEclConfig()).compute(components2, **params_s2)
    reportado2 = detail2["ecl_reported"].to_numpy()
    np.testing.assert_allclose(reportado2, detail2["ecl_lifetime"].to_numpy(), rtol=1e-12)
    assert not np.allclose(reportado2, detail2["ecl_12m"].to_numpy())


# ─────────────────────────── convención de descuento ───────────────────────────


def test_convencion_period_eir_usa_period() -> None:
    # time_value ≠ period: period_eir descuenta por el índice de período, no por el tiempo en años.
    components = _components(
        row_id=["op1", "op1"],
        scenario=["base", "base"],
        period=[1, 2],
        time_value=[0.5, 0.5],
        pd_marginal=[0.10, 0.08],
        lgd=[0.40, 0.40],
        ead=[1000.0, 900.0],
    )
    cfg = IfrsEclConfig(discount_convention="period_eir")
    ts, _ = EclEngine.from_config(cfg).compute(
        components,
        eir=pd.Series([0.10], index=["op1"]),
        stages=pd.Series([2], index=["op1"]),
        weights={"base": 1.0},
        horizon_12m=1,
    )
    np.testing.assert_allclose(
        ts["discount_factor"].to_numpy(), [1.0 / 1.1, 1.0 / 1.21], rtol=1e-12
    )


def test_convencion_anual_usa_time_value() -> None:
    components = _components(
        row_id=["op1", "op1"],
        scenario=["base", "base"],
        period=[1, 2],
        time_value=[0.5, 0.5],
        pd_marginal=[0.10, 0.08],
        lgd=[0.40, 0.40],
        ead=[1000.0, 900.0],
    )
    ts, _ = EclEngine.from_config(IfrsEclConfig()).compute(
        components,
        eir=pd.Series([0.10], index=["op1"]),
        stages=pd.Series([2], index=["op1"]),
        weights={"base": 1.0},
        horizon_12m=1,
    )
    # annual_eir_year_fraction: DF = 1.1^-0.5 en ambos períodos (τ = time_value = 0.5).
    np.testing.assert_allclose(ts["discount_factor"].to_numpy(), [1.1**-0.5, 1.1**-0.5], rtol=1e-12)


# ─────────────────────────── Stage 3 directo (EAD·LGD·DF(0)) ───────────────────────────


def test_stage3_direct_ead_lgd() -> None:
    components = _components(
        row_id=["op1", "op1"],
        scenario=["base", "base"],
        period=[1, 2],
        time_value=[1.0, 2.0],
        pd_marginal=[0.10, 0.08],
        lgd=[0.50, 0.50],
        ead=[1000.0, 900.0],
    )
    cfg = IfrsEclConfig(stage3_direct=True)
    _, detail = EclEngine.from_config(cfg).compute(
        components,
        eir=pd.Series([0.10], index=["op1"]),
        stages=pd.Series([3], index=["op1"]),
        weights={"base": 1.0},
        horizon_12m=1,
    )
    # Stage 3 directo: EAD_0·LGD_0·DF(0) = 1000·0.50·1 = 500 (período más temprano, DF(0)=1).
    np.testing.assert_allclose(detail["ecl_lifetime"].to_numpy(), [500.0], rtol=1e-12)
    np.testing.assert_allclose(detail["ecl_reported"].to_numpy(), [500.0], rtol=1e-12)


# ─────────────── índice NO-RangeIndex (asignación posicional) ───────────────


def test_indice_no_rangeindex_no_produce_nan() -> None:
    # Lección B16.4/5/6: la asignación posicional no debe alinear por etiqueta (NaN silencioso).
    components, params = _single_scenario_two_periods(stage=2)
    components.index = pd.Index([17, 42], name="custom")
    ts, detail = EclEngine.from_config(IfrsEclConfig()).compute(components, **params)
    assert not ts["ecl_marginal"].isna().any()
    np.testing.assert_allclose(detail["ecl_lifetime"].to_numpy(), [_ECL_GOLDEN], rtol=1e-12)


def test_no_muta_los_insumos() -> None:
    components, params = _single_scenario_two_periods(stage=2)
    snapshot = components.copy(deep=True)
    EclEngine.from_config(IfrsEclConfig()).compute(components, **params)
    pd.testing.assert_frame_equal(components, snapshot)


def test_normaliza_signo_de_cero() -> None:
    components = _components(
        row_id=["op1"],
        scenario=["base"],
        period=[1],
        time_value=[1.0],
        pd_marginal=[0.0],
        lgd=[0.40],
        ead=[1000.0],
    )
    ts, detail = EclEngine.from_config(IfrsEclConfig()).compute(
        components,
        eir=pd.Series([0.10], index=["op1"]),
        stages=pd.Series([2], index=["op1"]),
        weights={"base": 1.0},
        horizon_12m=1,
    )
    assert not bool(np.signbit(ts["ecl_marginal"].to_numpy()[0]))
    assert not bool(np.signbit(detail["ecl_reported"].to_numpy()[0]))


# ─────────────────────────── errores: horizontes ───────────────────────────


def test_horizon_12m_invalido() -> None:
    components, params = _single_scenario_two_periods()
    params["horizon_12m"] = 0
    with pytest.raises(IfrsEclError, match="horizon_12m debe ser"):
        EclEngine.from_config(IfrsEclConfig()).compute(components, **params)


def test_max_lifetime_invalido() -> None:
    components, params = _single_scenario_two_periods()
    with pytest.raises(IfrsEclError, match="max_lifetime debe ser"):
        EclEngine.from_config(IfrsEclConfig()).compute(components, max_lifetime=0, **params)


def test_max_lifetime_sin_periodos() -> None:
    components = _components(
        row_id=["op1"],
        scenario=["base"],
        period=[3],
        time_value=[3.0],
        pd_marginal=[0.10],
        lgd=[0.40],
        ead=[1000.0],
    )
    with pytest.raises(IfrsEclError, match="No quedan períodos"):
        EclEngine.from_config(IfrsEclConfig()).compute(
            components,
            eir=pd.Series([0.10], index=["op1"]),
            stages=pd.Series([2], index=["op1"]),
            weights={"base": 1.0},
            horizon_12m=1,
            max_lifetime=2,
        )


# ─────────────────────────── errores: malla de componentes ───────────────────────────


def test_columna_faltante() -> None:
    components = _components(
        row_id=["op1"],
        scenario=["base"],
        period=[1],
        time_value=[1.0],
        pd_marginal=[0.10],
        lgd=[0.40],
        ead=[1000.0],
    ).drop(columns=["lgd"])
    with pytest.raises(IfrsEclError, match="columnas faltantes"):
        EclEngine.from_config(IfrsEclConfig()).compute(
            components,
            eir=pd.Series([0.10], index=["op1"]),
            stages=pd.Series([2], index=["op1"]),
            weights={"base": 1.0},
            horizon_12m=1,
        )


def test_components_vacio() -> None:
    components = _components(
        row_id=[], scenario=[], period=[], time_value=[], pd_marginal=[], lgd=[], ead=[]
    )
    with pytest.raises(IfrsEclError, match="no puede estar vacío"):
        EclEngine.from_config(IfrsEclConfig()).compute(
            components,
            eir=pd.Series([0.10], index=["op1"]),
            stages=pd.Series([2], index=["op1"]),
            weights={"base": 1.0},
            horizon_12m=1,
        )


@pytest.mark.parametrize(
    ("column", "value", "match"),
    [
        ("period", 0, "period debe ser un entero"),
        ("period", 1.5, "period debe ser un entero"),
        ("time_value", -1.0, "time_value debe ser"),
        ("pd_marginal", 1.5, r"pd_marginal debe estar en \[0, 1\]"),
        ("lgd", -0.1, r"lgd debe estar en \[0, 1\]"),
        ("ead", -1.0, "ead debe ser mayor"),
        ("ead", "x", "debe ser numérico"),
        ("ead", np.inf, "valores finitos"),
    ],
)
def test_componente_fuera_de_contrato(column: str, value: Any, match: str) -> None:
    data: dict[str, list[Any]] = {
        "row_id": ["op1"],
        "scenario": ["base"],
        "period": [1],
        "time_value": [1.0],
        "pd_marginal": [0.10],
        "lgd": [0.40],
        "ead": [1000.0],
    }
    data[column] = [value]
    components = pd.DataFrame(data)
    with pytest.raises(IfrsEclError, match=match):
        EclEngine.from_config(IfrsEclConfig()).compute(
            components,
            eir=pd.Series([0.10], index=["op1"]),
            stages=pd.Series([2], index=["op1"]),
            weights={"base": 1.0},
            horizon_12m=1,
        )


# ─────────────────────────── errores: pesos de escenario ───────────────────────────


def _compute_con_pesos(weights: Any) -> None:
    """Corre ``compute`` de un escenario variando solo los pesos, para probar el guard."""
    components, params = _single_scenario_two_periods()
    params["weights"] = weights
    EclEngine.from_config(IfrsEclConfig()).compute(components, **params)


def test_pesos_vacios() -> None:
    with pytest.raises(IfrsEclError, match="no pueden estar vacíos"):
        _compute_con_pesos({})


def test_pesos_no_finitos() -> None:
    with pytest.raises(IfrsEclError, match="debe ser finito"):
        _compute_con_pesos({"base": float("nan")})


@pytest.mark.parametrize("peso", [0.0, -0.1])
def test_pesos_no_positivos(peso: float) -> None:
    """Peso 0 y negativo caen en el mismo guard; si algún día se relaja el 0 (frontera forward,
    decisión de política pendiente), el negativo debe seguir fallando."""
    with pytest.raises(IfrsEclError, match="estrictamente positivo"):
        _compute_con_pesos({"base": peso})


def test_pesos_no_cubren_escenarios() -> None:
    with pytest.raises(IfrsEclError, match="cubrir exactamente"):
        _compute_con_pesos({"otro": 1.0})


def test_pesos_no_suman_uno() -> None:
    components = _components(
        row_id=["op1", "op1"],
        scenario=["base", "adverso"],
        period=[1, 1],
        time_value=[1.0, 1.0],
        pd_marginal=[0.10, 0.10],
        lgd=[0.40, 0.40],
        ead=[1000.0, 1000.0],
    )
    with pytest.raises(IfrsEclError, match="deben sumar 1"):
        EclEngine.from_config(IfrsEclConfig()).compute(
            components,
            eir=pd.Series([0.10], index=["op1"]),
            stages=pd.Series([2], index=["op1"]),
            weights={"base": 0.5, "adverso": 0.3},
            horizon_12m=1,
        )


# ─────────────────────────── errores: EIR y stages ───────────────────────────


def test_eir_faltante_para_operacion() -> None:
    components, params = _single_scenario_two_periods()
    params["eir"] = pd.Series([0.10], index=["otra"])
    with pytest.raises(IfrsEclError, match="Faltan EIR"):
        EclEngine.from_config(IfrsEclConfig()).compute(components, **params)


def test_eir_indice_duplicado() -> None:
    components, params = _single_scenario_two_periods()
    params["eir"] = pd.Series([0.10, 0.20], index=["op1", "op1"])
    with pytest.raises(IfrsEclError, match="único por row_id"):
        EclEngine.from_config(IfrsEclConfig()).compute(components, **params)


def test_eir_menor_o_igual_menos_uno() -> None:
    components, params = _single_scenario_two_periods()
    params["eir"] = pd.Series([-1.5], index=["op1"])
    with pytest.raises(IfrsEclError, match="mayor que -1"):
        EclEngine.from_config(IfrsEclConfig()).compute(components, **params)


def test_stage_faltante_para_operacion() -> None:
    components, params = _single_scenario_two_periods()
    params["stages"] = pd.Series([2], index=["otra"])
    with pytest.raises(IfrsEclError, match="Faltan stages"):
        EclEngine.from_config(IfrsEclConfig()).compute(components, **params)


def test_stage_indice_duplicado() -> None:
    components = _components(
        row_id=["op1", "op2"],
        scenario=["base", "base"],
        period=[1, 1],
        time_value=[1.0, 1.0],
        pd_marginal=[0.10, 0.10],
        lgd=[0.40, 0.40],
        ead=[1000.0, 1000.0],
    )
    with pytest.raises(IfrsEclError, match="único por row_id"):
        EclEngine.from_config(IfrsEclConfig()).compute(
            components,
            eir=pd.Series([0.10, 0.10], index=["op1", "op2"]),
            stages=pd.Series([2, 3], index=["op1", "op1"]),
            weights={"base": 1.0},
            horizon_12m=1,
        )


def test_stage_valor_invalido() -> None:
    components, params = _single_scenario_two_periods()
    params["stages"] = pd.Series([4], index=["op1"])
    with pytest.raises(IfrsEclError, match="debe ser 1, 2 o 3"):
        EclEngine.from_config(IfrsEclConfig()).compute(components, **params)


# ─────────────────────────── errores: factor de descuento ───────────────────────────


def test_discount_factor_no_finito() -> None:
    # EIR ∈ (-1, 0) con horizonte grande → (1+EIR)^-τ desborda a +inf → error controlado.
    components = _components(
        row_id=["op1"],
        scenario=["base"],
        period=[1],
        time_value=[400.0],
        pd_marginal=[0.10],
        lgd=[0.40],
        ead=[1000.0],
    )
    with pytest.raises(IfrsEclError, match="no es finito"):
        EclEngine.from_config(IfrsEclConfig()).compute(
            components,
            eir=pd.Series([-0.9], index=["op1"]),
            stages=pd.Series([2], index=["op1"]),
            weights={"base": 1.0},
            horizon_12m=1,
        )


def test_discount_factor_mayor_que_uno() -> None:
    # EIR negativa con τ>0 produce DF>1 finito → fuera de (0, 1], error sin clip silencioso.
    components = _components(
        row_id=["op1"],
        scenario=["base"],
        period=[1],
        time_value=[1.0],
        pd_marginal=[0.10],
        lgd=[0.40],
        ead=[1000.0],
    )
    with pytest.raises(IfrsEclError, match=r"\(0, 1\]"):
        EclEngine.from_config(IfrsEclConfig()).compute(
            components,
            eir=pd.Series([-0.1], index=["op1"]),
            stages=pd.Series([2], index=["op1"]),
            weights={"base": 1.0},
            horizon_12m=1,
        )


# ─────────────────────────── guards de dependencia perezosa ───────────────────────────


def _blocker(*modules: str) -> Any:
    """Construye un reemplazo de ``import_module`` que bloquea los módulos indicados."""
    real_import = importlib.import_module

    def block(name: str) -> Any:
        if name in modules:
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return real_import(name)

    return block


def test_compute_numpy_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    components, params = _single_scenario_two_periods()
    monkeypatch.setattr(ecl_module.importlib, "import_module", _blocker("numpy"))
    with pytest.raises(MissingDependencyError, match="numpy"):
        EclEngine.from_config(IfrsEclConfig()).compute(components, **params)


def test_compute_pandas_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    components, params = _single_scenario_two_periods()
    monkeypatch.setattr(ecl_module.importlib, "import_module", _blocker("pandas"))
    with pytest.raises(MissingDependencyError, match="pandas"):
        EclEngine.from_config(IfrsEclConfig()).compute(components, **params)
