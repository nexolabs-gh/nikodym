/**
 * Modo demo (showcase estático) — SDD-23 / lanzamiento F7.
 *
 * Sirve los fixtures de corridas REALES del motor para que la app funcione end-to-end SIN backend,
 * en el deploy estático de `demo.nikodym.cl`. Es MULTI-PRESET: empaqueta dos corridas capturadas
 * contra el backend FastAPI (ver `scripts/capture_demo_fixtures*.py`):
 *   - `f1-estandar-consumo` — scorecard de comportamiento puro (sin provisiones).
 *   - `f4-ifrs9-retail` — provisiones IFRS 9 / ECL de tres etapas (SDD-16, experimental).
 *
 * ⚠️ La corrida F3 (provisiones CMF, la regla del máximo B-1) SALIÓ de la demo con D-JUR-9.7: su
 * preset es un caso de referencia y el catálogo instalable ya no lo ofrece, así que dejarlo
 * sembrado en la demo pública habría dicho lo contrario que el paquete. El motor, sus tests, su
 * evidencia y la página «Aterrizar una norma local» siguen intactos (D-JUR-9.9); lo que se retiró
 * es una corrida capturada, recuperable en el historial. F5 (provisión interna sobre cartera
 * genérica) entra con la recaptura única de la release, que tiene su propio OK (D-GOB-9).
 *
 * El preset ACTIVO se rastrea en un `activePresetId` de módulo: `demoGetPresetById` (que dispara el
 * selector de Ejecutar) lo mueve, y `demoGetResults`/`demoConfigToYaml`/`demoValidateConfig`/
 * `demoRunPipeline` devuelven el set del preset elegido. LOS DOS presets traen informe (los cuatro
 * entregables); un preset futuro sin informe degrada como el backend real (404), sin romper la UI.
 * El preset por defecto que siembra el arranque es F1, el scorecard.
 *
 * Se activa SOLO en el build con `VITE_DEMO_MODE=true` (ver `web/.env.demo`). En el build normal la
 * constante es `false` (literal resuelta en build) → el bundler hace *dead-code elimination* de cada
 * rama `if (DEMO_MODE)` de `api.ts`/`schema.ts` y este módulo queda inerte (fixtures fuera del bundle).
 *
 * Regla del SDD respetada: la UI NO reimplementa lógica de dominio. Estos fixtures NO se calculan en
 * el front; son la salida verbatim del motor (`nikodym.run`) sobre cada preset.
 */

import { ApiError } from "@/lib/api"
import type { DemoRuntime } from "@/lib/demo-contract"
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
import presetIfrs9Fixture from "@/fixtures/demo/preset-ifrs9.json"
import resultsIfrs9Fixture from "@/fixtures/demo/results-ifrs9.json"
import toYamlIfrs9Fixture from "@/fixtures/demo/toyaml-ifrs9.json"
import presetF1Fixture from "@/fixtures/demo/preset-f1.json"
import resultsF1Fixture from "@/fixtures/demo/results-f1.json"
import toYamlF1Fixture from "@/fixtures/demo/toyaml-f1.json"
// Informe IFRS 9 (F4): los cuatro entregables, capturados por capture_demo_fixtures_ifrs9.py.
//
// A diferencia de los JSON/HTML (embebidos como valores JS, que el DCE saca del build normal), el
// PDF es binario: `?url` de Vite lo emite como asset estático y devuelve su URL servida. NOTA: el
// asset se emite en AMBOS builds (Vite lo emite al resolver `?url`, no depende del tree-shaking),
// así que el build normal arrastra un PDF huérfano que ningún JS referencia (ver reporte). Mismo
// trato para el Word y el ZIP de la base editable (`.qmd` + sus figuras, tal como lo arma el
// endpoint `/md` del backend real).
import reportIfrs9Html from "@/fixtures/demo/report-ifrs9.html?raw"
import reportIfrs9PdfUrl from "@/fixtures/demo/report-ifrs9.pdf?url"
import reportIfrs9DocxUrl from "@/fixtures/demo/report-ifrs9.docx?url"
import reportIfrs9QuartoZipUrl from "@/fixtures/demo/report-quarto-ifrs9.zip?url"
// Informe scorecard (F1): mismos cuatro entregables, capturados por capture_demo_fixtures_f1.py.
import reportF1Html from "@/fixtures/demo/report-f1.html?raw"
import reportF1PdfUrl from "@/fixtures/demo/report-f1.pdf?url"
import reportF1DocxUrl from "@/fixtures/demo/report-f1.docx?url"
import reportF1QuartoZipUrl from "@/fixtures/demo/report-quarto-f1.zip?url"

/** Activo solo en el build de la demo estática (`VITE_DEMO_MODE=true`). */
export const DEMO_MODE: boolean = import.meta.env.VITE_DEMO_MODE === "true"

/** Los cuatro entregables de un informe, servidos como assets estáticos. */
interface DemoReport {
  html: string
  pdfUrl: string
  docxUrl: string
  editableZipUrl: string
}

/** Un preset empaquetado en la demo: su detalle, su corrida real, su YAML y (si tiene) su informe. */
interface DemoBundle {
  preset: PresetResponse
  results: ResultsResponse
  toYaml: ConfigToYamlResponse
  /** run_id real de la corrida capturada: mantiene coherentes run → results. */
  runId: string
  /** Entregables del informe, o `null` si el preset no genera reporte. */
  report: DemoReport | null
}

const presetF4 = presetIfrs9Fixture as unknown as PresetResponse
const presetF1 = presetF1Fixture as unknown as PresetResponse
const resultsF4 = resultsIfrs9Fixture as unknown as ResultsResponse
const resultsF1 = resultsF1Fixture as unknown as ResultsResponse
const toYamlF4 = toYamlIfrs9Fixture as unknown as ConfigToYamlResponse
const toYamlF1 = toYamlF1Fixture as unknown as ConfigToYamlResponse
const datasets = datasetsFixture as unknown as DatasetInfo[]

/** Id estable de un preset (el fixture no siempre trae `id` → cae al `dataset_id`). */
function presetIdOf(preset: PresetResponse): string {
  return preset.id ?? preset.dataset_id
}

const F1_ID = presetIdOf(presetF1)
const F4_ID = presetIdOf(presetF4)

/** Registro de presets empaquetados, por id. */
const BUNDLES: Record<string, DemoBundle> = {
  [F1_ID]: {
    preset: presetF1,
    results: resultsF1,
    toYaml: toYamlF1,
    runId: resultsF1.run_id ?? "demo-run-f1",
    report: {
      html: reportF1Html,
      pdfUrl: reportF1PdfUrl,
      docxUrl: reportF1DocxUrl,
      editableZipUrl: reportF1QuartoZipUrl,
    },
  },
  [F4_ID]: {
    preset: presetF4,
    results: resultsF4,
    toYaml: toYamlF4,
    runId: resultsF4.run_id ?? "demo-run-f4",
    report: {
      html: reportIfrs9Html,
      pdfUrl: reportIfrs9PdfUrl,
      docxUrl: reportIfrs9DocxUrl,
      editableZipUrl: reportIfrs9QuartoZipUrl,
    },
  },
}

/** Orden estable del selector: scorecard F1 primero, IFRS 9 F4 (D-JUR-9.7; F5 con la release). */
const PRESET_ORDER: readonly string[] = [F1_ID, F4_ID]

/**
 * Preset ACTIVO de la demo (single-flight de módulo). Default = F1, el scorecard: es el trabajo que
 * abre el catálogo y el único preset de fábrica que la demo puede sembrar sin ofrecer un caso de
 * referencia (D-JUR-9.7). `demoGetPresetById` lo mueve al elegir en el selector.
 */
let activePresetId: string = F1_ID

/** El bundle del preset activo (cae a F1 si el id activo no estuviera registrado, por robustez). */
function activeBundle(): DemoBundle {
  return BUNDLES[activePresetId] ?? BUNDLES[F1_ID]
}

/** Error de "esta corrida no generó reporte" (404): reusa el mapeo del backend real (ver `report.ts`). */
function noReportError(): ApiError {
  return new ApiError("Este preset no genera un informe.", 404)
}

/** Preset estándar que siembra el arranque: SIEMPRE F1 (el scorecard, D-JUR-9.7). */
export function demoGetPreset(): Promise<PresetResponse> {
  return Promise.resolve(BUNDLES[F1_ID].preset)
}

/**
 * Catálogo de presets en la demo estática: expone LOS DOS presets empaquetados (F1 scorecard y F4
 * IFRS 9), en orden estable. El backend real sirve los presets que OFRECE —que desde D-JUR-9 ya no
 * incluyen el de referencia—; la demo, al ser un showcase enlatado, expone los que tiene
 * capturados.
 */
export function demoListPresets(): Promise<PresetsIndexResponse> {
  return Promise.resolve({
    presets: PRESET_ORDER.map((id) => {
      const { preset } = BUNDLES[id]
      return {
        id,
        name: preset.name,
        description: preset.description,
        dataset_id: preset.dataset_id,
      }
    }),
  })
}

/**
 * Detalle de un preset por id. RASTREA el preset elegido: mueve el `activePresetId` para que run/
 * results/yaml/validate devuelvan su set. Un id desconocido —incluido el de la corrida F3 que ya no
 * viaja— cae a F1 (no rompe la demo, ni con un `?preset=` viejo en la URL).
 */
export function demoGetPresetById(presetId: string): Promise<PresetResponse> {
  if (presetId in BUNDLES) activePresetId = presetId
  return Promise.resolve((BUNDLES[presetId] ?? BUNDLES[F1_ID]).preset)
}

/**
 * En demo el config no se recomputa: el preset ACTIVO se acepta como válido (abre el gate de
 * Ejecutar).
 *
 * `pipeline: null` —«sin información»— y no un `executable: true` fabricado: resolver el pipeline
 * exige el motor, que aquí no existe. Un veredicto inventado sobreviviría a cualquier edición del
 * config en la demo y seguiría diciendo que todo corre, que es peor que no decir nada. El front
 * trata `null` como «nada que advertir», así que la demo se comporta igual que antes.
 */
export function demoValidateConfig(): Promise<ValidateResponse> {
  return Promise.resolve({
    valid: true,
    config_hash: activeBundle().preset.config_hash,
    errors: [],
    pipeline: null,
  })
}

export function demoConfigToYaml(): Promise<ConfigToYamlResponse> {
  return Promise.resolve(activeBundle().toYaml)
}

export function demoConfigFromYaml(): Promise<ConfigFromYamlResponse> {
  const { preset } = activeBundle()
  return Promise.resolve({
    config: preset.config,
    config_hash: preset.config_hash,
  })
}

/**
 * Catálogo de datasets: el registro completo del backend (recapturado con los fixtures F1), que ya
 * incluye `ifrs9_retail_latam`, el dataset propio que recomienda el preset F4. La demo no tiene
 * backend que materialice filas, así que Datos degrada sin preview de datos; al elegir cualquier
 * preset, Ejecutar queda habilitado igual (el `datasetId` del preset abre el gate), sin romperse.
 */
export function demoListDatasets(): Promise<DatasetInfo[]> {
  return Promise.resolve(datasets)
}

export function demoRunPipeline(): Promise<RunResponse> {
  return Promise.resolve({ run_id: activeBundle().runId, status: "done" as const })
}

export function demoGetResults(): Promise<ResultsResponse> {
  return Promise.resolve(activeBundle().results)
}

/** HTML del informe del preset activo; 404 si su config no genera reporte. */
export function demoGetReport(): Promise<string> {
  const { report } = activeBundle()
  return report === null ? Promise.reject(noReportError()) : Promise.resolve(report.html)
}

/** El PDF del preset activo (asset estático → Blob); 404 si el preset no genera reporte. */
export function demoGetReportPdf(): Promise<Blob> {
  const { report } = activeBundle()
  if (report === null) return Promise.reject(noReportError())
  return fetch(report.pdfUrl).then((r) => r.blob())
}

/** El ZIP de la base editable del preset activo; 404 si el preset no genera reporte. */
export function demoGetReportEditable(): Promise<Blob> {
  const { report } = activeBundle()
  if (report === null) return Promise.reject(noReportError())
  return fetch(report.editableZipUrl).then((r) => r.blob())
}

/** El Word del preset activo (asset estático); 404 si el preset no genera reporte. */
export function demoGetReportDocx(): Promise<Blob> {
  const { report } = activeBundle()
  if (report === null) return Promise.reject(noReportError())
  return fetch(report.docxUrl).then((r) => r.blob())
}

/** Gate de tipos compartido: demo real y stub instalable satisfacen la misma superficie. */
export const DEMO_RUNTIME = {
  DEMO_MODE,
  demoGetPreset,
  demoListPresets,
  demoGetPresetById,
  demoValidateConfig,
  demoConfigToYaml,
  demoConfigFromYaml,
  demoListDatasets,
  demoRunPipeline,
  demoGetResults,
  demoGetReport,
  demoGetReportPdf,
  demoGetReportEditable,
  demoGetReportDocx,
} satisfies DemoRuntime

/** Solo para tests: reinicia el preset activo al default (F1). Cada test arranca limpio. */
export function resetDemoActivePresetForTests(): void {
  activePresetId = F1_ID
}
