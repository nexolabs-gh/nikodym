import { beforeEach, describe, expect, it } from "vitest"

import {
  demoConfigFromYaml,
  demoConfigToYaml,
  demoGetPreset,
  demoGetPresetById,
  demoGetReport,
  demoGetResults,
  demoListPresets,
  demoRunPipeline,
  demoValidateConfig,
  resetDemoActivePresetForTests,
} from "@/lib/demo"

/**
 * Gate del modo demo MULTI-PRESET (SDD-28 / F7): la demo estática empaqueta TRES corridas reales
 * —`f1-estandar-consumo` (scorecard puro), `f3-provisiones-consumo` (default) y `f4-ifrs9-retail`
 * (IFRS 9)— y rastrea el preset elegido para que run/results/yaml/validate devuelvan el set correcto.
 * Verifica que F3 sigue intacto (default), que al elegir F1/F4 todo el set cambia (sin contaminación
 * cruzada de provisiones), y que los tres presets sirven su informe (F1 titulado como validación de
 * scorecard, F4 como informe IFRS 9). Todas las funciones demo son deterministas y no dependen de
 * `DEMO_MODE` (solo `api.ts` ramifica por él): se ejercitan directamente en el entorno node de vitest.
 */

const F1_ID = "f1-estandar-consumo"
const F3_ID = "f3-provisiones-consumo"
const F4_ID = "f4-ifrs9-retail"
// Recalculado en 1.4.0: `data.load.source` (la ruta del dataset en disco) dejó de entrar al
// `config_hash`, que ahora identifica sólo el contenido lógico del config.
const F4_CONFIG_HASH =
  "cbe5d9fa856ae838623e88974bf1ea783825289ff8580c9b02098a0392c8f4d4"

beforeEach(() => {
  // Cada test arranca con el preset activo en su default (F3): el estado de módulo no se filtra.
  resetDemoActivePresetForTests()
})

describe("demoListPresets", () => {
  it("expone LOS TRES presets en orden estable (F1 scorecard, F3 provisiones, F4 IFRS 9)", async () => {
    const { presets } = await demoListPresets()
    expect(presets.map((p) => p.id)).toEqual([F1_ID, F3_ID, F4_ID])
    // Cada item trae lo justo para el selector (id/name/description/dataset_id).
    for (const p of presets) {
      expect(p.name.length).toBeGreaterThan(0)
      expect(p.dataset_id.length).toBeGreaterThan(0)
    }
  })
})

describe("preset por defecto (F3 intacto)", () => {
  it("demoGetPreset siembra SIEMPRE F3 (la demo de provisiones queda idéntica)", async () => {
    const preset = await demoGetPreset()
    expect(preset.id ?? preset.dataset_id).toBe(F3_ID)
  })

  it("sin elegir preset, results/yaml/validate/run son los de F3 (provisiones CMF/interno)", async () => {
    const results = await demoGetResults()
    expect(results.provisioning).not.toBeNull()
    expect(results.provisioning).toBeDefined()
    // F3 NO trae el bloque IFRS 9.
    expect(results.provisioning_ifrs9 ?? null).toBeNull()

    const validate = await demoValidateConfig()
    const preset = await demoGetPreset()
    expect(validate.valid).toBe(true)
    expect(validate.config_hash).toBe(preset.config_hash)

    const run = await demoRunPipeline()
    expect(run.run_id).toBe(results.run_id)
    expect(run.status).toBe("done")
  })

  it("F3 SÍ genera informe: demoGetReport resuelve el HTML embebido", async () => {
    await expect(demoGetReport()).resolves.toContain("<")
  })
})

describe("elegir el preset IFRS 9 (F4) rastrea todo el set", () => {
  it("demoGetPresetById(F4) mueve el activo → results son IFRS 9 (bloque provisioning_ifrs9)", async () => {
    const preset = await demoGetPresetById(F4_ID)
    expect(preset.id ?? preset.dataset_id).toBe(F4_ID)
    expect(preset.config_hash).toBe(F4_CONFIG_HASH)

    const results = await demoGetResults()
    expect(results.provisioning_ifrs9).toBeDefined()
    expect(results.provisioning_ifrs9).not.toBeNull()
    const ifrs9 = results.provisioning_ifrs9
    expect(ifrs9).not.toBeNull()
    expect(Math.round(ifrs9?.total_ecl_reported ?? 0)).toBe(3_423_116)
    expect(Math.round(ifrs9?.total_ead ?? 0)).toBe(114_325_315)
    expect([ifrs9?.n_stage1, ifrs9?.n_stage2, ifrs9?.n_stage3]).toEqual([
      5_235,
      477,
      288,
    ])
    expect((ifrs9?.total_ecl_reported ?? 0) / (ifrs9?.total_ead ?? 1)).toBeCloseTo(
      0.029941891063941795,
      12,
    )
    expect(results.survival?.n_rows).toBe(6_000)
    expect(results.survival?.n_events).toBe(1_502)

    const methodology = ifrs9?.methodology
    expect(methodology).toBeDefined()
    const active = Object.fromEntries(
      (methodology?.active ?? []).map((fact) => [fact.id, fact]),
    )
    expect(active.lifetime_pd?.detail).toBe(
      "6.000 filas · 1.502 eventos · horizonte 5 años",
    )
    expect(active.loss_inputs?.value).toBe("LGD provided · EAD provided")
    expect(active.staging?.value).toBe("30/90 días + is_default")
    expect(active.scenario?.value).toBe("Base 100 %")
    expect(active.discount?.value).toBe("EIR anual")
    expect(methodology?.not_exercised.map((fact) => fact.id)).toEqual([
      "forward",
      "macro_scenarios",
      "markov",
    ])
    // Al elegir IFRS 9, el bloque de provisiones CMF/interno F3 NO viaja.
    expect(results.provisioning ?? null).toBeNull()
  })

  it("validate/yaml/run/configFromYaml siguen al preset F4", async () => {
    const preset = await demoGetPresetById(F4_ID)
    const results = await demoGetResults()

    const validate = await demoValidateConfig()
    expect(validate.config_hash).toBe(preset.config_hash)

    const yaml = await demoConfigToYaml()
    expect(yaml.yaml.length).toBeGreaterThan(0)

    const run = await demoRunPipeline()
    expect(run.run_id).toBe(results.run_id)

    const fromYaml = await demoConfigFromYaml()
    expect(fromYaml.config_hash).toBe(preset.config_hash)
  })

  it("F4 SÍ genera informe: demoGetReport resuelve el HTML del informe IFRS 9", async () => {
    await demoGetPresetById(F4_ID)
    const html = await demoGetReport()
    expect(html).toContain("<")
    // Es el informe IFRS 9 (título dinámico del renderer), no el de validación de scorecard.
    expect(html).toContain("Informe de Provisiones IFRS 9 / ECL")
    expect(html).toContain("Provisiones IFRS 9 / ECL")
    expect(html).toContain("Activo en esta corrida:")
    expect(html).toContain("Capacidad no ejercida en esta corrida:")
    expect(html).toContain('data-section-id="appendix_parameters.survival"')
    expect(html).toContain(
      'data-section-id="appendix_parameters.provisioning_ifrs9"',
    )
  })

  it("volver a F3 restaura la demo de provisiones", async () => {
    await demoGetPresetById(F4_ID)
    await demoGetPresetById(F3_ID)
    const results = await demoGetResults()
    expect(results.provisioning).toBeDefined()
    expect(results.provisioning_ifrs9 ?? null).toBeNull()
    await expect(demoGetReport()).resolves.toContain("<")
  })
})

describe("elegir el preset scorecard (F1) rastrea todo el set", () => {
  it("demoGetPresetById(F1) mueve el activo → results son scorecard PURO (sin provisiones)", async () => {
    const preset = await demoGetPresetById(F1_ID)
    expect(preset.id ?? preset.dataset_id).toBe(F1_ID)

    const results = await demoGetResults()
    // Scorecard puro: las cards de scorecard y performance vienen pobladas...
    expect(results.scorecard ?? null).not.toBeNull()
    expect(results.performance ?? null).not.toBeNull()
    // ...y NINGUNA card de provisiones viaja (el F1 no calcula provisiones, ni CMF ni IFRS 9).
    expect(results.provisioning ?? null).toBeNull()
    expect(results.provisioning_cmf ?? null).toBeNull()
    expect(results.provisioning_internal ?? null).toBeNull()
    expect(results.provisioning_ifrs9 ?? null).toBeNull()

    // run → results comparten el run_id real de la corrida capturada.
    const run = await demoRunPipeline()
    expect(run.run_id).toBe(results.run_id)
  })

  it("F1 SÍ genera informe: demoGetReport resuelve el informe de validación de scorecard", async () => {
    await demoGetPresetById(F1_ID)
    const html = await demoGetReport()
    expect(html).toContain("<")
    // Es el informe de scorecard (título dinámico del renderer), no el de provisiones IFRS 9.
    expect(html).toContain("Informe de Validación de Scorecard")
    expect(html).not.toContain("Informe de Provisiones IFRS 9 / ECL")
  })

  it("volver a F3 tras F1 restaura la demo de provisiones", async () => {
    await demoGetPresetById(F1_ID)
    await demoGetPresetById(F3_ID)
    const results = await demoGetResults()
    expect(results.provisioning).toBeDefined()
    expect(results.provisioning ?? null).not.toBeNull()
    expect(results.provisioning_ifrs9 ?? null).toBeNull()
  })
})

describe("robustez", () => {
  it("un preset id desconocido cae a F3 sin romper la demo", async () => {
    const preset = await demoGetPresetById("preset-inexistente")
    expect(preset.id ?? preset.dataset_id).toBe(F3_ID)
    const results = await demoGetResults()
    expect(results.provisioning_ifrs9 ?? null).toBeNull()
  })
})
