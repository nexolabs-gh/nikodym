/**
 * Gate de CLASE: ningún `<Select>` puede pintar el valor crudo donde la lista muestra otra cosa.
 *
 * 🔴 Este repo ha pagado la misma trampa TRES veces, y las tres se vieron abriendo la pantalla, no
 * en un test:
 *   1. `__por_orden__` en el selector de llave de un artefacto externo (ExternalInputCard).
 *   2. `f3-provisiones-consumo` en el selector de ejemplos de Ejecutar (RunTab).
 *   3. `holdout` / `oot` en el selector de partición de Resultados (ResultsTab).
 *
 * La causa es siempre la misma: `Select.Value` resuelve la etiqueta con `items` del `<Select>`, y
 * si no se los pasas cae a serializar el valor — el texto del `<SelectItem>` **nunca se lee**.
 * Medido en el fuente del paquete (`@base-ui/react/select/value/SelectValue.js`): con `children`
 * función se usa la función y el `placeholder` se ignora; sin `children` y sin `items`, se pinta el
 * valor.
 *
 * Por qué es un guardrail sobre el FUENTE y no un test de render: vitest corre sin DOM en este
 * repo, así que montar el componente no es una opción. Mismo patrón que `public-copy.test.ts`.
 *
 * Un `<Select>` pasa si cumple UNA de tres:
 *   (a) su `<SelectValue>` trae `children` (función que resuelve la etiqueta), o
 *   (b) el `<Select>` declara `items` (Base UI resuelve la etiqueta solo), o
 *   (c) sus `<SelectItem>` muestran exactamente su propio `value` — no hay nada que perder.
 */

import { describe, expect, it } from "vitest"

/**
 * Barrido AUTOMÁTICO de todos los componentes, no una lista escrita a mano: un `<Select>` nuevo en
 * un componente nuevo tiene que entrar solo, o el gate protege sólo lo que ya estaba.
 */
const FUENTES = import.meta.glob("./*.tsx", { query: "?raw", import: "default", eager: true }) as Record<
  string,
  string
>

interface BloqueSelect {
  archivo: string
  fuente: string
  resuelvePor: "children" | "items" | "label-igual-a-value" | null
}

/** Trocea el fuente en bloques `<Select …>…</Select>`, anidados incluidos. */
function bloquesDeSelect(archivo: string, fuente: string): BloqueSelect[] {
  const bloques: BloqueSelect[] = []
  const apertura = /<Select(?![A-Za-z])/g
  let match: RegExpExecArray | null
  while ((match = apertura.exec(fuente)) !== null) {
    const cierre = fuente.indexOf("</Select>", match.index)
    if (cierre === -1) continue
    const cuerpo = fuente.slice(match.index, cierre)
    bloques.push({ archivo, fuente: cuerpo, resuelvePor: clasificar(cuerpo) })
  }
  return bloques
}

function clasificar(cuerpo: string): BloqueSelect["resuelvePor"] {
  // (a) `<SelectValue>` con children: la apertura NO se autocierra.
  const valor = cuerpo.match(/<SelectValue\b[^>]*?(\/?)>/)
  if (!valor) return "children" // sin `<SelectValue>` no hay nada que pintar mal
  if (valor[1] !== "/") return "children"

  // (b) `items` en la etiqueta de apertura del propio `<Select>`.
  const aperturaSelect = cuerpo.slice(0, cuerpo.indexOf(">") + 1)
  if (/\bitems=/.test(aperturaSelect)) return "items"

  // (c) todo `<SelectItem value={X}>` muestra `{X}` (con o sin un `<span>` de estilo en medio).
  const items = [...cuerpo.matchAll(/<SelectItem\b[^>]*?value=\{([^}]+)\}[^>]*>([\s\S]*?)<\/SelectItem>/g)]
  if (items.length === 0) return null
  const todosIguales = items.every(([, valorItem, contenido]) => {
    const pintado = contenido.match(/\{([^}]+)\}/)
    return pintado !== null && pintado[1].trim() === valorItem.trim()
  })
  return todosIguales ? "label-igual-a-value" : null
}

function todosLosBloques(): BloqueSelect[] {
  return Object.entries(FUENTES).flatMap(([ruta, fuente]) =>
    bloquesDeSelect(ruta.replace("./", ""), fuente),
  )
}

describe("Select.Value nunca pinta el valor crudo cuando la lista dice otra cosa", () => {
  it("el barrido no es vacuo", () => {
    const bloques = todosLosBloques()
    // Ancla: si el troceo se rompe, «0 ofensores» se lee igual que «todo limpio». Eran 7 al
    // escribir esto, repartidos en 5 archivos.
    expect(bloques.length).toBeGreaterThanOrEqual(7)
    expect(new Set(bloques.map((b) => b.archivo)).size).toBeGreaterThanOrEqual(4)
  })

  it("ningún selector pinta el valor crudo donde su lista muestra otra cosa", () => {
    const ofensores = todosLosBloques().filter((b) => b.resuelvePor === null)
    expect(
      ofensores.map((b) => `${b.archivo}: ${b.fuente.slice(0, 120).replace(/\s+/g, " ")}`),
    ).toEqual([])
  })

  it("los dos selectores que ya se equivocaron resuelven por children", () => {
    // Ancla nominal positiva: sin esto, un troceo que devolviera bloques vacíos daría verde en el
    // test de arriba y este gate no probaría nada sobre los casos que existe para cubrir.
    const porArchivo = (archivo: string) =>
      todosLosBloques().filter((b) => b.archivo === archivo && /<SelectValue\b/.test(b.fuente))
    expect(porArchivo("RunTab.tsx").some((b) => b.resuelvePor === "children")).toBe(true)
    expect(porArchivo("ResultsTab.tsx").some((b) => b.resuelvePor === "children")).toBe(true)
    expect(porArchivo("ExternalInputCard.tsx").some((b) => b.resuelvePor === "children")).toBe(true)
    // Y el que resuelve por la otra vía legítima sigue haciéndolo.
    expect(porArchivo("DatosTab.tsx").some((b) => b.resuelvePor === "items")).toBe(true)
  })
})
