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
import { DEMO_MODE } from "@/lib/demo-runtime"
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

/**
 * Sonda de degradación del schema: si NINGUNA de estas llegara con campos, es que el backend
 * respondió con los dominios opacos y hay que caer al snapshot.
 *
 * NO es la lista de secciones que el formulario edita — eso lo decide `configSectionSchema`
 * preguntándole al schema cargado, no una whitelist. Lo fue hasta que provisiones y survival
 * entraron al formulario, y confundir ambas cosas es lo que las mantuvo fuera: el backend las
 * mandaba expandidas y el front las descartaba.
 */
export const F1_SECTIONS = [
  "data",
  "binning",
  "selection",
  "model",
  "scorecard",
  "calibration",
  "performance",
] as const

/** Una sección de configuración navegable desde el sidebar. */
export interface ConfigSectionDef {
  /** Clave de sección del schema (`json_schema.properties`). */
  key: string
  /** Etiqueta humana, on-brand (sidebar + encabezado). */
  label: string
  /** Subtítulo del encabezado. */
  description: string
}

/**
 * Catálogo de secciones que el formulario ofrece, en orden de pipeline.
 *
 * Vive aquí y no en `App.tsx` para que exista UNA sola lista: estaba duplicada entre el sidebar y
 * la whitelist de `ConfigTab`, y mantener las dos sincronizadas a mano es justo lo que dejó
 * provisiones y survival fuera del formulario mientras el backend ya las mandaba expandidas. El
 * icono NO es parte del catálogo: vive en `App.tsx`, para que este módulo siga siendo lógica pura
 * testeable sin React.
 *
 * Una sección listada aquí cuyo extra no esté instalado llega opaca y `ConfigTab` lo avisa: el
 * catálogo declara la intención, el schema cargado decide lo que se puede pintar.
 */
export const CONFIG_SECTIONS: ConfigSectionDef[] = [
  {
    key: "data",
    label: "Esquema y target",
    description:
      "Cómo se interpreta el dataset cargado: esquema, tipos, target, missing y partición.",
  },
  {
    key: "binning",
    label: "Optimal Binning",
    description: "Binning óptimo (OptBinning): restricciones, monotonía, solver y salida.",
  },
  {
    key: "selection",
    label: "Selección de variables",
    description:
      "Filtros de selección: IV, métricas univariadas, correlación, VIF y estabilidad.",
  },
  {
    key: "model",
    label: "Modelo",
    description: "Ajuste del modelo, inferencia, stepwise y política de signos de beta.",
  },
  {
    key: "scorecard",
    label: "Scorecard",
    description: "Escalado a puntaje: PDO, odds objetivo, rango y publicación.",
  },
  {
    key: "calibration",
    label: "Calibración",
    description: "Calibración de PD: método, ancla y ajuste.",
  },
  {
    key: "performance",
    label: "Performance",
    description: "Métricas de desempeño: columnas, población y deciles.",
  },
  {
    key: "stability",
    label: "Estabilidad",
    description:
      "PSI y CSI del score y de la PD calibrada: umbrales, comparaciones entre particiones y eje temporal.",
  },
  {
    key: "survival",
    label: "Survival — PD lifetime",
    description:
      "Tiempo hasta el incumplimiento: método, grilla temporal, covariables y unidad de la curva.",
  },
  {
    key: "provisioning_cmf",
    label: "Provisiones CMF",
    description:
      "Método estándar de la CMF de Chile (Cap. B-1): matrices, mapeo de PD, exposición y garantías.",
  },
  {
    key: "provisioning_internal",
    label: "Provisiones método interno",
    description:
      "Método interno del banco: grupos homogéneos, PD, LGD y exposición propias de la institución.",
  },
  {
    key: "provisioning_ifrs9",
    label: "Provisiones IFRS 9",
    description:
      "ECL de tres etapas: PD lifetime, LGD, EAD, staging por SICR, escenarios y descuento a la EIR.",
  },
  {
    key: "provisioning",
    label: "Comparación de provisiones",
    description:
      "La regla del máximo del Cap. B-1: qué dos métodos se comparan y a qué nivel de agregación.",
  },
]

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

/**
 * Rama con campos de una sección de dominio, o `null` si llegó opaca (extra no instalado).
 *
 * Una sección expandida es APAGABLE, así que el backend la emite como
 * `anyOf: [<objeto>, {"type": "null"}]` con `default: null` — la misma gramática que Pydantic usa
 * para un `X | None`. Espejo de `rama_objeto` en `core/config/schema.py`, que es donde vive el
 * contrato; aquí se replica porque el `tsconfig` no puede leer Python (mismo motivo que
 * `markers.ts`). `nullable` dice si la sección declara su rama nula, o sea si el formulario puede
 * ofrecer apagarla.
 */
export function configSectionSchema(
  payload: SchemaPayload,
  section: string,
): { schema: JsonSchema; nullable: boolean } | null {
  const raw = (payload.json_schema.properties ?? {})[section]
  if (!raw) return null
  const variants = raw.anyOf ?? raw.oneOf
  if (variants) {
    const branch = variants.find((v) => v.type !== "null")
    const nullable = variants.some((v) => v.type === "null")
    if (!branch || !isRenderableSection(branch)) return null
    return { schema: branch, nullable }
  }
  return isRenderableSection(raw) ? { schema: raw, nullable: false } : null
}

/** ¿El backend expandió las secciones, o llegaron opacas? */
export function f1SectionsRenderable(payload: SchemaPayload): boolean {
  return F1_SECTIONS.some((section) => configSectionSchema(payload, section) !== null)
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
