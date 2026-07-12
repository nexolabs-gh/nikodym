"""Tests de resultados de ``report``: DTOs puros, copias y lazy exports."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.report as report_pkg
import nikodym.report.results as report_results
from nikodym.core.lineage import LineageBundle
from nikodym.report.results import (
    AiNarrationBlock,
    ReportInputBundle,
    ReportManifest,
    ReportResult,
    ReportSection,
)


def test_report_section_golden_ct2_copias_frozen_y_extra() -> None:
    metric_sections: dict[str, Any] = {
        "performance": {
            "metrics": {"auc": {"holdout": 0.74321}, "ks": {"holdout": 0.31234}},
            "flags": ["ok", {"source": "performance"}],
        }
    }
    payload: dict[str, Any] = {
        "summary": {"n_total": 1_000},
        "items": ("score", {"points": [10, 20]}),
    }
    section = _section(payload=payload, metric_sections=metric_sections)

    # Los campos de estructura del documento son ADITIVOS y con default: una sección construida con
    # el contrato previo (una card del pipeline) sigue validando sin tocarla.
    assert tuple(ReportSection.model_fields) == (
        "id",
        "title",
        "status",
        "source_domain",
        "source_key",
        "payload",
        "metric_sections",
        "kind",
        "level",
        "number",
        "body",
        "placeholder",
    )
    assert section.kind == "data"
    assert section.level == 1
    assert section.number == ""
    assert section.body == ()
    assert section.placeholder is None
    assert section.model_dump(mode="json") == {
        "id": "performance",
        "title": "Desempeño",
        "status": "included",
        "source_domain": "performance",
        "source_key": "card",
        "kind": "data",
        "level": 1,
        "number": "",
        "body": [],
        "placeholder": None,
        "payload": {
            "summary": {"n_total": 1_000},
            "items": ["score", {"points": [10, 20]}],
        },
        "metric_sections": {
            "performance": {
                "metrics": {"auc": {"holdout": 0.74321}, "ks": {"holdout": 0.31234}},
                "flags": ["ok", {"source": "performance"}],
            }
        },
    }
    assert section.metric_sections["performance"]["metrics"]["auc"]["holdout"] == 0.74321
    assert "auc" not in section.metric_sections

    payload["summary"]["n_total"] = 99
    metric_sections["performance"]["metrics"]["auc"]["holdout"] = 99.0
    section.payload["summary"]["n_total"] = 88
    section.metric_sections["performance"]["metrics"]["auc"]["holdout"] = 88.0

    assert section.payload["summary"]["n_total"] == 1_000
    assert section.metric_sections["performance"]["metrics"]["auc"]["holdout"] == 0.74321

    with pytest.raises(ValidationError, match="frozen"):
        section.title = "mutado"
    with pytest.raises(ValidationError):
        _section(extra="no permitido")
    with pytest.raises(ValidationError):
        _section(status="unknown")


def test_report_input_bundle_golden_copias_frozen_y_extra() -> None:
    frame = _table()
    cards: dict[str, Any] = {"performance": {"auc": 0.74321}}
    figures: dict[str, Any] = {"roc": {"kind": "line", "points": [0.0, 1.0]}}
    section = _section()
    bundle = _bundle(cards=cards, tables={"performance_table": frame}, figures=figures)

    assert tuple(ReportInputBundle.model_fields) == (
        "lineage",
        "cards",
        "tables",
        "figures",
        "sections",
        "missing_sections",
        "pipeline_params",
    )
    assert bundle.pipeline_params == {}
    assert bundle.lineage == _lineage()
    assert bundle.cards == {"performance": {"auc": 0.74321}}
    assert_frame_equal(bundle.tables["performance_table"], _table())
    assert bundle.figures == {"roc": {"kind": "line", "points": [0.0, 1.0]}}
    assert bundle.sections == (section,)
    assert bundle.missing_sections == ()

    cards["performance"]["auc"] = 99.0
    frame.at[0, "ks"] = 99.0
    figures["roc"]["points"][0] = 99.0
    bundle.cards["performance"]["auc"] = 88.0
    returned_frame = bundle.tables["performance_table"]
    returned_frame.at[0, "ks"] = 88.0
    bundle.figures["roc"]["points"][0] = 88.0

    assert bundle.cards == {"performance": {"auc": 0.74321}}
    assert_frame_equal(bundle.tables["performance_table"], _table())
    assert bundle.figures == {"roc": {"kind": "line", "points": [0.0, 1.0]}}

    with pytest.raises(ValidationError, match="frozen"):
        bundle.missing_sections = ("model",)
    with pytest.raises(ValidationError):
        _bundle(extra="no permitido")
    with pytest.raises(ValidationError):
        _bundle(cards=[])


def test_ai_narration_block_golden_frozen_y_extra() -> None:
    block = _ai_block()

    assert tuple(AiNarrationBlock.model_fields) == (
        "section_id",
        "text",
        "provider",
        "model",
        "generated",
        "prompt_hash",
        "input_payload_hash",
        "warning",
    )
    assert block.model_dump(mode="json") == {
        "section_id": "performance",
        "text": "El desempeño se mantiene sobre umbral.",
        "provider": "none",
        "model": "rule_based_v1",
        "generated": False,
        "prompt_hash": "0" * 64,
        "input_payload_hash": "1" * 64,
        "warning": None,
    }

    with pytest.raises(ValidationError, match="frozen"):
        block.text = "mutado"
    with pytest.raises(ValidationError):
        _ai_block(extra="no permitido")


def test_report_manifest_golden_formato_estado_frozen_y_extra() -> None:
    section = _section()
    manifest = _manifest(sections=(section,))

    assert tuple(ReportManifest.model_fields) == (
        "report_id",
        "title",
        "created_from_lineage_at",
        "template_id",
        "template_version",
        "output_format",
        "path",
        "sha256",
        "deterministic",
        "ai_enabled",
        "ai_used",
        "sections",
    )
    assert manifest.model_dump(mode="json") == {
        "report_id": "report-001",
        "title": "Reporte scorecard",
        "created_from_lineage_at": "2026-06-24T09:30:00+00:00",
        "template_id": "scorecard_basic_v1",
        "template_version": "1.0.0",
        "output_format": "html",
        "path": "reports/scorecard_report.html",
        "sha256": "2" * 64,
        "deterministic": True,
        "ai_enabled": False,
        "ai_used": False,
        "sections": [section.model_dump(mode="json")],
    }

    with pytest.raises(ValidationError, match="frozen"):
        manifest.sha256 = "mutado"
    with pytest.raises(ValidationError):
        _manifest(extra="no permitido")
    with pytest.raises(ValidationError):
        _manifest(output_format="xml")


def test_report_result_golden_copias_frozen_y_extra() -> None:
    data_exports = {"performance_table": "reports/performance_table.csv"}
    ai_block = _ai_block()
    result = _result(data_exports=data_exports, ai_blocks=(ai_block,))

    assert tuple(ReportResult.model_fields) == (
        "manifest",
        "input_bundle",
        "html_path",
        "pdf_path",
        "md_path",  # la fuente editable (.qmd), junto al resto de rutas publicadas
        "docx_path",
        "data_exports",
        "ai_blocks",
    )
    assert result.manifest == _manifest()
    expected_bundle = _bundle()
    assert result.input_bundle.lineage == expected_bundle.lineage
    assert result.input_bundle.cards == expected_bundle.cards
    assert_frame_equal(
        result.input_bundle.tables["performance_table"],
        expected_bundle.tables["performance_table"],
    )
    assert result.input_bundle.figures == expected_bundle.figures
    assert result.input_bundle.sections == expected_bundle.sections
    assert result.input_bundle.missing_sections == expected_bundle.missing_sections
    assert result.html_path == "reports/scorecard_report.html"
    assert result.pdf_path is None
    assert result.docx_path is None
    assert result.data_exports == {"performance_table": "reports/performance_table.csv"}
    assert result.ai_blocks == (ai_block,)

    data_exports["performance_table"] = "mutado.csv"
    result.data_exports["performance_table"] = "mutado.csv"
    assert result.data_exports == {"performance_table": "reports/performance_table.csv"}

    with pytest.raises(ValidationError, match="frozen"):
        result.html_path = "mutado.html"
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_report_results_lazy_exports_y_nucleo_liviano_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.core;"
        "blocked=[m for m in ('matplotlib','plotly','anthropic','jinja2') if m in sys.modules];"
        "assert not blocked, blocked;"
        "import nikodym.report as report;"
        "blocked=[m for m in ('matplotlib','plotly','anthropic','jinja2','pandas') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "loaded=[getattr(report, name).__name__ for name in "
        "('ReportSection','ReportInputBundle','AiNarrationBlock','ReportManifest',"
        "'ReportResult')];"
        "assert loaded == ['ReportSection','ReportInputBundle','AiNarrationBlock',"
        "'ReportManifest','ReportResult'];"
        "blocked=[m for m in ('matplotlib','plotly','anthropic','jinja2','pandas') "
        "if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_results_module_y_paquete_exponen_aliases_publicos() -> None:
    assert report_pkg.ReportSection is ReportSection
    assert report_pkg.ReportInputBundle is ReportInputBundle
    assert report_pkg.AiNarrationBlock is AiNarrationBlock
    assert report_pkg.ReportManifest is ReportManifest
    assert report_pkg.ReportResult is ReportResult
    assert "ReportSection" in report_results.__all__
    assert "ReportInputBundle" in report_results.__all__
    assert "AiNarrationBlock" in report_results.__all__
    assert "ReportManifest" in report_results.__all__
    assert "ReportResult" in report_results.__all__
    missing_name = "NoExiste"
    with pytest.raises(AttributeError, match="NoExiste"):
        getattr(report_pkg, missing_name)


def _lineage() -> LineageBundle:
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123",
        config_hash="cfg123",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "0.1.0"},
        determinism_caveats=[],
        created_at=datetime(2026, 6, 24, 9, 30, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _section(**updates: Any) -> ReportSection:
    payload: dict[str, Any] = {
        "id": "performance",
        "title": "Desempeño",
        "status": "included",
        "source_domain": "performance",
        "source_key": "card",
        "payload": {"summary": {"n_total": 1_000}},
        "metric_sections": {"performance": {"ks": {"holdout": 0.31234}}},
    }
    payload.update(updates)
    return ReportSection(**payload)


def _table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["holdout"],
            "auc": [0.74321],
            "ks": [0.31234],
        }
    )


def _bundle(**updates: Any) -> ReportInputBundle:
    payload: dict[str, Any] = {
        "lineage": _lineage(),
        "cards": {"performance": {"auc": 0.74321}},
        "tables": {"performance_table": _table()},
        "figures": {"roc": {"kind": "line", "points": [0.0, 1.0]}},
        "sections": (_section(),),
        "missing_sections": (),
    }
    payload.update(updates)
    return ReportInputBundle(**payload)


def _ai_block(**updates: Any) -> AiNarrationBlock:
    payload: dict[str, Any] = {
        "section_id": "performance",
        "text": "El desempeño se mantiene sobre umbral.",
        "provider": "none",
        "model": "rule_based_v1",
        "generated": False,
        "prompt_hash": "0" * 64,
        "input_payload_hash": "1" * 64,
        "warning": None,
    }
    payload.update(updates)
    return AiNarrationBlock(**payload)


def _manifest(**updates: Any) -> ReportManifest:
    payload: dict[str, Any] = {
        "report_id": "report-001",
        "title": "Reporte scorecard",
        "created_from_lineage_at": "2026-06-24T09:30:00+00:00",
        "template_id": "scorecard_basic_v1",
        "template_version": "1.0.0",
        "output_format": "html",
        "path": "reports/scorecard_report.html",
        "sha256": "2" * 64,
        "deterministic": True,
        "ai_enabled": False,
        "ai_used": False,
        "sections": (_section(),),
    }
    payload.update(updates)
    return ReportManifest(**payload)


def _result(**updates: Any) -> ReportResult:
    payload: dict[str, Any] = {
        "manifest": _manifest(),
        "input_bundle": _bundle(),
        "html_path": "reports/scorecard_report.html",
        "pdf_path": None,
        "docx_path": None,
        "data_exports": {"performance_table": "reports/performance_table.csv"},
        "ai_blocks": (),
    }
    payload.update(updates)
    return ReportResult(**payload)
