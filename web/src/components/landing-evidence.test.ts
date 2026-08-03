import { describe, expect, it } from "vitest"

import reportF1Html from "@/fixtures/demo/report-f1.html?raw"
import resultsF1 from "@/fixtures/demo/results-f1.json"
import { CAPITULOS, GAINS_HOLDOUT, METRICAS, PIPELINE } from "@/components/landing-evidence"

/**
 * Gate de la evidencia de la landing: **cada cifra publicada se re-deriva del fixture**, no se
 * compara contra sí misma.
 *
 * Existe porque `landing-evidence.ts` copia a mano ~15 números de `results-f1.json` —y lo hace por
 * una razón buena, escrita en su cabecera: importar el fixture de 160 KB metería la corrida entera
 * en el bundle de la primera pantalla—. Pero copiar a mano no tenía contrapeso: una recaptura de la
 * demo reescribe el fixture y **nada comprobaba que la landing siguiera diciendo la verdad**. La
 * página cuya tesis es «todo aquí se puede verificar» podía quedar mintiendo en silencio, que es
 * exactamente el modo de fallo que este repo persigue.
 *
 * Este test **no** contradice la decisión de no importar el fixture en producción: un test no se
 * bundlea. El costo del import vive aquí, no en la primera pantalla del usuario.
 *
 * Se verificó inyectando el defecto: mover un solo decil, un dígito de AUC o un conteo del pipeline
 * pone este archivo en rojo.
 */

/** Las cifras se publican en español («0,695»); el fixture las trae como float. */
function desdeTextoEsp(valor: string): number {
  return Number(valor.replace(",", "."))
}

/** `Number.toFixed` sobre el fixture, con el mismo redondeo que se usó al escribir la constante. */
function redondeado(valor: number, decimales: number): number {
  return Number(valor.toFixed(decimales))
}

const DECILES_HOLDOUT = resultsF1.performance.deciles
  .filter((fila) => fila.partition === "holdout")
  .sort((a, b) => a.decile - b.decile)

const DISCRIMINANTE_HOLDOUT = resultsF1.performance.discriminant.find(
  (fila) => fila.partition === "holdout",
)

describe("la evidencia de la landing se re-deriva del fixture de la corrida real", () => {
  it("no es un barrido vacío: el fixture trae las cuatro fuentes que este gate mide", () => {
    // Anti-tautología. Sin esto, un fixture que cambiara de forma dejaría los filtros en `[]` y
    // todos los `toEqual` de abajo pasarían comparando nada contra nada.
    expect(DECILES_HOLDOUT).toHaveLength(10)
    expect(DISCRIMINANTE_HOLDOUT).toBeDefined()
    expect(resultsF1.stability.max_psi_by_comparison.dev_vs_holdout).toBeTypeOf("number")
    expect(resultsF1.model.fit_statistics.n_obs_dev).toBeGreaterThan(0)
  })

  it("la curva de gains es la del holdout del fixture, decil a decil", () => {
    const delFixture = DECILES_HOLDOUT.map((fila) => ({
      decil: fila.decile,
      capturado: redondeado(fila.cum_bad_capture_rate * 100, 1),
    }))
    expect(GAINS_HOLDOUT).toEqual(delFixture)
  })

  it("AUC y KS son los del holdout, y el PSI es el de dev contra holdout", () => {
    const porClave = Object.fromEntries(METRICAS.map((m) => [m.clave, desdeTextoEsp(m.valor)]))
    expect(porClave.AUC).toBe(redondeado(DISCRIMINANTE_HOLDOUT!.auc, 3))
    expect(porClave.KS).toBe(redondeado(DISCRIMINANTE_HOLDOUT!.ks, 3))
    expect(porClave.PSI).toBe(
      redondeado(resultsF1.stability.max_psi_by_comparison.dev_vs_holdout, 3),
    )
    // La nota importa tanto como el número: un AUC de desarrollo publicado como «holdout» sería
    // la cifra buena en el sitio equivocado, que en riesgo se lee como sobrepromesa.
    expect(METRICAS.map((m) => m.nota)).toEqual(["holdout", "holdout", "dev vs holdout"])
  })

  it("los seis datos del pipeline salen de las cards de la misma corrida", () => {
    const porPaso = Object.fromEntries(PIPELINE.map((p) => [p.paso, p.dato]))
    const miles = (n: number) => n.toLocaleString("es-CL")

    const { n_obs_dev, n_events_dev } = resultsF1.model.fit_statistics
    expect(porPaso.Datos).toBe(`${miles(n_obs_dev)} obs · ${miles(n_events_dev)} eventos`)

    expect(porPaso.Binning).toBe(`${resultsF1.binning.n_variables_binned} variables`)

    const { n_candidates, n_selected } = resultsF1.selection
    expect(porPaso["Selección"]).toBe(`${n_candidates} → ${n_selected} variables`)

    expect(porPaso.Modelo).toBe(`${resultsF1.model.n_final_features} features finales`)

    const pdMedia = redondeado(resultsF1.calibration.calibrated_mean_pd_dev * 100, 1)
    expect(porPaso["Calibración"]).toBe(`PD media ${pdMedia.toFixed(1).replace(".", ",")} %`)

    const capitulos = CAPITULOS.filter((c) => /^\d+$/.test(c.n)).length
    const anexos = CAPITULOS.filter((c) => /^[A-Z]$/.test(c.n)).length
    expect(porPaso.Informe).toBe(`${capitulos} capítulos + ${anexos} anexos`)
  })

  it("los capítulos son los que el informe de esa corrida imprime, en su orden", () => {
    // El propio `landing-evidence.ts` avisa de que el 7 NO es constante del motor: `CHAPTER_SPECS`
    // emite capítulos condicionales y la numeración se reajusta sola. Por eso se lee del informe.
    const encabezados = [...reportF1Html.matchAll(/<h2[^>]*>(.*?)<\/h2>/gs)]
      .map(([, interior]) => interior.replace(/<[^>]+>/g, "").trim())
      .filter((titulo) => titulo !== "Índice")
    expect(encabezados.length).toBeGreaterThan(5)

    const publicados = CAPITULOS.map(({ n, titulo }) =>
      n === "—" ? titulo : /^\d+$/.test(n) ? `${n}${titulo}` : `Anexo ${n} —${titulo}`,
    )
    expect(publicados).toEqual(encabezados)
  })
})
