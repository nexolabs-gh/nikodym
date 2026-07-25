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
 * Este gate existe porque ningún otro mira la presentación: los defectos que lo motivaron
 * (`landing-evidence.ts` y la nota de runoff de `ResultsTab`) sobrevivieron a un CI 16/16 verde.
 * Por eso barre la CLASE y no las dos instancias conocidas:
 *
 *  1. **Datos de copy** — recorre `import * as` de los módulos de presentación, así que un export
 *     nuevo queda cubierto el día que se escribe, sin tocar este archivo.
 *  2. **Fuentes `.tsx`** — red de seguridad sobre el copy escrito inline en JSX, vía `?raw`.
 *
 * La regla que separa copy de identificador legítimo no es una allowlist por línea (se rompe al
 * mover código) sino la forma del literal: `"FALTA-DATO-IFRS-4"` a secas es un identificador —el
 * flag con el que `ResultsTab` decide si mostrar la nota—, mientras que un código EMBEBIDO en una
 * frase con espacios es, por definición, prosa dirigida a alguien.
 */

import { describe, expect, it } from "vitest"

import landingLauncherSource from "@/components/LandingLauncher.tsx?raw"
import * as landingEvidence from "@/components/landing-evidence"
import resultsTabSource from "@/components/ResultsTab.tsx?raw"
import { presetDisplay } from "@/lib/presentation"

/**
 * Los códigos internos, con o sin sufijo de familia. El token pelado cuenta: la salvedad de los
 * parámetros CMF decía «declaradas como FALTA-DATO» sin sufijo y era igual de opaca.
 */
const CODIGO_INTERNO = /FALTA-DATO|DATO-INSTITUCIONAL/

/** Los presets empaquetados en la demo, cuyo copy curado ve el usuario en la landing y en Ejecutar. */
const PRESETS_DEMO = [
  { id: "f1-estandar-consumo", name: "Preset estándar F1 — consumo", description: "" },
  { id: "f3-provisiones-consumo", name: "Preset F3 — provisiones", description: "" },
  { id: "f4-ifrs9-retail", name: "Preset F4 — IFRS 9 retail", description: "" },
]

/** Aplana a `[ruta, texto]` todos los strings de un valor exportado, por hondo que esté anidado. */
function textos(valor: unknown, ruta: string): Array<[string, string]> {
  if (typeof valor === "string") return [[ruta, valor]]
  if (Array.isArray(valor)) return valor.flatMap((v, i) => textos(v, `${ruta}[${i}]`))
  if (valor && typeof valor === "object") {
    return Object.entries(valor).flatMap(([k, v]) => textos(v, `${ruta}.${k}`))
  }
  return []
}

/**
 * Los literales de texto de un fuente, sin comentarios. Los comentarios SÍ pueden nombrar el
 * código —son para quien mantiene, no para quien lee la página— y de hecho lo hacen: el JSDoc de
 * `Ifrs9RunoffNote` explica cuál es el disparador de la nota.
 */
function literales(fuente: string): string[] {
  const sinComentarios = fuente.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "")
  return sinComentarios.match(/"[^"\n]*"|'[^'\n]*'/g) ?? []
}

describe("gate de copy público: ningún código interno llega al lector", () => {
  it("los datos de la landing explican la limitación sin nombrar el código", () => {
    const ofensores = textos(landingEvidence, "landing-evidence")
      .filter(([, texto]) => CODIGO_INTERNO.test(texto))
      .map(([ruta, texto]) => `${ruta}: ${texto}`)

    expect(ofensores).toEqual([])
  })

  it("el copy curado de los presets tampoco lo nombra", () => {
    const ofensores = PRESETS_DEMO.flatMap((p) =>
      textos(presetDisplay(p), `presetDisplay(${p.id})`),
    )
      .filter(([, texto]) => CODIGO_INTERNO.test(texto))
      .map(([ruta, texto]) => `${ruta}: ${texto}`)

    expect(ofensores).toEqual([])
  })

  it.each([
    ["LandingLauncher.tsx", landingLauncherSource],
    ["ResultsTab.tsx", resultsTabSource],
  ])("%s no escribe el código dentro de una frase", (_archivo, fuente) => {
    // Un literal que ES el código (sin espacios) es el identificador con el que el componente
    // decide qué mostrar, y es legítimo. Uno que lo lleva DENTRO de una frase es copy.
    const ofensores = literales(fuente).filter(
      (lit) => CODIGO_INTERNO.test(lit) && /\s/.test(lit.slice(1, -1).trim()),
    )

    expect(ofensores).toEqual([])
  })
})
