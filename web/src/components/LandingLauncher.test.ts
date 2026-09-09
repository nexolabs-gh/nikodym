/**
 * Gate §6-8 de D-JUR-9: la landing pinta el bloque de referencia SÓLO con los trabajos ofrecidos.
 *
 * El runner corre en `node` —sin DOM, sin jsdom ni testing-library: el goal veta deps nuevas—, así
 * que el catálogo REAL se renderiza a HTML estático con `react-dom/server`, que ya es dependencia
 * del front. Es el mismo patrón que `ResultsTab.test.ts`, y por la misma razón: un guardrail sobre
 * el fuente prueba que la llamada está escrita, no que la pantalla salga como se dice.
 *
 * `JobCatalogo` recibe el catálogo por props; `JobSelector` es la cáscara que lo trae en un
 * `useEffect` —que en render estático no corre—. Lo que esto NO prueba —layout, foco, el hover de
 * las tarjetas— se verifica en la UI viva, como declara `jobs.test.ts`.
 */

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { JobCatalogo } from "@/components/LandingLauncher"
import { FIXTURE_JOBS, type Job } from "@/lib/jobs"

/** Rótulo del bloque de referencia: lo escribe la landing y nada más. */
const BLOQUE_DE_REFERENCIA = "Normativa local · casos de referencia"

const JOBS = FIXTURE_JOBS.jobs

function pintar(jobs: Job[]): string {
  return renderToStaticMarkup(createElement(JobCatalogo, { jobs, onPick: () => {} }))
}

describe("la landing ofrece lo que el catálogo marca como ofrecido (D-JUR-9.2)", () => {
  it("con el `jobs.json` empaquetado no pinta el bloque de referencia ni sus dos tarjetas", () => {
    const html = pintar(JOBS)

    expect(html).not.toContain(BLOQUE_DE_REFERENCIA)
    // Los rótulos de negocio de los dos trabajos de referencia, tal como los publica el catálogo.
    for (const job of JOBS.filter((j) => !j.offered)) {
      expect(html).not.toContain(job.label)
    }
    // Anti-vacuidad: si el render devolviera vacío, los tres asserts de arriba pasarían solos.
    expect(html).toContain("¿A qué viniste?")
    for (const job of JOBS.filter((j) => j.offered)) {
      expect(html).toContain(job.label)
    }
  })

  it("con el opt-in del lanzador vuelve el bloque, con sus dos tarjetas y su encuadre", () => {
    const html = pintar(JOBS.map((j) => ({ ...j, offered: true })))

    expect(html).toContain(BLOQUE_DE_REFERENCIA)
    // El encuadre de D-JUR-7: evidencia congelada, no promesa de mantenimiento.
    expect(html).toContain("Están congelados en la versión que se cotejó")
    for (const job of JOBS) expect(html).toContain(job.label)
  })

  it("🔴 CONTROL NEGATIVO: partir sobre el catálogo entero devolvería el bloque a la pantalla", () => {
    // Es la regresión exacta que `catalogoDeLanding` impide. Se demuestra pintando el mismo
    // componente con todo marcado como ofrecido: si el filtro desapareciera del código, el render
    // del fixture empaquetado sería IDÉNTICO a éste, y el primer test se pondría rojo.
    const comoSiNoFiltrara = pintar(JOBS.map((j) => ({ ...j, offered: true })))
    expect(comoSiNoFiltrara).toContain(BLOQUE_DE_REFERENCIA)
    expect(pintar(JOBS)).not.toBe(comoSiNoFiltrara)
  })

  it("sin catálogo no pinta nada (el fetch todavía no volvió)", () => {
    expect(pintar([])).toBe("")
  })
})
