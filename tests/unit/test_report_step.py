"""Tests de ``ReportStep``: contrato CT-1, auditoría, no-mutación e import liviano."""

from __future__ import annotations

import builtins
import importlib.util
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.core.study as study_module
import nikodym.report as report_pkg
import nikodym.report.renderer as renderer_module
import nikodym.report.step as step_module
from nikodym.binning.config import BinningConfig
from nikodym.calibration.config import CalibrationConfig
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig, ReproConfig, config_hash
from nikodym.core.exceptions import ArtifactNotFoundError
from nikodym.core.lineage import LineageBundle
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.data.config import (
    CohortSplitConfig,
    ColumnSpec,
    DataConfig,
    PartitionConfig,
    Predicate,
    Rule,
    SchemaConfig,
    TargetConfig,
)
from nikodym.data.step import INPUT_FRAME_KEY
from nikodym.eda.config import (
    DefaultRateConfig,
    EdaConfig,
    TemporalStabilityConfig,
    UnivariateConfig,
)
from nikodym.model.config import IvContributionConfig, ModelConfig, SignPolicyConfig, StepwiseConfig
from nikodym.performance.config import PerformanceConfig
from nikodym.report.builder import CANONICAL_SECTION_ORDER
from nikodym.report.config import (
    AiNarrationConfig,
    PdfRenderConfig,
    ReportConfig,
    SectionPolicyConfig,
)
from nikodym.report.exceptions import ReportDependencyError, ReportExportError
from nikodym.report.renderer import HtmlReportRenderer
from nikodym.report.results import AiNarrationBlock, ReportInputBundle, ReportResult
from nikodym.report.step import REPORT_ARTIFACTS, REPORT_REQUIRED_CARDS, ReportStep
from nikodym.scorecard.config import ScorecardConfig
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.stability.config import StabilityConfig

ROOT_SEED = 20_240_629
# Golden del ``_digest_html`` (excluye ``<svg>``): con el extra ``report`` el bundle golden embebe
# un único gráfico (forest de coeficientes) cuyo slot cuenta en el digest.
GOLDEN_STEP_HTML_SHA256 = "4e733e1a33aca0b11e5ec0c9b1f426c48c70b691078b7a950781529e6fc61c7b"

_HAS_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita importar OR-Tools dentro del proceso pytest."""
    del fake_binning_process


def test_from_config_registro_reexport_y_contrato_step_exacto() -> None:
    """``ReportStep`` expone el contrato CT-1 exacto de SDD-26 §4."""
    cfg = ReportConfig()
    step = ReportStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("report", "standard") is ReportStep
    assert report_pkg.__getattr__("ReportStep") is ReportStep
    assert step.config is cfg
    assert step.name == "report"
    assert step.requires == REPORT_REQUIRED_CARDS
    assert step.provides == tuple(("report", key) for key in REPORT_ARTIFACTS)
    step.emit(
        AuditEvent(
            kind="decision",
            step="report",
            payload={"regla": "x"},
            ts=datetime.now(UTC),
        )
    )
    assert sink.events[-1].payload == {"regla": "x"}


def test_requires_se_deriva_de_required_sections() -> None:
    """``requires`` filtra ``REPORT_REQUIRED_CARDS`` por ``sections.required_sections`` (CT-1).

    Con el default de ocho secciones el contrato no cambia; un pipeline que no corre ``eda`` (p.
    ej. el preset F1) declara ``required_sections`` sin ``eda`` y el step deja de exigir su card, de
    modo que ``_validate_pipeline`` no rechaza el config por un prerequisito inalcanzable.
    """
    assert ReportStep.from_config(ReportConfig()).requires == REPORT_REQUIRED_CARDS

    sin_eda = (
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
        "stability",
    )
    step = ReportStep.from_config(
        ReportConfig(sections=SectionPolicyConfig(required_sections=sin_eda))
    )
    assert ("eda", "eda_card") not in step.requires
    assert step.requires == tuple(
        (domain, key) for domain, key in REPORT_REQUIRED_CARDS if domain != "eda"
    )

    solo_modelo = ReportStep.from_config(
        ReportConfig(sections=SectionPolicyConfig(required_sections=("model",)))
    )
    assert solo_modelo.requires == (("model", "model_card"),)


def test_core_study_cablea_report_en_orden_por_defecto(tmp_path: Path) -> None:
    """``Study`` resuelve ``report`` como dominio perezoso después de ``stability``."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order[order.index("stability") + 1] == "report"
    assert study_module._DOMAIN_MODULES["report"] == "nikodym.report"
    assert study_module._DOMAIN_CONFIG_CLASSES["report"] == (
        "nikodym.report.config",
        "ReportConfig",
    )

    study = Study(NikodymConfig(report=ReportConfig(output_dir=str(tmp_path))))

    assert study._default_step_names() == ["report"]
    assert isinstance(study._resolve_step("report"), ReportStep)


def test_execute_publica_result_manifest_goldens_audit_y_no_consume_rng(tmp_path: Path) -> None:
    """El step renderiza HTML, publica copias y registra decisiones auditables."""
    cfg = ReportConfig(
        output_dir=str(tmp_path),
        sections=SectionPolicyConfig(max_table_rows=10),
    )
    study = _study_with_report_artifacts(config=cfg)
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = ReportStep.from_config(study.config.report)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(ROOT_SEED))
    output = tmp_path / "scorecard_report.html"

    assert isinstance(result, ReportResult)
    assert output.exists()
    assert output.read_bytes() == output.read_text(encoding="utf-8").encode("utf-8")
    assert result.manifest.sha256 == renderer_module._digest_html(
        output.read_text(encoding="utf-8")
    )
    if _HAS_MATPLOTLIB:
        assert result.manifest.sha256 == GOLDEN_STEP_HTML_SHA256
    assert result.manifest.report_id == "45760c500091db31"
    assert result.manifest.path == "scorecard_report.html"
    assert result.manifest.ai_enabled is True
    assert result.manifest.ai_used is False
    # El documento: capítulos de primer nivel en el orden canónico único (report.document).
    assert (
        tuple(section.id for section in result.input_bundle.sections if section.level == 1)
        == CANONICAL_SECTION_ORDER
    )
    # Los ocho dominios del pipeline son ahora subsecciones, no secciones de primer nivel.
    ids = {section.id for section in result.input_bundle.sections}
    assert "results.performance" in ids
    assert "appendix_parameters.model" in ids
    assert "performance" not in ids
    assert result.input_bundle.missing_sections == ()
    assert tuple(block.section_id for block in result.ai_blocks) == tuple(
        section.id for section in result.input_bundle.sections
    )
    assert all(not block.generated for block in result.ai_blocks)

    for key in REPORT_ARTIFACTS:
        assert study.artifacts.has("report", key)
    artifact_result = study.artifacts.get("report", "result")
    assert isinstance(artifact_result, ReportResult)
    assert artifact_result.manifest == result.manifest
    assert artifact_result.input_bundle.lineage == result.input_bundle.lineage
    assert tuple(section.id for section in artifact_result.input_bundle.sections) == tuple(
        section.id for section in result.input_bundle.sections
    )
    assert_frame_equal(
        artifact_result.input_bundle.tables["model.coefficients"],
        result.input_bundle.tables["model.coefficients"],
    )
    assert artifact_result.ai_blocks == result.ai_blocks

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert rules == [
        "report_sections",
        "report_table_truncation",
        "report_ai_disabled",
        "report_export_html",
    ]


def test_execute_no_muta_artefactos_upstream(tmp_path: Path) -> None:
    """Las cards y tablas de dominios aguas arriba quedan intactas tras el render."""
    study = _study_with_report_artifacts(
        config=ReportConfig(
            output_dir=str(tmp_path),
            sections=SectionPolicyConfig(max_table_rows=10),
        )
    )
    model_card_before = study.artifacts.get("model", "model_card")["embedded_table"].copy(deep=True)
    performance_table_before = study.artifacts.get(
        "performance",
        "performance_table",
    ).copy(deep=True)
    stability_card_before = dict(study.artifacts.get("stability", "card"))

    ReportStep.from_config(study.config.report).execute(
        study,
        np.random.default_rng(1),
    )

    assert_frame_equal(
        study.artifacts.get("model", "model_card")["embedded_table"],
        model_card_before,
    )
    assert_frame_equal(
        study.artifacts.get("performance", "performance_table"),
        performance_table_before,
    )
    assert study.artifacts.get("stability", "card") == stability_card_before


def test_requires_faltante_falla_con_artifactnotfounderror(tmp_path: Path) -> None:
    """Si falta una card requerida, CT-1 levanta ``ArtifactNotFoundError`` claro."""
    study = _study_with_report_artifacts(config=ReportConfig(output_dir=str(tmp_path)))
    study.artifacts._store.pop(("stability", "card"))

    with pytest.raises(ArtifactNotFoundError, match=r"\('stability', 'card'\)"):
        study.run_step("report")
    with pytest.raises(ArtifactNotFoundError, match=r"\('stability', 'card'\)"):
        ReportStep.from_config(study.config.report).execute(study, np.random.default_rng(2))


def test_output_dir_no_escribible_falla_antes_de_ia(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """El preflight de export falla antes de llamar a narrativa IA o render."""
    cfg = ReportConfig(
        output_dir=str(tmp_path / "bloqueado"),
        ai=AiNarrationConfig(enabled=True, provider="anthropic"),
    )
    study = _study_with_report_artifacts(config=cfg)
    monkeypatch.setattr(step_module.os, "access", lambda path, mode: False)

    def fail_narration(*_args: object, **_kwargs: object) -> tuple[AiNarrationBlock, ...]:
        raise AssertionError("No se debía llamar narrativa si output_dir no es escribible.")

    monkeypatch.setattr(step_module, "_narration_blocks", fail_narration)
    with pytest.raises(ReportExportError, match="no es escribible"):
        ReportStep.from_config(cfg).execute(study, np.random.default_rng(2))


def test_manifest_en_memoria_y_exportado_tienen_identidad_canonica(tmp_path: Path) -> None:
    """El manifest no depende del toggle ``output_dir`` salvo por ``path``."""
    cfg = ReportConfig(
        output_dir="",
        schema_version="9.9.9",
        sections=SectionPolicyConfig(max_table_rows=10),
    )
    study = _study_with_report_artifacts(config=cfg)
    builder = step_module.ReportBuilder.from_config(cfg)
    bundle = builder.collect(study)
    reversed_bundle = bundle.model_copy(update={"sections": tuple(reversed(bundle.sections))})
    ai_blocks = step_module._narration_blocks(reversed_bundle, cfg)
    renderer = HtmlReportRenderer.from_config(cfg)
    html = renderer.render(reversed_bundle, ai_blocks=ai_blocks)

    memory_manifest = renderer.build_manifest(html)
    written_manifest = renderer.write(html, output_dir=str(tmp_path))

    assert memory_manifest.path == ""
    assert written_manifest.path == "scorecard_report.html"
    assert memory_manifest.model_copy(update={"path": written_manifest.path}) == written_manifest
    assert memory_manifest.report_id == written_manifest.report_id == "45760c500091db31"
    assert memory_manifest.template_version == written_manifest.template_version == "1.0.0"
    assert memory_manifest.sha256 == written_manifest.sha256
    if _HAS_MATPLOTLIB:
        assert memory_manifest.sha256 == GOLDEN_STEP_HTML_SHA256
    # El manifest reordena al orden canónico del documento aunque el bundle llegue invertido.
    assert (
        tuple(section.id for section in memory_manifest.sections if section.level == 1)
        == CANONICAL_SECTION_ORDER
    )
    assert tuple(section.id for section in written_manifest.sections) == tuple(
        section.id for section in memory_manifest.sections
    )

    with pytest.raises(ReportExportError, match="build_manifest"):
        HtmlReportRenderer.from_config(cfg).build_manifest(html)


def test_helpers_defensivos_cubren_config_export_ia_y_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ramas defensivas del step preservan errores propios y manifiestos deterministas."""
    fallback = ReportConfig(output_dir="")
    assert (
        step_module._report_config_from_study(
            SimpleNamespace(config=SimpleNamespace(report={"basename": "dict_cfg"})),
            fallback=fallback,
        ).basename
        == "dict_cfg"
    )
    assert (
        step_module._report_config_from_study(
            SimpleNamespace(config=SimpleNamespace(report=None)),
            fallback=fallback,
        )
        is fallback
    )
    assert (
        step_module._report_config_from_study(
            SimpleNamespace(config=SimpleNamespace(report=fallback)),
            fallback=ReportConfig(output_dir=str(tmp_path)),
        )
        is fallback
    )

    cfg = ReportConfig(output_dir="")
    study = _study_with_report_artifacts(config=cfg)
    result = ReportStep.from_config(cfg).execute(study, np.random.default_rng(3))
    assert result.manifest.path == ""
    assert result.html_path is None
    assert result.manifest.sha256
    assert result.manifest.deterministic is True

    original_mkdir = step_module.Path.mkdir

    def fail_mkdir(self: Path, *, parents: bool, exist_ok: bool) -> None:
        del self, parents, exist_ok
        raise OSError("mkdir denegado")

    monkeypatch.setattr(step_module.Path, "mkdir", fail_mkdir)
    with pytest.raises(ReportExportError, match="crear el directorio"):
        step_module._preflight_output_dir(ReportConfig(output_dir=str(tmp_path / "sin_padre")))
    monkeypatch.setattr(step_module.Path, "mkdir", original_mkdir)

    monkeypatch.setattr(step_module.Path, "is_dir", lambda self: False)
    with pytest.raises(ReportExportError, match="no es escribible"):
        step_module._preflight_output_dir(ReportConfig(output_dir=str(tmp_path / "falso")))


def test_ai_enabled_degrada_y_ai_generada_queda_auditada(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """La IA opcional se audita como fallback o uso generado según los bloques resultantes."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fallback_cfg = ReportConfig(
        output_dir=str(tmp_path / "fallback"),
        ai=AiNarrationConfig(enabled=True, provider="anthropic"),
    )
    fallback_study = _study_with_report_artifacts(config=fallback_cfg)
    fallback_sink = InMemoryAuditSink()
    fallback_study.set_audit_sink(fallback_sink)
    fallback_step = ReportStep.from_config(fallback_cfg)
    fallback_step._audit = fallback_sink
    fallback_result = fallback_step.execute(fallback_study, np.random.default_rng(4))

    assert all(not block.generated for block in fallback_result.ai_blocks)
    assert all(block.warning is not None for block in fallback_result.ai_blocks)
    assert "report_ai_fallback" in [
        event.payload["regla"] for event in fallback_sink.events if event.kind == "decision"
    ]

    generated_cfg = ReportConfig(
        output_dir=str(tmp_path / "generated"),
        ai=AiNarrationConfig(enabled=True, provider="anthropic", model="modelo-test"),
    )
    generated_study = _study_with_report_artifacts(config=generated_cfg)
    generated_sink = InMemoryAuditSink()
    generated_study.set_audit_sink(generated_sink)

    def generated_blocks(
        bundle: ReportInputBundle,
        config: ReportConfig,
    ) -> tuple[AiNarrationBlock, ...]:
        del config
        return tuple(
            AiNarrationBlock(
                section_id=section.id,
                text=f"Narrativa IA {section.id}.",
                provider="anthropic",
                model="modelo-test",
                generated=True,
                prompt_hash="0" * 64,
                input_payload_hash=f"{index:064x}",
                warning=None,
            )
            for index, section in enumerate(bundle.sections)
        )

    monkeypatch.setattr(step_module, "_narration_blocks", generated_blocks)
    generated_step = ReportStep.from_config(generated_cfg)
    generated_step._audit = generated_sink
    generated_result = generated_step.execute(generated_study, np.random.default_rng(5))

    assert generated_result.manifest.ai_used is True
    rules = [event.payload["regla"] for event in generated_sink.events if event.kind == "decision"]
    assert "report_ai_usage" in rules


# ─────────────────────── cableado del PDF opt-in (formats + degradación) ───────────────────────


def _block_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fuerza ``ModuleNotFoundError`` al importar ``weasyprint`` (ausencia determinista).

    WeasyPrint no está en el entorno de estos jobs (extra ``pdf`` fuera de ``all``); bloquear su
    import hace la degradación determinista con independencia del entorno.
    """
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "weasyprint":
            raise ModuleNotFoundError("weasyprint")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_execute_sin_pdf_en_formats_no_escribe_pdf(tmp_path: Path) -> None:
    """Sin ``"pdf"`` en ``formats`` el step no escribe PDF ni refleja ``pdf_path``."""
    cfg = ReportConfig(output_dir=str(tmp_path), sections=SectionPolicyConfig(max_table_rows=10))
    study = _study_with_report_artifacts(config=cfg)

    result = ReportStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))

    assert result.pdf_path is None
    assert not (tmp_path / "scorecard_report.pdf").exists()


def test_execute_pdf_en_formats_degrada_sin_weasyprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Con ``"pdf"`` en ``formats`` y WeasyPrint ausente (``fail_if_unavailable=False``) degrada.

    ``formats`` es la fuente de verdad del step: con ``pdf.enabled=False`` el PDF se intenta igual
    porque ``"pdf"`` está en ``formats``. Sin WeasyPrint degrada con gracia: ``pdf_path=None``,
    ``RuntimeWarning`` y sólo se escribe el HTML determinístico.
    """
    _block_weasyprint(monkeypatch)
    cfg = ReportConfig(
        output_dir=str(tmp_path),
        formats=("html", "pdf"),
        pdf=PdfRenderConfig(enabled=False, fail_if_unavailable=False),
        sections=SectionPolicyConfig(max_table_rows=10),
    )
    study = _study_with_report_artifacts(config=cfg)

    with pytest.warns(RuntimeWarning, match="WeasyPrint no está disponible"):
        result = ReportStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))

    assert result.pdf_path is None
    assert (tmp_path / "scorecard_report.html").is_file()
    assert not (tmp_path / "scorecard_report.pdf").exists()


def test_execute_pdf_en_formats_fail_if_unavailable_relanza(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Con ``"pdf"`` en ``formats``, WeasyPrint ausente y ``fail_if_unavailable=True`` re-lanza."""
    _block_weasyprint(monkeypatch)
    cfg = ReportConfig(
        output_dir=str(tmp_path),
        formats=("html", "pdf"),
        pdf=PdfRenderConfig(fail_if_unavailable=True),
        sections=SectionPolicyConfig(max_table_rows=10),
    )
    study = _study_with_report_artifacts(config=cfg)

    with pytest.raises(ReportDependencyError, match="WeasyPrint"):
        ReportStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))


def test_execute_refleja_pdf_path_y_audita_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cuando ``_maybe_write_pdf`` devuelve una ruta, el step la refleja y audita el export PDF."""
    cfg = ReportConfig(
        output_dir=str(tmp_path),
        formats=("html", "pdf"),
        sections=SectionPolicyConfig(max_table_rows=10),
    )
    study = _study_with_report_artifacts(config=cfg)
    sink = InMemoryAuditSink()
    step = ReportStep.from_config(cfg)
    step._audit = sink
    fake_pdf = str(tmp_path / "scorecard_report.pdf")
    monkeypatch.setattr(step_module, "_maybe_write_pdf", lambda *args, **kwargs: fake_pdf)

    result = step.execute(study, np.random.default_rng(ROOT_SEED))

    assert result.pdf_path == fake_pdf
    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert "report_export_pdf" in rules


def test_execute_md_en_formats_escribe_la_base_editable_y_la_audita(tmp_path: Path) -> None:
    """``"md"`` en ``formats`` escribe el ``.qmd`` (y sus figuras), lo refleja y lo audita.

    El ``.qmd`` no requiere extras —es texto—, así que no hay degradación posible: si se pide, sale.
    """
    cfg = ReportConfig(
        output_dir=str(tmp_path),
        formats=("html", "md"),
        sections=SectionPolicyConfig(max_table_rows=10),
    )
    study = _study_with_report_artifacts(config=cfg)
    sink = InMemoryAuditSink()
    step = ReportStep.from_config(cfg)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(ROOT_SEED))

    assert result.md_path == str(tmp_path / "scorecard_report.qmd")
    qmd = tmp_path / "scorecard_report.qmd"
    assert qmd.is_file()
    assert qmd.read_text(encoding="utf-8").startswith("---\n")  # front-matter YAML
    assert "## 1 Introducción" in qmd.read_text(encoding="utf-8")

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert "report_export_md" in rules


def test_execute_csv_en_formats_puebla_data_exports_con_las_tablas_completas(
    tmp_path: Path,
) -> None:
    """``data_exports`` deja de estar muerto: se puebla con los adjuntos por observación.

    El campo ya existía en ``ReportResult`` y nadie lo escribía. Aquí se cierra el círculo: las
    tablas por observación salen del documento y entran, completas, como archivos.
    """
    cfg = ReportConfig(
        output_dir=str(tmp_path),
        formats=("html", "csv"),
        sections=SectionPolicyConfig(max_table_rows=10),
    )
    study = _study_with_report_artifacts(config=cfg)
    study.artifacts.set("scorecard", "score", _score_frame())
    sink = InMemoryAuditSink()
    step = ReportStep.from_config(cfg)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(ROOT_SEED))

    assert set(result.data_exports) == {"scorecard_report__scorecard_score.csv"}
    export = Path(result.data_exports["scorecard_report__scorecard_score.csv"])
    assert export.is_file()
    assert len(export.read_text(encoding="utf-8-sig").strip().splitlines()) == 26  # 25 filas + head

    # La tabla NO se renderiza en el documento, pero el documento dice dónde está.
    html = (tmp_path / "scorecard_report.html").read_text(encoding="utf-8")
    assert 'data-table-key="scorecard.score"' not in html
    assert "scorecard_report__scorecard_score.csv" in html

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert "report_export_datos" in rules


def test_sin_formato_de_datos_no_hay_exports(tmp_path: Path) -> None:
    """Sin ``csv``/``xlsx`` no se escribe ningún adjunto: ``data_exports`` queda vacío."""
    cfg = ReportConfig(
        output_dir=str(tmp_path),
        formats=("html",),
        sections=SectionPolicyConfig(max_table_rows=10),
    )
    study = _study_with_report_artifacts(config=cfg)
    study.artifacts.set("scorecard", "score", _score_frame())

    result = ReportStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))

    assert result.data_exports == {}
    assert not list(tmp_path.glob("*.csv"))
    # El documento declara la ausencia en vez de callarla.
    assert "no se exportaron" in (tmp_path / "scorecard_report.html").read_text(encoding="utf-8")


def _score_frame() -> pd.DataFrame:
    """Frame por observación (25 filas) con el identificador de la operación como índice."""
    return pd.DataFrame(
        {"score": [600 + index for index in range(25)]},
        index=pd.Index([f"op-{index:03d}" for index in range(25)], name="loan_id"),
    )


def test_import_report_step_y_core_livianos_por_subprocess() -> None:
    """``core`` no arrastra dominios y ``report`` registra sin dependencias pesadas."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym.core

        blocked_core = [
            name
            for name in ("nikodym.report", "nikodym.data", "pandas", "pandera", "jinja2")
            if name in sys.modules
        ]
        assert blocked_core == [], blocked_core

        import nikodym.report
        from nikodym.core.registry import REGISTRY

        assert REGISTRY.resolve("report", "standard").__name__ == "ReportStep"
        blocked_report = [
            name
            for name in ("pandas", "pandera", "jinja2", "matplotlib", "plotly", "anthropic")
            if name in sys.modules
        ]
        assert blocked_report == [], blocked_report
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_study_run_pipeline_scorecard_report_end_to_end(tmp_path: Path) -> None:
    """``Study.run([...,'report'])`` produce los tres artefactos finales del reporte."""
    study = _pipeline_study(tmp_path)
    _inject_pipeline_frame(study)

    assert (
        study.run(
            [
                "data",
                "eda",
                "binning",
                "selection",
                "model",
                "scorecard",
                "calibration",
                "performance",
                "stability",
                "report",
            ]
        )
        is study
    )

    for key in REPORT_ARTIFACTS:
        assert study.artifacts.has("report", key)
    result = study.artifacts.get("report", "result")
    assert isinstance(result, ReportResult)
    assert result.input_bundle.missing_sections == ()
    assert result.manifest.sha256 == renderer_module._digest_html(
        (tmp_path / "scorecard_report.html").read_text(encoding="utf-8")
    )
    assert study.run_context.lineage is not None
    assert result.input_bundle.lineage.config_hash == config_hash(study.config)


def _study_with_report_artifacts(*, config: ReportConfig) -> Study:
    """Construye un ``Study`` con las ocho cards requeridas y tablas de reporte."""
    study = Study(NikodymConfig(report=config))
    study.run_context.lineage = _lineage()
    for domain, key in REPORT_REQUIRED_CARDS:
        study.artifacts.set(domain, key, _card(domain))
    study.artifacts.set("performance", "performance_table", _performance_table())
    study.artifacts.set("model", "coefficients", _coefficients_table())
    return study


def _card(domain: str) -> dict[str, Any]:
    """Card sintética con ``metric_sections`` serializable y una tabla embebida en model."""
    if domain == "model":
        return {
            "summary": "model-card",
            "selected_features": ("saldo", "mora"),
            "embedded_table": _coefficients_table(),
            "metric_sections": {"model": {"p_value_max": 0.041}},
        }
    if domain == "performance":
        return {
            "summary": "performance-card",
            "metric_sections": {"performance": {"auc": 0.74321, "ks": 0.31234}},
        }
    if domain == "stability":
        return {
            "summary": "stability-card",
            "metric_sections": {"stability": {"score_psi": {"max_psi": 0.271, "band": "review"}}},
        }
    return {"summary": f"{domain}-card", "metric_sections": {domain: {"ok": 1}}}


def _lineage() -> LineageBundle:
    """Lineage fijo para golden values de ``ReportStep``."""
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123456789abcdef",
        config_hash="cfg123456789abcdef",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "0.1.0", "pandas": "2.2.0"},
        determinism_caveats=["fixture controlado"],
        created_at=datetime(2026, 6, 24, 9, 30, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _performance_table() -> pd.DataFrame:
    """Tabla suficientemente larga para ejercer truncamiento visual auditado."""
    return pd.DataFrame(
        {
            "decile": list(range(12, 0, -1)),
            "pd": [index / 1000 for index in range(12)],
            "default_rate": [index / 100 for index in range(12)],
        }
    )


def _coefficients_table() -> pd.DataFrame:
    """Tabla de coeficientes sintética usada como artefacto y card embebida."""
    return pd.DataFrame(
        {
            "feature": ["mora", "saldo"],
            "beta": [-0.0, 1.25],
            "p_value": [0.04, 0.03],
        }
    )


def _bad_rule() -> Rule:
    """Regla canónica de default para el fixture end-to-end."""
    return Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),))


def _pipeline_frame() -> pd.DataFrame:
    """Dataset crudo estable con Desarrollo/Holdout por hash y OOT por cohorte."""
    index = pd.Index([f"op-{position:03d}" for position in range(30)], name="loan_id")
    return pd.DataFrame(
        {
            "score": [
                0,
                0,
                1,
                1,
                2,
                2,
                3,
                3,
                0,
                1,
                2,
                3,
                0,
                1,
                2,
                3,
                0,
                1,
                2,
                3,
                0,
                1,
                2,
                3,
                0,
                1,
                2,
                3,
                1,
                2,
            ],
            "segment": [
                "A",
                "B",
                "A",
                "B",
                "A",
                "B",
                "A",
                "B",
                "Z",
                "A",
                "B",
                "Z",
                "A",
                "Z",
                "A",
                "B",
                "B",
                "Z",
                "A",
                "Z",
                "A",
                "B",
                "Z",
                "A",
                "B",
                "Z",
                "A",
                "B",
                "Z",
                "A",
            ],
            "bad_flag": [
                1,
                0,
                1,
                0,
                0,
                1,
                0,
                1,
                0,
                1,
                0,
                0,
                1,
                0,
                1,
                0,
                0,
                1,
                0,
                1,
                1,
                0,
                1,
                0,
                0,
                1,
                0,
                1,
                0,
                1,
            ],
            "fecha": pd.to_datetime(
                [
                    "2024-01-01",
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-04",
                    "2024-01-05",
                    "2024-01-06",
                    "2024-01-07",
                    "2024-01-08",
                    "2024-02-01",
                    "2024-02-02",
                    "2024-02-03",
                    "2024-02-04",
                    "2024-02-05",
                    "2024-02-06",
                    "2024-02-07",
                    "2024-02-08",
                    "2024-03-01",
                    "2024-03-02",
                    "2024-03-03",
                    "2024-03-04",
                    "2024-03-05",
                    "2024-03-06",
                    "2024-03-07",
                    "2024-03-08",
                    "2024-04-01",
                    "2024-04-02",
                    "2024-04-03",
                    "2024-04-04",
                    "2024-04-05",
                    "2024-04-06",
                ]
            ),
            "cohort": ["dev"] * 24 + ["oot"] * 6,
        },
        index=index,
    )


def _pipeline_study(tmp_path: Path) -> Study:
    """Study con el pipeline F1 completo activado hasta ``report``."""
    return Study(
        NikodymConfig(
            repro=ReproConfig(seed=ROOT_SEED),
            data=DataConfig(
                schema_=SchemaConfig(
                    columns=(
                        ColumnSpec(name="score", dtype="int", nullable=False),
                        ColumnSpec(name="segment", dtype="str", nullable=False),
                        ColumnSpec(name="bad_flag", dtype="int", nullable=False),
                        ColumnSpec(name="fecha", dtype="datetime", nullable=False),
                        ColumnSpec(name="cohort", dtype="str", nullable=False),
                    ),
                    index_col="loan_id",
                ),
                target=TargetConfig(bad_rule=_bad_rule()),
                partition=PartitionConfig(
                    strategy=CohortSplitConfig(
                        cohort_col="cohort",
                        oot_cohorts=("oot",),
                        holdout_fraction=0.20,
                    ),
                    min_bads_per_partition=0,
                ),
            ),
            eda=EdaConfig(
                analysis_partition="todas",
                default_rate=DefaultRateConfig(
                    axis="period",
                    date_col="fecha",
                    min_obs_per_period=1,
                ),
                stability=TemporalStabilityConfig(threshold=10.0),
                univariate=UnivariateConfig(columns=("score", "segment"), n_quantile_bins=3),
            ),
            binning=BinningConfig(
                feature_columns=("score", "segment"),
                categorical_columns=("segment",),
                solver="mip",
                max_n_prebins=4,
                max_n_bins=4,
                min_bin_size=0.1,
                time_limit=5,
                monotonic_trend=None,
            ),
            selection=SelectionConfig(
                min_iv=0.0,
                correlation=CorrelationSelectionConfig(enabled=False),
                vif=VifSelectionConfig(enabled=False),
                stability=StabilitySelectionConfig(enabled=False),
            ),
            model=ModelConfig(
                stepwise=StepwiseConfig(direction="none"),
                sign_policy=SignPolicyConfig(action="flag", fail_on_forced_inverted=False),
                iv_contribution=IvContributionConfig(action="flag"),
            ),
            scorecard=ScorecardConfig(rounding_method="none"),
            calibration=CalibrationConfig(
                target_pd=0.31,
                anchor_source="business_input",
                min_fit_rows=1,
            ),
            performance=PerformanceConfig(
                n_deciles=2,
                min_rows_per_partition=1,
                min_events_per_partition=1,
            ),
            stability=StabilityConfig(
                psi_bins=2,
                csi_bins=2,
                temporal_column="cohort",
                include_pd_stability=False,
            ),
            report=ReportConfig(
                output_dir=str(tmp_path),
                sections=SectionPolicyConfig(max_table_rows=10),
            ),
        )
    )


def _inject_pipeline_frame(study: Study) -> None:
    """Inyecta el frame crudo bajo la clave pública de ``DataStep``."""
    study.artifacts.set("data", INPUT_FRAME_KEY, _pipeline_frame())
