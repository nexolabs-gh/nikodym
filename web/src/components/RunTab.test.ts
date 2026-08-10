/**
 * Tests de `applyPreset`, el flujo REAL que usan los tres callers que cargan un ejemplo:
 * `RunTab.handlePreset` (selector in-workspace), `App.enterDemo` (selector del landing) y
 * `ConfigTab.handleLoadPreset` («Ver un ejemplo»). Cubren sus dos responsabilidades:
 *
 * 1. **El CORTE de la corrida anterior** (bug P0). Escenario: el usuario ejecuta un dominio (F1),
 *    cambia a otro (F4/IFRS 9) SIN volver a ejecutar. Antes, el flujo nunca limpiaba la corrida
 *    anterior, así que Resultados/Reporte y la tarjeta "Corrida completada" seguían mostrando el
 *    dominio VIEJO con lineage mixto.
 * 2. 🔴 **El TRABAJO de la sesión** (D-JOB-17). Entrar por «Ver un ejemplo» de scorecard estando en
 *    IFRS 9 dejaba un config de scorecard bajo el sidebar de IFRS 9: las secciones del ejemplo sin
 *    pestaña, y las que se veían apagadas en él — el estado exacto que D-JOB-1 existe para impedir.
 *    La regla ya estaba escrita y conectada para el YAML (`applyYamlConfig`); el ejemplo entra por
 *    el mismo hueco que aquél y no la usaba.
 *
 * Igual que `bootstrap.test.ts`, el runner corre en `node` (sin DOM: no hay jsdom ni
 * testing-library y el goal veta deps nuevas), así que se prueba la LÓGICA con deps inyectadas más
 * guardrails estáticos (`?raw`) de que los tres callers siguen enrutando por `applyPreset` con su
 * `setJob` (si alguno vuelve a resembrar inline, se pierden el corte y el cambio de trabajo) y de
 * que la OTRA ruta de ConfigTab, `handleStartBlank` («Empezar de cero», sin preset → sin
 * `applyPreset`), corta igual results/lastRun. Que el sidebar de verdad se repinte se verifica en la
 * pantalla: es la limitación declarada de vitest sin DOM, la misma que ya declara `jobs.test.ts`.
 */

import { describe, expect, it, vi } from "vitest"

import appSource from "@/App.tsx?raw"
import configTabSource from "@/components/ConfigTab.tsx?raw"
import { applyPreset, type PresetSwitchDeps } from "@/components/RunTab"
import runTabSource from "@/components/RunTab.tsx?raw"
import presetF1Fixture from "@/fixtures/demo/preset-f1.json"
import presetF3Fixture from "@/fixtures/demo/preset.json"
import presetF4Fixture from "@/fixtures/demo/preset-ifrs9.json"
import type { PresetResponse, ResultsResponse } from "@/lib/api"
import type { SeedState } from "@/lib/bootstrap"
import type { SelectedDataset } from "@/lib/datasets"
import { FIXTURE_JOBS, sectionsOfJob, type Job } from "@/lib/jobs"
import { CONFIG_SECTIONS } from "@/lib/schema"
import type { LastRun } from "@/state/appStore"

const JOBS = FIXTURE_JOBS.jobs
const porId = (id: string): Job => {
  const job = JOBS.find((j) => j.id === id)
  if (!job) throw new Error(`el fixture no trae el trabajo ${id}`)
  return job
}

/** Preset "destino": el dominio nuevo que se siembra al cambiar. */
const PRESET_DESTINO: PresetResponse = {
  id: "f4-ifrs9-retail",
  // Las secciones que un config de IFRS 9 trae encendidas: es lo que mira `jobForConfig`.
  config: {
    data: {},
    survival: {},
    provisioning_ifrs9: {},
    report: {},
  },
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
 * escriben en variables locales, sembrado con el estado que deja una corrida previa de alguien que
 * entró por «Scorecard». `applyPreset` (el código de producción) opera sobre estos setters
 * exactamente como lo hace sobre los del store.
 */
function makeFakeStore(
  preset: PresetResponse = PRESET_DESTINO,
  jobInicial: Job | null = porId("scorecard_pd"),
) {
  const state = {
    config: {} as Record<string, unknown>,
    job: jobInicial,
    datasetId: "consumo_comportamiento" as string | null,
    selectedDataset: { id: "consumo_comportamiento" } as SelectedDataset | null,
    seed: null as SeedState | null,
    results: RESULTS_VIEJOS as ResultsResponse | null,
    lastRun: LAST_RUN_VIEJO as LastRun | null,
    outcomeIdle: false,
  }
  const deps: PresetSwitchDeps = {
    getPreset: vi.fn(() => Promise.resolve(preset)),
    loadJobs: vi.fn(() => Promise.resolve(JOBS)),
    setConfig: (v) => {
      state.config = typeof v === "function" ? v(state.config) : v
    },
    setJob: (v) => {
      state.job = typeof v === "function" ? v(state.job) : v
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

    await applyPreset("f4-ifrs9-retail", state.job, deps)

    // El preset destino quedó sembrado…
    expect(state.datasetId).toBe("ifrs9_retail")
    expect(state.seed).toEqual({
      kind: "preset",
      name: "IFRS 9 retail",
      datasetId: "ifrs9_retail",
      fingerprint: expect.any(String),
    })
    // …y —lo que arregla el P0— la corrida anterior YA NO está en el store.
    expect(state.results).toBeNull()
    expect(state.lastRun).toBeNull()
    expect(state.outcomeIdle).toBe(true)
  })

  it("si el detalle del preset no llega, propaga el error y NO limpia (el preset vigente sigue)", async () => {
    const { state, deps } = makeFakeStore()
    const jobAntes = state.job
    deps.getPreset = () => Promise.reject(new Error("HTTP 500"))

    await expect(applyPreset("f4-ifrs9-retail", state.job, deps)).rejects.toThrow(
      "HTTP 500",
    )

    // El preset no cambió → mantener la corrida previa es coherente (mismo dominio), no un bug.
    expect(state.results).toBe(RESULTS_VIEJOS)
    expect(state.lastRun).toBe(LAST_RUN_VIEJO)
    expect(state.outcomeIdle).toBe(false)
    // Y el trabajo tampoco se movió: config y sidebar siguen siendo coherentes entre sí.
    expect(state.job).toBe(jobAntes)
  })
})

describe("applyPreset (el ejemplo selecciona su trabajo · D-JOB-17)", () => {
  it("cargar el ejemplo de IFRS 9 desde «Scorecard» pasa la sesión a IFRS 9", async () => {
    const { state, deps } = makeFakeStore()

    const cambio = await applyPreset("f4-ifrs9-retail", state.job, deps)

    expect(state.job?.id).toBe("provisiones_ifrs9")
    expect(cambio).toEqual({ job: porId("provisiones_ifrs9"), cambia: true })
  })

  it("un ejemplo del trabajo YA activo no toca el trabajo ni avisa de nada", async () => {
    // Un aviso que se dispara de más se aprende a ignorar, y reescribir el trabajo con un objeto
    // equivalente —el catálogo se vuelve a pedir en cada carga— sería un render de más sin motivo.
    const { state, deps } = makeFakeStore({
      ...PRESET_DESTINO,
      config: {
        data: {},
        binning: {},
        selection: {},
        model: {},
        scorecard: {},
        calibration: {},
        performance: {},
        stability: {},
        report: {},
      },
    })
    const jobAntes = state.job

    const cambio = await applyPreset("f1-estandar-consumo", state.job, deps)

    expect(cambio.cambia).toBe(false)
    expect(state.job).toBe(jobAntes) // la MISMA referencia: no se reescribió
  })

  it("el trabajo se resuelve con el catálogo que devuelva `loadJobs`, que nunca lanza", async () => {
    // `loadJobs` cae al fixture bundleado si el backend no responde, así que un catálogo caído no
    // deja el ejemplo sin trabajo: el flujo no necesita una rama propia para ese caso.
    const { state, deps } = makeFakeStore()
    await applyPreset("f4-ifrs9-retail", state.job, deps)
    expect(deps.loadJobs).toHaveBeenCalledTimes(1)
  })
})

/**
 * 🔴 El efecto MEDIDO sobre los tres ejemplos que publica el backend, con sus configs REALES.
 *
 * Es el gate que hizo aceptable el cambio: ninguno de los tres deja el sidebar vacío, que era el
 * único desenlace intolerable. Los configs vienen de los fixtures de la demo, que son la salida
 * verbatim del backend (`scripts/capture_demo_fixtures*.py`); se comprobó contra
 * `nikodym.ui.presets` que las secciones activas de los tres coinciden con las de aquí.
 *
 * ⚠️ **La demo estática cambia con esto, y es la decisión tomada** (por encima del «`job === null` a
 * propósito» de D-JOB-19): el escaparate deja de enseñar 14 secciones para el ejemplo de scorecard y
 * para el de IFRS 9. Lo que desaparece son exactamente las secciones que ese ejemplo trae APAGADAS
 * —pestañas vacías—, y el último test de este bloque lo asevera. El de provisiones no calza con
 * ningún trabajo (mezcla scorecard, CMF, método interno y la comparación, y no hay trabajo que cubra
 * los cuatro) y **sigue enseñando las 14**, por el criterio ya escrito en `jobForConfig`.
 */
describe("efecto medido sobre los tres ejemplos publicados (y sobre la demo estática)", () => {
  const CASOS: {
    nombre: string
    preset: PresetResponse
    job: string | null
    secciones: number
  }[] = [
    {
      nombre: "F1 · scorecard",
      preset: presetF1Fixture as unknown as PresetResponse,
      job: "scorecard_pd",
      secciones: 9,
    },
    {
      nombre: "F3 · provisiones (CMF + método interno)",
      preset: presetF3Fixture as unknown as PresetResponse,
      job: null,
      secciones: CONFIG_SECTIONS.length,
    },
    {
      nombre: "F4 · IFRS 9",
      preset: presetF4Fixture as unknown as PresetResponse,
      job: "provisiones_ifrs9",
      secciones: 4,
    },
  ]

  /**
   * 🔴 Ancla anti-tautología, y no es teórica: la primera versión de estos tests arrancaba los tres
   * casos desde «Scorecard», así que el de F1 **pasaba sin que nadie llamara a `setJob`** —el
   * trabajo esperado era ya el de partida— y quedaba verde con el defecto puesto. Se descubrió
   * corriendo el control negativo. Se arranca desde un trabajo que no es la respuesta de ninguno de
   * los tres, para que los tres tengan que MOVERSE.
   */
  const PARTIDA = porId("provision_interna")

  for (const caso of CASOS) {
    it(`${caso.nombre} → trabajo ${caso.job ?? "(ninguno)"}, ${caso.secciones} secciones en el sidebar`, async () => {
      const { state, deps } = makeFakeStore(caso.preset, PARTIDA)
      expect(state.job?.id).not.toBe(caso.job) // el caso no puede pasar por quedarse quieto

      await applyPreset(caso.preset.id ?? "", state.job, deps)

      expect(state.job?.id ?? null).toBe(caso.job)
      expect(sectionsOfJob(state.job)).toHaveLength(caso.secciones)
    })
  }

  it("ningún ejemplo deja el sidebar VACÍO (el único desenlace intolerable)", () => {
    // Un sidebar sin secciones sería un workspace sin formulario y sin salida. `sectionsOfJob`
    // devuelve las 14 cuando no hay trabajo, así que el piso lo pone el trabajo más pequeño.
    for (const caso of CASOS) {
      expect(caso.secciones).toBeGreaterThan(0)
    }
  })

  it("las secciones que el sidebar esconde son SÓLO las que el ejemplo trae apagadas", () => {
    // Es lo que hace tolerable el encogimiento: no se oculta nada que el visitante pudiera ver.
    // Si un trabajo dejara fuera una sección ENCENDIDA del ejemplo, ese trozo del config quedaría
    // inalcanzable desde el formulario — el defecto simétrico al que este cambio corrige.
    for (const caso of CASOS) {
      const config = caso.preset.config as Record<string, unknown>
      const activas = CONFIG_SECTIONS.map((s) => s.key).filter(
        (k) => config[k] !== null && config[k] !== undefined,
      )
      const job = caso.job === null ? null : porId(caso.job)
      const visibles = new Set(sectionsOfJob(job).map((s) => s.key))
      expect(activas.filter((k) => !visibles.has(k))).toEqual([])
    }
  })
})

describe("los callers enrutan el cambio de preset por applyPreset (guardrail de wiring)", () => {
  it("RunTab.handlePreset delega en applyPreset con setJob (inline perdería corte y trabajo)", () => {
    const body =
      runTabSource.match(
        /async function handlePreset\(presetId: string\) \{([\s\S]*?)\r?\n  \}\r?\n/,
      )?.[1] ?? ""
    expect(body).not.toBe("")
    expect(body).toMatch(/await applyPreset\(/)
    expect(body).toMatch(/loadJobs,/)
    expect(body).toMatch(/setJob,/)
    // Y lo DICE: el sidebar se reescribe desde otra pestaña, así que el silencio desorienta.
    expect(body).toMatch(/setJobNotice\(jobSwitchNotice\(/)
  })

  it("el aviso de RunTab se RENDERIZA (si sólo se calculara, el usuario no se enteraría igual)", () => {
    const cuerpo = runTabSource.slice(runTabSource.indexOf("export function RunTab"))
    expect(cuerpo).toMatch(/\{jobNotice \?/)
    expect(cuerpo).toMatch(/\{jobNotice\}<\/span>/)
  })

  it("App.enterDemo delega en applyPreset al entrar con un preset del landing", () => {
    expect(appSource).toMatch(/await applyPreset\(/)
    // Le pasa el catálogo y el setter: sin ellos el ejemplo del landing no elegiría su trabajo.
    const body =
      appSource.match(/const enterDemo = async \(([\s\S]*?)\r?\n  \}\r?\n/)?.[1] ?? ""
    expect(body).not.toBe("")
    expect(body).toMatch(/loadJobs,/)
    expect(body).toMatch(/setJob,/)
  })

  it('ConfigTab.handleLoadPreset ("Ver un ejemplo") delega en applyPreset (3er caller, mismo trato)', () => {
    // Importa applyPreset desde RunTab…
    expect(configTabSource).toMatch(
      /import\s*\{[^}]*\bapplyPreset\b[^}]*\}\s*from\s*"@\/components\/RunTab"/,
    )
    // …y lo invoca con el trabajo activo, su catálogo y su setter, más el aviso.
    const body =
      configTabSource.match(
        /const handleLoadPreset = useCallback\(([\s\S]*?)\}, \[/,
      )?.[1] ?? ""
    expect(body).not.toBe("")
    expect(body).toMatch(/await applyPreset\("", job, \{/)
    expect(body).toMatch(/loadJobs,/)
    expect(body).toMatch(/setJob,/)
    expect(body).toMatch(/setJobNotice\(jobSwitchNotice\(/)
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
