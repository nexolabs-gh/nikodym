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
from nikodym.report import document
from nikodym.report.builder import CANONICAL_SECTION_ORDER, ReportBuilder
from nikodym.report.config import (
    AiNarrationConfig,
    DocumentStructureConfig,
    ReportConfig,
    SectionPolicyConfig,
)
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


def test_collect_arma_el_documento_y_manifest_pre_render_golden() -> None:
    """``collect`` arma el DOCUMENTO (capítulos + anexos), no una sección por card.

    Los ocho dominios del pipeline dejan de ser secciones de primer nivel: aparecen como
    subsecciones de Resultados y de los anexos. El dump crudo (payload y ``metric_sections``) vive
    sólo en el Anexo C; el cuerpo lleva prosa y las tablas que importan.
    """
    study = _study_completo()
    builder = ReportBuilder.from_config(ReportConfig())

    bundle = builder.collect(study)
    manifest = builder.build_manifest(bundle, path="reports/scorecard_report.html")
    by_id = {section.id: section for section in bundle.sections}

    # Los capítulos de primer nivel son el documento, en el orden canónico. Se verifica
    # SUBSECUENCIA, no igualdad: los capítulos condicionales (`ChapterSpec.requires_domain`) solo
    # se emiten si su dominio corrió, así que un informe concreto emite un subconjunto ordenado.
    emitidos = tuple(section.id for section in bundle.sections if section.level == 1)
    assert set(emitidos) <= set(CANONICAL_SECTION_ORDER)
    posiciones = [CANONICAL_SECTION_ORDER.index(seccion) for seccion in emitidos]
    assert posiciones == sorted(posiciones), "los capítulos no respetan el orden canónico"
    # Este bundle no activa ningún capítulo condicional ⇒ están todos los incondicionales.
    assert emitidos == tuple(spec.id for spec in document.CHAPTER_SPECS if not spec.requires_domain)
    assert bundle.missing_sections == ()
    assert bundle.cards["performance"] == {
        "summary": "performance-card",
        "metric_sections": {"performance": {"auc": 0.74321}},
    }

    # Numeración: 1-6 para capítulos, A/B/C para anexos, N.M para subsecciones.
    assert by_id["introduction"].number == "1"
    assert by_id["limitations"].number == "6"
    assert by_id["appendix_lineage"].number == "A"
    assert by_id["appendix_tables"].number == "B"
    assert by_id["appendix_parameters"].number == "C"
    assert by_id["results.model"].number.startswith("4.")
    assert by_id["results.model"].level == 2
    assert by_id["results.model"].kind == "data"
    assert by_id["results.model"].source_domain == "model"

    # El dump completo NO se pierde: se degrada al Anexo C.
    anexo_model = by_id["appendix_parameters.model"]
    assert anexo_model.kind == "appendix"
    assert anexo_model.payload["embedded_table"] == {"table_ref": "model.model_card.embedded_table"}
    assert anexo_model.metric_sections == {"model": {"p_value_max": 0.041}}
    # ...y el cuerpo no lo repite.
    assert by_id["results.model"].payload == {}

    # El lineage completo queda en el Anexo A.
    assert by_id["appendix_lineage"].payload["config_hash"] == "cfg123456789abcdef"

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


def test_metodologia_redacta_los_parametros_reales_del_config() -> None:
    """La Metodología describe lo que se ejecutó, con los parámetros REALES del config.

    Es el corazón de la mejora: antes estas secciones emitían "La sección X está disponible con
    estado included". Ahora el motor redacta el binning, la selección, el escalado y la calibración
    leyendo el config de la corrida, sin inventar un solo número.
    """
    bundle = ReportBuilder.from_config(ReportConfig()).collect(_study_completo())
    by_id = {section.id: section for section in bundle.sections}

    binning = " ".join(by_id["methodology.binning"].body)
    seleccion = " ".join(by_id["methodology.selection"].body)

    # Parámetros reales del BinningConfig del Study (solver mip, 4 bins, min_bin_size 0.10).
    assert "programación entera mixta (MIP)" in binning
    assert "máximo de 4 bins por variable" in binning
    assert "10.00 % de la población" in binning
    assert "ascendente o descendente" in binning  # monotonic_trend="auto_asc_desc"

    # Umbrales reales del SelectionConfig (min_iv=0.03, VIF 4.5, correlación spearman 0.80).
    assert "IV inferior a 0.03" in seleccion
    assert "VIF bajo 4.5" in seleccion
    assert "(spearman) sobre 0.80" in seleccion

    # Cero alucinación: sin card de scorecard/calibration en el fixture, no hay prosa inventada.
    assert "methodology.scorecard" not in by_id
    assert "methodology.calibration" not in by_id


def test_build_manifest_resuelve_formato_por_suffix_config_y_default() -> None:
    """El formato sale del path si es conocido; si no, cae al config o a HTML."""
    bundle = ReportBuilder.from_config(ReportConfig()).collect(_study_completo())
    ai_builder = ReportBuilder.from_config(
        ReportConfig(ai=AiNarrationConfig(enabled=True, provider="anthropic"))
    )
    pdf_builder = ReportBuilder.from_config(ReportConfig(formats=("pdf",)))
    empty_builder = ReportBuilder.from_config(ReportConfig(formats=()))

    ai_manifest = ai_builder.build_manifest(bundle, path="reports/informe.pdf")
    pdf_manifest = pdf_builder.build_manifest(bundle, path="reports/informe")
    default_manifest = empty_builder.build_manifest(bundle, path="reports/informe")

    assert ai_manifest.output_format == "pdf"
    assert ai_manifest.deterministic is False
    assert ai_manifest.ai_enabled is True
    assert pdf_manifest.output_format == "pdf"
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
    """Una card requerida ausente queda explícita en Resultados y sin métricas inventadas."""
    cfg = ReportConfig(sections=SectionPolicyConfig(missing_policy="warn"))
    bundle = ReportBuilder.from_config(cfg).collect(_study_completo(omit=("model",)))
    ids = tuple(section.id for section in bundle.sections)
    model_section = next(section for section in bundle.sections if section.id == "results.model")

    assert bundle.missing_sections == ("model",)
    assert model_section.status == "missing"
    assert model_section.payload == {
        "warning": (
            "Sección requerida ausente; el reporte parcial no inventa números ni rellena métricas."
        )
    }
    assert model_section.metric_sections == {}
    assert model_section.body == ()
    # Un dominio ausente no tiene parámetros que anexar ni metodología que describir.
    assert "appendix_parameters.model" not in ids
    assert "methodology.model" not in ids


def test_missing_policy_error_lanza_report_input_error() -> None:
    """La política default falla ruidosamente si falta una card requerida."""
    with pytest.raises(ReportInputError, match="dominio='model', clave='model_card'"):
        ReportBuilder.from_config(ReportConfig()).collect(_study_completo(omit=("model",)))


def test_missing_policy_skip_omite_seccion_y_la_declara_en_limitaciones() -> None:
    """``skip`` no renderiza la sección ausente, pero conserva trazabilidad."""
    cfg = ReportConfig(sections=SectionPolicyConfig(missing_policy="skip"))
    bundle = ReportBuilder.from_config(cfg).collect(_study_completo(omit=("model",)))
    ids = tuple(section.id for section in bundle.sections)
    limitations = next(section for section in bundle.sections if section.id == "limitations")

    assert "results.model" not in ids
    assert bundle.missing_sections == ("model",)
    assert limitations.payload["missing_sections"] == ("model",)
    assert any("model" in paragraph for paragraph in limitations.body)


def test_seccion_no_requerida_ausente_se_omite_sin_missing() -> None:
    """Una sección no requerida no se marca como faltante en reportes parciales."""
    cfg = ReportConfig(sections=SectionPolicyConfig(required_sections=_REQUIRED_WITHOUT_MODEL))
    bundle = ReportBuilder.from_config(cfg).collect(_study_completo(omit=("model",)))

    assert "results.model" not in tuple(section.id for section in bundle.sections)
    assert bundle.missing_sections == ()


def test_collect_sin_figures_deja_el_anexo_sin_figure_keys() -> None:
    """Las figuras son opcionales en el builder parcial."""
    bundle = ReportBuilder.from_config(ReportConfig()).collect(
        _study_completo(include_figures=False)
    )
    anexo = next(section for section in bundle.sections if section.id == "appendix_tables")

    assert bundle.figures == {}
    assert anexo.payload["figure_keys"] == ()


def test_placeholders_hide_retira_los_bloques_por_completar() -> None:
    """``placeholders='hide'`` produce el entregable final: sin bloques POR COMPLETAR.

    Los capítulos siguen ahí (y su prosa determinista también): lo que desaparece es la caja de
    guía que sólo sirve mientras el informe es un borrador.
    """
    show = ReportBuilder.from_config(ReportConfig()).collect(_study_completo())
    hide = ReportBuilder.from_config(
        ReportConfig(document=DocumentStructureConfig(placeholders="hide"))
    ).collect(_study_completo())

    con_guia = {section.id for section in show.sections if section.placeholder is not None}
    assert con_guia == {"introduction", "context", "conclusions"}
    assert all(section.placeholder is None for section in hide.sections)
    assert tuple(s.id for s in show.sections) == tuple(s.id for s in hide.sections)

    introduccion = next(s for s in show.sections if s.id == "introduction")
    assert introduccion.placeholder is not None
    assert introduccion.placeholder.title == "Introducción"
    assert introduccion.placeholder.guidance  # guía real, no lorem ipsum mudo


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
    """Config raíz con parámetros REALES de binning y selección.

    La prosa de Metodología los lee del config de la corrida (``bundle.pipeline_params``), así que
    el fixture debe traerlos: son justamente lo que el informe tiene que saber redactar.
    """
    return NikodymConfig.model_validate(
        {
            "binning": {
                "feature_columns": ("saldo",),
                "solver": "mip",
                "max_n_bins": 4,
                "min_bin_size": 0.10,
                "monotonic_trend": "auto_asc_desc",
            },
            "selection": {
                "min_iv": 0.03,
                "correlation": {"enabled": True, "method": "spearman", "threshold": 0.80},
                "vif": {"enabled": True, "threshold": 4.5},
                "stability": {"enabled": False},
            },
        }
    )


def test_capitulo_de_provisiones_es_condicional_a_su_card() -> None:
    """El capítulo REAL de provisiones (``requires_domain="provisioning"``) solo existe con su card.

    Es el mecanismo que permite que el informe de un scorecard **no** traiga un capítulo de
    provisiones vacío, y que el de una corrida con provisiones **sí** lo traiga — sin que el
    documento tenga que declarar por escrito que "las provisiones corresponden a fases posteriores".

    Se verifica sobre el ``CHAPTER_SPECS`` real (sin monkeypatch), en las dos direcciones: sin la
    card, el capítulo desaparece **y la numeración de los siguientes no deja huecos**; con la card,
    aparece en su posición canónica (tras Resultados, antes de Conclusiones) y desplaza el resto.
    """
    builder = ReportBuilder.from_config(ReportConfig())

    # --- Sin la card del dominio: el capítulo NO existe ---
    sin_provisiones = builder.collect(_study_completo())
    ids_sin = [s.id for s in sin_provisiones.sections if s.level == 1]
    assert "provisions" not in ids_sin
    numeros_sin = {s.id: s.number for s in sin_provisiones.sections if s.level == 1}
    assert numeros_sin["conclusions"] == "5"
    assert numeros_sin["limitations"] == "6", "la numeración dejó un hueco al omitir el capítulo"

    # --- Con la card: el capítulo aparece, y desplaza la numeración siguiente ---
    study = _study_completo()
    study.artifacts.set("provisioning", "card", {"summary": "provisioning-card"})
    con_provisiones = builder.collect(study)
    ids_con = [s.id for s in con_provisiones.sections if s.level == 1]
    assert "provisions" in ids_con
    numeros_con = {s.id: s.number for s in con_provisiones.sections if s.level == 1}
    assert numeros_con["provisions"] == "5"
    assert numeros_con["conclusions"] == "6", "el capítulo nuevo no desplazó la numeración"
    assert numeros_con["limitations"] == "7"
