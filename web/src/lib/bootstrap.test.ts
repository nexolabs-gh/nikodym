/**
 * Tests del ARRANQUE del workspace. Cubren tres cosas, y las tres tienen un defecto detrás:
 *
 *  (a) **D-JOB-2**: el build instalable arranca VACÍO —sin config sembrado y sin dataset— y ni
 *      siquiera pide el preset. La demo estática sigue sembrando (D-JOB-19), porque no tiene
 *      backend ni acepta datasets propios;
 *  (b) el gate de UX1, ahora sólo en la rama que siembra: el preset se siembra y valida sin abrir
 *      Configuración, y `canRun` abre con el dataset que trae el propio preset;
 *  (c) el bug hermano: el arranque ocurre UNA sola vez por sesión, así que volver a Configuración
 *      (que se desmonta al navegar) no puede pisar ni las ediciones del config ni el dataset
 *      que el usuario eligió o subió.
 *
 * El runner corre en entorno `node` (sin DOM: el proyecto no trae jsdom ni testing-library, y el
 * goal veta dependencias nuevas), así que se testea la LÓGICA del arranque con deps inyectadas —
 * que es donde vive el bug— más un guardrail estático de que `ConfigTab` ya no siembra.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"

// Los fuentes como texto (`?raw` de Vite) para los guardrails estáticos del final.
import configTabSource from "@/components/ConfigTab.tsx?raw"
import bootstrapSource from "@/lib/bootstrap.ts?raw"
import type { PresetResponse } from "@/lib/api"
import {
  bootstrapOnce,
  bootstrapWorkspace,
  configEditadoRespectoDelPreset,
  configFingerprint,
  resetBootstrapForTests,
  seedDatasetId,
  type BootstrapDeps,
} from "@/lib/bootstrap"
import type { LoadedSchema } from "@/lib/schema"
import { canRun } from "@/lib/validation"

const SCHEMA: LoadedSchema = {
  payload: {
    json_schema: { properties: { binning: { type: "object" } } },
    defaults: { binning: { min_prebin_size: 0.05 } },
    section_order: ["binning"],
  },
  source: "backend",
}

const PRESET: PresetResponse = {
  config: { binning: { min_prebin_size: 0.05 }, model: { type: "logit" } },
  config_hash: "f53ffc9f11eaac29",
  dataset_id: "consumo_comportamiento",
  name: "Scorecard de comportamiento",
  description: "Preset estándar F1.",
}

/** Deps del BUILD INSTALABLE: backend sano, pero el arranque no siembra nada (D-JOB-2). */
function okDeps(): BootstrapDeps {
  return {
    loadSchema: vi.fn(() => Promise.resolve(SCHEMA)),
    getPreset: vi.fn(() => Promise.resolve(PRESET)),
    sembrarAlArrancar: false,
  }
}

/** Deps de la DEMO ESTÁTICA: la única build que siembra al arrancar (D-JOB-19). */
function demoDeps(): BootstrapDeps {
  return { ...okDeps(), sembrarAlArrancar: true }
}

beforeEach(() => {
  resetBootstrapForTests() // cada test es una sesión nueva
})

describe("bootstrapWorkspace · build instalable: la sesión arranca VACÍA (D-JOB-2)", () => {
  it("no siembra config ni dataset, y ni siquiera pide el preset", async () => {
    const deps = okDeps()
    const outcome = await bootstrapWorkspace(deps)

    expect(outcome.config).toEqual(SCHEMA.payload.defaults)
    expect(outcome.config).not.toBe(SCHEMA.payload.defaults) // clon: editar no muta el schema
    expect(outcome.datasetId).toBeNull()
    expect(outcome.seed).toEqual({ kind: "empty" })
    // El aserto que da valor al test: no basta con descartar la respuesta del preset, hay que NO
    // preguntarla. Un arranque que igual la pide deja al instalable dependiendo del catálogo de
    // demos para abrir, y esa dependencia sería invisible salvo con el backend caído.
    expect(deps.getPreset).not.toHaveBeenCalled()
  })

  it("con el config vacío ya validado, el gate pide TUS DATOS y no una configuración", async () => {
    // Es el punto entero de D-JOB-2: la sesión abre pudiendo validar, y lo único que falta es el
    // archivo del usuario. Antes abría con el dataset sintético del preset ya elegido por nosotros.
    const outcome = await bootstrapWorkspace(okDeps())
    const validation = { kind: "valid", hash: "d0d0cafe", pipeline: null } as const

    expect(canRun(validation, outcome.datasetId)).toEqual({
      ok: false,
      reason: "Falta elegir dataset",
    })
  })

  it("`empty` no es «config editado»: no hay preset contra el cual comparar", () => {
    expect(configEditadoRespectoDelPreset({ kind: "empty" }, PRESET.config)).toBe(false)
  })
})

describe("bootstrapWorkspace · demo estática: sigue sembrando (D-JOB-19)", () => {
  it("siembra el config del preset y su dataset recomendado, sin abrir Configuración", async () => {
    const outcome = await bootstrapWorkspace(demoDeps())

    expect(outcome.config).toEqual(PRESET.config)
    expect(outcome.datasetId).toBe("consumo_comportamiento")
    expect(outcome.seed).toEqual({
      kind: "preset",
      name: "Scorecard de comportamiento",
      datasetId: "consumo_comportamiento",
      // La huella del config sembrado: con ella el selector de Ejecutar sabe después si lo que
      // hay es el preset o el trabajo del usuario.
      fingerprint: configFingerprint(PRESET.config),
    })
    expect(outcome.schema).toBe(SCHEMA)
  })

  it("con el preset sembrado y validado, el gate de Ejecutar ABRE sin tocar la configuración", async () => {
    // Réplica del arranque del provider: bootstrap → validación en vivo (el backend produce el
    // config_hash) → gate. Antes de UX1 esto solo ocurría si el usuario abría ConfigTab.
    const outcome = await bootstrapWorkspace(demoDeps())
    const validation = { kind: "valid", hash: PRESET.config_hash, pipeline: null } as const

    expect(canRun(validation, outcome.datasetId)).toEqual({ ok: true })
  })

  it("mientras la validación no termina, el gate bloquea con un motivo TRANSITORIO (no 'te falta config')", () => {
    expect(canRun({ kind: "idle" }, "consumo_comportamiento")).toEqual({
      ok: false,
      reason: "Preparando la configuración…",
    })
  })

  it("sin preset (backend caído) cae al config vacío del schema y NO inventa dataset", async () => {
    const deps: BootstrapDeps = {
      loadSchema: vi.fn(() => Promise.resolve(SCHEMA)),
      getPreset: vi.fn(() => Promise.reject(new Error("HTTP 500"))),
      sembrarAlArrancar: true,
    }
    const outcome = await bootstrapWorkspace(deps)

    expect(outcome.config).toEqual(SCHEMA.payload.defaults)
    expect(outcome.config).not.toBe(SCHEMA.payload.defaults) // clon: editar no muta el schema
    expect(outcome.datasetId).toBeNull()
    // `fallback` y no `empty`: la demo SÍ intentó sembrar y no pudo, que es un estado degradado
    // con su propio aviso. Colapsarlos escondería el backend caído tras la pantalla de arranque
    // normal del instalable.
    expect(outcome.seed).toEqual({ kind: "fallback" })
  })
})

describe("bootstrapOnce (un solo arranque por sesión)", () => {
  it("varias llamadas (remontajes, StrictMode) piden el preset UNA vez y devuelven el mismo arranque", async () => {
    const deps = demoDeps()

    const outcomes = await Promise.all([
      bootstrapOnce(deps),
      bootstrapOnce(deps),
      bootstrapOnce(deps),
    ])

    expect(deps.getPreset).toHaveBeenCalledTimes(1)
    expect(deps.loadSchema).toHaveBeenCalledTimes(1)
    expect(outcomes[1]).toBe(outcomes[0])
    expect(outcomes[2]).toBe(outcomes[0])
  })

  it("navegar a Datos y VOLVER a Configuración no re-siembra: no pisa ediciones ni dataset", async () => {
    const deps = demoDeps()

    // Arranque de la sesión (provider): siembra el preset.
    const first = await bootstrapOnce(deps)
    // El usuario edita el config y elige OTRO dataset en Datos.
    const edited = { ...first.config, binning: { min_prebin_size: 0.11 } }
    const chosen = "hipotecario_comportamiento"

    // Vuelve a Configuración: ConfigTab se monta de nuevo. Antes, su efecto de montaje re-pedía
    // el preset y re-sembraba; ahora la siembra está memoizada y el estado del usuario manda.
    await bootstrapOnce(deps)

    expect(deps.getPreset).toHaveBeenCalledTimes(1)
    expect(edited.binning).toEqual({ min_prebin_size: 0.11 })
    expect(seedDatasetId(chosen, first)).toBe("hipotecario_comportamiento")
  })
})

describe("seedDatasetId (el preset no pisa la elección del usuario)", () => {
  it("sin dataset elegido ⇒ usa el recomendado por el preset", async () => {
    const outcome = await bootstrapWorkspace(demoDeps())
    expect(seedDatasetId(null, outcome)).toBe("consumo_comportamiento")
  })

  it("con dataset ya elegido (o subido) ⇒ lo respeta, aunque el preset traiga otro", async () => {
    const outcome = await bootstrapWorkspace(demoDeps())
    expect(seedDatasetId("upload_a1b2", outcome)).toBe("upload_a1b2")
  })

  it("el arranque vacío del instalable no aporta dataset: se conserva el que el usuario ya eligió", async () => {
    const outcome = await bootstrapWorkspace(okDeps())
    expect(seedDatasetId("upload_a1b2", outcome)).toBe("upload_a1b2")
    expect(seedDatasetId(null, outcome)).toBeNull()
  })

  it("sin preset y sin elección ⇒ null (el gate pedirá elegir dataset)", async () => {
    const deps: BootstrapDeps = {
      loadSchema: vi.fn(() => Promise.resolve(SCHEMA)),
      getPreset: vi.fn(() => Promise.reject(new Error("offline"))),
      sembrarAlArrancar: true,
    }
    const outcome = await bootstrapWorkspace(deps)
    expect(seedDatasetId(null, outcome)).toBeNull()
    expect(canRun({ kind: "valid", hash: "x", pipeline: null }, seedDatasetId(null, outcome))).toEqual({
      ok: false,
      reason: "Falta elegir dataset",
    })
  })
})

describe("ConfigTab es un editor PURO (guardrail de la regresión UX1)", () => {
  it("no tiene efectos de montaje: no puede volver a sembrar el config al navegar", () => {
    // La siembra automática solo puede reaparecer por un efecto de montaje. `getPreset` sigue
    // permitido: es el botón "Ver un ejemplo" (acción explícita del usuario).
    expect(configTabSource).not.toMatch(/useEffect/)
  })
})

describe("guardrail: el instalable no puede volver a sembrar (D-JOB-2)", () => {
  it("las deps reales atan la siembra a DEMO_MODE, no a un literal", () => {
    // Los tests de arriba inyectan el flag, así que ninguno vería a alguien poniendo
    // `sembrarAlArrancar: true` en las deps de producción: pasarían los dos grupos y la aplicación
    // instalada volvería a arrancar sembrada. Es el mismo motivo por el que D-FX necesitó un
    // guardrail estático — vitest corre sin DOM y no puede cazarlo arrancando la app.
    expect(bootstrapSource).toMatch(/sembrarAlArrancar:\s*DEMO_MODE/)
    expect(bootstrapSource).not.toMatch(/sembrarAlArrancar:\s*true\s*,?\s*\n?\s*\}/)
  })
})

describe("configEditadoRespectoDelPreset (M5: el selector no puede mentir)", () => {
  const seed = {
    kind: "preset" as const,
    name: "Scorecard de comportamiento",
    datasetId: "consumo_comportamiento",
    fingerprint: configFingerprint(PRESET.config),
  }

  it("el config recién sembrado NO cuenta como editado", () => {
    expect(configEditadoRespectoDelPreset(seed, PRESET.config)).toBe(false)
  })

  it("una sola edición del formulario ya cuenta", () => {
    const editado = structuredClone(PRESET.config) as Record<string, unknown>
    ;(editado.model as Record<string, unknown>).type = "xgboost"
    expect(configEditadoRespectoDelPreset(seed, editado)).toBe(true)
  })

  it("reordenar las claves NO es editar: la huella es canónica", () => {
    const alReves = Object.fromEntries(
      Object.entries(PRESET.config as Record<string, unknown>).reverse(),
    )
    expect(configEditadoRespectoDelPreset(seed, alReves)).toBe(false)
  })

  it("sin preset sembrado (YAML cargado, defaults) no se acusa de editado", () => {
    expect(
      configEditadoRespectoDelPreset({ kind: "yaml", fileName: "mi.yaml" }, PRESET.config),
    ).toBe(false)
    expect(configEditadoRespectoDelPreset(null, PRESET.config)).toBe(false)
  })

  it("un seed sin huella (sesión anterior) tampoco acusa: ante la duda, no se afirma", () => {
    const viejo = {
      kind: "preset" as const,
      name: "Scorecard de comportamiento",
      datasetId: "consumo_comportamiento",
    }
    expect(configEditadoRespectoDelPreset(viejo, { otra: "cosa" })).toBe(false)
  })
})
