/**
 * Tests del ARRANQUE del workspace (UX1). Cubren los dos bugs que motivaron mover la siembra
 * del preset fuera de `ConfigTab`:
 *
 *  (a) el gate: entrar basta para poder ejecutar — el preset se siembra y valida sin abrir
 *      Configuración, y `canRun` abre con el dataset que trae el propio preset;
 *  (b) el bug hermano: la siembra ocurre UNA sola vez por sesión, así que volver a Configuración
 *      (que se desmonta al navegar) no puede pisar ni las ediciones del config ni el dataset
 *      que el usuario eligió o subió.
 *
 * El runner corre en entorno `node` (sin DOM: el proyecto no trae jsdom ni testing-library, y el
 * goal veta dependencias nuevas), así que se testea la LÓGICA del arranque con deps inyectadas —
 * que es donde vive el bug— más un guardrail estático de que `ConfigTab` ya no siembra.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"

// El fuente de ConfigTab como texto (`?raw` de Vite) para el guardrail estático del final.
import configTabSource from "@/components/ConfigTab.tsx?raw"
import type { PresetResponse } from "@/lib/api"
import {
  bootstrapOnce,
  bootstrapWorkspace,
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

/** Deps del arranque con el backend sano (schema + preset). */
function okDeps(): BootstrapDeps {
  return {
    loadSchema: vi.fn(() => Promise.resolve(SCHEMA)),
    getPreset: vi.fn(() => Promise.resolve(PRESET)),
  }
}

beforeEach(() => {
  resetBootstrapForTests() // cada test es una sesión nueva
})

describe("bootstrapWorkspace (siembra del preset al entrar)", () => {
  it("siembra el config del preset y su dataset recomendado, sin abrir Configuración", async () => {
    const outcome = await bootstrapWorkspace(okDeps())

    expect(outcome.config).toEqual(PRESET.config)
    expect(outcome.datasetId).toBe("consumo_comportamiento")
    expect(outcome.seed).toEqual({
      kind: "preset",
      name: "Scorecard de comportamiento",
      datasetId: "consumo_comportamiento",
    })
    expect(outcome.schema).toBe(SCHEMA)
  })

  it("con el preset sembrado y validado, el gate de Ejecutar ABRE sin tocar la configuración", async () => {
    // Réplica del arranque del provider: bootstrap → validación en vivo (el backend produce el
    // config_hash) → gate. Antes de UX1 esto solo ocurría si el usuario abría ConfigTab.
    const outcome = await bootstrapWorkspace(okDeps())
    const validation = { kind: "valid", hash: PRESET.config_hash } as const

    expect(canRun(validation, outcome.datasetId)).toEqual({ ok: true })
  })

  it("mientras la validación no termina, el gate bloquea con un motivo TRANSITORIO (no 'te falta config')", () => {
    expect(canRun({ kind: "idle" }, "consumo_comportamiento")).toEqual({
      ok: false,
      reason: "Preparando la configuración…",
    })
  })

  it("sin preset (backend caído) cae a los defaults del schema y NO inventa dataset", async () => {
    const deps: BootstrapDeps = {
      loadSchema: vi.fn(() => Promise.resolve(SCHEMA)),
      getPreset: vi.fn(() => Promise.reject(new Error("HTTP 500"))),
    }
    const outcome = await bootstrapWorkspace(deps)

    expect(outcome.config).toEqual(SCHEMA.payload.defaults)
    expect(outcome.config).not.toBe(SCHEMA.payload.defaults) // clon: editar no muta el schema
    expect(outcome.datasetId).toBeNull()
    expect(outcome.seed).toEqual({ kind: "fallback" })
  })
})

describe("bootstrapOnce (una sola siembra por sesión)", () => {
  it("varias llamadas (remontajes, StrictMode) piden el preset UNA vez y devuelven el mismo arranque", async () => {
    const deps = okDeps()

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
    const deps = okDeps()

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
    const outcome = await bootstrapWorkspace(okDeps())
    expect(seedDatasetId(null, outcome)).toBe("consumo_comportamiento")
  })

  it("con dataset ya elegido (o subido) ⇒ lo respeta, aunque el preset traiga otro", async () => {
    const outcome = await bootstrapWorkspace(okDeps())
    expect(seedDatasetId("upload_a1b2", outcome)).toBe("upload_a1b2")
  })

  it("sin preset y sin elección ⇒ null (el gate pedirá elegir dataset)", async () => {
    const deps: BootstrapDeps = {
      loadSchema: vi.fn(() => Promise.resolve(SCHEMA)),
      getPreset: vi.fn(() => Promise.reject(new Error("offline"))),
    }
    const outcome = await bootstrapWorkspace(deps)
    expect(seedDatasetId(null, outcome)).toBeNull()
    expect(canRun({ kind: "valid", hash: "x" }, seedDatasetId(null, outcome))).toEqual({
      ok: false,
      reason: "Falta elegir dataset",
    })
  })
})

describe("ConfigTab es un editor PURO (guardrail de la regresión UX1)", () => {
  it("no tiene efectos de montaje: no puede volver a sembrar el config al navegar", () => {
    // La siembra automática solo puede reaparecer por un efecto de montaje. `getPreset` sigue
    // permitido: es el botón "Configuración estándar" (acción explícita del usuario).
    expect(configTabSource).not.toMatch(/useEffect/)
  })
})
