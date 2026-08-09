"""Gates de coherencia entre la prosa publicada y el comportamiento efectivo del motor."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from nikodym.data.config import MissingConfig
from nikodym.report.prose import conclusions_body, executive_view, methodology_body, results_body
from nikodym.report.results import ReportInputBundle
from nikodym.selection.config import SelectionConfig, StabilitySelectionConfig
from nikodym.stability.config import StabilityConfig
from nikodym.validation.config import StabilityValidationConfig


def _bundle(
    *,
    cards: dict[str, Any] | None = None,
    pipeline_params: dict[str, Any] | None = None,
) -> ReportInputBundle:
    """Bundle estructural mínimo para ejercer la prosa sin inventar artefactos aguas arriba."""
    return cast(
        ReportInputBundle,
        SimpleNamespace(
            cards=cards or {},
            pipeline_params=pipeline_params or {},
            results={},
            currency="",
            missing_sections=(),
        ),
    )


def test_max_missing_rate_publica_auditoria_y_no_rechazo() -> None:
    """El umbral registra una decisión: no elimina ni rechaza la variable (SDD-02)."""
    texto = " ".join(
        methodology_body(
            _bundle(
                pipeline_params={
                    "data": {"missing": {"max_missing_rate": 0.30, "special_values": []}}
                }
            ),
            "data",
        )
    )

    assert "se reporta para revisión toda variable con más de 30,00 %" in texto
    assert "rechaza" not in texto
    assert "sin eliminarla automáticamente" in texto
    field = MissingConfig.model_fields["max_missing_rate"]
    assert field.title == "Umbral de revisión por tasa de nulos"
    assert "ninguna etapa las elimina automáticamente" in (field.description or "")
    assert "por sobre el cual" in str((field.json_schema_extra or {}).get("ui_help", ""))


def test_max_iv_publica_la_frontera_inclusiva_en_informe_y_formulario() -> None:
    """El selector aplica ``iv >= max_iv``; las dos caras públicas deben decirlo."""
    texto = " ".join(
        methodology_body(
            _bundle(
                pipeline_params={
                    "selection": {"min_iv": 0.02, "max_iv": 0.50, "max_iv_action": "flag"}
                }
            ),
            "selection",
        )
    )
    field = SelectionConfig.model_fields["max_iv_action"]
    help_text = str((field.json_schema_extra or {}).get("ui_help", ""))

    assert "IV igual o superior a 0,50" in texto
    assert "igual o superior a max_iv" in (field.description or "")
    assert "al alcanzar o superar" in help_text


def test_resultados_publican_deciles_efectivos_por_particion() -> None:
    """Con poblaciones pequeñas se informan los grupos producidos, no sólo el máximo pedido."""
    performance = {
        "evaluation_source": "pd_calibrated",
        "partitions": ["desarrollo", "holdout"],
        "max_metrics_by_partition": {
            "desarrollo": {"auc": 0.70, "gini": 0.40, "ks": 0.30},
            "holdout": {"auc": 0.68, "gini": 0.36, "ks": 0.28},
        },
        "bands_by_partition": {"desarrollo": "ok", "holdout": "ok"},
        "n_deciles": 10,
        "metric_sections": {
            "discrimination": {"effective_deciles_by_partition": {"desarrollo": 2, "holdout": 5}}
        },
    }

    texto = " ".join(results_body(_bundle(cards={"performance": performance}), "performance"))

    assert "hasta 10 tramos de riesgo configurados" in texto
    assert "Desarrollo: 2" in texto
    assert "Holdout: 5" in texto
    assert "ordenados por la PD calibrada" in texto
    assert "reparte la población en 10 tramos" not in texto


def test_direct_loss_rate_publica_la_formula_ejecutada_y_el_rol_real_de_la_pd() -> None:
    """La tasa directa no se descompone en PD/LGD; la PD sólo forma bandas cuando corresponde."""
    card = {
        "method": "direct_loss_rate",
        "total_internal_provision": 260_000.0,
        "n_groups": 3,
        "pd_source": "calibration",
        "grouping": "score_band",
        "metric_sections": {
            "provisioning_internal": {
                "metodo": (
                    "provisión = exposición del grupo · tasa de pérdida esperada directa del grupo."
                ),
                "lgd_method": None,
            }
        },
    }

    texto = " ".join(
        results_body(_bundle(cards={"provisioning_internal": card}), "provisioning_internal")
    )

    assert "exposición del grupo · tasa de pérdida esperada directa del grupo" in texto
    assert "no se descompone en PD y LGD" in texto
    assert "La PD calibrada sólo se usó para formar las bandas" in texto
    assert "el modelo del banco entra por aquí en el número reportado" not in texto


def test_pd_lgd_conserva_su_formula_y_procedencia() -> None:
    """Control simétrico: corregir la tasa directa no debe callar la rama PD·LGD."""
    card = {
        "method": "pd_lgd",
        "total_internal_provision": 84_000.0,
        "n_groups": 2,
        "pd_source": "calibration",
        "grouping": "provided",
        "metric_sections": {
            "provisioning_internal": {
                "metodo": (
                    "provisión = exposición del grupo · PD estimada · pérdida dado el "
                    "incumplimiento."
                ),
                "lgd_method": "provided",
            }
        },
    }

    texto = " ".join(
        results_body(_bundle(cards={"provisioning_internal": card}), "provisioning_internal")
    )

    assert "exposición del grupo · PD estimada · pérdida dado el incumplimiento" in texto
    assert "La PD proviene de la PD calibrada del scorecard" in texto
    assert "La severidad la aporta la institución" in texto


def test_resumen_psi_publica_magnitud_identidad_banda_y_fronteras_coherentes() -> None:
    """El peor valor, su identidad y su banda forman una sola observación auditable."""
    stability = {
        "comparisons": ["dev_vs_holdout"],
        "stable_threshold": 0.10,
        "review_threshold": 0.25,
        "max_psi_by_comparison": {"dev_vs_holdout": 0.12},
        "psi_metric_by_comparison": {"dev_vs_holdout": "pd_psi"},
        "bands_by_comparison": {"dev_vs_holdout": "review"},
        "psi_bins": 10,
        "worst_csi_feature": None,
        "worst_csi_value": None,
    }
    bundle = _bundle(cards={"stability": stability})

    texto_resultados = " ".join(results_body(bundle, "stability"))
    texto_conclusiones = " ".join(conclusions_body(bundle))
    vista_ejecutiva = executive_view(bundle)
    metrica_psi = next(metric for metric in vista_ejecutiva.metrics if "PSI" in metric.label)

    assert "El peor PSI entre score y PD" in texto_resultados
    assert "corresponde a la PD calibrada" in texto_resultados
    assert "0,1200" in texto_resultados
    assert "Requiere revisión" in texto_resultados
    assert "PSI del score 0,1200" not in texto_resultados
    assert metrica_psi.label == "Peor PSI entre score y PD · PD calibrada"
    assert metrica_psi.value == "0,1200"
    assert metrica_psi.band == "Requiere revisión"
    assert "Estabilidad (peor PSI entre score y PD)" in texto_conclusiones
    assert "PD calibrada" in texto_conclusiones
    assert "redesarrollo desde 0,25" in " ".join(vista_ejecutiva.notes)

    for config_class in (StabilitySelectionConfig, StabilityConfig, StabilityValidationConfig):
        stable_field = config_class.model_fields[
            "stable_threshold"
            if config_class is StabilitySelectionConfig
            else "psi_stable_threshold"
        ]
        review_field = config_class.model_fields[
            "review_threshold"
            if config_class is StabilitySelectionConfig
            else "psi_review_threshold"
        ]
        assert "bajo" in (stable_field.description or "").lower()
        assert "alcanzar o superar" in (review_field.description or "").lower()


def test_resumen_psi_score_y_card_legacy_no_inventan_identidad() -> None:
    """Control simétrico A1 y compatibilidad de lectura con cards 1.x."""
    base = {
        "comparisons": ["dev_vs_holdout"],
        "stable_threshold": 0.10,
        "review_threshold": 0.25,
        "max_psi_by_comparison": {"dev_vs_holdout": 0.18},
        "bands_by_comparison": {"dev_vs_holdout": "review"},
        "psi_bins": 10,
        "worst_csi_feature": None,
        "worst_csi_value": None,
    }
    score = dict(base, psi_metric_by_comparison={"dev_vs_holdout": "score_psi"})
    legacy = dict(base)

    score_text = " ".join(results_body(_bundle(cards={"stability": score}), "stability"))
    legacy_text = " ".join(results_body(_bundle(cards={"stability": legacy}), "stability"))

    assert "corresponde al score" in score_text
    assert "corresponde a la PD calibrada" not in score_text
    assert "corresponde al score" not in legacy_text
    assert "corresponde a la PD calibrada" not in legacy_text
