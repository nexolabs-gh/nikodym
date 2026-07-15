/**
 * Modo demo (showcase estático) — SDD-23 / lanzamiento F7.
 *
 * Sirve los fixtures de UNA corrida F3 real —el preset `f3-provisiones-consumo`, capturado contra
 * el backend FastAPI (ver `scripts/capture_demo_fixtures.py`)— para que la app funcione end-to-end
 * SIN backend, en el deploy estático de `demo.nikodym.cl`.
 *
 * Se activa SOLO en el build con `VITE_DEMO_MODE=true` (ver `web/.env.demo`). En el build normal
 * la constante es `false` (literal resuelta en build) → el bundler hace *dead-code elimination* de
 * cada rama `if (DEMO_MODE)` de `api.ts`/`schema.ts` y este módulo queda inerte.
 *
 * Regla del SDD respetada: la UI NO reimplementa lógica de dominio. Estos fixtures NO se calculan
 * en el front; son la salida verbatim del motor (`nikodym.run`) sobre el preset F3 de provisiones
 * (`f3-provisiones-consumo`): scorecard + método estándar CMF + método interno + la regla del máximo.
 */

import type {
  ConfigFromYamlResponse,
  ConfigToYamlResponse,
  DatasetInfo,
  PresetResponse,
  PresetsIndexResponse,
  ResultsResponse,
  RunResponse,
  ValidateResponse,
} from "@/lib/api"

import datasetsFixture from "@/fixtures/demo/datasets.json"
import presetFixture from "@/fixtures/demo/preset.json"
import resultsFixture from "@/fixtures/demo/results.json"
import toYamlFixture from "@/fixtures/demo/toyaml.json"
import reportHtml from "@/fixtures/demo/report.html?raw"
// A diferencia de los JSON/HTML (embebidos como valores JS, que el DCE saca del build normal), el
// PDF es binario: `?url` de Vite lo emite como asset estático y devuelve su URL servida. NOTA: el
// asset se emite en AMBOS builds (Vite lo emite al resolver `?url`, no depende del tree-shaking),
// así que el build normal arrastra un PDF huérfano ~478 kB que ningún JS referencia (ver reporte).
import reportPdfUrl from "@/fixtures/demo/report.pdf?url"
// Mismo trato que el PDF (binarios servidos como asset estático): el Word y el ZIP de la base
// editable (`.qmd` + sus figuras, tal como lo arma el endpoint `/md` del backend real).
import reportDocxUrl from "@/fixtures/demo/report.docx?url"
import reportQuartoZipUrl from "@/fixtures/demo/report-quarto.zip?url"

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

/** Id estable del preset empaquetado en la demo (el fixture no siempre trae `id`). */
const DEMO_PRESET_ID: string = preset.id ?? preset.dataset_id

/**
 * Catálogo de presets en la demo estática: expone SOLO el preset que la demo empaqueta (su
 * fixture), catalogado desde él. El backend real sirve todos los presets registrados; la demo,
 * al ser un showcase enlatado, solo puede correr el que tiene capturado.
 */
export function demoListPresets(): Promise<PresetsIndexResponse> {
  return Promise.resolve({
    presets: [
      {
        id: DEMO_PRESET_ID,
        name: preset.name,
        description: preset.description,
        dataset_id: preset.dataset_id,
      },
    ],
  })
}

/** Detalle de un preset en la demo: siempre el fixture empaquetado (id ignorado, hay uno solo). */
export function demoGetPresetById(_presetId: string): Promise<PresetResponse> {
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

/** El PDF de la demo se sirve como asset estático (ver `reportPdfUrl`): se baja como Blob. */
export function demoGetReportPdf(): Promise<Blob> {
  return fetch(reportPdfUrl).then((r) => r.blob())
}

/** La base editable de la demo: el ZIP con el `.qmd` y sus figuras, igual que el backend real. */
export function demoGetReportEditable(): Promise<Blob> {
  return fetch(reportQuartoZipUrl).then((r) => r.blob())
}

/** El Word de la demo, servido como asset estático. */
export function demoGetReportDocx(): Promise<Blob> {
  return fetch(reportDocxUrl).then((r) => r.blob())
}
