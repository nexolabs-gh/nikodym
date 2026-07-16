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
 * Gate del modo demo MULTI-PRESET (SDD-28 / F7): la demo estática empaqueta DOS corridas reales
 * —`f3-provisiones-consumo` (default) y `f4-ifrs9-retail` (IFRS 9)— y rastrea el preset elegido para
 * que run/results/yaml/validate devuelvan el set correcto. Verifica que F3 sigue intacto (default),
 * que al elegir F4 todo el set cambia, y que AMBOS presets sirven su informe (el de F4 titulado
 * como informe IFRS 9). Todas las funciones demo son deterministas y no dependen de `DEMO_MODE` (solo `api.ts`
 * ramifica por él), así que se ejercitan directamente en el entorno node de vitest.
 */

const F3_ID = "f3-provisiones-consumo"
const F4_ID = "f4-ifrs9-retail"

beforeEach(() => {
  // Cada test arranca con el preset activo en su default (F3): el estado de módulo no se filtra.
  resetDemoActivePresetForTests()
})

describe("demoListPresets", () => {
  it("expone AMBOS presets en orden estable (F3 provisiones, F4 IFRS 9)", async () => {
    const { presets } = await demoListPresets()
    expect(presets.map((p) => p.id)).toEqual([F3_ID, F4_ID])
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

    const results = await demoGetResults()
    expect(results.provisioning_ifrs9).toBeDefined()
    expect(results.provisioning_ifrs9).not.toBeNull()
    expect(results.provisioning_ifrs9?.total_ecl_reported).toBeGreaterThan(0)
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

describe("robustez", () => {
  it("un preset id desconocido cae a F3 sin romper la demo", async () => {
    const preset = await demoGetPresetById("preset-inexistente")
    expect(preset.id ?? preset.dataset_id).toBe(F3_ID)
    const results = await demoGetResults()
    expect(results.provisioning_ifrs9 ?? null).toBeNull()
  })
})
