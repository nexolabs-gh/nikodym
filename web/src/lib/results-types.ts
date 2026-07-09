/**
 * DTOs tipados de `GET /api/results/{run_id}` (B27 backend, expandido).
 *
 * Reflejan el SHAPE REAL que devuelve el backend para el preset estándar F1
 * (verificado contra un payload real, `results_real.json`). El front SOLO
 * transporta/formatea estos artefactos ya calculados (SDD-23 §1/§3.3): CERO
 * lógica de dominio; un número en pantalla viene siempre del artefacto.
 *
 * Convenciones de tipado:
 *  - Campos que el backend puede omitir en corridas parciales/`failed` → opcionales.
 *  - Campos presentes pero nulos en el payload real (p.ej. `min_score`, `sign_ok`,
 *    `isotonic_knots`, `slope`) → `X | null`.
 *  - NO se inventan campos: lo no explotado por la UI se tipa laxo (`unknown[]`,
 *    `Record<string, unknown>`) en lugar de adivinar su forma interna.
 */

/** Estado terminal de una corrida (mismo dominio que `RunStatus`). */
export type ResultsStatus = "done" | "failed"

// --- performance ------------------------------------------------------------

/** Métricas de discriminación máximas de una partición. */
export interface PartitionMetrics {
  auc: number
  gini: number
  ks: number
}

/**
 * Fila de la tabla de deciles/gains (`performance.deciles`), espejo del DTO
 * `DecilePerformanceRecord` del backend. Hay una fila por (partición × decil): los
 * deciles se ordenan por riesgo DESCENDENTE (decil 1 = 10% más riesgoso), así que
 * `cum_bad_capture_rate` es la ganancia acumulada (% de malos capturados hasta ese
 * decil) y crece hasta 1.0 en el último. Todos los floats son requeridos y finitos
 * (el DTO fila-nivel los valida), por eso NO son nullable. La UI solo los grafica.
 */
export interface DecileRow {
  partition: string
  decile: number
  n_total: number
  n_bad: number
  n_good: number
  bad_rate: number
  good_rate: number
  mean_pd: number
  min_pd: number
  max_pd: number
  mean_score: number
  min_score: number
  max_score: number
  cum_total: number
  cum_bad: number
  cum_good: number
  /** Ganancia acumulada: fracción de malos capturados hasta este decil (0–1). */
  cum_bad_capture_rate: number
  cum_good_capture_rate: number
  /** Lift del decil: bad_rate del decil / bad_rate global (1 = azar). */
  lift: number
  ks_at_decile: number
}

/** Fila de discriminación por partición (`performance.discriminant`). */
export interface DiscriminantRow {
  partition: string
  n_total: number
  n_bad: number
  n_good: number
  auc: number
  gini: number
  ks: number
  ks_cutoff_risk_score: number | null
  ks_cutoff_score: number | null
  tpr_at_ks: number | null
  fpr_at_ks: number | null
  source: string
  status: string
}

/** Sección de performance/discriminación de la corrida. */
export interface PerformanceResult {
  evaluation_source: string
  score_direction: string
  /** Orden canónico de particiones (p.ej. `["desarrollo","holdout","oot"]`). */
  partitions: string[]
  max_metrics_by_partition: Record<string, PartitionMetrics>
  discriminant: DiscriminantRow[]
  n_deciles: number
  thresholds?: Record<string, unknown>
  bands_by_partition?: Record<string, unknown>
  /** Tabla de deciles/gains (30 filas: 10 deciles × 3 particiones en el preset). */
  deciles?: DecileRow[]
  metric_sections?: Record<string, unknown>
  dependency_versions?: Record<string, unknown>
}

// --- binning ----------------------------------------------------------------

/**
 * Fila de una tabla de binning (`binning.tables_by_variable[var]`). La última fila
 * es el total: su `Bin` es `""` y su `WoE` viene como string vacío (por eso los
 * tipos unión). La pestaña Resultados SÍ renderiza estas tablas (visor "Análisis por
 * variable (WoE)": curva WoE por bin + tabla de detalle); ver `variableBinning`.
 */
export interface BinRow {
  Bin: string | (string | number)[]
  Count: number
  "Count (%)": number
  "Non-event": number
  Event: number
  "Event rate": number
  WoE: number | string
  IV: number
  JS: number
}

/** Sección de binning (WoE/IV por variable). */
export interface BinningResult {
  n_variables_requested: number
  n_variables_binned: number
  n_variables_skipped: number
  /** IV total por variable (feature → IV). */
  iv_by_variable: Record<string, number>
  monotonicity_by_variable?: Record<string, unknown>
  special_handling?: string
  missing_handling?: string
  optbinning_version?: string
  tables_by_variable?: Record<string, BinRow[]>
}

// --- selection --------------------------------------------------------------

/** Sección de selección de variables (no renderizada en v1; tipada laxa). */
export interface SelectionResult {
  n_candidates: number
  n_selected: number
  n_excluded: number
  selected_features: string[]
  max_abs_correlation_after_selection?: number
  max_vif_after_selection?: number
  thresholds?: Record<string, unknown>
  excluded_by_reason?: Record<string, unknown>
  high_iv_flags?: unknown[]
  stability_flags?: unknown[]
  decisions?: unknown[]
  dependency_versions?: Record<string, unknown>
}

// --- model ------------------------------------------------------------------

/** Estadísticos de ajuste de la regresión (`model.fit_statistics`). */
export interface FitStatistics {
  n_obs_dev: number
  n_events_dev: number
  n_nonevents_dev: number
  log_likelihood: number
  null_log_likelihood: number
  pseudo_r2_mcfadden: number
  aic: number
  bic: number
  llr: number
  llr_p_value: number
  converged: boolean
  optimizer?: string
  n_iterations?: number
}

/**
 * Coeficiente estimado (`model.coefficients`). El intercepto trae `expected_sign:"none"`
 * y `sign_ok/iv/iv_contribution` nulos; las variables sí traen esos campos.
 */
export interface Coefficient {
  feature: string
  woe_column: string
  beta: number
  standard_error: number
  wald_z: number
  p_value: number
  conf_low: number
  conf_high: number
  expected_sign: string
  sign_ok: boolean | null
  iv: number | null
  iv_contribution: number | null
}

/** Sección del modelo (regresión logística sobre WoE). */
export interface ModelResult {
  engine: string
  n_candidates: number
  n_final_features: number
  final_features: string[]
  fit_statistics: FitStatistics
  coefficients: Coefficient[]
  thresholds?: Record<string, unknown>
  sign_flags?: unknown[]
  iv_contribution_flags?: unknown[]
  metric_sections?: Record<string, unknown>
  dependency_versions?: Record<string, unknown>
}

// --- scorecard --------------------------------------------------------------

/** Sección de la scorecard (escala de puntajes). `min/max_score` pueden venir nulos. */
export interface ScorecardResult {
  pdo: number
  target_score: number
  target_odds: number
  factor: number
  offset: number
  score_direction: string
  rounding_method: string
  n_variables: number
  score_column: string
  points_columns: string[]
  min_score: number | null
  max_score: number | null
  overrides_count: number
  points?: unknown[]
  /** Score fila-nivel crudo (~6000 floats) para el histograma; `null`/ausente si falta. */
  score_values?: number[]
  metric_sections?: Record<string, unknown>
  dependency_versions?: Record<string, unknown>
}

// --- calibration ------------------------------------------------------------

/**
 * Un bin del reliability diagram (curva de confiabilidad): compara la PD predicha
 * media del bin con la tasa de default observada, ambas en [0,1]. `ci_low`/`ci_high`
 * son la banda de Wilson 95% de la tasa OBSERVADA (eje Y); `pd_lo`/`pd_hi` acotan la PD
 * predicha dentro del bin (eje X). Todos los floats son requeridos y finitos (el DTO
 * fila-nivel los valida). La UI solo los grafica; CERO recálculo.
 */
export interface ReliabilityBin {
  bin: number
  n: number
  mean_predicted_pd: number
  observed_default_rate: number
  ci_low: number
  ci_high: number
  pd_lo: number
  pd_hi: number
}

/**
 * Curva de confiabilidad de UNA partición, con sus escalares de calibración: `brier`
 * (Brier score, menor = mejor) y `ece` (Expected Calibration Error). Los bins vienen en
 * orden de riesgo (decil ascendente).
 */
export interface ReliabilityPartition {
  partition: string
  n: number
  brier: number
  ece: number
  bins: ReliabilityBin[]
}

/**
 * Sección `calibration.reliability` (reliability diagram por partición, B35a backend).
 * `by_partition` es una LISTA en orden desarrollo → holdout → oot. Puede venir ausente/
 * `null` (backend no la emite) o con `by_partition` vacío → el visor NO se renderiza
 * (guard por presencia). Ver `reliabilityCurve` en `results-format`.
 */
export interface ReliabilityCurve {
  strategy: string
  n_bins: number
  by_partition: ReliabilityPartition[]
}

/**
 * Sección de calibración de PD. Para `method:"intercept_offset"`, `slope`/`intercept`/
 * `isotonic_knots` vienen nulos (son de la variante isotónica).
 */
export interface CalibrationResult {
  method: string
  target_pd: number
  anchor_kind: string
  anchor_source: string
  fit_partition: string
  n_fit: number
  raw_mean_pd_dev: number
  calibrated_mean_pd_dev: number
  observed_default_rate_dev: number
  offset: number
  slope: number | null
  intercept: number | null
  ranking_preserved: boolean
  ties_created: number
  pd_raw_column: string
  pd_calibrated_column: string
  isotonic_knots: unknown[] | null
  /** Reliability diagram por partición (B35a). Ausente/`null` si el backend no lo emite. */
  reliability?: ReliabilityCurve | null
  metric_sections?: Record<string, unknown>
  dependency_versions?: Record<string, unknown>
}

// --- stability --------------------------------------------------------------

/**
 * Banda de estabilidad (enum del backend `StabilityBand`). El dataset actual solo
 * produce `stable`, pero el contrato define las cuatro: la UI DEBE manejarlas todas
 * (no hardcodear "todo verde"). `not_evaluable` = métrica sin valor comparable.
 */
export type StabilityBand = "stable" | "review" | "redevelop" | "not_evaluable"

/** Acción auditada mapeada 1:1 desde la banda (`StabilityAction` del backend). */
export type StabilityAction = "none" | "vigilar" | "redesarrollar"

/** Métrica de estabilidad (`StabilityMetricName`). Las tres primeras son PSI/CSI. */
export type StabilityMetricName = "score_psi" | "pd_psi" | "csi" | "temporal_score"

/**
 * Fila RESUMEN de `stability.stability_metrics` (una por métrica/comparación). Para
 * `metric:"csi"` el `feature` es la variable y `value` su CSI; para las PSI el `feature`
 * es `score`/`pd_calibrated`. `value` puede venir nulo (métrica no evaluable → `NaN`→`null`).
 */
export interface StabilityMetricRow {
  metric: StabilityMetricName
  comparison: string
  feature: string
  value: number | null
  stable_threshold: number
  review_threshold: number
  band: StabilityBand
  action: StabilityAction
}

/**
 * Fila bin-level de `stability.psi_table` (detalle fino de PSI del score/PD y CSI). No se
 * grafica en este batch (opcional en el pedido); se tipa para fidelidad del contrato.
 */
export interface PsiTableRow {
  metric: StabilityMetricName
  comparison: string
  feature: string
  bin_label: string
  expected_count: number
  actual_count: number
  expected_pct: number
  actual_pct: number
  component_value: number
  total_value: number
  band: StabilityBand
}

/**
 * Bloque `stability` de `GET /api/results` (`StabilityCardSection` + frames ricos
 * fusionados por el serializer). Es `null` en la respuesta si estabilidad no corrió.
 * `stability_metrics`/`psi_table` vienen `null` si el frame concreto está ausente.
 */
export interface StabilityResponse {
  score_direction: string
  csi_source: string
  /** Comparaciones evaluadas, p.ej. `["dev_vs_holdout","dev_vs_oot"]`. */
  comparisons: string[]
  psi_bins: number
  stable_threshold: number
  review_threshold: number
  /** PSI máximo por comparación (puede venir nulo por comparación no evaluable). */
  max_psi_by_comparison: Record<string, number | null>
  /** Banda peor-caso por comparación. */
  bands_by_comparison: Record<string, string>
  worst_csi_feature: string | null
  worst_csi_value: number | null
  dependency_versions?: Record<string, string>
  metric_sections?: Record<string, unknown>
  stability_metrics?: StabilityMetricRow[] | null
  psi_table?: PsiTableRow[] | null
}

// --- top-level --------------------------------------------------------------

/**
 * `GET /api/results/{run_id}` — ModelCard + DTOs por dominio. En una corrida
 * `failed` las secciones de dominio pueden faltar (payload parcial) y `error`
 * trae el mensaje; por eso las secciones son opcionales. `model_card` viene null
 * en el preset estándar (forma aún no explotada por la UI → laxa).
 */
export interface ResultsResponse {
  status: ResultsStatus
  run_id: string
  error: string | null
  model_card: Record<string, unknown> | null
  binning?: BinningResult
  selection?: SelectionResult
  model?: ModelResult
  scorecard?: ScorecardResult
  calibration?: CalibrationResult
  performance?: PerformanceResult
  /** Estabilidad post-modelo (PSI/CSI). `null` si no corrió; ausente en payloads viejos. */
  stability?: StabilityResponse | null
}
