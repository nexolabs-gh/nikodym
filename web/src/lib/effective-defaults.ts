/**
 * Defaults efectivos: qué PINTA un campo ausente, sin escribirlo (enmienda DEFAULTS-EFECTIVOS-UI).
 *
 * El formulario editaba un config **sparse**: lo que el usuario no toca, no está. Para pintar un
 * campo ausente hacía `value ?? schema.default`, y eso rompía dos veces:
 *
 * 1. `??` confunde `null` EXPLÍCITO con ausencia — apagar algo a propósito se pintaba como si no
 *    se hubiera decidido nada—, y usarlo con truthiness rompe además `false`, `0`, `""` y `[]`.
 * 2. `schema.default` no existe para los submodelos que Pydantic crea con `default_factory`, que
 *    son justo `report.sections`, `report.html`, `model.stepwise`, `selection.correlation`… El
 *    interruptor aparecía apagado mientras el motor corría con `true`.
 *
 * Aquí está la mitad del front del arreglo: un resolver PURO que responde `{displayed, provenance}`
 * a partir de la **presencia de la clave** —nunca de `??` ni de truthiness— y del catálogo
 * `effective_defaults` que publica el backend. `provenance` es lo que permite al widget decir
 * «esto es un valor predeterminado» sin escribirlo en el documento del usuario (D-FX-7/D-FX-8).
 *
 * Lógica PURA (sin React), testeable con vitest.
 */

/**
 * Hoja del catálogo: `has_default=false` OMITE `value`; `true` lo trae aunque sea `null`.
 *
 * `children` sólo lo trae el descriptor de un submodelo **obligatorio** (D-OBL-2), que tiene que
 * decir dos cosas a la vez: que no hay valor que ofrecer para el objeto entero —y por tanto la
 * proyección canónica debe omitirlo— y cuáles son los defaults de dentro, que el formulario sigue
 * necesitando para pintar sus controles.
 */
export interface DefaultDescriptor {
  has_default: boolean
  value?: unknown
  children?: DefaultsMap
}

/** Nodo del catálogo: un descriptor (hoja) o el mapa de campos de un submodelo. */
export type DefaultsNode = DefaultDescriptor | DefaultsMap

/** Mapa `{clave pública del campo: nodo}` de un modelo. */
export interface DefaultsMap {
  [key: string]: DefaultsNode
}

/** El catálogo completo que viaja en `GET /api/schema`. */
export interface EffectiveDefaults {
  version: number
  sections: DefaultsMap
  $defs: Record<string, DefaultsMap>
}

/** Versión del catálogo que este front sabe interpretar (espejo de `EFFECTIVE_DEFAULTS_VERSION`). */
export const EFFECTIVE_DEFAULTS_VERSION = 1

/**
 * De dónde sale lo que se está viendo.
 *
 * - `explicit`: la clave existe en el config; el valor es del usuario (o del preset), literal.
 * - `default`: la clave NO existe y el catálogo dice qué usaría el motor. Valor **virtual**.
 * - `missing`: la clave no existe y no hay default que ofrecer (campo obligatorio, o catálogo
 *   ausente). El control se pinta vacío.
 */
export type Provenance = "explicit" | "default" | "missing"

export interface ResolvedValue {
  displayed: unknown
  provenance: Provenance
}

/** ¿Es un descriptor de hoja y no un mapa de campos? */
export function isDescriptor(node: unknown): node is DefaultDescriptor {
  return (
    typeof node === "object" &&
    node !== null &&
    typeof (node as DefaultDescriptor).has_default === "boolean"
  )
}

/**
 * El catálogo, si es interpretable por este front. Una versión que no se conoce se ignora entera:
 * leerla a medias es peor que no leerla, porque el formulario pintaría defaults inventados.
 */
export function usableCatalog(
  catalog: EffectiveDefaults | undefined,
): EffectiveDefaults | undefined {
  if (!catalog || catalog.version !== EFFECTIVE_DEFAULTS_VERSION) return undefined
  return catalog
}

/**
 * Resuelve qué pintar en un campo (D-FX-7).
 *
 * `stored === undefined` ⟺ **la clave no está en el config**: el config es JSON, así que no hay
 * otra forma de producir `undefined`. Por eso la presencia se decide aquí y no con `??`: `null`,
 * `false`, `0`, `""` y `[]` explícitos son valores del usuario y jamás caen al default.
 */
export function resolveValue(stored: unknown, node: DefaultsNode | undefined): ResolvedValue {
  if (stored !== undefined) return { displayed: stored, provenance: "explicit" }
  if (isDescriptor(node) && node.has_default) {
    return { displayed: node.value, provenance: "default" }
  }
  return { displayed: undefined, provenance: "missing" }
}

/**
 * El mapa de campos de los HIJOS de este nodo, o `undefined` si el nodo es una hoja.
 *
 * Un descriptor normalmente NO tiene hijos —es una hoja—, salvo el de un submodelo obligatorio, que
 * los cuelga de `children` (D-OBL-2). Sin este caso el formulario perdería los defaults de dentro de
 * `data.target` y pintaría vacío un `target_col` que el motor resuelve como `"target"`.
 */
export function childMap(node: DefaultsNode | undefined): DefaultsMap | undefined {
  if (node === undefined) return undefined
  if (isDescriptor(node)) return node.children
  return node
}

/**
 * Proyección canónica de un modelo: el objeto que se escribe al ACTIVAR una sección o un submodelo.
 *
 * Escribe recursivamente **todas** las hojas con default y **omite las obligatorias sin default**
 * (D-FX-8): sembrar un obligatorio con un valor inventado es lo que hacía el activador anterior, y
 * dejaba en el config un valor que el usuario nunca eligió y que el backend igual iba a rechazar.
 *
 * ⚠️ Esta función NO cambió con D-OBL-2, y ahí está la gracia: ya hacía lo correcto: lo que fallaba
 * era que un submodelo obligatorio llegaba como mapa desnudo, y la rama `else` no tiene forma de
 * omitir un mapa. Ahora llega como descriptor `has_default: false` y cae por la rama de arriba, que
 * ya sabía omitirlo. De ahí salía `data.target.bad_rule = {all_of: [], any_of: []}`, que el motor
 * rechaza con «una Rule debe declarar al menos un predicado».
 */
export function canonicalProjection(map: DefaultsMap | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (!map) return out
  for (const [key, node] of Object.entries(map)) {
    if (isDescriptor(node)) {
      if (node.has_default) out[key] = node.value
    } else {
      out[key] = canonicalProjection(node)
    }
  }
  return out
}

/**
 * Baja por la coordenada `sections` del catálogo siguiendo un `path` del formulario.
 *
 * Se detiene en cualquier tramo numérico: una fila de lista no vive en `sections`, sino en la
 * entrada de `$defs` de su modelo de elemento (ahí es donde la busca `FieldRenderer`).
 */
export function nodeAtPath(
  catalog: EffectiveDefaults | undefined,
  path: (string | number)[],
): DefaultsNode | undefined {
  const usable = usableCatalog(catalog)
  if (!usable) return undefined
  let node: DefaultsNode | undefined = usable.sections
  for (const segment of path) {
    if (typeof segment === "number") return undefined
    const map = childMap(node)
    if (!map) return undefined
    node = map[segment]
    if (node === undefined) return undefined
  }
  return node
}

/** El mapa de un `$def` del catálogo por su clave (la misma que referencia `json_schema`). */
export function defMap(
  catalog: EffectiveDefaults | undefined,
  ref: string | undefined,
): DefaultsMap | undefined {
  const usable = usableCatalog(catalog)
  if (!usable || !ref) return undefined
  return usable.$defs[ref]
}
