/**
 * Test de la CONEXIÓN de D-JOB-17: cargar un YAML deja la sesión en el trabajo que ese archivo trae.
 *
 * 🔴 La regla estaba implementada, documentada y probada (`jobForConfig`, `jobs.test.ts`) y **no la
 * llamaba nadie**: existía en el repo y no en el producto. Sin ella, traer un YAML de IFRS 9 estando
 * en «Scorecard» dejaba el sidebar del scorecard sobre un config de IFRS 9 — las secciones que el
 * usuario acababa de traer no tenían pestaña, y las que veía estaban apagadas en su archivo—. Estos
 * tests aseveran el flujo REAL (`applyYamlConfig`, el que corre el handler), no que la función
 * exista.
 *
 * Igual que `RunTab.test.ts` y `bootstrap.test.ts`, el runner corre en `node` (sin DOM), así que se
 * prueba la LÓGICA con deps inyectadas más guardrails estáticos (`?raw`) del cableado. Que el
 * sidebar de verdad se repinte se verifica **en la pantalla**, con Playwright: es la limitación
 * declarada de vitest sin DOM, la misma que ya declara `jobs.test.ts`.
 */

import { describe, expect, it, vi } from "vitest"

import { applyYamlConfig, type YamlIntakeDeps } from "@/components/ConfigTab"
import configTabSource from "@/components/ConfigTab.tsx?raw"
import type { ConfigDict, ConfigFromYamlResponse } from "@/lib/api"
import type { SeedState } from "@/lib/bootstrap"
import { FIXTURE_JOBS, jobSwitchNotice, type Job } from "@/lib/jobs"

const JOBS = FIXTURE_JOBS.jobs
const porId = (id: string): Job => {
  const job = JOBS.find((j) => j.id === id)
  if (!job) throw new Error(`el fixture no trae el trabajo ${id}`)
  return job
}

/** Config de IFRS 9 tal como lo devuelve el backend: sólo lo que el ARCHIVO traía (`exclude_unset`). */
const CONFIG_IFRS9: ConfigDict = {
  name: "ecl-retail",
  data: {},
  survival: {},
  provisioning_ifrs9: {},
  report: {},
}

/**
 * Store falso mínimo: setters `Dispatch`-compatibles que escriben en variables locales, sembrado con
 * la sesión de alguien que entró por «Scorecard». `applyYamlConfig` (el código de producción) opera
 * sobre ellos exactamente como sobre los del store real.
 */
function makeFakeStore(config: ConfigDict = CONFIG_IFRS9) {
  const state = {
    config: { binning: {} } as Record<string, unknown>,
    job: porId("scorecard_pd") as Job | null,
    seed: { kind: "job", jobId: "scorecard_pd", label: "Scorecard" } as SeedState | null,
  }
  const respuesta: ConfigFromYamlResponse = { config, config_hash: "abc123" }
  const deps: YamlIntakeDeps = {
    fromYaml: vi.fn(() => Promise.resolve(respuesta)),
    loadJobs: vi.fn(() => Promise.resolve(JOBS)),
    setConfig: (v) => {
      state.config = typeof v === "function" ? v(state.config) : v
    },
    setJob: (v) => {
      state.job = typeof v === "function" ? v(state.job) : v
    },
    setSeed: (v) => {
      state.seed = typeof v === "function" ? v(state.seed) : v
    },
  }
  return { state, deps }
}

describe("applyYamlConfig (el YAML selecciona su trabajo · D-JOB-17)", () => {
  it("un YAML de IFRS 9 cargado desde «Scorecard» pasa la sesión a IFRS 9", async () => {
    const { state, deps } = makeFakeStore()

    const cambio = await applyYamlConfig("yaml: crudo", "ecl.yaml", state.job, deps)

    // El config del usuario queda sembrado tal cual lo devolvió el backend…
    expect(state.config).toEqual(CONFIG_IFRS9)
    // …y —lo que arregla el defecto— el trabajo de la sesión ya no es el scorecard.
    expect(state.job?.id).toBe("provisiones_ifrs9")
    expect(cambio).toEqual({ job: porId("provisiones_ifrs9"), cambia: true })
    // El seed deja de mentir que el config es el del trabajo elegido en el landing.
    expect(state.seed).toEqual({ kind: "yaml", fileName: "ecl.yaml" })
  })

  it("el usuario se ENTERA: el aviso nombra el trabajo por su etiqueta, nunca por su id", async () => {
    // Cambiar de trabajo reescribe el sidebar entero; hacerlo en silencio es la sorpresa que este
    // repo evita. Y el `id` es coordenada interna, como el `path` de una decisión obligatoria.
    const { state, deps } = makeFakeStore()
    const cambio = await applyYamlConfig("yaml: crudo", "ecl.yaml", state.job, deps)
    const aviso = jobSwitchNotice(cambio, "archivo")

    expect(aviso).toContain("Provisiones IFRS 9 / ECL")
    expect(aviso).not.toContain("provisiones_ifrs9")
  })

  it("un YAML que corresponde al trabajo YA activo no toca el trabajo ni avisa de nada", async () => {
    // Un aviso que se dispara de más se aprende a ignorar, y reescribir el trabajo con un objeto
    // equivalente —el catálogo se vuelve a pedir en cada carga— sería un render de más sin motivo.
    const { state, deps } = makeFakeStore({
      data: {},
      binning: {},
      selection: {},
      model: {},
      scorecard: {},
      calibration: {},
      performance: {},
      stability: {},
      report: {},
    })
    const jobAntes = state.job

    const cambio = await applyYamlConfig("yaml: crudo", "sc.yaml", state.job, deps)

    expect(cambio.cambia).toBe(false)
    expect(state.job).toBe(jobAntes) // la MISMA referencia: no se reescribió
    expect(jobSwitchNotice(cambio, "archivo")).toBeNull()
  })

  it("un YAML que no calza con ningún trabajo deja la sesión SIN trabajo, y lo dice", async () => {
    // Es el criterio ya escrito en `jobForConfig`: es el config del usuario, no el nuestro, y
    // esconderle parte de lo que él mismo trajo sería la mentira contraria.
    const { state, deps } = makeFakeStore({
      data: {},
      binning: {},
      provisioning_cmf: {},
      survival: {},
      provisioning_ifrs9: {},
      report: {},
    })

    const cambio = await applyYamlConfig("yaml: crudo", "mixto.yaml", state.job, deps)

    expect(state.job).toBeNull()
    expect(cambio).toEqual({ job: null, cambia: true })
    expect(jobSwitchNotice(cambio, "archivo")).toContain("todas las secciones")
  })

  it("si el backend rechaza el YAML no se escribe NADA: config y trabajo siguen siendo coherentes", async () => {
    const { state, deps } = makeFakeStore()
    const configAntes = state.config
    const jobAntes = state.job
    deps.fromYaml = () => Promise.reject(new Error("HTTP 422"))

    await expect(
      applyYamlConfig("yaml: roto", "malo.yaml", state.job, deps),
    ).rejects.toThrow("HTTP 422")

    expect(state.config).toBe(configAntes)
    expect(state.job).toBe(jobAntes)
    expect(state.seed).toEqual({ kind: "job", jobId: "scorecard_pd", label: "Scorecard" })
  })

  it("el trabajo se resuelve con el catálogo que devuelva `loadJobs`, que nunca lanza", async () => {
    // `loadJobs` cae al fixture bundleado si el backend no responde, así que un catálogo caído no
    // deja el YAML sin trabajo: el flujo no necesita una rama propia para ese caso.
    const { state, deps } = makeFakeStore()
    await applyYamlConfig("yaml: crudo", "ecl.yaml", state.job, deps)
    expect(deps.loadJobs).toHaveBeenCalledTimes(1)
  })
})

describe("guardrail: el handler de «Cargar YAML» enruta por applyYamlConfig", () => {
  it("`handleUploadYaml` delega en applyYamlConfig y le pasa `setJob`", () => {
    // Si alguien vuelve a resembrar inline (`setConfig(result.config)` a secas), la conexión de
    // D-JOB-17 se pierde en silencio y el sidebar vuelve a contradecir al config cargado — que es
    // exactamente el estado en que estuvo el repo desde que se aprobó el SDD.
    const body =
      configTabSource.match(
        /const handleUploadYaml = async \(([\s\S]*?)\r?\n  \}\r?\n/,
      )?.[1] ?? ""
    expect(body).not.toBe("")
    expect(body).toMatch(/await applyYamlConfig\(/)
    expect(body).toMatch(/setJob,/)
    expect(body).toMatch(/setJobNotice\(jobSwitchNotice\(/)
    // Y no vuelve a escribir el config por su cuenta saltándose el flujo.
    expect(body).not.toMatch(/setConfig\(result\.config\)/)
  })

  it("el aviso se RENDERIZA (si sólo se calculara, el usuario no se enteraría igual)", () => {
    const cuerpo = configTabSource.slice(
      configTabSource.indexOf("export function ConfigTab"),
    )
    expect(cuerpo).toMatch(/\{jobNotice \?/)
    expect(cuerpo).toMatch(/\{jobNotice\}<\/span>/)
  })

  it("`ConfigTab` sigue sin efectos: el cambio de trabajo se escribe desde el handler", () => {
    // El gate de `bootstrap.test.ts` protege la regresión UX1 (un efecto de montaje resembraba el
    // preset). Se repite aquí porque la tentación natural al conectar esto era un `useEffect` que
    // mirara el config: no hace falta, y ahí está prohibido.
    expect(configTabSource).not.toMatch(/useEffect/)
  })
})
