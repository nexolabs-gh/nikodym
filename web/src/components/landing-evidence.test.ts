import { describe, expect, it } from "vitest"

import landingLauncherFuente from "@/components/LandingLauncher.tsx?raw"
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
 *
 * ⚠️ Tres huecos que una revisión adversarial encontró y que quedaron cerrados aquí, porque los
 * tres compartían la misma forma —**el gate leía menos de lo que la landing pinta**—:
 *
 *  1. **`Object.fromEntries` PIERDE información.** Se queda con la última de dos claves iguales,
 *     mientras la página renderiza las dos. Medido: duplicar el paso «Datos» con
 *     `999.999 obs · 999.999 eventos` **delante** del bueno dejaba este archivo en verde. Por eso
 *     ahora la lista de claves se fija ENTERA —longitud, orden y conjunto— antes de reducir a mapa.
 *  2. **`CAPITULOS.tipo` no se comprobaba.** Cambiar Introducción a `"generado"` pasaba el gate, y
 *     eso publica «lo escribe el motor» sobre un capítulo que nace con bloque POR COMPLETAR.
 *  3. **El `aria-label` de la curva duplicaba el 21,3 % a mano**, sin que nada lo atara al primer
 *     decil. Es el número que oye quien usa lector de pantalla: el único de la página que podía
 *     quedar desfasado sin que se notara ni mirando la pantalla.
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

/**
 * El informe partido en capítulos, leído del HTML crudo (vitest corre en `node`, sin DOM).
 *
 * Cada `<h2>` abre un capítulo y su cuerpo es todo lo que va hasta el `<h2>` siguiente: las
 * subsecciones usan `<h3>`, así que no cortan. El primer trozo —portada y `<style>`— se descarta,
 * y con él la única mención de «POR COMPLETAR» que no es un bloque real (vive en un comentario
 * CSS).
 *
 * `editable` sale de un marcador que el propio documento imprime, no de una lista escrita al lado:
 *   - `<div class="placeholder">` es el bloque POR COMPLETAR que emite `ChapterSpec.placeholder_*`
 *     (`report/document.py`) — Introducción, Contexto, Validación formal y Conclusiones;
 *   - `<div class="verdict">` es el «Veredicto de validación» del resumen ejecutivo, que la propia
 *     plantilla rotula «Campo estructural… no es un resultado calculado por el motor»
 *     (`report/templates/_exec_summary.html.j2`).
 *
 * Se eligió el HTML y no el fuente Python de `ChapterSpec` por tres razones. Es **el artefacto que
 * la landing dice describir**, y ya era la fuente de los títulos, así que título y tipo se miden
 * contra lo mismo y una recaptura los mueve juntos. `ChapterSpec` está aguas arriba y emite
 * capítulos CONDICIONALES: cuáles trae ESTA corrida sólo lo sabe su informe. Y leer
 * `src/nikodym/report/` desde aquí cruzaría la raíz de vite (`web/`) por un dato que el fixture
 * ya trae.
 */
const CAPITULOS_DEL_INFORME = reportF1Html
  .split(/(?=<h2[\s>])/)
  .slice(1)
  .map((trozo) => {
    const encabezado = trozo.match(/^<h2[^>]*>(.*?)<\/h2>/s)
    const cuerpo = trozo.slice(trozo.indexOf("</h2>"))
    return {
      rotulo: (encabezado?.[1] ?? "").replace(/<[^>]+>/g, "").trim(),
      editable: /<div class="(?:placeholder|verdict)">/.test(cuerpo),
    }
  })
  .filter(({ rotulo }) => rotulo !== "Índice")

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

  it("el rótulo accesible de la curva cita el primer decil, no un número escrito a mano", () => {
    // El `aria-label` del SVG es la única cifra de la landing que vive FUERA de
    // `landing-evidence.ts` —medido: es el único literal con coma decimal o porcentaje en todo
    // `LandingLauncher.tsx`, que es la landing entera (`App.tsx:389`)—. Quien usa lector de
    // pantalla oye ese número y no ve la curva, así que copiado a mano podía quedar
    // contradiciendo al gráfico que describe sin que lo delataran ni el gate ni mirar la pantalla.
    const rotulos = [
      ...landingLauncherFuente.matchAll(/aria-label="([^"]*[Cc]urva de gains[^"]*)"/g),
    ].map(([, texto]) => texto)
    // Anti-tautología: si el rótulo se renombra o desaparece, este gate lo dice en vez de aprobar
    // una lista vacía.
    expect(rotulos).toHaveLength(1)
    const [rotulo] = rotulos

    // El texto afirma DOS cosas verificables además del número: de qué partición habla y que la
    // cifra es la del primer decil.
    expect(rotulo).toContain("holdout")
    expect(GAINS_HOLDOUT[0].decil).toBe(1)

    const esperado = GAINS_HOLDOUT[0].capturado.toFixed(1).replace(".", ",")
    // Se exige UNA sola cifra porcentual en el rótulo, y que sea ésa. Un porcentaje nuevo escrito
    // a mano ahí es exactamente el riesgo que este test existe para cazar, así que sumarlo tiene
    // que costar una decisión, no pasar en silencio.
    const porcentajes = [...rotulo.matchAll(/(\d+(?:,\d+)?)\s*%/g)].map(([, cifra]) => cifra)
    expect(porcentajes).toEqual([esperado])
  })

  it("AUC y KS son los del holdout, y el PSI es el de dev contra holdout", () => {
    // La lista de claves se fija ENTERA antes de reducir a mapa: `Object.fromEntries` conserva
    // sólo la última de dos claves iguales, así que una entrada duplicada —que la página SÍ
    // pintaría— desaparecería de todo lo que viene después. Fijarla asevera de una vez longitud,
    // orden y conjunto exacto. Los literales no son cifras medidas: son el contrato de qué
    // publica esta tarjeta, y eso el fixture no lo puede decir.
    expect(METRICAS.map((m) => m.clave)).toEqual(["AUC", "KS", "PSI"])

    const porClave = Object.fromEntries(METRICAS.map((m) => [m.clave, desdeTextoEsp(m.valor)]))
    expect(porClave.AUC).toBe(redondeado(DISCRIMINANTE_HOLDOUT!.auc, 3))
    expect(porClave.KS).toBe(redondeado(DISCRIMINANTE_HOLDOUT!.ks, 3))
    expect(porClave.PSI).toBe(
      redondeado(resultsF1.stability.max_psi_by_comparison.dev_vs_holdout, 3),
    )
    const psiGanadores = resultsF1.stability.stability_metrics.filter(
      (row) =>
        row.comparison === "dev_vs_holdout" &&
        (row.metric === "score_psi" || row.metric === "pd_psi") &&
        row.value !== null,
    )
    const ganador = psiGanadores.reduce((actual, candidato) =>
      candidato.value! > actual.value! ? candidato : actual,
    )
    expect(ganador.metric).toBe("pd_psi")
    expect(resultsF1.stability.max_psi_by_comparison.dev_vs_holdout).toBe(ganador.value)
    // La nota importa tanto como el número: un AUC de desarrollo publicado como «holdout» sería
    // la cifra buena en el sitio equivocado, que en riesgo se lee como sobrepromesa.
    expect(METRICAS.map((m) => m.nota)).toEqual([
      "holdout",
      "holdout",
      "PD · dev vs holdout",
    ])
  })

  it("los seis datos del pipeline salen de las cards de la misma corrida", () => {
    // Misma razón que en METRICAS, y aquí el hueco era real: duplicar «Datos» con una cifra
    // inflada delante del bueno dejaba este archivo en verde con los dos renderizados.
    expect(PIPELINE.map((p) => p.paso)).toEqual([
      "Datos",
      "Binning",
      "Selección",
      "Modelo",
      "Calibración",
      "Informe",
    ])
    // `n` es la numeración que se ve en la página: un paso repetido rompe también su rótulo.
    expect(PIPELINE.map((p) => p.n)).toEqual(["01", "02", "03", "04", "05", "06"])

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
    expect(CAPITULOS_DEL_INFORME.length).toBeGreaterThan(5)

    const publicados = CAPITULOS.map(({ n, titulo }) =>
      n === "—" ? titulo : /^\d+$/.test(n) ? `${n}${titulo}` : `Anexo ${n} —${titulo}`,
    )
    expect(publicados).toEqual(CAPITULOS_DEL_INFORME.map(({ rotulo }) => rotulo))
  })

  it("«lo escribes tú / lo escribe el motor» sale de los bloques que el informe imprime", () => {
    // `tipo` no es cosmético: `LandingLauncher` lo convierte en una promesa sobre quién firma cada
    // capítulo. Rotular «lo escribe el motor» un capítulo que nace con POR COMPLETAR promete un
    // entregable que el motor no entrega, y al revés esconde trabajo que el informe sí automatiza.
    //
    // Anti-tautología, y ancla de que el marcador se sigue imprimiendo: son los CUATRO
    // `ChapterSpec` con `placeholder_*` que esta corrida emite, más el veredicto del resumen
    // ejecutivo. Si el informe dejara de marcarlos, sin esto todo pasaría a «generado» en silencio.
    expect(reportF1Html.match(/<div class="placeholder">/g) ?? []).toHaveLength(4)
    expect(reportF1Html.match(/<div class="verdict">/g) ?? []).toHaveLength(1)

    // Se comparan pares «capítulo: tipo» y no dos listas de booleanos sueltas, para que el fallo
    // nombre el capítulo que quedó mal rotulado.
    const conRotulo = (rotulo: string, tipo: string) => `${rotulo}: ${tipo}`
    const publicados = CAPITULOS.map((c, i) =>
      conRotulo(CAPITULOS_DEL_INFORME[i]?.rotulo ?? "?", c.tipo),
    )
    const delInforme = CAPITULOS_DEL_INFORME.map(({ rotulo, editable }) =>
      conRotulo(rotulo, editable ? "editable" : "generado"),
    )
    expect(publicados).toEqual(delInforme)
  })
})
