/**
 * Helpers PUROS de validación en vivo (SDD-23 §3.3 / §7): el backend PRODUCE el
 * `config_hash` y los errores (`POST /api/validate`); el front SOLO los indexa por
 * campo y los pinta. CERO lógica de dominio aquí: no se reimplementan rangos, enums
 * ni finitud (§3.3). Lógica pura, testeable con vitest sin React ni DOM (entorno node).
 */

import type { PipelineInfo, ValidationErrorItem } from "@/lib/api"
import type { Path } from "@/lib/config-store"
import {
  type Defs,
  type JsonSchema,
  discriminatedBranches,
  resolveRef,
  unwrapNullable,
} from "@/lib/form-engine"
import { CONFIG_SECTIONS } from "@/lib/schema"

/**
 * Clave estable de un `loc`/`path` para el lookup de errores: los segmentos unidos por
 * `"."`. `loc` (Pydantic `ValidationError.errors()`) y `path` (árbol del form) comparten
 * convención —nombres de campo en orden, índices numéricos de listas—, así que ambos
 * producen la misma clave y el matcheo loc↔path es una igualdad de strings.
 */
export function pathKey(segments: readonly (string | number)[]): string {
  return segments.join(".")
}

/**
 * Normaliza un `loc` del backend a la convención de `path` del formulario (D-VIS-7).
 *
 * 🔴 Pydantic inserta el **tag** de la variante en el `loc` de una unión discriminada
 * —`data.partition.strategy.cohort.holdout_fraction`—, mientras `DiscriminatedField`
 * (`FieldRenderer.tsx:709`) pasa `path={path}` a sus hijos **sin** el tag, así que el control se
 * monta como `data.partition.strategy.holdout_fraction`. Como `errorAtPath` casa por igualdad
 * exacta, esas hojas no encontraban su campo **nunca**: medido, **58 hojas** bajo las 3 uniones del
 * config (`data.partition.strategy` 18, `provisioning_internal.lgd` 29,
 * `tuning.search_space.params.*` 11), o sea el 8,3 % de las 700 hojas.
 *
 * Se normaliza el `loc`, **nunca** el `path` del render: insertar el tag en los `id` sería el
 * arreglo simétrico y movería 58 controles, rompiendo el salto del preflight, `candidateFieldIds` y
 * los guardrails estáticos de `form-engine.test.ts`. Traducir convenciones es lo que el preflight ya
 * hace en `fieldIdForPath` (corchetes → puntos).
 *
 * ⚠️ **El tag se elide por POSICIÓN en el schema, no por nombre.** Sólo se quita el segmento que es
 * tag declarado de la unión que hay justo en ese punto del árbol; un campo que se llamara como un
 * tag en otro sitio no se toca. Y se recorren **todas** las ramas, no la primera: quedarse con la
 * primera es el patrón que este repo pagó tres veces en una sola sesión.
 *
 * Sin schema (`undefined`) devuelve el `loc` tal cual: no se adivina.
 */
export function normalizarLoc(
  loc: readonly (string | number)[],
  raiz: JsonSchema | undefined,
  defs: Defs = {},
): (string | number)[] {
  if (raiz === undefined) return [...loc]
  const salida: (string | number)[] = []
  let nodo: JsonSchema | undefined = raiz
  for (const segmento of loc) {
    if (nodo === undefined) {
      // Perdimos el hilo del schema (nodo opaco, `additionalProperties: true`…): se transporta el
      // resto tal cual. Un `loc` sin normalizar es el comportamiento de siempre, nunca peor.
      salida.push(segmento)
      continue
    }
    const rama = ramaPorTag(nodo, segmento, defs)
    if (rama !== undefined) {
      nodo = rama // el tag NO viaja al `path`: se elide
      continue
    }
    nodo = bajarUnNivel(nodo, segmento, defs)
    salida.push(segmento)
  }
  return salida
}

/** La rama de `nodo` cuyo tag es `segmento`, o `undefined` si `nodo` no es unión discriminada. */
function ramaPorTag(
  nodo: JsonSchema,
  segmento: string | number,
  defs: Defs,
): JsonSchema | undefined {
  if (typeof segmento !== "string") return undefined
  const ramas = discriminatedBranches(nodo, defs)
  if (ramas.length === 0) return undefined
  return ramas.find((r) => r.tag === segmento)?.schema
}

/** El sub-schema en `segmento`: propiedad, item de lista o valor de mapping. `undefined` si no baja. */
function bajarUnNivel(
  nodo: JsonSchema,
  segmento: string | number,
  defs: Defs,
): JsonSchema | undefined {
  // Una sección de dominio y todo campo opcional viajan como `anyOf: [<objeto>, {"type":"null"}]`;
  // sin desenvolverlo no hay `properties` por donde bajar (mismo motivo que `rama_objeto()`).
  const base = unwrapNullable(resolveRef(nodo, defs)).schema
  if (typeof segmento === "number") {
    return base.items ? resolveRef(base.items, defs) : undefined
  }
  const propiedad = base.properties?.[segmento]
  if (propiedad !== undefined) return resolveRef(propiedad, defs)
  // Mapping (`dict[str, X]`): la clave la pone el usuario y el valor lo describe
  // `additionalProperties`. Es por donde vive `tuning.search_space.params.<clave>`.
  const extra = base.additionalProperties
  return typeof extra === "object" ? resolveRef(extra, defs) : undefined
}

/**
 * Arma el lookup `loc→msg` desde los `errors` de `/api/validate`. Indexa por
 * `pathKey(normalizarLoc(loc))` para que cada `FieldRenderer` recupere su mensaje por `path`. Si
 * varios errores caen en el mismo `loc`, se concatenan en el orden que los emite el backend (un
 * campo puede violar más de una restricción). No interpreta el mensaje: lo transporta.
 *
 * `raiz` es el JSON Schema del config, y sirve **sólo** para elidir el tag de las uniones
 * discriminadas (D-VIS-7). Omitirlo conserva el comportamiento anterior.
 */
export function buildErrorLookup(
  errors: readonly ValidationErrorItem[],
  raiz?: JsonSchema,
  defs: Defs = {},
): Map<string, string> {
  const lookup = new Map<string, string>()
  for (const error of errors) {
    const key = pathKey(normalizarLoc(error.loc, raiz, defs))
    const previous = lookup.get(key)
    lookup.set(key, previous ? `${previous} · ${error.msg}` : error.msg)
  }
  return lookup
}

/** Mensaje de error del campo en `path`, o `undefined` si no hay (lookup ausente incluido). */
export function errorAtPath(
  lookup: Map<string, string> | undefined,
  path: Path,
): string | undefined {
  return lookup?.get(pathKey(path))
}

/** Un error que la vista actual no ancla a ningún campo, con dónde vive y si se puede saltar. */
export interface ErrorSinSuperficie {
  /** Clave del lookup: los segmentos del `loc` ya normalizado, unidos por `.` (vacía si `loc: []`). */
  path: string
  /** El mensaje del motor, tal cual. El front no lo reescribe (SDD-23 §3.3). */
  msg: string
  /** Sección de config a la que pertenece, o `null` si el error no es de ninguna (`loc: []`). */
  seccion: string | null
  /** Rótulo de la sección tal como lo lee el usuario en el sidebar, o `null`. */
  seccionLabel: string | null
  /** ¿Hay pestaña a la que llevarlo? `false` ⇒ se dice dónde vive, no se ofrece salto. */
  alcanzable: boolean
}

/**
 * Errores que la vista actual **no pinta en ningún campo**, para que el contador nunca se quede solo
 * (D-VIS-1/2). Generaliza `unanchoredError`, que sólo veía `loc: []`.
 *
 * 🔴 **La razón, medida en pantalla el 2026-08-08.** D-ANC-12 cerró el caso del error de sección
 * (`loc: []`, clave `""`, que ningún `FieldRenderer` reclama). Pero el flanco simétrico seguía
 * abierto y D-EXI-5 lo volvió alcanzable: un error **con** `loc` sólo se pinta si su campo está
 * montado, así que basta cambiar de sección para que el mensaje desaparezca de la pantalla entera —
 * verificado: estando en «Esquema y target» con `provisioning_internal.lgd.covariate_cols` roto, el
 * único texto en rojo era «Config inválido · 1 error», y el sidebar no marcaba nada—. Con el `loc`
 * vacío de antes, el mismo error **sí** se leía. Anclar no puede costar la visibilidad.
 *
 * No es de los errores de dominio: los de Pydantic **siempre** trajeron `loc`, así que con tres
 * secciones rotas a la vez dos de los tres mensajes eran invisibles desde siempre.
 *
 * ⚠️ **El criterio es POR SECCIÓN y es puro a propósito.** Preguntarle al DOM qué claves reclamó
 * algún control cubriría también el caso del tag del discriminador, pero exige un efecto post-render
 * y deja el resultado dependiendo del orden de montaje; esto se testea con vitest, que corre sin DOM.
 * El caso del tag lo cierra D-VIS-7 **anclándolo de verdad**, que es mejor que publicarlo suelto.
 */
export function erroresSinSuperficie(
  state: ValidationState,
  seccionActiva: string | null,
): ErrorSinSuperficie[] {
  if (state.kind !== "invalid") return []
  const fuera: ErrorSinSuperficie[] = []
  for (const [path, msg] of state.lookup) {
    const seccion = path === "" ? null : seccionDe(path)
    if (seccion !== null && seccion === seccionActiva) continue // lo pinta su propio campo
    const definicion = CONFIG_SECTIONS.find((s) => s.key === seccion)
    fuera.push({
      path,
      msg,
      seccion,
      seccionLabel: definicion?.label ?? null,
      alcanzable: definicion !== undefined,
    })
  }
  return fuera
}

/**
 * Secciones de config que tienen al menos un error, para que el sidebar las marque (D-VIS-4).
 *
 * Orienta en el caso que `erroresSinSuperficie` no puede ver —un `loc` de la sección **activa** que
 * aun así no case con ningún control—: el usuario sabe dónde mirar aunque el mensaje no encuentre su
 * campo. Coste de ruido cero: es información que el contador ya tenía y no publicaba.
 */
export function seccionesConError(state: ValidationState): Set<string> {
  if (state.kind !== "invalid") return new Set()
  const secciones = new Set<string>()
  for (const path of state.lookup.keys()) {
    if (path !== "") secciones.add(seccionDe(path))
  }
  return secciones
}

/** Primer segmento de una clave de lookup: la sección de config a la que pertenece. */
function seccionDe(path: string): string {
  const corte = path.indexOf(".")
  return corte === -1 ? path : path.slice(0, corte)
}

/**
 * Extrae un mensaje legible del cuerpo de un `ApiError` (422 de los endpoints YAML): FastAPI
 * envuelve el detalle en `{detail}`, que puede ser un string (mensaje del motor, p.ej. en
 * `config/from-yaml`) o la lista `[{loc,msg,type}]` de validación (p.ej. `config/to-yaml`). El
 * front SOLO lo pinta (§3.3). PURO: no toca red ni DOM; cae a `fallback` si no reconoce la forma.
 */
export function describeApiError(body: unknown, fallback: string): string {
  const detail = isRecord(body) ? body.detail : undefined
  if (typeof detail === "string" && detail.trim() !== "") return detail
  if (Array.isArray(detail)) {
    const lines = detail
      .filter(isRecord)
      .map((item) => {
        const loc = Array.isArray(item.loc)
          ? pathKey(item.loc as (string | number)[])
          : ""
        const msg = typeof item.msg === "string" ? item.msg : ""
        return loc ? `${loc}: ${msg}` : msg
      })
      .filter((line) => line !== "")
    if (lines.length > 0) return lines.join("; ")
  }
  return fallback
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

/**
 * Estado de la validación en vivo (SDD-23 §3.3/§7): la verdad la produce el backend
 * (`POST /api/validate`); el front solo transporta el `config_hash` o los errores. Vive
 * aquí (módulo compartido) para que Config, Ejecutar y el sidebar lean el mismo tipo.
 */
export type ValidationState =
  | { kind: "idle" }
  | { kind: "checking" }
  | {
      kind: "valid"
      hash: string
      pipeline: PipelineInfo | null
      /**
       * D-PRO-2, ya resuelto por sección. Opcional a propósito: un backend anterior a la enmienda
       * no lo manda, y `undefined` significa «no se sabe» —el consumidor cae a las columnas del
       * archivo, que es lo que hacía antes—, nunca «ninguna sección produce nada».
       */
      producedColumns?: Record<string, string[]>
    }
  | { kind: "invalid"; count: number; lookup: Map<string, string> }
  | { kind: "unreachable" }

/**
 * Aviso de config inejecutable, o `null` si no hay nada que advertir (enmienda
 * VALIDACION-PIPELINE, D-PIPE-5). PURO: sin React ni DOM.
 *
 * El **encabezado** es copy del front —el idioma del lector— y el **cuerpo** es el mensaje del
 * motor tal cual lo entregó el backend, ya saneado de códigos de marca. El front no traduce ese
 * mensaje ni deduce qué sección hay que encender: el motor es el que sabe (SDD-23 §3.3).
 *
 * Sólo aplica sobre un config VÁLIDO: mientras el config no reconstruye no hay pipeline que
 * resolver, y encimar dos avisos sobre el mismo campo roto sería ruido.
 */
export function pipelineWarning(state: ValidationState): string | null {
  if (state.kind !== "valid") return null
  if (state.pipeline === null || state.pipeline.executable) return null
  return state.pipeline.message
}

/**
 * Gate PURO de la corrida (SDD-23 §8): solo se puede ejecutar con un config **válido**
 * (hay `config_hash`) y un `datasetId` elegido. Devuelve el motivo del bloqueo para
 * pintarlo en texto sobrio. NO valida dominio: la validez ya la produjo el backend en
 * `validation`; aquí solo se combinan los dos prerequisitos. Testeable sin React ni DOM.
 *
 * El motivo distingue el bloqueo TRANSITORIO (el arranque de la sesión aún siembra y valida el
 * preset: `idle`/`checking`) del bloqueo REAL (config inválido / sin backend): desde UX1 el
 * config se siembra solo, así que `idle` ya no es "no configuraste", es "todavía no termina".
 */
export function canRun(
  validation: ValidationState,
  datasetId: string | null,
): { ok: boolean; reason?: string } {
  switch (validation.kind) {
    case "idle":
      return { ok: false, reason: "Preparando la configuración…" }
    case "checking":
      return { ok: false, reason: "Validando la configuración…" }
    case "invalid":
      return { ok: false, reason: "El config tiene errores: revísalo en Configuración" }
    case "unreachable":
      return { ok: false, reason: "Sin backend: no se pudo validar el config" }
  }
  if (datasetId === null || datasetId === "") {
    return { ok: false, reason: "Falta elegir dataset" }
  }
  return { ok: true }
}
