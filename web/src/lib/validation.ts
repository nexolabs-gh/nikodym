/**
 * Helpers PUROS de validación en vivo (SDD-23 §3.3 / §7): el backend PRODUCE el
 * `config_hash` y los errores (`POST /api/validate`); el front SOLO los indexa por
 * campo y los pinta. CERO lógica de dominio aquí: no se reimplementan rangos, enums
 * ni finitud (§3.3). Lógica pura, testeable con vitest sin React ni DOM (entorno node).
 */

import type { PipelineInfo, ValidationErrorItem } from "@/lib/api"
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
 * Error que **no pertenece a ningún campo**, o `undefined` si no hay (D-ANC-12).
 *
 * 🔴 Un `ConfigError` levantado por el `model_validator` de una sección llega con `loc: []` —no lo
 * emite pydantic sobre un campo, sino el dominio sobre la sección entera—, así que su clave de
 * lookup es la cadena vacía y **ningún `FieldRenderer` la reclama**. El resultado, medido abriendo
 * la pantalla: el formulario decía «Config inválido · 1 error» y el mensaje no aparecía por ningún
 * lado, dejando al usuario con un contador y nada que corregir.
 *
 * No es de un caso: el motor tiene **123 `raise` en validadores de 18 secciones de dominio**, todos
 * con `loc: []`, y varios se arman con dos clics (`binning.solver='cp'`, el par del ancla). El
 * mensaje ya viaja en el `lookup`; lo único que faltaba era mirarlo.
 */
export function unanchoredError(state: ValidationState): string | undefined {
  return state.kind === "invalid" ? state.lookup.get("") : undefined
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

/**
 * Estado de la validación en vivo (SDD-23 §3.3/§7): la verdad la produce el backend
 * (`POST /api/validate`); el front solo transporta el `config_hash` o los errores. Vive
 * aquí (módulo compartido) para que Config, Ejecutar y el sidebar lean el mismo tipo.
 */
export type ValidationState =
  | { kind: "idle" }
  | { kind: "checking" }
  | {
      kind: "valid"
      hash: string
      pipeline: PipelineInfo | null
      /**
       * D-PRO-2, ya resuelto por sección. Opcional a propósito: un backend anterior a la enmienda
       * no lo manda, y `undefined` significa «no se sabe» —el consumidor cae a las columnas del
       * archivo, que es lo que hacía antes—, nunca «ninguna sección produce nada».
       */
      producedColumns?: Record<string, string[]>
    }
  | { kind: "invalid"; count: number; lookup: Map<string, string> }
  | { kind: "unreachable" }

/**
 * Aviso de config inejecutable, o `null` si no hay nada que advertir (enmienda
 * VALIDACION-PIPELINE, D-PIPE-5). PURO: sin React ni DOM.
 *
 * El **encabezado** es copy del front —el idioma del lector— y el **cuerpo** es el mensaje del
 * motor tal cual lo entregó el backend, ya saneado de códigos de marca. El front no traduce ese
 * mensaje ni deduce qué sección hay que encender: el motor es el que sabe (SDD-23 §3.3).
 *
 * Sólo aplica sobre un config VÁLIDO: mientras el config no reconstruye no hay pipeline que
 * resolver, y encimar dos avisos sobre el mismo campo roto sería ruido.
 */
export function pipelineWarning(state: ValidationState): string | null {
  if (state.kind !== "valid") return null
  if (state.pipeline === null || state.pipeline.executable) return null
  return state.pipeline.message
}

/**
 * Gate PURO de la corrida (SDD-23 §8): solo se puede ejecutar con un config **válido**
 * (hay `config_hash`) y un `datasetId` elegido. Devuelve el motivo del bloqueo para
 * pintarlo en texto sobrio. NO valida dominio: la validez ya la produjo el backend en
 * `validation`; aquí solo se combinan los dos prerequisitos. Testeable sin React ni DOM.
 *
 * El motivo distingue el bloqueo TRANSITORIO (el arranque de la sesión aún siembra y valida el
 * preset: `idle`/`checking`) del bloqueo REAL (config inválido / sin backend): desde UX1 el
 * config se siembra solo, así que `idle` ya no es "no configuraste", es "todavía no termina".
 */
export function canRun(
  validation: ValidationState,
  datasetId: string | null,
): { ok: boolean; reason?: string } {
  switch (validation.kind) {
    case "idle":
      return { ok: false, reason: "Preparando la configuración…" }
    case "checking":
      return { ok: false, reason: "Validando la configuración…" }
    case "invalid":
      return { ok: false, reason: "El config tiene errores: revísalo en Configuración" }
    case "unreachable":
      return { ok: false, reason: "Sin backend: no se pudo validar el config" }
  }
  if (datasetId === null || datasetId === "") {
    return { ok: false, reason: "Falta elegir dataset" }
  }
  return { ok: true }
}
