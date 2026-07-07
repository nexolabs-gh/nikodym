import { describe, expect, it } from "vitest"

import {
  type Defs,
  type JsonSchema,
  enumOptions,
  fieldLabel,
  hasBothBounds,
  numericBounds,
  orderedFields,
  resolveRef,
  resolveWidget,
  schemaType,
  unwrapNullable,
} from "./form-engine"

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
