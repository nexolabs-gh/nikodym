/**
 * Test del CORTE de estado al cambiar de preset (bug P0). Escenario: el usuario ejecuta un dominio
 * (F1), cambia a otro (F4/IFRS 9) SIN volver a ejecutar. Antes, el flujo de cambio de preset nunca
 * limpiaba la corrida anterior, así que Resultados/Reporte y la tarjeta "Corrida completada"
 * seguían mostrando el dominio VIEJO con lineage mixto.
 *
 * Igual que `bootstrap.test.ts`, el runner corre en `node` (sin DOM: no hay jsdom ni
 * testing-library y el goal veta deps nuevas), así que se prueba la LÓGICA con deps inyectadas —
 * `applyPreset`, el flujo REAL que usan los tres callers que cambian de preset: `RunTab.handlePreset`
 * (selector in-workspace), `App.enterDemo` (selector del landing) y `ConfigTab.handleLoadPreset`
 * ("Configuración estándar")— más guardrails estáticos (`?raw`) de que los tres siguen enrutando por
 * `applyPreset` (si alguno vuelve a resembrar inline, se pierde el corte) y de que la OTRA ruta de
 * ConfigTab, `handleStartBlank` ("Empezar de cero", sin preset → sin `applyPreset`), corta igual
 * results/lastRun. Sin esos cortes, Resultados/Reporte quedaban con lineage mixto del dominio viejo.
 */

import { describe, expect, it, vi } from "vitest"

import appSource from "@/App.tsx?raw"
import configTabSource from "@/components/ConfigTab.tsx?raw"
import { applyPreset, type PresetSwitchDeps } from "@/components/RunTab"
import runTabSource from "@/components/RunTab.tsx?raw"
import type { PresetResponse, ResultsResponse } from "@/lib/api"
import type { SeedState } from "@/lib/bootstrap"
import type { SelectedDataset } from "@/lib/datasets"
import type { LastRun } from "@/state/appStore"

/** Preset "destino": el dominio nuevo que se siembra al cambiar. */
const PRESET_DESTINO: PresetResponse = {
  id: "f4-ifrs9-retail",
  config: { model: { type: "logit" } },
  config_hash: "abc123",
  dataset_id: "ifrs9_retail",
  name: "IFRS 9 retail",
  description: "Preset F4.",
}

/** Artefactos que dejó la corrida ANTERIOR (dominio viejo) y que no deben sobrevivir al cambio. */
const RESULTS_VIEJOS: ResultsResponse = {
  status: "done",
  run_id: "run-viejo-f1",
  error: null,
  model_card: null,
}
const LAST_RUN_VIEJO: LastRun = { runId: "run-viejo-f1", status: "done" }

/**
 * Store falso mínimo (equivalente a "montar el store"): setters `Dispatch`-compatibles que
 * escriben en variables locales, sembrado con el estado que deja una corrida previa. `applyPreset`
 * (el código de producción) opera sobre estos setters exactamente como lo hace sobre los del store.
 */
function makeFakeStore() {
  const state = {
    config: {} as Record<string, unknown>,
    datasetId: "consumo_comportamiento" as string | null,
    selectedDataset: { id: "consumo_comportamiento" } as SelectedDataset | null,
    seed: null as SeedState | null,
    results: RESULTS_VIEJOS as ResultsResponse | null,
    lastRun: LAST_RUN_VIEJO as LastRun | null,
    outcomeIdle: false,
  }
  const deps: PresetSwitchDeps = {
    getPreset: vi.fn(() => Promise.resolve(PRESET_DESTINO)),
    setConfig: (v) => {
      state.config = typeof v === "function" ? v(state.config) : v
    },
    setDatasetId: (v) => {
      state.datasetId = typeof v === "function" ? v(state.datasetId) : v
    },
    setSelectedDataset: (v) => {
      state.selectedDataset = typeof v === "function" ? v(state.selectedDataset) : v
    },
    setSeed: (v) => {
      state.seed = typeof v === "function" ? v(state.seed) : v
    },
    setResults: (v) => {
      state.results = typeof v === "function" ? v(state.results) : v
    },
    setLastRun: (v) => {
      state.lastRun = typeof v === "function" ? v(state.lastRun) : v
    },
    resetOutcome: () => {
      state.outcomeIdle = true
    },
  }
  return { state, deps }
}

describe("applyPreset (corte de la corrida al cambiar de preset)", () => {
  it("siembra el preset nuevo y LIMPIA results, lastRun y outcome de la corrida anterior", async () => {
    const { state, deps } = makeFakeStore()

    await applyPreset("f4-ifrs9-retail", deps)

    // El preset destino quedó sembrado…
    expect(state.datasetId).toBe("ifrs9_retail")
    expect(state.seed).toEqual({
      kind: "preset",
      name: "IFRS 9 retail",
      datasetId: "ifrs9_retail",
    })
    // …y —lo que arregla el P0— la corrida anterior YA NO está en el store.
    expect(state.results).toBeNull()
    expect(state.lastRun).toBeNull()
    expect(state.outcomeIdle).toBe(true)
  })

  it("si el detalle del preset no llega, propaga el error y NO limpia (el preset vigente sigue)", async () => {
    const { state, deps } = makeFakeStore()
    deps.getPreset = () => Promise.reject(new Error("HTTP 500"))

    await expect(applyPreset("f4-ifrs9-retail", deps)).rejects.toThrow("HTTP 500")

    // El preset no cambió → mantener la corrida previa es coherente (mismo dominio), no un bug.
    expect(state.results).toBe(RESULTS_VIEJOS)
    expect(state.lastRun).toBe(LAST_RUN_VIEJO)
    expect(state.outcomeIdle).toBe(false)
  })
})

describe("los callers enrutan el cambio de preset por applyPreset (guardrail de wiring)", () => {
  it("RunTab.handlePreset delega en applyPreset (no re-siembra inline, que perdería el corte)", () => {
    expect(runTabSource).toMatch(/await applyPreset\(/)
  })

  it("App.enterDemo delega en applyPreset al entrar con un preset del landing", () => {
    expect(appSource).toMatch(/await applyPreset\(/)
  })

  it('ConfigTab.handleLoadPreset ("Configuración estándar") delega en applyPreset (3er caller, mismo corte)', () => {
    // Importa applyPreset desde RunTab…
    expect(configTabSource).toMatch(
      /import\s*\{[^}]*\bapplyPreset\b[^}]*\}\s*from\s*"@\/components\/RunTab"/,
    )
    // …y lo invoca (no re-siembra inline, que perdería el corte de results/lastRun).
    expect(configTabSource).toMatch(/await applyPreset\(/)
  })
})

describe('ConfigTab: "Empezar de cero" corta la corrida previa (ruta sin preset → sin applyPreset)', () => {
  it("handleStartBlank limpia results y lastRun, para no dejar el dominio viejo en Resultados/Reporte", () => {
    // Acota al CUERPO del handler (hasta el cierre `}, [` del useCallback) para no colar un
    // setResults/setLastRun que viviera en otra parte del archivo (p.ej. otro handler).
    const body =
      configTabSource.match(
        /const handleStartBlank = useCallback\(([\s\S]*?)\}, \[/,
      )?.[1] ?? ""
    expect(body).not.toBe("")
    expect(body).toMatch(/setResults\(null\)/)
    expect(body).toMatch(/setLastRun\(null\)/)
  })
})
