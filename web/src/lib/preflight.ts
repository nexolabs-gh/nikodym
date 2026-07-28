/**
 * Helpers PUROS del preflight config↔dataset (enmienda PREFLIGHT-DATASET, D-PRE-1…D-PRE-9).
 *
 * El backend PRODUCE el veredicto (`POST /api/preflight`); el front sólo lo transporta, lo indexa
 * por sección y lo pinta. CERO lógica de dominio aquí (SDD-23 §3.3): no se decide qué columna hace
 * falta ni se reinterpreta el mensaje del motor, que ya viene en español y sin códigos internos.
 * Lógica pura, testeable con vitest sin React ni DOM.
 */

import type { PreflightMismatch } from "@/lib/api"
import { CONFIG_SECTIONS } from "@/lib/schema"

/**
 * Estado del preflight en vivo. `idle` cubre los tres casos en que la pregunta **no aplica**
 * todavía —sin dataset elegido, config aún inválido, o build de demo— y por eso no se pinta nada:
 * un aviso sobre una comparación que no se hizo sería una afirmación inventada.
 */
export type PreflightState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "ok" }
  | {
      kind: "issues"
      mismatches: readonly PreflightMismatch[]
      uninspected: readonly string[]
    }
  | { kind: "unreachable" }

/**
 * `id` del control del formulario que corresponde a `path`, traduciendo la convención del motor.
 *
 * ⚠️ Las dos convenciones NO coinciden: el motor emite los elementos de lista con corchetes
 * (`data.schema.columns[3].name`, `dataset_check.py::_declaraciones`) y `FieldRenderer` usa
 * `path.join(".")` como `id`. Sin esta traducción el salto funciona en los campos planos y falla
 * justo en los de lista.
 */
export function fieldIdForPath(path: string): string {
  return path.replace(/\[(\d+)\]/g, ".$1")
}

/**
 * `id`s candidatos para enfocar `path`, del más específico al más general.
 *
 * ⚠️ **Medido en vivo, y por eso existe:** traducir los corchetes no alcanzaba. El formulario
 * **no expande las listas de objetos**: de `data.schema.columns[0].name` no hay ningún control en
 * el DOM, sino UNO solo para la lista entera, con `id="data.schema.columns"` (ídem
 * `data.target.bad_rule.all_of`). Un test que sólo comparase strings habría quedado verde y el
 * salto habría caído al `body` en 8 de los 15 desajustes del caso real.
 *
 * El llamador prueba los candidatos en orden y usa el primero que exista, así que el salto
 * degrada solo: al campo exacto si algún día las listas se expanden, y hoy al control que edita
 * la lista — que es donde el usuario corrige el nombre de todos modos.
 */
export function candidateFieldIds(path: string): string[] {
  const candidatos = [fieldIdForPath(path)]
  // Recorta por cada nivel de lista, del más profundo al más superficial: `a.b[1].c[2].d` deja
  // `a.b[1].c` y luego `a.b`, siempre normalizados a la convención del formulario.
  let resto = path
  let corte = resto.lastIndexOf("[")
  while (corte !== -1) {
    resto = resto.slice(0, corte)
    candidatos.push(fieldIdForPath(resto))
    corte = resto.lastIndexOf("[")
  }
  return candidatos
}

/**
 * Sección de config a la que pertenece `path` (su primer segmento): `data`, `binning`, `stability`…
 * Es la clave que el sidebar usa para navegar, así que un desajuste sabe a qué pestaña saltar.
 */
export function sectionOfPath(path: string): string {
  const corte = path.search(/[.[]/)
  return corte === -1 ? path : path.slice(0, corte)
}

/**
 * ¿El formulario ofrece esta sección? Decide si un desajuste puede ofrecer «ir al campo».
 *
 * ⚠️ No todas las secciones del config están en el formulario, y el preflight lo destapa: uno de
 * los seis desajustes del caso medido cae en `stability.temporal_column`, y `stability` **no**
 * está en `CONFIG_SECTIONS` —es sección del config, pero hoy sólo se edita por YAML o por
 * código—. Ofrecer un salto a una pestaña que no existe sería peor que no ofrecerlo: el aviso lo
 * dice en vez de fingir.
 */
export function sectionIsEditable(section: string): boolean {
  return CONFIG_SECTIONS.some((s) => s.key === section)
}

/** ¿Este desajuste tiene un campo del formulario al que saltar? */
export function canJumpTo(mismatch: PreflightMismatch): boolean {
  return sectionIsEditable(sectionOfPath(mismatch.path))
}

/** Desajustes que caen dentro de `section`, para pintarlos junto al formulario que los arregla. */
export function mismatchesForSection(
  state: PreflightState,
  section: string,
): readonly PreflightMismatch[] {
  if (state.kind !== "issues") return []
  return state.mismatches.filter((m) => sectionOfPath(m.path) === section)
}

/** Cuántos desajustes hay en total (0 si el estado no es `issues`). */
export function mismatchCount(state: PreflightState): number {
  return state.kind === "issues" ? state.mismatches.length : 0
}

/**
 * Aviso de una línea para el botón Ejecutar, o `null` si no hay nada que advertir.
 *
 * D-PRE-5 manda informar sin bloquear, y aquí eso es literal: este texto acompaña al botón, que
 * sigue habilitado. La corrida es la autoridad sobre sí misma; el preflight sólo adelanta lo que
 * ya se sabe antes de pagar el intento.
 */
export function runHint(state: PreflightState): string | null {
  if (state.kind !== "issues") return null
  const n = state.mismatches.length
  if (n === 0) {
    return (
      "No se pudo comparar todo el config con el dataset: hay secciones que esta instalación " +
      "no sabe leer. Puedes ejecutar igual."
    )
  }
  return n === 1
    ? "El dataset no calza con 1 campo del config. Puedes ejecutar igual, pero es probable que la corrida falle."
    : `El dataset no calza con ${n} campos del config. Puedes ejecutar igual, pero es probable que la corrida falle.`
}

/**
 * Encabezado del panel de avisos, o `null` si no hay panel que mostrar.
 *
 * El estado `ok` SÍ dice algo —«el dataset calza»— porque es información que el usuario no tiene
 * de otro modo y que evita la duda de si la comprobación llegó a correr.
 */
export function preflightHeadline(state: PreflightState): string | null {
  switch (state.kind) {
    case "ok":
      return "El dataset trae todas las columnas que el config declara."
    case "issues": {
      const n = state.mismatches.length
      if (n === 0) return "Hay partes del config que no se pudieron comparar con el dataset."
      return n === 1
        ? "El config declara 1 columna que el dataset no tiene."
        : `El config declara ${n} columnas que el dataset no tiene.`
    }
    default:
      return null
  }
}
