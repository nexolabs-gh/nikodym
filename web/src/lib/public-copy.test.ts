/**
 * Gate de copy público: un código interno no se le muestra nunca al lector.
 *
 * El proyecto marca sus avisos declarados con dos códigos —`FALTA-DATO-*` (la carencia es del
 * motor) y `DATO-INSTITUCIONAL-*` (el dato lo aporta la institución)—. Son un CONTRATO INTERNO:
 * viven en `src/nikodym/core/markers.py`, viajan en `warning_codes` y sirven para que el motor y la
 * UI se entiendan. Al lector de la landing o del panel de resultados no le dicen nada: le dicen que
 * está leyendo el roadmap de otra persona.
 *
 * La regla NO es callar la limitación —el motor la publica en cada fila, así que esconderla sería
 * mentir por omisión sobre un producto regulatorio—. La regla es explicarla en el idioma del
 * lector: se queda la salvedad, se va el código.
 *
 * ## Cómo distingue copy de identificador
 *
 * `"FALTA-DATO-IFRS-4"` a secas es el flag con el que `ResultsTab` decide si mostrar una nota, y es
 * legítimo. El mismo código dentro de una frase es prosa dirigida a alguien. En vez de una
 * allowlist por línea —que se rompe al mover código— el gate **borra del fuente lo que es
 * inequívocamente identificador** (comentarios y literales cuyo contenido es exactamente el
 * código) y falla si el código sobrevive a esa poda. Eso cubre de una vez la prosa JSX plana (sin
 * comillas), los template literals, la concatenación partida entre líneas y el código armado por
 * interpolación — cuatro formas que una versión anterior de este gate, que sólo miraba literales
 * entre comillas, dejaba pasar en verde.
 *
 * ## Alcance
 *
 * Barre **todo** `web/src`, no una lista de archivos: un módulo de copy nuevo queda cubierto el día
 * que se escribe. Y las marcas se leen de `core/markers.py`, no se escriben a mano — el contrato
 * dice que ningún filtro compare el literal, y un gate que se exime de su propia regla no protege
 * de una tercera marca.
 */

import { describe, expect, it } from "vitest"

import { MARCAS_DECLARADAS } from "@/lib/markers"
import { presetDisplay } from "@/lib/presentation"

const MARCAS: readonly string[] = MARCAS_DECLARADAS

/** El código completo: la marca más su sufijo de familia, si lo trae. */
const CODIGO = new RegExp(`(${MARCAS.join("|")})(-[A-Z0-9]+)*`, "g")

/**
 * Todo el fuente del front, como texto. `import.meta.glob` con `eager` lo resuelve en build, así
 * que un módulo nuevo entra solo — no hay lista de archivos que actualizar ni que recordar.
 * Fuera: los tests (hablan de los códigos por oficio) y los fixtures, que son salida del motor.
 *
 * El barrido usa el pipeline de Vite y no `node:fs` a propósito: el `tsconfig` de la app expone
 * sólo `vite/client`, y meterle los tipos de Node para un test dejaría que cualquier componente de
 * UI importara APIs de servidor sin que el typecheck chistara.
 */
const FUENTES = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>

function fuentes(): [string, string][] {
  return Object.entries(FUENTES).filter(
    ([ruta]) => !/\.test\.tsx?$/.test(ruta) && !ruta.includes("fixtures"),
  )
}

/**
 * Poda del fuente todo lo que es inequívocamente identificador y no prosa:
 *
 *  1. comentarios de bloque y de línea — documentan para quien mantiene, no para quien lee la
 *     página, y ahí nombrar el código es correcto (el JSDoc de `Ifrs9RunoffNote` explica cuál es el
 *     disparador de la nota). El `//` sólo cuenta si no viene tras `:`, o partiría toda URL;
 *  2. literales cuyo contenido es EXACTAMENTE un código, que es la forma del flag — **salvo que
 *     estén pegados a un `+`**: `"…declara " + "FALTA-DATO" + " en cada fila"` es una frase partida,
 *     y sin esa salvedad bastaba con trocear el string para colar el código en verde.
 *
 * Lo que sobreviva y siga conteniendo un código es prosa.
 */
function podarIdentificadores(fuente: string): string {
  const codigo = `(${MARCAS.join("|")})(-[A-Z0-9]+)*`
  return fuente
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ")
    .replace(new RegExp(`(?<!\\+\\s*)(["'\`])${codigo}\\1(?!\\s*\\+)`, "g"), " ")
}

describe("gate de copy público: ningún código interno llega al lector", () => {
  it("hay fuentes que revisar", () => {
    // Un `src/` renombrado, o un filtro demasiado goloso, dejarían cero archivos y verde perpetuo.
    // La correspondencia de `MARCAS_DECLARADAS` con el contrato Python la verifica el gemelo
    // Python (`tests/unit/test_public_copy.py`), que sí alcanza los dos lados del repo.
    expect(MARCAS).toContain("FALTA-DATO")
    expect(fuentes().length).toBeGreaterThan(30)
  })

  it("ningún fuente del front escribe el código dentro de una frase", () => {
    const ofensores = fuentes().flatMap(([ruta, fuente]) => {
      const podado = podarIdentificadores(fuente)
      return [...podado.matchAll(CODIGO)].map((m) => {
        const linea = podado.slice(0, m.index).split("\n").length
        return `${ruta}:${linea}: ${podado.slice(m.index, m.index + 90).trim()}`
      })
    })

    expect(ofensores).toEqual([])
  })

  it("el copy curado de los presets tampoco lo nombra, ni siquiera por el fallback", () => {
    // Los tres ids curados y, sobre todo, uno desconocido: ahí `presetDisplay` degrada copiando la
    // `description` del backend a `blurb`, y el backend SÍ escribe estos códigos en campos
    // `description` (el catálogo de datasets lo hace). Es la rama por la que el copy ajeno entra.
    const presets = [
      { id: "f1-estandar-consumo", name: "Preset estándar F1 — consumo", description: "" },
      { id: "f3-provisiones-consumo", name: "Preset F3 — provisiones", description: "" },
      { id: "f4-ifrs9-retail", name: "Preset F4 — IFRS 9 retail", description: "" },
      {
        id: "preset-desconocido",
        name: "Preset F5 — stress",
        description: "Escenarios con FALTA-DATO-STR-1 declarado en cada corrida.",
      },
    ]

    const ofensores = presets
      .flatMap((p) => {
        const d = presetDisplay(p)
        return [
          [`${p.id}.title`, d.title],
          [`${p.id}.blurb`, d.blurb],
        ]
      })
      .filter(([, texto]) => new RegExp(MARCAS.join("|")).test(texto))
      .map(([ruta, texto]) => `${ruta}: ${texto}`)

    expect(ofensores).toEqual([])
  })
})
