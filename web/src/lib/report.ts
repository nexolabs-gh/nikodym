/**
 * Helpers PUROS de la pestaña Reporte (B38b). El reporte HTML lo PRODUCE el backend
 * (`GET /api/report/{run_id}`); el front SOLO lo transporta, embebe y descarga —CERO lógica
 * de dominio (SDD-23 §1)—. Aquí vive la parte pura y testeable sin React ni DOM (entorno
 * node): el nombre fijo del archivo de descarga y el mapeo de un fallo de la API a un mensaje
 * legible, con el 404 ("la corrida no generó reporte") tratado como caso claro y no como HTTP
 * crudo. Imports relativos (molde de `datasets.ts`) para no necesitar el alias `@/` en vitest.
 */

import { ApiError } from "./api"
import { describeApiError } from "./validation"

/** Nombre fijo del archivo al descargar el reporte (independiente del `run_id`). */
export const REPORT_FILENAME = "reporte-modelo.html"

/** Nombre fijo del archivo al descargar el PDF del reporte (independiente del `run_id`). */
export const REPORT_PDF_FILENAME = "reporte-modelo.pdf"

/**
 * Mensaje legible de un fallo al pedir el reporte. Un `ApiError` 404 significa que la corrida
 * existe pero no generó reporte → mensaje claro y accionable, no el status HTTP crudo. Otro
 * `ApiError` delega en `describeApiError` (detalle del backend o su mensaje). Cualquier otro
 * error (red/desconocido) cae a su `message` o a su string. PURO: no toca red ni DOM.
 */
export function reportErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) {
      return "Esta corrida no generó un reporte."
    }
    return describeApiError(err.body, err.message)
  }
  return err instanceof Error ? err.message : String(err)
}

/**
 * Igual que `reportErrorMessage`, pero para la descarga del PDF. El PDF es opt-in (se pide vía
 * `formats`), así que un `ApiError` 404 significa que la corrida existe pero NO generó PDF →
 * mensaje claro y específico. El resto del mapeo es idéntico. PURO: no toca red ni DOM.
 */
export function reportPdfErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) {
      return "Esta corrida no generó un PDF."
    }
    return describeApiError(err.body, err.message)
  }
  return err instanceof Error ? err.message : String(err)
}
