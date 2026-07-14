"""Tests de resultados de la orquestación ``provisioning``: DTOs puros, copias, CT-2 y máximo."""

from __future__ import annotations

import inspect
import math
import subprocess
import sys
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.provisioning.results as prov_results
from nikodym.provisioning.results import (
    ProvisionComparisonRecord,
    ProvisionComparisonSummary,
    ProvisionOrchestrationCard,
    ProvisionOrchestrationResult,
)

_UNSET = object()

# ─────────────────────────── ProvisionComparisonRecord ───────────────────────────


def test_comparison_record_golden_frozen_extra_y_reconciliacion() -> None:
    warnings = ["floor_bites"]
    record = _record(warnings=warnings)

    assert tuple(ProvisionComparisonRecord.model_fields) == (
        "cell_id",
        "level",
        "source_a",
        "source_b",
        "provision_a",
        "provision_b",
        "reported_provision",
        "binding",
        "coverage",
        "warnings",
    )
    # Golden "gana CMF" (§11): cmf=100.0 > ifrs9=60.165289 -> reported=100.0, binding=cmf.
    assert record.model_dump(mode="json") == {
        "cell_id": "commercial",
        "level": "portfolio",
        "source_a": "cmf",
        "source_b": "ifrs9",
        "provision_a": "100.00",
        "provision_b": 60.165289,
        "reported_provision": "100.00",
        "binding": "cmf",
        "coverage": "both",
        "warnings": ["floor_bites"],
    }
    # Reconciliación D-PROV-4: el dominio de cada fuente se preserva (CMF Decimal, IFRS 9 float).
    assert isinstance(record.provision_a, Decimal)
    assert isinstance(record.provision_b, float)
    assert isinstance(record.reported_provision, Decimal)
    assert record.warnings == ("floor_bites",)

    warnings.append("mutado")
    assert record.warnings == ("floor_bites",)

    with pytest.raises(ValidationError, match="frozen"):
        record.reported_provision = Decimal("1")
    with pytest.raises(ValidationError):
        _record(extra="no permitido")


def test_comparison_record_fuentes_configurables_estandar_vs_interno() -> None:
    """El registro nombra las fuentes reales: estándar vs. interno, con binding legible (SDD-28)."""
    interno_gana = _record(
        source_b="internal",
        provision_a=Decimal("1440.00000"),
        provision_b=Decimal("184000.00"),
        reported_provision=Decimal("184000.00"),
        binding="internal",
    )
    assert interno_gana.source_a == "cmf"
    assert interno_gana.source_b == "internal"
    assert interno_gana.binding == "internal"
    # Ambas fuentes son Decimal: ninguna se degrada a float al compararlas.
    assert isinstance(interno_gana.provision_a, Decimal)
    assert isinstance(interno_gana.provision_b, Decimal)

    with pytest.raises(ValidationError, match="fuentes distintas"):
        _record(source_a="cmf", source_b="cmf")
    with pytest.raises(ValidationError, match=r"source solo admite"):
        _record(source_b="basilea")


def test_comparison_record_golden_gana_ifrs9_y_empate() -> None:
    # Golden "gana IFRS 9" (SDD-17 §11): provision_b=73.0 > cmf=50.0 => reported=73.0.
    gana_ifrs9 = _record(
        provision_a=Decimal("50.0"),
        provision_b=73.0,
        reported_provision=Decimal("73.0"),
        binding="ifrs9",
    )
    assert gana_ifrs9.binding == "ifrs9"
    assert gana_ifrs9.reported_provision == Decimal("73.0")

    # Golden "empate" (SDD-17 §11): cmf == ifrs9 == 73.0 => reported=73.0, binding=tie.
    empate = _record(
        provision_a=Decimal("73.0"),
        provision_b=73.0,
        reported_provision=Decimal("73.0"),
        binding="tie",
    )
    assert empate.binding == "tie"


def test_comparison_record_normaliza_negativos_cero() -> None:
    record = _record(provision_b=-0.0, provision_a=Decimal("-0"), reported_provision=Decimal("-0"))
    assert record.provision_b == 0.0
    assert math.copysign(1.0, record.provision_b) == 1.0
    assert record.provision_a == Decimal("0")
    assert record.reported_provision == Decimal("0")


def test_comparison_record_valida_montos_y_cell_id() -> None:
    with pytest.raises(ValidationError, match="cell_id no puede estar vacío"):
        _record(cell_id="  ")
    with pytest.raises(ValidationError, match="no pueden ser negativos"):
        _record(provision_a=Decimal("-0.01"))
    with pytest.raises(ValidationError, match="no pueden ser negativos"):
        _record(reported_provision=Decimal("-0.01"))
    with pytest.raises(ValidationError, match="no pueden ser negativos"):
        _record(provision_b=-1.0)
    with pytest.raises(ValidationError, match="no pueden ser NaN ni inf"):
        _record(provision_b=float("inf"))
    with pytest.raises(ValidationError, match="números reales finitos"):
        _record(provision_b=True)
    with pytest.raises(ValueError, match="deben ser finitos"):
        prov_results._normalize_non_negative_decimal(Decimal("NaN"))


def test_comparison_record_cobertura_parcial_y_coherencia() -> None:
    # Cobertura parcial (SDD-17 §8): celda solo-CMF => reported=cmf, binding=cmf_only.
    solo_cmf = _record(
        provision_a=Decimal("438750"),
        provision_b=None,
        reported_provision=Decimal("438750"),
        binding="cmf_only",
        coverage="cmf_only",
    )
    assert solo_cmf.reported_provision == Decimal("438750")
    solo_ifrs9 = _record(
        provision_a=None,
        provision_b=42.0,
        reported_provision=Decimal("42.0"),
        binding="ifrs9_only",
        coverage="ifrs9_only",
    )
    assert solo_ifrs9.provision_b == 42.0

    with pytest.raises(ValidationError, match="coverage='both' exige provision_a y provision_b"):
        _record(provision_a=None)
    with pytest.raises(ValidationError, match=r"coverage='both' exige binding en \{cmf"):
        _record(binding="cmf_only")
    with pytest.raises(ValidationError, match="coverage='cmf_only' exige solo el monto de cmf"):
        _record(coverage="cmf_only", binding="cmf_only")
    with pytest.raises(ValidationError, match="coverage='cmf_only' exige binding='cmf_only'"):
        _record(provision_a=Decimal("10"), provision_b=None, coverage="cmf_only", binding="cmf")
    with pytest.raises(ValidationError, match="coverage='ifrs9_only' exige solo el monto de ifrs9"):
        _record(coverage="ifrs9_only", binding="ifrs9_only")
    with pytest.raises(ValidationError, match="coverage='ifrs9_only' exige binding='ifrs9_only'"):
        _record(provision_a=None, provision_b=42.0, coverage="ifrs9_only", binding="ifrs9")
    # La cobertura de una fuente que no participa en la comparación es incoherente.
    with pytest.raises(ValidationError, match="no corresponde a las fuentes declaradas"):
        _record(
            provision_a=Decimal("10"),
            provision_b=None,
            coverage="internal_only",
            binding="internal_only",
        )


# ─────────────────────────── ProvisionComparisonSummary ───────────────────────────


def test_comparison_summary_golden_frozen_y_conteos() -> None:
    summary = _summary()

    assert tuple(ProvisionComparisonSummary.model_fields) == (
        "level",
        "source_a",
        "source_b",
        "n_cells",
        "n_binding_a",
        "n_binding_b",
        "n_binding_tie",
        "total_provision_a",
        "total_provision_b",
        "total_reported_provision",
        "warnings",
    )
    assert summary.model_dump(mode="json") == {
        "level": "portfolio",
        "source_a": "cmf",
        "source_b": "ifrs9",
        "n_cells": 2,
        "n_binding_a": 2,
        "n_binding_b": 0,
        "n_binding_tie": 0,
        "total_provision_a": "150.00",
        "total_provision_b": "60.165289",
        "total_reported_provision": "150.00",
        "warnings": [],
    }

    with pytest.raises(ValidationError, match="frozen"):
        summary.n_cells = 5
    with pytest.raises(ValidationError):
        _summary(extra="no permitido")
    with pytest.raises(ValidationError):
        _summary(n_cells=-1)
    with pytest.raises(ValidationError, match="no pueden ser negativos"):
        _summary(total_reported_provision=Decimal("-0.01"))
    with pytest.raises(ValidationError, match="no puede exceder n_cells"):
        _summary(n_cells=1, n_binding_a=2)
    with pytest.raises(ValidationError, match="source solo admite"):
        _summary(source_a="basilea")


# ─────────────────────────── ProvisionOrchestrationCard ───────────────────────────


def test_orchestration_card_golden_metric_sections_y_copias() -> None:
    metric_sections: dict[str, Any] = {
        "floor_bite_ratio": {"serie": [1.0, -0.0, ("t",), float("inf")], "flag": True, "n": 2},
        "binding_by_portfolio": "texto",
    }
    card = _card(metric_sections=metric_sections)

    assert tuple(ProvisionOrchestrationCard.model_fields) == (
        "as_of_date",
        "comparison_level",
        "rule",
        "source_a",
        "source_b",
        "engines_present",
        "binding",
        "n_cells",
        "n_binding_a",
        "n_binding_b",
        "n_binding_tie",
        "total_provision_a",
        "total_provision_b",
        "total_reported_provision",
        "cmf_matrix_version",
        "ifrs9_term_structure_source",
        "internal_method",
        "regulatory_sources",
        "falta_dato",
        "metric_sections",
    )
    observed = card.metric_sections
    assert observed["floor_bite_ratio"]["serie"] == [1.0, 0.0, ("t",), None]
    assert observed["floor_bite_ratio"]["flag"] is True
    assert observed["floor_bite_ratio"]["n"] == 2
    assert observed["binding_by_portfolio"] == "texto"
    assert card.engines_present == ("cmf", "ifrs9")
    assert card.cmf_matrix_version == "cmf_b1_b3_2025_01"
    assert card.ifrs9_term_structure_source == "survival"

    metric_sections["binding_by_portfolio"] = "mutado"
    card.metric_sections["binding_by_portfolio"] = "otro"
    assert card.metric_sections["binding_by_portfolio"] == "texto"
    assert _card().metric_sections == {}
    assert _card(metric_sections=None).metric_sections == {}

    with pytest.raises(ValidationError, match="frozen"):
        card.n_cells = 9
    with pytest.raises(ValidationError):
        _card(extra="no permitido")
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])


def test_orchestration_card_dice_que_fuente_gano() -> None:
    """La card es legible: nombra la regla, las fuentes y la que resultó vinculante (SDD-28)."""
    card = _card(
        comparison_level="total",
        rule="use_internal",
        source_b="internal",
        engines_present=("cmf", "internal"),
        binding="internal",
        n_cells=1,
        n_binding_a=0,
        n_binding_b=1,
        total_provision_a=Decimal("1440.00000"),
        total_provision_b=Decimal("184000.00"),
        total_reported_provision=Decimal("184000.00"),
        ifrs9_term_structure_source=None,
        internal_method="pd_lgd",
    )
    assert card.rule == "use_internal"
    assert card.binding == "internal"
    assert card.internal_method == "pd_lgd"
    assert card.engines_present == ("cmf", "internal")


def test_orchestration_card_valida_texto_engines_y_conteos() -> None:
    sin_fuentes = _card(cmf_matrix_version=None, ifrs9_term_structure_source=None)
    assert sin_fuentes.cmf_matrix_version is None
    assert sin_fuentes.ifrs9_term_structure_source is None
    with pytest.raises(ValidationError, match="no pueden estar vacíos"):
        _card(comparison_level="   ")
    with pytest.raises(ValidationError, match="no pueden estar vacíos"):
        _card(rule="   ")
    with pytest.raises(ValidationError, match="engines_present no puede estar vacío"):
        _card(engines_present=())
    with pytest.raises(ValidationError, match="engines_present solo admite"):
        _card(engines_present=("cmf", "otro"))
    with pytest.raises(ValidationError, match="no pueden ser negativos"):
        _card(total_provision_a=Decimal("-0.01"))
    with pytest.raises(ValidationError, match="no puede exceder n_cells"):
        _card(n_cells=1, n_binding_b=2)
    with pytest.raises(ValidationError, match="source solo admite"):
        _card(source_a="basilea")
    # El método interno SÍ es una fuente válida (antes solo se admitían cmf/ifrs9).
    assert _card(source_b="internal", engines_present=("cmf", "internal")).source_b == "internal"


# ─────────────────────────── ProvisionOrchestrationResult ───────────────────────────


def test_orchestration_result_envuelve_dataframes_y_copias() -> None:
    comparison = _comparison_frame()
    summary = _summary_frame()
    result = _result(comparison=comparison, summary=summary)

    assert tuple(ProvisionOrchestrationResult.model_fields) == (
        "comparison",
        "summary",
        "records",
        "card",
        "ifrs9_term_structure",
    )
    comparison.loc[0, "reported_provision"] = Decimal("999")
    summary.loc[0, "total_reported_provision"] = Decimal("999")

    assert result.comparison is not result.comparison
    assert_frame_equal(result.comparison, _comparison_frame())
    assert_frame_equal(result.summary, _summary_frame())
    assert tuple(result.comparison.columns) == prov_results._COMPARISON_COLUMNS
    assert tuple(result.summary.columns) == prov_results._SUMMARY_COLUMNS
    assert result.records == (_record(), _record(cell_id="consumer", provision_b=0.0))
    assert result.card == _card()

    observed = result.comparison
    observed.loc[0, "reported_provision"] = Decimal("777")
    assert_frame_equal(result.comparison, _comparison_frame())

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card()
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_orchestration_result_valida_dataframes_y_paralelismo() -> None:
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(comparison="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(comparison=_comparison_frame().drop(columns=["binding"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(summary=_summary_frame().drop(columns=["warning_codes"]))
    with pytest.raises(ValidationError, match=r"debe ser un pandas\.DataFrame o None"):
        _result(ifrs9_term_structure="no es DataFrame")
    with pytest.raises(ValidationError, match="una entrada por fila de comparison"):
        _result(records=(_record(),))


def test_orchestration_result_term_structure_delega_o_none() -> None:
    curve = _ifrs9_term_structure_frame()
    result = _result(ifrs9_term_structure=curve)

    expuesta = result.term_structure()
    assert expuesta is not None
    assert_frame_equal(expuesta, _ifrs9_term_structure_frame())
    # Copia defensiva: mutar la salida no toca el DTO ni el original.
    expuesta.loc[0, "value"] = 111.0
    curve.loc[0, "value"] = 222.0
    assert_frame_equal(result.term_structure(), _ifrs9_term_structure_frame())

    solo_cmf = _result(ifrs9_term_structure=None)
    assert solo_cmf.term_structure() is None

    annotation = inspect.signature(ProvisionOrchestrationResult.term_structure).return_annotation
    assert annotation == "pandas.DataFrame | None"


def test_orchestration_result_term_structure_delega_en_ifrs9_result() -> None:
    from nikodym.provisioning.ifrs9 import IfrsProvisionResult

    ifrs9 = _ifrs9_result()
    curva_ifrs9 = ifrs9.term_structure()
    assert curva_ifrs9 is not None

    result = _result(ifrs9_term_structure=curva_ifrs9)
    assert isinstance(ifrs9, IfrsProvisionResult)
    assert_frame_equal(result.term_structure(), ifrs9.term_structure())


# ─────────────────────────── import liviano / exports ───────────────────────────


def test_provisioning_results_import_liviano_y_exports_publicos() -> None:
    code = (
        "import sys;"
        "import nikodym.provisioning;"
        "import nikodym.provisioning.results;"
        "bloqueados=[m for m in "
        "('nikodym.data','pandera','pyarrow','pandas','numpy','scipy','statsmodels',"
        "'nikodym.tracking','mlflow') if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    for nombre in (
        "ProvisionComparisonRecord",
        "ProvisionComparisonSummary",
        "ProvisionOrchestrationCard",
        "ProvisionOrchestrationResult",
    ):
        assert nombre in prov_results.__all__


# ─────────────────────────── factories ───────────────────────────


def _record(**updates: Any) -> ProvisionComparisonRecord:
    payload: dict[str, Any] = {
        "cell_id": "commercial",
        "level": "portfolio",
        "source_a": "cmf",
        "source_b": "ifrs9",
        "provision_a": Decimal("100.00"),
        "provision_b": 60.165289,
        "reported_provision": Decimal("100.00"),
        "binding": "cmf",
        "coverage": "both",
        "warnings": (),
    }
    if "extra" in updates:
        payload["extra"] = updates.pop("extra")
    payload.update(updates)
    return ProvisionComparisonRecord(**payload)


def _summary(**updates: Any) -> ProvisionComparisonSummary:
    payload: dict[str, Any] = {
        "level": "portfolio",
        "source_a": "cmf",
        "source_b": "ifrs9",
        "n_cells": 2,
        "n_binding_a": 2,
        "n_binding_b": 0,
        "n_binding_tie": 0,
        "total_provision_a": Decimal("150.00"),
        "total_provision_b": Decimal("60.165289"),
        "total_reported_provision": Decimal("150.00"),
        "warnings": (),
    }
    if "extra" in updates:
        payload["extra"] = updates.pop("extra")
    payload.update(updates)
    return ProvisionComparisonSummary(**payload)


def _card(**updates: Any) -> ProvisionOrchestrationCard:
    payload: dict[str, Any] = {
        "as_of_date": "2026-01-31",
        "comparison_level": "portfolio",
        "rule": "max",
        "source_a": "cmf",
        "source_b": "ifrs9",
        "engines_present": ("cmf", "ifrs9"),
        "binding": None,
        "n_cells": 2,
        "n_binding_a": 2,
        "n_binding_b": 0,
        "n_binding_tie": 0,
        "total_provision_a": Decimal("150.00"),
        "total_provision_b": Decimal("60.165289"),
        "total_reported_provision": Decimal("150.00"),
        "cmf_matrix_version": "cmf_b1_b3_2025_01",
        "ifrs9_term_structure_source": "survival",
        "internal_method": None,
        "regulatory_sources": ("CNC B-1 hoja 10-11", "CNC B-1 §2.1"),
        "falta_dato": (),
    }
    if "extra" in updates:
        payload["extra"] = updates.pop("extra")
    payload.update(updates)
    return ProvisionOrchestrationCard(**payload)


def _comparison_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cell_id": ["commercial", "consumer"],
            "level": ["portfolio", "portfolio"],
            "source_a": ["cmf", "cmf"],
            "source_b": ["ifrs9", "ifrs9"],
            "provision_a": [Decimal("100.00"), Decimal("50.00")],
            "provision_b": [60.165289, 0.0],
            "reported_provision": [Decimal("100.00"), Decimal("50.00")],
            "binding": ["cmf", "cmf"],
            "coverage": ["both", "both"],
            "warning_codes": [(), ()],
        }
    )


def _summary_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "level": ["portfolio"],
            "source_a": ["cmf"],
            "source_b": ["ifrs9"],
            "n_cells": [2],
            "n_binding_a": [2],
            "n_binding_b": [0],
            "n_binding_tie": [0],
            "total_provision_a": [Decimal("150.00")],
            "total_provision_b": [Decimal("60.165289")],
            "total_reported_provision": [Decimal("150.00")],
            "warning_codes": [()],
        }
    )


def _ifrs9_term_structure_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "row_id": ["loan-1", "loan-1"],
            "scenario": ["base", "base"],
            "period": [1, 2],
            "time_value": [1.0, 2.0],
            "component": ["ecl_marginal", "ecl_marginal"],
            "value": [36.0, 0.0],
        }
    )


def _result(
    *,
    comparison: Any | None = None,
    summary: Any | None = None,
    records: tuple[ProvisionComparisonRecord, ...] | None = None,
    card: ProvisionOrchestrationCard | None = None,
    ifrs9_term_structure: Any = _UNSET,
    extra: object | None = None,
) -> ProvisionOrchestrationResult:
    payload: dict[str, Any] = {
        "comparison": _comparison_frame() if comparison is None else comparison,
        "summary": _summary_frame() if summary is None else summary,
        "records": (
            (_record(), _record(cell_id="consumer", provision_b=0.0))
            if records is None
            else records
        ),
        "card": _card() if card is None else card,
        "ifrs9_term_structure": (
            _ifrs9_term_structure_frame()
            if ifrs9_term_structure is _UNSET
            else ifrs9_term_structure
        ),
    }
    if extra is not None:
        payload["extra"] = extra
    return ProvisionOrchestrationResult(**payload)


def _ifrs9_result() -> Any:
    """Construye un ``IfrsProvisionResult`` mínimo real para probar la delegación CT-2."""
    from nikodym.provisioning.ifrs9 import (
        IfrsEclRecord,
        IfrsProvisionCard,
        IfrsProvisionResult,
        IfrsStageRecord,
    )

    staging = pd.DataFrame(
        {
            "row_id": ["loan-1"],
            "portfolio": ["retail"],
            "stage": [1],
            "days_past_due": [0],
            "pd_life_current": [0.02],
            "pd_life_origination": [0.02],
            "sicr_triggers": [()],
            "low_credit_risk_exempt": [False],
            "warning_codes": [()],
        }
    )
    detail = pd.DataFrame(
        {
            "row_id": ["loan-1"],
            "portfolio": ["retail"],
            "stage": [1],
            "ead": [1000.0],
            "lgd": [0.40],
            "eir": [0.10],
            "pd_12m": [0.10],
            "pd_life": [0.10],
            "ecl_12m": [36.0],
            "ecl_lifetime": [60.0],
            "ecl_reported": [36.0],
            "scenario_weights": ['{"base": 1.0}'],
            "pd_basis": ["pit"],
            "warning_codes": [()],
        }
    )
    ecl_term_structure = pd.DataFrame(
        {
            "row_id": ["loan-1", "loan-1"],
            "scenario": ["base", "base"],
            "period": [1, 2],
            "time_value": [1.0, 2.0],
            "pd_marginal": [0.10, 0.08],
            "lgd": [0.40, 0.40],
            "ead": [1000.0, 900.0],
            "discount_factor": [0.9, 0.82],
            "ecl_marginal": [36.0, 23.6],
        }
    )
    summary = pd.DataFrame(
        {
            "portfolio": ["retail"],
            "stage": [1],
            "scenario": ["base"],
            "n_rows": [1],
            "total_ead": [1000.0],
            "total_ecl_reported": [36.0],
            "coverage_ratio": [0.036],
            "warning_codes": [()],
        }
    )
    stage_record = IfrsStageRecord(
        row_id="loan-1",
        stage=1,
        days_past_due=0,
        pd_life_current=0.02,
        pd_life_origination=0.02,
    )
    ecl_record = IfrsEclRecord(
        row_id="loan-1",
        stage=1,
        ead=1000.0,
        lgd=0.40,
        eir=0.10,
        ecl_12m=36.0,
        ecl_lifetime=60.0,
        ecl_reported=36.0,
        scenario_weights={"base": 1.0},
        pd_basis="pit",
    )
    card = IfrsProvisionCard(
        as_of_date="2026-01-31",
        term_structure_source="survival",
        pit_mode="consume_pit",
        n_rows=1,
        n_stage1=1,
        n_stage2=0,
        n_stage3=0,
        total_ead=1000.0,
        total_ecl_reported=36.0,
        scenarios=("base",),
        scenario_weights={"base": 1.0},
        dependency_versions={"pandas": "2.2.0"},
    )
    return IfrsProvisionResult(
        staging=staging,
        detail=detail,
        ecl_term_structure=ecl_term_structure,
        summary=summary,
        stage_records=(stage_record,),
        ecl_records=(ecl_record,),
        card=card,
    )
