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
 * —`f1-estandar-consumo` (scorecard puro, el default) y `f4-ifrs9-retail` (IFRS 9)— y rastrea el
 * preset elegido para que run/results/yaml/validate devuelvan el set correcto. Verifica que F1
 * siembra el arranque, que al elegir F4 todo el set cambia (sin contaminación cruzada de
 * provisiones) y que los dos presets sirven su informe (F1 titulado como validación de scorecard,
 * F4 como informe IFRS 9). Todas las funciones demo son deterministas y no dependen de `DEMO_MODE`
 * (solo `api.ts` ramifica por él): se ejercitan directamente en el entorno node de vitest.
 *
 * ⚠️ La corrida F3 (provisiones CMF) salió de la demo con D-JUR-9.7 y sus fixtures salieron del
 * árbol con el OK de Cami del 2026-09-09. Su id se conserva aquí como entrada DESCONOCIDA: es el
 * caso que prueba que un `?preset=f3-provisiones-consumo` viejo —un enlace guardado, un marcador—
 * cae al default en vez de romper la demo.
 */

const F1_ID = "f1-estandar-consumo"
/** Id de la corrida retirada (D-JUR-9.7): ya NO está empaquetada; sirve de id desconocido. */
const F3_ID_RETIRADO = "f3-provisiones-consumo"
const F4_ID = "f4-ifrs9-retail"
// Recalculado en 1.4.0: `data.load.source` (la ruta del dataset en disco) dejó de entrar al
// `config_hash`, que ahora identifica sólo el contenido lógico del config.
// Recalculado otra vez en 1.6.0: la sección `provisioning_ifrs9` ganó `portfolio_scheme`
// (D-SEG-3), y esa sección sí entra al hash. El mismo valor está fijado del lado Python en
// `tests/unit/test_ui_presets.py`; si los dos lados se separan, la identidad UI↔código se rompe.
// Recalculado una tercera vez en 1.6.0 por D-CRP6-8: el preset declara los intervalos de
// confianza de Kaplan-Meier. Los dos goldens fallaron a la vez —éste y el de Python—, que es
// exactamente lo que se les pide: son el par que detecta un fixture de demo servido con un
// config distinto del que trae el paquete instalado.
const F4_CONFIG_HASH =
  "013e69dc4c96e03ee87e9f3f54bcf5e1f6e6fd56b5a1b1ffdd5bf021093360b6"

beforeEach(() => {
  // Cada test arranca con el preset activo en su default (F1): el estado de módulo no se filtra.
  resetDemoActivePresetForTests()
})

describe("demoListPresets", () => {
  it("expone LOS DOS presets en orden estable (F1 scorecard, F4 IFRS 9)", async () => {
    const { presets } = await demoListPresets()
    expect(presets.map((p) => p.id)).toEqual([F1_ID, F4_ID])
    // D-JUR-9.7: el selector de la demo no ofrece la corrida de referencia.
    expect(presets.map((p) => p.id)).not.toContain(F3_ID_RETIRADO)
    // Cada item trae lo justo para el selector (id/name/description/dataset_id).
    for (const p of presets) {
      expect(p.name.length).toBeGreaterThan(0)
      expect(p.dataset_id.length).toBeGreaterThan(0)
    }
  })
})

describe("preset por defecto (F1, el scorecard)", () => {
  it("demoGetPreset siembra SIEMPRE F1 (D-JUR-9.7)", async () => {
    const preset = await demoGetPreset()
    expect(preset.id ?? preset.dataset_id).toBe(F1_ID)
  })

  it("sin elegir preset, results/yaml/validate/run son los de F1 (scorecard puro)", async () => {
    const results = await demoGetResults()
    // Scorecard puro: NINGUNA card de provisiones viaja en la corrida que siembra el arranque.
    expect(results.scorecard ?? null).not.toBeNull()
    expect(results.provisioning ?? null).toBeNull()
    expect(results.provisioning_cmf ?? null).toBeNull()
    expect(results.provisioning_ifrs9 ?? null).toBeNull()

    const validate = await demoValidateConfig()
    const preset = await demoGetPreset()
    expect(validate.valid).toBe(true)
    expect(validate.config_hash).toBe(preset.config_hash)

    const run = await demoRunPipeline()
    expect(run.run_id).toBe(results.run_id)
    expect(run.status).toBe("done")
  })

  it("F1 SÍ genera informe desde el arranque: demoGetReport resuelve el HTML embebido", async () => {
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
    // Al elegir IFRS 9, el bloque de provisiones CMF/interno no viaja.
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

  it("volver a F1 restaura el scorecard", async () => {
    await demoGetPresetById(F4_ID)
    await demoGetPresetById(F1_ID)
    const results = await demoGetResults()
    expect(results.scorecard ?? null).not.toBeNull()
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

  it("volver a F4 tras F1 restaura la demo IFRS 9", async () => {
    await demoGetPresetById(F1_ID)
    await demoGetPresetById(F4_ID)
    const results = await demoGetResults()
    expect(results.provisioning_ifrs9 ?? null).not.toBeNull()
    expect(results.scorecard ?? null).toBeNull()
  })
})

describe("robustez", () => {
  it("un preset id desconocido cae a F1 sin romper la demo", async () => {
    const preset = await demoGetPresetById("preset-inexistente")
    expect(preset.id ?? preset.dataset_id).toBe(F1_ID)
    const results = await demoGetResults()
    expect(results.provisioning_ifrs9 ?? null).toBeNull()
  })

  it("🔴 el id de la corrida RETIRADA cae al default, no rompe un enlace guardado", async () => {
    // `demo.nikodym.cl/?preset=f3-provisiones-consumo` fue una URL válida hasta D-JUR-9.7, así que
    // hay marcadores y enlaces compartidos que lo traen. Es la ruta REAL de ese enlace: carga
    // limpia, sin selección previa. Cae a F1 y el set entero es el de F1.
    const preset = await demoGetPresetById(F3_ID_RETIRADO)
    expect(preset.id ?? preset.dataset_id).toBe(F1_ID)
    const results = await demoGetResults()
    expect(results.scorecard ?? null).not.toBeNull()
    expect(results.provisioning ?? null).toBeNull()
    expect(results.provisioning_ifrs9 ?? null).toBeNull()
    // Y el informe sigue resolviendo: la demo no queda a medias con un id que ya no existe.
    await expect(demoGetReport()).resolves.toContain("<")
  })
})
