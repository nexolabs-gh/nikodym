"""Tests de la frontera de contrato forward→IFRS 9 (caracterización P0, ROADMAP §P0.2).

Fija con tests los límites explícitos del contrato entre la capa forward (SDD-20) y el motor
IFRS 9 (SDD-16) que la revisión P0 caracterizó sin cambiar el motor:

- **Pesos cero:** forward permite ``w_k = 0`` (contrato ``w_k ≥ 0, Σ=1``) y su ponderador los
  acepta con contribución nula, pero IFRS 9 exige pesos estrictamente positivos en tres guards
  (config ``source='config'``, ``EclEngine`` y los DTO de ``results``). La vía soportada es
  excluir aguas arriba el escenario peso-0; la resolución de fondo queda como decisión de
  política posterior (SDD-16 §8, SDD-20 §5).
- **Z implícito:** forward no publica un factor sistémico Z en su term-structure; el canario
  hace ruido si alguien lo añade sin pasar por un SDD (``apply_vasicek`` exige Z explícito).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from nikodym.forward.config import (
    ForwardConfig,
    ForwardInputConfig,
    MacroModelConfig,
    MacroSourceConfig,
    SatelliteConfig,
    ScenarioConfig,
    ScenarioDefinitionConfig,
    TtcReversionConfig,
)
from nikodym.forward.scenarios import ScenarioWeighting
from nikodym.forward.step import _FORWARD_TERM_STRUCTURE_COLUMNS
from nikodym.provisioning.ifrs9 import EclEngine
from nikodym.provisioning.ifrs9.config import IfrsEclConfig
from nikodym.provisioning.ifrs9.exceptions import IfrsEclError
from nikodym.provisioning.ifrs9.results import IfrsEclRecord, IfrsProvisionCard


def _scenario(name: str, weight: float, shock: float = 0.0) -> ScenarioDefinitionConfig:
    """Escenario con shock no vacío fuera de base (FALTA-DATO-FWD-1 exige shocks o path)."""
    shocks = {} if name == "base" else {"x": shock}
    return ScenarioDefinitionConfig(name=name, weight=weight, shocks=shocks)


def _cfg_forward_peso_cero() -> ForwardConfig:
    """Config forward válida con ``severe`` de peso 0 (contrato SDD-20: ``w_k ≥ 0``)."""
    return ForwardConfig(
        input=ForwardInputConfig(
            macro_source=MacroSourceConfig(type="dataframe", variable_cols=("x",)),
            pd_basis_assumption="pit",
        ),
        satellite=SatelliteConfig(factor_cols=("x",), min_history_periods=3),
        macro=MacroModelConfig(horizon_periods=5, ljung_box_lags=(1,)),
        scenarios=ScenarioConfig(
            scenarios=(
                _scenario("base", 0.70),
                _scenario("adverse", 0.30, 1.0),
                _scenario("severe", 0.00, 2.0),
            )
        ),
        ttc_reversion=TtcReversionConfig(reasonable_supportable_periods=2, reversion_periods=2),
    )


def _components_dos_escenarios(scenarios: list[str]) -> pd.DataFrame:
    """Malla ECL tidy de ``op1`` con un período por escenario (ECL_k = pd·lgd·ead, DF=1)."""
    n = len(scenarios)
    return pd.DataFrame(
        {
            "row_id": ["op1"] * n,
            "scenario": scenarios,
            "period": [1] * n,
            "time_value": [1.0] * n,
            "pd_marginal": [0.05, 0.08, 0.12][:n],
            "lgd": [1.0] * n,
            "ead": [1000.0] * n,
        }
    )


# ─────────────────────────── pesos cero: lado forward (w=0 es válido) ───────────────────────────


def test_forward_acepta_peso_cero_y_lo_publica() -> None:
    """``ScenarioWeighting`` acepta ``severe=0.0`` (contrato ``w_k ≥ 0, Σ=1`` de SDD-20)."""
    weighting = ScenarioWeighting.from_config(_cfg_forward_peso_cero())
    assert weighting.scenario_weights_ == {"base": 0.70, "adverse": 0.30, "severe": 0.00}


def test_forward_weight_outputs_peso_cero_presente_o_ausente() -> None:
    """El escenario peso-0 es de presencia opcional y pondera igual (contribución nula).

    Golden: ``0.7·100 + 0.3·200 + 0·900 = 130.0`` con ``severe`` presente y ausente.
    """
    weighting = ScenarioWeighting.from_config(_cfg_forward_peso_cero())
    con_severe = pd.DataFrame(
        {"scenario": ["base", "adverse", "severe"], "ecl": [100.0, 200.0, 900.0]}
    )
    sin_severe = pd.DataFrame({"scenario": ["base", "adverse"], "ecl": [100.0, 200.0]})
    for frame in (con_severe, sin_severe):
        result = weighting.weight_outputs(frame, value_cols=("ecl",), group_cols=())
        np.testing.assert_allclose(result["ecl"].to_numpy(), [130.0], rtol=1e-12)


# ─────────────────────── pesos cero: frontera (IFRS 9 exige w > 0) ───────────────────────


def test_pesos_forward_con_cero_no_consumibles_por_ecl_engine() -> None:
    """Los pesos que publica forward con un 0 revientan en ``EclEngine`` (guard tardío fijado)."""
    weights = ScenarioWeighting.from_config(_cfg_forward_peso_cero()).scenario_weights_
    components = _components_dos_escenarios(["base", "adverse", "severe"])
    with pytest.raises(IfrsEclError, match="estrictamente positivo"):
        EclEngine.from_config(IfrsEclConfig()).compute(
            components,
            eir=pd.Series([0.0], index=["op1"]),
            stages=pd.Series([2], index=["op1"]),
            weights=weights,
            horizon_12m=1,
        )


def test_pesos_forward_filtrados_calculan_golden() -> None:
    """La vía soportada: excluir el escenario peso-0 de pesos y malla antes del ECL.

    Golden lifetime Stage 2: ``0.7·(0.05·1000) + 0.3·(0.08·1000) = 59.0`` — idéntico al teórico
    con peso 0 como contribución nula.
    """
    weights = ScenarioWeighting.from_config(_cfg_forward_peso_cero()).scenario_weights_
    positivos = {name: value for name, value in weights.items() if value > 0.0}
    components = _components_dos_escenarios(["base", "adverse"])
    _, detail = EclEngine.from_config(IfrsEclConfig()).compute(
        components,
        eir=pd.Series([0.0], index=["op1"]),
        stages=pd.Series([2], index=["op1"]),
        weights=positivos,
        horizon_12m=1,
    )
    np.testing.assert_allclose(detail["ecl_reported"].to_numpy(), [59.0], rtol=1e-12)


@pytest.mark.parametrize("dto", ["record", "card"])
def test_dtos_results_rechazan_peso_cero(dto: str) -> None:
    """El tercer guard de positividad: los DTO de ``results`` tampoco aceptan ``w=0``.

    Relajar solo ``EclEngine`` movería el fallo aún más tarde (ValidationError al ensamblar el
    resultado): cualquier resolución futura debe tocar los tres guards a la vez.
    """
    pesos = {"base": 0.7, "adverse": 0.3, "severe": 0.0}
    with pytest.raises(ValidationError, match="estrictamente positivos"):
        if dto == "record":
            IfrsEclRecord(
                row_id="op1",
                stage=2,
                ead=1000.0,
                lgd=0.5,
                eir=0.1,
                ecl_12m=10.0,
                ecl_lifetime=20.0,
                ecl_reported=20.0,
                scenario_weights=pesos,
                pd_basis="pit",
            )
        else:
            IfrsProvisionCard(
                as_of_date="2026-01-31",
                term_structure_source="forward",
                pit_mode="consume_pit",
                n_rows=1,
                n_stage1=0,
                n_stage2=1,
                n_stage3=0,
                total_ead=1000.0,
                total_ecl_reported=20.0,
                scenarios=("base", "adverse", "severe"),
                scenario_weights=pesos,
                dependency_versions={},
            )


# ─────────────────────────── Z implícito: canario del contrato forward ───────────────────────────


def test_contrato_forward_no_publica_factor_sistemico_z() -> None:
    """Canario: la term-structure de forward NO trae factor sistémico Z (SDD-20).

    ``apply_vasicek`` exige un Z explícito vía ``pd.systemic_factor_col``; la exención por
    ``scenarios.source='forward'`` se eliminó porque prometía un Z implícito inexistente. Si
    alguien materializa Z en el contrato forward sin pasar por un SDD, este test hace ruido.
    """
    columnas = {column.lower() for column in _FORWARD_TERM_STRUCTURE_COLUMNS}
    assert "z" not in columnas
    assert not any("systemic" in column for column in columnas)
    assert not any("factor_sistemico" in column for column in columnas)
