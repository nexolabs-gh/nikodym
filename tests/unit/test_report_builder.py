"""Tests de ``ReportBuilder``: recolección, secciones, faltantes e import liviano."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import BaseModel, ConfigDict

import nikodym.report as report_pkg
from nikodym.core.config import NikodymConfig
from nikodym.core.lineage import LineageBundle
from nikodym.core.study import Study
from nikodym.data.card import DataCardSection
from nikodym.report import document
from nikodym.report.builder import CANONICAL_SECTION_ORDER, ReportBuilder
from nikodym.report.config import (
    AiNarrationConfig,
    DocumentStructureConfig,
    ReportConfig,
    SectionPolicyConfig,
)
from nikodym.report.exceptions import ReportInputError
from nikodym.report.prose import executive_view, limitations_body
from nikodym.validation.results import (
    BacktestRecord,
    CalibrationTestRecord,
    DiscriminationRecord,
    ValidationCardSection,
    ValidationResult,
)

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
    assert emitidos == tuple(
        spec.id
        for spec in document.CHAPTER_SPECS
        if not spec.requires_domain and not spec.requires_result
    )
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

    builder = ReportBuilder.from_config(ReportConfig())
    bundle = builder.collect(study)

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


def _data_card() -> DataCardSection:
    """DataCardSection real con valores literales conocidos para el oracle del informe."""
    return DataCardSection(
        source="poblacion.parquet",
        n_rows=1_000,
        n_features=8,
        target_col="target",
        bad_rate=0.25,
        class_counts={"good": 750, "bad": 250},
        partition_sizes={"desarrollo": 600, "holdout": 200, "oot": 200},
        partition_bad_rates={"desarrollo": 0.20, "holdout": 0.25, "oot": 0.40},
        performance_window_months=12,
        exclusions_by_reason={"ventana_incompleta": 17},
        data_hash="data-card-hash",
    )


def _validation_result() -> ValidationResult:
    """ValidationResult real con una fila conocida por familia, creado fuera de ``report``."""
    discrimination_record = DiscriminationRecord(
        partition="oot",
        n_total=200,
        n_bad=80,
        auc=0.81,
        gini=0.62,
        ks=0.48,
        source="performance_artifact",
        status="ok",
    )
    calibration_record = CalibrationTestRecord(
        partition="oot",
        test="hosmer_lemeshow",
        n_groups=10,
        degrees_of_freedom=8,
        statistic=7.5,
        p_value=0.48,
        alpha=0.05,
        decision="pass",
    )
    backtest_record = BacktestRecord(
        parameter="pd",
        segment="retail",
        n=200,
        predicted_mean=0.25,
        realised_mean=0.24,
        test="jeffreys",
        statistic=-0.2,
        p_value=0.60,
        alpha=0.05,
        one_sided=True,
        decision="pass",
    )
    discrimination = pd.DataFrame(
        {
            "partition": ["oot"],
            "n_total": [200],
            "n_bad": [80],
            "auc": [0.81],
            "gini": [0.62],
            "ks": [0.48],
            "source": ["performance_artifact"],
            "status": ["ok"],
        }
    )
    calibration = pd.DataFrame(
        {
            "partition": ["oot"],
            "test": ["hosmer_lemeshow"],
            "grade": ["ALL"],
            "n": [200],
            "observed_defaults": [80],
            "expected_pd": [0.25],
            "observed_dr": [0.40],
            "statistic": [7.5],
            "degrees_of_freedom": [8],
            "p_value": [0.48],
            "alpha": [0.05],
            "decision": ["pass"],
            "traffic_light": [None],
        }
    )
    stability = pd.DataFrame(
        {
            "metric": ["score_psi"],
            "comparison": ["dev_vs_oot"],
            "feature": ["score"],
            "value": [0.08],
            "stable_threshold": [0.10],
            "review_threshold": [0.25],
            "band": ["stable"],
            "action": ["none"],
            "source": ["stability_artifact"],
            "status": ["ok"],
            "decision": ["pass"],
        }
    )
    backtesting = pd.DataFrame(
        {
            "parameter": ["pd"],
            "segment": ["retail"],
            "n": [200],
            "predicted_mean": [0.25],
            "realised_mean": [0.24],
            "test": ["jeffreys"],
            "statistic": [-0.2],
            "p_value": [0.60],
            "alpha": [0.05],
            "one_sided": [True],
            "decision": ["pass"],
        }
    )
    card = ValidationCardSection(
        model_ref="scorecard@oracle",
        families_run=("discrimination", "calibration", "stability", "backtesting"),
        overall_status="pass",
        n_tests=4,
        n_failed=0,
        dependency_versions={"pandas": "2.3.3"},
        falta_dato=(),
        metric_sections={},
    )
    return ValidationResult(
        discrimination=discrimination,
        calibration=calibration,
        stability=stability,
        backtesting=backtesting,
        discrimination_records=(discrimination_record,),
        calibration_records=(calibration_record,),
        grade_records=(),
        backtest_records=(backtest_record,),
        card=card,
    )


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


def test_data_y_validation_reales_se_proyectan_literalmente_y_sin_mutar_upstream() -> None:
    """Oracle independiente: DTOs reales creados fuera de report pasan sin recalcular números."""
    from nikodym.ui.presets import standard_preset

    study = _study_completo()
    study.config = NikodymConfig.model_validate(standard_preset()["config"])
    data_card = _data_card()
    validation = _validation_result()
    study.artifacts.set("data", "data_card", data_card)
    study.artifacts.set("validation", "card", validation.card)
    study.artifacts.set("validation", "result", validation)
    study.artifacts.set("provisioning", "card", {"summary": "provisioning-card"})

    builder = ReportBuilder.from_config(ReportConfig())
    bundle = builder.collect(study)
    by_id = {section.id: section for section in bundle.sections}
    ids = [section.id for section in bundle.sections]

    assert ids.index("context.data") < ids.index("context.eda")
    assert by_id["context.data"].title == "Población, particiones y exclusiones"
    assert ids.index("results") < ids.index("validation") < ids.index("provisions")
    assert [section.id for section in bundle.sections if section.id.startswith("validation.")] == [
        "validation.discrimination",
        "validation.calibration",
        "validation.stability",
        "validation.backtesting",
    ]
    assert "corresponde al validador humano" in " ".join(by_id["validation"].body)
    assert by_id["validation"].placeholder is not None

    assert_frame_equal(
        bundle.tables["data.states"],
        pd.DataFrame({"Estado": ["good", "bad"], "Observaciones": [750, 250]}),
    )
    assert_frame_equal(
        bundle.tables["data.partitions"],
        pd.DataFrame(
            {
                "Partición": ["desarrollo", "holdout", "oot"],
                "Observaciones": [600, 200, 200],
                "Tasa de incumplimiento": [0.20, 0.25, 0.40],
            }
        ),
    )
    assert_frame_equal(
        bundle.tables["data.exclusions"],
        pd.DataFrame({"Motivo": ["ventana_incompleta"], "Exclusiones": [17]}),
    )
    for family in ("discrimination", "calibration", "stability", "backtesting"):
        assert_frame_equal(bundle.tables[f"validation.{family}"], getattr(validation, family))

    # El DTO agregado queda preservado como oracle y las lecturas del bundle son defensivas.
    assert isinstance(bundle.results["validation"], ValidationResult)
    returned = bundle.results["validation"].discrimination
    returned.at[0, "auc"] = 0.01
    assert validation.discrimination.at[0, "auc"] == 0.81

    # Anexo C: data/validation y cada dominio configurado llevan config efectivo namespaced.
    appendix_by_domain = {
        section.source_domain: section
        for section in bundle.sections
        if section.id.startswith("appendix_parameters.")
    }
    for domain, effective_config in bundle.pipeline_params.items():
        assert appendix_by_domain[domain].payload["effective_config"] == effective_config
    assert (
        by_id["appendix_parameters.data"].payload["effective_config"]["target"]["target_col"]
        == "target"
    )
    assert (
        by_id["appendix_parameters.validation"].payload["effective_config"]["calibration"][
            "binomial_by_grade"
        ]
        is False
    )
    assert by_id["appendix_parameters.model"].payload["effective_config"]["engine"] == "logit"

    # Los dominios config-only también quedan auditables: Anexo C no depende de una card.
    config_only = bundle.model_copy(
        update={
            "pipeline_params": {
                **bundle.pipeline_params,
                "markov": {"states": ["al_dia", "mora"]},
                "forward": {"scenario": "base"},
            }
        },
        deep=True,
    )
    config_only_sections = builder.build_sections(config_only)
    config_only_by_id = {section.id: section for section in config_only_sections}
    assert config_only_by_id["appendix_parameters.markov"].payload == {
        "effective_config": {"states": ["al_dia", "mora"]}
    }
    assert config_only_by_id["appendix_parameters.forward"].payload == {
        "effective_config": {"scenario": "base"}
    }

    # Mutar la presentación no muta los DTOs aguas arriba.
    projected_tables = bundle.tables
    projected_tables["data.partitions"].loc[0, "Observaciones"] = 999
    assert data_card.partition_sizes["desarrollo"] == 600


def test_sin_validation_omite_capitulo_tablas_metrica_y_frases_positivas() -> None:
    """Control negativo: una Study sin validation no aparenta haber ejecutado validación formal."""
    bundle = ReportBuilder.from_config(ReportConfig()).collect(_study_completo())

    ids = {section.id for section in bundle.sections}
    assert "validation" not in ids
    assert not any(section_id.startswith("validation.") for section_id in ids)
    assert not any(key.startswith("validation.") for key in bundle.tables)
    assert "validation" not in bundle.results
    assert "Estado técnico de validación formal" not in " ".join(
        paragraph for section in bundle.sections for paragraph in section.body
    )

    # Una card aislada se conserva para auditoría en Anexo C, pero no sustituye el DTO atómico.
    card_only_study = _study_completo()
    card_only_study.artifacts.set("validation", "card", _validation_result().card)
    card_only = ReportBuilder.from_config(ReportConfig()).collect(card_only_study)
    assert "validation" in card_only.cards
    assert "validation" not in card_only.results
    assert "validation" not in {section.id for section in card_only.sections}
    assert not any(
        metric.label == "Estado técnico de validación formal"
        for metric in executive_view(card_only).metrics
    )
    assert "no ejecutó la capa de validación formal" in " ".join(limitations_body(card_only))


def test_capitulo_ifrs9_es_condicional_a_su_card() -> None:
    """El capítulo IFRS 9 (``requires_domain="provisioning_ifrs9"``) solo existe con su card.

    Mismo mecanismo que el capítulo de provisiones (SDD-28 D5), aplicado a la ECL (SDD-16): el
    informe de un scorecard no trae un capítulo IFRS 9 vacío, y el de una corrida ECL sí lo trae,
    en su posición canónica (tras el de provisiones si existiera, antes de Conclusiones).
    """
    builder = ReportBuilder.from_config(ReportConfig())

    # --- Sin la card del dominio: el capítulo NO existe ---
    sin_ifrs9 = builder.collect(_study_completo())
    ids_sin = [s.id for s in sin_ifrs9.sections if s.level == 1]
    assert "ifrs9" not in ids_sin

    # --- Con la card: el capítulo aparece, con su subsección de dominio, y desplaza el resto ---
    study = _study_completo()
    study.artifacts.set("provisioning_ifrs9", "card", {"summary": "ifrs9-card"})
    con_ifrs9 = builder.collect(study)
    ids_con = [s.id for s in con_ifrs9.sections if s.level == 1]
    assert "ifrs9" in ids_con
    numeros_con = {s.id: s.number for s in con_ifrs9.sections if s.level == 1}
    assert numeros_con["ifrs9"] == "5"
    assert numeros_con["conclusions"] == "6", "el capítulo nuevo no desplazó la numeración"
    subsecciones = [s.id for s in con_ifrs9.sections if s.id.startswith("ifrs9.")]
    assert subsecciones == ["ifrs9.provisioning_ifrs9"]


def test_ficha_ifrs9_y_anexo_c_comparten_config_y_cards_f4() -> None:
    """F4 publica la ficha source-backed y las dos cards crudas en el Anexo C."""
    from nikodym.ui.presets import ifrs9_preset

    study = Study(NikodymConfig.model_validate(ifrs9_preset()["config"]))
    study.run_context.lineage = _lineage()
    study.artifacts.set(
        "survival",
        "card",
        {
            "method": "discrete_hazard",
            "pd_source": "none",
            "time_unit": "year",
            "n_rows": 6_000,
            "n_events": 1_502,
            "n_periods": 5,
            "diagnostics": {"n_censored": 4_498},
            "metric_sections": {"fit": {"link": "logit"}},
        },
    )
    study.artifacts.set(
        "provisioning_ifrs9",
        "card",
        {
            "term_structure_source": "survival",
            "pit_mode": "ttc_only",
            "scenarios": ("base",),
            "scenario_weights": {"base": 1.0},
            "falta_dato": ("FALTA-DATO-IFRS-4",),
            "metric_sections": {"staging_migration": {"stage_1": 5_235}},
        },
    )

    bundle = ReportBuilder.from_config(
        ReportConfig(sections=SectionPolicyConfig(required_sections=()))
    ).collect(study)
    by_id = {section.id: section for section in bundle.sections}

    metodologia = by_id["methodology.provisioning_ifrs9"]
    body = " ".join(metodologia.body)
    assert "Activo en esta corrida:" in body
    assert "6.000 filas · 1.502 eventos · horizonte 5 años" in body
    assert "LGD provided · EAD provided" in body
    assert "30/90 días + is_default" in body
    assert "Base 100 %" in body
    assert "EIR anual" in body
    assert "Capacidad no ejercida en esta corrida:" in body
    assert "Forward-looking" in body and "Markov" in body

    anexo_survival = by_id["appendix_parameters.survival"]
    anexo_ifrs9 = by_id["appendix_parameters.provisioning_ifrs9"]
    assert anexo_survival.payload["n_events"] == 1_502
    assert anexo_survival.payload["effective_config"]["time_grid"]["horizon_periods"] == 5
    assert anexo_survival.metric_sections == {"fit": {"link": "logit"}}
    assert anexo_ifrs9.payload["scenario_weights"] == {"base": 1.0}
    assert anexo_ifrs9.payload["effective_config"]["staging"]["dpd_sicr_backstop"] == 30
    assert anexo_ifrs9.metric_sections == {"staging_migration": {"stage_1": 5_235}}
    assert anexo_survival.number < anexo_ifrs9.number

    # Los parámetros que alimentan la ficha vienen del config efectivo del mismo Study.
    assert bundle.pipeline_params["survival"]["time_grid"]["horizon_periods"] == 5
    assert bundle.pipeline_params["provisioning_ifrs9"]["staging"]["dpd_sicr_backstop"] == 30


@pytest.mark.parametrize("term_source", ["forward", "markov"])
def test_ficha_ifrs9_informe_admite_fuente_no_survival(
    term_source: Literal["forward", "markov"],
) -> None:
    """El informe usa el DTO común sin inventar referencias survival para otras fuentes."""
    from nikodym.provisioning.ifrs9.config import (
        IfrsPdConfig,
        IfrsProvisioningConfig,
        IfrsScenarioConfig,
    )

    study = Study(
        NikodymConfig(
            provisioning_ifrs9=IfrsProvisioningConfig(
                pd=IfrsPdConfig(term_structure_source=term_source, pit_mode="ttc_only"),
                scenarios=IfrsScenarioConfig(source="single"),
            )
        )
    )
    study.run_context.lineage = _lineage()
    study.artifacts.set(
        "provisioning_ifrs9",
        "card",
        {
            "term_structure_source": term_source,
            "pit_mode": "ttc_only",
            "scenarios": ("base",),
            "scenario_weights": {"base": 1.0},
            "falta_dato": (),
        },
    )

    bundle = ReportBuilder.from_config(
        ReportConfig(sections=SectionPolicyConfig(required_sections=()))
    ).collect(study)
    by_id = {section.id: section for section in bundle.sections}
    body = " ".join(by_id["methodology.provisioning_ifrs9"].body)

    assert f"La term-structure activa proviene de {term_source}." in body
    assert "config.survival" not in body
    assert "survival.card" not in body
    assert "Fuentes técnicas: config.provisioning_ifrs9, provisioning_ifrs9.card." in body
    if term_source == "forward":
        assert "La term-structure activa proviene de forward, no de Markov." in body
    else:
        assert "Matrices de transición Markov" not in body


def test_capitulo_resultados_es_condicional_any_of_a_los_dominios_scorecard() -> None:
    """«Resultados» (``requires_any_domain=RESULT_DOMAINS``) se omite si ningún dominio corrió.

    Es la cadena standalone IFRS 9 (``data → survival → provisioning_ifrs9``): sin etapas de
    scorecard el informe no debe traer un capítulo «Resultados» vacío — su resultado de negocio
    vive en el capítulo condicional IFRS 9 — y la numeración no deja huecos. Con al menos un
    dominio scorecard presente, la condición any-of lo mantiene (guardia del informe F1).
    """
    builder = ReportBuilder.from_config(
        ReportConfig(sections=SectionPolicyConfig(required_sections=()))
    )
    sin_scorecard = _study_completo(
        omit=(
            "binning",
            "selection",
            "model",
            "scorecard",
            "calibration",
            "performance",
            "stability",
        )
    )
    sin_scorecard.artifacts.set("survival", "card", {"summary": "survival-card"})
    sin_scorecard.artifacts.set("provisioning_ifrs9", "card", {"summary": "ifrs9-card"})
    bundle = builder.collect(sin_scorecard)
    ids = [s.id for s in bundle.sections if s.level == 1]
    assert "results" not in ids
    assert "ifrs9" in ids
    numeros = {s.id: s.number for s in bundle.sections if s.level == 1}
    assert numeros["methodology"] == "3"
    assert numeros["ifrs9"] == "4", "la numeración dejó un hueco al omitir «Resultados»"
    assert numeros["conclusions"] == "5"

    # Con un solo dominio scorecard (``model``) la condición any-of mantiene el capítulo.
    con_model = builder.collect(
        _study_completo(
            omit=("binning", "selection", "scorecard", "calibration", "performance", "stability")
        )
    )
    assert "results" in [s.id for s in con_model.sections if s.level == 1]


def test_limitaciones_ifrs9_distingue_curva_standalone_de_scorecard() -> None:
    """La salvedad de Limitaciones espeja cómo se ajustó la curva (SDD-16/SDD-18).

    Standalone (``pd_source='none'``) la corrida no estima ningún modelo PD de scorecard:
    afirmar que «se estimó en esta misma corrida» sería falso. Con fuente PD de F1 el texto
    original se mantiene.
    """
    builder = ReportBuilder.from_config(
        ReportConfig(sections=SectionPolicyConfig(required_sections=()))
    )
    omit = (
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
        "stability",
    )

    standalone = _study_completo(omit=omit)
    standalone.artifacts.set("survival", "card", {"pd_source": "none"})
    standalone.artifacts.set("provisioning_ifrs9", "card", {"summary": "ifrs9-card"})
    bundle = builder.collect(standalone)
    body = next(s for s in bundle.sections if s.id == "limitations").body
    assert any("autocontenida" in paragraph for paragraph in body)
    assert not any("El modelo PD que alimenta la curva" in paragraph for paragraph in body)

    con_scorecard = _study_completo(omit=omit)
    con_scorecard.artifacts.set("survival", "card", {"pd_source": "model_raw"})
    con_scorecard.artifacts.set("provisioning_ifrs9", "card", {"summary": "ifrs9-card"})
    bundle = builder.collect(con_scorecard)
    body = next(s for s in bundle.sections if s.id == "limitations").body
    assert any("El modelo PD que alimenta la curva" in paragraph for paragraph in body)
