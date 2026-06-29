"""Tests de ``ReportBuilder``: recolección, secciones, faltantes e import liviano."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import BaseModel, ConfigDict

import nikodym.report as report_pkg
from nikodym.core.config import NikodymConfig
from nikodym.core.lineage import LineageBundle
from nikodym.core.study import Study
from nikodym.report.builder import CANONICAL_SECTION_ORDER, ReportBuilder
from nikodym.report.config import AiNarrationConfig, ReportConfig, SectionPolicyConfig
from nikodym.report.exceptions import ReportInputError

_CARD_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("eda", "eda_card"),
    ("binning", "binning_card"),
    ("selection", "selection_card"),
    ("model", "model_card"),
    ("scorecard", "card"),
    ("calibration", "card"),
    ("performance", "card"),
    ("stability", "card"),
)
_REQUIRED_WITHOUT_MODEL: tuple[str, ...] = (
    "eda",
    "binning",
    "selection",
    "scorecard",
    "calibration",
    "performance",
    "stability",
)


class _TabularArtifact(BaseModel):
    """Artefacto sintético con un ``DataFrame`` embebido."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    by_period: pd.DataFrame
    label: str


class _FigureSpec(BaseModel):
    """Figura declarativa mínima para cubrir copias de BaseModel."""

    figure_id: str
    title: str


class _PydanticCard(BaseModel):
    """Card sintética Pydantic para validar normalización de cards reales."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    summary: str
    metric_sections: dict[str, Any]


def test_collect_orden_canonico_y_manifest_pre_render_golden() -> None:
    """``collect`` ordena secciones y ``build_manifest`` no inventa hash HTML."""
    study = _study_completo()
    builder = ReportBuilder.from_config(ReportConfig())

    bundle = builder.collect(study)
    manifest = builder.build_manifest(bundle, path="reports/scorecard_report.html")

    assert tuple(section.id for section in bundle.sections) == CANONICAL_SECTION_ORDER
    assert bundle.missing_sections == ()
    assert bundle.cards["performance"] == {
        "summary": "performance-card",
        "metric_sections": {"performance": {"auc": 0.74321}},
    }
    assert bundle.sections[0].payload["config_hash"] == "cfg123456789abcdef"
    assert bundle.sections[4].payload["embedded_table"] == {
        "table_ref": "model.model_card.embedded_table"
    }
    assert bundle.sections[4].metric_sections == {"model": {"p_value_max": 0.041}}
    assert tuple(bundle.tables) == (
        "eda.default_rate.by_period",
        "binning.tables.saldo",
        "model.coefficients",
        "model.model_card.embedded_table",
    )
    assert bundle.figures == {
        "eda.figures": (_FigureSpec(figure_id="default_rate", title="Default rate"),)
    }
    assert manifest.model_dump(mode="json") == {
        "report_id": "45760c500091db31",
        "title": "Reporte scorecard",
        "created_from_lineage_at": "2026-06-24T09:30:00+00:00",
        "template_id": "scorecard_basic_v1",
        "template_version": "1.0.0",
        "output_format": "html",
        "path": "reports/scorecard_report.html",
        "sha256": "",
        "deterministic": True,
        "ai_enabled": False,
        "ai_used": False,
        "sections": [section.model_dump(mode="json") for section in bundle.sections],
    }


def test_build_manifest_resuelve_formato_por_suffix_config_y_default() -> None:
    """El formato sale del path si es conocido; si no, cae al config o a HTML."""
    bundle = ReportBuilder.from_config(ReportConfig()).collect(_study_completo())
    ai_builder = ReportBuilder.from_config(
        ReportConfig(ai=AiNarrationConfig(enabled=True, provider="anthropic"))
    )
    json_builder = ReportBuilder.from_config(ReportConfig(formats=("json",)))
    empty_builder = ReportBuilder.from_config(ReportConfig(formats=()))

    ai_manifest = ai_builder.build_manifest(bundle, path="reports/informe.pdf")
    json_manifest = json_builder.build_manifest(bundle, path="reports/informe")
    default_manifest = empty_builder.build_manifest(bundle, path="reports/informe")

    assert ai_manifest.output_format == "pdf"
    assert ai_manifest.deterministic is False
    assert ai_manifest.ai_enabled is True
    assert json_manifest.output_format == "json"
    assert default_manifest.output_format == "html"


def test_collect_no_muta_dataframes_upstream_y_expone_copias_defensivas() -> None:
    """Las tablas embebidas y artefactos tabulares quedan aislados del ``Study``."""
    model_card_frame = _model_card_frame()
    coefficients = _coefficients_frame()
    study = _study_completo(model_card_frame=model_card_frame, coefficients=coefficients)
    model_card_before = model_card_frame.copy(deep=True)
    coefficients_before = coefficients.copy(deep=True)

    bundle = ReportBuilder.from_config(ReportConfig()).collect(study)

    assert_frame_equal(
        study.artifacts.get("model", "model_card")["embedded_table"],
        model_card_before,
    )
    assert_frame_equal(study.artifacts.get("model", "coefficients"), coefficients_before)

    returned_card = bundle.cards["model"]
    returned_table = bundle.tables["model.coefficients"]
    returned_card["embedded_table"].at[0, "beta"] = 99.0
    returned_table.at[0, "beta"] = 88.0

    assert_frame_equal(bundle.cards["model"]["embedded_table"], model_card_before)
    assert_frame_equal(bundle.tables["model.coefficients"], coefficients_before)
    assert_frame_equal(
        study.artifacts.get("model", "model_card")["embedded_table"],
        model_card_before,
    )
    assert_frame_equal(study.artifacts.get("model", "coefficients"), coefficients_before)


def test_missing_policy_warn_publica_seccion_missing_sin_numeros() -> None:
    """Una card requerida ausente queda explícita y sin métricas inventadas."""
    cfg = ReportConfig(sections=SectionPolicyConfig(missing_policy="warn"))
    bundle = ReportBuilder.from_config(cfg).collect(_study_completo(omit=("model",)))
    model_section = next(section for section in bundle.sections if section.id == "model")

    assert bundle.missing_sections == ("model",)
    assert model_section.status == "missing"
    assert model_section.payload == {
        "warning": (
            "Sección requerida ausente; el reporte parcial no inventa números ni rellena métricas."
        )
    }
    assert model_section.metric_sections == {}


def test_missing_policy_error_lanza_report_input_error() -> None:
    """La política default falla ruidosamente si falta una card requerida."""
    with pytest.raises(ReportInputError, match="dominio='model', clave='model_card'"):
        ReportBuilder.from_config(ReportConfig()).collect(_study_completo(omit=("model",)))


def test_missing_policy_skip_omite_seccion_y_la_lista_en_apendice() -> None:
    """``skip`` no renderiza la sección ausente, pero conserva trazabilidad."""
    cfg = ReportConfig(sections=SectionPolicyConfig(missing_policy="skip"))
    bundle = ReportBuilder.from_config(cfg).collect(_study_completo(omit=("model",)))
    ids = tuple(section.id for section in bundle.sections)
    appendix = next(section for section in bundle.sections if section.id == "appendix")

    assert "model" not in ids
    assert bundle.missing_sections == ("model",)
    assert appendix.payload["missing_sections"] == ("model",)


def test_seccion_no_requerida_ausente_se_omite_sin_missing() -> None:
    """Una sección no requerida no se marca como faltante en reportes parciales."""
    cfg = ReportConfig(sections=SectionPolicyConfig(required_sections=_REQUIRED_WITHOUT_MODEL))
    bundle = ReportBuilder.from_config(cfg).collect(_study_completo(omit=("model",)))

    assert "model" not in tuple(section.id for section in bundle.sections)
    assert bundle.missing_sections == ()


def test_collect_sin_figures_deja_apendice_sin_figure_keys() -> None:
    """Las figuras son opcionales en el builder parcial."""
    bundle = ReportBuilder.from_config(ReportConfig()).collect(
        _study_completo(include_figures=False)
    )
    appendix = next(section for section in bundle.sections if section.id == "appendix")

    assert bundle.figures == {}
    assert appendix.payload["figure_keys"] == ()


@pytest.mark.parametrize(
    "invalid_card",
    [
        {"summary": "bad", "metric_sections": {"bad": object()}},
        {"summary": "bad", "metric_sections": ["bad"]},
    ],
)
def test_metric_sections_no_serializable_lanza_report_input_error(
    invalid_card: dict[str, Any],
) -> None:
    """``metric_sections`` debe ser mapping JSON-serializable."""
    study = _study_completo(card_overrides={"model": invalid_card})

    with pytest.raises(ReportInputError, match="metric_sections"):
        ReportBuilder.from_config(ReportConfig()).collect(study)


def test_card_con_tipo_invalido_lanza_report_input_error() -> None:
    """Una card opaca no entra al contrato canónico de ``ReportBuilder``."""
    study = _study_completo(card_overrides={"model": object()})

    with pytest.raises(ReportInputError, match=r"model\.model_card"):
        ReportBuilder.from_config(ReportConfig()).collect(study)


def test_collect_sin_lineage_lanza_report_input_error() -> None:
    """El bundle requiere ``LineageBundle`` disponible antes de reportar."""
    study = Study(_nikodym_config())

    with pytest.raises(ReportInputError, match="LineageBundle"):
        ReportBuilder.from_config(ReportConfig()).collect(study)


def test_report_builder_lazy_export_y_nucleo_liviano_por_subprocess() -> None:
    """``import nikodym.report`` no arrastra renderizadores ni SDK IA."""
    code = (
        "import sys;"
        "import nikodym.report as report;"
        "blocked=[m for m in ('jinja2','matplotlib','plotly','anthropic','pandas') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'ReportBuilder' in report.__all__;"
        "builder_cls=report.ReportBuilder;"
        "assert builder_cls.__name__ == 'ReportBuilder';"
        "blocked=[m for m in ('jinja2','matplotlib','plotly','anthropic') if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    assert report_pkg.ReportBuilder is ReportBuilder


def _study_completo(
    *,
    omit: tuple[str, ...] = (),
    model_card_frame: pd.DataFrame | None = None,
    coefficients: pd.DataFrame | None = None,
    card_overrides: dict[str, Any] | None = None,
    include_figures: bool = True,
) -> Study:
    """Construye un ``Study`` mínimo con cards F1 y artefactos tabulares."""
    study = Study(_nikodym_config())
    study.run_context.lineage = _lineage()
    overrides = {} if card_overrides is None else card_overrides
    for domain, key in _CARD_ARTIFACTS:
        if domain in omit:
            continue
        study.artifacts.set(
            domain,
            key,
            overrides.get(domain, _card(domain, model_card_frame=model_card_frame)),
        )

    study.artifacts.set(
        "eda",
        "default_rate",
        _TabularArtifact(by_period=_default_rate_frame(), label="default_rate"),
    )
    study.artifacts.set("binning", "tables", {"saldo": _binning_table()})
    study.artifacts.set(
        "model",
        "coefficients",
        _coefficients_frame() if coefficients is None else coefficients,
    )
    study.artifacts.set("model", "stepwise_trace", ("sin_tabla",))
    if include_figures:
        study.artifacts.set(
            "eda",
            "figures",
            (_FigureSpec(figure_id="default_rate", title="Default rate"),),
        )
    return study


def _card(domain: str, *, model_card_frame: pd.DataFrame | None) -> Any:
    """Devuelve cards heterogéneas: mappings, ``None`` CT-2 y BaseModel."""
    if domain == "model":
        return {
            "summary": "model-card",
            "embedded_table": _model_card_frame() if model_card_frame is None else model_card_frame,
            "notes": ["sin recalculo", {"source": "upstream"}],
            "nested": _FigureSpec(figure_id="coeficientes", title="Coeficientes"),
            "selected_features": ("saldo",),
            "metric_sections": {"model": {"p_value_max": 0.041}},
        }
    if domain == "binning":
        return {"summary": "binning-card", "metric_sections": None}
    if domain == "performance":
        return _PydanticCard(
            summary="performance-card",
            metric_sections={"performance": {"auc": 0.74321}},
        )
    return {"summary": f"{domain}-card"}


def _lineage() -> LineageBundle:
    """Lineage fijo para golden values del builder."""
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123",
        config_hash="cfg123456789abcdef",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "0.1.0"},
        determinism_caveats=["working tree controlado"],
        created_at=datetime(2026, 6, 24, 9, 30, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _model_card_frame() -> pd.DataFrame:
    """Tabla embebida en una card sintética."""
    return pd.DataFrame({"feature": ["saldo"], "beta": [1.25]})


def _coefficients_frame() -> pd.DataFrame:
    """Artefacto tabular de coeficientes sintético."""
    return pd.DataFrame({"feature": ["saldo"], "beta": [1.25], "p_value": [0.041]})


def _default_rate_frame() -> pd.DataFrame:
    """Tabla EDA sintética extraída desde un BaseModel."""
    return pd.DataFrame({"period": ["2026-01"], "default_rate": [0.12345]})


def _binning_table() -> pd.DataFrame:
    """Tabla de binning sintética dentro de un mapping."""
    return pd.DataFrame({"bin": ["bajo", "alto"], "iv": [0.10, 0.20]})


def _nikodym_config() -> NikodymConfig:
    """Construye el config raíz vía validación Pydantic para mypy estricto."""
    return NikodymConfig.model_validate({})
