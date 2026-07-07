/**
 * Motor de formulario — LÓGICA PURA (sin React, sin fetch; testeable con fixtures).
 *
 * Implementa el mapeo tipo→widget del SDD-23 §5: dado el schema de un campo del
 * JSON-Schema de `NikodymConfig` (Draft 2020-12), decide qué widget lo edita. La
 * UI **no** reimplementa rangos/enums/finitud (SDD §3.3): a lo sumo usa las cotas
 * del schema como HINTS de UX del widget. La validación autoritativa es del backend.
 *
 * B23.4b cubre los CASOS BASE; los subforms condicionales de uniones discriminadas,
 * el toggle activar/None y el editor JSON real quedan STUB para B23.5.
 */

// ---------------------------------------------------------------------------
// Tipos del JSON-Schema (subset Draft 2020-12) — este módulo es su dueño para
// no arrastrar runtime (fetch/fixture) al motor puro.
// ---------------------------------------------------------------------------

export interface JsonSchema {
  type?: string | string[]
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  const?: unknown
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  multipleOf?: number
  properties?: Record<string, JsonSchema>
  required?: string[]
  items?: JsonSchema
  $ref?: string
  $defs?: Record<string, JsonSchema>
  anyOf?: JsonSchema[]
  oneOf?: JsonSchema[]
  allOf?: JsonSchema[]
  discriminator?: { propertyName: string; mapping?: Record<string, string> }
  additionalProperties?: boolean | JsonSchema
  // Metadatos de presentación (json_schema_extra / ui_*, contrato SDD-05 §5.5)
  ui_widget?: string
  ui_group?: string
  ui_order?: number
  [key: string]: unknown
}

export type Defs = Record<string, JsonSchema>

/** Widgets soportados por el front (mapeo §5). */
export type WidgetKind =
  | "select"
  | "switch"
  | "slider"
  | "number"
  | "text"
  | "textarea"
  | "group"
  | "discriminated"
  | "multiselect"
  | "json"

export interface ResolveContext {
  /** Defs para resolver `$ref` (`#/$defs/<Name>`). */
  defs?: Defs
  /** Si el campo es requerido (hint de UX; no cambia el widget base). */
  required?: boolean
}

/** Umbral de longitud de `description` a partir del cual un string usa textarea. */
export const TEXTAREA_DESCRIPTION_THRESHOLD = 120

/** Aliases de `ui_widget` (json_schema_extra) → WidgetKind. Override del default. */
const UI_WIDGET_ALIASES: Record<string, WidgetKind> = {
  select: "select",
  switch: "switch",
  checkbox: "switch",
  slider: "slider",
  number: "number",
  number_input: "number",
  text: "text",
  input: "text",
  textarea: "textarea",
  multiselect: "multiselect",
  json: "json",
  group: "group",
  accordion: "group",
}

// ---------------------------------------------------------------------------
// Helpers puros
// ---------------------------------------------------------------------------

/** Tipo efectivo de un schema (si `type` es lista, el primero no-null). */
export function schemaType(schema: JsonSchema): string | undefined {
  if (Array.isArray(schema.type)) {
    return schema.type.find((t) => t !== "null") ?? schema.type[0]
  }
  return schema.type
}

function isNullSchema(schema: JsonSchema): boolean {
  return schemaType(schema) === "null"
}

/** Resuelve un `$ref` (`#/$defs/<Name>`) contra `defs`; conserva title/description. */
export function resolveRef(schema: JsonSchema, defs: Defs = {}): JsonSchema {
  if (typeof schema.$ref !== "string") return schema
  const name = schema.$ref.replace(/^#\/\$defs\//, "")
  const target = defs[name]
  if (!target) return schema
  return {
    ...target,
    title: schema.title ?? target.title,
    description: schema.description ?? target.description,
  }
}

/**
 * Desempaqueta `anyOf`/`oneOf` de la forma `[T, null]` (campo opcional) devolviendo
 * `T` con los metadatos externos (title/description/default/ui_*) preservados. Si no
 * es esa forma, devuelve el schema tal cual con `nullable=false`.
 */
export function unwrapNullable(schema: JsonSchema): {
  schema: JsonSchema
  nullable: boolean
} {
  const variants = schema.anyOf ?? schema.oneOf
  if (!variants) return { schema, nullable: false }
  const nonNull = variants.filter((v) => !isNullSchema(v))
  const hasNull = variants.some(isNullSchema)
  if (hasNull && nonNull.length === 1) {
    const base = nonNull[0]
    return {
      schema: {
        ...base,
        title: schema.title ?? base.title,
        description: schema.description ?? base.description,
        default: schema.default ?? base.default,
        ui_widget: schema.ui_widget ?? base.ui_widget,
        ui_group: schema.ui_group ?? base.ui_group,
        ui_order: schema.ui_order ?? base.ui_order,
      },
      nullable: true,
    }
  }
  return { schema, nullable: false }
}

function uiWidgetToKind(widget: unknown): WidgetKind | undefined {
  if (typeof widget !== "string") return undefined
  return UI_WIDGET_ALIASES[widget]
}

/** ¿El schema tiene ambas cotas (min y max), sea inclusiva o exclusiva? */
export function hasBothBounds(schema: JsonSchema): boolean {
  const hasMin =
    schema.minimum !== undefined || schema.exclusiveMinimum !== undefined
  const hasMax =
    schema.maximum !== undefined || schema.exclusiveMaximum !== undefined
  return hasMin && hasMax
}

/** Cotas numéricas del schema como hints del widget (min/max/step). */
export function numericBounds(schema: JsonSchema): {
  min?: number
  max?: number
  step?: number
} {
  const min = schema.minimum ?? schema.exclusiveMinimum
  const max = schema.maximum ?? schema.exclusiveMaximum
  const step =
    schema.multipleOf ??
    (schemaType(schema) === "integer" ? 1 : undefined)
  return { min, max, step }
}

/** Opciones de un enum/const (para select/multiselect). */
export function enumOptions(schema: JsonSchema): unknown[] {
  if (Array.isArray(schema.enum)) return schema.enum
  if (schema.const !== undefined) return [schema.const]
  return []
}

/** Etiqueta del campo (title, o el nombre en su defecto). */
export function fieldLabel(name: string, schema: JsonSchema): string {
  return typeof schema.title === "string" && schema.title.length > 0
    ? schema.title
    : name
}

/**
 * Lista ordenada de campos `[name, schema]` de un objeto (resuelto), ordenados por
 * `ui_order` cuando existe y luego por orden de declaración.
 */
export function orderedFields(objectSchema: JsonSchema): [string, JsonSchema][] {
  const props = objectSchema.properties ?? {}
  const entries = Object.entries(props)
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => {
      const ao = a.entry[1].ui_order
      const bo = b.entry[1].ui_order
      if (ao !== undefined && bo !== undefined) return ao - bo
      if (ao !== undefined) return -1
      if (bo !== undefined) return 1
      return a.index - b.index
    })
    .map(({ entry }) => entry)
}

// ---------------------------------------------------------------------------
// resolveWidget — el corazón del mapeo §5
// ---------------------------------------------------------------------------

/**
 * Decide el widget de un campo según su schema (tabla §5), casos base de B23.4b:
 *
 *  - `enum` / `const`                                  → "select"
 *  - `boolean`                                         → "switch"
 *  - number/integer con min **y** max                  → "slider"
 *  - number/integer sin ambas cotas                    → "number"
 *  - `string`                                          → "text" (o "textarea" si description larga)
 *  - `$ref` / `object` (sub-modelo)                    → "group" (render recursivo)
 *  - `anyOf` con rama `null` (opcional)                → desempaqueta al tipo base y lo resuelve
 *  - `oneOf`/`anyOf` + `discriminator` (unión discr.)  → "discriminated" (STUB en B23.4b)
 *  - array de enum                                     → "multiselect" (STUB)
 *  - no mapeado / exótico                              → "json" (placeholder; editor real en B23.5)
 *
 * `ui_widget` (json_schema_extra) SOBREESCRIBE el default por tipo.
 */
export function resolveWidget(
  field: JsonSchema,
  context: ResolveContext = {},
): WidgetKind {
  const defs = context.defs ?? {}

  // (1) ui_widget del campo original tiene prioridad (antes de resolver $ref).
  const override = uiWidgetToKind(field.ui_widget)
  if (override) return override

  // (2) Resolver $ref para inspeccionar el destino.
  const resolved = resolveRef(field, defs)
  const resolvedOverride = uiWidgetToKind(resolved.ui_widget)
  if (resolvedOverride) return resolvedOverride

  // (3) Unión discriminada (antes de desempaquetar nullable).
  if ((resolved.oneOf || resolved.anyOf) && resolved.discriminator) {
    return "discriminated"
  }

  // (4) Campo opcional `anyOf: [T, null]` → resolver el tipo base.
  const { schema: base } = unwrapNullable(resolved)
  if (base !== resolved) {
    return resolveWidget(base, context)
  }

  // (5) enum / const → select.
  if (Array.isArray(resolved.enum) || resolved.const !== undefined) {
    return "select"
  }

  // (6) Por tipo.
  const type = schemaType(resolved)
  if (type === "boolean") return "switch"
  if (type === "integer" || type === "number") {
    return hasBothBounds(resolved) ? "slider" : "number"
  }
  if (type === "string") {
    const description = resolved.description ?? ""
    return description.length > TEXTAREA_DESCRIPTION_THRESHOLD
      ? "textarea"
      : "text"
  }
  if (type === "object" || resolved.properties) return "group"
  if (type === "array") {
    const items = resolved.items
    if (items && (Array.isArray(items.enum) || items.const !== undefined)) {
      return "multiselect"
    }
    return "json"
  }

  // (7) No mapeado / exótico.
  return "json"
}

// ---------------------------------------------------------------------------
// Unión discriminada (B23.5a §5) — ramas, tag y defaults de variante
// ---------------------------------------------------------------------------

/** Propiedad discriminadora de una unión (`discriminator.propertyName`, o "type"). */
export function discriminatorProperty(schema: JsonSchema): string {
  return schema.discriminator?.propertyName ?? "type"
}

/**
 * Ramas de una unión discriminada, resueltas y etiquetadas por su tag, en el orden
 * de `oneOf`/`anyOf`: `[{ tag, schema }]`. El tag sale de `properties[propName].const`
 * de cada rama (camino robusto), **no** de `discriminator.mapping`: el `mapping`
 * referencia nombres SIN el prefijo de namespace (`RandomSplitConfig`) que no existen
 * en `$defs` (`Data_RandomSplitConfig`) y por tanto no resuelve — el `const` de la rama
 * es la fuente fiable (SDD §5; verificado contra `fixtures/schema.json`).
 */
export function discriminatedBranches(
  schema: JsonSchema,
  defs: Defs = {},
): { tag: string; schema: JsonSchema }[] {
  const propName = discriminatorProperty(schema)
  const branches = schema.oneOf ?? schema.anyOf ?? []
  const out: { tag: string; schema: JsonSchema }[] = []
  for (const branch of branches) {
    const resolved = resolveRef(branch, defs)
    const tag = resolved.properties?.[propName]?.const
    if (typeof tag === "string") out.push({ tag, schema: resolved })
  }
  return out
}

/**
 * Sub-objeto por defecto de una variante (rama de objeto): por cada propiedad con
 * `const` (p.ej. el tag discriminador) o con `default` en el schema, siembra ese valor;
 * los campos sin default se dejan sin sembrar (los pinta vacíos el widget y el backend
 * los exige). Reproduce lo que emite el modelo Pydantic por defecto (SDD §5).
 */
export function variantDefaults(branchSchema: JsonSchema): Record<string, unknown> {
  const props = branchSchema.properties ?? {}
  const out: Record<string, unknown> = {}
  for (const [name, prop] of Object.entries(props)) {
    if (prop.const !== undefined) out[name] = prop.const
    else if ("default" in prop) out[name] = prop.default
  }
  return out
}

/**
 * Valor semilla al ACTIVAR una sección opcional (`X | None`, SDD §5): el `default` del
 * schema si existe y no es null; en su defecto un valor por tipo (objeto→defaults de sus
 * campos, array→[], número→cota inferior o 0, string→primer enum o "", bool→false). El
 * resultado es siempre no-null, para distinguir "activado vacío" de "desactivado" (None).
 */
export function defaultForSchema(schema: JsonSchema, defs: Defs = {}): unknown {
  const resolved = resolveRef(schema, defs)
  if (resolved.default !== undefined && resolved.default !== null) {
    return resolved.default
  }
  const type = schemaType(resolved)
  if (type === "object" || resolved.properties) return variantDefaults(resolved)
  if (type === "array") return []
  if (type === "boolean") return false
  if (type === "integer" || type === "number") {
    return numericBounds(resolved).min ?? 0
  }
  if (type === "string") {
    const options = enumOptions(resolved)
    return options.length > 0 ? options[0] : ""
  }
  return {}
}

// ---------------------------------------------------------------------------
// Multiselect (B23.5a §5) — `tuple[Literal, ...]` / array de enum
// ---------------------------------------------------------------------------

/** Opciones de un multiselect (`array` de `enum`/`const`): el `enum` de sus `items`. */
export function multiselectOptions(schema: JsonSchema): unknown[] {
  return schema.items ? enumOptions(schema.items) : []
}

/**
 * Alterna `option` en el valor de un multiselect y devuelve el array resultante en ORDEN
 * ESTABLE (= el de `options`, no el de marcado). Pura; el widget la invoca en cada
 * check/uncheck. Los valores fuera de `options` se descartan (canónico).
 */
export function toggleMultiselect(
  current: unknown,
  option: unknown,
  checked: boolean,
  options: unknown[],
): unknown[] {
  const selected = new Set(Array.isArray(current) ? current : [])
  if (checked) selected.add(option)
  else selected.delete(option)
  return options.filter((o) => selected.has(o))
}
