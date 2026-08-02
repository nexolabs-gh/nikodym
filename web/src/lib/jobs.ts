/**
 * Catálogo de TRABAJOS del lado del front (D-JOB-1/3/15).
 *
 * La FUENTE es el backend (`nikodym/ui/jobs.py`, servido por `GET /api/jobs`): declarar qué
 * secciones e insumos define un trabajo es dominio, y SDD-23 §1 lo prohíbe en el front. Aquí sólo
 * se transporta lo que devuelve, con un fixture bundleado como respaldo —mismo patrón que
 * `schema.ts`, y por la misma razón: sin catálogo no hay por dónde entrar, así que un backend caído
 * no puede dejar la landing en blanco—.
 *
 * Cero lógica de dominio: las tres funciones de abajo filtran, proyectan y comparan conjuntos de
 * claves. Ninguna decide qué es un trabajo.
 */

import { API_BASE } from "@/lib/api"
import {
  canonicalProjection,
  childMap,
  nodeAtPath,
  type EffectiveDefaults,
} from "@/lib/effective-defaults"
import { CONFIG_SECTIONS, type ConfigSectionDef } from "@/lib/schema"
import fixtureJobs from "@/fixtures/jobs.json"

/**
 * Una decisión que el motor NO puede tomar por nadie (D-OBL-6).
 *
 * `path` es la coordenada interna —la misma que indexa el config— y no se enseña nunca: lo que el
 * usuario lee es `question` (D-OBL-9).
 */
export interface RequiredDecision {
  path: string
  question: string
  help: string
}

/**
 * Un rol de columna del insumo externo: qué se pregunta y dónde se escribe la respuesta (D-PUE-5).
 *
 * `config_paths` es plural porque dos secciones que leen el MISMO archivo nombran la misma columna
 * —`performance` y `stability` piden ambas la de la probabilidad—, y preguntarlo dos veces sería
 * absurdo. Una respuesta, varios campos.
 */
export interface ExternalColumnRole {
  question: string
  config_paths: string[]
}

/**
 * Lo que un trabajo acepta traer de fuera, en forma máquina-legible (D-PUE-2).
 *
 * `artifact` es la pareja `(dominio, clave)` del motor y **no se enseña nunca**: lo que el usuario
 * lee es `label` y las preguntas. Es la misma separación que `path` vs `question` en una decisión
 * obligatoria, y por la misma razón.
 */
export interface ExternalArtifact {
  artifact: [string, string]
  label: string
  /** Condición del config que hace pertinente esta clave; `null` = siempre. */
  when: { path: string; equals: string } | null
  key_question: string
  columns: ExternalColumnRole[]
}

/** Un trabajo del catálogo, tal como lo publica `GET /api/jobs`. */
export interface Job {
  id: string
  /** Nombre de negocio (D-JOB-14): como lo llaman los equipos dentro de un banco. */
  label: string
  description: string
  /** Claves de sección del formulario que este trabajo muestra. */
  sections: string[]
  /** Secciones que necesitaría y que el formulario NO ofrece hoy; por eso no está disponible. */
  missing_sections: string[]
  /** Insumo que hay que traer de fuera, en lenguaje de negocio; `null` si ninguno. */
  external_input: string | null
  /**
   * El mismo insumo, en forma máquina-legible: qué claves acepta y qué hay que mapear (D-PUE-2).
   *
   * ⚠️ Puede estar vacío con `external_input` no nulo, y no es una incoherencia: «PD lifetime»
   * describe un insumo **opcional del método** que ningún paso requiere, así que no hay clave que
   * traer. Los dos campos miden cosas distintas.
   */
  external_artifacts: ExternalArtifact[]
  /** País cuya normativa impone el cálculo; `null` = neutral (D-JOB-8). */
  jurisdiction_code: string | null
  jurisdiction_label: string | null
  status: "available" | "unavailable"
  /** Por qué no se puede iniciar, sin jerga (D-JOB-6); `null` si está disponible. */
  unavailable_reason: string | null
  /** Lo que sólo el usuario puede decidir sobre SUS datos, en idioma de negocio (D-OBL-6). */
  required_decisions: RequiredDecision[]
}

export interface JobsPayload {
  jobs: Job[]
}

/** Snapshot bundleado del catálogo (respaldo offline y de la demo estática). */
export const FIXTURE_JOBS = fixtureJobs as unknown as JobsPayload

/** Fetch crudo de `GET /api/jobs` (lanza en error de red/HTTP). */
export async function fetchJobs(): Promise<JobsPayload> {
  const res = await fetch(`${API_BASE}/api/jobs`)
  if (!res.ok) throw new Error(`HTTP ${res.status} al pedir /api/jobs`)
  return (await res.json()) as JobsPayload
}

/**
 * Catálogo para la landing: el del backend, o el snapshot si no responde.
 *
 * Nunca lanza y nunca devuelve vacío: quedarse sin trabajos es quedarse sin entrada a la
 * aplicación, y un catálogo levemente viejo es infinitamente mejor que una pantalla sin botones.
 */
export async function loadJobs(): Promise<Job[]> {
  try {
    const live = await fetchJobs()
    if (live.jobs.length > 0) return live.jobs
  } catch {
    /* backend caído: sigue el snapshot */
  }
  return FIXTURE_JOBS.jobs
}

/**
 * Secciones del formulario que muestra un trabajo, **en el orden canónico de `CONFIG_SECTIONS`**
 * (que es el del pipeline). Sin trabajo elegido se ven todas: es lo que corresponde a quien trajo
 * un config que no calza con ninguno (D-JOB-17), y también el estado de la demo estática.
 *
 * ⚠️ Filtra; no reordena. Si tomara el orden de `job.sections`, el sidebar dependería de cómo se
 * escribió el catálogo y dos trabajos podrían pintar las mismas secciones en orden distinto.
 */
export function sectionsOfJob(job: Job | null): ConfigSectionDef[] {
  if (job === null) return CONFIG_SECTIONS
  const permitidas = new Set(job.sections)
  return CONFIG_SECTIONS.filter((s) => permitidas.has(s.key))
}

/**
 * Config con el que empieza un trabajo (D-JOB-16): sus secciones activas con la proyección
 * canónica de sus defaults, el resto en `null`, y **ningún dataset**.
 *
 * Activar una sección es un gesto de ESTRUCTURA (D-FX-8), así que se escriben las hojas con
 * default de su proyección canónica — exactamente lo que hace el interruptor de sección en
 * `ConfigTab`, y por eso el esqueleto y activar a mano producen el mismo config.
 *
 * Sin catálogo de defaults efectivos la sección se deja como venía: sembrarla con `{}` produciría
 * una sección a medias que el motor rechaza, y un config inválido al entrar sería peor que uno
 * apagado.
 */
export function jobSkeleton(
  base: Record<string, unknown>,
  job: Job,
  catalogo: EffectiveDefaults | undefined,
): Record<string, unknown> {
  const skeleton = structuredClone(base)
  for (const section of job.sections) {
    const canonica = childMap(nodeAtPath(catalogo, [section]))
    if (canonica === undefined) continue
    skeleton[section] = canonicalProjection(canonica)
  }
  recortarCapitulosDelInforme(skeleton, job)
  return skeleton
}

/**
 * Deja en `report.sections.required_sections` sólo los capítulos que este trabajo produce (D-OBL-11).
 *
 * 🔴 **Sin esto ningún trabajo llega a `done`, y se descubría sólo corriendo.** El default del motor
 * son ocho capítulos obligatorios, entre ellos `eda`; un scorecard declara nueve secciones y `eda`
 * no está entre ellas —el formulario ni siquiera la ofrece—, así que el informe exigía una card que
 * la corrida no iba a producir y el paso `report` moría con `missing_policy: error`. El preset F1 no
 * lo sufría porque declara sus siete capítulos a mano.
 *
 * El criterio no es nuevo: es el de D-FX-3 —el informe exige sólo lo de los dominios activos de la
 * invocación— aplicado al sitio que faltaba, la siembra. Y no toca el default del motor, que sigue
 * siendo el correcto para quien usa la librería por código con el pipeline completo.
 *
 * ⚠️ Se recorta, nunca se añade: si un capítulo del default no está en el trabajo se quita, pero no
 * se mete uno que el default no pedía. Sembrar un capítulo que el usuario no eligió sería la mentira
 * simétrica.
 */
function recortarCapitulosDelInforme(
  skeleton: Record<string, unknown>,
  job: Job,
): void {
  const report = skeleton.report
  if (typeof report !== "object" || report === null) return
  const sections = (report as Record<string, unknown>).sections
  if (typeof sections !== "object" || sections === null) return
  const exigidos = (sections as Record<string, unknown>).required_sections
  if (!Array.isArray(exigidos)) return
  const suyas = new Set(job.sections)
  ;(sections as Record<string, unknown>).required_sections = exigidos.filter(
    (capitulo) => typeof capitulo === "string" && suyas.has(capitulo),
  )
}

/**
 * Estado de una decisión obligatoria frente al config actual (D-OBL-6).
 *
 * `answered` se decide por **presencia de la clave**, nunca por truthiness ni por `??`: es el mismo
 * criterio de D-FX-7, y por la misma razón. Un `bad_rule` que el usuario dejó explícitamente vacío,
 * un `0` o un `false` son respuestas suyas; sólo la ausencia significa «esto sigue sin decidirse».
 */
export interface DecisionStatus extends RequiredDecision {
  answered: boolean
}

/** Baja por un path con puntos y dice si la clave EXISTE, sin mirar su valor. */
function hasAtPath(config: Record<string, unknown>, path: string): boolean {
  let node: unknown = config
  for (const segment of path.split(".")) {
    if (typeof node !== "object" || node === null) return false
    if (!(segment in (node as Record<string, unknown>))) return false
    node = (node as Record<string, unknown>)[segment]
  }
  return node !== undefined
}

/**
 * Las decisiones del trabajo con su estado frente al config actual.
 *
 * Devuelve **todas**, no sólo las pendientes: la lista completa es lo que convierte la tarjeta en un
 * resumen de «a qué viniste y qué te falta» en vez de en una lista de errores que desaparece. Ver
 * una decisión ya respondida, con su marca, es información — y hace que la tarjeta no parpadee
 * entrando y saliendo mientras se trabaja.
 */
export function decisionStatuses(
  job: Job | null,
  config: Record<string, unknown> | null,
): DecisionStatus[] {
  if (job === null || config === null) return []
  return job.required_decisions.map((decision) => ({
    ...decision,
    answered: hasAtPath(config, decision.path),
  }))
}

/**
 * Trabajo al que corresponde un config traído de fuera (D-JOB-17), o `null` si no calza con
 * ninguno.
 *
 * Es la regla que cierra el caso «cargo un YAML con secciones que este trabajo no muestra» **sin
 * un parche en la vista**: en vez de añadir un aviso de sección ajena, el config selecciona su
 * trabajo. Si ninguno lo contiene, la sesión queda sin trabajo y se ve el formulario completo —es
 * el config del usuario, no el nuestro, y esconderle parte de lo que él mismo trajo sería la
 * mentira contraria—.
 *
 * Criterio: el trabajo MÁS PEQUEÑO que contenga todas las secciones activas. El más pequeño y no
 * el primero, porque un config de sólo survival lo contienen tanto «PD lifetime» como
 * «Provisiones IFRS 9», y el correcto es el que no añade pantallas que el config no usa.
 *
 * ⚠️ Esto NO contradice el «los trabajos no se derivan de las secciones no nulas» de D-JOB-1. Ahí
 * la regla veta derivarlo como mecanismo general —con «empezar de cero» dejaría el sidebar vacío—;
 * cargar un YAML es un gesto explícito con señal explícita.
 */
export function jobForConfig(
  jobs: readonly Job[],
  config: Record<string, unknown>,
): Job | null {
  const activas = CONFIG_SECTIONS.map((s) => s.key).filter((key) => {
    const value = config[key]
    return value !== null && value !== undefined
  })
  if (activas.length === 0) return null
  const candidatos = jobs.filter((job) => {
    const suyas = new Set(job.sections)
    return activas.every((key) => suyas.has(key))
  })
  if (candidatos.length === 0) return null
  return candidatos.reduce((mejor, job) =>
    job.sections.length < mejor.sections.length ? job : mejor,
  )
}

/**
 * Qué le hace al trabajo de la sesión un config traído de fuera.
 *
 * `job` es lo que hay que dejar en el store —`null` incluido, que significa «sin trabajo, formulario
 * completo»— y `cambia` dice si eso difiere de lo que el usuario tenía. Los dos datos, y no sólo el
 * primero, porque **el usuario tiene que enterarse**: cambiar de trabajo reescribe el sidebar
 * entero, y hacerlo en silencio deja a alguien mirando una navegación que no pidió sin saber por
 * qué. Cuando no cambia no hay nada que decir, y un aviso que sobra se aprende a ignorar.
 */
export interface JobSwitch {
  job: Job | null
  cambia: boolean
}

/**
 * El trabajo que corresponde a un config traído de fuera, contrastado con el activo (D-JOB-17).
 *
 * Manda el config del usuario: si su archivo corresponde a otro trabajo, la sesión pasa a ése. No es
 * una preferencia sobre la suya —el archivo *es* suya—, y la alternativa (conservar el trabajo
 * elegido) es justo el estado que D-JOB-17 existe para evitar: un sidebar que esconde secciones que
 * el propio usuario acaba de traer.
 *
 * Se compara por `id` y no por identidad de objeto: el catálogo se vuelve a pedir en cada carga, así
 * que el mismo trabajo llega como un objeto distinto y comparar referencias daría «cambió» siempre.
 */
export function jobSwitchForConfig(
  jobs: readonly Job[],
  config: Record<string, unknown>,
  activo: Job | null,
): JobSwitch {
  const job = jobForConfig(jobs, config)
  return { job, cambia: (job?.id ?? null) !== (activo?.id ?? null) }
}
