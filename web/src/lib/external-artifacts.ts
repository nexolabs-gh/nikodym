/**
 * Lo que el usuario trae de fuera: qué se le pide, qué falta y qué se manda al backend (D-PUE-5).
 *
 * Cero lógica de dominio, como el resto de `lib/`: aquí se filtra el catálogo que publica el
 * backend, se comparan nombres de columna y se arma el cuerpo de la petición. Quién decide qué
 * resultado acepta un trabajo, y en qué campo del config se escribe cada respuesta, es el catálogo
 * de `nikodym/ui/jobs.py` — que vive en el backend precisamente para que lo consuma también el
 * preflight, que es Python (D-JOB-3/15).
 */

import type { ConfigDict, ExternalArtifactRef } from "@/lib/api"
import type { ExternalArtifact, Job } from "@/lib/jobs"

/**
 * Un archivo que el usuario ya subió para cubrir un insumo externo.
 *
 * Guarda las columnas del archivo porque son las opciones de los selectores del mapeo: el usuario
 * elige de una lista real en vez de teclear un nombre y descubrir el error al correr.
 */
export interface ExternalInput {
  datasetId: string
  fileName: string
  columns: string[]
  /** `null` = alinear por orden de filas (D-PUE-6), que es una elección con su aviso. */
  keyColumn: string | null
}

/** Clave estable de un artefacto para indexar el estado; nunca se enseña. */
export function artifactKey(artifact: readonly [string, string]): string {
  return `${artifact[0]}.${artifact[1]}`
}

/** Valor del config en un path con puntos, o `undefined` si la clave no existe. */
function valueAtPath(config: ConfigDict, path: string): unknown {
  let node: unknown = config
  for (const segment of path.split(".")) {
    if (typeof node !== "object" || node === null) return undefined
    node = (node as Record<string, unknown>)[segment]
  }
  return node
}

/**
 * Los insumos que este trabajo pide **con el config actual**.
 *
 * ⚠️ El filtro por `when` no es un detalle: el método interno pide un resultado **u otro** según de
 * dónde declares que sale la probabilidad. Pedir los dos obligaría al usuario a subir un archivo
 * que nadie va a leer, y pedir uno fijo rompería el trabajo en silencio al cambiar ese campo.
 */
export function requiredExternalArtifacts(
  job: Job | null,
  config: ConfigDict,
): ExternalArtifact[] {
  if (job === null) return []
  return job.external_artifacts.filter(
    (entry) =>
      entry.when === null || valueAtPath(config, entry.when.path) === entry.when.equals,
  )
}

/** Los insumos pedidos que todavía no tienen archivo: es lo que falta para poder correr. */
export function missingExternalInputs(
  required: readonly ExternalArtifact[],
  inputs: Readonly<Record<string, ExternalInput>>,
): ExternalArtifact[] {
  return required.filter((entry) => inputs[artifactKey(entry.artifact)] === undefined)
}

/**
 * El cuerpo que viaja al backend: una referencia por insumo pedido y ya cubierto.
 *
 * Se deriva de lo **pedido**, no de lo subido: un archivo que quedó de un trabajo anterior no se
 * manda, porque el backend lo declararía inerte y el usuario vería un aviso sobre algo que ya no
 * está pidiendo.
 */
export function externalRefs(
  required: readonly ExternalArtifact[],
  inputs: Readonly<Record<string, ExternalInput>>,
): ExternalArtifactRef[] {
  const refs: ExternalArtifactRef[] = []
  for (const entry of required) {
    const input = inputs[artifactKey(entry.artifact)]
    if (input === undefined) continue
    refs.push({
      artifact: entry.artifact,
      dataset_id: input.datasetId,
      key_column: input.keyColumn,
    })
  }
  return refs
}

/**
 * Los insumos que van a alinearse **por orden de filas**, para avisarlo antes de correr (D-PUE-6).
 *
 * El aviso es obligatorio, no cosmético: si las filas del archivo están en otro orden que la
 * cartera y el conteo coincide, la corrida termina sin un solo error con la probabilidad de cada
 * cliente asignada a otro. Nadie puede detectarlo después; lo único honesto es decirlo antes y
 * dejarlo escrito en el informe.
 */
export function positionalInputs(
  required: readonly ExternalArtifact[],
  inputs: Readonly<Record<string, ExternalInput>>,
): ExternalArtifact[] {
  return required.filter((entry) => {
    const input = inputs[artifactKey(entry.artifact)]
    return input !== undefined && input.keyColumn === null
  })
}

/**
 * ¿La llave elegida para el archivo existe también en la cartera? (D-PUE-6-bis).
 *
 * 🔴 Existe porque emparejar exige la columna en los **dos** lados. Indexar sólo el archivo externo
 * no alinea por etiqueta: cruza —la cartera conserva su índice posicional, así que con llaves
 * numéricas los dos índices coinciden por accidente y la probabilidad de cada operación cae en
 * otra sin que nada falle—. El backend hace el emparejamiento y rechaza con 422 si la columna no
 * está; esto es para decirlo antes, en la misma pantalla donde se arregla.
 *
 * ⚠️ `undefined` en `carteraColumns` significa «todavía no sé qué columnas tiene», no «no tiene
 * ninguna»: sin cartera elegida no se acusa nada, igual que el multiselect distingue «no hay lista»
 * de «la lista está vacía».
 */
export function carteraKeyMismatch(
  keyColumn: string | null,
  carteraColumns: readonly string[] | undefined,
): boolean {
  if (keyColumn === null || carteraColumns === undefined) return false
  return !carteraColumns.includes(keyColumn)
}

/**
 * Config con el mapeo de columnas escrito en los campos que el catálogo declara (D-PUE-5).
 *
 * Escribe en el config y **no en un canal paralelo** porque esos campos ya existen: son los mismos
 * que edita quien trabaja por código. Así el `config_hash` es el mismo por los dos caminos y la
 * paridad UI ↔ código se mantiene sin esfuerzo.
 */
export function withColumnMapping(
  config: ConfigDict,
  paths: readonly string[],
  column: string,
): ConfigDict {
  const next = structuredClone(config) as ConfigDict
  for (const path of paths) {
    const segments = path.split(".")
    const leaf = segments.pop()
    if (leaf === undefined) continue
    let node: Record<string, unknown> = next
    let reachable = true
    for (const segment of segments) {
      const child = node[segment]
      // No se crea la sección si no está: activarla es un gesto de estructura del usuario, y
      // escribirla aquí encendería una sección que él dejó apagada a propósito.
      if (typeof child !== "object" || child === null) {
        reachable = false
        break
      }
      node = child as Record<string, unknown>
    }
    if (reachable) node[leaf] = column
  }
  return next
}
