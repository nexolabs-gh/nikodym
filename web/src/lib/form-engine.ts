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
  examples?: unknown[]
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
  /** Texto de ayuda HUMANO por campo (tooltip ⓘ); si falta, el front cae en `description`. */
  ui_help?: string
  /**
   * Qué ES el valor de un campo que nombra columnas (D-PRE-3, vocabulario en :type:`ColumnRole`).
   *
   * Va declarado —y no sólo alcanzable por la firma de índice— porque es metadato que **viaja con
   * el campo**, igual que los `ui_*`: quien copie propiedades de un nodo a otro tiene que verlo
   * en la lista. Omitirlo en `unwrapNullable` es exactamente lo que dejaba a
   * `data.schema.unique_keys` en el editor JSON.
   */
  column_role?: string
  /**
   * De qué columna salen las OPCIONES de este campo (D-COL-7): el nombre del campo HERMANO que
   * nombra la columna, no el de la columna.
   *
   * `column_role` dice «mi valor ES un nombre de columna»; esto dice «mi valor es uno de los
   * VALORES de la columna que nombra ese otro campo». Es la forma de `data.partition.strategy`
   * cuando la división ya viene marcada en el archivo: `desarrollo`/`holdout`/`oot` declaran
   * `column_values_from: "partition_col"`, así que sus opciones son los valores observados en la
   * columna que el usuario haya escrito en `partition_col`.
   *
   * Viaja en la lista junto a los `ui_*` y a `column_role` por la misma razón que aquéllos: quien
   * copie propiedades de un nodo a otro tiene que verlo. Omitirlo en `unwrapNullable` es
   * exactamente el defecto que dejó a `data.schema.unique_keys` en el editor JSON.
   */
  column_values_from?: string
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
  /** Lista de sub-objetos: una fila editable por elemento (`data.schema.columns`, reglas…). */
  | "list"
  | "json"
  /** Fontanería del config que el usuario no edita: no se pinta (ver `HIDDEN_WIDGET`). */
  | "hidden"

export interface ResolveContext {
  /** Defs para resolver `$ref` (`#/$defs/<Name>`). */
  defs?: Defs
  /** Si el campo es requerido (hint de UX; no cambia el widget base). */
  required?: boolean
}

/** Umbral de longitud de `description` a partir del cual un string usa textarea. */
export const TEXTAREA_DESCRIPTION_THRESHOLD = 120

/** Widget de un campo marcado `hidden`: el dispatcher no lo pinta y los enumeradores lo omiten. */
export const HIDDEN_WIDGET: WidgetKind = "hidden"

/**
 * Aliases de `ui_widget` (json_schema_extra) → WidgetKind. Override del default.
 *
 * Cubre el vocabulario COMPLETO que emiten los configs de `src/`, y eso lo vigila
 * `tests/unit/test_ui_widget_vocabulary.py`. No es celo: hasta que entró ese gate, de los 20
 * literales que el motor emitía este mapa conocía **cuatro** (`number_input`, `checkbox`,
 * `multiselect`, `slider`). Los demás caían a la resolución por tipo, que acertaba por accidente
 * en unos (`text_input` → text, `selectbox` → select porque traen `enum`) y fallaba callada en
 * otros: `hidden` se renderizaba, y los `dict[str, X]` (`kv_*`, `key_value`) pintaban un fieldset
 * VACÍO, porque son `type: "object"` sin `properties`.
 */
const UI_WIDGET_ALIASES: Record<string, WidgetKind> = {
  select: "select",
  selectbox: "select",
  switch: "switch",
  checkbox: "switch",
  slider: "slider",
  number: "number",
  number_input: "number",
  text: "text",
  text_input: "text",
  input: "text",
  artifact_key: "text",
  textarea: "textarea",
  text_area: "textarea",
  multiselect: "multiselect",
  json: "json",
  group: "group",
  section: "group",
  accordion: "group",
  hidden: HIDDEN_WIDGET,
  // Colecciones y mapas: no hay widget nativo para ellos, y el editor JSON es honesto y usable.
  // Sin este bloque, los `*_list`/`*_tuple` caían a JSON igual (por tipo), pero los `dict[str, X]`
  // resolvían a `group` y pintaban una caja sin un solo campo dentro.
  text_list: "json",
  number_list: "json",
  number_tuple: "json",
  table: "json",
  editable_table: "json",
  key_value: "json",
  kv_text: "json",
  kv_number: "json",
  number_or_select: "json",
  text_or_number: "json",
}

/** ¿Este campo es fontanería del config, que el formulario no debe pintar? */
export function isHiddenField(schema: JsonSchema): boolean {
  return uiWidgetToKind(schema.ui_widget) === HIDDEN_WIDGET
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

/**
 * Clave del `$def` al que apunta un nodo, SIN resolverlo. `undefined` si no apunta a ninguno.
 *
 * Es lo que `resolveRef` descarta al devolver el objetivo, y lo que hace falta para indexar el
 * catálogo de defaults efectivos: sus claves de `$defs` son literalmente las que referencia el
 * `json_schema`. Baja por la rama no nula de una unión `[T, null]`, que es como viaja un submodelo
 * opcional; una unión DISCRIMINADA (varias ramas no nulas) devuelve `undefined` a propósito —ahí la
 * rama la elige el usuario, y la resuelve `discriminatedBranchRef`—.
 */
export function refName(schema: JsonSchema): string | undefined {
  if (typeof schema.$ref === "string") {
    return schema.$ref.replace(/^#\/\$defs\//, "")
  }
  const variants = schema.anyOf ?? schema.oneOf
  if (!variants) return undefined
  const nonNull = variants.filter((v) => !isNullSchema(v))
  if (nonNull.length !== 1) return undefined
  return refName(nonNull[0])
}

/** Clave del `$def` del ELEMENTO de una lista (`items`), sin resolverlo. */
export function itemRefName(schema: JsonSchema, defs: Defs = {}): string | undefined {
  const array = arrayBranch(schema, defs)
  return array?.items ? refName(array.items) : undefined
}

/** Clave del `$def` de la rama `tag` de una unión discriminada, sin resolverla. */
export function discriminatedBranchRef(
  schema: JsonSchema,
  tag: string,
  defs: Defs = {},
): string | undefined {
  const propName = discriminatorProperty(schema)
  for (const branch of schema.oneOf ?? schema.anyOf ?? []) {
    if (resolveRef(branch, defs).properties?.[propName]?.const === tag) {
      return refName(branch)
    }
  }
  return undefined
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
    examples: schema.examples ?? target.examples,
  }
}

/**
 * Desempaqueta `anyOf`/`oneOf` de la forma `[T, null]` (campo opcional) devolviendo
 * `T` con los metadatos externos (title, description, default, los `ui_*` y `column_role`)
 * preservados. Si no es esa forma, devuelve el schema tal cual con `nullable=false`.
 *
 * ⚠️ **Lo que esta función NO copia, el campo lo PIERDE**, y el desempaquetado está en el camino
 * de todo campo opcional: `resolveWidget` recurre sobre la rama desempaquetada (§4) y
 * `NullableField` le pasa `baseSchema` al renderer hijo, que es quien resuelve widget y opciones.
 * `column_role` faltaba en la lista, así que `data.schema.unique_keys` —`tuple[str, ...] | None`
 * con `column_role: "input"` declarado— llegaba al front sin rol y caía al **editor JSON crudo**
 * en vez del multiselect de columnas del dataset. Medido sobre el schema real: son los 4 campos
 * que declaran rol bajo un `X | None` (`unique_keys`, `index_col`, `data_cutoff_col`,
 * `stability.temporal_column`); en los otros tres el rol aún no cambia el widget —son escalares—,
 * pero se propaga igual porque el rol es del campo, no de su forma.
 *
 * El gate en la dirección rol ⇒ widget está en `form-engine.test.ts`, y recorre el schema real.
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
        examples: schema.examples ?? base.examples,
        default: schema.default ?? base.default,
        ui_widget: schema.ui_widget ?? base.ui_widget,
        ui_group: schema.ui_group ?? base.ui_group,
        ui_order: schema.ui_order ?? base.ui_order,
        ui_help: schema.ui_help ?? base.ui_help,
        column_role: schema.column_role ?? base.column_role,
        column_values_from: schema.column_values_from ?? base.column_values_from,
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
 * Texto de ayuda del tooltip ⓘ (contrato B31): el `ui_help` humano curado en el backend, con
 * fallback a la `description` técnica de Pydantic mientras un campo aún no tenga `ui_help`.
 * `undefined` si el campo no trae ninguno de los dos (no se pinta tooltip).
 */
export function fieldHelp(schema: JsonSchema): string | undefined {
  if (typeof schema.ui_help === "string" && schema.ui_help.length > 0) {
    return schema.ui_help
  }
  return typeof schema.description === "string" ? schema.description : undefined
}

/** Formatea un valor de `examples` como hint legible (string tal cual; el resto vía JSON). */
function formatExample(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value)
}

/**
 * Placeholder/hint de un campo de entrada libre (text/number), ayuda en campos del SDD §5:
 * usa los `examples` del schema (Pydantic `Field(examples=[...])`) formateados como sugerencia
 * ("p. ej. …"); si el schema no trae examples, cae en la `description`. `undefined` si no hay
 * ninguno. Puro y sin inventar ejemplos (restricción del goal): solo transporta lo que trae el
 * schema del backend. Hoy los modelos no declaran `examples`, así que el comportamiento efectivo
 * sigue siendo la `description` como placeholder; esto es refuerzo para cuando el usuario borra un
 * campo o empieza de cero, y queda listo si mañana se añaden `examples` al backend.
 */
export function fieldPlaceholder(schema: JsonSchema): string | undefined {
  const examples = Array.isArray(schema.examples) ? schema.examples : []
  if (examples.length > 0) {
    return `p. ej. ${examples.map(formatExample).join(", ")}`
  }
  return typeof schema.description === "string" ? schema.description : undefined
}

/**
 * Lista ordenada de campos `[name, schema]` de un objeto (resuelto), ordenados por
 * `ui_order` cuando existe y luego por orden de declaración.
 *
 * Omite los campos `hidden`. El filtro vive aquí y en `groupedFields` —los dos enumeradores— para
 * que `ConfigSectionForm`, `GroupField` y `DiscriminatedField` lo hereden sin repetirlo.
 */
export function orderedFields(objectSchema: JsonSchema): [string, JsonSchema][] {
  const props = objectSchema.properties ?? {}
  const entries = Object.entries(props).filter(([, schema]) => !isHiddenField(schema))
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

/** Un grupo de campos de una sección (`ui_group`): su título y sus campos ya ordenados. */
export interface FieldGroup {
  /** Título del grupo (`ui_group`), o `null` si sus campos no declaran grupo. */
  group: string | null
  fields: [string, JsonSchema][]
}

/**
 * Agrupa los campos de un objeto por `ui_group` (contrato SDD-05 §5.5) para pintarlos como
 * sub-fieldsets/accordions dentro de su sección.
 *
 * OJO — `ui_order` es LOCAL a cada grupo (cada grupo numera sus campos 1,2,3…), no global a la
 * sección; por eso el orden de los GRUPOS sale del **orden de declaración** (que en el schema
 * refleja el orden de dominio: General → Variables → Restricciones → …), y el orden DENTRO de
 * cada grupo sale de `ui_order` (con la declaración como desempate). Ordenar por `ui_order`
 * global —como hace `orderedFields`— entremezclaría los grupos, así que aquí NO se reutiliza.
 *
 * Los campos sin `ui_group` caen en un grupo `group: null` (consúmelo como "General" o sin
 * encabezado). Puro y testeable con fixtures; la validación autoritativa sigue siendo del backend.
 *
 * Omite los campos `hidden`, igual que `orderedFields`. Un grupo que quede sin campos visibles no
 * se emite: pintaría un encabezado sobre nada.
 */
export function groupedFields(objectSchema: JsonSchema): FieldGroup[] {
  const props = objectSchema.properties ?? {}
  const NO_GROUP = "" // sentinela interno: los `ui_group` reales tienen longitud > 0
  const buckets = new Map<string, { name: string; schema: JsonSchema; index: number }[]>()
  const order: string[] = [] // orden de aparición (declaración) de cada grupo
  let index = 0
  for (const [name, schema] of Object.entries(props)) {
    if (isHiddenField(schema)) continue
    const raw = schema.ui_group
    const key = typeof raw === "string" && raw.length > 0 ? raw : NO_GROUP
    let bucket = buckets.get(key)
    if (!bucket) {
      bucket = []
      buckets.set(key, bucket)
      order.push(key)
    }
    bucket.push({ name, schema, index })
    index += 1
  }
  return order.map((key) => ({
    group: key === NO_GROUP ? null : key,
    fields: buckets
      .get(key)!
      .slice()
      .sort((a, b) => {
        const ao = a.schema.ui_order
        const bo = b.schema.ui_order
        if (ao !== undefined && bo !== undefined) return ao - bo || a.index - b.index
        if (ao !== undefined) return -1
        if (bo !== undefined) return 1
        return a.index - b.index
      })
      .map(({ name, schema }): [string, JsonSchema] => [name, schema]),
  }))
}

/**
 * ¿El título del grupo dice ya lo mismo que su único campo? Entonces el campo no debe repetirlo.
 *
 * Ocurre cuando un sub-modelo declara su `ui_group` con el mismo nombre que su `title` —
 * «Documento», «HTML», «PDF», «Word», «Secciones» en la sección Informe—: el accordion pinta el
 * título del grupo y el `fieldset` de dentro volvía a pintarlo, así que se leía «Documento /
 * Documento». Sólo aplica con UN campo en el grupo: con dos o más, el título del grupo es un
 * paraguas legítimo y cada campo necesita el suyo.
 *
 * Vive aquí y no en el JSX porque vitest corre sin DOM: en el componente no tendría test.
 */
export function grupoTitulaASuUnicoCampo(group: FieldGroup): boolean {
  if (group.group === null || group.fields.length !== 1) return false
  const [name, schema] = group.fields[0]
  return fieldLabel(name, schema) === group.group
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
  if (override === HIDDEN_WIDGET) return HIDDEN_WIDGET

  // (1-bis) Una lista de SUB-OBJETOS se edita fila a fila, y eso gana sobre el alias declarado:
  // ninguno de los que emite el motor describe esa forma, y los dos que lo intentan fallaban en
  // direcciones opuestas —`table` (`scorecard.point_overrides`) caía al editor JSON, y `section`
  // (`binning.variable_overrides`) resolvía a `group`, que sobre un array no encuentra
  // `properties` y pintaba un fieldset con «Sin campos.»—. `hidden` sí sigue mandando: es la
  // única decisión que dice "no pintes esto", y un widget no puede sobreescribirla.
  if (isObjectList(field, defs)) return "list"
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
    if (isObjectList(resolved, defs)) return "list"
    // Una lista de NOMBRES DE COLUMNA no puede traer `enum` —sus valores dependen del archivo que
    // cargue el usuario, no del schema—, pero es tan elegible como un enum: sus opciones salen del
    // dataset. Sin esta rama, `data.schema.unique_keys` (que declara el rol pero no `ui_widget`)
    // caía al editor JSON aunque el front tuviera las columnas a mano.
    if (columnRole(field, defs) !== undefined) return "multiselect"
    // Una lista de VALORES DE UNA COLUMNA tampoco puede traer `enum`, y por el mismo motivo: sus
    // opciones dependen del archivo. Sin esta rama, los tres campos de la división ya marcada
    // (`desarrollo`/`holdout`/`oot`) caían al editor JSON y obligaban a teclear `["DEV"]` a mano.
    if (columnValuesFrom(field, defs) !== undefined) return "multiselect"
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
// Listas de sub-objetos — una fila editable por elemento
// ---------------------------------------------------------------------------

/**
 * Schema del ELEMENTO de una lista, resuelto; `undefined` si el campo no es una lista.
 *
 * Mira también las ramas de una unión, por la misma razón que `columnRole`: los campos que
 * importan suelen viajar como `X | None` o `tuple[...] | Literal[...]`.
 */
export function itemSchema(
  schema: JsonSchema,
  defs: Defs = {},
): JsonSchema | undefined {
  const array = arrayBranch(schema, defs)
  if (!array?.items) return undefined
  return resolveRef(array.items, defs)
}

/**
 * ¿Es una lista cuyos elementos son sub-objetos con campos propios?
 *
 * Es la pregunta que decide entre «una fila por elemento» y el editor JSON. Exige `properties`
 * de verdad: un `dict[str, X]` es `type: "object"` SIN properties y no tiene formulario que
 * pintar —de ahí que siga yendo al editor JSON, que para ese caso es honesto—.
 */
export function isObjectList(schema: JsonSchema, defs: Defs = {}): boolean {
  const item = itemSchema(schema, defs)
  if (!item) return false
  return Object.keys(item.properties ?? {}).length > 0
}

/** Los elementos actuales de una lista (array vacío si el valor no es un array). */
export function listItems(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/**
 * Devuelve la lista con un elemento nuevo al final, sembrado con los defaults de su schema
 * (`variantDefaults` vía `defaultForSchema`), para que la fila nazca con lo que el modelo de
 * Pydantic pondría y el usuario sólo rellene lo que le falta.
 */
export function appendListItem(
  value: unknown,
  item: JsonSchema,
  defs: Defs = {},
): unknown[] {
  return [...listItems(value), defaultForSchema(item, defs)]
}

/** Devuelve la lista sin el elemento `index` (sin cambios si el índice no existe). */
export function removeListItem(value: unknown, index: number): unknown[] {
  const items = listItems(value)
  if (index < 0 || index >= items.length) return items
  return [...items.slice(0, index), ...items.slice(index + 1)]
}

/**
 * Mueve el elemento `index` `delta` posiciones (−1 arriba, +1 abajo). Sin cambios si el
 * movimiento sale de la lista: el orden importa —`data.schema.columns` lo compara `ordered`— y
 * un botón que no hace nada es preferible a uno que reordena a lo loco en el borde.
 */
export function moveListItem(
  value: unknown,
  index: number,
  delta: number,
): unknown[] {
  const items = listItems(value)
  const destino = index + delta
  if (index < 0 || index >= items.length) return items
  if (destino < 0 || destino >= items.length) return items
  const copia = [...items]
  const [movido] = copia.splice(index, 1)
  copia.splice(destino, 0, movido)
  return copia
}

/**
 * Etiqueta de una fila: el valor de su campo más identificatorio, para no leer «Elemento 3» sobre
 * algo que ya se llama «DEBTINC». Se prefiere `name`, luego `col`, luego `variable`, y el primer
 * string no vacío como último recurso. `null` si la fila no tiene ninguno (el llamador cae al
 * ordinal).
 */
export function listItemLabel(item: unknown): string | null {
  if (!item || typeof item !== "object" || Array.isArray(item)) return null
  const record = item as Record<string, unknown>
  for (const clave of ["name", "col", "variable", "feature", "column"]) {
    const valor = record[clave]
    if (typeof valor === "string" && valor.length > 0) return valor
  }
  for (const valor of Object.values(record)) {
    if (typeof valor === "string" && valor.length > 0) return valor
  }
  return null
}

// ---------------------------------------------------------------------------
// Multiselect (B23.5a §5) — `tuple[Literal, ...]` / array de enum
// ---------------------------------------------------------------------------

/**
 * Vocabulario `column_role` que el motor declara en el propio `Field` (D-PRE-3, el mismo que
 * consume el preflight): dice qué ES el valor de un campo que nombra columnas.
 *
 *  - `input`        — una columna del DATASET que el usuario carga. Su lista de opciones existe
 *                     antes de correr nada: la trae `POST /api/upload` / `GET /api/datasets`.
 *  - `derived`      — una variable que PRODUCE un paso anterior (p.ej. las WoE de binning). No
 *                     hay lista cerrada antes de la corrida, así que se edita libre.
 *  - `index`        — el índice, que por definición no está entre las columnas.
 *  - `not_a_column` — el nombre engaña pero no refiere a ninguna columna.
 */
export type ColumnRole = "input" | "derived" | "index" | "not_a_column"

/** Contexto de DATOS del formulario (no del schema): lo que el motor puro no puede deducir solo. */
export interface FieldDataContext {
  /** Columnas del dataset activo. `undefined` = todavía no hay dataset cargado. */
  datasetColumns?: string[]
  /**
   * Valores ofrecibles por columna del dataset activo (D-COL-7), indexado por NOMBRE de columna.
   *
   * Es lo que consume un campo con `column_values_from`. Una columna ausente del mapa, o presente
   * con lista vacía, significa **«no se midió»** —demasiados valores distintos, o dataset del
   * catálogo aún sin materializar—, nunca «esa columna no tiene valores»: el consumidor cae a
   * entrada libre, que es el comportamiento de siempre.
   */
  datasetColumnValues?: Record<string, string[]>
  /**
   * Valor actual de los campos HERMANOS del que se está resolviendo (el objeto que lo contiene).
   *
   * Existe sólo por `column_values_from`, que es la primera anotación del schema que apunta a otro
   * campo en vez de describirse a sí misma: sin los hermanos a mano no hay forma de saber QUÉ
   * columna nombró el usuario. `undefined` = el llamador no lo aportó ⇒ sin opciones, entrada
   * libre.
   */
  siblingValues?: Record<string, unknown>
}

/** Ramas no-`null` de un campo (`anyOf`/`oneOf`), resueltas; el propio campo si no es unión. */
function branchesOf(schema: JsonSchema, defs: Defs = {}): JsonSchema[] {
  const variants = schema.anyOf ?? schema.oneOf
  if (!variants) return [resolveRef(schema, defs)]
  return variants.filter((v) => !isNullSchema(v)).map((v) => resolveRef(v, defs))
}

/**
 * `column_role` declarado por el campo (o por alguna de sus ramas). `undefined` si no lo declara.
 *
 * Se mira TAMBIÉN en las ramas porque los campos más importantes son uniones: `feature_columns`
 * es `tuple[str, ...] | Literal["*"]`, y ahí el rol viaja en el campo, no en la rama de array.
 */
export function columnRole(
  schema: JsonSchema,
  defs: Defs = {},
): ColumnRole | undefined {
  const candidates = [schema, ...branchesOf(schema, defs)]
  for (const candidate of candidates) {
    const role = candidate.column_role
    if (
      role === "input" ||
      role === "derived" ||
      role === "index" ||
      role === "not_a_column"
    ) {
      return role
    }
  }
  return undefined
}

/**
 * `column_values_from` declarado por el campo (o por alguna de sus ramas): el NOMBRE DEL CAMPO
 * hermano que nombra la columna de la que salen las opciones. `undefined` si no lo declara.
 *
 * Se mira también en las ramas por la misma razón que :func:`columnRole`: un campo opcional viaja
 * como `anyOf: [T, null]` y la anotación puede estar en cualquiera de los dos lados.
 *
 * ⚠️ Devuelve el nombre del CAMPO, no el de la columna. Resolverlo a una columna exige el valor
 * actual de ese hermano, que es dato del formulario y no del schema.
 */
export function columnValuesFrom(
  schema: JsonSchema,
  defs: Defs = {},
): string | undefined {
  const candidates = [schema, ...branchesOf(schema, defs)]
  for (const candidate of candidates) {
    const from = candidate.column_values_from
    if (typeof from === "string" && from !== "") return from
  }
  return undefined
}

/** La rama `array` de un campo (o el campo mismo si ya lo es); `undefined` si no tiene ninguna. */
export function arrayBranch(
  schema: JsonSchema,
  defs: Defs = {},
): JsonSchema | undefined {
  return branchesOf(schema, defs).find((b) => schemaType(b) === "array")
}

/** Comodín «todas las variables» del config (`Literal["*"]`). */
export const WILDCARD = "*"

/**
 * ¿El campo acepta el comodín `"*"` («todas las variables») además de una lista explícita?
 *
 * Es la forma de `binning.feature_columns` y `selection.feature_columns`
 * (`tuple[str, ...] | Literal["*"]`): sin esto el widget sólo sabría ofrecer la lista y no habría
 * manera de volver al default del preset, que es justamente `"*"`.
 */
export function acceptsWildcard(schema: JsonSchema, defs: Defs = {}): boolean {
  return branchesOf(schema, defs).some(
    (b) => b.const === WILDCARD || (Array.isArray(b.enum) && b.enum.includes(WILDCARD)),
  )
}

/**
 * Opciones de un multiselect. Tres orígenes, en este orden:
 *
 *  1. El **schema**, cuando la lista es cerrada (`enum`/`const` de los `items`).
 *  2. Las **columnas** del dataset, cuando el campo declara `column_role: "input"` — sus valores
 *     son nombres de columna, que ningún `enum` puede conocer porque dependen del archivo que
 *     cargue el usuario.
 *  3. Los **valores de UNA columna**, cuando el campo declara `column_values_from` — la columna la
 *     nombra el campo hermano que esa anotación apunta, así que hace falta su valor ACTUAL.
 *
 * Cualquier otro caso devuelve `[]`, que NO significa «no hay nada que elegir» sino «no hay lista
 * cerrada»: el widget cae entonces a entrada libre. Confundir ambos es lo que hacía que
 * `feature_columns` pintara «Sin opciones.» con doce variables dentro.
 *
 * En el caso 3 el `[]` es además el estado NORMAL de arranque —el hermano todavía en blanco, o un
 * dataset del catálogo sin materializar—, y por eso no puede degradar a nada bloqueante.
 */
export function multiselectOptions(
  schema: JsonSchema,
  context: FieldDataContext = {},
  defs: Defs = {},
): unknown[] {
  const array = arrayBranch(schema, defs) ?? schema
  const fromSchema = array.items ? enumOptions(resolveRef(array.items, defs)) : []
  if (fromSchema.length > 0) return fromSchema
  if (columnRole(schema, defs) === "input") return context.datasetColumns ?? []
  const from = columnValuesFrom(schema, defs)
  if (from !== undefined) {
    const columna = context.siblingValues?.[from]
    // El hermano en blanco, ausente o mal tipado ⇒ no hay columna que consultar. No es un error:
    // es el orden natural de llenado (primero se dice qué columna marca la muestra, después qué
    // valores de esa columna forman cada conjunto).
    if (typeof columna !== "string" || columna === "") return []
    return context.datasetColumnValues?.[columna] ?? []
  }
  return []
}

/**
 * ¿La lista de opciones es CERRADA (el schema las enumera) o abierta (nombres de columna, o
 * valores de una columna, que el usuario puede escribir aunque no salgan en la lista ofrecida)?
 * Decide si el widget ofrece además un campo para añadir un valor a mano.
 *
 * ⚠️ Sólo un `enum` del schema cierra una lista, y por eso `column_values_from` NO la cierra: lo
 * que el dataset publica son los valores **más frecuentes** de la columna (top-20, y vacío si la
 * columna tiene demasiados distintos), no su dominio. Tratarlos como lista cerrada dejaría sin
 * forma de declarar un valor real que no entró en el recorte.
 */
export function hasClosedOptions(schema: JsonSchema, defs: Defs = {}): boolean {
  const array = arrayBranch(schema, defs) ?? schema
  return array.items ? enumOptions(resolveRef(array.items, defs)).length > 0 : false
}

/**
 * ¿Las opciones de este multiselect SALEN del dataset cargado?
 *
 * Es la única condición que autoriza a decirle al usuario que un valor suyo **no está en el
 * dataset**: hay listas de strings que no nombran columnas —`report.sections.required_sections`
 * nombra secciones del informe— y ésas no traen `enum` ni `column_role`, así que se quedan sin
 * opciones y todos sus valores parecen «ausentes». Marcarlos pintaba un config de fábrica,
 * perfectamente válido, con etiquetas rojas diciendo una falsedad.
 *
 * Un `enum` manda sobre el rol (misma precedencia que :func:`multiselectOptions`): si el schema
 * enumera los valores, la lista es cerrada y el dataset no tiene nada que decir.
 *
 * ⚠️ Un campo con `column_values_from` responde que **no**, aunque sus opciones también salgan del
 * dataset, y la diferencia es de VERDAD, no de origen: de las columnas se publican todas, así que
 * una que falte falta de verdad; de los valores de una columna se publican sólo los más
 * frecuentes, así que uno que falte puede estar perfectamente en el archivo. Marcarlo «no está en
 * el dataset» sería exactamente la falsedad contra la que se escribió esta función.
 */
export function optionsFromDataset(schema: JsonSchema, defs: Defs = {}): boolean {
  if (hasClosedOptions(schema, defs)) return false
  if (columnValuesFrom(schema, defs) !== undefined) return false
  return columnRole(schema, defs) === "input"
}

/**
 * Alterna `option` en el valor de un multiselect y devuelve el array resultante en ORDEN
 * ESTABLE (= el de `options`, no el de marcado). Pura; el widget la invoca en cada check/uncheck.
 *
 * ⚠️ Los valores seleccionados que NO están en `options` se CONSERVAN, al final y en su orden.
 * Descartarlos —lo que se hacía antes— borra en silencio el trabajo del usuario en cuanto las
 * opciones vienen del dataset y no del schema: basta cambiar de archivo, o cargar un config cuyas
 * columnas aún no se han subido, para que el valor se vacíe solo. Que un valor no esté entre las
 * opciones es exactamente lo que el preflight tiene que poder señalar; el formulario no debe
 * taparlo borrándolo.
 */
export function toggleMultiselect(
  current: unknown,
  option: unknown,
  checked: boolean,
  options: unknown[],
): unknown[] {
  const previous = Array.isArray(current) ? current : []
  const selected = new Set(previous)
  if (checked) selected.add(option)
  else selected.delete(option)
  const known = options.filter((o) => selected.has(o))
  const unknown = previous.filter((v) => selected.has(v) && !options.includes(v))
  return [...known, ...unknown]
}
