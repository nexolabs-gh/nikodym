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

from copy import deepcopy
from typing import Any

__all__ = ["standard_preset"]

STANDARD_PRESET_ID = "f1-estandar-consumo"
STANDARD_DATASET_ID = "consumo_comportamiento"

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
    "validation": None,
    # Report HTML determinístico activado. Derivado con ``ReportConfig(sections=SectionPolicyConfig(
    # required_sections=(...)))`` + ``model_dump(mode="json", by_alias=True)`` (NO editar a mano).
    # Las ``required_sections`` son EXACTAMENTE las cards que el preset produce (sin ``eda`` ni
    # ``data``: el pipeline no corre EDA), para que ``ReportStep.requires`` no exija una card
    # inalcanzable y el motor (CT-1) no rechace el config. ``report`` es INFRA (``INFRA_SECTIONS``)
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
