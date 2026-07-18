"""Presets estándar del config F1 (SDD-23 §3.2, §5): configs curados *domain-agnostic*.

Un **preset estándar** es un config F1 COMPLETO y curado, alineado a las columnas de un dataset
sintético del registro (:mod:`nikodym.ui.datasets`), que corre end-to-end
(data→binning→selection→model→scorecard→calibration→performance→stability) y produce un scorecard
**sin que el usuario rellene ningún campo**. El front lo carga por defecto para que, "sin tocar
nada, ya funcione" (feedback de producto).

El preset es un **dict JSON-able literal**: NO se construye con ``BinningConfig(...)``/
``ModelConfig(...)`` porque ``nikodym.ui`` es *domain-agnostic* (SDD-23 §3.3; el test AST
``test_ui_no_importa_modulos_de_dominio`` veta importar módulos de dominio). El literal se
**derivó** construyendo el config con los objetos Pydantic de dominio en un script aparte y
volcándolo con ``model_dump(mode="json", by_alias=True)``; aquí se sirve tal cual y la validación
sigue siendo ``NikodymConfig.model_validate`` (no se reimplementa el schema). No editar el literal
a mano: regenerarlo con el mismo procedimiento si cambia una sección de dominio.

Los valores están curados para un **escaparate metodológicamente defendible** sobre el dataset
``consumo_comportamiento`` (6000 filas), verificado end-to-end: binning MIP con ``time_limit``
corto, **selección de variables activa** (stepwise bidireccional + filtros de correlación y VIF),
**estabilidad post-modelo activa** (PSI del score y de la PD calibrada dev_vs_holdout/dev_vs_oot,
CSI por característica y estabilidad temporal por cohorte, con umbrales 0.10/0.25) y políticas de
signo/IV en modo ``flag``. Sobre este dataset la selección
NO poda features —verificado: da las mismas métricas que el pipeline sin filtros (desarrollo
AUC≈0.71, Gini≈0.42, KS≈0.32)— pero deja ver el motor haciendo selección real, no un pipeline
crudo. Las 5 features numéricas producen el scorecard; ``segmento`` (ruido, sin señal de riesgo)
cae por ``min_iv``. La partición reserva la cohorte ``2024Q2`` como OOT (propia de
``consumo_comportamiento``), por lo que este preset es específico de ese dataset.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

__all__ = [
    "get_preset",
    "ifrs9_preset",
    "list_presets",
    "provisiones_preset",
    "standard_preset",
]

STANDARD_PRESET_ID = "f1-estandar-consumo"
STANDARD_DATASET_ID = "consumo_comportamiento"

PROVISIONES_PRESET_ID = "f3-provisiones-consumo"
PROVISIONES_DATASET_ID = "provisiones_consumo"

# Config F1 COMPLETO derivado de los objetos Pydantic de dominio (``model_dump(mode="json",
# by_alias=True)``) y pegado como literal para preservar la frontera domain-agnostic (SDD-23 §3.3).
# NO editar a mano: regenerar con el script de derivación si cambia una sección de dominio.
_STANDARD_CONFIG: dict[str, Any] = {
    "schema_version": "1.0.0",
    "name": "preset-estandar-consumo",
    "repro": {"seed": 20240706, "strict_determinism": False},
    "run": {"steps": None, "fail_fast": True},
    "data": {
        "type": "standard",
        "load": {
            "source": None,
            "file_format": "auto",
            "backend": "pandas",
            "csv_options": {"sep": ",", "decimal": ".", "encoding": "utf-8"},
        },
        "schema": {
            "columns": [
                {
                    "name": "ingreso_mensual",
                    "dtype": "float",
                    "nullable": False,
                    "required": True,
                    "coerce": False,
                    "ge": None,
                    "le": None,
                    "isin": None,
                    "unique": False,
                },
                {
                    "name": "deuda_ingreso",
                    "dtype": "float",
                    "nullable": False,
                    "required": True,
                    "coerce": False,
                    "ge": None,
                    "le": None,
                    "isin": None,
                    "unique": False,
                },
                {
                    "name": "utilizacion_linea",
                    "dtype": "float",
                    "nullable": False,
                    "required": True,
                    "coerce": False,
                    "ge": None,
                    "le": None,
                    "isin": None,
                    "unique": False,
                },
                {
                    "name": "mora_max_12m",
                    "dtype": "int",
                    "nullable": False,
                    "required": True,
                    "coerce": False,
                    "ge": None,
                    "le": None,
                    "isin": None,
                    "unique": False,
                },
                {
                    "name": "antiguedad_meses",
                    "dtype": "int",
                    "nullable": False,
                    "required": True,
                    "coerce": False,
                    "ge": None,
                    "le": None,
                    "isin": None,
                    "unique": False,
                },
                {
                    "name": "segmento",
                    "dtype": "str",
                    "nullable": False,
                    "required": True,
                    "coerce": False,
                    "ge": None,
                    "le": None,
                    "isin": None,
                    "unique": False,
                },
                {
                    "name": "cohorte",
                    "dtype": "str",
                    "nullable": False,
                    "required": True,
                    "coerce": False,
                    "ge": None,
                    "le": None,
                    "isin": None,
                    "unique": False,
                },
                {
                    "name": "bad_flag",
                    "dtype": "int",
                    "nullable": False,
                    "required": True,
                    "coerce": False,
                    "ge": None,
                    "le": None,
                    "isin": None,
                    "unique": False,
                },
            ],
            "strict": False,
            "ordered": False,
            "index_col": "loan_id",
            "unique_keys": None,
        },
        "missing": {"special_values": [], "max_missing_rate": 0.99},
        "target": {
            "target_col": "target",
            "bad_rule": {
                "all_of": [{"col": "bad_flag", "op": "==", "value": 1}],
                "any_of": [],
            },
            "good_rule": None,
            "indeterminate_rule": None,
            "exclusion_rules": [],
            "window": None,
        },
        "partition": {
            "strategy": {
                "type": "cohort",
                "cohort_col": "cohorte",
                "oot_cohorts": ["2024Q2"],
                "holdout_fraction": 0.2,
            },
            "ttd_includes_excluded": True,
            "min_bads_per_partition": 30,
        },
    },
    "markov": None,
    "eda": None,
    "binning": {
        "type": "standard",
        "feature_columns": [
            "ingreso_mensual",
            "deuda_ingreso",
            "utilizacion_linea",
            "mora_max_12m",
            "antiguedad_meses",
            "segmento",
        ],
        "exclude_columns": [],
        "categorical_columns": ["segmento"],
        "variable_overrides": [],
        "max_n_prebins": 20,
        "min_prebin_size": 0.05,
        "min_n_bins": None,
        "max_n_bins": 6,
        "min_bin_size": 0.05,
        "min_bin_n_event": 1,
        "min_bin_n_nonevent": 1,
        "monotonic_trend": "auto_asc_desc",
        "min_event_rate_diff": 0.0,
        "max_pvalue": None,
        "max_pvalue_policy": "consecutive",
        "solver": "mip",
        "mip_solver": "bop",
        "time_limit": 10,
        "require_optimal": True,
        "n_jobs": None,
        "special_handling": "separate",
        "metric_special": "empirical",
        "metric_missing": "empirical",
        "cat_cutoff": 0.01,
        "cat_unknown": None,
        "split_digits": None,
        "output_suffix": "__woe",
        "keep_structural_columns": True,
        "fail_on_non_binnable": False,
    },
    "selection": {
        "type": "standard",
        "feature_columns": "*",
        "exclude_columns": [],
        "force_include": [],
        "force_exclude": [],
        "min_iv": 0.02,
        "max_iv": 0.5,
        "max_iv_action": "flag",
        "compute_univariate_metrics": True,
        "min_auc": None,
        "min_ks": None,
        "min_gini": None,
        "priority_order": ["iv", "auc", "ks", "name"],
        "correlation": {
            "enabled": True,
            "method": "pearson",
            "threshold": 0.75,
            "clustering_method": "none",
        },
        "vif": {
            "enabled": True,
            "threshold": 5.0,
            "add_intercept": True,
            "max_iterations": None,
        },
        "stability": {
            "enabled": False,
            "action": "report_only",
            "stable_threshold": 0.1,
            "review_threshold": 0.25,
            "smoothing": 1e-06,
        },
        "keep_structural_columns": True,
        "fail_if_no_features": True,
    },
    "model": {
        "type": "standard",
        "engine": "logit",
        "fit_intercept": True,
        "optimizer": "newton",
        "fit_maxiter": 100,
        "tol": 1e-08,
        "alpha": 0.05,
        "stepwise": {
            "enabled": True,
            "direction": "bidirectional",
            "criterion": "wald_pvalue",
            "entry_p_value": 0.05,
            "exit_p_value": 0.05,
            "max_iter": 100,
            "min_features": 1,
        },
        "sign_policy": {
            "expected_beta_sign": "negative",
            "action": "flag",
            "fail_on_forced_inverted": False,
        },
        "iv_contribution": {"threshold": 0.9, "action": "flag"},
        "force_include": [],
        "force_exclude": [],
        "fail_if_no_features": True,
    },
    "scorecard": {
        "type": "standard",
        "pdo": 20.0,
        "target_score": 600.0,
        "target_odds": 50.0,
        "score_direction": "higher_is_lower_risk",
        "intercept_allocation": "uniform",
        "rounding_method": "nearest_integer",
        "output_suffix": "__points",
        "score_column": "score",
        "min_score": None,
        "max_score": None,
        "clip": False,
        "point_overrides": [],
    },
    "calibration": {
        "type": "standard",
        "method": "intercept_offset",
        "target_pd": 0.2,
        "anchor_kind": "through_the_cycle",
        "anchor_source": "business_input",
        "fit_partition": "desarrollo",
        "target_tolerance": 1e-12,
        "max_abs_offset": None,
        "max_iter": 100,
        "min_fit_rows": 30,
        "require_both_classes_for_supervised": True,
        "pd_raw_column": "pd_raw",
        "linear_predictor_column": "linear_predictor",
        "pd_calibrated_column": "pd_calibrated",
        "linear_predictor_calibrated_column": "linear_predictor_calibrated",
        "partition_column": "partition",
        "target_column": "target",
    },
    "tuning": None,
    "ml": None,
    "explain": None,
    "survival": None,
    "forward": None,
    "stress": None,
    "provisioning_cmf": None,
    "provisioning_ifrs9": None,
    "provisioning": None,
    "performance": {
        "schema_version": "1.0.0",
        "type": "standard",
        "score_column": "score",
        "pd_column": "pd_calibrated",
        "target_column": "target",
        "partition_column": "partition",
        "score_direction": "higher_is_lower_risk",
        "evaluation_source": "pd_calibrated",
        "partitions": ["desarrollo", "holdout", "oot"],
        "n_deciles": 10,
        "min_rows_per_partition": 30,
        "min_events_per_partition": 1,
        "optional_thresholds": {},
    },
    "stability": {
        "schema_version": "1.0.0",
        "type": "standard",
        "score_column": "score",
        "pd_column": "pd_calibrated",
        "partition_column": "partition",
        "score_direction": "higher_is_lower_risk",
        "psi_bins": 10,
        "csi_bins": 10,
        "psi_stable_threshold": 0.1,
        "psi_review_threshold": 0.25,
        "smoothing": 1e-06,
        "comparisons": ["dev_vs_holdout", "dev_vs_oot"],
        "temporal_axis": "period",
        "temporal_column": None,
        "temporal_freq": "M",
        "include_pd_stability": True,
        "csi_source": "score_points",
    },
    # Validación formal explícita para la demo F1, derivada de ``ValidationConfig(...).model_dump``.
    # Reúsa performance/stability y ejecuta HL+Brier sobre la PD calibrada. El fixture no trae
    # ``grade``: el contraste por grado queda apagado; backtesting tampoco se activa porque esta
    # corrida no tiene realizados IFRS 9. Los umbrales listados son defaults públicos del DTO, no
    # parámetros internos de una institución.
    "validation": {
        "schema_version": "1.0.0",
        "type": "standard",
        "families": ["discrimination", "calibration", "stability"],
        "discrimination": {
            "consume_performance": True,
            "partitions": ["desarrollo", "holdout", "oot"],
        },
        "calibration": {
            "hosmer_lemeshow": True,
            "hl_n_groups": 10,
            "hl_grouping": "deciles",
            "brier": True,
            "binomial_by_grade": False,
            "grade_col": "grade",
            "pd_test": "jeffreys",
            "alpha": 0.05,
            "traffic_light_green_alpha": 0.05,
            "traffic_light_red_alpha": 0.01,
            "target_column": "target",
            "pd_column": "pd_calibrated",
            "partition_column": "partition",
            "min_rows_per_group": 30,
        },
        "stability": {
            "consume_stability": True,
            "psi_stable_threshold": 0.1,
            "psi_review_threshold": 0.25,
        },
        "backtesting": {
            "enabled": False,
            "parameters": ["pd", "lgd", "ead"],
            "segment_col": "portfolio",
            "alpha": 0.05,
            "one_sided": True,
            "realised_pd_col": "realised_default",
            "realised_lgd_col": "realised_lgd",
            "realised_ead_col": "realised_ead",
            "pd_test": "jeffreys",
        },
        "fail_on_falta_dato": True,
    },
    # Report HTML determinístico activado. Derivado con ``ReportConfig(sections=SectionPolicyConfig(
    # required_sections=(...)))`` + ``model_dump(mode="json", by_alias=True)`` (NO editar a mano).
    # Las ``required_sections`` son las cards scorecard obligatorias (sin ``eda``); ``data_card`` y
    # ``validation.result`` se consumen de manera aditiva y no entran en ``ReportStep.requires``.
    # Así el motor CT-1 conserva el contrato estable de prerequisitos. ``report`` es INFRA
    # (``INFRA_SECTIONS``)
    # → NO entra al ``config_hash``. ``output_dir`` se cablea a un dir absoluto bajo el workdir en
    # ejecución (``routes._wire_report_output_dir``); aquí queda el default relativo.
    #
    # Se piden los CUATRO entregables (HTML + PDF + base editable .qmd + Word), no solo HTML: la UI
    # no expone una sección "Reporte" donde activarlos, así que con ``formats=["html"]`` los botones
    # de descarga del front respondían 404 SIEMPRE en uso real, y el reporte editable era una
    # función inalcanzable. El preset existe para que todo funcione sin tocar nada.
    #
    # PDF y DOCX viven tras extras opcionales (``weasyprint`` / ``python-docx``). Con
    # ``fail_if_unavailable=False`` una instalación mínima simplemente no los emite (aviso + 404 con
    # mensaje claro al descargar) en vez de tumbar la corrida entera: el HTML, que es el entregable
    # base, sale igual.
    "report": {
        "schema_version": "1.0.0",
        "type": "standard",
        "output_dir": "reports",
        "basename": "scorecard_report",
        "language": "es",
        "formats": ["html", "pdf", "md", "docx"],
        "html": {
            "template_id": "scorecard_basic_v1",
            "theme": "nikodym",
            "embed_assets": True,
            "include_interactive_charts": False,
            "deterministic_ids": True,
        },
        "pdf": {
            "enabled": True,
            "fail_if_unavailable": False,
        },
        "docx": {
            "fail_if_unavailable": False,
        },
        "ai": {
            "enabled": False,
            "provider": "none",
            "model": None,
            "api_key_env": "ANTHROPIC_API_KEY",
            "timeout_seconds": 20.0,
            "max_input_tokens": 12000,
            "send_raw_data": False,
            "label_ai_text": True,
        },
        "sections": {
            "required_sections": [
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
    },
    "audit": None,
    "governance": None,
    "tracking": None,
}


def standard_preset() -> dict[str, Any]:
    """Devuelve el descriptor del preset estándar F1 (config curado + dataset recomendado).

    Returns
    -------
    dict
        ``{id, name, description, config, dataset_id}``: un config F1 completo y JSON-able (copia
        defensiva, no el literal compartido) alineado a las columnas del dataset sintético
        ``consumo_comportamiento``. El ``config`` valida con ``NikodymConfig.model_validate`` y
        corre end-to-end produciendo un scorecard; ``dataset_id`` es el dataset recomendado para
        materializar y ejecutar la corrida (SDD-23 §3.2/§5).
    """
    return {
        "id": STANDARD_PRESET_ID,
        "name": "Preset estándar F1 — consumo (comportamiento)",
        "description": (
            "Config F1 completo y curado, listo para correr sin tocar nada: scorecard de "
            "comportamiento (data→binning→selection→model→scorecard→calibration→performance→"
            "stability) sobre el dataset sintético de consumo."
        ),
        "config": deepcopy(_STANDARD_CONFIG),
        "dataset_id": STANDARD_DATASET_ID,
    }


# ---------------------------------------------------------------------------------------------
# Preset F3 — provisiones (CMF estándar + método interno + regla del máximo)
# ---------------------------------------------------------------------------------------------
# El preset F3 es el MISMO scorecard base del F1 (data→binning→…→calibration→performance→stability)
# con dos añadidos: una calibración distinta y las tres secciones de provisiones. Se compone del F1
# por ``deepcopy`` + delta (``provisiones_preset``) en vez de duplicar ~380 líneas idénticas: es el
# mismo pipeline de scorecard, y debe seguir al F1 si éste cambia. La composición es pura
# manipulación de dicts JSON-able —NO importa ``nikodym.provisioning``—, así que respeta la frontera
# domain-agnostic (SDD-23 §3.3) que veta importar dominio desde ``ui/``.
#
# El delta de provisiones se DERIVA de los objetos Pydantic de dominio con
# ``scripts/derive_provisiones_preset.py`` (``model_dump(mode="json", by_alias=True)``), que además
# CORRE la cadena entera y comprueba que el número tiene sentido de negocio. NO editar a mano:
# regenerar con ese script si cambia un default de dominio.

# 🔴 La calibración NO se hereda del F1. El F1 ancla la PD a ``target_pd=0.20`` (business_input).
# Sobre esta cartera (default ~7 %) eso infla la PD 3x, el método interno supera al estándar, la
# regla del máximo deja de morder y el producto se queda sin titular. ``development_observed``
# estima la PD ancla como el promedio observado en Desarrollo y exige ``target_pd`` NULO (un valor
# sería la trampa). No se ve con un test de ``status == done``: solo corriendo y viendo el número.
#
# ``target_pd`` se deja explícito en ``None``, NO se elimina: la forma canónica del config es la
# que produce ``CalibrationConfig.model_dump`` (emite ``target_pd: None``). Omitir la clave haría
# que el ``config_hash`` dependiera de si la capa de dominio está importada (con coacción reaparece;
# sin ella, no) — un hash inestable entre entornos. Regla para todo preset: los campos con default
# en ``None`` van explícitos, no omitidos.
_PROVISIONES_CALIBRATION_OVERRIDE: dict[str, Any] = {
    "anchor_source": "development_observed",
    "target_pd": None,
}

_PROVISIONES_SECTIONS: dict[str, Any] = {
    "provisioning_cmf": {
        "schema_version": "1.0.0",
        "type": "standard",
        "as_of_date_col": "as_of_date",
        "portfolio_col": "cmf_portfolio",
        "debtor_id_col": "debtor_id",
        "category_col": "cmf_category",
        "days_past_due_col": "days_past_due",
        "product_type_col": "cmf_product_type",
        "matrices": {
            "active_version": "cmf_b1_b3_2025_01",
            "require_verified_rows": True,
            "fail_on_unmapped_contingent_type": True,
            "fail_on_source_mismatch": True,
        },
        "pd_mapping": {
            "pd_source_domain": "model",
            "pd_source_key": "raw_pd_frame",
            "pd_column": "pd_raw",
            "method": "provided_cmf_category",
            "pd_breaks": [],
            "categories": [],
        },
        "exposure": {
            "direct_exposure_col": "exposure_amount",
            "contingent_amount_col": "contingent_amount",
            "contingent_type_col": "contingent_type",
            "is_default_col": "is_default",
            "allow_negative_exposure": False,
            "rounding": "none",
        },
        "guarantees": {
            "enable_aval_substitution": True,
            "financial_guarantee_policy": "fail",
            "recoverable_amount_col": None,
            "require_recoverable_for_default": True,
        },
    },
    "provisioning_internal": {
        "schema_version": "1.0.0",
        "type": "standard",
        "as_of_date_col": "as_of_date",
        "portfolio_col": "cmf_portfolio",
        "exposure_col": "exposure_amount",
        "pd_source": "calibration",
        "pd_column": "pd_calibrated",
        "grouping": "score_band",
        "group_col": None,
        "n_score_bands": 10,
        "lgd": {"method": "provided", "lgd_col": "lgd", "lgd_floor": 0.0, "lgd_cap": 1.0},
        "method": "pd_lgd",
        "loss_rate_col": None,
        "rounding": "currency_2dp",
        "fail_on_falta_dato": True,
    },
    "provisioning": {
        "schema_version": "1.0.0",
        "type": "standard",
        "source_a": "provisioning_cmf",
        "source_b": "provisioning_internal",
        "rule": "max",
        "as_of_date_col": "as_of_date",
        "comparison_level": "total",
        "cmf_portfolio_col": "portfolio",
        "ifrs9_portfolio_col": "portfolio",
        "internal_portfolio_col": "portfolio",
        "portfolio_crosswalk": {},
        "segment_col": None,
        "row_id_col": "row_id",
        "consume_a": True,
        "consume_b": True,
        "consume_cmf": None,
        "consume_ifrs9": None,
        "require_both": True,
        "coverage_policy": "use_available",
        "numeric_reconciliation": "decimal_quantize",
        "tie_tolerance": 1e-09,
        "rounding": "none",
        "fail_on_falta_dato": True,
    },
}


def _provisiones_config() -> dict[str, Any]:
    """Compone el config F3 = F1 base + override de calibración + las tres secciones de provisiones.

    Copia defensiva: nunca muta ``_STANDARD_CONFIG`` ni los literales de delta.
    """
    cfg = deepcopy(_STANDARD_CONFIG)
    cfg["name"] = "preset-provisiones-consumo"
    cfg["calibration"] = {**cfg["calibration"], **_PROVISIONES_CALIBRATION_OVERRIDE}
    cfg["provisioning_cmf"] = deepcopy(_PROVISIONES_SECTIONS["provisioning_cmf"])
    cfg["provisioning_internal"] = deepcopy(_PROVISIONES_SECTIONS["provisioning_internal"])
    cfg["provisioning"] = deepcopy(_PROVISIONES_SECTIONS["provisioning"])
    cfg["provisioning_ifrs9"] = None
    # La activación pedida es propia del fixture F1; F3 conserva su alcance regulatorio previo.
    cfg["validation"] = None
    return cfg


def provisiones_preset() -> dict[str, Any]:
    """Devuelve el descriptor del preset F3 (scorecard F1 + provisiones CMF/interno).

    Returns
    -------
    dict
        ``{id, name, description, config, dataset_id}``: el config F1 completo más las tres
        secciones de provisiones, JSON-able y copia defensiva. Corre end-to-end sobre
        ``provisiones_consumo`` produciendo scorecard + método estándar CMF (Cap. B-1) + método
        interno (PD·LGD·Exposición) + la regla del máximo estándar-vs-interno a nivel de entidad.
    """
    return {
        "id": PROVISIONES_PRESET_ID,
        "name": "Preset F3 — provisiones consumo (CMF + método interno)",
        "description": (
            "Config completo listo para correr sin tocar nada: el scorecard F1 y, encima, las "
            "provisiones que la norma chilena exige — método estándar de la CMF (Cap. B-1) y "
            "método interno (PD·LGD·Exposición), con la provisión reportada = el mayor de los dos "
            "a nivel de entidad — sobre el dataset sintético de consumo con columnas regulatorias."
        ),
        "config": _provisiones_config(),
        "dataset_id": PROVISIONES_DATASET_ID,
    }


# ---------------------------------------------------------------------------------------------
# Preset F4 — provisiones IFRS 9 / ECL (staging de tres etapas + pérdida esperada)
# ---------------------------------------------------------------------------------------------
# El preset F4 es la cadena MÍNIMA que produce la ECL IFRS 9, **standalone de verdad** (sin
# scorecard): ``data → survival → provisioning_ifrs9``. El survival ajusta el discrete-time hazard
# con ``pd_source='none'`` sobre covariables PROPIAS del dataset (mora actual, utilización de
# línea, DTI, antigüedad): el área IFRS 9 de un banco no depende del modelo de originación, y la
# demo cuenta esa historia — modelos propios, datos propios. ``provisioning_ifrs9`` hace el
# staging Stage 1/2/3 + ECL descontada. El ``report`` queda ENCENDIDO: el informe con el capítulo
# «Provisiones IFRS 9 / ECL» es un entregable central (sin capítulo «Resultados»: es condicional
# any-of a los dominios scorecard y esta cadena no corre ninguno).
#
# ``base_pd_source='term_structure'`` deriva la PD de la propia curva lifetime,
# ``pit_mode='ttc_only'`` evita pedir ``rho``/``Z`` y ``scenarios='single'`` evita pesos macro. El
# staging aplica por política conservadora v1 las presunciones rebatibles de mora 30/90 días
# (IFRS 9 5.5.11 / B5.5.37). El descuento es ``annual_eir_year_fraction`` con periodos ANUALES
# (``time_value`` = año), así que la EIR del dataset es anual y el descuento es correcto.
# IFRS 9 está implementado y es EXPERIMENTAL (fuera de la garantía SemVer 1.x).
#
# Las secciones ``survival`` y ``provisioning_ifrs9`` se DERIVAN de los objetos Pydantic de dominio
# con ``scripts/derive_ifrs9_preset.py`` (``model_dump(mode="json", by_alias=True)``), que además
# CORRE la cadena entera y comprueba que la ECL tiene sentido de negocio (coverage ~3 %, staging
# S1>S2>S3). NO editar a mano: regenerar con ese script si cambia un default de dominio.

F4_IFRS9_PRESET_ID = "f4-ifrs9-retail"
IFRS9_DATASET_ID = "ifrs9_retail_latam"

# Secciones del F1 que la cadena standalone IFRS 9 apaga: TODO el pipeline scorecard
# (``binning``/``selection``/``model`` incluidos — con ``pd_source='none'`` survival ya no consume
# ``model.raw_pd_frame``) más calibración/performance/estabilidad. ``report`` NO se apaga: el
# informe trae el capítulo condicional «Provisiones IFRS 9 / ECL»
# (requires_domain='provisioning_ifrs9') y es un entregable central de la demo. Sus
# ``required_sections`` quedan vacías abajo: esta cadena no corre ningún dominio scorecard.
_IFRS9_DROP_SECTIONS: tuple[str, ...] = (
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
)

_IFRS9_SURVIVAL_SECTION: dict[str, Any] = {
    "schema_version": "1.0.0",
    "type": "standard",
    "method": "discrete_hazard",
    "input": {
        "duration_col": "duration",
        "event_col": "event",
        "id_col": None,
        "segment_col": None,
        "pd_source": "none",
        "pd_column": "pd_raw",
        "linear_predictor_column": "linear_predictor",
        "covariate_cols": [
            "days_past_due",
            "utilizacion_linea",
            "deuda_ingreso",
            "antiguedad_meses",
        ],
    },
    "time_grid": {"time_unit": "year", "horizon_periods": 5, "evaluation_times": []},
    "kaplan_meier": {"confidence_level": None, "confidence_transform": None},
    "discrete_hazard": {
        "link": "logit",
        "include_period_dummies": True,
        "pd_role": "none",
        "min_events_per_period": None,
    },
    "cox_aft": {"ph_test_enabled": True, "ph_p_value_threshold": None, "aft_family": None},
    "fail_on_falta_dato": True,
}

_IFRS9_PROVISIONING_SECTION: dict[str, Any] = {
    "schema_version": "1.0.0",
    "type": "standard",
    "as_of_date_col": "as_of_date",
    "row_id_col": None,
    "portfolio_col": "portfolio",
    "pd": {
        "term_structure_source": "survival",
        "base_pd_source": "term_structure",
        "pit_mode": "ttc_only",
        "rho": None,
        "rho_col": None,
        "systemic_factor_col": None,
        "horizon_12m_periods": 1,
        "max_lifetime_periods": None,
    },
    "lgd": {
        "method": "provided",
        "lgd_col": "lgd",
        "recovery_col": None,
        "lgd_floor": 0.0,
        "lgd_cap": 1.0,
        "covariate_cols": [],
        "workout_discount": "eir",
    },
    "ead": {
        "method": "provided",
        "ead_col": "ead",
        "drawn_col": "drawn",
        "limit_col": "credit_limit",
        "ccf_col": None,
        "ccf_value": None,
        "exposure_profile_col": None,
    },
    "staging": {
        "sicr_pd_ratio_threshold": 2.0,
        "sicr_pd_pit_backstop_multiple": 3.0,
        "dpd_sicr_backstop": 30,
        "dpd_default_backstop": 90,
        "days_past_due_col": "days_past_due",
        "is_default_col": "is_default",
        "origination_pd_life_col": None,
        "rating_col": None,
        "origination_rating_col": None,
        "notch_downgrade_threshold": None,
        "stage_override_col": None,
        "low_credit_risk_exemption": False,
        "low_credit_risk_col": None,
    },
    "scenarios": {"source": "single", "weights": {}, "forbid_mean_scenario": True},
    "ecl": {
        "eir_col": "eir",
        "discount_convention": "annual_eir_year_fraction",
        "stage3_direct": False,
        "rounding": "none",
    },
    "fail_on_falta_dato": True,
}


def _ifrs9_config() -> dict[str, Any]:
    """Compone el config F4 = F1 base (mínimo) + survival + provisioning_ifrs9.

    Copia defensiva: nunca muta ``_STANDARD_CONFIG`` ni los literales de sección.
    """
    cfg = deepcopy(_STANDARD_CONFIG)
    cfg["name"] = "preset-ifrs9-retail"
    for section in _IFRS9_DROP_SECTIONS:
        cfg[section] = None
    cfg["survival"] = deepcopy(_IFRS9_SURVIVAL_SECTION)
    cfg["provisioning_ifrs9"] = deepcopy(_IFRS9_PROVISIONING_SECTION)
    cfg["validation"] = None
    # El informe hereda del F1 los cuatro entregables, pero esta cadena standalone no corre ningún
    # dominio scorecard: exigir cualquiera tumbaría el report (missing_policy='error'). La lista
    # queda VACÍA; el capítulo IFRS 9 se activa solo por la presencia de la card
    # (``requires_domain``) y «Resultados» se omite solo (condicional any-of sin dominios).
    cfg["report"]["basename"] = "ifrs9_ecl_report"
    cfg["report"]["sections"]["required_sections"] = []
    return cfg


def ifrs9_preset() -> dict[str, Any]:
    """Devuelve el descriptor del preset F4 (ECL IFRS 9 de tres etapas sobre cartera retail).

    Returns
    -------
    dict
        ``{id, name, description, config, dataset_id}``: la cadena standalone ``data → survival``
        (term-structure lifetime PD sobre covariables propias de la cartera) ``→
        provisioning_ifrs9`` (staging + ECL), JSON-able y copia defensiva. Corre end-to-end sobre
        ``ifrs9_retail_latam`` produciendo la pérdida esperada IFRS 9 de tres etapas (Stage 1/2/3)
        con staging por los backstops de mora 30/90 días, sin scorecard de por medio.
        **Experimental** (SDD-16, fuera de la garantía SemVer 1.x).
    """
    return {
        "id": F4_IFRS9_PRESET_ID,
        "name": "Preset F4 — provisiones IFRS 9 / ECL (retail multi-cartera)",
        "description": (
            "Config listo para correr sin tocar nada, y sin scorecard de por medio: sobre una "
            "cartera retail LatAm multi-producto (Consumo, Tarjetas, Comercial, Hipotecario) "
            "ajusta la curva lifetime PD con un modelo de supervivencia sobre covariables propias "
            "de la cartera (mora, utilización, carga financiera, antigüedad) y calcula la pérdida "
            "esperada IFRS 9 de tres etapas — staging Stage 1/2/3 por los backstops de mora 30/90 "
            "días y ECL 12 meses / lifetime descontada a la tasa efectiva. IFRS 9 es experimental "
            "(SDD-16, fuera de la garantía SemVer 1.x)."
        ),
        "config": _ifrs9_config(),
        "dataset_id": IFRS9_DATASET_ID,
    }


# Registro de presets id -> constructor de descriptor. El orden fija el del listado del front.
_PRESETS: dict[str, Callable[[], dict[str, Any]]] = {
    STANDARD_PRESET_ID: standard_preset,
    PROVISIONES_PRESET_ID: provisiones_preset,
    F4_IFRS9_PRESET_ID: ifrs9_preset,
}


def list_presets() -> list[dict[str, Any]]:
    """Descriptores SIN ``config`` de todos los presets, para el selector del front (SDD-28)."""
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
            "dataset_id": p["dataset_id"],
        }
        for p in (build() for build in _PRESETS.values())
    ]


def get_preset(preset_id: str) -> dict[str, Any]:
    """Descriptor completo (con ``config``) de un preset por id; ``KeyError`` si no existe."""
    if preset_id not in _PRESETS:
        raise KeyError(preset_id)
    return _PRESETS[preset_id]()
