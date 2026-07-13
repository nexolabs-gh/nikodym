/**
 * Cliente HTTP mínimo del backend FastAPI de Nikodym (SDD-23 §4.2).
 *
 * B23.4a deja SOLO el cableado base: firmas tipadas de los 6 endpoints REST,
 * sin consumirlas todavía (el motor de formulario y los visores son B23.4b/B23.5).
 * Regla dura del SDD (§3.3 / §5): la UI NO reimplementa validación ni lógica de
 * dominio; la verdad vive en el backend (Pydantic). Este módulo solo transporta.
 */

import type { ResultsResponse } from "@/lib/results-types"
import {
  DEMO_MODE,
  demoConfigFromYaml,
  demoConfigToYaml,
  demoGetPreset,
  demoGetReport,
  demoGetReportDocx,
  demoGetReportEditable,
  demoGetReportPdf,
  demoGetResults,
  demoListDatasets,
  demoRunPipeline,
  demoValidateConfig,
} from "@/lib/demo"

// Los DTOs de resultados (B27) viven en `results-types.ts`; se re-exportan aquí para
// que store y consumidores los tomen de la misma superficie que el resto de la API.
export type { ResultsResponse } from "@/lib/results-types"

/** Base del backend; configurable por entorno, con default local. */
export const API_BASE: string =
  import.meta.env.VITE_API_BASE ?? "http://localhost:8000"

// ---------------------------------------------------------------------------
// Contratos de datos (espejo del contrato REST del SDD-23 §4.2; se afinan en
// B23.4b al consumir /api/schema). Se tipa laxo lo que aún no se explota.
// ---------------------------------------------------------------------------

/** Config declarativo editado en el front (dict JSON-able de NikodymConfig). */
export type ConfigDict = Record<string, unknown>

/** GET /api/schema */
export interface SchemaResponse {
  json_schema: Record<string, unknown>
  defaults: Record<string, unknown>
  section_order: string[]
}

/** Un error de validación estructurado (forma de `ValidationError.errors()`). */
export interface ValidationErrorItem {
  loc: (string | number)[]
  msg: string
  type: string
}

/** POST /api/validate */
export interface ValidateResponse {
  valid: boolean
  config_hash: string | null
  errors: ValidationErrorItem[]
}

/** POST /api/config/to-yaml — YAML canónico del config (`dump_config`, SDD-05 §5.5). */
export interface ConfigToYamlResponse {
  yaml: string
}

/** POST /api/config/from-yaml — config cargado + migrado desde YAML (`loads_config`, SDD-05 §5.4). */
export interface ConfigFromYamlResponse {
  config: ConfigDict
  config_hash: string
}

/**
 * GET /api/config/preset — preset estándar F1 (SDD-23 §3.2/§5): un config completo, curado y
 * *domain-agnostic* que corre end-to-end, más su identidad (`config_hash`) y el `dataset_id`
 * recomendado. La validez la produce el backend (Pydantic); el front solo lo transporta (§3.3).
 */
export interface PresetResponse {
  config: ConfigDict
  config_hash: string
  dataset_id: string
  name: string
  description: string
}

/** Columna de un dataset sintético. */
export interface DatasetColumn {
  name: string
  dtype: string
  role: string
}

/** GET /api/datasets (un item) */
export interface DatasetInfo {
  id: string
  name: string
  description: string
  columns: DatasetColumn[]
  n_rows: number
}

/**
 * POST /api/upload (un item) — dataset propio subido por el usuario (B36b). Su forma difiere
 * del catálogo: la clave es `dataset_id` (no `id`) y las columnas NO traen `role`.
 */
export interface UploadedDataset {
  dataset_id: string
  name: string
  n_rows: number
  columns: { name: string; dtype: string }[]
}

/** Estado de una corrida. */
export type RunStatus = "done" | "failed"

/** POST /api/run */
export interface RunResponse {
  run_id: string
  status: RunStatus
}

// `ResultsResponse` se define y tipa en `results-types.ts` (re-exportado arriba).

// ---------------------------------------------------------------------------
// Helper de transporte
// ---------------------------------------------------------------------------

/** Error de red/HTTP del cliente (no de dominio). */
export class ApiError extends Error {
  readonly status: number
  readonly body?: unknown

  constructor(message: string, status: number, body?: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    let body: unknown
    try {
      body = await res.json()
    } catch {
      body = await res.text().catch(() => undefined)
    }
    throw new ApiError(`HTTP ${res.status} en ${path}`, res.status, body)
  }
  return (await res.json()) as T
}

// ---------------------------------------------------------------------------
// Stubs tipados de los 6 endpoints (aún sin uso en B23.4a; ver SDD-23 §4.2)
// ---------------------------------------------------------------------------

/** GET /api/schema — JSON-Schema de NikodymConfig + defaults + orden de secciones. */
export function getSchema(): Promise<SchemaResponse> {
  return request<SchemaResponse>("/api/schema")
}

/** POST /api/validate — valida por reconstrucción en el backend (siempre 200). */
export function validateConfig(config: ConfigDict): Promise<ValidateResponse> {
  if (DEMO_MODE) return demoValidateConfig()
  return request<ValidateResponse>("/api/validate", {
    method: "POST",
    body: JSON.stringify({ config }),
  })
}

/**
 * POST /api/config/to-yaml — exporta el config editado a YAML canónico (round-trip, SDD-23
 * §3.4). El backend reconstruye `NikodymConfig` y delega en `dump_config`; lanza `ApiError`
 * (422 con `{detail:[{loc,msg,type}]}`) si el config no reconstruye un modelo válido.
 */
export function configToYaml(config: ConfigDict): Promise<ConfigToYamlResponse> {
  if (DEMO_MODE) return demoConfigToYaml()
  return request<ConfigToYamlResponse>("/api/config/to-yaml", {
    method: "POST",
    body: JSON.stringify({ config }),
  })
}

/**
 * POST /api/config/from-yaml — carga (y migra) un YAML a config + `config_hash` para poblar el
 * form (round-trip, SDD-23 §3.4). El backend es la fuente: NO se parsea YAML en el front. Lanza
 * `ApiError` (422 con `{detail:"…"}`) si el YAML es malformado o falla la migración/validación.
 */
export function configFromYaml(
  yamlText: string,
): Promise<ConfigFromYamlResponse> {
  if (DEMO_MODE) return demoConfigFromYaml()
  return request<ConfigFromYamlResponse>("/api/config/from-yaml", {
    method: "POST",
    body: JSON.stringify({ yaml: yamlText }),
  })
}

/**
 * GET /api/config/preset — preset estándar F1 (SDD-23 §3.2/§5): el config curado listo para correr
 * que la UI siembra por defecto. El front no reimplementa su lógica: el backend lo compone y valida.
 */
export function getPreset(): Promise<PresetResponse> {
  if (DEMO_MODE) return demoGetPreset()
  return request<PresetResponse>("/api/config/preset")
}

/** GET /api/datasets — datasets sintéticos deterministas disponibles. */
export function listDatasets(): Promise<DatasetInfo[]> {
  if (DEMO_MODE) return demoListDatasets()
  return request<DatasetInfo[]>("/api/datasets")
}

/**
 * POST /api/upload — sube un dataset propio (.csv/.xlsx/.parquet) como `multipart/form-data`.
 * fetch CRUDO (molde de `getReport`): NO usa `request()`, porque ese helper fuerza
 * `Content-Type: application/json`, lo que rompería el multipart (el browser debe poner el
 * `boundary` por sí mismo). Reproduce el manejo de error de `request()`: lee el body
 * (json → text) y lanza `ApiError` con el status y el cuerpo. El front solo transporta.
 */
export async function uploadDataset(file: File): Promise<UploadedDataset> {
  if (DEMO_MODE) {
    throw new ApiError(
      "La subida de datasets no está disponible en la demo. Usa el dataset de ejemplo ya cargado.",
      0,
    )
  }
  const form = new FormData()
  form.append("file", file)
  const res = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    body: form,
  })
  if (!res.ok) {
    let body: unknown
    try {
      body = await res.json()
    } catch {
      body = await res.text().catch(() => undefined)
    }
    throw new ApiError(`HTTP ${res.status} en /api/upload`, res.status, body)
  }
  return (await res.json()) as UploadedDataset
}

/** POST /api/run — ejecuta la corrida (síncrona) vía nikodym.run. */
export function runPipeline(
  config: ConfigDict,
  datasetId: string,
): Promise<RunResponse> {
  if (DEMO_MODE) return demoRunPipeline()
  return request<RunResponse>("/api/run", {
    method: "POST",
    body: JSON.stringify({ config, dataset_id: datasetId }),
  })
}

/** GET /api/results/{run_id} — artefactos serializados de una corrida. */
export function getResults(runId: string): Promise<ResultsResponse> {
  if (DEMO_MODE) return demoGetResults()
  return request<ResultsResponse>(`/api/results/${encodeURIComponent(runId)}`)
}

/** GET /api/report/{run_id} — HTML determinístico del reporte (texto crudo). */
export async function getReport(runId: string): Promise<string> {
  if (DEMO_MODE) return demoGetReport()
  const res = await fetch(
    `${API_BASE}/api/report/${encodeURIComponent(runId)}`,
  )
  if (!res.ok) {
    throw new ApiError(`HTTP ${res.status} en /api/report`, res.status)
  }
  return res.text()
}

/**
 * GET /api/report/{run_id}/pdf — PDF del reporte (binario). Espejo de `getReport` pero devuelve
 * el `Blob` en vez de texto. El PDF es opt-in (se pide vía `formats`): un 404 significa que esa
 * corrida no lo generó (lo mapea `reportPdfErrorMessage`). El front solo transporta y descarga.
 */
export async function getReportPdf(runId: string): Promise<Blob> {
  if (DEMO_MODE) return demoGetReportPdf()
  const res = await fetch(
    `${API_BASE}/api/report/${encodeURIComponent(runId)}/pdf`,
  )
  if (!res.ok) {
    throw new ApiError(`HTTP ${res.status} en /api/report/pdf`, res.status)
  }
  return res.blob()
}

/**
 * GET /api/report/{run_id}/md — la BASE EDITABLE, como ZIP (`.qmd` de Quarto + sus figuras).
 *
 * Va empaquetada porque el `.qmd` referencia las figuras por ruta relativa: bajar el texto solo
 * daría un informe con las imágenes rotas. Opt-in vía `formats`, igual que el PDF: un 404 quiere
 * decir que la corrida no la generó.
 */
export async function getReportEditable(runId: string): Promise<Blob> {
  if (DEMO_MODE) return demoGetReportEditable()
  const res = await fetch(`${API_BASE}/api/report/${encodeURIComponent(runId)}/md`)
  if (!res.ok) {
    throw new ApiError(`HTTP ${res.status} en /api/report/md`, res.status)
  }
  return res.blob()
}

/** GET /api/report/{run_id}/docx — el informe en Word. Opt-in vía `formats` (404 si no se generó). */
export async function getReportDocx(runId: string): Promise<Blob> {
  if (DEMO_MODE) return demoGetReportDocx()
  const res = await fetch(`${API_BASE}/api/report/${encodeURIComponent(runId)}/docx`)
  if (!res.ok) {
    throw new ApiError(`HTTP ${res.status} en /api/report/docx`, res.status)
  }
  return res.blob()
}
