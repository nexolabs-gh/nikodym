/**
 * Cliente HTTP mínimo del backend FastAPI de Nikodym (SDD-23 §4.2).
 *
 * B23.4a deja SOLO el cableado base: firmas tipadas de los 6 endpoints REST,
 * sin consumirlas todavía (el motor de formulario y los visores son B23.4b/B23.5).
 * Regla dura del SDD (§3.3 / §5): la UI NO reimplementa validación ni lógica de
 * dominio; la verdad vive en el backend (Pydantic). Este módulo solo transporta.
 */

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

/** Estado de una corrida. */
export type RunStatus = "done" | "failed"

/** POST /api/run */
export interface RunResponse {
  run_id: string
  status: RunStatus
}

/** GET /api/results/{run_id} — ModelCard + DTOs por dominio (forma abierta). */
export type ResultsResponse = Record<string, unknown>

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
  return request<ValidateResponse>("/api/validate", {
    method: "POST",
    body: JSON.stringify({ config }),
  })
}

/** GET /api/datasets — datasets sintéticos deterministas disponibles. */
export function listDatasets(): Promise<DatasetInfo[]> {
  return request<DatasetInfo[]>("/api/datasets")
}

/** POST /api/run — ejecuta la corrida (síncrona) vía nikodym.run. */
export function runPipeline(
  config: ConfigDict,
  datasetId: string,
): Promise<RunResponse> {
  return request<RunResponse>("/api/run", {
    method: "POST",
    body: JSON.stringify({ config, dataset_id: datasetId }),
  })
}

/** GET /api/results/{run_id} — artefactos serializados de una corrida. */
export function getResults(runId: string): Promise<ResultsResponse> {
  return request<ResultsResponse>(`/api/results/${encodeURIComponent(runId)}`)
}

/** GET /api/report/{run_id} — HTML determinístico del reporte (texto crudo). */
export async function getReport(runId: string): Promise<string> {
  const res = await fetch(
    `${API_BASE}/api/report/${encodeURIComponent(runId)}`,
  )
  if (!res.ok) {
    throw new ApiError(`HTTP ${res.status} en /api/report`, res.status)
  }
  return res.text()
}
