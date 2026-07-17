import { describe, expect, it } from "vitest"

import { cleanPresetName, presetDisplay } from "@/lib/presentation"

/**
 * Capa de presentación de los presets de la demo (IBK-03). Cubre los defectos que el grid dejaba
 * pasar en verde: el título de F1 con «estándar» en medio (que el regex viejo NO limpiaba), la
 * garantía derivada de un dato estructurado (no de un substring de la prosa) y el copy por área
 * sin insinuar un máximo entre CMF e IFRS 9. Los nombres/descripciones crudos replican los
 * `preset*.json` verbatim (no se tocan los fixtures).
 */

// Nombres crudos, tal como viven en los fixtures preset*.json.
const F1 = {
  id: "f1-estandar-consumo",
  name: "Preset estándar F1 — consumo (comportamiento)",
  description:
    "Config F1 completo y curado, listo para correr sin tocar nada: scorecard de comportamiento.",
}
const F3 = {
  id: "f3-provisiones-consumo",
  name: "Preset F3 — provisiones consumo (CMF + método interno)",
  description:
    "Config completo listo para correr: el scorecard F1 y, encima, las provisiones que la norma chilena exige.",
}
const F4 = {
  id: "f4-ifrs9-retail",
  name: "Preset F4 — provisiones IFRS 9 / ECL (retail multi-cartera)",
  description:
    "Config listo para correr sin scorecard de por medio. IFRS 9 es experimental (SDD-16, fuera de la garantía SemVer 1.x).",
}

describe("presetDisplay (títulos por área)", () => {
  it("F1 → «Scorecard de comportamiento», estable (aunque el nombre crudo mete «estándar»)", () => {
    const d = presetDisplay(F1)
    expect(d.title).toBe("Scorecard de comportamiento")
    expect(d.garantia).toBe("estable")
    // El título curado NO arrastra la jerga de repo del nombre crudo.
    expect(d.title).not.toContain("Preset")
    expect(d.title).not.toContain("F1")
  })

  it("F3 → «CMF vs. método interno», experimental", () => {
    const d = presetDisplay(F3)
    expect(d.title).toBe("CMF vs. método interno")
    expect(d.garantia).toBe("experimental")
  })

  it("F4 → «IFRS 9 / ECL retail», experimental", () => {
    const d = presetDisplay(F4)
    expect(d.title).toBe("IFRS 9 / ECL retail")
    expect(d.garantia).toBe("experimental")
  })

  it("los tres títulos salen limpios y del mapa curado (no del nombre crudo)", () => {
    for (const p of [F1, F3, F4]) {
      const d = presetDisplay(p)
      expect(d.title.length).toBeGreaterThan(0)
      expect(d.title).not.toMatch(/^Preset\s/i)
      expect(d.blurb.length).toBeGreaterThan(0)
    }
  })
})

describe("presetDisplay (encuadre regulatorio LatAm)", () => {
  it("el blurb de F3 enmarca el máximo como estándar-CMF vs. interno, NUNCA CMF vs. IFRS 9", () => {
    const { blurb } = presetDisplay(F3)
    expect(blurb).toContain("método estándar de la CMF")
    expect(blurb).toContain("método interno")
    expect(blurb).toContain("por institución")
    // No insinúa un máximo entre marcos: IFRS 9 no aparece en la provisión CMF.
    expect(blurb).not.toContain("IFRS")
    // El único rótulo de país legítimo es el de CMF.
    expect(blurb).toContain("Chile")
  })

  it("el blurb de F4 (IFRS 9) es genérico LatAm y marco separado de la CMF", () => {
    const { blurb } = presetDisplay(F4)
    expect(blurb).toContain("IFRS 9")
    expect(blurb).toContain("LatAm")
    expect(blurb).toContain("separado de la CMF")
    // IFRS 9 no se rotula por país.
    expect(blurb).not.toContain("Chile")
  })

  it("ningún blurb promete el extra inexistente nikodym[markov]", () => {
    for (const p of [F1, F3, F4]) {
      expect(presetDisplay(p).blurb.toLowerCase()).not.toContain("markov")
    }
  })
})

describe("fallback para presets no curados (backend real / futuros)", () => {
  it("limpia el prefijo de jerga y deriva la garantía de la descripción", () => {
    const otro = {
      id: "preset-futuro-x",
      name: "Preset F9 — algo nuevo",
      description: "Un dominio nuevo, marcado experimental por ahora.",
    }
    const d = presetDisplay(otro)
    expect(d.title).toBe("Algo nuevo")
    expect(d.garantia).toBe("experimental")
    expect(d.blurb).toBe(otro.description)
  })

  it("cleanPresetName admite un token entre «Preset» y «F#» (el caso que el regex viejo fallaba)", () => {
    expect(cleanPresetName("Preset estándar F1 — consumo (comportamiento)")).toBe(
      "Consumo (comportamiento)",
    )
    expect(cleanPresetName("Preset F3 — provisiones consumo")).toBe(
      "Provisiones consumo",
    )
    // Sin prefijo reconocible, deja el nombre (capitalizado).
    expect(cleanPresetName("dominio suelto")).toBe("Dominio suelto")
  })
})
