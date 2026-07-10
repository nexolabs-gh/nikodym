/**
 * Lógica PURA de la pestaña Datos (sin React): normaliza las dos formas de dataset a un
 * tipo común y valida la extensión antes de subir. El catálogo (GET /api/datasets) trae
 * `id` y columnas con `role`; una subida (POST /api/upload) trae `dataset_id` y columnas
 * SIN `role`. El front las unifica en `SelectedDataset` para poder previsualizar cualquiera
 * de las dos igual. Testeable con vitest en entorno `node`, como el resto de `lib/*.test.ts`.
 */

import type { DatasetInfo, UploadedDataset } from "./api"

/**
 * Dataset elegido, normalizado desde cualquiera de las dos rutas (catálogo o subida). `role`
 * es opcional: el catálogo lo trae por columna; una subida no lo conoce y queda `undefined`.
 */
export interface SelectedDataset {
  id: string
  name: string
  nRows: number
  columns: { name: string; dtype: string; role?: string }[]
}

/** Extensiones que acepta POST /api/upload (B36b): CSV, Excel y Parquet. */
export const ALLOWED_DATA_EXTENSIONS = [".csv", ".xlsx", ".parquet"] as const

/**
 * ¿El nombre de archivo tiene una extensión de dataset aceptada? (case-insensitive). Útil para
 * dar un error local claro ANTES de subir, sin depender de que el backend rechace el archivo.
 */
export function isAllowedDataFile(filename: string): boolean {
  const lower = filename.toLowerCase()
  return ALLOWED_DATA_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

/** Normaliza un item del catálogo (conserva `id` y el `role` de cada columna). */
export function fromCatalog(info: DatasetInfo): SelectedDataset {
  return {
    id: info.id,
    name: info.name,
    nRows: info.n_rows,
    columns: info.columns.map((c) => ({
      name: c.name,
      dtype: c.dtype,
      role: c.role,
    })),
  }
}

/** Normaliza la respuesta de una subida (usa `dataset_id`; sus columnas no traen `role`). */
export function fromUpload(resp: UploadedDataset): SelectedDataset {
  return {
    id: resp.dataset_id,
    name: resp.name,
    nRows: resp.n_rows,
    columns: resp.columns.map((c) => ({
      name: c.name,
      dtype: c.dtype,
      role: undefined,
    })),
  }
}

/** Etiqueta de una opción del selector de catálogo, p.ej. `Consumo · 10.000 filas`. */
export function datasetOptionLabel(info: DatasetInfo): string {
  return `${info.name} · ${info.n_rows.toLocaleString("es-CL")} filas`
}
