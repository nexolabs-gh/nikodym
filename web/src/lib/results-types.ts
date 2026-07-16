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
 * SOBRECOSTO = reportada − interna (SDD-28 §3.5), en CLP. `binding` dice qué método mandó.
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
  /** Provisión del método estándar (source_a), en CLP. */
  total_provision_a: number
  /** Provisión del método interno (source_b), en CLP. */
  total_provision_b: number
  /** Provisión reportada = mayor(estándar, interno), en CLP. */
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
 * Fila por grupo homogéneo del método interno (`provisioning_internal.groups`, 10 bandas de
 * score con `grouping:"score_band"`). Es la tabla que un validador pide: PD·LGD·Exposición por
 * grupo. `pd_group`/`lgd_group`/`expected_loss_rate` son PROPORCIONES [0,1]; `provision_amount`
 * y `total_exposure` en CLP.
 */
export interface InternalGroupRow {
  group_id: string
  portfolio: string
  n_operations: number
  total_exposure: number
  pd_group: number
  lgd_group: number
  expected_loss_rate: number
  provision_amount: number
  warning_codes: string[]
}

/**
 * Card del método interno (`provisioning_internal`): provisión = Exposición · PD · LGD por grupo
 * homogéneo (B-1 §3). `total_internal_provision` es la provisión interna total (CLP);
 * `total_exposure` las colocaciones (CLP). El desglose por grupo vive en `groups`.
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
  /** Desglose por grupo homogéneo (10 bandas); ausente/`null` si el frame no se emitió. */
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
  time_value: number
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
  /** Códigos de dato faltante/supuesto (p. ej. `["FALTA-DATO-IFRS-4"]` = EAD constante). */
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
