import { describe, expect, it } from "vitest"

import fieldRendererSource from "@/components/FieldRenderer.tsx?raw"
import fixtureSchema from "@/fixtures/schema.json"
import type { DatasetInfo } from "@/lib/api"
import {
  columnValuesByName,
  fromCatalog,
  reconcileSelected,
  type SelectedDataset,
} from "@/lib/datasets"
import type { SchemaPayload } from "@/lib/schema"

import {
  type Defs,
  type JsonSchema,
  acceptsWildcard,
  appendListItem,
  arrayBranch,
  columnOptions,
  columnRole,
  columnValuesFrom,
  defaultForSchema,
  discriminatedBranches,
  discriminatorProperty,
  enumOptions,
  fieldHelp,
  fieldLabel,
  fieldPlaceholder,
  groupedFields,
  grupoTitulaASuUnicoCampo,
  hasBothBounds,
  hasClosedOptions,
  isColumnField,
  isHiddenField,
  isObjectList,
  itemSchema,
  listItemLabel,
  moveListItem,
  multiselectOptions,
  optionsFromDataset,
  optionsWithDraft,
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

  it("«no está en el dataset» sólo se puede decir si las opciones SALEN del dataset", () => {
    // Regresión medida el 2026-07-29 al añadir la sección `report` al formulario:
    // `report.sections.required_sections` es una lista de strings que nombra SECCIONES del informe,
    // sin `enum` ni `column_role`. Sin opciones que ofrecer, sus siete valores de fábrica caían en
    // la rama «ausente» y la pantalla los pintaba en rojo con «(no está en el dataset)» sobre un
    // config perfectamente válido.
    const SECCIONES_DEL_INFORME: JsonSchema = { type: "array", items: { type: "string" } }
    expect(optionsFromDataset(SECCIONES_DEL_INFORME)).toBe(false)
    expect(multiselectOptions(SECCIONES_DEL_INFORME, { datasetColumns: COLUMNAS })).toEqual([])

    // Una lista de nombres de columna SÍ autoriza la marca, con dataset cargado o sin él.
    expect(optionsFromDataset(LISTA_CON_ROL)).toBe(true)
    expect(optionsFromDataset(LISTA_O_COMODIN)).toBe(true)

    // Un enum manda sobre el rol: lista cerrada ⇒ el dataset no tiene nada que decir.
    expect(
      optionsFromDataset({
        type: "array",
        items: { enum: ["pd", "lgd"] },
        column_role: "input",
      }),
    ).toBe(false)
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

  it("feature_columns explica la exclusión automática y la salida explícita", () => {
    const campo = seccion!.properties!.feature_columns
    expect(campo.description).toContain("definen el target")
    expect(campo.ui_help).toContain("lista explícita")
    expect(campo.ui_help).toContain("queda auditada")
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

describe("grupoTitulaASuUnicoCampo (M10: «Documento / Documento»)", () => {
  const documento: JsonSchema = { $ref: "#/$defs/Doc", title: "Documento", ui_group: "Documento" }

  it("un grupo cuyo único campo se llama igual: el campo no debe repetir el título", () => {
    expect(
      grupoTitulaASuUnicoCampo({ group: "Documento", fields: [["document", documento]] }),
    ).toBe(true)
  })

  it("con DOS campos el título del grupo es un paraguas: cada campo conserva el suyo", () => {
    expect(
      grupoTitulaASuUnicoCampo({
        group: "Documento",
        fields: [
          ["document", documento],
          ["otro", { type: "string", title: "Otro" }],
        ],
      }),
    ).toBe(false)
  })

  it("títulos distintos: no se toca nada", () => {
    expect(
      grupoTitulaASuUnicoCampo({
        group: "Salida",
        fields: [["document", documento]],
      }),
    ).toBe(false)
  })

  it("grupo sin título (campos sin ui_group): no aplica", () => {
    expect(grupoTitulaASuUnicoCampo({ group: null, fields: [["document", documento]] })).toBe(false)
  })

  it("cae al NOMBRE del campo cuando no hay title, igual que fieldLabel", () => {
    expect(
      grupoTitulaASuUnicoCampo({ group: "html", fields: [["html", { type: "object" }]] }),
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Gate: rol ⇒ widget, sobre el SCHEMA REAL y atravesando el desempaquetado de nullables
// ---------------------------------------------------------------------------

/**
 * Gate en la dirección que faltaba: **un campo que declara `column_role` tiene que llegar al
 * formulario con ese rol**, sea cual sea la forma en que viaje.
 *
 * `tests/unit/test_column_roles.py` cubre la dirección contraria (todo multiselect de texto libre
 * declara su rol) y por eso no podía ver este defecto: `data.schema.unique_keys` DECLARA
 * `column_role: "input"` desde siempre (`data/config.py:271-281`), así que el gate de Python
 * estaba legítimamente verde mientras el front pintaba un textarea de JSON crudo.
 *
 * La causa era el desempaquetado: `unwrapNullable` copiaba ocho propiedades del nodo externo y
 * `column_role` no estaba entre ellas, de modo que un `X | None` perdía el rol al bajar a su rama.
 * `resolveWidget` recurre sobre esa rama y `NullableField` se la pasa al renderer hijo, así que la
 * pérdida se lleva por delante el widget **y** el origen de las opciones.
 *
 * ⚠️ El caso se escapó de la suite porque los tests de esta zona construyen schemas a mano y
 * **no-nullables** (ver «un array de strings con rol resuelve a multiselect aunque no declare
 * ui_widget»): sobre esa forma el rol nunca se pierde. De ahí que este gate recorra el schema REAL
 * del backend, que es el único sitio donde existe la forma que falla.
 */
describe("todo campo con `column_role` conserva su rol al llegar al widget", () => {
  const defs: Defs = (fixtureSchema as unknown as SchemaPayload).json_schema.$defs ?? {}

  /**
   * Todo nodo del schema compuesto que declare `column_role`, con su ruta.
   *
   * Recorre el JSON **crudo y entero**, sin asumir la forma de un campo: las 22 clases raíz de
   * sección van *inline* en la raíz y sus sub-modelos en `$defs`, así que un barrido que mire una
   * sola de las dos coordenadas deja fuera un tercio del catálogo (lección del paquete D).
   */
  function nodosConRol(): { ruta: string; schema: JsonSchema }[] {
    const salida: { ruta: string; schema: JsonSchema }[] = []
    const baja = (nodo: unknown, ruta: string): void => {
      if (Array.isArray(nodo)) {
        nodo.forEach((hijo, i) => baja(hijo, `${ruta}[${i}]`))
        return
      }
      if (!nodo || typeof nodo !== "object") return
      const objeto = nodo as JsonSchema
      if (objeto.column_role !== undefined) salida.push({ ruta, schema: objeto })
      for (const [clave, hijo] of Object.entries(objeto)) baja(hijo, `${ruta}/${clave}`)
    }
    baja((fixtureSchema as unknown as SchemaPayload).json_schema, "")
    return salida
  }

  const CON_ROL = nodosConRol()

  it("el barrido encuentra campos de verdad (si no, este gate estaría vacío)", () => {
    // Un gate que recorre cero campos da verde sin comprobar nada, y «0 ofensores» se lee igual
    // que «todo limpio». La cifra sale de la medición del 2026-08-02 sobre el fixture real.
    expect(CON_ROL.length).toBeGreaterThanOrEqual(36)
  })

  it("el rol sobrevive al desempaquetado de `X | None`", () => {
    const perdidos = CON_ROL.filter(({ schema }) => {
      const declarado = columnRole(schema, defs)
      const { schema: base } = unwrapNullable(resolveRef(schema, defs))
      return columnRole(base, defs) !== declarado
    }).map(({ ruta, schema }) => `${ruta} (${String(schema.column_role)})`)

    expect(
      perdidos,
      "Campos que declaran `column_role` y lo PIERDEN al desempaquetar su rama no nula. " +
        "El formulario les da entonces el widget equivocado (una lista de columnas cae al editor " +
        "JSON) y el multiselect se queda sin opciones. Propaga la propiedad en `unwrapNullable`.",
    ).toEqual([])
  })

  it("una lista de columnas `input` resuelve a multiselect, no al editor JSON", () => {
    // La pregunta de producto, no la mecánica: si el valor del campo es una LISTA y sus elementos
    // son nombres de columna del dataset, el usuario tiene que poder elegirlos con checkboxes.
    const listas = CON_ROL.filter(
      ({ schema }) =>
        columnRole(schema, defs) === "input" &&
        arrayBranch(schema, defs) !== undefined &&
        !isObjectList(schema, defs),
    )
    expect(listas.length).toBeGreaterThanOrEqual(4)

    const alEditorJson = listas
      .filter(({ schema }) => resolveWidget(schema, { defs }) !== "multiselect")
      .map(({ ruta }) => ruta)

    expect(
      alEditorJson,
      "Listas de nombres de columna que NO llegan como multiselect: el usuario tendría que " +
        "escribir JSON a mano teniendo el front las columnas del dataset cargadas.",
    ).toEqual([])
  })

  it("`data.schema.unique_keys` es el caso concreto, con nombre y todo", () => {
    // Ancla escrita a mano: si el barrido de arriba deja de encontrar este campo, el gate genérico
    // podría quedarse verde sobre un conjunto vacío y nadie se enteraría.
    const uniqueKeys = (defs["data__SchemaConfig"]?.properties ?? {})["unique_keys"]
    expect(uniqueKeys, "`data__SchemaConfig.unique_keys` no está en el schema").toBeDefined()
    expect(columnRole(uniqueKeys, defs)).toBe("input")
    expect(resolveWidget(uniqueKeys, { defs })).toBe("multiselect")

    // Y sus opciones son las columnas del dataset, también tras el desempaquetado: es lo que
    // consume `NullableField`, que le pasa al renderer hijo la rama base y no el campo original.
    const COLUMNAS = ["cliente_id", "fecha", "monto"]
    const { schema: base } = unwrapNullable(resolveRef(uniqueKeys, defs))
    expect(multiselectOptions(base, { datasetColumns: COLUMNAS }, defs)).toEqual(COLUMNAS)
    expect(optionsFromDataset(base, defs)).toBe(true)
  })
})

describe("la división ya marcada en el archivo, contra el SCHEMA REAL del backend", () => {
  // `data.partition.strategy = {type: "columna"}` (D-COL-2/3/4): el usuario ya separó su muestra y
  // sólo declara qué valor de su columna corresponde a cada conjunto. Sus tres campos son listas de
  // strings SIN `enum` —los valores dependen del archivo—, así que sin `column_values_from` caían
  // al editor JSON y obligaban a teclear `["DEV"]` a mano sobre un textarea.
  //
  // Ancla escrita a mano sobre el fixture que viaja en el paquete: si el motor deja de declarar la
  // anotación, esto se pone rojo aunque todo lo demás siga compilando.
  const defs: Defs = (fixtureSchema as unknown as SchemaPayload).json_schema.$defs ?? {}
  const columnSplit = defs["data__ColumnSplitConfig"]
  const CAMPOS = ["desarrollo", "holdout", "oot"] as const

  // Una columna «muestra» con sus valores, como los publica el perfil del dataset (D-COL-7).
  const VALORES = { muestra: ["DEV", "VAL", "OOT"], region: ["RM", "V", "VIII"] }

  it("la rama `columna` existe en el schema y trae sus cuatro campos", () => {
    expect(columnSplit, "`data__ColumnSplitConfig` no está en el schema").toBeDefined()
    expect(Object.keys(columnSplit!.properties ?? {}).sort()).toEqual([
      "desarrollo",
      "holdout",
      "oot",
      "partition_col",
      "type",
    ])
  })

  it.each(CAMPOS)("%s declara de qué campo hermano salen sus opciones", (nombre) => {
    const campo = columnSplit!.properties![nombre]
    expect(campo, `${nombre} no está en el schema`).toBeDefined()
    // El nombre del CAMPO hermano, no el de la columna: la columna la elige el usuario.
    expect(columnValuesFrom(campo, defs)).toBe("partition_col")
  })

  it.each(CAMPOS)("%s se pinta como multiselect, no como editor JSON", (nombre) => {
    expect(resolveWidget(columnSplit!.properties![nombre], { defs })).toBe(
      "multiselect",
    )
  })

  it.each(CAMPOS)(
    "%s ofrece los valores de la columna que nombra `partition_col`",
    (nombre) => {
      const campo = columnSplit!.properties![nombre]
      expect(
        multiselectOptions(
          campo,
          {
            datasetColumnValues: VALORES,
            siblingValues: { type: "columna", partition_col: "muestra" },
          },
          defs,
        ),
      ).toEqual(["DEV", "VAL", "OOT"])
    },
  )

  it("cambiar de columna cambia las opciones (se indexa por el hermano, no por el campo)", () => {
    const campo = columnSplit!.properties!.desarrollo
    expect(
      multiselectOptions(
        campo,
        {
          datasetColumnValues: VALORES,
          siblingValues: { partition_col: "region" },
        },
        defs,
      ),
    ).toEqual(["RM", "V", "VIII"])
  })

  it("`partition_col` es una columna del dataset, y sigue siéndolo", () => {
    // No es decorativo: es el campo que estos tres consultan. Si dejara de declarar su rol, el
    // usuario perdería el selector de columna y con él las opciones de los otros tres.
    expect(columnRole(columnSplit!.properties!.partition_col, defs)).toBe("input")
  })

  describe("controles negativos — nunca «Sin opciones.», siempre entrada libre", () => {
    it.each(CAMPOS)("%s: sin `datasetColumnValues` no hay opciones", (nombre) => {
      const campo = columnSplit!.properties![nombre]
      expect(
        multiselectOptions(campo, { siblingValues: { partition_col: "muestra" } }, defs),
      ).toEqual([])
    })

    it.each(CAMPOS)("%s: con `partition_col` en blanco no hay opciones", (nombre) => {
      const campo = columnSplit!.properties![nombre]
      expect(
        multiselectOptions(
          campo,
          { datasetColumnValues: VALORES, siblingValues: { partition_col: "" } },
          defs,
        ),
      ).toEqual([])
      // Y con el hermano AUSENTE, que es el estado de arranque del formulario.
      expect(
        multiselectOptions(campo, { datasetColumnValues: VALORES, siblingValues: {} }, defs),
      ).toEqual([])
      // Y sin contexto ninguno.
      expect(multiselectOptions(campo, {}, defs)).toEqual([])
    })

    it("una columna sin valores medidos tampoco los inventa", () => {
      // Perfil ausente (dataset del catálogo sin materializar) o columna con demasiados valores
      // distintos: el backend publica `[]`, que significa «no se midió», no «no tiene valores».
      const campo = columnSplit!.properties!.desarrollo
      expect(
        multiselectOptions(
          campo,
          {
            datasetColumnValues: VALORES,
            siblingValues: { partition_col: "cliente_id" },
          },
          defs,
        ),
      ).toEqual([])
    })

    it.each(CAMPOS)("%s: la lista NO es cerrada — se puede escribir a mano", (nombre) => {
      // Lo decisivo del control negativo: sin opciones el widget tiene que ofrecer entrada libre.
      // El perfil publica sólo los valores más FRECUENTES (top-20), así que incluso con la lista
      // llena el usuario puede tener un valor que no salga.
      expect(hasClosedOptions(columnSplit!.properties![nombre], defs)).toBe(false)
    })

    it.each(CAMPOS)("%s: no se acusa a un valor de «no estar en el dataset»", (nombre) => {
      // `optionsFromDataset` es lo ÚNICO que autoriza esa etiqueta roja. Aquí sería falsa: que un
      // valor no esté entre los veinte más frecuentes no significa que no esté en el archivo.
      expect(optionsFromDataset(columnSplit!.properties![nombre], defs)).toBe(false)
    })

    it("y tampoco si el campo declarase ADEMÁS `column_role: input`", () => {
      // ⚠️ Medido: los tres campos reales no declaran `column_role`, así que el `false` de arriba
      // saldría igual sin la guarda de `column_values_from` — es un verde que no la mide. Este caso
      // sí la ejerce, y es el que la guarda existe para atender: si mañana un campo declara las dos
      // anotaciones, manda la que describe VALORES, porque de ellos sólo se publica un recorte.
      const ambas: JsonSchema = {
        type: "array",
        items: { type: "string" },
        column_role: "input",
        column_values_from: "partition_col",
      }
      expect(columnRole(ambas, defs)).toBe("input")
      expect(optionsFromDataset(ambas, defs)).toBe(false)
    })

    it("un valor escrito a mano se conserva aunque no esté entre las opciones", () => {
      // Regresión histórica: `toggleMultiselect` descartaba los valores fuera de `options` y
      // borraba en silencio el trabajo del usuario en cuanto las opciones venían de los datos.
      const opciones = ["DEV", "VAL", "OOT"]
      expect(toggleMultiselect(["ENTRENAMIENTO"], "DEV", true, opciones)).toEqual([
        "DEV",
        "ENTRENAMIENTO",
      ])
      // Y quitar otro tampoco se lo lleva por delante.
      expect(
        toggleMultiselect(["DEV", "ENTRENAMIENTO"], "DEV", false, opciones),
      ).toEqual(["ENTRENAMIENTO"])
    })
  })

  it.each(CAMPOS)("%s: `column_values_from` sobrevive a `unwrapNullable`", (nombre) => {
    // El defecto exacto de la sesión anterior: `unwrapNullable` copia propiedades A MANO y omitir
    // una deja al campo con el widget equivocado (fue lo que dejó `unique_keys` en el editor JSON).
    //
    // ⚠️ La anotación va en el nodo EXTERIOR, no dentro de la rama, y eso NO es una elección del
    // test: es donde Pydantic la pone. Medido sobre el campo opcional real
    // `data__SchemaConfig.unique_keys`, que publica `{anyOf: [<array>, <null>], column_role: …}`.
    // Meterla dentro de la rama hace pasar el test con la propagación BORRADA —el `...base` de
    // `unwrapNullable` ya la arrastraría—, o sea un verde que no mide nada.
    const { column_values_from, ...forma } = columnSplit!.properties![nombre]
    const opcional: JsonSchema = {
      anyOf: [forma, { type: "null" }],
      column_values_from,
      default: null,
    }
    expect(
      (opcional.anyOf![0] as JsonSchema).column_values_from,
      "la rama no debe traer la anotación, o el test se mide a sí mismo",
    ).toBeUndefined()

    const { schema: base, nullable } = unwrapNullable(opcional)
    expect(nullable).toBe(true)
    expect(base.column_values_from).toBe("partition_col")
    expect(resolveWidget(base, { defs })).toBe("multiselect")
    expect(
      multiselectOptions(
        base,
        {
          datasetColumnValues: VALORES,
          siblingValues: { partition_col: "muestra" },
        },
        defs,
      ),
    ).toEqual(["DEV", "VAL", "OOT"])
  })

  it("y el campo opcional entero resuelve a multiselect sin desempaquetar a mano", () => {
    // El camino que recorre el renderer de verdad: `resolveWidget` desempaqueta él mismo. Si la
    // propagación se pierde, aquí el campo cae al editor JSON.
    const { column_values_from, ...forma } = columnSplit!.properties!.desarrollo
    const opcional: JsonSchema = {
      anyOf: [forma, { type: "null" }],
      column_values_from,
      default: null,
    }
    expect(columnValuesFrom(opcional, defs)).toBe("partition_col")
    expect(resolveWidget(opcional, { defs })).toBe("multiselect")
  })
})

describe("añadir a mano un valor NUNCA duplica (el `config_hash` no se mueve solo)", () => {
  // 🔴 Defecto real: `addDraft` concatenaba el nombre escrito a las opciones SIEMPRE. Con una
  // opción ya ofrecida pero sin marcar —el caso normal desde que las opciones salen de los valores
  // del dataset (D-COL-7)— la lista llegaba con el nombre repetido y salía `["DEV","DEV"]`: UN
  // checkbox en pantalla, un duplicado en el YAML y el `config_hash` movido sin que nada lo
  // delatara.
  const OFRECIDAS = ["DEV", "VAL", "OOT"]

  describe("toggleMultiselect — la segunda línea de defensa", () => {
    it("no devuelve duplicados aunque `options` los traiga (el reproductor exacto)", () => {
      expect(toggleMultiselect([], "DEV", true, ["DEV", "VAL", "OOT", "DEV"])).toEqual([
        "DEV",
      ])
    })

    it("tampoco con un valor ya elegido y repetido en las opciones", () => {
      expect(
        toggleMultiselect(["DEV"], "VAL", true, ["DEV", "VAL", "DEV", "VAL"]),
      ).toEqual(["DEV", "VAL"])
    })

    it("ni cuando el repetido viene de un valor libre que además se ofrece", () => {
      // `known` y `unknown` pueden reclamar el mismo valor si `options` lo trae dos veces.
      expect(
        toggleMultiselect(["MIO"], "DEV", true, ["DEV", "MIO", "MIO"]),
      ).toEqual(["DEV", "MIO"])
    })

    it("y sigue conservando el orden estable y los valores libres al final", () => {
      // El dedup no puede cambiar lo que esta función ya prometía: orden de `options`, y los
      // valores que no están entre ellas conservados al final.
      expect(
        toggleMultiselect(["ESCRITO_A_MANO", "OOT"], "DEV", true, OFRECIDAS),
      ).toEqual(["DEV", "OOT", "ESCRITO_A_MANO"])
    })
  })

  describe("optionsWithDraft — la causa, en el único sitio donde es falsable", () => {
    // ⚠️ Medido: con el dedup de `toggleMultiselect` puesto, la lista FINAL sale bien con o sin
    // esta guarda, así que un test sobre el resultado del flujo pasa igual con la causa dentro.
    // Por eso la guarda vive en una función propia y se prueba en su propia salida.
    it("no repite un nombre que ya se ofrecía", () => {
      expect(optionsWithDraft(OFRECIDAS, [], "DEV")).toEqual(OFRECIDAS)
    })

    it("no repite un nombre que ya estaba entre los valores libres", () => {
      expect(optionsWithDraft(OFRECIDAS, ["MIO"], "MIO")).toEqual([
        ...OFRECIDAS,
        "MIO",
      ])
    })

    it("añade al final un nombre que de verdad es nuevo", () => {
      expect(optionsWithDraft(OFRECIDAS, [], "ENTRENAMIENTO")).toEqual([
        ...OFRECIDAS,
        "ENTRENAMIENTO",
      ])
    })

    it("su salida nunca tiene repetidos, sea cual sea el borrador", () => {
      for (const borrador of ["DEV", "VAL", "OOT", "MIO", "NUEVO"]) {
        const salida = optionsWithDraft(OFRECIDAS, ["MIO"], borrador)
        expect(new Set(salida).size, `«${borrador}» duplicó una opción`).toBe(
          salida.length,
        )
      }
    })
  })

  it("el flujo completo de addDraft sobre una opción ya ofrecida y NO marcada", () => {
    // La secuencia exacta que ejecuta el widget: se computan las candidatas y se alterna sobre
    // ellas. Antes daba `["DEV","DEV"]`.
    const current: unknown[] = []
    const options = OFRECIDAS
    const extra: unknown[] = []
    const escrito = "DEV"

    const resultado = toggleMultiselect(
      current,
      escrito,
      true,
      optionsWithDraft(options, extra, escrito),
    )
    expect(resultado).toEqual(["DEV"])
    expect(new Set(resultado).size).toBe(resultado.length)
  })

  it("y sobre un valor que de verdad no se ofrecía (no se rompió el caso bueno)", () => {
    const resultado = toggleMultiselect(
      ["DEV"],
      "ENTRENAMIENTO",
      true,
      optionsWithDraft(OFRECIDAS, [], "ENTRENAMIENTO"),
    )
    expect(resultado).toEqual(["DEV", "ENTRENAMIENTO"])
  })
})

describe("la secuencia REAL: catálogo sin perfil → elegir → preflight → formulario", () => {
  // 🔴 El defecto que cierra, de punta a punta y con las funciones de verdad (nada re-implementado
  // en el test): en un workdir nuevo el catálogo describe los datasets SIN materializar, así que
  // sus columnas llegan con `values: []`; quien las mide es el preflight, DESPUÉS de que el
  // usuario ya eligió. La ficha activa se quedaba con la instantánea pobre y las casillas de
  // valores no aparecían nunca para un dataset del catálogo.
  //
  // Medido contra el backend antes de escribir esto: `list_datasets` da 0 columnas con valores
  // antes de `materialize()` y 4 después, sobre `consumo_comportamiento`.
  const defs: Defs = (fixtureSchema as unknown as SchemaPayload).json_schema.$defs ?? {}
  const desarrollo = defs["data__ColumnSplitConfig"]!.properties!.desarrollo
  const hermanos = { type: "columna", partition_col: "cohorte" }

  const GET_1: DatasetInfo = {
    id: "consumo_comportamiento",
    name: "Consumo",
    description: "",
    n_rows: 10000,
    columns: [
      { name: "loan_id", dtype: "int64", role: "feature", values: [] },
      { name: "cohorte", dtype: "object", role: "feature", values: [] },
    ],
  }
  const GET_2: DatasetInfo = {
    ...GET_1,
    columns: [
      { name: "loan_id", dtype: "int64", role: "feature", values: [] },
      {
        name: "cohorte",
        dtype: "object",
        role: "feature",
        values: ["2023Q1", "2023Q2", "2023Q3", "2024Q1"],
      },
    ],
  }

  /** Lo que el formulario ofrece con una ficha dada (la cadena entera, como en `ConfigTab`). */
  const opcionesDelFormulario = (ficha: SelectedDataset | null): unknown[] =>
    multiselectOptions(
      desarrollo,
      { datasetColumnValues: columnValuesByName(ficha), siblingValues: hermanos },
      defs,
    )

  it("antes del preflight el formulario no puede ofrecer nada, y no miente", () => {
    const elegida = fromCatalog(GET_1)
    expect(opcionesDelFormulario(elegida)).toEqual([])
    // Y eso NO puede degradar a «Sin opciones.»: la lista sigue abierta.
    expect(hasClosedOptions(desarrollo, defs)).toBe(false)
  })

  it("después del preflight, las casillas aparecen SIN cambiar de dataset", () => {
    const elegida = fromCatalog(GET_1) // paso 1-2: GET sin perfil + elección
    const reconciliada = reconcileSelected(elegida, [GET_2]) // paso 3: preflight materializó

    expect(reconciliada!.id).toBe(elegida.id) // el dataset es el MISMO
    expect(opcionesDelFormulario(reconciliada)).toEqual([
      "2023Q1",
      "2023Q2",
      "2023Q3",
      "2024Q1",
    ])
  })

  it("y el widget sigue siendo multiselect, no el editor JSON", () => {
    expect(resolveWidget(desarrollo, { defs })).toBe("multiselect")
  })
})

/**
 * El hueco ESCALAR que D-COL-7 dejó abierto: los VALORES de una columna ya se eligen con casillas,
 * pero el NOMBRE de la columna se tecleaba a ciegas en una caja de texto, con el archivo cargado y
 * sus columnas conocidas por la aplicación. Ocho campos del schema real, el más visible de ellos el
 * `col` de cada predicado de `bad_rule` («¿qué define a un cliente malo?»).
 *
 * Se mide contra el schema REAL del backend y no contra formas escritas a mano, por el mismo motivo
 * que el gate de `column_role` de aquí arriba: la forma que falla —la anotación en el nodo exterior
 * de un `X | None`, o conviviendo con un `ui_widget`— sólo existe en el schema del motor.
 */
describe("una columna suelta se ELIGE, no se escribe a ciegas", () => {
  const defs: Defs = (fixtureSchema as unknown as SchemaPayload).json_schema.$defs ?? {}
  const COLUMNAS = ["cliente_id", "muestra", "monto", "mora_dias"]

  /**
   * Todo campo ESCALAR de texto que declara `column_role: "input"`, con su ruta.
   *
   * El criterio de «escalar» se escribe A MANO —tipo `string`, o `X | None` con una sola rama no
   * nula de tipo `string`— y no llamando a `isColumnField`: un barrido derivado de la función que
   * vigila encuentra exactamente lo que ella dice y no mide nada.
   */
  function columnasSueltas(): { ruta: string; schema: JsonSchema }[] {
    const escalarDeTexto = (s: JsonSchema): boolean => {
      if (s.type === "string") return true
      const ramas = (s.anyOf ?? s.oneOf ?? []).filter((r) => r.type !== "null")
      return ramas.length === 1 && ramas[0].type === "string"
    }
    const salida: { ruta: string; schema: JsonSchema }[] = []
    const baja = (nodo: unknown, ruta: string): void => {
      if (Array.isArray(nodo)) {
        nodo.forEach((hijo, i) => baja(hijo, `${ruta}[${i}]`))
        return
      }
      if (!nodo || typeof nodo !== "object") return
      const objeto = nodo as JsonSchema
      if (objeto.column_role === "input" && escalarDeTexto(objeto)) {
        salida.push({ ruta, schema: objeto })
      }
      for (const [clave, hijo] of Object.entries(objeto)) baja(hijo, `${ruta}/${clave}`)
    }
    baja((fixtureSchema as unknown as SchemaPayload).json_schema, "")
    return salida
  }

  const SUELTAS = columnasSueltas()

  it("el barrido encuentra los ocho campos (si no, el gate estaría vacío)", () => {
    // Medido sobre el fixture real el 2026-08-02: `col` del predicado, `partition_col`, `date_col`,
    // `cohort_col`, `observation_date_col`, `data_cutoff_col`, `columns[].name` y
    // `stability.temporal_column`. Un gate que recorre cero campos da verde sin comprobar nada.
    expect(SUELTAS.length).toBeGreaterThanOrEqual(8)
  })

  it("ninguno se queda en caja de texto", () => {
    const aCiegas = SUELTAS.filter(
      ({ schema }) => resolveWidget(schema, { defs }) !== "column",
    ).map(({ ruta }) => ruta)
    expect(
      aCiegas,
      "Campos que nombran UNA columna del dataset y llegan al formulario como caja de texto: el " +
        "usuario tiene que escribir el nombre a ciegas y sin errata posible, teniendo el front las " +
        "columnas cargadas.",
    ).toEqual([])
  })

  it("todos ofrecen las columnas del dataset activo", () => {
    const sinOpciones = SUELTAS.filter(
      ({ schema }) =>
        columnOptions(schema, { datasetColumns: COLUMNAS }, defs).join() !== COLUMNAS.join(),
    ).map(({ ruta }) => ruta)
    expect(sinOpciones).toEqual([])
  })

  it("y sin dataset cargado no inventan ninguna", () => {
    // `[]` = «no hay lista que ofrecer» ⇒ entrada libre, que es el comportamiento de siempre. No
    // puede degradar a nada bloqueante: es el estado de arranque de toda sesión (D-JOB-2).
    for (const { ruta, schema } of SUELTAS) {
      expect(columnOptions(schema, {}, defs), ruta).toEqual([])
      expect(columnOptions(schema, { datasetColumns: [] }, defs), ruta).toEqual([])
    }
  })

  describe("anclas escritas a mano — el barrido no puede quedarse vacío en silencio", () => {
    it("`col` del predicado: el campo que motivó todo esto", () => {
      const col = (defs["data__Predicate"]?.properties ?? {})["col"]
      expect(col, "`data__Predicate.col` no está en el schema").toBeDefined()
      expect(columnRole(col, defs)).toBe("input")
      expect(resolveWidget(col, { defs })).toBe("column")
      expect(columnOptions(col, { datasetColumns: COLUMNAS }, defs)).toEqual(COLUMNAS)
    })

    it("`partition_col`, del que cuelgan las opciones de los otros tres campos", () => {
      const campo = (defs["data__ColumnSplitConfig"]?.properties ?? {})["partition_col"]
      expect(resolveWidget(campo, { defs })).toBe("column")
    })

    it("`data.schema.columns[].name`, la lista de columnas esperadas", () => {
      const campo = (defs["data__ColumnSpec"]?.properties ?? {})["name"]
      expect(resolveWidget(campo, { defs })).toBe("column")
    })

    it("`data_cutoff_col`, que es opcional y declara el rol POR FUERA del `anyOf`", () => {
      // La forma que se escapa de los tests escritos a mano: `{anyOf: [string, null],
      // column_role: …}`. Si `unwrapNullable` dejara de propagar el rol, aquí se cae.
      const campo = (defs["data__PerformanceWindow"]?.properties ?? {})["data_cutoff_col"]
      expect(campo?.anyOf, "el campo dejó de ser `X | None`").toBeDefined()
      expect(resolveWidget(campo, { defs })).toBe("column")
      expect(columnOptions(campo, { datasetColumns: COLUMNAS }, defs)).toEqual(COLUMNAS)
    })

    it("`stability.temporal_column`, el único que declara `ui_widget: text_input`", () => {
      // 🔴 El caso que obliga a que la regla gane sobre el alias. Sin esa precedencia este campo se
      // quedaba en caja de texto y los otros siete no, sin que nada lo delatara.
      const stability = (fixtureSchema as unknown as SchemaPayload).json_schema.properties
        ?.stability as JsonSchema
      const campo = ((stability.anyOf?.[0] as JsonSchema)?.properties ?? {})["temporal_column"]
      expect(campo?.ui_widget, "el campo dejó de declarar `ui_widget`").toBe("text_input")
      expect(resolveWidget(campo, { defs })).toBe("column")
    })
  })

  describe("controles negativos — a quién NO se le ofrecen columnas", () => {
    it("una variable DERIVADA no la ofrece: no existe antes de correr", () => {
      // `calibration.pd_raw_column` nombra una columna que PRODUCE un paso anterior, no una del
      // archivo. Ofrecerle las columnas del dataset sería ofrecer la lista equivocada.
      const calibration = (fixtureSchema as unknown as SchemaPayload).json_schema.properties
        ?.calibration as JsonSchema
      const campo = ((calibration.anyOf?.[0] as JsonSchema)?.properties ?? {})["pd_raw_column"]
      expect(columnRole(campo, defs)).toBe("derived")
      expect(resolveWidget(campo, { defs })).toBe("text")
      expect(columnOptions(campo, { datasetColumns: COLUMNAS }, defs)).toEqual([])
    })

    it("el ÍNDICE tampoco: por definición no está entre las columnas", () => {
      const campo = (defs["data__SchemaConfig"]?.properties ?? {})["index_col"]
      expect(columnRole(campo, defs)).toBe("index")
      expect(resolveWidget(campo, { defs })).not.toBe("column")
      expect(columnOptions(campo, { datasetColumns: COLUMNAS }, defs)).toEqual([])
    })

    it("un `enum` manda sobre el rol: si el schema cierra el dominio, se elige de él", () => {
      const cerrado: JsonSchema = {
        type: "string",
        column_role: "input",
        enum: ["a", "b"],
      }
      expect(isColumnField(cerrado, defs)).toBe(false)
      expect(resolveWidget(cerrado, { defs })).toBe("select")
    })

    it("un `ui_widget` que NO es caja de texto sigue mandando", () => {
      // La precedencia es estrecha a propósito: sólo se corrige el «esto se escribe». Un alias que
      // pida otro control pidió algo que no es una caja de texto, y se respeta.
      expect(
        resolveWidget({ type: "string", column_role: "input", ui_widget: "selectbox" }, { defs }),
      ).toBe("select")
      // …y `hidden` gana a todo, que es la única decisión que dice «no pintes esto».
      expect(
        resolveWidget({ type: "string", column_role: "input", ui_widget: "hidden" }, { defs }),
      ).toBe("hidden")
    })

    it("una LISTA de columnas sigue siendo multiselect, no `column`", () => {
      // El caso plural ya estaba resuelto; la rama nueva no puede robárselo.
      const uniqueKeys = (defs["data__SchemaConfig"]?.properties ?? {})["unique_keys"]
      expect(resolveWidget(uniqueKeys, { defs })).toBe("multiselect")
      expect(isColumnField(uniqueKeys, defs)).toBe(false)
    })

    it("la lista NO es cerrada: siempre se puede escribir un nombre que no salga", () => {
      // Es la mitad que importa del contrato: el dataset puede no estar cargado, o el usuario puede
      // estar describiendo un archivo que todavía no ha subido.
      for (const { ruta, schema } of SUELTAS) {
        expect(hasClosedOptions(schema, defs), ruta).toBe(false)
      }
    })

    it("y un valor fuera de la lista SÍ se puede acusar, porque las columnas se publican todas", () => {
      // La diferencia con `column_values_from`, donde acusar sería falso: de los valores de una
      // columna sólo se publica el top-20, pero de las columnas se publican todas.
      const col = (defs["data__Predicate"]?.properties ?? {})["col"]
      expect(optionsFromDataset(col, defs)).toBe(true)
    })
  })
})

describe("guardrail estático: el campo de columna no pierde el `id` ni borra lo escrito", () => {
  // Vitest corre sin DOM, así que el render no se puede probar; se vigila el FUENTE, igual que el
  // guardrail de propagación del catálogo. Lo que se protege son las dos propiedades que ningún
  // test de lógica alcanza: que el control siga siendo el `<input>` con el `id` del path —al que
  // salta el aviso del preflight (`controlVisible`)— y que elegir una columna ESCRIBA la columna,
  // nunca vacíe el campo.
  const codigo = fieldRendererSource
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((l) => !l.trimStart().startsWith("//"))
    .join("\n")
  const cuerpo = codigo.slice(
    codigo.indexOf("function ColumnField"),
    codigo.indexOf("function TextareaField"),
  )

  it("el widget existe y está enrutado", () => {
    expect(cuerpo.length, "`ColumnField` no está en el fuente").toBeGreaterThan(0)
    expect(codigo).toMatch(/case "column":\s*\n?\s*return <ColumnField \{\.\.\.props\} \/>/)
  })

  it("el control del path sigue siendo un `<input>` con el `id` del campo", () => {
    // Si esto se convirtiera en un `Select`, el `id` pasaría a un `button` y el salto del preflight
    // dejaría de enfocar el campo — que es el defecto que `candidateFieldIds` existe para evitar.
    expect(cuerpo).toMatch(/<Input\b[\s\S]*?id=\{id\}/)
    expect(cuerpo).toMatch(/const id = path\.join\("\."\)/)
  })

  it("elegir una columna la escribe, y nada la borra", () => {
    expect(cuerpo).toMatch(/onClick=\{\(\) => onChange\(path, columna\)\}/)
    // Ningún camino escribe vacío ni descarta el valor por no estar entre las opciones: es el
    // defecto que ya se pagó con `toggleMultiselect`.
    expect(cuerpo).not.toMatch(/onChange\(path, ""\)/)
    expect(cuerpo).not.toMatch(/onChange\(path, undefined\)/)
  })

  it("el gate caza lo que promete", () => {
    // Anclas del detector contra el texto exacto de los defectos que vigila.
    const conSelect = `<SelectTrigger id={id} className="w-full">`
    expect(/<Input\b[\s\S]*?id=\{id\}/.test(conSelect)).toBe(false)
    const queBorra = `onChange(path, "")`
    expect(/onChange\(path, ""\)/.test(queBorra)).toBe(true)
  })
})
