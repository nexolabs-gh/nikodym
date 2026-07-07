/**
 * Helpers PUROS de validación en vivo (SDD-23 §3.3 / §7): el backend PRODUCE el
 * `config_hash` y los errores (`POST /api/validate`); el front SOLO los indexa por
 * campo y los pinta. CERO lógica de dominio aquí: no se reimplementan rangos, enums
 * ni finitud (§3.3). Lógica pura, testeable con vitest sin React ni DOM (entorno node).
 */

import type { ValidationErrorItem } from "@/lib/api"
import type { Path } from "@/lib/config-store"

/**
 * Clave estable de un `loc`/`path` para el lookup de errores: los segmentos unidos por
 * `"."`. `loc` (Pydantic `ValidationError.errors()`) y `path` (árbol del form) comparten
 * convención —nombres de campo en orden, índices numéricos de listas—, así que ambos
 * producen la misma clave y el matcheo loc↔path es una igualdad de strings.
 */
export function pathKey(segments: readonly (string | number)[]): string {
  return segments.join(".")
}

/**
 * Arma el lookup `loc→msg` desde los `errors` de `/api/validate`. Indexa por
 * `pathKey(loc)` para que cada `FieldRenderer` recupere su mensaje por `path`. Si varios
 * errores caen en el mismo `loc`, se concatenan en el orden que los emite el backend (un
 * campo puede violar más de una restricción). No interpreta el mensaje: lo transporta.
 */
export function buildErrorLookup(
  errors: readonly ValidationErrorItem[],
): Map<string, string> {
  const lookup = new Map<string, string>()
  for (const error of errors) {
    const key = pathKey(error.loc)
    const previous = lookup.get(key)
    lookup.set(key, previous ? `${previous} · ${error.msg}` : error.msg)
  }
  return lookup
}

/** Mensaje de error del campo en `path`, o `undefined` si no hay (lookup ausente incluido). */
export function errorAtPath(
  lookup: Map<string, string> | undefined,
  path: Path,
): string | undefined {
  return lookup?.get(pathKey(path))
}

/**
 * Extrae un mensaje legible del cuerpo de un `ApiError` (422 de los endpoints YAML): FastAPI
 * envuelve el detalle en `{detail}`, que puede ser un string (mensaje del motor, p.ej. en
 * `config/from-yaml`) o la lista `[{loc,msg,type}]` de validación (p.ej. `config/to-yaml`). El
 * front SOLO lo pinta (§3.3). PURO: no toca red ni DOM; cae a `fallback` si no reconoce la forma.
 */
export function describeApiError(body: unknown, fallback: string): string {
  const detail = isRecord(body) ? body.detail : undefined
  if (typeof detail === "string" && detail.trim() !== "") return detail
  if (Array.isArray(detail)) {
    const lines = detail
      .filter(isRecord)
      .map((item) => {
        const loc = Array.isArray(item.loc)
          ? pathKey(item.loc as (string | number)[])
          : ""
        const msg = typeof item.msg === "string" ? item.msg : ""
        return loc ? `${loc}: ${msg}` : msg
      })
      .filter((line) => line !== "")
    if (lines.length > 0) return lines.join("; ")
  }
  return fallback
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
