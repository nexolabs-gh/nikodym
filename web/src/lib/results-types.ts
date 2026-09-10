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
  excluded_by_target_rule?: string[]
  tables_by_variable?: Record<string, BinRow[]>
}

// --- selection --------------------------------------------------------------

/**
 * Banda diagnóstica del IV (`IvBand` del backend). El slug es el dato; su palabra en español
 * la resuelve `ivBandLabel`, espejo de `nikodym.binning.results.IV_BAND_LABELS`.
 */
export type IvBand = "none" | "weak" | "medium" | "strong" | "suspicious"

/**
 * Motivo de la decisión sobre una variable candidata (`SelectionDecisionReason` del backend).
 * `included` es el único que no excluye. Su palabra en español la resuelve `selectionReasonLabel`,
 * espejo de `nikodym.selection.results.REASON_LABELS`.
 */
export type SelectionDecisionReason =
  | "included"
  | "business_exclude"
  | "business_include"
  | "low_iv"
  | "high_iv"
  | "low_auc"
  | "low_ks"
  | "low_gini"
  | "high_correlation"
  | "high_vif"
  | "cluster_representative_lost"
  | "constant_or_nonfinite"
  | "missing_binning_artifact"
  | "forced_conflict"
  | "high_stability"

/**
 * Una fila de `selection.decisions` (`VariableSelectionDecision` del backend): la decisión
 * auditable sobre una variable candidata. `detail` es texto libre del motor (p. ej.
 * `iv=0.0029 < min_iv=0.02`) y se muestra tal cual: es el dato de auditoría de la fila.
 */
export interface SelectionDecision {
  feature: string
  woe_column: string
  included: boolean
  reason: SelectionDecisionReason
  iv: number
  iv_band: IvBand
  auc: number | null
  gini: number | null
  ks: number | null
  max_abs_corr: number | null
  max_corr_with: string | null
  vif: number | null
  max_csi: number | null
  forced: "include" | "exclude" | null
  detail: string | null
}

/**
 * Valor de un umbral activo de `selection.thresholds` (`ThresholdValue` del backend): un número,
 * el valor crudo de un enum (el mismo que muestra el formulario) o `null` si está apagado.
 */
export type SelectionThresholdValue = number | string | null

/** Sección de selección de variables (`SelectionCardSection` + `decisions`). */
export interface SelectionResult {
  n_candidates: number
  n_selected: number
  n_excluded: number
  selected_features: string[]
  max_abs_correlation_after_selection?: number | null
  max_vif_after_selection?: number | null
  thresholds?: Record<string, SelectionThresholdValue>
  excluded_by_reason?: Record<string, number>
  high_iv_flags?: string[]
  stability_flags?: string[]
  decisions?: SelectionDecision[] | null
  dependency_versions?: Record<string, string>
}

// --- validation -------------------------------------------------------------

/**
 * Estado técnico agregado de la validación formal (`OverallStatus` del backend). El slug es el
 * dato; su palabra la resuelve `validationStatusLabel`, espejo de
 * `nikodym.validation.results.VALIDATION_STATUS_LABELS`.
 */
export type ValidationOverallStatus = "pass" | "warn" | "fail"

/** Familia de pruebas que la validación ejecuta (`ValidationFamily` del backend). */
export type ValidationFamily =
  | "discrimination"
  | "calibration"
  | "stability"
  | "backtesting"

/** Veredicto de una fila de calibración o de backtesting (`CalibrationDecision`/`BacktestDecision`). */
export type ValidationDecision = "pass" | "fail" | "not_evaluable"

/** Semáforo de un grado de rating (`TrafficLight` del backend). */
export type TrafficLight = "green" | "amber" | "red"

/** De dónde salió el AUC/Gini/KS de una partición (`DiscriminationSource` del backend). */
export type DiscriminationSource = "performance_artifact" | "recomputed"

/** Estado de evaluabilidad de una partición (`DiscriminationStatus` del backend). */
export type DiscriminationStatus = "ok" | "not_evaluable"

/** Prueba de calibración por partición (`CalibrationTest` del backend). */
export type CalibrationTest = "hosmer_lemeshow" | "brier"

/** Parámetro IFRS 9 contrastado contra lo realizado (`BacktestParameter` del backend). */
export type BacktestParameter = "pd" | "lgd" | "ead"

/** Prueba usada en una fila de backtesting (`BacktestTest` del backend). */
export type BacktestTest = "t_test" | "binomial" | "jeffreys"

/** Fila de `validation.discrimination` (`DiscriminationRecord` del backend). */
export interface ValidationDiscriminationRow {
  partition: string
  n_total: number
  n_bad: number
  auc: number | null
  gini: number | null
  ks: number | null
  source: DiscriminationSource
  status: DiscriminationStatus
}

/**
 * Fila de `validation.calibration`. La tabla canónica del motor mezcla dos formas y la columna
 * `grade` es la que las distingue: las filas de Hosmer-Lemeshow y del puntaje de Brier traen
 * `grade: "ALL"` y `traffic_light: null`; las del contraste por grado traen el grado y su semáforo.
 */
export interface ValidationCalibrationRow {
  partition: string
  test: CalibrationTest | BacktestTest
  grade: string
  n: number
  observed_defaults: number
  expected_pd: number | null
  observed_dr: number | null
  statistic: number | null
  degrees_of_freedom: number | null
  p_value: number | null
  alpha: number | null
  decision: ValidationDecision
  traffic_light: TrafficLight | null
}

/** Fila de `validation.stability`: el PSI que la etapa de estabilidad ya calculó, con su banda. */
export interface ValidationStabilityRow {
  metric: string
  comparison: string
  feature: string | null
  value: number | null
  stable_threshold: number | null
  review_threshold: number | null
  band: StabilityBand
  action: string | null
  source: string
  status: string
  decision: ValidationDecision
}

/** Fila de `validation.backtesting`: un contraste realizado-vs-estimado por parámetro y segmento. */
export interface ValidationBacktestRow {
  parameter: BacktestParameter
  segment: string
  n: number
  predicted_mean: number | null
  realised_mean: number | null
  test: BacktestTest
  statistic: number | null
  p_value: number | null
  alpha: number | null
  one_sided: boolean
  decision: ValidationDecision
}

/**
 * Un grado de rating sin potencia estadística, tal como lo publica
 * `card.metric_sections.validation.not_evaluable_grades`.
 *
 * 🔴 Estos grados NO están en la tabla de calibración ni cuentan en `n_tests`/`n_failed`: es un
 * invariante del motor (un grado sin potencia no produce semáforo). Por eso el panel tiene que
 * publicar la cobertura además de la tabla: sin ella, «Pasa · 0 de 1 pruebas fallidas» podría
 * esconder una cartera entera sin evaluar.
 */
export interface ValidationNotEvaluableGrade {
  grade: string
  n: number
  observed_defaults: number
  expected_pd: number | null
  observed_dr: number | null
  min_rows: number
  status: string
}

/** Sección de validación formal (`ValidationCardSection` + sus cuatro tablas tidy). */
export interface ValidationResult {
  model_ref: string
  families_run: ValidationFamily[]
  overall_status: ValidationOverallStatus
  n_tests: number
  n_failed: number
  falta_dato?: string[]
  dependency_versions?: Record<string, string>
  /**
   * Puerta CT-2 del motor. Repite el resumen de la card —`families_run`, `overall_status`,
   * `n_tests`, `n_failed`— para los consumidores que sólo reciben esta sección (informe y ficha
   * del modelo), y añade lo que NO está en las tablas: el recuento del semáforo por grado y los
   * grados que se quedaron sin evaluar. El panel lee de aquí sólo lo segundo; el estado lo toma
   * de la card, que es donde vive.
   */
  metric_sections?: {
    validation?: {
      families_run?: ValidationFamily[]
      overall_status?: ValidationOverallStatus
      n_tests?: number
      n_failed?: number
      traffic_light?: Record<string, number>
      not_evaluable_grades?: ValidationNotEvaluableGrade[]
    }
  }
  discrimination?: ValidationDiscriminationRow[] | null
  calibration?: ValidationCalibrationRow[] | null
  stability?: ValidationStabilityRow[] | null
  backtesting?: ValidationBacktestRow[] | null
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

/** Magnitud que determina el peor resumen PSI por comparación. */
export type PsiSummaryMetric = "score_psi" | "pd_psi"

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
  /** Identidad del PSI que determina el máximo; ausente en cards legacy 1.x. */
  psi_metric_by_comparison?: Record<string, PsiSummaryMetric | null> | null
  /** Banda peor-caso por comparación. */
  bands_by_comparison: Record<string, StabilityBand>
  worst_csi_feature: string | null
  worst_csi_value: number | null
  dependency_versions?: Record<string, string>
  metric_sections?: Record<string, unknown>
  stability_metrics?: StabilityMetricRow[] | null
  psi_table?: PsiTableRow[] | null
}

// --- provisiones (SDD-28) ---------------------------------------------------
//
// Las tres cards de provisiones (`provisioning`, `provisioning_cmf`,
// `provisioning_internal`) más sus frames AGREGADOS graficables. Reflejan el SHAPE REAL
// del preset F3 `f3-provisiones-consumo` (verificado contra un payload real generado
// corriendo la cadena entera y serializado por `ui/serializers.serialize_study` — el mismo
// que sirve `GET /api/results`). Los MONTOS vienen como `number` (CLP): el motor trabaja en
// `Decimal` y el serializer lo coacciona a float en la frontera (D9). El serializer emite
// estas tres claves SIEMPRE: `null` cuando el dominio no corrió (p. ej. una corrida F1 sin
// provisiones), la card + sus frames cuando sí. La UI usa guard-por-presencia (CERO cálculo).

/**
 * Fila de la comparación estándar-vs-interno por celda (`provisioning.comparison`). Con
 * `comparison_level:"total"` (el preset F3) hay UNA fila (`cell_id:"TOTAL"`, `level:"total"`).
 * `provision_a`/`provision_b` son los operandos comparados (source_a/source_b);
 * `reported_provision` es el mayor (lo que la norma obliga a constituir); `binding` dice cuál
 * mandó. Montos en CLP. Todos los floats vienen del artefacto; la UI solo los grafica.
 */
export interface ProvisioningComparisonRow {
  cell_id: string
  level: string
  source_a: string
  source_b: string
  provision_a: number
  provision_b: number
  reported_provision: number
  binding: string
  coverage: string
  warning_codes: string[]
}

/**
 * Card de orquestación — la regla del máximo del B-1 (`provisioning`). `total_provision_a` es
 * el método estándar (source_a, normalmente `"cmf"`), `total_provision_b` el método interno
 * (source_b, `"internal"`), y `total_reported_provision` el MAYOR de los dos: la provisión que
 * la norma chilena obliga a constituir (Cap. B-1, hoja 10-11). El titular del producto es el
 * SOBRECOSTO = reportada − interna (SDD-28 §3.5), en la moneda de la corrida. `binding` dice qué método mandó.
 * `falta_dato`/`metric_sections` se tipan laxos (no explotados en detalle por la UI).
 */
export interface ProvisioningResult {
  as_of_date: string
  comparison_level: string
  rule: string
  source_a: string
  source_b: string
  /** Motores presentes en la comparación (p. ej. `["cmf","internal"]`). */
  engines_present: string[]
  /** Qué método mandó a nivel de entidad (`"cmf"`/`"internal"`/…). */
  binding: string
  n_cells: number
  n_binding_a: number
  n_binding_b: number
  n_binding_tie: number
  /** Provisión del método estándar (source_a), en la moneda de la corrida. */
  total_provision_a: number
  /** Provisión del método interno (source_b), en la moneda de la corrida. */
  total_provision_b: number
  /** Provisión reportada = mayor(estándar, interno), en la moneda de la corrida. */
  total_reported_provision: number
  cmf_matrix_version: string
  ifrs9_term_structure_source: string | null
  internal_method: string
  /** Citas normativas de la regla aplicada (para el pie/auditoría). */
  regulatory_sources: string[]
  /** Operaciones con dato faltante (vacío en la corrida de referencia; laxo). */
  falta_dato?: unknown[]
  metric_sections?: Record<string, unknown>
  /** Comparación por celda (1 fila con `comparison_level:"total"`). */
  comparison?: ProvisioningComparisonRow[]
}

/** Agregado por cartera del método estándar CMF (`provisioning_cmf.portfolios`). */
export interface CmfPortfolioRow {
  portfolio: string
  n_rows: number
  total_exposure_amount: number
  total_provision_amount: number
  /** Pérdida esperada ponderada, en PORCENTAJE (0–100, NO proporción). */
  weighted_pe_percent: number
  warnings: string[]
}

/**
 * Fila del desglose del método estándar por categoría CMF (`provisioning_cmf.summary`, ~20
 * filas). `cmf_category` es el código derivado por el motor `(bucket_dpd|hipotecario_sistema|
 * mora_sistema)`, p. ej. `"0_7|no|no"`. Montos en CLP; `weighted_pe_percent` en % (0–100).
 */
export interface CmfSummaryRow {
  portfolio: string
  method: string
  cmf_category: string
  n_rows: number
  total_exposure_amount: number
  total_provision_amount: number
  weighted_pe_percent: number
  matrix_version: string
  warning_codes: string[]
}

/**
 * Card del método estándar CMF (Cap. B-1/B-3), `provisioning_cmf`. `total_provision_amount` es
 * la provisión estándar total (CLP); `total_exposure_amount` las colocaciones (CLP). El
 * desglose por categoría vive en `summary`.
 */
export interface CmfProvisioningResult {
  matrix_version: string
  as_of_date: string
  n_rows: number
  total_exposure_amount: number
  total_provision_amount: number
  portfolios: CmfPortfolioRow[]
  regulatory_sources: string[]
  metric_sections?: Record<string, unknown>
  /** Desglose por categoría CMF (~20 filas); ausente/`null` si el frame no se emitió. */
  summary?: CmfSummaryRow[]
}

/**
 * Fila por grupo homogéneo del método interno (`provisioning_internal.groups`). Puede representar
 * bandas efectivas de score, segmentos o grupos provistos. `pd_group`/`lgd_group`/
 * `expected_loss_rate` son PROPORCIONES [0,1]; `lgd_group` es nulo con tasa directa;
 * `provision_amount` y `total_exposure` son montos.
 */
export interface InternalGroupRow {
  group_id: string
  portfolio: string
  n_operations: number
  total_exposure: number
  pd_group: number
  lgd_group: number | null
  expected_loss_rate: number
  provision_amount: number
  warning_codes: string[]
}

/**
 * Card del método interno (`provisioning_internal`): pérdida descompuesta en PD/LGD o tasa directa,
 * según `method`. `total_internal_provision` es la provisión total; `total_exposure`, la exposición.
 * El desglose efectivo por grupo vive en `groups`.
 */
export interface InternalProvisioningResult {
  as_of_date: string
  method: string
  grouping: string
  pd_source: string
  n_groups: number
  n_rows: number
  total_exposure: number
  total_internal_provision: number
  falta_dato?: unknown[]
  metric_sections?: Record<string, unknown>
  /** Desglose por grupo homogéneo efectivo; ausente/`null` si el frame no se emitió. */
  groups?: InternalGroupRow[]
}

// --- provisiones IFRS 9 / ECL (SDD-16, experimental) ------------------------
//
// Dominio IFRS 9 / ECL de tres etapas (`provisioning_ifrs9`). Refleja el SHAPE REAL del preset
// F4 `f4-ifrs9-retail` (verificado contra una corrida real serializada por `ui/serializers`).
// Es EXPERIMENTAL (fuera de la garantía SemVer 1.x). Los MONTOS vienen SIN moneda a propósito
// (cartera genérica LatAm): la UI los formatea con un símbolo de moneda parametrizable, NO CLP
// (ver `MONEY`/`formatMoney` en `results-format`). El serializer emite la clave `null` cuando el
// dominio no corrió (p. ej. la corrida F3 de CMF/interno). La UI usa guard-por-presencia (CERO
// cálculo): un número en pantalla siempre viene del artefacto.

/** Card agregada de survival: evidencia observada del ajuste que alimenta la ficha F4. */
export interface SurvivalResult {
  method: string
  pd_source: string
  duration_col: string
  event_col: string
  time_unit: string
  n_rows: number
  n_events: number
  n_periods: number
  output_columns: string[]
  diagnostics: Record<string, unknown>
  dependency_versions?: Record<string, string>
  falta_dato?: string[]
  metric_sections?: Record<string, unknown>
}

export type MethodologyStatus = "active" | "not_exercised"

/** Afirmación individual de la ficha, ya derivada por el backend desde config + cards. */
export interface MethodologyFact {
  id: string
  status: MethodologyStatus
  label: string
  value: string
  detail: string
  sources: string[]
}

/** Ficha metodológica común a la UI y al informe; no se recalcula en TypeScript. */
export interface Ifrs9MethodologyCard {
  domain: "provisioning_ifrs9"
  active: MethodologyFact[]
  not_exercised: MethodologyFact[]
  source_refs: string[]
}

/**
 * Fila de la distribución por etapa (`provisioning_ifrs9.staging_distribution`, 3 filas: Stage
 * 1/2/3). RECONCILIA con la card titular: suma de `total_ead`/`total_ecl_reported` = los totales.
 * `coverage_ratio` = ECL/EAD del stage (proporción [0,1]). Montos sin moneda; la UI solo grafica.
 */
export interface Ifrs9StagingRow {
  stage: number
  n_rows: number
  total_ead: number
  total_ecl_reported: number
  coverage_ratio: number
}

/**
 * Fila del desglose por cartera×stage (`provisioning_ifrs9.summary`, ~12 filas = 4 carteras ×
 * 3 stages). `scenario` es la agregación de escenarios (`"all"` en la corrida base). Montos sin
 * moneda; `coverage_ratio` en proporción [0,1]. Todos los campos vienen del artefacto.
 */
export interface Ifrs9SummaryRow {
  portfolio: string
  stage: number
  scenario: string
  n_rows: number
  total_ead: number
  total_ecl_reported: number
  coverage_ratio: number
  warning_codes: string[]
}

/**
 * Punto de la curva de ECL LIFETIME (`provisioning_ifrs9.ecl_term_structure`): el runoff de la
 * pérdida esperada de la cartera período a período. `ecl_marginal` es la ECL del período;
 * `ecl_cumulative` la acumulada hasta él. OJO (honestidad, ver la pantalla): el `ecl_cumulative`
 * del último período NO iguala `total_ecl_reported` — esta curva es la forma del riesgo en el
 * tiempo (asumiendo EAD constante, FALTA-DATO-IFRS-4), distinta de la provisión contable reportada
 * que trunca por stage. `pd_marginal_weighted` es la PD marginal ponderada; `discount_factor_mean`
 * el factor de descuento medio a la EIR. Todos los floats vienen del artefacto; la UI solo grafica.
 */
export interface Ifrs9TermStructureRow {
  period: number
  /**
   * Instante CRUDO del período, en la unidad en que lo emitió el productor de la term-structure
   * (survival/markov). Reconcilia fila a fila con la curva de origen, pero NO es el exponente del
   * descuento: para eso está `time_value_years`. Viaja sin rótulo de unidad — `time_unit` se
   * consume en el motor y no llega al payload.
   */
  time_value: number
  /**
   * El mismo instante convertido a años (D-HOR-0): es el τ con el que se calculó
   * `discount_factor_mean`, y el único con el que `DF = (1 + EIR)^(-τ)` cuadra. Con una curva
   * mensual, usar `time_value` daría la tasa mensual equivalente en vez de la EIR anual.
   */
  time_value_years: number
  ecl_marginal: number
  ecl_cumulative: number
  pd_marginal_weighted: number
  discount_factor_mean: number
  n_rows: number
}

/**
 * Fila de la MUESTRA por operación (`provisioning_ifrs9.detail_sample`, 30 filas = top-10 por ECL
 * de cada stage; NO la cartera completa). `ead`/`ecl_*` sin moneda; `lgd`/`eir`/`pd_*` en
 * proporción [0,1]. `sicr_triggers` son los gatillos de SICR que dispararon para esa operación.
 */
export interface Ifrs9DetailRow {
  loan_id: string
  portfolio: string
  stage: number
  ead: number
  lgd: number
  eir: number
  pd_12m: number
  pd_life: number
  ecl_12m: number
  ecl_lifetime: number
  ecl_reported: number
  sicr_triggers: string[]
}

/**
 * Card del dominio IFRS 9 / ECL (`provisioning_ifrs9`, SDD-16). `total_ecl_reported` es la ECL
 * reportada de la cartera (la provisión contable) y `total_ead` la exposición total, AMBOS SIN
 * moneda (cartera genérica LatAm). Los conteos por etapa (`n_stage1/2/3`) reconcilian con
 * `staging_distribution`. Los frames graficables viven en `staging_distribution`, `summary`,
 * `ecl_term_structure` y `detail_sample`. `sicr_triggers` mapea gatillo→conteo de operaciones.
 * `falta_dato` documenta los supuestos conocidos (p. ej. `FALTA-DATO-IFRS-4` = EAD constante por
 * período). `scenarios`/`scenario_weights`/`dependency_versions`/`metric_sections` se tipan laxos
 * (no explotados en detalle por la UI). EXPERIMENTAL: fuera de la garantía SemVer 1.x.
 */
export interface Ifrs9ProvisioningResult {
  as_of_date: string
  term_structure_source: string
  pit_mode: string
  n_rows: number
  n_stage1: number
  n_stage2: number
  n_stage3: number
  /** Exposición total (EAD) de la cartera, SIN moneda. */
  total_ead: number
  /** ECL reportada total (provisión contable), SIN moneda. */
  total_ecl_reported: number
  scenarios: string[]
  scenario_weights: Record<string, number>
  dependency_versions?: Record<string, unknown>
  /** Avisos declarados: `FALTA-DATO-*` (brecha del motor) o `DATO-INSTITUCIONAL-*` (input del banco). */
  falta_dato: string[]
  metric_sections?: Record<string, unknown>
  /** Distribución por etapa (3 filas: Stage 1/2/3); reconcilia con los totales de la card. */
  staging_distribution: Ifrs9StagingRow[]
  /** Desglose por cartera×stage (~12 filas). */
  summary: Ifrs9SummaryRow[]
  /** Curva de ECL lifetime (runoff de la cartera período a período). */
  ecl_term_structure: Ifrs9TermStructureRow[]
  /** Gatillo de SICR → nº de operaciones que lo dispararon. */
  sicr_triggers: Record<string, number>
  /** Muestra por operación (top-30 por ECL, 10 por stage); NO la cartera completa. */
  detail_sample: Ifrs9DetailRow[]
  /** Ficha source-backed derivada del config efectivo y las cards de esta misma corrida. */
  methodology?: Ifrs9MethodologyCard | null
}

// --- model card (gobernanza) ------------------------------------------------

/**
 * Una decisión registrada en el audit-trail y materializada en la ficha (`DecisionRecord`).
 * `umbral` y `valor` son lo que el paso escribió —un número, un texto, una lista o un objeto—,
 * así que se tipan `unknown` y la pantalla los describe tal cual, sin interpretarlos.
 */
export interface ModelCardDecision {
  step: string | null
  regla: string
  umbral: unknown
  valor: unknown
  accion: string
  ts: string
}

/** Snapshot del entorno que acompañó a la corrida (`EnvironmentSnapshot`). */
export interface ModelCardEnvironment {
  python_version: string
  platform: string
  library_versions: Record<string, string>
  uv_lock_hash: string | null
  captured_at: string
}

/** Resumen auditable del dataset de entrada (`DataCardSection`); `null` si la corrida no lo dejó. */
export interface ModelCardDataDescription {
  source: string
  n_rows: number
  n_features: number
  target_col: string
  bad_rate: number
  class_counts: Record<string, number>
  partition_sizes: Record<string, number>
  partition_bad_rates: Record<string, number>
  performance_window_months: number | null
  exclusions_by_reason: Record<string, number>
  data_hash: string
}

/**
 * Ficha del modelo (`ModelCard`, D-GOB-16): las 19 claves que `ui/serializers.py` emite para una
 * corrida con `governance`, medidas sobre la respuesta real de `GET /api/results/<run_id>` y en el
 * mismo orden que el modelo Pydantic. Es `null` en toda corrida sin gobernanza —los tres fixtures
 * de la demo entre ellos— y cuando la corrida quedó demasiado parcial para una ficha válida: el
 * serializador la omite, no la fabrica.
 *
 * `metrics` es plano, `"<dominio>.<métrica>"` → número finito (D-GOB-2); `metric_sections` es un
 * nivel por dominio con el payload estructurado que ese dominio ya publica (D-GOB-3/5). Las fechas
 * son ISO-8601 en UTC. Un gate Python (`test_gobernanza_en_pantalla.py`) exige que estas claves y
 * las del modelo Pydantic sean las mismas, en los dos sentidos y en este orden.
 */
export interface ModelCard {
  run_id: string
  config_hash: string
  data_hash: string | null
  git_sha: string | null
  git_dirty: boolean
  root_seed: number
  schema_version: string
  created_at: string
  purpose: string
  assumptions: string[]
  limitations: string[]
  data_description: ModelCardDataDescription | null
  metrics: Record<string, number>
  metric_sections: Record<string, Record<string, unknown>>
  decisions: ModelCardDecision[]
  determinism_caveats: string[]
  review_date: string
  next_review_date: string
  environment: ModelCardEnvironment
}

// --- top-level --------------------------------------------------------------

/**
 * Procedencia congelada de una corrida (D-LIN-1). Es el mismo bundle que el Anexo del informe
 * publica; el panel lo enseña porque quien corre por la interfaz ve el panel **antes** que el
 * informe, y hasta ahora esa pantalla no decía de dónde salió lo que muestra.
 *
 * `null` mientras la corrida no congeló su procedencia, y **ausente** en payloads escritos antes
 * de esta clave —los tres fixtures de la demo, entre ellos—, así que se consume con
 * guard-por-presencia y nunca con `!`.
 */
export interface RunLineage {
  git_sha: string | null
  git_dirty: boolean
  data_hash: string | null
  config_hash: string
  root_seed: number
  uv_lock_hash: string | null
  library_versions: Record<string, string>
  determinism_caveats: string[]
  created_at: string
  schema_version: string
  /** Claves que entraron desde fuera de la corrida (puerta de artefactos). */
  injected_artifacts: string[]
}

/**
 * `GET /api/results/{run_id}` — ficha del modelo + DTOs por dominio. En una corrida
 * `failed` las secciones de dominio pueden faltar (payload parcial) y `error`
 * trae el mensaje; por eso las secciones son opcionales. `model_card` es `null` sin
 * `governance` —los tres fixtures de la demo entre ellos— y, con ella, la ficha tipada
 * (`ModelCard`, D-GOB-16) que el panel pinta con guard por presencia (D-GOB-15).
 */
export interface ResultsResponse {
  status: ResultsStatus
  run_id: string
  error: string | null
  model_card: ModelCard | null
  /** Procedencia de ESTA corrida. Ausente en payloads viejos; `null` si no llegó a congelarse. */
  lineage?: RunLineage | null
  binning?: BinningResult
  selection?: SelectionResult
  model?: ModelResult
  scorecard?: ScorecardResult
  calibration?: CalibrationResult
  performance?: PerformanceResult
  /** Estabilidad post-modelo (PSI/CSI). `null` si no corrió; ausente en payloads viejos. */
  stability?: StabilityResponse | null
  /**
   * Validación formal (SDD-22, D-SC-9). `null` cuando el dominio no corrió; ausente en payloads
   * anteriores a la capa 2 —incluida la demo publicada, que se recaptura con la release—, así que
   * el panel se guarda por presencia y no por verdad.
   */
  validation?: ValidationResult | null
  /** Card survival agregada; presente en F4 y `null` cuando el dominio no corrió. */
  survival?: SurvivalResult | null
  /**
   * Provisiones (SDD-28). Las tres cards salen `null` en una corrida F1 (sin provisiones) y
   * pobladas en el preset F3. Ausentes en payloads viejos anteriores al serializer de B23.5.
   */
  provisioning?: ProvisioningResult | null
  provisioning_cmf?: CmfProvisioningResult | null
  provisioning_internal?: InternalProvisioningResult | null
  /**
   * Provisiones IFRS 9 / ECL (SDD-16, experimental). `null`/ausente salvo en el preset F4
   * `f4-ifrs9-retail`; poblada cuando ese dominio corrió. Guard-por-presencia en la UI.
   */
  provisioning_ifrs9?: Ifrs9ProvisioningResult | null
}
