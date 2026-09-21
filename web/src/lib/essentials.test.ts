/**
 * Esenciales abiertos y «Avanzado» plegado (SDD-31 D-SIM-4; enmienda FLUJO-GUIADO D-FLU-8).
 *
 * Tres cosas se prueban aquí, sin DOM: (1) el golden del front es el espejo de las marcas del
 * schema que el backend publica —en los dos sentidos, como el golden de Python—; (2) la división
 * de una sección en sus dos vistas es exacta: cada hoja marcada va a esenciales y sólo ahí, el
 * resto a «Avanzado» y sólo ahí, los `hidden` a ninguna, y un sub-modelo que queda entero viaja
 * sin copiar; (3) la cifra del bloque plegado cuenta lo que difiere de fábrica y nada más. Que
 * el bloque se pinte cerrado, se abra con el clic y con un error dentro se comprueba en la UI
 * viva (vitest corre sin DOM), más el guardrail estático de `ConfigTab.test.ts`.
 */

import { describe, expect, it } from "vitest"

import fixtureSchema from "@/fixtures/schema.json"
import type { EffectiveDefaults } from "@/lib/effective-defaults"
import {
  AVANZADO,
  ESSENTIALS_BY_SECTION,
  advancedLeaves,
  advancedSchema,
  advancedSummary,
  countChangedAdvanced,
  declaresEssentials,
  differsFromDefault,
  errorsInsideAdvanced,
  essentialFields,
  essentialPaths,
  hasEssentialInside,
  insideAdvanced,
  pruneForView,
} from "@/lib/essentials"
import { type Defs, type JsonSchema, groupedFields, orderedFields, resolveRef } from "@/lib/form-engine"
import { type SchemaPayload, configSectionSchema } from "@/lib/schema"

const PAYLOAD = fixtureSchema as unknown as SchemaPayload
const DEFS: Defs = PAYLOAD.json_schema.$defs ?? {}
const CATALOGO = PAYLOAD.effective_defaults as EffectiveDefaults

/** La rama con campos de una sección del fixture, resuelta como la resuelve `ConfigTab`. */
function seccion(clave: string): JsonSchema {
  const entrada = configSectionSchema(PAYLOAD, clave)
  if (!entrada) throw new Error(`el fixture no trae la sección ${clave}`)
  return resolveRef(entrada.schema, DEFS)
}

/** Todas las hojas (paths) de un schema, bajando por sub-modelos; uniones y listas son hojas. */
function hojas(schema: JsonSchema, prefijo: string): string[] {
  const out: string[] = []
  for (const [name, child] of orderedFields(schema)) {
    const path = `${prefijo}.${name}`
    const target = resolveRef(child, DEFS)
    const variants = (target.anyOf ?? target.oneOf ?? []).filter((v) => v.type !== "null")
    const branch = variants.length === 1 ? resolveRef(variants[0], DEFS) : target
    if (branch.properties && variants.length <= 1 && branch.items === undefined) {
      out.push(...hojas(branch, path))
    } else {
      out.push(path)
    }
  }
  return out
}

describe("golden espejo: las marcas del schema son exactamente las del golden (D-FLU-7)", () => {
  it("las doce secciones del scorecard declaran sus esenciales, y ninguna otra", () => {
    const declaradas = Object.keys(PAYLOAD.json_schema.properties ?? {}).filter((clave) => {
      const entrada = configSectionSchema(PAYLOAD, clave)
      return entrada !== null && declaresEssentials(resolveRef(entrada.schema, DEFS))
    })
    expect(new Set(declaradas)).toEqual(new Set(Object.keys(ESSENTIALS_BY_SECTION)))
    expect(declaradas).toHaveLength(12)
  })

  it.each(Object.keys(ESSENTIALS_BY_SECTION))(
    "%s: cada marca está en el golden y cada entrada del golden está marcada",
    (clave) => {
      const marcadas = essentialPaths(seccion(clave), DEFS, clave)
      expect([...marcadas].sort()).toEqual([...ESSENTIALS_BY_SECTION[clave]].sort())
    },
  )

  it("una sección fuera del scorecard no declara esenciales y no se divide", () => {
    const survival = configSectionSchema(PAYLOAD, "survival")
    expect(survival).not.toBeNull()
    const schema = resolveRef(survival!.schema, DEFS)
    expect(declaresEssentials(schema)).toBe(false)
    expect(essentialPaths(schema, DEFS, "survival").size).toBe(0)
  })
})

describe("la división de una sección es exacta y no pierde ni duplica campos", () => {
  it.each(Object.keys(ESSENTIALS_BY_SECTION))("%s", (clave) => {
    const schema = seccion(clave)
    const esenciales = essentialFields(schema, DEFS)
    const avanzado = advancedSchema(schema, DEFS)
    const abiertas = esenciales.flatMap(([name, part]) => hojas({ properties: { [name]: part } }, clave))
    const plegadas = avanzado ? hojas(avanzado, clave) : []
    const todas = hojas(schema, clave)
    // Ninguna hoja en las dos vistas, ninguna perdida: la unión es el formulario entero.
    expect(abiertas.filter((p) => plegadas.includes(p))).toEqual([])
    expect([...abiertas, ...plegadas].sort()).toEqual(todas.sort())
    // Cada marca está cubierta por una hoja abierta (la misma, una hoja dentro de un sub-modelo
    // marcado entero como `bad_rule`, o la unión/lista atómica que la contiene); y toda hoja
    // abierta se explica por una marca.
    const cubre = (hoja: string, marca: string) =>
      hoja === marca || hoja.startsWith(`${marca}.`) || marca.startsWith(`${hoja}.`)
    for (const marcada of ESSENTIALS_BY_SECTION[clave]) {
      expect(abiertas.some((p) => cubre(p, marcada)), `${marcada} no está abierta`).toBe(true)
    }
    for (const abierta of abiertas) {
      const esMarca = ESSENTIALS_BY_SECTION[clave].some((m) => cubre(abierta, m))
      expect(esMarca, `${abierta} está abierta sin marca`).toBe(true)
    }
    for (const plegada of plegadas) {
      expect(ESSENTIALS_BY_SECTION[clave]).not.toContain(plegada)
    }
  })

  it("los esenciales visibles a la vez respetan el tope de 6 y suman 35 (cifra 2)", () => {
    // La estrategia de partición es UNA unión atómica: cuenta como un campo abierto aunque su
    // rama más cargada pinte cuatro esenciales; el golden de Python cuenta por rama (6 en data).
    let total = 0
    for (const clave of Object.keys(ESSENTIALS_BY_SECTION)) {
      const marcas = essentialPaths(seccion(clave), DEFS, clave)
      const porRama =
        clave === "data"
          ? marcas.size - 2 // `date_col`/`oot_from` y `cohort_col`/`oot_cohorts` no coinciden
          : marcas.size
      expect(porRama).toBeLessThanOrEqual(6)
      total += porRama
    }
    expect(total).toBe(35)
  })

  it("eda declara cero esenciales: nada abierto y todo plegado", () => {
    const schema = seccion("eda")
    expect(essentialFields(schema, DEFS)).toEqual([])
    const avanzado = advancedSchema(schema, DEFS)
    expect(avanzado).not.toBeNull()
    expect(groupedFields(avanzado!).flatMap((g) => g.fields).length).toBe(
      groupedFields(schema).flatMap((g) => g.fields).length,
    )
  })

  it("un sub-modelo con marcas dentro se poda en cada vista y conserva el título y el grupo", () => {
    const report = seccion("report")
    const abiertos = Object.fromEntries(essentialFields(report, DEFS))
    const documento = abiertos.document
    expect(documento).toBeDefined()
    const declarado = (report.properties ?? {}).document
    // Las claves del CAMPO declarado (grupo, orden, ayuda, título) viajan con la copia: sin ellas
    // el sub-modelo podado caería al grupo «General» y perdería su tooltip.
    for (const clave of ["ui_group", "ui_order", "ui_help", "title"] as const) {
      if (declarado[clave] !== undefined) expect(documento[clave]).toBe(declarado[clave])
    }
    expect(declarado.ui_group ?? declarado.ui_order ?? declarado.ui_help).toBeDefined()
    expect(documento.$ref).toBeUndefined() // copia inline: sólo sus hojas marcadas
    expect(Object.keys(documento.properties ?? {}).sort()).toEqual([
      "author",
      "entity",
      "model_name",
      "portfolio",
    ])
    const plegado = advancedSchema(report, DEFS)!
    const restoDocumento = (plegado.properties ?? {}).document
    expect(restoDocumento).toBeDefined()
    expect(Object.keys(restoDocumento.properties ?? {})).not.toContain("author")
  })

  it("un sub-modelo que queda entero en una vista viaja SIN copiar (conserva su $ref)", () => {
    const data = seccion("data")
    const plegado = advancedSchema(data, DEFS)!
    const missing = (plegado.properties ?? {}).missing
    expect(missing).toBe((data.properties ?? {}).missing)
  })

  it("una unión discriminada con una marca dentro es atómica: entera en esenciales", () => {
    const data = seccion("data")
    const abiertos = Object.fromEntries(essentialFields(data, DEFS))
    const particion = abiertos.partition
    expect(particion).toBeDefined()
    expect(Object.keys(particion.properties ?? {})).toEqual(["strategy"])
    const strategy = resolveRef((particion.properties ?? {}).strategy, DEFS)
    expect(strategy.anyOf ?? strategy.oneOf).toBeDefined()
    const plegado = advancedSchema(data, DEFS)!
    expect(Object.keys((plegado.properties ?? {}).partition.properties ?? {}).sort()).toEqual([
      "min_bads_per_partition",
      "ttd_includes_excluded",
    ])
  })

  it("un campo hidden no va a ninguna vista y no rompe la copia", () => {
    const campo: JsonSchema = {
      type: "object",
      properties: {
        type: { type: "string", ui_widget: "hidden" },
        a: { type: "number", ui_essential: true },
        b: { type: "number" },
      },
    }
    expect(pruneForView(campo, {}, "essential")?.properties).toEqual({
      a: { type: "number", ui_essential: true },
    })
    expect(pruneForView(campo, {}, "advanced")?.properties).toEqual({ b: { type: "number" } })
    expect(hasEssentialInside(campo, {})).toBe(true)
    expect(pruneForView({ type: "number", ui_widget: "hidden" }, {}, "advanced")).toBeNull()
  })

  it("un sub-modelo nulable podado sigue siendo nulable", () => {
    const campo: JsonSchema = {
      title: "Bloque",
      anyOf: [
        { type: "object", properties: { a: { type: "number", ui_essential: true }, b: { type: "number" } } },
        { type: "null" },
      ],
    }
    const abierto = pruneForView(campo, {}, "essential")!
    expect(abierto.anyOf?.[1]).toEqual({ type: "null" })
    expect(Object.keys(abierto.anyOf?.[0].properties ?? {})).toEqual(["a"])
    expect(abierto.title).toBe("Bloque")
  })
})

describe("la cifra de «Avanzado»: cuántos campos difieren de fábrica (D-FLU-8)", () => {
  it("un config sin claves no difiere en nada, y un valor igual al de fábrica tampoco", () => {
    const selection = seccion("selection")
    const hojas = advancedLeaves(advancedSchema(selection, DEFS), DEFS, ["selection"])
    expect(hojas.length).toBeGreaterThan(3)
    expect(countChangedAdvanced(hojas, {}, CATALOGO)).toBe(0)
    expect(
      countChangedAdvanced(hojas, { selection: { correlation: { method: "pearson" } } }, CATALOGO),
    ).toBe(0)
  })

  it("cuenta cada hoja plegada que difiere, y no un esencial cambiado", () => {
    const selection = seccion("selection")
    const hojas = advancedLeaves(advancedSchema(selection, DEFS), DEFS, ["selection"])
    const config = {
      selection: {
        min_iv: 0.5, // esencial: no cuenta
        correlation: { method: "spearman", threshold: 0.9 }, // `threshold` es esencial
        stability: { enabled: false },
      },
    }
    expect(countChangedAdvanced(hojas, config, CATALOGO)).toBe(2)
  })

  it("una lista y un null explícito son valores: `[]` no difiere de `[]`, `null` sí de un mapa", () => {
    expect(differsFromDefault([], { has_default: true, value: [] })).toBe(false)
    expect(differsFromDefault(null, { has_default: true, value: null })).toBe(false)
    expect(differsFromDefault(null, { a: { has_default: true, value: 1 } })).toBe(true)
    expect(differsFromDefault({ a: 1 }, { a: { has_default: true, value: 1 } })).toBe(false)
    expect(differsFromDefault(undefined, { has_default: true, value: 1 })).toBe(false)
    // Obligatoria sin default: escrita por el usuario ⇒ cambiada. Sin catálogo no se afirma nada.
    expect(differsFromDefault("x", { has_default: false })).toBe(true)
    expect(differsFromDefault("x", undefined)).toBe(false)
  })

  it("el ejemplo F1 del fixture cambia hojas plegadas en `data` y ninguna en `scorecard`", () => {
    // Las 14 hojas que el preset toca (medido en S16) se reparten entre esenciales y avanzadas;
    // aquí se ancla lo observable en pantalla sobre el catálogo bundleado con un config mínimo.
    const data = seccion("data")
    const hojasData = advancedLeaves(advancedSchema(data, DEFS), DEFS, ["data"])
    expect(
      countChangedAdvanced(
        hojasData,
        { data: { partition: { min_bads_per_partition: 10 }, missing: { max_missing_rate: 0.5 } } },
        CATALOGO,
      ),
    ).toBe(2)
    const scorecard = seccion("scorecard")
    const hojasScorecard = advancedLeaves(advancedSchema(scorecard, DEFS), DEFS, ["scorecard"])
    expect(countChangedAdvanced(hojasScorecard, { scorecard: { pdo: 30 } }, CATALOGO)).toBe(0)
  })

  it("el rótulo dice el número, en singular o plural, y los errores sólo si los hay", () => {
    expect(advancedSummary(0, 0)).toBe("sin cambios")
    expect(advancedSummary(1, 0)).toBe("1 campo cambiado")
    expect(advancedSummary(3, 0)).toBe("3 campos cambiados")
    expect(advancedSummary(0, 1)).toBe("sin cambios · 1 error")
    expect(advancedSummary(2, 2)).toBe("2 campos cambiados · 2 errores")
    expect(AVANZADO).toBe("Avanzado")
  })
})

describe("errores y foco dentro de «Avanzado»: lo que abre el bloque", () => {
  it("un error del backend en una hoja plegada (o dentro de ella) cuenta; uno esencial, no", () => {
    const data = seccion("data")
    const hojas = advancedLeaves(advancedSchema(data, DEFS), DEFS, ["data"])
    const errores = new Map<string, string>([
      ["data.schema.columns.0.name", "columna repetida"],
      ["data.partition.strategy.oot_from", "fecha ilegible"],
      ["data.load.source", "no existe"],
    ])
    expect(errorsInsideAdvanced(hojas, errores)).toBe(1)
    expect(errorsInsideAdvanced(hojas, undefined)).toBe(0)
  })

  it("un foco pedido con corchetes o con puntos cae en la misma hoja", () => {
    const data = seccion("data")
    const hojas = advancedLeaves(advancedSchema(data, DEFS), DEFS, ["data"])
    expect(insideAdvanced(hojas, "data.schema.columns[0].name")).toBe(true)
    expect(insideAdvanced(hojas, "data.schema.columns.0.name")).toBe(true)
    expect(insideAdvanced(hojas, "data.schema.unique_keys")).toBe(false)
    expect(insideAdvanced(hojas, "binning.max_n_prebins")).toBe(false)
  })
})
