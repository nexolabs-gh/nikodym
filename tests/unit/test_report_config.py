"""Tests de ``ReportConfig`` (SDD-26 §5) y su integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import nikodym.report as report_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.report.config import (
    AiNarrationConfig,
    HtmlRenderConfig,
    QuartoRenderConfig,
    ReportConfig,
    SectionPolicyConfig,
)
from nikodym.report.exceptions import (
    ReportAIError,
    ReportDependencyError,
    ReportError,
    ReportExportError,
    ReportInputError,
    ReportRenderError,
)

GOLDEN_DEFAULT_CONFIG_HASH = "70dbc51fb6c230afac21fb20fa1d28e6e766d09759d5d765d82ab5cd5aacc1a8"


@pytest.fixture(autouse=True)
def _capa_report_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_REPORT_CONFIG_CLS", ReportConfig)


def _report_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-26 §5."""
    return {
        "schema_version": "1.0.0",
        "type": "standard",
        "output_dir": "reports",
        "basename": "scorecard_report",
        "language": "es",
        "formats": ["html"],
        "html": {
            "template_id": "scorecard_basic_v1",
            "theme": "nikodym",
            "embed_assets": True,
            "include_interactive_charts": False,
            "deterministic_ids": True,
        },
        "quarto": {
            "enabled": False,
            "formats": [],
            "fail_if_unavailable": False,
        },
        "ai": {
            "enabled": False,
            "provider": "none",
            "model": None,
            "api_key_env": "ANTHROPIC_API_KEY",
            "timeout_seconds": 20.0,
            "max_input_tokens": 12_000,
            "send_raw_data": False,
            "label_ai_text": True,
        },
        "sections": {
            "required_sections": [
                "eda",
                "binning",
                "selection",
                "model",
                "scorecard",
                "calibration",
                "performance",
                "stability",
            ],
            "missing_policy": "error",
            "include_raw_tables": False,
            "max_table_rows": 200,
        },
    }


def test_reportconfig_defaults_golden() -> None:
    """``ReportConfig()`` construye sin argumentos y coincide bit a bit con el golden."""
    assert ReportConfig().model_dump(mode="json") == _report_defaults()


def test_round_trip_yaml_reportconfig() -> None:
    """Serializar y recargar ``ReportConfig`` por YAML preserva igualdad exacta."""
    cfg = ReportConfig(
        output_dir="docs/reportes",
        basename="informe_scorecard",
        formats=("html", "json", "csv", "xlsx"),
        html=HtmlRenderConfig(
            template_id="scorecard_detallado_v1",
            theme="plain",
            embed_assets=False,
            include_interactive_charts=True,
            deterministic_ids=False,
        ),
        quarto=QuartoRenderConfig(
            enabled=True,
            formats=("pdf", "docx"),
            fail_if_unavailable=True,
        ),
        ai=AiNarrationConfig(
            enabled=True,
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            timeout_seconds=45.0,
            max_input_tokens=20_000,
        ),
        sections=SectionPolicyConfig(
            missing_policy="warn",
            include_raw_tables=True,
            max_table_rows=500,
        ),
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert ReportConfig.model_validate(raw) == cfg


def test_nikodymconfig_report_instancia() -> None:
    """Pasar una instancia ``ReportConfig`` a ``NikodymConfig`` la conserva."""
    report = ReportConfig()
    cfg = NikodymConfig(report=report)
    assert isinstance(cfg.report, ReportConfig)
    assert cfg.report is report


def test_nikodymconfig_report_dict_coacciona() -> None:
    """Un dict en ``report`` se coacciona a ``ReportConfig`` por el hook cargado."""
    cfg = NikodymConfig(report={"output_dir": "salidas", "ai": {"enabled": True}})
    assert isinstance(cfg.report, ReportConfig)
    assert cfg.report.output_dir == "salidas"
    assert cfg.report.ai.enabled is True


def test_nikodymconfig_report_none_explicito() -> None:
    """``report=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(report=None).report is None


def test_nikodymconfig_report_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``report`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_REPORT_CONFIG_CLS", None)
    cfg = NikodymConfig(report={"output_dir": "salidas", "ai": {"enabled": True}})
    assert cfg.report == {"output_dir": "salidas", "ai": {"enabled": True}}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_report_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``report`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_REPORT_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(report=blob)


@pytest.mark.parametrize(
    "report",
    [
        ReportConfig(output_dir="reportes_cliente"),
        ReportConfig(basename="scorecard_validacion"),
        ReportConfig(formats=("html", "json", "csv", "xlsx")),
        ReportConfig(html=HtmlRenderConfig(template_id="scorecard_detallado_v1")),
        ReportConfig(html=HtmlRenderConfig(theme="plain")),
        ReportConfig(quarto=QuartoRenderConfig(enabled=True)),
        ReportConfig(ai=AiNarrationConfig(enabled=True, provider="anthropic")),
        ReportConfig(sections=SectionPolicyConfig(missing_policy="warn")),
        ReportConfig(sections=SectionPolicyConfig(max_table_rows=1_000)),
    ],
)
def test_config_hash_no_cambia_al_variar_report(report: ReportConfig) -> None:
    """``report`` es INFRA: plantilla, output, formatos, Quarto e IA no cambian identidad."""
    base = config_hash(NikodymConfig(report=ReportConfig()))
    variado = config_hash(NikodymConfig(report=report))
    assert "report" in INFRA_SECTIONS
    assert variado == base == GOLDEN_DEFAULT_CONFIG_HASH


def test_config_hash_default_no_cambia_al_importar_report() -> None:
    """Importar y cablear ``report`` no mueve el golden del config por defecto."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_report_en_infra_sections() -> None:
    """``report`` pertenece explícitamente a las secciones excluidas del ``config_hash``."""
    assert "report" in INFRA_SECTIONS


def test_dump_load_nikodymconfig_con_report_idempotente() -> None:
    """``dump_config``/``loads_config`` preservan la sección ``report`` cableada."""
    cfg = NikodymConfig(
        report=ReportConfig(
            output_dir="docs/reportes",
            formats=("html", "xlsx"),
            sections=SectionPolicyConfig(missing_policy="skip"),
        )
    )
    assert loads_config(dump_config(cfg)) == cfg


def test_ai_send_raw_data_true_rechazado_por_literal_false() -> None:
    """``send_raw_data=True`` queda bloqueado por ``Literal[False]``."""
    with pytest.raises(ValidationError):
        AiNarrationConfig(send_raw_data=True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("config_cls", "kwargs"),
    [
        (AiNarrationConfig, {"timeout_seconds": 0.5}),
        (AiNarrationConfig, {"timeout_seconds": 121.0}),
        (AiNarrationConfig, {"max_input_tokens": 999}),
        (SectionPolicyConfig, {"max_table_rows": 9}),
    ],
)
def test_rangos_invalidos_rechazados_por_pydantic(
    config_cls: type[object],
    kwargs: dict[str, object],
) -> None:
    """Timeout, tokens y filas fuera de rango violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        config_cls(**kwargs)


@pytest.mark.parametrize(
    ("config_cls", "kwargs"),
    [
        (ReportConfig, {"formats": ("pdf",)}),
        (QuartoRenderConfig, {"formats": ("html",)}),
        (AiNarrationConfig, {"provider": "openai"}),
        (SectionPolicyConfig, {"missing_policy": "ignore"}),
        (HtmlRenderConfig, {"theme": "dark"}),
    ],
)
def test_literales_invalidos_rechazados_por_pydantic(
    config_cls: type[object],
    kwargs: dict[str, object],
) -> None:
    """Valores fuera de los ``Literal`` documentados son inválidos."""
    with pytest.raises(ValidationError):
        config_cls(**kwargs)


def test_campos_report_tienen_metadatos_ui() -> None:
    """Todos los campos de config report declaran metadata de UI para SDD-23."""
    for config_cls in (
        HtmlRenderConfig,
        QuartoRenderConfig,
        AiNarrationConfig,
        SectionPolicyConfig,
        ReportConfig,
    ):
        for nombre, campo in config_cls.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{config_cls.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{config_cls.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{config_cls.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_report_public_api_minimo() -> None:
    """El paquete expone config, excepciones y el step registrado en B26.6."""
    assert report_pkg.ReportConfig is ReportConfig
    assert "ReportStep" in report_pkg.__all__
    assert report_pkg.ReportStep.__name__ == "ReportStep"
    assert report_pkg.ReportError is ReportError


def test_report_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``report`` cuelgan de la raíz propia de la librería."""
    error_classes = (
        ReportError,
        ReportInputError,
        ReportRenderError,
        ReportExportError,
        ReportAIError,
        ReportDependencyError,
    )
    for error_cls in error_classes:
        assert issubclass(error_cls, NikodymError)
        with pytest.raises(ReportError, match="fallo report"):
            raise error_cls("fallo report")


def test_import_report_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.report`` registra el hook sin arrastrar renderizadores ni SDK IA."""
    code = (
        "import nikodym.report, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.report.config import ReportConfig;"
        "bloqueados=[m for m in ('jinja2','matplotlib','plotly','anthropic') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(report={'output_dir': 'salidas'});"
        "assert isinstance(cfg.report, ReportConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_report_como_blob_opaco_sin_importar_report() -> None:
    """El core acepta ``report`` JSON/dict sin importar ``nikodym.report``."""
    code = (
        "from nikodym.core.config import NikodymConfig, dump_config;"
        "import sys;"
        "assert 'nikodym.report' not in sys.modules;"
        "cfg=NikodymConfig(report={'output_dir': 'salidas', 'ai': {'enabled': True}});"
        "assert cfg.report == {'output_dir': 'salidas', 'ai': {'enabled': True}};"
        "texto=dump_config(cfg);"
        "assert 'report:' in texto;"
        "assert 'nikodym.report' not in sys.modules;"
        "bloqueados=[m for m in ('jinja2','matplotlib','plotly','anthropic') if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
