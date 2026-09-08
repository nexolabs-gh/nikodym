/**
 * Proyección de la ficha del modelo (`ModelCard`) a lo que la pestaña Resultados pinta (D-GOB-15).
 *
 * Vive en `lib/` y no dentro del componente por la misma razón que `lineageRows`: vitest corre sin
 * DOM, y una proyección escrita en el JSX sólo se podría vigilar con un guardrail sintáctico sobre
 * el fuente, que es más débil y más frágil. Aquí es lógica pura: agrupar, ordenar y formatear.
 *
 * CERO lógica de dominio: cada cifra viene de la ficha tal como el serializador la emitió. Nada se
 * recalcula, nada se interpreta, y lo que la ficha no trae no se fabrica.
 */

import { esAvisoDeclarado } from "@/lib/markers"
import { EMPTY, formatBool, formatCount, formatMetric } from "@/lib/results-format"
import type { ModelCard } from "@/lib/results-types"
import { CONFIG_SECTIONS } from "@/lib/schema"

/**
 * Claves de la ficha que el panel **no pinta**, cada una con su razón.
 *
 * Mismo contrato que `LINEAGE_NO_PINTADO`: el payload publica la ficha entera y la pantalla enseña
 * una proyección menor. Sin declarar la diferencia, «el panel pinta la ficha» sería una
 * sobrepromesa, y la sección podría encogerse campo a campo sin que nada lo notara. Un gate exige
 * que toda clave de la ficha esté **o pintada o listada aquí**.
 *
 * El criterio de fondo: la ficha va inmediatamente después de «Artefactos de la corrida», así que
 * lo que ya se lee ahí —la identidad reproducible de la corrida— no se repite dos tarjetas más
 * abajo con otro nombre.
 */
export const MODEL_CARD_NO_PINTADO: Record<string, string> = {
  run_id: "identifica la corrida y ya encabeza «Artefactos de la corrida», la tarjeta anterior",
  config_hash: "ya se lee en la procedencia de la corrida, la tarjeta anterior; no se repite",
  data_hash: "ya se lee en la procedencia de la corrida, la tarjeta anterior; no se repite",
  git_sha: "la procedencia lo pinta fundido con git_dirty en la fila «código»",
  git_dirty: "la procedencia lo pinta fundido con git_sha en la fila «código»",
  root_seed: "ya se lee como «semilla» en la procedencia de la corrida",
  schema_version: "describe el formato del registro, no el modelo ni la corrida",
  created_at:
    "es la marca de la corrida, que la procedencia ya muestra como «ejecutada»; la fecha propia " +
    "de la ficha es la de su emisión (review_date)",
  determinism_caveats:
    "la procedencia los pinta en prosa, y el motor ya los copia dentro de las limitaciones de la " +
    "ficha, que sí se pintan",
  environment:
    "el entorno completo son decenas de paquetes: evidencia de auditoría, no lectura de tarjeta; " +
    "su hash de lock ya se lee como «entorno» en la procedencia y el snapshot íntegro va al informe",
  data_description:
    "las cifras que importan a la lectura (filas, variables, tasa de malos) ya llegan como " +
    "métricas del dominio de datos, y el hash del dataset está en la procedencia",
}

/**
 * Fecha calendario (AAAA-MM-DD) de una marca ISO-8601 en UTC, tal como el serializador la emite.
 * Una marca que no tenga esa forma se deja tal cual: no se adivina, y el valor completo sigue
 * disponible en el `title` de la celda.
 */
export function isoDate(iso: string): string {
  return /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10) : iso
}

/** Una métrica plana de la ficha, ya sin el prefijo del dominio y formateada para leerse. */
export interface ModelCardMetricRow {
  /** Nombre de la métrica tal como el dominio la declara (sin el prefijo `<dominio>.`). */
  name: string
  value: string
}

/**
 * Un hecho del payload estructurado del dominio (CT-2), aplanado a una línea legible.
 *
 * `avisoDeclarado` marca la fila cuyo valor lleva un código de aviso declarado (`FALTA-DATO-*` o
 * `DATO-INSTITUCIONAL-*`, reconocidos por `esAvisoDeclarado`, nunca por el literal): el motor
 * interno de provisiones, por ejemplo, publica sus `warning_codes` en la sección CT-2. El código se
 * conserva tal cual —aquí es el dato, como en el volcado de auditoría del anexo del informe— y la
 * marca es lo que permite a la pantalla explicarlo en el idioma del lector en vez de publicarlo
 * mudo. Lo señaló la revisión adversarial de S4.
 */
export interface ModelCardEvidenceRow {
  label: string
  value: string
  avisoDeclarado: boolean
}

/** Resumen de un dominio en la ficha: sus métricas planas y su evidencia estructurada. */
export interface ModelCardDomainSummary {
  /** Clave del dominio (`performance`, `stability`, …): la misma que su sección del formulario. */
  domain: string
  /** Rótulo humano de la sección; cae a la clave si el dominio no tiene sección en el formulario. */
  label: string
  metrics: ModelCardMetricRow[]
  evidence: ModelCardEvidenceRow[]
}

/** Rótulo para las métricas que llegaran sin prefijo de dominio (D-GOB-2 lo impide; no se ocultan). */
const SIN_DOMINIO = "otras"

function domainLabel(domain: string): string {
  if (domain === "") return SIN_DOMINIO
  return CONFIG_SECTIONS.find((s) => s.key === domain)?.label ?? domain
}

/** Divide `<dominio>.<métrica>` en el primer punto; sin punto, la métrica entera queda sin dominio. */
function splitMetricKey(key: string): { domain: string; name: string } {
  const dot = key.indexOf(".")
  return dot === -1
    ? { domain: "", name: key }
    : { domain: key.slice(0, dot), name: key.slice(dot + 1) }
}

/**
 * Un número de la ficha: los enteros como conteo, el resto a 4 decimales (como AUC/Gini/KS). Un
 * valor diminuto —una tolerancia de `1e-8`— va en notación exponencial, con el mismo criterio que
 * `formatPValue`: a 4 decimales colapsaría a «0.0000» y se leería como cero.
 */
function formatNumber(value: number): string {
  if (Number.isInteger(value)) return formatCount(value)
  if (Number.isFinite(value) && value !== 0 && Math.abs(value) < 1e-4) {
    return value.toExponential(1)
  }
  return formatMetric(value, 4)
}

const esEscalar = (v: unknown): boolean =>
  v === null || ["string", "number", "boolean"].includes(typeof v)

/**
 * Describe un valor arbitrario del payload en una línea, sin interpretarlo: los escalares tal cual,
 * las listas de escalares separadas por coma (a cualquier profundidad: `falta_dato: A, B` se lee
 * mejor que su JSON), los objetos como `clave: valor` separados por «·», y lo anidado más hondo
 * —objetos dentro de objetos, listas de objetos dentro de objetos— en JSON. Lo vacío (`null`, `[]`,
 * `{}`) se marca ausente, no se omite: un mapa vacío de razones no evaluables es un hecho
 * («ninguna»), no ruido.
 */
export function describeValue(value: unknown, depth = 0): string {
  if (value === null || value === undefined) return EMPTY
  if (typeof value === "boolean") return formatBool(value)
  if (typeof value === "number") return formatNumber(value)
  if (typeof value === "string") return value === "" ? EMPTY : value
  if (Array.isArray(value)) {
    if (value.length === 0) return EMPTY
    return depth === 0 || value.every(esEscalar)
      ? value.map((item) => describeValue(item, depth + 1)).join(", ")
      : JSON.stringify(value)
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return EMPTY
    return depth === 0
      ? entries.map(([k, v]) => `${k}: ${describeValue(v, depth + 1)}`).join(" · ")
      : JSON.stringify(value)
  }
  return String(value)
}

/**
 * Aplana el payload CT-2 de un dominio a filas `etiqueta → valor`. El payload es un nivel por
 * dominio (`{ discrimination: {...} }`); cada subsección con entradas da una fila por entrada,
 * rotulada `subsección · clave`, y una subsección escalar o vacía da una sola fila.
 */
export function flattenEvidence(section: Record<string, unknown>): ModelCardEvidenceRow[] {
  const rows: ModelCardEvidenceRow[] = []
  for (const [subsection, payload] of Object.entries(section)) {
    if (payload !== null && typeof payload === "object" && !Array.isArray(payload)) {
      const entries = Object.entries(payload as Record<string, unknown>)
      if (entries.length > 0) {
        for (const [key, value] of entries) {
          rows.push(evidenceRow(`${subsection} · ${key}`, value))
        }
        continue
      }
    }
    rows.push(evidenceRow(subsection, payload))
  }
  return rows
}

function evidenceRow(label: string, value: unknown): ModelCardEvidenceRow {
  const descrito = describeValue(value)
  return { label, value: descrito, avisoDeclarado: esAvisoDeclarado(descrito) }
}

/**
 * Las métricas de la ficha agrupadas por dominio, con la evidencia estructurada (CT-2) de cada uno.
 *
 * El orden es el de la ficha —el del pipeline, porque `metrics` se publica paso a paso—, y los
 * dominios que sólo aportan evidencia estructurada van al final en su propio orden. No se inventa
 * un orden «lógico»: el lector ve los dominios en el orden en que corrieron.
 */
export function modelCardDomains(card: ModelCard): ModelCardDomainSummary[] {
  const byDomain = new Map<string, ModelCardDomainSummary>()
  const summaryOf = (domain: string): ModelCardDomainSummary => {
    let summary = byDomain.get(domain)
    if (!summary) {
      summary = { domain, label: domainLabel(domain), metrics: [], evidence: [] }
      byDomain.set(domain, summary)
    }
    return summary
  }
  for (const [key, value] of Object.entries(card.metrics)) {
    const { domain, name } = splitMetricKey(key)
    summaryOf(domain).metrics.push({ name, value: formatNumber(value) })
  }
  for (const [domain, section] of Object.entries(card.metric_sections)) {
    summaryOf(domain).evidence.push(...flattenEvidence(section))
  }
  return [...byDomain.values()]
}

/** Una decisión del registro de auditoría, lista para la tabla de detalle. */
export interface ModelCardDecisionRow {
  ts: string
  /** Paso que la registró; ausente (`null`) cuando el evento no lo trae. */
  step: string | null
  regla: string
  accion: string
  umbral: string
  valor: string
  /**
   * El umbral o el valor llevan un código de aviso declarado: p. ej. `internal_falta_dato` con
   * `fail_on_falta_dato=false` registra que un dato ausente se imputó a cero y deja el código de
   * la institución en `valor`. La fila se marca para que la sección lo explique; el código no se
   * recorta (es la evidencia).
   */
  avisoDeclarado: boolean
}

/**
 * Las decisiones registradas, en el orden del trail y sin agrupar: el conteo que la ficha titula
 * es `card.decisions.length`, y el detalle es esta lista, una por evento. `umbral` y `valor` son
 * lo que el paso escribió —número, texto, lista u objeto—; se describen, no se interpretan.
 */
export function modelCardDecisionRows(card: ModelCard): ModelCardDecisionRow[] {
  return card.decisions.map((d) => {
    const umbral = describeValue(d.umbral)
    const valor = describeValue(d.valor)
    return {
      ts: d.ts,
      step: d.step,
      regla: d.regla,
      accion: d.accion,
      umbral,
      valor,
      avisoDeclarado: esAvisoDeclarado(umbral) || esAvisoDeclarado(valor),
    }
  })
}

/**
 * Si algo de lo que la ficha pinta —evidencia CT-2 o decisiones— lleva un aviso declarado. Es lo
 * que decide si la sección escribe la explicación: sin avisos no hay nota, para no explicar una
 * salvedad que no ocurrió.
 */
export function modelCardTieneAvisosDeclarados(
  domains: ModelCardDomainSummary[],
  decisions: ModelCardDecisionRow[],
): boolean {
  return (
    domains.some((d) => d.evidence.some((e) => e.avisoDeclarado)) ||
    decisions.some((d) => d.avisoDeclarado)
  )
}
