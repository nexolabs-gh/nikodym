/**
 * Superficie del modo demo para el build instalable.
 *
 * Vite resuelve `@/lib/demo-runtime` hacia este módulo en el build normal. Así
 * ningún import de `fixtures/demo` entra siquiera al grafo; las ramas son
 * inalcanzables porque `DEMO_MODE` es un literal falso.
 */

import type { DemoRuntime } from "@/lib/demo-contract"

export const DEMO_MODE: boolean = false

function disabled(): never {
  throw new Error("La API demo no está disponible en el build instalable")
}

export async function demoGetPreset(): Promise<never> { return disabled() }
export async function demoListPresets(): Promise<never> { return disabled() }
export async function demoGetPresetById(_presetId: string): Promise<never> { return disabled() }
export async function demoValidateConfig(): Promise<never> { return disabled() }
export async function demoConfigToYaml(): Promise<never> { return disabled() }
export async function demoConfigFromYaml(): Promise<never> { return disabled() }
export async function demoListDatasets(): Promise<never> { return disabled() }
export async function demoRunPipeline(): Promise<never> { return disabled() }
export async function demoGetResults(): Promise<never> { return disabled() }
export async function demoGetReport(): Promise<never> { return disabled() }
export async function demoGetReportPdf(): Promise<never> { return disabled() }
export async function demoGetReportEditable(): Promise<never> { return disabled() }
export async function demoGetReportDocx(): Promise<never> { return disabled() }

/** Gate de tipos compartido, sin importar jamás `demo.ts` ni su árbol de fixtures. */
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
