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
