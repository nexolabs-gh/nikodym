/**
 * Helpers PUROS de formateo/derivación de resultados (SDD-23 §1/§3.3): la UI SOLO
 * presenta artefactos ya calculados por el backend. CERO lógica de dominio aquí —
 * no se recalcula ninguna métrica; solo se formatean números y se reordenan/derivan
 * filas para las tablas. Lógica pura, testeable con vitest sin React ni DOM (node).
 */

import type {
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
export function csiBars(
  rows: StabilityMetricRow[] | null | undefined,
): CsiBarRow[] {
  if (!rows) return []
  return rows
    .filter((r) => r.metric === "csi")
    .map((r) => ({ feature: r.feature, value: r.value, band: r.band }))
    .sort(
      (a, b) =>
        (b.value ?? Number.NEGATIVE_INFINITY) -
        (a.value ?? Number.NEGATIVE_INFINITY),
    )
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
