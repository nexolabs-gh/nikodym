/**
 * Modo demo (showcase estático) — SDD-23 / lanzamiento F7.
 *
 * Sirve los fixtures de UNA corrida F1 real (capturados contra el backend FastAPI) para que la
 * app funcione end-to-end SIN backend, en el deploy estático de `demo.nikodym.cl`.
 *
 * Se activa SOLO en el build con `VITE_DEMO_MODE=true` (ver `web/.env.demo`). En el build normal
 * la constante es `false` (literal resuelta en build) → el bundler hace *dead-code elimination* de
 * cada rama `if (DEMO_MODE)` de `api.ts`/`schema.ts` y este módulo queda inerte.
 *
 * Regla del SDD respetada: la UI NO reimplementa lógica de dominio. Estos fixtures NO se calculan
 * en el front; son la salida verbatim del motor (`nikodym.run`) sobre el preset estándar F1.
 */

import type {
  ConfigFromYamlResponse,
  ConfigToYamlResponse,
  DatasetInfo,
  PresetResponse,
  ResultsResponse,
  RunResponse,
  ValidateResponse,
} from "@/lib/api"

import datasetsFixture from "@/fixtures/demo/datasets.json"
import presetFixture from "@/fixtures/demo/preset.json"
import resultsFixture from "@/fixtures/demo/results.json"
import toYamlFixture from "@/fixtures/demo/toyaml.json"
import reportHtml from "@/fixtures/demo/report.html?raw"

/** Activo solo en el build de la demo estática (`VITE_DEMO_MODE=true`). */
export const DEMO_MODE: boolean = import.meta.env.VITE_DEMO_MODE === "true"

const preset = presetFixture as unknown as PresetResponse
const datasets = datasetsFixture as unknown as DatasetInfo[]
const results = resultsFixture as unknown as ResultsResponse
const toYaml = toYamlFixture as unknown as ConfigToYamlResponse

/** run_id real de la corrida capturada: mantiene coherentes run → results → report. */
const DEMO_RUN_ID: string = results.run_id ?? "demo-run"

export function demoGetPreset(): Promise<PresetResponse> {
  return Promise.resolve(preset)
}

/** En demo el config no se recomputa: se acepta el preset como válido para abrir el gate de Ejecutar. */
export function demoValidateConfig(): Promise<ValidateResponse> {
  return Promise.resolve({
    valid: true,
    config_hash: preset.config_hash,
    errors: [],
  })
}

export function demoConfigToYaml(): Promise<ConfigToYamlResponse> {
  return Promise.resolve(toYaml)
}

export function demoConfigFromYaml(): Promise<ConfigFromYamlResponse> {
  return Promise.resolve({
    config: preset.config,
    config_hash: preset.config_hash,
  })
}

export function demoListDatasets(): Promise<DatasetInfo[]> {
  return Promise.resolve(datasets)
}

export function demoRunPipeline(): Promise<RunResponse> {
  return Promise.resolve({ run_id: DEMO_RUN_ID, status: "done" as const })
}

export function demoGetResults(): Promise<ResultsResponse> {
  return Promise.resolve(results)
}

export function demoGetReport(): Promise<string> {
  return Promise.resolve(reportHtml)
}
