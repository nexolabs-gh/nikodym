/**
 * Arranque del workspace: carga del schema + SIEMBRA del preset estándar (SDD-23 §3.2).
 *
 * Vivía dentro de `ConfigTab` (efecto de montaje), lo que acoplaba la vida del config a que el
 * usuario abriera Configuración: quien iba Datos → Ejecutar nunca tenía config sembrado ni
 * validado (botón "Ejecutar corrida" muerto), y al VOLVER a Configuración el efecto re-corría y
 * pisaba las ediciones y el dataset elegido. Ahora la siembra vive aquí y la consume el provider
 * (`state/appStore.tsx`) UNA sola vez por sesión (`bootstrapOnce`); `ConfigTab` es puro editor.
 *
 * Lógica INYECTABLE y sin React ni DOM (deps explícitas) → testeable en el entorno `node` de
 * vitest. Cero lógica de dominio (SDD-23 §1): el preset lo compone y valida el backend; aquí
 * solo se transporta lo que devuelve.
 */

import { getPreset, type PresetResponse } from "@/lib/api"
import { loadSchema, type LoadedSchema } from "@/lib/schema"

/**
 * Qué se sembró en el form (SDD-23 §3.2). `preset` = configuración estándar del backend (default);
 * `defaults` = "empezar de cero" con los defaults vacíos del schema (elección explícita);
 * `fallback` = defaults porque el preset no estaba disponible al arrancar (backend caído).
 */
export type SeedState =
  | { kind: "preset"; name: string; datasetId: string }
  | { kind: "defaults" }
  | { kind: "fallback" }

/** Puertas al backend que necesita el arranque; se inyectan para poder testearlo sin red. */
export interface BootstrapDeps {
  loadSchema: () => Promise<LoadedSchema>
  getPreset: () => Promise<PresetResponse>
}

/** Deps reales (backend / fixtures de demo, según `DEMO_MODE`). */
export const DEFAULT_BOOTSTRAP_DEPS: BootstrapDeps = { loadSchema, getPreset }

/** Estado inicial del workspace tal como lo aplica el provider. */
export interface BootstrapOutcome {
  schema: LoadedSchema
  config: Record<string, unknown>
  /** Dataset recomendado por el preset, o `null` si no hubo preset (backend caído). */
  datasetId: string | null
  seed: SeedState
}

/**
 * Arranca el workspace: schema + config sembrado. `loadSchema()` nunca lanza (degrada al
 * snapshot local), así que el único fallo posible es el preset: si el backend no lo entrega,
 * se cae a los defaults del schema (`fallback`) sin romper la app y sin dataset recomendado.
 */
export async function bootstrapWorkspace(
  deps: BootstrapDeps = DEFAULT_BOOTSTRAP_DEPS,
): Promise<BootstrapOutcome> {
  const schema = await deps.loadSchema()
  try {
    const preset = await deps.getPreset()
    return {
      schema,
      config: preset.config,
      // El preset trae el dataset recomendado: con él, entrar basta para poder ejecutar.
      datasetId: preset.dataset_id,
      seed: { kind: "preset", name: preset.name, datasetId: preset.dataset_id },
    }
  } catch {
    return {
      schema,
      config: structuredClone(schema.payload.defaults),
      datasetId: null,
      seed: { kind: "fallback" },
    }
  }
}

/** Siembra en curso/resuelta de ESTA sesión (memo de módulo; ver `bootstrapOnce`). */
let pending: Promise<BootstrapOutcome> | null = null

/**
 * Arranque memoizado: la siembra ocurre UNA sola vez por sesión. Remontar el provider (o el
 * doble montaje de `StrictMode` en dev) no vuelve a pedir el preset ni re-siembra el config,
 * así que no puede pisar lo que el usuario ya editó o eligió.
 */
export function bootstrapOnce(
  deps: BootstrapDeps = DEFAULT_BOOTSTRAP_DEPS,
): Promise<BootstrapOutcome> {
  pending ??= bootstrapWorkspace(deps)
  return pending
}

/** Solo para tests: olvida la siembra memoizada (cada test arranca en una sesión limpia). */
export function resetBootstrapForTests(): void {
  pending = null
}

/**
 * Dataset con el que queda el workspace tras la siembra: el del preset SOLO si el usuario aún
 * no eligió (o subió) uno. Protege una elección hecha en Datos mientras el preset viajaba.
 */
export function seedDatasetId(
  previous: string | null,
  outcome: BootstrapOutcome,
): string | null {
  return previous ?? outcome.datasetId
}
