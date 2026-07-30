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
 * `fallback` = defaults porque el preset no estaba disponible al arrancar (backend caído);
 * `yaml` = el usuario trajo su propio config con «Cargar YAML».
 *
 * ⚠️ `yaml` existe porque su ausencia hacía MENTIR al selector de preset: cargar un YAML sólo
 * llamaba a `setConfig`, así que el `seed` seguía diciendo `preset` y el selector de Ejecutar
 * mostraba `f1-estandar-consumo` sobre un config que ya no era ése — y tocarlo resembraba el
 * preset entero, borrando el trabajo del usuario sin avisar. Lo que se sembró es parte del estado
 * del workspace, no un detalle del arranque: quien cambie el config por otro camino debe decirlo
 * aquí.
 */
export type SeedState =
  | {
      kind: "preset"
      name: string
      datasetId: string
      /**
       * Huella del config TAL COMO LO SEMBRÓ el preset. Sirve para una sola pregunta: ¿el config
       * que hay ahora sigue siendo el del preset, o el usuario lo editó? Sin ella, el selector de
       * la pestaña Ejecutar afirma «f1-estandar-consumo» sobre un config que ya no lo es, y
       * cambiar de preset descarta el trabajo sin avisar.
       */
      fingerprint?: string
    }
  | { kind: "defaults" }
  | { kind: "fallback" }
  | { kind: "yaml"; fileName: string }

/**
 * Huella estable de un config para comparar «¿cambió?», no para identificarlo.
 *
 * NO es el `config_hash`: ése lo calcula el backend con su canonicalización (y es lo que va al
 * lineage). Éste es local, barato y sólo se compara consigo mismo. Las claves se ordenan para que
 * reordenar el objeto no cuente como edición.
 */
export function configFingerprint(config: unknown): string {
  const canonico = (valor: unknown): unknown => {
    if (Array.isArray(valor)) return valor.map(canonico)
    if (valor && typeof valor === "object") {
      return Object.fromEntries(
        Object.entries(valor as Record<string, unknown>)
          .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
          .map(([k, v]) => [k, canonico(v)]),
      )
    }
    return valor
  }
  return JSON.stringify(canonico(config))
}

/**
 * ¿El config actual dejó de ser el que sembró el preset? `false` si no hay preset sembrado o si la
 * siembra no dejó huella (una sesión que venga de un `seed` viejo): ante la duda **no se acusa** de
 * editado, que es el error que se lee como un aviso falso.
 */
export function configEditadoRespectoDelPreset(
  seed: SeedState | null,
  config: unknown,
): boolean {
  if (seed?.kind !== "preset" || seed.fingerprint === undefined) return false
  return configFingerprint(config) !== seed.fingerprint
}

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
      seed: {
        kind: "preset",
        name: preset.name,
        datasetId: preset.dataset_id,
        fingerprint: configFingerprint(preset.config),
      },
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
