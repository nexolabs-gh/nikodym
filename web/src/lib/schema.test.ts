/**
 * Tests de la lectura del schema de configuración: qué secciones trae un payload y en qué forma.
 *
 * Esta lógica vivía dentro de `ConfigTab.tsx`, donde ningún test la alcanzaba (`web/src/components/`
 * no tiene ni un `*.test.tsx`). Vive aquí como función pura precisamente por eso: un formulario que
 * se pinta vacío no lo caza ningún gate automático, así que la parte que SÍ se puede probar se saca
 * del componente.
 */

import { describe, expect, it } from "vitest"

import {
  CONFIG_SECTIONS,
  FIXTURE_SCHEMA,
  configSectionSchema,
  f1SectionsRenderable,
} from "@/lib/schema"
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

describe("CONFIG_SECTIONS (catálogo navegable)", () => {
  it("no repite claves", () => {
    const claves = CONFIG_SECTIONS.map((s) => s.key)
    expect(new Set(claves).size).toBe(claves.length)
  })

  it("toda sección del catálogo existe en el schema y se puede pintar", () => {
    // El catálogo declara la intención; el schema decide. Una clave que no exista ahí sería un
    // ítem de sidebar que sólo sabe decir «no está disponible».
    const huerfanas = CONFIG_SECTIONS.filter(
      (s) => configSectionSchema(FIXTURE_SCHEMA, s.key) === null,
    ).map((s) => s.key)
    expect(huerfanas).toEqual([])
  })

  it("toda sección del catálogo está en el section_order del backend", () => {
    const orden = new Set(FIXTURE_SCHEMA.section_order)
    expect(CONFIG_SECTIONS.filter((s) => !orden.has(s.key)).map((s) => s.key)).toEqual([])
  })

  it("cubre las cinco secciones que la paridad UI↔código exigía", () => {
    const claves = new Set(CONFIG_SECTIONS.map((s) => s.key))
    for (const nueva of [
      "survival",
      "provisioning",
      "provisioning_cmf",
      "provisioning_ifrs9",
      "provisioning_internal",
    ]) {
      expect(claves.has(nueva)).toBe(true)
    }
  })
})

describe("el fixture del schema (contrato con el backend)", () => {
  const secciones = CONFIG_SECTIONS.map((s) => s.key)

  it.each(secciones)("«%s» trae campos y declara que se puede apagar", (seccion) => {
    const entry = configSectionSchema(FIXTURE_SCHEMA, seccion)
    expect(entry).not.toBeNull()
    expect(Object.keys(entry?.schema.properties ?? {}).length).toBeGreaterThan(0)
    // La mitad que se perdía al empotrar: sin rama nula el formulario no puede apagar la sección.
    expect(entry?.nullable).toBe(true)
  })

  it("no reexporta aliases de compatibilidad ni Markov reservado", () => {
    const root = FIXTURE_SCHEMA.json_schema
    const properties = root.properties ?? {}
    const section = (key: string) =>
      (properties[key]?.anyOf?.[0]?.properties ?? {}) as Record<
        string,
        { const?: unknown; enum?: unknown[]; items?: { enum?: unknown[] } }
      >
    const values = (key: string, field: string) => {
      const node = section(key)[field]
      return node?.items?.enum ?? node?.enum ?? (node?.const === undefined ? [] : [node.const])
    }

    expect(values("model", "engine")).toEqual(["logit"])
    expect(values("selection", "priority_order")).not.toContain("gini")
    expect(values("report", "formats")).not.toContain("html")

    const markov = root.$defs?.["markov__MarkovDynamicsConfig"]?.properties ?? {}
    expect(markov.projection_mode?.enum).not.toContain("period_matrices")
  })
})
