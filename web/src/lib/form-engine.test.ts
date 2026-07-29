import { describe, expect, it } from "vitest"

import fixtureSchema from "@/fixtures/schema.json"
import type { SchemaPayload } from "@/lib/schema"

import {
  type Defs,
  type JsonSchema,
  acceptsWildcard,
  appendListItem,
  columnRole,
  defaultForSchema,
  discriminatedBranches,
  discriminatorProperty,
  enumOptions,
  fieldHelp,
  fieldLabel,
  fieldPlaceholder,
  groupedFields,
  hasBothBounds,
  hasClosedOptions,
  isHiddenField,
  isObjectList,
  itemSchema,
  listItemLabel,
  moveListItem,
  multiselectOptions,
  numericBounds,
  orderedFields,
  removeListItem,
  resolveRef,
  resolveWidget,
  schemaType,
  toggleMultiselect,
  unwrapNullable,
  variantDefaults,
} from "./form-engine"

// Réplica del shape real de una unión discriminada (SDD §5, fixtures/schema.json):
// el `discriminator.mapping` usa nombres SIN prefijo de namespace ("RandomSplitConfig")
// que NO existen en `$defs` (prefijados "Data_RandomSplitConfig"); las ramas se
// resuelven por el `const` del tag, no por el mapping.
const PARTITION_DEFS: Defs = {
  Data_RandomSplitConfig: {
    type: "object",
    title: "Partición aleatoria",
    properties: {
      type: { const: "random", default: "random", type: "string" },
      dev_fraction: { type: "number", default: 0.7 },
      holdout_fraction: { type: "number", default: 0.15 },
      stratify_by: { type: "string", default: null },
    },
    required: ["type"],
  },
  Data_TemporalSplitConfig: {
    type: "object",
    title: "Partición temporal",
    properties: {
      type: { const: "temporal", default: "temporal", type: "string" },
      date_col: { type: "string", default: null },
      holdout_fraction: { type: "number", default: 0.2 },
    },
    required: ["type", "date_col"],
  },
}

const PARTITION_UNION: JsonSchema = {
  title: "Estrategia de partición",
  discriminator: {
    propertyName: "type",
    // Nombres SIN prefijo: no resuelven contra PARTITION_DEFS (a propósito).
    mapping: {
      random: "#/$defs/RandomSplitConfig",
      temporal: "#/$defs/TemporalSplitConfig",
    },
  },
  oneOf: [
    { $ref: "#/$defs/Data_TemporalSplitConfig" },
    { $ref: "#/$defs/Data_RandomSplitConfig" },
  ],
}

describe("resolveWidget — tabla §5 (casos base)", () => {
  it("enum → select", () => {
    expect(resolveWidget({ type: "string", enum: ["logit", "glm"] })).toBe(
      "select",
    )
  })

  it("const → select", () => {
    expect(resolveWidget({ type: "string", const: "standard" })).toBe("select")
  })

  it("boolean → switch", () => {
    expect(resolveWidget({ type: "boolean" })).toBe("switch")
  })

  it("number con minimum Y maximum → slider", () => {
    expect(resolveWidget({ type: "number", minimum: 0, maximum: 1 })).toBe(
      "slider",
    )
  })

  it("integer con ambas cotas → slider", () => {
    expect(resolveWidget({ type: "integer", minimum: 2, maximum: 10 })).toBe(
      "slider",
    )
  })

  it("number con cotas exclusivas (gt/lt) → slider", () => {
    expect(
      resolveWidget({
        type: "number",
        exclusiveMinimum: 0,
        exclusiveMaximum: 1,
      }),
    ).toBe("slider")
  })

  it("number con solo minimum → number", () => {
    expect(resolveWidget({ type: "number", exclusiveMinimum: 0 })).toBe(
      "number",
    )
  })

  it("number con solo maximum → number", () => {
    expect(resolveWidget({ type: "number", maximum: 100 })).toBe("number")
  })

  it("number sin cotas → number", () => {
    expect(resolveWidget({ type: "number" })).toBe("number")
  })

  it("string corto → text", () => {
    expect(resolveWidget({ type: "string", description: "Nombre" })).toBe("text")
  })

  it("string con description larga → textarea", () => {
    const long = "x".repeat(200)
    expect(resolveWidget({ type: "string", description: long })).toBe("textarea")
  })

  it("$ref (sub-modelo) → group", () => {
    const defs: Defs = {
      LoadConfig: { type: "object", properties: { source: { type: "string" } } },
    }
    expect(resolveWidget({ $ref: "#/$defs/LoadConfig" }, { defs })).toBe("group")
  })

  it("object con properties → group", () => {
    expect(
      resolveWidget({ type: "object", properties: { a: { type: "string" } } }),
    ).toBe("group")
  })

  it("anyOf [T, null] (opcional) → resuelve el tipo base", () => {
    // number sin cotas bajo null → number
    expect(
      resolveWidget({ anyOf: [{ type: "number" }, { type: "null" }] }),
    ).toBe("number")
    // number con ambas cotas bajo null → slider
    expect(
      resolveWidget({
        anyOf: [
          { type: "number", exclusiveMinimum: 0, exclusiveMaximum: 1 },
          { type: "null" },
        ],
      }),
    ).toBe("slider")
  })

  it("oneOf + discriminator → discriminated (stub)", () => {
    const field: JsonSchema = {
      oneOf: [{ $ref: "#/$defs/Logit" }, { $ref: "#/$defs/XGB" }],
      discriminator: { propertyName: "type" },
    }
    expect(resolveWidget(field)).toBe("discriminated")
  })

  it("array de enum → multiselect", () => {
    expect(
      resolveWidget({ type: "array", items: { enum: ["a", "b", "c"] } }),
    ).toBe("multiselect")
  })

  it("array de string → json (stub)", () => {
    expect(resolveWidget({ type: "array", items: { type: "string" } })).toBe(
      "json",
    )
  })

  it("tipo no mapeado / vacío → json", () => {
    expect(resolveWidget({})).toBe("json")
  })
})

describe("resolveWidget — override por ui_widget", () => {
  it("ui_widget=checkbox sobre boolean → switch", () => {
    expect(resolveWidget({ type: "boolean", ui_widget: "checkbox" })).toBe(
      "switch",
    )
  })

  it("ui_widget=number_input sobre number con cotas → number (override gana al slider)", () => {
    expect(
      resolveWidget({
        type: "number",
        minimum: 0,
        maximum: 1,
        ui_widget: "number_input",
      }),
    ).toBe("number")
  })

  it("ui_widget=textarea sobre string corto → textarea", () => {
    expect(
      resolveWidget({ type: "string", ui_widget: "textarea" }),
    ).toBe("textarea")
  })

  it("ui_widget desconocido → cae al default por tipo", () => {
    expect(resolveWidget({ type: "boolean", ui_widget: "quantum" })).toBe(
      "switch",
    )
  })

  it("ui_widget=hidden → hidden, aunque el tipo diga otra cosa", () => {
    // `schema_version` es un string: sin este alias resolvía a `text` y el usuario veía —y podía
    // romper— la fontanería del config.
    expect(resolveWidget({ type: "string", ui_widget: "hidden" })).toBe("hidden")
    expect(isHiddenField({ type: "string", ui_widget: "hidden" })).toBe(true)
    expect(isHiddenField({ type: "string" })).toBe(false)
  })

  it("un dict[str, X] va al editor JSON, no a un fieldset vacío", () => {
    // `kv_text`/`key_value` son `type: "object"` SIN `properties`: resolvían a `group` y pintaban
    // una caja con leyenda y ni un campo dentro.
    const mapa: JsonSchema = {
      type: "object",
      additionalProperties: { type: "string" },
      ui_widget: "kv_text",
    }
    expect(resolveWidget(mapa)).toBe("json")
  })

  it("los alias del motor resuelven a su widget (no por accidente del tipo)", () => {
    expect(resolveWidget({ type: "string", ui_widget: "text_input" })).toBe("text")
    expect(resolveWidget({ type: "string", ui_widget: "selectbox", enum: ["a"] })).toBe("select")
    expect(resolveWidget({ type: "array", ui_widget: "number_list" })).toBe("json")
    expect(resolveWidget({ type: "object", ui_widget: "section" })).toBe("group")
  })
})

describe("resolveRef", () => {
  it("resuelve #/$defs/<Name> contra defs y preserva title/description", () => {
    const defs: Defs = {
      Foo: { type: "object", title: "Interno", properties: {} },
    }
    const out = resolveRef(
      { $ref: "#/$defs/Foo", title: "Externo", description: "d" },
      defs,
    )
    expect(out.type).toBe("object")
    expect(out.title).toBe("Externo")
    expect(out.description).toBe("d")
  })

  it("ref no encontrado → devuelve el schema tal cual", () => {
    const out = resolveRef({ $ref: "#/$defs/NoExiste" }, {})
    expect(out.$ref).toBe("#/$defs/NoExiste")
  })

  it("sin $ref → identidad", () => {
    const schema: JsonSchema = { type: "string" }
    expect(resolveRef(schema, {})).toBe(schema)
  })
})

describe("unwrapNullable", () => {
  it("[T, null] → T con nullable=true", () => {
    const { schema, nullable } = unwrapNullable({
      anyOf: [{ type: "number", minimum: 0 }, { type: "null" }],
      title: "Opcional",
    })
    expect(nullable).toBe(true)
    expect(schemaType(schema)).toBe("number")
    expect(schema.title).toBe("Opcional")
  })

  it("unión sin null → sin cambios", () => {
    const input: JsonSchema = {
      anyOf: [{ type: "array" }, { const: "*" }],
    }
    const { schema, nullable } = unwrapNullable(input)
    expect(nullable).toBe(false)
    expect(schema).toBe(input)
  })
})

describe("helpers de cotas y opciones", () => {
  it("hasBothBounds detecta inclusivas y exclusivas", () => {
    expect(hasBothBounds({ minimum: 0, maximum: 1 })).toBe(true)
    expect(hasBothBounds({ exclusiveMinimum: 0, exclusiveMaximum: 1 })).toBe(
      true,
    )
    expect(hasBothBounds({ minimum: 0 })).toBe(false)
  })

  it("numericBounds toma min/max presentes y step=1 para integer", () => {
    expect(numericBounds({ type: "integer", minimum: 2, maximum: 8 })).toEqual({
      min: 2,
      max: 8,
      step: 1,
    })
    expect(
      numericBounds({ type: "number", exclusiveMinimum: 0, exclusiveMaximum: 1 }),
    ).toEqual({ min: 0, max: 1, step: undefined })
  })

  it("enumOptions devuelve enum o [const]", () => {
    expect(enumOptions({ enum: ["a", "b"] })).toEqual(["a", "b"])
    expect(enumOptions({ const: "x" })).toEqual(["x"])
    expect(enumOptions({ type: "string" })).toEqual([])
  })
})

describe("orderedFields y fieldLabel", () => {
  it("ordena por ui_order y luego por declaración", () => {
    const schema: JsonSchema = {
      type: "object",
      properties: {
        a: { type: "string", ui_order: 2 },
        b: { type: "string", ui_order: 1 },
        c: { type: "string" },
      },
    }
    expect(orderedFields(schema).map(([name]) => name)).toEqual(["b", "a", "c"])
  })

  it("fieldLabel usa title o cae al nombre", () => {
    expect(fieldLabel("pdo", { title: "PDO" })).toBe("PDO")
    expect(fieldLabel("pdo", {})).toBe("pdo")
  })

  it("fieldHelp prefiere ui_help y cae en description (B31)", () => {
    expect(
      fieldHelp({ ui_help: "Ayuda humana.", description: "Jerga técnica." }),
    ).toBe("Ayuda humana.")
    expect(fieldHelp({ description: "Jerga técnica." })).toBe("Jerga técnica.")
    expect(fieldHelp({ ui_help: "", description: "Fallback." })).toBe("Fallback.")
    expect(fieldHelp({})).toBeUndefined()
  })
})

describe("groupedFields (agrupado por ui_group, B30)", () => {
  // Réplica del shape real (fixtures/schema.json): grupos declarados en bloque y `ui_order`
  // LOCAL a cada grupo (numerado desde 1; `type` de General en 0).
  const BINNING_LIKE: JsonSchema = {
    type: "object",
    properties: {
      type: { type: "string", const: "standard", ui_group: "General", ui_order: 0 },
      feature_columns: { type: "array", ui_group: "Variables", ui_order: 1 },
      exclude_columns: { type: "array", ui_group: "Variables", ui_order: 2 },
      max_n_prebins: { type: "integer", ui_group: "Restricciones", ui_order: 1 },
      min_prebin_size: { type: "number", ui_group: "Restricciones", ui_order: 2 },
      monotonic_trend: { type: "string", ui_group: "Monotonía", ui_order: 1 },
    },
  }

  it("omite los campos hidden, y el grupo que se queda sin visibles no se emite", () => {
    const conFontaneria: JsonSchema = {
      type: "object",
      properties: {
        schema_version: { type: "string", ui_widget: "hidden", ui_group: "Interno" },
        type: { type: "string", ui_widget: "hidden", ui_group: "Interno" },
        min_prebin_size: { type: "number", ui_group: "Restricciones" },
      },
    }
    expect(orderedFields(conFontaneria).map(([n]) => n)).toEqual(["min_prebin_size"])
    // «Interno» era sólo fontanería: pintar su encabezado sobre nada sería peor que omitirlo.
    expect(groupedFields(conFontaneria).map((g) => g.group)).toEqual(["Restricciones"])
  })

  it("agrupa por ui_group y ordena los grupos por orden de declaración", () => {
    const groups = groupedFields(BINNING_LIKE)
    expect(groups.map((g) => g.group)).toEqual([
      "General",
      "Variables",
      "Restricciones",
      "Monotonía",
    ])
  })

  it("dentro de cada grupo ordena por ui_order (local), no por el global", () => {
    const groups = groupedFields(BINNING_LIKE)
    const variables = groups.find((g) => g.group === "Variables")!
    expect(variables.fields.map(([n]) => n)).toEqual([
      "feature_columns",
      "exclude_columns",
    ])
    // Aunque max_n_prebins y feature_columns comparten ui_order=1, quedan en grupos
    // distintos (no se entremezclan como haría un sort global por ui_order).
    const restricciones = groups.find((g) => g.group === "Restricciones")!
    expect(restricciones.fields.map(([n]) => n)).toEqual([
      "max_n_prebins",
      "min_prebin_size",
    ])
  })

  it("ordena por ui_order aunque la declaración vaya al revés", () => {
    const schema: JsonSchema = {
      type: "object",
      properties: {
        b: { type: "string", ui_group: "G", ui_order: 2 },
        a: { type: "string", ui_group: "G", ui_order: 1 },
      },
    }
    expect(groupedFields(schema)[0].fields.map(([n]) => n)).toEqual(["a", "b"])
  })

  it("campos sin ui_group caen en un grupo group=null (caso data)", () => {
    const schema: JsonSchema = {
      type: "object",
      properties: {
        load: { $ref: "#/$defs/Load" },
        target: { $ref: "#/$defs/Target" },
      },
    }
    const groups = groupedFields(schema)
    expect(groups).toHaveLength(1)
    expect(groups[0].group).toBeNull()
    expect(groups[0].fields.map(([n]) => n)).toEqual(["load", "target"])
  })

  it("objeto sin properties → sin grupos", () => {
    expect(groupedFields({ type: "object" })).toEqual([])
  })
})

describe("unión discriminada (B23.5a §5)", () => {
  it("discriminatorProperty usa el propertyName o 'type' por defecto", () => {
    expect(discriminatorProperty(PARTITION_UNION)).toBe("type")
    expect(discriminatorProperty({ discriminator: { propertyName: "kind" } })).toBe(
      "kind",
    )
    expect(discriminatorProperty({})).toBe("type")
  })

  it("discriminatedBranches resuelve por const del tag (no por mapping) y conserva orden", () => {
    const branches = discriminatedBranches(PARTITION_UNION, PARTITION_DEFS)
    expect(branches.map((b) => b.tag)).toEqual(["temporal", "random"])
    // La rama resuelta trae sus properties (resolvió el $ref prefijado).
    expect(branches[1].schema.properties?.dev_fraction).toBeDefined()
  })

  it("discriminatedBranches ignora ramas sin const de tag string", () => {
    const union: JsonSchema = {
      discriminator: { propertyName: "type" },
      oneOf: [{ type: "object", properties: {} }, { $ref: "#/$defs/Data_RandomSplitConfig" }],
    }
    expect(discriminatedBranches(union, PARTITION_DEFS).map((b) => b.tag)).toEqual([
      "random",
    ])
  })

  it("variantDefaults siembra const y defaults (incluido null explícito)", () => {
    const random = discriminatedBranches(PARTITION_UNION, PARTITION_DEFS).find(
      (b) => b.tag === "random",
    )!
    expect(variantDefaults(random.schema)).toEqual({
      type: "random",
      dev_fraction: 0.7,
      holdout_fraction: 0.15,
      stratify_by: null,
    })
  })

  it("cambiar de tag reemplaza el subobjeto por los defaults de la variante nueva", () => {
    const branches = discriminatedBranches(PARTITION_UNION, PARTITION_DEFS)
    const random = branches.find((b) => b.tag === "random")!
    const temporal = branches.find((b) => b.tag === "temporal")!
    // Estado previo: variante random con su default.
    const before = variantDefaults(random.schema)
    expect(before).toHaveProperty("dev_fraction")
    // Al cambiar a temporal, el nuevo subobjeto NO arrastra dev_fraction.
    const after = variantDefaults(temporal.schema)
    expect(after).toEqual({
      type: "temporal",
      date_col: null,
      holdout_fraction: 0.2,
    })
    expect(after).not.toHaveProperty("dev_fraction")
  })
})

describe("defaultForSchema (semilla al activar X | None)", () => {
  it("usa el default del schema si existe y no es null", () => {
    expect(defaultForSchema({ type: "number", default: 0.05 })).toBe(0.05)
  })

  it("objeto → defaults de sus campos", () => {
    const schema: JsonSchema = {
      type: "object",
      properties: { a: { type: "number", default: 1 }, b: { type: "string" } },
    }
    expect(defaultForSchema(schema)).toEqual({ a: 1 })
  })

  it("por tipo cuando no hay default utilizable (no-null)", () => {
    expect(defaultForSchema({ type: "array" })).toEqual([])
    expect(defaultForSchema({ type: "boolean" })).toBe(false)
    expect(defaultForSchema({ type: "string" })).toBe("")
    expect(defaultForSchema({ type: "string", enum: ["x", "y"] })).toBe("x")
    // número: cota inferior si existe, si no 0
    expect(defaultForSchema({ type: "number", minimum: 2, maximum: 8 })).toBe(2)
    expect(defaultForSchema({ type: "number" })).toBe(0)
  })

  it("resuelve $ref antes de sembrar", () => {
    expect(defaultForSchema({ $ref: "#/$defs/Data_RandomSplitConfig" }, PARTITION_DEFS)).toEqual(
      {
        type: "random",
        dev_fraction: 0.7,
        holdout_fraction: 0.15,
        stratify_by: null,
      },
    )
  })
})

describe("multiselect (B23.5a §5)", () => {
  it("multiselectOptions toma el enum de los items", () => {
    expect(
      multiselectOptions({ type: "array", items: { enum: ["a", "b", "c"] } }),
    ).toEqual(["a", "b", "c"])
    expect(multiselectOptions({ type: "array" })).toEqual([])
  })

  const OPTIONS = ["a", "b", "c"]

  it("marcar agrega en orden estable (= orden del enum), no de marcado", () => {
    // Marca "c" primero, luego "a": el array queda ["a","c"] (orden del enum).
    const step1 = toggleMultiselect([], "c", true, OPTIONS)
    expect(step1).toEqual(["c"])
    const step2 = toggleMultiselect(step1, "a", true, OPTIONS)
    expect(step2).toEqual(["a", "c"])
  })

  it("desmarcar quita el tag", () => {
    expect(toggleMultiselect(["a", "b", "c"], "b", false, OPTIONS)).toEqual([
      "a",
      "c",
    ])
  })

  it("valor no-array de partida se trata como vacío", () => {
    expect(toggleMultiselect(null, "b", true, OPTIONS)).toEqual(["b"])
  })

  it("CONSERVA los valores elegidos que no están entre las opciones", () => {
    // Regresión: descartarlos borraba en silencio el trabajo del usuario en cuanto las opciones
    // vienen del dataset y no del schema (cambiar de archivo, o cargar un YAML antes de subir el
    // CSV, vaciaba el campo solo). Un valor ausente es lo que el preflight debe poder señalar.
    expect(toggleMultiselect(["a", "DEBTINC"], "b", true, OPTIONS)).toEqual([
      "a",
      "b",
      "DEBTINC",
    ])
    // Y se puede desmarcar aunque no esté en options.
    expect(toggleMultiselect(["a", "DEBTINC"], "DEBTINC", false, OPTIONS)).toEqual([
      "a",
    ])
  })
})

describe("listas de sub-objetos — una fila por elemento, no JSON crudo", () => {
  const COLUMNA: JsonSchema = {
    type: "object",
    properties: {
      name: { type: "string", title: "Nombre" },
      dtype: { type: "string", enum: ["int", "float", "str"], default: "float" },
      nullable: { type: "boolean", default: false },
    },
    required: ["name"],
  }
  const LISTA: JsonSchema = { type: "array", items: COLUMNA }
  const DEFS: Defs = { Data_ColumnSpec: COLUMNA }

  it("array de objetos → list (antes caía al editor JSON)", () => {
    expect(resolveWidget(LISTA)).toBe("list")
    expect(isObjectList(LISTA)).toBe(true)
  })

  it("resuelve el item por $ref", () => {
    const porRef: JsonSchema = {
      type: "array",
      items: { $ref: "#/$defs/Data_ColumnSpec" },
    }
    expect(resolveWidget(porRef, { defs: DEFS })).toBe("list")
    expect(itemSchema(porRef, DEFS)?.properties?.name).toBeDefined()
  })

  it("ui_widget `table` y `section` NO ganan sobre una lista de objetos", () => {
    // Los dos alias que el motor emite sobre listas de objetos fallaban en direcciones opuestas:
    // `table` (`scorecard.point_overrides`) caía al editor JSON, y `section`
    // (`binning.variable_overrides`) resolvía a `group`, que sobre un array no encuentra
    // `properties` y pintaba un fieldset con «Sin campos.».
    expect(resolveWidget({ ...LISTA, ui_widget: "table" })).toBe("list")
    expect(resolveWidget({ ...LISTA, ui_widget: "section" })).toBe("list")
  })

  it("`hidden` sigue mandando sobre todo lo demás", () => {
    expect(resolveWidget({ ...LISTA, ui_widget: "hidden" })).toBe("hidden")
  })

  it("un dict[str, X] (object SIN properties) sigue yendo al editor JSON", () => {
    const mapa: JsonSchema = {
      type: "array",
      items: { type: "object", additionalProperties: { type: "string" } },
    }
    expect(isObjectList(mapa)).toBe(false)
    expect(resolveWidget(mapa)).toBe("json")
  })

  it("añadir siembra la fila con los defaults de su schema", () => {
    // Medido: siembra lo que pondría el modelo de Pydantic —los campos con `default`— y NO
    // inventa valor para un requerido que no lo tiene (`name`). La fila nace con el nombre
    // ausente y su input vacío, que es justo lo que el usuario va a escribir; sembrar `""`
    // metería en el config un nombre de columna vacío que el backend rechazaría con un
    // diagnóstico peor que el campo en blanco.
    expect(appendListItem([], COLUMNA)).toEqual([
      { dtype: "float", nullable: false },
    ])
    // Y no pisa lo que ya había.
    expect(appendListItem([{ name: "BAD" }], COLUMNA)).toHaveLength(2)
  })

  it("eliminar quita solo esa fila; un índice inexistente no cambia nada", () => {
    const filas = [{ name: "a" }, { name: "b" }, { name: "c" }]
    expect(removeListItem(filas, 1)).toEqual([{ name: "a" }, { name: "c" }])
    expect(removeListItem(filas, 9)).toEqual(filas)
    expect(removeListItem("no es lista", 0)).toEqual([])
  })

  it("reordenar respeta los bordes (el orden lo compara `data.schema.ordered`)", () => {
    const filas = [{ name: "a" }, { name: "b" }, { name: "c" }]
    expect(moveListItem(filas, 2, -1)).toEqual([
      { name: "a" },
      { name: "c" },
      { name: "b" },
    ])
    expect(moveListItem(filas, 0, -1)).toEqual(filas) // ya está arriba
    expect(moveListItem(filas, 2, 1)).toEqual(filas) // ya está abajo
  })

  it("la etiqueta de una fila sale de su campo identificatorio", () => {
    expect(listItemLabel({ name: "DEBTINC", dtype: "float" })).toBe("DEBTINC")
    expect(listItemLabel({ col: "BAD", op: "==" })).toBe("BAD")
    expect(listItemLabel({ op: "==", value: 1 })).toBe("==") // primer string no vacío
    expect(listItemLabel({ value: 1 })).toBeNull()
    expect(listItemLabel(null)).toBeNull()
  })
})

describe("las listas de objetos del SCHEMA REAL del backend", () => {
  const defs: Defs = (fixtureSchema as unknown as SchemaPayload).json_schema.$defs ?? {}
  const raiz = (fixtureSchema as unknown as SchemaPayload).json_schema

  /** Baja por un path de secciones/campos resolviendo uniones y $ref, como hace el renderer. */
  const campoEn = (ruta: string[]): JsonSchema | undefined => {
    let nodo: JsonSchema | undefined = raiz
    for (const tramo of ruta) {
      if (!nodo) return undefined
      const candidatas: JsonSchema[] = nodo.anyOf ?? nodo.oneOf ?? [nodo]
      const ramas: JsonSchema[] = candidatas.map((r: JsonSchema) =>
        resolveRef(r, defs),
      )
      const conProps: JsonSchema | undefined = ramas.find(
        (r: JsonSchema) => r.properties?.[tramo] !== undefined,
      )
      const siguiente: JsonSchema | undefined = conProps?.properties?.[tramo]
      nodo = siguiente ? resolveRef(siguiente, defs) : undefined
    }
    return nodo
  }

  it("data.schema.columns se edita fila a fila, con un campo `name` por fila", () => {
    // El caso que se midió en cámara: 1.552 caracteres de JSON en un textarea de cinco líneas,
    // y 2.412 que teclear para describir HMEQ.
    const campo = campoEn(["data", "schema", "columns"])
    expect(campo, "data.schema.columns no está en el schema").toBeDefined()
    expect(resolveWidget(campo!, { defs })).toBe("list")
    expect(itemSchema(campo!, defs)?.properties?.name).toBeDefined()
  })

  it.each([
    ["data.target.bad_rule.all_of", ["data", "target", "bad_rule", "all_of"]],
    ["binning.variable_overrides", ["binning", "variable_overrides"]],
    ["scorecard.point_overrides", ["scorecard", "point_overrides"]],
  ])("%s también", (_nombre, ruta) => {
    const campo = campoEn(ruta as string[])
    expect(campo).toBeDefined()
    expect(resolveWidget(campo!, { defs })).toBe("list")
  })
})

describe("listas de nombres de columna — opciones del DATASET, no del schema", () => {
  /** `tuple[str, ...]` con rol, la forma de `binning.categorical_columns`. */
  const LISTA_CON_ROL: JsonSchema = {
    type: "array",
    items: { type: "string" },
    column_role: "input",
    ui_widget: "multiselect",
  }

  /** `tuple[str, ...] | Literal["*"]`, la forma de `binning.feature_columns`. */
  const LISTA_O_COMODIN: JsonSchema = {
    anyOf: [{ type: "array", items: { type: "string" } }, { const: "*" }],
    column_role: "input",
    ui_widget: "multiselect",
  }

  const COLUMNAS = ["BAD", "LOAN", "DEBTINC"]

  it("column_role se lee en el campo y también en sus ramas", () => {
    expect(columnRole(LISTA_CON_ROL)).toBe("input")
    expect(columnRole(LISTA_O_COMODIN)).toBe("input")
    expect(columnRole({ type: "array", items: { type: "string" } })).toBeUndefined()
  })

  it("sin enum pero con rol `input`, las opciones son las columnas del dataset", () => {
    // Antes devolvía [] y el formulario pintaba «Sin opciones.» con cero controles.
    expect(multiselectOptions(LISTA_CON_ROL, { datasetColumns: COLUMNAS })).toEqual(
      COLUMNAS,
    )
  })

  it("también en la unión con el comodín, donde la raíz no tiene `items`", () => {
    // El caso que rompía: `multiselectOptions` miraba `schema.items` y una unión no lo tiene,
    // así que `feature_columns` —el campo central de la demo— no ofrecía nada.
    expect(multiselectOptions(LISTA_O_COMODIN, { datasetColumns: COLUMNAS })).toEqual(
      COLUMNAS,
    )
  })

  it("sin dataset cargado devuelve [] y la lista NO es cerrada (⇒ entrada libre)", () => {
    expect(multiselectOptions(LISTA_CON_ROL, {})).toEqual([])
    expect(hasClosedOptions(LISTA_CON_ROL)).toBe(false)
  })

  it("un enum del schema sigue mandando sobre las columnas, y es lista CERRADA", () => {
    const conEnum: JsonSchema = {
      type: "array",
      items: { enum: ["pd", "lgd"] },
      column_role: "input",
    }
    expect(multiselectOptions(conEnum, { datasetColumns: COLUMNAS })).toEqual([
      "pd",
      "lgd",
    ])
    expect(hasClosedOptions(conEnum)).toBe(true)
  })

  it("acceptsWildcard distingue la unión con `*` de una lista simple", () => {
    expect(acceptsWildcard(LISTA_O_COMODIN)).toBe(true)
    expect(acceptsWildcard(LISTA_CON_ROL)).toBe(false)
  })

  it("un array de strings con rol resuelve a multiselect aunque no declare ui_widget", () => {
    // `data.schema.unique_keys` declara el rol y ningún `ui_widget`: caía al editor JSON.
    const sinWidget: JsonSchema = {
      type: "array",
      items: { type: "string" },
      column_role: "input",
    }
    expect(resolveWidget(sinWidget)).toBe("multiselect")
    // Sin rol, una lista de strings sigue siendo JSON: no todo array de texto son columnas
    // (`data.partition.strategy.oot_cohorts` son VALORES de cohorte).
    expect(resolveWidget({ type: "array", items: { type: "string" } })).toBe("json")
  })
})

describe("las tres listas de binning contra el SCHEMA REAL del backend", () => {
  // Ancla con nombres escritos a mano —no derivados de lo que se vigila— sobre el fixture que
  // viaja en el paquete. Es el caso que se vio roto en cámara: subir un CSV y no poder elegir
  // ni ver una sola variable. Si el motor deja de declarar `column_role` en cualquiera de los
  // tres, esto se pone rojo aunque el resto del formulario siga compilando.
  const defs: Defs = (fixtureSchema as unknown as SchemaPayload).json_schema.$defs ?? {}
  const binning = resolveRef(
    (fixtureSchema as unknown as SchemaPayload).json_schema.properties?.binning ?? {},
    defs,
  )
  const seccion = (binning.anyOf ?? binning.oneOf ?? [binning])
    .map((rama) => resolveRef(rama, defs))
    .find((rama) => rama.properties !== undefined)

  const COLUMNAS_HMEQ = ["BAD", "LOAN", "DEBTINC", "REASON", "JOB"]

  it.each(["feature_columns", "exclude_columns", "categorical_columns"])(
    "binning.%s ofrece las columnas del dataset",
    (nombre) => {
      const campo = seccion?.properties?.[nombre]
      expect(campo, `binning.${nombre} no está en el schema`).toBeDefined()
      expect(columnRole(campo!, defs)).toBe("input")
      expect(resolveWidget(campo!, { defs })).toBe("multiselect")
      expect(
        multiselectOptions(campo!, { datasetColumns: COLUMNAS_HMEQ }, defs),
      ).toEqual(COLUMNAS_HMEQ)
    },
  )

  it("feature_columns admite el comodín `*` (el valor que traen los presets)", () => {
    expect(acceptsWildcard(seccion!.properties!.feature_columns, defs)).toBe(true)
  })
})

describe("fieldPlaceholder — ayuda en campos (examples > description)", () => {
  it("usa el primer example como sugerencia 'p. ej. …'", () => {
    expect(
      fieldPlaceholder({ type: "string", examples: ["target_default"] }),
    ).toBe("p. ej. target_default")
  })

  it("varios examples se unen por coma en orden", () => {
    expect(
      fieldPlaceholder({ type: "string", examples: ["a", "b", "c"] }),
    ).toBe("p. ej. a, b, c")
  })

  it("examples no-string se formatean vía JSON (números, arrays)", () => {
    expect(fieldPlaceholder({ type: "number", examples: [0.7] })).toBe(
      "p. ej. 0.7",
    )
    expect(
      fieldPlaceholder({ type: "array", examples: [["x", "y"]] }),
    ).toBe('p. ej. ["x","y"]')
  })

  it("examples tiene prioridad sobre description", () => {
    expect(
      fieldPlaceholder({
        type: "string",
        description: "Nombre de la columna objetivo",
        examples: ["default_12m"],
      }),
    ).toBe("p. ej. default_12m")
  })

  it("sin examples cae en la description (comportamiento actual del schema)", () => {
    expect(
      fieldPlaceholder({ type: "string", description: "Nombre de la columna" }),
    ).toBe("Nombre de la columna")
  })

  it("examples vacío o ausente → cae en la description", () => {
    expect(
      fieldPlaceholder({ type: "string", examples: [], description: "d" }),
    ).toBe("d")
  })

  it("sin examples ni description → undefined (no inventa ejemplos)", () => {
    expect(fieldPlaceholder({ type: "string" })).toBeUndefined()
  })
})
