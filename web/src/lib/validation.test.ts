import { describe, expect, it } from "vitest"

import {
  buildErrorLookup,
  describeApiError,
  errorAtPath,
  pathKey,
} from "./validation"

describe("pathKey", () => {
  it("une los segmentos con punto (misma clave para loc y path)", () => {
    expect(pathKey(["data", "load", "source"])).toBe("data.load.source")
  })

  it("conserva los índices numéricos de listas", () => {
    expect(pathKey(["binning", "rules", 2, "field"])).toBe(
      "binning.rules.2.field",
    )
  })

  it("segmentos vacíos ⇒ string vacío", () => {
    expect(pathKey([])).toBe("")
  })
})

describe("buildErrorLookup", () => {
  it("indexa cada error por pathKey(loc)", () => {
    const lookup = buildErrorLookup([
      { loc: ["binning", "min_iv"], msg: "debe ser ≥ 0", type: "greater_than" },
      { loc: ["model", "type"], msg: "tag desconocido", type: "union_tag" },
    ])
    expect(lookup.get("binning.min_iv")).toBe("debe ser ≥ 0")
    expect(lookup.get("model.type")).toBe("tag desconocido")
    expect(lookup.size).toBe(2)
  })

  it("concatena varios errores del mismo loc en orden", () => {
    const lookup = buildErrorLookup([
      { loc: ["data", "target"], msg: "requerido", type: "missing" },
      { loc: ["data", "target"], msg: "no puede ser vacío", type: "value_error" },
    ])
    expect(lookup.get("data.target")).toBe("requerido · no puede ser vacío")
  })

  it("lista vacía ⇒ lookup vacío", () => {
    expect(buildErrorLookup([]).size).toBe(0)
  })
})

describe("errorAtPath", () => {
  const lookup = buildErrorLookup([
    { loc: ["binning", "min_iv"], msg: "fuera de rango", type: "greater_than" },
  ])

  it("devuelve el msg cuando el path matchea un loc", () => {
    expect(errorAtPath(lookup, ["binning", "min_iv"])).toBe("fuera de rango")
  })

  it("devuelve undefined cuando no matchea", () => {
    expect(errorAtPath(lookup, ["binning", "max_bins"])).toBeUndefined()
  })

  it("lookup ausente ⇒ undefined (sin crashear)", () => {
    expect(errorAtPath(undefined, ["binning", "min_iv"])).toBeUndefined()
  })
})

describe("describeApiError (422 de los endpoints YAML)", () => {
  it("detail string (mensaje del motor) ⇒ se devuelve tal cual", () => {
    const body = { detail: "el schema_version 0 no soporta migración" }
    expect(describeApiError(body, "fallback")).toBe(
      "el schema_version 0 no soporta migración",
    )
  })

  it("detail lista [{loc,msg}] ⇒ se formatea loc: msg por línea", () => {
    const body = {
      detail: [
        { loc: ["binning", "min_iv"], msg: "debe ser ≥ 0", type: "greater_than" },
        { loc: ["model"], msg: "requerido", type: "missing" },
      ],
    }
    expect(describeApiError(body, "fallback")).toBe(
      "binning.min_iv: debe ser ≥ 0; model: requerido",
    )
  })

  it("cuerpo no reconocido ⇒ fallback", () => {
    expect(describeApiError(null, "fallback")).toBe("fallback")
    expect(describeApiError({ detail: [] }, "fallback")).toBe("fallback")
    expect(describeApiError({ other: 1 }, "fallback")).toBe("fallback")
  })
})
