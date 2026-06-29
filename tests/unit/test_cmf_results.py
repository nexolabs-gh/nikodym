"""Tests de resultados de ``provisioning.cmf``: DTOs puros, copias y CT-2."""

from __future__ import annotations

import inspect
import math
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.provisioning.cmf.results as cmf_results
from nikodym.provisioning.cmf.matrices import CmfMatrixBundle, load_cmf_matrices
from nikodym.provisioning.cmf.results import (
    CmfPortfolioSummary,
    CmfProvisionCard,
    CmfProvisionRecord,
    CmfProvisionResult,
)


@dataclass(frozen=True)
class MatrixConfig:
    """Config estructural mínima compatible con ``CmfMatrixConfigLike``."""

    active_version: str = "cmf_b1_b3_2025_01"
    require_verified_rows: bool = True
    fail_on_source_mismatch: bool = True


def test_cmf_provision_record_golden_frozen_extra_y_copias() -> None:
    warnings = ["contingent_b3_override"]
    record = _record(
        direct_exposure_amount=Decimal("-0"),
        pd_source_value=Decimal("-0"),
        warnings=warnings,
    )

    assert tuple(CmfProvisionRecord.model_fields) == (
        "row_id",
        "portfolio",
        "method",
        "exposure_amount",
        "direct_exposure_amount",
        "contingent_exposure_amount",
        "pi_percent",
        "pdi_percent",
        "pe_percent",
        "provision_amount",
        "matrix_id",
        "matrix_row_id",
        "cmf_category",
        "pd_source_value",
        "guarantee_treatment",
        "warnings",
    )
    assert record.model_dump(mode="json") == {
        "row_id": "loan-001",
        "portfolio": "commercial_individual",
        "method": "standard_b1",
        "exposure_amount": "125000.50",
        "direct_exposure_amount": "0",
        "contingent_exposure_amount": "25000.00",
        "pi_percent": "0.04",
        "pdi_percent": "90.0",
        "pe_percent": "0.03600",
        "provision_amount": "45.00018",
        "matrix_id": "commercial_individual_performing_v2014",
        "matrix_row_id": "A1",
        "cmf_category": "A1",
        "pd_source_value": "0",
        "guarantee_treatment": "none",
        "warnings": ["contingent_b3_override"],
    }
    assert record.warnings == ("contingent_b3_override",)

    warnings.append("mutado")
    assert record.warnings == ("contingent_b3_override",)

    with pytest.raises(ValidationError, match="frozen"):
        record.provision_amount = Decimal("99")
    with pytest.raises(ValidationError):
        _record(extra="no permitido")
    with pytest.raises(ValidationError, match="no pueden ser negativos"):
        _record(exposure_amount=Decimal("-0.01"))
    with pytest.raises(ValidationError, match="finite number"):
        _record(pe_percent=Decimal("NaN"))
    with pytest.raises(ValueError, match="deben ser Decimal finitos"):
        cmf_results._normalize_non_negative_decimal(Decimal("NaN"))


def test_cmf_portfolio_summary_golden_frozen_extra_y_decimal() -> None:
    summary = _portfolio_summary(total_exposure_amount=Decimal("-0"))

    assert tuple(CmfPortfolioSummary.model_fields) == (
        "portfolio",
        "n_rows",
        "total_exposure_amount",
        "total_provision_amount",
        "weighted_pe_percent",
        "warnings",
    )
    assert summary.model_dump(mode="json") == {
        "portfolio": "commercial_individual",
        "n_rows": 2,
        "total_exposure_amount": "0",
        "total_provision_amount": "90.00036",
        "weighted_pe_percent": "0.03600",
        "warnings": ["sin_brechas"],
    }

    with pytest.raises(ValidationError, match="frozen"):
        summary.n_rows = 3
    with pytest.raises(ValidationError):
        _portfolio_summary(extra="no permitido")
    with pytest.raises(ValidationError):
        _portfolio_summary(n_rows=-1)


def test_cmf_provision_card_golden_metric_sections_default_y_copias() -> None:
    metric_sections: dict[str, Any] = {
        "zeta": {"serie": [2, {"b": "segundo", "a": "primero"}]},
        "alfa": {"valor": 1, "flags": ("ok",)},
    }
    card = _card(metric_sections=metric_sections)

    assert tuple(CmfProvisionCard.model_fields) == (
        "matrix_version",
        "as_of_date",
        "n_rows",
        "total_exposure_amount",
        "total_provision_amount",
        "portfolios",
        "regulatory_sources",
        "metric_sections",
    )
    assert card.model_dump(mode="json") == {
        "matrix_version": "cmf_b1_b3_2025_01",
        "as_of_date": "2026-01-31",
        "n_rows": 2,
        "total_exposure_amount": "250001.00",
        "total_provision_amount": "90.00036",
        "portfolios": [_portfolio_summary().model_dump(mode="json")],
        "regulatory_sources": ["CNC B-1 §2.1", "CNC B-3 §3"],
        "metric_sections": {
            "zeta": {"serie": [2, {"b": "segundo", "a": "primero"}]},
            "alfa": {"valor": 1, "flags": ["ok"]},
        },
    }
    dumped_metric_sections = card.model_dump(mode="json")["metric_sections"]
    assert list(dumped_metric_sections) == ["zeta", "alfa"]
    assert list(dumped_metric_sections["zeta"]["serie"][1]) == ["b", "a"]
    assert list(dumped_metric_sections["alfa"]) == ["valor", "flags"]
    assert _card().metric_sections == {}
    assert _card(metric_sections=None).metric_sections == {}
    observed_metric_sections = card.metric_sections
    assert list(observed_metric_sections) == ["zeta", "alfa"]
    assert list(observed_metric_sections["zeta"]["serie"][1]) == ["b", "a"]
    assert list(observed_metric_sections["alfa"]) == ["valor", "flags"]

    metric_sections["alfa"]["valor"] = 99
    card.metric_sections["alfa"]["valor"] = 88
    assert card.metric_sections["alfa"]["valor"] == 1

    with pytest.raises(ValidationError, match="frozen"):
        card.n_rows = 3
    with pytest.raises(ValidationError):
        _card(extra="no permitido")
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])
    with pytest.raises(ValidationError):
        _card(n_rows=-1)


def test_cmf_provision_result_envuelve_dataframes_y_term_structure() -> None:
    detail = _detail_frame()
    summary = _summary_frame()
    result = _result(detail=detail, summary=summary)

    detail.loc["loan-001", "provision_amount"] = 99.0
    summary.loc["commercial_individual|standard_b1|A1", "total_provision_amount"] = 99.0
    observed_detail = result.detail
    observed_summary = result.summary

    assert result.detail is not result.detail
    assert result.summary is not result.summary
    assert_frame_equal(observed_detail, _normalized_detail_frame())
    assert_frame_equal(observed_summary, _normalized_summary_frame())
    assert tuple(observed_detail.columns) == (
        "portfolio",
        "method",
        "cmf_category",
        "matrix_id",
        "matrix_row_id",
        "direct_exposure_amount",
        "contingent_exposure_amount",
        "exposure_amount",
        "pd_source_value",
        "pi_percent",
        "pdi_percent",
        "pe_percent",
        "provision_amount",
        "guarantee_treatment",
        "ccf_percent",
        "warning_codes",
        "source_reference",
        "matrix_version",
    )
    assert tuple(observed_summary.columns) == (
        "portfolio",
        "method",
        "cmf_category",
        "n_rows",
        "total_exposure_amount",
        "total_provision_amount",
        "weighted_pe_percent",
        "matrix_version",
        "warning_codes",
    )
    assert math.copysign(1.0, observed_detail.loc["loan-001", "pd_source_value"]) == 1.0
    assert result.records == (_record(),)
    assert result.card == _card()
    assert isinstance(result.matrix_bundle, CmfMatrixBundle)
    assert result.term_structure() is None

    annotation = inspect.signature(CmfProvisionResult.term_structure).return_annotation
    assert annotation == "pandas.DataFrame | None"

    observed_detail.loc["loan-001", "provision_amount"] = 77.0
    observed_summary.loc["commercial_individual|standard_b1|A1", "total_provision_amount"] = 77.0
    assert_frame_equal(result.detail, _normalized_detail_frame())
    assert_frame_equal(result.summary, _normalized_summary_frame())

    with pytest.raises(ValidationError, match="frozen"):
        result.card = _card(n_rows=3)
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_cmf_provision_result_valida_dataframes() -> None:
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(detail="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(detail=_detail_frame().drop(columns=["matrix_version"]))
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(summary=_summary_frame().drop(columns=["warning_codes"]))


def test_cmf_results_import_liviano_y_exports_publicos() -> None:
    code = (
        "import sys;"
        "import nikodym.provisioning.cmf.results;"
        "blocked=[m for m in "
        "('nikodym.data','pandera','pyarrow','pandas','nikodym.tracking','mlflow') "
        "if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert "CmfProvisionRecord" in cmf_results.__all__
    assert "CmfPortfolioSummary" in cmf_results.__all__
    assert "CmfProvisionCard" in cmf_results.__all__
    assert "CmfProvisionResult" in cmf_results.__all__


def _record(**updates: Any) -> CmfProvisionRecord:
    payload: dict[str, Any] = {
        "row_id": "loan-001",
        "portfolio": "commercial_individual",
        "method": "standard_b1",
        "exposure_amount": Decimal("125000.50"),
        "direct_exposure_amount": Decimal("100000.50"),
        "contingent_exposure_amount": Decimal("25000.00"),
        "pi_percent": Decimal("0.04"),
        "pdi_percent": Decimal("90.0"),
        "pe_percent": Decimal("0.03600"),
        "provision_amount": Decimal("45.00018"),
        "matrix_id": "commercial_individual_performing_v2014",
        "matrix_row_id": "A1",
        "cmf_category": "A1",
        "pd_source_value": None,
        "guarantee_treatment": "none",
        "warnings": (),
    }
    payload.update(updates)
    return CmfProvisionRecord(**payload)


def _portfolio_summary(**updates: Any) -> CmfPortfolioSummary:
    payload: dict[str, Any] = {
        "portfolio": "commercial_individual",
        "n_rows": 2,
        "total_exposure_amount": Decimal("250001.00"),
        "total_provision_amount": Decimal("90.00036"),
        "weighted_pe_percent": Decimal("0.03600"),
        "warnings": ("sin_brechas",),
    }
    payload.update(updates)
    return CmfPortfolioSummary(**payload)


def _card(**updates: Any) -> CmfProvisionCard:
    payload: dict[str, Any] = {
        "matrix_version": "cmf_b1_b3_2025_01",
        "as_of_date": "2026-01-31",
        "n_rows": 2,
        "total_exposure_amount": Decimal("250001.00"),
        "total_provision_amount": Decimal("90.00036"),
        "portfolios": (_portfolio_summary(),),
        "regulatory_sources": ("CNC B-1 §2.1", "CNC B-3 §3"),
    }
    payload.update(updates)
    return CmfProvisionCard(**payload)


def _result(
    *,
    detail: Any | None = None,
    summary: Any | None = None,
    records: tuple[CmfProvisionRecord, ...] | None = None,
    card: CmfProvisionCard | None = None,
    matrix_bundle: CmfMatrixBundle | None = None,
    extra: object | None = None,
) -> CmfProvisionResult:
    payload: dict[str, Any] = {
        "detail": _detail_frame() if detail is None else detail,
        "summary": _summary_frame() if summary is None else summary,
        "records": (_record(),) if records is None else records,
        "card": _card() if card is None else card,
        "matrix_bundle": _load_bundle() if matrix_bundle is None else matrix_bundle,
    }
    if extra is not None:
        payload["extra"] = extra
    return CmfProvisionResult(**payload)


def _detail_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "portfolio": ["commercial_individual"],
            "method": ["standard_b1"],
            "cmf_category": ["A1"],
            "matrix_id": ["commercial_individual_performing_v2014"],
            "matrix_row_id": ["A1"],
            "direct_exposure_amount": [100000.50],
            "contingent_exposure_amount": [25000.00],
            "exposure_amount": [125000.50],
            "pd_source_value": [-0.0],
            "pi_percent": [0.04],
            "pdi_percent": [90.0],
            "pe_percent": [0.03600],
            "provision_amount": [45.00018],
            "guarantee_treatment": ["none"],
            "ccf_percent": [100.0],
            "warning_codes": [()],
            "source_reference": ["docs/normativa_cmf_parametros.md §1.1"],
            "matrix_version": ["cmf_b1_b3_2025_01"],
        },
        index=pd.Index(["loan-001"], name="row_id"),
    )


def _summary_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "portfolio": ["commercial_individual"],
            "method": ["standard_b1"],
            "cmf_category": ["A1"],
            "n_rows": [2],
            "total_exposure_amount": [250001.00],
            "total_provision_amount": [90.00036],
            "weighted_pe_percent": [0.03600],
            "matrix_version": ["cmf_b1_b3_2025_01"],
            "warning_codes": [("sin_brechas",)],
        },
        index=pd.Index(["commercial_individual|standard_b1|A1"], name="summary_id"),
    )


def _normalized_detail_frame() -> pd.DataFrame:
    return _normalize_frame(_detail_frame())


def _normalized_summary_frame() -> pd.DataFrame:
    return _normalize_frame(_summary_frame())


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    for column in normalized.select_dtypes(include=["float"]).columns:
        normalized[column] = normalized[column].mask(normalized[column] == 0.0, 0.0)
    return normalized


def _load_bundle() -> CmfMatrixBundle:
    return load_cmf_matrices(MatrixConfig())
