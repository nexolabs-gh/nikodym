/**
 * Helpers PUROS de formateo/derivación de resultados (SDD-23 §1/§3.3): la UI SOLO
 * presenta artefactos ya calculados por el backend. CERO lógica de dominio aquí —
 * no se recalcula ninguna métrica; solo se formatean números y se reordenan/derivan
 * filas para las tablas. Lógica pura, testeable con vitest sin React ni DOM (node).
 */

import type { PerformanceResult } from "@/lib/results-types"

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
 * Formatea un conteo entero con separador de miles "." (convención es-CL, sin depender
 * de `toLocaleString`/ICU para ser determinista). Ausente/no finito → `EMPTY`.
 */
export function formatCount(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return EMPTY
  return Math.trunc(x)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ".")
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
