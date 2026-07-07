/**
 * Estado del config en construcción (SDD-23 §3.5): el config es un **objeto JSON
 * plano** en el estado del cliente; se edita de forma inmutable y (en B23.5) se
 * re-valida en el backend. NADA de validación de dominio aquí — solo estructura.
 *
 * Lógica PURA (sin React), testeable con vitest.
 */

export type PathSegment = string | number
export type Path = PathSegment[]

/** Config editable: árbol JSON-able arbitrario. */
export type ConfigValue =
  | null
  | boolean
  | number
  | string
  | ConfigValue[]
  | { [key: string]: ConfigValue }

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

/** Lee el valor en `path`, o `undefined` si algún tramo no existe. */
export function getAtPath(obj: unknown, path: Path): unknown {
  let current: unknown = obj
  for (const key of path) {
    if (Array.isArray(current) && typeof key === "number") {
      current = current[key]
    } else if (isPlainObject(current)) {
      current = current[key as string]
    } else {
      return undefined
    }
  }
  return current
}

/**
 * Devuelve una copia de `obj` con `value` fijado en `path` (inmutable: clona solo
 * el camino tocado). Crea los contenedores intermedios que falten (objeto por
 * defecto; array si el tramo es numérico).
 */
export function setAtPath<T>(obj: T, path: Path, value: unknown): T {
  if (path.length === 0) return value as T
  const [head, ...rest] = path
  const base: unknown = obj

  if (typeof head === "number") {
    const arr = Array.isArray(base) ? [...base] : []
    arr[head] = rest.length === 0 ? value : setAtPath(arr[head], rest, value)
    return arr as unknown as T
  }

  const record: Record<string, unknown> = isPlainObject(base) ? { ...base } : {}
  record[head] =
    rest.length === 0 ? value : setAtPath(record[head], rest, value)
  return record as unknown as T
}

/**
 * Devuelve una copia de `obj` SIN la clave/índice en `path` (inmutable: clona solo el
 * camino tocado). Si algún tramo no existe, devuelve `obj` sin cambios. Complementa a
 * `setAtPath`; se usa donde borrar la clave (en vez de dejar `null`) refleja mejor lo
 * que emite el código. Nota B23.5a: el toggle activar/None usa `setAtPath(path, null)`
 * porque `model_dump` de Pydantic emite `null`, no omite la clave (ver FieldRenderer).
 */
export function removeAtPath<T>(obj: T, path: Path): T {
  if (path.length === 0) return obj
  const [head, ...rest] = path
  const base: unknown = obj

  if (typeof head === "number") {
    if (!Array.isArray(base) || head < 0 || head >= base.length) return obj
    const arr = [...base]
    if (rest.length === 0) arr.splice(head, 1)
    else arr[head] = removeAtPath(arr[head], rest)
    return arr as unknown as T
  }

  if (!isPlainObject(base) || !(head in base)) return obj
  const record = { ...base }
  if (rest.length === 0) delete record[head]
  else record[head] = removeAtPath(record[head], rest)
  return record as unknown as T
}

/** Resultado de parsear el texto del editor JSON fallback (§5/§8). */
export type JsonParseResult =
  | { ok: true; value: ConfigValue }
  | { ok: false; error: string }

/**
 * Parsea `text` como JSON para el editor fallback de tipos exóticos (SDD §5/§8). Solo
 * valida **sintaxis** local: si parsea, devuelve el valor; si no, el mensaje de error.
 * La validación **semántica** contra el schema es del backend (`POST /api/validate`,
 * B23.5b). Texto vacío ⇒ `null` (sección sin valor), no error.
 */
export function parseJsonInput(text: string): JsonParseResult {
  const trimmed = text.trim()
  if (trimmed === "") return { ok: true, value: null }
  try {
    return { ok: true, value: JSON.parse(trimmed) as ConfigValue }
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}
