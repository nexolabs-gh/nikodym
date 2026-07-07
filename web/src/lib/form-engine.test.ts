import { describe, expect, it } from "vitest"

import {
  type Defs,
  type JsonSchema,
  defaultForSchema,
  discriminatedBranches,
  discriminatorProperty,
  enumOptions,
  fieldLabel,
  hasBothBounds,
  multiselectOptions,
  numericBounds,
  orderedFields,
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
})
