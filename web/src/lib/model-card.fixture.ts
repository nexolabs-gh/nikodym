/**
 * Ficha del modelo con VALORES REALES: recorte tipado de `GET /api/results/<run_id>.model_card`
 * de una corrida del preset F1 con `governance` encendida y `purpose` declarado por el usuario
 * (corrida `4b04cbde…` sobre `consumo_comportamiento`, 6.000 filas; 24 métricas, 41 decisiones).
 *
 * Es sólo para tests —los tres fixtures de la demo traen `model_card: null` y no se recapturan sin
 * un OK propio (D-GOB-9)—, y vive fuera de los archivos `.test.ts` para que dos suites lo compartan
 * sin importarse entre sí. Que este objeto compile como `ModelCard` YA es una verificación del
 * contrato (D-GOB-16): si el tipo dejara de reflejar lo que el serializador emite, `tsc` fallaría
 * aquí. Las decisiones se recortan a ocho, una por cada combinación real de tipos de `umbral` y
 * `valor` (texto, número, booleano, lista, objeto).
 */

import type { ModelCard } from "@/lib/results-types"

export const MODEL_CARD_F1: ModelCard = {
  run_id: "4b04cbdeed9a45d5b701aabbb8760eff",
  config_hash: "ec10eb43314cad2e369584c7dabe4bbf2456391e255a2b69218d405bba2a448e",
  data_hash: "74c5d9ddeca8ff71853623d20ace015d0788564549339d61bfb66f24dfadfcc8",
  git_sha: "3cad020682cedd09c6437ec71f8bf71e790858e5",
  git_dirty: false,
  root_seed: 20240706,
  schema_version: "1.0.0",
  created_at: "2026-09-03T01:05:40.519654Z",
  purpose: "Estimar la PD de la cartera de consumo para el calculo de provisiones.",
  assumptions: ["La cartera sintetica es representativa del segmento."],
  limitations: ["No se modela la amortizacion del credito."],
  data_description: {
    source: "consumo_comportamiento.parquet",
    n_rows: 6000,
    n_features: 8,
    target_col: "target",
    bad_rate: 0.2345,
    class_counts: { bueno: 4593, malo: 1407, indeterminado: 0, excluido: 0 },
    partition_sizes: { desarrollo: 3961, holdout: 1031, oot: 1008, fuera_de_modelo: 0 },
    partition_bad_rates: {
      desarrollo: 0.23327442565008835,
      holdout: 0.23666343355965083,
      oot: 0.2371031746031746,
      fuera_de_modelo: 0.0,
    },
    performance_window_months: null,
    exclusions_by_reason: {},
    data_hash: "74c5d9ddeca8ff71853623d20ace015d0788564549339d61bfb66f24dfadfcc8",
  },
  metrics: {
    "data.n_rows": 6000.0,
    "data.n_features": 8.0,
    "data.bad_rate": 0.2345,
    "binning.n_variables_binned": 6.0,
    "binning.n_variables_skipped": 0.0,
    "selection.n_candidates": 6.0,
    "selection.n_selected": 5.0,
    "selection.max_abs_correlation_after_selection": 0.030325981242350992,
    "model.n_final_features": 5.0,
    "scorecard.n_variables": 5.0,
    "calibration.target_pd": 0.23327442565008835,
    "calibration.calibrated_mean_pd_dev": 0.23327442565008835,
    "calibration.observed_default_rate_dev": 0.23327442565008835,
    "performance.auc_desarrollo": 0.7123458941453674,
    "performance.gini_desarrollo": 0.42469178829073484,
    "performance.ks_desarrollo": 0.32014426688447106,
    "performance.auc_holdout": 0.6946460932780636,
    "performance.gini_holdout": 0.3892921865561272,
    "performance.ks_holdout": 0.3118920157477034,
    "performance.auc_oot": 0.6560957827097084,
    "performance.gini_oot": 0.31219156541941673,
    "performance.ks_oot": 0.25190569723218226,
    "stability.worst_psi": 0.013181930579331572,
    "stability.worst_csi_value": 0.010208836708625104,
  },
  metric_sections: {
    performance: {
      discrimination: {
        effective_deciles_by_partition: { desarrollo: 10, holdout: 10, oot: 10 },
        not_evaluable_reasons_by_partition: {},
        threshold_flags_by_partition: {},
      },
    },
    stability: {
      stability: {
        temporal_axis: "period",
        include_pd_stability: true,
        csi_features: [
          "antiguedad_meses__points",
          "deuda_ingreso__points",
          "ingreso_mensual__points",
          "mora_max_12m__points",
          "utilizacion_linea__points",
        ],
        n_periods: 6,
      },
    },
  },
  decisions: [
    {
      step: null,
      regla: "partition_strategy",
      umbral: "cohort",
      valor: "cohort",
      accion: "aplicar_estrategia",
      ts: "2026-09-03T01:05:41.512580Z",
    },
    {
      step: null,
      regla: "partition_summary",
      umbral: "sizes_bad_rates",
      valor: {
        bad_rates: {
          desarrollo: 0.23327442565008835,
          fuera_de_modelo: 0.0,
          holdout: 0.23666343355965083,
          oot: 0.2371031746031746,
        },
        sizes: { desarrollo: 3961, fuera_de_modelo: 0, holdout: 1031, oot: 1008 },
      },
      accion: "reportar_particiones",
      ts: "2026-09-03T01:05:41.512884Z",
    },
    {
      step: null,
      regla: "bins_colapsados",
      umbral: 6,
      valor: { n_bins: 5, variable: "utilizacion_linea" },
      accion: "conservar_variable",
      ts: "2026-09-03T01:05:59.493695Z",
    },
    {
      step: null,
      regla: "iv_bajo",
      umbral: 0.02,
      valor: { iv: 0.002922409359928141, variable: "segmento" },
      accion: "diagnosticar_sin_eliminar",
      ts: "2026-09-03T01:05:59.493695Z",
    },
    {
      step: null,
      regla: "statsmodels_convergence",
      umbral: { fit_maxiter: 100, tol: 1e-8 },
      valor: { converged: true, n_iterations: 6, optimizer: "newton" },
      accion: "aceptar_ajuste",
      ts: "2026-09-03T01:06:00.106128Z",
    },
    {
      step: null,
      regla: "woe_duplicado",
      umbral: "primera_aparicion_feature_woe",
      valor: [
        {
          bin_label: "Missing",
          feature: "antiguedad_meses",
          points_descartados: 104,
          points_usados: 104,
          woe: 0.0,
        },
        {
          bin_label: "Missing",
          feature: "deuda_ingreso",
          points_descartados: 104,
          points_usados: 104,
          woe: 0.0,
        },
      ],
      accion: "usar_punto_determinista",
      ts: "2026-09-03T01:06:00.119123Z",
    },
    {
      step: null,
      regla: "report_sections",
      umbral: ["binning", "selection", "model", "scorecard", "calibration", "performance", "stability"],
      valor: { missing_sections: [], sections: ["toc", "introduction", "results", "limitations"] },
      accion: "renderizar_reporte",
      ts: "2026-09-03T01:06:03.843566Z",
    },
    {
      step: null,
      regla: "report_ai_disabled",
      umbral: false,
      valor: { provider: "none" },
      accion: "usar_narrativa_basica",
      ts: "2026-09-03T01:06:03.843566Z",
    },
  ],
  determinism_caveats: [],
  review_date: "2026-09-03T01:06:03.859794Z",
  next_review_date: "2027-09-03T01:06:03.859794Z",
  environment: {
    python_version: "3.12.10",
    platform: "Windows-11-10.0.26200-SP0",
    library_versions: {
      nikodym: "1.11.0",
      numpy: "2.4.6",
      pandas: "2.3.3",
      pandera: "0.32.0",
      pyarrow: "24.0.0",
      pydantic: "2.13.4",
      joblib: "1.5.3",
      PyYAML: "6.0.3",
    },
    uv_lock_hash: "32c611ad4b1e061c14e1262548bf30346610d7529a6e4fb7bc52c68ec3540d24",
    captured_at: "2026-09-03T01:06:03.870062Z",
  },
}
