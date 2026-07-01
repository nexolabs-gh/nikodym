"""Tests canónicos de ``stress.engine`` para B21.3."""

from __future__ import annotations

import functools
import json
import math
import os
import subprocess
import sys
import warnings
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, ClassVar

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.forward.step as forward_step_module
import nikodym.stress as stress_pkg
import nikodym.stress.engine as engine_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.forward.results import FORWARD_ECL_CONTRACT_VERSION, ForwardEclInput
from nikodym.stress.config import (
    ReverseStressConfig,
    SensitivitySweepConfig,
    StressConfig,
    StressInputConfig,
    StressOutputConfig,
    StressScenarioConfig,
    StressShockConfig,
    StressTargetConfig,
    StressValidationConfig,
)
from nikodym.stress.engine import EclEngineLike, ProvisionEngineLike, StressTestEngine
from nikodym.stress.exceptions import (
    ReverseStressError,
    StressDependencyError,
    StressEngineError,
    StressFaltaDatoError,
    StressInputError,
    StressOutputError,
    StressScenarioError,
)

_FORWARD_TERM_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "partition",
    "source_model",
    "period",
    "time_value",
    "scenario",
    "scenario_weight",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "pd_marginal_base",
    "pd_cumulative_base",
    "lgd",
    "lgd_base",
    "pd_basis",
    "basis_state",
    "ttc_reversion_weight",
    "satellite_adjustment",
    "macro_model_id",
    "satellite_model_id",
    "method",
    "pd_source",
    "warning_codes",
)
_SCENARIO_WEIGHT_COLUMNS: tuple[str, ...] = (
    "scenario",
    "weight",
    "is_default",
    "source",
    "description",
)
_MACRO_PROJECTION_COLUMNS: tuple[str, ...] = (
    "scenario",
    "scenario_weight",
    "period",
    "time_value",
    "macro_variable",
    "projected_value",
    "model_value",
    "shock_value",
    "method",
    "model_id",
    "is_reasonable_supportable",
    "warning_codes",
)
_STRESS_SCENARIO_COLUMNS: tuple[str, ...] = (
    "stress_scenario",
    "scenario_kind",
    "base_forward_scenario",
    "severity",
    "macro_variable",
    "operation",
    "shock_value",
    "applied_shock",
    "period",
    "source",
    "warning_codes",
)


class SatelliteStub:
    """Satellite mínimo con coeficientes fijos auditables."""

    coefficients_: ClassVar[dict[str, dict[str, dict[str, object]]]] = {
        "pd": {"retail": {"alpha": 0.0, "factors": {"x": 0.5}}},
        "lgd": {"retail": {"alpha": 0.0, "factors": {"x": 0.0}}},
    }


class AlternateSatelliteStub:
    """Satellite con coeficiente PD distinto para probar lineage no tabular."""

    coefficients_: ClassVar[dict[str, dict[str, dict[str, object]]]] = {
        "pd": {"retail": {"alpha": 0.0, "factors": {"x": 0.25}}},
        "lgd": {"retail": {"alpha": 0.0, "factors": {"x": 0.0}}},
    }


class PortfolioSatelliteStub:
    """Satellite con coeficientes aplicables a cualquier segmento."""

    coefficients_: ClassVar[dict[str, dict[str, dict[str, object]]]] = {
        "pd": {"__all__": {"alpha": 0.0, "factors": {"x": 0.0}}},
        "lgd": {"__all__": {"alpha": 0.0, "factors": {"x": 0.0}}},
    }


class ScenarioWeightingStub:
    """Validador forward mínimo usado por el engine."""

    def __init__(self) -> None:
        self.calls = 0

    def validate_macro_projection(self, frame: pd.DataFrame) -> None:
        """Comprueba que el engine entrega copia defensiva al validador."""
        self.calls += 1
        assert "scenario" in frame.columns
        frame.loc[:, "projected_value"] = 999.0


class NoopScenarioWeightingStub:
    """Validador forward mínimo que no aplica reglas extra."""

    def validate_macro_projection(self, frame: pd.DataFrame) -> None:
        """Acepta la proyección para probar validaciones locales de stress."""
        del frame


class StatefulScenarioWeightingStub(ScenarioWeightingStub):
    """Validador con estado público material para lineage."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label


class EclStub:
    """Engine ECL determinista: ECL = PD marginal * LGD * 1000."""

    def __init__(self) -> None:
        self.calls: list[pd.DataFrame] = []

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Calcula ECL por período desde el contrato forward."""
        term = ecl_input.term_structure_frame
        assert term is not None
        self.calls.append(term.copy(deep=True))
        return pd.DataFrame(
            {
                "period": term["period"].tolist(),
                "ecl": (term["pd_marginal"].astype(float) * term["lgd"].astype(float) * 1000.0),
            }
        )


class EquivalentEclStub(EclStub):
    """Engine ECL con salida equivalente, pero identidad de motor distinta."""


@dataclass(frozen=True)
class NestedLineageConfig:
    """Configuración pública anidada para probar hashes de lineage."""

    limit: float
    labels: tuple[str, ...]


class StatefulEclStub(EclStub):
    """Engine ECL con estado público anidado que debe entrar al lineage."""

    def __init__(self, *, limit: float, probability_tol: float) -> None:
        super().__init__()
        self.public_config = {
            "nested": [NestedLineageConfig(limit=limit, labels=("retail", "stress"))],
            "validation": StressValidationConfig(probability_tol=probability_tol),
        }


class HistoryConfiguredEclStub(EclStub):
    """Engine cuyo atributo ``history`` es configuración material, no runtime."""

    def __init__(self, multiplier: float) -> None:
        super().__init__()
        self.history = {"multiplier": multiplier}

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Escala ECL usando configuración pública llamada ``history``."""
        term = ecl_input.term_structure_frame
        assert term is not None
        self.calls.append(term.copy(deep=True))
        return pd.DataFrame(
            {
                "period": term["period"].tolist(),
                "ecl": (
                    term["pd_marginal"].astype(float)
                    * term["lgd"].astype(float)
                    * 1000.0
                    * float(self.history["multiplier"])
                ),
            }
        )


class SlottedHistoryConfiguredEclStub:
    """Engine ECL slotted cuyo ``history`` público debe entrar al lineage."""

    __slots__ = ("calls", "history")

    calls: list[pd.DataFrame]
    history: dict[str, float]

    def __init__(self, multiplier: float) -> None:
        self.calls = []
        self.history = {"multiplier": multiplier}

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Escala ECL desde configuración pública definida en ``__slots__``."""
        term = ecl_input.term_structure_frame
        assert term is not None
        self.calls.append(term.copy(deep=True))
        return pd.DataFrame(
            {
                "period": term["period"].tolist(),
                "ecl": (
                    term["pd_marginal"].astype(float)
                    * term["lgd"].astype(float)
                    * 1000.0
                    * float(self.history["multiplier"])
                ),
            }
        )


def _lineage_ecl_multiplier_one(term: pd.DataFrame) -> float:
    """Estrategia callable pública estable para lineage."""
    del term
    return 1.0


def _lineage_ecl_multiplier_two(term: pd.DataFrame) -> float:
    """Estrategia callable pública alternativa para lineage."""
    del term
    return 2.0


def _lineage_ecl_multiplier_partial(term: pd.DataFrame, *, multiplier: float) -> float:
    """Estrategia estable parametrizable por ``functools.partial``."""
    del term
    return multiplier


class BoundLineageMultiplier:
    """Estrategia con método bound y estado material en ``self``."""

    def __init__(self, multiplier: float) -> None:
        self.multiplier = multiplier

    def scale(self, term: pd.DataFrame) -> float:
        """Retorna multiplicador configurado en el dueño del método."""
        del term
        return self.multiplier


class ClassBoundLineageMultiplier:
    """Estrategia classmethod para cubrir dueño tipo clase."""

    @classmethod
    def scale(cls, term: pd.DataFrame) -> float:
        """Retorna multiplicador unitario."""
        del term
        return 1.0


class LineageCallableMultiplier:
    """Callable público con configuración propia para lineage."""

    def __init__(self, multiplier: float) -> None:
        self.multiplier = multiplier

    def __call__(self, term: pd.DataFrame) -> float:
        """Retorna multiplicador configurado."""
        del term
        return self.multiplier


class CallableIdentityFallback:
    """Callable que fuerza fallback a identidad de clase."""

    def __init__(self) -> None:
        self.__module__ = None
        self.__qualname__ = None

    def __call__(self, term: pd.DataFrame) -> float:
        """Retorna multiplicador unitario."""
        del term
        return 1.0


class CallableConfiguredEclStub:
    """Engine ECL con estrategia callable pública material."""

    __slots__ = ("calls", "strategy")

    calls: list[pd.DataFrame]
    strategy: Any

    def __init__(self, strategy: Any) -> None:
        self.calls = []
        self.strategy = strategy

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Escala ECL con una estrategia callable pública."""
        term = ecl_input.term_structure_frame
        assert term is not None
        self.calls.append(term.copy(deep=True))
        return pd.DataFrame(
            {
                "period": term["period"].tolist(),
                "ecl": (
                    term["pd_marginal"].astype(float)
                    * term["lgd"].astype(float)
                    * 1000.0
                    * float(self.strategy(term))
                ),
            }
        )


class NestedCallableConfigEclStub:
    """Engine ECL con callable material anidado en configuración pública."""

    def __init__(self, strategy: Any) -> None:
        self.calls: list[pd.DataFrame] = []
        self.public_config = {"strategy": strategy}

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Escala ECL con estrategia anidada en ``public_config``."""
        term = ecl_input.term_structure_frame
        assert term is not None
        self.calls.append(term.copy(deep=True))
        return pd.DataFrame(
            {
                "period": term["period"].tolist(),
                "ecl": (
                    term["pd_marginal"].astype(float)
                    * term["lgd"].astype(float)
                    * 1000.0
                    * float(self.public_config["strategy"](term))
                ),
            }
        )


class CapturingEclStub(EclStub):
    """ECL stub que captura también el frame de pesos recibido."""

    def __init__(self) -> None:
        super().__init__()
        self.weight_calls: list[pd.DataFrame] = []

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Guarda pesos por escenario antes de delegar el cálculo ECL."""
        self.weight_calls.append(ecl_input.scenario_weight_frame.copy(deep=True))
        return super().calculate(ecl_input)


class ProvisionStub:
    """Engine de provisión determinista sobre ECL."""

    def calculate(self, ecl_frame: pd.DataFrame) -> pd.DataFrame:
        """Publica provisión como 110% del ECL."""
        return pd.DataFrame(
            {
                "period": ecl_frame["period"].tolist(),
                "provision": ecl_frame["ecl"].astype(float) * 1.1,
            }
        )


class DuplicateMetricProvisionStub:
    """Engine de provisión que publica columnas duplicadas de métrica."""

    def calculate(self, ecl_frame: pd.DataFrame) -> pd.DataFrame:
        """Retorna columnas ``provision`` duplicadas."""
        rows = [[period, 1.0, 2.0] for period in ecl_frame["period"].tolist()]
        return pd.DataFrame(rows, columns=["period", "provision", "provision"])


class BadEclStub:
    """Engine ECL inválido para probar rechazo de no finitos."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna infinito deliberado."""
        del ecl_input
        return pd.DataFrame({"period": [1], "ecl": [math.inf]})


class NoPeriodEclStub:
    """Engine ECL que publica métrica agregada sin período."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Calcula ECL total sin columna ``period``."""
        term = ecl_input.term_structure_frame
        assert term is not None
        value = float((term["pd_marginal"].astype(float) * term["lgd"].astype(float)).sum())
        return pd.DataFrame({"ecl": [value * 1000.0]})


class RatioEclStub:
    """Engine ECL que publica ratio ya agregado por período."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna un ratio único por período y escenario recibido."""
        term = ecl_input.term_structure_frame
        assert term is not None
        scenario = str(term["scenario"].iloc[0])
        ratio = 0.60 if scenario == "severe" else 0.70
        periods = sorted({int(value) for value in term["period"].tolist()})
        return pd.DataFrame({"period": periods, "ratio": [ratio] * len(periods)})


class MultiRowRatioEclStub:
    """Engine ECL inválido: publica varios ratios para el mismo período."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna dos ratios no agregables para el mismo período."""
        del ecl_input
        return pd.DataFrame({"period": [1, 1], "ratio": [0.60, 0.70]})


class EmptyEclStub:
    """Engine ECL inválido que publica un frame económico vacío."""

    def __init__(self, *, with_period: bool) -> None:
        self.with_period = with_period

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna salidas vacías con forma agregada o por período."""
        del ecl_input
        if self.with_period:
            return pd.DataFrame(
                {
                    "period": pd.Series(dtype="int64"),
                    "ecl": pd.Series(dtype="float64"),
                }
            )
        return pd.DataFrame({"ecl": pd.Series(dtype="float64")})


class MissingMetricEclStub:
    """Engine ECL que no publica columna reconocida."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna una columna ajena al contrato."""
        del ecl_input
        return pd.DataFrame({"period": [1], "otra": [1.0]})


class UnknownDimensionEclStub:
    """Engine ECL que publica una dimensión no soportada por el contrato."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna una columna ``portfolio_id`` que no debe agregarse en silencio."""
        term = ecl_input.term_structure_frame
        assert term is not None
        return pd.DataFrame(
            {
                "period": term["period"].tolist(),
                "portfolio_id": ["A"] * len(term.index),
                "ecl": [1.0] * len(term.index),
            }
        )


class NegativeEclStub:
    """Engine ECL que publica métrica negativa."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna ECL negativo."""
        del ecl_input
        return pd.DataFrame({"period": [1], "ecl": [-1.0]})


class OffsettingNegativeEclStub:
    """Engine ECL inválido: un negativo por fila se cancela en la suma."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna ECL con total positivo y una fila negativa."""
        del ecl_input
        return pd.DataFrame({"period": [1, 1], "ecl": [-1.0, 2.0]})


class WarningEclStub:
    """Engine ECL que emite warning bajo ``filterwarnings=error``."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Emite warning deliberado."""
        del ecl_input
        import warnings

        warnings.warn("engine warning", UserWarning, stacklevel=2)
        return pd.DataFrame({"period": [1], "ecl": [1.0]})


class NonFrameEclStub:
    """Engine ECL que retorna un objeto inválido."""

    def calculate(self, ecl_input: ForwardEclInput) -> object:
        """Retorna objeto no tabular."""
        del ecl_input
        return object()


class BaselineMissingMetricEclStub:
    """Engine que omite la métrica solo en baseline."""

    def __init__(self) -> None:
        self.calls = 0

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Alterna forma de salida para cubrir validación baseline/stress."""
        del ecl_input
        self.calls += 1
        if self.calls == 1:
            return pd.DataFrame({"period": [1], "otra": [1.0]})
        return pd.DataFrame({"period": [1], "ecl": [1.0]})


class AmbiguousMetricEclStub:
    """Engine que publica dos aliases reconocidos para la misma métrica."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna ECL con aliases redundantes que deben rechazarse."""
        term = ecl_input.term_structure_frame
        assert term is not None
        periods = term["period"].tolist()
        return pd.DataFrame(
            {
                "period": periods,
                "ecl": [1.0] * len(periods),
                "expected_loss": [1.0] * len(periods),
            }
        )


class DuplicateMetricEclStub:
    """Engine que publica dos columnas con el mismo nombre de métrica."""

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna columnas ``ecl`` duplicadas antes de resolver aliases."""
        term = ecl_input.term_structure_frame
        assert term is not None
        rows = [[period, 1.0, 2.0] for period in term["period"].tolist()]
        return pd.DataFrame(rows, columns=["period", "ecl", "ecl"])


class AliasSwitchingEclStub:
    """Engine que cambia alias reconocido entre baseline y stress."""

    def __init__(self) -> None:
        self.calls = 0

    def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
        """Retorna ``ecl`` en baseline y ``expected_loss`` en stress."""
        term = ecl_input.term_structure_frame
        assert term is not None
        self.calls += 1
        column = "ecl" if self.calls == 1 else "expected_loss"
        return pd.DataFrame({"period": term["period"].tolist(), column: [1.0] * len(term.index)})


class SimpleForwardInput:
    """Payload ECL incompleto para probar rechazo de contrato."""

    def __init__(self) -> None:
        self.term_structure_frame: pd.DataFrame | None = None


class CompatibleForwardInput:
    """Payload ECL estructuralmente compatible sin depender de Pydantic."""

    def __init__(
        self,
        *,
        term_structure_frame: pd.DataFrame | None,
        scenario_weight_frame: pd.DataFrame,
        pit_consistency: dict[str, object] | None = None,
        contract_version: str = FORWARD_ECL_CONTRACT_VERSION,
        chain: str = engine_module._FORWARD_ECL_CHAIN,
    ) -> None:
        self.term_structure_frame = term_structure_frame
        self.scenario_weight_frame = scenario_weight_frame
        self.pit_consistency = pit_consistency or {"basis": "pit"}
        self.contract_version = contract_version
        self.chain = chain


class ExplodingAttrForwardInput:
    """Payload cuyo atributo público falla al leerse."""

    @property
    def contract_version(self) -> str:
        """Simula un descriptor roto en el contrato forward."""
        raise RuntimeError("boom")


class FailingModelCopyForwardInput(CompatibleForwardInput):
    """Payload compatible cuyo ``model_copy`` falla."""

    def model_copy(self, *, update: dict[str, object], deep: bool) -> object:
        """Falla deliberadamente para cubrir la ruta defensiva del clone."""
        del update, deep
        raise RuntimeError("copy boom")


class IgnoringTermModelCopyForwardInput(CompatibleForwardInput):
    """Payload compatible cuyo ``model_copy`` ignora el term inyectado."""

    def model_copy(self, *, update: dict[str, object], deep: bool) -> object:
        """Devuelve una copia válida pero con term-structure viejo."""
        del update, deep
        return CompatibleForwardInput(
            term_structure_frame=self.term_structure_frame,
            scenario_weight_frame=self.scenario_weight_frame,
        )


class IgnoringWeightModelCopyForwardInput(CompatibleForwardInput):
    """Payload compatible cuyo ``model_copy`` ignora los pesos inyectados."""

    def model_copy(self, *, update: dict[str, object], deep: bool) -> object:
        """Aplica el term nuevo pero conserva pesos viejos."""
        del deep
        term = update["term_structure_frame"]
        assert isinstance(term, pd.DataFrame)
        return CompatibleForwardInput(
            term_structure_frame=term,
            scenario_weight_frame=self.scenario_weight_frame,
        )


class ReadOnlyCompatibleForwardInput:
    """Payload compatible pero no mutable para cubrir fallback sin ``model_copy``."""

    def __init__(self, *, term: pd.DataFrame | None, weights: pd.DataFrame) -> None:
        self._term = term
        self._weights = weights
        self.pit_consistency = {"basis": "pit"}
        self.contract_version = FORWARD_ECL_CONTRACT_VERSION
        self.chain = engine_module._FORWARD_ECL_CHAIN

    @property
    def term_structure_frame(self) -> pd.DataFrame | None:
        """Term-structure solo lectura."""
        return self._term

    @property
    def scenario_weight_frame(self) -> pd.DataFrame:
        """Pesos solo lectura."""
        return self._weights


class ImmutableForwardInput:
    """Payload ECL que no permite setear ``term_structure_frame``."""

    __slots__ = ()


class OpaqueHashCell:
    """Objeto sin estado público para probar hash opaco estable."""

    __slots__ = ()


class PublicStateHashCell:
    """Objeto con estado público material para probar hash reproducible."""

    def __init__(self, value: int) -> None:
        self.value = value


class MissingValueSentinel:
    """Objeto cuyo ``!=`` falla para cubrir ruta defensiva de missing."""

    def __ne__(self, other: object) -> bool:
        """Levanta ``ValueError`` como algunos objetos tabulares raros."""
        del other
        raise ValueError("comparación inválida")


def _satellite_with_coefficients(payload: Any, *, attr: str = "coefficients_") -> object:
    """Crea un satellite dinámico pequeño para rutas de coeficientes."""
    return type("SatelliteFixture", (), {attr: payload})()


def test_stress_engine_golden_satellite_ecl_y_attrs() -> None:
    """Escenario severo reproduce goldens SDD-21 §11 con ECL stub."""
    cfg = _cfg(metrics=("pd_marginal", "pd_cumulative", "ecl"))
    ecl = EclStub()
    weighting = ScenarioWeightingStub()
    macro = _macro_projection(periods=(1,), adverse={1: 1.0}, severe={1: 0.0})
    term = _forward_term_structure([0.02])
    ecl_input = _ecl_input(term)
    audit = InMemoryAuditSink()

    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=ecl_input,
        macro_projection=macro,
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=weighting,
        ecl_engine=ecl,
        audit=audit,
    )

    observed_term = result.term_structure()
    assert observed_term is not None
    assert weighting.calls == 1
    assert [event.payload["regla"] for event in audit.events] == [
        "stress_forward_inputs",
        "stress_size_estimate",
        "stress_scenario_config",
        "stress_dominance_check",
        "stress_macro_application",
        "stress_satellite_application",
        "stress_term_structure",
        "stress_economic_engine",
        "stress_result",
    ]
    audit_by_rule = {str(event.payload["regla"]): event.payload for event in audit.events}
    size_event = audit_by_rule["stress_size_estimate"]
    assert size_event["accion"] == "diagnose"
    assert size_event["umbral"] == {
        "expression": "term_structure_rows * scenario_count",
        "configurable_limit": None,
    }
    assert size_event["valor"]["macro_rows"] == len(macro.index)
    assert size_event["valor"]["term_structure_rows"] == len(term.index)
    assert size_event["valor"]["scenario_count"] == len(cfg.scenarios)
    assert size_event["valor"]["estimated_stress_term_structure_rows"] == len(term.index)
    assert size_event["valor"]["estimated_sensitivity_evaluations"] == 0
    assert size_event["valor"]["estimated_reverse_evaluations"] == 0
    scenario_event = audit_by_rule["stress_scenario_config"]
    assert scenario_event["valor"]["shocks"][0]["factor"] == "x"
    assert scenario_event["valor"]["shocks"][0]["operation"] == "additive"
    assert scenario_event["valor"]["shocks"][0]["source"] == "user"
    assert audit_by_rule["stress_dominance_check"]["accion"] == "skip"
    satellite_event = audit_by_rule["stress_satellite_application"]
    satellite_row = satellite_event["valor"]["records"][0]
    assert satellite_event["valor"]["row_count"] == 1
    assert satellite_row["satellite_model_id"] == "sat:test"
    assert satellite_row["factors"][0]["coefficient"] == pytest.approx(0.5)
    assert satellite_row["factors"][0]["macro_delta"] == pytest.approx(1.0)
    assert satellite_row["delta_logit"] == pytest.approx(0.5)
    term_event = audit_by_rule["stress_term_structure"]
    assert term_event["valor"]["row_count"] == 1
    assert term_event["valor"]["basis"] == ("pit",)
    assert term_event["valor"]["warning_codes"] == ()
    assert term_event["valor"]["probability_ranges"]["hazard_stress"]["max"] == pytest.approx(
        0.0325520809,
        abs=1e-10,
    )
    assert result.diagnostics.scenario_count == 1
    assert result.diagnostics.dependency_versions["nikodym.stress.engine"] == "B21.3"
    assert result.card.metric_sections["scenario_impacts"]["metrics"] == (
        "pd_marginal",
        "pd_cumulative",
        "ecl",
    )
    assert observed_term.loc[0, "hazard_stress"] == pytest.approx(0.0325520809, abs=1e-10)
    assert observed_term.loc[0, "pd_marginal_stress"] == pytest.approx(
        0.0325520809,
        abs=1e-10,
    )
    assert observed_term.loc[0, "pd_basis"] == "pit"
    assert observed_term.loc[0, "basis_state"] == "pit"
    assert observed_term.loc[0, "macro_variable_set"] == ("x",)
    assert observed_term.loc[0, "satellite_adjustment_stress"] == pytest.approx(0.5)

    scenarios = result.scenarios()
    assert tuple(scenarios.columns) == _STRESS_SCENARIO_COLUMNS
    assert tuple(result.scenario_results[0].scenario_frame.columns) == _STRESS_SCENARIO_COLUMNS
    assert (
        tuple(result.scenario_results[0].stressed_macro_frame.columns) == _MACRO_PROJECTION_COLUMNS
    )
    assert scenarios.loc[0, "stress_scenario"] == "severe_plus"
    assert scenarios.loc[0, "base_forward_scenario"] == "severe"
    assert scenarios.loc[0, "macro_variable"] == "x"
    assert scenarios.loc[0, "operation"] == "additive"
    assert scenarios.loc[0, "applied_shock"] == pytest.approx(1.0)
    assert_frame_equal(result.scenario_results[0].scenario_frame, scenarios)
    assert result.card.summary["scenario_rows"] == 1
    assert result.card.metric_sections["stress_scenarios"]["rows"] == 1

    impact = result.tidy()
    ecl_row = impact[impact["metric"] == "ecl"].iloc[0]
    assert ecl_row["value_base"] == pytest.approx(9.0, abs=1e-10)
    assert ecl_row["value_stress"] == pytest.approx(14.6484363909, abs=1e-10)
    assert ecl_row["absolute_delta"] == pytest.approx(5.6484363909, abs=1e-10)
    assert ecl_row["engine_source"] == "ecl_engine"
    assert ecl.calls[0].loc[0, "scenario"] == "severe"
    assert ecl.calls[1].loc[0, "scenario"] == "severe_plus"
    assert ecl.calls[1].loc[0, "pd_marginal"] == pytest.approx(0.0325520809, abs=1e-10)

    engine = StressTestEngine.from_config(cfg)
    second = engine.run(
        forward_ecl_input=ecl_input,
        macro_projection=macro,
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=EclStub(),
    )
    assert engine.forward_hash_ is not None
    assert engine.config_hash_ is not None
    assert engine.run_started_at_ is not None
    assert engine.scenario_results_ == second.scenario_results
    assert engine.sensitivity_results_ == ()
    assert engine.reverse_results_ == ()
    assert engine.diagnostics_ == second.diagnostics


def test_forward_hash_distingue_dependencias_no_tabulares() -> None:
    """El lineage cambia si cambian coeficientes, pesos ECL o identidad del engine."""
    cfg = _cfg(metrics=("ecl",))
    macro = _macro_projection(periods=(1,), include_adverse=False)
    term = _forward_term_structure([0.02])

    def run_case(
        *,
        satellite_model: object | None = None,
        ecl_input: ForwardEclInput | None = None,
        ecl_engine: EclEngineLike | None = None,
        scenario_weighting: object | None = None,
    ) -> tuple[str, dict[str, Any]]:
        audit = InMemoryAuditSink()
        engine = StressTestEngine.from_config(cfg)
        engine.run(
            forward_ecl_input=ecl_input or _ecl_input(term),
            macro_projection=macro,
            satellite_model=satellite_model or SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=scenario_weighting or ScenarioWeightingStub(),
            ecl_engine=ecl_engine or EclStub(),
            audit=audit,
        )
        assert engine.forward_hash_ is not None
        forward_event = next(
            event.payload
            for event in audit.events
            if event.payload["regla"] == "stress_forward_inputs"
        )
        return engine.forward_hash_, forward_event["valor"]["lineage_components"]

    base_hash, base_components = run_case()
    satellite_hash, satellite_components = run_case(satellite_model=AlternateSatelliteStub())
    engine_hash, engine_components = run_case(ecl_engine=EquivalentEclStub())
    stateful_hash, stateful_components = run_case(
        ecl_engine=StatefulEclStub(limit=0.10, probability_tol=1e-10)
    )
    stateful_alt_hash, stateful_alt_components = run_case(
        ecl_engine=StatefulEclStub(limit=0.20, probability_tol=2e-10)
    )
    history_hash, history_components = run_case(ecl_engine=HistoryConfiguredEclStub(1.0))
    history_alt_hash, history_alt_components = run_case(ecl_engine=HistoryConfiguredEclStub(2.0))
    slotted_history_hash, slotted_history_components = run_case(
        ecl_engine=SlottedHistoryConfiguredEclStub(1.0)
    )
    slotted_history_alt_hash, slotted_history_alt_components = run_case(
        ecl_engine=SlottedHistoryConfiguredEclStub(2.0)
    )
    callable_hash, callable_components = run_case(
        ecl_engine=CallableConfiguredEclStub(_lineage_ecl_multiplier_one)
    )
    callable_alt_hash, callable_alt_components = run_case(
        ecl_engine=CallableConfiguredEclStub(_lineage_ecl_multiplier_two)
    )
    bound_callable_hash, bound_callable_components = run_case(
        ecl_engine=CallableConfiguredEclStub(BoundLineageMultiplier(1.0).scale)
    )
    bound_callable_alt_hash, bound_callable_alt_components = run_case(
        ecl_engine=CallableConfiguredEclStub(BoundLineageMultiplier(2.0).scale)
    )
    partial_callable_hash, partial_callable_components = run_case(
        ecl_engine=CallableConfiguredEclStub(
            functools.partial(_lineage_ecl_multiplier_partial, multiplier=1.0)
        )
    )
    partial_callable_alt_hash, partial_callable_alt_components = run_case(
        ecl_engine=CallableConfiguredEclStub(
            functools.partial(_lineage_ecl_multiplier_partial, multiplier=2.0)
        )
    )
    nested_callable_hash, nested_callable_components = run_case(
        ecl_engine=NestedCallableConfigEclStub(
            functools.partial(_lineage_ecl_multiplier_partial, multiplier=1.0)
        )
    )
    nested_callable_alt_hash, nested_callable_alt_components = run_case(
        ecl_engine=NestedCallableConfigEclStub(
            functools.partial(_lineage_ecl_multiplier_partial, multiplier=2.0)
        )
    )

    alt_weights = _ecl_input(term).scenario_weight_frame
    alt_weights.loc[alt_weights["scenario"] == "severe", "description"] = "severe alternativa"
    altered_input = ForwardEclInput(
        term_structure_frame=term,
        scenario_weight_frame=alt_weights,
        pit_consistency={"basis": "pit"},
        contract_version=FORWARD_ECL_CONTRACT_VERSION,
    )
    input_hash, input_components = run_case(ecl_input=altered_input)
    weighting_hash, weighting_components = run_case(
        scenario_weighting=StatefulScenarioWeightingStub("ponderador-a")
    )
    weighting_alt_hash, weighting_alt_components = run_case(
        scenario_weighting=StatefulScenarioWeightingStub("ponderador-b")
    )

    assert satellite_hash != base_hash
    assert (
        satellite_components["satellite_model"]["coefficients_hash"]
        != (base_components["satellite_model"]["coefficients_hash"])
    )
    assert engine_hash != base_hash
    assert engine_components["ecl_engine"]["type"] != base_components["ecl_engine"]["type"]
    assert stateful_alt_hash != stateful_hash
    assert (
        stateful_alt_components["ecl_engine"]["state_hash"]
        != stateful_components["ecl_engine"]["state_hash"]
    )
    assert history_alt_hash != history_hash
    assert (
        history_alt_components["ecl_engine"]["state_hash"]
        != history_components["ecl_engine"]["state_hash"]
    )
    assert slotted_history_alt_hash != slotted_history_hash
    assert (
        slotted_history_alt_components["ecl_engine"]["state_hash"]
        != slotted_history_components["ecl_engine"]["state_hash"]
    )
    assert callable_alt_hash != callable_hash
    assert (
        callable_alt_components["ecl_engine"]["state_hash"]
        != callable_components["ecl_engine"]["state_hash"]
    )
    assert bound_callable_alt_hash != bound_callable_hash
    assert (
        bound_callable_alt_components["ecl_engine"]["state_hash"]
        != bound_callable_components["ecl_engine"]["state_hash"]
    )
    assert partial_callable_alt_hash != partial_callable_hash
    assert (
        partial_callable_alt_components["ecl_engine"]["state_hash"]
        != partial_callable_components["ecl_engine"]["state_hash"]
    )
    assert nested_callable_alt_hash != nested_callable_hash
    assert (
        nested_callable_alt_components["ecl_engine"]["state_hash"]
        != nested_callable_components["ecl_engine"]["state_hash"]
    )
    assert input_hash != base_hash
    assert (
        input_components["forward_ecl_input"]["scenario_weight_frame_hash"]
        != (base_components["forward_ecl_input"]["scenario_weight_frame_hash"])
    )
    assert weighting_alt_hash != weighting_hash
    assert (
        weighting_alt_components["scenario_weighting"]["state_hash"]
        != weighting_components["scenario_weighting"]["state_hash"]
    )


def test_forward_hash_estable_al_reusar_dependencias_con_estado_runtime() -> None:
    """Contadores/historiales de ejecución no cambian el lineage lógico entre corridas."""
    cfg = _cfg(metrics=("ecl",))
    macro = _macro_projection(periods=(1,), include_adverse=False)
    term = _forward_term_structure([0.02])
    ecl_input = _ecl_input(term)
    ecl_engine = EclStub()
    scenario_weighting = ScenarioWeightingStub()
    hashes: list[str] = []
    weighting_state_hashes: list[str | None] = []

    for _ in range(2):
        audit = InMemoryAuditSink()
        engine = StressTestEngine.from_config(cfg)
        engine.run(
            forward_ecl_input=ecl_input,
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=scenario_weighting,
            ecl_engine=ecl_engine,
            audit=audit,
        )
        assert engine.forward_hash_ is not None
        hashes.append(engine.forward_hash_)
        forward_event = next(
            event.payload
            for event in audit.events
            if event.payload["regla"] == "stress_forward_inputs"
        )
        weighting_state_hashes.append(
            forward_event["valor"]["lineage_components"]["scenario_weighting"]["state_hash"]
        )

    assert hashes[1] == hashes[0]
    assert weighting_state_hashes == [None, None]
    assert scenario_weighting.calls == 2
    assert len(ecl_engine.calls) == 4


def test_macro_projection_permutada_conserva_forward_hash_y_publicacion() -> None:
    """El macro lógico no depende del orden físico de filas, columnas ni índice."""
    cfg = _cfg(metrics=("pd_marginal",))
    macro_x = _macro_projection(
        periods=(1, 2),
        include_adverse=False,
        severe={1: 0.0, 2: 0.5},
    )
    macro_z = macro_x.copy(deep=True)
    macro_z.loc[:, "macro_variable"] = "z"
    macro_z.loc[:, "projected_value"] = [10.0, 20.0]
    macro_z.loc[:, "model_value"] = [10.0, 20.0]
    macro_z.loc[:, "shock_value"] = [0.0, 0.0]
    canonical_logical = pd.concat([macro_x, macro_z], ignore_index=True)
    permuted = canonical_logical.iloc[[3, 1, 0, 2]].copy(deep=True)
    permuted.index = pd.Index(["z-2", "x-2", "x-1", "z-1"], name="external_row")
    permuted = permuted.loc[:, list(reversed(canonical_logical.columns))]
    term = _forward_term_structure([0.02, 0.03])

    def run_case(macro: pd.DataFrame) -> tuple[str, dict[str, Any], pd.DataFrame, pd.DataFrame]:
        audit = InMemoryAuditSink()
        engine = StressTestEngine.from_config(cfg)
        result = engine.run(
            forward_ecl_input=_ecl_input(term),
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
            audit=audit,
        )
        assert engine.forward_hash_ is not None
        forward_event = next(
            event.payload
            for event in audit.events
            if event.payload["regla"] == "stress_forward_inputs"
        )
        return (
            engine.forward_hash_,
            forward_event["valor"]["lineage_components"],
            result.scenario_results[0].stressed_macro_frame,
            result.scenarios(),
        )

    base_hash, base_components, base_macro_publicado, base_scenarios = run_case(canonical_logical)
    permuted_hash, permuted_components, permuted_macro_publicado, permuted_scenarios = run_case(
        permuted
    )

    assert permuted_hash == base_hash
    assert (
        permuted_components["macro_projection"]["hash"]
        == base_components["macro_projection"]["hash"]
    )
    assert (
        permuted_components["macro_projection"]["columns"]
        == base_components["macro_projection"]["columns"]
    )
    assert_frame_equal(permuted_macro_publicado, base_macro_publicado)
    assert_frame_equal(permuted_scenarios, base_scenarios)
    assert base_macro_publicado["macro_variable"].tolist() == ["x", "x", "z", "z"]
    assert base_macro_publicado["period"].tolist() == [1, 2, 1, 2]
    assert base_macro_publicado["projected_value"].tolist() == [1.0, 1.5, 10.0, 20.0]
    assert base_macro_publicado.index.tolist() == [0, 1, 2, 3]


def test_macro_projection_canoniza_projected_y_model_en_forward_hash() -> None:
    """Macros equivalentes con floats/Decimal/string conservan hash y output."""
    cfg = _cfg(metrics=("pd_marginal",))
    term = _forward_term_structure([0.02])
    macro_float = _macro_projection(periods=(1,), include_adverse=False)
    macro_float.loc[:, "projected_value"] = 0.75
    macro_float.loc[:, "model_value"] = 0.25
    macro_float.loc[:, "shock_value"] = 0.50
    macro_coercible = macro_float.copy(deep=True)
    macro_coercible["projected_value"] = pd.Series(["0.75"], dtype=object)
    macro_coercible["model_value"] = pd.Series([Decimal("0.25")], dtype=object)
    macro_coercible["shock_value"] = pd.Series(["0.50"], dtype=object)

    def run_case(macro: pd.DataFrame) -> tuple[str, pd.DataFrame, pd.DataFrame]:
        engine = StressTestEngine.from_config(cfg)
        result = engine.run(
            forward_ecl_input=_ecl_input(term),
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
        )
        assert engine.forward_hash_ is not None
        return (
            engine.forward_hash_,
            result.tidy(),
            result.scenario_results[0].stressed_macro_frame,
        )

    float_hash, float_output, float_macro_publicado = run_case(macro_float)
    coercible_hash, coercible_output, coercible_macro_publicado = run_case(macro_coercible)

    assert coercible_hash == float_hash
    assert_frame_equal(coercible_output, float_output)
    assert_frame_equal(coercible_macro_publicado, float_macro_publicado)


def test_macro_projection_hash_no_oculta_columnas_reales_sort() -> None:
    """Columnas macro reales ``_sort_*`` afectan lineage y no se borran como helpers."""
    cfg = _cfg(metrics=("pd_marginal",))
    term = _forward_term_structure([0.02])

    def run_case(value: str) -> tuple[str, dict[str, Any], pd.DataFrame]:
        macro = _macro_projection(periods=(1,), include_adverse=False)
        macro.loc[:, "_sort_user"] = value
        engine = StressTestEngine.from_config(cfg)
        audit = InMemoryAuditSink()
        result = engine.run(
            forward_ecl_input=_ecl_input(term),
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
            audit=audit,
        )
        forward_event = next(
            event.payload
            for event in audit.events
            if event.payload["regla"] == "stress_forward_inputs"
        )
        assert engine.forward_hash_ is not None
        return (
            engine.forward_hash_,
            forward_event["valor"]["lineage_components"],
            result.scenario_results[0].stressed_macro_frame,
        )

    hash_a, components_a, published_a = run_case("valor-a")
    hash_b, components_b, published_b = run_case("valor-b")

    assert hash_b != hash_a
    assert "_sort_user" in components_a["macro_projection"]["columns"]
    assert components_b["macro_projection"]["hash"] != components_a["macro_projection"]["hash"]
    assert tuple(published_a.columns) == _MACRO_PROJECTION_COLUMNS
    assert tuple(published_b.columns) == _MACRO_PROJECTION_COLUMNS


def test_forward_hash_canonico_permutando_term_structure_y_ecl_frames() -> None:
    """Lineage ignora orden físico de term-structure y frames del contrato ECL."""
    cfg = _cfg(metrics=("ecl",))
    macro = _macro_projection(
        periods=(1, 2),
        include_adverse=False,
        severe={1: 0.0, 2: 0.5},
    )
    term = _forward_term_structure([0.02, 0.03])
    base_ecl_input = _ecl_input(term)
    weights = base_ecl_input.scenario_weight_frame

    permuted_forward_term = term.iloc[[1, 0]].copy(deep=True)
    permuted_forward_term.index = pd.Index(["term-2", "term-1"], name="external_term")
    permuted_forward_term = permuted_forward_term.loc[:, list(reversed(term.columns))]

    permuted_ecl_term = term.iloc[[1, 0]].copy(deep=True)
    permuted_ecl_term.index = pd.Index(["ecl-2", "ecl-1"], name="external_ecl_term")
    permuted_weights = weights.iloc[[2, 0, 1]].copy(deep=True)
    permuted_weights.index = pd.Index(["w-severe", "w-base", "w-adverse"], name="external_weight")

    def run_case(
        *,
        forward_term_structure: pd.DataFrame,
        ecl_term_structure: pd.DataFrame,
        scenario_weight_frame: pd.DataFrame,
    ) -> tuple[str, dict[str, Any], pd.DataFrame]:
        audit = InMemoryAuditSink()
        engine = StressTestEngine.from_config(cfg)
        ecl_input = ForwardEclInput(
            term_structure_frame=ecl_term_structure,
            scenario_weight_frame=scenario_weight_frame,
            pit_consistency={"basis": "pit"},
            contract_version=FORWARD_ECL_CONTRACT_VERSION,
        )
        result = engine.run(
            forward_ecl_input=ecl_input,
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=forward_term_structure,
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=EclStub(),
            audit=audit,
        )
        assert engine.forward_hash_ is not None
        forward_event = next(
            event.payload
            for event in audit.events
            if event.payload["regla"] == "stress_forward_inputs"
        )
        return engine.forward_hash_, forward_event["valor"]["lineage_components"], result.tidy()

    base_hash, base_components, base_impact = run_case(
        forward_term_structure=term,
        ecl_term_structure=term,
        scenario_weight_frame=weights,
    )
    permuted_hash, permuted_components, permuted_impact = run_case(
        forward_term_structure=permuted_forward_term,
        ecl_term_structure=permuted_ecl_term,
        scenario_weight_frame=permuted_weights,
    )

    assert permuted_hash == base_hash
    assert (
        permuted_components["forward_term_structure"]["hash"]
        == base_components["forward_term_structure"]["hash"]
    )
    assert (
        permuted_components["forward_ecl_input"]["term_structure_frame_hash"]
        == base_components["forward_ecl_input"]["term_structure_frame_hash"]
    )
    assert (
        permuted_components["forward_ecl_input"]["scenario_weight_frame_hash"]
        == base_components["forward_ecl_input"]["scenario_weight_frame_hash"]
    )
    assert (
        permuted_components["forward_term_structure"]["columns"]
        == base_components["forward_term_structure"]["columns"]
    )
    assert_frame_equal(permuted_impact, base_impact)


def test_forward_hash_canoniza_term_structure_y_pesos_coercibles() -> None:
    """Lineage usa la forma lógica de frames forward aceptados por validación."""
    cfg = _cfg(metrics=("pd_marginal",))
    macro = _macro_projection(periods=(1,), include_adverse=False)
    term = _forward_term_structure([0.02])
    weights = _ecl_input(term).scenario_weight_frame
    coerced_term = term.copy(deep=True)
    for column in (
        "period",
        "time_value",
        "scenario_weight",
        "hazard",
        "survival",
        "pd_marginal",
        "pd_cumulative",
        "pd_marginal_base",
        "pd_cumulative_base",
        "lgd",
        "lgd_base",
        "ttc_reversion_weight",
        "satellite_adjustment",
    ):
        coerced_term[column] = coerced_term[column].astype(str)
    for column in ("scenario", "source_model", "method", "pd_source", "pd_basis", "basis_state"):
        coerced_term[column] = coerced_term[column].map(lambda value: f" {value} ")
    coerced_term["warning_codes"] = [[] for _ in range(len(coerced_term.index))]

    def run_case(
        *,
        forward_term_structure: pd.DataFrame,
        ecl_term_structure: pd.DataFrame,
        scenario_weight_frame: pd.DataFrame,
    ) -> tuple[str, dict[str, Any], pd.DataFrame]:
        term_before = forward_term_structure.copy(deep=True)
        engine = StressTestEngine.from_config(cfg)
        audit = InMemoryAuditSink()
        ecl_input = ForwardEclInput(
            term_structure_frame=ecl_term_structure,
            scenario_weight_frame=scenario_weight_frame,
            pit_consistency={"basis": "pit"},
            contract_version=FORWARD_ECL_CONTRACT_VERSION,
        )
        result = engine.run(
            forward_ecl_input=ecl_input,
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=forward_term_structure,
            scenario_weighting=ScenarioWeightingStub(),
            audit=audit,
        )
        assert engine.forward_hash_ is not None
        assert_frame_equal(forward_term_structure, term_before)
        forward_event = next(
            event.payload
            for event in audit.events
            if event.payload["regla"] == "stress_forward_inputs"
        )
        return engine.forward_hash_, forward_event["valor"]["lineage_components"], result.tidy()

    base_hash, base_components, base_impact = run_case(
        forward_term_structure=term,
        ecl_term_structure=term,
        scenario_weight_frame=weights,
    )
    coerced_hash, coerced_components, coerced_impact = run_case(
        forward_term_structure=coerced_term,
        ecl_term_structure=coerced_term,
        scenario_weight_frame=weights,
    )

    assert coerced_hash == base_hash
    assert (
        coerced_components["forward_term_structure"]["hash"]
        == base_components["forward_term_structure"]["hash"]
    )
    assert (
        coerced_components["forward_ecl_input"]["term_structure_frame_hash"]
        == base_components["forward_ecl_input"]["term_structure_frame_hash"]
    )
    assert (
        coerced_components["forward_ecl_input"]["scenario_weight_frame_hash"]
        == base_components["forward_ecl_input"]["scenario_weight_frame_hash"]
    )
    assert_frame_equal(coerced_impact, base_impact)


def test_forward_hash_no_oculta_columnas_reales_con_prefijo_hash_sort() -> None:
    """Columnas reales ``_hash_sort_*`` afectan lineage y llegan al engine económico."""
    cfg = _cfg(metrics=("ecl",))
    macro = _macro_projection(periods=(1,), include_adverse=False)

    def run_case(value: str) -> tuple[str, CapturingEclStub]:
        term = _forward_term_structure([0.02])
        term.loc[:, "_hash_sort_0"] = value
        term.loc[:, "_sort_row_id"] = f"sort-{value}"
        ecl = CapturingEclStub()
        ecl_input = CompatibleForwardInput(
            term_structure_frame=None,
            scenario_weight_frame=_ecl_input(_forward_term_structure([0.02])).scenario_weight_frame,
        )
        engine = StressTestEngine.from_config(cfg)
        engine.run(
            forward_ecl_input=ecl_input,
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=ecl,
        )
        assert engine.forward_hash_ is not None
        return engine.forward_hash_, ecl

    hash_a, ecl_a = run_case("valor-a")
    hash_b, ecl_b = run_case("valor-b")

    assert hash_b != hash_a
    assert ecl_a.calls[1]["_hash_sort_0"].tolist() == ["valor-a"]
    assert ecl_b.calls[1]["_hash_sort_0"].tolist() == ["valor-b"]
    assert ecl_a.calls[1]["_sort_row_id"].tolist() == ["sort-valor-a"]
    assert ecl_b.calls[1]["_sort_row_id"].tolist() == ["sort-valor-b"]


def test_forward_hash_canoniza_temporales_en_payload_compatible() -> None:
    """Valores temporales en claves lógicas cambian el lineage aunque el DTO sea compatible."""
    cfg = _cfg(metrics=("pd_marginal",))
    macro = _macro_projection(periods=(1,), include_adverse=False)
    weights = pd.DataFrame(
        [
            {
                "scenario": "severe",
                "weight": 1.0,
                "is_default": False,
                "source": "config",
                "description": "severe",
            }
        ],
        columns=_SCENARIO_WEIGHT_COLUMNS,
    )

    def run_case(row_id: pd.Timestamp) -> tuple[str, str]:
        term = _forward_term_structure([0.02])
        term.loc[:, "row_id"] = pd.Series([row_id], dtype=object)
        engine = StressTestEngine.from_config(cfg)
        result = engine.run(
            forward_ecl_input=CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights,
            ),
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
        )
        assert engine.forward_hash_ is not None
        return engine.forward_hash_, str(result.tidy().loc[0, "group_key"])

    hash_a, group_a = run_case(pd.Timestamp("2026-01-01"))
    hash_b, group_b = run_case(pd.Timestamp("2027-01-01"))

    assert hash_a != hash_b
    assert group_a != group_b


def test_hash_frame_canoniza_objetos_opacos_y_estado_publico() -> None:
    """El hash tabular no depende de identidad/repr con dirección de memoria."""
    opaque_a = pd.DataFrame({"payload": [OpaqueHashCell()]})
    opaque_b = pd.DataFrame({"payload": [OpaqueHashCell()]})
    same_state_a = pd.DataFrame({"payload": [PublicStateHashCell(1)]})
    same_state_b = pd.DataFrame({"payload": [PublicStateHashCell(1)]})
    other_state = pd.DataFrame({"payload": [PublicStateHashCell(2)]})

    assert engine_module._combined_frame_hash((opaque_a,), pd=pd) == (
        engine_module._combined_frame_hash((opaque_b,), pd=pd)
    )
    assert engine_module._combined_frame_hash((same_state_a,), pd=pd) == (
        engine_module._combined_frame_hash((same_state_b,), pd=pd)
    )
    assert engine_module._combined_frame_hash((other_state,), pd=pd) != (
        engine_module._combined_frame_hash((same_state_a,), pd=pd)
    )

    seed_code = "\n".join(
        [
            "import pandas as pd",
            "import nikodym.stress.engine as engine",
            "class Opaque:",
            "    __slots__ = ()",
            "class Public:",
            "    def __init__(self, value):",
            "        self.value = value",
            "frame = pd.DataFrame({'opaque': [Opaque()], 'public': [Public(7)]})",
            "print(engine._combined_frame_hash((frame,), pd=pd))",
        ]
    )
    seed_env = os.environ.copy()
    seed_env["PYTHONHASHSEED"] = "1"
    hash_seed_1 = subprocess.check_output(
        [sys.executable, "-c", seed_code],
        env=seed_env,
        text=True,
    ).strip()
    seed_env["PYTHONHASHSEED"] = "2"
    hash_seed_2 = subprocess.check_output(
        [sys.executable, "-c", seed_code],
        env=seed_env,
        text=True,
    ).strip()
    assert hash_seed_1 == hash_seed_2


def test_hash_numpy_normaliza_cero_negativo_endianness_y_no_finitos() -> None:
    """Arrays NumPy usan payload canónico sin signo de cero ni endianness físico."""
    assert engine_module._canonical_hash({"arr": np.array([-0.0, 1.0], dtype="<f8")}, pd=pd) == (
        engine_module._canonical_hash({"arr": np.array([0.0, 1.0], dtype=">f8")}, pd=pd)
    )
    assert engine_module._canonical_hash(
        {"arr": np.array([np.nan, np.inf, -np.inf], dtype="<f8")},
        pd=pd,
    ) == engine_module._canonical_hash(
        {"arr": np.array([np.nan, np.inf, -np.inf], dtype=">f8")},
        pd=pd,
    )
    assert engine_module._canonical_hash(
        {"arr": np.array([complex(-0.0, 0.0)], dtype="<c16")},
        pd=pd,
    ) == engine_module._canonical_hash(
        {"arr": np.array([complex(0.0, -0.0)], dtype=">c16")},
        pd=pd,
    )
    assert engine_module._canonical_hash({"arr": np.array([1, 2], dtype="<i8")}, pd=pd) == (
        engine_module._canonical_hash({"arr": np.array([1, 2], dtype=">i8")}, pd=pd)
    )


def test_forward_ecl_input_incompatible_falla_como_dependencia() -> None:
    """El contrato ``ForwardEclInput`` se valida antes de lineage/ECL."""
    cfg = _cfg(metrics=("pd_marginal",))
    term = _forward_term_structure([0.02])
    macro = _macro_projection(periods=(1,), include_adverse=False)
    weights = _ecl_input(term).scenario_weight_frame

    def run_with(forward_ecl_input: object) -> None:
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=forward_ecl_input,  # type: ignore[arg-type]
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
        )

    with pytest.raises(StressDependencyError, match="forward_ecl_input"):
        run_with(None)

    with pytest.raises(StressDependencyError, match="contract_version"):
        run_with(
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights,
                contract_version="forward-ecl-v2",
            )
        )

    with pytest.raises(StressDependencyError, match=r"scenario_weight_frame.*source"):
        run_with(
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.drop(columns=["source"]),
            )
        )


def test_forward_ecl_input_debe_coincidir_con_forward_autoritativo() -> None:
    """El input ECL no puede traer term-structure ni pesos distintos a lo usado por stress."""
    cfg = _cfg(metrics=("pd_marginal",))
    term = _forward_term_structure([0.02])
    macro = _macro_projection(periods=(1,), include_adverse=False)

    def run_with(
        *,
        ecl_term: pd.DataFrame | None = None,
        weights: pd.DataFrame | None = None,
    ) -> None:
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=CompatibleForwardInput(
                term_structure_frame=ecl_term if ecl_term is not None else term,
                scenario_weight_frame=weights
                if weights is not None
                else _ecl_input(term).scenario_weight_frame,
            ),
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
        )

    altered_term = term.copy(deep=True)
    altered_term.loc[0, "row_id"] = "id-alterno"
    with pytest.raises(StressDependencyError, match="term_structure_frame no coincide"):
        run_with(ecl_term=altered_term)

    missing_scenario_weights = pd.DataFrame(
        [
            {
                "scenario": "base",
                "weight": 1.0,
                "is_default": False,
                "source": "config",
                "description": "base",
            }
        ],
        columns=_SCENARIO_WEIGHT_COLUMNS,
    )
    with pytest.raises(StressDependencyError, match="no cubre escenarios"):
        run_with(weights=missing_scenario_weights)

    extra_nonzero_weights = _ecl_input(term).scenario_weight_frame.copy(deep=True)
    extra_nonzero_weights.loc[extra_nonzero_weights["scenario"] == "base", "weight"] = 0.1
    extra_nonzero_weights.loc[extra_nonzero_weights["scenario"] == "severe", "weight"] = 0.9
    with pytest.raises(StressDependencyError, match="escenarios extra"):
        run_with(weights=extra_nonzero_weights)

    mismatched_term = term.copy(deep=True)
    mismatched_term.loc[:, "scenario_weight"] = 0.9
    with pytest.raises(StressDependencyError, match="no coincide"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=CompatibleForwardInput(
                term_structure_frame=mismatched_term,
                scenario_weight_frame=_ecl_input(term).scenario_weight_frame,
            ),
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=mismatched_term,
            scenario_weighting=ScenarioWeightingStub(),
        )


def test_forward_ecl_input_clonado_respeta_tolerancia_configurada() -> None:
    """El precheck del clon ECL usa ``cfg.validation`` y no tolerancias por defecto."""
    base_term = _forward_term_structure([0.02])
    base_term.loc[:, "scenario"] = "base"
    base_term.loc[:, "scenario_weight"] = 0.6
    adverse_term = _forward_term_structure([0.02])
    adverse_term.loc[:, "scenario"] = "adverse"
    adverse_term.loc[:, "scenario_weight"] = 0.3
    severe_term = _forward_term_structure([0.02])
    severe_term.loc[:, "scenario_weight"] = 0.1000000005
    term = pd.concat([base_term, adverse_term, severe_term], ignore_index=True)
    weights = pd.DataFrame(
        [
            {
                "scenario": "base",
                "weight": 0.6,
                "is_default": False,
                "source": "config",
                "description": "base",
            },
            {
                "scenario": "adverse",
                "weight": 0.3,
                "is_default": False,
                "source": "config",
                "description": "adverse",
            },
            {
                "scenario": "severe",
                "weight": 0.1000000005,
                "is_default": False,
                "source": "config",
                "description": "severe",
            },
        ],
        columns=_SCENARIO_WEIGHT_COLUMNS,
    )
    cfg = _cfg(
        metrics=("ecl",),
        validation=StressValidationConfig(
            weight_sum_tol=1e-6,
            fail_on_falta_dato=False,
            require_dominates_forward_adverse=False,
        ),
    )

    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=CompatibleForwardInput(
            term_structure_frame=term,
            scenario_weight_frame=weights,
        ),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=EclStub(),
    )

    assert not result.tidy().empty


def test_acepta_forward_ecl_input_real_publicado_por_forward_step() -> None:
    """Stress consume el contrato ECL que ensambla ``ForwardStep`` sin versionarlo en tests."""
    cfg = _cfg(metrics=("pd_marginal",))
    term = _forward_term_structure([0.02])
    macro = _macro_projection(periods=(1,), include_adverse=False)
    forward_ecl_input = forward_step_module._ecl_input(
        forward_term_structure=term,
        scenario_weight_frame=_ecl_input(term).scenario_weight_frame,
        diagnostics=SimpleNamespace(
            pd_basis="pit",
            basis_states=("pit",),
            pit_warnings=(),
            pit_decisions=(),
        ),
    )

    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=forward_ecl_input,
        macro_projection=macro,
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
    )

    assert forward_ecl_input.contract_version == FORWARD_ECL_CONTRACT_VERSION
    assert result.scenarios()["stress_scenario"].tolist() == [cfg.scenarios[0].name]


def test_forward_ecl_input_contract_rechaza_formas_invalidas() -> None:
    """Ramas defensivas del contrato forward fallan como dependencia externa."""
    cfg = _cfg(metrics=("pd_marginal",))
    term = _forward_term_structure([0.02])
    weights = _ecl_input(term).scenario_weight_frame

    def validate(forward_ecl_input: object) -> None:
        engine_module._validate_forward_ecl_input_contract(forward_ecl_input, cfg=cfg, pd=pd)

    bad_pit_type = CompatibleForwardInput(term_structure_frame=term, scenario_weight_frame=weights)
    bad_pit_type.pit_consistency = None  # type: ignore[assignment]
    cases: list[tuple[object, str]] = [
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights,
                chain="cadena-incompatible",
            ),
            "chain",
        ),
        (bad_pit_type, "pit_consistency"),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights,
                pit_consistency={"x": math.inf},
            ),
            "no finitos",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights,
                pit_consistency={"x": Decimal("Infinity")},
            ),
            "no finitos",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=object(),  # type: ignore[arg-type]
            ),
            "pandas.DataFrame",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(scenario=""),
            ),
            "scenario",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(scenario=["mean", "adverse", "severe"]),
            ),
            "escenario medio",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(scenario="severe"),
            ),
            "duplicados",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(weight=-0.1),
            ),
            "negativo",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(source=""),
            ),
            "source",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(source="manual"),
            ),
            "default_a_confirmar",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(is_default="no"),
            ),
            "is_default",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(description=""),
            ),
            "description",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(description=math.inf),
            ),
            "description",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.iloc[0:0],
            ),
            "no puede estar vacío",
        ),
        (
            CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=weights.assign(weight=0.5),
            ),
            "deben sumar 1",
        ),
    ]
    broken_term = term.copy(deep=True)
    broken_term.loc[0, "pd_marginal"] = 0.50
    cases.append(
        (
            CompatibleForwardInput(
                term_structure_frame=broken_term,
                scenario_weight_frame=weights,
            ),
            "lifetime incoherente",
        )
    )

    for payload, pattern in cases:
        with pytest.raises(StressDependencyError, match=pattern):
            validate(payload)

    with pytest.raises(StressDependencyError, match="no se pudo leer"):
        validate(ExplodingAttrForwardInput())


def test_macro_projection_rechaza_clave_scenario_factor_period_duplicada() -> None:
    """La canonicidad falla ruidoso si el macro no tiene clave lógica única."""
    cfg = _cfg(metrics=("pd_marginal",))
    macro = _macro_projection(periods=(1,), include_adverse=False)
    duplicate = macro.copy(deep=True)
    duplicate.loc[:, "macro_variable"] = "z"
    duplicate.loc[:, "projected_value"] = 3.0
    duplicate.loc[:, "model_value"] = 3.0
    duplicate.loc[:, "shock_value"] = 0.0
    duplicated_macro = pd.concat([macro, duplicate, duplicate], ignore_index=True)

    with pytest.raises(StressScenarioError, match="scenario/macro_variable/period"):
        _run_forward_only(
            cfg,
            macro=duplicated_macro,
            term=_forward_term_structure([0.02]),
        )


def test_macro_projection_rechaza_columnas_duplicadas_con_error_tipado() -> None:
    """Columnas duplicadas en macro fallan temprano sin ``AttributeError``."""
    macro = _macro_projection(periods=(1,), include_adverse=False)
    duplicated_macro = pd.concat([macro, macro[["scenario"]]], axis=1)

    with pytest.raises(StressInputError, match=r"macro_projection.*columnas duplicadas"):
        _run_forward_only(
            _cfg(metrics=("pd_marginal",)),
            macro=duplicated_macro,
            term=_forward_term_structure([0.02]),
        )


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"scenario_weight": -0.1}, "scenario_weight"),
        ({"time_value": -1.0}, "time_value"),
        ({"method": "   "}, "method"),
        ({"model_id": ""}, "model_id"),
        ({"is_reasonable_supportable": "yes"}, "is_reasonable_supportable"),
        ({"warning_codes": "WARN"}, "warning_codes"),
        ({"warning_codes": (1,)}, "warning_codes"),
    ],
)
def test_macro_projection_invalida_falla_antes_de_lineage(
    updates: dict[str, object],
    match: str,
) -> None:
    """Campos macro inválidos fallan como input antes de iniciar la corrida."""
    macro = _macro_projection(periods=(1,), include_adverse=False)
    for column, value in updates.items():
        macro[column] = pd.Series([value] * len(macro), index=macro.index, dtype=object)
    engine = StressTestEngine.from_config(_cfg(metrics=("pd_marginal",)))

    with pytest.raises(StressInputError, match=match):
        engine.run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
        )

    assert engine.run_started_at_ is None
    assert engine.forward_hash_ is None
    assert engine.config_hash_ is None
    assert engine._context is None


def test_macro_projection_booleano_nullable_se_normaliza() -> None:
    """Booleanos numpy y ``warning_codes`` nulos se normalizan antes del DTO."""
    macro = _macro_projection(periods=(1,), include_adverse=False)
    macro["is_reasonable_supportable"] = pd.Series(
        [np.bool_(True)],
        index=macro.index,
        dtype=object,
    )
    macro["warning_codes"] = pd.Series([None], index=macro.index, dtype=object)

    result = _run_forward_only(
        _cfg(metrics=("pd_marginal",)),
        macro=macro,
        term=_forward_term_structure([0.02]),
    )

    published = result.scenario_results[0].stressed_macro_frame
    assert published.loc[0, "is_reasonable_supportable"] is True
    assert published.loc[0, "warning_codes"] == ()


def test_apply_macro_shocks_conserva_guard_defensivo_de_fila_unica() -> None:
    """El helper interno mantiene el error ruidoso si recibe macro no canónico."""
    macro = pd.concat(
        [_macro_projection(include_adverse=False), _macro_projection(include_adverse=False)],
        ignore_index=True,
    )

    with pytest.raises(StressScenarioError, match="fila única"):
        engine_module._apply_macro_shocks(
            _scenario(),
            severity=1.0,
            macro_projection=macro,
            forward_term_structure=_forward_term_structure([0.02]),
            cfg=_cfg(metrics=("pd_marginal",)),
            pd=pd,
            audit=None,
        )


def test_forward_hazard_en_frontera_es_valido_para_stress() -> None:
    """Stress consume hazards 0/1 válidos del contrato forward sin logit inválido."""
    cfg = _cfg(metrics=("pd_marginal",))
    term = _forward_term_structure([0.0, 1.0])
    result = _run_forward_only(
        cfg,
        macro=_macro_projection(periods=(1, 2), include_adverse=False),
        term=term,
    )

    observed = result.term_structure()
    assert observed is not None
    assert observed["hazard_stress"].tolist() == [0.0, 1.0]
    assert observed["pd_marginal_stress"].tolist() == [0.0, 1.0]
    assert observed["survival_stress"].tolist() == [1.0, 0.0]


def test_shock_cero_preserva_hazards_cercanos_a_fronteras() -> None:
    """Shock cero no clipea probabilidades válidas cerca de 0 ni de 1."""
    cfg = _cfg(
        metrics=("pd_marginal", "pd_cumulative"),
        scenario=_scenario(
            kind="custom",
            shock=StressShockConfig(factor="x", value=0.0),
        ),
    )
    near_zero = 1e-12
    near_one = 1.0 - 1e-12
    result = _run_forward_only(
        cfg,
        macro=_macro_projection(periods=(1, 2), include_adverse=False),
        term=_forward_term_structure([near_zero, near_one]),
    )

    observed = result.term_structure()
    assert observed is not None
    expected_survival_final = (1.0 - near_zero) * (1.0 - near_one)
    assert observed.loc[0, "hazard_stress"] == pytest.approx(near_zero, rel=0.0, abs=1e-18)
    assert observed.loc[1, "hazard_stress"] == pytest.approx(near_one, rel=0.0, abs=1e-18)
    assert observed.loc[0, "hazard_stress"] > 0.0
    assert observed.loc[1, "hazard_stress"] < 1.0
    assert observed.loc[0, "pd_marginal_stress"] == pytest.approx(
        near_zero,
        rel=0.0,
        abs=1e-18,
    )
    assert observed.loc[1, "survival_stress"] == pytest.approx(
        expected_survival_final,
        rel=0.0,
        abs=1e-18,
    )
    assert observed.loc[1, "pd_cumulative_stress"] < 1.0
    assert result.tidy()["absolute_delta"].abs().max() == pytest.approx(0.0, abs=1e-18)


def test_ecl_inputs_economicos_filtran_escenario_y_reconstruyen_pesos() -> None:
    """ECL compara el escenario forward base contra el stress equivalente, no todo forward."""
    term_parts: list[pd.DataFrame] = []
    for scenario_name, hazard, weight in (
        ("base", 0.01, 0.50),
        ("adverse", 0.015, 0.30),
        ("severe", 0.02, 0.20),
    ):
        part = _forward_term_structure([hazard])
        part.loc[:, "scenario"] = scenario_name
        part.loc[:, "scenario_weight"] = weight
        term_parts.append(part)
    term = pd.concat(term_parts, ignore_index=True)
    ecl_input = ForwardEclInput(
        term_structure_frame=term,
        scenario_weight_frame=pd.DataFrame(
            [
                {
                    "scenario": "base",
                    "weight": 0.50,
                    "is_default": False,
                    "source": "config",
                    "description": "base",
                },
                {
                    "scenario": "adverse",
                    "weight": 0.30,
                    "is_default": False,
                    "source": "config",
                    "description": "adverse",
                },
                {
                    "scenario": "severe",
                    "weight": 0.20,
                    "is_default": False,
                    "source": "config",
                    "description": "severe",
                },
            ],
            columns=_SCENARIO_WEIGHT_COLUMNS,
        ),
        pit_consistency={"basis": "pit"},
        contract_version=FORWARD_ECL_CONTRACT_VERSION,
    )
    ecl = CapturingEclStub()

    result = StressTestEngine.from_config(_cfg(metrics=("ecl",))).run(
        forward_ecl_input=ecl_input,
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=ecl,
    )

    assert ecl.calls[0]["scenario"].tolist() == ["severe"]
    assert ecl.calls[1]["scenario"].tolist() == ["severe_plus"]
    assert ecl.weight_calls[0]["scenario"].tolist() == ["severe"]
    assert ecl.weight_calls[1]["scenario"].tolist() == ["severe_plus"]
    assert ecl.calls[0]["scenario_weight"].tolist() == [1.0]
    assert ecl.calls[1]["scenario_weight"].tolist() == [1.0]
    assert ecl.weight_calls[0]["weight"].tolist() == [1.0]
    assert ecl.weight_calls[1]["weight"].tolist() == [1.0]
    ecl_row = result.tidy().iloc[0]
    assert ecl_row["value_base"] == pytest.approx(9.0, abs=1e-10)
    assert ecl_row["value_stress"] == pytest.approx(14.6484363909, abs=1e-10)
    assert ecl_row["absolute_delta"] == pytest.approx(5.6484363909, abs=1e-10)


def test_baseline_ecl_usa_orden_logico_estable_para_forward_permutado() -> None:
    """El baseline ECL recibe la misma canonicidad de filas que el stress term."""

    class OrderSensitiveEclStub:
        """Engine deliberadamente sensible al orden físico del term recibido."""

        def __init__(self) -> None:
            self.calls: list[pd.DataFrame] = []

        def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
            """Pondera por posición para detectar diferencias de orden no canónicas."""
            term = ecl_input.term_structure_frame
            assert term is not None
            self.calls.append(term[["period", "pd_marginal"]].copy(deep=True))
            total = math.fsum(
                (index + 1) * float(value)
                for index, value in enumerate(term["pd_marginal"].tolist())
            )
            return pd.DataFrame({"ecl": [total]})

    cfg = _cfg(
        metrics=("ecl",),
        scenario=_scenario(
            kind="custom",
            shock=StressShockConfig(factor="x", value=0.0),
        ),
    )
    macro = _macro_projection(periods=(1, 2), include_adverse=False)
    canonical = _forward_term_structure([0.02, 0.03])
    permuted = canonical.iloc[[1, 0]].copy(deep=True).reset_index(drop=True)

    def run_case(term: pd.DataFrame) -> tuple[pd.Series, list[int]]:
        ecl = OrderSensitiveEclStub()
        result = StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(term),
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=ecl,
        )
        return result.tidy().iloc[0], ecl.calls[0]["period"].astype(int).tolist()

    canonical_row, canonical_periods = run_case(canonical)
    permuted_row, permuted_periods = run_case(permuted)

    assert canonical_periods == [1, 2]
    assert permuted_periods == [1, 2]
    assert permuted_row["value_base"] == pytest.approx(canonical_row["value_base"], abs=1e-12)
    assert permuted_row["value_stress"] == pytest.approx(canonical_row["value_stress"], abs=1e-12)
    assert permuted_row["absolute_delta"] == pytest.approx(
        canonical_row["absolute_delta"],
        abs=1e-12,
    )


def test_ratio_economico_exige_salida_agregada_unica_por_periodo() -> None:
    """Ratio económico se compara por período, pero nunca se suma entre filas."""
    cfg = _cfg(metrics=("ratio",))
    term = _forward_term_structure([0.02])
    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=_ecl_input(term),
        macro_projection=_macro_projection(include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=RatioEclStub(),
    )

    row = result.tidy().iloc[0]
    assert row["metric"] == "ratio"
    assert row["value_base"] == pytest.approx(0.60)
    assert row["value_stress"] == pytest.approx(0.70)
    assert row["absolute_delta"] == pytest.approx(0.10)

    with pytest.raises(StressOutputError, match="ratio exige una salida ya agregada"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(term),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=MultiRowRatioEclStub(),
        )


def test_recomposicion_lifetime_identidad_shock_cero() -> None:
    """Shock cero conserva la identidad lifetime de hazards 0.10/0.20."""
    cfg = _cfg(
        metrics=("pd_marginal", "pd_cumulative"),
        scenario=_scenario(
            kind="custom",
            shock=StressShockConfig(factor="x", value=0.0),
        ),
    )
    result = _run_forward_only(
        cfg,
        macro=_macro_projection(periods=(1, 2), include_adverse=False),
        term=_forward_term_structure([0.10, 0.20]),
    )

    term = result.term_structure()
    assert term is not None
    assert term.loc[0, "survival_stress"] == pytest.approx(0.90, abs=1e-12)
    assert term.loc[0, "pd_marginal_stress"] == pytest.approx(0.10, abs=1e-12)
    assert term.loc[1, "survival_stress"] == pytest.approx(0.72, abs=1e-12)
    assert term.loc[1, "pd_marginal_stress"] == pytest.approx(0.18, abs=1e-12)
    assert term.loc[1, "pd_cumulative_stress"] == pytest.approx(0.28, abs=1e-12)
    assert set(result.tidy()["engine_source"]) == {"forward_only"}


@pytest.mark.parametrize(
    ("column", "bad_value", "match"),
    [
        ("survival", 0.73, r"survival_t"),
        ("pd_marginal", 0.19, r"pd_marginal_t"),
        ("pd_cumulative", 0.27, r"pd_cumulative_t"),
    ],
)
def test_forward_term_structure_rechaza_lifetime_incoherente_antes_de_stress(
    column: str,
    bad_value: float,
    match: str,
) -> None:
    """El input forward debe traer curvas lifetime coherentes antes del stress."""
    term = _forward_term_structure([0.10, 0.20])
    term.loc[1, column] = bad_value

    with pytest.raises(StressInputError, match=match):
        _run_forward_only(
            _cfg(metrics=("pd_marginal",)),
            macro=_macro_projection(periods=(1, 2), include_adverse=False),
            term=term,
        )


@pytest.mark.parametrize(
    ("periods", "match"),
    [
        ([2], r"esperado=1, observado=2"),
        ([1, 3], r"esperado=2, observado=3"),
    ],
)
def test_forward_term_structure_rechaza_periodos_lifetime_no_contiguos(
    periods: list[int],
    match: str,
) -> None:
    """Cada curva lifetime debe partir en 1 y no saltarse períodos."""
    term = _forward_term_structure([0.10 for _ in periods])
    term.loc[:, "period"] = periods
    term.loc[:, "time_value"] = [float(period) for period in periods]

    with pytest.raises(StressInputError, match=match):
        _run_forward_only(
            _cfg(metrics=("pd_marginal",)),
            macro=_macro_projection(periods=tuple(periods), include_adverse=False),
            term=term,
        )


def test_term_structure_separa_curvas_por_method_y_pd_source() -> None:
    """Curvas forward con mismo source_model no comparten supervivencia entre métodos."""
    cfg = _cfg(
        metrics=("pd_marginal",),
        scenario=_scenario(
            kind="custom",
            shock=StressShockConfig(factor="x", value=0.0),
        ),
    )
    survival_curve = _forward_term_structure([0.10, 0.20])
    markov_curve = _forward_term_structure([0.30, 0.40])
    markov_curve.loc[:, "method"] = "markov"
    markov_curve.loc[:, "pd_source"] = "markov"
    term = pd.concat([survival_curve, markov_curve], ignore_index=True)
    term_permuted = pd.concat([markov_curve, survival_curve], ignore_index=True)

    result = _run_forward_only(
        cfg,
        macro=_macro_projection(periods=(1, 2), include_adverse=False),
        term=term,
    )
    result_permuted = _run_forward_only(
        cfg,
        macro=_macro_projection(periods=(1, 2), include_adverse=False),
        term=term_permuted,
    )

    observed = result.term_structure()
    observed_permuted = result_permuted.term_structure()
    assert observed is not None
    assert observed_permuted is not None
    assert_frame_equal(observed, observed_permuted)
    assert len(observed.index) == 4
    assert set(observed["source_model"].tolist()) == {"survival"}
    assert set(observed["method"].tolist()) == {"survival", "markov"}
    assert set(observed["pd_source"].tolist()) == {"survival", "markov"}
    survival_second = observed.loc[observed["hazard_base"] == 0.20].iloc[0]
    markov_second = observed.loc[observed["hazard_base"] == 0.40].iloc[0]
    assert survival_second["survival_stress"] == pytest.approx(0.72, abs=1e-12)
    assert markov_second["survival_stress"] == pytest.approx(0.42, abs=1e-12)


def test_forward_only_impactos_separan_segmentos_sin_promediar() -> None:
    """Impactos forward-only publican un grupo canónico por segmento/grano."""
    cfg = _cfg(
        metrics=("pd_marginal",),
        scenario=_scenario(
            kind="custom",
            shock=StressShockConfig(factor="x", value=0.0),
        ),
    )
    retail = _forward_term_structure([0.10])
    retail.loc[:, "row_id"] = "retail-1"
    retail.loc[:, "segment"] = "retail"
    pyme = _forward_term_structure([0.30])
    pyme.loc[:, "row_id"] = "pyme-1"
    pyme.loc[:, "segment"] = "pyme"
    term = pd.concat([retail, pyme], ignore_index=True)

    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=_ecl_input(term),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=PortfolioSatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
    )

    impacts = result.tidy().sort_values("value_base").reset_index(drop=True)
    assert impacts["value_base"].tolist() == pytest.approx([0.10, 0.30], abs=1e-12)
    assert impacts["value_stress"].tolist() == pytest.approx([0.10, 0.30], abs=1e-12)
    groups = [json.loads(value) for value in impacts["group_key"].tolist()]
    assert [group["segment"] for group in groups] == ["retail", "pyme"]
    assert [group["row_id"] for group in groups] == ["retail-1", "pyme-1"]
    assert {group["partition"] for group in groups} == {"desarrollo"}


def test_forward_only_impactos_separan_row_id_int_y_texto() -> None:
    """``group_key`` conserva tipo para no mezclar ``1`` con ``"1"``."""
    cfg = _cfg(
        metrics=("pd_marginal",),
        scenario=_scenario(
            kind="custom",
            shock=StressShockConfig(factor="x", value=0.0),
        ),
    )
    numeric_id = _forward_term_structure([0.10])
    numeric_id.loc[:, "row_id"] = 1
    text_id = _forward_term_structure([0.30])
    text_id.loc[:, "row_id"] = "1"
    term = pd.concat([numeric_id, text_id], ignore_index=True)

    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=_ecl_input(term),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=PortfolioSatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
    )

    impacts = result.tidy().sort_values("value_base").reset_index(drop=True)
    assert impacts["value_base"].tolist() == pytest.approx([0.10, 0.30], abs=1e-12)
    groups = [json.loads(value) for value in impacts["group_key"].tolist()]
    assert [group["row_id"] for group in groups] == [1, "1"]


def test_term_structure_orden_tipado_estable_con_row_id_int_y_texto() -> None:
    """El orden publicado no depende del orden físico cuando ``1`` y ``"1"`` coexisten."""
    cfg = _cfg(metrics=("pd_marginal",))
    numeric_id = _forward_term_structure([0.10])
    numeric_id.loc[:, "row_id"] = 1
    text_id = _forward_term_structure([0.30])
    text_id.loc[:, "row_id"] = "1"
    term_a = pd.concat([numeric_id, text_id], ignore_index=True)
    term_b = pd.concat([text_id, numeric_id], ignore_index=True)

    engine_a = StressTestEngine.from_config(cfg)
    result_a = engine_a.run(
        forward_ecl_input=_ecl_input(term_a),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=PortfolioSatelliteStub(),
        forward_term_structure=term_a,
        scenario_weighting=ScenarioWeightingStub(),
    )
    engine_b = StressTestEngine.from_config(cfg)
    result_b = engine_b.run(
        forward_ecl_input=_ecl_input(term_b),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=PortfolioSatelliteStub(),
        forward_term_structure=term_b,
        scenario_weighting=ScenarioWeightingStub(),
    )

    assert engine_a.forward_hash_ == engine_b.forward_hash_
    published_a = result_a.term_structure()
    published_b = result_b.term_structure()
    assert published_a is not None
    assert published_b is not None
    assert published_a["row_id"].tolist() == published_b["row_id"].tolist() == ["1", 1]
    assert published_a["pd_marginal_stress"].tolist() == pytest.approx([0.30, 0.10], abs=1e-12)
    assert published_b["pd_marginal_stress"].tolist() == pytest.approx([0.30, 0.10], abs=1e-12)


def test_forward_only_impactos_separan_survival_y_markov() -> None:
    """Impactos forward-only no mezclan curvas survival y markov del mismo período."""
    cfg = _cfg(
        metrics=("pd_marginal",),
        scenario=_scenario(
            kind="custom",
            shock=StressShockConfig(factor="x", value=0.0),
        ),
    )
    survival = _forward_term_structure([0.10])
    survival.loc[:, "row_id"] = "cliente-1"
    survival.loc[:, "source_model"] = "survival"
    survival.loc[:, "method"] = "survival"
    survival.loc[:, "pd_source"] = "survival"
    markov = _forward_term_structure([0.40])
    markov.loc[:, "row_id"] = "cliente-1"
    markov.loc[:, "source_model"] = "markov"
    markov.loc[:, "method"] = "markov"
    markov.loc[:, "pd_source"] = "markov"
    term = pd.concat([survival, markov], ignore_index=True)

    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=_ecl_input(term),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=PortfolioSatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
    )

    impacts = result.tidy().sort_values("value_base").reset_index(drop=True)
    assert impacts["value_base"].tolist() == pytest.approx([0.10, 0.40], abs=1e-12)
    groups = [json.loads(value) for value in impacts["group_key"].tolist()]
    assert [group["source_model"] for group in groups] == ["survival", "markov"]
    assert [group["method"] for group in groups] == ["survival", "markov"]
    assert [group["pd_source"] for group in groups] == ["survival", "markov"]


def test_forward_only_no_exige_ecl_engine_y_relative_operation_construct() -> None:
    """PD forward-only funciona sin ECL y relative aplica x*(1+severity*delta)."""
    result = _run_forward_only(
        _relative_cfg(),
        macro=_macro_projection(periods=(1,), severe={1: 2.0}, include_adverse=False),
        term=_forward_term_structure([0.02]),
    )

    macro_frame = result.scenario_results[0].stressed_macro_frame
    assert tuple(macro_frame.columns) == _MACRO_PROJECTION_COLUMNS
    assert macro_frame.loc[0, "scenario"] == "relative_plus"
    assert macro_frame.loc[0, "projected_value"] == pytest.approx(3.0)
    assert macro_frame.loc[0, "shock_value"] == pytest.approx(3.0)
    # x severo base=2.0; relative +50% produce delta incremental 1.0 y beta=0.5.
    assert result.term_structure().loc[0, "hazard_stress"] == pytest.approx(
        0.0325520809,
        abs=1e-10,
    )
    assert set(result.tidy()["engine_source"]) == {"forward_only"}


def test_basis_blended_aplica_stress_y_ttc_preserva_curva_forward() -> None:
    """Stress respeta metadata PIT/TTC: blended se estresa y TTC no recibe shock satelital."""
    cfg = _cfg(metrics=("pd_marginal", "lgd"))
    weights = _ecl_input(_forward_term_structure([0.02])).scenario_weight_frame

    blended = _forward_term_structure([0.02])
    blended.loc[0, "basis_state"] = "blended"
    blended_result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=CompatibleForwardInput(
            term_structure_frame=blended,
            scenario_weight_frame=weights,
        ),
        macro_projection=_macro_projection(include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=blended,
        scenario_weighting=ScenarioWeightingStub(),
    )
    blended_term = blended_result.term_structure()
    assert blended_term is not None
    assert blended_term.loc[0, "basis_state"] == "blended"
    assert blended_term.loc[0, "pd_basis"] == "pit"
    assert blended_term.loc[0, "hazard_stress"] > blended_term.loc[0, "hazard_base"]

    ttc = _forward_term_structure([0.02])
    ttc.loc[0, "pd_basis"] = "pit"
    ttc.loc[0, "basis_state"] = "ttc"
    ttc.loc[0, "ttc_reversion_weight"] = 0.0
    ttc_result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=CompatibleForwardInput(
            term_structure_frame=ttc,
            scenario_weight_frame=weights,
        ),
        macro_projection=_macro_projection(include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=ttc,
        scenario_weighting=ScenarioWeightingStub(),
    )
    ttc_term = ttc_result.term_structure()
    assert ttc_term is not None
    assert ttc_term.loc[0, "pd_basis"] == "pit"
    assert ttc_term.loc[0, "basis_state"] == "ttc"
    assert ttc_term.loc[0, "hazard_stress"] == pytest.approx(ttc_term.loc[0, "hazard_base"])
    assert ttc_term.loc[0, "pd_marginal_stress"] == pytest.approx(
        ttc_term.loc[0, "pd_marginal_base"]
    )
    assert ttc_term.loc[0, "lgd_stress"] == pytest.approx(ttc_term.loc[0, "lgd_base"])
    assert ttc_term.loc[0, "satellite_adjustment_stress"] == pytest.approx(
        ttc_term.loc[0, "satellite_adjustment_base"]
    )


@pytest.mark.parametrize("base_value", [0.0, -1.0])
def test_relative_operation_rechaza_base_cero_o_negativa(base_value: float) -> None:
    """Shocks relativos solo se aplican sobre factores base estrictamente positivos."""
    with pytest.raises(StressScenarioError, match="base positivo"):
        _run_forward_only(
            _relative_cfg(),
            macro=_macro_projection(periods=(1,), severe={1: base_value}, include_adverse=False),
            term=_forward_term_structure([0.02]),
        )


def test_periodos_macro_string_decimal_se_normalizan_al_aplicar_shocks() -> None:
    """Los períodos enteros serializados como ``"1.0"`` no rompen el filtrado de shocks."""
    cfg = _cfg(metrics=("pd_marginal",))
    macro = _macro_projection(periods=(1,), include_adverse=False)
    macro = macro.assign(period=macro["period"].astype(float).astype(str))

    result = _run_forward_only(cfg, macro=macro, term=_forward_term_structure([0.02]))

    row = result.scenario_results[0].stressed_macro_frame.iloc[0]
    assert row["period"] == 1
    assert row["projected_value"] == pytest.approx(1.0)
    assert row["shock_value"] == pytest.approx(1.0)
    assert result.tidy().iloc[0]["value_stress"] == pytest.approx(0.0325520809, abs=1e-10)


def test_macro_projection_residual_metric_tol_publica_delta_efectivo() -> None:
    """Una identidad macro válida dentro de tolerancia se publica como identidad exacta."""
    cfg = _cfg(
        metrics=("pd_marginal",),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
            metric_tol=1e-8,
        ),
    )
    macro = _macro_projection(periods=(1,), include_adverse=False)
    macro.loc[:, "projected_value"] = (
        macro["model_value"].astype(float) + macro["shock_value"].astype(float) + 5e-9
    )

    result = _run_forward_only(cfg, macro=macro, term=_forward_term_structure([0.02]))

    row = result.scenario_results[0].stressed_macro_frame.iloc[0]
    assert row["shock_value"] == pytest.approx(row["projected_value"] - row["model_value"])
    assert result.tidy().iloc[0]["value_stress"] > result.tidy().iloc[0]["value_base"]


def test_stressed_macro_projection_preserva_columnas_y_variables_no_shockeadas() -> None:
    """La macro publicada conserva contrato forward y variables no shockeadas."""
    cfg = _cfg(metrics=("pd_marginal",))
    macro_x = _macro_projection(periods=(1,), include_adverse=False)
    macro_z = macro_x.copy(deep=True)
    macro_z.loc[:, "macro_variable"] = "z"
    macro_z.loc[:, "model_value"] = 2.0
    macro_z.loc[:, "projected_value"] = 2.0
    macro = pd.concat([macro_x, macro_z], ignore_index=False)

    result = _run_forward_only(cfg, macro=macro, term=_forward_term_structure([0.02]))

    macro_frame = result.scenario_results[0].stressed_macro_frame
    assert tuple(macro_frame.columns) == _MACRO_PROJECTION_COLUMNS
    assert macro_frame["scenario"].tolist() == ["severe_plus", "severe_plus"]
    assert macro_frame["period"].tolist() == [1, 1]
    assert macro_frame["macro_variable"].tolist() == ["x", "z"]
    observed_by_variable = macro_frame.set_index("macro_variable")
    assert observed_by_variable.loc["x", "projected_value"] == pytest.approx(1.0)
    assert observed_by_variable.loc["x", "shock_value"] == pytest.approx(1.0)
    assert observed_by_variable.loc["z", "projected_value"] == pytest.approx(2.0)
    assert observed_by_variable.loc["z", "shock_value"] == pytest.approx(0.0)
    assert result.tidy().iloc[0]["value_stress"] == pytest.approx(0.0325520809, abs=1e-10)


def test_stressed_macro_projection_reordena_y_descarta_columnas_diagnosticas() -> None:
    """La macro estresada siempre publica columnas canónicas aunque el input traiga extras."""
    cfg = _cfg(metrics=("pd_marginal",))
    macro = _macro_projection(periods=(1,), include_adverse=False)
    macro.loc[:, "diagnostic_note"] = "debug"
    macro = macro.loc[:, ["diagnostic_note", *reversed(_MACRO_PROJECTION_COLUMNS)]]
    macro_before = macro.copy(deep=True)

    result = _run_forward_only(cfg, macro=macro, term=_forward_term_structure([0.02]))

    assert_frame_equal(macro, macro_before)
    macro_frame = result.scenario_results[0].stressed_macro_frame
    assert tuple(macro_frame.columns) == _MACRO_PROJECTION_COLUMNS
    assert "diagnostic_note" not in macro_frame.columns
    assert macro_frame.loc[0, "scenario"] == "severe_plus"
    assert macro_frame.loc[0, "macro_variable"] == "x"
    assert macro_frame.loc[0, "projected_value"] == pytest.approx(1.0)
    assert macro_frame.loc[0, "shock_value"] == pytest.approx(1.0)


def test_macro_projection_entera_y_categoria_no_emiten_warning_al_aplicar_shock() -> None:
    """Columnas int/categorical se castean antes de asignar escenario y shocks float."""
    cfg = _cfg(
        metrics=("pd_marginal",),
        shock=StressShockConfig(factor="x", value=0.5),
    )
    macro = pd.DataFrame(
        [
            {
                "scenario": "severe",
                "scenario_weight": 1,
                "period": 1,
                "time_value": 1,
                "macro_variable": "x",
                "projected_value": 0,
                "model_value": 0,
                "shock_value": 0,
                "method": "test",
                "model_id": "macro:test",
                "is_reasonable_supportable": True,
                "warning_codes": (),
            }
        ]
    )
    macro["scenario"] = macro["scenario"].astype("category")

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        result = _run_forward_only(cfg, macro=macro, term=_forward_term_structure([0.02]))

    assert result.scenario_results[0].stressed_macro_frame.loc[0, "projected_value"] == 0.5
    assert result.tidy().iloc[0]["value_stress"] > result.tidy().iloc[0]["value_base"]


def test_warning_codes_forward_y_macro_se_propagan_a_diagnosticos_e_impactos() -> None:
    """Warnings heredados de forward/macro no se pierden al publicar impactos."""
    cfg = _cfg(metrics=("pd_marginal",))
    macro = _macro_projection(include_adverse=False)
    macro.loc[0, "warning_codes"] = ("MACRO-WARN",)
    term = _forward_term_structure([0.02])
    term.loc[0, "warning_codes"] = ("FWD-WARN",)

    result = _run_forward_only(cfg, macro=macro, term=term)

    assert result.scenario_results[0].warning_codes == ("MACRO-WARN", "FWD-WARN")
    assert result.diagnostics.warning_codes == ("MACRO-WARN", "FWD-WARN")
    assert result.tidy().iloc[0]["warning_codes"] == ("MACRO-WARN", "FWD-WARN")
    assert result.term_structure().loc[0, "warning_codes"] == ("FWD-WARN", "MACRO-WARN")


def test_ecl_y_provision_requieren_engines_y_no_publican_ceros_silenciosos() -> None:
    """Métricas económicas fallan sin engine y calculan provisión si ambos engines existen."""

    class LgdStressSatellite:
        coefficients_: ClassVar[dict[str, dict[str, dict[str, object]]]] = {
            "pd": {"retail": {"factors": {"x": 0.0}}},
            "lgd": {"retail": {"factors": {"x": 0.2}}},
        }

    missing_cfg = _cfg(
        metrics=("ecl",),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    with pytest.raises(StressDependencyError, match="ECL engine"):
        _run_forward_only(missing_cfg)

    provision_cfg = _cfg(metrics=("provision",))
    result = StressTestEngine.from_config(provision_cfg).run(
        forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=_forward_term_structure([0.02]),
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=EclStub(),
        provision_engine=ProvisionStub(),
    )
    provision = result.tidy().iloc[0]
    assert provision["metric"] == "provision"
    assert provision["engine_source"] == "provision_engine"
    assert provision["value_base"] == pytest.approx(9.9, abs=1e-10)
    assert provision["value_stress"] == pytest.approx(16.11328003, abs=1e-8)
    assert isinstance(EclStub(), EclEngineLike)
    assert isinstance(ProvisionStub(), ProvisionEngineLike)

    ecl = EclStub()
    StressTestEngine.from_config(_cfg(metrics=("ecl",))).run(
        forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=LgdStressSatellite(),
        forward_term_structure=_forward_term_structure([0.02]),
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=ecl,
    )
    assert ecl.calls[1].loc[0, "lgd"] == pytest.approx(0.4998323261407476, abs=1e-12)
    assert ecl.calls[1].loc[0, "lgd_base"] == pytest.approx(0.45, abs=1e-12)

    missing_lgd_term = _forward_term_structure([0.02]).drop(columns=["lgd"])
    ecl_missing_lgd = EclStub()
    missing_lgd_result = StressTestEngine.from_config(_cfg(metrics=("ecl",))).run(
        forward_ecl_input=_ecl_input(missing_lgd_term),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=LgdStressSatellite(),
        forward_term_structure=missing_lgd_term,
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=ecl_missing_lgd,
    )
    assert "lgd" not in missing_lgd_term.columns
    assert ecl_missing_lgd.calls[1].loc[0, "lgd"] == pytest.approx(
        0.4998323261407476,
        abs=1e-12,
    )
    assert ecl_missing_lgd.calls[1].loc[0, "lgd_base"] == pytest.approx(0.45, abs=1e-12)
    ecl_impact = missing_lgd_result.tidy().iloc[0]
    assert ecl_impact["value_stress"] == pytest.approx(9.9966465228, abs=1e-10)


def test_impactos_economicos_preservan_grupos_publicados_por_engine() -> None:
    """ECL/provisión no deben compensar segmentos publicados por el engine económico."""

    class GroupedEclStub:
        """Engine ECL que conserva la dimensión ``segment`` en su salida."""

        def calculate(self, ecl_input: ForwardEclInput) -> pd.DataFrame:
            """Calcula ECL por período y segmento desde el contrato forward."""
            term = ecl_input.term_structure_frame
            assert term is not None
            return pd.DataFrame(
                {
                    "period": term["period"].tolist(),
                    "segment": term["segment"].tolist(),
                    "pd_marginal": term["pd_marginal"].astype(float).tolist(),
                    "lgd": term["lgd"].astype(float).tolist(),
                    "ead": [1000.0] * len(term.index),
                    "ecl": term["pd_marginal"].astype(float) * 1000.0,
                }
            )

    retail = _forward_term_structure([0.02])
    retail.loc[:, "segment"] = "retail"
    pyme = _forward_term_structure([0.04])
    pyme.loc[:, "segment"] = "pyme"
    term = pd.concat([retail, pyme], ignore_index=True)

    result = StressTestEngine.from_config(_cfg(metrics=("ecl",))).run(
        forward_ecl_input=_ecl_input(term),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=PortfolioSatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=GroupedEclStub(),
    )

    impact = result.tidy().sort_values("group_key").reset_index(drop=True)
    groups = [json.loads(value) for value in impact["group_key"].tolist()]
    assert [group["segment"] for group in groups] == ["pyme", "retail"]
    assert all(set(group) == {"segment"} for group in groups)
    assert impact["value_base"].tolist() == pytest.approx([40.0, 20.0], abs=1e-12)
    assert len(impact.index) == 2


def test_engine_economico_rechaza_columnas_duplicadas_antes_de_resolver_metricas() -> None:
    """ECL/provisión duplicados fallan con ``StressOutputError`` propio."""
    with pytest.raises(StressOutputError, match=r"ecl_base.*columnas duplicadas.*ecl"):
        StressTestEngine.from_config(_cfg(metrics=("ecl",))).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(periods=(1,), include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=DuplicateMetricEclStub(),
        )

    with pytest.raises(StressOutputError, match=r"provision_base.*columnas duplicadas.*provision"):
        StressTestEngine.from_config(_cfg(metrics=("provision",))).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(periods=(1,), include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=EclStub(),
            provision_engine=DuplicateMetricProvisionStub(),
        )


def test_lgd_solicitado_sin_datos_falla_o_emite_falta_dato() -> None:
    """LGD pedido no puede desaparecer del impacto sin señal FALTA-DATO."""
    term = _forward_term_structure([0.02])
    term = term.astype({"lgd": "object", "lgd_base": "object"})
    term.loc[:, "lgd"] = None
    term.loc[:, "lgd_base"] = None
    relaxed_cfg = _cfg(
        metrics=("lgd",),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    relaxed_audit = InMemoryAuditSink()
    relaxed_result = _run_forward_only(relaxed_cfg, term=term, audit=relaxed_audit)

    assert relaxed_result.tidy().empty
    assert relaxed_result.diagnostics.falta_dato_codes == ("FALTA-DATO-STR-LGD",)
    falta_event = next(
        event.payload
        for event in relaxed_audit.events
        if event.payload["regla"] == "stress_falta_dato"
    )
    assert falta_event["accion"] == "warn"
    assert falta_event["valor"]["reason"] == "missing_lgd_metric_inputs"
    assert falta_event["valor"]["source"] == "forward_term_structure"

    strict_cfg = _cfg(
        metrics=("lgd",),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=True,
            fail_on_missing_ecl_engine=True,
        ),
    )
    with pytest.raises(StressFaltaDatoError, match="FALTA-DATO-STR-LGD"):
        _run_forward_only(strict_cfg, term=term)


def test_forward_only_permite_lgd_faltante_cuando_no_se_solicita() -> None:
    """LGD es opcional: métricas PD no deben bloquearse por columnas LGD ausentes."""
    term = _forward_term_structure([0.02]).drop(columns=["lgd", "lgd_base"])

    result = _run_forward_only(_cfg(metrics=("pd_marginal",)), term=term)

    assert result.diagnostics.falta_dato_codes == ()
    impact = result.tidy()
    assert impact["metric"].tolist() == ["pd_marginal"]
    observed_term = result.term_structure()
    assert observed_term is not None
    assert observed_term.loc[0, "lgd_base"] is None
    assert observed_term.loc[0, "lgd_stress"] is None


def test_lgd_solicitado_con_columnas_faltantes_emite_falta_dato() -> None:
    """Ausencia estructural de LGD sigue el mismo contrato FALTA-DATO que valores vacíos."""
    term = _forward_term_structure([0.02]).drop(columns=["lgd", "lgd_base"])
    cfg = _cfg(
        metrics=("lgd",),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )

    result = _run_forward_only(cfg, term=term)

    assert result.tidy().empty
    assert result.diagnostics.falta_dato_codes == ("FALTA-DATO-STR-LGD",)


def test_impactos_economicos_publican_periodos_string_como_enteros() -> None:
    """ECL puede preservar períodos string, pero stress publica horizonte numérico estable."""
    cfg = _cfg(metrics=("ecl",))
    macro = _macro_projection(periods=(1, 2, 3), include_adverse=False)
    macro = macro.assign(period=macro["period"].astype(str))
    term = _forward_term_structure([0.02, 0.03, 0.04])
    term = term.assign(period=term["period"].astype(str))
    ecl = EclStub()

    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=_ecl_input(term),
        macro_projection=macro,
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=ecl,
    )

    assert ecl.calls[0]["period"].tolist() == [1, 2, 3]
    assert ecl.calls[1]["period"].tolist() == [1, 2, 3]
    assert result.tidy()["period"].tolist() == [1, 2, 3]


def test_dominancia_adverse_y_falta_dato_segun_config() -> None:
    """Dominancia falla si stress < adverse y FALTA-DATO se registra o levanta."""
    strong = _cfg(
        shock=StressShockConfig(factor="x", value=2.0),
        require_dominates=True,
        metrics=("pd_marginal",),
    )
    strong_macro = _macro_projection(periods=(1,), adverse={1: 1.0}, severe={1: 0.0})
    strong_macro = strong_macro.assign(period=strong_macro["period"].astype(float).astype(str))
    strong_result = _run_forward_only(strong, macro=strong_macro)
    assert strong_result.diagnostics.falta_dato_codes == ()

    weak = _cfg(
        shock=StressShockConfig(factor="x", value=0.5),
        require_dominates=True,
        metrics=("pd_marginal",),
    )
    with pytest.raises(StressScenarioError, match="no domina adverse"):
        _run_forward_only(
            weak,
            macro=_macro_projection(periods=(1,), adverse={1: 1.0}, severe={1: 0.0}),
        )

    opposite_sign = _cfg(
        shock=StressShockConfig(factor="x", value=-2.0),
        require_dominates=True,
        metrics=("pd_marginal",),
    )
    with pytest.raises(StressScenarioError, match="no domina adverse"):
        _run_forward_only(
            opposite_sign,
            macro=_macro_projection(periods=(1,), adverse={1: 1.0}, severe={1: 0.0}),
        )

    with pytest.raises(StressScenarioError, match="no domina adverse"):
        _run_forward_only(
            weak,
            macro=_macro_projection(periods=(1,), adverse={1: 2.0}, severe={1: 0.0}),
        )

    adverse_path = _macro_projection(periods=(1,), adverse={1: 5.0}, severe={1: 0.0})
    adverse_path.loc[adverse_path["scenario"] == "adverse", "model_value"] = 5.0
    adverse_path.loc[adverse_path["scenario"] == "adverse", "shock_value"] = 0.0
    base_row = adverse_path[adverse_path["scenario"] == "severe"].copy(deep=True)
    base_row.loc[:, "scenario"] = "base"
    adverse_path = pd.concat([base_row, adverse_path], ignore_index=True)
    with pytest.raises(StressScenarioError, match="no domina adverse"):
        _run_forward_only(
            strong,
            macro=adverse_path,
        )

    inconsistent_adverse = _macro_projection(periods=(1,), adverse={1: 2.0}, severe={1: 0.0})
    inconsistent_adverse.loc[inconsistent_adverse["scenario"] == "adverse", "shock_value"] = 0.25
    engine = StressTestEngine.from_config(
        _cfg(
            shock=StressShockConfig(factor="x", value=1.0),
            require_dominates=True,
            metrics=("pd_marginal",),
        )
    )
    term = _forward_term_structure([0.02])
    with pytest.raises(StressInputError, match="identidad macro inconsistente"):
        engine.run(
            forward_ecl_input=_ecl_input(term),
            macro_projection=inconsistent_adverse,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
        )
    assert engine.run_started_at_ is None
    assert engine.forward_hash_ is None

    tolerant_cfg = _cfg(
        shock=StressShockConfig(factor="x", value=2.0),
        require_dominates=True,
        metrics=("pd_marginal",),
        validation=StressValidationConfig(
            metric_tol=1e-4,
            require_dominates_forward_adverse=True,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    tolerant_macro = _macro_projection(periods=(1,), adverse={1: 1.0}, severe={1: 0.0})
    tolerant_macro.loc[
        tolerant_macro["scenario"] == "adverse",
        "projected_value",
    ] = 1.0 + 5e-5
    tolerant_audit = InMemoryAuditSink()
    tolerant_result = _run_forward_only(tolerant_cfg, macro=tolerant_macro, audit=tolerant_audit)
    assert tolerant_result.diagnostics.falta_dato_codes == ()
    tolerance_event = next(
        event.payload
        for event in tolerant_audit.events
        if event.payload["regla"] == "stress_dominance_check" and event.payload["accion"] == "pass"
    )
    assert tolerance_event["valor"]["checks"][0]["adverse_delta"] == pytest.approx(1.0 + 5e-5)

    intolerant_macro = _macro_projection(periods=(1,), adverse={1: 1.0}, severe={1: 0.0})
    intolerant_macro.loc[
        intolerant_macro["scenario"] == "adverse",
        "projected_value",
    ] = 1.0 + 5e-4
    with pytest.raises(StressInputError, match="identidad macro inconsistente"):
        _run_forward_only(tolerant_cfg, macro=intolerant_macro)

    missing_adverse = _cfg(
        require_dominates=True,
        metrics=("pd_marginal",),
    )
    missing_audit = InMemoryAuditSink()
    result = _run_forward_only(
        missing_adverse,
        macro=_macro_projection(periods=(1,), include_adverse=False),
        audit=missing_audit,
    )
    assert result.diagnostics.falta_dato_codes == ("FALTA-DATO-STR-1",)
    assert result.scenario_results[0].warning_codes == ("FALTA-DATO-STR-1",)
    missing_events = [event.payload for event in missing_audit.events]
    dominance_event = next(
        payload for payload in missing_events if payload["regla"] == "stress_dominance_check"
    )
    assert dominance_event["accion"] == "falta_dato"
    assert dominance_event["valor"]["checks"][0]["result"] == "missing_adverse"
    falta_event = next(
        payload for payload in missing_events if payload["regla"] == "stress_falta_dato"
    )
    assert falta_event["valor"]["reason"] == "missing_forward_adverse_delta"
    assert falta_event["umbral"] == {"code": "FALTA-DATO-STR-1", "blocked": False}

    strict_cfg = StressConfig(
        scenarios=(_scenario(require_dominates=True),),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=StressValidationConfig(),
    )
    strict_audit = InMemoryAuditSink()
    with pytest.raises(StressFaltaDatoError, match="FALTA-DATO-STR-1"):
        _run_forward_only(
            strict_cfg,
            macro=_macro_projection(periods=(1,), include_adverse=False),
            audit=strict_audit,
        )
    strict_falta = next(
        event.payload
        for event in strict_audit.events
        if event.payload["regla"] == "stress_falta_dato"
    )
    assert strict_falta["accion"] == "block"
    assert strict_falta["umbral"] == {"code": "FALTA-DATO-STR-1", "blocked": True}


def test_dominancia_default_estricta_corre_con_adverse_comparable() -> None:
    """Defaults estrictos validan dominancia en runtime sin bypass de config."""
    cfg = StressConfig(
        scenarios=(
            StressScenarioConfig(
                name="severe_plus",
                shocks=(StressShockConfig(factor="x", value=2.0),),
            ),
        ),
        output=StressOutputConfig(metrics=("pd_marginal",)),
    )

    result = _run_forward_only(
        cfg,
        macro=_macro_projection(periods=(1,), adverse={1: 1.0}, severe={1: 0.0}),
    )

    assert result.diagnostics.falta_dato_codes == ()
    assert result.scenario_results[0].warning_codes == ()


def test_dominancia_relative_compara_delta_efectivo_por_periodo() -> None:
    """Dominancia relative usa x_base * shock relativo, no solo la magnitud declarada."""
    relative_cfg = _relative_cfg(require_dominates=True)
    result = _run_forward_only(
        relative_cfg,
        macro=_macro_projection(periods=(1,), adverse={1: 0.75}, severe={1: 2.0}),
    )
    assert result.diagnostics.falta_dato_codes == ()

    with pytest.raises(StressScenarioError, match="no domina adverse"):
        _run_forward_only(
            relative_cfg,
            macro=_macro_projection(periods=(1,), adverse={1: 1.25}, severe={1: 2.0}),
        )

    with pytest.raises(StressScenarioError, match="base positivo"):
        _run_forward_only(
            relative_cfg,
            macro=_macro_projection(periods=(1,), adverse={1: 0.10}, severe={1: 0.0}),
        )


def test_delta_de_dominancia_rechaza_operacion_invalida_construct() -> None:
    """La ruta interna de dominancia rechaza operaciones fuera del contrato."""
    shock = StressShockConfig.model_construct(
        factor="x",
        operation="multiplicative",
        value=1.0,
        unit=None,
        periods="all",
        source="user",
        description=None,
    )
    scenario = StressScenarioConfig.model_construct(
        name="invalid_operation",
        kind="severe",
        base_forward_scenario="severe",
        severity=1.0,
        shocks=(shock,),
        weight=None,
        require_dominates_forward_adverse=True,
        description=None,
    )

    with pytest.raises(StressScenarioError, match="Operación de shock no soportada"):
        engine_module._stress_delta_for_dominance(
            scenario,
            shock,
            severity=1.0,
            period=1,
            macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        )


def test_delta_de_dominancia_relative_exige_fila_base_unica() -> None:
    """Dominancia relative falla si la base no es única por escenario/factor/período."""
    relative_cfg = _relative_cfg(require_dominates=True)
    scenario = relative_cfg.scenarios[0]
    shock = scenario.shocks[0]
    macro = pd.concat(
        [
            _macro_projection(periods=(1,), severe={1: 2.0}),
            _macro_projection(periods=(1,), severe={1: 3.0}, include_adverse=False),
        ],
        ignore_index=True,
    )

    with pytest.raises(StressScenarioError, match="fila base única"):
        engine_module._stress_delta_for_dominance(
            scenario,
            shock,
            severity=scenario.severity,
            period=1,
            macro_projection=macro,
        )


def test_periodos_declarados_y_sigmoid_eta_positivo() -> None:
    """Períodos explícitos aplican ordenados y la sigmoid estable cubre eta positivo."""
    cfg = _cfg(
        metrics=("pd_marginal",),
        shock=StressShockConfig(factor="x", value=10.0, periods=(1,)),
    )
    result = _run_forward_only(cfg, term=_forward_term_structure([0.02]))
    term = result.term_structure()
    assert term is not None
    assert term.loc[0, "hazard_stress"] > 0.70
    assert result.scenario_results[0].stressed_macro_frame.loc[0, "period"] == 1


def test_copias_defensivas_no_mutacion_y_outputs_finitos() -> None:
    """El engine no muta inputs, ECL input ni engines, y no publica no finitos/-0.0."""
    cfg = _cfg(metrics=("pd_marginal", "ecl"))
    macro = _macro_projection(periods=(1,), severe={1: -0.0}, include_adverse=False)
    term = _forward_term_structure([0.02])
    ecl_input = _ecl_input(term)
    macro_before = macro.copy(deep=True)
    term_before = term.copy(deep=True)
    ecl_term_before = ecl_input.term_structure_frame
    assert ecl_term_before is not None

    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=ecl_input,
        macro_projection=macro,
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=EclStub(),
    )

    assert_frame_equal(macro, macro_before)
    assert_frame_equal(term, term_before)
    assert_frame_equal(ecl_input.term_structure_frame, ecl_term_before)
    for frame in (result.term_structure(), result.tidy()):
        assert frame is not None
        for value in frame.select_dtypes(include=["float"]).to_numpy().ravel():
            assert math.isfinite(float(value))
            if float(value) == 0.0:
                assert math.copysign(1.0, float(value)) > 0.0


def test_engine_rechaza_no_finitos_de_ecl() -> None:
    """Un engine económico no puede publicar infinitos silenciosos."""
    cfg = _cfg(metrics=("ecl",))
    with pytest.raises(StressOutputError, match="NaN ni infinitos"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(periods=(1,), include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=BadEclStub(),
        )


@pytest.mark.parametrize("nonfinite", [math.inf, Decimal("Infinity")])
def test_forward_term_structure_rechaza_no_finitos_extra_antes_de_ecl(
    nonfinite: float | Decimal,
) -> None:
    """Columnas económicas extra no pueden llevar infinitos hacia el engine ECL."""
    cfg = _cfg(metrics=("ecl",))
    term = _forward_term_structure([0.02])
    term.loc[:, "ead"] = nonfinite
    ecl = EclStub()

    with pytest.raises(StressInputError, match=r"forward_term_structure\.ead"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(periods=(1,), include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=ecl,
        )

    assert ecl.calls == []


def test_forward_term_structure_permite_claves_opcionales_faltantes() -> None:
    """Identificadores forward opcionales ausentes no invalidan un contrato válido."""
    term = _forward_term_structure([0.02])
    term["row_id"] = pd.Series([math.nan], dtype=object)
    term["segment"] = pd.Series([pd.NA], dtype=object)
    term["partition"] = pd.Series([pd.NaT], dtype=object)

    result = StressTestEngine.from_config(_cfg(metrics=("pd_marginal",))).run(
        forward_ecl_input=_ecl_input(term),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=PortfolioSatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
    )

    stress_term = result.term_structure()
    assert stress_term is not None
    assert stress_term.loc[0, "row_id"] is None
    assert stress_term.loc[0, "segment"] is None
    assert stress_term.loc[0, "partition"] is None
    impact_group = json.loads(str(result.tidy().loc[0, "group_key"]))
    assert impact_group["row_id"] is None
    assert impact_group["segment"] is None
    assert impact_group["partition"] is None


def test_forward_term_structure_claves_opcionales_rechazan_infinitos() -> None:
    """Las claves opcionales toleran faltantes, no valores no finitos observados."""
    term = _forward_term_structure([0.02])
    term.loc[:, "row_id"] = math.inf

    with pytest.raises(StressInputError, match=r"forward_term_structure\.row_id"):
        _run_forward_only(_cfg(metrics=("pd_marginal",)), term=term)


def test_forward_term_structure_claves_opcionales_rechazan_objetos_opacos() -> None:
    """Objetos sin estado público estable no pueden identificar curvas distintas."""

    class OpaqueForwardKey:
        """Objeto hashable sin identidad pública canónica."""

    term = _forward_term_structure([0.02])
    term["row_id"] = pd.Series([OpaqueForwardKey()], dtype=object)

    with pytest.raises(StressInputError, match=r"forward_term_structure\.row_id"):
        _run_forward_only(_cfg(metrics=("pd_marginal",)), term=term)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("row_id", {"id": 1}),
        ("segment", ["retail"]),
        ("partition", np.array([1])),
    ],
)
def test_forward_term_structure_claves_opcionales_exigen_escalares(
    column: str,
    value: object,
) -> None:
    """Identificadores opcionales no aceptan objetos no escalares."""
    term = _forward_term_structure([0.02])
    term[column] = pd.Series([value], dtype=object)

    with pytest.raises(StressInputError, match=rf"forward_term_structure\.{column}"):
        _run_forward_only(_cfg(metrics=("pd_marginal",)), term=term)


@pytest.mark.parametrize("with_period", [False, True])
def test_engine_rechaza_frames_economicos_vacios(with_period: bool) -> None:
    """Un engine económico vacío no puede publicarse como impacto cero."""
    cfg = _cfg(metrics=("ecl",))
    with pytest.raises(StressOutputError, match="frame vacío"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(periods=(1,), include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=EmptyEclStub(with_period=with_period),
        )


def test_publicacion_term_structure_none_y_features_diferidas_en_run() -> None:
    """``run`` falla claro para diferidos y respeta publish_stressed_term_structure."""
    no_term_cfg = _cfg(
        metrics=("pd_marginal",),
        output=StressOutputConfig(
            metrics=("pd_marginal",),
            publish_stressed_term_structure=False,
        ),
    )
    result = _run_forward_only(no_term_cfg)
    assert result.term_structure() is None
    assert result.card.summary["term_structure_rows"] == 0

    no_baseline_cfg = _cfg(
        metrics=("pd_marginal",),
        output=StressOutputConfig(
            metrics=("pd_marginal",),
            include_baseline_rows=False,
        ),
    )
    with pytest.raises(StressEngineError, match="include_baseline_rows=False"):
        _run_forward_only(no_baseline_cfg)

    sensitivity_cfg = StressConfig.model_construct(
        type="standard",
        input=StressInputConfig(),
        scenarios=(_scenario(),),
        sensitivities=(SensitivitySweepConfig(name="grid_x", factor="x", shock_value=1.0),),
        reverse=(),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    with pytest.raises(StressEngineError, match=r"B21\.4"):
        _run_forward_only(sensitivity_cfg)

    reverse_cfg = StressConfig.model_construct(
        type="standard",
        input=StressInputConfig(),
        scenarios=(_scenario(),),
        sensitivities=(),
        reverse=(
            ReverseStressConfig(
                enabled=True,
                target=StressTargetConfig(
                    name="pd_target",
                    metric="pd_marginal",
                    threshold=0.05,
                    scenario_name="severe_plus",
                    requires_economic_engine=False,
                ),
                factor="x",
                shock_value=1.0,
            ),
        ),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    with pytest.raises(ReverseStressError, match=r"B21\.5"):
        _run_forward_only(reverse_cfg)


def test_engines_invalidos_missing_relajado_y_source_official() -> None:
    """Ramas de dependencia económica y fuente official quedan auditables."""
    invalid_ecl_cfg = _cfg(metrics=("ecl",))
    with pytest.raises(StressDependencyError, match="calculate"):
        StressTestEngine.from_config(invalid_ecl_cfg).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=object(),  # type: ignore[arg-type]
        )

    invalid_provision_cfg = _cfg(metrics=("provision",))
    with pytest.raises(StressDependencyError, match="provision_engine"):
        StressTestEngine.from_config(invalid_provision_cfg).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=EclStub(),
            provision_engine=object(),  # type: ignore[arg-type]
        )

    strict_ecl = _cfg(
        metrics=("ecl",),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    strict_ecl_audit = InMemoryAuditSink()
    with pytest.raises(StressDependencyError, match="ECL engine conectado"):
        _run_forward_only(strict_ecl, audit=strict_ecl_audit)
    strict_ecl_falta = next(
        event.payload
        for event in strict_ecl_audit.events
        if event.payload["regla"] == "stress_falta_dato"
    )
    assert strict_ecl_falta["valor"]["reason"] == "missing_ecl_engine"
    assert strict_ecl_falta["valor"]["source"] == "engine_dependency"
    assert strict_ecl_falta["valor"]["scenario"] == "all"
    assert strict_ecl_falta["umbral"] == {"code": "FALTA-DATO-STR-5", "blocked": True}
    assert strict_ecl_falta["accion"] == "block"

    strict_provision = _cfg(
        metrics=("ecl", "provision"),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    strict_provision_audit = InMemoryAuditSink()
    with pytest.raises(StressDependencyError, match="provision_engine conectado"):
        StressTestEngine.from_config(strict_provision).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=EclStub(),
            audit=strict_provision_audit,
        )
    strict_provision_falta = next(
        event.payload
        for event in strict_provision_audit.events
        if event.payload["regla"] == "stress_falta_dato"
    )
    assert strict_provision_falta["valor"]["reason"] == "missing_provision_engine"
    assert strict_provision_falta["valor"]["source"] == "engine_dependency"
    assert strict_provision_falta["valor"]["scenario"] == "all"
    assert strict_provision_falta["umbral"] == {
        "code": "FALTA-DATO-STR-5",
        "blocked": True,
    }
    assert strict_provision_falta["accion"] == "block"

    relaxed_ecl = _cfg(
        metrics=("ecl",),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=False,
        ),
    )
    relaxed_audit = InMemoryAuditSink()
    relaxed_result = _run_forward_only(relaxed_ecl, audit=relaxed_audit)
    assert relaxed_result.diagnostics.warning_codes == ("FALTA-DATO-STR-5",)
    assert relaxed_result.tidy().empty
    relaxed_falta = next(
        event.payload
        for event in relaxed_audit.events
        if event.payload["regla"] == "stress_falta_dato"
    )
    assert relaxed_falta["valor"]["reason"] == "missing_ecl_engine"
    assert relaxed_falta["umbral"] == {"code": "FALTA-DATO-STR-5", "blocked": False}

    relaxed_provision = _cfg(
        metrics=("ecl", "provision"),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=False,
        ),
    )
    provision_audit = InMemoryAuditSink()
    with_provision_warning = StressTestEngine.from_config(relaxed_provision).run(
        forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
        macro_projection=_macro_projection(include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=_forward_term_structure([0.02]),
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=EclStub(),
        audit=provision_audit,
    )
    assert "FALTA-DATO-STR-5" in with_provision_warning.diagnostics.warning_codes
    assert set(with_provision_warning.tidy()["metric"]) == {"ecl"}
    provision_falta = next(
        event.payload
        for event in provision_audit.events
        if event.payload["regla"] == "stress_falta_dato"
    )
    assert provision_falta["valor"]["reason"] == "missing_provision_engine"
    assert provision_falta["umbral"] == {"code": "FALTA-DATO-STR-5", "blocked": False}

    official_shock = StressShockConfig(factor="x", value=1.0, source="official")
    official_cfg = _cfg(
        metrics=("pd_marginal", "ecl"),
        shock=official_shock,
        scenario=StressScenarioConfig(
            name="official_plus",
            base_forward_scenario="severe",
            severity=1.0,
            shocks=(official_shock,),
            weight=0.7,
            require_dominates_forward_adverse=False,
        ),
    )
    ecl = EclStub()
    official_audit = InMemoryAuditSink()
    official_result = StressTestEngine.from_config(official_cfg).run(
        forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
        macro_projection=_macro_projection(include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=_forward_term_structure([0.02]),
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=ecl,
        audit=official_audit,
    )
    assert official_result.diagnostics.falta_dato_codes == ("FALTA-DATO-STR-2",)
    official_falta = next(
        event.payload
        for event in official_audit.events
        if event.payload["regla"] == "stress_falta_dato"
    )
    assert official_falta["valor"]["source"] == "official"
    assert official_falta["umbral"] == {"code": "FALTA-DATO-STR-2", "blocked": False}
    official_warnings = {
        str(row.metric): row.warning_codes for row in official_result.tidy().itertuples(index=False)
    }
    assert official_warnings["pd_marginal"] == ("FALTA-DATO-STR-2",)
    assert official_warnings["ecl"] == ("FALTA-DATO-STR-2",)
    assert ecl.calls[1].loc[0, "scenario_weight"] == pytest.approx(1.0)


def test_errores_de_forma_en_engine_ecl_y_agregado_sin_periodo() -> None:
    """El output ECL se valida por forma, dominio y agregación sin período."""
    cfg = _cfg(metrics=("ecl",))
    no_period = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
        macro_projection=_macro_projection(include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=_forward_term_structure([0.02]),
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=NoPeriodEclStub(),
    )
    assert no_period.tidy().iloc[0]["period"] is None

    for engine, match in (
        (MissingMetricEclStub(), "columna reconocida"),
        (UnknownDimensionEclStub(), "columnas no soportadas"),
        (AmbiguousMetricEclStub(), "ambiguas"),
        (AliasSwitchingEclStub(), "aliases distintos"),
        (NegativeEclStub(), "no puede ser negativo"),
        (WarningEclStub(), "warning"),
        (NonFrameEclStub(), "pandas.DataFrame"),
    ):
        with pytest.raises((StressOutputError, StressDependencyError), match=match):
            StressTestEngine.from_config(cfg).run(
                forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
                macro_projection=_macro_projection(include_adverse=False),
                satellite_model=SatelliteStub(),
                forward_term_structure=_forward_term_structure([0.02]),
                scenario_weighting=ScenarioWeightingStub(),
                ecl_engine=engine,  # type: ignore[arg-type]
            )

    with pytest.raises(StressOutputError, match="fila-a-fila"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=OffsettingNegativeEclStub(),
        )


def test_inputs_forward_incompletos_fallan_y_periodos_string_ordenan_numerico() -> None:
    """El contrato forward se exige completo y los períodos se ordenan como enteros."""
    cfg = _cfg(
        metrics=("pd_marginal",),
        validation=StressValidationConfig(
            require_forward_severe=False,
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    with pytest.raises(StressInputError, match="scenario_weight"):
        _run_forward_only(
            cfg,
            macro=_macro_projection(include_adverse=False).drop(columns=["scenario_weight"]),
        )
    term_for_contract = _forward_term_structure([0.02])
    with pytest.raises(StressDependencyError, match="scenario_weighting"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(term_for_contract),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=term_for_contract,
            scenario_weighting=None,  # type: ignore[arg-type]
        )
    with pytest.raises(StressDependencyError, match="validate_macro_projection"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(term_for_contract),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=term_for_contract,
            scenario_weighting=object(),
        )
    invalid_weight_macro = _macro_projection(include_adverse=False)
    invalid_weight_macro.loc[:, "scenario_weight"] = 2.0
    with pytest.raises(StressInputError, match=r"macro_projection\.scenario_weight"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(term_for_contract),
            macro_projection=invalid_weight_macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term_for_contract,
            scenario_weighting=NoopScenarioWeightingStub(),
        )
    inconsistent_weight_macro = _macro_projection(periods=(1, 2), include_adverse=False)
    inconsistent_weight_macro.loc[:, "scenario_weight"] = [1.0, 0.5]
    with pytest.raises(StressInputError, match="constante por escenario"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(term_for_contract),
            macro_projection=inconsistent_weight_macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term_for_contract,
            scenario_weighting=NoopScenarioWeightingStub(),
        )
    with pytest.raises(StressInputError, match="source_model"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=SimpleForwardInput(),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]).drop(columns=["source_model"]),
            scenario_weighting=ScenarioWeightingStub(),
        )
    valid_weights = _ecl_input(_forward_term_structure([0.02])).scenario_weight_frame
    for metadata_column in ("source_model", "method", "pd_source", "pd_basis", "basis_state"):
        term = _forward_term_structure([0.02])
        term.loc[0, metadata_column] = ""
        with pytest.raises(
            StressInputError,
            match=rf"forward_term_structure\.{metadata_column}",
        ):
            StressTestEngine.from_config(cfg).run(
                forward_ecl_input=CompatibleForwardInput(
                    term_structure_frame=term,
                    scenario_weight_frame=valid_weights,
                ),
                macro_projection=_macro_projection(include_adverse=False),
                satellite_model=SatelliteStub(),
                forward_term_structure=term,
                scenario_weighting=ScenarioWeightingStub(),
            )
    term = _forward_term_structure([0.02])
    term.loc[0, "pd_basis"] = "unknown"
    with pytest.raises(StressInputError, match="pd_basis debe ser pit o ttc"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=valid_weights,
            ),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
        )
    term = _forward_term_structure([0.02])
    term.loc[0, "basis_state"] = "unknown"
    with pytest.raises(StressInputError, match="basis_state debe ser pit, blended o ttc"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=CompatibleForwardInput(
                term_structure_frame=term,
                scenario_weight_frame=valid_weights,
            ),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
        )

    term = _forward_term_structure([0.02])
    duplicated_term = pd.concat([term, term[["hazard"]]], axis=1)
    with pytest.raises(StressInputError, match=r"forward_term_structure.*columnas duplicadas"):
        StressTestEngine.from_config(cfg).run(
            forward_ecl_input=_ecl_input(term),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=duplicated_term,
            scenario_weighting=ScenarioWeightingStub(),
        )

    macro = _macro_projection(periods=(1, 2, 3), include_adverse=False)
    macro["period"] = macro["period"].astype(str)
    term = _forward_term_structure([0.02, 0.03, 0.04])
    term["period"] = term["period"].astype(str)
    result = StressTestEngine.from_config(cfg).run(
        forward_ecl_input=_ecl_input(term),
        macro_projection=macro,
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
    )

    term_frame = result.term_structure()
    assert term_frame is not None
    assert term_frame["period"].tolist() == [1, 2, 3]


def test_run_fallido_limpia_estado_previo_y_bloquea_run_scenario() -> None:
    """Una corrida inválida posterior no deja contexto viejo reutilizable."""
    cfg = _cfg(metrics=("pd_marginal",))
    term = _forward_term_structure([0.02])
    engine = StressTestEngine.from_config(cfg)
    result = engine.run(
        forward_ecl_input=_ecl_input(term),
        macro_projection=_macro_projection(periods=(1,), include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=term,
        scenario_weighting=ScenarioWeightingStub(),
    )
    assert result.tidy()["metric"].tolist() == ["pd_marginal"]
    assert engine._context is not None
    assert engine.forward_hash_ is not None
    assert engine.config_hash_ is not None
    assert engine.diagnostics_ is not None
    assert engine.dependency_versions_
    assert engine.run_started_at_ is not None
    assert engine.scenario_results_

    bad_macro = _macro_projection(periods=(1,), include_adverse=False).drop(
        columns=["scenario_weight"]
    )
    with pytest.raises(StressInputError, match="scenario_weight"):
        engine.run(
            forward_ecl_input=_ecl_input(term),
            macro_projection=bad_macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=term,
            scenario_weighting=ScenarioWeightingStub(),
        )

    assert engine._context is None
    assert engine.forward_hash_ is None
    assert engine.config_hash_ is None
    assert engine.scenario_results_ == ()
    assert engine.sensitivity_results_ == ()
    assert engine.reverse_results_ == ()
    assert engine.diagnostics_ is None
    assert engine.dependency_versions_ == {}
    assert engine.run_started_at_ is None
    with pytest.raises(StressEngineError, match="run_scenario exige ejecutar run"):
        engine.run_scenario(cfg.scenarios[0])


def test_dependencias_economicas_y_ramas_de_escenario_defensivas() -> None:
    """El engine falla explícitamente ante dependencias o escenarios inválidos."""
    provision_cfg = _cfg(metrics=("provision",))
    with pytest.raises(StressDependencyError, match="provisión requiere ECL"):
        _run_forward_only(provision_cfg)

    reverse_only_cfg = StressConfig(
        scenarios=(),
        reverse=(
            ReverseStressConfig(
                enabled=True,
                target=StressTargetConfig(
                    name="pd_objetivo",
                    metric="pd_cumulative",
                    threshold=0.25,
                    scenario_name="solo_reverse",
                    requires_economic_engine=False,
                ),
                factor="x",
                shock_value=1.0,
            ),
        ),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    with pytest.raises(ReverseStressError, match=r"B21\.5"):
        _run_forward_only(reverse_only_cfg)

    no_scenarios_cfg = StressConfig.model_construct(
        type="standard",
        input=StressInputConfig(),
        scenarios=(),
        sensitivities=(),
        reverse=(),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    with pytest.raises(StressEngineError, match="al menos un escenario"):
        _run_forward_only(no_scenarios_cfg)

    with pytest.raises(StressDependencyError, match="provision_engine conectado"):
        StressTestEngine.from_config(provision_cfg).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=EclStub(),
        )

    baseline_missing_cfg = _cfg(metrics=("ecl",))
    with pytest.raises(StressOutputError, match="baseline"):
        StressTestEngine.from_config(baseline_missing_cfg).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=_macro_projection(include_adverse=False),
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=ScenarioWeightingStub(),
            ecl_engine=BaselineMissingMetricEclStub(),
        )

    duplicated = StressScenarioConfig.model_construct(
        name="duplicated",
        kind="severe",
        base_forward_scenario="severe",
        severity=1.0,
        shocks=(
            StressShockConfig(factor="x", value=1.0, periods=(1,)),
            StressShockConfig(factor="x", value=2.0, periods=(1,)),
        ),
        weight=None,
        require_dominates_forward_adverse=False,
        description=None,
    )
    duplicated_cfg = StressConfig.model_construct(
        type="standard",
        input=StressInputConfig(),
        scenarios=(duplicated,),
        sensitivities=(),
        reverse=(),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    with pytest.raises(StressScenarioError, match="duplicados"):
        _run_forward_only(duplicated_cfg)

    duplicated_macro = pd.concat(
        [_macro_projection(include_adverse=False), _macro_projection(include_adverse=False)],
        ignore_index=True,
    )
    with pytest.raises(StressScenarioError, match="fila única"):
        _run_forward_only(_cfg(metrics=("pd_marginal",)), macro=duplicated_macro)

    missing_factor_cfg = _cfg(
        metrics=("pd_marginal",),
        shock=StressShockConfig(factor="z", value=1.0),
    )
    with pytest.raises(StressScenarioError, match="Factor de shock no existe"):
        _run_forward_only(missing_factor_cfg)

    missing_period_cfg = _cfg(
        metrics=("pd_marginal",),
        shock=StressShockConfig(factor="x", value=1.0, periods=(2,)),
    )
    with pytest.raises(StressScenarioError, match="fuera del horizonte"):
        _run_forward_only(missing_period_cfg)

    with pytest.raises(StressInputError, match="macro_projection no cubre forward_term_structure"):
        _run_forward_only(
            _cfg(metrics=("pd_marginal",)),
            macro=_macro_projection(periods=(1,), include_adverse=False),
            term=_forward_term_structure([0.02, 0.02]),
        )

    bad_operation_shock = StressShockConfig.model_construct(
        factor="x",
        operation="multiplicative",
        value=1.0,
        unit=None,
        periods="all",
        source="user",
        description=None,
    )
    bad_operation_cfg = StressConfig.model_construct(
        type="standard",
        input=StressInputConfig(),
        scenarios=(_scenario(shock=bad_operation_shock),),
        sensitivities=(),
        reverse=(),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )
    with pytest.raises(StressScenarioError, match="Operación de shock"):
        _run_forward_only(bad_operation_cfg)

    duplicated_period = pd.concat(
        [_forward_term_structure([0.02]), _forward_term_structure([0.02])],
        ignore_index=True,
    )
    with pytest.raises(StressInputError, match="períodos lifetime contiguos"):
        _run_forward_only(_cfg(metrics=("pd_marginal",)), term=duplicated_period)


def test_helpers_de_adverse_macro_y_validadores_tabulares_directos() -> None:
    """Rutas FALTA-DATO, adverse y validaciones tabulares quedan cubiertas."""
    strict_cfg = _cfg(
        metrics=("pd_marginal",),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=False,
            fail_on_falta_dato=True,
            fail_on_missing_ecl_engine=True,
        ),
    )
    official = StressShockConfig.model_construct(
        factor="x",
        operation="additive",
        value=1.0,
        unit=None,
        periods="all",
        source="official",
        description=None,
    )
    with pytest.raises(StressFaltaDatoError, match="FALTA-DATO-STR-2"):
        engine_module._validate_shock_source(official, scenario=_scenario(), cfg=strict_cfg)

    adverse_model = pd.DataFrame(
        {
            "scenario": ["adverse"],
            "macro_variable": ["x"],
            "period": [1],
            "projected_value": [3.0],
            "model_value": [1.0],
            "shock_value": [2.0],
        }
    )
    assert engine_module._adverse_delta(adverse_model, factor="x", period=1) == pytest.approx(2.0)

    adverse_base = pd.DataFrame(
        {
            "scenario": ["base", "adverse"],
            "macro_variable": ["x", "x"],
            "period": [1, 1],
            "projected_value": [1.0, 3.0],
            "model_value": [1.0, 3.0],
            "shock_value": [0.0, 0.0],
        }
    )
    assert engine_module._adverse_delta(adverse_base, factor="x", period=1) == pytest.approx(2.0)
    assert engine_module._adverse_delta(adverse_base.iloc[[1]], factor="x", period=1) is None

    adverse_path_default_shock = pd.DataFrame(
        {
            "scenario": ["base", "adverse"],
            "macro_variable": ["x", "x"],
            "period": [1, 1],
            "projected_value": [1.0, 3.0],
            "model_value": [1.0, 3.0],
            "shock_value": [0.0, 0.0],
        }
    )
    assert engine_module._adverse_delta(
        adverse_path_default_shock,
        factor="x",
        period=1,
    ) == pytest.approx(2.0)

    inconsistent_adverse_delta = adverse_path_default_shock.copy(deep=True)
    inconsistent_adverse_delta.loc[
        inconsistent_adverse_delta["scenario"] == "adverse",
        "shock_value",
    ] = 0.5
    with pytest.raises(StressInputError, match="identidad macro inconsistente"):
        engine_module._adverse_delta(inconsistent_adverse_delta, factor="x", period=1)

    adverse_zero = pd.DataFrame(
        {
            "scenario": ["base", "adverse"],
            "macro_variable": ["x", "x"],
            "period": [1, 1],
            "projected_value": [1.0, 1.0],
            "model_value": [1.0, 1.0],
            "shock_value": [0.0, 0.0],
        }
    )
    assert engine_module._adverse_delta(adverse_zero, factor="x", period=1) == 0.0
    adverse_zero_without_model = pd.DataFrame(
        {
            "scenario": ["base", "adverse"],
            "macro_variable": ["x", "x"],
            "period": [1, 1],
            "projected_value": [1.0, 1.0],
            "model_value": [1.0, 1.0],
            "shock_value": [0.0, 0.0],
        }
    )
    assert engine_module._adverse_delta(adverse_zero_without_model, factor="x", period=1) == 0.0

    engine_module._validate_macro_projection_values(_macro_projection(include_adverse=False))
    with pytest.raises(StressInputError, match="scenario_weight"):
        engine_module._validate_macro_projection_values(
            pd.DataFrame(
                {
                    "scenario": ["severe"],
                    "period": [1],
                    "macro_variable": ["x"],
                    "projected_value": [1.0],
                    "model_value": [0.0],
                    "shock_value": [1.0],
                }
            )
        )
    invalid_macro = _macro_projection(include_adverse=False)
    invalid_macro["scenario_weight"] = pd.Series(
        [None] * len(invalid_macro),
        index=invalid_macro.index,
        dtype=object,
    )
    with pytest.raises(StressInputError, match="scenario_weight"):
        engine_module._validate_macro_projection_values(invalid_macro)
    with pytest.raises(StressInputError, match="columnas requeridas"):
        engine_module._validate_macro_projection_values(
            pd.DataFrame(
                {
                    "scenario": ["severe"],
                    "period": [1],
                    "macro_variable": ["x"],
                    "projected_value": [1.0],
                }
            )
        )

    no_period_row = engine_module._forward_ecl_row(
        pd.Series({"scenario": "severe", "warning_codes": ()}),
        scenario=_scenario(),
        hazard=0.02,
        survival=0.98,
        pd_marginal=0.02,
        pd_cumulative=0.02,
        lgd=None,
        satellite_adjustment=0.0,
        warning_codes=(),
    )
    assert "period" not in no_period_row
    invalid_identity = _macro_projection(include_adverse=False)
    invalid_identity["model_value"] = pd.Series(
        [None] * len(invalid_identity),
        index=invalid_identity.index,
        dtype=object,
    )
    invalid_identity["shock_value"] = pd.Series(
        [None] * len(invalid_identity),
        index=invalid_identity.index,
        dtype=object,
    )
    with pytest.raises(StressInputError, match="model_value"):
        engine_module._validate_macro_projection_values(invalid_identity)
    invalid_macro = _macro_projection(include_adverse=False)
    invalid_macro.loc[0, "projected_value"] = 1.0
    invalid_macro.loc[0, "model_value"] = 0.0
    invalid_macro.loc[0, "shock_value"] = 0.5
    with pytest.raises(StressInputError, match="identidad macro inconsistente"):
        engine_module._validate_macro_projection_values(invalid_macro)
    nonfinite_macro = _macro_projection(include_adverse=False)
    nonfinite_macro.loc[0, "shock_value"] = math.inf
    with pytest.raises(StressInputError, match="NaN ni infinito"):
        engine_module._validate_macro_projection_values(nonfinite_macro)

    with pytest.raises(StressInputError, match="columnas requeridas"):
        engine_module._require_columns(pd.DataFrame({"x": [1]}), ("missing",), field_name="x")
    with pytest.raises(StressInputError, match="scenario='severe'"):
        engine_module._require_observed_scenario(
            pd.DataFrame({"scenario": ["base"]}),
            "severe",
            field_name="macro",
        )
    with pytest.raises(StressInputError, match="escenario medio prohibido"):
        engine_module._reject_reserved_scenarios(
            pd.DataFrame({"scenario": ["mean"]}),
            field_name="macro",
        )
    with pytest.raises(StressInputError, match="weighted_mean_input"):
        engine_module._reject_weighted_mean_columns(
            pd.DataFrame({"scenario": ["severe"], "weighted_mean_input": [True]}),
            field_name="macro",
        )
    with pytest.raises(StressScenarioError, match="sin períodos"):
        engine_module._shock_periods(
            StressShockConfig(factor="x", value=1.0),
            pd.DataFrame({"macro_variable": [], "period": []}),
            pd=None,
        )
    with pytest.raises(StressScenarioError, match="fuera del horizonte"):
        engine_module._shock_periods(
            StressShockConfig(factor="x", value=1.0, periods=(2,)),
            pd.DataFrame({"macro_variable": ["x"], "period": [1]}),
            pd=None,
        )
    empty_periods_shock = StressShockConfig.model_construct(
        factor="x",
        operation="additive",
        value=1.0,
        unit=None,
        periods=(),
        source="user",
        description=None,
    )
    with pytest.raises(StressScenarioError, match="no resolvió períodos"):
        engine_module._shock_periods(
            empty_periods_shock,
            pd.DataFrame({"macro_variable": ["x"], "period": [1]}),
            pd=None,
        )


def test_macro_projection_rechaza_weighted_mean_input_sin_validador_externo() -> None:
    """El guard anti promedio de inputs no depende del objeto ``scenario_weighting``."""
    macro = _macro_projection(periods=(1,), include_adverse=False)
    macro.loc[:, "weighted_mean_input"] = True

    with pytest.raises(StressInputError, match="weighted_mean_input"):
        StressTestEngine.from_config(_cfg(metrics=("pd_marginal",))).run(
            forward_ecl_input=_ecl_input(_forward_term_structure([0.02])),
            macro_projection=macro,
            satellite_model=SatelliteStub(),
            forward_term_structure=_forward_term_structure([0.02]),
            scenario_weighting=object(),
        )


def test_helpers_satellite_economicos_y_frames_privados() -> None:
    """Helpers privados críticos cubren rutas no alcanzables desde config validada."""
    term = _forward_term_structure([0.02])
    scenario = _scenario()
    macro_result = engine_module._MacroStressResult(
        scenario_frame=pd.DataFrame(),
        projection_frame=pd.DataFrame(),
        delta_lookup={(1, "x"): 1.0},
        macro_variable_set=("x",),
        warning_codes=(),
    )

    assert (
        engine_module._factor_coefficient(
            _satellite_with_coefficients({"x": 0.5}),
            component="pd",
            factor="x",
            segment="retail",
            required=True,
        )
        == 0.5
    )
    assert engine_module._direct_factor_coefficient({"factors": {"x": 0.5}}, factor="x") == 0.5
    assert (
        engine_module._factor_coefficient(
            _satellite_with_coefficients(
                {"pd": {"retail": {"factors": {"x": 0.4}}}},
                attr="coefficients",
            ),
            component="pd",
            factor="x",
            segment="retail",
            required=True,
        )
        == 0.4
    )
    for satellite, match in (
        (type("NoCoefficients", (), {})(), "coefficients_"),
        (type("MissingComponent", (), {"coefficients_": {"lgd": {}}})(), "coeficientes"),
        (
            _satellite_with_coefficients({"pd": {"otro": {"factors": {"x": 0.5}}}}),
            "segmento",
        ),
        (
            _satellite_with_coefficients({"pd": {"retail": {"factors": {"z": 0.5}}}}),
            "factor",
        ),
    ):
        with pytest.raises((StressInputError, StressScenarioError), match=match):
            engine_module._factor_coefficient(
                satellite,
                component="pd",
                factor="x",
                segment="retail",
                required=True,
            )

    assert (
        engine_module._factor_coefficient(
            _satellite_with_coefficients({"pd": {}}),
            component="lgd",
            factor="x",
            segment="retail",
            required=False,
        )
        is None
    )
    assert (
        engine_module._factor_coefficient(
            _satellite_with_coefficients({"lgd": {"otro": {"factors": {"x": 0.2}}}}),
            component="lgd",
            factor="x",
            segment="retail",
            required=False,
        )
        is None
    )
    assert (
        engine_module._factor_coefficient(
            _satellite_with_coefficients({"lgd": {"retail": {"factors": {"z": 0.2}}}}),
            component="lgd",
            factor="x",
            segment="retail",
            required=False,
        )
        is None
    )
    assert (
        engine_module._project_lgd(
            pd.Series({"segment": "retail"}),
            period=1,
            lgd_base=None,
            macro_result=macro_result,
            satellite_model=SatelliteStub(),
            cfg=_cfg(),
        )
        is None
    )
    assert engine_module._project_lgd(
        pd.Series({"segment": "retail"}),
        period=1,
        lgd_base=0.45,
        macro_result=macro_result,
        satellite_model=_satellite_with_coefficients({"pd": {"retail": {"factors": {"x": 0.5}}}}),
        cfg=_cfg(),
    ) == pytest.approx(0.45)

    lgd_rows, lgd_warnings = engine_module._forward_only_impact_rows(
        scenario,
        severity=1.0,
        stress_term_structure=pd.DataFrame(
            {"period": [1], "lgd_base": [None], "lgd_stress": [None]}
        ),
        metrics=("lgd",),
        cfg=_cfg(metrics=("lgd",)),
        audit=None,
    )
    assert lgd_rows == []
    assert lgd_warnings == ("FALTA-DATO-STR-LGD",)
    pd_rows, pd_warnings = engine_module._forward_only_impact_rows(
        scenario,
        severity=1.0,
        stress_term_structure=pd.DataFrame(
            {"period": [1], "pd_marginal_base": [None], "pd_marginal_stress": [None]}
        ),
        metrics=("pd_marginal",),
        cfg=_cfg(metrics=("pd_marginal",)),
        audit=None,
    )
    assert pd_rows == []
    assert pd_warnings == ()
    zero_base = engine_module._impact_row(
        scenario,
        severity=1.0,
        metric="ecl",
        value_base=0.0,
        value_stress=1.0,
        period=1,
        engine_source="ecl_engine",
        warning_codes=(),
    )
    assert zero_base["relative_delta"] is None
    minimal_ecl_row = engine_module._forward_ecl_row(
        pd.Series({"period": 1, "scenario": "severe"}),
        scenario=scenario,
        hazard=0.02,
        survival=0.98,
        pd_marginal=0.02,
        pd_cumulative=0.02,
        lgd=None,
        satellite_adjustment=0.0,
        warning_codes=(),
    )
    assert "scenario_weight" not in minimal_ecl_row
    assert "lgd" not in minimal_ecl_row
    assert "warning_codes" not in minimal_ecl_row

    missing_ecl_context = engine_module._RunContext(
        macro_projection=_macro_projection(include_adverse=False),
        forward_term_structure=term,
        forward_ecl_input=_ecl_input(term),
        satellite_model=SatelliteStub(),
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=None,
        provision_engine=None,
        audit=None,
        pd=pd,
    )
    with pytest.raises(StressDependencyError, match="Métrica económica"):
        engine_module._economic_impact_rows(
            scenario,
            severity=1.0,
            forward_ecl_term_structure=term,
            context=missing_ecl_context,
            cfg=_cfg(metrics=("ecl",)),
        )

    missing_provision_context = engine_module._RunContext(
        macro_projection=_macro_projection(include_adverse=False),
        forward_term_structure=term,
        forward_ecl_input=_ecl_input(term),
        satellite_model=SatelliteStub(),
        scenario_weighting=ScenarioWeightingStub(),
        ecl_engine=EclStub(),
        provision_engine=None,
        audit=None,
        pd=pd,
    )
    stress_term = term.copy(deep=True)
    stress_term.loc[:, "scenario"] = scenario.name
    with pytest.raises(StressDependencyError, match="Métrica provision"):
        engine_module._economic_impact_rows(
            scenario,
            severity=1.0,
            forward_ecl_term_structure=stress_term,
            context=missing_provision_context,
            cfg=_cfg(metrics=("provision",)),
        )

    with pytest.raises(StressOutputError, match="baseline"):
        engine_module._metric_rows_from_engine_frames(
            scenario,
            severity=1.0,
            metric="ecl",
            value_base_frame=pd.DataFrame({"period": [1], "otra": [1.0]}),
            value_stress_frame=pd.DataFrame({"period": [1], "ecl": [1.0]}),
            engine_source="ecl_engine",
        )
    with pytest.raises(StressOutputError, match="períodos/grupos inconsistentes"):
        engine_module._metric_rows_from_engine_frames(
            scenario,
            severity=1.0,
            metric="ecl",
            value_base_frame=pd.DataFrame({"period": [1], "ecl": [1.0]}),
            value_stress_frame=pd.DataFrame({"period": [2], "ecl": [1.0]}),
            engine_source="ecl_engine",
        )

    compatible = CompatibleForwardInput(
        term_structure_frame=None,
        scenario_weight_frame=_ecl_input(term).scenario_weight_frame,
    )
    cfg = _cfg()
    cloned = engine_module._clone_forward_ecl_input(compatible, cfg=cfg, term_structure_frame=term)
    assert cloned.term_structure_frame is not term
    weight_frame = pd.DataFrame(
        [
            {
                "scenario": "severe",
                "weight": 1.0,
                "is_default": False,
                "source": "config",
                "description": "severe",
            }
        ],
        columns=_SCENARIO_WEIGHT_COLUMNS,
    )
    cloned_with_weight = engine_module._clone_forward_ecl_input(
        compatible,
        cfg=cfg,
        term_structure_frame=term,
        scenario_weight_frame=weight_frame,
    )
    assert_frame_equal(cloned_with_weight.scenario_weight_frame, weight_frame)
    with pytest.raises(StressDependencyError, match="contract_version"):
        engine_module._clone_forward_ecl_input(
            SimpleForwardInput(), cfg=cfg, term_structure_frame=term
        )
    with pytest.raises(StressDependencyError, match="contract_version"):
        engine_module._clone_forward_ecl_input(
            ImmutableForwardInput(),
            cfg=cfg,
            term_structure_frame=term,
        )
    with pytest.raises(StressDependencyError, match="model_copy"):
        engine_module._clone_forward_ecl_input(
            FailingModelCopyForwardInput(
                term_structure_frame=None,
                scenario_weight_frame=_ecl_input(term).scenario_weight_frame,
            ),
            cfg=cfg,
            term_structure_frame=term,
        )
    with pytest.raises(StressDependencyError, match="term_structure_frame"):
        engine_module._clone_forward_ecl_input(
            IgnoringTermModelCopyForwardInput(
                term_structure_frame=None,
                scenario_weight_frame=_ecl_input(term).scenario_weight_frame,
            ),
            cfg=cfg,
            term_structure_frame=term,
        )
    stale_term = term.copy(deep=True)
    stale_term.loc[0, "row_id"] = "stale-id"
    with pytest.raises(StressDependencyError, match="term_structure_frame"):
        engine_module._clone_forward_ecl_input(
            IgnoringTermModelCopyForwardInput(
                term_structure_frame=stale_term,
                scenario_weight_frame=_ecl_input(stale_term).scenario_weight_frame,
            ),
            cfg=cfg,
            term_structure_frame=term,
        )
    with pytest.raises(StressDependencyError, match="scenario_weight_frame"):
        engine_module._clone_forward_ecl_input(
            IgnoringWeightModelCopyForwardInput(
                term_structure_frame=None,
                scenario_weight_frame=_ecl_input(term).scenario_weight_frame,
            ),
            cfg=cfg,
            term_structure_frame=term,
            scenario_weight_frame=weight_frame,
        )
    with pytest.raises(StressDependencyError, match="term_structure_frame"):
        engine_module._clone_forward_ecl_input(
            ReadOnlyCompatibleForwardInput(
                term=None,
                weights=_ecl_input(term).scenario_weight_frame,
            ),
            cfg=cfg,
            term_structure_frame=term,
        )

    assert engine_module._concat_required_frames((), columns=("x",), pd=pd).empty
    with pytest.raises(StressInputError, match="scenario='missing'"):
        engine_module._scenario_term_structure(term, scenario_name="missing", pd=pd)
    with pytest.raises(StressInputError, match="scenario_weight vacío"):
        engine_module._scenario_weight_frame(term.iloc[0:0], scenario_name="severe", pd=pd)
    inconsistent_weight = pd.concat([term, term], ignore_index=True)
    inconsistent_weight.loc[:, "scenario_weight"] = [1.0, 0.5]
    with pytest.raises(StressInputError, match="scenario_weight debe ser constante"):
        engine_module._scenario_weight_frame(
            inconsistent_weight,
            scenario_name="severe",
            pd=pd,
        )
    with pytest.raises(StressDependencyError, match="constante por escenario"):
        engine_module._term_scenario_weights(
            pd.DataFrame(
                [
                    {"scenario": "severe", "weight": 1.0},
                    {"scenario": "severe", "weight": 0.5},
                ]
            ),
            scenario_column="scenario",
            weight_column="weight",
            field_name="weights",
        )
    assert engine_module._segment_value(pd.Series({})) == "__all__"
    assert (
        engine_module._forward_term_text(SimpleNamespace(source_model="survival"), "source_model")
        == "survival"
    )
    with pytest.raises(StressInputError, match="source_model"):
        engine_module._forward_term_text(SimpleNamespace(source_model="   "), "source_model")
    assert engine_module._optional_probability_from_row(pd.Series({}), ("lgd",), cfg=_cfg()) is None
    assert (
        engine_module._optional_probability_from_row(pd.Series({"lgd": None}), ("lgd",), cfg=_cfg())
        is None
    )
    assert (
        engine_module._optional_probability_from_row(
            pd.Series({"lgd": pd.NA}), ("lgd",), cfg=_cfg()
        )
        is None
    )
    assert engine_module._mean_optional_probability([None], metric="lgd") is None
    with pytest.raises(StressOutputError, match="negativo"):
        engine_module._non_negative_metric_sum([-1.0], field_name="ecl")

    duplicated_term = pd.concat([term, term], ignore_index=True)
    with pytest.raises(StressInputError, match="períodos lifetime contiguos"):
        engine_module._apply_satellite_stress(
            scenario,
            severity=1.0,
            macro_result=macro_result,
            forward_term_structure=duplicated_term,
            satellite_model=SatelliteStub(),
            cfg=_cfg(),
            pd=pd,
            audit=None,
        )


def test_helpers_numericos_missing_e_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Normalizadores numéricos y guards de import fallan con mensajes propios."""
    assert engine_module._contains_nonfinite(None) is False
    assert engine_module._contains_nonfinite(True) is False
    assert engine_module._contains_nonfinite(pd.NA) is True
    assert engine_module._contains_nonfinite(pd.Series([float("inf")], dtype="Float32").iloc[0])
    assert engine_module._contains_nonfinite({"x": math.inf}) is True
    assert engine_module._contains_nonfinite([math.inf]) is True
    assert engine_module._contains_nonfinite(np.array([1.0, math.nan])) is True
    assert engine_module._contains_nonfinite(np.array([1.0, 2.0])) is False
    assert engine_module._contains_nonfinite(np.array([{"x": math.inf}], dtype=object)) is True
    assert engine_module._contains_nonfinite(np.array(["NaT"], dtype="datetime64[ns]")) is True
    assert engine_module._contains_nonfinite(np.array(["NaT"], dtype="timedelta64[ns]")) is True
    assert engine_module._contains_nonfinite(np.array(["ok"], dtype=str)) is False
    assert (
        engine_module._numpy_array_contains_nonfinite(np.array(["NaT"], dtype="datetime64[ns]"))
        is True
    )
    hash_a = engine_module._combined_frame_hash(
        (pd.DataFrame({"x": [-0.0], "warning_codes": [["A"]]}),),
        pd=pd,
    )
    hash_b = engine_module._combined_frame_hash(
        (pd.DataFrame({"x": [0.0], "warning_codes": [("A",)]}),),
        pd=pd,
    )
    assert hash_a == hash_b
    object_decimal_zero = pd.DataFrame(
        {"x": pd.Series([Decimal("-0")], dtype="object"), "label": ["same"]}
    )
    object_positive_zero = pd.DataFrame({"x": pd.Series([0.0], dtype="object"), "label": ["same"]})
    object_negative_zero = pd.DataFrame({"x": pd.Series([-0.0], dtype="object"), "label": ["same"]})
    assert engine_module._combined_frame_hash((object_decimal_zero,), pd=pd) == (
        engine_module._combined_frame_hash((object_positive_zero,), pd=pd)
    )
    assert engine_module._combined_frame_hash((object_negative_zero,), pd=pd) == (
        engine_module._combined_frame_hash((object_positive_zero,), pd=pd)
    )
    object_decimal_one = pd.DataFrame({"x": pd.Series([Decimal("1.0")], dtype="object")})
    object_string_one = pd.DataFrame({"x": pd.Series(["1"], dtype="object")})
    assert engine_module._combined_frame_hash((object_decimal_one,), pd=pd) != (
        engine_module._combined_frame_hash((object_string_one,), pd=pd)
    )
    object_mapping_decimal = pd.DataFrame(
        {"x": pd.Series([{"value": Decimal("1.0")}], dtype="object")}
    )
    object_mapping_string = pd.DataFrame({"x": pd.Series([{"value": "1"}], dtype="object")})
    assert engine_module._combined_frame_hash((object_mapping_decimal,), pd=pd) != (
        engine_module._combined_frame_hash((object_mapping_string,), pd=pd)
    )
    assert engine_module._hashable_cell(True) == ("__bool__", True)
    assert engine_module._hashable_cell(np.bool_(True)) == ("__bool__", True)
    assert engine_module._hashable_cell(np.int64(1)) == 1
    assert engine_module._hashable_cell(np.float64(1.0)) == 1.0
    assert engine_module._hashable_cell(np.float64(-0.0)) == 0.0
    assert engine_module._hashable_cell(np.array(0.5)) == 0.5
    assert engine_module._hashable_cell(_lineage_ecl_multiplier_one)[0] == "__callable__"
    assert engine_module._canonical_hash({"x": np.float64(0.5)}, pd=pd) == (
        engine_module._canonical_hash({"x": 0.5}, pd=pd)
    )
    assert engine_module._canonical_payload(np.bool_(True), pd=pd) == (
        engine_module._canonical_payload(True, pd=pd)
    )
    assert engine_module._canonical_payload(np.array(True), pd=pd) == (
        engine_module._canonical_payload(True, pd=pd)
    )
    assert engine_module._canonical_hash({"x": np.array(-0.0)}, pd=pd) == (
        engine_module._canonical_hash({"x": 0.0}, pd=pd)
    )
    assert engine_module._hashable_cell(Decimal("NaN")) == ("__decimal__", "NaN")
    assert engine_module._hashable_cell(Decimal("1.2300")) == ("__decimal__", "1.23")
    assert engine_module._hashable_cell(1.5) == 1.5
    assert engine_module._hashable_cell(math.inf) == ("__float__", "inf")
    assert engine_module._canonical_hash({"x": math.nan}, pd=pd) != (
        engine_module._canonical_hash({"x": "nan"}, pd=pd)
    )
    assert engine_module._combined_frame_hash(
        (pd.DataFrame({"x": pd.Series([math.nan], dtype="object")}),),
        pd=pd,
    ) != engine_module._combined_frame_hash(
        (pd.DataFrame({"x": pd.Series(["nan"], dtype="object")}),),
        pd=pd,
    )
    assert engine_module._combined_frame_hash(
        (pd.DataFrame({"x": pd.Series([False], dtype="object")}),),
        pd=pd,
    ) != engine_module._combined_frame_hash(
        (pd.DataFrame({"x": pd.Series([0], dtype="object")}),),
        pd=pd,
    )
    assert engine_module._combined_frame_hash((pd.DataFrame({"x": [True]}),), pd=pd) != (
        engine_module._combined_frame_hash((pd.DataFrame({"x": [1]}),), pd=pd)
    )
    hashable_dataclass = engine_module._hashable_cell(
        NestedLineageConfig(limit=0.10, labels=("x",))
    )
    assert hashable_dataclass[0] == "__object__"
    sort_helpers, payload_helper = engine_module._hash_helper_columns(
        ("_nikodym_hash_sort_0", "_nikodym_hash_sort_payload"),
        key_count=1,
    )
    assert sort_helpers == ("_nikodym_hash_sort_0_1",)
    assert payload_helper == "_nikodym_hash_sort_payload_1"
    assert (
        engine_module._satellite_model_lineage(
            _satellite_with_coefficients(
                {"pd": {"retail": {"factors": {"x": 0.5}}}}, attr="coefficients"
            ),
            pd=pd,
        )["coefficients_hash"]
        is not None
    )

    class DumpMapping:
        """Objeto mínimo con estado serializable por ``model_dump``."""

        def model_dump(self, *, mode: str) -> dict[str, object]:
            """Retorna mapping canónico para lineage."""
            assert mode == "python"
            return {"x": Decimal("-0")}

    class DumpList:
        """Objeto con ``model_dump`` no mapping."""

        def model_dump(self, *, mode: str) -> list[str]:
            """Retorna forma no aceptada como estado público."""
            assert mode == "python"
            return ["x"]

    class DumpFiltered:
        """Objeto con ``model_dump`` sometido al filtro runtime común."""

        def model_dump(self, *, mode: str) -> dict[str, object]:
            """Retorna estado público mezclado con trazas runtime."""
            assert mode == "python"
            return {
                "_private": "x",
                "calls": [1],
                "events": [2],
                "history": {"multiplier": 2.0},
                "records": ("material",),
                "weight_calls": [3],
                "batch_events": [4],
                "custom_calls": [5],
            }

    class DumpCallable:
        """Objeto tipo Pydantic con callable anidado en ``model_dump``."""

        def __init__(self, strategy: Any) -> None:
            self.strategy = strategy

        def model_dump(self, *, mode: str) -> dict[str, object]:
            """Retorna estado público con callable anidado."""
            assert mode == "python"
            return {"strategy": self.strategy}

    @dataclass(frozen=True)
    class DataclassFiltered:
        """Dataclass con campos materiales y runtime."""

        history: dict[str, float]
        records: tuple[str, ...]
        calls: tuple[int, ...]
        refresh_events: tuple[int, ...]

    @dataclass(frozen=True)
    class DataclassCallable:
        """Dataclass con callable anidado."""

        strategy: Any

    class SlotOnly:
        """Objeto sin ``__dict__`` para lineage defensivo."""

        __slots__ = ()

    class SlotFiltered:
        """Objeto slotted con estado material y runtime."""

        __slots__ = ("_private", "calls", "history", "records", "refresh_events")

        def __init__(self) -> None:
            self._private = "x"
            self.calls = [1]
            self.history = {"multiplier": 2.0}
            self.records = ("material",)
            self.refresh_events = [2]

    class SlotPartiallyUnset:
        """Objeto slotted con un slot declarado pero no inicializado."""

        __slots__ = ("history", "records")

        def __init__(self) -> None:
            self.history = {"multiplier": 2.0}

    class DictFiltered:
        """Objeto con ``__dict__`` y el mismo filtro runtime."""

        def __init__(self) -> None:
            self._private = "x"
            self.calls = [1]
            self.history = {"multiplier": 2.0}
            self.records = ("material",)
            self.refresh_events = [2]

    class CallableFiltered:
        """Objeto con callable público material para lineage."""

        def __init__(self, strategy: Any) -> None:
            self.strategy = strategy

    class Opaque:
        """Objeto opaco para canonicalización por tipo."""

        __slots__ = ()

    class OpaqueKey:
        """Clave opaca indistinguible sin estado público."""

        __slots__ = ()

    class ArrayState:
        """Objeto con estado público tipo ndarray para lineage."""

        def __init__(self, coefficient: float, *, dtype: str = "<f8") -> None:
            self.coef_ = np.array([coefficient], dtype=dtype)

    assert engine_module._public_state(DumpMapping()) == {"x": Decimal("-0")}
    assert engine_module._public_state(DumpList()) == {}
    filtered_state = {"history": {"multiplier": 2.0}, "records": ("material",)}
    assert engine_module._public_state(DumpFiltered()) == filtered_state
    assert (
        engine_module._public_state(
            DataclassFiltered(
                history={"multiplier": 2.0},
                records=("material",),
                calls=(1,),
                refresh_events=(2,),
            )
        )
        == filtered_state
    )
    assert engine_module._public_state(SlotFiltered()) == filtered_state
    assert engine_module._public_state(SlotPartiallyUnset()) == {"history": {"multiplier": 2.0}}
    assert engine_module._public_state(DictFiltered()) == filtered_state
    assert engine_module._public_state_from_items(((1, "x"), ("history", {"x": 1}))) == {
        "history": {"x": 1}
    }
    callable_state = engine_module._public_state(CallableFiltered(_lineage_ecl_multiplier_one))
    assert callable_state["strategy"]["__callable__"].endswith("._lineage_ecl_multiplier_one")
    assert callable_state["strategy"]["package_version"] == "no-disponible"
    callable_object_state = engine_module._public_state(
        CallableFiltered(LineageCallableMultiplier(2.0))
    )
    assert callable_object_state["strategy"]["state"] == {"multiplier": 2.0}
    bound_callable_state = engine_module._public_state(
        CallableFiltered(BoundLineageMultiplier(2.0).scale)
    )
    assert bound_callable_state["strategy"]["bound_method"]["self"]["state"] == {"multiplier": 2.0}
    class_bound_callable_state = engine_module._public_state(
        CallableFiltered(ClassBoundLineageMultiplier.scale)
    )
    assert class_bound_callable_state["strategy"]["bound_method"]["self"]["type"].endswith(
        ".ClassBoundLineageMultiplier"
    )
    partial_callable_state = engine_module._public_state(
        CallableFiltered(functools.partial(_lineage_ecl_multiplier_partial, multiplier=2.0))
    )
    assert partial_callable_state["strategy"]["partial"]["keywords"] == {"multiplier": 2.0}
    fallback_callable_state = engine_module._public_state(
        CallableFiltered(CallableIdentityFallback())
    )
    assert fallback_callable_state["strategy"]["__callable__"].endswith(".CallableIdentityFallback")
    assert engine_module._module_package_version(None) == "no-disponible"
    with pytest.raises(StressDependencyError, match="callable"):
        engine_module._public_state(CallableFiltered(lambda term: term))
    nested_strategy_a = functools.partial(_lineage_ecl_multiplier_partial, multiplier=1.0)
    nested_strategy_b = functools.partial(_lineage_ecl_multiplier_partial, multiplier=2.0)
    assert engine_module._canonical_hash({"strategy": nested_strategy_a}, pd=pd) != (
        engine_module._canonical_hash({"strategy": nested_strategy_b}, pd=pd)
    )
    assert engine_module._canonical_hash([BoundLineageMultiplier(1.0).scale], pd=pd) != (
        engine_module._canonical_hash([BoundLineageMultiplier(2.0).scale], pd=pd)
    )
    assert engine_module._canonical_hash(DataclassCallable(nested_strategy_a), pd=pd) != (
        engine_module._canonical_hash(DataclassCallable(nested_strategy_b), pd=pd)
    )
    assert engine_module._canonical_hash(DumpCallable(nested_strategy_a), pd=pd) != (
        engine_module._canonical_hash(DumpCallable(nested_strategy_b), pd=pd)
    )
    with pytest.raises(StressDependencyError, match="callable"):
        engine_module._canonical_hash({"strategy": lambda term: term}, pd=pd)
    assert engine_module._public_state([Decimal("-0")]) == {
        "__sequence_type__": "builtins.list",
        "items": [Decimal("-0")],
    }
    assert engine_module._public_state({"b", "a"}) == {
        "__sequence_type__": "builtins.set",
        "items": ["a", "b"],
    }
    assert engine_module._public_state(SlotOnly()) == {}
    assert engine_module._object_lineage(1, pd=pd)["package_version"] == "no-disponible"
    nested_state_a = {
        "items": [NestedLineageConfig(limit=0.10, labels=("x",))],
        "validation": StressValidationConfig(probability_tol=1e-10),
    }
    nested_state_b = {
        "items": [NestedLineageConfig(limit=0.20, labels=("x",))],
        "validation": StressValidationConfig(probability_tol=2e-10),
    }
    assert (
        engine_module._object_lineage(nested_state_a, pd=pd)["state_hash"]
        != (engine_module._object_lineage(nested_state_b, pd=pd)["state_hash"])
    )
    assert (
        engine_module._object_lineage(ArrayState(1.0), pd=pd)["state_hash"]
        != engine_module._object_lineage(ArrayState(2.0), pd=pd)["state_hash"]
    )
    assert (
        engine_module._object_lineage(ArrayState(1.0, dtype="<f8"), pd=pd)["state_hash"]
        == engine_module._object_lineage(ArrayState(1.0, dtype=">f8"), pd=pd)["state_hash"]
    )

    class OpaqueLineageKey:
        """Clave opaca sin estado público para probar colisiones de canonicalización."""

    opaque_mapping = {OpaqueLineageKey(): [], OpaqueLineageKey(): {}}
    with pytest.raises(StressDependencyError, match="claves no distinguibles"):
        engine_module._public_state(opaque_mapping)
    with pytest.raises(StressDependencyError, match="claves no distinguibles"):
        engine_module._object_lineage(opaque_mapping, pd=pd)

    assert (
        engine_module._maybe_logical_frame_hash(
            None,
            key_columns=engine_module._FORWARD_TERM_HASH_KEY_COLUMNS,
            field_name="term",
            pd=pd,
        )
        is None
    )
    assert (
        engine_module._maybe_logical_frame_hash(
            pd.DataFrame({"scenario": ["severe"], "value": [1]}),
            key_columns=("scenario",),
            field_name="term",
            pd=pd,
        )
        is not None
    )
    assert engine_module._maybe_logical_frame_hash(
        {"x": Decimal("-0")},
        key_columns=engine_module._FORWARD_TERM_HASH_KEY_COLUMNS,
        field_name="term",
        pd=pd,
    ) == engine_module._canonical_hash({"x": 0.0}, pd=pd)
    cfg = _cfg(metrics=("pd_marginal",))
    assert (
        engine_module._maybe_forward_term_frame_hash(
            None,
            cfg=cfg,
            key_columns=engine_module._FORWARD_TERM_HASH_KEY_COLUMNS,
            field_name="term",
            pd=pd,
        )
        is None
    )
    assert engine_module._maybe_forward_term_frame_hash(
        {"x": Decimal("-0")},
        cfg=cfg,
        key_columns=engine_module._FORWARD_TERM_HASH_KEY_COLUMNS,
        field_name="term",
        pd=pd,
    ) == engine_module._canonical_hash({"x": 0.0}, pd=pd)
    assert (
        engine_module._maybe_scenario_weight_frame_hash(
            None,
            key_columns=engine_module._SCENARIO_WEIGHT_HASH_KEY_COLUMNS,
            field_name="weights",
            pd=pd,
        )
        is None
    )
    assert engine_module._maybe_scenario_weight_frame_hash(
        {"x": Decimal("-0")},
        key_columns=engine_module._SCENARIO_WEIGHT_HASH_KEY_COLUMNS,
        field_name="weights",
        pd=pd,
    ) == engine_module._canonical_hash({"x": 0.0}, pd=pd)
    with pytest.raises(StressInputError, match="columnas de hash lógico"):
        engine_module._canonical_hash_frame(
            pd.DataFrame({"scenario": ["severe"]}),
            key_columns=("missing",),
            field_name="term",
        )
    with pytest.raises(StressInputError, match="columnas duplicadas"):
        engine_module._canonical_hash_frame(
            pd.DataFrame([["severe", "base"]], columns=["scenario", "scenario"]),
            key_columns=("scenario",),
            field_name="term",
        )
    assert engine_module._canonical_hash({"x": Decimal("1.0")}, pd=pd) != (
        engine_module._canonical_hash({"x": "1"}, pd=pd)
    )
    assert engine_module._canonical_hash({"x": {"value": Decimal("1.0")}}, pd=pd) != (
        engine_module._canonical_hash({"x": {"value": "1"}}, pd=pd)
    )
    missing_lgd_base = pd.DataFrame({"lgd_base": [None], "pd_basis": ["pit"]})
    engine_module._insert_lgd_from_base_if_available(missing_lgd_base)
    assert "lgd" not in missing_lgd_base.columns
    assert engine_module._forward_ecl_columns(("pd_basis",), ({"lgd": 0.4},)) == (
        "lgd",
        "pd_basis",
    )
    assert engine_module._forward_ecl_columns(("x",), ({"lgd": 0.4},)) == ("x", "lgd")
    assert engine_module._canonical_payload(pd.DataFrame({"x": [1]}), pd=pd)["value"]["rows"] == 1
    assert engine_module._canonical_payload({"s": {"b", "a"}}, pd=pd) == {
        "__nikodym_payload_type__": "mapping",
        "value": {
            "type": "builtins.dict",
            "items": [
                [
                    ["builtins.str", "s"],
                    {
                        "__nikodym_payload_type__": "set",
                        "value": {"type": "builtins.set", "items": ["a", "b"]},
                    },
                ]
            ],
        },
    }
    assert engine_module._canonical_hash({1: "b"}, pd=pd) != engine_module._canonical_hash(
        {"1": "a", 1: "b"},
        pd=pd,
    )
    assert engine_module._canonical_hash({"1": "a", 1: "b"}, pd=pd) == (
        engine_module._canonical_hash({1: "b", "1": "a"}, pd=pd)
    )
    with pytest.raises(StressDependencyError, match="claves no distinguibles"):
        engine_module._canonical_hash({OpaqueKey(): [], OpaqueKey(): {}}, pd=pd)
    with pytest.raises(StressDependencyError, match="claves no distinguibles"):
        engine_module._combined_frame_hash(
            (
                pd.DataFrame(
                    {
                        "x": pd.Series(
                            [{OpaqueKey(): "left", OpaqueKey(): "right"}],
                            dtype="object",
                        )
                    }
                ),
            ),
            pd=pd,
        )
    with pytest.raises(StressDependencyError, match="claves no distinguibles"):
        engine_module._hashable_cell(
            np.array([{OpaqueKey(): "left", OpaqueKey(): "right"}], dtype=object)
        )
    assert engine_module._canonical_payload((1, Decimal("-0")), pd=pd) == {
        "__nikodym_payload_type__": "tuple",
        "value": [1, 0.0],
    }
    assert engine_module._canonical_hash({"x": pd.Timestamp("2026-01-01")}, pd=pd) != (
        engine_module._canonical_hash({"x": pd.Timestamp("2027-01-01")}, pd=pd)
    )
    assert engine_module._canonical_hash({"x": date(2026, 1, 1)}, pd=pd) != (
        engine_module._canonical_hash({"x": date(2027, 1, 1)}, pd=pd)
    )
    assert engine_module._canonical_hash({"x": time(12, 0)}, pd=pd) != (
        engine_module._canonical_hash({"x": time(13, 0)}, pd=pd)
    )
    assert engine_module._canonical_payload(Opaque(), pd=pd) == {
        "__nikodym_payload_type__": "hashable",
        "value": [
            "__opaque__",
            f"{__name__}.test_helpers_numericos_missing_e_imports.<locals>.Opaque",
        ],
    }
    bytes_payload = {"__nikodym_payload_type__": "hashable", "value": ["__bytes__", "78"]}
    assert engine_module._canonical_payload(b"x", pd=pd) == bytes_payload
    assert engine_module._canonical_payload(bytearray(b"x"), pd=pd) == bytes_payload
    assert engine_module._canonical_payload(memoryview(b"x"), pd=pd) == bytes_payload
    assert engine_module._hashable_cell({}) != engine_module._hashable_cell([])
    assert engine_module._hashable_cell([]) != engine_module._hashable_cell(())
    assert engine_module._canonical_hash({"cfg": {}}, pd=pd) != (
        engine_module._canonical_hash({"cfg": ["__mapping__", "builtins.dict", []]}, pd=pd)
    )
    assert engine_module._canonical_hash([], pd=pd) != engine_module._canonical_hash((), pd=pd)
    assert engine_module._canonical_hash(b"x", pd=pd) != (
        engine_module._canonical_hash(["__bytes__", "78"], pd=pd)
    )
    assert engine_module._canonical_hash(_lineage_ecl_multiplier_one, pd=pd) != (
        engine_module._canonical_hash(["__callable__", "sentinel"], pd=pd)
    )
    frame_hashes = {
        engine_module._combined_frame_hash(
            (pd.DataFrame({"x": pd.Series([{}], dtype="object")}),), pd=pd
        ),
        engine_module._combined_frame_hash(
            (pd.DataFrame({"x": pd.Series([[]], dtype="object")}),), pd=pd
        ),
        engine_module._combined_frame_hash(
            (pd.DataFrame({"x": pd.Series([()], dtype="object")}),), pd=pd
        ),
        engine_module._combined_frame_hash(
            (pd.DataFrame({"x": pd.Series([b"x"], dtype="object")}),), pd=pd
        ),
        engine_module._combined_frame_hash(
            (pd.DataFrame({"x": pd.Series([("__bytes__", "78")], dtype="object")}),),
            pd=pd,
        ),
        engine_module._combined_frame_hash(
            (pd.DataFrame({"x": pd.Series([_lineage_ecl_multiplier_one], dtype="object")}),),
            pd=pd,
        ),
    }
    assert len(frame_hashes) == 6
    assert engine_module._canonical_hash({"payload": b"a"}, pd=pd) != (
        engine_module._canonical_hash({"payload": b"b"}, pd=pd)
    )
    assert engine_module._canonical_hash({"arr": np.array([1.0, 2.0], dtype="<f8")}, pd=pd) == (
        engine_module._canonical_hash({"arr": np.array([1.0, 2.0], dtype=">f8")}, pd=pd)
    )
    assert engine_module._canonical_hash({"arr": np.array([1.0, 2.0])}, pd=pd) != (
        engine_module._canonical_hash({"arr": np.array([9.0, 2.0])}, pd=pd)
    )
    assert engine_module._canonical_hash(
        {"arr": np.array([{"b": {"x", "a"}}], dtype=object)},
        pd=pd,
    ) != engine_module._canonical_hash(
        {"arr": np.array([{"b": {"x", "z"}}], dtype=object)},
        pd=pd,
    )
    with monkeypatch.context() as missing_numpy:
        real_import_module = engine_module.importlib.import_module

        def fake_numpy_import(name: str) -> Any:
            if name == "numpy":
                raise ModuleNotFoundError(name)
            return real_import_module(name)

        missing_numpy.setattr(engine_module.importlib, "import_module", fake_numpy_import)
        assert engine_module._hashable_array(np.array([1.0])) is None
    with monkeypatch.context() as opaque_normalized:

        class NormalizedOpaque:
            """Objeto normalizado no serializable por JSON."""

        opaque_normalized.setattr(
            engine_module,
            "_hashable_cell",
            lambda value: NormalizedOpaque(),
        )
        assert engine_module._canonical_payload("x", pd=pd) == {
            "__type__": (
                f"{__name__}.test_helpers_numericos_missing_e_imports.<locals>.NormalizedOpaque"
            )
        }
    seed_code = (
        "from decimal import Decimal; "
        "import pandas as pd; "
        "import nikodym.stress.engine as engine; "
        "frame=pd.DataFrame({'x': pd.Series([Decimal('-0')], dtype='object'), "
        "'payload': [{'b': {'z', 'a'}, 'a': [Decimal('-0')]}]}); "
        "print(engine._combined_frame_hash((frame,), pd=pd))"
    )
    seed_env = os.environ.copy()
    seed_env["PYTHONHASHSEED"] = "1"
    hash_seed_1 = subprocess.check_output(
        [sys.executable, "-c", seed_code],
        env=seed_env,
        text=True,
    ).strip()
    seed_env["PYTHONHASHSEED"] = "2"
    hash_seed_2 = subprocess.check_output(
        [sys.executable, "-c", seed_code],
        env=seed_env,
        text=True,
    ).strip()
    assert hash_seed_1 == hash_seed_2
    term_payload = engine_module._term_structure_audit_payload(
        pd.DataFrame(
            {
                "pd_basis": ["pit"],
                "basis_state": ["pit"],
                "warning_codes": [()],
                "lgd_stress": [None],
            }
        )
    )
    assert term_payload["probability_ranges"]["lgd_stress"] is None
    no_column = pd.DataFrame({"x": [1]})
    engine_module._coerce_float_columns(no_column, columns=("missing",))
    engine_module._coerce_object_columns(no_column, columns=("missing",))
    hash_c = engine_module._combined_frame_hash(
        (pd.DataFrame({"payload": [{"b": {"x"}, "a": ["A"]}]}),),
        pd=pd,
    )
    hash_d = engine_module._combined_frame_hash(
        (pd.DataFrame({"payload": [{"a": ("A",), "b": {"x"}}]}),),
        pd=pd,
    )
    assert hash_c != hash_d
    frame_hash_int_key = engine_module._combined_frame_hash(
        (pd.DataFrame({"payload": [{1: "b"}]}),),
        pd=pd,
    )
    frame_hash_mixed_a = engine_module._combined_frame_hash(
        (pd.DataFrame({"payload": [{"1": "a", 1: "b"}]}),),
        pd=pd,
    )
    frame_hash_mixed_b = engine_module._combined_frame_hash(
        (pd.DataFrame({"payload": [{1: "b", "1": "a"}]}),),
        pd=pd,
    )
    assert frame_hash_int_key != frame_hash_mixed_a
    assert frame_hash_mixed_a == frame_hash_mixed_b
    assert engine_module._frame_warning_codes(pd.DataFrame({"x": [1]})) == ()
    assert (
        engine_module._unique_helper_column(
            "_nikodym_sort_row_id",
            taken={"_nikodym_sort_row_id", "_nikodym_sort_row_id_1"},
        )
        == "_nikodym_sort_row_id_2"
    )
    with pytest.raises(StressInputError, match=r"pandas\.DataFrame"):
        engine_module._as_dataframe(object(), pd=pd, field_name="frame")
    assert engine_module._package_version("paquete-nikodym-inexistente-xyz") == "no-disponible"

    with pytest.raises(StressInputError, match=r"\(0, 1\)"):
        engine_module._probability(0.0, field_name="p", tol=0.0, open_interval=True)
    with pytest.raises(StressInputError, match=r"\[0, 1\]"):
        engine_module._probability(2.0, field_name="p", tol=1e-12)
    assert engine_module._probability(-1e-13, field_name="p", tol=1e-12) == 0.0
    assert engine_module._probability(1e-13, field_name="p", tol=1e-12) == pytest.approx(1e-13)
    assert engine_module._probability(1.0 - 1e-13, field_name="p", tol=1e-12) == pytest.approx(
        1.0 - 1e-13
    )
    assert engine_module._probability(1.0 + 1e-13, field_name="p", tol=1e-12) == 1.0
    assert engine_module._probability(1.0, field_name="p", tol=1e-12) == 1.0
    assert engine_module._sigmoid(-1.0) == pytest.approx(0.2689414213699951)
    with pytest.raises(StressEngineError, match="Overflow"):
        engine_module._sigmoid(math.inf)
    with pytest.raises(StressEngineError, match="Probabilidad fuera de rango"):
        engine_module._sigmoid(10000.0)
    with pytest.raises(StressScenarioError, match="no negativo"):
        engine_module._non_negative_float(-1.0, field_name="severity")

    for value in (True, np.bool_(True), np.array(True), None):
        with pytest.raises(StressInputError, match="número finito"):
            engine_module._required_float(value, field_name="x")
    assert engine_module._required_bool(np.array(True), field_name="x") is True
    with pytest.raises(StressInputError, match="número finito"):
        engine_module._required_float("abc", field_name="x")
    assert engine_module._optional_float(None) is None
    with pytest.raises(StressInputError, match="NaN"):
        engine_module._clean_float(math.nan)
    for value in (True, np.bool_(True), np.array(True), None, "abc", math.inf):
        with pytest.raises(StressInputError, match="entero positivo"):
            engine_module._positive_int(value, field_name="period")
    with pytest.raises(StressInputError, match="entero positivo"):
        engine_module._positive_int(1.5, field_name="period")
    with pytest.raises(StressInputError, match="mayor o igual"):
        engine_module._positive_int(0, field_name="period")
    assert engine_module._jsonable_hashable([("__bool__", True), {"x": ("__bytes__", "78")}]) == [
        ["__bool__", True],
        {"x": ["__bytes__", "78"]},
    ]
    assert (
        engine_module._normalize_optional_forward_key(np.array("id-1"), field_name="row_id")
        == "id-1"
    )

    class NonHashableKey:
        """Objeto no hashable para claves opcionales forward."""

        __hash__ = None

    with pytest.raises(StressInputError, match="escalar"):
        engine_module._normalize_optional_forward_key(NonHashableKey(), field_name="row_id")

    class FakeBoolShapeNone:
        """Objeto tipo NumPy con dtype bool y shape ausente."""

        __module__ = "numpy"
        dtype = type("Dtype", (), {"kind": "b"})()
        shape = None

    class FakeBoolBadShape:
        """Objeto tipo NumPy con dtype bool y shape no iterable."""

        __module__ = "numpy"
        dtype = type("Dtype", (), {"kind": "b"})()
        shape = object()

    assert engine_module._is_bool_like(FakeBoolShapeNone()) is False
    assert engine_module._is_bool_like(FakeBoolBadShape()) is False
    with pytest.raises(StressInputError, match="texto no vacío"):
        engine_module._validate_non_empty_text(1, field_name="scenario")
    with pytest.raises(StressInputError, match="no puede estar vacío"):
        engine_module._validate_non_empty_text("   ", field_name="scenario")

    assert engine_module._warning_tuple(None) == ()
    assert engine_module._warning_tuple("W") == ("W",)
    assert engine_module._warning_tuple(("A", None, "")) == ("A",)
    assert engine_module._warning_tuple(7) == ("7",)
    assert engine_module._none_if_missing(None) is None
    assert engine_module._is_missing(None) is True
    assert engine_module._is_missing(pd.NA) is True
    assert engine_module._is_missing(MissingValueSentinel()) is False
    assert engine_module._sort_value(None) == ""

    real_import = engine_module.importlib.import_module

    def fake_import_module(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError(name)
        return real_import(name)

    monkeypatch.setattr(engine_module.importlib, "import_module", fake_import_module)
    with pytest.raises(StressDependencyError, match="requiere pandas"):
        engine_module._import_pandas()


def test_stubs_diferidos_y_export_lazy_import_guard() -> None:
    """Sensibilidad/reverse quedan explícitos y ``nikodym.stress`` sigue liviano."""
    cfg = _cfg(metrics=("pd_marginal",))
    engine = StressTestEngine.from_config(cfg)
    with pytest.raises(StressEngineError, match="run\\(\\.\\.\\.\\) primero"):
        engine.run_scenario(cfg.scenarios[0])
    with pytest.raises(StressEngineError, match=r"B21\.4"):
        engine.run_sensitivity(SensitivitySweepConfig(name="grid_x", factor="x", shock_value=1.0))
    with pytest.raises(ReverseStressError, match=r"B21\.5"):
        engine.run_reverse_stress(
            StressTargetConfig(
                name="pd_target",
                metric="pd_marginal",
                threshold=0.05,
                scenario_name="severe_plus",
                requires_economic_engine=False,
            ),
            ReverseStressConfig(factor="x", shock_value=1.0),
        )
    assert stress_pkg.StressTestEngine is StressTestEngine

    code = (
        "import sys, nikodym.stress; "
        "blocked=('pandas','numpy','scipy','statsmodels','nikodym.provisioning'); "
        "loaded=[m for m in blocked if m in sys.modules]; "
        "assert not loaded, loaded"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def _cfg(
    *,
    metrics: tuple[str, ...] = ("pd_marginal", "pd_cumulative"),
    shock: StressShockConfig | None = None,
    scenario: StressScenarioConfig | None = None,
    output: StressOutputConfig | None = None,
    validation: StressValidationConfig | None = None,
    require_dominates: bool = False,
) -> StressConfig:
    scenario_cfg = scenario or _scenario(
        shock=shock or StressShockConfig(factor="x", value=1.0),
        require_dominates=require_dominates,
    )
    return StressConfig(
        scenarios=(scenario_cfg,),
        output=output or StressOutputConfig(metrics=metrics),
        validation=validation
        or StressValidationConfig(
            require_dominates_forward_adverse=require_dominates,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )


def _scenario(
    *,
    shock: StressShockConfig | None = None,
    kind: str = "severe",
    require_dominates: bool = False,
) -> StressScenarioConfig:
    return StressScenarioConfig(
        name="severe_plus",
        kind=kind,  # type: ignore[arg-type]
        base_forward_scenario="severe",
        shocks=(shock or StressShockConfig(factor="x", value=1.0),),
        require_dominates_forward_adverse=require_dominates,
    )


def _relative_cfg(
    *,
    require_dominates: bool = False,
    shock_value: float = 0.5,
) -> StressConfig:
    shock = StressShockConfig(
        factor="x",
        operation="relative",
        value=shock_value,
    )
    scenario = StressScenarioConfig(
        name="relative_plus",
        shocks=(shock,),
        require_dominates_forward_adverse=require_dominates,
    )
    return StressConfig(
        scenarios=(scenario,),
        output=StressOutputConfig(metrics=("pd_marginal",)),
        validation=StressValidationConfig(
            require_dominates_forward_adverse=require_dominates,
            fail_on_falta_dato=False,
            fail_on_missing_ecl_engine=True,
        ),
    )


def _run_forward_only(
    cfg: StressConfig,
    *,
    macro: pd.DataFrame | None = None,
    term: pd.DataFrame | None = None,
    audit: InMemoryAuditSink | None = None,
) -> Any:
    term_frame = term if term is not None else _forward_term_structure([0.02])
    return StressTestEngine.from_config(cfg).run(
        forward_ecl_input=_ecl_input(term_frame),
        macro_projection=macro if macro is not None else _macro_projection(include_adverse=False),
        satellite_model=SatelliteStub(),
        forward_term_structure=term_frame,
        scenario_weighting=ScenarioWeightingStub(),
        audit=audit,
    )


def _macro_projection(
    *,
    periods: tuple[int, ...] = (1,),
    adverse: dict[int, float] | None = None,
    severe: dict[int, float] | None = None,
    include_adverse: bool = True,
) -> pd.DataFrame:
    adverse_values = adverse or {period: 1.0 for period in periods}
    severe_values = severe or {period: 0.0 for period in periods}
    scenarios = ["severe"]
    if include_adverse:
        scenarios.insert(0, "adverse")
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        for period in periods:
            projected = adverse_values[period] if scenario == "adverse" else severe_values[period]
            rows.append(
                {
                    "scenario": scenario,
                    "scenario_weight": 1.0,
                    "period": period,
                    "time_value": float(period),
                    "macro_variable": "x",
                    "projected_value": projected,
                    "model_value": 0.0,
                    "shock_value": projected,
                    "method": "test",
                    "model_id": "macro:test",
                    "is_reasonable_supportable": True,
                    "warning_codes": (),
                }
            )
    return pd.DataFrame(rows)


def _forward_term_structure(hazards: list[float]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    previous_survival = 1.0
    for period, hazard in enumerate(hazards, start=1):
        pd_marginal = previous_survival * hazard
        survival = previous_survival * (1.0 - hazard)
        pd_cumulative = 1.0 - survival
        rows.append(
            {
                "row_id": "id-1",
                "segment": "retail",
                "partition": "desarrollo",
                "source_model": "survival",
                "period": period,
                "time_value": float(period),
                "scenario": "severe",
                "scenario_weight": 1.0,
                "hazard": hazard,
                "survival": survival,
                "pd_marginal": pd_marginal,
                "pd_cumulative": pd_cumulative,
                "pd_marginal_base": pd_marginal,
                "pd_cumulative_base": pd_cumulative,
                "lgd": 0.45,
                "lgd_base": 0.45,
                "pd_basis": "pit",
                "basis_state": "pit",
                "ttc_reversion_weight": 1.0,
                "satellite_adjustment": 0.0,
                "macro_model_id": "macro:test",
                "satellite_model_id": "sat:test",
                "method": "survival",
                "pd_source": "survival",
                "warning_codes": (),
            }
        )
        previous_survival = survival
    return pd.DataFrame(rows, columns=_FORWARD_TERM_COLUMNS)


def _ecl_input(term: pd.DataFrame) -> ForwardEclInput:
    return ForwardEclInput(
        term_structure_frame=term,
        scenario_weight_frame=pd.DataFrame(
            [
                {
                    "scenario": "base",
                    "weight": 0.0,
                    "is_default": False,
                    "source": "config",
                    "description": "base",
                },
                {
                    "scenario": "adverse",
                    "weight": 0.0,
                    "is_default": False,
                    "source": "config",
                    "description": "adverse",
                },
                {
                    "scenario": "severe",
                    "weight": 1.0,
                    "is_default": False,
                    "source": "config",
                    "description": "severe",
                },
            ],
            columns=_SCENARIO_WEIGHT_COLUMNS,
        ),
        pit_consistency={"basis": "pit"},
        contract_version=FORWARD_ECL_CONTRACT_VERSION,
    )
