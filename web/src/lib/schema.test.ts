/**
 * Tests de la lectura del schema de configuración: qué secciones trae un payload y en qué forma.
 *
 * Esta lógica vivía dentro de `ConfigTab.tsx`, donde ningún test la alcanzaba (`web/src/components/`
 * no tiene ni un `*.test.tsx`). Vive aquí como función pura precisamente por eso: un formulario que
 * se pinta vacío no lo caza ningún gate automático, así que la parte que SÍ se puede probar se saca
 * del componente.
 */

import { describe, expect, it } from "vitest"

import { FIXTURE_SCHEMA, configSectionSchema, f1SectionsRenderable } from "@/lib/schema"
import type { SchemaPayload } from "@/lib/schema"

/** Payload mínimo con las secciones dadas, para probar formas concretas del nodo. */
function payloadCon(properties: Record<string, unknown>): SchemaPayload {
  return {
    json_schema: { properties } as SchemaPayload["json_schema"],
    defaults: {},
    section_order: Object.keys(properties),
  }
}

const OBJETO = { type: "object", properties: { a: { type: "string" } } }

describe("configSectionSchema", () => {
  it("desenvuelve una sección apagable y reporta que se puede apagar", () => {
    // La forma real que emite el backend: el campo es `Any` con `default=None`, así que la unión
    // es lo único que declara la nulabilidad.
    const payload = payloadCon({
      binning: { anyOf: [OBJETO, { type: "null" }], default: null, title: "Binning" },
    })
    expect(configSectionSchema(payload, "binning")).toEqual({
      schema: OBJETO,
      nullable: true,
    })
  })

  it("acepta una sección objeto plana, sin rama nula", () => {
    const payload = payloadCon({ binning: OBJETO })
    expect(configSectionSchema(payload, "binning")).toEqual({
      schema: OBJETO,
      nullable: false,
    })
  })

  it("null para una sección opaca (su extra no está instalado)", () => {
    // Lo que Pydantic emite para un campo `Any` sin expandir: ni campos ni unión.
    const payload = payloadCon({ markov: { default: null, title: "Markov" } })
    expect(configSectionSchema(payload, "markov")).toBeNull()
  })

  it("null para una sección ausente del schema", () => {
    expect(configSectionSchema(payloadCon({}), "binning")).toBeNull()
  })

  it("null si la unión trae una rama-objeto vacía (no un formulario)", () => {
    // Sin esto, `f1SectionsRenderable` daría verde por el mero `anyOf` y la app se quedaría con un
    // schema degradado creyendo que el backend respondió bien.
    const payload = payloadCon({
      binning: { anyOf: [{ title: "nada" }, { type: "null" }], default: null },
    })
    expect(configSectionSchema(payload, "binning")).toBeNull()
  })
})

describe("f1SectionsRenderable", () => {
  it("verde sobre el fixture real: las secciones llegan expandidas", () => {
    expect(f1SectionsRenderable(FIXTURE_SCHEMA)).toBe(true)
  })

  it("rojo si todas llegaron opacas", () => {
    const opaco = payloadCon({
      data: { default: null },
      binning: { default: null },
      selection: { default: null },
      model: { default: null },
      scorecard: { default: null },
      calibration: { default: null },
      performance: { default: null },
    })
    expect(f1SectionsRenderable(opaco)).toBe(false)
  })
})

describe("el fixture del schema (contrato con el backend)", () => {
  const secciones = [
    "data",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "survival",
    "provisioning",
    "provisioning_cmf",
    "provisioning_ifrs9",
    "provisioning_internal",
  ]

  it.each(secciones)("«%s» trae campos y declara que se puede apagar", (seccion) => {
    const entry = configSectionSchema(FIXTURE_SCHEMA, seccion)
    expect(entry).not.toBeNull()
    expect(Object.keys(entry?.schema.properties ?? {}).length).toBeGreaterThan(0)
    // La mitad que se perdía al empotrar: sin rama nula el formulario no puede apagar la sección.
    expect(entry?.nullable).toBe(true)
  })
})
