/**
 * Carga del JSON-Schema de `NikodymConfig` para el motor de formulario.
 *
 * En runtime hace fetch real a `GET /api/schema` (SDD-23 §4.2). Desde **B23.4c** el backend
 * ya devuelve el schema **completo** (materializa los dominios instalados vía
 * `build_full_json_schema`), así que las secciones F1 llegan expandidas y `loadSchema` usa la
 * rama "backend". El **snapshot** bundleado (`fixtures/schema.json`) queda como fallback
 * offline (backend caído) y como respaldo defensivo si, por lo que sea, una sección F1 llegara
 * sin expandir (`fixture-opaque`, hoy inesperado). Nunca crashea: degrada a fixture con un aviso.
 */

import { API_BASE } from "@/lib/api"
import { DEMO_MODE } from "@/lib/demo"
import type { JsonSchema } from "@/lib/form-engine"
import fixtureSchema from "@/fixtures/schema.json"

/** Respuesta de `GET /api/schema`. */
export interface SchemaPayload {
  json_schema: JsonSchema
  defaults: Record<string, unknown>
  section_order: string[]
}

/** Snapshot local bundleado (schema compuesto con secciones F1 expandidas). */
export const FIXTURE_SCHEMA = fixtureSchema as unknown as SchemaPayload

/** De dónde salió el schema efectivamente usado por el form. */
export type SchemaSource = "backend" | "fixture-opaque" | "fixture-offline"

export interface LoadedSchema {
  payload: SchemaPayload
  source: SchemaSource
  /** Mensaje del fallo de red, si aplica. */
  error?: string
}

/** Secciones del flujo F1 que el form de B23.4b renderiza. */
export const F1_SECTIONS = [
  "data",
  "binning",
  "selection",
  "model",
  "scorecard",
  "calibration",
  "performance",
] as const

/** ¿El schema de una sección es renderable (tiene campos), no opaco? */
export function isRenderableSection(schema: JsonSchema | undefined): boolean {
  if (!schema) return false
  return (
    typeof schema.$ref === "string" ||
    schema.properties !== undefined ||
    schema.type === "object" ||
    schema.oneOf !== undefined ||
    schema.anyOf !== undefined
  )
}

/** ¿El backend expandió las secciones F1, o llegaron opacas? */
export function f1SectionsRenderable(payload: SchemaPayload): boolean {
  const props = payload.json_schema.properties ?? {}
  return F1_SECTIONS.some((section) => isRenderableSection(props[section]))
}

/** Fetch crudo de `GET /api/schema` (lanza en error de red/HTTP). */
export async function fetchSchema(): Promise<SchemaPayload> {
  const res = await fetch(`${API_BASE}/api/schema`)
  if (!res.ok) throw new Error(`HTTP ${res.status} al pedir /api/schema`)
  return (await res.json()) as SchemaPayload
}

/**
 * Carga el schema para el form: intenta el backend (rama normal desde B23.4c, que ya expande
 * las secciones F1); si falla la red usa el snapshot offline; si —caso defensivo— el backend
 * respondiera con las secciones F1 sin expandir, cae al snapshot (que sí las trae expandidas).
 * Siempre devuelve un payload usable + la fuente.
 */
export async function loadSchema(): Promise<LoadedSchema> {
  // Modo demo: el snapshot bundleado ya trae las secciones F1 expandidas; se sirve como
  // fuente "backend" para que la UI se vea en vivo (no como el estado degradado offline).
  if (DEMO_MODE) return { payload: FIXTURE_SCHEMA, source: "backend" }
  try {
    const live = await fetchSchema()
    if (f1SectionsRenderable(live)) return { payload: live, source: "backend" }
    return { payload: FIXTURE_SCHEMA, source: "fixture-opaque" }
  } catch (err) {
    return {
      payload: FIXTURE_SCHEMA,
      source: "fixture-offline",
      error: err instanceof Error ? err.message : String(err),
    }
  }
}
