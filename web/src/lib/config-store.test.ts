import { describe, expect, it } from "vitest"

import { getAtPath, setAtPath } from "./config-store"

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
