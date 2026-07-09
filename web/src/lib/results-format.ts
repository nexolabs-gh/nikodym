/**
 * Helpers PUROS de formateo/derivación de resultados (SDD-23 §1/§3.3): la UI SOLO
 * presenta artefactos ya calculados por el backend. CERO lógica de dominio aquí —
 * no se recalcula ninguna métrica; solo se formatean números y se reordenan/derivan
 * filas para las tablas. Lógica pura, testeable con vitest sin React ni DOM (node).
 */

import type {
  BinningResult,
  BinRow,
  DecileRow,
  PerformanceResult,
  StabilityBand,
  StabilityMetricRow,
} from "@/lib/results-types"

/** Placeholder uniforme para valores ausentes/no finitos en toda la pestaña. */
export const EMPTY = "—"

/**
 * Formatea una métrica numérica a `digits` decimales fijos (default 4, para AUC/Gini/KS).
 * Ausente/no finito → `EMPTY`. NO redondea con criterio de dominio: solo presentación.
 */
export function formatMetric(
  x: number | null | undefined,
  digits = 4,
): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return EMPTY
  return x.toFixed(digits)
}

/**
 * Formatea un p-value: valores diminutos (|x| < 1e-4) en notación exponencial (así no
 * colapsan a "0.0000"); el resto a 4 decimales. Ausente/no finito → `EMPTY`.
 */
export function formatPValue(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return EMPTY
  if (x !== 0 && Math.abs(x) < 1e-4) return x.toExponential(1)
  return x.toFixed(4)
}

/**
 * Formatea una proporción [0,1] como porcentaje (default 1 decimal). Ausente/no
 * finito → `EMPTY`. Presentación pura: no interpreta el número.
 */
export function formatPercent(
  x: number | null | undefined,
  digits = 1,
): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return EMPTY
  return `${(x * 100).toFixed(digits)}%`
}

/**
 * Formatea un conteo entero con separador de miles "," INEQUÍVOCO (convención anglo:
 * coma = miles, punto = decimal), sin depender de `toLocaleString`/ICU para ser
 * determinista. Así "3,961" (conteo) no se confunde con "0.71" (métrica decimal).
 * Ausente/no finito → `EMPTY`.
 */
export function formatCount(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return EMPTY
  return Math.trunc(x)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

/** Booleano legible en español; `null`/`undefined` → `EMPTY`. */
export function formatBool(x: boolean | null | undefined): string {
  if (x === true) return "Sí"
  if (x === false) return "No"
  return EMPTY
}

/** Fila de métricas de discriminación normalizada para la tabla (una por partición). */
export interface MetricRow {
  partition: string
  auc: number | null
  gini: number | null
  ks: number | null
}

/**
 * Deriva las filas de discriminación (AUC/Gini/KS por partición) desde `performance`.
 * Prefiere `discriminant` (rico) y cae a `max_metrics_by_partition` respetando el orden
 * de `partitions`. NO calcula métricas: solo selecciona/reordena las ya materializadas.
 */
export function discriminantRows(
  performance: PerformanceResult | undefined,
): MetricRow[] {
  if (!performance) return []

  const { discriminant, max_metrics_by_partition, partitions } = performance

  if (Array.isArray(discriminant) && discriminant.length > 0) {
    return discriminant.map((d) => ({
      partition: d.partition,
      auc: d.auc ?? null,
      gini: d.gini ?? null,
      ks: d.ks ?? null,
    }))
  }

  if (max_metrics_by_partition) {
    const order =
      partitions && partitions.length > 0
        ? partitions
        : Object.keys(max_metrics_by_partition)
    return order
      .filter((p) => p in max_metrics_by_partition)
      .map((p) => {
        const m = max_metrics_by_partition[p]
        return {
          partition: p,
          auc: m.auc ?? null,
          gini: m.gini ?? null,
          ks: m.ks ?? null,
        }
      })
  }

  return []
}

/** Fila de IV por variable (feature → IV) normalizada para la tabla. */
export interface IvRow {
  feature: string
  iv: number
}

/**
 * Ordena `iv_by_variable` (feature → IV) de mayor a menor IV. NO filtra ni umbraliza:
 * solo reordena lo que el backend ya calculó.
 */
export function sortByIv(
  ivByVariable: Record<string, number> | undefined,
): IvRow[] {
  if (!ivByVariable) return []
  return Object.entries(ivByVariable)
    .map(([feature, iv]) => ({ feature, iv }))
    .sort((a, b) => b.iv - a.iv)
}

// --- estabilidad (PSI/CSI) --------------------------------------------------

/**
 * Orden canónico de comparaciones en los charts de PSI (las temporales al final). Una
 * comparación fuera de esta lista se ordena después, preservando su orden de llegada.
 */
const COMPARISON_ORDER = ["dev_vs_holdout", "dev_vs_oot", "period"] as const

/** Índice de orden de una comparación (desconocida → al final). */
function comparisonOrder(comparison: string): number {
  const i = COMPARISON_ORDER.indexOf(comparison as (typeof COMPARISON_ORDER)[number])
  return i === -1 ? COMPARISON_ORDER.length : i
}

/**
 * Etiqueta legible de una comparación de estabilidad. Fallback (comparación no prevista):
 * el propio slug, para no ocultar nada. Presentación pura, sin lógica de dominio.
 */
export function comparisonLabel(comparison: string): string {
  switch (comparison) {
    case "dev_vs_holdout":
      return "Dev vs Holdout"
    case "dev_vs_oot":
      return "Dev vs OOT"
    case "period":
      return "Temporal"
    default:
      return comparison
  }
}

/** Barra de PSI por comparación (una por comparison), coloreada por banda. */
export interface PsiBarRow {
  comparison: string
  label: string
  value: number | null
  band: StabilityBand
}

/**
 * Filas de PSI por comparación para una métrica dada (`score_psi` o `pd_psi`), ordenadas
 * por el orden canónico de comparaciones. NO recalcula: `value`/`band` vienen del artefacto.
 */
export function psiBars(
  rows: StabilityMetricRow[] | null | undefined,
  metric: "score_psi" | "pd_psi",
): PsiBarRow[] {
  if (!rows) return []
  return rows
    .filter((r) => r.metric === metric)
    .map((r) => ({
      comparison: r.comparison,
      label: comparisonLabel(r.comparison),
      value: r.value,
      band: r.band,
    }))
    .sort((a, b) => comparisonOrder(a.comparison) - comparisonOrder(b.comparison))
}

/** Barra de CSI por característica, coloreada por banda. */
export interface CsiBarRow {
  feature: string
  value: number | null
  band: StabilityBand
}

/**
 * Filas de CSI por característica (`metric == "csi"`) ordenadas de mayor a menor CSI
 * (nulos al final). Solo selecciona/reordena lo que el backend ya calculó.
 */
/**
 * Elige la comparación de CSI a mostrar: prefiere la temporal (dev_vs_oot) — el drift
 * out-of-time es el que degrada un scorecard en producción; el holdout es un split aleatorio
 * (ruido ~0). Fallback a la primera comparación presente. `null` si no hay filas CSI.
 */
function selectCsiComparison(csiRows: StabilityMetricRow[]): string | null {
  const comparisons = [...new Set(csiRows.map((r) => r.comparison))]
  return comparisons.find((c) => c.includes("oot")) ?? comparisons[0] ?? null
}

/**
 * Barras de CSI por característica, de UNA sola comparación (la temporal; ver
 * `selectCsiComparison`), ordenadas por CSI desc con los nulos al final. Mostrar una única
 * comparación evita barras ambiguas con la misma etiqueta (el CSI se reporta por
 * feature×comparación). Solo lee/filtra/ordena; CERO cálculo.
 */
export function csiBars(
  rows: StabilityMetricRow[] | null | undefined,
): CsiBarRow[] {
  if (!rows) return []
  const csi = rows.filter((r) => r.metric === "csi")
  const comparison = selectCsiComparison(csi)
  if (comparison === null) return []
  return csi
    .filter((r) => r.comparison === comparison)
    .map((r) => ({ feature: r.feature, value: r.value, band: r.band }))
    .sort(
      (a, b) =>
        (b.value ?? Number.NEGATIVE_INFINITY) -
        (a.value ?? Number.NEGATIVE_INFINITY),
    )
}

/**
 * Label legible de la comparación de CSI que muestra `csiBars` (para el título del visor):
 * "dev vs OOT" / "dev vs holdout". `null` si no hay CSI. Presentación pura.
 */
export function csiComparisonLabel(
  rows: StabilityMetricRow[] | null | undefined,
): string | null {
  if (!rows) return null
  const comparison = selectCsiComparison(rows.filter((r) => r.metric === "csi"))
  if (comparison === null) return null
  return comparison.replace(/_/g, " ").replace(/\boot\b/gi, "OOT")
}

/** Escalar de estabilidad temporal (`metric == "temporal_score"`). */
export interface TemporalScore {
  value: number | null
  band: StabilityBand
}

/**
 * Extrae el escalar `temporal_score` (una sola fila) o `null` si no está. NO fabrica una
 * serie temporal: el detalle por período no viene en `stability_metrics`.
 */
export function temporalScore(
  rows: StabilityMetricRow[] | null | undefined,
): TemporalScore | null {
  if (!rows) return null
  const row = rows.find((r) => r.metric === "temporal_score")
  return row ? { value: row.value, band: row.band } : null
}

/**
 * Bandas presentes en un conjunto de filas de estabilidad, en el orden semántico
 * canónico (estable → revisar → redesarrollar → no evaluable). Alimenta la leyenda: se
 * muestran siempre las tres primarias más `not_evaluable` solo si aparece en los datos.
 */
export function bandsPresent(
  rows: StabilityMetricRow[] | null | undefined,
): StabilityBand[] {
  const order: StabilityBand[] = [
    "stable",
    "review",
    "redevelop",
    "not_evaluable",
  ]
  const present = new Set((rows ?? []).map((r) => r.band))
  return order.filter(
    (b) => b !== "not_evaluable" || present.has("not_evaluable"),
  )
}

// --- deciles: gains / lift --------------------------------------------------

/** Orden canónico de particiones en los charts (desconocida → al final). */
const PARTITION_ORDER = ["desarrollo", "holdout", "oot"] as const

/** Índice de orden de una partición (fuera del orden canónico → al final). */
function partitionRank(partition: string): number {
  const i = PARTITION_ORDER.indexOf(
    partition as (typeof PARTITION_ORDER)[number],
  )
  return i === -1 ? PARTITION_ORDER.length : i
}

/**
 * Etiqueta legible de una partición. Fallback: el propio slug (no oculta nada).
 * Presentación pura, sin lógica de dominio.
 */
export function partitionLabel(partition: string): string {
  switch (partition) {
    case "desarrollo":
      return "Desarrollo"
    case "holdout":
      return "Holdout"
    case "oot":
      return "OOT"
    default:
      return partition
  }
}

/**
 * Partición "principal" para los charts de una sola serie (lift): la preferida
 * (`desarrollo` por defecto) si está presente, si no la primera que aparezca; `null`
 * si no hay deciles. NO calcula nada: solo elige qué partición mostrar.
 */
export function primaryPartition(
  deciles: DecileRow[] | undefined,
  preferred = "desarrollo",
): string | null {
  if (!deciles || deciles.length === 0) return null
  if (deciles.some((d) => d.partition === preferred)) return preferred
  return deciles[0]?.partition ?? null
}

/**
 * Punto de la curva de ganancias. `decile` es el eje X (0 = ancla de origen, ver más
 * abajo); `random` es la diagonal del modelo aleatorio; cada clave de partición trae su
 * `cum_bad_capture_rate` en ese decil (o `null` si esa partición no tiene ese decil).
 */
export interface GainsRow {
  decile: number
  random: number
  [partition: string]: number | null
}

/** Serie de ganancias lista para Recharts: qué particiones hay y los puntos por decil. */
export interface GainsSeries {
  /** Particiones presentes, en orden canónico (desarrollo → holdout → oot → …). */
  partitions: string[]
  data: GainsRow[]
}

/**
 * Deriva la curva de ganancias (gains) desde `performance.deciles`: para cada partición,
 * `cum_bad_capture_rate` (Y, 0–1) por decil (X). Añade la diagonal `random` (modelo
 * aleatorio: decil k → k/N, con N = nº de deciles presentes) y una fila ANCLA en el
 * origen (decil 0 → 0 en todas las series): 0 deciles examinados capturan 0% de malos,
 * es el punto definitorio (0,0) —igual estatus que la diagonal de referencia—, NO un
 * dato fabricado del backend. CERO cálculo de dominio: solo selecciona/reordena lo que el
 * backend ya materializó y añade referencias de lectura.
 */
export function gainsSeries(deciles: DecileRow[] | undefined): GainsSeries {
  if (!deciles || deciles.length === 0) return { partitions: [], data: [] }

  const partitions = [...new Set(deciles.map((d) => d.partition))].sort(
    (a, b) => partitionRank(a) - partitionRank(b),
  )
  const decileNums = [...new Set(deciles.map((d) => d.decile))].sort(
    (a, b) => a - b,
  )
  if (decileNums.length === 0) return { partitions: [], data: [] }
  const maxDecile = decileNums[decileNums.length - 1] ?? 1

  // Índice (partición|decil) → ganancia acumulada, para armar cada fila del eje X.
  const capture = new Map<string, number>()
  for (const d of deciles) {
    capture.set(`${d.partition}|${d.decile}`, d.cum_bad_capture_rate)
  }

  const origin: GainsRow = { decile: 0, random: 0 }
  for (const p of partitions) origin[p] = 0

  const data: GainsRow[] = [origin]
  for (const k of decileNums) {
    const row: GainsRow = { decile: k, random: maxDecile > 0 ? k / maxDecile : 0 }
    for (const p of partitions) {
      const v = capture.get(`${p}|${k}`)
      row[p] = v === undefined ? null : v
    }
    data.push(row)
  }

  return { partitions, data }
}

/** Fila de lift por decil (para el chart de barras de una partición). */
export interface LiftRow {
  decile: number
  lift: number
  bad_rate: number
  n_total: number
}

/**
 * Lift por decil de UNA partición (default `desarrollo`), ordenado por decil ascendente.
 * NO recalcula: `lift`/`bad_rate` vienen del artefacto. Devuelve `[]` si la partición no
 * está presente.
 */
export function liftByDecile(
  deciles: DecileRow[] | undefined,
  partition = "desarrollo",
): LiftRow[] {
  if (!deciles || deciles.length === 0) return []
  return deciles
    .filter((d) => d.partition === partition)
    .sort((a, b) => a.decile - b.decile)
    .map((d) => ({
      decile: d.decile,
      lift: d.lift,
      bad_rate: d.bad_rate,
      n_total: d.n_total,
    }))
}

// --- histograma del score (PRESENTACIÓN pura, testeada) ---------------------

/** Un bin del histograma: [x0, x1) con su punto medio y su frecuencia. */
export interface HistogramBin {
  /** Límite inferior del bin (score). */
  x0: number
  /** Límite superior del bin (score). */
  x1: number
  /** Punto medio del bin (posición del eje X). */
  center: number
  /** Frecuencia (nº de observaciones en el bin). */
  count: number
}

/** Histograma del score + estadísticos descriptivos de la muestra dibujada. */
export interface ScoreHistogram {
  bins: HistogramBin[]
  /** Ancho de bin ((max−min)/nBins); 0 en el caso degenerado (todos iguales). */
  binWidth: number
  min: number
  max: number
  /** Nº de valores finitos considerados. */
  count: number
  /** Media de la muestra dibujada (referencia de lectura, no un corte de dominio). */
  mean: number
  /** Mediana de la muestra dibujada (referencia de lectura). */
  median: number
}

/**
 * Agrupa los ~6000 scores crudos en bins de ancho uniforme para DIBUJAR el histograma.
 * Esto es PRESENTACIÓN (min/max/ancho de bin), NO lógica de dominio: no umbraliza ni
 * decide cortes de riesgo. La media/mediana son estadísticos descriptivos de la MISMA
 * muestra que se dibuja (referencias de lectura, igual naturaleza que el conteo por bin).
 * Helper puro y testeable. Devuelve `null` si no hay valores finitos (guard por presencia).
 * El valor máximo cae en el último bin (borde derecho cerrado) para no perder la cola.
 */
export function scoreHistogram(
  values: readonly number[] | undefined,
  binCount = 24,
): ScoreHistogram | null {
  if (!values || values.length === 0) return null
  const finite = values.filter((v) => Number.isFinite(v))
  if (finite.length === 0) return null

  const bins = Math.max(1, Math.floor(binCount))
  let min = finite[0]
  let max = finite[0]
  let sum = 0
  for (const v of finite) {
    if (v < min) min = v
    if (v > max) max = v
    sum += v
  }
  const mean = sum / finite.length

  const sorted = [...finite].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  const median =
    sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]

  const range = max - min
  // Degenerado (todos iguales): un solo bin centrado en el valor común.
  if (range === 0) {
    return {
      bins: [{ x0: min, x1: max, center: min, count: finite.length }],
      binWidth: 0,
      min,
      max,
      count: finite.length,
      mean,
      median,
    }
  }

  const binWidth = range / bins
  const counts = new Array<number>(bins).fill(0)
  for (const v of finite) {
    let idx = Math.floor((v - min) / binWidth)
    if (idx >= bins) idx = bins - 1 // el máximo cae en el último bin
    if (idx < 0) idx = 0
    counts[idx] += 1
  }

  const out: HistogramBin[] = counts.map((count, i) => {
    const x0 = min + i * binWidth
    const x1 = i === bins - 1 ? max : min + (i + 1) * binWidth
    return { x0, x1, center: (x0 + x1) / 2, count }
  })

  return { bins: out, binWidth, min, max, count: finite.length, mean, median }
}

// --- binning: WoE por bin (detalle por variable, 3er batch de visores) -------

/**
 * Normaliza la etiqueta de un bin a un string legible. Un bin NUMÉRICO ya llega como
 * string ("[a, b)"); un bin CATEGÓRICO llega como array (`["independiente"]`) → se une con
 * ", ". Presentación pura: no reordena ni reinterpreta las categorías.
 */
export function normalizeBinLabel(bin: string | (string | number)[]): string {
  return Array.isArray(bin) ? bin.map(String).join(", ") : bin
}

/**
 * WoE a `number` o `null`. La fila Totals trae el WoE como string vacío (`""`), y cualquier
 * WoE no numérico/no finito se trata como `null` (nunca NaN). NO recalcula el WoE: solo lo
 * lee y lo normaliza para graficar/formatear.
 */
function woeToNumber(woe: number | string): number | null {
  return typeof woe === "number" && Number.isFinite(woe) ? woe : null
}

/** ¿Es la fila el agregado Totals? Convención del backend: `Bin` es el string vacío. */
function isTotalsRow(row: BinRow): boolean {
  return typeof row.Bin === "string" && row.Bin === ""
}

/**
 * Fila normalizada de un bin real (Count>0, sin Totals): alimenta a la vez la curva WoE y
 * la tabla de detalle. Todos los campos vienen del artefacto; solo se normaliza la etiqueta
 * y el WoE string→null.
 */
export interface BinDetailRow {
  binLabel: string
  count: number
  countPct: number
  nonEvent: number
  event: number
  eventRate: number
  /** WoE del bin (number); `null` solo si el payload no trajo un número finito. */
  woe: number | null
  iv: number
  js: number
}

/** Agregado de la variable (fila Totals) para el pie de la tabla de detalle. */
export interface BinTotal {
  totalCount: number
  baseEventRate: number
  ivTotal: number
  countPct: number
  nonEvent: number
  event: number
  js: number
}

/** Monotonicidad de un binning numérico; `null` = categórica / no aplicable. */
export type BinMonotonicity = "ascending" | "descending" | null

/** Detalle de binning de UNA variable: filas graficables + agregado + metadatos. */
export interface VariableBinning {
  variable: string
  /** Bins reales (Count>0, sin la fila Totals): alimentan el chart y la tabla. */
  rows: BinDetailRow[]
  /** Fila Totals (pie de tabla); `null` si el payload no la trajo. */
  total: BinTotal | null
  /** IV total de la variable (de `iv_by_variable`; fallback a la fila Totals). */
  ivTotal: number | null
  /** Monotonicidad declarada por el binning (asc/desc) o `null` (categórica). */
  monotonicity: BinMonotonicity
}

/**
 * Deriva el detalle de binning de una variable desde `binning.tables_by_variable[var]`.
 * Separa la fila Totals (`Bin==""`) del resto, filtra los bins vacíos (Count==0, p.ej.
 * "Special"/"Missing" sin datos — el filtro es por Count, NO por el nombre) para no ensuciar
 * chart ni tabla, y normaliza etiquetas y el WoE string→null. CERO cálculo de riesgo: solo
 * lee/normaliza/reordena campos ya materializados por el motor. Devuelve `null` si la
 * variable no tiene tabla.
 */
export function variableBinning(
  binning: BinningResult | undefined,
  variable: string,
): VariableBinning | null {
  const table = binning?.tables_by_variable?.[variable]
  if (!table || table.length === 0) return null

  const rows: BinDetailRow[] = table
    .filter((r) => !isTotalsRow(r) && r.Count > 0)
    .map((r) => ({
      binLabel: normalizeBinLabel(r.Bin),
      count: r.Count,
      countPct: r["Count (%)"],
      nonEvent: r["Non-event"],
      event: r.Event,
      eventRate: r["Event rate"],
      woe: woeToNumber(r.WoE),
      iv: r.IV,
      js: r.JS,
    }))

  const totalsRow = table.find(isTotalsRow) ?? null
  const total: BinTotal | null = totalsRow
    ? {
        totalCount: totalsRow.Count,
        baseEventRate: totalsRow["Event rate"],
        ivTotal: totalsRow.IV,
        countPct: totalsRow["Count (%)"],
        nonEvent: totalsRow["Non-event"],
        event: totalsRow.Event,
        js: totalsRow.JS,
      }
    : null

  const ivFromMap = binning?.iv_by_variable?.[variable]
  const ivTotal =
    typeof ivFromMap === "number" && Number.isFinite(ivFromMap)
      ? ivFromMap
      : (total?.ivTotal ?? null)

  const rawMono = binning?.monotonicity_by_variable?.[variable]
  const monotonicity: BinMonotonicity =
    rawMono === "ascending" || rawMono === "descending" ? rawMono : null

  return { variable, rows, total, ivTotal, monotonicity }
}

/** Variable con tabla de binning (para el selector), con su IV total. */
export interface BinnedVariable {
  feature: string
  iv: number
}

/**
 * Variables que tienen tabla de binning, ordenadas por IV DESC (para el selector). El IV
 * sale de `iv_by_variable`; si faltara, se cae a la fila Totals de la tabla y, en último
 * término, a 0. Solo reordena lo que el backend ya calculó (no umbraliza ni filtra por IV).
 */
export function binnedVariables(
  binning: BinningResult | undefined,
): BinnedVariable[] {
  const tables = binning?.tables_by_variable
  if (!tables) return []
  return Object.keys(tables)
    .map((feature) => {
      const ivFromMap = binning.iv_by_variable?.[feature]
      if (typeof ivFromMap === "number" && Number.isFinite(ivFromMap)) {
        return { feature, iv: ivFromMap }
      }
      const totals = tables[feature]?.find(isTotalsRow)
      return { feature, iv: totals ? totals.IV : 0 }
    })
    .sort((a, b) => b.iv - a.iv)
}

/** Etiqueta humana de la monotonicidad (chip del header). Presentación pura. */
export function monotonicityLabel(m: BinMonotonicity): string {
  switch (m) {
    case "ascending":
      return "Monótona ascendente"
    case "descending":
      return "Monótona descendente"
    default:
      return "Categórica"
  }
}
