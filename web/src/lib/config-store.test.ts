import { describe, expect, it } from "vitest"

import {
  getAtPath,
  parseJsonInput,
  removeAtPath,
  setAtPath,
} from "./config-store"

describe("setAtPath (inmutable)", () => {
  it("fija un valor anidado sin mutar el original", () => {
    const original = { data: { load: { source: "a.csv" } } }
    const next = setAtPath(original, ["data", "load", "source"], "b.parquet")
    expect(next).toEqual({ data: { load: { source: "b.parquet" } } })
    expect(original.data.load.source).toBe("a.csv") // intacto
    expect(next).not.toBe(original)
    expect(next.data).not.toBe(original.data)
  })

  it("crea contenedores intermedios que faltan", () => {
    const next = setAtPath({}, ["binning", "min_iv"], 0.02)
    expect(next).toEqual({ binning: { min_iv: 0.02 } })
  })

  it("parte desde null/undefined creando el objeto", () => {
    const next = setAtPath(
      { data: null } as Record<string, unknown>,
      ["data", "type"],
      "standard",
    )
    expect(next).toEqual({ data: { type: "standard" } })
  })

  it("soporta índices numéricos (arrays)", () => {
    const next = setAtPath({ cols: ["a", "b"] }, ["cols", 1], "z")
    expect(next).toEqual({ cols: ["a", "z"] })
  })

  it("path vacío reemplaza la raíz", () => {
    expect(setAtPath({ a: 1 }, [], { b: 2 })).toEqual({ b: 2 })
  })
})

describe("getAtPath", () => {
  it("lee un valor anidado", () => {
    expect(getAtPath({ a: { b: { c: 3 } } }, ["a", "b", "c"])).toBe(3)
  })

  it("devuelve undefined si un tramo no existe", () => {
    expect(getAtPath({ a: {} }, ["a", "b", "c"])).toBeUndefined()
    expect(getAtPath(null, ["a"])).toBeUndefined()
  })

  it("lee índices de array", () => {
    expect(getAtPath({ cols: ["x", "y"] }, ["cols", 0])).toBe("x")
  })
})

describe("removeAtPath (inmutable)", () => {
  it("borra la clave anidada sin mutar el original", () => {
    const original = { data: { load: { source: "a.csv", extra: 1 } } }
    const next = removeAtPath(original, ["data", "load", "extra"])
    expect(next).toEqual({ data: { load: { source: "a.csv" } } })
    expect(original.data.load.extra).toBe(1) // intacto
    expect(next.data).not.toBe(original.data)
  })

  it("borra una clave de nivel superior", () => {
    expect(removeAtPath({ a: 1, b: 2 }, ["b"])).toEqual({ a: 1 })
  })

  it("no crea claves cuando un tramo no existe", () => {
    const original = { a: {} }
    const next = removeAtPath(original, ["a", "b", "c"])
    expect(next).toEqual({ a: {} })
    expect("b" in (next.a as Record<string, unknown>)).toBe(false)
  })

  it("elimina un elemento de array por índice", () => {
    expect(removeAtPath({ cols: ["a", "b", "c"] }, ["cols", 1])).toEqual({
      cols: ["a", "c"],
    })
  })

  it("índice fuera de rango → sin cambios", () => {
    const original = { cols: ["a"] }
    expect(removeAtPath(original, ["cols", 5])).toEqual({ cols: ["a"] })
  })

  it("path vacío → sin cambios", () => {
    const original = { a: 1 }
    expect(removeAtPath(original, [])).toBe(original)
  })
})

describe("parseJsonInput (editor JSON fallback §5/§8)", () => {
  it("parsea JSON válido y devuelve el valor", () => {
    expect(parseJsonInput('{"a": [1, 2], "b": "x"}')).toEqual({
      ok: true,
      value: { a: [1, 2], b: "x" },
    })
  })

  it("texto vacío ⇒ null (sección sin valor), no error", () => {
    expect(parseJsonInput("   ")).toEqual({ ok: true, value: null })
  })

  it("JSON inválido ⇒ ok:false con mensaje de sintaxis", () => {
    const result = parseJsonInput("{ no es json ")
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error.length).toBeGreaterThan(0)
  })
})
