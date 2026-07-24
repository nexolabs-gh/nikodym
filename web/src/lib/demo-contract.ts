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

/** Superficie única que ambos modos Vite deben implementar sin importar fixtures entre sí. */
export interface DemoRuntime {
  readonly DEMO_MODE: boolean
  readonly demoGetPreset: () => Promise<PresetResponse>
  readonly demoListPresets: () => Promise<PresetsIndexResponse>
  readonly demoGetPresetById: (presetId: string) => Promise<PresetResponse>
  readonly demoValidateConfig: () => Promise<ValidateResponse>
  readonly demoConfigToYaml: () => Promise<ConfigToYamlResponse>
  readonly demoConfigFromYaml: () => Promise<ConfigFromYamlResponse>
  readonly demoListDatasets: () => Promise<DatasetInfo[]>
  readonly demoRunPipeline: () => Promise<RunResponse>
  readonly demoGetResults: () => Promise<ResultsResponse>
  readonly demoGetReport: () => Promise<string>
  readonly demoGetReportPdf: () => Promise<Blob>
  readonly demoGetReportEditable: () => Promise<Blob>
  readonly demoGetReportDocx: () => Promise<Blob>
}
