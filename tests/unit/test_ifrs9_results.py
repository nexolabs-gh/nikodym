"""Tests de resultados de ``provisioning.ifrs9``: DTOs puros, copias, CT-2 y ``BaseEclModel``."""

from __future__ import annotations

import inspect
import math
import subprocess
import sys
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.provisioning.ifrs9.results as ifrs9_results
from nikodym.provisioning.ifrs9 import IfrsProvisioningConfig
from nikodym.provisioning.ifrs9.base import BaseEclModel
from nikodym.provisioning.ifrs9.results import (
    IfrsEclRecord,
    IfrsEclTermRecord,
    IfrsProvisionCard,
    IfrsProvisionResult,
    IfrsStageRecord,
)

# ─────────────────────────── IfrsStageRecord ───────────────────────────


def test_ifrs_stage_record_golden_frozen_extra_y_normalizacion() -> None:
    triggers = ["sicr_pd_ratio", "dpd_30"]
    record = _stage_record(pd_life_current=-0.0, sicr_triggers=triggers)

    assert tuple(IfrsStageRecord.model_fields) == (
        "row_id",
        "stage",
        "days_past_due",
        "pd_life_current",
        "pd_life_origination",
        "sicr_triggers",
        "low_credit_risk_exempt",
        "warnings",
    )
    assert record.stage == 2
    assert record.pd_life_current == 0.0
    assert math.copysign(1.0, record.pd_life_current) == 1.0
    assert record.sicr_triggers == ("sicr_pd_ratio", "dpd_30")

    triggers.append("mutado")
    assert record.sicr_triggers == ("sicr_pd_ratio", "dpd_30")

    with pytest.raises(ValidationError, match="frozen"):
        record.stage = 3
    with pytest.raises(ValidationError):
        _stage_record(extra="no permitido")
    with pytest.raises(ValidationError):
        _stage_record(stage=4)


def test_ifrs_stage_record_valida_rangos() -> None:
    vacio = _stage_record(days_past_due=None, pd_life_current=None, pd_life_origination=None)
    assert vacio.pd_life_current is None
    assert vacio.pd_life_origination is None
    with pytest.raises(ValidationError, match="days_past_due"):
        _stage_record(days_past_due=-1)
    with pytest.raises(ValidationError, match=r"pd_life_current debe estar en \[0, 1\]"):
        _stage_record(pd_life_current=1.5)
    with pytest.raises(ValidationError, match=r"pd_life_origination debe estar en \[0, 1\]"):
        _stage_record(pd_life_origination=-0.5)
    with pytest.raises(ValidationError, match="números finitos"):
        _stage_record(pd_life_current=float("inf"))


# ─────────────────────────── IfrsEclRecord ───────────────────────────


def test_ifrs_ecl_record_golden_frozen_extra_y_copias() -> None:
    weights = {"base": 0.6, "adverso": 0.4}
    record = _ecl_record(ead=-0.0, scenario_weights=weights)

    assert tuple(IfrsEclRecord.model_fields) == (
        "row_id",
        "stage",
        "ead",
        "lgd",
        "eir",
        "ecl_12m",
        "ecl_lifetime",
        "ecl_reported",
        "scenario_weights",
        "pd_basis",
        "warnings",
    )
    assert record.ead == 0.0
    assert math.copysign(1.0, record.ead) == 1.0
    assert record.scenario_weights == {"base": 0.6, "adverso": 0.4}

    weights["base"] = 0.99
    assert record.scenario_weights == {"base": 0.6, "adverso": 0.4}
    observed = record.scenario_weights
    observed["base"] = 0.11
    assert record.scenario_weights == {"base": 0.6, "adverso": 0.4}
    assert record.scenario_weights is not record.scenario_weights

    with pytest.raises(ValidationError, match="frozen"):
        record.ead = 10.0
    with pytest.raises(ValidationError):
        _ecl_record(extra="no permitido")
    with pytest.raises(ValidationError):
        _ecl_record(pd_basis="desconocido")


def test_ifrs_ecl_record_consistencia_stage_horizonte() -> None:
    stage1 = _ecl_record(stage=1, ecl_12m=12.0, ecl_lifetime=30.0, ecl_reported=12.0)
    assert stage1.ecl_reported == 12.0
    stage2 = _ecl_record(stage=2, ecl_12m=12.0, ecl_lifetime=30.0, ecl_reported=30.0)
    assert stage2.ecl_reported == 30.0

    with pytest.raises(ValidationError, match="ecl_reported debe ser ecl_12m"):
        _ecl_record(stage=1, ecl_12m=12.0, ecl_lifetime=30.0, ecl_reported=30.0)
    with pytest.raises(ValidationError, match="ecl_reported debe ser ecl_12m"):
        _ecl_record(stage=3, ecl_12m=12.0, ecl_lifetime=30.0, ecl_reported=12.0)


def test_ifrs_ecl_record_valida_rangos_y_pesos() -> None:
    with pytest.raises(ValidationError, match="ead debe ser mayor o igual a 0"):
        _ecl_record(ead=-1.0)
    with pytest.raises(ValidationError, match=r"lgd debe estar en \[0, 1\]"):
        _ecl_record(lgd=1.2)
    with pytest.raises(ValidationError, match="ecl_lifetime debe ser mayor o igual a 0"):
        _ecl_record(stage=2, ecl_lifetime=-3.0, ecl_reported=-3.0)
    with pytest.raises(ValidationError, match="números finitos"):
        _ecl_record(eir=float("nan"))
    with pytest.raises(ValidationError, match="números finitos"):
        _ecl_record(ead=True)

    with pytest.raises(ValidationError, match="no puede estar vacío"):
        _ecl_record(scenario_weights={})
    with pytest.raises(ValidationError, match="nombres de escenario no vacíos"):
        _ecl_record(scenario_weights={"  ": 1.0})
    with pytest.raises(ValidationError, match="estrictamente positivos"):
        _ecl_record(scenario_weights={"base": 0.0})
    with pytest.raises(ValidationError, match="debe sumar 1"):
        _ecl_record(scenario_weights={"base": 0.4, "adverso": 0.4})
    with pytest.raises(ValidationError, match="números finitos"):
        _ecl_record(scenario_weights={"base": float("inf")})
    with pytest.raises(ValidationError):
        _ecl_record(scenario_weights=["base", 1.0])


# ─────────────────────────── IfrsEclTermRecord ───────────────────────────


def test_ifrs_ecl_term_record_golden_frozen_extra_y_normalizacion() -> None:
    record = _term_record(ecl_marginal=-0.0)

    assert tuple(IfrsEclTermRecord.model_fields) == (
        "row_id",
        "scenario",
        "period",
        "time_value",
        "pd_marginal",
        "lgd",
        "ead",
        "discount_factor",
        "ecl_marginal",
        "warnings",
    )
    assert record.ecl_marginal == 0.0
    assert math.copysign(1.0, record.ecl_marginal) == 1.0

    with pytest.raises(ValidationError, match="frozen"):
        record.period = 2
    with pytest.raises(ValidationError):
        _term_record(extra="no permitido")
    with pytest.raises(ValidationError):
        _term_record(period=0)


def test_ifrs_ecl_term_record_valida_rangos() -> None:
    assert _term_record(discount_factor=1.0).discount_factor == 1.0
    with pytest.raises(ValidationError, match="time_value debe ser mayor o igual a 0"):
        _term_record(time_value=-0.1)
    with pytest.raises(ValidationError, match=r"pd_marginal debe estar en \[0, 1\]"):
        _term_record(pd_marginal=1.4)
    with pytest.raises(ValidationError, match=r"lgd debe estar en \[0, 1\]"):
        _term_record(lgd=-0.2)
    with pytest.raises(ValidationError, match="ead debe ser mayor o igual a 0"):
        _term_record(ead=-5.0)
    with pytest.raises(ValidationError, match=r"discount_factor debe estar en \(0, 1\]"):
        _term_record(discount_factor=0.0)
    with pytest.raises(ValidationError, match=r"discount_factor debe estar en \(0, 1\]"):
        _term_record(discount_factor=1.5)
    with pytest.raises(ValidationError, match="ecl_marginal debe ser mayor o igual a 0"):
        _term_record(ecl_marginal=-1.0)


# ─────────────────────────── IfrsProvisionCard ───────────────────────────


def test_ifrs_provision_card_golden_metric_sections_y_copias() -> None:
    metric_sections: dict[str, Any] = {
        "ecl_by_scenario": {"serie": [1.0, -0.0, ("t",), float("inf")], "flag": True, "n": 3},
        "staging_migration": "texto",
    }
    dependency_versions = {"pandas": "2.2.0"}
    card = _card(metric_sections=metric_sections, dependency_versions=dependency_versions)

    assert tuple(IfrsProvisionCard.model_fields) == (
        "as_of_date",
        "term_structure_source",
        "pit_mode",
        "n_rows",
        "n_stage1",
        "n_stage2",
        "n_stage3",
        "total_ead",
        "total_ecl_reported",
        "scenarios",
        "scenario_weights",
        "dependency_versions",
        "falta_dato",
        "metric_sections",
    )
    observed = card.metric_sections
    assert observed["ecl_by_scenario"]["serie"] == [1.0, 0.0, ("t",), None]
    assert observed["ecl_by_scenario"]["flag"] is True
    assert observed["ecl_by_scenario"]["n"] == 3
    assert observed["staging_migration"] == "texto"

    metric_sections["staging_migration"] = "mutado"
    dependency_versions["pandas"] = "9.9.9"
    card.metric_sections["staging_migration"] = "otro"
    assert card.metric_sections["staging_migration"] == "texto"
    assert card.dependency_versions == {"pandas": "2.2.0"}
    assert _card().metric_sections == {}
    assert _card(metric_sections=None).metric_sections == {}

    with pytest.raises(ValidationError, match="frozen"):
        card.n_rows = 9
    with pytest.raises(ValidationError):
        _card(extra="no permitido")
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])
    with pytest.raises(ValidationError):
        _card(dependency_versions=["no permitido"])


def test_ifrs_provision_card_valida_conteos_y_escenarios() -> None:
    with pytest.raises(ValidationError, match="no pueden estar vacíos"):
        _card(pit_mode="   ")
    with pytest.raises(ValidationError, match="total_ead debe ser mayor o igual a 0"):
        _card(total_ead=-1.0)
    with pytest.raises(ValidationError, match="total_ecl_reported debe ser mayor o igual a 0"):
        _card(total_ecl_reported=-1.0)
    with pytest.raises(ValidationError, match="debe ser igual a n_rows"):
        _card(n_rows=5, n_stage1=1, n_stage2=1, n_stage3=1)
    with pytest.raises(ValidationError, match="debe coincidir con las llaves de scenario_weights"):
        _card(scenarios=("base", "otro"), scenario_weights={"base": 1.0})
    with pytest.raises(ValidationError):
        _card(n_stage1=-1)


# ─────────────────────────── IfrsProvisionResult ───────────────────────────


def test_ifrs_provision_result_envuelve_dataframes_y_metadata() -> None:
    staging = _staging_frame()
    result = _result(staging=staging)

    assert tuple(IfrsProvisionResult.model_fields) == (
        "staging",
        "detail",
        "ecl_term_structure",
        "summary",
        "stage_records",
        "ecl_records",
        "card",
    )
    staging.loc[0, "pd_life_current"] = 0.99
    assert result.staging is not result.staging
    assert_frame_equal(result.staging, _staging_frame())
    assert tuple(result.staging.columns) == ifrs9_results._STAGING_COLUMNS
    assert tuple(result.detail.columns) == ifrs9_results._DETAIL_COLUMNS
    assert tuple(result.ecl_term_structure.columns) == ifrs9_results._ECL_TERM_STRUCTURE_COLUMNS
    assert tuple(result.summary.columns) == ifrs9_results._SUMMARY_COLUMNS
    assert result.stage_records == (_stage_record(),)
    assert result.ecl_records == (_ecl_record(),)
    assert result.card == _card()

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card()
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_ifrs_provision_result_valida_dataframes() -> None:
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(staging="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(detail=_detail_frame().drop(columns=["pd_basis"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(ecl_term_structure=_ecl_term_structure_frame().drop(columns=["ecl_marginal"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(summary=_summary_frame().drop(columns=["coverage_ratio"]))


def test_ifrs_provision_result_term_structure_larga_ct2() -> None:
    result = _result()
    long_frame = result.term_structure()

    assert long_frame is not None
    assert tuple(long_frame.columns) == ifrs9_results._TERM_STRUCTURE_OUTPUT_COLUMNS
    # 3 filas (row_id, scenario, period) por 5 componentes = 15 filas largas.
    assert len(long_frame) == 15

    # Los 5 componentes aparecen en orden canónico dentro de cada (row_id, scenario, period).
    primer_grupo = long_frame[
        (long_frame["row_id"] == "loan-1")
        & (long_frame["scenario"] == "base")
        & (long_frame["period"] == 1)
    ]
    assert list(primer_grupo["component"]) == list(ifrs9_results._ECL_TERM_COMPONENTS)
    valores = dict(zip(primer_grupo["component"], primer_grupo["value"], strict=True))
    assert valores == {
        "pd_marginal": 0.10,
        "lgd": 0.40,
        "ead": 1000.0,
        "discount_factor": 0.9,
        "ecl_marginal": 36.0,
    }

    # ``-0.0`` publicado como ``0.0`` en la forma larga.
    cero = long_frame[
        (long_frame["row_id"] == "loan-2") & (long_frame["component"] == "ecl_marginal")
    ]
    assert cero["value"].iloc[0] == 0.0
    assert math.copysign(1.0, cero["value"].iloc[0]) == 1.0

    annotation = inspect.signature(IfrsProvisionResult.term_structure).return_annotation
    assert annotation == "pandas.DataFrame | None"


# ─────────────────────────── BaseEclModel (Protocol) ───────────────────────────


class _ConformingEclModel:
    """Motor mínimo que cumple el contrato ``BaseEclModel``."""

    config_cls = IfrsProvisioningConfig

    @classmethod
    def from_config(cls, cfg: IfrsProvisioningConfig) -> _ConformingEclModel:
        return cls()

    def calculate(
        self,
        frame: Any,
        *,
        term_structure: Any,
        calibrated_pd: Any = None,
        as_of_date: str,
        audit: Any = None,
    ) -> Any:
        return None


class _NonConformingEclModel:
    """Le falta ``calculate``: no cumple el contrato."""

    config_cls = IfrsProvisioningConfig

    @classmethod
    def from_config(cls, cfg: IfrsProvisioningConfig) -> _NonConformingEclModel:
        return cls()


def test_base_ecl_model_runtime_checkable() -> None:
    assert isinstance(_ConformingEclModel(), BaseEclModel)
    assert not isinstance(_NonConformingEclModel(), BaseEclModel)
    assert _ConformingEclModel.config_cls is IfrsProvisioningConfig


# ─────────────────────────── import liviano / exports ───────────────────────────


def test_ifrs9_results_import_liviano_y_exports_publicos() -> None:
    code = (
        "import sys;"
        "import nikodym.provisioning.ifrs9.results;"
        "import nikodym.provisioning.ifrs9.base;"
        "bloqueados=[m for m in "
        "('nikodym.data','pandera','pyarrow','pandas','numpy','scipy','statsmodels',"
        "'nikodym.tracking','mlflow') if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    for nombre in (
        "IfrsStageRecord",
        "IfrsEclRecord",
        "IfrsEclTermRecord",
        "IfrsProvisionCard",
        "IfrsProvisionResult",
    ):
        assert nombre in ifrs9_results.__all__


# ─────────────────────────── factories ───────────────────────────


def _stage_record(**updates: Any) -> IfrsStageRecord:
    payload: dict[str, Any] = {
        "row_id": "loan-1",
        "stage": 2,
        "days_past_due": 35,
        "pd_life_current": 0.11,
        "pd_life_origination": 0.05,
        "sicr_triggers": ("sicr_pd_ratio",),
        "low_credit_risk_exempt": False,
        "warnings": (),
    }
    if "extra" in updates:
        payload["extra"] = updates.pop("extra")
    payload.update(updates)
    return IfrsStageRecord(**payload)


def _ecl_record(**updates: Any) -> IfrsEclRecord:
    payload: dict[str, Any] = {
        "row_id": "loan-1",
        "stage": 1,
        "ead": 1000.0,
        "lgd": 0.40,
        "eir": 0.10,
        "ecl_12m": 36.0,
        "ecl_lifetime": 60.0,
        "ecl_reported": 36.0,
        "scenario_weights": {"base": 1.0},
        "pd_basis": "pit",
        "warnings": (),
    }
    if "extra" in updates:
        payload["extra"] = updates.pop("extra")
    payload.update(updates)
    return IfrsEclRecord(**payload)


def _term_record(**updates: Any) -> IfrsEclTermRecord:
    payload: dict[str, Any] = {
        "row_id": "loan-1",
        "scenario": "base",
        "period": 1,
        "time_value": 1.0,
        "pd_marginal": 0.10,
        "lgd": 0.40,
        "ead": 1000.0,
        "discount_factor": 0.9,
        "ecl_marginal": 36.0,
        "warnings": (),
    }
    if "extra" in updates:
        payload["extra"] = updates.pop("extra")
    payload.update(updates)
    return IfrsEclTermRecord(**payload)


def _card(**updates: Any) -> IfrsProvisionCard:
    payload: dict[str, Any] = {
        "as_of_date": "2026-01-31",
        "term_structure_source": "survival",
        "pit_mode": "consume_pit",
        "n_rows": 2,
        "n_stage1": 1,
        "n_stage2": 1,
        "n_stage3": 0,
        "total_ead": 1900.0,
        "total_ecl_reported": 96.0,
        "scenarios": ("base",),
        "scenario_weights": {"base": 1.0},
        "dependency_versions": {"pandas": "2.2.0"},
        "falta_dato": (),
    }
    if "extra" in updates:
        payload["extra"] = updates.pop("extra")
    payload.update(updates)
    return IfrsProvisionCard(**payload)


def _staging_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "row_id": ["loan-1", "loan-2"],
            "portfolio": ["retail", "retail"],
            "stage": [2, 1],
            "days_past_due": [35, 0],
            "pd_life_current": [0.11, 0.02],
            "pd_life_origination": [0.05, 0.02],
            "sicr_triggers": [("sicr_pd_ratio",), ()],
            "low_credit_risk_exempt": [False, False],
            "warning_codes": [(), ()],
        }
    )


def _detail_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "row_id": ["loan-1", "loan-2"],
            "portfolio": ["retail", "retail"],
            "stage": [2, 1],
            "ead": [1000.0, 900.0],
            "lgd": [0.40, 0.40],
            "eir": [0.10, 0.10],
            "pd_12m": [0.10, 0.02],
            "pd_life": [0.23, 0.02],
            "ecl_12m": [36.0, 7.2],
            "ecl_lifetime": [60.0, 7.2],
            "ecl_reported": [60.0, 7.2],
            "scenario_weights": ['{"base": 1.0}', '{"base": 1.0}'],
            "pd_basis": ["pit", "pit"],
            "warning_codes": [(), ()],
        }
    )


def _ecl_term_structure_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "row_id": ["loan-1", "loan-1", "loan-2"],
            "scenario": ["base", "base", "base"],
            "period": [1, 2, 1],
            "time_value": [1.0, 2.0, 1.0],
            "pd_marginal": [0.10, 0.08, 0.02],
            "lgd": [0.40, 0.40, 0.40],
            "ead": [1000.0, 900.0, 900.0],
            "discount_factor": [0.9, 0.82, 0.9],
            "ecl_marginal": [36.0, 23.6, -0.0],
        }
    )


def _summary_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "portfolio": ["retail", "retail"],
            "stage": [1, 2],
            "scenario": ["base", "base"],
            "n_rows": [1, 1],
            "total_ead": [900.0, 1000.0],
            "total_ecl_reported": [7.2, 60.0],
            "coverage_ratio": [0.008, 0.06],
            "warning_codes": [(), ()],
        }
    )


def _result(
    *,
    staging: Any | None = None,
    detail: Any | None = None,
    ecl_term_structure: Any | None = None,
    summary: Any | None = None,
    extra: object | None = None,
) -> IfrsProvisionResult:
    payload: dict[str, Any] = {
        "staging": _staging_frame() if staging is None else staging,
        "detail": _detail_frame() if detail is None else detail,
        "ecl_term_structure": (
            _ecl_term_structure_frame() if ecl_term_structure is None else ecl_term_structure
        ),
        "summary": _summary_frame() if summary is None else summary,
        "stage_records": (_stage_record(),),
        "ecl_records": (_ecl_record(),),
        "card": _card(),
    }
    if extra is not None:
        payload["extra"] = extra
    return IfrsProvisionResult(**payload)
