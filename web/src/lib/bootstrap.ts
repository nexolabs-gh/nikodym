/**
 * Arranque del workspace: carga del schema y, en la demo estática, siembra del preset (SDD-23 §3.2).
 *
 * Vivía dentro de `ConfigTab` (efecto de montaje), lo que acoplaba la vida del config a que el
 * usuario abriera Configuración: quien iba Datos → Ejecutar nunca tenía config sembrado ni
 * validado (botón "Ejecutar corrida" muerto), y al VOLVER a Configuración el efecto re-corría y
 * pisaba las ediciones y el dataset elegido. Ahora el arranque vive aquí y lo consume el provider
 * (`state/appStore.tsx`) UNA sola vez por sesión (`bootstrapOnce`); `ConfigTab` es puro editor.
 *
 * 🔴 **Desde D-JOB-2 el build instalable arranca VACÍO.** Sembrar un preset y su dataset sintético
 * al entrar ponía la demostración por delante de traer datos propios, que es el trabajo real de
 * quien instala esto. Los presets siguen existiendo como «ver un ejemplo con datos de muestra»:
 * camino explícito y secundario, nunca el estado inicial.
 *
 * ⚠️ **La demo estática de `demo.nikodym.cl` sí sigue sembrando, y no es una excepción de
 * conveniencia** (D-JOB-19): esa build no tiene backend, no recalcula y no acepta datasets propios
 * —lo dice su copy en pantalla—, así que arrancarla vacía la dejaría sin poder hacer lo único que
 * pediría. Quien entra ahí sí viene a ver una demostración; el reproche que originó D-JOB-2 es que
 * el instalable se comportara igual. Las dos ramas se separan **aquí**, en el arranque, no con un
 * `if (DEMO_MODE)` esparcido por los componentes.
 *
 * Lógica INYECTABLE y sin React ni DOM (deps explícitas) → testeable en el entorno `node` de
 * vitest. Cero lógica de dominio (SDD-23 §1): el preset lo compone y valida el backend; aquí
 * solo se transporta lo que devuelve.
 */

import { getPreset, type PresetResponse } from "@/lib/api"
import { DEMO_MODE } from "@/lib/demo-runtime"
import { loadSchema, type LoadedSchema } from "@/lib/schema"

/**
 * Qué se sembró en el form (SDD-23 §3.2). `empty` = la sesión arrancó vacía, sin config ni dataset
 * (D-JOB-2: el estado inicial del build instalable); `preset` = configuración de ejemplo pedida
 * explícitamente, o la siembra de la demo estática; `defaults` = "empezar de cero" desde
 * Configuración (elección explícita, ya dentro del workspace); `fallback` = la demo no pudo traer
 * su preset (backend caído); `job` = el usuario eligió un trabajo y se sembró su esqueleto
 * (D-JOB-16); `yaml` = el usuario trajo su propio config con «Cargar YAML».
 *
 * ⚠️ `empty` y `defaults` llevan el MISMO config y son estados distintos a propósito: uno es «aún
 * no has dicho a qué viniste» y el otro «dijiste que partes de cero». Colapsarlos haría que la
 * pantalla de arranque se explique con el copy de una acción que el usuario nunca ejecutó.
 *
 * ⚠️ `yaml` existe porque su ausencia hacía MENTIR al selector de preset: cargar un YAML sólo
 * llamaba a `setConfig`, así que el `seed` seguía diciendo `preset` y el selector de Ejecutar
 * mostraba `f1-estandar-consumo` sobre un config que ya no era ése — y tocarlo resembraba el
 * preset entero, borrando el trabajo del usuario sin avisar. Lo que se sembró es parte del estado
 * del workspace, no un detalle del arranque: quien cambie el config por otro camino debe decirlo
 * aquí.
 */
export type SeedState =
  | { kind: "empty" }
  | {
      /**
       * El usuario eligió un TRABAJO y se sembró su esqueleto (D-JOB-16). No es `preset`: no hay
       * dataset ni parámetros curados detrás, sólo las secciones de ese trabajo con los defaults
       * del motor. Reusar `preset` aquí haría que el selector de Ejecutar afirmara que el config
       * «es» un preset que nadie cargó, que es exactamente la mentira que la variante `yaml` tuvo
       * que venir a corregir.
       */
      kind: "job"
      jobId: string
      label: string
    }
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
  /**
   * ¿Esta build siembra un preset al arrancar? **Sólo la demo estática** (D-JOB-19). Es un dato
   * inyectado y no un `DEMO_MODE` leído aquí dentro por una razón de test: el flag es constante de
   * módulo resuelta en build, así que sin inyectarlo una de las dos ramas sería inalcanzable desde
   * vitest — y la que quedaría sin probar es justo la nueva.
   */
  sembrarAlArrancar: boolean
}

/** Deps reales (backend / fixtures de demo, según `DEMO_MODE`). */
export const DEFAULT_BOOTSTRAP_DEPS: BootstrapDeps = {
  loadSchema,
  getPreset,
  sembrarAlArrancar: DEMO_MODE,
}

/** Estado inicial del workspace tal como lo aplica el provider. */
export interface BootstrapOutcome {
  schema: LoadedSchema
  config: Record<string, unknown>
  /** Dataset recomendado por el preset, o `null` si no se sembró ninguno. */
  datasetId: string | null
  seed: SeedState
}

/** Config vacío del schema, clonado: editarlo no puede mutar el snapshot compartido. */
function configVacio(schema: LoadedSchema): Record<string, unknown> {
  return structuredClone(schema.payload.defaults)
}

/**
 * Arranca el workspace: schema + el config con el que empieza la sesión.
 *
 * En el build instalable (`sembrarAlArrancar: false`) **no se pide ningún preset**: la sesión
 * empieza con el config vacío del schema y sin dataset, y el primer gesto del usuario es traer su
 * archivo (D-JOB-2). En la demo estática se siembra el preset con su dataset, que es lo que esa
 * build puede ofrecer (D-JOB-19).
 *
 * `loadSchema()` nunca lanza (degrada al snapshot local), así que el único fallo posible es el
 * preset de la demo: si no lo entrega, se cae al config vacío (`fallback`) sin romper la app.
 */
export async function bootstrapWorkspace(
  deps: BootstrapDeps = DEFAULT_BOOTSTRAP_DEPS,
): Promise<BootstrapOutcome> {
  const schema = await deps.loadSchema()
  if (!deps.sembrarAlArrancar) {
    return {
      schema,
      config: configVacio(schema),
      datasetId: null,
      seed: { kind: "empty" },
    }
  }
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
      config: configVacio(schema),
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
